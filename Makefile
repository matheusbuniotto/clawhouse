.PHONY: all help check lint format test frontend-install frontend-check sync deploy logs status demo

APP_NAME ?= clawhouse
DEMO_PORT ?= 8000
# Where `make sync` uploads the app source. Resolution order:
#   1. WORKSPACE_PATH, if you set it
#   2. the deployed app's current source path (`databricks apps get`)
#   3. /Workspace/Users/$(DATABRICKS_USER)/$(APP_NAME), where DATABRICKS_USER
#      defaults to the CLI's signed-in user (`databricks current-user me`)
WORKSPACE_PATH ?= $(shell databricks apps get $(APP_NAME) -o json 2>/dev/null | jq -r '.default_source_code_path // empty' 2>/dev/null)
ifeq ($(strip $(WORKSPACE_PATH)),)
DATABRICKS_USER ?= $(shell databricks current-user me -o json 2>/dev/null | jq -r '.userName // empty' 2>/dev/null)
WORKSPACE_PATH = /Workspace/Users/$(DATABRICKS_USER)/$(APP_NAME)
endif

# Default target runs the quality checks
all: check

help:
	@echo "Clawhouse Management Makefile"
	@echo ""
	@echo "Quality targets:"
	@echo "  make check      - Run all prek quality gates, pytest, and the frontend checks"
	@echo "  make lint       - Run ruff, complexipy, pyright"
	@echo "  make format     - Run ruff fix and format"
	@echo "  make test       - Run test suite with uv run pytest"
	@echo "  make frontend-install - npm ci for the frontend toolchain"
	@echo "  make frontend-check   - Type-check (tsc) and run component tests (vitest)"
	@echo ""
	@echo "Try it:"
	@echo "  make demo       - Run the chat with a scripted model: no keys, no Databricks (http://localhost:$(DEMO_PORT)/chat)"
	@echo ""
	@echo "Deployment targets:"
	@echo "  make deploy     - Run quality checks, sync code, and deploy to Databricks Apps"
	@echo "  make sync       - Sync workspace files to Databricks"
	@echo "  make status     - View current Databricks App status"
	@echo "  make logs       - Tail or view Databricks App logs"

format:
	uv run ruff check --fix .
	uv run ruff format .

lint:
	uv run ruff check .
	uv run ruff format --check .
	uv run complexipy src --max-complexity-allowed 10
	python3 scripts/check_ast_limits.py
	uv run pyright

test:
	uv run pytest

frontend-install:
	npm ci

frontend-check:
	@echo "==> Type-checking frontend (tsc)..."
	npm run typecheck
	@echo "==> Building frontend and checking committed output is current..."
	npm run build
	git diff --exit-code -- src/clawhouse/static
	@echo "==> Running frontend component tests (vitest)..."
	npm test

check:
	@echo "==> Running quality gates (prek)..."
	@if command -v prek >/dev/null 2>&1; then \
		prek run -a; \
	else \
		echo "prek is not installed; running ruff, complexipy, AST checks, and pyright"; \
		uv run ruff check . && uv run ruff format --check . && uv run complexipy src --max-complexity-allowed 10 && python3 scripts/check_ast_limits.py && uv run pyright; \
	fi
	@echo "==> Running pytest test suite..."
	uv run pytest
	@$(MAKE) frontend-check

demo:
	@echo "==> Clawhouse demo mode: scripted model, in-memory store, no keys needed."
	@echo "==> Open http://localhost:$(DEMO_PORT)/chat and send any message."
	CLAWHOUSE_DEMO=1 \
	CLAWHOUSE_STORE=memory \
	CLAWHOUSE_DEV_USER=demo@example.com \
	CLAWHOUSE_TELEMETRY=0 \
	CLAWHOUSE_MLFLOW_TRACING=false \
	MLFLOW_DISABLE_AGENT_HINT=1 \
	uv run uvicorn clawhouse.api.app:app --port $(DEMO_PORT)

sync:
	@if [ -z "$(DATABRICKS_USER)" ] && [ "$(WORKSPACE_PATH)" = "/Workspace/Users//$(APP_NAME)" ]; then \
		echo "Set WORKSPACE_PATH or DATABRICKS_USER (or sign in with the databricks CLI)."; exit 1; \
	fi
	@echo "==> Syncing files to Databricks workspace $(WORKSPACE_PATH)..."
	databricks sync . $(WORKSPACE_PATH) \
		--exclude ".git/**" \
		--exclude ".venv/**" \
		--exclude ".pytest_cache/**" \
		--exclude ".ruff_cache/**" \
		--exclude ".complexipy_cache/**" \
		--exclude ".github/**" \
		--exclude "tests/**" \
		--exclude "docs/**" \
		--exclude "frontend/**" \
		--exclude "frontend-reimagined/**" \
		--exclude "package.json" \
		--exclude "package-lock.json" \
		--exclude "vitest.config.ts" \
		--exclude "node_modules/**" \
		--exclude ".agents/**" \
		--exclude ".claude/**" \
		--exclude ".grok/**" \
		--exclude "**/__pycache__/**" \
		--exclude "**/*.pyc"

deploy: check sync
	@echo "==> Deploying $(APP_NAME) on Databricks Apps..."
	databricks apps deploy $(APP_NAME) --source-code-path $(WORKSPACE_PATH)
	@echo "==> Deployment initiated successfully!"
	@databricks apps get $(APP_NAME)

status:
	databricks apps get $(APP_NAME)

logs:
	databricks apps logs $(APP_NAME)
