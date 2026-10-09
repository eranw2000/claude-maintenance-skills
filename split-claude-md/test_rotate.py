#!/usr/bin/env python3
"""Tests for rotate.py.

rotate.py is the only script in this skill that DELETES content from a real
CLAUDE.md, so it is the one that most needs a suite. Every check runs against a
throwaway fixture in a temp directory; nothing here reads or writes a real
project file.

Row 0 is a CONTROL whose value is known. If it ever fails, the harness is broken
rather than the script, which is the only way to tell a clean run from a run that
checked nothing.

Run:  python3 test_rotate.py
"""

import os
import re
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROTATE = os.path.join(HERE, "rotate.py")
sys.path.insert(0, HERE)
import rotate  # noqa: E402


# Five dated '## ' records across two months, plus one undated section and one
# '### ' subheading that CARRIES A DATE and must be neither a record nor a
# record boundary. Counts are deliberately unequal: 5 dated records, 3 moved,
# 2 archive months, so no assertion can pass by reading the wrong number.
SECTION = """# Project

## Overview

This section carries no date at all and must never be treated as a record.

## Alpha record about the widget engine (2026-05-03)

This is the alpha body line, which is comfortably longer than forty chars.

### A subheading inside alpha dated 2026-05-04

Alpha body continues after the subheading, and this line is also long enough.

## Epsilon record about the token budget (2026-05-20)

This is the epsilon body line, which is comfortably longer than forty chars.

## Beta record concerning the crawler (2026-06-11)

This is the beta body line, which is comfortably longer than forty chars now.

## Gamma record on the deploy path (2026-06-22)

This is the gamma body line, which is comfortably longer than forty chars now.

## Delta record about the renderer (2026-08-09)

This is the delta body line, which is comfortably longer than forty chars now.
Measured on 2026-03-01, a date in ordinary PROSE that must never be read as a
record of its own. Records cite dates in their bodies constantly, and this one
is older than every heading, so a parser that mistook it would move it away.
"""

# Three dated '### ' entries. Entry one is ended by another '### ', entry two by
# a '## ', which are two different boundary rules in the same fixture.
ENTRY = """# Project

## Decisions Log

### 2026-04-02: Entry one about the parser

Entry one body, which is comfortably longer than forty characters in total.

### 2026-04-18: Entry two about the loader

Entry two body, which is comfortably longer than forty characters in total.

## Some Other Section

### 2026-09-01: Entry three under a different section

Entry three body, which is comfortably longer than forty characters total.

## Trailing Section With No Date

tail content
"""

# A moved record whose body line also appears verbatim inside a KEPT record.
# After the move that fragment still occurs once in CLAUDE.md, so the
# both-directions check must FAIL and the script must exit 2.
COLLIDING = """# Project

## Old record that is going to move (2026-05-05)

A duplicated sentence that is comfortably longer than forty characters here.

## New record that stays behind (2026-08-05)

A duplicated sentence that is comfortably longer than forty characters here.
"""

NO_DATES = """# Project

## Overview

No dated headings anywhere in this file at all.

## Another Section

Still nothing dated.
"""


def run(path, *extra):
    cmd = [sys.executable, ROTATE, path] + list(extra)
    p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    return p.returncode, p.stdout.decode("utf-8"), p.stderr.decode("utf-8")


def fresh(body, name="CLAUDE.md"):
    """A throwaway directory holding one fixture file. Never a real project."""
    d = tempfile.mkdtemp(prefix="rotate-test-")
    p = os.path.join(d, name)
    with open(p, "w", encoding="utf-8") as fh:
        fh.write(body)
    return d, p


def read(path):
    """Contents, or "" when the file is absent.

    Returning "" rather than raising is deliberate. When a mutation stops a file
    being written, a raising helper aborts the whole run, the suite exits
    non-zero with no named failure, and the mutation is scored KILLED while the
    check aimed at it never ran. An empty string instead lets every "is X in the
    archive" check fail by name, which is the only outcome that proves anything.
    """
    if not os.path.exists(path):
        return ""
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def pick(records, needle):
    """First record whose title holds needle, or a blank stand-in.

    Never raises. A helper that can raise turns a mutation into a CRASH, and a
    crash is a kill by exit code that proves nothing about the check it was
    aimed at, so the mutation gets a false pin while the intended check never
    runs. See the mutation-harness blind spot on crash-as-kill.
    """
    for r in records:
        if needle in r[3]:
            return r
    return (0, 0, "", "")


def text_of(lines, rec):
    return "".join(lines[rec[0]:rec[1]])


def parse(lines, convention):
    """parse_records that returns [] instead of raising, for the happy paths.

    Same reason as read(): a mutation that makes a valid convention fall through
    to the refusal branch would otherwise abort the run with no named failure.
    The check that the refusal DOES raise calls parse_records directly, so this
    wrapper cannot hide it.
    """
    try:
        return rotate.parse_records(lines, convention)
    except Exception:                                          # noqa: BLE001
        return []


def main():
    checks = []

    def check(name, ok, detail=""):
        # Coerce detail: a non-string would crash the failure PRINTER and
        # swallow every verdict after the first failed row.
        if not isinstance(detail, str):
            detail = repr(detail)
        checks.append((name, bool(ok), detail))

    tmpdirs = []

    def sandbox(body, name="CLAUDE.md"):
        d, p = fresh(body, name)
        tmpdirs.append(d)
        return d, p

    # ---------------------------------------------------------------- CONTROL
    d, p = sandbox(SECTION)
    rc, out, err = run(p, "--convention", "section", "--cut-date", "2026-07-01")
    check("CONTROL harness runs rotate.py and gets a FILE line",
          rc == 0 and out.startswith("FILE"),
          "rc=%d out=%r err=%r" % (rc, out[:120], err[:200]))

    # ------------------------------------------------------ parse_records unit
    slines = SECTION.splitlines(keepends=True)
    elines = ENTRY.splitlines(keepends=True)

    srecs = parse(slines, "section")
    check("section convention finds exactly the 5 dated '## ' records",
          len(srecs) == 5, "got %d: %r" % (len(srecs), [r[2] for r in srecs]))

    check("an UNDATED '## ' heading is not a record",
          all("Overview" not in r[3] for r in srecs),
          repr([r[3] for r in srecs]))

    # A date in prose is the common case in these files, and it is only excluded
    # because the line does not start with the record prefix. Nothing else
    # rejects it, so this is the check that holds that filter in place.
    check("a date inside a record's BODY PROSE is not a record",
          all("ordinary PROSE" not in r[3] for r in srecs)
          and all(r[2] != "2026-03-01" for r in srecs),
          repr([(r[2], r[3][:40]) for r in srecs]))

    check("a dated '### ' subheading is NOT a record under section convention",
          all("subheading inside alpha" not in r[3] for r in srecs),
          repr([r[3] for r in srecs]))

    # What actually excludes a '### ' line under the section convention is the
    # SPACE in the '## ' prefix, not the three explicit "and not startswith
    # ('### ')" guards in parse_records. Those three are unreachable: no string
    # can start with both prefixes, because position 2 is a space in one and a
    # hash in the other. Mutation testing found all three surviving, and this
    # check records why, so nobody reads them as a coverage hole. Both halves
    # below must hold, so a change to either prefix fails here first.
    check("'### ' and '## ' are mutually exclusive prefixes, which is the real filter",
          not "### x".startswith("## ") and "## x".startswith("## ")
          and "### x".startswith("### "),
          "'### x' vs '## ': %s" % "### x".startswith("## "))

    alpha = pick(srecs, "Alpha")
    alpha_text = text_of(slines, alpha)
    check("a dated '### ' subheading does NOT end its parent section record",
          "Alpha body continues after the subheading" in alpha_text,
          alpha_text[:200])
    # The non-empty half is load-bearing: a "does not contain" assertion on an
    # empty string passes vacuously, so a broken parser would score this green.
    check("a section record ENDS at the next '## ' heading",
          alpha_text != "" and "Epsilon record" not in alpha_text,
          "len=%d tail=%r" % (len(alpha_text), alpha_text[-160:]))

    erecs = parse(elines, "entry")
    check("entry convention finds exactly the 3 dated '### ' entries",
          len(erecs) == 3, "got %d: %r" % (len(erecs), [r[2] for r in erecs]))

    e_one_text = text_of(elines, pick(erecs, "Entry one"))
    check("an entry record ENDS at the next '### ' heading",
          "Entry one body" in e_one_text and "Entry two" not in e_one_text,
          "len=%d tail=%r" % (len(e_one_text), e_one_text[-160:]))

    e_two_text = text_of(elines, pick(erecs, "Entry two"))
    check("an entry record ENDS at a '## ' heading too",
          "Entry two body" in e_two_text and "Some Other Section" not in e_two_text,
          "len=%d tail=%r" % (len(e_two_text), e_two_text[-160:]))

    check("entry convention does NOT treat a '## ' heading as a record",
          all(not r[3].startswith("## ") for r in erecs),
          repr([r[3] for r in erecs]))

    try:
        rotate.parse_records(slines, "bogus")
        raised = ""
    except ValueError as exc:
        raised = str(exc)
    check("an unknown convention RAISES rather than silently finding nothing",
          "bogus" in raised, "raised=%r" % raised)

    check("a file with no dated headings yields zero records",
          rotate.parse_records(NO_DATES.splitlines(keepends=True), "section") == [],
          repr(rotate.parse_records(NO_DATES.splitlines(keepends=True), "section")))

    # ------------------------------------------------------------ backup unit
    bd = tempfile.mkdtemp(prefix="rotate-test-backup-")
    tmpdirs.append(bd)
    bp = os.path.join(bd, "thing.md")
    with open(bp, "w", encoding="utf-8") as fh:
        fh.write("payload one")

    b1 = rotate.backup(bp, "2026-08-15")
    check("backup creates a dated copy with the original bytes",
          b1 is not None and read(b1) == "payload one", "b1=%r" % b1)

    with open(bp, "w", encoding="utf-8") as fh:
        fh.write("payload two")
    b2 = rotate.backup(bp, "2026-08-15")
    check("a SECOND backup on the same day does not overwrite the first",
          b1 != b2 and read(b1) == "payload one" and read(b2) == "payload two",
          "b1=%r b2=%r" % (b1, b2))

    try:
        missing = rotate.backup(os.path.join(bd, "absent.md"), "2026-08-15")
        missing_err = ""
    except Exception as exc:                                   # noqa: BLE001
        missing, missing_err = "raised", "%s: %s" % (type(exc).__name__, exc)
    check("backup of a MISSING file returns None instead of crashing",
          missing is None, "got=%r err=%s" % (missing, missing_err))

    # ------------------------------------------------------- occurrences unit
    check("occurrences counts OCCURRENCES, not lines (two on one line)",
          rotate.occurrences("aXbXc", "X") == 2,
          str(rotate.occurrences("aXbXc", "X")))
    check("occurrences of an absent needle is 0",
          rotate.occurrences("abc", "zz") == 0)
    check("occurrences of an EMPTY needle is 0, not the string length",
          rotate.occurrences("abc", "") == 0,
          str(rotate.occurrences("abc", "")))

    # ------------------------------------------------------ fragments_of unit
    frag_lines = [
        "## A title that is well over twelve characters long\n",
        "\n",
        "A body line that is comfortably longer than forty characters in total.\n",
    ]
    fr = rotate.fragments_of(frag_lines, 0, 3)
    check("fragments_of returns BOTH the title and a body fragment",
          len(fr) == 2 and fr[0].startswith("## A title") and fr[1].startswith("A body line"),
          repr(fr))

    short_title = ["## hi\n", "\n",
                   "A body line that is comfortably longer than forty characters here.\n"]
    fr2 = rotate.fragments_of(short_title, 0, 3)
    check("a title of 12 chars or fewer is NOT used as a fragment",
          len(fr2) == 1 and fr2[0].startswith("A body line"), repr(fr2))

    short_body = ["## A title that is well over twelve characters long\n", "\n", "tiny\n"]
    fr3 = rotate.fragments_of(short_body, 0, 3)
    check("a body line of 40 chars or fewer is NOT used as a fragment",
          len(fr3) == 1 and fr3[0].startswith("## A title"), repr(fr3))

    long_body = ["## A title that is well over twelve characters long\n",
                 "x" * 400 + "\n"]
    fr4 = rotate.fragments_of(long_body, 0, 2)
    check("a body fragment is truncated to 160 chars",
          len(fr4) == 2 and len(fr4[1]) == 160, repr([len(x) for x in fr4]))

    # ------------------------------------------------------------- dry run CLI
    d, p = sandbox(SECTION)
    before = read(p)
    rc, out, err = run(p, "--convention", "section", "--cut-date", "2026-07-01")
    check("dry run exits 0", rc == 0, "rc=%d err=%r" % (rc, err[:200]))
    check("dry run CHANGES NOTHING on disk", read(p) == before)
    _ls = sorted(os.listdir(d))
    _run = [n for n in _ls if re.fullmatch(r"split_\d{4}-\d{2}-\d{2}", n)]
    check("dry run creates no archive and no index (only CLAUDE.md and its run folder)",
          len(_ls) == 2 and "CLAUDE.md" in _ls and len(_run) == 1, repr(_ls))
    check("dry run writes exactly REPORT.dry.md in its run folder",
          len(_run) == 1 and sorted(os.listdir(os.path.join(d, _run[0]))) == ["REPORT.dry.md"],
          repr(_ls))
    check("dry run says it is a dry run", "DRY RUN" in out, out[-200:])
    check("dry run reports 4 move and 1 keep at that cut date",
          "4 move, 1 keep" in out, [l for l in out.split("\n") if "records " in l])

    # ---------------------------------------------------------------- --keep
    rc, out, err = run(p, "--convention", "section", "--cut-date", "2026-07-01",
                       "--keep", "crawler")
    check("--keep protects an OLD record from moving",
          "3 move, 2 keep" in out, [l for l in out.split("\n") if "records " in l])
    check("--keep reports WHICH fragment matched",
          "--keep matched 'crawler'" in out, out[out.find("KEEP:"):][:400])
    check("--keep matches case-insensitively",
          "3 move, 2 keep" in run(p, "--convention", "section",
                                  "--cut-date", "2026-07-01", "--keep", "CRAWLER")[1])
    check("a record NEWER than the cut is kept for the other reason",
          "newer than cut" in out, out[out.find("KEEP:"):][:400])
    check("a --keep fragment matching nothing protects nothing",
          "4 move, 1 keep" in run(p, "--convention", "section",
                                  "--cut-date", "2026-07-01", "--keep", "zzz")[1])

    # ------------------------------------------------------------ no records
    d2, p2 = sandbox(NO_DATES)
    rc, out, err = run(p2, "--convention", "section", "--cut-date", "2026-07-01")
    check("a file with no dated records exits 1 and says so",
          rc == 1 and "No dated records" in out, "rc=%d out=%r" % (rc, out[:200]))
    check("a file with no dated records writes nothing",
          sorted(os.listdir(d2)) == ["CLAUDE.md"], repr(sorted(os.listdir(d2))))

    # --------------------------------------------------- nothing to move CLI
    d3, p3 = sandbox(SECTION)
    rc, out, err = run(p3, "--convention", "section", "--cut-date", "2026-01-01", "--apply")
    check("--apply with nothing old enough exits 0 and refuses to write",
          rc == 0 and "Nothing to move" in out, "rc=%d out=%r" % (rc, out[-200:]))
    check("--apply with nothing to move leaves the directory untouched",
          sorted(os.listdir(d3)) == ["CLAUDE.md"], repr(sorted(os.listdir(d3))))

    # ------------------------------------------------------------- apply CLI
    d4, p4 = sandbox(SECTION)
    original = read(p4)
    rc, out, err = run(p4, "--convention", "section", "--cut-date", "2026-07-01",
                       "--keep", "crawler", "--apply", "--today", "2026-08-15")
    after = read(p4)
    names = sorted(os.listdir(d4))
    check("--apply exits 0 on a clean run",
          rc == 0, "rc=%d out=%r err=%r" % (rc, out[-400:], err[:200]))
    check("--apply reports that every presence check passed",
          "All presence checks passed" in out, out[-300:])
    check("--apply creates one archive per MONTH, not per record",
          "CLAUDE_DECISIONS_2026-05.md" in names and "CLAUDE_DECISIONS_2026-06.md" in names
          and "CLAUDE_DECISIONS_2026-07.md" not in names, repr(names))
    check("--apply creates the index",
          "CLAUDE_DECISIONS_INDEX.md" in names, repr(names))
    check("--apply backs up CLAUDE.md before writing",
          "CLAUDE.md.backup-before-split-2026-08-15" in names, repr(names))
    check("the backup holds the ORIGINAL bytes",
          read(os.path.join(d4, "CLAUDE.md.backup-before-split-2026-08-15")) == original)

    may = read(os.path.join(d4, "CLAUDE_DECISIONS_2026-05.md"))
    jun = read(os.path.join(d4, "CLAUDE_DECISIONS_2026-06.md"))

    check("a MOVED record's title is gone from CLAUDE.md",
          "Alpha record about the widget engine" not in after, after[:300])
    check("a MOVED record's BODY is gone from CLAUDE.md too, not just its heading",
          "This is the alpha body line" not in after, after[:300])
    check("a MOVED record's title AND body are both in the archive",
          "Alpha record about the widget engine" in may
          and "This is the alpha body line" in may, may[:300])
    check("a record is filed under ITS OWN month",
          "Gamma record on the deploy path" in jun
          and "Gamma record on the deploy path" not in may)
    check("both same-month records land in one archive",
          "Alpha record" in may and "Epsilon record" in may)

    check("a --keep protected record STAYS in CLAUDE.md",
          "Beta record concerning the crawler" in after
          and "This is the beta body line" in after)
    check("a --keep protected record is NOT copied into any archive",
          "Beta record concerning the crawler" not in may + jun)
    check("a record newer than the cut STAYS in CLAUDE.md",
          "Delta record about the renderer" in after)
    check("undated content is untouched",
          "## Overview" in after and "no date at all" in after)
    check("a dated subheading travels WITH its parent record",
          "A subheading inside alpha dated 2026-05-04" in may
          and "A subheading inside alpha dated 2026-05-04" not in after)

    idx = read(os.path.join(d4, "CLAUDE_DECISIONS_INDEX.md"))
    check("the index carries one row per moved record and none per kept record",
          idx.count("- 2026-") == 3 and "Beta record" not in idx,
          repr([l for l in idx.split("\n") if l.startswith("- 2026-")]))
    check("index rows are in chronological order",
          idx.find("2026-05-03") < idx.find("2026-05-20") < idx.find("2026-06-22"))
    check("each index row names the archive file that holds it",
          "CLAUDE_DECISIONS_2026-05.md`" in idx and "CLAUDE_DECISIONS_2026-06.md`" in idx)
    check("a section-convention index records the '## ' heading convention",
          "`## `" in idx, idx[idx.find("convention"):][:200])

    # ---------------------------------------------- second run appends, never
    #                                                overwrites
    rc2, out2, err2 = run(p4, "--convention", "section", "--cut-date", "2026-09-01",
                          "--apply", "--today", "2026-08-16", "--narrative", "Delta record")
    may2 = read(os.path.join(d4, "CLAUDE_DECISIONS_2026-05.md"))
    jun2 = read(os.path.join(d4, "CLAUDE_DECISIONS_2026-06.md"))
    idx2 = read(os.path.join(d4, "CLAUDE_DECISIONS_INDEX.md"))
    aug2 = read(os.path.join(d4, "CLAUDE_DECISIONS_2026-08.md"))
    check("a second run exits 0", rc2 == 0, "rc=%d out=%r" % (rc2, out2[-300:]))
    check("a second run APPENDS to an existing archive, never overwrites it",
          "Beta record concerning the crawler" in jun2
          and "Gamma record on the deploy path" in jun2, jun2[:200])
    check("an appended archive is marked as an additional rotation",
          "additional rotation" in jun2)
    check("a first-time archive gets the header, an appended one does not",
          aug2.startswith("# Decisions Log Archive") and not may2.startswith("\n<!--"))
    check("an untouched archive is left alone by the second run",
          may2 == may)
    check("the index APPENDS rows rather than being regenerated",
          idx2.count("- 2026-") == 5 and "Alpha record" in idx2,
          repr([l for l in idx2.split("\n") if l.startswith("- 2026-")]))
    # Row count alone cannot see this: appending under a SECOND entries heading
    # keeps every row and still leaves the index with two of them.
    check("appending reuses the one entries heading, never adds a second",
          idx2.count("## Entries (chronological)") == 1,
          "count=%d" % idx2.count("## Entries (chronological)"))
    check("every dated record is gone from CLAUDE.md after the second run",
          "Beta record" not in read(p4) and "Delta record" not in read(p4))
    check("the second run backs up under ITS OWN date",
          "CLAUDE.md.backup-before-split-2026-08-16" in os.listdir(d4),
          repr(sorted(os.listdir(d4))))

    # ------------------------------------------------- entry convention apply
    d5, p5 = sandbox(ENTRY)
    rc, out, err = run(p5, "--convention", "entry", "--cut-date", "2026-05-01",
                       "--apply", "--today", "2026-08-15")
    after5 = read(p5)
    apr = read(os.path.join(d5, "CLAUDE_DECISIONS_2026-04.md"))
    check("entry convention applies cleanly",
          rc == 0 and "All presence checks passed" in out, "rc=%d %r" % (rc, out[-300:]))
    check("entry convention moves the two April entries",
          "Entry one about the parser" in apr and "Entry two about the loader" in apr)
    check("entry convention leaves the September entry behind",
          "Entry three under a different section" in after5)
    check("entry convention leaves the OWNING '## ' heading in place",
          "## Decisions Log" in after5 and "## Some Other Section" in after5)
    check("entry convention does not swallow the trailing section",
          "## Trailing Section With No Date" in after5 and "tail content" in after5)
    check("an entry-convention index records the '### ' heading convention",
          "`### `" in read(os.path.join(d5, "CLAUDE_DECISIONS_INDEX.md")))

    # ------------------------------------- the verification can actually FAIL
    d6, p6 = sandbox(COLLIDING)
    rc, out, err = run(p6, "--convention", "section", "--cut-date", "2026-07-01",
                       "--apply", "--today", "2026-08-15")
    check("a moved fragment still present in CLAUDE.md is REPORTED as a failure",
          "FAIL moved" in out, out[-500:])
    check("a verification failure exits 2, not 0",
          rc == 2, "rc=%d" % rc)
    check("a verification failure points at the backup files",
          "Restore from the .backup-before-split" in out, out[-300:])

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
