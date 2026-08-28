## Phase E - Scope rules to file paths

Skip this phase if `--no-scope` was passed. It runs LAST, after Phase D.

Phase D keeps every rule in the always-loaded file and moves only its evidence
out. That sets a floor: once every rule is down to its imperative plus its tell,
extraction has nothing left to take, and the only way lower is to delete rules.
`survey.py` prints that floor and this skill has always told you to stop there.

Phase E goes below it without deleting anything. A rule in `.claude/rules/` with
`paths:` frontmatter is not loaded at session start. It loads when Claude reads a
file matching one of its globs, and it is not loaded at all in a session that
never touches such a file. The rule still fires exactly where it applies.

Measured on the global CLAUDE.md, 2026-08-11: 13 of 13 Phase C candidates were
rule-shaped and the estimated floor was near 16,100 tokens. Every rule tied to a
file type is a candidate to move below that number.

### E1. THE CAVEAT, and read it before choosing anything

**A rule with `paths:` frontmatter is LOST after a compaction, until Claude reads
a matching file again.** A nested CLAUDE.md in a subdirectory behaves the same
way. Unscoped rules and the project-root CLAUDE.md are re-injected from disk.

So the question that decides every candidate is not "is this rule big" and not
"is this rule about Django". It is:

**Does this rule fire on a FILE, or on a CONVERSATION?**

A rule that fires on a file survives the caveat, because the next matching read
brings it back at exactly the moment it is needed. A rule that fires on a
conversation does not, because no file read will ever return it, and after one
compaction it is simply gone.

Get this backwards and the file gets smaller while a behaviour rule quietly stops
applying. That is the same failure Phase D exists to prevent, arriving through a
different door.

### E2. What qualifies

A rule qualifies when ALL of these hold:

- Its trigger is a file type, a directory, or a framework surface you can write
  as a glob.
- A session that never opens such a file has no use for it.
- Losing it after a compaction is harmless, because the next matching read
  reloads it.
- It is not needed to decide WHETHER to open such a file in the first place.

That last one is the subtle exclusion. A rule saying "never edit the vendored
directory" must be in context BEFORE Claude reads a vendored file, so scoping it
to that directory arms it exactly one step too late.

Worked examples of qualifying rules, from real always-loaded files:

- Django rules, scoped to `**/models.py`, `**/admin.py`, `**/views.py`,
  `**/settings.py`, `**/migrations/**`
- Django template rules, scoped to `**/templates/**`
- Word and PowerPoint right-to-left rules, scoped to the scripts that build them
- draw.io grammar, scoped to `**/*.drawio` and `**/render.py`
- Container and hosting rules, scoped to `**/Dockerfile`, `**/render.yaml`,
  `**/docker-compose*.yml`
- Frontend contrast and viewport rules, scoped to `**/*.{css,scss,html,jsx,tsx,vue,svelte}`

### E3. What does NOT qualify, and this list is longer than it looks

- Anything about how to talk to the user, what to lead with, or when to ask.
- Anything about verification posture, autonomy, or when to stop.
- Anything about writing style, voice, or what may leave for a customer.
- Model routing, session limits, budget rules.
- A rule that decides whether to open a file, per E2.
- A rule whose only trigger is a topic rather than a file. "Diagrams are draw.io
  by default" fires when someone ASKS for a diagram, before any `.drawio` file
  exists. The grammar for writing one is scopeable; the choice of tool is not.

That last pair is the shape to watch. One rule often splits into a
conversation half that stays and a file half that moves. Split it rather than
forcing the whole rule into one destination.

### E4. Write the rule file

One file per theme in `.claude/rules/`, or `~/.claude/rules/` for a rule that
applies to every project on the machine. Files are discovered recursively, so
subdirectories are allowed. User-level rules load before project rules, which
gives project rules the higher priority.

```markdown
---
paths:
  - "**/models.py"
  - "**/admin.py"
  - "**/migrations/**"
---

# Django model and admin rules

<the rule text, moved verbatim from CLAUDE.md>
```

**A rules file with NO `paths:` field loads every session, exactly like
CLAUDE.md.** Splitting into unscoped rules buys organisation and zero context.
If the frontmatter is missing or malformed, the saving is silently zero and the
file still looks split. Assert the field is present on every file this phase
writes.

Glob mechanics that bite:

- Brace expansion multiplies. `src/*.{ts,tsx}` is two patterns; `{a,b}/{c,d}/*.{ts,tsx}`
  is eight. A rule's whole `paths:` list shares a budget of 1,000 expanded
  patterns and 4 MiB. A pattern that would exceed the budget is used UNEXPANDED,
  and its literal braces then match nothing.
- `[` starts a bracket expression. `photos [2024/**` is invalid, matches nothing,
  and the rule's other patterns keep working, so the failure is partial and
  quiet. Escape a literal bracket as `photos \[2024/**`.
- Matching triggers when Claude READS a matching file, not on every tool use.

### E5. Cut CLAUDE.md, and leave the right amount behind

Delete the moved rule from CLAUDE.md. Do not leave a pointer stub: a stub costs
context and a path-scoped rule needs no discovery, because the harness loads it.

Leave behind only what the conversation half needs, which is often nothing and is
sometimes one line. When you do leave a line, it names the trigger and not the
rule, so the two copies cannot drift into disagreement.

### E6. Verify Phase E, and a grep is not enough here

The check that matters is whether the rule LOADS, and text cannot answer that.

- **Observe the load.** Wire the `InstructionsLoaded` hook, which logs which
  instruction files load, when, and why. Open a matching file and confirm the
  rule appears. This observes the mechanism instead of inferring it.
- **A two-way control.** Open a file that must NOT match and confirm the rule
  does not load. A check that only proves the rule can fire is half a control:
  a glob of `**/*` fires on everything and saves nothing.
- **`/context` before and after.** The saving is the drop in the startup
  breakdown, not the size of the file you moved. Report the measured drop.
- **Frontmatter present on every written file**, asserted, per E4.
- **The must-survive list from Phase D applies here too.** Grep the moved rule's
  distinctive phrase and confirm it is present in exactly one place, and that
  the place is the rules file rather than both.

### E7. When a rule must never be missed, it is a hook and not a rule

CLAUDE.md reaches Claude as a user message. A rule is context, not enforcement,
wherever it lives. Phase E changes WHEN a rule is read; it cannot make one
binding.

If this phase meets a rule shaped "every time X, always do Y", say so in the
report and name it a `PreToolUse` hook candidate. Scoping it is still an
improvement, and it is not the fix that rule actually wants.

### Phase E does NOT

- Move a rule whose trigger is a conversation.
- Move a rule that decides whether to open a file.
- Leave a pointer stub behind.
- Reword a rule on the way out. It moves verbatim, like Phase C.
- Claim a saving that `/context` did not measure.
