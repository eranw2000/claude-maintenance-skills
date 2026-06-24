---
name: split-claude-md
description: Three-phase CLAUDE.md cleanup. Phase A rotates old Decisions Log entries into monthly archive files, builds/updates an index, and adds a grep-pattern navigation header. Phase B consolidates recurring failure patterns (2+ instances) into a canonical "Known Patterns & Gotchas" section with current instance counts. Phase C extracts stable reference sections (architecture, file maps, data layouts) into standalone files (ARCHITECTURE.md, DEVELOPMENT.md, etc.) with one-line pointer stubs in CLAUDE.md. Use when CLAUDE.md exceeds ~50K chars, when the user asks to "split" / "archive" / "shrink" / "consolidate" / "extract" CLAUDE.md, when several decision entries have accumulated that share root causes, or when CLAUDE.md has accumulated reference docs that rarely change.
disable-model-invocation: false
argument-hint: "[--cut-date YYYY-MM-DD | --keep-days N | --target-file <path> | --patterns-only | --no-patterns | --extract-only | --no-extract]"
---

# Split CLAUDE.md — archive + consolidate + extract

Active context is finite. Every conversation pays prompt-token cost for the full CLAUDE.md. Three problems grow over time:
1. Old decision-log entries get loaded every turn even when no future session needs them.
2. Recurring bugs accumulate as scattered prose with stale instance counts — future sessions can't tell that a "new" bug is the Nth instance of a known pattern, so the same fix gets rediscovered.
3. Stable reference docs (architecture diagrams, file maps, directory layouts, advisor lists) live inline even though they're consulted maybe once per ten conversations. Every conversation that DOESN'T need them still pays their context cost.

This skill runs in three phases:
- **Phase A — Archive old decisions.** Rotates older entries into dated archive files, builds an index of one-line summaries that stays in active context, adds a "Finding Historical Context" navigation section so future sessions know when and how to grep the archives.
- **Phase B — Consolidate recurring patterns.** Identifies failure modes that have hit 2+ times across the decisions log + archives, writes canonical entries (signal / fix shape / project hooks / instance list / global-memory pointer) into a "Known Patterns & Gotchas" section. Replaces stale "Known Issues" content with current instance counts.
- **Phase C — Extract stable reference sections.** Identifies sections that are large + reference-shaped + rarely changed, moves them to standalone sibling files (`ARCHITECTURE.md`, `DEVELOPMENT.md`, `OPERATIONS.md`, etc.), and replaces each with a one-line pointer stub in CLAUDE.md so future sessions can find them by section heading and load on demand.

Default behavior runs all three phases in order (A → B → C). Skip with `--no-patterns` / `--no-extract`, or run a single phase with `--patterns-only` / `--extract-only`.

## When to run

- The user asks to "split" / "shrink" / "archive" / "rotate" / "consolidate" / "extract" CLAUDE.md.
- `wc -c CLAUDE.md` reports > 50,000 chars and the bulk is decision-log entries.
- After a long session that added many decision entries.
- Decision-log entries explicitly cite "Nth instance", "Updated count", or "recurring pattern" — a sign Phase B consolidation is overdue.
- CLAUDE.md contains large stable reference sections (architecture pipelines, file maps, directory layouts, advisor / endpoint tables) that haven't been edited in many sessions — a sign Phase C extraction is overdue.

## When NOT to run

- CLAUDE.md is under 50K chars AND no recurring patterns are obvious AND no large reference sections — the cleanup adds maintenance burden without saving meaningful context.
- The file has no clear date-keyed section (Phase A needs `### YYYY-MM-DD: title` style headings; Phases B and C can still run independently).
- All entries are from the last 30 days AND no recurring patterns exist AND all sections are small/active — nothing to do at any phase.

## Inputs

Default behavior:
- Target file: `CLAUDE.md` in the current working directory.
- Cut date (Phase A): 30 days before today (entries dated before this go to archive).
- Archive granularity: by month, files named `CLAUDE_DECISIONS_YYYY-MM.md` next to CLAUDE.md.
- All three phases run; order is A → B → C.

Optional arguments (passed as `$ARGUMENTS`):
- `--cut-date YYYY-MM-DD` — Phase A: entries strictly before this date go to archive. Overrides --keep-days.
- `--keep-days N` — Phase A: keep entries from last N days in active CLAUDE.md.
- `--target-file <path>` — operate on a CLAUDE.md outside the current directory.
- `--patterns-only` — run only Phase B (skip A and C).
- `--no-patterns` — skip Phase B.
- `--extract-only` — run only Phase C (skip A and B).
- `--no-extract` — skip Phase C.

Conflict resolution: `--patterns-only` and `--extract-only` cannot be combined — if both passed, stop and ask the user which they meant. `--no-patterns --no-extract` together is fine (= Phase A only).

If $ARGUMENTS is empty, use defaults and report what you're about to do before doing it.

---

## Phase A — Archive old decisions

Skip this phase if `--patterns-only` was passed.

### A1. Discover the target file and confirm it qualifies

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

### A3. Back up CLAUDE.md

```bash
cp CLAUDE.md "CLAUDE.md.backup-before-split-$(date +%Y%m%d)"
```

Do NOT skip this. The user must be able to revert if anything looks off.

### A4. Group entries to archive by month

For every dated heading whose date is < cut date:
- Extract the entry: from the `### YYYY-MM-DD: ...` line to the line before the next `### YYYY-MM-DD:` (or before the next `## ` heading, whichever comes first).
- Bucket by `YYYY-MM` (year + month).

For each bucket, write `CLAUDE_DECISIONS_YYYY-MM.md` in the same directory as CLAUDE.md. If the archive file already exists from a previous run, append the new entries to it (don't overwrite — entries already there are the load-bearing historical record).

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

If the index already exists, regenerate it from all `CLAUDE_DECISIONS_YYYY-MM.md` files in the directory (don't just append — the user may have manually corrected entries).

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
- Every dated entry whose date is ≥ cut date.
- Everything AFTER the Decisions Log section (e.g., Custom Skills tables, postamble).

The replacement Decisions Log header is:

```markdown
## Decisions Log

Last ~30 days only (or whatever the keep window was). Older entries archived by month — see "Finding Historical Context" above, `CLAUDE_DECISIONS_INDEX.md` for the one-line index, and `CLAUDE_DECISIONS_YYYY-MM.md` archives for full entries.
```

### A7. Insert "Finding Historical Context" section if absent

`grep -q '^## Finding Historical Context' CLAUDE.md`. If absent, insert this block right before the Decisions Log section (or right after Directory Conventions / Project Overview, whichever is later in the file):

```markdown
## Finding Historical Context

This CLAUDE.md keeps roughly the last ~30 days of decision-log entries. Older decisions live in separate archive files in this same directory:
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
- The cut date used and the count of entries archived vs kept.
- Backup file location.

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

---

## Phase B — Consolidate recurring patterns

Skip this phase if `--no-patterns` was passed.

Recurring failure modes deserve a canonical entry that future sessions can find FIRST, before grepping the decision log. Phase B identifies patterns (≥ 2 instances), writes structured entries, and replaces any stale "Known Issues" content. **Unlike Phase A, this phase is judgment-heavy — the skill scaffolds and structures, but the AI invoking it must read carefully and decide what's actually a pattern.**

### B1. Survey for candidate patterns

Read the active CLAUDE.md decision-log entries AND the archive files (whether they exist from a prior run or were just created in Phase A). Build a candidate-pattern list by looking for:

- **Explicit instance markers** — phrases like "Nth instance", "Nth time", "Updated count", "X prior instances", "recurring pattern", "Nth occurrence".
- **Repeated production symptoms** — distinct entries describing the same observable failure (e.g., "empty body", "broken output", "silent failure", "no rows returned", "wrong instrument shown").
- **Repeated fix shapes** — distinct entries that describe the same recipe (e.g., "switch to prose-mode LLM", "add hedging-intent signal", "centralise normalisation at the reader").
- **Repeated symbol references** — function names, file paths, or commit-sequence markers that appear in 2+ entries.
- **Pre-written lesson sections** — many entries end with a "Lesson" / "Pattern" / "Takeaway" paragraph. These are pre-articulated candidate patterns.

Useful grep starting points:
```bash
# Explicit instance markers
grep -nE "instance|recurring pattern|Updated count|Nth time" CLAUDE.md CLAUDE_DECISIONS_*.md

# Pre-articulated lessons
grep -B1 -A3 "^\*\*Lesson" CLAUDE.md CLAUDE_DECISIONS_*.md
```

Report candidates to the user with rough instance count, the symptom signature, and one sample entry per pattern. **DO NOT proceed to writing entries until the user has confirmed which candidates to consolidate.**

**Judgment, not mechanics.** Keyword-frequency alone doesn't make a pattern. Two entries that share the word "error" aren't a pattern. Two entries that share root cause AND fix shape are. When in doubt, ask the user.

### B2. Map candidates to global memory

Some patterns may already be documented as cross-project lessons in global memory (`~/.claude/projects/<USER>/memory/feedback_*.md`, or wherever the user's MEMORY.md lives). The aim is to avoid duplication: project pattern entries should POINT at global memory rather than restate the cross-project lesson.

For each candidate:
- **Global memory entry exists** that captures the cross-project lesson → project pattern entry should be SHORTER and end with `**See also (global memory):** \`feedback_<name>.md\``.
- **No global memory entry yet** AND the pattern crosses project boundaries (e.g., "always re-check token caps when adding fields to a schema") → flag it. Ask the user whether to promote a new global memory entry as part of this consolidation.
- **Pattern is genuinely project-specific** (named functions, project-specific data flows) → keep the full entry inline; no global memory pointer needed.

Useful grep on global memory:
```bash
ls ~/.claude/projects/*/memory/feedback_*.md 2>/dev/null
grep -li "<keyword>" ~/.claude/projects/*/memory/feedback_*.md
```

### B3. Write canonical pattern entries

Each pattern entry uses this template:

```markdown
### Pattern: <Short Pattern Name> (<N> instances)

**Signal.** <One sentence describing what this looks like in production — error message, missing data, wrong output, etc.>

**Fix shape.** <One sentence describing the recipe. Reference a project helper or function if one exists.>

**Detection rule.** <Optional. When to check for this pattern proactively — e.g., "Before bumping the LLM model" or "When adding fields to a JSON schema".>

**Project hooks.** <Files / symbols / helpers in this codebase where the fix is implemented or where the bug recurs.>

**Instances:**
- YYYY-MM-DD (`<commit>`) — <one-line description, naming the location affected>
- YYYY-MM-DD (`<commit>`) — <one-line description>
...

**See also (global memory):** `feedback_<name>.md` (only if a relevant entry exists; omit the line otherwise).
```

Notes on filling the template:
- **Pattern Name** comes from the user's existing terminology in the decision entries (e.g., "JSON-mode/markdown trap", "family-bug classifier extensions"). Don't invent new names; mine the existing prose.
- **Instance rows** should distinguish each occurrence — same pattern, different location. "JSON-mode trap in Phase 4" vs "JSON-mode trap in macro fast path" — both instances, different locations.
- **Commit hashes** come from the decision entries themselves. If an entry doesn't cite a commit, omit it from the row.
- **Project hooks** name the canonical place the fix lives. If a project helper was introduced specifically to defend against this pattern (e.g., `_call_moa_markdown_body`), that's the hook to name.

### B4. Locate or create the "Known Patterns & Gotchas" section

Search for an existing section that consolidates project gotchas:
- `## Known Patterns & Gotchas` — already in the canonical form, update in place.
- `## Known Issues & Gotchas` / `## Gotchas` / `## Known Issues` — rename to `## Known Patterns & Gotchas`, replace content.
- None exists — create `## Known Patterns & Gotchas` immediately before `## Decisions Log`.

The section structure:

```markdown
## Known Patterns & Gotchas

<One-paragraph intro: what this section is, when to scan it, pointer to global memory for cross-project lessons.>

### Pattern: <Name 1> (<N> instances)
...

### Pattern: <Name 2> (<N> instances)
...

---

### Other project gotchas (non-pattern, kept for reference)

<Single-instance facts that don't qualify as patterns but are still useful project knowledge.>
```

### B5. Preserve non-pattern facts

When replacing an existing "Known Issues" section, NOT every entry becomes a Pattern. Single-instance facts (specific API quirks, CLI commands, model-specific gotchas, rendering pipeline reference notes) aren't patterns — they're project knowledge.

Move these to the "Other project gotchas (non-pattern, kept for reference)" subsection at the bottom. Reformat as `**Topic:** prose blurb` rather than the bullet-list form of the original Known Issues section. This keeps them findable without elevating them to pattern status.

### B6. Verify Phase B

Report:
- Number of patterns consolidated, and the name of each.
- Each pattern's instance count + how it compares to any prior count (e.g., "JSON-mode trap: was 'THIRD instance' in old Known Issues, now '6 instances' after scanning archives").
- Whether the "Known Patterns & Gotchas" section grew or shrank vs the prior "Known Issues" section. If it GREW, that's normal — patterns previously buried in decision-log prose are now visible. Be HONEST about the size delta. Don't claim "saved bytes" if you added them; the win was findability and currency, not compression.
- Any non-pattern facts preserved in the "Other" subsection.
- Any candidate patterns the user declined to consolidate.
- Any global memory entries promoted (with user approval) as part of the consolidation.

### What Phase B does NOT do

- It does NOT rewrite the original decision-log entries. Those stay verbatim in the archive. The Known Patterns section is an ADDITIONAL layer of organisation, not a replacement for history.
- It does NOT invent pattern names. Names come from the user's existing terminology in the entries themselves.
- It does NOT mechanically count keywords and declare patterns. Pattern identification is a JUDGMENT CALL — the skill assists with structure but the AI invoking it must read carefully and decide.
- It does NOT touch global memory without explicit user approval. If a candidate looks like a cross-project lesson worth promoting, ASK before writing.

---

## Phase C — Extract stable reference sections

Skip this phase if `--no-patterns --no-extract` was passed jointly. Run only this phase if `--extract-only` was passed.

Some `## ` sections in CLAUDE.md are stable reference docs (architecture pipelines, file maps, directory layouts, advisor / endpoint tables, environment variable lists). They're consulted maybe once per ten conversations — but every conversation that doesn't need them still pays their context cost. Phase C moves them to standalone sibling files and leaves one-line pointer stubs in CLAUDE.md so future sessions find them by section heading and load on demand. **Like Phase B, this is judgment-heavy — the skill identifies candidates but the user/AI decides which to extract.**

### C1. Survey for candidate sections

List every `## ` heading in CLAUDE.md. For each, compute:
- **Size**: lines + chars (`sed -n '<start>,<end>p' CLAUDE.md | wc -lc`).
- **Stability signal**: how often the section's symbols/topic appear in the decisions log + archives. Few mentions = stable.
- **Shape**: mostly tables / lists / file maps (reference) or prose / narrative (active context)?

Candidates qualify when ALL of:
- Size ≥ ~30 lines OR ~3K chars (smaller sections aren't worth the indirection).
- Few or no recent decision-log mentions of changes to the section's content.
- Reference-shaped: tables, lists, file maps, directory layouts, endpoint catalogs. Not narrative prose.

**Never extract** these section types even if they meet the size threshold (active context, load-bearing terminology, or navigation aids):
- `## Project Overview` — sets project context.
- `## Directory Conventions` — load-bearing terminology used across CLAUDE.md.
- `## Finding Historical Context` — navigation aid for the archives.
- `## Known Patterns & Gotchas` / `## Known Issues & Gotchas` — consulted on every bug.
- `## Decisions Log` — active context (recent entries).
- `## Custom Skills (project-level)` table — small + active.
- Any section whose body has been touched in the last week (find via `git log --since='7 days ago' -p CLAUDE.md | grep <heading>`, when CLAUDE.md is in a repo).

Report candidates to the user with size + shape + a one-line guess at content. **Wait for explicit per-section approval before extracting anything.**

### C2. Suggest target filenames

Group candidates by topic. Common generic groupings:
- **`ARCHITECTURE.md`** — system architecture, phase pipelines, agent/advisor lists, file maps, data directory layouts, supported-input lists.
- **`DEVELOPMENT.md`** — tech stack, environment variables, local install/run instructions, rate-limit notes, log file locations, monitoring commands.
- **`OPERATIONS.md`** — production endpoints, admin/debug routes, deploy CLI commands, monitoring dashboards, user-feedback query procedures.
- **`DEPLOYMENT.md`** — infrastructure service IDs, hosting-provider CLI quirks, deploy hooks, environment promotion sequences.

**Topic-specific filenames are often a better fit.** When the project has well-defined domain areas (e.g., a single dominant reference doc), name the target file after the topic rather than forcing it into the generic shape:
- `METRICS.md` — all metric formulas, thresholds, calibration history for a metrics-heavy project.
- `DASHBOARD.md` — UI mode design, surface differences, page-level behavior.
- `DATA_MODEL.md` — schema reference, table layouts, key relationships.
- `API.md` — endpoint catalogs, request/response schemas, auth flows.
- `MODELING.md` — ML model cards, feature definitions, training pipelines.

Rule of thumb: if a candidate section is large enough to extract AND its content is dominated by one topic, name the file after the topic. If multiple smaller sections share an architectural theme, group them into `ARCHITECTURE.md`. Don't force everything into the generic four-file taxonomy if a topical name lands cleaner — future sessions find files by name, and `METRICS.md` is more discoverable than "the metric reference section inside ARCHITECTURE.md".

If a candidate doesn't fit any grouping, ask the user where it should go (or whether to skip it).

Propose the grouping (with filenames) and wait for explicit confirmation before writing.

### C3. Build the standalone file(s)

For each target file, write or append:

```markdown
# <Project> — <Topic> Reference

Stable reference for <topic>: <one-sentence description of what's in this file>. Extracted from `CLAUDE.md` on YYYY-MM-DD to keep active context lean.

Load this file when you need to:
- <Use case 1 — e.g., "Understand the orchestration flow.">
- <Use case 2 — e.g., "Look up where a specific function lives.">
- <Use case 3 — e.g., "Navigate the persistent disk layout.">

Active `CLAUDE.md` (same directory) contains <one line on what stays in CLAUDE.md — e.g., "directory conventions, infrastructure pointers, known patterns, recent decisions log, and links to other stable docs.">

---

<extracted section 1 verbatim>

<extracted section 2 verbatim>

...
```

When the target file already exists from a previous run, APPEND the new sections beneath the existing content. Do NOT rewrite the header — preserve the original extraction date for provenance.

### C4. Replace each extracted section in CLAUDE.md with a pointer stub

For each `## <Section Heading>` that was extracted, the stub is:

```markdown
## <Section Heading exactly as it was>
See `<TARGET>.md` for <brief description of what's there — same one-liner used in the target file's header>.
```

CRITICAL: **keep the section heading exactly as it appeared in the original** (same capitalization, same parenthetical suffix, same em-dashes). Future sessions scanning headers should find the same topics they expect — only the body changes from prose-and-tables to a single pointer line.

### C5. Verify Phase C

Report:
- For each extracted section: original lines/chars → stub lines/chars → bytes saved.
- New standalone files: name, total size, sections within.
- Net change in CLAUDE.md size after Phase C alone (separate from Phases A and B).
- Confirm every original section heading is still present in CLAUDE.md as a stub.
- Confirm the standalone files have the proper header + "Load this file when..." block + backlink to CLAUDE.md.

If a candidate was extracted but the resulting standalone file is < 2K, flag it — the indirection cost may exceed the savings; offer to revert.

### What Phase C does NOT do

- Does NOT extract sections smaller than ~30 lines / ~3K chars — cost of indirection exceeds the saved context.
- Does NOT extract sections in the deny list (Project Overview, Directory Conventions, Finding Historical Context, Known Patterns, Decisions Log, Custom Skills).
- Does NOT auto-extract. Always asks for per-section approval and per-file grouping.
- Does NOT rewrite the content being extracted — moves it verbatim. Compression of reference docs is out of scope (use a separate doc-refactor pass if needed).
- Does NOT delete sections without confirming with the user. If a candidate is genuinely never consulted, ask whether to delete outright vs. extract.

---

## Implementation notes (all phases)

- Use `sed -n 'A,Bp'` for line-range extraction. Avoid awk-only solutions because date matching across formats is brittle.
- Heredocs for the templated header blocks. Always use `<<'HEADER'` (single quotes) to prevent shell expansion inside the template.
- When grouping entries by month, parse the date with `grep -oE '^[0-9]{4}-[0-9]{2}-[0-9]{2}'` and split on `-`. Don't try to be clever with `date -d` — dates in CLAUDE.md are ISO 8601 strings, not shell-native.
- Some headings have variants: `### 2026-05-07 (late): ...` or `### 2026-05-05/06: ...`. The leading `YYYY-MM-DD` is always the first 10 chars after `### `. Use that for date matching, don't try to parse the rest.
- The `## ` heading boundary detection must skip the new `## Finding Historical Context`, `## Known Patterns & Gotchas`, and `## Decisions Log` headers (they're the boundaries of the sections being modified).

## Edge cases

- **No commit hashes in entries.** That's fine for all phases — the entry title is enough for the index, and pattern entries can omit the commit if not cited.
- **Entries with multi-dated headings (`### 2026-05-05/06: ...`).** Treat the earliest date as the entry's date for bucketing.
- **Entries with dates that span months at the cut boundary.** Use the entry's own date (leftmost), not the cut date.
- **Multiple Decisions Log sections.** Rare. Stop and ask the user which one to process; don't guess.
- **No dated entries at all.** Stop Phase A. Phases B and C can still run independently.
- **A pattern has only 1 instance but is repeatedly cited as a cautionary tale** (e.g., a Phase 4 cascade that almost shipped). It's OK to include it as a Pattern entry tagged `(1 instance — cautionary)` if the user wants future sessions to be alert for the recurrence. Ask the user.
- **Phase B finds no candidates worth consolidating.** Report that, do nothing, exit Phase B clean. Don't manufacture patterns to justify the run.
- **Phase C finds no extractable sections.** Same posture — report, exit Phase C clean, don't extract small or active sections just to justify a run.
- **A Phase C target file already exists** (e.g., `ARCHITECTURE.md` from a prior run). Append new sections to it; do NOT rewrite the existing header (preserves provenance) and do NOT overwrite prior sections without explicit user approval.
- **A section's heading contains characters that complicate the stub** (em-dashes, parens, special chars). Preserve the heading verbatim in the stub — copy-paste don't retype.

## Don't

- Don't try to "compress" individual decision-log entries in Phase A (one-line summaries, dropped context, etc.). Phase A MOVES entries; it doesn't rewrite them. Entry content stays verbatim in the archive.
- Don't delete CLAUDE.md before writing the new version. Always `mv CLAUDE.md.new CLAUDE.md` at the end after verifying.
- Don't run this on files other than CLAUDE.md unless `--target-file` was explicitly passed.
- Don't push or commit anything. This is a local file restructure; commits/pushes are a separate concern.
- Don't invent pattern names, instance counts, or root causes in Phase B. Source everything from the user's existing decision-log prose. When the prose is ambiguous, ASK.
- Don't promote a candidate to global memory in Phase B without explicit user approval. Even if a pattern looks cross-project, the user owns the global memory layout.
- Don't extract sections in Phase C that are on the deny list, smaller than the threshold, or recently edited — even if the user pre-approves a batch. Confirm per-section.
- Don't rewrite a section's content during Phase C extraction — Phase C MOVES sections verbatim. If a section needs rewriting, do that as a separate slice before or after the extraction.

---

## Lessons from prior runs

Patterns the skill has observed across multiple real runs. Apply them proactively even when the user hasn't mentioned them.

### Heading conventions vary by project

Different projects log their decisions differently. Examples seen so far:
- Standard: `### YYYY-MM-DD: title` inside `## Decisions Log`.
- Version-keyed: `### vN.M.K (YYYY-MM-DD) — title` inside `## Recalibration History` or `## Release History`.
- Mixed-dated: `### 2026-05-05/06: title` (range), `### v4.10.11 (Current, 2026-05-07) — title` (parenthetical qualifier).
- Undated old entries: `### v4.0` with no date at all — historical, predates the project's adoption of dating.

Procedure:
1. Discover the convention via A1 sanity-floor grep.
2. Confirm with the user when you find a non-default style. Don't STOP just because the default pattern returned zero.
3. Adapt the date-extraction regex to match.
4. Document the discovered convention in the INDEX file's "Project heading convention" subsection so the next run inherits it.
5. Undated old entries bucket under `pre-YYYY-MM.md` (a single archive that holds everything older than the earliest dated entry kept active) rather than per-month buckets.

### First-run honest report

The "Finding Historical Context" navigation section is ~35 lines / ~1.5 KB. On a first run where only a handful of entries qualify for the archive (e.g., 2 undated entries totaling 15 lines), CLAUDE.md grows net. **Report this honestly:** state the line/char delta, the structural reason (navigation overhead vs. archive size), and the compounding effect future runs deliver. Don't claim "saved bytes" if you added them. Don't STOP unless the growth is unexplained by the navigation section.

### Phase B's real win is findability, not compression

A canonical pattern entry (Signal / Fix shape / Detection rule / Project hooks / Instances / See-also) is heavier than a one-line Lessons-Learned bullet. Expect Phase B to GROW the section it consolidates (saw +~6.5 KB on one run). Be explicit with the user that the win is currency and findability: future sessions scan one structured section instead of grepping decision-log prose for related instances. Compression of the file is a Phase A / Phase C goal, not Phase B's.

### When to promote a project pattern to global memory

The signal to promote during Phase B:
- The pattern's fix shape names no project-specific symbols (no function names, file paths, table names from this codebase).
- The pattern's signal would recognise the same bug in another tech stack — same shape, different surface (e.g., "status string with trailing detail breaks `==`" applies to many systems, not just this one).
- The pattern's detection rule (when to check for it) is portable.

When all three are true, write the proposed global memory entry as a DRAFT and present it to the user along with the existing project pattern. The user owns the global memory layout; they approve or decline. Two real promotions captured this way: `feedback_verify_compute_order.md` (pipeline dependency-order bugs, recognisable in any pipeline language) and `feedback_status_string_startswith.md` (status field comparisons, recognisable across many storage layers). Both started as project patterns and were promoted only after the cross-project shape was articulated.

The project entry then becomes shorter — it cites the project-specific symptoms / hooks / instances and ends with `**See also (global memory):** \`feedback_<name>.md\``. The cross-project lesson lives once, in global memory.

### Topic-specific Phase C filenames

When a project has a dominant reference topic (a giant Metrics section, a domain-model dump, an API catalog), name the extracted file after the topic (`METRICS.md`, `DATA_MODEL.md`, `API.md`) rather than forcing it into `ARCHITECTURE.md`. Future sessions find files by name; topical filenames are more discoverable. Reserve the generic four-file taxonomy (ARCHITECTURE / DEVELOPMENT / OPERATIONS / DEPLOYMENT) for projects where several smaller related sections share an architectural theme.

### Maintenance threshold is a per-project judgment call

The skill's default `>50K chars` trigger is a heuristic. Some projects accumulate context faster than others. Document the project's own threshold in the "Maintenance rule" line of the Finding Historical Context section — `~50K`, `~100K`, `~150K`, whatever the project's natural cadence is. The threshold is a hint to future sessions, not a hard rule.

### Edit strategy for Phase C stubs

When replacing 5+ sections with stubs, a single Python script that opens the file, finds each heading, scans to the next `## ` heading, and rewrites the slice is much less brittle than 5+ separate multiline `Edit` calls. Sample shape:

```python
import re
path = "CLAUDE.md"
text = open(path, "r", encoding="utf-8").read()
replacements = [
    ("## <Heading 1>", "See `<TARGET>.md` for ..."),
    ("## <Heading 2>", "See `<TARGET>.md` for ..."),
    # ...
]
for heading, stub_body in replacements:
    idx = text.find(heading + "\n")
    if idx == -1: raise SystemExit(f"Heading not found: {heading!r}")
    rest = text[idx + len(heading) + 1:]
    m = re.search(r"^## ", rest, re.MULTILINE)
    if m is None: raise SystemExit(f"No following ## heading after: {heading!r}")
    section_end = idx + len(heading) + 1 + m.start()
    new_block = f"{heading}\n\n{stub_body}\n\n"
    text = text[:idx] + new_block + text[section_end:]
open(path, "w", encoding="utf-8").write(text)
```

Saves several rounds of Edit + Read verification. Safe because each heading is unique and the script fails fast if a heading is missing.

### Always back up

Phase A's required `cp CLAUDE.md "CLAUDE.md.backup-before-split-$(date +%Y%m%d)"` applies even when Phase A is skipped (`--patterns-only`, `--extract-only`). Phases B and C also mutate CLAUDE.md; the backup is a single revert away from any mistake. The backup is small (it's one file copy) — never skip it.

### Verify with `diff` against the backup

After all phases complete, `diff <(sed -n '1,10p' CLAUDE.md) <(sed -n '1,10p' CLAUDE.md.backup-before-split-YYYYMMDD)` and the same for the tail should both produce empty output. Preamble and postamble must be byte-identical to the backup. If they're not, something went wrong in the heading-boundary detection or stub replacement. This sanity check is fast and catches the most common Phase C bug.
