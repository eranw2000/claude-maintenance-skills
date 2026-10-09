#!/usr/bin/env python3
"""Tests for the open-work, waiver, run-folder and report parts of rotate.py.

Open-work evidence and its refusal, the run folder rule, REPORT.dry.md and the
refused apply, the in-memory loss check and pointer report that see the run's
own archives and index, and the one-record waivers --move-anyway and
--narrative. test_rotate.py keeps the older checks; these sit beside it.

Every fixture is a synthetic string built here and written to a mkdtemp
folder. Row 0 is a CONTROL with a known answer: if it fails, the harness is
broken rather than the script.

Run:  python3 test_rotate_noloss.py
"""

import json
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

SECTION = test_rotate.SECTION
DELTA_RULE = ("Measured on 2026-03-01, a date in ordinary PROSE that must never "
              "be read as a")

# Open-work fixture: one old record whose backticked token is named by
# one open item with a continuation line. No RULE_RE word anywhere.
OW_TITLE = "Gadget sorter record about the conveyor (2026-01-10)"
OW_FILE = "sort_gadgets_v3.py"
OW_CLAUDE = ("# Project\n\nPreamble for the gadget project.\n\n"
             "## " + OW_TITLE + "\n\n"
             "The sorter writes its batches through `" + OW_FILE + "` before the noon shift.\n\n"
             "## Later record about the gadget dashboard (2026-03-20)\n\n"
             "The dashboard reads the sorter totals once a day.\n")
OW_ITEM_1 = ("Retire the old path inside `" + OW_FILE + "` once the warehouse team "
             "confirms the totals")
OW_ITEM_2 = "and the weekly counts line up with the paper log"
OW_ITEM = OW_ITEM_1 + " " + OW_ITEM_2
OW_TODO = ("# TODO\n\n## Active\n\n- [ ] " + OW_ITEM_1 + "\n  " + OW_ITEM_2 + "\n"
           "- [x] A closed item about lunch.\n")

# Rule-free fixture for the run folder tests.
RF_CLAUDE = ("# Project\n\nPreamble for the folder tests.\n\n"
             "## Folder alpha record about the crates (2026-01-05)\n\n"
             "The crates moved to the north shelf during the stock count.\n\n"
             "## Folder beta record about the labels (2026-02-10)\n\n"
             "The labels switched to the larger print size that week.\n\n"
             "## Folder gamma record about the scanner (2026-04-01)\n\n"
             "The scanner reads the larger labels without retries now.\n")
RF_TODAY = "2026-04-15"

# Run outputs fixture: rule-free, an identifier per moving record.
G_CLAUDE = ("# Project\n\nPreamble line for the gadget project.\n\n"
            "## Overview\n\n{overview}\n\n"
            "## Gadget intake record (2026-05-04)\n\n"
            "The gadget intake moved to commit `a1b2c3d` and the queue shrank by half overnight.\n\n"
            "## Gadget export record (2026-06-12)\n\n"
            "The gadget export feed was rebuilt in commit `b2c3d4e` with daily files.\n\n"
            "## Gadget dashboard record (2026-08-20)\n\n"
            "The gadget dashboard now reads the export feed once each morning at six.\n")
G_PLAIN = "Plain overview text about the gadget project."
G_MISSING = "See `MISSING_NOTES.md` for the old gadget notes."

# Two moving records whose titles share "Gadget sorter", each named by open work.
CASE_B_CLAUDE = ("# Project\n\nPreamble for the waiver tests.\n\n"
              "## Gadget sorter alpha batch (2026-01-10)\n\n"
              "The alpha batch runs `sort_alpha_v1.py` each morning before the shift.\n\n"
              "## Gadget sorter beta batch (2026-01-12)\n\n"
              "The beta batch runs `sort_beta_v1.py` each evening after the shift.\n\n"
              "## Later record about the dashboard (2026-03-20)\n\n"
              "The dashboard reads the batch totals once a day.\n")
CASE_B_TODO = ("# TODO\n\n- [ ] Move `sort_alpha_v1.py` onto the new belt controller next week\n"
            "- [ ] Move `sort_beta_v1.py` onto the new belt controller next month\n")
# One moving title is a substring of another; only the shorter has open work.
CASE_B2_SHORT = "Gadget sorter alpha batch (2026-01-10)"
CASE_B2_LONG = "Notes on Gadget sorter alpha batch (2026-01-10)"
CASE_B2_CLAUDE = ("# Project\n\nPreamble for the waiver tests.\n\n"
               "## " + CASE_B2_SHORT + "\n\n"
               "The alpha batch runs `sort_alpha_v1.py` each morning before the shift.\n\n"
               "## " + CASE_B2_LONG + "\n\n"
               "The follow-up notes describe the spare belt in the north hall.\n\n"
               "## Later record about the dashboard (2026-03-20)\n\n"
               "The dashboard reads the batch totals once a day.\n")
CASE_B2_TODO = "# TODO\n\n- [ ] Move `sort_alpha_v1.py` onto the new belt controller next week\n"

# (m): two moving records, one rule sentence each, titles sharing "Gadget rule".
M_CLAUDE = ("# Project\n\nPreamble for the narrative tests.\n\n"
            "## Gadget rule alpha (2026-01-10)\n\n"
            "Never run the alpha sorter without the guard rail in place on the belt.\n\n"
            "## Gadget rule beta (2026-01-12)\n\n"
            "Always log the beta sorter totals into the paper ledger before noon.\n\n"
            "## Later record about the dashboard (2026-03-20)\n\n"
            "The dashboard reads the batch totals once a day.\n")

# Open-work matcher fixture (in-process). R1 moves; R2 and R3 stay.
MT_TITLE = "Matcher record about the packing station (2026-01-10)"
MT_BEFORE = ("# Project\n\n"
             "## " + MT_TITLE + "\n\n"
             "Runs `alpha_job_v1.py`, reads `shared_cfg.yaml`, see `README.md` and `widget`,\n"
             "writes under `docs/` and calls `crowd_tool.py` at commit 9f8e7d6c1.\n\n"
             "## Second record about the scales (2026-02-11)\n\n"
             "Reads `shared_cfg.yaml` too.\n\n"
             "## Third record about the labels (2026-03-12)\n\n"
             "Also reads `shared_cfg.yaml` here.\n")
MT_ITEMS = [
    "Port `alpha_job_v1.py` to the new runner",                  # 1 distinctive token
    "Tidy `shared_cfg.yaml` keys",                               # 2 in 3 records
    "Update `README.md` for the team",                           # 3 stoplist
    "Rename the `widget` helper",                                # 4 not identifier-shaped
    "Clean `docs/` of old pages",                                # 5 bare word/ folder
    "Check `xalpha_job_v1.py` output",                           # 6 edge: not the token
    "Look again at what we know about the packing station first", # 7 title 4-word run
    "Verify commit 9f8e7d6c1 reached the scales",                # 8 hex hash
] + ["Retry `crowd_tool.py` run %d" % i for i in range(1, 7)]    # 9-14 key in 6 items

# hash keys ("hashes always qualify"): an all-letter and an all-digit commit id.
CASE_D_BEFORE = ("# Project\n\n"
             "## Widget shipped (2025-01-05)\n\n"
             "Shipped in commit `abcdefa` and tagged 7654321 for the archive.\n\n"
             "## Later record about the mirror (2026-03-05)\n\nThe mirror syncs nightly.\n")
CASE_D_ITEMS = ["Follow up on commit abcdefa after the next sync",
            "Check build 7654321 on the mirror"]

# The key is in 3 records of the BEFORE text but only 1 of the folder's
# CLAUDE.md, so the matcher must count over the before text it is given.
CASE_K_BEFORE = ("# Project\n\n"
               "## Shared alpha record (2026-01-10)\n\nUses `pack_tool_v9.py` daily.\n\n"
               "## Shared beta record (2026-02-10)\n\nUses `pack_tool_v9.py` weekly.\n\n"
               "## Shared gamma record (2026-03-10)\n\nUses `pack_tool_v9.py` monthly.\n")
CASE_K_FOLDER = ("# Project\n\n"
               "## Shared alpha record (2026-01-10)\n\nUses `pack_tool_v9.py` daily.\n")


RUN_ROOTS = []


def run(path, *extra, cwd=None):
    """rotate.py in a child process. A call that names neither --root nor
    --undo gets a fresh empty --root (new rotate.py tests pass
    --root <tmp>), so no verdict depends on the real home .claude folder."""
    extra = list(extra)
    if "--root" not in extra and "--undo" not in extra:
        r = os.path.realpath(tempfile.mkdtemp(prefix="noloss-root-"))
        RUN_ROOTS.append(r)
        extra += ["--root", r]
    cmd = [sys.executable, ROTATE, path] + extra
    p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, cwd=cwd)
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


def write(path, text, binary=False):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb" if binary else "w", **({} if binary else {"encoding": "utf-8"})) as fh:
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


def runs_rows(index_text):
    rows, inside = [], False
    for ln in index_text.splitlines():
        if inside and ln.startswith("## "):
            break
        if inside and ln.startswith("|") and not ln.replace(" ", "").startswith("|Date|") \
                and not re.match(r"^[\s|:\-]+$", ln):
            rows.append(ln)
        if ln.strip() == "## Runs":
            inside = True
    return rows


def last_run_lines(text):
    return [l for l in text.splitlines() if l.startswith("Last split run:")]


def open_work(*a, **k):
    """rotate.open_work, or [] when it is absent or raises (fail, never crash)."""
    fn = getattr(rotate, "open_work", None)
    if fn is None:
        return []
    try:
        return fn(*a, **k)
    except Exception:                                          # noqa: BLE001
        return []


def main():
    checks = []

    def check(name, ok, detail=""):
        if not isinstance(detail, str):
            detail = repr(detail)
        checks.append((name, bool(ok), detail))

    tmpdirs = []

    def mk():
        d = os.path.realpath(tempfile.mkdtemp(prefix="rotate-noloss-"))
        tmpdirs.append(d)
        return d

    def sandbox(body, todo=None):
        d = mk()
        p = write(os.path.join(d, "CLAUDE.md"), body)
        if todo is not None:
            write(os.path.join(d, "TODO.md"), todo)
        return d, p

    # ---------------------------------------------------------------- CONTROL
    d, p = sandbox(SECTION)
    rc, out, err = run(p, "--convention", "section", "--cut-date", "2026-07-01")
    check("CONTROL harness runs rotate.py on the SECTION fixture and gets exit 0 and a FILE line",
          rc == 0 and out.startswith("FILE"), "rc=%d out=%r err=%r" % (rc, out[:120], err[-200:]))

    # ======================================== (k) to (n): --narrative (B28-1)
    def first_apply():
        d, p = sandbox(SECTION)
        run(p, "--convention", "section", "--cut-date", "2026-07-01",
            "--keep", "crawler", "--apply", "--today", "2026-08-15")
        return d, p

    second = ["--convention", "section", "--cut-date", "2026-09-01", "--apply", "--today", "2026-08-16"]

    d, p = first_apply()
    after_first = read(p)
    rc, out, err = run(p, *second)
    lazy = [l for l in out.splitlines() if l.startswith("LAZY-ONLY: ") and DELTA_RULE in l]
    rd = os.path.join(d, "split_2026-08-16")
    check("(k) the Delta apply WITHOUT --narrative exits 3",
          rc == 3, "rc=%d %r" % (rc, (out + err)[-400:]))
    check("(k) a stdout line starting 'LAZY-ONLY: ' carries the Delta rule sentence",
          len(lazy) >= 1, [l for l in out.splitlines() if l.startswith("LAZY-ONLY")][:4])
    check("(k) CLAUDE.md is byte-equal to its text after the first apply",
          after_first != "" and read(p) == after_first, read(p)[-200:])
    check("(k) no CLAUDE.md.backup-before-split-2026-08-16 exists",
          "CLAUDE.md.backup-before-split-2026-08-16" not in ls(d), repr(ls(d)))
    check("(k) the run folder holds exactly REPORT.dry.md, line 1 'Mode: --apply refused (exit 3)'",
          ls(rd) == ["REPORT.dry.md"]
          and read(os.path.join(rd, "REPORT.dry.md")).split("\n")[0] == "Mode: --apply refused (exit 3)",
          "%r %r" % (ls(rd), read(os.path.join(rd, "REPORT.dry.md"))[:80]))

    d, p = first_apply()
    rc, out, err = run(p, *(second + ["--narrative", "Delta record"]))
    rep = read(os.path.join(d, "split_2026-08-16", "REPORT.md"))
    w = section(rep, "Waivers")
    wi = next((i for i, l in enumerate(w) if "--narrative" in l and "Delta record" in l), None)
    check("(l) the same apply WITH --narrative \"Delta record\" exits 0",
          rc == 0, "rc=%d %r" % (rc, (out + err)[-400:]))
    check("(l) REPORT.md Waivers lists --narrative with Delta record and, under it, the Delta rule sentence",
          wi is not None and any(DELTA_RULE in l for l in w[wi + 1:]), w[:8])

    for mode in ("dry run", "--apply"):
        d, p = sandbox(M_CLAUDE)
        before = read(p)
        args = ["--convention", "section", "--cut-date", "2026-02-01", "--today", "2026-02-15",
                "--narrative", "Gadget rule"]
        if mode == "--apply":
            args.append("--apply")
        rc, out, err = run(p, *args)
        check("(m) %s: --narrative matching two moving records exits 3, prints both titles, "
              "writes nothing" % mode,
              rc == 3 and "Gadget rule alpha (2026-01-10)" in out and "Gadget rule beta (2026-01-12)" in out
              and read(p) == before and split_dirs(d) == [],
              "rc=%d dirs=%r %r" % (rc, split_dirs(d), out[-400:]))

    for value in ("", "   "):
        d, p = first_apply()
        snap = snapshot(d)
        dirs = split_dirs(d)
        rc, out, err = run(p, *(second + ["--narrative", value]))
        check("(n) --apply --narrative %r exits 2 naming --narrative, nothing written" % value,
              rc == 2 and "--narrative" in out + err and snapshot(d) == snap and split_dirs(d) == dirs,
              "rc=%d %r" % (rc, (out + err)[-300:]))

    # ========================================== run folder
    base = ["--convention", "section", "--today", RF_TODAY]
    run_name = "split_" + RF_TODAY

    # (a)
    d, p = sandbox(RF_CLAUDE)
    notes = write(os.path.join(d, run_name, "notes.md"), "hand notes\n")
    rc, out, err = run(p, *(base + ["--cut-date", "2026-02-01"]))
    check("(a) a dry run beside a hand-made split_<today>/notes.md writes split_<today>-2/REPORT.dry.md",
          rc == 0 and ls(os.path.join(d, run_name + "-2")) == ["REPORT.dry.md"],
          "rc=%d dirs=%r %r" % (rc, split_dirs(d), out[-200:]))
    rc, out, err = run(p, *(base + ["--cut-date", "2026-02-01", "--apply"]))
    check("(a) the --apply then reuses -2/, which holds REPORT.dry.md, REPORT.md and manifest.json",
          rc == 0 and ls(os.path.join(d, run_name + "-2")) == ["REPORT.dry.md", "REPORT.md", "manifest.json"],
          "rc=%d %r %r" % (rc, ls(os.path.join(d, run_name + "-2")), (out + err)[-300:]))
    lr = last_run_lines(read(p))
    check("(a) the Last-run line names split_<today>-2",
          len(lr) == 1 and (run_name + "-2/REPORT.md") in lr[0], repr(lr))
    rows = runs_rows(read(os.path.join(d, "CLAUDE_DECISIONS_INDEX.md")))
    check("(a) the Runs row names split_<today>-2",
          len(rows) == 1 and (run_name + "-2") in rows[0], repr(rows))
    check("(a) notes.md is byte-identical and the only entry of split_<today>/",
          read(notes) == "hand notes\n" and ls(os.path.join(d, run_name)) == ["notes.md"],
          repr(ls(os.path.join(d, run_name))))

    # (b)
    d, p = sandbox(RF_CLAUDE)
    rc1, o1, _ = run(p, *(base + ["--cut-date", "2026-02-01", "--apply"]))
    rc2, o2, _ = run(p, *(base + ["--cut-date", "2026-03-01", "--apply"]))
    check("(b) two applies on the same day: the second lands in split_<today>-2/",
          rc1 == 0 and rc2 == 0 and "REPORT.md" in ls(os.path.join(d, run_name))
          and "REPORT.md" in ls(os.path.join(d, run_name + "-2")),
          "rc=%d,%d dirs=%r %r" % (rc1, rc2, split_dirs(d), o2[-200:]))

    # (c)
    d, p = sandbox(RF_CLAUDE)
    os.makedirs(os.path.join(d, run_name))
    rc, out, err = run(p, *(base + ["--cut-date", "2026-02-01"]))
    check("(c) an EMPTY pre-made split_<today>/ is skipped: the run writes -2/",
          rc == 0 and ls(os.path.join(d, run_name + "-2")) == ["REPORT.dry.md"],
          "rc=%d dirs=%r" % (rc, split_dirs(d)))
    check("(c) the empty split_<today>/ stays empty",
          os.path.isdir(os.path.join(d, run_name)) and ls(os.path.join(d, run_name)) == [],
          repr(ls(os.path.join(d, run_name))))

    # (d)
    d, p = sandbox(RF_CLAUDE)
    ds = write(os.path.join(d, run_name, ".DS_Store"), b"\x00\x01finder", binary=True)
    write(os.path.join(d, run_name, "REPORT.dry.md"), "Mode: dry run\nold\n")
    rc, out, err = run(p, *(base + ["--cut-date", "2026-02-01"]))
    check("(d) split_<today>/ holding .DS_Store and REPORT.dry.md is reused, .DS_Store byte-identical",
          rc == 0 and split_dirs(d) == [run_name] and readb(ds) == b"\x00\x01finder"
          and read(os.path.join(d, run_name, "REPORT.dry.md")).startswith("Mode: dry run\n")
          and read(os.path.join(d, run_name, "REPORT.dry.md")) != "Mode: dry run\nold\n",
          "rc=%d dirs=%r" % (rc, split_dirs(d)))
    d, p = sandbox(RF_CLAUDE)
    ds = write(os.path.join(d, run_name, ".DS_Store"), b"\x00\x01finder", binary=True)
    rc, out, err = run(p, *(base + ["--cut-date", "2026-02-01"]))
    check("(d) split_<today>/ holding .DS_Store alone is skipped to -2/, .DS_Store byte-identical",
          rc == 0 and ls(os.path.join(d, run_name + "-2")) == ["REPORT.dry.md"]
          and readb(ds) == b"\x00\x01finder" and ls(os.path.join(d, run_name)) == [".DS_Store"],
          "rc=%d dirs=%r" % (rc, split_dirs(d)))

    # (e)
    d, p = sandbox(OW_CLAUDE, OW_TODO)
    before = read(p)
    eargs = ["--convention", "section", "--cut-date", "2026-02-01", "--today", "2026-02-15", "--apply"]
    rc, out, err = run(p, *eargs)
    ed = os.path.join(d, "split_2026-02-15")
    check("(e) an open-work refused --apply exits 3 and its folder holds exactly REPORT.dry.md",
          rc == 3 and ls(ed) == ["REPORT.dry.md"], "rc=%d %r %r" % (rc, ls(ed), (out + err)[-300:]))
    check("(e) the refused report's line 1 is 'Mode: --apply refused (exit 3)'",
          read(os.path.join(ed, "REPORT.dry.md")).split("\n")[0] == "Mode: --apply refused (exit 3)",
          read(os.path.join(ed, "REPORT.dry.md"))[:80])
    check("(e) the refused apply makes no backup and leaves CLAUDE.md byte-identical",
          read(p) == before and not any("backup-before-split" in n for n in ls(d)), repr(ls(d)))
    rc, out, err = run(p, *(eargs + ["--move-anyway", OW_TITLE]))
    check("(e) the same apply with --move-anyway the whole title exits 0 into the SAME folder",
          rc == 0 and split_dirs(d) == ["split_2026-02-15"] and "REPORT.md" in ls(ed),
          "rc=%d dirs=%r %r" % (rc, split_dirs(d), (out + err)[-300:]))

    # (f)
    d, p = sandbox(RF_CLAUDE)
    q = write(os.path.join(d, run_name, "QUESTIONS.md"), "q one | frag | fact\n")
    write(os.path.join(d, run_name, "REPORT.dry.md"), "Mode: dry run\n")
    rc, out, err = run(p, *(base + ["--cut-date", "2026-02-01", "--apply"]))
    man = {}
    try:
        man = json.loads(read(os.path.join(d, run_name, "manifest.json")) or "{}")
    except ValueError:
        man = {}
    check("(f) a folder holding REPORT.dry.md and QUESTIONS.md is reused by --apply",
          rc == 0 and ls(os.path.join(d, run_name))
          == ["QUESTIONS.md", "REPORT.dry.md", "REPORT.md", "manifest.json"],
          "rc=%d %r %r" % (rc, ls(os.path.join(d, run_name)), (out + err)[-300:]))
    check("(f) QUESTIONS.md is byte-identical and is no manifest entry",
          read(q) == "q one | frag | fact\n" and man.get("files")
          and not any("QUESTIONS" in f.get("path", "") for f in man.get("files", [])),
          repr(man)[:300])
    lr = last_run_lines(read(p))
    check("(f) the Last-run line names split_<today> (no suffix)",
          len(lr) == 1 and lr[0].endswith("report %s/REPORT.md" % run_name), repr(lr))
    d, p = sandbox(RF_CLAUDE)
    q = write(os.path.join(d, run_name, "QUESTIONS.md"), "q one | frag | fact\n")
    rc, out, err = run(p, *(base + ["--cut-date", "2026-02-01", "--apply"]))
    check("(f twin) a folder holding only QUESTIONS.md is skipped to -2/ and stays byte-identical",
          rc == 0 and ls(os.path.join(d, run_name)) == ["QUESTIONS.md"]
          and read(q) == "q one | frag | fact\n" and "REPORT.md" in ls(os.path.join(d, run_name + "-2")),
          "rc=%d dirs=%r" % (rc, split_dirs(d)))

    # ======================================== run outputs present (pointers)
    groot = mk()
    gargs = ["--convention", "section", "--today", "2026-09-01", "--root", groot]
    d, p = sandbox(G_CLAUDE.format(overview=G_PLAIN))
    rc, out, err = run(p, *(gargs + ["--cut-date", "2026-06-01"]))
    dry = read(os.path.join(d, "split_2026-09-01", "REPORT.dry.md"))
    rc_a, out_a, err_a = run(p, *(gargs + ["--cut-date", "2026-06-01", "--apply"]))
    rep = read(os.path.join(d, "split_2026-09-01", "REPORT.md"))
    check("(g) the first --apply exits 0", rc_a == 0, "rc=%d %r" % (rc_a, (out_a + err_a)[-400:]))
    check("(g) REPORT.md has a Pointers section that does NOT list CLAUDE_DECISIONS_INDEX.md",
          "## Pointers" in rep.splitlines()
          and not any("CLAUDE_DECISIONS_INDEX.md" in l for l in section(rep, "Pointers")),
          section(rep, "Pointers")[:6])
    head = "## Gadget intake record (2026-05-04)"
    for name, text in (("dry run", dry), ("--apply", rep)):
        ls_ = section(text, "Loss check")
        nowhere = [l for l in ls_ if l.startswith("NOWHERE: ")]
        head_ok = any(l.startswith(("LAZY-ONLY: ", "POINTED (archive: ")) and l.endswith(head) for l in ls_)
        check("(h) %s: 0 NOWHERE items and the moved heading reads LAZY-ONLY or POINTED (archive)" % name,
              ls_ != [] and not nowhere and head_ok, ls_[:8])

    on_disk = read(os.path.join(d, "CLAUDE_DECISIONS_INDEX.md"))
    rc, out, err = run(p, *(gargs + ["--cut-date", "2026-07-01", "--apply"]))
    rep2 = read(os.path.join(d, "split_2026-09-01-2", "REPORT.md"))
    jline = [l for l in section(rep2, "Loss check")
             if l.startswith("POINTED (archive: CLAUDE_DECISIONS_2026-06.md") and "b2c3d4e" in l]
    check("(j) precondition: the index on disk before the second run does not name the June archive",
          on_disk != "" and "CLAUDE_DECISIONS_2026-06.md" not in on_disk, on_disk[-200:])
    check("(j) a second apply into a new month reads its identifier POINTED (archive) via the in-memory index",
          rc == 0 and len(jline) == 1, "rc=%d %r" % (rc, section(rep2, "Loss check")[:8]))

    d, p = sandbox(G_CLAUDE.format(overview=G_MISSING))
    rc, out, err = run(p, *(gargs + ["--cut-date", "2026-06-01", "--apply"]))
    rep = read(os.path.join(d, "split_2026-09-01", "REPORT.md"))
    check("(i) an unresolved pointer in a kept section: the apply still exits 0",
          rc == 0, "rc=%d %r" % (rc, (out + err)[-300:]))
    check("(i) REPORT.md's Pointers section lists MISSING_NOTES.md with its section",
          any("MISSING_NOTES.md" in l and "Overview" in l for l in section(rep, "Pointers")),
          section(rep, "Pointers")[:6])

    # ========================================== open-work evidence
    d, p = sandbox(OW_CLAUDE, OW_TODO)
    ow = ["--convention", "section", "--cut-date", "2026-02-01", "--today", "2026-02-15"]
    rc, out, err = run(p, *ow)
    dry = read(os.path.join(d, "split_2026-02-15", "REPORT.dry.md"))
    sec = section(dry, "Open-work evidence")
    ti = next((i for i, l in enumerate(sec) if OW_TITLE in l), None)
    check("open work: the dry run exits 0 and names the open item on stdout with its key",
          rc == 0 and any(OW_FILE in l and "key" in l for l in out.splitlines()), out[-400:])
    check("open work: REPORT.dry.md lists the whole title, then the whole item (continuation joined) with key: <token>",
          ti is not None and any(OW_ITEM in l and re.search(r"key: `?" + re.escape(OW_FILE), l)
                                 for l in sec[ti + 1:]), sec[:6])
    check("open work: line 1 of a dry run's report is 'Mode: dry run'",
          dry.split("\n")[0] == "Mode: dry run", dry[:60])
    heads = [l[3:] for l in dry.splitlines() if l.startswith("## ") and l[3:] in REPORT_SECTIONS]
    check("open work: REPORT.dry.md carries Summary, Move, Keep, Open-work evidence, Loss check, Pointers "
          "in the data model order",
          all(h in heads for h in ("Summary", "Move", "Keep", "Open-work evidence", "Loss check", "Pointers"))
          and heads == [s for s in REPORT_SECTIONS if s in heads], repr(heads))
    mline = [l for l in out.splitlines() if OW_TITLE[:40] in l and l.startswith("  2026-01-10")]
    check("open work: the dry run's MOVE line prints the record's obligation and reference density",
          len(mline) == 1 and "obligation" in mline[0] and "reference" in mline[0], repr(mline))
    rc, out, err = run(p, *(ow + ["--apply"]))
    check("open work: --apply on that input exits 3 and writes nothing to CLAUDE.md or an archive",
          rc == 3 and read(p) == OW_CLAUDE and not any(n.startswith("CLAUDE_DECISIONS") for n in ls(d)),
          "rc=%d %r" % (rc, ls(d)))
    rc, out, err = run(p, *(ow + ["--apply", "--move-anyway", OW_TITLE]))
    rep = read(os.path.join(d, "split_2026-02-15", "REPORT.md"))
    check("open work: --move-anyway <whole title> applies and REPORT.md's Waivers names it and the record",
          rc == 0 and any("--move-anyway" in l and OW_TITLE in l for l in section(rep, "Waivers"))
          and ("## " + OW_TITLE) not in read(p).splitlines(),
          "rc=%d %r" % (rc, section(rep, "Waivers")[:6]))

    # matcher, in process
    md = mk()
    todo = write(os.path.join(md, "TODO.md"),
                 "# TODO\n\n" + "".join("- [ ] %s\n" % t for t in MT_ITEMS))
    write(os.path.join(md, "CLAUDE.md"), MT_BEFORE)
    mlines = MT_BEFORE.splitlines(keepends=True)
    mrec = [r for r in rotate.parse_records(mlines, "section") if r[2] < "2026-02-01"]
    moving = [(r[3], "".join(mlines[r[0]:r[1]])) for r in mrec]
    res = open_work(md, [], moving, MT_BEFORE, "section")
    hits = res[0][1] if res and len(res[0]) > 1 else []
    by_ord = dict((h.ordinal, h) for h in hits) if hits and hasattr(hits[0], "ordinal") else {}
    check("open-work matcher: a distinctive backticked token matches its open item, key printed",
          1 in by_ord and by_ord[1].key == "alpha_job_v1.py", repr(hits))
    check("open-work matcher: a key in more than 2 records of the before text does not count",
          by_ord != {} and 2 not in by_ord, repr(sorted(by_ord)))
    check("open-work matcher: a stoplist token does not count", by_ord != {} and 3 not in by_ord,
          repr(sorted(by_ord)))
    check("open-work matcher: a token that is not identifier-shaped does not count",
          by_ord != {} and 4 not in by_ord, repr(sorted(by_ord)))
    check("open-work matcher: a bare word/ folder does not count", by_ord != {} and 5 not in by_ord,
          repr(sorted(by_ord)))
    check("open-work matcher: a key matches on token edges, never inside a longer token",
          by_ord != {} and 6 not in by_ord, repr(sorted(by_ord)))
    check("open-work matcher: a 4-word run of the title (date removed) is a key",
          7 in by_ord and by_ord[7].key == "about the packing station", repr(sorted(by_ord)))
    check("open-work matcher: a hex hash of the record is a key",
          8 in by_ord and by_ord[8].key == "9f8e7d6c1", repr(sorted(by_ord)))
    check("open-work matcher: a key in more than 5 open items does not count",
          by_ord != {} and not any(o >= 9 for o in by_ord), repr(sorted(by_ord)))
    check("open-work matcher: each hit carries its source file and ordinal",
          1 in by_ord and os.path.basename(by_ord[1].source) == "TODO.md", repr(hits))
    rd = mk()
    write(os.path.join(rd, "TODO.md"), "# TODO\n\n" + "".join("- [ ] %s\n" % t for t in CASE_D_ITEMS))
    write(os.path.join(rd, "CLAUDE.md"), CASE_D_BEFORE)
    rlines = CASE_D_BEFORE.splitlines(keepends=True)
    rrec = [r for r in rotate.parse_records(rlines, "section") if r[2] < "2026-01-01"]
    rres = open_work(rd, [], [(r[3], "".join(rlines[r[0]:r[1]])) for r in rrec], CASE_D_BEFORE, "section")
    rhits = rres[0][1] if rres and len(rres[0]) > 1 else []
    got = sorted((h.ordinal, h.key) for h in rhits if hasattr(h, "ordinal"))
    check("hash keys, open-work matcher: an all-letter and an all-digit commit id of the record are hash keys "
          "(hashes always qualify)", got == [(1, "abcdefa"), (2, "7654321")], repr(got))

    # the record count reads the BEFORE text given, never the folder's CLAUDE.md
    wd = mk()
    write(os.path.join(wd, "CLAUDE.md"), CASE_K_FOLDER)
    write(os.path.join(wd, "TODO.md"), "# TODO\n\n- [ ] Retire `pack_tool_v9.py` after the move\n")
    wl = CASE_K_BEFORE.splitlines(keepends=True)
    wrec = [r for r in rotate.parse_records(wl, "section") if r[2] < "2026-02-01"]
    wres = open_work(wd, [], [(r[3], "".join(wl[r[0]:r[1]])) for r in wrec], CASE_K_BEFORE, "section")
    # control: the same call with the FOLDER text as before text does give the item
    wctl = open_work(wd, [], [(r[3], "".join(wl[r[0]:r[1]])) for r in wrec], CASE_K_FOLDER, "section")
    check("before text: the matcher counts records over the before text it is given (3 records: no item)",
          len(wres) == 1 and wres[0][1] == [] and len(wctl) == 1 and len(wctl[0][1]) == 1,
          "given before=%r control=%r" % (wres, wctl))

    # --todo adds a file outside the folder
    td = mk()
    tf = write(os.path.join(mk(), "elsewhere.md"), OW_TODO)
    p = write(os.path.join(td, "CLAUDE.md"), OW_CLAUDE)
    rc, out, err = run(p, *(ow + ["--apply", "--todo", tf]))
    check("open work: --todo F is read too: its open item refuses the apply (exit 3)",
          rc == 3, "rc=%d %r" % (rc, out[-300:]))

    # ============================================= one record per waiver
    for mode in ("dry run", "--apply"):
        d, p = sandbox(CASE_B_CLAUDE, CASE_B_TODO)
        before = read(p)
        args = ow + ["--move-anyway", "Gadget sorter"] + (["--apply"] if mode == "--apply" else [])
        rc, out, err = run(p, *args)
        check("one record per waiver (a) %s: --move-anyway matching two moving records exits 3, prints both titles, "
              "writes nothing" % mode,
              rc == 3 and "Gadget sorter alpha batch (2026-01-10)" in out
              and "Gadget sorter beta batch (2026-01-12)" in out
              and read(p) == before and split_dirs(d) == [],
              "rc=%d dirs=%r %r" % (rc, split_dirs(d), out[-300:]))
    d, p = sandbox(CASE_B2_CLAUDE, CASE_B2_TODO)
    rc, out, err = run(p, *(ow + ["--apply", "--move-anyway", CASE_B2_SHORT]))
    rep = read(os.path.join(d, "split_2026-02-15", "REPORT.md"))
    wl_ = [l for l in section(rep, "Waivers") if "--move-anyway" in l]
    check("one record per waiver (b) the shorter WHOLE title, also a substring of another title, waives only that record",
          rc == 0 and len(wl_) == 1 and CASE_B2_SHORT in wl_[0] and CASE_B2_LONG not in wl_[0],
          "rc=%d %r %r" % (rc, wl_, out[-300:]))

    # ================================================== empty waivers
    for value, mode in (("", "--apply"), ("   ", "--apply"), ("", "dry run")):
        d, p = sandbox(OW_CLAUDE, OW_TODO)
        snap = snapshot(d)
        args = ow + ["--move-anyway", value] + (["--apply"] if mode == "--apply" else [])
        rc, out, err = run(p, *args)
        check("empty waiver: %s --move-anyway %r exits 2 naming --move-anyway, nothing written" % (mode, value),
              rc == 2 and "--move-anyway" in out + err and snapshot(d) == snap and split_dirs(d) == [],
              "rc=%d %r" % (rc, (out + err)[-300:]))
    d, p = sandbox(OW_CLAUDE, OW_TODO)
    rc, out, err = run(p, *(ow + ["--accept", ""]))
    check("empty waiver: a dry run with --accept \"\" exits 2 naming --accept, no split_* folder",
          rc == 2 and "--accept" in out + err and split_dirs(d) == [],
          "rc=%d %r" % (rc, (out + err)[-300:]))

    # ======================================================= --accept
    # --accept is a loss-check waiver only; the rules draft still refuses the Delta rule.
    d, p = first_apply()
    after_first = read(p)
    rc, out, err = run(p, *(second + ["--accept", "ordinary PROSE"]))
    rd = os.path.join(d, "split_2026-08-16")
    rep = read(os.path.join(rd, "REPORT.dry.md"))
    w = section(rep, "Waivers")
    wi = next((i for i, l in enumerate(w)
               if "--accept" in l and "ordinary PROSE" in l and "1 item" in l), None)
    verdict = [l for l in section(rep, "Summary") if "verdict" in l]
    mr = [l for l in out.splitlines() if l.startswith("MISSING RULE: ")]
    check("--accept with a fragment of the Delta rule waives the loss-check item and is reported; "
          "the rules draft still refuses (exit 3)",
          rc == 3 and len(mr) == 1 and DELTA_RULE in mr[0]
          and wi is not None and any(DELTA_RULE in l for l in w[wi + 1:wi + 3])
          and len(verdict) == 1 and "0 blocking loss-check item(s)" in verdict[0]
          and "1 rule sentence(s) missing" in verdict[0]
          and not os.path.exists(os.path.join(rd, "REPORT.md"))
          and after_first != "" and read(p) == after_first,
          "rc=%d mr=%r waivers=%r verdict=%r" % (rc, mr, w[:6], verdict))

    for d in tmpdirs + RUN_ROOTS:
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
