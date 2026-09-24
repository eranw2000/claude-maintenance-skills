#!/usr/bin/env python3
"""Tests for find_session_scripts.py, over small hand-built transcripts.

Run: /usr/bin/python3 test_find_session_scripts.py
"""
import contextlib
import importlib.util
import io
import json
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
_spec = importlib.util.spec_from_file_location("fss", HERE / "find_session_scripts.py")
fss = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(fss)


# ---- transcript builders -------------------------------------------------

def _rec(role, content, ts="2026-09-19T10:00:00.000Z", sidechain=False):
    return {"type": role, "isSidechain": sidechain, "timestamp": ts,
            "message": {"role": role, "content": content}}


def skill_call(name, **kw):
    return _rec("assistant", [{"type": "tool_use", "id": "s-" + name,
                               "name": "Skill", "input": {"skill": name}}], **kw)


def typed_command(name, **kw):
    return _rec("user", f"<command-message>{name}</command-message>"
                        f"<command-name>/{name}</command-name>", **kw)


def write(path, content, **kw):
    return _rec("assistant", [{"type": "tool_use", "id": "w-" + path, "name": "Write",
                               "input": {"file_path": path, "content": content}}], **kw)


def edit(path, **kw):
    return _rec("assistant", [{"type": "tool_use", "id": "e-" + path, "name": "Edit",
                               "input": {"file_path": path, "old_string": "a",
                                         "new_string": "b"}}], **kw)


def bash(cmd, tid, **kw):
    return _rec("assistant", [{"type": "tool_use", "id": tid, "name": "Bash",
                               "input": {"command": cmd}}], **kw)


def result(tid, is_error=False, **kw):
    return _rec("user", [{"type": "tool_result", "tool_use_id": tid,
                          "content": "x", "is_error": is_error}], **kw)


class Base(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.tmp = Path(self._td.name)

    def tearDown(self):
        self._td.cleanup()

    def transcript(self, recs, name="t.jsonl", raw_lines=()):
        p = self.tmp / name
        with open(p, "w", encoding="utf-8") as fh:
            for line in raw_lines:
                fh.write(line + "\n")
            for r in recs:
                fh.write(json.dumps(r) + "\n")
        return p

    def script_file(self, name, text="#!/usr/bin/env python3\nprint('hi')\n"):
        p = self.tmp / name
        p.write_text(text, encoding="utf-8")
        return str(p)

    def run_main(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with mock.patch("sys.argv", ["fss", *argv]), \
                contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            rc = fss.main()
        return rc, out.getvalue(), err.getvalue()


# ---- scan ------------------------------------------------------------------

class ScanTests(Base):
    def test_file_written_then_run_is_one_candidate_read_from_disk(self):
        path = self.script_file("build.py", "#!/usr/bin/env python3\nprint('disk')\n")
        t = self.transcript([skill_call("todo"), write(path, "print('transcript')\n"),
                             bash(f"python3 {path} --x 1", "b1"), result("b1")])
        skill, cands = fss.scan(t, None)
        self.assertEqual(skill, "todo")
        self.assertEqual(len(cands), 1)
        c = cands[0]
        self.assertEqual((c["kind"], c["path"], c["runs"], c["failed_runs"]),
                         ("file", path, 1, 0))
        self.assertTrue(c["on_disk"])
        self.assertIn("disk", c["source"])          # disk beats transcript copy
        self.assertEqual(c["lines"], 2)

    def test_failed_run_is_counted(self):
        path = self.script_file("a.sh")
        t = self.transcript([skill_call("x"), write(path, "echo"),
                             bash(f"bash {path}", "b1"), result("b1", is_error=True),
                             bash(f"bash {path}", "b2"), result("b2")])
        c = fss.scan(t, None)[1][0]
        self.assertEqual((c["runs"], c["failed_runs"]), (2, 1))

    def test_run_before_its_result_arrives_counts_as_not_failed(self):
        path = self.script_file("a.py")
        t = self.transcript([skill_call("x"), write(path, "p"), bash(f"python3 {path}", "b1")])
        c = fss.scan(t, None)[1][0]
        self.assertEqual((c["runs"], c["failed_runs"]), (1, 0))

    def test_typed_slash_command_counts_as_skill_invocation(self):
        path = self.script_file("a.py")
        t = self.transcript([typed_command("save-context"), write(path, "p")])
        skill, cands = fss.scan(t, None)
        self.assertEqual(skill, "save-context")
        self.assertEqual(len(cands), 1)

    def test_command_tag_in_assistant_text_is_not_an_invocation(self):
        t = self.transcript([_rec("assistant", [{"type": "text",
                             "text": "<command-name>/todo</command-name>"}])])
        self.assertEqual(fss.scan(t, None), (None, []))

    def test_last_skill_wins_and_earlier_scripts_are_excluded(self):
        early, late = self.script_file("early.py"), self.script_file("late.py")
        t = self.transcript([skill_call("one"), write(early, "p"),
                             skill_call("two"), write(late, "p")])
        skill, cands = fss.scan(t, None)
        self.assertEqual(skill, "two")
        self.assertEqual([c["path"] for c in cands], [late])

    def test_want_skill_picks_that_skills_last_invocation(self):
        a, b = self.script_file("a.py"), self.script_file("b.py")
        t = self.transcript([skill_call("one"), write(a, "p"),
                             skill_call("two"), write(b, "p")])
        skill, cands = fss.scan(t, "one")
        self.assertEqual(skill, "one")
        self.assertEqual([c["path"] for c in cands], [a, b])

    def test_want_skill_never_invoked_returns_none(self):
        t = self.transcript([skill_call("one")])
        self.assertEqual(fss.scan(t, "nope"), (None, []))

    def test_no_skill_at_all_returns_none(self):
        t = self.transcript([write(self.script_file("a.py"), "p")])
        self.assertEqual(fss.scan(t, None), (None, []))

    def test_non_script_extension_is_ignored(self):
        md = self.script_file("notes.md", "# hi")
        t = self.transcript([skill_call("x"), write(md, "# hi")])
        self.assertEqual(fss.scan(t, None)[1], [])

    def test_every_script_extension_is_accepted(self):
        recs = [skill_call("x")]
        for ext in fss.SCRIPT_EXT:
            recs.append(write(self.script_file("f" + ext), "p"))
        self.assertEqual(len(fss.scan(self.transcript(recs), None)[1]), len(fss.SCRIPT_EXT))

    def test_edit_and_multiedit_make_a_candidate_read_from_disk(self):
        a = self.script_file("a.py", "one\ntwo\nthree\n")
        b = self.script_file("b.py")
        me = _rec("assistant", [{"type": "tool_use", "id": "m", "name": "MultiEdit",
                                 "input": {"file_path": b, "edits": []}}])
        cands = fss.scan(self.transcript([skill_call("x"), edit(a), me]), None)[1]
        self.assertEqual([c["path"] for c in cands], [a, b])
        self.assertEqual(cands[0]["lines"], 3)
        self.assertTrue(all(c["on_disk"] for c in cands))

    def test_rewrite_of_same_path_is_one_candidate_with_latest_content(self):
        gone = str(self.tmp / "gone.py")                     # never on disk
        t = self.transcript([skill_call("x"), write(gone, "v1\n"), write(gone, "v2\n")])
        cands = fss.scan(t, None)[1]
        self.assertEqual(len(cands), 1)
        self.assertEqual(cands[0]["source"], "v2\n")

    def test_edit_after_write_keeps_the_written_content_when_file_is_gone(self):
        gone = str(self.tmp / "gone.py")
        t = self.transcript([skill_call("x"), write(gone, "v1\n"), edit(gone)])
        c = fss.scan(t, None)[1][0]
        self.assertEqual((c["source"], c["on_disk"]), ("v1\n", False))

    def test_deleted_file_falls_back_to_transcript_content(self):
        gone = str(self.tmp / "gone.py")
        c = fss.scan(self.transcript([skill_call("x"), write(gone, "a\nb\n")]), None)[1][0]
        self.assertFalse(c["on_disk"])
        self.assertEqual((c["source"], c["lines"]), ("a\nb\n", 2))

    def test_inline_heredoc_and_dash_c_are_candidates(self):
        t = self.transcript([skill_call("x"),
                             bash("python3 - <<'EOF'\nprint(1)\nEOF", "b1"), result("b1"),
                             bash("python3 -c 'print(2)'", "b2"), result("b2", is_error=True),
                             bash("node <<EOF\nconsole.log(1)\nEOF", "b3")])
        cands = fss.scan(t, None)[1]
        self.assertEqual([c["kind"] for c in cands], ["inline"] * 3)
        self.assertEqual([c["failed_runs"] for c in cands], [0, 1, 0])
        self.assertIsNone(cands[0]["path"])
        self.assertFalse(cands[0]["on_disk"])

    def test_plain_commands_are_not_candidates(self):
        t = self.transcript([skill_call("x"), bash("ls -la", "b1"),
                             bash("git status", "b2"), bash("cat <<EOF > f.txt\nhi\nEOF", "b3")])
        self.assertEqual(fss.scan(t, None)[1], [])

    def test_bash_running_a_known_file_is_a_run_not_an_inline_candidate(self):
        path = self.script_file("tool.py")
        t = self.transcript([skill_call("x"), write(path, "p"),
                             bash("python3 -c 'import x' && python3 tool.py", "b1")])
        cands = fss.scan(t, None)[1]
        self.assertEqual(len(cands), 1)
        self.assertEqual(cands[0]["runs"], 1)

    def test_bash_before_the_file_is_written_does_not_count(self):
        path = self.script_file("tool.py")
        t = self.transcript([skill_call("x"), bash("ls tool.py", "b1"), write(path, "p")])
        self.assertEqual(fss.scan(t, None)[1][0]["runs"], 0)

    def test_sidechain_records_are_ignored(self):
        path = self.script_file("a.py")
        t = self.transcript([skill_call("x"), write(path, "p", sidechain=True),
                             skill_call("sub", sidechain=True)])
        self.assertEqual(fss.scan(t, None), ("x", []))

    def test_malformed_lines_are_skipped(self):
        path = self.script_file("a.py")
        t = self.transcript([skill_call("x"), write(path, "p")],
                            raw_lines=["{not json", "", "[1, 2]"])
        self.assertEqual(len(fss.scan(t, None)[1]), 1)

    def test_record_without_message_is_skipped(self):
        t = self.transcript([{"type": "summary", "summary": "x"}, skill_call("x")])
        self.assertEqual(fss.scan(t, None), ("x", []))


# ---- resolve_skill_dir / default_transcript ----------------------------------

class PathTests(Base):
    def test_plugin_skill_is_refused(self):
        d, why = fss.resolve_skill_dir("hookify:help", str(self.tmp))
        self.assertIsNone(d)
        self.assertIn("plugin", why)

    def test_project_skill_beats_home_skill(self):
        home, cwd = self.tmp / "home", self.tmp / "proj"
        for base in (home / ".claude", cwd / ".claude"):
            (base / "skills" / "s").mkdir(parents=True)
            (base / "skills" / "s" / "SKILL.md").write_text("x")
        with mock.patch.dict(os.environ, {"HOME": str(home)}):
            d, why = fss.resolve_skill_dir("s", str(cwd))
        self.assertEqual((d, why), (cwd / ".claude" / "skills" / "s", None))

    def test_home_skill_found_when_project_has_none(self):
        home = self.tmp / "home"
        (home / ".claude" / "skills" / "s").mkdir(parents=True)
        (home / ".claude" / "skills" / "s" / "SKILL.md").write_text("x")
        with mock.patch.dict(os.environ, {"HOME": str(home)}):
            d, _ = fss.resolve_skill_dir("s", str(self.tmp / "nowhere"))
        self.assertEqual(d, home / ".claude" / "skills" / "s")

    def test_dir_without_skill_md_is_not_found(self):
        home = self.tmp / "home"
        (home / ".claude" / "skills" / "s").mkdir(parents=True)
        with mock.patch.dict(os.environ, {"HOME": str(home)}):
            d, why = fss.resolve_skill_dir("s", str(self.tmp))
        self.assertIsNone(d)
        self.assertIn("no SKILL.md", why)

    def test_default_transcript_encodes_cwd_and_picks_newest(self):
        home = self.tmp / "home"
        cwd = "/home/me/.claude/projects/my_proj"
        d = home / ".claude" / "projects" / "-home-me--claude-projects-my-proj"
        d.mkdir(parents=True)
        old, new = d / "old.jsonl", d / "new.jsonl"
        old.write_text("")
        new.write_text("")
        now = time.time()
        os.utime(old, (now - 100, now - 100))
        os.utime(new, (now, now))
        (d / "newer.txt").write_text("")                    # not a transcript
        with mock.patch.dict(os.environ, {"HOME": str(home)}):
            self.assertEqual(fss.default_transcript(cwd), new)

    def test_default_transcript_none_when_no_folder(self):
        with mock.patch.dict(os.environ, {"HOME": str(self.tmp)}):
            self.assertIsNone(fss.default_transcript("/no/such/dir"))


# ---- main ----------------------------------------------------------------------

class MainTests(Base):
    def setUp(self):
        super().setUp()
        self.path = self.script_file("tool.py", "#!/usr/bin/env python3\nprint('x')\n")
        self.t = self.transcript([skill_call("todo"), write(self.path, "p"),
                                  bash(f"python3 {self.path}", "b1"), result("b1")])

    def test_missing_transcript_exits_2(self):
        rc, _, err = self.run_main("--transcript", str(self.tmp / "none.jsonl"))
        self.assertEqual(rc, 2)
        self.assertIn("no transcript", err)

    def test_no_transcript_folder_for_cwd_exits_2(self):
        with mock.patch.dict(os.environ, {"HOME": str(self.tmp)}):
            rc, _, _ = self.run_main("--cwd", str(self.tmp / "x"))
        self.assertEqual(rc, 2)

    def test_no_skill_exits_3(self):
        t = self.transcript([write(self.path, "p")], name="noskill.jsonl")
        rc, _, err = self.run_main("--transcript", str(t))
        self.assertEqual(rc, 3)
        self.assertIn("no skill invocation", err)

    def test_listing(self):
        rc, out, _ = self.run_main("--transcript", str(self.t), "--cwd", str(self.tmp))
        self.assertEqual(rc, 0)
        self.assertIn("skill:      todo", out)
        self.assertIn("candidates: 1", out)
        self.assertIn(f" 1. {self.path}  [2 lines, runs 1, failed 0, on disk,", out)
        self.assertIn("#!/usr/bin/env python3", out)

    def test_listing_shows_why_skill_dir_is_missing(self):
        with mock.patch.dict(os.environ, {"HOME": str(self.tmp)}):
            _, out, _ = self.run_main("--transcript", str(self.t), "--cwd", str(self.tmp))
        self.assertIn("skill dir:  -- no SKILL.md", out)

    def test_show_prints_full_source(self):
        rc, out, _ = self.run_main("--transcript", str(self.t), "--show", "1")
        self.assertEqual((rc, out), (0, "#!/usr/bin/env python3\nprint('x')\n\n"))

    def test_show_out_of_range_exits_4(self):
        for n in ("0", "2"):
            rc, _, err = self.run_main("--transcript", str(self.t), "--show", n)
            self.assertEqual(rc, 4, n)
            self.assertIn("1..1", err)

    def test_json_output(self):
        rc, out, _ = self.run_main("--transcript", str(self.t), "--json")
        self.assertEqual(rc, 0)
        data = json.loads(out)
        self.assertEqual(data["skill"], "todo")
        self.assertEqual(data["transcript"], str(self.t))
        self.assertEqual(data["candidates"][0]["path"], self.path)
        self.assertEqual(data["candidates"][0]["runs"], 1)

    def test_skill_flag_is_passed_through(self):
        rc, _, _ = self.run_main("--transcript", str(self.t), "--skill", "other")
        self.assertEqual(rc, 3)


if __name__ == "__main__":
    unittest.main(verbosity=1)
