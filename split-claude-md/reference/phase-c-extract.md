## Phase C — Extract stable reference sections

Skip this phase if `--no-patterns --no-extract` was passed jointly. Run only this phase if `--extract-only` was passed.

Some `## ` sections in CLAUDE.md are stable reference docs (architecture pipelines, file maps, directory layouts, advisor / endpoint tables, environment variable lists). They're consulted maybe once per ten conversations — but every conversation that doesn't need them still pays their context cost. Phase C moves them to standalone sibling files and leaves one-line pointer stubs in CLAUDE.md so future sessions find them by section heading and load on demand. **Like Phase B, this is judgment-heavy — the skill identifies candidates but the user/AI decides which to extract.**

### C1. Survey for candidate sections

`survey.py` (step A0) already printed this list under `PHASE C CANDIDATES`, with the deny-list sections named separately so they cannot be picked by mistake. Re-run it here if Phase A changed the file. What it gives you is SIZE only, which qualifies a section without deciding it; the stability and shape judgments below are still yours.

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


### C6. Choose the DESTINATION, not just the filename (added 2026-08-24)

C2 and C3 assume one destination: a sibling markdown file plus a pointer stub.
That is right for a lookup table and wrong for a procedure, and the difference
is discovery rather than size.

A pointer stub is found only when a session reads the stub and acts on it. A
skill's DESCRIPTION is in context every session, so Claude finds the content by
relevance without anybody remembering a pointer. Anthropic states the rule
plainly: content that is a multi-step procedure, or that only matters for one
part of the codebase, belongs in a skill or a path-scoped rule rather than in
CLAUDE.md. The blog guidance puts a number on it: a 30-line procedure in
CLAUDE.md should be a skill.

**The test.** Is this content something a session LOOKS UP, or something a
session FOLLOWS?

- **Looks up** (a table, a file map, a catalog, a layout, a set of ids): a
  sibling markdown file plus a pointer stub. Unchanged from C2 to C5.
- **Follows** (ordered steps, a checklist, a workflow with a beginning and an
  end): a skill.

**Building the skill.** Move the section verbatim into `SKILL.md` under a new
skill directory, write a description whose trigger phrases are the words a
session would actually use, and validate the frontmatter with skill-creator's
`quick_validate.py` before finishing. An unquoted `: ` is invalid YAML, a `->`
counts as an angle bracket, and a description past 1024 chars silently loses the
trigger phrases at the end, which is exactly the half that makes it fire.

**The cost, which is not zero.** Every model-invocable skill's description loads
in every session. Ten small skills are worse than one good one. When a procedure
fires rarely, or has side effects, set `disable-model-invocation: true`: the
description then stays out of context entirely and the skill costs nothing until
it is invoked by name.

**The stub.** A skill needs no pointer stub, because the harness surfaces it. If
CLAUDE.md must still mention it, one line naming the skill is enough, and it
names the trigger rather than restating the steps, so the two cannot drift.

**Compaction.** An invoked skill body is re-injected after a compaction but
capped at 5,000 tokens per skill, and truncation keeps the START of the file. A
procedure long enough to be worth extracting is long enough to be truncated, so
put the load-bearing steps near the top.

### C7. Before extracting anything, ask whether it should be DELETED (added 2026-08-24)

Phase 0 runs first for this reason. A section that the repository itself answers
is not a Phase C candidate: extracting it pays a write, keeps a file nobody
should read, and leaves a pointer aiming a future session at a worse source than
the code. If Phase 0 was skipped, apply its one question here before choosing a
destination. See `phase-0-prune.md`.
