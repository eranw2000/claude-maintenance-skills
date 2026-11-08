#!/usr/bin/env python3
"""Save one reader's report as a slice file, read from the reader's output file.

    save_slice.py <output_file the Agent call returned> "$OUT/slice_<family>.md"

A helper cannot write the slice file itself, and copying a 20K-char report through the
conversation costs the same tokens again. This reads the report out of the reader's transcript
instead: the text of its hand-back call, and only one that holds at least one verdict. A long
reply with no hand-back is a reader that was cut off, so it is never saved. It prints only the
size and the heading count, never the text.

Exit 0 when a report was saved; 2 when none was found (run that reader again, or save its report by
hand from its message) or a file cannot be read.
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import coverage_check  # noqa: E402


def texts(obj, found):
    """Collect hand-back texts from any nesting of the transcript record."""
    if isinstance(obj, dict):
        if obj.get("type") == "tool_use" and "andback" in str(obj.get("name", "")):
            for v in (obj.get("input") or {}).values():
                if isinstance(v, str):
                    found.append(v)
        for v in obj.values():
            texts(v, found)
    elif isinstance(obj, list):
        for v in obj:
            texts(v, found)


def main(argv):
    if len(argv) != 3:
        print(__doc__.split("\n\n")[1], file=sys.stderr)
        return 2
    src, dst = argv[1], argv[2]
    try:
        with open(src, encoding="utf-8") as fh:
            lines = fh.read().splitlines()
    except OSError as e:
        print(f"NOT SAVED: {e}", file=sys.stderr)
        return 2
    records = []
    for line in lines:
        try:
            records.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    found = []
    texts(records, found)
    report = next((t for t in reversed(found) if coverage_check.verdicts(t)), None)
    if not report:
        print(f"NOT SAVED: no hand-back with a verdict in {src}; run that reader again, or save its report by hand", file=sys.stderr)
        return 2
    with open(dst, "w", encoding="utf-8") as fh:
        fh.write(report if report.endswith("\n") else report + "\n")
    print(f"{dst}: {len(report)} chars, {report.count(chr(10) + '### ')} headings")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
