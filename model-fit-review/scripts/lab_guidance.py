#!/usr/bin/env python3
"""Read what the AI labs recommend today, and check what a reader quoted from it.

    lab_guidance.py fetch --sources reference/lab-sources.txt --out "$OUT/lab"
    lab_guidance.py check --lab-dir "$OUT/lab" --advice "$OUT/LAB_ADVICE.md" --models-file "$OUT/models.txt" [--report "$OUT/REPORT.md"]

fetch downloads each listed page and each page they link to that matches a `follow` line and no
`skip` line, on the hosts of the listed pages only, saves the text, and writes index.json. Each
link a skip line drops is printed as SKIPPED and kept in index.json, so a skip leaves a trace.
The labs serve markdown when `.md` is added to a page address (OpenAI: "Markdown versions of
documentation pages are available by appending `.md` to the page URL", latest-model.md;
Anthropic's pages answer the same way), so a link is read that way.
Exit 0 every page was read; 1 some page was not (each is named, the review goes on and reports
it); 2 a lab has no page at all, or an `expect` line found nothing, which means a page changed
and the follow lines went blind.

check reads LAB_ADVICE.md. Exit 0 every number is used once, every quote is on its saved page,
every item names that page's lab and audience, every saved page was used or has a `no advice:`
or `not read:` line, and every item from a page whose audience is `claude` has a `models:` line
that is exactly `all current Claude models` or a comma list of names from --models-file, each
named on the item's own page. With --report, every number also starts a line of the report that
carries its real quote and one outcome, and every `not read:` page is named there. 1 lists what
failed. 2 means there was nothing to check, or no usable models file, which can never pass.

The models file has one `pin | Claude model name` line per pin, written once per run from the
transcripts, in the form the lab pages use ("Claude Opus 5.5"). fill_rubric.py reads it too.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
from urllib.parse import urlsplit

MAX_PAGES = 30
MIN_QUOTE_WORDS = 5
KINDS = {"start", "page", "expect", "follow", "skip", "audience"}
LINK = re.compile(r"""(?<![\w/.-])(?:https?:)?(?://[\w.-]+)?/[^\s)\]"'<>`#?]+""")
FIELD = re.compile(r"^(lab|page|models|quote|applies to|means):[ \t]*(.*)$", re.M)
ITEM = re.compile(r"^### (A\d+)[ \t]*$", re.M)
NO_ADVICE = re.compile(r"^no advice: (\S+): (\S.*)$", re.M)
NOT_READ = re.compile(r"^not read: (\S+): (\S.*)$", re.M)
EXCUSE = re.compile(r"could not|couldn't|cannot|can't|unable|failed|truncat|cut off|not read|too (long|large)", re.I)
REPORT_ID = re.compile(r"^[ \t>*#-]*(A\d+)\b", re.M)
REPORT_HEADING = re.compile(r"^#", re.M)
OUTCOME = re.compile(r"\b(FOLLOWED|DIFFERS|ADD|NOT FOR US)\b")
CURLY = {0x2018: "'", 0x2019: "'", 0x201c: '"', 0x201d: '"'}
ALL_CLAUDE = "all current claude models"


def read_model_pins(path):
    """[(pin, Claude model name)] from a models file, in order. A line it cannot read refuses."""
    pins = []
    with open(path, encoding="utf-8") as fh:
        for n, raw in enumerate(fh, 1):
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            parts = [p.strip() for p in line.split("|")]
            if len(parts) != 2 or not parts[0] or not parts[1]:
                raise ValueError(f"line {n} is not `pin | model name`: {line!r}")
            pins.append((parts[0], parts[1]))
    if not pins:
        raise ValueError("it holds no model name")
    return pins


def read_models(path):
    """The distinct Claude model names of a models file, in order."""
    names = []
    for _, name in read_model_pins(path):
        if name.lower() not in (x.lower() for x in names):
            names.append(name)
    return names


def names_model(text, name):
    """The text names this model as a whole name: "Claude Opus 5" is not found in "Claude Opus 5.5"."""
    return re.search(r"(?<![\w.])" + re.escape(name) + r"(?![\w-]|\.\d)", text, re.I) is not None


def model_problems(ident, line, models, page_text):
    """What is wrong with a `claude` item's `models:` line; an empty list when nothing is."""
    line = line.strip()
    if line.lower() == ALL_CLAUDE:
        return []
    names = [x.strip() for x in line.split(",")]
    if not line or not all(names):
        return [f"{ident}: no usable `models:` line. Write `all current Claude models`, or names from the models file"]
    known = {m.lower() for m in models}
    unknown = [x for x in names if x.lower() not in known]
    if unknown:
        return [f"{ident}: `models:` names {', '.join(unknown)}, which is not `all current Claude models` and not a model "
                f"the harness runs ({', '.join(models)}). Drop the item, unless the page ties the sentence to one of those "
                f"models; a note goes in `means:`"]
    if page_text is None:
        return []
    return [f"{ident}: the page does not name {x}, so that label is not the page's. Drop the item, or name the model "
            f"the page ties it to" for x in names if not names_model(page_text, x)]


def read_sources(path):
    """Returns {kind: [(lab, value)]}. A line it cannot read refuses, so a typo drops no page."""
    out = {k: [] for k in KINDS}
    with open(path, encoding="utf-8") as fh:
        for n, raw in enumerate(fh, 1):
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            parts = [p.strip() for p in line.split("|", 2)]
            if len(parts) != 3 or parts[0] not in KINDS or not parts[2]:
                raise ValueError(f"{path} line {n} is not `kind | lab | value`: {line!r}")
            out[parts[0]].append((parts[1], parts[2]))
    return out


def fetch(url):
    """(status, content type, text) through curl, https only. A redirect is not followed."""
    r = subprocess.run(["curl", "-sS", "--proto", "=https", "--max-time", "30",
                        "-w", "\n%{http_code} %{content_type}", url],
                       capture_output=True, text=True, errors="replace", check=False)
    if r.returncode != 0:
        # curl still prints the status of a transfer cut off part way, so 200 alone proves nothing.
        raise OSError(f"curl exit {r.returncode}")
    body, _, tail = r.stdout.rpartition("\n")
    status, _, ctype = tail.partition(" ")
    return status, ctype, body


def normal_url(link, page_url):
    """A link as the address to fetch: absolute, https, no query, ending in .md or .txt."""
    if link.startswith("//"):
        link = "https:" + link
    elif link.startswith("/"):
        link = "https://" + urlsplit(page_url).hostname + link
    parts = urlsplit(link)
    path = parts.path.rstrip(".,;:")
    if not path.endswith((".md", ".txt")):
        path += ".md"
    return f"https://{parts.hostname}{path}"


def file_name(lab, url, taken):
    tail = urlsplit(url).path.rstrip("/").split("/")[-2:]
    stem = re.sub(r"[^\w-]+", "-", "-".join(tail).rsplit(".", 1)[0]).strip("-")
    name = f"{lab}__{stem}.md"
    n = 1
    while name in taken:
        n += 1
        name = f"{lab}__{stem}-{n}.md"
    taken.add(name)
    return name


def crawl(src, out_dir, max_pages=MAX_PAGES):
    hosts = {urlsplit(v).hostname for k in ("start", "page") for _, v in src[k]}
    follow = [re.compile(v) for _, v in src["follow"]]
    skip = [re.compile(v) for _, v in src["skip"]]
    audience = dict(src["audience"])
    queue = [(lab, kind, url, "") for kind in ("start", "page") for lab, url in src[kind]]
    seen = {q[2] for q in queue}
    pages, unread, other_host, skipped, taken = [], [], [], [], set()
    while queue:
        lab, role, url, found_on = queue.pop(0)
        if len(pages) >= max_pages:
            unread.append((url, f"over the limit of {max_pages} pages"))
            continue
        try:
            status, ctype, body = fetch(url)
        except (OSError, subprocess.SubprocessError) as exc:
            unread.append((url, f"{type(exc).__name__}: {exc}"))
            continue
        if status != "200":
            unread.append((url, f"HTTP {status or 'no answer'}"))
            continue
        if "html" in ctype or body.lstrip()[:15].lower().startswith(("<!doctype", "<html")):
            unread.append((url, "answered with a web page, no text version"))
            continue
        name = file_name(lab, url, taken)
        with open(os.path.join(out_dir, name), "w", encoding="utf-8") as fh:
            fh.write(body)
        pages.append({"lab": lab, "audience": audience.get(lab, ""), "role": role, "url": url,
                      "file": name, "found_on": found_on,
                      "chars": len(body), "sha256": hashlib.sha256(body.encode()).hexdigest()})
        for link in LINK.findall(body):
            if not any(p.search(link) for p in follow):
                continue
            target = normal_url(link, url)
            if any(p.search(link) for p in skip):
                if target not in skipped:
                    skipped.append(target)
                continue
            if urlsplit(target).hostname not in hosts:
                if target not in other_host:
                    other_host.append(target)
            elif target not in seen:
                seen.add(target)
                queue.append((lab, "followed", target, url))
    return pages, unread, other_host, skipped


def run_fetch(a):
    try:
        src = read_sources(a.sources)
    except (OSError, ValueError) as exc:
        print(f"CANNOT READ the source list: {exc}")
        return 2
    labs = sorted({lab for k in ("start", "page") for lab, _ in src[k]})
    if not labs:
        print("no pages listed")
        return 2
    os.makedirs(a.out, exist_ok=True)
    pages, unread, other_host, skipped = crawl(src, a.out, a.max_pages)
    with open(os.path.join(a.out, "index.json"), "w", encoding="utf-8") as fh:
        json.dump({"pages": pages, "unread": [{"url": u, "why": w} for u, w in unread],
                   "other_host": other_host, "skipped": skipped}, fh, indent=1)
    for p in pages:
        print(f"READ {p['lab']} {p['role']} {p['chars']} chars {p['file']} {p['url']}")
    for u, w in unread:
        print(f"NOT READ {u}: {w}")
    for u in other_host:
        print(f"OTHER HOST, not followed {u}")
    for u in skipped:
        print(f"SKIPPED by a skip line {u}")
    dead = [lab for lab in labs if not any(p["lab"] == lab for p in pages)]
    blind = [f"{lab}: {text}" for lab, text in src["expect"]
             if not any(p["lab"] == lab and text in p["url"] for p in pages)]
    if dead:
        print(f"NO PAGE READ for: {', '.join(dead)}")
    if blind:
        print(f"EXPECTED PAGE NOT FOUND, a page changed: {'; '.join(blind)}")
    if dead or blind:
        return 2
    return 1 if unread else 0


def norm(text):
    """Markdown marks and curly quotes differ between what a reader quotes and the saved page."""
    text = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", text).translate(CURLY)
    text = re.sub(r"\\([^\w\s])", r"\1", text)
    # Only paired marks are formatting: a lone star, as in foo*, is part of what the page says.
    text = re.sub(r"\*\*(?=\S)(.+?)(?<=\S)\*\*", r"\1", text)
    text = re.sub(r"(?<![\w*])\*(?=\S)([^*\n]+?)(?<=\S)\*(?![\w*])", r"\1", text)
    return " ".join(text.replace("`", "").split())


def holds(text, quote):
    """The quote stands in the text as whole words, so `state x` is not found in `overstate x`."""
    return re.search(r"(?<!\w)" + re.escape(quote) + r"(?!\w)", text) is not None


def report_blocks(report):
    """{number: [text]}: from a line that starts with the number to the next such line or heading."""
    ends = sorted([m.start() for m in REPORT_ID.finditer(report)]
                  + [m.start() for m in REPORT_HEADING.finditer(report)] + [len(report)])
    blocks = {}
    for m in REPORT_ID.finditer(report):
        stop = next(e for e in ends if e > m.start())
        blocks.setdefault(m.group(1), []).append(norm(report[m.start():stop]))
    return blocks


def read_items(advice):
    pieces = ITEM.split(advice)
    return [(pieces[i], dict(FIELD.findall(pieces[i + 1]))) for i in range(1, len(pieces), 2)]


def run_check(a):
    # Refused here, never by argparse, so leaving the flag out or giving an empty list is a
    # returned 2 that a caller and a test can read, not a crash.
    if not a.models_file:
        print("CANNOT CHECK: --models-file is required (the Claude models the harness runs)")
        return 2
    try:
        models = read_models(a.models_file)
    except (OSError, ValueError, TypeError) as exc:
        print(f"CANNOT CHECK: the models file {a.models_file}: {type(exc).__name__}: {exc}")
        return 2
    try:
        with open(os.path.join(a.lab_dir, "index.json"), encoding="utf-8") as fh:
            rows = {p["file"]: p for p in json.load(fh)["pages"]}
        with open(a.advice, encoding="utf-8") as fh:
            advice = fh.read()
        report = None
        if a.report:
            with open(a.report, encoding="utf-8") as fh:
                report = fh.read()
    except (OSError, ValueError, KeyError) as exc:
        print(f"CANNOT READ: {type(exc).__name__}: {exc}")
        return 2
    pages = set(rows)
    items = read_items(advice)
    if not pages or not items:
        print(f"nothing to check: {len(pages)} pages, {len(items)} advice items")
        return 2
    bad = []
    no_advice = NO_ADVICE.findall(advice)
    not_read = NOT_READ.findall(advice)
    used = {name for name, _ in no_advice + not_read}
    on_disk = {p for p in pages if os.path.exists(os.path.join(a.lab_dir, p))}
    bad += [f"{p}: saved page missing from disk" for p in sorted(pages - on_disk)]
    bad += [f"{name}: accounted for, but this run did not save it" for name in sorted(used - pages)]
    for name, why in no_advice:
        if EXCUSE.search(why):
            bad.append(f"{name}: says it could not be read, so use `not read:`, not `no advice:`")
    numbers = [ident for ident, _ in items]
    for ident in sorted(set(numbers)):
        if numbers.count(ident) > 1:
            bad.append(f"{ident}: used {numbers.count(ident)} times")
    blocks = report_blocks(report) if report is not None else {}
    for ident, f in items:
        page = f.get("page", "")
        used.add(page)
        quote = norm(f.get("quote", "")).strip('"')
        if page not in pages:
            bad.append(f"{ident}: page {page!r} was not saved in this run")
        else:
            if f.get("lab") != rows[page].get("lab"):
                bad.append(f"{ident}: says lab {f.get('lab')!r}, but the page belongs to {rows[page].get('lab')!r}")
            if f.get("applies to") != rows[page].get("audience"):
                bad.append(f"{ident}: `applies to` says {f.get('applies to')!r}, "
                           f"but this lab's models are {rows[page].get('audience')!r}")
            page_text = None
            if page in on_disk:
                with open(os.path.join(a.lab_dir, page), encoding="utf-8") as fh:
                    page_text = norm(fh.read())
            if len(quote.split()) < MIN_QUOTE_WORDS:
                bad.append(f"{ident}: the quote is under {MIN_QUOTE_WORDS} words, so it proves nothing")
            elif page_text is not None and not holds(page_text, quote):
                bad.append(f"{ident}: the quote is not on {page}: {quote[:80]!r}")
            if rows[page].get("audience") == "claude":
                bad += model_problems(ident, f.get("models", ""), models, page_text)
        if report is not None:
            found = blocks.get(ident, [])
            if not found:
                bad.append(f"{ident}: NOT IN THE REPORT as a line of its own")
            elif not any(holds(b, quote) for b in found):
                bad.append(f"{ident}: the report does not carry its real quote")
            elif not any(holds(b, quote) and OUTCOME.search(b) for b in found):
                bad.append(f"{ident}: the report gives it no outcome")
    bad += [f"{p}: saved but not used, and no `no advice:` or `not read:` line" for p in sorted(pages - used)]
    for name, why in not_read:
        print(f"NOT READ BY THE READER {name}: {why}")
        if report is not None and name not in report:
            bad.append(f"{name}: the reader could not read it and the report does not say so")
    for line in bad:
        print(f"FAILED {line}")
    print(f"Claude models the harness runs: {', '.join(models)}")
    print(f"{len(items)} advice items, {len(pages)} pages, {len(bad)} failed")
    return 1 if bad else 0


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    f = sub.add_parser("fetch")
    f.add_argument("--sources", required=True)
    f.add_argument("--out", required=True)
    f.add_argument("--max-pages", type=int, default=MAX_PAGES)
    c = sub.add_parser("check")
    c.add_argument("--lab-dir", required=True)
    c.add_argument("--advice", required=True)
    c.add_argument("--report")
    c.add_argument("--models-file", help="one `pin | Claude model name` line per pin; required, run_check refuses without it")
    a = ap.parse_args()
    return run_fetch(a) if a.cmd == "fetch" else run_check(a)


if __name__ == "__main__":
    sys.exit(main())
