# Remove Tool Cards Checks

Profile: light
Plan: `.specs/features/remove-tool-cards/plan.md`

5 checks in 1 slice · 0 one-way doors · 0 open, of which 0 block

## Checks

Grouped by the spec's slices; numbering runs across the whole feature.

### S1 - Remove Manual Tool Cards and Redundant System Prompt Tools · 4 files · ~55 KB · ~14k

**C1** - `build_system_prompt` called without `tools` succeeds without `ValueError` and produces prompt without `# Tools` (AC 1, AC 2) · done
Proof: `uv run pytest tests/test_prompt.py -k test_build_system_prompt_omits_tools_when_none_provided`

**C2** - `build_system_prompt` with explicit `tools` renders `# Tools` for backwards compatibility (AC 1) · done
Proof: `uv run pytest tests/test_prompt.py -k test_system_prompt_preserves_deterministic_order_of_tools`

**C3** - Manual tool cards constants are removed from `turn.py` and `sheets.py` (AC 3) · done
Proof: `uv run pytest tests/test_prompt.py -k test_manual_tool_card_constants_are_removed`

**C4** - `_prompt_for` builds system prompt without injecting manual tool cards into prompt (AC 4) · done
Proof: `uv run pytest tests/test_turn.py -k test_prompt_for_omits_tool_cards`

**C5** - Evals and turn tool execution with capabilities continue to pass without regression (AC 5) · done
Proof: `uv run pytest tests/test_evals.py -k test_worked_example_dataset_runs_and_passes_all_assertions`

## Coverage

| Set (size) | Member -> proof | Unproven |
| --- | --- | --- |
| Prompt generation (2) | omitted tools C1 · custom tools C2 | - |
| Catalog removal (2) | constants removed C3 · prompt_for omits cards C4 | - |
| Evals integrity (1) | evals pass C5 | - |

- Claims naming a status code, route or response shape: none - internal prompt composition and tool catalog removal only
- No other check claims more than the single case its proof exercises

## Swept

Where each unwritten requirement landed. All nine, one line each, every time.

- validation: C1, C2
- failure modes: C1
- idempotency: C1, C4
- authorization: n/a - system prompt generation does not check user permissions directly
- concurrency: n/a - pure string and dataclass composition with no shared mutable state
- data lifecycle: n/a - system prompts are composed per-turn in memory
- dependency failure: n/a - no external service calls during prompt assembly
- state transitions: C4
- observability: C1, C4

## Handoff

Total size: 4 files · ~55 KB · ~14k tokens.
Under the 150k budget — one builder, no ask.
Mechanism: one builder.

- **Boundary:** C1-C5 closed
- **Settled mid-build:** none
- **Abandoned:** none
