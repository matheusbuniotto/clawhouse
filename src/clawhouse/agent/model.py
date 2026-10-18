"""Model providers: Databricks Model Serving plus any OpenAI-compatible endpoint.

Databricks uses the forwarded user token as the api key for that request only; it
is never written to disk. Other providers read their api key from the environment
by name, so secrets stay out of the model catalog.
"""

from dataclasses import dataclass
from typing import Literal

from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.openai import OpenAIProvider

Provider = Literal["databricks", "openai_compatible"]


class MissingModelConfig(Exception):
    """A provider is missing its endpoint, model, host, or api key."""


class MissingAccessToken(Exception):
    """The request has no forwarded user token."""


class UnknownModel(Exception):
    """No configured model matches the requested id."""


@dataclass(frozen=True, slots=True)
class ModelEntry:
    """One selectable model. `api_key_env` names where the secret lives, never holds it."""

    id: str
    label: str
    provider: Provider
    model: str
    base_url: str | None = None
    api_key_env: str | None = None
    is_default: bool = False


def databricks_chat_model(
    *,
    endpoint: str,
    workspace_host: str,
    access_token: str,
) -> OpenAIChatModel:
    if not endpoint or not workspace_host:
        raise MissingModelConfig
    if not access_token:
        raise MissingAccessToken
    host = workspace_host.removeprefix("https://").strip("/")
    return OpenAIChatModel(
        endpoint,
        provider=OpenAIProvider(
            base_url=f"https://{host}/serving-endpoints",
            api_key=access_token,
        ),
    )


def openai_compatible_chat_model(
    *,
    model: str,
    base_url: str,
    api_key: str,
) -> OpenAIChatModel:
    """An OpenRouter or any other OpenAI-compatible Chat Completions endpoint."""
    if not model or not base_url or not api_key:
        raise MissingModelConfig
    return OpenAIChatModel(
        model,
        provider=OpenAIProvider(base_url=base_url, api_key=api_key),
    )


def _select_default_model(models: tuple[ModelEntry, ...]) -> ModelEntry:
    for entry in models:
        if entry.is_default:
            return entry
    if models:
        return models[0]
    raise MissingModelConfig


def select_model(models: tuple[ModelEntry, ...], model_id: str | None) -> ModelEntry:
    """The requested model, or the default when no id is given."""
    if model_id is None:
        return _select_default_model(models)
    for entry in models:
        if model_id in (entry.id, entry.model):
            return entry
    raise UnknownModel(model_id)
