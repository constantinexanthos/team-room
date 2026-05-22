# Team Room v3 — Projects, Sidebar, Clean Dialogue

Date: 2026-05-22
Status: In progress

## What v3 unlocks

v2 made the team room interactive (Costa types, both agents iterate). v3 makes it a **proper LLM-app surface**: projects organize topics, github repos bind to projects, sidebar gives ChatGPT/Claude.ai-style navigation, and the message dialogue reads like two minds thinking together rather than a structured ceremony.

This is a UI rewrite. The v2 backend (`server.py`, `orchestrate.py`, `ask-*.sh`) stays. The frontend (`viewer.html`, `index.html`) becomes legacy; a React app replaces it.

## Goals

1. Land on a **project picker** (à la Conductor): Open project / Open GitHub project / Quick start + Recents
2. Once a project is open, **sidebar** shows projects → expandable to their topics
3. **Topic view** is a clean chronological transcript — no "R1/R2" labels, no ceremony
4. Each project optionally **bound to a github repo** (auto-detected from workspace git remote)
5. Existing v2 topics get **migrated** under a "Legacy" project (no manual work)

## Non-goals (v3 deliberately omits)

- **Native Tauri wrap.** Browser only for v3. Tauri = v3.5 if the surface validates.
- **Auto-cloning GitHub repos.** Open GitHub project = paste URL + manually pick existing local clone. Auto-clone deferred.
- **Multi-project concurrent iterations.** Same lock as v2 — one topic at a time per project.
- **Sub-agent dispatch in the room.** Still v4 territory.
- **PRs / issues / commits panel inside a project.** GitHub binding is just a URL + link for v3.0.
- **Auth / multi-user.** Single operator (Costa), single machine, no auth layer.

## Data model

New entity: **Project**. Stored at `.team-room/<project_id>.project.json`:

```json
{
  "id": "vigil",
  "name": "Vigil",
  "workspace": "/Users/costaxanthos/vigil",
  "github_url": "https://github.com/constantinexanthos/vigil",
  "created_at": "2026-05-22T03:00:00Z",
  "last_opened_at": "2026-05-22T03:00:00Z"
}
```

- `id` is a stable slug (`^[a-z0-9-]{1,64}$`). Derived from workspace dir basename by default.
- `name` is the human label (mutable).
- `workspace` is the read-only context dir for both agents (same as v2 topic-workspace).
- `github_url` is auto-detected from `git -C <workspace> remote get-url origin` if available; nullable.
- `last_opened_at` powers Recents ordering.

**Topics** gain a `project_id` field:

```json
{ "id": "launch-prep", "project_id": "vigil", "created_at": "..." }
```

Stored at `.team-room/<topic>.topic.json`. (Currently topics have implicit identity = filename of `<topic>.jsonl`; v3 makes this explicit so we can attach project_id and other metadata.)

**Backward compat:** topics with no `.topic.json` and no project assignment get bundled under the `legacy` project on first v3 boot.

## API additions (server.py)

| Method | Path | Body | Returns |
|---|---|---|---|
| `GET` | `/projects` | — | `[{id, name, workspace, github_url, last_opened_at, topic_count}, ...]` ordered by `last_opened_at desc` |
| `POST` | `/projects` | `{workspace}` (required) or `{name, workspace, github_url}` | 201 with full project; auto-detects github_url from workspace's git remote if not provided |
| `GET` | `/projects/:id` | — | full project + list of topics under it |
| `PATCH` | `/projects/:id` | partial fields | updated project |
| `DELETE` | `/projects/:id` | — | 204; topics under it become orphaned (we don't delete JSONLs) |
| `POST` | `/projects/:id/open` | — | bumps `last_opened_at`, returns project |
| `GET` | `/recents` | — | top 10 projects by `last_opened_at` |
| `POST` | `/topic` (extended) | `{name, project_id, workspace?}` | as before; workspace defaults to project's workspace |
| `GET` | `/topics?project_id=...` | — | topics filtered by project |

Existing `/prompt`, `/status/<topic>`, `/topics.json` unchanged.

## React app structure

Built with Vite + React 18 + Tailwind + shadcn/ui. 21st.dev MCP used for hero components (sidebar tree, message bubble, project card).

```
web/
├── package.json
├── vite.config.ts
├── tailwind.config.ts
├── postcss.config.js
├── tsconfig.json
├── index.html                 ← Vite entry; loads /assets/index-*.js
├── src/
│   ├── main.tsx
│   ├── App.tsx                ← top-level router (picker vs project view)
│   ├── api/
│   │   ├── client.ts          ← fetch helpers, types
│   │   └── types.ts           ← Project, Topic, Message
│   ├── components/
│   │   ├── ProjectPicker.tsx  ← landing page (Conductor-style)
│   │   ├── Sidebar.tsx        ← projects tree
│   │   ├── ProjectHeader.tsx  ← top bar of project view
│   │   ├── TopicView.tsx      ← active topic transcript + input dock
│   │   ├── MessageBubble.tsx  ← single message (role-tinted)
│   │   ├── InputDock.tsx      ← textarea + send
│   │   ├── ThinkingBubble.tsx ← skeleton placeholder
│   │   └── ui/                ← shadcn primitives
│   ├── hooks/
│   │   ├── useTopics.ts       ← polls /topics?project_id=
│   │   ├── useTranscript.ts   ← polls topic JSONL
│   │   └── useStatus.ts       ← polls /status/<topic>
│   └── styles/
│       └── globals.css         ← tailwind base + custom CSS variables
└── dist/                       ← built bundle, served by server.py
```

Build pipeline: `npm run build` produces `web/dist/`. `start.sh` copies dist contents to `.team-room/` alongside `server.py`. Browser loads from `localhost:8765/index.html` which is the React app.

## UI sketch (detailed)

### Project picker (no project selected)

```
┌──────────────────────────────────────────────────┐
│                                                  │
│            TEAM ROOM                             │
│                                                  │
│   ┌────────────────────────────────────────┐     │
│   │ 📁  Open project                       │     │
│   ├────────────────────────────────────────┤     │
│   │ 🌐  Open GitHub project                │     │
│   ├────────────────────────────────────────┤     │
│   │ ➕  Quick start                        │     │
│   └────────────────────────────────────────┘     │
│                                                  │
│   RECENTS                                        │
│   📁 ~/vigil           Vigil                     │
│   📁 ~/team-room       Team Room                 │
│   📁 ~/conductor       Conductor                 │
│                                                  │
└──────────────────────────────────────────────────┘
```

### Project view (project selected)

```
┌────────────────────┬─────────────────────────────────────────┐
│ ← Projects         │  vigil-launch-prep                     ⋯ │
│                    │  Vigil · gh/vigil · ~/vigil              │
│ ▼ Vigil            ├─────────────────────────────────────────┤
│   ● launch-prep    │                                          │
│   ○ policy-design  │  ─── exchange a3f12 ───                  │
│   ○ sub-project-e  │                                          │
│ ▼ Team Room        │  COSTA  10:32                            │
│   ○ v2-architect   │  Should I prioritize v0.1.0e or F?       │
│ ▼ Legacy           │                                          │
│   ○ smoke-test     │  CLAUDE  10:32                           │
│   ○ market-scan    │  First take: …                           │
│   ○ ask-claude-…   │                                          │
│                    │  CODEX  10:32                            │
│ + New topic        │  First take: …                           │
│ + New project      │                                          │
│                    │  CLAUDE  10:33                           │
│ 7 topics, 3 proj   │  Reading Codex's frame: where I push… │
│                    │                                          │
│                    │  CODEX  10:33                            │
│                    │  On Claude's claim: the weak point is…  │
│                    │                                          │
│                    │  ┌────────────────────────────────────┐  │
│                    │  │ Type a message to the room…        │  │
│                    │  │                            [Send] │  │
│                    │  └────────────────────────────────────┘  │
└────────────────────┴─────────────────────────────────────────┘
```

Notes:
- `●` = active topic, `○` = inactive
- Project header `⋯` opens settings modal (rename, change workspace, edit github URL, delete)
- No "R1"/"R2" labels in message meta
- Iteration separators stay (subtle horizontal rule with short id) for navigation
- Skeleton "thinking" bubbles still show during in-flight rounds

## Dialogue treatment (the "thinking together" feel)

The orchestrator still runs R1 → R2; the JSONL still stores `round` per message. The change is purely visual:

- Meta line shows: `ROLE   TIME` only (no `R1`/`R2`)
- Iteration separator: same subtle hr with short prompt_id (label says `exchange` not `iteration` — feels less mechanical)
- During in-flight rounds: skeleton "thinking…" bubbles per agent. When R2 starts (after both R1s lend), new skeletons appear naturally. The user sees a continuous flow of bubbles appearing, not two distinct rounds.

The visual effect: it looks like Claude and Codex are alternately speaking, sometimes addressing each other (which is what R2 actually does). Reads as collaboration, not ceremony.

## Migration (existing topics)

On first v3 boot:
1. Check if any `.project.json` files exist
2. If none: create `legacy.project.json` with name "Legacy", workspace = `$HOME`
3. For every `<topic>.jsonl` without a `<topic>.topic.json`: create one with `project_id: "legacy"`
4. Done. Costa can rename Legacy, split topics into real projects, etc. from the UI

## Server changes — file map

| File | Change |
|---|---|
| `server.py` | Add all `/projects*` endpoints; extend `/topic` to accept project_id; add migration helper invoked at startup |
| `start.sh` | Build the React app (`npm --prefix web run build` || dev mode skip), copy `web/dist/*` into `.team-room/` |
| Existing endpoints | Unchanged. v2 client can still hit them if needed. |
| `viewer.html`, `index.html` | Stay in repo as legacy fallback. Not linked from the new app. |

## Build sequence

1. ✅ Spec written
2. Vite/React/Tailwind/shadcn scaffold in `web/`
3. Server.py: `/projects` CRUD + migration + git remote auto-detect
4. ProjectPicker.tsx (uses 21st.dev components)
5. Sidebar.tsx + project-tree
6. TopicView.tsx + MessageBubble.tsx + InputDock.tsx + ThinkingBubble.tsx
7. Project settings modal
8. start.sh builds + stages React app
9. E2E test in browser
10. Commit, push

## What "done" looks like

- Open Desktop launcher → browser opens to project picker
- Click "Open project" → folder picker → pick `~/vigil` → project created, github URL auto-detected
- Sidebar shows Vigil project + Legacy project (with all existing topics)
- Click a topic → transcript view with clean dialogue
- Type a prompt → R1 + R2 fire as before but UI shows them as natural conversation
- Status pill, skeleton bubbles, prompt_id grouping all work
- Costa says "yeah this is what I wanted"

## Risks

- **shadcn install requires npx + node** — Costa has these (he's running Node ecosystem already for Vigil's Tauri app)
- **First-run npm install is slow** — instructions in README cover this; `start.sh` checks and prompts
- **React introduces a build step** — yes, intentional. The team-room is becoming a real app.
- **GitHub URL auto-detect could fail silently** for workspaces that aren't git repos — we just leave the field null and let the user fill in via the project settings modal
