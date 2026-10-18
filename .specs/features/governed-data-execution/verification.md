# Governed Data Execution verification

**Verdict**: PASS
**Profile**: light
**Diff range**: 42cf8a5fb08b..cee2f551277e
**Round**: 2 - full
**Verifier**: independent sub-agent (author != verifier)

HEAD is `cee2f551277e`. Round 1 at `d5d586fe9253` failed C4 and C10. `cee2f55` changed only `tests/test_run_python_analysis.py` for this feature. This round re-ran every named proof at HEAD and re-judged C1–C13. Nothing was carried forward.

`tests/test_run_python_analysis.py` is added in `42cf8a5..HEAD` and edited in `cee2f55`. The two transcript proofs are added in `frontend/transcript.test.ts` in that range. Neither proof is an untouched pre-existing test.

Light profile: binding-source comparison, coverage recompute, test-policy verdicts, and fault injection did not run. `checks.md` has no `Test policy` section.

## Checks

| Check | Claim | Proof run | Evidence | Result |
| --- | --- | --- | --- | --- |
| C1 | forwarded token uploads `/Workspace/Shared/clawhouse/executions/{execution_id}.py` via `mkdirs` and `upload`, and `jobs.submit` once with `spark_python_task` source `WORKSPACE` | `uv run pytest tests/test_run_python_analysis.py -v --tb=short` exit 0; `test_uploads_shared_py_and_submits_spark_python_task` PASSED, not skipped | `tests/test_run_python_analysis.py:75` - `client.workspace.mkdirs.assert_called_once_with("/Workspace/Shared/clawhouse/executions")`; `tests/test_run_python_analysis.py:77` - `assert upload.args[0] == "/Workspace/Shared/clawhouse/executions/exec-1.py"`; `tests/test_run_python_analysis.py:82` - `assert task.spark_python_task.source == Source.WORKSPACE`; `tests/test_run_python_analysis.py:83` - `assert client.jobs.submit.call_count == 1` | PASS |
| C2 | submitted tool result contains `run_id`, `life_cycle_state`, and `run_page_url` | same pytest invocation; `test_submitted_run_returns_run_id_state_and_page_url` PASSED, not skipped | `tests/test_run_python_analysis.py:98` - `assert result["run_id"] == 9`; `tests/test_run_python_analysis.py:99` - `assert result["life_cycle_state"] == "TERMINATED"`; `tests/test_run_python_analysis.py:100` - `assert result["run_page_url"] == "https://example.cloud.databricks.com/#job/0/run/9"` | PASS |
| C3 | while not `TERMINATED`, `jobs.get_run` is polled at an interval of at most 5 seconds and polling stops when `timeout_seconds` elapses | same pytest invocation; `test_polls_at_most_every_5_seconds_until_timeout` PASSED, not skipped | `tests/test_run_python_analysis.py:126` - `assert max(sleeps) <= 5`; `tests/test_run_python_analysis.py:127` - `assert result["status"] == "TIMED_OUT_WAITING"`; `tests/test_run_python_analysis.py:128` - `assert client.jobs.get_run.call_count == 3` | PASS |
| C4 | `TERMINATED` / `SUCCESS` returns `logs` and `duration_ms`, and `logs` is at most the last 20000 characters | same pytest invocation; `test_success_returns_logs_capped_at_20000_and_duration_ms` PASSED, not skipped | `tests/test_run_python_analysis.py:143` - `assert result["result_state"] == "SUCCESS"`; `tests/test_run_python_analysis.py:144` - `assert result["duration_ms"] == 2_000`; `tests/test_run_python_analysis.py:148` - `assert logs == raw[-20_000:]`. `raw` is `"HEAD" + ("x" * 20_006) + "TAIL"` at `tests/test_run_python_analysis.py:139`. `tests/test_run_python_analysis.py:149` - `assert logs.endswith("TAIL")`; `tests/test_run_python_analysis.py:150` - `assert not logs.startswith("HEAD")` | PASS |
| C5 | `TERMINATED` / `FAILED` returns `result_state` `FAILED`, task `error`, and `run_page_url` | same pytest invocation; `test_failed_run_returns_error_and_page_url` PASSED, not skipped | `tests/test_run_python_analysis.py:164` - `assert result["result_state"] == "FAILED"`; `tests/test_run_python_analysis.py:165` - `assert result["error"] == "boom"`; `tests/test_run_python_analysis.py:166` - `assert result["run_page_url"] == "https://example.cloud.databricks.com/#job/0/run/9"` | PASS |
| C6 | timeout yields `status` `TIMED_OUT_WAITING` with `run_id` and `run_page_url`, and no cancel | same pytest invocation; `test_timeout_returns_timed_out_waiting_without_cancel` PASSED, not skipped | `tests/test_run_python_analysis.py:189` - `assert result["status"] == "TIMED_OUT_WAITING"`; `tests/test_run_python_analysis.py:190` - `assert result["run_id"] == 11`; `tests/test_run_python_analysis.py:191` - `assert result["run_page_url"] == "https://example.cloud.databricks.com/#job/0/run/11"`; `tests/test_run_python_analysis.py:192` - `client.jobs.cancel_run.assert_not_called()` | PASS |
| C7 | empty user token returns `{"error": "user token required"}`, does not `jobs.submit`, and does not read `CLAWHOUSE_JOBS_SP_CLIENT_ID` or `CLAWHOUSE_JOBS_SP_CLIENT_SECRET` | same pytest invocation; `test_missing_user_token_does_not_submit_or_use_jobs_sp` PASSED, not skipped | `tests/test_run_python_analysis.py:213` - `assert result == {"error": "user token required"}`; `tests/test_run_python_analysis.py:214` - `assert seen == []`; `tests/test_run_python_analysis.py:215` - `client.jobs.submit.assert_not_called()`. `seen` is appended only for those two env keys at `tests/test_run_python_analysis.py:202` | PASS |
| C8 | with `CLAWHOUSE_SENSITIVE_TOOLS` unset, the default sensitive-tool set includes `run_python_analysis` | same pytest invocation; `test_default_sensitive_set_includes_run_python_analysis` PASSED, not skipped | `tests/test_run_python_analysis.py:219` - `assert sensitive_tools_from_env({}) == ()`; `tests/test_run_python_analysis.py:220` - `assert "run_python_analysis" in DEFAULT_APPROVAL_REQUIRED_TOOLS` | PASS |
| C9 | unset `CLAWHOUSE_EXECUTION_TIMEOUT_SECONDS` passes `timeout_seconds` `120` to `jobs.submit`; `45` passes `45` | same pytest invocation; `test_timeout_seconds_defaults_to_120_and_honors_env` PASSED, not skipped | `tests/test_run_python_analysis.py:225` - `monkeypatch.delenv("CLAWHOUSE_EXECUTION_TIMEOUT_SECONDS", raising=False)`; `tests/test_run_python_analysis.py:234` - `assert client.jobs.submit.call_args.kwargs["timeout_seconds"] == 120`; `tests/test_run_python_analysis.py:236` - `monkeypatch.setenv("CLAWHOUSE_EXECUTION_TIMEOUT_SECONDS", "45")`; `tests/test_run_python_analysis.py:238` - `assert client.jobs.submit.call_args.kwargs["timeout_seconds"] == 45` | PASS |
| C10 | the turn emits a `tool_call` SSE frame whose `name` is `run_python_analysis` and whose `arguments` include `execution_id` | same pytest invocation; `test_tool_call_frame_names_run_python_analysis_and_execution_id` PASSED, not skipped | `tests/test_run_python_analysis.py:284` - `paused = await run_turn(SESSION, "analyze", ctx=ctx)` with `ctx.emit` capturing `ToolCallNotice` at `tests/test_run_python_analysis.py:283`; `tests/test_run_python_analysis.py:286` - `assert emitted, "turn emitted no tool_call notice"`; `tests/test_run_python_analysis.py:287` - `frame = _stream_frame(emitted[0])`; `tests/test_run_python_analysis.py:290` - `assert event == "tool_call"`; `tests/test_run_python_analysis.py:291` - `assert payload["name"] == "run_python_analysis"`; `tests/test_run_python_analysis.py:292` - `assert "exec-sse" in str(payload["arguments"])` | PASS |
| C11 | transcript renderer shows `result_state`, `duration_ms`, and `logs` from the `tool_result` frame | `npx vitest run frontend/transcript.test.ts -t "<both named titles>" --reporter=verbose` exit 0; `run_python_analysis renders result_state duration_ms and logs` passed, not skipped | `frontend/transcript.test.ts:491` - `expect(host.textContent).toContain("SUCCESS")`; `frontend/transcript.test.ts:492` - `expect(host.textContent).toContain("2000")`; `frontend/transcript.test.ts:493` - `expect(host.textContent).toContain("revenue by region")` | PASS |
| C12 | `FAILED` or `TIMED_OUT_WAITING` renders the error text and an anchor whose `href` is `run_page_url` | same vitest invocation; `run_python_analysis failure renders error and run_page_url` passed, not skipped | `frontend/transcript.test.ts:507` - `expect(host.querySelector(".analysis-error")?.textContent).toBe("boom")`; `frontend/transcript.test.ts:508` - `expect(host.querySelector("a")?.getAttribute("href")).toBe("https://example.cloud.databricks.com/run/9")`; `frontend/transcript.test.ts:521` - `expect(timed.textContent).toContain("TIMED_OUT_WAITING")`; `frontend/transcript.test.ts:522` - `expect(timed.querySelector("a")?.getAttribute("href")).toBe("https://example.cloud.databricks.com/run/11")` | PASS |
| C13 | headless turn with no user token returns `{"error": "user token required"}` and the turn still completes | same pytest invocation; `test_headless_turn_without_token_returns_user_token_required_and_continues` PASSED, not skipped | `tests/test_run_python_analysis.py:309` - `assert finished.status == "ok"`; `tests/test_run_python_analysis.py:311` - `assert json.loads(tool.content) == {"error": "user token required"}`. Precondition `headless=True` and empty token is `tests/test_run_python_analysis.py:261` inside `_ctx`, passed as `""` at `tests/test_run_python_analysis.py:301` | PASS |

## Swept existing

No Swept row resolves to `existing`. Re-read at `cee2f551277e`.

- validation, failure modes, authorization, dependency failure, state transitions, and observability cite checks. Those are not pre-existing guards. They stand or fall with the Checks table.
- idempotency, concurrency, and data lifecycle are `n/a` with approved reasons. Nothing in the code for those rows to be wrong about.

## Level and sampling

- C9 names both timeout cases (`120` unset, `45` set). Both are asserted in that proof. No sampling gap.
- C12 names `FAILED` and `TIMED_OUT_WAITING`. Both are asserted. No sampling gap.
- No other check names more cases than its proof exercises.
- C4 names the last 20000 characters. `logs == raw[-20_000:]` against a string that starts with `HEAD` and ends with `TAIL` settles the suffix. The round-1 uniform-string gap is closed.
- C5 and C6 name tool-result statuses. The assertions read those fields on the `run_python_analysis` return. That is the tool-result boundary.
- C10 names an emitted `tool_call` SSE frame. The notice comes from `run_turn`'s `emit` callback, then `_stream_frame` (the route's frame function) serializes it. `payload["name"]` can fail if the turn emits a different name. The round-1 level gap is closed.
- C12 names rendered error text and an `href`. The assertions are on the transcript renderer. Not a level gap.
- C13 names a completed headless turn and the error payload. The assertions are on `resume_turn`'s result. Not a level gap.

## Gate

`uv run pytest tests/test_run_python_analysis.py -v --tb=short` - 11 passed, 0 failed, 0 skipped. Each named pytest proof appeared as PASSED.

`npx vitest run frontend/transcript.test.ts -t "run_python_analysis renders result_state duration_ms and logs|run_python_analysis failure renders error and run_page_url" --reporter=verbose` - 2 passed, 0 failed, 29 skipped. The 29 skips are other tests in the file excluded by `-t`. The two named proofs printed as passed and were not skipped.
