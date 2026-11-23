#!/usr/bin/env python3
"""Count what one Claude Code session did, from its own transcript. Read-only; facts, no verdicts.

The efficiency pass of /improve-dev-workflow (reference/1-efficiency-pass.md) reads these
counts so every cost in a finding is a number, not a memory. Nothing gates on this output.

Identity: --transcript PATH, or --session ID, or $CLAUDE_CODE_SESSION_ID, resolved as
<projects>/*/<ID>.jsonl. With none of them it stops with "no transcript identity" and lists
candidates. It never takes the newest file: in a folder two sessions share, the newest is
routinely the other session's. --projects-dir moves the lookup root (tests use it).

Transcript shapes this script reads: only `assistant` and `user` lines are counted
(`api-request-blob` lines repeat earlier tool blocks); `is_error` is absent, false or true;
`system` `turn_duration` lines carry `durationMs`; finish notices arrive in `attachment`
lines of type `queued_command`; helper transcripts sit in <session>/subagents/agent-*.jsonl.
A compaction leaves no record this script reads, so it is not counted.
A line of an odd shape is skipped, never fatal.

Exit 0 printed, 2 no identity or unreadable.
"""
import argparse
import glob
import json
import os
import re
import sys
from collections import Counter, OrderedDict

HERE = os.path.dirname(os.path.abspath(__file__))


def iter_rows(path):
    """Yield every parsable JSON line of a transcript. A malformed line is skipped, never fatal."""
    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except ValueError:
                continue


EDIT_TOOLS = ("Edit", "Write", "NotebookEdit", "MultiEdit")
SID_RE = re.compile(r"^[0-9A-Za-z][0-9A-Za-z-]{0,80}$")
NOTICE_RE = re.compile(r"<task-notification>.*?<task-id>([^<\s]+)</task-id>", re.S)
COMPACTION_NOTE = ("cannot tell from the file: a compaction leaves no record this script reads. "
                   "If your context starts from a summary, say so.")
LIMITS = ("An edit made by a shell command or git is not seen, so 'no edit seen' is not 'nothing "
          "changed'. A test run is a command that STARTS with a known runner (see is_test_run); "
          "a line holding a quote mark is read only at its start, and a loop over test files is "
          "not counted. Helper transcripts are listed, not counted. A compaction cannot be seen.")
LABEL = 90
SHOW_MAX = 12

# A test run is the smallest shape real use needs: the command's first word is a runner.
# Nothing else is parsed (no quote tracking): a reader of shell text grows holes each review.
RUNNERS = ("pytest", "py.test")
PYTHON = re.compile(r"^(?:.*/)?python(?:\d+(?:\.\d+)?)?$")
TEST_SCRIPT = re.compile(r"(?:^|/)(?:test_\w*\.py|run_tests\.py|run_evals\.py)$")
TOOL_TEST = ("go", "cargo", "dotnet", "mvn", "gradle", "gradlew")
CD_STEP = re.compile(r"^(?:cd\s+\S+\s*(?:;|&&)\s*)+")
HEREDOC = re.compile(r"<<-?\s*(['\"]?)([A-Za-z0-9_.-]+)\1")


def text_of(v):
    return v if isinstance(v, str) else ""


def label(s):
    return " ".join(text_of(s).split())[:LABEL]


def command_lines(raw):
    """The command's shell lines, with every heredoc body left out (a body is only text)."""
    out, pending = [], []
    for ln in text_of(raw).split("\n"):
        if pending:
            if ln.strip() == pending[0]:
                pending.pop(0)
            continue
        out.append(ln)
        pending += [m.group(2) for m in HEREDOC.finditer(ln)]
    return out


def is_test_run(part):
    toks = CD_STEP.sub("", part.strip()).split()
    while toks and toks[0] == "time":
        toks = toks[1:]
    if not toks:
        return False
    first = os.path.basename(toks[0])
    if first in RUNNERS:
        return True
    if PYTHON.match(toks[0]):
        rest = toks[1:]
        while rest and rest[0].startswith("-") and rest[0] not in ("-m", "-c"):
            rest = rest[1:]
        if rest[:1] == ["-m"]:
            return rest[1:2] in (["pytest"], ["unittest"])
        return bool(rest) and rest[0] != "-c" and bool(TEST_SCRIPT.search(rest[0]))
    if first in ("npm", "pnpm", "yarn"):
        return toks[1:2] == ["test"] or toks[1:3] == ["run", "test"]
    return first in TOOL_TEST and toks[1:2] == ["test"]


def test_runs(raw):
    """Each test run in one Bash command, as its own text (raw, not whitespace-collapsed)."""
    runs = []
    for line in command_lines(raw):
        quoted = "'" in line or '"' in line
        parts = [line] if quoted else re.split(r"\s*(?:;|&&|\|\|)\s*", line)
        runs += [p.strip() for p in parts if is_test_run(p)]
    return runs


def label_of(name, inp):
    for key in ("command", "file_path", "pattern", "query", "url", "description", "skill"):
        if text_of(inp.get(key)):
            return "%s: %s" % (name, label(CD_STEP.sub("", inp[key].strip())))
    return name


def result_size(content):
    if isinstance(content, str):
        return len(content)
    n = 0
    if isinstance(content, list):
        for b in content:
            if isinstance(b, dict):
                n += len(text_of(b.get("text")))
                src = b.get("source")
                if isinstance(src, dict):
                    n += len(text_of(src.get("data")))
    return n


def mtime(p):
    try:
        return os.path.getmtime(p)
    except OSError:
        return -1


def resolve(args):
    """The transcript path, or (None, message, candidates)."""
    if args.transcript:
        if os.path.isfile(args.transcript):
            return args.transcript, None, []
        return None, "no transcript at %s" % args.transcript, []
    sid = args.session or os.environ.get("CLAUDE_CODE_SESSION_ID")
    if not sid:
        here = os.path.join(args.projects_dir, re.sub(r"[^A-Za-z0-9]", "-", os.getcwd()))
        cands = sorted(glob.glob(os.path.join(glob.escape(here), "*.jsonl")),
                       key=mtime, reverse=True)[:5]
        return None, "no transcript identity: pass --session or --transcript", cands
    if not SID_RE.match(sid):
        return None, "no transcript: %r is not a session id" % sid, []
    hits = glob.glob(os.path.join(glob.escape(args.projects_dir), "*", sid + ".jsonl"))
    if len(hits) == 1:
        return hits[0], None, []
    if not hits:
        return None, "no transcript for session %s under %s" % (sid, args.projects_dir), []
    return None, "session %s matches %d transcripts" % (sid, len(hits)), sorted(hits)


def count(path):
    calls = OrderedDict()          # tool_use id -> (name, input), in order
    results = {}                   # tool_use id -> (is_error, size)
    first = last = None
    turn_ms = 0
    humans = peers = 0
    notices = set()
    for row in iter_rows(path):
        if not isinstance(row, dict) or row.get("isSidechain"):
            continue
        t = row.get("type")
        ts = row.get("timestamp")
        if isinstance(ts, str) and t in ("assistant", "user", "system"):
            first = first or ts
            last = ts
        if t == "system" and row.get("subtype") == "turn_duration":
            try:
                turn_ms += int(float(row.get("durationMs") or 0))
            except (TypeError, ValueError):
                pass
            continue
        if t == "attachment":
            att = row.get("attachment")
            if isinstance(att, dict) and att.get("type") == "queued_command":
                notices.update(NOTICE_RE.findall(text_of(att.get("prompt"))))
            continue
        if t not in ("assistant", "user"):
            continue
        msg = row.get("message")
        content = msg.get("content") if isinstance(msg, dict) else None
        if t == "user":
            origin = row.get("origin")
            kind = origin.get("kind") if isinstance(origin, dict) else None
            if kind == "human":
                humans += 1
            elif kind == "peer":
                peers += 1
            notices.update(NOTICE_RE.findall(text_of(content)))
        if not isinstance(content, list):
            continue
        for b in content:
            if not isinstance(b, dict):
                continue
            if t == "assistant" and b.get("type") == "tool_use":
                tid = b.get("id")
                if isinstance(tid, str) and tid not in calls:
                    inp = b.get("input")
                    calls[tid] = (text_of(b.get("name")) or "?", inp if isinstance(inp, dict) else {})
            elif t == "user" and b.get("type") == "tool_result":
                results[b.get("tool_use_id")] = (b.get("is_error") is True,
                                                result_size(b.get("content")))
    return calls, results, first, last, turn_ms, humans, peers, notices


def build(path):
    calls, results, first, last, turn_ms, humans, peers, notices = count(path)
    by_tool, failed, bash_seen = Counter(), Counter(), Counter()
    reads = OrderedDict()          # (path, offset, limit) -> reads, edit counter at last read
    last_fail, failed_again = {}, []
    test_last, test_rep, test_cmds = {}, [], []
    edits = bg = questions = 0
    helpers, sizes = [], []
    web = {"WebSearch": 0, "WebFetch": 0}
    for tid, (name, inp) in calls.items():
        err, size = results.get(tid, (False, 0))
        by_tool[name] += 1
        if err:
            failed[name] += 1
        sizes.append((size, label_of(name, inp)))
        if name in EDIT_TOOLS:
            if not err:            # a failed edit changed nothing
                edits += 1
        elif name == "Read":
            key = (text_of(inp.get("file_path")), inp.get("offset"), inp.get("limit"))
            r = reads.setdefault(key, {"reads": 0, "edit_between": False, "at": None})
            if r["reads"] and r["at"] != edits:
                r["edit_between"] = True
            r["reads"] += 1
            r["at"] = edits
        elif name == "Bash":
            cmd = text_of(inp.get("command")).strip()
            bash_seen[cmd] += 1
            if inp.get("run_in_background") is True:
                bg += 1
            if err:
                if last_fail.get(cmd) == edits and label(cmd) not in [x["command"] for x in failed_again]:
                    failed_again.append({"command": label(cmd)})
                last_fail[cmd] = edits
            for run in test_runs(cmd):
                test_cmds.append(label(run))
                if test_last.get(run) == edits and label(run) not in test_rep:
                    test_rep.append(label(run))
                test_last[run] = edits
        elif name == "Agent":
            helpers.append({"type": text_of(inp.get("subagent_type")) or "general-purpose",
                            "description": label(inp.get("description"))})
        elif name in web:
            web[name] += 1
        elif name == "AskUserQuestion":
            questions += 1
    sid = os.path.basename(path)[:-len(".jsonl")]
    sub = sorted(glob.glob(os.path.join(glob.escape(os.path.join(os.path.dirname(path), sid)),
                                        "subagents", "agent-*.jsonl")))
    read_rows = []
    for (p, off, lim), r in reads.items():
        if r["reads"] >= 3:
            row = {"path": p, "reads": r["reads"], "edit_between": r["edit_between"]}
            if off is not None or lim is not None:
                row["offset"], row["limit"] = off, lim
            read_rows.append(row)
    return OrderedDict([
        ("transcript", path),
        ("session", sid),
        ("first_utc", first), ("last_utc", last),
        ("span_note", "first to last line, includes idle time"),
        ("active_turn_ms", turn_ms),
        ("compaction", COMPACTION_NOTE),
        ("messages_from_eran", humans),
        ("helper_handbacks", peers),
        ("tool_calls", dict(by_tool.most_common())),
        ("failed_calls", dict(failed.most_common())),
        ("repeated_commands", [{"command": label(c), "runs": n}
                               for c, n in bash_seen.most_common() if n > 1]),
        ("failed_again_no_edit_seen", failed_again),
        ("files_read_3_plus", read_rows),
        ("largest_results", [{"chars": s, "call": l} for s, l in sorted(sizes, reverse=True)[:5]]),
        ("suite_runs", {"count": len(test_cmds), "repeated_no_edit_seen": test_rep,
                        "commands": test_cmds}),
        ("helpers", helpers),
        ("helper_transcripts", sub),
        ("web", web),
        ("questions_asked", questions),
        ("background", {"bash_launched": bg, "helpers_launched": len(helpers),
                        "finish_notices_seen": len(notices)}),
        ("limits", LIMITS),
    ])


def show(d):
    out = []
    for k, v in d.items():
        if isinstance(v, dict) and v:
            out.append("%s:" % k)
            for a, b in v.items():
                if isinstance(b, list) and len(b) > SHOW_MAX:
                    b = b[:SHOW_MAX] + ["... and %d more (see --json)" % (len(b) - SHOW_MAX)]
                out.append("  %s: %s" % (a, b))
        elif isinstance(v, list) and v:
            out.append("%s:" % k)
            for b in v[:SHOW_MAX]:
                out.append("  %s" % (b,))
            if len(v) > SHOW_MAX:
                out.append("  ... and %d more (see --json)" % (len(v) - SHOW_MAX))
        else:
            out.append("%s: %s" % (k, v if v not in ({}, []) else "none"))
    return "\n".join(out)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--transcript")
    ap.add_argument("--session")
    ap.add_argument("--projects-dir", default=os.path.expanduser("~/.claude/projects"))
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    path, msg, cands = resolve(args)
    if not path:
        print(msg)
        for c in cands:
            print("  candidate (not picked): %s" % c)
        return 2
    try:
        d = build(path)
    except OSError as e:
        print("cannot read %s: %s" % (path, type(e).__name__))
        return 2
    print(json.dumps(d, indent=1) if args.json else show(d))
    return 0


if __name__ == "__main__":
    sys.exit(main())
