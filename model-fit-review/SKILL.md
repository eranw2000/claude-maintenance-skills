---
name: model-fit-review
description: Review every skill, agent and command in ~/.claude for text written for weaker, older models that now costs a strong model (start gates that stop the run to ask, stale model names and dead tool references, the same sentence pasted dozens of times, dated war stories inside rules, files so long a compaction drops the step that matters). Measures the tree with a script, collects what Anthropic and OpenAI recommend today as checked quotes from their live pages, sends the files to seven parallel readers against one rubric, re-greps every headline claim, checks every artifact got a verdict, and writes a report with the decisions first. Recommends only, never edits. Use when a new Claude model family ships, or when the user says "review my skills for the new model", "do my agents still fit the new model", "are my rules crippling the model", "model-fit review", "re-run the harness review". Not for reviewing one skill against someone else's (compare-skills), and not for shrinking a CLAUDE.md (split-claude-md).
model: inherit
argument-hint: "[root folder, default ~/.claude] [optional: 'measure only']"
---

# Model-fit review

Question for every file: which sentences exist because an OLDER model was weak, and now cost
more (context, rigidity, blocked autonomy, wrong routing) than they buy? The answer is a report
the user reads, never an edit. The user's preferences, project facts, vendor gotchas, safety guards and
dated decisions are KEEP by definition; the rubric says so.

Say which model is serving (read `.message.model` from the newest transcript, never the system
prompt) and run; never stop to ask about the model. The readers are judgment work, so they run
on the session model.

## 1. Measure first

```bash
P=python3   # a Python with PyYAML (pip install pyyaml): inventory.py refuses without it
S=~/.claude/skills/model-fit-review/scripts
OUT="$PWD/model_fit_review_$(date +%F_%H%M%S)"   # a new folder, where you run this
mkdir -p "$(dirname "$OUT")" && mkdir "$OUT" && {
  $P "$S/docs_caps.py" --json "$OUT/caps.json" > "$OUT/docs_caps.txt"; echo "docs_caps exit $?"
  $P "$S/inventory.py" --root ~/.claude --caps "$OUT/caps.json" --json "$OUT/inventory.json" > "$OUT/inventory.txt"; echo "inventory exit $?"
}
```

Each run gets its own new folder, so a re-run can never read an earlier run's slice files. **No
exit lines printed means the folder could not be made, and an exit of 2 from either script stops
the review**: read the message and say what refused. Then read the two text files. Update `reference/stale-names.txt` first when the live default moved: a name
is stale once nothing current uses it, so a tool name still real in a third-party skill or in a
parser of tool calls stays off that list and is judged by reading.

`inventory.py` prints, per file: size, lines, description length (parsed as YAML, so comment lines
inside it do not count), pins, shouting (count and per 1,000 chars), stale names, copies of
the pasted pointer phrase, story sentences ("Measured <date>", narrow on purpose so runs compare),
dated mentions (the wider net, candidates to read), asks. Across files: anything over 16,000 chars
and the headings a compaction drops, descriptions over both caps, paragraphs shared verbatim by
two or more files, readers of every `skills/_shared/*.md` with the ones nobody reads named, and
what it did not measure (nested SKILL.md such as third-party or plugin skills, other markdown in
skill folders). Report that last line in the report's "did not cover" section.

Its flags: `--root`, `--json`, `--caps` as above, and these three defaults come from `--caps`
(given on the same command line, the flag wins): `--listing-cap`, `--keep-chars`, `--line-guide`.
The rest are for a change of question:
`--phrase` (regex of the pasted sentence to count), `--stale-names` (another list), `--size-line`
(16,000), `--validator-cap` (1,024, quick_validate's limit), `--dup-min`
(80, the shortest shared paragraph counted; the run prints it), `--control-phrase` (must appear
or the run refuses), `--quiet`.

`docs_caps.py` reads the live Claude Code skills page for the three numbers the rubric leans on
(listing cap, compaction keep, line guideline), writes them for `--caps`, and exits 2 when the
page changed. Never type those numbers from memory.

`P` and `OUT` do not carry to a new Bash call, so set them again in each command below.

Measure-only (`measure only` argument): run the fetch in step 1b as well, then stop, hand the user
`inventory.txt` and `lab.txt`, and say what changed since the last run (runs are dated folders;
diff the two `inventory.json`, and the `sha256` of each page in the two `lab/index.json`).

## 1b. What the labs recommend today

```bash
$P ~/.claude/skills/model-fit-review/scripts/lab_guidance.py fetch --sources ~/.claude/skills/model-fit-review/reference/lab-sources.txt --out "$OUT/lab" > "$OUT/lab.txt"; echo "lab fetch exit $?"
```

It starts from the two start pages in `reference/lab-sources.txt`, which are lists of links, and follows the prompting guides
they lead to. Exit 0 read every page; 1 some page was not read, so go on and name each one under
"did not cover"; 2 stops the review, because a lab is missing or the guide for a model the harness
runs was not found: say what it printed. When a routing tier moves to a new model, update its `expect`
line in `reference/lab-sources.txt` first, as with `stale-names.txt`.

Run one `general-purpose` Agent with `reference/lab-advice-brief.md` as the prompt, on the session
model, before the readers. Expect about 110K tokens: the pages come to about 440K chars. Save its
answer as `$OUT/LAB_ADVICE.md`, then:

```bash
$P ~/.claude/skills/model-fit-review/scripts/lab_guidance.py check --lab-dir "$OUT/lab" --advice "$OUT/LAB_ADVICE.md"
```

Exit 1 lists each quote that is not on its page, each number used twice, each item naming the wrong
lab or audience, and each page nobody accounted for: send those back to the reader, or drop the item
when the sentence is not there. A page marked `not read:` is printed and allowed: the report names it. Exit 2 means nothing was collected,
which can never pass. A lab's sentence is a reason to look, never a verdict.

## 2. Readers, seven in parallel

Fill the rubric's four `<FILL: ...>` marks. `--tiers` is one sentence: the serving model you just
read plus the model each pin (`opus`, `sonnet`, `inherit`) reaches in this setup; the script takes
the SIZE and DESCRIPTION sentences from `docs_caps.txt` and the path of `$OUT/LAB_ADVICE.md` itself.
Then write `$OUT/families.json` from `reference/slicing.md` (family name to a list of skill folder
names, paths or globs such as `agents/*`; a new skill joins its family) and cut the slices:

```bash
$P ~/.claude/skills/model-fit-review/scripts/fill_rubric.py --out "$OUT" --tiers "<serving model; tier defaults>"
$P ~/.claude/skills/model-fit-review/scripts/build_slices.py --out "$OUT" --families "$OUT/families.json" --extra <family>=skills/_shared/<note>.md
```

`fill_rubric.py` exits 0 when no mark is left and 2 when it cannot fill one, so no reader starts on
a half-filled rubric. `build_slices.py` exits 1 and names each file with no family or two, and each
family over 350K chars (split it); fix `families.json` and run it again. Spawn one
`general-purpose` Agent per slice in `$OUT/slices.json` with `reference/reader-brief.md` as the
prompt, all in one message. Each reader returns text, and a helper cannot write the file itself.
Save each report the moment it arrives, from the `output_file` its Agent call returned:

```bash
$P ~/.claude/skills/model-fit-review/scripts/save_slice.py "<output_file>" "$OUT/slice_<family>.md"
```

Exit 2 means that file holds no hand-back with a verdict in it, so the reader was cut off or failed:
run that reader again, or save its report by hand from its message.
Expect 5 to 10 minutes and about 2M tokens for seven readers over 1.5 MB.

## 3. Trust nothing you did not re-grep

A reader returns claims. Before any number goes into the report, re-run it: the pointer phrase
count by file, the stale names, the readers of a shared file, a dead tool or command name
(`grep -rn <name> skills agents commands`, and look in `settings.json` and `~/.claude.json`
for a tool a reader says is missing), a "measured 0 uses" claim against the transcripts. Keep
the two scopes apart in every count: the reviewed files (what `inventory.py` reads) and the
whole folders (scripts, tests, `_shared` included).

```bash
$P ~/.claude/skills/model-fit-review/scripts/coverage_check.py --root ~/.claude --slices "$OUT"
```

Exit 0 means every skill, agent and command has a heading and a verdict word in some slice file
(a path mentioned in prose is not a verdict); 1 lists each MISSING one (send it to a reader); 2
means no slice files were found, which can never pass.

## 4. The report

Write `$OUT/REPORT_body.md` in the shape of `reference/report-shape.md`: the short answer, then the
decisions only the user can make (anything that retires or loosens a gate, touches a public pack, or
contradicts a recorded decision), then the fixes that need no decision in three groups (wrong or
dead text; text written for a weaker model; size and duplication), then the line
`<!-- LAB SECTION -->`, then `## 6. Per-file verdicts` and the line `<!-- VERDICTS -->`, then what
the review did not cover. Plain words, no pipe tables, no em dashes. When a reader's number turns
out wrong, add a dated Correction block at the top rather than rewriting the slice files, so the
trail stays readable. Write each lab item's outcome into `$OUT/outcomes.json` (`{"A1": "DIFFERS:
<file, line and the change>"}`, starting FOLLOWED, DIFFERS, ADD or NOT FOR US), then build the
report and check it:

```bash
$P ~/.claude/skills/model-fit-review/scripts/assemble_report.py --out "$OUT" --body "$OUT/REPORT_body.md" --outcomes "$OUT/outcomes.json"
$P ~/.claude/skills/model-fit-review/scripts/lab_guidance.py check --lab-dir "$OUT/lab" --advice "$OUT/LAB_ADVICE.md" --report "$OUT/REPORT.md"
```

`assemble_report.py` copies each quote from `LAB_ADVICE.md` (never retyped) and writes one verdict
line per file in `slices.json`; it exits 2 on a file with no verdict or two different ones (send it
back to its reader), an item with no outcome, an unknown outcome word, a quote not on one line or a
missing place line. The check fails unless each number starts a line carrying its real quote
and an outcome, and names each page the reader could not read.

## 5. What comes after is a separate ask

The report ends the skill. A fix plan and the edits are the user's call and follow the
normal development flow: a plan, a branch, a review, then install.

## Rules

- Recommend, never edit: this skill changes no file outside `$OUT` except `reference/stale-names.txt`.
- A number in the report is one a command printed in this run. A reader's count is a claim.
- A sentence from a lab is quoted from the page saved in this run, and `lab_guidance.py check` proves it. Never quote one from memory.
- Measure frontmatter with a YAML parser, never with a regex to the next key.
- The rubric's KEEP list is not negotiable: a dated incident story may go, the rule it taught stays.
- The run folder holds the user's own paths and findings: keep it out of any public place.
