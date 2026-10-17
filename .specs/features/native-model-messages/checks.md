# native-model-messages checks

Profile: light
Plan: `.specs/features/native-model-messages/plan.md`

## Intent

<5 checks in 1 slice · 1 one-way door · 0 open, of which 0 block>

## Checks

Grouped by the spec's slices; numbering runs across the whole feature.

### S1 - Native ModelMessages Storage and Turn Resume · 4 files · 15 KB · ~15k

**C1** - MemorySessionStore and LakebaseSessionStore store and retrieve native messages via save_messages and messages, and clear messages on clear_transcript (AC 1, AC 5)
Proof: `uv run pytest tests/test_history.py -k "test_session_store_native_messages_lifecycle"`

**C2** - Executing a chat turn or pausing for approval persists native messages to the store (AC 2)
Proof: `uv run pytest tests/test_history.py -k "test_chat_turn_persists_native_messages"`

**C3** - Resuming an approval turn executes using persisted native messages without replacing [REDACTED] tokens in arguments (AC 3)
Proof: `uv run pytest tests/test_history.py -k "test_resume_turn_uses_native_messages_without_redaction_replacement"`

**C4** - Sessions without stored native messages fall back to to_model_messages transcript reconstruction (AC 4)
Proof: `uv run pytest tests/test_history.py -k "test_turn_history_fallback_for_legacy_sessions"`

**C5** - _transcript_to_messages is removed from clawhouse.capabilities.mentions in favor of shared history loading (AC 6)
Proof: `uv run pytest tests/test_mentions_and_compaction.py -k "test_mentions_module_does_not_have_transcript_to_messages"`

## Coverage

| Set (size) | Member -> proof | Unproven |
| --- | --- | --- |
| store implementations (2) | `MemorySessionStore` C1 · `LakebaseSessionStore` C1 | - |
| turn execution modes (2) | normal ok turn C2 · paused approval turn C2 | - |
| resume decisions (2) | approved C3 · denied C3 | - |
| history source resolution (2) | native messages present C2 · legacy fallback C4 | - |
| mentions module helpers (1) | `_transcript_to_messages` removed C5 | - |

- Claims naming a status code, route or response shape: none
- No other check claims more than the single case its proof exercises

## Swept

Where each unwritten requirement landed. All nine, one line each, every time.

- validation: C1
- failure modes: C4
- idempotency: n/a - message saving is idempotent per turn
- authorization: existing - Caller authorization in session API
- concurrency: existing - run locking in MemorySessionStore and Lakebase
- data lifecycle: C1
- dependency failure: C4
- state transitions: C3
- observability: existing - turn notices and events

## Handoff

Size, with the arithmetic, written after the checks exist and before any code.

Under the budget — one builder, no ask:

- S1 = 15k across store/store.py, agent/turn.py, capabilities/mentions.py, under 150k budget - one builder
