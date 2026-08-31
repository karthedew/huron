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
make up      # docker compose up -d --wait postgres minio keycloak  (or podman-compose)
make down    # stop and remove the containers
```

`make up` starts infra only — Postgres, MinIO, and Keycloak (the local IdP) — and nothing else.
The API itself runs on the host (`make api`, below) unless you opt into the fully containerized
stack.

| Service | Host port | Stands in for |
|---|---|---|
| PostgreSQL 16 | **5433** | PostgreSQL |
| MinIO | 9000 (API) / 9001 (console) | Ceph RGW |
| Keycloak 26 | 8081 | The IdP; realm `huron` is pre-seeded from `scripts/keycloak/huron-realm.json` |

Keycloak's healthcheck probes `/health/ready` on its management port
(`KC_HEALTH_ENABLED=true`), not just the HTTP port accepting connections — so
`make up`/`make stack` only report it healthy once realm import has actually finished, and a
broken `huron-realm.json` shows up as `make up` hanging/failing rather than as a later
discovery 404 from `api`.

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
  for what each one means). `HURON_STORE_BACKEND=postgres` and `HURON_AUTH_MODE=oidc` here — this
  is the one place the whole login flow (password *and* OIDC) runs end-to-end against real
  Postgres and a real IdP.

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

Run `make hosts` once, then set the same OIDC variables whether `api` runs in the container or
on the host — e.g. in `.env` for `make api`:

```bash
HURON_AUTH_MODE=oidc
HURON_OIDC__ISSUER=http://keycloak:8081/realms/huron
HURON_OIDC__CLIENT_ID=huron-web
HURON_OIDC__CLIENT_SECRET=dev-only-secret
HURON_OIDC__REDIRECT_URL=http://localhost:8080/auth/oidc/callback
```

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
make migrate            # uv run alembic upgrade head
```

Migrations live in `migrations/versions/`. Each one is a module docstring explaining *why*, a
`DDL = r"""..."""` string, `upgrade()` running `op.execute(DDL)`, and a real `downgrade()`.
`migrations/schema.sql` is a hand-maintained summary of the whole metastore for reading — it is
documentation and is never executed.

## Running the API

```bash
make api                # uvicorn huron.service.api.app:app --reload --port 8080
```

Configuration is environment variables with the `HURON_` prefix, read by `ApiSettings` in
`huron/service/api/settings.py`:

| Variable | Required | Notes |
|---|---|---|
| `HURON_ENV` | yes | `development` / `staging` / `production` |
| `HURON_AUTH_MODE` | yes | `oidc` / `dev-headers`. Refused at startup if `dev-headers` outside `development` |
| `HURON_DATABASE_URL` | yes | |
| `HURON_CLASSIFICATION_VOCABULARY` | yes | Codes and orders must each be unique, and the list may not be empty |
| `HURON_DATA_ROOT` | no | Defaults to `/data` |
| `HURON_BOOTSTRAP_PLATFORM_OWNER` | no | Subject granted a SYSTEM-scope `platform_owner` binding at startup |
| `HURON_STORE_BACKEND` | no | `memory` (default) or `postgres` |
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

!!! note "`HURON_STORE_BACKEND` defaults to `memory`"

    `postgres` wires the Postgres-backed RBAC *and* auth stores together, and is only safe
    once the rows their foreign keys target — organizations and projects — are real Postgres
    rows. The organization/project/dataset hierarchy is not Postgres-backed yet, so `memory`
    is the working default and `postgres` is an explicit opt-in.
