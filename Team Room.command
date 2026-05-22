#!/usr/bin/env bash
# Double-click this file (or its Desktop symlink) to open the team room.
# macOS launches `.command` files in Terminal automatically.
#
# Resolves symlinks so it works whether double-clicked here or from the Desktop.

set -euo pipefail

SOURCE="${BASH_SOURCE[0]}"
while [ -L "$SOURCE" ]; do
  TARGET="$(readlink "$SOURCE")"
  case "$TARGET" in
    /*) SOURCE="$TARGET" ;;
    *)  SOURCE="$(cd -P "$(dirname "$SOURCE")" && pwd)/$TARGET" ;;
  esac
done
SCRIPT_DIR="$(cd -P "$(dirname "$SOURCE")" && pwd)"

exec "$SCRIPT_DIR/start.sh"
