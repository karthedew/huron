.PHONY: help up down stack hosts bootstrap migrate api test lint docs docs-serve

.DEFAULT_GOAL := help

# Prefers Docker Compose; falls back to Podman Compose when Docker is absent.
COMPOSE := $(shell command -v docker >/dev/null 2>&1 && echo "docker compose" || echo "podman-compose")

help: ## List available commands.
	@grep -E '^[a-zA-Z_-]+:.*## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*## "}; {printf "  \033[36m%-12s\033[0m %s\n", $$1, $$2}'

up: ## Start PostgreSQL, MinIO, and Keycloak (infra only), waiting for all to report healthy.
	$(COMPOSE) up -d --wait postgres minio keycloak

stack: ## Build and run the WHOLE app (api + migrations) in containers, behind the "app" profile.
	$(COMPOSE) --profile app up -d --build --wait

hosts: ## Idempotently add "127.0.0.1 keycloak" to /etc/hosts (prompts for sudo), needed on the host in both make up and make stack modes.
	grep -q "127.0.0.1 keycloak" /etc/hosts || echo "127.0.0.1 keycloak" | sudo tee -a /etc/hosts

down: ## Stop the stack and remove its containers.
	$(COMPOSE) down

bootstrap: ## Create and configure the raw, staging, and index buckets.
	./scripts/bootstrap-buckets.sh

migrate: ## Run pending Alembic migrations against the database.
	uv run alembic upgrade head

api: ## Run the API on the host with autoreload, against infra started by "make up".
	uv run uvicorn huron.service.api.app:app --reload --port 8080

test: ## Run the fast unit suite.
	uv run pytest -m unit

lint: ## Run every static check CI enforces.
	uv run ruff check .
	uv run ruff format --check .
	uv run mypy
	uv run lint-imports

docs: ## Build the documentation site, failing on broken internal links.
	uv run --group docs zensical build --strict

docs-serve: ## Serve the documentation with live reload on :8000.
	uv run --group docs zensical serve
