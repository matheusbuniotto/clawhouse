# Project state

## Decisions

Project-level architectural decisions are recorded as ADRs in `docs/adr/`:

| ID | Decision | Rationale | Status | Date |
| --- | --- | --- | --- | --- |
| ADR-0001 | FastAPI backend, TypeScript/HTML frontend served by App | Single deployment container, minimal hops behind Databricks App proxy | active | 2026-10-10 |
| ADR-0002 | Lakebase for structured state; user workspace for personal files | Relational integrity for turns/approvals, workspace files for agents | active | 2026-10-10 |
| ADR-0003 | Pydantic AI as the agent turn runtime | Typed agent loop, native streaming, harness capabilities | active | 2026-10-10 |
| ADR-0004 | UI v1 is 5 screens: chat, sessions, new, approvals, status | Lean coherent surface covering essential OpenClaw control plane | active | 2026-10-10 |
| ADR-0005 | Platform-controlled agent runtime with inline approvals | Ambient client fallback for platform permissions + gated mutation | active | 2026-10-10 |
| ADR-0006 | Pluggable model providers with Databricks Foundation Models | Enterprise LLM routing via WorkspaceClient / Model Serving | active | 2026-10-10 |
| ADR-0007 | First-hatch customization via user workspace | User-specific instructions without redeploying backend | active | 2026-10-10 |
| ADR-0008 | OpenTelemetry runtime telemetry with Logfire / OTLP fallback | First-party Pydantic AI instrumentation + zero heavy extra dependencies | active | 2026-10-16 |
| ADR-0009 | User-code execution and estate reads use only the forwarded user token, fail closed | Ambient SP fallback is limited to platform-resource management | active | 2026-10-17 |

## Handoff

**Feature**: native-model-messages
**Where**: Completed and squashed into main (PR #107 closed issue #79)
**In progress**: Idle / ready for next sub-issue in Epic #77 (Issue #83 [6/14])
**Next step**: Plan feature for Issue #83
**Blockers**: none
**Uncommitted**: none
**Branch**: main
