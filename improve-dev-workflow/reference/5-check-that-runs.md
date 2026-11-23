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
