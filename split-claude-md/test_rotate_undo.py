#!/usr/bin/env python3
"""Tests for the run record and undo parts of rotate.py.

The run record: the pending manifest written through a temp file and
os.replace, the undo command printed after any failure once that
manifest exists, the one computation of every final text, the
Last-run line's format and placement and the Runs
table and entry rows at the end of their own sections.

Undo: --undo <date|dir>, dry run by default, containment with both
sides resolved, hash checks before any change, backups and
the renamed run folder kept, and the argparse rules.

Every fixture is a synthetic string built here and written to a mkdtemp
folder; every path a test hands to rotate.py, decoys included, sits under the
system temp folder, and the last check asserts that. Row 0 is a CONTROL with a
known answer: if it fails, the harness is broken rather than the script.

Run:  python3 test_rotate_undo.py
"""

import hashlib
import io
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
from contextlib import redirect_stderr, redirect_stdout

HERE = os.path.dirname(os.path.abspath(__file__))
ROTATE = os.path.join(HERE, "rotate.py")
POINTERS = os.path.join(HERE, "pointers.py")
LOSS = os.path.join(HERE, "loss_check.py")
sys.path.insert(0, HERE)
import rotate  # noqa: E402
import splitlib  # noqa: E402
import test_rotate  # noqa: E402

SECTION = test_rotate.SECTION
COLLIDING = test_rotate.COLLIDING
TEMP_ROOT = os.path.realpath(tempfile.gettempdir())
MISSING = object()

# One old record moves, one stays. No RULE_RE word anywhere.
U_CLAUDE = ("# Project\n\nPreamble text for the undo tests.\n\n"
            "## Early record about the paper tray (2026-01-07)\n\n"
            "The paper tray got a new spring during the January service visit.\n\n"
            "## Recent record about the toner (2026-03-09)\n\n"
            "The toner order moved to a new supplier in the spring.\n")
U_ARGS = ["--convention", "section", "--cut-date", "2026-02-01", "--today", "2026-02-15"]
U_RUN = "split_2026-02-15"

# Two January records: run 1 creates the archive, run 2 appends to it.
U2_CLAUDE = ("# Project\n\nPreamble text for the second-run undo tests.\n\n"
             "## First record about the coffee machine (2026-01-05)\n\n"
             "The coffee machine got a new filter holder in early January.\n\n"
             "## Second record about the kettle (2026-01-20)\n\n"
             "The kettle was moved next to the window in late January.\n\n"
             "## Third record about the fridge (2026-03-09)\n\n"
             "The fridge shelves were cleaned and relabelled in March.\n")

# (c) Last-run K value: sized so that counting the line WOULD change the K.
C_HEAD = "# Project\n\n"
C_OLD = ("## Old record about the binder (2026-01-05)\n\n"
         "The binder clips were replaced with a sturdier model.\n\n")
C_NEW = ("## New record about the stapler (2026-03-05)\n\n"
         "The stapler now takes the longer staples.\n")
C_FILL = "The office keeps spare paper in the hall cupboard near the stairs. "
C_WITHOUT_LEN = 1450

# (d) Hebrew: characters, not bytes.
H_PRE = "# פרויקט\n\nשורת פתיחה של הפרויקט בעברית.\n\n"
H_OLD = "## רשומה ישנה על המדפסת (2026-01-05)\n\nהמדפסת קיבלה מגש נייר חדש בחודש ינואר.\n\n"
H_NEW = "## רשומה חדשה על הטונר (2026-03-05)\n\nהטונר הוזמן מספק חדש באביב.\n"

# (e) the Last-run line format pair, written for real by an apply.
S_BEFORE = ("# Project\n\nPreamble text line.\n\n## Overview\n\nOverview text.\n\n"
            "## Old record (2026-01-05)\n\nOld record body text.\n\n"
            "## New record (2026-03-05)\n\nNew record body text.\n")
M_BEFORE = S_BEFORE.replace("## Overview",
                            "## Maintenance rule\n\nRotate when it grows.\n\n## Overview")

# A hand-placed Last-run line inside a dated record.
LR_OLD = ("Last split run: 2026-01-01, 1K to 1K chars, 0 records moved to "
          "`CLAUDE_DECISIONS_INDEX.md`, report split_2026-01-01/REPORT.md")
CASE_E_KEPT = ("# Project\n\nPreamble text for the stray line tests.\n\n"
            "## Old record about the shelf (2026-01-05)\n\n"
            "The shelf brackets were swapped for steel ones in January.\n\n"
            "## New record about the lamp (2026-03-05)\n\n"
            + LR_OLD + "\nThe lamp bulb was changed to a warmer colour this spring.\n")
CASE_E_MOVING = ("# Project\n\nPreamble text for the stray line tests.\n\n"
              "## Old record about the shelf (2026-01-05)\n\n"
              + LR_OLD + "\nThe shelf brackets were swapped for steel ones in January.\n\n"
              "## New record about the lamp (2026-03-05)\n\n"
              "The lamp bulb was changed to a warmer colour this spring.\n")

# Files that exist before the run, so the undo RESTOREs them.
ARCH = "CLAUDE_DECISIONS_2026-01.md"
INDEX = "CLAUDE_DECISIONS_INDEX.md"
IDX_OLD = ("# Decisions Log Index\n\n## Entries (chronological)\n\n"
           "- 2025-12-01: Older record - `CLAUDE_DECISIONS_2025-12.md`\n")
ARCH_OLD = "# Decisions Log Archive - January 2026\n\nAn older entry archived by hand in January.\n"

# A moving rule sentence makes --apply refuse (exit 3) before any write.
H_CLAUDE_RULE = U_CLAUDE.replace("The paper tray got a new spring", "Never force the paper tray. It got a new spring")

# Two Last-run lines outside every record, the second followed by a blank line.
LR_B = LR_OLD.replace("2026-01-01", "2026-01-15")
CASE_G_SECTION = ("# Project\n\n## Maintenance rule\n\n" + LR_OLD + "\n\n" + LR_B + "\n\n"
              "Rotate when it grows.\n\n## Old record (2026-01-05)\n\nOld record body text.\n\n"
              "## New record (2026-03-05)\n\nNew record body text.\n")
CASE_G_ENTRY = ("# Project\n\n## Maintenance rule\n\n" + LR_OLD + "\n\n" + LR_B + "\n\n"
            "## Decisions\n\n### Old entry (2026-01-05)\n\nOld entry body text.\n\n"
            "### New entry (2026-03-05)\n\nNew entry body text.\n")

# An existing index with a section AFTER the entries heading.
IDX_TRAIL = ("# Decisions Log Index\n\n## Entries (chronological)\n\n"
             "- 2025-12-01: Older record - `CLAUDE_DECISIONS_2025-12.md`\n\n"
             "## Trailing notes\n\nNotes that sit after the entries.\n")


def sha(data):
    if isinstance(data, str):
        data = data.encode("utf-8")
    return hashlib.sha256(data).hexdigest()


def run(path, *extra, cwd=None):
    cmd = [sys.executable, ROTATE, path] + list(extra)
    p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, cwd=cwd)
    return p.returncode, p.stdout.decode("utf-8", "replace"), p.stderr.decode("utf-8", "replace")


def run_script(script, *args):
    p = subprocess.run([sys.executable, script] + list(args), stdout=subprocess.PIPE,
                       stderr=subprocess.PIPE)
    return p.returncode, p.stdout.decode("utf-8", "replace"), p.stderr.decode("utf-8", "replace")


def inproc(argv, patches=()):
    """rotate.main() in this process with the given (object, name, value)
    patches; every patch is put back. Never raises: an exception from main()
    comes back as a string, so the check that reads it fails by name."""
    saved, buf, old_argv = [], io.StringIO(), sys.argv
    rc = None
    try:
        for obj, name, val in patches:
            saved.append((obj, name, getattr(obj, name, MISSING)))
            setattr(obj, name, val)
        sys.argv = ["rotate.py"] + list(argv)
        with redirect_stdout(buf), redirect_stderr(buf):
            try:
                rc = rotate.main()
            except SystemExit as e:
                rc = e.code if isinstance(e.code, int) else 2
            except Exception as e:                                  # noqa: BLE001
                rc = "raised %s: %s" % (type(e).__name__, e)
    finally:
        sys.argv = old_argv
        for obj, name, val in reversed(saved):
            if val is MISSING:
                delattr(obj, name)
            else:
                setattr(obj, name, val)
    return rc, buf.getvalue()


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
    with open(path, "wb" if isinstance(text, bytes) else "w",
              **({} if isinstance(text, bytes) else {"encoding": "utf-8"})) as fh:
        fh.write(text)
    return path


def ls(d):
    return sorted(os.listdir(d)) if os.path.isdir(d) else []


def split_dirs(d):
    return sorted(n for n in ls(d) if n.startswith("split_") and os.path.isdir(os.path.join(d, n)))


def snapshot(d):
    out = {}
    for root, dirs, files in os.walk(d):
        for x in dirs:
            out[os.path.relpath(os.path.join(root, x), d) + "/"] = "dir"
        for f in files:
            p = os.path.join(root, f)
            out[os.path.relpath(p, d)] = readb(p)
    return out


def manifest(d, run_name):
    try:
        return json.loads(read(os.path.join(d, run_name, "manifest.json")) or "null")
    except ValueError:
        return None


def put_manifest(d, run_name, man):
    write(os.path.join(d, run_name, "manifest.json"), json.dumps(man, indent=2))


def labelled(out, label):
    """Half-done undo message: the first shell word after `label` on every line
    that starts with it (None when the rest does not split)."""
    res = []
    for ln in out.splitlines():
        if ln.startswith(label):
            try:
                res.append(shlex.split(ln[len(label):])[0])
            except (ValueError, IndexError):
                res.append(None)
    return res


def command_after(out, label):
    """The line after each `label` line, split as a shell would split it."""
    lines = out.splitlines()
    res = []
    for i, ln in enumerate(lines):
        if ln.startswith(label):
            try:
                res.append(shlex.split(lines[i + 1]) if i + 1 < len(lines) else None)
            except ValueError:
                res.append(None)
    return res


def mv_lines(out):
    """Every printed mv command, split as a shell would split it."""
    res = []
    for ln in out.splitlines():
        if ln.strip().startswith("mv "):
            try:
                res.append(shlex.split(ln))
            except ValueError:
                res.append(None)
    return res


def run_printed(argv):
    """Run one printed command (a list) the way a person would; never raises."""
    if not argv:
        return None
    try:
        return subprocess.run(argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE).returncode
    except OSError:
        return None


def finished(d, man):
    """Every manifest file at its pre_sha256, or gone where pre_sha256 is null."""
    fs = [f for f in (man or {}).get("files", []) if isinstance(f, dict) and f.get("path")]
    if not fs:
        return False
    for f in fs:
        p = os.path.join(d, f["path"])
        if f.get("pre_sha256") is None:
            if os.path.lexists(p):
                return False
        elif readb(p) is None or sha(readb(p)) != f.get("pre_sha256"):
            return False
    return True


def last_run_lines(text):
    return [l for l in text.splitlines() if l.startswith("Last split run:")]


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


def in_span(text, line_text, convention="section"):
    """True when the line equal to line_text sits inside a parse_records span."""
    lines = text.splitlines(keepends=True)
    idx = [i for i, l in enumerate(lines) if l.rstrip("\n") == line_text]
    spans = rotate.parse_records(lines, convention)
    return bool(idx) and any(s <= i < e for i in idx for s, e, _, _ in spans)


def archive_texts(d):
    return dict((n, read(os.path.join(d, n))) for n in ls(d)
                if re.match(r"^CLAUDE_DECISIONS_\d{4}-\d{2}\.md$", n))


def index_layout(idx):
    """Every '- 20' row inside the Entries section, every '| 20' row
    between '## Runs' and the Entries heading, and the Runs table contiguous."""
    lines = idx.splitlines()
    if "## Runs" not in lines or "## Entries (chronological)" not in lines:
        return False, "a heading is missing"
    r, e = lines.index("## Runs"), lines.index("## Entries (chronological)")
    end = next((j for j in range(e + 1, len(lines)) if lines[j].startswith("## ")), len(lines))
    ent = [j for j, l in enumerate(lines) if l.startswith("- 20")]
    rws = [j for j, l in enumerate(lines) if l.startswith("| 20")]
    tbl = [j for j in range(r + 1, e) if lines[j].startswith("|")]
    ok = (r < e and ent and rws and tbl and all(e < j < end for j in ent)
          and all(r < j < e for j in rws) and tbl == list(range(tbl[0], tbl[-1] + 1)))
    return bool(ok), "runs=%d entries=%d end=%d ent=%r rws=%r tbl=%r" % (r, e, end, ent, rws, tbl)


def main():
    checks = []

    def check(name, ok, detail=""):
        if not isinstance(detail, str):
            detail = repr(detail)
        checks.append((name, bool(ok), detail))

    tmpdirs = []

    def mk():
        d = os.path.realpath(tempfile.mkdtemp(prefix="rotate-undo-"))
        tmpdirs.append(d)
        return d

    root = mk()

    def sandbox(body):
        d = mk()
        return d, write(os.path.join(d, "CLAUDE.md"), body)

    def applied(body=U_CLAUDE, args=U_ARGS):
        d, p = sandbox(body)
        rc, out, err = run(p, *(args + ["--root", root, "--apply"]))
        return d, p, rc, out + err

    def pending_colliding():
        d, p = sandbox(COLLIDING)
        rc, out, err = run(p, "--convention", "section", "--cut-date", "2026-07-01",
                           "--today", "2026-08-15", "--root", root, "--apply")
        return d, p, rc, out + err, manifest(d, "split_2026-08-15")

    # ---------------------------------------------------------------- CONTROL
    d, p = sandbox(SECTION)
    rc, out, err = run(p, "--convention", "section", "--cut-date", "2026-07-01", "--root", root)
    check("CONTROL harness runs rotate.py on the SECTION fixture and gets exit 0 and a FILE line",
          rc == 0 and out.startswith("FILE"), "rc=%d out=%r err=%r" % (rc, out[:120], err[-200:]))

    # ================================================== argparse
    d, p = sandbox(U_CLAUDE)
    rc, out, err = run(p, "--convention", "section")
    check("a non-undo call missing --cut-date exits 2 naming it with argparse's text",
          rc == 2 and "the following arguments are required: --cut-date" in err, "rc=%d %r" % (rc, err[-300:]))
    rc, out, err = run(p, "--cut-date", "2026-02-01")
    check("a non-undo call missing --convention exits 2 naming it with argparse's text",
          rc == 2 and "the following arguments are required: --convention" in err, "rc=%d %r" % (rc, err[-300:]))
    rc, out, err = run(p)
    check("a non-undo call missing both names both, in argparse's order",
          rc == 2 and "the following arguments are required: --convention, --cut-date" in err,
          "rc=%d %r" % (rc, err[-300:]))
    rc, out, err = run(p, "--undo", "split_2030-01-01")
    check("--undo <dir> alone gets past argparse (no usage text; no such run is exit 3)",
          rc == 3 and "usage:" not in err and "split_2030-01-01" in out, "rc=%d %r" % (rc, (out + err)[-300:]))
    for flag, val in (("--convention", "section"), ("--cut-date", "2026-02-01"), ("--keep", "tray"),
                      ("--hoisted", p), ("--narrative", "tray"), ("--move-anyway", "tray")):
        rc, out, err = run(p, "--undo", "split_2030-01-01", flag, val)
        check("--undo plus %s exits 2 through argparse naming %s" % (flag, flag),
              rc == 2 and "usage:" in err and flag in err, "rc=%d %r" % (rc, err[-300:]))
    d, p, rc, log = applied()
    rc, out, err = run(p, "--undo", U_RUN, "--apply", "--today", "2026-02-20")
    check("--apply and --today stay valid with --undo",
          rc == 0 and "usage:" not in err, "rc=%d %r" % (rc, (out + err)[-300:]))

    # ======================================== undo happy path
    d, p = sandbox(U_CLAUDE)
    before_files = ls(d)
    rc, out, err = run(p, *(U_ARGS + ["--root", root, "--apply"]))
    man = manifest(d, U_RUN)
    check("apply exits 0 and writes a complete manifest", rc == 0 and man and man.get("status") == "complete",
          "rc=%d man=%r %r" % (rc, man, (out + err)[-300:]))
    man = man or {}
    files = man.get("files", [])
    created = [f["path"] for f in files if f.get("pre_sha256") is None]
    backups = [(f["backup"], f["pre_sha256"]) for f in files if f.get("backup")]
    snap = snapshot(d)
    rc, out, err = run(p, "--undo", U_RUN)
    check("an undo dry run exits 0 and changes nothing", rc == 0 and snapshot(d) == snap,
          "rc=%d %r" % (rc, (out + err)[-300:]))
    check("the dry run lists every file it will RESTORE and DELETE",
          bool(created) and all(any(l.startswith("  DELETE") and c in l for l in out.splitlines()) for c in created)
          and any(l.startswith("  RESTORE") and "CLAUDE.md" in l for l in out.splitlines()),
          "created=%r %r" % (created, out[-400:]))
    rc, out, err = run(p, "--undo", U_RUN, "--apply")
    check("undo --apply exits 0", rc == 0, "rc=%d %r" % (rc, (out + err)[-300:]))
    check("undo --apply restores CLAUDE.md byte-equal", read(p) == U_CLAUDE, read(p)[:200])
    check("undo --apply deletes every created file (archive and index)",
          bool(created) and not any(os.path.exists(os.path.join(d, c)) for c in created), repr(ls(d)))
    check("every backup the manifest names still exists at its pre_sha256",
          bool(backups) and all(readb(os.path.join(d, b)) is not None
                                and sha(readb(os.path.join(d, b))) == h for b, h in backups),
          repr(backups))
    check("the run folder is renamed split_<date>.undone and keeps REPORT.md and manifest.json",
          split_dirs(d) == [U_RUN + ".undone"]
          and {"REPORT.md", "manifest.json"} <= set(ls(os.path.join(d, U_RUN + ".undone"))),
          repr(split_dirs(d)))
    check("undo touches nothing else: the folder holds the old files, the backups and the undone folder",
          ls(d) == sorted(before_files + [b for b, _ in backups] + [U_RUN + ".undone"]), repr(ls(d)))

    # ---- restore of files that existed before (second run appends)
    d, p = sandbox(U2_CLAUDE)
    rc1, o1, _ = run(p, "--convention", "section", "--cut-date", "2026-01-10", "--today", "2026-02-15",
                     "--root", root, "--apply")
    after1 = dict((n, readb(os.path.join(d, n))) for n in ls(d) if os.path.isfile(os.path.join(d, n)))
    rc2, o2, _ = run(p, "--convention", "section", "--cut-date", "2026-02-01", "--today", "2026-02-16",
                     "--root", root, "--apply")
    man2 = manifest(d, "split_2026-02-16") or {}
    restored = [f["path"] for f in man2.get("files", []) if f.get("pre_sha256")]
    rc, out, err = run(p, "--undo", "split_2026-02-16", "--apply")
    now = dict((n, readb(os.path.join(d, n))) for n in after1)
    check("undo of an appending run restores CLAUDE.md, the archive and the index byte-equal",
          rc1 == 0 and rc2 == 0 and rc == 0
          and sorted(restored) == ["CLAUDE.md", "CLAUDE_DECISIONS_2026-01.md", "CLAUDE_DECISIONS_INDEX.md"]
          and now == after1,
          "rc=%r restored=%r differ=%r %r" % ((rc1, rc2, rc), restored,
                                              [n for n in after1 if now[n] != after1[n]], (out + err)[-300:]))
    check("that undo leaves the first run's folder alone",
          "split_2026-02-15" in split_dirs(d) and "split_2026-02-16.undone" in split_dirs(d), repr(split_dirs(d)))

    # ---- apply and undo through a symlink to the project folder
    real = mk()
    link_home = mk()
    write(os.path.join(real, "CLAUDE.md"), U_CLAUDE)
    lnk = os.path.join(link_home, "proj")
    os.symlink(real, lnk)
    lp = os.path.join(lnk, "CLAUDE.md")
    rc1, o1, e1 = run(lp, *(U_ARGS + ["--root", root, "--apply"]))
    man = manifest(real, U_RUN) or {}
    rc2, o2, e2 = run(lp, "--undo", U_RUN, "--apply")
    check("the manifest's folder is the realpath of the project folder",
          man.get("folder") == real, repr(man.get("folder")))
    check("apply and undo through a symlinked folder restore byte-equal",
          rc1 == 0 and rc2 == 0 and read(os.path.join(real, "CLAUDE.md")) == U_CLAUDE
          and not os.path.exists(os.path.join(real, "CLAUDE_DECISIONS_INDEX.md")),
          "rc=%d,%d %r" % (rc1, rc2, (o2 + e2)[-300:]))

    # ================================================ refusals, complete
    d, p, rc0, log = applied()
    write(p, read(p) + "A later edit.\n")
    snap = snapshot(d)
    rc, out, err = run(p, "--undo", U_RUN, "--apply")
    check("a complete run whose CLAUDE.md was edited refuses with exit 3 naming CLAUDE.md, nothing changed",
          rc0 == 0 and rc == 3 and "CLAUDE.md" in out and snapshot(d) == snap, "rc=%d %r" % (rc, out[-300:]))
    d, p, rc0, log = applied()
    if os.path.lexists(os.path.join(d, "CLAUDE_DECISIONS_2026-01.md")):
        os.remove(os.path.join(d, "CLAUDE_DECISIONS_2026-01.md"))
    snap = snapshot(d)
    rc, out, err = run(p, "--undo", U_RUN, "--apply")
    check("a created file that is gone refuses with exit 3 naming it, no traceback, nothing changed",
          rc == 3 and "CLAUDE_DECISIONS_2026-01.md" in out and "Traceback" not in err and snapshot(d) == snap,
          "rc=%d %r %r" % (rc, out[-300:], err[-200:]))
    d, p, rc0, log = applied()
    bk = [f["backup"] for f in (manifest(d, U_RUN) or {}).get("files", []) if f.get("backup")]
    if bk:
        write(os.path.join(d, bk[0]), read(os.path.join(d, bk[0])) + "changed backup\n")
    snap = snapshot(d)
    rc, out, err = run(p, "--undo", U_RUN, "--apply")
    check("a backup not at its pre_sha256 refuses with exit 3 naming the backup, nothing changed",
          bool(bk) and rc == 3 and bk[0] in out and snapshot(d) == snap, "rc=%d %r" % (rc, out[-300:]))
    d, p, rc0, log = applied()
    bk = [f["backup"] for f in (manifest(d, U_RUN) or {}).get("files", []) if f.get("backup")]
    if bk:
        os.remove(os.path.join(d, bk[0]))
    snap = snapshot(d)
    rc, out, err = run(p, "--undo", U_RUN, "--apply")
    check("a missing backup refuses with exit 3 naming it, nothing changed",
          bool(bk) and rc == 3 and bk[0] in out and snapshot(d) == snap, "rc=%d %r" % (rc, out[-300:]))
    d, p, rc0, log = applied()
    write(os.path.join(d, U_RUN, "manifest.json"), '{"version": 1, "status": "comp')
    snap = snapshot(d)
    rc, out, err = run(p, "--undo", U_RUN, "--apply")
    check("an unreadable manifest is exit 2 (cannot tell), no traceback, nothing changed",
          rc == 2 and "Traceback" not in err and snapshot(d) == snap, "rc=%d %r %r" % (rc, out[-200:], err[-200:]))
    d, p, rc0, log = applied()
    man = manifest(d, U_RUN) or {}
    man["status"] = "half"
    put_manifest(d, U_RUN, man)
    snap = snapshot(d)
    rc, out, err = run(p, "--undo", U_RUN, "--apply")
    check("a manifest status other than pending or complete is exit 2, nothing changed",
          rc == 2 and snapshot(d) == snap, "rc=%d %r" % (rc, out[-200:]))
    d, p, rc0, log = applied()
    man = manifest(d, U_RUN) or {}
    for f in man.get("files", []):
        if f.get("path") == "CLAUDE.md":
            f["backup"] = None
    put_manifest(d, U_RUN, man)
    snap = snapshot(d)
    rc, out, err = run(p, "--undo", U_RUN, "--apply")
    check("an existing file with no backup in the manifest is exit 2, nothing changed",
          rc == 2 and snapshot(d) == snap, "rc=%d %r" % (rc, out[-200:]))

    # ---- restore verified after the copy
    d, p, rc0, log = applied()
    real_copy2 = shutil.copy2

    def bad_copy2(src, dst, *a, **k):
        r = real_copy2(src, dst, *a, **k)
        with open(dst, "a", encoding="utf-8") as fh:
            fh.write("torn\n")
        return r
    rc, out = inproc([p, "--undo", U_RUN, "--apply"], [(rotate.shutil, "copy2", bad_copy2)])
    check("a restore whose bytes do not verify exits 2 and leaves the run folder unrenamed",
          rc == 2 and U_RUN in split_dirs(d) and "CLAUDE.md" in out, "rc=%r %r" % (rc, out[-300:]))

    # ================================ half-done undo names its files (a stated limit)
    def spaced(extra):
        dd = os.path.realpath(tempfile.mkdtemp(prefix="rotate undo space-"))
        tmpdirs.append(dd)
        pp = write(os.path.join(dd, "CLAUDE.md"), U_CLAUDE)
        for name, text in extra.items():
            write(os.path.join(dd, name), text)
        rc0, o0, e0 = run(pp, *(U_ARGS + ["--root", root, "--apply"]))
        return dd, pp, rc0

    def by_path(man):
        return dict((f.get("path"), f) for f in (man or {}).get("files", []) if isinstance(f, dict))

    def nth_fails(real, n_fail, half=False):
        n = [0]

        def fake(*a, **k):
            n[0] += 1
            if n[0] == n_fail:
                if half:
                    with open(a[0], "rb") as fh:
                        data = fh.read()
                    with open(a[1], "wb") as fh:
                        fh.write(data[:len(data) // 2])
                raise OSError("injected at call %d" % n_fail)
            return real(*a, **k)
        return fake

    real_copy2 = shutil.copy2

    # first red: mixed fixture (existing index, no archive), OSError on the 2nd copy
    d, p, rc0 = spaced({INDEX: IDX_OLD})
    man = manifest(d, U_RUN)
    fs = by_path(man)
    T = dict((n, os.path.join(d, n)) for n in ("CLAUDE.md", ARCH, INDEX))
    rr = os.path.join(d, U_RUN)
    rc, out = inproc([p, "--undo", U_RUN, "--apply"], [(rotate.shutil, "copy2", nth_fails(real_copy2, 2))])
    pb, dl = labelled(out, "PUT BACK: "), labelled(out, "DELETED: ")
    npb, nd = labelled(out, "NOT PUT BACK: "), labelled(out, "NOT DELETED: ")
    cmds = command_after(out, "NOT PUT BACK: ")
    check("a half-done undo (2nd copy fails; existing index, no archive; a space in the folder) "
          "exits 2: one PUT BACK (CLAUDE.md), one NOT PUT BACK (the index) with its cp -p command, "
          "one NOT DELETED (the archive), no DELETED line, every path the quoted realpath",
          rc0 == 0 and " " in d and rc == 2 and pb == [T["CLAUDE.md"]] and npb == [T[INDEX]]
          and cmds == [["cp", "-p", os.path.join(d, (fs.get(INDEX) or {}).get("backup") or "?"), T[INDEX]]]
          and nd == [T[ARCH]] and dl == [],
          "rc=%r pb=%r npb=%r cmds=%r nd=%r dl=%r %r" % (rc, pb, npb, cmds, nd, dl, out[-500:]))
    for c in cmds:
        run_printed(c)
    for x in nd:
        if x and os.path.lexists(x):
            os.remove(x)
    mv = mv_lines(out)
    if len(mv) == 1:
        run_printed(mv[0])
    check("the hand finish works: the printed cp, the NOT DELETED file deleted and the "
          "printed mv leave every manifest file at its pre_sha256 or gone and the folder at .undone",
          len(mv) == 1 and mv[0] == ["mv", rr, rr + ".undone"] and finished(d, man)
          and split_dirs(d) == [U_RUN + ".undone"], "mv=%r dirs=%r" % (mv, split_dirs(d)))

    # twin (i): three RESTOREs, the 2nd copy writes half the file and raises
    d, p = sandbox(U_CLAUDE)
    write(os.path.join(d, ARCH), ARCH_OLD)
    write(os.path.join(d, INDEX), IDX_OLD)
    rc0, o0, e0 = run(p, *(U_ARGS + ["--root", root, "--apply"]))
    man = manifest(d, U_RUN)
    fs = by_path(man)
    T = dict((n, os.path.join(d, n)) for n in ("CLAUDE.md", ARCH, INDEX))
    rc, out = inproc([p, "--undo", U_RUN, "--apply"],
                     [(rotate.shutil, "copy2", nth_fails(real_copy2, 2, half=True))])
    pb, dl = labelled(out, "PUT BACK: "), labelled(out, "DELETED: ")
    npb, nd = labelled(out, "NOT PUT BACK: "), labelled(out, "NOT DELETED: ")
    cmds = command_after(out, "NOT PUT BACK: ")
    cut = readb(T[ARCH])
    bk_of = dict((n, os.path.join(d, (fs.get(n) or {}).get("backup") or "?")) for n in (ARCH, INDEX))
    check("a copy cut short: one PUT BACK, two NOT PUT BACK (the cut-short archive among "
          "them) each with its cp -p command, no DELETED or NOT DELETED line",
          rc0 == 0 and rc == 2 and pb == [T["CLAUDE.md"]] and npb == [T[ARCH], T[INDEX]]
          and cmds == [["cp", "-p", bk_of[ARCH], T[ARCH]], ["cp", "-p", bk_of[INDEX], T[INDEX]]]
          and dl == [] and nd == [],
          "rc=%r pb=%r npb=%r cmds=%r dl=%r nd=%r" % (rc, pb, npb, cmds, dl, nd))
    run_printed(cmds[0] if cmds else None)
    check("the cut-short archive was at neither hash, and its printed command restores it",
          cut is not None and sha(cut) not in ((fs.get(ARCH) or {}).get("pre_sha256"),
                                               (fs.get(ARCH) or {}).get("post_sha256"))
          and readb(T[ARCH]) is not None and sha(readb(T[ARCH])) == (fs.get(ARCH) or {}).get("pre_sha256"),
          "cut=%r" % (sha(cut) if cut else None))

    # twin (ii): a restore that does not verify, on U_CLAUDE (1 RESTORE, 2 created files)
    d, p, rc0, log = applied()
    man = manifest(d, U_RUN)
    fs = by_path(man)
    T = dict((n, os.path.join(d, n)) for n in ("CLAUDE.md", ARCH, INDEX))
    rr = os.path.join(d, U_RUN)

    def torn_copy2(src, dst, *a, **k):
        r = real_copy2(src, dst, *a, **k)
        with open(dst, "a", encoding="utf-8") as fh:
            fh.write("torn\n")
        return r
    rc, out = inproc([p, "--undo", U_RUN, "--apply"], [(rotate.shutil, "copy2", torn_copy2)])
    pb, dl = labelled(out, "PUT BACK: "), labelled(out, "DELETED: ")
    npb, nd = labelled(out, "NOT PUT BACK: "), labelled(out, "NOT DELETED: ")
    cmds = command_after(out, "NOT PUT BACK: ")
    mv = mv_lines(out)
    check("a restore that does not verify: one NOT PUT BACK (CLAUDE.md) with its cp -p "
          "command, two NOT DELETED, no PUT BACK or DELETED line, the folder unrenamed, and the mv line",
          rc0 == 0 and rc == 2 and npb == [T["CLAUDE.md"]]
          and cmds == [["cp", "-p", os.path.join(d, (fs.get("CLAUDE.md") or {}).get("backup") or "?"),
                        T["CLAUDE.md"]]]
          and nd == [T[ARCH], T[INDEX]] and pb == [] and dl == [] and split_dirs(d) == [U_RUN]
          and mv == [["mv", rr, rr + ".undone"]],
          "rc=%r pb=%r npb=%r nd=%r dl=%r mv=%r" % (rc, pb, npb, nd, dl, mv))
    for c in cmds:
        run_printed(c)
    for x in nd:
        if x and os.path.lexists(x):
            os.remove(x)
    run_printed(mv[0] if len(mv) == 1 else None)
    check("the hand finish works: every manifest file at its pre_sha256 or gone, the "
          "folder at its .undone name",
          finished(d, man) and split_dirs(d) == [U_RUN + ".undone"], repr(split_dirs(d)))

    # twin (iii): the folder rename fails, on U_CLAUDE; then one clash case
    def bad_rename(src, dst, *a, **k):
        raise OSError("injected at the folder rename")
    d, p, rc0, log = applied()
    T = dict((n, os.path.join(d, n)) for n in ("CLAUDE.md", ARCH, INDEX))
    rr = os.path.join(d, U_RUN)
    rc, out = inproc([p, "--undo", U_RUN, "--apply"], [(rotate.os, "rename", bad_rename)])
    pb, dl = labelled(out, "PUT BACK: "), labelled(out, "DELETED: ")
    npb, nd = labelled(out, "NOT PUT BACK: "), labelled(out, "NOT DELETED: ")
    mv = mv_lines(out)
    check("the folder rename fails: one PUT BACK, two DELETED, no NOT line, the folder "
          "keeps its name, and the mv line names <run>.undone",
          rc0 == 0 and rc == 2 and pb == [T["CLAUDE.md"]] and dl == [T[ARCH], T[INDEX]]
          and npb == [] and nd == [] and split_dirs(d) == [U_RUN] and mv == [["mv", rr, rr + ".undone"]],
          "rc=%r pb=%r dl=%r npb=%r nd=%r mv=%r" % (rc, pb, dl, npb, nd, mv))
    run_printed(mv[0] if len(mv) == 1 else None)
    rc, out2, err2 = run(p, "--undo", "2026-02-15")
    check("after the printed mv, a later --undo <date> reads the run as undone: exit 3, "
          "no run folder matches",
          rc == 3 and "no run folder with a manifest matches" in out2, "rc=%d %r" % (rc, out2[-300:]))
    d, p, rc0, log = applied()
    rr = os.path.join(d, U_RUN)
    os.makedirs(rr + ".undone")
    rc, out = inproc([p, "--undo", U_RUN, "--apply"], [(rotate.os, "rename", bad_rename)])
    check("with <run>.undone already there, the mv line names <run>.undone-2",
          rc0 == 0 and rc == 2 and mv_lines(out) == [["mv", rr, rr + ".undone-2"]], repr(mv_lines(out)))

    # twin (iv): the 2nd os.remove fails, on U_CLAUDE
    d, p, rc0, log = applied()
    man = manifest(d, U_RUN)
    T = dict((n, os.path.join(d, n)) for n in ("CLAUDE.md", ARCH, INDEX))
    rc, out = inproc([p, "--undo", U_RUN, "--apply"], [(rotate.os, "remove", nth_fails(os.remove, 2))])
    pb, dl = labelled(out, "PUT BACK: "), labelled(out, "DELETED: ")
    npb, nd = labelled(out, "NOT PUT BACK: "), labelled(out, "NOT DELETED: ")
    stars = [ln for ln in out.splitlines() if ln.startswith("***")]
    check("the 2nd delete fails: the first line says the undo stopped part way, one PUT "
          "BACK (CLAUDE.md), one DELETED (the archive), one NOT DELETED (the index), no NOT PUT BACK "
          "line, the folder keeps its name",
          rc0 == 0 and rc == 2 and bool(stars) and stars[0].startswith("*** The undo stopped part way")
          and pb == [T["CLAUDE.md"]] and dl == [T[ARCH]] and nd == [T[INDEX]] and npb == []
          and split_dirs(d) == [U_RUN],
          "rc=%r stars=%r pb=%r dl=%r nd=%r npb=%r" % (rc, stars[:1], pb, dl, nd, npb))
    for x in nd:
        if x and os.path.lexists(x):
            os.remove(x)
    check("after deleting the NOT DELETED file by hand, every manifest file is at its "
          "pre_sha256 or gone", finished(d, man), repr(ls(d)))

    # ================================================ refusals, pending
    d, p, rc, log, man = pending_colliding()
    check("the COLLIDING apply fails with exit 2 and leaves a pending manifest",
          rc == 2 and man is not None and man.get("status") == "pending", "rc=%d man=%r" % (rc, man))
    check("the failure prints the undo command beside the backup phrase",
          "Restore from the .backup-before-split" in log
          and ("rotate.py %s --undo split_2026-08-15" % p) in log, log[-400:])
    created = [f["path"] for f in (man or {}).get("files", []) if f.get("pre_sha256") is None]
    rc, out, err = run(p, "--undo", "split_2026-08-15", "--apply")
    check("--undo --apply after the failed apply restores CLAUDE.md byte-equal and removes "
          "the created archive and index",
          rc == 0 and read(p) == COLLIDING and len(created) == 2
          and not any(os.path.exists(os.path.join(d, c)) for c in created),
          "rc=%d created=%r %r" % (rc, created, (out + err)[-300:]))

    d, p, rc, log, man = pending_colliding()
    arch = os.path.join(d, "CLAUDE_DECISIONS_2026-05.md")
    write(arch, read(arch) + "A later edit.\n")
    snap = snapshot(d)
    rc, out, err = run(p, "--undo", "split_2026-08-15", "--apply")
    check("a pending manifest with a file at neither hash refuses with exit 3 naming it",
          rc == 3 and "CLAUDE_DECISIONS_2026-05.md" in out and "neither" in out and snapshot(d) == snap,
          "rc=%d %r" % (rc, out[-300:]))

    d, p, rc, log, man = pending_colliding()
    bk = [f["backup"] for f in (man or {}).get("files", []) if f.get("path") == "CLAUDE.md"]
    if bk:
        shutil.copyfile(os.path.join(d, bk[0]), p)
    os.utime(p, (1000000000, 1000000000))
    if os.path.lexists(os.path.join(d, "CLAUDE_DECISIONS_INDEX.md")):
        os.remove(os.path.join(d, "CLAUDE_DECISIONS_INDEX.md"))
    rc, out, err = run(p, "--undo", "split_2026-08-15")
    nw = [l for l in out.splitlines() if "not written" in l]
    check("the dry run reports a file still at pre_sha256 (or absent) as not written",
          rc == 0 and any("CLAUDE.md" in l for l in nw) and any("CLAUDE_DECISIONS_INDEX.md" in l for l in nw),
          "rc=%d %r" % (rc, out[-400:]))
    rc, out, err = run(p, "--undo", "split_2026-08-15", "--apply")
    check("--apply leaves a not-written file alone and undoes the rest",
          rc == 0 and os.stat(p).st_mtime == 1000000000 and read(p) == COLLIDING
          and not os.path.exists(os.path.join(d, "CLAUDE_DECISIONS_2026-05.md"))
          and not os.path.exists(os.path.join(d, "CLAUDE_DECISIONS_INDEX.md")),
          "rc=%d mtime=%r %r" % (rc, os.stat(p).st_mtime, (out + err)[-300:]))

    # ---- (f): a failure injected at step 6 (the REPORT.md writer raises)
    d, p = sandbox(U_CLAUDE)
    real_wr = getattr(rotate, "write_report", None)

    def raising_report(run_dir, name, text):
        if name == "REPORT.md":
            raise OSError("injected at step 6")
        return real_wr(run_dir, name, text)
    rc, out = inproc([p] + U_ARGS + ["--root", root, "--apply"], [(rotate, "write_report", raising_report)])
    man = manifest(d, U_RUN) or {}
    check("a failure at step 6 exits 2, prints the undo command and leaves a pending manifest",
          rc == 2 and ("--undo " + U_RUN) in out and man.get("status") == "pending",
          "rc=%r status=%r %r" % (rc, man.get("status"), out[-300:]))
    created = [f["path"] for f in man.get("files", []) if f.get("pre_sha256") is None]
    rc, out, err = run(p, "--undo", U_RUN, "--apply")
    check("--undo --apply then restores CLAUDE.md byte-equal and deletes the created archive and index",
          rc == 0 and read(p) == U_CLAUDE and len(created) == 2
          and not any(os.path.exists(os.path.join(d, c)) for c in created),
          "rc=%d created=%r %r" % (rc, created, (out + err)[-300:]))

    # ================================================ manifest writes
    wm = getattr(rotate, "write_manifest", None)
    calls = []
    real_replace = os.replace

    def raising_replace(src, dst, *a, **k):
        calls.append((src, dst))
        raise OSError("injected rename failure")
    rd = os.path.join(mk(), "split_x")
    os.makedirs(rd)
    raised = False
    os.replace = raising_replace
    try:
        if wm:
            wm(rd, {"version": 1, "status": "pending", "files": []})
    except OSError:
        raised = True
    finally:
        os.replace = real_replace
    check("with no earlier manifest, a failed os.replace leaves no manifest.json and no temp file",
          wm is not None and raised and ls(rd) == [], "raised=%r ls=%r" % (raised, ls(rd)))
    check("the manifest goes through os.replace from a temp file in the same run folder",
          len(calls) == 1 and calls[0][1] == os.path.join(rd, "manifest.json")
          and os.path.dirname(calls[0][0]) == rd and calls[0][0] != calls[0][1], repr(calls))
    prev = json.dumps({"version": 1, "status": "pending", "files": [{"path": "CLAUDE.md"}]}, indent=2)
    write(os.path.join(rd, "manifest.json"), prev)
    raised = False
    os.replace = raising_replace
    try:
        if wm:
            wm(rd, {"version": 1, "status": "complete", "files": [{"path": "CLAUDE.md"}]})
    except OSError:
        raised = True
    finally:
        os.replace = real_replace
    got = read(os.path.join(rd, "manifest.json"))
    try:
        parsed = json.loads(got)
    except ValueError:
        parsed = None
    check("a failed os.replace leaves the previous manifest whole (parses, equal bytes)",
          raised and got == prev and parsed is not None and ls(rd) == ["manifest.json"],
          "raised=%r ls=%r got=%r" % (raised, ls(rd), got[:120]))
    if wm:
        wm(rd, {"version": 1, "status": "complete", "files": []})
    check("a working os.replace writes the new manifest and leaves no temp file",
          json.loads(read(os.path.join(rd, "manifest.json")) or "{}").get("status") == "complete"
          and ls(rd) == ["manifest.json"], repr(ls(rd)))

    d, p = sandbox(U_CLAUDE)
    n = [0]

    def second_replace_fails(src, dst, *a, **k):
        n[0] += 1
        if n[0] == 2:
            raise OSError("injected at the complete write")
        return real_replace(src, dst, *a, **k)
    rc, out = inproc([p] + U_ARGS + ["--root", root, "--apply"], [(os, "replace", second_replace_fails)])
    man = manifest(d, U_RUN) or {}
    check("a failed complete write exits 2, prints the undo command, and leaves the pending manifest",
          rc == 2 and ("--undo " + U_RUN) in out and man.get("status") == "pending",
          "rc=%r status=%r %r" % (rc, man.get("status"), out[-300:]))

    # ================================================ one computation
    d, p = sandbox(SECTION)
    cnt = {"build": 0, "pick": 0}
    real_build = getattr(rotate, "build_final", None)
    real_pick = rotate.pick_run_folder

    def count_build(*a, **k):
        cnt["build"] += 1
        return real_build(*a, **k)

    def count_pick(*a, **k):
        cnt["pick"] += 1
        return real_pick(*a, **k)
    rc, out = inproc([p, "--convention", "section", "--cut-date", "2026-07-01", "--keep", "crawler",
                      "--today", "2026-08-15", "--root", root, "--apply"],
                     [(rotate, "build_final", count_build), (rotate, "pick_run_folder", count_pick)])
    lr = last_run_lines(read(p))
    m = re.search(r"report (\S+)/REPORT\.md$", lr[0]) if len(lr) == 1 else None
    named = m.group(1) if m else None
    holders = [n for n in split_dirs(d) if os.path.isfile(os.path.join(d, n, "manifest.json"))]
    check("one --apply builds the final texts once and picks the run folder once",
          rc == 0 and real_build is not None and cnt == {"build": 1, "pick": 1}, "rc=%r cnt=%r" % (rc, cnt))
    check("the folder named in the Last-run line is the folder holding manifest.json",
          named is not None and holders == [named], "named=%r holders=%r" % (named, holders))

    # ================================================ Last-run line format
    d, p, rc, log = applied()
    text = read(p)
    lr = last_run_lines(text)
    ptrs = splitlib.pointers(text, d, [root], None, None) if lr else []
    ln = (text.splitlines().index(lr[0]) + 1) if lr else -1
    hit = [x for x in ptrs if x.token == "CLAUDE_DECISIONS_INDEX.md" and x.lineno == ln]
    prc, pout, perr = run_script(POINTERS, p, "--root", root)
    check("pointers.py reads the written Last-run line as a resolved pointer to the index",
          rc == 0 and len(hit) == 1 and hit[0].status == "RESOLVED" and prc == 0,
          "rc=%d hit=%r prc=%d %r" % (rc, hit, prc, pout[-200:]))

    d, p = sandbox(U_CLAUDE)
    write(os.path.join(d, U_RUN, "notes.md"), "hand notes\n")
    rc, out, err = run(p, *(U_ARGS + ["--root", root, "--apply"]))
    lr = last_run_lines(read(p))
    check("a run in split_<today>-2 ends the line 'report split_<today>-2/REPORT.md', split_ once",
          rc == 0 and len(lr) == 1 and lr[0].endswith("report %s-2/REPORT.md" % U_RUN)
          and lr[0].count("split_") == 1, repr(lr))

    target = C_WITHOUT_LEN - len(C_HEAD) - len("\n\n") - len(C_NEW)
    fill = (C_FILL * (target // len(C_FILL) + 2))[:target]
    c_body = C_HEAD + fill + "\n\n" + C_OLD + C_NEW
    without = C_HEAD + fill + "\n\n" + C_NEW
    d, p = sandbox(c_body)
    rc, out, err = run(p, *(U_ARGS + ["--root", root, "--apply"]))
    lr = last_run_lines(read(p))
    rows = runs_rows(read(os.path.join(d, "CLAUDE_DECISIONS_INDEX.md")))
    cells = [c.strip() for c in rows[0].strip("|").split("|")] if len(rows) == 1 else []
    k_with = (len(without) + (len(lr[0]) + 2 if lr else 0) + 500) // 1000
    check("precondition: counting the line would change the K value",
          len(without) == C_WITHOUT_LEN and lr and k_with != (len(without) + 500) // 1000,
          "without=%d k_with=%d" % (len(without), k_with))
    check("<after> is (len(final text without the line) + 500) // 1000, <before> likewise",
          rc == 0 and len(lr) == 1 and (" %dK to %dK chars," % ((len(c_body) + 500) // 1000,
                                                              (len(without) + 500) // 1000)) in lr[0],
          "rc=%d %r" % (rc, lr))
    check("the Runs row carries Before and After exact",
          len(cells) == 5 and cells[1] == str(len(c_body)) and cells[2] == str(len(without)),
          "cells=%r want %d %d" % (cells, len(c_body), len(without)))

    h_body = H_PRE + H_OLD + H_NEW
    d, p = sandbox(h_body)
    rc, out, err = run(p, *(U_ARGS + ["--root", root, "--apply"]))
    rows = runs_rows(read(os.path.join(d, "CLAUDE_DECISIONS_INDEX.md")))
    cells = [c.strip() for c in rows[0].strip("|").split("|")] if len(rows) == 1 else []
    check("the Hebrew fixture's Runs row Before and After are characters, not bytes",
          rc == 0 and len(cells) == 5 and cells[1] == str(len(h_body)) and cells[2] == str(len(H_PRE + H_NEW))
          and len(h_body) != len(h_body.encode("utf-8")),
          "rc=%d cells=%r want %d %d" % (rc, cells, len(h_body), len(H_PRE + H_NEW)))

    for label, body, placement in (("(3)", S_BEFORE, 3), ("(2)", M_BEFORE, 2)):
        d, p = sandbox(body)
        rc, out, err = run(p, *(U_ARGS + ["--root", root, "--apply"]))
        after = read(p)
        lines = after.splitlines()
        lr = last_run_lines(after)
        i = lines.index(lr[0]) if len(lr) == 1 else -1
        where = (i > 0 and lines[i - 1] == "## Maintenance rule") if placement == 2 else \
            (i >= 0 and i + 2 < len(lines) and lines[i + 1] == "" and lines[i + 2].startswith("## New record"))
        bk = os.path.join(d, "CLAUDE.md.backup-before-split-2026-02-15")
        lrc, lout, lerr = run_script(LOSS, "--before", bk, "--after", p, "--structure")
        check("placement %s: the line sits where the data model puts it and "
              "loss_check.py --structure exits 0 on it" % label,
              rc == 0 and where and lrc == 0, "rc=%d where=%r lrc=%d %r" % (rc, where, lrc, lout[-300:]))

    # ================================================ placement
    d, p = sandbox(SECTION)
    rc, out, err = run(p, "--convention", "section", "--cut-date", "2026-07-01", "--keep", "crawler",
                       "--today", "2026-08-15", "--root", root, "--apply")
    after = read(p)
    lr = last_run_lines(after)
    check("SECTION, no Maintenance heading: the written line belongs to no parse_records span",
          rc == 0 and len(lr) == 1 and not in_span(after, lr[0]), "rc=%d %r" % (rc, lr))
    eof = after.rstrip("\n") + "\n" + (lr[0] if lr else LR_OLD) + "\n"
    check("control: the same assertion on an EOF-placed line reads it inside a span",
          in_span(eof, lr[0] if lr else LR_OLD), "")
    rc2, out2, err2 = run(p, "--convention", "section", "--cut-date", "2026-09-01", "--today", "2026-08-16",
                          "--narrative", "Delta record", "--root", root, "--apply")
    arch = archive_texts(d)
    check("two runs, the second moving the last record: 'Last split run' is 0 in every archive "
          "and 1 in CLAUDE.md",
          rc2 == 0 and len(arch) == 3 and all(t.count("Last split run") == 0 for t in arch.values())
          and read(p).count("Last split run") == 1,
          "rc=%d counts=%r claude=%d %r" % (rc2, dict((k, v.count("Last split run")) for k, v in arch.items()),
                                            read(p).count("Last split run"), out2[-300:]))

    for label, body in (("KEPT", CASE_E_KEPT), ("MOVING", CASE_E_MOVING)):
        d, p = sandbox(body)
        rc, out, err = run(p, *(U_ARGS + ["--root", root, "--apply"]))
        after = read(p)
        arch = archive_texts(d)
        lr = last_run_lines(after)
        check("a Last-run line inside a %s dated record is moved out: exit 0, presence checks "
              "pass, 0 in every archive, 1 in CLAUDE.md, outside every span" % label,
              rc == 0 and "All presence checks passed" in out and len(arch) == 1
              and all(t.count("Last split run") == 0 for t in arch.values())
              and after.count("Last split run") == 1 and len(lr) == 1 and not in_span(after, lr[0]),
              "rc=%d claude=%d arch=%r %r" % (rc, after.count("Last split run"),
                                              [t.count("Last split run") for t in arch.values()], out[-300:]))

    for label, body, conv, edited in (("SECTION", CASE_G_SECTION, "section", []),
                                      ("ENTRY", CASE_G_ENTRY, "entry", ["--edited", "## Decisions"])):
        d, p = sandbox(body)
        rc, out, err = run(p, "--convention", conv, "--cut-date", "2026-02-01", "--today", "2026-02-15",
                           "--root", root, "--apply")
        after = read(p)
        bk = os.path.join(d, "CLAUDE.md.backup-before-split-2026-02-15")
        lrc, lout, lerr = run_script(LOSS, "--before", bk, "--after", p, "--structure", *edited)
        check("%s fixture with two Last-run lines outside every record (a blank after the second): "
              "--apply leaves exactly one, presence checks pass, loss_check --structure exits 0" % label,
              rc == 0 and "All presence checks passed" in out and len(last_run_lines(after)) == 1
              and last_run_lines(after)[0].startswith("Last split run: 2026-02-15") and lrc == 0,
              "rc=%d lrc=%d %r %r" % (rc, lrc, last_run_lines(after), (out + lout)[-300:]))

    d, p = sandbox(U_CLAUDE)
    snap = snapshot(d)
    real_place = rotate.place_last_run

    def place_twice(lines, placement, i, line):
        out_lines = real_place(lines, placement, i, line)
        out_lines.insert(i + 1, LR_OLD + "\n")
        return out_lines
    rc, out = inproc([p] + U_ARGS + ["--root", root, "--apply"], [(rotate, "place_last_run", place_twice)])
    check("the internal assertion: a second Last-run line in the final text exits 2, nothing written, "
          "no split_* folder", rc == 2 and snapshot(d) == snap and split_dirs(d) == [],
          "rc=%r %r" % (rc, out[-300:]))

    for mode in ("dry run", "--apply"):
        d, p = sandbox(U_CLAUDE)
        snap = snapshot(d)

        def bad_slot(lines, convention):
            spans = rotate.parse_records(lines, convention)
            s = spans[-1][0]
            return 3, s + 1
        argv = [p] + U_ARGS + ["--root", root] + (["--apply"] if mode == "--apply" else [])
        rc, out = inproc(argv, [(rotate, "last_run_slot", bad_slot)])
        check("%s: a placement inside a kept record's span exits 2, nothing written, no split_* folder"
              % mode, rc == 2 and snapshot(d) == snap and split_dirs(d) == [], "rc=%r %r" % (rc, out[-300:]))

    # ================================================ Runs table and entry rows
    d, p = sandbox(U2_CLAUDE)
    write(os.path.join(d, "CLAUDE_DECISIONS_INDEX.md"), IDX_TRAIL)
    rc, out, err = run(p, "--convention", "section", "--cut-date", "2026-01-10", "--today", "2026-02-15",
                       "--root", root, "--apply")
    lines = read(os.path.join(d, "CLAUDE_DECISIONS_INDEX.md")).splitlines()
    ent = [i for i, l in enumerate(lines) if l.startswith("- 2026-01-05")]
    e = lines.index("## Entries (chronological)") if "## Entries (chronological)" in lines else -1
    t = lines.index("## Trailing notes") if "## Trailing notes" in lines else -1
    check("with a section after Entries, the new entry row sits between the Entries heading and it",
          rc == 0 and len(ent) == 1 and e < ent[0] < t and lines[-1] == "Notes that sit after the entries.",
          "rc=%d e=%d ent=%r t=%d %r" % (rc, e, ent, t, lines[-6:]))
    rc2, out2, err2 = run(p, "--convention", "section", "--cut-date", "2026-02-01", "--today", "2026-02-16",
                          "--root", root, "--apply")
    ok, why = index_layout(read(os.path.join(d, "CLAUDE_DECISIONS_INDEX.md")))
    check("two runs on that index: rows in their own sections, Runs table contiguous",
          rc2 == 0 and ok and len(runs_rows(read(os.path.join(d, "CLAUDE_DECISIONS_INDEX.md")))) == 2,
          "rc=%d %s" % (rc2, why))
    d, p = sandbox(U2_CLAUDE)
    rc1, _, _ = run(p, "--convention", "section", "--cut-date", "2026-01-10", "--today", "2026-02-15",
                    "--root", root, "--apply")
    rc2, _, _ = run(p, "--convention", "section", "--cut-date", "2026-02-01", "--today", "2026-02-16",
                    "--root", root, "--apply")
    ok, why = index_layout(read(os.path.join(d, "CLAUDE_DECISIONS_INDEX.md")))
    check("two runs on a new index: every '- 20' row under Entries, every '| 20' row under Runs, "
          "no non-'|' line inside the Runs table", rc1 == 0 and rc2 == 0 and ok, why)

    # ================================================ undo by date
    d, p, rc0, log = applied()
    rc, out, err = run(p, "--undo", "2026-02-15", "--apply")
    check("one match by date is used", rc0 == 0 and rc == 0 and read(p) == U_CLAUDE
          and split_dirs(d) == [U_RUN + ".undone"], "rc=%d %r" % (rc, (out + err)[-300:]))
    rc, out, err = run(p, "--undo", "2026-02-15")
    check("an undone folder never matches its date again (exit 3)", rc == 3, "rc=%d %r" % (rc, out[-200:]))
    d, p, rc0, log = applied()
    snap = snapshot(d)
    rc, out, err = run(p, "--undo", "2030-01-01", "--apply")
    check("no folder for the date exits 3, nothing changed", rc == 3 and snapshot(d) == snap,
          "rc=%d %r" % (rc, out[-200:]))
    write(os.path.join(d, "split_2026-02-15-2", "notes.md"), "a hand folder with no manifest\n")
    snap = snapshot(d)
    rc, out, err = run(p, "--undo", "2026-02-15")
    check("a same-date folder with no manifest is no match (one match, dry run exit 0)",
          rc == 0 and snapshot(d) == snap and "split_2026-02-15-2" not in out, "rc=%d %r" % (rc, out[-200:]))
    d, p = sandbox(U2_CLAUDE)
    rc1, _, _ = run(p, "--convention", "section", "--cut-date", "2026-01-10", "--today", "2026-02-15",
                    "--root", root, "--apply")
    rc2, _, _ = run(p, "--convention", "section", "--cut-date", "2026-02-01", "--today", "2026-02-15",
                    "--root", root, "--apply")
    snap = snapshot(d)
    rc, out, err = run(p, "--undo", "2026-02-15", "--apply")
    check("two matches exit 3, list both and ask for --undo <dir>, no file changed",
          rc1 == 0 and rc2 == 0 and rc == 3 and "split_2026-02-15\n" in out + "\n"
          and "split_2026-02-15-2" in out and "--undo <dir>" in out and snapshot(d) == snap,
          "rc=%r %r" % ((rc1, rc2, rc), out[-300:]))
    d, p = sandbox(U_CLAUDE)
    ok = True
    for _ in range(2):
        rca, _, _ = run(p, *(U_ARGS + ["--root", root, "--apply"]))
        rcu, ou, _ = run(p, "--undo", "2026-02-15", "--apply")
        ok = ok and rca == 0 and rcu == 0
    check("apply, undo, apply, undo: both undone folders survive (.undone and .undone-2)",
          ok and split_dirs(d) == [U_RUN + ".undone", U_RUN + ".undone-2"] and read(p) == U_CLAUDE,
          "ok=%r dirs=%r" % (ok, split_dirs(d)))
    snap = snapshot(d)
    rc, out, err = run(p, "--undo", U_RUN + ".undone", "--apply")
    check("--undo naming an already undone folder exits 3, nothing changed",
          rc == 3 and snapshot(d) == snap, "rc=%d %r" % (rc, out[-200:]))
    d, p = sandbox(U_CLAUDE)
    rca, _, _ = run(p, *(U_ARGS + ["--root", root, "--apply"]))
    rcu, _, _ = run(p, "--undo", U_RUN, "--apply")
    rcb, _, _ = run(p, *(U_ARGS + ["--root", root, "--apply"]))
    snap = snapshot(d)
    rc, out, err = run(p, "--undo", U_RUN + ".undone", "--apply")
    check("an undone folder is refused by name even when a later identical run put every "
          "file back at its hashes (exit 3, nothing changed)",
          (rca, rcu, rcb) == (0, 0, 0) and rc == 3 and snapshot(d) == snap,
          "rc=%r %r" % ((rca, rcu, rcb, rc), out[-200:]))
    d, p, rc0, log = applied()
    other = mk()
    shutil.copytree(os.path.join(d, U_RUN), os.path.join(other, U_RUN))
    sa, sb = snapshot(d), snapshot(other)
    rc, out, err = run(p, "--undo", os.path.join(other, U_RUN), "--apply")
    check("--undo naming a run folder outside the project folder exits 3, both folders unchanged",
          rc0 == 0 and rc == 3 and snapshot(d) == sa and snapshot(other) == sb,
          "rc=%d %r" % (rc, out[-200:]))

    # ---- a manifest.json in the project folder itself is never a run folder
    d, p, rc0, log = applied()
    if os.path.isfile(os.path.join(d, U_RUN, "manifest.json")):
        shutil.copyfile(os.path.join(d, U_RUN, "manifest.json"), os.path.join(d, "manifest.json"))
    snap = snapshot(d)
    rc, out, err = run(p, "--undo", ".", "--apply")
    check("--undo naming the project folder itself exits 3, even with a manifest.json there",
          rc0 == 0 and rc == 3 and snapshot(d) == snap and os.path.isdir(d), "rc=%d %r" % (rc, out[-200:]))

    # ---- a directory where the manifest names a file
    d, p, rc0, log = applied()
    if os.path.lexists(os.path.join(d, "CLAUDE_DECISIONS_INDEX.md")):
        os.remove(os.path.join(d, "CLAUDE_DECISIONS_INDEX.md"))
    os.makedirs(os.path.join(d, "CLAUDE_DECISIONS_INDEX.md"))
    snap = snapshot(d)
    rc, out, err = run(p, "--undo", U_RUN, "--apply")
    check("a directory in place of a manifest file refuses with exit 3 naming it, no traceback",
          rc == 3 and "CLAUDE_DECISIONS_INDEX.md" in out and "Traceback" not in err and snapshot(d) == snap,
          "rc=%d %r %r" % (rc, out[-200:], err[-200:]))

    # ---- malformed manifests: cannot tell (exit 2), never a crash, nothing changed
    def bad_files(man, how):
        fs = man.get("files", [])
        if how == "no files":
            man["files"] = []
        elif how == "files not a list":
            man["files"] = "CLAUDE.md"
        elif how == "an entry not a mapping":
            fs[0] = "CLAUDE.md"
        elif how == "an entry with no path":
            del fs[0]["path"]
        elif how == "an entry with no post_sha256":
            del fs[0]["post_sha256"]
        elif how == "a pre_sha256 that is a number":
            fs[0]["pre_sha256"] = 5
        elif how == "a backup that is a number":
            fs[0]["backup"] = 7
        elif how in ("a created entry with no backup key", "a created entry with no pre_sha256 key"):
            made = [f for f in fs if isinstance(f, dict) and "pre_sha256" in f and f["pre_sha256"] is None]
            if made:
                del made[0]["backup" if "backup key" in how else "pre_sha256"]
    for how in ("no files", "files not a list", "an entry not a mapping", "an entry with no path",
                "an entry with no post_sha256", "a pre_sha256 that is a number", "a backup that is a number",
                "a created entry with no backup key", "a created entry with no pre_sha256 key"):
        d, p, rc0, log = applied()
        man = manifest(d, U_RUN) or {"files": [{"path": "CLAUDE.md", "pre_sha256": None,
                                                 "post_sha256": "0" * 64, "backup": None}]}
        bad_files(man, how)
        put_manifest(d, U_RUN, man)
        snap = snapshot(d)
        rc, out, err = run(p, "--undo", U_RUN, "--apply")
        check("a manifest with %s is exit 2, no traceback, nothing changed" % how,
              rc0 == 0 and rc == 2 and "Traceback" not in err and snapshot(d) == snap,
              "rc=%d %r %r" % (rc, out[-200:], err[-200:]))

    # ---- undo reads that fail before any change: exit 2, nothing changed
    real_sha = splitlib.sha256
    for label, hit in (("a target", lambda x: os.path.basename(x) == "CLAUDE.md"),
                       ("a backup", lambda x: ".backup-before-split-" in os.path.basename(x))):
        d, p, rc0, log = applied()
        snap = snapshot(d)

        def locked_sha(x, hit=hit):
            if hit(x):
                raise PermissionError(13, "Permission denied", x)
            return real_sha(x)
        rc, out = inproc([p, "--undo", U_RUN, "--apply"], [(splitlib, "sha256", locked_sha)])
        check("undo --apply with %s that cannot be read for its hash exits 2 naming it "
              "unreadable (PermissionError), nothing changed, the folder not renamed" % label,
              rc0 == 0 and rc == 2 and "is unreadable (PermissionError)" in out and snapshot(d) == snap
              and split_dirs(d) == [U_RUN], "rc=%r %r" % (rc, out[-300:]))
    gone = os.path.join(mk(), "no-such-folder", "CLAUDE.md")
    rc, out, err = run(gone, "--undo", "2026-02-15", "--apply")
    check("--undo --apply with a CLAUDE.md under a folder that does not exist exits 2 with "
          "'CANNOT TELL: folder missing: ', no traceback",
          rc == 2 and any(l.startswith("CANNOT TELL: folder missing: ") for l in out.splitlines())
          and "Traceback" not in err, "rc=%d %r %r" % (rc, out[-200:], err[-200:]))
    d, p, rc0, log = applied()
    snap = snapshot(d)
    listed = []

    def locked_listdir(x, *a, **k):
        listed.append(x)
        raise PermissionError(13, "Permission denied", x)
    rc, out = inproc([p, "--undo", "2026-02-15", "--apply"], [(rotate.os, "listdir", locked_listdir)])
    check("--undo <date> --apply on a folder that cannot be listed exits 2 saying it is "
          "unreadable (PermissionError), no traceback, nothing changed, the listing was called",
          rc0 == 0 and rc == 2 and bool(listed) and "is unreadable (PermissionError)" in out
          and snapshot(d) == snap, "rc=%r listed=%r %r" % (rc, listed, out[-300:]))

    # ---- a notes-set file rotate.py cannot read: exit 2 before any write
    for mode in ("dry run", "--apply"):
        d, p = sandbox(U_CLAUDE)
        locked = write(os.path.join(d, "NOTES.md"), "Plain notes line.\n")
        os.chmod(locked, 0)
        unreadable = not os.access(locked, os.R_OK)
        rc, out, err = run(p, *(U_ARGS + ["--root", root] + (["--apply"] if mode == "--apply" else [])))
        os.chmod(locked, 0o644)
        check("%s with a notes file that cannot be opened (mode 000) exits 2 naming it, no "
              "traceback, CLAUDE.md unchanged, no run folder" % mode,
              unreadable and rc == 2 and "NOTES.md" in out and "Traceback" not in err
              and read(p) == U_CLAUDE and split_dirs(d) == [],
              "unreadable=%r rc=%d %r %r" % (unreadable, rc, out[-300:], err[-200:]))
    d, p = sandbox(U_CLAUDE)
    write(os.path.join(d, "NOTES.md"), b"Notes caf\xe9 line\n")
    rc, out, err = run(p, *(U_ARGS + ["--root", root]))
    lrc, lout, lerr = run_script(LOSS, "--before", p, "--after", p)
    check("a dry run with a notes file that is not UTF-8 exits 2 naming it, as loss_check.py "
          "does on the same folder, no run folder",
          rc == 2 and "NOTES.md" in out and "Traceback" not in err and lrc == 2 and split_dirs(d) == [],
          "rc=%d lrc=%d %r" % (rc, lrc, out[-300:]))

    # ---- a write before the pending manifest fails: exit 2, leftovers named
    def bad_makedirs(x, *a, **k):
        raise PermissionError(13, "Permission denied", x)
    d, p = sandbox(U_CLAUDE)
    rc, out = inproc([p] + U_ARGS + ["--root", root], [(rotate.os, "makedirs", bad_makedirs)])
    check("a dry run whose run folder cannot be made exits 2, no traceback, CLAUDE.md unchanged, "
          "and says CLAUDE.md, the archives and the index were not written",
          rc == 2 and "Traceback" not in out and read(p) == U_CLAUDE and "were not written" in out,
          "rc=%r %r" % (rc, out[-300:]))
    d, p = sandbox(H_CLAUDE_RULE)
    rc, out = inproc([p] + U_ARGS + ["--root", root, "--apply"], [(rotate.os, "makedirs", bad_makedirs)])
    check("a refused --apply whose REPORT.dry.md cannot be written exits 2, not 3",
          rc == 2 and "Traceback" not in out and read(p) == H_CLAUDE_RULE, "rc=%r %r" % (rc, out[-300:]))
    d, p = sandbox(U_CLAUDE)
    write(os.path.join(d, INDEX), IDX_OLD)
    real_copy2 = shutil.copy2
    n2 = [0]

    def second_backup_fails(src, dst, *a, **k):
        n2[0] += 1
        if n2[0] == 2:
            raise OSError("injected at the 2nd backup")
        return real_copy2(src, dst, *a, **k)
    rc, out = inproc([p] + U_ARGS + ["--root", root, "--apply"], [(rotate.shutil, "copy2", second_backup_fails)])
    first_bk = os.path.join(d, "CLAUDE.md.backup-before-split-2026-02-15")
    fail_line = next((l for l in out.splitlines() if l.startswith("CANNOT TELL: ")), "")
    check("a backup that fails on --apply exits 2, no traceback, CLAUDE.md and the index unchanged, "
          "the run folder and the backup already made named and left in place",
          rc == 2 and "Traceback" not in out and read(p) == U_CLAUDE and read(os.path.join(d, INDEX)) == IDX_OLD
          and os.path.isdir(os.path.join(d, U_RUN)) and os.path.isfile(first_bk)
          and os.path.join(d, U_RUN) in fail_line and first_bk in fail_line
          and not os.path.exists(os.path.join(d, U_RUN, "manifest.json")),
          "rc=%r %r" % (rc, out[-400:]))

    # ---- an index with no Entries heading, and one with no final newline
    d, p = sandbox(U_CLAUDE)
    write(os.path.join(d, "CLAUDE_DECISIONS_INDEX.md"), "# Decisions Log Index\n\nA hand index with no sections.\n")
    rc, out, err = run(p, *(U_ARGS + ["--root", root, "--apply"]))
    ok, why = index_layout(read(os.path.join(d, "CLAUDE_DECISIONS_INDEX.md")))
    check("an index with no Entries heading gets Runs then Entries, each row in its own section",
          rc == 0 and ok, "rc=%d %s %r" % (rc, why, (out + err)[-200:]))
    d, p = sandbox(U_CLAUDE)
    old_row = "- 2025-12-01: Older record - `CLAUDE_DECISIONS_2025-12.md`"
    write(os.path.join(d, "CLAUDE_DECISIONS_INDEX.md"),
          "# Decisions Log Index\n\n## Entries (chronological)\n\n" + old_row)
    rc, out, err = run(p, *(U_ARGS + ["--root", root, "--apply"]))
    lines = read(os.path.join(d, "CLAUDE_DECISIONS_INDEX.md")).splitlines()
    check("an index whose last entry row has no newline keeps that row whole; the new row is its own line",
          rc == 0 and old_row in lines and any(l.startswith("- 2026-01-07: ") for l in lines),
          "rc=%d %r" % (rc, lines[-3:]))

    # ---- the line not where its placement says
    d, p = sandbox(M_BEFORE)
    snap = snapshot(d)

    def eof_place(lines, placement, i, line):
        return list(lines) + [line + "\n"]
    rc, out = inproc([p] + U_ARGS + ["--root", root, "--apply"], [(rotate, "place_last_run", eof_place)])
    check("a Last-run line placed anywhere but its slot exits 2, nothing written, no split_* folder",
          rc == 2 and snapshot(d) == snap and split_dirs(d) == [], "rc=%r %r" % (rc, out[-300:]))

    # ---- a KEPT fragment failure after the pending manifest prints the undo command
    KEPT_DUP = ("# Project\n\nThe lamp bulb was changed to a warmer colour this spring, near the desk.\n\n"
                "## Old record about the shelf (2026-01-05)\n\n"
                "The shelf brackets were swapped for steel ones in January.\n\n"
                "## New record about the lamp (2026-03-05)\n\n"
                "The lamp bulb was changed to a warmer colour this spring, near the desk.\n")
    d, p = sandbox(KEPT_DUP)
    rc, out, err = run(p, *(U_ARGS + ["--root", root, "--apply"]))
    check("a kept-fragment failure exits 2, prints FAIL kept and the undo command",
          rc == 2 and "FAIL kept" in out and ("--undo " + U_RUN) in out
          and (manifest(d, U_RUN) or {}).get("status") == "pending", "rc=%d %r" % (rc, out[-300:]))

    # ---- step 5: CLAUDE.md re-read at a hash other than the one written
    d, p = sandbox(U_CLAUDE)
    real_sha = splitlib.sha256
    seen = []

    def drifting_sha(path):
        h = real_sha(path)
        if os.path.basename(path) == "CLAUDE.md":
            seen.append(path)
            if len(seen) >= 2:
                return "0" * 64
        return h
    rc, out = inproc([p] + U_ARGS + ["--root", root, "--apply"], [(splitlib, "sha256", drifting_sha)])
    check("step 5: CLAUDE.md not at its written hash exits 2 and prints the undo command",
          rc == 2 and "not at the hash this run wrote" in out and ("--undo " + U_RUN) in out
          and (manifest(d, U_RUN) or {}).get("status") == "pending", "rc=%r %r" % (rc, out[-300:]))

    # ================================================ containment
    def escape_case(label, mutate_manifest, prefix_sibling=False):
        a = mk()
        if prefix_sibling:
            b = a + "-sibling"
            os.makedirs(b)
            tmpdirs.append(b)
        else:
            b = mk()
        p = write(os.path.join(a, "CLAUDE.md"), U_CLAUDE)
        rc0, _, _ = run(p, *(U_ARGS + ["--root", root, "--apply"]))
        man = manifest(a, U_RUN) or {"files": []}
        named = mutate_manifest(a, b, man)
        put_manifest(a, U_RUN, man)
        sa, sb = snapshot(a), snapshot(b)
        try:
            rc, out, err = run(p, "--undo", U_RUN, "--apply")
            check("%s: exit 3 naming the path, every decoy in B and every file in A unchanged" % label,
                  rc0 == 0 and rc == 3 and named in out and snapshot(a) == sa and snapshot(b) == sb,
                  "rc=%d named=%r %r" % (rc, named, out[-300:]))
        finally:
            shutil.rmtree(a, ignore_errors=True)
            shutil.rmtree(b, ignore_errors=True)

    def rel(a, x):
        return os.path.relpath(x, a)

    for how in ("relative", "absolute"):
        def created_escape(a, b, man, how=how):
            decoy = write(os.path.join(b, "decoy_created.md"), "decoy created file\n")
            path = rel(a, decoy) if how == "relative" else decoy
            man["files"].append({"path": path, "pre_sha256": None,
                                 "post_sha256": sha("decoy created file\n"), "backup": None})
            return path
        escape_case("(a) %s created-file entry into B" % how, created_escape)

        def both_escape(a, b, man, how=how):
            tgt = write(os.path.join(b, "target.md"), "target bytes in B\n")
            bkp = write(os.path.join(b, "backup_decoy.md"), "backup decoy bytes\n")
            path = rel(a, tgt) if how == "relative" else tgt
            man["files"].append({"path": path, "pre_sha256": sha("backup decoy bytes\n"),
                                 "post_sha256": sha("target bytes in B\n"),
                                 "backup": rel(a, bkp) if how == "relative" else bkp})
            return path
        escape_case("(b) %s backup entry and restore target in B" % how, both_escape)

        def backup_escape(a, b, man, how=how):
            bkp = write(os.path.join(b, "claude_backup.md"), U_CLAUDE)
            path = rel(a, bkp) if how == "relative" else bkp
            for f in man["files"]:
                if f.get("path") == "CLAUDE.md":
                    f["backup"] = path
            return path
        escape_case("(b2) %s CLAUDE.md's backup in B" % how, backup_escape)

        def path_escape(a, b, man, how=how):
            tgt = write(os.path.join(b, "target.md"), "target bytes in B\n")
            write(os.path.join(a, "inside_backup.md"), "inside backup bytes\n")
            path = rel(a, tgt) if how == "relative" else tgt
            man["files"].append({"path": path, "pre_sha256": sha("inside backup bytes\n"),
                                 "post_sha256": sha("target bytes in B\n"), "backup": "inside_backup.md"})
            return path
        escape_case("(b3) %s restore target in B, backup in A" % how, path_escape)

    def link_escape(a, b, man):
        write(os.path.join(b, "x.md"), "decoy behind a link\n")
        os.symlink(b, os.path.join(a, "lnk"))
        man["files"].append({"path": "lnk/x.md", "pre_sha256": None,
                             "post_sha256": sha("decoy behind a link\n"), "backup": None})
        return "lnk/x.md"
    escape_case("(c) a path through a symlink in A that resolves into B", link_escape)

    def prefix_escape(a, b, man):
        decoy = write(os.path.join(b, "decoy_created.md"), "decoy created file\n")
        man["files"].append({"path": rel(a, decoy), "pre_sha256": None,
                             "post_sha256": sha("decoy created file\n"), "backup": None})
        return rel(a, decoy)
    escape_case("(d) a created-file entry in a sibling folder whose name starts with A's name",
                prefix_escape, prefix_sibling=True)

    # ------------------------------------------------- the sandbox fence itself
    check("every folder this file used sits under the system temp folder",
          bool(tmpdirs) and all(os.path.commonpath([t, TEMP_ROOT]) == TEMP_ROOT for t in tmpdirs),
          repr([t for t in tmpdirs if os.path.commonpath([t, TEMP_ROOT]) != TEMP_ROOT]))

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
