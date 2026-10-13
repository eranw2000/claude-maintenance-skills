#!/usr/bin/env python3
"""Phase D cutter: keep every rule, move story sentences to the month archive.

It cuts INSIDE kept sections. A spec names, per cut, the section heading, the
first-line prefix of one unit (a bullet with its indented continuation lines,
or a plain paragraph), the story sentences to drop, and the archive month. The
unit as it stood before the cut is copied verbatim into
CLAUDE_DECISIONS_<month>.md under the same heading, unless that exact text is
already there under that heading (an earlier run archived it), in which case it
is not copied twice. No pointer line per section: one optional shared pointer
line, placed after a line the spec names.

Usage:
  python3 phase_d.py <CLAUDE.md> --spec <spec.json> [--today YYYY-MM-DD] [--write] [--no-backup]
                     [--accept FRAGMENT ...] [--root DIR ...]

Spec (JSON):
  {"cuts": [{"heading": "## Section title", "prefix": "- **Start of the bullet",
             "mode": "join" | "raw", "archive": "2026-09",
             "drops": [" A story sentence."], "allow_rule_edit": false}],
   "pointer": {"after": "<an existing line, exact>", "line": "<the new line>"}}

  join: the unit's wrapped lines are joined with one space before the drops are
        removed, and the result is written back as one line;
  raw:  the drops are removed from the unit text as it is (use it for a unit
        with a nested list, and write a drop that spans a wrap with its "\\n  ").
  allow_rule_edit: true lets this cut change a rule sentence (a sentence holding
        never, always, must, do not, don't, refuse, forbid or only). Use it only
        for a story clause inside a rule sentence, and read the result.

Checks (any failure: exit 3, nothing written): each prefix starts exactly one
line, outside code fences, under the named heading; no two cuts' units overlap;
each drop matches exactly once in its unit; every rule sentence of the unit
survives word for word unless the cut sets allow_rule_edit; no double or
trailing space is left; headings unchanged; no character the file did not
already hold; every untouched section identical, compared by position; each
unit's old text is gone from CLAUDE.md and present in its archive under the
same heading. Then, on the planned texts and still before any write, the loss
check (loss_check.py's classes: nothing lost unless an --accept fragment
waives it) and the pointer check (pointers.py's resolver, with each --root,
default ~/.claude): a pointer broken before the cut is counted, a NEW one
refuses. A file the cut would write that is a symlink refuses; a missing
--root folder is cannot tell.

Exit: 0 the checks hold (dry run, or written); 3 a check failed; 2 cannot tell
(spec malformed, a file unreadable, a code fence never closes, a write failed).
Dry run unless --write. --write backs up every file it changes first (never
over a same-day backup) unless --no-backup says the session already did.
"""

import argparse
import datetime
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import splitlib  # noqa: E402
from rotate import backup  # noqa: E402

INDEX = "CLAUDE_DECISIONS_INDEX.md"
CUT_KEYS = {"heading", "prefix", "mode", "archive", "drops", "allow_rule_edit"}


class Refused(Exception):
    """A check failed: exit 3."""


class CannotTell(Exception):
    """Input unreadable or malformed, or a write failed: exit 2."""


def fences(lines, name):
    """splitlib's fence flags for a whole text (truthy = inside a fence or on
    its fence line). A fence that never closes is cannot-tell."""
    try:
        return splitlib.closed_fence_states(lines)
    except splitlib.UnclosedFence as e:
        raise CannotTell("%s: a code fence opened at line %s never closes" % (name, e))


def spans(lines, fenced):
    """The '## ' sections in order, as (heading line or '' for the preamble,
    start, end). A '## ' line inside a fence is content, not a heading."""
    heads = [i for i, ln in enumerate(lines) if not fenced[i] and ln.startswith("## ")]
    starts = [0] + heads
    out = []
    for k, s in enumerate(starts):
        e = starts[k + 1] if k + 1 < len(starts) else len(lines)
        if k == 0 and heads and heads[0] == 0:
            continue
        out.append((lines[s] if s in heads else "", s, e))
    return out


def owner(sp, i):
    """Index into spans() of the section holding line i."""
    for k, (_, s, e) in enumerate(sp):
        if s <= i < e:
            return k
    return None


def unit_end(lines, i):
    """One past the last line of the unit starting at i. A bullet runs over its
    indented continuation lines; a paragraph runs to a blank line, a heading or
    a list item."""
    j = i + 1
    if lines[i].lstrip().startswith(("- ", "* ")):
        while j < len(lines) and lines[j].startswith("  ") and lines[j].strip():
            j += 1
    else:
        while (j < len(lines) and lines[j].strip() and not lines[j].startswith("#")
               and not lines[j].lstrip().startswith(("- ", "* "))):
            j += 1
    return j


def joined(raw):
    """The unit's lines joined with one space (leading indent of the
    continuation lines dropped)."""
    parts = raw.split("\n")
    return " ".join([parts[0]] + [p.strip() for p in parts[1:]])


def squash(s):
    """Whitespace collapsed and ** bold marks dropped: emphasis is not content, and
    a bold rule ending ".**" is then split from the story sentence after it."""
    return " ".join(s.replace("**", "").split())


def under_heading(text, heading):
    """All lines of every section of `text` whose heading line is `heading`,
    fences respected (an archive with an open fence is read without them)."""
    lines = text.split("\n")
    fenced, _ = splitlib.fence_states(lines)
    return "\n".join("\n".join(lines[s:e]) for h, s, e in spans(lines, fenced) if h == heading)


def load_spec(path):
    try:
        with open(path, encoding="utf-8") as fh:
            spec = json.load(fh)
    except (OSError, ValueError) as e:
        raise CannotTell("spec unreadable: %s (%s)" % (path, type(e).__name__))
    if not isinstance(spec, dict) or set(spec) - {"cuts", "pointer"}:
        raise CannotTell("spec must be an object with \"cuts\" and an optional \"pointer\"")
    cuts = spec.get("cuts")
    if not isinstance(cuts, list) or not cuts:
        raise CannotTell("spec has no \"cuts\" list")
    nonempty = lambda v: isinstance(v, str) and v != ""
    for n, c in enumerate(cuts, 1):
        if not isinstance(c, dict):
            raise CannotTell("cut %d is not an object" % n)
        if set(c) - CUT_KEYS:
            raise CannotTell("cut %d has unknown key(s): %s" % (n, ", ".join(sorted(set(c) - CUT_KEYS))))
        for k in ("heading", "prefix", "archive"):
            if not nonempty(c.get(k)):
                raise CannotTell("cut %d: %r must be a non-empty string" % (n, k))
        if c.get("mode", "join") not in ("join", "raw"):
            raise CannotTell("cut %d: mode must be \"join\" or \"raw\"" % n)
        if not re.fullmatch(r"\d{4}-\d{2}", c["archive"]):
            raise CannotTell("cut %d: archive must be YYYY-MM" % n)
        if (not isinstance(c.get("drops"), list) or not c["drops"]
                or not all(nonempty(d) for d in c["drops"])):
            raise CannotTell("cut %d: drops must be a non-empty list of non-empty strings" % n)
        if "allow_rule_edit" in c and not isinstance(c["allow_rule_edit"], bool):
            raise CannotTell("cut %d: allow_rule_edit must be true or false, not %r"
                             % (n, c["allow_rule_edit"]))
    p = spec.get("pointer")
    if p is not None and not (isinstance(p, dict) and set(p) == {"after", "line"}
                              and nonempty(p["after"]) and nonempty(p["line"])):
        raise CannotTell("pointer must be {\"after\": <line>, \"line\": <line>}, both non-empty strings")
    return cuts, p


def read(path):
    try:
        with open(path, encoding="utf-8") as fh:
            return fh.read()
    except (OSError, UnicodeDecodeError) as e:
        raise CannotTell("unreadable: %s (%s)" % (path, type(e).__name__))


def plan(cm_text, cuts, pointer, cm, today):
    """Everything --write would write, as {path: new text}, plus a summary.
    Raises Refused on any failed check."""
    folder = os.path.dirname(cm)
    lines = cm_text.split("\n")
    fenced = fences(lines, "CLAUDE.md")
    sp = spans(lines, fenced)
    problems, edits, moved = [], [], {}
    for n, c in enumerate(cuts, 1):
        hits = [i for i, ln in enumerate(lines) if ln.startswith(c["prefix"]) and not fenced[i]]
        if len(hits) != 1:
            problems.append("cut %d: prefix starts %d lines outside code fences (needs 1): %r"
                            % (n, len(hits), c["prefix"][:70]))
            continue
        i = hits[0]
        k = owner(sp, i)
        if sp[k][0] != c["heading"]:
            problems.append("cut %d: prefix is under %r, not %r" % (n, sp[k][0], c["heading"]))
            continue
        j = unit_end(lines, i)
        raw = "\n".join(lines[i:j])
        text = raw if c.get("mode", "join") == "raw" else joined(raw)
        for d in c["drops"]:
            m = text.count(d)
            if m != 1:
                problems.append("cut %d: drop matches %d times (needs 1): %r" % (n, m, d[:70]))
                continue
            text = text.replace(d, "", 1)
        if not c.get("allow_rule_edit"):
            after = squash(text)
            for s in splitlib.unit_sentences(squash(joined(raw))):
                if squash(s) not in after:
                    problems.append("cut %d: a rule sentence would not survive word for word: %r; "
                                    "keep it, or set allow_rule_edit on this cut" % (n, s[:90]))
        for ln in text.split("\n"):
            if "  " in ln.lstrip(" ") or ln != ln.rstrip(" "):
                problems.append("cut %d: a double or trailing space is left; widen a drop "
                                "by one space: %r" % (n, ln[:70]))
                break
        edits.append((i, j, n, k, text.split("\n")))
        moved.setdefault(c["archive"], {}).setdefault(c["heading"], []).append(raw)
    ordered = sorted(edits)
    for a, b in zip(ordered, ordered[1:]):
        if b[0] < a[1]:
            problems.append("cut %d and cut %d overlap (lines %d-%d and %d-%d); put both "
                            "drops in one cut on the outer unit" % (a[2], b[2], a[0] + 1, a[1],
                                                                     b[0] + 1, b[1]))
    if problems:
        raise Refused(problems)

    new = list(lines)
    for i, j, _, _, repl in sorted(edits, reverse=True):
        new[i:j] = repl
    touched = {k for _, _, _, k, _ in edits}
    pointer_added = False
    if pointer:
        nf = fences(new, "CLAUDE.md after the cut")
        if not any(ln == pointer["line"] and not nf[x] for x, ln in enumerate(new)):
            at = [x for x, ln in enumerate(new) if ln == pointer["after"] and not nf[x]]
            if len(at) != 1:
                raise Refused(["pointer: the \"after\" line occurs %d times outside code fences "
                               "(needs 1)" % len(at)])
            new.insert(at[0] + 1, pointer["line"])
            pointer_added = True
            # the section of the "after" line, counted in the ORIGINAL file
            orig_at = [x for x, ln in enumerate(lines) if ln == pointer["after"] and not fenced[x]]
            if len(orig_at) == 1:
                touched.add(owner(sp, orig_at[0]))
    new_text = "\n".join(new)

    writes, already, copied = {}, 0, 0
    for month, by_head in sorted(moved.items()):
        path = os.path.join(folder, "CLAUDE_DECISIONS_%s.md" % month)
        old = read(path) if splitlib.exists(path) else (
            "# Decisions Log Archive, %s\n\nEntries archived from `CLAUDE.md`. Index: `%s`.\n\n---\n"
            % (month, INDEX))
        block, n_new = [], 0
        for h, bodies in by_head.items():
            there = under_heading(old, h)
            fresh = [b for b in bodies if b not in there]
            already += len(bodies) - len(fresh)
            if not fresh:
                continue
            n_new += len(fresh)
            block += [h, "", "Units as they stood before the %s Phase D cut. The section and "
                      "its rules are still in CLAUDE.md." % today, ""] + fresh + [""]
        copied += n_new
        if n_new:
            head = ["", "", "<!-- Archived from CLAUDE.md on %s: full text of %d unit(s) whose story "
                    "sentences left CLAUDE.md (Phase D). The rule sentences stay in CLAUDE.md. -->"
                    % (today, n_new), ""]
            writes[path] = old.rstrip("\n") + "\n" + "\n".join(head + block).rstrip("\n") + "\n"

    # the checks on the planned texts
    bad = []
    hd = lambda s: [ln for ln in s.split("\n") if ln.startswith("#")]
    if hd(cm_text) != hd(new_text):
        bad.append("headings changed")
    extra = set(new_text) - set(cm_text)
    if extra:
        bad.append("new characters: %r" % sorted(extra))
    nl = new_text.split("\n")
    nsp = spans(nl, fences(nl, "CLAUDE.md after the cut"))
    if len(nsp) != len(sp):
        bad.append("section count changed: %d -> %d" % (len(sp), len(nsp)))
    else:
        for k, ((h, s, e), (h2, s2, e2)) in enumerate(zip(sp, nsp)):
            if k not in touched and lines[s:e] != nl[s2:e2]:
                bad.append("untouched section changed: %r (section %d)" % (h, k + 1))
    for month, by_head in moved.items():
        path = os.path.join(folder, "CLAUDE_DECISIONS_%s.md" % month)
        arch = writes.get(path) or read(path)
        for h, bodies in by_head.items():
            there = under_heading(arch, h)
            for body in bodies:
                if new_text.count(body):
                    bad.append("old text still in CLAUDE.md: %r" % body[:70])
                if body not in there:
                    bad.append("old text not under %r in %s: %r"
                               % (h, os.path.basename(path), body[:70]))
    if bad:
        raise Refused(bad)

    n_units = sum(len(v) for by in moved.values() for v in by.values())
    n_secs = len({h for by in moved.values() for h in by})
    idx = os.path.join(folder, INDEX)
    if splitlib.exists(idx):
        names = ", ".join("`CLAUDE_DECISIONS_%s.md`" % m for m in sorted(moved))
        row = ("- %s: Story sentences cut from %d unit(s) in %d kept section(s) (Phase D, rules kept); "
               "full text of %d copied under the same headings" % (today, n_units, n_secs, copied))
        if already:
            row += ", the other %d were already archived word for word" % already
        row += " - " + names
        old_idx = read(idx)
        if row not in old_idx:
            writes[idx] = old_idx.rstrip("\n") + "\n" + row + "\n"
    writes[cm] = new_text
    summary = {"before": len(cm_text), "after": len(new_text), "lines_before": len(lines),
               "lines_after": len(new), "units": n_units, "sections": n_secs,
               "copied": copied, "already": already, "pointer": pointer_added}
    return writes, summary


def after_checks(cm_text, writes, cm, accepts, roots):
    """The loss check and the pointer check, run on the planned texts before
    anything is written, the way rotate.py runs them: the planned archives and
    index are `present`, every other notes file is read from disk. Refused
    when an item is lost without an --accept waiver, or when the cut adds an
    unresolved pointer (old unresolved ones are counted, not refused).
    Returns the summary lines."""
    for v in accepts:
        msg = splitlib.refuse_empty_waiver("--accept", v)
        if msg:
            raise CannotTell(msg)
    for r in roots:
        if not os.path.isdir(r):
            raise CannotTell("--root folder missing: %s" % r)
    # write_all() replaces a symlink with a regular file, which the checks
    # below cannot model (they would read the link's target)
    links = sorted(os.path.basename(p) for p in writes if os.path.islink(p))
    if links:
        raise Refused(["a file the cut would write is a symlink: %s; write would replace "
                       "the link with a regular file" % ", ".join(links)])
    folder = os.path.dirname(cm)
    new_text = writes[cm]
    present = dict((os.path.basename(p), t) for p, t in writes.items() if p != cm)
    cache = {}
    try:
        lazy = [(p, splitlib.read_once(cache, p)) for p in splitlib.notes_set(folder, exclude=[cm])
                if os.path.basename(p) not in present]
        lazy += [(os.path.join(folder, n), t) for n, t in present.items()]
        results = splitlib.classify(cm_text, new_text, folder, lazy=lazy, hoisted=[],
                                    roots=(), present=present, cache=cache)
        wcounts = splitlib.apply_waivers(results, [('--accept "%s"' % v, v) for v in accepts])
        before = splitlib.pointers(cm_text, folder, roots, None, None, cache)
        after = splitlib.pointers(new_text, folder, roots, None, present, cache)
    except splitlib.UnclosedFence as e:
        raise CannotTell("a code fence opened at line %d never closes" % e.line)
    except (OSError, ValueError, UnicodeDecodeError) as e:
        raise CannotTell("the loss or pointer check could not read %s (%s)"
                         % (getattr(e, "filename", None) or "a notes file", type(e).__name__))
    bad = []
    if splitlib.unwaived_blocking(results):
        bad.append("loss check: an item would be lost (waive one with --accept \"<fragment>\"):")
        bad += ["  " + ln for ln in splitlib.listing_lines(results)]
    key = lambda p: (p.token, splitlib.section_name(p.section))
    old = [key(p) for p in before if p.status == "UNRESOLVED"]
    new = [p for p in after if p.status == "UNRESOLVED"]
    for p in new:
        if key(p) in old:
            old.remove(key(p))
        else:
            bad.append("pointer check: the cut adds an unresolved pointer: %s in section %s; %s"
                       % (p.token, splitlib.section_name(p.section), p.why))
    if bad:
        raise Refused(bad)
    counts = splitlib.class_counts(results)
    lines = ["loss check: " + ", ".join("%s %d" % (c, n) for c, n in counts.items())
             + " (nothing lost without a waiver)"]
    lines += splitlib.waiver_lines(wcounts)
    n_old = sum(1 for p in before if p.status == "UNRESOLVED")
    lines.append("pointer check: unresolved %d before, %d after, none new" % (n_old, len(new)))
    return lines


def write_all(writes, cm, today, no_backup):
    """Back up, then write every archive and the index, CLAUDE.md last. Each
    write goes to a temp file and is renamed over the target."""
    order = sorted(p for p in writes if p != cm) + [cm]
    if not no_backup:
        for p in order:
            b = backup(p, today)
            if b:
                print("backup  " + b)
    for p in order:
        tmp = p + ".phase_d.tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            fh.write(writes[p])
        os.replace(tmp, p)
        print("wrote   " + p)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("target")
    ap.add_argument("--spec", required=True)
    ap.add_argument("--today", default=datetime.date.today().isoformat())
    ap.add_argument("--write", action="store_true")
    ap.add_argument("--no-backup", action="store_true")
    ap.add_argument("--accept", action="append", default=[],
                    help="loss-check waiver: let through the items whose text holds this (repeatable)")
    ap.add_argument("--root", action="append", default=None,
                    help="another folder pointers resolve against (repeatable; default ~/.claude)")
    args = ap.parse_args(argv)
    cm = os.path.abspath(args.target)
    roots = args.root or [os.path.expanduser("~/.claude")]
    try:
        cuts, pointer = load_spec(args.spec)
        text = read(cm)
        writes, s = plan(text, cuts, pointer, cm, args.today)
        checked = after_checks(text, writes, cm, args.accept, roots)
    except CannotTell as e:
        print("CANNOT TELL: %s. Exit 2: nothing was written." % e)
        return 2
    except Refused as e:
        print("REFUSED (exit 3, nothing was written):")
        for p in e.args[0]:
            print("  " + p)
        return 3
    print("CLAUDE.md %d -> %d chars (%d -> %d lines)" % (s["before"], s["after"],
                                                         s["lines_before"], s["lines_after"]))
    print("units cut: %d in %d section(s); copied to archive: %d; already archived: %d; "
          "shared pointer line added: %s"
          % (s["units"], s["sections"], s["copied"], s["already"], "yes" if s["pointer"] else "no"))
    for ln in checked:
        print(ln)
    print("ALL CHECKS PASS")
    if not args.write:
        print("DRY RUN. Re-run with --write to write.")
        return 0
    try:
        write_all(writes, cm, args.today, args.no_backup)
    except OSError as e:
        print("CANNOT TELL: a write failed (%s). Exit 2: check the files named above "
              "against their backups." % type(e).__name__)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
