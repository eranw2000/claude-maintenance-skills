#!/usr/bin/env python3
"""Offline tests for build_comparison_sheet.py: input validation, the markdown twin, and
the shape of the Sheets requests. No network, no token.

    python3 test_build_comparison_sheet.py
"""
import importlib.util
import json
import pathlib
import sys
import tempfile
import unittest

HERE = pathlib.Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("bcs", HERE / "build_comparison_sheet.py")
bcs = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bcs)


def sample():
    return {
        "title": "Skill comparison: theirs vs ours", "built": "2026-10-17",
        "theirs": {"name": "Their skill", "source": "https://example.invalid/skill"},
        "mine": {"name": "Our /improve-dev-workflow", "source": "skills/x/SKILL.md"},
        "rows": [
            {"feature": "When it runs", "theirs": "By hand.", "mine": "By itself.",
             "action": "Keep mine", "notes": "Ours fires while the miss is fresh."},
            {"feature": "Session log", "theirs": "Reads it.", "mine": "Does not name it.",
             "action": "Enhance", "notes": "One line in Observe."},
            {"feature": "Size", "theirs": "4.4K", "mine": "20.8K",
             "action": "Change", "notes": "Split it."},
            {"feature": "Packaging for another tool", "theirs": "openai.yaml", "mine": "None.",
             "action": "Nothing to do",
             "notes": "Searched: openai, yaml, agents.md in skills, agents, hooks: 0 hits."},
        ],
        "suggested_order": ["1. Change: split (row 3).", "2. Enhance: session log (row 2)."],
    }


def write(data):
    tmp = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False)
    json.dump(data, tmp)
    tmp.close()
    return tmp.name


class Load(unittest.TestCase):
    def test_valid_file_loads_and_counts(self):
        data = bcs.load(write(sample()))
        self.assertEqual(bcs.counts(data),
                         {"Enhance": 1, "Change": 1, "Keep mine": 1, "Nothing to do": 1})
        self.assertEqual(bcs.headers(data),
                         ["#", "Feature", "Their skill", "Our /improve-dev-workflow",
                          "Action", "Notes"])

    def test_bad_action_exits_2_naming_the_row(self):
        data = sample()
        data["rows"][1]["action"] = "Maybe"
        with self.assertRaises(SystemExit) as ctx:
            bcs.load(write(data))
        self.assertIn("row 2", str(ctx.exception))
        self.assertIn("Maybe", str(ctx.exception))

    def test_empty_feature_exits(self):
        data = sample()
        data["rows"][0]["feature"] = "  "
        with self.assertRaises(SystemExit) as ctx:
            bcs.load(write(data))
        self.assertIn("row 1", str(ctx.exception))

    def test_missing_row_key_exits(self):
        data = sample()
        del data["rows"][2]["notes"]
        with self.assertRaises(SystemExit) as ctx:
            bcs.load(write(data))
        self.assertIn("notes", str(ctx.exception))

    def test_side_without_name_exits(self):
        data = sample()
        data["mine"] = {"source": "x"}
        with self.assertRaises(SystemExit):
            bcs.load(write(data))

    def test_json_null_exits_with_a_message_not_a_traceback(self):
        with self.assertRaises(SystemExit) as ctx:
            bcs.load(write(None))
        self.assertIn("object", str(ctx.exception))

    def test_a_null_row_exits_naming_the_row(self):
        data = sample()
        data["rows"][1] = None
        with self.assertRaises(SystemExit) as ctx:
            bcs.load(write(data))
        self.assertIn("row 2", str(ctx.exception))

    def test_a_non_text_cell_exits_naming_the_row(self):
        data = sample()
        data["rows"][0]["theirs"] = ["a", "list"]
        with self.assertRaises(SystemExit) as ctx:
            bcs.load(write(data))
        self.assertIn("row 1", str(ctx.exception))

    def test_a_numeric_suggested_order_exits_before_any_sheet(self):
        data = sample()
        data["suggested_order"] = 3
        with self.assertRaises(SystemExit) as ctx:
            bcs.load(write(data))
        self.assertIn("suggested_order", str(ctx.exception))

    def test_a_string_side_exits(self):
        data = sample()
        data["theirs"] = "Their skill"
        with self.assertRaises(SystemExit):
            bcs.load(write(data))

    def test_an_absence_claim_without_its_search_exits_naming_the_row(self):
        # A row that says ours lacks a table, with no search named.
        data = sample()
        data["rows"].append({"feature": "A risk table", "theirs": "One row per risk.",
                             "mine": "Ours names risks in one line. No separate table.",
                             "action": "Enhance", "notes": "Nice-to-have."})
        with self.assertRaises(SystemExit) as ctx:
            bcs.load(write(data))
        self.assertIn("row 5", str(ctx.exception))
        self.assertIn("Searched:", str(ctx.exception))

    def test_a_none_cell_needs_its_search_too(self):
        data = sample()
        data["rows"][3]["notes"] = ""
        with self.assertRaises(SystemExit) as ctx:
            bcs.load(write(data))
        self.assertIn("row 4", str(ctx.exception))

    def test_not_covered_and_missing_are_absence_claims_too(self):
        for cell in ("Not covered.", "Partly. Missing in ours."):
            data = sample()
            data["rows"][0]["mine"] = cell
            with self.assertRaises(SystemExit, msg=cell):
                bcs.load(write(data))

    def test_a_cell_that_claims_no_absence_needs_no_search(self):
        data = sample()
        data["rows"][3]["mine"] = "Covered by skills/x/reference/pack.md; nothing to add."
        data["rows"][3]["notes"] = ""
        bcs.load(write(data))

    def test_control_a_good_file_does_not_exit(self):
        bcs.load(write(sample()))  # the checks above fire only on the broken input


class Markdown(unittest.TestCase):
    def test_every_row_and_count_is_in_the_twin(self):
        data = bcs.load(write(sample()))
        md = bcs.render_md(data, "SHEETID")
        for i, row in enumerate(data["rows"], 1):
            self.assertIn(f"### {i}. {row['feature']}", md)
            self.assertIn(f"- Action: {row['action']}", md)
        self.assertIn("Enhance 1, Change 1, Keep mine 1, Nothing to do 1", md)
        self.assertIn("spreadsheets/d/SHEETID/edit", md)
        self.assertIn("1. Change: split (row 3).", md)
        self.assertNotIn("- Notes: \n", md)  # an empty note writes no Notes line

    def test_no_sheet_yet_is_said(self):
        md = bcs.render_md(bcs.load(write(sample())), "")
        self.assertIn("Sheet: not built yet", md)


class Requests(unittest.TestCase):
    def test_grid_has_header_plus_one_row_per_feature(self):
        data = bcs.load(write(sample()))
        rows = bcs.comparison_rows(data)
        self.assertEqual(len(rows), len(data["rows"]) + 1)
        self.assertEqual([c["userEnteredValue"]["stringValue"] for c in rows[0]],
                         bcs.headers(data))
        self.assertEqual(rows[3][4]["userEnteredValue"]["stringValue"], "Change")

    def test_action_column_is_a_strict_dropdown_with_four_colours(self):
        reqs = bcs.action_column(7, n_rows=4)
        dv = reqs[0]["setDataValidation"]
        self.assertEqual(dv["range"], {"sheetId": 7, "startRowIndex": 1, "endRowIndex": 5,
                                       "startColumnIndex": 4, "endColumnIndex": 5})
        self.assertEqual(dv["rule"]["condition"]["type"], "ONE_OF_LIST")
        self.assertEqual([v["userEnteredValue"] for v in dv["rule"]["condition"]["values"]],
                         bcs.ACTIONS)
        self.assertTrue(dv["rule"]["strict"] and dv["rule"]["showCustomUi"])
        colours = [r for r in reqs if "addConditionalFormatRule" in r]
        self.assertEqual(len(colours), 4)
        self.assertEqual(
            [r["addConditionalFormatRule"]["rule"]["booleanRule"]["condition"]["values"][0]
             ["userEnteredValue"] for r in colours], bcs.ACTIONS)
        self.assertIn("setBasicFilter", reqs[-1])

    def test_rewrite_clears_old_colour_rules_and_the_freeze_before_the_shrink(self):
        reqs = bcs.rewrite(3, [[bcs.cell("a")], [bcs.cell("b")]], [], 1, 0, old_cf_count=4)
        self.assertEqual(sum(1 for r in reqs if "deleteConditionalFormatRule" in r), 4)
        kinds = [next(iter(r)) for r in reqs]
        props = [r["updateSheetProperties"]["properties"]["gridProperties"]
                 for r in reqs if "updateSheetProperties" in r]
        self.assertEqual(props[0], {"frozenRowCount": 0, "frozenColumnCount": 0})
        self.assertEqual(props[1], {"rowCount": 1})
        self.assertEqual(props[2]["rowCount"], 2)
        self.assertLess(kinds.index("updateSheetProperties"), kinds.index("updateCells"))
        self.assertNotIn("deleteSheet", kinds)

    def test_updated_rows_add_a_last_column_to_grid_filter_and_twin(self):
        data = sample()
        data["rows"][1]["updated"] = "skills/x/SKILL.md step 1"
        data = bcs.load(write(data))
        self.assertEqual(bcs.headers(data)[-1], "Feature updated")
        rows = bcs.comparison_rows(data)
        self.assertTrue(all(len(r) == 7 for r in rows))
        self.assertEqual(rows[2][6]["userEnteredValue"]["stringValue"], "skills/x/SKILL.md step 1")
        self.assertEqual(rows[1][6]["userEnteredValue"]["stringValue"], "")
        self.assertIn((6, 7, 330), bcs.widths(data))
        flt = bcs.action_column(7, 4, len(bcs.headers(data)))[-1]["setBasicFilter"]
        self.assertEqual(flt["filter"]["range"]["endColumnIndex"], 7)
        md = bcs.render_md(data, "SHEETID")
        self.assertIn("- Feature updated: skills/x/SKILL.md step 1", md)
        self.assertEqual(md.count("- Feature updated:"), 1)

    def test_control_no_updated_key_keeps_six_columns(self):
        data = bcs.load(write(sample()))
        self.assertEqual(len(bcs.headers(data)), 6)
        self.assertTrue(all(len(r) == 6 for r in bcs.comparison_rows(data)))
        self.assertEqual(bcs.widths(data), bcs.WIDTHS)
        self.assertNotIn("Feature updated", bcs.render_md(data, ""))

    def test_a_non_text_updated_exits_naming_the_row(self):
        data = sample()
        data["rows"][2]["updated"] = ["a list"]
        with self.assertRaises(SystemExit) as ctx:
            bcs.load(write(data))
        self.assertIn("row 3", str(ctx.exception))

    def test_summary_lists_counts_and_meanings(self):
        data = bcs.load(write(sample()))
        text = [c["userEnteredValue"]["stringValue"] for row in bcs.summary_rows(data) for c in row]
        for a in bcs.ACTIONS:
            self.assertIn(a, text)
            self.assertIn(bcs.ACTION_MEANING[a], text)
        self.assertIn("1. Change: split (row 3).", text)


if __name__ == "__main__":
    unittest.main(verbosity=1)
