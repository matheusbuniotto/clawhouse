"""Transcript replay. An unfinished tool call must not erase later turns."""

from pydantic_ai.messages import ModelMessage

from crabriks.history import to_model_messages
from crabriks.shapes import TranscriptEntry


def _texts(messages: list[ModelMessage]) -> list[str]:
    found: list[str] = []
    for message in messages:
        for part in message.parts:
            content = getattr(part, "content", None)
            if isinstance(content, str):
                found.append(content)
            args = getattr(part, "args", None)
            if isinstance(args, str):
                found.append(args)
    return found


def test_a_tool_pair_is_replayed_between_the_user_and_the_reply() -> None:
    messages = to_model_messages(
        (
            TranscriptEntry(role="user", content="hi"),
            TranscriptEntry(role="tool_call", content="{}", tool_name="clock", tool_call_id="c1"),
            TranscriptEntry(
                role="tool_result",
                content="2026-10-10T12:00:00Z",
                tool_name="clock",
                tool_call_id="c1",
            ),
            TranscriptEntry(role="assistant", content="noon"),
        )
    )
    assert _texts(messages) == ["hi", "{}", "2026-10-10T12:00:00Z", "noon"]


def test_an_unpaired_tool_call_does_not_drop_later_turns() -> None:
    messages = to_model_messages(
        (
            TranscriptEntry(role="user", content="first"),
            TranscriptEntry(role="tool_call", content="{}", tool_name="clock", tool_call_id="c1"),
            TranscriptEntry(role="user", content="second"),
            TranscriptEntry(role="assistant", content="later"),
        )
    )
    assert _texts(messages) == ["first", "second", "later"]
