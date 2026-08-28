---
model: sonnet
name: split-claude-md
description: Six-phase CLAUDE.md cleanup for a file that has grown too large. Phase 0 deletes what the repository itself answers. Phase A rotates old dated records into monthly archives with an index and a navigation header. Phase B consolidates recurring failure patterns into a Known Patterns section with current instance counts. Phase C extracts stable reference sections to sibling files or to a skill, leaving a pointer. Phase D keeps a rule in place and moves only its evidence to a satellite, for always-loaded files where a rule moved out stops being read. Phase E scopes file-triggered rules to .claude/rules with paths frontmatter so they leave the always-loaded set entirely. Use when CLAUDE.md is over its threshold, when a rule is being followed unreliably, or when the user asks to split, shrink, archive, rotate, consolidate, extract, prune or scope a CLAUDE.md.
disable-model-invocation: false
argument-hint: "[--cut-date YYYY-MM-DD | --keep-days N | --target-file <path> | --no-prune | --patterns-only | --no-patterns | --extract-only | --no-extract | --no-scope]"
---

# Split CLAUDE.md - prune, archive, consolidate, extract, compress, scope

An always-loaded file is re-read on every request of every session. Text in it is
not stored once; it is paid for continuously. Six things grow over time:

1. Old dated records load every turn even when no future session needs them.
2. Recurring bugs accumulate as scattered prose with stale instance counts, so a
   future session cannot tell that a "new" bug is the Nth instance of a known one.
3. Stable reference docs sit inline although they are consulted rarely, and every
   session that does not need them still pays for them.
4. Rules accumulate their own evidence, and the war story outgrows the rule.
5. Content the repository already answers gets written down and then goes stale,
   so the file starts contradicting the code.
6. Rules that only matter for one file type load in every session regardless.

**There are TWO reasons to cut, and the second one is usually missed.** Cost is
the obvious one. Adherence is the other: a longer file is followed less
reliably, which Anthropic states twice. So a file sitting exactly at its cost
threshold is not finished, and a rule being ignored is a reason to cut rather
than a reason to restate the rule more loudly.

## Read this first

`reference/loading-model.md` holds the mechanics every phase depends on: what
each destination costs, what loads lazily, what is free, what is lost after a
compaction, and the hard limits. **Read it before choosing a destination for
anything.** Two facts from it decide most of a run:

- **`@path` imports do not reduce context.** Imported files load at launch with
  the file that imports them. This is the usual wrong answer to a large
  CLAUDE.md and it saves nothing.
- **A rule moved to a lazy destination is LOST after a compaction** until a
  matching file is read again. A rule that fires on a FILE survives that. A rule
  that fires on a CONVERSATION does not, and must not be moved.

## The six destinations, cheapest last

- CLAUDE.md, and unscoped `.claude/rules/*.md`: full content, every session.
- A skill: description every session, body only when it runs. Zero with
  `disable-model-invocation: true`.
- A sibling markdown file plus a pointer stub: the stub only.
- `.claude/rules/*.md` with `paths:` frontmatter: nothing until Claude reads a
  matching file.
- A nested CLAUDE.md in a subdirectory: nothing until Claude reads a file there.
- Deleted: nothing, ever again.

## Run order

Phase 0, then A, then B, then C, then D, then E. The letters are names; this
line is the order. Phase 0 runs first so every later phase moves a smaller set.
Phase E runs last because it needs the rules already reduced to their imperative.

Each phase lives in its own file so a compaction cannot truncate it away. Read
the phase file when you reach that phase, not before.

- **Phase 0**, delete what the repo answers: `reference/phase-0-prune.md`
- **Phase A**, archive old records: `reference/phase-a-archive.md`
- **Phase B**, consolidate patterns: `reference/phase-b-patterns.md`
- **Phase C**, extract reference sections: `reference/phase-c-extract.md`
- **Phase D**, split rules from their evidence: `reference/phase-d-rule-evidence.md`
- **Phase E**, scope rules to file paths: `reference/phase-e-path-scope.md`
- Implementation notes, edge cases, and lessons from prior runs:
  `reference/cross-phase.md`

The skill's own checks: `python3 <skill-dir>/run_tests.py` runs every test file
and prints one total. It fails when any file reports no tally, because a runner
that silently covers a fraction of its suite is the exact shape of a check that
cannot fail.

## When to run

- The user asks to "split" / "shrink" / "archive" / "rotate" / "consolidate" / "extract" CLAUDE.md.
- `wc -c CLAUDE.md` reports > 50,000 chars and the bulk is decision-log entries.
- After a long session that added many decision entries.
- Decision-log entries explicitly cite "Nth instance", "Updated count", or "recurring pattern" — a sign Phase B consolidation is overdue.
- CLAUDE.md contains large stable reference sections (architecture pipelines, file maps, directory layouts, advisor / endpoint tables) that haven't been edited in many sessions — a sign Phase C extraction is overdue.
- A rule in the file is being followed unreliably. Length reduces adherence, so
  a cut is a candidate fix and restating the rule is not.
- The file describes something the repository already answers, such as a
  directory layout, a dependency list, or a module inventory. Phase 0 is due,
  and a section the repo now CONTRADICTS is the more expensive case.
- The file carries rules that only matter for one file type (a framework, a
  document format, a container file). Phase E moves those out of every session.
- `/context` shows the always-loaded block dominating the startup breakdown, or
  `/doctor` proposes trims on a checked-in CLAUDE.md.
- The file is over 200 lines, which is Anthropic's stated target per CLAUDE.md.

## When NOT to run

- CLAUDE.md is under 50K chars AND no recurring patterns are obvious AND no large reference sections — the cleanup adds maintenance burden without saving meaningful context.
- The file has no dated records in ANY of the three shapes Phase A can archive (`### YYYY-MM-DD: title` entries, whole dated `## ` sections, or dated top-level bullets `- Shipped (YYYY-MM-DD): ...`); Phases B and C can still run independently.
- All entries are from the last 30 days (or, on a project that cuts by state, every entry is still load-bearing) AND no recurring patterns exist AND all sections are small/active — nothing to do at any phase.
- The file is NOT always-loaded. A satellite, an archive, or a reference doc
  that only loads when something opens it costs nothing per session, so
  shrinking it buys nothing. Confirm with `/context` which files actually load
  before treating any file as expensive.

## Inputs

Default target: `CLAUDE.md` in the current working directory. Default cut for
Phase A: 30 days before today. Archives are `CLAUDE_DECISIONS_YYYY-MM.md` beside
CLAUDE.md. All six phases run in the order above.

- `--target-file <path>` operate on a CLAUDE.md outside the current directory.
- `--cut-date YYYY-MM-DD` Phase A, records strictly before this date archive.
- `--keep-days N` Phase A, keep records from the last N days.
- `--no-prune` skip Phase 0. `--no-patterns` skip B. `--no-extract` skip C.
  `--no-scope` skip E.
- `--patterns-only` run only B. `--extract-only` run only C.

`--patterns-only` and `--extract-only` cannot be combined. If both are passed,
stop and ask which was meant. Several `--no-*` flags together are fine.

If no arguments were passed, use the defaults and report what you are about to
do before you do it.

## Step 1. Measure, before anything else

**Run `/context` and record the startup breakdown.** It reports tokens by
category, names which CLAUDE.md and memory files ACTUALLY loaded, and prints its
own suggestions. `wc -c` counts bytes, python `len()` counts characters, and
neither counts tokens, which is the bill. On a file with Hebrew or other
multibyte text all three disagree.

`/context` is also the only way to prove a file loaded at all. A rule that
silently stopped loading reads exactly like a rule being ignored, and no
character count can tell them apart.

Then run the surveyor, which answers the discovery questions for Phases 0, A, C,
D and E in one pass and prints its evidence:

```bash
python3 <skill-dir>/survey.py <path-to-CLAUDE.md> --keep-days 30
```

On a checked-in CLAUDE.md, run `/doctor` too and read its trim proposal. It is
evidence for Phase 0, not a verdict.

**Report the line count against 200.** That is Anthropic's stated target per
CLAUDE.md file. A project's own threshold governs the run; the 200-line figure
keeps the gap visible even when the project threshold is met.

## Step N. Measure again, and report what MOVED versus what went

Run `/context` at the end and report the measured drop, not the size of the text
you relocated. They differ, and only one of them is a saving.

Report these separately, because they are not the same kind of result:

- **Deleted** (Phase 0): permanent, never comes back.
- **Moved to a lazy destination** (C to a skill, E to a scoped rule): gone from
  startup, returns when needed, lost after a compaction until then.
- **Moved to an archive or satellite** (A, C to a file, D): gone from startup,
  found only if a session follows the pointer.
- **Compressed in place** (D's retained rules): still loaded, just shorter.

A single percentage over all four hides which one happened, and they carry
different risks.

## Universal rules, every phase

**Back up before the first mutation, and never skip it.** A run mutates several
files: CLAUDE.md is rewritten, an archive is appended to, the index is edited in
place, and Phases C and E create new files. Copy each existing one with the same
dated suffix, skip absent files without erroring, and never overwrite a same-day
backup, which is the only true pre-run state. Back up to the project directory,
never to an ephemeral job tmp dir. The full loop is in `phase-a-archive.md` A3
and applies even when Phase A is skipped.

**Fail closed on shape.** `survey.py` classifies a section REFERENCE or RULE and
proves reference-ness rather than assuming it. Calling a rule "reference" is the
harmful direction, because it ends with a behaviour rule extracted out of an
always-loaded file. Calling reference "rule" only costs a slightly smaller cut.

**A heading check is not a rule check.** Confirming every heading survived passes
on a stub whose rule was gutted. Before starting, hand-write the distinctive
phrases of the load-bearing rules, and grep the finished file for every one. That
is the check that proves the cut was safe.

**Never claim a saving you did not measure.** Phase B normally GROWS the file and
that is correct, because its win is currency and findability. Say so.

**A rule shaped "every time X, always do Y" wants a hook, not a destination.**
CLAUDE.md reaches Claude as a user message, so it is context and not enforcement,
wherever it lives. No phase here can make a rule binding. When one turns up, name
it a `PreToolUse` hook candidate in the report and move on.

**Compare the character set against the ORIGINAL file, not against an absolute.**
A pure-ASCII assertion is the wrong check and fails on a legitimate file that
carries Hebrew scan terms or arrows on purpose.

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
- Don't use `@path` imports to make a file smaller. They load at launch with the
  importing file and save nothing.
- Don't move a rule whose trigger is a conversation to a lazy destination. One
  compaction and it is gone with no file read that will bring it back.
- Don't delete a RULE-shaped section in Phase 0, however derivable it looks.
- Don't put a rule, or any fact a session needs, in an HTML comment. Comments are
  stripped before Claude sees them, so a rule there is invisible, not cheap.
- Don't report a saving that `/context` did not measure.
- Don't leave a `.claude/rules/` file without `paths:` frontmatter and call it a
  saving. Unscoped rules load every session.
