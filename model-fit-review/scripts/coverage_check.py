#!/usr/bin/env python3
"""Check that every skill, agent and command received a verdict in the reader slice files.

Usage: coverage_check.py --root ~/.claude --slices <folder with slice_*.md>

A file counts as covered only when a slice file has a heading naming its root-relative path
(`### skills/<name>/SKILL.md (...)`, agents/<f>.md, commands/<f>.md) and a verdict word (KEEP,
TRIM, REWRITE, RETIRE) in that section: a `Verdict: TRIM` line before the next heading, or the
one-line form for small files, `### <path> (5,829; model: opus): KEEP (...)`.
In that form the word must come right after the size note, so `(chars: TRIM later)` is no verdict.
A path mentioned in prose, or a pasted list of paths, is not a verdict. The artifact list is inventory.py's own, so the two
scripts cannot disagree on what the review covers; what it leaves out is printed.

Exit 0 when all are covered, 1 when any is missing (each printed as MISSING), 2 when there are
no slice files or no artifacts, so an empty read can never pass.
"""
import argparse
import glob
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import inventory  # noqa: E402

HEADING_RE = re.compile(r"^#{2,4} +`?([\w./-]+\.md)`?(?=[\s(,:;]|$)")
ANY_HEADING_RE = re.compile(r"^#{1,6} ")
WORDS = r"(KEEP|TRIM|REWRITE|RETIRE)\b"
VERDICT_RE = re.compile(r"^\W*Verdict\W*" + WORDS)
NOTE_RE = re.compile(r"^\s*\((?:[^()]|\([^()]*\))*\)")
ONE_LINE_RE = re.compile(r"\s*:\W*(?:Verdict\W*)?" + WORDS)
SAVEABLE_RE = re.compile(r"Saveable: ~([\d,]+)")


def saveable(line):
    m = SAVEABLE_RE.search(line)
    return int(m.group(1).replace(",", "")) if m else 0


def read_verdicts(text):
    """(path, verdict word, saveable chars) for each verdict line, read inside its own section. A
    section ends at any heading. The one reader of a slice's verdicts: this check and
    assemble_report.py both use it, so they cannot disagree on what counts as a verdict."""
    found, current = [], None
    for line in text.splitlines():
        if ANY_HEADING_RE.match(line):
            m = HEADING_RE.match(line)
            current = m.group(1) if m else None
            one = current and ONE_LINE_RE.match(NOTE_RE.sub("", line[m.end():], count=1))
            if one:
                found.append((current, one.group(1), saveable(line)))
        elif current:
            v = VERDICT_RE.match(line)
            if v:
                found.append((current, v.group(1), saveable(line)))
    return found


def verdicts(text):
    """Paths whose own section holds a verdict line."""
    return {path for path, _, _ in read_verdicts(text)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=os.path.expanduser("~/.claude"))
    ap.add_argument("--slices", required=True)
    a = ap.parse_args()
    root = os.path.abspath(os.path.expanduser(a.root))
    slice_files = sorted(glob.glob(os.path.join(os.path.expanduser(a.slices), "slice_*.md")))
    if not slice_files:
        print(f"CANNOT CHECK: no slice_*.md under {a.slices}", file=sys.stderr)
        return 2
    files = inventory.collect(root)
    wanted = [os.path.relpath(p, root) for kind, p in files if kind != "reference"]
    if not wanted:
        print(f"CANNOT CHECK: no artifacts under {root}", file=sys.stderr)
        return 2
    covered = set()
    for f in slice_files:
        with open(f, encoding="utf-8", errors="replace") as fh:
            covered |= verdicts(fh.read())
    missing = [w for w in wanted if w not in covered]
    for m in missing:
        print(f"MISSING {m}")
    print(f"covered {len(wanted) - len(missing)} of {len(wanted)} across {len(slice_files)} slice files")
    nested = inventory.not_measured(root, files)["nested_skill_md"]
    print(f"outside the review: nested SKILL.md {nested or 'none'}")
    return 1 if missing else 0


if __name__ == "__main__":
    sys.exit(main())
