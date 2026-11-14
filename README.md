# Huron

Huron is a catalog and access-control plane for raw scientific data that lives on an NFS share.
Scientists and administrators work through the `huron` command-line tool. A FastAPI service and a
PostgreSQL database hold the catalog of organizations, catalogs, namespaces and collections, their
metadata, the role grants and an audit log.

The service is the one writer of the share, apart from tusd's own files and the provision
commands of the storage admin. These prepare the lake path and the organization directories, and
give the catalog directories their share groups. A push uploads each file over HTTPS through an
upload proxy to tusd. The service seals each upload: it copies the bytes into a private object area and
measures their size and SHA-256 hash. A commit then names the sealed uploads, and the service puts
the files on the share with hard links and renames. Users mount the share read-only, for example
at `/projects/huron`, to read the files. A push does not need the mount.

Huron uses no POSIX ACLs. A catalog can have one share group, a POSIX group whose members read
the catalog directory on the share. Without one, only the service user and the service group read
it. Roles in the service belong to LDAP groups and control the API.
Collection metadata is validated against a schema registry: each catalog is assigned a schema, and
a collection may extend it with an override. Each commit carries the version that it was based on,
so the service refuses a push that is behind until the user pulls. `huron adm check` reports where
the share and the catalog disagree.

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

The API of `make api` holds the lake at `/data1/huron` (`lake_path` in `huron.dev.yaml`). The API
does not start when that directory does not exist, or when it cannot make `.tus-uploads` in it.
So make the directory first, writable by you (see [The CLI on the host](#the-cli-on-the-host)). The
API takes uploads only through the upload proxy and tusd. Start them in a fourth terminal with `make uploads`,
and stop them with `make uploads-down`. They use host networking: nginx listens on port 1080 of
each network interface of your machine, and tusd on `127.0.0.1:1081`. `make app` runs its own tusd
over the same lake, so `make uploads` first stops the `make app` stack, and `make app` first stops
the stack of `make uploads`. Before the first push, prepare the lake with `huron adm provision-orgs`
(see [The CLI on the host](#the-cli-on-the-host)). This stack and `make app` keep separate
databases over the same lake. Read [One lake, two databases](#one-lake-two-databases) before you
change from one stack to the other.

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
the lake preparation, the API, tusd and the upload proxy, the development group directory, Keycloak
as a stand-in for the company OIDC provider, the web app, and a one-shot seed that loads the demo
data of the web's end-to-end fixture. The API reads its organizations from
[`huron.dev.yaml`](#the-development-configuration). It returns once every service is healthy and
the seed has run.

The lake is the directory `/data1/huron` on your machine. `lake-init`, the API and tusd bind it at
the same path. They run as you (`id -u` and `id -g`), so you own each file that they write on it. To use another
directory, set `HURON_LAKE_SOURCE`, `HURON_LAKE_PATH` and `HURON_DEV_CONFIG` (see
[The CLI on the host](#the-cli-on-the-host)). Before the API starts, the one-shot service
`lake-init` runs [scripts/dev-provision.py](scripts/dev-provision.py). It prepares the lake and the
declared organizations with `huron adm provision-orgs --config`.

Prerequisites: Docker Engine 25 or newer with the Compose plugin on Linux, or Docker Desktop 4.27 or
newer on macOS or Windows; ports 1080, 3000, 5432, 8080, 8081 and 8082 free on 127.0.0.1; the
directory `/data1/huron`, writable by you; `uv` for the CLI. The first run pulls the images and
builds the API and web images, which takes a few minutes. The images `tusproject/tusd:v2.10.1`
and `nginx:1.31.8` are not pulled: they must be in the local image cache.

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
| Upload proxy, the `uploads_url` | http://127.0.0.1:1080/files/ |

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
`uv run` finds the project. A plain directory stands in for the NFS export: the lake path and root
that `huron.dev.yaml` names, `/data1/huron`, must exist and be writable by you. Creating it needs
root once. To avoid that, use a directory that you own, such as `/home/you/huron/data1`. Write a
copy of `huron.dev.yaml` with that directory as `lake_path` and as each `root`. Then start the
stack with `HURON_LAKE_SOURCE`, `HURON_LAKE_PATH` and `HURON_DEV_CONFIG` set:
`HURON_LAKE_SOURCE=<dir> HURON_LAKE_PATH=<dir> HURON_DEV_CONFIG=<copy> make app`. Then use that
directory in place of `/data1/huron` below, also as `mount_prefix`. Each later `make app` needs the
three variables again, and `make demo-noaa` needs `HURON_LAKE_PATH=<dir>`. Without them,
`make app` uses `huron.dev.yaml` and the lake `/data1/huron` again, and `make demo-noaa` prepares
`/data1/huron`. Set the variables on the command line of each command. Do not export them: in the
environment of `make api` or of the tests, `HURON_LAKE_PATH` sets `lake_path`.

```bash
uv sync
sudo mkdir -p /data1/huron
sudo chown "$(id -un):$(id -gn)" /data1/huron
uv run huron config set api_url http://127.0.0.1:8080
uv run huron config set issuer http://127.0.0.1:8081/realms/company
uv run huron config set mount_prefix /data1/huron   # the lake path on this machine
uv run huron login --device    # open the printed link, sign in as admin, then grant access
uv run huron whoami
uv run huron adm provision-orgs --dry-run   # what it would change
uv run huron adm provision-orgs             # the lake path and the organizations, with markers
uv run huron adm verify-mounts              # every organization ok
```

`provision-orgs` takes the lake path from `mount_prefix`. It writes a marker `.huron` at the lake
path and into each organization directory, with the stack's instance id (`instance_id` in
`huron.dev.yaml`, also at http://127.0.0.1:8080/healthz). The marker of an organization also names
the organization. The API refuses to write under an organization whose marker does not match. On
`make app`, `lake-init` did this already, and the command changes nothing.

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
`/data1/huron/helio/…`, the same paths that the CLI reads. Only for an organization without a root
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

A commit publishes uploads. The seed of `make app` reads `uploads_url` from the API and sends the
bytes of the fixture's files with tus through the upload proxy and tusd, as the CLI does. Then it
commits them. The API makes the directories of the seeded catalogs, namespaces and collections on
the lake.

Sign out of Keycloak as described above, sign the CLI in as `user`, and make a collection in a
seeded namespace. It shows in the web at once, at
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

`add` stages `results.csv`. `push` uploads it through the upload proxy and tusd, and commits it.
The file is then at
`/data1/huron/helio/heliophysics/solar-wind/ace/my-run/results.csv`.

### The NOAA demo

`make demo-noaa` loads real data into a running stack whose API takes uploads: the catalog
`planetary` in the organization `noaa`, with a year of NOAA SWPC Planetary K-index files stored as
raw files
([examples/noaa](examples/noaa/README.md) describes the data and the layout). It runs
[scripts/demo-noaa.sh](scripts/demo-noaa.sh), which:

1. checks that the API answers http://127.0.0.1:8080/readyz, or stops with `start it with: make app`;
2. gives the CLI a configuration and state of its own under `~/.cache/huron/demo-noaa/`
   (`$XDG_CACHE_HOME/huron/demo-noaa/` when that is set), so your own CLI configuration and
   sign-in are left alone, and signs it in as `admin` without a browser;
3. downloads the raw files from NOAA into `~/.cache/huron/demo-noaa/raw` the first time (about
   90 s) and reuses them afterwards;
4. sets the CLI's `mount_prefix` to the lake path (`HURON_LAKE_PATH`, default `/data1/huron`),
   runs `huron adm provision-orgs`, then `examples/noaa/load.sh`, which creates the catalog, its
   namespaces and collections and pushes the files to `/data1/huron/noaa/planetary/…`; it grants
   nothing, since `noaa`'s `groups.reader` in `huron.dev.yaml` makes `noaa-readers` a reader of
   every `noaa` catalog;
5. prints `huron --catalog planetary tree` and the files on disk.

It needs `/data1/huron` writable by you, like the rest of [the CLI on the host](#the-cli-on-the-host).
Running it again changes nothing: the second run uploads no file and makes no commit. `NOAA_REFRESH=1 make demo-noaa` downloads again and pushes only
what changed (the current quarter, which NOAA reissues daily, and a new dated snapshot);
`NOAA_RAW=<dir> make demo-noaa` loads an existing `examples/noaa/fetch.py --out <dir>` download
instead. In the web, open http://localhost:3000/catalogs/planetary as `admin`, or as `user`, a
member of `noaa-readers`.

### Stopping and resetting

```bash
make app-logs    # follow the logs
make app-down    # stop; the database stays in the volume huron-app_postgres-data
make app         # start again: the data is still there and the seed changes nothing
make app-reset   # stop and delete the database; the lake /data1/huron stays
make down        # stop the stacks of make app, make up and make uploads; their data stays
```

### Start again with an empty database

For a fresh database with the seed's demo data, do these steps:

1. Run `make app-reset`. It stops the stack and deletes the database. It does not change the
   lake `/data1/huron`.
2. Delete the catalog directories in `/data1/huron/helio`, `/data1/huron/geo` and
   `/data1/huron/noaa`. Keep each `.huron` marker and each `.huron-objects` directory. This
   command deletes every other entry of the three organization directories:

   ```bash
   find /data1/huron/helio /data1/huron/geo /data1/huron/noaa -mindepth 1 -maxdepth 1 \
     ! -name .huron ! -name .huron-objects -exec rm -rf {} +
   ```

3. Run `make app`. The seed loads the demo data again.

Step 2 is necessary. The seed and `make demo-noaa` make catalog directories on the lake, and no
row of the new database records them. A create command adopts an existing directory only when it
is empty. Without step 2, the seed stops at its first catalog with `STORAGE_FAILED`, and
`make app` fails.

When `make app` already failed in this way, the database records that first catalog. A seed
leaves out each catalog that exists, so a second seed leaves that catalog incomplete. Do the three
steps again, from step 1.

Step 2 also deletes the catalog directories that the stack of `make up` and `make api` made on the
same lake. See [One lake, two databases](#one-lake-two-databases).

### One lake, two databases

`make app` and the stack of `make up` and `make api` keep separate databases, in the volumes
`huron-app_postgres-data` and `huron_postgres-data`. Both stacks read `huron.dev.yaml`, so both use
the lake `/data1/huron`. `make uploads` binds the same lake.

On one stack, the seed, `make demo-noaa` and the create commands of the CLI make catalog
directories on the lake. The database of the other stack does not record them. A create command
adopts an existing directory only when it is empty. So on the other stack, the seed, the demo or
a create of the same catalog stops at the first such directory with `STORAGE_FAILED` (`… exists
and is not an empty directory`). The CLI then also gives the hint to run `huron adm repair`. Do not
run it for this error: the repair takes the directory with the files of the other stack in it.

Before you change to the other stack, do one of these:

- Delete the catalog directories, as in step 2 of
  [Start again with an empty database](#start-again-with-an-empty-database). Their files are then
  lost. The database of the stack that made them still records them. On that stack,
  `huron adm check` reports the missing directories. `huron adm repair <catalog> --recursive`
  makes the directories again, but not the files: the check then reports each recorded file as
  `file_missing`.
- Give one stack a lake of its own. Write a copy of `huron.dev.yaml` with that directory as
  `lake_path` and as each `root`, and make the directory, writable by you.
  - For `make app`, set `HURON_LAKE_SOURCE`, `HURON_LAKE_PATH` and `HURON_DEV_CONFIG`, as
    [The CLI on the host](#the-cli-on-the-host) shows.
  - For the other stack, run `HURON_CONFIG_FILE=<copy> make api` and
    `HURON_LAKE_SOURCE=<dir> HURON_LAKE_PATH=<dir> make uploads`.
  - On both stacks, set the CLI's `mount_prefix` to the lake of the stack that you use, and run
    `HURON_LAKE_PATH=<dir> make demo-noaa`.

Each database holds its own signing keys. So a Huron token of one stack is not valid on the other
stack: run `huron login` again after the change. The files that one stack leaves in `.tus-uploads`
and `.huron-objects` stay on the lake, because the cleanup of the other stack selects by the rows
of its own database.

Keycloak keeps nothing between starts: it imports `scripts/keycloak/company-realm.json` whenever it
starts, so realm edits apply after `make app-down` and `make app`, and every restart ends the Keycloak
sessions. Huron tokens the CLI holds stay valid until they expire. The web keeps its sessions in
memory, so restarting it signs everyone out of the web. The images `huron-app-api:dev` and
`huron-app-web:dev` stay until you remove them with `docker image rm`.

### Troubleshooting

- **A port is in use.** When `make up` (5432, 8081), `make api` (8080), the group directory (8082),
  `make uploads` (1080) or another program holds one of the stack's ports, `make app` stops with an error that names the
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
  the cause, then do the steps of
  [Start again with an empty database](#start-again-with-an-empty-database). Every user the fixture
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
  do the steps of [Start again with an empty database](#start-again-with-an-empty-database) for a
  database with the declared organizations only.
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
- **Linux and Docker Desktop.** Both work the same way: ports published on 127.0.0.1 of the host reach
  the containers, and inside them 127.0.0.1 is the shared namespace. Docker Desktop must share the
  repository's folder for the bind mounts (`huron.dev.yaml`, `scripts/`, `docker/seed/`,
  `deploy/openshift/`, `web/e2e/support/`), and the lake directory (`/data1/huron`); its default
  shares your home directory. On Windows, clone the repository
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
radon, complexipy, the pyscn dead-code and complexity check, the clone baseline check and the
schema-map check. `make test-contract` and `make test-integration` run the PostgreSQL-backed tiers.
