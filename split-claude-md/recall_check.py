#!/usr/bin/env python3
"""Recall check: does a fresh session still answer the same questions after a split?

    recall_check.py CLAUDE.md --pack split_<date>/QUESTIONS.md
                    (--before <backup of CLAUDE.md> | --manifest split_<date>/manifest.json)
                    [--claude <path>] [--max-calls 30] [--timeout 180] [--report <file>]

Two modes, judged on the final answer text only.

- RULE questions run with NO tools (`--tools ""`), so only the auto-loaded CLAUDE.md can
  answer; a rule moved behind a pointer fails AFTER and counts as LOST.
- FACT questions run with Read only (`--tools Read --restricted`), so the session may follow
  pointers into archives inside the temp copy. Per `claude --help`,
  `--restricted` "confines the file tools to the working directories (--add-dir included)".

Three copies of the notes set, each in its own temp folder: BEFORE (CLAUDE.md from the
backup or the manifest), AFTER (as it is now) and CONTROL (CLAUDE.md empty, rule questions
only). Per question: passed BEFORE and failed AFTER is LOST; failed BEFORE is BAD QUESTION and
does not count. Half or more of the rule questions passing in CONTROL means the pack is too
easy.

The pack holds 6 to 10 lines of `question | expected fragment | rule|fact`; blank lines and
`#` lines are not counted, and at least one line must be a rule. A fragment must hold a
letter or digit and must not appear in its own question (a refusal that repeats the
question would otherwise pass).

Judging: the fragment must appear in the JSON `result` text on identifier edges, after `*`
and backtick marks are removed, whitespace runs become one space and case is folded. An
identifier character is any Unicode letter or digit, `_` or `-`, so DB_PROD does not match
inside DB_PROD_BACKUP and TOKEN-1 does not match TOKEN-10 or TOKEN-1-OLD. An answer that
holds a refusal phrase (NOT IN MY INSTRUCTIONS / NOT IN MY NOTES) fails.

Exit 0: nothing lost. Exit 3: at least one LOST. Exit 2: cannot tell (bad input, a failed
or timed-out call, a pack that is too easy, the call cap, a copy that could not be built).
Every input check runs before the first call. A failed call is never retried, and no call
follows it.

The prompt goes on stdin: `--tools <tools...>` takes a list and swallows a trailing prompt
argument.
"""
import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import splitlib  # noqa: E402

PACK_MIN, PACK_MAX = 6, 10
BASE_FLAGS = ["-p", "--setting-sources", "project", "--no-session-persistence",
              "--strict-mcp-config", "--output-format", "json"]
MODE_FLAGS = {"rule": ["--tools", ""], "fact": ["--tools", "Read", "--restricted"]}
RULE_REFUSAL, FACT_REFUSAL = "NOT IN MY INSTRUCTIONS", "NOT IN MY NOTES"
RULE_PROMPT = ("You have NO tools in this session. Do not write tool calls, do not pretend to "
               "open or list files. Answer only from the project instructions already loaded in "
               "your context, in one line. If they do not say, reply exactly: " + RULE_REFUSAL +
               ". Question: {q}")
FACT_PROMPT = ("Answer in one line. You may use the Read tool on files in this folder, and follow "
               "any pointer the notes give. If the notes in this folder do not say, reply exactly: " +
               FACT_REFUSAL + ". Question: {q}")
# Only bold/italic stars and code backticks are markdown noise; `_` and `-` are part
# of identifiers (DB_PROD is not DBPROD). One definition of an identifier
# character, Unicode letters and digits plus `_` and `-`, used for both edges.
MARKS_RE = re.compile(r"[*`]")
SPACE_RE = re.compile(r"\s+")
ALNUM_RE = re.compile(r"[^\W_]")
EDGE_BEFORE, EDGE_AFTER = r"(?<![\w-])", r"(?![\w-])"


class Refused(Exception):
    """An input problem found before any call: exit 2."""


class CallFailed(Exception):
    """A call that failed or timed out: exit 2, no call after it."""


def norm(text):
    return SPACE_RE.sub(" ", MARKS_RE.sub("", text)).casefold()


def found(frag, answer):
    """The fragment on token edges in the answer; a refusal never passes."""
    a = norm(answer)
    if norm(RULE_REFUSAL) in a or norm(FACT_REFUSAL) in a:
        return False
    f = norm(frag)
    return re.search(EDGE_BEFORE + re.escape(f) + EDGE_AFTER, a) is not None


def read_pack(path):
    try:
        with open(path, encoding="utf-8") as fh:
            raw = fh.read().splitlines()
    except (OSError, UnicodeDecodeError) as e:
        raise Refused("cannot read the pack %s (%s)" % (path, type(e).__name__))
    out = []
    for n, line in enumerate(raw, 1):
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        parts = [p.strip() for p in s.split("|")]
        if len(parts) != 3 or not parts[0] or not parts[1]:
            raise Refused("pack line %d is not `question | expected fragment | rule|fact`: %r" % (n, s))
        if parts[2] not in ("rule", "fact"):
            raise Refused("pack line %d has kind %r; it must be rule or fact" % (n, parts[2]))
        if not ALNUM_RE.search(norm(parts[1])):
            raise Refused("pack line %d: the fragment %r holds no letter or digit" % (n, parts[1]))
        if norm(parts[1]) in norm(parts[0]):
            raise Refused("pack line %d: the fragment %r is in its own question, so any answer that "
                          "repeats the question would pass" % (n, parts[1]))
        out.append({"q": parts[0], "frag": parts[1], "kind": parts[2]})
    if not PACK_MIN <= len(out) <= PACK_MAX:
        raise Refused("the pack has %d question lines; it needs %d to %d" % (len(out), PACK_MIN, PACK_MAX))
    if not any(x["kind"] == "rule" for x in out):
        raise Refused("the pack has no rule line, so CONTROL cannot run; add at least one rule question")
    return out


def sha256_file(path):
    with open(path, "rb") as fh:
        return hashlib.sha256(fh.read()).hexdigest()


def inside(path, folder):
    rp, rf = os.path.realpath(path), os.path.realpath(folder)
    return os.path.commonpath([rp, rf]) == rf


def before_from_manifest(target, mpath):
    """The manifest is checked whole before any call. Returns (claude_backup, overrides,
    created): overrides maps a notes file's realpath to the backup it is read from, created
    names files the run made (absent in BEFORE)."""
    folder = os.path.dirname(os.path.realpath(target))
    try:
        with open(mpath, encoding="utf-8") as fh:
            man = json.load(fh)
    except (OSError, ValueError) as e:
        raise Refused("cannot read the manifest %s (%s)" % (mpath, type(e).__name__))
    if not isinstance(man, dict) or man.get("status") != "complete":
        raise Refused("the manifest's status is %r; only a complete run can be checked"
                      % (man.get("status") if isinstance(man, dict) else None))
    if not isinstance(man.get("folder"), str) or os.path.realpath(man["folder"]) != folder:
        raise Refused("the manifest names folder %r, not %s" % (man.get("folder"), folder))
    files = man.get("files")
    if not isinstance(files, list) or not files:
        raise Refused("the manifest lists no files")
    overrides, created, claude = {}, set(), None
    for f in files:
        if not isinstance(f, dict) or not isinstance(f.get("path"), str) or not f["path"]:
            raise Refused("a manifest entry has no path")
        # Both keys present, each a string or null, and null together
        if "pre_sha256" not in f or "backup" not in f:
            raise Refused("manifest entry %s has no pre_sha256 or backup key" % f["path"])
        pre, bk = f["pre_sha256"], f["backup"]
        if not (pre is None or isinstance(pre, str)) or not (bk is None or isinstance(bk, str)):
            raise Refused("manifest entry %s has a malformed pre_sha256 or backup" % f["path"])
        if (pre is None) != (bk is None):
            raise Refused("manifest entry %s has a pre_sha256 without a backup, or a backup without "
                          "a pre_sha256" % f["path"])
        if "\x00" in f["path"] or (bk is not None and "\x00" in bk):
            raise Refused("manifest entry %r holds a NUL character" % f["path"])
        p = os.path.join(folder, f["path"])
        if not inside(p, folder):
            raise Refused("manifest path %s resolves outside the folder" % f["path"])
        if bk is None:
            created.add(os.path.realpath(p))
            continue
        b = os.path.join(folder, bk)
        if not inside(b, folder):
            raise Refused("backup %s of %s resolves outside the folder" % (bk, f["path"]))
        if not os.path.isfile(b):
            raise Refused("backup %s of %s is missing" % (bk, f["path"]))
        try:
            ok = sha256_file(b) == pre
        except OSError as e:
            raise Refused("backup %s of %s cannot be read (%s)" % (bk, f["path"], type(e).__name__))
        if not ok:
            raise Refused("backup %s of %s is not at its pre_sha256" % (bk, f["path"]))
        if os.path.realpath(p) == os.path.realpath(target):
            claude = b
        else:
            overrides[os.path.realpath(p)] = b
    if claude is None:
        raise Refused("the manifest holds no backup of %s" % os.path.basename(target))
    return claude, overrides, created


def build_copy(copies, folder, claude_src, overrides=None, drop=(), empty_claude=False):
    """One temp copy: the notes set (splitlib.notes_set) plus CLAUDE.md. The folder is put in
    `copies` before anything is copied into it, so the caller removes it on any exit."""
    d = os.path.realpath(tempfile.mkdtemp(prefix="recallcopy"))
    copies.append(d)
    for p in splitlib.notes_set(folder):
        rp = os.path.realpath(p)
        if rp in drop:
            continue
        src = (overrides or {}).get(rp, p)
        shutil.copyfile(src, os.path.join(d, os.path.basename(p)))
    for rp, src in (overrides or {}).items():
        dst = os.path.join(d, os.path.basename(rp))
        if not os.path.exists(dst):
            shutil.copyfile(src, dst)
    if empty_claude:
        open(os.path.join(d, "CLAUDE.md"), "w").close()
    else:
        shutil.copyfile(claude_src, os.path.join(d, "CLAUDE.md"))
    return d


def session_folder(cwd):
    enc = re.sub(r"[^A-Za-z0-9]", "-", os.path.realpath(cwd))
    return os.path.join(os.path.expanduser("~"), ".claude", "projects", enc)


def clean_session(cwd, existed_before, left):
    """Remove the encoded session folder Claude Code made for this call's temp copy: only
    empty real directories, never a file. A folder that existed before the call, or
    one that is a symlink, is not this call's and is never touched."""
    top = session_folder(cwd)
    if not os.path.lexists(top):
        return
    if existed_before or os.path.islink(top):
        left.append((top, "it existed before the call or is a symlink"))
        return
    for root, dirs, files in os.walk(top, topdown=False, followlinks=False):
        if files or any(os.path.islink(os.path.join(root, x)) for x in dirs):
            continue
        try:
            os.rmdir(root)
        except OSError:
            pass
    if os.path.lexists(top):
        left.append((top, "it holds files"))


def ask(claude, cwd, kind, question, timeout):
    prompt = (RULE_PROMPT if kind == "rule" else FACT_PROMPT).format(q=question)
    try:
        r = subprocess.run([claude] + BASE_FLAGS + MODE_FLAGS[kind], cwd=cwd,
                           input=prompt.encode("utf-8"), capture_output=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        raise CallFailed("timed out after %d s" % timeout)
    except OSError as e:
        raise CallFailed("could not start %s (%s)" % (claude, type(e).__name__))
    try:
        out = r.stdout.decode("utf-8")
        err = r.stderr.decode("utf-8", "replace")
    except UnicodeDecodeError:
        raise CallFailed("stdout is not UTF-8")
    if r.returncode != 0:
        raise CallFailed("exit %d: %s" % (r.returncode, (err or out).strip()[:200]))
    try:
        j = json.loads(out)
    except ValueError:
        raise CallFailed("stdout is not JSON: %r" % out[:200])
    if not isinstance(j, dict) or j.get("is_error") is not False or not isinstance(j.get("result"), str):
        raise CallFailed("the result is an error or has no text: %r" % out[:200])
    return j["result"]


def main(argv=None):
    ap = argparse.ArgumentParser(description="Recall check for a CLAUDE.md split.")
    ap.add_argument("target", help="the CLAUDE.md the split edited")
    ap.add_argument("--pack", required=True)
    ap.add_argument("--before", help="the backup of CLAUDE.md taken before the split")
    ap.add_argument("--manifest", help="the rotate.py run's manifest.json")
    ap.add_argument("--claude", default=shutil.which("claude") or "claude")
    ap.add_argument("--max-calls", type=int, default=30)
    ap.add_argument("--timeout", type=int, default=180)
    ap.add_argument("--report")
    a = ap.parse_args(argv)

    lines = []

    def say(s):
        lines.append(s)
        print(s)

    def finish(code):
        say("VERDICT exit %d" % code)
        if a.report:
            with open(a.report, "w", encoding="utf-8") as fh:
                fh.write("\n".join(lines) + "\n")
        return code

    target = os.path.realpath(a.target)
    folder = os.path.dirname(target)
    say("RECALL CHECK  %s" % target)
    try:
        if bool(a.before) == bool(a.manifest):
            raise Refused("give exactly one of --before <backup> or --manifest <manifest.json>")
        if not os.path.isfile(target):
            raise Refused("%s is not a file" % a.target)
        pack = read_pack(a.pack)
        overrides, created = {}, set()
        if a.manifest:
            claude_before, overrides, created = before_from_manifest(target, a.manifest)
            current = [os.path.basename(p) for p in splitlib.notes_set(folder)
                       if os.path.realpath(p) not in overrides and os.path.realpath(p) not in created]
            say("BEFORE: CLAUDE.md from %s; notes taken from the current folder: %s"
                % (os.path.relpath(claude_before, folder), ", ".join(current) or "none"))
        else:
            claude_before = a.before
            # the backup must be a file inside the project folder, symlinks resolved
            if not os.path.isfile(claude_before) or not inside(claude_before, folder):
                raise Refused("--before %s is not a file inside %s" % (a.before, folder))
            say("BEFORE: CLAUDE.md from %s; every other notes file from the current folder"
                % os.path.relpath(os.path.realpath(claude_before), folder))
        say("Phase 0 deletions are checked by the Phase 0 loss check.")
        rules = [x for x in pack if x["kind"] == "rule"]
        need = 2 * len(pack) + len(rules)
        if need > a.max_calls:
            raise Refused("this pack needs %d calls, more than --max-calls %d" % (need, a.max_calls))
    except Refused as e:
        say("REFUSED: %s" % e)
        return finish(2)
    except (ValueError, TypeError) as e:     # any other bad input, never exit 1
        say("REFUSED: an input could not be read (%s: %s)" % (type(e).__name__, e))
        return finish(2)

    left, copies, res = [], [], {}
    try:
        try:
            before = build_copy(copies, folder, claude_before, overrides, drop=created)
            after = build_copy(copies, folder, target)
            control = build_copy(copies, folder, target, empty_claude=True)
        except OSError as e:
            say("FAILED: could not build the temp copies (%s)" % type(e).__name__)
            return finish(2)
        for name, cwd, items in (("BEFORE", before, pack), ("AFTER", after, pack), ("CONTROL", control, rules)):
            for x in items:
                existed = os.path.lexists(session_folder(cwd))
                try:
                    ans = ask(a.claude, cwd, x["kind"], x["q"], a.timeout)
                except CallFailed as e:
                    say("FAILED: %s call for question %d (%s): %s" % (name, pack.index(x) + 1, x["q"], e))
                    return finish(2)
                finally:
                    clean_session(cwd, existed, left)
                res[(name, id(x))] = found(x["frag"], ans)
    finally:
        for d in copies:
            shutil.rmtree(d, ignore_errors=True)
        seen = {}
        for d, why in left:                   # one line per folder, its first reason
            seen.setdefault(d, why)
        for d in sorted(seen):
            say("LEFT: %s was not removed: %s" % (d, seen[d]))

    lost = bad = 0
    for n, x in enumerate(pack, 1):
        b, af = res[("BEFORE", id(x))], res[("AFTER", id(x))]
        tag = "BAD QUESTION" if not b else ("KEPT" if af else "LOST")
        lost += tag == "LOST"
        bad += tag == "BAD QUESTION"
        say("%s: %d %s (%s)" % (tag, n, x["q"], x["kind"]))
    easy = sum(1 for x in rules if res[("CONTROL", id(x))])
    say("CONTROL: %d of %d rule questions pass with an empty CLAUDE.md" % (easy, len(rules)))
    if easy * 2 >= len(rules):
        say("The pack is too easy: rewrite the rule questions so the fragment is not in the question "
            "or in general knowledge.")
        return finish(2)
    if bad == len(pack):
        say("No question passed BEFORE, so nothing was measured.")
        return finish(2)
    return finish(3 if lost else 0)


if __name__ == "__main__":
    sys.exit(main())
