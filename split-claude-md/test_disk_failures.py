#!/usr/bin/env python3
"""The disk-failure rule, proven by enumeration.

One boundary per segment: rotate.py up to the pending manifest
(rotate.before_manifest), rotate.py's undo up to its first change
(rotate.undo_checks), and loss_check.py's main. This file:

  1. lists by AST every filesystem call reachable from the three segments
     (the raising callees, os.path.realpath, and the existence predicates),
  2. runs a fixed list of scenarios once each, recording which sites each one
     reaches inside a segment,
  3. re-runs a scenario per reached site with a failure injected at that site
     only, and asserts exit 2, no escape, no file changed, and one CANNOT TELL
     line that names the path the error carries and every new path,
  4. audits the existence predicates and the handlers that could turn a disk
     error into a value,
  5. runs the named disk-failure tests.

Every fixture is a synthetic string built here and written to a mkdtemp
folder. Row 0 is a CONTROL with a known answer: if it fails, the harness is
broken rather than the code.

Run:  python3 test_disk_failures.py
      python3 test_disk_failures.py --target <copy of this folder> --site <file>:<line>
The second form is the planted-call control's child: it imports rotate,
loss_check and splitlib from the copy, injects at one site only and prints
only its DISK SITES, FAIL site, UNREACHED and summary lines.
"""

import ast
import builtins
import io
import os
import posixpath
import re
import shutil
import stat
import subprocess
import sys
import tempfile
from contextlib import redirect_stderr, redirect_stdout

HERE = os.path.dirname(os.path.abspath(__file__))


def _target_args(argv):
    target, site = None, None
    if "--target" in argv:
        target = os.path.abspath(argv[argv.index("--target") + 1])
    if "--site" in argv:
        site = argv[argv.index("--site") + 1]
    return target, site


TARGET, ONLY_SITE = _target_args(sys.argv[1:])
CODE_DIR = TARGET or HERE
sys.path.insert(0, CODE_DIR)
import rotate  # noqa: E402
import loss_check  # noqa: E402
import splitlib  # noqa: E402
import test_rotate_undo as tru  # noqa: E402
import test_loss_check as tlc  # noqa: E402

MISSING = object()
FILES = ("rotate.py", "loss_check.py", "splitlib.py")
MODULES = {"rotate.py": rotate, "loss_check.py": loss_check, "splitlib.py": splitlib}
RAISING = {"open", "os.listdir", "os.scandir", "os.stat", "os.lstat", "os.makedirs", "os.mkdir",
           "os.remove", "os.unlink", "os.rmdir", "os.rename", "os.replace", "os.fsync",
           "shutil.copy", "shutil.copy2", "shutil.copyfile", "shutil.copystat", "shutil.move",
           "shutil.rmtree"}
REALPATH = "os.path.realpath"
# K.2: decided by what a function does, not by its module. abspath and relpath call
# os.getcwd() on a relative path, so they are sites as realpath is, injected with the error a
# deleted working folder raises.
CWD_CALLS = {"os.path.abspath", "os.path.relpath"}
PREDICATES = {"os.path.isfile", "os.path.isdir", "os.path.exists", "os.path.lexists", "os.path.islink"}
NOT_DISK = {"os.path.join", "os.path.basename", "os.path.dirname",
            "os.path.normpath", "os.path.commonpath", "os.path.expanduser",
            "os.path.isabs", "os.path.splitext"}

# UNREACHED_OK: (file, enclosing function, callee, ordinal of that callee in the function) ->
# reason. Two reason forms only: "handler" (the call sits in an except or finally body of its
# own function) or "fixture: <what no scenario can build>".
UNREACHED_OK = {
    ("rotate.py", "write_manifest", "os.remove", 0): "handler",
}

# The predicate and handler audit's exemptions, by file and enclosing
# function, never by line: (file, function, name) -> why a False on PermissionError, or the
# value this handler returns, cannot change an exit code or a fact written to disk.
EXEMPT = {
    ("rotate.py", "before_manifest", "os.path.isfile"):
        "argument check: a False already exits 2 (file, --todo or --hoisted missing)",
    ("rotate.py", "before_manifest", "os.path.isdir"):
        "argument check: a False already exits 2 (--root folder missing)",
    ("rotate.py", "undo_checks", "os.path.isdir"):
        "argument check: a False already exits 2 (folder missing)",
    ("loss_check.py", "main", "os.path.isfile"):
        "argument check: a False already exits 2 (an input file missing)",
    ("rotate.py", "write_manifest", "os.path.lexists"):
        "cleanup in the handler of a failed manifest write: the error is re-raised, so the exit "
        "is 2 whatever it answers",
    ("rotate.py", "undone_name", "os.path.lexists"):
        "a free name for the undone folder: called after undo's first change (outside the "
        "segments) and in half_done for message text only",
    ("rotate.py", "pre_manifest_failure", "os.path.lexists"):
        "message text: it names a leftover on a cannot-tell line whose exit is already 2",
    ("splitlib.py", "stat_of", "except"):
        "the absence rule itself: FileNotFoundError, and nothing else, is absence",
    ("splitlib.py", "token_stat_of", "except"):
        "the absence rule widened for pointer candidates: NotADirectoryError and ENAMETOOLONG are absence "
        "there, nothing else",
}

SENTINEL_NAME = "DISK-SENTINEL"
ORIGINALS = dict([(n, (os, n[3:], getattr(os, n[3:]))) for n in RAISING if n.startswith("os.")]
                 + [(n, (shutil, n[7:], getattr(shutil, n[7:]))) for n in RAISING if n.startswith("shutil.")]
                 + [(REALPATH, (posixpath, "realpath", posixpath.realpath))]
                 + [(n, (posixpath, n[8:], getattr(posixpath, n[8:]))) for n in sorted(CWD_CALLS)])
TALLY = re.compile(r"\d+/\d+ passed")


# ---------------------------------------------------------------- enumeration (static)

def dotted(node):
    """'os.path.realpath' for a Call's func, 'open' for the builtin, else None."""
    parts = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        parts.append(node.id)
        return ".".join(reversed(parts))
    return None


def parse_files(sources=None):
    out = {}
    for f in FILES:
        if sources and f in sources:
            src = sources[f]
        else:
            with open(os.path.join(CODE_DIR, f), encoding="utf-8") as fh:
                src = fh.read()
        out[f] = ast.parse(src)
    return out


def qualified(tree):
    """{node: qualified name of its innermost enclosing def or class}, for every node."""
    owner = {}

    def visit(node, stack):
        for ch in ast.iter_child_nodes(node):
            if isinstance(ch, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                owner[ch] = ".".join(stack) or "<module>"
                visit(ch, stack + [ch.name])
            else:
                owner[ch] = ".".join(stack) or "<module>"
                visit(ch, stack)
    visit(tree, [])
    return owner


def enumerate_sites(trees, segments):
    """The static half of the injection test. segments: [(file, top-level def name)]. Returns a dict:
    reach (set of (file, name)), sites {key: (file, callee, lo, hi, qual, ordinal)},
    predicates [(file, line, qual, name)], unclassified [lines], ambiguous [lines]."""
    defs = {}
    for f, tree in trees.items():
        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.ClassDef)):
                defs[(f, node.name)] = node
    reach, todo = set(), [s for s in segments if s in defs]
    while todo:
        k = todo.pop()
        if k in reach:
            continue
        reach.add(k)
        f, _ = k
        for n in ast.walk(defs[k]):
            if isinstance(n, ast.Name) and (f, n.id) in defs:
                todo.append((f, n.id))
            if (isinstance(n, ast.Attribute) and isinstance(n.value, ast.Name)
                    and n.value.id == "splitlib" and ("splitlib.py", n.attr) in defs):
                todo.append(("splitlib.py", n.attr))
    out = {"reach": reach, "sites": {}, "predicates": [], "unclassified": [], "ambiguous": []}
    calls = []      # every raising call, one entry per call (two on one line overlap)
    owners = dict((f, qualified(t)) for f, t in trees.items())
    seen = set()
    for f, name in sorted(reach):
        for n in ast.walk(defs[(f, name)]):
            if not isinstance(n, ast.Call) or id(n) in seen:
                continue
            seen.add(id(n))
            callee = dotted(n.func)
            if callee is None:
                continue
            qual = owners[f].get(n, name)
            if callee in RAISING or callee == REALPATH or callee in CWD_CALLS:
                calls.append((f, callee, n.lineno, n.end_lineno or n.lineno))
                out["sites"].setdefault((f, callee, n.lineno, n.end_lineno or n.lineno), qual)
            elif callee in PREDICATES:
                out["predicates"].append((f, n.lineno, qual, callee))
            elif callee in NOT_DISK:
                pass
            elif callee.startswith(("os.", "shutil.")):
                out["unclassified"].append("UNCLASSIFIED %s:%d %s" % (f, n.lineno, callee))
    # ordinal of each site among the same callee in the same function, in line order
    keyed, count = {}, {}
    for (f, callee, lo, hi), qual in sorted(out["sites"].items(), key=lambda x: (x[0][0], x[0][2], x[0][1])):
        k = (f, qual, callee)
        keyed[(f, callee, lo, hi)] = (qual, count.get(k, 0))
        count[k] = count.get(k, 0) + 1
    out["sites"] = keyed
    by = {}
    for (f, callee, lo, hi) in calls:
        by.setdefault((f, callee), []).append((lo, hi))
    for (f, callee), spans in sorted(by.items()):
        spans.sort()
        for a, b in zip(spans, spans[1:]):
            if b[0] <= a[1]:
                out["ambiguous"].append("AMBIGUOUS %s:%d %s" % (f, b[0], callee))
    return out


# K.3: the callees rotate.main's own body may call; anything else is a call
# outside a segment's boundary. os.path.abspath is not among them (it moved
# into undo_checks); cannot_tell and pre_manifest_failure only because they sit in the
# boundary's handler.
MAIN_ALLOW = {"argparse.ArgumentParser", "ap.add_argument", "ap.parse_args", "ap.error", "date.today",
              "<expr>.isoformat", "<expr>.join", "set", "isinstance", "undo", "before_manifest",
              "after_manifest", "cannot_tell", "pre_manifest_failure"}


def callee_name(node):
    """dotted() with a call or subscript base written as '<expr>'."""
    parts = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        parts.append(node.id)
        return ".".join(reversed(parts))
    return "<expr>." + ".".join(reversed(parts))


def main_outside_boundary(tree):
    """K.3: a 'MAIN OUTSIDE BOUNDARY rotate.py:<line> <callee>' line for every call in
    rotate.main's own body whose callee is not in MAIN_ALLOW."""
    mains = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "main"]
    if len(mains) != 1:
        return ["MAIN OUTSIDE BOUNDARY rotate.py: main occurs %d times" % len(mains)]
    return ["MAIN OUTSIDE BOUNDARY rotate.py:%d %s" % (n.lineno, callee_name(n.func))
            for n in own_nodes(mains[0].body) if isinstance(n, ast.Call)
            and callee_name(n.func) not in MAIN_ALLOW]


def site_name(key):
    f, callee, lo, _hi = key
    return "%s:%d %s" % (f, lo, callee)


def ok_key(key, sites):
    f, callee, lo, hi = key
    qual, k = sites[key]
    return (f, qual, callee, k)


def in_handler(trees, key):
    """'handler': the call sits in an except or finally body of its own function."""
    f, callee, lo, hi = key
    for node in ast.walk(trees[f]):
        bodies = []
        if isinstance(node, ast.Try):
            bodies = [h.body for h in node.handlers] + [node.finalbody]
        for body in bodies:
            for st in body:
                for n in ast.walk(st):
                    if (isinstance(n, ast.Call) and dotted(n.func) == callee and n.lineno == lo):
                        return True
    return False


# ---------------------------------------------------------------- the hit recorder

class Recorder(object):
    """Wraps every raising callee and realpath in its module (os, os.path, shutil) and
    `open` as a module global of the three files. A hit is recorded only when the caller's
    file is one of the three, its line falls in a site's range for that callee, and a
    SEGMENTS function's code object is on the stack. One site may be set to raise at its
    first in-segment hit; every later call passes through."""

    def __init__(self, sites, seg_codes, sentinel):
        self.by = {}
        for key in sites:
            f, callee, lo, hi = key
            self.by.setdefault((f, callee), []).append((lo, hi, key))
        self.seg_codes = seg_codes
        # each file as its frames name it: a code object's co_filename
        self.files = dict((MODULES[f].cannot_tell.__code__.co_filename if f != "splitlib.py"
                           else MODULES[f].sha256.__code__.co_filename, f) for f in FILES)
        self.sentinel = sentinel
        self.hits = []
        self.seg_seen = set()
        self.inject, self.fired = None, 0
        self.saved = []

    def _seg(self, frame):
        found = False
        while frame is not None:
            for i, c in enumerate(self.seg_codes):
                if frame.f_code is c:
                    self.seg_seen.add(i)
                    found = True
            frame = frame.f_back
        return found

    def wrap(self, callee, orig):
        rec = self

        def wrapper(*a, **k):
            fr = sys._getframe(1)
            f = rec.files.get(fr.f_code.co_filename)     # no path call here: realpath is wrapped
            if f is not None:
                for lo, hi, key in rec.by.get((f, callee), ()):
                    if lo <= fr.f_lineno <= hi and rec._seg(fr):
                        if key not in rec.hits:
                            rec.hits.append(key)
                        if key == rec.inject and not rec.fired:
                            rec.fired += 1
                            if callee == REALPATH:
                                raise ValueError("disk failure injected")
                            if callee in CWD_CALLS:     # K.2: what a deleted working folder raises
                                raise FileNotFoundError(2, "disk failure injected", rec.sentinel)
                            raise PermissionError(13, "disk failure injected", rec.sentinel)
                        break
            return orig(*a, **k)
        return wrapper

    def install(self):
        targets = [(os, n[3:]) for n in RAISING if n.startswith("os.")]
        targets += [(shutil, n[7:]) for n in RAISING if n.startswith("shutil.")]
        targets.append((posixpath, "realpath"))
        targets += [(posixpath, n[8:]) for n in sorted(CWD_CALLS)]
        for mod, name in targets:
            orig = getattr(mod, name)
            callee = (("os." if mod is os else "shutil." if mod is shutil else "os.path.") + name)
            self.saved.append((mod, name, orig))
            setattr(mod, name, self.wrap(callee, orig))
        for f in FILES:
            m = MODULES[f]
            self.saved.append((m, "open", m.__dict__.get("open", MISSING)))
            setattr(m, "open", self.wrap("open", builtins.open))

    def uninstall(self):
        for mod, name, orig in reversed(self.saved):
            if orig is MISSING:
                if name in mod.__dict__:
                    delattr(mod, name)
            else:
                setattr(mod, name, orig)
        self.saved = []

    @staticmethod
    def restored():
        """The names every wrapped callee is again its original (`is`)."""
        bad = [n for n, (mod, name, orig) in ORIGINALS.items() if getattr(mod, name) is not orig]
        bad += ["%s open" % f for f in FILES if "open" in MODULES[f].__dict__]
        return bad


# ---------------------------------------------------------------- scenarios

def mk(tmp):
    d = os.path.realpath(tempfile.mkdtemp(prefix="disk-", dir=tmp))
    return d


def write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb" if isinstance(text, bytes) else "w",
              **({} if isinstance(text, bytes) else {"encoding": "utf-8"})) as fh:
        fh.write(text)
    return path


def call_rotate(argv):
    buf, old = io.StringIO(), sys.argv
    sys.argv = ["rotate.py"] + list(argv)
    try:
        with redirect_stdout(buf), redirect_stderr(buf):
            try:
                rc = rotate.main()
            except SystemExit as e:
                rc = e.code if isinstance(e.code, int) else 2
            except Exception as e:                              # noqa: BLE001
                rc = "raised %s: %s" % (type(e).__name__, e)
    finally:
        sys.argv = old
    return rc, buf.getvalue()


def call_loss(argv):
    buf = io.StringIO()
    with redirect_stdout(buf), redirect_stderr(buf):
        try:
            rc = loss_check.main(list(argv))
        except SystemExit as e:
            rc = e.code if isinstance(e.code, int) else 2
        except Exception as e:                                  # noqa: BLE001
            rc = "raised %s: %s" % (type(e).__name__, e)
    return rc, buf.getvalue()


def applied(tmp, claude, extra=None):
    """A project folder after an uninjected --apply run (the undo scenarios' setup)."""
    d, root = mk(tmp), mk(tmp)
    p = write(os.path.join(d, "CLAUDE.md"), claude)
    for n, t in (extra or {}).items():
        write(os.path.join(d, n), t)
    rc, out = call_rotate([p] + tru.U_ARGS + ["--root", root, "--apply"])
    return d, root, p, rc


def fx_rot_dry(tmp):
    d, root = mk(tmp), mk(tmp)
    p = write(os.path.join(d, "CLAUDE.md"), tru.U_CLAUDE)
    write(os.path.join(d, tru.INDEX), tru.IDX_OLD)
    write(os.path.join(d, "TODO.md"), "# Todo\n\n- [ ] Water the plants on Friday\n")
    return {"run": call_rotate, "argv": [p] + tru.U_ARGS + ["--root", root],
            "watch": [d, root], "project": d}


def fx_rot_apply(tmp):
    d, root = mk(tmp), mk(tmp)
    p = write(os.path.join(d, "CLAUDE.md"), tru.U_CLAUDE)
    write(os.path.join(d, tru.INDEX), tru.IDX_OLD)
    write(os.path.join(d, tru.ARCH), tru.ARCH_OLD)
    write(os.path.join(d, tru.U_RUN, "notes.txt"), "An earlier hand-made work folder.\n")
    return {"run": call_rotate, "argv": [p] + tru.U_ARGS + ["--root", root, "--apply"],
            "watch": [d, root], "project": d}


def fx_rot_refused(tmp):
    d, root = mk(tmp), mk(tmp)
    p = write(os.path.join(d, "CLAUDE.md"), tru.H_CLAUDE_RULE)
    return {"run": call_rotate, "argv": [p] + tru.U_ARGS + ["--root", root, "--apply"],
            "watch": [d, root], "project": d}


def fx_rot_hoisted(tmp):
    a, root = mk(tmp), mk(tmp)
    p = write(os.path.join(a, "proj", "CLAUDE.md"), tru.H_CLAUDE_RULE)
    h = write(os.path.join(a, "CLAUDE.md"), "# Global rules\n\nNever force the paper tray.\n")
    return {"run": call_rotate, "argv": [p] + tru.U_ARGS + ["--root", root, "--apply", "--hoisted", h],
            "watch": [a, root], "project": os.path.dirname(p)}


def fx_undo_date_dry(tmp):
    d, root, p, _rc = applied(tmp, tru.U_CLAUDE, {tru.INDEX: tru.IDX_OLD, tru.ARCH: tru.ARCH_OLD})
    return {"run": call_rotate, "argv": [p, "--undo", "2026-02-15"], "watch": [d, root], "project": d}


def fx_undo_dir_apply(tmp):
    d, root, p, _rc = applied(tmp, tru.U_CLAUDE, {tru.INDEX: tru.IDX_OLD, tru.ARCH: tru.ARCH_OLD})
    return {"run": call_rotate, "argv": [p, "--undo", tru.U_RUN, "--apply"], "watch": [d, root], "project": d}


def fx_rot_hoisted_local(tmp):
    """A --hoisted file inside the project folder: <F>/.claude/CLAUDE.md."""
    d, root = mk(tmp), mk(tmp)
    p = write(os.path.join(d, "CLAUDE.md"), tru.H_CLAUDE_RULE)
    h = write(os.path.join(d, ".claude", "CLAUDE.md"), "# Local rules\n\nNever force the paper tray.\n")
    return {"run": call_rotate, "argv": [p] + tru.U_ARGS + ["--root", root, "--apply", "--hoisted", h],
            "watch": [d, root], "project": d}


def fx_loss_lazy(tmp):
    """A --lazy file also in the notes set, and a same-heading pointer that resolves
    (POINTED)."""
    d = mk(tmp)
    rule = "Never push the nightly build without a dry run first."
    b = write(os.path.join(d, "CLAUDE.md.backup-before-split-2026-02-01"),
              "# P\n\n## Notes\n\n" + rule + "\n")
    a = write(os.path.join(d, "CLAUDE.md"), "# P\n\n## Notes\n\nSee `NOTES.md`, same heading.\n")
    n = write(os.path.join(d, "NOTES.md"), "# Notes\n\n## Notes\n\n" + rule + "\n")
    return {"run": call_loss, "argv": ["--before", b, "--after", a, "--lazy", n],
            "watch": [d], "project": d}


def fx_loss(tmp):
    d = mk(tmp)
    b = write(os.path.join(d, "CLAUDE.md.backup-before-split-2026-02-01"), tlc.BEFORE)
    a = write(os.path.join(d, "CLAUDE.md"),
              tlc.AFTER_MOVED + "\nDetail: see `CLAUDE_DECISIONS_INDEX.md`.\n")
    write(os.path.join(d, "CLAUDE_DECISIONS_2026-01.md"), tlc.ARCHIVE)
    write(os.path.join(d, "CLAUDE_DECISIONS_INDEX.md"),
          "# Index\n\n## Archives\n\n- `CLAUDE_DECISIONS_2026-01.md`\n")
    acc = write(os.path.join(d, "accept.txt"), "nightly widget export straight\n")
    rep = os.path.join(d, "LOSS.md")
    return {"run": call_loss, "argv": ["--before", b, "--after", a, "--accept-file", acc, "--report", rep],
            "watch": [d], "project": d}


# (name, fixture builder, expected uninjected exit). Rows may be added, never removed.
SCENARIOS = [
    ("ROT-DRY", fx_rot_dry, 0),
    ("ROT-APPLY", fx_rot_apply, 0),
    ("ROT-REFUSED", fx_rot_refused, 3),
    ("ROT-HOISTED", fx_rot_hoisted, 0),
    ("UNDO-DATE-DRY", fx_undo_date_dry, 0),
    ("UNDO-DIR-APPLY", fx_undo_dir_apply, 0),
    ("LOSS", fx_loss, 0),
    ("ROT-HOISTED-LOCAL", fx_rot_hoisted_local, 0),
    ("LOSS-LAZY", fx_loss_lazy, 0),
]


def snapshot(folders):
    files, dirs = {}, set()
    for top in folders:
        for dp, dn, fn in os.walk(top):
            for n in dn:
                dirs.add(os.path.join(dp, n))
            for n in fn:
                p = os.path.join(dp, n)
                try:
                    with open(p, "rb") as fh:
                        files[p] = fh.read()
                except OSError:
                    files[p] = None
    return files, dirs


# ---------------------------------------------------------------- the injection test

def injection(trees, seg_funcs, tmp, emit, only=None):
    """The injection test: returns a dict of counts and lists; emit(line) prints a result line."""
    segs = [("rotate.py", "before_manifest"), ("rotate.py", "undo_checks"), ("loss_check.py", "main")]
    en = enumerate_sites(trees, segs)
    sites = en["sites"]
    nfile = dict((f, sum(1 for k in sites if k[0] == f)) for f in FILES)
    emit("DISK SITES %d (rotate.py %d, loss_check.py %d, splitlib.py %d) PREDICATES %d"
         % (len(sites), nfile["rotate.py"], nfile["loss_check.py"], nfile["splitlib.py"],
            len(en["predicates"])))
    res = {"en": en, "baseline": [], "red": [], "unreached": [], "ok_bad": [], "stale_ok": [],
           "leak": [], "nohits": [], "restored": [], "runs": 0, "fails": [], "first": {}}
    for name in ("undo", "main"):
        if ("rotate.py", name) in en["reach"]:
            res["leak"].append("SEGMENT LEAK rotate.py %s" % name)
    seg_codes = [f.__code__ for f in seg_funcs]
    sentinel = os.path.join(tmp, SENTINEL_NAME)
    # uninjected runs: the hit set
    first, seg_seen = {}, set()
    for sname, build, want in SCENARIOS:
        fx = build(tmp)
        rec = Recorder(sites, seg_codes, sentinel)
        rec.install()
        try:
            rc, out = fx["run"](fx["argv"])
        finally:
            rec.uninstall()
        bad = Recorder.restored()
        if bad:
            res["restored"].append("NOT RESTORED after %s: %s" % (sname, ", ".join(bad)))
        if rc != want or rc == 2:
            res["baseline"].append("BASELINE %s: exit %s" % (sname, rc))
        for key in rec.hits:
            first.setdefault(key, sname)
        seg_seen |= rec.seg_seen
    res["first"] = first
    if not first:
        res["nohits"].append("NO HITS")
    # NO HITS per segment: no hit was recorded with that segment's code object on the stack
    for i, fn in enumerate(seg_funcs):
        if i not in seg_seen:
            res["nohits"].append("NO HITS %s.%s" % (fn.__module__, fn.__name__))
    # UNREACHED and UNREACHED_OK
    okeys = dict((ok_key(k, sites), k) for k in sites)
    n_handler = n_fixture = 0
    for k, why in UNREACHED_OK.items():
        if k not in okeys:
            res["stale_ok"].append("STALE UNREACHED_OK %r" % (k,))
            continue
        key = okeys[k]
        if why == "handler":
            n_handler += 1
            if not in_handler(trees, key):
                res["ok_bad"].append("UNREACHED_OK NOT IN HANDLER %s" % site_name(key))
        elif why.startswith("fixture: ") and len(why) > len("fixture: "):
            n_fixture += 1
        else:
            res["ok_bad"].append("UNREACHED_OK BAD REASON %s" % site_name(key))
    for key in sorted(sites, key=lambda k: (k[0], k[2])):
        if key not in first and ok_key(key, sites) not in UNREACHED_OK:
            res["unreached"].append("UNREACHED %s" % site_name(key))
    # injection, one site per run
    for key in sorted(first, key=lambda k: (k[0], k[2])):
        if only and site_name(key).split(" ")[0] != only:
            continue
        sname = first[key]
        build, want = [(b, w) for n, b, w in SCENARIOS if n == sname][0]
        fx = build(tmp)
        before_files, before_dirs = snapshot(fx["watch"])
        rec = Recorder(sites, seg_codes, sentinel)
        rec.inject = key
        rec.install()
        try:
            rc, out = fx["run"](fx["argv"])
        finally:
            rec.uninstall()
        res["runs"] += 1
        bad = Recorder.restored()
        if bad:
            res["restored"].append("NOT RESTORED after %s: %s" % (site_name(key), ", ".join(bad)))
        after_files, after_dirs = snapshot(fx["watch"])
        reasons = []
        if rec.fired != 1:
            reasons.append("not fired")
        if rc != 2:
            reasons.append("exit %s" % rc)
        if not isinstance(rc, int):
            reasons.append("escaped %s" % rc)
        for p, data in sorted(before_files.items()):
            rel = os.path.relpath(p, fx["project"])
            if p not in after_files:
                reasons.append("removed %s" % rel)
            elif after_files[p] != data:
                reasons.append("changed %s" % rel)
        line = next((l for l in out.splitlines() if l.startswith("CANNOT TELL: ")), None)
        if line is None:
            reasons.append("no CANNOT TELL line")
        else:
            want_txt = "ValueError" if key[1] == REALPATH else sentinel
            if want_txt not in line:
                reasons.append("sentinel missing")
            new = sorted((set(after_files) - set(before_files)) | (after_dirs - before_dirs))
            for p in new:
                rel = os.path.relpath(p, fx["project"])
                if p not in line and rel not in line:
                    reasons.append("unnamed %s" % rel)
            if not new and "nothing was changed" not in line:
                reasons.append("unnamed nothing was changed")
        if reasons:
            res["red"].append(key)
            for r in reasons:
                emit("FAIL site %s [%s]: %s" % (site_name(key), sname, r))
    emit("INJECTED RUNS %d RED SITES %d UNREACHED %d UNREACHED_OK %d (handler %d, fixture %d)"
         % (res["runs"], len(res["red"]), len(res["unreached"]), len(UNREACHED_OK), n_handler, n_fixture))
    for ln in res["unreached"]:
        emit(ln)
    return res


# ---------------------------------------------------------------- predicate and handler audit

SWALLOW_TYPES = (OSError, ValueError, UnicodeDecodeError, Exception, BaseException)
NOT_SWALLOW_CALLS = ("cannot_tell", "half_done", "failed")


def handler_types(node):
    """The exception classes an except clause names (None for a bare except)."""
    if node.type is None:
        return None
    elts = node.type.elts if isinstance(node.type, ast.Tuple) else [node.type]
    out = []
    for e in elts:
        name = dotted(e) or ""
        obj = getattr(builtins, name, None)
        if obj is None and name.startswith("splitlib."):
            obj = getattr(splitlib, name.split(".", 1)[1], None)
        if obj is None:
            obj = getattr(splitlib, name, None) or getattr(rotate, name, None)
        out.append(obj)
    return out


def own_nodes(body):
    stack, out = list(body), []
    while stack:
        n = stack.pop()
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda, ast.ClassDef)):
            continue
        out.append(n)
        stack.extend(ast.iter_child_nodes(n))
    return out


def audit(trees):
    """The predicate and handler audit: (predicate lines, swallow lines, stale lines, counts)."""
    preds, swallows, used = [], [], set()
    n_pred = n_scope = 0
    for f in FILES:
        owner = qualified(trees[f])
        for n in ast.walk(trees[f]):
            if isinstance(n, ast.Call) and dotted(n.func) in PREDICATES:
                n_pred += 1
                key = (f, owner.get(n, "<module>"), dotted(n.func))
                if key in EXEMPT:
                    used.add(key)
                else:
                    preds.append("PREDICATE %s:%d %s %s" % (f, n.lineno, key[1], key[2]))
            if isinstance(n, ast.ExceptHandler):
                types = handler_types(n)
                in_scope = types is None or any(
                    isinstance(t, type) and (issubclass(t, (OSError, ValueError, UnicodeDecodeError))
                                             or t in (Exception, BaseException)) for t in types)
                if not in_scope:
                    continue
                n_scope += 1
                fine = False
                for x in own_nodes(n.body):
                    if isinstance(x, ast.Raise):
                        fine = True
                    if isinstance(x, ast.Return) and x.value is not None:
                        if isinstance(x.value, ast.Constant) and x.value.value == 2:
                            fine = True
                        if isinstance(x.value, ast.Call) and (dotted(x.value.func) or "").split(".")[-1] \
                                in NOT_SWALLOW_CALLS:
                            fine = True
                if fine:
                    continue
                key = (f, owner.get(n, "<module>"), "except")
                if key in EXEMPT:
                    used.add(key)
                else:
                    swallows.append("SWALLOW %s:%d %s" % (f, n.lineno, key[1]))
    stale = ["STALE EXEMPT %r" % (k,) for k in EXEMPT if k not in used]
    return preds, swallows, stale, n_pred, n_scope


# ---------------------------------------------------------------- plants (controls C1, C2)

def plant_copy(tmp):
    """A copy of this folder whose rotate.py holds the C1 and C2 plants inside
    before_manifest. Returns (copy dir, planted line, unreached line) or a reason."""
    dst = os.path.join(tmp, "copy")
    shutil.copytree(CODE_DIR, dst, ignore=shutil.ignore_patterns("__pycache__"))
    p = os.path.join(dst, "rotate.py")
    with open(p, encoding="utf-8") as fh:
        src = fh.read()
    tree = ast.parse(src)
    fns = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "before_manifest"]
    if len(fns) != 1:
        return "before_manifest occurs %d times in rotate.py" % len(fns)
    first = fns[0].body[0]
    lines = src.split("\n")
    ind = " " * first.col_offset
    i = first.lineno - 1
    plant = [ind + "try:", ind + "    os.listdir(os.curdir)  # PLANTED", ind + "except OSError:",
             ind + "    return 1", ind + "if False:", ind + "    os.listdir(os.curdir)  # UNREACHED"]
    lines[i:i] = plant
    with open(p, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines))
    return dst, i + 2, i + 6


# ---------------------------------------------------------------- named tests (B.4)

def interpreter_312():
    """The first of python3.14, python3.13, python3.12 that shutil.which finds and that
    reports a version of 3.12 or later. Returns (path, version text) or (None, why)."""
    for name in ("python3.14", "python3.13", "python3.12"):
        p = shutil.which(name)
        if not p:
            continue
        r = subprocess.run([p, "-c", "import sys; print(sys.version_info >= (3, 12)); print(sys.version.split()[0])"],
                           capture_output=True, text=True)
        out = r.stdout.split()
        if r.returncode == 0 and out[:1] == ["True"]:
            return p, out[1]
    return None, "no python3.14, python3.13 or python3.12 on PATH reports 3.12 or later"


def leftovers(line):
    """The entries a pre-manifest CANNOT TELL line lists as left in place."""
    mark = "left in place, nothing deleted: "
    return line.split(mark, 1)[1].split(", ") if mark in line else []


def named_tests(check, tmp):
    U = tru.U_CLAUDE
    real_copy2 = shutil.copy2

    # W-C: a backup copy writes part of the file, then the disk fills
    d, root = mk(tmp), mk(tmp)
    p = write(os.path.join(d, "CLAUDE.md"), U)
    write(os.path.join(d, tru.INDEX), tru.IDX_OLD)
    calls = [0]

    def partial_copy(src, dst, *a, **k):
        calls[0] += 1
        if calls[0] == 2:
            with open(src, "rb") as fi, open(dst, "wb") as fo:
                fo.write(fi.read(5))
            raise OSError(28, "No space left on device", dst)
        return real_copy2(src, dst, *a, **k)
    saved = rotate.shutil.copy2
    rotate.shutil.copy2 = partial_copy
    try:
        rc, out = call_rotate([p] + tru.U_ARGS + ["--root", root, "--apply"])
    finally:
        rotate.shutil.copy2 = saved
    line = next((l for l in out.splitlines() if l.startswith("CANNOT TELL: ")), "")
    bk2 = os.path.join(d, tru.INDEX + ".backup-before-split-2026-02-15")
    check("W-C a backup copy that writes part of the file and then fails (ENOSPC) exits 2; the CANNOT "
          "TELL line names the run folder and that backup with (not complete)",
          rc == 2 and os.path.join(d, tru.U_RUN) in leftovers(line) and (bk2 + " (not complete)") in leftovers(line)
          and os.path.exists(bk2), "rc=%r %r" % (rc, line or out[-300:]))

    # W-D: the pending manifest write fails
    d, root = mk(tmp), mk(tmp)
    p = write(os.path.join(d, "CLAUDE.md"), U)
    write(os.path.join(d, tru.INDEX), tru.IDX_OLD)

    def bad_manifest(run_dir, man):
        raise PermissionError(13, "Permission denied", os.path.join(run_dir, "manifest.json.tmp"))
    saved = rotate.write_manifest
    rotate.write_manifest = bad_manifest
    try:
        rc, out = call_rotate([p] + tru.U_ARGS + ["--root", root, "--apply"])
    finally:
        rotate.write_manifest = saved
    line = next((l for l in out.splitlines() if l.startswith("CANNOT TELL: ")), "")
    bks = [os.path.join(d, n + ".backup-before-split-2026-02-15") for n in ("CLAUDE.md", tru.INDEX)]
    check("W-D a pending manifest write that fails exits 2; the CANNOT TELL line names the run folder "
          "and each backup",
          rc == 2 and os.path.join(d, tru.U_RUN) in leftovers(line) and all(b in leftovers(line) for b in bks)
          and all(os.path.isfile(b) for b in bks) and tru.read(p) == U, "rc=%r %r" % (rc, line or out[-300:]))

    # a run folder whose manifest.json cannot be stat'ed
    for label, value in (("--undo <date> --apply", "2026-02-15"), ("--undo <dir> --apply", tru.U_RUN)):
        d, root, p, rc0 = applied(tmp, U)
        run_dir = os.path.join(d, tru.U_RUN)
        os.chmod(run_dir, 0o600)            # listable names, but no stat of what is inside
        try:
            probe = None
            try:
                os.stat(os.path.join(run_dir, "manifest.json"))
            except PermissionError:
                probe = "denied"
            except OSError:
                probe = "other"
            rc, out = call_rotate([p, "--undo", value, "--apply"])
        finally:
            os.chmod(run_dir, 0o755)
        if probe != "denied":
            print("  SKIPPED %s: chmod did not deny a stat (running as root?)" % label)
            continue
        check("%s with a run folder whose manifest.json cannot be stat'ed (PermissionError) "
              "exits 2, never 3, with a CANNOT TELL line" % label,
              rc0 == 0 and rc == 2 and any(l.startswith("CANNOT TELL: ") for l in out.splitlines())
              and os.path.isdir(run_dir), "rc0=%r rc=%r %r" % (rc0, rc, out[-300:]))

    # --accept-file is read once; the waivers used are the bytes validated
    d = mk(tmp)
    b = write(os.path.join(d, "CLAUDE.md.backup-before-split-2026-02-01"), tlc.BEFORE)
    a = write(os.path.join(d, "CLAUDE.md"), tlc.AFTER_MOVED)
    write(os.path.join(d, "CLAUDE_DECISIONS_2026-01.md"), tlc.ARCHIVE)
    acc = write(os.path.join(d, "accept.txt"), "nightly widget export straight\n")
    opened = []
    real_open = builtins.open

    def counting_open(f, *a, **k):
        if os.path.realpath(str(f)) == os.path.realpath(acc):
            opened.append(f)
            if len(opened) > 1:
                raise PermissionError(13, "second open of the accept file", f)
        return real_open(f, *a, **k)
    loss_check.open = counting_open
    splitlib.open = counting_open
    try:
        rc, out = call_loss(["--before", b, "--after", a, "--accept-file", acc])
    finally:
        del loss_check.open
        del splitlib.open
    check("--accept-file is opened once and its waiver lets the moved rule through: exit 0, "
          "one open, the waiver line from the validated bytes",
          rc == 0 and len(opened) == 1
          and 'WAIVER: --accept-file "nightly widget export straight" let through 1 item(s)' in out.splitlines(),
          "rc=%r opened=%d %r" % (rc, len(opened), out[-300:]))

    # J: one read per realpath per run, over input shapes
    # this test generates; a same-heading pointer makes body_of reach each target
    j_rule = "Never push the nightly build without a dry run first."
    real_open = builtins.open

    def counted(run, setup):
        """Run with open counted per realpath in loss_check, rotate and splitlib (read modes only)."""
        opens = {}

        def counting_open(f, mode="r", *a, **k):
            if isinstance(f, (str, bytes, os.PathLike)) and not any(c in mode for c in "wax+"):
                rp = os.path.realpath(f)
                opens[rp] = opens.get(rp, 0) + 1
            return real_open(f, mode, *a, **k)
        for m in (loss_check, rotate, splitlib):
            m.open = counting_open
        try:
            rc, out = run()
        finally:
            for m in (loss_check, rotate, splitlib):
                if "open" in m.__dict__:
                    del m.open
        subjects = dict((os.path.realpath(p), opens.get(os.path.realpath(p), 0)) for p in setup)
        return rc, out, subjects
    old_home = os.environ.get("HOME")
    for shape in ("in the folder", "a ../ sibling", "an absolute path", "a ~ path", "a symlink inside pointing out"):
        top = mk(tmp)
        p = os.path.join(top, "p")
        out_file = os.path.join(top, "sib", "OUT.md")
        if shape == "in the folder":
            target, token = os.path.join(p, "NOTES.md"), "NOTES.md"
        elif shape == "a ../ sibling":
            target, token = out_file, "../sib/OUT.md"
        elif shape == "an absolute path":
            target, token = out_file, out_file
        elif shape == "a ~ path":
            target, token = os.path.join(top, "home", "notes", "OUT.md"), "~/notes/OUT.md"
        else:
            target, token = out_file, "link.md"
        write(target, "# Notes\n\n## Notes\n\n" + j_rule + "\n")
        lazy_arg = target
        if shape == "a symlink inside pointing out":
            os.makedirs(p, exist_ok=True)
            os.symlink(out_file, os.path.join(p, "link.md"))
            lazy_arg = os.path.join(p, "link.md")
        b = write(os.path.join(p, "CLAUDE.md.backup-before-split-2026-02-01"), "# P\n\n## Notes\n\n" + j_rule + "\n")
        a = write(os.path.join(p, "CLAUDE.md"), "# P\n\n## Notes\n\nSee `%s`, same heading.\n" % token)
        if shape == "a ~ path":
            os.environ["HOME"] = os.path.join(top, "home")
        try:
            rc, out, subj = counted(lambda: call_loss(["--before", b, "--after", a, "--lazy", lazy_arg]),
                                    [b, a, target])
        finally:
            if shape == "a ~ path":
                if old_home is None:
                    os.environ.pop("HOME", None)
                else:
                    os.environ["HOME"] = old_home
        check("J1 loss_check.py, the lazy target as %s: exit 0 with 'POINTED 1' (the same-heading pointer "
              "resolved), and at most one open per realpath for every input (opens %s)"
              % (shape, sorted(subj.values())),
              rc == 0 and "POINTED 1" in out and subj and max(subj.values()) <= 1,
              "rc=%r opens=%r %r" % (rc, dict((os.path.basename(k), v) for k, v in subj.items()), out[-300:]))
    # rotate.py: a notes file in the folder, and a --hoisted ancestor reached by a ../CLAUDE.md pointer
    for shape in ("a notes file in the folder", "the --hoisted ancestor by ../CLAUDE.md"):
        top = mk(tmp)
        p = os.path.join(top, "proj")
        kept = ("See `NOTES.md`, same heading." if shape == "a notes file in the folder"
                else "See `../CLAUDE.md`, same heading.")
        c = write(os.path.join(p, "CLAUDE.md"), "# P\n\n## Notes\n\n" + kept + "\n\n" + tru.U_CLAUDE.split("\n", 1)[1])
        n = write(os.path.join(p, "NOTES.md"), "# Notes\n\n## Notes\n\nNotes body.\n")
        h = write(os.path.join(top, "CLAUDE.md"), "# Global\n\n## Notes\n\nNever force the paper tray.\n")
        argv = [c] + tru.U_ARGS + ["--root", mk(tmp)]
        setup = [c, n]
        if shape != "a notes file in the folder":
            argv += ["--hoisted", h]
            setup = [c, h]
        rc, out, subj = counted(lambda: call_rotate(argv), setup)
        unres = [l for l in out.splitlines() if l.startswith("POINTERS: ")]
        check("J1 rotate.py dry run, %s: exit 0, the pointer resolved (POINTERS line with 0 unresolved), and at "
              "most one open per realpath for every input (opens %s)" % (shape, sorted(subj.values())),
              rc == 0 and unres and " 0 unresolved " in unres[0] and max(subj.values()) <= 1,
              "rc=%r opens=%r %r %r" % (rc, dict((os.path.basename(k), v) for k, v in subj.items()), unres, out[-300:]))
    # J2: the changing-read case (reads 1 and 2 give the wrong heading, read 3 the right one, no rule)
    d = mk(tmp)
    b = write(os.path.join(d, "before.md"), "## Notes\n\n" + j_rule + "\n")
    a = write(os.path.join(d, "CLAUDE.md"), "## Notes\n\nSee `NOTES.md`, same heading.\n")
    nf = write(os.path.join(d, "NOTES.md"), "# Notes\n")
    reads = [0]

    def changing_open(f, mode="r", *aa, **k):
        if isinstance(f, (str, bytes, os.PathLike)) and os.path.realpath(f) == os.path.realpath(nf):
            reads[0] += 1
            return io.StringIO(("# Wrong heading\n\n" + j_rule + "\n") if reads[0] <= 2 else "# Notes\n")
        return real_open(f, mode, *aa, **k)
    for m in (loss_check, splitlib):
        m.open = changing_open
    cwd = os.getcwd()
    try:
        os.chdir(d)         # the brief's driver: relative argv, so the --lazy key is "NOTES.md"
        rc, out = call_loss(["--before", "before.md", "--after", "CLAUDE.md", "--lazy", "NOTES.md"])
    finally:
        os.chdir(cwd)
        for m in (loss_check, splitlib):
            if "open" in m.__dict__:
                del m.open
    check("J2 the changing-read case: NOTES.md is read once, so the rule and the heading come "
          "from one snapshot: exit 3 with 'FINDING: 1 item(s) lost'",
          rc == 3 and any(l.startswith("FINDING: 1 item(s) lost") for l in out.splitlines()),
          "rc=%r reads=%d %r" % (rc, reads[0], out[-400:]))
    # J3 (a name whose text the cache holds is answered from that text and never statted
    # again; a mutation survivor of lookup's cache test): token_stat_of never sees a cached
    # input, and does see a pointer target that is no input (the control)
    d = mk(tmp)
    b = write(os.path.join(d, "CLAUDE.md.backup-before-split-2026-02-01"), "# P\n\n## Notes\n\n" + j_rule + "\n")
    a = write(os.path.join(d, "CLAUDE.md"), "# P\n\n## Notes\n\nSee `NOTES.md`, same heading.\n"
                                            "Detail: see `OTHER.md`.\n")
    nf = write(os.path.join(d, "NOTES.md"), "# Notes\n\n## Notes\n\n" + j_rule + "\n")
    statted = []
    real_tso = splitlib.token_stat_of

    def recording_tso(path):
        statted.append(os.path.realpath(path))
        return real_tso(path)
    splitlib.token_stat_of = recording_tso
    try:
        rc, out = call_loss(["--before", b, "--after", a, "--lazy", nf])
    finally:
        splitlib.token_stat_of = real_tso
    check("J3 a pointer target already read in the run is answered from that text and never statted again: "
          "exit 0 with 'POINTED 1', token_stat_of never called for NOTES.md, and called for OTHER.md (no input; "
          "the control)",
          rc == 0 and "POINTED 1" in out and os.path.realpath(nf) not in statted
          and os.path.realpath(os.path.join(d, "OTHER.md")) in statted,
          "rc=%r statted=%r %r" % (rc, [os.path.basename(x) for x in statted], out[-300:]))

    # a manifest path holding NUL exits 2, files unchanged, under 3.9 and under 3.12+
    def nul_manifest():
        d, root, p, rc0 = applied(tmp, U, {tru.INDEX: tru.IDX_OLD})
        mp = os.path.join(d, tru.U_RUN, "manifest.json")
        import json
        with open(mp, encoding="utf-8") as fh:
            man = json.load(fh)
        man["files"][0]["path"] = "CLAUDE\u0000.md"
        with open(mp, "w", encoding="utf-8") as fh:
            json.dump(man, fh)
        return d, p, snapshot([d])
    d, p, snap = nul_manifest()
    rc, out = call_rotate([p, "--undo", tru.U_RUN, "--apply"])
    check("(%s) a manifest path holding NUL: --undo <dir> --apply exits 2, files unchanged"
          % sys.version.split()[0], rc == 2 and snapshot([d]) == snap, "rc=%r %r" % (rc, out[-300:]))
    py, ver = interpreter_312()
    if py is None:
        check("3.12+: no interpreter found", False, ver)
    else:
        print("  3.12+ interpreter: %s (%s)" % (py, ver))
        d, p, snap = nul_manifest()
        r = subprocess.run([py, "-I", os.path.join(CODE_DIR, "rotate.py"), p, "--undo", tru.U_RUN, "--apply"],
                           capture_output=True, text=True)
        check("3.12+ (%s %s) a manifest path holding NUL: --undo <dir> --apply exits 2, no "
              "Traceback, files unchanged" % (os.path.basename(py), ver),
              r.returncode == 2 and "Traceback" not in r.stderr and snapshot([d]) == snap,
              "rc=%d %r %r" % (r.returncode, r.stdout[-300:], r.stderr[-300:]))

    # Real EACCES at the archive: the existing month archive is a symlink into a mode-000 folder
    for mode in ([], ["--apply"]):
        d, root = mk(tmp), mk(tmp)
        p = write(os.path.join(d, "CLAUDE.md"), U)
        locked = os.path.join(mk(tmp), "locked")
        write(os.path.join(locked, tru.ARCH), tru.ARCH_OLD)
        os.symlink(os.path.join(locked, tru.ARCH), os.path.join(d, tru.ARCH))
        os.chmod(locked, 0)
        try:
            denied = not os.access(os.path.join(locked, tru.ARCH), os.R_OK)
            rc, out = call_rotate([p] + tru.U_ARGS + ["--root", root] + mode)
        finally:
            os.chmod(locked, 0o755)
        if not denied:
            print("  SKIPPED real-EACCES twin: chmod 000 did not take (running as root?)")
            continue
        line = next((l for l in out.splitlines() if l.startswith("CANNOT TELL: ")), "")
        check("real-EACCES twin %s: the month archive is a symlink into a mode-000 folder: exit 2 with "
              "the CANNOT TELL line naming the archive, no run folder, no manifest.json"
              % (mode[0] if mode else "dry run"),
              rc == 2 and tru.ARCH in line and not os.path.exists(os.path.join(d, tru.U_RUN)),
              "rc=%r %r" % (rc, line or out[-300:]))

    # an unreadable pointer target is cannot tell, not a pointer result
    rule = "Never push to main without a review."
    pb = "# P\n\n## Deploy\n\n" + rule + "\n"
    pa = "# P\n\n## Deploy\n\nFiles in `archive/`.\nDetail: see `CLAUDE_DECISIONS_INDEX.md`.\n"
    for locked_idx in (False, True):
        d = mk(tmp)
        b = write(os.path.join(d, "CLAUDE.md.backup-before-split-2026-02-01"), pb)
        a = write(os.path.join(d, "CLAUDE.md"), pa)
        idx = write(os.path.join(d, "archive", "CLAUDE_DECISIONS_INDEX.md"),
                    "# Index\n\n- `CLAUDE_DECISIONS_2026-08.md`\n")
        lz = write(os.path.join(d, "archive", "CLAUDE_DECISIONS_2026-08.md"), "# Aug\n\n" + rule + "\n")
        if locked_idx:
            os.chmod(idx, 0)
        try:
            denied = locked_idx and not os.access(idx, os.R_OK)
            r = subprocess.run([sys.executable, os.path.join(CODE_DIR, "loss_check.py"), "--before", b,
                                "--after", a, "--lazy", lz], capture_output=True, text=True)
            rp = subprocess.run([sys.executable, os.path.join(CODE_DIR, "pointers.py"), a, "--root", mk(tmp)],
                                capture_output=True, text=True)
        finally:
            os.chmod(idx, 0o644)
        if not locked_idx:
            check("control, index readable: loss_check.py exit 0 with POINTED 1",
                  r.returncode == 0 and "POINTED 1" in r.stdout, "rc=%d %r" % (r.returncode, r.stdout[-300:]))
            continue
        if not denied:
            print("  SKIPPED: chmod 000 did not take (running as root?)")
            continue
        line = next((l for l in r.stdout.splitlines() if l.startswith("CANNOT TELL: ")), "")
        check("index at mode 000: loss_check.py exits 2 with a CANNOT TELL line naming the index and "
              "no LAZY-ONLY line",
              r.returncode == 2 and "CLAUDE_DECISIONS_INDEX.md" in line and "LAZY-ONLY: " not in r.stdout
              and "Traceback" not in r.stderr, "rc=%d %r %r" % (r.returncode, r.stdout[-300:], r.stderr[-200:]))
        check("index at mode 000: pointers.py exits 2 with a CANNOT TELL line naming the index",
              rp.returncode == 2 and any(l.startswith("CANNOT TELL: ") and "CLAUDE_DECISIONS_INDEX.md" in l
                                         for l in rp.stdout.splitlines()) and "Traceback" not in rp.stderr,
              "rc=%d %r %r" % (rp.returncode, rp.stdout[-300:], rp.stderr[-200:]))
    # the same unreadable index through rotate.py's in-memory pointer report
    d, root = mk(tmp), mk(tmp)
    p = write(os.path.join(d, "CLAUDE.md"), U.replace(
        "Preamble text for the undo tests.\n",
        "Preamble text for the undo tests.\n\nFiles in `archive/`.\nDetail: see `archive/CLAUDE_DECISIONS_INDEX.md`.\n"))
    idx = write(os.path.join(d, "archive", "CLAUDE_DECISIONS_INDEX.md"), "# Index\n\n- `CLAUDE_DECISIONS_2025-12.md`\n")
    os.chmod(idx, 0)
    try:
        denied = not os.access(idx, os.R_OK)
        rc, out = call_rotate([p] + tru.U_ARGS + ["--root", root])
    finally:
        os.chmod(idx, 0o644)
    if denied:
        line = next((l for l in out.splitlines() if l.startswith("CANNOT TELL: ")), "")
        check("rotate.py's in-memory pointer report on a pointer to an index at mode 000: exit 2 with "
              "a CANNOT TELL line naming the index, no run folder",
              rc == 2 and "CLAUDE_DECISIONS_INDEX.md" in line and not os.path.exists(os.path.join(d, tru.U_RUN)),
              "rc=%r %r" % (rc, line or out[-300:]))
    else:
        print("  SKIPPED rotate.py: chmod 000 did not take (running as root?)")

    # K.4: undo from a deleted working folder, through the real CLI, with -I
    for label, args in (("K2 --undo 2026-02-15", ["--undo", "2026-02-15"]),
                        ("K3 control, the non-undo path", ["--convention", "section", "--cut-date", "2026-02-01"])):
        gone = mk(tmp)
        r = subprocess.run(["sh", "-c", 'cd "$1" && rmdir "$1" && shift && exec "$@"', "sh", gone,
                            sys.executable, "-I", os.path.join(CODE_DIR, "rotate.py"), "CLAUDE.md"] + args,
                           capture_output=True, text=True)
        tells = [l for l in r.stdout.splitlines() if l.startswith("CANNOT TELL: ")]
        if label.startswith("K2"):
            check("K2 rotate.py CLAUDE.md --undo 2026-02-15 from a deleted working folder: exit 2, a 'CANNOT TELL: ' "
                  "line on stdout, no Traceback on stdout or stderr",
                  r.returncode == 2 and len(tells) == 1 and "Traceback" not in r.stdout + r.stderr,
                  "rc=%d %r %r" % (r.returncode, r.stdout[-300:], r.stderr[-300:]))
        else:
            check("K3 control: the same deleted folder on the non-undo path gives 'CANNOT TELL: FileNotFoundError; "
                  "...' and exit 2",
                  r.returncode == 2 and len(tells) == 1 and tells[0].startswith("CANNOT TELL: FileNotFoundError; ")
                  and "Traceback" not in r.stdout + r.stderr,
                  "rc=%d %r %r" % (r.returncode, r.stdout[-300:], r.stderr[-300:]))


def refusal_controls(check, tmp):
    """The boundary catches three exception types only: a returned refusal keeps 3, and
    the no-dated-records exit keeps 1 (no injection)."""
    d = mk(tmp)
    b = write(os.path.join(d, "CLAUDE.md.backup-before-split-2026-02-01"), tlc.BEFORE)
    a = write(os.path.join(d, "CLAUDE.md"), tlc.AFTER_MOVED)
    rc, out = call_loss(["--before", b, "--after", a])
    check("refusal control, loss check: loss_check.py on a rule left nowhere exits 3", rc == 3, "rc=%r" % rc)
    d, root = mk(tmp), mk(tmp)
    p = write(os.path.join(d, "CLAUDE.md"), tru.U_CLAUDE)
    write(os.path.join(d, "TODO.md"), "# Todo\n\n- [ ] Check the record about the paper tray again\n")
    rc, out = call_rotate([p] + tru.U_ARGS + ["--root", root, "--apply"])
    check("refusal control, open work: open work names the moving record, --apply exits 3", rc == 3,
          "rc=%r %r" % (rc, out[-200:]))
    d, root = mk(tmp), mk(tmp)
    p = write(os.path.join(d, "CLAUDE.md"), tru.H_CLAUDE_RULE)
    rc, out = call_rotate([p] + tru.U_ARGS + ["--root", root, "--apply"])
    check("refusal control, rules draft: a moving rule sentence, --apply exits 3", rc == 3, "rc=%r" % rc)
    d, root, p, rc0 = applied(tmp, tru.U_CLAUDE)
    with open(p, "a", encoding="utf-8") as fh:
        fh.write("An edit made after the run.\n")
    rc, out = call_rotate([p, "--undo", "2026-02-15", "--apply"])
    check("refusal control, undo: an undo after CLAUDE.md changed exits 3", rc0 == 0 and rc == 3,
          "rc0=%r rc=%r" % (rc0, rc))
    d, root = mk(tmp), mk(tmp)
    p = write(os.path.join(d, "CLAUDE.md"), "# Project\n\nNo dated record here.\n")
    rc, out = call_rotate([p] + tru.U_ARGS + ["--root", root])
    check("refusal control: no dated records still exits 1", rc == 1, "rc=%r" % rc)


# ---------------------------------------------------------------- main

CHECKS = []


def resolve_segments():
    out, missing = [], []
    for mod, name in ((rotate, "before_manifest"), (rotate, "undo_checks"), (loss_check, "main")):
        fn = getattr(mod, name, None)
        if fn is None:
            missing.append("%s.%s" % (mod.__name__, name))
        else:
            out.append(fn)
    return out, missing


def target_main():
    """The child of controls C1 and C2: the copy's own modules, one site injected."""
    for m in (rotate, loss_check, splitlib):
        if not os.path.realpath(m.__file__).startswith(os.path.realpath(TARGET) + os.sep):
            print("TARGET NOT LOADED %s" % m.__name__)
            return 1
    segs, missing = resolve_segments()
    if missing:
        print("SEGMENTS MISSING %s" % ", ".join(missing))
        return 1
    tmp = os.path.realpath(tempfile.mkdtemp(prefix="disk-target-"))
    try:
        res = injection(parse_files(), segs, tmp, print, only=ONLY_SITE)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return 0 if not res["red"] else 1


def main():
    checks = CHECKS

    def check(name, ok, detail=""):
        if not isinstance(detail, str):
            detail = repr(detail)
        checks.append((name, bool(ok), detail))

    tmp = os.path.realpath(tempfile.mkdtemp(prefix="disk-failures-"))
    try:
        # ---------------------------------------------------------------- CONTROL
        trees = parse_files()
        en0 = enumerate_sites(trees, [("splitlib.py", "sha256")])
        check("CONTROL splitlib.sha256 reaches exactly one disk site, its open",
              [k[1] for k in en0["sites"]] == ["open"], en0["sites"])

        segs, missing = resolve_segments()
        check("SEGMENTS resolve: rotate.before_manifest, rotate.undo_checks and loss_check.main exist",
              not missing, "missing: %s" % ", ".join(missing))
        if missing:
            return report(checks)

        lines = []

        def emit(ln):
            lines.append(ln)
            print(ln)
        res = injection(trees, segs, tmp, emit)
        en = res["en"]
        check("the enumeration has no UNCLASSIFIED call", not en["unclassified"], en["unclassified"])
        check("no two sites of one callee overlap (AMBIGUOUS)", not en["ambiguous"], en["ambiguous"])
        check("no SEGMENT LEAK: rotate.undo and rotate.main are outside the reachable set",
              not res["leak"], res["leak"])
        check("every scenario's uninjected run exits as its row says (no BASELINE line)",
              not res["baseline"], res["baseline"])
        check("hits were recorded for every segment (no NO HITS line)", not res["nohits"], res["nohits"])
        check("every wrapped name is its original again after every run", not res["restored"],
              res["restored"])
        check("RED SITES 0: every reached site, injected, exits 2 with no escape, nothing changed, "
              "one CANNOT TELL line naming the path and every new path",
              not res["red"] and res["runs"] > 0, [site_name(k) for k in res["red"]][:12])
        check("UNREACHED 0: every enumerated site is reached by a scenario or is an UNREACHED_OK row",
              not res["unreached"], res["unreached"][:12])
        nih = [x for x in res["ok_bad"] if x.startswith("UNREACHED_OK NOT IN HANDLER ")]
        check("no UNREACHED_OK NOT IN HANDLER line: every handler row sits in an except or finally body",
              not nih, nih)
        badr = [x for x in res["ok_bad"] if x.startswith("UNREACHED_OK BAD REASON ")]
        check("no UNREACHED_OK BAD REASON line: every row's reason is handler or fixture: <what>",
              not badr, badr)
        check("no STALE UNREACHED_OK row", not res["stale_ok"], res["stale_ok"])
        # H5: the PermissionError control at token_stat_of's os.stat stays cannot tell
        tsk = [k for k, (qual, _n) in en["sites"].items()
               if k[0] == "splitlib.py" and k[1] == "os.stat" and qual == "token_stat_of"]
        h5 = ["H5 site %s [%s]" % (site_name(k), res["first"].get(k, "never reached")) for k in tsk]
        for ln in h5:
            print(ln)
        check("H5 the injected PermissionError at splitlib.token_stat_of's os.stat, in the scenario that first "
              "reaches it, exits 2 with its CANNOT TELL line (the site is reached and is no RED SITE): %s"
              % ", ".join(h5), len(tsk) == 1 and tsk[0] in res["first"] and tsk[0] not in res["red"], h5)

        # ---------------------------------------------------------------- predicate and handler audit
        preds, swallows, stale, n_pred, n_scope = audit(trees)
        print("AUDIT PREDICATES %d (%d not exempt) HANDLERS IN SCOPE %d (%d swallow)"
              % (n_pred, len(preds), n_scope, len(swallows)))
        check("every existence predicate is replaced by splitlib.stat_of or EXEMPT with its reason",
              not preds, preds)
        check("no handler in the three files swallows a disk error into a value (SWALLOW)",
              not swallows, swallows)
        check("no STALE EXEMPT row", not stale, stale)
        planted = dict((f, ast.unparse(t)) for f, t in trees.items())
        planted["rotate.py"] = planted["rotate.py"].replace(
            "def build_final(lines, d, to_move, convention, today, before_chars, run_name):\n",
            "def build_final(lines, d, to_move, convention, today, before_chars, run_name):\n"
            "    os.path.exists(d)\n", 1)
        planted["rotate.py"] += ("\n\ndef planted_reader(p):\n    try:\n        return open(p).read()\n"
                                 "    except OSError:\n        return ''\n")
        p2, s2, _st, _n, _h = audit(dict((f, ast.parse(s)) for f, s in planted.items()))
        p2 = [x for x in p2 if x not in preds]
        s2 = [x for x in s2 if x not in swallows]
        check("planted-predicate control: one os.path.exists added in build_final prints one PREDICATE "
              "line naming build_final", len(p2) == 1 and " build_final os.path.exists" in p2[0], p2)
        check("planted-handler control: an except OSError returning '' prints one SWALLOW line naming "
              "the new function", len(s2) == 1 and s2[0].endswith(" planted_reader"), s2)

        # ---------------------------------------------------------------- K.3 MAIN OUTSIDE BOUNDARY
        mob = main_outside_boundary(trees["rotate.py"])
        for ln in mob:
            print(ln)
        src = ast.unparse(trees["rotate.py"])
        anchor = "    args = ap.parse_args()\n"
        if src.count(anchor) == 1:
            mob2 = main_outside_boundary(ast.parse(src.replace(
                anchor, anchor + "    splitlib.is_file(args.file)\n", 1)))
        else:
            mob2 = ["no single parse_args line in rotate.main"]
        check("K1 MAIN OUTSIDE BOUNDARY: every call in rotate.main's own body is in the allow-list (no line), "
              "and a planted splitlib.is_file(args.file) before the dispatch prints exactly one line naming it",
              mob == [] and len(mob2) == 1 and mob2[0].endswith(" splitlib.is_file"), (mob, mob2))

        # ---------------------------------------------------------------- controls C1 and C2
        got = plant_copy(tmp)
        if isinstance(got, str):
            check("C1/C2 the planted copy could be made", False, got)
        else:
            dst, planted_line, unreached_line = got
            base_n = len(en["sites"])
            r = subprocess.run([sys.executable, "-I", os.path.abspath(__file__), "--target", dst,
                                "--site", "rotate.py:%d" % planted_line], capture_output=True, text=True,
                               cwd=dst)
            out = "\n".join(l for l in r.stdout.splitlines() if not TALLY.search(l))
            ds = re.search(r"^DISK SITES (\d+) ", out, re.M)
            check("C1 the planted call inside before_manifest is enumerated (the count rises by 2 with C2's "
                  "plant) and, injected, prints FAIL site rotate.py:%d os.listdir [...]: exit 1" % planted_line,
                  "TARGET NOT LOADED" not in out and ds is not None and int(ds.group(1)) == base_n + 2
                  and re.search(r"^FAIL site rotate\.py:%d os\.listdir \[[A-Z-]+\]: exit 1$" % planted_line,
                                out, re.M) is not None, out[-600:] + r.stderr[-300:])
            check("C2 the unreached plant prints UNREACHED rotate.py:%d os.listdir" % unreached_line,
                  ("UNREACHED rotate.py:%d os.listdir" % unreached_line) in out.splitlines(), out[-600:])

        # ---------------------------------------------------------------- refusals and named tests
        refusal_controls(check, tmp)
        named_tests(check, tmp)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return report(checks)


def report(checks):
    if not checks:
        print("0/0 passed -- the harness ran NO checks, which is a harness bug")
        return 1
    failed = [c for c in checks if not c[1]]
    for name, ok, detail in checks:
        if not ok:
            print("  FAILED " + name)
            print("         " + TALLY.sub("<tally>", detail.replace("\n", "\n         "))[:600])
    print("%d/%d passed" % (len(checks) - len(failed), len(checks)))
    return 1 if failed else 0


if __name__ == "__main__":
    if TARGET:
        sys.exit(target_main())
    try:
        RC = main()
    except Exception as e:                                      # noqa: BLE001
        CHECKS.append(("the file ran to its end without an exception", False,
                       "stopped at %s: %s" % (type(e).__name__, e)))
        RC = report(CHECKS)
    sys.exit(RC)
