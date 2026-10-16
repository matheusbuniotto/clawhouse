# Runtime Telemetry and OpenTelemetry Observability

## Problem

Today, Clawhouse executes agent turns (LLM calls, tool execution, MCP calls) with zero runtime observability or telemetry. When an agent turn runs on a Databricks App in production, operations and developers have no visibility into token consumption (input/output tokens), model latency, time-to-first-chunk, tool execution duration, or error traces.

Furthermore, Databricks enterprise governance requires OpenTelemetry standard GenAI auditability. Without runtime telemetry, performance degradation during agent refactoring (such as upcoming streaming and token injection slices) cannot be detected or measured.

When this ships, operators and developers can observe end-to-end turn traces with full span hierarchy in Logfire, Langwatch, or any OTLP collector: root turn spans with session metadata, model spans with token usage, and tool spans with execution duration and arguments. In test environments, in-memory exporters verify exact span telemetry without external network calls.

## Flow

This feature reuses Pydantic AI's native `Instrumentation` capability (`pydantic_ai.capabilities.instrumentation.Instrumentation`) and `Agent.instrument_all()`, OpenTelemetry SDK, and Logfire already installed in the environment.

1. `clawhouse.api.app` (exists) - during lifespan startup, initializes telemetry via `clawhouse.telemetry` (door 1) using `Settings` (exists)
2. `clawhouse.agent.turn` (exists) - `iter_turn` wraps turn execution in `turn_span` context manager from `clawhouse.telemetry` (door 1) with session, owner, run, and agent metadata
3. `clawhouse.agent.core` (exists) - `clawhouse_agent` enables native OpenTelemetry GenAI instrumentation
4. out: OpenTelemetry spans emitted to the configured TracerProvider / exporter (Logfire, OTLP collector, or in-memory test exporter), and turn execution returns `TurnResult` to `clawhouse.api.app` (exists)

## Impact

| Front | What changes |
| --- | --- |
| domain | new module: `clawhouse.telemetry` - setup_telemetry, turn_span context manager, and OTel span enrichment |
| domain | existing config: `Settings` adds `otel_endpoint`, `otel_headers`, `logfire_token`, `telemetry_enabled` fields parsed from env |
| stored data | nothing to migrate - runtime spans are exported directly via OpenTelemetry exporters, no Lakebase schema changes |

## Relations

None - no stored-data shape change

## Surface

None - nothing consumed outside

## Landing

| One-way door | Literal shape | Alternative rejected |
| --- | --- | --- |
| Telemetry provider interface | `logfire.configure(send_to_logfire='if-token-present', token=settings.logfire_token)` with fallback to standard `TracerProvider` and `OTLPSpanExporter` | Dedicated MLflow tracing package (`mlflow`); rejected because it adds ~150MB heavy dependencies (numpy/pandas/scipy), lacks native Pydantic AI instrumentation, and locks telemetry to MLflow UI rather than standard OTel |
| Span enrichment mechanism | `turn_span(session_id: str, owner_id: str, agent_id: str, run_id: str)` context manager wrapping `iter_turn` emitting span `clawhouse.turn` with attributes `clawhouse.session_id`, `clawhouse.owner_id`, `clawhouse.agent_id`, `clawhouse.run_id`, `clawhouse.turn_status` | Custom ASGI middleware span; rejected because ASGI middleware does not have visibility into domain agent selection, user session ownership, or turn completion status |
| Native Agent instrumentation | `Agent.instrument_all(True)` or `Instrumentation()` capability inside `clawhouse.telemetry.setup_telemetry` | Custom wrapper around each tool function and model call; rejected because Pydantic AI natively implements OpenTelemetry GenAI semantic conventions out of the box |

- Nothing else in this change is hard to reverse

## Criteria

Grouped by slice - one observable outcome each, never a layer. Numbering runs across the whole plan.

### S1: Telemetry Settings and Setup Seam (P1)

Configuration parsing for OTel/Logfire and lifespan setup hook.

**Acceptance Criteria**

1. WHEN `settings_from_env` parses an environment mapping THEN the system SHALL populate `Settings.otel_endpoint` from `OTEL_EXPORTER_OTLP_ENDPOINT`, `Settings.otel_headers` from `OTEL_EXPORTER_OTLP_HEADERS`, `Settings.logfire_token` from `LOGFIRE_TOKEN`, and `Settings.telemetry_enabled` from `CLAWHOUSE_TELEMETRY` (defaulting to True when unset).
2. IF `CLAWHOUSE_TELEMETRY` is set to `0`, `false`, or `no` (case-insensitive) THEN the system SHALL set `Settings.telemetry_enabled` to False.
3. WHEN `setup_telemetry` is called with `telemetry_enabled=False` THEN the system SHALL return without registering any remote exporter or instrumenting agents.
4. WHEN `setup_telemetry` is called with `logfire_token` set THEN the system SHALL configure Logfire with `send_to_logfire='if-token-present'` and the provided token.
5. WHERE `otel_endpoint` is set and `logfire_token` is unset, WHEN `setup_telemetry` is called THEN the system SHALL register an `OTLPSpanExporter` targeting `otel_endpoint` with headers from `otel_headers`.

**Independent test:** Invoke `settings_from_env` with various env mappings, verify `Settings` fields, and assert `setup_telemetry` configures the expected exporter without errors.

### S2: Turn Span & Session Attributes (P1)

Turn-level root span tracking session, owner, run, agent, and terminal status.

**Acceptance Criteria**

6. WHEN a turn begins via `iter_turn` THEN the system SHALL open an active OpenTelemetry span named `clawhouse.turn` with attributes `clawhouse.session_id`, `clawhouse.owner_id`, and `clawhouse.run_id`.
7. WHEN the active agent is identified during turn execution THEN the system SHALL record attribute `clawhouse.agent_id` on the active `clawhouse.turn` span.
8. WHEN `iter_turn` completes with status `ok` THEN the system SHALL record attribute `clawhouse.turn_status="ok"` and end the span.
9. IF `iter_turn` raises an exception or finishes with status `error` THEN the system SHALL record attribute `clawhouse.turn_status="error"`, record the exception on the span, and end the span.
10. IF `iter_turn` pauses for human approval with status `pending_approval` THEN the system SHALL record attribute `clawhouse.turn_status="pending_approval"` and end the span.

**Independent test:** Run a test turn with an `InMemorySpanExporter`, inspect exported spans, and assert the presence of `clawhouse.turn` with expected attribute keys and values.

### S3: Pydantic AI Native Model and Tool Instrumentation (P1)

Pydantic AI native GenAI spans for model calls and tool executions.

**Acceptance Criteria**

11. The system SHALL enable Pydantic AI OpenTelemetry GenAI instrumentation across all agent runs when `telemetry_enabled=True`.
12. WHEN an agent executes a model invocation THEN the system SHALL emit a child span conforming to GenAI semantic conventions containing `gen_ai.client.token.usage` input and output counts.
13. WHEN an agent invokes a tool THEN the system SHALL emit a child span for the tool recording tool arguments and execution duration.

**Independent test:** Execute `run_turn` with a model call and tool execution using `InMemorySpanExporter`, asserting child spans for `chat` and `tool:` appear under the turn root span.

## Out of scope

Product capabilities only. Process and harness rules live in AGENTS.md or as Observable `n/a`.

| Excluded | Why |
| --- | --- |
| MLflow SDK native integration | Excluded due to ~150MB heavy dependency footprint and lack of native Pydantic AI support; standard OTLP export can ingest into Databricks once OTel bridge is available |
| Prometheus pull metric scraper | Clawhouse runs as a Databricks App behind proxy where pull endpoints cannot be scraped; push-based OTel and Logfire are supported |
| Turn transcript payload export to external OTel logs | Transcripts are already securely persisted in Lakebase with redaction; OTel receives metadata, token metrics, and tool execution spans |

## Assumptions

Defaults that are not already a numbered criterion. Drop a row once it is.

| Assumption | Chosen default | Rationale | Confirmed? |
| --- | --- | --- | --- |
| Default telemetry status when unconfigured | Enabled with local TracerProvider | Emits spans locally without failing if no token or endpoint is set | y |
| Test suite telemetry isolation | Tests use InMemorySpanExporter or disable remote network export | Prevents unit and integration tests from leaking traces or making external network calls | y |

**Open questions:** none - all resolved or logged above.

## Observable

Worksheet, not the review. `n/a` needs its reason. One row may group the same decision across several routes.

| Surface | Decision | Landing |
| --- | --- | --- |
| CLI / Env `CLAWHOUSE_TELEMETRY` | boolean parsing and defaults | AC 1, AC 2 |
| CLI / Env `OTEL_EXPORTER_OTLP_ENDPOINT` | endpoint url configuration | AC 1, AC 5 |
| CLI / Env `LOGFIRE_TOKEN` | token configuration | AC 1, AC 4 |
| Span `clawhouse.turn` | attributes and status codes | AC 6, AC 7, AC 8, AC 9, AC 10 |
| GenAI spans | token usage and tool call spans | AC 11, AC 12, AC 13 |
| all new `/api/*` routes | versioning, rate limits | n/a - no new HTTP routes added |

## Sources

- `clawhouse-runtime-telemetry-design.md` - TLC Discover analysis confirming Shape 1 (OTel/Logfire/OTLP) and disqualifying Shape 2 (MLflow)
- `docs/adr/0003-pydantic-ai.md` - ADR-0003 establishing Pydantic AI as agent runtime
