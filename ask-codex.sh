#!/usr/bin/env bash
# Send a prompt to Codex CLI, append both the prompt and response to a topic transcript.
# Usage: ask-codex.sh <topic> <prompt> [asker_role]
#   asker_role defaults to "claude"; pass "costa" when running directly.

set -euo pipefail

TOPIC="${1:?usage: ask-codex.sh <topic> <prompt> [asker_role]}"
PROMPT="${2:?usage: ask-codex.sh <topic> <prompt> [asker_role]}"
ASKER="${3:-claude}"

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ROOM_DIR="${TEAM_ROOM_DIR:-$SCRIPT_DIR/.team-room}"
mkdir -p "$ROOM_DIR"
TRANSCRIPT="$ROOM_DIR/$TOPIC.jsonl"

append() {
  python3 -c '
import json, sys, datetime
print(json.dumps({
    "ts": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    "role": sys.argv[1],
    "model": sys.argv[2],
    "content": sys.argv[3],
}))
' "$1" "$2" "$3" >> "$TRANSCRIPT"
}

asker_model() {
  case "$1" in
    claude) echo "claude-opus-4-7" ;;
    costa)  echo "human" ;;
    *)      echo "$1" ;;
  esac
}

append "$ASKER" "$(asker_model "$ASKER")" "$PROMPT"

# When stdin is piped (not a TTY), `codex exec` emits just the response on stdout.
# stderr carries the diagnostic banner, MCP auth noise, and skill warnings — drop it.
# Default to high reasoning effort: Costa is on Codex Pro and we use this wrapper
# for design critique, not lookups. Override via CODEX_REASONING_EFFORT=medium etc.
EFFORT="${CODEX_REASONING_EFFORT:-high}"
RESPONSE="$(printf '%s' "$PROMPT" | codex exec -c "model_reasoning_effort=$EFFORT" 2>/dev/null)"

# Trim trailing blank lines
RESPONSE="$(printf '%s' "$RESPONSE" | awk 'NF {p=1} p {print}' | sed -e :a -e '/^$/{$d;N;ba' -e '}')"

append "codex" "gpt-5.5" "$RESPONSE"
printf '%s\n' "$RESPONSE"
