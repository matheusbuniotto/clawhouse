# ADR-0009: User-code execution and estate reads never use the ambient service principal

Date: 2026-10-17
Status: accepted
Related: [ADR-0005 platform-controlled agent](0005-platform-controlled-agent.md),
[ADR-0002 Lakebase + workspace storage](0002-lakebase-workspace-storage.md)

## Context

ADR-0005 requires capabilities to provide an ambient `WorkspaceClient()` fallback (the app service
principal) for **platform resources** — workspace files, job CRUD — while attributing actions to the
user. That fallback exists because forwarded OBO tokens may lack workspace-write or warehouse
enumeration permissions (`AGENTS.md`, "Databricks Apps ambient client fallback").

Two new capabilities break that rule if they inherit it:

- **Governed data execution** runs arbitrary user-authored code. If the ambient service principal
  runs it, the code executes with platform privileges, not the caller's Unity Catalog grants.
- **Data-estate intelligence** reads grants and lineage. If the ambient service principal reads
  them, it can disclose metadata the caller is not allowed to see.

Both are user-attributed reads/actions over governed data, not platform-resource management. The
fallback is safe only when the action is Clawhouse managing its own platform objects.

## Decision

Any capability that executes user-authored code, or reads user-visible governance metadata, MUST use
only the forwarded user token and MUST fail closed when it is absent or insufficient.

- `run_python_analysis` never calls `jobs_identity` and never uses `CLAWHOUSE_JOBS_SP_*`. With no
  user token it returns `{"error": "user token required"}`.
- Estate reads (`uc_list_grants`, lineage, run-failure analysis) call the forwarded
  `WorkspaceClient` directly, not `DatabricksTools._call`, and return
  `{"error": "not visible to you"}` on a permission error.
- The ambient fallback remains for platform-resource operations: workspace file upload, job
  create/edit/delete, and warehouse-id resolution where the platform owns the object.

## Consequences

- These capabilities are unavailable when the OBO token is missing or lacks the relevant scope.
  The failure is explicit in the tool result, never a silent substitute identity.
- `_call`'s ambient fallback stays unchanged for existing tools; the new tools opt out by calling
  `self.client` directly.
- A future capability that reads governed data must make the same choice and cite this ADR.
- The security property is testable: with `user_token=""`, the tool returns the error and no
  `WorkspaceClient` call is made.
