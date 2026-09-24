#!/usr/bin/env python3
"""Find the skill a session last invoked and the scripts written or run after it.

Reads the session transcript (.jsonl), not the conversation, so a summarized
context cannot hide a script. Lists candidates; --show N prints one in full.

Usage:
  find_session_scripts.py [--transcript PATH] [--cwd DIR] [--skill NAME]
                          [--show N] [--json]
Exit: 0 ok, 2 no transcript, 3 no skill invocation found, 4 bad --show index.
"""
import argparse
import json
import os
import re
import sys
from pathlib import Path

SCRIPT_EXT = (".py", ".sh", ".bash", ".zsh", ".js", ".mjs", ".ts", ".rb", ".pl")
INLINE = re.compile(r"(python3?|node|bash|sh|zsh|ruby|perl)\b[^\n]*(<<-?\s*['\"]?\w+|\s-c\s)")
COMMAND_TAG = re.compile(r"<command-name>/?([\w:.-]+)</command-name>")


def default_transcript(cwd):
    enc = re.sub(r"[^A-Za-z0-9]", "-", os.path.abspath(cwd))
    d = Path.home() / ".claude" / "projects" / enc
    files = sorted(d.glob("*.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True)
    return files[0] if files else None


def resolve_skill_dir(name, cwd):
    if ":" in name:
        return None, "plugin skill, not editable here"
    for base in (Path(cwd) / ".claude" / "skills", Path.home() / ".claude" / "skills"):
        p = base / name / "SKILL.md"
        if p.is_file():
            return p.parent, None
    return None, "no SKILL.md found under .claude/skills"


def records(path):
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            try:
                d = json.loads(line)
            except ValueError:
                continue
            if not isinstance(d, dict) or d.get("isSidechain"):
                continue
            yield d


def blocks(d):
    c = (d.get("message") or {}).get("content")
    if isinstance(c, str):
        return [{"type": "text", "text": c}]
    return [b for b in c or [] if isinstance(b, dict)]


def scan(path, want_skill):
    events, results = [], {}
    for d in records(path):
        ts = d.get("timestamp", "")
        for b in blocks(d):
            t = b.get("type")
            if t == "tool_result":
                results[b.get("tool_use_id")] = bool(b.get("is_error"))
            elif t == "text" and d.get("type") == "user":
                for m in COMMAND_TAG.finditer(b.get("text", "")):
                    events.append(("skill", m.group(1), ts, None))
            elif t == "tool_use":
                name, inp = b.get("name"), b.get("input") or {}
                if name == "Skill":
                    events.append(("skill", inp.get("skill", ""), ts, None))
                elif name in ("Write", "Edit", "MultiEdit"):
                    fp = inp.get("file_path", "")
                    if fp.endswith(SCRIPT_EXT):
                        events.append((name.lower(), fp, ts, inp.get("content")))
                elif name == "Bash":
                    events.append(("bash", inp.get("command", ""), ts, b.get("id")))

    start, skill = None, None
    for i, (kind, val, _, _) in enumerate(events):
        if kind == "skill" and (not want_skill or val == want_skill):
            start, skill = i, val
    if start is None:
        return None, []

    later = events[start + 1:]
    cands, by_path = [], {}
    for kind, val, ts, extra in later:
        if kind in ("write", "edit", "multiedit"):
            if val not in by_path:
                by_path[val] = {"kind": "file", "path": val, "first_seen": ts,
                                "source": None, "runs": 0, "failed_runs": 0}
                cands.append(by_path[val])
            if kind == "write" and extra is not None:
                by_path[val]["source"] = extra
        elif kind == "bash":
            failed = results.get(extra, False)
            hit = False
            for c in by_path.values():
                if os.path.basename(c["path"]) in val:
                    c["runs"] += 1
                    c["failed_runs"] += failed
                    hit = True
            if not hit and INLINE.search(val):
                cands.append({"kind": "inline", "path": None, "first_seen": ts,
                              "source": val, "runs": 1, "failed_runs": int(failed)})
    for c in cands:
        if c["kind"] == "file" and os.path.isfile(c["path"]):
            c["source"] = Path(c["path"]).read_text(encoding="utf-8", errors="replace")
            c["on_disk"] = True
        else:
            c["on_disk"] = False
        c["lines"] = len((c["source"] or "").splitlines())
    return skill, cands


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--transcript")
    ap.add_argument("--cwd", default=os.getcwd())
    ap.add_argument("--skill", help="use the last invocation of THIS skill")
    ap.add_argument("--show", type=int, help="print candidate N in full")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()

    tp = Path(a.transcript) if a.transcript else default_transcript(a.cwd)
    if not tp or not tp.is_file():
        print(f"no transcript found (cwd {a.cwd})", file=sys.stderr)
        return 2
    skill, cands = scan(tp, a.skill)
    if skill is None:
        print(f"no skill invocation found in {tp}", file=sys.stderr)
        return 3
    sdir, why = resolve_skill_dir(skill, a.cwd)

    if a.show is not None:
        if not 1 <= a.show <= len(cands):
            print(f"--show must be 1..{len(cands)}", file=sys.stderr)
            return 4
        print(cands[a.show - 1]["source"] or "")
        return 0
    if a.json:
        print(json.dumps({"transcript": str(tp), "skill": skill,
                          "skill_dir": str(sdir) if sdir else None,
                          "skill_dir_problem": why, "candidates": cands}, indent=1))
        return 0

    print(f"transcript: {tp}")
    print(f"skill:      {skill}")
    print(f"skill dir:  {sdir or '-- ' + why}")
    print(f"candidates: {len(cands)} (written or run after the skill was invoked)")
    for i, c in enumerate(cands, 1):
        where = c["path"] or "inline command"
        state = "on disk" if c["on_disk"] else ("gone" if c["kind"] == "file" else "-")
        first = next((l for l in (c["source"] or "").splitlines() if l.strip()), "")[:70]
        print(f" {i}. {where}  [{c['lines']} lines, runs {c['runs']}, "
              f"failed {c['failed_runs']}, {state}, {c['first_seen'][:19]}Z]")
        print(f"    {first}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
