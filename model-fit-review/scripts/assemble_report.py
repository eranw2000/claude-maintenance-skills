#!/usr/bin/env python3
"""Build REPORT.md from the body Claude wrote, adding the two sections a script writes better.

    assemble_report.py --out "$OUT" --body "$OUT/REPORT_body.md" --outcomes "$OUT/outcomes.json"

Section 5 (what the labs recommend): one line per item of "$OUT/LAB_ADVICE.md", carrying its
quote copied from that file (never retyped), the page's address from "$OUT/lab/index.json", and
the outcome from outcomes.json ({"A1": "DIFFERS: <file, line and the change>", ...}). Each outcome
starts with FOLLOWED, DIFFERS, ADD or NOT FOR US.

Section 6 (per-file verdicts): every file in "$OUT/slices.json" with its verdict word and the
reader's Saveable estimate, grouped RETIRE, REWRITE, TRIM, KEEP, plus the estimates summed. The
verdicts are read by coverage_check.py's own reader, so the two scripts agree on what counts.

The body carries the two places as the lines `<!-- LAB SECTION -->` and `<!-- VERDICTS -->`, once
each. Exit 0 when REPORT.md was written; 2 when it was not (a place missing or doubled, an item
with no outcome, an outcome for an item that does not exist, an outcome word it does not know, an
item line that is not one of its one-line fields, a page not in index.json, no slice files, a file
with no verdict or with two different ones). Step 4's `lab_guidance.py check --report` still runs after.
"""
import argparse
import collections
import glob
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import coverage_check  # noqa: E402

ITEM = re.compile(r"^### (A\d+)\n(.*?)(?=^### A\d+|^no advice:|^not read:|\Z)", re.M | re.S)
FIELD = re.compile(r"^(\w[\w ]*): (.*)$", re.M)
FIELDS = {"lab", "page", "models", "quote", "applies to", "means"}
OUTCOME = re.compile(r"^(FOLLOWED|DIFFERS|ADD|NOT FOR US)\b")
LAB_MARK, VERDICT_MARK = "<!-- LAB SECTION -->", "<!-- VERDICTS -->"


class Refuse(Exception):
    pass


def lab_section(out, outcomes):
    with open(os.path.join(out, "LAB_ADVICE.md"), encoding="utf-8") as fh:
        advice = fh.read()
    with open(os.path.join(out, "lab", "index.json"), encoding="utf-8") as fh:
        urls = {p["file"]: p["url"] for p in json.load(fh)["pages"]}
    items = {}
    for m in ITEM.finditer(advice):
        for line in m.group(2).splitlines():
            f = FIELD.match(line)
            if line.strip() and not (f and f.group(1) in FIELDS):
                raise Refuse(f"{m.group(1)}: {line[:60]!r} is not one of the item's one-line fields (a quote must stay on one line)")
        items[m.group(1)] = dict(FIELD.findall(m.group(2)))
    if not items:
        raise Refuse("LAB_ADVICE.md holds no items")
    if set(items) != set(outcomes):
        raise Refuse(f"items and outcomes differ: no outcome for {sorted(set(items) - set(outcomes))}, "
                     f"no item for {sorted(set(outcomes) - set(items))}")
    lines = ["## 5. What the labs recommend", "",
             "Each item: its number, the lab's sentence word for word, the page, and one outcome. "
             "The quotes are copied from `LAB_ADVICE.md`, which `lab_guidance.py check` proved against the saved pages.", ""]
    for ident in sorted(items, key=lambda s: int(s[1:])):
        f, o = items[ident], outcomes[ident].strip()
        if not OUTCOME.match(o):
            raise Refuse(f"{ident}: the outcome must start with FOLLOWED, DIFFERS, ADD or NOT FOR US")
        page = f.get("page", "").strip()
        if page not in urls:
            raise Refuse(f"{ident}: page {page!r} is not in lab/index.json")
        lines += [f"{ident} ({f.get('lab', '?')}, {f.get('applies to', '?')}): \"{f.get('quote', '')}\" "
                  f"Source: {urls[page]}. Outcome: {o}", ""]
    return "\n".join(lines).rstrip() + "\n"


def verdicts(out):
    with open(os.path.join(out, "slices.json"), encoding="utf-8") as fh:
        expected = sorted({p for paths in json.load(fh).values() for p in paths})
    if not expected:
        raise Refuse("slices.json lists no files")
    files = sorted(glob.glob(os.path.join(out, "slice_*.md")))
    if not files:
        raise Refuse("no slice_*.md files")
    words, saved = collections.defaultdict(set), collections.defaultdict(int)
    for path in files:
        with open(path, encoding="utf-8") as fh:
            for p, word, n in coverage_check.read_verdicts(fh.read()):
                words[p].add(word)
                saved[p] = max(saved[p], n)
    missing = [p for p in expected if p not in words]
    if missing:
        raise Refuse(f"no verdict for {len(missing)} of {len(expected)} files: {', '.join(missing[:20])}")
    torn = [p for p in expected if len(words[p]) > 1]
    if torn:
        raise Refuse(f"two different verdicts for: {', '.join(torn[:20])}")
    groups = collections.defaultdict(list)
    for p in expected:
        groups[next(iter(words[p]))].append(p)
    out_lines = []
    for k in ("RETIRE", "REWRITE", "TRIM", "KEEP"):
        if groups[k]:
            out_lines.append(f"- {k} ({len(groups[k])}): " + ", ".join(p + (f" (~{saved[p]:,})" if saved[p] else "") for p in groups[k]))
    total = sum(saved[p] for p in expected)
    out_lines.append(f"- Files with a verdict: {len(expected)}. The readers' Saveable estimates summed: ~{total:,} chars (an estimate, not a measurement).")
    return "\n".join(out_lines) + "\n"


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--out", required=True)
    ap.add_argument("--body", required=True)
    ap.add_argument("--outcomes", required=True)
    a = ap.parse_args()
    try:
        with open(a.body, encoding="utf-8") as fh:
            body = fh.read()
        with open(a.outcomes, encoding="utf-8") as fh:
            outcomes = json.load(fh)
        for mark in (LAB_MARK, VERDICT_MARK):
            if body.count(mark) != 1:
                raise Refuse(f"the body must carry {mark} exactly once (found {body.count(mark)})")
        sections = {LAB_MARK: lab_section(a.out, outcomes), VERDICT_MARK: verdicts(a.out)}
        body = re.sub("|".join(map(re.escape, sections)), lambda m: sections[m.group(0)], body)
    except (OSError, ValueError, KeyError, Refuse) as e:
        print(f"NOT WRITTEN: {e}", file=sys.stderr)
        return 2
    dest = os.path.join(a.out, "REPORT.md")
    with open(dest, "w", encoding="utf-8") as fh:
        fh.write(body)
    print(f"{dest}: {len(body)} chars")
    return 0


if __name__ == "__main__":
    sys.exit(main())
