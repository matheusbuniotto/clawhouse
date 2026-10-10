"""Databricks Model Serving, via the OpenAI-compatible Chat Completions API.

The user token is the api key for this request only. It is not written to disk.
"""

from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.openai import OpenAIProvider


class MissingModelConfig(Exception):
    """SERVING_ENDPOINT or DATABRICKS_HOST is unset."""


class MissingAccessToken(Exception):
    """The request has no forwarded user token."""


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
