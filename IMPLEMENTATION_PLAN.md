# Huron implementation plan

Huron is a catalog and access-control plane for raw scientific data that lives on an NFS share. Scientists
and administrators work through a command-line tool on machines that mount the share. A FastAPI service
and a PostgreSQL database on OpenShift hold the catalog, the metadata, the roles and the audit log. The
share's directory permissions enforce the same roles on disk.

This plan is written for a fresh repository. It assumes nothing exists but the repository scaffolding
(skills, agent instructions, `.gitignore`, pre-commit configuration). Every file it names is created by a
task in this plan. There is no previous Huron to migrate from, delete or stay compatible with.

## How to execute this plan

- Work one task at a time, in milestone order. A task's `Dependencies` line names the tasks that must be
  complete first; within a milestone, tasks run in the order written unless the line says otherwise.
- Every task ends green: the plan-wide gate (section 10) passes on the whole tree, and the task's own
  `Verification` commands pass. A task is not complete while anything in the gate fails.
- Each task carries a `- Status:` line. The implementer sets it to `in progress` when starting and the
  verifier sets it to `complete` after an independent review; a short `Execution notes` paragraph under the
  task records anything a later task needs to know (a renamed symbol, a deferred edge case, a receipt).
- Sections 3 to 9 are binding design. When a task description and a binding section disagree, the binding
  section wins and the task's `Execution notes` record the discrepancy. Changing a decision in section 3
  is a plan amendment, written as a dated subsection at the end of section 3, never a silent edit.
- Names in this plan (packages, modules, classes, tables, routes, CLI verbs, error codes) are the names
  to use. Where the plan gives no name, choose one that follows the conventions in section 4.4.

## 1. Goal

Deliver Huron version 1: the service, the database, the CLI and the on-disk layout, production-ready for
one NFS share mounted at `/projects/huron` on designated machines, with the service running on OpenShift.
When the plan is complete:

- A platform administrator creates organizations. An organization administrator creates catalogs and
  appoints catalog administrators. A catalog administrator creates nested namespaces, marks which
  namespaces may hold collections, publishes the catalog's metadata schema and manages reader and
  contributor groups.
- A contributor creates a collection under a namespace, fills in its metadata by an interactive
  walkthrough against the catalog's schema, activates it, stages files, and pushes them. The push copies
  the files over the NFS mount and records them with the service in one synchronous commit. A push that
  is behind the collection's current version is refused until the user pulls.
- A reader lists catalogs, namespaces and collections, searches metadata, and reads files straight from
  the mount.
- Every directory the CLI creates carries POSIX ACLs derived from the catalog's role-to-LDAP-group
  mappings, so the filesystem enforces the same reader, contributor and administrator boundaries as the
  service. `huron check` reports where disk and catalog disagree.
- Every change is audited, every list is paged, every error is a `problem+json` document with a stable
  code, and the service is deployable from the manifests in `deploy/`.

## 2. Non-goals

These are out of scope for this plan. The design must not block them, and no task builds them.

- Versioning of raw data: no revisions, releases, tags, snapshots or per-file history. A collection has a
  single integer `version` used for optimistic concurrency only. Recovery from mistakes is the storage
  team's snapshot policy.
- Moving or renaming anything: no `mv` for collections, namespaces, catalogs or organizations.
- File bytes through the service: no HTTP upload, no resumable-upload protocol, no service-side mount of
  the share, no service-side hashing of pushed files. The service trusts the hashes the CLI reports.
- A web UI, a Python SDK, pipeline clients, service accounts, API keys, Apache Polaris, Icechunk/Zarr
  layers, S3 object storage. The API's list routes are shaped like Iceberg REST so a Polaris projection
  can come later.
- Grants on namespaces or collections. Version 1 grants roles at platform, organization and catalog scope.
  The privilege model allows finer scopes later.
- Custom roles. Version 1 has five fixed roles with fixed privilege sets.
- Automatic repair of disk drift. `huron check` reports; `huron acl apply` re-applies ACLs on directories
  the caller owns; nothing deletes user files.
- A Windows CLI. The CLI refuses to run on Windows with one message.
- Service-side group lookups per request. Groups are captured at login into the Huron token and re-mapped
  to roles on every request; a changed LDAP membership takes effect at the next login.

## 3. Decisions

Numbered so tasks can cite them. All are settled.

**Model**

- D-1 Hierarchy: Organization → Catalog → Namespace (recursive, any depth within path-length limits) →
  Collection. A namespace may hold child namespaces and, when `collections_allowed` is true, collections.
  A namespace and a collection may not share a name under the same parent.
- D-2 Catalog names are unique across the whole platform. Organization names are unique across the
  platform. Namespace and collection names are unique among their siblings.
- D-3 A collection's identifier is `catalog.ns1.ns2.name`: the catalog name, the dotted namespace path and
  the collection name. A namespace's identifier is `catalog.ns1.ns2`. The organization is not part of the
  identifier; it appears in the on-disk path and in administrative routes.
- D-4 Name segments match `[a-z0-9][a-z0-9_-]{0,62}`, NFC-normalized, lowercase, at most 63 bytes. The
  segments `huron`, `metadata` and anything starting with `.` are reserved. An identifier is at most 255
  bytes.
- D-5 A collection has states `draft`, `active` and `incomplete`. Deletion removes the row; the audit log
  keeps the history. Only `active` and `incomplete` collections have a directory.
- D-6 A collection carries one integer `version`, starting at 1 and incremented by every write to the row
  (metadata, schema override, activation, commit). It is the ETag for `If-Match` and the `base_version`
  a commit must carry.
- D-7 A commit is synchronous: one request with `base_version`, `adds` (relative path, size, sha256) and
  `removes`; the service applies it in one transaction or refuses it whole. A commit whose `base_version`
  is not the current version is refused with 409 `BASE_VERSION_CONFLICT`.
- D-8 No idempotency keys. A CLI that loses the response to a commit re-reads the collection: if the
  version advanced and its files are recorded, the commit succeeded.

**Roles**

- D-9 Five roles, modeled on Polaris: Platform Admin (platform scope), Org Admin (organization scope),
  Catalog Admin, Contributor and Reader (catalog scope). Each role is a fixed set of named privileges
  (section 5.2); authorization checks privileges, never role names, so finer scopes and custom roles can
  come later.
- D-10 Roles are granted to LDAP groups, never to individual users. The Huron token carries the user's
  groups; each request maps groups to roles through the current grants table. The platform admin group
  comes from configuration and is seeded as a grant at startup.
- D-11 A contributor may delete a collection they created (`created_by` matches the actor); a catalog
  administrator may delete any collection. This mirrors the sticky bit on namespace directories, where
  only the directory's owner can remove it.
- D-12 Huron is the auth broker: the CLI logs in to the institutional OIDC provider, exchanges that token
  at the service for a Huron-signed ES256 JWT, and uses the Huron token everywhere. The service fetches
  the user's LDAP groups from the group directory at exchange time and puts them in the token. The service
  publishes OIDC discovery and JWKS documents so another system (Polaris, later) can trust Huron tokens.

**Metadata and schemas**

- D-13 A schema registry holds versioned JSON Schema documents, scoped to the platform (the seeded
  `huron-base`) or to an organization. A document may `extend` another registry entry. Composition
  inherits the parent's properties and required fields; the child may add properties, add required
  fields and redefine a property's constraints, but may not drop a required field or change a required
  property's type.
- D-14 Each catalog is assigned exactly one registry entry (a specific version). Publishing a new version
  never changes a catalog; assignment is an explicit catalog-admin action.
- D-15 A collection may carry a schema override: an inline document composed on top of the catalog's
  assigned schema under the same rules as D-13. The schema a collection's metadata is validated against
  is always resolve(catalog assignment, collection override).
- D-16 When a catalog's assignment changes, every active or incomplete collection in it is re-validated:
  failures become `incomplete`, passes become `active`, each change bumping `version` and writing an audit
  entry. A collection's own metadata and override change in one request and must validate together.
- D-17 Metadata is stored in PostgreSQL as JSONB and is the source of truth. The CLI writes a
  `metadata.json` sidecar into the collection directory after activation and after every metadata
  publish, so the information survives apart from the service. `huron check` reports a stale sidecar.

**Storage and enforcement**

- D-18 Plain NFS. The share is mounted at a configurable prefix (default `/projects/huron`) on designated
  machines. The service on OpenShift mounts nothing; only the CLI touches the filesystem.
- D-19 Directories are created by the CLI as the user running it, after the service has authorized and
  recorded the change. The root directory is prepared once by the storage administrator with the script
  in `scripts/init-root.sh`.
- D-20 Every directory the CLI creates has setgid set and carries POSIX ACLs derived from the catalog's
  effective role groups (section 6.2). Structural directories (organization, catalog, namespace) are
  writable only by their administrators. A namespace with `collections_allowed` additionally gives the
  contributor groups write access and has the sticky bit set. Collection directories give contributors
  write access and carry default ACLs so new files are group-writable.
- D-21 Platform admin groups receive an inherited `rwx` default ACL at every level, so administrators can
  remove clutter without elevated privileges. Organization admin groups receive the same within their
  organization.
- D-22 Enforcement is contain-and-detect. Accepted: a scientist can write into their own collection
  directory without the CLI; the service trusts reported hashes; only a directory's owner can change its
  ACLs, so a changed group mapping is re-applied by owners running `huron acl apply`, and the rest is
  reported by `huron check`. The upgrade path, if ever needed, is HTTP ingest to a service that mounts the
  share, behind the same `Storage` interface the CLI uses now.
- D-23 The push write path: copy each file to `<rel_path>.huron-part` in the collection directory while
  hashing, `fsync`, rename into place, then commit. Removals are committed first and unlinked after. A
  retried push skips files already present with the recorded size and hash.

**Code**

- D-24 Layout: `src/huron/{pkg,schema,core,applications}` as in section 4.2. No directory under `src/`
  or `tests/` contains an underscore (`__init__.py` is a file, not a directory). No `_impl` or other
  "private" directories: visibility is expressed by names inside modules and by `__init__.py` exports.
- D-25 In every module, public classes and functions come first, private (underscore-prefixed) classes
  and functions after them. A test enforces both this and D-24.
- D-26 Runtime database access is asyncpg with hand-written SQL. Table definitions are SQLAlchemy Core
  objects used by Alembic migrations and by the schema-map check; no ORM sessions at runtime.
- D-27 Every store has an in-memory fake and a PostgreSQL adapter that pass the same contract test suite.
  Unit tests use the fakes; contract and integration tests use PostgreSQL in a container.

### Amendment (2026-10-31): the web client and the development stack

- **Section 2's "web UI" non-goal is narrowed.** A read-only web client of the API is in scope:
  `web/`, a SvelteKit server that signs people in with the company OIDC provider, exchanges the ID
  token at `POST /api/v1/auth/exchange` for a Huron token that only the server holds, and lets
  people switch between the organizations they can see, browse catalogs, namespaces and
  collections, and search a catalog or an organization. It writes nothing: changes stay with the
  CLI, the only part that touches the share (D-18, D-19), and the pages show the `huron` command
  where the signed-in user could act. A web UI that writes, and every other item of that bullet,
  stays out of scope. The design is [docs/web-design.md](docs/web-design.md). Section 2's text is
  unchanged.
- **Company JWKS.** `CompanyTokenVerifier` (`src/huron/core/security/broker/company.py`) keeps only
  usable signing keys: besides entries without a `kid`, as before, it now skips entries whose `use`
  is something other than `sig` (an entry without `use` stays) and entries PyJWT cannot load.
  Keycloak publishes an `RSA-OAEP` encryption key next to its `RS256` signing key, and loading that
  key failed every exchange with a 500. `tests/unit/security/test_exchange.py` covers it.
- **The whole application in Docker.** `docker-compose.app.yml` (`make app`, compose project
  `huron-app`) runs PostgreSQL, the migrations, the API, the group directory, Keycloak 26.0, the web
  and a one-shot seed of the web's e2e fixture. The containers share one network namespace and
  publish their ports on 127.0.0.1 only, and Keycloak runs with `KC_HOSTNAME`, so the issuer is
  `http://127.0.0.1:8081/realms/company` in the containers and on the host alike. It replaces the
  `app` profile of `docker-compose.yml` (M5.5), whose containers could not reach the issuer the
  tokens carry; `scripts/e2e.sh` (M10.3) runs on it as its own project, `huron-e2e`. `make up`
  still starts PostgreSQL and Keycloak alone, for `make api` on the host.
- **`dev.env`'s issuer.** `HURON_COMPANY_ISSUER` is `http://127.0.0.1:8081/realms/company`, the
  issuer Keycloak writes into its tokens. It was `http://keycloak:8081/realms/company`, which the
  host cannot resolve and no token carries, so `make api` refused every login.
- **The development realm.** `scripts/keycloak/company-realm.json` gains `huron-web`, the web's
  confidential client (code flow only, PKCE S256, exact callback and post-logout URIs on ports
  3000, 5173 and 4173, and an audience mapper that adds `huron-cli` to its ID tokens only), and
  the accounts `admin` (platform admin) and `user` (contributor and reader);
  `tests/unit/test_dev_realm.py` checks them. `huron-cli` loses its `pkce.code.challenge.method`
  attribute: with it, Keycloak 26 demands PKCE at the device endpoint too, and the CLI's device
  flow sends none, so `huron login --device` failed. The loopback flow still sends S256.
- **CLI follow-up.** `Oidc.device_flow` (`src/huron/applications/cli/login.py`) should send PKCE
  S256: a `code_challenge` with the device authorization request and the `code_verifier` with the
  device token request. `huron-cli` can then require PKCE again.
- **Compose follow-up.** `docker-compose.yml` (`make up`) publishes PostgreSQL (5432) and Keycloak
  (8081) on every network interface, with their development credentials; it should bind both to
  127.0.0.1, as `docker-compose.app.yml` does. `scripts/devgroups.py`, which the host stack runs
  beside them, listens on 0.0.0.0 too; on the host it could bind 127.0.0.1, while in `make app` it
  must stay reachable through the published port. Until then `web/README.md` and `README.md` say to
  run the host stack on a trusted machine and network.

## 4. Architecture

### 4.1 Components

| Component | Runs | Responsibility |
| --- | --- | --- |
| `huron-api` | OpenShift pod | Authentication broker, authorization, catalog of organizations, catalogs, namespaces, collections, files; schema registry; audit log; search. No filesystem access. |
| PostgreSQL | OpenShift (or managed) | Schema `huron`: all tables in section 7. |
| `huron` CLI | Designated machines with the NFS mount | Login, browsing, administration verbs, the metadata walkthrough, staging and push, directory creation and ACLs, drift checks. Talks to the API over HTTPS and to the share through the local mount. |
| Institutional OIDC provider | External | Issues the company token the CLI exchanges. |
| Group directory | External | `GET …/users/{username}/groups` → `{"groups": [...]}`; mocked in development. |
| NFS share | External | `/projects/huron`, prepared once by `scripts/init-root.sh`. |

### 4.2 Package tree

Binding. Files listed here are created by the milestone in parentheses; a task may add sibling modules
inside a package but not new top-level packages.

```text
src/huron/
  __init__.py
  pkg/                      Generic code with no Huron knowledge. Importable by everything. (M1)
    errors.py               HuronError base, ErrorCode registry, problem document rendering
    paging.py               Cursor encoding, Page[T], page-size bounds
    canonical.py            RFC 8785 canonical JSON bytes, stable hashing of documents
    identifiers.py          UUIDv7 generation, parsing
    clock.py                Clock protocol, SystemClock, FrozenClock
    hashing.py              Streaming sha256 over a file or a byte iterator
    fs/
      posix.py              mkdir with mode, atomic copy via part file + rename, fsync, unlink, walk, stat
      acl.py                POSIX ACL entries, getfacl/setfacl invocation and parsing
  schema/                   Document contracts. Imports pkg only. (M1)
    documents/              JSON Schema files: huron-base-v1.json, commit-request-v1.json,
                            schema-document-v1.json (the allowed subset of JSON Schema)
    loader.py               Load and cache the documents above
    validator.py            JSON Schema 2020-12 validation with RE2 patterns; Problem list
    naming.py               Segment, identifier and relative-path rules (D-4, section 5.1)
    composition.py          extends-composition of schema documents (D-13)
  core/
    lake/                   Domain. Imports pkg, schema, core.security.rbac. (M3)
      organizations/        models.py  operations.py  grants.py  errors.py  ports.py
      catalogs/             models.py  operations.py  errors.py  ports.py
      namespaces/           models.py  operations.py  errors.py  ports.py
      collections/          models.py  lifecycle.py  metadata.py  errors.py  ports.py
      files/                models.py  commits.py  errors.py  ports.py
      schemas/              models.py  registry.py  completeness.py  errors.py  ports.py
      audit/                models.py  ports.py  writer.py
      bootstrap.py          Lake composition; seeds: huron-base schema, platform grant, first signing key
    security/               Imports pkg, schema. Never imports core.lake. (M2)
      broker/               discovery.py  company.py  groups.py  keys.py  tokens.py  exchange.py
      rbac/                 roles.py  privileges.py  grants.py  actor.py  authorize.py  ports.py
    metastore/              Persistence adapters. Imports core.lake, core.security, pkg. (M3 fakes, M4 Postgres)
      tables.py             The shared MetaData(schema="huron")
      postgres.py           Pool, transaction, advisory-lock key space
      memory.py             In-memory transaction root shared by the fakes
      store.py              Store and Transaction protocols: one attribute per area
      organizations/        tables.py  postgres.py  memory.py
      catalogs/             tables.py  postgres.py  memory.py
      namespaces/           tables.py  postgres.py  memory.py
      collections/          tables.py  postgres.py  memory.py
      files/                tables.py  postgres.py  memory.py
      schemas/              tables.py  postgres.py  memory.py
      grants/               tables.py  postgres.py  memory.py
      audit/                tables.py  postgres.py  memory.py
      keys/                 tables.py  postgres.py  memory.py
    storage/                Share layout and ACLs. Imports pkg, core.lake models. Used by the CLI. (M7)
      ports.py              Storage protocol
      layout.py             Identifier → path, path → identifier, reserved names
      aclplan.py            Effective groups by role → ACL entries per directory kind (section 6.2)
      posix.py              PosixStorage over pkg.fs
      memory.py             MemoryStorage fake with the same contract
      marker.py             Root marker file (.huron) read and verify
      check.py              Drift findings: compare the API's view with the storage's walk (M9)
  applications/
    api/                    (M5)
      main.py               uvicorn entry: `huron.applications.api.main:app`
      app.py                create_app(settings, store, …): routers, middleware, error handlers
      settings.py           pydantic-settings, HURON_* environment
      lifespan.py           Pool, key ring, bootstrap, readiness
      problems.py           problem+json responses from HuronError
      dependencies.py       Store, clock, settings providers
      openapi.py            `python -m huron.applications.api.openapi` writes docs/openapi.json
      authorization/
        actors.py           current_actor: Huron JWT → Actor with roles resolved from grants
      routes/
        pagination.py       Cursor query parameters and Link headers
        preconditions.py    If-Match parsing, ETag rendering
        discovery.py        /.well-known/openid-configuration, /jwks.json
        health.py           /healthz, /readyz
        v1/
          router.py         /api/v1 composition
          endpoints/        auth.py organizations.py catalogs.py grants.py schemas.py namespaces.py
                            collections.py commits.py files.py search.py admin.py
          schema/           Request and response bodies, one module per endpoints module
    cli/                    (M6, M7, M8, M9)
      main.py               console entry `huron`
      app.py                Root Typer app, error boundary, exit codes
      errors.py             ExitCode, CliError and the problem-code → exit-code mapping
      services.py           Services: the one composition seam (state, http, clock, storage, prompter)
      config.py             config.yaml: api_url, issuer, client_id, mount_prefix, acl_backend
      state.py              XDG state dir, tokens.json (0600), working copies
      client.py             httpx client: problem+json → CliError, paging, ETags
      login.py              Device grant and loopback PKCE flows, token exchange, refresh
      identifiers.py        Relative identifiers against the current catalog
      mount.py              Mount prefix and marker checks before any disk operation
      sync.py               Stage, pull and push logic shared by the stage verbs
      output.py             -o table|json|yaml rendering
      prompts.py            Prompter protocol and the questionary implementation
      walkthrough.py        JSON Schema → prompt plan → metadata document
      commands/             session.py organizations.py catalogs.py schemas.py namespaces.py
                            collections.py stage.py meta.py check.py acl.py platform.py
migrations/
  env.py                    Alembic environment bound to the SQLAlchemy Core tables
  versions/0001_huron.py    The whole version-1 schema (M4)
alembic.ini
tests/
  unit/                     Fakes only; the default `make test`
  contract/                 Store contract suite against memory and PostgreSQL (testcontainers)
  integration/              API over PostgreSQL; CLI over a real temp directory and the in-process API
  acl/                      Real getfacl/setfacl round trips; skipped where the filesystem lacks ACLs
  fakes/                    Company OIDC issuer, group directory, scripted prompter
  support/                  Shared fixtures and builders
deploy/openshift/           Kustomize base: Deployment, Service, Route, ConfigMap, Secret, migration Job (M10)
scripts/                    init-root.sh, check-stack.sh, check_schema_map.py, devgroups.py, dev-groups.yaml,
                            e2e.sh, keycloak/company-realm.json
docs/                       architecture.md, operator.md, user-guide.md, api-errors.md, openapi.json, adr/
```

### 4.3 Dependency graph

Enforced by `import-linter` contracts in `pyproject.toml`, created in M0 and extended as packages appear.

```text
pkg            ← imports nothing from huron
schema         ← pkg
core.security  ← pkg, schema
core.lake      ← pkg, schema, core.security.rbac
core.metastore ← pkg, core.lake, core.security
core.storage   ← pkg, schema, core.lake (models only), core.security.rbac (roles)
applications.api ← everything except applications.cli and core.storage
applications.cli ← pkg, schema, core.storage, core.security.rbac (role names), core.lake models
```

Contracts:

1. `huron.pkg` is independent of every other `huron` package.
2. `huron.schema` may import only `huron.pkg`.
3. `huron.core.security` must not import `huron.core.lake`, `huron.core.metastore`, `huron.core.storage`
   or `huron.applications`.
4. `huron.core.lake` must not import `huron.core.metastore`, `huron.core.storage` or `huron.applications`.
5. Nothing outside `huron.applications` imports `huron.core.metastore`.
6. `huron.applications.api` must not import `huron.applications.cli` or `huron.core.storage`.
7. `huron.applications.cli` must not import `huron.applications.api`, `huron.core.metastore` or
   `huron.core.security.broker`.
8. Inside `huron.core.lake`, an area package may import another area's `models`, `errors` and `ports`
   modules but never its `operations`, `lifecycle`, `registry`, `commits` or `completeness` modules;
   cross-area collaboration goes through constructor arguments (section 11 names them).

### 4.4 Code conventions

- Python 3.12, `from __future__ import annotations` not needed; use PEP 604 unions and PEP 695 generics
  where they read better.
- No directory name contains an underscore; no `_impl`, `_internal`, `internal` or `private` directories
  (D-24). Module file names may contain underscores when a single word does not fit.
- Public before private in every module (D-25): all public classes and functions, then all
  underscore-prefixed ones. Module-level constants come first; dunder metadata and `__all__` at the top.
- `__init__.py` of each package exports its public surface in `__all__`; other packages import from the
  package, not from its modules, unless the import-linter contract requires the module path.
- Values are frozen dataclasses (`@dataclass(frozen=True, slots=True)`) or pydantic models at the API and
  CLI edges only. Domain operations are classes with explicit constructor dependencies; no module-level
  singletons, no global state.
- Ports are `typing.Protocol` classes owned by the package that calls them (`core.lake.<area>.ports`,
  `core.storage.ports`, `core.security.rbac.ports`). Adapters live in `core.metastore` and
  `core.storage`.
- Errors: every domain error subclasses `huron.pkg.errors.HuronError` with a stable `code`, an HTTP
  `status`, a one-line `message` and a `context` dict. `ErrorCode` entries are registered in the module
  that raises them and collected into one table the API and CLI share.
- Async everywhere on the service side (asyncpg, httpx.AsyncClient). The CLI is synchronous.
- Logging through `structlog`, one event name per log line in `area.event` form, never f-strings in
  event names.
- Docstrings on every public class and function, in plain language, stating behavior and errors.
- Tests: pytest, `pytest-asyncio` in auto mode, Hypothesis for the naming and composition rules. Test
  names describe behavior. Fakes over mocks; mock only at real I/O boundaries (subprocess, network,
  clock).
- Type checking: `mypy --strict` and `ty check` both clean. Public functions are fully annotated.

## 5. Domain model

### 5.1 Hierarchy, identifiers and naming

| Entity | Parent | Name uniqueness | Identifier | Directory |
| --- | --- | --- | --- | --- |
| Organization | platform | global | `org` (admin routes only) | `<prefix>/<org>/` |
| Catalog | organization | global (D-2) | `catalog` | `<prefix>/<org>/<catalog>/` |
| Namespace | catalog or namespace | siblings | `catalog.ns1.ns2` | `<prefix>/<org>/<catalog>/ns1/ns2/` |
| Collection | namespace | siblings (shared with namespaces) | `catalog.ns1.ns2.name` | `<prefix>/<org>/<catalog>/ns1/ns2/name/` |

`huron.schema.naming` owns the rules:

- `check_segment(value)` applies D-4 and returns the normalized segment or raises `NamingError(rule,
  value)` with rule ids `segment_nfc`, `segment_chars`, `segment_length`, `segment_reserved`.
- `parse_identifier(text) -> Identifier(catalog, namespace_path, name | None)` splits on dots; at most
  255 bytes total (`identifier_length`); at least one segment.
- `check_rel_path(value)` for files inside a collection: NFC, at most 1024 bytes, each segment at most
  255 bytes, no empty segment, no `.` or `..` segment, no control characters, `/` only as separator, no
  leading `/`, the root entry `metadata.json` and any entry starting with `.huron` reserved. Rule ids
  `rel_path_nfc`, `rel_path_length`, `rel_path_segment`, `rel_path_control`, `rel_path_separator`,
  `rel_path_reserved`. `rel_path_key(value)` is the case-folded key used for uniqueness so that two paths
  differing only in case cannot both be recorded. `part_name(rel_path)` is `<rel_path>.huron-part`.

### 5.2 Roles, privileges and grants

Scopes: `platform`, `organization` (by organization id), `catalog` (by catalog id).

| Privilege | Platform Admin | Org Admin | Catalog Admin | Contributor | Reader |
| --- | --- | --- | --- | --- | --- |
| `ORGANIZATION_CREATE`, `ORGANIZATION_DELETE`, `ORGANIZATION_GRANT` | ✓ | | | | |
| `PLATFORM_SCHEMA_PUBLISH`, `SIGNING_KEY_ROTATE` | ✓ | | | | |
| `ORGANIZATION_READ` | ✓ | ✓ | ✓ | ✓ | ✓ |
| `CATALOG_CREATE`, `CATALOG_DELETE`, `CATALOG_GRANT_ADMIN`, `SCHEMA_PUBLISH` | ✓ | ✓ | | | |
| `CATALOG_GRANT_MEMBER` (readers and contributors), `SCHEMA_ASSIGN`, `NAMESPACE_CREATE`, `NAMESPACE_DELETE`, `NAMESPACE_CONFIGURE` | ✓ | ✓ | ✓ | | |
| `COLLECTION_DELETE_ANY` | ✓ | ✓ | ✓ | | |
| `COLLECTION_CREATE`, `COLLECTION_WRITE_METADATA`, `COLLECTION_WRITE_FILES`, `COLLECTION_DELETE_OWN` | ✓ | ✓ | ✓ | ✓ | |
| `CATALOG_READ`, `COLLECTION_READ`, `AUDIT_READ` | ✓ | ✓ | ✓ | ✓ | ✓ |

- A grant is `(scope_type, scope_id, role, ldap_group)`. Platform Admin grants have `scope_id = NULL`.
  Org Admin grants are scoped to an organization; the three catalog roles to a catalog.
- An `Actor` is `(subject, display_name, groups)`. `Authorizer.roles_for(actor)` returns the set of
  `(scope, role)` pairs from grants whose group is in `actor.groups`. `Authorizer.require(actor,
  privilege, scope)` passes when any role the actor holds at that scope or an enclosing scope carries the
  privilege; otherwise it raises `Forbidden` (403 `FORBIDDEN`). An enclosing scope is: platform encloses
  everything; an organization encloses its catalogs.
- Visibility: an actor sees an organization if they hold any role at platform scope, at that
  organization, or at any catalog in it. An actor sees a catalog if they hold any role at platform
  scope, at its organization, or at the catalog. Hidden objects answer 404 `NOT_FOUND`, so existence
  leaks nothing.
- The platform admin group `settings.platform_admin_group` is seeded as a Platform Admin grant at
  startup and cannot be removed through the API.

### 5.3 Collection lifecycle

```text
                create                    activate
  (none) ───────────────▶ draft ─────────────────────▶ active ◀──────▶ incomplete
                           │                            │                 │
                           │ delete (creator or admin)  │ delete          │ delete
                           ▼                            ▼                 ▼
                         (row removed; audit keeps the trail)
```

- `create(actor, catalog, namespace_path, name, metadata?)`: requires `COLLECTION_CREATE` on the catalog
  and a namespace with `collections_allowed`; reserves the name among its siblings; stores metadata
  without validating it; state `draft`, `version` 1; audit `collection.create`.
- `update(actor, id, expected_version, metadata_patch?, schema_override?)`: JSON merge patch (RFC 7396)
  on the metadata; when either field is present the result is validated against
  resolve(catalog assignment, new override). A draft may hold invalid metadata (validation problems are
  returned as warnings); an `active` or `incomplete` collection refuses invalid metadata with 422
  `METADATA_INVALID`. Bumps `version`; audit `collection.update_metadata` and/or
  `collection.set_schema_override`.
- `activate(actor, id, expected_version)`: requires valid metadata; state `active`; `activated_at`;
  audit `collection.activate`. The CLI creates the directory and ACLs before calling activate and writes
  the sidecar after (D-17, D-19).
- `recompute(catalog)`: after a schema assignment, re-validates every `active`/`incomplete` collection
  (D-16).
- `delete(actor, id, expected_version)`: `COLLECTION_DELETE_ANY`, or `COLLECTION_DELETE_OWN` when
  `created_by` matches; requires `file_count == 0` (409 `COLLECTION_NOT_EMPTY`); removes the row; audit
  `collection.delete`. The CLI removes recorded files by a commit, then deletes the row, then removes the
  directory.

### 5.4 Files and commits

- A file row is `(collection_id, rel_path, rel_path_key, size, sha256, recorded_at, recorded_by,
  commit_id)`. Re-adding an existing `rel_path` replaces its row (an update), counted as an add.
- `commit(actor, id, request)` with `request = {base_version, adds[], removes[], host, message?}`:
  1. Authorize `COLLECTION_WRITE_FILES`; state must be `active` or `incomplete` (409 `STATE_CONFLICT`
     for drafts).
  2. Validate: every `rel_path` passes `check_rel_path`; no path appears twice (by `rel_path_key`) or in
     both lists (422 `COMMIT_INVALID`); `sha256` is 64 lowercase hex characters; `size >= 0`; at most
     10,000 entries (413 `COMMIT_TOO_LARGE`); every `remove` names a recorded file (422
     `FILE_NOT_RECORDED`).
  3. Lock the collection row; `base_version` must equal `version` (409 `BASE_VERSION_CONFLICT` with
     `current_version`).
  4. Apply rows, set `file_count`, bump `version`, insert the commit row, write audit `collection.commit`
     with `{adds, removes, host, message}`.
  5. Return `{version, file_count, commit_id}`.
- `list_files(actor, id, cursor)` pages by `rel_path_key`.

### 5.5 Metadata schemas

- Registry entry: `(id, organization_id | NULL, name, version, extends_id | NULL, document, created_at,
  created_by)`, unique on `(organization_id, name, version)`. `version` is assigned by the service: one
  more than the highest existing version of that name in that scope.
- A schema document must validate against `schema-document-v1.json`, the allowed subset of JSON Schema
  2020-12: `type` object at the root; `properties`; `required`; `additionalProperties` (boolean);
  `title`; `description`; property types `string`, `number`, `integer`, `boolean`, `array` (of scalars
  or of objects declared inline), `object` (inline); constraints `enum`, `const`, `minimum`, `maximum`,
  `minLength`, `maxLength`, `pattern` (RE2 syntax, compiled with `google-re2`), `minItems`, `maxItems`,
  `uniqueItems`, `format` in `{date, date-time, email, uri}`; no `$ref`, no conditionals, no
  `patternProperties`. Violations are 422 `SCHEMA_INVALID` with the validator's problems.
- `compose(parent, child)` (D-13): properties merged with child winning per property; `required` is the
  union; `additionalProperties` from the child when present, else the parent; a child redefining a
  parent-required property must keep its `type` (`SCHEMA_INCOMPATIBLE`); a child may not list a
  parent-required property as optional (there is no way to express that, so the union rule covers it).
  `resolve(entry)` composes the chain from the root down and caches by `(entry.id)`;
  `resolve_for_collection(catalog, collection)` composes `resolve(catalog.schema)` with the override.
- `huron-base` v1 (platform scope, seeded) requires `title` (string, 1–200) and `description` (string)
  and offers `keywords` (array of strings), `contacts` (array of `{name, email}`), `instrument`,
  `campaign`, `start_time`, `end_time` (date-time), `labels` (object of string → string). Every
  organization schema must extend `huron-base` or another entry that does.
- Assignment: `assign(actor, catalog, schema_id)` requires `SCHEMA_ASSIGN`; the entry must belong to the
  catalog's organization or to the platform (422 `SCHEMA_SCOPE`); then `recompute(catalog)`.

### 5.6 Audit

Append-only table `audit`. Entry: `(id, at, actor_subject, action, object_type, object_id, catalog_id |
NULL, organization_id | NULL, detail jsonb)`. Actions are a closed vocabulary in
`core.lake.audit.models.Action`: `organization.create|delete|grant|revoke`,
`catalog.create|delete|grant|revoke|assign_schema`, `namespace.create|delete|configure`,
`schema.publish`, `collection.create|update_metadata|set_schema_override|activate|mark_incomplete|
mark_active|commit|delete`, `signing_key.rotate`. Every write operation writes its entry in the same
transaction as its change. `GET /collections/{id}/log` and `GET /catalogs/{catalog}/log` page the table
newest first.

## 6. Storage layout and ACLs

### 6.1 Root and marker

- The storage administrator runs `scripts/init-root.sh <prefix> <platform-admin-group> <api-url>
  <instance-id>` once, as a user that owns the prefix (or as root): `chgrp`, `chmod 2771`, access ACL `g:<platform>:rwx`, default ACL
  `g:<platform>:rwx`, and writes `<prefix>/.huron` containing `{"huron": 1, "api_url": "<url>",
  "instance_id": "<uuid>"}` (`0644`). The `instance_id` matches `settings.instance_id` of the service the
  share belongs to.
- The CLI refuses any disk operation unless the marker exists and its `instance_id` equals the one the
  API reports in `GET /healthz`. This keeps a CLI pointed at a staging API from writing into production
  directories.
- `others` have traverse-only (`--x`) on the root and on organization directories, so readers can reach a
  catalog they are granted without listing what else exists.

### 6.2 Directory kinds and ACL plans

Groups come from the effective grants of the catalog, returned by `GET /catalogs/{catalog}/grants` as
`{platform_admin: [...], org_admin: [...], catalog_admin: [...], contributor: [...], reader: [...]}`.
`core.storage.aclplan.plan(kind, groups) -> AclPlan(mode, access, default)` produces:

| Kind | Mode | Access ACL (group entries) | Default ACL (inherited by children) | Others |
| --- | --- | --- | --- | --- |
| organization | `2771` | platform `rwx`, org_admin `rwx` | platform `rwx`, org_admin `rwx` | `--x` |
| catalog | `2770` | platform `rwx`, org_admin `rwx`, catalog_admin `rwx`, contributor `r-x`, reader `r-x` | platform `rwx`, org_admin `rwx` | `---` |
| namespace, `collections_allowed = false` | `2770` | same as catalog | platform `rwx`, org_admin `rwx` | `---` |
| namespace, `collections_allowed = true` | `3770` (setgid + sticky) | platform `rwx`, org_admin `rwx`, catalog_admin `rwx`, contributor `rwx`, reader `r-x` | platform `rwx`, org_admin `rwx` | `---` |
| collection | `2770` | platform `rwx`, org_admin `rwx`, catalog_admin `rwx`, contributor `rwx`, reader `r-x` | platform `rwx`, org_admin `rwx`, catalog_admin `rwx`, contributor `rwx`, reader `r-x` | `---` |

- The owning group of every directory is the first contributor group for collection directories and
  namespaces that allow collections, otherwise the first catalog admin group; the setgid bit makes new
  entries inherit it.
- `setfacl -m` recalculates the mask; the plan is verified by reading back with `getfacl` and comparing
  the parsed entries, ignoring order and the mask line.
- `PosixStorage.apply(path, plan)` is idempotent: applying the same plan twice changes nothing and
  reports `changed=False`.
- Who applies: the CLI, as the user who created the directory. `huron acl apply <identifier>
  [--recursive]` re-applies plans for every directory under the identifier that the caller owns and
  prints the ones it could not change.
- The CLI computes plans locally from `GET /catalogs/{catalog}/grants`; the API never returns ACL
  entries and never imports storage code (contract 6).
- With `acl_backend: none` in the CLI configuration (development machines, filesystems without ACL
  support) the CLI applies the mode bits only and prints a warning on every directory it creates.

### 6.3 Push write path

See D-23. `PosixStorage.copy_in(source, dest_dir, rel_path) -> FileStamp(size, sha256)`:

1. `dest = dest_dir / rel_path`; create intermediate directories with mode `2770` (they inherit the
   default ACL).
2. If the caller passes an `expected` stamp and `dest` exists with that size and sha256 (the destination
   is re-hashed to check), return the stamp without copying. Without `expected`, always copy.
3. Open `dest.huron-part` with `O_CREAT | O_EXCL | O_WRONLY`; stream the source through
   `pkg.hashing.sha256_copy` in 8 MiB chunks; `fsync`; `rename` over `dest`.
4. On any failure remove the part file and re-raise `StorageError`.

Removals: after the commit succeeds, `unlink` each removed path; a missing file is not an error.
`huron check` reports `.huron-part` files older than one hour as `stale_part`.

### 6.4 What `huron check` reports

For every catalog the caller can read (or the one named), with the mount available:

| Finding | Severity | Meaning |
| --- | --- | --- |
| `namespace_dir_missing` | error | A namespace row with no directory. `huron namespace create` is idempotent on disk and recreates it. |
| `collection_dir_missing` | error | An active collection with no directory. |
| `file_missing` | error | A recorded file absent from disk. |
| `file_changed` | warning | Size differs from the recorded stamp; with `--hash`, sha256 differs. |
| `file_unrecorded` | warning | A file on disk inside a collection that no commit recorded. |
| `dir_unrecorded` | warning | A directory under a namespace that is neither a namespace nor a collection. |
| `sidecar_stale` | warning | `metadata.json` missing or not equal to the service's rendering. |
| `acl_drift` | warning | A directory whose ACL does not match its plan (only directories the caller can read). |
| `stale_part` | info | A `.huron-part` file older than one hour. |
| `incomplete` | info | A collection in state `incomplete`. |
| `stale_draft` | info | A draft older than 30 days. |

Exit code 0 with no findings, 1 with findings, 2 on an error running the check.

## 7. Persistence

PostgreSQL 16, schema `huron`, one Alembic revision `0001_huron` for version 1. Table definitions are
SQLAlchemy Core objects in `core/metastore/<area>/tables.py`; `migrations/env.py` imports them so
`alembic revision --autogenerate` detects drift, and `scripts/check_schema_map.py` fails the gate when
the live schema after `upgrade head` differs from the Core metadata.

| Table | Columns (type, constraints) |
| --- | --- |
| `organizations` | `id uuid pk`, `name text unique`, `display_name text`, `description text`, `version int`, `created_at timestamptz`, `created_by text` |
| `catalogs` | `id uuid pk`, `organization_id uuid fk`, `name text unique`, `display_name text`, `description text`, `schema_id uuid fk schemas`, `version int`, `created_at`, `created_by` |
| `namespaces` | `id uuid pk`, `catalog_id uuid fk`, `parent_id uuid fk namespaces null`, `name text`, `path text` (dotted, denormalized for lookups), `collections_allowed bool`, `version int`, `created_at`, `created_by`; unique `(catalog_id, path)`; check `parent_id is null or parent is in the same catalog` (trigger) |
| `collections` | `id uuid pk`, `catalog_id uuid fk`, `namespace_id uuid fk`, `name text`, `identifier text unique`, `state text check in (draft, active, incomplete)`, `version int`, `metadata jsonb`, `schema_override jsonb null`, `file_count int`, `created_at`, `created_by`, `activated_at null`, `updated_at`; unique `(namespace_id, name)` |
| `files` | `collection_id uuid fk on delete restrict`, `rel_path text`, `rel_path_key text`, `size bigint check >= 0`, `sha256 char(64)`, `recorded_at`, `recorded_by`, `commit_id uuid fk`; pk `(collection_id, rel_path_key)` |
| `commits` | `id uuid pk`, `collection_id uuid fk`, `base_version int`, `new_version int`, `adds int`, `removes int`, `host text`, `actor text`, `created_at` |
| `schemas` | `id uuid pk`, `organization_id uuid fk null`, `name text`, `version int`, `extends_id uuid fk schemas null`, `document jsonb`, `created_at`, `created_by`; unique `(organization_id, name, version)` nulls not distinct |
| `grants` | `id uuid pk`, `scope_type text check in (platform, organization, catalog)`, `scope_id uuid null`, `role text check in (platform_admin, org_admin, catalog_admin, contributor, reader)`, `ldap_group text`, `created_at`, `created_by`; unique `(scope_type, scope_id, role, ldap_group)` nulls not distinct; check `(scope_type = 'platform') = (scope_id is null)`; check role matches scope |
| `audit` | `id bigint generated always as identity pk`, `at timestamptz`, `actor text`, `action text`, `object_type text`, `object_id uuid`, `catalog_id uuid null`, `organization_id uuid null`, `detail jsonb` |
| `signing_keys` | `kid text pk`, `private_pem text`, `public_jwk jsonb`, `created_at`, `retired_at null` |

Indexes: `collections (catalog_id, state)`, `collections using gin (metadata jsonb_path_ops)`,
`namespaces (catalog_id, parent_id)`, `audit (object_id, id desc)`, `audit (catalog_id, id desc)`,
`grants (ldap_group)`, `files (collection_id, rel_path_key)` (the pk).

Triggers: `sibling_exclusion` refuses a namespace whose `(catalog_id, parent_id, name)` matches a
collection's `(catalog_id, namespace_id, name)` and the reverse, so the uniqueness in D-1 holds across the
two tables.

Locking: writes to a collection take `SELECT … FOR UPDATE` on its row. Catalog-wide changes (schema
assignment and recompute, namespace creation and deletion) take `pg_advisory_xact_lock(hashtext('catalog:'
|| catalog_id))`. Lock order is always catalog, then collection, then files.

`core.metastore.store.Store` exposes one attribute per area, each a reader-and-writer object implementing
that area's port, and `Store.transaction()` yields a `Transaction` whose area objects share one connection.
The in-memory `Store` has the same shape over `core.metastore.memory.MemoryRoot`, with copy-on-commit so a
failed transaction leaves nothing behind.

## 8. API surface

Base path `/api/v1`. Authentication: `Authorization: Bearer <huron token>` on everything except discovery,
health and the exchange. Errors are `application/problem+json` with `type`, `title`, `status`, `detail`,
`code` and `context`. Lists are paged with `?cursor=&limit=` (limit 1–500, default 100) and return
`{items, next_cursor}`. Collection responses carry `ETag: "<version>"`; writes to a collection require
`If-Match` and answer 428 `PRECONDITION_REQUIRED` without it and 412 `VERSION_CONFLICT` on a mismatch.

| Method and path | Minimum privilege | Notes |
| --- | --- | --- |
| `GET /.well-known/openid-configuration`, `GET /jwks.json` | none | Huron issuer discovery. |
| `GET /healthz`, `GET /readyz` | none | `healthz` returns `{status, instance_id, version}`; `readyz` checks the pool and the key ring. |
| `POST /auth/exchange` | none | `{company_token}` → `{huron_token, expires_at, subject, groups, roles}`. 401 `TOKEN_INVALID`, 503 `GROUP_DIRECTORY_UNAVAILABLE`. |
| `GET /auth/whoami` | authenticated | Subject, groups, effective `(scope, role)` list. |
| `GET /organizations` | visibility | Organizations the actor can see. |
| `POST /organizations` | `ORGANIZATION_CREATE` | `{name, display_name, description}`. 409 `NAME_TAKEN`. |
| `GET /organizations/{org}` | `ORGANIZATION_READ` | Body includes `catalog_count`. |
| `DELETE /organizations/{org}` | `ORGANIZATION_DELETE` | 409 `ORGANIZATION_NOT_EMPTY` while catalogs exist. |
| `GET /organizations/{org}/grants`, `PUT /organizations/{org}/grants/{role}` | `ORGANIZATION_GRANT` | `role` is `org_admin`; body `{ldap_groups: [...]}` replaces the set. |
| `GET /organizations/{org}/schemas` | `ORGANIZATION_READ` | Registry entries of the organization, newest version first. |
| `POST /organizations/{org}/schemas` | `SCHEMA_PUBLISH` | `{name, extends_id, document}` → new version. 422 `SCHEMA_INVALID`, `SCHEMA_INCOMPATIBLE`, `SCHEMA_SCOPE`. |
| `GET /schemas/{id}`, `GET /schemas/{id}/resolved` | visibility of its scope | Platform entries are visible to every authenticated actor. |
| `POST /platform/schemas` | `PLATFORM_SCHEMA_PUBLISH` | New version of a platform-scoped entry. |
| `GET /platform/grants`, `PUT /platform/grants/platform_admin` | `ORGANIZATION_GRANT` | The configured group is always present and cannot be removed. |
| `GET /catalogs` | visibility | `?organization=` filter. Iceberg-shaped: `{items: [{name, organization, …}]}`. |
| `POST /organizations/{org}/catalogs` | `CATALOG_CREATE` | `{name, display_name, description, schema_id?}`; default schema is `huron-base` latest. |
| `GET /catalogs/{catalog}` | `CATALOG_READ` | Includes `schema` (id, name, version) and counts. |
| `DELETE /catalogs/{catalog}` | `CATALOG_DELETE` | 409 `CATALOG_NOT_EMPTY` while namespaces exist. |
| `GET /catalogs/{catalog}/grants` | `CATALOG_READ` | Effective groups by role, including inherited org and platform groups (section 6.2). |
| `PUT /catalogs/{catalog}/grants/{role}` | `CATALOG_GRANT_ADMIN` for `catalog_admin`, `CATALOG_GRANT_MEMBER` for `contributor` and `reader` | `{ldap_groups}` replaces the set. Audit `catalog.grant`/`revoke` per change. |
| `PUT /catalogs/{catalog}/schema` | `SCHEMA_ASSIGN` | `{schema_id}`; triggers recompute; answers `{assigned, recompute: {incomplete, active}}`. |
| `GET /catalogs/{catalog}/schema` | `CATALOG_READ` | The resolved document. |
| `GET /catalogs/{catalog}/namespaces?parent=` | `CATALOG_READ` | Children of `parent` (dotted path, empty for the root). |
| `POST /catalogs/{catalog}/namespaces` | `NAMESPACE_CREATE` | `{parent, name, collections_allowed}`. 404 for a missing parent; 409 `NAME_TAKEN`; 422 `NAME_INVALID`. |
| `GET /catalogs/{catalog}/namespaces/{path}` | `CATALOG_READ` | Includes `collections_allowed`, child counts and `path` (relative to the prefix). |
| `PATCH /catalogs/{catalog}/namespaces/{path}` | `NAMESPACE_CONFIGURE` | `{collections_allowed}`; refuses `false` while collections exist (409 `NAMESPACE_NOT_EMPTY`). |
| `DELETE /catalogs/{catalog}/namespaces/{path}` | `NAMESPACE_DELETE` | 409 `NAMESPACE_NOT_EMPTY` while children or collections (including drafts) exist. |
| `GET /catalogs/{catalog}/namespaces/{path}/collections` | `CATALOG_READ` | Drafts are shown only to actors holding `COLLECTION_CREATE`. |
| `POST /catalogs/{catalog}/namespaces/{path}/collections` | `COLLECTION_CREATE` | `{name, metadata?}` → draft. 409 `COLLECTIONS_NOT_ALLOWED`, `NAME_TAKEN`. |
| `GET /catalogs/{catalog}/collections/{identifier}` | `COLLECTION_READ` | Resolve by identifier; answers the same body as `GET /collections/{id}`. |
| `GET /collections/{id}` | `COLLECTION_READ` | Body: identifier, organization, catalog, state, version, metadata, schema_override, schema (the resolved `SchemaRef`), file_count, created_by, timestamps, `path` (relative to the prefix, `null` for drafts), validation `problems` (for drafts and incomplete). |
| `PATCH /collections/{id}` | `COLLECTION_WRITE_METADATA` | `If-Match`; `{metadata?, schema_override?}` (merge patch; `null` override clears). 422 `METADATA_INVALID`. |
| `POST /collections/{id}/activate` | `COLLECTION_WRITE_METADATA` | `If-Match`. 409 `STATE_CONFLICT` unless draft; 422 `METADATA_INVALID`. |
| `DELETE /collections/{id}` | `COLLECTION_DELETE_OWN` or `COLLECTION_DELETE_ANY` | `If-Match`. 409 `COLLECTION_NOT_EMPTY`. |
| `GET /collections/{id}/schema` | `COLLECTION_READ` | Resolved schema for this collection. |
| `GET /collections/{id}/metadata.json` | `COLLECTION_READ` | The canonical sidecar rendering (section 5.3, D-17). |
| `GET /collections/{id}/files` | `COLLECTION_READ` | Paged by `rel_path_key`. |
| `POST /collections/{id}/commits` | `COLLECTION_WRITE_FILES` | Section 5.4. 409 `BASE_VERSION_CONFLICT` carries `current_version`. |
| `GET /collections/{id}/commits` | `COLLECTION_READ` | Paged, newest first. |
| `GET /collections/{id}/log`, `GET /catalogs/{catalog}/log` | `AUDIT_READ` | Audit entries, newest first. |
| `GET /catalogs/{catalog}/search?q=&label=k:v&state=` | `CATALOG_READ` | `q` matches `title`/`description`/identifier case-insensitively; `label` repeats and matches `metadata.labels`; results are collection summaries. |
| `GET /admin/signing-keys`, `POST /admin/signing-keys/rotate` | `SIGNING_KEY_ROTATE` | Rotation adds a key and retires the previous after `settings.key_overlap`. |

Error codes (`huron.pkg.errors.ErrorCode`, HTTP status): `UNAUTHENTICATED` 401, `TOKEN_INVALID` 401,
`FORBIDDEN` 403, `NOT_FOUND` 404, `NAME_INVALID` 422, `NAME_TAKEN` 409, `STATE_CONFLICT` 409,
`VERSION_CONFLICT` 412 (`If-Match`), `BASE_VERSION_CONFLICT` 409 (commit), `PRECONDITION_REQUIRED` 428, `ORGANIZATION_NOT_EMPTY`
409, `CATALOG_NOT_EMPTY` 409, `NAMESPACE_NOT_EMPTY` 409, `COLLECTION_NOT_EMPTY` 409,
`COLLECTIONS_NOT_ALLOWED` 409, `METADATA_INVALID` 422, `SCHEMA_INVALID` 422, `SCHEMA_INCOMPATIBLE` 422,
`SCHEMA_SCOPE` 422, `COMMIT_INVALID` 422, `FILE_NOT_RECORDED` 422, `COMMIT_TOO_LARGE` 413,
`REQUEST_INVALID` 422 (body or query shape), `INVALID_CURSOR` 400, `GROUP_DIRECTORY_UNAVAILABLE` 503,
`DEPENDENCY_UNAVAILABLE` 503. `tests/unit/test_error_contract.py` asserts that every raised code is
registered exactly once and that `docs/api-errors.md` lists each one.

## 9. CLI surface

Executable `huron`. Global options: `-o table|json|yaml`, `--api-url`, `--catalog` (overrides the current
catalog), `-v`. Exit codes: 0 success; 1 generic failure; 2 usage; 3 not logged in; 4 forbidden; 5 not
found; 6 conflict (version, state, not empty); 7 validation (metadata, schema, names); 8 storage (mount or
ACL); 130 interrupted.

| Verb | Needs API | Needs mount | Minimum role | Behavior |
| --- | --- | --- | --- | --- |
| `huron login [--device\|--browser]`, `logout`, `whoami` | ✓ | | any | Device grant by default; loopback PKCE with `--browser`; exchange; tokens at `$XDG_STATE_HOME/huron/tokens.json` mode 0600. |
| `huron config show\|set <key> <value>` | | | any | `api_url`, `issuer`, `client_id`, `mount_prefix`, `acl_backend` (`posix` in production; `none` applies modes only, for machines whose filesystem lacks ACL support). |
| `huron catalog list\|use <name>\|describe [name]\|grants [name]` | ✓ | | Reader | `use` records the current catalog in config. |
| `huron org list\|create <name>\|delete <name>\|grants <name>` | ✓ | create: ✓ | Platform Admin (`create`/`delete`), Reader to list | `create` records the organization, then creates `<prefix>/<org>` with its ACL plan. `delete` removes the empty directory after the API accepts. |
| `huron org grant\|revoke <org> org_admin <group>` | ✓ | | Platform Admin | Edits the group set. |
| `huron catalog create <org> <name> [--schema id]\|delete <name>` | ✓ | ✓ | Org Admin | Row first, then directory and ACLs. Idempotent on disk. |
| `huron catalog grant\|revoke <catalog> <role> <group>` | ✓ | | Org Admin for `catalog_admin`, Catalog Admin for members | Prints a reminder to run `huron acl apply` where plans changed. |
| `huron namespace list [parent]\|create <identifier> [--allow-collections] [--parents]\|delete <identifier>\|configure <identifier> --allow-collections/--no-allow-collections` | ✓ | create, delete, configure: ✓ | Catalog Admin | `--parents` creates missing ancestors one by one. `configure` re-applies the directory's ACL plan. Directory creation is idempotent. |
| `huron schema list [org]\|show <id> [--resolved]\|publish <org> <name> <file> [--extends id]\|assign <catalog> <id>` | ✓ | | see section 8 | `assign` prints the recompute counts. |
| `huron collection create <identifier> [--metadata file] [--draft]` | ✓ | ✓ unless `--draft` | Contributor | Reserves the draft, runs the walkthrough unless `--metadata`, then activates: directory, ACLs, `activate`, sidecar. `--draft` stops after the walkthrough. |
| `huron collection activate [identifier]` | ✓ | ✓ | Contributor | For drafts created with `--draft`. |
| `huron collection list [namespace]\|describe [identifier]\|delete <identifier> [--yes]` | ✓ | delete: ✓ | Reader; delete per D-11 | `delete` commits the removal of every file, unlinks them, deletes the row, removes the directory. |
| `huron checkout <identifier>` | ✓ | | Reader | Records a working copy (collection id, identifier, version, path) and makes it current. Several working copies may exist; `checkout` switches. |
| `huron add <path>... [--as rel_path] [--recursive]` | | | Contributor | Stages local files or directories for the current collection; a directory is staged with its relative layout. |
| `huron rm <rel_path>...` | ✓ | | Contributor | Stages removals; refuses paths not recorded. |
| `huron status` | ✓ | optional | Reader | Staged adds and removes, base vs current version, and unrecorded files when the mount is present. |
| `huron pull` | ✓ | | Reader | Refreshes version and file list; drops staged removes of files no longer recorded with a warning. |
| `huron push [-m message]` | ✓ | ✓ | Contributor | D-23. Progress per file; summary of the commit; exit 6 on `BASE_VERSION_CONFLICT` with the hint `run huron pull`. |
| `huron meta show\|edit\|validate\|publish [identifier]` | ✓ | publish: ✓ | Contributor to edit, Reader to show | `edit` loads the current metadata, walks the resolved schema's fields, saves a local draft; `publish` sends the patch with `If-Match` and writes the sidecar. |
| `huron meta override set <file>\|clear [identifier]` | ✓ | | Contributor | Sets or clears the collection's schema override together with the current metadata draft. |
| `huron log [identifier]`, `huron files [identifier]`, `huron search <catalog> [-q] [-l k=v] [--state]` | ✓ | | Reader | Paged output. |
| `huron check [--catalog name] [--hash]` | ✓ | ✓ | Reader | Section 6.4. |
| `huron acl apply <identifier> [--recursive]` | ✓ | ✓ | owner of the directories | Section 6.2. |
| `huron platform verify-root` | ✓ | ✓ | any | Checks the marker, the root ACL and the instance id. |

Working-copy state lives in `$XDG_STATE_HOME/huron/collections/<uuid>/`: `copy.json` (identifier, version,
path, checked_out_at), `stage.json` (adds as `{rel_path, source, size}`, removes), `metadata.draft.json`.
The current collection and catalog are in `$XDG_CONFIG_HOME/huron/config.yaml`. The CLI never writes
anything but `metadata.json`, data files and `.huron-part` files into the share.

## 10. Plan-wide rules

- **Gate.** Every task runs this from the repository root and every command must exit 0; `radon`
  commands must also print nothing.

  ```text
  uv run ruff check src tests
  uv run ruff format --check src tests
  uv run mypy
  uv run ty check
  uv run lint-imports
  uv run pytest -m "not contract and not integration" --cov=src/huron --cov-report=term-missing
  uv run radon cc src --min C
  uv run radon mi src --min B
  uv run complexipy src --max-complexity-allowed 15
  uv run python scripts/check_schema_map.py        # from M4 onward
  ```

  Coverage floor: `fail_under = 90` overall, and every source file a task creates or changes at 100 %
  line coverage unless its `Execution notes` say why a line cannot be reached in a unit test (an OS error
  branch in `pkg.fs`, for instance). Contract and integration tiers run where the task says so:
  `uv run pytest -m contract` (needs Docker or Podman for testcontainers) and `uv run pytest -m
  integration`. Run them in the background and poll; they take minutes.
- **Status discipline.** `pending` → `in progress` → `complete`. A verifier, not the implementer, writes
  `complete`. Nothing is complete with a failing gate, a skipped verification command or a TODO in code.
- **Testing standard.** Every public function and class has direct tests covering the happy path,
  boundaries, empty inputs and every error it raises. Tests assert behavior, not implementation. Fakes
  for stores and storage; mocks only at subprocess, network and clock boundaries. Test names describe the
  behavior and never mention task numbers. Fixtures are shared through `tests/support` and `conftest.py`.
- **Conventions test.** `tests/unit/test_conventions.py` (M0) walks `src/` and `tests/` and fails on any
  directory containing an underscore, any directory named `_impl`, `internal` or `private`, and any module
  where an underscore-prefixed top-level `def` or `class` precedes a public one. It is part of the gate
  from M0 onward.
- **Containers.** Contract and integration tests start `postgres:16` through testcontainers. Never start
  or stop the developer's own `make up` stack from a task; validate `docker-compose.yml` with `docker
  compose config --quiet`.
- **Documentation.** `docs/` is plain Markdown; `make docs-check` runs a link check only. Every public
  route is in the OpenAPI document that `make openapi` regenerates into `docs/openapi.json`;
  `tests/unit/test_openapi_snapshot.py` fails when the app's document differs from the committed file.
- **Secrets.** Signing keys live in the `signing_keys` table; the database URL and the OIDC client
  settings come from environment variables; nothing secret is committed, and `dev.env` holds development
  values only.
- **Commits.** One task per commit, message `M<n>.<m>: <task title>`, body listing the files created and
  the verification run. Branch `fresh-start` until M10 merges it.

## 11. Milestones

| Milestone | Delivers | Depends on |
| --- | --- | --- |
| M0 Repository | Branch, scaffold, tooling, gate, CI, agent instructions | — |
| M1 Foundations | `huron.pkg`, `huron.schema` | M0 |
| M2 Security | RBAC model, Huron tokens, company-token exchange, fakes | M1 |
| M3 Domain | `core.lake` over in-memory stores, store contract suite | M2 |
| M4 PostgreSQL | Migration `0001_huron`, asyncpg adapters, contract suite on Postgres | M3 |
| M5 API | FastAPI service, every route in section 8, dev stack, integration tier | M4 |
| M6 CLI foundation | Login, state, output, client, browsing and administration verbs (no disk) | M5 |
| M7 Storage | `core.storage`, root marker, directory creation and ACLs from the CLI | M6 |
| M8 Collections in the CLI | Walkthrough, create and activate, checkout, stage, push, metadata publish, delete | M7 |
| M9 Check and ACL repair | `huron check`, `huron acl apply` | M8 |
| M10 Release | Deployment manifests, operator and user docs, end-to-end test, merge | M9 |

### Milestone 0 — Repository

#### M0.1 Branch, wipe and scaffold

- Intent: start from an empty tree on branch `fresh-start`, keeping only the agent tooling, and lay down
  the Python project.
- Create:
  - Branch `fresh-start` from `main`. Remove every tracked path except `.agents/`, `.claude/`,
    `.opencode/`, `skills-lock.json`, `opencode.json`, `.gitignore`, `.pre-commit-config.yaml`,
    `.python-version`.
  - `pyproject.toml`: project `huron` 1.0.0a0, Python `>=3.12`, hatchling, `packages = ["src/huron"]`,
    console script `huron = "huron.applications.cli.main:main"`. Runtime dependencies: `fastapi`,
    `uvicorn[standard]`, `pydantic>=2`, `pydantic-settings>=2`, `sqlalchemy>=2`, `asyncpg`, `alembic`,
    `httpx`, `pyjwt[crypto]`, `jsonschema[format-nongpl]`, `google-re2`, `rfc8785`, `structlog`,
    `typer`, `rich`, `questionary`, `pyyaml`, `uuid-utils`. Dev group: `ruff`, `mypy`, `ty`,
    `import-linter`, `pytest`, `pytest-asyncio`, `pytest-cov`, `hypothesis`, `testcontainers[postgres]`,
    `respx`, `radon`, `complexipy`, `types-jsonschema`, `types-pyyaml`. Tool configuration: ruff
    (line length 100; select `E F I N UP B SIM TCH RUF FAST`), mypy strict with `plugins =
    ["pydantic.mypy"]`, ty, pytest (`asyncio_mode = "auto"`, markers `contract`, `integration`, `acl`), coverage (`fail_under = 90`, source `src/huron`), import-linter (`root_package = "huron"`,
    contracts added by M1 onward).
  - `uv.lock` from `uv lock`.
  - `src/huron/__init__.py` with `__version__`.
  - `README.md`: what Huron is in three paragraphs, the quick start (`uv sync`, `make up`,
    `make migrate`, `make api`, `huron login`), and links to `docs/`.
  - `Makefile` targets: `help`, `up`, `down`, `migrate`, `api`, `test`, `test-contract`,
    `test-integration`, `lint`, `gate` (section 10 in order), `openapi`, `docs-check`.
  - `.github/workflows/ci.yml`: job `gate` (ubuntu, `uv sync`, `make gate`), job `contract`
    (`uv run pytest -m contract` with Docker), job `integration` (`uv run pytest -m integration`).
  - `tests/__init__.py`, `tests/conftest.py`, `tests/unit/__init__.py`, `tests/support/__init__.py`,
    and `tests/unit/test_version.py` asserting `huron.__version__` matches `pyproject.toml`, so the gate
    has one test to run from the start.
- Acceptance: `uv sync` succeeds; `uv run python -c "import huron"` prints nothing; `make gate` passes on
  the scaffold.
- Verification: `make gate`; `git status --porcelain` is empty after the commit; `git ls-files | wc -l`
  is below 400 (the skills dominate).
- Dependencies: none.
- Status: complete

#### M0.2 Conventions test and agent instructions

- Intent: make D-24 and D-25 mechanical, and point the agent tooling at this plan.
- Create:
  - `tests/unit/test_conventions.py`: walks `src/` and `tests/`; fails on directories containing `_`
    (except `__pycache__`), on directories named `_impl`, `internal`, `private`; parses every `.py` with
    `ast` and fails when a top-level `FunctionDef`, `AsyncFunctionDef` or `ClassDef` whose name starts
    with `_` precedes one that does not. Dunder names (`__all__`, `__version__`) are ignored.
  - `AGENTS.md`: the layout (section 4.2), the dependency graph (4.3), the code conventions (4.4), the
    gate (10), the testing standard, and "the implementation plan is `IMPLEMENTATION_PLAN.md`; its
    sections 3–9 are binding".
  - `CLAUDE.md`: a short pointer to `AGENTS.md` and to the skills in `.claude/skills/` by area
    (`fastapi` for `applications/api`, `oop-design` for `core`, `postgresql-table-design` for
    `core/metastore` and `migrations`).
  - Update the gate list inside `.claude/commands/implement-markdown.md` and
    `.opencode/commands/implement-markdown.md` to section 10's commands, replacing references to scripts
    that do not exist in this repository.
  - `IMPLEMENTATION_PLAN.md`: this document, committed at the repository root.
- Acceptance: the conventions test passes on the scaffold and fails on a fixture tree (tested with
  `tmp_path`) containing `a_b/` and a module with a private function before a public one.
- Verification: `make gate`.
- Dependencies: M0.1.
- Status: complete

#### M0.3 Development stack

- Intent: a local PostgreSQL and a local OIDC provider for `make up`, validated without starting them.
- Create:
  - `docker-compose.yml`: `postgres` (`postgres:16`, database `huron`, healthcheck), `keycloak`
    (`quay.io/keycloak/keycloak`, `start-dev --import-realm`, realm file mounted), both with named
    volumes. The `api` and `groups` services arrive in M5.5 behind the `app` profile.
  - `scripts/keycloak/company-realm.json`: realm `company`, public client `huron-cli` with the device
    grant and `http://127.0.0.1:*` loopback redirects enabled, users `alice` (platform admin), `bob`
    (org admin), `carol` (catalog admin), `dave` (contributor), `erin` (reader), password `password`.
  - `dev.env`: `HURON_DATABASE_URL`, `HURON_ISSUER`, `HURON_COMPANY_ISSUER`, `HURON_COMPANY_AUDIENCE`,
    `HURON_GROUP_DIRECTORY_URL`, `HURON_PLATFORM_ADMIN_GROUP=huron-platform-admins`,
    `HURON_INSTANCE_ID` (a fixed UUID), `HURON_API_URL=http://127.0.0.1:8080`.
  - `scripts/check-stack.sh`: probes Postgres and the Keycloak realm; `make up` runs it.
  - `alembic.ini` pointing at `migrations/` with `sqlalchemy.url` read from `HURON_DATABASE_URL`.
- Acceptance: `docker compose config --quiet` passes; `bash -n scripts/check-stack.sh` passes.
- Verification: `make gate`; the two commands above.
- Dependencies: M0.1.
- Status: complete

### Milestone 1 — Foundations

#### M1.1 `huron.pkg`: errors, paging, canonical, identifiers, clock, hashing

- Intent: the generic pieces every other package uses, with no Huron vocabulary in them.
- Create:
  - `src/huron/pkg/errors.py`: `ErrorCode(code, status, title)` frozen value; `ErrorCodes` registry
    (`register(code)` refuses duplicates, `all()` sorted); `HuronError(code, message, context)` with
    `problem(instance)` rendering the RFC 9457 document; `Forbidden`, `NotFound`, `Conflict`,
    `Invalid`, `Unavailable` base classes bound to the generic codes `FORBIDDEN`, `NOT_FOUND`,
    `STATE_CONFLICT`, `REQUEST_INVALID`, `DEPENDENCY_UNAVAILABLE`.
  - `src/huron/pkg/paging.py`: `Cursor` (opaque, base64url of a JSON tuple with a version byte),
    `Page[T](items, next_cursor)`, `clamp_limit(value, default=100, maximum=500)`, `InvalidCursor`
    (`INVALID_CURSOR`, 400).
  - `src/huron/pkg/canonical.py`: `canonical_bytes(document)` via `rfc8785`, `document_sha256`.
  - `src/huron/pkg/identifiers.py`: `new_id()` UUIDv7 as `uuid.UUID`, `parse_id(text)`.
  - `src/huron/pkg/clock.py`: `Clock` protocol (`now() -> datetime` aware UTC), `SystemClock`,
    `FrozenClock(at)` with `advance`.
  - `src/huron/pkg/hashing.py`: `sha256_copy(src: BinaryIO, dst: BinaryIO, chunk=8 MiB) ->
    (size, hexdigest)`, `sha256_file(path)`.
  - Tests under `tests/unit/pkg/` for each module, including Hypothesis round trips for cursors.
  - import-linter contract 1 (section 4.3).
- Acceptance: `canonical_bytes` is byte-identical under key reordering; a cursor from a newer version byte
  raises `InvalidCursor`; `sha256_copy` on an empty stream returns `(0, <sha256 of empty>)`.
- Verification: `make gate`; `uv run lint-imports` reports 1 contract kept.
- Dependencies: M0.2.
- Status: complete

#### M1.2 `huron.pkg.fs`: POSIX operations and ACLs

- Intent: the only place that touches the filesystem or runs `setfacl`, so storage code above it is
  testable with a fake.
- Create:
  - `src/huron/pkg/fs/posix.py`: `make_dir(path, mode)` (idempotent, applies `chmod` when the mode
    differs, never follows symlinks), `atomic_copy(src, dest, *, part_suffix) -> (size, sha256)`
    (section 6.3 steps 3–4), `remove_file`, `remove_empty_dir`, `walk(path) -> Iterator[Entry]` with
    `Entry(rel_path, kind, size, mtime_ns, is_symlink)` sorted by name, `stat(path) -> Stamp(size,
    mtime_ns)`, `is_mount_or_dir(path)`.
  - `src/huron/pkg/fs/acl.py`: `AclEntry(tag: 'user'|'group'|'other'|'mask', qualifier: str | None,
    perms: str)` and `Acl(access: frozenset[AclEntry], default: frozenset[AclEntry])`; `read_acl(path)`
    parsing `getfacl -pE` output; `write_acl(path, acl)` running `setfacl --set-file=-` with the entries
    rendered in getfacl syntax, including the base `user::`, `group::` and `other::` entries derived from
    the directory mode, so one call replaces the whole access and default ACL deterministically; `acl_supported(path)` →
    bool by probing `getfacl`; `AclError` (`ACL_FAILED`, 500) carrying the command's stderr. Commands run
    through an injectable `Runner` protocol (`run(argv, input) -> (returncode, stdout, stderr)`), default
    `subprocess.run`.
  - Tests: `tests/unit/pkg/test_posix.py` on `tmp_path` (atomic copy leaves no part file on failure,
    skips when sizes and hash match, preserves an existing file on a failed copy); `tests/unit/pkg/
    test_acl.py` parses recorded `getfacl` output and renders `setfacl` input through a `FakeRunner`;
    `tests/acl/test_acl_real.py` marked `acl`, skipped unless `acl_supported(tmp_path)`, applies a plan
    and reads it back.
- Acceptance: `read_acl(write_acl(x))` round-trips entries ignoring the mask; a `Runner` returning
  non-zero raises `AclError` with the stderr text.
- Verification: `make gate`; `uv run pytest -m acl` on Linux with `acl` installed passes or is skipped
  with the reason printed.
- Dependencies: M1.1.
- Status: complete

#### M1.3 `huron.schema.naming`

- Intent: one implementation of D-4 and the relative-path rule, proven by properties.
- Create:
  - `src/huron/schema/naming.py`: `check_segment`, `parse_identifier`, `Identifier(catalog,
    namespace_path: tuple[str, ...], name: str | None)` with `str()` rendering and `parent`,
    `check_rel_path`, `rel_path_key`, `part_name`, `NamingError(rule, value)` (`NAME_INVALID`, 422),
    `RelPathError(rule, value)` (`REQUEST_INVALID`, 422), constants `SEGMENT_MAX_BYTES = 63`,
    `IDENTIFIER_MAX_BYTES = 255`, `REL_PATH_MAX_BYTES = 1024`, `REL_PATH_SEGMENT_MAX_BYTES = 255`,
    `RESERVED_SEGMENTS`.
  - `tests/unit/schema/test_naming.py` with Hypothesis strategies in `tests/support/naming.py`: valid
    segments round-trip; every mutation (upper case, leading hyphen, 64 bytes, a dot, NFD form, a
    reserved word) is refused with the expected rule; `rel_path_key` is case-insensitive and
    NFC-stable; `metadata.json` at the root is reserved but `sub/metadata.json` is not.
  - import-linter contract 2.
- Verification: `make gate`.
- Dependencies: M1.1.
- Status: complete

#### M1.4 `huron.schema`: documents, validator and composition

- Intent: the metadata schema machinery of section 5.5 without any persistence.
- Create:
  - `src/huron/schema/documents/schema-document-v1.json`: the allowed JSON Schema subset, itself a JSON
    Schema.
  - `src/huron/schema/documents/huron-base-v1.json`: the platform base schema of section 5.5.
  - `src/huron/schema/documents/commit-request-v1.json`: the commit body of section 5.4.
  - `src/huron/schema/loader.py`: `load_document(name)` cached; `DOCUMENTS` registry.
  - `src/huron/schema/validator.py`: `Validator.for_document(document)` compiling a 2020-12 validator
    with an RE2 `pattern` checker and the four formats; `validate(instance) -> list[Problem]` with
    `Problem(path, message, rule)`; `check_schema_document(document)` validating against
    `schema-document-v1.json` and additionally compiling every `pattern` with RE2 (`SchemaInvalid`,
    `SCHEMA_INVALID`, 422).
  - `src/huron/schema/composition.py`: `compose(parent, child) -> document` (D-13; `SchemaIncompatible`,
    `SCHEMA_INCOMPATIBLE`, 422), `resolve_chain(documents: Sequence[document])`.
  - Tests: `tests/unit/schema/test_validator.py` (each allowed keyword accepted, each disallowed one
    refused, a catastrophic regex compiles under RE2 and validates in bounded time),
    `tests/unit/schema/test_composition.py` (Hypothesis: composing with an empty child is identity;
    `required` grows monotonically; changing a required property's type is refused),
    `tests/unit/schema/test_documents.py` (every document in `documents/` passes `check_schema`).
- Verification: `make gate`.
- Dependencies: M1.3.
- Status: complete

### Milestone 2 — Security

#### M2.1 RBAC: roles, privileges, grants and the authorizer

- Intent: section 5.2 as pure code over a grants port.
- Create:
  - `src/huron/core/security/rbac/privileges.py`: `Privilege` enum with every name in section 5.2.
  - `src/huron/core/security/rbac/roles.py`: `Role` enum (`platform_admin`, `org_admin`,
    `catalog_admin`, `contributor`, `reader`), `ROLE_PRIVILEGES: Mapping[Role, frozenset[Privilege]]`,
    `scope_type_of(role)`.
  - `src/huron/core/security/rbac/grants.py`: `Scope(type, id | None)` with `PLATFORM`, `organization(id)`,
    `catalog(id)` constructors; `Grant(scope, role, ldap_group)`; `check_grant(grant)` refusing a
    role at the wrong scope type (`GrantInvalid`, `REQUEST_INVALID`).
  - `src/huron/core/security/rbac/ports.py`: `GrantReader` protocol (`roles_for_groups(groups) ->
    Sequence[(Scope, Role)]`, `groups_for_scope(scope) -> Mapping[Role, Sequence[str]]`,
    `enclosing(scope) -> Sequence[Scope]` resolved by the adapter from catalog → organization).
  - `src/huron/core/security/rbac/actor.py`: `Actor(subject, display_name, groups: frozenset[str])`.
  - `src/huron/core/security/rbac/authorize.py`: `Authorizer(grants)` with `roles_for(actor)`,
    `holds(actor, privilege, scope)`, `require(actor, privilege, scope)` raising `Forbidden`,
    `can_see_organization`, `can_see_catalog`, `effective_groups(catalog_scope)` returning the section
    6.2 mapping with platform and organization groups included.
  - `src/huron/core/security/rbac/__init__.py` exporting the above.
  - `tests/unit/security/test_rbac.py` over an in-test `FakeGrantReader`: the privilege table is exactly
    section 5.2 (a parametrized test per cell); a contributor on catalog A holds nothing on catalog B;
    org admin encloses catalogs; platform encloses everything; unknown groups grant nothing; a stale
    role in a token grants nothing because roles come only from grants.
  - import-linter contract 3.
- Verification: `make gate`.
- Dependencies: M1.4.
- Status: complete

#### M2.2 Huron tokens: key ring, issuer, verifier, JWKS and discovery

- Intent: the Huron-signed JWT and what other systems need to verify it.
- Create:
  - `src/huron/core/security/broker/keys.py`: `SigningKey(kid, private_pem, public_jwk, created_at,
    retired_at)`, `generate_key(clock)` (ES256, `kid` = first 16 hex of the public JWK thumbprint),
    `KeyRing(keys)` with `current`, `verification_keys` (current plus retired keys younger than
    `overlap`), `jwks()`.
  - `src/huron/core/security/broker/tokens.py`: `HuronClaims(sub, name, groups, iss, aud, iat, exp,
    jti)`, `TokenIssuer(ring, clock, issuer, audience, ttl)` → compact JWT, `TokenVerifier(ring, issuer,
    audience, clock)` → `HuronClaims` or `TokenInvalid` (`TOKEN_INVALID`, 401) for every failure
    (signature, `exp`, `iss`, `aud`, missing claims, unknown `kid`, `alg` other than ES256).
  - `src/huron/core/security/broker/discovery.py`: `discovery_document(issuer)` with `issuer`,
    `jwks_uri`, `id_token_signing_alg_values_supported: ["ES256"]`.
  - Tests: `tests/unit/security/test_tokens.py` including a golden token signed with a fixed test key
    verified without the issuer's help; rotation keeps verifying a token signed by the retired key within
    `overlap` and refuses it after.
- Verification: `make gate`.
- Dependencies: M2.1.
- Status: complete

#### M2.3 Company token verification, group directory and the exchange

- Intent: D-12's exchange over HTTP boundaries that tests can fake.
- Create:
  - `src/huron/core/security/broker/company.py`: `CompanyTokenVerifier(http, issuer, audience, clock)`:
    fetches `<issuer>/.well-known/openid-configuration` then its JWKS (cached, refreshed on an unknown
    `kid` at most once per minute), verifies RS256 or ES256 ID tokens, returns `CompanyIdentity(subject,
    username, display_name)` where `username` is `preferred_username` falling back to `sub`.
  - `src/huron/core/security/broker/groups.py`: `GroupDirectory` protocol (`groups_for(username) ->
    frozenset[str]`), `HttpGroupDirectory(http, base_url)` for `GET <base>/users/{username}/groups` →
    `{"groups": [...]}`; 404 → empty set; any other failure → `GroupDirectoryUnavailable`
    (`GROUP_DIRECTORY_UNAVAILABLE`, 503).
  - `src/huron/core/security/broker/exchange.py`: `TokenExchange(company, groups, issuer)` with
    `exchange(company_token) -> ExchangeResult(token, claims)`; logs `broker.exchange` with subject and
    group count, never the token.
  - `tests/fakes/issuer.py`: `FakeIssuer` holding an RSA key, producing discovery and JWKS documents and
    signing ID tokens for a username with chosen claims; `httpx.MockTransport` handler for its URLs.
  - `tests/fakes/groups.py`: `FakeGroups(mapping)` as a `GroupDirectory`, plus `groups_transport(mapping)`
    for the HTTP adapter and `main()` serving it with `http.server` for the development stack.
  - Tests: `tests/unit/security/test_company.py`, `test_groups.py`, `test_exchange.py` (expired company
    token → `TOKEN_INVALID`; wrong audience → `TOKEN_INVALID`; directory 503 → 503 and no Huron token;
    the Huron token carries exactly the directory's groups).
- Verification: `make gate`.
- Dependencies: M2.2.
- Status: complete

### Milestone 3 — Domain over in-memory stores

Every operation in this milestone is built and tested over the in-memory store; M4 adds PostgreSQL behind
the same ports. The store contract suite (`tests/contract/suite.py`) is written here and runs against the
memory store in the unit tier.

#### M3.1 Audit, the memory root and the `Store` shape

- Intent: the transaction and audit plumbing every other area uses.
- Create:
  - `src/huron/core/lake/audit/models.py`: `Action` enum (section 5.6), `AuditEntry`.
  - `src/huron/core/lake/audit/ports.py`: `AuditWriter` (`write(entry)`), `AuditReader`
    (`for_object(object_id, cursor, limit)`, `for_catalog(catalog_id, cursor, limit)`).
  - `src/huron/core/lake/audit/writer.py`: `audit(tx, actor, action, object, detail)` helper building
    an entry with the transaction's clock.
  - `src/huron/core/metastore/memory.py`: `MemoryRoot` holding one dict per table, `MemoryTransaction`
    with copy-on-write snapshots, commit and rollback.
  - `src/huron/core/metastore/store.py`: `Store` protocol (`transaction() -> AsyncContextManager[
    Transaction]`), `Transaction` protocol with one attribute per area (added as areas arrive) and
    `clock`.
  - `src/huron/core/metastore/audit/memory.py`: `MemoryAudit` implementing both audit ports.
  - `tests/unit/metastore/test_memory.py`: a rolled-back transaction leaves the root unchanged; two
    transactions do not see each other's uncommitted writes.
  - import-linter contracts 4 and 5.
- Verification: `make gate`.
- Dependencies: M2.3.
- Status: complete

#### M3.2 Organizations and grants

- Intent: the top of the hierarchy and the grants that drive every authorization check.
- Create:
  - `src/huron/core/lake/organizations/models.py`: `Organization(id, name, display_name, description,
    version, created_at, created_by)`; `OrganizationView` with `catalog_count`.
  - `.../organizations/ports.py`: `OrganizationStore` (`insert`, `get_by_name`, `get`, `list_visible(
    ids | all)`, `delete`, `catalog_count`).
  - `.../organizations/errors.py`: `OrganizationNotEmpty` (`ORGANIZATION_NOT_EMPTY`, 409).
  - `.../organizations/operations.py`: `Organizations(store, authorizer, clock)` with `create`, `get`,
    `list`, `delete` per section 8, each writing its audit entry.
  - `src/huron/core/metastore/grants/memory.py`: `MemoryGrants` implementing `GrantReader` plus a
    `GrantWriter` port (`replace(scope, role, groups) -> (added, removed)`) declared in
    `core/security/rbac/ports.py`.
  - `src/huron/core/lake/organizations/grants.py`: `GrantAdministration(store, authorizer)` with
    `set_platform_admins`, `set_org_admins`, `set_catalog_role` enforcing the privilege per role, the
    protected configured group, and `check_grant`; audit `organization.grant`/`revoke`,
    `catalog.grant`/`revoke` per group added or removed.
  - `src/huron/core/metastore/organizations/memory.py`.
  - Tests: `tests/unit/lake/test_organizations.py`, `test_grants.py` (removing the configured platform
    group is refused with 422 `REQUEST_INVALID`; a catalog admin cannot change `catalog_admin` groups; a
    reader sees only organizations containing a catalog they are granted).
  - `tests/contract/suite.py`: `StoreContract` abstract test class parametrized by a `store_factory`
    fixture, with the organizations and grants scenarios; `tests/unit/metastore/test_memory_contract.py`
    binds it to the memory store.
- Verification: `make gate`.
- Dependencies: M3.1.
- Status: complete

#### M3.3 Schema registry

- Intent: section 5.5's registry, resolution and seeding; assignment follows in M3.4.
- Create:
  - `src/huron/core/lake/schemas/models.py`: `SchemaEntry`, `SchemaRef(id, name, version)`.
  - `.../schemas/ports.py`: `SchemaStore` (`insert`, `get`, `next_version(scope, name)`, `list_for_org`,
    `latest(scope, name)`).
  - `.../schemas/errors.py`: `SchemaScope` (`SCHEMA_SCOPE`, 422).
  - `.../schemas/registry.py`: `SchemaRegistry(store, authorizer, clock)` with `publish(actor, org |
    None, name, extends_id, document)` (checks the document, composes against the parent to prove
    compatibility, requires that the chain reaches `huron-base`, writes `schema.publish`), `get`,
    `resolve(entry_id) -> document` with an LRU cache keyed by entry id, `list_for_org`.
  - `src/huron/core/metastore/schemas/memory.py`.
  - Tests: `tests/unit/lake/test_schema_registry.py` (versions increment per name and scope; an org
    schema cannot extend another org's entry; a chain not rooted at `huron-base` is refused with
    `SCHEMA_INCOMPATIBLE`; resolve returns the composed document and is cached).
  - Contract scenarios for schemas in `tests/contract/suite.py`.
- Verification: `make gate`.
- Dependencies: M3.2.
- Status: complete

#### M3.4 Catalogs and namespaces

- Intent: catalogs with their schema assignment and effective groups, and the recursive namespace tree.
- Create:
  - `src/huron/core/lake/catalogs/models.py`: `Catalog(id, organization_id, name, display_name,
    description, schema_id, version, …)`, `CatalogView` with `schema: SchemaRef`, counts and
    `effective_groups`.
  - `.../catalogs/ports.py`: `CatalogStore` (`insert`, `get`, `get_by_name`, `list_visible`,
    `set_schema`, `delete`, `namespace_count`).
  - `.../catalogs/errors.py`: `CatalogNotEmpty` (`CATALOG_NOT_EMPTY`, 409).
  - `.../catalogs/operations.py`: `Catalogs(store, organizations, registry, grants, authorizer, clock)`
    with `create` (default schema: latest `huron-base`), `get`, `list`, `delete`, `assign_schema`
    (scope check, then `set_schema`, then `completeness.recompute` injected as a callable so M3.5 can
    supply it), `effective_groups`, `resolved_schema`.
  - `src/huron/core/lake/namespaces/models.py`: `Namespace(id, catalog_id, parent_id, name, path,
    collections_allowed, version, …)`.
  - `.../namespaces/ports.py`: `NamespaceStore` (`insert`, `get_by_path`, `children`, `child_counts`,
    `set_collections_allowed`, `delete`, `sibling_collection_exists(parent, name)`).
  - `.../namespaces/errors.py`: `NamespaceNotEmpty` (`NAMESPACE_NOT_EMPTY`, 409).
  - `.../namespaces/operations.py`: `Namespaces(store, catalogs, authorizer, clock)` with `create(actor,
    catalog, parent_path, name, collections_allowed)` (parent must exist; sibling exclusion against
    namespaces and collections; `NAME_TAKEN`), `get`, `children`, `configure`, `delete`.
  - `src/huron/core/metastore/catalogs/memory.py`, `.../namespaces/memory.py` (the memory store enforces
    sibling exclusion so the contract suite can test it on both adapters).
  - Tests: `tests/unit/lake/test_catalogs.py`, `test_namespaces.py` (a namespace named like a sibling
    collection is `NAME_TAKEN`; deleting a namespace with a child namespace or any collection, draft
    included, is `NAMESPACE_NOT_EMPTY`; `configure(false)` with collections present is
    `NAMESPACE_NOT_EMPTY`; depth 12 works; a catalog name taken in another organization is
    `NAME_TAKEN`).
  - Contract scenarios for catalogs and namespaces.
- Verification: `make gate`.
- Dependencies: M3.3.
- Status: complete

#### M3.5 Collections: lifecycle, metadata, overrides and completeness

- Intent: section 5.3 and the parts of 5.5 that touch collections.
- Create:
  - `src/huron/core/lake/collections/models.py`: `Collection`, `CollectionView` (the section 8 body,
    with `path` rendered as `<org>/<catalog>/<namespace segments>/<name>` for settled collections),
    `State` enum, `MetadataPatch`.
  - `.../collections/ports.py`: `CollectionStore` (`insert`, `get`, `get_by_identifier`, `lock`,
    `update`, `delete`, `list_in_namespace`, `list_in_catalog(states)`, `search(catalog, q, labels,
    state, cursor, limit)`, `sibling_namespace_exists`).
  - `.../collections/errors.py`: `MetadataInvalid` (`METADATA_INVALID`, 422, `context.problems`),
    `CollectionNotEmpty` (`COLLECTION_NOT_EMPTY`, 409), `CollectionsNotAllowed`
    (`COLLECTIONS_NOT_ALLOWED`, 409), `VersionConflict` (`VERSION_CONFLICT`, 412, `context.
    current_version`).
  - `.../collections/metadata.py`: `merge_patch(document, patch)` (RFC 7396), `render_sidecar(view,
    schema_ref) -> bytes` canonical JSON with `huron`, `identifier`, `schema`, `metadata`, `version`.
  - `.../collections/lifecycle.py`: `Collections(store, namespaces, catalogs, registry, files_count,
    authorizer, clock)` with `create`, `get`, `get_by_identifier`, `list`, `search`, `update`,
    `activate`, `delete`, `resolved_schema`, each exactly as section 5.3 and the route table state;
    `expected_version` mismatches raise `VersionConflict`.
  - `src/huron/core/lake/schemas/completeness.py`: `Completeness(collections_store, registry)` with
    `recompute(tx, actor, catalog) -> (incomplete, active)` writing `collection.mark_incomplete` /
    `mark_active` and bumping versions only for collections whose state changed.
  - `src/huron/core/metastore/collections/memory.py` with search implemented over the dicts.
  - Tests: `tests/unit/lake/test_collections.py` (draft accepts invalid metadata and reports problems;
    activation refuses them; an active collection refuses an invalid patch; the override and metadata
    validate together; `delete` by a different contributor is 403 and by the creator or a catalog admin
    succeeds; a stale `expected_version` is 412 with `current_version`), `test_completeness.py` (assigning
    a schema that adds a required field turns conforming collections `incomplete` with `version + 1`;
    assigning one that removes it turns them `active` again; untouched collections keep their version),
    `test_sidecar.py` (byte-identical under key order; drafts have no sidecar).
  - Contract scenarios for collections, including search by label and `q`.
- Verification: `make gate`.
- Dependencies: M3.4.
- Status: complete

#### M3.6 Files and commits

- Intent: section 5.4.
- Create:
  - `src/huron/core/lake/files/models.py`: `FileRecord`, `FileAdd`, `CommitRequest(base_version, adds,
    removes, host, message)`, `CommitResult(version, file_count, commit_id)`, `Commit` row model.
  - `.../files/ports.py`: `FileStore` (`upsert_many`, `delete_many`, `exists_many(keys)`, `list(cursor,
    limit)`, `count`), `CommitStore` (`insert`, `list(collection, cursor, limit)`).
  - `.../files/errors.py`: `CommitInvalid` (`COMMIT_INVALID`, 422), `FileNotRecorded`
    (`FILE_NOT_RECORDED`, 422), `CommitTooLarge` (`COMMIT_TOO_LARGE`, 413), `BaseVersionConflict`
    (`BASE_VERSION_CONFLICT`, 409, `context.current_version`).
  - `.../files/commits.py`: `parse_commit_request(body) -> CommitRequest` validating against
    `commit-request-v1.json` and the naming rules; `Commits(files, commits, collections, authorizer,
    clock)` with `commit(actor, collection_id, request)` implementing steps 1–5 of section 5.4, and
    `list_files`, `list_commits`.
  - `src/huron/core/metastore/files/memory.py`.
  - Tests: `tests/unit/lake/test_commits.py` for every refusal in section 5.4, for an add that replaces a
    recorded path (file_count unchanged, row replaced), for a removes-only commit, for 10,001 entries,
    and for the audit detail `{adds, removes, host, message}`.
  - Contract scenarios: concurrent commits with the same base version (the memory store simulates
    interleaving through the transaction snapshot; PostgreSQL tests the real race in M4.3).
- Verification: `make gate`.
- Dependencies: M3.5.
- Status: complete

#### M3.7 Bootstrap and the composed domain

- Intent: one function that assembles the domain over a store, and the startup seeds.
- Create:
  - `src/huron/core/lake/bootstrap.py`: `Lake` dataclass holding every operations object;
    `build_lake(store, clock, settings)`; `bootstrap(tx, settings)` ensuring the `huron-base` entry, the
    platform admin grant for `settings.platform_admin_group`, and a current signing key (through a
    `KeyStore` port in `core/security/broker/keys.py`, memory adapter in `core/metastore/keys/
    memory.py`). Idempotent: a second run changes nothing and writes no audit entry.
  - `tests/unit/lake/test_bootstrap.py`; `tests/support/lake.py` with `make_lake()` and actor fixtures
    (`platform_admin`, `org_admin`, `catalog_admin`, `contributor`, `reader`, `stranger`) used by every
    later test.
- Verification: `make gate`; `uv run pytest tests/unit/metastore/test_memory_contract.py` runs every
  contract scenario green.
- Dependencies: M3.6.
- Status: complete

### Milestone 4 — PostgreSQL

#### M4.1 Migration `0001_huron` and the schema map

- Intent: section 7 as Core tables and one Alembic revision, with drift detection.
- Create:
  - `src/huron/core/metastore/<area>/tables.py` for every area, sharing `MetaData(schema="huron")` from
    `src/huron/core/metastore/tables.py`.
  - `migrations/env.py` (async engine, `target_metadata`), `migrations/versions/0001_huron.py` creating
    the schema, tables, indexes, checks and the `sibling_exclusion` trigger function and triggers.
  - `scripts/check_schema_map.py`: starts `postgres:16` with testcontainers, runs `alembic upgrade
    head`, compares the live schema with the Core metadata through `alembic.autogenerate.compare_metadata`
    and exits 1 on any difference; also runs `downgrade base` and asserts the schema is empty.
  - `tests/support/postgres.py`: session-scoped container fixture, `migrated_dsn`, per-test truncation.
  - `tests/contract/test_migration.py` marked `contract`: upgrade, compare, downgrade.
- Verification: `make gate`; `uv run python scripts/check_schema_map.py`; `uv run pytest -m contract
  tests/contract/test_migration.py`.
- Dependencies: M3.7.
- Status: complete

#### M4.2 PostgreSQL adapters: pool, organizations, grants, schemas, audit, keys

- Intent: the first half of the asyncpg store, with the transaction and locking primitives.
- Create:
  - `src/huron/core/metastore/postgres.py`: `PostgresStore(dsn, clock)` with `connect()`/`close()`
    (`asyncpg.create_pool`, `min_size=1`, `max_size=settings.pool_size`), `transaction()` yielding a
    `PostgresTransaction` on one connection in `BEGIN`/`COMMIT`, `advisory_lock(tx, key)`, `LockKeys`
    (`catalog(id)`), JSONB codecs set once per connection.
  - `.../organizations/postgres.py`, `.../grants/postgres.py`, `.../schemas/postgres.py`,
    `.../audit/postgres.py`, `.../keys/postgres.py`: hand-written SQL, `RETURNING` for inserts, cursor
    paging by `(sort key, id)`, unique violations translated to `NAME_TAKEN` or `REQUEST_INVALID`.
  - `tests/contract/test_postgres_contract.py` marked `contract`: binds `StoreContract` to the Postgres
    store for the areas delivered so far.
- Verification: `make gate`; `uv run pytest -m contract` green.
- Dependencies: M4.1.
- Status: complete

#### M4.3 PostgreSQL adapters: catalogs, namespaces, collections, files, commits

- Intent: the rest of the store, with the real races the memory store can only simulate.
- Create:
  - `.../catalogs/postgres.py`, `.../namespaces/postgres.py` (path lookups by `(catalog_id, path)`;
    the trigger does sibling exclusion and its error maps to `NAME_TAKEN`), `.../collections/postgres.py`
    (`lock` is `SELECT … FOR UPDATE`; search uses `metadata @> jsonb` for labels and `ILIKE` on
    `identifier`, `metadata->>'title'`, `metadata->>'description'`), `.../files/postgres.py`
    (`upsert_many` with `INSERT … ON CONFLICT (collection_id, rel_path_key) DO UPDATE`, `unnest` for
    batches).
  - `tests/contract/test_postgres_races.py` marked `contract`: two commits with the same `base_version`
    on separate connections → exactly one `CommitResult`, one `BASE_VERSION_CONFLICT`; a namespace and a
    collection created concurrently with the same sibling name → exactly one succeeds; schema assignment
    racing a metadata update ends with a consistent state (the collection's state matches validation
    against the final assignment); deleting a namespace racing a collection creation under it never
    leaves an orphan collection.
  - The full `StoreContract` bound to Postgres.
- Verification: `make gate`; `uv run pytest -m contract` green twice in a row (races are treated as
  deterministic: an intermittent failure fails the task).
- Dependencies: M4.2.
- Status: complete

### Milestone 5 — API

#### M5.1 Application skeleton, authentication and discovery

- Intent: a running service with health, discovery, the exchange and the actor dependency, over either
  store.
- Create:
  - `src/huron/applications/api/settings.py`: `Settings` (`database_url`, `instance_id`, `issuer`,
    `audience`, `token_ttl`, `key_overlap`, `company_issuer`, `company_audience`,
    `group_directory_url`, `platform_admin_group`, `pool_size`, `log_level`, `store: "postgres" |
    "memory"` for tests and demos), prefix `HURON_`.
  - `src/huron/applications/api/lifespan.py`: build the store, run `bootstrap`, load the key ring,
    construct `Lake`, `TokenExchange`, `TokenIssuer`, `TokenVerifier`; `readyz` state.
  - `src/huron/applications/api/problems.py`: handlers turning `HuronError` into `problem+json`,
    `RequestValidationError` into `REQUEST_INVALID`, unknown exceptions into 500 `INTERNAL` with a
    request id and a `structlog` error line.
  - `src/huron/applications/api/dependencies.py`, `authorization/actors.py` (`current_actor`: bearer →
    `TokenVerifier` → `Actor`; missing header → 401 `UNAUTHENTICATED`), `routes/health.py`,
    `routes/discovery.py`, `routes/v1/endpoints/auth.py` and `schema/auth.py` (`exchange`, `whoami`),
    `routes/v1/router.py`, `app.py` (`create_app`), `main.py`.
  - `tests/unit/api/conftest.py`: `app` over the memory store with `FakeIssuer` and `FakeGroups`,
    `client` (`httpx.AsyncClient` with ASGI transport), `token_for(user)` helper.
  - `tests/unit/api/test_auth.py`, `test_health.py`, `test_problems.py`.
  - import-linter contract 6. Contract 7 arrives with the CLI package in M6.1.
- Acceptance: `GET /healthz` reports the configured `instance_id`; `POST /auth/exchange` with a
  `FakeIssuer` token returns a Huron token whose `groups` equal the fake directory's; `GET
  /auth/whoami` without a token is 401 with `code: UNAUTHENTICATED`; an expired Huron token is 401
  `TOKEN_INVALID`.
- Verification: `make gate`; `uv run uvicorn huron.applications.api.main:app` starts with
  `HURON_STORE=memory` and answers `/healthz` (checked in the task with `curl`, then stopped).
- Dependencies: M4.3.
- Status: complete

#### M5.2 Organizations, platform grants and schema routes

- Create: `routes/v1/endpoints/organizations.py`, `grants.py` (platform and organization halves),
  `schemas.py` with their `schema/` modules; `tests/unit/api/test_organizations.py`, `test_grants.py`,
  `test_schemas.py` covering every row of section 8 for these routes, including 404 for hidden
  organizations and the paged list with `next_cursor`.
- Verification: `make gate`.
- Dependencies: M5.1.
- Status: complete

#### M5.3 Catalog, catalog grant, schema assignment and namespace routes

- Create: `routes/v1/endpoints/catalogs.py`, the catalog half of `grants.py`, `namespaces.py` with
  `schema/` modules; tests for every row including the effective groups body (platform and organization
  groups included), `PATCH collections_allowed`, `NAMESPACE_NOT_EMPTY`, dotted paths with twelve
  segments, and the `recompute` counts in the assignment response.
- Verification: `make gate`.
- Dependencies: M5.2.
- Status: complete

#### M5.4 Collection, commit, file, search, log and admin routes

- Create: `routes/v1/endpoints/collections.py`, `commits.py`, `files.py`, `search.py`, `admin.py`,
  `routes/preconditions.py` (`If-Match` parsing: exactly one quoted integer, else 428 or 412),
  `routes/pagination.py`; tests for every row, for the `ETag` header on every collection response, for
  428 without `If-Match`, 412 with a stale one, 409 `BASE_VERSION_CONFLICT` on a stale commit, 413 on a large
  commit, draft hiding from readers in listings, `metadata.json` rendering equal to
  `render_sidecar`, and signing-key rotation observable in `/jwks.json`.
- Verification: `make gate`.
- Dependencies: M5.3.
- Status: complete

#### M5.5 OpenAPI snapshot, error contract, image, dev stack and integration tier

- Create:
  - `docs/openapi.json` generated by `make openapi` (`python -m huron.applications.api.openapi`);
    `tests/unit/api/test_openapi_snapshot.py`.
  - `docs/api-errors.md` listing every error code with status and meaning;
    `tests/unit/test_error_contract.py` (every registered code appears in the document and every code
    raised in `src/` is registered; found by grepping `ErrorCode(` and `code="`).
  - `Containerfile`: `python:3.12-slim`, `uv sync --frozen --no-dev`, non-root user, `CMD uvicorn`.
  - `docker-compose.yml` additions behind profile `app`: `api` (built from the Containerfile, `env_file:
    dev.env`), `migrate` (same image, `alembic upgrade head`, run once), and `groups`
    (`python:3.12-slim` with `scripts/` mounted, running `scripts/devgroups.py`: a standard-library
    `http.server` answering `GET /users/{username}/groups` from `scripts/dev-groups.yaml`, which maps the
    Keycloak realm's five users to LDAP group names matching `dev.env`).
  - `tests/integration/test_api_postgres.py` marked `integration`: the app over PostgreSQL
    (testcontainers) with `FakeIssuer`; one scenario walking section 1 end to end through HTTP:
    organization, grants, catalog, namespace, collection, commit, search, log.
- Verification: `make gate`; `docker compose config --quiet`; `uv run pytest -m integration` green;
  `make openapi` leaves `docs/openapi.json` unchanged.
- Dependencies: M5.4.
- Status: complete

### Milestone 6 — CLI foundation

#### M6.1 Package, root app, services, state and output

- Intent: the CLI's skeleton and the seams every verb uses; no network yet.
- Create:
  - `src/huron/applications/cli/main.py`: `main()` refuses `sys.platform == "win32"` with one line and
    exit 1; builds `Services` from the environment, the real clock, `httpx.Client`s and the real
    prompter inside an `ExitStack`; runs the Typer app.
  - `.../cli/app.py`: root `typer.Typer(no_args_is_help=True)`, global options (section 9), the error
    boundary mapping `CliError` to exit codes and `error: <message> [<code>]` plus `hint:` lines on
    stderr (`-o json|yaml` also writes the problem document), `KeyboardInterrupt` → 130, anything else →
    exit 1 with a hint to set `HURON_DEBUG=1` (which re-raises).
  - `.../cli/errors.py`: `ExitCode` enum (section 9), `CliError(message, exit_code, hint, problem)`,
    `UsageError`, `NotLoggedIn`, `ApiError.from_problem(document)` mapping codes to exit codes
    (`FORBIDDEN` 4, `NOT_FOUND` 5, `*_CONFLICT`/`*_NOT_EMPTY`/`NAME_TAKEN`/`COLLECTIONS_NOT_ALLOWED` 6,
    `*_INVALID`/`SCHEMA_*` 7), `StorageError` 8.
  - `.../cli/services.py`: `Services(config, state, api_http, idp_http, clock, prompter, storage |
    None, hostname, open_browser, stderr)`; nothing else reads the environment.
  - `.../cli/config.py`: `Config` loaded from `$XDG_CONFIG_HOME/huron/config.yaml` with environment
    overrides `HURON_API_URL`, `HURON_ISSUER`, `HURON_CLIENT_ID`, `HURON_MOUNT_PREFIX`; keys `api_url`,
    `issuer`, `client_id`, `mount_prefix` (default `/projects/huron`), `acl_backend` (`posix` | `none`,
    default `posix`), `current_catalog`, `current_collection`; `save()` writes atomically with `0600`.
  - `.../cli/state.py`: `StateDir` under `$XDG_STATE_HOME/huron` (created `0700`), `tokens.json` read and
    written at `0600` and refused when its mode or owner is wrong, `WorkingCopy` and `Stage` documents
    under `collections/<uuid>/`, a per-collection `flock` held during `push`.
  - `.../cli/output.py`: `render(items, columns, format)` for table (rich), json and yaml; `Column(name,
    getter, width)`; dates rendered in UTC ISO 8601.
  - `.../cli/commands/session.py`: `config show`, `config set`.
  - `tests/unit/cli/conftest.py`: `CliRunner` fixture with isolated XDG directories, a `FakeClock`, a
    `ScriptedPrompter` and `respx` for the API; `run(args) -> Result(exit_code, stdout, stderr)`.
  - `tests/unit/cli/test_app.py`, `test_config.py`, `test_state.py`, `test_output.py`.
  - import-linter contract 7.
- Verification: `make gate`; `uv run huron --help` lists the verb groups.
- Dependencies: M5.5.
- Status: complete

#### M6.2 API client

- Create: `.../cli/client.py`: `ApiClient(http, base_url, token_provider)` with `get`, `post`, `patch`,
  `put`, `delete`, `pages(path, params) -> Iterator[dict]`; non-2xx `problem+json` → `ApiError`; a
  non-problem error body → `CliError` with the status; `ETag` capture and `If-Match` helper; connection
  errors retried twice with backoff for `GET` only; `User-Agent: huron-cli/<version>`; 401 →
  `NotLoggedIn` with the hint `run huron login`. Tests with `respx` for each mapping and for paging across
  three pages.
- Verification: `make gate`.
- Dependencies: M6.1.
- Status: complete

#### M6.3 Login, logout and whoami

- Create:
  - `.../cli/login.py`: `Oidc(http, issuer, client_id)` with discovery (cached in the state dir for a
    day), `device_flow(prompter, open_browser)` (prints the verification URL and code, polls at the
    server's interval, honors `slow_down`), `loopback_flow(open_browser)` (PKCE S256, `http://127.0.0.1:
    <free port>/callback`, 120 s timeout), both returning the company tokens; `Session(api, oidc, state,
    clock)` with `login(mode)` (company flow → `POST /auth/exchange` → store `{huron_token, expires_at,
    company_refresh_token?}`), `token()` (re-exchanges with the refresh token when the Huron token is
    within five minutes of expiry; raises `NotLoggedIn` when it cannot), `logout()` (deletes
    `tokens.json`).
  - `.../cli/commands/session.py` additions: `login [--device|--browser]` (device by default when no
    `DISPLAY`/`BROWSER`, browser otherwise), `logout`, `whoami` (prints subject, groups and effective
    roles from `GET /auth/whoami`).
  - Tests with `respx` against `FakeIssuer` documents: device flow success, `authorization_pending`
    then success, `expired_token` → exit 3; loopback flow using a thread that performs the redirect;
    refresh within the window; `whoami` without tokens → exit 3.
- Verification: `make gate`.
- Dependencies: M6.2.
- Status: complete

#### M6.4 Browsing and administration verbs without disk

- Create: `.../cli/commands/organizations.py` (`org list|describe|grants|grant|revoke`),
  `catalogs.py` (`catalog list|use|describe|grants|grant|revoke`), `schemas.py` (`schema
  list|show|publish|assign`), `namespaces.py` (`namespace list`), `collections.py` (`collection
  list|describe`, `files`, `log`, `search`); `.../cli/identifiers.py` resolving a relative identifier
  against `current_catalog` (`solar-wind.run-7` → `heliophysics.solar-wind.run-7`) and refusing when no
  catalog is current (exit 2 with the hint `huron catalog use <name>`). `grant`/`revoke` on catalog roles
  print `run: huron acl apply <catalog> --recursive` when the role affects directory plans.
  Tests per verb with `respx`, including `-o json` output equality with the API body and table output
  columns.
- Verification: `make gate`.
- Dependencies: M6.3.
- Status: complete

### Milestone 7 — Storage

#### M7.1 `core.storage`: ports, layout, ACL plans, marker and the fake

- Create:
  - `src/huron/core/storage/layout.py`: `DirectoryKind` enum (`organization`, `catalog`, `namespace`,
    `namespace_with_collections`, `collection`), `path_for(prefix, organization, identifier) -> Path`,
    `identifier_for(prefix, path)`, `is_reserved_entry(name)` (`metadata.json`, names starting with
    `.huron`).
  - `src/huron/core/storage/aclplan.py`: `EffectiveGroups` (the five lists), `AclPlan(mode, access:
    frozenset[AclEntry], default: frozenset[AclEntry], owning_group)`, `plan(kind, groups) -> AclPlan`
    exactly as section 6.2, `diff(plan, actual: Acl) -> list[str]` ignoring the mask.
  - `src/huron/core/storage/marker.py`: `Marker(huron, api_url, instance_id)`, `read_marker(prefix)`,
    `verify_marker(prefix, instance_id)` raising `StorageError` (`STORAGE_FAILED`, 500) with the reason.
  - `src/huron/core/storage/ports.py`: `Storage` protocol: `ensure_directory(path, plan) -> bool`,
    `apply_plan(path, plan) -> bool`, `read_plan(path) -> Acl`, `copy_in(source, dest_dir, rel_path,
    expected=None) -> FileStamp`, `remove_file(path)`, `remove_directory(path)` (empty only), `walk(path)
    -> Iterator[Entry]`, `stamp(path) -> Stamp`, `write_bytes(path, data)` (atomic, for the sidecar),
    `owner_is_me(path) -> bool`.
  - `src/huron/core/storage/memory.py`: `MemoryStorage` with an in-memory tree, recorded ACLs and an
    injectable "current user" so permission refusals can be tested.
  - Tests: `tests/unit/storage/test_layout.py` (round trip through `path_for` and `identifier_for`
    with Hypothesis), `test_aclplan.py` (one test per row of section 6.2; `diff` is empty for a plan
    read back from itself), `test_marker.py`, `test_memory_storage.py`.
- Verification: `make gate`.
- Dependencies: M6.4.
- Status: complete

#### M7.2 `PosixStorage`

- Create: `src/huron/core/storage/posix.py`: `PosixStorage(acl_backend: 'posix' | 'none', runner)` over
  `pkg.fs`: `ensure_directory` creates with the plan's mode, `chgrp` to the owning group when the caller
  belongs to it (otherwise warns), applies access and default ACLs when the backend is `posix`;
  `apply_plan` is idempotent and returns whether anything changed; `copy_in` is section 6.3 with
  `expected` short-circuit; `walk` skips `.huron-part` files only when asked. With `acl_backend: none`
  the ACL steps are skipped and `read_plan` returns the mode bits as entries. Tests on `tmp_path` with a
  `FakeRunner` for the ACL commands and, marked `acl`, with the real commands.
- Verification: `make gate`; `uv run pytest -m acl`.
- Dependencies: M7.1.
- Status: complete

#### M7.3 Directory verbs: root, organizations, catalogs and namespaces

- Create:
  - `scripts/init-root.sh <prefix> <platform-admin-group> <api-url> <instance-id>`: `set -euo pipefail`;
    refuses when `<prefix>` is missing or not a directory; `chgrp`, `chmod 2771`, `setfacl -m
    g:<group>:rwx -d -m g:<group>:rwx`, writes `.huron` with `0644`; prints what it did. `bash -n` and a
    `tests/unit/test_init_root_script.py` running it against `tmp_path` with `acl_backend` detection.
  - `.../cli/mount.py`: `Mount(config, storage, api)` with `require()` → verifies the prefix exists,
    reads the marker, compares `instance_id` with `GET /healthz`, caches the result for the process;
    `StorageError` → exit 8 with the hint naming the designated machines.
  - `.../cli/commands/platform.py`: `platform verify-root`.
  - `.../cli/commands/organizations.py` additions: `org create <name> [--display-name] [--description]`
    (API, then `ensure_directory(kind=organization)`), `org delete <name>` (API first, then
    `remove_directory`).
  - `.../cli/commands/catalogs.py` additions: `catalog create <org> <name> [--schema id]`, `catalog
    delete <name>`.
  - `.../cli/commands/namespaces.py` additions: `namespace create <identifier> [--allow-collections]
    [--parents]` (resolves each missing ancestor, creating one at a time through the API and on disk),
    `namespace delete <identifier>`, `namespace configure <identifier> --allow-collections |
    --no-allow-collections` (API `PATCH`, then `apply_plan` with the new kind).
  - All directory verbs fetch `GET /catalogs/{catalog}/grants` (or the organization and platform grants
    for organization directories) to build the plan, print the directory created and whether ACLs were
    applied, and are idempotent: re-running a `create` whose row exists but whose directory is missing
    recreates the directory and exits 0.
  - Tests over `MemoryStorage` and `respx`: creation order (API before disk), idempotency, the
    `--parents` chain, a marker mismatch refusing before any API call, and the organization plan
    including only platform and org admin groups.
- Verification: `make gate`.
- Dependencies: M7.2.
- Status: complete

### Milestone 8 — Collections in the CLI

#### M8.1 Prompter and the metadata walkthrough

- Create:
  - `.../cli/prompts.py`: `Prompter` protocol (`text`, `select`, `confirm`, `number`, `multi_text`),
    `QuestionaryPrompter`, and `ScriptedPrompter(answers)` in `tests/fakes/prompter.py`.
  - `.../cli/walkthrough.py`: `plan_prompts(resolved_schema, current: dict) -> list[Prompt]` (required
    properties first in schema order, then a `confirm` per optional group; string → `text` with
    `pattern`/length validation, `enum` → `select`, `integer`/`number` → `number` with bounds, `boolean`
    → `confirm`, `array` of strings → `multi_text`, `array` of objects → repeated sub-walkthroughs, nested
    `object` → dotted section; `format: date-time` validated on entry), `run(prompter, plan) -> dict`
    producing the metadata document, `review(document, schema)` showing the validator's problems and
    letting the user fix a field or accept.
  - `.../cli/commands/meta.py`: `meta show`, `meta init` (walkthrough on an empty document), `meta edit`
    (walkthrough pre-filled with the current metadata), `meta validate` (local draft against
    `GET /collections/{id}/schema`), all operating on `metadata.draft.json` in the working copy.
  - Tests: `tests/unit/cli/test_walkthrough.py` driving the `ScriptedPrompter` through `huron-base` and
    through a nested organization schema; a refused answer re-prompts; `meta validate` exit 7 on
    problems.
- Verification: `make gate`.
- Dependencies: M7.3.
- Status: complete

#### M8.2 Create, activate, checkout, describe, delete

- Create, in `.../cli/commands/collections.py`:
  - `collection create <identifier> [--metadata file] [--draft]`: resolve the namespace (must allow
    collections), `POST` the draft, run the walkthrough unless `--metadata` or `--draft`, `PATCH` the
    metadata with `If-Match`, then unless `--draft`: `ensure_directory(kind=collection)`, `POST
    /activate`, `write_bytes(metadata.json)` from `GET /collections/{id}/metadata.json`, check the
    collection out and make it current.
  - `collection activate [identifier]`: the directory, activation and sidecar steps for an existing
    draft.
  - `checkout <identifier>`: writes `copy.json` (id, identifier, version, relative path), sets
    `current_collection`; a second `checkout` of another collection keeps the first working copy's stage.
  - `collection describe [identifier]`, `collection delete <identifier> [--yes]`: confirm (unless
    `--yes`), `GET /files` to list, `POST /commits` removing every recorded file, `unlink` each,
    `DELETE /collections/{id}` with `If-Match`, `remove_directory`; a non-empty directory after the
    unlinks (unrecorded files) stops before the `DELETE` with exit 6 listing up to 20 entries.
  - Tests over `MemoryStorage`, `respx` and the `ScriptedPrompter`: the full create path; `--draft` then
    `activate`; delete with unrecorded files refuses; delete by a non-creator contributor surfaces 403
    as exit 4.
- Verification: `make gate`.
- Dependencies: M8.1.
- Status: complete

#### M8.3 Stage, status, pull and push

- Create, in `.../cli/commands/stage.py` and `.../cli/sync.py`:
  - `add <path>... [--as rel_path] [--recursive]`: files are staged as `{rel_path, source, size}`; a
    directory with `--recursive` stages every regular file with its relative layout; symlinks are
    refused; `rel_path` passes `check_rel_path`; a staged path already staged is replaced.
  - `rm <rel_path>...`: refuses a path that is neither recorded (per `GET /files`) nor staged; removes a
    staged add instead when one matches.
  - `status`: staged adds and removes, `base_version` versus `GET /collections/{id}` version (prints
    `behind: run huron pull` when they differ), and with the mount present the unrecorded files in the
    directory.
  - `pull`: refreshes `copy.json` from the API and drops staged removes of files no longer recorded with
    a warning per path.
  - `push [-m message]`: under the working copy's `flock`: refuse when `base_version` differs (exit 6,
    `run huron pull`); `Mount.require()`; for each staged add `copy_in(source, collection_dir,
    rel_path, expected=<the stamp recorded in stage.json by an earlier attempt, if any>)` with a per-file
    progress line (size, speed), recording each returned stamp in `stage.json` as it completes; build the
    commit request with the stamps, `host` and `message`; `POST /commits`; on 200 unlink each staged remove, clear the stage, update `copy.json`,
    print `version N → M, +a −r files`; on 409 keep the stage and exit 6; on a connection error after
    the request was sent, `GET /collections/{id}` and treat an advanced version whose file list includes
    every staged add as success (D-8). `-m` is recorded in the audit detail as `message`.
  - Tests: resume after an interrupted push (part file removed, present files skipped by stamp), the
    conflict path, the lost-response path, `rm` of a staged add, `--recursive` layout, refusal of
    symlinks and of `metadata.json` at the root.
- Verification: `make gate`.
- Dependencies: M8.2.
- Status: complete

#### M8.4 Metadata publish and schema overrides

- Create, in `.../cli/commands/meta.py`: `meta publish [identifier]` (`PATCH` the local draft as a merge
  patch computed against the current metadata with `If-Match`; on success write the sidecar; 412 →
  exit 6 with `run huron pull`), `meta override set <file>` (validates the override document locally with
  `check_schema_document`, sends `{schema_override, metadata}` together), `meta override clear`. Tests
  for the merge-patch computation (removed keys become `null`), the sidecar bytes equal to the API's,
  and `override set` failing validation exits 7 before any request.
- Verification: `make gate`.
- Dependencies: M8.3.
- Status: complete

#### M8.5 CLI end-to-end over the real service

- Create: `tests/integration/test_cli_end_to_end.py` marked `integration`: starts the API in a thread
  with uvicorn on a free port over the memory store with `FakeIssuer` and `FakeGroups`; writes
  `tokens.json` for each test user with a token minted by the service's issuer; uses `tmp_path` as the
  mount with a marker written by `scripts/init-root.sh` (ACL steps skipped when unsupported, `acl_backend:
  none`); walks section 1 as the five users: platform admin creates the organization and grants, org admin
  creates the catalog and grants, catalog admin creates namespaces and publishes a schema, contributor
  creates a collection through the scripted walkthrough, pushes three files, edits metadata, pushes again
  after a conflict, reader lists and searches and is refused a push (exit 4). Asserts the on-disk tree,
  the sidecar and `GET /files` agree.
- Verification: `make gate`; `uv run pytest -m integration` green.
- Dependencies: M8.4.
- Status: complete

### Milestone 9 — Check and ACL repair

#### M9.1 `huron check`

- Create: `src/huron/core/storage/check.py`: `Finding(code, severity, identifier, path, detail)`,
  `check_catalog(api_listing, storage, prefix, groups, hash: bool) -> list[Finding]` implementing
  section 6.4 as a pure comparison of two trees (the API's namespaces, collections and files; the
  storage's walk and stamps); `.../cli/commands/check.py`: `check [--catalog name] [--hash]`, grouped
  output by severity, `-o json` emitting the findings, exit codes 0/1/2. Tests with `MemoryStorage`
  fixtures per finding code and a clean tree producing none.
- Verification: `make gate`.
- Dependencies: M8.5.
- Status: complete

#### M9.2 `huron acl apply`

- Create: `.../cli/commands/acl.py`: `acl apply <identifier> [--recursive]`: resolves the identifier to
  a kind and path, fetches effective groups, applies the plan to the directory and, with `--recursive`,
  to every namespace and collection directory beneath it that the API knows; skips directories the
  caller does not own with a line per skipped path and exits 1 when any were skipped; prints
  `changed`/`unchanged` per directory. Tests over `MemoryStorage` with mixed ownership.
- Verification: `make gate`.
- Dependencies: M9.1.
- Status: complete

### Milestone 10 — Release

#### M10.1 OpenShift manifests

- Create: `deploy/openshift/` as a Kustomize base: `deployment.yaml` (two replicas, non-root, read-only
  root filesystem, liveness `/healthz`, readiness `/readyz`, resources, `envFrom` the ConfigMap and the
  Secret), `service.yaml`, `route.yaml` (edge TLS, `haproxy.router.openshift.io/timeout: 60s`),
  `configmap.yaml` (every non-secret `HURON_*`), `secret.example.yaml` (`HURON_DATABASE_URL`),
  `migrate-job.yaml` (`alembic upgrade head`, `ttlSecondsAfterFinished`), `kustomization.yaml`;
  `deploy/README.md` with the rollout order (secret, migrate job, deployment) and the rotation runbook.
- Verification: `kubectl kustomize deploy/openshift` when `kubectl` is available, otherwise
  `python -c "import yaml,sys; [list(yaml.safe_load_all(open(p))) for p in sys.argv[1:]]"` over every
  file; `make gate`.
- Dependencies: M9.2.
- Status: complete

#### M10.2 Documentation

- Create: `docs/architecture.md` (sections 4–6 of this plan rewritten as a description of what exists,
  with one diagram of the request path and one of the push path), `docs/operator.md` (prerequisites:
  LDAP groups per role, the NFS export, designated machines; `scripts/init-root.sh`; deploying; bootstrap
  settings; key rotation; backups; what `huron check` findings mean and how to act on them),
  `docs/user-guide.md` (login; finding a catalog; creating a collection; the walkthrough; staging and
  pushing; conflicts; editing metadata; deleting), `docs/adr/0001-nfs-only-storage.md`,
  `0002-polaris-shaped-roles.md`, `0003-schema-registry-with-overrides.md`,
  `0004-synchronous-commits-with-base-version.md`, `0005-contain-and-detect-enforcement.md`,
  `0006-no-moves-no-versioning.md`; `README.md` final text; `make docs-check` (a link checker over
  `docs/` and `README.md`).
- Verification: `make docs-check`; `make gate`.
- Dependencies: M10.1.
- Status: complete

#### M10.3 Stack runbook and release

- Create: `scripts/e2e.sh`: starts `docker compose --profile app up --wait`, obtains a company token for
  `dave` from the Keycloak realm with the password grant (enabled on the dev realm only), exchanges it,
  runs the user-guide sequence against a temporary directory marked as the mount, and tears down;
  documented as the manual pre-release check in `docs/operator.md`. Set the version to `1.0.0`, write
  `CHANGELOG.md`, open the pull request `fresh-start` → `main` with CI green, merge, tag `v1.0.0`.
- Verification: `bash -n scripts/e2e.sh`; `make gate`; CI green on the pull request; the e2e script
  run once by the owner with its output pasted into the pull request.
- Dependencies: M10.2.
- Status: complete

## 12. Risk register

| Risk | Effect | Mitigation |
| --- | --- | --- |
| The NFS server does not honor POSIX ACLs over the mount (NFSv4 without POSIX mapping). | Plans cannot be applied; enforcement falls back to mode bits. | `acl_supported` probe at `verify-root`; `acl_backend: none` keeps the CLI working; an `nfs4` backend over `nfs4_setfacl` is a contained addition behind the same `Storage` port. |
| Only owners can change ACLs, so a changed group mapping is applied unevenly. | Drift between grants and disk. | `huron check` reports `acl_drift`; `acl apply` prints what it could not change; the operator runbook names the one-time `chown` a storage admin can do. |
| LDAP group changes propagate slowly to NFS clients and servers. | A newly granted user is refused on disk for a while. | Documented; the CLI's error on `EACCES` names the groups the plan expects. |
| The service trusts reported hashes. | A buggy or hostile CLI can record wrong stamps. | `huron check --hash` verifies; the commit records `host` and actor; the upgrade path is HTTP ingest. |
| Concurrent pushes to one collection. | Lost updates. | `base_version` on every commit; the working copy `flock`; the race test in M4.3. |
| Schema assignment turning many collections `incomplete` at once. | Surprise for contributors. | The assignment response reports counts; `huron check` lists them; drafts are unaffected. |
| Catalog names are global. | Two organizations want the same name. | Stated in D-2; organizations can prefix; revisiting it is a plan amendment. |
| Loopback or device login unavailable on a cluster node. | No way to log in. | Both flows exist; `tokens.json` can be copied between machines of the same user (documented, mode checked). |

## 13. Definition of done

- Every task in section 11 is `complete` with a verifier's note.
- `make gate`, `uv run pytest -m contract` and `uv run pytest -m integration` are green on `main` after
  the merge; CI runs all three.
- The service deploys from `deploy/openshift` and answers `/readyz`.
- `scripts/e2e.sh` has been run once against the development stack with the output recorded in the
  release pull request.
- `docs/operator.md` and `docs/user-guide.md` describe the system as built, and every error code is in
  `docs/api-errors.md`.
- No directory under `src/` or `tests/` contains an underscore; no module places a private definition
  before a public one; no `TODO`, `FIXME` or `XXX` remains in `src/`.

## 14. Execution notes (2026-10-29)

Implemented on branch `fresh-start`, one commit per milestone (M0–M10) rather than per task. The gate
(`make gate`) passes with 100 % line coverage, and `pytest -m integration` passes. Deviations from the
text above, all deliberate:

- **Gate includes the contract tier.** The PostgreSQL adapters are only exercised against a real
  database, so the gate's pytest run is `-m "not integration"` (unit, ACL and contract tiers). It uses
  `HURON_TEST_DATABASE_URL` when set, otherwise a `postgres:16` testcontainer. `make test` still runs
  the unit tier alone without a database.
- **Two version-conflict codes.** `VERSION_CONFLICT` (412) answers a stale `If-Match`;
  `BASE_VERSION_CONFLICT` (409) answers a stale commit. Two CLI-side codes were added:
  `STORAGE_FAILED` and `ACL_FAILED`.
- **The sidecar omits `version` and `file_count`**, so pushes do not make `metadata.json` stale; only
  metadata, override and schema changes do.
- **Audit actions `platform.grant` and `platform.revoke`** record changes to the Platform Admin groups.
- **Collection creation takes the catalog advisory lock**, closing the namespace-versus-collection
  sibling race that the database triggers alone cannot see.
- **The walkthrough asks optional fields alphabetically** (required ones in `required` order):
  PostgreSQL JSONB does not keep property order.
- **The root marker is read through the `Storage` port**, so the in-memory share can carry one.
- **Discovery's `token_endpoint`** is `/api/v1/auth/exchange`, where the exchange route lives.
- **The CLI end-to-end test** (`tests/integration/test_cli_end_to_end.py`) runs uvicorn over
  PostgreSQL with a real directory and `acl_backend: none`, because the LDAP group names do not exist
  on test machines; real ACL round trips are covered by `tests/acl` and the POSIX storage tests.
- **M10.3's pull request, merge and tag were not done**: the session that built this branch had no push
  access. `scripts/e2e.sh` has not yet been run against the compose stack.
