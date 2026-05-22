# Team Room v2 — Interactive Iteration Loop

Date: 2026-05-22
Author: Costa + Claude (Opus 4.7)
Status: Approved (signed-off 2026-05-22) — implementation in progress

## What's changing from v1

**v1 (shipped):** Browser viewer that polls a JSONL transcript. You type into a terminal (Claude Code), the terminal invokes Codex via `ask-codex.sh`, both sides land in the JSONL, browser updates. Read-only viewer.

**v2 (this spec):** Browser becomes the *room*. You type directly in the viewer. Both Claude and Codex respond, and — critically — each one's second turn is informed by what the other said. Not parallel A/B testing; actual collaboration.

## Goals

1. Costa types a prompt in the browser, hits Send.
2. Both Claude and Codex respond cold (parallel) — that's the unbiased first take.
3. Both Claude and Codex respond again, each having seen the other's first take. They critique, build on, or push back.
4. Costa sees all 4 responses streaming in, color-coded, in chronological order.
5. Costa can intervene any time with another prompt — that becomes the next iteration's seed.

## Workspace file access (MVP addition)

Without file access, the agents are guessing in a vacuum — useless for real deliberation on actual code. **Both agents get read-only access to a per-topic workspace directory.**

- Each topic has a workspace dir (configured at topic creation; defaults to `~/vigil` for the first real use).
- Orchestrator launches `claude --print` and `codex exec` with `cwd = <workspace>`.
- Both CLIs already support file reads natively (their built-in tools). No new tool layer needed.
- **Write/execute are disabled.** Claude: `--disallowedTools "Write Edit Bash NotebookEdit"`. Codex: `--sandbox read-only` (already the default).
- The R1/R2 prompts explicitly tell the agents they can read files in the workspace and should ground their answers in the actual code, not their priors.

Storage: workspace path lives in `<topic>.workspace.json` (created at topic creation; persists across iterations).

### ⚠️ Workspace = data-leak surface

When agents read files from the workspace, those file contents are sent to model provider APIs (Anthropic for Claude, OpenAI for Codex). That means:

- **Secrets** in `.env`, `.envrc`, `~/.aws/credentials`, etc. WILL be visible to the agent if it reads them, and WILL be transmitted to the provider as context. Costa is the only operator and chooses the workspace — for personal use this is acceptable but worth knowing.
- **Customer data, private keys, internal docs** in the workspace are similarly exposed.
- **If this product is ever multi-user / productized**, the workspace policy needs hardening: a denylist for sensitive paths (`.env`, `*.pem`, `*.key`, `.git/`), max file size, optional secret scanning before send.

For v2 MVP (Costa-only, personal use, pointing at workspaces Costa already trusts to his other AI agents like Claude Code and Cursor), no extra guardrails are added.

## Validation criteria (this v2 is an experiment, not a finished product)

We're shipping v2 to answer one question: **does multi-agent iteration produce measurably better answers than a single agent with high reasoning effort?**

**Concrete metrics to log per iteration** (the viewer should expose a one-click "log decision outcome" button after each iteration finishes; writes to `.team-room/<topic>.decisions.jsonl`):

- `decision_changed`: did R2 change Costa's final decision? (yes/no/partial)
- `r2_novel_risks_count`: how many concrete risks/considerations did each R2 surface that weren't in either R1?
- `r2_false_claims_called`: did R2 identify a false/unsupported claim in the other's R1? (yes/no, per agent)
- `latency_seconds_total`: wall-clock from POST /prompt to status returning to idle
- `costa_would_have_caught`: subjective — would Costa have caught the issue on his own? (yes/no/maybe)

**Success looks like (after 2 weeks of real use):**
- `decision_changed = yes|partial` on ≥30% of iterations
- Median `r2_novel_risks_count` per agent ≥1
- `latency_seconds_total` p95 ≤120s
- `costa_would_have_caught = no` on ≥3 occasions (the leverage moments)
- Net qualitative read from Costa: "this is making my decisions better and I want to keep using it"

**Failure looks like (kill conditions, any of):**
- `decision_changed = no` on ≥80% of iterations after 10+ real uses
- Mean `r2_novel_risks_count` < 0.3 (R2 just rehashing R1)
- `latency_seconds_total` p95 > 240s (deliberation interrupts flow more than it helps)
- Sycophancy hit rate: ≥30% of R2 responses contain phrases like "I broadly agree" / "good point" without identifying false claims or material gaps (auto-detectable via regex on response content)
- Costa stops opening the team room within a week

**What we do on failure:** kill the product idea. Keep the v1 CLI tools (they're useful as a research-parallelism primitive). Don't invest in v2.5 Tauri wrap.

**What we do on failure:** kill the product idea. Keep the v1 CLI tools (they're useful as a research-parallelism primitive). Don't invest in v2.5 Tauri wrap.

## Non-goals (v2 deliberately omits)

- **Division-of-labor / sub-agent dispatch.** ("Claude, you do X; Codex, critique.") That's a v3 capability. v2 is pure deliberation.
- **Native app / Tauri wrapper.** Browser tab is enough until we validate the loop. Tauri wrap is v2.5.
- **Multi-topic concurrent loops.** One iteration per topic at a time. Lock the input during a round.
- **Convergence detection.** No "did they agree?" heuristic. Fixed 2 rounds, then stop and wait for Costa.
- **Cancel mid-round.** If Costa types again while a round is running, his new message queues until the round completes. No interruption.
- **Memory across topics.** Each topic is isolated. Switching topics in the viewer is switching to a different conversation.

## User journey (the golden path)

1. Costa double-clicks `Team Room` on his Desktop.
2. Browser opens to the topic picker. He clicks an existing topic or creates a new one (typed in the index page).
3. Topic viewer loads. Past transcript visible. **Input box at the bottom.**
4. Costa types: *"Should Vigil's policy engine use YAML or a DSL?"* Hits Send (or Cmd+Enter).
5. His message appears immediately (role: costa). Input locks. Two "thinking..." placeholders appear: one orange (Claude), one green (Codex).
6. ~10-60s later, Codex's first response appears (green placeholder → real text). ~5-30s after that, Claude's first response appears.
7. Round 2 starts automatically. Two new "thinking..." placeholders appear.
8. Claude's R2 lands first this time. Then Codex's R2.
9. Input unlocks. Costa reads. Either types again (new iteration) or moves on.

## Architecture

```
┌─────────────────────────┐
│  Browser (viewer.html)  │
│  ┌───────────────────┐  │
│  │  Transcript view  │  │  ← reads .team-room/<topic>.jsonl, polls /topics.json
│  │  (existing v1)    │  │
│  └───────────────────┘  │
│  ┌───────────────────┐  │
│  │   Input box       │  │  ← NEW: POSTs to /prompt
│  └───────────────────┘  │
└──────────┬──────────────┘
           │ HTTP
┌──────────▼──────────────┐
│  server.py              │
│  GET  /                 │  ← (existing) static files
│  GET  /topics.json      │  ← (existing) topic discovery
│  POST /prompt           │  ← NEW: kicks off orchestrate.py async
│  GET  /status/<topic>   │  ← NEW: returns "idle" or "round-N" so input UI can lock
└──────────┬──────────────┘
           │ subprocess
┌──────────▼──────────────┐
│  orchestrate.py         │  ← NEW: runs the 2-round loop
│   - appends costa msg   │
│   - spawns claude + codex in parallel (R1)
│   - waits for both
│   - spawns claude + codex with cross-context (R2)
│   - writes each response to JSONL on completion
└──────────┬──────────────┘
           │ subprocess
┌──────────▼──────────────┐  ┌──────────────────────┐
│  ask-claude.sh          │  │  ask-codex.sh        │
│  (NEW)                  │  │  (existing v1)       │
│  invokes claude --print │  │  invokes codex exec  │
└─────────────────────────┘  └──────────────────────┘
```

## Iteration loop semantics

**Fixed at 2 rounds per Costa-prompt.** Each round has Claude + Codex responding.

**Round 1 (cold takes, parallel):**
- Both agents receive: full transcript up to and including Costa's latest message.
- They respond in parallel. Whichever finishes first writes first.
- Each response is logged with `round: 1` in the JSONL metadata.

**Round 2 (cross-reaction, parallel):**
- Triggered as soon as *both* R1 responses are in.
- Each agent receives: full transcript including the other agent's R1.
- The wrapping prompt for R2 explicitly says: *"The other agent said X. Where do you agree? Where do you push back? Has your view changed?"*
- Both run in parallel.
- Each response is logged with `round: 2`.

**Stop:** After R2 both land, input unlocks. Costa drives the next iteration.

**Why parallel within a round, not sequential:** Sequential within a round (Claude first, then Codex sees Claude's R1) creates a first-mover bias. Parallel keeps the cold takes truly cold. The cross-reaction happens in R2 across rounds, not within R1.

**Why 2 rounds, not 3+:** First round = cold take. Second round = informed reaction. A third round risks the conversation degenerating into "I still agree with you, but more politely." If Costa wants more depth, he types another prompt to drive a fresh iteration with the accumulated context.

## Prompts (the load-bearing strings)

**R1 prompt to Claude/Codex:**
```
You are participating in a team room with another AI agent ({other_agent}).
The human leading the room is Costa. Your job is to give your honest first-take
response to his latest message. Don't reference the other agent's response —
they haven't responded yet. Be terse, evidence-first.

Full conversation so far:
{full_transcript}

Respond to Costa's most recent message.
```

**R2 prompt to Claude/Codex** (rewritten after Codex's R1 critique pointed out the v1 R2 prompt legitimized convergence by asking for agreement first):
```
You are participating in a team room with another AI agent ({other_agent}).
{other_agent} just answered the same question you did. Read their response carefully.

Your task — be ruthless. Identify, in this exact order:

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

Respond.
```

## JSONL schema extension

Existing v1 line:
```json
{"ts":"2026-05-22T00:30:00Z","role":"claude","model":"claude-opus-4-7","content":"..."}
```

v2 adds optional fields:
```json
{"ts":"...","role":"claude","model":"...","content":"...","round":1,"prompt_id":"abc123"}
```

- `round`: 1 or 2, only present for orchestrated responses (manual `log.sh` calls don't set it)
- `prompt_id`: a short ID linking all 5 messages (1 costa + 4 agent) from one iteration. Helps the viewer visually group them.

## Hard parts — decisions

### 1. How does ask-claude.sh avoid inheriting Costa's CLAUDE.md context?

**Decision:** Invoke `claude --print` with `cwd = <topic-workspace>` (e.g. `~/vigil`). The agent picks up the workspace's CLAUDE.md if any — for a Vigil deliberation, that's a *feature* (the agent should know Vigil's context). For neutral deliberation, point the workspace at a clean dir.

We also pass `--disallowedTools "Write Edit Bash NotebookEdit"` to keep the agent read-only. Memory accumulates per-cwd; that's fine — the team-room Claude builds its own memory of past discussions over time.

If we ever want a fully sterile Claude (no memory, no CLAUDE.md), we can switch to `--bare` mode with explicit `ANTHROPIC_API_KEY` — but that requires Costa to manage an API key separately and costs go off-subscription. Defer until needed.

### 2. How does the browser show "thinking" state?

**Decision:** Skeleton message bubbles with a typing-dots animation. When Costa hits Send:
- Costa's message renders immediately
- Two placeholder bubbles appear in the right colors (orange Claude, green Codex), each with "thinking…" + dots animation
- When R1 arrives for either agent, that placeholder's content fills in (smooth swap)
- New placeholders appear for R2 once both R1s are in
- When R2 lands, those fill in too. Input unlocks.

The viewer polls `/topics.json` (existing) for transcript changes and `/status/<topic>` (new) for in-flight state.

### 3. What if one model finishes way faster than the other?

**Decision:** Stream-as-ready. Each agent's response lands in JSONL the moment it's done. Viewer renders by timestamp. Sometimes Codex's R1 appears before Claude's R1; that's accurate.

Round 2 only starts when both R1s are in. So even if Codex is fast, it has to wait for Claude before getting the cross-reaction prompt. (Codex won't see its own R1 + Claude's R1 mid-round; it sees the full state only at round boundary.)

### 4. What if claude --print or codex exec hangs forever?

**Decision:** 5-minute timeout per agent per round. If a round times out, write a system message to JSONL ("Claude timed out after 5min — skipping its R2") and let the loop continue with whatever responses succeeded. Input unlocks. Costa decides what to do.

### 5. Where does orchestrate.py log its own errors?

**Decision:** stderr from orchestrate.py goes to a per-topic logfile at `.team-room/<topic>.log`. Costa can `tail -f` it if something's weird. Not exposed in the browser to keep the UI clean.

## File-by-file changes

| File | Status | What |
|---|---|---|
| `ask-claude.sh` | NEW | Mirror of ask-codex.sh: takes topic + prompt + asker_role, runs `claude --print`, appends both sides to JSONL with proper role tagging. Lives in repo root next to ask-codex.sh. |
| `orchestrate.py` | NEW | Async Python script. Inputs: topic + costa_message + prompt_id. Output: writes 4 agent responses (2 R1 + 2 R2) to the topic JSONL. Uses asyncio + subprocess.run for parallel agent calls. ~150 lines. |
| `server.py` | MODIFY | Add POST /prompt (kicks off orchestrate.py via subprocess, returns 202 with prompt_id). Add GET /status/<topic> (reads a simple state file at .team-room/<topic>.state). |
| `viewer.html` | MODIFY | Add input box at bottom (textarea + send button, Cmd+Enter to send). Add skeleton "thinking…" bubbles. Poll /status to lock/unlock input. Group messages by prompt_id with a subtle separator. |
| `index.html` | MODIFY | Add a "new topic" form (just a text input that takes you to the new topic's viewer). Currently you have to invoke a CLI command. |
| `README.md` | MODIFY | Document the new flow (browser-driven) as the primary path. CLI tools demoted to "advanced/scripting" section. |

## Interface contracts (binding for all implementers)

These are the contracts between `orchestrate.py`, `server.py`, and `viewer.html`. **Implementers MUST conform to these.** Any deviation requires updating this section and notifying the other implementers.

**Revision history:** v1 of this section had several P0 contradictions caught by Codex during the spec review (the team-room dogfooding itself). Race condition between concurrent POSTs, ambiguous "who appends Costa's message" (server vs orchestrator), no JSONL append locking, dual-mode ask-*.sh ambiguity, recovery protocol missing. Fixed throughout.

### Filesystem layout in `.team-room/`

```
.team-room/
  <topic>.jsonl              # append-only message log (existing)
  <topic>.state.json         # current iteration state (NEW)
  <topic>.workspace.json     # workspace config (NEW)
  <topic>.orchestrate.log    # orchestrator stderr (NEW)
  viewer.html, index.html, server.py   # served files (existing — copied here by start.sh)
```

### JSONL line schema (v2 — extends v1 additively)

```json
{
  "ts": "2026-05-22T01:02:03Z",
  "role": "claude" | "codex" | "costa" | "system",
  "model": "claude-opus-4-7" | "gpt-5.5" | "human" | "system",
  "content": "...",
  "round": 1 | 2,                 // OPTIONAL, only for orchestrated agent responses
  "prompt_id": "abc12345"          // OPTIONAL, present on all 5 messages from one iteration (costa + 4 agents)
}
```

Backward compat: v1 lines (no `round`, no `prompt_id`) MUST still render correctly in the viewer.

### State file `<topic>.state.json`

Written atomically: write to `<topic>.state.json.tmp` (same dir as the real file) then `os.replace()` (POSIX atomic rename on same filesystem). All readers/writers of this file MUST acquire `<topic>.state.lock` via `fcntl.flock(LOCK_EX)` before reading-then-writing, or `flock(LOCK_SH)` for pure reads. Single JSON object:

```json
{
  "status": "idle" | "round-1" | "round-2" | "crashed",
  "prompt_id": "abc12345" | null,
  "started_at": "2026-05-22T01:02:03Z" | null,
  "orchestrator_pid": 12345 | null,
  "claude_done": true | false,
  "codex_done": true | false,
  "last_error": null | "Claude timed out after 5min"
}
```

- `"idle"` = no iteration in flight; viewer unlocks input
- `"round-1"` = R1 in flight (parallel)
- `"round-2"` = R2 in flight (parallel)
- `"crashed"` = recovery state (see below)
- `claude_done`/`codex_done` let viewer remove the right "thinking" placeholder when that agent's response lands

**Recovery / stale-lock handling.** If state file has `status != "idle"` AND (orchestrator_pid is dead per `os.kill(pid, 0)` failing) AND (`started_at` is older than 10 minutes) → state is treated as `"crashed"`. The next `POST /prompt` performs recovery: write a system message to JSONL ("orchestrator crashed mid-round, resetting"), reset state to `idle`, proceed normally. Server includes this check in its lock-acquire-then-check sequence.

If the file doesn't exist, treat as `idle`.

### Workspace file `<topic>.workspace.json`

Set on topic creation; persists across iterations. Single JSON object:

```json
{
  "workspace": "/Users/costaxanthos/vigil",
  "created_at": "2026-05-22T00:00:00Z"
}
```

If missing, orchestrator uses `$HOME` as the default and writes the file with that value.

### Server endpoints (new)

**`POST /prompt`**
- Request body (JSON): `{"topic": "string", "content": "string", "workspace": "string | optional"}`
- Behavior — SYNCHRONOUSLY, under the state lock, in this order:
  1. Acquire `<topic>.state.lock` (LOCK_EX)
  2. Read current state; if non-idle AND not stale-crashed, release lock, return 409 with `{"error": "iteration in progress", "status": "round-N"}`
  3. If `workspace` arg provided and `<topic>.workspace.json` does not exist, create it now
  4. Generate fresh `prompt_id` (8 random hex chars)
  5. Append Costa's message to `<topic>.jsonl` (under JSONL append lock — see below)
  6. Spawn `orchestrate.py` as detached subprocess; capture its PID
  7. Write state file with `status: "round-1"`, `prompt_id`, `started_at`, `orchestrator_pid`, both `*_done: false`
  8. Release state lock
  9. Return 202 with `{"prompt_id": "..."}`
- Race safety: any second concurrent POST hits step 2's lock and sees `round-1`, returns 409 cleanly.

**`GET /status/<topic>`**
- Returns the state file contents, or `{"status": "idle", ...defaults}` if missing.
- `Cache-Control: no-store`.

**`POST /topic`** (small addition for index page new-topic form)
- Request body (JSON): `{"name": "string", "workspace": "string | optional"}`
- Creates an empty `<topic>.jsonl` and `<topic>.workspace.json`. Returns 201 with `{"name": "...", "url": "/viewer.html?topic=..."}`.
- Slug-validates the name (lowercase letters, digits, hyphens; 1-64 chars).

### JSONL append lock

ALL appends to `<topic>.jsonl` (whether from server, orchestrator, or `log.sh` / `ask-*.sh`) MUST acquire `<topic>.jsonl.lock` via `flock(LOCK_EX)` for the duration of the write. Python helpers can use `fcntl.flock`; bash helpers can use `flock -x` (macOS: install `util-linux` or use the `flock` package — verify in implementation; if not available, fall back to `lockfile` or atomic `mkdir` lockdir).

This prevents interleaved writes when both agents finish writing within the same millisecond. Each JSONL line must be complete and on its own line — atomic from the reader's perspective.

### Orchestrator CLI

`python3 orchestrate.py --topic <name> --prompt-id <id>`

The orchestrator reads workspace from `<topic>.workspace.json`. It does NOT need `--content` because Costa's message is already in the JSONL by the time the orchestrator starts (the server appended it). The orchestrator's job is purely the R1 + R2 loop.

Runs detached from the server (server uses `subprocess.Popen` with `start_new_session=True`). All output goes to `.team-room/<topic>.orchestrate.log`. The orchestrator's responsibilities:

1. State is already `round-1` when orchestrator starts (server set it)
2. Build R1 prompt from current transcript (read JSONL under shared lock)
3. Spawn `ask-claude.sh` and `ask-codex.sh` in parallel for R1, with cwd = workspace, transcript piped via stdin
4. As each finishes: (a) the helper script appended the agent's response to JSONL (under append lock), (b) orchestrator updates state to mark `claude_done` or `codex_done`
5. When both R1 done: under state lock, transition to `round-2`, reset `*_done` flags
6. Read latest transcript (now including both R1s), build R2 prompts
7. Spawn both agents in parallel for R2
8. When both R2 done: under state lock, transition to `idle`
9. On any error or timeout: write system message to JSONL with explanation, set state to `idle`, exit

Timeout: 5 minutes per agent per round. On timeout, kill the helper subprocess, write system message, mark state idle, exit.

### ask-claude.sh / ask-codex.sh contract

**Two modes, mutually exclusive.** The first positional argument determines mode:

**Mode A — Legacy positional (manual CLI driver, unchanged from v1):**
```
ask-claude.sh <topic> <prompt> [asker_role]
ask-codex.sh  <topic> <prompt> [asker_role]
```
Appends asker's message to JSONL (as `claude` or whoever the asker is), invokes the model, appends response. No `round` / `prompt_id` fields written.

**Mode B — Orchestrator flag-based (used by orchestrate.py):**
```
ask-claude.sh --orchestrate --topic <t> --prompt-id <id> --round <1|2> --cwd <workspace> < <prompt-via-stdin>
ask-codex.sh  --orchestrate --topic <t> --prompt-id <id> --round <1|2> --cwd <workspace> < <prompt-via-stdin>
```
- Reads the full prompt from stdin (multi-KB transcripts are fine)
- Invokes `claude --print --disallowedTools "Write Edit Bash NotebookEdit"` (or `codex exec --sandbox read-only -c model_reasoning_effort=high`) with cwd = workspace
- Appends ONLY the response to JSONL under the append lock, with `round` and `prompt_id` set
- Exits 0 on success, non-zero on failure with diagnostic to stderr
- Does NOT log the prompt — the orchestrator already has the full transcript in JSONL

Mode is selected by checking if the first arg is `--orchestrate`. If yes, parse flags. If no, parse as Mode A positional.

## Build estimate

~6-8 hours of focused work:
- `ask-claude.sh` + parallel-invocation testing: 30 min
- `orchestrate.py` with the loop, error handling, timeouts: 2-3 hours
- `server.py` endpoint additions: 1 hour
- `viewer.html` input + thinking-state + prompt grouping: 2-3 hours
- `index.html` new-topic form: 30 min
- End-to-end testing with a real iteration: 1 hour

## Open questions for Costa

None blocking — all the hard parts above have a committed decision. But two judgment calls worth flagging:

1. **The R2 prompt is opinionated.** It tells the agent to push back, not just agree. That's deliberate (avoid sycophancy) but it might create artificial conflict on questions where they actually agree. If R2 reads as forced disagreement on the first few real conversations, we tune the prompt.

2. **Group-by-prompt-id visual treatment.** Right now I'm planning a subtle horizontal-rule separator between iterations. Could also be a more pronounced "Round 1 / Round 2" header. Will get this right in implementation; flag if you want a specific style.

## After this ships

Things to validate over the first week of usage:
- Does R2 actually produce better answers than R1 alone, or does it tend to make them converge prematurely?
- Is 2 rounds the right number?
- Is the latency tolerable? (each round = max of Claude+Codex response time)
- Are the cold-take prompts producing genuinely cold takes, or does Codex still anchor on Claude's pre-existing context somehow?

If the loop genuinely produces better answers — that's the validation for building the Tauri wrap (v2.5) and considering productization.
