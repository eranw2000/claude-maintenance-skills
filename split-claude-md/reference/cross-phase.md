## Implementation notes (all phases)

- Use `sed -n 'A,Bp'` for line-range extraction. Avoid awk-only solutions because date matching across formats is brittle.
- Heredocs for the templated header blocks. Always use `<<'HEADER'` (single quotes) to prevent shell expansion inside the template.
- When grouping entries by month, parse the date with `grep -oE '^[0-9]{4}-[0-9]{2}-[0-9]{2}'` and split on `-`. Don't try to be clever with `date -d` — dates in CLAUDE.md are ISO 8601 strings, not shell-native.
- Some headings have variants: `### 2026-05-07 (late): ...` or `### 2026-05-05/06: ...`. For the ENTRY convention the leading `YYYY-MM-DD` is the first 10 chars after `### `; use that for date matching, don't try to parse the rest. This is NOT true for the other two conventions: a dated `## ` section carries its date in a trailing parenthetical, and a record BULLET carries it paren-anchored before the line's first colon (`- Shipped (YYYY-MM-DD): ...`), which is exactly how it is told apart from instance-row decoys dated at line start.
- The `## ` heading boundary detection must skip the new `## Finding Historical Context`, `## Known Patterns & Gotchas`, and `## Decisions Log` headers (they're the boundaries of the sections being modified).

## Edge cases

- **No commit hashes in entries.** That's fine for all phases — the entry title is enough for the index, and pattern entries can omit the commit if not cited.
- **Entries with multi-dated headings (`### 2026-05-05/06: ...`).** Treat the earliest date as the entry's date for bucketing.
- **Entries with dates that span months at the cut boundary.** Use the entry's own date (leftmost), not the cut date.
- **Multiple Decisions Log sections.** Rare. Stop and ask the user which one to process; don't guess.
- **No dated entries at all.** Stop Phase A. Phases B and C can still run independently.
- **A pattern has only 1 instance but is repeatedly cited as a cautionary tale** (e.g., a Phase 4 cascade that almost shipped). It's OK to include it as a Pattern entry tagged `(1 instance — cautionary)` if the user wants future sessions to be alert for the recurrence. Ask the user.
- **Phase B finds no candidates worth consolidating.** Report that, do nothing, exit Phase B clean. Don't manufacture patterns to justify the run.
- **Phase C finds no extractable sections.** Same posture — report, exit Phase C clean, don't extract small or active sections just to justify a run.
- **A Phase C target file already exists** (e.g., `ARCHITECTURE.md` from a prior run). Append new sections to it; do NOT rewrite the existing header (preserves provenance) and do NOT overwrite prior sections without explicit user approval.
- **A section's heading contains characters that complicate the stub** (em-dashes, parens, special chars). Preserve the heading verbatim in the stub — copy-paste don't retype.

## Lessons from prior runs

Patterns the skill has observed across multiple real runs. Apply them proactively even when the user hasn't mentioned them.

### Heading conventions vary by project

Different projects log their decisions differently. Examples seen so far:
- Standard: `### YYYY-MM-DD: title` inside `## Decisions Log`.
- Version-keyed: `### vN.M.K (YYYY-MM-DD) — title` inside `## Recalibration History` or `## Release History`.
- Mixed-dated: `### 2026-05-05/06: title` (range), `### v4.10.11 (Current, 2026-05-07) — title` (parenthetical qualifier).
- Undated old entries: `### v4.0` with no date at all — historical, predates the project's adoption of dating.
- Dated top-level BULLETS: `- Shipped (YYYY-MM-DD): title ...` interleaved with undated config bullets inside one section (a project whose one section mixes shipped-on dates with standing config). `survey.py` detects this as `convention=bullet`. Two traps it defends against, both measured on the real file: instance rows in a Known Patterns section are dated at line START with no paren, and a share floor alone cannot separate them (95% of that section's chars under a bare date match), so the paren anchor before the first colon is the discriminator, never widen it; and two false-positive shapes need their own rules (a config bullet whose date is an incidental mid-line parenthetical, and an archive-pointer bullet whose paren holds a date RANGE).

Procedure:
1. Discover the convention via A1 sanity-floor grep.
2. Confirm with the user when you find a non-default style. Don't STOP just because the default pattern returned zero.
3. Adapt the date-extraction regex to match.
4. Document the discovered convention in the INDEX file's "Project heading convention" subsection so the next run inherits it.
5. Undated old entries bucket under `pre-YYYY-MM.md` (a single archive that holds everything older than the earliest dated entry kept active) rather than per-month buckets.

### First-run honest report

The "Finding Historical Context" navigation section is ~35 lines / ~1.5 KB. On a first run where only a handful of entries qualify for the archive (e.g., 2 undated entries totaling 15 lines), CLAUDE.md grows net. **Report this honestly:** state the line/char delta, the structural reason (navigation overhead vs. archive size), and the compounding effect future runs deliver. Don't claim "saved bytes" if you added them. Don't STOP unless the growth is unexplained by the navigation section.

### Phase B's real win is findability, not compression

A canonical pattern entry (Signal / Fix shape / Detection rule / Project hooks / Instances / See-also) is heavier than a one-line Lessons-Learned bullet. Expect Phase B to GROW the section it consolidates (saw +~6.5 KB on one run). Be explicit with the user that the win is currency and findability: future sessions scan one structured section instead of grepping decision-log prose for related instances. Compression of the file is a Phase A / Phase C goal, not Phase B's.

### When to promote a project pattern to global memory

The signal to promote during Phase B:
- The pattern's fix shape names no project-specific symbols (no function names, file paths, table names from this codebase).
- The pattern's signal would recognise the same bug in another tech stack — same shape, different surface (e.g., "status string with trailing detail breaks `==`" applies to many systems, not just this one).
- The pattern's detection rule (when to check for it) is portable.

When all three are true, write the proposed global memory entry as a DRAFT and present it to the user along with the existing project pattern. The user owns the global memory layout; they approve or decline. Two real promotions captured this way: `feedback_verify_compute_order.md` (pipeline dependency-order bugs, recognisable in any pipeline language) and `feedback_status_string_startswith.md` (status field comparisons, recognisable across many storage layers). Both started as project patterns and were promoted only after the cross-project shape was articulated.

The project entry then becomes shorter — it cites the project-specific symptoms / hooks / instances and ends with `**See also (global memory):** \`feedback_<name>.md\``. The cross-project lesson lives once, in global memory.

### Topic-specific Phase C filenames

When a project has a dominant reference topic (a giant Metrics section, a domain-model dump, an API catalog), name the extracted file after the topic (`METRICS.md`, `DATA_MODEL.md`, `API.md`) rather than forcing it into `ARCHITECTURE.md`. Future sessions find files by name; topical filenames are more discoverable. Reserve the generic four-file taxonomy (ARCHITECTURE / DEVELOPMENT / OPERATIONS / DEPLOYMENT) for projects where several smaller related sections share an architectural theme.

### Maintenance threshold is a per-project judgment call

The skill's default `>50K chars` trigger is a heuristic. Some projects accumulate context faster than others. Document the project's own threshold in the "Maintenance rule" line of the Finding Historical Context section — `~50K`, `~100K`, `~150K`, whatever the project's natural cadence is. The threshold is a hint to future sessions, not a hard rule.

### Edit strategy for Phase C stubs

When replacing 5+ sections with stubs, a single Python script that opens the file, finds each heading, scans to the next `## ` heading, and rewrites the slice is much less brittle than 5+ separate multiline `Edit` calls. Sample shape:

```python
import re
path = "CLAUDE.md"
text = open(path, "r", encoding="utf-8").read()
replacements = [
    ("## <Heading 1>", "See `<TARGET>.md` for ..."),
    ("## <Heading 2>", "See `<TARGET>.md` for ..."),
    # ...
]
for heading, stub_body in replacements:
    idx = text.find(heading + "\n")
    if idx == -1: raise SystemExit(f"Heading not found: {heading!r}")
    rest = text[idx + len(heading) + 1:]
    m = re.search(r"^## ", rest, re.MULTILINE)
    if m is None: raise SystemExit(f"No following ## heading after: {heading!r}")
    section_end = idx + len(heading) + 1 + m.start()
    new_block = f"{heading}\n\n{stub_body}\n\n"
    text = text[:idx] + new_block + text[section_end:]
open(path, "w", encoding="utf-8").write(text)
```

Saves several rounds of Edit + Read verification. Safe because each heading is unique and the script fails fast if a heading is missing.

### Always back up

Phase A's required A3 backup loop (CLAUDE.md, the index, the target archive; skip absent files, never overwrite a same-day backup) applies even when Phase A is skipped (`--patterns-only`, `--extract-only`). Phases B and C also mutate CLAUDE.md; the backup is a single revert away from any mistake. The backups are three small file copies: never skip them, and never write them to an ephemeral job tmp dir, which is where the 2026-08-10 run put the index and archive copies before this rule named all three.

### Verify with `diff` against the backup

After all phases complete, `diff <(sed -n '1,10p' CLAUDE.md) <(sed -n '1,10p' CLAUDE.md.backup-before-split-YYYYMMDD)` and the same for the tail should both produce empty output. Preamble and postamble must be byte-identical to the backup. If they're not, something went wrong in the heading-boundary detection or stub replacement. This sanity check is fast and catches the most common Phase C bug.
