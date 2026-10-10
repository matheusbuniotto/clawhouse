# ADR-0004: UI v1 is 5 screens

Date: 2026-10-10
Status: accepted (review vote: UI-OpenClaw ❌ full list → 4-5 screens)

## Context

The OpenClaw inventory (`docs/openclaw-DESIGN.md` §2, `docs/openclaw-ui/SCREENSHOTS.md`) proposes a large v1 copy list (~15 routes). Review decision: start with 4-5 screens only.

## Decision

v1 ships exactly 5 screens:

1. **Chat** (`/chat`) — main conversation + streaming + tool-call display + error states.
2. **Sessions** (`/sessions`) — list, switch, history.
3. **New session** (`/new`) — minimal compose (agent, placement).
4. **Approvals** (`/approvals`) — pending tool approvals + history.
5. **Status** — connection/auth snapshot + run status + log tail link (trimmed from OpenClaw connection/logs/about).

Everything else (channels, cron/automations, usage, skills, plugins, devices/nodes, model setup, config editor, memory, terminal/browser, dashboards) is deferred past v1.

## Consequences

- FastAPI serves 5 TS views + chat/sessions/approvals/status endpoints with SSE for turns.
- Frontend ticket builds 5 screens only; any 6th screen needs a new decision.
