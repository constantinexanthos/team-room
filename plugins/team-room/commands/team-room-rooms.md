---
description: List recent team-room topics — useful to find an existing room to continue.
argument-hint: '[--limit N]'
allowed-tools: mcp__team-room__team_room_recent
---

The user wants to see recent team-room topics.

Raw arguments:
`$ARGUMENTS`

Steps:
1. Parse `$ARGUMENTS` for an optional `--limit N` flag (default 10).
2. Call `team_room_recent` with that limit.
3. Format the result as a simple list: topic id + last activity (relative time).
4. Note: continuing a topic just means passing `--topic <id>` to `/team-room`.
