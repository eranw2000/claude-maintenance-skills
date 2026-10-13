#!/usr/bin/env python3
"""Run EVERY test file in this skill, plus goal_check.py, and report one honest total.

It discovers the sibling test files by glob, runs each in its own process, parses each file's own
"N/M passed" line, and FAILS if any file reports nothing. Then it runs goal_check.py (the frozen
acceptance scenarios), which the test_*.py glob does not match: it counts as one check, passes
only on exit 0 with a "GOAL HOLDS" line, and a run with no verdict line is BROKEN.

Run:  python3 run_tests.py
"""

import glob
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
TALLY = re.compile(r"(\d+)/(\d+) passed")
GOAL = os.path.join(HERE, "goal_check.py")


def main():
    files = sorted(f for f in glob.glob(os.path.join(HERE, "test_*.py")))
    if not files:
        print("NO test files found. The runner is broken, not the code.")
        return 1

    total_ok = total_all = 0
    broken = []
    for f in files:
        p = subprocess.run([sys.executable, f], capture_output=True, text=True,
                           cwd=HERE)
        m = TALLY.search(p.stdout)
        name = os.path.basename(f)
        if not m:
            broken.append(name)
            print("  %-32s NO TALLY (rc=%d) -- cannot be counted" % (name, p.returncode))
            if p.stderr.strip():
                print("      " + p.stderr.strip().splitlines()[-1][:150])
            continue
        ok, all_ = int(m.group(1)), int(m.group(2))
        total_ok += ok
        total_all += all_
        flag = "" if ok == all_ else "   <-- FAILURES"
        print("  %-32s %s/%s%s" % (name, ok, all_, flag))
        if ok != all_:
            for line in p.stdout.splitlines():
                if line.strip().startswith("FAILED"):
                    print("      " + line.strip())

    n_files = len(files)
    if os.path.isfile(GOAL):
        n_files += 1
        p = subprocess.run([sys.executable, GOAL], capture_output=True, text=True, cwd=HERE)
        verdict = [l for l in p.stdout.splitlines() if l.startswith(("GOAL HOLDS", "GOAL NOT MET"))]
        if not verdict:
            broken.append("goal_check.py")
            print("  %-32s NO VERDICT (rc=%d) -- cannot be counted" % ("goal_check.py", p.returncode))
        else:
            held = p.returncode == 0 and verdict[-1].startswith("GOAL HOLDS")
            total_all += 1
            total_ok += held
            print("  %-32s %s%s" % ("goal_check.py", verdict[-1][:60], "" if held else "   <-- FAILURES"))
            if not held:
                for line in p.stdout.splitlines():
                    if " FAIL " in line:
                        print("      " + line.strip()[:150])

    print("")
    print("TOTAL %d/%d across %d test files" % (total_ok, total_all, n_files))
    if broken:
        print("BROKEN: %s reported no tally, so the total above is INCOMPLETE."
              % ", ".join(broken))
        return 1
    if total_all == 0:
        print("The suite ran ZERO checks. That is a harness bug, not a clean run.")
        return 1
    return 0 if total_ok == total_all else 1


if __name__ == "__main__":
    sys.exit(main())
