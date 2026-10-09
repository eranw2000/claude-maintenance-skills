#!/usr/bin/env python3
"""Run EVERY test file in this skill and report one honest total.

It discovers the sibling test files by glob, runs each in its own process, parses each file's own
"N/M passed" line, and FAILS if any file reports nothing.

Run:  python3 run_tests.py
"""

import glob
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
TALLY = re.compile(r"(\d+)/(\d+) passed")


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

    print("")
    print("TOTAL %d/%d across %d test files" % (total_ok, total_all, len(files)))
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
