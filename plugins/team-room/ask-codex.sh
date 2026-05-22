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
#   - Invokes `codex exec --sandbox read-only --json -c model_reasoning_effort=high`
#     so we can drop the final agent_message into a sidecar partial file. Codex's
#     --json output does NOT stream individual tokens — it emits a single
#     `item.completed` event with the full agent_message at the END of the turn.
#     So the streaming UX win for codex is marginal (the partial file lands a
#     fraction of a second before the JSONL append), but it keeps the per-turn
#     partial-file protocol symmetric with claude.
#   - Appends ONLY the response to <topic>.jsonl with `round` and `prompt_id` set
#   - Does NOT log the prompt (orchestrator already has it in JSONL)
#   - Deletes the partial sidecar file on completion / failure

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
  PARTIAL_FILE="$ROOM_DIR/$TOPIC.partial.$PROMPT_ID.$ROUND.txt"
  RESPONSE_FILE="$(mktemp -t ask-codex-resp.XXXXXX)"
  STDERR_FILE="$(mktemp -t ask-codex-stderr.XXXXXX)"
  PROMPT="$(cat)"

  cleanup_partial() {
    rm -f "$PARTIAL_FILE" "$RESPONSE_FILE" "$STDERR_FILE" 2>/dev/null || true
  }
  trap cleanup_partial EXIT

  # Reset partial file (in case a previous attempt left a stale one).
  : > "$PARTIAL_FILE"

  # Use `--json` so we can read agent_message items as they complete. Codex
  # batches the message at the end (no incremental token deltas), so the
  # partial file gets populated in one write near completion — but at least
  # the protocol is symmetric with claude.
  export TEAM_ROOM_PARTIAL_FILE="$PARTIAL_FILE"
  export TEAM_ROOM_RESPONSE_FILE="$RESPONSE_FILE"
  set +e
  printf '%s' "$PROMPT" \
    | (cd "$CWD" && codex exec --sandbox read-only --skip-git-repo-check --json \
        -c "model_reasoning_effort=$EFFORT" 2>"$STDERR_FILE") \
    | python3 -u -c '
import json, os, sys

partial_path = os.environ["TEAM_ROOM_PARTIAL_FILE"]
response_path = os.environ["TEAM_ROOM_RESPONSE_FILE"]

# Track the final agent_message text (codex emits one or more `item.completed`
# events; we keep the last agent_message one, matching codex exec text output).
final_text = ""

with open(partial_path, "a", buffering=1, encoding="utf-8") as partial_fh:
    for raw in sys.stdin:
        raw = raw.strip()
        if not raw:
            continue
        try:
            obj = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if obj.get("type") == "item.completed":
            item = obj.get("item") or {}
            if item.get("type") == "agent_message":
                text = item.get("text") or ""
                if text:
                    final_text = text
                    # Truncate + rewrite (codex sends the full message at once,
                    # so this populates the partial file with the final text in
                    # a single write near the end of the turn).
                    partial_fh.seek(0)
                    partial_fh.truncate()
                    partial_fh.write(text)
                    partial_fh.flush()
                    try:
                        os.fsync(partial_fh.fileno())
                    except OSError:
                        pass

with open(response_path, "w", encoding="utf-8") as fh:
    fh.write(final_text)
'
  PIPE_STATUSES=("${PIPESTATUS[@]}")
  CODEX_EXIT="${PIPE_STATUSES[0]:-1}"
  PARSER_EXIT="${PIPE_STATUSES[1]:-1}"
  set -e

  if [[ $CODEX_EXIT -ne 0 ]]; then
    echo "codex exec exited $CODEX_EXIT" >&2
    echo "--- codex stderr ---" >&2
    head -c 4000 "$STDERR_FILE" >&2 || true
    echo >&2
    exit 1
  fi
  if [[ $PARSER_EXIT -ne 0 ]]; then
    echo "codex stream-json parser exited $PARSER_EXIT" >&2
    exit 1
  fi

  RESPONSE="$(cat "$RESPONSE_FILE")"
  RESPONSE="$(printf '%s' "$RESPONSE" | awk 'NF {p=1} p {print}' | sed -e :a -e '/^$/{$d;N;ba' -e '}')"

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
