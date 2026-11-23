#!/usr/bin/env python3
"""Tests for session_facts.py, the read-only counter behind the efficiency pass.

Fixture lines copy the FIELD NAMES and nesting of real Claude Code transcript lines (read
2026-11-23 from a real session: compact JSON, `type` assistant/user, tool_use blocks with
`id`/`name`/`input`, tool_result blocks with `tool_use_id`/`is_error`, `api-request-blob`
lines that repeat tool blocks, `system` `turn_duration` lines with `durationMs`). Content is
made up. No test reads a live transcript: those are deleted after 30 days.
"""
import json
import os
import re
import subprocess
import sys
import tempfile
import time
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPT = os.path.join(HERE, "session_facts.py")
ENC = "-Users-someone-work-proj"


def line(d):
    return json.dumps(d, separators=(",", ":"))


class Builder:
    """Builds one transcript from real-shaped lines."""

    def __init__(self, sid):
        self.sid = sid
        self.rows = [{"type": "agent-setting", "agentSetting": "claude", "sessionId": sid}]
        self.n = 0
        self.t = 1700000000

    def _ts(self):
        self.t += 7
        return time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime(self.t))

    def human(self, text):
        self.rows.append({"type": "user", "isSidechain": False, "sessionId": self.sid,
                          "timestamp": self._ts(), "origin": {"kind": "human"},
                          "message": {"role": "user", "content": text}})

    def call(self, name, inp, result="ok", is_error="absent", blob_copy=False):
        self.n += 1
        tid = "toolu_%04d" % self.n
        block = {"type": "tool_use", "id": tid, "name": name, "input": inp, "caller": {}}
        self.rows.append({"type": "assistant", "isSidechain": False, "sessionId": self.sid,
                          "timestamp": self._ts(),
                          "message": {"model": "m", "role": "assistant", "content": [block]}})
        if blob_copy:
            # Real api-request-blob lines carry earlier tool blocks again. Never counted.
            self.rows.append({"type": "api-request-blob", "sessionId": self.sid,
                              "blob": {"messages": [{"role": "assistant", "content": [block]}]}})
        res = {"type": "tool_result", "tool_use_id": tid, "content": result}
        if is_error != "absent":
            res["is_error"] = is_error
        self.rows.append({"type": "user", "isSidechain": False, "sessionId": self.sid,
                          "timestamp": self._ts(), "toolUseResult": {},
                          "message": {"role": "user", "content": [res]}})
        return tid

    def turn(self, ms):
        self.rows.append({"type": "system", "subtype": "turn_duration", "durationMs": ms,
                          "messageCount": 3, "sessionId": self.sid, "timestamp": self._ts()})

    def write(self, projects, enc=ENC):
        folder = os.path.join(projects, enc)
        os.makedirs(folder, exist_ok=True)
        path = os.path.join(folder, self.sid + ".jsonl")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write("\n".join(line(r) for r in self.rows) + "\n")
        return path


def run(args, env_sid=None, cwd=None):
    env = dict(os.environ)
    env.pop("CLAUDE_CODE_SESSION_ID", None)
    if env_sid:
        env["CLAUDE_CODE_SESSION_ID"] = env_sid
    p = subprocess.run([sys.executable, SCRIPT] + args, capture_output=True, text=True, env=env,
                       cwd=cwd)
    return p.returncode, p.stdout, p.stderr


def facts(projects, sid):
    code, out, err = run(["--projects-dir", projects, "--session", sid, "--json"])
    assert code == 0, (code, out, err)
    return json.loads(out)


class Identity(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        # The launch folder's own transcript folder, named the way Claude Code names it, so the
        # no-identity case runs where a "take the newest" fallback would find the decoy.
        self.work = os.path.realpath(tempfile.mkdtemp())
        enc = re.sub(r"[^A-Za-z0-9]", "-", self.work)
        mine = Builder("aaaaaaaa-0000-0000-0000-000000000001")
        mine.human("do the thing")
        self.mine = mine.write(self.tmp, enc)
        decoy = Builder("bbbbbbbb-0000-0000-0000-000000000002")
        decoy.human("someone else")
        self.decoy = decoy.write(self.tmp, enc)
        later = time.time() + 100
        os.utime(self.decoy, (later, later))  # the decoy is the NEWEST file in the folder

    def test_no_identity_refuses_and_never_picks_the_newest(self):
        code, out, err = run(["--projects-dir", self.tmp], cwd=self.work)
        self.assertEqual(code, 2)
        self.assertIn("no transcript identity", out + err)
        # It saw the decoy (so the fallback had something to pick) and named it unpicked.
        self.assertIn("candidate (not picked): " + self.decoy, out)
        self.assertNotIn('"transcript"', out)  # nothing was read

    def test_session_id_picks_its_own_file_not_the_newer_decoy(self):
        d = facts(self.tmp, "aaaaaaaa-0000-0000-0000-000000000001")
        self.assertEqual(d["transcript"], self.mine)

    def test_env_session_id_is_used(self):
        code, out, err = run(["--projects-dir", self.tmp, "--json"],
                             env_sid="aaaaaaaa-0000-0000-0000-000000000001")
        self.assertEqual(code, 0, err)
        self.assertEqual(json.loads(out)["transcript"], self.mine)

    def test_unknown_session_refuses(self):
        code, out, err = run(["--projects-dir", self.tmp, "--session", "cccccccc-dead"])
        self.assertEqual(code, 2)
        self.assertIn("no transcript", out + err)


class Counts(unittest.TestCase):
    SID = "dddddddd-0000-0000-0000-000000000004"

    def build(self, fill):
        tmp = tempfile.mkdtemp()
        b = Builder(self.SID)
        b.human("goal")
        fill(b)
        b.write(tmp)
        return facts(tmp, self.SID)

    def test_blob_lines_are_not_counted(self):
        d = self.build(lambda b: b.call("Bash", {"command": "ls"}, blob_copy=True))
        self.assertEqual(d["tool_calls"], {"Bash": 1})

    def test_is_error_absent_or_false_is_not_a_failure(self):
        def fill(b):
            b.call("Bash", {"command": "a"})
            b.call("Bash", {"command": "b"}, is_error=False)
            b.call("Bash", {"command": "c"}, is_error=True)
        self.assertEqual(self.build(fill)["failed_calls"], {"Bash": 1})

    def test_unchanged_retry_is_told_apart_from_retry_after_an_edit(self):
        def fill(b):
            b.call("Bash", {"command": "make build"}, "boom", is_error=True)
            b.call("Bash", {"command": "make build"}, "boom", is_error=True)
            b.call("Bash", {"command": "pytest x"}, "red", is_error=True)
            b.call("Edit", {"file_path": "/r/x.py", "old_string": "a", "new_string": "b"})
            b.call("Bash", {"command": "pytest x"}, "red", is_error=True)
        d = self.build(fill)
        unchanged = [r["command"] for r in d["failed_again_no_edit_seen"]]
        self.assertEqual(unchanged, ["make build"])

    def test_quiet_session_prints_zeros(self):
        def fill(b):
            b.call("Bash", {"command": "ls"})
            b.call("Read", {"file_path": "/r/a.py"})
            b.call("Bash", {"command": "git status"})
        d = self.build(fill)
        self.assertEqual(d["repeated_commands"], [])
        self.assertEqual(d["failed_again_no_edit_seen"], [])
        self.assertEqual(d["files_read_3_plus"], [])
        self.assertEqual(d["suite_runs"]["repeated_no_edit_seen"], [])

    def test_repeated_reads_say_whether_an_edit_sat_between(self):
        def fill(b):
            for _ in range(3):
                b.call("Read", {"file_path": "/r/same.py"})
            b.call("Read", {"file_path": "/r/edited.py"})
            b.call("Edit", {"file_path": "/r/edited.py", "old_string": "a", "new_string": "b"})
            b.call("Read", {"file_path": "/r/edited.py"})
            b.call("Read", {"file_path": "/r/edited.py"})
        rows = {r["path"]: r for r in self.build(fill)["files_read_3_plus"]}
        self.assertEqual(rows["/r/same.py"]["reads"], 3)
        self.assertFalse(rows["/r/same.py"]["edit_between"])
        self.assertTrue(rows["/r/edited.py"]["edit_between"])

    def test_suite_rerun_with_no_edit_is_named(self):
        def fill(b):
            b.call("Bash", {"command": "python3 run_tests.py"})
            b.call("Bash", {"command": "python3 run_tests.py"})
            b.call("Bash", {"command": "python3 -m pytest tests"})
            b.call("Write", {"file_path": "/r/new.py", "content": "x"})
            b.call("Bash", {"command": "python3 -m pytest tests"})
        s = self.build(fill)["suite_runs"]
        self.assertEqual(s["count"], 4)
        self.assertEqual(s["repeated_no_edit_seen"], ["python3 run_tests.py"])

    def test_a_search_naming_a_test_file_is_not_a_suite_run(self):
        def fill(b):
            b.call("Bash", {"command": "cd /r && python3 -m pytest tests"})
            b.call("Bash", {"command": "cd /r; grep -rl run_tests.py ."})
            b.call("Bash", {"command": "git log -- test_x.py"})
            b.call("Bash", {"command": "python3 - <<'EOF'\nopen('test_x.py').read()\nEOF"})
            b.call("Bash", {"command": "python3 - <<'EOF'\nprint(1)\nEOF\npython3 test_y.py"})
        s = self.build(fill)["suite_runs"]
        self.assertEqual(s["count"], 2)
        self.assertEqual(s["commands"][0], "python3 -m pytest tests")

    def test_helpers_web_questions_and_turn_time(self):
        def fill(b):
            b.call("Agent", {"description": "map", "prompt": "p", "subagent_type": "Explore"})
            b.call("WebSearch", {"query": "q"})
            b.call("AskUserQuestion", {"questions": []})
            b.turn(60000)
            b.turn(30000)
        d = self.build(fill)
        self.assertEqual(d["helpers"], [{"type": "Explore", "description": "map"}])
        self.assertEqual(d["web"], {"WebSearch": 1, "WebFetch": 0})
        self.assertEqual(d["questions_asked"], 1)
        self.assertEqual(d["active_turn_ms"], 90000)

    def test_compaction_is_reported_as_unknown_not_zero(self):
        d = self.build(lambda b: None)
        self.assertNotIn("compactions", d)
        self.assertIn("cannot tell", d["compaction"])


def sidecar(b, row):
    b.rows.append(row)


class Round1Fixes(unittest.TestCase):
    """One test per finding of the 2026-11-23 review round (REVIEW_FINDINGS.md ids)."""
    SID = "abababab-0000-0000-0000-000000000005"

    def build(self, fill):
        tmp = tempfile.mkdtemp()
        b = Builder(self.SID)
        b.human("goal")
        fill(b)
        self.path = b.write(tmp)
        self.tmp = tmp
        return facts(tmp, self.SID)

    def test_cr1_an_edit_after_the_last_read_is_not_between(self):
        def fill(b):
            for _ in range(3):
                b.call("Read", {"file_path": "/r/a.py"})
            b.call("Edit", {"file_path": "/r/a.py", "old_string": "x", "new_string": "y"})
        rows = self.build(fill)["files_read_3_plus"]
        self.assertEqual(rows, [{"path": "/r/a.py", "reads": 3, "edit_between": False}])

    def test_cr3_a_failed_edit_is_not_a_change(self):
        def fill(b):
            b.call("Bash", {"command": "make"}, "boom", is_error=True)
            b.call("Edit", {"file_path": "/r/a.py", "old_string": "x", "new_string": "y"},
                   "String to replace not found", is_error=True)
            b.call("Bash", {"command": "make"}, "boom", is_error=True)
        self.assertEqual(self.build(fill)["failed_again_no_edit_seen"], [{"command": "make"}])

    def test_cx6_spacing_inside_a_command_keeps_two_commands_apart(self):
        def fill(b):
            b.call("Bash", {"command": "build --v 'a  b'"}, "x", is_error=True)
            b.call("Bash", {"command": "build --v 'a b'"}, "x", is_error=True)
        d = self.build(fill)
        self.assertEqual(d["failed_again_no_edit_seen"], [])
        self.assertEqual(d["repeated_commands"], [])

    def test_cx9_each_test_run_in_one_call_counts(self):
        s = self.build(lambda b: b.call("Bash", {"command": "pytest; pytest; pytest"}))["suite_runs"]
        self.assertEqual(s["count"], 3)
        self.assertEqual(s["repeated_no_edit_seen"], ["pytest"])

    def test_cr2_cx7_only_a_runner_at_the_start_is_a_test_run(self):
        not_runs = ["rm test_x.py", "mv test_a.py test_b.py", "pip install pytest",
                    "ruff check test_x.py", "python3 -m py_compile test_x.py",
                    "echo '|' pytest", "python3 -c 'print(\"pytest\")'", "cat run_tests.py"]
        runs = ["python3 -m unittest", "npm run test", "go test ./...", "time pytest -q",
                "cd /r && python3 run_tests.py", "/usr/bin/python3 -I tests/test_a.py"]

        def fill(b):
            for c in not_runs + runs:
                b.call("Bash", {"command": c})
        s = self.build(fill)["suite_runs"]
        self.assertEqual(s["count"], len(runs), s["commands"])

    def test_cx8_heredoc_names_with_a_dash_and_two_bodies(self):
        def fill(b):
            b.call("Bash", {"command": "cat <<'PY-END'\npytest\nPY-END\npytest -q"})
            b.call("Bash", {"command": "cat <<A <<B\nx\nA\npytest\nB\necho done"})
        self.assertEqual(self.build(fill)["suite_runs"]["commands"], ["pytest -q"])

    def test_cx10_every_counted_command_is_kept(self):
        def fill(b):
            for i in range(13):
                b.call("Bash", {"command": "pytest -k case%d" % i})
        d = self.build(fill)
        self.assertEqual(len(d["suite_runs"]["commands"]), 13)
        code, out, err = run(["--projects-dir", self.tmp, "--session", self.SID])
        self.assertEqual(code, 0, err)
        self.assertIn("... and 1 more (see --json)", out)

    def test_cx12_finish_notices_are_counted_by_task_id(self):
        def fill(b):
            b.call("Bash", {"command": "sleep 5", "run_in_background": True})
            b.call("Agent", {"description": "map", "prompt": "p", "subagent_type": "Explore"})
            for tid in ("t1", "t1", "t2"):
                sidecar(b, {"type": "attachment", "sessionId": self.SID, "attachment": {
                    "type": "queued_command",
                    "prompt": "<task-notification>\n<task-id>%s</task-id>\n</task-notification>" % tid}})
        self.assertEqual(self.build(fill)["background"],
                         {"bash_launched": 1, "helpers_launched": 1, "finish_notices_seen": 2})

    def test_cr7_odd_lines_are_skipped_not_fatal(self):
        def fill(b):
            odd = [[1, 2], "row", {"type": "user", "origin": "str", "message": "s"},
                   {"type": "system", "subtype": "turn_duration", "durationMs": "12.5"},
                   {"type": "assistant", "message": {"content": [
                       {"type": "tool_use", "name": "Bash", "input": {"command": "x"}},
                       {"type": "tool_use", "id": "z1", "name": "Bash", "input": "oops"},
                       {"type": "tool_use", "id": "z2", "name": "Bash", "input": {"command": ["a"]}},
                       {"type": "tool_use", "id": "z3", "name": "Agent", "input": {"description": None}},
                       {"type": "text", "text": None}]}},
                   {"type": "user", "message": {"content": [
                       {"type": "tool_result", "tool_use_id": "z1", "content": [{"text": None}]}]}}]
            for row in odd:
                sidecar(b, row)
            b.call("Bash", {"command": "ls"})
        d = self.build(fill)
        self.assertEqual(d["tool_calls"], {"Bash": 3, "Agent": 1})
        self.assertEqual(d["active_turn_ms"], 12)

    def test_cr8_a_session_id_with_a_path_is_refused(self):
        tmp = tempfile.mkdtemp()
        code, out, err = run(["--projects-dir", tmp, "--session", "../../tmp/x"])
        self.assertEqual(code, 2)
        self.assertIn("is not a session id", out)

    def test_cx11_a_candidate_that_vanishes_is_not_fatal(self):
        sys.path.insert(0, HERE)
        import session_facts as F
        real = F.glob.glob
        saved = os.environ.pop("CLAUDE_CODE_SESSION_ID", None)  # the real session's id
        try:
            F.glob.glob = lambda pattern: ["/nonexistent/gone.jsonl"]
            got = F.resolve(F.argparse.Namespace(transcript=None, session=None,
                                                 projects_dir="/nonexistent"))
        finally:
            F.glob.glob = real
            if saved is not None:
                os.environ["CLAUDE_CODE_SESSION_ID"] = saved
        self.assertIsNone(got[0])
        self.assertEqual(got[2], ["/nonexistent/gone.jsonl"])

    def test_cr9_images_count_and_paged_reads_stay_apart(self):
        def fill(b):
            b.call("Read", {"file_path": "/r/shot.png"},
                   [{"type": "image", "source": {"type": "base64", "data": "A" * 5000}}])
            for off in (1, 2000, 4000):
                b.call("Read", {"file_path": "/r/big.py", "offset": off, "limit": 2000})
        d = self.build(fill)
        self.assertEqual(d["largest_results"][0]["chars"], 5000)
        self.assertEqual(d["files_read_3_plus"], [])


class Fields(unittest.TestCase):
    """Fields that had no test (CR10)."""
    SID = "cdcdcdcd-0000-0000-0000-000000000006"

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        b = Builder(self.SID)
        b.human("goal")
        b.call("Bash", {"command": "git status"})
        b.call("Bash", {"command": "git status"})
        sidecar(b, {"type": "assistant", "isSidechain": True, "sessionId": self.SID,
                    "message": {"content": [{"type": "tool_use", "id": "side1", "name": "Bash",
                                             "input": {"command": "git status"}}]}})
        sidecar(b, {"type": "user", "sessionId": self.SID, "timestamp": "2030-01-01T00:00:00.000Z",
                    "origin": {"kind": "peer"}, "message": {"content": "report"}})
        b.human("next")
        self.path = b.write(self.tmp)
        os.makedirs(os.path.join(self.tmp, ENC, self.SID, "subagents"))
        self.helper = os.path.join(self.tmp, ENC, self.SID, "subagents", "agent-a1.jsonl")
        open(self.helper, "w").close()

    def test_counts_people_helpers_repeats_and_times(self):
        d = facts(self.tmp, self.SID)
        self.assertEqual(d["messages_from_eran"], 2)
        self.assertEqual(d["helper_handbacks"], 1)
        self.assertEqual(d["repeated_commands"], [{"command": "git status", "runs": 2}])
        self.assertEqual(d["tool_calls"], {"Bash": 2})  # the sidechain call is skipped
        self.assertEqual(d["helper_transcripts"], [self.helper])
        self.assertTrue(d["first_utc"].startswith("2023-"))
        self.assertGreater(d["last_utc"], d["first_utc"])

    def test_transcript_path_and_plain_text_output(self):
        code, out, err = run(["--transcript", self.path])
        self.assertEqual(code, 0, err)
        self.assertIn("repeated_commands:", out)
        self.assertIn("messages_from_eran: 2", out)

    def test_two_transcripts_for_one_id_are_refused(self):
        other = os.path.join(self.tmp, "-other-folder")
        os.makedirs(other)
        open(os.path.join(other, self.SID + ".jsonl"), "w").close()
        code, out, err = run(["--projects-dir", self.tmp, "--session", self.SID])
        self.assertEqual(code, 2)
        self.assertIn("matches 2 transcripts", out)


if __name__ == "__main__":
    unittest.main()
