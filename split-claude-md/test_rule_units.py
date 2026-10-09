#!/usr/bin/env python3
"""Tests for rule units and rule sentences (splitlib and rotate.py).

A rule UNIT is what the rules draft lists: a paragraph or list item with its
continuation lines joined, a table row, or a heading, holding a rule word. A
rule SENTENCE is what the loss check and the refusal read: each piece of a
rule-shaped unit that holds a rule word. A unit counts as kept only when
every rule sentence in it is kept. The fragment check after an in-file hoist
skips a body line only when it is in a kept text AND still in CLAUDE.md.

Every fixture is a synthetic string built here and written to a mkdtemp
folder. Every hoist is a draft line copied from the dry run's own stdout.
Row 0 is a CONTROL with a known answer: if it fails, the harness is broken
rather than the code.

Run:  python3 test_rule_units.py
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
import splitlib  # noqa: E402
import test_rotate  # noqa: E402
import test_rotate_rules as trr  # noqa: E402

DRAFT_RE = re.compile(r'^- (.*) \(kept from "(.*)", (\d{4}-\d{2}-\d{2})\)( \[already kept\])?$')
BASE = ["--convention", "section", "--cut-date", "2026-02-01", "--today", "2026-02-15"]

# U3: a rule-shaped heading inside a moving record.
H_TITLE = "Roof record about the hatch (2026-01-10)"
H_RULE = "Only the night crew opens the hatch on the roof deck"
H_CLAUDE = ("# Project\n\nPreamble for the roof project.\n\n"
            "## " + H_TITLE + "\n\n### " + H_RULE + "\n\n"
            "The hatch got new hinges and a fresh seal in the winter.\n\n"
            "## Later record about the roof schedule (2026-03-20)\n\n"
            "The roof schedule now runs on weekdays.\n")

# U6: one line with two rule sentences, the first kept outside.
F_X = "Never leave the forklift keys in the ignition overnight."
F_Y = "Always chain the forklift to the charging post."
F_TITLE = "Forklift record about the keys (2026-01-10)"
F_CLAUDE = ("# Project\n\nPreamble for the yard project.\n\n" + F_X + "\n\n"
            "## " + F_TITLE + "\n\n" + F_X + " " + F_Y + "\n\n"
            "## Later record about the yard schedule (2026-03-20)\n\n"
            "The yard schedule now runs on weekdays.\n")

# Kept unit (1b): the rule line and the long story line in two paragraphs.
V1B_CLAUDE = trr.V1_CLAUDE.replace(trr.V_RULE + "\n" + trr.V_LONG, trr.V_RULE + "\n\n" + trr.V_LONG)
# Kept unit (6): V4 with its short story line replaced by one over 40 characters.
V6_STORY = "The valve handle was wrapped in red tape that week."
V6_CLAUDE = trr.V4_CLAUDE.replace("Painted green.", V6_STORY)

# U12: fence state runs through the whole text, not per '## ' section.
CASE_C_RULE = "Never reveal the actual account token to callers."
CASE_C_TEXT = ("# P\n\n## Real section\n\n```\n## Sample\n```\n" + CASE_C_RULE + "\n\n"
           "## Next\n\nNext section text.\n")
CASE_C_TWIN = CASE_C_TEXT.replace("```\n## Sample\n```", "```\nsample line\n```")

# U11 (token edges): a moving rule whose token sits outside only inside a longer word.
E_RULE = "Never run `rm` on the shared data folder at all."
E_TITLE = "Data record about the shared folder (2026-01-10)"
E_CLAUDE = ("# Project\n\nAlways confirm with the owner before a deploy.\n\n"
            "## " + E_TITLE + "\n\n" + E_RULE + "\n\n"
            "## Later record about the yard schedule (2026-03-20)\n\n"
            "The yard schedule now runs on weekdays.\n")
E_GH = "Never run `gh` on the shared data folder at all."
E_GREP = "Never run `grep` on the shared data folder at all."
E_DIR = "Never write into `~/data/logs/` by hand at all."
E_C_TEXT = "# P\n\nAlways ask before you `rm` anything here.\n"
E_F_TEXT = "# P\n\nAlways rotate `~/data/logs/app.log` once a week.\n"

# C (clause (a) lists, never keeps): a moving rule whose token sits on an
# unrelated base-word line outside the moving records.
GF_RULE = "Never run `git` with --force on the shared data folder."
GF_TITLE = "Git record about the shared folder (2026-01-10)"
GF_LINE = "- Always use git through the wrapper script."
GF_CLAUDE = ("# Project\n\n## Standing\n\n" + GF_LINE + "\n\n## " + GF_TITLE + "\n\n" + GF_RULE + "\n\n"
             "## Later record about the yard schedule (2026-03-20)\n\n"
             "The yard schedule now runs on weekdays.\n")


def run(path, *extra, cwd=None):
    cmd = [sys.executable, ROTATE, path] + list(extra)
    p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, cwd=cwd)
    return p.returncode, p.stdout.decode("utf-8", "replace"), p.stderr.decode("utf-8", "replace")


def read(path):
    if not os.path.isfile(path):
        return ""
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)
    return path


def draft_lines(out):
    return [l for l in out.splitlines() if DRAFT_RE.match(l)]


def missing(out):
    return [l for l in out.splitlines() if l.startswith("MISSING RULE: ")]


def skipped(out):
    return [l for l in out.splitlines() if l.startswith("  KEPT-RULE FRAGMENT SKIPPED: ")]


def hoist(text, line):
    """Paste one draft line above the moving spans, in its own section."""
    head, rest = text.split("\n## ", 1)
    return head + "\n## Standing rules kept\n\n" + line + "\n\n## " + rest


def call(name, *args):
    """A splitlib function by name, or a string naming why it could not run:
    an absent function makes the check FAIL by name, never crash the file."""
    fn = getattr(splitlib, name, None)
    if fn is None:
        return "splitlib.%s is absent" % name
    try:
        return fn(*args)
    except Exception as e:                                      # noqa: BLE001
        return "raised %s: %s" % (type(e).__name__, e)


def rule_items(text):
    return [i.text for i in splitlib.atoms(text) if i.kind == "rule"]


def doc(body):
    return "# P\n\n## S\n\n" + body + "\n"


def raised_line(name, *args):
    """The line an UnclosedFence carries when splitlib.<name>(*args) raises it,
    or a string saying what happened instead (a check fails by name)."""
    fn = getattr(splitlib, name, None)
    if fn is None:
        return "splitlib.%s is absent" % name
    try:
        got = fn(*args)
    except Exception as e:                                      # noqa: BLE001
        if type(e).__name__ == "UnclosedFence" and isinstance(e, ValueError):
            return getattr(e, "line", "no line attribute")
        return "raised %s: %s" % (type(e).__name__, e)
    return "returned %r" % (got,)


# ---------------------------------------------------------------- A fixtures (synthetic)
FA_LR_REAL = ("Last split run: 2026-01-01, 10K to 9K chars, 1 records moved to "
              "`CLAUDE_DECISIONS_INDEX.md`, report x/REPORT.md")
FA_EXAMPLE = ("```\nLast split run: 2025-12-01, 9K to 8K chars, 2 records moved to "
              "`CLAUDE_DECISIONS_INDEX.md`, report y/REPORT.md\n```\n")
FA_OLD = "## Old work (2026-06-01)\n\n- Some old story about work done once.\n\n"
FA_NEW = "## New work (2026-09-01)\n\n- Recent notes.\n"
FA_LR = ("# Project\n\n## Maintenance rule\n\n" + FA_LR_REAL + "\n\n## How to read the line\n\n"
         "An example of the line the tool writes:\n\n" + FA_EXAMPLE + "\n" + FA_OLD + FA_NEW)
FA_LR_BEFORE = ("# Project\n\n## How to read the line\n\nAn example of the line the tool writes:\n\n"
                + FA_EXAMPLE + "\n## Maintenance rule\n\n" + FA_LR_REAL + "\n\n" + FA_OLD + FA_NEW)
FA_REC = ("# Project\n\n## Maintenance rule\n\n" + FA_LR_REAL + "\n\n## Old work (2026-06-01)\n\n"
          "- Some old story about work done once. The tool wrote this line:\n\n" + FA_EXAMPLE + "\n"
          + FA_NEW)
FA_MR_BLOCK = "```\n## Maintenance rule\nRun the split when the file grows.\n```\n"
FA_MR = ("# Project\n\n## Template\n\nA new project file starts like this:\n\n" + FA_MR_BLOCK + "\n"
         + FA_OLD + FA_NEW)
FA_C6_RULE = "Never deploy on a Friday without a rollback plan ready."
FA_C6 = ("# Project\n\n## Old work (2026-06-01)\n\n- An old story. The heading format we use:\n\n"
         "```\n## Example entry (2026-05-01)\n" + FA_C6_RULE + "\n```\n\n" + FA_NEW)
FA_SPLIT = ("# Project\n\nPreamble with no obligation word.\n\n## Rec A (2026-01-01)\n\n"
            "- Never leave the yard gate open overnight.\n\n```\n## Rec B (2026-01-02)\n"
            "Always keep the side gate shut in winter.\n```\n- Must lock the tool shed at night.\n")
FA_CUT = ["--convention", "section", "--cut-date", "2026-08-01", "--today", "2026-10-08"]


def section_of(text, heading):
    """The lines of one '## ' section of a report, its heading excluded."""
    out, on = [], False
    for ln in text.splitlines():
        if ln.startswith("## "):
            on = ln == heading
            continue
        if on:
            out.append(ln)
    return out


# ---------------------------------------------------------------- A: the derived reader set
READER_FILES = ("splitlib.py", "rotate.py", "loss_check.py", "pointers.py")
READER_STATE = ("fence_states", "fenced", "start_fenced")
PROSE = "reads fenced lines as prose (a stated exclusion)"
NOT_LINE = "not a line of a notes text"
EXCLUDED = [
    ("splitlib.py", "sections", PROSE),
    ("rotate.py", "parse_records", PROSE),
    ("splitlib.py", "_drop_last_run", PROSE),
    ("splitlib.py", "Text.__init__", PROSE),
    ("rotate.py", "add_runs_row", PROSE + ": the archive index rotate.py writes"),
    ("rotate.py", "index_final", PROSE + ": the archive index rotate.py writes"),
    ("splitlib.py", "open_items", PROSE + ": open-work files, not a CLAUDE.md"),
    ("splitlib.py", "token_kind", NOT_LINE),
    ("splitlib.py", "_places", NOT_LINE),
    ("splitlib.py", "file_token", NOT_LINE),
    ("splitlib.py", "pointers.lookup", NOT_LINE),
    ("splitlib.py", "pointers.hub", NOT_LINE),
    ("splitlib.py", "classify", NOT_LINE),
    ("splitlib.py", "record_keys", NOT_LINE),
    ("splitlib.py", "_edited_match", NOT_LINE),
    ("rotate.py", "undo_matches", NOT_LINE),
    ("splitlib.py", "_walk_blind", PROSE + ": the fence-blind rule units, rule unit (v)"),
]


def derived_readers(sources, excluded=None):
    """The readers are derived: every call whose callee is an
    attribute named startswith or match, keyed by file and innermost enclosing
    function (qualified name). A function is a fence reader when its own body
    (nested def and class bodies excluded) loads fence_states (bare or as an
    attribute), fenced or start_fenced. Returns (count line, problem lines,
    fence reader names). sources: {file name: source text}."""
    import ast
    excluded = EXCLUDED if excluded is None else excluded
    funcs, calls = {}, 0      # (file, qual) -> [first call line, reads fence]

    def own_loads(fn):
        stack, found = list(fn.body), False
        while stack:
            n = stack.pop()
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                continue
            if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load) and n.id in READER_STATE:
                found = True
            if isinstance(n, ast.Attribute) and n.attr == "fence_states" and isinstance(n.ctx, ast.Load):
                found = True
            stack.extend(ast.iter_child_nodes(n))
        return found

    for fname in READER_FILES:
        tree = ast.parse(sources[fname])

        def visit(node, stack):
            nonlocal calls
            for ch in ast.iter_child_nodes(node):
                if isinstance(ch, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                    visit(ch, stack + [ch])
                else:
                    visit(ch, stack)
            if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                    and node.func.attr in ("startswith", "match")):
                calls += 1
                fns = [s for s in stack if not isinstance(s, ast.ClassDef)]
                qual = ".".join(s.name for s in stack) or "<module>"
                key = (fname, qual)
                if key not in funcs:
                    funcs[key] = [node.lineno, bool(fns) and own_loads(fns[-1])]
                funcs[key][0] = min(funcs[key][0], node.lineno)
        visit(tree, [])
    rows = set((f, q) for f, q, _ in excluded)
    problems, fence = [], []
    for (f, q), (line, reads) in sorted(funcs.items()):
        if reads and (f, q) in rows:
            # a stated exclusion that loads fence state is no exclusion
            problems.append("EXCLUDED READS FENCE %s %s" % (f, q))
        if reads:
            fence.append(q)
        elif (f, q) not in rows:
            problems.append("UNLISTED READER %s:%d %s" % (f, line, q))
    for f, q, why in excluded:
        if (f, q) not in funcs:
            problems.append("STALE EXCLUDED %s %s (%s)" % (f, q, why))
    n_ex = sum(1 for k in funcs if k in rows and not funcs[k][1])
    return ("READERS %d calls, %d fence, %d excluded" % (calls, len(fence), n_ex)), problems, fence


def reader_sources():
    out = {}
    for f in READER_FILES:
        with open(os.path.join(HERE, f), encoding="utf-8") as fh:
            out[f] = fh.read()
    return out


def fence_checks(check, mk, sandbox):
    """Fence checks (fenced blocks, derived readers, a slice never raises):
    the rotate.py readers end to end, the slice start state and
    the derived reader set."""
    def no_split(d):
        return not [n for n in os.listdir(d) if n.startswith("split_")]

    # S2: a fenced Last-run example in a section that stays
    d, p, r = sandbox(FA_LR)
    rc, out, err = run(p, *(FA_CUT + r + ["--apply"]))
    after = read(p)
    real = [l for l in after.splitlines()
            if l.startswith(splitlib.LAST_RUN_PREFIX) and l not in FA_EXAMPLE.splitlines()]
    check("A S2 a fenced 'Last split run:' example in a kept section: --apply exits 0, no INTERNAL line, "
          "the example kept byte for byte, exactly one unfenced Last-run line, at today's date",
          rc == 0 and not [l for l in out.splitlines() if l.startswith("INTERNAL: ")]
          and after.count(FA_EXAMPLE) == 1 and len(real) == 1
          and real[0].startswith(splitlib.LAST_RUN_PREFIX + " 2026-10-08,"),
          "rc=%d %r %r" % (rc, real, (out + err)[-400:]))
    d, p, r = sandbox(FA_LR_BEFORE)
    rc, out, err = run(p, *(FA_CUT + r + ["--apply"]))
    after = read(p)
    check("A S2 before-slot twin: a fenced 'Last split run:' line before the real one is not the slot: "
          "exit 0, the example byte for byte, the real line now at today's date, its old date gone",
          rc == 0 and after.count(FA_EXAMPLE) == 1 and FA_LR_REAL not in after
          and any(l.startswith(splitlib.LAST_RUN_PREFIX + " 2026-10-08,") for l in after.splitlines()),
          "rc=%d %r" % (rc, (out + err)[-400:]))
    # S2 twin inside a moving record (step 1's stray removal)
    d, p, r = sandbox(FA_REC)
    rc, out, err = run(p, *(FA_CUT + r + ["--apply"]))
    arch = read(os.path.join(d, "CLAUDE_DECISIONS_2026-06.md"))
    check("A S2 in-record twin: a fenced 'Last split run:' example inside the moving record: --apply "
          "exits 0, no NOWHERE line, the example in the archive byte for byte",
          rc == 0 and not [l for l in out.splitlines() if l.startswith("NOWHERE: ")]
          and arch.count(FA_EXAMPLE) == 1, "rc=%d %r" % (rc, (out + err)[-400:]))
    # a fenced '## Maintenance rule' is not the slot (placement falls through)
    d, p, r = sandbox(FA_MR)
    rc, out, err = run(p, *(FA_CUT + r + ["--apply"]))
    after = read(p)
    check("A fenced '## Maintenance rule' template: the real Last-run line is not written inside the "
          "fence (the fenced example is byte for byte as before), exit 0",
          rc == 0 and after.count(FA_MR_BLOCK) == 1, "rc=%d %r" % (rc, after[:400]))

    # change 6: the rules draft and the in-memory loss check read a record alike
    d, p, r = sandbox(FA_C6)
    rc, out, err = run(p, *(["--convention", "section", "--cut-date", "2026-07-01",
                             "--today", "2026-10-08"] + r))
    rep = read(os.path.join(d, "split_2026-10-08", "REPORT.dry.md"))
    draft, loss = section_of(rep, "## Rules draft"), section_of(rep, "## Loss check")
    held = [i for i, l in enumerate(loss) if FA_C6_RULE in l]
    c6_counts = [l for l in out.splitlines() if l.startswith("RULES DRAFT: ")]
    c6_lazy = "LAZY-ONLY: " + FA_C6_RULE
    c6_at = loss.index(c6_lazy) if c6_lazy in loss else -1
    check("A change 6: a fence opened in one dated record holds a dated '## ' example; the rules draft and the "
          "in-memory loss check read the record alike, now both listing and blocking the fenced rule: "
          "dry run exit 0, no Traceback, no CANNOT TELL, no MISSING RULE line on stdout, the counts "
          "line '1 rule sentence(s) ... 1 refused on --apply'; REPORT.dry.md's Rules draft holds the draft "
          "line and its MISSING RULE line, its Loss check the LAZY-ONLY rule item with its rule detail line, "
          "the POINTED (archive) command item, and '1 blocking item(s) not waived'",
          rc == 0 and "Traceback" not in err
          and not [l for l in out.splitlines() if l.startswith("CANNOT TELL: ")] and not missing(out)
          and c6_counts == ["RULES DRAFT: 1 rule sentence(s) in the moving records; 0 already kept, "
                            "0 kept in --hoisted, 0 let through by --narrative, 1 refused on --apply"]
          and ('- %s (kept from "Example entry (2026-05-01)", 2026-05-01)' % FA_C6_RULE) in draft
          and ("MISSING RULE: " + FA_C6_RULE) in draft
          and c6_at >= 0 and c6_at + 1 < len(loss)
          and loss[c6_at + 1] == ("    rule in section ## Example entry (2026-05-01); held in "
                                  "CLAUDE_DECISIONS_2026-05.md blocks; --accept \"<fragment of it>\" lets it "
                                  "through")
          and ("POINTED (archive: CLAUDE_DECISIONS_2026-05.md): " + FA_C6_RULE) in loss
          and [l for l in loss if l.strip()][-1:] == ["1 blocking item(s) not waived"],
          "rc=%d counts=%r draft=%r loss=%r err=%r" % (rc, c6_counts, draft, loss, err[-300:]))
    # after the move, record 1's opener is left with no closer (cannot tell)
    for mode in ([], ["--apply"]):
        d, p, r = sandbox(FA_C6)
        rc, out, err = run(p, *(["--convention", "section", "--cut-date", "2026-05-15",
                                 "--today", "2026-10-08"] + r + mode))
        want = "CANNOT TELL: fence opened at line 7 never closes (%s after the move)" % p
        check("A after-the-move unclosed twin %s: exit 2, the exact CANNOT TELL line, no Traceback, no "
              "run folder, CLAUDE.md unchanged" % (mode[0] if mode else "dry run"),
              rc == 2 and [l for l in out.splitlines() if l == want] == [want]
              and "Traceback" not in out + err and no_split(d) and read(p) == FA_C6,
              "rc=%d %r %r" % (rc, out[-400:], err[-300:]))
    # rotate.py on a CLAUDE.md whose fence never closes
    for mode in ([], ["--apply"]):
        bad = FA_LR.replace(FA_EXAMPLE, "```\nopened and never closed\n")
        d, p, r = sandbox(bad)
        rc, out, err = run(p, *(FA_CUT + r + mode))
        want = "CANNOT TELL: fence opened at line 11 never closes (%s)" % p
        check("A rotate.py %s on a CLAUDE.md whose fence never closes: exit 2, the CANNOT TELL line, "
              "no run folder, CLAUDE.md unchanged" % (mode[0] if mode else "dry run"),
              rc == 2 and [l for l in out.splitlines() if l.startswith("CANNOT TELL: fence")] == [want]
              and "Traceback" not in err and no_split(d) and read(p) == bad,
              "rc=%d %r %r" % (rc, out[-400:], err[-300:]))

    # a slice never raises; its start state comes from the whole text
    lines = FA_SPLIT.splitlines(keepends=True)
    recs = rotate.parse_records(lines, "section")
    try:
        fenced, _open = splitlib.fence_states(lines)
        starts = [splitlib.fence_start(lines, fenced, s) for s, _, _, _ in recs]
        drafts = rotate.rules_draft([(t, dt, "".join(lines[s:e])) for s, e, dt, t in recs], "",
                                    start_fenced=starts)
        got = [u.text for dr in drafts for u in dr.units]
    except Exception as e:                                      # noqa: BLE001
        got = "raised %s: %s" % (type(e).__name__, e)
    whole = call("rule_units", FA_SPLIT)
    first = next((x for x in zip(got, whole) if x[0] != x[1]), None) if isinstance(got, list) else None
    check("A split-cut twin: a record whose slice ends inside a fence the next record closes gives "
          "exactly the units the whole-text walk gives",
          isinstance(got, list) and got == whole
          and whole == ["Never leave the yard gate open overnight.", "Always keep the side gate shut in winter.",
                        "Must lock the tool shed at night."],
          "got=%r whole=%r first difference=%r" % (got, whole, first))
    try:
        dr3 = rotate.rules_draft([("## T (2026-01-01)", "2026-01-01",
                                   "## T (2026-01-01)\n\n- Never leave the gate open at night.\n")], "")
        got = [u.text for u in dr3[0].units]
    except Exception as e:                                      # noqa: BLE001
        got = "raised %s: %s" % (type(e).__name__, e)
    check("A 3-tuple twin: rules_draft([(title, date, text)], outside) still returns Drafts with "
          ".units, read from outside a fence", got == ["Never leave the gate open at night."], got)

    # the derived reader set, and its planted-reader control
    line, problems, fence = derived_readers(reader_sources())
    print(line)
    check("A derived readers: every startswith/match reader in the four files reads fence state or is "
          "a stated exclusion (17 rows), and no exclusion is stale; %s; fence readers %s" % (line, fence),
          not problems and len(EXCLUDED) == 17 and len(fence) >= 1, problems)
    # G24: an exclusion that loads fence state prints its own problem line
    planted = reader_sources()
    anchor = "def _walk_blind(body):\n"
    if planted["splitlib.py"].count(anchor) == 1:
        planted["splitlib.py"] = planted["splitlib.py"].replace(
            anchor, anchor + "    fenced = None\n    if fenced:\n        return\n", 1)
        _l, pp, _f = derived_readers(planted)
        pp = [x for x in pp if x not in problems]
    else:
        pp = ["no single 'def _walk_blind(body):' line in splitlib.py"]
    check("G24 derived readers: the real sources print no 'EXCLUDED READS FENCE' line, and a copy whose "
          "_walk_blind loads 'fenced' prints exactly 'EXCLUDED READS FENCE splitlib.py _walk_blind'",
          not [x for x in problems if x.startswith("EXCLUDED READS FENCE ")]
          and pp == ["EXCLUDED READS FENCE splitlib.py _walk_blind"], (problems, pp))
    # G5: the closer rule decides listing only; pinned on fence_states' flags
    FO, FC = splitlib.FENCE_OPEN, splitlib.FENCE_CLOSE
    w1 = ("# Notes\n\n## Setup\n\n```bash\nmake install\n``` end of setup\n\n## Deploy\n\n"
          "- Never deploy on a Friday without a rollback plan ready.\n\n## Test\n\n```bash\nmake test\n```\n")
    got = splitlib.fence_states(w1.splitlines())
    want = ([False] * 4 + [FO] + [True] * 11 + [FC], None)
    check("G5 a closer with text after the backticks is content: shape (b)'s flags are False x4, open, "
          "True x11 (the '``` end of setup' line True), close", got == (want[0], None), got)
    w1t = w1.replace("``` end of setup", "```")
    got = splitlib.fence_states(w1t.splitlines())
    want = [False] * 4 + [FO, True, FC] + [False] * 7 + [FO, True, FC]
    check("G5 twin: the same text with a bare closer gives FENCE_CLOSE on that line", got == (want, None), got)
    planted = reader_sources()
    planted["rotate.py"] += ("\n\ndef planted_reader(lines):\n"
                             "    return [ln for ln in lines if ln.startswith(\"## \")]\n")
    _l, pp, _f = derived_readers(planted)
    pp = [x for x in pp if x not in problems]
    check("A derived readers planted control: a new function with one startswith loop prints exactly "
          "one UNLISTED READER line more than the unedited files, naming it",
          len(pp) == 1 and pp[0].startswith("UNLISTED READER rotate.py:") and pp[0].endswith(" planted_reader"),
          pp)


CHECKS = []


def main():
    checks = CHECKS

    def check(name, ok, detail=""):
        if not isinstance(detail, str):
            detail = repr(detail)
        checks.append((name, bool(ok), detail))

    tmpdirs = []

    def mk():
        d = os.path.realpath(tempfile.mkdtemp(prefix="rule-units-"))
        tmpdirs.append(d)
        return d

    def sandbox(body):
        d = mk()
        root = mk()
        p = write(os.path.join(d, "CLAUDE.md"), body)
        return d, p, ["--root", root]

    # ---------------------------------------------------------------- CONTROL
    got = rule_items(test_rotate.SECTION)
    check("CONTROL splitlib.atoms(test_rotate.SECTION) yields exactly 2 rule items",
          len(got) == 2, got)

    # U11, placed first: a later check that crashes cannot hide it
    prepared = call("clause_a_kept", E_RULE, splitlib.Text(E_C_TEXT))
    check("U11 clause_a_kept given a prepared Text answers as given the str (twin (c), kept)",
          prepared is True and call("clause_a_kept", E_RULE, E_C_TEXT) is True, prepared)

    # ---------------------------------------------------------------- U1
    u1 = doc("- Never open the vent valve\n  while the tank is still warm.")
    j1 = "Never open the vent valve while the tank is still warm."
    got = call("rule_units", u1)
    check("U1 a multi-line bullet is one rule unit, its lines joined, marker removed",
          got == [j1], got)
    got = rule_items(u1)
    check("U1 the multi-line bullet is one rule sentence, joined", got == [j1], got)

    # ---------------------------------------------------------------- U2
    got = rule_items(doc("Staff do\nnot carry the store keys home at night."))
    check("U2 a rule word spanning a line break makes one rule sentence",
          got == ["Staff do not carry the store keys home at night."], got)

    # ---------------------------------------------------------------- U3
    rec = H_CLAUDE.split("## Later")[0].split("\n\n", 2)[2]
    items = [(i.kind, i.text) for i in splitlib.atoms(rec)]
    check("U3 a rule-shaped heading is a heading item AND a rule sentence without its #s",
          ("heading", "### " + H_RULE) in items and ("rule", H_RULE) in items, items)
    d, p, r = sandbox(H_CLAUDE)
    rc, out, err = run(p, *(BASE + r))
    want = '- %s (kept from "%s", 2026-01-10)' % (H_RULE, H_TITLE)
    dl = draft_lines(out)
    check("U3 the dry run prints the heading as a draft line", rc == 0 and dl == [want],
          "rc=%d %r" % (rc, dl))
    d, p, r = sandbox(H_CLAUDE)
    rc, out, err = run(p, *(BASE + r + ["--apply"]))
    check("U3 --apply without a waiver exits 3 with its MISSING RULE line",
          rc == 3 and missing(out) == ["MISSING RULE: " + H_RULE], "rc=%d %r" % (rc, missing(out)))
    d, p, r = sandbox(H_CLAUDE)
    rc, out, err = run(p, *(BASE + r + ["--apply", "--narrative", H_TITLE]))
    check("U3 --narrative lets the heading's rule sentence through: exit 0",
          rc == 0 and missing(out) == [], "rc=%d %r" % (rc, (out + err)[-300:]))
    d, p, r = sandbox(H_CLAUDE)
    write(p, hoist(read(p), want))
    rc, out, err = run(p, *(BASE + r + ["--apply"]))
    check("U3 after pasting its draft line, --apply exits 0 on 1 record / 2 fragments",
          rc == 0 and "moved records: 1 records / 2 fragments" in out,
          "rc=%d %r" % (rc, (out + err)[-500:]))

    # ---------------------------------------------------------------- U4
    got = rule_items(doc("Only the duty manager signs the cash sheet."))
    check("U4 a sentence whose only rule word is 'only' is a rule sentence",
          got == ["Only the duty manager signs the cash sheet."], got)
    got = rule_items(doc("The shop opens daily at nine."))
    check("U4 twin: a sentence with no rule word is no rule sentence", got == [], got)

    # ---------------------------------------------------------------- U5
    u5 = doc("Never prop the fire door open with a wedge.\n"
             "The wedge was found under the stairs last week.")
    got = call("rule_units", u5)
    check("U5 a rule paragraph is one draft unit holding its story sentence",
          isinstance(got, list) and len(got) == 1
          and splitlib.rule_kept("wedge was found under the", got[0]), got)
    got = rule_items(u5)
    check("U5 the same paragraph is one rule sentence",
          got == ["Never prop the fire door open with a wedge."], got)

    # ---------------------------------------------------------------- U6
    d, p, r = sandbox(F_CLAUDE)
    rc, out, err = run(p, *(BASE + r))
    dl = draft_lines(out)
    check("U6 a unit with one rule sentence kept outside and one not is not [already kept]",
          rc == 0 and dl == ['- %s %s (kept from "%s", 2026-01-10)' % (F_X, F_Y, F_TITLE)],
          "rc=%d %r" % (rc, dl))
    d, p, r = sandbox(F_CLAUDE)
    rc, out, err = run(p, *(BASE + r + ["--apply"]))
    check("U6 --apply names only the rule sentence that is not kept",
          rc == 3 and missing(out) == ["MISSING RULE: " + F_Y], "rc=%d %r" % (rc, missing(out)))

    # ---------------------------------------------------------------- U7
    got = call("rule_units", doc("| Never run the mixer dry | daily |\n"
                                 "| Always rinse the drum | weekly |"))
    check("U7 two table rows are two units",
          got == ["| Never run the mixer dry | daily |", "| Always rinse the drum | weekly |"], got)

    # ---------------------------------------------------------------- U8
    u8 = doc("```\necho never do this\n```")
    got = call("rule_units", u8)
    check("U8 a rule-shaped line inside a fenced block is a unit of its own (rule unit (iv))",
          got == ["echo never do this"], got)
    got = rule_items(u8)
    check("U8 a rule-shaped line inside a fenced block is a rule sentence of its own (rule unit "
          "(iv))", got == ["echo never do this"], got)

    # ---------------------------------------------------------------- U9
    got = call("rule_units", doc("- Never stack crates above the red line\n"
                                 "  - Always strap the top crate to the rack"))
    check("U9 a nested marker line starts its own unit",
          got == ["Never stack crates above the red line", "Always strap the top crate to the rack"],
          got)

    # ---------------------------------------------------------------- kept unit (1b)
    d, p, r = sandbox(V1B_CLAUDE)
    rc, out, err = run(p, *(BASE + r))
    dl = draft_lines(out)
    write(p, hoist(read(p), dl[0] if dl else "- (no draft line)"))
    rc, out, err = run(p, *(BASE + r + ["--apply"]))
    check("kept unit (1b) rule line, blank line, long line: after the paste, exit 0 on "
          "1 records / 2 fragments with one SKIPPED line",
          rc == 0 and "moved records: 1 records / 2 fragments" in out and len(skipped(out)) == 1,
          "rc=%d %r %r" % (rc, skipped(out), (out + err)[-400:]))

    # ---------------------------------------------------------------- kept unit (6)
    d, p, r = sandbox(V6_CLAUDE)
    rc, out, err = run(p, *(BASE + r + ["--apply"]))
    check("kept unit (6) a long story line in a kept unit but not in CLAUDE.md stays checked: "
          "exit 0 on 1 records / 2 fragments with one SKIPPED line",
          rc == 0 and "moved records: 1 records / 2 fragments" in out and len(skipped(out)) == 1,
          "rc=%d %r %r" % (rc, skipped(out), (out + err)[-400:]))

    # ---------------------------------------------------------------- U10
    rule = "Never run `foo.py` against production."
    check("U10 a backticked token held outside only on a line whose rule word is 'only' "
          "does not keep the rule",
          splitlib.rule_kept(rule, "# P\n\nRun `foo.py` only on Mondays.\n") is False)
    check("U10 twin: rule_kept, the listing judge, still sees the same token on a base-word line "
          "through clause (a)",
          splitlib.rule_kept(rule, "# P\n\nNever deploy `foo.py` on Fridays.\n") is True)
    got = call("unit_kept", rule, "# P\n\nNever deploy `foo.py` on Fridays.\n")
    check("C U10 twin: unit_kept, the verdict judge, does not keep it (clause (a) lists, never keeps)",
          got is False, got)

    # ---------------------------------------------------------------- U11 (token edges)
    d, p, r = sandbox(E_CLAUDE)
    rc, out, err = run(p, *(BASE + r + ["--apply"]))
    want = '- %s (kept from "%s", 2026-01-10)' % (E_RULE, E_TITLE)
    check("U11 a token held outside only inside an unrelated word ('rm' in 'confirm') does not "
          "keep the rule: --apply exits 3 with its MISSING RULE line, the draft line not "
          "[already kept], CLAUDE.md unchanged",
          rc == 3 and missing(out) == ["MISSING RULE: " + E_RULE] and draft_lines(out) == [want]
          and read(p) == E_CLAUDE,
          "rc=%d %r %r" % (rc, missing(out), draft_lines(out)))
    gh_text = "# P\n\nAlways go through the owner before a deploy.\n"
    check("U11 (b) 'gh' held only inside 'through' is not kept by clause (a)",
          call("clause_a_kept", E_GH, gh_text) is False, call("clause_a_kept", E_GH, gh_text))
    check("U11 (c) the token in backticks on a base-word line is kept by clause (a)",
          call("clause_a_kept", E_RULE, E_C_TEXT) is True, call("clause_a_kept", E_RULE, E_C_TEXT))
    d_text = "# P\n\nAlways ask before you rm anything here.\n"
    check("U11 (d) the same token as a bare word on a base-word line is kept by clause (a)",
          call("clause_a_kept", E_RULE, d_text) is True, call("clause_a_kept", E_RULE, d_text))
    e_text = "# P\n\nAlways use BSD-grep on this Mac.\n"
    check("U11 (e) 'grep' held only as 'BSD-grep' is not kept by clause (a)",
          call("clause_a_kept", E_GREP, e_text) is False, call("clause_a_kept", E_GREP, e_text))
    check("U11 (f) a folder token ending in '/' held only as the start of a longer path is not "
          "kept by clause (a)",
          call("clause_a_kept", E_DIR, E_F_TEXT) is False, call("clause_a_kept", E_DIR, E_F_TEXT))

    # ---------------------------------------------------------------- C (W-F option 3)
    d, p, r = sandbox(GF_CLAUDE)
    rc, out, err = run(p, *(BASE + r + ["--apply"]))
    want = '- %s (kept from "%s", 2026-01-10)' % (GF_RULE, GF_TITLE)
    check("C a moved rule whose token sits outside only on an unrelated base-word line is not kept: "
          "--apply exits 3 with exactly one MISSING RULE line naming it, its draft line without "
          "[already kept], CLAUDE.md unchanged",
          rc == 3 and missing(out) == ["MISSING RULE: " + GF_RULE] and draft_lines(out) == [want]
          and read(p) == GF_CLAUDE, "rc=%d %r %r %r" % (rc, missing(out), draft_lines(out),
                                                       [l for l in out.splitlines() if l.startswith("RULES DRAFT")]))
    for tag, line in (("(c)", "Always ask before you `rm` anything here."),
                      ("(d)", "Always ask before you rm anything here.")):
        text = E_CLAUDE.replace("Always confirm with the owner before a deploy.", line)
        d, p, r = sandbox(text)
        rc, out, err = run(p, *(BASE + r + ["--apply"]))
        check("C U11 %s end to end: the rule's only outside base-word line is the %s text, so --apply "
              "exits 3 with its MISSING RULE line" % (tag, tag),
              rc == 3 and missing(out) == ["MISSING RULE: " + E_RULE], "rc=%d %r" % (rc, missing(out)))
    A = mk()
    proj = os.path.join(A, "proj")
    p = write(os.path.join(proj, "CLAUDE.md"), GF_CLAUDE.replace("## Standing\n\n" + GF_LINE + "\n\n", ""))
    h = write(os.path.join(A, "CLAUDE.md"), "# Global rules\n\n" + GF_LINE + "\n")
    rc, out, err = run(p, *(BASE + ["--root", mk(), "--apply", "--hoisted", h]), cwd=proj)
    rd = [l for l in out.splitlines() if l.startswith("RULES DRAFT: ")]
    check("C hoisted twin: the token held only on a base-word line of an accepted --hoisted file: "
          "--apply exits 3 with exactly one 'MISSING RULE: Never run' line, and the RULES DRAFT line "
          "reads '0 kept in --hoisted'",
          rc == 3 and [l for l in out.splitlines() if l.startswith("MISSING RULE: Never run")] ==
          ["MISSING RULE: " + GF_RULE] and len(rd) == 1 and "0 kept in --hoisted" in rd[0],
          "rc=%d %r %r" % (rc, missing(out), rd))

    # ---------------------------------------------------------------- U13 (one edge test)
    edge_re = lambda tok, text: re.search(r"(?<![\w./-])" + re.escape(tok) + r"(?![\w/-]|\.\w)",
                                          text) is not None
    toks = ["rm", "ta47", "~/data/logs/", "a.b", "x-y", "_u", "é"]
    texts = ["", "rm", " rm ", "confirm", "rm.", "rm.x", "rm.\n", ".rm", "/rm", "-rm", "rm-", "rm/",
             "rm_", "_rm", "(rm)", "`rm`", "rmrm rm", "xrm rm", "ta4731 ta47", "ta47.5 ta47,",
             "~/data/logs/app.log", "x ~/data/logs/", "a.bc a.b", "a.b.", "x-y-z x-y!", "__u _u",
             "éé é", "café é.", "rm\nrm", "line\nrm\nend", "rm" * 3 + " " + "rm"]
    bad = [(t, x) for t in toks for x in texts if bool(splitlib.on_edges(t, x)) != edge_re(t, x)]
    check("U13 on_edges answers exactly as the token-edge pattern on %d token/text pairs"
          % (len(toks) * len(texts)), not bad, bad[:5])

    # ---------------------------------------------------------------- U12
    got = [(i.kind, i.section) for i in splitlib.atoms(CASE_C_TEXT) if i.text == CASE_C_RULE]
    check("U12 a rule after a fenced '## ' line is a rule item, owned by the section that line starts",
          got == [("rule", ("## Sample", 1))], got)
    got = call("rule_units", CASE_C_TEXT)
    check("U12 rule_units returns the rule after a fenced '## ' line, as the twin with no fenced '## ' does",
          got == [CASE_C_RULE] and call("rule_units", CASE_C_TWIN) == [CASE_C_RULE], got)
    got = [(i.kind, i.text) for i in splitlib.atoms(CASE_C_TEXT) if i.kind == "command"]
    check("U12 the fenced '## ' line itself is a command item, not a heading",
          got == [("command", "## Sample")]
          and "## Sample" not in [i.text for i in splitlib.atoms(CASE_C_TEXT) if i.kind == "heading"], got)
    ptxt = ("# P\n\n## Real\n\n```\n## Sample\n[[inside-fence]]\n```\nSee [[after-fence]] here.\n\n"
            "## Next\n\nNothing.\n")
    got = [x.token for x in splitlib.pointers(ptxt, mk(), [], None)]
    check("U12 pointers: a [[name]] after a fenced '## ' example is found, one inside the fence is not",
          got == ["after-fence"], got)
    unclosed = ("# P\n\n## A\n\n```\nopened and never closed\n\n## B\n\n" + CASE_C_RULE + "\n")
    got = (raised_line("atoms", unclosed), raised_line("rule_units", unclosed))
    check("U12 an unclosed fence is cannot tell: atoms and rule_units on the whole text "
          "raise splitlib.UnclosedFence carrying the opener's line (5)", got == (5, 5), got)

    # ------------------------------------------------ A: one fence reader
    fence_checks(check, mk, sandbox)

    for d in tmpdirs:
        shutil.rmtree(d, ignore_errors=True)

    return report(checks)


def report(checks):
    if not checks:
        print("0/0 passed -- the harness ran NO checks, which is a harness bug")
        return 1
    failed = [c for c in checks if not c[1]]
    for name, ok, detail in checks:
        if not ok:
            print("  FAILED " + name)
            print("         " + re.sub(r"(\d+)/(\d+) passed", r"\1 of \2 passed",
                                       detail.replace("\n", "\n         "))[:400])
    print("%d/%d passed" % (len(checks) - len(failed), len(checks)))
    return 1 if failed else 0


if __name__ == "__main__":
    # A check must FAIL, never crash the file: an exception that ends main()
    # early is one failed check, and every check that ran is still reported.
    try:
        RC = main()
    except Exception as e:                                      # noqa: BLE001
        CHECKS.append(("the file ran to its end without an exception", False,
                       "stopped at %s: %s" % (type(e).__name__, e)))
        RC = report(CHECKS)
    sys.exit(RC)
