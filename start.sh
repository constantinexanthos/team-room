#!/usr/bin/env bash
# Start the team-room viewer.
# Usage: start.sh [topic]
#   With no argument: opens the topic-picker index (recommended).
#   With a topic:     jumps straight into that topic's viewer.
#
# Spins up a tiny static file server at .team-room/ (next to this script),
# opens the viewer in your browser. Ctrl-C to stop.

set -euo pipefail

TOPIC="${1:-}"
PORT="${PORT:-8765}"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ROOM_DIR="${TEAM_ROOM_DIR:-$SCRIPT_DIR/.team-room}"

mkdir -p "$ROOM_DIR"
cp "$SCRIPT_DIR/viewer.html" "$ROOM_DIR/viewer.html"
cp "$SCRIPT_DIR/index.html"  "$ROOM_DIR/index.html"
cp "$SCRIPT_DIR/server.py"   "$ROOM_DIR/server.py"

if [[ -n "$TOPIC" ]]; then
  touch "$ROOM_DIR/$TOPIC.jsonl"
  URL="http://localhost:$PORT/viewer.html?topic=$TOPIC"
else
  URL="http://localhost:$PORT/"
fi

echo "Team room: $URL"
echo "Transcripts: $ROOM_DIR/"
echo "Ctrl-C to stop."
echo

( sleep 0.5 && open "$URL" 2>/dev/null || true ) &

exec python3 "$ROOM_DIR/server.py" "$PORT"
