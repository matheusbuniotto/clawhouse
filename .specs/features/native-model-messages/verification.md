# Native Model Messages verification

**Verdict**: PASS
**Profile**: light
**Diff range**: e64ced7a8251ca09365287f484174d6301313f8f..HEAD
**Round**: 1 - full
**Verifier**: independent sub-agent (author != verifier)

## Checks

| Check | Claim | Proof run | Evidence | Result |
| --- | --- | --- | --- | --- |
| C1 | MemorySessionStore and LakebaseSessionStore store and retrieve native messages via save_messages and messages, and clear messages on clear_transcript (AC 1, AC 5) | `uv run pytest tests/test_history.py -k "test_session_store_native_messages_lifecycle"` exit 0 | `tests/test_history.py:76` - `assert await mem_store.messages(session.id) == payload` | PASS |
| C2 | Executing a chat turn or pausing for approval persists native messages to the store (AC 2) | `uv run pytest tests/test_history.py -k "test_chat_turn_persists_native_messages"` exit 0 | `tests/test_history.py:152` - `assert raw is not None` | PASS |
| C3 | Resuming an approval turn executes using persisted native messages without replacing [REDACTED] tokens in arguments (AC 3) | `uv run pytest tests/test_history.py -k "test_resume_turn_uses_native_messages_without_redaction_replacement"` exit 0 | `tests/test_history.py:275` - `assert b"[REDACTED]" not in raw` | PASS |
| C4 | Sessions without stored native messages fall back to to_model_messages transcript reconstruction (AC 4) | `uv run pytest tests/test_history.py -k "test_turn_history_fallback_for_legacy_sessions"` exit 0 | `tests/test_history.py:390` - `assert "Legacy turn 1" in texts` | PASS |
| C5 | _transcript_to_messages is removed from clawhouse.capabilities.mentions in favor of shared history loading (AC 6) | `uv run pytest tests/test_mentions_and_compaction.py -k "test_mentions_module_does_not_have_transcript_to_messages"` exit 0 | `tests/test_mentions_and_compaction.py:258` - `assert not hasattr(mentions_module, "_transcript_to_messages")` | PASS |

## Gate

`uv run pytest tests/test_history.py tests/test_mentions_and_compaction.py` - 16 passed, 0 failed
