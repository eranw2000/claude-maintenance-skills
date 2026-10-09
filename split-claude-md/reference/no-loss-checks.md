## No-loss checks: the dry-run report, the loss check and the pointer check

These checks replace the hand-typed must-survive list. A heading check passes on
a stub whose rule was gutted; these checks read every rule sentence, heading,
path, identifier and command of the file before the edit and say where each one
went. Every script here exits 0 when the check holds, 3 on a finding and 2 when
it cannot tell. Do not start the next phase, and do not end the run, on a 3 or a 2.

`<skill-dir>` is this skill's folder. `<session folder>` is the run folder the
session makes itself (below).

### Scope

The open-work refusal, the rules refusal, the manifest and `--undo` cover
`rotate.py` runs only. A Phase A run done by hand (the bullet convention, which
`rotate.py` does not take) and Phases B to E get the manual calls in the last two
sections of this file.

### Before the first file: keep the run folder out of git

Before the run creates its first file (the first backup, the session's `mkdir`
of the run folder, or the first `rotate.py` dry run, which writes
`split_<date>/REPORT.dry.md` by itself), run SKILL.md's "check that git will not
ship it" loop with the run folder included. Test names of files INSIDE it,
`split_<date>/REPORT.dry.md` and `split_<date>.undone/REPORT.md`, never the bare
folder name: a directory pattern cannot match a path that does not exist yet, so
the bare name stays TRACKABLE after the fix. On a TRACKABLE line the
`.git/info/exclude` entry is the folder pattern `split_20*/`, which covers every
suffix, the `.undone` rename and everything the session writes there.

### The session folder

When the run needs a hand check file (Phase 0's report and its waiver list, or a
per-phase copy for Phases B to E), the session itself makes `split_<date>/`, or
the first such name with a `-2`, `-3` suffix that does not yet exist, with
`mkdir`, before the first call that writes into it. `loss_check.py --report`
only writes the file; it makes no folder.

Those files always go in that subfolder, never as a top-level `*.md` beside
CLAUDE.md. The NOTES SET is the top-level regular `*.md` files, so a top-level
report or list would make every later check read each deleted item as held by a
notes file rather than NOWHERE. A later `rotate.py` run skips that folder to the
next suffix.

### Every run with Phase 0: first backup, then the Phase 0 loss check

1. The run's first CLAUDE.md backup is taken before Phase 0 (`phase-0-prune.md`
   step 0.0; SKILL.md's universal rule: before the first mutation).
2. Write each intended deletion as one exact item per line of
   `<session folder>/phase0_waivers.txt`. Never one broad `--accept`.
3. After Phase 0 and before the next phase starts:

   ```bash
   python3 <skill-dir>/loss_check.py --before <first backup> --after CLAUDE.md \
     --accept-file <session folder>/phase0_waivers.txt \
     --report <session folder>/LOSS_PHASE0.md
   ```

   No `--structure` here: Phase 0 deletes whole sections. Exit 0 is required
   before the next phase starts, or before the run ends when no phase follows (a
   file with no dated records skips Phase A).
4. After a `rotate.py --apply` exits 0 in a run where Phase 0 ran, append one
   line at the end of that run's REPORT.md:
   `Phase 0 loss report: <session folder>/LOSS_PHASE0.md`. REPORT.md is never a
   manifest entry, so `--undo` is unaffected.

### Phase A with rotate.py: dry run, approval, apply

A rule-holding Phase A run goes in this order:

1. The run's first backup (taken before Phase 0 when Phase 0 runs).
2. The dry run. It changes nothing and writes `split_<date>/REPORT.dry.md`:

   ```bash
   python3 <skill-dir>/rotate.py CLAUDE.md --convention <entry|section> \
     --cut-date <YYYY-MM-DD> [--keep "<title fragment>"]...
   ```

   The report lists the records that move and the ones kept (with the reason),
   the open work that names a moving record, the Rules draft, the in-memory loss
   check, the unresolved pointers, every waiver with what it let through, and the
   `FRAGMENT CHECK (predicted for --apply)` line. Each Rules draft line is a
   whole paragraph, list item, table row or heading that holds a rule word,
   written as a line you can paste.
3. Show the dry-run report to the person and get approval of the moved set and
   of every waiver before any `--apply`. Each waiver names one record or one
   item, and the report lists each one:
   - `--keep "<fragment>"` keeps a record in CLAUDE.md;
   - `--move-anyway "<title>"` moves a record that open work names;
   - `--narrative "<title>"` lets that record's rule sentences leave with it as
     story, not as rules;
   - `--accept "<text>"` lets one lost item through;
   - `--hoisted <file>` names another always-loaded CLAUDE.md that now holds a
     rule;
   - `--todo <file>` adds an open-work file; `--root <folder>` adds a folder
     that pointers resolve against.

   The approval includes the FRAGMENT CHECK line. Do not run `--apply` while
   the FRAGMENT CHECK line names a failure; stop and show the person the named
   record. A predicted failure means `--apply` will write every file and then
   exit 2 with an undo to run.
4. Hoist: paste the Rules draft lines that must stay into CLAUDE.md above the
   moving records, or into a `--hoisted` file. A draft line is a whole
   paragraph, list item, table row or heading; paste it whole, or cut its story
   sentences but keep each rule sentence whole, since the refusal checks each
   one.
5. The pre-apply loss check, once, after the hoist:
   `loss_check.py --before <first backup> --after CLAUDE.md`. Exit 0 is
   expected; an intended deletion needs `--accept`. When Phase 0 ran, pass the
   same `--accept-file`, so the check covers everything since the first backup.
6. `--apply` with the flags the person approved. Exit 0 writes REPORT.md,
   manifest.json, one Last-run line in CLAUDE.md and a Runs row in the index.
   Exit 3 is a refusal: nothing is written but REPORT.dry.md. Exit 2 is cannot
   tell; once the pending manifest exists, it prints the `--undo` command.
   A `CANNOT TELL: fence opened at line <N> never closes (<CLAUDE.md>)` line
   means CLAUDE.md holds a fence that never closes: close or fix the named
   fence in CLAUDE.md, take the backup again and rerun from the dry run. The
   same line ending `(<CLAUDE.md> after the move)` means the file on disk is
   fine and the move itself would leave that fence open: change `--cut-date`
   or `--keep` instead.
7. Undo: `rotate.py CLAUDE.md --undo <date or run folder>` first as a dry run,
   then again with `--apply`. It checks every hash first and touches no file the
   manifest does not name. `--undo` refuses once Phase B to E have edited
   CLAUDE.md, because its hash no longer matches; restore from the backups then.
   Exit 2 from `--undo --apply` comes in two kinds, told apart by its first
   line. A `CANNOT TELL` line means nothing was changed: fix the cause it names
   and run the undo again. A first line starting `***` (`RESTORE of ... did not
   verify` or `The undo stopped part way`) means it stopped part way: do each
   line it printed by hand (the copy commands, the deletes, then the `mv`), and
   do not run the undo again.

### Phases B to E: one check per phase

Before each of Phases B, C, D and E, copy CLAUDE.md to
`<session folder>/CLAUDE.md.before-<letter>` (`CLAUDE.md.before-B` and so on).
After that phase:

```bash
python3 <skill-dir>/loss_check.py --before <session folder>/CLAUDE.md.before-<letter> \
  --after CLAUDE.md --structure --edited "<heading>" [--accept "<item>"]...
python3 <skill-dir>/pointers.py CLAUDE.md
```

- `--edited` once for each section the phase changed or added.
- `--accept` only for that phase's own intended deletions. A rule Phase E moves
  to `.claude/rules/` needs one, since a rules file is not a holding file.
- Never the first backup here: earlier phases' waivers (Phase 0's list, Phase
  A's `--narrative` sentences, a bullet run's `--accept` values) are then on
  neither side. The first backup stays the revert copy.

### The recall check: last, on every run

The loss check reads the text; this check asks a fresh `claude -p` session. It runs once,
after the last loss and pointer checks of the run, on every run that changed CLAUDE.md.

1. Before `--apply` (or before the first edit of a hand run), write
   `<run folder>/QUESTIONS.md`: 6 to 10 lines of `question | expected fragment | rule|fact`,
   drawn from what is about to move or change (an identifier, a rule, a command each), with
   at least one `rule` line. Never put the fragment's words in the question, or the
   control fails it as too easy.
2. After the run:

   ```bash
   python3 <skill-dir>/recall_check.py CLAUDE.md --pack <run folder>/QUESTIONS.md \
     --manifest <run folder>/manifest.json --report <run folder>/RECALL.md
   ```

   A hand run with no manifest passes `--before <first backup>` instead of `--manifest`.
3. A `rule` question is asked with no tools, so only CLAUDE.md can answer it: a rule moved
   behind a pointer reads LOST. A `fact` question may read the notes files, so a fact behind
   a pointer reads KEPT.
4. Exit 0: nothing lost. Exit 3: show each LOST line to the person and offer the undo (the
   `--undo` dry run, or the backups for a hand run). Exit 2: say why (a REFUSED or FAILED
   line, or a pack too easy) and never re-run to make it pass. It costs real calls: 2 per
   question plus 1 per rule question, capped by `--max-calls` (30).

### A Phase A run by hand (bullet convention)

Run the same two calls with `--before <first backup>`, `--edited` for the
records' section, one `--accept` per rule sentence that leaves with its record,
and, when Phase 0 ran, the same `--accept-file`. Write the hand REPORT.md into
the session folder. When Phase 0 ran, its Waivers section carries one line
naming `LOSS_PHASE0.md`.

Then write the Last-run line into CLAUDE.md from this template:

```text
Last split run: <date>, <before> to <after> chars, <N> records moved to `CLAUDE_DECISIONS_INDEX.md`, report <run folder name>/REPORT.md
```

- `<run folder name>` is the folder the run actually wrote its REPORT.md into,
  suffix included (`split_2026-10-07-2`), never prefixed again.
- `<before>` is CLAUDE.md's character count (Python `len()`) before the run;
  `<after>` is its count without this line. Write each as `(n + 500) // 1000`
  followed by `K`.
- Placement: outside every dated record; on the line after the heading
  containing "Maintenance rule" when there is one, else on its own line followed
  by a blank line immediately before the first dated record. Delete any older
  `Last split run:` line first, so the file holds exactly one.

The backticked index name makes the line a pointer to the index, so the
archives the index names count as pointed to. Add the Runs row to the index's
`## Runs` section (make the section, with this header, just before
`## Entries (chronological)` when it is absent), with the two counts exact:

```text
| Date | Before | After | Records | Report |
| --- | --- | --- | --- | --- |
| <date> | <before chars> | <after chars> | <N> | <run folder name>/REPORT.md |
```
