# The loading model: what actually costs context, and what does not

Every phase of this skill is a bet about how Claude Code loads a file. Get the
bet wrong and a run moves 30K of text and saves nothing. This file holds the
mechanics. Read it before choosing a destination for anything.

Verified against `code.claude.com/docs/en/memory`, `/context-window` and
`/features-overview` on 2026-08-24. Re-verify before trusting a figure: these
are product behaviours and they move.

## The six destinations, and what each one costs

- **CLAUDE.md** (`./CLAUDE.md`, `./.claude/CLAUDE.md`, `~/.claude/CLAUDE.md`).
  Full content, every session, every request. The most expensive place text can
  live. A file in the directory hierarchy at or above the launch directory loads
  at launch.
- **A nested CLAUDE.md in a SUBDIRECTORY of the launch directory.** Loads ON
  DEMAND, when Claude reads a file in that directory. Free until then.
- **`.claude/rules/*.md` with NO `paths:` frontmatter.** Loads every session,
  same cost as CLAUDE.md. Splitting into these buys organisation, never context.
- **`.claude/rules/*.md` WITH `paths:` frontmatter.** Loads only when Claude
  reads a file matching one of the globs. This is the one true lazy mechanism
  for a RULE. See `phase-e-path-scope.md`.
- **A skill.** The description loads every session so Claude can choose it. The
  body loads only when the skill runs. With `disable-model-invocation: true`
  even the description stays out, and the skill costs zero until invoked by name.
- **A plain sibling markdown file plus a pointer stub.** Costs the stub. The
  body loads only when a session decides to open it, which requires a session to
  read the stub and act on it. Cheapest, and the weakest discovery of the six.

## What does NOT save context, and is the usual wrong answer

**`@path/to/file` imports do not reduce anything.** The documentation is
explicit: imported files are expanded and loaded into context at launch
alongside the CLAUDE.md that references them. An import is an organisation tool.
It is the first thing most people reach for when a CLAUDE.md is too large and it
delivers nothing.

Import mechanics worth knowing anyway: relative paths resolve against the file
holding the import, not the working directory; imports nest to a maximum depth
of four hops; import parsing skips code spans and fenced blocks, so a path in
backticks stays literal text.

## What IS free

**Block-level HTML comments are stripped before the content reaches Claude.**
`<!-- maintainer notes -->` costs zero tokens and stays visible when the file is
opened with Read. Comments inside code blocks are preserved and do cost tokens.

Use it for text that exists for the human maintainer and for nothing else:
provenance markers, extraction dates, a run log, a note about why a section is
shaped the way it is. Never a rule, never a fact a session needs, because a
stripped comment is invisible to every session.

## Two reasons to cut, and the second one is usually missed

Cost is the obvious one. Adherence is the other, and it changes the target.
The documentation states it twice: "Longer files consume more context and reduce
adherence" and "Shorter files produce better adherence".

So a file that sits at its cost threshold is not finished. If a rule is being
followed unreliably, the file being long is a candidate cause, and the fix is to
cut rather than to restate the rule more loudly.

Anthropic's stated target is **under 200 lines per CLAUDE.md file**. Treat that
as the reference point, not as this skill's threshold, which is per project.
Report the run's line count against 200 so the gap is visible even when the
project's own threshold is met.

## Hard limits

- A CLAUDE.md up to 4 MiB loads in full. A LARGER FILE IS SKIPPED ENTIRELY, with
  every rule in it silently gone.
- The auto-memory index `MEMORY.md` loads only its first 200 lines or first
  25KB, whichever comes first. Content past that is dropped at session start.
  Claude Code warns when the file nears a limit and errors when a write puts it
  over. Auto-memory TOPIC files are not loaded at startup at all, which is what
  makes the satellite-index pattern correct.
- A skill body re-injected after a compaction is capped at 5,000 tokens per
  skill and 25,000 tokens total, oldest dropped first. Truncation keeps the
  START of the file. This is why this skill is a short driver plus reference
  files rather than one long SKILL.md.

## Compaction, which decides whether a lazy destination is safe

After a compaction:

- Project-root CLAUDE.md and unscoped rules: re-injected from disk.
- Rules with `paths:` frontmatter: LOST until a matching file is read again.
- Nested CLAUDE.md in a subdirectory: LOST until a file there is read again.
- Invoked skill bodies: re-injected, capped as above.
- Skill DESCRIPTIONS: not re-injected. Only skills already invoked survive.

The consequence for this skill: any phase that moves a rule to a lazy
destination must ask whether the rule can afford to be absent after a
compaction. A rule that fires on a FILE can. A rule that fires on a
CONVERSATION cannot, because no file read will bring it back.

## Enforcement is a different question from loading

CLAUDE.md reaches Claude as a user message after the system prompt, not as part
of it. It is context, not configuration. A rule that must hold every time is a
`PreToolUse` hook, not a line in any of the six destinations above.

When a phase of this skill finds a rule shaped "every time X, always do Y",
name it as a hook candidate in the report. Moving it is not the same as making
it run.

## How to measure, and why `wc -c` is the wrong instrument

`wc -c` counts bytes. Python `len()` counts characters. Neither counts tokens,
and tokens are the bill. Hebrew and other multibyte text move all three apart.

`/context` reports the live breakdown by category, names which CLAUDE.md and
memory files ACTUALLY loaded, and prints its own suggestions. `/context all`
adds per-tool token counts. It is the only way to prove a file loaded at all,
which is the failure a character count can never see: a rule that silently
stopped applying reads exactly like a rule that is being ignored.

`/doctor` proposes trims for a checked-in CLAUDE.md. It cuts what Claude can
derive from the codebase and keeps pitfalls, rationale and conventions that
differ from tool defaults. That is the same test Phase 0 applies by hand.

The `InstructionsLoaded` hook logs exactly which instruction files load, when,
and why. It is the right check after a Phase E cut, and it is stronger than any
grep, because it observes the load rather than inferring it from the text.

## Monorepo note

`claudeMdExcludes` in settings skips ancestor CLAUDE.md files by absolute-path
glob, at any settings layer, and arrays merge across layers. A managed policy
CLAUDE.md cannot be excluded. Relevant only when someone else's CLAUDE.md is
inflating the launch context; it is not a tool for shrinking your own.
