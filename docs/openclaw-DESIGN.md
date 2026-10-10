# OpenClaw — Design & UI Inventory for the DatabricksClaw Port

Status: exploration output for issue #3. Not an ADR.
Source: `https://github.com/openclaw/openclaw` @ `9cd23e6067c84433439d14166b15c132ddcc1983`
(release train `2026.9.9`), cloned shallow to `/tmp/openclaw-src`.

Audience: the DatabricksClaw port. Target stack per ADR-0001/0002:
FastAPI backend, TypeScript/HTML frontend served by the Databricks App,
Lakebase for structured state, user workspace for personal files,
pydantic-ai as the turn runtime.

This document has four parts:

1. Architecture map (gateway, agent core, tools, sessions, channels, trust boundaries).
2. UI inventory (must-copy for v1 vs defer) with per-route source references.
3. API / WebSocket contract notes relevant to a FastAPI + TS port.
4. Open questions and porting risks.

Companion file: [`docs/openclaw-ui/SCREENSHOTS.md`](openclaw-ui/SCREENSHOTS.md) — per-screen text descriptions and source links.

---

## 0. TL;DR for the port

- OpenClaw is a **local-first personal assistant daemon**. A single **Gateway** process owns
  every channel connection, session, tool execution, and the WebSocket control plane. Clients
  (web Control UI, CLI, TUI, native apps, nodes) are thin and speak one JSON-over-WS protocol.
- The **agent loop** is a serialized, per-session turn: intake → context assembly → model
  inference → tool execution → streaming → persistence. It is exposed over the same protocol
  via `agent` / `agent.wait` and mirrored to a UI-friendly `chat` event stream.
- The **web UI** is a large Vite + Lit SPA (~50 route groups, ~470 RPC methods behind it). For
  DatabricksClaw v1 we should port a small, coherent subset (chat, sessions, agents, models,
  approvals, channels, config, usage) and deliberately defer nodes/devices, terminal/browser/
  desktop panels, plugins marketplace, dashboards/workboard, and native-app surfaces.
- The protocol is **schema-first** (TypeBox → JSON Schema → generated Swift/TS types). For a
  FastAPI port, do not re-implement the entire surface; define a narrow typed contract that
  covers the v1 feature set and keeps the frame envelope/handshake shape so a future TS client
  can be swapped in.

---

## 1. Architecture map

### 1.1 Process topology

```
                    ┌────────────────────────────────────────────┐
   Channels ───────▶│                GATEWAY (daemon)             │
 (WhatsApp,         │  - channel/provider connections             │
  Telegram, Slack,  │  - session store + transcript store         │
  Discord, Signal,  │  - agent runtime (embedded loop)            │
  iMessage, ...)    │  - tool execution + policy + approvals      │
                    │  - scheduler (cron/heartbeat)               │
                    │  - HTTP server (static UI, /v1, /tools)     │
                    │  - WS server (control plane + nodes)        │
                    └───────┬───────────────┬──────────────┬──────┘
                            │ WS            │ WS           │ HTTP
                   ┌────────▼──────┐ ┌──────▼───────┐ ┌────▼─────────────┐
                   │ operator      │ │ node         │ │ Control UI (SPA) │
                   │ clients:      │ │ hosts:       │ │ CLI / TUI        │
                   │ web/CLI/TUI/  │ │ macOS/iOS/   │ │ OpenAI-compat    │
                   │ native apps   │ │ Android/head │ │ /v1, /tools      │
                   └───────────────┘ └──────────────┘ └──────────────────┘
```

Key invariants (from `docs/concepts/architecture.md`):

- **Exactly one Gateway** per host owns a channel session (e.g. one Baileys/WhatsApp session).
- The **first WS frame must be `connect`**; any non-JSON or non-connect first frame is a hard close.
- **Events are not replayed.** Clients must refresh on sequence gaps.
- One `GatewayScheduler` owns all timed work (cron, heartbeats, maintenance).

### 1.2 Gateway

Location: `src/gateway/` (huge; ~thousands of files). Subsystems:

| Area | Path | Notes |
| --- | --- | --- |
| WS server + dispatch | `src/gateway/server/`, `src/gateway/server-methods/` | one handler per method family |
| Method policy table | `src/gateway/methods/core-descriptors.ts` | **canonical** append-only table: method → handler group → required scope |
| Method registry | `src/gateway/methods/registry.ts`, `core-method-policy.ts` | derived lookup + dispatch policy |
| Operator scopes | `src/gateway/operator-scopes.ts` | scope set + method→scope mapping |
| HTTP routes | `src/gateway/control-ui*.ts`, `embeddings-http.ts`, `tools-invoke-http.ts`, `board-http.ts` | static UI, media, OpenAI-compat, tools |
| Sessions | `src/gateway/session-*.ts`, `session-utils*.ts` | index, rows, projections, transcripts |
| Chat | `src/gateway/chat-*.ts` | `chat.send/history/abort/inject`, display projection |
| Agent dispatch | `src/gateway/agent*.ts`, `server-methods/agent*.ts` | `agent`, `agent.wait`, run ownership |
| Approvals | `src/gateway/exec-approval-*.ts`, `approval-*.ts` | durable approval registry |
| Channels | `src/gateway/channel-*.ts` | channel status/start/stop/login |
| Auth | `src/gateway/auth*.ts`, `device-auth.ts`, `auth-rate-limit.ts` | token/password/trusted-proxy/tailscale, device pairing |
| Storage | `src/gateway/session-*.ts`, `src/storage/` | shared state DB + per-agent SQLite |

The method table `CORE_GATEWAY_METHOD_SPECS` is the single source of truth for the RPC surface.
It currently lists **≈500 method rows (~470 unique names)** (see §3.3 for the grouped list).

### 1.3 Agent runtime core

Per `docs/agent-runtime-architecture.md`:

| Path | Owns |
| --- | --- |
| `packages/agent-core/` | Reusable agent core: agent loop (`agent-loop.ts`), harness types, messages, compaction helpers, prompt templates, skills, session-storage contracts |
| `src/agents/embedded-agent-runner/` | Built-in attempt loop (`run.ts`, `run/`), model selection, per-provider params, compaction, transcript/session wiring |
| `src/agents/sessions/` | Session persistence, resource discovery, extensions loading, prompt templates, skills, themes, tool renderers |
| `src/agents/runtime/` | Facade wiring `@openclaw/agent-core` to the plugin-SDK LLM runtime |
| `src/agents/agent-tools*.ts` | Tool definitions, parameter schemas, tool policy, before/after adapters |
| `src/agents/agent-hooks/` | Built-in hooks: compaction safeguard, compaction instructions, context pruning |
| `src/agents/harness/` | Harness registry + selection (built-in vs plugin harnesses, e.g. `codex`) |
| `src/llm/` | Model/provider registry + provider stream implementations |

Runtime selection: built-in runtime id is `openclaw` (legacy alias `pi`). `agentRuntime.id`
config can select a plugin harness (e.g. `codex`). `auto` prefers a registered plugin harness
that supports the effective provider route, else the built-in loop.

### 1.4 Agent loop (exact sequence)

From `docs/concepts/agent-loop.md`:

1. `agent` RPC validates params, resolves the session (`sessionKey`/`sessionId`), persists
   metadata, and returns `{ runId, acceptedAt }` **immediately**.
2. `agentCommand` resolves model + thinking/verbose/trace defaults, loads the skills snapshot,
   calls `runEmbeddedAgent`, and emits a fallback terminal lifecycle event.
3. `runEmbeddedAgent` serializes runs via **per-session lane + optional global lane**, resolves
   model + auth profile, builds the session, subscribes to runtime events, streams
   assistant/tool deltas, enforces the run timeout, returns payloads + usage.
4. `subscribeEmbeddedAgentSession` bridges runtime events to the `agent` stream:
   `stream: "tool"`, `stream: "assistant"`, `stream: "lifecycle"`
   (`phase: start | finishing | end | error`).
5. `agent.wait` waits for the terminal outcome on a `runId`:
   `{ status: ok|error|timeout, startedAt, endedAt, error? }` plus `terminalReply`/`terminalReceipt`.

Run phases in order: intake → workspace resolution → skills + bootstrap context injection →
prompt assembly → hooks → model inference → tool execution → reply shaping → persistence.

Concurrency: runs are serialized per session key; a **durable writer claim** (`activeWriterRunId`)
fences every transcript append/rewrite so a superseded run cannot commit stale data. A SQLite
writer queue orders per-agent mutations; a state-directory lock prevents two gateways.

Hooks (two systems):

- **Internal hooks**: `HOOK.md` scripts for command/lifecycle events (`command:new`, etc.).
- **Plugin hooks**: typed `api.on(...)` handlers — `before_model_resolve`, `before_prompt_build`,
  `before_agent_reply`, `agent_end`, `before_compaction`/`after_compaction`,
  `before_tool_call`/`after_tool_call`, `before_install`, `tool_result_persist`,
  `message_received`/`message_sending`/`message_sent`, `session_start`/`session_end`,
  `gateway_start`/`gateway_stop`.

Timeouts: `agent.wait` default 30s (wait-only); agent runtime budget
`agents.defaults.timeoutSeconds` default **172800s (48h)**, `0` = unlimited; model idle
timeout cloud 120s / self-hosted 300s.

### 1.5 Tool system

- Tools are typed functions the model calls. Visible tools are filtered by profile,
  allow/deny policy, provider restrictions, sandbox state, channel permissions, and plugin
  availability (`src/agents/agent-tool-availability.ts`, `tool-resolution*.ts`).
- Representative built-in tools by category (from `docs/tools/index.md`):
  - Runtime: `exec`, `process`, `terminal`, `code_execution`
  - Files: `read`, `write`, `edit`, `apply_patch`
  - Human input: `ask_user`, `secrets`
  - Web: `web_search`, `x_search`, `web_fetch`
  - Browser: `browser`
  - Operator UI: `screen`, `theme`
  - Progress: `progress_card`
  - Messaging: `message`
  - Sessions/agents: `sessions_*`, `agents_wait`, `subagents`, `agents_list`, `session_status`, `get_goal`/`create_goal`/`update_goal`
  - Automation: `cron`, `heartbeat_respond`
  - Gateway/nodes: `gateway`, `nodes`
  - Plugins: `plugins`
  - Media: `view_image`, `image_generate`, `music_generate`, `video_generate`, `tts`
  - Large catalogs: `tool_search`, `tool_describe`, `tool_call` (Tool Search / Code Mode)
- Tool policy is layered before sandbox rules; `tools.elevated` is an explicit escape hatch that
  runs `exec` outside the sandbox.
- `tools.invoke` HTTP endpoint (`POST /tools/invoke`) invokes a single tool directly with tool
  policy enforcement (bearer = full operator access).

### 1.6 Sessions

- Every inbound message routes to a **session** by source. State is Gateway-owned; UI clients
  query the Gateway.
- Routing defaults: DMs → shared main session (`session.dmScope: "main"`); group chats →
  isolated per group; rooms → isolated per room; cron → fresh session per run; webhooks →
  isolated per hook.
- `session.dmScope` options: `main`, `per-peer`, `per-channel-peer`, `per-account-channel-peer`.
  `session.groupScope`: `per-group` (default) or `main`.
- Session key forms: `agent:<agentId>:main`, `agent:<agentId>:global`, `agent:<agentId>:unknown`,
  and channel-derived keys; `session.identityLinks` maps a person's channel identities to one peer.
- Session rows carry: creator (immutable), owner (assignable), participants (history), model
  selection/thinking/fast/verbose/trace overrides, category/groups, archive/snooze, unread,
  placement, sharing/visibility, board membership, token usage.
- Transcripts are persisted per session with writer-claim fencing; the session index is a SQLite
  projection with compact/full row modes.
- Session-scoped RPCs: `sessions.list`, `sessions.subscribe`, `sessions.create`, `sessions.patch`,
  `sessions.send`, `sessions.abort`, `sessions.reset`, `sessions.delete`, `sessions.fork`,
  `sessions.rewind`, `sessions.compact`, `sessions.search`, `sessions.branches.*`,
  `sessions.usage*`, `sessions.messages.subscribe/unsubscribe`, `sessions.groups.*`, etc.

### 1.7 Channels

- Built-in + bundled + external plugin channels. Named channels in `docs/channels/`:
  a2a, buzz, clickclack, discord, feishu, googlechat, imessage, irc, line, matrix, mattermost,
  msteams, nextcloud-talk, nostr, qqbot, signal, slack, sms, synology-chat, telegram, tlon,
  twitch, wechat, wecom, whatsapp, x, yuanbao, zalo, plus group/broadcast/ambient-room semantics.
- Channel runtime code: `src/channels/` (account resolution, allowlists, mention gating,
  DM guard, draft streaming, progress drafts, inbound debounce, message access, native command
  routing). Bundled channel plugins live in `extensions/` (e.g. `extensions/slack`,
  `extensions/telegram`, `extensions/whatsapp`, ...).
- Channel RPCs: `channels.status`, `channels.start`/`stop`/`logout`, `web.login.start/wait`,
  `channels.pairing.list/approve/dismiss`.
- **DM pairing**: unknown DM senders are paired by default; approve with
  `openclaw pairing approve <channel> <code>` or `channels.pairing.approve`.

### 1.8 Trust boundaries, auth, scopes, sandboxing

Trust model (`docs/gateway/operator-scopes.md`, `docs/gateway/authentication.md`):

- Scopes are a **control-plane guardrail inside one trusted operator domain**, *not* hostile
  multi-tenant isolation. For real separation run separate gateways under separate OS users.
- Every WS client connects with a role: `operator`, `node`, or `worker`.
- Operator scopes (full closed set):
  `operator.read`, `operator.write`, `operator.admin`, `operator.approvals`,
  `operator.questions`, `operator.pairing`, `operator.talk`, `operator.talk.secrets`,
  plus narrower `operator.sessions.read` / `operator.sessions.write`.
  `operator.admin` satisfies all; `operator.write` satisfies read + talk.
- Reserved prefixes always require `operator.admin`: `config.*`, `exec.approvals.*`,
  `wizard.*`, `update.*`.
- Auth modes: shared secret (`token`/`password`), `trusted-proxy`, Tailscale Serve,
  private-ingress `none`. Device identity + `connect.challenge` nonce signing (payload v3)
  is mandatory for normal clients; pairing approval is required for new device IDs (loopback
  auto-approval allowed).
- HTTP auth: `Authorization: Bearer <gateway token/password>` for `/v1/*` and `/tools/invoke`;
  shared-secret HTTP callers are treated as **full operator** regardless of narrower scope headers.

Sandboxing (`docs/gateway/sandboxing.md`):

- Off by default. Controlled by `agents.defaults.sandbox`, per-agent `agents.entries.*.sandbox`,
  or a required creator-role sandbox policy.
- The Gateway always stays on the host; only **tool execution** moves into the sandbox.
- Backends: Docker (default), Podman, SSH, OpenShell, Crabbox.
- Config axes: `mode` (e.g. `non-main`), `scope` (`session`/`shared`), `workspaceAccess`
  (`none`/...), image, `setupCommand`.
- Precedence: tool allow/deny policy → sandbox rules → `tools.elevated` escape hatch.
- Multi-agent overrides via `agents.entries.*.tools.sandbox.tools`.

### 1.9 Storage

From `docs/reference/database-schemas.md` and `docs/concepts/storage-locations.md`:

- **Shared state database** (SQLite) for control-plane state.
- **One SQLite database per agent** for agent data.
- Schema migrations run forward on open; older builds refuse newer schemas.
- The Gateway process is the single owner of every DB; child processes route mutations through
  the Gateway or take exclusive ownership while stopped.
- **Storage locations** (`storage.locations.<name>`) name artifact destinations. Built-in
  `filesystem` provider; plugin providers (e.g. Cloudflare R2). Optional encryption with a
  passphrase `SecretRef`. Explicit `storage init` writes `openclaw-storage.json`.

DatabricksClaw mapping (ADR-0002): structured session/transcript/run-lock state → **Lakebase**;
personal files (`AGENTS.md`, `SOUL.md`, `IDENTITY.md`, `USER.md`, `MEMORY.md`, `skills/`,
`context/`, `memory/`) → **user workspace** under `{user workspace}/claw/agents/{name}/`.

### 1.10 Plugins / extensions

- `extensions/` holds ~170 plugin packages (providers, channels, tools, media, search).
- Plugin manifest declares resources in `package.json` under `openclaw`:
  `extensions`, `skills`, `prompts`, `themes` (globs).
- Plugin SDK entrypoints: `packages/plugin-sdk/src/*` (channel runtime, gateway-method runtime,
  provider auth, config mutation, cron store, hooks, etc.).
- Plugins can add tools, skills, channels, model providers, speech, realtime voice, media
  generation, web search/fetch, hooks, and Control UI tabs.
- Install sources: `bundled`, `clawhub`, `git`, `local`, `marketplace`, `npm`, `npm-pack`,
  `official`. Capability consent + install-policy acknowledgement gates exist.

---

## 2. UI inventory (must-copy for v1 vs defer)

The Control UI is a Vite + **Lit** SPA (`ui/`, `ui/package.json` name `openclaw-control-ui`)
served by the Gateway on the same port (default `18789`, optional `gateway.controlUi.basePath`).
It talks **directly to the Gateway WS**. Routing uses `@openclaw/uirouter` with a route table in
`ui/src/app-routes.ts`; route ids/paths live in `ui/src/app-route-paths.ts`
(`APP_ROUTE_DEFINITIONS`). Sidebar grouping is in `ui/src/app-navigation.ts`.

### 2.1 Route table

Paths from `ui/src/app-route-paths.ts`; purposes from `docs/web/control-ui/*` and
`docs/web/control-ui/feature-reference.md`. "v1" = recommend porting to DatabricksClaw v1.

| Route id | Path(s) | Purpose | Port |
| --- | --- | --- | --- |
| `chat` | `/chat` (+ `/chat/:sessionRef`) | Primary chat view | **v1** |
| `new-session` | `/new` | Compose a new session (placement, model, repo) | **v1** |
| `sessions` | `/sessions`, `/settings/sessions` | Sessions table (Threads) + Worktrees tab | **v1** |
| `approvals` | `/settings/approvals` | Approval history + policy | **v1** |
| `agents-home` | `/agents` | Agent roster / "New agent" custodian entry | **v1** |
| `agents` | `/settings/agents[/:agentId[/:panel]]` | Per-agent config (Overview/Files/Tools/Skills/Channels/Automations/Memory) | **v1** |
| `model-providers` | `/settings/model-providers` | Provider connections, models, auth status, usage | **v1** |
| `model-setup` | `/settings/model-setup` | First-run / provider setup wizard | **v1** |
| `connection` | `/settings/connection` | This browser's gateway link + handshake snapshot | **v1** |
| `config` | `/settings/general`, `/config` | Curated settings + raw JSON5 config editor | **v1** |
| `profile` | `/settings/profile` | Person profile, model accounts, GitHub | **v1 (trim)** |
| `channels` | `/settings/channels`, `/channels` | Channel status, QR login, per-channel config | **v1 (read/status)** |
| `cron` | `/automations`, `/cron` | Automations (cron jobs) + run history | **v1 (basic)** |
| `usage` | `/usage` | Token/cost analytics, provider quotas | **v1** |
| `logs` | `/logs` | Live gateway log tail + filter/export | **v1** |
| `about` | `/settings/about` | Version/build/about | **v1** |
| `security` | `/settings/security` | Security settings (auth, exec policy, tool profile) | v1.1 |
| `secrets` | `/settings/secrets` | Team secret/env store (`secrets.store.*`) | defer |
| `appearance` | `/settings/appearance` | Themes, typography, language, tab icon | v1.1 |
| `notifications` | `/settings/notifications` | Web push subscribe/test | defer |
| `advanced` | `/settings/advanced` | Raw config sections + JSON5 editor | v1.1 |
| `mcp` | `/settings/mcp`, `/mcp` | MCP server rows + scoped config | defer |
| `memory` | `/settings/memory` | Memory / dreaming / Dream Diary | defer |
| `search` | `/settings/search` | Web search provider config | v1.1 |
| `talk` | `/settings/talk` | Realtime voice provider/model/voice | defer |
| `infrastructure` | `/settings/infrastructure` | Gateway infra, CLI agents, storage | defer |
| `labs` | `/settings/labs` | Experimental features (Code Mode, Tool Search, plugin UI, desktop) | defer |
| `updates` | `/settings/updates` | Update run + restart report | defer |
| `skills` | `/skills` | Skills catalog + status | defer |
| `skill-workshop` | `/skills/workshop` | Skill authoring/review | defer |
| `skill-settings` | `/settings/skills` | Skills config | defer |
| `plugins` | `/plugins` | Plugin catalog/store/install | defer |
| `plugin-settings` | `/settings/plugins` | Per-plugin settings | defer |
| `plugin` | `/plugin` | Plugin-contributed tab surface | defer |
| `devices` | `/settings/devices`, `/nodes` | Paired devices + node inventory + host stats | defer |
| `device` | `/settings/device` | This device capabilities | defer |
| `device-permissions` | `/settings/device/permissions` | Device permissions | defer |
| `cloud-workers` | `/settings/cloud-workers` | Cloud worker pools | defer |
| `worktrees` | `/worktrees` | Git worktrees hub | defer |
| `workboard` | `/workboard` | Plugin-owned widget boards | defer |
| `dashboards` | `/dashboards` | Session dashboards gallery | defer |
| `activity` | `/activity` | Live activity / run inspector | defer (partial) |
| `meetings` | `/meetings` | Meeting capture/transcripts | defer |
| `apps` | `/apps` | Companion apps / extensions | defer |
| `portals` | `/portals` | Portal surfaces | defer |
| `systems` | `/systems` | Host load/memory/disk telemetry | defer (partial) |
| `debug` | `/debug` | Diagnostics, event log, manual RPC | defer |
| `custodian` | `/custodian` | Guided agent creation chat | defer |
| `lobsterdex` | `/settings/lobsterdex` | Community/art surface | defer |
| `terminal` | `/terminal` | Operator terminal page | defer |
| `memory-import` | `/memory-import` | Import Claude/Codex/Hermes memory | defer |
| `communications` | `/settings/communications` | Shared channel defaults | defer |

Document routes: `approval` → `/approve`, `question` → `/ask` (deep-linkable approval/question
documents, see `CONTROL_UI_DOCUMENT_ROUTE_PATHS`).

### 2.2 Chat view (must-copy — the core surface)

Source: `ui/src/pages/chat/` (~250 non-test modules), docs `docs/web/control-ui/chat.md`.

Layout and behavior to reproduce:

- **Transcript**: assistant/user messages, markdown (markdown-it), code blocks, images,
  tool-call rows (kind-aware: shell commands with output, edit/write inline diffs with
  `+added -removed`), grouped consecutive tool activity ("13 commands · 6 reads · 9 edits"),
  "Worked for …" collapsed run summary, streaming assistant tail at the bottom of the run.
- **Composer**: text input with IME handling, attachments (images/PDF/video), emoji, mentions,
  slash-command palette, dictation/microphone, model/thinking/fast/verbose controls,
  queue while running, steer, undo/redo, draft persistence across reloads/tabs.
- **Session header**: title rename, model/thinking/session settings, panels menu,
  share/visibility, owner chip, presence/viewers.
- **Side panels** (embedded in chat): Dashboard/board, Terminal, Browser, Files, Review,
  Processes, Subagents, GitHub reader, MCP apps.
- **Sidebar**: session rail with live narration, running tool icon, attention items,
  online/people list with presence, outbox/unsent draft indicators.
- **Live transport**: `chat.history`, `chat.send`, `chat.abort`, `chat.inject`; events
  `chat` (delta/final/error/aborted), `agent` (assistant/tool/lifecycle), `session.message`,
  `session.tool`, `session.narration`, `session.observer`, `sessions.changed`.
- Scroll ownership: follow-at-end, manual scroll interruption, return-to-latest.

### 2.3 Sessions list / sidebar (must-copy)

Source: `ui/src/pages/sessions/`, `ui/src/components/session-*`, docs
`docs/web/control-ui/sessions-and-sidebar.md`.

- Sidebar session list with groups, pinning, drag-to-group, owner filter, status filters
  (Active / Snoozed / Archived / All), unread dots, live run indicator, search.
- Sessions page: table with overview tiles (count, live runs, unread, tokens, archived),
  kind glyphs, status dot, token/context meter, per-row kebab menu, group-by control,
  Fork, archive/restore, per-session model/thinking/fast/verbose/trace overrides.
- RPCs: `sessions.list`, `sessions.subscribe`, `sessions.patch`, `sessions.create`
  (`parentSessionKey`, `fork: true`), `sessions.describe`, `sessions.search`,
  `sessions.groups.*`, `sessions.assignOwner`.

### 2.4 Approvals (must-copy)

Source: `ui/src/pages/approvals/`, `ui/src/pages/approval/`, docs
`docs/gateway/protocol/rpc-devices-nodes-and-approvals.md`.

- Approval cards for exec / plugin / system-agent requests; approve/reject.
- History view (newest-first, 30 days), filter by kind, resolver attribution, source session.
- Exec allowlist/policy editing (`exec.approvals.get/set`, node variants).
- RPCs: `approval.get/resolve/history`, `exec.approval.*`, `exec.approvals.*`,
  `plugin.approval.*`, `question.*`.
- Events: `exec.approval.requested/resolved`, `plugin.approval.requested/resolved`.

### 2.5 Status / nodes / systems pages (defer, capture for reference)

- `devices` (`ui/src/pages/devices/`): inventory joining `device.pair.list`, `node.list`,
  `system-presence`; resource meters from `system.info`; pairing approve/reject; token
  rotate/revoke; exec approvals per node.
- `systems` (`ui/src/pages/systems/`): load/memory/disk history graphs.
- `debug` (`ui/src/pages/debug/`): status/health/models snapshots, command lanes, heartbeat,
  event log (250 events), manual RPC calls; "System busyness" overlay.
- `activity` (`ui/src/pages/activity/`): live activity, run inspector, tool activity.

### 2.6 Settings surface (mixed)

- `config`/`advanced`: schema-driven form (`config.schema`, `config.schema.lookup`) + raw JSON5
  editor with safe round-trip, base-hash guard, SecretRef handling.
- `model-providers`/`model-setup`: provider cards, auth status (`models.authStatus`),
  model catalog (`models.list`), live quota (`usage.status`), local spend (`sessions.usage`).
- `agents`: per-agent tabs — Overview (identity, avatar, primary model + fallback chain),
  Files, Tools (GitHub execution account), Skills, Channels, Automations, Memory.
- `channels`: status, QR/web login (`web.login.*`), per-channel config (`config.patch`),
  DM pairing.
- `security`, `secrets`, `mcp`, `labs`, `notifications`, `appearance`, `talk`.

### 2.7 Components worth reusing conceptually

`ui/src/components/` is large; the load-bearing primitives:

- `session-menu.ts`, `session-organizer-*`, `session-owner-chip.ts`, `session-progress-card.ts`,
  `session-row-badges.ts`, `sidebar-attention-*`, `sidebar-*`.
- `settings-sidebar.ts`, `settings-ui.ts`, `settings-save-indicator.ts`.
- `terminal/*` (PTY panel, fonts, uploads), `browser/*`, `desktop/*`, `board/*`.
- `markdown` rendering via `packages/markdown-core` + `markdown-it` + DOMPurify.
- Theme system: `ui/src/app/theme-*`, `ui/src/lib/theme-*`, `ui/public/themes/`.
- Web Awesome (`@awesome.me/webawesome`) design system, Lit 3.

### 2.8 Defer list (explicit)

Do **not** port for v1: nodes/devices/desktop, terminal/browser panels, dashboards/workboard
widgets, plugin marketplace + plugin-contributed UI tabs, cloud workers, worktrees,
meetings, portals, lobsterdex, custodian, memory/dreaming, skill workshop, MCP apps,
Talk/realtime voice, web push, systems/debug/activity inspectors.

---

## 3. API / WS contract notes for the FastAPI + TS port

### 3.1 Transport and framing

From `docs/gateway/protocol/transport.md`:

- WebSocket, text frames, JSON payloads. No `permessage-deflate` negotiation.
- First frame must be a `connect` request. Pre-connect frames capped at 64 KiB
  (`MAX_PREAUTH_PAYLOAD_BYTES`).
- Frame shapes:
  - Request: `{type:"req", id, method, params, traceparent?, expectedProfileId?}`
  - Response: `{type:"res", id, ok, payload|error}`
  - Event: `{type:"event", event, payload, seq?, stateVersion?, recipientProfileId?}`
- After handshake, limits come from `hello-ok.policy`:
  `maxPayload` (default 25 MiB), `maxBufferedBytes` (50 MiB), `tickIntervalMs` (15000),
  `attachments.maxBytes` (20 MB), `attachments.maxImageBytes` (6 MB).
- Optional W3C `traceparent` on requests for distributed tracing.

### 3.2 Handshake, roles, scopes

From `docs/gateway/protocol/handshake.md` and `auth.md`:

- Gateway sends `event: connect.challenge` `{ nonce, ts }` before `connect`.
- Client sends `connect` with `minProtocol`/`maxProtocol`, `client` (id/version/platform/mode),
  `role`, `scopes`, `caps`, `commands`, `permissions`, `auth`, `locale`, `userAgent`, `device`.
- `PROTOCOL_VERSION = 4`; `MIN_CLIENT_PROTOCOL_VERSION = 4`, `MIN_NODE = 3`, `MIN_PROBE = 3`
  (`packages/gateway-protocol/src/version.ts`).
- `hello-ok` payload: `type`, `protocol`, `server {version, connId}`, `features {methods, events}`,
  `snapshot`, `auth {role, scopes, deviceToken?}`, `policy {…}`, optional `controlUiUrl`,
  `pluginSurfaceUrls`, `appliedConfigHash`.
- Device identity is a keypair fingerprint; `connect.params.device` includes
  `{id, publicKey, signature, signedAt, nonce}` signed over payload v3 (binds platform +
  deviceFamily). New device ids require pairing approval (loopback auto-approval allowed).
- Client capabilities (`caps`) gate optional surfaces: `tool-events`, `inline-widgets`,
  `ultrafast`, `chat-only-assistant-text`, `ui-commands`, `usage-refreshing`, `desktop`.
- Idempotency keys are required for side-effecting methods (`send`, `agent`).

### 3.3 RPC method families (grouped; full list from `core-descriptors.ts`)

The method table is `src/gateway/methods/core-descriptors.ts` (~500 rows / ~470 unique names). Grouped surface:

- **System/identity**: `health`, `status`, `diagnostics.stability`, `system.info`,
  `gateway.identity.get`, `system-presence`, `system-event`, `last-heartbeat`, `set-heartbeats`,
  `gateway.restart.request`, `gateway.stop.request`, `gateway.suspend.*`, `wake`.
- **Models/usage**: `models.list`, `models.authStatus`, `models.authLogin/Logout/Refresh`,
  `models.authSetApiKey`, `models.authOrderSet`, `models.probe`, `usage.status`, `usage.cost`,
  `sessions.usage`, `sessions.usage.timeseries`, `sessions.usage.logs`.
- **Chat**: `chat.history`, `chat.send`, `chat.abort`, `chat.inject`, `chat.startup`,
  `chat.message.get`, `chat.toolTitles`.
- **Agent**: `agent`, `agent.wait`, `agent.identity.get`, `agents.create/delete/list/update`,
  `agents.files.*`, `agents.workspace.*`.
- **Sessions**: `sessions.*` (list, subscribe, create, patch, patchMany, send, abort, reset,
  delete, fork, rewind, compact, search, resolve, describe, move, recover, preview, diff,
  dispatch, cleanup, branches.*, groups.*, usage*, files.*, messages.*, processes.*,
  goal.*, reactions.*, suggestions.*, members.*, viewers.*, storage.*, catalog.*,
  companion.*, observer.visibility, github.*, providerReview.*, title.prepare).
- **Channels**: `channels.status/start/stop/logout`, `channels.pairing.*`,
  `web.login.start/wait`, `push.test`, `voicewake.*`.
- **Config**: `config.get/set/apply/patch/schema/schema.lookup`, `config.openFile`.
- **Approvals/questions**: `approval.get/resolve/history`, `exec.approval.*`,
  `exec.approvals.*` (gateway + node), `plugin.approval.*`, `question.*`.
- **Devices/nodes**: `device.pair.*`, `device.token.*`, `device.scopes.*`, `node.pair.*`,
  `node.list/describe/invoke/rename/event`, `node.pending.*`, `node.pluginTools.update`,
  `node.skills.update`, `node.pluginSurface.refresh`.
- **Plugins/skills/tools**: `plugins.*` (list, inspect, search, catalog.*, install, setEnabled,
  reload, refresh, uninstall, uiDescriptors, credentials.inspect, sessionAction),
  `skills.*` (status, install, update, search, detail, bins, library.*, proposals.*,
  workshop.*, curator.*, upload.*), `tools.catalog`, `tools.effective`, `tools.invoke`,
  `tools.github.*`.
- **Cron/automation**: `cron.get/list/add/update/remove/run/runs/history/scratch.*`,
  `wake`, `hooks.status`.
- **Memory/doctor**: `memory.search/get/status`, `doctor.memory.*`, `migrations.memory.*`.
- **Logs/update/audit**: `logs.tail`, `update.run/status/hold/report/runs.*`,
  `audit.list`, `audit.activity.list`, `audit.run.inspect`, `backup.status`.
- **Talk/TTS/media**: `talk.*`, `tts.*`, `voicewake.*`, `talk.voice.*`.
- **Terminal/desktop/browser/computer**: `terminal.*`, `desktop.*`, `worker.desktop.*`,
  `computer.*`, `board.*`, `canvas.*`.
- **Users/profile**: `users.*` (self, list, prefs.*, setAvatar, setDisplayName, setRole,
  link*/unlink*, model accounts, github.*, background.*, personalFile.*, merge),
  `push.web.*`, `themes.*`.
- **Worktrees/cloud workers/environments**: `worktrees.*`, `environments.*`,
  `environments.session.*`.
- **Control UI helpers**: `ui.command`, `controlUi.githubPreview/githubDetail/linkPreview/
  sessionPreview/sessionPullRequests.*`.
- **Artifacts/transcripts**: `artifacts.list/get/download`, `transcripts.*`,
  `assistant.media.get`, `attach.grant/revoke`, `storage.locations.*`.

### 3.4 Event families

From `docs/gateway/protocol/rpc-bootstrap-and-events.md`:

- `chat` (delta/final/error/aborted; `deltaText`, `replace`, `message`, `errorDetail`),
  `agent` (assistant/tool/lifecycle/usage/items), `session.message`, `session.operation`,
  `session.tool`, `session.narration`, `session.approval`, `session.observer`,
  `sessions.changed`, `presence`, `tick`, `health`, `heartbeat`, `cron`, `shutdown`,
  `node.pair.requested/resolved`, `node.invoke.request`, `device.pair.requested/resolved`,
  `device.pair.setup.completed/deliveryUncertain`, `voicewake.changed`, `plugins.changed`,
  `config.changed`, `skills.changed`, `exec.approval.requested/resolved`,
  `plugin.approval.requested/resolved`.
- Session list bootstrap: `sessions.subscribe` with a `sessions.list` param object returns
  `{subscribed: true, list}` in one round trip; clients must listen for `sessions.changed`
  before the request.

### 3.5 HTTP endpoints

- Static Control UI + assets on the gateway port.
- Hosted widget surfaces: `/__openclaw__/canvas/`, `/__openclaw__/a2ui/`.
- Worker closed protocol: `/__openclaw__/worker` (separate admission).
- `POST /tools/invoke` (single tool, tool policy, 2 MB default body).
- OpenAI-compatible `/v1/*` (`docs/gateway/openai-http-api.md`) and OpenResponses
  (`docs/gateway/openresponses-http-api.md`).
- Media/avatar/background/workspace-icon routes; artifact downloads (inline base64 or
  short-lived HTTPS URL).

### 3.6 Suggested FastAPI + TS mapping

Do not clone the WS protocol 1:1 for v1. Keep the *envelope semantics* and a typed method
registry so the surface can grow:

- **REST (FastAPI)**: `GET/POST` for sessions, messages, agents, models, approvals, config.
  Return Pydantic models; use a stable error shape `{code, message, details, retryAfterMs?}`.
- **Streaming**: SSE (or WS) for `chat`/`agent` deltas. Preserve the delta/replace/snapshot
  contract (`deltaText`, `replace`, first-frame full `message` snapshot, terminal `final`/
  `error`/`aborted`) so the TS client logic ports directly.
- **Turn contract**: `POST /sessions/{id}/messages` returns `{runId, acceptedAt}` immediately;
  `GET /runs/{runId}` (or WS subscription) yields lifecycle/tool/assistant events;
  `POST /runs/{runId}/abort` cancels. This mirrors `agent` + `agent.wait` + `chat.*`.
- **Scopes**: model the operator scope set as a dependency; keep reserved admin-only families
  (`config.*`, approvals, update) explicit even if v1 has a single-user model.
- **Idempotency**: accept `Idempotency-Key` on side-effecting POSTs; dedupe cache server-side.
- **Auth**: v1 can rely on Databricks App identity (forwarded user) rather than device pairing,
  but keep an auth boundary object so scopes can be layered later.
- **Agent runtime**: pydantic-ai replaces `runEmbeddedAgent`. Preserve the per-session serialized
  lane, a durable writer claim for transcript appends, and the hook points (`before_tool_call`,
  `after_tool_call`, `before_agent_reply`, `agent_end`, message hooks) as middleware/events.
- **Storage**: Lakebase tables mirror the SQLite session index + transcript + run locks;
  workspace files mirror bootstrap files/skills. Keep a single-writer discipline per session
  (advisory lock / row claim) to preserve OpenClaw's fencing guarantee.

---

## 4. Open questions and porting risks

1. **Scope of v1 UI.** Chat + sessions + agents + models + approvals + config + usage is a lot.
   Should v1 ship chat + sessions + agents only, with config/models read-only?
2. **Streaming transport.** SSE vs WS for Databricks Apps. SSE is simpler behind App proxies;
   WS preserves OpenClaw's bidirectional control (`ui.command`, terminal). Recommend SSE for v1.
3. **Session/transcript schema.** OpenClaw's session row is very rich (creator/owner/participants,
   placement, sharing, usage, board membership). Decide the minimal Lakebase schema; do not
   mirror every column.
4. **Writer fencing on Lakebase.** SQLite WAL + writer queue + state-dir lock is the safety
   mechanism. Lakebase needs an equivalent (row-level `active_writer_run_id` CAS + advisory lock).
   How do we guarantee no stale transcript commit across multiple App instances?
5. **Tool execution surface.** Which built-in tools ship in v1? Databricks-hosted execution
   implies a sandbox boundary different from Docker/SSH. `exec`/`browser`/`terminal` likely
   defer; `web_fetch`, `web_search`, file read/write within the user workspace, and Databricks
   SQL/Unity Catalog tools are the interesting native ones.
6. **Channels.** Multi-channel is a huge surface. DatabricksClaw v1 likely has no external
   channels; the chat UI *is* the channel. Confirm channels are deferred entirely.
7. **Auth & multi-user.** OpenClaw scopes are explicitly "not hostile multi-tenant isolation."
   Databricks Apps give us a real user identity; decide whether sessions are per-user and how
   workspace paths are scoped (`{user workspace}/claw/agents/{name}/`).
8. **Prompt/skills compatibility.** Should we read OpenClaw's `AGENTS.md`/`SOUL.md`/`IDENTITY.md`
   formats verbatim (ADR-0002 implies yes) and support `SKILL.md` loading? This affects the
   agent workspace loader and system-prompt assembly.
9. **Model/provider layer.** OpenClaw's provider catalog is plugin-driven and enormous. v1 should
   target Databricks Foundation Model APIs + a small set (OpenAI/Anthropic) with a narrow
   provider interface rather than porting the plugin provider runtime.
10. **Approvals semantics.** OpenClaw's approval registry is durable, first-answer-wins, with
    expiry and push. A Databricks port may need this only if tools are dangerous; decide whether
    v1 has any tool requiring human approval.
11. **Protocol compatibility.** Is there any intent to make DatabricksClaw speak the OpenClaw
    protocol so existing clients/plugins work? If not, keep our own contract but borrow the
    delta/replace/terminal event semantics. (Recommend: own contract, borrow semantics.)
12. **Fidelity vs velocity.** The Control UI is ~50 routes and thousands of modules. Porting it
    wholesale is not viable. Recommend a fresh minimal TS client that reuses OpenClaw's *patterns*
    (route ids, session rail, composer, tool-activity rows) and the markdown/theme primitives,
    not the code.

---

## Appendix A — Reference file map

| Topic | Source |
| --- | --- |
| Architecture | `docs/concepts/architecture.md` |
| Agent runtime layout | `docs/agent-runtime-architecture.md` |
| Agent loop | `docs/concepts/agent-loop.md` |
| Sessions | `docs/concepts/session.md`, `docs/concepts/main-session.md` |
| Multi-user | `docs/concepts/multi-user.md` |
| Storage locations | `docs/concepts/storage-locations.md` |
| DB schemas | `docs/reference/database-schemas.md` |
| Gateway protocol | `docs/gateway/protocol.md` + `docs/gateway/protocol/*.md` |
| Operator scopes | `docs/gateway/operator-scopes.md` |
| Authentication | `docs/gateway/authentication.md` |
| Sandboxing | `docs/gateway/sandboxing.md` |
| Tools overview | `docs/tools/index.md` |
| Channels | `docs/channels/index.md` |
| Control UI | `docs/web/control-ui.md` + `docs/web/control-ui/*.md` |
| Dashboard architecture | `docs/web/dashboard-architecture.md` |
| Method table | `src/gateway/methods/core-descriptors.ts` |
| Protocol version | `packages/gateway-protocol/src/version.ts` |
| UI routes | `ui/src/app-route-paths.ts`, `ui/src/app-routes.ts` |
| UI navigation | `ui/src/app-navigation.ts` |
| UI pages | `ui/src/pages/*` |
| UI components | `ui/src/components/*` |
| Agent core | `packages/agent-core/src/*` |
| Plugin SDK | `packages/plugin-sdk/src/*` |
| Gateway client | `packages/gateway-client/src/*` |
