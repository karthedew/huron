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
service; `huron adm check` reports where disk and catalog disagree.

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

`make migrate` and `make api` read `dev.env`, which holds only the database URL, the API URL and
`HURON_CONFIG_FILE`; through it the API reads every other setting from
[the development configuration](#the-development-configuration) in `huron.dev.yaml`. `make api`
restarts when that file changes. Never load `dev.env` into the CLI's environment: the CLI reads
`HURON_API_URL` and `HURON_ISSUER` as its own settings. The accounts are those in [Accounts](#accounts) below. `make up`
and `make app` use the same ports, so only one runs at a time: `make up` first stops the `make app`
stack and `make app` first stops this one, and `make down` stops both. None of them deletes data.
Unlike `make app`, which binds 127.0.0.1 only, this stack's PostgreSQL and Keycloak, with their
development passwords, and its group directory listen on every network interface: run it on a
machine and network you trust. To run the web against this stack, follow
[web/README.md](web/README.md#against-the-development-stack-make-up).

## Run everything in Docker

`make app` builds and starts the whole application in Docker
([docker-compose.app.yml](docker-compose.app.yml)): PostgreSQL with its own volume, the migrations,
the API, the development group directory, Keycloak as a stand-in for the company OIDC provider, the
web app, and a one-shot seed that loads the demo data of the web's end-to-end fixture. The API reads
its organizations from [`huron.dev.yaml`](#the-development-configuration). It returns once every
service is healthy and the seed has run.

Prerequisites: Docker Engine 25 or newer with the Compose plugin on Linux, or Docker Desktop 4.27 or
newer on macOS or Windows; ports 3000, 5432, 8080, 8081 and 8082 free on 127.0.0.1; `uv` for the
CLI. The first run pulls the images and builds the API and web images, which takes a few minutes.

```bash
make app
make demo-noaa    # optional: the NOAA Planetary K-index catalog in the organization noaa
```

`make demo-noaa` needs the running stack; see [The NOAA demo](#the-noaa-demo) below.

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

### The development configuration

`huron.dev.yaml` in the repository root is the service configuration of both stacks: `make app`
mounts it read-only into the API container as `/etc/huron/huron.yaml`, and `make api` reads it
through `dev.env`. It is the one file to edit: its keys are the API's settings
(`src/huron/applications/api/settings.py`) in lower case without the `HURON_` prefix, such as
`instance_id`, `issuer` and `platform_admin_group`, plus `organizations`. A `HURON_*` environment
variable still wins over the file; `dev.env` sets none of these, only the database URL, which stays
in the environment. It declares the three development organizations, all under the root
`/data1/huron`, each with the LDAP groups of its organization-wide roles:

```yaml
organizations:
  - name: helio
    display_name: Heliophysics Division
    groups:
      org_admin: [helio-org-admins]
      catalog_admin: [helio-catalog-admins]
      contributor: [helio-contributors]
      reader: [helio-readers]
    root: /data1/huron
  - {name: geo, display_name: Earth Science, groups: {org_admin: [geo-org-admins], reader: [geo-readers]}, root: /data1/huron}
  - {name: noaa, display_name: NOAA, groups: {org_admin: [noaa-org-admins], reader: [noaa-readers]}, root: /data1/huron}
```

The `catalog_admin`, `contributor` and `reader` groups hold their role in every catalog of the
organization, the seeded ones and any you create; a grant on one catalog adds groups to that catalog
and cannot take an inherited one away. `huron get grants --catalog <catalog>` shows each group's
source.

So `helio` lives at `/data1/huron/helio`, `geo` at `/data1/huron/geo` and `noaa` at
`/data1/huron/noaa`. The seed loads demo catalogs into `helio` and `geo` only; `noaa` starts empty
until `make demo-noaa` loads its catalog.
At startup the API
creates the declared organizations that are missing, updates their display names and descriptions
and makes each role's groups under `groups` exactly their organization-wide groups (an unknown role
key, or the old `admin_groups`, stops the API at startup); it never deletes an organization you remove
from the file, it only logs a warning. While the file declares organizations, `huron create org`
is refused: add an entry here instead. To change the configuration, edit the file and run
`make app` again, which recreates the API with the new file (or restart `make api`). A key the API
does not know, such as `organisations:`, a key given twice, `organizations:` with every entry
commented out (write `organizations: []` for none) or two entries with the same name stop the API
at startup;
`make app-logs` shows why. [docs/operator.md](docs/operator.md#configuration) describes every field.

### Accounts

Users of the realm `company` ([scripts/keycloak/company-realm.json](scripts/keycloak/company-realm.json));
their LDAP groups come from [scripts/dev-groups.yaml](scripts/dev-groups.yaml).

| User | Password | Groups | Role in the demo data |
| --- | --- | --- | --- |
| `admin` | `admin` | `huron-platform-admins` | Platform admin: sees and manages everything |
| `user` | `user` | `helio-contributors`, `geo-readers`, `noaa-readers` | Scientist: contributor in every `helio` catalog, reader of every `geo` and `noaa` catalog |
| `alice` | `password` | `huron-platform-admins` | Platform admin; a creator in the demo data |
| `bob` | `password` | `helio-org-admins` | Org admin of `helio` |
| `carol` | `password` | `helio-catalog-admins` | Catalog admin of every `helio` catalog |
| `dave` | `password` | `helio-contributors`, `geo-readers` | Contributor in every `helio` catalog, reader of every `geo` catalog |
| `erin` | `password` | `helio-readers` | Reader of every `helio` catalog |

The Keycloak admin console's `admin` / `admin` is a different account in the `master` realm: it
administers Keycloak, not Huron.

### Signing in to the web

Open http://localhost:3000 and choose **Sign in with your company account**. Keycloak's login form
opens on 127.0.0.1:8081; sign in as `admin` or `user`. **Sign out** in the account menu ends the web
session and, once you confirm on Keycloak's page, the Keycloak session too.

### The CLI on the host

The CLI signs in to the same Keycloak and uses the same API. Run it in the repository root, where
`uv run` finds the project. Plain directories stand in for the NFS exports: the root that
`huron.dev.yaml` names, `/data1/huron`, must exist and be writable by you, and
`acl_backend none` applies modes without POSIX ACLs. Creating them needs root once; to avoid that,
point the `root:` entries of `huron.dev.yaml` at absolute directories you own, such as
`/home/you/huron/data1`, and run `make app` again.

```bash
uv sync
sudo mkdir -p /data1/huron
sudo chown "$(id -un):$(id -gn)" /data1/huron
uv run huron config set api_url http://127.0.0.1:8080
uv run huron config set issuer http://127.0.0.1:8081/realms/company
uv run huron config set acl_backend none
uv run huron login --device    # open the printed link, sign in as admin, then grant access
uv run huron whoami
uv run huron adm provision-orgs --dry-run   # what it would create
uv run huron adm provision-orgs             # /data1/huron/helio and /data1/huron/geo, with markers
uv run huron adm verify-mounts              # both organizations ok
```

`provision-orgs` writes a marker `.huron` into each organization directory with the stack's
instance id (`instance_id` in `huron.dev.yaml`, also at http://127.0.0.1:8080/healthz) and the
organization's name; the CLI refuses to write under an organization whose marker does not match.
An organization without a `root` lives under the CLI's `mount_prefix` instead (default
`/projects/huron`, `huron config set mount_prefix <dir>`), marked once with `scripts/init-root.sh`
when it is not declared.

`huron login --browser` uses the loopback flow instead: it opens Keycloak in a browser on this
machine and receives the answer on `http://127.0.0.1:<random port>/callback`. Plain `huron login`
takes the browser when `DISPLAY` is set and the device flow otherwise.

Keycloak remembers who signed in last in a browser, through the web or the CLI. While that session
lasts, `huron login` signs the CLI in as that account without showing the form, and the device
flow's **Grant Access to huron-cli** page does not say who it is. To sign in as someone else, first
end that session: open http://127.0.0.1:8081/realms/company/protocol/openid-connect/logout and
choose **Logout**, or sign out of the web and confirm on Keycloak's page. A private window works
too. `uv run huron whoami` shows who the CLI is.

The web shows share paths under each organization's root from the API, such as
`/data1/huron/helio/…`, the same paths the CLI writes to. Only for an organization without a root
does it fall back to its mount prefix, `/projects/huron`; to match a different CLI `mount_prefix`,
start the stack with `HURON_WEB_MOUNT_PREFIX=<dir> make app`. Every `make app` without it goes back
to `/projects/huron`.

### The seeded data

The seed, `docker/seed/run.mjs`, loads the fixture in `web/e2e/support/fixture.mjs`. The
organizations, `helio` and `geo`, and their organization-wide role groups come from `huron.dev.yaml`,
not from the seed: with organizations declared, it creates none and grants no Org Admins. It loads the
fixture's catalogs of the declared organizations, their nested namespaces and collections, their
per-catalog grants (which overlap the organization-wide groups and add to them) and an organization
schema; the fixture's organizations the file does not declare, `astro` and `planetary`, are skipped
with their catalogs. It runs on every `make app`, creates each fixture catalog that is still
missing, and changes nothing once its data is there.

The seed records catalog entries only. No directory and no file bytes exist on any share: the files
the web lists are records without bytes on disk. `uv run huron adm check --catalog geoscience` therefore
reports the seeded namespaces and collections missing from your share (`namespace_dir_missing`,
`collection_dir_missing`) and exits 1.

On `heliophysics`, and without `--catalog`, `huron adm check` stops with `error: internal error
[INTERNAL]` instead. That is a known API bug, not your setup: the metadata of the seeded collection
`heliophysics.solar-wind.wind.swe-2023` holds the number `-1e31`, which the API reads back from
PostgreSQL as an integer too large for its canonical JSON, so it cannot render that collection's
`metadata.json`. The web's `metadata.json` page of that collection fails the same way.

Before the CLI writes below a seeded namespace, a platform admin creates its directories on your
share; re-running a create command repairs a missing directory. Signed in as `admin`, after
`huron adm provision-orgs` (above):

```bash
uv run huron create catalog heliophysics --org helio
uv run huron create namespace heliophysics.solar-wind.ace --parents
```

Then sign out of Keycloak as described above, sign the CLI in as `user`, and make a collection with
one file. Both show in the web at once, at
http://localhost:3000/catalogs/heliophysics/collections/solar-wind.ace.my-run:

```bash
uv run huron login --device    # sign in as user
uv run huron whoami            # subject user
uv run huron catalog heliophysics
work="$(mktemp -d)"            # the metadata and the file, outside the repository
printf '{"title": "My run", "description": "Made with the CLI"}\n' > "$work/meta.json"
printf 'time,value\n2024-01-01T00:00:00Z,1.5\n' > "$work/results.csv"
uv run huron create collection solar-wind.ace.my-run --metadata "$work/meta.json"
uv run huron add "$work/results.csv"
uv run huron push -m "First results"
```

`push` copies `results.csv` to `/data1/huron/helio/heliophysics/solar-wind/ace/my-run/`.

### The NOAA demo

`make demo-noaa` loads real data into the running stack: the catalog `planetary` in the
organization `noaa`, with a year of NOAA SWPC Planetary K-index files stored as raw files
([examples/noaa](examples/noaa/README.md) describes the data and the layout). It runs
[scripts/demo-noaa.sh](scripts/demo-noaa.sh), which:

1. checks that the API answers http://127.0.0.1:8080/readyz, or stops with `start it with: make app`;
2. gives the CLI a configuration and state of its own under `~/.cache/huron/demo-noaa/`
   (`$XDG_CACHE_HOME/huron/demo-noaa/` when that is set), so your own CLI configuration and
   sign-in are left alone, and signs it in as `admin` without a browser;
3. downloads the raw files from NOAA into `~/.cache/huron/demo-noaa/raw` the first time (about
   90 s) and reuses them afterwards;
4. runs `huron adm provision-orgs`, then `examples/noaa/load.sh`, which creates the catalog, its
   namespaces and collections and pushes the files to `/data1/huron/noaa/planetary/…`; it grants
   nothing, since `noaa`'s `groups.reader` in `huron.dev.yaml` makes `noaa-readers` a reader of
   every `noaa` catalog;
5. prints `huron --catalog planetary tree` and the files on disk.

It needs `/data1/huron` writable by you, like the rest of [the CLI on the host](#the-cli-on-the-host).
Running it again changes nothing. `NOAA_REFRESH=1 make demo-noaa` downloads again and pushes only
what changed (the current quarter, which NOAA reissues daily, and a new dated snapshot);
`NOAA_RAW=<dir> make demo-noaa` loads an existing `examples/noaa/fetch.py --out <dir>` download
instead. In the web, open http://localhost:3000/catalogs/planetary as `admin`, or as `user`, a
member of `noaa-readers`.

### Stopping and resetting

```bash
make app-logs    # follow the logs
make app-down    # stop; the database stays in the volume huron-app_postgres-data
make app         # start again: the data is still there and the seed changes nothing
make app-reset   # stop and delete the database; the next make app seeds again
make down        # stop this stack and the make up stack; the data of both stays
```

For a fresh database with the demo data, the seed's and NOAA's:

```bash
make app-reset && make app && make demo-noaa
```

`make app-reset` deletes the database, not `/data1/huron`: the directories and files of an earlier
`make demo-noaa` stay there, and the next `make demo-noaa` records them again, reusing the
directories and replacing each file at its path. Nothing under `/data1/huron` is deleted.

Keycloak keeps nothing between starts: it imports `scripts/keycloak/company-realm.json` whenever it
starts, so realm edits apply after `make app-down` and `make app`, and every restart ends the Keycloak
sessions. Huron tokens the CLI holds stay valid until they expire. The web keeps its sessions in
memory, so restarting it signs everyone out of the web. The images `huron-app-api:dev` and
`huron-app-web:dev` stay until you remove them with `docker image rm`.

### Troubleshooting

- **A port is in use.** When `make up` (5432, 8081), `make api` (8080), the group directory (8082)
  or another program holds one of the stack's ports, `make app` stops with an error that names the
  port, on Linux `failed to bind port 127.0.0.1:<port>/tcp: … bind: address already in use`.
  `make app` stops the `make up` stack itself; stop `make api` and the group directory with Ctrl-C
  in their terminals. When another Docker project publishes the port, such as a running `scripts/e2e.sh`,
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
  `make app`, which restarts Keycloak. A seed that stopped later, part-way, creates
  the catalogs still missing on the next run but does not complete one it created only part-way: fix
  the cause, then run `make app-reset`, which deletes the stack's database, and `make app`. Every user the fixture
  names as a creator must be a realm user with the password `password`.
- **The API does not start after an edit of `huron.dev.yaml`.** `make app` stops with the API
  unhealthy, or `make api` exits. Read the reason with `make app-logs` (or in the `make api`
  terminal): a key the settings do not know (a typo such as `organisations:`), two organizations
  with the same name, a name that breaks the naming rules, or a `root` that is not an absolute path
  without `..`. Fix the file and run `make app` again.
- **`huron adm verify-mounts` says `missing` or `no marker`.** The root does not exist, or
  `huron adm provision-orgs` has not run since you changed it; see
  [The CLI on the host](#the-cli-on-the-host).
- **`huron adm verify-mounts` lists organizations as `undeclared`.** They are in the stack's
  database but not in `huron.dev.yaml`: removed from the file, or left from a seed of an older,
  unmanaged stack (such as `astro` and `planetary`). They do not fail `verify-mounts`, and
  `huron adm check` reports them as `org_undeclared` warnings. Declare them in the file again, or
  run `make app-reset` and `make app` for a database with the declared organizations only.
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
- **`huron adm check` stops with `error: internal error [INTERNAL]`.** The seeded
  `heliophysics.solar-wind.wind.swe-2023` trips a known API bug (see
  [The seeded data](#the-seeded-data)); check the other catalogs with `--catalog`.
- **Linux and Docker Desktop.** Both work the same way: ports published on 127.0.0.1 of the host reach
  the containers, and inside them 127.0.0.1 is the shared namespace. Docker Desktop must share the
  repository's folder for the bind mounts (`huron.dev.yaml`, `scripts/`, `docker/seed/`,
  `web/e2e/support/`); its default shares your home directory. On Windows, clone the repository
  inside WSL 2. With a Docker Engine older than 25, `make app` stops with `can't set healthcheck.start_interval as feature
  require Docker Engine v25 or later`: update Docker.

`scripts/e2e.sh`, the manual pre-release check, runs the stack's backend as its own compose project
`huron-e2e`, with an empty database and its own API image `huron-e2e-api:dev`, and removes the
project and the image afterwards; stop both stacks first with `make down`.

## Documentation

The guides below and the CLI reference are also a website: the web serves it at `/docs`
(http://localhost:3000/docs/ under `make app`), readable without signing in, with search. Its
source is `web/docs-site/`. The prose stays in `docs/*.md` and `docs/concepts/*.md`, from which
the site's pages are generated, and the CLI reference is generated from the CLI itself:

```bash
uv run python scripts/cli_reference.py    # after changing a command; make gate runs it with --check
cd web && npm run docs:install            # once
npm run docs:build                        # rebuild web/docs-site/dist, which the web serves
npm run docs:dev                          # or preview the site alone at http://localhost:4321/docs/
```

`make app` builds the site into the web image. [web/README.md](web/README.md#the-documentation-at-docs)
has the details.

- [How Huron works](docs/concepts/how-huron-works.md) and the other concept guides in
  [docs/concepts/](docs/concepts/)
- [Architecture](docs/architecture.md)
- [Operator guide](docs/operator.md)
- [Deploying: Helm chart and Kustomize base](deploy/README.md)
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
