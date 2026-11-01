.PHONY: help up down migrate api app app-down app-logs app-reset demo-noaa test test-contract test-integration lint gate openapi docs-check

.DEFAULT_GOAL := help

COMPOSE := $(shell command -v docker >/dev/null 2>&1 && echo "docker compose" || echo "podman-compose")
ENV_FILE := dev.env
# The two compose projects: `make up`'s "huron" (PostgreSQL and Keycloak) and `make app`'s "huron-app".
DEV := $(COMPOSE) -f docker-compose.yml
APP := $(COMPOSE) -f docker-compose.app.yml
# The service configuration of both stacks: `make api` reads huron.dev.yaml through dev.env's
# HURON_CONFIG_FILE; `make app` mounts it, or the file HURON_DEV_CONFIG names (the file it hashes is
# always the file it mounts).
API_CONFIG := huron.dev.yaml
DEV_CONFIG ?= $(or $(HURON_DEV_CONFIG),$(API_CONFIG))
# Its SHA-256, which makes `make app` recreate the API when the file changes (docker-compose.app.yml).
DEV_CONFIG_SHA256 = $(firstword $(shell sha256sum $(DEV_CONFIG) 2>/dev/null || shasum -a 256 $(DEV_CONFIG) 2>/dev/null))

help: ## List available commands.
	@grep -E '^[a-zA-Z_-]+:.*## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*## "}; {printf "  \033[36m%-18s\033[0m %s\n", $$1, $$2}'

# The two stacks share their ports, so each start stops the other one first, and `make down` stops
# both; none of these deletes data (only `make app-reset` does).
up: ## Stop the Docker application (data kept), start PostgreSQL and Keycloak, then probe them.
	$(APP) down
	$(DEV) up -d --wait postgres keycloak
	./scripts/check-stack.sh

down: ## Stop both stacks, `make up`'s and `make app`'s; their data stays.
	$(DEV) down
	$(APP) down

migrate: ## Apply Alembic migrations to the database in dev.env.
	uv run --env-file $(ENV_FILE) alembic upgrade head

api: ## Run the API on the host with autoreload, also when huron.dev.yaml changes.
	uv run --env-file $(ENV_FILE) uvicorn huron.applications.api.main:app --reload --reload-include $(API_CONFIG) --port 8080

app: ## Stop the `make up` stack (data kept), then build and start the whole application in Docker, or apply an edited huron.dev.yaml; the web is http://localhost:3000.
	@test -f $(DEV_CONFIG) || { echo "app: $(DEV_CONFIG) is missing" >&2; exit 1; }
	$(DEV) down
	HURON_DEV_CONFIG=$(abspath $(DEV_CONFIG)) HURON_DEV_CONFIG_SHA256=$(DEV_CONFIG_SHA256) $(APP) up -d --build --wait
	@echo "web: http://localhost:3000   API: http://127.0.0.1:8080   Keycloak: http://127.0.0.1:8081/realms/company"

app-down: ## Stop only the Docker application; its data stays.
	$(APP) down

app-logs: ## Follow the logs of the Docker application.
	$(APP) logs -f

app-reset: ## Stop the Docker application and delete its data.
	$(APP) down -v

# NOAA_RAW=<dir> loads an existing examples/noaa/fetch.py download; NOAA_REFRESH=1 fetches again.
demo-noaa: ## Load the NOAA Planetary K-index demo (catalog planetary in org noaa) into a running `make app`; safe to re-run.
	./scripts/demo-noaa.sh

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
