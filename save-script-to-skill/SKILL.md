---
name: save-script-to-skill
description: "Turn a script Claude wrote during a skill run into a permanent tool of that skill. Finds the skill last invoked in the session and the script written or run after it (from the session transcript, so a summarized conversation cannot hide it), makes it reusable (arguments instead of hard-coded session values, no secrets, clear exit codes), saves it in the skill's scripts folder, runs it once, and rewrites the skill's SKILL.md so future runs execute the file instead of writing it again. Use when the user says 'save the script you just created into the skill', 'add this script as a tool to the skill', 'make the skill use this script next time', 'stop rewriting this script', 'bundle this script with the skill', or '/save-script-to-skill'."
model: opus
argument-hint: "[skill-name] [script path or number]"
---

# save-script-to-skill

A skill ran. To finish the job, Claude wrote a script and ran it. Next time the skill runs,
Claude would write that script again from scratch. This skill stops that: the script moves
into `<skill dir>/scripts/`, and the skill's `SKILL.md` says to RUN it.

The end state looks like this: a skill folder with a `scripts/` subfolder holding a helper
that began as an ad hoc script written during a session, and a `SKILL.md` that runs it.

## Arguments

Both optional. `$1` is the skill name (default: the skill invoked last in this session).
`$2` is the script, as a path or as the number the finder prints (default: ask, unless there
is exactly one clear candidate).

## Steps

### 1. Find the skill and the script

Run the finder. It reads the session transcript, not your memory of the conversation:

```bash
python3 ~/.claude/skills/save-script-to-skill/scripts/find_session_scripts.py [--skill NAME]
```

It prints the skill, its directory, and every script written (Write/Edit of a `.py`, `.sh`,
`.js` ...) or run inline (heredoc, `python3 -c`) after that skill was invoked, with how many
times each ran and how many runs failed. `--show N` prints candidate N in full; `--json` for
all fields. Exit 3 means no skill was invoked in this session: ask the user which skill they mean
and pass `--skill`. If the transcript is not found (exit 2), pass `--cwd <launch dir>` or
`--transcript <path>`.

Pick the script:
- **Skip the project's own code.** A file that is part of the repo being worked on (a module,
  a test, anything tracked by that repo's git) is the WORK, not a helper. The helper is the
  one that did the skill's job: usually in a scratch or job `tmp/` folder, or an inline heredoc.
- Prefer the LAST version that ran without failing.
- If more than one real candidate is left, ask the user with `AskUserQuestion`, one line each.

Stop and say why if:
- the skill directory is a plugin skill (`name:with-colon`) or has no `SKILL.md` you can edit;
- the script is a one-off tied to this session's data (it only makes sense for one file,
  one customer, one date). Say so and ask whether the user still wants it.

### 2. Read both files fully

Read the whole script and the whole `SKILL.md`. Find the step in `SKILL.md` where the script's
work happens. That step is what you will rewrite.

### 3. Make the script reusable

Edit a copy, not the session's original. Change only what reuse needs:
- **Hard-coded session values become arguments** (`argparse` for Python): input and output
  paths, IDs, dates, project names, URLs. Keep sensible defaults only where every future run
  would use the same value.
- **No secrets and no personal data in the file.** Read credentials from where they already
  live (env var, config file), never paste them in.
- **Clear results**: exit 0 on success, non-zero on failure, errors to stderr. Never catch an
  error and carry on silently.
- A top docstring or comment: what it does, usage line, exit codes.
- Paths inside the skill are written as `~/.claude/skills/<skill>/scripts/<file>` (or relative
  to the skill dir), never `/Users/<name>/...`.
- Name the file by what it does (`build_report.py`, not `tmp_script.py`).
- Do not add features, options or refactors the session did not need.

### 4. Save it

- `mkdir -p <skill dir>/scripts`, write `<skill dir>/scripts/<name>`, `chmod +x` it.
- **A file of that name already exists:** read it and diff. Same job: update it in place and
  keep what the old one did that the new one lacks. Different job: pick another name. Never
  overwrite without looking.
- The skill may already have a script for part of this job. Then extend that script rather
  than adding a second one that does almost the same thing.

### 5. Run it once

One sanity run, part of the job:
- `--help` (or equivalent) works;
- a real run on the SAME input the session used, and compare its output to what the session
  produced. Same result: good. Different: fix the script, re-run.
- If a real run would cause a side effect (sends mail, writes to a live service, costs money),
  do NOT run it for real. Run `--help` plus a dry run if one exists, and say plainly that the
  real path was not exercised.

### 6. Rewrite SKILL.md

Change the step found in step 2 so it says to RUN the file. Use targeted `Edit` calls
(grep a short fragment for the anchor first). The new text must say:

- the exact command, with the arguments explained:
  `python3 ~/.claude/skills/<skill>/scripts/<name>.py --in <file> --out <file>`
- **"Run this script. Do not write a new one for this step."**
- **"If it fails or lacks something, fix or extend this script, then run it again."** This
  keeps the next improvement in the file instead of in a throwaway copy.

Remove the old instructions that told Claude how to write that code, since the script now
owns them. Also add or update a short `## Scripts` section near the top: one line per script,
what it does.

If you touched the frontmatter, validate it:

```bash
PYTHONPATH=<skill-creator dir> python3 -m scripts.quick_validate <skill dir>
```
(`model`, `argument-hint` and `disable-model-invocation` are reported as unexpected keys; that
is fine, strip them from a temp copy to see real errors.)

### 7. Commit and report

- If the skill lives in a git repo (`~/.claude` or a project repo), stage ONLY the script and
  the `SKILL.md` by explicit path, commit, and push per that repo's rules. Leave
  other sessions' changes alone.
- If the skill also ships in a public pack (check the public repos you maintain), say
  that the pack copy now differs and a sync is owed. Do not sync it unasked.
- Report: script path, what changed in `SKILL.md`, the sanity-run result, and the commit.
