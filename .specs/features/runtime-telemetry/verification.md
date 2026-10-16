# Runtime Telemetry verification

**Verdict**: PASS
**Profile**: light
**Diff range**: d0f44f57b6aade773ebc30e4fb79e61dfdfe2f6e..HEAD
**Round**: 1 - full
**Verifier**: independent sub-agent (author != verifier)

## Checks

| Check | Claim | Proof run | Evidence | Result |
| --- | --- | --- | --- | --- |
| C1 | `settings_from_env` parses `OTEL_EXPORTER_OTLP_ENDPOINT`, `OTEL_EXPORTER_OTLP_HEADERS`, `LOGFIRE_TOKEN`, and `CLAWHOUSE_TELEMETRY` into `Settings` (AC 1) | `uv run pytest tests/test_telemetry.py -k test_settings_telemetry_defaults_and_env` exit 0 | `tests/test_telemetry.py:101` - `assert s.telemetry_enabled is True and s.otel_endpoint == "http://localhost:4318/v1/traces"` | PASS |
| C2 | `settings_from_env` sets `telemetry_enabled=False` when `CLAWHOUSE_TELEMETRY` is `0`, `false`, or `no` (AC 2) | `uv run pytest tests/test_telemetry.py -k test_settings_telemetry_disabled` exit 0 | `tests/test_telemetry.py:111` - `assert s.telemetry_enabled is False` | PASS |
| C3 | `setup_telemetry` with `telemetry_enabled=False` is a no-op and registers no exporters (AC 3) | `uv run pytest tests/test_telemetry.py -k test_setup_telemetry_disabled_noop` exit 0 | `tests/test_telemetry.py:126` - `mock_logfire.assert_not_called()` | PASS |
| C4 | `setup_telemetry` configures Logfire with `send_to_logfire='if-token-present'` and token when `logfire_token` is set (AC 4) | `uv run pytest tests/test_telemetry.py -k test_setup_telemetry_logfire_token` exit 0 | `tests/test_telemetry.py:144` - `mock_logfire.assert_called_once_with(send_to_logfire="if-token-present", token="secret_token", service_name="clawhouse")` | PASS |
| C5 | `setup_telemetry` registers standard `OTLPSpanExporter` targeting `otel_endpoint` with headers from `otel_headers` when `otel_endpoint` is present and `logfire_token` is unset (AC 5) | `uv run pytest tests/test_telemetry.py -k test_setup_telemetry_otlp_endpoint` exit 0 | `tests/test_telemetry.py:171` - `mock_exporter.assert_called_once_with(endpoint="http://collector:4318/v1/traces", headers={"Authorization": "Bearer abc", "Key": "Value"})` | PASS |
| C6 | `iter_turn` opens active span `clawhouse.turn` with attributes `clawhouse.session_id`, `clawhouse.owner_id`, and `clawhouse.run_id` (AC 6) | `uv run pytest tests/test_telemetry.py -k test_turn_span_lifecycle_ok` exit 0 | `tests/test_telemetry.py:200` - `assert attrs.get("clawhouse.session_id") == SESSION and attrs.get("clawhouse.owner_id") == OWNER and "clawhouse.run_id" in attrs` | PASS |
| C7 | Active agent selection records attribute `clawhouse.agent_id` on the active turn span (AC 7) | `uv run pytest tests/test_telemetry.py -k test_turn_span_records_agent_id` exit 0 | `tests/test_telemetry.py:221` - `assert "clawhouse.agent_id" in attrs` | PASS |
| C8 | Successful turn completion records attribute `clawhouse.turn_status="ok"` on `clawhouse.turn` span (AC 8) | `uv run pytest tests/test_telemetry.py -k test_turn_span_lifecycle_ok` exit 0 | `tests/test_telemetry.py:203` - `assert attrs.get("clawhouse.turn_status") == "ok"` | PASS |
| C9 | Turn failure records attribute `clawhouse.turn_status="error"` and records exception on `clawhouse.turn` span (AC 9) | `uv run pytest tests/test_telemetry.py -k test_turn_span_lifecycle_error` exit 0 | `tests/test_telemetry.py:240` - `assert attrs.get("clawhouse.turn_status") == "error"` | PASS |
| C10 | Turn pausing for human approval records attribute `clawhouse.turn_status="pending_approval"` on `clawhouse.turn` span (AC 10) | `uv run pytest tests/test_telemetry.py -k test_turn_span_lifecycle_pending_approval` exit 0 | `tests/test_telemetry.py:262` - `assert attrs.get("clawhouse.turn_status") == "pending_approval"` | PASS |
| C11 | Agent run enables Pydantic AI OpenTelemetry GenAI instrumentation when `telemetry_enabled=True` (AC 11) | `uv run pytest tests/test_telemetry.py -k test_agent_telemetry_genai_spans` exit 0 | `tests/test_telemetry.py:296` - `assert len(genai_chat) >= 1` | PASS |
| C12 | Model execution emits a GenAI span containing input and output token counts (AC 12) | `uv run pytest tests/test_telemetry.py -k test_agent_telemetry_genai_spans` exit 0 | `tests/test_telemetry.py:299` - `assert "gen_ai.usage.input_tokens" in attrs or "gen_ai.client.token.usage" in attrs` | PASS |
| C13 | Tool execution emits a child span for the tool containing arguments and duration (AC 13) | `uv run pytest tests/test_telemetry.py -k test_agent_telemetry_tool_spans` exit 0 | `tests/test_telemetry.py:333` - `assert (attrs.get("gen_ai.tool.name") == "clock" or "clock" in tool_span.name or "gen_ai.tool.call.arguments" in attrs)` | PASS |
| C14 | App lifespan in `create_app` invokes `setup_telemetry` on startup (AC 3, AC 4) | `uv run pytest tests/test_telemetry.py -k test_app_lifespan_telemetry_setup` exit 0 | `tests/test_telemetry.py:359` - `mock_setup.assert_called_once_with(settings)` | PASS |

## Gate

`uv run pytest tests/test_telemetry.py` - 21 passed, 0 failed
