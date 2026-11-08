# Report shape (REPORT.md), decisions first

Write the body to the run's folder as `$OUT/REPORT_body.md`; `scripts/assemble_report.py` adds
sections 5 and 6 and writes `$OUT/REPORT.md`, beside `RUBRIC.md` (the
rubric copy used), `LAB_ADVICE.md`, the seven `slice_*.md` reader reports, and `inventory.json`.
Plain words, bullets, no pipe tables, no em dashes.

Header: the serving model (read from the transcript), the scope with counts, how it was read.

0. **The short answer.** Three sentences: what hurts the model most, in order of damage, and
   the measured total that can go without losing a rule, guard, fact or decision.
1. **Decisions only the user can make.** Numbered D1..Dn, one paragraph each: the finding, two or
   three options, the recommended one first with its reason. Anything that retires or loosens
   a gate, changes a public pack, or contradicts a recorded decision goes here, never in a
   fix list.
2. **Fix without asking: wrong or dead text.** The readers' WRONG-TEXT findings: stale facts,
   dead references, contradictions with current rules. File and line per item. These mislead the model today, so they rank
   first among the fixes.
3. **Fix without asking: text written for a weaker model.** The pasted sentence and its
   count, rules stated N times, rhetoric, how-to-code coaching, prompt inflation, gates a
   strong model does not need.
4. **Fix without asking: size and duplication.** Files over the size line and what a
   compaction drops; blocks shared verbatim; stories inside rules; templates in bodies;
   descriptions over the caps (by the YAML measurement only).
5. **What the labs recommend.** In the body this section is only the line `<!-- LAB SECTION -->`; the
   script writes it from `LAB_ADVICE.md` and your `outcomes.json`. Every item of `LAB_ADVICE.md`. Each starts its own line with its
   number, then carries its quote word for word, its link and one outcome: FOLLOWED, DIFFERS (file and line, and the change), ADD (what the harness lacks),
   or NOT FOR US (why, such as written for API apps). A difference that touches a gate or one of
   the user's stated preferences also goes in section 1 as a decision.
6. **Per-file verdicts.** In the body: the heading `## 6. Per-file verdicts`, then the line
   `<!-- VERDICTS -->`. The script writes KEEP / TRIM / REWRITE / RETIRE, grouped by verdict.
7. **What this review did NOT cover.** Folders skipped (`inventory.py`'s "not measured" line), lab pages not read (`lab.txt`'s NOT READ and OTHER HOST lines, and each page `LAB_ADVICE.md` marks `not read:`), claims not re-verified, model pins
   judged against the routing the setup states.
8. **Suggested order if the user says go.**

Then a short summary in the chat: what was done, where the report is, and what the user decides next.
