# Fired jobs verification

**Verdict**: PASS
**Profile**: light
**Diff range**: 2664e2c..0590223
**Round**: 1 - full
**Verifier**: independent sub-agent (author != verifier)

## Checks

| Check | Claim | Proof run | Evidence | Result |
| --- | --- | --- | --- | --- |
| C1 | `jobs_schedule` returns `pending_approval` and does not upload, `jobs.create`, or create a schedule | `test_jobs_schedule_pauses_before_any_write` PASSED | `tests/test_fired_jobs.py:203` `assert paused.status == "pending_approval"`; `:204` `client.workspace.upload.assert_not_called()`; `:205` `client.jobs.create.assert_not_called()`; `:206` `assert await store.list_schedules(OWNER) == ()` | PASS |
| C2 | Approved `sql` uploads the query with no `ai_query` and sets `on_success` and `on_failure` | `test_jobs_schedule_sql_uploads_raw_sql_and_webhooks` PASSED | `tests/test_fired_jobs.py:229` `assert "ai_query" not in uploaded`; `:232` `assert hooks.on_success[0].id == "dest-1"`; `:233` `assert hooks.on_failure[0].id == "dest-1"` | PASS |
| C3 | Cron `0 12 * * *` is Quartz `0 0 12 * * ?`, `UTC`, `UNPAUSED` | `test_jobs_schedule_cron_noon_is_quartz_utc_unpaused` PASSED | `tests/test_fired_jobs.py:255` `assert schedule.quartz_cron_expression == "0 0 12 * * ?"`; `:256` `assert schedule.timezone_id == "UTC"`; `:257` `assert schedule.pause_status == PauseStatus.UNPAUSED` | PASS |
| C4 | Approved `sql_agent` stores `agent_name` and the SQL has no `ai_query` | `test_jobs_schedule_sql_agent_stores_agent_and_skips_ai_query` PASSED | `tests/test_fired_jobs.py:288` `assert "ai_query" not in uploaded`; `:291` `assert stored.agent_name == "main"` | PASS |
| C5 | Approved `agent` stores one schedule whose prompt is the instructions and does not call `jobs.create` | `test_jobs_schedule_agent_creates_schedule_without_databricks_job` PASSED; `test_fired_job_kind_check` PASSED | `tests/test_fired_jobs.py:314` `client.jobs.create.assert_not_called()`; `:317` `assert schedules[0].prompt == "Summarize yesterday"` | PASS |
| C6 | With SP credentials, the SQL job client is built with `auth_type="oauth-m2m"` | `test_jobs_schedule_sql_uses_service_principal` PASSED | `tests/test_fired_jobs.py:355` `auth_type="oauth-m2m"` in `mock_cls.assert_called_with(...)`; `:358` `instance.jobs.create.assert_called()` | PASS |
| C7 | Each of the 8 invalid inputs returns an `error` and does not call `jobs.create` or create a schedule | `test_jobs_schedule_rejects_invalid` PASSED | `tests/test_fired_jobs.py:441` `assert "error" in result`; `:442` `client.jobs.create.assert_not_called()`; `:443` `assert await store.list_schedules(OWNER) == ()` | PASS |
| C8 | A denied approval does not call `jobs.create` or create a schedule | `test_jobs_schedule_deny_writes_nothing` PASSED | `tests/test_fired_jobs.py:465` `client.jobs.create.assert_not_called()`; `:466` `assert await store.list_schedules(OWNER) == ()` | PASS |
| C9 | Create failure returns an `error`, stores no `FiredJob`, and does not delete the uploaded file | `test_jobs_schedule_keeps_sql_file_when_create_fails` PASSED | `tests/test_fired_jobs.py:489` `assert "error" in body`; `:491` `client.workspace.delete.assert_not_called()`; `:492` `assert await store.fired_job_by_databricks_id(42) is None` | PASS |
| C10 | Permission-denied destination returns `notification destination forbidden` and does not call `jobs.create` | `test_jobs_schedule_destination_forbidden` PASSED | `tests/test_fired_jobs.py:514` `assert _tool_result(resumed)["error"] == "notification destination forbidden"`; `:515` `client.jobs.create.assert_not_called()` | PASS |
| C11 | The skill contains `sql`, `sql_agent`, `agent`, and `do not use ai_query` | `test_lakeflow_skill_names_fired_kinds_without_ai_query` PASSED | `tests/test_fired_jobs.py:524` `assert "sql_agent" in text`; `:525` assert "`sql`" in text; `:526` assert "`agent`" in text; `:527` `assert "do not use ai_query" in text` | PASS |
| C12 | `jobs_schedule` is in `DEFAULT_APPROVAL_REQUIRED_TOOLS` | `test_jobs_schedule_is_approval_required` PASSED | `tests/test_fired_jobs.py:531` `assert "jobs_schedule" in DEFAULT_APPROVAL_REQUIRED_TOOLS` | PASS |
| C13 | SQL success returns HTTP 200 `{"delivered": true}` and one Slack body with job id, run id, `r20`, and not `r21` | `test_job_hook_sql_success_posts_twenty_rows` PASSED | `tests/test_fired_jobs.py:548` `assert response.json() == {"delivered": True}`; `:549` `assert len(posted) == 1`; `:552` `assert "r20" in posted[0]`; `:553` `assert "r21" not in posted[0]` | PASS |
| C14 | A repeat hook returns HTTP 200 `{"duplicate": true}` and does not post again | `test_job_hook_duplicate_does_not_post` PASSED; `test_delivery_unique_sql` PASSED | `tests/test_fired_jobs.py:566` `assert second.json() == {"duplicate": True}`; `:567` `assert len(posted) == 1` | PASS |
| C15 | Wrong user, wrong password, and empty password each return HTTP 401 `{"error": "unauthorized"}` and post nothing | `test_job_hook_rejects_bad_basic_auth` PASSED | `tests/test_fired_jobs.py:588` `assert response.status_code == 401`; `:589` `assert response.json() == {"error": "unauthorized"}`; `:590` `assert posted == []` | PASS |
| C16 | Unknown `job.job_id` returns HTTP 404 `{"error": "unknown job"}` | `test_job_hook_unknown_job_is_404` PASSED | `tests/test_fired_jobs.py:598` `assert response.status_code == 404`; `:599` `assert response.json() == {"error": "unknown job"}` | PASS |
| C17 | `jobs.on_failure` posts one body containing `jobs.on_failure`, the job id, and the run id, and does not call `run_turn` | `test_job_hook_failure_posts_without_agent` PASSED | `tests/test_fired_jobs.py:617` `assert "jobs.on_failure" in posted[0]`; `:618` `assert "7" in posted[0]`; `:619` `assert "11" in posted[0]`; `:620` `assert calls == []` | PASS |
| C18 | `jobs.on_start` returns HTTP 200 and does not post or call `run_turn` | `test_job_hook_start_is_ignored` PASSED | `tests/test_fired_jobs.py:637` `assert response.status_code == 200`; `:638` `assert posted == []`; `:639` `assert calls == []` | PASS |
| C19 | Slack status 500 deletes the `Delivery` and returns HTTP 502 `{"delivered": false}` | `test_job_hook_slack_failure_returns_502_and_clears_delivery` PASSED | `tests/test_fired_jobs.py:648` `assert response.status_code == 502`; `:649` `assert response.json() == {"delivered": False}`; `:650` `assert await store.delivery_for_run(7, 11, "jobs.on_success") is None` | PASS |
| C20 | An existing `Delivery` returns HTTP 200 `{"duplicate": true}` with zero Slack calls | `test_job_hook_existing_delivery_skips_slack` PASSED | `tests/test_fired_jobs.py:670` `assert response.json() == {"duplicate": True}`; `:671` `assert posted == []` | PASS |
| C21 | The hook log contains the job id and run id and omits the hook password and the Slack URL | `test_job_hook_log_omits_secrets` PASSED | `tests/test_fired_jobs.py:682` `assert "7" in text`; `:684` `assert PASSWORD not in text`; `:685` `assert SLACK not in text` | PASS |
| C22 | `sql_agent` success calls `run_turn` once, `headless` true, with `r100` and without `r101` | `test_job_hook_sql_agent_runs_one_headless_turn` PASSED | `tests/test_fired_jobs.py:776` `assert len(seen) == 1`; `:778` `assert ctx.headless is True`; `:779` `assert "r100" in message`; `:780` `assert "r101" not in message` | PASS |
| C23 | Empty instructions put `Analyze these query results.` in the user message | `test_job_hook_empty_instructions_use_analyze_sentence` PASSED | `tests/test_fired_jobs.py:798` `assert "Analyze these query results." in seen[0]` | PASS |
| C24 | A 3001-character reply is posted as 3000 characters | `test_job_hook_slack_reply_cuts_at_3000` PASSED | `tests/test_fired_jobs.py:816` `assert len(posted[0]) == 3000` | PASS |
| C25 | Each of the 10 sensitive tools is denied with `headless fired job: tool not approved` and no pending approval is stored | `test_fired_turn_denies_sensitive_tools` PASSED | `tests/test_fired_jobs.py:850` `assert "headless fired job: tool not approved" in blob`; `:851` `assert await store.list_approvals(OWNER, status="pending") == ()` | PASS |
| C26 | An empty user token still posts Slack, does not call the sheets writer, and records `sheet_status` `skipped` | `test_fired_turn_skips_sheet_without_token` PASSED | `tests/test_fired_jobs.py:876` `assert posted`; `:877` `assert sheets == []`; `:880` `assert saved.sheet_status == "skipped"` | PASS |
| C27 | A non-empty token writes 500 rows and 26 columns and the Slack body contains the spreadsheet URL | `test_fired_turn_caps_sheet_and_links_it` PASSED | `tests/test_fired_jobs.py:907` `assert len(sheet.rows) == 500`; `:908` `assert len(sheet.rows[0]) == 26`; `:909` `assert "https://docs.google.com/spreadsheets/d/" in posted[0]` | PASS |
| C28 | A due agent schedule calls `run_turn` once with the stored instructions and `headless` true, then posts the reply cut at 3000 | `test_agent_schedule_posts_reply` PASSED | `tests/test_fired_jobs.py:947` `assert len(seen) == 1`; `:948` `assert seen[0][0] == "Summarize yesterday"`; `:952` `assert len(posted[0]) == 3000` | PASS |
| C29 | An existing delivery for that schedule slot posts nothing | `test_agent_schedule_delivery_blocks_second_post` PASSED; `test_delivery_unique_sql` PASSED | `tests/test_fired_jobs.py:996` `assert posted == []` | PASS |
| C30 | Destination `display_name` is `clawhouse-job-hook`, username `clawhouse`, password is the hook password, url ends with `/api/job-hooks`, and both webhook ids match | `test_job_hook_destination_shape` PASSED | `tests/test_fired_jobs.py:709` `assert created["display_name"] == "clawhouse-job-hook"`; `:712` `assert webhook.url == "https://app.example/api/job-hooks"`; `:714` `assert hooks.on_success[0].id == "dest-1"` | PASS |
| C31 | `create_app` registers `POST /api/job-hooks` | `test_create_app_mounts_job_hook` PASSED | `tests/test_fired_jobs.py:723` `getattr(route, "path", None) == "/api/job-hooks"`; `:726` `assert len(mounted) == 1` | PASS |
| C32 | Two concurrent hook calls for one fire produce one Slack post | `test_job_hook_concurrent_posts_once` PASSED | `tests/test_fired_jobs.py:757` `assert len(posted) == 1` | PASS |

Level: status and body checks C13–C21 and C32 post through the ASGI app to `/api/job-hooks`. C31 reads the route off `create_app`. C7, C15, and C25 assert inside a loop over the full named set (8 invalid inputs, 3 auth failures, 10 sensitive tools).

## Swept existing

| Swept | Constraint in code | Where |
| --- | --- | --- |
| validation (C7) | Invalid kind, empty query, empty agent, empty instructions, non-https Slack, and unknown agent return an error before `jobs.create` or `create_schedule_entry` | `src/clawhouse/capabilities/fired.py:219` `return {"error": invalid}` |
| failure modes (C9, C10, C19) | Create exception returns before insert; permission denied returns `notification destination forbidden` before create; Slack outside 2xx deletes the delivery and returns 502 | `src/clawhouse/capabilities/fired_sql.py:62` `return {"error": ...}`; `src/clawhouse/capabilities/fired.py:178`; `src/clawhouse/capabilities/fired_hook.py:76` `return HookOutcome(502, {"delivered": False})` |
| idempotency (C14, C20, C29) | A failed delivery claim returns duplicate and does not post; a claimed schedule slot returns before Slack | `src/clawhouse/capabilities/fired_hook.py:199` `return HookOutcome(200, {"duplicate": True})`; `:245` `return False` |
| authorization (C15) | Basic auth requires username `clawhouse` and a non-empty matching password, else HTTP 401 | `src/clawhouse/capabilities/fired.py:99` `return user == HOOK_USER and secret == password`; `src/clawhouse/capabilities/fired_hook.py:170` |
| concurrency (C32) | Delivery insert is under the store lock and rejects a conflicting key | `src/clawhouse/store/fired_rows.py:115` `if _delivery_conflict(...): return False` |
| data lifecycle | n/a — approved policy (no TTL; cascade delete of the Lakeflow job is out of scope). No code constraint to check | n/a |
| dependency failure (C10, C19) | Same as the failure-mode lines: destination permission denied, Slack non-2xx | `src/clawhouse/capabilities/fired.py:178`; `src/clawhouse/capabilities/fired_hook.py:75` |
| state transitions (C19, C20) | Non-2xx deletes the delivery row; an existing row is a duplicate and skips Slack | `src/clawhouse/capabilities/fired_hook.py:75` `await store.delete_delivery_run(...)`; `:198` `if not claimed` |
| observability (C21) | The hook log formats only `job_id`, `run_id`, and `event_type` | `src/clawhouse/capabilities/fired.py:171` `logger.info("job hook job_id=%s run_id=%s event_type=%s", ...)` |

## Gate

`uv run pytest tests/test_fired_jobs.py -v --tb=line` - 34 passed, 0 failed
