# Scheduled Turns verification

**Verdict**: PASS
**Profile**: light
**Diff range**: 704b64e116c7838f9b452f8f7b53ae45ac72b9ac..HEAD
**Round**: 1 - full
**Verifier**: independent sub-agent (author != verifier)

## Checks

| Check | Claim | Proof run | Evidence | Result |
| --- | --- | --- | --- | --- |
| C1 | `settings_from_env` parses `CLAWHOUSE_JOBS_SP_CLIENT_ID` and `CLAWHOUSE_JOBS_SP_CLIENT_SECRET` into `Settings` (AC 1) | `uv run pytest tests/test_jobs_identity.py -k test_settings_jobs_sp_credentials` exit 0 | `tests/test_jobs_identity.py:22` - `assert settings.jobs_sp_client_id == "test-sp-client-id" and settings.jobs_sp_client_secret == "test-sp-client-secret"` | PASS |
| C2 | `jobs_identity` returns `JobsIdentity(kind="service_principal", ...)` with `oauth-m2m` when SP client_id and secret are set (AC 2) | `uv run pytest tests/test_jobs_identity.py -k test_jobs_identity_service_principal` exit 0 | `tests/test_jobs_identity.py:41` - `assert ident.kind == "service_principal" and ident.label == "sp-client-123"` | PASS |
| C3 | `jobs_identity` returns `JobsIdentity(kind="user_obo", ...)` with `pat` when SP is unset and user_token is provided (AC 3) | `uv run pytest tests/test_jobs_identity.py -k test_jobs_identity_user_obo` exit 0 | `tests/test_jobs_identity.py:54` - `assert ident.kind == "user_obo" and ident.label == "user"` | PASS |
| C4 | `jobs_identity` raises `MissingJobsIdentityError` and does NOT fall back to ambient credentials when neither SP nor user token is available (AC 4) | `uv run pytest tests/test_jobs_identity.py -k test_jobs_identity_missing_raises` exit 0 | `tests/test_jobs_identity.py:61` - `pytest.raises(MissingJobsIdentityError)` and `mock_wc.assert_not_called()` | PASS |
| C5 | `jobs_create`, `jobs_edit`, `jobs_run_now`, and `jobs_cancel_run` return `identity` containing `kind` and `label` on success (AC 5) | `uv run pytest tests/test_jobs_identity.py -k test_mutating_jobs_tools_return_identity` exit 0 | `tests/test_jobs_identity.py:82` - `assert res_create["identity"] == {"kind": "service_principal", "label": "sp-client-123"}` | PASS |
| C6 | Mutating jobs tools return descriptive error dict when no jobs execution identity is configured (AC 6) | `uv run pytest tests/test_jobs_identity.py -k test_jobs_create_fails_without_identity` exit 0 | `tests/test_jobs_identity.py:111` - `assert "no jobs execution identity configured" in str(res["error"]).lower()` | PASS |
| C7 | `LakebaseSessionStore.claim_due_schedules` selects active due schedules using `FOR UPDATE SKIP LOCKED` (AC 7) | `uv run pytest tests/test_schedules.py -k test_claim_due_schedules_uses_skip_locked` exit 0 | `tests/test_schedules.py:291` - `assert "FOR UPDATE SKIP LOCKED" in sql and "ORDER BY next_run_at ASC" in sql` | PASS |
| C8 | `run_scheduled_turn` advances `next_run_at` to the next cron interval and sets `last_status="ok"` on success (AC 8) | `uv run pytest tests/test_schedules.py -k test_run_scheduled_turn_success_advances_and_records_status` exit 0 | `tests/test_schedules.py:348` - `assert updated.next_run_at == datetime(2026, 10, 12, 12, 15, tzinfo=UTC) and updated.last_status == "ok"` | PASS |
| C9 | `run_scheduled_turn` advances `next_run_at` to the next cron interval and records `last_status="error"` and `last_error` when turn execution raises an exception (AC 9) | `uv run pytest tests/test_schedules.py -k test_run_scheduled_turn_error_advances_and_records_error` exit 0 | `tests/test_schedules.py:394` - `assert updated.next_run_at == datetime(2026, 10, 12, 12, 20, tzinfo=UTC) and updated.last_status == "error"` | PASS |
| C10 | `schedule_worker` processes a batch of due schedules and continues processing remaining items when one item raises an exception (AC 10) | `uv run pytest tests/test_schedules.py -k test_schedule_worker_continues_on_item_error` exit 0 | `tests/test_schedules.py:465` - `assert executed == ["Fail please", "Succeed please"] and schedules["sch-failing"].last_status == "error"` | PASS |

## Gate

`uv run pytest tests/test_jobs_identity.py tests/test_schedules.py` - 19 passed, 0 failed
