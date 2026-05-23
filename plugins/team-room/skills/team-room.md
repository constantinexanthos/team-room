---
name: team-room
description: Use when the user asks a strategic question that benefits from cross-model deliberation between Claude and Codex — architecture choices, prioritization, product trade-offs, naming, "should we X or Y", or anything that benefits from BOTH a code/infra lens (Codex) AND a UX/product/safety lens (Claude). Triggers an MCP-backed two-model working session and returns a structured joint read.
---

# Team Room

Team Room puts Claude (Opus 4.7) and Codex (gpt-5.5) in a structured working session — they address each other by name, build on each other's frames, and converge on one joint read for the user. The collaboration produces answers neither model would give alone, especially the "reshape" move where the second agent collapses the first's framing into something sharper.

## When to use

Call `mcp__plugin_team-room_team-room__team_room_ask` when the user's question has any of these shapes:

- **Strategic call:** "should we X or Y", "what's the best approach for…", "prioritize between A/B/C"
- **Architecture choice:** "Postgres vs DynamoDB", "monorepo or split", "client-side or server-side"
- **Naming / API design:** "what should we call this", "right shape for this endpoint"
- **Product trade-off:** "ship now or polish", "v0.2 priority", "what's the moat"
- **Cross-domain question:** anything that benefits from BOTH a code/infra lens (Codex) AND a UX/product/safety lens (Claude)

Do NOT call team-room for:
- Single-domain tactical questions ("fix this bug", "write a test")
- Questions where one specific lens clearly dominates ("debug this stack trace" = just answer)
- Time-sensitive answers where you already know the right answer

## How to call

```ts
mcp__plugin_team-room_team-room__team_room_ask({
  question: "<the user's question, framed precisely>",
  mode: "dialogue",   // default — collaborative working session
  wait: true,         // block until done; returns full transcript + brief
  timeout_s: 300,     // 5 min headroom; sessions usually 30-90s
})
```

Default `mode: "dialogue"` 99% of the time. Use `mode: "rounds"` ONLY when the user explicitly asks for adversarial stress-testing ("have them critique each other").

The response contains:
- `outcome`: `converged` | `forked` | `timed-out` | `failed`
- `final_brief`: structured artifact with `joint_read` (converged) or `fork` (forked)
- `messages`: full transcript for inspection

## How to render the result

The deliberation can be deep; the surfaced answer must be tight. Two separate jobs:

**READING (mandatory):** absorb the full `messages` and `final_brief`. The deliberation, dissent, and lens-asymmetries are context for YOUR follow-up thinking. If team-room shifted your view, say so. You are the senior who heard the report, not an echo of the punchline.

**RENDERING (minimal):** the user sees the tool-call widget collapsed by default and can expand to see the transcript. Your text response is the headline, not the article.

- `converged`: QUOTE `final_brief.joint_read` verbatim. One short lead-in is fine ("Team Room's read:"). Don't paraphrase, don't expand, don't narrate the deliberation, don't summarize per turn.
- `forked`: present `final_brief.fork` bullets concisely; ask the user how they want to resolve.
- `timed-out`: one line ("Team Room timed out at turn N — partial in the expanded view").
- `failed`: one line with `final_brief.error`.

OK to add ONE sentence of synthesis if the deliberation surfaced something load-bearing the joint_read elided ("Codex flagged X mid-dialogue — worth knowing if you go that way"). Don't do this performatively.

Do NOT paste `messages`, `final_brief` metadata, or `session` info into your text response.

## Examples

**Should trigger:**
- "Should we ship the auth refactor as one PR or split it into three?" → call team_room_ask
- "What's the right caching strategy for our search results?" → call team_room_ask
- "Postgres or SQLite for this side project?" → call team_room_ask
- "What's the v0.3 priority for [project]?" → call team_room_ask
- "Have Claude and Codex argue about monorepo vs polyrepo for us" → call with `mode: "rounds"`

**Should NOT trigger:**
- "Fix the off-by-one bug in `parseRange`" → just fix it
- "Write a unit test for `formatTimestamp`" → just write it
- "Explain how this regex works" → just explain
- "What does this error mean?" → just answer
