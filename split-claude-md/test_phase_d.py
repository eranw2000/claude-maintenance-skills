#!/usr/bin/env python3
"""Tests for phase_d.py (Phase D: keep rules, move story sentences).

Every fixture is a synthetic string written to a mkdtemp folder. Row 0 is a
CONTROL with a known answer: if it fails, the harness is broken rather than
the script. Two fixture shapes matter most: a unit already in the archive
word for word, and one shared pointer line instead of one per section.

Run:  python3 test_phase_d.py
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
TOOL = os.path.join(HERE, "phase_d.py")

CLAUDE = """# Project

## Finding Historical Context

- `CLAUDE_DECISIONS_YYYY-MM.md` - full archived entries by month.

## Widget export (2026-09-02)

- **Run the export with `--dry` first.** The first run wiped 40 rows by
  accident. Then run it for real.
- **Keep the bucket name in `export.cfg`.** It moved twice in August.

Paragraph about the exporter, wrapped
over two lines. It was found on a Tuesday.

```text
## not a heading, inside a fence
```

- **After the fence.** Written after lunch.

## Untouched (2026-09-03)

- A line nobody edits. It stays exactly.
"""
ARCHIVE = "# Decisions Log Archive, 2026-09\n\n---\n"
INDEX = "# Decisions Log Index\n\n## Entries (chronological)\n\n- 2026-09-01: old row\n"
H = "## Widget export (2026-09-02)"


def cut(prefix, drops, **kw):
    c = {"heading": H, "prefix": prefix, "mode": "join", "archive": "2026-09", "drops": drops}
    c.update(kw)
    return c


C_BULLET = cut("- **Run the export", [" The first run wiped 40 rows by accident."])
C_PARA = cut("Paragraph about the exporter", [" It was found on a Tuesday."])
POINTER = {"after": "- `CLAUDE_DECISIONS_YYYY-MM.md` - full archived entries by month.",
           "line": "- Story sentences cut from kept sections are in the month archive."}


def setup(claude=CLAUDE, archive=ARCHIVE, index=INDEX):
    d = tempfile.mkdtemp(prefix="phase_d_test_")
    files = {"CLAUDE.md": claude, "CLAUDE_DECISIONS_2026-09.md": archive,
             "CLAUDE_DECISIONS_INDEX.md": index}
    for name, text in files.items():
        if text is not None:
            with open(os.path.join(d, name), "w", encoding="utf-8") as fh:
                fh.write(text)
    return d


def run(d, spec, *extra):
    sp = os.path.join(d, "spec.json")
    with open(sp, "w", encoding="utf-8") as fh:
        fh.write(spec if isinstance(spec, str) else json.dumps(spec))
    p = subprocess.run([sys.executable, TOOL, os.path.join(d, "CLAUDE.md"), "--spec", sp,
                        "--today", "2026-10-13"] + list(extra), capture_output=True, text=True)
    return p.returncode, p.stdout + p.stderr


def read(d, name):
    with open(os.path.join(d, name), encoding="utf-8") as fh:
        return fh.read()


def unchanged(d):
    return (read(d, "CLAUDE.md") == CLAUDE and read(d, "CLAUDE_DECISIONS_2026-09.md") == ARCHIVE
            and read(d, "CLAUDE_DECISIONS_INDEX.md") == INDEX)


RESULTS = []


def check(name, cond, detail=""):
    RESULTS.append((name, bool(cond)))
    if not cond:
        print("FAILED %s %s" % (name, detail[:400]))


def t00_control_dry_run_passes_and_writes_nothing():
    d = setup()
    rc, out = run(d, {"cuts": [C_BULLET]})
    check("00 control: dry run exit 0", rc == 0 and "ALL CHECKS PASS" in out, out)
    check("00 control: dry run writes nothing", unchanged(d))
    shutil.rmtree(d)


def t01_write_moves_story_keeps_rule():
    d = setup()
    rc, out = run(d, {"cuts": [C_BULLET]}, "--write")
    cm, ar = read(d, "CLAUDE.md"), read(d, "CLAUDE_DECISIONS_2026-09.md")
    check("01 write exit 0", rc == 0, out)
    check("01 rule kept, joined onto one line",
          "- **Run the export with `--dry` first.** Then run it for real.\n" in cm, cm)
    check("01 story gone from CLAUDE.md", "wiped 40 rows" not in cm)
    old = ("- **Run the export with `--dry` first.** The first run wiped 40 rows by\n"
           "  accident. Then run it for real.")
    check("01 old unit verbatim in archive, under the same heading",
          ar.count(old) == 1 and ar.index(H) < ar.index(old), ar)
    check("01 index row added", "2026-10-13: Story sentences cut from 1 unit(s)" in read(d, "CLAUDE_DECISIONS_INDEX.md"))
    check("01 backups made", all(os.path.exists(os.path.join(d, n + ".backup-before-split-2026-10-13"))
                                 for n in ("CLAUDE.md", "CLAUDE_DECISIONS_2026-09.md", "CLAUDE_DECISIONS_INDEX.md")))
    check("01 untouched section identical",
          cm.split("## Untouched (2026-09-03)")[1] == CLAUDE.split("## Untouched (2026-09-03)")[1])
    shutil.rmtree(d)


def t02_already_archived_unit_not_copied_twice():
    old = ("- **Run the export with `--dry` first.** The first run wiped 40 rows by\n"
           "  accident. Then run it for real.")
    d = setup(archive=ARCHIVE + "\n" + H + "\n\n" + old + "\n")
    rc, out = run(d, {"cuts": [C_BULLET]}, "--write")
    ar = read(d, "CLAUDE_DECISIONS_2026-09.md")
    check("02 exit 0 when the unit is already archived", rc == 0, out)
    check("02 not copied a second time", ar.count(old) == 1, ar)
    check("02 reported as already archived", "already archived: 1" in out, out)
    check("02 index row says so", "already archived word for word" in read(d, "CLAUDE_DECISIONS_INDEX.md"))
    shutil.rmtree(d)


def t03_one_shared_pointer_line_never_twice():
    d = setup()
    rc, out = run(d, {"cuts": [C_BULLET, C_PARA], "pointer": POINTER}, "--write")
    cm = read(d, "CLAUDE.md")
    check("03 pointer added once", rc == 0 and cm.count(POINTER["line"]) == 1, out)
    check("03 pointer placed after the named line",
          POINTER["after"] + "\n" + POINTER["line"] + "\n" in cm, cm)
    check("03 no pointer line per section", cm.count("Evidence moved out") == 0)
    rc2, out2 = run(d, {"cuts": [cut("- **Keep the bucket", [" It moved twice in August."])],
                        "pointer": POINTER}, "--write", "--no-backup")
    check("03 second run does not add it again", rc2 == 0 and read(d, "CLAUDE.md").count(POINTER["line"]) == 1, out2)
    shutil.rmtree(d)


def t04_drop_must_match_exactly_once():
    d = setup()
    rc, out = run(d, {"cuts": [cut("- **Run the export", [" No such sentence."])]}, "--write")
    check("04 a drop that matches nothing refuses (3)", rc == 3 and "matches 0 times" in out, out)
    check("04 nothing written", unchanged(d))
    rc, out = run(d, {"cuts": [cut("- **Run the export", ["run"])]}, "--write")
    check("04 a drop that matches twice refuses (3)", rc == 3 and "matches 2 times" in out, out)
    shutil.rmtree(d)


def t05_prefix_must_sit_under_the_named_heading():
    d = setup()
    rc, out = run(d, {"cuts": [cut("- A line nobody edits.", [" It stays exactly."])]}, "--write")
    check("05 wrong section refuses (3)", rc == 3 and "is under" in out, out)
    rc, out = run(d, {"cuts": [cut("- **Nope", [" x"])]})
    check("05 a prefix that starts no line refuses (3)", rc == 3 and "starts 0 lines" in out, out)
    check("05 nothing written", unchanged(d))
    shutil.rmtree(d)


def t06_rule_sentence_must_survive_unless_allowed():
    d = setup()
    rc, out = run(d, {"cuts": [cut("- **Run the export", [" The first run wiped 40 rows by accident. Then run it for real."])]})
    check("06 control: a drop with no rule word passes", rc == 0, out)
    claude = CLAUDE.replace("The first run wiped", "Never skip it. The first run wiped")
    d2 = setup(claude=claude)
    c = cut("- **Run the export", [" Never skip it."])
    rc, out = run(d2, {"cuts": [c]}, "--write")
    check("06 dropping a whole 'Never' sentence refuses (3)", rc == 3 and "rule sentence would not survive" in out, out)
    check("06 nothing written", read(d2, "CLAUDE.md") == claude)
    c["allow_rule_edit"] = True
    rc, out = run(d2, {"cuts": [c]})
    check("06 allow_rule_edit lets it through", rc == 0, out)
    shutil.rmtree(d)
    shutil.rmtree(d2)


def t07_double_space_left_refused():
    d = setup()
    rc, out = run(d, {"cuts": [cut("- **Run the export", ["The first run wiped 40 rows by accident."])]}, "--write")
    check("07 a drop that leaves two spaces refuses (3)", rc == 3 and "double or trailing space" in out, out)
    check("07 nothing written", unchanged(d))
    shutil.rmtree(d)


def t08_overlapping_cuts_refused():
    d = setup()
    rc, out = run(d, {"cuts": [C_BULLET, cut("- **Run the export", [" Then run it for real."])]})
    check("08 two cuts on the same unit refuse (3)", rc == 3 and "cut 1 and cut 2 overlap" in out, out)
    shutil.rmtree(d)
    # A parent bullet and its nested child start on DIFFERENT lines
    nested = CLAUDE.replace("- **Keep the bucket name",
                            "- **Parent rule.** Outer story.\n  - **Child.** Child story.\n"
                            "- **Must preserve the sibling rule.**\n- **Keep the bucket name")
    d = setup(claude=nested)
    rc, out = run(d, {"cuts": [cut("- **Parent rule.**", [" Outer story."], mode="raw"),
                               cut("  - **Child.**", [" Child story."])]}, "--write")
    check("08 a parent cut and a nested child cut overlap: refused (3)",
          rc == 3 and "overlap" in out, out)
    check("08 nothing written, the sibling rule still there",
          read(d, "CLAUDE.md") == nested and "- **Must preserve the sibling rule.**" in read(d, "CLAUDE.md"))
    shutil.rmtree(d)


def t09_paragraph_unit_and_fence():
    d = setup()
    rc, out = run(d, {"cuts": [C_PARA]}, "--write")
    cm = read(d, "CLAUDE.md")
    check("09 paragraph joined and cut", rc == 0 and
          "Paragraph about the exporter, wrapped over two lines.\n\n```text" in cm, out + cm)
    rc, out = run(d, {"cuts": [cut("- **After the fence.**", [" Written after lunch."])]}, "--write", "--no-backup")
    check("09 a '## ' line inside a fence does not end the section", rc == 0 and
          "- **After the fence.**\n" in read(d, "CLAUDE.md"), out)
    shutil.rmtree(d)


def t10_bad_spec_cannot_tell():
    d = setup()
    rc, out = run(d, "{not json")
    check("10 unreadable spec is exit 2", rc == 2 and "CANNOT TELL" in out, out)
    rc, out = run(d, {"cuts": [{"heading": H, "prefix": "x", "archive": "Sept", "drops": ["a"]}]})
    check("10 bad archive month is exit 2", rc == 2, out)
    check("10 nothing written", unchanged(d))
    shutil.rmtree(d)


def t11_archive_created_when_absent():
    d = setup(archive=None)
    rc, out = run(d, {"cuts": [C_BULLET]}, "--write")
    ar = read(d, "CLAUDE_DECISIONS_2026-09.md") if os.path.exists(os.path.join(d, "CLAUDE_DECISIONS_2026-09.md")) else ""
    check("11 missing archive is created with the unit", rc == 0 and "wiped 40 rows" in ar and H in ar, out)
    shutil.rmtree(d)


def t12_drop_inside_a_rule_sentence_refused():
    claude = CLAUDE.replace("- **Keep the bucket name", "- Do not ship secrets. Old story.\n"
                            "- Only publish after approval. Older story.\n- **Keep the bucket name")
    d = setup(claude=claude)
    rc, out = run(d, {"cuts": [cut("- Do not ship", ["not "])]})
    check("12 dropping 'not ' from a rule refuses (3)",
          rc == 3 and "Do not ship secrets" in out and "would not survive" in out, out)
    rc, out = run(d, {"cuts": [cut("- Only publish", ["Only publish after approval. "])]})
    check("12 dropping an 'Only ...' rule sentence refuses (3)", rc == 3 and "would not survive" in out, out)
    rc, out = run(d, {"cuts": [cut("- Do not ship", [" Old story."])]})
    check("12 control: dropping the story beside the rule passes", rc == 0, out)
    bold = CLAUDE.replace("- **Keep the bucket name", "- **Never cut a block in half.** Found on a Monday.\n"
                          "- **Keep the bucket name")
    d2 = setup(claude=bold)
    rc, out = run(d2, {"cuts": [cut("- **Never cut", [" Found on a Monday."])]})
    check("12 a bold rule ending '.**' is its own sentence: the story after it can go", rc == 0, out)
    shutil.rmtree(d2)
    shutil.rmtree(d)


def t13_spec_types_are_checked():
    d = setup()
    for label, spec in [
            ("allow_rule_edit as the string \"false\"", {"cuts": [dict(C_BULLET, allow_rule_edit="false")]}),
            ("a null cut", {"cuts": [None]}),
            ("a null archive", {"cuts": [dict(C_BULLET, archive=None)]}),
            ("an unknown key (the old allow_rule_words)", {"cuts": [dict(C_BULLET, allow_rule_words=True)]}),
            ("a non-string drop", {"cuts": [dict(C_BULLET, drops=[3])]}),
            ("a pointer missing its line", {"cuts": [C_BULLET], "pointer": {"after": "x"}})]:
        rc, out = run(d, spec)
        check("13 %s is exit 2, no traceback" % label, rc == 2 and "Traceback" not in out, out)
    check("13 nothing written", unchanged(d))
    shutil.rmtree(d)


def t14_four_backtick_fence_holds_a_three_backtick_line():
    claude = CLAUDE.replace("```text\n## not a heading, inside a fence\n```",
                            "````md\n```\n## Example\n```\n````")
    d = setup(claude=claude)
    rc, out = run(d, {"cuts": [cut("- **After the fence.**", [" Written after lunch."])]})
    check("14 a '## ' line inside a four-backtick fence is not a section", rc == 0, out)
    shutil.rmtree(d)


def t15_already_archived_only_under_the_same_heading():
    old = ("- **Run the export with `--dry` first.** The first run wiped 40 rows by\n"
           "  accident. Then run it for real.")
    d = setup(archive=ARCHIVE + "\n## Unrelated section\n\n" + old + "\n")
    rc, out = run(d, {"cuts": [C_BULLET]}, "--write")
    ar = read(d, "CLAUDE_DECISIONS_2026-09.md")
    check("15 the same text under ANOTHER heading does not count as archived",
          rc == 0 and "already archived: 0" in out and ar.count(old) == 2
          and ar.index(H) < ar.rindex(old), out + ar)
    shutil.rmtree(d)


def t16_pointer_inside_a_fence_does_not_count():
    claude = CLAUDE.replace("```text\n## not a heading, inside a fence\n```",
                            "```text\n" + POINTER["line"] + "\n```")
    d = setup(claude=claude)
    rc, out = run(d, {"cuts": [C_BULLET], "pointer": POINTER}, "--write")
    cm = read(d, "CLAUDE.md")
    check("16 a pointer line seen only inside a fence is still added for real",
          rc == 0 and POINTER["after"] + "\n" + POINTER["line"] + "\n" in cm, out + cm)
    shutil.rmtree(d)


GUTTED = "- Never merge on Friday afternoons because the deploy team is away. It broke twice.\n"
C_GUT = cut("- Never merge", [" on Friday afternoons because the deploy team is away. It broke twice."],
            allow_rule_edit=True)


def t17_loss_check_refuses_a_gutted_rule_unless_waived():
    claude = CLAUDE.replace("- **Keep the bucket name", GUTTED + "- **Keep the bucket name")
    d = setup(claude=claude)
    rc, out = run(d, {"cuts": [C_GUT]}, "--write")
    check("17 a rule unit emptied under allow_rule_edit is refused by the loss check (3)",
          rc == 3 and "loss check: an item would be lost" in out and "Never merge on Friday" in out, out)
    check("17 nothing written", read(d, "CLAUDE.md") == claude
          and read(d, "CLAUDE_DECISIONS_2026-09.md") == ARCHIVE)
    rc, out = run(d, {"cuts": [C_GUT]}, "--write", "--accept", "Never merge on Friday")
    check("17 an --accept waiver lets it through and is reported",
          rc == 0 and "let through 1 item" in out and "- Never merge\n" in read(d, "CLAUDE.md"), out)
    shutil.rmtree(d)


def t18_pointer_check_refuses_a_cut_that_breaks_a_pointer():
    claude = CLAUDE.replace("- **Keep the bucket name",
                            "- **Keep runs short.** The logs went to `runs/`.\n"
                            "- Detail in `notes.md`.\n- **Keep the bucket name")
    d = setup(claude=claude)
    os.mkdir(os.path.join(d, "runs"))
    with open(os.path.join(d, "runs", "notes.md"), "w", encoding="utf-8") as fh:
        fh.write("x\n")
    c = cut("- **Keep runs short.**", [" The logs went to `runs/`."])
    rc, out = run(d, {"cuts": [c]}, "--write", "--root", d)
    check("18 dropping the folder a later pointer resolves through is refused (3)",
          rc == 3 and "adds an unresolved pointer: notes.md" in out, out)
    check("18 nothing written", read(d, "CLAUDE.md") == claude)
    p = dict(POINTER, line="- See `CLAUDE_DECISIONS_2026-02.md`, same heading.")
    rc, out = run(d, {"cuts": [C_BULLET], "pointer": p}, "--root", d)
    check("18 a shared pointer line naming a missing archive is refused (3)",
          rc == 3 and "adds an unresolved pointer: CLAUDE_DECISIONS_2026-02.md" in out, out)
    shutil.rmtree(d)


def t19_old_unresolved_pointer_is_counted_not_refused():
    claude = CLAUDE.replace("- A line nobody edits.", "- A line nobody edits. See `gone.md`.")
    d = setup(claude=claude)
    rc, out = run(d, {"cuts": [C_BULLET]}, "--root", d)
    check("19 control: a pointer broken before the cut does not block",
          rc == 0 and "pointer check: unresolved 1 before, 1 after, none new" in out, out)
    rc, out = run(d, {"cuts": [C_BULLET]}, "--accept", "")
    check("19 an empty --accept is exit 2", rc == 2 and "CANNOT TELL" in out, out)
    shutil.rmtree(d)


def t20_symlinked_archive_refused():
    d = setup(archive=None)
    with open(os.path.join(d, "history.md"), "w", encoding="utf-8") as fh:
        fh.write(ARCHIVE)
    os.symlink("history.md", os.path.join(d, "CLAUDE_DECISIONS_2026-09.md"))
    rc, out = run(d, {"cuts": [C_BULLET]}, "--write")
    check("20 an archive that is a symlink is refused (3)",
          rc == 3 and "is a symlink: CLAUDE_DECISIONS_2026-09.md" in out, out)
    check("20 nothing written, the link kept", read(d, "CLAUDE.md") == CLAUDE
          and os.path.islink(os.path.join(d, "CLAUDE_DECISIONS_2026-09.md"))
          and read(d, "history.md") == ARCHIVE)
    shutil.rmtree(d)


def t21_missing_root_cannot_tell():
    d = setup()
    rc, out = run(d, {"cuts": [C_BULLET]}, "--write", "--root", os.path.join(d, "no-such-folder"))
    check("21 a --root that does not exist is exit 2",
          rc == 2 and "--root folder missing" in out and "Traceback" not in out, out)
    check("21 nothing written", unchanged(d))
    shutil.rmtree(d)


def t22_check_read_errors_cannot_tell():
    d = setup()
    notes = os.path.join(d, "NOTES.md")
    with open(notes, "w", encoding="utf-8") as fh:
        fh.write("notes\n")
    os.chmod(notes, 0)
    rc, out = run(d, {"cuts": [C_BULLET]}, "--write")
    os.chmod(notes, 0o600)
    check("22 an unreadable notes file is exit 2, no traceback",
          rc == 2 and "could not read" in out and "NOTES.md" in out and "Traceback" not in out, out)
    check("22 nothing written, no backup", unchanged(d) and not any(
        ".backup-before-split-" in n for n in os.listdir(d)))
    shutil.rmtree(d)
    # plan() splits on "\n" only; the loss check's splitlines() also splits on U+2028
    claude = CLAUDE.replace("- A line nobody edits.", "- A line nobody edits.\u2028```")
    d = setup(claude=claude)
    rc, out = run(d, {"cuts": [C_BULLET]}, "--write")
    check("22 a fence only the checks' line reader sees is exit 2, no traceback",
          rc == 2 and "never closes" in out and "Traceback" not in out, out)
    check("22 nothing written", read(d, "CLAUDE.md") == claude)
    shutil.rmtree(d)


def main():
    for name, fn in sorted(globals().items()):
        if name.startswith("t") and name[1:3].isdigit() and callable(fn):
            fn()
    ok = sum(1 for _, r in RESULTS if r)
    print("%d/%d passed" % (ok, len(RESULTS)))
    return 0 if ok == len(RESULTS) else 1


if __name__ == "__main__":
    sys.exit(main())
