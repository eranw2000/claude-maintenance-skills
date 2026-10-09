#!/usr/bin/env python3
"""What did a CLAUDE.md edit lose? (Plus a structure check.)

    loss_check.py --before <backup> --after CLAUDE.md
        [--lazy F ...] [--hoisted F ...] [--accept S ...] [--accept-file F]
        [--report F] [--structure [--edited H ...]]

Every rule-shaped sentence, identifier, path, command and heading of the
BEFORE file is classified as KEPT (in the after CLAUDE.md, or in an
accepted --hoisted file), POINTED (in a lazy file, and its section still points
there), LAZY-ONLY (in a lazy file, no pointer) or NOWHERE. Lazy files are the
top-level *.md files beside the after CLAUDE.md, plus --lazy files.

Exit codes:
  0  nothing lost that is not waived (and, with --structure, nothing changed)
  3  a finding: a NOWHERE item or a LAZY-ONLY rule not waived, or a changed
     or unnamed new section under --structure
  2  cannot tell: a missing or unreadable input, an empty waiver value, or a
     --hoisted path that is refused; nothing is written

The text rules live in splitlib.py; this file only reads, calls and prints.
"""
import argparse
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import splitlib  # noqa: E402


def cannot_tell(msg):
    print("CANNOT TELL: " + msg)
    print("Exit 2: nothing was checked and no report was written.")
    return 2


def main(argv=None):
    """The loss check. Its whole body is one error boundary: an
    OSError, ValueError or UnicodeDecodeError that escapes it is exit 2 with one
    cannot-tell line naming the path the error carries (or its type)."""
    try:
        ap = argparse.ArgumentParser(description="Loss check for a CLAUDE.md split.")
        ap.add_argument("--before", required=True, help="the backup taken before the edit")
        ap.add_argument("--after", required=True, help="the CLAUDE.md as it is now")
        ap.add_argument("--lazy", action="append", default=[],
                        help="another lazy file to search (repeatable)")
        ap.add_argument("--hoisted", action="append", default=[],
                        help="another always-loaded CLAUDE.md holding hoisted rules (repeatable)")
        ap.add_argument("--accept", action="append", default=[],
                        help="waive the items whose text holds this (repeatable)")
        ap.add_argument("--accept-file", help="one --accept value per line")
        ap.add_argument("--report", help="write the report to this file")
        ap.add_argument("--structure", action="store_true",
                        help="also require unedited sections to be byte-identical")
        ap.add_argument("--edited", action="append", default=[],
                        help="a section heading the edit was allowed to change (repeatable)")
        args = ap.parse_args(argv)

        # Empty waiver values first: an empty value matches every item.
        for v in args.accept:
            msg = splitlib.refuse_empty_waiver("--accept", v)
            if msg:
                print(msg)
                return 2

        inputs = [("--before", args.before), ("--after", args.after)]
        inputs += [("--lazy", p) for p in args.lazy]
        inputs += [("--hoisted", p) for p in args.hoisted]
        if args.accept_file:
            inputs.append(("--accept-file", args.accept_file))
        texts = {}
        cache = {}      # one read per realpath per run (splitlib.read_once)
        for flag, p in inputs:
            if not os.path.isfile(p):
                return cannot_tell("%s file missing: %s" % (flag, p))
            try:
                texts[p] = splitlib.read_once(cache, p)
            except (OSError, UnicodeDecodeError) as e:
                return cannot_tell("%s file unreadable: %s (%s); nothing was changed"
                                   % (flag, getattr(e, "filename", None) or p, type(e).__name__))

        for p in args.hoisted:
            why = splitlib.hoisted_refusal(p, [args.after, args.before])
            if why:
                print("REFUSED --hoisted %s: %s" % (p, why))
                print("Exit 2: nothing was checked and no report was written.")
                return 2

        waivers = [('--accept "%s"' % v, v) for v in args.accept]
        if args.accept_file:
            # the waivers are the bytes the guarded read above returned
            waivers += [('--accept-file "%s"' % v, v)
                        for v in splitlib.accept_lines(texts[args.accept_file])]

        base = os.path.dirname(os.path.abspath(args.after))
        lazy_paths = splitlib.notes_set(base, exclude=[args.before, args.after]
                                        + list(args.hoisted))
        held = set(os.path.realpath(x) for x in lazy_paths)
        for p in args.lazy:
            if os.path.realpath(p) not in held:
                lazy_paths.append(p)
        lazy = []
        for p in lazy_paths:
            try:
                lazy.append((p, splitlib.read_once(cache, p)))
            except (OSError, UnicodeDecodeError) as e:
                return cannot_tell("notes file unreadable: %s (%s); nothing was changed"
                                   % (getattr(e, "filename", None) or p, type(e).__name__))
        hoisted = [(p, texts[p]) for p in args.hoisted]

        before, after = texts[args.before], texts[args.after]
        # a fence still open at the end of either text is cannot tell
        for p in (args.before, args.after):
            try:
                splitlib.closed_fence_states(texts[p].splitlines())
            except splitlib.UnclosedFence as e:
                return cannot_tell("fence opened at line %d never closes (%s)" % (e.line, p))
        # POINTED: the pointer resolver gets no extra root, so a pointer
        # counts only when it reaches a lazy file from the CLAUDE.md folder.
        results = splitlib.classify(before, after, base, lazy=lazy, hoisted=hoisted,
                                    roots=(), memory_dir=None, cache=cache)
        wcounts = splitlib.apply_waivers(results, waivers)
        blocking = splitlib.unwaived_blocking(results)
        diffs = splitlib.structure_diffs(before, after, args.edited) if args.structure else []

        counts = splitlib.class_counts(results)
        out = []
        out.append("LOSS CHECK  before %s  after %s" % (args.before, args.after))
        out.append("chars before %d  after %d" % (len(before), len(after)))
        out.append("items %d: " % len(results)
                   + ", ".join("%s %d" % (c, n) for c, n in counts.items()))
        out.append("lazy files: " + (", ".join(os.path.relpath(p, base) for p, _ in lazy)
                                     if lazy else "none"))
        out += splitlib.listing_lines(results)
        out += splitlib.waiver_lines(wcounts)
        for key, why in diffs:
            out.append("STRUCTURE CHANGED: %s (%s)" % (splitlib.section_name(key), why))
        if blocking or diffs:
            verdict = ("FINDING: %d item(s) lost without a waiver, %d section(s) changed"
                       % (len(blocking), len(diffs)))
            code = 3
        else:
            verdict = "HOLDS: nothing lost without a waiver"
            if args.structure:
                verdict += ", no unnamed section changed"
            code = 0
        out.append(verdict)
        print("\n".join(out))

        if args.report:
            rep = ["# Loss check report", "",
                   "## Summary", "",
                   "- before: %s (%d chars)" % (args.before, len(before)),
                   "- after: %s (%d chars)" % (args.after, len(after)),
                   "- verdict: %s (exit %d)" % (verdict, code), "",
                   "## Loss check", ""]
            rep += ["- %s: %d" % (c, n) for c, n in counts.items()]
            rep.append("")
            rep += splitlib.listing_lines(results)
            rep += ["%s: %s" % (r.label(), r.item.text) for r in results
                    if r.cls == "KEPT (hoisted)"]
            rep += ["", "## Waivers", ""]
            wl = splitlib.waiver_lines(wcounts)
            rep += wl if wl else ["none"]
            for r in results:
                if r.waiver:
                    rep.append("- %s let through: %s" % (r.waiver, r.item.text))
            if args.structure:
                rep += ["", "## Structure", ""]
                rep += (["- %s: %s" % (splitlib.section_name(k), w) for k, w in diffs]
                        or ["unchanged outside the sections named by --edited"])
            try:
                with open(args.report, "w", encoding="utf-8") as fh:
                    fh.write("\n".join(rep) + "\n")
            except OSError as e:
                print("CANNOT TELL: report not written: %s (%s); nothing was changed"
                      % (getattr(e, "filename", None) or args.report, type(e).__name__))
                return 2
        return code
    except (OSError, ValueError, UnicodeDecodeError) as e:     # the error boundary
        fn = getattr(e, "filename", None)
        return cannot_tell("%s; nothing was changed" % ("%s (%s)" % (fn, type(e).__name__) if fn
                                                        else type(e).__name__))


if __name__ == "__main__":
    sys.exit(main())
