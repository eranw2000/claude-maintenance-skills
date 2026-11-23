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
