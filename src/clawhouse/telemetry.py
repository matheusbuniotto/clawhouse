"""OpenTelemetry runtime telemetry and Logfire integration for Clawhouse."""

from __future__ import annotations

import logging
import os
from collections.abc import Iterator
from contextlib import contextmanager
from typing import TYPE_CHECKING

import logfire
import mlflow
from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.trace import StatusCode
from pydantic_ai import Agent

if TYPE_CHECKING:
    from clawhouse.settings import Settings

logger = logging.getLogger("clawhouse.telemetry")

TRACER_NAME = "clawhouse"


def parse_otlp_headers(raw: str | None) -> dict[str, str] | None:
    """Parse comma-separated KEY=VALUE pairs into a header dictionary."""
    if not raw:
        return None
    headers: dict[str, str] = {}
    for item in raw.split(","):
        part = item.strip()
        if "=" in part:
            k, v = part.split("=", 1)
            headers[k.strip()] = v.strip()
    return headers or None


def setup_mlflow_tracing(settings: Settings) -> None:
    """Initialize MLflow Tracing with native Pydantic AI autologging."""
    if not settings.mlflow_enabled:
        return
    try:
        tracking_uri = os.environ.get("MLFLOW_TRACKING_URI")
        if not tracking_uri:
            if (
                settings.workspace_host
                or os.environ.get("DATABRICKS_HOST")
                or (settings.mlflow_experiment and settings.mlflow_experiment.startswith("/"))
            ):
                mlflow.set_tracking_uri("databricks")
        else:
            mlflow.set_tracking_uri(tracking_uri)

        if settings.mlflow_experiment:
            mlflow.set_experiment(settings.mlflow_experiment)
        pydantic_ai_mod = getattr(mlflow, "pydantic_ai", None)
        if pydantic_ai_mod is not None and hasattr(pydantic_ai_mod, "autolog"):
            pydantic_ai_mod.autolog()
            logger.info("MLflow Pydantic AI autologging enabled")
    except Exception as exc:  # noqa: BLE001
        logger.warning("Failed to initialize MLflow tracing: %s", exc)


def flush_telemetry() -> None:
    """Flush pending OpenTelemetry spans and MLflow traces."""
    try:
        provider = trace.get_tracer_provider()
        force_flush = getattr(provider, "force_flush", None)
        if callable(force_flush):
            force_flush()
    except Exception as exc:  # noqa: BLE001
        logger.debug("Failed to flush OpenTelemetry provider: %s", exc)

    try:
        flush_fn = getattr(mlflow, "flush_trace_async_logging", None)
        if callable(flush_fn):
            flush_fn()
    except Exception as exc:  # noqa: BLE001
        logger.debug("Failed to flush MLflow traces: %s", exc)


def setup_telemetry(settings: Settings) -> None:
    """Initialize OpenTelemetry runtime telemetry based on application settings."""
    if not settings.telemetry_enabled:
        logger.debug("telemetry disabled by configuration")
        return

    setup_mlflow_tracing(settings)

    if settings.logfire_token:
        logfire.configure(
            send_to_logfire="if-token-present",
            token=settings.logfire_token,
            service_name="clawhouse",
        )
    elif settings.otel_endpoint:
        headers = parse_otlp_headers(settings.otel_headers)
        exporter = OTLPSpanExporter(endpoint=settings.otel_endpoint, headers=headers)
        provider = trace.get_tracer_provider()
        if not isinstance(provider, TracerProvider):
            provider = TracerProvider()
            trace.set_tracer_provider(provider)
        provider.add_span_processor(BatchSpanProcessor(exporter))

    Agent.instrument_all(True)


@contextmanager
def turn_span(
    session_id: str,
    owner_id: str,
    run_id: str,
    agent_id: str | None = None,
) -> Iterator[trace.Span]:
    """Context manager for the root turn execution span."""
    tracer = trace.get_tracer(TRACER_NAME)
    with tracer.start_as_current_span("clawhouse.turn") as span:
        span.set_attribute("clawhouse.session_id", session_id)
        span.set_attribute("clawhouse.owner_id", owner_id)
        span.set_attribute("clawhouse.run_id", run_id)
        if agent_id:
            span.set_attribute("clawhouse.agent_id", agent_id)
        yield span


def record_turn_agent(agent_id: str) -> None:
    """Record active agent identifier on the current span."""
    span = trace.get_current_span()
    if span.is_recording():
        span.set_attribute("clawhouse.agent_id", agent_id)


def record_turn_status(status: str, error: Exception | None = None) -> None:
    """Record terminal turn status and optional exception on the current span."""
    span = trace.get_current_span()
    if not span.is_recording():
        return
    span.set_attribute("clawhouse.turn_status", status)
    if error is not None:
        span.record_exception(error)
        span.set_status(StatusCode.ERROR, str(error))
    elif status == "error":
        span.set_status(StatusCode.ERROR, "turn error")
