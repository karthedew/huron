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

### Running the whole app in containers

```bash
make hosts   # one-time: adds "127.0.0.1 keycloak" to /etc/hosts (sudo prompt)
make stack   # docker/podman compose --profile app up -d --build --wait
```

`make stack` builds the `Containerfile` (multi-stage `uv sync --frozen --no-dev`, non-root
user, `uvicorn ... --host 0.0.0.0 --port 8080`) and brings up two more services behind the
`app` Compose profile, on top of everything `make up` starts:

- `migrate` — a one-shot container that runs `alembic upgrade head` against Postgres and exits;
  `api` waits for it to complete successfully before starting.
- `api` — the whole application, published on `http://localhost:8080`, configured entirely
  through the `HURON_*` environment variables set in `docker-compose.yml` (see the table below
  for what each one means). The API always connects to `HURON_DATABASE_URL`, real Postgres
  here, and `HURON_AUTH_MODE=oidc` makes this the one place the whole login flow (password
  *and* OIDC) runs end-to-end against real Postgres and a real IdP.

**The issuer, decided once — and `make hosts` is required in BOTH modes.** The compose
`keycloak` service sets `KC_HOSTNAME: http://keycloak:8081`, which fixes Keycloak's *entire*
discovery document — `issuer`, `authorization_endpoint`, `token_endpoint`, `jwks_uri` — to
`http://keycloak:8081/...` no matter which URL was used to reach
`/.well-known/openid-configuration` in the first place. Fetch discovery from `localhost:8081`
and you still get `keycloak:8081` URLs back. So every consumer of this realm needs `keycloak`
to resolve — the browser (redirected to `authorization_endpoint`) **and** the API's own
outbound calls during discovery and token exchange, regardless of whether the API process
itself is running in the compose network (`make stack`, where `keycloak` already resolves as a
service name) or on the host (`make api`, where it needs the `make hosts` line). There is no
host-mode variant that can skip it or use `localhost:8081` instead — `HURON_OIDC__ISSUER` is
`http://keycloak:8081/realms/huron` either way.

Run `make hosts` once. The OIDC variables are the same whether `api` runs in the container or
on the host: both read `dev.env` (below), and the compose service overrides only
`HURON_DATABASE_URL`.

Both dev users seeded in the realm log in at Keycloak's own login form during the code flow:
`karl` / `karl-dev-password` (realm role `platform-admins`, surfaced as the OIDC `groups`
claim — though what actually seeds karl's `platform_owner` RBAC binding is
`HURON_BOOTSTRAP_PLATFORM_OWNER=karl`, unrelated to Keycloak) and `sam` / `sam-dev-password`
(a plain user, no elevated role). All of it — client secret, both passwords — is a
development-only literal that lives in `scripts/keycloak/huron-realm.json`, valid only for a
Keycloak instance nobody but your own machine can reach.

!!! warning "PostgreSQL is on 5433, not 5432"

    Deliberate, so the stack coexists with another project already bound to 5432. `alembic.ini`
    and every example here use `postgresql+asyncpg://huron:huron@localhost:5433/huron`.

!!! warning "MinIO is not Ceph RGW"

    Close enough for use-case tests and wrong in the places that matter — multipart ETag
    computation, conditional writes, resharding. Storage adapter contract tests must run against
    a real RGW before a release.

Object storage buckets are created once with `make bootstrap`, which runs
`scripts/bootstrap_buckets.py` through botocore rather than shelling out to a client binary, so
nothing beyond the project's own dependencies is needed.

### Podman on macOS

If MinIO starts rejecting signed requests with `RequestTimeTooSkewed`, or `podman ps -a` shows
containers that exited "292 years ago", the Podman VM's clock has drifted after a host sleep.
With Keycloak in the stack, the same drift also shows up as token `iat`/`exp` verification
failures — a token issued by (or verified against) a clock that thinks it's the wrong time.
Either way, the fix is the same:

```bash
podman machine stop && podman machine start
```

## Migrations

```bash
make migrate            # uv run --env-file dev.env alembic upgrade head
```

Migrations live in `migrations/versions/`. Each one is a module docstring explaining *why*, a
`DDL = r"""..."""` string, `upgrade()` handing it to `migrations._ddl.execute_sql` (asyncpg
prepares one statement at a time, so a multi-statement `op.execute` fails), and a real
`downgrade()`.
`migrations/schema.sql` is a hand-maintained summary of the whole metastore for reading — it is
documentation and is never executed.

## Running the API

```bash
make api                # uv run --env-file dev.env uvicorn huron.applications.api.main:app --reload --port 8080
```

Configuration is environment variables with the `HURON_` prefix, read by `ApiSettings` in
`huron/applications/api/settings.py`. `ApiSettings` reads the process environment and nothing else —
it has no `.env` support of its own, so a bare `uvicorn` with nothing exported fails at import
with four `Field required` errors. `dev.env` at the repository root holds the development
values, and both `make api` and `make migrate` load it through `uv run --env-file`; a variable
already set in your shell takes precedence over the file. The compose `api` service reads the
same file through `env_file`, so there is one place to change the development configuration.
Every value in it is a development-only literal for the local stack — the JSON vocabulary is
single-quoted so uv, Docker Compose and podman-compose all read it byte for byte.

| Variable | Required | Notes |
|---|---|---|
| `HURON_ENV` | yes | `development` / `staging` / `production` |
| `HURON_AUTH_MODE` | yes | `oidc` / `dev-headers`. Refused at startup if `dev-headers` outside `development` |
| `HURON_DATABASE_URL` | yes | |
| `HURON_CLASSIFICATION_VOCABULARY` | yes | Codes and orders must each be unique, and the list may not be empty |
| `HURON_DATA_ROOT` | no | Defaults to `/data` |
| `HURON_BOOTSTRAP_PLATFORM_OWNER` | no | Subject granted a SYSTEM-scope `platform_owner` binding at startup |
| `HURON_LOGIN_FLOW_SECRET` | outside `development` | Signs the transient `huron_login` flow cookie |
| `HURON_OIDC__*` | when `HURON_AUTH_MODE=oidc` | Nested via `__`, e.g. `HURON_OIDC__ISSUER`, `HURON_OIDC__CLIENT_ID`, `HURON_OIDC__CLIENT_SECRET`, `HURON_OIDC__REDIRECT_URL` |
| `HURON_PASSWORD_LOGIN_ENABLED` | no | Defaults to `true` |
| `HURON_SESSION_COOKIE_NAME` | no | Defaults to `huron_session` |
| `HURON_WEB_APP_URL` | no | Where `/auth/oidc/callback` lands the browser after login; defaults to `http://localhost:5173` |

### Authenticating in development

With `HURON_AUTH_MODE=dev-headers`, identity comes from request headers:

```bash
curl -H 'X-Huron-Subject: alice' -H 'X-Huron-Groups: physics,leads' \
     http://localhost:8080/auth/session
```

`DevHeaderResolver` refuses to construct outside `development`, and `ApiSettings` refuses the
combination at startup — so this cannot be switched on in a deployed environment by setting one
variable.

An API key works anywhere: `Authorization: Bearer hk_{key_id}_{secret}`. Any other bearer token
is treated as an OIDC JWT and passed to the verifier the composition root injects.

!!! note "Bootstrapping permissions"

    A fresh deployment has no role bindings, so nothing can create an organization or grant a
    role. `HURON_BOOTSTRAP_PLATFORM_OWNER` grants exactly one SYSTEM-scope `platform_owner`
    binding at startup — the single way in. Unset it once real bindings exist.

## Running the frontend

```bash
make web-install        # npm ci in web/, once
make web                # vite dev server on http://localhost:5173
make web-check          # svelte-check + prettier --check
make web-test           # vitest
make web-build          # production build (adapter-node)
```

`http://localhost:5173` is where `/auth/oidc/callback` sends the browser after login
(`HURON_WEB_APP_URL` in `dev.env`), so the API and the frontend are meant to run side by side:
`make up`, `make migrate`, then `make api` in one terminal and `make web` in another.
