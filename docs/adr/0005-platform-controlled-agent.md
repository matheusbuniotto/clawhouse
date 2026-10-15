# ADR-0005: One platform-controlled agent, files in a Git-versioned workspace folder

Date: 2026-10-10
Status: accepted
Related: [ADR-0002 Lakebase + user workspace storage](0002-lakebase-workspace-storage.md), [issue #1 spec](https://github.com/matheusbuniotto/clawhouse/issues/1)

## Context

The spec framed the agent's personal folder as `{user workspace}/claw/agents/{name}/` and stories 8–14 as an "agent owner" editing `AGENTS.md`, `SOUL.md`, `IDENTITY.md`, `USER.md`, and `MEMORY.md`. That implies a per-user file hierarchy owned by the end user. Grilling the open questions surfaced two facts that pull the other way:

- Databricks Apps run as a **service principal**; reading or writing a user's `{user workspace}` requires the forwarded on-behalf-of user token (Public Preview), not the SP. Isolation across users then depends on **our** path mapping unless the substrate enforces it.
- For MVP, the product needs exactly **one** agent, like OpenClaw's `main` — not user-authored agents.

Carrying a per-user file layer for a single builtin agent would import multi-tenant file isolation, ACL handling, and a public-preview auth dependency that v1 does not need.

## Decision

v1 ships **one platform-controlled builtin agent** (`main`).

- Its files (`AGENTS.md`, `SOUL.md`, `IDENTITY.md`, `USER.md`, `MEMORY.md`, `skills/`, `context/`) live in a **platform-owned Workspace Git folder**, alongside the app, and are **versioned by Git**.
- The app is **read-only** over these files. The operator changes the agent's persona, instructions, skills, and context by **committing to that folder** — there is no in-app file editor and no per-user file layer.
- `resolve_agent_workspace(root, agent_name)` resolves against this single platform root, not a user root. It stays a pure path composer.
- The per-user dimension in v1 is the **Lakebase session/transcript owner**, not a filesystem path. Users see only their own sessions.
- User-authored / per-user agents are **post-v1**; they are the point at which a per-user root and its isolation model get designed.

## Considered options

- **Per-user agent files** (original ADR-0002 framing): rejected for v1 — demands multi-tenant isolation we cannot cheaply enforce (SP vs on-behalf-of token), and there is only one builtin agent to isolate.
- **Shared UC Volume with per-user subdirectories**: rejected — UC `GRANT`s apply at volume level, so per-user isolation would still be app-enforced, and it adds volume/grant setup for a handful of markdown files.
- **Workspace Git folder, operator-edited (chosen)**: gives free versioning, keeps per-user isolation out of v1, and makes skills "drop a `SKILL.md` in the repo" rather than an authoring feature.

## Consequences

- **Partially amends ADR-0002**: structured state is still Lakebase, but "personal files in the user workspace" is deferred; agent files are platform-owned, not per-user.
- The spec's stories 8–14 are satisfied by the **platform operator** working through Git, not by end users.
- The bootstrap budget and truncation policy (`AGENTS 8k, SOUL 4k, IDENTITY 4k, USER 4k, MEMORY 8k`, total 20k; truncate `MEMORY → USER → IDENTITY → SOUL`, `AGENTS.md` never) applies to this single platform agent.
- A future per-user or user-authored agent feature must revisit this ADR and design the isolation model it deliberately omitted.
