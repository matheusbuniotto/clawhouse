# Clawhouse 🦀

> Databricks-native agent runtime and chat app built on **Pydantic AI**, **Lakebase Postgres**, and **Model Serving**.

---

## Try it in 60 seconds (no keys, no Databricks)

```bash
git clone https://github.com/matheusbuniotto/clawhouse.git && cd clawhouse
uv sync
make demo
```

Open **`http://localhost:8000/chat`** and send any message. Demo mode (`CLAWHOUSE_DEMO=1`) swaps the model for a scripted one, so you see the full turn loop with no account: streamed replies, a live progress card, a question card, and an approval card before a tool with side effects runs. Sessions live in memory and disappear when you stop the server.

## Run locally with a real model

```bash
uv sync
CLAWHOUSE_DEV_USER=you@example.com \
CLAWHOUSE_STORE=memory \
uv run uvicorn clawhouse.api.app:app --reload
```

Open **`http://localhost:8000/chat`**.

> Provide `DATABRICKS_HOST`, `DATABRICKS_TOKEN`, and `SERVING_ENDPOINT` for Databricks Model Serving, or `CLAWHOUSE_MODELS` for any OpenAI-compatible endpoint. If no model is connected, the chat tells you how to connect one (or to run `make demo`).

---

## Architecture

```text
src/clawhouse/
├── agent/         # Turn execution, @agent roster, command dispatch, prompt & history
├── capabilities/  # Databricks (UC/SQL/Jobs), Sheets, MCP, skills, ask_user & progress
├── api/           # FastAPI routes, SSE turn streaming, unified /api/jobs, SSO identity
├── store/         # Lakebase Postgres (OAuth) & in-memory session/transcript/schedule store
└── settings.py    # Environment configuration
```

---

## Core Capabilities

- **Per-Message `@agent` Routing**: Mention `@agent` in any message to route the turn to that agent's persona, workspace (`claw/agents/<name>/`), and skills while sharing conversation history.
- **Interactive Turn Cards**:
  - **`ask_user`**: Pauses the run and renders an inline question card with option buttons (headless scheduled runs automatically select `default`).
  - **`report_progress`**: Streams and updates a single in-place step checklist per `task_id`.
  - **Tool Approvals**: Sensitive tools (`jobs_*`, `sheets_*`, `delivery_*`, and `CLAWHOUSE_SENSITIVE_TOOLS`) pause the run for inline `[Approve]` / `[Deny]` confirmation or resolution in `/approvals`.
- **Unified Jobs (`/jobs`)**: Lists in-app cron schedules and Databricks Lakeflow Jobs visible to the caller (via OBO token or workspace ACL fallback), with **Run now**, schedule deletion, and links to run transcripts.
- **Composer Commands & Context**:
  - Slash commands: `/compact`, `/clear`, `/schedule <cron> | <prompt>`, `/skill:<name>`.
  - Context mentions: `@catalog.schema.table` (Unity Catalog schema), `@file:<path>`, `@agent` autocomplete.
  - Context-window ring indicator tracking sent input tokens.
- **Databricks & MCP Tools**: Unity Catalog discovery, read-only DBSQL queries, Lakeflow Jobs (`sql`, `agentic` via `ai_query`, `python`), Google Sheets (`system.ai.google_drive`), Slack/webhook delivery, and external HTTPS MCP servers with token scrubbing.

---

## Configuration

| Variable | Purpose |
| :--- | :--- |
| `SERVING_ENDPOINT` | Default Databricks Model Serving endpoint name |
| `LAKEBASE_ENDPOINT` | Lakebase Autoscaling resource key (omit or set `CLAWHOUSE_STORE=memory` locally) |
| `DATABRICKS_WAREHOUSE_ID` | SQL Warehouse ID for DBSQL queries and SQL/agentic job tasks |
| `CLAWHOUSE_MODELS` | JSON list of extra OpenAI-compatible model entries (`id`, `label`, `model`, `base_url`, `api_key_env`, `default`) |
| `CLAWHOUSE_MCP_SERVERS` | JSON list of HTTPS MCP servers (`name`, `url`, `timeout_seconds`) |
| `CLAWHOUSE_SENSITIVE_TOOLS` | Comma-separated list or JSON array of tool names requiring interactive approval |
| `CLAWHOUSE_DEV_USER` | Local dev identity fallback when `X-Forwarded-Email` is absent |
| `CLAWHOUSE_DEMO` | `1` runs every turn on a scripted, keyless demo model (used by `make demo`) |

Example `CLAWHOUSE_MODELS`:

```bash
export CLAWHOUSE_MODELS='[
  {
    "id": "openrouter-model",
    "label": "My model (OpenRouter)",
    "model": "<provider>/<model>",
    "base_url": "https://openrouter.ai/api/v1",
    "api_key_env": "OPENROUTER_API_KEY",
    "default": true
  }
]'
export OPENROUTER_API_KEY=sk-or-...
```

---

## Deploy

Direct sync and deploy to Databricks Apps:

```bash
make deploy
```

`make sync` uploads the source to the deployed app's current source path. For a first deploy it uses `/Workspace/Users/$DATABRICKS_USER/clawhouse`; `DATABRICKS_USER` defaults to the Databricks CLI's signed-in user. Set `WORKSPACE_PATH` to pick any other folder:

```bash
DATABRICKS_USER=you@example.com make deploy
# or
WORKSPACE_PATH=/Workspace/Users/you@example.com/clawhouse make deploy
```

Or deploy via Databricks Asset Bundles (DAB):

```bash
export BUNDLE_VAR_sql_warehouse_id=<warehouse-id>          # required
# optional: extra OpenAI-compatible models (reads OPENROUTER_API_KEY from the app secret)
export BUNDLE_VAR_extra_models='[{"id":"openrouter-model","label":"My model (OpenRouter)","model":"<provider>/<model>","base_url":"https://openrouter.ai/api/v1","api_key_env":"OPENROUTER_API_KEY","default":true}]'
databricks bundle deploy --profile <PROFILE>
```

Bundle variables (`databricks.yml`): `serving_endpoint`, `postgres_branch`, `postgres_database`, `provider_secret_scope`, `provider_secret_key`, `sql_warehouse_id` (required), `extra_models` (default `[]`), and `mlflow_experiment` (default `/Users/<you>/clawhouse-traces`). Set any of them with `--var name=value` or `BUNDLE_VAR_<name>`.

---

## Quality Gates

```bash
make check           # Runs prek (ruff, complexipy, pyright), pytest, tsc, build check, and vitest
```

Individual checks:

```bash
uv run ruff check --fix . && uv run ruff format .
uv run complexipy src --max-complexity-allowed 15
uv run pyright
uv run vulture src --min-confidence 80
npx jscpd@5 src --threshold 3 --min-lines 5 --min-tokens 50
uv run pytest
npm test
```
