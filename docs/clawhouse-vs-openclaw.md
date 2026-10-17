# Clawhouse vs OpenClaw — capability gap and opportunity assessment

Goal: make Clawhouse the obvious choice over OpenClaw for a **data team on Databricks**, not a
feature-for-feature clone.

Evidence base:

- OpenClaw source: `https://github.com/openclaw/openclaw` @ `30184f85d02ec9d34918c39c1017b9026bc36522`
  (`main`, release `2026.10.4`, read from a sparse clone at `/tmp/openclaw-real`). File links below
  use `blob/30184f85…`.
- Clawhouse source: `src/clawhouse/`, `AGENTS.md`, `.specs/STATE.md`, `docs/adr/`.
- A prior inventory exists at `docs/openclaw-DESIGN.md` and `docs/openclaw-ui/SCREENSHOTS.md`, but it
  targets OpenClaw `9cd23e6` (`2026.9.9`); where it disagrees with the `2026.10.4` source, this
  document wins.

Legend: **F** = how often a Databricks data user hits the gap (1–5); **A** = strength of a
Databricks-only advantage if Clawhouse builds it (1–5). `unverified` marks a claim not confirmed
against running code.

---

## 1. OpenClaw user-facing capabilities, with evidence

| # | Capability | Evidence (file / URL) |
| --- | --- | --- |
| 1 | Multi-channel messaging (Discord, Slack, Telegram, WhatsApp, Signal, iMessage, Teams, Matrix, IRC, ~25 channels) | `docs/concepts/features.md`; `docs/channels/index.md`; route `channels` in `ui/src/app-route-paths.ts:56` |
| 2 | Browser Control UI: chat, sessions, approvals, agents, models, config, usage, automations | `ui/src/app-route-paths.ts:40-103`; `docs/web/control-ui/feature-reference.md` |
| 3 | Agent loop with tool streaming, per-session lane, 48h budget | `docs/concepts/agent-loop.md`; `packages/agent-core/` |
| 4 | Sessions: create, rename, fork, rewind, compact, archive, snooze, groups, unread, usage | `docs/web/control-ui/feature-reference.md` ("Threads"); `docs/concepts/session.md` |
| 5 | Session transcript search (`sessions_search`) | `docs/concepts/session-search.md` |
| 6 | Markdown memory files + search, dreaming, Memory Wiki, memory import | `docs/concepts/memory.md`; `docs/concepts/memory-architecture.md`; `docs/concepts/dreaming.md` |
| 7 | Skills (AgentSkills), Skill Workshop, self-learning | `docs/tools/skills.md`; `docs/tools/skill-workshop.md`; `docs/tools/self-learning.md` |
| 8 | MCP **client** (Streamable HTTP/SSE/stdio + OAuth) | `docs/tools/mcp.md` |
| 9 | MCP **server** (`openclaw mcp serve`) | `docs/cli/mcp`; `docs/tools/mcp.md` |
| 10 | Plugins + ClawHub marketplace (~166 bundled extensions) | `docs/tools/plugin.md`; `https://docs.openclaw.ai/clawhub`; `extensions/` |
| 11 | Cron / automations, webhooks, heartbeat, standing orders | `docs/automation/cron-jobs.md`; `docs/automation/standing-orders.md` |
| 12 | Sub-agents (background, per-session) | `docs/tools/subagents.md` |
| 13 | Swarm (concurrent agent orchestration from code) | `docs/tools/swarm.md` |
| 14 | Code Mode + Tool Search (many tool calls in one sandboxed program) | `docs/tools/code-mode.md`; `docs/tools/tool-search.md` |
| 15 | Exec / process / terminal / sandboxing (Docker, SSH, cloud workers) | `docs/tools/exec.md`; `docs/gateway/sandboxing.md` |
| 16 | Files: read/write/edit/apply_patch over workspace | `docs/tools/apply-patch.md`; `docs/tools/index.md` |
| 17 | Browser automation | `docs/tools/browser.md` |
| 18 | Web search (13 providers) + web fetch | `docs/tools/web.md`; `docs/tools/web-fetch.md` |
| 19 | Goal (durable per-session objective, tool-observed) | `docs/tools/goal.md` |
| 20 | Progress card (durable step list in the transcript) | `docs/tools/progress-card.md` |
| 21 | ask_user (structured human decision) + secrets tool | `docs/tools/ask-user.md`; `docs/tools/secrets.md` |
| 22 | Exec approvals + policy history | `docs/tools/exec-approvals.md`; `docs/web/control-ui/feature-reference.md` |
| 23 | Media: view images, image/music/video generation, TTS, transcription | `docs/tools/media-overview.md`; `docs/tools/tts.md` |
| 24 | Realtime voice / Talk | `docs/web/control-ui/feature-reference.md` ("Talk") |
| 25 | Nodes / devices: macOS app, iOS/Android nodes, desktop, pairing | `docs/nodes/`; `docs/web/control-ui/feature-reference.md` |
| 26 | Model providers (~90), subscription OAuth, failover | `docs/providers/`; `docs/concepts/model-failover.md` |
| 27 | Usage tracking (provider quota/spend) + cost dashboard | `docs/concepts/usage-tracking.md`; `docs/reference/api-usage-costs.md` |
| 28 | Dashboards / A2UI / Workboard | `docs/web/dashboards.md`; `docs/web/dashboard-architecture.md`; route `workboard` `ui/src/app-route-paths.ts:80` |
| 29 | OpenAI-compatible API (`/v1/chat/completions`, `/v1/responses`) | `docs/start/why-openclaw.md` (Open standards); `docs/gateway` |
| 30 | Managed git worktrees | `docs/concepts/managed-worktrees.md` |
| 31 | OpenTelemetry + Prometheus | `docs/gateway/opentelemetry.md` (note: Prometheus page not located in clone — `unverified`) |
| 32 | External harness runtimes (Codex, Claude Code, Copilot) via ACP | `docs/concepts/agent-runtimes.md`; `docs/tools/acp-agents.md` |
| 33 | Themes / appearance; i18n | route `appearance` `ui/src/app-route-paths.ts:62`; `ui/src/i18n/` |
| 34 | PDF/document understanding | `docs/tools/pdf.md` |

OpenClaw scale evidence: ~470 unique gateway RPC methods (`docs/openclaw-DESIGN.md` §1.2, from
`src/gateway/methods/core-descriptors.ts`), 1,374 docs pages in the clone, 166 bundled extensions,
~74 provider docs, 55 PRs in `2026.10.4` (`CHANGELOG/2026.10.4.md`).

OpenClaw issue pressure (frequency signal, `api.github.com` search on 2026-10-17):
6,205 open issues. Recent P1s are update/gateway/crash-loop defects (`#175862`, `#175861`,
`#175848`), not missing data features — i.e. OpenClaw's own churn is operational, so Clawhouse
should not chase parity breadth (`unverified` as a trend beyond the sample).

---

## 2. Capability → Clawhouse status

| OpenClaw capability | Clawhouse status | Proof |
| --- | --- | --- |
| Web chat, streaming turns | **present** | `src/clawhouse/api/app.py` `_stream_turn`/`_sse` (~L1356–1432); `src/clawhouse/static/chat.js` |
| Markdown render, code highlight, copy, tables | **present** | `src/clawhouse/static/transcript.js` (`renderMarkdown` L405, `codeBlock` L500); `highlight.js` |
| Tool activity rows | **present** | SSE `tool_call`/`tool_result` (`app.py` L1371–1375); `transcript.js` |
| Inline approvals + approvals screen/history | **present** | `approval_required` (`app.py` L1377); `pydantic_ai_harness.guardrails` (`agent/turn.py` L41, L496); `/api/approvals` (`app.py` L643–671); `static/approvals.js` |
| `ask_user` structured question | **present** | `capabilities/interaction.py`; `/api/questions` (`app.py` L673–682); `static/cards.js` |
| `report_progress` card | **present** | `capabilities/interaction.py` (`REPORT_PROGRESS`); `static/cards.js` `upsertProgressCard` |
| Sessions: list/create/rename/delete/clear/compact | **present** | `store/store.py` L189–201, L333–419; `/api/sessions*` (`app.py` L487–569); `commands.py` `/compact`,`/clear` |
| Sessions: fork / rewind / archive / snooze / groups / unread | **missing** | no `fork`/`archive`/`snooze` in `store/store.py`; `session-management` feature is rename/mgmt only (`.specs/features/session-management/`) |
| Session transcript search | **missing** | no search method in `store/store.py`; no `/api/search` route in `app.py` |
| Multi-agent (`@agent`) persona routing | **present** (weaker: single-turn persona switch, not subprocess) | `agent/roster.py`; `capabilities/mentions.py`; AGENTS.md "Single-turn agent delegation" |
| Sub-agents / parallel background runs | **missing** | no spawn/parallel run path in `agent/turn.py`; one `run_turn` seam |
| Swarm / Code Mode / Tool Search | **missing** | no `CodeMode`/`tool_search` in `src/clawhouse/` |
| Skills (AgentSkills library) | **present** (read-only) | `capabilities/skills.py` (`pydantic_ai_harness.Skills`); `claw/agents/main/skills/` |
| Skill authoring / workshop / self-learning | **missing** | no authoring path; skills are repo files (ADR-0005) |
| MCP client | **present** (HTTPS only) | `capabilities/mcp.py`; wired into the turn at `agent/turn.py` L796 |
| MCP server (expose Clawhouse) | **missing** | no `mcp serve`; `api/app.py` has no MCP server route |
| Plugins / marketplace | **missing** | no plugin loader; `capabilities/__init__.py` is a fixed list |
| Cron schedules | **present** | `capabilities/schedules.py`; `/schedule` in `commands.py`; `/api/schedules` (`app.py` L944–1003) |
| Cron webhooks / IMAP / heartbeat / standing orders | **missing** | `schedules.py` supports cron only |
| Exec / shell / sandbox | **missing** | no `exec`/subprocess tool in `src/clawhouse/` (grep); only harness `Skills`+`guardrails`+`compaction` |
| Files read/write/edit in agent workspace | **missing** (agent has no file tools; workspace is prompt context only) | `capabilities/workspace.py` composes paths; `bootstrap.py` reads read-only |
| Browser automation | **missing** | none in `src/clawhouse/` |
| Web search / web fetch | **missing** | none; only `system_ai_query` (`databricks.py` L422) |
| Goal / standing intents | **missing** | no goal in `store/store.py` or `turn.py` |
| Media (image/audio/video/TTS) | **missing** | none |
| Realtime voice / Talk | **missing** | none |
| Nodes / mobile devices | **missing** | web only |
| Model providers + selection | **present** | `agent/model.py`; `/api/models` (`app.py` L473); ADR-0006 |
| Model failover chain | **missing** | `model.py` resolves one default; no fallback chain |
| Provider usage/quota dashboard | **missing** | `telemetry.py` is tracing only; no `/api/usage` |
| Cost tracking | **partial** — token/context usage + evals, no cost | `capabilities/mentions.py` `ReportContextUsage`; `evals.py` |
| Dashboards / A2UI / Workboard | **missing** | 7 screens (Chat, Sessions, New, Approvals, Status, Agents, Jobs); rail has 6 links, `static/index.html` L88–95 |
| OpenAI-compatible API | **missing** | no `/v1/*` in `app.py` |
| Git worktrees / repo edits | **missing** | none; Databricks Jobs tools create workspace files (`databricks.py` `_save_workspace_sql_file` L486) |
| OTel tracing | **present** | `telemetry.py`; ADR-0008; `docs/adr/0008-opentelemetry-runtime-telemetry.md` |
| External harness runtimes (Codex/Claude) | **missing** | Pydantic AI runtime only (ADR-0003) |
| Themes / appearance | **partial** — token layer + `data-theme`, no settings UI | `static/tokens.css` (`data-theme`); no appearance route |
| Secrets management | **partial** — model keys via env; MCP token scrubbed | `agent/model.py` (`api_key_env`); `capabilities/mcp.py` `scrub_token`; OBO identity (`api/identity.py`) |
| Multi-user identity / auth | **present, different model** — Databricks SSO + OBO, no device pairing | `api/identity.py`; ADR-0005 |
| PDF/document understanding | **missing** | none |
| **Databricks-native (no OpenClaw peer):** UC discovery, DBSQL, Jobs lifecycle, agentic Jobs via `ai_query`, Google Sheets, Slack/webhook delivery | **present** | `capabilities/databricks.py` (`all_tools` L951–969); `capabilities/sheets.py`; `/api/jobs` (`api/jobs.py`); AGENTS.md |

`docs/openclaw-ui/CURRENT-STATE.md` (dated 2026-10-11) describes only 5 screens and no shell; it is
**stale** — the live tree has a persistent shell, Agents and Jobs screens (`static/index.html`
L88–95, `app.py` L363–370). Do not cite it as current.

---

## 3. Missing capabilities, ranked for a Databricks data team

Ranked by `F × A`. The top rows are also where OpenClaw cannot follow.

| Rank | Missing capability | F | A | Why | OpenClaw reference |
| --- | --- | --- | --- | --- | --- |
| 1 | **Governed code execution** on Databricks compute (Python/Spark/notebooks under the user's identity over UC data) | 5 | 5 | Every real data task needs pandas/Spark, not just SQL; Databricks gives serverless/cluster compute + governance instead of a local sandbox | `docs/tools/exec.md`, `docs/tools/code-execution.md`, `docs/gateway/sandboxing.md` |
| 2 | **Durable, searchable memory grounded in Unity Catalog** | 5 | 5 | Data teams repeat schema/business-definition context; UC metadata + lineage can auto-seed and verify memory | `docs/concepts/memory.md`, `docs/concepts/memory-architecture.md` |
| 3 | **Session transcript search / recall** | 5 | 4 | "We solved this last month" is constant; Lakebase already stores every transcript | `docs/concepts/session-search.md` |
| 4 | **Cost & usage ledger** from `system.billing` + serving + agent usage | 4 | 5 | Cost is the data team's own KPI; OpenClaw can only estimate provider spend | `docs/concepts/usage-tracking.md`, `docs/reference/api-usage-costs.md` |
| 5 | **Sub-agents / parallel delegation** | 4 | 3 | Long analyses want fan-out; each subagent could be a Lakeflow run | `docs/tools/subagents.md` |
| 6 | **Dashboards / A2UI / Workboard** | 3 | 4 | Databricks AI/BI dashboards are the native output | `docs/web/dashboards.md` |
| 7 | **Secrets management UI/secret scopes** | 3 | 4 | Databricks Secret Scopes are native | `docs/gateway/secrets.md` |
| 8 | **Channels (Slack/Teams)** | 5 | 2 | Data teams live in Slack, but Databricks gives no advantage | `docs/concepts/features.md`, `docs/channels/` |
| 9 | **Rich cron (webhooks, IMAP, heartbeat, standing orders)** | 3 | 3 | Event-driven pipelines | `docs/automation/` |
| 10 | **Goals / standing intents** | 3 | 3 | Long-lived objectives | `docs/tools/goal.md`, `docs/concepts/standing-intents.md` |
| 11 | **Browser automation / web search** | 3 | 2 | Docs lookup; no Databricks edge | `docs/tools/browser.md`, `docs/tools/web.md` |
| 12 | **Plugins / marketplace** | 3 | 2 | Ecosystem, but a data moat is built from UC/Jobs, not plugins | `docs/tools/plugin.md`, `https://docs.openclaw.ai/clawhub` |
| 13 | **Code Mode / Tool Search** | 3 | 2 | Efficiency, not capability | `docs/tools/code-mode.md`, `docs/tools/tool-search.md` |
| 14 | **MCP server (expose Clawhouse)** | 2 | 2 | Nice interop, low frequency | `docs/tools/mcp.md` |
| 15 | **PDF/doc understanding** | 2 | 2 | — | `docs/tools/pdf.md` |
| 16 | **Session fork/rewind/archive/snooze/groups** | 2 | 1 | QoL, no data advantage | `docs/web/control-ui/feature-reference.md` |
| 17 | **Media / voice / nodes** | 2 | 1 | Not a data-team job | `docs/tools/media-overview.md`, `docs/nodes/` |
| 18 | **External harnesses (Codex/Claude/Copilot)** | 2 | 1 | — | `docs/concepts/agent-runtimes.md` |

---

## 4. Things OpenClaw cannot do that Clawhouse can, because of Databricks

1. **Governed execution on the data platform.** OpenClaw's `exec`/sandbox runs on the user's machine
   or a container (`docs/gateway/sandboxing.md`). Clawhouse *could* run Python/Spark/notebooks on
   Databricks serverless or a cluster, under the forwarded OBO user token, against UC-governed data,
   with results landing in governed tables — not built yet (see `governed-data-execution`). OpenClaw
   has no notion of UC grants or compute policy. Evidence of the Clawhouse identity/compute
   substrate: `api/identity.py`, `capabilities/databricks.py` (`_call` user-client with ambient
   fallback L328–347), ADR-0005.
2. **Data-estate intelligence from Unity Catalog and system tables.** "Who can read this table?",
   "what jobs and dashboards depend on it?", "what broke the 4am run?", "what changed in this schema
   last week?" become answerable from UC metadata, lineage, and `system.*` tables — not built yet
   (see `data-estate-intelligence`). OpenClaw has no first-party catalog, lineage, audit, or billing
   tool (`docs/tools/index.md` lists none). Clawhouse already talks to UC and Jobs
   (`capabilities/databricks.py` L336–485) — the gap is lineage/permission/audit reads, not the
   connection.
3. **Native Databricks cost and governance accounting.** `system.billing.usage`,
   `system.access.audit`, and serving-endpoint usage could give exact, governed numbers; not built
   yet (runner-up `cost-usage-ledger`). OpenClaw's usage page is provider-reported quota/spend or
   local estimates (`docs/concepts/usage-tracking.md`).

Runner-up Databricks-only advantage: **event-driven Lakeflow triggers** (file arrival, table update)
as first-class schedules — OpenClaw's scheduler is cron/heartbeat only (`docs/automation/cron-jobs.md`).

---

## 5. Top 3 intents

Chosen as the best `F × A` opportunities that also create a Databricks moat. Each is written as an
intent under `.specs/features/` (no code yet).

1. **`governed-data-execution`** — run Python/Spark/notebook code on Databricks compute under the
   user's identity, over UC data, instead of a local sandbox. (Parity gap #1 + perfect Databricks fit.)
2. **`unity-catalog-memory`** — durable, searchable memory and transcript recall grounded in Unity
   Catalog metadata and lineage. (Parity gaps #2 and #3 + Databricks fit.)
3. **`data-estate-intelligence`** — answer permission, lineage, impact, and run-failure questions
   from UC and `system.*` tables. (Databricks-only; the strongest "obvious choice" hook.)

Runner-up: `cost-usage-ledger` (parity gap #4). Not written as an intent in this pass.
