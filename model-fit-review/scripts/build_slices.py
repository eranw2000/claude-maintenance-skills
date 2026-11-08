#!/usr/bin/env python3
"""Cut the measured files into reader slices by family.

    build_slices.py --out "$OUT" --families "$OUT/families.json" [--extra family=path ...]

families.json maps a family name to a list of entries. An entry is a skill folder name
(`grill-me`, which takes its SKILL.md and reference files), a path (`commands/instruct.md`), or a
glob over paths (`agents/*`). Every file in "$OUT/inventory.json" must land in exactly one family;
--extra adds a file the inventory does not measure (a `skills/_shared` note) to a family.

Writes "$OUT/slices.json" ({family: [paths]}) and prints each family's file count and chars.
Exit 0 when every file has one family and none is over --max-chars (default 350000, the size one
reader holds); 1 when a file has no family or two, or a family is too big (each is named, and
nothing is written); 2 when an input cannot be read.
"""
import argparse
import fnmatch
import json
import os
import sys


def unit(path):
    parts = path.split("/")
    return parts[1] if parts[0] == "skills" and len(parts) > 2 else path


def matches(entry, path):
    if any(c in entry for c in "*?["):
        return fnmatch.fnmatch(path, entry)
    return entry == path or entry == unit(path)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--out", required=True)
    ap.add_argument("--families", required=True)
    ap.add_argument("--extra", action="append", default=[], help="family=path, a file the inventory does not measure")
    ap.add_argument("--root", default=os.path.expanduser("~/.claude"))
    ap.add_argument("--max-chars", type=int, default=350000)
    a = ap.parse_args()
    try:
        with open(os.path.join(a.out, "inventory.json"), encoding="utf-8") as fh:
            rows = json.load(fh)["rows"]
        with open(a.families, encoding="utf-8") as fh:
            fams = json.load(fh)
        if not isinstance(fams, dict) or not all(isinstance(v, list) for v in fams.values()):
            raise ValueError("families must map a name to a list")
    except (OSError, ValueError, KeyError) as e:
        print(f"CANNOT SLICE: {e}", file=sys.stderr)
        return 2

    slices = {f: [] for f in fams}
    size = {f: 0 for f in fams}
    bad = []
    for r in rows:
        p = r["path"]
        homes = [f for f, entries in fams.items() if any(matches(e, p) for e in entries)]
        if len(homes) != 1:
            bad.append(f"{p}: {'no family' if not homes else 'in ' + ', '.join(homes)}")
            continue
        slices[homes[0]].append(p)
        size[homes[0]] += r["chars"]
    for spec in a.extra:
        fam, _, path = spec.partition("=")
        if fam not in slices or not path:
            bad.append(f"--extra {spec}: name a family from the file, then =path")
            continue
        try:
            size[fam] += os.path.getsize(os.path.join(a.root, path))
        except OSError as e:
            print(f"CANNOT SLICE: {e}", file=sys.stderr)
            return 2
        slices[fam].append(path)
    for f in slices:
        print(f"{f}: {len(slices[f])} files, {size[f]} chars")
        if size[f] > a.max_chars:
            bad.append(f"{f}: {size[f]} chars, over {a.max_chars}; split it in two")
        if not slices[f]:
            bad.append(f"{f}: no files")
    if bad:
        print("NOT SLICED:", *bad, sep="\n  ")
        return 1
    with open(os.path.join(a.out, "slices.json"), "w", encoding="utf-8") as fh:
        json.dump(slices, fh, indent=1)
    return 0


if __name__ == "__main__":
    sys.exit(main())
