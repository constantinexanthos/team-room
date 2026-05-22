#!/usr/bin/env bash
# Start the team-room v3.
# Usage: start.sh
#
# 1. Builds the React app under web/ (skipped if dist/ is up to date)
# 2. Stages dist/* + helper scripts into .team-room/
# 3. Boots the Python server on $PORT (default 8765)
# 4. Opens the browser to http://localhost:$PORT/
#
# Legacy mode: pass a topic name to skip the React app and open the v2 viewer
#   start.sh <topic>     # opens the legacy viewer.html for that topic

set -euo pipefail

TOPIC="${1:-}"
PORT="${PORT:-8765}"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ROOM_DIR="${TEAM_ROOM_DIR:-$SCRIPT_DIR/.team-room}"
WEB_DIR="$SCRIPT_DIR/web"
DIST_DIR="$WEB_DIR/dist"

mkdir -p "$ROOM_DIR"

# Build the React app if web/ exists and dist is missing or stale.
if [[ -d "$WEB_DIR" && -z "$TOPIC" ]]; then
  if [[ ! -d "$DIST_DIR" ]] || find "$WEB_DIR/src" -newer "$DIST_DIR/index.html" -print -quit 2>/dev/null | grep -q .; then
    echo "Building React app..."
    if [[ ! -d "$WEB_DIR/node_modules" ]]; then
      echo "Installing dependencies (first run only, ~30s)..."
      (cd "$WEB_DIR" && npm install --no-fund --no-audit) >/dev/null
    fi
    (cd "$WEB_DIR" && npm run build) >/dev/null
    echo "Build complete."
  fi
fi

# Stage server + helper scripts into ROOM_DIR.
cp "$SCRIPT_DIR/server.py" "$ROOM_DIR/server.py"

# Stage the React app (overrides legacy viewer.html as the default served page).
if [[ -d "$DIST_DIR" ]]; then
  cp -R "$DIST_DIR/"* "$ROOM_DIR/"
fi

# Keep legacy v2 viewer + index available as fallback at /legacy/*
if [[ -f "$SCRIPT_DIR/viewer.html" ]]; then
  cp "$SCRIPT_DIR/viewer.html" "$ROOM_DIR/legacy-viewer.html"
fi

if [[ -n "$TOPIC" ]]; then
  touch "$ROOM_DIR/$TOPIC.jsonl"
  URL="http://localhost:$PORT/legacy-viewer.html?topic=$TOPIC"
else
  URL="http://localhost:$PORT/"
fi

echo "Team room: $URL"
echo "Transcripts: $ROOM_DIR/"
echo "Ctrl-C to stop."
echo

( sleep 0.5 && open "$URL" 2>/dev/null || true ) &

exec python3 "$ROOM_DIR/server.py" "$PORT"
