#!/usr/bin/env python3
"""Write the run's RUBRIC.md: a copy of reference/rubric.md with its four <FILL: ...> marks filled.

    fill_rubric.py --out "$OUT" --tiers "<serving model, and each tier's current default>"

Each mark is matched by what it asks for, never by position: the tiers sentence from --tiers, the
compaction-keep and shared-budget sentences and the listing-cap sentence from
"$OUT/docs_caps.txt" (written by docs_caps.py in step 1), and the absolute path of
"$OUT/LAB_ADVICE.md".

Exit 0 when RUBRIC.md has no mark left; 2 when it cannot (a caps line missing, a mark it does not
know, a mark left over, an empty --tiers). Nothing is written on exit 2.
"""
import argparse
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_RUBRIC = os.path.join(HERE, "..", "reference", "rubric.md")
MARK = re.compile(r"<FILL:[^>]*>")


def caps_line(lines, key):
    for line in lines:
        if line.startswith(key + ":"):
            return line.split(": ", 1)[1].strip()
    return None


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--out", required=True, help="the run folder ($OUT)")
    ap.add_argument("--tiers", required=True, help="the serving model plus each tier's current default")
    ap.add_argument("--rubric", default=DEFAULT_RUBRIC)
    a = ap.parse_args()

    if not a.tiers.strip():
        print("CANNOT FILL: --tiers is empty", file=sys.stderr)
        return 2
    try:
        with open(os.path.join(a.out, "docs_caps.txt"), encoding="utf-8") as fh:
            caps = fh.read().splitlines()
        with open(a.rubric, encoding="utf-8") as fh:
            text = fh.read()
    except OSError as e:
        print(f"CANNOT FILL: {e}", file=sys.stderr)
        return 2

    keep, budget, listing = (caps_line(caps, k) for k in ("compaction keep", "shared budget", "listing cap"))
    missing = [k for k, v in (("compaction keep", keep), ("listing cap", listing)) if not v]
    if missing:
        print(f"CANNOT FILL: docs_caps.txt has no line for {', '.join(missing)}", file=sys.stderr)
        return 2

    fills = [
        ("serving model", a.tiers.strip()),
        ("compaction keep", keep + (" " + budget if budget else "")),
        ("listing cap", listing),
        ("LAB_ADVICE", os.path.abspath(os.path.join(a.out, "LAB_ADVICE.md"))),
    ]
    for mark in MARK.findall(text):
        hit = [v for k, v in fills if k in mark]
        if len(hit) != 1:
            print(f"CANNOT FILL: no single fill for the mark {mark!r}", file=sys.stderr)
            return 2
        text = text.replace(mark, hit[0], 1)
    if MARK.search(text):
        print("CANNOT FILL: a mark is left over", file=sys.stderr)
        return 2
    dest = os.path.join(a.out, "RUBRIC.md")
    with open(dest, "w", encoding="utf-8") as fh:
        fh.write(text)
    print(dest)
    return 0


if __name__ == "__main__":
    sys.exit(main())
