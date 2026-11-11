# Architecture

Huron catalogs raw scientific data on an NFS share and controls who can read and write it. The
service records organizations, catalogs, namespaces, collections, files, grants and the audit log
in PostgreSQL. It never opens the share. The `huron` CLI runs on the machines that mount the share,
and it is the only part that writes files and directories there. The web is a read-only view of
the catalog in a browser. This page describes each part, the rules between the parts, where each
part keeps its state, and how the parts work together. The [glossary](user-guide.md#glossary)
defines the Huron terms.

## Components

<figure class="architecture-components">
  <picture>
    <source media="(max-width: 89.99rem)" srcset="/docs/diagrams/components-compact.svg" width="360" height="920" />
    <img src="/docs/diagrams/components.svg" width="720" height="584" alt="Clients call the API, which stores records in PostgreSQL. The browser uses the web. Only the CLI accesses NFS. The API checks company tokens and reads groups." />
  </picture>
  <figcaption>Catalog requests, identity checks and file access follow separate paths.</figcaption>
</figure>

The CLI and web sign in with the company OIDC provider. Each exchanges its company ID token at the
API for a Huron token. The API checks the ID token and calls the group directory at each exchange.
The web then reads the catalog through the API. Only the CLI touches the share.

| Part | Runs on | Does |
| --- | --- | --- |
| `huron-api` | OpenShift, from the Helm chart or the kustomize base | Exchanges company ID tokens for Huron tokens. Records the catalog, the schema registry, the grants and the audit log. Has no access to the share. |
| PostgreSQL | OpenShift or a managed server | Holds the schema `huron`, which is the catalog of record. |
| `huron` CLI | The machines that mount the share | Signs the user in, browses, creates directories with their ACLs, copies files onto the share, commits them, and checks for drift. |
| `huron-web` | A Node.js server, next to the API | Signs people in with the company OIDC provider and shows the catalog. It only reads. It also serves this documentation at `/docs`. |
| Company OIDC provider | External | Issues the company ID token that the CLI and the web exchange. |
| Group directory | External | Answers `GET <group_directory_url>/users/{username}/groups` with `{"groups": [...]}`. |
| NFS share | External | One or more exports that hold the directory of each organization. |

## The service

`huron-api` is a FastAPI application (`src/huron/applications/api/`). Uvicorn starts it as
`huron.applications.api.main:app` on port 8080. The service is asynchronous: it uses asyncpg for
PostgreSQL and `httpx.AsyncClient` for the OIDC provider and the group directory.

The routes are these:

- `/api/v1/...`: the catalog, the grants, the schemas, the commits, search and the token exchange.
- `/healthz`: liveness. It reports the `instance_id` that the markers on the share must name,
  `organizations_managed`, `uploads_url`, `service_user` and `upload_hook_timeout`.
- `/readyz`: readiness. It answers 503 until the database and the signing keys are usable. With
  `lake_path`, the check `lake` also needs a `.tus-uploads` directory that the API can write.
  The API also makes a hard link from the object area into each declared organization directory,
  then removes it. A second API process that finds the writer lock held writes nothing. Its
  check `lake` needs only the `.tus-uploads` directory, and it serves reads only.
- `/.well-known/openid-configuration` and `/jwks.json`: discovery documents, so that other systems
  can check Huron tokens.

Every error leaves the service as an RFC 9457 problem document with a stable code.
[API error codes](api-errors.md) lists the codes.

At startup the service builds one runtime object (`runtime.py`). The runtime connects the store
and runs the bootstrap. It then composes the lake operations and makes the token checker and the
group directory client.

The bootstrap (`core/lake/bootstrap.py`) runs in one transaction under an advisory lock. Thus
replicas that start together run it one after the other. It does these steps:

1. It seeds the `huron-base` schema.
2. It seeds the Platform Admin grant for `platform_admin_group`.
3. It makes sure that a current signing key exists.
4. It reconciles the declared organizations (see [Configuration](#configuration)).

A second run with the same configuration writes nothing.

The service has three packages in `core`:

- `core.lake` is the domain. It has one package for each area: organizations, catalogs,
  namespaces, collections, files, schemas and audit. Each operation takes the actor and checks the
  privilege of the actor in the same transaction as the change.
- `core.security` has two parts. `broker` checks company ID tokens, gets the groups of the user,
  and issues and checks Huron tokens. `rbac` holds the five roles, their privileges and the
  `Authorizer`, which maps the groups of an actor to roles through the current grants.
- `core.metastore` holds the adapters of the lake ports. `PostgresStore` uses asyncpg and
  hand-written SQL. `MemoryStore` keeps the same data in memory. The setting `store` (`postgres`
  or `memory`) selects one. The unit tests and the web's end-to-end stack use the memory store.

Every store passes the same contract test suite, against PostgreSQL and against the memory fake.

## Requests and authorization

Each request to `/api/v1` carries `Authorization: Bearer <Huron token>`, except the token
exchange. The service checks the token with its key ring. It then makes an actor from the
subject, the name and the groups of the token. The lake operation then asks the `Authorizer`
for the roles of those groups, from the grants table as it is now.

These rules follow from that design:

- A revoked grant applies to the next request.
- A change to LDAP membership applies at the next sign-in, because the token carries the groups
  from the time of the exchange.
- An object that the actor cannot see answers 404, not 403.

The service reloads the key ring at most every `key_cache_seconds` (60 by default). Thus a key
rotation reaches every replica within that time. [Who has access](user-guide.md#who-has-access)
describes the roles from the view of a user.

## The CLI

The CLI (`src/huron/applications/cli/`) is a synchronous Typer application. It talks to the API
over HTTPS with `httpx`. It talks to the share through the local mount, with the package
`core.storage`:

- `layout.py` maps identifiers to paths and paths to identifiers.
- `aclplan.py` computes the mode and POSIX ACL of each kind of directory from the effective
  groups of the catalog.
- `posix.py` (`PosixStorage`) does the disk operations. `memory.py` is a fake with the same
  contract, for tests.
- `marker.py` reads and checks the `.huron` marker files.
- `check.py` compares what the service records with what is on the share, for `huron adm check`.

All disk access goes through `Mount` (`cli/mount.py`). `Mount` gets the root of the organization
from the API and resolves each absolute path. It checks the marker of the organization before it
gives a path to a command. The marker must name the `instance_id` that `GET /healthz` reports. A
per-organization marker must also name the organization. Thus a CLI that points at another
service writes nothing, and the CLI writes nothing into an export at the wrong root.

The CLI creates catalog and namespace directories after the service records them. For a collection,
the service reserves a draft first. The CLI creates its directory before the service activates it.
All these directories belong to the user who runs the CLI. The storage admin prepares the organization
directories with [`huron adm provision-orgs`](/docs/reference/cli/adm/#huron-adm-provision-orgs).

Enforcement is contain-and-detect. A contributor can write into a collection directory without the
CLI, and the service trusts the sizes and hashes that the CLI reports. `huron adm check` finds the
drift. [Reading `huron adm check`](operator.md#reading-huron-adm-check) explains each finding.

## The web

`huron-web` (`web/`) is a SvelteKit application on Node.js (adapter-node), on port 3000. It is a
backend for the browser: the browser talks only to the SvelteKit server, and the server talks to
the API.

The server keeps each session in its own memory (`web/src/lib/server/sessions.ts`). The browser
holds only an opaque `huron_session` cookie (HttpOnly). The Huron token of the session stays on the
server and never reaches the browser. The server renders each page from its own API calls with the
token of the user. Thus the grants of the API, and its 404 for hidden objects, apply without
change.

The web only reads. Its API client sends GET requests only, apart from the token exchange. Where
the user could make a change, the page shows the `huron` command to run.

One process holds every session, so these limits apply:

- The web runs as one replica, or behind sticky sessions.
- A restart or an out-of-memory kill signs out every user.
- The key that seals the sign-ins in progress is random for each process.

[Deploying the web](operator.md#deploying-the-web) lists its settings. `docs/web-design.md` is the
binding design of the web.

## The docs site

The documentation site is a Starlight (Astro) site in `web/docs-site/`. The web image builds it and
the web serves it at `/docs`, without sign-in. The site has three kinds of pages:

- The concepts and guides come from `docs/`. The script `web/docs-site/scripts/sync.mjs` generates their
  pages at each build and rewrites the links between them to `/docs/...` addresses.
- The CLI reference comes from the help of the real command tree. `scripts/cli_reference.py`
  generates it, and the gate fails when the committed pages are out of date.
- The start pages (`index.mdx` and `getting-started.md`) are hand-written.

## Dependency rules

The packages of `src/huron` are `pkg` (generic code), `schema` (JSON Schema documents, the
validator and the naming rules), `core` and `applications`. Import-linter contracts in
`pyproject.toml` enforce these rules, and `uv run lint-imports` in the gate checks them:

1. `huron.pkg` imports no other `huron` package.
2. `huron.schema` imports only `huron.pkg`.
3. `core.security` does not import `core.lake`, `core.metastore`, `core.storage` or
   `applications`.
4. `core.lake` does not import `core.metastore`, `core.storage` or `applications`.
5. Only `applications` import `core.metastore`.
6. The API does not import the CLI or `core.storage`.
7. The CLI does not import the API, `core.metastore` or `core.security.broker`.
8. The `models` module of a lake area does not import the operation modules of any area.

```text
  applications.api ---> core.lake, core.security, core.metastore
  applications.cli ---> core.storage, core.lake models, core.security.rbac

  core.metastore   ---> core.lake, core.security
  core.storage     ---> core.lake models, core.security.rbac
  core.lake        ---> core.security.rbac
  core.security    ---> schema, pkg
  schema           ---> pkg
```

Rule 6 is the reason that the API cannot touch the share. Rule 7 is the reason that the CLI uses
the database only through the API.

## Where state lives

| State | Where | Notes |
| --- | --- | --- |
| The catalog, recorded files, commits, schemas, grants, the audit log and the signing keys | PostgreSQL, schema `huron` | The catalog of record. Back it up. |
| File bytes, `metadata.json` sidecars and `.huron` markers | The share | Only the CLI writes here. Huron keeps no file versions. |
| The service configuration and the declared organizations | The file that `HURON_CONFIG_FILE` names, and `HURON_*` variables | Roots are configuration, not database rows. |
| The CLI configuration and the current organization, catalog and collection | `$XDG_CONFIG_HOME/huron/config.yaml` (mode 0600) | `huron config` shows and sets the keys. `huron org`, `huron catalog` and `huron checkout` set the current values. |
| Tokens and working copies | `$XDG_STATE_HOME/huron/` (mode 0700) | See below. |
| Web sessions | The memory of the web process | Lost on restart. |

The default of `$XDG_CONFIG_HOME` is `~/.config`, and the default of `$XDG_STATE_HOME` is
`~/.local/state`. The state directory of the CLI holds these files:

- `tokens.json` (mode 0600): the Huron token, its expiry and the company refresh token.
- `state.lock`: the state lock. A command that changes the local state holds it.
- `collections/<collection id>/working.json`: the working copy. It holds a format version, the
  version of the collection, the stage, the upload attempts and the pending commit.
- `collections/<collection id>/push.lock`: the lock that a push of that working copy holds.
- `collections/<collection id>/metadata.draft.json`: the metadata draft, when there is one.

The CLI refuses to read `tokens.json` when another user owns it, or when its mode gives any access
to the group or to others.

## Sign-in and the token exchange

Huron is the authentication broker. A client gets a company ID token from the company OIDC
provider and exchanges it at `POST /api/v1/auth/exchange` for a Huron token. Clients then send
only the Huron token.

```text
  CLI or web server          huron-api                 external
  -----------------          ---------                 --------
  company ID token ----> 1. check the ID token ---> OIDC provider (JWKS)
                         2. get the groups ------> group directory
                         3. issue a Huron token
  Huron token <--------- 4. log broker.exchange
```

The service does these steps in `TokenExchange` (`core/security/broker/exchange.py`):

1. It checks the signature of the ID token against the keys that the company issuer publishes.
   It also checks the issuer and the audience (`company_issuer`, `company_audience`).
2. It gets the LDAP groups of the user from the group directory.
3. It issues a Huron token, signed with ES256, that carries the subject, the name and the groups.
   The token is valid for `token_ttl_seconds` (8 hours by default).
4. It writes the `broker.exchange` log line.

The CLI gets the ID token with the device flow or with a loopback flow that sends PKCE (S256). It
stores the Huron token in `tokens.json`. When less than five minutes of the token remain, the CLI
uses the company refresh token. It gets a new ID token and exchanges it again.
[Logging in](user-guide.md#logging-in) shows the commands.

The web server uses the authorization code flow with PKCE (S256). It seals the sign-in in progress
into a short-lived cookie. After the callback, the server exchanges the ID token and keeps the
Huron token in a new session.

## A push

A push uploads the stage of the current collection through tusd and records it in one commit.
The code is `push` in `cli/sync.py` and the tus client in `cli/uploads.py`.

```text
  huron push
    1. lock the working copy
    2. GET  /api/v1/collections/{id}       stop if the version is not the base
    3. POST .../commits?dry_run=true       the service checks, changes nothing
    4. POST <uploads_url>, PATCH ...       one upload attempt for each add
    5. POST .../commits                    request_id, base_version, adds, removes
    6. GET  /api/v1/commit-requests/{id}   only after a 202
    7. empty the stage, record the new version
```

1. The CLI locks the working copy, so that two pushes of one working copy cannot run together.
2. The CLI reads the collection. When its version is not the version of the working copy, the push
   stops with `BASE_VERSION_CONFLICT`. The push also stops when the collection is a draft.
3. The CLI sends the commit as a dry run, without a request ID. An add carries its size, and an
   add that an earlier push already uploaded also carries its SHA-256 and its upload ID. The
   service checks the right to write files, a pending commit, the base version and the paths, as
   for a real commit, and changes nothing. A refusal stops the push before the CLI sends a byte.
4. For each add, the CLI records a new `attempt_id` in the stage and creates a tus upload with
   that `attempt_id`. The pre-create hook issues the upload ID. The CLI makes the upload address
   from its `uploads_url` and the upload ID, and it sends the bytes in chunks of at most 64 MiB.
   The pre-finish hook seals the upload: the API copies the bytes into the object area of the
   organization and measures the copy. The answer to the last chunk says `ready`, or `sealing`
   when the seal takes more than 20 seconds. Some answers do not say `ready`: `sealing`, a 500,
   502 or 504, or no answer in time. After such an answer, the CLI reads the upload attempt every
   5 seconds until it is `ready` or ended, for at most `upload_hook_timeout` (from
   `GET /healthz`). An upload that is still not sealed then stops the push, and the stage keeps
   its attempt for the next push.
5. The CLI sends the commit with a new `request_id`, the `base_version`, the adds (path, size,
   SHA-256 and upload ID), the removals, the host name and the message. The service accepts the
   request, publishes each entry on the lake, then records the files, the version and the audit
   record in one transaction.
6. The service answers 200 when the commit succeeded. A commit that does not end within 5
   seconds gets 202 and the address of the state of the request. The CLI then reads that state
   every 5 seconds for at most 600 seconds. A request that is rejected, blocked or abandoned, or
   that is still accepted at the end of the wait, stops the push with a message.
7. The CLI empties the stage and records the new version in the working copy.

When the commit request fails without a problem document, the CLI reads the collection again. If
the version increased and the service recorded each added file with its hash, the CLI accepts the
commit as done.

The dry run and the real commit use separate transactions. The dry run does not reserve the
version while the CLI uploads files. Another change can make the real commit fail. The uploads of
such a push stay `ready`, and the stage keeps them for the next push.

A repeated push does not send a file again when its upload attempt is `ready` and the file did not
change. [Staging and pushing files](user-guide.md#staging-and-pushing-files) and
[`huron push`](/docs/reference/cli/push/) describe the commands.

## Configuration

The service reads its settings from `HURON_*` environment variables and from an optional YAML file
that `HURON_CONFIG_FILE` names (`applications/api/settings.py`). The order of precedence is this:

1. An environment variable.
2. The file.
3. The default.

The file has the same keys as the settings, in lower case without the prefix, plus
`organizations`. The service refuses to start for each of these errors:

- The file is missing.
- The file has an unknown key, or a key two times.
- The file has an `organizations` key without a list.

The service also refuses to start for two organizations with the same name.

Keep `HURON_DATABASE_URL` in the environment, from a Secret. `HURON_ORGANIZATIONS`, a JSON list,
replaces the list of the file.

An `organizations` key, also an empty list, puts the service in managed mode. At each start, the
bootstrap makes the database agree with the list:

- It creates the declared organizations that are missing.
- It updates a changed `display_name` or `description`.
- It sets the groups of the four organization-wide roles to exactly the declared `groups`.

The bootstrap never deletes an organization. An organization that the list no longer declares
stays in the database, and the service logs a warning. In managed mode, the API refuses to create
organizations, to delete a declared organization and to change its organization-wide role groups.
Without the key, the service is in unmanaged mode, and platform admins create organizations with
`huron create org`. [Declared organizations](operator.md#declared-organizations) gives the fields
and the rules. ADR 0007 (`docs/adr/0007-declared-organizations.md`) records the decision.

The CLI has its own configuration, `config.yaml`. Its keys are `api_url`, `issuer`, `client_id`,
`mount_prefix` and `acl_backend`. The variables `HURON_API_URL`, `HURON_ISSUER`, `HURON_CLIENT_ID`
and `HURON_MOUNT_PREFIX` override the file. The web reads only environment variables, such as
`ORIGIN`, `HURON_API_URL` and `HURON_WEB_OIDC_ISSUER`.

## Organizations and their roots

The service configuration can give an organization a `root`. The directory of the organization is
then `<root>/<name>`. Without a root, the directory is `<mount_prefix>/<name>`, where
`mount_prefix` is a setting of the CLI. Below the directory of the organization, the layout is
`<catalog>/<namespace...>/<collection>`.

The service never opens a root. The API reports paths relative to a root, which start with the name
of the organization. It also reports the root: `root` and `path` on an organization, and
`share_root` on its catalogs, namespaces and collections. The CLI and the web join `share_root` and
the relative path. When `share_root` is `null`, they use their own mount prefix.

```text
  organizations:                         on a machine that runs the CLI
    - {name: helio, root: /data1/huron}  -> /data1/huron/helio/heliophysics/...
    - {name: geo,   root: /data1/huron}  -> /data1/huron/geo/geoscience/...
    - {name: astro}  (no root)           -> <mount_prefix>/astro/...
```

[Where your files are](user-guide.md#where-your-files-are) describes the paths for a user.
[The mount prefix, for organizations without a root](operator.md#the-mount-prefix-for-organizations-without-a-root)
describes the marker at the mount prefix.

## Deployment

Huron supports two ways to deploy the service on OpenShift. Both use the API image from
`Containerfile`, both put the service configuration in a ConfigMap at `/etc/huron/huron.yaml`, and
in both the API pod mounts no share.

| | Helm chart `deploy/helm/huron` | Kustomize base `deploy/openshift` |
| --- | --- | --- |
| Service configuration | The value `config`, rendered as `huron.yaml` | `huron.yaml`, through a `configMapGenerator` |
| Migrations | A Job that is a `pre-install,pre-upgrade` hook | The Job `huron-migrate`, which you apply and wait for |
| A changed configuration | A `checksum/config` annotation restarts the API pods | A new ConfigMap name restarts the API pods |
| Exposure | A Route or an Ingress | A Route |
| The web | Optional, off by default | Not included |

Both migration Jobs run `alembic upgrade head`. The revisions are in `migrations/versions/`:
`0001_huron` is the first schema, and `0002_organization_catalog_roles` lets the three catalog
roles have grants at organization scope. The web image comes from `web/Containerfile`, with
`docs/` as the build context `docs`. [Deploying](operator.md#deploying) and
`deploy/README.md` give the steps.

For development, the Makefile starts one of two Docker stacks. They use the same ports, so each
start stops the other stack first.

- `make up` (`docker-compose.yml`) starts PostgreSQL and Keycloak. Then `make migrate` applies the
  migrations, and `make api` runs the API on the host with `dev.env` and `huron.dev.yaml`.
- `make app` (`docker-compose.app.yml`) runs PostgreSQL, the migrations, Keycloak, the group
  directory, the API, a one-time seed and the web. All containers share one network namespace, and
  the ports are on 127.0.0.1 only. The web is at `http://localhost:3000`. The API has no lake, so
  it takes no upload and no commit, and the seeded collections have no files.

`make app` mounts `huron.dev.yaml` into the API and recreates the API when the file changes.
`make down` stops both stacks and keeps their data. `make app-reset` deletes the data of `make app`.

## Logging

The service writes its log to standard output, one line for each event, through structlog
(`applications/api/logs.py`). Each line has a UTC timestamp, the level, the event name, the logger
and the fields. `log_level` (`HURON_LOG_LEVEL`) sets the lowest level. Uvicorn keeps its own access
and startup lines. The service writes these events:

| Event | Level | When |
| --- | --- | --- |
| `bootstrap.organization_created` | INFO | The bootstrap created a declared organization. |
| `bootstrap.organization_updated` | INFO | The bootstrap changed a `display_name` or `description`. |
| `bootstrap.organization_regranted` | INFO | The bootstrap set the organization-wide role groups. |
| `bootstrap.organization_undeclared` | WARNING | The database holds an organization that the configuration does not declare. |
| `broker.exchange` | INFO | A token exchange succeeded. The line has the subject and the group count. |
| `api.unexpected_error` | ERROR | A request failed with an unexpected error. The `request_id` is also in the 500 response. |

[Logging](operator.md#logging) shows example lines.

## Binding design documents

These documents decide the design. When this page and one of them disagree, the document wins.

- `IMPLEMENTATION_PLAN.md`, sections 3 to 9, with their dated amendments: the decisions, the
  architecture, the domain model, the storage layout, the persistence, the API and the CLI.
- `docs/web-design.md`, with its dated amendments: the design of the web.
- `docs/adr/`: the architecture decision records, from NFS-only storage (0001) to declared
  organizations (0007).
- `AGENTS.md`: the package layout, the dependency rules, the code conventions and the gate.
- `docs/openapi.json`: the API contract. The web generates its API types from it.

## Related pages

- [User guide](user-guide.md)
- [Glossary](user-guide.md#glossary)
- [Configuration](operator.md#configuration)
- [Deploying](operator.md#deploying)
- [Deploying the web](operator.md#deploying-the-web)
- [API error codes](api-errors.md)
- [CLI reference](/docs/reference/cli/)
- [How Huron works](concepts/how-huron-works.md) and the other concept pages
- [The push, step by step](concepts/raw-ingest.md#the-push-step-by-step)
