"""Agent reasoning loop, turn execution, model connectors, and prompt composition."""

from crabriks.agent.core import (
    ApprovalRequired,
    TurnDeps,
    crabriks_agent,
    format_utc,
)
from crabriks.agent.history import to_model_messages
from crabriks.agent.model import (
    ModelEntry,
    databricks_chat_model,
    openai_compatible_chat_model,
    select_model,
)
from crabriks.agent.prompt import (
    AGENT_NAME,
    SystemPrompt,
    build_system_prompt,
)
from crabriks.agent.turn import (
    ApprovalNotice,
    Token,
    ToolCallNotice,
    ToolResultNotice,
    TurnContext,
    TurnNotice,
    TurnResult,
    iter_resume_turn,
    iter_turn,
    resume_turn,
    run_turn,
)

__all__ = [
    "AGENT_NAME",
    "ApprovalNotice",
    "ApprovalRequired",
    "ModelEntry",
    "SystemPrompt",
    "Token",
    "ToolCallNotice",
    "ToolResultNotice",
    "TurnContext",
    "TurnDeps",
    "TurnNotice",
    "TurnResult",
    "build_system_prompt",
    "crabriks_agent",
    "databricks_chat_model",
    "format_utc",
    "iter_resume_turn",
    "iter_turn",
    "openai_compatible_chat_model",
    "resume_turn",
    "run_turn",
    "select_model",
    "to_model_messages",
]
