# Agents Management and Selection UI (`/agents`)

## Problem

Today, Clawhouse allows custom agents to be registered in the backend (`/api/agents`) with workspace folders provisioned on disk (`AGENTS.md`, `SOUL.md`, `CONTEXT.md`) and addressed in chat via `@agent_name` or `?agent=<name>`. However, the UI has no dedicated agents overview or management screen. Workspace operators and end users must use the cluttered `/new` (New session) screen—which mixes session creation with inline custom agent forms and deletion lists—or memorize agent handles to type `@mentions` directly in chat without knowing which agents exist, what model they run on, or what they were most recently doing.

Reference: OpenClaw's `/agents` screen (`docs/openclaw-ui/SHOTS.md` §9-10) provides a dedicated `/agents` route with header "Agents", subtitle "Who is on your team and what they are doing", actions "Manage agents" and "New agent", and a card grid showing avatars, models, activity status, and direct "Open chat" launch buttons.

When this ships, an operator can navigate to `/agents` from the primary navigation rail, see all platform and custom agents in a card grid with their signature emoji, model badge, relative activity timestamp, and recent activity snippet, click "Open chat" on any card to immediately start a session with that agent as the session default, create a new custom agent or delete custom agents via overlay modals on `/agents`, and use a clean `/new` screen focused on session creation with a link to `/agents`.

## Flow

This feature reuses the existing persistent shell router (`frontend/shell.ts`), `/api/agents` CRUD routes, `provision_agent_workspace` filesystem provisioning, and `/api/sessions` session creation.

1. User clicks `#nav-agents` ("Agents") in `src/clawhouse/static/index.html` (exists) -> `frontend/shell.ts` (exists) dynamically imports `/agents.js` and mounts `frontend/agents.ts` (door 1) into `#screen`
2. `frontend/agents.ts` (door 1) requests `GET /api/agents` -> `clawhouse.api.app` (exists) queries `clawhouse.store.store` (exists) for custom agents and recent agent activity (door 2), returning enriched `CustomAgentOut` items with `model`, `last_active_at`, and `last_activity`
3. `frontend/agents.ts` (door 1) renders `.agents-page` header and `.agents-grid` cards; clicking `.btn-open-chat` posts to `POST /api/sessions` and navigates to `/chat?session=<id>&agent=<name>` (or `/chat?session=<id>` for `main`)
4. Clicking `#btn-new-agent` or `#btn-manage-agents` in `frontend/agents.ts` (door 1) opens the creation modal (`POST /api/agents`) or management modal (`DELETE /api/agents/{id}`) and refreshes the grid in-place; `frontend/new.ts` (exists) removes inline agent creation/deletion forms and links to `/agents`

## Impact

| Front | What changes |
| --- | --- |
| domain | existing term: `CustomAgentOut` - previously carried identity and prompt fields only; now includes optional `model`, `last_active_at`, and `last_activity` fields for roster display |
| domain | new screen module: `frontend/agents.ts` (compiled to `src/clawhouse/static/agents.js`) mounted at `/agents` |
| stored data | nothing to migrate; agent activity metadata (`last_active_at`, `last_activity`) is derived from existing `clawhouse.transcript_entries` and `clawhouse.runs` tables |

## Relations

None - no stored-data shape change

## Surface

Only routes this adds or whose signature changes.

| Route | In | Out | Status |
| --- | --- | --- | --- |
| `GET /agents` | none | HTML shell document (`index.html`) | `200`, `401` |
| `GET /agents.js` | none | JavaScript module (`agents.js`) | `200` |
| `GET /api/agents` | none | `id` · `owner_id` · `name` · `description` · `system_prompt` · `signature_emoji` · `is_platform` · `model` · `last_active_at` · `last_activity` | `200`, `401` |
| `POST /api/agents` | `name`, `description`, `system_prompt`, `signature_emoji`, `soul`, `context` | `id` · `owner_id` · `name` · `description` · `system_prompt` · `signature_emoji` · `is_platform` · `model` · `last_active_at` · `last_activity` | `201`, `401`, `422` |

## Landing

| One-way door | Literal shape | Alternative rejected |
| --- | --- | --- |
| Dedicated `/agents` screen and modals (door 1) | Route `/agents` in `shell.ts` mounting `agents.js` with `.agents-grid` cards and overlay modals for "Novo agente" and "Gerenciar agentes" | Conversational agent maker in chat transcript; rejected because it requires an active LLM loop with tool calling to synthesize `AGENTS.md`/`SOUL.md` before an agent exists, adding latency, token cost, and non-deterministic failure for simple configuration |
| Enriched `CustomAgentOut` contract on `GET /api/agents` (door 2) | `CustomAgentOut` adds `model: str`, `last_active_at: str \| None = None`, `last_activity: str = ""` | Separate `GET /api/agents/{id}/activity` per card; rejected because N+1 requests on page load degrade roster rendering latency |

- Nothing else in this change is hard to reverse

## Criteria

Grouped by slice - one observable outcome each, never a layer. Numbering runs across the whole plan.

### S1: Rail Navigation & Route Mounting (`/agents`) (P1)

Primary navigation link, client-side route registration, backend shell route, and static asset serving for `/agents`.

**Acceptance Criteria**

1. The shell HTML (`index.html`) SHALL include `<a class="rail-link" id="nav-agents" data-nav href="/agents">Agents</a>` inside `.rail-nav`.
2. WHEN a signed-in client requests `GET /agents` THEN the backend SHALL return HTTP 200 with the shell HTML document (`index.html`).
3. IF an unauthenticated client requests `GET /agents` THEN the backend SHALL return HTTP 401.
4. WHEN a client requests `GET /agents.js` THEN the backend SHALL return HTTP 200 with `src/clawhouse/static/agents.js` and `text/javascript` media type.
5. WHEN the user navigates to `/agents` in the shell THEN `shell.ts` SHALL set `document.title` to `"Clawhouse · Agents"`, mark `#nav-agents` with `aria-current="page"`, and mount `agents.js` into `#screen`.

**Independent test:** Request `GET /agents` and `GET /agents.js` via HTTP client and verify 200 responses; click `#nav-agents` in the shell and verify `location.pathname` is `"/agents"`, `document.title` is `"Clawhouse · Agents"`, and `#nav-agents` has `aria-current="page"`.

### S2: Enriched Agent API (`GET /api/agents` & `POST /api/agents`) (P1)

Agent listing and creation responses enriched with configured model identifier, last active timestamp, and recent activity preview.

**Acceptance Criteria**

6. WHEN a client requests `GET /api/agents` THEN the system SHALL return HTTP 200 with a JSON array where every agent object includes `model` (the default configured model id/name or `"databricks"` fallback), `last_active_at` (ISO-8601 timestamp string or `null`), and `last_activity` (string).
7. WHEN an agent has executed at least one turn in an owned session THEN `GET /api/agents` SHALL populate `last_active_at` with the ISO timestamp of that agent's most recent run/turn and `last_activity` with a preview of the latest user prompt or assistant activity (truncated to at most 120 characters).
8. WHEN an agent has no recorded turns THEN `GET /api/agents` SHALL return `last_active_at: null` and `last_activity` set to `"Heartbeat & platform operations"` for `main` or `c.description` for a custom agent.
9. IF a client sends `POST /api/agents` with an unsafe agent name (failing `[A-Za-z0-9][A-Za-z0-9_-]{0,63}`) or reserved name `"main"` THEN the system SHALL return HTTP 422 without creating a database row or provisioning a workspace folder.

**Independent test:** Call `GET /api/agents` before and after running a turn with `@fraud`, and verify `model`, `last_active_at`, and `last_activity` update to reflect the turn.

### S3: Agents Overview Grid Screen (`agents.ts` & CSS) (P1)

Dedicated `/agents` screen displaying the team header, loading/error states, agent cards grid, and direct "Open chat" session launcher.

**Acceptance Criteria**

10. WHEN `agents.ts` mounts into `#screen` THEN it SHALL render `.agents-page` with header title `"Agents"`, subtitle `"Who is on your team and what they are doing"`, button `#btn-manage-agents` (`"Manage agents"`), and button `#btn-new-agent` (`"New agent"`).
11. WHILE `GET /api/agents` is in flight THEN `agents.ts` SHALL render a loading state element `.agents-loading` inside `.agents-grid`.
12. IF `GET /api/agents` fails or returns a non-OK status THEN `agents.ts` SHALL render `.agents-error` with an error message and a `.btn-retry-agents` button that re-triggers `GET /api/agents` when clicked.
13. WHEN `GET /api/agents` succeeds THEN `agents.ts` SHALL render one `.agent-card` per returned agent inside `.agents-grid`, displaying `.agent-card-avatar` (signature emoji), `.agent-card-title` (agent name), `.agent-card-model` (model badge), `.agent-card-status` (relative time from `last_active_at` or `"Newly created"` when `null`), `.agent-card-activity` (`last_activity` or `description`), and a `.btn-open-chat` button (`"Open chat"`).
14. WHEN the user clicks `.btn-open-chat` on an `.agent-card` THEN the system SHALL send `POST /api/sessions` and navigate to `/chat?session=<id>` for `main` or `/chat?session=<id>&agent=<encodeURIComponent(agent.name)>` for a custom agent.

**Independent test:** Mount `agents.ts` with mocked `/api/agents`, verify header copy and card fields for `main` and custom agents, click `.btn-open-chat` on a custom agent card, and verify `POST /api/sessions` is called followed by navigation to `/chat?session=<id>&agent=<name>`.

### S4: "Novo agente" & "Gerenciar agentes" Modals + `/new` Cleanup (P1)

Overlay modals on `/agents` for creating and deleting custom agents, plus simplifying `/new` to focus on session creation.

**Acceptance Criteria**

15. WHEN the user clicks `#btn-new-agent` on `/agents` THEN the system SHALL open a modal `#modal-new-agent` containing inputs for name (`name`), emoji (`signature_emoji`, default `"🤖"`), description (`description`), system prompt (`system_prompt`), optional `SOUL.md` (`soul`), and optional `CONTEXT.md` (`context`).
16. WHEN the user submits `#modal-new-agent` THEN the system SHALL send `POST /api/agents` with the trimmed form values, close `#modal-new-agent` on HTTP 201, and refresh `.agents-grid` so the newly created agent card is rendered.
17. IF `POST /api/agents` fails when submitting `#modal-new-agent` THEN the system SHALL keep `#modal-new-agent` open, re-enable the submit button, and display an error message in `.modal-status`.
18. WHEN the user clicks `#btn-manage-agents` on `/agents` THEN the system SHALL open `#modal-manage-agents` listing all agents, where `main` is marked protected without a delete button and each custom agent row has a `.btn-delete-agent` button.
19. WHEN the user clicks `.btn-delete-agent` for a custom agent in `#modal-manage-agents` THEN the system SHALL send `DELETE /api/agents/{id}` and remove the deleted agent from both `#modal-manage-agents` and `.agents-grid`.
20. WHEN the user clicks the modal close button, clicks the modal backdrop, or presses `Escape` while `#modal-new-agent` or `#modal-manage-agents` is open THEN the system SHALL close the active modal.
21. The `/new` screen (`frontend/new.ts`) SHALL render the agent picker and `#start` form without inline `.create-agent-form` or `.custom-agents-list`, and SHALL include a link `a[href="/agents"][data-nav]` to manage or create agents on `/agents`.

**Independent test:** On `/agents`, open `#modal-new-agent`, submit a new agent, verify it appears in `.agents-grid`; open `#modal-manage-agents`, delete the custom agent, verify it disappears from `.agents-grid`; mount `/new` and verify inline agent creation form is gone and a link to `/agents` is present.

## Out of scope

Product capabilities only. Process and harness rules live in AGENTS.md or as Observable `n/a`.

| Excluded | Why |
| --- | --- |
| Conversational LLM agent maker wizard | Explicitly rejected in Shape B of `docs/specs/design-agents-management-ui.md` due to latency, token spend, and non-determinism |
| Editing an existing custom agent's `AGENTS.md`/`SOUL.md` via UI modal | V1 supports create and delete; editing existing workspace files is done via workspace tools or recreate |
| Per-agent custom model override stored in `custom_agents` table | All agents currently share the workspace's configured model options; per-agent model pinning requires a schema migration deferred to a future slice |

## Assumptions

Defaults that are not already a numbered criterion. Drop a row once it is.

| Assumption | Chosen default | Rationale | Confirmed? |
| --- | --- | --- | --- |
| Navigation rail link order | `Chat`, `Sessions`, `Agents`, `Approvals`, `Jobs`, `Status` (or `Agentes` placed after `Sessions`) | Groups core conversational entities (`Chat`, `Sessions`, `Agents`) together at the top of the primary nav | y |
| Delete confirmation in "Gerenciar agentes" modal | Direct delete button in the dedicated management modal without a second browser `confirm()` dialog (matching existing `new.ts` delete behavior) | The user is already inside the explicit "Gerenciar agentes" modal | y |

**Open questions:** none - all resolved or logged above.

## Observable

Worksheet, not the review. `n/a` needs its reason. One row may group the same decision across several routes.

| Surface | Decision | Landing |
| --- | --- | --- |
| screen `agents` | empty state | AC 13 (platform agent `main` is always present, so grid always has at least 1 card; `#modal-manage-agents` shows empty note when no custom agents exist) |
| screen `agents` | loading state | AC 11 |
| screen `agents` | error state and retry | AC 12 |
| screen `agents` | unauthorised state | AC 3 |
| screen `agents` | density and ordering | AC 13 (`main` first, followed by custom agents in creation order inside responsive CSS grid) |
| screen `agents` | destructive action confirms | AC 18, AC 19 |
| screen `new` | cleanup of inline agent management | AC 21 |
| API `GET /api/agents` | response shape and enriched fields | AC 6, AC 7, AC 8 |
| API `POST /api/agents` | error shape and validation codes | AC 9, AC 17 |
| all new `/api/agents*` and `/agents*` routes | versioning, rate limits | n/a - internal application endpoints running behind Databricks App authenticated proxy |

## Sources

- `docs/specs/design-agents-management-ui.md` - Confirmed design specification for `/agents` screen, API enrichment, modals, and `/new` cleanup
- `docs/openclaw-ui/SHOTS.md` §9-10 - OpenClaw `/agents` overview visual reference
