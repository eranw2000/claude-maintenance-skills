#!/usr/bin/env python3
"""Notice when an AI lab lists a model it did not list before. No model call, no cost.

    model_watch.py check [--lists reference/model-lists.txt] [--state FILE]
    model_watch.py ack   [--state FILE] ID [ID ...]  # clears only the named models
    model_watch.py seen  [--state FILE]

check fetches each page named on a `list` line of model-lists.txt (the same way
lab_guidance.py fetches: curl, https only, no redirect followed), pulls the model ids out
with that line's regex, drops what an `ignore` line matches, and compares them with the ids
recorded in the state file (default: `DEFAULT_STATE` below).

- A lab seen for the first time (a fresh install, or a lab just added to the list) is
  recorded quietly, so nobody is told about every model that already exists.
- After that, an id not recorded is NEW: it is recorded as seen AND as pending. A pending
  model is printed on every check (`PENDING`) until `ack` clears it, so a notice that never
  reached anyone (the session ended, the output was lost, the line was skipped) comes back
  the next day instead of being gone for good.
  Nothing here records whether anyone was TOLD, because that cannot be known.
- `ack` clears only the ids it is given, and refuses with none, so okaying the models one
  session told cannot clear a model only another session saw.
- A trailing snapshot date (`-YYYYMMDD` or `-YYYY-MM-DD`, with an optional `-vN` after it, as
  cloud ids carry) is dropped, so a dated snapshot reads as its model.
- `check` and `ack` take one lock (`run.lock` beside the state file), so an ack during a
  check is not undone when the check saves.
- A lab is read only when EVERY one of its pages answered and gave at least one id. One that
  did not is BROKEN the first day and STILL-BROKEN after, printed on every check until it
  recovers, and never read as "nothing new". Its ids are not compared that day, so a page
  that failed cannot make old models look new.
- When no page answered, or every page that answered was a web page (a wifi login page
  answers 200 with HTML), the machine is treated as offline: OFFLINE is printed and the state
  is left exactly as it was.

Lines: `NEW <lab> <id>`, `PENDING <lab> <id> since <date>`, `BROKEN <lab> <reason>`,
`STILL-BROKEN <lab> <reason>`, `RECOVERED <lab>`, `OK <lab> <n> ids`, `SEEDED <lab> <n> ids`,
`UNSAVED state <path>: <reason>`, `OFFLINE`. When the state file cannot be written (a folder
that turned read-only, a full disk), the lines read are still returned with an UNSAVED line, so
nothing read is hidden; nothing was recorded, so a NEW model is NEW again on the next check.
Exit 0 nothing to tell anyone; 3 a NEW, PENDING, BROKEN or STILL-BROKEN line was printed;
2 the list file or the state file cannot be read or is not the right shape, or `ack` was given
no model, which can never pass.
"""
from __future__ import annotations

import argparse
import datetime
import errno
import importlib.util
import json
import os
import re
import sys
import time

try:
    import fcntl
except ImportError:  # Windows: no fcntl; msvcrt.locking holds a one-byte lock instead
    fcntl = None
    import msvcrt

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_LISTS = os.path.join(HERE, "..", "reference", "model-lists.txt")
DEFAULT_STATE = os.path.join(os.path.expanduser("~"), ".claude", "hooks", ".model-watch", "known.json")
TELL = ("NEW ", "PENDING ", "BROKEN ", "STILL-BROKEN ", "UNSAVED ")
# a file, not a directory, so the lock call can take it
LOCK_NAME = "run.lock"
SNAPSHOT = re.compile(r"-(?:\d{8}|\d{4}-\d{2}-\d{2})(?:-v\d+)?$")


def acquire_lock(state_dir, wait=True):
    """An fd holding an exclusive flock on <state_dir>/run.lock, or None when `wait` is False
    and another process holds it. The kernel drops the lock when the fd closes or the process
    dies, so a killed run leaves nothing behind. Raises OSError when the folder is unusable."""
    os.makedirs(state_dir, exist_ok=True)
    fd = os.open(os.path.join(state_dir, LOCK_NAME), os.O_CREAT | os.O_RDWR, 0o600)
    if fcntl is None:
        return _windows_lock(fd, wait)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX if wait else fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        os.close(fd)
        return None
    return fd


def _windows_lock(fd, wait):
    """Lock byte 0 of the lock file. Microsoft's _locking page: EACCES is "Locking violation
    (file already locked or unlocked)", and regions "should be unlocked before closing a file
    or exiting the program", so release_lock unlocks first. Any other error is raised."""
    while True:
        os.lseek(fd, 0, os.SEEK_SET)
        try:
            msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
            return fd
        except OSError as e:
            if e.errno != errno.EACCES:
                os.close(fd)
                raise
            if not wait:
                os.close(fd)
                return None
            time.sleep(0.2)


def release_lock(fd):
    if fd is not None:
        if fcntl is None:
            try:
                os.lseek(fd, 0, os.SEEK_SET)
                msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
            except OSError:
                pass
        try:
            os.close(fd)
        except OSError:
            pass


def _lab_guidance():
    spec = importlib.util.spec_from_file_location("lab_guidance", os.path.join(HERE, "lab_guidance.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def default_fetch(url):
    """(status, content type, text), from lab_guidance.fetch, so both read pages one way."""
    return _lab_guidance().fetch(url)


def _compile(path, n, text):
    try:
        return re.compile(text)
    except re.error as exc:
        raise ValueError(f"{path} line {n}: bad regex {text!r}: {exc}") from None


def read_lists(path):
    """{"list": [(lab, url, compiled regex)], "ignore": {lab: [compiled regex]}}.

    A regex may itself hold `|`, so a list line splits into exactly four fields and an
    ignore line into three. A line it cannot read refuses, so a typo drops no page."""
    out = {"list": [], "ignore": {}}
    with open(path, encoding="utf-8") as fh:
        for n, raw in enumerate(fh, 1):
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            kind = line.split("|", 1)[0].strip()
            if kind == "list":
                parts = [p.strip() for p in line.split("|", 3)]
                if len(parts) != 4 or not all(parts):
                    raise ValueError(f"{path} line {n} is not `list | lab | url | regex`: {line!r}")
                out["list"].append((parts[1], parts[2], _compile(path, n, parts[3])))
            elif kind == "ignore":
                parts = [p.strip() for p in line.split("|", 2)]
                if len(parts) != 3 or not all(parts):
                    raise ValueError(f"{path} line {n} is not `ignore | lab | regex`: {line!r}")
                out["ignore"].setdefault(parts[1], []).append(_compile(path, n, parts[2]))
            else:
                raise ValueError(f"{path} line {n} has unknown kind {kind!r}: {line!r}")
    if not out["list"]:
        raise ValueError(f"{path} names no list page")
    return out


def ids_on_page(text, pattern):
    found = set()
    for m in pattern.finditer(text):
        model = m.group(1) if pattern.groups else m.group(0)
        if model.endswith(".md"):
            model = model[:-3]
        found.add(SNAPSHOT.sub("", model))
    return found


def _is_web_page(ctype, body):
    return "html" in (ctype or "") or body.lstrip()[:15].lower().startswith(("<!doctype", "<html"))


def read_labs(lists, fetch):
    """({lab: ("ok", ids) | ("broken", reason)}, whether any page answered with text)."""
    pages = {}
    for lab, url, pattern in lists["list"]:
        pages.setdefault(lab, []).append((url, pattern))
    result, any_text = {}, False
    for lab, entries in pages.items():
        ids, problem = set(), None
        for url, pattern in entries:
            try:
                status, ctype, body = fetch(url)
            except Exception as exc:  # a fetch that cannot run is that page failing, never a crash
                problem = problem or f"{url}: {type(exc).__name__}: {exc}"
                continue
            if status != "200":
                any_text = any_text or not _is_web_page(ctype, body or "")
                problem = problem or f"{url}: HTTP {status or 'no answer'}"
                continue
            if _is_web_page(ctype, body):
                problem = problem or f"{url}: answered with a web page, no text version"
                continue
            any_text = True
            page_ids = ids_on_page(body, pattern)
            if not page_ids:
                problem = problem or f"{url}: the pattern found no model id"
                continue
            ids |= page_ids
        if problem:
            result[lab] = ("broken", problem)
        else:
            drop = lists["ignore"].get(lab, [])
            result[lab] = ("ok", {i for i in ids if not any(p.search(i) for p in drop)})
    return result, any_text


def _check_shape(path, state):
    def lab_map(name, leaf):
        value = state.get(name, {})
        if not isinstance(value, dict):
            raise ValueError(f"{path}: `{name}` must be an object, not {type(value).__name__}")
        for lab, inner in value.items():
            if not leaf(inner):
                raise ValueError(f"{path}: `{name}.{lab}` has the wrong shape ({type(inner).__name__})")
    is_dates = lambda v: isinstance(v, dict) and all(isinstance(k, str) and isinstance(d, str) for k, d in v.items())
    lab_map("seen", is_dates)
    lab_map("pending", is_dates)
    lab_map("broken", lambda v: isinstance(v, str))


def load_state(path):
    """The state, or a fresh one when the file does not exist. A file that is there but cannot
    be read as a state raises ValueError: guessing would re-seed and swallow a new model."""
    if not os.path.exists(path):
        return {"version": 2, "seen": {}, "pending": {}, "broken": {}}
    try:
        with open(path, encoding="utf-8") as fh:
            state = json.load(fh)
    except ValueError as exc:
        raise ValueError(f"{path} is not valid JSON: {exc}") from None
    if not isinstance(state, dict) or not isinstance(state.get("seen"), dict):
        raise ValueError(f"{path} is not a model-watch state file")
    state.setdefault("pending", {})
    state.setdefault("broken", {})
    _check_shape(path, state)
    state["version"] = 2
    return state


def save_state(path, state):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    tmp = f"{path}.tmp-{os.getpid()}"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(state, fh, indent=1, sort_keys=True)
        fh.write("\n")
    os.replace(tmp, path)


def check(lists_path=DEFAULT_LISTS, state_path=DEFAULT_STATE, fetch=default_fetch, today=None):
    """Returns (exit status, lines). Writes the state file unless the machine is offline."""
    lists = read_lists(lists_path)
    state = load_state(state_path)
    today = today or datetime.date.today().isoformat()
    labs, any_text = read_labs(lists, fetch)
    if not any_text:
        return 0, ["OFFLINE"]
    lines = []
    for lab in sorted(labs):
        kind, value = labs[lab]
        if kind == "broken":
            word = "STILL-BROKEN" if lab in state["broken"] else "BROKEN"
            lines.append(f"{word} {lab} {value}")
            state["broken"][lab] = value
            continue
        if state["broken"].pop(lab, None) is not None:
            lines.append(f"RECOVERED {lab}")
        seen = state["seen"].get(lab)
        if seen is None:
            state["seen"][lab] = {i: today for i in sorted(value)}
            lines.append(f"SEEDED {lab} {len(value)} ids")
            continue
        pending = state["pending"].setdefault(lab, {})
        for model in sorted(value - set(seen)):
            seen[model] = today
            pending[model] = today
            lines.append(f"NEW {lab} {model}")
        lines.append(f"OK {lab} {len(value)} ids")
    for lab in sorted(state["pending"]):
        for model, since in sorted(state["pending"][lab].items()):
            if f"NEW {lab} {model}" not in lines:
                lines.append(f"PENDING {lab} {model} since {since}")
    state["pending"] = {lab: ids for lab, ids in state["pending"].items() if ids}
    try:
        save_state(state_path, state)
    except OSError as exc:
        lines.append(f"UNSAVED state {state_path}: {exc}")
    return (3 if any(l.startswith(TELL) for l in lines) else 0), lines


def ack(state_path=DEFAULT_STATE, models=None):
    """Clear the named pending models. Returns the lines it printed. Refuses (ValueError) with
    no names: a bare ack would clear a model told only in another session, or never told."""
    if not models:
        raise ValueError("ack needs the model ids to clear (see `model_watch.py seen`)")
    state = load_state(state_path)
    lines = []
    for lab in sorted(state["pending"]):
        for model in sorted(state["pending"][lab]):
            if model in models:
                lines.append(f"ACKED {lab} {model}")
                del state["pending"][lab][model]
    state["pending"] = {lab: ids for lab, ids in state["pending"].items() if ids}
    unknown = sorted(set(models) - {l.split()[2] for l in lines})
    lines += [f"NOT PENDING {m}" for m in unknown]
    save_state(state_path, state)
    return lines


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("check")
    c.add_argument("--lists", default=DEFAULT_LISTS)
    c.add_argument("--state", default=DEFAULT_STATE)
    a = sub.add_parser("ack")
    a.add_argument("--state", default=DEFAULT_STATE)
    a.add_argument("models", nargs="*")
    s = sub.add_parser("seen")
    s.add_argument("--state", default=DEFAULT_STATE)
    args = ap.parse_args(argv)
    try:
        if args.cmd == "seen":
            state = load_state(args.state)
            for lab in sorted(state["seen"]):
                for model, day in sorted(state["seen"][lab].items()):
                    flag = " pending" if model in state["pending"].get(lab, {}) else ""
                    print(f"{lab} {model} {day}{flag}")
            return 0
        fd = acquire_lock(os.path.dirname(os.path.abspath(args.state)))
        try:
            if args.cmd == "ack":
                for line in ack(args.state, args.models):
                    print(line)
                return 0
            status, lines = check(args.lists, args.state)
        finally:
            release_lock(fd)
    except (OSError, ValueError) as exc:
        print(f"model_watch: {exc}", file=sys.stderr)
        return 2
    for line in lines:
        print(line)
    return status


if __name__ == "__main__":
    sys.exit(main())
