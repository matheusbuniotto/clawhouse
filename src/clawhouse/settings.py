"""Process configuration. Resource ids come from the environment, never from source."""

import json
import math
from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import TypeGuard

from clawhouse.agent.model import ModelEntry
from clawhouse.capabilities.mcp import DuplicateMCPServerName, MCPServerConfig

MODELS_ENV = "CLAWHOUSE_MODELS"
MCP_SERVERS_ENV = "CLAWHOUSE_MCP_SERVERS"
DEFAULT_MODEL_ID = "databricks"


def default_agent_root() -> Path:
    """The app source root: two levels above this package when run from `src/`."""
    return Path(__file__).resolve().parents[2]


@dataclass(frozen=True, slots=True)
class Settings:
    dev_user: str | None
    dev_token: str | None
    serving_endpoint: str | None
    workspace_host: str | None
    models: tuple[ModelEntry, ...] = ()
    mcp_servers: tuple[MCPServerConfig, ...] = ()
    agent_root: Path = field(default_factory=default_agent_root)
    sensitive_tools: tuple[str, ...] = ()
    log_tail_url: str | None = None
    telemetry_enabled: bool = True
    otel_endpoint: str | None = None
    otel_headers: str | None = None
    logfire_token: str | None = None
    mlflow_enabled: bool = False
    mlflow_experiment: str | None = None
    jobs_sp_client_id: str | None = None
    jobs_sp_client_secret: str | None = None


def telemetry_enabled_from_env(env: Mapping[str, str]) -> bool:
    raw = env.get("CLAWHOUSE_TELEMETRY")
    if raw is None:
        return True
    return raw.strip().lower() not in {"0", "false", "no"}


def mlflow_enabled_from_env(env: Mapping[str, str]) -> bool:
    raw = env.get("CLAWHOUSE_MLFLOW_TRACING")
    if raw is not None:
        return raw.strip().lower() not in {"0", "false", "no"}
    return bool(
        env.get("MLFLOW_TRACKING_URI")
        or env.get("MLFLOW_EXPERIMENT_NAME")
        or env.get("MLFLOW_EXPERIMENT_ID")
    )


def settings_from_env(env: Mapping[str, str]) -> Settings:
    return Settings(
        dev_user=env.get("CLAWHOUSE_DEV_USER") or None,
        dev_token=env.get("DATABRICKS_TOKEN") or None,
        serving_endpoint=env.get("SERVING_ENDPOINT") or env.get("DATABRICKS_MODEL") or None,
        workspace_host=env.get("DATABRICKS_HOST") or None,
        models=models_from_env(env),
        mcp_servers=mcp_servers_from_env(env),
        sensitive_tools=sensitive_tools_from_env(env),
        log_tail_url=env.get("CLAWHOUSE_LOG_TAIL_URL") or env.get("LOG_TAIL_URL") or None,
        telemetry_enabled=telemetry_enabled_from_env(env),
        otel_endpoint=env.get("OTEL_EXPORTER_OTLP_ENDPOINT") or None,
        otel_headers=env.get("OTEL_EXPORTER_OTLP_HEADERS") or None,
        logfire_token=env.get("LOGFIRE_TOKEN") or None,
        mlflow_enabled=mlflow_enabled_from_env(env),
        mlflow_experiment=env.get("MLFLOW_EXPERIMENT_NAME") or env.get("MLFLOW_EXPERIMENT") or None,
        jobs_sp_client_id=env.get("CLAWHOUSE_JOBS_SP_CLIENT_ID") or None,
        jobs_sp_client_secret=env.get("CLAWHOUSE_JOBS_SP_CLIENT_SECRET") or None,
    )


def sensitive_tools_from_env(env: Mapping[str, str]) -> tuple[str, ...]:
    raw = env.get("CLAWHOUSE_SENSITIVE_TOOLS")
    if not raw:
        return ()
    stripped = raw.strip()
    if stripped.startswith(("[", "{")):
        loaded = json.loads(stripped)
        if not _tool_name_list(loaded):
            raise ValueError("CLAWHOUSE_SENSITIVE_TOOLS JSON must be a list of tool names")
        return tuple(name.strip() for name in loaded)
    return tuple(part.strip() for part in raw.split(",") if part.strip())


def _tool_name_list(loaded: object) -> TypeGuard[list[str]]:
    if not isinstance(loaded, list):
        return False
    return all(isinstance(name, str) and name.strip() for name in loaded)


def models_from_env(env: Mapping[str, str]) -> tuple[ModelEntry, ...]:
    """The Databricks endpoint (if configured) plus `CLAWHOUSE_MODELS` entries.

    `CLAWHOUSE_MODELS` is a JSON array of OpenAI-compatible models:
    `[{"id": "...", "label": "...", "model": "...", "base_url": "...", "api_key_env": "..."}]`.
    """
    compat = list(_compatible_models(env.get(MODELS_ENV)))
    has_compat_default = any(entry.is_default for entry in compat)
    db_entries = list(_databricks_models(env, is_default=not has_compat_default))
    return _mark_default(db_entries + compat)


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


def _databricks_models(
    env: Mapping[str, str], *, is_default: bool = True
) -> tuple[ModelEntry, ...]:
    endpoint = env.get("SERVING_ENDPOINT") or env.get("DATABRICKS_MODEL")
    if not endpoint:
        return ()
    return (
        ModelEntry(
            id=DEFAULT_MODEL_ID,
            label=f"Databricks · {endpoint}",
            provider="databricks",
            model=endpoint,
            is_default=is_default,
        ),
    )


def _compatible_models(raw: str | None) -> tuple[ModelEntry, ...]:
    if not raw:
        return ()
    items: list[dict[str, object]] = json.loads(raw)
    return tuple(_compatible_entry(item) for item in items)


def _compatible_entry(item: Mapping[str, object]) -> ModelEntry:
    is_default = bool(item.get("default") or item.get("is_default"))
    api_key_env_val = item.get("api_key_env")
    return ModelEntry(
        id=str(item["id"]),
        label=str(item.get("label") or item["id"]),
        provider="openai_compatible",
        model=str(item["model"]),
        base_url=str(item["base_url"]),
        api_key_env=str(api_key_env_val) if api_key_env_val else None,
        is_default=is_default,
    )


def _mark_default(entries: list[ModelEntry]) -> tuple[ModelEntry, ...]:
    if not entries or any(entry.is_default for entry in entries):
        return tuple(entries)
    return (replace(entries[0], is_default=True), *entries[1:])


def mcp_servers_from_env(env: Mapping[str, str]) -> tuple[MCPServerConfig, ...]:
    raw = env.get(MCP_SERVERS_ENV) or env.get("MCP_SERVERS")
    if not raw:
        return ()
    items: list[dict[str, object]] = json.loads(raw)
    servers = tuple(_mcp_server_entry(item) for item in items)
    seen: set[str] = set()
    for s in servers:
        if s.name in seen:
            raise DuplicateMCPServerName(f"Duplicate MCP server name: {s.name!r}")
        seen.add(s.name)
    return servers


def _mcp_server_entry(item: Mapping[str, object]) -> MCPServerConfig:
    timeout_val = _parse_timeout(item.get("timeout_seconds"))
    return MCPServerConfig(
        name=str(item["name"]),
        url=str(item["url"]),
        timeout_seconds=timeout_val,
    )


def _parse_timeout(timeout: object) -> float:
    if isinstance(timeout, int | float | str):
        try:
            val = float(timeout)
            if math.isfinite(val) and val > 0:
                return val
        except (ValueError, TypeError):
            pass
    return 30.0
