# Databricks-Native User Sandbox (`user-sandbox`)

## Problem

Today, running user-authored Python in Clawhouse relies on `run_python_analysis` (`src/clawhouse/capabilities/databricks/python_analysis.py`), which cold-starts or attaches a single-node cluster via `jobs.submit` and takes minutes to return simple calculations. Furthermore, chat sessions have no persistent user workspace for storing multi-turn scripts, notes, or data transformations across turns. OpenClaw provides `exec` and workspace file tools (`read`, `write`, `edit`) within a sandbox (`docs/clawhouse-vs-openclaw.md` §2 rows 15–16), which Clawhouse currently lacks.

When this ships, users get a 100% Databricks-native sandbox without third-party VM or container infrastructure. Ad-hoc Python runs in seconds via Databricks's native `system.ai.python_exec` MCP service (`/api/2.0/mcp/functions/system/ai/python_exec`) under the caller's forwarded OBO identity (ADR-0009, ADR-0010), while persistent user files are stored in the Databricks Workspace (`/Workspace/Shared/clawhouse/sandboxes/{user_slug}/`) across sessions with inspection and reset actions on `/status`.

## Flow

This reuses `DatabricksTools` (`src/clawhouse/capabilities/databricks/tools.py`), the inline approval guardrail (`clawhouse.agent.pauses`), token scrubbing (`clawhouse.capabilities.mcp.scrub_token`), Databricks Workspace file operations (`workspace.mkdirs`, `workspace.upload`, `workspace.download`, `workspace.list`, `workspace.delete`), and the `/status` screen (`frontend/status.ts`).

1. User turn -> `clawhouse.agent.runner` (exists) passes the updated `DatabricksTools` (exists) containing `python_exec`, `sandbox_write_file`, `sandbox_read_file`, and `sandbox_list_files`.
2. Read-only calls (`sandbox_read_file`, `sandbox_list_files`) execute immediately; mutating calls (`python_exec`, `sandbox_write_file`) pause through `clawhouse.agent.pauses` (exists) for inline approval (door 2).
3. On execution, `python_exec` calls `POST /api/2.0/mcp/functions/system/ai/python_exec` via `self.client` using only the forwarded user token (door 1), failing closed if `user_token` is missing (ADR-0009). If `script_path` is passed, it loads the script from the user's workspace sandbox before execution.
4. File tools manage files under `/Workspace/Shared/clawhouse/sandboxes/{user_slug}/` via `DatabricksTools._call` with path-traversal prevention (door 3).
5. Out: tool result returns to the transcript stream (`clawhouse.api.sse`, exists); on `/status`, `frontend/status.ts` (exists) calls `GET /api/sandbox` and `POST /api/sandbox/reset` (door 4) to monitor and reset the workspace.

## Impact

| Front | What changes |
| --- | --- |
| domain | new term: `python_exec` - tool on `DatabricksTools` executing stateless Python via Databricks Unity Catalog MCP endpoint `/api/2.0/mcp/functions/system/ai/python_exec` |
| domain | new term: `WorkspaceSandbox` - per-user persistent workspace directory under `/Workspace/Shared/clawhouse/sandboxes/{user_slug}/` |
| domain | existing term: `DEFAULT_APPROVAL_REQUIRED_TOOLS` in `clawhouse.agent.pauses` gains `python_exec` and `sandbox_write_file`; who branches today: `_sensitive_decision` in `pauses.py` |
| stored data | files stored in Databricks Workspace under `/Workspace/Shared/clawhouse/sandboxes/{user_slug}/`; no Lakebase table migration required |

## Relations

`None - no stored-data shape change`

## Surface

Only routes this adds or whose signature changes.

| Route | In | Out | Status |
| --- | --- | --- | --- |
| `GET /api/sandbox` | none | `owner_id` · `workspace_path` · `backend` · `status` · `file_count` | `200`, `401` |
| `POST /api/sandbox/reset` | none | `owner_id` · `workspace_path` · `backend` · `status` · `file_count` | `200`, `401`, `502` |

## Landing

| One-way door | Literal shape | Alternative rejected |
| --- | --- | --- |
| Serverless Python execution endpoint (door 1) | `POST /api/2.0/mcp/functions/system/ai/python_exec` with JSON-RPC `method: "tools/call"`, `params: {"name": "system__ai__python_exec", "arguments": {"code": <code>}}` via `tools.client` | `/ai-gateway/mcp-services/system.ai.python_exec` (returns 403 / -32007 unauthorized) or spawning single-node Spark clusters (minutes of latency) |
| Execution identity & approval gate (door 2) | `python_exec` requires non-empty `user_token` (fails closed with `{"error": "user token required"}`), scrubs `user_token` from output, and registers `python_exec` and `sandbox_write_file` in `DEFAULT_APPROVAL_REQUIRED_TOOLS` | Running under ambient App Service Principal credentials or without inline approval (violates ADR-0005 and ADR-0009) |
| Workspace isolation & path safety (door 3) | Path root `/Workspace/Shared/clawhouse/sandboxes/{user_slug}/` with `user_slug = re.sub(r"[^a-zA-Z0-9_]", "_", owner_id) + "_" + hashlib.sha256(owner_id.encode()).hexdigest()[:8]`; reject any path starting with `/` or containing `..` | User home directory `/Users/{email}/...` (fails when App SP lacks user home write scope) or shared unpartitioned directory (leaks files across users) |
| UI status and reset contract (door 4) | `GET /api/sandbox` and `POST /api/sandbox/reset` in `status.py`, rendered in `frontend/status.ts` | CLI-only or chat-prompt-only reset (inconvenient when transcript is stuck or user wants a clean start) |

- Nothing else in this change is hard to reverse.

## Criteria

Grouped by slice - one observable outcome each, never a layer. Numbering runs across the whole plan.

### S1: Native Serverless Python Execution (`python_exec`) (P1)

Fast, isolated Python execution using Databricks's native `system.ai.python_exec` MCP service.

**Acceptance Criteria**

1. The system SHALL include `python_exec` and `sandbox_write_file` in `DEFAULT_APPROVAL_REQUIRED_TOOLS`.
2. WHEN `python_exec` is called and the turn carries no forwarded `user_token` (`user_token == ""`) THEN the system SHALL return `{"error": "user token required"}` and SHALL NOT invoke the Databricks API or use ambient service principal credentials.
3. WHEN `python_exec` is approved with code and `user_token` is present THEN the system SHALL send a JSON-RPC `tools/call` for `system__ai__python_exec` to `/api/2.0/mcp/functions/system/ai/python_exec` using the caller's client and SHALL return `{"output": <str>, "is_truncated": <bool>}`.
4. WHERE `python_exec` is called with `script_path` THEN the system SHALL read the script content from the caller's workspace sandbox before sending it to `system__ai__python_exec`.
5. IF `python_exec` produces output containing the caller's `user_token` THEN the system SHALL scrub every occurrence of `user_token` with `"[REDACTED]"` before returning the result.
6. IF the Databricks MCP endpoint returns an error or HTTP non-2xx THEN `python_exec` SHALL return `{"error": f"python_exec failed: {detail}"}`.
7. WHEN `python_exec` returns output longer than `20000` characters THEN the system SHALL truncate `output` to the last `20000` characters and set `is_truncated: true`.

**Independent test:** Call `python_exec` without a token and assert error; call `python_exec("print(40 + 2)")` with a mock client returning `{ "structuredContent": { "rows": [["42\n"]] } }` and assert `output == "42\n"`.

### S2: Persistent Per-User Workspace Sandbox Files (P1)

Read, write, and list persistent files in the user's Databricks Workspace sandbox folder.

**Acceptance Criteria**

8. WHEN a turn calls `sandbox_write_file` THEN the system SHALL pause for inline approval before writing any workspace file.
9. WHEN `sandbox_write_file` is approved with relative path `path` and `content` THEN the system SHALL upload the file to `/Workspace/Shared/clawhouse/sandboxes/{user_slug}/{path}` with `format=ImportFormat.AUTO` and `overwrite=True`, ensuring parent directories exist via `workspace.mkdirs`, and return `{"path": <path>, "bytes_written": <int>}`.
10. WHEN `sandbox_read_file` or `sandbox_list_files` is called THEN the system SHALL execute the tool without pausing for approval.
11. WHEN `sandbox_read_file` is called for an existing file in the caller's sandbox THEN the system SHALL download and return `{"path": <path>, "content": <text>}` truncated to at most `50000` characters.
12. IF `sandbox_read_file` is called for a non-existent file THEN the system SHALL return `{"error": "file not found", "path": <path>}`.
13. WHEN `sandbox_list_files` is called THEN the system SHALL list all items under `/Workspace/Shared/clawhouse/sandboxes/{user_slug}/` recursively and return `{"files": [...]}` sorted lexicographically by relative path.
14. IF `sandbox_write_file`, `sandbox_read_file`, or `sandbox_list_files` receives a path starting with `/` or containing `..` THEN the system SHALL return `{"error": "path traversal denied"}` and SHALL NOT access files outside the user's sandbox directory.
15. WHEN User A writes a file and User B lists files THEN User B SHALL NOT see User A's files.

**Independent test:** Write a file `calc.py` as user A, read it back, list files, test path traversal `../foo`, and verify user B sees an empty listing.

### S3: Sandbox Status & Reset (`/status` & `/api/sandbox`) (P1)

Diagnostics and workspace reset available in the web UI.

**Acceptance Criteria**

16. WHEN an authenticated caller requests `GET /api/sandbox` THEN the backend SHALL return HTTP 200 with `{owner_id, workspace_path, backend: "databricks_python_exec", status: "ready", file_count: <int>}`.
17. IF an unauthenticated caller requests `GET /api/sandbox` or `POST /api/sandbox/reset` THEN the backend SHALL return HTTP 401.
18. WHEN an authenticated caller requests `POST /api/sandbox/reset` THEN the backend SHALL recursively delete the caller's directory `/Workspace/Shared/clawhouse/sandboxes/{user_slug}/`, recreate the empty directory, and return HTTP 200 with `file_count: 0`.
19. WHEN `frontend/status.ts` mounts into `#screen` THEN it SHALL render a `"User Sandbox"` section displaying `#stat-sandbox-status`, `#stat-sandbox-backend`, `#stat-sandbox-path`, `#stat-sandbox-files`, and a button `#btn-reset-sandbox` (`"Reset sandbox"`).
20. WHEN the user clicks `#btn-reset-sandbox` on `/status` THEN `frontend/status.ts` SHALL send `POST /api/sandbox/reset`, update `#stat-sandbox-files` to `"0 files"`, and re-enable `#btn-reset-sandbox`.

**Independent test:** Call `GET /api/sandbox` on an existing folder, verify file count; trigger `POST /api/sandbox/reset` and verify directory deletion and `file_count: 0`.

## Out of scope

Product capabilities only. Process and harness rules live in AGENTS.md or as Observable `n/a`.

| Excluded | Why |
| --- | --- |
| Outbound internet access from `system.ai.python_exec` | Databricks's native `system.ai.python_exec` sandbox is purposefully network-isolated for security |
| Interactive bash/terminal PTY shell | `system.ai.python_exec` is a Python execution engine; interactive shell requires external VMs |
| Arbitrary third-party `pip install` inside `system.ai.python_exec` | The runtime environment is managed by Databricks with standard scientific packages pre-installed |

## Assumptions

Defaults that are not already a numbered criterion. Drop a row once it is.

| Assumption | Chosen default | Rationale | Confirmed? |
| --- | --- | --- | --- |
| Sandbox backend substrate | Databricks-native `system.ai.python_exec` + Workspace files | Confirmed by user; avoids external VM infrastructure | y |
| Shared workspace sandbox folder | `/Workspace/Shared/clawhouse/sandboxes/{user_slug}/` | Consistent with `/Workspace/Shared/clawhouse/executions/` and avoids user-home ACL issues | y |

**Open questions:** none - all resolved or logged above.

## Observable

Worksheet, not the review. `n/a` needs its reason. One row may group the same decision across several routes.

| Surface | Decision | Landing |
| --- | --- | --- |
| tool `python_exec` | output shape, truncation, and error handling | AC 3, AC 6, AC 7 |
| tool `python_exec` | identity, approval, and secret scrubbing | AC 1, AC 2, AC 5 |
| tools `sandbox_write_file`, `sandbox_read_file`, `sandbox_list_files` | output shape, bounds, path traversal, user isolation | AC 8, AC 9, AC 10, AC 11, AC 12, AC 13, AC 14, AC 15 |
| API `GET /api/sandbox` | response shape and auth | AC 16, AC 17 |
| API `POST /api/sandbox/reset` | response shape, error codes, auth | AC 17, AC 18 |
| all new `/api/sandbox*` routes | versioning, rate limits | n/a - internal application endpoints behind Databricks App proxy |
| screen `status` (`User Sandbox` card) | loading, populated, error, and reset states | AC 19, AC 20 |
| screen `status` (`User Sandbox` card) | empty state | AC 16, AC 19 (new user sandbox displays `0 files`) |
| screen `status` (`User Sandbox` card) | destructive action confirms | AC 20 (explicit `"Reset sandbox"` button in status screen) |

## Sources

- User direction, 2026-10-19 - Use Databricks native `python_exec` and Workspace storage
- Workspace probe, 2026-10-19 on `dbc-562d9321-2592` - `/api/2.0/mcp/functions/system/ai/python_exec` confirmed working with `system__ai__python_exec`
- `docs/adr/0010-user-sandbox-vm.md` - ADR for Databricks-native sandbox execution
- `docs/adr/0009-user-code-execution-identity.md` - Fail-closed user identity for user-code execution
