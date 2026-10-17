# Turn Deps User Token verification

**Verdict**: PASS
**Profile**: light
**Diff range**: 704b64e116c7838f9b452f8f7b53ae45ac72b9ac..HEAD
**Round**: 1 - full
**Verifier**: independent sub-agent (author != verifier)

## Checks

| Check | Claim | Proof run | Evidence | Result |
| --- | --- | --- | --- | --- |
| C1 | `TurnDeps` dataclass has `user_token: str = ""` field and is frozen (AC 1) | `uv run pytest tests/test_turn.py -k test_turn_deps_user_token_field` exit 0 | `tests/test_turn.py:1165` - `assert deps.user_token == "tok-123"` | PASS |
| C2 | `run_turn` populates `TurnDeps.user_token` from `TurnContext.user_token` (AC 2) | `uv run pytest tests/test_turn.py -k test_run_turn_populates_turn_deps_user_token` exit 0 | `tests/test_turn.py:1195` - `assert captured_deps[0].user_token == "usr-tok-777"` | PASS |
| C3 | `_capabilities_for_turn` leaves original `TurnContext.databricks_capability` instance attribute unmutated (AC 3) | `uv run pytest tests/test_turn.py -k test_capabilities_for_turn_does_not_mutate_original_capability` exit 0 | `tests/test_turn.py:1212` - `assert cap.user_token == ""` | PASS |
| C4 | Two concurrent turns with different user tokens using shared `DatabricksCapability` initialize tools with their respective tokens (AC 4) | `uv run pytest tests/test_turn.py -k test_concurrent_turns_use_distinct_user_tokens` exit 0 | `tests/test_turn.py:1279` - `assert clients_seen["user_a"] == ["token-a"]` | PASS |

## Gate

`uv run pytest tests/test_turn.py` - 30 passed, 0 failed
