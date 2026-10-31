# Huron

Huron is a catalog and access-control plane for raw scientific data that lives on an NFS share.
Scientists and administrators work through the `huron` command-line tool on machines that mount the
share at `/projects/huron`. A FastAPI service and a PostgreSQL database hold the catalog of
organizations, catalogs, namespaces and collections, their metadata, the role grants and an audit log.

Every directory the CLI creates carries POSIX ACLs derived from the catalog's role-to-LDAP-group
grants, so the filesystem enforces the same reader, contributor and administrator boundaries as the
service. Collection metadata is validated against a schema registry: each catalog is assigned a
schema, and a collection may extend it with an override. Pushes are synchronous commits that carry the
version they were based on, so a push that is behind is refused until the user pulls.

The service never touches file bytes. The CLI copies files over the mount and records them with the
service; `huron check` reports where disk and catalog disagree.

## Quick start

The API runs on the host, against PostgreSQL and Keycloak in Docker. It takes three terminals in the
repository root:

```bash
# Terminal 1: PostgreSQL and Keycloak, the migrations, then the group directory (keep it running)
uv sync
make up
make migrate
uv run python scripts/devgroups.py scripts/dev-groups.yaml 8082

# Terminal 2: the API on http://127.0.0.1:8080, with autoreload (keep it running)
make api

# Terminal 3: the CLI
uv run huron config set api_url http://127.0.0.1:8080
uv run huron config set issuer http://127.0.0.1:8081/realms/company
uv run huron login
```

`make migrate` and `make api` read `dev.env`. Never load that file into the CLI's environment: there
`HURON_ISSUER` is the API's own token issuer, while the CLI reads `HURON_ISSUER` as the company
identity provider. The accounts are those in [Accounts](#accounts) below. `make down` stops
PostgreSQL and Keycloak. `make up` and `make app` use the same ports, so run one at a time.
Unlike `make app`, which binds 127.0.0.1 only, this stack's PostgreSQL and Keycloak, with their
development passwords, and its group directory listen on every network interface: run it on a
machine and network you trust. To run the web against this stack, follow
[web/README.md](web/README.md#against-the-development-stack-make-up).

## Run everything in Docker

`make app` builds and starts the whole application in Docker
([docker-compose.app.yml](docker-compose.app.yml)): PostgreSQL with its own volume, the migrations,
the API, the development group directory, Keycloak as a stand-in for the company OIDC provider, the
web app, and a one-shot seed that loads the demo data of the web's end-to-end fixture. It returns once
every service is healthy and the seed has run.

Prerequisites: Docker Engine 25 or newer with the Compose plugin on Linux, or Docker Desktop 4.27 or
newer on macOS or Windows; ports 3000, 5432, 8080, 8081 and 8082 free on 127.0.0.1; `uv` for the
CLI. The first run pulls the images and builds the API and web images, which takes a few minutes.

```bash
make app
```

| Service | Address |
| --- | --- |
| Web app | http://localhost:3000 |
| API | http://127.0.0.1:8080 |
| Keycloak realm `company`, the issuer | http://127.0.0.1:8081/realms/company |
| Keycloak admin console | http://127.0.0.1:8081/admin/ |
| Group directory | http://127.0.0.1:8082/users/admin/groups |
| PostgreSQL (user, password and database `huron`) | 127.0.0.1:5432 |

All containers share one network namespace and publish their ports on 127.0.0.1 only, so these
addresses are the same inside the containers and on the host. That matters: Keycloak stamps its own
URL into every token as the issuer, and the API accepts a token only when that issuer is exactly
`http://127.0.0.1:8081/realms/company`. Use `127.0.0.1` for Keycloak and the API, not `localhost`.

The web is the one exception: open it at exactly http://localhost:3000. It is on `localhost`, a
different host from Keycloak's, so their cookies never mix, and it sends every sign-in back to
`http://localhost:3000/auth/callback`. A sign-in started on http://127.0.0.1:3000 therefore ends
with "That sign-in expired or was already used".

### Accounts

Users of the realm `company` ([scripts/keycloak/company-realm.json](scripts/keycloak/company-realm.json));
their LDAP groups come from [scripts/dev-groups.yaml](scripts/dev-groups.yaml).

| User | Password | Groups | Role in the demo data |
| --- | --- | --- | --- |
| `admin` | `admin` | `huron-platform-admins` | Platform admin: sees and manages everything |
| `user` | `user` | `helio-contributors`, `geo-readers` | Scientist: contributor in `heliophysics` and `space-weather`, reader of `geoscience` |
| `alice` | `password` | `huron-platform-admins` | Platform admin; created the organizations |
| `bob` | `password` | `helio-org-admins` | Org admin of `helio` |
| `carol` | `password` | `helio-catalog-admins` | Catalog admin of `heliophysics` and `space-weather` |
| `dave` | `password` | `helio-contributors`, `geo-readers` | Contributor in `helio`, reader of `geoscience` |
| `erin` | `password` | `helio-readers` | Reader in `helio` |

The Keycloak admin console's `admin` / `admin` is a different account in the `master` realm: it
administers Keycloak, not Huron.

### Signing in to the web

Open http://localhost:3000 and choose **Sign in with your company account**. Keycloak's login form
opens on 127.0.0.1:8081; sign in as `admin` or `user`. **Sign out** in the account menu ends the web
session and, once you confirm on Keycloak's page, the Keycloak session too.

### The CLI on the host

The CLI signs in to the same Keycloak and uses the same API. Run it in the repository root, where
`uv run` finds the project. A directory stands in for the NFS share; `scripts/init-root.sh` marks it
with the stack's instance id (`HURON_INSTANCE_ID` in `dev.env`, also at
http://127.0.0.1:8080/healthz), and `acl_backend none` applies modes without POSIX ACLs:

```bash
uv sync
mkdir -p ~/huron-share
scripts/init-root.sh ~/huron-share "$(id -gn)" http://127.0.0.1:8080 0192b6a0-0000-7000-8000-000000000001
uv run huron config set api_url http://127.0.0.1:8080
uv run huron config set issuer http://127.0.0.1:8081/realms/company
uv run huron config set mount_prefix ~/huron-share
uv run huron config set acl_backend none
uv run huron login --device    # open the printed link, sign in as admin, then grant access
uv run huron whoami
```

`huron login --browser` uses the loopback flow instead: it opens Keycloak in a browser on this
machine and receives the answer on `http://127.0.0.1:<random port>/callback`. Plain `huron login`
takes the browser when `DISPLAY` is set and the device flow otherwise.

Keycloak remembers who signed in last in a browser, through the web or the CLI. While that session
lasts, `huron login` signs the CLI in as that account without showing the form, and the device
flow's **Grant Access to huron-cli** page does not say who it is. To sign in as someone else, first
end that session: open http://127.0.0.1:8081/realms/company/protocol/openid-connect/logout and
choose **Logout**, or sign out of the web and confirm on Keycloak's page. A private window works
too. `uv run huron whoami` shows who the CLI is.

The web shows share paths under `/projects/huron`, the production mount point. To see the paths
on your share instead, start the stack with the CLI's `mount_prefix`:
`HURON_WEB_MOUNT_PREFIX="$HOME/huron-share" make app`. Every `make app` without it goes back to
`/projects/huron`.

### The seeded data

The seed runs `web/e2e/support/seed.mjs` with the fixture in `web/e2e/support/fixture.mjs`: the
organizations `helio`, `geo`, `astro` and `planetary`, four catalogs, nested namespaces, about 70
collections and an organization schema. It runs on every `make app` and changes nothing once the
first organization exists.

The seed records catalog entries only. No directory and no file bytes exist on any share: the files
the web lists are records without bytes on disk. `uv run huron check --catalog geoscience` therefore
reports the seeded namespaces and collections missing from your share (`namespace_dir_missing`,
`collection_dir_missing`) and exits 1.

On `heliophysics`, and without `--catalog`, `huron check` stops with `error: internal error
[INTERNAL]` instead. That is a known API bug, not your setup: the metadata of the seeded collection
`heliophysics.solar-wind.wind.swe-2023` holds the number `-1e31`, which the API reads back from
PostgreSQL as an integer too large for its canonical JSON, so it cannot render that collection's
`metadata.json`. The web's `metadata.json` page of that collection fails the same way.

Before the CLI writes below a seeded namespace, a platform admin creates its directories on your
share; re-running a create command repairs a missing directory. Signed in as `admin`:

```bash
uv run huron org create helio
uv run huron catalog create helio heliophysics
uv run huron namespace create heliophysics.solar-wind.ace --parents
```

Then sign out of Keycloak as described above, sign the CLI in as `user`, and make a collection with
one file. Both show in the web at once, at
http://localhost:3000/catalogs/heliophysics/collections/solar-wind.ace.my-run:

```bash
uv run huron login --device    # sign in as user
uv run huron whoami            # subject user
uv run huron catalog use heliophysics
work="$(mktemp -d)"            # the metadata and the file, outside the repository
printf '{"title": "My run", "description": "Made with the CLI"}\n' > "$work/meta.json"
printf 'time,value\n2024-01-01T00:00:00Z,1.5\n' > "$work/results.csv"
uv run huron collection create solar-wind.ace.my-run --metadata "$work/meta.json"
uv run huron add "$work/results.csv"
uv run huron push -m "First results"
```

`push` copies `results.csv` to `~/huron-share/helio/heliophysics/solar-wind/ace/my-run/`.

### Stopping and resetting

```bash
make app-logs    # follow the logs
make app-down    # stop; the database stays in the volume huron-app_postgres-data
make app         # start again: the data is still there and the seed changes nothing
make app-reset   # stop and delete the database; the next make app seeds again
```

Keycloak keeps nothing between starts: it imports `scripts/keycloak/company-realm.json` whenever it
starts, so realm edits apply after `make app-down` and `make app`, and every restart ends the Keycloak
sessions. Huron tokens the CLI holds stay valid until they expire. The web keeps its sessions in
memory, so restarting it signs everyone out of the web. The images `huron-app-api:dev` and
`huron-app-web:dev` stay until you remove them with `docker image rm`.

### Troubleshooting

- **A port is in use.** When `make up` (5432, 8081), `make api` (8080), the group directory (8082)
  or another program holds one of the stack's ports, `make app` stops with an error that names the
  port, on Linux `failed to bind port 127.0.0.1:<port>/tcp: … bind: address already in use`. Stop
  `make up` with `make down`, and `make api` and the group directory with Ctrl-C in their
  terminals. When another Docker project publishes the port, such as a running `scripts/e2e.sh`,
  the error is `Bind for 127.0.0.1:<port> failed: port is already allocated` instead. `ss -ltnp`
  on Linux or `lsof -nP -iTCP -sTCP:LISTEN` on macOS shows what holds a port.
- **A `make up` Keycloak started before the realm changed.** That Keycloak keeps its realm in the
  volume `huron_keycloak-data`, and `--import-realm` skips a realm that already exists, so it lacks
  the `huron-web` client, the `admin` and `user` accounts and the device flow fix. Recreate only that
  volume; the database volume `huron_postgres-data` and its data stay:

  ```bash
  docker compose rm --stop --force keycloak
  docker volume rm huron_keycloak-data
  make up
  ```

  The new Keycloak signs with new keys. If `make api` is running, restart it (Ctrl-C, then
  `make api`) or wait a minute before signing in.

- **`make app` fails at the seed, or demo data is missing.** The web starts only after the seed
  succeeds; read why it failed with `docker compose -f docker-compose.app.yml logs seed`. When it
  says `Keycloak issued no ID token for alice: …`, the seed stopped at its first request, before it
  wrote anything, and your data is intact: find the cause in
  `docker compose -f docker-compose.app.yml logs keycloak`, then run `make app-down` and
  `make app`, which restarts Keycloak. A seed that stopped later, part-way, is not resumed: the
  next run finds the first organization and changes nothing. Fix the cause, then run
  `make app-reset`, which deletes the stack's database, and `make app`. Every user the fixture
  names as a creator must be a realm user with the password `password`.
- **The web says "That sign-in expired or was already used".** Open the web at
  http://localhost:3000, not http://127.0.0.1:3000, and sign in again.
- **The web says "Huron didn't accept this sign-in", or the CLI says
  `company token was signed by an unknown key`.** Use `http://127.0.0.1:8081` for Keycloak, never
  `localhost`, and read `make app-logs`. After a restart of Keycloak alone, or after you recreated
  its `make up` volume (see above), the API takes up to a minute to fetch Keycloak's new signing
  keys. Until then the web refuses the sign-in and the CLI stops with
  `error: company token was signed by an unknown key [TOKEN_INVALID]`: sign in again a minute
  later, or restart the API (`docker compose -f docker-compose.app.yml restart api`, or Ctrl-C and
  `make api`).
- **The CLI is signed in as the wrong account.** Keycloak signed it in with your browser's session;
  sign out of Keycloak (see [The CLI on the host](#the-cli-on-the-host)) and log in again.
- **`huron check` stops with `error: internal error [INTERNAL]`.** The seeded
  `heliophysics.solar-wind.wind.swe-2023` trips a known API bug (see
  [The seeded data](#the-seeded-data)); check the other catalogs with `--catalog`.
- **Linux and Docker Desktop.** Both work the same way: ports published on 127.0.0.1 of the host reach
  the containers, and inside them 127.0.0.1 is the shared namespace. Docker Desktop must share the
  repository's folder for the bind mounts (`scripts/`, `docker/seed/`, `web/e2e/support/`); its
  default shares your home directory. On Windows, clone the repository inside WSL 2. With a Docker
  Engine older than 25, `make app` stops with `can't set healthcheck.start_interval as feature
  require Docker Engine v25 or later`: update Docker.

`scripts/e2e.sh`, the manual pre-release check, runs the stack's backend as its own compose project
`huron-e2e`, with an empty database and its own API image `huron-e2e-api:dev`, and removes the
project and the image afterwards; stop `make app` first.

## Documentation

- [Architecture](docs/architecture.md)
- [Operator guide](docs/operator.md)
- [User guide](docs/user-guide.md)
- [Web app](web/README.md)
- [Web design](docs/web-design.md)
- [API error codes](docs/api-errors.md)
- [Architecture decision records](docs/adr/)
- [Implementation plan](IMPLEMENTATION_PLAN.md)

## Development

`make gate` runs the full validation gate: ruff, mypy, ty, import-linter, the unit tier with coverage,
radon, complexipy and the schema-map check. `make test-contract` and `make test-integration` run the
PostgreSQL-backed tiers.
