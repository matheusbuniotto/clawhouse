# Unify Approvals verification

**Verdict**: PASS
**Profile**: light
**Diff range**: 82c345baecaf3216287cdc0d1080cd60a9ac1af0..HEAD
**Round**: 1 - full
**Verifier**: independent sub-agent (author != verifier)

## Checks

| Check | Claim | Proof run | Evidence | Result |
| --- | --- | --- | --- | --- |
| C1 | Mutating Lakeflow tools and Google Sheets write tools are defined in `DEFAULT_APPROVAL_REQUIRED_TOOLS` in `clawhouse.agent.turn` (AC 1) | `uv run pytest tests/test_approvals.py -k "test_default_approval_required_tools_contents"` exit 0 | `tests/test_approvals.py:657` - `assert expected == DEFAULT_APPROVAL_REQUIRED_TOOLS` | PASS |
| C2 | Neither `DatabricksCapability` nor `GoogleSheetsCapability` implements `get_wrapper_toolset` (AC 2) | `uv run pytest tests/test_approvals.py -k "test_capabilities_do_not_have_wrapper_toolset"` exit 0 | `tests/test_approvals.py:661` - `assert "get_wrapper_toolset" not in DatabricksCapability.__dict__` | PASS |
| C3 | `_sensitive_tool_guard` returns `GuardrailResult.approve()` for each default sensitive tool and configured dynamic sensitive tool (AC 3) | `uv run pytest tests/test_approvals.py -k "test_sensitive_tool_guard_returns_approve_for_all_sensitive_tools"` exit 0 | `tests/test_approvals.py:684` - `assert guard(call) == GuardrailResult.approve()` | PASS |
| C4 | `_sensitive_tool_guard` inspects `dbsql_query` and returns `GuardrailResult.approve()` for non-readonly SQL and `GuardrailResult.allow()` for readonly SQL (AC 4, AC 5) | `uv run pytest tests/test_approvals.py -k "test_sensitive_tool_guard_dbsql_query_sql_safety"` exit 0 | `tests/test_approvals.py:711` - `assert guard(call) == expected` | PASS |
| C5 | Parameterized execution of each sensitive tool during a chat turn pauses execution with status pending_approval and generates deferred tool requests (AC 6) | `uv run pytest tests/test_approvals.py -k "test_each_sensitive_tool_pauses_turn_and_generates_pending_approval"` exit 0 | `tests/test_approvals.py:763` - `assert result.status == "pending_approval"` | PASS |

## Gate

`uv run pytest tests/test_approvals.py tests/test_jobs_create_characterization.py` - 73 passed, 0 failed
