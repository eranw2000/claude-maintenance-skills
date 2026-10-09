#!/usr/bin/env python3
"""Tests for the rules-draft parts of rotate.py.

The rules draft and its refusal: every rule sentence of a moving record
is printed as a draft line, and an --apply that would take one out of
CLAUDE.md is refused with a 'MISSING RULE: ' line unless it is kept outside
the moving records, kept in an accepted --hoisted file, or its record is
named by --narrative. --hoisted goes through splitlib's --hoisted check. The
fragment check skips a body line the rules draft found kept in CLAUDE.md.

Every fixture is a synthetic string built here and written to a mkdtemp
folder. Every hoist is a draft line copied from the dry run's own stdout,
never typed by hand. Row 0 is a CONTROL with a known answer: if it fails, the
harness is broken rather than the script.

Run:  python3 test_rotate_rules.py
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
import test_rotate  # noqa: E402

COLLIDING = test_rotate.COLLIDING
DRAFT_RE = re.compile(r'^- (.*) \(kept from "(.*)", (\d{4}-\d{2}-\d{2})\)( \[already kept\])?$')

# refusal / once-per-check: one moving record with two rule sentences.
P_TITLE = "Pump rule record about the intake (2026-01-10)"
P_R1 = "Never start the pump without priming the intake line and reading the gauge."
P_R2 = "Always log the pump hours in the paper ledger before the shift ends."
P_CLAUDE = ("# Project\n\nPreamble for the pump project.\n\n"
            "## " + P_TITLE + "\n\n" + P_R1 + "\n" + P_R2 + "\n"
            "The pump room got a new floor drain that spring.\n\n"
            "## Later record about the pump schedule (2026-03-20)\n\n"
            "The schedule now runs the pump twice a day.\n")

# Two moving records with one rule each: --narrative names only the first.
N_A_TITLE = "Crane rule record about the hook (2026-01-08)"
N_B_TITLE = "Hoist rule record about the chain (2026-01-09)"
N_A_RULE = "Never lift the crane hook over the loading bay while people stand below."
N_B_RULE = "Always grease the hoist chain before the first lift of the morning."
N_CLAUDE = ("# Project\n\nPreamble for the crane project.\n\n"
            "## " + N_A_TITLE + "\n\n" + N_A_RULE + "\n\n"
            "## " + N_B_TITLE + "\n\n" + N_B_RULE + "\n\n"
            "## Later record about the crane schedule (2026-03-20)\n\n"
            "The crane schedule now runs on weekdays only.\n")

# in-file hoist (1): the first body line over 40 chars is one rule sentence, then a long
# non-rule line. In-file hoist (2): the rule line is the only long body line.
V_TITLE = "Valve rule record about the bypass (2026-01-10)"
V_RULE = "Never open the bypass valve while the main line still holds pressure from the pump."
V_LONG = "The bypass valve was repainted green during the spring maintenance week."
V_TAIL = ("## Later record about the valve schedule (2026-03-20)\n\n"
          "The schedule now checks every valve once a week on Monday.\n")
V1_CLAUDE = ("# Project\n\nPreamble for the valve project.\n\n"
             "## " + V_TITLE + "\n\n" + V_RULE + "\n" + V_LONG + "\n\n" + V_TAIL)
V2_CLAUDE = ("# Project\n\nPreamble for the valve project.\n\n"
             "## " + V_TITLE + "\n\n" + V_RULE + "\nPainted green.\n\n" + V_TAIL)
# in-file hoist (4): the moving record's rule line already opens a KEPT record.
V4_CLAUDE = ("# Project\n\nPreamble for the valve project.\n\n"
             "## " + V_TITLE + "\n\n" + V_RULE + "\nPainted green.\n\n"
             "## Valve rule restated for the new pump (2026-03-20)\n\n" + V_RULE + "\n"
             "The new pump arrived in March with its own pressure gauge.\n")

# rule-free, so only the --hoisted refusal can stop the apply.
RF_CLAUDE = ("# Project\n\nPreamble for the folder tests.\n\n"
             "## Folder alpha record about the crates (2026-01-05)\n\n"
             "The crates moved to the north shelf during the stock count.\n\n"
             "## Folder gamma record about the scanner (2026-04-01)\n\n"
             "The scanner reads the larger labels without retries now.\n")

BASE = ["--convention", "section", "--cut-date", "2026-02-01", "--today", "2026-02-15"]


def run(path, *extra, cwd=None, env=None):
    cmd = [sys.executable, ROTATE, path] + list(extra)
    p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, cwd=cwd, env=env)
    return p.returncode, p.stdout.decode("utf-8", "replace"), p.stderr.decode("utf-8", "replace")


def read(path):
    if not os.path.isfile(path):
        return ""
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def readb(path):
    if not os.path.isfile(path):
        return None
    with open(path, "rb") as fh:
        return fh.read()


def write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)
    return path


def ls(d):
    return sorted(os.listdir(d)) if os.path.isdir(d) else []


def split_dirs(d):
    return sorted(n for n in ls(d) if n.startswith("split_") and os.path.isdir(os.path.join(d, n)))


def snapshot(d):
    out = {}
    for root, _dirs, files in os.walk(d):
        for f in files:
            p = os.path.join(root, f)
            out[os.path.relpath(p, d)] = readb(p)
    return out


REPORT_SECTIONS = ["Summary", "Move", "Keep", "Open-work evidence", "Rules draft", "Loss check",
                   "Pointers", "Waivers", "Backups", "Files sent"]


def section(text, name):
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


def draft_lines(out):
    return [l for l in out.splitlines() if DRAFT_RE.match(l)]


def missing(out):
    return [l for l in out.splitlines() if l.startswith("MISSING RULE: ")]


def skipped(out):
    return [l for l in out.splitlines() if l.startswith("  KEPT-RULE FRAGMENT SKIPPED: ")]


def note(out):
    return [l for l in out.splitlines() if l.strip().startswith("NOTE:")]


def hoist(text, line):
    """Paste one draft line above the moving spans, in its own section."""
    head, rest = text.split("\n## ", 1)
    return head + "\n## Standing rules kept\n\n" + line + "\n\n## " + rest


def draft_fn():
    return getattr(rotate, "rules_draft", None)


# ---------------------------------------------------------------- G: the always-block rule
# "A fence reading never decides whether a rule blocks" and "Fence-blind rule units are always
# present; fence state may only add". Fixtures are synthetic text.
G_RULE = "Never deploy on a Friday without a rollback plan ready."
G_REC = "## Deploy notes (2026-01-05)"
G_FROM = ' (kept from "Deploy notes (2026-01-05)", 2026-01-05)'
G_ARGS = ["--convention", "section", "--cut-date", "2026-02-01", "--today", "2026-03-01"]


def g_counts(n, kept, nar, refused):
    return ("RULES DRAFT: %d rule sentence(s) in the moving records; %d already kept, 0 kept in "
            "--hoisted, %d let through by --narrative, %d refused on --apply" % (n, kept, nar, refused))


def g_c1(shape, rule_line):
    """The two closer shapes: (a) a list-marker opener, (b) a closer with text after the backticks."""
    if shape == "a":
        b1, b2 = "- ```bash\n  make install\n  ```\n", "- ```bash\n  make test\n  ```\n"
    else:
        b1, b2 = "```bash\nmake install\n``` end of setup\n", "```bash\nmake test\n```\n"
    return "# Notes\n\n## Setup\n\n" + b1 + "\n" + G_REC + "\n\n" + rule_line + "\n\n## Test\n\n" + b2


def g_w175(kept, rec, closer):
    return ("# Notes\n\n## Releases\n\n" + kept + "\n\n## Setup\n\n```bash\nmake install\n" + closer + "\n\n"
            + G_REC + "\n\n" + rec + "\n\n## Test\n\n```bash\nmake test\n```\n")


def g_w185(kept, rec):
    return "# Notes\n\n## Releases\n\n" + kept + "\n\n" + G_REC + "\n\n" + rec + "\n\n## Test\n\nplain text here.\n"


G_W175 = [
    ("1", "Release tags: never on a Friday afternoon either.",
     "Deploys go out on Tuesdays and Thursdays after the smoke test passes,\nnever on a Friday.",
     "Deploys go out on Tuesdays and Thursdays after the smoke test passes, never on a Friday."),
    ("2", "Hotfixes may go out any day of the week,\nnever on a Friday.",
     "Deploys go out on Tuesdays and Thursdays after the smoke test passes,\nnever on a Friday.",
     "Deploys go out on Tuesdays and Thursdays after the smoke test passes, never on a Friday."),
    ("3", "We never deploy blindly.", "Never deploy\non a Friday without the rollback plan ready.",
     "Never deploy on a Friday without the rollback plan ready."),
]
FENCED_CASE_RULE = "Never deploy ```make```-built images on a Friday without a second review."


def counts_lines(out):
    return [l for l in out.splitlines() if l.startswith("RULES DRAFT: ")]


def always_block_checks(check, sandbox):
    """G: every check reads rotate.py's own lines (the counts line, the draft lines,
    'MISSING RULE: '), never an exit code alone."""
    # the two closer shapes through rotate.py
    for shape in ("a", "b"):
        d, p, r = sandbox(g_c1(shape, "- " + G_RULE))
        rc, out, err = run(p, *(G_ARGS + r))
        check("G closer shapes, rotate.py dry run, shape (%s): exit 0, the counts line '1 rule sentence(s) ... "
              "1 refused on --apply' and exactly one draft line '- %s (kept from ...)'" % (shape, G_RULE),
              rc == 0 and counts_lines(out) == [g_counts(1, 0, 0, 1)]
              and draft_lines(out) == ["- " + G_RULE + G_FROM], "rc=%d %r %r" % (rc, counts_lines(out),
                                                                                  draft_lines(out)))
        before = read(p)
        rc, out, err = run(p, *(G_ARGS + r + ["--apply"]))
        check("G closer shapes, rotate.py --apply, shape (%s): exit 3, 'MISSING RULE: %s', CLAUDE.md "
              "byte-unchanged with the rule in it once" % (shape, G_RULE),
              rc == 3 and missing(out) == ["MISSING RULE: " + G_RULE] and read(p) == before
              and read(p).count(G_RULE) == 1, "rc=%d %r %r" % (rc, missing(out), counts_lines(out)))

    # the misread-closer twins, misread and read right
    for name, kept, rec, whole in G_W175:
        for label, closer, cnt in (("misread", "``` end of setup", g_counts(2, 1, 0, 1)),
                                   ("read right", "```", g_counts(1, 0, 0, 1))):
            d, p, r = sandbox(g_w175(kept, rec, closer))
            before = read(p)
            rc, out, err = run(p, *(G_ARGS + r + ["--apply"]))
            extra_ok = True
            if name == "1" and label == "misread":
                extra_ok = draft_lines(out) == ["- never on a Friday." + G_FROM + " [already kept]",
                                                "- " + whole + G_FROM]
            check("G misread-closer twin case %s %s: --apply exit 3, CLAUDE.md byte-unchanged, 'MISSING RULE: %s', "
                  "the counts line '%s'%s" % (name, label, whole, cnt,
                                              ", and the two draft lines" if name == "1" and label == "misread"
                                              else ""),
                  rc == 3 and read(p) == before and missing(out) == ["MISSING RULE: " + whole]
                  and counts_lines(out) == [cnt] and extra_ok,
                  "rc=%d %r %r %r" % (rc, missing(out), counts_lines(out), draft_lines(out)))

    # the inline-code-span twin (a line starting with an inline code span is prose, never a boundary)
    for label, closer, cnt in (("misread", "``` end of setup", g_counts(2, 1, 0, 1)),
                               ("read right", "```", g_counts(1, 0, 0, 1))):
        txt = ("# Notes\n\n## Releases\n\nWe never deploy blindly.\n\n## Setup\n\n```bash\nmake install\n"
               + closer + "\n\n" + G_REC + "\n\nNever deploy\n"
               "```make```-built images on a Friday without a second review.\n\n"
               "## Test\n\n```bash\nmake test\n```\n")
        d, p, r = sandbox(txt)
        rc, out, err = run(p, *(G_ARGS + r + ["--apply"]))
        check("G inline-code-span twin %s: --apply exit 3, CLAUDE.md byte-unchanged, 'MISSING RULE: %s', the counts "
              "line '%s'" % (label, FENCED_CASE_RULE, cnt),
              rc == 3 and read(p) == txt and missing(out) == ["MISSING RULE: " + FENCED_CASE_RULE]
              and counts_lines(out) == [cnt],
              "rc=%d %r %r %r" % (rc, missing(out), counts_lines(out), draft_lines(out)))

    # the stated-cost twin, a stated cost under a correct reading
    txt = g_w185("Tags: never on main.", "```bash\nmake build\nnever on main\nmake deploy\n```")
    d, p, r = sandbox(txt)
    rc, out, err = run(p, *(G_ARGS + r + ["--apply"]))
    check("G stated-cost twin: a fenced block of three lines with a short rule line refuses: exit 3, "
          "CLAUDE.md byte-unchanged, 'MISSING RULE: make build never on main make deploy', counts '2 rule "
          "sentence(s) ...; 1 already kept, ... 1 refused on --apply', the two draft lines",
          rc == 3 and read(p) == txt and missing(out) == ["MISSING RULE: make build never on main make deploy"]
          and counts_lines(out) == [g_counts(2, 1, 0, 1)]
          and draft_lines(out) == ["- never on main" + G_FROM + " [already kept]",
                                   "- make build never on main make deploy" + G_FROM],
          "rc=%d %r %r %r" % (rc, missing(out), counts_lines(out), draft_lines(out)))

    # [already kept], pinned as a single-line block (guards over-blocking)
    txt = g_w185("Tags: never on main.", "```bash\nnever on main\n```")
    d, p, r = sandbox(txt)
    rc, out, err = run(p, *(G_ARGS + r + ["--apply"]))
    check("G [already kept] twin (single-line block): --apply exit 0, counts '1 rule sentence(s) ...; 1 already "
          "kept, ... 0 refused on --apply', one draft line '- never on main (kept from ...) [already kept]'",
          rc == 0 and counts_lines(out) == [g_counts(1, 1, 0, 0)]
          and draft_lines(out) == ["- never on main" + G_FROM + " [already kept]"],
          "rc=%d %r %r" % (rc, counts_lines(out), draft_lines(out)))

    # a kept fenced rule (the section does not move) is never listed (guards over-blocking)
    txt = ("# Notes\n\n## Ops\n\n```bash\n# never run this against prod\nmake deploy\n```\n\n" + G_REC
           + "\n\nThe deploy box got a new disk that week.\n\n## Test\n\nplain text here.\n")
    d, p, r = sandbox(txt)
    rc, out, err = run(p, *(G_ARGS + r))
    check("G kept fenced rule twin: rotate.py dry run with the fenced '# never run this against prod' in a kept "
          "section: exit 0, counts '0 rule sentence(s) ...', no draft line",
          rc == 0 and counts_lines(out) == [g_counts(0, 0, 0, 0)] and draft_lines(out) == [],
          "rc=%d %r %r" % (rc, counts_lines(out), draft_lines(out)))

    # a moved fenced line with no rule word is a command item only (guards over-blocking)
    txt = ("# Notes\n\n" + G_REC + "\n\nThe test step runs like this:\n\n```bash\nmake test\n```\n\n"
           "## Later notes (2026-05-01)\n\nplain text here.\n")
    d, p, r = sandbox(txt)
    rc, out, err = run(p, *(G_ARGS + r + ["--apply"]))
    loss = section(read(os.path.join(d, "split_2026-03-01", "REPORT.md")), "Loss check")
    cmd = [l for l in loss if l.endswith(": make test")]
    check("G no-rule-word twin: a moved fenced 'make test' is a LAZY-ONLY or POINTED (archive: ...) command "
          "item only: --apply exit 0, no 'MISSING RULE: ' line, no rule item line",
          rc == 0 and not missing(out) and len(cmd) == 1
          and (cmd[0].startswith("LAZY-ONLY: ") or cmd[0].startswith("POINTED (archive: "))
          and not [l for l in loss if l.startswith("    rule in section")],
          "rc=%d %r %r" % (rc, missing(out), loss))

    # the --narrative waiver reaches a fenced rule (guards something else: the rules-draft waiver)
    d, p, r = sandbox(g_c1("b", "- " + G_RULE))
    rc, out, err = run(p, *(G_ARGS + r + ["--narrative", "Deploy notes (2026-01-05)"]))
    rc2, out2, err2 = run(p, *(G_ARGS + r + ["--narrative", "Deploy notes (2026-01-05)", "--apply"]))
    check("G waiver twin: shape (b) with --narrative \"Deploy notes (2026-01-05)\": counts '1 let through by "
          "--narrative', --apply exit 0",
          rc == 0 and counts_lines(out) == [g_counts(1, 0, 1, 0)] and rc2 == 0 and not missing(out2),
          "rc=%d rc2=%d %r %r" % (rc, rc2, counts_lines(out), (out2 + err2)[-300:]))

    # a rule-shaped fence line (an info string with a rule word) refuses
    txt = ("# Notes\n\n" + G_REC + "\n\n```sh never run against prod\nmake deploy\n```\n\n"
           "## Later notes (2026-05-01)\n\nplain text here.\n")
    d, p, r = sandbox(txt)
    rc, out, err = run(p, *(G_ARGS + r + ["--apply"]))
    check("G rule-shaped fence line twin: a moving record opened by '```sh never run against prod': --apply "
          "exit 3, 'MISSING RULE: ```sh never run against prod', CLAUDE.md byte-unchanged",
          rc == 3 and missing(out) == ["MISSING RULE: ```sh never run against prod"] and read(p) == txt,
          "rc=%d %r %r" % (rc, missing(out), counts_lines(out)))


def main():
    checks = []

    def check(name, ok, detail=""):
        if not isinstance(detail, str):
            detail = repr(detail)
        checks.append((name, bool(ok), detail))

    tmpdirs = []

    def mk():
        d = os.path.realpath(tempfile.mkdtemp(prefix="rotate-rules-"))
        tmpdirs.append(d)
        return d

    def sandbox(body):
        d = mk()
        root = mk()
        p = write(os.path.join(d, "CLAUDE.md"), body)
        return d, p, ["--root", root]

    # ---------------------------------------------------------------- CONTROL
    d, p, r = sandbox(test_rotate.SECTION)
    rc, out, err = run(p, "--convention", "section", "--cut-date", "2026-07-01", *r)
    check("CONTROL harness runs rotate.py on the SECTION fixture and gets exit 0 and a FILE line",
          rc == 0 and out.startswith("FILE"), "rc=%d out=%r err=%r" % (rc, out[:120], err[-200:]))

    # ======================================== the rules draft and the loss check both refuse
    d, p, r = sandbox(P_CLAUDE)
    before = read(p)
    rc, out, err = run(p, *(BASE + r + ["--apply"]))
    mr = missing(out)
    check("refusal: an --apply on a rule-holding record with no --hoisted and no --narrative exits 3",
          rc == 3, "rc=%d %r" % (rc, (out + err)[-400:]))
    check("refusal: the output carries a 'MISSING RULE: ' line holding the first rule sentence whole",
          any(l == "MISSING RULE: " + P_R1 for l in mr), mr)
    check("refusal: the output also lists the same sentence as LAZY-ONLY (loss check)",
          any(l == "LAZY-ONLY: " + P_R1 for l in out.splitlines()),
          [l for l in out.splitlines() if l.startswith("LAZY-ONLY")])
    check("refusal: the refused apply left CLAUDE.md byte-equal and wrote only REPORT.dry.md",
          read(p) == before and split_dirs(d) == ["split_2026-02-15"]
          and ls(os.path.join(d, "split_2026-02-15")) == ["REPORT.dry.md"],
          "%r %r" % (split_dirs(d), ls(os.path.join(d, "split_2026-02-15"))))
    check("once per check: exactly one 'MISSING RULE: ' line per missing sentence (2 sentences, 2 lines)",
          len(mr) == 2 and sum(1 for l in mr if P_R1 in l) == 1 and sum(1 for l in mr if P_R2 in l) == 1,
          mr)
    check("once per check: the loss-check listing names each missing sentence exactly once more",
          sum(1 for l in out.splitlines() if l == "LAZY-ONLY: " + P_R1) == 1
          and sum(1 for l in out.splitlines() if l == "LAZY-ONLY: " + P_R2) == 1,
          [l for l in out.splitlines() if l.startswith("LAZY-ONLY")])
    rep = read(os.path.join(d, "split_2026-02-15", "REPORT.dry.md"))
    rdl = [l for l in section(rep, "Rules draft") if DRAFT_RE.match(l)]
    check("the refused apply's REPORT.dry.md Rules draft section holds each draft line",
          len(rdl) == 1 and P_R1 in rdl[0] and P_R2 in rdl[0], section(rep, "Rules draft"))

    d, p, r = sandbox(P_CLAUDE)
    rc, out, err = run(p, *(BASE + r + ["--apply", "--narrative", P_TITLE]))
    rep = read(os.path.join(d, "split_2026-02-15", "REPORT.md"))
    w = section(rep, "Waivers")
    wi = next((i for i, l in enumerate(w) if "--narrative" in l and P_TITLE in l), None)
    check("refusal: the same apply with --narrative \"<title>\" exits 0 with no 'MISSING RULE: ' line",
          rc == 0 and missing(out) == [], "rc=%d %r" % (rc, (out + err)[-400:]))
    check("refusal: REPORT.md lists both sentences under that --narrative waiver",
          wi is not None and any(P_R1 in l for l in w[wi + 1:]) and any(P_R2 in l for l in w[wi + 1:]),
          w[:8])

    # --narrative waives the rules draft for its one record only
    d, p, r = sandbox(N_CLAUDE)
    rc, out, err = run(p, *(BASE + r + ["--apply", "--narrative", N_A_TITLE]))
    mr = missing(out)
    check("--narrative waives the rules draft for its own record only: the other record's sentence is still refused",
          rc == 3 and not any(N_A_RULE in l for l in mr) and any(l == "MISSING RULE: " + N_B_RULE for l in mr),
          "rc=%d %r" % (rc, mr))

    # an --accept also matching a sentence --narrative already waived counts only its own
    d, p, r = sandbox(N_CLAUDE)
    rc, out, err = run(p, *(BASE + r + ["--apply", "--narrative", N_A_TITLE, "--accept", "lift"]))
    w = section(read(os.path.join(d, "split_2026-02-15", "REPORT.dry.md")), "Waivers")
    check("--narrative plus an --accept matching its sentence and one elsewhere: the --accept "
          "count is 1 on stdout and in the report",
          rc == 3 and 'WAIVER: --accept "lift" let through 1 item(s)' in out.splitlines()
          and '- --accept "lift" (let through 1 item(s))' in w, "rc=%d %r %r" % (rc, w[:8], out[-300:]))

    # a duplicate waiver lets nothing through, so no item lines under it
    q_title = "Queue rule record about the jobs (2026-01-08)"
    q_claude = ("# Project\n\nPreamble for the queue project.\n\n## " + q_title + "\n\n"
                "Never touch the queue.\n\n## Later record about the yard schedule (2026-03-20)\n\n"
                "The yard schedule now runs on weekdays.\n")
    d, p, r = sandbox(q_claude)
    rc, out, err = run(p, *(BASE + r + ["--accept", "queue", "--accept", "queue"]))
    w = section(read(os.path.join(d, "split_2026-02-15", "REPORT.dry.md")), "Waivers")
    unused = ('- UNUSED WAIVER: --accept "queue" let through no item (every match already waived by '
              '--accept "queue")')
    ui = w.index(unused) if unused in w else None
    check("E a duplicate --accept: the first lets through 1 item with its item line, the UNUSED entry "
          "has no item line under it",
          rc == 0 and w.count(unused) == 1 and ui is not None
          and not (ui + 1 < len(w) and w[ui + 1].startswith("  - "))
          and w.count('- --accept "queue" (let through 1 item(s))') == 1
          and w.count("  - Never touch the queue.") == 1, "rc=%d %r" % (rc, w))
    d, p, r = sandbox(q_claude)
    rc, out, err = run(p, *(BASE + r + ["--narrative", "Queue rule record", "--narrative", "Queue rule record"]))
    w = section(read(os.path.join(d, "split_2026-02-15", "REPORT.dry.md")), "Waivers")
    first = '- --narrative "Queue rule record": %s (let through 1 item(s))' % q_title
    unused = ('- UNUSED WAIVER: --narrative "Queue rule record" let through no item (every match already '
              'waived by --narrative "Queue rule record")')
    fi = w.index(first) if first in w else None
    ui = w.index(unused) if unused in w else None
    check("E a duplicate --narrative: one entry lets through the record's 1 item with its item line, the "
          "second is one UNUSED WAIVER line with no item line under it",
          rc == 0 and w.count(first) == 1 and w.count(unused) == 1 and fi is not None and ui is not None
          and w[fi + 1] == "  - Never touch the queue."
          and not (ui + 1 < len(w) and w[ui + 1].startswith("  - ")), "rc=%d %r" % (rc, w))

    # --hoisted: an ancestor CLAUDE.md is in the loaded set
    for name, held, want_rc, want_missing in (("one hoisted", [P_R1], 3, [P_R2]),
                                              ("both hoisted", [P_R1, P_R2], 0, [])):
        A = mk()
        root = mk()
        proj = os.path.join(A, "proj")
        p = write(os.path.join(proj, "CLAUDE.md"), P_CLAUDE)
        h = write(os.path.join(A, "CLAUDE.md"), "# Global rules\n\n" + "\n".join(held) + "\n")
        rc, out, err = run(p, *(BASE + ["--root", root, "--apply", "--hoisted", h]), cwd=proj)
        mr = missing(out)
        check("--hoisted %s: exit %d and 'MISSING RULE: ' names exactly %r" % (name, want_rc, want_missing),
              rc == want_rc and mr == ["MISSING RULE: " + s for s in want_missing],
              "rc=%d %r %r" % (rc, mr, (out + err)[-300:]))

    # the report names the --hoisted file of every KEPT (hoisted) item
    for mode, rname in (("dry run", "REPORT.dry.md"), ("--apply", "REPORT.md")):
        A = mk()
        root = mk()
        proj = os.path.join(A, "proj")
        p = write(os.path.join(proj, "CLAUDE.md"), P_CLAUDE)
        h = write(os.path.join(A, "CLAUDE.md"), "# Global rules\n\n" + P_R1 + "\n" + P_R2 + "\n")
        rc, out, err = run(p, *(BASE + ["--root", root, "--hoisted", h]
                                + (["--apply"] if mode == "--apply" else [])), cwd=proj)
        lc = section(read(os.path.join(proj, "split_2026-02-15", rname)), "Loss check")
        kh = [l for l in lc if l.startswith("KEPT (hoisted: ")]
        check("hoisted report %s: %s's Loss check names the --hoisted file on a KEPT (hoisted: <file>) line for "
              "each hoisted rule sentence" % (mode, rname),
              rc == 0 and any(l.endswith(P_R1) for l in kh) and any(l.endswith(P_R2) for l in kh),
              "rc=%d %r" % (rc, lc[:12]))
        want = sorted("KEPT (hoisted: ../CLAUDE.md): " + x for x in (P_R1, P_R2))
        check("hoisted report count %s: exactly two KEPT (hoisted: ../CLAUDE.md) lines, one per hoisted rule sentence" % mode,
              rc == 0 and sorted(kh) == want, "rc=%d %r" % (rc, kh))

    # the home CLAUDE.md is itself a file symlink; rotate.py, the second consumer
    H = mk()
    real = write(os.path.join(mk(), "CLAUDE.md"), "# Global rules\n\n" + P_R1 + "\n" + P_R2 + "\n")
    os.makedirs(os.path.join(H, ".claude"))
    os.symlink(real, os.path.join(H, ".claude", "CLAUDE.md"))
    d, p, r = sandbox(P_CLAUDE)
    rc, out, err = run(p, *(BASE + r + ["--apply", "--hoisted", os.path.join(H, ".claude", "CLAUDE.md")]),
                       env=dict(os.environ, HOME=H))
    check("home symlink: --hoisted <H>/.claude/CLAUDE.md, a file symlink, with HOME=<H>: accepted, both rules kept, exit 0",
          rc == 0 and missing(out) == [], "rc=%d %r" % (rc, (out + err)[-300:]))

    # ======================================== the --hoisted check through splitlib
    d, p, r = sandbox(RF_CLAUDE)
    snap = snapshot(d)
    rc, out, err = run(p, *(BASE + r + ["--apply", "--hoisted", p]))
    check("--hoisted check: --apply --hoisted <the target CLAUDE.md> exits 2",
          rc == 2, "rc=%d %r" % (rc, (out + err)[-300:]))
    check("--hoisted check: after that refusal every file is byte-equal (no backup, no manifest, no run folder)",
          snapshot(d) == snap, sorted(set(snapshot(d)) ^ set(snap)))
    d, p, r = sandbox(RF_CLAUDE)
    snap = snapshot(d)
    other = write(os.path.join(mk(), "CLAUDE.md"), "# Unrelated\n\n" + P_R1 + "\n")
    rc, out, err = run(p, *(BASE + r + ["--hoisted", other]))
    check("--hoisted check: a dry run with --hoisted naming a CLAUDE.md outside the loaded set exits 2, nothing written",
          rc == 2 and snapshot(d) == snap, "rc=%d %r" % (rc, (out + err)[-300:]))
    d, p, r = sandbox(RF_CLAUDE)
    snap = snapshot(d)
    rc, out, err = run(p, *(BASE + r + ["--apply", "--hoisted", os.path.join(os.path.dirname(d), "nope",
                                                                             "CLAUDE.md")]))
    check("disk-failure rule: a missing --hoisted file exits 2, nothing written",
          rc == 2 and snapshot(d) == snap, "rc=%d %r" % (rc, (out + err)[-300:]))

    # ======================================== the draft is one function
    d, p, r = sandbox(V1_CLAUDE)
    rc, out, err = run(p, *(BASE + r))
    dl = draft_lines(out)
    fn = draft_fn()
    got = None
    if fn is not None:
        try:
            text = read(p)
            lines = text.splitlines(keepends=True)
            recs = [x for x in rotate.parse_records(lines, "section") if x[2] < "2026-02-01"]
            drop = set()
            for s, e, _, _ in recs:
                drop.update(range(s, e))
            outside = "".join(l for i, l in enumerate(lines) if i not in drop)
            res = fn([(t, dt, "".join(lines[s:e])) for s, e, dt, t in recs], outside)
            got = [u.text for rec in res for u in rec.units]
            got_s = [s.text for rec in res for s in rec.sentences]
        except Exception as e:                                  # noqa: BLE001
            got = got_s = "raised %s: %s" % (type(e).__name__, e)
    check("one draft function: rotate.rules_draft's units equal, in order, the <unit> parts of the dry run's draft lines",
          isinstance(got, list) and got != [] and got == [DRAFT_RE.match(l).group(1) for l in dl],
          "fn=%r draft=%r" % (got, dl))
    d, p, r = sandbox(V1_CLAUDE)
    rc, out, err = run(p, *(BASE + r + ["--apply"]))
    check("one draft function: on V1's refused --apply, rotate.rules_draft's sentences equal, in order, "
          "the MISSING RULE texts ([V_RULE])",
          rc == 3 and isinstance(got_s, list) and got_s == [V_RULE]
          and got_s == [l[len("MISSING RULE: "):] for l in missing(out)],
          "rc=%d fn=%r missing=%r" % (rc, got_s, missing(out)))

    # ======================================== in-file hoist, fragment check
    # (1)
    d, p, r = sandbox(V1_CLAUDE)
    rc, out, err = run(p, *(BASE + r))
    dl = draft_lines(out)
    check("in-file hoist (1) the dry run prints one draft line, title whole without '#'s, no [already kept]",
          dl == ['- %s %s (kept from "%s", 2026-01-10)' % (V_RULE, V_LONG, V_TITLE)], dl)
    write(p, hoist(read(p), dl[0] if dl else "- (no draft line)"))
    rc, out, err = run(p, *(BASE + r + ["--apply"]))
    check("in-file hoist (1) after pasting the draft line, --apply exits 0 and all presence checks pass",
          rc == 0 and "All presence checks passed" in out, "rc=%d %r" % (rc, (out + err)[-500:]))
    check("in-file hoist (1) the pasted unit holds both body lines: 1 fragment, two SKIPPED lines, "
          "and the NOTE counts it",
          "moved records: 1 records / 1 fragments" in out and len(skipped(out)) == 2
          and any("1 record(s) had no usable body fragment" in l for l in note(out)),
          "%r %r %r" % (skipped(out), note(out), [l for l in out.splitlines() if "moved records" in l]))
    # (2)
    d, p, r = sandbox(V2_CLAUDE)
    rc, out, err = run(p, *(BASE + r))
    dl = draft_lines(out)
    write(p, hoist(read(p), dl[0] if dl else "- (no draft line)"))
    rc, out, err = run(p, *(BASE + r + ["--apply"]))
    check("in-file hoist (2) the rule line as the only long body line: exit 0, one SKIPPED line, the NOTE counts it",
          rc == 0 and len(skipped(out)) == 1 and any("1 record(s) had no usable body fragment" in l
                                                      for l in note(out)),
          "rc=%d %r %r %r" % (rc, skipped(out), note(out), (out + err)[-300:]))
    # (3)
    d, p, r = sandbox(V2_CLAUDE)
    rc, out, err = run(p, *(BASE + r + ["--apply", "--narrative", V_TITLE]))
    check("in-file hoist (3) the same record with no hoist and --narrative: exit 0, no SKIPPED line, no NOTE",
          rc == 0 and skipped(out) == [] and note(out) == [],
          "rc=%d %r %r %r" % (rc, skipped(out), note(out), (out + err)[-300:]))
    # (4)
    d, p, r = sandbox(V4_CLAUDE)
    rc, out, err = run(p, *(BASE + r))
    dl = draft_lines(out)
    check("in-file hoist (4) a rule line that already opens a KEPT record: its draft line ends ' [already kept]'",
          dl == ['- %s Painted green. (kept from "%s", 2026-01-10) [already kept]' % (V_RULE, V_TITLE)], dl)
    rc, out, err = run(p, *(BASE + r + ["--apply"]))
    check("in-file hoist (4) --apply with no hoist exits 0",
          rc == 0 and "All presence checks passed" in out, "rc=%d %r" % (rc, (out + err)[-400:]))
    # (5)
    d, p, r = sandbox(COLLIDING)
    rc, out, err = run(p, "--convention", "section", "--cut-date", "2026-07-01", "--apply",
                       "--today", "2026-08-15", *r)
    check("in-file hoist (5) COLLIDING is unchanged: FAIL moved, exit 2",
          rc == 2 and "FAIL moved" in out, "rc=%d %r" % (rc, out[-300:]))

    # ======================================== G: the always-block rule
    always_block_checks(check, sandbox)

    for d in tmpdirs:
        shutil.rmtree(d, ignore_errors=True)

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
    sys.exit(main())
