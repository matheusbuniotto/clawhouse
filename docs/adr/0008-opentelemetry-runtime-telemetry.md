# 0008 - OpenTelemetry Runtime Telemetry with Logfire / OTLP Fallback

**Status**: Accepted

## Context

Clawhouse executes agent turns (LLM calls, tool execution, MCP calls) that require observability in production Databricks App deployments. Operators and developers need visibility into token consumption, latency, time-to-first-chunk, tool execution duration, and error traces.

Furthermore, Databricks enterprise governance requires standard GenAI observability.

## Decision

Implement runtime telemetry using:
1. Native Pydantic AI instrumentation (`pydantic_ai.capabilities.instrumentation.Instrumentation`) and `Agent.instrument_all()`.
2. First-class Logfire configuration with standard OpenTelemetry fallback (`TracerProvider` and `OTLPSpanExporter`).
3. Root `turn_span` context manager enriching traces with `session_id`, `owner_id`, `run_id`, and active agent metadata.
4. Non-intrusive environment-driven configuration (`Settings` fields: `telemetry_enabled`, `otel_endpoint`, `otel_headers`, `logfire_token`, `mlflow_enabled`).

## Consequences

- Full span hierarchy (turn -> model -> tool) emitted to standard OpenTelemetry collectors or Logfire.
- Zero heavy proprietary dependencies added for tracing.
- Test environments can use in-memory span exporters without network calls.

---

*Recorded on 2026-10-16*
