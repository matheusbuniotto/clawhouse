# Turn Deps User Token Checks

Profile: light
Plan: `.specs/features/turn-deps-user-token/plan.md`

4 checks in 1 slice · 0 one-way doors · 0 open, of which 0 block

## Checks

Grouped by the spec's slices; numbering runs across the whole feature.

### S1 - Immutable Capability Resolution & TurnDeps Token · 3 files · ~65 KB · ~16k

**C1** - `TurnDeps` dataclass has `user_token: str = ""` field and is frozen (AC 1) · done
Proof: `uv run pytest tests/test_turn.py -k test_turn_deps_user_token_field`

**C2** - `run_turn` populates `TurnDeps.user_token` from `TurnContext.user_token` (AC 2) · done
Proof: `uv run pytest tests/test_turn.py -k test_run_turn_populates_turn_deps_user_token`

**C3** - `_capabilities_for_turn` leaves original `TurnContext.databricks_capability` instance attribute unmutated (AC 3) · done
Proof: `uv run pytest tests/test_turn.py -k test_capabilities_for_turn_does_not_mutate_original_capability`

**C4** - Two concurrent turns with different user tokens using shared `DatabricksCapability` initialize tools with their respective tokens (AC 4) · done
Proof: `uv run pytest tests/test_turn.py -k test_concurrent_turns_use_distinct_user_tokens`

## Coverage

| Set (size) | Member -> proof | Unproven |
| --- | --- | --- |
| Token propagation (2) | `TurnDeps` field C1 · `TurnContext` passed C2 | - |
| Capability immutability (2) | instance untouched C3 · concurrent isolation C4 | - |

- Claims naming a status code, route or response shape: none - internal turn dependencies and capability resolution only
- No other check claims more than the single case its proof exercises

## Swept

Where each unwritten requirement landed. All nine, one line each, every time.

- validation: C1
- failure modes: C4
- idempotency: C3
- authorization: C2, C4
- concurrency: C4
- data lifecycle: n/a - in-memory turn dependencies and capability objects discarded after turn completion
- dependency failure: n/a - no external service calls during dependency construction
- state transitions: C2, C3
- observability: C1, C2

## Handoff

Total size: 3 files · ~65 KB · ~16k tokens.
Under the 150k budget — one builder, no ask.
Mechanism: one builder.

- **Boundary:** C1-C4 closed
- **Settled mid-build:** none
- **Abandoned:** none
