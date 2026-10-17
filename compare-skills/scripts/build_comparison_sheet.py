#!/usr/bin/env python3
"""Build, or rewrite in place, the Google Sheet of a skill comparison (one feature per row),
and write its markdown twin.

    python3 build_comparison_sheet.py <rows.json> --out-dir <folder> --md-only   # markdown only
    python3 build_comparison_sheet.py <rows.json> --out-dir <folder>             # markdown + Sheet

--md-only needs nothing beyond Python. The Sheet needs google-api-python-client and a token
made once with mint_sheets_token.py beside this file (default
~/.claude/google-oauth/sheets_token.json, or the COMPARE_SKILLS_SHEETS_TOKEN variable). The
spreadsheet id is kept in <folder>/sheet_id.txt, so a re-run rewrites the SAME Sheet and the
link holds.

rows.json:
    {"title": "...", "built": "YYYY-MM-DD",
     "theirs": {"name": "<column label>", "source": "<link>"},
     "mine":   {"name": "<column label>", "source": "<path>"},
     "rows": [{"feature": "", "theirs": "", "mine": "", "action": "Enhance", "notes": ""}],
     "suggested_order": ["1. ..."]}
action is one of: Enhance, Change, Keep mine, Nothing to do.

Tabs: `Comparison` (header frozen, column E a dropdown with a fill colour per action, a
filter over the table) and `Summary` (sources, counts, what each word means, suggested
order). The request sequence (clear the freeze first, drop and regrow the rows, never delete
a tab, delete old conditional-format rules before adding) is not style: each rule was
measured against the Sheets API.

Exit 0 ok; 2 bad input (the message names the row); 1 when Google refuses a request.
"""
import argparse
import json
import os
import sys
from pathlib import Path

TOKEN = os.path.expanduser(os.environ.get("COMPARE_SKILLS_SHEETS_TOKEN",
                                         "~/.claude/google-oauth/sheets_token.json"))
GRID_TAB, SUMMARY_TAB = "Comparison", "Summary"

ENHANCE, CHANGE, KEEP, NOTHING = "Enhance", "Change", "Keep mine", "Nothing to do"
ACTIONS = [ENHANCE, CHANGE, KEEP, NOTHING]
ACTION_FILL = {ENHANCE: "D9EAD3", CHANGE: "FCE5CD", KEEP: "CFE2F3", NOTHING: "EFEFEF"}
ACTION_MEANING = {
    ENHANCE: "Add this from their skill to ours.",
    CHANGE: "Ours should change how it does this.",
    KEEP: "Ours is better, or their version does not fit. Leave it as is.",
    NOTHING: "Both are equal, or another artifact of ours already owns it.",
}
WIDTHS = [(0, 1, 40), (1, 2, 190), (2, 3, 330), (3, 4, 330), (4, 5, 130), (5, 6, 400)]
ROW_KEYS = ("feature", "theirs", "mine", "action", "notes")


# ---------------------------------------------------------------- input

def load(path):
    """Read and validate rows.json; a bad file exits 2 naming the first wrong thing."""
    try:
        data = json.loads(Path(path).read_text())
    except (OSError, ValueError) as exc:
        sys.exit(f"cannot read {path}: {type(exc).__name__}")
    if not isinstance(data, dict):
        sys.exit("rows.json: the top level must be an object")
    for key in ("title", "built", "theirs", "mine", "rows"):
        if key not in data:
            sys.exit(f"rows.json: missing top-level key {key!r}")
    for key in ("title", "built"):
        if not isinstance(data[key], str) or not data[key].strip():
            sys.exit(f"rows.json: {key!r} must be non-empty text")
    for side in ("theirs", "mine"):
        if not isinstance(data[side], dict) or not isinstance(data[side].get("name"), str) \
                or not data[side]["name"].strip():
            sys.exit(f"rows.json: {side!r} needs a 'name' (the column label)")
        if not isinstance(data[side].get("source", ""), str):
            sys.exit(f"rows.json: {side!r} 'source' must be text")
    if not isinstance(data["rows"], list) or not data["rows"]:
        sys.exit("rows.json: 'rows' must be a non-empty list")
    for i, row in enumerate(data["rows"], 1):
        if not isinstance(row, dict):
            sys.exit(f"rows.json: row {i} must be an object")
        for key in ROW_KEYS:
            if key not in row:
                sys.exit(f"rows.json: row {i} lacks {key!r}")
            if not isinstance(row[key], str):
                sys.exit(f"rows.json: row {i} {key!r} must be text")
        if not row["feature"].strip():
            sys.exit(f"rows.json: row {i} has an empty feature")
        if row["action"] not in ACTIONS:
            sys.exit(f"rows.json: row {i} action {row['action']!r} is not one of {ACTIONS}")
    order = data.setdefault("suggested_order", [])
    if not isinstance(order, list) or not all(isinstance(x, str) for x in order):
        sys.exit("rows.json: 'suggested_order' must be a list of text lines")
    return data


def headers(data):
    return ["#", "Feature", data["theirs"]["name"], data["mine"]["name"], "Action", "Notes"]


def counts(data):
    return {a: sum(1 for r in data["rows"] if r["action"] == a) for a in ACTIONS}


# ---------------------------------------------------------------- cells

def rgb(hex6):
    return {"red": int(hex6[0:2], 16) / 255, "green": int(hex6[2:4], 16) / 255,
            "blue": int(hex6[4:6], 16) / 255}


BORDER = {"style": "SOLID", "width": 1, "color": rgb("BFBFBF")}
BORDERS = {"top": BORDER, "bottom": BORDER, "left": BORDER, "right": BORDER}


def cell(value, *, bold=False, italic=False, size=10, colour=None, fill=None,
         halign="LEFT", valign="TOP", borders=True):
    fmt = {"textFormat": {"bold": bold, "italic": italic, "fontSize": size},
           "horizontalAlignment": halign, "verticalAlignment": valign,
           "wrapStrategy": "WRAP"}
    if colour:
        fmt["textFormat"]["foregroundColor"] = rgb(colour)
    if fill:
        fmt["backgroundColor"] = rgb(fill)
    if borders:
        fmt["borders"] = BORDERS
    return {"userEnteredValue": {"stringValue": "" if value is None else str(value)},
            "userEnteredFormat": fmt}


def comparison_rows(data):
    out = [[cell(h, bold=True, colour="FFFFFF", fill="1F3864", valign="MIDDLE")
            for h in headers(data)]]
    for i, row in enumerate(data["rows"], 1):
        out.append([cell(i, bold=True, halign="CENTER"), cell(row["feature"], bold=True),
                    cell(row["theirs"]), cell(row["mine"]),
                    cell(row["action"], bold=True, halign="CENTER", valign="MIDDLE"),
                    cell(row["notes"])])
    return out


def summary_rows(data):
    c = counts(data)
    band = lambda t: [cell(t, bold=True, colour="FFFFFF", fill="1F3864"),  # noqa: E731
                      cell("", fill="1F3864")]
    blank = lambda: [cell("", borders=False), cell("", borders=False)]  # noqa: E731
    rows = [
        [cell(data["title"], bold=True, size=14, borders=False), cell("", borders=False)],
        [cell("Built", bold=True), cell(f"{data['built']}, by Claude")],
        [cell(data["theirs"]["name"], bold=True), cell(data["theirs"].get("source", ""))],
        [cell(data["mine"]["name"], bold=True), cell(data["mine"].get("source", ""))],
        [cell("Rows", bold=True), cell(str(len(data["rows"])))],
        blank(), band("Action counts"),
    ]
    rows += [[cell(a, bold=True, fill=ACTION_FILL[a]), cell(str(c[a]))] for a in ACTIONS]
    rows += [blank(), band("What the action words mean")]
    rows += [[cell(a, bold=True, fill=ACTION_FILL[a]), cell(ACTION_MEANING[a])] for a in ACTIONS]
    if data["suggested_order"]:
        rows += [blank(), band("Suggested order, if you say yes")]
        rows += [[cell("", borders=False), cell(line)] for line in data["suggested_order"]]
    return rows


# ---------------------------------------------------------------- requests

def rewrite(sheet_id, rows, widths, frozen_rows, frozen_cols, old_cf_count):
    """Replace a tab's contents in place (same tab id, so the link holds).

    Order matters, each rule measured on the Sheets API: clear the freeze in its own
    request BEFORE the shrink; drop and regrow the rows so no row keeps a fixed height
    (Google's fit-rows request is inert for wrapped text); never delete the tab.
    Conditional-format rules are deleted from index 0, old_cf_count times, or a re-run
    stacks a second copy of each rule.
    """
    height, width = len(rows), max(len(r) for r in rows)
    reqs = [{"deleteConditionalFormatRule": {"sheetId": sheet_id, "index": 0}}
            for _ in range(old_cf_count)]
    reqs += [
        {"clearBasicFilter": {"sheetId": sheet_id}},
        {"unmergeCells": {"range": {"sheetId": sheet_id}}},
        {"setDataValidation": {"range": {"sheetId": sheet_id}}},  # no rule = clear
        {"updateSheetProperties": {
            "properties": {"sheetId": sheet_id,
                           "gridProperties": {"frozenRowCount": 0, "frozenColumnCount": 0}},
            "fields": "gridProperties.frozenRowCount,gridProperties.frozenColumnCount"}},
        {"updateSheetProperties": {
            "properties": {"sheetId": sheet_id, "gridProperties": {"rowCount": 1}},
            "fields": "gridProperties.rowCount"}},
        {"updateSheetProperties": {
            "properties": {"sheetId": sheet_id,
                           "gridProperties": {"rowCount": height, "columnCount": width,
                                              "frozenRowCount": frozen_rows,
                                              "frozenColumnCount": frozen_cols}},
            "fields": ("gridProperties.rowCount,gridProperties.columnCount,"
                       "gridProperties.frozenRowCount,gridProperties.frozenColumnCount")}},
        {"updateCells": {
            "rows": [{"values": r + [cell("", borders=False)] * (width - len(r))} for r in rows],
            "fields": "userEnteredValue,userEnteredFormat",
            "start": {"sheetId": sheet_id, "rowIndex": 0, "columnIndex": 0}}},
    ]
    for start, end, pixels in widths:
        reqs.append({"updateDimensionProperties": {
            "range": {"sheetId": sheet_id, "dimension": "COLUMNS",
                      "startIndex": start, "endIndex": end},
            "properties": {"pixelSize": pixels}, "fields": "pixelSize"}})
    return reqs


def action_column(sheet_id, n_rows, n_cols=6):
    """Dropdown plus a fill colour per action value on column E, data rows only."""
    rng = {"sheetId": sheet_id, "startRowIndex": 1, "endRowIndex": n_rows + 1,
           "startColumnIndex": 4, "endColumnIndex": 5}
    reqs = [{"setDataValidation": {
        "range": rng,
        "rule": {"condition": {"type": "ONE_OF_LIST",
                               "values": [{"userEnteredValue": a} for a in ACTIONS]},
                 "strict": True, "showCustomUi": True,
                 "inputMessage": "Pick one: " + ", ".join(ACTIONS)}}}]
    for i, a in enumerate(ACTIONS):
        reqs.append({"addConditionalFormatRule": {
            "index": i,
            "rule": {"ranges": [rng],
                     "booleanRule": {"condition": {"type": "TEXT_EQ",
                                                   "values": [{"userEnteredValue": a}]},
                                     "format": {"backgroundColor": rgb(ACTION_FILL[a])}}}}})
    reqs.append({"setBasicFilter": {"filter": {"range": {
        "sheetId": sheet_id, "startRowIndex": 0, "endRowIndex": n_rows + 1,
        "startColumnIndex": 0, "endColumnIndex": n_cols}}}})
    return reqs


# ---------------------------------------------------------------- Sheets plumbing

def sheets_service():
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build
    if not os.path.isfile(TOKEN):
        sys.exit(f"no Sheets token at {TOKEN}; run mint_sheets_token.py beside this "
                 "file once, or use --md-only")
    # NO scopes= here: a refresh-token grant's scopes are fixed at consent time, and
    # passing a list makes the refresh fail on any scope that was never consented.
    return build("sheets", "v4", credentials=Credentials.from_authorized_user_file(TOKEN))


def open_or_create(svc, data, id_file):
    if id_file.is_file():
        sid = id_file.read_text().strip()
        meta = svc.spreadsheets().get(spreadsheetId=sid).execute()
        print(f"rewriting the existing Sheet {sid}")
    else:
        meta = svc.spreadsheets().create(body={
            "properties": {"title": data["title"]},
            "sheets": [{"properties": {"title": GRID_TAB, "index": 0}},
                       {"properties": {"title": SUMMARY_TAB, "index": 1}}]}).execute()
        sid = meta["spreadsheetId"]
        id_file.write_text(sid + "\n")
        print(f"created the Sheet {sid} and recorded its id in {id_file}")
    tabs = {s["properties"]["title"]: s["properties"]["sheetId"] for s in meta["sheets"]}
    cf = {s["properties"]["title"]: len(s.get("conditionalFormats", [])) for s in meta["sheets"]}
    for tab in (GRID_TAB, SUMMARY_TAB):
        if tab not in tabs:
            sys.exit(f"the Sheet {sid} has no tab named {tab!r}; it is not one this script made")
    return sid, tabs, cf


def sheet_url(sid):
    return f"https://docs.google.com/spreadsheets/d/{sid}/edit"


def read_back(svc, sid, data):
    """The one sanity check: the grid holds every row, and column E really is a dropdown."""
    n = len(data["rows"]) + 1
    got = svc.spreadsheets().values().get(
        spreadsheetId=sid, range=f"{GRID_TAB}!A1:F{n}").execute().get("values", [])
    assert got and got[0] == headers(data), f"header read back as {got[:1]}"
    assert len(got) == n, f"expected {n} rows, read {len(got)}"
    assert [r[4] for r in got[1:]] == [r["action"] for r in data["rows"]], "Action column differs"
    meta = svc.spreadsheets().get(spreadsheetId=sid, ranges=[f"{GRID_TAB}!E2:E2"],
                                  includeGridData=True).execute()
    sheet = meta["sheets"][0]
    dv = sheet["data"][0]["rowData"][0]["values"][0].get("dataValidation")
    assert dv and dv["condition"]["type"] == "ONE_OF_LIST", f"no dropdown on E2: {dv}"
    cf = len(sheet.get("conditionalFormats", []))
    assert cf == len(ACTIONS), f"expected {len(ACTIONS)} colour rules, found {cf}"
    return len(got) - 1, cf


# ---------------------------------------------------------------- markdown twin

def render_md(data, sid):
    c = counts(data)
    lines = [f"# {data['title']} ({data['built']})", "",
             f"{data['theirs']['name']}: {data['theirs'].get('source', '')}",
             f"{data['mine']['name']}: {data['mine'].get('source', '')}",
             f"Sheet: {sheet_url(sid) if sid else 'not built yet'}", "",
             "Action counts: " + ", ".join(f"{a} {c[a]}" for a in ACTIONS), "",
             "## What the action words mean", ""]
    lines += [f"- {a}: {ACTION_MEANING[a]}" for a in ACTIONS]
    if data["suggested_order"]:
        lines += ["", "## Suggested order, if you say yes", ""]
        lines += [f"- {s}" for s in data["suggested_order"]]
    lines += ["", "## Rows", ""]
    for i, row in enumerate(data["rows"], 1):
        lines += [f"### {i}. {row['feature']}", "",
                  f"- {data['theirs']['name']}: {row['theirs']}",
                  f"- {data['mine']['name']}: {row['mine']}",
                  f"- Action: {row['action']}"]
        if row["notes"]:
            lines.append(f"- Notes: {row['notes']}")
        lines.append("")
    return "\n".join(lines)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("rows", help="rows.json")
    ap.add_argument("--out-dir", required=True, help="folder for sheet_id.txt and COMPARISON.md")
    ap.add_argument("--md-only", action="store_true", help="write COMPARISON.md only, no network")
    args = ap.parse_args(argv)
    data = load(args.rows)
    out = Path(args.out_dir).expanduser()
    out.mkdir(parents=True, exist_ok=True)
    id_file, md_file = out / "sheet_id.txt", out / "COMPARISON.md"
    if args.md_only:
        sid = id_file.read_text().strip() if id_file.is_file() else ""
        md_file.write_text(render_md(data, sid))
        print(f"wrote {md_file}")
        return 0
    svc = sheets_service()
    sid, tabs, cf = open_or_create(svc, data, id_file)
    reqs = rewrite(tabs[GRID_TAB], comparison_rows(data), WIDTHS, 1, 2, cf[GRID_TAB])
    reqs += action_column(tabs[GRID_TAB], len(data["rows"]))
    reqs += rewrite(tabs[SUMMARY_TAB], summary_rows(data), [(0, 1, 220), (1, 2, 640)], 0, 0,
                    cf[SUMMARY_TAB])
    svc.spreadsheets().batchUpdate(spreadsheetId=sid, body={"requests": reqs}).execute()
    rows, rules = read_back(svc, sid, data)
    md_file.write_text(render_md(data, sid))
    c = counts(data)
    print(f"read back {rows} rows, dropdown on Action, {rules} colour rules")
    print("counts: " + ", ".join(f"{a} {c[a]}" for a in ACTIONS))
    print(f"wrote {md_file}")
    print(sheet_url(sid))
    return 0


if __name__ == "__main__":
    sys.exit(main())
