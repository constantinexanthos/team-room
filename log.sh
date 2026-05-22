#!/usr/bin/env bash
# Append an arbitrary message to a team-room transcript.
# Usage: log.sh <topic> <role> <content>
#   Common roles: claude, codex, costa, system

set -euo pipefail

TOPIC="${1:?usage: log.sh <topic> <role> <content>}"
ROLE="${2:?usage: log.sh <topic> <role> <content>}"
CONTENT="${3:?usage: log.sh <topic> <role> <content>}"

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ROOM_DIR="${TEAM_ROOM_DIR:-$SCRIPT_DIR/.team-room}"
mkdir -p "$ROOM_DIR"

case "$ROLE" in
  claude) MODEL="claude-opus-4-7" ;;
  codex)  MODEL="gpt-5.5" ;;
  costa)  MODEL="human" ;;
  system) MODEL="system" ;;
  *)      MODEL="$ROLE" ;;
esac

python3 -c '
import json, sys, datetime
print(json.dumps({
    "ts": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    "role": sys.argv[1],
    "model": sys.argv[2],
    "content": sys.argv[3],
}))
' "$ROLE" "$MODEL" "$CONTENT" >> "$ROOM_DIR/$TOPIC.jsonl"
