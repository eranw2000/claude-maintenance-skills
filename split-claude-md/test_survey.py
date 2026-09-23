#!/usr/bin/env python3
"""Tests for survey.py.

Every check asserts on real output from a real subprocess run against a real
fixture file. Row 0 is a CONTROL whose value is known: if it ever fails, the
harness is broken rather than the script, which is the only way to tell a clean
run from a run that checked nothing.

Run:  python3 test_survey.py
"""

import os
import re
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
SURVEY = os.path.join(HERE, "survey.py")

STANDARD = """# Project

## Project Overview

Context.

## Decisions Log

### 2026-05-01: First thing
body line
body line

### 2026-06-15: Second thing
body line

### 2026-07-20: Third thing
body line

## Custom Skills (project-level)

a table
"""

DATED_SECTIONS = """# Project

## Shipped packs

A list that carries no date.

## Security posture (audited 2026-07-16)

body line
body line

## The seventh pack: drawio-diagram-skill (2026-08-02)

body line

## Build cycle 1: RAN and SHIPPED (2026-08-09)

body line
"""\
    + "body line\n" * 40

VERSION_KEYED = """# Project

## Recalibration History

### v4.10.5 (2026-05-03) - retune the thresholds
body line

### v4.11.0 (2026-06-03) - second retune
body line
"""

NO_DATES = """# Project

## Overview

text

## Conventions

text
"""

NO_HEADINGS = "just some prose\nand another line\n"

DENY_AND_CANDIDATE = ("# Project\n\n## Directory Conventions\n\n"
                      + "a line of terminology\n" * 40
                      + "\n## Architecture\n\n### An undated subsection\n\n"
                      + "a line of reference material\n" * 40
                      + "\n## Tiny Section\n\nshort\n")

# The dated-BULLET convention, modeled on a real wiki project's file.
# The decoy section uses the REAL instance-row shape (date at line START, no
# paren): a paren-dated decoy would pass under a broken matcher and prove
# nothing. The config bullet (early colon, incidental mid-line date) and the
# pointer bullet (date RANGE) pin the two measured false-positive shapes.
_REC = "body words for a record entry, long enough to dominate the section. "
BULLETS = ("# Project\n\n"
           "## Terminology\n\n"
           "- **The framework name** (2026-07-03): decided once, and this"
           " single bullet dominates the tiny section it lives in.\n\n"
           "## Where things are\n\n"
           "- Repo / code: lives under the usual path, with several undated"
           " reference notes that pad this section well past the share floor's"
           " reach, so its two dated bullets stay a minority of its chars.\n"
           "- More reference prose: an undated bullet carrying yet more"
           " padding so the dated pair below cannot reach sixty percent.\n"
           "- **Diagram note A** (2026-07-11): dated but small.\n"
           "- **Diagram note B** (2026-07-14): dated but small.\n\n"
           "## Demo presentation set\n\n"
           "- **Diagram set A** (2026-07-15): six rendered diagrams for"
           " presenting the methodology, read from the live config files.\n"
           "- **Diagram set B** (2026-07-16): the narrative and presenting"
           " order, with the two corrected facts noted inline.\n\n"
           "## Known Patterns & Gotchas\n\n"
           "### Pattern: a decoy shape that recurs (3 instances)\n\n"
           "**Instances:**\n"
           "- 2026-07-12 (`a1b2c3d`, PR #1): dated at line START with no"
           " paren, which is the real instance-row shape.\n"
           "- 2026-07-15 (`b2c3d4e`, PR #2): second instance row.\n"
           "- 2026-07-16 (`c3d4e5f`, PR #3): third instance row.\n\n"
           "## App essentials\n\n"
           "- Stack: the app runs over websockets.\n"
           "- Render service is live: `srv-x0` at https://example.test."
           " Confirmed the plan (2026-06-11).\n"
           "- **Older shipped entries archived** (2026-06-06 -> 2026-08-01):"
           " full text in the dated archive files.\n"
           "- Shipped (2026-08-02): **THE FIRST RECORD.** " + _REC * 10 + "\n"
           "- Shipped (2026-08-03): **THE SECOND RECORD.** " + _REC * 10 + "\n"
           "- **SHIPPED (2026-08-04): THE THIRD RECORD.** " + _REC * 10 + "\n"
           "- **SHIPPED (2026-08-05) A RECORD WITHOUT A COLON** short body.\n"
           "- **SHIPPED (2026-08-10): THE FOURTH RECORD.** " + _REC * 10 + "\n"
           "### Not a record, only a subheading\n\n"
           + "pad line under the subheading\n" * 20)

# BOTH conventions at once: dated '### ' entries in a VARIANT-NAMED section
# (nothing in the name deny list matches "Ship history") plus a qualifying
# bullet section. Pins the precedence (entry wins) and the evidence-derived
# Phase C denial of the entries' parent.
MIXED = ("# Project\n\n"
         "## Front matter maps\n\n" + "an undated reference line\n" * 40 + "\n"
         "## Ship history\n\n"
         "### 2026-05-01: First entry\n" + "body line\n" * 160 + "\n"
         "### 2026-06-15: Second entry\n" + "body line\n" * 160 + "\n"
         "## Field notes\n\n"
         "- Shipped (2026-07-01): a bullet-shaped record with body enough to"
         " clear the share floor in this small section, easily.\n"
         "- Shipped (2026-07-02): another bullet-shaped record with body"
         " enough to clear the floor beside its sibling.\n\n"
         "## Rear reference\n\n" + "an undated reference line\n" * 40)


def run(path, *extra):
    cmd = [sys.executable, SURVEY, path] + list(extra)
    p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    return p.returncode, p.stdout.decode("utf-8"), p.stderr.decode("utf-8")


def summary_of(out):
    for ln in out.split("\n"):
        if ln.startswith("SUMMARY "):
            return ln.strip()
    return ""


def main():
    tmp = tempfile.mkdtemp(prefix="survey-test-")
    files = {}
    for name, body in [("standard.md", STANDARD), ("dated.md", DATED_SECTIONS),
                       ("version.md", VERSION_KEYED), ("nodates.md", NO_DATES),
                       ("noheadings.md", NO_HEADINGS), ("deny.md", DENY_AND_CANDIDATE),
                       ("bullets.md", BULLETS), ("mixed.md", MIXED)]:
        p = os.path.join(tmp, name)
        open(p, "w", encoding="utf-8").write(body)
        files[name] = p

    def write(d, name, body):
        q = os.path.join(d, name)
        open(q, "w", encoding="utf-8").write(body)
        return q

    checks = []

    def check(name, ok, detail=""):
        # Coerce detail: a non-string (a list, a match object) would crash the
        # failure PRINTER, killing the run after the first failed rows and
        # swallowing every later verdict -- the checker-dies shape.
        if not isinstance(detail, str):
            detail = repr(detail)
        checks.append((name, bool(ok), detail))

    # 0. CONTROL: the harness can run the script at all and gets a summary line.
    rc, out, err = run(files["standard.md"])
    check("CONTROL harness runs survey.py and gets a SUMMARY line",
          rc == 0 and summary_of(out).startswith("SUMMARY "),
          "rc=%d summary=%r err=%r" % (rc, summary_of(out), err[:120]))

    # 1. Standard convention: records at '### ' level.
    check("standard file detects convention=entry with 3 dated records",
          "convention=entry" in summary_of(out) and "dated=3" in summary_of(out),
          summary_of(out))

    # 2. The variant this skill got wrong before: dated '## ' sections.
    rc, out, err = run(files["dated.md"])
    s = summary_of(out)
    check("dated '## ' sections detect convention=section with 3 records",
          rc == 0 and "convention=section" in s and "dated=3" in s, s)
    check("the section variant is announced as a VARIANT, not applied silently",
          "VARIANT" in out, out[:200])

    # 3. Version-keyed headings, date inside parentheses.
    rc, out, err = run(files["version.md"])
    s = summary_of(out)
    check("version-keyed '### vN (date)' headings are read as dated entries",
          rc == 0 and "convention=entry" in s and "dated=2" in s, s)
    check("the date is pulled from the parentheses, not the version number",
          "2026-05-03" in out and "4.10.5" not in s, s)

    # 4. Nothing dated: must say so loudly rather than print an empty table.
    rc, out, err = run(files["nodates.md"])
    check("a file with no dated records says Phase A cannot run",
          "convention=none" in summary_of(out) and "Phase A cannot run" in out,
          summary_of(out))

    # 5. No headings at all: loud, and a non-zero exit.
    rc, out, err = run(files["noheadings.md"])
    check("a file with no headings exits non-zero and says so",
          rc == 2 and "NO HEADINGS FOUND" in out, "rc=%d" % rc)

    # 6. Cut arithmetic against the standard fixture.
    rc, out, err = run(files["standard.md"], "--cut-date", "2026-06-01")
    s = summary_of(out)
    check("cut at 2026-06-01 archives 1 and keeps 2",
          "archive=1" in s and "keep=2" in s, s)
    check("the archived record is bucketed into its own month file",
          "CLAUDE_DECISIONS_2026-05.md" in out
          and "CLAUDE_DECISIONS_2026-06.md" not in out, out[:400])

    # 7. A cut that moves nothing must be called out, not reported as a split.
    rc, out, err = run(files["standard.md"], "--cut-date", "2020-01-01")
    check("a cut that archives nothing prints the NOTE",
          "archive=0" in summary_of(out) and "archives NOTHING" in out,
          summary_of(out))

    # 8. keep-days arithmetic, pinned with --today so the run is reproducible.
    rc, out, err = run(files["dated.md"], "--keep-days", "10", "--today", "2026-08-09")
    s = summary_of(out)
    check("--keep-days 10 from 2026-08-09 archives the July record only",
          "archive=1" in s and "keep=2" in s, s)

    # 9. Deny list beats size; a large ordinary section is a candidate.
    rc, out, err = run(files["deny.md"])
    body = out.split("PHASE C CANDIDATES")[-1]
    check("a large deny-list section is never a Phase C candidate",
          "Directory Conventions" not in body.split("never extract")[0], body[:300])
    check("a large ordinary section IS a Phase C candidate",
          "Architecture" in body.split("never extract")[0], body[:300])
    check("a small section is not a candidate",
          "Tiny Section" not in body, body[:300])

    # 9b. SHAPE classification and the FLOOR estimate (added 2026-08-12 after
    # Phase C offered 13 rule sections on the global CLAUDE.md as extraction
    # candidates -- following it would have moved behaviour rules out of the
    # always-loaded file).
    rule_sec = ("## Big Rule Section\n\n"
                + ("You must never do this and you should always do that. "
                   "Never skip the check.\n"
                   "Use the tool. Verify the output. Do NOT assume it worked.\n") * 24)
    ref_sec = ("## Big Reference Section\n\n"
               + "| col a | col b | col c |\n|---|---|---|\n"
               + "".join("| v%d | w%d | x%d |\n" % (i, i, i) for i in range(60)))
    # Deliberately sized into the gap: over Phase D's 900 chars, but under
    # Phase C's 3000 chars AND 30 lines, so it is NOT a Phase C candidate.
    mid_rule = ("## Mid Rule Section\n\n"
                + ("You must never skip this step, and you should always check "
                   "the result before proceeding. Do NOT assume it worked.\n") * 11)
    shp = write(tmp, "shape.md", "# P\n\n" + rule_sec + "\n" + ref_sec + "\n")
    rc, out, err = run(shp)
    cand = out.split("PHASE C CANDIDATES")[-1]
    check("a large obligation-heavy section is labelled RULE",
          re.search(r"RULE\s+L\d+\s+Big Rule Section", cand) is not None, cand[:400])
    check("CONTRAST: a large table-heavy section is labelled REFERENCE",
          re.search(r"REFERENCE\s+L\d+\s+Big Reference Section", cand) is not None,
          cand[:400])
    check("with a REFERENCE present, the all-rules NOTE is NOT printed",
          "every candidate here is RULE-shaped" not in cand, cand[:400])

    # A rule section that HAPPENS to contain tables, with its obligations in
    # UPPERCASE (the house style: MUST / NEVER / Do NOT). The obligations must
    # veto the REFERENCE call, or a rules section gets Phase-C'd out of context.
    # This fixture exists because the lowercase-obligation one could not tell
    # whether case-insensitive matching was working: the pattern is lowercase, so
    # dropping re.I still matched it.
    upper_rule = ("## Upper Rule With Tables\n\n"
                  # ONLY uppercase obligations: no lowercase "should"/"must" to
                  # carry the count, and no line-start imperative verb, so the
                  # case-insensitive flag is the single thing keeping this RULE.
                  + "The gate MUST fire before deploy and MUST NEVER be skipped.\n" * 7
                  + "| stage | gate | owner |\n|---|---|---|\n"
                  + "".join("| s%d | g%d | o%d |\n" % (i, i, i) for i in range(30)))
    shpu = write(tmp, "shape_upper.md", "# P\n\n" + upper_rule + "\n")
    rc, out, err = run(shpu)
    cand_u = out.split("PHASE C CANDIDATES")[-1]
    check("UPPERCASE obligations veto REFERENCE on a table-heavy rule section",
          re.search(r"RULE\s+L\d+\s+Upper Rule With Tables", cand_u) is not None,
          cand_u[:400])

    shp2 = write(tmp, "shape_rules_only.md", "# P\n\n" + rule_sec + "\n")
    rc, out, err = run(shp2)
    check("when every candidate is rule-shaped the NOTE says Phase C has nothing to do",
          "every candidate here is RULE-shaped" in out, out[-700:])
    check("the FLOOR block is printed with an ESTIMATE",
          "FLOOR" in out and "ESTIMATE" in out, out[-700:])

    # The floor must count rule sections BELOW Phase C's 3000-char threshold but
    # above Phase D's 900, or it under-predicts the achievable cut. Using Phase
    # C's threshold predicted 28% on the real file where 51% was achieved.
    shp3 = write(tmp, "shape_mid.md", "# P\n\n" + mid_rule + "\n")
    rc, out, err = run(shp3)
    m = re.search(r"(\d+) RULE-shaped sections over (\d+) ch", out)
    check("a section under Phase C's threshold still counts toward the floor",
          m is not None and int(m.group(1)) >= 1 and int(m.group(2)) == 900,
          out[-700:])
    check("that section is NOT a Phase C candidate (so the two thresholds differ)",
          "Mid Rule Section" not in out.split("PHASE C CANDIDATES")[-1]
          .split("FLOOR")[0], out[-900:])

    # 10. The target is required, and contradictory cut flags are refused.
    p = subprocess.run([sys.executable, SURVEY],
                       stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    check("running with no target file exits non-zero", p.returncode != 0,
          "rc=%d" % p.returncode)
    rc, out, err = run(files["standard.md"], "--cut-date", "2026-01-01",
                       "--keep-days", "30")
    check("--cut-date and --keep-days together are refused",
          rc == 2 and "not both" in err, "rc=%d err=%r" % (rc, err[:80]))

    # 11. The surveyed file is echoed back, so a run cannot certify the wrong file.
    rc, out, err = run(files["standard.md"])
    check("the resolved target path is printed in the header",
          files["standard.md"] in out, out[:120])

    # 12. The dated-BULLET convention (the shape survey.py answered
    # convention=none on, 2026-08-10, while offering the decisions log for
    # Phase C extraction).
    rc, out, err = run(files["bullets.md"])
    s = summary_of(out)
    check("dated top-level bullets detect convention=bullet with 5 records",
          rc == 0 and "convention=bullet" in s and "dated=5" in s, s)

    # 13. ONE records section, chosen by size; the runner-up is printed, not used.
    conv = out.split("CONVENTION")[-1].split("DATED RECORDS")[0]
    check("the verdict names App essentials as the single records section",
          "TOP-LEVEL BULLETS inside '## App essentials'" in conv
          and "runner-up: '## Demo presentation set'" in conv, conv[:400])

    # 14. The evidence counts are exact: 6 record bullets in 2 qualifying
    # sections. Pins the paren anchor (a widened matcher counts the decoy's
    # rows), the colon and range exclusions, the >=2 floor (Terminology has 1)
    # and the 60% share floor (Where things are has 2 dated bullets under it).
    check("record-bullet evidence counts are exact (7 in 2 sections)",
          "dated record bullets:   7 (in 2 qualifying section(s))" in out,
          [l for l in out.split("\n") if "record bullets" in l])

    # 15a. Both measured false-positive shapes are excluded from the records.
    rec_block = out.split("DATED RECORDS")[-1].split("PHASE C")[0]
    check("the pointer bullet and the config bullet are not records",
          "Older shipped entries archived" not in rec_block
          and "Render service is live" not in rec_block, rec_block[:300])

    # 15b. The decoy section (start-anchored dates, no paren) is neither the
    # records section nor a runner-up.
    check("the Known Patterns decoy is not read as a records section",
          "Known Patterns" not in conv, conv[:400])

    # 16. Cut arithmetic over bullet records.
    rc, out, err = run(files["bullets.md"], "--cut-date", "2026-08-04")
    s = summary_of(out)
    check("bullet cut at 2026-08-04 archives 2 and keeps 3, bucketed to 2026-08",
          "archive=2" in s and "keep=3" in s
          and "CLAUDE_DECISIONS_2026-08.md  <- 2 records" in out, s)

    # 17. Phase C: the section HOLDING the records is denied by evidence, not
    # offered as a candidate, however it is named.
    body = out.split("PHASE C CANDIDATES")[-1]
    check("the records section is evidence-denied for Phase C, not a candidate",
          "App essentials" not in body.split("never extract")[0]
          and "holds the dated records" in body
          and "App essentials" in body.split("holds the dated records")[-1],
          body[:400])

    # 18. Precedence is written down: entries beat bullets when both exist.
    rc, out, err = run(files["mixed.md"])
    s = summary_of(out)
    check("a file with dated entries AND bullet records stays convention=entry",
          "convention=entry" in s and "dated=2" in s, s)

    # 19. The entry convention's variant-name hole: the parent section of the
    # dated entries is evidence-denied even when the name deny list misses it.
    body = out.split("PHASE C CANDIDATES")[-1]
    check("a variant-named entries parent is evidence-denied for Phase C",
          "Ship history" not in body.split("never extract")[0]
          and "Ship history" in body.split("holds the dated records")[-1],
          body[:400])
    check("ordinary sections flanking the entries stay candidates",
          "Front matter maps" in body.split("never extract")[0]
          and "Rear reference" in body.split("never extract")[0],
          body[:400])

    # 20. Bullet extent is clipped at the next bullet or heading: every
    # record prints small chars; a broken extent balloons one past 800.
    rc, out, err = run(files["bullets.md"])
    rec_block = out.split("DATED RECORDS")[-1].split("PHASE C")[0]
    sizes = re.findall(r"2026-08-\d\d\s+(\d+)", rec_block)
    check("every bullet record extent stays under 800 chars",
          len(sizes) == 5 and max(int(x) for x in sizes) < 800,
          "sizes=%r" % sizes)

    # 21. A candidate-sized DATED section is evidence-denied for Phase C.
    rc, out, err = run(files["dated.md"])
    body = out.split("PHASE C CANDIDATES")[-1]
    check("a candidate-sized dated section is evidence-denied for Phase C",
          "Build cycle 1" not in body.split("never extract")[0]
          and "Build cycle 1" in body.split("holds the dated records")[-1],
          body[:400])

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
