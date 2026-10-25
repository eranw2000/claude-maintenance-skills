#!/usr/bin/env python3
"""Close a session that went idle for 50 minutes, and refuse one idle past an hour.

Two bands, measured from the last time this session was active (the end of
the previous assistant turn, or the previous prompt):

  50 to 60 minutes  ->  run /close-session, print the saved line, stop.
  over 60 minutes   ->  refuse the request and ask for a fresh session.

The 60-minute band matches the prompt cache. On subscription auth Claude Code
requests the 1-hour TTL, and that TTL is an inactivity timer, so only a gap
over an hour expires the prefix. Resuming a long session after that gap pays
a full cache write on a prefix that grew all day.

Nothing wakes a sleeping session, so both bands fire on the NEXT prompt. That
loses nothing: an idle session is frozen, so what /close-session saves at
minute 50 is the same as what it saves at minute 71.

The over-an-hour band BLOCKS (exit 2), because an injected instruction is only
a hint that a model can talk itself out of. It is sticky for the rest of the
session, otherwise retyping the prompt walks straight through it.
/close-session, /save-context and /improve-dev-workflow are always let
through, so the guard never leaves the user with no way to save.

The Stop half saves at turn end. It blocks the stop and asks for /save-context
when the context grew by SAVE_GROWTH_TOKENS since the last save, first passed
FORCED_SAVE_TOKENS, or has not been saved for STALE_SAVE_SECONDS. Past
BIG_SESSION_TOKENS it nudges once to close before walking away. Turn end is
the only moment this can happen: no hook fires on a timer, and a hook cannot
start a turn or invoke a skill. The reason text reaches Claude as plain text,
and Claude acts on it.

Stop blocks via a top-level {"decision": "block", "reason": ...} on stdout,
which is the documented form for THIS event. Do not copy PreToolUse's exit-2
contract here.

Wire BOTH:
  UserPromptSubmit ->  python3 ~/.claude/hooks/session-idle-guard.py
  Stop             ->  python3 ~/.claude/hooks/session-idle-guard.py

Two things are never blocked:

  a <task-notification> prompt  ->  the harness reporting finished work. It is
                                    activity, so it stamps the clock and passes.
  a background or remote session ->  never force-closed. Past an hour the prompt
                                    is still refused, through the JSON block
                                    form, so no model call is made and the
                                    reason reaches the user. See session_mode().

Escape hatches: CLAUDE_IDLE_GUARD_OFF=1 in the environment disables it entirely
(for scheduled or background sessions, where a blocked prompt would break the
automation), CLAUDE_IDLE_GUARD_NO_SAVE=1 disables ONLY the forced save and
keeps the idle bands, and the marker below lets a single prompt through.
"""
import json
import os
import sys
import time

HOME = os.path.expanduser("~")
STATE_DIR = os.path.join(HOME, ".claude", "hooks", ".session-idle")

AUTOCLOSE_SECONDS = 50 * 60      # 50 minutes: save and stop
EXPIRED_SECONDS = 60 * 60        # 60 minutes: refuse, start fresh
PRUNE_AFTER_SECONDS = 7 * 24 * 3600

# Turn-end trigger. SIZE FIRST, TIME ONLY AS A BACKSTOP.
#
# Elapsed time is a poor stand-in for what is at risk, which is how much
# unsaved context exists, so the save fires on context size. It still runs at
# TURN END: nothing wakes a sleeping session and a hook cannot start a turn,
# so an idle check would only run on the next prompt, too late to matter.
#
# First crossing of this total forces one save.
FORCED_SAVE_TOKENS = 600_000
# After ANY save, this much NEW context forces the next one. Without it the
# total rule above would re-fire on every turn once the session sits past
# FORCED_SAVE_TOKENS, which is the cry-wolf failure BIG_SESSION_TOKENS already
# guards against.
SAVE_GROWTH_TOKENS = 200_000
# The time backstop covers a session whose token count cannot be read, and
# a session that works for hours without growing. A continuously working
# session refreshes its own prefix on every request; only an idle gap over
# an hour expires it.
STALE_SAVE_SECONDS = 4 * 3600
# One nudge per session once the prefix passes this. Fired ONCE rather than
# every turn, because a check that cries wolf gets discounted.
BIG_SESSION_TOKENS = 500_000

OVERRIDE_MARKER = "#continue-anyway"
# Let through in BOTH bands. The first two are the save path, so the guard can
# never trap the user with no way to save. /improve-dev-workflow turns a
# harness failure into a durable fix, and the guard fires exactly when that
# failure is freshest.
ALWAYS_ALLOWED = ("/close-session", "/save-context", "/improve-dev-workflow")
# The subset of the above that actually WRITES this session's context.
# /improve-dev-workflow edits harness artifacts rather than saving the
# session, so it may not reset the stale-save clock.
SAVE_COMMANDS = ("/close-session", "/save-context")

# Prompts the HARNESS submits, not the user. A background command or agent
# finishing arrives as a UserPromptSubmit whose text is a <task-notification>
# block. The gap before it is the time that work ran, so it is proof the
# session was BUSY, not idle, and blocking it would throw away the result.
HARNESS_PROMPT_PREFIXES = ("<task-notification>",)

# Environment markers of a session the user reaches from somewhere else. A
# hard block there strands them: from a phone the prompt just vanishes, and a
# forced /close-session tears down background agents a long run is waiting
# on. In these sessions nothing is force-closed; past an hour the prompt is refused.
#   CLAUDE_JOB_DIR                 set in a background job (claude --bg)
#   CLAUDE_CODE_SESSION_ATTENDED   "0" when no terminal is attached
#   CLAUDE_CODE_BRIDGE_SESSION_ID  set when the session is bridged to claude.ai
#                                  for remote control
BACKGROUND_ENV = "CLAUDE_JOB_DIR"
ATTENDED_ENV = "CLAUDE_CODE_SESSION_ATTENDED"
BRIDGE_ENV = "CLAUDE_CODE_BRIDGE_SESSION_ID"

# The lines shown to the user. Keep the wording stable.
SAVED_LINE = "**This session was saved after 50 minutes idle**"
EXPIRED_LINE = (
    "You have been away more than an hour, please close the session and "
    "start a fresh session"
)
# Who the messages to Claude name. Put your own name here if you like.
USER = "the user"


def state_path(session_id: str) -> str:
    safe = "".join(c for c in str(session_id) if c.isalnum() or c in "-_")
    return os.path.join(STATE_DIR, (safe or "unknown") + ".json")


def read_state(path: str) -> dict:
    try:
        with open(path) as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def write_state(path: str, state: dict) -> None:
    try:
        os.makedirs(STATE_DIR, exist_ok=True)
        tmp = path + ".tmp"
        with open(tmp, "w") as fh:
            json.dump(state, fh)
        os.replace(tmp, path)
    except Exception:
        pass


def prune(now: float) -> None:
    """Drop stamps for sessions that ended long ago, so the dir cannot grow forever."""
    try:
        for name in os.listdir(STATE_DIR):
            p = os.path.join(STATE_DIR, name)
            if now - os.path.getmtime(p) > PRUNE_AFTER_SECONDS:
                os.remove(p)
    except Exception:
        pass


def minutes(seconds: float) -> int:
    return int(seconds // 60)


def is_save_command(prompt: str) -> bool:
    """True only for a prompt whose FIRST token is a real save command.

    An exact token match, not a prefix: a longer command that merely starts
    with /close-session must not reset the stale-save clock.
    """
    parts = (prompt or "").strip().lower().split()
    return bool(parts) and parts[0] in SAVE_COMMANDS


SAVE_SKILLS = ("save-context", "close-session")
SKILL_MARKER = b'"name":"Skill"'


def saw_save_skill(state: dict, transcript_path) -> bool:
    """True when the transcript gained a Skill call to a save skill since the last look.

    A save Claude runs because the user asked in words, or because a skill
    called it, never arrives as a typed /save-context prompt. Reading only the new
    bytes keeps this cheap on a multi-megabyte transcript; a transcript seen for the
    first time is marked, never read back, so an old save cannot reset the clock.
    """
    if not transcript_path:
        return False
    try:
        size = os.path.getsize(transcript_path)
    except OSError:
        return False
    offset = state.get("scan_offset")
    if (state.get("scan_path") != transcript_path or not isinstance(offset, int)
            or offset > size):
        state["scan_path"] = transcript_path
        state["scan_offset"] = size
        return False
    try:
        with open(transcript_path, "rb") as fh:
            fh.seek(offset)
            chunk = fh.read(size - offset)
    except OSError:
        return False
    end = chunk.rfind(b"\n")
    if end < 0:
        return False
    state["scan_offset"] = offset + end + 1
    for line in chunk[:end].split(b"\n"):
        if SKILL_MARKER not in line:
            continue
        try:
            content = (json.loads(line).get("message") or {}).get("content")
        except Exception:
            continue
        for item in content if isinstance(content, list) else ():
            if (isinstance(item, dict) and item.get("type") == "tool_use"
                    and item.get("name") == "Skill"
                    and (item.get("input") or {}).get("skill") in SAVE_SKILLS):
                return True
    return False


def is_harness_prompt(prompt: str) -> bool:
    """True when the harness, not a person, submitted this prompt."""
    return (prompt or "").lstrip().startswith(HARNESS_PROMPT_PREFIXES)


def session_mode() -> str:
    """'background', 'remote' or 'local'. Only 'local' may be hard-blocked."""
    if os.environ.get(BACKGROUND_ENV) or os.environ.get(ATTENDED_ENV) == "0":
        return "background"
    if os.environ.get(BRIDGE_ENV):
        return "remote"
    return "local"


def session_tokens(transcript_path):
    """Prefix size in tokens at the last assistant turn, or None if unreadable.

    Every call sends the whole prefix, so its size is what a cold resume would
    have to re-write. The three input fields are disjoint parts of that one
    prefix (fresh + cache-write + cache-read), so they sum; output_tokens is
    NOT part of it and is deliberately excluded.

    Reads only the tail: a transcript runs to megabytes and this fires on every
    turn. Iterating in reverse also disposes of the partial line the byte-offset
    read leaves at the FRONT of the buffer, which is never reached.

    Returns None on anything unexpected. A nudge that cannot measure must stay
    silent rather than guess.
    """
    if not transcript_path:
        return None
    try:
        with open(transcript_path, "rb") as fh:
            fh.seek(0, os.SEEK_END)
            fh.seek(max(0, fh.tell() - 262144))
            chunk = fh.read().decode("utf-8", "replace")
    except Exception:
        return None
    for line in reversed(chunk.split("\n")):
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            usage = (json.loads(line).get("message") or {}).get("usage") or {}
        except Exception:
            continue
        total = 0
        seen = False
        for key in ("input_tokens", "cache_creation_input_tokens",
                    "cache_read_input_tokens"):
            value = usage.get(key)
            if isinstance(value, int):
                total += value
                seen = True
        if seen:
            return total
    return None


def autoclose_context(gap: float) -> str:
    return "\n".join([
        "IDLE GUARD: this session was last active %d minutes ago, over the "
        "50-minute idle limit." % minutes(gap),
        "",
        "Do this now, and do NOT carry out the request in the message you just "
        "received:",
        "1. Run the /close-session skill in full (save context, then clean up).",
        "   EXCEPTION: if background agents, tasks or a long-running loop "
        "are still running, run /save-context instead, so that work keeps "
        "running and its results still arrive.",
        "2. Then write this line, exactly as written, as the last thing you say:",
        "   " + SAVED_LINE,
        "3. Stop. Do not start any other work in this turn.",
        "",
        "The request itself is not lost: %s can send it again after the close, "
        "and chooses whether to continue here or start fresh." % USER,
    ])


def expired_message(gap: float) -> str:
    hours = gap / 3600.0
    return "\n".join([
        EXPIRED_LINE,
        "",
        "(Idle guard: %.1f hours since this session was last active, past the "
        "1-hour cache window, so resuming costs more and the context is stale.)"
        % hours,
        "You can still run /close-session, /save-context or "
        "/improve-dev-workflow here. To work in this session anyway, resend the "
        "prompt with %s appended." % OVERRIDE_MARKER,
        "To start fresh, open a new session and run /new-session there.",
    ])


def forced_save_message(trigger: str, tokens) -> str:
    """`trigger` says WHICH rule fired, in plain words rather than a constant
    name. The banner says SAVE and never IDLE, because two clocks live in this
    file."""
    size = ""
    if isinstance(tokens, int):
        size = " It is carrying about %d,000 tokens of context." % (tokens // 1000)
    return "\n".join([
        "SAVE GUARD: %s.%s" % (trigger, size),
        "",
        "Before this turn ends, run the /save-context skill in full. Save only, "
        "and do NOT run /close-session: a close tears down shells and background "
        "jobs, which is wrong for a session %s may still be using." % USER,
        "",
        "Then say in one BOLD line that the session was saved, marked with "
        "characters that stand out in a terminal such as ##, for example "
        "`## **Session saved**`. Then stop. Do not start any other work.",
        "",
        "Why now rather than later: nothing can save this session once %s walks "
        "away, and a hook cannot start a turn, so the end of THIS turn is the "
        "only moment a save can happen at all, and it reads a warm prefix here."
        % USER,
    ])


def nudge_message(tokens: int) -> str:
    return (
        "SAVE GUARD: this session is carrying about %d,000 tokens of context. "
        "Close it with /close-session before you walk away, because resuming it "
        "after an hour pays a full cache write. (Shown once per session.)"
        % (tokens // 1000)
    )


def handle_stop(payload: dict, now: float) -> int:
    """The turn just ended: stamp the idle clock, then save or nudge if due.

    This is the only moment anything can be made to happen without the user
    typing. Nothing wakes a sleeping session and a hook cannot start a turn, so
    a save that must survive the user's absence has to run HERE, at the end of
    the last turn, while the context is live and the cache is warm. That is
    also why the trigger is turn-end plus "the last save was long ago" and never
    an idle timer: elapsed idle time is unknowable while the user is away.
    """
    session_id = payload.get("session_id") or "unknown"
    path = state_path(session_id)
    state = read_state(path)
    state["last_active"] = now

    # Measured before any early return, so the diagnostic is recorded every turn.
    tokens = session_tokens(payload.get("transcript_path"))
    state["tokens"] = tokens
    state["saw_transcript"] = bool(payload.get("transcript_path"))

    # Before every early return below, so the scan offset always advances.
    if saw_save_skill(state, payload.get("transcript_path")):
        state["last_save"] = now
        if isinstance(tokens, int):
            state["tokens_at_last_save"] = tokens
            state["forced_at_size"] = tokens >= FORCED_SAVE_TOKENS

    last_save = state.get("last_save")
    if not isinstance(last_save, (int, float)):
        # First sight of this session. Seed rather than fire: a brand-new
        # session has nothing to lose yet, and an absent stamp must not read
        # as an infinitely stale one.
        state["last_save"] = now
        state["tokens_at_last_save"] = tokens if isinstance(tokens, int) else None
        last_save = now      # keep the local in step with the state, so the
                             # arithmetic below stays well defined.
        write_state(path, state)
        return 0

    # Claude is already continuing BECAUSE this hook blocked. Firing again here
    # is the documented way to loop forever. Claude Code also overrides a Stop
    # hook after eight consecutive blocks, which is a backstop, not a licence.
    if payload.get("stop_hook_active"):
        write_state(path, state)
        return 0

    save_gap = max(0.0, now - float(last_save))

    # Size first, time last. Each branch names its own trigger, so the message
    # shown says which rule fired rather than leaving it to be inferred.
    baseline = state.get("tokens_at_last_save")
    growth = (tokens - baseline
              if isinstance(tokens, int) and isinstance(baseline, int)
              else None)
    trigger = ""
    if growth is not None and growth >= SAVE_GROWTH_TOKENS:
        trigger = ("about %d,000 tokens of new context since the last save"
                   % (growth // 1000))
    elif (isinstance(tokens, int) and tokens >= FORCED_SAVE_TOKENS
            and not state.get("forced_at_size")):
        state["forced_at_size"] = True
        trigger = ("this session passed %d,000 tokens" % (FORCED_SAVE_TOKENS // 1000))
    elif save_gap >= STALE_SAVE_SECONDS:
        # The backstop. Reached only when the size rules could not read a token
        # count, or a session genuinely crawled for hours without growing.
        trigger = ("the last save was %d minutes ago and the size rules did not "
                   "fire" % minutes(save_gap))

    if trigger and os.environ.get("CLAUDE_IDLE_GUARD_NO_SAVE") != "1":
        # Stamp BEFORE firing. Claude runs /save-context itself rather than the
        # user typing it, so no UserPromptSubmit confirms it, and stamping first
        # keeps it from re-firing every turn.
        state["last_save"] = now
        state["tokens_at_last_save"] = tokens if isinstance(tokens, int) else baseline
        write_state(path, state)
        # Stop blocks via a TOP-LEVEL decision field, which is the documented
        # form for this event. The reason text reaches Claude as plain text, and
        # Claude acts on it.
        print(json.dumps({
            "decision": "block",
            "reason": forced_save_message(trigger, tokens),
            "systemMessage": "Save guard: forcing a /save-context, because %s."
                             % trigger,
        }))
        return 0

    if isinstance(tokens, int) and tokens >= BIG_SESSION_TOKENS and not state.get("nudged"):
        state["nudged"] = True
        write_state(path, state)
        print(json.dumps({
            "systemMessage": nudge_message(tokens),
            "hookSpecificOutput": {"hookEventName": "Stop"},
        }))
        return 0

    write_state(path, state)
    return 0


def handle_prompt(payload: dict, now: float) -> int:
    session_id = payload.get("session_id") or "unknown"
    prompt = (payload.get("prompt") or "").strip()
    path = state_path(session_id)
    state = read_state(path)

    override = OVERRIDE_MARKER in prompt.lower()
    allowed = prompt.lower().startswith(ALWAYS_ALLOWED)

    mode = session_mode()
    state["mode"] = mode      # diagnostic: the mode the hook read

    if override:
        state["expired"] = False
        state["last_active"] = now
        write_state(path, state)
        return 0

    if is_harness_prompt(prompt):
        # Work was running up to this moment, so this is activity. Never block
        # it and never autoclose on it. The expired flag is left exactly as it
        # was: a notification is not the user coming back.
        state["last_active"] = now
        write_state(path, state)
        return 0

    if allowed:
        # never trap the user with no way to save; the expired flag stays set
        state["last_active"] = now
        if is_save_command(prompt):
            state["last_save"] = now
            # Reset the size baseline too, so the growth rule measures from this save.
            typed_tokens = session_tokens(payload.get("transcript_path"))
            if isinstance(typed_tokens, int):
                state["tokens_at_last_save"] = typed_tokens
                # The one-time 600,000 crossing stays SPENT while the session is
                # still that big. Clearing it on every save would re-arm the alarm that
                # had just asked for that save, and the end of the same turn would fire it
                # again.
                #
                # Only a session that has SHRUNK back under the line can cross it
                # afresh, which a compaction really does.
                state["forced_at_size"] = typed_tokens >= FORCED_SAVE_TOKENS
            # When the count cannot be read, forced_at_size is left exactly as it
            # was. Guessing False here is the same bug with an extra step, and
            # this is the branch a prompt with no transcript path takes.
        write_state(path, state)
        return 0

    last = state.get("last_active")
    gap = max(0.0, now - float(last)) if isinstance(last, (int, float)) else 0.0

    # sticky: once expired, every later prompt in this session is refused too
    if state.get("expired") or gap >= EXPIRED_SECONDS:
        state["expired"] = True
        state["last_active"] = now
        write_state(path, state)
        shown = gap if gap >= EXPIRED_SECONDS else float(EXPIRED_SECONDS)
        if mode != "local":
            # Refused here, in the hook, because any answer from Claude would
            # already pay the cold re-send this band exists to avoid. Claude Code
            # hooks reference, UserPromptSubmit: "block" "prevents the prompt from
            # being processed and erases it from context", and `reason` is "Shown
            # to the user when decision is block. Not added to context."
            print(json.dumps({"decision": "block", "reason": expired_message(shown)}))
            return 0
        print(expired_message(shown), file=sys.stderr)
        return 2                               # blocks the prompt; stderr goes to the user

    state["last_active"] = now
    write_state(path, state)

    # Never force a close where the user may be remote: a close tears down
    # background agents a long run is waiting on.
    if gap >= AUTOCLOSE_SECONDS and mode == "local":
        print(json.dumps({
            "hookSpecificOutput": {
                "hookEventName": "UserPromptSubmit",   # dropped silently without this
                "additionalContext": autoclose_context(gap),
            }
        }))
    return 0


def main() -> int:
    if os.environ.get("CLAUDE_IDLE_GUARD_OFF") == "1":
        return 0
    try:
        payload = json.load(sys.stdin)
    except Exception:
        return 0

    now = time.time()
    event = payload.get("hook_event_name") or ""

    if event == "UserPromptSubmit":
        rc = handle_prompt(payload, now)
        prune(now)
        return rc

    # Stop / SubagentStop / anything else: the turn just ended, so the idle
    # clock starts here. Measuring from the last PROMPT instead would count a
    # 40-minute autonomous run as idle time.
    rc = handle_stop(payload, now)
    prune(now)
    return rc


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:          # fail OPEN, loudly: never wedge the session
        print("session-idle-guard: internal error, failing open: %s" % e, file=sys.stderr)
        sys.exit(0)
