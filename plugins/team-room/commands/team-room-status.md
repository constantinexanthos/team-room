---
description: Check the status of a team-room iteration (in-flight, idle, crashed)
argument-hint: '<topic-id>'
allowed-tools: mcp__team-room__team_room.status
---

The user wants to check the status of a specific team-room topic.

Topic id (lowercase + hyphens):
`$ARGUMENTS`

Steps:
1. Take the topic id from `$ARGUMENTS`. If empty, ask the user which topic.
2. Call `team_room.status` with that topic id.
3. Present the result naturally:
   - `idle` — no iteration in flight, you can fire a new one
   - `dialogue` — live dialogue running; surface `turn N/M (current_agent thinking…)` and the prompt_id
   - `round-1` / `round-2` — legacy rounds mode mid-iteration
   - `crashed` — orchestrator died; the next /team-room call will auto-recover
4. If `last_error` is non-null, surface it — usually a timeout or auth failure.
