# Crabriks

## Development Setup

This project uses [uv](https://github.com/astral-sh/uv) and [prek](https://github.com/j178/prek) (Rust-powered Git hook manager).

### 1. Environment Setup

```bash
# Pin and install Python 3.11 with all dev dependencies
uv sync
```

### 2. Git Hooks & Quality Gate (`prek`)

Git hook shims are installed using `prek`:

```bash
# Install git hooks into .git/hooks/pre-commit
prek install

# Run checks against staged files (runs automatically on git commit)
prek run

# Run checks on all files
prek run -a
```

> **Fallback:** If `prek` is not installed globally, you can also run `uv run pre-commit run -a`.

### 3. Manual Checks

```bash
# Fast lint & format auto-fix
uv run ruff check --fix .
uv run ruff format .

# Cognitive complexity gate
uv run complexipy src --max-complexity-allowed 15

# Type check
uv run pyright
```

### 4. Run the chat page

```bash
CRABRIKS_DEV_USER=you@example.com CRABRIKS_STORE=memory \
  uv run uvicorn crabriks.app:app --reload
```

The page is at <http://localhost:8000/chat>. A turn needs a Databricks user token and a serving endpoint. Forward the token as `X-Forwarded-Access-Token`, or set `DATABRICKS_TOKEN` when the caller is `CRABRIKS_DEV_USER`. Also set `SERVING_ENDPOINT` and `DATABRICKS_HOST`. Without them the page loads, and a turn returns 401 or 503.

On Databricks Apps, `app.yaml` names the serving endpoint and the Lakebase Autoscaling endpoint. The platform injects `PGHOST`, `PGUSER`, `PGDATABASE`, `PGPORT`, and `PGSSLMODE`. The app mints a short-lived database password from `LAKEBASE_ENDPOINT`. Create the app with user-authorization scope `model-serving`, or the forwarded user token cannot call the endpoint. Do not set `CRABRIKS_DEV_USER` or `DATABRICKS_TOKEN` on the deployed app.

### Model providers

The chat picker lists every configured model. Databricks Model Serving is the default when `SERVING_ENDPOINT` and `DATABRICKS_HOST` are set. Add any OpenAI-compatible provider (OpenRouter, a gateway, a self-hosted server) with `CRABRIKS_MODELS`, a JSON array whose `api_key_env` names where the secret is read from — the catalog never holds the key itself:

```bash
CRABRIKS_MODELS='[
  {
    "id": "openrouter-llama-3.3-70b",
    "label": "Llama 3.3 70B · OpenRouter",
    "model": "meta-llama/llama-3.3-70b-instruct",
    "base_url": "https://openrouter.ai/api/v1",
    "api_key_env": "OPENROUTER_API_KEY"
  }
]'
OPENROUTER_API_KEY=sk-or-...
```

A turn carries the picked model id (`{"message": "...", "model": "..."}`); an unknown id is rejected with 422, and omitting it uses the default. The picker is display only — Databricks remains the only provider that uses the per-request user token.

### Deploy to another workspace

`databricks.yml` is a bundle that creates the app and its three resources, so another workspace (or a Marketplace install) does not have to build them by hand:

```bash
databricks bundle deploy --profile <PROFILE> \
  --var serving_endpoint=databricks-meta-llama-3-3-70b-instruct \
  --var postgres_branch=<branch> \
  --var postgres_database=<database> \
  --var provider_secret_scope=<scope> \
  --var provider_secret_key=<key>
```

The bundle attaches the serving endpoint, the Lakebase database, and the provider secret, and mirrors `app.yaml`. To share the app with just Databricks and no extra provider, drop the `OPENROUTER_API_KEY` and `CRABRIKS_MODELS` env entries and the `openrouter-api-key` resource from both files. If the app already exists, bind it first (`databricks bundle deployment bind`) or deploy by name (`databricks apps deploy crabriks`) to use the API flow.
