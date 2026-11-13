.PHONY: help up down migrate api app app-down app-logs app-reset uploads uploads-down demo-noaa k8s-local-cluster k8s-local k8s-local-smoke k8s-local-down test test-contract test-integration lint gate openapi docs-check

.DEFAULT_GOAL := help

COMPOSE := $(shell command -v docker >/dev/null 2>&1 && echo "docker compose" || echo "podman-compose")
ENV_FILE := dev.env
# The three compose projects: `make up`'s "huron" (PostgreSQL and Keycloak), `make app`'s
# "huron-app" and `make uploads`'s "huron-uploads" (nginx and tusd for `make api`).
# The containers that write the lake run as you, and the lake is HURON_LAKE_SOURCE on the host,
# bound at HURON_LAKE_PATH, the `lake_path` of the service configuration. The API reports
# HURON_GROUP as its service group. The compose commands get these variables, `make api` gets
# HURON_GROUP and `make demo-noaa` gets HURON_LAKE_PATH. They are not exported: in the environment
# of the API or of the tests, HURON_LAKE_PATH would set `lake_path`.
HURON_UID ?= $(shell id -u)
HURON_GID ?= $(shell id -g)
HURON_GROUP ?= $(shell id -gn)
HURON_LAKE_SOURCE ?= /data1/huron
HURON_LAKE_PATH ?= /data1/huron
LAKE_ENV := HURON_UID=$(HURON_UID) HURON_GID=$(HURON_GID) HURON_GROUP=$(HURON_GROUP) HURON_LAKE_SOURCE=$(HURON_LAKE_SOURCE) HURON_LAKE_PATH=$(HURON_LAKE_PATH)
DEV := $(COMPOSE) -f docker-compose.yml
APP := $(LAKE_ENV) $(COMPOSE) -f docker-compose.app.yml
UPLOADS := $(LAKE_ENV) $(COMPOSE) -f docker-compose.uploads.yml
# The service configuration of both stacks: `make api` reads huron.dev.yaml through dev.env's
# HURON_CONFIG_FILE; `make app` mounts it, or the file HURON_DEV_CONFIG names (the file it hashes is
# always the file it mounts).
API_CONFIG := huron.dev.yaml
DEV_CONFIG ?= $(or $(HURON_DEV_CONFIG),$(API_CONFIG))
# Its SHA-256, which makes `make app` recreate the API when the file changes (docker-compose.app.yml).
DEV_CONFIG_SHA256 = $(firstword $(shell sha256sum $(DEV_CONFIG) 2>/dev/null || shasum -a 256 $(DEV_CONFIG) 2>/dev/null))
# The scripts the gate lints and type-checks with src and tests. The other scripts fail ruff today.
CHECKED_SCRIPTS := scripts/check_duplication.py scripts/cli_reference.py scripts/ste_check.py

help: ## List available commands.
	@grep -E '^[a-zA-Z0-9_-]+:.*## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*## "}; {printf "  \033[36m%-18s\033[0m %s\n", $$1, $$2}'

# The two stacks share their ports, so each start stops the other one first, and `make down` stops
# all three projects; none of these deletes data (only `make app-reset` does).
up: ## Stop the Docker application (data kept), start PostgreSQL and Keycloak, then probe them.
	$(APP) down
	$(DEV) up -d --wait postgres keycloak
	./scripts/check-stack.sh

down: ## Stop the stacks of `make up`, `make app` and `make uploads`; their data stays.
	$(DEV) down
	$(APP) down
	$(UPLOADS) down

migrate: ## Apply Alembic migrations to the database in dev.env.
	uv run --env-file $(ENV_FILE) alembic upgrade head

api: ## Run the API on the host with autoreload, also when huron.dev.yaml changes.
	HURON_SERVICE_GROUP=$(HURON_GROUP) uv run --env-file $(ENV_FILE) uvicorn huron.applications.api.main:app --reload --reload-include $(API_CONFIG) --port 8080

app: ## Stop the `make up` and `make uploads` stacks (data kept), then build and start the whole application in Docker, or apply an edited huron.dev.yaml; the web is http://localhost:3000.
	@test -f $(DEV_CONFIG) || { echo "app: $(DEV_CONFIG) is missing" >&2; exit 1; }
	$(DEV) down
	$(UPLOADS) down
	HURON_DEV_CONFIG=$(abspath $(DEV_CONFIG)) HURON_DEV_CONFIG_SHA256=$(DEV_CONFIG_SHA256) $(APP) up -d --build --wait
	@echo "web: http://localhost:3000   API: http://127.0.0.1:8080   Keycloak: http://127.0.0.1:8081/realms/company   uploads: http://127.0.0.1:1080/files/"

app-down: ## Stop only the Docker application; its data stays.
	$(APP) down

app-logs: ## Follow the logs of the Docker application.
	$(APP) logs -f

app-reset: ## Stop the Docker application and delete its database; the lake stays.
	$(APP) down -v

# `make app` runs its own tusd over the same lake, so `make uploads` stops that stack first.
uploads: ## Stop the Docker application (data kept), then start the upload proxy on port 1080 and tusd for the API of `make api`.
	$(APP) down
	$(UPLOADS) up -d --wait

uploads-down: ## Stop the upload proxy and tusd of `make uploads`.
	$(UPLOADS) down

# NOAA_RAW=<dir> loads an existing examples/noaa/fetch.py download; NOAA_REFRESH=1 fetches again.
demo-noaa: ## Load the NOAA Planetary K-index demo (catalog planetary in org noaa) into a running stack whose API takes uploads; safe to re-run.
	HURON_LAKE_PATH=$(HURON_LAKE_PATH) ./scripts/demo-noaa.sh

# The local cluster (deploy/local) on the kind cluster huron-local, through K8S_LOCAL_KUBECONFIG;
# scripts/k8s-local.sh says what the node needs. The smoke uses port 8081, as Keycloak of `make app`
# and `make up`.
k8s-local-cluster: ## Make the kind cluster huron-local with the lake mount and port 18444, then install ingress-nginx.
	./scripts/k8s-local.sh cluster

k8s-local: ## Build the API image, import the images into the node of the local cluster, apply deploy/local and wait for it.
	./scripts/k8s-local.sh up

k8s-local-smoke: ## Push files to the local cluster from the host, then check its lake from the host; stop `make app` and `make up` first.
	./scripts/k8s-local.sh smoke

k8s-local-down: ## Delete the namespace huron and the lake volume of the local cluster; the lake content stays unless K8S_LOCAL_PURGE=1.
	./scripts/k8s-local.sh down

test: ## Run the unit tier (no database needed).
	uv run pytest -m "not contract and not integration"

test-contract: ## Run the store contract suite against PostgreSQL.
	uv run pytest -m contract

test-integration: ## Run the integration tier.
	uv run pytest -m integration

lint: ## Static checks only.
	uv run ruff check src tests $(CHECKED_SCRIPTS)
	uv run ruff format --check src tests $(CHECKED_SCRIPTS)
	uv run mypy
	uv run mypy $(CHECKED_SCRIPTS)
	uv run ty check
	uv run ty check $(CHECKED_SCRIPTS)
	uv run lint-imports
	uv run python scripts/cli_reference.py --check
	uv run python scripts/ste_check.py

gate: lint ## Run every check of the gate; the contract tier needs Docker or HURON_TEST_DATABASE_URL.
	uv run pytest -m "not integration" --cov=src/huron --cov-report=term-missing
	@out="$$(uv run radon cc src --min C)"; if [ -n "$$out" ]; then echo "$$out"; exit 1; fi
	@out="$$(uv run radon mi src --min B)"; if [ -n "$$out" ]; then echo "$$out"; exit 1; fi
	uv run complexipy src --max-complexity-allowed 15
	uv run --locked pyscn check src
	uv run --locked python scripts/check_duplication.py src
	uv run python scripts/check_schema_map.py

openapi: ## Regenerate docs/openapi.json from the application.
	uv run python -m huron.applications.api.openapi docs/openapi.json

docs-check: ## Check relative links in docs/ and README.md.
	uv run python scripts/check_links.py README.md docs deploy/README.md
