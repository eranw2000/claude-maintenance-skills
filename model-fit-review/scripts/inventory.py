#!/usr/bin/env python3
"""Measure a Claude Code harness (skills, agents, commands) for text written for weaker models.

Prints one table row per file and a cross-file section, and writes the same as JSON with
--json. Every number here is read from the files; nothing is remembered between runs.

Scope: skills/<name>/SKILL.md, the .md files directly in its reference/ or references/ folder,
agents/*.md, commands/*.md. Everything else that is markdown under skills/ (a SKILL.md nested
deeper, such as third-party or plugin skills, and any other .md in a skill folder) is listed
under "not measured", so the narrower scope is stated on every run rather than silent.

Checks per file: chars, lines, description length (frontmatter), model and effort pins,
shouting (NEVER/ALWAYS/MUST/DO NOT count, and per 1,000 chars), stale model names
(reference/stale-names.txt, one regex per line), copies of the pointer phrase (--phrase), story
sentences ("Measured <date>"), dated mentions (every
YYYY-MM-DD outside a code fence of any shape, a wider net to read as candidates), and asks to
the user.

Checks across files: files over the SKILL.md size line (--size-line, default 16000), lines
over the documented guideline (--line-guide, default 500), descriptions over the validator's
cap (--validator-cap, default 1024) and over Claude Code's listing cap (--listing-cap, default
1536, description plus when_to_use), the headings a compaction would drop (everything after
the first --keep-chars, default 20000, about 5,000 tokens), paragraphs of --dup-min chars
(default 80) shared verbatim by two or more files, and the readers of every skills/_shared
file, a file with no reader included. --caps reads the listing cap, keep and line guideline
from the JSON docs_caps.py wrote, so a changed docs page moves the checks too; a flag given on
the same command line wins over the file.

Control: --control-phrase (default "## ") must be found at least once in the tree, or the run
exits 2: a tree in which nothing matches is a broken run, not a clean one.

PyYAML is required: a description is measured as YAML reads it. Without it the run refuses.

Exit 0 when it measured, 2 when it could not (no PyYAML, no files, control phrase absent, a
caps file it cannot read).
"""
import argparse
import json
import os
import re
import sys
from collections import defaultdict

try:
    import yaml
except ImportError:
    yaml = None

DEFAULT_PHRASE = r"is only a summary and is not enough to act on"
STORY_RE = re.compile(r"\bMeasured(?: on| here)? 20\d\d-\d\d-\d\d")
DATED_RE = re.compile(r"\b20\d\d-\d\d-\d\d\b")
FENCE_OPEN_RE = re.compile(r" {0,3}(`{3,}|~{3,})")
SHOUT_RE = re.compile(r"\b(NEVER|ALWAYS|MUST|DO NOT|NOT)\b")
ASK_RE = re.compile(r"(?i)\bask(?:s|ed)? (?:the user|him|her|them)\b|AskUserQuestion")
FM_RE = re.compile(r"^---\n(.*?)\n---", re.S)


def frontmatter(text):
    m = FM_RE.match(text)
    return m.group(1) if m else ""


def fm_field(fm, key):
    """Value of one frontmatter key as YAML sees it, so comment lines are not
    part of it. None when the frontmatter is not valid YAML (a real defect: quick_validate
    fails it, while Claude Code's lenient parser hides it)."""
    try:
        data = yaml.safe_load(fm) or {}
    except yaml.YAMLError:
        return None
    v = data.get(key, "") if isinstance(data, dict) else ""
    return str(v).strip() if v is not None else ""


CUT_RE = re.compile(r"\s#")


def description_cut(fm):
    """True when the description is a plain (unquoted, not block) scalar holding " #". YAML reads
    that as the start of a comment, so everything after it is dropped from the value while the
    frontmatter stays valid: the length check and the YAML check both pass on a description that
    has lost its trigger phrases. Continuation lines are the indented lines after the key; a
    comment at column 0 is not one."""
    lines = fm.split("\n")
    for i, line in enumerate(lines):
        if not line.startswith("description:"):
            continue
        raw = [line[len("description:"):]]
        for nxt in lines[i + 1:]:
            if nxt[:1] in (" ", "\t") and nxt.strip():
                raw.append(nxt)
            else:
                break
        first = "".join(raw).lstrip()
        if not first or first[0] in "'\"|>":
            return False
        return any(CUT_RE.search(" " + piece.strip()) for piece in raw if piece.strip())
    return False


def read(path):
    with open(path, encoding="utf-8", errors="replace") as fh:
        return fh.read()


def prose(text):
    """The text without its code fences: backtick or tilde, indented up to three spaces. A fence
    closes only on a line holding nothing but the same character, at least as many times."""
    out, fence = [], None
    for line in text.split("\n"):
        m = FENCE_OPEN_RE.match(line)
        if fence:
            if m and m.group(1)[0] == fence[0] and len(m.group(1)) >= len(fence) and not line.strip(" " + fence[0]):
                fence = None
            continue
        if m:
            fence = m.group(1)
            continue
        out.append(line)
    return "\n".join(out)


def logical_lines(text):
    """Lines as an editor counts them: the final newline does not start another one."""
    if not text:
        return 0
    return text.count("\n") + (0 if text.endswith("\n") else 1)


def load_stale(path):
    pats = []
    if path and os.path.exists(path):
        for line in read(path).splitlines():
            line = line.strip()
            if line and not line.startswith("#"):
                pats.append(re.compile(line, re.I))
    return pats


REFERENCE_FOLDERS = ("reference", "references")


def collect(root):
    files = []
    sk = os.path.join(root, "skills")
    if os.path.isdir(sk):
        for d in sorted(os.listdir(sk)):
            p = os.path.join(sk, d, "SKILL.md")
            if os.path.isfile(p):
                files.append(("skill", p))
            for folder in REFERENCE_FOLDERS:
                ref = os.path.join(sk, d, folder)
                if os.path.isdir(ref):
                    for f in sorted(os.listdir(ref)):
                        if f.endswith(".md"):
                            files.append(("reference", os.path.join(ref, f)))
    for kind in ("agents", "commands"):
        d = os.path.join(root, kind)
        if os.path.isdir(d):
            for f in sorted(os.listdir(d)):
                if f.endswith(".md"):
                    files.append((kind[:-1], os.path.join(d, f)))
    return files


def not_measured(root, files):
    """Markdown under skills/ that collect() leaves out, by top folder: stated, never silent."""
    sk = os.path.join(root, "skills")
    measured = {p for _, p in files}
    nested, other = defaultdict(int), defaultdict(int)
    for dirpath, _dirs, names in os.walk(sk):
        rel = os.path.relpath(dirpath, sk)
        top = rel.split(os.sep)[0]
        if rel == "." or top == "_shared":
            continue
        for n in names:
            if n.endswith(".md") and os.path.join(dirpath, n) not in measured:
                (nested if n == "SKILL.md" else other)[top] += 1
    return {"nested_skill_md": dict(sorted(nested.items())), "other_md": dict(sorted(other.items()))}


def shared_readers(root, rows, texts):
    """Who names each skills/_shared/*.md. The whole name must match: notes-old.md is no
    reader of notes.md, and neither are notes.py and notes.md.bak. A file nobody
    names stays in the map with an empty list, because that is the orphan worth reading."""
    shared_dir = os.path.join(root, "skills", "_shared")
    out = {}
    if os.path.isdir(shared_dir):
        for f in sorted(os.listdir(shared_dir)):
            if f.endswith(".md"):
                pat = re.compile(r"(?<![\w-])" + re.escape(f[:-3]) + r"(?:\.md)?(?![\w-]|\.\w)")
                out[f] = [r["path"] for r in rows if pat.search(texts[r["path"]])]
    return out


def paragraphs(text):
    out = []
    for para in re.split(r"\n\s*\n", text):
        norm = re.sub(r"\s+", " ", para).strip()
        if norm:
            out.append(norm)
    return out


def headings_dropped(text, keep_chars):
    kept = [h for h in re.finditer(r"^#{2,3} .*$", text, re.M) if h.start() < keep_chars]
    dropped = [h.group(0) for h in re.finditer(r"^#{2,3} .*$", text, re.M) if h.start() >= keep_chars]
    last_kept = kept[-1].group(0) if kept else ""
    return last_kept, dropped


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--root", default=os.path.expanduser("~/.claude"))
    ap.add_argument("--json", help="write the full result here")
    ap.add_argument("--phrase", default=DEFAULT_PHRASE, help="regex of the pasted pointer phrase")
    ap.add_argument("--stale-names", default=os.path.join(os.path.dirname(__file__), "..", "reference", "stale-names.txt"))
    ap.add_argument("--size-line", type=int, default=16000)
    ap.add_argument("--line-guide", type=int, default=500)
    ap.add_argument("--validator-cap", type=int, default=1024)
    ap.add_argument("--listing-cap", type=int, default=1536)
    ap.add_argument("--keep-chars", type=int, default=20000)
    ap.add_argument("--dup-min", type=int, default=80)
    ap.add_argument("--control-phrase", default="## ")
    ap.add_argument("--caps", help="JSON from docs_caps.py --json; its numbers replace the three defaults")
    ap.add_argument("--quiet", action="store_true")
    try:
        caps_path = ap.parse_known_args()[0].caps
        if caps_path:
            with open(caps_path, encoding="utf-8") as fh:
                caps = json.load(fh)
            ap.set_defaults(listing_cap=caps["listing_cap"], keep_chars=caps["keep_chars"], line_guide=caps["line_guide"])
    except (OSError, ValueError, KeyError) as exc:
        print(f"CANNOT MEASURE: caps file unreadable ({type(exc).__name__}); docs_caps.py must exit 0 first", file=sys.stderr)
        return 2
    a = ap.parse_args()

    if yaml is None:
        print("CANNOT MEASURE: PyYAML is required (a description is measured as YAML reads it); "
              "install it with pip install pyyaml", file=sys.stderr)
        return 2

    root = os.path.abspath(os.path.expanduser(a.root))
    files = collect(root)
    if not files:
        print(f"CANNOT MEASURE: no skills/agents/commands under {root}", file=sys.stderr)
        return 2
    phrase_re = re.compile(a.phrase)
    stale = load_stale(a.stale_names)
    control_hits = 0
    rows = []
    para_owners = defaultdict(set)
    texts = {}
    total = 0
    for kind, path in files:
        text = read(path)
        texts[os.path.relpath(path, root)] = text
        total += len(text)
        control_hits += text.count(a.control_phrase)
        fm = frontmatter(text)
        desc = fm_field(fm, "description")
        invalid_fm = desc is None
        desc = desc or ""
        wtu = fm_field(fm, "when_to_use") or ""
        stale_hits = sorted({m.group(0) for p in stale for m in p.finditer(text)})
        lines = logical_lines(text)
        shouting = len(SHOUT_RE.findall(text))
        last_kept, dropped = headings_dropped(text, a.keep_chars)
        row = {
            "kind": kind,
            "path": os.path.relpath(path, root),
            "chars": len(text),
            "lines": lines,
            "description_chars": len(desc),
            "listing_chars": len(desc) + len(wtu),
            "frontmatter_invalid": invalid_fm,
            "description_cut": (not invalid_fm) and description_cut(fm),
            "model": (fm_field(fm, "model") or "-") if not invalid_fm else "?",
            "effort": (fm_field(fm, "effort") or "-") if not invalid_fm else "?",
            "shouting": shouting,
            "shouting_per_1k": round(shouting * 1000 / len(text), 1) if text else 0.0,
            "stale_names": stale_hits,
            "pointer_phrase": len(phrase_re.findall(text)),
            "stories": len(STORY_RE.findall(text)),
            "dated_mentions": len(DATED_RE.findall(prose(text))),
            "asks": len(ASK_RE.findall(text)),
            "over_size_line": len(text) > a.size_line,
            "over_line_guide": lines > a.line_guide,
            "over_validator_cap": len(desc) > a.validator_cap,
            "over_listing_cap": len(desc) + len(wtu) > a.listing_cap,
            "last_heading_kept": last_kept,
            "headings_dropped": dropped,
        }
        rows.append(row)
        for para in paragraphs(text):
            if len(para) >= a.dup_min:
                para_owners[para].add(row["path"])
    if control_hits == 0:
        print(f"CANNOT MEASURE: control phrase {a.control_phrase!r} found nowhere; the read is broken", file=sys.stderr)
        return 2

    dups = [{"chars": len(p), "files": sorted(fs), "start": p[:90]} for p, fs in para_owners.items() if len(fs) >= 2]
    dups.sort(key=lambda d: -d["chars"] * len(d["files"]))
    readers = shared_readers(root, rows, texts)
    skipped = not_measured(root, files)
    summary = {
        "root": root,
        "files": len(rows),
        "total_chars": total,
        "pointer_phrase_copies": sum(r["pointer_phrase"] for r in rows),
        "pointer_phrase_files": sum(1 for r in rows if r["pointer_phrase"]),
        "story_sentences": sum(r["stories"] for r in rows),
        "dated_mentions": sum(r["dated_mentions"] for r in rows),
        "stale_name_files": sum(1 for r in rows if r["stale_names"]),
        "over_size_line": [r["path"] for r in rows if r["over_size_line"]],
        "over_line_guide": [r["path"] for r in rows if r["over_line_guide"]],
        "over_validator_cap": [(r["path"], r["description_chars"]) for r in rows if r["over_validator_cap"]],
        "over_listing_cap": [(r["path"], r["listing_chars"]) for r in rows if r["over_listing_cap"]],
        "frontmatter_invalid": [r["path"] for r in rows if r["frontmatter_invalid"]],
        "description_cut": [r["path"] for r in rows if r["description_cut"]],
        "pins": {m: sum(1 for r in rows if r["kind"] == "skill" and r["model"] == m) for m in sorted({r["model"] for r in rows if r["kind"] == "skill"})},
        "duplicate_paragraphs": len(dups),
        "duplicate_floor_chars": a.dup_min,
        "caps": {"listing": a.listing_cap, "keep_chars": a.keep_chars, "line_guide": a.line_guide, "validator": a.validator_cap},
        "shared_files_with_no_reader": [f for f, who in readers.items() if not who],
        "not_measured": skipped,
        "control_phrase_hits": control_hits,
    }
    result = {"summary": summary, "rows": rows, "duplicates": dups, "shared_readers": readers}
    if a.json:
        with open(a.json, "w", encoding="utf-8") as fh:
            json.dump(result, fh, indent=1, ensure_ascii=False)
    if not a.quiet:
        print(f"files {summary['files']}  chars {summary['total_chars']}  control hits {control_hits}")
        print(f"pointer phrase: {summary['pointer_phrase_copies']} copies in {summary['pointer_phrase_files']} files")
        print(f"story sentences: {summary['story_sentences']}   dated mentions: {summary['dated_mentions']}   stale-name files: {summary['stale_name_files']}")
        print(f"over {a.size_line} chars: {len(summary['over_size_line'])}   over {a.line_guide} lines: {len(summary['over_line_guide'])}")
        print(f"descriptions over {a.validator_cap}: {len(summary['over_validator_cap'])}   over {a.listing_cap} (listing): {len(summary['over_listing_cap'])}")
        print(f"frontmatter that is not valid YAML: {summary['frontmatter_invalid'] or 'none'}")
        print(f"descriptions cut short by an unquoted ' #' (YAML reads a comment): {summary['description_cut'] or 'none'}")
        print(f"skill pins: {summary['pins']}   duplicate paragraphs (2+ files, {a.dup_min}+ chars): {len(dups)}")
        print(f"not measured: nested SKILL.md {skipped['nested_skill_md'] or 'none'}; other .md in skill folders {sum(skipped['other_md'].values())}")
        print(f"_shared files with no reader: {summary['shared_files_with_no_reader'] or 'none'}")
        print()
        print("kind | path | chars | lines | desc | model | shout | per 1k | stale | pointer | stories | dated | asks")
        for r in rows:
            print(f"{r['kind']} | {r['path']} | {r['chars']} | {r['lines']} | {r['description_chars']} | {r['model']} | {r['shouting']} | {r['shouting_per_1k']} | {','.join(r['stale_names']) or '-'} | {r['pointer_phrase']} | {r['stories']} | {r['dated_mentions']} | {r['asks']}")
        if dups:
            print()
            print("verbatim paragraphs shared by 2+ files (largest first, top 15):")
            for d in dups[:15]:
                print(f"  {d['chars']} chars x {len(d['files'])}: {', '.join(d['files'])}\n      {d['start']}...")
        if readers:
            print()
            print("readers of skills/_shared/*.md:")
            for f, who in sorted(readers.items(), key=lambda kv: -len(kv[1])):
                print(f"  {f}: {len(who)}")
        big = [r for r in rows if r["headings_dropped"]]
        if big:
            print()
            print(f"what a compaction drops (headings after the first {a.keep_chars} chars):")
            for r in big:
                print(f"  {r['path']} ({r['chars']}): last kept '{r['last_heading_kept']}'; drops {len(r['headings_dropped'])}: {'; '.join(h[:50] for h in r['headings_dropped'][:6])}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
