#!/usr/bin/env python3
"""Tests for the skill's own wiring.

The checks only help if the instructions tell a session to run them. These
checks read SKILL.md and the reference files and assert that:

  - SKILL.md stays under 16,000 characters and carries exactly three pointer
    lines to reference/no-loss-checks.md in place of the hand-typed
    must-survive paragraph (the third is the recall check);
  - reference/no-loss-checks.md names every call it owns, and every flag it
    or phase-a-archive.md names is a real flag of the script it belongs to;
  - its hand Last-run line and Runs row, filled in, equal what rotate.py
    itself writes for the same run;
  - the phase files carry the backup and per-phase check steps;
  - every pointer in the edited files resolves (pointers.py, explicit root).

Row 0 is a CONTROL with a known answer: if it fails, the harness is broken
rather than the text.

Run:  python3 test_wiring.py
"""

import os
import re
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
REF = os.path.join(HERE, "reference")
NLC = os.path.join(REF, "no-loss-checks.md")
NLC_REL = "reference/no-loss-checks.md"
sys.path.insert(0, HERE)
import test_rotate  # noqa: E402

FLAG_RE = re.compile(r"(?<![\w-])(--[a-z][a-z-]*[a-z])")
HELP_FLAG_RE = re.compile(r"(?<![\w-])(--[a-z][a-z-]*[a-z])")


def read(path):
    try:
        with open(path, encoding="utf-8") as fh:
            return fh.read()
    except (OSError, UnicodeDecodeError):
        return ""


def help_flags(script):
    p = subprocess.run([sys.executable, os.path.join(HERE, script), "--help"],
                       capture_output=True, text=True, cwd=HERE)
    return set(HELP_FLAG_RE.findall(p.stdout)) - {"--help"}


def skill_args():
    """The skill's own arguments, from SKILL.md's argument-hint line."""
    m = re.search(r"^argument-hint: (.*)$", read(os.path.join(HERE, "SKILL.md")), re.M)
    return set(FLAG_RE.findall(m.group(1))) if m else set()


def section(text, heading_re):
    """The text from the heading matching heading_re to the next heading of
    the same or a higher level (outside code fences)."""
    lines = text.splitlines()
    start = None
    level = 0
    in_fence = False
    for i, ln in enumerate(lines):
        if ln.strip().startswith("```"):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        m = re.match(r"^(#+) ", ln)
        if not m:
            continue
        if start is None and re.match(heading_re, ln):
            start, level = i, len(m.group(1))
            continue
        if start is not None and len(m.group(1)) <= level:
            return "\n".join(lines[start:i])
    return "\n".join(lines[start:]) if start is not None else ""


def pointers_rc(path):
    p = subprocess.run([sys.executable, os.path.join(HERE, "pointers.py"), path,
                        "--root", HERE], capture_output=True, text=True, cwd=HERE)
    return p.returncode, p.stdout


def fenced_lines(text):
    out, in_fence = [], False
    for ln in text.splitlines():
        if ln.strip().startswith("```"):
            in_fence = not in_fence
            continue
        if in_fence:
            out.append(ln)
    return out


def main():
    checks = []

    def check(name, ok, detail=""):
        checks.append((name, bool(ok), detail))

    skill = read(os.path.join(HERE, "SKILL.md"))
    nlc = read(NLC)
    p0 = read(os.path.join(REF, "phase-0-prune.md"))
    pa = read(os.path.join(REF, "phase-a-archive.md"))
    pb = read(os.path.join(REF, "phase-b-patterns.md"))
    cp = read(os.path.join(REF, "cross-phase.md"))
    pd = read(os.path.join(REF, "phase-d-rule-evidence.md"))
    pe = read(os.path.join(REF, "phase-e-path-scope.md"))
    rot = help_flags("rotate.py")
    lc = help_flags("loss_check.py")
    pt = help_flags("pointers.py")
    rc = help_flags("recall_check.py")
    sv = help_flags("survey.py")

    # ---- row 0: CONTROL
    check("CONTROL: the reader finds a known SKILL.md line and not an absent one, and "
          "--apply is a rotate.py flag while --no-such-flag is not",
          "Phase 0, then A, then B" in skill and "zz-not-in-the-skill-zz" not in skill
          and "--apply" in rot and "--no-such-flag" not in rot and "--structure" in lc,
          "rot=%r lc=%r" % (sorted(rot), sorted(lc)))

    # ---- SKILL.md
    check("SKILL.md is under 16,000 characters", 0 < len(skill) < 16000, "len=%d" % len(skill))
    plines = [l for l in skill.splitlines() if NLC_REL in l]
    check("SKILL.md has exactly three lines pointing at reference/no-loss-checks.md",
          len(plines) == 3, repr(plines))
    check("one SKILL.md pointer line is the dry-run report and its approval",
          any("REPORT.dry.md" in l and "approv" in l for l in plines), repr(plines))
    check("one SKILL.md pointer line is the loss and pointer checks",
          any("loss_check.py" in l and "pointers.py" in l for l in plines), repr(plines))
    check("SKILL.md no longer carries the hand-typed must-survive paragraph",
          "hand-write the distinctive phrases" not in skill
          and "A heading check is not a rule check" not in skill)
    check("one SKILL.md pointer line is the recall check, its pack and the undo",
          any("recall_check.py" in l and "QUESTIONS.md" in l and "undo" in l for l in plines),
          repr(plines))

    # ---- reference/no-loss-checks.md
    check("reference/no-loss-checks.md exists and is not empty", len(nlc) > 500, "len=%d" % len(nlc))
    for needle in ("loss_check.py --before", "--after CLAUDE.md", "--structure",
                   "pointers.py CLAUDE.md", "--accept-file", "phase0_waivers.txt",
                   "LOSS_PHASE0.md", "CLAUDE.md.before-<letter>", "--edited",
                   "REPORT.dry.md", "--undo", "split_20*/", ".git/info/exclude",
                   "split_<date>.undone/REPORT.md", "Phase 0 loss report: ",
                   "--narrative", "--hoisted", "--move-anyway", "--keep", "mkdir"):
        check("no-loss-checks.md names %s" % needle, needle in nlc)
    check("no-loss-checks.md says the refusals, manifest and undo cover rotate.py runs only",
          re.search(r"rotate\.py\W+runs only", nlc) is not None)
    check("no-loss-checks.md says --undo refuses on CLAUDE.md once Phases B to E edited it",
          re.search(r"--undo`? refuses[^.]*Phases? B to E", nlc) is not None)
    # the fenced calls themselves, continuation lines joined
    calls = " ".join(fenced_lines(nlc)).replace("\\ ", " ").replace("\\", " ")
    calls = [c for c in re.split(r"(?=python3 )", " ".join(calls.split())) if "loss_check.py" in c]
    p0call = [c for c in calls if "--accept-file" in c]
    check("the Phase 0 loss_check.py call compares the first backup with CLAUDE.md, takes "
          "phase0_waivers.txt by --accept-file and writes LOSS_PHASE0.md in the session folder",
          len(p0call) == 1 and "--before <first backup> --after CLAUDE.md" in p0call[0]
          and "--accept-file <session folder>/phase0_waivers.txt" in p0call[0]
          and "--report <session folder>/LOSS_PHASE0.md" in p0call[0]
          and "--structure" not in p0call[0], repr(calls))
    bcall = [c for c in calls if "--structure" in c]
    check("the per-phase loss_check.py call compares that phase's own CLAUDE.md.before-<letter> "
          "copy with --structure and --edited",
          len(bcall) == 1 and "--before <session folder>/CLAUDE.md.before-<letter>" in bcall[0]
          and "--edited" in bcall[0], repr(calls))
    bad = sorted(set(FLAG_RE.findall(nlc)) - (rot | lc | pt | rc))
    check("every flag no-loss-checks.md names is a real rotate.py, loss_check.py, "
          "pointers.py or recall_check.py flag", not bad and FLAG_RE.findall(nlc), repr(bad))
    bad_a = sorted(set(FLAG_RE.findall(pa)) - (rot | lc | pt | sv | skill_args()))
    check("every flag phase-a-archive.md names is a real flag of a skill script or the skill",
          not bad_a, repr(bad_a))
    rsec = section(nlc, r"^### The recall check")
    rcall = [c for c in re.split(r"(?=python3 )", " ".join(" ".join(fenced_lines(rsec)).replace("\\", " ").split()))
             if "recall_check.py" in c]
    check("no-loss-checks.md has a recall check section whose call passes the pack, the "
          "manifest and a report",
          len(rcall) == 1 and "--pack <run folder>/QUESTIONS.md" in rcall[0]
          and "--manifest <run folder>/manifest.json" in rcall[0]
          and re.search(r"--report <run folder>/RECALL\.md(?=\s|$)", rcall[0]) is not None,
          repr(rcall))
    check("the recall section names --before for a hand run and the undo on exit 3",
          "--before <first backup>" in rsec and re.search(r"Exit 3[^.]*undo", rsec) is not None)
    # the approval step binds the predicted fragment check to not applying:
    # one sentence of step 3, read on whitespace-collapsed text
    pa_sec = section(nlc, r"^### Phase A with rotate\.py")
    m3 = re.search(r"^3\. .*?(?=^4\. )", pa_sec, re.M | re.S)
    step3 = " ".join(m3.group(0).split()) if m3 else ""
    check("no-loss-checks.md step 3 holds the whole sentence 'Do not run `--apply` while the "
          "FRAGMENT CHECK line names a failure' (pinned whole, so a flipped rule fails)",
          "Do not run `--apply` while the FRAGMENT CHECK line names a failure" in step3, step3[:300])
    m7 = re.search(r"^7\. .*?(?=^#|\Z)", pa_sec, re.M | re.S)
    step7 = " ".join(m7.group(0).split()) if m7 else ""
    # step 7 splits undo's exit 2 by its first line
    s7a = ("A `CANNOT TELL` line means nothing was changed: fix the cause it names and run the undo "
           "again.")
    s7b = ("A first line starting `***` (`RESTORE of ... did not verify` or `The undo stopped part way`) "
           "means it stopped part way: do each line it printed by hand (the copy commands, the deletes, "
           "then the `mv`), and do not run the undo again.")
    check("no-loss-checks.md step 7 holds both halves on undo's exit 2, each pinned whole so a flipped "
          "half fails: the CANNOT TELL half (nothing changed, fix and re-run) and the *** half (finish by "
          "hand, do not re-run)", s7a in step7 and s7b in step7, step7[-500:])
    # step 6 says what to do on an unclosed-fence cannot tell, both variants
    m6 = re.search(r"^6\. .*?(?=^7\. )", pa_sec, re.M | re.S)
    step6 = " ".join(m6.group(0).split()) if m6 else ""
    s6a = ("A `CANNOT TELL: fence opened at line <N> never closes (<CLAUDE.md>)` line means CLAUDE.md "
           "holds a fence that never closes: close or fix the named fence in CLAUDE.md, take the backup "
           "again and rerun from the dry run.")
    s6b = ("The same line ending `(<CLAUDE.md> after the move)` means the file on disk is fine and the "
           "move itself would leave that fence open: change `--cut-date` or `--keep` instead.")
    check("no-loss-checks.md step 6 holds both variants of the unclosed-fence cannot tell, each pinned "
          "whole: the plain one (fix CLAUDE.md, back up again, rerun from the dry run) and the 'after "
          "the move' one (change --cut-date or --keep)", s6a in step6 and s6b in step6, step6[-600:])
    check("no-loss-checks.md no longer describes the draft as every rule sentence of every "
          "moving record", "every rule sentence of every moving record" not in " ".join(nlc.split()))

    # ---- the hand template equals rotate.py's own output
    tmpl = [l for l in fenced_lines(nlc) if l.startswith("Last split run: <date>")]
    rowt = [l for l in fenced_lines(nlc) if l.startswith("| <date> |")]
    check("no-loss-checks.md carries one Last-run template line and one Runs row template, "
          "in a code fence", len(tmpl) == 1 and len(rowt) == 1, repr((tmpl, rowt)))
    d = os.path.realpath(tempfile.mkdtemp())
    try:
        p = os.path.join(d, "CLAUDE.md")
        with open(p, "w", encoding="utf-8") as fh:
            fh.write(test_rotate.SECTION)
        r = subprocess.run([sys.executable, os.path.join(HERE, "rotate.py"), p,
                            "--convention", "section", "--cut-date", "2026-07-01",
                            "--today", "2026-08-15", "--apply", "--root", d],
                           capture_output=True, text=True, cwd=d)
        got_line = [l for l in read(p).splitlines() if l.startswith("Last split run:")]
        idx = read(os.path.join(d, "CLAUDE_DECISIONS_INDEX.md"))
        got_row = [l for l in idx.splitlines() if l.startswith("| 2026-08-15 |")]
        ok_run = r.returncode == 0 and len(got_line) == 1 and len(got_row) == 1
        check("synthetic rotate.py --apply writes one Last-run line and one Runs row",
              ok_run, "rc=%d %r" % (r.returncode, r.stdout[-300:]))
        if ok_run and tmpl and rowt:
            cells = [c.strip() for c in got_row[0].strip("|").split("|")]
            date, before, after, n, report = cells
            folder = report.split("/")[0]
            k = lambda v: "%dK" % ((int(v) + 500) // 1000)
            filled = (tmpl[0].replace("<date>", date).replace("<before>", k(before))
                      .replace("<after>", k(after)).replace("<N>", n)
                      .replace("<run folder name>", folder))
            check("the hand Last-run template, filled in, equals rotate.py's line",
                  filled == got_line[0], "%r != %r" % (filled, got_line[0]))
            frow = (rowt[0].replace("<date>", date).replace("<before chars>", before)
                    .replace("<after chars>", after).replace("<N>", n)
                    .replace("<run folder name>", folder))
            check("the hand Runs row template, filled in, equals rotate.py's row",
                  frow == got_row[0], "%r != %r" % (frow, got_row[0]))
        else:
            check("the hand Last-run template, filled in, equals rotate.py's line", False,
                  "no template or no run")
            check("the hand Runs row template, filled in, equals rotate.py's row", False,
                  "no template or no run")
    finally:
        shutil.rmtree(d, ignore_errors=True)

    # ---- phase files
    heads = [l for l in p0.splitlines() if l.startswith("### ")]
    check("phase-0-prune.md's first step is '### 0.0 Back up first'",
          heads and heads[0] == "### 0.0 Back up first", repr(heads[:2]))
    s00 = section(p0, r"^### 0\.0 ")
    check("0.0 runs A3's loop for CLAUDE.md and the index only and records the first backup",
          "A3" in s00 and "CLAUDE.md and the index" in s00 and "first backup" in s00, s00[:200])
    s06 = section(p0, r"^### 0\.6 ")
    check("0.6 names the Phase 0 loss check in reference/no-loss-checks.md, exit 0 before "
          "the next phase", NLC_REL in s06 and "exit 0" in s06 and "next phase" in s06, s06[-300:])
    a3 = section(pa, r"^### A3\. ")
    check("A3 says each file is backed up once per run, only files with no backup recorded",
          "once per run" in a3 and "no backup recorded in this run" in a3, a3[-400:])
    for step in ("A4", "A5", "A6", "A7", "A8", "A9"):
        s = section(pa, r"^### %s\. " % step)
        check("phase-a-archive.md %s uses rotate.py or one of its flags" % step,
              "rotate.py" in s or any(f in s for f in rot), s[:120])
    pat_heads = [l for l in pb.splitlines() if l.startswith("### Pattern:")]
    check("phase-b-patterns.md: no pattern heading carries an instance count",
          pat_heads and not any("instance" in l for l in pat_heads), repr(pat_heads))
    b3 = section(pb, r"^### B3\. ")
    tl = b3.splitlines()
    first_after = next((tl[i + 2] for i, l in enumerate(tl)
                        if l.startswith("### Pattern:") and i + 2 < len(tl)), "")
    check("the B3 template's first line under the heading carries the instance count",
          "<N>" in first_after and "instance" in first_after, repr(first_after))
    ab = section(cp, r"^### Always back up")
    check("cross-phase.md 'Always back up' says once per file per run",
          "once per run" in ab and "no backup recorded in this run" in ab, ab[-300:])
    vd = section(cp, r"^### Verify")
    check("cross-phase.md's end-of-run verify points at the per-phase checks",
          "loss_check.py --structure" in vd and "pointers.py" in vd and NLC_REL in vd, vd[-300:])
    check("phase-d-rule-evidence.md no longer hand-writes a must-survive list",
          "hand-write the distinctive" not in pd)
    check("phase-d-rule-evidence.md points its verify at loss_check.py --structure and pointers.py",
          "loss_check.py --structure" in pd and "pointers.py" in pd and NLC_REL in pd)
    d0 = section(pd, r"^### D0\. ")
    check("Phase D has a backup step: files with no backup recorded in this run, and "
          "the CLAUDE.md.before-D copy", "no backup recorded in this run" in d0
          and "CLAUDE.md.before-D" in d0, d0[:300])
    check("phase-e-path-scope.md no longer points at Phase D's must-survive list",
          "The must-survive list from Phase D applies here too" not in pe)
    e6 = section(pe, r"^### E6\. ")
    check("Phase E's verify points at the per-phase loss check against CLAUDE.md.before-E, "
          "--accept for each moved rule, and keeps the one-place grep",
          NLC_REL in e6 and "CLAUDE.md.before-E" in e6 and "--accept" in e6
          and "exactly one place" in e6, e6[-500:])

    # ---- pointers resolve (explicit root: the skill folder)
    for rel in ("SKILL.md", "reference/no-loss-checks.md", "reference/phase-0-prune.md",
                "reference/phase-b-patterns.md", "reference/cross-phase.md",
                "reference/phase-d-rule-evidence.md", "reference/phase-e-path-scope.md"):
        rc, out = pointers_rc(os.path.join(HERE, rel))
        check("pointers.py resolves every pointer in %s" % rel, rc == 0, out[-300:])
    # pointers.py counts a name only on a line with a pointer word, so a bare
    # "per `reference/no-loss-checks.md`" is not one: check every such name too.
    texts = [("SKILL.md", skill)] + [(os.path.join("reference", n), read(os.path.join(REF, n)))
                                     for n in sorted(os.listdir(REF)) if n.endswith(".md")]
    missing, seen = [], []
    for rel, txt in texts:
        for tok in re.findall(r"`([^`\s]+)`", txt):
            if tok.startswith("reference/") and tok.endswith(".md"):
                where = os.path.join(HERE, tok)
            elif re.match(r"^(?:phase-[\w-]+|cross-phase|loading-model|no-loss-checks)\.md$", tok):
                where = os.path.join(REF, tok)
            else:
                continue
            seen.append((rel, tok))
            if not os.path.isfile(where):
                missing.append((rel, tok))
    check("every backticked reference file name in SKILL.md and reference/ exists",
          not missing and ("SKILL.md", NLC_REL) in seen, repr(missing))
    rc, out = pointers_rc(os.path.join(HERE, "reference/phase-a-archive.md"))
    unres = [l for l in out.splitlines() if l.startswith("UNRESOLVED:")]
    check("phase-a-archive.md: no unresolved pointer names a script or no-loss-checks.md",
          rc in (0, 3) and not any(".py" in l or "no-loss-checks" in l for l in unres), out[-300:])

    if not checks:
        print("0/0 passed -- the harness ran NO checks, which is a harness bug")
        return 1
    failed = [c for c in checks if not c[1]]
    for name, ok, detail in checks:
        if not ok:
            print("  FAILED " + name)
            print("         " + re.sub(r"(\d+)/(\d+) passed", r"\1 of \2 passed",
                                       str(detail).replace("\n", "\n         "))[:400])
    print("%d/%d passed" % (len(checks) - len(failed), len(checks)))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
