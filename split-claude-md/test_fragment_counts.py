#!/usr/bin/env python3
"""Tests for the fragment counts and the predicted fragment check (rotate.py).

A moved fragment passes when its count in its archive after the run MINUS its
count in that archive before the run is exactly 1, and its count in the
CLAUDE.md move result is 0; a kept fragment passes at exactly 1 in CLAUDE.md.
Every report and every dry run states the verdict --apply will reach
(FRAGMENT CHECK, predicted); the prediction is never an exit, and the check
over the WRITTEN archives still decides --apply.

Every fixture here is rule-free and has no TODO file, so only the fragment
check can stop an apply. Fixtures are synthetic strings written to mkdtemp
folders. Row 0 is a CONTROL with a known answer: if it fails, the harness is
broken rather than the code.

Run:  python3 test_fragment_counts.py
"""

import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from contextlib import redirect_stderr, redirect_stdout

HERE = os.path.dirname(os.path.abspath(__file__))
ROTATE = os.path.join(HERE, "rotate.py")
sys.path.insert(0, HERE)
import rotate  # noqa: E402
import splitlib  # noqa: E402
import test_rotate  # noqa: E402
import test_rotate_rules as trr  # noqa: E402

SECTION = test_rotate.SECTION
COLLIDING = test_rotate.COLLIDING
ARGS = ["--convention", "section", "--cut-date", "2026-07-01", "--today", "2026-08-15"]
RUN = "split_2026-08-15"
ALPHA = "## Alpha record about the widget engine (2026-05-03)"
ALPHA_BODY = "This is the alpha body line, which is comfortably longer than forty chars."
EPSILON = "## Epsilon record about the token budget (2026-05-20)"
BETA = "## Beta record concerning the crawler (2026-06-11)"
MAY = "CLAUDE_DECISIONS_2026-05.md"
JUNE = "CLAUDE_DECISIONS_2026-06.md"
KEPT_DUP = ("# Project\n\nThe lamp bulb was changed to a warmer colour this spring, near the desk.\n\n"
            "## Old record about the shelf (2026-01-05)\n\n"
            "The shelf brackets were swapped for steel ones in January.\n\n"
            "## New record about the lamp (2026-03-05)\n\n"
            "The lamp bulb was changed to a warmer colour this spring, near the desk.\n")
KD_ARGS = ["--convention", "section", "--cut-date", "2026-02-01", "--today", "2026-02-15"]
MISSING = object()
NOTE_RE = re.compile(r"NOTE: (\d+) moved fragment\(s\) were already in their archive before this "
                     r"run; each was checked as exactly one more copy\.")
PRED_RE = re.compile(r"^FRAGMENT CHECK \(predicted for --apply\): (\d+) fragment\(s\), "
                     r"(\d+) failure\(s\)$")
SUMMARY_RE = re.compile(r"^- fragment check predicted for --apply: (\d+) fragment\(s\), "
                        r"(\d+) failure\(s\)$")


def run(path, *extra):
    p = subprocess.run([sys.executable, ROTATE, path] + list(extra),
                       stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    return p.returncode, p.stdout.decode("utf-8", "replace") + p.stderr.decode("utf-8", "replace")


def inproc(argv, patches=()):
    """rotate.main() in this process with (object, name, value) patches, every
    patch put back. An exception comes back as a string, never raised."""
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


def write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)
    return path


def manifest(d):
    try:
        return json.loads(read(os.path.join(d, RUN, "manifest.json")) or "null") or {}
    except ValueError:
        return {}


def pred(out):
    m = [PRED_RE.match(l) for l in out.splitlines()]
    m = [x for x in m if x]
    return (int(m[0].group(1)), int(m[0].group(2))) if len(m) == 1 else None


def lines_starting(out, prefix):
    return [l for l in out.splitlines() if l.strip().startswith(prefix)]


def notes(out):
    return [int(m.group(1)) for m in (NOTE_RE.search(l) for l in out.splitlines()) if m]


def record_text(lines, title):
    for s, e, dt, t in rotate.parse_records(lines, "section"):
        if t.startswith(title):
            return "".join(lines[s:e]).rstrip("\n") + "\n\n"
    return None


def double_record(title, name):
    """A build_final that appends one moving record to its archive twice."""
    real = rotate.build_final

    def fake(lines, *a, **k):
        fin = real(lines, *a, **k)
        fin.arch_final[name] = fin.arch_final[name] + record_text(lines, title)
        return fin
    return fake


def drop_record(title, name):
    """A build_final that leaves one moving record out of its archive."""
    real = rotate.build_final

    def fake(lines, *a, **k):
        fin = real(lines, *a, **k)
        txt = record_text(lines, title)
        assert txt and txt in fin.arch_final[name]
        fin.arch_final[name] = fin.arch_final[name].replace(txt, "", 1)
        return fin
    return fake


def doubling_open(name):
    """An open() for rotate's namespace that writes the named archive's text twice."""
    real_open = open

    class Twice(object):
        def __init__(self, fh):
            self.fh = fh

        def write(self, text):
            self.fh.write(text)
            return self.fh.write(text)

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            self.fh.close()

    def fake(path, mode="r", *a, **k):
        fh = real_open(path, mode, *a, **k)
        if "w" in mode and os.path.basename(str(path)) == name:
            return Twice(fh)
        return fh
    return fake


def main():
    checks = []

    def check(name, ok, detail=""):
        if not isinstance(detail, str):
            detail = repr(detail)
        checks.append((name, bool(ok), detail))

    tmpdirs = []

    def mk():
        d = os.path.realpath(tempfile.mkdtemp(prefix="frag-counts-"))
        tmpdirs.append(d)
        return d

    root = mk()

    def sandbox(body, archives=()):
        d = mk()
        for n, t in archives:
            write(os.path.join(d, n), t)
        return d, write(os.path.join(d, "CLAUDE.md"), body)

    # ---------------------------------------------------------------- CONTROL
    d, p = sandbox(SECTION)
    rc, out = run(p, *(ARGS + ["--root", root, "--apply"]))
    check("CONTROL the SECTION fixture's first --apply exits 0", rc == 0, "rc=%d %r" % (rc, out[-300:]))

    # ---------------------------------------------------------------- F1, F2, F3
    for label, arch, want_title in (
            ("F1 the archive already holds the moving title once",
             "# Archive\n\n" + ALPHA + "\n\nEvidence notes for the alpha record sit here.\n", 2),
            ("F2 the archive already holds the moving title three times",
             "# Archive\n\n" + "".join(ALPHA + "\n\nEvidence notes, copy %d.\n\n" % i for i in (1, 2, 3)), 4),
            ("F3 the record's first long body line is already in the archive under another heading",
             "# Archive\n\n## Earlier evidence about the widgets\n\n" + ALPHA_BODY + "\n", None)):
        d, p = sandbox(SECTION, [(MAY, arch)])
        rc, out = run(p, *(ARGS + ["--root", root]))
        pr = pred(out)
        check(label + ": the dry run predicts 0 failure(s)", rc == 0 and pr is not None and pr[1] == 0,
              "rc=%d pred=%r" % (rc, pr))
        rc, out = run(p, *(ARGS + ["--root", root, "--apply"]))
        after = read(os.path.join(d, MAY))
        ok_count = (after.count(ALPHA) == want_title) if want_title else (after.count(ALPHA_BODY) == 2)
        check(label + ": --apply exits 0, the VERIFY NOTE counts 1 fragment already archived, "
              "and the archive holds one more copy",
              rc == 0 and notes(out) == [1] and ok_count,
              "rc=%d notes=%r title=%d body=%d %r" % (rc, notes(out), after.count(ALPHA),
                                                      after.count(ALPHA_BODY), out[-300:]))

    # ---------------------------------------------------------------- F4a
    d, p = sandbox(SECTION)
    patch = [(rotate, "build_final", double_record(BETA, JUNE))]
    rc, out = inproc([p] + ARGS + ["--root", root], patch)
    pl = [l for l in lines_starting(out, "PREDICTED FAIL moved") if BETA[:40] in l]
    check("F4a build_final appending a record twice: the dry run predicts two PREDICTED FAIL "
          "moved lines for that title and 2 failure(s)",
          rc == 0 and len(pl) == 2 and (pred(out) or (0, -1))[1] == 2, "rc=%r pred=%r %r" % (rc, pred(out), pl))
    rc, out = inproc([p] + ARGS + ["--root", root, "--apply"], patch)
    fl = [l for l in lines_starting(out, "FAIL moved") if BETA[:40] in l]
    check("F4a --apply exits 2 with two FAIL moved lines for that title, the undo command and "
          "a pending manifest",
          rc == 2 and len(fl) == 2 and ("--undo " + RUN) in out
          and manifest(d).get("status") == "pending", "rc=%r %r %r" % (rc, fl, out[-300:]))

    # ---------------------------------------------------------------- F4b
    d, p = sandbox(SECTION)
    patch = [(rotate, "open", doubling_open(JUNE))]
    rc, out = inproc([p] + ARGS + ["--root", root], patch)
    check("F4b only the written archive doubled: the dry run predicts 0 failure(s)",
          rc == 0 and (pred(out) or (0, -1))[1] == 0, "rc=%r pred=%r" % (rc, pred(out)))
    rc, out = inproc([p] + ARGS + ["--root", root, "--apply"], patch)
    check("F4b --apply exits 2 with FAIL moved (step 4 reads the written archive)",
          rc == 2 and any(BETA[:40] in l for l in lines_starting(out, "FAIL moved")),
          "rc=%r %r" % (rc, out[-400:]))

    # ---------------------------------------------------------------- F5
    d, p = sandbox(SECTION)
    before = read(p)
    patch = [(rotate, "build_final", drop_record(EPSILON, MAY))]
    rc, out = inproc([p] + ARGS + ["--root", root], patch)
    check("F5a a record left out of its archive: the dry run prints PREDICTED FAIL moved "
          "(difference 0) and exits 0",
          rc == 0 and any(EPSILON[:40] in l and "arch=0 before=0" in l
                          for l in lines_starting(out, "PREDICTED FAIL moved")),
          "rc=%r %r" % (rc, lines_starting(out, "PREDICTED")))
    shutil.rmtree(os.path.join(d, RUN), ignore_errors=True)
    rc, out = inproc([p] + ARGS + ["--root", root, "--apply"], patch)
    check("F5a --apply without a waiver exits 3 with NOWHERE: <that heading> and writes "
          "nothing but REPORT.dry.md",
          rc == 3 and ("NOWHERE: " + EPSILON) in out and read(p) == before
          and sorted(os.listdir(d)) == ["CLAUDE.md", RUN]
          and os.listdir(os.path.join(d, RUN)) == ["REPORT.dry.md"],
          "rc=%r %r %r" % (rc, sorted(os.listdir(d)), out[-300:]))
    d, p = sandbox(SECTION)
    rc, out = inproc([p] + ARGS + ["--root", root, "--apply", "--accept", EPSILON], patch)
    check("F5b with --accept of that heading, --apply exits 2 with FAIL moved arch=0 before=0 "
          "claude=0, the undo command and a pending manifest",
          rc == 2 and any(EPSILON[:40] in l and "FAIL moved  arch=0 before=0 claude=0" in l
                          for l in lines_starting(out, "FAIL moved"))
          and ("--undo " + RUN) in out and manifest(d).get("status") == "pending",
          "rc=%r %r" % (rc, out[-400:]))

    # ---------------------------------------------------------------- F6
    d, p = sandbox(COLLIDING)
    rc, out = run(p, *(ARGS + ["--root", root]))
    pl = lines_starting(out, "PREDICTED FAIL moved")
    check("F6 COLLIDING: the dry run exits 0 with one PREDICTED FAIL moved line",
          rc == 0 and len(pl) == 1 and "Old record that is going to move" in pl[0],
          "rc=%d %r" % (rc, pl))
    summ = [m for m in (SUMMARY_RE.match(l) for l in read(os.path.join(d, RUN, "REPORT.dry.md")).splitlines())
            if m]
    check("F6 REPORT.dry.md's Summary carries the predicted fragment check with 1 failure(s)",
          len(summ) == 1 and summ[0].group(2) == "1",
          [m.group(0) for m in summ])
    rc, out = run(p, *(ARGS + ["--root", root, "--apply"]))
    check("F6 --apply exits 2 with FAIL moved for the same title",
          rc == 2 and any("Old record that is going to move" in l for l in lines_starting(out, "FAIL moved")),
          "rc=%d %r" % (rc, out[-300:]))
    d, p = sandbox(KEPT_DUP)
    rc, out = run(p, *(KD_ARGS + ["--root", root]))
    check("F6 a kept record whose body line also sits in the preamble: the dry run predicts "
          "PREDICTED FAIL kept", rc == 0 and len(lines_starting(out, "PREDICTED FAIL kept")) == 1,
          "rc=%d %r" % (rc, lines_starting(out, "PREDICTED")))

    # ---------------------------------------------------------------- F7
    d, p = sandbox(trr.V1_CLAUDE)
    rc, out = run(p, *(trr.BASE + ["--root", root]))
    dl = [l for l in out.splitlines() if trr.DRAFT_RE.match(l)]
    write(p, trr.hoist(read(p), dl[0] if dl else "- (no draft line)"))
    shutil.rmtree(os.path.join(d, "split_2026-02-15"), ignore_errors=True)
    rc1, out1 = run(p, *(trr.BASE + ["--root", root]))
    rc2, out2 = run(p, *(trr.BASE + ["--root", root, "--apply"]))
    check("F7 after the paste the dry run prints 0 KEPT-RULE FRAGMENT SKIPPED lines and "
          "--apply prints exactly 2",
          rc1 == 0 and len(trr.skipped(out1)) == 0 and rc2 == 0 and len(trr.skipped(out2)) == 2,
          "rc=%d/%d dry=%d apply=%d" % (rc1, rc2, len(trr.skipped(out1)), len(trr.skipped(out2))))

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
