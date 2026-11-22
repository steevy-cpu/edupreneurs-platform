# Mon Edupreneur 2.0 — local task runner. Everything here targets THIS machine only.
SUPABASE := npx --no-install supabase
PY := uv run

.DEFAULT_GOAL := help
.PHONY: help install setup start stop status db-reset api token test test-db test-api lint format typecheck check openapi

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  %-12s %s\n", $$1, $$2}'

install: ## Install the pinned Supabase CLI and Python dependencies
	npm ci --no-fund --no-audit
	uv sync

setup: install ## First-time setup: signing key, start stack, apply schema, write .env
	$(PY) python scripts/local_stack.py keys
	$(MAKE) start
	$(MAKE) db-reset

start: ## Start the local Supabase stack (Postgres + Auth), Docker required
	$(PY) python scripts/local_stack.py keys
	$(SUPABASE) start

stop: ## Stop the local stack (data is kept until the next db-reset)
	$(SUPABASE) stop

status: ## Show local stack status
	$(SUPABASE) status

db-reset: ## DESTROY and rebuild the LOCAL database from migrations + seed
	@echo ">> Target: LOCAL disposable database only (no --linked / --remote)."
	$(SUPABASE) db reset
	$(PY) python scripts/local_stack.py env
	$(PY) python scripts/local_stack.py provision

api: ## Run the API at http://127.0.0.1:8000 (docs at /docs)
	$(PY) uvicorn edu_api.main:create_app --factory --host 127.0.0.1 --port 8000 --reload

token: ## Print a local access token: make token ACCOUNT=student_a
	@$(PY) python scripts/dev_token.py $(or $(ACCOUNT),student_a)

test-db: ## Database tests (pgTAP) inside the local Postgres
	$(SUPABASE) test db

test-api: ## API unit + integration tests (pytest) against the local stack
	$(PY) pytest

test: test-db test-api ## Run every test

lint: ## Ruff lint + format check
	$(PY) ruff check .
	$(PY) ruff format --check .

format: ## Auto-format Python
	$(PY) ruff format .
	$(PY) ruff check --fix .

typecheck: ## mypy (strict)
	$(PY) mypy

check: lint typecheck test ## Everything CI runs

openapi: ## Regenerate packages/contracts/openapi.json
	$(PY) python scripts/export_openapi.py
