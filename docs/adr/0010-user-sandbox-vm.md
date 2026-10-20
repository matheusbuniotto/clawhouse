# ADR-0010: Databricks-native user sandbox via `system.ai.python_exec` and Workspace files

Date: 2026-10-19
Status: accepted
Related: [ADR-0002 Lakebase + workspace storage](0002-lakebase-workspace-storage.md),
[ADR-0003 Pydantic AI runtime](0003-pydantic-ai.md),
[ADR-0005 platform-controlled agent](0005-platform-controlled-agent.md),
[ADR-0009 user-code execution identity](0009-user-code-execution-identity.md)

## Context

`run_python_analysis` (ADR-0009) submits a one-off Lakeflow `SparkPythonTask` (`jobs.submit` with a
single-node cluster) when a user needs distributed Spark over Unity Catalog tables. However, for
fast ad-hoc Python computation, data transformation, and persistent scratch files across chat
sessions, spinning up a Job cluster is too slow and requires no external VM infrastructure when
Databricks already provides two native primitives:

1. **`system.ai.python_exec` via Databricks Managed MCP (`/api/2.0/mcp/functions/system/ai/python_exec`):**
   Confirmed by live probe on workspace `dbc-562d9321-2592` (2026-10-19):
   - `POST /api/2.0/mcp/functions/system/ai/python_exec` with JSON-RPC `tools/call`
     (`name: "system__ai__python_exec"`, `arguments: {"code": "<python>"}`) executes Python in a
     Databricks-managed stateless, isolated sandbox container and returns
     `{"content": [{"type": "text", "text": "{\"is_truncated\":false,\"columns\":[\"output\"],\"rows\":[[\"<stdout>\"]]}"}], "isError": false}`.
   - By contrast, `/ai-gateway/mcp-services/system.ai.python_exec` returns HTTP 403 (`-32007`); the
     Unity Catalog function MCP path `/api/2.0/mcp/functions/system/ai/python_exec` is the working
     endpoint.
2. **Databricks Workspace Files (`/Workspace/Shared/clawhouse/sandboxes/{user_slug}/`):**
   Provides persistent per-user file storage across chat sessions using the existing
   `workspace.mkdirs`, `workspace.upload(format=ImportFormat.AUTO)`, `workspace.download`,
   `workspace.list`, and `workspace.delete(recursive=True)` SDK primitives, with ambient client
   fallback for workspace storage operations (`AGENTS.md`).

## Decision

Build the user sandbox 100% natively on Databricks without any external VM or container daemon:

1. **Instant Python execution (`python_exec` tool on `DatabricksTools`):**
   - Calls `POST /api/2.0/mcp/functions/system/ai/python_exec` (`method: "tools/call"`,
     `name: "system__ai__python_exec"`) using ONLY the caller's forwarded `WorkspaceClient`
     (`self.client`), never the ambient Service Principal (`ADR-0009`).
   - Fails closed with `{"error": "user token required"}` when `user_token` is empty.
   - Supports executing inline `code` or a saved workspace sandbox file via optional `script_path`
     (which loads the script from the caller's workspace sandbox folder and passes it to
     `system__ai__python_exec`).
   - Included in `DEFAULT_APPROVAL_REQUIRED_TOOLS` so every execution pauses for inline approval.
2. **Persistent per-user Workspace files (`sandbox_write_file`, `sandbox_read_file`, `sandbox_list_files`):**
   - Scoped to `/Workspace/Shared/clawhouse/sandboxes/{user_slug}` where `user_slug` is derived
     deterministically from `owner_id` (`<safe_prefix>_<sha256[:8]>`), preventing cross-user access
     and rejecting any relative path containing `..` or leading `/`.
   - Uses `DatabricksTools._call` (user client with ambient SP fallback) because workspace file
     storage under `/Workspace/Shared/clawhouse/` is a platform-managed storage resource
     (`AGENTS.md`, `ADR-0009`).
   - `sandbox_write_file` is in `DEFAULT_APPROVAL_REQUIRED_TOOLS`; `sandbox_read_file` and
     `sandbox_list_files` are read-only and run without pausing.
3. **Sandbox inspection & reset (`GET /api/sandbox` and `POST /api/sandbox/reset`):**
   - Lists or recursively deletes (`workspace.delete(..., recursive=True)`) the caller's
     `/Workspace/Shared/clawhouse/sandboxes/{user_slug}` folder and surfaces a **User Sandbox** card
     with a **Reset sandbox** button on `/status`.

## Consequences

- Zero external infrastructure, daemons, or third-party API keys (`CLAWHOUSE_SANDBOX_URL` not needed).
- Fast Python execution runs in Databricks's native `system.ai.python_exec` sandbox under the
  caller's OBO token (`ADR-0009`), while heavy Spark/UC jobs continue to use `run_python_analysis`.
- Persistent user files live natively in the Databricks Workspace alongside existing Clawhouse
  artifacts (`/Workspace/Shared/clawhouse/`).
