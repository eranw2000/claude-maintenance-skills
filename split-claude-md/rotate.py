#!/usr/bin/env python3
"""Execute Phase A of /split-claude-md mechanically.

The SKILL tells you to do A4-A6 by hand. On a 190K-char CLAUDE.md that means
loading the whole file into context to move a few records, which is both
expensive and exactly the kind of hand-slicing the global rules forbid.

This does the move programmatically and verifies it, so the human decides only
WHICH records go (the judgment) and never touches the bytes (the mechanics).

    # 1. see what would move, change nothing
    rotate.py <CLAUDE.md> --convention section --cut-date 2026-08-01

    # 2. protect load-bearing records by title fragment (repeatable)
    rotate.py <CLAUDE.md> --convention section --cut-date 2026-08-01 \
        --keep "scraper returns another site" --keep "still blocked"

    # 3. do it
    rotate.py <CLAUDE.md> --convention section --cut-date 2026-08-01 --apply

Conventions (match survey.py's verdict line):
  entry    records are '### ' headings carrying a date
  section  records are '## '  headings carrying a date

Safety:
  - dry run unless --apply
  - backs up every mutated file, never overwriting a same-day backup
  - archives are APPENDED to, never overwritten
  - the index is APPENDED to, never regenerated
  - both-directions presence check on every moved and kept record, counting
    OCCURRENCES (not lines), because records are often one long line
"""
import argparse
import os
import re
import shutil
import sys
from collections import OrderedDict
from datetime import date

DATE_RE = re.compile(r"(\d{4}-\d{2}-\d{2})")   # identical to survey.py

ARCHIVE_HEADER = """# Decisions Log Archive - {month_name} {year}

Decisions log entries archived from `CLAUDE.md` on {today} to keep active context lean.

- Active CLAUDE.md is at `CLAUDE.md` (same directory).
- Index of all archived entries: `CLAUDE_DECISIONS_INDEX.md`.
- For full context on any entry, look for the commit hash in the entry body and run `git show <hash>` in the relevant repo.

---
"""

MONTHS = ["", "January", "February", "March", "April", "May", "June",
          "July", "August", "September", "October", "November", "December"]


def parse_records(lines, convention):
    """Return [(start_idx, end_idx, date_str, title_line)] for dated records.

    end_idx is exclusive. A record runs to the next heading that could start a
    new record, or to the next higher-level heading, whichever comes first.
    """
    if convention == "entry":
        rec_prefix, stop_prefixes = "### ", ("### ", "## ")
    elif convention == "section":
        rec_prefix, stop_prefixes = "## ", ("## ",)
    else:
        raise ValueError(f"unknown convention {convention!r}")

    starts = []
    for i, ln in enumerate(lines):
        if not ln.startswith(rec_prefix):
            continue
        # '## ' must not also match '### '
        if convention == "section" and ln.startswith("### "):
            continue
        m = DATE_RE.search(ln)
        if m:
            starts.append((i, m.group(1), ln.rstrip("\n")))

    records = []
    for n, (i, dt, title) in enumerate(starts):
        end = len(lines)
        for j in range(i + 1, len(lines)):
            ln = lines[j]
            if convention == "section":
                if ln.startswith("## ") and not ln.startswith("### "):
                    end = j
                    break
            else:
                if ln.startswith("### "):
                    end = j
                    break
                if ln.startswith("## ") and not ln.startswith("### "):
                    end = j
                    break
        records.append((i, end, dt, title))
    return records


def backup(path, today):
    if not os.path.exists(path):
        return None
    b = f"{path}.backup-before-split-{today}"
    n = 2
    while os.path.exists(b):
        b = f"{path}.backup-before-split-{today}-{n}"
        n += 1
    shutil.copy2(path, b)
    return b


def occurrences(haystack, needle):
    """Count occurrences, not lines. Records are often one very long line."""
    if not needle:
        return 0
    return haystack.count(needle)


def fragments_of(lines, start, end):
    """Distinctive fragments of a record, for the both-directions check.

    Returns BOTH the title line and a body line whenever a body line exists.
    Checking the title alone is not enough: an off-by-one that removes the
    heading and orphans the body passes a title-only check while leaving the
    record's whole body behind. Checking the body alone is not enough either,
    since a heading left without its body also has to be caught. So both.
    """
    out = []
    t = lines[start].rstrip("\n")
    if len(t) > 12:
        out.append(t)
    for j in range(start + 1, min(end, start + 12)):
        s = lines[j].strip()
        if len(s) > 40:
            out.append(s[:160])
            break
    return out


def main():
    ap = argparse.ArgumentParser(description="Phase A rotation for /split-claude-md.")
    ap.add_argument("file")
    ap.add_argument("--convention", required=True, choices=["entry", "section"])
    ap.add_argument("--cut-date", required=True, help="records strictly before this date are candidates")
    ap.add_argument("--keep", action="append", default=[],
                    help="substring of a record title to KEEP despite its age (repeatable)")
    ap.add_argument("--apply", action="store_true", help="actually write (default: dry run)")
    ap.add_argument("--today", default=date.today().isoformat())
    args = ap.parse_args()

    path = os.path.abspath(args.file)
    d = os.path.dirname(path)
    with open(path, encoding="utf-8") as fh:
        original = fh.read()
    lines = original.splitlines(keepends=True)

    records = parse_records(lines, args.convention)
    if not records:
        print("No dated records found with that convention. Nothing to do.")
        return 1

    keep_frags = [k.lower() for k in args.keep]
    to_move, to_keep = [], []
    for start, end, dt, title in records:
        held = next((k for k in keep_frags if k in title.lower()), None)
        if dt < args.cut_date and not held:
            to_move.append((start, end, dt, title))
        else:
            why = "newer than cut" if dt >= args.cut_date else f"--keep matched {held!r}"
            to_keep.append((start, end, dt, title, why))

    print(f"FILE        {path}")
    print(f"convention  {args.convention}   cut-date {args.cut_date}")
    print(f"records     {len(records)} dated  ->  {len(to_move)} move, {len(to_keep)} keep")
    moved_chars = sum(len("".join(lines[s:e])) for s, e, _, _ in to_move)
    print(f"would move  {moved_chars:,} chars of {len(original):,} "
          f"({moved_chars / len(original) * 100:.1f}%)")
    print()
    print("MOVE:")
    for s, e, dt, title in to_move:
        print(f"  {dt}  {len(''.join(lines[s:e])):>7,}ch  {title[:96]}")
    print("KEEP:")
    for s, e, dt, title, why in to_keep:
        print(f"  {dt}  {len(''.join(lines[s:e])):>7,}ch  {title[:78]}   [{why}]")

    if not args.apply:
        print("\nDRY RUN. Re-run with --apply to write.")
        return 0
    if not to_move:
        print("\nNothing to move. Not writing.")
        return 0

    # ---- bucket by month
    buckets = OrderedDict()
    for s, e, dt, title in to_move:
        buckets.setdefault(dt[:7], []).append((s, e, dt, title))

    index_path = os.path.join(d, "CLAUDE_DECISIONS_INDEX.md")
    mutated = [path, index_path] + [os.path.join(d, f"CLAUDE_DECISIONS_{m}.md") for m in buckets]

    print("\nBACKUPS")
    for f in mutated:
        b = backup(f, args.today)
        print(f"  {'created ' if b else 'absent  '}{os.path.basename(b) if b else os.path.basename(f)}")

    # ---- write archives (append, never overwrite)
    for month, recs in buckets.items():
        ap_path = os.path.join(d, f"CLAUDE_DECISIONS_{month}.md")
        exists = os.path.exists(ap_path)
        body = []
        if not exists:
            y, mo = month.split("-")
            body.append(ARCHIVE_HEADER.format(month_name=MONTHS[int(mo)], year=y, today=args.today))
        else:
            body.append(f"\n<!-- Archived from CLAUDE.md on {args.today} (additional rotation). -->\n")
        for s, e, dt, title in recs:
            chunk = "".join(lines[s:e])
            if args.convention == "entry":
                pass  # keep '### ' depth as-is inside the archive
            body.append(chunk.rstrip("\n") + "\n\n")
        with open(ap_path, "a" if exists else "w", encoding="utf-8") as fh:
            fh.write("".join(body))
        print(f"  archive {'appended' if exists else 'created '} {os.path.basename(ap_path)} (+{len(''.join(body)):,} ch)")

    # ---- rewrite CLAUDE.md by deleting moved spans (never a string slice)
    drop = set()
    for s, e, _, _ in to_move:
        drop.update(range(s, e))
    new_lines = [ln for i, ln in enumerate(lines) if i not in drop]
    new_text = "".join(new_lines)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(new_text)

    # ---- index: APPEND rows, never regenerate
    rows = [f"- {dt}: {title.lstrip('#').strip()} - `CLAUDE_DECISIONS_{dt[:7]}.md`\n"
            for _, _, dt, title in sorted(to_move, key=lambda r: r[2])]
    if os.path.exists(index_path):
        with open(index_path, encoding="utf-8") as fh:
            idx = fh.read()
        if "## Entries (chronological)" in idx:
            head, tail = idx.split("## Entries (chronological)", 1)
            idx = head + "## Entries (chronological)" + tail.rstrip("\n") + "\n" + "".join(rows)
        else:
            idx = idx.rstrip("\n") + "\n\n## Entries (chronological)\n\n" + "".join(rows)
        with open(index_path, "w", encoding="utf-8") as fh:
            fh.write(idx)
        print(f"  index   appended {len(rows)} rows to {os.path.basename(index_path)}")
    else:
        with open(index_path, "w", encoding="utf-8") as fh:
            fh.write(
                "# Decisions Log Index\n\n"
                "One-line summary of every archived decision-log entry from CLAUDE.md. This index "
                "stays in active context; the full entries live in the dated archive files "
                "referenced in each row.\n\n"
                "## How to use\n\n"
                "- **Looking for \"why did we do X?\"** - scan for keywords, then read the matching "
                "archive entry with `grep -B2 -A60 \"<entry-title>\" CLAUDE_DECISIONS_YYYY-MM.md`.\n"
                "- **Looking for a specific commit** - most entries cite their commit hash in the "
                "body. Run `git show <hash>` inside the project repo for the full diff.\n"
                "- **Looking by date** - entries are listed in chronological order below.\n\n"
                "## Project heading convention\n\n"
                f"This project's decision-log records are whole dated `{'## ' if args.convention == 'section' else '### '}` "
                "headings. Future `/split-claude-md` runs must use that pattern, not the default.\n\n"
                "## Archives\n"
                + "".join(f"- `CLAUDE_DECISIONS_{m}.md` - {len(r)} entries\n" for m, r in buckets.items())
                + "\n## Entries (chronological)\n\n" + "".join(rows)
            )
        print(f"  index   created {os.path.basename(index_path)} with {len(rows)} rows")

    # ---- A9 both-directions presence check, counting OCCURRENCES
    print("\nVERIFY (both directions, occurrence counts)")
    archives = {m: open(os.path.join(d, f"CLAUDE_DECISIONS_{m}.md"), encoding="utf-8").read()
                for m in buckets}
    fails = 0
    nfrag_moved = nfrag_kept = 0
    for s, e, dt, title in to_move:
        for frag in fragments_of(lines, s, e):
            nfrag_moved += 1
            in_arch = occurrences(archives[dt[:7]], frag)
            in_new = occurrences(new_text, frag)
            ok = (in_arch == 1 and in_new == 0)
            fails += (not ok)
            if not ok:
                print(f"  FAIL moved  arch={in_arch} claude={in_new}  {title[:60]}")
                print(f"              fragment: {frag[:80]!r}")
    for s, e, dt, title, _ in to_keep:
        for frag in fragments_of(lines, s, e):
            nfrag_kept += 1
            in_new = occurrences(new_text, frag)
            ok = in_new == 1
            fails += (not ok)
            if not ok:
                print(f"  FAIL kept   claude={in_new}  {title[:60]}")
                print(f"              fragment: {frag[:80]!r}")
    print(f"  moved records: {len(to_move)} records / {nfrag_moved} fragments "
          f"(each must be 1 in archive, 0 in CLAUDE.md)")
    print(f"  kept  records: {len(to_keep)} records / {nfrag_kept} fragments "
          f"(each must be 1 in CLAUDE.md)")
    if nfrag_moved < len(to_move) * 2:
        print(f"  NOTE: {len(to_move) * 2 - nfrag_moved} record(s) had no usable body fragment "
              f"(short records); those were checked on their title only.")

    # ---- line accounting
    arch_lines = sum(a.count("\n") for a in archives.values())
    print(f"\nACCOUNTING")
    print(f"  original CLAUDE.md : {len(original):>9,} ch  {original.count(chr(10)):>6,} lines")
    print(f"  new      CLAUDE.md : {len(new_text):>9,} ch  {new_text.count(chr(10)):>6,} lines"
          f"   ({(1 - len(new_text)/len(original))*100:.1f}% smaller)")
    print(f"  archives (this run): {sum(len(a) for a in archives.values()):>9,} ch  {arch_lines:>6,} lines")

    if fails:
        print(f"\n*** {fails} VERIFICATION FAILURE(S). Restore from the .backup-before-split-* files. ***")
        return 2
    print("\nAll presence checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
