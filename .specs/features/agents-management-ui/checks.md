# Agents Management and Selection UI (`/agents`) checks

Profile: light
Plan: `.specs/features/agents-management-ui/plan.md`

17 checks in 4 slices · 2 one-way doors · 0 open, of which 0 block

## Checks

Grouped by the spec's slices; numbering runs across the whole feature.

### S1 - Rail Navigation & Route Mounting (`/agents`) · 6 files · 90 KB · ~23k

**C1** - `GET /agents` returns HTTP 200 with the shell HTML document containing `<a class="rail-link" id="nav-agents" data-nav href="/agents">Agents</a>` inside `.rail-nav` for a signed-in client (AC 1, AC 2)
Proof: `uv run pytest tests/test_shell.py::test_every_route_serves_the_same_shell_document`

**C2** - `GET /agents` without caller identity returns HTTP 401 (AC 3)
Proof: `uv run pytest tests/test_shell.py::test_every_route_requires_a_signed_in_user`

**C3** - `GET /agents.js` returns HTTP 200 with `text/javascript` content type and is registered in the wheel build manifest (AC 4)
Proof: `uv run pytest tests/test_build.py::test_every_served_script_has_a_typescript_source`

**C4** - Navigating to `/agents` in `shell.ts` sets `document.title` to `"Clawhouse · Agents"`, sets `aria-current="page"` on `#nav-agents`, and mounts `agents.js` into `#screen` (AC 5)
Proof: `npm test -- frontend/shell.test.ts -t "highlights the active screen in the rail and updates the title"`

### S2 - Enriched Agent API (`GET /api/agents` & `POST /api/agents`) · 4 files · 59 KB · ~15k

**C5** - `GET /api/agents` returns HTTP 200 with `main` first followed by custom agents, each carrying `model` (configured default model or `"databricks"`), `last_active_at: null`, and `last_activity` set to `"Heartbeat & platform operations"` for `main` or `description` for custom agents when no turns have run (AC 6, AC 8)
Proof: `uv run pytest tests/test_suggestions_api.py::test_agents_api_enriches_model_and_default_activity`

**C6** - After an agent executes a turn in an owned session, `GET /api/agents` returns `last_active_at` set to the run's ISO-8601 timestamp and `last_activity` set to a preview of the latest turn content truncated to at most 120 characters (AC 7)
Proof: `uv run pytest tests/test_suggestions_api.py::test_agents_api_populates_last_active_at_and_activity_from_turns`

**C7** - `POST /api/agents` with an unsafe agent name (`"../evil"`, `"bad name"`) or reserved name `"main"` returns HTTP 422 without creating a database record or workspace directory, and unauthenticated `GET /api/agents` or `POST /api/agents` returns HTTP 401 (AC 9)
Proof: `uv run pytest tests/test_suggestions_api.py::test_create_agent_rejects_unsafe_or_reserved_names_and_unauthenticated_requests`

### S3 - Agents Overview Grid Screen (`agents.ts` & CSS) · 3 files · 28 KB · ~7k

**C8** - Mounting `agents.ts` renders `.agents-page` with header title `"Agents"`, subtitle `"Who is on your team and what they are doing"`, `#btn-manage-agents` (`"Manage agents"`), `#btn-new-agent` (`"New agent"`), and `.agents-loading` while `GET /api/agents` is in flight (AC 10, AC 11)
Proof: `npm test -- frontend/agents-page.test.ts -t "renders header copy and loading state while fetching agents"`

**C9** - When `GET /api/agents` fails or returns HTTP 500, `agents.ts` renders `.agents-error` with `.btn-retry-agents`, and clicking `.btn-retry-agents` re-requests `GET /api/agents` and renders `.agent-card` items (AC 12)
Proof: `npm test -- frontend/agents-page.test.ts -t "renders error state on fetch failure and retries when clicking retry button"`

**C10** - When `GET /api/agents` returns agents, `agents.ts` renders one `.agent-card` per agent inside `.agents-grid` with `.agent-card-avatar`, `.agent-card-title`, `.agent-card-model`, `.agent-card-status` (relative time or `"Newly created"` when `last_active_at` is `null`), `.agent-card-activity`, and `.btn-open-chat` (`"Open chat"`) (AC 13)
Proof: `npm test -- frontend/agents-page.test.ts -t "renders agent cards with avatar, model badge, relative status, activity, and open chat button"`

**C11** - Clicking `.btn-open-chat` on an `.agent-card` sends `POST /api/sessions` and navigates to `/chat?session=<id>` for `main` or `/chat?session=<id>&agent=<encodeURIComponent(name)>` for a custom agent (AC 14)
Proof: `npm test -- frontend/agents-page.test.ts -t "creates a session and navigates to chat with agent parameter when clicking Open chat"`

### S4 - "Novo agente" & "Gerenciar agentes" Modals + `/new` Cleanup · 4 files · 25 KB · ~6k

**C12** - Clicking `#btn-new-agent` opens `#modal-new-agent` with inputs `name`, `signature_emoji` (default `"🤖"`), `description`, `system_prompt`, `soul`, and `context`; submitting sends `POST /api/agents`, closes `#modal-new-agent` on HTTP 201, and renders the new `.agent-card` in `.agents-grid` (AC 15, AC 16)
Proof: `npm test -- frontend/agents-page.test.ts -t "creates a new custom agent via #modal-new-agent and refreshes the grid"`

**C13** - When `POST /api/agents` returns an error on `#modal-new-agent` submission, `#modal-new-agent` stays open, re-enables the submit button, and displays the error in `.modal-status` (AC 17)
Proof: `npm test -- frontend/agents-page.test.ts -t "keeps #modal-new-agent open and shows .modal-status when POST /api/agents fails"`

**C14** - Clicking `#btn-manage-agents` opens `#modal-manage-agents` where `main` is listed without `.btn-delete-agent` and custom agents have `.btn-delete-agent`; clicking `.btn-delete-agent` sends `DELETE /api/agents/{id}` and removes the agent from `#modal-manage-agents` and `.agents-grid` (AC 18, AC 19)
Proof: `npm test -- frontend/agents-page.test.ts -t "lists agents in #modal-manage-agents, protects main, and deletes a custom agent"`

**C15** - Clicking the modal close button, clicking the modal backdrop, or pressing `Escape` closes `#modal-new-agent` or `#modal-manage-agents` (AC 20)
Proof: `npm test -- frontend/agents-page.test.ts -t "closes active modal on close button, backdrop click, or Escape key"`

**C16** - Mounting `frontend/new.ts` renders the `#agent` picker and `#start` button without `.create-agent-form` or `.custom-agents-list`, and renders `a[href="/agents"][data-nav]` (AC 21)
Proof: `npm test -- frontend/new.test.ts -t "links to /agents instead of rendering inline agent creation or deletion forms"`

**C17** - All new CSS rules for `.agents-page`, `.agents-grid`, `.agent-card`, and `.modal-backdrop` in `screens.css` use design tokens from `tokens.css` with zero literal color, border-radius, or font-family values (AC 10, AC 13, AC 15, AC 18)
Proof: `uv run pytest tests/test_design_tokens.py::test_component_sheets_resolve_style_through_tokens`

## Coverage

| Set (size) | Member -> proof | Unproven |
| --- | --- | --- |
| `GET /agents` statuses (2) | `200` C1 · `401` C2 | - |
| `GET /agents.js` statuses (1) | `200` C3 | - |
| `GET /api/agents` statuses (2) | `200` C5 · `401` C7 | - |
| `POST /api/agents` statuses (3) | `201` C12 · `401` C7 · `422` C7 | - |
| Landing doors (2) | door 1 (`/agents` screen and modals) C8 · door 2 (enriched `CustomAgentOut`) C5 | - |
| `agents` screen states (3) | loading C8 · error/retry C9 · populated grid C10 | - |
| modal dismissal triggers (3) | close button C15 · backdrop click C15 · `Escape` key C15 | - |

- Claims naming a status code, route or response shape: C1, C2, C3, C5, C6, C7, C12 - each has a proof that crosses the boundary
- No other check claims more than the single case its proof exercises

## Swept

- validation: C7, C13
- failure modes: C9, C13
- idempotency: existing - `DELETE /api/agents/{id}` returns 204 whether called once or repeated, and `provision_agent_workspace` uses `mkdir(parents=True, exist_ok=True)`
- authorization: C2, C7
- concurrency: existing - `LakebaseSessionStore` and `MemorySessionStore` scope custom agent queries and deletions by `(owner_id, agent_id)`
- data lifecycle: existing - `DELETE /api/agents/{id}` removes both the store record and the physical workspace directory via `delete_agent_workspace`
- dependency failure: C9, C13
- state transitions: C11, C12, C14, C15
- observability: n/a - no new background jobs or telemetry spans introduced by the `/agents` UI slice

## Handoff

- S1 = 23k, S2 = 15k, S3 = 7k, S4 = 6k -> 51k total across 17 files, under the 150k budget - one builder
- **Boundary:** C1-C17 closed in `feat/agents-management-ui`
- **Settled mid-build:** none
- **Abandoned:** none
