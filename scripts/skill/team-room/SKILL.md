---
name: team-room
description: Outsource a strategic question to a live Claude+Codex deliberation. Use when the current task has a non-obvious judgment call (architecture, prioritization, naming, trade-offs) and a cross-model second opinion would beat a unilateral guess. Returns the full transcript so you can cite specific points back to the human.
---

# Team Room — Cross-model deliberation

You have access to a local Team Room server that runs Claude + Codex in a
live micro-turn dialogue. Use it as two on-call consultants when:

- You hit a real strategic judgment call and you want a second opinion before
  proceeding (architectural choice, prioritization, trade-off, naming)
- The question is hard enough that a unilateral Claude answer might miss
  something a cross-model voice would catch
- You're about to make a recommendation to the human and want it pressure-tested

**Do NOT use the team room for:**
- Mechanical tasks (write this code, run these tests, format this file)
- Questions where the answer is obvious from reading the code
- Anything that needs a human's specific preference (style, vibe, brand voice)

## How to invoke

The team-room ships with a CLI helper at `~/team-room/scripts/ask-team-room.sh`.
Call it from Bash and read the stdout:

```bash
~/team-room/scripts/ask-team-room.sh \
  --project <project-id> \
  <topic-slug> \
  "Your strategic question, framed precisely. Include constraints. State what
   you would otherwise default to so the agents can pressure-test it."
```

The helper:
1. Creates the topic if missing (under the project you specify)
2. Waits for any in-flight iteration to finish first
3. POSTs the prompt, polls until the dialogue completes (~30-120s typical)
4. Prints the full transcript (Costa's question + alternating Claude/Codex turns)

Topic slug should describe the question (`policy-vs-launch`, `naming-the-mark`).
Re-use a topic to continue the same thread; pick a new slug for a fresh decision.

## Preconditions

- Team Room server must be running at `localhost:8765` (Costa runs `./start.sh`
  in `~/team-room/`). If `curl -sS localhost:8765/health` fails, the room
  isn't up and you should fall back to asking the human directly.
- A project must exist or be creatable. List with
  `curl -sS localhost:8765/projects | python3 -m json.tool`.

## Reading the output

The deliberation comes back as:

```
EXCHANGE <prompt_id>

YOU [timestamp]
<the question you sent>

CLAUDE [timestamp]
<first turn — opening position>

CODEX [timestamp]
<reaction to Claude>

CLAUDE [timestamp]
<reaction to Codex>

... up to 8 turns or until one of them writes "# CONVERGED" + summary
```

When you cite the deliberation back to the human, name the agents explicitly
("Codex pushed back on the timeout, arguing X; Claude conceded but added Y").
That's the value — two named voices, not a synthesized mush.

## Cost / latency

Each call burns Costa's Claude Max subscription + his Codex Pro subscription
(both at high reasoning effort). Expect 30-120s per iteration; up to 8 minutes
in pathological cases. Don't fire this for trivia.

## Install (one-time, per machine)

This skill file lives at `~/team-room/scripts/skill/team-room/SKILL.md` in the
repo. Symlink it into your Claude Code skills directory:

```bash
mkdir -p ~/.claude/skills
ln -sfn ~/team-room/scripts/skill/team-room ~/.claude/skills/team-room
```

After install, any Claude Code session can invoke `/team-room` or simply read
this skill when the description matches the situation at hand.
