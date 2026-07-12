---
model: sonnet
name: project-status
description: Cold-start orientation for a project. Gathers git state, open PRs against main, Render deploy health, local Docker container status, OpenSpec change progress, unresolved spec-review Blockers, and pending items from project memory — then synthesizes a "what's the state of this project right now" report. Use when sitting back down on a project after time away ("where was I", "catch me up", "what's the state", "status check"). Read-only, never mutates git, gh, Render, Docker, or project files.
---

# Project status

Cold-start orientation skill. Run when you sit down on a project after being away and want a quick read on what's live, what's in flight, what's stale, and what needs your attention before you start coding.

This is a **read-only** skill. No commits, no merges, no deploys, no file writes. Just inspection + synthesis.

## Step 1: Detect project context

Determine which project this is. Order:
1. If cwd is inside a git repo: project = repo basename. `REPO_ROOT=$(git rev-parse --show-toplevel)`.
2. If cwd is inside `~/.claude/projects/<X>/`: project = `<X>`. No repo unless one is linked.
3. Otherwise: bail with "Run from a project directory (git repo or ~/.claude/projects/<X>/)."

Locate the project's CLAUDE.md (in priority order):
1. Repo-root `CLAUDE.md`
2. `~/.claude/projects/<project>/CLAUDE.md`
3. `~/.claude/projects/<other-naming-variant>/CLAUDE.md` (a prefixed or dash-encoded variant of the project name)

State the detected project + CLAUDE.md path in the first line of the report.

## Step 2: Gather data (run in parallel where possible)

### 2a. Git state (always)
```bash
git rev-parse --abbrev-ref HEAD          # current branch
git status --porcelain | wc -l           # dirty file count
git log -1 --format='%h %s (%cr)'        # last commit, age
git rev-list --left-right --count HEAD...main 2>/dev/null  # ahead/behind main
```

### 2b. Open PRs against main (if gh CLI authed)
```bash
gh pr list --base main --state open --json number,title,headRefName,isDraft,createdAt,mergeable 2>/dev/null
```
For each PR, compute age in days. Flag PRs older than 14 days as stale.

### 2c. Render deploy status (if a Render service ID is found)
Extract `srv-...` ID from project CLAUDE.md OR `render.yaml`:
```bash
grep -hE 'srv-[a-z0-9]+' CLAUDE.md render.yaml 2>/dev/null | head -3
```
If found, query the Render API:
```bash
TOKEN=$(python3 -c "import yaml; print(yaml.safe_load(open('$HOME/.render/cli.yaml'))['api']['key'])" 2>/dev/null)
curl -s -H "Authorization: Bearer $TOKEN" \
  "https://api.render.com/v1/services/$SRV_ID/deploys?limit=1" \
  | python3 -c "import json,sys; d=json.load(sys.stdin); print(d)" 2>/dev/null
```
Report: status (live/build_failed/etc.), timestamp of last deploy, commit hash deployed.

Note: per `reference_render_api_gotchas.md`, Render deploy GET responses contain raw `\n` control chars — use `json.loads(s, strict=False)` if parsing in Python rather than the Bash one-liner above. The Bash approach uses `python3 -c "import json,sys"` which defaults to strict, so add `strict=False` if it errors.

### 2d. Local Docker (if compose file present in repo root)
```bash
[ -f docker-compose.yml ] && docker compose ps --status running --quiet 2>/dev/null
```
Report whether the project's local container is running. Don't start it — just observe.

### 2e. OpenSpec changes (if openspec/ dir present)
```bash
ls openspec/changes/ 2>/dev/null
```
For each open change, count completed vs total tasks in its tasks.md if present:
```bash
grep -c '\[x\]' openspec/changes/<change>/tasks.md
grep -c '\[ \]' openspec/changes/<change>/tasks.md
```

### 2f. Unresolved spec-review Blockers (if COMMENTS.md present)
```bash
[ -f COMMENTS.md ] && grep -c '^## B-' COMMENTS.md       # total Blockers
[ -f COMMENTS.md ] && grep -c '^## B-.*RESOLVED' COMMENTS.md  # resolved ones
```
Unresolved = total − resolved. Any > 0 is a release-blocker.

### 2g. Project memory pending items
Look at the project's memory dir (priority order matches CLAUDE.md detection):
1. `~/.claude/projects/<project>/memory/`
2. `~/.claude/projects/-Users-<username>-<repo-location>-<project>/memory/`
3. `~/.claude/projects/-Users-<username>--claude-projects-<project>/memory/`

Read the project's `MEMORY.md` index. Surface any entries whose hooks contain "Pending", "Parked", "Open:", "awaiting", "TODO" — these are explicit pending-state markers in your memory convention.

### 2h. CLAUDE.md freshness
```bash
stat -f %Sm -t '%Y-%m-%d' CLAUDE.md  # macOS
```
Compute age in days. Flag if > 30 days since last update (per the global "End-of-Conversation Rule" — likely a project that's been worked on without doc updates).

## Step 3: Synthesize the report

Single status block, ordered by urgency:

```
# Project status: <project name>
CLAUDE.md: <path> (last updated <N> days ago)

## 🚨 Watch-outs (only if any exist)
- Unresolved Blockers in COMMENTS.md: <N>
- Stale PRs (>14d open): #<num> "<title>" (<N>d)
- Failed deploy: <timestamp> commit <hash>
- Local Docker not running (compose file present)
- CLAUDE.md not updated in <N> days

## 🔵 In flight
- Branch: <name> (<dirty count> uncommitted, <ahead>/<behind> vs main)
- Open PRs: <N>
  - #<num> "<title>" by <author> (<N>d, <draft|ready>)
- OpenSpec changes: <N>
  - <change-name>: <done>/<total> tasks complete
- Pending items from memory:
  - <hook from MEMORY.md>

## 🟢 Live state
- Render: <service-name> <status> — last deploy <timestamp>, commit <hash>
- Local Docker: <container-name> <status>
- Last commit: <hash> "<message>" (<age>)
```

Omit sections with no content. The headline should immediately convey "is this project healthy / blocked / abandoned."

## Step 4: Recommend next action (one line)

Based on what you found, suggest ONE concrete next step:
- Blockers present → "Resolve Blockers in COMMENTS.md before considering release."
- Stale PR found → "Decide on PR #N — close or revive (open <N>d)."
- Open OpenSpec change with unfinished tasks → "Continue /opsx:apply on <change-name> (<N> tasks remaining)."
- Pending memory item → "Resume <memory hook>."
- Nothing pressing → "Project is quiet — last activity <date>. Pick the next thing from your own backlog."

## Guardrails

- **Read-only.** Never run `git push`, `gh pr merge`, `render deploys create`, `docker compose up`, or any state-mutating command. If you find yourself reaching for one, stop and surface the finding instead.
- **Network calls are best-effort.** If `gh` isn't authed, Render token is missing, or Docker isn't running, skip that section silently and note in the report ("Render check skipped — no token / no service ID found").
- **Don't read large files into context.** For COMMENTS.md / MEMORY.md / tasks.md, use grep / wc / head to get counts and surface, not the full content.
- **Cap runtime.** Whole skill should finish in under ~15 seconds. If a network call (gh, render) hangs, kill it with a `timeout 5` wrapper and report "check timed out."
- **Respect the dual-viewport rule trigger.** This skill doesn't edit files, so the PostToolUse hook won't fire — but if your report suggests a UI change as next action, restate the dual-viewport requirement in the recommendation.
