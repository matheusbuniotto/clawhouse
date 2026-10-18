.PHONY: all help check lint format test frontend-install frontend-check sync deploy logs status

APP_NAME ?= clawhouse
WORKSPACE_PATH ?= $(shell databricks apps get $(APP_NAME) -o json 2>/dev/null | jq -r '.default_source_code_path // empty' 2>/dev/null)
ifeq ($(strip $(WORKSPACE_PATH)),)
WORKSPACE_PATH := /Workspace/Users/matheus.buniotto@gmail.com/clawhouse
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

sync:
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
