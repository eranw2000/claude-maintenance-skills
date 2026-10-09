#!/usr/bin/env python3
"""Tests for recall_check.py, the recall check.

Every run goes through the real entry point by subprocess, with `--claude` pointing at
fake_claude.py and HOME pointing at a temp folder, so no test ever reaches the real
`claude` or the real ~/.claude/projects. Every fixture is synthetic text written to a
mkdtemp folder. Row 0 is a CONTROL with a known answer.

Run:  python3 test_recall_check.py
"""

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
RECALL = os.path.join(HERE, "recall_check.py")
FAKE = os.path.join(HERE, "fake_claude.py")
BACKUP = "CLAUDE.md.backup-before-split-2026-01-01"

FILLER = ["What is filler item %d? | FILLTOKEN-%d | fact" % (i, i) for i in range(1, 11)]
FILLER_TEXT = "\n".join("- Filler item %d is FILLTOKEN-%d." % (i, i) for i in range(1, 11))
RULE_LINE = "What is the Friday deploy rule? | NODEPLOYFRI-7Q | rule"
RULE_TEXT = "- Never deploy on a Friday (NODEPLOYFRI-7Q)."
FACT_LINE = "What is the staging database called? | ORCHIDDB-42 | fact"
FACT_TEXT = "- The staging database is ORCHIDDB-42."
POINTER = "- Older records live in `CLAUDE_DECISIONS_2026-01.md`, same heading."


def notes(*lines):
    return "# Demo project\n\n" + "\n".join(lines) + "\n" + FILLER_TEXT + "\n"


def pack(*lines, filler=5):
    return "# recall pack\n\n" + "\n".join(list(lines) + FILLER[:filler]) + "\n"


class Run(object):
    def __init__(self, rc, out, err, calls, home, folder, tmp):
        self.rc, self.out, self.err, self.calls, self.home, self.folder = rc, out, err, calls, home, folder
        self.tmp = tmp


def leftover_copies(tmp):
    return [n for n in os.listdir(tmp) if n.startswith("recallcopy")]


def main():
    checks, tmpdirs = [], []

    def check(name, ok, detail=""):
        checks.append((name, bool(ok), detail))

    def project(before, after, archive=None, extra=None):
        d = os.path.realpath(tempfile.mkdtemp(prefix="recall_t_"))
        tmpdirs.append(d)
        with open(os.path.join(d, "CLAUDE.md"), "w") as fh:
            fh.write(after)
        with open(os.path.join(d, BACKUP), "w") as fh:
            fh.write(before)
        if archive is not None:
            with open(os.path.join(d, "CLAUDE_DECISIONS_2026-01.md"), "w") as fh:
                fh.write(archive)
        for name, text in (extra or {}).items():
            with open(os.path.join(d, name), "w") as fh:
                fh.write(text)
        os.makedirs(os.path.join(d, "split_2026-01-01"))
        return d

    def run(d, pack_text, args=None, env_extra=None, before=True):
        p = os.path.join(d, "split_2026-01-01", "QUESTIONS.md")
        with open(p, "w") as fh:
            fh.write(pack_text)
        home = os.path.realpath(tempfile.mkdtemp(prefix="recall_home_"))
        tmpdirs.append(home)
        log = os.path.join(home, "calls.jsonl")
        tmp = os.path.join(home, "tmp")
        os.makedirs(tmp)
        env = {"PATH": "/usr/bin:/bin", "HOME": home, "FAKE_CLAUDE_LOG": log, "TMPDIR": tmp}
        env.update(env_extra or {})
        argv = [sys.executable, RECALL, os.path.join(d, "CLAUDE.md"), "--pack", p, "--claude", FAKE]
        if before:
            argv += ["--before", os.path.join(d, BACKUP)]
        argv += args or []
        r = subprocess.run(argv, capture_output=True, text=True, env=env, timeout=120)
        calls = []
        if os.path.exists(log):
            with open(log) as fh:
                calls = [json.loads(l) for l in fh]
        return Run(r.returncode, r.stdout, r.stderr, calls, home, d, tmp)

    # ------------------------------------------------------------ 0 CONTROL: the fake itself
    d = project(notes(RULE_TEXT), notes(RULE_TEXT))
    r = subprocess.run([FAKE, "-p", "--setting-sources", "project", "--no-session-persistence",
                        "--strict-mcp-config", "--output-format", "json", "--tools", ""],
                       input="Q?", capture_output=True, text=True, cwd=d)
    check("0 CONTROL: the fake answers from CLAUDE.md in rule mode",
          r.returncode == 0 and "NODEPLOYFRI-7Q" in json.loads(r.stdout)["result"], r.stdout + r.stderr)
    r = subprocess.run([FAKE, "-p", "--setting-sources", "project", "--no-session-persistence",
                        "--strict-mcp-config", "--output-format", "json", "--tools", "", "Q?"],
                       input="", capture_output=True, text=True, cwd=d)
    check("0 CONTROL: the fake refuses a prompt given as a trailing argument",
          r.returncode == 2 and "FAKE ARGV BROKEN" in r.stderr, r.stderr)

    # ------------------------------------------------------------ 1 kept rule, kept fact: exit 0
    d = project(notes(RULE_TEXT, FACT_TEXT), notes(RULE_TEXT, FACT_TEXT))
    r = run(d, pack(RULE_LINE, FACT_LINE, filler=4))
    check("1 nothing moved: exit 0", r.rc == 0, r.out + r.err)
    check("1 nothing moved: no LOST line", r.rc == 0 and "LOST:" not in r.out and "KEPT:" in r.out, r.out)
    check("1 the run makes 2 calls per question plus 1 CONTROL call per rule question",
          len(r.calls) == 2 * 6 + 1, "calls %d" % len(r.calls))

    # ------------------------------------------------------------ 2 rule moved behind a pointer: exit 3
    d = project(notes(RULE_TEXT, FACT_TEXT), notes(POINTER, FACT_TEXT),
                archive="# Archive\n\n## Old\n\n" + RULE_TEXT + "\n")
    r = run(d, pack(RULE_LINE, FACT_LINE, filler=4))
    check("2 rule moved to an archive behind a pointer: exit 3", r.rc == 3, r.out + r.err)
    check("2 the LOST line names the rule question",
          re.search(r"^LOST: .*Friday deploy rule.*\(rule\)", r.out, re.M), r.out)

    # ------------------------------------------------------------ 3 fact moved behind a pointer: exit 0
    d = project(notes(RULE_TEXT, FACT_TEXT), notes(RULE_TEXT, POINTER),
                archive="# Archive\n\n## Old\n\n" + FACT_TEXT + "\n")
    r = run(d, pack(RULE_LINE, FACT_LINE, filler=4))
    check("3 fact moved to an archive behind a pointer: exit 0 (fact mode reads the archive)",
          r.rc == 0, r.out + r.err)
    # twin: the same move, asked as a rule
    r = run(d, pack(RULE_LINE, "What is the staging database called? | ORCHIDDB-42 | rule", filler=4))
    check("3 twin: the same moved line asked as a rule question: exit 3", r.rc == 3, r.out + r.err)

    # ------------------------------------------------------------ 4 fact deleted: exit 3
    d = project(notes(RULE_TEXT, FACT_TEXT), notes(RULE_TEXT))
    r = run(d, pack(RULE_LINE, FACT_LINE, filler=4))
    check("4 fact deleted outright: exit 3", r.rc == 3, r.out + r.err)
    check("4 the LOST line names the fact question",
          re.search(r"^LOST: .*staging database.*\(fact\)", r.out, re.M), r.out)

    # ------------------------------------------------------------ 5 bad question
    d = project(notes(RULE_TEXT), notes(RULE_TEXT))
    r = run(d, pack(RULE_LINE, "What is the never-written thing? | NOWHERE-TOKEN-1 | fact", filler=4))
    check("5 a question that fails BEFORE is BAD QUESTION and does not count: exit 0",
          r.rc == 0 and re.search(r"^BAD QUESTION: .*never-written", r.out, re.M), r.out + r.err)

    # ------------------------------------------------------------ 6 control too easy
    d = project(notes(RULE_TEXT), notes(RULE_TEXT))
    knows = {"FAKE_CLAUDE_KNOWS": "NODEPLOYFRI-7Q"}
    r = run(d, pack(RULE_LINE, filler=5), env_extra=knows)
    check("6 a rule question that passes with an empty CLAUDE.md: exit 2 (pack too easy)",
          r.rc == 2 and "CONTROL" in r.out and "too easy" in r.out, r.out + r.err)
    r2l = "What is the lock rule? | LOCKRULE-9 | rule"
    r3l = "What is the backup rule? | BACKRULE-5 | rule"
    d = project(notes(RULE_TEXT, "- Never skip the lock (LOCKRULE-9).", "- Always back up (BACKRULE-5)."),
                notes(RULE_TEXT, "- Never skip the lock (LOCKRULE-9).", "- Always back up (BACKRULE-5)."))
    r = run(d, pack(RULE_LINE, r2l, r3l, filler=3), env_extra=knows)
    check("6 twin: 1 of 3 rule questions passes CONTROL (under half): not exit 2",
          r.rc == 0, r.out + r.err)
    r = run(d, pack(RULE_LINE, r2l, filler=4), env_extra=knows)
    check("6 boundary: exactly half (1 of 2) of the rule questions pass CONTROL: exit 2",
          r.rc == 2 and "too easy" in r.out, r.out + r.err)

    # ------------------------------------------------------------ 7 pack size and shape, zero calls
    d = project(notes(RULE_TEXT), notes(RULE_TEXT))
    for n, want in ((5, 2), (6, 0), (10, 0), (11, 2)):
        r = run(d, pack(RULE_LINE, filler=n - 1) if n <= 11 else "")
        if want == 2:
            check("7 a %d-line pack exits 2 before any call" % n,
                  r.rc == 2 and not r.calls and "REFUSED" in r.out, r.out + r.err)
        else:
            check("7 a %d-line pack runs" % n, r.rc == 0 and r.calls, r.out + r.err)
    r = run(d, pack(filler=6))
    check("7 a pack with no rule line exits 2 before any call",
          r.rc == 2 and not r.calls and "rule" in r.out, r.out + r.err)
    r = run(d, pack(RULE_LINE, "a line with no separator", filler=4))
    check("7 a malformed line exits 2 before any call", r.rc == 2 and not r.calls and "REFUSED" in r.out, r.out + r.err)
    r = run(d, pack(RULE_LINE, "Q? | TOKEN | maybe", filler=4))
    check("7 a kind other than rule or fact exits 2 before any call", r.rc == 2 and not r.calls and "REFUSED" in r.out,
          r.out + r.err)

    # ------------------------------------------------------------ 8 max calls
    d = project(notes(RULE_TEXT), notes(RULE_TEXT))
    r = run(d, pack(RULE_LINE, filler=5), ["--max-calls", "12"])
    check("8 6 questions, 1 rule = 13 calls; --max-calls 12 exits 2 with zero calls",
          r.rc == 2 and not r.calls and "13" in r.out, r.out + r.err)
    r = run(d, pack(RULE_LINE, filler=5), ["--max-calls", "13"])
    check("8 twin: --max-calls 13 runs all 13", r.rc == 0 and len(r.calls) == 13, r.out + r.err)

    # ------------------------------------------------------------ 9 failed calls
    d = project(notes(RULE_TEXT), notes(RULE_TEXT))
    for kind in ("nonjson", "is_error", "rc"):
        r = run(d, pack(RULE_LINE, filler=5), env_extra={"FAKE_CLAUDE_FAIL": "3:" + kind})
        check("9 call 3 fails (%s): exit 2, FAILED names the question, no call after it" % kind,
              r.rc == 2 and re.search(r"^FAILED: BEFORE call for question 3 \(What is filler item 2\?\)",
                                      r.out, re.M) and len(r.calls) == 3,
              "calls %d\n%s%s" % (len(r.calls), r.out, r.err))
    r = run(d, pack(RULE_LINE, filler=5), ["--timeout", "2"], env_extra={"FAKE_CLAUDE_FAIL": "2:sleep"})
    check("9 a call that times out: exit 2 with FAILED naming question 2, no call after it",
          r.rc == 2 and "FAILED: BEFORE call for question 2 (What is filler item 1?)" in r.out
          and "timed out" in r.out and len(r.calls) == 2, "calls %d\n%s" % (len(r.calls), r.out + r.err))
    r = run(d, pack(RULE_LINE, filler=5), env_extra={"FAKE_CLAUDE_FAIL": "3:badutf8"})
    check("9 stdout that is not UTF-8: exit 2 with FAILED, never a traceback",
          r.rc == 2 and "FAILED: BEFORE call for question 3" in r.out and "not UTF-8" in r.out
          and "Traceback" not in r.err and len(r.calls) == 3, r.out + r.err)
    r = run(d, pack(RULE_LINE, filler=5))
    check("9 the fake never reported broken argv on a normal run", r.rc == 0 and r.calls and "FAKE ARGV BROKEN" not in r.out + r.err,
          r.out + r.err)

    # ------------------------------------------------------------ 10 the calls themselves
    d = project(notes(RULE_TEXT, FACT_TEXT), notes(RULE_TEXT, FACT_TEXT))
    r = run(d, pack(RULE_LINE, FACT_LINE, filler=4))
    modes = [c["mode"] for c in r.calls]
    check("10 rule questions use --tools \"\" and fact questions --tools Read --restricted",
          modes.count("rule") == 3 and modes.count("fact") == 10, repr(modes))
    check("10 every call runs in a temp copy, never in the project folder",
          r.calls and all(os.path.realpath(c["cwd"]) != d and not c["cwd"].startswith(d) for c in r.calls),
          repr([c["cwd"] for c in r.calls[:2]]))
    check("10 the prompt goes on stdin and carries the question",
          r.calls and all("Question:" in c["stdin"] for c in r.calls), "")
    check("10 temp copies are removed after the run",
          r.calls and all(not os.path.exists(c["cwd"]) for c in r.calls)
          and not leftover_copies(r.tmp), repr(leftover_copies(r.tmp)))

    # ------------------------------------------------------------ 11 cleanup of ~/.claude/projects
    r = run(d, pack(RULE_LINE, filler=5), env_extra={"FAKE_CLAUDE_MEMORY": "1"})
    proj = os.path.join(r.home, ".claude", "projects")
    left = os.listdir(proj) if os.path.isdir(proj) else []
    check("11 the encoded session folder and its empty memory/ are removed after each call",
          r.rc == 0 and not left, repr(left) + r.out + r.err)
    r = run(d, pack(RULE_LINE, filler=5), env_extra={"FAKE_CLAUDE_MEMORY": "file"})
    proj = os.path.join(r.home, ".claude", "projects")
    left = os.listdir(proj) if os.path.isdir(proj) else []
    copies_used = sorted(set(c["cwd"] for c in r.calls))
    expected = sorted(re.sub(r"[^A-Za-z0-9]", "-", os.path.realpath(c)) for c in copies_used)
    notes_left = [os.path.join(proj, x, "memory", "note.md") for x in expected]
    check("11 twin: all 3 copies' session folders hold a file, so all 3 are LEFT, reported, and "
          "every file is intact",
          len(copies_used) == 3 and sorted(left) == expected and r.out.count("LEFT:") == 3
          and all(os.path.isfile(f) and open(f).read() == "left by the fake\n" for f in notes_left),
          repr(left) + repr(expected) + r.out)

    # ------------------------------------------------------------ 12 --manifest mode
    def manifest_project(status="complete", tamper=None, outside=False, folder=None, entry=None, entry2=None):
        d = project(notes(RULE_TEXT, FACT_TEXT), notes(POINTER, FACT_TEXT),
                    archive="# Archive\n\n" + RULE_TEXT + "\n",
                    extra={"OTHER_NOTES.md": "# Other\n"})
        run_dir = os.path.join(d, "split_2026-01-01")
        bk = os.path.join(d, BACKUP)
        pre = hashlib.sha256(open(bk, "rb").read()).hexdigest()
        if tamper == "changed":
            with open(bk, "a") as fh:
                fh.write("changed\n")
        if tamper == "missing":
            os.remove(bk)
        path_bk = BACKUP
        if outside:
            o = os.path.realpath(tempfile.mkdtemp(prefix="recall_out_"))
            tmpdirs.append(o)
            shutil.copy(os.path.join(d, BACKUP), os.path.join(o, BACKUP))
            path_bk = os.path.relpath(os.path.join(o, BACKUP), d)
        man = {"version": 1, "status": status, "date": "2026-01-01", "folder": folder or d,
               "files": [{"path": "CLAUDE.md", "pre_sha256": pre, "post_sha256": "x", "backup": path_bk},
                         {"path": "CLAUDE_DECISIONS_2026-01.md", "pre_sha256": None,
                          "post_sha256": "y", "backup": None}]}
        if entry is not None:
            man["files"][0] = entry(man["files"][0])
        if entry2 is not None:
            man["files"][1] = entry2(man["files"][1])
        with open(os.path.join(run_dir, "manifest.json"), "w") as fh:
            json.dump(man, fh)
        return d, os.path.join(run_dir, "manifest.json")

    d, m = manifest_project()
    r = run(d, pack(RULE_LINE, FACT_LINE, filler=4), ["--manifest", m], before=False)
    check("12 --manifest: a rule moved by the run is LOST: exit 3", r.rc == 3, r.out + r.err)
    n = len(r.calls) and 6
    check("12 --manifest: the BEFORE copy lacks the file the run created; the AFTER copy has it",
          len(r.calls) == 13
          and all("CLAUDE_DECISIONS_2026-01.md" not in c["files"] for c in r.calls[:n])
          and all("CLAUDE_DECISIONS_2026-01.md" in c["files"] for c in r.calls[n:2 * n])
          and all("OTHER_NOTES.md" in c["files"] for c in r.calls[:n]),
          repr([c["files"] for c in r.calls[:1]]) + r.out)
    check("12 REPORT names the notes files BEFORE took from the current folder",
          re.search(r"taken from the current folder: .*OTHER_NOTES\.md", r.out), r.out)
    check("12 REPORT says Phase 0 deletions are covered by the Phase 0 loss check",
          "Phase 0" in r.out, r.out)
    for why, kw in (("pending", dict(status="pending")), ("backup changed", dict(tamper="changed")),
                    ("backup missing", dict(tamper="missing")), ("backup outside the folder", dict(outside=True)),
                    ("folder mismatch", dict(folder="/nonexistent/elsewhere")),
                    ("backup key missing", dict(entry=lambda e: {k: v for k, v in e.items() if k != "backup"})),
                    ("pre_sha256 without a backup", dict(entry2=lambda e: dict(e, pre_sha256="a" * 64))),
                    ("backup is a number", dict(entry=lambda e: dict(e, backup=17))),
                    ("backup is a list", dict(entry=lambda e: dict(e, backup=["x"])))):
        d, m = manifest_project(**kw)
        r = run(d, pack(RULE_LINE, filler=5), ["--manifest", m], before=False)
        check("12 --manifest refuses (%s): exit 2, zero calls" % why,
              r.rc == 2 and not r.calls and "REFUSED" in r.out and "Traceback" not in r.err, r.out + r.err)

    # ------------------------------------------------------------ 13 BEFORE source flags
    d = project(notes(RULE_TEXT), notes(RULE_TEXT))
    r = run(d, pack(RULE_LINE, filler=5), before=False)
    check("13 neither --before nor --manifest: exit 2, zero calls", r.rc == 2 and not r.calls and "REFUSED" in r.out, r.out + r.err)
    d2, m = manifest_project()
    r = run(d2, pack(RULE_LINE, filler=5), ["--manifest", m])
    check("13 both --before and --manifest: exit 2, zero calls", r.rc == 2 and not r.calls and "REFUSED" in r.out, r.out + r.err)
    r = run(d, pack(RULE_LINE, filler=5), ["--before", os.path.join(d, "missing.md")], before=False)
    check("13 --before names a missing file: exit 2, zero calls", r.rc == 2 and not r.calls and "REFUSED" in r.out, r.out + r.err)
    o = os.path.realpath(tempfile.mkdtemp(prefix="recall_out_"))
    tmpdirs.append(o)
    with open(os.path.join(o, "private.md"), "w") as fh:
        fh.write(notes(RULE_TEXT))
    r = run(d, pack(RULE_LINE, filler=5), ["--before", os.path.join(o, "private.md")], before=False)
    check("13 --before outside the project folder: exit 2, zero calls",
          r.rc == 2 and not r.calls and "REFUSED" in r.out, r.out + r.err)
    os.symlink(os.path.join(o, "private.md"), os.path.join(d, "CLAUDE.md.backup-before-split-2026-02-02"))
    r = run(d, pack(RULE_LINE, filler=5), ["--before", os.path.join(d, "CLAUDE.md.backup-before-split-2026-02-02")],
            before=False)
    check("13 a --before symlink inside the folder that resolves outside: exit 2, zero calls",
          r.rc == 2 and not r.calls and "REFUSED" in r.out, r.out + r.err)

    # ------------------------------------------------------------ 14 judging
    d = project(notes("- Never deploy on a Friday."), notes("- **Never** deploy on a `Friday`."))
    r = run(d, pack("What is the Friday deploy rule? | never deploy on a friday | rule", filler=5))
    check("14 the fragment matches through case and markdown marks: exit 0", r.rc == 0, r.out + r.err)

    # ------------------------------------------------------------ 15 report file
    d = project(notes(RULE_TEXT), notes(RULE_TEXT))
    rep = os.path.join(d, "split_2026-01-01", "RECALL.md")
    r = run(d, pack(RULE_LINE, filler=5), ["--report", rep])
    check("15 --report writes the same verdict to a file",
          os.path.exists(rep) and "VERDICT exit 0" in open(rep).read(), r.out + r.err)

    # ------------------------------------------------------------ 16 edge cases
    import importlib
    sys.path.insert(0, HERE)
    rc_mod = importlib.import_module("recall_check")
    f = rc_mod.found
    check("16 an answer holding the refusal phrase fails even when it names the fragment",
          not f("NODEPLOYFRI-7Q", "NOT IN MY INSTRUCTIONS. You asked about NODEPLOYFRI-7Q.")
          and not f("ORCHIDDB-42", "NOT IN MY NOTES (ORCHIDDB-42)") and f("NODEPLOYFRI-7Q", "It is NODEPLOYFRI-7Q."), "")
    d = project(notes(RULE_TEXT), notes(RULE_TEXT))
    r = run(d, pack(RULE_LINE, "Is NODEPLOYFRI-7Q the Friday rule? | NODEPLOYFRI-7Q | rule", filler=4))
    check("16 a pack line whose fragment is in its own question exits 2 before any call",
          r.rc == 2 and not r.calls and "in its own question" in r.out, r.out + r.err)
    check("16 DB_PROD does not match DBPROD, TOKEN-1 does not match TOKEN-10",
          not f("DB_PROD", "use DBPROD") and f("DB_PROD", "use DB_PROD") and f("DB_PROD", "use `DB_PROD`")
          and not f("TOKEN-1", "it is TOKEN-10") and f("TOKEN-1", "it is TOKEN-1."), "")
    r = run(d, pack(RULE_LINE, "What is the bold marker? | ** | fact", filler=4))
    check("16 a fragment with no letter or digit exits 2 before any call",
          r.rc == 2 and not r.calls and "no letter or digit" in r.out, r.out + r.err)
    check("16 round 2: a refusal split by a line break or extra spaces still fails",
          not f("NODEPLOYFRI-7Q", "NOT IN MY\nINSTRUCTIONS. You asked about NODEPLOYFRI-7Q.")
          and not f("ORCHIDDB-42", "NOT  IN   MY NOTES: ORCHIDDB-42"), "")
    check("16 round 2: DB_PROD does not match inside DB_PROD_BACKUP, TOKEN-1 not inside TOKEN-1-OLD",
          not f("DB_PROD", "only DB_PROD_BACKUP") and not f("TOKEN-1", "now TOKEN-1-OLD")
          and f("DB_PROD", "it is DB_PROD, not the backup"), "")
    check("16 round 2: a phrase fragment matches across a line break in the answer",
          f("never deploy on a friday", "Never deploy\non a Friday."), "")
    heb = "\u05e9\u05d9\u05e9\u05d9"
    d = project(notes(RULE_TEXT, "- Deploy day is " + heb + "."), notes(RULE_TEXT, "- Deploy day is " + heb + "."))
    r = run(d, pack(RULE_LINE, "What is the deploy day? | " + heb + " | fact", filler=4))
    check("16 round 2: a Hebrew fragment is accepted and judged (exit 0, KEPT)",
          r.rc == 0 and "KEPT: 2" in r.out, r.out + r.err)
    d, m = manifest_project(entry=lambda e: dict(e, backup="bad\x00backup"))
    r = run(d, pack(RULE_LINE, filler=5), ["--manifest", m], before=False)
    check("16 round 2: a manifest backup holding a NUL character: exit 2, REFUSED, no traceback",
          r.rc == 2 and not r.calls and "REFUSED" in r.out and "Traceback" not in r.err, r.out + r.err)
    d = project(notes(RULE_TEXT), notes(RULE_TEXT), extra={"LOCKED.md": "# locked\n"})
    os.chmod(os.path.join(d, "LOCKED.md"), 0)
    r = run(d, pack(RULE_LINE, filler=5))
    os.chmod(os.path.join(d, "LOCKED.md"), 0o600)
    check("16 a notes file that cannot be copied: exit 2 with FAILED, zero calls, no temp copy left",
          r.rc == 2 and "could not build the temp copies" in r.out and not r.calls
          and not leftover_copies(r.tmp) and "Traceback" not in r.err,
          repr(leftover_copies(r.tmp)) + r.out + r.err)
    d = project(notes(RULE_TEXT), notes(RULE_TEXT))
    r = run(d, pack(RULE_LINE, filler=5), env_extra={"FAKE_CLAUDE_DECOY": "7"})
    check("16 judging reads only `result`: a non-answer there with the notes in another field is LOST",
          r.rc == 3 and "LOST: 1" in r.out, r.out + r.err)
    # clean_session, in process, with HOME pointed at a temp folder
    old_home = os.environ.get("HOME")
    h = os.path.realpath(tempfile.mkdtemp(prefix="recall_home_"))
    tmpdirs.append(h)
    os.environ["HOME"] = h
    try:
        other = os.path.join(h, "other_session")
        os.makedirs(os.path.join(other, "memory"))
        cwd1 = os.path.join(h, "copyA")
        top = rc_mod.session_folder(cwd1)
        os.makedirs(os.path.dirname(top))
        os.symlink(other, top)
        left = []
        rc_mod.clean_session(cwd1, False, left)
        check("16 a symlinked session folder is never followed: the other session's memory/ stays",
              os.path.isdir(os.path.join(other, "memory")) and os.path.islink(top) and left, repr(left))
        cwd2 = os.path.join(h, "copyB")
        top2 = rc_mod.session_folder(cwd2)
        os.makedirs(os.path.join(top2, "memory"))
        left = []
        rc_mod.clean_session(cwd2, True, left)
        check("16 a session folder that existed before the call is never touched",
              os.path.isdir(os.path.join(top2, "memory")) and left, repr(left))
        left = []
        rc_mod.clean_session(cwd2, False, left)
        check("16 control: the same empty folder made by the call is removed",
              not os.path.lexists(top2) and not left, repr(left))
    finally:
        if old_home is None:
            os.environ.pop("HOME", None)
        else:
            os.environ["HOME"] = old_home

    for t in tmpdirs:
        shutil.rmtree(t, ignore_errors=True)

    if not checks:
        print("0/0 passed -- the harness ran NO checks, which is a harness bug")
        return 1
    failed = [c for c in checks if not c[1]]
    for name, ok, detail in checks:
        if not ok:
            print("  FAILED " + name)
            print("         " + detail.replace("\n", "\n         ")[:600])
    print("%d/%d passed" % (len(checks) - len(failed), len(checks)))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
