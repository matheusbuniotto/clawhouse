# Data Estate Intelligence checks

Profile: light
Plan: `.specs/features/data-estate-intelligence/plan.md`

14 checks in 3 slices · 3 one-way doors · 0 open, of which 0 block

## Checks

### S1 - Permissions · 1 file · 39 KB · ~10k

**C1** - `uc_list_grants("main.sales.orders")` returns `full_name` `main.sales.orders` and a list of `{principal, privilege, inherited}` taken from `grants.get_effective(securable_type="table", full_name="main.sales.orders")` (AC 1)
Proof: `uv run pytest tests/test_estate_tools.py::test_uc_list_grants_returns_effective_assignments -q`

**C2** - A permission error from `grants.get_effective` returns `{"error": "not visible to you"}` and does not return an empty list (AC 2)
Proof: `uv run pytest tests/test_estate_tools.py::test_uc_list_grants_permission_error_is_not_an_empty_list -q`

**C3** - With `user_token` `""`, `uc_list_grants` returns `{"error": "not visible to you"}` and does not construct the ambient `WorkspaceClient` (AC 3)
Proof: `uv run pytest tests/test_estate_tools.py::test_uc_list_grants_empty_token_does_not_call_ambient_client -q`

**C4** - `full_name` values `sales.orders` and `main.sales.orders.extra` each return `{"error": "full_name must be catalog.schema.table"}` (AC 4)
Proof: `uv run pytest tests/test_estate_tools.py::test_uc_list_grants_rejects_non_three_part_names -q`

### S2 - Lineage · 1 file · 39 KB · ~10k

**C5** - `uc_table_lineage("main.sales.orders")` returns `upstream` and `downstream` arrays of `{table, last_seen}` from `system.access.table_lineage` (AC 5)
Proof: `uv run pytest tests/test_estate_tools.py::test_uc_table_lineage_splits_upstream_and_downstream -q`

**C6** - `uc_column_lineage("main.sales.orders", "amount")` returns `upstream` and `downstream` arrays of `{table, column, last_seen}` from `system.access.column_lineage` (AC 6)
Proof: `uv run pytest tests/test_estate_tools.py::test_uc_column_lineage_returns_column_pairs -q`

**C7** - Zero lineage rows return `{"table": "main.sales.orders", "upstream": [], "downstream": [], "note": "no lineage found"}` (AC 7)
Proof: `uv run pytest tests/test_estate_tools.py::test_empty_lineage_returns_note -q`

**C8** - Each of `upstream` and `downstream` contains at most 50 tables, ordered by `last_seen` descending (AC 8)
Proof: `uv run pytest tests/test_estate_tools.py::test_lineage_caps_each_direction_at_50 -q`

**C9** - With `user_token` `""`, `uc_table_lineage` and `uc_column_lineage` each return `{"error": "not visible to you"}` and issue no `execute_statement` call
Proof: `uv run pytest tests/test_estate_tools.py::test_lineage_empty_token_does_not_query -q`

### S3 - Run failure · 1 file · 39 KB · ~10k

**C10** - `job_run_failure(run_id)` returns `run_id`, `life_cycle_state`, `result_state`, `state_message`, `duration_ms`, and `run_page_url` (AC 9)
Proof: `uv run pytest tests/test_estate_tools.py::test_job_run_failure_returns_run_fields -q`

**C11** - When the run has failed tasks, the result includes each failed task's `task_key`, `result_state`, and `state_message` (AC 10)
Proof: `uv run pytest tests/test_estate_tools.py::test_job_run_failure_lists_failed_tasks -q`

**C12** - A run whose `life_cycle_state` is `RUNNING` returns that `life_cycle_state` and does not set `result_state` to `FAILED` (AC 11)
Proof: `uv run pytest tests/test_estate_tools.py::test_running_run_is_not_labeled_failed -q`

**C13** - With `user_token` `""`, `job_run_failure` returns `{"error": "not visible to you"}` and does not call `jobs.get_run`
Proof: `uv run pytest tests/test_estate_tools.py::test_job_run_failure_empty_token_does_not_get_run -q`

**C14** - The lineage statement queries `system.access.table_lineage` with `source_table_full_name` or `target_table_full_name` equal to the given `full_name`
Proof: `uv run pytest tests/test_estate_tools.py::test_table_lineage_sql_filters_source_or_target -q`

## Coverage

| Set (size) | Member -> proof | Unproven |
| --- | --- | --- |
| Landing doors (3) | fail closed, never `_call` C3 · lineage SQL on `system.access.table_lineage` C14 · `grants.get_effective` C1 | - |
| estate tools fail closed (4) | `uc_list_grants` C3 · `uc_table_lineage` C9 · `uc_column_lineage` C9 · `job_run_failure` C13 | - |
| grant fields (3) | `principal` C1 · `privilege` C1 · `inherited` C1 | - |
| `full_name` shapes (2) | two parts `sales.orders` C4 · four parts `main.sales.orders.extra` C4 | - |
| table lineage directions (2) | `upstream` C5 · `downstream` C5 | - |
| column lineage directions (2) | `upstream` C6 · `downstream` C6 | - |
| lineage cap (2) | `upstream` 50 C8 · `downstream` 50 C8 | - |
| run fields (6) | `run_id` C10 · `life_cycle_state` C10 · `result_state` C10 · `state_message` C10 · `duration_ms` C10 · `run_page_url` C10 | - |
| failed-task fields (3) | `task_key` C11 · `result_state` C11 · `state_message` C11 | - |
| run life cycle (2) | `RUNNING` not labeled `FAILED` C12 · terminal failure lists tasks C11 | - |

- Claims naming an error string or SQL source: C2, C3, C4, C9, C13, C14 — each proof asserts that value
- No other check claims more than the single case its proof exercises

## Swept

- validation: C4
- failure modes: C2, C12
- idempotency: n/a - every call is a live read; no write to retry
- authorization: C3, C9, C13
- concurrency: n/a - no stored estate snapshot to race
- data lifecycle: n/a - nothing is stored; answers are queried live
- dependency failure: C2
- state transitions: C12
- observability: n/a - no logging requirement in this plan

## Handoff

- S1–S3 = 10k, all in `capabilities/databricks.py`, under the 150k budget — one builder
- **Boundary:** C1–C14 closed in the estate commit
- **Settled mid-build:** lineage uses statement execution on the forwarded client, not `dbsql_query`, because `dbsql_query` goes through `_call`
- **Abandoned:** none
