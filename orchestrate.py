#!/usr/bin/env python3
"""Team Room v2 orchestrator: runs the R1 + R2 deliberation loop.

Invoked by server.py after Costa's message has been appended to JSONL and
state has been set to round-1. This script spawns Claude + Codex in parallel
for two rounds, the second of which sees the other agent's R1 response.

Usage:
    python3 orchestrate.py --topic <name> --prompt-id <id>

State transitions (all under fcntl.flock on <topic>.state.lock):
    round-1 (entry) -> round-2 (after both R1 done) -> idle (after both R2 done)

On any timeout or fatal error: writes a system message to JSONL, transitions
state to idle with last_error set, exits non-zero.
"""

from __future__ import annotations

import argparse
import asyncio
import datetime
import fcntl
import json
import os
import signal
import subprocess
import sys
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parent
ROOM_DIR = Path(os.environ.get("TEAM_ROOM_DIR", SCRIPT_DIR / ".team-room"))
APPENDER = SCRIPT_DIR / "_append-jsonl.py"
ASK_CLAUDE = SCRIPT_DIR / "ask-claude.sh"
ASK_CODEX = SCRIPT_DIR / "ask-codex.sh"

# 5 minutes per agent per round, per spec. Overridable for testing via env.
AGENT_TIMEOUT_S = int(os.environ.get("TEAM_ROOM_AGENT_TIMEOUT", "300"))


# ---------- Prompt templates (verbatim from v2-design.md) ----------

R1_PROMPT = """You are participating in a team room with another AI agent ({other_agent}).
The human leading the room is Costa. Your job is to give your honest first-take
response to his latest message. Don't reference the other agent's response -
they haven't responded yet. Be terse, evidence-first.

Full conversation so far:
{full_transcript}

Respond to Costa's most recent message."""


R2_PROMPT = """You are participating in a team room with another AI agent ({other_agent}).
{other_agent} just answered the same question you did. Read their response carefully.

Your task - be ruthless. Identify, in this exact order:

1. **The strongest false or unsupported claim** in {other_agent}'s response. Quote
   the claim. Explain why it's wrong, weak, or insufficient. If you cannot identify
   one, explicitly state "I find no false or unsupported claims" and give your
   evidence for why (e.g., "every factual claim is corroborated by file X" or
   "their argument is supported by documented behavior").

2. **One important risk or consideration they MISSED.** Be specific. If they
   missed nothing material, say "no material gap" with reasoning.

3. **Does this change your recommendation?** Answer yes/no/partial. If yes/partial,
   state your revised position clearly. If no, explain what evidence would change
   your mind.

You may not respond with "I broadly agree" or similar consensus phrasing unless
you have provided concrete evidence in points 1 and 2 that no false claims exist
and no material gaps were missed. Sycophancy weakens the team. Disagreement with
evidence strengthens it.

Full conversation so far (including your R1 and {other_agent}'s R1):
{full_transcript}

Respond."""


# ---------- Logging / time helpers ----------


def now_iso() -> str:
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def log(msg: str) -> None:
    """Tee important events to stderr (already redirected to orchestrate.log by server)."""
    print(f"[{now_iso()}] orchestrate: {msg}", file=sys.stderr, flush=True)


# ---------- State file (atomic R/W under flock) ----------


def state_paths(topic: str) -> tuple[Path, Path, Path]:
    state_path = ROOM_DIR / f"{topic}.state.json"
    lock_path = ROOM_DIR / f"{topic}.state.lock"
    tmp_path = ROOM_DIR / f"{topic}.state.json.tmp"
    return state_path, lock_path, tmp_path


def _read_state_unlocked(state_path: Path) -> dict:
    if not state_path.exists():
        return {}
    try:
        return json.loads(state_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def _write_state_unlocked(state_path: Path, tmp_path: Path, state: dict) -> None:
    tmp_path.write_text(json.dumps(state, indent=2), encoding="utf-8")
    os.replace(tmp_path, state_path)  # POSIX atomic on same fs


def update_state(topic: str, updates: dict) -> dict:
    """Read-modify-write the state file under LOCK_EX. Returns the new state."""
    state_path, lock_path, tmp_path = state_paths(topic)
    ROOM_DIR.mkdir(parents=True, exist_ok=True)
    with open(lock_path, "w") as lockf:
        fcntl.flock(lockf, fcntl.LOCK_EX)
        try:
            state = _read_state_unlocked(state_path)
            state.update(updates)
            _write_state_unlocked(state_path, tmp_path, state)
            return state
        finally:
            fcntl.flock(lockf, fcntl.LOCK_UN)


# ---------- Workspace ----------


def resolve_workspace(topic: str) -> str:
    workspace_path = ROOM_DIR / f"{topic}.workspace.json"
    if workspace_path.exists():
        try:
            data = json.loads(workspace_path.read_text(encoding="utf-8"))
            ws = data.get("workspace")
            if ws and Path(ws).is_dir():
                return ws
            if ws:
                log(f"configured workspace does not exist: {ws}; falling back to $HOME")
        except (json.JSONDecodeError, OSError) as e:
            log(f"workspace.json unreadable ({e}); falling back to $HOME")
    home = os.environ.get("HOME", str(Path.home()))
    # Write the default for future runs so the file is canonical.
    try:
        ROOM_DIR.mkdir(parents=True, exist_ok=True)
        workspace_path.write_text(
            json.dumps({"workspace": home, "created_at": now_iso()}, indent=2),
            encoding="utf-8",
        )
    except OSError as e:
        log(f"could not persist default workspace ({e}); continuing with {home}")
    return home


# ---------- Transcript ----------


def read_transcript(topic: str) -> list[dict]:
    """Read JSONL under shared lock so we never race with an in-flight append."""
    jsonl_path = ROOM_DIR / f"{topic}.jsonl"
    if not jsonl_path.exists():
        return []
    lock_path = ROOM_DIR / f"{topic}.jsonl.lock"
    msgs: list[dict] = []
    with open(lock_path, "a") as lockf:
        fcntl.flock(lockf, fcntl.LOCK_SH)
        try:
            with open(jsonl_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        msgs.append(json.loads(line))
                    except json.JSONDecodeError:
                        # Skip malformed line; viewer is lenient too.
                        continue
        finally:
            fcntl.flock(lockf, fcntl.LOCK_UN)
    return msgs


def format_transcript(msgs: list[dict]) -> str:
    """Render messages as the one-block-per-message form the prompt expects."""
    lines = []
    for m in msgs:
        ts = m.get("ts", "?")
        role = m.get("role", "unknown").upper()
        rnd = m.get("round")
        tag = f"{role} (R{rnd})" if rnd else role
        content = m.get("content", "")
        lines.append(f"[{ts}] {tag}: {content}")
    return "\n\n".join(lines)


def append_system_message(topic: str, content: str) -> None:
    """Append a system-role message via the canonical locked appender."""
    jsonl_path = ROOM_DIR / f"{topic}.jsonl"
    try:
        subprocess.run(
            [sys.executable, str(APPENDER), str(jsonl_path), "system", "system", content],
            check=True,
            timeout=10,
        )
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as e:
        # Last-resort: log to stderr (orchestrate.log) so the failure is visible.
        log(f"FAILED to append system message {content!r}: {e}")


# ---------- Agent invocation ----------

AGENTS = ("claude", "codex")
OTHER = {"claude": "Codex", "codex": "Claude"}
SCRIPT_FOR = {"claude": ASK_CLAUDE, "codex": ASK_CODEX}
DONE_FLAG = {"claude": "claude_done", "codex": "codex_done"}


async def run_agent(
    agent: str,
    topic: str,
    prompt_id: str,
    round_n: int,
    cwd: str,
    prompt: str,
) -> tuple[str, bool, str]:
    """Spawn ask-<agent>.sh in --orchestrate mode, pipe prompt via stdin.

    Returns (agent, success, error_or_empty). The agent's response (on success)
    is written to JSONL by the helper script itself via _append-jsonl.py.
    """
    script = SCRIPT_FOR[agent]
    cmd = [
        "bash",
        str(script),
        "--orchestrate",
        "--topic", topic,
        "--prompt-id", prompt_id,
        "--round", str(round_n),
        "--cwd", cwd,
    ]
    log(f"R{round_n} spawn {agent}: {' '.join(cmd)}")
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        start_new_session=True,  # new pgid so we can kill children too on timeout
    )
    try:
        stdout, stderr = await asyncio.wait_for(
            proc.communicate(input=prompt.encode("utf-8")),
            timeout=AGENT_TIMEOUT_S,
        )
    except asyncio.TimeoutError:
        # Kill the whole process group; claude/codex may have fork-execed children.
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            pass
        try:
            await asyncio.wait_for(proc.wait(), timeout=5)
        except asyncio.TimeoutError:
            pass
        log(f"R{round_n} {agent} TIMED OUT after {AGENT_TIMEOUT_S}s")
        if AGENT_TIMEOUT_S >= 60:
            human = f"{AGENT_TIMEOUT_S // 60}min"
        else:
            human = f"{AGENT_TIMEOUT_S}s"
        return agent, False, f"{agent.capitalize()} timed out after {human} during R{round_n}"

    if proc.returncode != 0:
        err = (stderr.decode("utf-8", errors="replace") or "").strip()
        err_short = err.splitlines()[-1] if err else f"exit {proc.returncode}"
        log(f"R{round_n} {agent} FAILED (exit {proc.returncode}): {err}")
        return agent, False, f"{agent.capitalize()} failed during R{round_n}: {err_short}"

    log(f"R{round_n} {agent} OK ({len(stdout)} bytes)")
    return agent, True, ""


# ---------- Round orchestration ----------


async def run_round(
    topic: str,
    prompt_id: str,
    round_n: int,
    cwd: str,
) -> bool:
    """Run one round (R1 or R2) of both agents in parallel.

    Returns True if both agents succeeded, False otherwise (system messages
    have already been appended to JSONL for any failures).
    """
    msgs = read_transcript(topic)
    transcript = format_transcript(msgs)

    tasks = []
    for agent in AGENTS:
        prompt_template = R1_PROMPT if round_n == 1 else R2_PROMPT
        prompt = prompt_template.format(
            other_agent=OTHER[agent],
            full_transcript=transcript,
        )
        tasks.append(run_agent(agent, topic, prompt_id, round_n, cwd, prompt))

    results = await asyncio.gather(*tasks, return_exceptions=True)

    all_ok = True
    for r in results:
        if isinstance(r, BaseException):
            log(f"R{round_n} task raised: {r!r}")
            append_system_message(topic, f"Orchestrator error during R{round_n}: {r!r}")
            all_ok = False
            continue
        agent, ok, err_msg = r
        # Mark done regardless of success so viewer placeholders clear.
        update_state(topic, {DONE_FLAG[agent]: True})
        if not ok:
            append_system_message(topic, err_msg)
            all_ok = False
    return all_ok


async def main_async(topic: str, prompt_id: str) -> int:
    cwd = resolve_workspace(topic)
    log(f"start topic={topic} prompt_id={prompt_id} cwd={cwd} pid={os.getpid()}")

    # Sanity-check: state file should already say round-1 with our prompt_id.
    state_path, _, _ = state_paths(topic)
    state = _read_state_unlocked(state_path)
    if state.get("prompt_id") != prompt_id:
        log(f"WARN state prompt_id={state.get('prompt_id')!r} != ours={prompt_id!r}; continuing anyway")

    # --- Round 1 ---
    r1_ok = await run_round(topic, prompt_id, 1, cwd)
    if not r1_ok:
        log("R1 had failures; skipping R2 and going idle")
        update_state(topic, {
            "status": "idle",
            "prompt_id": None,
            "started_at": None,
            "orchestrator_pid": None,
            "claude_done": False,
            "codex_done": False,
            "last_error": "one or more agents failed during R1",
        })
        return 1

    # Transition R1 -> R2 atomically.
    update_state(topic, {
        "status": "round-2",
        "claude_done": False,
        "codex_done": False,
        "last_error": None,
    })
    log("transitioned to round-2")

    # --- Round 2 ---
    r2_ok = await run_round(topic, prompt_id, 2, cwd)

    # Always finish in idle, regardless of R2 outcome. Partial responses are
    # still in JSONL; Costa decides what to do next.
    final_error = None if r2_ok else "one or more agents failed during R2"
    update_state(topic, {
        "status": "idle",
        "prompt_id": None,
        "started_at": None,
        "orchestrator_pid": None,
        "claude_done": False,
        "codex_done": False,
        "last_error": final_error,
    })
    log(f"done (R2 ok={r2_ok}); state=idle")
    return 0 if r2_ok else 1


def main() -> int:
    ap = argparse.ArgumentParser(description="Team Room v2 orchestrator")
    ap.add_argument("--topic", required=True)
    ap.add_argument("--prompt-id", required=True)
    args = ap.parse_args()

    try:
        return asyncio.run(main_async(args.topic, args.prompt_id))
    except KeyboardInterrupt:
        log("interrupted; marking state idle")
        update_state(args.topic, {
            "status": "idle",
            "prompt_id": None,
            "started_at": None,
            "orchestrator_pid": None,
            "claude_done": False,
            "codex_done": False,
            "last_error": "orchestrator interrupted",
        })
        return 130
    except Exception as e:
        log(f"FATAL: {e!r}")
        try:
            append_system_message(args.topic, f"Orchestrator crashed: {e!r}")
            update_state(args.topic, {
                "status": "idle",
                "prompt_id": None,
                "started_at": None,
                "orchestrator_pid": None,
                "claude_done": False,
                "codex_done": False,
                "last_error": f"orchestrator crashed: {e!r}",
            })
        except Exception:
            pass
        return 1


if __name__ == "__main__":
    sys.exit(main())
