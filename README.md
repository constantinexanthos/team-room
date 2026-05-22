# Team Room

A two-mind deliberation room. Claude (Anthropic) and Codex (OpenAI) collaborate on your question over short turns, address each other by name, and arrive at an answer together. Use it three ways:

- **As a Claude Code plugin** (`/team-room "..."`) — agent-callable from any session via the bundled MCP server
- **As a shell tool** (`scripts/ask-team-room.sh`) — for cron, scripts, other agents
- **As a browser app** (`./start.sh`) — chat-style UI with projects, topics, live streaming

## Why

Same-model self-consensus drifts toward agreement. A second voice from a different lab catches things the first model would systematically miss. The current dialogue mode frames the agents as *colleagues building an answer together*, not graders critiquing each other's essays.

## Install as a Claude Code plugin (recommended)

If you have Claude Code installed:

```
/plugin marketplace add costaxanthos/team-room
/plugin install team-room@team-room
/reload-plugins
```

After install, in any Claude Code session:

- `/team-room "your question"` — opens a working session, returns the dialogue
- `/team-room:rooms` — list recent topics
- `/team-room:status <topic>` — check an in-flight session
- The MCP tool `team_room.ask` is also callable directly by other agents — that's the agent-orchestration interface

The plugin bundles an MCP server (stdio, no daemon) that Claude Code launches on demand. State (transcripts) lives in `~/.team-room/` by default — override with `TEAM_ROOM_DIR=...`.

**Requirements:** `claude` CLI authed (Anthropic Max or API key), `codex` CLI authed (ChatGPT Plus/Pro or OpenAI API key).

## Quickstart for the browser app

One-time install:

```bash
git clone https://github.com/constantinexanthos/team-room.git ~/team-room
cd ~/team-room
./install-desktop.sh
```

That drops a `Team Room` launcher on your Desktop. **Double-click it** any time:

1. Terminal opens, server starts on `localhost:8765`
2. Browser pops to the topic picker (all topics ranked by recency, with last-spoke role)
3. Click a topic → enter the transcript viewer

Close the Terminal window to stop. Re-open by double-clicking again.

## Driving the conversation

In Claude Code (or any terminal), three commands:

```bash
# You/Claude proposes something into the room
./log.sh sub-project-e claude "Draft spec for the Overview tab: ..."

# Claude asks Codex for an adversarial read (high reasoning effort by default)
./ask-codex.sh sub-project-e "Critique this spec. Find what's missing."

# You weigh in directly
./log.sh sub-project-e costa "Pick option B, skip the polling refresh."
```

The viewer updates within ~1.5s. Color stripes on the left mark who's talking: orange = Claude, green = Codex, blue = you, purple = system.

## Files

| File | Purpose |
|---|---|
| `Team Room.command` | macOS double-click launcher (symlinked to Desktop by installer) |
| `install-desktop.sh` | One-time: drops the launcher symlink on your Desktop |
| `start.sh` | Boots the server + opens the browser |
| `server.py` | Tiny static server with `/topics.json` auto-discovery |
| `index.html` | Topic picker landing page |
| `viewer.html` | Single-page transcript viewer (polls JSONL every 1.5s) |
| `ask-codex.sh` | Send prompt to Codex, append both sides to a topic |
| `log.sh` | Append an arbitrary message (claude / codex / costa / system) |

## Transcripts

JSONL at `.team-room/<topic>.jsonl` (gitignored). One line per message:

```json
{"ts":"2026-05-22T00:30:00Z","role":"claude","model":"claude-opus-4-7","content":"..."}
```

Topics are arbitrary slug strings — use one per decision (e.g. `sub-project-e`, `policy-engine-design`, `launch-positioning`). Old topics stay in the picker; nothing is ever deleted automatically.

Override the room dir with `TEAM_ROOM_DIR=/some/path` if you want transcripts somewhere else.

## Requirements

- macOS (`open` and `.command` handling are Darwin-specific; would need small tweaks for Linux)
- Python 3.10+
- [Codex CLI](https://github.com/openai/codex) authed via `codex login` (ChatGPT Plus or Pro)
- A Claude session (Claude Code is the natural fit)

## What v1 deliberately doesn't do

- **No write path from the browser.** Interventions happen in the terminal — keeps the security surface tiny.
- **No persistence beyond JSONL.** No DB, no search, no replay UI.
- **No autonomous loop.** Claude prompts Codex when there's a strategic call to make; Codex doesn't poll for new messages.
- **No "type into the team room itself" input.** You drive via the terminal; the viewer is read-only. Lifting this is the natural v2.

If any of those become friction, lift the limit. Don't pre-build.

## License

MIT.
