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

Report candidates to the user with rough instance count, the symptom signature, and one sample entry per pattern. **The confirmation gate splits by what is actually judgment-heavy.** Refreshing EXISTING patterns (bumping instance counts, appending evidence-backed instance rows) proceeds without asking; report it after, with the size delta. Creating a NEW pattern entry, renaming a pattern, or promoting anything to global memory still requires the user's confirmation first. **And when the file is only moderately over threshold, hold Phase B to the refresh deliberately:** a counts-and-rows pass measured +4.8K on 2026-08-10, while entry-writing passes measured +10.7K and +17.6K on the two runs before it and can eat most of Phase A's savings. That restraint is what let a 30K archive land as a 24K net cut.

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

