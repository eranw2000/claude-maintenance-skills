#!/usr/bin/env python3
"""Read the numbers the rubric leans on from the live Claude Code skills page.

Prints the sentence for each: the skill-listing cap (description plus when_to_use), how much
of an invoked skill survives a compaction, and the SKILL.md line guideline; the budget those
re-attached skills share is printed when the page states it, and is not required. With --json
it writes the three numbers for inventory.py --caps (keep_chars is the token figure times 4).

Exit 0 when the three were found, 2 when the page changed or could not be read (then re-read
the page by hand before trusting any cap in the rubric).
"""
import argparse
import json
import re
import subprocess
import sys

URL = "https://code.claude.com/docs/en/skills.md"
# Each number is found in a sentence that holds its clause. The page is split into sentences
# once: a sentence ends at a period followed by space, or at a line end, so the dot inside
# `SKILL.md` or a decimal does not cut one short.
REQUIRED = {
    "listing cap": r"truncated at ([\d,]+) characters",
    "compaction keep": r"keeping the first ([\d,]+) tokens",
    "line guideline": r"under (\d+) lines",
}
OPTIONAL = {"shared budget": r"combined budget of ([\d,]+) tokens"}


def fetch():
    """The page through curl, https only, one fixed address. A redirect is a refusal."""
    r = subprocess.run(["curl", "-sS", "--proto", "=https", "--max-time", "20", "-w", "\n%{http_code}", URL],
                       capture_output=True, text=True, errors="replace", check=False)
    body, _, status = r.stdout.rpartition("\n")
    if status != "200":
        raise OSError(f"HTTP {status or 'no answer'}")
    return body


def read_caps(text):
    """Returns (lines to print, numbers found, names of required sentences not found)."""
    sentences = [x.strip().lstrip("> ") for x in re.split(r"(?<=\.)\s+|\n", text)]
    lines, numbers, missing = [], {}, []
    for wanted, required in ((REQUIRED, True), (OPTIONAL, False)):
        for name, pat in wanted.items():
            hit = next((m for m in (re.search(pat, x) for x in sentences) if m), None)
            if hit:
                lines.append(f"{name}: {hit.string}")
                numbers[name] = int(hit.group(1).replace(",", ""))
            elif required:
                lines.append(f"{name}: NOT FOUND on the page (it changed; read it by hand)")
                missing.append(name)
            else:
                lines.append(f"{name}: not stated on the page")
    return lines, numbers, missing


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", help="write listing_cap, keep_chars and line_guide here")
    a = ap.parse_args()
    try:
        text = fetch()
    except Exception as exc:  # noqa: BLE001
        print(f"CANNOT READ {URL}: {type(exc).__name__}", file=sys.stderr)
        return 2
    lines, numbers, missing = read_caps(text)
    print("\n".join(lines))
    print(f"source: {URL}")
    if missing:
        return 2
    if a.json:
        with open(a.json, "w", encoding="utf-8") as fh:
            json.dump({"listing_cap": numbers["listing cap"],
                       "keep_chars": numbers["compaction keep"] * 4,
                       "line_guide": numbers["line guideline"]}, fh)
    return 0


if __name__ == "__main__":
    sys.exit(main())
