#!/usr/bin/env python3
"""Tests for loss_check.py and the splitlib text rules it uses.

Every fixture is a synthetic string built here and written to a mkdtemp folder;
nothing reads or writes a real project file. Row 0 is a CONTROL with a known
answer: if it fails, the harness is broken rather than the script.

Run:  python3 test_loss_check.py
"""

import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
LOSS = os.path.join(HERE, "loss_check.py")
sys.path.insert(0, HERE)

RULE = ("Never push the nightly widget export straight to the shared bucket "
        "without a dry run first.")

BEFORE = """# Project

Preamble line that says what this file is for.

## Overview

Plain overview text with no obligation word in it at all.

## Widget export record (2026-01-10)

{rule}
The export ran on the staging box and the numbers looked fine.

## Newer record (2026-03-02)

Newer record body text that stays in place.
""".format(rule=RULE)

AFTER_MOVED = """# Project

Preamble line that says what this file is for.

## Overview

Plain overview text with no obligation word in it at all.

## Newer record (2026-03-02)

Newer record body text that stays in place.
"""

ARCHIVE = """# Decisions Log Archive - January 2026

## Widget export record (2026-01-10)

{rule}
The export ran on the staging box and the numbers looked fine.
""".format(rule=RULE)


def run(*args, env=None, cwd=None):
    p = subprocess.run([sys.executable, LOSS] + list(args), stdout=subprocess.PIPE,
                       stderr=subprocess.PIPE, env=env, cwd=cwd)
    return p.returncode, p.stdout.decode("utf-8"), p.stderr.decode("utf-8")


def write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)
    return path


def read(path):
    if not os.path.exists(path):
        return ""
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def prefixed(out, prefix):
    return [l for l in out.splitlines() if l.startswith(prefix)]


def main():
    checks = []
    outputs = []

    def check(name, ok, detail=""):
        if not isinstance(detail, str):
            detail = repr(detail)
        checks.append((name, bool(ok), detail))

    tmpdirs = []

    def folder():
        d = tempfile.mkdtemp(prefix="loss-test-")
        tmpdirs.append(d)
        return d

    def project(before, after, extra=None):
        """A split folder: the backup, CLAUDE.md and any extra top-level files."""
        d = folder()
        b = write(os.path.join(d, "CLAUDE.md.backup-before-split-2026-02-01"), before)
        a = write(os.path.join(d, "CLAUDE.md"), after)
        for name, text in (extra or {}).items():
            write(os.path.join(d, name), text)
        return d, b, a

    def lc(*args, **kw):
        rc, out, err = run(*args, **kw)
        outputs.append(out)
        return rc, out, err

    # ---------------------------------------------------------------- CONTROL
    d, b, a = project(BEFORE, BEFORE)
    rc, out, err = lc("--before", b, "--after", a)
    check("CONTROL identical before and after exits 0 with a LOSS CHECK line",
          rc == 0 and out.startswith("LOSS CHECK"), "rc=%d out=%r err=%r" % (rc, out[-300:], err[-300:]))

    # ------------------------------------------ a moved rule with no pointer
    d, b, a = project(BEFORE, AFTER_MOVED, {"CLAUDE_DECISIONS_2026-01.md": ARCHIVE})
    rc, out, err = lc("--before", b, "--after", a)
    named = [l for l in prefixed(out, "LAZY-ONLY: ") if RULE.rstrip(".") in l]
    check("a rule moved to an archive with no pointer exits 3 and is named LAZY-ONLY",
          rc == 3 and len(named) == 1, "rc=%d out=%r" % (rc, out[-600:]))

    # ---------------------------------- the same run with --accept, and report
    d, b, a = project(BEFORE, AFTER_MOVED, {"CLAUDE_DECISIONS_2026-01.md": ARCHIVE})
    os.makedirs(os.path.join(d, "split_2026-02-01"))
    rep = os.path.join(d, "split_2026-02-01", "LOSS.md")
    rc, out, err = lc("--before", b, "--after", a, "--accept", "nightly widget export straight",
                      "--report", rep)
    r = read(rep)
    check("the same run with --accept <fragment> exits 0", rc == 0, "rc=%d out=%r" % (rc, out[-500:]))
    check("the waived rule is still listed, ending (waived: --accept ...)",
          any(RULE.rstrip(".") in l and l.endswith('(waived: --accept "nightly widget export straight")')
              for l in prefixed(out, "LAZY-ONLY: ")), out[-500:])
    check("the report lists the waiver with its count and the item it let through",
          '--accept "nightly widget export straight" let through 1 item' in r
          and ("let through: " + RULE) in r, r[-600:])

    # ------------------------------------------------- cannot tell, exit 2
    rep2 = os.path.join(d, "split_2026-02-01", "MISSING.md")
    rc, out, err = lc("--before", os.path.join(d, "no-such-backup"), "--after", a, "--report", rep2)
    check("a missing before-file exits 2 (cannot tell), never 0",
          rc == 2 and "CANNOT TELL" in out and "no-such-backup" in out, "rc=%d %r" % (rc, out))
    check("a missing before-file writes no report", not os.path.exists(rep2))
    rc, out, err = lc("--before", b, "--after", os.path.join(d, "gone.md"))
    check("a missing after-file exits 2", rc == 2 and "gone.md" in out, "rc=%d %r" % (rc, out))
    rc, out, err = lc("--before", b, "--after", a, "--lazy", os.path.join(d, "nolazy.md"))
    check("a missing --lazy file exits 2", rc == 2 and "nolazy.md" in out, "rc=%d %r" % (rc, out))
    d, b, a = project(BEFORE, BEFORE)
    write(os.path.join(d, "NOTES.md"), "")
    with open(os.path.join(d, "NOTES.md"), "wb") as fh:
        fh.write(b"Notes caf\xe9 line\n")
    rep3 = os.path.join(d, "LATIN.md")
    rc, out, err = lc("--before", b, "--after", a, "--report", rep3)
    check("a notes-set file that is not UTF-8 exits 2 (CANNOT TELL) naming it, no traceback, "
          "no report", rc == 2 and "CANNOT TELL" in out and "NOTES.md" in out and "Traceback" not in err
          and not os.path.exists(rep3), "rc=%d %r %r" % (rc, out[-300:], err[-200:]))
    d, b, a = project(BEFORE, BEFORE)
    locked = write(os.path.join(d, "NOTES.md"), "Plain notes line.\n")
    os.chmod(locked, 0)
    rep4 = os.path.join(d, "LOCKED.md")
    rc, out, err = lc("--before", b, "--after", a, "--report", rep4)
    unreadable = not os.access(locked, os.R_OK)
    os.chmod(locked, 0o644)
    check("a notes-set file that cannot be opened (mode 000) exits 2 (CANNOT TELL) naming it, "
          "no traceback, no report", unreadable and rc == 2 and "CANNOT TELL" in out and "NOTES.md" in out
          and "Traceback" not in err and not os.path.exists(rep4),
          "unreadable=%r rc=%d %r %r" % (unreadable, rc, out[-300:], err[-200:]))

    # --------------------------------------------- reworded in place is KEPT
    reworded = ("Never push the nightly widget export to the shared bucket unless a "
                "dry run passed first.")
    d, b, a = project(BEFORE, BEFORE.replace(RULE, reworded))
    rc, out, err = lc("--before", b, "--after", a)
    check("a rule reworded in place (one 5-word window survives) reads KEPT, exit 0",
          rc == 0 and not prefixed(out, "LAZY-ONLY: ") and not prefixed(out, "NOWHERE: "),
          "rc=%d %r" % (rc, out[-500:]))

    def one_rule(before_rule, after_text):
        bt = "# P\n\n## Notes\n\n" + before_rule + "\n"
        d, b, a = project(bt, "# P\n\n## Notes\n\n" + after_text + "\n")
        return lc("--before", b, "--after", a)

    rc, out, err = one_rule("Never run `deploy_widget.sh` on a weekend.",
                            "Always ask a reviewer before `deploy_widget.sh` runs.")
    check("kept clause (a) lists, never keeps: a backticked token on a rule-shaped after line no longer keeps "
          "the rule (exit 3, NOWHERE)",
          rc == 3 and prefixed(out, "NOWHERE: Never run"), "rc=%d %r" % (rc, out[-400:]))
    rc, out, err = one_rule("Never run `deploy_widget.sh` on a weekend.",
                            "The helper `deploy_widget.sh` lives in the scripts folder.")
    check("kept clause (a) twin: the token on a line with no rule word does not keep it",
          rc == 3 and prefixed(out, "NOWHERE: Never run"), "rc=%d %r" % (rc, out[-400:]))
    rc, out, err = one_rule("Never edit `TODO.md` by hand during a release.",
                            "Always keep `TODO.md` short and current.")
    check("kept clause (a) skips stoplist tokens (TODO.md keeps nothing)",
          rc == 3, "rc=%d %r" % (rc, out[-400:]))
    import splitlib as _sl
    got = _sl.clause_a_kept("Never edit `TODO.md` by hand during a release.",
                            "# P\n\nAlways keep `TODO.md` short and current.\n")
    check("C clause_a_kept skips a stoplist token (TODO.md on a base-word line keeps nothing)",
          got is False, repr(got))
    got = _sl.clause_a_kept("Never edit `deploy_widget.sh` by hand during a release.",
                            "# P\n\nAlways keep `deploy_widget.sh` short and current.\n")
    check("C clause_a_kept control: a token not on the stoplist on the same line shape is kept",
          got is True, repr(got))
    rc, out, err = one_rule("Never force push.", "Never force push to main.")
    check("a sentence under 5 words is kept by its whole normalized form",
          rc == 0, "rc=%d %r" % (rc, out[-400:]))
    rc, out, err = one_rule("Never force push.", "Never force the push.")
    check("a sentence under 5 words without its whole form is lost",
          rc == 3, "rc=%d %r" % (rc, out[-400:]))

    # ------------------------------------------------------- atom kinds
    import splitlib
    kinds_text = """# Top heading

## Kinds

Links `https://example.invalid/a/b` and `0b1e2c3d-4a5b-6c7d-8e9f-0a1b2c3d4e5f`.
Commit `a1b2c3d` and service `srv-q1w2e` and task `ta1234` and `WIDGET_TOKEN`.
Paths `skills/x/run.py` and `~/notes`; command `git status --short`; plain `build_widget_v2.py`.
Short caps `ABC` stays out.

### Sub heading

```bash
python3 tool.py --flag
# a comment line inside a fence
```
"""
    got = {}
    for it in splitlib.atoms(kinds_text):
        got.setdefault(it.kind, set()).add(it.text)
    check("atom identifiers: URL, UUID, hash, service ids, UPPER_SNAKE",
          got.get("identifier") == {"https://example.invalid/a/b",
                                    "0b1e2c3d-4a5b-6c7d-8e9f-0a1b2c3d4e5f", "a1b2c3d",
                                    "srv-q1w2e", "ta1234", "WIDGET_TOKEN"},
          repr(got.get("identifier")))
    check("atom paths: a token holding / or starting with ~",
          got.get("path") == {"skills/x/run.py", "~/notes"}, repr(got.get("path")))
    check("atom commands: a command-word token and every fenced line",
          got.get("command") == {"git status --short", "python3 tool.py --flag",
                                 "# a comment line inside a fence"}, repr(got.get("command")))
    check("atom headings: every # line outside a fence",
          got.get("heading") == {"# Top heading", "## Kinds", "### Sub heading"},
          repr(got.get("heading")))
    check("a plain file token is no atom", "build_widget_v2.py" not in
          set().union(*got.values()), repr(got))
    rs = splitlib.atoms("## S\n\n- Always tag it; never skip the check. Then rest. Do not wait.\n")
    check("atom rules: split at '. ' and '; ', list marker dropped, one item each",
          [i.text for i in rs if i.kind == "rule"] == ["Always tag it", "never skip the check.",
                                                       "Do not wait."],
          repr([i.text for i in rs]))
    check("RULE_RE holds don't and none of its words inside other words",
          splitlib.RULE_RE.search("don't do it") and not splitlib.RULE_RE.search(
              "nevertheless the mustard is refused"), "")

    # -------------------------------------------- the classifier record
    nd = folder()
    write(os.path.join(nd, "NOTES.md"), "Service `srv-q1w2e` notes.\n")
    res = splitlib.classify("## S\n\nService `srv-q1w2e` runs.\n", "## S\n\nService runs.\n",
                            nd, lazy=[(os.path.join(nd, "NOTES.md"), read(os.path.join(nd, "NOTES.md")))])
    recs = [r.record() for r in res if r.kind == "identifier"]
    check("classifier record: a moved identifier in a top-level NOTES.md is (identifier, LAZY-ONLY, [NOTES.md])",
          recs == [("identifier", "LAZY-ONLY", ["NOTES.md"])], repr(recs))
    kept = [r.record() for r in res if r.kind == "heading"]
    check("classifier record: a KEPT item has empty holding files", kept == [("heading", "KEPT", [])], repr(kept))

    # --------------------------------------------- class listing on stdout
    bt = ("# P\n\n## Overview\n\nKeep `srv-kep11` here.\nService `srv-gon22` ran.\n\n"
          "## Widget export record (2026-01-10)\n\n" + RULE + "\n")
    at = "# P\n\n## Overview\n\nKeep `srv-kep11` here.\nService ran.\n"
    d, b, a = project(bt, at, {"CLAUDE_DECISIONS_2026-01.md": "## Widget export record (2026-01-10)\n\n"
                               + RULE + "\n"})
    rc, out, err = lc("--before", b, "--after", a)
    listed = prefixed(out, "LAZY-ONLY: ") + prefixed(out, "NOWHERE: ")
    check("listing: one LAZY-ONLY rule and one NOWHERE identifier print exactly two class lines",
          sorted(listed) == sorted(["LAZY-ONLY: " + RULE, "LAZY-ONLY: ## Widget export record (2026-01-10)",
                                    "NOWHERE: srv-gon22"]) and rc == 3, "rc=%d %r" % (rc, listed))
    check("listing: a long rule sentence is printed whole, never cut",
          ("LAZY-ONLY: " + RULE) in out and len(RULE) > 60, out[-400:])
    check("listing: no line names a KEPT item", "srv-kep11" not in out, out[-400:])
    check("the refusal names the rule's section",
          "rule in section ## Widget export record (2026-01-10)" in out, out[-600:])

    # ------------------------------------------------------ waiver counts
    def must_rules(n):
        rules = ["Builds must pin version %s of the widget toolchain." % w
                 for w in ("one", "two", "three", "four", "five", "six")[:n]]
        bt = "# P\n\n## Old record (2026-01-02)\n\n" + "\n".join(rules) + "\n"
        d, b, a = project(bt, "# P\n", {"NOTES.md": bt})
        return d, b, a, rules

    d, b, a, rules = must_rules(6)
    os.makedirs(os.path.join(d, "split_2026-02-01"))
    rep = os.path.join(d, "split_2026-02-01", "LOSS.md")
    rc, out, err = lc("--before", b, "--after", a, "--accept", "must", "--report", rep)
    check("waiver count: --accept must over 6 LAZY-ONLY rules still exits 0", rc == 0, "rc=%d %r" % (rc, out[-400:]))
    check("waiver count: stdout names the broad waiver with its count 6",
          'BROAD WAIVER: --accept "must" let through 6 items' in out, out[-400:])
    check("waiver count: the report names the broad waiver with its count 6",
          'BROAD WAIVER: --accept "must" let through 6 items' in read(rep), read(rep)[-400:])
    d, b, a, rules = must_rules(5)
    rc, out, err = lc("--before", b, "--after", a, "--accept", "must")
    check("waiver count: exactly 5 prints the count and no broad line",
          '--accept "must" let through 5 item(s)' in out and "BROAD" not in out, out[-400:])
    rc, out, err = lc("--before", b, "--after", a, "--accept", "version three of")
    check("waiver count: a fragment of one sentence reads count 1",
          '--accept "version three of" let through 1 item(s)' in out and rc == 3, out[-400:])
    rc, out, err = lc("--before", b, "--after", a, "--accept", "no such words anywhere", "--accept", "must")
    check("a waiver that matches nothing is listed as unused, not a failure",
          'UNUSED WAIVER: --accept "no such words anywhere"' in out and rc == 0, out[-400:])
    d, b, a, rules = must_rules(2)
    rc, out, err = lc("--before", b, "--after", a, "--accept", "version one", "--accept", "pin version one")
    check("waiver owners (A) a second --accept matching only an item the first already let through reads unused, "
          "with the waiver that took it; the first still reads 1; exit 3",
          rc == 3 and 'WAIVER: --accept "version one" let through 1 item(s)' in out.splitlines()
          and ('UNUSED WAIVER: --accept "pin version one" let through no item (every match already '
               'waived by --accept "version one")') in out.splitlines(), out[-500:])
    rc, out, err = lc("--before", b, "--after", a, "--accept", "version one", "--accept", "must")
    check("waiver owners (B) --accept must after --accept \"version one\" counts only the item it let through: 1",
          rc == 0 and 'WAIVER: --accept "must" let through 1 item(s)' in out.splitlines(), out[-500:])
    d, b, a, rules = must_rules(6)
    rc, out, err = lc("--before", b, "--after", a, "--accept", rules[0], "--accept", rules[1], "--accept", "must")
    check("waiver owners (D) BROAD reads the let-through count: 6 'must' items, 2 owned by exact waivers, "
          "--accept must reads 4 and no BROAD line",
          rc == 0 and 'WAIVER: --accept "must" let through 4 item(s)' in out.splitlines() and "BROAD" not in out,
          out[-500:])

    # ------------------------------------------------------ empty waivers
    ids_b = ("# P\n\n## Overview\n\nServices `srv-aaa11`, `srv-bbb22` and `srv-ccc33` run here.\n\n"
             "## Old heading\n\nPlain words here.\n")
    ids_a = "# P\n\n## Overview\n\nServices run here.\n"
    d, b, a = project(ids_b, ids_a)
    af = write(os.path.join(d, "split_2026-02-01", "accept.txt"),
               "srv-aaa11\n\n   \nsrv-bbb22\n## Old heading\n")
    rc, out, err = lc("--before", b, "--after", a, "--accept-file", af)
    nw = prefixed(out, "NOWHERE: ")
    check("empty waivers (a): blank and whitespace-only lines are skipped; the third item stays unwaived, exit 3",
          rc == 3 and "NOWHERE: srv-ccc33" in nw, "rc=%d %r" % (rc, nw))
    check("empty waivers (a): the two named items read (waived: ...) with count 1 each",
          'NOWHERE: srv-aaa11 (waived: --accept-file "srv-aaa11")' in nw
          and 'NOWHERE: srv-bbb22 (waived: --accept-file "srv-bbb22")' in nw
          and '--accept-file "srv-aaa11" let through 1 item(s)' in out
          and '--accept-file "srv-bbb22" let through 1 item(s)' in out, repr(nw) + out[-300:])
    check("empty waivers (d): a list line '## Old heading' waives that deleted heading item",
          'NOWHERE: ## Old heading (waived: --accept-file "## Old heading")' in nw, repr(nw))
    write(af, "srv-aaa11\n\n   \nsrv-bbb22\n## Old heading\nsrv-ccc33\n")
    rc, out, err = lc("--before", b, "--after", a, "--accept-file", af)
    check("empty waivers (b): with the third item's text added, exit 0", rc == 0, "rc=%d %r" % (rc, out[-300:]))
    pw = [(i.kind, i.text) for i in splitlib.atoms("# P\n\n## Old heading\n\nPlain words only.\n")
          if i.kind == "rule"]
    check("empty waivers (b) twin: splitlib.atoms reads 'Plain words only.' as one rule item",
          pw == [("rule", "Plain words only.")], repr(pw))
    rc, out, err = lc("--before", b, "--after", a, "--accept", "")
    check("empty waivers (c): --accept \"\" exits 2 naming --accept", rc == 2 and "--accept" in out, "rc=%d %r" % (rc, out))
    rc, out, err = lc("--before", b, "--after", a, "--accept", "   ")
    check("empty waivers (c): --accept of spaces exits 2 naming --accept", rc == 2 and "--accept" in out, "rc=%d %r" % (rc, out))
    check("empty waivers: the empty-value refusal is its own splitlib function",
          splitlib.refuse_empty_waiver("--move-anyway", " ") and "--move-anyway" in
          splitlib.refuse_empty_waiver("--move-anyway", " ")
          and splitlib.refuse_empty_waiver("--accept", "x") is None, "")

    # ------------------------------------------- structure check
    S_BEFORE = ("# Project\n\nPreamble text line.\n\n## Overview\n\nOverview text.\n\n"
                "## Old record (2026-01-05)\n\nOld record body text.\n\n"
                "## New record (2026-03-05)\n\nNew record body text.\n")
    LAST = ("Last split run: 2026-02-01, 1K to 1K chars, 1 records moved to "
            "`CLAUDE_DECISIONS_INDEX.md`, report split_2026-02-01/REPORT.md\n")
    S_AFTER3 = ("# Project\n\nPreamble text line.\n\n## Overview\n\nOverview text.\n\n" + LAST + "\n"
                "## New record (2026-03-05)\n\nNew record body text.\n")
    ARCH_S = "## Old record (2026-01-05)\n\nOld record body text.\n"

    def structure(before, after, *extra):
        d, b, a = project(before, after, {"CLAUDE_DECISIONS_2026-01.md": ARCH_S})
        return lc("--before", b, "--after", a, "--structure", *extra)

    rc, out, err = structure(S_BEFORE, S_AFTER3)
    check("structure (a): Last-run line by placement (3), line plus its blank, exits 0",
          rc == 0, "rc=%d %r" % (rc, out[-400:]))
    M_BEFORE = S_BEFORE.replace("## Overview", "## Maintenance rule\n\nRotate when it grows.\n\n## Overview")
    M_AFTER2 = ("# Project\n\nPreamble text line.\n\n## Maintenance rule\n" + LAST
                + "\nRotate when it grows.\n\n## Overview\n\nOverview text.\n\n"
                "## New record (2026-03-05)\n\nNew record body text.\n")
    rc, out, err = structure(M_BEFORE, M_AFTER2)
    check("structure (b): placement (2) after the Maintenance rule heading and its own blank exits 0",
          rc == 0, "rc=%d %r" % (rc, out[-400:]))
    rc, out, err = structure(S_BEFORE, S_AFTER3.replace(LAST + "\n", LAST + "\n\n"))
    check("structure (c): one extra blank after the Last-run line is refused, naming that section",
          rc == 3 and "STRUCTURE CHANGED: ## Overview" in out, "rc=%d %r" % (rc, out[-400:]))
    rc, out, err = structure(S_BEFORE, S_AFTER3.replace("New record body text.\n", "New record body text.\n\n"))
    check("structure (d): a blank line added elsewhere in an unedited section is refused",
          rc == 3 and "STRUCTURE CHANGED: ## New record (2026-03-05)" in out, "rc=%d %r" % (rc, out[-400:]))
    rc, out, err = structure(S_BEFORE, S_AFTER3.replace("Preamble text line.", "Preamble text, edited."))
    check("structure: a changed preamble exits 3 and names the preamble",
          rc == 3 and "STRUCTURE CHANGED: preamble" in out, "rc=%d %r" % (rc, out[-400:]))
    rc, out, err = structure(S_BEFORE, S_AFTER3 + "## Standing rules kept\n\nKept text here.\n")
    check("structure: a section new in the after-file must be named by --edited (exit 3 without)",
          rc == 3 and "## Standing rules kept" in out and "--edited" in out, "rc=%d %r" % (rc, out[-400:]))
    rc, out, err = structure(S_BEFORE, S_AFTER3 + "## Standing rules kept\n\nKept text here.\n",
                             "--edited", "Standing rules kept")
    check("structure: the new section named by --edited exits 0", rc == 0, "rc=%d %r" % (rc, out[-400:]))
    rc, out, err = structure(S_BEFORE, S_AFTER3.replace("Overview text.", "Overview text, edited."),
                             "--edited", "## Overview")
    check("structure: a changed section named by --edited exits 0", rc == 0, "rc=%d %r" % (rc, out[-400:]))
    rc, out, err = lc("--before", b, "--after", a)
    PROF = "# P\n\n## Project profile\n\nRepo one.\n\n## Project profile\n\nRepo two.\n"
    keys = list(splitlib.sections(PROF).keys())
    check("sections: two sections with the same heading are told apart by occurrence number",
          keys == [("", 1), ("## Project profile", 1), ("## Project profile", 2)], repr(keys))
    check("sections: sections() gives back the text byte for byte",
          "".join(splitlib.sections(PROF).values()) == PROF)
    rc, out, err = structure(PROF, PROF.replace("Repo two.", "Repo two, edited."))
    check("sections: a change to the second one names occurrence 2 only",
          rc == 3 and "## Project profile (occurrence 2)" in out
          and "STRUCTURE CHANGED: ## Project profile (changed)" not in out, "rc=%d %r" % (rc, out[-400:]))

    # ------------------------------------------- --hoisted
    A = os.path.realpath(folder())
    proj = os.path.join(A, "proj")
    hb = write(os.path.join(proj, "CLAUDE.md.backup-before-split-2026-02-01"), BEFORE)
    ha = write(os.path.join(proj, "CLAUDE.md"), AFTER_MOVED)
    write(os.path.join(proj, "CLAUDE_DECISIONS_2026-01.md"), ARCHIVE)
    write(os.path.join(A, "CLAUDE.md"), "# Ancestor\n\n" + RULE + "\n")
    hrep = os.path.join(proj, "split_2026-02-01", "LOSS.md")
    os.makedirs(os.path.dirname(hrep))

    def hoist(path, env=None, after=ha, before=hb):
        if os.path.exists(hrep):
            os.remove(hrep)
        return lc("--before", before, "--after", after, "--hoisted", path, "--report", hrep, env=env)

    rc, out, err = lc("--before", hb, "--after", ha)
    check("hoisted: an absent --hoisted counts nothing as kept (exit 3)", rc == 3, "rc=%d" % rc)
    rc, out, err = hoist(os.path.join(A, "nope", "CLAUDE.md"))
    check("hoisted: a missing --hoisted file exits 2, names it, writes no report",
          rc == 2 and "nope" in out and not os.path.exists(hrep), "rc=%d %r" % (rc, out))

    def refused(name, path, reason=None, **kw):
        rc, out, err = hoist(path, **kw)
        check("hoisted %s: exits 2, names the path, writes no report" % name,
              rc == 2 and path in out and not os.path.exists(hrep)
              and (reason is None or reason in out), "rc=%d %r" % (rc, out[-400:]))

    refused("(a) --hoisted equal to --after", ha, "file being split")
    write(os.path.join(proj, "NOTES.md"), RULE + "\n")
    refused("(b) a top-level NOTES.md", os.path.join(proj, "NOTES.md"))
    os.remove(os.path.join(proj, "NOTES.md"))
    refused("(c) split_2026-01-01/CLAUDE.md", write(os.path.join(proj, "split_2026-01-01", "CLAUDE.md"), RULE + "\n"))
    other = os.path.realpath(folder())
    refused("(d) a CLAUDE.md in an unrelated mkdtemp", write(os.path.join(other, "CLAUDE.md"), RULE + "\n"),
            "not loaded")
    refused("(e) a sibling <A>/other/CLAUDE.md", write(os.path.join(A, "other", "CLAUDE.md"), RULE + "\n"),
            "not loaded")

    def linked(target):
        sib = folder()
        L = os.path.join(sib, "L")
        os.symlink(os.path.realpath(target), L)
        return L

    def accepted(name, path, env=None):
        rc, out, err = hoist(path, env=env)
        check("hoisted control %s: accepted, reports KEPT (hoisted: ...), exit 0" % name,
              rc == 0 and "KEPT (hoisted: " in read(hrep), "rc=%d %r %r" % (rc, out[-400:], read(hrep)[-300:]))

    L = linked(A)
    check("hoisted: the linked folder differs from its realpath", os.path.realpath(L) != L, L)
    accepted("ancestor <A>/CLAUDE.md via a linked folder", os.path.join(L, "CLAUDE.md"))
    write(os.path.join(proj, ".claude", "CLAUDE.md"), RULE + "\n")
    accepted("<A>/proj/.claude/CLAUDE.md via a linked folder", os.path.join(L, "proj", ".claude", "CLAUDE.md"))
    H = os.path.realpath(folder())
    write(os.path.join(H, ".claude", "CLAUDE.md"), RULE + "\n")
    LH = linked(H)
    env = dict(os.environ, HOME=H)
    accepted("<H>/.claude/CLAUDE.md with HOME=<H> via a linked folder",
             os.path.join(LH, ".claude", "CLAUDE.md"), env=env)
    LP = linked(proj)
    rc, out, err = hoist(os.path.join(proj, "CLAUDE.md"), after=os.path.join(LP, "CLAUDE.md"),
                         before=os.path.join(LP, "CLAUDE.md.backup-before-split-2026-02-01"))
    check("hoisted (f): target given through a linked folder, --hoisted its real path: exit 2 as the file being split",
          rc == 2 and "file being split" in out, "rc=%d %r" % (rc, out[-400:]))

    # Membership is realpath equality: a loaded CLAUDE.md that is itself a link
    A8 = os.path.realpath(folder())
    p8 = os.path.join(A8, "proj")
    b8 = write(os.path.join(p8, "CLAUDE.md.backup-before-split-2026-02-01"), BEFORE)
    a8 = write(os.path.join(p8, "CLAUDE.md"), AFTER_MOVED)
    write(os.path.join(p8, "CLAUDE_DECISIONS_2026-01.md"), ARCHIVE)
    H8 = os.path.realpath(folder())
    real8 = write(os.path.join(os.path.realpath(folder()), "CLAUDE.md"), "# Global\n\n" + RULE + "\n")
    os.makedirs(os.path.join(H8, ".claude"))
    os.symlink(real8, os.path.join(H8, ".claude", "CLAUDE.md"))
    env8 = dict(os.environ, HOME=H8)
    rep8 = os.path.join(p8, "R8.md")
    rc, out, err = lc("--before", b8, "--after", a8, "--hoisted", os.path.join(H8, ".claude", "CLAUDE.md"),
                      "--report", rep8, env=env8)
    check("linked <H>/.claude/CLAUDE.md as a FILE symlink to a CLAUDE.md elsewhere, HOME=<H>: accepted, "
          "exit 0, KEPT (hoisted: ...)", rc == 0 and "KEPT (hoisted: " in read(rep8),
          "rc=%d %r" % (rc, out[-400:]))
    stray = os.path.join(os.path.realpath(folder()), "CLAUDE.md")
    os.symlink(write(os.path.join(os.path.realpath(folder()), "CLAUDE.md"), "# Unrelated\n\n" + RULE + "\n"),
               stray)
    rc, out, err = lc("--before", b8, "--after", a8, "--hoisted", stray, env=env8)
    check("linked twin: a link outside the loaded set pointing at an unrelated CLAUDE.md still exits 2 'not loaded'",
          rc == 2 and "not loaded" in out, "rc=%d %r" % (rc, out[-300:]))
    write(os.path.join(p8, "shared", "CLAUDE.md"), "# Shared\n\n" + RULE + "\n")
    os.makedirs(os.path.join(p8, ".claude"))
    os.symlink(os.path.join(p8, "shared", "CLAUDE.md"), os.path.join(p8, ".claude", "CLAUDE.md"))
    rep8c = os.path.join(p8, "R8c.md")
    rc, out, err = lc("--before", b8, "--after", a8, "--hoisted", os.path.join(p8, ".claude", "CLAUDE.md"),
                      "--report", rep8c, env=env8)
    check("linked (c): <F>/.claude/CLAUDE.md as a link to a file inside F is the loaded file: accepted, exit 0",
          rc == 0 and "KEPT (hoisted: " in read(rep8c), "rc=%d %r" % (rc, out[-400:]))

    # ------------------------------------------------------ lazy files
    idb = "# P\n\n## Overview\n\nService `srv-mov77` runs.\n"
    ida = "# P\n\n## Overview\n\nService runs.\n"
    d, b, a = project(idb, ida, {"split_2026-01-01/REPORT.md": "Quoted `srv-mov77` here.\n"})
    rc, out, err = lc("--before", b, "--after", a)
    check("lazy files (i): an identifier quoted only in a split_*/ subfolder reads NOWHERE, exit 3",
          rc == 3 and "NOWHERE: srv-mov77" in out, "rc=%d %r" % (rc, out[-400:]))
    d, b, a = project(idb, ida, {"NOTES.md": "Quoted `srv-mov77` here.\n"})
    rc, out, err = lc("--before", b, "--after", a)
    check("lazy files (ii): the same text in a top-level NOTES.md reads LAZY-ONLY (non-blocking)",
          rc == 0 and "LAZY-ONLY: srv-mov77" in out, "rc=%d %r" % (rc, out[-400:]))
    d, b, a = project(idb, ida)
    lz = write(os.path.join(folder(), "elsewhere.md"), "Quoted `srv-mov77` here.\n")
    rc, out, err = lc("--before", b, "--after", a, "--lazy", lz)
    check("a --lazy file outside the folder is searched too", rc == 0 and "LAZY-ONLY: srv-mov77" in out,
          "rc=%d %r" % (rc, out[-400:]))

    # ---------------------------------------------- POINTED (stub resolver)
    pb = "# P\n\n## Overview\n\nService `srv-pnt01` runs.\n" + RULE + "\n"
    pa = "# P\n\n## Overview\n\nDetail in `NOTES.md`.\n"
    d, b, a = project(pb, pa, {"NOTES.md": "Service `srv-pnt01` runs.\n" + RULE + "\n"})
    rc, out, err = lc("--before", b, "--after", a)
    check("POINTED: moved to NOTES.md and the owning section points there, exit 0",
          rc == 0 and "POINTED 2" in out, "rc=%d %r" % (rc, out[-400:]))
    d, b, a = project(pb, "# P\n\n## Overview\n\nNothing here now.\n",
                      {"NOTES.md": "Service `srv-pnt01` runs.\n" + RULE + "\n"})
    rc, out, err = lc("--before", b, "--after", a)
    check("POINTED twin: with the pointer gone the rule reads LAZY-ONLY and blocks",
          rc == 3 and ("LAZY-ONLY: " + RULE) in out, "rc=%d %r" % (rc, out[-400:]))
    arch_b = BEFORE.replace("The export ran", "Service `srv-arc44` ran. The export ran")
    arch_a = AFTER_MOVED + "\nOld records: see `CLAUDE_DECISIONS_2026-01.md`.\n"
    arch_txt = ARCHIVE.replace("The export ran", "Service `srv-arc44` ran. The export ran")
    write(os.path.join(d, "CLAUDE_DECISIONS_2026-01.md"), arch_txt)
    res = splitlib.classify(arch_b, arch_a, d, lazy=[(os.path.join(d, "CLAUDE_DECISIONS_2026-01.md"), arch_txt)])
    got = dict((r.item.text, (r.label(), r.holding)) for r in res)
    check("POINTED (archive): an identifier moved into an archive the after file points at",
          got.get("srv-arc44") == ("POINTED (archive: CLAUDE_DECISIONS_2026-01.md)",
                                      ["CLAUDE_DECISIONS_2026-01.md"]), repr(got.get("srv-arc44")))
    check("a rule sentence from the same record is never POINTED (archive)",
          got.get(RULE, ("",))[0] == "LAZY-ONLY", repr(got.get(RULE)))
    res = splitlib.classify(arch_b, AFTER_MOVED, d,
                            lazy=[(os.path.join(d, "CLAUDE_DECISIONS_2026-01.md"), arch_txt)])
    got = dict((r.item.text, r.cls) for r in res)
    check("POINTED (archive) twin: no pointer, the identifier reads LAZY-ONLY",
          got.get("srv-arc44") == "LAZY-ONLY", repr(got.get("srv-arc44")))

    # ------------------------------------------- --narrative waiver argument
    res = splitlib.classify(BEFORE, AFTER_MOVED, d,
                            lazy=[(os.path.join(d, "CLAUDE_DECISIONS_2026-01.md"), ARCHIVE)],
                            narrative={RULE: '--narrative "Widget export record"'})
    rr = [r for r in res if r.item.text == RULE]
    check("the classifier takes per-record --narrative waivers as an argument",
          len(rr) == 1 and rr[0].cls == "LAZY-ONLY" and rr[0].waiver == '--narrative "Widget export record"'
          and not splitlib.unwaived_blocking(res), repr([(r.item.text, r.cls, r.waiver) for r in res]))

    # ----------------------------------------- characters, not bytes (L10N)
    heb = "# פרויקט\n\n## סקירה\n\nשורה בעברית שאינה כוללת מילת חובה כלשהי.\n"
    d, b, a = project(heb, heb)
    rep = os.path.join(d, "split_2026-02-01", "LOSS.md")
    os.makedirs(os.path.dirname(rep))
    rc, out, err = lc("--before", b, "--after", a, "--report", rep)
    check("Hebrew fixture: lengths are counted in characters, not bytes",
          rc == 0 and ("chars before %d  after %d" % (len(heb), len(heb))) in out
          and ("(%d chars)" % len(heb)) in read(rep) and len(heb) != len(heb.encode("utf-8")),
          "rc=%d %r" % (rc, out[:300]))

    # ---------------------------------------------- 160K chars under 10 s
    import time
    parts = ["# Big\n\nPreamble.\n"]
    for i in range(700):
        parts.append("\n## Record number %d about widget batch %d (2026-01-%02d)\n\n"
                     "Never ship batch %d without the checksum `srv-b%06d` recorded first.\n"
                     "Path `skills/batch_%d/run.py` and command `git log -1 batch-%d` apply.\n"
                     "Plain filler text about the widget pipeline and its staging run number %d.\n"
                     % (i, i, i % 28 + 1, i, i, i, i, i))
    big = "".join(parts)
    keep_half = "".join(parts[:350])
    d, b, a = project(big, keep_half, {"NOTES.md": "".join(parts[350:])})
    t0 = time.time()
    rc, out, err = lc("--before", b, "--after", a)
    dt = time.time() - t0
    check("speed (loss part): a %dK-char file is checked in under 10 s" % (len(big) // 1000),
          len(big) >= 160000 and dt < 10 and rc == 3, "len=%d dt=%.1f rc=%d" % (len(big), dt, rc))

    # ------------------------------------- atoms on token edges
    w_before = ("# P\n\n## Notes\n\nCard `ta47` tracks the export.\n\n"
                "See `ta4731` for the import.\n\nKeep logs in `~/data/logs/`.\n")
    w_after = ("# P\n\n## Notes\n\nSee `ta4731` for the import.\n\n"
               "Keep logs in `~/data/logs/app.log`.\n")
    d, b, a = project(w_before, w_after)
    rc, out, err = lc("--before", b, "--after", a)
    check("edges: an identifier and a path held in after only inside longer tokens read NOWHERE: "
          "exit 3 with NOWHERE: ta47 and NOWHERE: ~/data/logs/",
          rc == 3 and "NOWHERE: ta47" in out.splitlines() and "NOWHERE: ~/data/logs/" in out.splitlines(),
          "rc=%d %r" % (rc, out[-500:]))
    d, b, a = project(w_before, "# P\n\n## Notes\n\nCard `ta47` moved to the board.\n\n"
                      "See `ta4731` for the import.\n\nLogs live in `~/data/logs/` now.\n")
    rc, out, err = lc("--before", b, "--after", a)
    check("edges (a) the same atoms on edges in after (in backticks) are KEPT: exit 0, no NOWHERE line",
          rc == 0 and not prefixed(out, "NOWHERE: "), "rc=%d %r" % (rc, out[-400:]))
    oks = []
    for tail in ("The card moved; it was ta47.", "We can see ta47, then the board."):
        d, b, a = project(w_before, "# P\n\n## Notes\n\n" + tail + "\n\nSee `ta4731` for the import.\n\n"
                          "Logs live in `~/data/logs/` now.\n")
        rc, out, err = lc("--before", b, "--after", a)
        oks.append((rc, prefixed(out, "NOWHERE: ")))
    check("edges (b) the atom as a bare word with '.' or ',' after it is KEPT: exit 0 both ways",
          oks == [(0, []), (0, [])], repr(oks))
    d, b, a = project(w_before, "# P\n\n## Notes\n\nSee `ta4731` for the import.\n\n"
                      "Logs live in `~/data/logs/` now.\n",
                      {"NOTES.md": "# Notes\n\nCard `ta47` tracks the export.\n"})
    rc, out, err = lc("--before", b, "--after", a)
    check("edges (c) the atom moved verbatim into a top-level note nothing points at, after holding "
          "only the longer token: LAZY-ONLY, exit 0, never NOWHERE",
          rc == 0 and any(l.startswith("LAZY-ONLY: ta47") for l in out.splitlines())
          and not any(l.startswith("NOWHERE: ta47") for l in out.splitlines()),
          "rc=%d %r" % (rc, out[-400:]))
    fenced = "# P\n\n## Run\n\n```bash\npython3 tool.py --flag\n```\n"
    d, b, a = project(fenced, fenced + "\nA plain line added below the block.\n")
    rc, out, err = lc("--before", b, "--after", a)
    check("edges (d) a fenced command line unchanged in after is KEPT: exit 0, no NOWHERE line",
          rc == 0 and not prefixed(out, "NOWHERE: "), "rc=%d %r" % (rc, out[-400:]))
    d, b, a = project("# P\n\n## Notes\n\nKeep logs in `~/data/logs`.\n",
                      "# P\n\n## Notes\n\nKeep logs in `~/data/logs/`.\n")
    rc, out, err = lc("--before", b, "--after", a)
    check("edges (e) a path held in after only with a trailing '/' reads NOWHERE: exit 3",
          rc == 3 and "NOWHERE: ~/data/logs" in out.splitlines(), "rc=%d %r" % (rc, out[-400:]))

    # ------------------------------- fence state across sections
    r3 = "Never reveal the actual account token to callers."
    r3_before = ("# P\n\n## Real section\n\n```\n## Sample\n```\n" + r3 + "\n\n"
                 "## Next\n\nNext section text.\n")
    r3_after = "# P\n\n## Real section\n\nShort.\n\n## Next\n\nNext section text.\n"
    d, b, a = project(r3_before, r3_after)
    arch = write(os.path.join(folder(), "arch", "ARCHIVE.md"), "# Archive\n\n" + r3 + "\n")
    rc, out, err = lc("--before", b, "--after", a, "--lazy", arch)
    check("fence across sections: a rule after a fenced '## ' line that moved to a lazy archive blocks: exit 3, "
          "'rule in section'", rc == 3 and "rule in section ## Sample" in out
          and any(l.startswith("LAZY-ONLY: " + r3) for l in out.splitlines()), "rc=%d %r" % (rc, out[-400:]))

    # ------------------------------- one fence reader
    fa_rule = "- Never deploy on a Friday without a rollback plan ready."
    fa_shapes = [("four_three_four", "````\n```\n````\n"), ("tilde_holds_tick", "~~~\n```\n~~~\n"),
                 ("unclosed", "```\necho hi\n"), ("ctl_balanced", "```\necho hi\n```\n")]
    for fa_name, fa_block in fa_shapes:
        fa_head = "# Notes\n\n## Docs\n\nExample:\n\n" + fa_block + "\n## Deploy\n\n"
        d, b, a = project(fa_head + fa_rule + "\n", fa_head + "See NOTES.md.\n",
                          {"NOTES.md": fa_rule + "\n"})
        rc, out, err = lc("--before", b, "--after", a, "--lazy", os.path.join(d, "NOTES.md"))
        if fa_name == "unclosed":
            want = "CANNOT TELL: fence opened at line 7 never closes (%s)" % b
            check("A unclosed: a fence never closed exits 2 with the CANNOT TELL line naming the "
                  "opener's line and the file, no Traceback",
                  rc == 2 and prefixed(out, "CANNOT TELL: fence opened at line")[:1] == [want]
                  and "Traceback" not in err, "rc=%d %r %r" % (rc, out[-400:], err[-300:]))
        else:
            check("A %s: the rule after the block that moved to a lazy file blocks: exit 3, "
                  "'rule in section ## Deploy'" % fa_name,
                  rc == 3 and "rule in section ## Deploy" in out, "rc=%d %r" % (rc, out[-400:]))

    # ------------- a fence reading never decides whether a rule blocks (group G)
    g_rule = "Never deploy on a Friday without a rollback plan ready."

    def g_doc(shape, rule_line):
        if shape == "a":
            b1, b2 = "- ```bash\n  make install\n  ```\n", "- ```bash\n  make test\n  ```\n"
        else:
            b1, b2 = "```bash\nmake install\n``` end of setup\n", "```bash\nmake test\n```\n"
        return "# Notes\n\n## Setup\n\n" + b1 + "\n## Deploy\n\n" + rule_line + "\n\n## Test\n\n" + b2

    for shape in ("a", "b"):
        d, b, a = project(g_doc(shape, "- " + g_rule), g_doc(shape, "- Deploy notes moved to NOTES.md."),
                          {"NOTES.md": "# Notes\n\n- " + g_rule + "\n"})
        rc, out, err = lc("--before", b, "--after", a, "--lazy", os.path.join(d, "NOTES.md"))
        lines = out.splitlines()
        at = lines.index("LAZY-ONLY: " + g_rule) if ("LAZY-ONLY: " + g_rule) in lines else -1
        check("G C1 first red, loss_check.py, shape (%s): exit 3, the line 'LAZY-ONLY: %s' then '    rule in "
              "section ## Deploy; held in NOTES.md blocks; ...', and 'FINDING: 1 item(s) lost without a waiver'"
              % (shape, g_rule),
              rc == 3 and at >= 0 and at + 1 < len(lines)
              and lines[at + 1].startswith("    rule in section ## Deploy; held in NOTES.md blocks; ")
              and prefixed(out, "FINDING: 1 item(s) lost without a waiver")
              and not prefixed(out, "HOLDS: "), "rc=%d %r" % (rc, out[-600:]))
    d, b, a = project(g_doc("b", "- " + g_rule), g_doc("b", "- Deploy notes moved to NOTES.md."),
                      {"NOTES.md": "# Notes\n\n- " + g_rule + "\n"})
    rc, out, err = lc("--before", b, "--after", a, "--lazy", os.path.join(d, "NOTES.md"),
                      "--accept", "Never deploy on a Friday")
    check("G waiver twin: shape (b) with --accept \"Never deploy on a Friday\" exits 0 with 'HOLDS: ' "
          "(the loss-check waiver reaches a fenced rule item)",
          rc == 0 and prefixed(out, "HOLDS: nothing lost without a waiver"), "rc=%d %r" % (rc, out[-400:]))
    g_kept = "# P\n\n## Ops\n\n```bash\n# never run this against prod\nmake deploy\n```\n"
    d, b, a = project(g_kept, g_kept)
    rc, out, err = lc("--before", b, "--after", a)
    check("G kept fenced rule twin: a section that does not move, fenced '# never run this against prod', "
          "before == after: exit 0, 'HOLDS: '", rc == 0 and prefixed(out, "HOLDS: nothing lost without a waiver"),
          "rc=%d %r" % (rc, out[-400:]))

    # ------------- a pointer candidate through a file is absent (group H)
    h_rule = "Never push the nightly build without a dry run first."
    h_before = "# P\n\n## Notes\n\n" + h_rule + "\n"
    h_after = h_before + "\nDetail: see `NOTES.md/old.md`.\n"
    d, b, a = project(h_before, h_after, {"NOTES.md": "# Notes\n\nNotes body text.\n"})
    rc, out, err = lc("--before", b, "--after", a)
    check("H1 a pointer 'NOTES.md/old.md' through a regular file is absent, not cannot tell: exit 0, "
          "'HOLDS: nothing lost without a waiver', no 'CANNOT TELL: ' line",
          rc == 0 and prefixed(out, "HOLDS: nothing lost without a waiver") and not prefixed(out, "CANNOT TELL: "),
          "rc=%d %r" % (rc, out[-400:]))
    rp = subprocess.run([sys.executable, os.path.join(HERE, "pointers.py"), a, "--root", folder()],
                        capture_output=True, text=True)
    check("H3 pointers.py on the same after file with an empty --root: exit 3, the pointer listed "
          "'UNRESOLVED: NOTES.md/old.md in section ## Notes', no 'CANNOT TELL: '",
          rp.returncode == 3 and prefixed(rp.stdout, "UNRESOLVED: NOTES.md/old.md in section ## Notes")
          and not prefixed(rp.stdout, "CANNOT TELL: "), "rc=%d %r" % (rp.returncode, rp.stdout[-400:]))
    long_tok = "a" * 297 + ".md"
    d, b, a = project(h_before, h_before + "\nDetail: see `" + long_tok + "`.\n")
    rc, out, err = lc("--before", b, "--after", a)
    check("H4 a 300-character backticked token on a pointer line (ENAMETOOLONG) is absent: exit 0, 'HOLDS: ', "
          "no 'CANNOT TELL: '", rc == 0 and prefixed(out, "HOLDS: ") and not prefixed(out, "CANNOT TELL: "),
          "rc=%d %r" % (rc, out[-300:]))
    hd = folder()
    h_claude = ("# P\n\n## Notes\n\nDetail: see `NOTES.md/old.md`.\n\n## Old record (2026-01-05)\n\n"
                "An old story about the shelf.\n\n## New record (2026-09-01)\n\nRecent notes.\n")
    hp = write(os.path.join(hd, "CLAUDE.md"), h_claude)
    write(os.path.join(hd, "NOTES.md"), "# Notes\n\nNotes body text.\n")
    rr = subprocess.run([sys.executable, os.path.join(HERE, "rotate.py"), hp, "--convention", "section",
                         "--cut-date", "2026-06-01", "--today", "2026-10-08", "--root", folder()],
                        capture_output=True, text=True)
    plines = [l for l in rr.stdout.splitlines() if l.startswith("POINTERS: ")]
    check("H2 rotate.py dry run with the pointer in a KEPT section and an empty --root: exit 0, the pointer "
          "counted unresolved on the 'POINTERS: ' line and listed '  UNRESOLVED: NOTES.md/old.md in section "
          "## Notes', no 'CANNOT TELL: '",
          rr.returncode == 0 and len(plines) == 1 and " 1 unresolved " in plines[0]
          and prefixed(rr.stdout, "  UNRESOLVED: NOTES.md/old.md in section ## Notes")
          and not prefixed(rr.stdout, "CANNOT TELL: "), "rc=%d %r" % (rr.returncode, rr.stdout[-500:]))

    # ------------- notes_set decides containment before it stats a link (group I)
    i_text = "# P\n\n## Notes\n\nNever leave the loading dock door open at night.\n"
    for label in ("I1", "I2"):
        top = folder()
        p = os.path.join(top, "p")
        b = write(os.path.join(p, "before.md"), i_text)
        a = write(os.path.join(p, "CLAUDE.md"), i_text)
        if label == "I1":
            locked = os.path.join(top, "locked")              # outside the folder
            link = os.path.join(p, "ext.md")
        else:
            locked = os.path.join(p, "locked")                # inside the folder
            link = os.path.join(p, "int.md")
        write(os.path.join(locked, "x.md"), "# X\n\nx\n")
        os.symlink(os.path.join(locked, "x.md"), link)
        os.chmod(locked, 0)
        try:
            denied = not os.access(os.path.join(locked, "x.md"), os.R_OK)
            rc, out, err = lc("--before", b, "--after", a)
        finally:
            os.chmod(locked, 0o755)
        if not denied:
            print("  SKIPPED %s: chmod 000 did not take (running as root?)" % label)
            continue
        if label == "I1":
            check("I1 a *.md symlink in the folder into a mode-000 folder OUTSIDE it is skipped before any "
                  "stat follows it: before == after exits 0 with 'HOLDS: ', no 'CANNOT TELL: '",
                  rc == 0 and prefixed(out, "HOLDS: nothing lost without a waiver")
                  and not prefixed(out, "CANNOT TELL: "), "rc=%d %r" % (rc, out[-400:]))
        else:
            check("I2 (twin) a *.md symlink to a file in a mode-000 folder INSIDE the folder stays cannot "
                  "tell: exit 2 with a 'CANNOT TELL: ' line naming the link, no 'HOLDS: '",
                  rc == 2 and any(l.startswith("CANNOT TELL: ") and "int.md" in l for l in out.splitlines())
                  and not prefixed(out, "HOLDS: "), "rc=%d %r" % (rc, out[-400:]))

    # ------------------------------------------------------------ odds
    import hashlib
    sp = write(os.path.join(folder(), "x.md"), "abc")
    check("sha256() is the file's sha256", splitlib.sha256(sp) == hashlib.sha256(b"abc").hexdigest())
    import re as _re
    tally = _re.compile(r"\d+/\d+ passed")
    bad = [l for o in outputs for l in o.splitlines() if tally.search(l)]
    check("tally shape: no loss_check output line looks like a test tally", not bad, repr(bad[:3]))

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
