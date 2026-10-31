.PHONY: help up down migrate api app app-down app-logs app-reset test test-contract test-integration lint gate openapi docs-check

.DEFAULT_GOAL := help

COMPOSE := $(shell command -v docker >/dev/null 2>&1 && echo "docker compose" || echo "podman-compose")
ENV_FILE := dev.env
APP := $(COMPOSE) -f docker-compose.app.yml

help: ## List available commands.
	@grep -E '^[a-zA-Z_-]+:.*## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*## "}; {printf "  \033[36m%-18s\033[0m %s\n", $$1, $$2}'

up: ## Start PostgreSQL and Keycloak, then probe them.
	$(COMPOSE) up -d --wait postgres keycloak
	./scripts/check-stack.sh

down: ## Stop the development stack.
	$(COMPOSE) down

migrate: ## Apply Alembic migrations to the database in dev.env.
	uv run --env-file $(ENV_FILE) alembic upgrade head

api: ## Run the API on the host with autoreload.
	uv run --env-file $(ENV_FILE) uvicorn huron.applications.api.main:app --reload --port 8080

app: ## Build and start the whole application in Docker; the web is http://localhost:3000.
	$(APP) up -d --build --wait
	@echo "web: http://localhost:3000   API: http://127.0.0.1:8080   Keycloak: http://127.0.0.1:8081/realms/company"

app-down: ## Stop the Docker application; its data stays.
	$(APP) down

app-logs: ## Follow the logs of the Docker application.
	$(APP) logs -f

app-reset: ## Stop the Docker application and delete its data.
	$(APP) down -v

test: ## Run the unit tier (no database needed).
	uv run pytest -m "not contract and not integration"

test-contract: ## Run the store contract suite against PostgreSQL.
	uv run pytest -m contract

test-integration: ## Run the integration tier.
	uv run pytest -m integration

lint: ## Static checks only.
	uv run ruff check src tests
	uv run ruff format --check src tests
	uv run mypy
	uv run ty check
	uv run lint-imports

gate: lint ## The plan-wide gate (section 10); the contract tier needs Docker or HURON_TEST_DATABASE_URL.
	uv run pytest -m "not integration" --cov=src/huron --cov-report=term-missing
	@out="$$(uv run radon cc src --min C)"; if [ -n "$$out" ]; then echo "$$out"; exit 1; fi
	@out="$$(uv run radon mi src --min B)"; if [ -n "$$out" ]; then echo "$$out"; exit 1; fi
	uv run complexipy src --max-complexity-allowed 15
	uv run python scripts/check_schema_map.py

openapi: ## Regenerate docs/openapi.json from the application.
	uv run python -m huron.applications.api.openapi docs/openapi.json

docs-check: ## Check relative links in docs/ and README.md.
	uv run python scripts/check_links.py README.md docs deploy/README.md
