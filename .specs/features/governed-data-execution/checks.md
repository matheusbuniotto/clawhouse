# Governed Data Execution checks

Profile: light
Plan: `.specs/features/governed-data-execution/plan.md`

13 checks in 2 slices · 3 one-way doors · 0 open, of which 0 block

## Checks

### S1 - Ad-hoc Python analysis · 2 files · 46 KB · ~12k

**C1** - A forwarded user token causes `run_python_analysis` to upload the code to `/Workspace/Shared/clawhouse/executions/{execution_id}.py` via `workspace.mkdirs` and `workspace.upload` and to call `jobs.submit` once with `spark_python_task` `source` `WORKSPACE` (AC 1)
Proof: `uv run pytest tests/test_run_python_analysis.py::test_uploads_shared_py_and_submits_spark_python_task -q`

**C2** - The tool result of a submitted run contains `run_id`, `life_cycle_state`, and `run_page_url` (AC 2)
Proof: `uv run pytest tests/test_run_python_analysis.py::test_submitted_run_returns_run_id_state_and_page_url -q`

**C3** - While the run is not `TERMINATED`, `jobs.get_run` is polled at an interval of at most 5 seconds and polling stops when `timeout_seconds` elapses (AC 3)
Proof: `uv run pytest tests/test_run_python_analysis.py::test_polls_at_most_every_5_seconds_until_timeout -q`

**C4** - A run that reaches `TERMINATED` with `result_state` `SUCCESS` returns `logs` and `duration_ms`, and `logs` is at most the last 20000 characters (AC 4)
Proof: `uv run pytest tests/test_run_python_analysis.py::test_success_returns_logs_capped_at_20000_and_duration_ms -q`

**C5** - A run that reaches `TERMINATED` with `result_state` `FAILED` returns `result_state` `FAILED`, the task `error`, and `run_page_url` (AC 5)
Proof: `uv run pytest tests/test_run_python_analysis.py::test_failed_run_returns_error_and_page_url -q`

**C6** - When `timeout_seconds` elapses before `TERMINATED`, the result is `status` `TIMED_OUT_WAITING` with `run_id` and `run_page_url`, and no cancel call is issued (AC 6)
Proof: `uv run pytest tests/test_run_python_analysis.py::test_timeout_returns_timed_out_waiting_without_cancel -q`

**C7** - An empty forwarded user token returns `{"error": "user token required"}`, does not call `jobs.submit`, and does not read `CLAWHOUSE_JOBS_SP_CLIENT_ID` or `CLAWHOUSE_JOBS_SP_CLIENT_SECRET` (AC 7)
Proof: `uv run pytest tests/test_run_python_analysis.py::test_missing_user_token_does_not_submit_or_use_jobs_sp -q`

**C8** - With `CLAWHOUSE_SENSITIVE_TOOLS` unset, the default sensitive-tool set includes `run_python_analysis` (AC 8)
Proof: `uv run pytest tests/test_run_python_analysis.py::test_default_sensitive_set_includes_run_python_analysis -q`

**C9** - When `CLAWHOUSE_EXECUTION_TIMEOUT_SECONDS` is unset, `timeout_seconds` passed to `jobs.submit` is `120`; when it is `45`, `timeout_seconds` is `45`
Proof: `uv run pytest tests/test_run_python_analysis.py::test_timeout_seconds_defaults_to_120_and_honors_env -q`

### S2 - Visible and attributable · 3 files · 110 KB · ~28k

**C10** - The turn emits a `tool_call` SSE frame whose `name` is `run_python_analysis` and whose `arguments` include `execution_id` (AC 9)
Proof: `uv run pytest tests/test_run_python_analysis.py::test_tool_call_frame_names_run_python_analysis_and_execution_id -q`

**C11** - The transcript renderer shows `result_state`, `duration_ms`, and `logs` from the `tool_result` frame (AC 10)
Proof: `npx vitest run frontend/transcript.test.ts -t "run_python_analysis renders result_state duration_ms and logs"`

**C12** - A `FAILED` or `TIMED_OUT_WAITING` tool result renders the error text and an anchor whose `href` is `run_page_url` (AC 11)
Proof: `npx vitest run frontend/transcript.test.ts -t "run_python_analysis failure renders error and run_page_url"`

**C13** - A headless turn that calls `run_python_analysis` with no user token returns `{"error": "user token required"}` and the turn still completes (AC 12)
Proof: `uv run pytest tests/test_run_python_analysis.py::test_headless_turn_without_token_returns_user_token_required_and_continues -q`

## Coverage

| Set (size) | Member -> proof | Unproven |
| --- | --- | --- |
| Landing doors (3) | artifact path `/Workspace/Shared/clawhouse/executions/{execution_id}.py` C1 · `jobs.submit` + `SparkPythonTask` C1 · user-token-only identity C7 | - |
| submitted tool fields (3) | `run_id` C2 · `life_cycle_state` C2 · `run_page_url` C2 | - |
| terminal `result_state` (2) | `SUCCESS` C4 · `FAILED` C5 | - |
| wait outcomes (2) | poll stops at `timeout_seconds` C3 · `TIMED_OUT_WAITING` C6 | - |
| identity branches (2) | token present submits C1 · token `""` returns `user token required` C7 | - |
| default sensitive set (1) | `run_python_analysis` C8 | - |
| timeout config (2) | unset `120` C9 · `CLAWHOUSE_EXECUTION_TIMEOUT_SECONDS=45` C9 | - |
| SSE / transcript frames (2) | `tool_call` C10 · `tool_result` C11 | - |
| failure render (2) | error text C12 · `run_page_url` href C12 | - |
| headless token (1) | no token returns `user token required` and the turn completes C13 | - |

- Claims naming a status or frame: C5, C6, C10, C12, C13 — each proof crosses that boundary
- No other check claims more than the single case its proof exercises

## Swept

- validation: C9
- failure modes: C5, C6
- idempotency: n/a - each call creates a new run; `execution_id` is unique per call
- authorization: C7, C8
- concurrency: n/a - one submitted run per call; no shared mutable app state
- data lifecycle: n/a - the Databricks run is the record; nothing is migrated
- dependency failure: C5
- state transitions: C3, C4, C5, C6
- observability: C10, C11

## Handoff

- S1 = 12k, all in `capabilities/databricks.py` and `settings.py`; S2 adds `agent/turn.py`, `api/app.py`, and `static/transcript.js` at 40k total, under the 150k budget — one builder
- **Boundary:** C1–C13 closed in the execution commit
- **Settled mid-build:** polling uses the forwarded client directly so a wait cannot fall back to the ambient client
- **Abandoned:** none
