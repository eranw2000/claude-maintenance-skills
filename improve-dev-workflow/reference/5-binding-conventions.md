# improve-dev-workflow, step 5: binding conventions for the implementation

- **Binding conventions for the implementation:**
  - Hooks: `hookSpecificOutput` needs `hookEventName` or it is silently dropped; blocking
    needs exit 2 + stderr, not `decision:block`; hooks fail OPEN, and settings.json edits do
    not rewire the running session, so live-fire proof happens in a FRESH session.
  - A repo with an allow-list `.gitignore`: prove a new path is included with
    `git add --dry-run <path>`, paired with a control path that must still be refused.
    `git check-ignore -v` prints the matching line whether it ignores or UN-ignores.
  - Every new gate/guard is MUTATION-TESTED (break it, exactly the intended check fails);
    every negative test carries a CONTRAST assertion.
  - **A guard over a POPULATION (every test, every route, every file) takes its members from
    the consumer's own enumerator**, never from a scan you write: pytest's collection, the
    router's table, `git ls-files`. Its acceptance plants one member of each shape the
    consumer admits and the scan might not (a class, a subfolder, a second naming pattern),
    and any hand-written classification list is checked row by row against the rule it
    claims. A guard that reads only top-level `def test_*` misses a test inside a class.
  - Edited judgment agents get a REGRESSION REPLAY against a past known catch, so an edit
    cannot silently dilute the checklist that reviews everything else.
  - The acceptance test for the whole loop: RE-ENACT the original incident against the new
    guardrail and watch it fire. If the incident cannot be re-enacted, say so explicitly.
    **And when it cannot be re-run NOW** (it needs a fresh session, a later phase, or a real
    service), write an open item in the project `TODO.md` naming the task to re-run, the entry
    point, and what should now happen instead of the miss. "The next run will show it" with
    nothing written down is how the check never happens.
    **Replay the ORIGINAL artifact, never a tidied-up fixture of it.** A guardrail that passes
    its own tests has not been shown to catch anything: a tidy one-line fixture can pass
    while the real code, wrapped over several lines, never matches. And a negative fixture
    the pattern rejects anyway proves nothing. So mutation-test the
    guardrail itself, assert the kill lands on the INTENDED assertion rather than collateral, and
    make every negative fixture one the check would otherwise match.
