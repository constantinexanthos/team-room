#!/usr/bin/env bash
# Send a prompt to Claude (`claude --print`), append both prompt and response
# to a topic transcript. Two modes:
#
# Mode A — Legacy CLI driver (matches ask-codex.sh v1):
#   ask-claude.sh <topic> <prompt> [asker_role]
#
# Mode B — Orchestrator (called by orchestrate.py):
#   ask-claude.sh --orchestrate --topic <t> --prompt-id <id> --round <1|2> --cwd <workspace> < <prompt-via-stdin>
#
# In Mode B, the script:
#   - Reads the full prompt from stdin (multi-KB transcripts OK)
#   - Invokes `claude --print --disallowedTools "Write Edit Bash NotebookEdit"` in --cwd
#   - Appends ONLY the response to <topic>.jsonl with `round` and `prompt_id` set
#   - Does NOT log the prompt (orchestrator already has it in JSONL)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ROOM_DIR="${TEAM_ROOM_DIR:-$SCRIPT_DIR/.team-room}"
APPENDER="$SCRIPT_DIR/_append-jsonl.py"

asker_model() {
  case "$1" in
    claude) echo "claude-opus-4-7" ;;
    costa)  echo "human" ;;
    *)      echo "$1" ;;
  esac
}

# ---------- Mode B (orchestrator) ----------
if [[ "${1:-}" == "--orchestrate" ]]; then
  shift
  TOPIC=""
  PROMPT_ID=""
  ROUND=""
  CWD=""
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --topic)     TOPIC="$2";     shift 2 ;;
      --prompt-id) PROMPT_ID="$2"; shift 2 ;;
      --round)     ROUND="$2";     shift 2 ;;
      --cwd)       CWD="$2";       shift 2 ;;
      *) echo "unknown arg: $1" >&2; exit 2 ;;
    esac
  done
  : "${TOPIC:?--topic required}"
  : "${PROMPT_ID:?--prompt-id required}"
  : "${ROUND:?--round required}"
  : "${CWD:?--cwd required}"
  [[ -d "$CWD" ]] || { echo "cwd does not exist: $CWD" >&2; exit 2; }

  mkdir -p "$ROOM_DIR"
  TRANSCRIPT="$ROOM_DIR/$TOPIC.jsonl"
  PROMPT="$(cat)"

  RESPONSE="$(printf '%s' "$PROMPT" | (cd "$CWD" && claude --print --disallowedTools "Write Edit Bash NotebookEdit" 2>/dev/null))"
  RESPONSE="$(printf '%s' "$RESPONSE" | awk 'NF {p=1} p {print}' | sed -e :a -e '/^$/{$d;N;ba' -e '}')"

  if [[ -z "$RESPONSE" ]]; then
    echo "claude returned empty response" >&2
    exit 1
  fi

  python3 "$APPENDER" "$TRANSCRIPT" "claude" "claude-opus-4-7" "$RESPONSE" --round "$ROUND" --prompt-id "$PROMPT_ID"
  printf '%s\n' "$RESPONSE"
  exit 0
fi

# ---------- Mode A (legacy positional) ----------
TOPIC="${1:?usage: ask-claude.sh <topic> <prompt> [asker_role]   OR   ask-claude.sh --orchestrate ...}"
PROMPT="${2:?usage: ask-claude.sh <topic> <prompt> [asker_role]   OR   ask-claude.sh --orchestrate ...}"
ASKER="${3:-claude}"

mkdir -p "$ROOM_DIR"
TRANSCRIPT="$ROOM_DIR/$TOPIC.jsonl"

python3 "$APPENDER" "$TRANSCRIPT" "$ASKER" "$(asker_model "$ASKER")" "$PROMPT"

# In Mode A, run from the team-room repo so we don't inherit foreign CLAUDE.md.
RESPONSE="$(printf '%s' "$PROMPT" | (cd "$SCRIPT_DIR" && claude --print 2>/dev/null))"
RESPONSE="$(printf '%s' "$RESPONSE" | awk 'NF {p=1} p {print}' | sed -e :a -e '/^$/{$d;N;ba' -e '}')"

if [[ -z "$RESPONSE" ]]; then
  echo "claude returned empty response" >&2
  exit 1
fi

python3 "$APPENDER" "$TRANSCRIPT" "claude" "claude-opus-4-7" "$RESPONSE"
printf '%s\n' "$RESPONSE"
