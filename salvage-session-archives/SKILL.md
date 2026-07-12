---
model: sonnet
name: salvage-session-archives
description: Mine the Claude Code session-transcript leftover folders for a given project, extract any facts/decisions/gotchas not already captured in the project CLAUDE.md, append them under a "Salvaged from session archives" section after a duplicate/contradiction cross-check, then delete the leftover folders. Use when the user says "salvage the session archives", "extract leftover transcripts", "collect important information from the leftover folders".
disable-model-invocation: false
---

# Salvage session archives for a project

Goal: recover any durable knowledge that lives in old session `.jsonl` transcripts but never made it into the project's `CLAUDE.md`, then clean up.

The Claude Code harness writes transcripts into auto-named "leftover folders" with dashed paths (e.g. `~/.claude/projects/-Users-<username>--claude-projects-<ProjectName>/`). Sessions that ended cleanly already distilled their content via an end-of-session save, but premature exits, subagent runs, and quietly-discovered gotchas often leave salvageable material behind.

## When to run

- User asks to salvage / collect / extract / mine session archives or leftover folders.
- End-of-quarter cleanup pass across multiple projects.

## Steps

### 1. Identify the project from the current working directory

Do NOT ask the user which project to work on. Derive `<project_name>` from the current working directory (`pwd`). Handle these cases:

- `pwd` is `~/.claude/projects/<ProjectName>/` → use `<ProjectName>` directly. This is the canonical project directory.
- `pwd` is the project's source repo (anywhere on disk) or a subdir of it → use the repo directory's basename as `<ProjectName>`. The canonical project directory is `~/.claude/projects/<ProjectName>/`.
- `pwd` is a dash-prefixed leftover folder like `~/.claude/projects/-Users-<username>--claude-projects-<ProjectName>/` → use `<ProjectName>` (the trailing segment after the last `-`).
- `pwd` is `~/.claude` itself or any other location that doesn't clearly map to a project → only in this case, list `~/.claude/projects/` and ask the user which project to target (show the 3-4 most recently-touched via `ls -lt`).

State the inferred project name in one sentence before continuing, so the user can redirect if needed. Then proceed without waiting for confirmation.

### 2. Find every leftover folder for that project

Run `find ~/.claude -maxdepth 3 -type d -iname "*<project_name>*"` and inspect the results. Real leftover folders are the dash-prefixed ones (Claude Code encodes each session's working-directory path into the folder name, replacing every `/` with `-`, so a `-Users-<username>-...` prefix is just your `$HOME` dash-encoded). For example:

- `~/.claude/projects/-Users-<username>--claude-projects-<ProjectName>/` (main transcripts)
- `~/.claude/projects/-Users-<username>--claude-worktrees-*<ProjectName>*/` (worktree-session transcripts)
- `~/.claude/projects/-Users-<username>-...-<ProjectName>/` (transcripts from running Claude inside the project's source repo, wherever it lives)

The canonical `<ProjectName>/` folder (the one containing `CLAUDE.md`) is NOT a leftover folder — never touch it during this step.

Inside each leftover folder, look for:
- `*.jsonl` files at the top level (one per session)
- `subagents/*.jsonl` (research that may never have surfaced to the main transcript)

Note file sizes and modification dates so the next step can prioritise the largest / most recent transcripts.

### 3. Read the canonical CLAUDE.md first

Read `~/.claude/projects/<project_name>/CLAUDE.md` in full. This is the canonical truth. Everything the salvage pass produces must be compared against it before being written back.

If no CLAUDE.md exists, note that — the salvage section may be unusually large because nothing has been distilled yet.

### 4. Spawn a general-purpose subagent for the mining

Do NOT read the .jsonl files inline — they are often >1 MB each and burn the main context. Delegate via the Agent tool (`subagent_type: general-purpose`). Brief the subagent with:

- Absolute paths of all leftover-folder .jsonl files plus any `subagents/*.jsonl`.
- Absolute path of the canonical `CLAUDE.md`.
- What to extract: technical facts, decisions with reasoning, gotchas / failed attempts, smoke-test commands and one-liners, API quirks, env-specific behavior.
- What to EXCLUDE: anything already covered in CLAUDE.md, intermediate conclusions that were later corrected within the same session, generic chitchat.
- Output instructions: append (via Edit with a unique anchor at end of file, NOT Write) a section titled exactly `## Salvaged from session archives`. Organize by topic, not by session. Tight bullets. Plain language: no em dashes, no AI-signal vocabulary (no "crucial", no "delve"), straight quotes.
- Reporting back: total count of net-new items, top 3 most useful, and whether the section ended up empty.

If the subagent reports the section is essentially empty, that is a GOOD outcome. It means previous end-of-session saves already did their job. Note this in the user-facing summary.

### 5. Cross-check the appended section for duplicates AND contradictions

This step exists because the subagent only sees what it was given and can miss subtle overlaps with existing prose. After the subagent returns:

1. Grep the existing `CLAUDE.md` for each distinctive token from the new section (URLs, commands, log strings, file paths, numbers, function names).
2. For each match, classify as:
   - **Contradiction** — the new bullet says one thing and the existing prose says another. STOP and ask the user which is correct.
   - **Near-verbatim duplicate** — the new bullet restates what's already documented. Remove the duplicate via Edit.
   - **Rule-and-implementation pair** — the existing doc states a rule, the new bullet provides the implementation (e.g. shell snippet). Keep the implementation but trim the redundant rule sentence and add a short pointer back ("Implements the rule already noted in section X.").
   - **Approximate vs precise** — existing says "~270", new says "271". Consistent; keep the precise number.
   - **Truly new** — no overlap. Keep as-is.

Report counts: contradictions found, duplicates trimmed, rule/implementation pairs reconciled, items kept verbatim.

### 6. Present the findings to the user

Before any deletion, surface:
- Project name and number of leftover folders identified.
- Count of net-new salvaged items (post-trim).
- The top 3-5 most useful items, one sentence each.
- Contradictions found (if any) and how they were resolved.
- Duplicates trimmed (counts only, not full text).
- Whether the salvage section is "near-empty" (confidence signal for safe deletion).

### 7. Confirm and delete

Ask the user to confirm before deleting. On confirmation, `rm -rf` each leftover folder identified in step 2. After deletion, run a quick `find` to confirm only the canonical project folder remains. Never delete the canonical folder.

If the user prefers to keep the leftover folder around (e.g. for further mining), stop here and report that the salvage write-back is complete but cleanup is pending.

## Output format for the salvage section

The section appended to CLAUDE.md should look like:

```markdown
## Salvaged from session archives

Items below were extracted from older session transcripts (<dates>) and are NOT already covered elsewhere in this file.

### <Topic A>
- One-line fact, with file path / commit hash / command if applicable.
- ...

### <Topic B>
- ...
```

Topic headings are organic — pick names that match the codebase's existing vocabulary, not a fixed taxonomy.

## Gotchas learned from running this skill

- **Don't read .jsonl files inline.** Even 200-line transcripts are often 400+ KB after embedded tool output. Always delegate to a subagent.
- **`subagents/` subfolders are rare** but high-value when present — they contain research that may have only existed as a tool result, never quoted in the main message stream.
- **The canonical project folder is the one containing `CLAUDE.md`,** under `~/.claude/projects/<ProjectName>/`. The skill operates on `~/.claude/projects/...` only; it never touches a source repo elsewhere on disk.
- **Cross-check is the load-bearing step.** An early run produced 7 items, of which 3 turned out to be near-duplicates that the subagent missed because each session's transcript looked novel in isolation. Always do step 5 even when the subagent claims everything is new.
- **Contradictions are rare but real.** If the salvage finds "X behaves as Y" and the doc says "X behaves as Z", the doc is usually right (it's been edited more recently) but ask the user before overwriting either.
- **AI-signal vocabulary creeps in.** Subagents tend to write "crucial", "delve", and em dashes. Sanity-check the appended section against the plain-prose rules before considering it done.
- **`rm -rf` only the dash-prefixed folders.** The classifier may flag the command; running with absolute paths (no `cd`) avoids the prompt. Never delete `~/.claude/projects/<project_name>/` — that's the canonical home.
