---
name: improve-dev-workflow
description: "Continuous-improvement loop for the development process itself, for when the workflow underperforms (a reviewer caught what authoring should have prevented, a test passed while the bug shipped, a hook or rule missed, the same mistake recurred), run the Observe, Diagnose, Verify, Learn, Improve loop and turn the failure into durable upgrades of the harness artifacts (skills, hooks, agents, commands, CLAUDE.md rules, memory), each with a check that goes red on the miss. Use when the user says 'learn from this', 'make sure this never happens again', 'improve our workflow', 'improve the development workflow', 'why did this slip through', or when a session surfaces repeated development-process failures worth institutionalizing. Not for fixing a single project bug (normal fix + review), not for stress-testing an idea (grill-me), not for reviewing one PR (pr-checkpoint / the review agents)."
model: inherit
---

# Improve the development workflow (the continuous-improvement loop)

The subject of this skill is the PROCESS, not the product. A project bug gets fixed in the
project; this skill fires when the process that was supposed to prevent the bug did not:
the authoring habits, the review agents, the hooks, the skills, the CLAUDE.md rules. Its
output is upgraded harness artifacts plus a durable record, so the same failure class
cannot recur silently.

The loop: **Observe -> Diagnose -> Verify -> Learn -> Improve**. Each step ends on a
"Done when" line; do not start the next step before it holds.

## Step 0: weigh it

Not every hiccup deserves the full loop.

- **LIGHT (single incident, single artifact):** one lesson, one obvious home. Do Observe and
  Diagnose inline, fix the one artifact directly, add the Verify step for that artifact only,
  and record (memory, or the project CLAUDE.md as a 1-instance candidate). No
  plan file needed, but step 5's rule applies here too: a check runs, or RULE-ONLY with its reason (read `~/.claude/skills/improve-dev-workflow/reference/5-check-that-runs.md`).
- **FULL (repeated failures, cross-cutting, or the fix spans artifacts):** the whole loop
  below, ending in a plan file + plan-gate before implementation.
- **Promotion rule:** the FIRST occurrence of a failure mode is a recorded candidate; the
  SECOND promotes it to a guardrail. Check the project CLAUDE.md and memory for prior
  instances before deciding the weight.

## 1. Observe: build the failure inventory

One numbered entry per incident, each with: the INCIDENT (what happened, verbatim evidence),
the MECHANISM (why it happened, technically), and WHERE A GUARDRAIL COULD HAVE CAUGHT IT
EARLIER. Rules:

- Read the session transcript FIRST: this session's own `.jsonl`, found the way
  `save-context` step 1 finds it, never the newest file on the machine. Default to the
  current session. After a compaction it is the only full record of what happened.

- Evidence is executed or measured, never remembered. Quote the failing output, the wrong
  count, the log line. "The suite stayed 28/28 when it should have read 30" is evidence;
  "the tests seemed not to run" is not.
- Include what WORKED too (the practices that caught the failures), because codifying a
  proven practice is as valuable as patching a gap.
- Keep incidents atomic: one mechanism per entry, so each maps to a specific guardrail.
- Then look through four lenses, one line each even when empty:
  - **Navigation**, when time went on finding a file, fact or dependency: a pointer in
    the running artifact.
  - **Existing checks**, before building any: list what already runs (CI, pre-commit,
    `run_tests.py`, hooks). One that is unwired or silently broken is the finding.
  - **Tool economy**, when a call cost many tokens or minutes: name the cheaper path.
  - **Information access**, when the answer sat in a log or service the session could
    not reach: the fix is a way to read it.
- **Efficiency pass**, when the user asks where a session wasted effort (`/improve-dev-workflow
  efficiency`) and on every FULL run; a LIGHT run skips it. It counts the session, checks
  twelve waste patterns against the work rules require, and ends on a top three or
  `nothing worth changing`.
  **Read `~/.claude/skills/improve-dev-workflow/reference/1-efficiency-pass.md` now, in full, and follow it. It is this pass's full text; the line above is only a summary and is not enough to act on.**

Done when every incident has its three parts with quoted evidence and each lens has its line.

## 2. Diagnose: root-cause to a workflow gap

For each incident, name the gap in the PROCESS: "nothing checks X", "the hook cannot see Y
(Bash heredoc writes bypass PostToolUse Edit/Write)", "the checklist says read, not execute",
"the rule exists but only in one project's CLAUDE.md". A diagnosis that blames attention
("I should have noticed") is not done: attention failures need structural nets.

Classify each incident's cause (process, missing context, weak rule, unreliable code) before designing any fix, then fix it in the smallest durable place.

**Read `~/.claude/skills/improve-dev-workflow/reference/2-classify-and-place.md` now, in full, and follow it. It is this step's full text; the line above is only a summary and is not enough to act on.**

**Then return to the same task and verify the fix.** Re-run the original task, from the same
entry point with the same input, and confirm the miss no longer happens. This is the
acceptance test in step 5, and it is the step that proves the fix, so it is not optional.

## 3. Verify: audit the current artifacts before proposing anything

Never propose against an assumed state of the harness. Two mandatory checks:

- **Coverage audit:** spawn Explore agents with POINTED coverage questions per artifact
  ("does pr-validator verify test-count deltas? quote the line or say NOT COVERED"), and
  demand file:line answers. A vague audit finds "partial coverage" everywhere and
  justifies nothing.
- **Measured, not assumed:** any proposed signal, threshold, filter, or heuristic gets
  measured against real history before it enters the design. State each design claim
  as measured or assumed; assumed claims are flagged for plan-gate.

Done when every coverage question has a file:line answer or NOT COVERED.

## 4. Learn: sweep the institutional context

Before designing, sweep for prior lessons and open wishes so the improvement builds on what
exists instead of duplicating or contradicting it:

- Project TODOs (all of `~/.claude/projects/*/TODO.md`) for open workflow items and recorded
  wishes ("should also check", "does not catch", "false positive").
- The global CLAUDE.md and the files it points to, and each relevant project CLAUDE.md
  (recorded patterns and their counts live there).
- Memory (`memory/` dirs + MEMORY.md indexes): feedback and reference entries often carry
  the exact gotcha (hook schemas, shell traps, tool-selection heuristics).

Done when each proposed fix names what it builds on, and links any open TODO it fulfils.

## 5. Improve: decide, design, gate, implement, prove

- **Decisions are asked early, and the trigger picks the artifact type:** hand over the whole inventory first, then ask scope, enforcement depth, and new artifact or existing one.

**Read `~/.claude/skills/improve-dev-workflow/reference/5-decisions-and-artifact-type.md` now, in full, and follow it. It is this step's full text; the line above is only a summary and is not enough to act on.**
- **Writing for agents:** when a fix edits a skill, rule, agent, command or CLAUDE.md,
  read `~/.claude/skills/improve-dev-workflow/reference/agent-writing-checklist.md` and apply it to the added lines.
- **FULL path:** write the plan file (failure inventory, audit findings, decisions, file-by-file
  design, verification, follow-ups, named accepted risks), then plan-gate it. LIGHT path:
  fix directly, but the Verify rules below still apply.
- **Binding conventions for the implementation:** the hook output schema,
  config-repo visibility read from an exit code, mutation-tested guards with contrast
  assertions, population guards fed by the consumer's own enumerator, regression replay
  for edited agents, and re-enacting the original incident against the ORIGINAL artifact.
  **Read `~/.claude/skills/improve-dev-workflow/reference/5-binding-conventions.md` now, in full, and follow it. It is this step's full text; the line above is only a summary and is not enough to act on.**
- **An improvement is done only when each fix has a CHECK THAT RUNS and goes red on this miss.** Words alone do not count. RULE-ONLY, with its reason, is allowed only when nothing runnable can catch the miss; "a rule is enough" or "no time" is not a reason.

**Read `~/.claude/skills/improve-dev-workflow/reference/5-check-that-runs.md` now, in full, and follow it. It is this step's full text; the line above is only a summary and is not enough to act on.**
- **Record:** write each incident with its cause class from step 2 (process, missing context,
  weak rule, unreliable code) and its `Check:` line (the hook, test file or eval case id that
  now goes red on the miss, or `RULE-ONLY: <why>`), then update the relevant CLAUDE.md,
  memory, and the TODO (follow-ups such as copying the change to a second repo). The
  failure inventory itself goes in the
  plan file or the project CLAUDE.md entry, so the next loop turn can count instances.

## Don't use this skill for

- A product/project bug whose process worked (the reviewer caught it, the test failed as it
  should): fix it normally and move on.
- Stress-testing an idea or unbuilt plan: grill-me / plan-gate.
- Reviewing one branch or PR: pr-checkpoint and the review agents.
- Pure recording with no fix intended: save-context / the todo skill.
- Comparing one of your skills with somebody else's: compare-skills.
