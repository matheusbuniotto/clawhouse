# Scheduled Turns Checks

Profile: light
Plan: `.specs/features/scheduled-turns/plan.md`

10 checks in 2 slices · 2 one-way doors · 0 open, of which 0 block

## Checks

Grouped by the spec's slices; numbering runs across the whole feature.

### S1 - Dedicated Service Principal & Jobs Identity Resolution · 3 files · ~52 KB · ~13k

**C1** - `settings_from_env` parses `CLAWHOUSE_JOBS_SP_CLIENT_ID` and `CLAWHOUSE_JOBS_SP_CLIENT_SECRET` into `Settings` (AC 1) · done
Proof: `uv run pytest tests/test_jobs_identity.py -k test_settings_jobs_sp_credentials`

**C2** - `jobs_identity` returns `JobsIdentity(kind="service_principal", ...)` with `oauth-m2m` when SP client_id and secret are set (AC 2) · done
Proof: `uv run pytest tests/test_jobs_identity.py -k test_jobs_identity_service_principal`

**C3** - `jobs_identity` returns `JobsIdentity(kind="user_obo", ...)` with `pat` when SP is unset and user_token is provided (AC 3) · done
Proof: `uv run pytest tests/test_jobs_identity.py -k test_jobs_identity_user_obo`

**C4** - `jobs_identity` raises `MissingJobsIdentityError` and does NOT fall back to ambient credentials when neither SP nor user token is available (AC 4) · done
Proof: `uv run pytest tests/test_jobs_identity.py -k test_jobs_identity_missing_raises`

**C5** - `jobs_create`, `jobs_edit`, `jobs_run_now`, and `jobs_cancel_run` return `identity` containing `kind` and `label` on success (AC 5) · done
Proof: `uv run pytest tests/test_jobs_identity.py -k test_mutating_jobs_tools_return_identity`

**C6** - Mutating jobs tools return descriptive error dict when no jobs execution identity is configured (AC 6) · done
Proof: `uv run pytest tests/test_jobs_identity.py -k test_jobs_create_fails_without_identity`

### S2 - Robust Next Run Advance & Atomic Schedule Claiming · 3 files · ~68 KB · ~17k

**C7** - `LakebaseSessionStore.claim_due_schedules` selects active due schedules using `FOR UPDATE SKIP LOCKED` (AC 7) · done
Proof: `uv run pytest tests/test_schedules.py -k test_claim_due_schedules_uses_skip_locked`

**C8** - `run_scheduled_turn` advances `next_run_at` to the next cron interval and sets `last_status="ok"` on success (AC 8) · done
Proof: `uv run pytest tests/test_schedules.py -k test_run_scheduled_turn_success_advances_and_records_status`

**C9** - `run_scheduled_turn` advances `next_run_at` to the next cron interval and records `last_status="error"` and `last_error` when turn execution raises an exception (AC 9) · done
Proof: `uv run pytest tests/test_schedules.py -k test_run_scheduled_turn_error_advances_and_records_error`

**C10** - `schedule_worker` processes a batch of due schedules and continues processing remaining items when one item raises an exception (AC 10) · done
Proof: `uv run pytest tests/test_schedules.py -k test_schedule_worker_continues_on_item_error`

## Coverage

| Set (size) | Member -> proof | Unproven |
| --- | --- | --- |
| `JobsIdentity` kind (2) | `service_principal` C2 · `user_obo` C3 | - |
| Mutating jobs tools identity metadata (4) | `jobs_create` C5 · `jobs_edit` C5 · `jobs_run_now` C5 · `jobs_cancel_run` C5 | - |
| Schedule execution status (2) | `ok` C8 · `error` C9 | - |
| Missing identity error rejection (2) | `jobs_identity` C4 · `jobs_create` C6 | - |

- Claims naming a status code, route or response shape: none - internal jobs identity resolution and Lakebase store operations only
- No other check claims more than the single case its proof exercises

## Swept

Where each unwritten requirement landed. All nine, one line each, every time.

- validation: C1
- failure modes: C9, C10
- idempotency: C8
- authorization: C3, C4
- concurrency: C7
- data lifecycle: n/a - schedule records in Lakebase persist last run timestamp and status without premature deletion
- dependency failure: C4, C6
- state transitions: C8, C9
- observability: C2, C5

## Handoff

Total size: 6 files · ~120 KB · ~30k tokens.
Under the 150k budget — one builder, no ask.
Mechanism: one builder.

- **Boundary:** C1-C10 closed
- **Settled mid-build:** none
- **Abandoned:** none
