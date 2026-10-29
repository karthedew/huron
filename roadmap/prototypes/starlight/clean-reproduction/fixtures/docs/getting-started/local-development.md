# Local development

## Prerequisites

| Tool | Version | Why |
|---|---|---|
| Python | 3.12+ | `requires-python = ">=3.12"`; the code uses 3.12 generics and `StrEnum` |
| [uv](https://docs.astral.sh/uv/) | recent | Dependency resolution and the project environment |
| Docker **or** Podman | recent | The Compose stack. The `Makefile` prefers `docker compose` and falls back to `podman-compose` |

```bash
uv sync                 # runtime + dev dependencies into .venv
uv sync --group docs    # adds the documentation toolchain
```

## The Compose stack

```bash
make up      # compose up -d --wait postgres minio keycloak, then scripts/check-stack.sh
make check   # re-run the probes against a stack that is already up
make logs SERVICE=keycloak   # follow one service's logs (omit SERVICE for all)
make down    # stop and remove the containers
```

`make up` starts infra only — Postgres, MinIO, and Keycloak (the local IdP) — and nothing else.
The API itself runs on the host (`make api`, below) unless you opt into the fully containerized
stack.

`make up` does not trust `compose up --wait` on its own. Docker Compose fails when a container
exits before its healthcheck passes; **podman-compose does not** — Podman's remote API (the path
`podman machine` always takes on macOS) answers `0` for a container that stopped before becoming
healthy, so podman-compose prints a bare `0` in its `--wait` output and exits successfully. That
is exactly what a failed Keycloak realm import looks like. So `make up` finishes by running
`scripts/check-stack.sh`, which probes each service from the host — Postgres answers the wire
protocol on 5433, MinIO's liveness endpoint, the `huron` realm's discovery document with the
expected issuer, and whether `keycloak` resolves on this host — and fails with a `[FAIL]` line
and a hint when one does not.

| Service | Host port | Stands in for |
|---|---|---|
| PostgreSQL 16 | **5433** | PostgreSQL |
| MinIO | 9000 (API) / 9001 (console) | Ceph RGW |
| Keycloak 26 | 8081 | The IdP; realm `huron` is pre-seeded from `scripts/keycloak/huron-realm.json` |

Keycloak's healthcheck probes `/health/ready` on its management port
(`KC_HEALTH_ENABLED=true`), not just the HTTP port accepting connections, so the container is
only healthy once realm import has actually finished. A broken `huron-realm.json` aborts the
import and the container exits; `make up` then reports `[FAIL] keycloak realm 'huron' is
missing`. Read the cause with `make logs SERVICE=keycloak`, fix the file, and run
`make keycloak-reset` — Keycloak keeps no volume, so re-creating its container re-imports the
realm from scratch. Two limits of the import schema are easy to trip: a role `description` is
at most 255 characters, and every user needs `firstName`, `lastName` and `email` or the
default user profile stops each login at an "Update Account Information" page.

### Running the backend in containers

```bash
make hosts   # one-time: adds "127.0.0.1 keycloak" to /etc/hosts (sudo prompt)
make stack   # docker/podman compose --profile app up -d --build --wait
```

`make stack` builds the `Containerfile` (multi-stage `uv sync --frozen --no-dev`, non-root
user, `uvicorn ... --host 0.0.0.0 --port 8080`) and brings up two more services behind the
`app` Compose profile, on top of everything `make up` starts:

- `migrate` — a one-shot container that runs `alembic upgrade head` against Postgres and exits;
  `api` waits for it to complete successfully before starting.
- `api` — the backend application, published on `http://localhost:8080`, configured entirely
  through the `HURON_*` environment variables set in `docker-compose.yml` (see the table below
  for what each one means). The API always connects to `HURON_DATABASE_URL`, real Postgres
  here, and `HURON_AUTH_MODE=oidc` makes this the one place the whole login flow (password
  *and* OIDC) runs end-to-end against real Postgres and a real IdP.

This does **not** start the frontend. Compose currently has no persistent Raw volume,
external directory mock or k6 service/profile. Frontend development uses 5173 and
Playwright's test server uses 4173. Establish port/service ownership before operating
any stack; another project may already own 5173 or 9000.
