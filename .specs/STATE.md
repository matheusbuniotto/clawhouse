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

## Handoff

**Feature**: openclaw-quickwins
**Where**: Complete - Verified PASS (16/16 checks proven)
**In progress**: none
**Next step**: Ready to commit and ship or choose the next feature slice
**Blockers**: none
**Uncommitted**: frontend changes, static build, .specs/
**Branch**: main
