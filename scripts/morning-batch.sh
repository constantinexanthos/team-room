#!/usr/bin/env bash
# Overnight queue processor: drop questions in queue.md before bed, wake up
# to deliberations recorded in the team-room.
#
# Queue format (one question per markdown bullet):
#   - [ ] Should I prioritize policy or launch?
#   - [ ] [vigil] How should the migration handle in-flight transactions?
#   - [x] (already-processed entries get an x; we skip them)
#
# Optional project prefix in brackets selects which project to log against.
# Defaults to TEAM_ROOM_PROJECT env or the most-recently-opened project.
#
# Topic for the iteration is auto-derived: `morning-YYYYMMDD-NNN` where NNN
# is the queue position. One topic per question keeps transcripts clean.
#
# Run via cron every 15 minutes overnight:
#   */15 0-7 * * *  /Users/costaxanthos/team-room/scripts/morning-batch.sh >> /tmp/morning-batch.log 2>&1
#
# Or one-shot from the command line to drain the queue immediately.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
QUEUE_FILE="${TEAM_ROOM_QUEUE:-$HOME/team-room-queue.md}"
URL="${TEAM_ROOM_URL:-http://localhost:8765}"
LOG_FILE="${TEAM_ROOM_BATCH_LOG:-$HOME/team-room-morning-batch.log}"
DEFAULT_PROJECT="${TEAM_ROOM_PROJECT:-}"

log() { printf '[%s] %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$*" | tee -a "$LOG_FILE" >&2; }

# Server up?
if ! curl -sS --max-time 3 -o /dev/null "$URL/projects"; then
  log "team-room server not reachable at $URL; skipping batch."
  exit 0
fi

# Resolve default project if not set: most-recently-opened
if [[ -z "$DEFAULT_PROJECT" ]]; then
  DEFAULT_PROJECT="$(curl -sS "$URL/recents" 2>/dev/null | python3 -c '
import json, sys
try:
    arr = json.load(sys.stdin)
    if arr: print(arr[0]["id"])
except Exception:
    pass
')"
fi
if [[ -z "$DEFAULT_PROJECT" ]]; then
  log "no project specified and no recents available; create one first or set TEAM_ROOM_PROJECT."
  exit 0
fi
log "default project: $DEFAULT_PROJECT"

# Create the queue file if missing so users see where to drop questions.
if [[ ! -f "$QUEUE_FILE" ]]; then
  mkdir -p "$(dirname "$QUEUE_FILE")"
  cat > "$QUEUE_FILE" <<EOF
# Team-room overnight queue

Drop questions here before bed (one per markdown bullet). The morning-batch
processor will run them through the team room while you sleep.

Mark with \`- [ ]\` for pending, \`- [x]\` for done. Optional \`[project-id]\`
prefix selects which project to log against (defaults to most-recently-opened).

Examples:
  - [ ] Should we ship policy first or launch first?
  - [ ] [vigil] Is the workspace.json schema final?

Pending:

EOF
  log "created queue file at $QUEUE_FILE"
  exit 0
fi

# Find the first unchecked bullet.
PENDING_LINE_NUM="$(grep -n '^[[:space:]]*-[[:space:]]*\[[[:space:]]\][[:space:]]' "$QUEUE_FILE" | head -1 | cut -d: -f1 || true)"
if [[ -z "$PENDING_LINE_NUM" ]]; then
  log "queue empty; nothing to process."
  exit 0
fi

PENDING_LINE="$(sed -n "${PENDING_LINE_NUM}p" "$QUEUE_FILE")"
# Strip the bullet + checkbox to get the question text.
RAW_TEXT="$(printf '%s' "$PENDING_LINE" | sed -E 's/^[[:space:]]*-[[:space:]]*\[[[:space:]]\][[:space:]]*//')"

# Optional [project-id] prefix.
PROJECT="$DEFAULT_PROJECT"
QUESTION="$RAW_TEXT"
if [[ "$RAW_TEXT" =~ ^\[([a-z0-9-]+)\][[:space:]]*(.+)$ ]]; then
  PROJECT="${BASH_REMATCH[1]}"
  QUESTION="${BASH_REMATCH[2]}"
fi

if [[ -z "$QUESTION" ]]; then
  log "skipping empty question on line $PENDING_LINE_NUM"
  exit 0
fi

# Derive topic: morning-YYYYMMDD-LLLL where LLLL is the line number.
DATESTAMP="$(date +%Y%m%d)"
TOPIC="morning-${DATESTAMP}-$(printf '%04d' "$PENDING_LINE_NUM")"

log "processing line $PENDING_LINE_NUM: project=$PROJECT topic=$TOPIC q=${QUESTION:0:80}"

# Run the iteration (uses dialogue mode by default per server.py).
OUTPUT="$("$REPO_ROOT/scripts/ask-team-room.sh" --project "$PROJECT" "$TOPIC" "$QUESTION" 2>&1)" || {
  log "FAILED to process line $PENDING_LINE_NUM (exit $?); leaving it pending."
  log "$OUTPUT" | head -20
  exit 1
}

log "iteration complete; transcript: $URL/?topic=$TOPIC (project $PROJECT)"

# Mark the line done in-place (atomic via temp + mv).
TMP_QUEUE="$(mktemp)"
awk -v line="$PENDING_LINE_NUM" '
NR == line {
  sub(/\[[[:space:]]\]/, "[x]")
  print $0 "  <!-- topic=" TOPIC " · " strftime("%Y-%m-%d %H:%M") " -->"
  next
}
{ print }
' TOPIC="$TOPIC" "$QUEUE_FILE" > "$TMP_QUEUE"
mv "$TMP_QUEUE" "$QUEUE_FILE"

log "marked line $PENDING_LINE_NUM done."
