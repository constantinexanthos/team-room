#!/usr/bin/env bash
# Send a prompt to Codex (`codex exec`), append both prompt and response
# to a topic transcript. Two modes:
#
# Mode A — Legacy CLI driver (v1):
#   ask-codex.sh <topic> <prompt> [asker_role]
#
# Mode B — Orchestrator (called by orchestrate.py):
#   ask-codex.sh --orchestrate --topic <t> --prompt-id <id> --round <1|2> --cwd <workspace> < <prompt-via-stdin>
#
# In Mode B, the script:
#   - Reads the full prompt from stdin (multi-KB transcripts OK)
#   - Invokes `codex exec --sandbox read-only -c model_reasoning_effort=high` in --cwd
#   - Appends ONLY the response to <topic>.jsonl with `round` and `prompt_id` set
#   - Does NOT log the prompt (orchestrator already has it in JSONL)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ROOM_DIR="${TEAM_ROOM_DIR:-$SCRIPT_DIR/.team-room}"
APPENDER="$SCRIPT_DIR/_append-jsonl.py"
EFFORT="${CODEX_REASONING_EFFORT:-high}"

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

  STDERR_FILE="$(mktemp -t ask-codex-stderr.XXXXXX)"
  trap 'rm -f "$STDERR_FILE"' EXIT
  # set +e: pipefail would kill the script before we reach the error reporting.
  set +e
  RESPONSE="$(printf '%s' "$PROMPT" | (cd "$CWD" && codex exec --sandbox read-only --skip-git-repo-check -c "model_reasoning_effort=$EFFORT" 2>"$STDERR_FILE"))"
  CODEX_EXIT=$?
  set -e
  RESPONSE="$(printf '%s' "$RESPONSE" | awk 'NF {p=1} p {print}' | sed -e :a -e '/^$/{$d;N;ba' -e '}')"

  if [[ $CODEX_EXIT -ne 0 ]]; then
    echo "codex exec exited $CODEX_EXIT" >&2
    echo "--- codex stderr ---" >&2
    head -c 4000 "$STDERR_FILE" >&2 || true
    echo >&2
    exit 1
  fi
  if [[ -z "$RESPONSE" ]]; then
    echo "codex returned empty response (exit 0)" >&2
    if [[ -s "$STDERR_FILE" ]]; then
      echo "--- codex stderr ---" >&2
      head -c 4000 "$STDERR_FILE" >&2 || true
      echo >&2
    fi
    exit 1
  fi

  python3 "$APPENDER" "$TRANSCRIPT" "codex" "gpt-5.5" "$RESPONSE" --round "$ROUND" --prompt-id "$PROMPT_ID"
  printf '%s\n' "$RESPONSE"
  exit 0
fi

# ---------- Mode A (legacy positional) ----------
TOPIC="${1:?usage: ask-codex.sh <topic> <prompt> [asker_role]   OR   ask-codex.sh --orchestrate ...}"
PROMPT="${2:?usage: ask-codex.sh <topic> <prompt> [asker_role]   OR   ask-codex.sh --orchestrate ...}"
ASKER="${3:-claude}"

mkdir -p "$ROOM_DIR"
TRANSCRIPT="$ROOM_DIR/$TOPIC.jsonl"

python3 "$APPENDER" "$TRANSCRIPT" "$ASKER" "$(asker_model "$ASKER")" "$PROMPT"

RESPONSE="$(printf '%s' "$PROMPT" | codex exec -c "model_reasoning_effort=$EFFORT" 2>/dev/null)"
RESPONSE="$(printf '%s' "$RESPONSE" | awk 'NF {p=1} p {print}' | sed -e :a -e '/^$/{$d;N;ba' -e '}')"

if [[ -z "$RESPONSE" ]]; then
  echo "codex returned empty response" >&2
  exit 1
fi

python3 "$APPENDER" "$TRANSCRIPT" "codex" "gpt-5.5" "$RESPONSE"
printf '%s\n' "$RESPONSE"
