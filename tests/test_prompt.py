"""Cache-stable system prompt for the platform agent."""

import pytest

from crabriks.prompt import CLOCK, build_system_prompt

SESSION_A = "11111111-1111-4111-8111-111111111111"
SESSION_B = "22222222-2222-4222-8222-222222222222"

EXPECTED_PREFIX = """\
# Identity
You are Crabriks, the platform agent main.

# Tools
- clock: Return the current UTC time as an ISO-8601 timestamp."""


def test_prefix_ignores_the_session_and_suffix_names_it() -> None:
    first = build_system_prompt(tools=(CLOCK,), session_id=SESSION_A)
    second = build_system_prompt(tools=(CLOCK,), session_id=SESSION_B)

    assert first.prefix == EXPECTED_PREFIX
    assert second.prefix == EXPECTED_PREFIX
    assert first.suffix == f"# Runtime\nsession_id: {SESSION_A}"
    assert second.suffix == f"# Runtime\nsession_id: {SESSION_B}"
    assert first.text == f"{EXPECTED_PREFIX}\n\n{first.suffix}"


def test_agent_without_a_tool_is_rejected() -> None:
    with pytest.raises(ValueError, match="at least one tool"):
        build_system_prompt(tools=(), session_id=SESSION_A)
