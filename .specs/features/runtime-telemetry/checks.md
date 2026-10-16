# Runtime Telemetry Checks

Profile: light
Plan: `.specs/features/runtime-telemetry/plan.md`

14 checks in 3 slices · 3 one-way doors · 0 open, of which 0 block

## Checks

Grouped by the spec's slices; numbering runs across the whole feature.

### S1 - Telemetry Settings and Setup Seam · 2 files · ~11 KB · ~3k

**C1** - `settings_from_env` parses `OTEL_EXPORTER_OTLP_ENDPOINT`, `OTEL_EXPORTER_OTLP_HEADERS`, `LOGFIRE_TOKEN`, and `CLAWHOUSE_TELEMETRY` into `Settings` (AC 1) · done
Proof: `uv run pytest tests/test_telemetry.py -k test_settings_telemetry_defaults_and_env`

**C2** - `settings_from_env` sets `telemetry_enabled=False` when `CLAWHOUSE_TELEMETRY` is `0`, `false`, or `no` (AC 2) · done
Proof: `uv run pytest tests/test_telemetry.py -k test_settings_telemetry_disabled`

**C3** - `setup_telemetry` with `telemetry_enabled=False` is a no-op and registers no exporters (AC 3) · done
Proof: `uv run pytest tests/test_telemetry.py -k test_setup_telemetry_disabled_noop`

**C4** - `setup_telemetry` configures Logfire with `send_to_logfire='if-token-present'` and token when `logfire_token` is set (AC 4) · done
Proof: `uv run pytest tests/test_telemetry.py -k test_setup_telemetry_logfire_token`

**C5** - `setup_telemetry` registers standard `OTLPSpanExporter` targeting `otel_endpoint` with headers from `otel_headers` when `otel_endpoint` is present and `logfire_token` is unset (AC 5) · done
Proof: `uv run pytest tests/test_telemetry.py -k test_setup_telemetry_otlp_endpoint`

### S2 - Turn Span & Session Attributes · 2 files · ~45 KB · ~11k

**C6** - `iter_turn` opens active span `clawhouse.turn` with attributes `clawhouse.session_id`, `clawhouse.owner_id`, and `clawhouse.run_id` (AC 6) · done
Proof: `uv run pytest tests/test_telemetry.py -k test_turn_span_lifecycle_ok`

**C7** - Active agent selection records attribute `clawhouse.agent_id` on the active turn span (AC 7) · done
Proof: `uv run pytest tests/test_telemetry.py -k test_turn_span_records_agent_id`

**C8** - Successful turn completion records attribute `clawhouse.turn_status="ok"` on `clawhouse.turn` span (AC 8) · done
Proof: `uv run pytest tests/test_telemetry.py -k test_turn_span_lifecycle_ok`

**C9** - Turn failure records attribute `clawhouse.turn_status="error"` and records exception on `clawhouse.turn` span (AC 9) · done
Proof: `uv run pytest tests/test_telemetry.py -k test_turn_span_lifecycle_error`

**C10** - Turn pausing for human approval records attribute `clawhouse.turn_status="pending_approval"` on `clawhouse.turn` span (AC 10) · done
Proof: `uv run pytest tests/test_telemetry.py -k test_turn_span_lifecycle_pending_approval`

### S3 - Pydantic AI Native Model and Tool Instrumentation · 2 files · ~45 KB · ~11k

**C11** - Agent run enables Pydantic AI OpenTelemetry GenAI instrumentation when `telemetry_enabled=True` (AC 11) · done
Proof: `uv run pytest tests/test_telemetry.py -k test_agent_telemetry_genai_spans`

**C12** - Model execution emits a GenAI span containing input and output token counts (AC 12) · done
Proof: `uv run pytest tests/test_telemetry.py -k test_agent_telemetry_genai_spans`

**C13** - Tool execution emits a child span for the tool containing arguments and duration (AC 13) · done
Proof: `uv run pytest tests/test_telemetry.py -k test_agent_telemetry_tool_spans`

**C14** - App lifespan in `create_app` invokes `setup_telemetry` on startup (AC 3, AC 4) · done
Proof: `uv run pytest tests/test_telemetry.py -k test_app_lifespan_telemetry_setup`

## Coverage

| Set (size) | Member -> proof | Unproven |
| --- | --- | --- |
| `CLAWHOUSE_TELEMETRY` parse values (4) | `true` C1 · `0` C2 · `false` C2 · `no` C2 | - |
| Telemetry export targets (3) | `disabled` C3 · `logfire` C4 · `otlp` C5 | - |
| `clawhouse.turn` terminal status values (3) | `ok` C8 · `error` C9 · `pending_approval` C10 | - |
| GenAI span types (2) | `chat` C12 · `tool` C13 | - |
| App startup assemblies (2) | `app-lifespan` C14 · `test-harness` C6 | - |

- Claims naming a status code, route or response shape: none - internal telemetry spans and environment configuration only
- No other check claims more than the single case its proof exercises

## Swept

Where each unwritten requirement landed. All nine, one line each, every time.

- validation: C1, C2
- failure modes: C9
- idempotency: C3, C4
- authorization: existing - identity token is scrubbed and not leaked to span attributes
- concurrency: C6
- data lifecycle: n/a - spans are ephemeral and exported directly to external collectors or in-memory buffers
- dependency failure: C5
- state transitions: C8, C9, C10
- observability: C6, C7, C8, C9, C10, C11, C12, C13

## Handoff

Total size: 5 files · ~103 KB · ~26k tokens.
Under the 150k budget — one builder, no ask.
Mechanism: one builder.

- **Boundary:** C1-C14 closed
- **Settled mid-build:** Attached processor to existing provider in test fixture to prevent multiple-set warnings; used `(s.attributes or {})` in assertions for strict pyright safety.
- **Abandoned:** none
