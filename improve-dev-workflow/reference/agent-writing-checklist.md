# Writing for agents: the checklist for lines a workflow improvement adds

Read this when a fix edits a skill, a rule, an agent, a command or a CLAUDE.md, and apply it
to the lines you ADD. It judges text written for an agent, which the global writing rules
(prose for people) do not cover. Based on the ideas in Matt Pocock's `writing-for-agents`
skill (https://github.com/mattpocock/skills, MIT), rewritten in my own words.

## Before writing

1. **Smallest durable place first** (the rule in SKILL.md step 2). Then this checklist shapes
   the words, not the destination.
2. **Measure the destination.** A SKILL.md stays under about 16,000 chars, and its
   steps sit inside the first 5,000 tokens, because a compaction
   re-attaches only that much of an invoked skill. A rule file that is always loaded costs
   its length on every call. Over the line, move evidence out before adding a sentence.

## The lines you add

3. **Lead with the trigger word.** In a description or a pointer, the word that decides
   whether the agent reaches the material goes first. One trigger per branch; two synonyms for
   one branch are one branch written twice.
4. **A leading word over a triad.** One word the model already thinks with (`red`, `tight`,
   `guardrail`, `lens`) does the work of "fast, deterministic, low-overhead". Coin a word only
   with a definition next to it.
5. **The target behaviour over a ban.** "Write one-line comments" steers; "do not write long
   comments" names the thing you want absent and makes it more available. Keep a ban only as a
   hard guardrail, and pair it with the positive target.
6. **A completion criterion on every step.** "Done when every modified model is accounted
   for" tells the agent what done is and how much digging it owes. A fuzzy bound ("understanding
   reached") invites ending the step early because the next step is in view.
7. **No no-ops.** A sentence the model already obeys by default pays its tokens to say nothing.
   The test is behaviour against the default, settled by running the document (an eval case),
   not by reading it. A sentence that fails is deleted whole, not trimmed.
8. **One source of truth.** Say a thing once, where its owner is, and point at it from
   elsewhere. The environment is a source too (a config file, `--help`, the repository), so a
   document that restates it is a cache that goes stale; cache only what the agent cannot look
   up (the unwritten convention, the reason, the gotcha).

## Where the lines go

9. **Steps in the file, reference on demand, evidence behind a pointer.** What the agent does
   in order stays in the file. Definitions and rules it consults stay in the file under one
   heading each. Dated incidents, measurements and worked examples go to a `reference/` file
   with a pointer in the step they belong to, in the exact pointer format the driver already
   uses, so the split tooling can expand it.
10. **Co-locate.** A concept's definition, its rules and its caveats sit under one heading. A
    meaning scattered over three sections reads as three half-meanings.
11. **Sharpen the pointer before inlining.** A must-read behind a weakly worded pointer is a
    variance bug: the agent reaches it on some runs and not others. Reword the pointer (what it
    is, when to reach it) first; inline only when that fails.

## Check, once

Re-read only the added lines. For each ban, ask whether it can be stated as the target. For
each step, find its "done when". For each dated sentence, ask whether it belongs in
`reference/`. Measure the file again and record the number in the commit message.
