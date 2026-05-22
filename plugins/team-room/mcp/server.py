#!/usr/bin/env python3
"""Team Room MCP server (stdio transport, stdlib only).

Exposes the team-room dialogue capability as MCP tools so any Claude Code
session (or any MCP-aware agent) can call it natively.

Tools:
  team_room_ask    — fire a dialogue and (optionally) wait for the result
  team_room_status — get current iteration state for a topic
  team_room_recent — list recent topics
  team_room_cancel — cancel an in-flight iteration

The server reuses the orchestrator scripts that live next to it in the
plugin install:
  ../orchestrate.py        (the dialogue loop)
  ../ask-claude.sh         (Claude turn helper)
  ../ask-codex.sh          (Codex turn helper)
  ../_append-jsonl.py      (locked JSONL appender)

State lives in ${TEAM_ROOM_DIR}, defaulting to ${HOME}/.team-room/. The plugin
intentionally does NOT depend on an always-on HTTP daemon — it's stdio-only,
launched on demand by Claude Code per the plugin manifest.

Protocol: JSON-RPC 2.0 with LSP-style Content-Length framing on stdin/stdout.
"""

from __future__ import annotations

import datetime
import json
import os
import re
import secrets
import signal
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Paths — resolved at startup
# ---------------------------------------------------------------------------

# Plugin root = parent of mcp/. When installed via /plugin install, this lives
# at ~/.claude/plugins/cache/<marketplace>/team-room/<version>/.
PLUGIN_ROOT = Path(__file__).resolve().parent.parent

# Room dir = where transcripts + state live. Honors $TEAM_ROOM_DIR, falls
# back to ~/.team-room/.
ROOM_DIR = Path(
    os.environ.get("TEAM_ROOM_DIR")
    or os.path.expanduser("~/.team-room")
)

ORCHESTRATE = PLUGIN_ROOT / "orchestrate.py"
ASK_CLAUDE = PLUGIN_ROOT / "ask-claude.sh"
ASK_CODEX = PLUGIN_ROOT / "ask-codex.sh"
APPENDER = PLUGIN_ROOT / "_append-jsonl.py"

TOPIC_NAME_RE = re.compile(r"^[a-z0-9-]{1,64}$")
PROJECT_ID_RE = re.compile(r"^[a-z0-9-]{1,64}$")
STALE_CRASH_SECONDS = 600


def now_iso() -> str:
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def stderr_log(*args: Any) -> None:
    """Server-side logging. stderr is for diagnostics; stdout is the JSON-RPC channel."""
    print("[team-room-mcp]", *args, file=sys.stderr, flush=True)


# ---------------------------------------------------------------------------
# State helpers (shared shape with server.py)
# ---------------------------------------------------------------------------

def state_path(topic: str) -> Path:
    return ROOM_DIR / f"{topic}.state.json"


def jsonl_path(topic: str) -> Path:
    return ROOM_DIR / f"{topic}.jsonl"


def workspace_path(topic: str) -> Path:
    return ROOM_DIR / f"{topic}.workspace.json"


def project_path(project_id: str) -> Path:
    return ROOM_DIR / f"{project_id}.project.json"


def topic_meta_path(topic_id: str) -> Path:
    return ROOM_DIR / f"{topic_id}.topic.json"


def brief_path(topic: str) -> Path:
    return ROOM_DIR / f"{topic}.brief.json"


def read_state(topic: str) -> dict:
    p = state_path(topic)
    if not p.exists():
        return {"status": "idle", "prompt_id": None}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"status": "idle", "prompt_id": None}


def read_brief(topic: str) -> dict | None:
    """Read the v0.2 envelope artifact for a topic, if present.

    The brief is written by the orchestrator at session close and captures
    the structured outcome (converged / forked / timed-out / failed) plus
    the joint read or fork map. None if the brief doesn't exist (older
    transcripts or in-flight sessions)."""
    p = brief_path(topic)
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def read_transcript(topic: str) -> list[dict]:
    p = jsonl_path(topic)
    if not p.exists():
        return []
    out = []
    try:
        for line in p.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    except OSError:
        pass
    return out


def append_costa_message(topic: str, content: str, prompt_id: str) -> None:
    cmd = [
        sys.executable, str(APPENDER), str(jsonl_path(topic)),
        "costa", "human", content,
        "--prompt-id", prompt_id,
    ]
    subprocess.run(cmd, check=True)


def write_initial_state(topic: str, prompt_id: str, orchestrator_pid: int, mode: str) -> None:
    state = {
        "status": "dialogue" if mode == "dialogue" else "round-1",
        "prompt_id": prompt_id,
        "started_at": now_iso(),
        "orchestrator_pid": orchestrator_pid,
        "claude_done": False,
        "codex_done": False,
        "mode": mode,
        "last_error": None,
    }
    if mode == "dialogue":
        state["turn"] = 1
        state["max_turns"] = 8
        state["current_agent"] = "claude"
    p = state_path(topic)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(p.suffix + ".tmp")
    tmp.write_text(json.dumps(state), encoding="utf-8")
    os.replace(tmp, p)


def resolve_project_workspace(project_id: str | None) -> tuple[str, str] | tuple[None, None]:
    """Return (project_id, workspace_path) if the project exists. Otherwise (None, None)."""
    if not project_id:
        return None, None
    if not PROJECT_ID_RE.match(project_id):
        return None, None
    p = project_path(project_id)
    if not p.exists():
        return None, None
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        return project_id, data.get("workspace") or os.path.expanduser("~")
    except (OSError, json.JSONDecodeError):
        return None, None


def ensure_topic(topic_id: str, project_id: str | None, workspace: str | None) -> None:
    """Touch the JSONL + write topic meta + workspace file."""
    ROOM_DIR.mkdir(parents=True, exist_ok=True)
    jsonl_path(topic_id).touch(exist_ok=True)

    # Workspace
    if not workspace_path(topic_id).exists():
        ws = workspace or os.environ.get("HOME") or "/"
        workspace_path(topic_id).write_text(
            json.dumps({"workspace": ws, "created_at": now_iso()}),
            encoding="utf-8",
        )

    # Topic meta
    if project_id and not topic_meta_path(topic_id).exists():
        topic_meta_path(topic_id).write_text(
            json.dumps({"id": topic_id, "project_id": project_id, "created_at": now_iso()}),
            encoding="utf-8",
        )


# ---------------------------------------------------------------------------
# Tool implementations
# ---------------------------------------------------------------------------

def emit_progress(progress_token: Any, progress: float, total: float | None, message: str) -> None:
    """Send a `notifications/progress` JSON-RPC notification to the client.

    Per MCP spec (2025-11-25/basic/utilities/progress):
      - progressToken must match an active request's token
      - progress MUST increase monotonically (we enforce via counter)
      - total is optional
      - message SHOULD be human-readable
      - notifications MUST stop after completion
    No-op if progress_token is None (client didn't request progress)."""
    if progress_token is None:
        return
    params: dict = {
        "progressToken": progress_token,
        "progress": progress,
    }
    if total is not None:
        params["total"] = total
    if message:
        params["message"] = message
    write_message({
        "jsonrpc": "2.0",
        "method": "notifications/progress",
        "params": params,
    })


def _progress_for_dialogue(state: dict) -> tuple[float, float, str]:
    """Map a dialogue-mode state.json snapshot to (progress, total, message).

    Progress is fractional: turn N composing = N - 0.5, turn N done = N.
    This keeps the counter monotonic across the (start-of-turn, end-of-turn)
    transitions and surfaces both 'X is composing' and 'X is done, Y up next'.
    """
    turn = state.get("turn") or 0
    max_turns = state.get("max_turns") or 8
    agent = (state.get("current_agent") or "?").capitalize()
    return (max(0.5, float(turn) - 0.5), float(max_turns),
            f"{agent} composing turn {turn} of {max_turns}")


def _progress_for_rounds(state: dict) -> tuple[float, float, str]:
    status = state.get("status") or ""
    if status == "round-1":
        return 0.5, 2.0, "Round 1: both agents writing first-take in parallel"
    if status == "round-2":
        return 1.5, 2.0, "Round 2: each agent critiquing the other"
    return 0.0, 2.0, f"Status: {status}"


def tool_ask(args: dict, _meta: dict | None = None) -> dict:
    """Fire a dialogue and (optionally) wait for the result.

    When _meta.progressToken is set by the client (per MCP progress spec),
    emits `notifications/progress` notifications as the orchestrator advances
    through turns — solves the 'silent middle' between team_room_ask and
    final_brief that v0.2 dog-fooding flagged as the biggest first-use gap.
    """
    question = args.get("question") or ""
    if not question.strip():
        return {"error": "question is required"}

    progress_token = (_meta or {}).get("progressToken")

    project_id = args.get("project_id")
    explicit_topic = args.get("topic")
    mode = args.get("mode") or "dialogue"
    wait = bool(args.get("wait", True))
    timeout = int(args.get("timeout_s", 600))

    if mode not in ("dialogue", "rounds"):
        return {"error": "mode must be 'dialogue' or 'rounds'"}

    # Resolve project + workspace
    resolved_project, workspace = resolve_project_workspace(project_id)
    if project_id and resolved_project is None:
        return {"error": f"project '{project_id}' does not exist"}

    # Pick / validate topic id
    if explicit_topic:
        if not TOPIC_NAME_RE.match(explicit_topic):
            return {"error": "invalid topic id"}
        topic = explicit_topic
    else:
        # Auto-derive: mcp-YYYYMMDD-HHMMSS-<4hex>
        topic = f"mcp-{datetime.datetime.now().strftime('%Y%m%d-%H%M%S')}-{secrets.token_hex(2)}"

    # Refuse if iteration in flight (no stale-check here for now; can add later)
    state = read_state(topic)
    if state.get("status") not in (None, "idle"):
        return {"error": f"iteration in progress on topic '{topic}'", "status": state.get("status")}

    ensure_topic(topic, resolved_project, workspace)

    prompt_id = secrets.token_hex(4)
    append_costa_message(topic, question, prompt_id)

    # Spawn orchestrate.py detached. We MUST pin TEAM_ROOM_DIR so orchestrate.py
    # and the ask-claude.sh/ask-codex.sh it invokes write to the same dir the
    # MCP server reads from. Their defaults differ (orchestrate.py defaults to
    # $SCRIPT_DIR/.team-room, i.e. the plugin install dir) — without this, the
    # prompt lands in ROOM_DIR while responses land in <plugin>/.team-room/.
    child_env = os.environ.copy()
    child_env["TEAM_ROOM_DIR"] = str(ROOM_DIR)
    log_fh = open(ROOM_DIR / f"{topic}.orchestrate.log", "a", encoding="utf-8")
    try:
        proc = subprocess.Popen(
            [sys.executable, str(ORCHESTRATE),
             "--topic", topic, "--prompt-id", prompt_id, "--mode", mode],
            stdin=subprocess.DEVNULL,
            stdout=log_fh,
            stderr=subprocess.STDOUT,
            start_new_session=True,
            close_fds=True,
            cwd=str(ROOM_DIR),
            env=child_env,
        )
    finally:
        log_fh.close()

    write_initial_state(topic, prompt_id, proc.pid, mode)

    if not wait:
        return {
            "session": {"topic": topic, "prompt_id": prompt_id, "orchestrator_pid": proc.pid},
            "status": "in_flight",
        }

    # Wait for completion (poll state.status -> idle). Emit MCP progress
    # notifications on every state transition if the client requested them,
    # so the silent middle gets a heartbeat (each turn boundary fires a
    # notification with `Codex composing turn 3 of 8` etc.).
    deadline = time.time() + timeout
    last_signature: tuple | None = None
    progress_counter: float = 0.0  # MUST be monotonically increasing per spec
    poll_interval = 0.5 if progress_token is not None else 2.0
    while time.time() < deadline:
        s = read_state(topic)
        if s.get("status") == "idle":
            break
        if progress_token is not None:
            sig = (s.get("status"), s.get("turn"), s.get("current_agent"),
                   s.get("claude_done"), s.get("codex_done"))
            if sig != last_signature:
                last_signature = sig
                if mode == "dialogue":
                    raw_progress, total, message = _progress_for_dialogue(s)
                else:
                    raw_progress, total, message = _progress_for_rounds(s)
                # Enforce monotonic increase even if state regresses (defensive).
                progress_counter = max(progress_counter + 0.01, raw_progress)
                emit_progress(progress_token, progress_counter, total, message)
        time.sleep(poll_interval)
    else:
        if progress_token is not None:
            emit_progress(progress_token, progress_counter + 1.0, None,
                          f"timed out after {timeout}s; orchestrator still running")
        return {
            "session": {"topic": topic, "prompt_id": prompt_id},
            "status": "timeout",
            "warning": f"iteration still running after {timeout}s; poll team_room_status",
        }

    # Final progress emission with the actual outcome so the client knows
    # the room landed (vs. hit its wait-timeout). Spec: notifications MUST
    # stop after completion — this is the last one for this token.
    final_state_for_progress = read_state(topic)
    final_outcome = final_state_for_progress.get("outcome") or "complete"
    if progress_token is not None:
        progress_counter = max(progress_counter + 1.0, float(final_state_for_progress.get("max_turns") or progress_counter))
        emit_progress(progress_token, progress_counter, progress_counter,
                      f"{final_outcome} — brief ready")

    # Pull messages for this iteration only
    messages = [m for m in read_transcript(topic) if m.get("prompt_id") == prompt_id]

    # v0.2 envelope: surface outcome + structured brief as the primary
    # artifact. The transcript is supporting material. Callers should render
    # the brief first; transcript is for inspection.
    final_state = read_state(topic)
    brief = read_brief(topic)
    response: dict = {
        "session": {"topic": topic, "prompt_id": prompt_id},
        "status": "complete",
        "outcome": (brief or {}).get("outcome") or final_state.get("outcome"),
        "messages": messages,
    }
    if brief is not None:
        # Only surface the brief if it matches this iteration's prompt_id
        # — older brief.json files (from a prior run on the same topic)
        # would mislead the caller otherwise.
        if brief.get("prompt_id") == prompt_id:
            response["final_brief"] = brief
        else:
            response["final_brief_note"] = (
                f"brief.json exists but is from a prior iteration "
                f"(prompt_id={brief.get('prompt_id')!r}); ignored"
            )
    return response


def tool_status(args: dict) -> dict:
    topic = args.get("topic") or ""
    if not TOPIC_NAME_RE.match(topic):
        return {"error": "invalid topic id"}
    state = read_state(topic)
    # For completed rooms, attach the structured brief so callers don't need
    # to make a second call to retrieve the artifact.
    if state.get("status") == "idle" and state.get("outcome"):
        brief = read_brief(topic)
        if brief is not None:
            state["final_brief"] = brief
    return state


def tool_recent(args: dict) -> dict:
    limit = int(args.get("limit", 10))
    if not ROOM_DIR.exists():
        return {"topics": []}
    items = []
    for jsonl in ROOM_DIR.glob("*.jsonl"):
        try:
            stat = jsonl.stat()
        except OSError:
            continue
        items.append({"id": jsonl.stem, "mtime": stat.st_mtime})
    items.sort(key=lambda t: t["mtime"], reverse=True)
    return {"topics": items[:limit]}


def tool_cancel(args: dict) -> dict:
    topic = args.get("topic") or ""
    if not TOPIC_NAME_RE.match(topic):
        return {"error": "invalid topic id"}
    state = read_state(topic)
    pid = state.get("orchestrator_pid")
    if not pid:
        return {"error": "no in-flight orchestrator"}
    try:
        os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        return {"warning": "process already exited"}
    except PermissionError as e:
        return {"error": f"could not signal pid {pid}: {e}"}
    return {"status": "cancel signal sent", "pid": pid}


TOOLS = {
    "team_room_ask": {
        "description": (
            "Open a working session: Claude and Codex deliberate on your question "
            "together over multiple short turns, then return a structured artifact. "
            "Use when a strategic call would benefit from cross-model dialogue "
            "(architecture choices, prioritization, design trade-offs, naming). "
            "Every session ends in exactly one legible terminal state: "
            "`converged` (joint read for you), `forked` (explicit unresolved "
            "disagreement with view-mapping), `timed-out` (max turns hit with "
            "partial progress), or `failed`. The response surfaces the "
            "structured `final_brief` as the primary artifact, with the raw "
            "`messages` transcript as supporting material. Render the brief "
            "first; the transcript is for inspection."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "question": {"type": "string", "description": "What to deliberate on. Frame precisely."},
                "project_id": {"type": "string", "description": "Optional project to attach the topic to."},
                "topic": {"type": "string", "description": "Optional explicit topic id (lowercase + hyphens). Auto-derived if omitted."},
                "mode": {"type": "string", "enum": ["dialogue", "rounds"], "description": "dialogue (default) = collaborative working session — Claude and Codex as teammates from different AI labs, framing together, addressing each other by name, mapping forks instead of grading. rounds = opt-in adversarial review mode — each agent answers independently in R1, then critiques the other in R2 with explicit false-claim / missed-risk rubric. Use rounds only when you explicitly want stress-testing rather than collaboration."},
                "wait": {"type": "boolean", "description": "If true (default), wait for the iteration to complete and return the full transcript. If false, return immediately with a session handle to poll."},
                "timeout_s": {"type": "integer", "description": "Max seconds to wait when wait=true. Default 600."},
            },
            "required": ["question"],
        },
    },
    "team_room_status": {
        "description": (
            "Get current iteration state for a topic. While in-flight, returns "
            "live status (dialogue/round-1/round-2 + current_agent + turn). "
            "After completion, returns idle status with `outcome` set and the "
            "`final_brief` artifact attached. Useful for polling wait=false "
            "sessions and for retrieving the brief from a previously-run topic."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {"topic": {"type": "string"}},
            "required": ["topic"],
        },
    },
    "team_room_recent": {
        "description": "List recent topics by last-modified time. Useful to find an existing topic to continue.",
        "inputSchema": {
            "type": "object",
            "properties": {"limit": {"type": "integer", "default": 10}},
        },
    },
    "team_room_cancel": {
        "description": "Cancel an in-flight iteration on a topic. Sends SIGTERM to the orchestrator.",
        "inputSchema": {
            "type": "object",
            "properties": {"topic": {"type": "string"}},
            "required": ["topic"],
        },
    },
}


TOOL_FNS = {
    "team_room_ask": tool_ask,
    "team_room_status": tool_status,
    "team_room_recent": tool_recent,
    "team_room_cancel": tool_cancel,
}


# ---------------------------------------------------------------------------
# JSON-RPC over stdio
# ---------------------------------------------------------------------------

def read_message() -> dict | None:
    """Read one newline-delimited JSON-RPC message from stdin.

    MCP stdio transport (per spec): each message is a single line of UTF-8
    JSON, terminated by '\\n'. No Content-Length headers, no embedded
    newlines, no batches.
    """
    while True:
        line = sys.stdin.buffer.readline()
        if not line:
            return None
        s = line.decode("utf-8", errors="replace").strip()
        if not s:
            continue
        try:
            return json.loads(s)
        except json.JSONDecodeError as e:
            stderr_log(f"ignoring malformed JSON line: {e}")
            continue


def write_message(msg: dict) -> None:
    # Compact (no indent, no embedded newlines) so the message is exactly one line.
    body = json.dumps(msg, separators=(",", ":"), ensure_ascii=False)
    sys.stdout.buffer.write(body.encode("utf-8"))
    sys.stdout.buffer.write(b"\n")
    sys.stdout.buffer.flush()


def jsonrpc_result(req_id: Any, result: Any) -> dict:
    return {"jsonrpc": "2.0", "id": req_id, "result": result}


def jsonrpc_error(req_id: Any, code: int, message: str, data: Any = None) -> dict:
    err = {"code": code, "message": message}
    if data is not None:
        err["data"] = data
    return {"jsonrpc": "2.0", "id": req_id, "error": err}


def handle(msg: dict) -> dict | None:
    method = msg.get("method", "")
    req_id = msg.get("id")
    params = msg.get("params") or {}

    if method == "initialize":
        return jsonrpc_result(req_id, {
            "protocolVersion": "2024-11-05",
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "team-room", "version": "0.1.0"},
        })

    if method == "tools/list":
        tools_array = [
            {"name": name, "description": t["description"], "inputSchema": t["inputSchema"]}
            for name, t in TOOLS.items()
        ]
        return jsonrpc_result(req_id, {"tools": tools_array})

    if method == "tools/call":
        name = params.get("name", "")
        args = params.get("arguments") or {}
        meta = params.get("_meta") or {}
        fn = TOOL_FNS.get(name)
        if not fn:
            return jsonrpc_error(req_id, -32601, f"unknown tool: {name}")
        try:
            # Tools that benefit from progress notifications opt-in via the
            # _meta keyword. Tools without long waits (status/recent/cancel)
            # ignore it.
            if name == "team_room_ask":
                result = fn(args, _meta=meta)
            else:
                result = fn(args)
        except Exception as e:
            stderr_log(f"tool {name} crashed: {e!r}")
            return jsonrpc_error(req_id, -32603, f"tool error: {e!r}")
        return jsonrpc_result(req_id, {
            "content": [{"type": "text", "text": json.dumps(result, indent=2)}],
            "isError": "error" in result,
        })

    if method.startswith("notifications/"):
        # Notifications carry no id; nothing to respond.
        return None

    return jsonrpc_error(req_id, -32601, f"method not found: {method}")


def main() -> int:
    stderr_log(f"team-room MCP server starting (room_dir={ROOM_DIR})")
    if not ORCHESTRATE.exists():
        stderr_log(f"WARNING: orchestrate.py not found at {ORCHESTRATE}; team_room_ask will fail")

    while True:
        msg = read_message()
        if msg is None:
            stderr_log("stdin closed; exiting")
            return 0
        try:
            response = handle(msg)
            if response is not None:
                write_message(response)
        except Exception as e:
            stderr_log(f"FATAL handling message: {e!r}")
            if msg.get("id") is not None:
                try:
                    write_message(jsonrpc_error(msg["id"], -32603, f"server error: {e!r}"))
                except Exception:
                    pass


if __name__ == "__main__":
    sys.exit(main())
