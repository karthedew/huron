.PHONY: help up down stack check hosts logs keycloak-reset bootstrap migrate api test test-acceptance lint docs docs-serve web-install web web-build web-check web-test

.DEFAULT_GOAL := help

# Prefers Docker Compose; falls back to Podman Compose when Docker is absent.
COMPOSE := $(shell command -v docker >/dev/null 2>&1 && echo "docker compose" || echo "podman-compose")

# HURON_* configuration for the API on the host; the compose "api" service
# reads the same file through env_file. Shell variables take precedence.
ENV_FILE := dev.env

# Service whose logs `make logs` follows; empty means every service.
SERVICE ?=

help: ## List available commands.
	@grep -E '^[a-zA-Z_-]+:.*## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*## "}; {printf "  \033[36m%-15s\033[0m %s\n", $$1, $$2}'

up: ## Start PostgreSQL, MinIO and Keycloak (infra only), then probe each one from the host.
	$(COMPOSE) up -d --wait postgres minio keycloak
	./scripts/check-stack.sh

stack: ## Build and run the WHOLE app (api + migrations) in containers, behind the "app" profile, then probe it.
	$(COMPOSE) --profile app up -d --build --wait
	./scripts/check-stack.sh postgres minio keycloak hosts api

check: ## Probe the running stack: Postgres, MinIO, the Keycloak realm and its issuer, and /etc/hosts.
	./scripts/check-stack.sh

hosts: ## Idempotently add "127.0.0.1 keycloak" to /etc/hosts (prompts for sudo), needed on the host in both make up and make stack modes.
	grep -q "127.0.0.1 keycloak" /etc/hosts || echo "127.0.0.1 keycloak" | sudo tee -a /etc/hosts

logs: ## Follow container logs; SERVICE=keycloak (or postgres, minio, api, migrate) narrows to one.
	$(COMPOSE) logs -f $(SERVICE)

keycloak-reset: ## Re-create the Keycloak container so scripts/keycloak/huron-realm.json is imported afresh.
	$(COMPOSE) down keycloak
	$(COMPOSE) up -d --wait keycloak
	./scripts/check-stack.sh keycloak hosts

down: ## Stop the stack and remove its containers.
	$(COMPOSE) down

bootstrap: ## Create and configure the raw, staging, and index buckets.
	./scripts/bootstrap-buckets.sh

migrate: ## Run pending Alembic migrations against the database configured in dev.env.
	uv run --env-file $(ENV_FILE) alembic upgrade head

api: ## Run the API on the host with autoreload, configured by dev.env, against infra started by "make up".
	uv run --env-file $(ENV_FILE) uvicorn huron.applications.api.main:app --reload --port 8080

test: ## Run the fast unit suite.
	uv run pytest -m unit

test-acceptance: ## Run the acceptance suite.
	uv run pytest -m acceptance

lint: ## Lint source under src and validate the migration schema map.
	uv run ruff check src
	uv run ruff format --check src
	uv run pydoclint src
	uv run mypy
	uv run ty check
	uv run lint-imports
	uv run python scripts/check_schema_map.py
	uv run radon cc src --min C
	uv run radon mi src --min B
	uv run complexipy src --max-complexity-allowed 15
	uv run --locked pyscn check src
	uv run --locked python scripts/check_duplication.py src

docs: ## Build the documentation site, failing on broken internal links.
	uv run --group docs zensical build --strict

docs-serve: ## Serve the documentation with live reload on :8000.
	uv run --group docs zensical serve

web-install: ## Install the frontend's locked dependencies (npm ci in web/).
	cd web && npm ci

web: ## Serve the frontend with hot reload on :5173 (the URL HURON_WEB_APP_URL in dev.env points at).
	cd web && npm run dev

web-build: ## Production build of the frontend (adapter-node).
	cd web && npm run build

web-check: ## Type-check the frontend (svelte-check) and verify formatting (prettier).
	cd web && npm run check && npm run lint

web-test: ## Run the frontend unit tests (vitest).
	cd web && npm test
