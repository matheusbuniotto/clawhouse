# Fired jobs checks

Profile: light
Plan: `.specs/features/fired-jobs/plan.md`

34 checks in 4 slices · 4 one-way doors · 2 open, of which 2 block go-live

## Checks

### S1 - Schedule three kinds from chat · 10 files · 94 KB · ~24k

**C1** - A turn that calls `jobs_schedule` returns `pending_approval` and does not upload a file, call `jobs.create`, or call `create_schedule` (AC 1) · done
Proof: `uv run pytest tests/test_fired_jobs.py -k test_jobs_schedule_pauses_before_any_write`

**C2** - Approved `kind="sql"` uploads the query text with no `ai_query` and creates one job whose `webhook_notifications` list both `on_success` and `on_failure` (AC 2) · done
Proof: `uv run pytest tests/test_fired_jobs.py -k test_jobs_schedule_sql_uploads_raw_sql_and_webhooks`

**C3** - Cron `0 12 * * *` with `timezone_id` omitted is sent as Quartz `0 0 12 * * ?`, timezone `UTC`, pause status `UNPAUSED` (AC 3) · done
Proof: `uv run pytest tests/test_fired_jobs.py -k test_jobs_schedule_cron_noon_is_quartz_utc_unpaused`

**C4** - Approved `kind="sql_agent"` stores `agent_name` on the `FiredJob` and the uploaded SQL does not contain `ai_query` (AC 4) · done
Proof: `uv run pytest tests/test_fired_jobs.py -k test_jobs_schedule_sql_agent_stores_agent_and_skips_ai_query`

**C5** - Approved `kind="agent"` creates one schedule whose prompt equals `instructions` and does not call `jobs.create` (AC 5) · done
Proof: `uv run pytest tests/test_fired_jobs.py -k test_jobs_schedule_agent_creates_schedule_without_databricks_job`
Proof: `uv run pytest tests/test_fired_jobs.py -k test_fired_job_kind_check`

**C6** - With `CLAWHOUSE_JOBS_SP_CLIENT_ID` and `CLAWHOUSE_JOBS_SP_CLIENT_SECRET` set, an approved `sql` schedule creates the job on a client built with `auth_type="oauth-m2m"` (AC 6) · done
Proof: `uv run pytest tests/test_fired_jobs.py -k test_jobs_schedule_sql_uses_service_principal`

**C7** - Each invalid `jobs_schedule` input returns an `error` and does not call `jobs.create` or `create_schedule` (AC 7) · done
Proof: `uv run pytest tests/test_fired_jobs.py -k test_jobs_schedule_rejects_invalid`

**C8** - A denied `jobs_schedule` approval does not call `jobs.create` or `create_schedule` (AC 8) · done
Proof: `uv run pytest tests/test_fired_jobs.py -k test_jobs_schedule_deny_writes_nothing`

**C9** - When the SQL upload succeeds and `jobs.create` raises, the result is an `error`, no `FiredJob` is stored, and the workspace file is still present (AC 9) · done
Proof: `uv run pytest tests/test_fired_jobs.py -k test_jobs_schedule_keeps_sql_file_when_create_fails`

**C10** - A permission-denied notification destination returns error `notification destination forbidden` and does not call `jobs.create` (AC 10) · done
Proof: `uv run pytest tests/test_fired_jobs.py -k test_jobs_schedule_destination_forbidden`

**C11** - `claw/agents/main/skills/lakeflow-jobs/SKILL.md` contains the literals `sql`, `sql_agent`, `agent`, and `do not use ai_query` (AC 11) · done
Proof: `uv run pytest tests/test_fired_jobs.py -k test_lakeflow_skill_names_fired_kinds_without_ai_query`

**C12** - `jobs_schedule` is a member of `DEFAULT_APPROVAL_REQUIRED_TOOLS` (AC 12) · done
Proof: `uv run pytest tests/test_fired_jobs.py -k test_jobs_schedule_is_approval_required`

### S2 - SQL success and failure reach Slack · 2 files · 11 KB · ~3k

**C13** - `POST /api/job-hooks` with `jobs.on_success` for `kind="sql"` returns HTTP 200 `{"delivered": true}` and posts one Slack body that contains the job id, the run id, row `r20`, and not row `r21` (AC 13) · done
Proof: `uv run pytest tests/test_fired_jobs.py -k test_job_hook_sql_success_posts_twenty_rows`

**C14** - A second `POST /api/job-hooks` with the same job id, run id, and `event_type` returns HTTP 200 `{"duplicate": true}` and does not post again (AC 14) · done
Proof: `uv run pytest tests/test_fired_jobs.py -k test_job_hook_duplicate_does_not_post`
Proof: `uv run pytest tests/test_fired_jobs.py -k test_delivery_unique_sql`

**C15** - Wrong Basic username, wrong password, and an empty `CLAWHOUSE_JOB_HOOK_PASSWORD` each return HTTP 401 `{"error": "unauthorized"}` and post nothing (AC 15) · done
Proof: `uv run pytest tests/test_fired_jobs.py -k test_job_hook_rejects_bad_basic_auth`

**C16** - An unknown `job.job_id` returns HTTP 404 `{"error": "unknown job"}` (AC 16) · done
Proof: `uv run pytest tests/test_fired_jobs.py -k test_job_hook_unknown_job_is_404`

**C17** - `jobs.on_failure` posts one Slack body containing `jobs.on_failure`, the job id, and the run id, and does not call `run_turn` (AC 17) · done
Proof: `uv run pytest tests/test_fired_jobs.py -k test_job_hook_failure_posts_without_agent`

**C18** - `jobs.on_start` returns HTTP 200 and does not post to Slack or call `run_turn` (AC 18) · done
Proof: `uv run pytest tests/test_fired_jobs.py -k test_job_hook_start_is_ignored`

**C19** - A Slack status 500 deletes the `Delivery` row and the hook returns HTTP 502 `{"delivered": false}` (AC 19) · done
Proof: `uv run pytest tests/test_fired_jobs.py -k test_job_hook_slack_failure_returns_502_and_clears_delivery`

**C20** - A `Delivery` row that already exists for that fire makes the hook return HTTP 200 `{"duplicate": true}` with zero Slack calls (AC 20) · done
Proof: `uv run pytest tests/test_fired_jobs.py -k test_job_hook_existing_delivery_skips_slack`

**C21** - The hook log line contains the job id and the run id and does not contain `CLAWHOUSE_JOB_HOOK_PASSWORD` or the Slack webhook URL (AC 21) · done
Proof: `uv run pytest tests/test_fired_jobs.py -k test_job_hook_log_omits_secrets`

**C30** - The notification destination `display_name` is `clawhouse-job-hook`, username `clawhouse`, password equals `CLAWHOUSE_JOB_HOOK_PASSWORD`, url ends with `/api/job-hooks`, and both job webhook ids equal that destination id (door 2) · done
Proof: `uv run pytest tests/test_fired_jobs.py -k test_job_hook_destination_shape`

**C31** - `create_app` registers `POST /api/job-hooks` (startup assembly) · done
Proof: `uv run pytest tests/test_fired_jobs.py -k test_create_app_mounts_job_hook`

**C32** - Two concurrent `POST /api/job-hooks` calls for one fire produce one Slack post (AC 14 race) · done
Proof: `uv run pytest tests/test_fired_jobs.py -k test_job_hook_concurrent_posts_once`

### S3 - SQL results enter one Clawhouse turn · 1 file · 14 KB · ~4k

**C22** - `jobs.on_success` for `kind="sql_agent"` calls `run_turn` once with `headless` true, the stored agent, a message that contains `r100`, and a message that does not contain `r101` (AC 22) · done
Proof: `uv run pytest tests/test_fired_jobs.py -k test_job_hook_sql_agent_runs_one_headless_turn`

**C23** - Empty instructions put the sentence `Analyze these query results.` in that user message (AC 23) · done
Proof: `uv run pytest tests/test_fired_jobs.py -k test_job_hook_empty_instructions_use_analyze_sentence`

**C24** - A 3001-character reply is posted to Slack as 3000 characters (AC 24) · done
Proof: `uv run pytest tests/test_fired_jobs.py -k test_job_hook_slack_reply_cuts_at_3000`

**C25** - On a fired headless turn, each tool in `DEFAULT_APPROVAL_REQUIRED_TOOLS` is denied with `headless fired job: tool not approved` and no pending approval is stored (AC 25) · done
Proof: `uv run pytest tests/test_fired_jobs.py -k test_fired_turn_denies_sensitive_tools`

**C26** - An empty user token posts Slack, does not call the sheets writer, and records `sheet_status` `skipped` (AC 26) · done
Proof: `uv run pytest tests/test_fired_jobs.py -k test_fired_turn_skips_sheet_without_token`

**C27** - A non-empty user token writes 500 rows and 26 columns from a 501-by-27 payload and the Slack body contains `https://docs.google.com/spreadsheets/d/` (AC 27) · done
Proof: `uv run pytest tests/test_fired_jobs.py -k test_fired_turn_caps_sheet_and_links_it`

### S4 - Agent schedule posts the reply · 1 file · 6 KB · ~2k

**C28** - A due `kind="agent"` schedule calls `run_turn` once with `headless` true and a user message equal to the stored instructions, then posts that reply cut at 3000 characters (AC 28) · done
Proof: `uv run pytest tests/test_fired_jobs.py -k test_agent_schedule_posts_reply`

**C29** - An existing `Delivery` for that schedule id and that `next_run_at` posts nothing (AC 29) · done
Proof: `uv run pytest tests/test_fired_jobs.py -k test_agent_schedule_delivery_blocks_second_post`
Proof: `uv run pytest tests/test_fired_jobs.py -k test_delivery_unique_sql`

## Coverage

| Set (size) | Member -> proof | Unproven |
| --- | --- | --- |
| FiredJob kind (3) | `sql` C2 · `sql_agent` C4 · `agent` C5 | - |
| `POST /api/job-hooks` statuses (4) | 200 C13 · 401 C15 · 404 C16 · 502 C19 | - |
| hook event_type (3) | `jobs.on_success` C13 · `jobs.on_failure` C17 · `jobs.on_start` C18 | - |
| success kind dispatch (2) | `sql` C13 · `sql_agent` C22 | - |
| invalid `jobs_schedule` input (8) | kind nope C7 · sql empty query C7 · sql_agent empty query C7 · sql_agent empty agent_name C7 · agent empty agent_name C7 · agent empty instructions C7 · slack http URL C7 · unknown agent C7 | - |
| hook Basic auth failure (3) | wrong username C15 · wrong password C15 · empty password C15 | - |
| sensitive fired-turn tools (10) | `jobs_run_now` C25 · `jobs_cancel_run` C25 · `jobs_create` C25 · `jobs_edit` C25 · `jobs_delete` C25 · `delivery_send_webhook` C25 · `create_google_sheet` C25 · `update_google_sheet` C25 · `run_python_analysis` C25 · `jobs_schedule` C25 | - |
| sheet token (2) | empty token C26 · non-empty token C27 | - |
| Landing doors (4) | door 1 C2 · door 2 C30 · door 3 C22 · door 4 C20 | - |
| Delivery dedup key (2) | job run event C14 · schedule slot C29 | - |
| startup config: job hook route (1) | `create_app` C31 | - |

- Claims naming a status code, route or response shape: C13, C14, C15, C16, C18, C19, C20, C31 - each proof calls `POST /api/job-hooks` or reads the route off `create_app`
- No other check claims more than the single case its proof exercises

## Swept

- validation: C7
- failure modes: C9, C10, C19
- idempotency: C14, C20, C29
- authorization: C15
- concurrency: C32
- data lifecycle: n/a - FiredJob rows have no TTL, and cascade delete of the Lakeflow job is out of scope
- dependency failure: C10, C19
- state transitions: C19, C20
- observability: C21

## Handoff

`wc -c` on the files each slice reads, divided by 4. New modules are not on disk yet; their allowance is stated beside the measured files.

- S1 = 24k. Measured 94,050 bytes across `jobs_client.py`, `jobs_tasks.py`, `tools.py`, `pauses.py`, `schema.py`, `memory.py`, `protocol.py`, `store.py`, `settings.py`, `lakeflow-jobs/SKILL.md` (94,050 / 4 = 23,512)
- S2 enters `app.py` (5,079 bytes, 1,270) plus an unwritten hook module allowed 8 KB (2k). Running total 27k
- S3 enters `runner.py` (13,945 bytes, 3,486). Running total 31k
- S4 enters `schedules.py` (6,361 bytes, 1,590). Running total 33k
- New `tests/test_fired_jobs.py` allowed 60 KB (15k). Running total 48k

Under the 150k budget — one builder, no ask.

- Mechanism: one builder
