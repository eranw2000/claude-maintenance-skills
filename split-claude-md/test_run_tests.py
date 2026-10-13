#!/usr/bin/env python3
"""Tests for run_tests.py: the suite total must include goal_check.py.

Each case copies run_tests.py into a mkdtemp folder with ONE passing test file
and a fake goal_check.py, so nothing here runs the real suite (and run_tests.py
never finds this file again, so it cannot recurse). Row 0 is a CONTROL with a
known answer.

Run:  python3 test_run_tests.py
"""

import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
RUNNER = os.path.join(HERE, "run_tests.py")
OK_TEST = 'print("1/1 passed")\n'

RESULTS = []


def check(name, cond, detail=""):
    RESULTS.append((name, bool(cond)))
    if not cond:
        print("FAILED %s %s" % (name, detail[-400:]))


def run_with(goal_src):
    d = tempfile.mkdtemp(prefix="run_tests_test_")
    shutil.copy(RUNNER, d)
    with open(os.path.join(d, "test_ok.py"), "w") as fh:
        fh.write(OK_TEST)
    if goal_src is not None:
        with open(os.path.join(d, "goal_check.py"), "w") as fh:
            fh.write(goal_src)
    p = subprocess.run([sys.executable, os.path.join(d, "run_tests.py")],
                       capture_output=True, text=True)
    shutil.rmtree(d)
    return p.returncode, p.stdout + p.stderr


def main():
    rc, out = run_with('import sys\nprint("GOAL HOLDS: every frozen scenario passes")\nsys.exit(0)\n')
    check("00 CONTROL: a holding goal_check and a passing test exit 0", rc == 0, out)
    check("00 the goal_check line is reported", "goal_check.py" in out and "GOAL HOLDS" in out, out)

    rc, out = run_with('import sys\nprint("SCENARIO 4  FAIL  x")\nprint("GOAL NOT MET: failing 4")\nsys.exit(3)\n')
    check("01 a failing goal_check makes the run fail", rc != 0, out)
    check("01 and names it", "goal_check.py" in out and "GOAL NOT MET" in out, out)

    rc, out = run_with('import sys\nsys.exit(0)\n')
    check("02 a goal_check that prints no verdict is BROKEN, not a pass",
          rc != 0 and "goal_check.py" in out, out)

    rc, out = run_with('import sys\nprint("GOAL HOLDS: every frozen scenario passes")\nsys.exit(3)\n')
    check("03 a verdict line that disagrees with the exit status fails", rc != 0, out)

    rc, out = run_with(None)
    check("04 a folder with no goal_check.py still runs the tests and exits 0", rc == 0, out)

    ok = sum(1 for _, r in RESULTS if r)
    print("%d/%d passed" % (ok, len(RESULTS)))
    return 0 if ok == len(RESULTS) else 1


if __name__ == "__main__":
    sys.exit(main())
