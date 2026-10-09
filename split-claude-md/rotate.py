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

    # 4. undo an applied run by its date or its run folder (dry run first)
    rotate.py <CLAUDE.md> --undo 2026-08-01
    rotate.py <CLAUDE.md> --undo split_2026-08-01 --apply

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

Before any write (split-no-loss): every run that moves
something writes split_<today>/REPORT.dry.md (dry run, or a refused --apply)
with open work that names a moving record, an in-memory loss check
and a pointer report that see this run's own archives and index.
--apply refuses (exit 3) a record open work names unless --keep or
--move-anyway names it, and a rule sentence that would leave CLAUDE.md:
each moving record's rule units are printed as draft lines to
paste above the moving records; a rule sentence not kept there, nor in an
accepted --hoisted file, is refused with a 'MISSING RULE: ' line unless
--narrative names its record. An applied run writes REPORT.md and
manifest.json in the run folder, one Last-run line in CLAUDE.md and a Runs
row in the index. --undo checks every hash and path first, then
restores each backup, deletes each file the run created and renames the run
folder <name>.undone; it never touches a file the manifest does not name.
"""
import argparse
import fnmatch
import hashlib
import json
import os
import re
import shlex
import shutil
import sys
from collections import OrderedDict, namedtuple
from datetime import date

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import splitlib  # noqa: E402

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


def backup(path, today, left=None):
    """A same-day backup of path, never over an existing one; None when path is
    absent (absence is FileNotFoundError, any other error rises).
    left: the backup's name is recorded before its copy starts and
    marked complete after the copy returns."""
    if not splitlib.exists(path):
        return None
    b = f"{path}.backup-before-split-{today}"
    n = 2
    while splitlib.exists(b):
        b = f"{path}.backup-before-split-{today}-{n}"
        n += 1
    if left is not None:
        left["paths"].append(b)
        left["backups"].add(b)
    shutil.copy2(path, b)
    if left is not None:
        left["done"].add(b)
    return b


def occurrences(haystack, needle):
    """Count occurrences, not lines. Records are often one very long line."""
    if not needle:
        return 0
    return haystack.count(needle)


FRAG_MARKER_RE = re.compile(r"^(?:[-*+] |\d+\. )")


def fragments_of(lines, start, end, kept=(), in_text=None, quiet=False):
    """Distinctive fragments of a record, for the both-directions check.

    Returns BOTH the title line and a body line whenever a body line exists.
    Checking the title alone is not enough: an off-by-one that removes the
    heading and orphans the body passes a title-only check while leaving the
    record's whole body behind. Checking the body alone is not enough either,
    since a heading left without its body also has to be caught. So both.

    kept: the record's rule sentences and rule units the rules draft found
    kept in the CLAUDE.md text outside the moving spans. A body line that is (with one
    list marker removed, or not) a substring of one of them is skipped, with a
    KEPT-RULE FRAGMENT SKIPPED line, and the next line over 40 chars is taken:
    a hoisted copy of that line legitimately stays in CLAUDE.md. With in_text
    (the CLAUDE.md move result) a line is skipped
    only when it also occurs there: a line not in CLAUDE.md cannot fail the
    check, so skipping it would only lose coverage. quiet suppresses the
    SKIPPED line (the predicted check, step 2).
    """
    out = []
    t = lines[start].rstrip("\n")
    if len(t) > 12:
        out.append(t)
    for j in range(start + 1, min(end, start + 12)):
        s = lines[j].strip()
        if len(s) > 40:
            cand = s[:160]
            forms = (cand, FRAG_MARKER_RE.sub("", cand, count=1))
            if (in_text is None or cand in in_text) and any(f in k for k in kept for f in forms):
                if not quiet:
                    print(f"  KEPT-RULE FRAGMENT SKIPPED: {t[:60]}")
                continue
            out.append(cand)
            break
    return out


def fragment_check(lines, to_move, to_keep, kept_of, arch_texts, arch_old, new_text, quiet):
    """Fragment counts, steps 2 and 4: one check, run on the
    in-memory texts (the prediction) and on the written archives (the verdict).

    A moved fragment passes when its count in its archive's text after the
    run (arch_texts) MINUS its count in that archive's text before the run
    (arch_old, "" for an archive the run creates) is exactly 1, and its count
    in the CLAUDE.md move result (new_text) is 0. A kept fragment passes at
    exactly 1 in new_text. Both dicts are keyed by archive file name. A moved
    record's body lines kept in CLAUDE.md (kept_of, keyed by the record's
    heading line) are skipped only when they occur in new_text.

    Returns (moved fragments, kept fragments, failures, already archived):
    failures are (failure line, fragment) pairs; already archived counts the
    moved fragments whose archive held them before the run.
    """
    fails, n_moved, n_kept, already = [], 0, 0, 0
    for s, e, dt, title in to_move:
        name = f"CLAUDE_DECISIONS_{dt[:7]}.md"
        for frag in fragments_of(lines, s, e, kept_of.get(title, ()), in_text=new_text, quiet=quiet):
            n_moved += 1
            n_after = occurrences(arch_texts[name], frag)
            n_before = occurrences(arch_old[name], frag)
            n_new = occurrences(new_text, frag)
            already += n_before > 0
            if not (n_after - n_before == 1 and n_new == 0):
                fails.append((f"FAIL moved  arch={n_after} before={n_before} claude={n_new}  "
                              f"{title[:60]}", frag))
    for s, e, dt, title, _ in to_keep:
        for frag in fragments_of(lines, s, e, quiet=quiet):
            n_kept += 1
            n_new = occurrences(new_text, frag)
            if n_new != 1:
                fails.append((f"FAIL kept   claude={n_new}  {title[:60]}", frag))
    return n_moved, n_kept, fails, already


# ---------------------------------------------------------------- rules draft

RuleSentence = namedtuple("RuleSentence", "text kept")
Draft = namedtuple("Draft", "heading title date sentences units")


def rules_draft(moving, outside_text, start_fenced=None):
    """The rules draft, one function so replays import it.

    moving: [(heading line, date, record text)] of the moving records;
    outside_text: the CLAUDE.md text outside the moving spans, as computed by
    the caller (never re-read from the folder). Returns one Draft per
    moving record, in order: its whole title, its date and two lists,
    each item with `kept` True when it is found in outside_text already:
    `sentences`, the rule sentences, which the refusal reads (one
    MISSING RULE line per sentence not kept); and `units`, the rule units
    which are the draft lines (a unit is kept only when every rule
    sentence in it is; its draft line then ends ' [already kept]').

    start_fenced (reading part of a text never raises): one start state per moving
    record, the whole text's fence state at its first line
    (splitlib.fence_start); None, the default, reads every record from outside
    a fence, so a 3-tuple caller measures what it measured before.
    """
    outside = splitlib.Text(outside_text)
    out = []
    for k, (heading, dt, text) in enumerate(moving):
        st = start_fenced[k] if start_fenced else False
        seen, sents = set(), []
        for it in splitlib.atoms(text, start_fenced=st):
            if it.kind == "rule" and it.text not in seen:
                seen.add(it.text)
                # the window match alone decides a verdict (a token match lists, never keeps)
                sents.append(RuleSentence(it.text, splitlib.window_kept(it.text, outside)))
        units = [RuleSentence(u, splitlib.unit_kept(u, outside))
                 for u in splitlib.rule_units(text, start_fenced=st)]
        out.append(Draft(heading, whole_title(heading), dt, sents, units))
    return out


def draft_line(draft, sent):
    """'- <unit> (kept from "<title>", <date>)', plus ' [already kept]'."""
    return ('- %s (kept from "%s", %s)%s'
            % (sent.text, draft.title, draft.date, " [already kept]" if sent.kept else ""))


# ---------------------------------------------------------------- open work, run folder, index

INDEX_NAME = "CLAUDE_DECISIONS_INDEX.md"
RUNS_HEADING = "## Runs"
RUNS_HEADER = "| Date | Before | After | Records | Report |\n| --- | --- | --- | --- | --- |\n"
ENTRIES_HEADING = "## Entries (chronological)"
OPEN_WORK_PATTERNS = ("TODO.md", "*HANDOFF*.md", "*PLAN*.md")
REUSABLE = (["REPORT.dry.md"], ["QUESTIONS.md", "REPORT.dry.md"])

Hit = namedtuple("Hit", "source ordinal text key")


def whole_title(heading):
    """The heading line without its leading '#'s and the space after them."""
    return re.sub(r"^#+ ", "", heading.rstrip("\n")).strip()


def open_work_files(folder):
    """The OPEN_WORK_PATTERNS files at the top level of the folder
    (regular files only)."""
    out = []
    for name in sorted(os.listdir(folder)):
        p = os.path.join(folder, name)
        # the name first: only an open-work file is stat'ed (a disk error rises)
        if any(fnmatch.fnmatchcase(name, pat) for pat in OPEN_WORK_PATTERNS) and splitlib.is_file(p):
            out.append(p)
    return out


def open_work(folder, todo_files, moving, before_text, convention):
    """The open-work matcher, one function so replays import it.

    folder: the CLAUDE.md folder (its open-work files are read); todo_files:
    the --todo files (read too); moving: [(heading line, record text)];
    before_text: the CLAUDE.md text being split, as read before any write. A
    key counts only when it is in at most 2 records of before_text (never of
    the folder's CLAUDE.md) and in at most 5 open items. Returns, per
    moving record in order, (heading line, [Hit(source, ordinal, text, key)]).
    """
    paths, seen = [], set()
    for p in open_work_files(folder) + list(todo_files):
        rp = os.path.realpath(p)
        if rp not in seen:
            seen.add(rp)
            paths.append(p)
    items = splitlib.open_items(paths)
    blines = before_text.splitlines(keepends=True)
    records = ["".join(blines[s:e]) for s, e, _, _ in parse_records(blines, convention)]
    distinct = {}

    def distinctive(kind, key):
        if (kind, key) not in distinct:
            in_recs = sum(1 for r in records if splitlib.key_in(kind, key, r))
            in_items = sum(1 for it in items if splitlib.key_in(kind, key, it.text))
            distinct[(kind, key)] = in_recs <= 2 and in_items <= 5
        return distinct[(kind, key)]

    out = []
    for heading, text in moving:
        keys = splitlib.record_keys(whole_title(heading), text)
        hits = []
        for it in items:
            for kind, key in keys:
                if splitlib.key_in(kind, key, it.text) and distinctive(kind, key):
                    hits.append(Hit(it.source, it.ordinal, it.text, key))
                    break
        out.append((heading, hits))
    return out


def resolve_waiver(value, moving):
    """The moving records a --move-anyway or --narrative value
    names. A whole-title match wins; otherwise substring. Case-insensitive,
    trimmed. Two or more records back means ambiguous."""
    v = value.strip().lower()
    whole = [r for r in moving if whole_title(r[3]).lower() == v]
    if whole:
        return whole
    return [r for r in moving if v in whole_title(r[3]).lower()]


def pick_run_folder(folder, today):
    """split_<today>, then -2, -3 ...;
    the first name that does not exist, or is a folder whose entries
    (ignoring .DS_Store) are exactly REPORT.dry.md, or REPORT.dry.md and
    QUESTIONS.md. Any other existing name is skipped."""
    n = 1
    while True:
        name = "split_%s" % today if n == 1 else "split_%s-%d" % (today, n)
        p = os.path.join(folder, name)
        if not splitlib.exists(p):              # a disk error rises
            return name
        if splitlib.is_dir(p) and sorted(e for e in os.listdir(p) if e != ".DS_Store") in REUSABLE:
            return name
        n += 1


def kchars(n):
    return "%dK" % ((n + 500) // 1000)


def last_run_slot(lines, convention):
    """Placement, first match wins: (1) an existing Last-run
    line outside every record span is replaced; (2) the line after a '## ' or
    '### ' heading holding "Maintenance rule", outside every span; (3) its own
    line plus a blank, before the first dated record's heading; (4) end of
    file. Returns (placement, index). A fenced line is never the slot (a
    fenced 'Last split run:' example or '## Maintenance rule' heading)."""
    spans = [(s, e) for s, e, _, _ in parse_records(lines, convention)]
    fenced = splitlib.fence_states(lines)[0]

    def inside(i):
        return any(s <= i < e for s, e in spans)

    for i, ln in enumerate(lines):
        if not fenced[i] and ln.startswith(splitlib.LAST_RUN_PREFIX) and not inside(i):
            return 1, i
    for i, ln in enumerate(lines):
        if (not fenced[i] and ln.startswith(("## ", "### ")) and "Maintenance rule" in ln
                and not inside(i)):
            return 2, i + 1
    if spans:
        return 3, spans[0][0]
    return 4, len(lines)


def place_last_run(lines, placement, i, line):
    out = list(lines)
    if placement == 1:
        out[i] = line + "\n"
    elif placement == 3:
        out[i:i] = [line + "\n", "\n"]
    else:
        if placement == 4 and out and not out[-1].endswith("\n"):
            out[-1] += "\n"
        out.insert(i, line + "\n")
    return out


def add_runs_row(idx, row):
    """Runs table: '## Runs' sits before the entries
    heading; the row goes after the section's last table line."""
    lines = idx.splitlines(keepends=True)
    if any(l.rstrip("\n") == RUNS_HEADING for l in lines):
        h = next(i for i, l in enumerate(lines) if l.rstrip("\n") == RUNS_HEADING)
        end = next((j for j in range(h + 1, len(lines)) if lines[j].startswith("## ")), len(lines))
        tbl = [j for j in range(h + 1, end) if lines[j].startswith("|")]
        if tbl:
            lines.insert(tbl[-1] + 1, row)
        else:
            lines[h + 1:h + 1] = ["\n", RUNS_HEADER, row]
        return "".join(lines)
    block = RUNS_HEADING + "\n\n" + RUNS_HEADER + row + "\n"
    e = next((i for i, l in enumerate(lines) if l.rstrip("\n") == ENTRIES_HEADING), None)
    if e is not None:
        lines.insert(e, block)
        return "".join(lines)
    return idx.rstrip("\n") + "\n\n" + block


def index_final(existing, convention, buckets, rows, runs_row):
    """The index text this run writes (step 2), computed in memory. The
    Runs row and the entry rows each go at the end of their own section."""
    if existing is None:
        return ("# Decisions Log Index\n\n"
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
                f"This project's decision-log records are whole dated `{'## ' if convention == 'section' else '### '}` "
                "headings. Future `/split-claude-md` runs must use that pattern, not the default.\n\n"
                "## Archives\n"
                + "".join(f"- `CLAUDE_DECISIONS_{m}.md` - {len(r)} entries\n" for m, r in buckets.items())
                + "\n" + RUNS_HEADING + "\n\n" + RUNS_HEADER + runs_row
                + "\n" + ENTRIES_HEADING + "\n\n" + "".join(rows))
    idx = add_runs_row(existing, runs_row)
    # Entry rows go at the END OF THE ENTRIES SECTION (after its last
    # non-blank line, before the next '## ' or EOF), never at end of file
    lines = idx.splitlines(keepends=True)
    e = next((i for i, l in enumerate(lines) if l.rstrip("\n") == ENTRIES_HEADING), None)
    if e is None:
        return idx.rstrip("\n") + "\n\n" + ENTRIES_HEADING + "\n\n" + "".join(rows)
    end = next((j for j in range(e + 1, len(lines)) if lines[j].startswith("## ")), len(lines))
    last = max(j for j in range(e, end) if lines[j].strip())
    if not lines[last].endswith("\n"):
        lines[last] += "\n"
    lines[last + 1:last + 1] = rows
    return "".join(lines)


def read_text(path):
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def cannot_tell(msg, tail="Exit 2: nothing was checked or written."):
    print("CANNOT TELL: " + msg)
    print(tail)
    return 2


def err_name(e, default):
    """The path a disk error carries, else `default` (the cannot-tell
    line names the path the exception carries)."""
    return getattr(e, "filename", None) or default


def pre_manifest_failure(e, left):
    """The one cannot-tell text for any disk, value or decode error
    before the pending manifest. It names the path the error carries (or its
    type), then every recorded leftover that exists, a backup whose copy did not
    return marked (not complete), or says nothing was changed. Nothing is
    deleted."""
    fn = getattr(e, "filename", None)
    what = "%s (%s)" % (fn, type(e).__name__) if fn else type(e).__name__
    names = []
    for p in left["paths"]:
        if os.path.lexists(p) and p not in [n.split(" (not complete)")[0] for n in names]:
            part = p in left["backups"] and p not in left["done"]
            names.append(p + (" (not complete)" if part else ""))
    head = "%s; CLAUDE.md, the archives and the index were not written; " % what
    if names:
        return head + "left in place, nothing deleted: " + ", ".join(names)
    return head + "nothing was changed"


def report_text(mode, ctx):
    """REPORT.dry.md / REPORT.md, sections in the data model order.
    Files sent (the recall check) is not written yet."""
    c = ctx
    out = ["Mode: " + mode, ""]
    out += ["## Summary", "",
            "- file: %s" % c["path"],
            "- convention %s, cut date %s, today %s" % (c["convention"], c["cut"], c["today"]),
            "- chars before %d, after %d (without the Last-run line)" % (c["before_chars"], c["after_chars"]),
            "- records: %d dated, %d move, %d keep" % (c["n_records"], len(c["to_move"]), len(c["to_keep"])),
            "- run folder: %s" % c["run_name"],
            "- verdict: %s" % c["verdict"],
            "- fragment check predicted for --apply: %d fragment(s), %d failure(s)"
            % (c["pred"][0], len(c["pred"][1]))]
    out += ["  - %s" % f for f in c["pred"][1]] + [""]
    out += ["## Move", ""]
    for (s, e, dt, title), dens in zip(c["to_move"], c["density"]):
        out.append("- %s %s (%d chars; %s, obligation %.2f, reference %.2f)"
                   % (dt, whole_title(title), c["chars"][(s, e)], dens[0], dens[1], dens[2]))
    out += ["none"] if not c["to_move"] else []
    out += ["", "## Keep", ""]
    for s, e, dt, title, why in c["to_keep"]:
        out.append("- %s %s [%s]" % (dt, whole_title(title), why))
    out += ["none"] if not c["to_keep"] else []
    out += ["", "## Open-work evidence", ""]
    any_ow = False
    for heading, hits in c["open_work"]:
        if not hits:
            continue
        any_ow = True
        state = ("waived by %s" % c["anyway_label"][heading]) if heading in c["anyway_label"] \
            else "refused on --apply"
        out.append("%s (%d open item(s); %s)" % (whole_title(heading), len(hits), state))
        for h in hits:
            out.append("- %s item %d: %s (key: `%s`)" % (os.path.basename(h.source), h.ordinal, h.text, h.key))
    if not any_ow:
        out.append("none: no open item names a moving record by a distinctive key")
    out += ["", "## Rules draft", ""]
    dl = [draft_line(dr, u) for dr in c["drafts"] for u in dr.units]
    out += dl or ["none: the moving records hold no rule sentence"]
    if any(u.kept for dr in c["drafts"] for u in dr.units):
        out += ["", "A line ending [already kept] is kept outside the moving records already; "
                "do not paste it."]
    if c["missing_rules"]:
        out.append("")
        out += ["MISSING RULE: " + s.text for _, s in c["missing_rules"]]
    out += ["", "## Loss check", ""]
    out += ["- %s: %d" % (k, n) for k, n in splitlib.class_counts(c["results"]).items()]
    out += [""] + splitlib.listing_lines(c["results"])
    out += ["%s: %s" % (r.label(), r.item.text) for r in c["results"]
            if r.cls in ("POINTED", "POINTED (archive)")]
    # A KEPT (hoisted) item names its --hoisted file, as loss_check.py's report does
    out += ["%s: %s" % (r.label(), r.item.text) for r in c["results"] if r.cls == "KEPT (hoisted)"]
    out += splitlib.waiver_lines(c["accept_counts"])
    out.append("%d blocking item(s) not waived" % len(c["blocking"]))
    out += ["", "## Pointers", ""]
    if c["unresolved"]:
        for p in c["unresolved"]:
            out.append("- UNRESOLVED: `%s` in section %s (line %d); %s"
                       % (p.token, splitlib.section_name(p.section), p.lineno, p.why))
    else:
        out.append("none: every pointer of the after text resolves (%d checked)" % c["n_pointers"])
    out += ["", "## Waivers", ""]
    wl = []
    for v, recs in c["anyway"]:
        if recs:
            r = recs[0]
            hits = c["hits_of"].get(r[3], [])
            wl.append('- --move-anyway "%s": %s (let through 1 record, %d open item(s))'
                      % (v, whole_title(r[3]), len(hits)))
            wl += ["  - %s" % h.text for h in hits]
        else:
            wl.append('- UNUSED WAIVER: --move-anyway "%s" matched no moving record' % v)
    nar_owner = {}
    for v, recs in c["narrative"]:
        label = '--narrative "%s"' % v
        if recs and recs[0][3] in nar_owner:
            # a second --narrative for a record already named lets nothing through
            wl.append("- UNUSED WAIVER: %s let through no item (every match already waived by %s)"
                      % (label, nar_owner[recs[0][3]]))
        elif recs:
            # one name lets the record through the rules draft and the loss check: both lists, once each
            h = recs[0][3]
            nar_owner[h] = label
            let = list(c["nar_let"].get(h, [])) if c["nar_label"].get(h) == label else []
            let += [r.item.text for r in c["results"] if r.waiver == label and r.item.text not in let]
            wl.append("- %s: %s (let through %d item(s))" % (label, whole_title(h), len(let)))
            wl += ["  - %s" % t for t in let]
        else:
            wl.append("- UNUSED WAIVER: %s matched no moving record" % label)
    for label, v, n, broad, owners in c["accept_counts"]:
        if n:
            wl.append("- %s (let through %d item(s))" % (label, n))
        elif owners:
            wl.append("- UNUSED WAIVER: %s let through no item (every match already waived by %s)"
                      % (label, ", ".join(owners)))
        else:
            wl.append("- UNUSED WAIVER: %s matched no item" % label)
        if broad:
            wl.append("  BROAD WAIVER: more than %d items" % splitlib.BROAD_LIMIT)
        if n:       # an entry that let nothing through lists no item
            wl += ["  - %s" % r.item.text for r in c["results"] if r.waiver == label]
    out += wl or ["none"]
    if c.get("backups") is not None:
        out += ["", "## Backups", ""]
        out += ["- %s" % b for b in c["backups"]] or ["none"]
    return "\n".join(out) + "\n"


Final = namedtuple("Final", "buckets arch_final arch_exists index_old new_lines new_text final_lines "
                            "final_text last_line line_at before_chars after_chars rows runs_row idx_final "
                            "arch_old origin", defaults=(None,))


def build_final(lines, d, to_move, convention, today, before_chars, run_name):
    """Step 2: every text the run would write, made once, in memory,
    on a dry run and on --apply alike: each archive (appended or created), the
    index with its entry rows and Runs row, and CLAUDE.md's final text with its
    Last-run line placed, plus each archive's text before this run (arch_old,
    "" for an archive the run creates). Raises OSError or UnicodeDecodeError on
    an unreadable archive or index."""
    buckets = OrderedDict()
    for s, e, dt, title in to_move:
        buckets.setdefault(dt[:7], []).append((s, e, dt, title))
    arch_final, arch_exists, arch_old = OrderedDict(), {}, {}
    for month, recs in buckets.items():
        name = f"CLAUDE_DECISIONS_{month}.md"
        ap_path = os.path.join(d, name)
        exists = splitlib.exists(ap_path)       # a disk error rises
        arch_exists[name] = exists
        body = [read_text(ap_path)] if exists else []
        arch_old[name] = body[0] if exists else ""      # the archive before this run
        if not exists:
            y, mo = month.split("-")
            body.append(ARCHIVE_HEADER.format(month_name=MONTHS[int(mo)], year=y, today=today))
        else:
            body.append(f"\n<!-- Archived from CLAUDE.md on {today} (additional rotation). -->\n")
        for s, e, dt, title in recs:
            body.append("".join(lines[s:e]).rstrip("\n") + "\n\n")
        arch_final[name] = "".join(body)
    index_path = os.path.join(d, INDEX_NAME)
    index_old = read_text(index_path) if splitlib.exists(index_path) else None

    drop = set()
    for s, e, _, _ in to_move:
        drop.update(range(s, e))
    keep = [i for i in range(len(lines)) if i not in drop]
    new_lines = [lines[i] for i in keep]
    # One Last-run line. Step 1 already took every one out of the
    # record spans; of those outside, the first is placement (1)'s slot
    # and every later one goes. Only the line: a blank after it stays, which
    # is what the structure check compares (it drops Last-run lines alone).
    # A fenced 'Last split run:' example is neither.
    fenced = splitlib.fence_states(new_lines)[0]
    stale = set([i for i, ln in enumerate(new_lines)
                 if not fenced[i] and ln.startswith(splitlib.LAST_RUN_PREFIX)][1:])
    new_lines = [ln for i, ln in enumerate(new_lines) if i not in stale]
    keep = [k for i, k in enumerate(keep) if i not in stale]
    new_text = "".join(new_lines)   # the move result, read by the fragment check

    placement, slot = last_run_slot(new_lines, convention)
    without = [ln for i, ln in enumerate(new_lines) if not (placement == 1 and i == slot)]
    after_chars = len("".join(without))
    last_line = (f"{splitlib.LAST_RUN_PREFIX} {today}, {kchars(before_chars)} to "
                 f"{kchars(after_chars)} chars, {len(to_move)} records moved to "
                 f"`{INDEX_NAME}`, report {run_name}/REPORT.md")
    final_lines = place_last_run(new_lines, placement, slot, last_line)
    # origin: each final line's index in `lines`, None for a line this run adds
    origin = (keep if placement == 1 else
              keep[:slot] + [None] * (2 if placement == 3 else 1) + keep[slot:])
    rows = [f"- {dt}: {title.lstrip('#').strip()} - `CLAUDE_DECISIONS_{dt[:7]}.md`\n"
            for _, _, dt, title in sorted(to_move, key=lambda r: r[2])]
    runs_row = f"| {today} | {before_chars} | {after_chars} | {len(to_move)} | {run_name}/REPORT.md |\n"
    idx_final = index_final(index_old, convention, buckets, rows, runs_row)
    # every placement inserts or replaces AT slot (placement (2)'s slot is the
    # line after its heading already)
    return Final(buckets, arch_final, arch_exists, index_old, new_lines, new_text, final_lines,
                 "".join(final_lines), last_line, slot, before_chars, after_chars, rows, runs_row,
                 idx_final, arch_old, origin)


def last_run_outside(fin, convention):
    """The internal assertion. The placed line is
    where the placement says, it is the only Last-run line, and it is
    outside every parse_records span of the final text. False is a bug in
    rotate.py, never a finding about the notes."""
    fl, i = fin.final_lines, fin.line_at
    if not (0 <= i < len(fl)) or fl[i].rstrip("\n") != fin.last_line:
        return False
    fenced = splitlib.fence_states(fl)[0]       # a fenced example is not a second one
    if sum(1 for k, ln in enumerate(fl)
           if not fenced[k] and ln.startswith(splitlib.LAST_RUN_PREFIX)) != 1:
        return False                                            # exactly one
    return not any(s <= i < e for s, e, _, _ in parse_records(fl, convention))


def write_report(run_dir, name, text):
    """REPORT.dry.md (step 3) or REPORT.md (step 6)."""
    with open(os.path.join(run_dir, name), "w", encoding="utf-8") as fh:
        fh.write(text)


def write_manifest(run_dir, manifest):
    """Every manifest write (pending and complete) goes to manifest.json.tmp
    in the same run folder, then os.replace onto manifest.json, so a reader sees
    the old manifest or the new one, never a torn one. Same folder, so same file
    system. POSIX rename(), read 2026-10-07
    (pubs.opengroup.org/onlinepubs/9799919799/functions/rename.html): "if the
    directory entry named by new exists, it shall be removed and old renamed to
    new. In this case, a directory entry named new shall remain visible to other
    threads throughout the renaming operation and refer either to the file
    referred to by new or old before the operation began." On a failed rename
    the temp file is removed and the error raised."""
    tmp = os.path.join(run_dir, "manifest.json.tmp")
    try:
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(manifest, fh, indent=2)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, os.path.join(run_dir, "manifest.json"))
    except BaseException:
        if os.path.lexists(tmp):
            os.remove(tmp)
        raise


# ---------------------------------------------------------------- undo

UNDO_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
UNDONE_RE = re.compile(r"\.undone(?:-\d+)?$")


def contained(base, p):
    """p sits inside base. Both sides are realpath'd by the caller;
    commonpath, never startswith (SEC-PATH-01)."""
    return os.path.commonpath([p, base]) == base


def file_state(p):
    """None when p does not exist, the sha256 of a regular file, else a marker
    that equals no hash. Absence is FileNotFoundError; any other disk
    error rises."""
    if not splitlib.lexists(p):
        return None
    if not splitlib.is_file(p):
        return "not a regular file"
    return splitlib.sha256(p)


def undo_matches(base, value):
    """A date matches only split_<date> or split_<date>-<n> folders that
    hold a manifest; any other value is one run folder, resolved against the
    project folder. A folder already marked undone never matches."""
    if UNDO_DATE_RE.match(value):
        pat = re.compile(r"^split_%s(?:-(\d+))?$" % re.escape(value))
        found = []
        for n in os.listdir(base):
            m = pat.match(n)
            if m and splitlib.is_file(os.path.join(base, n, "manifest.json")):
                found.append((int(m.group(1) or 1), n))
        return [n for _, n in sorted(found)]
    rd = os.path.realpath(os.path.join(base, value))
    if (rd != base and contained(base, rd) and not UNDONE_RE.search(rd)
            and splitlib.is_file(os.path.join(rd, "manifest.json"))):
        return [os.path.relpath(rd, base)]
    return []


def manifest_problem(man):
    """Why a manifest cannot be read as the data model's shape, or None."""
    if not isinstance(man, dict) or man.get("status") not in ("pending", "complete"):
        return "its status is neither pending nor complete"
    files = man.get("files")
    if not isinstance(files, list) or not files:
        return "it lists no files"
    for f in files:
        if not isinstance(f, dict) or not isinstance(f.get("path"), str) or not f["path"]:
            return "an entry has no path"
        if not isinstance(f.get("post_sha256"), str):
            return "%s has no post_sha256" % f["path"]
        if "pre_sha256" not in f or "backup" not in f:
            return "%s has no pre_sha256 or backup key" % f["path"]
        pre, bk = f.get("pre_sha256"), f.get("backup")
        if not (pre is None or isinstance(pre, str)) or not (bk is None or isinstance(bk, str)):
            return "%s has a malformed pre_sha256 or backup" % f["path"]
        if (pre is None) != (bk is None):
            return "%s has a pre_sha256 without a backup, or a backup without a pre_sha256" % f["path"]
    return None


def undone_name(run_dir):
    """The name a finished undo gives the run folder: <run>.undone, then
    .undone-2, -3 ... on a clash (os.path.lexists), so it never lands inside an
    existing folder."""
    new = run_dir + ".undone"
    n = 2
    while os.path.lexists(new):
        new = "%s.undone-%d" % (run_dir, n)
        n += 1
    return new


def half_done(first, actions, put_back, deleted, run_dir):
    """A stated limit of undo: the exit-2 message of an undo that
    stopped after --apply began to change files. It keeps its first line, then
    lists in manifest order each file put back (PUT BACK) or deleted (DELETED),
    each RESTORE not put back (NOT PUT BACK, the failed one included) with the
    cp command that restores it, and each created file still there (NOT
    DELETED); then the closing lines and the mv that marks the run undone.
    Every path is the realpath undo checked, shell-quoted. A LEAVE file is in
    neither list. Returns 2."""
    q = shlex.quote
    print(first)
    for i, (kind, f, tgt, bk) in enumerate(actions):
        if kind == "RESTORE" and i in put_back:
            print("PUT BACK: %s" % q(tgt))
        elif kind == "DELETE" and i in deleted:
            print("DELETED: %s" % q(tgt))
    for i, (kind, f, tgt, bk) in enumerate(actions):
        if kind == "RESTORE" and i not in put_back:
            print("NOT PUT BACK: %s" % q(tgt))
            print("  cp -p %s %s" % (q(bk), q(tgt)))
    for i, (kind, f, tgt, bk) in enumerate(actions):
        if kind == "DELETE" and i not in deleted:
            print("NOT DELETED: %s (created by the run; delete it by hand)" % q(tgt))
    rr = os.path.realpath(run_dir)
    print("The run folder keeps its name; finish the rest by hand with the lines above "
          "(this message offers no re-run).")
    print("When every line above is done, mark the run undone with:")
    print("  mv %s %s" % (q(rr), q(undone_name(rr))))
    return 2


def refuse(lines):
    for ln in lines:
        print("REFUSED: " + ln)
    print("Exit 3: nothing was changed.")
    return 3


def undo(path, value, apply):
    """Undo one applied run. Every check runs before any change
    (undo_checks); a dry run lists what it would restore and delete; --apply
    copies each backup back (its hash verified after), deletes each created
    file, and renames the run folder <name>.undone (-2, -3 on a clash). It
    never touches a file the manifest does not name."""
    try:
        res = undo_checks(path, value, apply)
    except (OSError, ValueError, UnicodeDecodeError) as e:     # undo's error boundary
        fn = getattr(e, "filename", None)
        return cannot_tell("%s; nothing was changed" % ("%s (%s)" % (fn, type(e).__name__) if fn
                                                        else type(e).__name__))
    if isinstance(res, int):
        return res
    actions, run_dir, run_rel = res
    put_back, deleted = set(), set()    # indexes into actions that finished
    try:
        for i, (kind, f, tgt, bk) in enumerate(actions):
            if kind == "RESTORE":
                shutil.copy2(bk, tgt)
                if file_state(tgt) != f["pre_sha256"]:
                    return half_done(
                        "*** RESTORE of %s did not verify: it is not at its pre_sha256. The run "
                        "folder keeps its name; the backup %s is untouched. Exit 2. ***"
                        % (f["path"], f["backup"]), actions, put_back, deleted, run_dir)
                put_back.add(i)
        for i, (kind, f, tgt, bk) in enumerate(actions):
            if kind == "DELETE":
                os.remove(tgt)
                deleted.add(i)
        new = undone_name(run_dir)
        os.rename(run_dir, new)
    except OSError as e:
        return half_done("*** The undo stopped part way (%s). The backups named in %s/manifest.json "
                         "are untouched. Exit 2. ***" % (type(e).__name__, run_rel),
                         actions, put_back, deleted, run_dir)
    print("UNDONE: restored %d, deleted %d, left %d; run folder renamed %s"
          % (sum(a[0] == "RESTORE" for a in actions), sum(a[0] == "DELETE" for a in actions),
             sum(a[0] == "LEAVE" for a in actions), os.path.basename(new)))
    return 0


def undo_checks(path, value, apply):
    """The undo error boundary: everything undo does before its first change
    (the match, the manifest read, containment, every hash check, the plan
    printed). Returns an exit code (a refusal, a cannot-tell, or the dry run's
    0), or (actions, run folder, its name) for --apply. `path` is the file
    argument as given: it is made absolute here, inside the segment, because
    os.path.abspath calls os.getcwd(), which fails in a deleted working folder."""
    path = os.path.abspath(path)
    base = os.path.realpath(os.path.dirname(path))
    if not os.path.isdir(base):
        return cannot_tell("folder missing: %s" % base)
    try:
        matches = undo_matches(base, value)
    except OSError as e:
        return cannot_tell("%s is unreadable (%s); nothing was changed" % (err_name(e, base), type(e).__name__))
    if not matches:
        return refuse(['no run folder with a manifest matches --undo "%s" in %s (a folder '
                       'already undone never matches)' % (value, base)])
    if len(matches) > 1:
        print('REFUSED: --undo "%s" matches %d run folders:' % (value, len(matches)))
        for n in matches:
            print("  " + n)
        print("Name one with --undo <dir>. Exit 3: nothing was changed.")
        return 3
    run_rel = matches[0]
    run_dir = os.path.join(base, run_rel)
    try:
        with open(os.path.join(run_dir, "manifest.json"), encoding="utf-8") as fh:
            man = json.load(fh)
    except (OSError, ValueError, UnicodeDecodeError) as e:
        return cannot_tell("%s is unreadable (%s); nothing was changed"
                           % (err_name(e, run_rel + "/manifest.json"), type(e).__name__))
    why = manifest_problem(man)
    if why:
        return cannot_tell("%s/manifest.json: %s" % (run_rel, why))
    status = man["status"]

    # containment, both sides resolved (SEC-PATH-01)
    entries, outside = [], []
    for f in man["files"]:
        tgt = os.path.realpath(os.path.join(base, f["path"]))
        bk = None if f["backup"] is None else os.path.realpath(os.path.join(base, f["backup"]))
        if not contained(base, tgt):
            outside.append("%s resolves outside the folder %s" % (f["path"], base))
        if bk is not None and not contained(base, bk):
            outside.append("%s (backup of %s) resolves outside the folder %s" % (f["backup"], f["path"], base))
        entries.append((f, tgt, bk))
    if outside:
        return refuse(outside)

    # hash checks, all before any change
    actions, problems = [], []
    for f, tgt, bk in entries:
        try:
            st = file_state(tgt)
        except OSError as e:
            return cannot_tell("%s is unreadable (%s); nothing was changed" % (err_name(e, tgt), type(e).__name__))
        if st == f["post_sha256"]:
            actions.append(("RESTORE" if f["pre_sha256"] else "DELETE", f, tgt, bk))
        elif status == "pending" and st == f["pre_sha256"]:
            actions.append(("LEAVE", f, tgt, bk))
        elif status == "complete":
            problems.append("%s is %s, not at the hash this run wrote"
                            % (f["path"], "missing" if st is None else "changed"))
        else:
            problems.append("%s is at neither hash (pre or post): it changed after the run" % f["path"])
        if bk is not None:
            try:
                bst = file_state(bk)
            except OSError as e:
                return cannot_tell("%s is unreadable (%s); nothing was changed"
                                   % (err_name(e, bk), type(e).__name__))
            if bst != f["pre_sha256"]:
                problems.append("backup %s of %s is %s, not at its pre_sha256"
                                % (f["backup"], f["path"], "missing" if bst is None else "changed"))
    if problems:
        return refuse(problems)

    print("UNDO %s (manifest status %s)" % (run_rel, status))
    for kind, f, tgt, bk in actions:
        if kind == "RESTORE":
            print("  RESTORE %s from %s" % (f["path"], f["backup"]))
        elif kind == "DELETE":
            print("  DELETE  %s (created by the run)" % f["path"])
        else:
            print("  LEAVE   %s: not written by the run (still at its pre_sha256), left alone" % f["path"])
    if not apply:
        print("DRY RUN. Re-run with --apply to undo. Nothing was changed.")
        return 0
    return actions, run_dir, run_rel



def main():
    ap = argparse.ArgumentParser(description="Phase A rotation for /split-claude-md.")
    ap.add_argument("file")
    ap.add_argument("--convention", choices=["entry", "section"], help="required unless --undo")
    ap.add_argument("--cut-date", help="records strictly before this date are candidates "
                                       "(required unless --undo)")
    ap.add_argument("--keep", action="append", default=[],
                    help="substring of a record title to KEEP despite its age (repeatable)")
    ap.add_argument("--apply", action="store_true", help="actually write (default: dry run)")
    ap.add_argument("--today", default=date.today().isoformat())
    ap.add_argument("--todo", action="append", default=[],
                    help="another file of open '- [ ]' items to read (repeatable)")
    ap.add_argument("--move-anyway", action="append", default=[],
                    help="move this one record although open work names it")
    ap.add_argument("--accept", action="append", default=[],
                    help="waive the loss-check items whose text holds this")
    ap.add_argument("--narrative", action="append", default=[],
                    help="this one record's rule sentences may leave CLAUDE.md")
    ap.add_argument("--hoisted", action="append", default=[],
                    help="another always-loaded CLAUDE.md that holds hoisted rule "
                         "sentences (repeatable; only some files count)")
    ap.add_argument("--root", action="append", default=None,
                    help="a folder pointers resolve against (repeatable; default ~/.claude)")
    ap.add_argument("--undo", default=None, metavar="DATE|DIR",
                    help="undo an applied run, named by its date or its run folder; "
                         "a dry run unless --apply")
    args = ap.parse_args()
    # The two flags are required only without --undo, with argparse's own text
    if args.undo is not None:
        given = [f for f, v in (("--convention", args.convention), ("--cut-date", args.cut_date),
                                ("--keep", args.keep), ("--hoisted", args.hoisted),
                                ("--narrative", args.narrative), ("--move-anyway", args.move_anyway))
                 if v is not None and v != []]
        if given:
            ap.error("--undo cannot be combined with %s" % ", ".join(given))
        return undo(args.file, args.undo, args.apply)
    missing = [f for f, v in (("--convention", args.convention), ("--cut-date", args.cut_date))
               if v is None]
    if missing:
        ap.error("the following arguments are required: %s" % ", ".join(missing))
    # the pre-manifest segment runs inside one error boundary
    left = {"paths": [], "backups": set(), "done": set()}
    try:
        st = before_manifest(args, left)
    except (OSError, ValueError, UnicodeDecodeError) as e:     # rotate.py's error boundary
        return cannot_tell(pre_manifest_failure(e, left), "Exit 2.")
    if isinstance(st, int):
        return st
    return after_manifest(st)


AFTER_KEYS = ("path", "d", "run_name", "run_dir", "arch_final", "arch_exists", "index_path", "idx_final", "index_old", "rows", "lines", "to_move", "to_keep", "kept_of", "fin", "original", "new_text", "manifest", "ctx", "backups", "final_text")


def before_manifest(args, left):
    """The rotate.py error boundary: from the --root default through the pending
    manifest write, a dry run and a refused --apply included. Returns an exit code, or
    the state the write phase needs (AFTER_KEYS). `left` records, before each write that
    creates one, every path a failure before the pending manifest may leave behind."""
    if not args.root:
        args.root = [os.path.expanduser("~/.claude")]

    # Empty waiver values first: an empty value matches everything.
    for flag, values in (("--accept", args.accept), ("--move-anyway", args.move_anyway),
                         ("--narrative", args.narrative)):
        for v in values:
            msg = splitlib.refuse_empty_waiver(flag, v)
            if msg:
                print(msg)
                return 2

    path = os.path.abspath(args.file)
    d = os.path.dirname(path)
    if not os.path.isfile(path):
        return cannot_tell("file missing: %s" % path)
    for t in args.todo:
        if not os.path.isfile(t):
            return cannot_tell("--todo file missing: %s" % t)
    for r in args.root:
        if not os.path.isdir(r):
            return cannot_tell("--root folder missing: %s" % r)
    # --hoisted: existence first, then splitlib's accept rule; exit 2 either way
    hoisted = []
    cache = {}      # one read per realpath per run (splitlib.read_once)
    for h in args.hoisted:
        if not os.path.isfile(h):
            return cannot_tell("--hoisted file missing: %s" % h)
    for h in args.hoisted:
        why = splitlib.hoisted_refusal(h, [path])
        if why:
            print("REFUSED --hoisted %s: %s" % (h, why))
            print("Exit 2: nothing was checked or written.")
            return 2
        try:
            hoisted.append((h, splitlib.read_once(cache, h)))
        except (OSError, UnicodeDecodeError) as e:
            return cannot_tell("--hoisted file unreadable: %s (%s); nothing was changed"
                               % (err_name(e, h), type(e).__name__))
    try:
        original = splitlib.read_once(cache, path)
    except (OSError, UnicodeDecodeError) as e:
        return cannot_tell("file unreadable: %s (%s); nothing was changed" % (err_name(e, path), type(e).__name__))
    lines = original.splitlines(keepends=True)
    # a fence still open at the end of CLAUDE.md is cannot tell
    try:
        fenced = splitlib.closed_fence_states(lines)
    except splitlib.UnclosedFence as e:
        return cannot_tell("fence opened at line %d never closes (%s)" % (e.line, path))

    # ---- step 1: a Last-run line inside a record span is removed from
    # `lines` itself and the records parsed again, before select, the archive
    # chunks and fragments_of; stripping only one output leaves fragments_of
    # pointing at the removed line. A fenced example moves with its record.
    stray = set(i for s, e, _, _ in parse_records(lines, args.convention) for i in range(s, e)
                if not fenced[i] and lines[i].startswith(splitlib.LAST_RUN_PREFIX))
    orig = [i for i in range(len(lines)) if i not in stray]    # index in the file as read
    if stray:
        lines = [ln for i, ln in enumerate(lines) if i not in stray]
        fenced = splitlib.fence_states(lines)[0]
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

    # ---- step 1: each --move-anyway / --narrative names one moving record
    anyway, narrative, ambiguous = [], [], []
    for flag, values, sink in (("--move-anyway", args.move_anyway, anyway),
                               ("--narrative", args.narrative, narrative)):
        for v in values:
            recs = resolve_waiver(v, to_move)
            if len(recs) > 1:
                ambiguous.append((flag, v, recs))
            sink.append((v, recs))

    chars = dict(((s, e), len("".join(lines[s:e]))) for s, e, _, _ in to_move)
    dens = [splitlib.density("".join(lines[s:e])) for s, e, _, _ in to_move]
    print(f"FILE        {path}")
    print(f"convention  {args.convention}   cut-date {args.cut_date}")
    print(f"records     {len(records)} dated  ->  {len(to_move)} move, {len(to_keep)} keep")
    moved_chars = sum(chars.values())
    print(f"would move  {moved_chars:,} chars of {len(original):,} "
          f"({moved_chars / len(original) * 100:.1f}%)")
    print()
    print("MOVE:")
    for (s, e, dt, title), dn in zip(to_move, dens):
        print(f"  {dt}  {chars[(s, e)]:>7,}ch  {title[:96]}"
              f"   [{dn[0]}, obligation {dn[1]:.2f}, reference {dn[2]:.2f}]")
    print("KEEP:")
    for s, e, dt, title, why in to_keep:
        print(f"  {dt}  {len(''.join(lines[s:e])):>7,}ch  {title[:78]}   [{why}]")

    if ambiguous:
        for flag, v, recs in ambiguous:
            print(f'\nREFUSED: {flag} "{v}" matches {len(recs)} moving records; give one whole title:')
            for r in recs:
                print(f"  {whole_title(r[3])}")
        print("Exit 3: nothing was written.")
        return 3

    if not to_move:
        if not args.apply:
            print("\nDRY RUN. Nothing would move, so no report is written.")
            return 0
        print("\nNothing to move. Not writing.")
        return 0

    # ---- step 2: every text this run would write, computed ONCE, in memory:
    # the run folder name, each archive, the index, and CLAUDE.md with its
    # Last-run line. Step 4 only hashes, backs up and writes these.
    run_name = pick_run_folder(d, args.today)
    run_dir = os.path.join(d, run_name)
    index_path = os.path.join(d, INDEX_NAME)
    try:
        fin = build_final(lines, d, to_move, args.convention, args.today, len(original), run_name)
    except (OSError, UnicodeDecodeError) as e:
        return cannot_tell("%s is unreadable (%s); nothing was changed"
                           % (err_name(e, "an archive or the index"), type(e).__name__))
    # the after text built in memory must close every fence it opens
    try:
        splitlib.closed_fence_states(fin.final_lines)
    except splitlib.UnclosedFence as e:
        k = fin.origin[e.line - 1] if fin.origin and fin.origin[e.line - 1] is not None else None
        return cannot_tell("fence opened at line %d never closes (%s after the move)"
                           % (orig[k] + 1 if k is not None else e.line, path))
    if not last_run_outside(fin, args.convention):
        print("INTERNAL: the Last-run line would sit inside a dated record. This is a bug in "
              "rotate.py. Exit 2: nothing was written.")
        return 2
    buckets, arch_final, arch_exists = fin.buckets, fin.arch_final, fin.arch_exists
    index_old, new_text, final_text = fin.index_old, fin.new_text, fin.final_text
    before_chars, after_chars, rows, idx_final = fin.before_chars, fin.after_chars, fin.rows, fin.idx_final

    # loss check and pointer report: the run's own outputs are present
    present = OrderedDict(arch_final)
    present[INDEX_NAME] = idx_final
    lazy = []
    for p in splitlib.notes_set(d):
        if os.path.basename(p) in present:
            continue
        try:
            lazy.append((p, splitlib.read_once(cache, p)))
        except (OSError, UnicodeDecodeError) as e:
            return cannot_tell("notes file unreadable: %s (%s); nothing was changed"
                               % (err_name(e, p), type(e).__name__))
    lazy += [(os.path.join(d, n), t) for n, t in present.items()]
    nar_map = {}
    for v, recs in narrative:
        if len(recs) == 1:
            s, e = recs[0][0], recs[0][1]
            for it in splitlib.atoms("".join(lines[s:e]),
                                     start_fenced=splitlib.fence_start(lines, fenced, s)):
                if it.kind == "rule":
                    nar_map.setdefault(it.text, '--narrative "%s"' % v)
    results = splitlib.classify(original, final_text, d, lazy=lazy, hoisted=hoisted,
                                narrative=nar_map, roots=(), present=present, cache=cache)
    accept_counts = splitlib.apply_waivers(results, [('--accept "%s"' % v, v) for v in args.accept])
    blocking = splitlib.unwaived_blocking(results)
    ptrs = splitlib.pointers(final_text, d, args.root, None, present, cache)
    unresolved = [p for p in ptrs if p.status == "UNRESOLVED"]

    # open work
    try:
        ow = open_work(d, args.todo, [(t, "".join(lines[s:e])) for s, e, _, t in to_move],
                       original, args.convention)
    except (OSError, UnicodeDecodeError) as e:
        return cannot_tell("%s is unreadable (%s); nothing was changed"
                           % (err_name(e, "an open-work file"), type(e).__name__))
    anyway_label = {}
    for v, recs in anyway:
        if len(recs) == 1:
            anyway_label.setdefault(recs[0][3], '--move-anyway "%s"' % v)
    refused = [(h, hits) for h, hits in ow if hits and h not in anyway_label]

    # rules draft and refusal: kept outside the moving spans, kept in an
    # accepted --hoisted file, or the record named by --narrative
    drafts = rules_draft([(t, dt, "".join(lines[s:e])) for s, e, dt, t in to_move], new_text,
                         start_fenced=[splitlib.fence_start(lines, fenced, s) for s, _, _, _ in to_move])
    nar_label = {}
    for v, recs in narrative:
        if len(recs) == 1:
            nar_label.setdefault(recs[0][3], '--narrative "%s"' % v)
    hoist_t = [splitlib.Text(t) for _, t in hoisted]
    missing_rules, nar_let, kept_of = [], {}, {}
    n_kept = n_hoisted = 0
    for dr in drafts:
        # the kept rule sentences AND the kept units
        kept_of[dr.heading] = [x.text for x in dr.sentences + dr.units if x.kept]
        for sent in dr.sentences:
            if sent.kept:
                n_kept += 1
            elif any(splitlib.window_kept(sent.text, t) for t in hoist_t):     # the window match
                n_hoisted += 1
            elif dr.heading in nar_label:
                nar_let.setdefault(dr.heading, []).append(sent.text)
            else:
                missing_rules.append((dr, sent))

    # ---- step 2: the fragment check predicted on the in-memory texts
    # (never an exit; quiet, so the VERIFY lines are not doubled)
    p_moved, p_kept, p_fails, _ = fragment_check(lines, to_move, to_keep, kept_of, fin.arch_final,
                                                 fin.arch_old, new_text, quiet=True)
    pred = (p_moved + p_kept, [f for f, _ in p_fails])

    print("\nOPEN WORK:")
    for heading, hits in ow:
        if not hits:
            continue
        state = ("waived by " + anyway_label[heading]) if heading in anyway_label else "refused on --apply"
        print(f"  {heading[:96]}  {len(hits)} open item(s), {state}")
        for h in hits:
            print(f"    {os.path.basename(h.source)} item {h.ordinal}  key `{h.key}`: {h.text[:100]}")
    if not any(hits for _, hits in ow):
        print("  none")
    n_sent = sum(len(dr.sentences) for dr in drafts)
    print("\nRULES DRAFT: %d rule sentence(s) in the moving records; %d already kept, "
          "%d kept in --hoisted, %d let through by --narrative, %d refused on --apply"
          % (n_sent, n_kept, n_hoisted, sum(len(v) for v in nar_let.values()), len(missing_rules)))
    for dr in drafts:
        for unit in dr.units:
            print(draft_line(dr, unit))
    counts = splitlib.class_counts(results)
    print("\nLOSS CHECK (in memory): items %d: " % len(results)
          + ", ".join("%s %d" % (k, n) for k, n in counts.items()))
    for ln in splitlib.listing_lines(results) + splitlib.waiver_lines(accept_counts):
        print(ln)
    for v, recs in anyway + narrative:
        if not recs:
            print(f'UNUSED WAIVER: "{v}" matched no moving record')
    print(f"\nPOINTERS: {len(ptrs)} checked, {len(unresolved)} unresolved (reported, never a refusal)")
    for p in unresolved:
        print(f"  UNRESOLVED: {p.token} in section {splitlib.section_name(p.section)}; {p.why}")

    verdict = ("%d blocking loss-check item(s), %d record(s) refused for open work, "
               "%d rule sentence(s) missing" % (len(blocking), len(refused), len(missing_rules)))
    ctx = {"path": path, "convention": args.convention, "cut": args.cut_date, "today": args.today,
           "before_chars": before_chars, "after_chars": after_chars, "n_records": len(records),
           "to_move": to_move, "to_keep": to_keep, "density": dens, "chars": chars,
           "run_name": run_name, "verdict": verdict, "open_work": ow, "anyway_label": anyway_label,
           "results": results, "accept_counts": accept_counts, "blocking": blocking,
           "unresolved": unresolved, "n_pointers": len(ptrs), "anyway": anyway,
           "narrative": narrative, "hits_of": dict(ow), "backups": None,
           "drafts": drafts, "missing_rules": missing_rules, "nar_let": nar_let,
           "nar_label": nar_label, "pred": pred}

    def write_dry(mode):
        """Step 3: REPORT.dry.md. A failure rises to the boundary, which names
        the run folder and the report if they exist: each name is
        recorded before the write that creates it."""
        left["paths"].append(run_dir)
        os.makedirs(run_dir, exist_ok=True)
        left["paths"].append(os.path.join(run_dir, "REPORT.dry.md"))
        write_report(run_dir, "REPORT.dry.md", report_text(mode, ctx))
        return None

    # ---- step 3: a dry run reports and stops; a refused apply reports and stops
    if not args.apply:
        print("\nFRAGMENT CHECK (predicted for --apply): %d fragment(s), %d failure(s)"
              % (pred[0], len(pred[1])))
        for f in pred[1]:
            print("  PREDICTED " + f)
        if write_dry("dry run"):
            return 2
        print(f"\nDRY RUN. Re-run with --apply to write. Report: {run_name}/REPORT.dry.md")
        return 0
    if blocking or refused or missing_rules:
        if write_dry("--apply refused (exit 3)"):
            return 2
        if missing_rules:
            print(f"\nREFUSED: {len(missing_rules)} rule sentence(s) would leave CLAUDE.md. "
                  "Paste the draft line that holds each one above the moving records (one draft "
                  "line can hold several), keep it in a --hoisted file, or name its record with "
                  "--narrative:")
            for dr, sent in missing_rules:
                print("MISSING RULE: " + sent.text)
                print(f'    from "{dr.title}"')
        if blocking:
            print(f"\nREFUSED: {len(blocking)} loss-check item(s) would leave CLAUDE.md with no "
                  "waiver (see the LAZY-ONLY and NOWHERE lines above).")
        for h, hits in refused:
            print(f'REFUSED: open work names "{whole_title(h)}"; --keep it, or '
                  f'--move-anyway "{whole_title(h)}".')
        print(f"Exit 3: wrote {run_name}/REPORT.dry.md and nothing else.")
        return 3

    # ---- step 4: folder, backups, pending manifest, then the writes
    targets = [(path, final_text)] + [(os.path.join(d, n), t) for n, t in arch_final.items()] \
        + [(index_path, idx_final)]
    pre = dict((p, splitlib.sha256(p) if splitlib.exists(p) else None) for p, _ in targets)
    backups, backup_of = [], {}
    # a failure from here to the pending manifest rises to the boundary,
    # which names the run folder and every backup made (each recorded before it is made)
    left["paths"].append(run_dir)
    os.makedirs(run_dir, exist_ok=True)
    print("\nBACKUPS")
    for f, _ in targets:
        b = backup(f, args.today, left)
        backup_of[f] = b
        backups.append(("created " + os.path.basename(b)) if b else ("absent  " + os.path.basename(f)))
        print(f"  {'created ' if b else 'absent  '}{os.path.basename(b) if b else os.path.basename(f)}")
    manifest = {"version": 1, "status": "pending", "date": args.today, "folder": os.path.realpath(d),
                "files": [{"path": os.path.relpath(p, d), "pre_sha256": pre[p],
                           "post_sha256": hashlib.sha256(t.encode("utf-8")).hexdigest(),
                           "backup": os.path.relpath(backup_of[p], d) if backup_of[p] else None}
                          for p, t in targets]}
    left["paths"].append(os.path.join(run_dir, "manifest.json.tmp"))
    left["paths"].append(os.path.join(run_dir, "manifest.json"))
    write_manifest(run_dir, manifest)
    here = locals()
    return dict((k, here[k]) for k in AFTER_KEYS)


def after_manifest(st):
    """Steps 4 to 7 after the pending manifest exists: the writes, the fragment
    check, the CLAUDE.md re-read, REPORT.md and the manifest marked complete. Any failure
    prints the --undo command."""
    (path, d, run_name, run_dir, arch_final, arch_exists, index_path, idx_final, index_old, rows, lines, to_move, to_keep, kept_of, fin, original, new_text, manifest, ctx, backups, final_text) = (st[k] for k in AFTER_KEYS)
    undo_cmd = f"rotate.py {path} --undo {run_name}"

    def failed(why):
        """Any failure after the pending manifest exists."""
        print(f"\n*** {why} Restore from the .backup-before-split-* files, or undo this run "
              "(a dry run; add --apply to restore): ***")
        print(f"  {undo_cmd}")
        return 2

    try:
        for name, text in arch_final.items():
            with open(os.path.join(d, name), "w", encoding="utf-8") as fh:
                fh.write(text)
            print(f"  archive {'appended' if arch_exists[name] else 'created '} {name}")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(final_text)
        with open(index_path, "w", encoding="utf-8") as fh:
            fh.write(idx_final)
        print(f"  index   {'appended' if index_old is not None else 'created '} {len(rows)} rows "
              f"and a Runs row in {INDEX_NAME}")

        # ---- A9 both-directions presence check, counting OCCURRENCES
        print("\nVERIFY (both directions, occurrence counts)")
        archives = OrderedDict((n, read_text(os.path.join(d, n))) for n in arch_final)
        nfrag_moved, nfrag_kept, vfails, already = fragment_check(
            lines, to_move, to_keep, kept_of, archives, fin.arch_old, new_text, quiet=False)
        for line, frag in vfails:
            print("  " + line)
            print(f"              fragment: {frag[:80]!r}")
        fails = len(vfails)
        print(f"  moved records: {len(to_move)} records / {nfrag_moved} fragments "
              f"(each must be exactly one more copy in its archive, 0 in CLAUDE.md)")
        print(f"  kept  records: {len(to_keep)} records / {nfrag_kept} fragments "
              f"(each must be 1 in CLAUDE.md)")
        if nfrag_moved < len(to_move) * 2:
            print(f"  NOTE: {len(to_move) * 2 - nfrag_moved} record(s) had no usable body fragment "
                  f"(short records); those were checked on their title only.")
        if already:
            print(f"  NOTE: {already} moved fragment(s) were already in their archive before this "
                  f"run; each was checked as exactly one more copy.")

        arch_lines = sum(a.count("\n") for a in archives.values())
        print(f"\nACCOUNTING")
        print(f"  original CLAUDE.md : {len(original):>9,} ch  {original.count(chr(10)):>6,} lines")
        print(f"  new      CLAUDE.md : {len(new_text):>9,} ch  {new_text.count(chr(10)):>6,} lines"
              f"   ({(1 - len(new_text)/len(original))*100:.1f}% smaller)")
        print(f"  archives (this run): {sum(len(a) for a in archives.values()):>9,} ch  {arch_lines:>6,} lines")

        if fails:
            return failed(f"{fails} VERIFICATION FAILURE(S).")
        # ---- step 5: CLAUDE.md re-read at its final hash
        if splitlib.sha256(path) != manifest["files"][0]["post_sha256"]:
            return failed("CLAUDE.md is not at the hash this run wrote.")
        # ---- steps 6 and 7: REPORT.md, then the manifest marked complete
        ctx["backups"] = backups
        ctx["verdict"] = "applied; every check and the fragment check passed"
        write_report(run_dir, "REPORT.md", report_text("--apply (exit 0)", ctx))
        manifest["status"] = "complete"
        write_manifest(run_dir, manifest)
        print(f"\nAll presence checks passed. Report: {run_name}/REPORT.md")
        return 0
    except Exception as e:                                      # noqa: BLE001
        return failed(f"The run stopped after the pending manifest ({type(e).__name__}).")


if __name__ == "__main__":
    sys.exit(main())
