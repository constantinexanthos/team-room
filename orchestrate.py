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
import re
import signal
import subprocess
import sys
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parent
ROOM_DIR = Path(os.environ.get("TEAM_ROOM_DIR", SCRIPT_DIR / ".team-room"))
APPENDER = SCRIPT_DIR / "_append-jsonl.py"
ASK_CLAUDE = SCRIPT_DIR / "ask-claude.sh"
ASK_CODEX = SCRIPT_DIR / "ask-codex.sh"

# 8 minutes per agent per round. Codex's first invocation in a fresh workspace
# (with high reasoning effort + MCP server warm-up + file exploration) can take
# longer than 5min the first time. Overridable for testing via env.
AGENT_TIMEOUT_S = int(os.environ.get("TEAM_ROOM_AGENT_TIMEOUT", "480"))

# Live dialogue mode: max turns per iteration before forcing convergence.
DIALOGUE_MAX_TURNS = int(os.environ.get("TEAM_ROOM_MAX_TURNS", "8"))

# Word budget per micro-turn. Long enough to make a real point, short enough
# to keep the dialogue feeling live and conversational.
DIALOGUE_TURN_WORDS = int(os.environ.get("TEAM_ROOM_TURN_WORDS", "150"))


# ---------- Prompt templates (verbatim from v2-design.md) ----------

R1_PROMPT = """You are participating in a team room with another AI agent ({other_agent}).
The human leading the room is Costa. Your job is to give your honest first-take
response to his latest message. Don't reference the other agent's response -
they haven't responded yet. Be terse, evidence-first.

Full conversation so far:
{full_transcript}

Respond to Costa's most recent message."""


DIALOGUE_OPENING_PROMPT = """You're opening a working session with {other_agent} — your
colleague from a different AI lab — to help Costa land a good answer to the question below.

This isn't a debate or a peer-review. You and {other_agent} are on the same team. Your
different training data and reasoning patterns are *useful* — between the two of you,
you'll catch things either of you alone would miss. The goal is to think harder together
than either of you could alone, and end up with an answer Costa can act on.

You're going first. Open the session by doing one of these:
  - Take a clear initial position so {other_agent} has something concrete to push on
  - Frame the question more precisely if Costa's wording leaves real ambiguity
  - Name what you think matters most about this question, and why
  - Surface what you're genuinely uncertain about and want {other_agent}'s read on

End your turn by giving {other_agent} something to engage with — a position to refine,
a question to weigh in on, or an explicit handoff ("{other_agent}, what's your read on X?").

Be ~{turn_words} words. Conversational, not formal. Don't try to close the question on
turn 1 — open it. You and {other_agent} will trade turns until you've genuinely landed
somewhere together.

You have read-only access to the workspace. If the question is grounded in code or files
and you need evidence, spawn a sub-agent (Agent tool) to investigate — one read-only
research task per turn is fine. Cite file:line in your response. Don't guess when you
can look.

Costa's question and the conversation so far:
{full_transcript}

Open the session."""


DIALOGUE_TURN_PROMPT = """You're in a working session with {other_agent} — your colleague
from a different AI lab — helping Costa land a good answer. This is turn {turn_n} of up
to {max_turns}. {other_agent} just spoke (their turn is at the bottom of the transcript).

You're teammates, not opponents. The frame here is *think together*, not *grade each
other*. Respond to what {other_agent} just said the way a good colleague would — engage
specifically with their reasoning, address them by name, and move the conversation toward
a real answer.

Natural moves your turn can take (mix as needed, you don't have to pick just one):

  - **Build on it:** "{other_agent}, that frames it well — one thing I'd add..."
  - **Refine:** "{other_agent} — yes, but the case you're describing only holds when X..."
  - **Defer:** "{other_agent}, you're closer to this than I am — what do you think
    about Y given what you just said?"
  - **Update:** "Hmm, {other_agent}, you're right that I missed Z. That changes my read on..."
  - **Raise something they didn't see:** "{other_agent}, one angle I think we should
    consider before we land this..."
  - **Land it:** if you've actually arrived together, write a short closing line
    addressed to Costa: "Costa, here's where we landed: [the answer]." That ends the
    session.

Don't perform disagreement to look thorough. If {other_agent} got it right, say so and
help refine. If they missed something material, raise it as a teammate would, not as a
debater. Address {other_agent} by name when you respond to a specific thing they said.

Be ~{turn_words} words. Conversational. You're not writing for an audience — you're
talking to {other_agent} and to Costa.

You have read-only access to the workspace. If you need evidence to back what you're
saying, spawn a sub-agent (Agent tool) for one read-only research task — grep for usage,
read a config, count occurrences. Cite file:line. Don't guess when you can look.

The session so far:
{full_transcript}

Your turn (#{turn_n}). Talk to {other_agent}."""


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


def append_system_message(topic: str, content: str, prompt_id: str | None = None, round_n: int | None = None) -> None:
    """Append a system-role message via the canonical locked appender.

    Passes prompt_id (and optional round) so the message groups with its iteration
    in the viewer — otherwise timeout/error messages float orphaned with no visual
    association to the prompt that triggered them.
    """
    jsonl_path = ROOM_DIR / f"{topic}.jsonl"
    cmd = [sys.executable, str(APPENDER), str(jsonl_path), "system", "system", content]
    if round_n is not None:
        cmd += ["--round", str(round_n)]
    if prompt_id is not None:
        cmd += ["--prompt-id", prompt_id]
    try:
        subprocess.run(cmd, check=True, timeout=10)
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as e:
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

    # IMPORTANT: do NOT pipe stdout/stderr through asyncio. The agent CLIs
    # (claude --print, codex exec) spawn MCP server daemon children that
    # inherit fds. Those children stay alive after the wrapper script exits,
    # holding the stdout/stderr pipes open, which makes proc.communicate()
    # hang forever even though our helper script has finished its work.
    # Solution: redirect the helper's stdout/stderr to /dev/null. The agent's
    # response is written to JSONL by the helper itself via _append-jsonl.py;
    # we only need to know whether the helper exited cleanly.
    stderr_log_path = ROOM_DIR / f"{topic}.orchestrate.log"
    stderr_log_path.parent.mkdir(parents=True, exist_ok=True)
    # Open a low-level fd we control explicitly. Passing a Python file object
    # to asyncio.create_subprocess_exec only takes a dup of its underlying fd;
    # the file object's buffer state in the parent doesn't matter, but we MUST
    # keep our fd alive until the child exits or the kernel closes the write
    # side and the child's writes silently disappear into a pipe-closed errno.
    stderr_fd = os.open(stderr_log_path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o644)
    proc = None
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=stderr_fd,
            start_new_session=True,
        )

        # Write the prompt and close stdin so the child sees EOF.
        try:
            if proc.stdin is not None:
                proc.stdin.write(prompt.encode("utf-8"))
                await proc.stdin.drain()
                proc.stdin.close()
        except (BrokenPipeError, ConnectionResetError):
            pass

        try:
            await asyncio.wait_for(proc.wait(), timeout=AGENT_TIMEOUT_S)
        except asyncio.TimeoutError:
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
            log(f"R{round_n} {agent} FAILED (exit {proc.returncode}); see stderr in this log above")
            return agent, False, f"{agent.capitalize()} failed during R{round_n} (exit {proc.returncode}; see {topic}.orchestrate.log)"

        log(f"R{round_n} {agent} OK")
        return agent, True, ""
    finally:
        # Close our fd only after the subprocess has exited (or has been
        # killed). The kernel keeps the file open as long as the child has
        # its dup'd fd, but closing ours frees the descriptor in our process.
        try:
            os.close(stderr_fd)
        except OSError:
            pass


# ---------- Round orchestration ----------


# The session closes when an agent signals it explicitly. Two patterns are
# recognized:
#   1. "Costa, here's where we landed:" — the natural conversational close
#      that the new collaborative-framed prompts ask for. Tolerant of common
#      variants ("Costa — here's...", "Costa: here is where we landed:") and
#      apostrophe direction.
#   2. "# CONVERGED" — the legacy marker. Kept for back-compat with older
#      iterations and as a hard-stop the agents can fall back to.
CONVERGENCE_RE = re.compile(
    r"(^\s*#\s*CONVERGED\b)"
    r"|(\bCosta[\s,—:-]+here(?:'?s|\s+is)?\s+where\s+we\s+landed\b)",
    re.MULTILINE | re.IGNORECASE,
)


def _has_converged(content: str) -> bool:
    """True if an agent's response signals the session has landed —
    either by addressing Costa with a wrap-up line, or by writing the
    legacy `# CONVERGED` marker."""
    return bool(CONVERGENCE_RE.search(content or ""))


def _alternating_agent(turn_n: int) -> str:
    """Turn 1 = claude, turn 2 = codex, alternating. Claude opens because the
    user types in their terminal and Claude (this session) is their primary."""
    return "claude" if turn_n % 2 == 1 else "codex"


async def run_dialogue(
    topic: str,
    prompt_id: str,
    cwd: str,
    max_turns: int = DIALOGUE_MAX_TURNS,
) -> bool:
    """Live micro-turn dialogue: Claude and Codex alternate short turns,
    reacting to each other, until convergence or max turns.

    Each turn:
      - the active agent sees the full transcript including the other's last turn
      - response is capped at DIALOGUE_TURN_WORDS for conversational pace
      - response is checked for the CONVERGED marker → if so, stop

    Status semantics during dialogue:
      status='dialogue', turn=N (current turn about to run), max_turns=M,
      current_agent='claude'|'codex', claude_done/codex_done track the latest pair.
    """
    log(f"dialogue start topic={topic} max_turns={max_turns} words/turn={DIALOGUE_TURN_WORDS}")

    converged = False
    last_turn = 0
    for turn_n in range(1, max_turns + 1):
        agent = _alternating_agent(turn_n)
        other = OTHER[agent]
        last_turn = turn_n

        # Mark this turn in-flight under the state lock.
        update_state(topic, {
            "status": "dialogue",
            "turn": turn_n,
            "max_turns": max_turns,
            "current_agent": agent,
            # Use *_done as: True iff that agent has spoken at least once
            # in this iteration. Lets the UI show different placeholders.
            "claude_done": turn_n > 1 or agent == "codex",
            "codex_done": turn_n > 1 and agent != "codex" or False,
            "last_error": None,
        })

        msgs = read_transcript(topic)
        transcript = format_transcript(msgs)

        if turn_n == 1:
            prompt = DIALOGUE_OPENING_PROMPT.format(
                other_agent=other,
                full_transcript=transcript,
                turn_words=DIALOGUE_TURN_WORDS,
            )
        else:
            prompt = DIALOGUE_TURN_PROMPT.format(
                other_agent=other,
                turn_n=turn_n,
                max_turns=max_turns,
                full_transcript=transcript,
                turn_words=DIALOGUE_TURN_WORDS,
            )

        try:
            _, ok, err = await run_agent(agent, topic, prompt_id, turn_n, cwd, prompt)
        except BaseException as e:
            log(f"dialogue turn {turn_n} ({agent}) raised: {e!r}")
            append_system_message(
                topic,
                f"Orchestrator error in dialogue turn {turn_n} ({agent}): {e!r}",
                prompt_id=prompt_id,
                round_n=turn_n,
            )
            return False

        if not ok:
            append_system_message(topic, err, prompt_id=prompt_id, round_n=turn_n)
            return False

        # Re-read transcript to inspect what was just appended.
        latest = read_transcript(topic)
        last_msg = latest[-1] if latest else None
        if last_msg and _has_converged(last_msg.get("content", "")):
            log(f"dialogue converged at turn {turn_n} ({agent})")
            converged = True
            append_system_message(
                topic,
                f"converged at turn {turn_n} ({agent})",
                prompt_id=prompt_id,
                round_n=turn_n,
            )
            break

    if not converged and last_turn == max_turns:
        append_system_message(
            topic,
            f"reached max_turns={max_turns} without explicit convergence",
            prompt_id=prompt_id,
            round_n=last_turn,
        )

    return True


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
            append_system_message(topic, f"Orchestrator error during R{round_n}: {r!r}", prompt_id=prompt_id, round_n=round_n)
            all_ok = False
            continue
        agent, ok, err_msg = r
        # Mark done regardless of success so viewer placeholders clear.
        update_state(topic, {DONE_FLAG[agent]: True})
        if not ok:
            append_system_message(topic, err_msg, prompt_id=prompt_id, round_n=round_n)
            all_ok = False
    return all_ok


async def main_async(topic: str, prompt_id: str, mode: str = "dialogue") -> int:
    cwd = resolve_workspace(topic)
    log(f"start topic={topic} prompt_id={prompt_id} mode={mode} cwd={cwd} pid={os.getpid()}")

    state_path, _, _ = state_paths(topic)
    state = _read_state_unlocked(state_path)
    if state.get("prompt_id") != prompt_id:
        log(f"WARN state prompt_id={state.get('prompt_id')!r} != ours={prompt_id!r}; continuing anyway")

    final_idle = {
        "status": "idle",
        "prompt_id": None,
        "started_at": None,
        "orchestrator_pid": None,
        "claude_done": False,
        "codex_done": False,
        "turn": None,
        "max_turns": None,
        "current_agent": None,
        "last_error": None,
    }

    if mode == "dialogue":
        try:
            ok = await run_dialogue(topic, prompt_id, cwd)
        except BaseException as e:
            log(f"dialogue raised: {e!r}")
            append_system_message(topic, f"Dialogue orchestrator crashed: {e!r}", prompt_id=prompt_id)
            ok = False
        final_idle["last_error"] = None if ok else "dialogue had failures"
        update_state(topic, final_idle)
        log(f"dialogue done (ok={ok}); state=idle")
        return 0 if ok else 1

    # --- mode == 'rounds' (legacy R1/R2) ---
    r1_ok = await run_round(topic, prompt_id, 1, cwd)
    if not r1_ok:
        log("R1 had failures; skipping R2 and going idle")
        final_idle["last_error"] = "one or more agents failed during R1"
        update_state(topic, final_idle)
        return 1

    update_state(topic, {
        "status": "round-2",
        "claude_done": False,
        "codex_done": False,
        "last_error": None,
    })
    log("transitioned to round-2")

    r2_ok = await run_round(topic, prompt_id, 2, cwd)
    final_idle["last_error"] = None if r2_ok else "one or more agents failed during R2"
    update_state(topic, final_idle)
    log(f"done (R2 ok={r2_ok}); state=idle")
    return 0 if r2_ok else 1


def main() -> int:
    ap = argparse.ArgumentParser(description="Team Room orchestrator")
    ap.add_argument("--topic", required=True)
    ap.add_argument("--prompt-id", required=True)
    ap.add_argument("--mode", default="dialogue", choices=["dialogue", "rounds"],
                    help="dialogue=live micro-turn (default); rounds=legacy R1/R2 structured")
    args = ap.parse_args()

    try:
        return asyncio.run(main_async(args.topic, args.prompt_id, args.mode))
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
