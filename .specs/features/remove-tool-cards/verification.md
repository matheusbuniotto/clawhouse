# Remove Tool Cards verification

**Verdict**: PASS
**Profile**: light
**Diff range**: f75e0aed95c6533ae156135e232031ec5543704d..HEAD
**Round**: 1 - full
**Verifier**: independent sub-agent (author != verifier)

## Checks

| Check | Claim | Proof run | Evidence | Result |
| --- | --- | --- | --- | --- |
| C1 | `build_system_prompt` called without `tools` succeeds without `ValueError` and produces prompt without `# Tools` (AC 1, AC 2) | `uv run pytest tests/test_prompt.py -k test_build_system_prompt_omits_tools_when_none_provided` exit 0 | `tests/test_prompt.py:40` - `assert "# Tools" not in prompt_default.text` | PASS |
| C2 | `build_system_prompt` with explicit `tools` renders `# Tools` for backwards compatibility (AC 1) | `uv run pytest tests/test_prompt.py -k test_system_prompt_preserves_deterministic_order_of_tools` exit 0 | `tests/test_prompt.py:191` - `assert tools_section in prompt.prefix` | PASS |
| C3 | Manual tool cards constants are removed from `turn.py` and `sheets.py` (AC 3) | `uv run pytest tests/test_prompt.py -k test_manual_tool_card_constants_are_removed` exit 0 | `tests/test_prompt.py:48` - `assert not hasattr(turn_mod, "DATABRICKS_TOOL_CARDS")` | PASS |
| C4 | `_prompt_for` builds system prompt without injecting manual tool cards into prompt (AC 4) | `uv run pytest tests/test_turn.py -k test_prompt_for_omits_tool_cards` exit 0 | `tests/test_turn.py:1287` - `assert "# Tools" not in prompt.prefix` | PASS |
| C5 | Evals and turn tool execution with capabilities continue to pass without regression (AC 5) | `uv run pytest tests/test_evals.py -k test_worked_example_dataset_runs_and_passes_all_assertions` exit 0 | `tests/test_evals.py:167` - `assert len(report.failures) == 0` | PASS |

## Gate

`uv run pytest tests/test_prompt.py tests/test_turn.py tests/test_evals.py` - 47 passed, 0 failed
