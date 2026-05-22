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

You're teammates, not opponents. Your different training pulls each of you toward
different lenses, and that asymmetry is the point: division of labor across vantage
points, not debate. Goal: an answer Costa can act on, that neither of you would have
produced alone.

**Turn 1 is a framing turn, not an answer turn.** Your job is to give {other_agent} a
working frame they can improve. Cover, briefly:
  - The decision you think Costa is actually asking about
  - The 2–3 criteria that should decide it
  - One uncertainty you want {other_agent} to test or weigh in on
  - The lens your training pulls you toward — surface it as a lens, not a status
    (e.g. "my code-base-heavy prior says…", "my policy/safety lens flags…")

End by handing off something specific for {other_agent} to engage with — a frame to
reshape, a question to push on, an explicit ask ("{other_agent}, what's your read on X?").

**Escape valve:** if the question is small or already-clear and framing it would be
ritual, open with `[frame-clear]` and go straight to evidence or recommendation. Use
sparingly — most non-trivial questions benefit from a real frame.

**Tag your turn at the very start, on its own line:** `[frame]` or `[frame-clear]`.

Be ~{turn_words} words. Conversational, not formal. Don't try to close the question on
turn 1.

You have read-only access to the workspace. If grounding the frame needs evidence,
dispatch a sub-agent (Agent tool) for one read-only research task and cite file:line.
Don't ask {other_agent} to do lookups you can do yourself.

Costa's question and the conversation so far:
{full_transcript}

Open the session."""


DIALOGUE_TURN_PROMPT = """You're in a working session with {other_agent} — your colleague
from a different AI lab — helping Costa land a good answer. This is turn {turn_n} of up
to {max_turns}. {other_agent} just spoke (their turn is at the bottom of the transcript).

You're teammates, not opponents. Engage with {other_agent}'s reasoning specifically,
address them by name, move the conversation toward a real answer.

**Substantive uptake — required, but real.** Open by naming what you're taking from
{other_agent}'s last turn before adding, narrowing, or challenging anything. If their
turn genuinely doesn't help, say so plainly and redirect — don't fake agreement.
Generic "great point, building on that…" is collaboration theater; honest redirect
beats empty echo.

**If you disagree, map the fork — don't score claims.** Identify the condition under
which {other_agent}'s view holds, the condition where yours differs, and what evidence
would decide it. Avoid debate vocabulary: no "false claim", "missed risk", "weak
argument" — that's grading-mode, not team-mode.

**Asymmetry is a tool.** Lean into your different lenses. "My code-base-heavy prior
notices…" / "My policy/safety lens flags…" — productive division of labor, not status.

**Turn 2 specifically:** your job is to *reshape* the frame {other_agent} just put
down before adding new substance. Don't write a parallel essay; improve the working
brief.

**Sub-agents inline.** If you need evidence, dispatch a sub-agent (Agent tool) for a
read-only task — grep, file read, count — and cite file:line in this turn. You may
direct-ask {other_agent} when their lens is genuinely sharper ("{other_agent}, your X
lens is better here — sanity-check Y while I look at Z?").

**Closing.** Two terminal moves; both ship a structured section the system extracts
to produce the artifact Costa cites. Use the exact markers — that's what's parsed.

If you've landed together, tag `[converge]` and include, in the body of your turn:

    **Joint read for Costa:** <ONE sentence — what to do, decided. A second
    sentence ONLY if the why is genuinely non-obvious. Never more than two.
    No hedging, no "we think", no preamble. This sentence is what gets
    surfaced verbatim to Costa — make every word earn its place.>

Anything else in the turn is optional reasoning around it — that stays in
the transcript, not the surfaced answer. The reasoning is for the expanded
view; the joint read is for the headline.

If the disagreement matters and won't resolve, tag `[fork]` and include:

    **Fork:**
    - {other_agent}'s view: <one sentence>
    - My view: <one sentence>
    - Deciding evidence: <one sentence — what would resolve this>

Don't paper over either. Don't fake convergence to look productive; don't manufacture
a fork to look thorough. The deliberation can be as deep as it needs to be — the
*surfaced* answer should be tight enough to fit in a single line of chat.

**Tag your turn at the very start, on its own line**, with one of:
  `[reshape]` `[evidence]` `[build]` `[refine]` `[push-back]` `[converge]` `[fork]`

`[converge]` and `[fork]` are terminal — they close the session. Use `[converge]`
only if you actually agree on a joint read for Costa; use `[fork]` only if you
genuinely cannot land. To map an unresolved fork mid-conversation without
closing, write it in prose and pick a non-terminal tag (`[push-back]`, `[refine]`).

Be ~{turn_words} words. Conversational. You're talking to {other_agent} and to Costa.

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


# The session closes when an agent signals it explicitly. Three patterns:
#   1. `[converge]` or `[fork]` as the OPENING tag of the turn (first non-empty
#      line). `[converge]` = team landed on a joint answer; `[fork]` = they
#      explicitly flagged unresolved disagreement. Both terminate. Mid-content
#      mentions of "fork" or `[fork]` are NOT terminators — only the opening
#      tag is, because the protocol requires the tag at the very start.
#   2. "Costa, here's where we landed:" — the natural conversational close.
#      Tolerant of common variants ("Costa — here's...", "Costa: here is where
#      we landed:") and apostrophe direction.
#   3. "# CONVERGED" — legacy marker, kept for back-compat with older iterations.
TERMINATOR_TAG_RE = re.compile(r"\A\s*\[(?:converge|fork)\]\s*(?:\n|$)", re.IGNORECASE)
CONVERGENCE_RE = re.compile(
    r"(^\s*#\s*CONVERGED\b)"
    r"|(\bCosta[\s,—:-]+here(?:'?s|\s+is)?\s+where\s+we\s+landed\b)",
    re.MULTILINE | re.IGNORECASE,
)


def _has_converged(content: str) -> bool:
    """True if an agent's response signals the session has landed.

    Recognized signals, in priority order:
      1. `[converge]` or `[fork]` as the opening tag of the turn (TERMINATOR_TAG_RE).
         Only the opening tag is treated as terminal — mid-content `[fork]`
         is treated as prose, not a terminator. This is the v2 collaborative
         protocol's canonical close signal.
      2. Legacy "Costa, here's where we landed:" closing line, or "# CONVERGED"
         marker — kept for back-compat (CONVERGENCE_RE).
    """
    text = content or ""
    if TERMINATOR_TAG_RE.match(text):
        return True
    return bool(CONVERGENCE_RE.search(text))


# ---------- Outcome classification + structured brief ----------
# Every dialogue session ends in exactly one of four outcomes:
#   converged  — agents landed on a joint read for Costa.
#   forked     — agents explicitly flagged unresolved disagreement.
#   timed-out  — max_turns reached without [converge] or [fork].
#   failed     — orchestrator/agent crash or non-zero exit.
#
# At session close we also write <topic>.brief.json so the MCP server can
# surface a single citable artifact alongside the transcript.

JOINT_READ_RE = re.compile(
    # Stop at: (a) blank line, (b) another **Bold heading**, or (c) end of string.
    # Whichever comes first. Non-greedy on the body so we don't slurp meta paragraphs.
    r"\*\*Joint read for Costa:\*\*\s*(?P<body>.+?)(?=\n\s*\n|\n\s*\*\*[A-Z]|\Z)",
    re.DOTALL | re.IGNORECASE,
)

FORK_SECTION_RE = re.compile(
    # Fork sections include the bullets directly under the heading. Stop at
    # the next non-bullet blank-line gap or another **Bold heading**.
    r"\*\*Fork:\*\*\s*\n?(?P<body>(?:[-*•+]\s*[^\n]+\n?)+)",
    re.IGNORECASE,
)

LEADING_TAG_RE = re.compile(r"\A\s*\[[a-z0-9-]+\]\s*\n?", re.IGNORECASE)


def classify_outcome(closing_content: str) -> str:
    """Return 'converged' | 'forked' | '' (empty if no terminal signal)."""
    text = closing_content or ""
    m = TERMINATOR_TAG_RE.match(text)
    if m:
        return "forked" if "fork" in m.group(0).lower() else "converged"
    if CONVERGENCE_RE.search(text):
        return "converged"
    return ""


def build_brief(
    topic: str,
    prompt_id: str,
    mode: str,
    outcome: str,
    closing_turn: dict | None,
    last_error: str | None = None,
    max_turns: int | None = None,
) -> dict:
    """Build the structured brief dict for <topic>.brief.json.

    closing_turn shape: {"agent": str, "turn": int, "content": str} | None.
    """
    brief: dict = {
        "topic": topic,
        "prompt_id": prompt_id,
        "mode": mode,
        "outcome": outcome,
        "completed_at": now_iso(),
        "transcript_path": str(ROOM_DIR / f"{topic}.jsonl"),
    }
    if closing_turn:
        brief["closing_agent"] = closing_turn["agent"]
        brief["closing_turn"] = closing_turn["turn"]
    if max_turns is not None:
        brief["max_turns"] = max_turns

    content = (closing_turn or {}).get("content", "")
    if outcome == "converged":
        m = JOINT_READ_RE.search(content)
        if m:
            brief["joint_read"] = m.group("body").strip()
        else:
            fallback = LEADING_TAG_RE.sub("", content, count=1).strip() or None
            brief["joint_read"] = fallback
            brief["parse_note"] = "no **Joint read for Costa:** marker; using full turn content"
    elif outcome == "forked":
        m = FORK_SECTION_RE.search(content)
        if m:
            brief["fork"] = m.group("body").strip()
        else:
            fallback = LEADING_TAG_RE.sub("", content, count=1).strip() or None
            brief["fork"] = fallback
            brief["parse_note"] = "no **Fork:** marker; using full turn content"
    elif outcome == "timed-out":
        brief["partial"] = LEADING_TAG_RE.sub("", content, count=1).strip() or None
    elif outcome == "failed":
        brief["error"] = last_error or "unknown failure"
    return brief


def write_brief(topic: str, brief: dict) -> Path:
    """Atomic write of <topic>.brief.json."""
    p = ROOM_DIR / f"{topic}.brief.json"
    tmp = p.with_suffix(p.suffix + ".tmp")
    tmp.write_text(json.dumps(brief, indent=2, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, p)
    return p


def _alternating_agent(turn_n: int) -> str:
    """Turn 1 = claude, turn 2 = codex, alternating. Claude opens because the
    user types in their terminal and Claude (this session) is their primary."""
    return "claude" if turn_n % 2 == 1 else "codex"


async def run_dialogue(
    topic: str,
    prompt_id: str,
    cwd: str,
    max_turns: int = DIALOGUE_MAX_TURNS,
) -> dict:
    """Live micro-turn dialogue: Claude and Codex alternate short turns,
    reacting to each other, until convergence or max turns.

    Returns a dict:
      {
        "ok": bool,                          # False on agent/orchestrator failure
        "outcome": "converged"|"forked"|"timed-out"|"failed",
        "closing_turn": {"agent","turn","content"} | None,
        "last_error": str | None,
        "max_turns": int,
      }

    Status semantics during dialogue:
      status='dialogue', turn=N (current turn about to run), max_turns=M,
      current_agent='claude'|'codex', claude_done/codex_done track the latest pair.
    """
    log(f"dialogue start topic={topic} max_turns={max_turns} words/turn={DIALOGUE_TURN_WORDS}")

    closing_turn: dict | None = None
    outcome = "timed-out"  # default if loop completes without converge/fork
    last_turn = 0

    for turn_n in range(1, max_turns + 1):
        agent = _alternating_agent(turn_n)
        other = OTHER[agent]
        last_turn = turn_n

        update_state(topic, {
            "status": "dialogue",
            "turn": turn_n,
            "max_turns": max_turns,
            "current_agent": agent,
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
            err_text = f"Orchestrator error in dialogue turn {turn_n} ({agent}): {e!r}"
            append_system_message(topic, err_text, prompt_id=prompt_id, round_n=turn_n)
            return {"ok": False, "outcome": "failed", "closing_turn": closing_turn,
                    "last_error": err_text, "max_turns": max_turns}

        if not ok:
            append_system_message(topic, err, prompt_id=prompt_id, round_n=turn_n)
            return {"ok": False, "outcome": "failed", "closing_turn": closing_turn,
                    "last_error": err, "max_turns": max_turns}

        # Capture the latest turn — it may be the closing one.
        latest = read_transcript(topic)
        last_msg = latest[-1] if latest else None
        if last_msg:
            closing_turn = {
                "agent": last_msg.get("role", agent),
                "turn": turn_n,
                "content": last_msg.get("content", ""),
            }

        content = last_msg.get("content", "") if last_msg else ""
        signaled = classify_outcome(content)
        if signaled:
            outcome = signaled
            log(f"dialogue {outcome} at turn {turn_n} ({agent})")
            append_system_message(
                topic,
                f"{outcome} at turn {turn_n} ({agent})",
                prompt_id=prompt_id,
                round_n=turn_n,
            )
            break

    if outcome == "timed-out" and last_turn == max_turns:
        append_system_message(
            topic,
            f"timed-out: reached max_turns={max_turns} without [converge] or [fork]",
            prompt_id=prompt_id,
            round_n=last_turn,
        )

    return {"ok": True, "outcome": outcome, "closing_turn": closing_turn,
            "last_error": None, "max_turns": max_turns}


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
        # v0.2 envelope: outcome surfaces in state.json so tool_status callers
        # see the terminal state directly. brief.json holds the full artifact.
        "outcome": None,
    }

    if mode == "dialogue":
        try:
            result = await run_dialogue(topic, prompt_id, cwd)
        except BaseException as e:
            log(f"dialogue raised: {e!r}")
            err_text = f"Dialogue orchestrator crashed: {e!r}"
            append_system_message(topic, err_text, prompt_id=prompt_id)
            result = {"ok": False, "outcome": "failed", "closing_turn": None,
                     "last_error": err_text, "max_turns": DIALOGUE_MAX_TURNS}

        # Write the structured brief regardless of outcome — the envelope is
        # contractually "every room ends in a legible terminal state."
        try:
            brief = build_brief(
                topic=topic,
                prompt_id=prompt_id,
                mode="dialogue",
                outcome=result["outcome"],
                closing_turn=result.get("closing_turn"),
                last_error=result.get("last_error"),
                max_turns=result.get("max_turns"),
            )
            brief_path = write_brief(topic, brief)
            log(f"brief written to {brief_path}")
        except Exception as e:
            log(f"failed to write brief: {e!r}")

        final_idle["outcome"] = result["outcome"]
        final_idle["last_error"] = result.get("last_error")
        update_state(topic, final_idle)
        log(f"dialogue done (outcome={result['outcome']}, ok={result['ok']}); state=idle")
        return 0 if result["ok"] else 1

    # --- mode == 'rounds' (opt-in adversarial review) ---
    rounds_error: str | None = None
    r1_ok = await run_round(topic, prompt_id, 1, cwd)
    if not r1_ok:
        log("R1 had failures; skipping R2 and going idle")
        rounds_error = "one or more agents failed during R1"
        outcome = "failed"
    else:
        update_state(topic, {
            "status": "round-2",
            "claude_done": False,
            "codex_done": False,
            "last_error": None,
        })
        log("transitioned to round-2")
        r2_ok = await run_round(topic, prompt_id, 2, cwd)
        if r2_ok:
            outcome = "completed"
        else:
            outcome = "failed"
            rounds_error = "one or more agents failed during R2"

    # Rounds-mode brief: minimal — outcome + last_error. Critique transcript
    # is the artifact; no joint_read/fork extraction (rounds is adversarial
    # review, not collaborative deliberation).
    try:
        brief = {
            "topic": topic,
            "prompt_id": prompt_id,
            "mode": "rounds",
            "outcome": outcome,
            "completed_at": now_iso(),
            "transcript_path": str(ROOM_DIR / f"{topic}.jsonl"),
        }
        if rounds_error:
            brief["error"] = rounds_error
        write_brief(topic, brief)
    except Exception as e:
        log(f"failed to write rounds brief: {e!r}")

    final_idle["outcome"] = outcome
    final_idle["last_error"] = rounds_error
    update_state(topic, final_idle)
    log(f"rounds done (outcome={outcome}); state=idle")
    return 0 if outcome == "completed" else 1


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
