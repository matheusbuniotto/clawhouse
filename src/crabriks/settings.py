"""Process configuration. Resource ids come from the environment, never from source."""

import json
from collections.abc import Mapping
from dataclasses import dataclass, replace

from crabriks.model import ModelEntry

MODELS_ENV = "CRABRIKS_MODELS"
DEFAULT_MODEL_ID = "databricks"


@dataclass(frozen=True, slots=True)
class Settings:
    dev_user: str | None
    dev_token: str | None
    serving_endpoint: str | None
    workspace_host: str | None
    models: tuple[ModelEntry, ...] = ()


def settings_from_env(env: Mapping[str, str]) -> Settings:
    return Settings(
        dev_user=env.get("CRABRIKS_DEV_USER") or None,
        dev_token=env.get("DATABRICKS_TOKEN") or None,
        serving_endpoint=env.get("SERVING_ENDPOINT") or env.get("DATABRICKS_MODEL") or None,
        workspace_host=env.get("DATABRICKS_HOST") or None,
        models=models_from_env(env),
    )


def models_from_env(env: Mapping[str, str]) -> tuple[ModelEntry, ...]:
    """The Databricks endpoint (if configured) plus `CRABRIKS_MODELS` entries.

    `CRABRIKS_MODELS` is a JSON array of OpenAI-compatible models:
    `[{"id": "...", "label": "...", "model": "...", "base_url": "...", "api_key_env": "..."}]`.
    """
    entries = list(_databricks_models(env))
    entries.extend(_compatible_models(env.get(MODELS_ENV)))
    return _mark_default(entries)


def request_token(
    *,
    forwarded: str,
    user_id: str,
    dev_user: str | None,
    dev_token: str | None,
) -> str:
    """The forwarded user token wins. A dev token applies only to the dev user."""
    if forwarded:
        return forwarded
    if dev_user and user_id == dev_user and dev_token:
        return dev_token
    return ""


def _databricks_models(env: Mapping[str, str]) -> tuple[ModelEntry, ...]:
    endpoint = env.get("SERVING_ENDPOINT") or env.get("DATABRICKS_MODEL")
    if not endpoint:
        return ()
    return (
        ModelEntry(
            id=DEFAULT_MODEL_ID,
            label=f"Databricks · {endpoint}",
            provider="databricks",
            model=endpoint,
            is_default=True,
        ),
    )


def _compatible_models(raw: str | None) -> tuple[ModelEntry, ...]:
    if not raw:
        return ()
    items: list[dict[str, str]] = json.loads(raw)
    return tuple(_compatible_entry(item) for item in items)


def _compatible_entry(item: Mapping[str, str]) -> ModelEntry:
    return ModelEntry(
        id=item["id"],
        label=item.get("label") or item["id"],
        provider="openai_compatible",
        model=item["model"],
        base_url=item["base_url"],
        api_key_env=item.get("api_key_env") or None,
    )


def _mark_default(entries: list[ModelEntry]) -> tuple[ModelEntry, ...]:
    if not entries or any(entry.is_default for entry in entries):
        return tuple(entries)
    return (replace(entries[0], is_default=True), *entries[1:])
