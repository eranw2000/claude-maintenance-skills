## Phase D - Extract evidence from RULE sections

Phase C moves a whole section out and leaves a stub. That is right for a
reference section and **wrong for a rule section**: a rule moved out of an
always-loaded file stops being read, so the file gets smaller and the behaviour
it was supposed to govern quietly stops happening. Phase D is the lever for
rule-shaped sections. It cuts **within** a section instead of between sections:
the rule stays, only its evidence leaves.

**Origin.** Run against the global `~/.claude/CLAUDE.md` on 2026-08-11, Phase A
could not run (no dated records) and Phase C offered 13 candidates of which
**13 of 13 were rules** - "Working Preferences", "All Writing: Avoid AI Signals",
"Model routing". Following Phase C literally would have moved behaviour rules out
of the always-loaded file. Phase D achieved 131,926 -> 65,034 chars (-51%) with
every rule retained.

### D1. Confirm the shape

`survey.py` labels every candidate `RULE` or `REFERENCE` and prints a FLOOR
block. Read both before starting:

- **REFERENCE candidates go to Phase C.** Phase D is not for them.
- **The FLOOR is a hard limit.** It states what extraction can reach on this
  file. **A target below the floor cannot be met by extraction; it means deleting
  rules. Say so before starting**, rather than discovering it three passes in.
  Measured 2026-08-11: a 8,000-token target was set for a file whose floor was
  ~16,100, and the gap only became visible after the work was done.

### D2. Split each rule section

For every RULE-shaped section over the Phase D threshold (900 chars), the body
becomes: **the imperative, the sharpest tell, and a pointer.** Everything else -
the worked example, the incident, the measurement, the war story - moves to a
satellite.

- **What stays:** what to DO, what the tell is, and any operative literal (a
  command, a flag, a threshold, a bypass token). If deleting a sentence would
  change what someone does, it stays.
- **What goes:** how it was discovered, what it cost, the dates, the project
  names, the measured figures backing the rule.
- **Satellite headings MUST match the CLAUDE.md headings exactly**, so the
  pointer resolves by searching the same text. One satellite per theme, not one
  per section.

### D3. Do it programmatically, not by hand

Parse the file into sections, replace ONLY the bodies over the threshold, and
leave every heading and every under-threshold section **byte-identical**. Editing
105 sections by hand is how a heading gets lost. The 2026-08-11 run replaced 41
bodies and left 64 sections untouched, verified byte-for-byte.

### D4. Verify Phase D

Phase C's C5 check ("confirm every original section heading is still present")
is necessary but **NOT sufficient here, and the difference is the whole point:
a heading check passes on a stub whose rule has been gutted.** Phase D adds:

- **A must-survive rule list.** Before starting, hand-write the distinctive
  phrases of the load-bearing rules - the ones whose loss would change behaviour
  - and grep the finished file for every one. The 2026-08-11 run used 34 and all
  34 survived. This is the check that actually proves the cut was safe.
- **Every moved body appears verbatim in its satellite.** Assert the exact
  original text is present, so nothing was silently reworded on the way out.
- **Every untouched section is byte-identical** to the backup.
- **No NEW characters were introduced.** Compare the character set against **the
  ORIGINAL file, not against an absolute.** A pure-ASCII assertion is the wrong
  check and will fail on a legitimate file: the global CLAUDE.md carries 163
  non-ASCII characters on purpose (49 em dashes, Hebrew scan terms, arrows). This
  is the same wrong-scope error as checking a registry and reporting about the
  system.

### Phase D does NOT

- Touch a REFERENCE-shaped section (that is Phase C).
- Reword a rule. Compression removes evidence; it never rephrases the imperative.
- Chase a size target below the floor. Report the floor and stop.

---


### D5. The floor is not the end any more (added 2026-08-24)

D1 says a target below the floor cannot be met by extraction and means deleting
rules. That was true when the only destinations were CLAUDE.md and a satellite
file. It is no longer the whole picture.

A rule whose trigger is a FILE can move to `.claude/rules/` with `paths:`
frontmatter and leave the always-loaded set entirely, without being deleted and
without ceasing to fire. That is Phase E, and it is the lever below Phase D's
floor.

So the honest statement of the floor has two parts. Phase D's floor is what
EVIDENCE EXTRACTION can reach while every rule stays always-loaded. Phase E's
floor is what remains once every file-triggered rule has moved out. `survey.py`
prints both. Report both, and say which one a requested target sits under.

What has NOT changed: a rule whose trigger is a CONVERSATION stays in the
always-loaded file at Phase D's retention, and no phase may move it. Phase E's
E3 list is the boundary.
