"""Backward-compatible facade for crabriks.agent.model."""

from crabriks.agent.model import (
    MissingAccessToken,
    MissingModelConfig,
    ModelEntry,
    UnknownModel,
    databricks_chat_model,
    openai_compatible_chat_model,
    select_model,
)

__all__ = [
    "MissingAccessToken",
    "MissingModelConfig",
    "ModelEntry",
    "UnknownModel",
    "databricks_chat_model",
    "openai_compatible_chat_model",
    "select_model",
]
