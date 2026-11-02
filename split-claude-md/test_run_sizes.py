#!/usr/bin/env python3
"""Tests for the sizes a run writes down and the floor its report carries.

A run's Last-run line and Runs row name the size it STARTED from and the size it
ended at. rotate.py runs after the hoist, so the file on disk is not the start:
the run's first backup is. Phase D edits after rotate.py, so rotate.py's after
figure is out of date once Phase D writes. And a dry-run report states
survey.py's estimate of how low the result can go, so the person is told that
figure.

Fixtures are synthetic strings in mkdtemp folders. Row 0 is a CONTROL with a known
answer: if it fails, the harness is broken rather than the code.

Run:  python3 test_run_sizes.py
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

# Read and write UTF-8 on every OS: the Windows default code page misreads it.
if __name__ == "__main__":
    for _stream in (sys.stdin, sys.stdout, sys.stderr):
        if hasattr(_stream, "reconfigure"):
            _stream.reconfigure(encoding="utf-8", errors="replace")

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import phase_d  # noqa: E402
import rotate  # noqa: E402

TODAY = "2026-08-15"
COMPACT = "20260815"
ARGS = ["--convention", "section", "--cut-date", "2026-07-01", "--today", TODAY]
FILLER = "plain words about the widget engine and its layout " * 100   # about 5,100 chars
STORY = "A story sentence that says what happened on the day."
ORIGINAL = ("# Project\n\n## Notes\n\n" + FILLER.strip() + " " + STORY + "\n\n"
            "## Alpha record about the widget engine (2026-05-03)\n\n"
            "This is the alpha body line, which is comfortably longer than forty chars.\n\n"
            "## Beta record about the crawler (2026-08-10)\n\n"
            "This is the beta body line, which is also comfortably longer than forty chars.\n")
# What the file looks like after the hoist: bigger than the run's real start.
HOIST = "## Live design hoisted here\n\n" + "plain hoisted words about the crawler pages " * 80 + "\n\n"
HOISTED = ORIGINAL.replace("## Alpha record", HOIST + "## Alpha record")


def write(path, text):
    with open(path, "w", encoding="utf-8", newline="") as fh:
        fh.write(text)
    return path


def read(path):
    with open(path, encoding="utf-8", newline="") as fh:
        return fh.read()


def run(path, *args):
    p = subprocess.run([sys.executable, os.path.join(HERE, "rotate.py"), path] + list(args),
                       capture_output=True, text=True, cwd=os.path.dirname(path))
    return p.returncode, p.stdout + p.stderr


def last_run(text):
    return [ln for ln in text.splitlines() if ln.startswith("Last split run:")]


def runs_row(folder):
    rows = [ln for ln in read(os.path.join(folder, rotate.INDEX_NAME)).splitlines()
            if ln.startswith("| " + TODAY)]
    return rows[-1] if rows else ""


def k(n):
    return "%dK" % ((n + 500) // 1000)


def main():
    checks = []

    def check(name, ok, detail=""):
        if not isinstance(detail, str):
            detail = repr(detail)
        checks.append((name, bool(ok), detail))

    tmpdirs = []

    def mk(text=HOISTED):
        d = os.path.realpath(tempfile.mkdtemp(prefix="run-sizes-"))
        tmpdirs.append(d)
        return d, write(os.path.join(d, "CLAUDE.md"), text)

    # ---- 0 control: with no backup the start is the file as it stands
    d, p = mk(ORIGINAL)
    rc, out = run(p, *ARGS, "--apply")
    line = (last_run(read(p)) or [""])[0]
    check("0 control: no backup, so the start is the file on disk (exit 0, %s)" % k(len(ORIGINAL)),
          rc == 0 and (", %s to " % k(len(ORIGINAL))) in line, "rc=%d %r %s" % (rc, line, out[-300:]))

    # ---- 1 the main case: the hoist makes the file bigger than the run's start
    d, p = mk()
    write(p + ".backup-before-split-" + COMPACT, ORIGINAL)
    rc, out = run(p, *ARGS, "--apply")
    line = (last_run(read(p)) or [""])[0]
    check("1 Last-run line starts from the first backup, not the hoisted file",
          rc == 0 and (", %s to " % k(len(ORIGINAL))) in line
          and k(len(ORIGINAL)) != k(len(HOISTED)), "rc=%d %r" % (rc, line))
    row = runs_row(d)
    check("1 Runs row's Before is the first backup's exact size",
          ("| %d |" % len(ORIGINAL)) in row and ("| %d |" % len(HOISTED)) not in row, row)
    report = read(os.path.join(d, "split_%s" % TODAY, "REPORT.md"))
    check("1 the report names the backup the start came from",
          ("chars before %d" % len(ORIGINAL)) in report
          and ("CLAUDE.md.backup-before-split-" + COMPACT) in report, report[:400])

    # ---- 2 rotate.py's own backups use the dashed date and are taken mid-run,
    # after the hoist, so they must never be read as the start
    d, p = mk()
    write(p + ".backup-before-split-" + TODAY, ORIGINAL)
    rc, out = run(p, *ARGS, "--apply")
    line = (last_run(read(p)) or [""])[0]
    check("2 a dashed backup (rotate's own) is not the start",
          rc == 0 and (", %s to " % k(len(HOISTED))) in line, "rc=%d %r" % (rc, line))

    # ---- 3 a second run the same day takes the -2 backup, and that is its start
    d, p = mk()
    write(p + ".backup-before-split-" + COMPACT, "# An older, much larger start\n" + FILLER * 5)
    write(p + ".backup-before-split-" + COMPACT + "-2", ORIGINAL)
    rc, out = run(p, *ARGS, "--apply")
    check("3 the highest same-day suffix is this run's start",
          rc == 0 and ("| %d |" % len(ORIGINAL)) in runs_row(d), runs_row(d))

    # ---- 4 the estimate is in the report and on screen, read from survey.py
    d, p = mk()
    rc, out = run(p, *ARGS)
    dry = read(os.path.join(d, "split_%s" % TODAY, "REPORT.dry.md"))
    m = re.search(r"how low this file can go.*?about (\d+) chars with evidence moved out, about (\d+) chars", dry)
    # the same run applied in a twin folder gives the very file the estimate is about
    d2, p2 = mk()
    run(p2, *ARGS, "--apply")
    sv = subprocess.run([sys.executable, os.path.join(HERE, "survey.py"), p2, "--keep-days", "30"],
                        capture_output=True, text=True).stdout
    want = re.findall(r"^  ESTIMATE(?: AFTER PHASE E)?\s+~(\d+) ch", sv, re.M)
    check("4 the dry-run report states survey.py's two estimates for the result",
          m is not None and len(want) == 2 and [m.group(1), m.group(2)] == want,
          "%r vs %r\n%s" % (m and m.groups(), want, dry[:500]))
    check("4 the dry run prints it too, since a report is not always read whole",
          "how low this file can go" in out, out[-400:])
    check("4 it is labelled a rough guess, never a limit",
          m is not None and "rough guess" in m.group(0) and "rough guess" in out, dry[:500])

    # ---- 5 no estimate is a stated third answer, and it never stops the run
    line5 = rotate.floor_line("# text\n", survey_path=os.path.join(HERE, "no_such_survey.py"))
    check("5 a survey that cannot run says cannot tell and offers no figure",
          "cannot tell" in line5 and not re.search(r"about \d+ chars", line5), line5)

    fake = write(os.path.join(d, "fake_survey.py"),
                 "print('  ESTIMATE  ~111 ch (~27 tokens), a 9% cut')\n"
                 "print('  ESTIMATE AFTER PHASE E  ~222 ch (~55 tokens), a 8% cut')\n")
    line5b = rotate.floor_line("# text\n", survey_path=fake)
    check("5 each estimate lands under its own label",
          "about 111 chars with evidence moved out, about 222 chars" in line5b, line5b)

    # ---- 6 Phase D moves the end size, so it rewrites the two records of it
    d, p = mk()
    write(p + ".backup-before-split-" + COMPACT, ORIGINAL)
    rc, out = run(p, *ARGS, "--apply")
    body = [ln for ln in read(p).splitlines() if ln.startswith("plain words about")][0]
    spec = write(os.path.join(d, "spec.json"), json.dumps({"cuts": [{
        "heading": "## Notes", "prefix": "plain words about", "mode": "join", "archive": "2026-08",
        "drops": [body[:2600]]}]}))
    os.makedirs(os.path.join(d, "root"))
    before_d = read(p)
    args = [p, "--spec", spec, "--today", TODAY, "--no-backup", "--root", os.path.join(d, "root"),
            "--accept", "plain words"]
    out_buf = io.StringIO()
    with redirect_stdout(out_buf), redirect_stderr(out_buf):
        rc_d = phase_d.main(args)
    unchanged = read(p) == before_d
    out_buf2 = io.StringIO()
    with redirect_stdout(out_buf2), redirect_stderr(out_buf2):
        rc_w = phase_d.main(args + ["--write"])
    now = read(p)
    without = "".join(ln for ln in now.splitlines(True) if not ln.startswith("Last split run:"))
    line = (last_run(now) or [""])[0]
    check("6 a Phase D dry run writes nothing", rc_d == 0 and unchanged, out_buf.getvalue()[-300:])
    check("6 Phase D rewrites the Last-run line's end size",
          rc_w == 0 and (" to %s chars," % k(len(without))) in line
          and (", %s to " % k(len(ORIGINAL))) in line
          and k(len(without)) != k(len(before_d)),
          "rc=%d %r %s" % (rc_w, line, out_buf2.getvalue()[-300:]))
    row = runs_row(d)
    check("6 Phase D rewrites the Runs row's After and leaves its Before",
          ("| %d | %d |" % (len(ORIGINAL), len(without))) in row, row)

    # ---- 7 a Last-run line and a Runs row from another day are history
    d, p = mk(ORIGINAL)
    old_line = "Last split run: 2026-01-01, 9K to 8K chars, 1 records moved to `%s`, report x/REPORT.md" % rotate.INDEX_NAME
    text = ORIGINAL.replace("## Notes\n\n", "## Notes\n\n" + old_line + "\n\n", 1)
    old_row = "| 2026-01-01 | 9000 | 8000 | 1 | x/REPORT.md |"
    index = "# Index\n\n## Runs\n\n| Date | Before | After | Records | Report |\n| --- | --- | --- | --- | --- |\n%s\n" % old_row
    writes = {p: text, os.path.join(d, rotate.INDEX_NAME): index}
    got = phase_d.refresh_run_sizes(dict(writes), p, TODAY)
    check("7 another day's line and row stay as written",
          got[p] == text and got[os.path.join(d, rotate.INDEX_NAME)] == index, got[p][:200])
    fenced = text.replace(old_line, "```\nLast split run: %s, 9K to 8K chars, 1 records moved\n```" % TODAY)
    got = phase_d.refresh_run_sizes({p: fenced}, p, TODAY)
    check("7 a fenced example of today's line stays as written", got[p] == fenced, got[p][:200])

    for t in tmpdirs:
        shutil.rmtree(t, ignore_errors=True)

    if not checks:
        print("0/0 passed -- the harness ran NO checks, which is a harness bug")
        return 1
    failed = [c for c in checks if not c[1]]
    for name, ok, detail in checks:
        if not ok:
            print("  FAILED " + name)
            print("         " + re.sub(r"(\d+)/(\d+) passed", r"\1 of \2 passed",
                                       detail.replace("\n", "\n         "))[:500])
    print("%d/%d passed" % (len(checks) - len(failed), len(checks)))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
