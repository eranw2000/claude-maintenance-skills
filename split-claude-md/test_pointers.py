#!/usr/bin/env python3
"""Tests for pointers.py and splitlib.pointers().

Every fixture is a synthetic string built here and written to a mkdtemp folder,
and every run passes an explicit empty temp root, so nothing resolves
against the real home folder. Row 0 is a CONTROL with a known answer: if it
fails, the harness is broken rather than the script.

Run:  python3 test_pointers.py
"""

import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
POINTERS = os.path.join(HERE, "pointers.py")
LOSS = os.path.join(HERE, "loss_check.py")
sys.path.insert(0, HERE)

RULE = ("Never push the nightly widget export straight to the shared bucket "
        "without a dry run first.")
LAST_RUN = ("Last split run: 2026-02-01, 1 to 1 chars, 1 records moved to "
            "`CLAUDE_DECISIONS_INDEX.md`, report split_2026-02-01/REPORT.md")
INDEX = """# Decisions Index

## Archives

- `CLAUDE_DECISIONS_2026-01.md`: January 2026 records

## Entries

| Date | Title | File |
| --- | --- | --- |
| 2026-01-10 | Widget export record | `CLAUDE_DECISIONS_2026-01.md` |
"""
RECORD = """## Widget export record (2026-01-10)

Service `srv-arc44` ran the export.
{rule}
"""
BEFORE = """# Project

Preamble line that says what this file is for.

## Overview

Plain overview text about the widget project.

{record}
## Newer record (2026-03-02)

Newer record body text that stays in place.
"""
AFTER = """# Project

Preamble line that says what this file is for.
{last_run}
## Overview

Plain overview text about the widget project.

## Newer record (2026-03-02)

Newer record body text that stays in place.
"""


def run(script, *args, env=None, cwd=None):
    p = subprocess.run([sys.executable, script] + list(args), stdout=subprocess.PIPE,
                       stderr=subprocess.PIPE, env=env, cwd=cwd)
    return p.returncode, p.stdout.decode("utf-8"), p.stderr.decode("utf-8")


def write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)
    return path


def main():
    import splitlib
    checks = []
    outputs = []

    def check(name, ok, detail=""):
        if not isinstance(detail, str):
            detail = repr(detail)
        checks.append((name, bool(ok), detail))

    tmpdirs = []

    def folder():
        d = os.path.realpath(tempfile.mkdtemp(prefix="pointers-test-"))
        tmpdirs.append(d)
        return d

    def pt(path, *args, **kw):
        rc, out, err = run(POINTERS, path, *args, **kw)
        outputs.append(out)
        return rc, out, err

    def lc(*args, **kw):
        rc, out, err = run(LOSS, *args, **kw)
        outputs.append(out)
        return rc, out, err

    def one(claude, extra=None, name="CLAUDE.md"):
        """A folder holding the file under check plus extra files; returns
        (file path, folder, an empty root folder)."""
        d = folder()
        f = write(os.path.join(d, name), claude)
        for n, t in (extra or {}).items():
            write(os.path.join(d, n), t)
        return f, d, folder()

    def unresolved(out, token):
        return [l for l in out.splitlines() if l.startswith("UNRESOLVED: %s " % token)]

    # ---------------------------------------------------------------- CONTROL
    # The default root comes from pointers.py's argument parsing, read through
    # HOME, so a fake HOME stands in for the real home folder (no verdict
    # may depend on what the real ~/.claude holds). CLAUDE.md exists in the fake
    # home .claude folder; the checked file is not itself named CLAUDE.md, so
    # only a hidden default root could resolve it.
    home = folder()
    write(os.path.join(home, ".claude", "CLAUDE.md"), "# Global\n")
    env = dict(os.environ, HOME=home)
    home_claude = os.path.isfile(os.path.join(home, ".claude", "CLAUDE.md"))
    f, d, root = one("# P\n\n## Overview\n\nSee `CLAUDE.md` for the rules.\n", name="PROJECT.md")
    rc, out, err = pt(f, "--root", root, env=env)
    check("CONTROL: a name that exists only in the (fake) home .claude reads unresolved, exit 3",
          home_claude and rc == 3 and "UNRESOLVED: CLAUDE.md" in out,
          "home has it=%s rc=%d %r %r" % (home_claude, rc, out[-300:], err[-300:]))
    rc, out, err = pt(f, env=env)
    check("with no --root, pointers.py's own default (HOME/.claude) resolves it, exit 0",
          rc == 0 and "unresolved 0" in out, "rc=%d %r %r" % (rc, out[-300:], err[-300:]))
    rc, out, err = pt(f, "--root", root, env=env)
    check("an explicit --root replaces the default (same fake HOME), exit 3",
          rc == 3 and unresolved(out, "CLAUDE.md"), "rc=%d %r" % (rc, out[-300:]))

    # ---------------------------------------------------------------- basics
    f, d, root = one("# P\n\n## Overview\n\nSee `MISSING_NOTES.md` for the old records.\n")
    rc, out, err = pt(f, "--root", root)
    check("a pointer to a missing file exits 3 and names the file and its section",
          rc == 3 and any("in section ## Overview" in l for l in unresolved(out, "MISSING_NOTES.md")),
          "rc=%d %r %r" % (rc, out[-300:], err[-300:]))
    f, d, root = one("# P\n\n## Overview\n\nSee `NOTES.md` for the old records.\n",
                     {"NOTES.md": "# Notes\n"})
    rc, out, err = pt(f, "--root", root)
    check("twin: the same pointer with NOTES.md beside the file resolves, exit 0",
          rc == 0 and "resolved 1, unresolved 0" in out, "rc=%d %r" % (rc, out[-300:]))
    f, d, root = one("# P\n\n## Overview\n\nSee `ROOT_ONLY.md` for the old records.\n")
    write(os.path.join(root, "ROOT_ONLY.md"), "# Root\n")
    rc, out, err = pt(f, "--root", root)
    check("a file found only in a --root resolves, exit 0", rc == 0 and "unresolved 0" in out,
          "rc=%d %r" % (rc, out[-300:]))
    f, d, root = one("# P\n\n## Overview\n\nThe file `MISSING_NOTES.md` is mentioned in passing.\n")
    rc, out, err = pt(f, "--root", root)
    check("a file token on a line with no pointer word is no pointer, exit 0",
          rc == 0 and "pointers 0:" in out, "rc=%d %r" % (rc, out[-300:]))
    for word in ("Evidence:", "Detail in", "lives in", "moved to", "pointer to"):
        f, d, root = one("# P\n\n## Overview\n\n%s `MISSING_NOTES.md` here.\n" % word)
        rc, out, err = pt(f, "--root", root)
        check("the pointer word %r makes a pointer (missing file, exit 3)" % word,
              rc == 3 and unresolved(out, "MISSING_NOTES.md"), "rc=%d %r" % (rc, out[-300:]))
    f, d, root = one("# P\n\n## Overview\n\n```\nSee `MISSING_NOTES.md` here.\n```\n")
    rc, out, err = pt(f, "--root", root)
    check("a line inside a code fence is no pointer, exit 0", rc == 0 and "pointers 0:" in out,
          "rc=%d %r" % (rc, out[-300:]))
    f, d, root = one("# P\n\n## Overview\n\n```\nopened and never closed\n\nSee `NOTES.md` here.\n",
                     {"NOTES.md": "# Notes\n"})
    rc, out, err = pt(f, "--root", root)
    want = "CANNOT TELL: fence opened at line 5 never closes (%s)" % f
    check("A pointers.py on a file whose fence never closes exits 2 with the CANNOT TELL line naming "
          "the opener's line and the file, no Traceback",
          rc == 2 and [l for l in out.splitlines() if l.startswith("CANNOT TELL: fence opened")] == [want]
          and "Traceback" not in err, "rc=%d %r %r" % (rc, out[-300:], err[-300:]))
    f, d, root = one("# P\n\n## Pattern: widget traps\n\nEvidence: `NOTES.md`, same heading.\n",
                     {"NOTES.md": "# Notes\n\n```\n## Pattern: widget traps\n```\n\nThe evidence.\n"})
    rc, out, err = pt(f, "--root", root)
    check("A same heading: the target holds the heading only inside a fenced example, so the pointer "
          "does not resolve, exit 3", rc == 3 and unresolved(out, "NOTES.md"), "rc=%d %r" % (rc, out[-300:]))
    f, d, root = one("# P\n\n## Overview\n\nSee `CLAUDE_DECISIONS_<YYYY-MM>.md` and `split_*/` and "
                     "`https://example.com/a.md` and `git log -1`.\n")
    rc, out, err = pt(f, "--root", root)
    check("a placeholder, a glob folder, a URL and a command are no file pointers, exit 0",
          rc == 0 and "pointers 0:" in out, "rc=%d %r" % (rc, out[-300:]))
    f, d, root = one("# P\n\n## Overview\n\nSee `tool.py:183` for the cut.\n", {"tool.py": "x = 1\n"})
    rc, out, err = pt(f, "--root", root)
    check("a file:line token points at the file, exit 0", rc == 0 and "resolved 1," in out,
          "rc=%d %r" % (rc, out[-300:]))

    # ------------------------------------------------- folders earlier in the section
    f, d, root = one("# P\n\n## Overview\n\nRun records are under `runs/`.\nSee `A_NOTE.md` for one.\n",
                     {"runs/A_NOTE.md": "# A\n"})
    rc, out, err = pt(f, "--root", root)
    check("a folder named earlier in the same section resolves the pointer, exit 0",
          rc == 0 and "resolved 1," in out, "rc=%d %r" % (rc, out[-300:]))
    f, d, root = one("# P\n\n## Overview\n\nSee `A_NOTE.md` for one.\nRun records are under `runs/`.\n",
                     {"runs/A_NOTE.md": "# A\n"})
    rc, out, err = pt(f, "--root", root)
    check("twin: the folder named AFTER the pointer does not resolve it, exit 3",
          rc == 3 and unresolved(out, "A_NOTE.md"), "rc=%d %r" % (rc, out[-300:]))
    f, d, root = one("# P\n\n## Runs\n\nRun records are under `runs/`.\n\n## Overview\n\n"
                     "See `A_NOTE.md` for one.\n", {"runs/A_NOTE.md": "# A\n"})
    rc, out, err = pt(f, "--root", root)
    check("twin: a folder named in another section does not resolve it, exit 3",
          rc == 3 and unresolved(out, "A_NOTE.md"), "rc=%d %r" % (rc, out[-300:]))

    # ---------------------------------------------------------------- same heading
    cases = [
        ("heading differs in words", "## Pattern: widget traps", "## Pattern: gadget traps", 3),
        ("heading differs only by (N instances) on the pointer side",
         "## Pattern: widget traps (3 instances)", "## Pattern: widget traps", 0),
        ("heading differs only by (N instances) on the target side",
         "## Pattern: widget traps", "## Pattern: widget traps (6 instances)", 0),
        ("headings at different levels with different counts",
         "### Pattern: widget traps (8 instances)", "## Pattern: widget traps (3 instances)", 0),
        ("the target holds only an unrelated heading",
         "## Pattern: widget traps", "## Something else", 3),
    ]
    for name, src, dst, want in cases:
        f, d, root = one("# P\n\n%s\n\nEvidence: `NOTES.md`, same heading.\n" % src,
                         {"NOTES.md": "# Notes\n\n%s\n\nThe evidence.\n" % dst})
        rc, out, err = pt(f, "--root", root)
        check("same heading: %s, exit %d" % (name, want), rc == want, "rc=%d %r" % (rc, out[-300:]))
    f, d, root = one("# P\n\nPreamble. Evidence: `NOTES.md`, same heading.\n",
                     {"NOTES.md": "# Notes\n"})
    rc, out, err = pt(f, "--root", root)
    check("same heading with no heading above the line reads unresolved, exit 3",
          rc == 3 and unresolved(out, "NOTES.md"), "rc=%d %r" % (rc, out[-300:]))

    # ---------------------------------------------------------------- [[name]] links
    f, d, root = one("# P\n\n## Overview\n\nSee [[reference_widget]] for the facts.\n")
    rc, out, err = pt(f, "--root", root)
    check("[[name]] with no --memory-dir is counted as skipped, exit 0",
          rc == 0 and "skipped 1" in out and "SKIPPED: [[reference_widget]]" in out,
          "rc=%d %r" % (rc, out[-300:]))
    mem = folder()
    write(os.path.join(mem, "reference_widget.md"), "# Widget\n")
    rc, out, err = pt(f, "--root", root, "--memory-dir", mem)
    check("[[name]] resolves to <memory-dir>/<name>.md, exit 0",
          rc == 0 and "resolved 1, unresolved 0, skipped 0" in out, "rc=%d %r" % (rc, out[-300:]))
    os.remove(os.path.join(mem, "reference_widget.md"))
    rc, out, err = pt(f, "--root", root, "--memory-dir", mem)
    check("[[name]] missing from the --memory-dir reads unresolved, exit 3",
          rc == 3 and unresolved(out, "reference_widget"), "rc=%d %r" % (rc, out[-300:]))

    # ---------------------------------------------------------------- cannot tell
    rc, out, err = pt(os.path.join(folder(), "CLAUDE.md"), "--root", root)
    check("a missing FILE exits 2", rc == 2 and "CANNOT TELL" in out, "rc=%d %r" % (rc, out))
    rc, out, err = pt(f, "--root", os.path.join(root, "nope"))
    check("a missing --root exits 2", rc == 2 and "CANNOT TELL" in out, "rc=%d %r" % (rc, out))
    rc, out, err = pt(f, "--root", root, "--memory-dir", os.path.join(root, "nope"))
    check("a missing --memory-dir exits 2", rc == 2 and "CANNOT TELL" in out, "rc=%d %r" % (rc, out))

    # ---------------------------------------------------------------- archive hub
    after_txt = AFTER.format(last_run=LAST_RUN + "\n")
    arch_jan = "# Decisions Log Archive - January 2026\n\n" + RECORD.format(rule="")
    f, d, root = one(after_txt, {"CLAUDE_DECISIONS_INDEX.md": INDEX,
                                 "CLAUDE_DECISIONS_2026-01.md": arch_jan,
                                 "CLAUDE_DECISIONS_2026-02.md": "# February\n"})
    ptrs = splitlib.pointers(after_txt, d, [root], None)
    idx = [p for p in ptrs if p.token == "CLAUDE_DECISIONS_INDEX.md"]
    targets = splitlib.pointer_targets(ptrs)
    check("hub: a Last-run line resolves the index",
          len(idx) == 1 and idx[0].status == "RESOLVED", repr(ptrs))
    check("hub: through the index, the archive its ## Archives list names resolves",
          os.path.join(d, "CLAUDE_DECISIONS_2026-01.md") in targets, repr(sorted(targets)))
    check("hub twin: an archive the index does not name stays unresolved",
          os.path.join(d, "CLAUDE_DECISIONS_2026-02.md") not in targets, repr(sorted(targets)))
    rc, out, err = pt(f, "--root", root)
    check("pointers.py on the Last-run line exits 0", rc == 0 and "resolved 1, unresolved 0" in out,
          "rc=%d %r" % (rc, out[-300:]))
    rows_only = INDEX.replace("- `CLAUDE_DECISIONS_2026-01.md`: January 2026 records\n", "")
    ptrs = splitlib.pointers(after_txt, d, [root], None,
                             present={"CLAUDE_DECISIONS_INDEX.md": rows_only.replace(
                                 "`CLAUDE_DECISIONS_2026-01.md`", "`CLAUDE_DECISIONS_2026-02.md`")})
    targets = splitlib.pointer_targets(ptrs)
    check("a 'present' index wins over the disk (its entry row names February, not January)",
          os.path.join(d, "CLAUDE_DECISIONS_2026-02.md") in targets
          and os.path.join(d, "CLAUDE_DECISIONS_2026-01.md") not in targets, repr(sorted(targets)))
    g = folder()
    ptrs = splitlib.pointers(after_txt, g, [], None,
                             present={"CLAUDE_DECISIONS_INDEX.md": INDEX,
                                      "CLAUDE_DECISIONS_2026-01.md": arch_jan})
    targets = splitlib.pointer_targets(ptrs)
    check("names in 'present' resolve with nothing on disk, the hub included",
          os.path.join(g, "CLAUDE_DECISIONS_INDEX.md") in targets
          and os.path.join(g, "CLAUDE_DECISIONS_2026-01.md") in targets, repr(sorted(targets)))

    # ------------------------------------- POINTED (archive) through the hub (a pair)
    def archive_split(rule, last_run=True, month="2026-01"):
        before = BEFORE.format(record=RECORD.format(rule=rule))
        after = AFTER.format(last_run=(LAST_RUN + "\n") if last_run else "")
        arch = "# Decisions Log Archive\n\n" + RECORD.format(rule=rule)
        d = folder()
        b = write(os.path.join(d, "CLAUDE.md.backup-before-split-2026-02-01"), before)
        a = write(os.path.join(d, "CLAUDE.md"), after)
        write(os.path.join(d, "CLAUDE_DECISIONS_INDEX.md"), INDEX)
        write(os.path.join(d, "CLAUDE_DECISIONS_%s.md" % month), arch)
        res = splitlib.classify(before, after, d,
                                lazy=[(os.path.join(d, "CLAUDE_DECISIONS_%s.md" % month), arch)],
                                roots=())
        return b, a, dict((r.item.text, r.label()) for r in res)

    b, a, got = archive_split("")
    check("POINTED (archive): index pointer present, the moved identifier reads POINTED (archive)",
          got.get("srv-arc44") == "POINTED (archive: CLAUDE_DECISIONS_2026-01.md)",
          repr(got.get("srv-arc44")))
    rc, out, err = lc("--before", b, "--after", a)
    check("loss_check on the same split exits 0 and counts POINTED (archive)",
          rc == 0 and "POINTED (archive) 2" in out, "rc=%d %r" % (rc, out[-400:]))
    b, a, got = archive_split("", last_run=False)
    check("POINTED (archive) twin: the pointer line removed, the identifier reads LAZY-ONLY",
          got.get("srv-arc44") == "LAZY-ONLY", repr(got.get("srv-arc44")))
    b, a, got = archive_split("", month="2026-02")
    check("POINTED (archive) twin: a record in an archive the index does not name reads LAZY-ONLY",
          got.get("srv-arc44") == "LAZY-ONLY", repr(got.get("srv-arc44")))

    # ------------------------------------------------------------- archive pointer twin
    b, a, got = archive_split(RULE)
    check("with the index pointer present, the identifier still reads POINTED (archive)",
          got.get("srv-arc44") == "POINTED (archive: CLAUDE_DECISIONS_2026-01.md)",
          repr(got.get("srv-arc44")))
    check("twin: a rule sentence from the same moved record reads LAZY-ONLY",
          got.get(RULE) == "LAZY-ONLY", repr(got.get(RULE)))
    rc, out, err = lc("--before", b, "--after", a)
    check("twin: loss_check exits 3 and names the rule sentence",
          rc == 3 and ("LAZY-ONLY: " + RULE[:-1]) in out, "rc=%d %r" % (rc, out[-400:]))
    rc, out, err = lc("--before", b, "--after", a, "--accept", "nightly widget export straight")
    check("twin: --accept with a fragment of the sentence exits 0",
          rc == 0, "rc=%d %r" % (rc, out[-400:]))

    # ---------------------------------------------------------------- tally shape
    import re as _re
    tally = _re.compile(r"\d+/\d+ passed")
    bad = [l for o in outputs for l in o.splitlines() if tally.search(l)]
    check("tally shape: no pointers.py or loss_check output line looks like a test tally",
          not bad, repr(bad[:3]))

    for d in tmpdirs:
        shutil.rmtree(d, ignore_errors=True)

    if not checks:
        print("0/0 passed -- the harness ran NO checks, which is a harness bug")
        return 1
    failed = [c for c in checks if not c[1]]
    for name, ok, detail in checks:
        if not ok:
            print("  FAILED " + name)
            print("         " + detail.replace("\n", "\n         ")[:400])
    print("%d/%d passed" % (len(checks) - len(failed), len(checks)))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
