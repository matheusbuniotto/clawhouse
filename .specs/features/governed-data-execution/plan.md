# Governed Data Execution

## Problem

Today a user can only get an answer over Unity Catalog data by writing SQL for `dbsql_query`, or by
creating a persistent Lakeflow Job with `jobs_create` and polling it
(`src/clawhouse/capabilities/databricks.py` L388–438, L439–899). Neither supports the ad-hoc loop a
data engineer actually runs: load a table, inspect rows, join, validate, iterate. The chat agent
cannot run pandas or Spark at all, so a request like "drop nulls and show me revenue by region"
dead-ends or is approximated in SQL. OpenClaw's answer is a local `exec` sandbox
(`docs/tools/exec.md`), which has no Unity Catalog access and no OBO identity. Evidence:
`docs/clawhouse-vs-openclaw.md` §3 row 1; `.specs/features/governed-data-execution/intent.md`.

When this ships, a user asks for a Python analysis over a governed table and gets the actual output
(rows, summary, a table) in the transcript, run as themselves on Databricks compute.

## Flow

This reuses the existing Databricks workspace client, the workspace-upload helper pattern, and the
run-polling/run-output methods instead of adding an execution service.

1. user turn -> `clawhouse.agent.turn` (exists) assembles the Databricks capability
   (`_capabilities_for_turn`, L564–599)
2. `clawhouse.capabilities.databricks.DatabricksTools` (exists) gains `run_python_analysis`; it
   uploads the submitted code to `/Workspace/Shared/clawhouse/executions/{execution_id}.py`
   (door 1)
3. the tool submits a one-off run with `client.jobs.submit(...)` and a `SparkPythonTask` (door 2)
   using the forwarded user client, then polls that same client (5s, same stop rule as
   `jobs_wait_run`) and reads terminal output with `jobs.get_run_output` on that client
4. out: the tool result `{run_id, life_cycle_state, result_state, duration_ms, logs, run_page_url}`
   -> existing `tool_result` SSE frame (`api/app.py` L1375) -> transcript renderer
   (`static/transcript.js`)

## Impact

| Front | What changes |
| --- | --- |
| domain | new term: Execution - one one-off Lakeflow run created for an ad-hoc Python analysis; lives in `capabilities/databricks.py` |
| domain | existing term: Jobs identity - still resolves SP/user for job CRUD; `run_python_analysis` opts out and requires the user token (ADR-0009); who branches today: every `_resolve_jobs_identity` caller |
| config | new optional `CLAWHOUSE_EXECUTION_TIMEOUT_SECONDS`, default `120` |
| stored data | nothing to migrate - the Databricks run is the record; the workspace `.py` file is the artifact |
| tests | new external-behavior tests beside `tests/test_jobs_tools.py` |

## Relations

`None - no stored-data shape change`

## Surface

`None - nothing consumed outside` (tool calls flow through the existing
`/api/sessions/{id}/turns` SSE route).

## Landing

| One-way door | Literal shape | Alternative rejected |
| --- | --- | --- |
| Execution artifact location | `/Workspace/Shared/clawhouse/executions/{execution_id}.py`, written with `workspace.mkdirs` + `workspace.upload(format=ImportFormat.AUTO, overwrite=True)` | per-user `/Users/{email}/...` - the Apps SP cannot write a user home without an extra OBO workspace scope, and the existing SQL-file path already uses the shared root (`databricks.py` L486–520) |
| One-off run primitive | `client.jobs.submit(run_name="clawhouse-exec-<id>", tasks=[SubmitTask(task_key="analysis", spark_python_task=SparkPythonTask(python_file=<path>, source=Source.WORKSPACE), new_cluster=<single-node spec>)], timeout_seconds=<n>)` | `jobs_create` then `run_now` then `jobs_delete` - pollutes the user's Jobs list, needs cleanup, and leaves a persistent object for an ad-hoc call |
| Execution identity | `run_python_analysis` uses only the forwarded user `WorkspaceClient`; when `user_token == ""` it returns `{"error": "user token required"}` and never calls `jobs_identity` | reuse `jobs_identity` / `CLAWHOUSE_JOBS_SP_*` fallback - would run arbitrary user code with platform SP privileges (ADR-0009) |

- Nothing else in this change is hard to reverse.

## Criteria

Grouped by slice - one observable outcome each, never a layer.

### S1: Ad-hoc Python analysis returns real output (P1)

A user can ask for a Python/Spark analysis over a UC table and see the run's output.

**Acceptance Criteria**

1. WHEN a turn calls `run_python_analysis` with a code string AND the request carries a forwarded user token THEN the system SHALL upload the code to `/Workspace/Shared/clawhouse/executions/{execution_id}.py` and submit one `spark_python_task` run.
2. WHEN the run is submitted THEN the system SHALL return `run_id`, `life_cycle_state`, and `run_page_url` in the tool result.
3. WHILE the run is not `TERMINATED` the system SHALL poll at intervals of at most 5 seconds and stop polling at `timeout_seconds`.
4. WHEN the run reaches `TERMINATED` with `result_state` `SUCCESS` THEN the system SHALL return the captured `logs` and `duration_ms` in the tool result.
5. IF the run reaches `TERMINATED` with `result_state` `FAILED` THEN the system SHALL return the task `error` and `run_page_url` and SHALL set `result_state` to `FAILED`.
6. IF `timeout_seconds` elapses before `TERMINATED` THEN the system SHALL return `status: "TIMED_OUT_WAITING"` with `run_id` and `run_page_url`, and SHALL NOT cancel the run.
7. IF the request carries no forwarded user token THEN the system SHALL return `{"error": "user token required"}` and SHALL NOT submit a run or use `CLAWHOUSE_JOBS_SP_*`.
8. The system SHALL require approval before every `run_python_analysis` call by including it in the default sensitive-tool set.

### S2: Execution is visible and attributable (P1)

The transcript shows the run state and output, and the run is attributable in Databricks.

9. WHEN the tool call starts THEN the system SHALL emit a `tool_call` SSE frame whose `name` is `run_python_analysis` and whose `arguments` include the `execution_id`.
10. WHEN the tool result is appended THEN the transcript SHALL render `result_state`, `duration_ms`, and `logs` using the existing tool-result renderer.
11. IF the run fails or times out THEN the transcript SHALL render the error text from AC 5 or AC 6 and a link to `run_page_url`.
12. WHEN a scheduled or headless turn calls `run_python_analysis` THEN the system SHALL submit the run only when a user token is available, otherwise return the AC 7 error and continue the turn.

**Independent test:** stub `WorkspaceClient.jobs.submit`, `jobs.get_run`, and `jobs.get_run_output`;
send a turn; assert the SSE frames and the rendered result for success, failure, timeout, and
no-token.

## Out of scope

Product capabilities only.

| Excluded | Why |
| --- | --- |
| Notebook execution and notebook output | v1 runs `.py` files only; notebook task shape is a different contract |
| Interactive cluster attach / long-lived session | each call is a one-off submitted run |
| Writing results into UC tables | requires a write-approval design beyond this slice |
| Installing arbitrary libraries | the run uses the cluster environment; package management is a separate door |
| Streaming / real-time output | the tool returns terminal output |

## Assumptions

| Assumption | Chosen default | Rationale | Confirmed? |
| --- | --- | --- | --- |
| Compute substrate | one-off `jobs.submit` with a small single-node `new_cluster` | reuses the Jobs SDK already imported; avoids a new service. Serverless is a follow-up if cluster start time is unacceptable | n |
| Code transport | `.py` file in the workspace, `Source.WORKSPACE` | `SparkPythonTask` requires a workspace/file source; matches `_save_workspace_sql_file` | n |
| Timeout | `120` s default, env override | matches `jobs_wait_run` default (`databricks.py` L859) | n |
| Output size | return at most the last 20,000 characters of `logs` | keeps the transcript bounded; full logs stay in Databricks | n |

**Open questions:** none - all resolved or logged above.

## Observable

Worksheet, not the review. `n/a` needs its reason.

| Surface | Decision | Landing |
| --- | --- | --- |
| tool `run_python_analysis` | output shape | AC 2, 4 |
| tool `run_python_analysis` | error shape and codes | AC 5, 6, 7 |
| tool `run_python_analysis` | authorization and identity | AC 7, 8 |
| tool `run_python_analysis` | rate limits | n/a - Databricks Jobs API enforces workspace limits; no app-level throttle |
| tool `run_python_analysis` | idempotency and duplicates | n/a - each call intentionally creates a new run; `execution_id` is unique per call |
| screen `chat` | loading state | existing - `tool_call` frame and run-state card |
| screen `chat` | error state | AC 11 |
| screen `chat` | empty state | n/a - a run always produces a result or an error |
| screen `chat` | destructive action confirms | AC 8 - approval prompt before execution |

## Sources

- `.specs/features/governed-data-execution/intent.md` - problem, who, done
- `docs/clawhouse-vs-openclaw.md` §3 row 1 - ranking and OpenClaw `exec` contrast
- `src/clawhouse/capabilities/databricks.py` - existing Jobs, `_save_workspace_sql_file`, `jobs_wait_run`
- `docs/adr/0009-user-code-execution-identity.md` - fail-closed identity constraint
