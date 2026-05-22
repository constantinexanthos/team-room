# Team Room

Multi-agent chat transcript: **Claude** (via Claude Code in your terminal) and **Codex** (via the `codex` CLI) deliberate in a shared JSONL while you watch in a browser tab.

## Why

Same-model self-consensus drifts toward agreement. A second voice from a different model lab catches things the first model misses. This makes that loop visible — you watch the discussion live instead of being the message bus between two agents.

## Quickstart

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
