---
name: improve-dev-workflow
description: "Continuous-improvement loop for the development process itself, for when the workflow underperforms (a reviewer caught what authoring should have prevented, a test passed while the bug shipped, a hook or rule missed, the same mistake recurred), run the Observe, Diagnose, Verify, Learn, Improve, Publish loop and turn the failure into durable upgrades of the harness artifacts, meaning skills, hooks, agents, commands, CLAUDE.md rules and satellites, memory. Use when the user says 'learn from this', 'make sure this never happens again', 'improve our workflow', 'harness retro', 'why did this slip through', or when a session surfaces repeated development-process failures worth institutionalizing. Not for fixing a single project bug (normal fix + review), not for stress-testing an idea (grill-me), not for reviewing one PR (pr-checkpoint / the review agents)."
model: inherit
---

# Improve the development workflow (the continuous-improvement loop)

> **Model notice.** This skill is judgment-heavy: it diagnoses why a process failed
> and redesigns part of it. Run it on your strongest reasoning model. If your session
> is on a faster model, say which one is serving before starting, so the depth of the
> analysis is not mistaken for the depth of the problem.

The subject of this skill is the PROCESS, not the product. A project bug gets fixed in the
project; this skill fires when the process that was supposed to prevent the bug did not:
the authoring habits, the review agents, the hooks, the skills, the CLAUDE.md rules. Its
output is upgraded harness artifacts plus a durable record, so the same failure class
cannot recur silently.

The loop: **Observe -> Diagnose -> Verify -> Learn -> Improve**. Each turn ends with the
improvement actually applied to the artifact that should have caught the failure, and with
a record of it where the next session will read it.

Worked example of one full turn of this loop, with every phase's artifacts:
`~/.claude/plans/it-looks-like-you-linear-galaxy.md` (2026-07-17: four vacuous-test shapes,
over-claimed docs, stale comments, and more, turned into a hook + four agent upgrades + a
review-round skill + a rules satellite). Read it when unsure what a phase's output looks like.

## Step 0: weigh it

Not every hiccup deserves the full loop.

- **LIGHT (single incident, single artifact):** one lesson, one obvious home. Do Observe and
  Diagnose inline, fix the one artifact directly, add the Verify step for that artifact only,
  and record (memory or the project's Known Patterns section as a 1-instance candidate). No
  plan file needed.
- **FULL (repeated failures, cross-cutting, or the fix spans artifacts):** the whole loop
  below, ending in a plan file + plan-gate before implementation.
- **Promotion rule** (the Known Patterns convention): the FIRST occurrence of a failure mode
  is a recorded candidate; the SECOND promotes it to a guardrail. Check the project CLAUDE.md
  Known Patterns section and memory for prior instances before deciding the weight.

## 1. Observe: build the failure inventory

One numbered entry per incident, each with: the INCIDENT (what happened, verbatim evidence),
the MECHANISM (why it happened, technically), and WHERE A GUARDRAIL COULD HAVE CAUGHT IT
EARLIER. Rules:

- Evidence is executed or measured, never remembered. Quote the failing output, the wrong
  count, the log line. "The suite stayed 28/28 when it should have read 30" is evidence;
  "the tests seemed not to run" is not.
- Include what WORKED too (the practices that caught the failures), because codifying a
  proven practice is as valuable as patching a gap.
- Keep incidents atomic: one mechanism per entry, so each maps to a specific guardrail.

## 2. Diagnose: root-cause to a workflow gap

For each incident, name the gap in the PROCESS: "nothing checks X", "the hook cannot see Y
(Bash heredoc writes bypass PostToolUse Edit/Write)", "the checklist says read, not execute",
"the rule exists but only in one project's CLAUDE.md". A diagnosis that blames attention
("I should have noticed") is not done: attention failures need structural nets.

## 3. Verify: audit the current artifacts before proposing anything

Never propose against an assumed state of the harness. Two mandatory checks:

- **Coverage audit:** spawn Explore agents with POINTED coverage questions per artifact
  ("does pr-validator verify test-count deltas? quote the line or say NOT COVERED"), and
  demand file:line answers. The 2026-07-17 audit found all eight coverage questions NOT
  COVERED, which is what justified the scope; a vaguer audit would have found "partial
  coverage" everywhere and justified nothing.
- **Measured, not assumed:** any proposed signal, threshold, filter, or heuristic gets
  measured against real history before it enters the design (the fingerprint signal was
  redesigned after measuring 35 raw gates vs 8 filtered on the real drift window). State
  each design claim as measured or assumed; assumed claims are flagged for plan-gate.

## 4. Learn: sweep the institutional context

Before designing, sweep for prior lessons and open wishes so the improvement builds on what
exists instead of duplicating or contradicting it:

- Project TODOs (all of `~/.claude/projects/*/TODO.md`) for open workflow items and recorded
  wishes ("should also check", "does not catch", "false positive").
- The global CLAUDE.md law book + its satellites, and each relevant project CLAUDE.md's
  Known Patterns section (instance counts live there).
- Memory (`memory/` dirs + MEMORY.md indexes): feedback and reference entries often carry
  the exact gotcha (hook schemas, shell traps, tool-selection heuristics).
- If public packs mirror the artifacts: `~/.claude/instructions/SKILLS_FRAMEWORK_HANDOFF.md`
  conventions (personal first, equal-or-ahead, de-personalization, allowlist visibility).

## 5. Improve: decide, design, gate, implement, prove

- **Decisions are the user's, asked early** (AskUserQuestion, in parallel with any running
  agents): scope (personal now vs public sync), enforcement depth (deterministic hooks vs
  agent checklists vs both; default to BOTH, the guard+net pattern), new artifact vs
  extending an existing one.
- **Artifact-type selection** (per the reference-claude-code-artifact-selection memory):
  auto-trigger on a tool event = hook; isolated one-shot judgment report = agent; interactive
  multi-step workflow = skill; a behavior rule = CLAUDE.md (pointer-pattern a satellite when
  the detail is large); an observational fact = memory. Every new skill/agent/command gets a
  `model:` pin per `~/.claude/instructions/three-tier_models_routing.md`, AND that map plus
  the global CLAUDE.md routing paragraph get updated in the same change.
- **FULL path:** write the plan file (failure inventory, audit findings, decisions, file-by-file
  design, verification, follow-ups, named accepted risks), then plan-gate it. LIGHT path:
  fix directly, but the Verify rules below still apply.
- **Binding conventions for the implementation, all hard-won:**
  - Hooks: `hookSpecificOutput` needs `hookEventName` or it is silently dropped; blocking
    needs exit 2 + stderr, not `decision:block`; hooks fail OPEN, and settings.json edits do
    not rewire the running session, so live-fire proof happens in a FRESH session.
  - Config-repo visibility: `~/.claude/.gitignore` is an allowlist; `git check-ignore` every
    new path or the Sync commit silently misses it. **Read its EXIT CODE, not its
    output**: `check-ignore -v` prints the matching `.gitignore` line whether that
    line ignores or UN-ignores, so an allowlisted path prints `!/NAME.md` and a
    naive "any output means ignored" test reads the proof of inclusion as proof of
    exclusion (measured 2026-08-12, on the two satellites the CLAUDE.md shrink
    created). The unambiguous check is `git add --dry-run <path>`, paired with a
    control path that must still be refused.
  - Every new gate/guard is MUTATION-TESTED (break it, exactly the intended check fails);
    every negative test carries a CONTRAST assertion.
  - Edited judgment agents get a REGRESSION REPLAY against a past known catch, so an edit
    cannot silently dilute the checklist that reviews everything else.
  - The acceptance test for the whole loop: RE-ENACT the original incident against the new
    guardrail and watch it fire. If the incident cannot be re-enacted, say so explicitly.
    **Replay the ORIGINAL artifact, never a tidied-up fixture of it.** A guardrail that passes
    its own tests has not been shown to catch anything. Measured 2026-08-04: a new
    mutation-target pattern passed every unit assertion written for it, then found ZERO hits
    when replayed against the actual incident diff, because the fixture was a one-line condition
    while the real code wrapped the assignment and its operands onto separate lines, which a
    line-by-line diff scanner reads as two unrelated lines. Green tests, inert guardrail. In the
    same session the follow-up fix carried its own vacuous contrast: the negative fixture was one
    the pattern rejected anyway, so weakening the pattern left it green. So mutation-test the
    guardrail itself, assert the kill lands on the INTENDED assertion rather than collateral, and
    make every negative fixture one the check would otherwise match.
- **Record:** update the relevant CLAUDE.md/Known Patterns instance counts, memory, and the
  TODO (follow-ups such as the public-pack sync). The failure inventory itself goes in the
  plan file or the project CLAUDE.md entry, so the next loop turn can count instances.

## Don't use this skill for

- A product/project bug whose process worked (the reviewer caught it, the test failed as it
  should): fix it normally and move on.
- Stress-testing an idea or unbuilt plan: grill-me / plan-gate.
- Reviewing one branch or PR: pr-checkpoint and the review agents (or the review-round skill
  once it ships).
- Pure recording with no fix intended: save-context / the todo skill.
