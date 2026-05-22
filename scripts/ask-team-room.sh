#!/usr/bin/env bash
# Programmatic consultant: send a prompt to a team-room topic, wait for the
# Claude+Codex iteration to finish, print all 4 agent responses to stdout.
#
# Designed for use BY OTHER agents (Claude Code in any project, scripts, cron).
# Lets you outsource hard strategic calls to a two-mind deliberation while you
# stay focused on execution.
#
# Usage:
#   ask-team-room.sh <topic_id> "<prompt>"
#   ask-team-room.sh --project <project_id> <topic_id> "<prompt>"
#   ask-team-room.sh --json <topic_id> "<prompt>"   # machine-readable output
#
# Env:
#   TEAM_ROOM_URL    default http://localhost:8765
#   TEAM_ROOM_WAIT   max seconds to wait for the iteration (default 900)
#
# Notes:
#   - If the topic doesn't exist yet, it's auto-created. You'll need to pass
#     --project so we know which project to bind it to. Otherwise the topic
#     must already exist (no auto-creation without explicit project).
#   - If an iteration is in flight, we wait for it to finish, then send ours.
#   - Exit codes: 0 success, 1 error (server unreachable, prompt rejected,
#     iteration crashed, etc.), 2 usage error.

set -euo pipefail

URL="${TEAM_ROOM_URL:-http://localhost:8765}"
WAIT_S="${TEAM_ROOM_WAIT:-900}"
PROJECT=""
JSON_OUT=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --project) PROJECT="$2"; shift 2 ;;
    --json)    JSON_OUT=1;  shift ;;
    --help|-h)
      sed -n '2,/^$/p' "$0" | sed 's/^# \{0,1\}//'
      exit 0
      ;;
    --*) echo "unknown flag: $1" >&2; exit 2 ;;
    *) break ;;
  esac
done

if [[ $# -lt 2 ]]; then
  echo "usage: ask-team-room.sh [--project <id>] [--json] <topic_id> <prompt>" >&2
  exit 2
fi

TOPIC="$1"
PROMPT="$2"

curl_json() {
  curl -sS --fail-with-body "$@"
}

# Sanity: server reachable?
if ! curl -sS --max-time 3 -o /dev/null "$URL/projects"; then
  echo "team-room server not reachable at $URL (start it with: ~/team-room/start.sh)" >&2
  exit 1
fi

# Ensure the topic exists. If --project supplied, create or upsert. Otherwise
# require it to exist already (the server's POST /prompt will 4xx if the JSONL
# is missing — but our path is gentler).
TOPIC_META_URL="$URL/topics"
if [[ -n "$PROJECT" ]]; then
  curl -sS -X POST "$URL/topic" \
    -H 'Content-Type: application/json' \
    -d "$(python3 -c 'import json,sys; print(json.dumps({"name": sys.argv[1], "project_id": sys.argv[2]}))' "$TOPIC" "$PROJECT")" \
    >/dev/null || true
fi

# If an iteration is already in flight on this topic, wait for it.
wait_for_idle() {
  local deadline=$(( $(date +%s) + WAIT_S ))
  while true; do
    local status
    status="$(curl -sS "$URL/status/$TOPIC" | python3 -c 'import json,sys; print(json.load(sys.stdin).get("status","idle"))')"
    if [[ "$status" == "idle" ]]; then
      return 0
    fi
    if [[ "$(date +%s)" -ge $deadline ]]; then
      echo "timed out after ${WAIT_S}s waiting for topic '$TOPIC' to become idle" >&2
      return 1
    fi
    sleep 2
  done
}

wait_for_idle || exit 1

# Send the prompt.
RESP="$(curl -sS -X POST "$URL/prompt" \
  -H 'Content-Type: application/json' \
  -d "$(python3 -c 'import json,sys; print(json.dumps({"topic": sys.argv[1], "content": sys.argv[2]}))' "$TOPIC" "$PROMPT")")"

PROMPT_ID="$(printf '%s' "$RESP" | python3 -c 'import json,sys; d=json.load(sys.stdin); print(d.get("prompt_id") or "")')"
if [[ -z "$PROMPT_ID" ]]; then
  echo "server did not return a prompt_id; response was:" >&2
  echo "$RESP" >&2
  exit 1
fi

# Wait for the iteration to complete.
wait_for_idle || exit 1

# Fetch the transcript and extract just our iteration's messages.
TRANSCRIPT_URL="$URL/${TOPIC}.jsonl?t=$(date +%s)"
TRANSCRIPT="$(curl -sS "$TRANSCRIPT_URL")"

OUTPUT="$(printf '%s' "$TRANSCRIPT" | python3 -c '
import json, sys
pid = sys.argv[1]
json_out = sys.argv[2] == "1"
msgs = []
for line in sys.stdin:
    line = line.strip()
    if not line:
        continue
    try:
        m = json.loads(line)
    except Exception:
        continue
    if m.get("prompt_id") == pid:
        msgs.append(m)

if json_out:
    print(json.dumps({"prompt_id": pid, "messages": msgs}, indent=2))
else:
    if not msgs:
        sys.stderr.write(f"no messages found for prompt_id {pid}\n")
        sys.exit(1)
    for m in msgs:
        role = (m.get("role") or "?").upper()
        rnd = m.get("round")
        tag = f"{role}" + (f" R{rnd}" if rnd else "")
        ts = m.get("ts", "")
        sep = "─" * 70
        print(sep)
        print(f"{tag}  [{ts}]")
        print(sep)
        print(m.get("content", ""))
        print()
' "$PROMPT_ID" "$JSON_OUT")"

printf '%s\n' "$OUTPUT"
