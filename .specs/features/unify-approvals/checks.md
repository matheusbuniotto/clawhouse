# unify-approvals checks

Profile: light
Plan: `.specs/features/unify-approvals/plan.md`

## Intent

<5 checks in 1 slice · 0 one-way doors · 0 open, of which 0 block>

## Checks

Grouped by the spec's slices; numbering runs across the whole feature.

### S1 - Unified ToolGuardrail Approval Mechanism · 3 files · 5 KB · ~5k

**C1** - Mutating Lakeflow tools and Google Sheets write tools are defined in `DEFAULT_APPROVAL_REQUIRED_TOOLS` in `clawhouse.agent.turn` (AC 1)
Proof: `uv run pytest tests/test_approvals.py -k "test_default_approval_required_tools_contents"`

**C2** - Neither `DatabricksCapability` nor `GoogleSheetsCapability` implements `get_wrapper_toolset` (AC 2)
Proof: `uv run pytest tests/test_approvals.py -k "test_capabilities_do_not_have_wrapper_toolset"`

**C3** - `_sensitive_tool_guard` returns `GuardrailResult.approve()` for each default sensitive tool and configured dynamic sensitive tool (AC 3)
Proof: `uv run pytest tests/test_approvals.py -k "test_sensitive_tool_guard_returns_approve_for_all_sensitive_tools"`

**C4** - `_sensitive_tool_guard` inspects `dbsql_query` and returns `GuardrailResult.approve()` for non-readonly SQL and `GuardrailResult.allow()` for readonly SQL (AC 4, AC 5)
Proof: `uv run pytest tests/test_approvals.py -k "test_sensitive_tool_guard_dbsql_query_sql_safety"`

**C5** - Parameterized execution of each sensitive tool during a chat turn pauses execution with status pending_approval and generates deferred tool requests (AC 6)
Proof: `uv run pytest tests/test_approvals.py -k "test_each_sensitive_tool_pauses_turn_and_generates_pending_approval"`

## Coverage

| Set (size) | Member -> proof | Unproven |
| --- | --- | --- |
| default approval tools (8) | `jobs_run_now` C1 · `jobs_cancel_run` C1 · `jobs_create` C1 · `jobs_edit` C1 · `jobs_delete` C1 · `delivery_send_webhook` C1 · `create_google_sheet` C1 · `update_google_sheet` C1 | - |
| capability wrapper methods (2) | `DatabricksCapability.get_wrapper_toolset` C2 · `GoogleSheetsCapability.get_wrapper_toolset` C2 | - |
| SQL query classifications (2) | readonly `SELECT 1` C4 · non-readonly `DROP TABLE t` C4 | - |
| pause turn execution per sensitive tool (9) | `jobs_run_now` C5 · `jobs_cancel_run` C5 · `jobs_create` C5 · `jobs_edit` C5 · `jobs_delete` C5 · `delivery_send_webhook` C5 · `create_google_sheet` C5 · `update_google_sheet` C5 · `dbsql_query` C5 | - |

- Claims naming a status code, route or response shape: none
- No other check claims more than the single case its proof exercises

## Swept

Where each unwritten requirement landed. All nine, one line each, every time.

- validation: C4
- failure modes: C3
- idempotency: n/a - approval evaluation is pure without side-effects
- authorization: existing - Caller token authorization in session API
- concurrency: existing - run locking in MemorySessionStore
- data lifecycle: n/a - approval record lifecycle unchanged
- dependency failure: n/a - in-process guardrail evaluation
- state transitions: C5
- observability: existing - ApprovalNotice emission via SSE

## Handoff

Size, with the arithmetic, written after the checks exist and before any code.

Under the budget — one builder, no ask:

- S1 = 5k in agent/turn.py, capabilities/databricks.py, capabilities/sheets.py, under 150k budget - one builder
