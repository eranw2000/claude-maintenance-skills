#!/usr/bin/env python3
"""Tests for the Phase 0 and Phase E detectors added to survey.py on 2026-08-24.

Every detector gets a TWO-WAY control: a fixture it must fire on and a fixture it
must stay silent on. A check that only proves a detector can fire is half a
control, because a detector that answers yes to everything passes it.

Row 0 is a harness control whose value is known. If it fails, the harness is
broken rather than the code.

Run:  python3 test_phase0_phasee.py
"""

import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

# A mutation run rewrites survey.py in place, often within the same second and
# sometimes at the same byte size. CPython's bytecode cache keys on mtime and
# size, so it can serve a STALE survey.pyc: the mutation then reports the wrong
# killing test, or is not detected at all and reads as a surviving mutant.
# A stale cache can credit the wrong test with a kill. Clear the cache before importing
# and never write a new one.
sys.dont_write_bytecode = True
import shutil  # noqa: E402
shutil.rmtree(os.path.join(HERE, "__pycache__"), ignore_errors=True)

import survey as S  # noqa: E402

SURVEY = os.path.join(HERE, "survey.py")


# --- fixtures --------------------------------------------------------------

DERIVABLE = """## Repository layout

- `src/api/handlers.py` handles requests
- `src/api/models.py` holds the schema
- `src/core/util.py` shared helpers
- `tests/test_api.py` the api tests
- `scripts/deploy.sh` the deploy script
- `config/settings.yaml` runtime config
"""

PINS = """## Dependencies

- django==5.0.1
- requests==2.31.0
- psycopg2-binary==2.9.9
- gunicorn==21.2.0
- celery==5.3.4
"""

PITFALL_WITH_PATHS = """## Never edit the vendored tree by hand

You MUST never edit `vendor/upstream/client.py` directly, and you must never
patch `vendor/upstream/auth.py` either. Always regenerate from `tools/vendor.py`
instead, because the next sync silently overwrites `vendor/` and the change is
gone with nothing red. Do not skip this. Run `make vendor` and check the diff.
"""

# A pitfall with ENOUGH paths to clear the hit and share floors, so the ONLY
# thing that can exclude it is the obligation guard. The first pitfall fixture
# above is excluded by TWO guards at once, which let the obligation guard survive
# a mutation: each defence masked the other and neither was really tested.
PITFALL_MANY_PATHS = """## Never hand-edit any vendored file

You MUST never edit `vendor/a/client.py` by hand.
You MUST never edit `vendor/a/auth.py` by hand.
You MUST never edit `vendor/b/models.py` by hand.
You MUST never edit `vendor/b/views.py` by hand.
You MUST never edit `vendor/c/serializers.py` by hand.
You MUST never edit `vendor/c/handlers.py` by hand.
"""

# Few path hits, no obligations, no imperatives. Excluded ONLY by the hit floor,
# so it is what makes that floor testable.
RATIONALE_FEW_PATHS = """## Why the loader lives where it does

The loader sits in `src/boot/loader.py` rather than beside the app.
That ordering is the whole reason, and the file itself does not show it.
"""

# Every line carries a path and no obligation, so it clears the hit floor, the
# share floor and the obligation guard. Excluded ONLY by the imperative guard.
# It is also the correct verdict on its merits: a runbook is a procedure, so it
# belongs in a skill per phase-c-extract.md C6, not in the bin.
RUNBOOK_WITH_PATHS = """## Local setup steps

Run `scripts/bootstrap.sh` to create the environment.
Read `config/local.yaml` and set the database URL.
Write your key into `secrets/dev.env` before the first start.
Check `logs/app.log` after the first request.
Load `fixtures/seed.json` into the database.
Start `src/server.py` and open the browser.
"""

# Four path mentions spread across long prose, so it CLEARS the hit floor while
# the share stays low. Excluded ONLY by the share floor. This is the realistic
# case of a discussion section that happens to name several files.
DISCUSSION_MANY_LINES = """## How the boot sequence came to look like this

The original design put everything in one entry point.
That worked while the process was single threaded.
The change came when the worker pool arrived.
At that point the entry point was doing two unrelated jobs.
`src/boot/entry.py` kept the process-level wiring.
The second job went somewhere with no import cycle.
`src/boot/workers.py` became the home for the pool.
The split was mechanical and took an afternoon.
Nobody has needed to think about it since.
The naming came from the old ticket and nothing else.
`src/boot/legacy_shim.py` is what remains of the first attempt.
It stays because two downstream teams still import from it.
The plan was always to retire it in the next cycle.
`src/boot/README.txt` records the retirement conditions.
Neither team has met them yet.
"""

# One Django rule padded OVER Phase D's floor, so Phase D would reach it and the
# floor arithmetic must count it at RETENTION rather than at full size.
BIG_DJANGO_RULE = ("""## Django admin big trap

A model field with a default is NOT optional in admin.py, and models.py will not
tell you. GET the admin URL and assert on the rendered HTML, never on the model.
Never derive readonly_fields from the model, because an empty POST becomes VALID
and dies on the first NOT NULL column. Check migrations before you trust it.
""" + ("Run the migrations and check models.py again for every field. " * 14))

DJANGO_RULE = """## Django admin traps

A model field with a default is NOT optional, and can be silently absent from the
form. GET the admin URL and assert on the rendered HTML. Never derive
readonly_fields from the model in admin.py, because an empty POST becomes VALID.
Check models.py and run the migrations before you trust it.
"""

CONVO_RULE = """## Lead with the blocking fact

When something is finished but NOT yet in front of the user, that sentence goes
FIRST, on its own line, before any evidence. A thorough verification section
reads as "it works", so a caveat after it does not land however plainly worded.
Never bury it. Always say what is not done.
"""

SCATTERED_RULE = """## Mixed stack notes

You must check the Dockerfile, and you should also verify models.py, plus the
stylesheet in main.css, and never forget the schema.sql migration, and the
package.json pin. Always confirm each one.
"""

PREEMPT_RULE = """## Diagrams are draw.io by default

Whenever a diagram is needed, produce it as a draw.io file. Do NOT default to
Mermaid or Graphviz unless the user asks. Always render the .drawio and look at
the image. Never report a diagram done blind. Use render.py to check it.
"""

MIXED_RULE = """## Frontend contrast

Any change touching a .css or .scss file must clear WCAG AA before it ships.
Measure the ratios, never eyeball them. Always report the number to the user and
ask him which palette to keep when a pair fails.
"""

TINY_DJANGO = """## Django tip

Use models.py and admin.py.
"""


def build(*sections):
    return "# Fixture\n\n" + "\n".join(sections)


def run_survey(text):
    fd, path = tempfile.mkstemp(suffix=".md")
    os.write(fd, text.encode("utf-8"))
    os.close(fd)
    try:
        p = subprocess.run([sys.executable, SURVEY, path],
                           capture_output=True, text=True)
        return p.stdout
    finally:
        os.unlink(path)


def sec(text):
    """Return the single level-2 section object for a one-section fixture."""
    secs = S.collect(build(text).split("\n"), 2)
    assert len(secs) == 1, "fixture must hold exactly one section, got %d" % len(secs)
    return secs[0]


def main():
    checks = []

    def check(name, ok, detail=""):
        checks.append((name, bool(ok), detail))

    # --- row 0, harness control ------------------------------------------
    check("CONTROL: the harness can call survey and get output",
          "FILE" in run_survey(build(DERIVABLE)), "no output at all")

    # --- Phase 0 detector, both directions -------------------------------
    check("prune FIRES on a file map",
          S.is_prune_candidate(sec(DERIVABLE)) is not None,
          str(S.prune_score(sec(DERIVABLE)["body"])))
    check("prune FIRES on a dependency pin list",
          S.is_prune_candidate(sec(PINS)) is not None,
          str(S.prune_score(sec(PINS)["body"])))
    check("prune is SILENT on a pitfall that is full of paths",
          S.is_prune_candidate(sec(PITFALL_WITH_PATHS)) is None,
          "a pitfall dressed as a file map must never be offered for deletion")
    check("prune is SILENT on a conversation rule",
          S.is_prune_candidate(sec(CONVO_RULE)) is None, "")
    # This one isolates the obligation guard: the fixture CLEARS the hit and
    # share floors, so only the obligation density can exclude it. Without it,
    # deleting the obligation guard passed the whole suite.
    _b = sec(PITFALL_MANY_PATHS)["body"]
    _share, _ev = S.prune_score(_b)
    _hits = _ev["path_lines"] + _ev["tree_lines"] + _ev["pin_lines"]
    check("the isolating fixture really does clear the hit and share floors",
          _hits >= S.PRUNE_MIN_HITS and _share >= S.PRUNE_SHARE,
          "hits=%d share=%.2f -- if this fails the next check is vacuous"
          % (_hits, _share))
    check("prune is SILENT on a pitfall that CLEARS the path floors",
          S.is_prune_candidate(sec(PITFALL_MANY_PATHS)) is None,
          "only the obligation guard can exclude this one")

    # Each guard needs a fixture that ONLY it excludes. Without one, two guards
    # mask each other and a mutation to either survives the whole suite.
    def only_guard_left(fixture):
        """Return which guards exclude this fixture, so isolation is provable."""
        body = sec(fixture)["body"]
        share, ev = S.prune_score(body)
        hits = ev["path_lines"] + ev["tree_lines"] + ev["pin_lines"]
        lines = [l for l in body.split("\n")[1:] if l.strip()]
        n = len(lines) or 1
        obl = len(S.OBLIGATION_RE.findall(body)) / n
        imp = sum(1 for l in lines if S.IMPERATIVE_RE.match(l)) / n
        out = []
        if hits < S.PRUNE_MIN_HITS:
            out.append("hits")
        if share < S.PRUNE_SHARE:
            out.append("share")
        if obl > S.PRUNE_MAX_OBLIGATION:
            out.append("obligation")
        if imp > S.PRUNE_MAX_IMPERATIVE:
            out.append("imperative")
        return out

    check("the hit-floor fixture is excluded by the HIT FLOOR ALONE",
          only_guard_left(RATIONALE_FEW_PATHS) == ["hits"],
          "excluded by %s -- if more than one, the next check is not isolating"
          % only_guard_left(RATIONALE_FEW_PATHS))
    check("prune is SILENT on a rationale with one path mention",
          S.is_prune_candidate(sec(RATIONALE_FEW_PATHS)) is None, "")

    check("the share-floor fixture is excluded by the SHARE FLOOR ALONE",
          only_guard_left(DISCUSSION_MANY_LINES) == ["share"],
          "excluded by %s -- if more than one, the next check is not isolating"
          % only_guard_left(DISCUSSION_MANY_LINES))
    check("prune is SILENT on prose that merely names several files",
          S.is_prune_candidate(sec(DISCUSSION_MANY_LINES)) is None,
          "four paths across fifteen lines is a discussion, not a file map")

    check("the runbook fixture is excluded by the IMPERATIVE GUARD ALONE",
          only_guard_left(RUNBOOK_WITH_PATHS) == ["imperative"],
          "excluded by %s -- if more than one, the next check is not isolating"
          % only_guard_left(RUNBOOK_WITH_PATHS))
    check("prune is SILENT on a runbook whose every line carries a path",
          S.is_prune_candidate(sec(RUNBOOK_WITH_PATHS)) is None,
          "a procedure is not derivable content; it belongs in a skill")
    check("prune excludes RULE-shaped sections by construction",
          S.classify_shape(sec(PITFALL_WITH_PATHS)["body"])[0] == "RULE",
          "the shape classifier is the primary guard for Phase 0")

    # --- Phase 0 in the real report --------------------------------------
    out = run_survey(build(DERIVABLE, PINS, PITFALL_WITH_PATHS))
    blk = out.split("PHASE 0 PRUNE CANDIDATES")[-1].split("PHASE C CANDIDATES")[0]
    check("report lists the file map under Phase 0",
          "Repository layout" in blk, blk[:300])
    check("report does NOT list the pitfall under Phase 0",
          "vendored tree" not in blk, blk[:300])
    check("report tells the run to execute the replacement command",
          "RUN that command" in blk, blk[:300])

    # --- Phase E detector, both directions -------------------------------
    r = S.scope_candidate(sec(DJANGO_RULE))
    check("scope FIRES on a Django rule", r is not None, str(r))
    check("scope names the django family and its globs",
          r and r[0] == "django" and "**/models.py" in r[1], str(r))
    check("scope is SILENT on a conversation rule",
          S.scope_candidate(sec(CONVO_RULE)) is None,
          "a rule with no file vocabulary must never be scoped")
    check("scope is SILENT on scattered vocabulary",
          S.scope_candidate(sec(SCATTERED_RULE)) is None,
          str(S.scope_candidate(sec(SCATTERED_RULE))))
    check("scope is SILENT on a REFERENCE-shaped section",
          S.scope_candidate(sec(DERIVABLE)) is None, "")

    # --- the two flags, each with its negative ---------------------------
    rp = S.scope_candidate(sec(PREEMPT_RULE))
    check("PREEMPT fires on a tool-choice rule", rp and rp[5] is True, str(rp))
    rd = S.scope_candidate(sec(DJANGO_RULE))
    check("PREEMPT does NOT fire on an ordinary file rule",
          rd and rd[5] is False, str(rd))
    rm = S.scope_candidate(sec(MIXED_RULE))
    check("MIXED fires when the rule also addresses the user",
          rm and rm[4] is True, str(rm))
    check("MIXED does NOT fire on a pure file rule",
          rd and rd[4] is False, str(rd))

    # --- the threshold that was wrong the first time ---------------------
    check("PHASE_E_CHARS is far below Phase D's floor",
          S.PHASE_E_CHARS < S.PHASE_D_CHARS / 4,
          "Phase E moves the whole rule out, so a small rule pays in full. "
          "At Phase D's 900-char floor the detector found ZERO candidates on a "
          "file full of Django rules. PHASE_E_CHARS=%d PHASE_D_CHARS=%d"
          % (S.PHASE_E_CHARS, S.PHASE_D_CHARS))
    out2 = run_survey(build(DJANGO_RULE))
    check("a rule well under Phase D's floor IS offered to Phase E",
          "django.md" in out2 and len(sec(DJANGO_RULE)["body"]) < S.PHASE_D_CHARS,
          "section is %d chars" % sec(DJANGO_RULE)["chars"])
    out3 = run_survey(build(TINY_DJANGO))
    check("a rule under PHASE_E_CHARS is NOT offered",
          "django.md" not in out3.split("PHASE E SCOPE")[-1],
          "tiny section is %d chars, floor is %d"
          % (sec(TINY_DJANGO)["chars"], S.PHASE_E_CHARS))

    # --- grouping and the second floor -----------------------------------
    out4 = run_survey(build(DJANGO_RULE, MIXED_RULE, PREEMPT_RULE))
    ublk = out4.split("PHASE E SCOPE")[-1].split("FLOOR")[0]
    check("candidates group by family into one rules file",
          ".claude/rules/django.md" in ublk, ublk[:400])
    check("singular is used for one rule, not '1 rules'",
          "1 rules" not in ublk, ublk[:400])
    check("the compaction caveat is stated in the report",
          "LOST after a compaction" in ublk, ublk[:400])
    fblk = out4.split("FLOOR")[-1]
    check("the report prints a SECOND floor for Phase E",
          "ESTIMATE AFTER PHASE E" in fblk, fblk[:400])
    check("the second floor is at or below the first",
          _num(fblk, "ESTIMATE AFTER PHASE E  ~") <= _num(fblk, "ESTIMATE  ~"),
          fblk[:400])
    check("PREEMPT rules are excluded from the saving claim in words",
          "PREEMPT-flagged rules are NOT in this number" in fblk, fblk[:400])

    # --- the floor arithmetic, which differs by whether Phase D reached it --
    big = sec(BIG_DJANGO_RULE)
    small = sec(DJANGO_RULE)
    check("the arithmetic fixtures straddle Phase D's floor",
          big["chars"] >= S.PHASE_D_CHARS and small["chars"] < S.PHASE_D_CHARS,
          "big=%d small=%d floor=%d -- if this fails the next two are vacuous"
          % (big["chars"], small["chars"], S.PHASE_D_CHARS))
    fb = run_survey(build(BIG_DJANGO_RULE)).split("FLOOR")[-1]
    saved_big = _scope_saving(fb)
    check("a rule Phase D WOULD reach is counted at retention, not full size",
          saved_big == int(big["chars"] * S.RULE_RETENTION),
          "reported saving %d, expected %d (chars %d at %d%% retention). "
          "Counting it at full size would overstate the Phase E win."
          % (saved_big, int(big["chars"] * S.RULE_RETENTION),
             big["chars"], int(S.RULE_RETENTION * 100)))
    fs = run_survey(build(DJANGO_RULE)).split("FLOOR")[-1]
    saved_small = _scope_saving(fs)
    check("a rule Phase D would NOT reach is counted at full size",
          saved_small == small["chars"],
          "reported saving %d, expected %d (the whole section leaves)"
          % (saved_small, small["chars"]))

    # --- a file with nothing to scope must say so ------------------------
    out5 = run_survey(build(CONVO_RULE))
    check("a file of conversation rules offers NO scope candidates",
          "none" in out5.split("PHASE E SCOPE")[-1].split("FLOOR")[0],
          out5.split("PHASE E SCOPE")[-1][:300])

    if not checks:
        print("0/0 passed -- the harness ran NO checks, which is a harness bug")
        return 1
    failed = [c for c in checks if not c[1]]
    for name, ok, detail in checks:
        if not ok:
            print("  FAILED " + name)
            print("         " + str(detail).replace("\n", "\n         ")[:500])
    print("%d/%d passed" % (len(checks) - len(failed), len(checks)))
    return 1 if failed else 0


def _scope_saving(floor_block):
    """Read the chars Phase E is credited with from the floor block."""
    import re as _re
    m = _re.search(r"(\d+) ch  of that estimate is", floor_block)
    return int(m.group(1)) if m else -1


def _num(text, marker):
    seg = text.split(marker)[-1]
    digits = ""
    for ch in seg:
        if ch.isdigit():
            digits += ch
        elif digits:
            break
    return int(digits) if digits else -1


if __name__ == "__main__":
    sys.exit(main())
