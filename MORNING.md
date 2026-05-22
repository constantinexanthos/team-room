# Morning briefing — team-room v3.4

Good morning. Here's what shipped while you slept, what to test first, and what to
push next.

## TL;DR

- **Live dialogue mode** is now the default. Up to 8 short turns of Claude ↔ Codex
  reacting to each other; either can declare `# CONVERGED` to end early.
- **Overnight queue + morning batch** lets you drop questions in
  `~/team-room-queue.md` before bed and wake up to deliberations.
- **Team Room is now a Claude Code skill** — any Claude Code session in any project
  can outsource a strategic call to the team room as a tool.
- **Stderr from agent CLIs surfaces** in `<topic>.orchestrate.log` instead of
  vanishing. Future failures will tell you why.

Server's running. Open `localhost:8765`.

## What you should actually do (in order)

1. **Refresh the browser** to pick up the new UI. The header should still show
   `● Claude  ● Codex` connected. The input dock hint now says "Enter to send".
2. **Send a real prompt** to a project — anything substantive enough to deliberate.
   You'll see the dialogue mode kick in:
   - First a Claude bubble lands (turn 1, ~120 words, short and conversational)
   - Then a Codex bubble (turn 2, reacting to what Claude just said)
   - Then Claude again (turn 3, reacting to Codex's reaction)
   - ... up to 8 turns or until one writes `# CONVERGED <one-line summary>`
   - The input dock shows `Live · Turn N/M · Claude thinking…` so you know exactly
     where you are
3. **Compare the feel** to the old R1/R2 essays. It should read like two minds
   thinking together. If it still feels like sequential essays, the prompt design
   needs another pass — tell me and I'll tune.

## The live dialogue change — what I actually built

**Before (R1/R2):** Claude writes a long structured essay. Codex writes one too.
Then each writes a critique of the other's essay using a forced "find the strongest
false claim" template. Felt like a grading exercise.

**After (dialogue):** Claude opens with ~120 words. Codex sees it and reacts in ~120
words. Claude sees Codex's reaction and reacts again. Each turn cites what the other
just said (build / push back / sharpen / converge). Either can declare convergence
once they actually agree, with evidence.

Implementation:
- `orchestrate.py` gains `run_dialogue()` — micro-turn loop, alternating Claude/Codex,
  caps at 8 turns, regex-detects `# CONVERGED` marker
- `DIALOGUE_OPENING_PROMPT` (turn 1) and `DIALOGUE_TURN_PROMPT` (subsequent turns)
  are the load-bearing strings. Both cap responses at 150 words and require reacting
  to the previous turn specifically. Anti-sycophancy is preserved but no longer a
  ceremony — agents can converge with evidence instead of always finding a fault
- `server.py` POST /prompt accepts `mode: 'dialogue' | 'rounds'`. Default is dialogue.
  Old rounds mode is still available if you want structured falsification on a
  specific question
- React UI handles `status: 'dialogue'` with a single in-flight skeleton for the
  current agent (not the old pair), and the input dock shows live turn counter

**The single biggest risk** in dialogue mode: convergence might be too easy. If the
opening prompt makes them too agreeable, you'll see 2-3 turns of "I agree, building
on that..." then convergence. Watch for this on your first 3-5 real prompts. If it
happens, the fix is one prompt edit (make the opening more adversarial). I'll tune
based on what you see.

## Overnight queue — how to use it

1. Drop questions in `~/team-room-queue.md` (any text editor) — one per markdown bullet:
   ```
   - [ ] Should I prioritize Sub-project D Policy or F Launch first?
   - [ ] [vigil] How should the migration handle in-flight transactions?
   ```
   Optional `[project-id]` prefix selects which project to log against.
   Defaults to your most-recently-opened.

2. Install the cron entry (one-time, run this once when you wake up):
   ```bash
   (crontab -l 2>/dev/null; echo "*/15 0-7 * * * /Users/costaxanthos/team-room/scripts/morning-batch.sh >> /tmp/morning-batch.log 2>&1") | crontab -
   ```
   This runs the batch every 15 minutes between midnight and 7am.
   Edit the hour window to suit your sleep schedule.

3. Before bed: ensure your laptop stays awake. Run:
   ```bash
   caffeinate -i ./start.sh
   ```
   instead of plain `./start.sh`. The `-i` prevents idle sleep until you Ctrl+C.

4. In the morning: questions in the queue are marked `[x]` with the topic ID
   appended as an HTML comment. Each question has its own topic in the team room
   you can open and read. The morning Cowork briefing will also surface them
   (let me know if you want me to wire that integration explicitly).

## Team Room as a Claude Code skill — install once

`scripts/skill/team-room/SKILL.md` ships as part of this repo. To make it
available to every Claude Code session you open (in any project, anywhere):

```bash
mkdir -p ~/.claude/skills
ln -sfn ~/team-room/scripts/skill/team-room ~/.claude/skills/team-room
```

After install, any Claude Code I run for you can autonomously ask the team room
for a second opinion when it hits a strategic call. The skill description tells
me when to invoke it (architecture choices, prioritization, naming, trade-offs)
and when NOT to (mechanical code, obvious calls). Returns the full transcript so
I can cite specific agents back to you.

This is the "two consultants" pattern you asked for, packaged so it works in every
terminal you open. If you want to distribute this so other devs can have Claude +
Codex in their workflow, the skill IS the distribution — they clone the repo and
run the same `ln -sfn`.

## Other small things that landed

- Stderr from `claude --print` and `codex exec` now surface in
  `<topic>.orchestrate.log` when an agent exits non-zero or returns empty (was
  silently `2>/dev/null` — could see "exit 1" but never why)
- System messages (timeouts, crashes, convergence markers) carry `prompt_id`
  and `round`/`turn` so they group with the iteration in the viewer instead
  of floating orphaned
- Agent timeout 5min → 8min (Codex first-run + MCP warm-up + high effort
  sometimes exceeded 5)
- `_default_state()` now includes the new dialogue fields so state recovery
  doesn't strip them

## What's NOT done (call your shot for next session)

- **The morning Cowork briefing doesn't yet incorporate team-room queue
  results.** Easy add — update the prompt at
  `~/vigil/docs/automation/cowork-preflight-prompt.md` to read
  `~/team-room/.team-room/morning-*.jsonl` and summarize the deliberations.
  ~10 min when you give the word.
- **Project settings modal** still alerts "coming soon" instead of letting you
  rename / change workspace / edit github URL. Endpoints exist; just need UI.
- **Trash icon for projects + topics in the sidebar** — DELETE endpoints exist
  (you can also right now manually curl `DELETE /projects/<id>` or
  `DELETE /topics/<id>`)
- **Markdown rendering inside message bubbles** — currently plaintext `<pre>`.
  Three-line add with `marked` or similar.
- **Claude logo** — still my simplified sunburst (anti-aliases at 12px; the
  real path turned to mud at sidebar size). Paste the SVG you want and I'll
  swap it in.

## How to verify everything works right now

```bash
# 1. Health probe — should show both CLIs reachable
curl -s localhost:8765/health | python3 -m json.tool

# 2. List projects — should show the 3 you have (no Legacy)
curl -s localhost:8765/projects | python3 -m json.tool

# 3. Drop a test question + drain the queue manually
echo "- [ ] Should we add markdown rendering to message bubbles next?" \
  >> ~/team-room-queue.md
~/team-room/scripts/morning-batch.sh

# 4. Read the deliberation
ls ~/team-room/.team-room/morning-*.jsonl | head -1 | xargs cat | \
  python3 -c "import json, sys; [print('---', m.get('role',''),
  m.get('round','-'), '---\n', m.get('content','')[:300], '\n')
  for line in sys.stdin if line.strip() for m in [json.loads(line)]]"
```

If anything 4xx/5xx's or returns "team-room server not reachable", check
`tail -20 /tmp/team-room-v34.log` and tell me.

## Final state of the repo

Branch: `main`, head: see `git log --oneline -5`.
Build artifacts: React app under `web/dist/`, staged into `.team-room/`.
Tests: still none (deferred per the prior call).

The product is genuinely better than 6 hours ago. Live dialogue is the closest
we've gotten to the "two minds thinking together" feel you asked for. The
overnight queue is the closest we've gotten to "while I sleep, work happens."

Next session: tune what's rough, then either ship the morning-briefing
integration or the project settings modal — your call. Sleep well.
