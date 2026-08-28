## Phase A — Archive old decisions

Skip this phase if `--patterns-only` was passed.

### A0. Survey the file first (one command, replaces the greps below)

Run the bundled surveyor before anything else. It answers A1, A2 and C1 in one pass and prints its evidence, so the heading convention is measured rather than assumed:

```bash
python3 <skill-dir>/survey.py <path-to-CLAUDE.md> --cut-date YYYY-MM-DD
# or preview a window instead of a fixed date:
python3 <skill-dir>/survey.py <path-to-CLAUDE.md> --keep-days 30
```

It prints the file size against the warning threshold (in python chars, not bytes; the two differ on any file with Hebrew or other multibyte text), the counts of dated `###` entries, dated `##` sections, and dated record BULLETS with its verdict on which shape the records live in, every dated record with size and start line, what the proposed cut would archive versus keep bucketed by month, and the Phase C candidates with deny-list sections named separately, including the section that HOLDS the dated records, which is denied by evidence whatever it is named. It ends with one `SUMMARY convention=... dated=... archive=... keep=...` line. Read-only; it never writes to the surveyed file. The target path is a required argument and is echoed in the header, so a run cannot certify a file other than the one you meant.

Four outputs are decision points rather than formalities:
- `convention=none` means Phase A cannot run on this file at all. Phases B and C still can.
- `archive=0` means the cut moves nothing. Widen the window or skip Phase A; do not report a split that moved no content.
- A `VARIANT` verdict means this project keeps whole dated `## ` sections rather than `### YYYY-MM-DD:` entries, so Phase A archives whole sections and the index must record the convention.
- `convention=bullet` means the records are dated TOP-LEVEL BULLETS (`- Shipped (YYYY-MM-DD): ...`) inside ONE named section; the survey names that section and prints any runner-up. Phase A archives whole bullets (A4 bullet mode), the records' section is auto-denied for Phase C, and the index must record the convention. Precedence when shapes coexist is entry, then section, then bullet, and the survey prints all three counts so you can overrule it.

**The survey proposes, you still judge.** It keys purely on dates, so it will list a dated section you mean to consolidate under Phase B instead of archiving, and it will miss an undated section that belongs in the archive anyway. Both happened on the 2026-08-09 run: it offered `Gotchas / hard-won (2026-07-01)`, which became a Known Patterns entry rather than an archived record, and it did not offer the undated `Open follow-ups`, which was 20K of finished July bullets and was archived. Treat the record list as candidates, not as the plan.

Tests: `python3 <skill-dir>/run_tests.py`, which runs EVERY test file in the skill and prints one total (mutation-verified; read the count from the run rather than from this sentence, which went stale the first time it carried a number). Do not run `test_survey.py` alone and treat its tally as the suite: it covers one file of three. A runner that only counts its own file is the shape of a check that cannot fail.

### A1. Discover the target file and confirm it qualifies

Only needed when the survey above could not run, or to double-check its verdict by hand.

- Default: `<cwd>/CLAUDE.md`. Otherwise use the `--target-file` argument.
- `wc -c` the file. If under 30K chars, STOP and tell the user the split would be premature.
- Count date-keyed entries. Try the standard pattern first, then fall back to project-specific variants:
  ```bash
  # Standard "### YYYY-MM-DD: title" pattern
  grep -c '^### [0-9]\{4\}-[0-9]\{2\}-[0-9]\{2\}' CLAUDE.md

  # Version-keyed with parens, e.g. "### v4.10.5 (2026-05-03) — title"
  grep -c '^### v[0-9]\+\(\.[0-9]\+\)* *(.*[0-9]\{4\}-[0-9]\{2\}-[0-9]\{2\}' CLAUDE.md

  # All level-3 headings (sanity floor — if the count is non-zero here but the
  # specific patterns are zero, the project uses a different convention)
  grep -c '^### ' CLAUDE.md
  ```
  If ALL of these are zero, STOP — the file truly has no dated entries section.
  If the standard pattern returns zero but a variant returns N>0, you have a non-standard project heading convention. **Do not STOP — adapt.** Confirm with the user that the variant is the project's decision-log style, then use that regex throughout Phase A. Record the convention in the INDEX file (A5) so future runs pick it up.
- Find the boundary of the section that contains the dated entries. Look for `^## Decisions Log` first, then `^## Recalibration History`, `^## Release History`, `^## Changelog`, or similar; if absent, fall back to the nearest `^## ` heading above the first dated entry. Capture the line range and report it to the user before proceeding (the section name may itself be a project-specific convention worth noting in the INDEX).

### A2. Determine the cut date

Resolve in this priority:
1. `--cut-date YYYY-MM-DD` argument → use as-is.
2. `--keep-days N` argument → today - N days, ISO 8601.
3. Default → today - 30 days.

State the chosen cut date and the count of entries before/after.

**Alternative: the STATE-BASED cut, first-class and preferred when the project's index documents a size or judgment cadence.** Archive entries that are CLOSED with nothing open reading from them; keep load-bearing entries regardless of age. "Closed" is checkable, not a feeling: grep the project TODO.md and any live plan files for references to the entry's subject before archiving it. The last two real runs on one project both needed this mode; a pure date cut would have archived the facts the next build slice grounds on while leaving closed newer material in place. Two obligations when cutting by state: the A8 report names every kept-despite-age entry with its reason, and the archive-pointer line in CLAUDE.md says the cut is by judgment, so no future session infers "everything before date X is archived". Note `survey.py`'s CUT ANALYSIS is date-only BY DESIGN: it informs a judgment cut but cannot express one, so never cite its `archive=N` as the plan when cutting by state. The date cut stays the default when no curation signal exists.

### A3. Back up EVERY file the run will mutate

```bash
for f in CLAUDE.md CLAUDE_DECISIONS_INDEX.md CLAUDE_DECISIONS_<target-month>.md; do
  [ -f "$f" ] || continue                       # first run: no index/archive yet
  b="$f.backup-before-split-$(date +%Y%m%d)"
  [ -e "$b" ] && b="$b-2"                       # NEVER overwrite a same-day backup
  cp "$f" "$b"
done
```

Do NOT skip this. The user must be able to revert if anything looks off. The run mutates THREE files, not one: CLAUDE.md is rewritten, the target archive is appended to, and the index is edited in place, so all three get siblings with the same suffix. Skip absent files without erroring (a first run has no index and no archive). And never overwrite an existing same-day backup: it is the only true pre-run state, and at the current 2-3-day rotation cadence two same-day runs have already happened; append a counter instead.

### A4. Group entries to archive by month

For every dated heading whose date is < cut date (or, on a state-based cut, every entry judged closed):
- Extract the entry: from the `### YYYY-MM-DD: ...` line to the line before the next `### YYYY-MM-DD:` (or before the next `## ` heading, whichever comes first).
- Bucket by `YYYY-MM` (year + month).

**Bullet mode** (`convention=bullet`): a record's extent runs from its column-0 `- ` line to the next column-0 `- ` line or heading, whichever comes first, so indented continuation lines ride along. Records in these projects interleave with undated config-reference bullets inside ONE section; extract only the record bullets and leave every undated bullet exactly where it is.

For each bucket, write `CLAUDE_DECISIONS_YYYY-MM.md` in the same directory as CLAUDE.md. If the archive file already exists from a previous run, append the new entries to it (don't overwrite — entries already there are the load-bearing historical record), and precede the appended batch with a provenance marker so multi-rotation months stay navigable:

```markdown
<!-- Archived from CLAUDE.md on YYYY-MM-DD (second rotation this month). -->
```

Each archive file gets a 7-line header at the top (only when creating, not when appending):

```markdown
# Decisions Log Archive — Month Year

Decisions log entries archived from `CLAUDE.md` on YYYY-MM-DD to keep active context lean.

- Active CLAUDE.md is at `CLAUDE.md` (same directory).
- Index of all archived entries: `CLAUDE_DECISIONS_INDEX.md`.
- For full context on any entry, look for the commit hash in the entry body and run `git show <hash>` in the relevant repo.

---
```

### A5. Build or update `CLAUDE_DECISIONS_INDEX.md`

The index is a one-line-per-entry chronological listing that stays in active context. Format:

```markdown
- YYYY-MM-DD: Entry title — `CLAUDE_DECISIONS_YYYY-MM.md`
```

If the index already exists, APPEND the new rows in chronological position and update the Archives table, preserving every prose section verbatim. Do NOT regenerate it from the archive files: a curated index carries hand-written material that regeneration wipes (one real project's holds a How-to-use section, the Project heading convention that lets runs adapt at all, and the rotation-cadence history). An earlier version of this step said the opposite, with the rationale "the user may have manually corrected entries"; that rationale is inverted, because corrections that live IN THE INDEX are exactly what regeneration destroys. Regenerate only when the index is purely mechanical (no prose beyond this template), and say in the A8 report which case applied.

Index file structure:

```markdown
# Decisions Log Index

One-line summary of every archived decision-log entry from CLAUDE.md. This index stays in active context; the full entries live in the dated archive files referenced in each row.

## How to use

- **Looking for "why did we do X?"** — scan for keywords, then read the matching archive entry with `grep -B2 -A60 "<entry-title>" CLAUDE_DECISIONS_YYYY-MM.md`.
- **Looking for a specific commit** — most entries cite their commit hash in the body. Run `git show <hash>` inside the project repo for the full diff + commit message.
- **Looking by date** — entries are listed in chronological order below.

## Project heading convention

This project's decision-log entries use `<exact heading pattern, e.g. ### vN.M.K (YYYY-MM-DD) — title>` inside `## <section name, e.g. Recalibration History>`. Future `/split-claude-md` runs adapt their date regex to this pattern. Undated old entries bucket into a single `pre-YYYY-MM` archive (rather than per-month) so the "earliest dated entry" anchor is preserved.

(Omit this subsection if the project uses the standard `### YYYY-MM-DD: title` pattern inside `## Decisions Log` — that's the assumed default and doesn't need documenting.)

## Archives
- `CLAUDE_DECISIONS_YYYY-MM.md` — N entries, K KB
- ... (one row per archive file)

## Entries (chronological)

- YYYY-MM-DD: Entry title — `CLAUDE_DECISIONS_YYYY-MM.md`
- ... (sorted by date)
```

### A6. Rewrite the active CLAUDE.md

The new CLAUDE.md keeps:
- Everything BEFORE the Decisions Log section (preamble).
- The "Finding Historical Context" section (insert if absent — see A7).
- The "## Decisions Log" header, slightly rewritten to point at the archives.
- Every dated entry whose date is ≥ cut date (state-based cut: every entry not judged closed). In bullet mode the records' section survives with its undated config-reference bullets exactly in place and only the archived record bullets removed.
- Everything AFTER the Decisions Log section (e.g., Custom Skills tables, postamble).

The replacement Decisions Log header is:

```markdown
## Decisions Log

Last ~30 days only (or whatever the keep window was; on a state-based cut, say instead: recent and still-load-bearing entries only, cut by judgment, so do not infer that everything before a date is archived). Older entries archived by month — see "Finding Historical Context" above, `CLAUDE_DECISIONS_INDEX.md` for the one-line index, and `CLAUDE_DECISIONS_YYYY-MM.md` archives for full entries.
```

### A7. Insert "Finding Historical Context" section if absent

`grep -q '^## Finding Historical Context' CLAUDE.md`. If absent, insert this block right before the Decisions Log section (or right after Directory Conventions / Project Overview, whichever is later in the file):

```markdown
## Finding Historical Context

This CLAUDE.md keeps roughly the last ~30 days of decision-log entries (a project that cuts by state keeps the still-load-bearing ones instead; adapt this sentence). Older decisions live in separate archive files in this same directory:
- `CLAUDE_DECISIONS_INDEX.md` — one-line index of every archived entry. Stays in active context; scan this first.
- `CLAUDE_DECISIONS_YYYY-MM.md` — full archived entries by month.

### When to grep the archives
- User asks "why did we do X?" or "when did we change Y?"
- You see a symbol, file, pattern, or function you don't recognize — search the archive for prior context before assuming it's new.
- A bug looks like a regression of something previously fixed — grep for the pattern keywords.
- Before proposing a "new" approach — check whether it was tried and reverted.

### How to grep
```bash
# Scan the index first (cheap, no archive load)
grep -i "<keyword>" CLAUDE_DECISIONS_INDEX.md

# Then open the matching archive month
grep -B2 -A60 "<entry-title>" CLAUDE_DECISIONS_YYYY-MM.md

# Most entries cite a commit hash — get the full diff + commit message
git show <hash>   # run inside the relevant project repo, not this directory
```

### When NOT to load archives
- Routine code-change tasks where current state is the only relevant context.
- Bug fixes where the failure mode is self-explanatory from the current code.
- Anything where reading the current code answers the question faster than reading history.

### Maintenance rule
When CLAUDE.md grows past ~50K chars, run `/split-claude-md` to rotate the oldest month of decisions into a new archive file and update the index. Don't manually edit CLAUDE.md to inline old decisions back in.
```

If the section IS already present, leave it alone (the user may have customized the wording).

### A8. Verify Phase A

Report:
- Original CLAUDE.md size (chars / lines).
- New CLAUDE.md size (chars / lines).
- Percentage reduction (or growth — see below).
- Archive files created or appended to, with their sizes.
- Index file size.
- The cut RULE used and the count of entries archived vs kept. For a date cut, the date. For a state-based cut, name every kept-despite-age entry with its one-line reason; that list is what stops a future session inferring date-completeness.
- Backup file locations (all three: CLAUDE.md, the index, the appended archive).

**If you write the run's result size into a persistent file (a "Runs so far" log in the Maintenance rule, an index note), write it AFTER Phase C, not here.** The Phase A number is not the run's result: Phase B normally GROWS the file (pattern entries are heavier than the prose they consolidate) and Phase C shrinks it, so a size recorded at A8 is stale the moment B runs. Hit 2026-07-29 on a real project, where the maintenance rule logged "236K -> 105K" while the finished run landed at 118K, and the false figure went into the same file whose own "a doc claims more than the code delivers" pattern the run had just written. Report the Phase A delta to the user here by all means; just do not persist it as the run's outcome until every phase has finished. **And when you do persist it, record it to the nearest K, as the LAST edit of the run.** An exact figure written into the file it measures invalidates itself by its own length: on the 2026-08-10 run two drafts of the "Runs so far" figure were each wrong the moment they were written, and the nearest-K form is the only one that stays true.

**Net growth is acceptable on first-run with a small archive.** The "Finding Historical Context" navigation section is a one-time ~35-line / ~1.5 KB overhead. If only a handful of old entries qualify for the archive (e.g., 2 undated entries totaling 15 lines), the navigation overhead exceeds the archive size and CLAUDE.md grows by a few hundred bytes net. **This is structural, not a bug.** Future Phase A runs amortize the navigation cost — the overhead is paid once, and every subsequent run compounds savings as more months age out.

If CLAUDE.md grew, report honestly:
- Net growth in lines/chars.
- The structural reason (navigation overhead vs. archive size).
- That the framework now exists so future runs deliver compounding savings.

STOP only if CLAUDE.md grew AND the growth cannot be explained by the navigation section + the archive being small. That signals real bugs: content duplicated, sections lost their boundaries, or the rewrite went wrong. Diff against the backup to find the issue.

### A9. Sanity-check the splits

- `head -20 CLAUDE.md` — first lines should be the same as the backup's first lines.
- `tail -20 CLAUDE.md` — last lines should be the same (postamble preserved).
- `wc -l` on every archive file — none should be < 5 lines.
- Sum of archive lines + new CLAUDE.md lines ≈ original CLAUDE.md lines + headers. Anything wildly off means content was lost.
- **The per-entry both-directions presence check, which is the one that catches duplication and partial moves (the line-sum above only catches gross loss).** Take a distinctive fragment of each MOVED entry: it must appear exactly once in the archive and zero times in CLAUDE.md. Take one of each deliberately KEPT entry: the inverse. Count OCCURRENCES, not lines: these entries are single multi-K-char lines, so `grep -cF` cannot tell one occurrence from two on the same line; use `grep -oF "<fragment>" <file> | wc -l`.

---

