#!/usr/bin/env python3
"""The split-no-loss definition of done, FROZEN.

    goal_check.py            (no arguments)

Runs every scenario through the real script entry point (by subprocess) on
SYNTHETIC fixtures written to mkdtemp folders, prints PASS or FAIL per
scenario, and exits 0 only when every scenario holds; otherwise 3.

Scenarios (Definition of done):
  0  CONTROL: the moving records of scenarios 4, 6 and 7 hold no RULE_RE word
  1  loss_check.py: moved rule exits 3 and is named; --accept exits 0;
     a missing backup exits 2; a rule reworded in place reads KEPT
  2  loss_check.py --structure: changed preamble exits 3, untouched exits 0
  3  pointers.py: missing file and heading differing in words exit 3; a
     heading differing only by "(N instances)" resolves
  4  rotate.py: open-work evidence, refusal, --move-anyway
  5  rotate.py: unhoisted rule sentences refused and named; --hoisted
  6  rotate.py: REPORT.md, manifest.json, one Last-run line, Runs rows
  7  rotate.py --undo: restore, refusal after an edit, missing file
  8  recall_check.py: a rule moved behind a pointer exits 3 and is LOST;
     nothing moved exits 0. Runs only against the fake, behind the PATH fence
  9  SKILL.md is under 16,000 characters
 10  speed: loss_check.py, pointers.py and the rotate.py
     dry run each finish under 10 s on a 160,000-char CLAUDE.md
 11  fragment counts: an archive already holding the
     moving title once or three times predicts 0 failures and applies with
     exit 0; a colliding record predicts a failure and --apply exits 2

These checks are fixed: a change may add a check, never weaken one to match the code.
"""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
LOSS = os.path.join(HERE, "loss_check.py")
POINTERS = os.path.join(HERE, "pointers.py")
ROTATE = os.path.join(HERE, "rotate.py")
SKILL_MD = os.path.join(HERE, "SKILL.md")

TMP = []


def mk():
    d = os.path.realpath(tempfile.mkdtemp(prefix="goal-check-"))
    TMP.append(d)
    return d


def write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)
    return path


def read(path):
    if not os.path.isfile(path):
        return ""
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def run(script, args, cwd=None, env=None):
    p = subprocess.run([sys.executable, script] + list(args), stdout=subprocess.PIPE,
                       stderr=subprocess.PIPE, cwd=cwd, env=env)
    return p.returncode, p.stdout.decode("utf-8", "replace"), p.stderr.decode("utf-8", "replace")


def words(text):
    return re.findall(r"[a-z0-9]+", text.lower())


def norm(text):
    return " ".join(re.sub(r"[^\w\s]", "", text.lower()).split())


def tail(s, n=300):
    return s[-n:].replace("\n", " | ")


def class_lines(out):
    return [l for l in out.splitlines() if l.startswith("LAZY-ONLY: ") or l.startswith("NOWHERE: ")]


REPORT_SECTIONS = ["Summary", "Move", "Keep", "Open-work evidence", "Rules draft", "Loss check",
                   "Pointers", "Waivers", "Backups", "Files sent"]


def report_section(text, name):
    """Lines after a line equal to '## <name>' up to the next line equal to
    '## ' plus one of the report section names, or end of file."""
    lines = text.splitlines()
    stops = set("## " + n for n in REPORT_SECTIONS)
    out, inside = [], False
    for ln in lines:
        if inside and ln in stops:
            break
        if inside:
            out.append(ln)
        elif ln == "## " + name:
            inside = True
    return out


def split_dirs(d):
    return sorted(n for n in os.listdir(d)
                  if n.startswith("split_") and os.path.isdir(os.path.join(d, n)))


# ------------------------------------------------------------- scenario 1

S1_RULE = ("Never push the nightly widget export straight to the shared bucket "
           "without a dry run first.")
S1_REWORDED = ("Never push the nightly widget export to the shared bucket unless a "
               "dry run passed first.")
S1_BEFORE = """# Project

Preamble line that says what this file is for.

## Overview

Plain overview text about the widget project.

## Widget export record (2026-01-10)

{r}
The export ran on the staging box and the numbers looked fine.

## Newer record (2026-03-02)

Newer record body text that stays in place.
"""
S1_AFTER_MOVED = """# Project

Preamble line that says what this file is for.

## Overview

Plain overview text about the widget project.

## Newer record (2026-03-02)

Newer record body text that stays in place.
"""
S1_ARCHIVE = """# Decisions Log Archive - January 2026

## Widget export record (2026-01-10)

{r}
The export ran on the staging box and the numbers looked fine.
"""


def scenario_1():
    fails = []
    r_text = S1_RULE.rstrip(".")
    before = S1_BEFORE.format(r=S1_RULE)
    # fixture rules, asserted before running
    if ". " in S1_RULE or "; " in S1_RULE or "`" in S1_RULE or "never" not in S1_RULE.lower():
        return False, "fixture: the rule sentence breaks the scenario 1 fixture rule"
    rw, rr = words(S1_REWORDED), words(S1_RULE)
    win = set(tuple(rr[i:i + 5]) for i in range(len(rr) - 4))
    if not any(tuple(rw[i:i + 5]) in win for i in range(len(rw) - 4)) or norm(S1_RULE) in norm(S1_REWORDED):
        return False, "fixture: the rewording keeps no 5-word window or holds the whole rule"
    if "CLAUDE_DECISIONS" in S1_AFTER_MOVED:
        return False, "fixture: the leg 1 after file points at the index or an archive"

    d = mk()
    b = write(os.path.join(d, "CLAUDE.md.backup-before-split-2026-02-01"), before)
    a = write(os.path.join(d, "CLAUDE.md"), S1_AFTER_MOVED)
    write(os.path.join(d, "CLAUDE_DECISIONS_2026-01.md"), S1_ARCHIVE.format(r=S1_RULE))
    rc, out, err = run(LOSS, ["--before", b, "--after", a], cwd=d)
    leg1_named = any(r_text in l for l in class_lines(out))
    if not (rc == 3 and leg1_named):
        fails.append("leg 1 moved rule: rc=%d named=%s %s" % (rc, leg1_named, tail(out + err)))
    rc, out, err = run(LOSS, ["--before", b, "--after", a, "--accept", "nightly widget export straight"], cwd=d)
    if rc != 0:
        fails.append("leg 2 --accept: rc=%d %s" % (rc, tail(out + err)))
    rc, out, err = run(LOSS, ["--before", os.path.join(d, "missing-backup"), "--after", a], cwd=d)
    if rc != 2:
        fails.append("leg 3 missing backup: rc=%d %s" % (rc, tail(out + err)))
    d4 = mk()
    b4 = write(os.path.join(d4, "CLAUDE.md.backup-before-split-2026-02-01"), before)
    a4 = write(os.path.join(d4, "CLAUDE.md"), before.replace(S1_RULE, S1_REWORDED))
    rc, out, err = run(LOSS, ["--before", b4, "--after", a4], cwd=d4)
    listed = any(r_text in l for l in class_lines(out))
    if not (rc == 0 and not listed and leg1_named):
        fails.append("leg 4 reworded in place: rc=%d listed=%s leg1_named=%s %s"
                     % (rc, listed, leg1_named, tail(out + err)))
    return (not fails), "; ".join(fails) or "moved rule named (exit 3), --accept 0, missing 2, reworded KEPT"


# ------------------------------------------------------------- scenario 2

S2_BEFORE = """# Project

Preamble text line.

## Overview

Overview text.

## Old record (2026-01-05)

Old record body text.

## New record (2026-03-05)

New record body text.
"""
S2_AFTER = """# Project

Preamble text line.

## Overview

Overview text.

## New record (2026-03-05)

New record body text.
"""


def scenario_2():
    fails = []
    for name, after, want in (("untouched", S2_AFTER, 0),
                              ("changed preamble", S2_AFTER.replace("Preamble text line.",
                                                                    "Preamble text, edited."), 3)):
        d = mk()
        b = write(os.path.join(d, "CLAUDE.md.backup-before-split-2026-02-01"), S2_BEFORE)
        a = write(os.path.join(d, "CLAUDE.md"), after)
        write(os.path.join(d, "CLAUDE_DECISIONS_2026-01.md"),
              "## Old record (2026-01-05)\n\nOld record body text.\n")
        rc, out, err = run(LOSS, ["--before", b, "--after", a, "--structure"], cwd=d)
        if rc != want or (want == 3 and "preamble" not in out):
            fails.append("%s: rc=%d want %d %s" % (name, rc, want, tail(out + err)))
    return (not fails), "; ".join(fails) or "changed preamble 3, untouched 0"


# ------------------------------------------------------------- scenario 3

def scenario_3():
    if not os.path.isfile(POINTERS):
        return False, "pointers.py is missing"
    fails = []
    cases = [
        ("missing file", "# P\n\n## Overview\n\nSee `MISSING_NOTES.md` for the old records.\n", None, 3),
        ("heading differs in words",
         "# P\n\n## Pattern: widget traps\n\nEvidence: `NOTES.md`, same heading.\n",
         "# Notes\n\n## Pattern: gadget traps\n\nThe gadget evidence.\n", 3),
        ("heading differs only by (N instances)",
         "# P\n\n## Pattern: widget traps (3 instances)\n\nEvidence: `NOTES.md`, same heading.\n",
         "# Notes\n\n## Pattern: widget traps\n\nThe widget evidence.\n", 0),
    ]
    for name, claude, notes, want in cases:
        d = mk()
        root = mk()
        c = write(os.path.join(d, "CLAUDE.md"), claude)
        if notes is not None:
            write(os.path.join(d, "NOTES.md"), notes)
        rc, out, err = run(POINTERS, [c, "--root", root], cwd=d)
        if rc != want:
            fails.append("%s: rc=%d want %d %s" % (name, rc, want, tail(out + err)))
    return (not fails), "; ".join(fails) or "missing 3, words differ 3, (N instances) resolves 0"


# ------------------------------------------------------------- scenario 4

S4_TOKEN = "build_widget_v2.py"
S4_HEADING = ("## Widget pipeline record about the nightly export job, its staging bucket "
              "layout and the retry budget (2026-01-10)")
S4_RECORD = (S4_HEADING + "\n\nThe nightly export now writes its staging files through `"
             + S4_TOKEN + "` and keeps a copy for the audit team.\n")
S4_CLAUDE = ("# Project\n\nPreamble text for the widget project.\n\n" + S4_RECORD
             + "\n## Later record about the reporting dashboard (2026-03-20)\n\n"
             "The dashboard reads the export once a day.\n")
S4_ITEM = ("Retire the legacy fallback inside `" + S4_TOKEN + "` after the analytics group "
           "confirms the quarterly numbers match the old totals")
S4_TODO = "# TODO\n\n## Active\n\n- [ ] " + S4_ITEM + "\n- [x] A closed item about lunch.\n"


def title_of(heading):
    return re.sub(r"^#+ ", "", heading).strip()


def scenario_4():
    title = title_of(S4_HEADING)
    # fixture rules: long texts, no shared four-word run, the token once per file
    trw = words(re.sub(r"\(\d{4}-\d{2}-\d{2}\)", "", title))
    runs = set(tuple(trw[i:i + 4]) for i in range(len(trw) - 3))
    iw = words(S4_ITEM)
    if (len(title) < 100 or len(S4_ITEM) < 100 or S4_TOKEN not in S4_ITEM or "key:" in S4_ITEM
            or any(tuple(iw[i:i + 4]) in runs for i in range(len(iw) - 3))
            or S4_CLAUDE.count(S4_TOKEN) != 1 or S4_TODO.count(S4_TOKEN) != 1):
        return False, "fixture: scenario 4 breaks a fixture rule"
    if not os.path.isfile(ROTATE):
        return False, "rotate.py missing"
    d = mk()
    root = mk()
    c = write(os.path.join(d, "CLAUDE.md"), S4_CLAUDE)
    write(os.path.join(d, "TODO.md"), S4_TODO)
    base = [c, "--convention", "section", "--cut-date", "2026-02-01", "--today", "2026-02-15",
            "--root", root]
    rc, out, err = run(ROTATE, base, cwd=d)
    dirs = split_dirs(d)
    if rc != 0 or len(dirs) != 1 or not os.path.isfile(os.path.join(d, dirs[0], "REPORT.dry.md")):
        return False, "leg 1 dry run: rc=%d split dirs=%r %s" % (rc, dirs, tail(out + err))
    sec = report_section(read(os.path.join(d, dirs[0], "REPORT.dry.md")), "Open-work evidence")
    ti = next((i for i, l in enumerate(sec) if title in l), None)
    key_re = re.compile(r"key: `?" + re.escape(S4_TOKEN) + r"`?")
    item_ok = ti is not None and any(S4_ITEM in l and key_re.search(l) for l in sec[ti + 1:])
    if not item_ok:
        return False, "leg 1: Open-work evidence lacks the whole title then the whole item with its key: %r" % sec[:6]
    rc, out, err = run(ROTATE, base + ["--apply"], cwd=d)
    if rc != 3:
        return False, "leg 2 --apply with no waiver: rc=%d want 3 %s" % (rc, tail(out + err))
    rc, out, err = run(ROTATE, base + ["--apply", "--move-anyway", title], cwd=d)
    if rc != 0:
        return False, "leg 3 --move-anyway: rc=%d %s" % (rc, tail(out + err))
    if any(l == S4_HEADING for l in read(c).splitlines()):
        return False, "leg 3: the record heading is still in CLAUDE.md"
    reps = [n for n in split_dirs(d) if os.path.isfile(os.path.join(d, n, "REPORT.md"))]
    if len(reps) != 1:
        return False, "leg 3: want exactly one split_*/REPORT.md, got %r" % reps
    w = report_section(read(os.path.join(d, reps[0], "REPORT.md")), "Waivers")
    if not any("--move-anyway" in l and title in l for l in w):
        return False, "leg 3: the Waivers section does not name --move-anyway with the whole title: %r" % w[:6]
    return True, "dry run lists the open item with its key, --apply 3, --move-anyway 0 and reported"


# ------------------------------------------------------------- scenario 5

S5_R1 = "Always run the staging export with the dry flag before touching the shared bucket."
S5_R2 = "Never rename the export columns without telling the reporting team first."
S5_CLAUDE = ("# Project\n\nPreamble text for the export project.\n\n"
             "## Export bucket record (2026-01-12)\n\n" + S5_R1 + "\n" + S5_R2 + "\n"
             "The bucket moved to the new region that week.\n\n"
             "## Later record about the export schedule (2026-03-18)\n\n"
             "The schedule now runs at night.\n")


def missing_rule_lines(out):
    return [l for l in out.splitlines() if l.startswith("MISSING RULE: ")]


def scenario_5():
    if not os.path.isfile(ROTATE):
        return False, "rotate.py missing"
    fails = []
    for name, hoisted, want_rc, want_named, want_absent in (
            ("no hoist", None, 3, [S5_R1, S5_R2], []),
            ("one missing", [S5_R1], 3, [S5_R2], [S5_R1]),
            ("all hoisted", [S5_R1, S5_R2], 0, [], [S5_R1, S5_R2])):
        A = mk()
        root = mk()
        proj = os.path.join(A, "proj")
        c = write(os.path.join(proj, "CLAUDE.md"), S5_CLAUDE)
        args = [c, "--convention", "section", "--cut-date", "2026-02-01", "--today", "2026-02-15",
                "--root", root, "--apply"]
        if hoisted is not None:
            h = write(os.path.join(A, "CLAUDE.md"), "# Global rules\n\n" + "\n".join(hoisted) + "\n")
            args += ["--hoisted", h]
        rc, out, err = run(ROTATE, args, cwd=proj)
        mr = missing_rule_lines(out)
        named_ok = all(any(s.rstrip(".") in l for l in mr) for s in want_named)
        absent_ok = not any(s.rstrip(".") in l for s in want_absent for l in mr)
        if rc != want_rc or not named_ok or not absent_ok:
            fails.append("%s: rc=%d want %d named=%s absent=%s %s"
                         % (name, rc, want_rc, named_ok, absent_ok, tail(out + err)))
    return (not fails), "; ".join(fails) or "unhoisted named (3), one missing named (3), hoisted 0"


# ------------------------------------------------------------- scenario 6

S6_CLAUDE = ("# Project\n\nPreamble text for the archive project.\n\n"
             "## First record about the intake form (2026-01-05)\n\nThe intake form gained a date field.\n\n"
             "## Second record about the export feed (2026-02-10)\n\nThe export feed switched to daily files.\n\n"
             "## Third record about the dashboard (2026-04-01)\n\nThe dashboard shows weekly totals.\n")


def runs_rows(index_text):
    rows, inside = [], False
    for ln in index_text.splitlines():
        if inside and ln.startswith("## "):
            break
        if inside and ln.startswith("|"):
            if ln.replace(" ", "").startswith("|Date|") or re.match(r"^[\s|:\-]+$", ln):
                continue
            rows.append(ln)
        if ln.strip() == "## Runs":
            inside = True
    return rows


def scenario_6():
    if not os.path.isfile(ROTATE):
        return False, "rotate.py missing"
    d = mk()
    root = mk()
    c = write(os.path.join(d, "CLAUDE.md"), S6_CLAUDE)
    rc, out, err = run(ROTATE, [c, "--convention", "section", "--cut-date", "2026-02-01",
                                "--today", "2026-02-15", "--root", root, "--apply"], cwd=d)
    dirs = [n for n in split_dirs(d) if re.match(r"^split_\d{4}-\d{2}-\d{2}(-\d+)?$", n)]
    have = [n for n in dirs if os.path.isfile(os.path.join(d, n, "REPORT.md"))
            and os.path.isfile(os.path.join(d, n, "manifest.json"))]
    if rc != 0 or len(have) != 1:
        return False, "run 1: rc=%d split dirs with REPORT.md and manifest.json=%r %s" % (rc, have, tail(out + err))
    rc, out, err = run(ROTATE, [c, "--convention", "section", "--cut-date", "2026-03-01",
                                "--today", "2026-03-15", "--root", root, "--apply"], cwd=d)
    if rc != 0:
        return False, "run 2: rc=%d %s" % (rc, tail(out + err))
    last = [l for l in read(c).splitlines() if l.startswith("Last split run:")]
    rows = runs_rows(read(os.path.join(d, "CLAUDE_DECISIONS_INDEX.md")))
    if len(last) != 1 or len(rows) != 2:
        return False, "after two runs: %d Last-run lines (want 1), %d Runs rows (want 2)" % (len(last), len(rows))
    return True, "REPORT.md and manifest.json written; one Last-run line, two Runs rows"


# ------------------------------------------------------------- scenario 7

S7_CLAUDE = ("# Project\n\nPreamble text for the undo project.\n\n"
             "## Early record about the label printer (2026-01-07)\n\nThe label printer got a new driver.\n\n"
             "## Recent record about the label stock (2026-03-09)\n\nThe label stock changed supplier.\n")


def applied_sandbox():
    d = mk()
    root = mk()
    c = write(os.path.join(d, "CLAUDE.md"), S7_CLAUDE)
    snap = {}
    for n in os.listdir(d):
        p = os.path.join(d, n)
        if os.path.isfile(p):
            with open(p, "rb") as fh:
                snap[n] = fh.read()
    rc, out, err = run(ROTATE, [c, "--convention", "section", "--cut-date", "2026-02-01",
                                "--today", "2026-02-15", "--root", root, "--apply"], cwd=d)
    dirs = [n for n in split_dirs(d) if os.path.isfile(os.path.join(d, n, "manifest.json"))]
    man = None
    if rc == 0 and len(dirs) == 1:
        try:
            with open(os.path.join(d, dirs[0], "manifest.json"), encoding="utf-8") as fh:
                man = json.load(fh)
        except (OSError, ValueError):
            man = None
    return d, c, snap, rc, dirs, man, out + err


def scenario_7():
    if not os.path.isfile(ROTATE):
        return False, "rotate.py missing"
    fails = []
    # leg a: restore every file, remove created files, keep backups
    d, c, snap, rc, dirs, man, log = applied_sandbox()
    if man is None:
        return False, "precondition: the apply run gave rc=%d dirs=%r and no readable manifest %s" % (rc, dirs, tail(log))
    files = man.get("files", [])
    created = [f["path"] for f in files if f.get("pre_sha256") is None]
    backups = [f["backup"] for f in files if f.get("backup")]
    rc, out, err = run(ROTATE, [c, "--undo", dirs[0], "--apply"], cwd=d)
    bad = [n for n, data in snap.items() if not os.path.isfile(os.path.join(d, n))
           or open(os.path.join(d, n), "rb").read() != data]
    left = [p for p in created if os.path.exists(os.path.join(d, p))]
    lost = [p for p in backups if not os.path.exists(os.path.join(d, p))]
    if rc != 0 or bad or left or lost or not created:
        fails.append("leg a restore: rc=%d not byte-equal=%r created left=%r backups lost=%r created=%r %s"
                     % (rc, bad, left, lost, created, tail(out + err)))
    # leg b: refuse and name the file after an edit
    d, c, snap, rc, dirs, man, log = applied_sandbox()
    if man is None:
        fails.append("leg b precondition: rc=%d %s" % (rc, tail(log)))
    else:
        with open(c, "a", encoding="utf-8") as fh:
            fh.write("A later edit.\n")
        edited = read(c)
        rc, out, err = run(ROTATE, [c, "--undo", dirs[0], "--apply"], cwd=d)
        if rc != 3 or "CLAUDE.md" not in out + err or read(c) != edited:
            fails.append("leg b edited: rc=%d want 3 naming CLAUDE.md, file untouched %s" % (rc, tail(out + err)))
    # leg c: a manifest naming a missing file refuses, no crash
    d, c, snap, rc, dirs, man, log = applied_sandbox()
    created = [f["path"] for f in (man or {}).get("files", []) if f.get("pre_sha256") is None]
    if man is None or not created:
        fails.append("leg c precondition: rc=%d created=%r %s" % (rc, created, tail(log)))
    else:
        gone = created[0]
        os.remove(os.path.join(d, gone))
        rc, out, err = run(ROTATE, [c, "--undo", dirs[0], "--apply"], cwd=d)
        if rc != 3 or "Traceback" in err or os.path.basename(gone) not in out + err:
            fails.append("leg c missing file: rc=%d want 3 naming %s, no crash %s" % (rc, gone, tail(out + err)))
    return (not fails), "; ".join(fails) or "restored byte-equal, refused after an edit, refused a missing file"


# ------------------------------------------------------------- scenario 8 (recall check)

RECALL = os.path.join(HERE, "recall_check.py")
FAKE = os.path.join(HERE, "fake_claude.py")


class FenceBroken(Exception):
    """The live-call fence does not hold: scenario 8 must not run."""


def scenario_8():
    """recall_check.py through its entry point, against the fake only (live-call fence): a rule moved
    behind a pointer exits 3 and is named LOST; the same pack with nothing moved exits 0."""
    fake_dir = mk()
    claude = os.path.join(fake_dir, "claude")
    os.symlink(FAKE, claude)
    path = fake_dir + ":/usr/bin:/bin"
    if shutil.which("claude", path=path) != claude:
        raise FenceBroken("which(claude) on %s is %r, not the fake" % (path, shutil.which("claude", path=path)))
    env = {"PATH": path, "HOME": mk()}
    filler = "\n".join("- Item %d is GOALFILL-%d." % (i, i) for i in range(1, 6))
    rule = "- Never ship the batch without the lock file (GOALRULE-8X)."
    qs = ["What must the batch never ship without? | GOALRULE-8X | rule"] + [
        "What is item %d? | GOALFILL-%d | fact" % (i, i) for i in range(1, 6)]
    out = []
    for leg, after, want in (("moved", "# P\n\n- Older records: `CLAUDE_DECISIONS_2026-01.md`.\n" + filler + "\n", 3),
                             ("kept", "# P\n\n" + rule + "\n" + filler + "\n", 0)):
        d = mk()
        write(os.path.join(d, "CLAUDE.md"), after)
        write(os.path.join(d, "CLAUDE.md.backup-before-split-2026-01-01"), "# P\n\n" + rule + "\n" + filler + "\n")
        write(os.path.join(d, "CLAUDE_DECISIONS_2026-01.md"), "# Archive\n\n" + rule + "\n")
        pack = write(os.path.join(d, "split_2026-01-01", "QUESTIONS.md"), "\n".join(qs) + "\n")
        rc, so, se = run(RECALL, [os.path.join(d, "CLAUDE.md"), "--pack", pack, "--claude", claude,
                                  "--before", os.path.join(d, "CLAUDE.md.backup-before-split-2026-01-01")],
                         env=env)
        ok = rc == want and (want == 0 or re.search(r"^LOST: 1 .*\(rule\)", so, re.M))
        out.append((leg, ok, rc))
        if not ok:
            return False, "leg %s: exit %d, expected %d: %s" % (leg, rc, want, tail(so + se))
    return True, "rule moved behind a pointer exits 3 and is LOST; nothing moved exits 0 (fake only)"


# ------------------------------------------------------------- scenario 9

def scenario_9():
    n = len(read(SKILL_MD))
    return (0 < n < 16000), "SKILL.md is %d characters (limit 16000)" % n


# ------------------------------------------------------------- check 10

PERF_LIMIT = 10.0
PERF_CHARS = 160000


def perf_fixture():
    """A synthetic CLAUDE.md of at least PERF_CHARS characters: dated '## '
    records with tokens, pointers and one rule sentence each."""
    parts = ["# Project\n\nPreamble for the timing fixture.\n\n"]
    i = 0
    while sum(len(x) for x in parts) < PERF_CHARS:
        dt = "2025-%02d-%02d" % (i % 12 + 1, i % 27 + 1)
        parts.append("## Record %d about the widget batch %d (%s)\n\n"
                     "The batch %d wrote `out_%d.csv` through `tool_v%d.py` at commit `%07x`. "
                     "See `NOTES_%d.md` for the detail of that night.\n"
                     "Never run batch %d twice on the same night without a fresh lock file.\n"
                     "Filler text about the batch so each record has some ordinary body to read.\n\n"
                     % (i, i, dt, i, i, i, 0xa000000 + i, i % 5, i))
        i += 1
    return "".join(parts)


def scenario_10():
    import time
    text = perf_fixture()
    if len(text) < PERF_CHARS:
        return False, "fixture: %d characters, want at least %d" % (len(text), PERF_CHARS)
    d = mk()
    root = mk()
    c = write(os.path.join(d, "CLAUDE.md"), text)
    lines = text.splitlines(keepends=True)
    kept = []
    skip = False
    for ln in lines:
        if ln.startswith("## "):
            skip = re.search(r"\(2025-0[1-6]-", ln) is not None
        if not skip:
            kept.append(ln)
    after_dir = mk()
    b = write(os.path.join(after_dir, "CLAUDE.md.backup-before-split-2026-01-01"), text)
    a = write(os.path.join(after_dir, "CLAUDE.md"), "".join(kept))
    write(os.path.join(after_dir, "ARCHIVE_NOTES.md"), "".join(l for l in lines if l not in kept))
    runs = [("loss_check.py", LOSS, ["--before", b, "--after", a], after_dir, (0, 3)),
            ("pointers.py", POINTERS, [c, "--root", root], d, (0, 3)),
            ("rotate.py dry run", ROTATE, [c, "--convention", "section", "--cut-date", "2025-07-01",
                                           "--today", "2026-01-01", "--root", root], d, (0,))]
    fails, took = [], []
    for name, script, args, cwd, ok_rc in runs:
        t0 = time.time()
        rc, out, err = run(script, args, cwd=cwd)
        dt = time.time() - t0
        took.append("%s %.2f s" % (name, dt))
        if rc not in ok_rc or dt >= PERF_LIMIT:
            fails.append("%s: rc=%d in %.2f s (limit %.0f s) %s" % (name, rc, dt, PERF_LIMIT, tail(out + err)))
    detail = "%d chars: %s" % (len(text), ", ".join(took))
    return (not fails), ("; ".join(fails) + " | " + detail) if fails else detail


# ------------------------------------------------------------- check 11

S11_ARGS = ["--convention", "section", "--cut-date", "2026-02-01", "--today", "2026-02-15"]
S11_TITLE = "## Kiosk record about the badge printer (2026-01-10)"
S11_CLAUDE = ("# Project\n\nPreamble text for the kiosk project.\n\n" + S11_TITLE + "\n\n"
              "The badge printer at the kiosk got a new ribbon in the first week.\n\n"
              "## Recent record about the kiosk screen (2026-03-20)\n\n"
              "The kiosk screen was cleaned and recalibrated by the vendor.\n")
S11_ARCH = "CLAUDE_DECISIONS_2026-01.md"
S11_EVIDENCE = S11_TITLE + "\n\nEarlier evidence for the badge printer sits here.\n\n"
S11_COLLIDE = ("# Project\n\nPreamble text for the kiosk queue.\n\n"
               "## Old kiosk record about the queue (2026-01-05)\n\n"
               "A repeated kiosk sentence that is comfortably longer than forty characters.\n\n"
               "## New kiosk record that stays (2026-03-05)\n\n"
               "A repeated kiosk sentence that is comfortably longer than forty characters.\n")
S11_PRED = re.compile(r"^FRAGMENT CHECK \(predicted for --apply\): (\d+) fragment\(s\), "
                      r"(\d+) failure\(s\)$", re.M)


def scenario_11():
    sys.path.insert(0, HERE)
    import splitlib
    # fixture rule: no record check 11 moves holds a RULE_RE word, read live
    moving = [S11_CLAUDE.split("## Recent")[0], S11_EVIDENCE, S11_COLLIDE.split("## New")[0]]
    if any(splitlib.RULE_RE.search(t) for t in moving):
        return False, "fixture: a check 11 record holds a RULE_RE word"
    fails, seen = [], []
    for label, copies in (("(a) title once", 1), ("(b) title three times", 3)):
        d = mk()
        root = mk()
        c = write(os.path.join(d, "CLAUDE.md"), S11_CLAUDE)
        write(os.path.join(d, S11_ARCH), "# Archive\n\n" + S11_EVIDENCE * copies)
        rc, out, err = run(ROTATE, [c] + S11_ARGS + ["--root", root], cwd=d)
        m = S11_PRED.search(out)
        if rc != 0 or not m or m.group(2) != "0":
            fails.append("%s dry run: rc=%d %s" % (label, rc, tail(out + err)))
        rc, out, err = run(ROTATE, [c] + S11_ARGS + ["--root", root, "--apply"], cwd=d)
        if rc != 0:
            fails.append("%s --apply: rc=%d %s" % (label, rc, tail(out + err)))
        seen.append("%s predicted %s, apply %d" % (label, m.group(2) if m else "none", rc))
    d = mk()
    root = mk()
    c = write(os.path.join(d, "CLAUDE.md"), S11_COLLIDE)
    rc, out, err = run(ROTATE, [c] + S11_ARGS + ["--root", root], cwd=d)
    m = S11_PRED.search(out)
    if rc != 0 or not m or int(m.group(2)) < 1:
        fails.append("(c) colliding dry run: rc=%d %s" % (rc, tail(out + err)))
    rc2, out2, err2 = run(ROTATE, [c] + S11_ARGS + ["--root", root, "--apply"], cwd=d)
    if rc2 != 2:
        fails.append("(c) colliding --apply: rc=%d %s" % (rc2, tail(out2 + err2)))
    seen.append("(c) colliding predicted %s, apply %d" % (m.group(2) if m else "none", rc2))
    return (not fails), ("; ".join(fails) if fails else "; ".join(seen))


# ------------------------------------------------------------- control

def scenario_0():
    try:
        sys.path.insert(0, HERE)
        import splitlib
    except Exception as e:   # noqa: BLE001
        return False, "splitlib did not import: %s" % type(e).__name__
    if not splitlib.RULE_RE.search(S1_RULE):
        return False, "RULE_RE does not match the scenario 1 rule (the control cannot fire)"
    moving = {"4": S4_RECORD,
              "6": S6_CLAUDE.split("## Third")[0].split("\n\n", 2)[2],
              "7": S7_CLAUDE.split("## Recent")[0].split("\n\n", 2)[2]}
    hits = ["%s: %r" % (k, m.group(0)) for k, t in moving.items() for m in [splitlib.RULE_RE.search(t)] if m]
    if hits:
        return False, "a moving record holds a RULE_RE word: " + ", ".join(hits)
    return True, "no RULE_RE word in the moving records of scenarios 4, 6, 7; RULE_RE matches a known rule"


SCENARIOS = [("CONTROL", scenario_0), ("1", scenario_1), ("2", scenario_2), ("3", scenario_3),
             ("4", scenario_4), ("5", scenario_5), ("6", scenario_6), ("7", scenario_7),
             ("8", scenario_8), ("9", scenario_9), ("10", scenario_10), ("11", scenario_11)]

TALLY = re.compile(r"(\d+)/(\d+) passed")


def main():
    failed = []
    try:
        for name, fn in SCENARIOS:
            try:
                ok, detail = fn()
            except FenceBroken as e:
                print("FENCE BROKEN: %s" % e)
                return 2
            except Exception as e:   # noqa: BLE001
                ok, detail = False, "crashed: %s: %s" % (type(e).__name__, e)
            detail = TALLY.sub(r"\1 of \2 passed", detail)
            print("SCENARIO %-7s %s  %s" % (name, "PASS" if ok else "FAIL", detail))
            if not ok:
                failed.append(name)
    finally:
        for d in TMP:
            shutil.rmtree(d, ignore_errors=True)
    if failed:
        print("GOAL NOT MET: failing %s" % ", ".join(failed))
        return 3
    print("GOAL HOLDS: every frozen scenario passes")
    return 0


if __name__ == "__main__":
    sys.exit(main())
