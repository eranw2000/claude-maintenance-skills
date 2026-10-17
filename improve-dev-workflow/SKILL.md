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
  plan file needed, but step 5's rule applies here too: a check runs, or RULE-ONLY with its reason.
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

Done when every incident has its three parts with quoted evidence and each lens has its line.

## 2. Diagnose: root-cause to a workflow gap

For each incident, name the gap in the PROCESS: "nothing checks X", "the hook cannot see Y
(Bash heredoc writes bypass PostToolUse Edit/Write)", "the checklist says read, not execute",
"the rule exists but only in one project's CLAUDE.md". A diagnosis that blames attention
("I should have noticed") is not done: attention failures need structural nets.

**Then CLASSIFY each incident's cause, before designing any fix.** Review
what went wrong during this run and name which of four causes it was. Each one is fixed in a
different kind of artifact, so the wrong class produces a fix that changes nothing.

- **Process.** The right information was available, but no step asked for it at that
  moment: a step was missing, in the wrong order, or a route skipped it. Update the skill,
  command or agent that owns the flow: add, move or re-point the step.
- **Missing context.** The fact or rule existed, but it never reached the session when it was
  needed: wrong file, not loaded at that point, memory not recalled, no pointer from the
  artifact that was running. Move or point the context to where it loads at that moment (a
  pointer in the running skill, a path-scoped rule, a hook that injects it). Do NOT write a
  new rule: one already exists.
  This covers access too: a fact in a system the session could not read needs a read route.
- **Weak rule.** The rule was read and followed, and its wording still allowed the wrong
  outcome: vague, a hole, an exception too wide, or not checkable. Rewrite it at its ONE
  owner so the failure is excluded and checkable.
- **Unreliable code.** A hook, script or tool gave a wrong answer, failed silently, or could
  not fire. Fix the code test-first: a failing test that reproduces it, the fix, then a
  mutation proof.

Tell them apart with three questions, in order. Was the right information in front of the
session at that moment? No: **missing context**. Yes, but no step made the session use it:
**process**. Yes, and the session did what it said: **weak rule**. Any answer that came from
a tool that was wrong: **unreliable code**. An incident can have two causes; name the primary
one, fix it, and record the second.
Before calling anything unreliable code, prove the tool failed: show the control should
have made it fire. A wrong control looks exactly like a broken hook.

Write the class next to each incident in the record (step 5), so the next improvement can count
repeats by cause as well as by incident.

Done when every incident has one primary cause class and the artifact that class points at.

**Fix it in the SMALLEST DURABLE PLACE.** Smallest: the one artifact that
was running when the miss happened, at the narrowest scope that still covers it. A step in
the skill that was running beats a global rule, a sentence in an existing section beats a new
section, and an existing owner beats a new file. Durable: it loads or runs by itself every
time that moment comes again. A memory note that has to be recalled, or a line in a file the
running artifact never reads, is not durable. When the smallest place and a durable place
differ, durable wins.

**Tiebreaker: context pressure.** The implementer carries the most, the
reviewer the least (it gets a diff). A judgement rule checkable from a diff goes on the
reviewer's checklist (code-reviewer, the review-round brief); a step that must happen
before review stays in the running skill; a mechanical check goes in a hook or a test.

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

- **Decisions are the user's, asked early** (AskUserQuestion, in parallel with any running
  agents): scope, enforcement depth (deterministic hooks vs agent checklists vs both;
  default to BOTH, the guard+net pattern), new artifact vs extending an existing one.
  Hand the user the whole inventory first, worst first by what each miss cost and how often.
- **Artifact-type selection:** auto-trigger on a tool event = hook; isolated one-shot
  judgment report = agent; interactive multi-step workflow = skill; a behavior rule =
  CLAUDE.md (a pointer to a separate file when the detail is large); an observational fact
  = memory. Every new skill, agent or command gets a `model:` choice that follows your
  model-routing rule, recorded in the same change.
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
- **An improvement is done only when each fix has a CHECK THAT RUNS, or is recorded as RULE-ONLY
  with its reason.** Each incident's fix adds at least one thing that runs by itself and
  goes red on this miss: a hook, a test, or a replay case (the original incident run
  through `claude -p`, its answer judged by a script). Words alone do not count: a
  CLAUDE.md line, a skill sentence or a memory is a fix that has to be remembered, and
  misses that recur are usually the ones fixed only in words. A weak-rule or process miss is
  usually a replay case: replay the original incident through `claude -p` and judge the
  answer by script, and read a FAIL's answer before
  trusting the judge. **Only when nothing runnable can catch it** (no past input to replay,
  and the miss is a judgment no script can score) is the fix **RULE-ONLY**: say so in the
  record with the reason. That is the ONE way a words-only fix finishes, and it is counted as a
  fix that cannot fire rather than a guard. The reason names why no input can be replayed or
  scored; "a rule is enough" or "no time" is not a reason, and the improvement stays open.
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
