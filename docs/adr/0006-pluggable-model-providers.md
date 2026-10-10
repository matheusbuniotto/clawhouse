# ADR-0006: Pluggable model providers behind a chat picker

Date: 2026-10-10
Status: accepted
Related: [ADR-0003 Pydantic AI](0003-pydantic-ai.md), [ADR-0004 UI v1 is 5 screens](0004-ui-v1-5-screens.md)

## Context

ADR-0003 wires exactly one model: a Databricks Model Serving endpoint called with the forwarded per-request user token. Users want to try OpenRouter or any other OpenAI-compatible endpoint (a gateway, a self-hosted server) without redeploying, and to choose per conversation. ADR-0004 defers full "model setup" past v1, so v1 needs a read-only picker, not an editor.

## Decision

Keep Databricks as the default provider and add a small, env-driven catalog of selectable models.

- **One catalog, resolved from the environment.** `SERVING_ENDPOINT` + `DATABRICKS_HOST` produce the default `databricks` entry. `CRABRIKS_MODELS` is a JSON array of OpenAI-compatible entries (`id`, `label`, `model`, `base_url`, `api_key_env`). Databricks wins the default when present; otherwise the first compatible entry is the default.
- **Secrets stay out of the catalog.** Each entry names the env var that holds its key (`api_key_env`), so the catalog itself is safe to put in `app.yaml` and the key is a platform secret resource.
- **One picker surface.** `GET /api/models` returns `id`, `label`, and `default` per entry; the chat page renders them in a `<select>` and persists the choice per session.
- **Per-turn selection.** A turn carries an optional `model` id. Omitted means the default; an unknown id is `422`. `model_for(caller, model_id)` stays the injection seam, and `databricks_chat_model` / `openai_compatible_chat_model` build the two provider shapes.

## Consequences

- The Databricks per-request user-token path is unchanged. Compatible providers use a platform-level key, so they are not per-user; that is acceptable for v1.
- Model profile quirks on compatible endpoints (tool calling, structured output) may still need tuning, as ADR-0003's open risks note.
- The picker is display only. Full model setup — adding endpoints, editing the catalog in-app — remains post-v1 per ADR-0004.
- `Settings.models` is the single source of truth for both the picker and turn resolution, so the UI and the agent never disagree about what is selectable.
