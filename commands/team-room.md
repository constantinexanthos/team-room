---
description: Open a working session — Claude and Codex deliberate on your question together over multiple short turns, then return what they landed on.
argument-hint: '"your question" [--project <id>] [--mode dialogue|rounds]'
allowed-tools: mcp__team-room__team_room.ask
---

The user wants to open a team-room working session: Claude and Codex (your colleague
from a different lab) think together on the question below, then return what they landed
on. This is for strategic / cross-model deliberation — not quick code review.

Raw slash-command arguments:
`$ARGUMENTS`

Steps:
1. Parse `$ARGUMENTS`. The question is the unquoted free-form text. Optional flags:
   - `--project <id>` — attach the session to an existing team-room project
   - `--mode dialogue|rounds` — default `dialogue`. `rounds` is legacy R1/R2.
   - `--topic <id>` — explicit topic id (lowercase + hyphens). Otherwise auto-derived.
   - `--no-wait` — fire and return a session handle immediately instead of waiting.

2. Call the `team_room.ask` MCP tool with the parsed arguments.

3. When the tool returns, present the result naturally:
   - If `status: complete`, render each message in order (you, claude, codex, system).
     Use the role name + the message body. Don't editorialize — Costa wants to read
     what the agents actually said.
   - If `status: in_flight` (because `--no-wait`), tell Costa the session handle
     (topic + prompt_id) and that he can poll with `/team-room:status <topic>`.
   - If `status: timeout`, tell Costa the session is still running and how to check on it.
   - If the tool returns an `error` field, surface the error message — usually the cause
     is missing project, invalid topic id, or another iteration in flight.

4. Don't add your own commentary or synthesis on top of the dialogue. The agents'
   conversation IS the answer. If Costa wants you to act on what they said, he'll ask.
