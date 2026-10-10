# ADR-0002: Lakebase plus user workspace storage

Date: 2026-10-10
Status: accepted (partially amended by [ADR-0005](0005-platform-controlled-agent.md): agent personal files are platform-owned, not per-user, in v1)

## Context

DatabricksClaw needs two kinds of state: structured session/transcript state and per-agent personal files (`AGENTS.md`, `SOUL.md`, `IDENTITY.md`, `USER.md`, `MEMORY.md`, `skills/`, `context/`, `memory/` under `{user workspace}/claw/agents/{name}/`).

## Decision

- Structured state (sessions, transcripts, run locks): Lakebase.
- Personal files (bootstrap files, skills, context): user workspace (workspace files / Volumes path per user).

`resolve_agent_workspace(root, agent_name)` takes the user-workspace root; transcript store is a Lakebase-backed dependency injected into the turn orchestrator.

## Consequences

- `app_entrypoint` and `session_store` build on Lakebase; bootstrap/skills modules read from workspace paths.
- Permissions follow both layers: Lakebase row/table grants plus workspace file ACLs / Unity Catalog grants.
- Migration/backup must cover both stores, not one.
