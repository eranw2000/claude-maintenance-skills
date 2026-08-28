#!/usr/bin/env python3
"""Survey a CLAUDE.md before splitting it.

Answers the measurement questions the skill's Phase A1, A2 and C1 ask, in one
call instead of a handful of greps: which heading convention this file actually
uses, how big every section is, what a proposed cut date would archive versus
keep, and which sections are Phase C extraction candidates.

Read-only. It never writes to the surveyed file.

Usage:
    survey.py <file> [--cut-date YYYY-MM-DD | --keep-days N] [--today YYYY-MM-DD]

The target file is a required argument and is echoed back in the header, so a
run can never quietly certify a file other than the one you meant. Stdlib only,
no f-string or PEP 604 syntax, so it runs on any python3 the machine offers.
"""

import argparse
import datetime
import os
import re
import sys

DATE_RE = re.compile(r"(\d{4}-\d{2}-\d{2})")

# Third convention: dated TOP-LEVEL BULLETS (`- Shipped (YYYY-MM-DD): ...`).
# A record bullet's date is PAREN-ANCHORED and must precede the line's first
# ':' when one exists. The paren anchor is THE discriminator against
# instance-row decoys: a Known Patterns section holds rows dated at line START
# with no paren (`- 2026-07-12 (\`hash\`...`), and a share floor alone CANNOT
# separate those (measured 95% of section chars on the real decoy), so never
# widen this to a bare date match. The colon rule kills bullets whose date is
# an incidental mid-line parenthetical after a `Label:` lead-in.
BULLET_DATE_RE = re.compile(r"\((\d{4}-\d{2}-\d{2})")
# A date RANGE in the parens marks a navigation pointer, not a record
# (`- **Older shipped entries archived** (2026-06-06 -> ...)`).
POINTER_RANGE_RE = re.compile(r"\(\d{4}-\d{2}-\d{2}\s*(->|\.\.)")
# A section qualifies as the records' home when at least this many record
# bullets cover at least this share of its chars.
BULLET_MIN_RECORDS = 2
BULLET_SHARE_FLOOR = 60

# Sections the skill's Phase C must never extract: active context, load-bearing
# terminology, or navigation aids.
DENY_SUBSTRINGS = [
    "project overview",
    "directory conventions",
    "finding historical context",
    "known patterns",
    "known issues",
    "decisions log",
    "custom skills",
]

# Claude Code warns past ~5% of the context window in characters, floor ~40000.
LARGE_FILE_CHARS = 40000

# Phase C candidate floor, from the skill: smaller sections are not worth the
# indirection.
CANDIDATE_LINES = 30
CANDIDATE_CHARS = 3000


# --- Shape classification (added 2026-08-12) -------------------------------
# Phase C extracts a WHOLE section and leaves a stub. That is right for a
# reference section and WRONG for a rule section: a rule moved out of an
# always-loaded file stops being read. Size alone cannot tell them apart, so
# classify shape and let Phase D handle rule-shaped sections instead.
#
# FAILS SAFE: reference-ness must be proven; anything else is called a rule.
# Calling a rule "reference" is the harmful direction; the reverse only costs a
# slightly smaller cut. Measured 2026-08-12 across both directions: 105/105 RULE
# on the pre-shrink global CLAUDE.md with zero false REFERENCE, 9/9 on
# DRAWIO_DIAGRAMS.md, 10/10 on RENDER_AND_DOCKER.md; and 5/6 REFERENCE on a real
# event-catalog file plus 9/16 on a commission-table CLAUDE.md, so it is a
# discriminator and not a constant.
OBLIGATION_RE = re.compile(
    r"\b(must|never|always|do not|don't|should|cannot|can't|"
    r"required|mandatory|forbidden)\b", re.I)
IMPERATIVE_RE = re.compile(
    r"^\s*(?:[-*]\s+)?(?:\*\*)?(Use|Run|Check|Verify|Assert|Keep|Write|Read|"
    r"Prefer|Never|Always|Do|Don't|Stop|Ask|Treat|Confirm|Name|State|Say|Add|"
    r"Remove|Strip|Apply|Avoid|Put|Set|Make|Give|Take|Start|Finish|Record|"
    r"Report|Scan|Grep|Measure|Test|Prove|Fix|Move|Split|Pin|Send|Call|Load|"
    r"Watch|Leave|Drop)\b")
TABLE_ROW_RE = re.compile(r"^\s*\|.*\|")
KV_ROW_RE = re.compile(r"^\s*[-*]\s+`[^`]+`\s*[:=-]")

# Measured retention: the 2026-08-11 global CLAUDE.md run compressed 41
# rule-shaped sections from 107,032 chars to 40,140 by moving evidence out and
# keeping every rule -- 37%. Used only to estimate the floor, never enforced.
RULE_RETENTION = 0.37

# --- Phase 0 detection (added 2026-08-24) ---------------------------------
# Phase 0 DELETES what the repository itself answers, instead of relocating it.
# The signal is a body dominated by path-like lines, directory-tree fences, or
# dependency pins. FAILS SAFE in the same direction as classify_shape: only
# REFERENCE-shaped sections are ever offered, because deleting a pitfall dressed
# as a file map is the harmful direction and keeping a directory tree for one
# more cycle is not.
PATHY_RE = re.compile(
    r"(^|\s|`)([~./]|[A-Za-z0-9_-]+/)[A-Za-z0-9_./-]*"
    r"\.(py|js|ts|tsx|jsx|md|json|ya?ml|toml|txt|cfg|ini|sh|sql|html|css)\b")
TREE_RE = re.compile(r"^\s*([|`+\\]--|\|   |\u251c|\u2514|\u2502)")
PIN_RE = re.compile(
    r"^\s*[-*]?\s*[\"'`]?[A-Za-z0-9_.-]+[\"'`]?\s*"
    r"(==|>=|<=|~=|\^|@)\s*[\"'`]?v?\d+\.")
PRUNE_SHARE = 0.35
PRUNE_MIN_HITS = 4

# Phase 0 has its OWN floor and its OWN safety test, and it must NOT borrow
# classify_shape's verdict. classify_shape proves REFERENCE-ness from STRUCTURE
# (tables and key-value rows) and fails safe to RULE for anything else, which is
# correct for Phases C and D. It makes Phase 0 blind, because a plain directory
# listing has no tables and no key-value rows, so it classifies RULE and the one
# phase built to delete file maps would never see a file map.
#
# What Phase 0 actually needs is the ABSENCE of obligations, not the presence of
# a table. So it tests that directly: positive derivable evidence, plus near-zero
# obligation and imperative density. That is what separates a directory listing
# from a pitfall that happens to be full of paths, which is the one deletion that
# would really hurt.
#
# Third instance in one session of the same error: reusing the previous phase's
# threshold or classifier because it is the number already in the file. See the
# PHASE_D_CHARS and PHASE_E_CHARS comments for the other two.
PHASE_0_CHARS = 200
PRUNE_MAX_OBLIGATION = 0.10
PRUNE_MAX_IMPERATIVE = 0.15

# --- Phase E detection (added 2026-08-24) ---------------------------------
# Phase E moves a FILE-TRIGGERED rule to .claude/rules/ with paths: frontmatter,
# so it leaves the always-loaded set without being deleted. A rule qualifies only
# when its trigger is a file, so the detector requires CONCENTRATED file-family
# vocabulary. A rule about a conversation scores zero here, which is the whole
# discriminator. Each family carries the globs to propose.
FILE_FAMILIES = [
    ("django", re.compile(
        r"\b(models\.py|admin\.py|views\.py|urls\.py|settings\.py|"
        r"migrations?\b|AppConfig|wsgi\.py|TransactionTestCase|django)\b", re.I),
     ["**/models.py", "**/admin.py", "**/views.py", "**/urls.py",
      "**/settings.py", "**/migrations/**"]),
    ("django-templates", re.compile(
        r"(\btemplates?/|\{%|\{\{\s*\w+\s*\}\})", re.I),
     ["**/templates/**"]),
    ("docker", re.compile(
        r"\b(Dockerfile|docker-compose|docker run|docker build|"
        r"python:3\.\d+-slim)\b", re.I),
     ["**/Dockerfile", "**/docker-compose*.yml", "**/*.dockerfile"]),
    ("render-yaml", re.compile(r"\brender\.yaml\b", re.I),
     ["**/render.yaml"]),
    ("drawio", re.compile(r"(\.drawio\b|\bdraw\.io\b|\brender\.py\b)", re.I),
     ["**/*.drawio", "**/render.py"]),
    ("docx", re.compile(r"(python-docx|\.docx\b)", re.I),
     ["**/*.docx", "**/*docx*.py"]),
    ("pptx", re.compile(r"(python-pptx|\.pptx\b)", re.I),
     ["**/*.pptx", "**/*pptx*.py", "**/*slide*.py"]),
    ("frontend", re.compile(
        r"(\.(css|scss|sass|jsx|tsx|vue|svelte)\b|\bstylesheet\b|"
        r"\bviewport\b|\bWCAG\b)", re.I),
     ["**/*.{css,scss,sass,html,htm,jsx,tsx,vue,svelte}"]),
    ("notebook", re.compile(r"\.ipynb\b", re.I), ["**/*.ipynb"]),
    ("sql", re.compile(r"(\.sql\b|\bCREATE TABLE\b|\bSELECT .*\bFROM\b)"),
     ["**/*.sql"]),
    ("deps", re.compile(
        r"\b(requirements\.txt|pyproject\.toml|package\.json|"
        r"poetry\.lock|package-lock\.json)\b", re.I),
     ["**/requirements*.txt", "**/pyproject.toml", "**/package.json"]),
]
SCOPE_MIN_HITS = 2
SCOPE_SHARE = 0.60

# Phase E has its OWN floor, and it is FAR lower than Phase D's. Phase D must
# RETAIN the rule, so a small rule barely compresses and is not worth touching.
# Phase E moves the WHOLE rule out of the always-loaded set, so a 200-char rule
# pays 200 chars in every session forever. Grouping is by FAMILY, so twelve small
# Django rules become ONE rules file and there is no per-rule indirection cost.
#
# Measured 2026-08-24 on the global CLAUDE.md: at Phase D's 900-char floor the
# detector found ZERO candidates on a file full of Django, Docker and draw.io
# rules, because Phase D had already compressed every one of them to a pointer
# under 900 chars. At this floor it finds 23 sections holding 9,238 chars. Same
# error the PHASE_D_CHARS comment records one phase earlier: reusing the previous
# phase's threshold because it is the number already in the file.
PHASE_E_CHARS = 100

# A rule that also talks ABOUT the conversation usually splits into a half that
# moves and a half that must stay. Flagged, never auto-excluded: the human
# applies the phase-e-path-scope.md E2/E3 test.
CONVO_RE = re.compile(
    r"\b(the user|ask (?:him|her|them|the user)|lead with|tell (?:him|her|them)|"
    r"report to|his call|her call|their call|in chat|conversation)\b", re.I)

# A rule that CHOOSES a tool, or decides whether to start something, fires BEFORE
# any matching file exists. Scoping it arms it exactly one step too late, which is
# the E2 exclusion. Measured 2026-08-24: this is what separates "draw.io is the
# default tool for all diagrams" (must stay) from "the draw.io grammar" (moves).
PREEMPTIVE_RE = re.compile(
    r"(\bdefault(?:s)? (?:tool|to|over)\b|\bunless \w+ asks\b|"
    r"\bwhenever a \w+ is needed\b|\bwhen(?:ever)? (?:someone|somebody|a user) "
    r"(?:asks|wants|requests)\b|\bbefore (?:you |any )?(?:creat|writ|open|start)"
    r"(?:e|ing)\b|\bdecide whether\b)", re.I)


# Phase D has its OWN, lower threshold than Phase C. Phase C's 3000-char floor
# exists because extracting a whole small section is not worth the indirection;
# Phase D only moves the evidence out, which pays off far sooner. Measured
# 2026-08-12: using Phase C's threshold for the floor predicted a 28% cut on the
# global CLAUDE.md when the real run achieved 51%, because ~28 sections between
# 900 and 3000 chars were counted as irreducible while they compressed fine.
PHASE_D_CHARS = 900


def classify_shape(body):
    """Return 'REFERENCE' or 'RULE' for a section body, plus its evidence."""
    lines = [l for l in body.split("\n")[1:] if l.strip()]
    if not lines:
        return "RULE", {}
    n = len(lines)
    tables = sum(1 for l in lines if TABLE_ROW_RE.match(l))
    kv = sum(1 for l in lines if KV_ROW_RE.match(l))
    imp = sum(1 for l in lines if IMPERATIVE_RE.match(l))
    obl = len(OBLIGATION_RE.findall(body))
    long_lines = sum(1 for l in lines if len(l) > 120)
    ref_score = (tables * 3 + kv * 2) / n
    rule_score = (imp * 2 + min(obl, n)) / n + (long_lines / n) * 0.5
    ev = {"tables": tables, "kv": kv, "imperatives": imp, "obligations": obl,
          "ref": round(ref_score, 2), "rule": round(rule_score, 2)}
    if (tables + kv) >= 3 and ref_score > rule_score and (obl / n) < 0.15:
        return "REFERENCE", ev
    return "RULE", ev


def prune_score(body):
    """Return (share, evidence) for how repo-derivable a section body looks."""
    lines = [l for l in body.split("\n")[1:] if l.strip()]
    if not lines:
        return 0.0, {}
    n = len(lines)
    pathy = sum(1 for l in lines if PATHY_RE.search(l))
    tree = sum(1 for l in lines if TREE_RE.match(l))
    pins = sum(1 for l in lines if PIN_RE.match(l))
    hits = pathy + tree + pins
    ev = {"path_lines": pathy, "tree_lines": tree, "pin_lines": pins,
          "lines": n, "share": round(hits / n, 2)}
    return hits / n, ev


def is_prune_candidate(section):
    """Derivable-looking AND carrying no obligations. Fails safe on obligations.

    Deliberately does NOT consult classify_shape; see the PHASE_0_CHARS comment.
    """
    body = section.get("body", "")
    share, ev = prune_score(body)
    hits = ev.get("path_lines", 0) + ev.get("tree_lines", 0) + ev.get("pin_lines", 0)
    if hits < PRUNE_MIN_HITS or share < PRUNE_SHARE:
        return None
    lines = [l for l in body.split("\n")[1:] if l.strip()]
    n = len(lines) or 1
    obl = len(OBLIGATION_RE.findall(body)) / n
    imp = sum(1 for l in lines if IMPERATIVE_RE.match(l)) / n
    if obl > PRUNE_MAX_OBLIGATION or imp > PRUNE_MAX_IMPERATIVE:
        return None
    ev["obligation_density"] = round(obl, 2)
    ev["imperative_density"] = round(imp, 2)
    return ev


def scope_candidate(section):
    """Return (family, globs, hits, share, mixed) when a RULE is file-triggered."""
    body = section.get("body", "")
    shape, _ = classify_shape(body)
    if shape != "RULE":
        return None
    counts = []
    for name, rx, globs in FILE_FAMILIES:
        c = len(rx.findall(body))
        if c:
            counts.append((c, name, globs))
    if not counts:
        return None
    counts.sort(reverse=True)
    top_c, top_name, top_globs = counts[0]
    total = sum(c for c, _, _ in counts)
    share = top_c / total
    if top_c < SCOPE_MIN_HITS or share < SCOPE_SHARE:
        return None
    mixed = bool(CONVO_RE.search(body))
    preemptive = bool(PREEMPTIVE_RE.search(body))
    return top_name, top_globs, top_c, round(share, 2), mixed, preemptive


def heading_level(line):
    """Return the markdown heading level of a line, or 0 if it is not one."""
    if not line.startswith("#"):
        return 0
    n = len(line) - len(line.lstrip("#"))
    if n == 0 or n >= len(line) or line[n] != " ":
        return 0
    return n


def collect(lines, level):
    """Return blocks for every heading at exactly `level`.

    A block ends at the next heading of the same level or shallower, which is
    what the skill means by an entry's boundary.
    """
    out = []
    starts = [i for i, ln in enumerate(lines) if heading_level(ln) == level]
    for i in starts:
        j = i + 1
        while j < len(lines):
            lv = heading_level(lines[j])
            if lv and lv <= level:
                break
            j += 1
        title = lines[i][level + 1:].strip()
        m = DATE_RE.search(lines[i])
        body = "\n".join(lines[i:j])
        out.append({
            "start": i + 1,
            "end": j,
            "title": title,
            "date": m.group(1) if m else None,
            "chars": len(body),
            "lines": j - i,
            "body": body,
        })
    return out


def bullet_records(lines, sec):
    """Dated top-level record bullets inside one level-2 section.

    A record starts with '- ' at column 0 and carries a paren-anchored date in
    its first physical line, before the line's first ':' when one exists; a
    date range in the parens marks a navigation pointer and is excluded. The
    extent runs to the next column-0 bullet or heading, so indented
    continuation lines ride along.
    """
    idxs = [k for k in range(sec["start"], sec["end"])
            if lines[k].startswith("- ")]
    bounds = idxs + [sec["end"]]
    out = []
    for n in range(len(idxs)):
        k = idxs[n]
        first = lines[k]
        m = BULLET_DATE_RE.search(first)
        if not m:
            continue
        colon = first.find(":")
        if colon != -1 and m.start() > colon:
            continue
        if POINTER_RANGE_RE.search(first):
            continue
        end = bounds[n + 1]
        for j in range(k + 1, end):
            if heading_level(lines[j]):
                end = j
                break
        body = "\n".join(lines[k:end])
        out.append({
            "start": k + 1,
            "end": end,
            "title": first[2:].strip(),
            "date": m.group(1),
            "chars": len(body),
            "lines": end - k,
        })
    return out


def detect_bullet_sections(lines, sections):
    """Sections that qualify as a dated-bullet records home, best first."""
    out = []
    for sec in sections:
        recs = bullet_records(lines, sec)
        if len(recs) < BULLET_MIN_RECORDS:
            continue
        ch = sum(r["chars"] for r in recs)
        share = 100 * ch // max(sec["chars"], 1)
        if share >= BULLET_SHARE_FLOOR:
            out.append({"section": sec, "records": recs,
                        "chars": ch, "share": share})
    out.sort(key=lambda b: -b["chars"])
    return out


def detect_convention(sections, entries, bullet_secs):
    """Pick the level the dated records live at, from the file's own evidence.

    Precedence is written down, not accidental: entry > section > bullet.
    Explicit heading conventions are deliberate structure; dated top-level
    bullets are the fallback shape.
    """
    n_sections = len([s for s in sections if s["date"]])
    n_entries = len([e for e in entries if e["date"]])
    if n_entries >= 2 and n_entries >= n_sections:
        return "entry", n_entries, n_sections
    if n_sections >= 2:
        return "section", n_entries, n_sections
    if bullet_secs:
        return "bullet", n_entries, n_sections
    return "none", n_entries, n_sections


def is_denied(title):
    low = title.lower()
    for d in DENY_SUBSTRINGS:
        if d in low:
            return True
    return False


def resolve_cut(args):
    """Return (cut_date, how) or (None, None) when no cut was requested."""
    if args.cut_date:
        return args.cut_date, "--cut-date"
    if args.keep_days is not None:
        base = args.today or datetime.date.today().isoformat()
        y, m, d = [int(x) for x in base.split("-")]
        cut = datetime.date(y, m, d) - datetime.timedelta(days=args.keep_days)
        return cut.isoformat(), "--keep-days " + str(args.keep_days) + " from " + base
    return None, None


def main(argv):
    ap = argparse.ArgumentParser(description="Survey a CLAUDE.md before splitting it.")
    ap.add_argument("file", help="path to the CLAUDE.md to survey (required)")
    ap.add_argument("--cut-date", help="entries strictly before this date would be archived")
    ap.add_argument("--keep-days", type=int, help="keep entries from the last N days")
    ap.add_argument("--today", help="override today's date, for reproducible runs")
    args = ap.parse_args(argv)

    if args.cut_date and args.keep_days is not None:
        sys.stderr.write("ERROR: pass --cut-date or --keep-days, not both\n")
        return 2

    path = os.path.abspath(args.file)
    if not os.path.isfile(path):
        sys.stderr.write("ERROR: not a file: " + path + "\n")
        return 2
    text = open(path, "r", encoding="utf-8", errors="replace").read()
    lines = text.split("\n")

    print("FILE      " + path)
    print("SIZE      " + str(len(text)) + " chars (python len, not bytes), "
          + str(len(lines)) + " lines"
          + ("  (over the ~" + str(LARGE_FILE_CHARS) + "-char warning threshold)"
             if len(text) > LARGE_FILE_CHARS else "  (under the warning threshold)"))

    sections = collect(lines, 2)
    entries = collect(lines, 3)
    print("READ      " + str(len(sections)) + " level-2 sections, "
          + str(len(entries)) + " level-3 entries")

    if not sections and not entries:
        print("")
        print("NO HEADINGS FOUND. This file has no '## ' or '### ' structure, so it is")
        print("not what the skill expects. Check you passed the right file.")
        print("SUMMARY convention=none dated=0 sections=0 archive=0 keep=0")
        return 2

    bullet_secs = detect_bullet_sections(lines, sections)
    convention, n_entries_dated, n_sections_dated = detect_convention(
        sections, entries, bullet_secs)
    print("")
    print("CONVENTION")
    print("  dated '### ' entries:   " + str(n_entries_dated))
    print("  dated '## ' sections:   " + str(n_sections_dated))
    print("  dated record bullets:   "
          + str(sum(len(b["records"]) for b in bullet_secs))
          + (" (in " + str(len(bullet_secs)) + " qualifying section(s))"
             if bullet_secs else ""))
    if convention == "entry":
        print("  verdict: records live at '### ' level (the skill's default shape).")
        records = [e for e in entries if e["date"]]
    elif convention == "section":
        print("  verdict: records are whole dated '## ' sections. This is a VARIANT:")
        print("  the skill's default '### YYYY-MM-DD:' regex finds nothing here, so")
        print("  Phase A must archive whole '## ' sections and say so in the index.")
        records = [s for s in sections if s["date"]]
    elif convention == "bullet":
        best = bullet_secs[0]
        print("  verdict: records are dated TOP-LEVEL BULLETS inside '## "
              + best["section"]["title"] + "' (" + str(len(best["records"]))
              + " records, " + str(best["share"]) + "% of the section).")
        print("  This is a VARIANT: Phase A archives whole bullets (SKILL.md A4")
        print("  bullet mode) and the index must record the convention.")
        for b in bullet_secs[1:]:
            print("  runner-up: '## " + b["section"]["title"] + "' ("
                  + str(len(b["records"])) + " records, " + str(b["share"])
                  + "%) -- NOT used; the verdict names ONE records section.")
        records = best["records"]
    else:
        print("  verdict: NO dated records found at any level.")
        print("  Phase A cannot run on this file. Phases B and C still can.")
        records = []

    if records:
        print("")
        print("DATED RECORDS (oldest first)")
        print("  date        chars   lines  line   title")
        for r in sorted(records, key=lambda r: (r["date"], r["start"])):
            print("  %-10s %6d  %5d  L%-5d %s"
                  % (r["date"], r["chars"], r["lines"], r["start"], r["title"][:70]))

    cut, how = resolve_cut(args)
    n_archive = 0
    n_keep = 0
    if cut and records:
        older = [r for r in records if r["date"] < cut]
        newer = [r for r in records if r["date"] >= cut]
        n_archive, n_keep = len(older), len(newer)
        print("")
        print("CUT ANALYSIS at " + cut + "  (" + how + ")")
        print("  archive: " + str(n_archive) + " records, "
              + str(sum(r["chars"] for r in older)) + " chars")
        print("  keep:    " + str(n_keep) + " records, "
              + str(sum(r["chars"] for r in newer)) + " chars")
        buckets = {}
        for r in older:
            buckets.setdefault(r["date"][:7], []).append(r)
        for month in sorted(buckets):
            rs = buckets[month]
            print("    CLAUDE_DECISIONS_" + month + ".md  <- " + str(len(rs))
                  + " records, " + str(sum(r["chars"] for r in rs)) + " chars")
        if n_archive == 0:
            print("  NOTE: this cut archives NOTHING. Either widen the window or skip")
            print("  Phase A rather than reporting a split that moved no content.")
    elif cut:
        print("")
        print("CUT ANALYSIS at " + cut + ": no dated records to split.")

    # Evidence-derived deny for Phase C: whatever HOLDS the dated records IS
    # the decisions log, whatever it is named. Name-keyed denial alone missed
    # a decisions log called 'Voice app essentials' and offered it for
    # extraction. Built from all three shapes regardless of the final verdict,
    # since denying is the safe direction and the human sees why.
    evidence_deny = set()
    for e in entries:
        if not e["date"]:
            continue
        for s in sections:
            if s["start"] < e["start"] and e["start"] <= s["end"]:
                evidence_deny.add(s["start"])
    for s in sections:
        if s["date"]:
            evidence_deny.add(s["start"])
    for b in bullet_secs:
        evidence_deny.add(b["section"]["start"])

    candidates = []
    denied = []
    denied_evidence = []
    for s in sections:
        if s["start"] in evidence_deny:
            denied_evidence.append(s)
        elif is_denied(s["title"]):
            denied.append(s)
        elif s["lines"] >= CANDIDATE_LINES or s["chars"] >= CANDIDATE_CHARS:
            candidates.append(s)
    # Phase 0 runs FIRST, so its candidates print first. Drawn from a LOWER
    # floor than Phase C: deleting pays off sooner than extracting, because a
    # deleted section is never surveyed, moved or verified again.
    prune_c = []
    for s in sections:
        if s["start"] in evidence_deny or is_denied(s["title"]):
            continue
        if s["chars"] < PHASE_0_CHARS:
            continue
        ev = is_prune_candidate(s)
        if ev:
            prune_c.append((s, ev))
    print("")
    print("PHASE 0 PRUNE CANDIDATES (dominated by content the repository itself")
    print("answers, carrying no obligations, at or over "
          + str(PHASE_0_CHARS) + " chars)")
    if prune_c:
        for s, ev in sorted(prune_c, key=lambda x: -x[0]["chars"]):
            print("  %6d ch  %4d ln  L%-5d %s"
                  % (s["chars"], s["lines"], s["start"], s["title"][:52]))
            print("             evidence: %d path lines, %d tree lines, %d pin"
                  " lines of %d (%d%%); obligations %.2f, imperatives %.2f"
                  % (ev["path_lines"], ev["tree_lines"], ev["pin_lines"],
                     ev["lines"], int(ev["share"] * 100),
                     ev["obligation_density"], ev["imperative_density"]))
        print("  These are CANDIDATES, not deletions. For each one, name the command")
        print("  whose output would replace it, RUN that command, and show the output")
        print("  beside the section. A command that returns nothing, errors, or")
        print("  disagrees with the section means NOT derivable: the section is")
        print("  stale or the repo has moved, and both are findings worth keeping.")
        print("  A section carrying obligations is excluded here by construction,")
        print("  which is what keeps a pitfall full of paths out of this list.")
    else:
        print("  none")

    print("")
    print("PHASE C CANDIDATES (undated sections at or over "
          + str(CANDIDATE_LINES) + " lines / " + str(CANDIDATE_CHARS) + " chars)")
    if candidates:
        for s in sorted(candidates, key=lambda s: -s["chars"]):
            shape, ev = classify_shape(s.get("body", ""))
            print("  %6d ch  %4d ln  %-9s L%-5d %s"
                  % (s["chars"], s["lines"], shape, s["start"], s["title"][:60]))
        n_rule = sum(1 for s in candidates
                     if classify_shape(s.get("body", ""))[0] == "RULE")
        print("  SHAPE decides the phase, size only qualifies. REFERENCE -> Phase C")
        print("  (extract the whole section, leave a stub). RULE -> Phase D (keep the")
        print("  rule, move only its evidence). Never Phase-C a RULE section: a rule")
        print("  moved out of an always-loaded file stops being read.")
        if n_rule == len(candidates):
            print("  NOTE: every candidate here is RULE-shaped, so Phase C has nothing")
            print("  to do on this file. Phase D is the lever.")
    else:
        print("  none")
    if denied:
        print("  never extract (deny list): "
              + ", ".join(s["title"][:40] for s in denied))
    if denied_evidence:
        print("  never extract (holds the dated records): "
              + ", ".join(s["title"][:40] for s in denied_evidence))

    ref_c = [s for s in candidates
             if classify_shape(s.get("body", ""))[0] == "REFERENCE"]
    ref_ids = set(id(s) for s in ref_c)
    # Phase D reaches every rule-shaped section over ITS threshold, not just the
    # Phase C candidates -- see PHASE_D_CHARS.
    rule_c = [s for s in sections
              if id(s) not in ref_ids
              and s["chars"] >= PHASE_D_CHARS
              and not is_denied(s["title"])
              and s["start"] not in evidence_deny
              and classify_shape(s.get("body", ""))[0] == "RULE"]
    touched = ref_ids | set(id(s) for s in rule_c)
    fixed = sum(s["chars"] for s in sections if id(s) not in touched)
    est = (fixed
           + int(sum(s["chars"] for s in rule_c) * RULE_RETENTION)
           + len(ref_c) * 120)
    # Phase E: which of the rule-shaped sections are FILE-triggered and can
    # leave the always-loaded set entirely without being deleted.
    rule_ids = set(id(s) for s in rule_c)
    scope_c = []
    for s in sections:
        if s["start"] in evidence_deny or is_denied(s["title"]):
            continue
        if s["chars"] < PHASE_E_CHARS:
            continue
        r = scope_candidate(s)
        if r:
            scope_c.append((s, r))
    print("")
    print("PHASE E SCOPE CANDIDATES (RULE-shaped, with concentrated file-family")
    print("vocabulary, so the trigger may be a FILE rather than a conversation)")
    if scope_c:
        fams = {}
        for s, r in scope_c:
            fams.setdefault(r[0], []).append((s, r))
        for fam in sorted(fams, key=lambda f: -sum(s["chars"] for s, _ in fams[f])):
            rows = fams[fam]
            print("  %s  ->  .claude/rules/%s.md   (%d rule%s, %d ch)"
                  % (fam, fam, len(rows), "" if len(rows) == 1 else "s",
                     sum(s["chars"] for s, _ in rows)))
            print("    paths: " + ", ".join(rows[0][1][1]))
            for s, r in sorted(rows, key=lambda x: -x[0]["chars"]):
                flag = "PREEMPT" if r[5] else ("MIXED  " if r[4] else "       ")
                print("    %6d ch  %2d hits %3d%%  %s L%-5d %s"
                      % (s["chars"], r[2], int(r[3] * 100), flag,
                         s["start"], s["title"][:38]))
        n_mixed = sum(1 for _, r in scope_c if r[4] and not r[5])
        n_pre = sum(1 for _, r in scope_c if r[5])
        if n_pre:
            print("  %d PREEMPT: the rule chooses a tool or decides whether to start."
                  % n_pre)
            print("  It fires BEFORE any matching file exists, so scoping it arms it")
            print("  one step too late. These usually STAY. This is the E2 exclusion.")
        if n_mixed:
            print("  %d MIXED: the rule also talks about the conversation, so it"
                  % n_mixed)
            print("  probably splits into a half that moves and a half that stays.")
        print("  Vocabulary is EVIDENCE, never the verdict. Apply the E2/E3 test in")
        print("  phase-e-path-scope.md: does this rule fire on a FILE or on a")
        print("  CONVERSATION? A scoped rule is LOST after a compaction until a")
        print("  matching file is read, and a conversation rule never comes back.")
        print("  Also exclude any rule that decides WHETHER to open such a file:")
        print("  scoping that one arms it exactly one step too late.")
    else:
        print("  none")

    print("")
    print("FLOOR  (what extraction can realistically reach on this file)")
    print("  %7d ch  sections already at or under the threshold -- irreducible"
          % fixed)
    print("               without DELETING rules, not relocating them")
    print("  %7d ch  %d RULE-shaped sections over %d ch -> ~%d ch at %d%% retention"
          % (sum(s["chars"] for s in rule_c), len(rule_c), PHASE_D_CHARS,
             int(sum(s["chars"] for s in rule_c) * RULE_RETENTION),
             int(RULE_RETENTION * 100)))
    print("  %7d ch  %d REFERENCE-shaped candidates -> ~%d ch as stubs"
          % (sum(s["chars"] for s in ref_c), len(ref_c), len(ref_c) * 120))
    print("  ESTIMATE  ~%d ch (~%d tokens), a %d%% cut from %d ch"
          % (est, est // 4, 100 - est * 100 // max(1, len(text)), len(text)))
    # A scoped rule Phase D WOULD have reached is already counted at retention;
    # one it would NOT have reached is counted at full size inside `fixed`.
    # Subtracting the wrong one overstates the saving.
    scope_saved = 0
    for s, _ in scope_c:
        scope_saved += (int(s["chars"] * RULE_RETENTION)
                        if id(s) in rule_ids else s["chars"])
    scope_chars = sum(s["chars"] for s, _ in scope_c)
    est_e = est - scope_saved
    print("  A target below THIS floor cannot be met by evidence extraction alone.")
    print("")
    print("  %7d ch  of that estimate is %d file-triggered rules (%d ch raw) that"
          % (scope_saved, len(scope_c), scope_chars))
    print("               Phase E can move out of the always-loaded set entirely,")
    print("               without deleting them. Phase E is the lever BELOW Phase")
    print("               D's floor. PREEMPT-flagged rules are NOT in this number's")
    print("               scope until a human clears them.")
    print("  ESTIMATE AFTER PHASE E  ~%d ch (~%d tokens), a %d%% cut from %d ch"
          % (est_e, est_e // 4, 100 - est_e * 100 // max(1, len(text)), len(text)))
    print("  Report BOTH floors. A target under the second one means deleting")
    print("  rules; a target between them means Phase E is not optional.")
    print("")
    print("SUMMARY convention=" + convention
          + " dated=" + str(len(records))
          + " sections=" + str(len(sections))
          + " archive=" + str(n_archive)
          + " keep=" + str(n_keep))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
