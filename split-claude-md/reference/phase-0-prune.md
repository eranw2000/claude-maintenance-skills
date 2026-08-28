## Phase 0 - Prune what the repository already answers

Skip this phase if `--no-prune` was passed.

Phases A, B, C and D all MOVE text. None of them deletes any. That is a real gap:
content the repository itself answers should not be archived, extracted, or given
a satellite. Moving it pays the write, keeps a file nobody should read, and leaves
a pointer that sends a future session to a worse source than the code.

Phase 0 runs FIRST, before Phase A, so every later phase operates on a smaller
set. A deleted section is not surveyed, not classified, not moved, and not
verified. It is the cheapest character in the file.

**This is the phase Claude Code now does for you in miniature.** `/doctor`
proposes trims for a checked-in CLAUDE.md: it cuts content derivable from the
codebase, such as directory layouts, dependency lists and architecture overviews,
and keeps pitfalls, rationale and conventions that differ from tool defaults.
Auto memory applies the same rule from the other side, skipping anything it can
derive from the code. Run `/doctor` on a checked-in file and read its proposal
before doing this by hand; it is evidence, not a verdict.

### 0.1 The test, and it is one question

**Could a session answer this by reading the repository, in one command it would
plausibly run anyway?**

Yes means DELETE. Not archive, not extract. Delete, and leave nothing behind, on
the grounds that the repository is a better source than a stale copy of it.

No means keep it and let the later phases decide where it goes.

The question is about the REPOSITORY, not about your memory of it. Run the
command. A section that describes a directory layout is derivable only if the
directory still looks like that.

### 0.2 What is derivable, with the command that settles each one

- **Directory or file layout.** `ls`, `find`, `tree`. Derivable unless the
  section explains WHY a file sits where it does.
- **Dependency lists, versions, the tech stack.** `cat requirements.txt`,
  `package.json`, `pyproject.toml`, the Dockerfile `FROM` line. Derivable unless
  the section records a PIN and its reason, which is a pitfall and stays.
- **Function, class, endpoint or model inventories.** `grep -rn "^def \|^class "`,
  the urls file, the router. Derivable unless the list carries an ordering or a
  contract the code does not state.
- **Command lists a script already holds.** If `make test` exists, the section
  restating what it runs is derivable.
- **An architecture overview that names modules and what they do.** Derivable
  from the module names and their docstrings, unless it records a decision that
  the structure does not reveal.
- **Env-var lists.** Derivable from `.env.example` or the settings module, unless
  the section records which are secret, which are retired, or what a missing one
  does.

### 0.3 What SURVIVES the test, always

Delete nothing in these classes, however derivable it looks:

- **A pitfall.** What broke, and what to do instead. The code shows the fix; it
  does not show that the fix was needed.
- **A rationale.** Why this and not the obvious alternative. Never derivable.
- **A convention that differs from the tool's default.** The gap is the content.
- **A measured figure.** The number cost a run to obtain, and re-deriving it
  costs the same run again.
- **A pointer to something OUTSIDE the repo.** A service id, a dashboard, a
  ticket. The repo cannot answer it by definition.
- **Anything carrying obligations.** A section full of paths that also says
  "must", "never" or "always" is a pitfall wearing a file map's clothes, and it
  is the one deletion that would really hurt. `survey.py` excludes these by
  measuring obligation and imperative density directly, and the phase excludes
  them by rule.

### 0.4 Fail closed, and this is not optional

**A section is kept unless it is PROVEN derivable.** The harmful direction is
deleting a pitfall dressed as a layout. The harmless direction is keeping a
directory tree for one more cycle.

So Phase 0 always asks a human before it deletes anything. For each candidate: state the section, state
the command whose output would replace it, RUN that command, show the output
beside the section, and ask. A candidate whose command returns nothing, errors,
or returns something that does not match the section is NOT derivable. It is
either stale, which is a correction, or it describes something the repo no
longer holds, which is a finding.

That last case is the phase's second payoff. A section the repo contradicts is
worse than a section the repo duplicates, and only running the command finds it.

### 0.5 What the surveyor gives you

`survey.py` prints a `PHASE 0 PRUNE CANDIDATES` block: sections whose bodies are
dominated by path-like tokens, directory-tree fences, or dependency-pin lines
AND whose obligation and imperative density is near zero. Both numbers print
beside each candidate as the evidence that qualified it.

**It deliberately does NOT use the REFERENCE / RULE classifier that Phases C and
D use.** That classifier proves reference-ness from structure, meaning tables and
key-value rows, and calls everything else a rule. That is correct for Phases C
and D, and it makes Phase 0 blind: a plain directory listing has no tables, so it
classifies as a rule, and the one phase built to delete file maps would never see
a file map. Measured 2026-08-24, on a six-line file map that any reader would
call reference. What Phase 0 needs is the ABSENCE of obligations, not the
presence of a table, so it tests that directly.

It proposes. It cannot run the command that settles the question, and it cannot
read a rationale hidden inside a file map. Treat the block as a shortlist.

### 0.6 Verify Phase 0

- Every deletion has a named command and that command's recorded output.
- Every deleted section was REFERENCE-shaped per `survey.py`, or the report says
  why the classifier was overruled and who overruled it.
- The chars deleted, reported separately from every later phase, since this is
  the only phase whose saving is permanent rather than relocated.
- A one-line note in the run report for each section the repo CONTRADICTED, so
  the correction does not vanish with the deletion.

### Phase 0 does NOT

- Delete a RULE-shaped section. Ever. That is Phase D or Phase E.
- Delete without running the replacement command first.
- Delete a section merely because it is old, large, or dull.
- Delete a measured figure, a rationale, a pitfall, or an external pointer.
