# User Sandbox checks

Profile: light
Plan: `.specs/features/user-sandbox/plan.md`

24 checks in 3 slices · 4 one-way doors · 0 open

## Checks

### S1 - Native Serverless Python Execution (`python_exec`) · 4 files · 30 KB · ~8k

**C1** - `python_exec` is registered in `DEFAULT_APPROVAL_REQUIRED_TOOLS` (AC 1)
Proof: `uv run pytest tests/test_user_sandbox.py -k test_python_exec_in_default_approval_tools`

**C2** - `python_exec` without a forwarded user token (`user_token == ""`) returns `{"error": "user token required"}` and makes no network or SDK call (AC 2)
Proof: `uv run pytest tests/test_user_sandbox.py -k test_python_exec_fails_closed_without_token`

**C3** - `python_exec` sends JSON-RPC `tools/call` for `system__ai__python_exec` to `/api/2.0/mcp/functions/system/ai/python_exec` via user client and returns output string (AC 3, door 1)
Proof: `uv run pytest tests/test_user_sandbox.py -k test_python_exec_calls_mcp_function_and_returns_output`

**C4** - `python_exec` with `script_path` reads the script from the caller's workspace sandbox before executing via MCP (AC 4)
Proof: `uv run pytest tests/test_user_sandbox.py -k test_python_exec_with_script_path`

**C5** - `python_exec` scrubs occurrences of `user_token` from output with `"[REDACTED]"` (AC 5, door 2)
Proof: `uv run pytest tests/test_user_sandbox.py -k test_python_exec_scrubs_token`

**C6** - `python_exec` returns `{"error": f"python_exec failed: {detail}"}` when Databricks MCP endpoint errors or returns non-2xx (AC 6)
Proof: `uv run pytest tests/test_user_sandbox.py -k test_python_exec_handles_mcp_error`

**C7** - `python_exec` truncates outputs exceeding 20000 characters to the last 20000 characters and sets `is_truncated: true` (AC 7)
Proof: `uv run pytest tests/test_user_sandbox.py -k test_python_exec_truncates_large_output`

### S2 - Persistent Per-User Workspace Sandbox Files · 4 files · 35 KB · ~9k

**C8** - A turn calling `sandbox_write_file` pauses for inline approval before writing any workspace file (AC 8, door 2)
Proof: `uv run pytest tests/test_user_sandbox.py -k test_sandbox_write_file_pauses_for_approval`

**C9** - Approved `sandbox_write_file` uploads content to `/Workspace/Shared/clawhouse/sandboxes/{user_slug}/{path}` with `format=AUTO` and returns path and byte count (AC 9, door 3)
Proof: `uv run pytest tests/test_user_sandbox.py -k test_sandbox_write_file_uploads_to_slug_path`

**C10** - `sandbox_read_file` and `sandbox_list_files` execute immediately without pausing for approval (AC 10)
Proof: `uv run pytest tests/test_user_sandbox.py -k test_sandbox_read_and_list_do_not_pause`

**C11** - `sandbox_read_file` downloads and returns file content up to 50000 characters (AC 11)
Proof: `uv run pytest tests/test_user_sandbox.py -k test_sandbox_read_file_returns_content`

**C12** - `sandbox_read_file` for a non-existent file returns `{"error": "file not found", "path": <path>}` (AC 12)
Proof: `uv run pytest tests/test_user_sandbox.py -k test_sandbox_read_file_missing_returns_error`

**C13** - `sandbox_list_files` returns relative POSIX paths sorted lexicographically (AC 13)
Proof: `uv run pytest tests/test_user_sandbox.py -k test_sandbox_list_files_returns_sorted_paths`

**C14** - Any sandbox file tool path starting with `/` or containing `..` returns `{"error": "path traversal denied"}` (AC 14, door 3)
Proof: `uv run pytest tests/test_user_sandbox.py -k test_sandbox_file_tools_deny_path_traversal`

**C15** - User A and User B have separate `user_slug` folders so User B cannot see or read User A's files (AC 15, door 3)
Proof: `uv run pytest tests/test_user_sandbox.py -k test_sandbox_files_user_isolation`

### S3 - Sandbox Status & Reset (`/status` & `/api/sandbox`) · 5 files · 40 KB · ~10k

**C16** - `GET /api/sandbox` returns HTTP 200 with `{owner_id, workspace_path, backend, status, file_count}` (AC 16, door 4)
Proof: `uv run pytest tests/test_user_sandbox.py -k test_api_get_sandbox_status`

**C17** - Unauthenticated `GET /api/sandbox` and `POST /api/sandbox/reset` return HTTP 401 (AC 17)
Proof: `uv run pytest tests/test_user_sandbox.py -k test_api_sandbox_requires_auth`

**C18** - `POST /api/sandbox/reset` recursively deletes the user sandbox folder and returns `file_count: 0` (AC 18, door 4)
Proof: `uv run pytest tests/test_user_sandbox.py -k test_api_post_sandbox_reset`

**C19** - `POST /api/sandbox/reset` returns HTTP 502 when workspace deletion fails (AC 18 error)
Proof: `uv run pytest tests/test_user_sandbox.py -k test_api_post_sandbox_reset_failure_502`

**C20** - `create_app` mounts `/api/sandbox` GET and POST routes (startup assembly)
Proof: `uv run pytest tests/test_user_sandbox.py -k test_create_app_mounts_sandbox_routes`

**C21** - `frontend/status.ts` renders User Sandbox section and `#btn-reset-sandbox` (AC 19)
Proof: `uv run pytest tests/test_user_sandbox.py -k test_status_js_contains_user_sandbox_and_reset_button`

**C22** - Clicking `#btn-reset-sandbox` calls `POST /api/sandbox/reset` and updates displayed count (AC 20)
Proof: `uv run pytest tests/test_user_sandbox.py -k test_status_js_wires_reset_sandbox_click`

**C23** - `DatabricksTools.all_tools()` includes `python_exec`, `sandbox_write_file`, `sandbox_read_file`, and `sandbox_list_files`
Proof: `uv run pytest tests/test_user_sandbox.py -k test_databricks_tools_includes_sandbox_tools`

**C24** - Headless turn with `python_exec` denies when token is empty without persisting approval (AC 2 headless)
Proof: `uv run pytest tests/test_user_sandbox.py -k test_headless_turn_python_exec_empty_token`

## Coverage

| Set (size) | Member -> proof | Unproven |
| --- | --- | --- |
| `GET /api/sandbox` statuses (2) | 200 C16 · 401 C17 | - |
| `POST /api/sandbox/reset` statuses (3) | 200 C18 · 401 C17 · 502 C19 | - |
| `python_exec` token states (2) | empty C2 · present C3 | - |
| `python_exec` source kinds (2) | inline code C3 · script path C4 | - |
| path traversal patterns (2) | leading slash C14 · parent traversal dotdot C14 | - |
| file tool operations (3) | write C9 · read C11 · list C13 | - |
| Landing doors (4) | door 1 C3 · door 2 C1, C5, C8 · door 3 C9, C14, C15 · door 4 C16, C18 | - |
| startup config: sandbox routes (1) | `create_app` C20 | - |

## Swept

- validation: C14
- failure modes: C2, C6, C12, C19
- idempotency: C9, C18
- authorization: C2, C17
- concurrency: C15
- data lifecycle: C18
- dependency failure: C6, C19
- state transitions: C18
- observability: C16, C20
- test policy: n/a - light profile

## Handoff

`wc -c` on files divided by 4:
- S1: ~8k tokens
- S2: ~9k tokens
- S3: ~10k tokens
Total: ~27k tokens (fits within 150k budget; mechanism: one builder).
