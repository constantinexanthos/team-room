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
#   - Invokes `claude --print --output-format stream-json --include-partial-messages`
#     so token-level deltas can be teed to a sidecar `<topic>.partial.<prompt_id>.<round>.txt`
#     file for the UI to poll. Final assembled response is read from the trailing
#     `{"type":"result",...}` event (or assembled from text_deltas as a fallback).
#   - Appends ONLY the final response to <topic>.jsonl with `round` and `prompt_id` set
#   - Does NOT log the prompt (orchestrator already has it in JSONL)
#   - Deletes the partial sidecar file on completion / failure

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
  PARTIAL_FILE="$ROOM_DIR/$TOPIC.partial.$PROMPT_ID.$ROUND.txt"
  RESPONSE_FILE="$(mktemp -t ask-claude-resp.XXXXXX)"
  STDERR_FILE="$(mktemp -t ask-claude-stderr.XXXXXX)"
  PROMPT="$(cat)"

  # Ensure we always tidy up temp + partial sidecar files, even on early exit.
  cleanup_partial() {
    rm -f "$PARTIAL_FILE" "$RESPONSE_FILE" "$STDERR_FILE" 2>/dev/null || true
  }
  trap cleanup_partial EXIT

  # Reset partial file (in case a previous attempt left a stale one).
  : > "$PARTIAL_FILE"

  # Stream-JSON consumer: each line of claude's stream-json output is parsed
  # by python3, which appends text_delta tokens to the partial file as they
  # arrive. The final response is written to RESPONSE_FILE. This keeps the
  # bash side simple and avoids running awk/jq for every token.
  export TEAM_ROOM_PARTIAL_FILE="$PARTIAL_FILE"
  export TEAM_ROOM_RESPONSE_FILE="$RESPONSE_FILE"
  set +e
  printf '%s' "$PROMPT" \
    | (cd "$CWD" && claude --print \
        --output-format stream-json \
        --include-partial-messages \
        --verbose \
        --disallowedTools "Write Edit Bash NotebookEdit" \
        2>"$STDERR_FILE") \
    | python3 -u -c '
import json, os, sys

partial_path = os.environ["TEAM_ROOM_PARTIAL_FILE"]
response_path = os.environ["TEAM_ROOM_RESPONSE_FILE"]

# Open partial file in append mode (created empty by the bash caller).
parts = []
final_result = None

with open(partial_path, "a", buffering=1, encoding="utf-8") as partial_fh:
    for raw in sys.stdin:
        raw = raw.strip()
        if not raw:
            continue
        try:
            obj = json.loads(raw)
        except json.JSONDecodeError:
            continue
        t = obj.get("type")
        if t == "stream_event":
            ev = obj.get("event") or {}
            if ev.get("type") == "content_block_delta":
                delta = ev.get("delta") or {}
                if delta.get("type") == "text_delta":
                    chunk = delta.get("text") or ""
                    if chunk:
                        parts.append(chunk)
                        partial_fh.write(chunk)
                        partial_fh.flush()
                        try:
                            os.fsync(partial_fh.fileno())
                        except OSError:
                            pass
        elif t == "result":
            final_result = obj.get("result")

# Prefer the canonical `result.result` text (already-trimmed); fall back to
# the assembled text_deltas if for some reason the result event was missing.
text = final_result if isinstance(final_result, str) and final_result else "".join(parts)
with open(response_path, "w", encoding="utf-8") as fh:
    fh.write(text)
'
  # PIPESTATUS reflects [claude_exit, python_exit] when set +e and pipefail-off.
  # Either failing should be treated as an error. Snapshot the whole array
  # into a local array so we don't re-read PIPESTATUS twice (which under
  # `set -u` after a prior expansion can read as unbound).
  PIPE_STATUSES=("${PIPESTATUS[@]}")
  CLAUDE_EXIT="${PIPE_STATUSES[0]:-1}"
  PARSER_EXIT="${PIPE_STATUSES[1]:-1}"
  set -e

  if [[ "$CLAUDE_EXIT" -ne 0 ]]; then
    echo "claude --print exited $CLAUDE_EXIT" >&2
    echo "--- claude stderr ---" >&2
    head -c 4000 "$STDERR_FILE" >&2 || true
    echo >&2
    exit 1
  fi
  if [[ "$PARSER_EXIT" -ne 0 ]]; then
    echo "stream-json parser exited $PARSER_EXIT" >&2
    exit 1
  fi

  RESPONSE="$(cat "$RESPONSE_FILE")"
  RESPONSE="$(printf '%s' "$RESPONSE" | awk 'NF {p=1} p {print}' | sed -e :a -e '/^$/{$d;N;ba' -e '}')"

  if [[ -z "$RESPONSE" ]]; then
    echo "claude returned empty response (exit 0)" >&2
    if [[ -s "$STDERR_FILE" ]]; then
      echo "--- claude stderr ---" >&2
      head -c 4000 "$STDERR_FILE" >&2 || true
      echo >&2
    fi
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
