# OpenClaw Control UI — Screenshot Inventory

No browser or headless renderer was available in the exploration environment
(Safari only; no Chromium/Playwright/Puppeteer), and the Control UI is a
client-rendered Vite + Lit SPA that requires a running Gateway and built assets,
so **no PNGs were produced**. This file is the text-description inventory
instead: per screen, what a user sees, the controls, states, and the source
files that implement it.

Source snapshot: `openclaw/openclaw` @ `9cd23e6` (release `2026.9.9`).
All paths are relative to the OpenClaw repo root; in the local clone they live
under `/tmp/openclaw-src/`.

How to capture real screenshots later:

```bash
cd /tmp/openclaw-src
pnpm install
pnpm build
pnpm ui:build
pnpm openclaw gateway          # serves Control UI on http://127.0.0.1:18789/
# then, with any headless Chromium available:
#   playwright screenshot --viewport-size=1440,900 http://127.0.0.1:18789/ docs/openclaw-ui/01-chat.png
```

Route ids/paths: `ui/src/app-route-paths.ts` (`APP_ROUTE_DEFINITIONS`),
route table: `ui/src/app-routes.ts`, sidebar grouping: `ui/src/app-navigation.ts`.

Legend: **[v1]** = recommend porting to DatabricksClaw v1; **[defer]** = skip v1;
**[v1.1]** = nice-to-have after v1.

---

## 00. Connection gate / login

**Route:** none (rendered before the app shell when the WS is not connected or the
device is unpaired). **Docs:** `docs/web/control-ui/connect-and-pair.md`,
`docs/web/control-ui/offline-and-reconnect.md`.

**Layout / description**

- Centered card on the app background. Fields: **Gateway URL**, **Gateway secret**
  (token or password), optional **default session key**, and a **Connect** button.
- States: idle → connecting → "Waiting for approval" (device pairing) → connected
  or terminal error. Pairing wait shows the request id and a retry/back-off state;
  terminal outcomes are `PAIRING_REJECTED` / `PAIRING_EXPIRED`.
- Offline reload shows the same gate with a "last known" banner. The "busy initial
  connection" state shows shimmer placeholders and a "The server is busy. Please
  try again in a moment." message when the gateway request queue is full.
- Runtime config endpoint can auto-populate the URL (served from the Gateway).
- PWA install + web-push prompts appear here when enabled.

**Source:** `ui/src/app/bootstrap.ts`, `ui/src/app/connection-bootstrap.ts`,
`ui/src/app/browser-auth-recovery.ts`, `ui/src/app/control-ui-auth.ts`,
`ui/src/app/gateway-store.ts`, `ui/src/app/control-ui-presentation.ts`,
`ui/src/pages/connection/connection-page.ts` (connected variant).

**[v1]** — replace with Databricks App identity/session; keep the offline/busy UX.

---

## 01. Chat — main conversation

**Route:** `/chat` (plus `/chat/:sessionRef`). **Docs:** `docs/web/control-ui/chat.md`.

**Layout (desktop)**

- Left: **session rail / sidebar** (see 02). Center: **transcript**. Right/bottom:
  optional **side panel** (Dashboard, Terminal, Browser, Files, Review, Processes,
  Subagents, GitHub reader). Top: **chat header** (title, model/thinking controls,
  panel buttons, share/owner, presence).

**Transcript**

- Message bubbles with markdown (markdown-it + DOMPurify), code blocks with copy,
  images/video/PDF attachments, Mermaid diagrams, markdown tables, hosted embeds
  (YouTube etc.).
- **Tool activity rows** are kind-aware: shell commands show a syntax-highlighted
  command with terminal-style output; edit/write show bounded inline diffs with
  line numbers and `+added -removed`; consecutive calls collapse into a single
  expandable log ("13 commands · 6 reads · 9 edits"). Running call names the group
  header. Failed/blocked/skipped outcomes are called out.
- **Run summary**: completed turns collapse narration + tools under
  "Worked for 2 minutes, 3 seconds" (with failed counts). Streaming assistant text
  stays at the bottom of the run; saved text keeps its transcript position.
- Compact **"updates from"** rows for inter-session messages and compact rows for
  automation inputs (expandable to the full prompt).
- **Thinking** blocks, reasoning streams, and "keep commentary" preference.
- GitHub issue/PR links become chips with hover cards; session links are clickable.

**Composer**

- Multiline text with IME-safe Enter/Escape, attachment picker (images/PDF/video),
  paste, emoji shortcodes, `@` mentions, `/` slash-command palette, dictation
  microphone, model/thinking/fast/verbose/trace controls, queue-while-running,
  steer, undo/redo, and durable draft persistence across reloads and tabs.
- Disabled banner for archived sessions with **Unarchive**.

**Header / controls**

- Title rename (inline edit), session menu, share/visibility, owner chip,
  viewer facepile, presence/typing, Stop/Abort, return-to-latest, panels menu.

**Live behavior**

- Follow-at-end scrolling with manual interruption; placeholder skeletons during
  history load; error banner with **Details** and **Copy error**; run error clears
  on a newer successful run.
- History pagination: ~80 recent messages initially; scroll-back pages up to 1000;
  prefetch next page.

**Source (key modules):** `ui/src/pages/chat/chat-page.ts`,
`chat-pane.ts`, `chat-pane-render.ts`, `chat-pane-history.ts`,
`chat-pane-header.ts`, `chat-view.ts`, `chat-composer.ts`,
`chat-history.ts`, `chat-history-stream.ts`, `chat-send-*`, `chat-queue.ts`,
`chat-tool-activity-coalesce.ts`, `tool-stream.ts`, `chat-scroll-input.ts`,
`ui/src/components/session-menu.ts`, `ui/src/components/session-progress-card.ts`.

**[v1]** — the core surface to port.

---

## 02. Sidebar / session rail

**Part of:** every route (persistent shell). **Docs:**
`docs/web/control-ui/sessions-and-sidebar.md`.

**Layout**

- **Session list** grouped by custom groups / channel / kind / agent / date; pinning,
  drag-to-group, reorder, archive/snooze, unread dots, live-run indicator, preview
  text, and a small static tool icon beside the progress text for running sessions.
- **Attention items** panel (failures, approvals, update cards) and **outbox** items
  for unsent drafts/messages.
- **Online / people** block: compact person rows with presence dots (solid green
  active, amber idle, hollow ring connected-no-activity), running count and open
  count, hovercard with recent sessions, "Filter & sort" (All/Running; sort by
  active/running/total/name), reset to defaults.
- **Agent switcher / roster** cards, plugin entries that expand to nested
  destinations, and a **Customize** menu for the pinned zone.
- Footer: Settings, Docs, theme toggle, build chip.

**Session menu (kebab / right-click):** pin, rename, snooze (presets), fork,
archive/restore, assign owner (me / pick person or agent), mark read/unread,
share/visibility, delete.

**Source:** `ui/src/components/sidebar-*.ts`,
`session-menu.ts`, `session-organizer-*.ts`, `session-owner-chip.ts`,
`session-row-badges.ts`, `session-row-subtitle.ts`, `session-people-search.ts`,
`ui/src/app-navigation.ts`, `ui/src/components/settings-sidebar.ts`.

**[v1]** — port a simplified rail (list + status + unread + running + owner).

---

## 03. New Session

**Route:** `/new`. **Docs:** `docs/web/control-ui/sessions-and-sidebar.md`.

**Layout**

- Composer-first page with target controls: **where** (agent, folder/repo, cloud
  machine, node/device placement), **model** picker, **incognito** toggle,
  repository/checkout chip, and background-session notice.
- Draft persistence, attachment staging, and "start in a new session" flows.
- Placement choices: local workspace, Git worktree, cloud worker profile, connected
  device. Session-startup handoff navigates to the created session's chat.

**Source:** `ui/src/pages/new-session/*` (notably `new-session-page.ts`,
`composer.ts`, `draft-*.ts`, `target-controls.ts`, `placement` files),
`ui/src/app/app-shell-new-session.ts`.

**[v1]** — port a simplified "new session" (agent + title + model, no placement).

---

## 04. Sessions (Threads) page

**Route:** `/sessions` (+ `/worktrees` tab). **Docs:**
`docs/web/control-ui/feature-reference.md` ("Channels, sessions, memory").

**Layout**

- **Overview tiles**: session count, live runs, unread sessions, total tokens,
  archived count.
- **Filter/search** toolbar and **Group by** control (custom groups, channel, kind,
  agent, date).
- **Table**: kind glyph + live-run dot, status dot + label, title, owner avatar,
  channel, tokens/context meter, last activity, per-row kebab menu (mirrors the
  sidebar session menu), row drawer with agent runtime and run duration.
- **Worktrees** tab: git worktree list, create/remove/restore/gc.
- **Transcript search** view and pagination.

**Source:** `ui/src/pages/sessions/*` (`sessions-page.ts`, `view.ts`,
`sessions-filters.ts`, `custom-groups.ts`, `session-menu.ts`),
`ui/src/pages/worktrees/worktrees-page.ts`.

**[v1]** — port the table + filters; defer worktrees.

---

## 05. Approvals

**Route:** `/settings/approvals`. **Docs:**
`docs/web/control-ui/feature-reference.md`, `docs/gateway/protocol/rpc-devices-nodes-and-approvals.md`.

**Layout**

- **Pending approvals** cards (exec / plugin / system-agent) with request details,
  source session, and **Approve** / **Reject** actions. Deep links use `/approve`.
- **History** tab: newest-first terminal approvals retained 30 days, filter by kind,
  cursor pagination, decision/reason/resolver attribution.
- **Exec policy** editors: gateway and per-node allowlists / ask policy.

**Source:** `ui/src/pages/approvals/approvals-page.ts`,
`ui/src/pages/approval/approval-page.ts`, `approval-presentation.ts`,
`ui/src/app/exec-approval.ts`, `ui/src/app/approval-deep-link.ts`.

**[v1]** — port if any v1 tool needs human approval; otherwise stub.

---

## 06. Agents home

**Route:** `/agents`. **Docs:** `docs/web/control-ui/feature-reference.md`.

**Layout**

- Agent roster cards (avatar, name, emoji, model, status) with **New agent**.
- **New agent** opens the **custodian** chat which recommends roles
  (chief of staff, researcher, writer, reviewer, team) or accepts a custom
  description/name.

**Source:** `ui/src/pages/agents-home/*`, `ui/src/pages/custodian/*`.

**[v1]** — roster + simple create; defer custodian wizard.

---

## 07. Agent detail / settings

**Route:** `/settings/agents[/:agentId[/:panel]]`. **Docs:**
`docs/web/control-ui/settings.md` / `feature-reference.md`.

**Layout — tabs**

- **Overview**: identity (display name, emoji, avatar image with browser
  downscale), primary model + ordered fallback chain (chip list), and
  `IDENTITY.md` mirroring.
- **Files**: agent workspace file browser/editor with conflict callouts and
  preview.
- **Tools**: effective GitHub execution account, per-agent tool overrides,
  device authorization, one-use PAT setup.
- **Skills**: agent skill list/status.
- **Channels**: agent channel bindings.
- **Automations**: agent-scoped cron jobs.
- **Memory**: dreaming status/toggle, Dream Diary reader, Imported Insights /
  Memory Wiki sub-tabs (when `memory-wiki` enabled).

**Source:** `ui/src/pages/agents/*` (`agents-page.ts`, `view.ts`,
`panels-overview.ts`, `panels-files.ts`, `panels-tools-skills.ts`,
`panels-skills.ts`, `identity-actions.ts`, `model-config.ts`),
`ui/src/pages/config/memory-*.ts`.

**[v1]** — Overview + Files (bootstrap files) are the important ones.

---

## 08. Model providers / Models

**Route:** `/settings/model-providers`. **Docs:**
`docs/web/control-ui/feature-reference.md` ("Config").

**Layout**

- **Defaults for all agents**: model, utility model, fallback chain, thinking,
  fast-mode.
- **Provider cards**: brand icon, auth state (`models.authStatus`), model
  availability (`models.list`), live plan/quota/billing (`usage.status`), local
  30-day spend (`sessions.usage`), **Refresh**/**Retry**, connect/disconnect.
- **Connect provider** dialog: provider-first searchable list; credential entry;
  "On this Gateway" setup discovery; custom endpoints.
- **Provider access** filter and per-agent scoping; shared Settings sidebar selects
  the agent.

**Source:** `ui/src/pages/model-providers/*` (`model-providers-page.ts`, `view.ts`,
`profiles-view.ts`, `login-controller.ts`, `account-usage.ts`),
`ui/src/pages/model-setup/*`.

**[v1]** — port a Databricks-focused provider page (FM APIs + OpenAI/Anthropic).

---

## 09. Model setup (first run)

**Route:** `/settings/model-setup`. **Docs:** `feature-reference.md`.

**Layout**

- Provider picker → credential entry → live inference verification → activation.
- States: loading skeleton, first-run activation receipt, "settings not applied"
  and "restart required" banners, success dialog, retry.
- Uses `openclaw.setup.*` RPCs and wizard steps.

**Source:** `ui/src/pages/model-setup/*` (`model-setup-page.ts`, `wizard-runner.ts`,
`provider-picker.ts`, `first-run.ts`, `success-dialog.ts`).

**[v1.1]** — may collapse into the providers page.

---

## 10. Settings / Config

**Routes:** `/settings/general` (config), `/settings/advanced`, plus the settings
sub-pages. **Docs:** `docs/web/control-ui/settings.md`,
`feature-reference.md` ("Config").

**Layout**

- **Settings sidebar** groups: Ask OpenClaw / Profile / Appearance / Notifications;
  Connections (Gateway, Channels, Communications, Talk, Devices);
  Agents & Tools (Agents, Labs, Models, MCP, Memory, Automation);
  Privacy & Security (Security, Secrets, Approvals);
  System (Infrastructure, Advanced, Debug, Logs, About).
- **Schema-driven form** (`config.schema`, `config.schema.lookup`) with
  titles/descriptions, defaults shown in placeholders, SecretRef masking,
  save indicator, base-hash conflict guard.
- **Raw JSON5 editor** (only when safe round-trip), reset-to-saved preserving
  authored shape; "Settings not applied" banner with the validation reason.
- **Appearance**: language, theme (light/dark/system/custom), typography, terminal
  font, browser tab icon (agent avatar; square/rounded/circle).
- **Advanced**: every config section without a curated home + raw editor.

**Source:** `ui/src/pages/config/*` (`config-page.ts`, `view.ts`,
`view-schema.ts`, `view-appearance*.ts`, `memory-*.ts`, `security.ts`, `mcp.ts`,
`talk*.ts`), `ui/src/components/settings-*.ts`,
`ui/src/lib/config-form-utils.ts`.

**[v1]** — port a curated subset (agents/models/security/connection) + raw JSON.

---

## 11. Channels

**Route:** `/settings/channels` (alias `/channels`). **Docs:**
`docs/channels/*`, `feature-reference.md`.

**Layout**

- **Channel cards**: status, account, runtime state, refresh; QR/web login wizard;
  per-channel config (`config.patch`); DM **pairing requests** with
  approve/reject.
- WhatsApp/Nostr-specific sub-views; wizard controller for guided setup.
- "Channel settings" grouping shows one channel at a time including plugin
  channels; "Other" groups shared defaults.

**Source:** `ui/src/pages/channels/*` (`channels-page.ts`, `view.ts`,
`view.pairing.ts`, `view.whatsapp.ts`, `view.nostr*.ts`, `wizard-*.ts`),
`ui/src/lib/channels/*`.

**[v1]** — likely defer entirely; DatabricksClaw chat is the channel.

---

## 12. Automations (Cron)

**Route:** `/automations` (alias `/cron`). **Docs:**
`feature-reference.md` ("Automations panel notes").

**Layout**

- **Stat cards**: automation count, failing count, scheduler state, next wake.
- **Automations** tab: filterable table (All/Active/Paused, search, schedule,
  last-run) with per-row menu; starter suggestions; full-page detail with
  Active/Paused switch and **Run now**.
- **Run history** tab: recent runs across automations, per-automation runs,
  delivery-suppression reason.
- Create/edit form: prompt, details, frequency/cron, advanced overrides
  (delete-after-run, agent/model/thinking overrides, delivery mode:
  announce/none/webhook).

**Source:** `ui/src/pages/cron/*` (`cron-page.ts`, `view.ts`, `view-jobs-filter.ts`,
`view-runs.ts`, `form-suggestions.ts`), `ui/src/lib/cron/*`.

**[v1]** — port basic scheduled tasks if in scope; otherwise defer.

---

## 13. Usage

**Route:** `/usage`. **Docs:** `feature-reference.md` ("Usage").

**Layout**

- Provider cards (`usage.status`) with live plan/quota/balance/spend.
- Session/cost dashboard: filters (provider, model, channel, tool, `key:value`
  terms), date range, Local/UTC toggle, hourly charts + peak error hours,
  heatmap, session table, selected-session timeline with draggable interval
  handles, system-prompt breakdown, CSV/JSON export.

**Source:** `ui/src/pages/usage/*` (`usage-page.ts`, `view-*.ts`, `heatmap.ts`,
`query.ts`, `export.ts`).

**[v1]** — port a read-only token/cost summary if desired.

---

## 14. Logs

**Route:** `/logs`. **Docs:** `feature-reference.md` ("Debug, logs, update").

**Layout**

- Live tail of gateway file logs (`logs.tail`), level/namespace filters, search,
  pause, clear, export.

**Source:** `ui/src/pages/logs/*` (`logs-page.ts`, `view.ts`, `log-lines.ts`).

**[v1]** — port a simple log viewer (useful for a hosted app).

---

## 15. About

**Route:** `/settings/about`. **Docs:** `settings.md`.

**Layout**

- Version/build info, environment identity, community invitation, credits.

**Source:** `ui/src/pages/about/*`, `ui/src/app/build-info.ts`.

**[v1]** — trivial.

---

## 16. Systems

**Route:** `/systems`. **Docs:** `feature-reference.md` ("Debug, logs, update").

**Layout**

- Per-machine interactive history graphs: 1-minute load average (with logical core
  count), used memory, per-volume disk free space. Offline/stale readings muted
  with last-report time. Node meters when reported.

**Source:** `ui/src/pages/systems/*` (`systems-page.ts`, `systems-telemetry.ts`,
`systems-data.ts`, `systems-sidebar.ts`).

**[defer]** — Databricks Apps expose host metrics differently.

---

## 17. Debug + System busyness overlay

**Route:** `/debug`. **Docs:** `feature-reference.md`.

**Layout**

- Snapshots (status/health/models) on open/refresh; live command lanes and
  heartbeat; event log (up to 250 events, Control UI RPC timings); manual RPC
  caller; lane tables.
- **System busyness overlay**: expanded panel with CPU, RSS memory, event-loop
  delay, per-disk free-space graphs polled every 10s; minimizable to a
  bottom-right widget with CPU/memory/ping sparklines; lists running/queued
  sessions (up to 100).

**Source:** `ui/src/pages/debug/*` (`debug-page.ts`, `debug-overlay*.ts`,
`lane-table.ts`), `ui/src/app/overlays.ts`.

**[defer]**.

---

## 18. Activity / Live activity

**Route:** `/activity`. **Docs:** `feature-reference.md`.

**Layout**

- Browser-local, redaction-first summaries of live tool activity; current work
  view; run inspector with evidence and model details; session activity
  controller with git/media summaries and pulse window.

**Source:** `ui/src/pages/activity/*` (`activity-page.ts`, `view.ts`,
`run-inspector-view.ts`, `session-activity-view.ts`, `tool-activity.ts`).

**[defer]** (could revisit for observability).

---

## 19. Devices / Nodes

**Route:** `/settings/devices` (alias `/nodes`). **Docs:**
`feature-reference.md` ("Cron, plugins, skills, devices, exec approvals").

**Layout**

- Unified inventory: gateway host pinned first; paired clients with connection
  status, roles, tokens, capabilities, commands; duplicate pairings grouped;
  "Clean up N stale" bulk action; per-row **Actions** (copy device id, edit alias,
  remove, approve/reject pending re-approval); **Details** with identity/IP/scopes/
  token rotation/revocation/commands.
- Resource meters (host load/memory/disk/uptime) and node meters; capability
  chips; **Desktop** launch.
- Pending device pairing approve/reject and mobile setup-code creation.

**Source:** `ui/src/pages/devices/*`, `ui/src/pages/device/*`.

**[defer]**.

---

## 20. Plugins

**Routes:** `/plugins`, `/settings/plugins`, `/plugin`. **Docs:**
`feature-reference.md`.

**Layout**

- Installed inventory + curated store; search ClawHub; catalog detail with
  README/security/capabilities; install/remove/enable/disable; capability consent
  dialog; install-policy warning acknowledgement; install progress; per-plugin
  settings; plugin-contributed tabs; MCP server rows.

**Source:** `ui/src/pages/plugins/*`, `ui/src/pages/plugin/*`,
`ui/src/lib/plugins/*`.

**[defer]**.

---

## 21. Skills

**Routes:** `/skills`, `/settings/skills`, `/skills/workshop`. **Docs:**
`feature-reference.md`, `docs/tools/skills.md`.

**Layout**

- Skill catalog/status, enable/disable, install, API key updates; skill detail and
  preview; Skill Workshop authoring/review (changes, archive, restore).

**Source:** `ui/src/pages/skills/*`, `ui/src/pages/skill-workshop/*`.

**[defer]** — but note `SKILL.md` loading matters for the agent workspace.

---

## 22. Terminal panel / page

**Routes:** `/terminal` (page) + chat side panel. **Docs:**
`docs/web/control-ui/panels.md`.

**Layout**

- Tabs of PTY sessions; fullscreen; new-session control; font settings; drag-drop
  file upload (stages files and pastes shell-quoted paths); connection/ownership
  indicators; detached-session timeout.

**Source:** `ui/src/pages/terminal/terminal-page.ts`,
`ui/src/components/terminal/*`.

**[defer]** — no PTY surface in Databricks Apps v1.

---

## 23. Browser panel + Desktop

**Part of:** chat side panel (and `/dashboards` for browser dashboards).
**Docs:** `docs/web/control-ui/panels.md`, `docs/web/dashboards.md`.

**Layout**

- Browser: live screencast/screenshot fallback, tabs, URL bar, back/forward/reload,
  open-in-browser, remote input forwarding, paste, download, annotate/inspect
  capture modes.
- Desktop: standalone VNC-style desktop window for capable nodes.

**Source:** `ui/src/components/browser/*`, `ui/src/components/desktop/*`,
`ui/src/app/gateway-canvas-surface.ts`.

**[defer]**.

---

## 24. Dashboards / Workboard (widget boards)

**Routes:** `/dashboards`, `/workboard`. **Docs:**
`docs/web/dashboard-architecture.md`.

**Layout**

- Session-attached persistent widget board; tabs; fluid auto-compacting grid;
  drag/resize; pin widgets from transcript; swap/focus/layout controls; widget
  sandbox iframes with capability manifests; Workboard plugin pins/boards.

**Source:** `ui/src/pages/dashboards/*`, `ui/src/pages/workboard/*`,
`ui/src/components/board/*`, `ui/src/lib/board/*`.

**[defer]**.

---

## 25. Memory / Dreaming / Import

**Routes:** `/settings/memory`, `/memory-import`. **Docs:**
`feature-reference.md`.

**Layout**

- Memory status, dreaming toggle, Dream Diary reader; Imported Insights / Memory
  Wiki sub-tabs (clustered synthesis, entities, concepts, claims, contradictions,
  inline previews); Import Memory preview/apply from Claude Code / Codex / Hermes.

**Source:** `ui/src/pages/config/memory-*.ts`, `ui/src/pages/memory-import/*`.

**[defer]** — relevant later for memory features.

---

## 26. Profile / Secrets / MCP / Labs / Talk / Updates / Meetings / Apps / Portals

- **Profile** `/settings/profile`: default agent identity, person profile, verified
  sign-in identity, Git co-author consent, model accounts, GitHub connections.
  Source: `ui/src/pages/profile/*`. **[v1.1]**
- **Secrets** `/settings/secrets`: team secret/env store (`secrets.store.*`).
  Source: `ui/src/pages/secrets/*`. **[defer]**
- **MCP** `/settings/mcp`: MCP server rows (transport, enablement, OAuth/filter/
  parallel), add/enable/disable/remove, scoped config. Source:
  `ui/src/pages/config/mcp.ts`. **[defer]**
- **Labs** `/settings/labs`: Code Mode, Tool Search, custom plugin UI, host
  desktop, cloud worker desktop. Source: `ui/src/pages/labs/*`. **[defer]**
- **Talk** `/settings/talk`: realtime voice provider/model/voice pickers from
  `talk.catalog`. Source: `ui/src/pages/config/talk*.ts`. **[defer]**
- **Updates** `/settings/updates`: run package/git update + restart report
  (`update.run`, `update.status`). Source: `ui/src/pages/config/updates*.ts`.
  **[defer]**
- **Meetings** `/meetings`: meeting capture/transcripts. Source:
  `ui/src/pages/meetings/*`. **[defer]**
- **Apps** `/apps`: companion apps/extensions + chrome setup. Source:
  `ui/src/pages/apps/*`. **[defer]**
- **Portals** `/portals`: portal surfaces. Source: `ui/src/pages/portals/*`.
  **[defer]**
- **Custodian** `/custodian`: guided agent creation chat. Source:
  `ui/src/pages/custodian/*`. **[defer]**
- **Lobsterdex** `/settings/lobsterdex`: community/art surface. **[defer]**
- **Search** `/settings/search`: web search provider config. **[v1.1]**

---

## Appendix — shared shell / design system

- **App shell**: `ui/src/app/app-shell-view.ts`, `app-shell-chrome.ts`,
  `app-shell-navigation.ts`, `app-host.ts`, `app-root.ts`.
- **Design system**: Web Awesome (`@awesome.me/webawesome`) + Lit 3; theme tokens
  in `ui/src/app/theme-*.ts`, `ui/src/lib/theme-*.ts`, `ui/public/themes/`.
- **Command palette**: `ui/src/app/app-shell-command-palette-loading.ts` and
  `docs/web/control-ui/sessions-and-sidebar.md` ("Command palette").
- **Keyboard shortcuts**: `ui/src/lib/keyboard-shortcut-catalog.ts`,
  `keyboard-shortcuts.ts`.
- **Markdown rendering**: `packages/markdown-core`, `ui/src/lib/markdown-dom-reconciler.ts`.
- **Notifications/toasts**: `ui/src/app/notifications-auto-prompt.ts`,
  `ui/src/lib/toast.ts`, `ui/src/components/sidebar-notification-card.ts`.
