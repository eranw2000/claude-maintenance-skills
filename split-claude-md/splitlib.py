#!/usr/bin/env python3
"""Text rules shared by every /split-claude-md check.

One place decides what a rule-shaped sentence is, what an identifier, path,
command and heading are, when an item still counts as kept, how a file splits
into sections, and how a loss is classified. loss_check.py is a thin command
over these functions; rotate.py and the later checks call the same ones, so the
text rules exist once.

Lengths are Python str lengths (characters), never byte counts.
Standard library only.
"""
import errno
import hashlib
import os
import re
import stat
from collections import OrderedDict

# The glossary list of rule words plus "don't" as the contraction of "do not";
# `only` is included too.
RULE_RE = re.compile(r"\b(?:never|always|must|do not|don't|refuse|forbid|only)\b",
                     re.IGNORECASE)
# The one exception, used for kept units: the seven base words,
# without `only`. It builds Text.rule_lines (kept clause (a)) and nothing else.
RULE_BASE_RE = re.compile(r"\b(?:never|always|must|do not|don't|refuse|forbid)\b",
                          re.IGNORECASE)
HEADING_MARK_RE = re.compile(r"^#+\s*")

# Open-work stoplist, also skipped by kept clause (a).
STOPLIST = {"CLAUDE.md", "TODO.md", "MEMORY.md", "README.md", "main", "origin",
            "~/.claude"}

COMMAND_WORDS = {"python3", "git", "gh", "curl", "bash", "npm", "docker",
                 "render", "az", "grep", "rg", "sed", "claude"}

TOKEN_RE = re.compile(r"`([^`\n]+)`")
URL_RE = re.compile(r"^https?://\S+$")
UUID_RE = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
                     r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")
HASH_RE = re.compile(r"^[0-9a-f]{7,40}$")
SERVICE_RE = re.compile(r"^(?:srv-[A-Za-z0-9]+|ta\d+|[A-Za-z]+-\d+)$")
UPPER_SNAKE_RE = re.compile(r"^[A-Z][A-Z0-9_]{3,}$")
LIST_MARKER_RE = re.compile(r"^(?:[-*+]|\d+\.)\s+")
SENTENCE_SPLIT_RE = re.compile(r"(?<=\.) |; ")
INSTANCES_RE = re.compile(r"\s*\(\d+ instances?\)\s*$")
PUNCT_RE = re.compile(r"[^\w\s]")
LAST_RUN_PREFIX = "Last split run:"
ARCHIVE_NAME_RE = re.compile(r"^CLAUDE_DECISIONS_\d{4}-\d{2}\.md$")
POINTER_WORD_RE = re.compile(r"\b(?:see|evidence|detail|same heading|pointer|"
                             r"lives in|moved to)\b", re.IGNORECASE)
WINDOW = 5
BROAD_LIMIT = 5   # a single --accept letting through MORE than this is broad

KINDS = ("rule", "heading", "path", "identifier", "command")


class Item(object):
    """One atom of the BEFORE text: its kind, its text and its owning section."""
    __slots__ = ("kind", "text", "section")

    def __init__(self, kind, text, section):
        self.kind, self.text, self.section = kind, text, section

    def key(self):
        return (self.kind, self.text, self.section)

    def __repr__(self):
        return "Item(%r, %r, %r)" % (self.kind, self.text, self.section)


class Result(object):
    """The classifier record for one item: kind, class, holding files."""
    __slots__ = ("item", "cls", "holding", "where", "waiver")

    def __init__(self, item, cls, holding, where=None):
        self.item, self.cls, self.holding, self.where = item, cls, holding, where
        self.waiver = None

    @property
    def kind(self):
        return self.item.kind

    def record(self):
        return (self.item.kind, self.cls, list(self.holding))

    def label(self):
        """The class as printed: KEPT (hoisted: f), POINTED (archive: f), ..."""
        if self.cls == "KEPT (hoisted)":
            return "KEPT (hoisted: %s)" % self.where
        if self.cls == "POINTED (archive)":
            return "POINTED (archive: %s)" % self.where
        return self.cls

    def blocking(self):
        """A NOWHERE item of any kind, or a LAZY-ONLY rule sentence."""
        return self.cls == "NOWHERE" or (self.cls == "LAZY-ONLY" and self.kind == "rule")


# ---------------------------------------------------------------- basics

def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def stat_of(path, follow=True):
    """os.stat (os.lstat with follow False) of path, or None when it is
    absent. Absent means FileNotFoundError and nothing else: any other OSError
    (a PermissionError above all) rises to the segment's boundary, so a disk
    error is cannot tell (2), never absent (3). The one helper every existence
    decision of rotate.py, loss_check.py and splitlib.py goes through."""
    try:
        if follow:
            return os.stat(path)
        return os.lstat(path)
    except FileNotFoundError:
        return None


def token_stat_of(path):
    """The absence rule widened for pointer candidates: os.stat of a path built
    from a backticked token, or None when it cannot exist: FileNotFoundError,
    NotADirectoryError (a component is a file) or ENAMETOOLONG (a name too long
    for the file system). Every other OSError (a PermissionError above all)
    rises, so a disk error is cannot tell (2), never absent. Only
    pointers()'s lookup (and through it the index hub) calls it; undo and the run
    folder pick stay on stat_of."""
    try:
        return os.stat(path)
    except (FileNotFoundError, NotADirectoryError):
        return None
    except OSError as e:
        if e.errno == errno.ENAMETOOLONG:
            return None
        raise


def read_once(cache, path):
    """An input is read once: the text of `path`, read through one
    dict per run keyed by os.path.realpath, so every later read of the same
    file in the run (the notes set, a pointer target, the same-heading test)
    gets the bytes the first read validated, whatever path names it."""
    rp = os.path.realpath(path)
    if rp not in cache:
        with open(path, encoding="utf-8") as fh:
            cache[rp] = fh.read()
    return cache[rp]


def exists(path):
    """os.path.exists, but a disk error rises."""
    return stat_of(path) is not None


def is_file(path):
    """os.path.isfile, but a disk error rises."""
    st = stat_of(path)
    return st is not None and stat.S_ISREG(st.st_mode)


def is_dir(path):
    """os.path.isdir, but a disk error rises."""
    st = stat_of(path)
    return st is not None and stat.S_ISDIR(st.st_mode)


def is_link(path):
    """os.path.islink, but a disk error rises."""
    st = stat_of(path, follow=False)
    return st is not None and stat.S_ISLNK(st.st_mode)


def lexists(path):
    """os.path.lexists, but a disk error rises."""
    return stat_of(path, follow=False) is not None


def normalize(text):
    """Lowercase, punctuation removed, words joined by one space."""
    return " ".join(PUNCT_RE.sub("", text.lower()).split())


def strip_instances(heading):
    return INSTANCES_RE.sub("", heading.rstrip("\n")).rstrip()


def sections(text):
    """OrderedDict {(heading, n): section text}.

    The text before the first '## ' line is keyed ("", 1). A section runs from
    its '## ' line to the next '## ' line ('### ' does not end it). n counts
    from 1 among equal headings, so two '## Project profile' sections differ.
    Joining the values in order gives back the text byte for byte.
    """
    out = OrderedDict()
    seen = {}
    key = ("", 1)
    buf = []
    for ln in text.splitlines(keepends=True):
        if ln.startswith("## "):
            if buf or key != ("", 1):
                out[key] = "".join(buf)
            head = ln.rstrip("\r\n")
            seen[head] = seen.get(head, 0) + 1
            key = (head, seen[head])
            buf = [ln]
        else:
            buf.append(ln)
    if buf or key != ("", 1):
        out[key] = "".join(buf)
    return out


def section_name(key):
    head, n = key
    name = head if head else "preamble"
    return name if n == 1 else "%s (occurrence %d)" % (name, n)


# ---------------------------------------------------------------- atoms

def token_kind(tok):
    """Kind of one backticked token, or None when it is no atom."""
    t = tok.strip()
    if not t:
        return None
    if t.split()[0] in COMMAND_WORDS:
        return "command"
    if URL_RE.match(t):
        return "identifier"
    if "/" in t or t.startswith("~"):
        return "path"
    if (UUID_RE.match(t) or HASH_RE.match(t) or SERVICE_RE.match(t)
            or UPPER_SNAKE_RE.match(t)):
        return "identifier"
    return None


# ---------------------------------------------------------------- fences

FENCE_OPEN, FENCE_CLOSE = "open", "close"


class UnclosedFence(ValueError):
    """A whole text ends inside a fenced block; `line` is the opener's
    1-based line number. A ValueError, so a path that misses the specific
    message still exits 2 under the disk-failure rule."""

    def __init__(self, line):
        ValueError.__init__(self, "fence opened at line %d never closes" % line)
        self.line = line


def _fence_run(st):
    """(character, count) of the run of backticks or tildes a stripped line
    begins with, or (None, 0). Counted, not matched, so this is no line
    reader of its own (every reader is derived from this one)."""
    ch = st[:1]
    if ch not in ("`", "~"):
        return None, 0
    return ch, len(st) - len(st.lstrip(ch))


def fence_states(lines, start_fenced=False):
    """The one fence reader. Returns (fenced,
    open_at): fenced[i] is False for a line outside every fenced block, True
    for a line inside one, FENCE_OPEN or FENCE_CLOSE for the block's opening
    and closing fence lines (both truthy, so "skip fenced lines" is one test);
    open_at is the 1-based line of a fence still open at the end, or None.

    Grammar (CommonMark 0.31.2 section 4.5, indentation stripped): an opener
    is a line whose stripped text starts with three or more backticks and
    holds no other backtick after them, or starts with three or more tildes;
    the block closes only on a line made of the opener's character alone, at
    least as many. Any other line inside is content. The state runs through
    the whole list and is never reset at a '## ' line.

    start_fenced: the state before the first line, for a slice walk (a record
    or a section): False (outside), or the opening run in force ('```',
    '~~~~'); True means '```'. A slice walk ignores open_at (a slice never
    raises); open_at is then 0 when the fence was already open at the start."""
    if start_fenced is True:
        start_fenced = "```"
    if start_fenced:
        ch, n = _fence_run(start_fenced)
        opener, at = (ch, n), 0
    else:
        opener, at = None, None
    fenced = []
    for i, ln in enumerate(lines):
        st = ln.strip()
        ch, n = _fence_run(st)
        if opener is None:
            if n >= 3 and not (ch == "`" and "`" in st[n:]):
                opener, at = (ch, n), i + 1
                fenced.append(FENCE_OPEN)
            else:
                fenced.append(False)
        elif ch == opener[0] and n >= opener[1] and n == len(st):
            opener, at = None, None
            fenced.append(FENCE_CLOSE)
        else:
            fenced.append(True)
    return fenced, (at if opener is not None else None)


def closed_fence_states(lines):
    """fence_states for a whole text (an entry point): raises
    UnclosedFence when a fence is still open at the end."""
    fenced, open_at = fence_states(lines)
    if open_at is not None:
        raise UnclosedFence(open_at)
    return fenced


def fence_start(lines, fenced, i):
    """The start state of a slice that begins at index i of a whole text whose
    flags are `fenced`: False, or the opening run of the fence in force just
    before line i (a slice never raises)."""
    j = i - 1
    if j < 0 or not fenced[j] or fenced[j] == FENCE_CLOSE:
        return False
    while j >= 0 and fenced[j] != FENCE_OPEN:
        j -= 1
    if j < 0:
        return "```"
    st = lines[j].strip()
    ch, n = _fence_run(st)
    return st[:n]


def _section_flags(text, fenced):
    """Pair each '## ' section body of `text` with its slice of the whole
    text's per-line flags."""
    out, k = [], 0
    for key, body in sections(text).items():
        n = len(body.splitlines())
        out.append((key, body, fenced[k:k + n]))
        k += n
    return out


def _text_flags(text, start_fenced):
    """The per-line flags of a text: a whole text (start_fenced None) raises
    UnclosedFence at an open end; a slice walk with a start state never does."""
    lines = text.splitlines()
    if start_fenced is None:
        return closed_fence_states(lines)
    return fence_states(lines, start_fenced)[0]


def _walk(body, fenced):
    """One walk of a section body, shared by atoms() and rule_units().

    fenced: the body's lines' flags from fence_states() over the whole text
    (or the slice), so a fenced '## ' line, which starts a section, keeps its
    state; the walk keeps no toggle of its own.

    Yields ("command", text) for each non-blank line inside a fence,
    ("heading", stripped line) for each '#' line, ("line", line) for every
    other non-blank line outside a fence, and ("unit", text, is_heading) for
    every unit, rule-shaped or not: a paragraph or list item (its stripped lines
    joined by one space, the first line's list marker removed), a table row
    alone, or a heading alone without its '#'s. A fence line, a blank line, a
    heading, a table row and a list-marker line each end the current unit.

    A fence reading never decides whether a rule blocks: a fenced
    line (content, opening or closing fence) whose stripped text RULE_RE
    matches is also a unit of its own, its first list marker removed (rule
    unit (iv)); it never joins a paragraph. Then, since fence-blind rule units are
    always present and fence state may only add: each unit of _walk_blind(body),
    rule unit (v), whose text this walk has not already yielded for the body.
    """
    evs = []
    cur = []
    for ln, f in zip(body.splitlines(), fenced):
        st = ln.strip()
        if f in (FENCE_OPEN, FENCE_CLOSE):
            if cur:
                evs.append(("unit", " ".join(cur), False))
                cur = []
            if RULE_RE.search(st):              # rule unit (iv): a rule-shaped fence line
                evs.append(("unit", LIST_MARKER_RE.sub("", st).strip(), False))
            continue
        if f:
            if st:
                evs.append(("command", st))
                if RULE_RE.search(st):          # rule unit (iv): a rule-shaped fenced line
                    evs.append(("unit", LIST_MARKER_RE.sub("", st).strip(), False))
            continue
        if not st:
            if cur:
                evs.append(("unit", " ".join(cur), False))
                cur = []
            continue
        if ln.startswith("#"):
            if cur:
                evs.append(("unit", " ".join(cur), False))
                cur = []
            evs.append(("heading", st))
            evs.append(("unit", HEADING_MARK_RE.sub("", st), True))
            continue
        evs.append(("line", ln))
        if st.startswith("|"):
            if cur:
                evs.append(("unit", " ".join(cur), False))
                cur = []
            evs.append(("unit", st, False))
            continue
        if LIST_MARKER_RE.match(st):
            if cur:
                evs.append(("unit", " ".join(cur), False))
            cur = [LIST_MARKER_RE.sub("", st).strip()]
            continue
        cur.append(st)
    if cur:
        evs.append(("unit", " ".join(cur), False))
    seen = set(ev[1] for ev in evs if ev[0] == "unit")
    for ev in _walk_blind(body):                # rule unit (v), not already yielded
        if ev[1] not in seen:
            seen.add(ev[1])
            evs.append(ev)
    for ev in evs:
        yield ev


def _walk_blind(body):
    """Rule unit (v): the units (i) to (iii) built over the whole
    body by a walk that reads no fence flag, so every reading of the fences
    gives the same units. A line the fence reader's opener test accepts,
    tested on that line alone with no pairing (three or more tildes, or three
    or more backticks with no other backtick after them; the run _fence_run
    counts), ends the current unit and is a unit alone, its first list marker
    removed, when RULE_RE matches it. A backtick run with another backtick
    after it (a line starting with an inline code span) is prose, never a
    boundary. Yields ("unit", text, is_heading) events only."""
    cur = []
    for ln in body.splitlines():
        st = ln.strip()
        ch, n = _fence_run(st)
        if n >= 3 and not (ch == "`" and "`" in st[n:]):
            if cur:
                yield ("unit", " ".join(cur), False)
                cur = []
            if RULE_RE.search(st):
                yield ("unit", LIST_MARKER_RE.sub("", st).strip(), False)
            continue
        if not st:
            if cur:
                yield ("unit", " ".join(cur), False)
                cur = []
            continue
        if ln.startswith("#"):
            if cur:
                yield ("unit", " ".join(cur), False)
                cur = []
            yield ("unit", HEADING_MARK_RE.sub("", st), True)
            continue
        if st.startswith("|"):
            if cur:
                yield ("unit", " ".join(cur), False)
                cur = []
            yield ("unit", st, False)
            continue
        if LIST_MARKER_RE.match(st):
            if cur:
                yield ("unit", " ".join(cur), False)
            cur = [LIST_MARKER_RE.sub("", st).strip()]
            continue
        cur.append(st)
    if cur:
        yield ("unit", " ".join(cur), False)


def unit_sentences(unit):
    """The rule sentences of one unit: its pieces split at '. ' and '; ', one
    leading list marker removed, the ones RULE_RE matches, in order."""
    out = []
    for piece in SENTENCE_SPLIT_RE.split(unit):
        s = LIST_MARKER_RE.sub("", piece.strip(), count=1).strip()
        if s and RULE_RE.search(s):
            out.append(s)
    return out


def rule_units(text, start_fenced=None):
    """The rule units (the rules draft lines): every unit of the text, in text
    order, that RULE_RE matches, headings included. A whole text (start_fenced
    None) raises UnclosedFence at an open end; a slice with a start state
    never raises."""
    out = []
    for _key, body, flags in _section_flags(text, _text_flags(text, start_fenced)):
        for ev in _walk(body, flags):
            if ev[0] == "unit" and RULE_RE.search(ev[1]):
                out.append(ev[1])
    return out


def atoms(text, start_fenced=None):
    """Every item of a BEFORE text, each with its owning '## ' section key.

    Rule items are the rule sentences of every rule-shaped unit,
    headings included: a rule-shaped heading is a heading item (with its '#'s)
    AND yields rule sentences (its text without them). Token items are read
    per line; each non-blank line of a fenced block is a command item, and a
    rule-shaped one also yields rule sentences, as do the fence-blind units
    (a fence reading never decides whether a rule blocks). A whole
    text (start_fenced None) raises UnclosedFence at an open end; a slice with
    a start state never raises."""
    items = OrderedDict()

    def add(kind, txt, sec):
        it = Item(kind, txt, sec)
        items.setdefault(it.key(), it)

    for key, body, flags in _section_flags(text, _text_flags(text, start_fenced)):
        for ev in _walk(body, flags):
            if ev[0] == "command":
                add("command", ev[1], key)
            elif ev[0] == "heading":
                add("heading", ev[1], key)
            elif ev[0] == "line":
                for tok in TOKEN_RE.findall(ev[1]):
                    k = token_kind(tok)
                    if k:
                        add(k, tok.strip(), key)
            else:
                for x in unit_sentences(ev[1]):
                    add("rule", x, key)
    return list(items.values())


# ---------------------------------------------------------------- kept

class Text(object):
    """A text prepared once for repeated kept-checks (linear time)."""

    def __init__(self, text):
        self.raw = text
        words = normalize(text).split()
        self.padded = " " + " ".join(words) + " "
        self.windows = set(tuple(words[i:i + WINDOW])
                           for i in range(max(0, len(words) - WINDOW + 1)))
        # for kept units: physical lines holding a base word, never `only`
        self.rule_lines = "\n".join(l for l in text.splitlines() if RULE_BASE_RE.search(l))
        self.headings = set(strip_instances(l.strip()) for l in text.splitlines()
                            if l.startswith("#"))


def _prep(text):
    return text if isinstance(text, Text) else Text(text)


def window_kept(sentence, text):
    """Kept clause (b): any 5-word window of the sentence is in the text; a
    sentence under 5 words needs its whole normalized form."""
    t = _prep(text)
    words = normalize(sentence).split()
    if not words:
        return False
    if len(words) < WINDOW:
        return (" " + " ".join(words) + " ") in t.padded
    return any(tuple(words[i:i + WINDOW]) in t.windows
               for i in range(len(words) - WINDOW + 1))


def on_edges(token, text):
    """Token edges: does `text` hold `token` on token edges? The
    character before it is not a letter, digit, '_', '.', '/' or '-'; the one
    after it is not a letter, digit, '_', '/' or '-', nor a '.' followed by a
    letter or digit; the start and end of a line count as edges. One pattern,
    shared by the open-work key_in, kept clause (a) and the identifier, path and
    command atoms (item_kept).

    It is the regex (?<![\w./-])TOKEN(?![\w/-]|\.\w), read occurrence by
    occurrence with str.find for speed on long texts. A word character is
    what the regex's \w is: str.isalnum() or '_'."""
    if not token:
        return re.search(r"(?<![\w./-])(?![\w/-]|\.\w)", text) is not None
    word = lambda ch: ch.isalnum() or ch == "_"
    n, i = len(token), text.find(token)
    while i != -1:
        before = text[i - 1] if i else ""
        after = text[i + n] if i + n < len(text) else ""
        nxt = text[i + n + 1] if i + n + 1 < len(text) else ""
        if not (before and (word(before) or before in "./-")) and not (
                after and (word(after) or after in "/-" or (after == "." and nxt and word(nxt)))):
            return True
        i = text.find(token, i + 1)
    return False


def clause_a_kept(sentence, text):
    """Kept clause (a): one of the sentence's backticked tokens, not on the
    stoplist, appears on token edges on a rule-shaped line of the text
    (Text.rule_lines, the base words of RULE_BASE_RE). `text` is a str or a
    prepared Text; it is prepared once, never per call. The
    substring test runs first only because it is cheap: an edge match is
    always a substring match (it keeps the check fast on large files)."""
    t = _prep(text)
    for tok in TOKEN_RE.findall(sentence):
        tok = tok.strip()
        if tok and tok not in STOPLIST and tok in t.rule_lines and on_edges(tok, t.rule_lines):
            return True
    return False


def rule_kept(sentence, text):
    """Kept: (a) a backticked token (not on the stoplist) on token edges on a
    rule-shaped line of the text, or (b) a 5-word window of the sentence in
    the text. The LISTING judge only (clause (a) lists, never keeps):
    no refusal, exit code, class or [already kept] mark reads it."""
    t = _prep(text)
    if clause_a_kept(sentence, t):
        return True
    return window_kept(sentence, t)


def unit_kept(unit, text):
    """Units: a rule unit is kept only when every rule sentence in it is
    kept by clause (b) (window_kept; clause (a) lists, never keeps); a unit
    with none, which the atom rules make unreachable for a rule-shaped unit, is judged
    whole."""
    t = _prep(text)
    return all(window_kept(x, t) for x in (unit_sentences(unit) or [unit]))


def item_kept(item, text):
    """Kept: a rule by clause (b) alone (window_kept; clause (a) lists, never
    keeps), a heading exactly (without its count), and an identifier, path or
    command on token edges (on_edges); the substring test
    runs first only because it is cheap."""
    t = _prep(text)
    if item.kind == "rule":
        return window_kept(item.text, t)
    if item.kind == "heading":
        return strip_instances(item.text) in t.headings
    return item.text in t.raw and on_edges(item.text, t.raw)


# ---------------------------------------------------------------- lazy files

def notes_set(folder, exclude=()):
    """NOTES SET: the top-level regular *.md files of the folder, never a
    subfolder, never CLAUDE.md, never a backup; a symlink only when its target
    resolves inside the folder. `exclude` drops more paths by realpath."""
    real = os.path.realpath(folder)
    drop = set(os.path.realpath(p) for p in exclude)
    out = []
    for name in sorted(os.listdir(folder)):
        p = os.path.join(folder, name)
        if not name.endswith(".md") or name == "CLAUDE.md":
            continue
        if ".backup-before-split-" in name:
            continue
        rp = os.path.realpath(p)
        # containment first (an lstat of the link itself): a link that
        # resolves outside the folder is skipped before any stat follows it
        if is_link(p) and os.path.commonpath([rp, real]) != real:
            continue
        if not is_file(p):                       # a disk error rises
            continue
        if rp in drop:
            continue
        out.append(p)
    return out


# ---------------------------------------------------------------- pointers

INDEX_NAME = "CLAUDE_DECISIONS_INDEX.md"
MEMORY_LINK_RE = re.compile(r"\[\[([^\[\]\n]+)\]\]")
FILE_LINE_RE = re.compile(r":\d[\d,\-]*$")
FILE_TOKEN_RE = re.compile(r"^[^\s<>*?{}$|]+\.[A-Za-z][A-Za-z0-9]{0,9}$")
SAME_HEADING_RE = re.compile(r"\bsame heading\b", re.IGNORECASE)


class Pointer(object):
    """One pointer of a text and what it resolved to.

    kind: 'file' or 'memory'. status: RESOLVED, UNRESOLVED or SKIPPED.
    section: the '## ' section key. lineno: 1-based line in the text.
    path: the resolved real path (a 'present' name reads as <base>/<name>).
    via: the archive paths an index pointer also resolves (the hub).
    """
    __slots__ = ("section", "lineno", "kind", "token", "same_heading", "status",
                 "path", "via", "why")

    def __init__(self, section, lineno, kind, token, same_heading=False):
        self.section, self.lineno, self.kind, self.token = section, lineno, kind, token
        self.same_heading = same_heading
        self.status, self.path, self.via, self.why = "UNRESOLVED", None, [], ""

    def targets(self):
        if self.status != "RESOLVED":
            return []
        return [self.path] + list(self.via)

    def __repr__(self):
        return "Pointer(%r, %r, %r)" % (self.token, self.status, self.why)


def file_token(tok):
    """The file name a backticked token points at, or None when the token is no
    file: a folder (ends '/'), a URL, a command, a placeholder or a glob. A
    trailing ':<line>' is dropped (`rotate.py:183` points at rotate.py)."""
    t = tok.strip()
    if not t or t.endswith("/") or "://" in t:
        return None
    t = FILE_LINE_RE.sub("", t)
    return t if FILE_TOKEN_RE.match(t) else None


def heading_text(line):
    """A heading compared for 'same heading': the '#' marks and an
    '(N instances)' count removed, so neither level nor count matters."""
    return strip_instances(line.strip().lstrip("#").strip())


def _places(tok, base, roots):
    """Candidate paths for a path-like token: absolute and '~' forms as
    written; any other form joined to the base, then to each root, in order."""
    t = tok.strip()
    if t.startswith("~"):
        return [os.path.expanduser(t)]
    if os.path.isabs(t):
        return [t]
    return [os.path.join(b, t) for b in [base] + list(roots)]


def pointers(text, base, roots, memory_dir, present=None, cache=None):
    """Every pointer of `text` (a file in folder `base`), resolved.

    A pointer is a backticked file token on a line that also says See,
    Evidence, Detail, same heading, pointer, lives in or moved to, plus every
    [[name]]. A file resolves against, in order: `base`, each of `roots`, and
    the folders named by a backticked token ending in '/' earlier in the same
    section. A 'same heading' pointer also needs the nearest heading above it
    to be a heading of the target, compared by heading_text(). [[name]]
    resolves to <memory_dir>/<name>.md, or is SKIPPED when memory_dir is None.

    roots has NO default here: only pointers.py's argument parsing
    applies the home .claude folder. present: {name relative to base: text} of
    files a caller is about to write; a name there resolves as a file of that
    text and wins over the disk. A pointer that resolves to
    CLAUDE_DECISIONS_INDEX.md also resolves every archive the index names in
    backticks (the hub). cache: the run's read_once dict {realpath: text};
    a target whose realpath it holds is answered from that text,
    never statted or read again, wherever it sits; `present` still wins for a
    name inside base. Returns [Pointer] in text order.
    """
    present = dict((os.path.normpath(k), v) for k, v in (present or {}).items())
    if cache is None:
        cache = {}      # a caller with no run cache (pointers.py): one read per target per call
    real_base = os.path.realpath(base)
    roots = [os.path.realpath(os.path.expanduser(r)) for r in roots]

    def lookup(path):
        """(real path, present text or None) when the file exists, else None."""
        rp = os.path.realpath(path)
        rel = os.path.relpath(rp, real_base)
        if not rel.startswith(".." + os.sep) and rel != "..":
            if os.path.normpath(rel) in present:
                return rp, present[os.path.normpath(rel)]
        if rp in cache:                          # read once in this run
            return rp, cache[rp]
        st = token_stat_of(rp)                   # absence widened for a pointer candidate
        if st is not None and stat.S_ISREG(st.st_mode):
            return rp, None
        return None

    def body_of(rp, txt):
        """A target's text. A read that fails rises: an
        unreadable target is cannot tell, never an empty text."""
        if txt is not None:
            return txt
        return read_once(cache, rp)

    def hub(rp, txt):
        """The hub: the archives the index names in backticks that exist."""
        out = []
        folder = os.path.dirname(rp)
        for tok in TOKEN_RE.findall(body_of(rp, txt)):
            name = tok.strip()
            if not ARCHIVE_NAME_RE.match(os.path.basename(name)):
                continue
            hit = lookup(os.path.join(folder, name))
            if hit and hit[0] not in out:
                out.append(hit[0])
        return out

    found = []
    lineno = 0
    # one fence reader over the whole text; an unclosed fence raises
    fenced = closed_fence_states(text.splitlines())
    for key, body in sections(text).items():
        folders = []
        heading = key[0] or None
        for ln in body.splitlines():
            lineno += 1
            if fenced[lineno - 1]:
                continue
            if ln.startswith("#"):
                heading = ln
                continue
            for name in MEMORY_LINK_RE.findall(ln):
                name = name.strip()
                p = Pointer(key, lineno, "memory", name)
                if memory_dir is None:
                    p.status, p.why = "SKIPPED", "no --memory-dir given"
                else:
                    hit = lookup(os.path.join(memory_dir, name + ".md"))
                    if hit:
                        p.status, p.path = "RESOLVED", hit[0]
                    else:
                        p.why = "no %s.md in the memory folder" % name
                found.append(p)
            pointer_line = bool(POINTER_WORD_RE.search(ln))
            same = bool(SAME_HEADING_RE.search(ln))
            for tok in TOKEN_RE.findall(ln):
                if tok.strip().endswith("/"):
                    folders.append(tok.strip())
                    continue
                name = file_token(tok)
                if not name or not pointer_line:
                    continue
                p = Pointer(key, lineno, "file", name, same)
                cands = _places(name, real_base, roots)
                if not (name.startswith("~") or os.path.isabs(name)):
                    for fd in folders:
                        cands += [os.path.join(c, name) for c in _places(fd, real_base, roots)]
                hit = None
                for c in cands:
                    hit = lookup(c)
                    if hit:
                        break
                if not hit:
                    p.why = ("no such file in the file's folder, a --root or a folder "
                             "named earlier in the section")
                    found.append(p)
                    continue
                rp, txt = hit
                p.path = rp
                if same:
                    want = heading_text(heading) if heading else ""
                    # a heading inside a fenced example of the target is no heading
                    tlines = body_of(rp, txt).splitlines()
                    tfenced = fence_states(tlines)[0]
                    have = set(heading_text(l) for l, f in zip(tlines, tfenced)
                               if not f and l.startswith("#"))
                    if not want or want not in have:
                        p.why = ("'same heading', but %s has no heading %r"
                                 % (os.path.basename(rp), want or "(no heading above the line)"))
                        found.append(p)
                        continue
                p.status = "RESOLVED"
                if os.path.basename(rp) == INDEX_NAME:
                    p.via = hub(rp, txt)
                found.append(p)
    return found


def pointer_targets(ptrs, section=None):
    """The real paths the RESOLVED pointers reach (archives through the hub
    included), of one '## ' section key or, with section None, the whole text."""
    out = set()
    for p in ptrs:
        if section is None or p.section == section:
            out.update(p.targets())
    return out


# ---------------------------------------------------------------- classify

def classify(before_text, after_text, base, lazy=(), hoisted=(), narrative=None,
             roots=(), memory_dir=None, present=None, cache=None):
    """Classify every atom of before_text; return Result records.

    after_text: the after CLAUDE.md text. base: the CLAUDE.md folder.
    lazy: [(path, text)] of the lazy files. hoisted: [(path, text)] of accepted
    --hoisted files (an absent flag counts nothing as kept). narrative: an
    optional {rule sentence text: waiver label} that rotate.py builds from its
    --narrative records; it waives only LAZY-ONLY rule sentences.
    roots, memory_dir, present, cache: passed to pointers() for the
    POINTED classes; roots defaults to none at all, never the home .claude
    folder; cache is the run's read_once dict.
    """
    after = Text(after_text)
    after_secs = sections(after_text)
    lazy_t = [(p, Text(t)) for p, t in lazy]
    hoist_t = [(p, Text(t)) for p, t in hoisted]
    real_base = os.path.realpath(base)

    def rel(p):
        return os.path.relpath(os.path.realpath(p), real_base)
    ptrs = pointers(after_text, base, roots, memory_dir, present, cache)
    whole_targets = pointer_targets(ptrs)
    results = []
    for it in atoms(before_text):
        if item_kept(it, after):
            results.append(Result(it, "KEPT", []))
            continue
        h_hold = [p for p, t in hoist_t if item_kept(it, t)]
        l_hold = [p for p, t in lazy_t if item_kept(it, t)]
        holding = sorted(set(rel(p) for p in h_hold + l_hold))
        if h_hold:
            results.append(Result(it, "KEPT (hoisted)", holding, rel(h_hold[0])))
            continue
        if not l_hold:
            results.append(Result(it, "NOWHERE", []))
            continue
        if it.section in after_secs:
            sec_targets = pointer_targets(ptrs, it.section)
            if any(os.path.realpath(p) in sec_targets for p in l_hold):
                results.append(Result(it, "POINTED", holding))
                continue
        if it.kind != "rule":
            arch = [p for p in l_hold if ARCHIVE_NAME_RE.match(os.path.basename(p))
                    and os.path.realpath(p) in whole_targets]
            if arch:
                results.append(Result(it, "POINTED (archive)", holding, rel(arch[0])))
                continue
        r = Result(it, "LAZY-ONLY", holding)
        if narrative and it.kind == "rule" and it.text in narrative:
            r.waiver = narrative[it.text]
        results.append(r)
    return results


# ---------------------------------------------------------------- waivers

def refuse_empty_waiver(flag, value):
    """A waiver value that is empty or whitespace-only would match
    every item. Returns the refusal message, or None when the value is fine.
    Called once per waiver flag value before any check runs."""
    if value is None or not value.strip():
        return ("CANNOT TELL: %s was given an empty value; it would waive every "
                "item. Nothing was checked or written." % flag)
    return None


def accept_lines(text):
    """One waiver per line; lines stripped; empty lines skipped; no
    comment syntax (a '#' line is a waiver like any other). The
    caller passes the text its guarded read returned, never a second open."""
    return [l.strip() for l in text.splitlines() if l.strip()]


def read_accept_file(path):
    """accept_lines of a file (for a caller with no text in hand)."""
    with open(path, encoding="utf-8") as fh:
        return accept_lines(fh.read())


def apply_waivers(results, waivers):
    """Match each waiver (case-insensitive substring of the item text) against
    the BLOCKING items; mark each item with the first waiver matching it.

    waivers: [(label, value)], label e.g. '--accept "x"'. Returns
    [(label, value, count, broad, owners)] in the order given; count is the
    number of items that waiver lets through (an item counts for the waiver
    that owns it, never for a later one that also matches it), broad when
    count > BROAD_LIMIT, and owners the labels that already held the
    items this waiver matched but did not take (a --narrative, set by
    classify, or an earlier waiver), sorted.
    """
    out = []
    for label, value in waivers:
        v = value.strip().lower()
        n, owners = 0, set()
        for r in results:
            if r.blocking() and v in r.item.text.lower():
                if r.waiver is None:
                    r.waiver = label
                    n += 1
                else:
                    owners.add(r.waiver)
        out.append((label, value, n, n > BROAD_LIMIT, sorted(owners)))
    return out


def unwaived_blocking(results):
    return [r for r in results if r.blocking() and r.waiver is None]


# ---------------------------------------------------------------- rendering

def listing_lines(results):
    """Every LAZY-ONLY and NOWHERE item on its own line, the item whole,
    a waived one ending ' (waived: <waiver>)', each followed by one indented
    detail line naming its kind, section and what would let it through. KEPT
    and POINTED items are counted, never listed. rotate.py prints through this
    same function."""
    out = []
    for r in results:
        if r.cls not in ("LAZY-ONLY", "NOWHERE"):
            continue
        line = "%s: %s" % (r.cls, r.item.text)
        if r.waiver:
            line += " (waived: %s)" % r.waiver
        out.append(line)
        sec = section_name(r.item.section)
        if r.blocking() and not r.waiver:
            how = 'blocks; --accept "<fragment of it>" lets it through'
        elif r.blocking():
            how = "let through by its waiver"
        else:
            how = "listed, not blocking"
        held = (" held in " + ", ".join(r.holding)) if r.holding else ""
        out.append("    %s in section %s;%s %s" % (r.kind, sec, held, how))
    return out


def class_counts(results):
    order = ["KEPT", "KEPT (hoisted)", "POINTED", "POINTED (archive)",
             "LAZY-ONLY", "NOWHERE"]
    counts = OrderedDict((c, 0) for c in order)
    for r in results:
        counts[r.cls] += 1
    return counts


def waiver_lines(waiver_counts):
    out = []
    for label, value, n, broad, owners in waiver_counts:
        if n == 0 and owners:
            out.append("UNUSED WAIVER: %s let through no item (every match already waived by %s)"
                       % (label, ", ".join(owners)))
        elif n == 0:
            out.append("UNUSED WAIVER: %s matched no item" % label)
        else:
            out.append("WAIVER: %s let through %d item(s)" % (label, n))
        if broad:
            out.append("BROAD WAIVER: %s let through %d items (more than %d); "
                       "name each item instead" % (label, n, BROAD_LIMIT))
    return out


# ---------------------------------------------------------------- open work

OPEN_ITEM_RE = re.compile(r"^(\s*)- \[ \]\s?(.*)$")
CHECKBOX_RE = re.compile(r"^\s*[-*+] \[[ xX]\]")
HEX_WORD_RE = re.compile(r"(?<![\w./-])[0-9a-f]{7,40}(?![\w/-])")
DATE_TEXT_RE = re.compile(r"\d{4}-\d{2}-\d{2}")
WORD_RE = re.compile(r"[a-z0-9]+")
BARE_FOLDER_RE = re.compile(r"^[^/\s]+/$")
IDENT_SHAPE_RE = re.compile(r"[._/0-9]")


class OpenItem(object):
    """One open '- [ ]' item: its file, its 1-based ordinal among that file's
    open items, and its text after '- [ ] ' with continuation lines joined."""
    __slots__ = ("source", "ordinal", "text")

    def __init__(self, source, ordinal, text):
        self.source, self.ordinal, self.text = source, ordinal, text

    def __repr__(self):
        return "OpenItem(%r, %d)" % (os.path.basename(self.source), self.ordinal)


def open_items(paths):
    """The open '- [ ]' items of each file, each with its indented
    continuation lines (deeper than the item, not blank, not a checkbox of its
    own) joined by one space. A nested '- [ ]' is an item of its own."""
    out = []
    for path in paths:
        with open(path, encoding="utf-8", errors="replace") as fh:
            lines = fh.read().splitlines()
        n, i = 0, 0
        while i < len(lines):
            m = OPEN_ITEM_RE.match(lines[i])
            if not m:
                i += 1
                continue
            indent, parts = len(m.group(1)), [m.group(2).strip()]
            j = i + 1
            while j < len(lines):
                ln = lines[j]
                if not ln.strip() or CHECKBOX_RE.match(ln):
                    break
                if len(ln) - len(ln.lstrip()) <= indent:
                    break
                parts.append(ln.strip())
                j += 1
            n += 1
            out.append(OpenItem(path, n, " ".join(p for p in parts if p)))
            i = j
    return out


def record_keys(title, text):
    """A record's candidate keys, in order, as (kind, key): its backticked
    tokens of 4+ chars that look like an identifier (hold '.', '_', '/' or a
    digit; not a bare 'word/'; not on the stoplist), every hex hash (7 to 40
    hex chars on token edges, all letters or all digits included:
    hashes always qualify), and every 4-word run of its title
    with the date removed. Distinctiveness (records, items) is the matcher's."""
    keys, seen = [], set()

    def add(kind, key):
        if key not in seen:
            seen.add(key)
            keys.append((kind, key))

    for tok in TOKEN_RE.findall(text):
        t = tok.strip()
        if (len(t) < 4 or t in STOPLIST or BARE_FOLDER_RE.match(t)
                or not IDENT_SHAPE_RE.search(t)):
            continue
        add("token", t)
    for h in HEX_WORD_RE.findall(text):
        add("hash", h)
    words = WORD_RE.findall(DATE_TEXT_RE.sub(" ", title.lower()))
    for i in range(len(words) - 3):
        add("title", " ".join(words[i:i + 4]))
    return keys


def key_in(kind, key, text):
    """Does `text` hold the key on token edges (never inside a longer
    token)? A title run matches whole words in order."""
    if kind == "title":
        return (" " + key + " ") in (" " + " ".join(WORD_RE.findall(text.lower())) + " ")
    return on_edges(key, text)


def density(record_text):
    """The open-work density column, from survey's classify_shape: (shape, obligations
    per non-empty body line, reference score)."""
    import survey  # noqa: E402  (imported only where open work needs it)
    shape, ev = survey.classify_shape(record_text)
    n = len([l for l in record_text.split("\n")[1:] if l.strip()])
    obl = (ev.get("obligations", 0) / float(n)) if n else 0.0
    return shape, obl, float(ev.get("ref", 0.0))


# ---------------------------------------------------------------- --hoisted

def loaded_set(folder, home=None):
    """The CLAUDE.md files a session launched in `folder` loads:
    <A>/CLAUDE.md for every proper ancestor A up to '/', <F>/.claude/CLAUDE.md
    and <home>/.claude/CLAUDE.md. All realpath'd."""
    f = os.path.realpath(folder)
    out = [os.path.join(f, ".claude", "CLAUDE.md")]
    a = f
    while True:
        parent = os.path.dirname(a)
        if parent == a:
            break
        a = parent
        out.append(os.path.join(a, "CLAUDE.md"))
    if home is None:
        home = os.path.expanduser("~")
    out.append(os.path.join(os.path.realpath(home), ".claude", "CLAUDE.md"))
    # membership is realpath equality, so the last part (a CLAUDE.md or
    # a .claude folder that is itself a link) is resolved too
    return [os.path.realpath(x) for x in out]


def hoisted_refusal(path, split_files, home=None):
    """None when `path` is an accepted --hoisted file, else the reason.

    split_files: the file(s) being split; the first one's folder is F. Both
    sides are realpath'd and containment uses commonpath, never
    startswith. The caller checks existence first.
    """
    p = os.path.realpath(path)
    targets = [os.path.realpath(s) for s in split_files]
    folder = os.path.dirname(targets[0])
    if p in targets:
        return ("it is the file being split; a block inside it is already "
                "counted without the flag")
    other = ("--hoisted takes another always-loaded CLAUDE.md, for example "
             "~/.claude/CLAUDE.md")
    if os.path.basename(p) != "CLAUDE.md":
        return other
    if (os.path.commonpath([p, folder]) == folder
            and p != os.path.realpath(os.path.join(folder, ".claude", "CLAUDE.md"))):
        return other
    accepted = loaded_set(folder, home)
    if p not in accepted:
        return ("not loaded: no session launched in %s loads that file; accepted: "
                "<ancestor>/CLAUDE.md, %s, %s" % (folder, accepted[0], accepted[-1]))
    return None


# ---------------------------------------------------------------- structure

def _drop_last_run(text, with_blank):
    """Remove every 'Last split run:' line; with_blank also drops the ONE
    blank line directly after each (the blank placement (3) adds)."""
    lines = text.splitlines(keepends=True)
    out = []
    i = 0
    while i < len(lines):
        if lines[i].startswith(LAST_RUN_PREFIX):
            i += 1
            if with_blank and i < len(lines) and not lines[i].strip():
                i += 1
            continue
        out.append(lines[i])
        i += 1
    return "".join(out)


def _edited_match(key, edited):
    head = key[0]
    for e in edited:
        e = e.strip()
        if e in (head, head[3:] if head.startswith("## ") else head):
            return True
        if not head and e.lower() == "preamble":
            return True
    return False


def structure_diffs(before_text, after_text, edited=()):
    """[(key, why)] for every AFTER section (preamble included) that is
    not byte-identical to the same (heading, n) section of BEFORE, and every
    section only in AFTER, unless named by `edited`. Last-run lines are
    removed from both sides; then the AFTER side may drop the one blank line
    that directly follows its Last-run line, and nothing else."""
    b = sections(before_text)
    out = []
    for key, a_sec in sections(after_text).items():
        if _edited_match(key, edited):
            continue
        if key not in b:
            out.append((key, "new section; name it with --edited"))
            continue
        b_sec = _drop_last_run(b[key], False)
        if _drop_last_run(a_sec, False) == b_sec:
            continue
        if _drop_last_run(a_sec, True) == b_sec:
            continue
        out.append((key, "changed"))
    return out
