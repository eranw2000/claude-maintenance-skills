#!/usr/bin/python3
"""A fake `claude` for the recall check's tests and goal_check scenario 8. Never a real call.

It models the two modes the recall check relies on:
  rule mode (`--tools ""`): the answer holds the question plus the text of CLAUDE.md in the
      working folder, nothing else, as a session that sees only the auto-loaded file;
  fact mode (`--tools Read --restricted`): the answer holds the question plus the text of
      every top-level *.md file in the working folder, as a session that may read them.
The question (the text after "Question: ") is echoed, never the whole prompt, which holds the
refusal phrases. FAKE_CLAUDE_KNOWS stands for general knowledge: its text is in every
answer, which is what makes a pack "too easy" in CONTROL.

It checks the argv the recall check must send and exits 2 with `FAKE ARGV BROKEN: ...` on
stderr when it is wrong, so a test that passes also proves the flags. The prompt must come
on stdin: a trailing prompt argument is refused.

Environment knobs:
  FAKE_CLAUDE_LOG   append one JSON line per call: argv, cwd, mode, stdin, files in cwd
  FAKE_CLAUDE_FAIL  "<n>:<kind>" makes call number n (1-based) fail; kind is one of
                    nonjson, is_error, rc, sleep
  FAKE_CLAUDE_MEMORY  "1": create ~/.claude/projects/<encoded cwd>/memory, as a real
                    Read-mode run does; "file": also put a file in it
  FAKE_CLAUDE_KNOWS   text added to every answer (general knowledge)
  FAKE_CLAUDE_DECOY   "<n>": from call n on, `result` is a non-answer and the notes text sits
                    in another JSON field, so judging the whole JSON would pass
  (FAKE_CLAUDE_FAIL kind "badutf8" writes a byte that is not UTF-8 to stdout)
"""
import json
import os
import re
import sys
import time

REQUIRED = ["-p", "--setting-sources", "project", "--no-session-persistence",
            "--strict-mcp-config", "--output-format", "json"]


def broken(why):
    sys.stderr.write("FAKE ARGV BROKEN: %s\n" % why)
    sys.exit(2)


def main():
    argv = sys.argv[1:]
    if argv[:len(REQUIRED)] != REQUIRED:
        broken("expected %r first, got %r" % (REQUIRED, argv[:len(REQUIRED)]))
    rest = argv[len(REQUIRED):]
    if rest == ["--tools", ""]:
        mode = "rule"
    elif rest == ["--tools", "Read", "--restricted"]:
        mode = "fact"
    else:
        broken("tools flags %r" % (rest,))
    prompt = sys.stdin.read()
    if not prompt.strip():
        broken("no prompt on stdin")

    log = os.environ.get("FAKE_CLAUDE_LOG")
    n = 1
    if log:
        if os.path.exists(log):
            with open(log) as fh:
                n = sum(1 for _ in fh) + 1
        with open(log, "a") as fh:
            fh.write(json.dumps({"argv": argv, "cwd": os.getcwd(), "mode": mode,
                                 "stdin": prompt, "files": sorted(os.listdir("."))}) + "\n")

    mem = os.environ.get("FAKE_CLAUDE_MEMORY")
    if mem:
        enc = re.sub(r"[^A-Za-z0-9]", "-", os.path.realpath(os.getcwd()))
        d = os.path.join(os.path.expanduser("~"), ".claude", "projects", enc, "memory")
        os.makedirs(d, exist_ok=True)
        if mem == "file":
            with open(os.path.join(d, "note.md"), "w") as fh:
                fh.write("left by the fake\n")

    fail = os.environ.get("FAKE_CLAUDE_FAIL", "")
    if fail:
        at, kind = fail.split(":", 1)
        if int(at) == n:
            if kind == "nonjson":
                print("this is not json")
                return 0
            if kind == "rc":
                sys.stderr.write("fake api error\n")
                return 1
            if kind == "sleep":
                time.sleep(30)
            if kind == "badutf8":
                sys.stdout.buffer.write(b"\xff\xfe not utf-8\n")
                return 0
            if kind == "is_error":
                print(json.dumps({"type": "result", "is_error": True, "result": "API Error"}))
                return 0

    names = ["CLAUDE.md"] if mode == "rule" else sorted(
        f for f in os.listdir(".") if f.endswith(".md") and os.path.isfile(f))
    body = []
    for f in names:
        if os.path.isfile(f):
            with open(f, encoding="utf-8") as fh:
                body.append(fh.read())
    question = prompt.split("Question: ", 1)[-1]
    answer = question + "\n" + os.environ.get("FAKE_CLAUDE_KNOWS", "") + "\n" + "\n".join(body)
    decoy = os.environ.get("FAKE_CLAUDE_DECOY")
    if decoy and n >= int(decoy):
        print(json.dumps({"type": "result", "is_error": False, "num_turns": 1,
                          "result": "I could not find that.", "debug": answer}))
        return 0
    print(json.dumps({"type": "result", "is_error": False, "num_turns": 1,
                      "result": answer, "total_cost_usd": 0.0}))
    return 0


sys.exit(main())
