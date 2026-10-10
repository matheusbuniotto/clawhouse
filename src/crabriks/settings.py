"""Process configuration. Resource ids come from the environment, never from source."""

from collections.abc import Mapping
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Settings:
    dev_user: str | None
    dev_token: str | None
    serving_endpoint: str | None
    workspace_host: str | None


def settings_from_env(env: Mapping[str, str]) -> Settings:
    return Settings(
        dev_user=env.get("CRABRIKS_DEV_USER") or None,
        dev_token=env.get("DATABRICKS_TOKEN") or None,
        serving_endpoint=env.get("SERVING_ENDPOINT") or env.get("DATABRICKS_MODEL") or None,
        workspace_host=env.get("DATABRICKS_HOST") or None,
    )


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
