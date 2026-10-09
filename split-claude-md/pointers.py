#!/usr/bin/env python3
"""Does every pointer in a CLAUDE.md resolve?

    pointers.py FILE [--root D ...] [--memory-dir D]

A pointer is a backticked file name on a line that also says See, Evidence,
Detail, same heading, pointer, lives in or moved to, plus every [[name]] link.
A file resolves against FILE's folder, then each --root (default: the home
.claude folder, applied here and nowhere else), then the folders a backticked
token ending in '/' names earlier in the same section. A 'same heading' pointer
also needs the heading above it to be a heading of the target, ignoring the
'#' level and an '(N instances)' count. A pointer to CLAUDE_DECISIONS_INDEX.md
also resolves every archive that index names. [[name]] resolves to
<memory-dir>/<name>.md, and is counted as skipped without --memory-dir.

Each unresolved pointer is printed on its own line with its section.

Exit codes:
  0  every pointer resolves (skipped memory links do not count)
  3  a finding: at least one pointer does not resolve
  2  cannot tell: FILE, a --root or the --memory-dir is missing or unreadable
"""
import argparse
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import splitlib  # noqa: E402


def parse(argv=None):
    ap = argparse.ArgumentParser(description="Pointer report for a CLAUDE.md.")
    ap.add_argument("file", help="the CLAUDE.md (or any notes file) to check")
    ap.add_argument("--root", action="append", default=None,
                    help="another folder pointers resolve against (repeatable; "
                         "default ~/.claude)")
    ap.add_argument("--memory-dir", help="the folder [[name]] links resolve in")
    args = ap.parse_args(argv)
    # The one place the home .claude default is applied.
    if not args.root:
        args.root = [os.path.expanduser("~/.claude")]
    return args


def cannot_tell(msg):
    print("CANNOT TELL: " + msg)
    print("Exit 2: no pointer was checked.")
    return 2


def main(argv=None):
    args = parse(argv)
    if not os.path.isfile(args.file):
        return cannot_tell("file missing: %s" % args.file)
    for r in args.root:
        if not os.path.isdir(r):
            return cannot_tell("--root folder missing: %s" % r)
    if args.memory_dir is not None and not os.path.isdir(args.memory_dir):
        return cannot_tell("--memory-dir folder missing: %s" % args.memory_dir)
    try:
        with open(args.file, encoding="utf-8") as fh:
            text = fh.read()
    except (OSError, UnicodeDecodeError) as e:
        return cannot_tell("file unreadable: %s (%s)" % (args.file, type(e).__name__))

    base = os.path.dirname(os.path.abspath(args.file))
    try:
        ptrs = splitlib.pointers(text, base, args.root, args.memory_dir)
    except splitlib.UnclosedFence as e:
        return cannot_tell("fence opened at line %d never closes (%s)" % (e.line, args.file))
    except (OSError, ValueError, UnicodeDecodeError) as e:
        # a pointer target that cannot be read is cannot tell, never an empty text
        return cannot_tell("%s unreadable (%s)" % (getattr(e, "filename", None) or "a pointer target",
                                                    type(e).__name__))
    status = dict((s, [p for p in ptrs if p.status == s])
                  for s in ("RESOLVED", "UNRESOLVED", "SKIPPED"))
    out = ["POINTERS  %s" % args.file,
           "roots: " + ", ".join(args.root),
           "pointers %d: resolved %d, unresolved %d, skipped %d"
           % (len(ptrs), len(status["RESOLVED"]), len(status["UNRESOLVED"]),
              len(status["SKIPPED"]))]
    for p in status["UNRESOLVED"]:
        out.append("UNRESOLVED: %s in section %s (line %d); %s"
                   % (p.token, splitlib.section_name(p.section), p.lineno, p.why))
    for p in status["SKIPPED"]:
        out.append("SKIPPED: [[%s]] in section %s (line %d); %s"
                   % (p.token, splitlib.section_name(p.section), p.lineno, p.why))
    if status["UNRESOLVED"]:
        out.append("FINDING: %d pointer(s) do not resolve" % len(status["UNRESOLVED"]))
        code = 3
    else:
        out.append("HOLDS: every pointer resolves")
        code = 0
    print("\n".join(out))
    return code


if __name__ == "__main__":
    sys.exit(main())
