#!/usr/bin/env bash
# Append an arbitrary message to a team-room transcript.
# Usage: log.sh <topic> <role> <content>
#   Common roles: claude, codex, costa, system
#
# Uses the shared locked-append helper so writes don't interleave with
# concurrent orchestrator / agent writes.

set -euo pipefail

TOPIC="${1:?usage: log.sh <topic> <role> <content>}"
ROLE="${2:?usage: log.sh <topic> <role> <content>}"
CONTENT="${3:?usage: log.sh <topic> <role> <content>}"

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ROOM_DIR="${TEAM_ROOM_DIR:-$SCRIPT_DIR/.team-room}"
APPENDER="$SCRIPT_DIR/_append-jsonl.py"

case "$ROLE" in
  claude) MODEL="claude-opus-4-7" ;;
  codex)  MODEL="gpt-5.5" ;;
  costa)  MODEL="human" ;;
  system) MODEL="system" ;;
  *)      MODEL="$ROLE" ;;
esac

mkdir -p "$ROOM_DIR"
python3 "$APPENDER" "$ROOM_DIR/$TOPIC.jsonl" "$ROLE" "$MODEL" "$CONTENT"
