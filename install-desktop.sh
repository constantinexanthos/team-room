#!/usr/bin/env bash
# Drop a "Team Room" launcher on your Desktop.
# Double-click it any time to open the topic picker in your browser.
#
# Run once: ./scripts/team-room/install-desktop.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
SOURCE="$SCRIPT_DIR/Team Room.command"
TARGET="$HOME/Desktop/Team Room.command"

if [[ ! -f "$SOURCE" ]]; then
  echo "error: $SOURCE not found" >&2
  exit 1
fi

chmod +x "$SOURCE"

if [[ -e "$TARGET" || -L "$TARGET" ]]; then
  echo "Replacing existing $TARGET"
  rm -f "$TARGET"
fi

ln -s "$SOURCE" "$TARGET"
echo "Installed: $TARGET"
echo "Double-click it to open the team room."
