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
  service. `huron adm check` reports where disk and catalog disagree.
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
- Automatic repair of disk drift. `huron adm check` reports; `huron adm repair` makes missing directories
  and sets permission bits through the API; nothing deletes user files.
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
  come later. (Extended 2026-10-31: the three catalog roles may also be granted at organization scope,
  where every catalog of the organization inherits them; see the amendment at the end of this section.)
- D-10 Roles are granted to LDAP groups, never to individual users. The Huron token carries the user's
  groups; each request maps groups to roles through the current grants table. The platform admin group
  comes from configuration and is seeded as a grant at startup. (Extended 2026-10-31: declared
  organizations and their org admin groups are reconciled at startup too; see the amendment at the end
  of this section.)
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
  publish, so the information survives apart from the service. `huron adm check` reports a stale sidecar.
  (Amended 2026-11-06: the API writes `metadata.json`, and the CLI never writes it. See "Read-only
  share and identity on disk" in the uploads amendment.)

**Storage and enforcement**

- D-18 Plain NFS. The share is mounted at a configurable prefix (default `/projects/huron`) on designated
  machines. The service on OpenShift mounts nothing; only the CLI touches the filesystem.
  (Amended 2026-11-06: the API mounts the lake read-write at `lake_path`, and the CLI mounts it
  read-only. See "Read-only share and identity on disk" in the uploads amendment.)
- D-19 Directories are created by the CLI as the user running it, after the service has authorized and
  recorded the change. The root directory is prepared once by the storage administrator with the script
  in `scripts/init-root.sh`. (Amended 2026-10-31: the storage administrator prepares each declared or
  rooted organization's directory with `huron adm provision-orgs`; see the amendment at the end of
  this section. Amended 2026-11-06: the API creates catalog, namespace and collection directories
  as `U`, and the CLI creates none. See "Read-only share and identity on disk" in the uploads
  amendment.)
- D-20 Every directory the CLI creates has setgid set and carries POSIX ACLs derived from the catalog's
  effective role groups (section 6.2). Structural directories (organization, catalog, namespace) are
  writable only by their administrators. A namespace with `collections_allowed` additionally gives the
  contributor groups write access and has the sticky bit set. Collection directories give contributors
  write access and carry default ACLs so new files are group-writable. (Amended 2026-11-06: there
  are no ACLs and no sticky bit. The mode and the group of a directory control read access.
  See "Read-only share and identity on disk" in the uploads amendment.)
- D-21 Platform admin groups receive an inherited `rwx` default ACL at every level, so administrators can
  remove clutter without elevated privileges. Organization admin groups receive the same within their
  organization. (Amended 2026-11-06: there are no ACLs. See "Read-only share and identity on
  disk" in the uploads amendment.)
- D-22 Enforcement is contain-and-detect. Accepted: a scientist can write into their own collection
  directory without the CLI; the service trusts reported hashes; only a directory's owner can change its
  ACLs, so a changed group mapping is re-applied by owners running `huron adm apply-acl`, and the rest is
  reported by `huron adm check`. The upgrade path, if ever needed, is HTTP ingest to a service that mounts the
  share, behind the same `Storage` interface the CLI uses now. (Amended 2026-11-06: the mount is
  read-only for scientists, the API computes the hashes, and `huron adm apply-acl` is removed.
  See "Read-only share and identity on disk" in the uploads amendment.)
- D-23 The push write path: copy each file to `<rel_path>.huron-part` in the collection directory while
  hashing, `fsync`, rename into place, then commit. Removals are committed first and unlinked after. A
  retried push skips files already present with the recorded size and hash. (Amended 2026-11-06:
  the push uploads through tusd, and the API places each file. See "Upload flow" in the uploads
  amendment.)

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

### Amendment (2026-10-31): declared organizations, per-organization roots and the configuration file

Decided with the user on 2026-10-31; the record is
[docs/adr/0007-declared-organizations.md](docs/adr/0007-declared-organizations.md). Each organization
has a root, on its own export or a shared one, such as `helio` at `/data1/huron/helio` and `geo` at
`/data1/huron/geo`, and the organizations, their administrators and their roots are declared in the
service configuration. Sections 4, 5.2, 5.6, 6.1, 6.2, 6.4, 7, 8, 9 and 11 carry the consequences; the
text of D-1 to D-27 is unchanged apart from the pointers on D-9, D-10 and D-19.

- **The configuration file.** `HURON_CONFIG_FILE` names a YAML file whose top-level keys are the
  field names of `Settings` (`src/huron/applications/api/settings.py`) plus `organizations`.
  Precedence: `HURON_*` environment variables, then the file, then the defaults. Unknown top-level
  keys and two entries with the same organization name fail startup, so a typo such as
  `organisations:` cannot silently mean unmanaged mode. Secrets (`database_url`) are documented as
  environment only; the file accepts them but the deployments never put them there. `HURON_ORGANIZATIONS`,
  a JSON list, replaces the file's list, for tests and emergencies. The file is read with
  pydantic-settings' YAML source in a strict subclass (`pyyaml` and `pydantic-settings` are already
  dependencies).
- **Organization entries.** `name` (the segment rules of D-4, `huron.schema.naming`), `display_name`
  (default `""`), `description` (`""`), `groups` (the LDAP groups of the organization-wide roles,
  below), `root` (optional;
  an absolute, normalized path without `..`) and `export` (`""`; an informational NFS source such as
  `nfs1:/export/data1`, shown in mount hints). The organization's directory is always
  `<root>/<name>`; no other path can be configured. Below it the layout is unchanged,
  `<org dir>/<catalog>/<namespace…>/<collection>`, so the relative paths the API returns
  (`helio/sun/…`) are unchanged too: the absolute path is the root of the organization named by the
  first segment, `/`, and the relative path. An organization without `root` stays at
  `<mount_prefix>/<name>`, the CLI's configured prefix.
- **Managed and unmanaged mode.** An `organizations` key that is present, even as `[]`, is managed
  mode. Without it the service is unmanaged and behaves as before: `POST /organizations` and
  `huron create org` work, and every organization lives under the mount prefix.
- **D-10 extended.** Declared organizations are reconciled at startup, as the platform admin group is
  seeded. `bootstrap()` (`src/huron/core/lake/bootstrap.py`) takes them through `LakeSettings` and
  reconciles in its transaction under a new advisory lock port, `tx.lock_bootstrap()`
  (`pg_advisory_xact_lock` on PostgreSQL, an `asyncio` lock or no-op in the memory fake), so two
  replicas starting together do not race; the lock guards the existing `huron-base` and signing-key
  seeds too. A missing organization is created (`created_by` `huron-bootstrap`, audit
  `organization.create`). A different `display_name` or `description` is updated through the new
  `OrganizationStore.update` port (`version` + 1, new audit action `organization.update`). The
  organization-scope grant set of each of the four roles of `groups` (`org_admin`, `catalog_admin`,
  `contributor`, `reader`) is replaced to equal the declared groups exactly, with the
  `organization.grant` and `organization.revoke` entries any grant change writes. An organization in the database that the
  configuration does not declare is logged as a warning with its `catalog_count`, stays usable through
  the API and is never deleted; its directory does not follow it, since its root came from the
  configuration (D-28). A run that finds nothing to change writes nothing, not even an audit entry. Only
  invalid configuration fails startup.
- **D-28 (new) Managed organizations.** In managed mode the configuration decides which
  organizations exist and who administers them. `POST /organizations` answers 409
  `ORGANIZATIONS_MANAGED`. `DELETE /organizations/{org}` of a declared organization and
  `PUT /organizations/{org}/grants/{role}` on one, for any of the four organization-scope roles,
  answer 409 `ORGANIZATION_DECLARED`. An
  undeclared organization (one removed from the configuration) may still be deleted once it is empty.
  The name is the key: a rename is the removal of one entry and the addition of another, and the old
  organization stays, undeclared, until it is emptied and deleted. Per-catalog grants inside a
  declared organization stay API-managed. An undeclared organization has no root (roots are configuration, not
  rows), so the CLI looks for its directory under the mount prefix only: removing a rooted
  organization strands its directory until it is declared again with the same root, which restores
  it, so an organization is emptied while declared and removed afterwards. The CLI learns managed
  mode from `organizations_managed` of `GET /healthz`; `adm verify-mounts` reports an undeclared
  organization as `undeclared` without failing, `adm check` as the warning `org_undeclared` when the
  mount prefix is not a marked share, and `delete org` skips its directory then, with a hint.
- **Organization-wide role groups (decided with the user on 2026-10-31).** Each entry's `groups`
  maps `org_admin`, `catalog_admin`, `contributor` and `reader` to LDAP groups, declared once for
  the organization; every key is optional (default `[]`), the groups are de-duplicated and sorted,
  and any other key fails startup. `admin_groups` is removed without an alias (pre-release): a
  configuration that still uses it fails startup with a message naming `groups.org_admin`. The
  three catalog roles may be granted at organization scope (section 5.2), and every catalog of the
  organization, existing and future, inherits them through the authorizer's enclosing-scope rule;
  per-catalog grants are unchanged and add to the inherited groups, never remove one. In unmanaged
  mode the organization-scope sets are API-managed: `org_admin` needs `ORGANIZATION_GRANT`
  (Platform Admin), and `catalog_admin`, `contributor` and `reader` need `CATALOG_GRANT_ADMIN` at the
  organization (Org Admin or Platform Admin): an organization-scope Catalog Admin, although it holds
  `CATALOG_GRANT_MEMBER` in every catalog of the organization and so edits each catalog's member
  grants, does not grant organization-wide members. A catalog's effective groups (section 6.2) merge the organization-scope catalog-role
  groups in, so its ACL plans name them; `GET /catalogs/{catalog}/grants/sources` reports each
  group's source. Migration `0002_organization_catalog_roles` widens `ck_grants_role_scope`
  (section 7). The record is ADR 0007, section "Organization-wide role groups".
- **D-18 restated.** The service still mounts nothing. `root`, `export` and the `path` derived from
  them are configuration the API reports, never paths it opens.
- **D-19 amended.** The storage administrator prepares each organization directory, not
  `huron create org`: `huron adm provision-orgs` requires the root to exist (it never creates a root),
  creates `<root>/<org>`, applies the organization ACL plan of section 6.2 and writes the
  per-organization marker of section 6.1; `--emit-script` prints the same steps as a shell script for
  roots that only `root` can write. Catalog, namespace and collection directories are created by the
  CLI as the user, as before (amended 2026-11-06: the API creates them as `U`, and the organization
  ACL plan is gone, see the uploads amendment). `scripts/init-root.sh` stays, for the mount prefix of organizations
  that are neither declared nor rooted.
- **Deployment.** The kustomize base `deploy/openshift` (M10.1) gains a `configMapGenerator` for
  `huron.yaml` with `HURON_CONFIG_FILE` and its volume, and a Helm chart, `deploy/helm/huron`, is
  added (M10.6). Both are supported. The API pod mounts no share in either.
- **Development.** `huron.dev.yaml` at the repository root declares `helio` (display name
  `Heliophysics Division`, root `/data1/huron`, `groups` `org_admin` `helio-org-admins`,
  `catalog_admin` `helio-catalog-admins`, `contributor` `helio-contributors`, `reader`
  `helio-readers`), `geo` (`Earth Science`, `/data1/huron`, `org_admin` `geo-org-admins`, `reader`
  `geo-readers`) and `noaa` (`NOAA`, `/data1/huron`, `org_admin` `noaa-org-admins`, `reader`
  `noaa-readers`), the names and groups of the web's demo fixture and `scripts/dev-groups.yaml`.
  The seed's per-catalog grants from the fixture stay; they overlap the inherited groups and add to
  them. `make app` mounts it read-only into the API as
  `/etc/huron/huron.yaml` and recreates the API when the file changes; `make api` reads it through
  `HURON_CONFIG_FILE` in `dev.env`. Editing that one file and re-running `make app` (or restarting
  `make api`) applies a new configuration. In managed mode the seed (`docker/seed/run.mjs`) creates
  no organization and no `org_admin` grant; it loads the catalogs, namespaces and collections of the
  declared organizations and skips the fixture's undeclared ones (`astro`, `planetary`).

### Amendment (2026-11-06): uploads through tusd

Decided with the user on 2026-11-06. The record is
[docs/adr/0008-uploads-through-tusd.md](docs/adr/0008-uploads-through-tusd.md), which supersedes ADR
0001. On the evening of the same day the user revised the design in four points. First, the share
is read-only for every machine except the API pod and the upload pod. Second, the API holds the
writable mount and is the only process that writes the share. There is no ingest sidecar and there
are no disk tasks. Third, an nginx proxy in the upload pod asks the API before any byte reaches
tusd. Fourth, read access on disk comes from one POSIX group per catalog, not from POSIX ACLs,
because the export does not support them. Section 2's "File bytes through the service" non-goal is
withdrawn for uploads: the push sends bytes over HTTPS with the tus protocol to an unmodified tusd.
D-17, D-18, D-19, D-20, D-21, D-22 and D-23 are amended as below. The other decisions stand.
Milestone 11 builds it. M11.1 is complete and stays as built.

On 2026-11-08, after the M11.5 escalation, the containment model ("Containment in the lake")
replaced the per-path device check. The lake contains no symbolic links, Huron places with hard
links only, there are no version 1 directories (production starts from scratch), and the mount
point never changes. The record is `architectural_review.md` ("S: Synthesis"). The bullets
"Containment in the lake", "The disk-access module" and "Install order" state the result.

- **Read-only share and identity on disk (D-17 to D-23 amended).** The export is NFSv3 with
  `sec=sys`, `local_lock=none` and no NFSACL (measured 2026-11-06). POSIX ACLs are not possible on
  it. Huron uses plain owners, groups and modes.
  - The storage administrator makes the export read-write only for the clients that run the API
    pod and the upload pod (the cluster's worker nodes, or a dedicated node pool). Every other
    client mounts it read-only (`ro`).
  - The API pod and the upload pod run as one fixed UID `U` with the primary GID `G`. `G` is the
    `gidNumber` of an LDAP POSIX group, the **service group**, named by the API setting
    `service_group`. `U` is the API setting `service_uid`. `G` is the pod's `runAsGroup`, and the
    API reads it with `os.getgid()`; there is no setting for the number. `G` has no human members.
  - The API is the only process that creates, changes or removes anything on the share: the
    placement of finished uploads, directory creation, `metadata.json`, the unlink of removed
    files, directory removal and the `.tus-uploads` sweep. tusd writes only `.tus-uploads`. The
    CLI writes nothing, apart from `huron adm provision-orgs` and `huron adm provision-catalogs`
    in direct mode, which the storage administrator runs as root ("The CLI").
  - D-17: the API writes `metadata.json` from its own rendering, in the request that changed the
    metadata. The CLI never writes it.
  - D-18: the API mounts the lake read-write at `lake_path` ("Lake path"). The web and the CLI
    mount nothing for a change.
  - D-19: the API creates catalog, namespace and collection directories as `U`, in the request.
    An unmanaged organization's directory directly below `lake_path` is created by
    `huron create org` through the API too. The directory of a declared organization stays with
    the storage administrator (`huron adm provision-orgs`), who makes `U:G` its owner and group.
  - D-20 and D-21: there are no ACLs. A directory's mode and group decide who reads it ("Catalog
    share group and directory modes"). The sticky bit is gone. D-11's rule stays in the API.
  - D-22: a scientist cannot write into a collection directory, because the mount is read-only.
    The API computes the hashes (receipts). No owner has to run a command after a grant change,
    because grants no longer reach the disk.
  - D-23: the push uploads through tusd ("Upload flow").
  - Read-only commands keep the read-only mount: `huron adm check`, `huron adm verify-mounts` and
    the unrecorded-file list of `huron status`. `huron pull` and `huron tree` read only the API.
    `huron delete collection` no longer checks for unrecorded files: the API unlinks only the
    files it recorded or placed, and leaves any other entry with a `dir_unrecorded` finding
    ("Directory verbs in the API").
  - A complete `huron adm check` needs an account that is in `G` and in every share group, or
    `U` itself (from an API pod: `oc exec deploy/huron -- huron adm check`). An entry that the
    reader cannot list or stat gives an `unreadable` finding (a warning with the path and the
    errno), not a `PermissionError`. `huron status` uses the same rule.
  - OpenShift: the restricted SCC (`restricted-v2`) accepts `runAsUser: U` only inside the
    namespace's UID range (annotation `openshift.io/sa.scc.uid-range`). The cluster administrator
    pins the annotation when the namespace is created. Both pods set `runAsNonRoot: true`,
    `runAsUser: U`, `runAsGroup: G`, `supplementalGroups: [G]` and
    `seccompProfile: RuntimeDefault`. They do not rely on `fsGroup`, which NFS volumes ignore.
    `restricted-v2` still gives the pod a default `fsGroup`, and that GID takes one of the 16
    group slots of AUTH_SYS. Every container drops all capabilities, forbids privilege escalation
    and has a read-only root filesystem. The deployment sets `U` and `G` (Helm `serviceUser.*`,
    kustomize `huron.yaml` and the security contexts). The operator guide says how to choose
    them: `U` is the first UID of the namespace's pinned range, and `G` is the `gidNumber` of the
    service group.
  - The export trusts UIDs (AUTH_SYS). `U` cannot `chown`, and `U` cannot `chgrp` to a group it is
    not a member of. The design never needs `chown` from `U`. It needs `chgrp` once per catalog,
    which is a storage-administrator step ("Catalog share group and directory modes"). The rules
    "no user can write the share" and "only the share group reads a catalog" hold only against
    users who are not root on a client.
  - `GET /healthz` reports `service_user: {"uid": U, "gid": G, "group": "<service_group>"}`, or
    `null` when `service_group` is not set ("Settings"). `gid` is the number from `os.getgid()`.
    The scripts that `huron adm provision-orgs --emit-script` and
    `huron adm provision-catalogs --emit-script` print use the numeric `U:G` from this field,
    never a group name for `G`. Their options `--uid` and `--gid` override `service_user`.
- **Facts about the storage (measured 2026-11-06).** These are the measured facts about the lake
  export. The other bullets of this amendment refer to this bullet by its name.
  - The server is NetApp ONTAP.
  - The client mounts the export with `vers=3`, `proto=tcp`, `hard`, `timeo=600`, `sec=sys`,
    `rsize=65536`, `wsize=65536` and `local_lock=none`.
  - `rpcinfo` on the server shows NFS (program 100003) versions 3 and 4. It does not show NFSACL
    (program 100227).
  - `setfacl` on the mount answers `Operation not supported`. POSIX ACLs are not possible.
  - Hard links work.
  - tusd v2.10.1 locks an upload with hard links (`github.com/tus/lockfile`), not with `flock`.
    So `local_lock=none` is correct for tusd ("Deployment").
  - Pending measurement: the setgid inheritance over NFSv3 and the volume security style (UNIX,
    NTFS or mixed). Procedure: as root, make a test directory `t` on the real export with owner
    `U`, group `S` and mode `2750`, where `U` is not a member of the group `S`. As `U`, with
    `umask 022`, run `mkdir -m 0750 t/d; touch t/f; stat -c '%a %U %G' t/d t/f`. The result must
    be `2750 U S` and `644 U S`. Then, as root, run `chgrp S t/d; chmod 2750 t/d` and
    `stat -c '%a %G' t/d`; the result must be `2750 S`. The operator records the date, the
    `stat` lines and the security style in this bullet, in place of this line. M11.13 (the Helm
    chart and the production values) starts only after that record exists ("Catalog share group
    and directory modes"). M11.11 runs on the local cluster, where the lake is a local Linux
    filesystem, and does not wait for the record (decided 2026-11-07).
- **Components.** Two Deployments.
  - `huron`, the API (two replicas, as before). It mounts the claim `huron-lake` (ReadWriteMany)
    at `HURON_LAKE_PATH`, read-write. It runs as `U:G`. It serves tusd's hooks and nginx's auth
    subrequests, places uploads, runs the directory verbs' disk work, drains the removal outbox
    and sweeps `.tus-uploads`.
  - `huron-uploads`, the upload pod: one replica with strategy `Recreate`. tusd locks an upload
    with a hard-linked lock file that holds its PID, and the test that this PID is alive is local
    to one PID namespace. So two tusd processes must never run at the same time. The pod mounts
    `huron-lake` at `HURON_LAKE_PATH`, read-write, and runs as `U:G`. One init container and two
    containers:
    - `clean-locks` (init): the tusd image with `sh -c`. It deletes `*.lock`, `*.lock.*` and
      `*.stop` in `${HURON_LAKE_PATH}/.tus-uploads` before tusd starts. tusd runs as PID 1, so
      after an unclean stop a new tusd finds its own PID in an old lock file and treats the
      upload as busy until the lock timeout. The deletion is safe because there is one replica.
    - `proxy`: the image `nginxinc/nginx-unprivileged:1.27-alpine`, pinned to its current patch
      tag by M11.11. It listens on port `1080` of the pod and is the only port a Service selects.
      It mounts no lake. It authorizes every request to tusd with the API ("Authorization in
      front of tusd") and streams bodies to tusd. The image's entrypoint renders
      `/etc/huron/nginx-uploads.conf.template` with `envsubst` into `/tmp/nginx-uploads.conf`
      (environment `NGINX_ENVSUBST_TEMPLATE_DIR=/etc/huron`,
      `NGINX_ENVSUBST_TEMPLATE_SUFFIX=.template`, `NGINX_ENVSUBST_OUTPUT_DIR=/tmp`,
      `NGINX_ENVSUBST_FILTER=^HURON_API_UPSTREAM$`, `HURON_API_UPSTREAM=<api host>:<port>`).
      `/tmp` is the container's `emptyDir`. The template step skips an output directory that
      does not exist, so the output directory is `/tmp` itself. The filter makes
      `${HURON_API_UPSTREAM}` the only substituted variable. Kubernetes sets
      `args: ["nginx", "-c", "/tmp/nginx-uploads.conf", "-g", "daemon off;"]` and never
      `command:`, because `command:` replaces the image's entrypoint and the `envsubst` step does
      not run. Compose sets `command:` with the same words, because Compose keeps the entrypoint.
    - `tusd`: the image `tusproject/tusd:v2.10.1`, run with `-host=127.0.0.1 -port=1081
      -upload-dir=${HURON_LAKE_PATH}/.tus-uploads -base-path=/files/ -behind-proxy
      -disable-download -hooks-http=http://<api host>:<port>/api/v1/uploads/hooks
      -hooks-http-forward-headers=Authorization
      -hooks-enabled-events=pre-create,pre-finish,pre-terminate
      -hooks-http-timeout=<upload_hook_timeout in seconds> -hooks-http-retry=3
      -hooks-http-backoff=1 -file-perms=0600 -dir-perms=0700` and `-max-size=<upload_max_size>`
      when it is not `0`. The deployment replaces its CMD (Kubernetes `args:`), since the image's
      default enables file hooks. The flag names were checked in `cmd/tusd/cli/flags.go` of
      v2.10.1 on 2026-11-06. M11.10 checks them again with `tusd -help` in the pinned image.
  - The `<api host>:<port>` is `huron:8080` (the API Service) on OpenShift,
    `{{ include "huron.fullname" . }}:{{ .Values.service.port }}` in the Helm chart, and
    `127.0.0.1:8080` in `make app` and `make api`.
  - The Service `huron-uploads` selects port `1080`. An edge Route (OpenShift) or an Ingress with
    path `/files` sends `https://<host>/files/…` to it. Its timeout is 3600 s, which covers the
    final PATCH: during that PATCH the API hashes the whole file inside `pre-finish`. tusd's
    `-hooks-http-timeout` equals `upload_hook_timeout`. tusd waits at most `upload_hook_timeout`
    for a hook, retries included. `upload_hook_timeout` is at most 55 minutes, so nginx's read
    timeout of 3600 s and the Route or Ingress timeout of 3600 s are always longer.
  - tusd sends a hook call again, up to three times with 1 s between calls, after a broken
    connection or any 5xx status (503 included). All calls run inside the one
    `-hooks-http-timeout`. A timeout is final: tusd does not send that hook again, and it
    answers the client with 500. A retry reaches the API only after a 5xx or a broken connection
    within the timeout, for example when an API pod stops during a rolling update. It can reach
    another API replica. So placement is idempotent ("Upload flow"), and a definitive refusal is
    a 4xx status in the hook response, never a 5xx. After a timeout the API's call continues and
    can still record the receipt. The CLI then reads the state of the upload ("The CLI").
- **Lake path (D-18 amended).** `lake_path` (`HURON_LAKE_PATH`) is the mount point of one
  filesystem in the API pod and in the upload pod, at the same path in both. The mount point
  never changes. Every declared organization root is `lake_path` or lies below it; startup
  refuses any other root ("Containment in the lake"). An unrooted organization lies directly
  below `lake_path`; the API has no `mount_prefix`. Every unit of disk work checks the
  organization's marker first (section 6.1, "The check"), in the disk worker and under the path
  lock (`LakeDisk.hold`, "The disk-access module"), as the CLI's `Mount` does before a read. A
  marker that is missing or names another instance or organization, a `lake_path` that the API
  cannot open as a directory, or a `lake_path` that `U` cannot write answers 503
  `LAKE_UNAVAILABLE`. `huron adm provision-orgs` makes `lake_path` and
  `${lake_path}/.tus-uploads` belong to `U:G` and writes the marker at `lake_path`
  ("Install order"). At startup the API creates `${lake_path}/.tus-uploads` (owner `U`,
  mode `0700`) when it is missing. `/readyz` reports `lake: false` while `lake_path` is set and
  `.tus-uploads` is not a directory that `U` can write. `/readyz` runs this probe in a thread,
  waits at most 2 seconds and keeps the result for 10 seconds. A probe that does not return in
  time reports `lake: false`. The mount is `hard`, so during an NFS outage a disk call blocks
  without end. Readiness then takes the API pods out of service. The API runs disk work in two
  dedicated pools, never in the default executor: a hash pool of 4 threads measures uploads
  (sub-steps 4 and 7 of "Upload flow"), and a disk pool of 8 threads runs the readiness probe and
  every other disk call. So a burst of large hashes never delays the probe or the short metadata
  calls (decided 2026-11-07). Without `lake_path`, the API serves
  no upload route (404 `UPLOADS_DISABLED`), and the directory verbs change only their rows
  ("Directory verbs in the API").
- **Containment in the lake (decided 2026-11-08, after the M11.5 escalation).** One rule keeps
  every disk operation inside the lake. It replaces the per-path device check.
  - A place on the disk is a `LakePath` (`core/storage/lakepath.py`): a tuple of names below the
    storage root. Each name passed `schema.naming.check_lake_name`: not empty, not `.` or `..`,
    no `/` or NUL, at most 255 bytes. A refusal is `NamingError` rule `lake_name`, 422
    `NAME_INVALID`. `LakePath` has no constructor from `Path`, no absolute form and no join that
    skips the check. `core.lake` produces API path strings and never imports `LakePath`.
  - No `Path` below `lake_path` exists in `core/storage` or `applications/api` outside
    `PosixStorage`. `PosixStorage(root)` opens the root with `O_PATH | O_DIRECTORY`. It opens
    the parent names one at a time with `openat(O_PATH | O_DIRECTORY | O_NOFOLLOW)`, and it runs
    the last step with the `dir_fd=` form and no follow. A root that does not open is
    `LakeUnavailable`.
  - A symbolic link at any step is `SymlinkInLake`: 409 `SYMLINK_IN_LAKE`, with the lake path of
    the link in `context.path`. Nothing is changed, and the link is not removed or replaced.
    Writes (`mkdir`, `chmod`, `chgrp`, `metadata.json`, `link`, `rename`, `unlink`, `rmdir`) and
    reads (the hash open, the marker, `metadata.json`, `stat`) refuse it the same way. `walk`
    yields a link as `kind="symlink"` and never enters it.
  - There is no `st_dev` compare, no mount-point check, no `OutsideLake`, no `OUTSIDE_LAKE` and
    no `resolve`. The only check on absolute paths runs at startup: `Settings` refuses a declared
    organization root that is not `lake_path` or below it.
  - Placement uses `link` (hard link) and `rename` only. Huron calls `symlink` nowhere.
    `MemoryStorage.symlink` exists for tests only: it plants the links that the refusal tests
    need.
  - A walker reports a link that it meets. Repair lists no directory, so it meets a link only
    on the traversal of a step and reports `symbolic_link` in `failed`. `remove_collection`
    keeps the directory (`KEPT`). An emptiness test counts a link as an entry, so a verb does not
    adopt the directory. `huron adm check` reports the error finding `symbolic_link`. The
    storage administrator removes the link. Huron never does.
  - The API service walks no tree. Four directory listings remain. Each goes through
    `Storage.walk` or `Storage.is_empty`, on the descriptor traversal:

    | Listing | Where | Extent and reason |
    | --- | --- | --- |
    | `is_empty` | `DirectoryWriter.remove`, `prune` | reads at most one entry of one directory, to decide `KEPT` or the adoption of an empty directory |
    | collection clean-up | `DirectoryWriter.remove_collection` (M11.5d) | one collection directory: `metadata.json`, part and backup files, then the empty subdirectories; a link below keeps the directory (`KEPT`) |
    | upload sweep | `Sweeper` (M11.6) | the one directory `.tus-uploads`, not recursive, to remove expired tusd files |
    | check and status | `huron adm check`, `context.unrecorded_files` (CLI, read-only `ShareReader` on a `ro` mount) | the organization tree, to compare it with the rows; the only recursive walk, and it writes nothing |

    The repair walk, the walks of `commands/delete.py`, `walk(on_error)` and the `_empty` helpers
    that walk are gone. The `os.walk` in `sync._collect` stays: it reads the user's local source
    folder for push staging, not the lake.
- **The disk-access module (decided 2026-11-08).** `core.storage.Storage` is the one
  disk-access module. Every byte that Huron writes or reads in the lake goes through it, on
  `LakePath`.
  - Behind the port: the traversal, the link refusal, the inheritance check
    (`InheritanceFailed`), emptiness, the inode guard and the mapping of `OSError` to
    `StorageError`, `SourceGone`, `SymlinkInLake` and `LakeUnavailable`.
  - The read side `ShareReader` has `stat(location) -> Stat | None`, `read_bytes`, `is_empty`,
    `walk` and `open_file`. `Stat` has `kind` (`file`, `dir`, `other`), `mode`, `gid`, `inode`
    and `size`; `stat` refuses a link. `walk` yields `Entry(names, kind, size, mtime_ns)` and
    has no error callback; M11.9 adds `kind="unreadable"` for a directory that it cannot list.
  - `Storage` adds `make_directory`, `make_inheriting_dir`, `set_mode`, `set_group`,
    `write_bytes` (mode required), `link(..., inode=)`, `rename`,
    `remove_file(..., inode=) -> Outcome`, `remove_directory -> Outcome`, and `in_group`
    (M11.5e). `Outcome` is `REMOVED`, `MISSING` or `KEPT`. `link` makes the hard link only when
    the source is a regular file with the measured inode, else `SourceGone`.
  - Gone from the port and both adapters: `exists`, `is_directory`, `owner`, `inode`, `stamp`,
    `hash`, `device`, `ensure_directory`, `apply_plan`, `read_acl`, `owned_by_me` and `copy_in`.
  - Two adapters: `PosixStorage(root)` and `MemoryStorage(root)`. `MemoryStorage` models links,
    not mounts. One contract suite (`tests/unit/storage/test_containment.py` and the port cases)
    runs over both.
  - Small synchronous rule modules sit above the port. Each is tested over both adapters without
    asyncio, and none touches `os` or `Path`:

    | Module | Rules |
    | --- | --- |
    | `core/storage/layout.py` | `OrganizationPlace(name, base, own_marker)`, `locate`, `mode_of(location)`, the modes, `UPLOADS` |
    | `core/storage/marker.py` | read and verify the marker on `LakePath` |
    | `core/storage/placement.py` | `Placer`: measure, `link(inode=)`, undo, drop the backup |
    | `core/storage/removal.py` | `prune`, `Unlinker` and `Sweeper` (M11.6) |
    | `core/storage/directories.py` | `DirectoryWriter(storage, service_gid)`: `make`, `set_group`, `write_metadata`, `remove`, `remove_collection` |
    | `core/storage/repair.py` | `Repairer`, `RepairStep`, `FailureReason`, `RepairResult` |
    | `core/storage/check.py`, `provision.py` | the read-side check; `Provisioner.provision` for the root and the organizations |

    `DirectoryWriter.set_group(location, share_group)` is the one home of the rule "a catalog
    without a share group carries the service group".
  - The API's disk layer is the package `applications/api/disk/`. It replaces `disk.py` and
    `routes/directories.py`. `LakeDisk` (`disk/lake.py`) holds the two pools, the `PathLocks`
    keyed by `LakePath`, the places and the marker. Its interface: `open`, `ready`, `close`,
    `locate(api_path) -> Located` (pure, no disk call, `NAME_INVALID` only),
    `hold(located, unit)`, `work(located, action)` and `measure(action)`.
    - `hold` is the one gate: the location's lock, the disk pool, and the marker verified first
      in the worker. A unit can await rows between two checked `run` calls (the receipt, a
      metadata render, a repair step's row read, a removal's re-check). `work` is the
      one-action case.
    - `measure` runs the hash in the hash pool, with no lock and no marker check. The locked
      link step checks the marker.
    - `Located(place, location)` is a value with no disk methods. `Located.joinpath` is used
      only by `Placements` (the collection directory and the file's `rel_path`).
  - The orchestrations, each with its rule object: `Placements` (`disk/placements.py`, placement
    with `Placer`), `LakeDirectories` and `NoLake` behind the protocol `Directories`
    (`disk/directories.py`, the verbs, with `DirectoryWriter`), `LakeRepair`
    (`disk/repair.py`, repair with `Repairer`) and `Removals` (`disk/removals.py`, the M11.6
    drain with `Unlinker`). `Runtime` builds them once. Without `lake_path` only `NoLake`
    exists, and the upload, repair and removal dependencies refuse (`UPLOADS_DISABLED`,
    `LAKE_UNAVAILABLE`).
  - A route never builds a path, reads a row for the disk or branches on the lake. The lake
    operation commits and returns the directory's API path; the route passes it to one verb.
  - Direction of dependency: routes, then the `disk/` orchestrations, then `LakeDisk`, then the
    `core.storage` rule modules, then the `Storage` port, then `PosixStorage`, then
    `pkg.fs.posix`. The CLI holds a `ShareReader` only.
- **Upload flow (D-23 amended).** The CLI creates one tus upload per staged add, with
  `Upload-Length` and the metadata `collection` (UUID) and `rel_path`, and sends
  `Authorization: Bearer <Huron token>` on every request. Every request reaches tusd through
  nginx, which authorizes it first. tusd sends its hooks to `POST /api/v1/uploads/hooks` with the
  forwarded `Authorization` header. The route verifies that token itself. The route answers 200
  with a tusd v2 hook response. A refusal carries `"HTTPResponse": {"StatusCode": <status>,
  "Header": {"Content-Type": "application/problem+json"}, "Body": <problem document>}`, and each
  hook has its own refusal field (`pkg/hooks/hooks.go` of v2.10.1):
  - `pre-create` adds `"RejectUpload": true`.
  - `pre-terminate` adds `"RejectTermination": true`.
  - `pre-finish` has no refusal field. tusd merges `HTTPResponse` into the response of the final
    PATCH, so the client sees the status, but tusd still treats the upload as finished. The
    sweep later removes what stays in `.tus-uploads`.

  A missing or invalid token answers a refusal with the 401 problem (`UNAUTHENTICATED` or
  `TOKEN_INVALID`), not an HTTP 401, so tusd passes the status to the client. The route needs no
  shared secret: a user who calls it directly gains nothing, as each step below shows.
  1. `pre-create`: the API reads `collection` and `rel_path` from `Event.Upload.MetaData` and the
     size from `Event.Upload.Size`. A deferred length, a partial upload or a concatenation is
     refused with 422 `REQUEST_INVALID`. `Uploads.begin` authorizes `COLLECTION_WRITE_FILES` on
     the catalog, requires a settled collection, checks `rel_path` with `check_rel_path`,
     `size >= 0` and `size <= upload_max_size` when set, and inserts an upload row (`pending`).
     The answer carries `ChangeFileInfo.ID` = the upload's UUID. A direct caller only gets a
     pending row of their own. A zero-length upload finishes in the creation POST (tusd's
     `PostFile`), so tusd calls `pre-finish` at once, and its result and `Huron-Sha256` come with
     the POST response.
  2. `pre-finish`: M11.1's `Uploads.placement` requires a `pending` row, so the hook handler
     orders the calls. All disk work runs in the API's disk pool.
     1. `Uploads.get(actor, id)` (creator only). State `placed` or `committed`: the API answers
        success with the stored `Huron-Upload-Id` and `Huron-Sha256` and does no disk work. State
        `failed` or `terminated`: the API answers the refusal 409 `UPLOAD_STATE_CONFLICT`.
     2. `Uploads.placement(actor, id)` (a `pending` row, the collection still settled and
        writable) returns `Destination(directory, rel_path)`: the collection's `disk_path` and
        the upload's `rel_path`.
     3. `Placements.place` locates the collection directory with `LakeDisk.locate` (pure, no
        disk call) and joins the names of `rel_path` to it. The marker check and the
        traversal run in the locked step (sub-step 5), not before the hash.
     4. Outside every lock (`LakeDisk.measure`, the hash pool), the API opens
        `.tus-uploads/<id>` read-only through the traversal. `fstat` on the
        descriptor gives the size and the inode; the open makes the NFS client read the
        attributes again. A size other than the declared size is the refusal 422
        `UPLOAD_SIZE_MISMATCH`, and the row stays `pending`. The API hashes the file from the
        descriptor and sets mode `0644` with `fchmod` on it (`U` owns the file). `ENOENT` at the
        open goes to sub-step 7.
     5. Under the API's in-process lock on the destination path (`LakeDisk.hold`, the marker
        first): the collection directory must exist. The placement never creates it. A
        symbolic link at the destination or on the way to it refuses the placement with
        `SYMLINK_IN_LAKE`: the API records it with `Uploads.fail` (row `failed`) and answers
        the 409 refusal. When the collection directory is missing, the API records
        `STORAGE_FAILED` with `Uploads.fail` (row `failed`) and answers a refusal that carries
        the 500 `STORAGE_FAILED` problem with the hint `huron adm repair`. The route itself
        answers 200, so tusd does not call the hook again. The API creates the missing
        intermediate directories below the collection directory with `make_inheriting_dir`
        ("Catalog share group and directory modes"). It links the file to
        its destination with `link`, only when the source is a regular file with the inode of
        sub-step 4 (else sub-step 7). On `EEXIST` it links the file to `.<name>.<id>.huron-part`
        beside the destination (on `EEXIST` there: unlink the part file, link again), links the
        existing destination to the backup `.<name>.<id>.huron-prev` (on `EEXIST` there: unlink
        the backup, link again), and `rename`s the part over the destination. The backup keeps
        the bytes that the overwrite replaces until the receipt is recorded (decided 2026-11-07).
        `ENOENT` on the link source goes to sub-step 7.
        The API unlinks `.tus-uploads/<id>` and `<id>.info`; `ENOENT` is not an error. Then,
        still under the lock, `Uploads.receipt(id, size, sha256, inode)` with the inode from
        sub-step 4 marks the row `placed`. After the receipt the API unlinks the backup
        (`ENOENT` is not an error). The answer carries the response headers
        `Huron-Upload-Id` and `Huron-Sha256`, which tusd adds to the final PATCH.
     6. When the receipt raises `UploadNotFound` or `UploadStateConflict` (the collection was
        deleted, or the creator terminated the upload during the hash), the API, under the same
        lock, undoes the placement when the destination's inode equals the placed inode: with a
        backup it `rename`s the backup over the destination, so the replaced bytes return;
        without one it unlinks the destination. It removes the empty intermediate directories
        that sub-step 5 made, and answers the refusal with the domain error's status (404 or
        409). A crash between the link and the receipt is an accepted residual, which
        `file_unrecorded` reports; a backup left by a crash is reported as `stale_part`.
     7. Idempotent branch (another attempt moved the source): the API reads the row again.
        `placed`: as sub-step 1. `pending` and the destination exists with the declared size: the
        API opens the destination, hashes it, takes the inode with `fstat`, sends the receipt and
        unlinks the backup when present. Otherwise the route answers 500 `STORAGE_FAILED`, and
        tusd calls the hook again.

     A receipt for a row that is already `placed` with the same `(size, sha256)` keeps the first
     inode and succeeds (M11.1's behaviour). `SYMLINK_IN_LAKE` and a size mismatch are
     definitive: the API records `SYMLINK_IN_LAKE` with `Uploads.fail` (row `failed`) and answers
     the refusal with the code's status, a 4xx, so tusd does not call the hook again. The file in
     `.tus-uploads` stays until the sweep. `LAKE_UNAVAILABLE` and the `STORAGE_FAILED` of
     sub-step 7 answer an HTTP 503 or 500 from the route, so tusd calls the hook again, on any
     replica, inside the one timeout. When the retries or the timeout run out, the client sees a
     500 and the row stays `pending`, unless the running call still records the receipt. A
     direct caller cannot place
     anything: the file in `.tus-uploads/<id>` must exist with the declared size.
  3. `pre-terminate`: `Uploads.terminate` by the same user marks the row `terminated`. tusd then
     removes its files. A direct caller marks only their own row.
  4. The commit (D-7 unchanged in shape). With `lake_path`, every add must be proved by the
     latest placement of its path ("Latest placement wins"), else 422 `UPLOAD_RECEIPT_MISSING`
     with `{rel_path}`. The applied commit marks those rows `committed` with its `commit_id` and
     copies each receipt's `inode` into `files.inode`. Without `lake_path` no route can issue a
     receipt, so the API records an add without one, with a `null` inode. There is no setting
     for this rule. `ReceiptMode` stays a bootstrap parameter of `core.lake` for the API without
     a lake and for the seeds. A dry run checks no receipt.
- **Authorization in front of tusd.** tusd calls no hook for HEAD, PATCH or DELETE, so without a
  proxy the upload URL alone would be a credential between creation and finish. The `proxy`
  container uses nginx's `auth_request`: each request to `/files/`, except OPTIONS, first makes a
  subrequest without a body to `GET /api/v1/uploads/auth` of the API. nginx sends the request to
  tusd only when the API answers 2xx. It answers 401 or 403 itself, before any byte reaches tusd.
  The body streams through nginx to tusd and never passes through Python. nginx sends OPTIONS to
  tusd without `auth_request`, through the named location `@tus_options`. tusd's OPTIONS reads no
  upload state.
  - **`GET /api/v1/uploads/auth`.** The API reads the original method from `X-Original-Method`,
    the original path from `X-Original-URI` (the query string removed) and the user's token from
    `Authorization`. The route has no rule for OPTIONS. The rules, in order:
    1. `POST` to exactly `/files/` (creation, no upload id yet) answers 204 when the request has
       `Authorization: Bearer …`, otherwise 401. `pre-create` decides the creation.
    2. Any method on `/files/<id>`: `<id>` must be a UUID, otherwise 403. Without a valid token
       the answer is 401 with `WWW-Authenticate: Bearer`. When the token's user created upload
       `<id>` (`Uploads.get`), the answer is 204. Otherwise (no such upload, or another user's)
       the answer is 403.
    3. Any other path answers 403.

    Without `lake_path` the route answers 404 `UPLOADS_DISABLED`, which nginx turns into a 500.
    nginx copies `WWW-Authenticate` from a 401 subrequest to the client.
  - **Cache.** nginx caches allows only, with `proxy_cache`. The key is the original method, the
    upload id and the `Authorization` value. Only a 204 is cached, for 30 seconds. A creation
    (empty id) and a request without `Authorization` are never cached. Every auth subrequest is a
    GET for the cache, so the key must hold the original method: without it, an allow for one
    method would serve another. The cache lives in the container's `/tmp` (an `emptyDir` with
    `medium: Memory`), which only the `proxy` container reads. nginx writes the key into each
    cache entry, so the cache holds the token value for at most 60 seconds after the last request
    of that upload and token (`inactive`).
  - **nginx configuration.** One file, `deploy/openshift/nginx-uploads.conf.template`. The Helm
    chart holds a byte-identical copy in `deploy/helm/huron/files/nginx-uploads.conf.template`,
    and `make app` and `make uploads` mount the kustomize file. `tests/unit/test_nginx_config.py`
    keeps the two equal. `${HURON_API_UPSTREAM}` is the one substituted variable. The shape:

    ```nginx
    worker_processes 1;
    pid /tmp/nginx.pid;
    error_log /dev/stderr warn;
    events { worker_connections 1024; }
    http {
        log_format huron '$remote_addr "$request_method $uri" $status $request_length $request_time';
        access_log /dev/stdout huron;           # never logs Authorization
        client_body_temp_path /tmp/client-body;
        proxy_temp_path /tmp/proxy;
        fastcgi_temp_path /tmp/fastcgi;
        uwsgi_temp_path /tmp/uwsgi;
        scgi_temp_path /tmp/scgi;
        proxy_cache_path /tmp/auth-cache levels=1 keys_zone=huron_auth:1m max_size=16m inactive=60s;
        server_tokens off;

        map $http_x_forwarded_proto $huron_proto { default $http_x_forwarded_proto; "" $scheme; }
        map $http_x_forwarded_host  $huron_host  { default $http_x_forwarded_host;  "" $http_host; }
        # The upload id of /files/<id>; empty for a creation, which is never cached.
        map $request_uri $huron_upload_id { "~^/files/(?<id>[0-9a-f-]{36})(\?|$)" $id; default ""; }
        map $huron_upload_id $huron_no_cache { "" 1; default 0; }
        # A request without Authorization is never cached.
        map $http_authorization $huron_no_auth { "" 1; default 0; }

        upstream tusd { server 127.0.0.1:1081; keepalive 16; }
        upstream api  { server ${HURON_API_UPSTREAM}; keepalive 16; }

        server {
            listen 1080;
            client_body_timeout 300s;
            send_timeout 300s;
            proxy_http_version 1.1;
            proxy_redirect off;                  # tusd builds Location from X-Forwarded-*
            proxy_set_header Connection "";
            proxy_set_header Host $http_host;
            proxy_set_header X-Forwarded-Host $huron_host;
            proxy_set_header X-Forwarded-Proto $huron_proto;
            proxy_set_header Forwarded "";       # tusd applies Forwarded after X-Forwarded-*

            location = /files/ {                 # creation: POST
                error_page 418 = @tus_options;
                if ($request_method = OPTIONS) { return 418; }
                auth_request /_huron_auth;
                client_max_body_size 1m;         # no large creation-with-upload body
                proxy_request_buffering off;
                proxy_buffering off;
                proxy_read_timeout 120s;
                proxy_pass http://tusd;
            }
            location /files/ {                   # HEAD, PATCH, DELETE of /files/<id>
                error_page 418 = @tus_options;
                if ($request_method = OPTIONS) { return 418; }
                auth_request /_huron_auth;
                client_max_body_size 0;
                proxy_request_buffering off;
                proxy_buffering off;
                proxy_send_timeout 300s;
                proxy_read_timeout 3600s;        # the final PATCH waits for pre-finish
                proxy_pass http://tusd;
            }
            location @tus_options {              # OPTIONS without auth_request
                proxy_pass http://tusd;
            }
            location = /_huron_auth {
                internal;
                proxy_pass http://api/api/v1/uploads/auth;
                proxy_method GET;
                proxy_pass_request_body off;
                proxy_set_header Content-Length "";
                proxy_set_header Connection "";
                proxy_set_header X-Original-Method $request_method;
                proxy_set_header X-Original-URI $request_uri;
                proxy_connect_timeout 2s;
                proxy_read_timeout 10s;
                proxy_cache huron_auth;
                proxy_cache_key "$request_method|$huron_upload_id|$http_authorization";
                proxy_cache_valid 204 30s;
                proxy_cache_methods GET;
                proxy_no_cache $huron_no_cache $huron_no_auth;
                proxy_cache_bypass $huron_no_cache $huron_no_auth;
                proxy_ignore_headers Cache-Control Expires Set-Cookie Vary;
            }
            location = /readyz {                 # tusd answers OPTIONS /files/ with Tus-Version
                proxy_method OPTIONS;
                proxy_pass http://tusd/files/;
            }
            location = /livez { return 204; }
            location / { return 404; }
        }
    }
    ```

    The request headers tusd needs pass unchanged: `Authorization` (forwarded to the hooks),
    `Tus-Resumable`, `Upload-Length`, `Upload-Offset`, `Upload-Metadata` and `Content-Type`. The
    response headers `Location`, `Upload-Offset`, `Huron-Upload-Id` and `Huron-Sha256` pass
    unchanged. With `-behind-proxy`, tusd builds `Location` from `X-Forwarded-Host` and
    `X-Forwarded-Proto`. tusd applies a `Forwarded` header after them, so nginx clears
    `Forwarded`. In the auth subrequest, `$request_method` and `$request_uri` are those of the
    original request. A location that sets its own `proxy_set_header` loses the server's. So the
    server sets the headers for tusd once, and both `/files/` locations and `@tus_options`, which
    set none, keep them all, `Forwarded ""` included. `/_huron_auth` sets its own and sets
    `Connection` again. The `if` holds only a `return`, which runs before `auth_request`. An
    `auth_request` answer other than 2xx, 401 or 403 reaches the client as a 500, and the tus
    client retries.
  - **Pod layout, the same in every target.** nginx on port 1080 (published or selected) and
    tusd on 127.0.0.1:1081. Before tusd starts, the stale tusd lock files in `.tus-uploads` are
    deleted (the `clean-locks` init container on Kubernetes, a step before tusd in the
    development stacks). The readiness probe of the pod is `GET /readyz` on port 1080, which
    nginx answers from tusd's `OPTIONS /files/`. The liveness probe is `GET /livez`. tusd has no
    probe of its own.
  - **Remaining limits.**
    - A creation passes nginx with a bearer token that nginx does not verify. `pre-create`
      verifies it. A refused creation stores no byte.
    - OPTIONS reaches tusd without authorization. tusd answers it from its configuration and
      reads no upload state.
    - For at most 30 seconds, a cached allow can outlive the token's expiry or the upload's
      termination. tusd refuses requests to an upload whose files are gone.
    - The bearer token is the credential for every upload of its user, as for every API call.
      Tokens live `token_ttl_seconds` (8 hours by default).
    - Processes inside the upload pod reach tusd on 127.0.0.1 without the proxy. In `make app`,
      every container of the shared network namespace can reach tusd on 127.0.0.1:1081.
    - The hooks route is reachable by every client of the API. This is safe: a direct caller
      gains nothing ("Upload flow"). There is no NetworkPolicy for it, because a NetworkPolicy
      selects pods and ports, not HTTP paths.
    - The size limit is tusd's `-max-size` and the API's `upload_max_size`. nginx has none
      (`client_max_body_size 0`).
    - A failed `pre-finish` reaches the client as the status in the hook response, or as a 500
      after a hook timeout or after tusd's retries. The client reads the reason from
      `GET /api/v1/uploads/{id}` ("The CLI").
    - Each request other than OPTIONS adds one subrequest. At most one API call per upload,
      method and token is made in 30 seconds.
    - One replica. nginx adds no availability.
- **Catalog share group and directory modes (D-20 and D-21 amended).** One read group per
  catalog. `catalogs.share_group` (nullable text, an LDAP POSIX group name) is set with
  `huron create catalog --share-group <group>` and changed with
  `huron set catalog <catalog> --share-group <group>` (`PATCH /api/v1/catalogs/{catalog}`
  `{share_group}`, `null` clears it, `CATALOG_GRANT_ADMIN` on the catalog, version + 1, audit
  action `catalog.set_share_group`). A name must match `^[A-Za-z_][A-Za-z0-9_.-]{0,31}$`;
  `Catalogs.create` and `Catalogs.set_share_group` refuse any other value with 422
  `REQUEST_INVALID`. `Catalogs.set_share_group` takes the catalog lock (`tx.lock_catalog`) and
  reads the catalog again after the lock. The PATCH takes no `If-Match`, like the namespace
  PATCH, because the catalog lock serializes it. The create and the PATCH answer
  `CatalogWriteOut`: the fields of `CatalogOut` and `warnings: list[ShareWarningOut]`.
  `GET /catalogs/{catalog}` answers `CatalogOut`, which reports `share_group`.
  - Modes, owners and groups (`core.storage.layout`):

    | Entry | Mode | Owner | Group | Who reads |
    | --- | --- | --- | --- | --- |
    | organization directory | `2751` | `U` | `G` | everyone traverses, nobody lists |
    | catalog directory | `2750` | `U` | `share_group` | members of the share group |
    | namespace, collection and intermediate directories | `2750` | `U` | inherited from the parent (setgid) | members of the share group |
    | placed file | `0644` | `U` | `G` (from `.tus-uploads`) | whoever traverses the ancestors |
    | `metadata.json` | `0644` | `U` | inherited | whoever traverses the ancestors |
    | `.tus-uploads` and its entries | `0700`, files `0600` | `U` | `G` | only `U` |

    `link` and `rename` keep the group of the inode, so a placed file keeps `G` from
    `.tus-uploads`. Reads of a file depend only on its mode `0644` and on the `2750` directories
    above it. `mode_drift` and `share_group_mismatch` never compare the group of a file.
  - Setgid makes every entry below the catalog inherit the catalog's group when `U` creates it.
    So `U` needs no membership in the share group. A catalog without a share group inherits `G`,
    and nobody but `U` can read it. The storage administrator keeps `others` traverse-only
    (`--x`) on `lake_path` and on every root.
  - The inheritance on this export is not measured yet, so the claim in the previous bullet is
    conditional on a measurement by the operator. As `U`, not a member of a group `S`, in a
    directory `2750 root:S` on the real export: `mkdir d; touch f; stat -c '%a %U %G' d f` must
    print `2750 U S` and `644 U S`. Also, a member of `S` runs `chgrp S` on a directory, and the
    setgid bit must stay. The operator also records the volume security style (UNIX, NTFS or
    mixed). The result goes into "Facts about the storage (measured 2026-11-06)" before M11.13
    starts. The code tasks do not wait: the `stat` after each `mkdir` (next bullet)
    makes a failed inheritance visible.
  - `chmod(2)` by a caller that is not in the file's group clears `S_ISGID` without an error.
    `mkdir(2)` sets only the permission bits, so the setgid bit and the group of a new directory
    come only from the server's inheritance. Below a catalog directory the API therefore never
    calls `chmod` on a directory whose permission bits are already right. It calls
    `make_inheriting_dir`: `mkdir(path, 0o750)`, then `stat` on the result. A missing `S_ISGID`,
    or a group other than the parent's, is `STORAGE_FAILED` in a directory verb and a
    `mode_drift` finding in a repair, never a silent `chmod`. The existing
    `pkg/fs/posix.make_dir` (mkdir, then chmod) is not used below a catalog. Repair fixes
    permission bits only. A missing setgid bit or a wrong directory group needs the storage
    administrator (`huron adm provision-catalogs`).
  - **`chgrp` is a storage-administrator step.** `U` cannot `chgrp` a directory to a group it is
    not a member of (AUTH_SYS, no `CAP_CHOWN`). `huron create catalog` creates the directory with
    the organization's group and records `share_group`. The API then tries `chgrp` (by name,
    through `grp.getgrnam`). The storage port answers `GroupResult(outcome, reason)`, with
    `GroupOutcome` `CHANGED`, `UNCHANGED` or `PENDING`; `GroupResult` and
    `ShareWarning(code, group, detail)` are in `core/storage/ports.py`. When the `chgrp`
    succeeds, the catalog response carries no warning. When it fails, or the name is unknown in
    the pod, the create and set responses carry
    `warnings: [{"code": "SHARE_GROUP_PENDING", "group": "<group>", "detail": "<reason>"}]`, the
    CLI prints the hint `To set the group on disk, run huron adm provision-catalogs
    --emit-script as the storage administrator`, and `huron adm check` reports
    `share_group_mismatch` until the group on disk matches.
  - `huron adm provision-catalogs [--catalog C] [--dry-run] [--emit-script [--uid U] [--gid GID]]`
    selects every catalog whose directory's group differs from its expected group, or below
    which a directory has `mode_drift` for the setgid bit or the group. The expected group is the
    catalog's `share_group`, or `G` (by its gid) for a catalog without one, so a cleared share
    group whose reset failed is selected too, and `<group>` below is that group. This is the
    selection rule of M11.9 (`provision_catalogs`); a catalog that the CLI cannot read is not
    selected for that reason only, because the check reports it as `unreadable`. In direct mode
    (root on a writable mount, or `U` with the right supplementary groups) it runs one line for
    each selected catalog: `find <catalog dir> -type d -exec chgrp <group> {} + -exec chmod 2750 {} +`.
    The line changes the group of directories only; files keep their group `G` and their mode
    `0644`. `find` keeps its default `-P`, so it follows no symbolic link. The directories below
    the catalog need the line too, because a namespace made while the share group was pending
    inherited the organization's group. With `--emit-script` it prints the same line as a shell
    script, for root, and changes nothing. The script quotes every name with `shlex.quote`. A
    later change of `share_group` goes through the same command, with the same line.
  - Documented option for small sites: list the catalog groups in the API pod's
    `supplementalGroups`. About 14 catalog groups fit: AUTH_SYS carries at most 16 groups, and
    the default `fsGroup` and `G` take two of them. The API pod must also resolve the group names
    (the API's `chgrp` looks the name up with `getgrnam`). The API's own `chgrp` then succeeds,
    and `provision-catalogs` has nothing to do.
- **Directory verbs in the API.** Every path is built from validated names below `lake_path`
  and opened without following a symbolic link; a link answers 409 `SYMLINK_IN_LAKE`
  ("Containment in the lake"). The lake operation writes its rows, commits the transaction and
  returns the directory's API path (the `disk_path` of its view). The route passes that path to
  one verb of `Directories` ("The disk-access module"). The verb locates it with
  `LakeDisk.locate` (pure) and does its disk work with `LakeDisk.work`: in a worker thread of
  the disk pool, under the API's in-process lock on the directory path, with the marker checked
  first ("Lake path"). It answers when the disk work is done. Every name in an API path passed
  `check_segment` or `check_rel_path` when its row was written, and those rules imply
  `check_lake_name`. A path that `locate` refuses comes only from a corrupted row: it answers
  422 `NAME_INVALID` with the rows kept, like any other failure after the commit.

  | Verb | Route | Disk work after the commit |
  | --- | --- | --- |
  | create organization (unmanaged) | `POST /organizations` | `mkdir <lake_path>/<org>` mode `2751` |
  | create catalog | `POST /organizations/{org}/catalogs` | `mkdir` mode `0750` (setgid and group inherited), then the `chgrp` attempt |
  | set share group | `PATCH /catalogs/{catalog}` | the `chgrp` attempt |
  | create namespace | `POST /catalogs/{catalog}/namespaces` | `mkdir` mode `0750` (setgid and group inherited; the CLI's `--parents` calls the route once per missing ancestor) |
  | activate collection | `POST /collections/{id}/activate` | `mkdir` mode `0750` (setgid and group inherited), then `metadata.json` written atomically, mode `0644` |
  | publish metadata, set or unset the override | `PATCH /collections/{id}` | `metadata.json` rewritten when its bytes changed (settled collections only) |
  | assign a schema | `PUT /catalogs/{catalog}/schema` | `metadata.json` of each settled collection whose bytes changed, each under its own collection lock, in identifier order; the first failure ends the request |
  | delete collection | `DELETE /collections/{id}` | drain the delete's removals ("Removals and the inode guard"), then unlink `metadata.json`, `.huron-part` and `.huron-prev` files and empty subdirectories, then `rmdir`; a symbolic link below keeps the directory |
  | delete namespace, catalog | `DELETE /catalogs/{catalog}/namespaces/{path}`, `DELETE /catalogs/{catalog}` | `rmdir` |
  | delete organization (unmanaged, unrooted) | `DELETE /organizations/{org}` | `rmdir` |

  - **Directories below a catalog inherit.** `chmod(2)` by a caller that is not in the group of
    the directory clears `S_ISGID` without an error. `mkdir(2)` applies only the permission bits.
    So the setgid bit and the group of a new directory come only from the server's inheritance.
    Below a catalog directory, the API calls `mkdir(path, 0o750)` and never calls `chmod` on a
    directory whose permission bits are already correct. After `mkdir` it does a `stat` of the
    result. A missing `S_ISGID`, or a group that is not the parent's group, answers 500
    `STORAGE_FAILED` in a verb. It is never repaired with a silent `chmod`. The existing
    `pkg/fs/posix.make_dir` (`mkdir`, then `chmod`) is not used below a catalog. The new
    `pkg/fs/posix.make_inheriting_dir` does `mkdir`, then the `stat` check.
  - **An entry that exists.** A `mkdir` that meets an empty directory adopts it. A symbolic link
    at the path answers 409 `SYMLINK_IN_LAKE`. Any other entry at the path answers 500
    `STORAGE_FAILED`. The rows are kept in both cases.
  - **`metadata.json`.** Inside the path lock, the API reads the collection (and the catalog's
    schema) again in a new read. It renders `metadata.json` from those rows and writes only when
    the bytes differ. It never renders from the request's copy of the rows. So two changes that
    commit in one order cannot write the file in the other order.
  - A disk failure after the commit of a create, set, activate, publish or assign verb answers
    500 `STORAGE_FAILED`, 503 `LAKE_UNAVAILABLE` or 409 `SYMLINK_IN_LAKE`, with the rows kept.
    A path from a corrupted row answers 422 `NAME_INVALID` (see above). These four are the only
    errors after the commit. No route and no verb catches or remaps them.
    The verb is repaired with `huron adm repair <identifier> [--recursive]`. For a symbolic
    link the storage administrator removes the link first. Running the create command again
    does not repair: `NAME_TAKEN` stays an error.
  - For a delete verb the rows are gone when the disk work runs. `Collections.delete` returns
    `DeletedCollection(disk_path, removals)`, with the removal rows that the delete claimed. The
    namespace and catalog deletes return their `disk_path`. The collection delete drains its
    removals first, then runs `remove_collection`. A directory that is not empty (`ENOTEMPTY`) is
    not a failure: the API leaves it, logs a warning and answers 204. `huron adm check` then
    reports it as `dir_unrecorded`, and the storage administrator decides what to do with it.
    Any other disk failure answers 500 `STORAGE_FAILED` with the rows gone, and `huron adm check`
    reports the directory the same way.
  - Without `lake_path` every verb changes only its rows and answers as if the disk work
    succeeded (`NoLake`, the one statement of this rule; the routes have no lake branch). This
    keeps the web's e2e harness, which runs the API without a lake, working.
    `huron adm check` reports the missing directories, and `huron adm repair` makes them once a
    lake is mounted.
  - **Repair.** `POST /api/v1/catalogs/{catalog}/repair` `{target, recursive}` repairs the
    catalog, a namespace or a settled collection named by `target` (an identifier). The lake
    operation `Repairs.plan(actor, catalog, target, recursive) -> RepairPlan` authorizes
    `NAMESPACE_CONFIGURE` on the catalog. The plan lists the planned directories from the rows,
    outermost first (the target's chain, and with `recursive` the planned namespaces and settled
    collections below the target), and the catalog's share group. Repair has no walk: nothing
    lists a directory, so nothing below a planned directory is entered, changed or skipped.
    `LakeRepair.repair(repairs, plan)` runs one step per planned directory on `LakeDisk.hold`,
    under that directory's lock, after the marker. Each step traverses again from the root:
    1. It makes the directory when it is missing (`DirectoryWriter.make`, with the rules of
       "Directories below a catalog inherit").
    2. It sets the permission bits only while `U` is in the directory's group (`in_group`, which
       trusts only the first 16 groups), because a `chmod` by a non-member clears `S_ISGID`.
    3. On the catalog directory only, it tries the share group (`set_group`).
    4. For a settled collection, it writes `metadata.json` when the bytes differ.
    - Repair fixes permission bits only. A directory below the catalog without the setgid bit, or
      with a group that is not the catalog directory's, goes into `failed` with the reason
      `mode_drift`. The storage administrator fixes it with `huron adm provision-catalogs`.
    - A symbolic link at or above a step's directory is that step's failure with the reason
      `symbolic_link` and the link's path. Nothing is changed. The steps after it run and
      report the same link once. Any other `StorageError` is the step's failure with the reason
      `storage_failed`. Only `LAKE_UNAVAILABLE` ends the repair (503). File modes and
      directories that no row plans are `huron adm check`'s findings.
    - Repair reads rows only. It reads the rows of each planned directory again under that
      directory's lock (`Repairs.expected`), before the step; a directory whose row is gone is
      skipped.
    - `POST /api/v1/organizations/{org}/repair` (`CATALOG_GRANT_ADMIN` on the organization)
      repairs the organization directory's mode (`2751`) and, for an unmanaged unrooted
      organization, makes the directory when it is missing.
    - Both routes answer 200 with `{"changed": [<path>…], "warnings": [<SHARE_GROUP_PENDING
      warnings>], "failed": [{"path": <path>, "reason": <reason>, "detail": <detail>}…]}`.
      `reason` is `mode_drift`, `symbolic_link` or `storage_failed`. Paths are lake paths in the
      API form. A repair is idempotent. Without `lake_path` both routes answer 503
      `LAKE_UNAVAILABLE`.
    - Residual: a delete and a create of the same directory on two replicas can leave the
      directory missing. `huron adm check` reports it (`*_dir_missing`), and `huron adm repair`
      makes it.
- **Removals and the inode guard.** M11.1's `removals` outbox stays as the durable queue. A
  commit's removes are recorded first, as before. The applied commit inserts one removal row per
  removed path, with `path`, `collection_id`, `commit_id`, `rel_path`, `rel_path_key`, `sha256`
  and the file's recorded `inode`, and it deletes the removal rows of the keys it adds again,
  claimed or not. It returns its claimed rows in `CommitResult.removals`. A collection delete
  inserts one removal per `placed` uncommitted upload (`Upload.removal`, inode from the receipt)
  and returns them in `DeletedCollection.removals`. Both insert their rows with `claimed_at` =
  now, so the request that made them owns them.
  - **The request drains its own rows** right after the commit (`Removals.drain`): for each row,
    on `LakeDisk.hold` with the API's in-process lock on the file path, it asks
    `Uploads.removal_still_valid`, unlinks the file when the row is valid, and calls
    `Uploads.finish_removal`. The response waits for the unlinks.
  - **Unlink results.** `remove_file(location, inode=)` answers an `Outcome`. `MISSING`, or
    `KEPT` for an inode on disk that differs from the row's, finishes the row. Any other error
    (`EACCES`, `EIO`, `SYMLINK_IN_LAKE`, a marker refusal) leaves the row claimed. The API logs
    a warning, and the commit or delete keeps its 200 or 204. The runner takes the row again
    after `REMOVAL_LEASE`.
  - **Empty directories.** After a successful unlink, the drain removes the empty directories
    from the file's parent up to the collection directory, not the collection directory itself
    (`prune`). The collection directory belongs to the delete verb.
  - **The background runner** (an API lifespan task, started only when `lake_path` is set)
    drains the leftovers every `removal_interval` (default 60 s): `Uploads.claim_removals`
    takes rows nobody claimed and rows whose claim is older than `REMOVAL_LEASE` (15 minutes),
    then the same steps. On PostgreSQL one replica is elected with `pg_try_advisory_lock` on a
    dedicated connection (`ClosableStore.lease_runner()`), and the others try again every
    `removal_interval`. The election saves work. Correctness does not depend on it: it rests on
    `for update skip locked` and on unlinks that accept `ENOENT`. The election connection sets
    TCP keepalives (`keepalives_idle=30`, `keepalives_interval=10`, `keepalives_count=3`), and
    the runner stops when that connection drops. The memory store runs the runner in-process.
    The runner also runs the sweep ("Sweep").
  - **Inode guard.** A removal may race a placement of the same path on another API replica.
    So receipts record the placed file's inode (`uploads.inode`, from `fstat` on the hashed
    descriptor), the commit copies it to `files.inode`, a removal row carries the removed file's
    `inode`, and the unlink happens only when the inode on disk matches. A removal without an
    inode (a file committed by an API without a lake) is finished with no disk call. A file
    whose inode differs is left alone and the removal finishes.
    Accepted residuals: the file system can give a freed inode number to a new file, so the
    guard is strong but not exact; and across replicas a narrow window remains between the
    `stat` and the `unlink`. `huron adm check --hash` detects both.
  - `collection_id` and `commit_id` are `on delete set null`, so a removal survives the deletion
    of its collection. `removal_still_valid` is M11.1's: a settled collection now at the row's
    directory that records the key, or whose latest placement of the key is `placed` and
    younger than `upload_ttl`, makes the removal invalid. Cancellation and validity compare
    `rel_path_key`, never the exact spelling. On a case-insensitive share, unlinking the old
    spelling would remove the new file. So a case-only rename leaves the old spelling on disk,
    and `huron adm check` reports it as `file_unrecorded`.
  - `huron delete collection` makes no check of unrecorded files before it asks the API. The
    API delete unlinks only what the collection recorded or placed. Any other file stays, and
    `huron adm check` reports the directory as `dir_unrecorded`. The CLI help says so.
- **Sweep.** Every `sweep_interval` (default 10 minutes) the runner removes every entry of
  `.tus-uploads` whose modification time is older than `upload_ttl` (default 24 hours). This
  covers `<id>`, `<id>.info`, `<id>.lock`, `<id>.stop` and the temporary files of tusd's lock.
  tusd itself never cleans up. The sweep (`Sweeper`) lists `.tus-uploads` with `walk`, one level,
  not recursive, and touches nothing outside `.tus-uploads`. Stale lock files
  of an unclean stop are removed before tusd starts ("Deployment"). `huron adm check` reports
  `.huron-part` and `.huron-prev` files in collections as `stale_part`.
- **Install order (decided 2026-11-08).** Production starts from scratch: there are no version 1
  directories or files to convert. The storage administrator runs the printed root scripts as
  root, on a machine with a writable mount (the storage system's own shell, or a client that the
  export does not squash). The scripts use the numeric owner `U:<gid>`, never a group name for
  `G`. They read `U` and `<gid>` from `service_user` of `GET /healthz`. The options `--uid` and
  `--gid` of `--emit-script` override them.
  1. Deploy the API and the upload pod with `service_uid`, `service_group`, `lake_path` and
     `uploads_url`. A from-scratch install sets `lake_path` from the first deploy.
  2. Run `huron adm provision-orgs --emit-script > orgs.sh`, which only prints, and run `orgs.sh`
     as root. For `lake_path` it runs `chown U:<gid>` and `chmod 2751`, makes `.tus-uploads`
     (owner `U:<gid>`, mode `0700`) and writes the marker at `lake_path` with no `organization`
     field.
     That marker guards every organization without its own marker. For each declared
     organization it requires the root to exist (the storage administrator makes it), runs
     `mkdir`, `chown U:<gid>` and `chmod 2751` on `<root>/<org>`, and writes its marker (`0644`).
     No line is recursive. The work is `Provisioner.provision`
     (`core/storage/provision.py`). An unmanaged organization needs no provisioning: the API's
     create verb makes its directory.
  3. Create the catalogs with their share groups (`huron create catalog --share-group
     <group>`).
  4. For each `SHARE_GROUP_PENDING` warning, run `huron adm provision-catalogs --emit-script >
     catalogs.sh` and run it as root ("Catalog share group and directory modes"). It runs the
     one `find ... -type d` line per selected catalog.
  5. Make the export read-only for every client except those of the API pod and the upload pod.
  6. Mount the share read-only (`ro`) on the workstations.
  7. Run `huron adm check` ("`huron adm check`" says who can run a complete check). It must
     report no `mode_drift`, no `share_group_mismatch`, no `symbolic_link` and no `unreadable`.

  Nothing else is needed: no ACLs, no recursive owner change and no file mode repair. When step 2
  is not complete, a directory verb answers 503 `LAKE_UNAVAILABLE` (no marker) or 500
  `STORAGE_FAILED` (permission denied), and `huron adm repair <identifier> --recursive` makes the
  missing directories after step 2.
- **Latest placement wins (refined 2026-11-06, after review).** A receipt proves an add only when it
  is the latest placement of that `rel_path_key` in the collection: no other upload of the key,
  `placed` or `committed`, by anyone, has a later `placed_at` (ties broken by id). A later
  placement linked new bytes over the destination, so an older receipt no longer describes the file
  on disk. Receipts lock the collection row before the upload row, as commits and collection
  deletes do, so the three serialize. A receipt for a row that is already `placed` with the same
  `(size, sha256)` succeeds and keeps the first inode (M11.1's behaviour). Accepted residual risk:
  between the API's link and its receipt the bytes on disk already changed, and a commit of the
  same path by another user in that window records the earlier hash; `huron adm check --hash`
  detects it (section 12, M11.12).
- **Lock order (decided 2026-11-06, after the M11.1 escalation).** Every operation that touches
  more than one row takes its locks in one order: the catalog advisory lock (`tx.lock_catalog`)
  when it takes one, then the collection row, then upload rows, then removal rows. A transaction
  writes its removal rows last.
  - `begin` locks the collection row (`find_collection(..., lock=True)`) before it inserts the
    upload row. A collection delete at the same time either sees the new row, or makes `begin` fail
    with the collection's not-found error, never with a foreign-key violation.
  - `receipt` locks the collection row, then the upload row.
  - A commit locks the collection row, marks upload rows `committed`, then inserts its removal
    rows and deletes the removal rows of re-added keys.
  - A collection delete locks the collection row, reads its placed uploads and inserts its
    removal rows. Activation and a metadata update lock the collection row only.
  - Namespace create and delete, catalog delete, schema assignment and the share-group change
    take the catalog lock first. `Catalogs.set_share_group` and `assign_schema` read the catalog
    again after the lock. `CatalogStore.update` raises the catalog's not-found error when no row
    matches. Organization create and delete, catalog create and grant changes change their own
    rows only.
  - `fail` and `terminate` lock the upload row only.
  - `claim_removals` locks removal rows only, with `for update skip locked`. `finish_removal` is a
    plain delete. `placement`, `get` and `removal_still_valid` lock nothing.
  - Repair locks no row. It reads rows, and reads them again before each step ("Repair").
  - A lost race surfaces as the domain's not-found or state-conflict error, never as a database
    error. Race tests on PostgreSQL cover each pair: begin against delete, receipt against delete,
    a commit's cancellation of a removal against its claim and its finish, and the share-group
    change against schema assignment and against catalog delete.
  - Disk work (hashing, linking, unlinking, directory and mode changes) runs outside every
    transaction. The hash of a placement runs outside every lock. The link, the unlinks and the
    directory changes run under the API's in-process lock per path. The directory verbs run their
    disk work after the commit, in the same request. Operations on one collection queue behind
    each other for the length of a transaction, which holds no disk work. The link-to-receipt
    window stays an accepted risk (no `placing` state), as "Latest placement wins" records. Two
    API replicas may place the same path at the same time, because the in-process lock does not
    extend across replicas. The inode guard covers a removal against a placement, except the
    narrow window between its `stat` and its `unlink`, and `huron adm check --hash` detects the
    rest. There is no lock across replicas.
- **Reading an upload.** `GET /api/v1/uploads/{id}` (bearer token, creator only, else 404
  `UPLOAD_NOT_FOUND`) returns `{id, collection_id, rel_path, size, state, sha256, failure}`. The
  CLI uses it to explain a 500, 502 or 504 from the final PATCH ("The CLI"). The `auth` route
  uses `Uploads.get` the same way to decide that the caller created the upload.
- **Settings.** API (`HURON_*` or the configuration file). Durations accept seconds or ISO 8601.
  - `lake_path` (default unset): the lake's mount point. Uploads and the disk work of the
    directory verbs exist only when it is set. `uploads_url` without `lake_path` fails startup.
    A declared organization root that is not `lake_path` or below it fails startup ("the root R
    of organization O is not below lake_path L"). The API has no `mount_prefix` setting: an
    organization without a root lies directly below `lake_path`. The CLI keeps its own
    `mount_prefix` key for the workstation's read-only mount.
  - `uploads_url` (default unset): the public tus endpoint, such as
    `https://huron.apps.example.org/files/`. `GET /healthz` reports it as `uploads_url`, `null`
    when uploads are off.
  - There is no `upload_receipts` setting. With `lake_path` every add needs a receipt; without
    it no receipt is issued ("Upload flow", step 4). `upload_ttl` (default 24 hours),
    `upload_max_size` (bytes, `0` = unlimited).
  - `upload_hook_timeout` (default 15 minutes, at most 55 minutes): how long tusd waits for a
    hook, retries included. The deployment passes it to tusd's `-hooks-http-timeout`.
    `GET /healthz` reports it as `upload_hook_timeout`, in seconds.
  - `removal_interval` (default 60 s) and `sweep_interval` (default 10 minutes).
  - `service_uid` (default: the UID the API runs as) and `service_group` (default unset).
    `GET /healthz` reports `service_user: {"uid": U, "gid": <gid>, "group": "<service_group>"}`,
    or `null` without `service_group`. The gid is the primary group of the API process
    (`os.getgid()`, the pod's `runAsGroup`); it is not a setting. The CLI reads `service_user`
    for `provision-orgs`, `provision-catalogs` and the owner part of `mode_drift`.
  - `GET /healthz` keeps `instance_id`, `version` and `organizations_managed`. `GET /readyz`
    adds the check `lake` ("Lake path"). The lake probe runs in a thread with a bound of 2 s,
    and its result is cached for 10 s. A probe that does not return in time reports
    `lake: false`.
- **Persistence.** Migration `0003_uploads` is unreleased, so M11.2 edits it in place. It
  creates `uploads` and `removals`, adds `inode bigint null` to `uploads`, `removals` and
  `files`, and adds `share_group text null` to `catalogs`. The downgrade drops the two columns
  and the two tables. There is no second migration and no `disk_tasks` table.

  `uploads` `(id uuid pk, collection_id fk on delete cascade, rel_path, rel_path_key, size,
  state, sha256 null, failure jsonb null, created_by, created_at, placed_at null, commit_id null
  fk, inode bigint null)` with `ck_uploads_state` over `pending`, `placed`, `failed`,
  `terminated`, `committed`, the checks of M11.1's Execution notes, `ck_uploads_inode`
  (`(state in ('placed', 'committed')) = (inode is not null)`), and the indexes
  `(collection_id, rel_path_key)` and `(commit_id)`.

  `removals` `(id uuid pk, collection_id null fk on delete set null, path, rel_path,
  rel_path_key, sha256, commit_id null fk on delete set null, created_at, claimed_at null,
  inode bigint null)` with the indexes `(collection_id, rel_path_key)` and `(commit_id)`.

  `files.inode` is the inode of the receipt that proved the record, `null` without one.
  `st_ino` is an unsigned 64-bit number. The PostgreSQL stores convert it to a two's-complement
  `bigint` on write (`ino - 2**64` when `ino >= 2**63`) and back on read. The domain and the
  memory store hold the unsigned value. A contract test uses an inode above `2**63`.
  `catalogs.share_group` is `null` until set. A share group name matches
  `^[A-Za-z_][A-Za-z0-9_.-]{0,31}$`; `Catalogs.create` and `Catalogs.set_share_group` refuse
  another name with 422 `REQUEST_INVALID`. Rows are not audited beyond the existing audit
  entries of commits, deletes and the new `catalog.set_share_group`.
- **The CLI (D-23 amended).** The CLI writes nothing to the share. `huron adm provision-orgs` and
  `huron adm provision-catalogs` in direct mode are the exceptions, and their help says so.
  For these two commands, the CLI's `mount_prefix` is the lake path on the machine that runs
  the command (section 6.1).
  - `huron push` learns `uploads_url` from `GET /healthz`, refuses with a hint when it is
    `null`, keeps the dry-run preflight, and uploads each add with a tus client over `httpx` in
    `src/huron/applications/cli/uploads.py` (creation, `HEAD` to resume, `PATCH` in 64 MiB
    chunks, no new dependency). It hashes locally while it sends and compares `Huron-Sha256`.
    For `Upload-Length: 0`, tusd finishes the upload in the creation POST, so the `pre-finish`
    result and `Huron-Sha256` come with the POST response.
  - On a 500, 502 or 504 from the final PATCH, push reads `GET /api/v1/uploads/{id}`. `placed` or
    `committed` with the local hash is a success. `pending`: push asks again every 5 s, for at
    most `upload_hook_timeout` (from `GET /healthz`). Then it reports the upload as not placed,
    and the next push starts a new upload. `failed` prints the failure.
  - A 401 from the proxy is explained as `run huron login`, a 403 as `this upload belongs to
    another user, or it no longer exists`. `StagedAdd` keeps `upload_url` and `upload_id`, so a
    later push resumes or skips a placed upload. Push needs no mount and unlinks nothing.
  - Directory verbs call the API only: `huron create org|catalog|namespace|collection`,
    `huron activate collection`, `huron publish meta`, `huron set override`,
    `huron unset override`, `huron set namespace`, `huron delete org|catalog|namespace|
    collection`. They make no marker check and no `Mount` call before or after the change. A
    500 `STORAGE_FAILED` or 503 `LAKE_UNAVAILABLE` from a create, activate or publish verb gets
    the hint `To make the directory again, run huron adm repair <identifier>`.
  - `huron create catalog --share-group <group>` and `huron set catalog <catalog>
    --share-group <group> | --no-share-group`. A `SHARE_GROUP_PENDING` warning in the response
    prints the `provision-catalogs` hint.
  - `huron adm repair <identifier> [--recursive]` calls the catalog's repair route.
    `huron adm repair --org <org>` calls the organization's. It prints each changed path, each
    warning, and each failed path with its reason.
  - `huron adm provision-catalogs [--catalog C] [--dry-run] [--emit-script [--uid U] [--gid
    GID]]` ("Catalog share group and directory modes").
  - `huron adm provision-orgs [--emit-script [--uid U] [--gid GID]]` sets up the directory that
    `lake_path` names (owner `U:<gid>`, mode `2751`), its `.tus-uploads` (owner `U:<gid>`, mode
    `0700`) and the marker at `lake_path`. For each declared organization it requires the root to
    exist (the storage administrator makes it, section 6.1), creates `<root>/<org>` when missing,
    makes `U:<gid>` the owner of `<root>/<org>` only (no `chown -R`), sets the mode `2751`, and
    writes the marker, in direct mode and in the `--emit-script` output ("Install order"). Direct mode
    runs `Provisioner.provision`. It reads `U` and `<gid>` from `service_user` of
    `GET /healthz`, and refuses without it unless `--uid` and `--gid` are given. Direct mode
    works only for a user that may `chown` (root, or `U` itself in development).
  - `huron delete collection` keeps the commit of its removes before the delete. It makes no
    check of unrecorded files and unlinks nothing ("Removals and the inode guard").
  - `huron adm grant` and `huron adm revoke` print no ACL reminder. Grants no longer reach the
    disk.
  - Gone: `PosixStorage.copy_in` and the `.huron-part` push path, `write_sidecar` in `sync.py`,
    `Mount.ensure`, `Mount.apply`, `Mount.remove` and `Mount.report`, `PosixStorage.owned_by_me`,
    `kind_of` and `DirectoryKind.NAMESPACE_WITH_COLLECTIONS`, `huron adm apply-acl`, the CLI
    configuration key `acl_backend`, the `_remind` text of `huron adm grant` and
    `huron adm revoke`, the unrecorded-file check `_refuse_unrecorded` and the walks of
    `huron delete collection` (`commands/delete.py`), and `scripts/init-root.sh`. The
    `os.walk` in `sync._collect` stays: it reads the user's local source folder, not the lake.
  - `Mount.storage` is typed as the read-only port `ShareReader`. The CLI never calls a write
    method, except `huron adm provision-orgs` and `huron adm provision-catalogs` in direct mode,
    which build a writable `PosixStorage` themselves.
- **`huron adm check`.** Section 6.4 has the table.
  - New findings:
    - `mode_drift` (warning): a directory or file whose permission bits differ from the table of
      "Catalog share group and directory modes", a directory below a catalog without the setgid
      bit or with a group other than the catalog directory's, or an entry whose owner is not the
      `uid` of `service_user` when `/healthz` reports it. Its hint: `huron adm repair` fixes
      permission bits; a missing setgid bit or a wrong directory group needs the storage
      administrator (`huron adm provision-catalogs`).
    - `share_group_mismatch` (warning): a catalog directory whose group is not the catalog's
      `share_group` (or `G`, by its gid, for a catalog without one), or whose `share_group` the
      machine cannot resolve.
    - `unreadable` (warning, the path and the `errno`): an entry that the reader cannot list or
      `stat` (`walk` yields it with `kind="unreadable"` and does not enter it). It replaces the
      `PermissionError` that stops the check today. `huron status` uses the same rule for its
      unrecorded files.
    - `symbolic_link` (error, the path): a symbolic link anywhere in the organization tree.
      `walk` yields it and never enters it ("Containment in the lake"). The storage
      administrator removes it.
  - Neither `mode_drift` nor `share_group_mismatch` compares the group of a file. A placed file
    keeps the group `G` of `.tus-uploads`, and reads depend only on the mode `0644` and the
    `2750` ancestors.
  - A complete check needs an account in `G` and in every share group, or `U`: from an API pod,
    `oc exec deploy/huron -- huron adm check`. Any other account gets `unreadable` findings for
    the entries it cannot reach.
  - Gone: `acl_drift`, `org_acl_drift`, `disk_task_failed`, `disk_task_stale`,
    `disk_task_pending`.
  - `stale_part` reports only `.huron-part` and `.huron-prev` files older than one hour, inside
    collections.
    Readers cannot read `.tus-uploads` (mode `0700`), and the sweep cleans it.
  - `file_unrecorded` covers placed, uncommitted files, and a file that a crash left between the
    link and the receipt of a placement.
- **Error codes** (registered where raised, listed in `docs/api-errors.md`):
  - In `core/lake/uploads/errors.py`: `UPLOAD_NOT_FOUND` 404, `UPLOAD_STATE_CONFLICT` 409,
    `UPLOAD_SIZE_MISMATCH` 422, `UPLOAD_TOO_LARGE` 413, `UPLOAD_RECEIPT_MISSING` 422 (all M11.1).
  - In `applications/api/dependencies.py`: `UPLOADS_DISABLED` 404 (an upload route without
    `lake_path`).
  - In `core/storage/errors.py`: `SYMLINK_IN_LAKE` 409 (a symbolic link at any step of a lake
    path; `context.path` is the lake path of the link; the message is "<path> is a symbolic
    link. The lake must not contain symbolic links. Remove it") and `LAKE_UNAVAILABLE` 503 (the
    lake is not mounted, its root does not open, it is not writable, or its marker refuses the
    write). `SYMLINK_IN_LAKE` is never re-wrapped as `LAKE_UNAVAILABLE`. The existing
    `STORAGE_FAILED` 500 covers the other errors of the API's disk work, with `context.path`.
    Messages name lake paths in the API form, not absolute server paths.
  - A name that fails `check_lake_name` is the existing 422 `NAME_INVALID` (rule `lake_name`).
  - `OUTSIDE_LAKE` does not exist.
  - An invalid share group name is the existing 422 `REQUEST_INVALID`.
  - `SHARE_GROUP_PENDING` is not an error. It is the `code` of a warning in the create and set
    catalog responses and in the repair response.
  - `ACL_FAILED` is removed with `pkg/fs/acl.py`. `DIRECTORY_NOT_READY`, `DISK_TASK_*`,
    `INGEST_*`, `PARENT_DIRECTORY_MISSING` and `DIRECTORY_NOT_EMPTY` do not exist.
- **Package tree and contracts (section 4).**
  - Lake: `core/lake/uploads/` (M11.1, with `Upload.inode`, `Removal.inode`,
    `Destination(directory, rel_path)`, `claim_removals -> list[Removal]` and
    `Uploads.receipt(id, size, sha256, inode)`),
    `core/lake/catalogs/` (`Catalog.share_group`, `Catalogs.set_share_group`),
    `core/lake/collections/` (`DeletedCollection(disk_path, removals)`), `core/lake/files/`
    (`FileRecord.inode`, `CommitResult.removals`), `core/lake/repairs/` (`Repairs.plan`,
    `Repairs.organization`, `Repairs.expected`, `RepairPlan` of `PlannedDirectory(path, level,
    id)`). `SchemaAssignment.settled` is a tuple of `SettledCollection(id, disk_path)`.
    `core.lake` produces API paths and rows; it never sees a `LakePath`.
  - Storage ("The disk-access module" has the port and the rule modules):
    `core/storage/lakepath.py` (`LakePath`), `core/storage/layout.py` (`OrganizationPlace`,
    `mode_of(location)`, the modes `ORGANIZATION_MODE` `0o2751`, `DIRECTORY_MODE` `0o2750`,
    `FILE_MODE` `0o644`, `UPLOAD_DIR_MODE` `0o700`, `UPLOADS`; no `DirectoryKind`, no `resolve`,
    no `place_of`), `core/storage/ports.py` (`ShareReader`, `Storage`, `Stat`, `Entry`,
    `Outcome`, `GroupResult(outcome: GroupOutcome, reason: str | None)` with `GroupOutcome`
    `CHANGED | UNCHANGED | PENDING`, and `ShareWarning(code, group, detail)`; no `device`),
    `core/storage/errors.py` (`SymlinkInLake`; no `OutsideLake`), `core/storage/marker.py`,
    `core/storage/placement.py` (`Placer`), `core/storage/removal.py` (`prune`, `Unlinker`,
    `Sweeper`), `core/storage/directories.py` (`DirectoryWriter`), `core/storage/repair.py`
    (`Repairer`, `RepairStep`, `FailureReason`, `RepairResult`), `core/storage/locks.py`
    (`PathLocks`, the in-process `asyncio` lock per `LakePath`), `core/storage/check.py`
    (findings), `core/storage/provision.py` (`Provisioner.provision` and the organization and
    catalog scripts). `core/storage/memory.py` (`MemoryStorage`) models symbolic links, not
    mounts. `pkg/fs/posix.py` holds the descriptor primitives (`open_beneath`, `entry`,
    `make_dir`, `make_inheriting_dir`, `atomic_write`, `link_into_place`, `remove_file`,
    `remove_empty_dir`, `walk`); its path functions go. Gone: `core/storage/aclplan.py`,
    `pkg/fs/acl.py`, `EffectiveGroups` in storage, `acl_backend`, `tests/acl`.
  - API: the package `applications/api/disk/` ("The disk-access module": `lake.py` with
    `LakeDisk` and `Located`, `placements.py`, `directories.py`, `repair.py`, `removals.py`),
    which replaces `applications/api/disk.py` and `routes/directories.py`,
    `applications/api/background.py` (the removal runner and the sweep, with the
    election), `applications/api/routes/v1/endpoints/uploads.py` and `schema/uploads.py`
    (`hooks`, `auth`, `GET /uploads/{id}`), `applications/api/routes/v1/endpoints/repairs.py`
    and `schema/repairs.py` (`RepairFailureOut` with `reason: FailureReason` and `detail`).
    `schema/catalogs.py` gains `CatalogWriteOut` (the `CatalogOut`
    fields and `warnings: list[ShareWarningOut]`), which the create catalog route and
    `PATCH /catalogs/{catalog}` answer. `GET` keeps `CatalogOut`, with `share_group`. The PATCH
    takes no `If-Match`, like the namespace PATCH: the catalog lock serializes it.
  - CLI: `applications/cli/uploads.py` (the tus client).
  - Deployment: `deploy/openshift/uploads.yaml`, `deploy/openshift/nginx-uploads.conf.template`
    and its copy `deploy/helm/huron/files/nginx-uploads.conf.template` (M11.13),
    `deploy/helm/huron/templates/uploads.yaml` (M11.13), `deploy/local/` (M11.11),
    `docker-compose.uploads.yml`.
  - There is no `applications/ingest` and no contract 9. M11.3, the task that first makes the
    API import `core.storage`, changes the contracts in `pyproject.toml` and the dependency
    rules in AGENTS.md. Contract 6 becomes "the API does not import the CLI": the API now
    imports `core.storage`, because it holds the mount. The contract "lake areas never import
    another area's operations" adds `huron.core.lake.uploads.models` to its sources and
    `huron.core.lake.uploads.operations` to its forbidden modules.
  - Two contracts are added (decided 2026-11-08). M11.5c adds "`core.storage` does not import
    `applications` or `core.metastore`", so the rule modules stay testable without the API;
    `placement.py`'s import of `core.lake.uploads.errors` stays allowed. M11.9a adds "only
    `core.storage` imports `huron.pkg.fs`" (sources `huron.applications`, `huron.core.lake`,
    `huron.core.security`, `huron.core.metastore` and `huron.schema`). The verifications of
    M11.5c and M11.5d add grep rules that import-linter cannot express: no `os` disk call,
    `shutil` or `Path(` in `applications/api/disk` and `applications/api/routes`, and
    `symlink` in `src/huron` only as `SymlinkInLake`, `MemoryStorage.symlink`, the `kind`
    literal and the `ELOOP` classification of `pkg/fs/posix.py`.
- **Deployment.** Every target runs the API with the lake, and nginx and tusd on the same
  ports.
  - `make app`: the `api` service bind-mounts `HURON_LAKE_SOURCE` (default `/data1/huron`) at
    `/data1/huron` read-write and runs as the host user (`HURON_UID`, `HURON_GID` from `id -u`
    and `id -g`). The services `uploads-proxy` (nginx, port 1080) and `uploads` (tusd,
    127.0.0.1:1081) join the shared network namespace `net`, which publishes 127.0.0.1:1080, and
    run as the host user with the same bind mount. Compose keeps the image entrypoint, so
    `uploads-proxy` sets the nginx start line with `command:`. Before tusd starts, a one-shot
    service `uploads-init` (the tusd image, `sh -c`) deletes `*.lock`, `*.lock.*` and `*.stop` in
    `.tus-uploads`. A one-shot service
    `lake-init` provisions the declared organizations of `huron.dev.yaml` with
    `scripts/dev-provision.py` before the API starts. The script calls `Provisioner.provision`
    and writes no layout of its own. The seed of `make app` runs against this API; seeds that
    need files on the lake upload them through tusd.
  - `make api`: the API on the host reads `lake_path: /data1/huron` from `huron.dev.yaml`.
    `make uploads` runs nginx and tusd from `docker-compose.uploads.yml` with host networking
    on the same ports, with the same lock cleanup, and `make uploads-down` stops them.
  - The kustomize base: `deployment.yaml` gains the `huron-lake` volume at `HURON_LAKE_PATH`,
    `runAsUser: U`, `runAsGroup: G` and `supplementalGroups: [G]`. The API Route `huron`
    (`route.yaml`) gets `haproxy.router.openshift.io/timeout: 300s`, for schema assignment,
    recursive repair and collection delete. `deploy/openshift/uploads.yaml` holds the Deployment
    `huron-uploads`, the Service `huron-uploads`, the Route `huron-uploads` with path `/files`
    and `haproxy.router.openshift.io/timeout: 3600s`, and the claim `huron-lake`, which the
    cluster administrator binds to the export's PersistentVolume (ReadWriteMany). The ConfigMap
    `huron-uploads-nginx` comes from a `configMapGenerator` over `nginx-uploads.conf.template`.
    There is no NetworkPolicy: a NetworkPolicy cannot select an HTTP path, and the hooks route
    is safe without one ("Upload flow").
  - The Deployment `huron-uploads`:
    - Strategy `Recreate` and one replica, because tusd's lock tests whether the PID in a lock
      file is alive, and that test is local to one PID namespace.
    - An init container (the tusd image, `sh -c`) deletes `*.lock`, `*.lock.*` and `*.stop` in
      `.tus-uploads` before tusd starts. tusd is PID 1 in its container, so after an unclean
      stop the new tusd finds its own PID in an old lock file, and every HEAD or PATCH of that
      upload ends in a lock timeout. The cleanup is safe with one replica.
    - The `proxy` container sets `args: ["nginx", "-c", "/tmp/nginx-uploads.conf", "-g",
      "daemon off;"]` and never `command:`, because `command:` replaces the image entrypoint and
      the `envsubst` step does not run. Its environment sets `NGINX_ENVSUBST_OUTPUT_DIR=/tmp`
      and `NGINX_ENVSUBST_FILTER=^HURON_API_UPSTREAM$`.
    - `nodeSelector`, `tolerations` and `affinity` place the pod on the clients that the export
      makes writable (a dedicated node pool, for example).
  - The local cluster (M11.11, decided 2026-11-07): the kustomize overlay `deploy/local/` on the
    base, for the kind cluster `ocp-test` on the development machine (ingress-nginx at
    `https://127.0.0.1:18443`, the `local-path` storage class, the Route CRD without a router).
    The overlay replaces the Routes with Ingresses, binds `huron-lake` to a `hostPath`
    PersistentVolume, and provisions the organizations with a one-shot Job that runs
    `Provisioner.provision` (the work of `scripts/dev-provision.py`). The lake there is a local
    Linux filesystem, so M11.11 does not wait for the setgid measurement.
  - The Helm chart (M11.13, after the setgid measurement in "Facts about the storage"; until
    then `deploy/README.md` and the operator guide list it as work still to do):
    `lake.claim`, `lake.path`, `serviceUser.uid`, `serviceUser.gid`,
    `serviceUser.group`, `uploads.enabled` (default `false`), the nginx and tusd images,
    `uploads.url`, `uploads.maxSize`, `uploads.hookTimeout` (at most 55m), `uploads.nodeSelector`,
    `uploads.tolerations`, `uploads.affinity`, Route and Ingress. `route.timeout` defaults to
    `300s`. `HURON_API_UPSTREAM` and tusd's `-hooks-http` use
    `{{ include "huron.fullname" . }}:{{ .Values.service.port }}`. `uploads.ingress.annotations`
    defaults to the ingress-nginx values `proxy-body-size: "0"`, `proxy-request-buffering:
    "off"`, `proxy-read-timeout: "3600"` and `proxy-send-timeout: "3600"`. `NOTES.txt` warns
    when uploads are off.
  - tusd locks an upload with hard links in `.tus-uploads` (`github.com/tus/lockfile`: a
    temporary file with the PID, then `link` to `<id>.lock`). It takes no `flock` and needs no
    NLM. The export supports hard links (measured). The mount options belong to the
    PersistentVolume, which both pods share.
  - `huron.dev.yaml` sets `lake_path: /data1/huron` and
    `uploads_url: http://127.0.0.1:1080/files/`. It has no `upload_receipts` and no
    `mount_prefix`.

## 4. Architecture

### 4.1 Components

| Component | Runs | Responsibility |
| --- | --- | --- |
| `huron-api` | OpenShift pod, mounts the lake read-write as `U:G` | Authentication broker, authorization, catalog of organizations, catalogs, namespaces, collections, files and uploads. Schema registry, audit log, search. tusd's hooks and nginx's authorization. Places uploads with hard links, creates, repairs and removes directories, writes `metadata.json`, unlinks removed files, sweeps `.tus-uploads`. Opens every lake path from the root with no follow of a symbolic link. The only process that writes the share, apart from tusd's filestore. |
| `huron-uploads` | OpenShift pod, one replica, `Recreate`, mounts the lake read-write as `U:G` | Init container: deletes tusd's old lock files in `.tus-uploads`. `proxy` (nginx): sends OPTIONS straight to tusd, asks the API before every other request, then streams it to tusd. `tusd`: the tus endpoint, on 127.0.0.1, writing only `.tus-uploads`. |
| PostgreSQL | OpenShift (or managed) | Schema `huron`: all tables in section 7, `uploads` and `removals` included. |
| `huron` CLI | Any machine. Machines with the read-only mount for disk checks | Login, browsing, administration verbs, the metadata walkthrough, staging and push over HTTPS, directory verbs through the API, drift checks over the read-only mount. Writes nothing to the share, apart from `huron adm provision-orgs` and `huron adm provision-catalogs` in direct mode, run by the storage administrator. |
| Institutional OIDC provider | External | Issues the company token the CLI exchanges. |
| Group directory | External | `GET …/users/{username}/groups` → `{"groups": [...]}`. Mocked in development. |
| NFS share | External | One NFSv3 export (`sec=sys`) without ACL support, mounted at the lake path. The mount point never changes. Every organization root is the lake path or lies below it, on one filesystem. An organization's directory is `<root>/<org>`; an unrooted organization lies directly below the lake path. `huron adm provision-orgs` prepares the lake path, `.tus-uploads`, the declared organizations and their markers. The lake contains no symbolic links; Huron places files with hard links only. Read-write only for the clients of the API pod and the upload pod, read-only everywhere else. |

### 4.2 Package tree

Binding. Files listed here are created by the milestone in parentheses; a task may add sibling modules
inside a package but not new top-level packages.

```text
src/huron/
  __init__.py
  pkg/                      Generic code with no Huron knowledge. Importable by everything. (M1)
    errors.py               HuronError base, ErrorCode registry, problem document rendering
    paging.py               Cursor encoding, Page[T], page-size bounds
    canonical.py            RFC 8785 canonical JSON bytes (integers of any size exact), stable hashing
    identifiers.py          UUIDv7 generation, parsing
    clock.py                Clock protocol, SystemClock, FrozenClock
    hashing.py              Streaming sha256 over a file or a byte iterator
    fs/
      posix.py              Descriptor primitives below one root, no follow of a symbolic link:
                            open_beneath, entry, make_dir, make_inheriting_dir, atomic_write,
                            link_into_place, remove_file, remove_empty_dir, walk (M11.5c)
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
      bootstrap.py          Lake composition; seeds: huron-base schema, platform grant, first signing key;
                            reconciles declared organizations under the bootstrap lock (amendment 2026-10-31)
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
    storage/                Share layout, modes and groups. Imports pkg, core.lake models. Used by the
                            CLI (read-only, except the provision commands in direct mode) and
                            the API's LakeDisk. (M7, M11)
      lakepath.py           LakePath: a tuple of names that passed check_lake_name (M11.5c)
      ports.py              ShareReader and Storage protocols on LakePath, Stat, Entry, Outcome
      errors.py             StorageError, SourceGone, SymlinkInLake, LakeUnavailable
      layout.py             OrganizationPlace, locate, mode_of(location), the modes, UPLOADS
      posix.py              PosixStorage(root) over pkg.fs.posix
      memory.py             MemoryStorage(root) fake with the same contract; models symbolic links
      marker.py             Lake-path and per-organization marker file (.huron) read and verify
      locks.py              PathLocks: the in-process lock per LakePath (M11.3)
      placement.py          Placer: measure, hard link with the inode guard, undo, drop the backup
      removal.py            prune (M11.5c), Unlinker and Sweeper (M11.6)
      directories.py        DirectoryWriter: make, set_group, write_metadata, remove (M11.5d)
      repair.py             Repairer, RepairStep, FailureReason, RepairResult (M11.5e)
      check.py              Drift findings: the API's view against the storage's walk (M9, M11.9)
      provision.py          Provisioner.provision and the organization and catalog scripts (M11.9)
  applications/
    api/                    (M5)
      main.py               uvicorn entry: `huron.applications.api.main:app`
      app.py                create_app(settings, store, …): routers, middleware, error handlers
      settings.py           pydantic-settings: HURON_* environment over HURON_CONFIG_FILE (YAML) and
                            the declared organizations
      lifespan.py           Pool, key ring, bootstrap, readiness
      problems.py           problem+json responses from HuronError
      dependencies.py       Store, clock, settings providers
      openapi.py            `python -m huron.applications.api.openapi` writes docs/openapi.json
      runtime.py            Runtime: builds LakeDisk and the disk orchestrations once (M11.3)
      background.py         The removal runner and the sweep of .tus-uploads, elected (M11.6)
      disk/                 The API's disk layer, in place of disk.py and routes/directories.py
                            (M11.5c)
        lake.py             LakeDisk (open, ready, close, locate, hold, work, measure) and Located
        placements.py       Placements: placement with Placer
        directories.py      Directories protocol, LakeDirectories and NoLake (M11.5d)
        repair.py           LakeRepair: repair with Repairer (M11.5e)
        removals.py         Removals: the drain with Unlinker (M11.6)
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
                            collections.py commits.py files.py search.py admin.py uploads.py
                            repairs.py (M11)
          schema/           Request and response bodies, one module per endpoints module
    cli/                    (M6, M7, M8, M9)
      main.py               console entry `huron`
      app.py                Root Typer app, error boundary, exit codes
      errors.py             ExitCode, CliError and the problem-code → exit-code mapping
      services.py           Services: the one composition seam (state, http, clock, storage, prompter)
      config.py             config.yaml: api_url, issuer, client_id, mount_prefix
      state.py              XDG state dir, tokens.json (0600), working copies
      client.py             httpx client: problem+json → CliError, paging, ETags
      login.py              Device grant and loopback PKCE flows, token exchange, refresh
      identifiers.py        Relative identifiers against the current catalog
      mount.py              Read-only ShareReader per organization (its root, else the mount prefix)
                            and the marker check before a read
      sync.py               Stage, pull and push logic shared by the stage verbs
      uploads.py            The tus client of huron push (M11.7)
      output.py             -o table|json|yaml rendering
      prompts.py            Prompter protocol and the questionary implementation
      walkthrough.py        JSON Schema → prompt plan → metadata document
      inventory.py          What the service records about a catalog (check, tree)
      tree.py               The namespace tree with collections as leaves, for `huron tree`
      picker.py             The level-by-level collection picker of `huron checkout`
      commands/             One module per verb group (section 9): session.py context.py get.py
                            describe.py explore.py (tree, search) create.py delete.py change.py
                            stage.py adm.py, with shared helpers in common.py
migrations/
  env.py                    Alembic environment bound to the SQLAlchemy Core tables
  versions/0001_huron.py    The whole version-1 schema (M4)
  versions/0002_organization_catalog_roles.py
                            Catalog roles at organization scope (D-28)
alembic.ini
tests/
  unit/                     Fakes only; the default `make test`
  contract/                 Store contract suite against memory and PostgreSQL (testcontainers)
  integration/              API over PostgreSQL; CLI over a real temp directory and the in-process API
  fakes/                    Company OIDC issuer, group directory, scripted prompter
  support/                  Shared fixtures and builders
deploy/openshift/           Kustomize base: Deployment, Service, Route, ConfigMap, Secret, migration Job (M10);
                            huron.yaml from a configMapGenerator (amendment 2026-10-31)
deploy/local/               Kustomize overlay for the local kind cluster ocp-test (M11.11)
deploy/helm/huron/          Helm chart: the API, its huron.yaml ConfigMap, the migration hook, an optional
                            web (M10.6); the upload pod and the production values (M11.13)
huron.dev.yaml              The development service configuration: the declared organizations (M10.6)
scripts/                    dev-provision.py, check-stack.sh, check_schema_map.py, devgroups.py,
                            dev-groups.yaml, e2e.sh, keycloak/company-realm.json
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
core.storage   ← pkg, schema, core.lake (models and errors only), core.security.rbac (roles)
pkg.fs         ← imported only by core.storage (M11.9a)
applications.api ← everything except applications.cli
applications.cli ← pkg, schema, core.storage, core.security.rbac (role names), core.lake models
```

Contracts:

1. `huron.pkg` is independent of every other `huron` package.
2. `huron.schema` may import only `huron.pkg`.
3. `huron.core.security` must not import `huron.core.lake`, `huron.core.metastore`, `huron.core.storage`
   or `huron.applications`.
4. `huron.core.lake` must not import `huron.core.metastore`, `huron.core.storage` or `huron.applications`.
5. Nothing outside `huron.applications` imports `huron.core.metastore`.
6. `huron.applications.api` must not import `huron.applications.cli`. The API imports
   `huron.core.storage`, because it holds the mount (M11.3).
7. `huron.applications.cli` must not import `huron.applications.api`, `huron.core.metastore` or
   `huron.core.security.broker`.
8. Inside `huron.core.lake`, an area package may import another area's `models`, `errors` and `ports`
   modules but never its `operations`, `lifecycle`, `registry`, `commits` or `completeness` modules;
   cross-area collaboration goes through constructor arguments (section 11 names them).
   M11.3 adds `huron.core.lake.uploads` to its lists. M11.5e adds `huron.core.lake.repairs`.

There is no contract 9 (it was the removed `applications/ingest` contract). The uploads amendment
adds two contracts (section 3, "Package tree and contracts"):

10. `huron.core.storage` must not import `huron.applications` or `huron.core.metastore` (M11.5c).
    The import of `huron.core.lake.uploads.errors` by `placement.py` stays allowed.
11. Only `huron.core.storage` imports `huron.pkg.fs`: `huron.applications`, `huron.core.lake`,
    `huron.core.security`, `huron.core.metastore` and `huron.schema` must not import it (M11.9a).

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
  (Amended 2026-11-08: M11.7 removes `part_name` with the CLI copy. Only the API makes part files,
  named `.<name>.<id>.huron-part`, section 6.3.)

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
  Org Admin grants are scoped to an organization; the three catalog roles to a catalog or (amendment
  2026-10-31) to an organization, where they hold in every catalog of that organization, existing and
  future, through the enclosing-scope rule below. A catalog's grants add groups to the ones it
  inherits and cannot remove one.
- Granting at organization scope (amendment 2026-10-31): `org_admin` needs `ORGANIZATION_GRANT`;
  all three catalog roles, `contributor` and `reader` included, need `CATALOG_GRANT_ADMIN` at the
  organization, which only Org Admin and Platform Admin carry. Requiring `CATALOG_GRANT_MEMBER` there
  would let an organization-scope Catalog Admin, which holds it at the organization, grant
  organization-wide members; deliberately it does not: it edits each catalog's member grants only. A declared organization's four organization-scope
  sets come from the configuration's `groups` and are not editable (section 3, D-28).
- An `Actor` is `(subject, display_name, groups)`. `Authorizer.roles_for(actor)` returns the set of
  `(scope, role)` pairs from grants whose group is in `actor.groups`. `Authorizer.require(actor,
  privilege, scope)` passes when any role the actor holds at that scope or an enclosing scope carries the
  privilege; otherwise it raises `Forbidden` (403 `FORBIDDEN`). An enclosing scope is: platform encloses
  everything; an organization encloses its catalogs.
- Visibility: an actor sees an organization if they hold any role at platform scope, at that
  organization, or at any catalog in it. An actor sees a catalog if they hold any role at platform
  scope, at its organization, or at the catalog. Any role at the organization counts, so an
  organization-scope Reader sees the organization and every one of its catalogs. Hidden objects answer 404 `NOT_FOUND`, so existence
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
  without validating it against the schema (only the 1 MiB canonical size and JSON representability are
  checked, 422 `METADATA_INVALID`); state `draft`, `version` 1; audit `collection.create`.
- `update(actor, id, expected_version, metadata_patch?, schema_override?)`: JSON merge patch (RFC 7396)
  on the metadata; when either field is present the result is validated against
  resolve(catalog assignment, new override). A draft may hold invalid metadata (validation problems are
  returned as warnings); an `active` or `incomplete` collection refuses invalid metadata with 422
  `METADATA_INVALID`. Bumps `version`; audit `collection.update_metadata` and/or
  `collection.set_schema_override`.
- `activate(actor, id, expected_version)`: requires valid metadata; state `active`; `activated_at`;
  audit `collection.activate`. The CLI creates the directory and ACLs before calling activate and writes
  the sidecar after (D-17, D-19). (Amended 2026-11-08: the CLI writes nothing to the lake. After the
  commit, the API creates the directory with mode `0750` and writes `metadata.json` in the same
  request. There are no ACLs. See section 3, "Directory verbs in the API".)
- `recompute(catalog)`: after a schema assignment, re-validates every `active`/`incomplete` collection
  (D-16).
- `delete(actor, id, expected_version)`: `COLLECTION_DELETE_ANY`, or `COLLECTION_DELETE_OWN` when
  `created_by` matches; requires `file_count == 0` (409 `COLLECTION_NOT_EMPTY`); removes the row; audit
  `collection.delete`. The CLI removes recorded files by a commit, then deletes the row, then removes the
  directory. (Amended 2026-11-08: the CLI commits the removes and calls the delete. The API unlinks
  the files and removes the directory. See section 3, "Removals and the inode guard".)

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
- **Dry run** (amendment 2026-10-31, the push preflight). `commit(..., dry_run=True)` runs steps 1–3
  and the file-tree checks in the same locked transaction, then returns the would-be
  `{version, file_count, commit_id: null}` without applying rows, bumping `version`, inserting the
  commit or writing audit, as `DELETE /collections/{id}?dry_run=true` does for collections. A dry-run
  body may leave out an add's `sha256` (the CLI asks before it copies, and a hash is known only once
  the file is copied; amended 2026-11-08: the CLI asks before it uploads through tusd, and the API
  hashes the placed file for the receipt); one that is present must still match the pattern. A real commit still requires
  every hash: the schema refuses a missing one, and `Commits` raises `COMMIT_INVALID` with
  `{rel_path}` should an unhashed add reach the apply step.
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
`core.lake.audit.models.Action`: `organization.create|update|delete|grant|revoke` (`update` since the
2026-10-31 amendment, written by the startup reconciliation),
`catalog.create|delete|grant|revoke|assign_schema`, `namespace.create|delete|configure`,
`schema.publish`, `collection.create|update_metadata|set_schema_override|activate|mark_incomplete|
mark_active|commit|delete`, `signing_key.rotate`. Every write operation writes its entry in the same
transaction as its change. `GET /collections/{id}/log` and `GET /catalogs/{catalog}/log` page the table
newest first.

## 6. Storage layout, modes and groups

### 6.1 Roots and markers

- **Where an organization lives.** An organization's directory is `<root>/<org>`. `root` is the
  organization's configured root (the 2026-10-31 amendment in section 3), reported as `root` by
  `GET /organizations/{org}`. Every root is `lake_path` or lies below it; startup refuses any
  other root. An organization without a root lies directly below `lake_path`. On a workstation,
  the CLI's `mount_prefix` (default `/projects/huron`) is where the read-only mount of
  `lake_path` is. Below it the layout is `<org dir>/<catalog>/<namespace…>/<collection>`. The API
  reports paths relative to the root, starting with the organization's name (`helio/sun/…`); the
  catalog, namespace and collection views carry `share_root`, the owning organization's root or
  `null`. A client's absolute path is `share_root + "/" + path` (a namespace's `disk_path`), or its own
  mount prefix in place of a `null` `share_root`. The CLI's `Mount` resolves every path this way, looking the organization up by
  the first segment and caching the answer for the command; no path derivation (inventory,
  `check`, `tree`, `status`) bypasses it. The CLI only reads through `Mount`. In the API, a place
  on the disk is a `LakePath` of validated names below `lake_path`, never an absolute path
  (section 3, "Containment in the lake").
- **Per-organization marker.** For each declared organization the storage administrator runs
  `huron adm provision-orgs [--org O] [--dry-run] [--emit-script]` as a user who can write the
  root (or, with `--emit-script`, hands the printed script to `root`). The work is
  `Provisioner.provision` (`core/storage/provision.py`). It requires `<root>` to exist (the
  root's own mode and owner belong to the storage administrator; Huron needs only that `others`
  may traverse it). It creates `<root>/<org>` when missing, makes `U:<gid>` the owner of
  `<root>/<org>` only, sets the mode `2751`, and writes `<root>/<org>/.huron` containing
  `{"huron": 1, "api_url": "<url>", "instance_id": "<uuid>", "organization": "<org>"}` (`0644`).
  No step is recursive. It refuses to overwrite a marker that names another instance or another
  organization, and is idempotent. `--dry-run` prints what it would do. `U` and `<gid>` come from
  `service_user` of `GET /healthz`, and `--uid` and `--gid` override them. The script uses the
  numeric IDs.
- **Lake-path marker.** `huron adm provision-orgs` also prepares `lake_path`: `chown U:<gid>
  <lake_path>; chmod 2751 <lake_path>; mkdir -p <lake_path>/.tus-uploads; chown U:<gid>
  <lake_path>/.tus-uploads; chmod 0700 <lake_path>/.tus-uploads`. It writes
  `<lake_path>/.huron` containing `{"huron": 1, "api_url": "<url>", "instance_id": "<uuid>"}`
  (`0644`, no `organization`). This marker guards every organization without its own marker
  (every organization in unmanaged mode). `scripts/init-root.sh` is removed (M11.9a).
- **Where `lake_path` is for the provision commands.** `GET /healthz` does not report
  `lake_path`. On the machine that runs `provision-orgs` or `provision-catalogs`, the CLI's
  `mount_prefix` is the lake path. The storage administrator sets `mount_prefix` to the path
  where that machine mounts `lake_path`. The `<lake_path>` steps, the lake-path marker and the
  directory `<lake_path>/<org>` of an organization without a root use this path. A rooted
  organization uses its `root` from `GET /organizations/{org}`, as on every client.
- **The check.** Every unit of disk work in the API checks the marker of the organization it
  writes into first, in the disk worker and under the path lock (`LakeDisk.hold`): the
  per-organization marker, or the lake-path marker for an organization that is neither declared
  nor rooted. The marker is read on `LakePath`, with no follow of a symbolic link. The marker
  must exist, name the API's own `instance_id`, and for a
  per-organization marker name the organization. A refusal answers 503 `LAKE_UNAVAILABLE` for a
  directory verb. In `pre-finish` the hooks route answers an HTTP 503, so tusd sends the hook
  again within `upload_hook_timeout`. The CLI makes the same check inside `Mount.path` before it
  reads, so `huron adm check` never compares the catalog with another service's share. A reader
  opens `<org>/.huron` (`0644`) without listing the organization directory. The check keeps an
  API pointed at a staging database from writing into production directories, and an export
  mounted at another organization's root from being written as that organization.
- `others` have traverse-only (`--x`) on `lake_path`, on every root and on organization
  directories, so readers can reach a catalog they are granted without listing what else exists.
- **Amendment (2026-10-31).** This subsection replaces "6.1 Root and marker", which had one root at
  the mount prefix, one marker there, and organization directories created by `huron create org`.
- **Amendment (2026-11-08).** The root marker of `scripts/init-root.sh` and its `chown -R` are
  removed. The lake-path marker replaces them. The API's `mount_prefix` is removed; the CLI keeps
  its `mount_prefix` key for the read-only mount. Production starts from scratch, so no
  directory needs a change of owner.

### 6.2 Directory kinds, modes and groups

This subsection replaces "6.2 Directory kinds and ACL plans". There are no ACLs: the export does
not support them. `core.storage.layout.mode_of(location)` gives the mode of a `LakePath` from its
depth below the organization directory; there is no `DirectoryKind`. The group of a directory
comes from the catalog's `share_group` through setgid inheritance. The group of a placed file is
the group of its inode in `.tus-uploads`.

| Kind | Mode | Owner | Group | Others |
| --- | --- | --- | --- | --- |
| organization | `2751` | `U` | `G`, the service group | `--x` |
| catalog | `2750` | `U` | the catalog's `share_group`, else inherited (`G`) | `---` |
| namespace, collection, intermediate directory | `2750` | `U` | inherited from the parent (setgid) | `---` |
| placed file (`FILE_MODE`) | `0644` | `U` | `G` (from `.tus-uploads`) | `r--`, unreachable without the ancestors |
| `metadata.json` (`FILE_MODE`) | `0644` | `U` | inherited from the directory | `r--`, unreachable without the ancestors |
| `.tus-uploads` and its entries | `0700`, files `0600` | `U` | `G` | `---` |

- Reads depend only on the mode `0644` of a file and on the `2750` directories above it. A
  member of the share group traverses the catalog's directories and reads every file in them.
  `mode_drift` and `share_group_mismatch` never compare the group of a file.
- A namespace that allows collections has the mode of every other namespace. The sticky bit and
  the contributor write access are gone, because no user writes the share (root on the nodes of
  the API pod and the upload pod excepted). The API still decides who may create and delete
  collections (D-11).
- Who reads a catalog is its share group, nothing else, against users who are not root on a
  client (AUTH_SYS trusts the client's UIDs). Grants decide what the API allows. The share group
  decides who reads the bytes over the mount. The operator keeps the two aligned by giving each
  catalog's readers one POSIX group and naming it with `--share-group`.
- The owner is the user that creates the entry, `U`. Below a catalog directory the API makes a
  directory with `mkdir` at mode `0o750` on the parent's descriptor
  (`pkg.fs.posix.make_inheriting_dir`), and the server sets its group and its setgid bit from
  the parent. `mkdir(2)` honours only the permission bits. The API then runs `stat` on the new
  directory, with no follow. A missing `S_ISGID` bit, or a group other than the parent's, is
  `InheritanceFailed`: `STORAGE_FAILED` in a verb, and a step in `failed` with the reason
  `mode_drift` in a repair. It is never fixed with a silent `chmod`.
- Every entry is a directory or a regular file. A symbolic link anywhere in the lake is an
  error: a write or read through it answers 409 `SYMLINK_IN_LAKE`, and `huron adm check`
  reports `symbolic_link` (section 3, "Containment in the lake"). Placement makes hard links
  only.
- Below a catalog directory the API never calls `chmod` on a directory whose permission bits are
  already right. `chmod(2)` by a caller that is not in the group of the directory clears
  `S_ISGID` without an error. `pkg.fs.posix.make_dir` (`mkdir` then `chmod`) is not used below a
  catalog. Repair fixes permission bits only, and only while `U` is in the directory's group
  (`Storage.in_group`). A missing setgid bit or a wrong directory group
  needs the storage administrator: `huron adm provision-catalogs` selects the catalog, and its
  script runs `find <catalog> -type d -exec chgrp <group> {} + -exec chmod 2750 {} +` as root.
  Files keep their group `G` and the mode `0644` that placement gave them, so no line changes a
  file. `find` keeps its default `-P` and follows no symbolic link.
- The claim that every directory below a catalog inherits the catalog's group depends on a
  measurement on the real export (not done yet). As `U`, not in group `S`, in a directory
  `2750 root:S`: `mkdir d; touch f; stat -c '%a %U %G' d f` must print `2750 U S` and
  `644 U S`. Also, a member of `S` runs `chgrp S` on a directory, and the setgid bit must stay.
  The operator records the result and the volume security style (UNIX, NTFS or mixed) in section
  3's bullet "Facts about the storage (measured 2026-11-06)" before M11.13 starts. M11.11 runs
  on the local cluster and does not wait for it.
- The API tries `chgrp` on a catalog directory when `share_group` is set or changed. It reports
  `SHARE_GROUP_PENDING` when `U` may not. `huron adm provision-catalogs` is the storage
  administrator's step that sets the group.
- `Storage.set_mode(location, mode)` sets permission bits, is idempotent, and reports whether it
  changed anything. `Storage.set_group(location, group)` returns
  `GroupResult(outcome, reason)`, with `outcome` one of `CHANGED`, `UNCHANGED` and `PENDING`
  (`GroupOutcome`, `core/storage/ports.py`).
- The API never returns modes or groups beyond `share_group`. The CLI computes the expected mode
  and group from this table for `huron adm check`.
- Development: every process runs as the host user, and the share groups of `huron.dev.yaml`'s
  catalogs are unset. Nothing needs `chgrp`.

### 6.3 Push write path

See the amendment's "Upload flow". The CLI copies nothing onto the share. The API places a
finished upload inside `pre-finish`. The hooks route first calls `Uploads.get` (creator only). A
row that is `placed` or `committed` gets its stored `Huron-Upload-Id` and `Huron-Sha256` back, with
no work on disk. A row that is `failed` or `terminated` gets the refusal `UPLOAD_STATE_CONFLICT`
409. For a `pending` row, `Uploads.placement` returns `Destination(directory, rel_path)`, and
`Placements.place` does the disk work with the steps of `Placer` (`core/storage/placement.py`):

1. It locates the collection directory with `LakeDisk.locate` (pure, no disk call) and joins the
   names of `rel_path` to it. The result is a `LakePath` of validated names below `lake_path`.
2. Outside every lock (`LakeDisk.measure`, the hash pool), it opens `.tus-uploads/<id>`
   read-only through the traversal. `fstat` on the descriptor gives the size and the inode. A
   size other than the declared size is the refusal `UPLOAD_SIZE_MISMATCH` 422, and the row
   stays `pending`. It hashes from the descriptor and sets the mode `0644` with `fchmod`.
3. Under the in-process lock on the destination path (`LakeDisk.hold`), it checks the marker
   first. Every step opens the path from the root with no follow. A symbolic link at the
   destination or on the way to it is the definitive refusal 409 `SYMLINK_IN_LAKE`, and the row
   becomes `failed`. It requires the collection directory.
   `Placer` never makes it: a missing collection directory is a definitive refusal with
   `STORAGE_FAILED` in the body, the row becomes `failed` through `Uploads.fail`, and the hint is
   `huron adm repair`. It makes the missing intermediate directories below it (section 6.2
   rules) and links into place with a hard link (`Storage.link(..., inode=)` over
   `pkg.fs.posix.link_into_place`), only when the source is a regular file with the inode of
   step 2: `link`, or on `EEXIST` a link
   to `.<name>.<id>.huron-part`, a link of the old file to the backup `.<name>.<id>.huron-prev`
   and a `rename` over the destination. It unlinks the upload and its `.info` (a missing file is
   not an error). Then it calls `Uploads.receipt(id, size, sha256, inode)` with the inode of step
   2, still under the lock, and unlinks the backup.
4. When the receipt raises `UploadNotFound` or `UploadStateConflict` (the collection was
   deleted, or the creator terminated the upload during the hash), it undoes the placement when
   the destination's inode is the placed inode (the backup is renamed back over the destination,
   or without a backup the destination is unlinked), removes the empty intermediate directories
   it made, and refuses with the domain error's status (404 or 409).
5. When the source is gone at step 2 or at the link (another attempt moved it), it reads the row
   again. A `placed` row is answered as above. A `pending` row whose destination exists with the
   declared size gets the hash and the inode of the destination, then the receipt. Anything else
   is 500 `STORAGE_FAILED` from the route, which tusd sends again.

A zero-length upload finishes in the creation POST, so `pre-finish` runs there and its headers
come with the POST response. tusd waits at most `upload_hook_timeout` for a hook, retries
included, and a timeout is final. The API call continues after a timeout and can still record
the receipt. tusd then answers the final PATCH with 500. On 500, 502 or 504 from the final PATCH,
the CLI reads `GET /api/v1/uploads/{id}`: `placed` or `committed` with the local hash is
success, `pending` is polled every 5 seconds for at most `upload_hook_timeout`, and `failed`
prints the failure.

Removals are removal rows that the committing request drains (`Removals.drain`, each row on
`LakeDisk.hold`) with `Unlinker` under the inode guard: `remove_file(location, inode=)`
answers an `Outcome`. `MISSING`, or `KEPT` for a different inode, finishes the row. A removal
without an inode finishes with no disk call. Any other error (`SYMLINK_IN_LAKE` and `EACCES`
included) leaves the row claimed for the runner, and the commit keeps its answer. After an
unlink, `prune` removes the empty directories from the file's parent up to the collection
directory, not the collection directory itself; that directory belongs to the delete verb.
`huron adm check` reports `.huron-part` and `.huron-prev` files older than one hour as
`stale_part`. No other write path exists: the CLI copies no bytes and makes no part file.

### 6.4 What `huron adm check` reports

For every catalog the caller can read (or the one named), with the mount available, and for the
organizations of those catalogs (the `org_*` findings, since the 2026-10-31 amendment):

| Finding | Severity | Meaning |
| --- | --- | --- |
| `org_dir_missing` | error | The directory `<root>/<org>` of a checked catalog's organization does not exist. `huron adm provision-orgs` creates it (`huron create org` for an organization that is neither declared nor rooted). |
| `org_marker_missing` | error | The organization directory has no `.huron` marker. `huron adm provision-orgs` writes it. |
| `org_marker_mismatch` | error | The organization's marker names another instance or another organization. |
| `org_undeclared` | warning | Managed mode only: the configuration does not declare the organization and the mount prefix is not a share of this service, so its directory cannot be located; its catalogs are not checked. |
| `namespace_dir_missing` | error | A namespace row with no directory. `huron adm repair <namespace>` makes it again. |
| `collection_dir_missing` | error | An active collection with no directory. `huron adm repair <collection>` makes it again. |
| `file_missing` | error | A recorded file absent from disk. |
| `file_changed` | warning | Size differs from the recorded stamp; with `--hash`, sha256 differs. |
| `file_unrecorded` | warning | A file on disk inside a collection that no commit recorded. |
| `dir_unrecorded` | warning | A directory under a namespace that is neither a namespace nor a collection. |
| `sidecar_stale` | warning | `metadata.json` missing or not equal to the service's rendering. |
| `stale_part` | info | A `.huron-part` or `.huron-prev` file inside a collection, older than one hour. |
| `incomplete` | info | A collection in state `incomplete`. |
| `stale_draft` | info | A draft older than 30 days. |
| `mode_drift` | warning | A directory or file whose permission bits are not the ones of section 6.2, a directory below a catalog without the setgid bit or with a group other than the catalog directory's, or an entry whose owner is not `service_uid` (when `/healthz` reports it). `huron adm repair <identifier> --recursive` fixes the permission bits of the directories that the rows plan, one planned step per directory; it lists no directory and changes no file. A missing setgid bit or a wrong directory group needs `huron adm provision-catalogs`. Only the storage administrator can change the owner. The group of a file is never compared. |
| `share_group_mismatch` | warning | A catalog directory whose group is not the catalog's `share_group` (or `G`, by its gid, for a catalog without one), or a `share_group` that this machine cannot resolve. The storage administrator runs `huron adm provision-catalogs`. |
| `unreadable` | warning | An entry that the account running the check cannot list or stat (`walk` yields it with `kind="unreadable"` and does not enter it). The detail gives the path and the errno. Run the check as `U` or as an account in `G` and in every share group. |
| `symbolic_link` | error | A symbolic link anywhere in the organization tree. `walk` yields it and never enters it. The lake must not contain symbolic links; the storage administrator removes it. Huron never removes or follows it. |

Every finding needs the read-only mount. A complete check needs `U` (from an API pod:
`oc exec deploy/huron -- huron adm check`) or an account in `G` and in every share group. Any
entry that the account cannot list or stat gives `unreadable`, never an error that stops the
check. `huron status` uses the same rule. `stale_part` does not look into `.tus-uploads`. The
check reads through a read-only `ShareReader` (`stat` and `walk` on `LakePath`) and writes
nothing. There are no ACL findings: `acl_drift` and `org_acl_drift` are removed (M11.9a).

Exit code 0 with no findings, 1 with findings, 2 on an error running the check.

## 7. Persistence

PostgreSQL 16, schema `huron`. Alembic revision `0001_huron` is the version-1 schema; `0002_organization_catalog_roles`
(D-28) lets the three catalog roles be granted at organization scope. Table definitions are
SQLAlchemy Core objects in `core/metastore/<area>/tables.py`; `migrations/env.py` imports them so
`alembic revision --autogenerate` detects drift, and `scripts/check_schema_map.py` fails the gate when
the live schema after `upgrade head` differs from the Core metadata.

| Table | Columns (type, constraints) |
| --- | --- |
| `organizations` | `id uuid pk`, `name text unique`, `display_name text`, `description text`, `version int`, `created_at timestamptz`, `created_by text` |
| `catalogs` | `id uuid pk`, `organization_id uuid fk`, `name text unique`, `display_name text`, `description text`, `schema_id uuid fk schemas`, `version int`, `created_at`, `created_by`, `share_group text null` (amendment 2026-11-06: an LDAP POSIX group name, `null` until set) |
| `namespaces` | `id uuid pk`, `catalog_id uuid fk`, `parent_id uuid fk namespaces null`, `name text`, `path text` (dotted, denormalized for lookups), `collections_allowed bool`, `version int`, `created_at`, `created_by`; unique `(catalog_id, path)`; check `parent_id is null or parent is in the same catalog` (trigger) |
| `collections` | `id uuid pk`, `catalog_id uuid fk`, `namespace_id uuid fk`, `name text`, `identifier text unique`, `state text check in (draft, active, incomplete)`, `version int`, `metadata jsonb`, `schema_override jsonb null`, `file_count int`, `created_at`, `created_by`, `activated_at null`, `updated_at`; unique `(namespace_id, name)` |
| `files` | `collection_id uuid fk on delete restrict`, `rel_path text`, `rel_path_key text`, `size bigint check >= 0`, `sha256 char(64)`, `recorded_at`, `recorded_by`, `commit_id uuid fk`, `inode bigint null` (amendment 2026-11-06: the inode of the receipt that proved the record, `null` without one); pk `(collection_id, rel_path_key)` |
| `uploads` | (amendment 2026-11-06) `id uuid pk`, `collection_id uuid fk on delete cascade`, `rel_path`, `rel_path_key`, `size`, `state`, `sha256 null`, `failure jsonb null`, `created_by`, `created_at`, `placed_at null`, `commit_id uuid fk null`, `inode bigint null`; check `ck_uploads_state` over `pending`, `placed`, `failed`, `terminated`, `committed`; the checks of M11.1's Execution notes; check `ck_uploads_inode` `(state in ('placed', 'committed')) = (inode is not null)` |
| `removals` | (amendment 2026-11-06) `id uuid pk`, `collection_id uuid fk null on delete set null`, `path`, `rel_path`, `rel_path_key`, `sha256`, `commit_id uuid fk null on delete set null`, `created_at`, `claimed_at null`, `inode bigint null` |
| `commits` | `id uuid pk`, `collection_id uuid fk`, `base_version int`, `new_version int`, `adds int`, `removes int`, `host text`, `actor text`, `created_at` |
| `schemas` | `id uuid pk`, `organization_id uuid fk null`, `name text`, `version int`, `extends_id uuid fk schemas null`, `document jsonb`, `created_at`, `created_by`; unique `(organization_id, name, version)` nulls not distinct |
| `grants` | `id uuid pk`, `scope_type text check in (platform, organization, catalog)`, `scope_id uuid null`, `role text check in (platform_admin, org_admin, catalog_admin, contributor, reader)`, `ldap_group text`, `created_at`, `created_by`; unique `(scope_type, scope_id, role, ldap_group)` nulls not distinct; check `(scope_type = 'platform') = (scope_id is null)`; check role matches scope |
| `audit` | `id bigint generated always as identity pk`, `at timestamptz`, `actor text`, `action text`, `object_type text`, `object_id uuid`, `catalog_id uuid null`, `organization_id uuid null`, `detail jsonb` |
| `signing_keys` | `kid text pk`, `private_pem text`, `public_jwk jsonb`, `created_at`, `retired_at null` |

Indexes: `collections (catalog_id, state)`, `collections using gin (metadata jsonb_path_ops)`,
`namespaces (catalog_id, parent_id)`, `audit (object_id, id desc)`, `audit (catalog_id, id desc)`,
`grants (ldap_group)`, `files (collection_id, rel_path_key)` (the pk), `uploads (collection_id,
rel_path_key)`, `uploads (commit_id)`, `removals (collection_id, rel_path_key)`,
`removals (commit_id)`.

Triggers: `sibling_exclusion` refuses a namespace whose `(catalog_id, parent_id, name)` matches a
collection's `(catalog_id, namespace_id, name)` and the reverse, so the uniqueness in D-1 holds across the
two tables.

Locking: writes to a collection take `SELECT … FOR UPDATE` on its row. Catalog-wide changes (schema
assignment and recompute, namespace creation and deletion) take `pg_advisory_xact_lock(hashtext('catalog:'
|| catalog_id))`. Lock order is always catalog, then collection, then files. Startup's `bootstrap()`
takes `tx.lock_bootstrap()`, a transaction-scoped advisory lock of its own key, before it seeds or
reconciles anything (the 2026-10-31 amendment in section 3), so concurrent replicas run it one after
the other.

Declared organizations add no table and no column: `declared`, `root`, `path`, `export` and
`share_root` in the API's views come from the configuration. The organization-wide role groups do
need one migration, `0002_organization_catalog_roles`: it widens the `grants` check
`ck_grants_role_scope` so `catalog_admin`, `contributor` and `reader` are allowed at `organization`
as well as `catalog` scope (its downgrade deletes those rows and restores the version-1 rule).

Uploads add one migration, `0003_uploads` (amendment 2026-11-06, "Persistence"; unreleased, so
M11.2 edits it in place). It creates `uploads` and `removals`, adds `inode bigint null` to
`uploads`, `removals` and `files`, and adds `share_group text null` to `catalogs`. The downgrade
drops the two columns and the two tables. There is no `disk_tasks` table. `st_ino` is an unsigned
64-bit number: the PostgreSQL stores write it as a two's-complement `bigint` (`ino - 2**64` when
`ino >= 2**63`) and convert it back on read. A share group name matches
`^[A-Za-z_][A-Za-z0-9_.-]{0,31}$`.

Rows hold lake paths in the API form (`helio/sun/…`), never absolute server paths and never a
`LakePath`. `removals.path` is the API path of the removed file. Every name in a stored path
passed `check_segment` or `check_rel_path` when the row was written, so the API can locate it
below `lake_path` without a check of the filesystem (section 3, "Containment in the lake").
Containment adds no table and no column. There is no table for ACLs, disk tasks or repairs:
a repair reads the rows of the planned directories and writes no row of its own.

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

**Accepted amendment (2026-11-01, browse sorting).** Catalog lists, namespace children and namespace
collection lists accept `sort=name|created_by|created_at` and `order=asc|desc`, defaulting to name
ascending. Sorting precedes pagination, with the unique name breaking ties in the same direction.
Non-default cursors record their sort field and direction; changing either rejects that cursor.
Existing name-ascending cursors remain compatible. Visibility and draft filtering still precede
the page limit. The API retains its existing limit range and default; the web's browse tables
request 20 rows.

| Method and path | Minimum privilege | Notes |
| --- | --- | --- |
| `GET /.well-known/openid-configuration`, `GET /jwks.json` | none | Huron issuer discovery. |
| `GET /healthz`, `GET /readyz` | none | `healthz` returns `{status, instance_id, version, organizations_managed}` (the last since the 2026-10-31 amendment: whether the configuration declares the organizations); `readyz` checks the pool and the key ring. |
| `POST /auth/exchange` | none | `{company_token}` → `{huron_token, expires_at, subject, groups, roles}`. 401 `TOKEN_INVALID`, 503 `GROUP_DIRECTORY_UNAVAILABLE`. |
| `GET /auth/whoami` | authenticated | Subject, groups, effective `(scope, role)` list. |
| `GET /organizations` | visibility | Organizations the actor can see. |
| `POST /organizations` | `ORGANIZATION_CREATE` | `{name, display_name, description}`. 409 `NAME_TAKEN`; 409 `ORGANIZATIONS_MANAGED` in managed mode (D-28). |
| `GET /organizations/{org}` | `ORGANIZATION_READ` | Body includes `catalog_count`, and `declared` (bool), `root` (the configured root or `null`), `path` (`root/name`, `null` without a root) and `export` (or `null`); the list rows carry the same four. |
| `POST /organizations/{org}/repair` | `CATALOG_GRANT_ADMIN` on the organization | Amendment 2026-11-06. Repairs the organization directory's mode (`2751`) and, for an unmanaged unrooted organization, makes the missing directory. Answers 200 `{changed, warnings, failed}`; each `failed` item has `path`, `reason` (`mode_drift`, `symbolic_link` or `storage_failed`) and `detail`. 503 `LAKE_UNAVAILABLE` without `lake_path`. |
| `DELETE /organizations/{org}` | `ORGANIZATION_DELETE` | 409 `ORGANIZATION_NOT_EMPTY` while catalogs exist; 409 `ORGANIZATION_DECLARED` for a declared organization. |
| `GET /organizations/{org}/grants` | `ORGANIZATION_READ` | `{org_admin: [...], catalog_admin: [...], contributor: [...], reader: [...]}`: the organization-scope groups of each role. |
| `PUT /organizations/{org}/grants/{role}` | `ORGANIZATION_GRANT` for `org_admin`; `CATALOG_GRANT_ADMIN` at the organization (Org Admin or Platform Admin) for `catalog_admin`, `contributor` and `reader` (section 5.2) | `role` is `org_admin`, `catalog_admin`, `contributor` or `reader`; body `{ldap_groups: [...]}` replaces the organization-scope set, with the same change response as the catalog `PUT`. 409 `ORGANIZATION_DECLARED` for a declared organization, whose four sets are its configured `groups`. |
| `GET /organizations/{org}/schemas` | `ORGANIZATION_READ` | Registry entries of the organization, newest version first. |
| `POST /organizations/{org}/schemas` | `SCHEMA_PUBLISH` | `{name, extends_id, document}` → new version. 422 `SCHEMA_INVALID`, `SCHEMA_INCOMPATIBLE`, `SCHEMA_SCOPE`. |
| `GET /schemas/{id}`, `GET /schemas/{id}/resolved` | visibility of its scope | Platform entries are visible to every authenticated actor. |
| `POST /platform/schemas` | `PLATFORM_SCHEMA_PUBLISH` | New version of a platform-scoped entry. |
| `GET /platform/grants`, `PUT /platform/grants/platform_admin` | `ORGANIZATION_GRANT` | The configured group is always present and cannot be removed. |
| `GET /catalogs` | visibility | `?organization=` filter. Iceberg-shaped: `{items: [{name, organization, share_root, …}]}`. |
| `POST /organizations/{org}/catalogs` | `CATALOG_CREATE` | `{name, display_name, description, schema_id?, share_group?}`; default schema is `huron-base` latest. Answers `CatalogWriteOut` (the `CatalogOut` fields and `warnings`, with `SHARE_GROUP_PENDING` when the `chgrp` fails). 422 `REQUEST_INVALID` for a share group name that does not match `^[A-Za-z_][A-Za-z0-9_.-]{0,31}$` (amendment 2026-11-06). |
| `GET /catalogs/{catalog}` | `CATALOG_READ` | Includes `schema` (id, name, version), counts, `share_root` (section 6.1) and `share_group` (amendment 2026-11-06). |
| `PATCH /catalogs/{catalog}` | `CATALOG_GRANT_ADMIN` | Amendment 2026-11-06. `{share_group}`, `null` clears it. No `If-Match`: the catalog lock serializes it. Version + 1, audit action `catalog.set_share_group`, then the `chgrp` attempt. Answers `CatalogWriteOut`. 422 `REQUEST_INVALID` for an invalid name. |
| `POST /catalogs/{catalog}/repair` | `NAMESPACE_CONFIGURE` | Amendment 2026-11-06 ("Directory verbs in the API"). `{target, recursive}`: the catalog, a namespace or a settled collection. One step per directory that the rows plan, outermost first; nothing lists a directory. Answers 200 `{changed, warnings, failed}`; a missing setgid bit or a wrong directory group is in `failed` with the reason `mode_drift`, a symbolic link at or above a step's directory with the reason `symbolic_link`, any other storage error with `storage_failed`. Only `LAKE_UNAVAILABLE` (503) ends the repair. Idempotent; never deletes. |
| `DELETE /catalogs/{catalog}` | `CATALOG_DELETE` | 409 `CATALOG_NOT_EMPTY` while namespaces exist. |
| `GET /catalogs/{catalog}/grants` | removed (M11.9a) | Its only consumer was the ACL plan code, which is removed with it (amendment 2026-11-08). `GET /catalogs/{catalog}/grants/sources` stays. |
| `GET /catalogs/{catalog}/grants/sources` | `CATALOG_READ` | `{items: [{role, group, scope}]}`, `scope` one of `platform`, `organization`, `catalog`: one row per (role, group, scope), sorted by role then group, so a group held both through the organization and on the catalog has two rows (amendment 2026-10-31). |
| `PUT /catalogs/{catalog}/grants/{role}` | `CATALOG_GRANT_ADMIN` for `catalog_admin`, `CATALOG_GRANT_MEMBER` for `contributor` and `reader` | `{ldap_groups}` replaces the set. Audit `catalog.grant`/`revoke` per change. |
| `PUT /catalogs/{catalog}/schema` | `SCHEMA_ASSIGN` | `{schema_id}`; triggers recompute; answers `{assigned, recompute: {incomplete, active}}`. |
| `GET /catalogs/{catalog}/schema` | `CATALOG_READ` | The resolved document. |
| `GET /catalogs/{catalog}/namespaces?parent=` | `CATALOG_READ` | Children of `parent` (dotted path, empty for the root). |
| `POST /catalogs/{catalog}/namespaces` | `NAMESPACE_CREATE` | `{parent, name, collections_allowed}`. 404 for a missing parent; 409 `NAME_TAKEN`; 422 `NAME_INVALID`. |
| `GET /catalogs/{catalog}/namespaces/{path}` | `CATALOG_READ` | Includes `collections_allowed`, child counts, `path` (the dotted path), `disk_path` (relative to the root) and `share_root`. |
| `PATCH /catalogs/{catalog}/namespaces/{path}` | `NAMESPACE_CONFIGURE` | `{collections_allowed}`; refuses `false` while collections exist (409 `NAMESPACE_NOT_EMPTY`). |
| `DELETE /catalogs/{catalog}/namespaces/{path}` | `NAMESPACE_DELETE` | 409 `NAMESPACE_NOT_EMPTY` while children or collections (including drafts) exist. |
| `GET /catalogs/{catalog}/namespaces/{path}/collections` | `CATALOG_READ` | Drafts are shown only to actors holding `COLLECTION_CREATE`. |
| `POST /catalogs/{catalog}/namespaces/{path}/collections` | `COLLECTION_CREATE` | `{name, metadata?}` → draft. 409 `COLLECTIONS_NOT_ALLOWED`, `NAME_TAKEN`. |
| `GET /catalogs/{catalog}/collections/{identifier}` | `COLLECTION_READ` | Resolve by identifier; answers the same body as `GET /collections/{id}`. |
| `GET /collections/{id}` | `COLLECTION_READ` | Body: identifier, organization, catalog, state, version, metadata, schema_override, schema (the resolved `SchemaRef`), file_count, created_by, timestamps, `path` (relative to the root, `null` for drafts), `share_root` (the owning organization's root or `null`; section 6.1), validation `problems` (for drafts and incomplete). |
| `PATCH /collections/{id}` | `COLLECTION_WRITE_METADATA` | `If-Match`; `{metadata?, schema_override?}` (merge patch; `null` override clears). 422 `METADATA_INVALID`. |
| `POST /collections/{id}/activate` | `COLLECTION_WRITE_METADATA` | `If-Match`. 409 `STATE_CONFLICT` unless draft; 422 `METADATA_INVALID`. |
| `DELETE /collections/{id}` | `COLLECTION_DELETE_OWN` or `COLLECTION_DELETE_ANY` | `If-Match`. 409 `COLLECTION_NOT_EMPTY`. |
| `GET /collections/{id}/schema` | `COLLECTION_READ` | Resolved schema for this collection. |
| `GET /collections/{id}/metadata.json` | `COLLECTION_READ` | The canonical sidecar rendering (section 5.3, D-17). |
| `GET /collections/{id}/files` | `COLLECTION_READ` | Paged by `rel_path_key`. |
| `POST /collections/{id}/commits[?dry_run=true]` | `COLLECTION_WRITE_FILES` | Section 5.4. 409 `BASE_VERSION_CONFLICT` carries `current_version`. With `dry_run=true` (amendment 2026-10-31) every check runs and the answer is the would-be result with `commit_id: null`; nothing is written or audited, no `ETag` is set, and adds may leave out `sha256`. |
| `GET /collections/{id}/commits` | `COLLECTION_READ` | Paged, newest first. |
| `GET /collections/{id}/log`, `GET /catalogs/{catalog}/log` | `AUDIT_READ` | Audit entries, newest first. |
| `GET /catalogs/{catalog}/search?q=&label=k:v&state=` | `CATALOG_READ` | `q` matches `title`/`description`/identifier case-insensitively; `label` repeats and matches `metadata.labels`; results are collection summaries. |
| `GET /admin/signing-keys`, `POST /admin/signing-keys/rotate` | `SIGNING_KEY_ROTATE` | Rotation adds a key and retires the previous after `settings.key_overlap`. |
| `POST /uploads/hooks` | the forwarded bearer token, which the route verifies; `pre-create` authorizes `COLLECTION_WRITE_FILES` on the catalog, `pre-finish` needs the upload's creator | Amendment 2026-11-06 ("Upload flow"). tusd's HTTP hooks. Answers 200 with a tusd v2 hook response; a refusal carries `HTTPResponse` with a problem document (`pre-create` adds `RejectUpload`, `pre-terminate` adds `RejectTermination`). A missing or invalid token is a refusal with the 401 problem, not an HTTP 401. 404 `UPLOADS_DISABLED` without `lake_path`. |
| `GET /uploads/auth` | the rules of "Authorization in front of tusd" | Amendment 2026-11-06. nginx's `auth_request` subrequest, with `X-Original-Method` and `X-Original-URI`. 204 for a `POST` to `/files/` with a bearer token, and for any method on `/files/<id>` by the creator of upload `<id>`; 401 with `WWW-Authenticate: Bearer` without a valid token; 403 otherwise. 404 `UPLOADS_DISABLED` without `lake_path`. |
| `GET /uploads/{id}` | authenticated; the upload's creator only | Amendment 2026-11-06 ("Reading an upload"). `{id, collection_id, rel_path, size, state, sha256, failure}`. 404 `UPLOAD_NOT_FOUND` for another user's upload or no upload. |

Error codes (`huron.pkg.errors.ErrorCode`, HTTP status): `UNAUTHENTICATED` 401, `TOKEN_INVALID` 401,
`FORBIDDEN` 403, `NOT_FOUND` 404, `NAME_INVALID` 422, `NAME_TAKEN` 409, `STATE_CONFLICT` 409,
`VERSION_CONFLICT` 412 (`If-Match`), `BASE_VERSION_CONFLICT` 409 (commit), `PRECONDITION_REQUIRED` 428, `ORGANIZATION_NOT_EMPTY`
409, `ORGANIZATIONS_MANAGED` 409, `ORGANIZATION_DECLARED` 409, `CATALOG_NOT_EMPTY` 409, `NAMESPACE_NOT_EMPTY` 409, `COLLECTION_NOT_EMPTY` 409,
`COLLECTIONS_NOT_ALLOWED` 409, `METADATA_INVALID` 422, `SCHEMA_INVALID` 422, `SCHEMA_INCOMPATIBLE` 422,
`SCHEMA_SCOPE` 422, `COMMIT_INVALID` 422, `FILE_NOT_RECORDED` 422, `COMMIT_TOO_LARGE` 413,
`REQUEST_INVALID` 422 (body or query shape), `INVALID_CURSOR` 400, `GROUP_DIRECTORY_UNAVAILABLE` 503,
`DEPENDENCY_UNAVAILABLE` 503. `tests/unit/test_error_contract.py` asserts that every raised code is
registered exactly once and that `docs/api-errors.md` lists each one.

**Amendment (2026-10-31).** Declared organizations (section 3) add `declared`, `root`, `path` and
`export` to the organization views, `share_root` to the catalog, namespace and collection views,
and the codes `ORGANIZATIONS_MANAGED` and `ORGANIZATION_DECLARED` (both `HuronError` subclasses
registered as `ErrorCode`s). In unmanaged mode every organization has `declared: false` and the new
fields are `null`, so `share_root` is `null` and clients use their mount prefix as before. In managed
mode an undeclared organization reports `declared: false` and `null` roots. The organization-wide
role groups of the same date make `GET /organizations/{org}/grants` answer all four
organization-scope roles (it answered `{ldap_groups}` for `org_admin` alone), let
`PUT /organizations/{org}/grants/{role}` take the three catalog roles, merge the organization-scope
catalog-role groups into `GET /catalogs/{catalog}/grants` without changing its shape, and add
`GET /catalogs/{catalog}/grants/sources`. `make openapi` regenerates `docs/openapi.json`, and
`web/src/lib/api/openapi.ts` is regenerated from it.

**Amendment (2026-11-06).** Uploads through tusd (section 3) add `PATCH /catalogs/{catalog}`, the
two repair routes and the three upload routes in the table above, `share_group` in the catalog
views, and `CatalogWriteOut` for the create and set catalog answers. `GET /healthz` also reports
`service_user` (`{uid, gid, group}` or `null`), `uploads_url` (or `null`) and
`upload_hook_timeout` in seconds ("Settings"). `GET /readyz` adds the check `lake` ("Lake path").
The new codes are `UPLOAD_NOT_FOUND` 404, `UPLOAD_STATE_CONFLICT` 409, `UPLOAD_SIZE_MISMATCH` 422,
`UPLOAD_TOO_LARGE` 413, `UPLOAD_RECEIPT_MISSING` 422, `UPLOADS_DISABLED` 404,
`SYMLINK_IN_LAKE` 409 and `LAKE_UNAVAILABLE` 503. The existing `STORAGE_FAILED` 500 covers the
other errors of the API's disk work. `SHARE_GROUP_PENDING` is the `code` of a warning, not an
error. `ACL_FAILED` is removed ("Error codes").

**Amendment (2026-11-08).** Containment in the lake (section 3) changes the error codes and two
routes. `SYMLINK_IN_LAKE` 409 replaces the planned `OUTSIDE_LAKE`, which does not exist: a
symbolic link at any step of a lake path refuses the disk work, with the lake path of the link
in `context.path`. A name that fails `check_lake_name` is the existing 422 `NAME_INVALID` (rule
`lake_name`). Every route that changes a directory (create, activate, delete, metadata, schema
assignment, share group, repair) commits its rows first and then does its disk work; a 409
`SYMLINK_IN_LAKE`, a 503 `LAKE_UNAVAILABLE` or a 500 `STORAGE_FAILED` from the disk work keeps
the rows. In `pre-finish`, `SYMLINK_IN_LAKE` is definitive: the upload becomes `failed`. The
repair answers carry `reason` and `detail` for each failed path. `GET /catalogs/{catalog}/grants`
is removed with the ACL plan code (M11.9a). Messages name lake paths in the API form, never
absolute server paths.

## 9. CLI surface

Executable `huron`. The surface is oc-style, `huron <verb> <noun>` (see the amendment below). Global
options, given before the verb: `-o table|json|yaml`, `--api-url`, `--catalog` (overrides the
current catalog). Exit
codes: 0 success; 1 generic failure; 2 usage; 3 not logged in; 4 forbidden; 5 not found; 6 conflict
(version, state, not empty); 7 validation (metadata, schema, names); 8 storage (mount or marker); 130
interrupted.

`huron --help` keeps Typer's rich help and groups the commands into boxed panels with
`rich_help_panel=`, titled exactly, in this order (amended 2026-10-31): **Catalog** (`org`, `catalog`,
`get`, `describe`, `tree`, `search`, `checkout`: find, navigate, search, check out), **Collection**
(`status`, `add`, `rm`, `pull`, `push`, `edit`, `validate`, `publish`, `activate`: work on the
checked-out collection), **Manage** (`create`, `delete`, `set`, `unset`), **Administration** (`adm`)
and **Settings** (`login`, `logout`, `whoami`, `config`). The order lives in one place, `LAYOUT` in
`src/huron/applications/cli/commands/__init__.py`, from which `PANELS`, `VERBS` and each verb's panel
are derived. The table follows the same grouping.
Identifiers are relative to the current catalog (section 5.1); "current collection" is the checked-out
one. A command that looks up an existing namespace or collection tries the identifier relative to the
current catalog first and, when that is not found, as written, so a full identifier printed for
another catalog (`huron --catalog other tree`) works too; a not-found error names every identifier
tried (``the API found no collection <c>.<identifier> or <identifier>``), and its hint names a command
that works where the user is: for the relative reading, ``identifiers are relative to the current
catalog <c>. To see that catalog, run `huron tree` `` (with a `--catalog <c>` override that is not
the saved catalog, ``identifiers are relative to catalog <c>, which `--catalog` selects. To see that
catalog, run `huron --catalog <c> tree` ``); for a full identifier of another catalog, ``to see
catalog <x>, run `huron --catalog <x> tree` `` when the API finds catalog `<x>`, else ``the API found
no catalog <x>. To list the catalogs, run `huron get catalogs -A` ``. A verb typed without its noun prints its help and exits 2 with no error line.

| Panel | Command | Needs API | Needs mount | Minimum role | Behavior |
| --- | --- | --- | --- | --- | --- |
| Catalog | `huron org [name]` | ✓ | | Reader | Like `oc projects` and `oc project` for organizations. Without a name: the organizations the caller can see, with a leading `CURRENT` column (`*` on the current one) and the columns of `get orgs` (`PATH` included), then `The current organization is <o> on <api_url>`, or, with none set, `There is no current organization on <api_url>` and the hint ``To select an organization, run `huron org <name>` ``, or, when the saved one is not among those listed (deleted or hidden), `The current organization <o> no longer exists, or you cannot see it` and the same hint; with none visible it prints `You can see no organizations` (json and yaml: `{organization, api_url, organizations}` with the API rows). With a name: verifies the organization through the API (not found is exit 5), records it in config and prints `The current organization is now <name> on <api_url>`; a current catalog of another organization (or one that can no longer be found) is cleared with the line `There is no current catalog now, because catalog <c> belongs to <o>` (or `because you cannot see catalog <c>`), followed by ``To list the catalogs, run `huron catalog` ``. The checked-out collection is left alone. json and yaml print the same mapping as without a name. |
| Catalog | `huron catalog [name]` | ✓ | | Reader | Like `oc projects` and `oc project`. Without a name: the catalogs of the current organization (every catalog when none is set; with `--catalog C`, the organization of `C`) with a leading `CURRENT` column (`*` on the current catalog) and the columns of `get catalogs`, then `The current catalog is <c> in organization <o> on <api_url>` (the organization part only when the catalog is in the listing), or, with no catalog set, `There is no current catalog on <api_url>` and the hint ``To select a catalog, run `huron catalog <name>` ``; then the checked-out collection (`Current collection: <identifier> (version N)`, or ``There is no current collection. To choose one, run `huron checkout` ``), and exit 0. An organization with no visible catalogs prints ``Organization <o> has no catalogs that you can see. To see the catalogs of all organizations, run `huron get catalogs -A` ``; a saved organization the API no longer finds is exit 5 with the hint ``the current organization <o> no longer exists, or you cannot see it. To select an organization, run `huron org <name>` ``. json and yaml: `{organization, catalog, api_url, collection, catalogs}` with the API rows. With a name: verifies the catalog through the API, records it and its organization in config, prints `The current catalog is now <name> on <api_url>` (and `The current organization is now <o>` when the organization changed), and mentions a checked-out collection that belongs to another catalog (``Current collection: <identifier> (version N), in catalog <c>. To choose one in this catalog, run `huron checkout` ``). A catalog the API does not find is exit 5 with the hint ``to list the catalogs, run `huron get catalogs -A` ``, as for `describe catalog` and `delete catalog`. |
| Catalog | `huron get orgs` | ✓ | | Reader | Organizations the caller can see. The table has a `PATH` column: the organization's `path`, or `<mount_prefix>/<org>` marked `(prefix)` when it has no root. json and yaml print the API rows unchanged. |
| Catalog | `huron get catalogs [--org O \| -A\|--all-orgs]` | ✓ | | Reader | The catalogs of the current organization when one is set, else of every organization; `--org` names another, `-A` lists every organization's, and `--org` with `-A` is a usage error. Table has a leading `CURRENT` column with `*` on the current catalog, like `oc get projects`; an empty listing scoped by the current organization adds a line naming it and `-A`; a saved organization the API no longer finds is exit 5 with the hint `huron org <name>`. json and yaml print the API rows unchanged. |
| Catalog | `huron get namespaces [parent]` | ✓ | | Reader | Children of `parent`, or the top level of the current catalog. The table ends with ``To list the collections in a namespace, run `huron get collections <namespace>`. To see the full tree, run `huron tree` ``; an empty one prints ``There are no namespaces here. To create one, run `huron create namespace <identifier>` `` instead. Here and in every hint below, `huron tree` reads `huron --catalog <c> tree` when the listed catalog `<c>` is not the saved current catalog (a `--catalog` override or a full identifier of another catalog), because `huron tree` alone shows only the saved one. |
| Catalog | `huron get collections [namespace]` | ✓ | | Reader | With a namespace, the collections directly in it; without one, every collection in the current catalog (search over every state). The table ends with ``To select a collection, run `huron checkout <COLLECTION>` ``; an empty one prints ``There are no collections here. To see the full catalog, run `huron tree`. To create a collection, run `huron create collection <identifier>` `` instead. |
| Catalog | `huron get files [identifier]`, `huron get log [identifier]` | ✓ | | Reader | Recorded files and audit entries of the collection (default the current one). Paged output. |
| Catalog | `huron get schemas [org]` | ✓ | | see section 8 | Registry entries, newest version first. |
| Catalog | `huron get grants [--org O \| --catalog C]` | ✓ | | Reader for a catalog; `--org`: see section 8 | `--org`: the organization's groups for each of `org_admin`, `catalog_admin`, `contributor` and `reader`. A catalog (default the current one; the sub-option wins over the global `--catalog`): `ROLE`, `GROUP`, `SOURCE` from `GET /catalogs/{catalog}/grants/sources`, the source `platform`, `organization <o>` or `catalog`; json and yaml print the `items` (amendment 2026-10-31). |
| Catalog | `huron get meta [identifier]` | ✓ | | Reader | The collection's metadata, its schema override and the local draft when one exists. |
| Catalog | `huron describe org <name>`, `describe catalog [name]`, `describe namespace <identifier>`, `describe collection [identifier]`, `describe schema <id> [--resolved]` | ✓ | | Reader; schemas per section 8 | One object in detail. `catalog` defaults to the current catalog, `collection` to the current collection. |
| Catalog | `huron tree [namespace]` | ✓ | | Reader | The namespace tree of the current catalog (or the subtree under `namespace`, hung from one branch named by its path), rooted at the catalog's name, with collections as leaves: a namespace shows whether it allows collections, a collection shows its full identifier, ready for `huron checkout`, and its state. A rich tree in table mode, a nested structure in json and yaml. Fetches no files. |
| Catalog | `huron search [-q] [-l k=v]... [--state]...` | ✓ | | Reader | Searches the current catalog (the global `--catalog` overrides). Paged output. |
| Catalog | `huron checkout [identifier]` | ✓ | | Reader | Records a working copy (collection id, identifier, version, path) and makes it current. Several working copies may exist; `checkout` switches. Without an identifier, an interactive picker walks the current catalog: child namespaces (shown as `name/`), the collections directly in the namespace, and `..` below the top, until a collection is chosen. Without a terminal, or with `-o json\|yaml`, the picker refuses with the usage error `` `huron checkout` needs a collection identifier when it cannot ask you to choose one `` and the hint ``to see the collections, run `huron tree`. Then run `huron checkout <identifier>` ``. |
| Collection | `huron status [--all]` | ✓ | optional | Reader | Always works. Without a checked-out collection: the organization, the catalog, the API url, `collection: null` and ``There is no current collection. To choose one, run `huron checkout` `` (with no catalog selected, ``There is no current catalog. To list the catalogs, run `huron catalog`. Then run `huron catalog <name>` ``), exit 0. With one, in table mode: the line `On collection <identifier> (version N, up to date \| version N, behind the service's version M) in catalog <c>[, organization <o>]`; a table of staged changes, `STAGED` (`add`\|`remove`), `PATH`, `SIZE` (binary units, `-` for removes), `FROM` (the local source, `-` for removes); `Unrecorded files on the share: a, b` when the mount is present and there are any, or `The share is not mounted on this machine. The CLI did not check for unrecorded files`, and ``Your working copy is behind the service. Run `huron pull` `` when behind; then the next step: ``Nothing is staged. To stage files, run `huron add <file>` ``, or ``To push, run `huron push -m "<message>"`. To unstage a path, run `huron rm <path>` ``. json and yaml keep every key they had and add `staged: [{action, rel_path, size, source}]`. `--all` reads every working copy under `$XDG_STATE_HOME/huron/collections/*` (`StateDir.working_copies()`, from `copy.json` and `stage.json`), one section each with `*` on the checked-out one, only those with something staged unless none are, then `Nothing is staged in any working copy` (with no working copy at all, ``There are no working copies on this machine. To make one, run `huron checkout <identifier>` ``); only the checked-out copy is compared with the service and the share, so the others show `(version N)` and ``To push or unstage these changes, run `huron checkout <identifier>` first``. With `-o json\|yaml`, `--all` is a list of reports, each with `current`, and `null` for the fields that need the API on the others. |
| Collection | `huron add <path>... [--as rel_path] [--recursive]` | | | Contributor | Stages local files or directories for the current collection; a directory is staged with its relative layout. |
| Collection | `huron rm <rel_path>...` | ✓ | | Contributor | Stages removals; refuses paths not recorded. |
| Collection | `huron pull` | ✓ | | Reader | Refreshes version and file list; drops staged removes of files no longer recorded with a warning. |
| Collection | `huron push [-m message]` | ✓ | | Contributor | D-23 as amended 2026-11-06 ("Upload flow", "The CLI"). Before it uploads a byte, a preflight `POST /collections/{id}/commits?dry_run=true` with the staged sizes (and a `sha256` only where a resumed push already knows it) lets the service refuse the push (`FORBIDDEN` exit 4, `BASE_VERSION_CONFLICT` exit 6, `FILE_NOT_RECORDED`, …), leaving the stage untouched. Then it uploads each staged add to tusd at `uploads_url` (from `GET /healthz`), with progress per file. It needs no mount and unlinks nothing. Then it prints the summary of the commit. Exit 6 on `BASE_VERSION_CONFLICT` with the hint ``run `huron pull` ``. |
| Collection | `huron edit meta [identifier] [--from-scratch \| --file <doc.json>]` | ✓ | | Contributor | Starts from the local draft or the published metadata (with `--from-scratch`, from an empty document), walks the resolved schema's fields and saves a local draft. With `--file` nothing is asked: the JSON document becomes the local draft as it is, and the same validation summary is printed (``Draft saved with N problems. To publish it, run `huron publish meta` ``); `--file` with `--from-scratch` is a usage error. |
| Collection | `huron validate meta [identifier]` | ✓ | | Contributor | Validates the draft against the resolved schema. |
| Collection | `huron publish meta [identifier]` | ✓ | | Contributor | Sends the patch with `If-Match`. The API writes `metadata.json` in the same request; the CLI writes nothing to the share. A 500 `STORAGE_FAILED` or 503 `LAKE_UNAVAILABLE` gets the hint ``To make the directory again, run `huron adm repair <identifier>` ``. |
| Collection | `huron activate collection [identifier]` | ✓ | | Contributor | For drafts created with `--draft`. The API creates the directory and writes `metadata.json`. A 500 `STORAGE_FAILED` or 503 `LAKE_UNAVAILABLE` gets the hint ``To make the directory again, run `huron adm repair <identifier>` ``; running the command again does not repair. |
| Manage | `huron create org <name> [--display-name] [--description]` | ✓ | | Platform Admin | Unmanaged mode only: the API records the organization, then creates `<lake_path>/<org>` with mode `2751`. In managed mode the API's 409 `ORGANIZATIONS_MANAGED` is exit 6 with the hint ``the service configuration declares the organizations. To prepare their directories, run `huron adm provision-orgs` ``. |
| Manage | `huron create catalog <name> [--org <org>] [--schema id] [--display-name] [--description] [--share-group <group>]` | ✓ | | Org Admin | `--org` defaults to the current organization; with neither, a usage error hints `--org <org>` or `huron org <name>`; a saved organization the API no longer finds is exit 5 with the hint `huron org <name>`. The API records the row and `share_group`, creates the directory and tries the `chgrp`. A `SHARE_GROUP_PENDING` warning prints the hint ``To set the group on disk, run `huron adm provision-catalogs --emit-script` as the storage administrator``. A 500 `STORAGE_FAILED` or 503 `LAKE_UNAVAILABLE` gets the hint ``To make the directory again, run `huron adm repair <identifier>` ``. |
| Manage | `huron create namespace <identifier> [--allow-collections] [--parents]` | ✓ | | Catalog Admin | `--parents` calls the API once for each missing ancestor. The API creates each directory. A 500 `STORAGE_FAILED` or 503 `LAKE_UNAVAILABLE` gets the hint ``To make the directory again, run `huron adm repair <identifier>` ``; running the command again does not repair (`NAME_TAKEN`). |
| Manage | `huron create collection <identifier> [--metadata file] [--draft]` | ✓ | | Contributor | Reserves the draft, runs the walkthrough unless `--metadata`, then calls `activate`: the API creates the directory and writes `metadata.json`. `--draft` stops after the walkthrough. |
| Manage | `huron delete org <name>`, `delete catalog <name>`, `delete namespace <identifier>` | ✓ | | Platform Admin (org), Org Admin (catalog), Catalog Admin (namespace) | The API deletes the row, then removes the empty directory (`rmdir`). A directory that is not empty stays, and `huron adm check` reports it as `dir_unrecorded`. The CLI removes nothing. Deleting the current organization clears it from config. A declared organization's 409 `ORGANIZATION_DECLARED` is exit 6 with a hint in the same style (remove it from the service configuration first). For an organization with a root, the API never removes `<root>/<org>`, which belongs to the storage administrator; the CLI prints a hint naming the directory instead. |
| Manage | `huron delete collection <identifier> [--yes]` | ✓ | | per D-11 | Commits the removal of every file, then deletes the collection through the API. The API unlinks the files that it recorded or placed, `metadata.json` and `.huron-part` files, then removes the directory ("Removals and the inode guard"). The CLI makes no check of unrecorded files and unlinks nothing; any other file stays, with a `dir_unrecorded` finding. |
| Manage | `huron set override <file> [identifier]`, `huron unset override [identifier]` | ✓ | | Contributor | Sets or clears the collection's schema override together with the current metadata draft. The API rewrites `metadata.json` when its bytes change. |
| Manage | `huron set catalog <catalog> --share-group <group> \| --no-share-group` | ✓ | | Org Admin | `PATCH /catalogs/{catalog}` with `{share_group}` (`--no-share-group` sends `null`). The API tries the `chgrp`. A `SHARE_GROUP_PENDING` warning prints the hint ``To set the group on disk, run `huron adm provision-catalogs --emit-script` as the storage administrator``. |
| Manage | `huron set namespace <identifier> --allow-collections/--no-allow-collections` | ✓ | | Catalog Admin | Changes `collections_allowed`. The directory's mode stays the same (section 6.2). |
| Administration | `huron adm grant <role> <group> [--org O \| --catalog C]`, `huron adm revoke <role> <group> [...]` | ✓ | | Platform Admin for `org_admin`; Org Admin for `catalog_admin`, and for every catalog role with `--org`; Catalog Admin for `contributor` and `reader` with `--catalog` | `--org O` takes `org_admin`, `catalog_admin`, `contributor` or `reader` (the catalog roles then hold in every catalog of `O`); `org_admin` needs `--org`; otherwise the catalog roles use `--catalog`, else the global or current catalog; any other role is a usage error. For a declared organization every `--org` change is refused with 409 `ORGANIZATION_DECLARED`, and the hint says to edit `groups.<role>` in the service configuration. Edits the group set. It prints no ACL reminder: grants do not reach the disk. |
| Administration | `huron adm check [--catalog name] [--hash]` | ✓ | ✓ | Reader | Section 6.4, including the organization findings `org_dir_missing`, `org_marker_missing`, `org_marker_mismatch` and, in managed mode, `org_undeclared` (a warning instead of a refusal when an undeclared organization's directory cannot be located). |
| Administration | `huron adm repair <identifier> [--recursive]`, `huron adm repair --org <org>` | ✓ | | Catalog Admin; Org Admin with `--org` | Calls `POST /catalogs/{catalog}/repair` (or, with `--org`, `POST /organizations/{org}/repair`). The API makes missing directories, sets permission bits, tries the `chgrp` of the catalog directory and rewrites `metadata.json` (the amendment's "Directory verbs in the API"). The API acts only on the directories that the rows plan, one step each, and lists no directory. The CLI prints each changed path, each warning and each failed path with its `reason` and `detail`. A missing setgid bit or a wrong directory group is a failed path with the reason `mode_drift`, for `huron adm provision-catalogs`. A symbolic link is a failed path with the reason `symbolic_link`; the storage administrator removes it. |
| Administration | `huron adm verify-mounts` | ✓ | ✓ | any | One row per organization the caller can see: `ORG`, `PATH`, `STATE` (`ok`, `missing`, `no marker`, `wrong instance`, `wrong org`, `undeclared`); checks the per-organization marker, or the lake-path marker for an organization that is neither declared nor rooted, against `GET /healthz`. In managed mode an organization the configuration does not declare is `undeclared` (path marked `(undeclared)`) and does not count. Exit 1 when any other row is not `ok`; the hint names `provision-orgs` for both markers. Replaces `adm verify-root`. |
| Administration | `huron adm provision-orgs [--org O] [--dry-run] [--emit-script [--uid U] [--gid GID]]` | ✓ | ✓ | Platform Admin, run by the storage administrator | Section 6.1: for each declared organization (or only `O`), requires its root, creates `<root>/<org>`, makes `U:<gid>` the owner of that directory only (no recursive step), sets the mode `2751`, prepares the lake path, `.tus-uploads` and the lake-path marker, and writes the per-organization marker (`Provisioner.provision`); refuses a marker naming another instance or organization; idempotent. `--dry-run` prints the steps; `--emit-script` prints an equivalent shell script (`mkdir`, `chown`, `chmod`, the marker write, with the numeric `U:<gid>`) for roots only `root` can write, and touches nothing. In the **Share** group of `huron adm --help`, beside `check` and `verify-mounts`. |
| Administration | `huron adm provision-catalogs [--catalog C] [--dry-run] [--emit-script [--uid U] [--gid GID]]` | ✓ | ✓ (read-only for `--dry-run` and `--emit-script`) | Reader (it reads each catalog's `share_group` through the API), run by the storage administrator | The amendment's "Catalog share group and directory modes": selects each catalog with a `share_group` whose directory group differs, or below which a directory has `mode_drift` for the setgid bit or the group (only `C` with `--catalog`). Direct mode (root on a writable mount, or `U` with the right supplementary groups) runs `find <catalog dir> -type d -exec chgrp <group> {} + -exec chmod 2750 {} +` for each; files keep their group and mode, and `find` follows no symbolic link. `--dry-run` prints the steps; `--emit-script` prints the same lines as a shell script for root (`set -eu`, names quoted with `shlex.quote`) and changes nothing. |
| Administration | `huron adm publish schema <org\|platform> <name> <file> [--extends id]` | ✓ | | see section 8 | Publishes a new version of an organization or platform entry. |
| Administration | `huron adm assign schema <schema_id> [--catalog C]` | ✓ | | see section 8 | Assigns the entry to the catalog (default the current one) and prints the recompute counts. |
| Settings | `huron login [--device\|--browser]`, `logout`, `whoami` | ✓ | | any | Device grant by default; loopback PKCE with `--browser`; exchange; tokens at `$XDG_STATE_HOME/huron/tokens.json` mode 0600. |
| Settings | `huron config show\|set <key> <value>` | | | any | `api_url`, `issuer`, `client_id`, `mount_prefix` (where the workstation's read-only mount of the lake path is; organizations without a root lie below it). The key `acl_backend` is gone (M11.9a). |

Working-copy state lives in `$XDG_STATE_HOME/huron/collections/<uuid>/`: `copy.json` (identifier, version,
path, checked_out_at), `stage.json` (adds as `{rel_path, source, size}`, removes), `metadata.draft.json`.
The current organization, catalog and collection are in `$XDG_CONFIG_HOME/huron/config.yaml`
(`current_organization`, `current_catalog`, `current_collection`; none is a `config set` key). The CLI writes
nothing to the share (amendment 2026-11-06, "The CLI"). The API writes `metadata.json`, places the
uploaded files and makes and removes the directories. `huron adm provision-orgs` and
`huron adm provision-catalogs` in direct mode are the only exceptions, and the storage administrator
runs them.

### Amendment (2026-10-31): the oc-style CLI surface

- **The table above replaces the CLI surface the plan first specified**, decided with the user on
  2026-10-31. It supersedes every older verb spelling elsewhere in this plan: the milestone text in
  section 11 is history and keeps the spellings it was built with.
- **Shape.** Commands read `huron <verb> <noun>`, after `oc`: `get`, `describe`, `create`, `delete`,
  `activate`, `edit`, `validate`, `publish`, `set` and `unset` take a noun; administration lives under
  one sub-command, `huron adm`. Under `get`, the nouns are plural (`get catalogs`), with the singular
  registered as a hidden alias; under `describe`, they are singular.
- **The old spellings are removed, with no aliases**, because Huron is pre-release. The mapping:
  `org list` → `get orgs`; `catalog list` → `get catalogs`; `catalog use <name>` → `catalog <name>`;
  `catalog describe` → `describe catalog`; `org grants`, `catalog grants` → `get grants`;
  `org create`, `catalog create <org> <name>` → `create org`, `create catalog <name> --org <org>`;
  `org delete`, `catalog delete` → `delete org`, `delete catalog`;
  `org grant|revoke <org> org_admin <group>` → `adm grant|revoke org_admin <group> --org <org>`;
  `catalog grant|revoke <catalog> <role> <group>` → `adm grant|revoke <role> <group> --catalog <catalog>`;
  `namespace list` → `get namespaces`; `namespace create|delete` → `create|delete namespace`;
  `namespace configure` → `set namespace`; `schema list|show` → `get schemas`, `describe schema`;
  `schema publish|assign` → `adm publish schema`, `adm assign schema <id> [--catalog C]`;
  `collection list` → `get collections`; `collection describe` → `describe collection`;
  `collection create|delete` → `create|delete collection`; `collection activate` →
  `activate collection`; `meta show` → `get meta`; `meta edit` → `edit meta`; `meta init` →
  `edit meta --from-scratch`; `meta validate|publish` → `validate|publish meta`;
  `meta override set|clear` → `set|unset override`; `files`, `log` → `get files`, `get log`;
  `search <catalog>` → `search` over the current catalog; `check` → `adm check`; `acl apply` →
  `adm apply-acl` (removed in M11.8a); `platform verify-root` → `adm verify-root`.
- **New commands.** `huron org` and `huron catalog` work as `oc projects` and `oc project` do:
  without a name they list the organizations, or the current organization's catalogs, with `*` on
  the current one; with a name they switch. The current organization is new config
  (`current_organization`): `huron org <name>` sets it, and clears a current catalog of another
  organization; `huron catalog <name>` sets it to the catalog's organization. It scopes
  `huron catalog` and `huron get catalogs` (`--org` names another, `-A` lists every one) and is the
  default `--org` of `huron create catalog`; `get grants --org` and `get schemas [org]` stay explicit.
  `huron delete org` clears it when it deletes the current one, a saved organization that is gone
  or hidden draws the hint `huron org <name>`, and `--catalog C` shows `C`'s organization in
  `huron catalog` and `huron status` without changing the saved one;
  `huron tree` shows the namespace tree with collections as leaves; `huron describe namespace`
  reads `GET /catalogs/{catalog}/namespaces/{path}`; `huron get collections` without a namespace
  lists the whole current catalog; `huron checkout` without an identifier opens a picker
  (`Prompter` gains a way to tell whether it can prompt, and the scripted fake follows); and
  `huron status` works without a checked-out collection.
- **Help.** Grouping uses Typer's own boxed panels (`rich_help_panel=`), not a hand-written help
  screen; the panel titles are those in the table. Regrouped later on 2026-10-31 into five panels,
  **Catalog**, **Collection**, **Manage**, **Administration** and **Settings** (section 9's
  introduction lists their verbs); the panels **Basic Commands**, **Context**, **Working Copy** and
  **Create and Change** are gone. No command spelling changed.
- **`huron status [--all]`** (decided later the same day). With a checked-out collection the table
  mode prints a header line, a `STAGED`/`PATH`/`SIZE`/`FROM` table, the unrecorded files and the next
  step, as the table row says; json and yaml add `staged`. `--all` lists every working copy on the
  machine from its state files and asks the API about the checked-out one only. `StateDir` gains a
  public `working_copies()`.
- **`huron edit meta --file <doc.json>`** stores a JSON document as the local draft without the
  walkthrough, then `huron publish meta` publishes it.
- **Push preflight** (a defect found by the NOAA verifier: a Reader's `huron push` copied files onto
  the share and left them unrecorded before the service refused the commit with 403). `huron push`
  now sends the commit as a dry run (section 5.4, section 8) before it uploads anything, so a
  refused push leaves the share untouched. Since M11.7 push copies nothing onto the share: it
  uploads through tusd.
- **Hints.** Every hint the CLI prints, and every command the web shows (`web/src/lib/cli.ts`),
  uses the new spellings.

### Amendment (2026-10-31): organizations declared in the service configuration

- **Decided with the user on 2026-10-31**, with the section 3 amendment of the same date. The rows
  of `get orgs`, `huron org`, `create org`, `delete org`, `adm grant`, `adm check`,
  `adm verify-mounts`, `adm provision-orgs` and `config` above carry it.
- **Paths per organization.** The CLI resolves every absolute path through `Mount`, by the
  organization of the first segment: its `root` from `GET /api/v1/organizations/{org}`, cached for
  the command, or `mount_prefix` when the root is `null` (section 6.1). The marker check lives inside
  `Mount`, so no command can skip it. Since M11.8a `Mount` only reads. Since M11.9a its storage is
  typed `ShareReader`.
- **Renamed, without an alias**: `adm verify-root` → `adm verify-mounts`, which reports every
  organization instead of the one root. The old amendment's mapping `platform verify-root` →
  `adm verify-root` now ends at `adm verify-mounts`.
- **New**: `adm provision-orgs`, the storage administrator's verb, in the `Share` group of
  `huron adm --help`.
- **Hints.** In managed mode `create org` and the refusals of `delete org` and `adm grant … --org`
  name the service configuration (for a grant, the `groups.<role>` key to edit) and
  `huron adm provision-orgs`; storage errors below a rooted
  organization name its path and, when configured, its `export`.

### Amendment (2026-11-08): the CLI writes nothing to the lake

- **Decided with the user on 2026-11-07 and 2026-11-08** (section 3, "The CLI" and "Containment in
  the lake"). The table above carries it.
- **No CLI disk writes.** Every directory verb calls the API only. The CLI makes no directory,
  writes no `metadata.json`, changes no mode or group and unlinks nothing. `Mount.storage` is the
  read-only port `ShareReader`, so a write does not type-check. `huron adm provision-orgs` and
  `huron adm provision-catalogs` in direct mode are the only exceptions. They build a writable
  `PosixStorage` themselves, and the storage administrator runs them.
- **Push through tusd.** `huron push` uploads each staged add to tusd at `uploads_url`, with the
  tus client in `applications/cli/uploads.py` (M11.7). It needs no mount. The old NFS-copy path
  (`copy_in`, the `.huron-part` push, `write_sidecar`) is removed, not kept for compatibility.
  The `os.walk` in `sync._collect` stays: it reads the user's local source folder for staging.
- **No ACL verb.** `huron adm apply-acl`, the `acl_backend` key and the ACL reminder of
  `huron adm grant` and `huron adm revoke` are removed (M11.8a, M11.9a).
- **Reads only through the traversal.** `huron adm check`, `huron adm verify-mounts` and
  `huron status` read the read-only mount through `ShareReader` on `LakePath`. A symbolic link
  is reported, never followed.

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
| M10 Release | Deployment manifests, operator and user docs, end-to-end test, merge; declared organizations with per-organization roots, the configuration file and the Helm chart (amendment 2026-10-31) | M9 |

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
  - `src/huron/pkg/canonical.py`: `canonical_bytes(document)`, `document_sha256`. RFC 8785 bytes, except
    that integers past the I-JSON range (2^53) are written with their exact digits rather than refused
    (jsonb answers a float such as `-1e31` as an integer); strings and floats go through `rfc8785`.
    NaN, infinity, non-string keys and lone surrogates raise `NotCanonicalizable`, which metadata and
    schema checks report as 422 `METADATA_INVALID` / `SCHEMA_INVALID` with rule `json`.
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
    `scope_type_of(role)` (since 2026-10-31 `scope_types_of(role)`, a set: the catalog roles also
    hold at organization scope, D-28).
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
    `set_platform_admins`, `set_org_admins` (since 2026-10-31 `set_organization_role`, for all four
    organization-scope roles, D-28), `set_catalog_role` enforcing the privilege per role, the
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
- Amended 2026-10-31 (M10.6): `configmap.yaml` is replaced by a `configMapGenerator` for
  `huron.yaml` (every non-secret setting and `organizations`), mounted at `/etc/huron` with
  `HURON_CONFIG_FILE`; the Deployment and the Job take only the Secret into their environment.
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
- **Note (2026-11-01, documentation website).** The documentation is also a website: an Astro
  Starlight site in `web/docs-site/` that the web serves at `/docs`, readable without signing in
  (docs/web-design.md §3.9). `docs/*.md` stay the only copy of the prose; the site's sync step
  generates its guides from them. The CLI reference is generated from the CLI by
  `scripts/cli_reference.py` and committed, and the gate checks it with `--check`. A change to
  `docs/*.md` or to a command reaches the site with the next `npm run docs:build` in `web/` or
  image build.

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

#### M10.4 Declared organizations in the service

- Intent: the section 3 amendment of 2026-10-31, service half (D-10 extended, D-28).
- Create or change:
  - `src/huron/applications/api/settings.py`: `HURON_CONFIG_FILE` through pydantic-settings' YAML
    source in a strict subclass (precedence environment, file, defaults; unknown top-level keys fail),
    `organizations` (entries `name`, `display_name`, `description`, `admin_groups` (since replaced by
    `groups`, the organization-wide role groups of the section 3 amendment), `root`, `export`; names checked with `huron.schema.naming`, duplicates fail, `root` absolute and
    normalized without `..`), `HURON_ORGANIZATIONS` as a JSON list replacing it; managed mode when the
    key is present, even empty.
  - `src/huron/core/lake/bootstrap.py`: the declared organizations through `LakeSettings`;
    reconciliation in the bootstrap transaction under `tx.lock_bootstrap()` (create, update through the
    new `OrganizationStore.update` port with `version` + 1 and audit `organization.update`, exact
    `org_admin` replacement with grant audit entries, a warning with `catalog_count` for each
    undeclared organization, no write at all when nothing differs). The lock port on the PostgreSQL and
    memory transactions; `organization.update` in `core.lake.audit.models.Action`.
  - Managed-mode guards as registered `ErrorCode`s: `ORGANIZATIONS_MANAGED` (409, `POST
    /organizations`) and `ORGANIZATION_DECLARED` (409, `DELETE` of a declared organization and `PUT`
    of its `org_admin` grants).
  - API views: `declared`, `root`, `path`, `export` on organizations; `share_root` on catalogs,
    namespaces and collections, from configuration (no migration). `make openapi`.
  - `docs/api-errors.md` lists both codes.
  - Tests: unit over the memory fakes and contract over PostgreSQL for the reconciliation (create,
    update, exact grant replacement and its audit, the undeclared warning, a second run writing
    nothing), concurrent bootstrap on PostgreSQL, settings precedence and strictness, the 409s and the
    new view fields.
- Verification: `make gate`; `uv run pytest -m contract`; `uv run pytest tests/unit/test_openapi_snapshot.py
  tests/unit/test_error_contract.py`.
- Dependencies: M10.3.
- Status: pending

#### M10.5 Per-organization roots in the CLI

- Intent: section 6.1 as rewritten and the section 9 amendment of 2026-10-31.
- Create or change:
  - `src/huron/core/storage/marker.py`: `Marker` gains the optional `organization`; verification of a
    per-organization marker compares it.
  - `src/huron/applications/cli/mount.py`: absolute paths per organization (its `root`, cached per
    command, else `mount_prefix`); the marker check inside `path`, `ensure`, `apply` and `remove`.
    Every path derivation (directory verbs, `inventory` disk paths, `activate`, `apply-acl`, `check`,
    `tree`, `push` and sync) goes through it.
  - `huron adm provision-orgs [--org O] [--dry-run] [--emit-script]`; `adm verify-root` renamed
    `adm verify-mounts` with one row per organization; the `org_*` findings in `adm check`; the
    managed-mode hints of `create org`, `delete org` and `adm grant org_admin`; `delete org` never
    removing a rooted organization's directory; the `PATH` column of `get orgs` and `huron org`.
  - Tests in `tests/unit/cli` and `tests/unit/storage`.
- Verification: `make gate`.
- Dependencies: M10.4.
- Status: pending

#### M10.6 The configuration file in the stacks, the Helm chart and kustomize

- Create or change:
  - `huron.dev.yaml` (section 3 amendment, Development). `docker-compose.app.yml` mounts it read-only
    at `/etc/huron/huron.yaml` with `HURON_CONFIG_FILE` and recreates the API when its content
    changes (verified by editing the file and re-running `make app`); `dev.env` sets
    `HURON_CONFIG_FILE=huron.dev.yaml` for `make api`.
  - `docker/seed/run.mjs`: in managed mode no organization and no `org_admin` grant, and no early
    return keyed on the first organization existing.
  - `scripts/e2e.sh`: `huron adm provision-orgs` instead of `create org`, with roots under a temporary
    directory through an override configuration.
  - `deploy/helm/huron`: `values.yaml` (image, replicas, `database.existingSecret` and key, `config`
    rendered verbatim as `huron.yaml` into a ConfigMap, `extraEnv`, an OpenShift Route and an ingress,
    each a toggle, resources, an optional web deployment, off by default), the migration Job as a
    `pre-install,pre-upgrade` hook needing only the database secret, a `checksum/config` annotation on
    the API pod template, `values.schema.json` (organization name pattern, `instance_id` required;
    unique names documented, not expressible), `NOTES.txt` reminding to run
    `huron adm provision-orgs`. The API pod mounts no share.
  - `deploy/openshift`: a `configMapGenerator` for `huron.yaml`, `HURON_CONFIG_FILE` and the volume.
  - `deploy/README.md` documents both paths.
- Verification: `make gate`; `helm lint --strict deploy/helm/huron -f
  deploy/helm/huron/ci/example-values.yaml` and `helm template huron deploy/helm/huron -f
  deploy/helm/huron/ci/example-values.yaml` when `helm` is available (`config.instance_id` has no
  default, so the chart's defaults alone do not lint); `kubectl kustomize deploy/openshift`; `docker compose -f docker-compose.app.yml
  config --quiet`; `bash -n scripts/e2e.sh`.
- Dependencies: M10.5.
- Status: pending

#### M10.7 Share roots in the web and the documentation

- Create or change: the web shows `share_root` + `/` + the relative path wherever it showed
  `${mountPrefix}/${path}`, and the configured mount prefix only when `share_root` is `null`;
  `web/src/lib/api/openapi.ts` regenerated with `npm run generate:api`; a dated accepted amendment in
  `docs/web-design.md`. `docs/operator.md` (the runbook: declare the organization, `helm upgrade`,
  `huron adm provision-orgs`), `docs/user-guide.md`, `docs/architecture.md`, `README.md` (the
  development configuration file and `make app`), `docs/adr/0007-declared-organizations.md`.
- Verification: `make gate`; `make docs-check`; the web's `npm run check` and unit tests.
- Dependencies: M10.4.
- Status: pending

### Milestone 11 — Uploads through tusd

The section 3 amendment of 2026-11-06 (ADR 0008), as revised on 2026-11-07 and after the M11.5
escalation on 2026-11-08: the API holds the mount. M11.1 to M11.4 are committed and verified. The
other tasks run in the order of this list, not in the order of their numbers: M11.5a, M11.7,
M11.8a, M11.9a, M11.5b, M11.5c, M11.5d, M11.5e, M11.6, M11.8, M11.9, M11.10, M11.11, M11.12 and
M11.13. The tasks keep their old identifiers, so that the references in sections 3 to 9 stay
correct. Each task fits one implementer in one pass and ends with `make gate` and its own grep
checks.

M11.5a records the escalated M11.5 tree on the branch `m11.5-escalated` and keeps only its two
verified parts: the hash pool and the overwrite backup. The branch is reference material for the
later tasks. No task deletes it. The orchestrator deletes it after M11.5e, when the user confirms.

The three deletion tasks (M11.7, M11.8a and M11.9a) come before the change of the `Storage` port
to `LakePath` (M11.5c), for two reasons. First, each CLI disk write, the copy method and each ACL
method is a caller of the port. If they stay, M11.5c must move dead code onto `LakePath`. After
the deletions, M11.5c is a type change plus `stat`, `is_empty`, `Outcome` and the inode guards.
Second, the CLI and the API must not both write the same directories. M11.8a removes the CLI
writes before the API's directory verbs come back in M11.5d, so the tree never holds two writers.
M11.5b then changes two value shapes and the root check, which have callers today and no tie to
the traversal. M11.5c changes the port once, with every caller: after it, no disk operation can
follow a symbolic link or leave the lake. M11.5d builds the directory verbs and M11.5e builds
repair, both on the final port.

Two intervals change behaviour, and neither keeps code for compatibility. From M11.8a to M11.5d, a
directory verb on a real lake changes only rows. From M11.7 to M11.6, the bytes of a removed file
stay on the disk. There is no production lake, so neither interval puts data at risk.

The setgid measurement of "Catalog share group and directory modes" gates only M11.13 (the Helm
chart and the production values). The operator records the result and the volume security style
in section 3's bullet "Facts about the storage (measured 2026-11-06)". M11.11 runs on the local
cluster, where the lake is a local Linux filesystem, and does not wait for that record. The code
tasks do not wait either: the `stat` after each `mkdir` makes a failed inheritance visible.

#### M11.1 The uploads area, its stores and receipts in commits

- Intent: the amendment's upload rows, receipts, removal outbox and persistence.
- Create or change:
  - `src/huron/core/lake/uploads/`: `models.py` (`Upload`, `UploadState`, `Removal`, `Destination`
    `{path, share_root, groups}` built by the caller), `ports.py` (`UploadStore`: insert, get, set
    state, find placed receipts by `(collection, keys, actor)`, mark committed, insert removals,
    delete pending removals by key, claim removals, finish removal, file/placed lookups by key),
    `errors.py` (the upload codes of the amendment), `operations.py` (`Uploads`: `begin`,
    `placement`, `receipt`, `fail`, `terminate`, `get`, `claim_removals`, `removal_still_valid`,
    `finish_removal`; each in one transaction, authorized through `Authorizer`).
  - `src/huron/core/lake/files/commits.py`: `Commits` takes a `receipts` mode (`required` |
    `optional`) and `upload_ttl`; a real commit checks receipts (`UPLOAD_RECEIPT_MISSING`), marks
    them `committed`, inserts removal rows and deletes pending removals of re-added keys, in the
    commit's transaction. Dry runs unchanged.
  - The `uploads` attribute on the `Store`/`Transaction` protocols, `core/metastore/uploads/`
    (memory and PostgreSQL), migration `migrations/versions/0003_uploads.py`, the schema map
    (`migrations/schema.sql`, `scripts/check_schema_map.py` passes), bootstrap composition.
  - Tests: unit over the fakes for every operation and error (wrong user, wrong state, size
    mismatch, expired receipt, receipt for another path, re-add cancelling a removal); the store
    contract suite over memory and PostgreSQL.
- Verification: `make gate`; `uv run pytest -m contract`.
- Dependencies: M10.7.
- Status: complete
- Execution notes: `Lake.uploads` is `Uploads(uow, clock, declarations, ttl=, max_size=)`, built by
  `build_lake` from `LakeSettings.upload_receipts` (`ReceiptMode.REQUIRED`), `upload_ttl` (24 h)
  and `upload_max_size` (`0`, no limit). The API runtime passes `ReceiptMode.OPTIONAL` for now,
  because it serves no upload route and so cannot issue receipts (the web e2e and Docker seeds
  commit file-less adds); M11.3 (v3 numbering) replaces that argument with
  `settings.upload_receipts` and threads `upload_ttl` and `upload_max_size`. `Destination(path, share_root, groups)`: `path` is
  `<collection disk path>/<rel_path>` (the form of every API path, below the organization's
  base), `share_root` comes from `Declarations.share_root(organization)` (the same source as the
  views' `share_root`), and `groups` is the rbac `EffectiveGroups` of the catalog, the value of
  `GET /catalogs/{catalog}/grants`, so M11.2's `EffectiveGroups.upload_service` reaches it with no
  change here. Authority: `begin`, `placement`, `terminate` and `get` take the user's `Actor`
  (creator-only operations answer `UPLOAD_NOT_FOUND` to anyone else); `receipt`, `fail`,
  `claim_removals(limit)`, `removal_still_valid(id)` and `finish_removal(id)` take no actor, as
  the ingest secret is their authority (M11.2). `receipt` repeated with the same size and hash on
  a placed upload is a no-op; otherwise it needs `pending`. `terminate` accepts `pending` and
  `failed`, and is a no-op on `terminated`.
  Receipts (latest placement wins): `UploadStore.latest_placements(collection, keys)` returns, per
  key, the `placed` or `committed` upload with the greatest `(placed_at, id)`, whoever made it
  (PostgreSQL `distinct on`). An add is proved only when that row is `placed`, is the
  committer's, has the identical `rel_path` (stricter than the key, so the placed name is the
  recorded name), the add's size and sha256, and is younger than `upload_ttl`; otherwise
  `UPLOAD_RECEIPT_MISSING`. Consuming marks only the proving row `committed` with the commit's
  id; the committer's older `placed` rows of the key are left as they are: no longer the latest,
  they prove nothing and expire. `Upload.proves` takes the committer and is asked only of the
  latest placement. The old `placed(collection, keys, created_by)` query is gone; `placed(collection)`
  lists a collection's placed uploads for the collection delete.
  Removals: a `Removal` row carries `path` (`<collection disk path>/<rel_path>`, as reported by
  the views), a nullable `collection_id` (`on delete set null`) and a nullable `commit_id`
  (`on delete set null`, since a deleted collection takes its commits with it; `null` too for
  rows queued by a collection delete). `Collections.delete` queues, in its
  transaction, one removal per `placed` upload of the collection (`Upload.removal`, sha256 from
  the receipt, no commit); the collection's upload rows then cascade. A commit's removal rows name
  the removing commit. Both build them with `Removal.of`, and `uploads.models.file_path` is the one
  join of a collection directory and a `rel_path` (removals and `Destination.path`).
  Lock order (the amendment's "Lock order" bullet): the collection row, then upload rows, then
  removal rows. `begin` locks the collection row (`find_collection(..., lock=True)`), then inserts
  the upload. A collection delete at the same time either finds the new upload and drops it, or
  makes `begin` fail with the collection's `NOT_FOUND`. `receipt` reads the upload, locks its
  collection, then locks the upload. A collection that was deleted meanwhile took the upload with
  it, so the receipt fails with `UPLOAD_NOT_FOUND`. Thus a receipt either commits before the delete
  reads the placed uploads (and the delete queues its removal), or waits and finds nothing. `fail`
  and `terminate` lock the upload row only. They change only unplaced rows, which commits and
  deletes do not read. `placement`, `get` and `removal_still_valid` lock nothing.
  `claim_removals` claims removal rows with `for update skip locked`. `test_postgres_races.py`
  forces the delete-first interleaving of `begin` and of `receipt`, and runs `begin` and a delete
  together. `claim_removals(limit)` bounds `limit` with `clamp_limit` (1..500, default
  100), re-claims a claim older than `REMOVAL_LEASE` (15 minutes) and returns
  `ClaimedRemoval(removal, share_root)`, its `path` from the row and `share_root` from the row's
  organization (the path's first segment), so the sidecar needs no collection.
  `removal_still_valid` resolves the settled collection now at the row's directory (the path
  minus `rel_path`: identifier from the path's segments, then the collection's disk path must
  equal the directory), whether the row's own collection or one created there since; no such
  collection means valid. Otherwise the removal is invalid when that collection records the key
  or the key's latest placement is `placed` and younger than `upload_ttl`. Cancellation and
  validity compare `rel_path_key`; a commit deletes the removal rows of re-added keys of its own
  collection whether or not they are claimed.
  Persistence: `uploads.commit_id` and `removals.commit_id` reference `commits.id` with
  `ix_uploads_commit_id` and `ix_removals_commit_id`; `uploads.commit_id` keeps `files.commit_id`'s
  default `no action` (its rows go with the collection in the same statement), `removals.commit_id`
  is `set null` so a removal survives. `uploads` checks `ck_uploads_receipt` (placed or committed
  have `sha256` and `placed_at`), `ck_uploads_commit` (`(state = 'committed') = (commit_id is not
  null)`) and `ck_uploads_failure` (failed has `failure`). The domain never writes a row that
  breaks them, the memory store does not re-check them, and
  `tests/contract/test_postgres_constraints.py` proves PostgreSQL refuses such rows and unknown
  commits. Only the lake's codes are registered here (`UPLOAD_NOT_FOUND`,
  `UPLOAD_STATE_CONFLICT`, `UPLOAD_SIZE_MISMATCH`, `UPLOAD_TOO_LARGE`, `UPLOAD_RECEIPT_MISSING`,
  each with a row in `docs/api-errors.md`); `UPLOADS_DISABLED`, `INGEST_FORBIDDEN` and
  `UPLOAD_OUTSIDE_LAKE` belong to M11.2 and M11.4. The repository has no `migrations/schema.sql`:
  the schema map is the SQLAlchemy tables, checked by `scripts/check_schema_map.py`;
  `metastore/tables.py`'s `load_all` now imports the areas by name. `FileStore` gained
  `get_many` (the commit reads the removed rows' recorded `rel_path` and `sha256` for the outbox),
  and `lookups.collection_path` gives a settled collection's directory. Tests use
  `tests/support/lake.py`'s `placed_upload`, `commit_uploaded` and `settled_collection` (all take
  a `Lake`).
  (Revision of 2026-11-06.) M11.2 folds `removals` into `disk_tasks` inside `0003_uploads`, so no
  released schema has a `removals` table.
  (Revision v3 of 2026-11-06, corrected 2026-11-07.) M11.2 extends `0003_uploads` in place with
  `uploads.inode`, `removals.inode`, `files.inode`, `catalogs.share_group` and the new
  `ck_uploads_inode`, so no released schema lacks them. This replaces the revision note of
  2026-11-06 above: the `removals` table stays, and no `disk_tasks` table exists.

#### M11.2 Persistence for inodes and share groups

- Intent: the amendment's "Persistence", the inode columns and `catalogs.share_group` in the lake
  and the stores, and the delete results that give the API its disk work. No setting, no route
  and no disk work yet.
- Create or change:
  - `migrations/versions/0003_uploads.py`, edited in place: `uploads.inode`, `removals.inode`,
    `files.inode` (all `bigint null`), `catalogs.share_group` (`text null`), and
    `ck_uploads_inode`: `(state in ('placed', 'committed')) = (inode is not null)`. The
    downgrade drops them. `src/huron/core/metastore/uploads/tables.py`, `files/tables.py`,
    `catalogs/tables.py` and their `postgres.py` and `memory.py` follow.
  - The inode conversion: `st_ino` is unsigned 64-bit. `src/huron/core/metastore/rows.py` gets
    `signed_inode` (`ino - 2**64` when `ino >= 2**63`) and `unsigned_inode` (the reverse). The
    PostgreSQL stores of `uploads`, `removals` and `files` call them on write and on read. The
    domain and the memory stores hold the unsigned value.
  - `src/huron/core/lake/uploads/models.py`: `Upload.inode`, `Removal.inode`, `Removal.of(...,
    inode=)`, `Upload.removal` carries the receipt's inode, `Destination(path, share_root)`
    without `groups` and without `declared`. `operations.py`: `Uploads.receipt(upload_id, size,
    sha256, inode)`. A receipt for a row that is already `placed` with the same
    `(size, sha256)` keeps the first inode and succeeds. The module docstring loses the sidecar
    and the ingest secret.
  - `src/huron/core/lake/files/models.py`: `FileRecord.inode`, `CommitResult.removals` (not
    rendered). `commits.py`: the proving receipt's inode goes into the record. The removal rows
    carry the removed record's inode and `claimed_at` = now. `CommitResult.removals` carries
    those claimed rows. `UploadStore.insert_removals` accepts claimed rows.
  - `src/huron/core/lake/collections/lifecycle.py`: `Collections.delete` returns
    `DeletedCollection(disk_path, removals)`. `removals` are the claimed removal rows of the
    placed uncommitted uploads, with the inode of each receipt.
    `src/huron/core/lake/namespaces/operations.py` and `catalogs/operations.py`: the namespace
    delete and the catalog delete return their `disk_path`.
  - `src/huron/core/lake/catalogs/`: `Catalog.share_group`, `CatalogView.as_dict` reports it,
    `Catalogs.create(..., share_group=)`, `Catalogs.set_share_group(actor, name, group)`
    (`CATALOG_GRANT_ADMIN` on the catalog, `tx.lock_catalog`, then a new read of the catalog,
    version + 1, `Action.CATALOG_SET_SHARE_GROUP` in `core/lake/audit/models.py`). `create` and
    `set_share_group` check the name against `^[A-Za-z_][A-Za-z0-9_.-]{0,31}$` (422
    `REQUEST_INVALID`). `assign_schema` reads the catalog after `tx.lock_catalog`, not before.
    `CatalogStore.update` writes the column and raises the catalog's not-found error when no row
    matches.
  - Tests: `tests/unit/lake/test_uploads.py` (the inode on receipts, a repeated receipt keeps the
    first inode), `tests/unit/lake/test_commits.py` (the inode on records and removals, claimed
    rows in `CommitResult.removals`), `tests/unit/lake/test_collections.py`
    (`DeletedCollection`), `tests/unit/lake/test_schemas_and_catalogs.py` (create, set and clear
    the share group, the privilege, the name pattern, the audit entry), `tests/contract` (the
    suite over memory and PostgreSQL for the new columns, an inode above `2**63` that comes back
    unchanged, `test_postgres_constraints.py` for `ck_uploads_inode`, `test_migration.py` for
    the edited upgrade and downgrade, `test_postgres_races.py` for the share-group change against
    a schema assignment and against a catalog delete).
- Verification: `make gate`; `uv run pytest -m contract`.
- Dependencies: M11.1.
- Status: complete
- Execution notes: `Collections.delete` returns `DeletedCollection | None`: `None` for a dry run
  (nothing to do on disk), and `disk_path` is `None` for a draft. The namespace delete returns
  `NamespaceView.disk_path`; the catalog delete returns the new, unrendered `CatalogView.disk_path`
  (`<organization>/<catalog>`). `Removal.of` always claims the row at `now`, so every removal
  that a commit or a delete writes belongs to that request until `REMOVAL_LEASE` passes.
  `CatalogNotFound` (a `NotFound`, code `NOT_FOUND`) in `core/lake/catalogs/errors.py` is the
  catalog's not-found error: `find_catalog`, the re-read after `tx.lock_catalog` and both
  `CatalogStore.update` adapters raise it. `Catalogs.set_share_group` raises the version on every
  call, also when the group is unchanged; its audit detail is `{share_group, previous}`.
  `Uploads.receipt` stores the inode as given (the API takes it from `fstat`). `Destination.as_dict`
  and `ClaimedRemoval.as_dict` are gone: nothing renders them now. The PostgreSQL bulk inserts
  build one tuple per row and transpose it with `metastore.rows.columns`. The new audit action
  `catalog.set_share_group` is in the web's closed vocabulary (`web/src/lib/api/types.ts`, the
  label and summary in `web/src/lib/activity.ts`, docs/web-design.md §4.4). The web's vitest run
  passes in this worktree: 130 test files and 1646 tests.

#### M11.3 Settings, LakeDisk and the storage ports

- Intent: the amendment's "Settings" and "Lake path", the API's hold on the lake, the mode-based
  storage ports, and the share-group route. No upload route and no disk work in a verb yet.
- Create or change:
  - `src/huron/applications/api/settings.py`: `lake_path`, `mount_prefix`, `uploads_url`,
    `upload_receipts`, `upload_ttl`, `upload_max_size`, `upload_hook_timeout` (default 15
    minutes, at most 55 minutes), `removal_interval`, `sweep_interval`, `service_uid`,
    `service_group`, and the startup error for `uploads_url` without `lake_path`.
  - `src/huron/applications/api/runtime.py`: `LakeSettings` from the settings in place of the
    fixed `ReceiptMode.OPTIONAL`. Without `lake_path` the runtime uses `optional` whatever
    `upload_receipts` says, because no route can issue a receipt. With `lake_path` the setting
    applies (default `required`). `Runtime.disk: LakeDisk | None`, `ready()` with `lake`.
  - `src/huron/core/storage/layout.py`: `ORGANIZATION_MODE` (`0o2751`), `DIRECTORY_MODE`
    (`0o2750`), `FILE_MODE` (`0o644`), `UPLOAD_DIR_MODE` (`0o700`), `mode_of(kind)`.
  - `src/huron/core/storage/ports.py`: `ShareReader` (`read_bytes`, `exists`, `is_directory`,
    `walk`, `stamp`, `hash`, `owner` returning `(uid, gid, mode)`, `device(path) -> int`) and
    `Storage(ShareReader)` with `make_directory(path, mode)`, `set_mode`,
    `set_group(path, group) -> GroupResult`, `write_bytes`, `remove_file`, `remove_directory`.
    `GroupResult(outcome: GroupOutcome, reason: str | None)` with `GroupOutcome` `CHANGED |
    UNCHANGED | PENDING`, and `ShareWarning(code, group, detail)`. No class is named `Warning`.
    `PosixStorage` and `MemoryStorage` implement them. `MemoryStorage` simulates mount points for
    `device`. The plan-based methods stay until M11.9.
  - `src/huron/applications/api/disk.py`: `LakeDisk(storage, lake_path, mount_prefix,
    instance_id, declarations, locks)` with `open()` (creates `.tus-uploads` mode `0700`),
    `ready()`, `place_of(organization)`, `check_marker(place)`, `resolve(relative) -> Path`
    (`OUTSIDE_LAKE` for a path outside `lake_path` or on another filesystem, by `device`;
    `LAKE_UNAVAILABLE`), `run(path, callable)` (the per-path lock around a worker thread), and
    `set_share_group(catalog_path, group) -> ShareWarning | None`. `ready()` runs the lake probe
    in a thread with a 2 s bound and caches the result for 10 s. A probe that does not return in
    time reports `lake: false`.
  - `src/huron/core/storage/locks.py`: `PathLocks`. `src/huron/core/storage/errors.py`:
    `OUTSIDE_LAKE` 422 and `LAKE_UNAVAILABLE` 503.
  - `src/huron/applications/api/routes/health.py`: `GET /healthz` reports `uploads_url`,
    `service_user` (`{"uid": U, "gid": <os.getgid()>, "group": "<service_group>"}`) and
    `upload_hook_timeout` in seconds. `GET /readyz` adds the `lake` check from `LakeDisk.ready()`.
  - `src/huron/applications/api/routes/v1/endpoints/catalogs.py` and
    `routes/v1/schema/catalogs.py`: `CatalogIn.share_group`, `CatalogOut.share_group`,
    `PATCH /catalogs/{catalog}` with `ShareGroupIn` and no `If-Match` (the catalog lock
    serializes it, like the namespace PATCH). The create and the PATCH answer `CatalogWriteOut`
    (the `CatalogOut` fields plus `warnings: list[ShareWarningOut]`). `GET` keeps `CatalogOut`.
    The `chgrp` attempt goes through `LakeDisk` and is a no-op without `lake_path`.
  - `pyproject.toml`: the contract "the API does not import the CLI or storage" becomes "the API
    does not import the CLI". The contract "lake areas never import another area's operations"
    adds `huron.core.lake.uploads.models` to its sources and
    `huron.core.lake.uploads.operations` to its forbidden modules. `AGENTS.md` line 37 (the
    dependency rules) says the same.
  - `make openapi`, `docs/api-errors.md` (`OUTSIDE_LAKE`, `LAKE_UNAVAILABLE`, and the
    `STORAGE_FAILED` row reworded: the API reports it for disk work), the web's
    `npm run generate:api`.
  - Tests: `tests/unit/api/test_settings.py` (each setting and its default, the 55-minute cap,
    `uploads_url` without `lake_path`, the effective receipt mode with and without `lake_path`),
    `tests/unit/api/test_service.py` (`/healthz` with `service_user` and `upload_hook_timeout`,
    `/readyz` with a temporary lake, with a lake that is not writable, with a probe that does not
    return within 2 s, and without a lake), `tests/unit/api/test_catalog_share_group.py`
    (create, set and clear through the routes, `CatalogWriteOut`, the `SHARE_GROUP_PENDING`
    warning), `tests/unit/storage/test_storage.py` (modes, the `set_group` outcomes, `device`),
    `tests/unit/api/test_lake_disk.py` (`resolve` inside and outside the lake, another
    filesystem on `MemoryStorage`, the marker, the lock).
- Verification: `make gate`; `uv run pytest tests/unit/api/test_openapi_snapshot.py
  tests/unit/test_error_contract.py`; from `web/`, `npm run check` and `npm test`.
- Dependencies: M11.2.
- Status: complete
- Execution notes: `LakeDisk` already runs every disk call, the probe included, in its own
  `ThreadPoolExecutor` of 8 workers (`DISK_WORKERS`), as the amendment's "Lake path" requires, so
  M11.5's change of `run` to a dedicated pool is done; `Runtime.close()` shuts the pool down.
  `resolve`, `check_marker`, `run`, `open`, `ready` and `set_share_group` are coroutines that hop to
  that pool. `run` keeps the path lock until its action returns, also when the caller is cancelled,
  because a worker thread cannot be stopped, and logs `disk.cancelled_action_failed` (path and
  error) when that action then raises; `PathLocks` forgets a cancelled waiter.
  `set_share_group(catalog_path, group)` takes the relative `<org>/<catalog>` path, resolves it,
  then checks the marker and runs `Storage.set_group` under the path lock; M11.5 moves the `resolve`
  before the transaction. `group=None` gives the directory back the service group `G`
  (`LakeDisk(..., service_gid=)`, `os.getgid()` in the runtime), which `U` can always give;
  `Storage.set_group` takes a name or a gid. The create calls it only with a share group, since a
  new catalog directory inherits `G`. The PATCH calls it on every change with a lake, so a clear
  (`null`) resets the group to `G`, and a failed reset answers `SHARE_GROUP_PENDING` with `group` =
  the gid of `G` as text. Until M11.5 makes the catalog directory, a create with a share group on a
  lake answers `SHARE_GROUP_PENDING` with `<path>: No such file or directory`. Any refused or failed
  `chgrp` is `PENDING` with the reason (`GroupResult.unknown(group)` for a name the machine cannot
  resolve). `/readyz` adds `lake` only when the service has a lake; without `lake_path` the checks
  stay `database` and `signing_keys`. The probe writes and removes
  `.tus-uploads/.huron-ready-<uuid>`; while a hung probe still runs, `ready()` awaits it again
  instead of starting another. A `lake_path` that is not a directory, or in which `open()` cannot
  make `.tus-uploads`, stops startup with `LAKE_UNAVAILABLE`. `build_runtime(..., disk=)` takes a
  `LakeDisk` in place of the one built from `lake_path` (tests use `tests/support/disk.py`:
  `memory_lake`, `memory_disk`, `StalledStorage`). Settings: durations take seconds (a number, also
  as text) or ISO 8601; `lake_path` and `mount_prefix` must be absolute without `..`; an unset
  `mount_prefix` stays `None` and the runtime gives `LakeDisk` `lake_path` in its place;
  `Settings.receipt_mode` is the effective mode. `ShareReader.owner` returns `Ownership(uid, gid,
  mode)`. `MemoryStorage` gained `uid`, `gid`, `groups` (the group database), `member_of`, `mounts`
  and `mount(path, device)`; its `make_directory` gives a new directory the group of a setgid parent
  and, like `chmod`, drops setgid outside `member_of`; its `write_bytes` gives a new file the group
  of a setgid parent too. `PosixStorage.apply_plan` sets its group through `set_group`. The web's
  catalog decoder (`web/src/lib/server/huron-api.ts`) and `catalogFixture` carry `share_group`.

#### M11.4 Placement, the hooks route and the auth route

- Intent: the amendment's "Upload flow" and "Authorization in front of tusd" on the API side, with
  the `pre-finish` sequence of "Upload flow" step 2.
- Create or change:
  - `src/huron/pkg/fs/posix.py`: `link_into_place(source, destination, part_name)` (`link`; on
    `EEXIST` a `link` to the part name beside it, on `EEXIST` there an unlink of the part and a
    new `link`, then a `rename` over the destination), with `fsync` of the directory, `inode(path)`,
    and `make_inheriting_dir(path)` (`mkdir(path, 0o750)`, then `stat`: a missing `S_ISGID` or a
    group other than the parent's raises; never a `chmod`). `pkg/fs/posix.make_dir` is not used
    below a catalog.
  - `src/huron/core/storage/ports.py`: `Storage.link`, `Storage.inode` and
    `Storage.make_inheriting_dir`. `PosixStorage` and `MemoryStorage` implement them.
  - `src/huron/core/storage/placement.py`: `Placer(storage, lake_path)` with one method per disk
    step of "Upload flow" step 2. `measure(upload_file, size) -> Measured(size, sha256, inode)`
    opens the file read-only, takes the size and the inode from `fstat` on the descriptor, raises
    `UPLOAD_SIZE_MISMATCH` when the size differs, hashes from the descriptor and runs `fchmod
    0644` on it. It returns `None` on `ENOENT`. `link(source, info_file, destination,
    collection_dir, upload_id) -> Linked(made_dirs)` requires the collection directory (it never
    creates it), makes the missing intermediate directories with `make_inheriting_dir`, calls
    `link_into_place`, and unlinks the source and the `.info` (`ENOENT` is not an error). It
    raises `SourceGone` on `ENOENT` of the link source. `undo(destination, inode, made_dirs)`
    unlinks the destination when its inode equals the placed inode and removes the empty
    directories that `link` made. `measure_destination(destination, size)` serves the idempotent
    branch.
  - `src/huron/applications/api/disk.py`: `place(destination, upload_id, size)`: `resolve` and
    `check_marker`, `measure` in a worker thread outside every lock, then under the in-process
    lock on the destination path `link` and `Uploads.receipt(id, size, sha256, inode)`. A
    receipt that raises `UploadNotFound` or `UploadStateConflict` calls `undo` under the same
    lock and answers the domain error's status (404 or 409). A missing collection directory is a
    definitive refusal: `Uploads.fail` with `STORAGE_FAILED` and the hint `huron adm repair`.
    `SourceGone` or `None` from `measure` goes to the idempotent branch: re-read the row; `placed`
    answers as step 1; `pending` with a destination of the declared size runs
    `measure_destination` and the receipt; anything else answers 500 `STORAGE_FAILED`.
  - `src/huron/applications/api/routes/v1/endpoints/uploads.py` and
    `routes/v1/schema/uploads.py`: the tusd v2 hook bodies (`HookRequest`, `HookResponse`,
    `HTTPResponse`, `RejectUpload`, `RejectTermination`, `ChangeFileInfo`).
    `POST /api/v1/uploads/hooks` verifies the token inside the route. `pre-create` refuses with
    `RejectUpload: true` and `HTTPResponse`. `pre-finish` first calls `Uploads.get(actor, id)`:
    `placed` or `committed` answers success with the stored `Huron-Upload-Id` and `Huron-Sha256`
    and does no disk work; `failed` or `terminated` answers the refusal `UPLOAD_STATE_CONFLICT`
    409. Then `Uploads.placement(actor, id)` and `LakeDisk.place`. A `pre-finish` refusal is an
    `HTTPResponse` only (the hook has no reject field). `pre-terminate` refuses with
    `RejectTermination: true` and `HTTPResponse`. `LAKE_UNAVAILABLE` answers 503 and
    `STORAGE_FAILED` 500 from the route, so tusd calls the hook again inside its one timeout. A
    zero-length upload finishes in the creation POST, so its `Huron-Sha256` comes with the POST
    response. `GET /api/v1/uploads/auth` has the three rules of the amendment and no `OPTIONS`
    rule (nginx answers `OPTIONS` without `auth_request`), with `WWW-Authenticate: Bearer` on
    401. `GET /api/v1/uploads/{id}`. `UPLOADS_DISABLED` in `dependencies.py`
    (`require_uploads`). `routes/v1/router.py`, `make openapi`, `docs/api-errors.md`
    (`UPLOADS_DISABLED`), the web's `npm run generate:api`.
  - Tests: `tests/unit/api/test_upload_hooks.py` over a temporary lake (a fresh upload placed and
    received, an overwrite through the part file, a stale part file, a retried `pre-finish`
    after the receipt, two attempts of one id interleaved, a size from `fstat`, a receipt
    failure after the link when the collection is deleted and when the creator terminates during
    the hash, a missing collection directory, a size mismatch, a path outside the lake, a wrong
    marker, a missing token, another user's upload, a deferred length, a zero-length upload, a
    terminate, the response fields of each hook), `tests/unit/api/test_upload_auth.py` (each
    rule, 401 with `WWW-Authenticate`, 403, a non-UUID id, `OPTIONS` treated as any other
    method, uploads disabled), `tests/unit/storage/test_placement.py` (every method, idempotent
    repeats, an inode above `2**63` on `MemoryStorage`), `tests/unit/pkg/test_posix.py`
    (`link_into_place`, `make_inheriting_dir` with and without an inherited group).
- Verification: `make gate`; `uv run pytest tests/unit/api/test_openapi_snapshot.py
  tests/unit/test_error_contract.py`; from `web/`, `npm run check` and `npm test`.
- Dependencies: M11.3.
- Status: complete
- Execution notes: measuring needs one descriptor for `fstat`, the hash and `fchmod`, so the
  storage port gained a fourth method, `Storage.open_file(path) -> OpenFile | None` (`size`,
  `inode`, `sha256()`, `set_mode()`, `close()`; `None` on `ENOENT`). `Storage.link` returns
  `False` when the source is gone, `Storage.inode` returns `None` for a missing path, and
  `make_inheriting_dir` returns whether it made the directory (an existing one is adopted); a
  directory that did not inherit setgid and the group is removed again before
  `pkg.fs.posix.InheritanceError` (an `OSError`, so `STORAGE_FAILED`) is raised, so a retry
  cannot adopt it. `link_into_place` removes the part file after the `rename`, because a
  `rename` between two links of one inode does nothing. `Placer(storage, lake_path)` also gives
  `upload_file(id)` and `info_file(id)`. `LakeDisk.place(uploads, actor, upload, destination)`
  takes the `Uploads` operations, the actor for the re-read and the `Upload` (its `rel_path`
  gives the collection directory). The link, the receipt, the undo and the whole idempotent
  branch run in one hold of the destination's path lock (`LakeDisk._hold`, which `run` now uses
  too), so a cancelled caller still waits for the receipt. The hooks route answers a refusal for
  every 4xx and for `CollectionDirectoryMissing`; every other 5xx is an HTTP error that tusd
  retries. A refusal's `Body` is the problem document as JSON text (tusd's `HTTPResponse.Body`
  is a string), with `instance` the tus request URI; a finished upload's answer sets only
  `Header`, so tusd keeps its own status. The missing-directory hint is `run huron adm repair
  for the collection` (the placement does not know the identifier). The auth route requires the
  canonical lowercase UUID and answers rules 2 and 3 with one 403 (`the path names no upload`);
  every 401 carries `WWW-Authenticate: Bearer`. `UPLOAD_SIZE_MISMATCH` now reads `but the file
  has N bytes`. Tests: `tests/support/disk.py`'s `memory_disk` is `lake_disk` (any `Storage`,
  `service_gid=`) with `PausingStorage`; `tests/support/tusd.py` has `FakeTusd`,
  `UploadTarget` and `upload_target`; `tests/support/api.py` has `active_collection`.

#### M11.5a The hash pool and the overwrite backup

- Intent: commit the two verified parts of the escalated M11.5 tree and nothing else of it. These
  are the separate hash pool and the overwrite backup of "Upload flow" sub-steps 5 to 7. They touch
  no containment code. First record the whole tree on a reference branch.
- Create or change:
  - Record the tree: `git switch -c m11.5-escalated`, `git add -A`, then `git commit -m "Record
    the escalated M11.5 tree (reference only)"`. Then `git switch tusd-integration`. Its working
    tree is clean at its last commit (5800e25a). Do not delete the branch. No task deletes it; the
    orchestrator deletes it after M11.5e, when the user confirms.
  - Keep four files from the branch: `git checkout m11.5-escalated -- IMPLEMENTATION_PLAN.md
    CONTEXT.md docs/adr/0008-uploads-through-tusd.md architectural_review.md`.
  - Re-apply only these hunks of `git diff 5800e25a m11.5-escalated`. Copy hunks, not whole files:
    - `src/huron/applications/api/disk.py`: `HASH_WORKERS = 4`, `_hash_pool`, `_hash`, both pools
      shut down in `close()`; `Placer.measure` and `measure_destination` on the hash pool; the
      backup drop after a successful receipt in `_settle` and in `_replay`. Where a hunk calls
      `self.hold` or `self.call`, keep the 5800e25a names `self._hold` and `self._call`.
    - `src/huron/pkg/fs/posix.py`: `link_into_place(source, destination, part_name, backup_name)
      -> Path | None`, `_replace` and `_link_afresh`, with the same-inode case and the left-over
      backup.
    - `src/huron/core/storage/ports.py`: `Storage.link(..., backup_name)` and `Storage.rename`;
      both in `posix.py` and `memory.py`; the backup of `MemoryStorage.link`.
    - `src/huron/core/storage/placement.py`: `Linked` with the backup, `backup_file`,
      `drop_backup`, `undo(destination, inode, linked)`. `SourceGone` moves to
      `src/huron/core/storage/errors.py`.
    - `src/huron/schema/naming.py`: `BACKUP_SUFFIX = ".huron-prev"`, reserved like the part
      suffix. `src/huron/core/storage/layout.py`: `is_reserved_entry` counts `BACKUP_SUFFIX`.
    - `tests/support/disk.py`: `PausingStorage.pause_next`. `tests/support/tusd.py`: what the
      backup tests need.
  - Facts that move here from M11.5's execution notes: `link_into_place` and `MemoryStorage.link`
    leave a destination that already links the source's inode alone. They return the backup that
    an interrupted earlier attempt left, so `undo` after a crash between the `rename` and the
    cleanup still puts the replaced bytes back. `Placer.undo` also removes its backup when the
    destination changed since the link.
  - Not brought back (each comes back only when its later task rebuilds it on the final design):
    `routes/directories.py`, `routes/v1/endpoints/repairs.py`, `routes/v1/schema/repairs.py`,
    `core/lake/repairs/`, `core/storage/directories.py`, `LakeDirectory`, the async
    `LakeDisk.locate`, `resolve` changes, `_visible`, `verify_marker` in `LakeDisk`,
    `directory_group`, `repair*`, `walk(on_error)`, `_listing`, `_kind`, `_fail`,
    `posix.exists`, `_lstat`, the `StorageError` mapping of each query of `PosixStorage`,
    `in_group`, `GroupResult.warning`, `InheritanceFailed`, the new lake reads, the lines in
    `pyproject.toml`, `temporary_mode` in `tests/conftest.py`, the tests of the verbs and repair,
    `docs/openapi.json` and `web/src/lib/api/openapi.ts` (both stay at 5800e25a).
  - Tests, as verified in the tree: the backup cases of `tests/unit/pkg/test_posix.py` and
    `tests/unit/storage/test_placement.py` (a backup made on an overwrite and not on a new name, a
    stale backup replaced, the same-inode case, undo restoring the old bytes and inode); the
    `link` and `rename` cases of `tests/unit/storage/test_storage.py`; the backup line of
    `tests/unit/schema/test_naming.py`; the overwrite cases of
    `tests/unit/api/test_upload_hooks.py` (an overwrite refused after the link by a collection
    delete and by a terminate during the hash leaves the old bytes and inode and no backup; a
    successful overwrite leaves no backup; a replay after a crash between the `rename` and the
    receipt removes the backup). The terminate case overwrites a committed file. A collection
    with recorded files cannot be deleted, so the delete case overwrites a placed, uncommitted
    upload. Both upload the first file through the hooks, and `PausingStorage.pause_next` pauses
    the second hash. The pool case of `tests/unit/api/test_lake_disk.py`: with all 4 hash workers
    blocked, `ready()` answers in time and a disk call completes; it queues `DISK_WORKERS + 1`
    placements, so one shared pool would starve the probe.
- Verification: `make gate`; `git branch --list m11.5-escalated` prints the branch;
  `git status --short | grep -E "routes/directories\.py|repairs|core/storage/directories\.py|pyproject\.toml|tests/conftest\.py|openapi\.(json|ts)|test_directory_verbs|test_directories"`
  prints nothing;
  `grep -rnE "\bon_error\b|\bin_group\b|LakeDirectory|\bRepairs\b|\bdirectory_group\b|temporary_mode|InheritanceFailed|\b_lstat\b" src/huron tests`
  prints nothing; `uv run pytest tests/unit/pkg/test_posix.py tests/unit/storage/test_placement.py
  tests/unit/api/test_upload_hooks.py tests/unit/api/test_lake_disk.py` passes.
- Dependencies: M11.4.
- Status: complete

#### M11.7 Push through tusd in the CLI

- Intent: the amendment's push ("The CLI"), and the removal of the NFS-copy path of version 1. After
  this task `huron push` uploads through tusd and writes nothing to the lake.
- Create or change:
  - `src/huron/applications/cli/uploads.py`: the tus client (create, `HEAD`, `PATCH` in 64 MiB
    chunks with a progress line, local sha256, the `Huron-Sha256` comparison, the 401 and 403
    hints). On a 500, 502 or 504 from the final PATCH it reads `GET /api/v1/uploads/{id}`.
    `placed` or `committed` with the local hash is success. `pending` is polled every 5 s for at
    most `upload_hook_timeout` (from `GET /healthz`). Then the CLI reports the upload as not placed
    and starts a new upload on the next push. `failed` prints the failure. A zero-length file
    finishes in the creation POST, so the CLI reads `Huron-Sha256` from the POST response.
  - `src/huron/applications/cli/sync.py`: `push` uploads instead of copying. It records
    `upload_url` and `upload_id` in the stage, skips placed uploads on a retried push, needs no
    mount and unlinks nothing. The copy step, the unlink loop, the "copied" line, the `FileStamp`
    use and `_copy_files` go. `_commit_body` takes each add's `sha256` from `Huron-Sha256`. The
    `os.walk` in `_collect` stays: it walks the user's local source folder for push staging, not
    the lake. `src/huron/applications/cli/state.py`: the `StagedAdd` fields `upload_url` and
    `upload_id`. No stage file outlives the test bed, so no old stage format is read.
  - Gone: `Storage.copy_in` in `core/storage/ports.py`, `PosixStorage` and `MemoryStorage`;
    `pkg.fs.posix.atomic_copy`; `pkg.hashing.sha256_copy` and its two tests in
    `tests/unit/pkg/test_small.py`; `PosixStorage._make_dir` and `_COPY_DIRECTORY_MODE`;
    `pkg.fs.posix.PART_SUFFIX` (`atomic_write` takes the part suffix from its caller, which passes
    `schema.naming.PART_SUFFIX`); `schema.naming.part_name` and its test in
    `tests/unit/schema/test_naming.py`.
  - `src/huron/applications/api/settings.py`: the setting `upload_receipts` goes. With
    `lake_path`, `Settings.receipt_mode` is `ReceiptMode.REQUIRED`; without it, `OPTIONAL`.
    `ReceiptMode` stays a parameter of `core/lake/bootstrap.py` for the API without a lake and for
    the seeds. The field `LakeSettings.upload_receipts` in `core/lake/bootstrap.py` becomes
    `receipt_mode`. `src/huron/applications/api/runtime.py` passes `receipt_mode=`.
    `tests/unit/lake/test_commits.py` and every seed that names the field follow.
    `tests/unit/api/test_settings.py` follows.
  - CLI messages and hints in strict STE. `uv run python scripts/cli_reference.py` output
    regenerated.
  - `tests/support/tus.py`: a shared fake tus server (`httpx.MockTransport`). It places files into
    `MemoryStorage` and records receipts through the in-process API, so the status and check tests
    keep their data.
  - Tests: `tests/unit/cli/test_push_tusd.py` over the fake tus server (a fresh upload, a resume
    after a dropped PATCH, a hash mismatch, a 500, a 502 and a 504 followed by `placed`, `pending`
    and `failed`, an empty file, a 403 and a 401 from the proxy, uploads disabled, a retried push
    that skips placed files). Moved to the fake tus server: `tests/unit/cli/test_collections.py`,
    `test_edges.py`, `test_managed_service.py`, `test_declared_organizations.py`,
    `test_status.py`, `test_panels.py` and `test_check_and_acl.py`. The adapter tests
    `tests/unit/storage/test_storage.py` and `tests/unit/pkg/test_posix.py` lose their `copy_in`
    and `atomic_copy` cases. `tests/unit/cli/test_push_preflight.py` is kept.
  - `tests/integration/test_cli_end_to_end.py` is marked skipped with the reason "rewritten by the
    dev-stack task". M11.10 removes the mark.
- Verification: `make gate`;
  `grep -rnE "\bcopy_in\b|atomic_copy|sha256_copy|_make_dir\b|_COPY_DIRECTORY_MODE|\bpart_name\(|_copy_files" src tests scripts`
  prints nothing; `grep -n "PART_SUFFIX\|huron" src/huron/pkg/fs/posix.py` prints nothing;
  `grep -rn "upload_receipts" src tests scripts huron.dev.yaml` prints nothing; `grep -rn "ReceiptMode.OPTIONAL" src/huron/applications` prints only the line without
  a lake in `Settings.receipt_mode`; `grep -n "os\.walk" src/huron/applications/cli/sync.py`
  prints only the line in `_collect`; `uv run python scripts/cli_reference.py --check`.
- Dependencies: M11.5a (both change `pkg/fs/posix.py` and the upload tests).
- Status: complete

#### M11.8a The CLI writes nothing to the lake

- Intent: the write half of the old M11.8. Every CLI directory verb, `activate`, `set meta` and
  `delete` calls the API only. The write grep below enforces it. M11.9a types the CLI's storage as
  the read-only `ShareReader`, because `adm check` and `provision-orgs` need the writable
  `Storage` until their ACL code goes. This task adds no feature: the share-group options and
  `adm repair` stay in M11.8.
- Create or change:
  - `src/huron/applications/cli/commands/create.py`, `delete.py`, `change.py` and `common.py`
    (`activate`): call the API only, with no `Mount` write and no marker check before a change.
    Gone: the `mount.ensure` and group arguments of `create.py`; `activate`'s `mount.ensure` and
    `write_sidecar`; `huron set namespace`'s `mount.apply`; `common.kind_of`; in `delete.py`,
    `_empty_directory`, `_refuse_unrecorded`, `_organization_directory`, `_KEPT`, the
    `mount.path` pre-check and the `mount.remove` of `delete namespace`, `catalog` and `org`.
    `huron delete collection` checks no unrecorded file and keeps the commit of its removes. Its
    help says that the API unlinks only the files that it recorded or placed, and that any other
    file stays with a `dir_unrecorded` finding.
  - `src/huron/applications/cli/sync.py`: `write_sidecar` goes.
  - `src/huron/applications/cli/inventory.py`: the module docstring (line 1 at 5800e25a) names
    ``adm check`` and ``tree`` only, not ``adm apply-acl``. The code of the module stays until
    M11.9a.
  - `src/huron/applications/cli/mount.py`: `ensure`, `apply`, `remove`, `report` and
    `catalog_groups` go. The read side stays (`path`, `verify`, `verify_catalog`, `verify_prefix`,
    `base`, `place`, `place_of_view`, `prefix_state`). `organization_groups` stays, because the
    ACL plans of `adm.py` (`_organization_plan`, `_target`) use it until M11.9a. `Mount.storage`
    and `Services.storage_factory` keep the type `Storage` until M11.9a.
  - `src/huron/applications/cli/commands/adm.py`: `apply-acl` and `_selected` go; `grant` and
    `revoke` lose `_remind`; `declared_groups_hint` loses its ACL sentences (the 409 hint names
    no ACL step).
  - The web: the `adm apply-acl` hint goes from `web/src/lib/cli.ts` and from
    `web/src/routes/(app)/catalogs/[catalog=segment]/(overview)/cli/+page.svelte`, with its cases
    in `web/src/lib/cli.test.ts`, `CliHint.svelte.test.ts` and that page's `page.svelte.test.ts`.
  - `tests/unit/cli/conftest.py`: the share fixture makes the directories that the status and
    check tests need. No test seeds the share through a CLI write.
  - CLI help and messages in strict STE. `uv run python scripts/cli_reference.py` output
    regenerated.
  - Tests: `tests/unit/cli/test_directories.py` rewritten against a read-only fake storage that
    fails on any write call (every directory verb, `activate`, `set namespace`, `delete
    collection` with and without a mount, none with an unrecorded-file check);
    `tests/unit/cli/test_administration.py` (`grant` and `revoke` output without a reminder).
    These tests assert the `huron adm apply-acl` text and change with it:
    `tests/unit/cli/test_browse.py` (the grant output has no reminder);
    `tests/unit/cli/test_organization_grants.py` (the grant and revoke output has no reminder, and
    the 409 hints name no ACL step); `tests/unit/cli/test_declared_organizations.py` (the 409 hint
    names no ACL step); `tests/unit/cli/test_check_and_acl.py` (the `apply-acl` cases go);
    `tests/unit/test_cli_reference.py` (the slug case uses another command).
- Verification: `make gate`;
  `grep -rnE "mount(\(\))?\.(ensure|apply|remove|report)\(|kind_of|_empty_directory|_refuse_unrecorded|catalog_groups|apply.acl|_remind|write_sidecar" src/huron/applications/cli web/src/lib web/src/routes`
  prints nothing;
  `grep -rnE "\.(write_bytes|remove_file|remove_directory|make_directory|make_inheriting_dir|set_mode|set_group|link|rename)\(" src/huron/applications/cli`
  prints nothing (the direct mode of the provision commands writes through
  `core.storage.provision`, not through a call in the CLI);
  `uv run python scripts/cli_reference.py --check`; from
  `web/`, `npm run check`, `npm test` and `npm run lint`.
- Dependencies: M11.7.
- Status: complete

#### M11.9a No ACL code

- Intent: the old M11.9's "Gone" list, completed. Every ACL path goes from the code, the scripts,
  the tests and the API. `provision-orgs` writes the marker at `lake_path`, which replaces
  `scripts/init-root.sh`. The new check findings and `provision-catalogs` stay in M11.9.
- Create or change:
  - Gone from `core.storage`: `aclplan.py` (`AclPlan`, `EffectiveGroups`, `plan`, `diff`) and its
    exports in `__init__.py`; `factory.py` (`storage_for`; `applications/api/runtime.py` and
    `applications/cli/main.py` construct `PosixStorage` directly); `Storage.ensure_directory`,
    `apply_plan`, `read_acl` and `owned_by_me` in the port and both adapters;
    `PosixStorage`'s `acl_backend` and `runner` arguments, `_acls`, `_runner` and `_perms`;
    `MemoryStorage`'s `Node.acl`, `Node.owner`, `Node.group`, `user` and the `("acl", path)` call
    (`uid`, `gid`, `groups`, `member_of` and `denied` stay; `add_root` takes `uid: int = 0` in
    place of `owner`);
    `DirectoryKind.NAMESPACE_WITH_COLLECTIONS` in `layout.py`.
  - Gone from `pkg.fs`: `acl.py`, and "POSIX ACLs" in the package docstring. `posix.make_dir` and
    its tests go with `ensure_directory`, its last caller.
  - `core/storage/check.py`: the `plan` fields, `_acl`, `acl_drift`, `org_acl_drift` and
    `AclError` go. The other findings stay.
  - `core/storage/provision.py`: `OrganizationTarget.plan`, `acls=`, `render_acl` and the
    owning-group `chgrp` go. Direct mode uses `make_directory(directory, ORGANIZATION_MODE)` and
    writes the marker of each organization and the marker at `lake_path` (no `organization`
    field). The script loses `setfacl`. `Provisioner` takes the lake path as an argument; it does
    not read a setting.
  - `applications/cli/commands/adm.py`: `adm check` loses `acls`, `_organization_plan` and the
    `plan(...)` calls in `_directories`, `_collections` and `_target`. `provision-orgs` gives
    `Provisioner` its own writable `PosixStorage` in place of `mount.storage`, with the CLI's
    `mount_prefix` as the lake path (section 6.1). The module docstring (line 1 at 5800e25a),
    the `adm` help (line 62) and the `provision-orgs` docstring (line 261, "the organization ACL
    plan") say "directory modes" in place of "directory ACLs". `provision-orgs` loses its `acls`
    variable and the `acl_backend` note. `applications/cli/inventory.py`: `groups`,
    the kinds of `directories()` and the `/grants` fetch go; `directories()` yields
    `(identifier, disk_path)` and the collections separately.
  - `applications/cli/mount.py`: `organization_groups` goes. `Mount.storage` and
    `Services.storage_factory` (`services.py`) are typed `ShareReader`. `check`,
    `check_organization` and `marker_state` in `core.storage` take a `ShareReader`.
  - `applications/cli/config.py`: the key `acl_backend` and its `CONFIG_KEYS` entry go.
    `applications/cli/errors.py`: `ACL_FAILED` goes, with its row in `docs/api-errors.md`.
  - The API: `GET /catalogs/{catalog}/grants` in `routes/v1/endpoints/grants.py`,
    `EffectiveGroupsOut` in `routes/v1/schema/grants.py`, `Grants.catalog_groups` in
    `core/lake/organizations/grants.py`, `Authorizer.effective_groups` and `EffectiveGroups` in
    `core/security/rbac/authorize.py`. The organization and platform grant routes stay. Then
    `make openapi`, and from `web/` `npm run generate:api`.
  - Scripts: `scripts/init-root.sh` and `tests/unit/test_init_root_script.py` go. The line
    `huron config set acl_backend none` goes from `scripts/e2e.sh` and `scripts/demo-noaa.sh`.
  - `pyproject.toml`: the `acl` pytest marker goes. Add the import contract "only core.storage
    imports huron.pkg.fs": a forbidden contract with the sources `huron.applications`,
    `huron.core.lake`, `huron.core.security`, `huron.core.metastore` and `huron.schema`, and the
    forbidden module `huron.pkg.fs`.
  - `AGENTS.md`: the layout rows without "acl" and "ACL plans", the tests line without `acl/`.
    `docs/user-guide.md`: the `adm` line says "directory modes". The rest of the ACL text in
    `docs/` is M11.12's work.
  - Tests that lose their ACL parts: `tests/acl/` and `tests/unit/pkg/test_acl.py` go;
    `tests/unit/test_error_contract.py` (the import of the ACL module);
    `tests/unit/cli/test_foundation.py` (`ACL_FAILED`); `tests/unit/cli/conftest.py`;
    `tests/unit/cli/test_check_and_acl.py` loses its ACL cases;
    `tests/unit/cli/test_declared_organizations.py`; every CLI test that builds an ACL plan;
    `tests/unit/storage/test_check.py` and `tests/unit/storage/test_storage.py` (the `Acl`
    imports, the `Node.acl` cases, the `storage_for` and ACL-plan cases);
    `tests/support/disk.py` (the `SubprocessRunner` import and argument);
    `tests/unit/cli/test_navigation.py` (the old spelling `acl apply` and the `acl ` branch of the
    hint pattern go); `tests/unit/test_ste_check.py` (the fixture hint title uses another
    phrase, for example "Grant a role; check the catalog").
    These also lose their ACL parts (found at 5800e25a with `git grep` for `effective_groups`,
    `EffectiveGroups`, `catalog_groups` and the route):
    `tests/unit/security/test_rbac.py` (the two `effective_groups` tests, lines 181 and 219);
    `tests/unit/cli/test_managed_service.py` (the `EffectiveGroups` and `plan` imports and the
    `ensure_directory` plan at line 149); `tests/unit/lake/test_organizations.py` and
    `tests/unit/lake/test_declared_organizations.py` (the `catalog_groups` cases);
    `tests/unit/api/test_admin_routes.py` (lines 59 and 183) and
    `tests/unit/api/test_managed_organizations.py` (line 108), which call
    `GET /catalogs/{catalog}/grants`; `tests/unit/cli/test_administration.py` and
    `tests/unit/cli/test_organization_grants.py`, where no assertion names `apply-acl`, not even
    a negative one such as `"apply-acl" not in granted`.
  - `tests/integration/test_cli_end_to_end.py`: construct `PosixStorage` directly in place of
    `storage_for`, and remove `acl_backend`. The skip mark of M11.7 stays until M11.10. The file
    must import without `factory.py`, because `pytest -m "not integration"` collects it.
  - Text that names ACLs: the `STORAGE_FAILED` row of `docs/api-errors.md` loses "an ACL
    operation failed"; the docstrings of `StorageError` in `core/storage/errors.py` and of
    `huron set namespace` in `applications/cli/commands/change.py` name no ACL.
    `tests/unit/storage/test_organizations.py`: direct mode writes the marker at `lake_path` and
    the organization markers, and the rendered script equals the expected lines exactly.
- Verification: `make gate`;
  `grep -rniwE "acl|acls|aclplan|acl_backend|setfacl|getfacl|EffectiveGroups|effective_groups|owned_by_me|NAMESPACE_WITH_COLLECTIONS|storage_for" src scripts tests web/src docs/api-errors.md docs/openapi.json AGENTS.md pyproject.toml`
  prints nothing; `grep -rn "organization_groups" src/huron/applications/cli` prints nothing;
  `test ! -e scripts/init-root.sh`; `test ! -e
  src/huron/core/storage/factory.py`; `make openapi`; `uv run pytest
  tests/unit/api/test_openapi_snapshot.py`; from `web/`, `npm run generate:api`, `npm run
  check` and `npm test`.
- Dependencies: M11.8a.
- Status: complete

#### M11.5b Removal shapes and roots below `lake_path`

- Intent: the pure parts of the containment model that have callers today. A destination and a
  removal carry names, not a joined path. A declared organization root lies at `lake_path` or
  below it, and the API has no `mount_prefix`. This task changes no disk operation.
- Create or change:
  - `src/huron/core/lake/uploads/models.py`: `Destination(directory, rel_path)`, the collection's
    `disk_path` and the upload's `rel_path`, the same two fields as `Removal`.
    `Destination.path`, `Destination.share_root` and `ClaimedRemoval` go.
    `core/lake/uploads/operations.py`, `ports.py` and both metastore adapters
    (`core/metastore/uploads/memory.py`, `postgres.py`): `claim_removals -> list[Removal]`.
    `Declarations.share_root` stays for the API views (`dependencies.with_share_root`).
  - `src/huron/applications/api/disk.py`: `place` takes the collection directory from
    `destination.directory` and joins the `rel_path` names below it. `Uploads.placement` in
    `core/lake/uploads/operations.py` builds the new `Destination`;
    `endpoints/uploads._finish` passes it on unchanged. The rest of `place` is unchanged until M11.5c.
  - `src/huron/applications/api/settings.py`: a model validator refuses a declared root that is
    not `lake_path` or below it, with the message "The root R of organization O is not below
    lake_path L". The validator runs only when `lake_path` is set: `huron.dev.yaml` declares
    roots and has no `lake_path` until M11.10, and the web e2e harness runs without a lake. The
    setting `mount_prefix` and its validator go.
    `src/huron/applications/api/runtime.py`: `settings.mount_prefix or lake_path` goes; an
    organization without a root lies directly below `lake_path`. The CLI key `mount_prefix`
    stays. `src/huron/applications/api/disk.py`: the `mount_prefix` parameter of the `LakeDisk`
    constructor and `_mount_prefix` go; `place_of` gets `lake_path` for an organization without a
    root.
  - `tests/support/disk.py`: the `mount_prefix` argument of `lake_disk` goes. Its call sites
    follow: `tests/unit/api/test_lake_disk.py` (the unmounted-lake case passes only
    `lake_path`). `test_a_path_outside_the_lake_fails_the_upload` in
    `tests/unit/api/test_upload_hooks.py` (`service(..., mount_prefix=...)`) is deleted; the
    symbolic-link case of M11.5c takes its place.
  - Tests: `tests/unit/lake/test_uploads.py` for `Destination` and `Removal`;
    `tests/unit/api/test_settings.py` (a root outside `lake_path` refuses to load, a root at
    `lake_path` and one below it load, `mount_prefix` is unknown);
    `tests/contract/suite.py` (`claim_removals` returns `Removal` rows);
    `test_a_mount_prefix_outside_the_lake_puts_unrooted_organizations_outside` in
    `tests/unit/api/test_lake_disk.py` deleted.
- Verification: `make gate`; `uv run pytest -m contract`;
  `grep -rnE "mount_prefix|ClaimedRemoval" src/huron/core src/huron/applications/api tests/support/disk.py tests/unit/api`
  prints only the unknown-key test in `tests/unit/api/test_settings.py` (`tests/support/cli.py`
  keeps the CLI key); `grep -rn "\.share_root\b"
  src/huron/core/lake/uploads src/huron/applications/api/disk.py` prints nothing.
- Dependencies: M11.9a.
- Status: complete

#### M11.5c Containment: `LakePath`, the descriptor traversal and the reduced port

- Intent: section 3's "Containment in the lake" and "The disk-access module", as one type change.
  Every disk operation names its place as a `LakePath` of validated names. `PosixStorage` opens
  it one name at a time from the root's descriptor and refuses any symbolic link. After this task
  no disk operation can follow a link or leave the lake. This is the containment fix for
  verification 3 of the M11.5 escalation. The directory verbs (M11.5d) and repair (M11.5e) are
  not part of it. This is the largest task. If it overruns, do not split it by layer, because
  that leaves two path models in the tree.
- Create or change:
  - `src/huron/core/storage/lakepath.py`: `LakePath(names)` with `of`, `parse`, `joinpath`,
    `parent`, `name`, `relative_to` and `__str__`, exported from `core.storage`. No constructor
    from `Path`, no absolute form. `src/huron/schema/naming.py`: `check_lake_name` (rule
    `lake_name`, 422 `NAME_INVALID`). `src/huron/core/storage/errors.py`: `SymlinkInLake`
    (`SYMLINK_IN_LAKE`, 409, the message "<path> is a symbolic link. The lake must not contain
    symbolic links. Remove it.", `context.path` the lake path of the link). `OutsideLake` and
    `OUTSIDE_LAKE` go. `docs/api-errors.md` follows.
  - `src/huron/pkg/fs/posix.py`: the descriptor primitives only. `open_beneath(root, names)`
    (`O_PATH | O_DIRECTORY | O_NOFOLLOW` steps, `SymlinkError(OSError)` naming the component).
    A link at an intermediate step fails with `ENOTDIR` on Linux, and a final non-directory
    open with `O_NOFOLLOW` fails with `ELOOP`. Each `ENOTDIR` or `ELOOP` is classified with
    `os.stat(name, dir_fd=, follow_symlinks=False)`: a link raises `SymlinkError`, any other
    entry keeps its `OSError`. `remove_file`, `remove_empty_dir`, `link_into_place`,
    `atomic_write` and `make_*` `lstat` the last name before they act, because `unlink`,
    `rename` and `mkdir` act on a link itself. Further functions:
    `make_dir(parent_fd, name, mode)`, `make_inheriting_dir(parent_fd, name)`,
    `atomic_write(parent_fd, name, data, mode, part_name)`, `link_into_place(source_fd,
    source_name, inode, parent_fd, name, part_name, backup_name)` with M11.5a's backup and the
    type and inode check of the source, `remove_file(parent_fd, name)`,
    `remove_empty_dir(parent_fd, name)`, `entry(parent_fd, name)` (`follow_symlinks=False`) and
    `walk(directory_fd)` yielding `Entry(names, kind, size, mtime_ns)` with `kind` in `file`,
    `dir`, `symlink`, `other`. `walk` is recursive and top-down: it yields a directory before
    its entries and enters no link. Every function that takes a `Path` below the root goes in
    the same change, with `exists`, `is_dir`, `inode`, `stat`, `_lstat`, `Entry.is_symlink` and the
    docstring claim "Nothing here follows symbolic links".
  - `src/huron/core/storage/ports.py`: the reduced port on `LakePath`. `ShareReader`: `stat ->
    Stat | None`, `read_bytes`, `is_empty`, `walk` (no `on_error`; recursive and top-down, as in
    `pkg.fs.posix`), `open_file`. `Storage` adds
    `make_directory`, `make_inheriting_dir`, `set_mode`, `set_group`, `write_bytes` (mode
    required), `link(source, destination, *, inode, part_name, backup_name) -> LakePath | None`,
    `rename`, `remove_file(location, *, inode=None) -> Outcome` and `remove_directory -> Outcome`.
    `Stat(kind, mode, gid, inode, size)`; `Outcome` (`REMOVED`, `MISSING`, `KEPT`) moves here.
    No `in_group`: M11.5e adds it with its one caller. Gone: `exists`, `is_directory`, `owner`,
    `inode`, `stamp`, `hash`, `device`, `Ownership`, `Stamp` and `FileStamp`.
  - `src/huron/core/storage/posix.py`: `PosixStorage(root)` on the traversal. A root that does
    not open is `LakeUnavailable`. A failed inheritance stays `pkg.fs.posix.InheritanceError`
    (`STORAGE_FAILED`); M11.5d adds `InheritanceFailed`. `src/huron/core/storage/memory.py`:
    `MemoryStorage(root)` with nodes keyed by `LakePath`, `Node.kind` (`dir`, `file`, `symlink`),
    `Node.inode`, `symlink(location, target)` for tests only, `unreadable` (a new set of
    `LakePath` for tests: directories that the caller cannot search), and one `_parent` that
    raises `SymlinkInLake` for a link and `StorageError` (`STORAGE_FAILED`, `EACCES`) for a
    directory in `unreadable`, like the POSIX traversal. `mounts`, `mount`, `ROOT_DEVICE` and
    `device` go; `add_root(path, uid)` becomes `add_directory(location, uid: int = 0)`. It takes
    a uid, not an owner name, because M11.9a removed `Node.owner`.
  - `src/huron/core/storage/layout.py`: `OrganizationPlace(name, base: LakePath, own_marker)`
    with `directory`, `marker_directory`, `locate(api_path) -> LakePath` and
    `mode_of(location)`; `UPLOADS = LakePath.of(UPLOAD_DIR)`. `layout.resolve`, `place_of`,
    `OrganizationPlace.rooted`, `declared`, `export` and `resolve` go.
    `src/huron/core/storage/marker.py`: `read_marker` and `verify_marker` on `LakePath`.
  - `src/huron/core/storage/placement.py`: `Placer(storage)` with `measure(upload_id, size)`,
    `measure_destination(target, size)`, `link(upload_id, collection, target, inode) -> Linked`,
    `undo(target, inode, linked)` and `drop_backup(target, upload_id)`. `Linked(made_dirs,
    backup)` holds `LakePath` values. `link` raises `ValueError` for a target that is not below
    its collection. The upload, `.info` and backup names are private and built on `UPLOADS`.
    `_remove_empty` and the `_empty` helper go. `src/huron/core/storage/removal.py`:
    `prune(storage, directories)`, innermost first, stops at the first directory that is not
    empty and never removes the collection directory.
  - `src/huron/applications/api/disk/` replaces `disk.py`. `disk/lake.py`: `Located(place,
    location)` with `joinpath`, and `LakeDisk(storage, places, instance_id, *, clock,
    probe_timeout)` with `open`, `ready`, `close`, `locate(api_path) -> Located` (pure,
    `NAME_INVALID` only), `hold(located, unit)`, `work(located, action)` and `measure(action)`.
    `hold` takes the lock of the location, runs the unit shielded, and verifies the marker in the
    disk worker before each `run`. `measure` uses the hash pool with no lock and no marker check.
    The places are built once from `settings.declarations`. `PathLocks` keys are `LakePath`.
    `disk/placements.py`: `Placements.place(uploads, actor, upload, destination)` with `_settle`
    and `_replay`. The marker is verified in the locked link, undo and drop-backup steps, not
    before the hash. `SymlinkInLake` fails the upload in the branch of
    `CollectionDirectoryMissing`. Gone: `resolve`, `_resolve`, `_visible`, `_require_lake`,
    `upload_dir`, `place_of`, public `run`, `call` and `check_marker`, the pre-hash
    `check_marker`, `_Placement.collection_dir` and the `depth` computation.
  - The committed share-group call of M11.3 (`LakeDisk.set_share_group`) moves onto `work` with a
    `LakePath`. M11.5d moves it into `LakeDirectories`.
  - `src/huron/applications/api/runtime.py`: `PosixStorage(root=lake_path)`; `lake_path` is used
    only for the readiness message. `tests/support/disk.py`: `memory_lake` and `lake_disk` on
    `LakePath`, `StalledStorage` and `PausingStorage` with `LakePath` overrides, and
    `plant_symlink(storage, location)` for both adapters.
  - Read callers, and the writes of `provision.py`, moved to `LakePath`, last in this list so that a verifier sees them done:
    `core/storage/check.py` (`stat`, `walk`, `read_bytes`, `open_file(...).sha256()`),
    `core/storage/provision.py` (`stat` in place of `is_directory`, and its writes:
    `make_directory` and the `write_bytes` of each organization marker and of the marker at
    `lake_path`, as M11.9a left them, on `LakePath` below the writable `PosixStorage` that
    `provision-orgs` builds at the CLI's `mount_prefix`), the CLI's `Mount` read side
    (a `PosixStorage(root=<organization base on this machine>)` with `LakePath.parse`),
    `applications/cli/context.py` (`unrecorded_files`) and `huron status`.
  - `pyproject.toml`: add the import contract "`core.storage` does not import `applications` or
    `core.metastore`". `placement.py`'s import of `core.lake.uploads.errors` stays allowed.
  - `make openapi`; from `web/`, `npm run generate:api` (the error code changes).
  - Tests:
    - `tests/unit/storage/test_lakepath.py`: `parse` and `of` refuse `""`, `.`, `..`, `a//b`,
      `/a`, `a/`, NUL and a 256-byte name with 422 `NAME_INVALID`; `relative_to` and `str` give
      the API form.
    - `tests/unit/pkg/test_posix.py`: for each primitive, a link planted as an intermediate
      directory and as the last name (parametrized) raises `SymlinkError` naming the component,
      with `outside` unchanged; `walk` yields the link as `symlink` and nothing from its target;
      `link_into_place` refuses a source that is a link or has another inode.
    - `tests/unit/storage/test_containment.py`: one suite parametrized over
      `PosixStorage(root=lake)` on a real temporary filesystem and `MemoryStorage`, with
      `plant_symlink`. For `stat`, `read_bytes`, `is_empty`, `open_file`, `make_directory`,
      `make_inheriting_dir`, `set_mode`, `set_group`, `write_bytes`, `link`, `rename`,
      `remove_file` and `remove_directory`, with the link intermediate and last:
      `(code, status) == ("SYMLINK_IN_LAKE", 409)` and `context["path"]` is the link's lake path.
      `walk` yields the link as `symlink` and does not enter it. The POSIX variant compares a
      snapshot of `tmp_path / "outside"` (names, modes, bytes) before and after; the memory
      variant asserts that no node changed and that `calls` holds no write.
    - `tests/unit/storage/test_storage.py`, over both adapters: `stat` of a file, a directory and
      a missing name; `is_empty`; `remove_directory` and `remove_file(inode=)` answering
      `REMOVED`, `MISSING` and `KEPT`; `link(inode=)` with another inode raising `SourceGone`
      with nothing linked. The `stamp`, `hash`, `device` and mount cases go.
    - `tests/unit/storage/test_placement.py`: all M11.4 and M11.5a cases on `LakePath` with the
      same assertions; a link with a replaced source (`SourceGone`, the made directories
      pruned); a target outside its collection (`ValueError`). `tests/unit/storage/test_removal.py`:
      `prune`.
    - `tests/unit/api/test_lake_disk.py`: `hold` verifies the marker before each `run`; `measure`
      holds no lock; the lock and cancellation tests on `work` and `hold` with a `Located`; the
      M11.5a pool test unchanged. The `OUTSIDE_LAKE`, `device` and mount cases go.
    - `tests/unit/api/test_upload_hooks.py`, on a real temporary lake: a `pre-finish` with the
      namespace directory replaced by a link to `outside` answers the refusal 409
      `SYMLINK_IN_LAKE`, the upload is `failed` with that code, the file in `.tus-uploads` is
      kept and `outside` is unchanged. It replaces the `OUTSIDE_LAKE` case that M11.5b deleted.
      The M11.5a overwrite cases pass unchanged.
- Verification: `make gate`;
  `grep -rnE "OUTSIDE_LAKE|OutsideLake|\.device\(|ROOT_DEVICE|is_symlink|mount_prefix|\b_visible\b|_require_lake" src/huron/core src/huron/applications/api tests/unit/api tests/unit/storage tests/support/disk.py docs/openapi.json web/src/lib/api`
  prints only the M11.5b unknown-key test in `tests/unit/api/test_settings.py`;
  `grep -rnE "os\.(open|stat|lstat|walk|scandir|listdir|mkdir|link|rename|replace|unlink|rmdir|chmod|chown)|shutil|Path\(" src/huron/applications/api/disk src/huron/applications/api/routes`
  prints nothing; `grep -nE "\bPath\b" src/huron/core/storage/placement.py
  src/huron/core/storage/removal.py` prints nothing; `grep -nE "^def [a-z]"
  src/huron/pkg/fs/posix.py` lists no function that takes a `Path` below the root;
  `uv run pytest tests/unit/storage/test_containment.py`; `uv run pytest
  tests/unit/api/test_openapi_snapshot.py`; from `web/`, `npm run check`.
- Dependencies: M11.5b.
- Status: pending

#### M11.5d Directory verbs and `metadata.json`

- Intent: section 3's "Directory verbs in the API" on the final port. Each verb commits its rows,
  takes the directory's API path from the operation's answer, and does that directory's work
  through `LakeDisk.work`. No route builds a path, reads a row for the disk or branches on the
  lake.
- Create or change:
  - The lake answers: `Organizations.delete` returns the deleted name (`str`).
    `core/lake/collections/models.py`: `SettledCollection(id, disk_path)`.
    `Collections.sidecar_of(id)` (no privilege, for disk work). `Catalogs.assign_schema` returns
    `SchemaAssignment(catalog, recompute, settled)` with `settled: tuple[SettledCollection, ...]`
    in identifier order. `NamespaceStore.list_in_catalog` in `core/lake/namespaces/ports.py` and
    in both metastore adapters. `CollectionView` keeps `disk_path` only (no `directory` field).
    `namespace_path` stays private in `core/lake/namespaces/operations.py`.
  - `src/huron/core/storage/directories.py`: `DirectoryWriter(storage, service_gid)`.
    `make(place, location) -> bool`: the organization's own directory with
    `make_directory(location, ORGANIZATION_MODE)`, any other with `make_inheriting_dir`; an
    existing empty directory is adopted unchanged (`False`); any other entry, a link included, is
    refused with `STORAGE_FAILED` or `SYMLINK_IN_LAKE`. `set_group(location, share_group: str |
    None) -> GroupResult`: `None` means the service gid; this is the one home of the rule "a
    catalog without a share group carries the service group". `write_metadata(location, body) ->
    bool`: equal bytes write nothing, else an atomic write with `FILE_MODE`.
    `remove(location) -> Outcome`. `remove_collection(location) -> Outcome`: `walk`, sorted by depth
    with the deepest entries first, removes `metadata.json`, part and backup files and the then-empty subdirectories, then the
    directory; a link below keeps the directory (`KEPT`, log `disk.link_found`); a missing
    collection is `MISSING` with no walk.
  - `src/huron/core/storage/errors.py`: `InheritanceFailed` (`STORAGE_FAILED`) for a directory that
    did not inherit setgid and the group; the directory is removed again first.
    Add `GroupResult.warning(group)` as the one builder of `SHARE_GROUP_PENDING`. At 5800e25a
    `LakeDisk.set_share_group` builds the `ShareWarning` itself; that code goes.
  - `src/huron/core/storage/layout.py`: `DirectoryKind` and `mode_of(kind)` go, with their uses
    in `check.py`, `applications/cli/inventory.py` and `applications/cli/commands/adm.py`;
    `OrganizationPlace.mode_of(location)` decides by location.
  - `src/huron/applications/api/disk/directories.py`: the protocol `Directories` (`make`,
    `set_group`, `write_metadata(path, render)`, `remove`, `remove_collection`, all on API
    paths), `LakeDirectories(disk, writer)` and `NoLake`. `write_metadata` uses `hold`: it awaits
    the render under the lock, from a new read of the rows, and a `None` render skips the write.
    `remove` and `remove_collection` return nothing and log `disk.directory_kept` for `KEPT`.
    `NoLake` returns at once and `set_group` returns `None`. `LakeDisk.set_share_group` goes.
  - `src/huron/applications/api/runtime.py` builds `LakeDirectories` or `NoLake`;
    `dependencies.py` gives `DirectoriesDep`, never `None`.
  - `routes/v1/endpoints/organizations.py`, `catalogs.py`, `namespaces.py`, `collections.py`: one
    verb per answer. Create organization: `make`. Delete organization, catalog or namespace:
    `remove`. Create catalog: `make`, then `set_group` when a share group is given. Set share
    group: `set_group`. Create namespace: `make`. Activate: `make`, then `write_metadata`.
    Update: `write_metadata` when `disk_path` is not `None`. Assign schema: `write_metadata` per
    settled collection, in order, each under its own lock; the first failure ends the request.
    Delete collection: `remove_collection` when `disk_path` is not `None`. After the commit the
    only errors are `STORAGE_FAILED` 500, `LAKE_UNAVAILABLE` 503, `SYMLINK_IN_LAKE` 409 and, for
    a path from a corrupted row that `locate` refuses, `NAME_INVALID` 422, with the rows kept
    for a create, set, activate, update or assign verb. The routes' `check_segment` and
    `namespace_path` calls, the organization read and `relative_to` in `catalogs.py` and
    every lake branch go. `routes/directories.py` is not rebuilt.
  - `make openapi`; from `web/`, `npm run generate:api`.
  - Tests:
    - `tests/unit/api/test_directory_verbs.py`, rebuilt from the branch's cases that stay: the
      mode per verb, an adopted empty directory, a non-empty entry answering 500 with the rows
      kept, a failed inheritance answering `STORAGE_FAILED`, `metadata.json` from a new read
      after activate, publish, override and assignment (two settled collections in two
      namespaces and a draft), a kept non-empty directory on delete with 204, an unmarked lake
      answering 503 with the rows kept, every verb over `NoLake` changing rows only, a dry-run
      delete. On a real temporary filesystem with `lake = tmp_path / "lake"` and `outside =
      tmp_path / "outside"`, a snapshot of `outside` equal before and after: verification 3's
      first reproduction (a settled collection directory replaced by a link to `outside`, then
      `PUT /catalogs/{catalog}/schema`: the rows are committed, the answer is 409
      `SYMLINK_IN_LAKE` with the link's lake path, and no `metadata.json` is in `outside`); the
      same with the namespace above the collection replaced by a link; a link at the parent of
      a new namespace and at an activated collection's directory (409, rows kept); a link inside
      a deleted collection (204, directory kept).
    - `tests/unit/storage/test_directories.py` over both adapters: the writer cases of the
      branch on `LakePath`, a link case for `make` and for `remove_collection`, `set_group` with
      and without a share group.
    - `tests/unit/api/test_lake_disk.py`: the metadata, kept-directory and share-group cases move
      onto `LakeDirectories`. `tests/unit/api/test_catalog_share_group.py` on `LakePath`.
      `tests/unit/lake` for the new answers.
  - Found in M11.8a's verification: the docstring of the `metadata.json` route in
    `src/huron/applications/api/routes/v1/endpoints/collections.py` (about line 173) still says
    the CLI writes the file beside the files. Rewrite it to the API writing it, and run
    `make openapi`.
- Verification: `make gate`; `uv run pytest -m contract` (`list_in_catalog`);
  `grep -rnE "DirectoryDep|LakeDirectory\b|DirectoryKind|_KINDS|directory_group|place_of\(|disk\.resolve\(" src/huron tests`
  prints nothing;
  `grep -rnE "joinpath|disk is (not )?None|directory is not None|check_segment|namespace_path" src/huron/applications/api/routes`
  prints nothing; `grep -nE "\bPath\b" src/huron/core/storage/directories.py` prints nothing;
  the `os.` grep of M11.5c over `src/huron/applications/api/disk` and `routes` prints nothing;
  `uv run pytest tests/unit/api/test_openapi_snapshot.py`; from `web/`, `npm run check` and
  `npm test`.
- Dependencies: M11.5c.
- Status: pending

#### M11.5e Repair

- Intent: section 3's "Repair" on the final port. A repair acts on the planned directories only and
  lists no directory. It runs one step per directory, under that directory's lock, and reports
  one failure shape.
- Create or change:
  - `src/huron/core/lake/repairs/`: `Level`, `PlannedDirectory(path, level, id)`,
    `RepairPlan(directories, share_group)` with the property `catalog`, `PlannedRow(metadata:
    bytes | None = None)` (the `metadata.json` of a settled collection, `None` for any other
    directory; the class `ExpectedDirectory` of `m11.5-escalated`, renamed so that it does not
    share a name with `core.storage.check.ExpectedDirectory`), and
    `Repairs` with `plan(actor, catalog, target, recursive) -> RepairPlan` (authorizes
    `NAMESPACE_CONFIGURE`; refuses a target of another catalog with `REQUEST_INVALID`, an
    unknown one with `NOT_FOUND`, a draft with `STATE_CONFLICT`), `organization(actor, name) ->
    RepairPlan` (one directory; authorizes `CATALOG_GRANT_ADMIN`) and `expected(directory) ->
    PlannedRow | None`. `_Tree` works on segment tuples, parents first. `Level` stays in
    `core.lake`. `core/lake/bootstrap.py` builds `Repairs`; `pyproject.toml` adds
    `huron.core.lake.repairs` to the contracts that list the `core.lake` packages.
  - `src/huron/core/storage/repair.py`: `FailureReason` (`mode_drift`, `symbolic_link`,
    `storage_failed`), `RepairFailure(path, reason, detail)`, `RepairResult(changed, warnings,
    failed)` with `combine`, `RepairStep(place, location, catalog, share_group=None,
    metadata=None)` and `Repairer(storage, writer).repair(step)`. The step, in order: one `stat`
    of the location; missing is `writer.make`, a link is `symbolic_link`, any other
    non-directory is `storage_failed`. Then the mode: `ORGANIZATION_MODE` for the organization's
    directory, `S_ISGID` for the catalog directory, `S_ISGID` and the catalog directory's gid
    below it. A broken setgid or group rule is `mode_drift`, unchanged. Other wrong bits get
    `set_mode(location, place.mode_of(location))` only when `in_group(gid)`, else `mode_drift`.
    Then `writer.set_group(location, share_group)` on the catalog step only (a refusal is the
    `SHARE_GROUP_PENDING` warning). Then `writer.write_metadata` for a settled collection.
    `InheritanceFailed` is `mode_drift`; `SymlinkInLake` is `symbolic_link` at the link's path;
    `LakeUnavailable` ends the repair; any other `StorageError` is `storage_failed`. Paths are in
    the API form, relative to the organization's base.
  - `src/huron/core/storage/ports.py`: `Storage.in_group(gid)`. `PosixStorage`: `os.getegid()`
    and the first 16 groups of `os.getgroups()`, because AUTH_SYS sends only 16 supplementary
    groups. `MemoryStorage`: `member_of`.
  - `src/huron/applications/api/disk/repair.py`: `LakeRepair(disk, repairer).repair(repairs,
    plan)`. For each planned directory, `locate` (pure), then one `hold` whose unit awaits
    `repairs.expected(planned)` and then runs the step; a row that is gone gives no step.
    `Runtime` builds it only with `lake_path`.
  - `routes/v1/endpoints/repairs.py`, `routes/v1/schema/repairs.py`, `routes/v1/router.py`:
    `POST /api/v1/catalogs/{catalog}/repair` (`{target, recursive}`) and
    `POST /api/v1/organizations/{org}/repair`, both 200 with `{changed, warnings, failed}`.
    `RepairFailureOut` has `path`, `reason` (an OpenAPI enum) and `detail`. Without `lake_path`
    both routes answer 503 `LAKE_UNAVAILABLE` after the privilege check (`require_lake`).
    `require_lake(repair: LakeRepair | None) -> LakeRepair` is a new private function in
    `repairs.py`. Each route calls it after the privilege check with the `LakeRepair` that
    `Runtime` holds (`None` without `lake_path`). For `None` it raises `LakeUnavailable` with the
    message "lake_path is not set. The API cannot repair directories." and an empty `context`.
    `make openapi`; from `web/`, `npm run generate:api`.
  - `tests/conftest.py`: `temporary_mode` comes back, with its first user.
  - The branch `m11.5-escalated` stays. This task does not delete it.
  - Tests:
    - `tests/unit/lake/test_repairs.py`: the plan from the catalog down to the target, a
      recursive plan with every namespace and settled collection in `directories`, the
      privileges, a target of another catalog, an unknown target, a draft, the share group in the
      plan and `plan.catalog`, and `solar` beside `solar-wind` (neither is in the other's plan).
    - `tests/unit/storage/test_repair.py` over `MemoryStorage` and `PosixStorage(root=tmp)`
      where the case needs no group membership: missing, wrong bits, right bits with no `chmod`,
      a missing setgid bit and another group as `mode_drift` with no `chmod`, a directory outside
      the service's groups with no `chmod`, a `chmod` that still drops setgid, the organization
      directory, the catalog's group attempt, a non-directory at a planned path, a link at the
      step's directory and above it (`symbolic_link`, no write in `calls`), an unreadable
      catalog directory (`storage_failed`), a stale `metadata.json`, combine with each failure
      once, idempotence. `tests/unit/storage/test_storage.py`: `in_group` with the 16-group
      limit.
    - `tests/unit/api/test_repair.py`: both routes, the privileges, 503 without a lake after the
      privilege check, a row deleted between the plan and the step (no directory), a recursive
      repair that makes a removed collection directory and its `metadata.json` and leaves an
      unplanned directory and file unchanged and unreported, the siblings of a repaired
      namespace unchanged. On a real temporary filesystem, with a snapshot of `tmp_path /
      "outside"` equal before and after: verification 3's second reproduction (a namespace made
      unsearchable with `temporary_mode(0o2000)` holds a collection directory replaced by a link
      to `outside`; a recursive repair repairs the namespace, the collection step is `failed`
      with `symbolic_link`, nothing changes in `outside`); a planned directory that is a link; a
      link at a namespace above two planned collections (one failure, the other steps run); a
      link at `metadata.json`.
- Verification: `make gate`;
  `grep -rnE "\bon_error\b|DirectoryPlan|_EntryGuard|_Report\b|\b_skipped\b|\.walks\b|walks=|\.chain\b|\.below\b|repair_organization|_repair_planned|_KINDS|VanishingStorage" src/huron tests`
  prints nothing; `grep -rn "^MODE_DRIFT" src/huron` prints nothing; `grep -n "walk"
  src/huron/core/storage/repair.py src/huron/core/lake/repairs/*.py` prints nothing;
  `grep -rn "Level" src/huron/core/storage` prints nothing; `grep -n "symbolic_link"
  docs/openapi.json` finds the reason enum; `grep -rn "symlink" src/huron/core src/huron/pkg
  src/huron/applications/api --include=*.py | grep -v "follow_symlinks=False"` finds only
  `MemoryStorage.symlink` and the `kind` literal `"symlink"` (the grep is case-sensitive, so it
  does not find `SymlinkInLake` or `SymlinkError`; the `is_symlink` checks of `sync._collect` read the local source folder
  and stay); `git branch --list m11.5-escalated` still prints the branch;
  `uv run pytest tests/unit/api/test_openapi_snapshot.py`; from `web/`, `npm run check` and
  `npm test`.
- Dependencies: M11.5d.
- Status: pending

#### M11.6 Removals, the background runner and the sweep

- Intent: the amendment's "Removals and the inode guard" and "Sweep", on the final port.
- Create or change:
  - `src/huron/core/storage/removal.py`, beside `prune`: `Unlinker(storage)` with
    `unlink(collection, target, inode) -> Outcome`. It calls `remove_file(target, inode=inode)`:
    `KEPT` when the inode differs, `MISSING` on `ENOENT`. After `REMOVED` it prunes the
    directories from `target.parent` up to, not including, the collection directory. A removal
    without an inode (a file committed by an API without a lake) is `MISSING` with no disk call.
    `Sweeper(storage, ttl, clock)` with `sweep() -> list[LakePath]`: it walks `UPLOADS`, takes
    only the entries with one name (one level) and removes each file whose modification time is older than `upload_ttl` (tusd's lock files
    included). A directory or a link there is logged and kept.
  - `src/huron/applications/api/disk/removals.py`: `Removals(disk, unlinker)` with
    `drain(uploads, removals)`. Each row runs as one `hold` of the file's location: the unit
    awaits `removal_still_valid`, runs the unlink, then awaits `finish_removal`. `MISSING` and
    `KEPT` finish the row. A `StorageError` (`SymlinkInLake`, `EACCES`, `EIO`,
    `LakeUnavailable`) leaves the row claimed and logs `disk.removal_failed` with the path and
    the code; the runner tries again after `REMOVAL_LEASE`. The drain never removes the
    collection directory; that is the delete verb's work (M11.5d).
  - `src/huron/applications/api/routes/v1/endpoints/files.py` (the commit route): drains
    `CommitResult.removals` after the commit. `collections.py` (the delete route): drains
    `DeletedCollection.removals` first, then calls `remove_collection`. A failed unlink does not
    change the 200 or the 204.
  - `src/huron/applications/api/background.py`: `Runner(runtime)` with the removal loop
    (`claim_removals` every `removal_interval`), the sweep loop (`sweep_interval`) and the
    election through `ClosableStore.lease_runner()` in `runtime.py` (`pg_try_advisory_lock` on a
    dedicated connection in `core/metastore/postgres.py`, always leased in
    `core/metastore/memory.py`). The election saves work; correctness rests on `skip locked` and
    on unlinks that accept `ENOENT`. The election connection sets TCP keepalives
    (`keepalives_idle=30, keepalives_interval=10, keepalives_count=3`), and the runner stops when
    that connection drops. `app.py` starts the runner in the lifespan when `lake_path` is set and
    stops it on shutdown.
  - Tests:
    - `tests/unit/storage/test_removal.py` over both adapters: `Unlinker` answers `REMOVED`,
      `MISSING` and `KEPT` and prunes only after `REMOVED`; a removal without an inode makes no
      disk call; `Sweeper` removes old files only and keeps a planted link.
    - `tests/unit/api/test_removals.py`: a commit's remove unlinks in the request; a collection
      delete unlinks placed uploads and then removes the directory; a re-added key cancels; the
      inode guard keeps a replaced file; a failing unlink leaves the row claimed and the commit
      answers 200; empty directories pruned after an unlink, the collection directory kept; a
      left-over row drained by the runner after the lease; after a late runner unlink the empty
      collection directory stays and a new collection at its path adopts it. On a real temporary
      filesystem: a removal whose namespace directory is replaced by a link to `tmp_path /
      "outside"` leaves the row claimed, logs `disk.removal_failed`, and leaves a snapshot of
      `outside` unchanged.
    - `tests/unit/api/test_background.py`: the loops with a frozen clock, the sweep removing old
      entries only, a runner that is not elected does nothing, a runner that stops when its
      election connection drops. `tests/contract/test_postgres_runtime.py`: two stores, one
      lease.
- Verification: `make gate`; `uv run pytest -m contract`;
  `grep -rnE "\b_empty\(|_remove_empty|parents\[depth|\.stamp\(|\.hash\(|\.is_directory\(|\.owner\(|Ownership|FileStamp|upload_dir|check_marker|directory_group|ClaimedRemoval" src/huron/core/storage src/huron/applications/api/disk src/huron/core/lake/uploads`
  prints nothing; `grep -n "remove_collection\|remove_directory"
  src/huron/applications/api/disk/removals.py` prints nothing.
- Dependencies: M11.5d.
- Status: pending

#### M11.8 Share group, `adm repair` and the hints in the CLI

- Intent: the CLI features of "The CLI" that need the API routes of M11.5d and M11.5e. The CLI
  write half is M11.8a.
- Create or change:
  - `src/huron/applications/cli/commands/create.py`: `create catalog --share-group <group>`.
    `change.py`: `set catalog <catalog> --share-group <group> | --no-share-group`, a new command
    on `set_app`. A `SHARE_GROUP_PENDING` warning in a response prints the `provision-catalogs`
    hint.
  - `src/huron/applications/cli/commands/adm.py`: `repair <identifier> [--recursive] | --org
    <org>`. It calls the catalog's or the organization's repair route and prints each changed
    path, each warning, and each failed path with its `reason` and `detail`.
  - `src/huron/applications/cli/errors.py`: the hints, in strict STE. `SHARE_GROUP_PENDING`: the
    `provision-catalogs` step. `STORAGE_FAILED` and `LAKE_UNAVAILABLE` from a create, activate or
    publish verb: `To make the directory again, run huron adm repair <identifier>`.
    `SYMLINK_IN_LAKE`: the storage administrator removes the link, then runs `huron adm repair`.
  - CLI help and messages in strict STE. `uv run python scripts/cli_reference.py` output
    regenerated.
  - Tests: `tests/unit/cli/test_directories.py` (the share-group options and hint, over the
    read-only fake storage of M11.8a); `tests/unit/cli/test_repair.py` (both forms, `--recursive`,
    the output of `changed`, `warnings` and `failed` with `reason` and `detail`, 503 without a
    lake); `tests/unit/cli/test_foundation.py` (the four hints).
- Verification: `make gate`; `uv run python scripts/cli_reference.py --check`;
  `grep -rnE "\.(write_bytes|remove_file|remove_directory|make_directory|make_inheriting_dir|set_mode|set_group|link|rename)\(" src/huron/applications/cli`
  prints nothing.
- Dependencies: M11.5e.
- Status: pending

#### M11.9 The check and provisioning on modes and groups

- Intent: sections 6.2 and 6.4 as built, and the storage administrator's commands, on the final
  port. The ACL code went in M11.9a.
- Create or change:
  - `src/huron/pkg/fs/posix.py`, `core/storage/posix.py` and `memory.py`: `walk` yields a
    directory that it cannot list as `Entry(kind="unreadable")`, with the `errno` in
    `Entry.errno`, and does not enter it. `MemoryStorage.unreadable` (M11.5c) gives the same
    entry; only the way `walk` reports it changes.
    `Stat` gains `uid`, for the owner part of `mode_drift`.
  - `src/huron/core/storage/check.py`: it reads through `stat` and `walk` on `LakePath`.
    `ExpectedDirectory`, `ExpectedCollection` and `ExpectedOrganization` carry `mode`, `group`
    and `owner`. `mode_drift` covers the mode and the owner, and for a directory below a catalog
    also a missing setgid bit or a group other than the catalog directory's.
    `share_group_mismatch` compares the catalog directory's group with the catalog's share group
    by name through `grp.getgrnam` and reports a name that it cannot resolve; for a catalog
    without a share group it compares with `G` by gid (`service_user.gid` from `/healthz`).
    Neither finding compares the group of a file. `unreadable` (warning, the path and the
    `errno`) comes from the `unreadable` entries. `symbolic_link` (error, the path) comes from
    each `symlink` entry. `huron status` (`context.unrecorded_files`) uses the same
    `unreadable` rule.
  - `src/huron/core/storage/provision.py`: `OrganizationTarget` with `owner_uid` and the numeric
    `gid`; `CatalogTarget(place, location, group)`; `Provisioner.provision` and
    `provision_script`. The organization part requires the root to exist (as at 5800e25a),
    creates `<root>/<org>` when missing, sets `U:<gid>` on `<root>/<org>` only (no `chown -R`),
    sets mode `2751` and writes the marker. The `lake_path` part emits
    `chown U:<gid> <lake_path>; chmod 2751 <lake_path>; mkdir -p <lake_path>/.tus-uploads;
    chown U:<gid> <lake_path>/.tus-uploads; chmod 0700 <lake_path>/.tus-uploads` and writes the
    marker at `lake_path`. An organization without a root is provisioned at
    `<lake_path>/<org>`. The caller passes the lake path: the CLI's `mount_prefix`. `provision_catalogs` selects a catalog when its directory group differs,
    or when a directory below it has `mode_drift` for the setgid bit or the group; a catalog
    without a share group is selected and targeted with `G`'s gid. `catalog_script` emits one
    line, `find <catalog> -type d -exec chgrp <group> {} + -exec chmod 2750 {} +` (`find` keeps
    its default `-P` and needs no `-xdev`), never `chgrp -R` and no line for files. Every script
    runs `set -eu`, uses the numeric `U:<gid>` and quotes with `shlex.quote`.
  - `src/huron/applications/cli/commands/adm.py`: the check wiring from `share_group`,
    `service_user` and section 6.2, with a help line that names who can run a complete check (an
    account in `G` and in every share group, or `U` from an API pod). `provision-catalogs`
    (direct mode and `--emit-script`, `--catalog`, `--dry-run`, `--uid`, `--gid`).
    `provision-orgs` with the non-recursive owner change, mode `2751` and the `lake_path` steps
    at the CLI's `mount_prefix` (section 6.1); `--uid` and `--gid` override `service_user`, and it refuses when neither gives the owner.
    `verify-mounts` unchanged.
  - Tests: `tests/unit/storage/test_check.py` over both adapters (a clean tree, each new
    finding, `unreadable`, a planted link as `symbolic_link`, the owner part with and without
    `service_user`, a placed file of group `G` with no finding);
    `tests/unit/storage/test_organizations.py` (the scripts and direct mode, the `lake_path`
    steps, no `chown -R`, `--uid` and `--gid`); `tests/unit/storage/test_provision_catalogs.py`
    (the selection, the one `find` line); `tests/unit/cli/test_check_and_acl.py` renamed
    `test_check.py` (findings over the fake share, `provision-catalogs` in both modes);
    `tests/unit/cli/test_status.py` (`unreadable`); `tests/unit/pkg/test_posix.py` and
    `tests/unit/storage/test_storage.py` (`walk` yields an unreadable directory and goes on).
- Verification: `make gate`; `uv run python scripts/cli_reference.py --check`;
  `grep -rnE "chown -R|-type f|setfacl" src/huron/core/storage/provision.py` prints nothing;
  `grep -rn "symlink" src/huron/core src/huron/pkg --include=*.py | grep -v
  "follow_symlinks=False"` finds only `MemoryStorage.symlink` and the `kind` literal
  `"symlink"` (`check.py` included). The grep is case-sensitive, so it does not find
  `SymlinkInLake` or `SymlinkError`.
- Dependencies: M11.5c, M11.9a.
- Status: pending

#### M11.10 The development stacks and the integration tier

- Intent: the amendment's `make app` and `make api`, and tests over real nginx and tusd.
- Create or change:
  - `deploy/openshift/nginx-uploads.conf.template`: the amendment's shape, with `OPTIONS`
    answered without `auth_request` (`error_page 418 = @tus_options; if ($request_method =
    OPTIONS) { return 418; }` and `location @tus_options`), `proxy_set_header Forwarded "";` once
    in the `server` block, which both `/files/` locations and `@tus_options` inherit because they
    set no `proxy_set_header` of their own, `proxy_cache_key
    "$request_method|$huron_upload_id|$http_authorization"`, and `map $http_authorization
    $huron_no_auth`. The Helm copy of this file is M11.13's work.
  - `docker-compose.app.yml`: the `api` service binds `HURON_LAKE_SOURCE` read-write at
    `/data1/huron` inside the container, runs as `user: "${HURON_UID}:${HURON_GID}"`, and sets
    `HURON_SERVICE_UID` and `HURON_SERVICE_GROUP` to the host user and group. `uploads-proxy` and
    `uploads` per the Deployment bullet. `uploads-proxy` uses `command:` (Compose keeps the image
    entrypoint, so the `envsubst` step runs), with `NGINX_ENVSUBST_OUTPUT_DIR=/tmp`,
    `NGINX_ENVSUBST_FILTER=^HURON_API_UPSTREAM$` and the configuration
    `/tmp/nginx-uploads.conf`. A one-shot `uploads-init` (the tusd image, `sh -c`) deletes
    `*.lock`, `*.lock.*` and `*.stop` in `.tus-uploads` before `uploads` starts. `net` publishes
    127.0.0.1:1080. The one-shot `lake-init` runs `scripts/dev-provision.py` before the API.
  - `scripts/dev-provision.py`: builds the organization targets from `huron.dev.yaml` and
    `HURON_INSTANCE_ID` and calls `Provisioner.provision` (the code of `provision-orgs` direct
    mode). So one module writes the organization directories, `.tus-uploads` and the markers.
    The script writes no layout of its own.
  - `docker-compose.uploads.yml` (nginx and tusd with host networking, the lake bind mount, the
    host user, the same `command:`, environment and lock cleanup). `Makefile`: `HURON_UID`,
    `HURON_GID`, `HURON_GROUP` and `HURON_LAKE_SOURCE`, the targets `uploads` and
    `uploads-down`.
  - `huron.dev.yaml`: `lake_path` and `uploads_url`. `make app`'s seed runs against the API with
    a lake. A seeded file goes through the proxy and tusd, so it has a receipt; a file-less seed
    needs no change. Only the web e2e harness runs without a lake. `dev.env` unchanged.
  - `scripts/e2e.sh`: pushes through the proxy. `HURON_LAKE_SOURCE` and `HURON_LAKE_PATH` are one
    directory under its temporary directory, bound at the same path inside the container.
    `service_uid` and `service_group` are the host user and group.
  - `tests/integration/test_uploads_tusd.py`: the API over PostgreSQL with `lake_path` set to a
    temporary lake, served by uvicorn on 127.0.0.1, and real tusd and nginx containers with host
    networking over the same directory as the host user. A push of new, overwritten and removed
    files, an empty file, a resumed upload, an overwrite over a part file left by an earlier
    attempt, a PATCH with another user's token refused 403 by nginx with no byte in
    `.tus-uploads`, a PATCH without a token refused 401, an `OPTIONS /files/<id>` followed by a
    PATCH without a token (401) and a PATCH with another user's token (403), a client
    `Forwarded` header that does not change tusd's `Location`, a stale `<id>.lock` removed by the
    cleanup step, a receipt-less commit refused, directories made and removed in the request,
    and a namespace directory replaced by a link to a directory outside the lake before the final
    PATCH (the hook answers 409 `SYMLINK_IN_LAKE`, the upload is `failed`, nothing is written
    outside the lake). `nginx -t` on the rendered configuration. Skipped without Docker.
  - `tests/integration/test_cli_end_to_end.py`: the skip mark of M11.7 removed. The API with a
    temporary lake, provisioned with `huron adm provision-orgs` in direct mode as the host user,
    so the directory verbs, `huron adm repair` and `huron adm check` run end to end.
  - `tests/unit/test_nginx_config.py`: the file has `listen 1080`, the upstreams on 1081 and
    `${HURON_API_UPSTREAM}`, `auth_request` in both `/files/` locations, the `OPTIONS` branch to
    `@tus_options` without `auth_request`, `proxy_set_header Forwarded ""` in the `server` block
    and no `proxy_set_header` in the two `/files/` locations and `@tus_options`, the cache key
    with `$request_method`, `proxy_no_cache` and `proxy_cache_bypass` with `$huron_no_cache
    $huron_no_auth`, `client_max_body_size 0` and `1m`, `proxy_request_buffering off`,
    `proxy_read_timeout 3600s`, `internal`, `proxy_pass_request_body off` and
    `proxy_cache_valid 204 30s`.
- Verification: `make gate`; `docker run --rm tusproject/tusd:v2.10.1 -help` lists every flag of
  the amendment's Components bullet (a name that differs is corrected in the bullet and in the
  stacks); `docker run --rm --entrypoint sh tusproject/tusd:v2.10.1 -c true` exits 0 (the lock
  cleanup needs `sh`); `docker compose -f docker-compose.app.yml config --quiet`; `docker compose
  -f docker-compose.uploads.yml config --quiet`; `bash -n scripts/e2e.sh`;
  `grep -rnE "upload_receipts|init-root|acl_backend" huron.dev.yaml scripts docker-compose.app.yml docker-compose.uploads.yml`
  prints nothing; `uv run pytest -m integration tests/integration/test_uploads_tusd.py
  tests/integration/test_cli_end_to_end.py`.
- Dependencies: M11.6, M11.8, M11.9.
- Status: pending

#### M11.11 Kustomize base and the local cluster

- Intent: the amendment's deployment as a kustomize base, and a running stack on the developer's
  own Kubernetes cluster: the kind cluster `ocp-test` on the development machine (one node,
  ingress-nginx at `https://127.0.0.1:18443`, the `local-path` storage class, the Route CRD
  without an OpenShift router; `kubectl` v1.37.1 is present, `helm` is not). The lake there is a
  local Linux filesystem, where setgid inheritance works, so this task does not wait for the
  measurement on the production export. The Helm chart and the production values are M11.13
  (decided 2026-11-07).
- Create or change:
  - `deploy/openshift/` (the base): `deployment.yaml` (the `huron-lake` volume at
    `HURON_LAKE_PATH`, `runAsUser`, `runAsGroup`, `supplementalGroups`); `route.yaml`
    (`haproxy.router.openshift.io/timeout: 300s`, because schema assignment, recursive repair and
    collection delete run their disk work in the request); `uploads.yaml`: the Deployment (one
    replica, `Recreate`; an init container, the tusd image with `sh -c`, that deletes `*.lock`,
    `*.lock.*` and `*.stop` in `.tus-uploads` before tusd starts; `proxy` and `tusd` with the
    pinned images; the security contexts; the claim; the nginx ConfigMap at `/etc/huron`; the
    `envsubst` environment `NGINX_ENVSUBST_TEMPLATE_DIR=/etc/huron`,
    `NGINX_ENVSUBST_TEMPLATE_SUFFIX=.template`, `NGINX_ENVSUBST_OUTPUT_DIR=/tmp`,
    `NGINX_ENVSUBST_FILTER=^HURON_API_UPSTREAM$` and `HURON_API_UPSTREAM`; for `proxy` `args:
    ["nginx", "-c", "/tmp/nginx-uploads.conf", "-g", "daemon off;"]` and never `command:`; an
    `emptyDir` with `medium: Memory` at `/tmp`; the probes; `nodeSelector`, `tolerations` and
    `affinity`), the Service `huron-uploads` on port 1080, the Route `huron-uploads` (path
    `/files`, timeout 3600s), the claim `huron-lake`. `kustomization.yaml`: the resources and
    the `configMapGenerator` `huron-uploads-nginx` from `nginx-uploads.conf.template`.
    `huron.yaml`: `lake_path`, `uploads_url`, `service_uid`, `service_group`,
    `upload_hook_timeout`. No `mount_prefix`, no NetworkPolicy.
  - `deploy/local/`: a kustomize overlay on `deploy/openshift`. A namespace `huron`; PostgreSQL
    as a one-replica StatefulSet on `local-path`; the claim `huron-lake` bound to a `hostPath`
    PersistentVolume (`ReadWriteMany`, one node) at a directory of the node; an Ingress for the
    API and one for `/files` with the ingress-nginx annotations `proxy-body-size: "0"`,
    `proxy-request-buffering: "off"`, `proxy-read-timeout` and `proxy-send-timeout` `"3600"`. The
    overlay removes the Routes, because no router serves them. The images are built from this
    repository with the tag `local` and `imagePullPolicy: Never`. `service_uid` and
    `service_group` equal the pods' `runAsUser` and `runAsGroup`. The migration Job. A one-shot
    Job `huron-lake-init` runs before the API starts. It uses the API image, which contains
    `scripts/dev-provision.py` and `scripts/devgroups.py` (the `Containerfile` gains
    `COPY scripts/dev-provision.py scripts/devgroups.py ./scripts/`). It reads the overlay's
    `deploy/local/huron.yaml` from a `configMapGenerator` of `deploy/local`. It runs
    `scripts/dev-provision.py --config <file>` from the image. No kustomize generator reads a
    file outside `deploy/local`. The script calls `Provisioner.provision` and writes `lake_path`
    (owner, mode `2751`, `.tus-uploads`, marker) and the organization roots with
    their markers. The Job runs as uid 0 in this overlay only, because it changes the owner of
    `lake_path`. `scripts/dev-provision.py` gains `--config` (default `huron.dev.yaml`).
    The root filesystem of the `api` container is read-only. So the overlay mounts an `emptyDir`
    at `/var/lib/huron-cli` in the `api` container and sets `XDG_STATE_HOME=/var/lib/huron-cli`
    there. The smoke writes `alice`'s token into that directory.
  - The identity provider of `deploy/local`: the overlay adds two containers to the API pod.
    Keycloak (the image of `docker-compose.yml`, `KC_HOSTNAME=http://127.0.0.1:8081`, the realm
    `scripts/keycloak/company-realm.json`) listens on 127.0.0.1:8081. The group directory
    (`scripts/devgroups.py` from the API image) listens on 127.0.0.1:8082. So `company_issuer`
    and `group_directory_url` have the values of `huron.dev.yaml` in the pod. `k8s-local.sh`
    creates the realm ConfigMap with `kubectl create configmap --from-file`, outside the
    kustomize render.
  - TLS of `deploy/local`: `k8s-local.sh` makes a local CA and a certificate for 127.0.0.1 with
    `openssl`, in `.k8s-local/` (ignored by git), and stores the certificate as the TLS Secret
    of both Ingresses. The smoke sets `SSL_CERT_FILE` (httpx) and `CURL_CA_BUNDLE` (curl) to
    that CA. The CLI gets no TLS option.
  - `scripts/k8s-local.sh` and the `Makefile` targets `k8s-local` (build the images, import them
    into the node with `docker save | docker exec <node> ctr -n k8s.io images import -`, so no
    `kind` binary is needed, apply the overlay, wait for the rollouts), `k8s-local-smoke` and
    `k8s-local-down`. `k8s-local-smoke` refuses to start when 127.0.0.1:8081 is in use (the
    compose stack). It runs `kubectl port-forward deploy/huron 8081:8081`, logs in with
    `scripts/dev-login.sh` as the platform administrator `alice`, creates a catalog and a
    collection, pushes a new, an overwritten and an empty file through
    `https://127.0.0.1:18443/files/` and commits. Then it runs
    `kubectl exec deploy/huron -c api -- huron adm check` as `U`, with `HURON_API_URL` set to
    the API in the pod, `HURON_MOUNT_PREFIX` set to `lake_path` and `alice`'s token written to
    the pod's `XDG_STATE_HOME`. The check prints no finding. Then the smoke deletes the
    collection. `k8s-local-down` deletes the namespace and the PersistentVolume. The node
    directory stays unless `K8S_LOCAL_PURGE=1`. The script refuses every kubectl context other
    than `K8S_LOCAL_CONTEXT` (default `kubernetes-admin@ocp-test`).
  - `deploy/README.md`: the base, the local overlay and its three targets, the lake claim, the
    pinned UID range, the service group, the export rules, tusd's lock files (hard links in
    `.tus-uploads`, removed by the init container), the install order ("Install order"), and a
    section "Helm: not yet delivered" that lists the work of M11.13.
  - `tests/unit/test_deploy_manifests.py`: `kubectl kustomize` of both directories renders; the
    upload Deployment has one replica, `Recreate`, the init container, `args:` and no `command:`
    for `proxy`; `huron.yaml` has no `mount_prefix`; the local overlay has no Route, has the four
    ingress-nginx annotations, has the Job `huron-lake-init` and has the containers `keycloak`
    and `groups` in the API pod. No `configMapGenerator` names a path with `..`. Skipped when
    `kubectl` is missing.
- Verification: `make gate`; `kubectl kustomize deploy/openshift`; `kubectl kustomize
  deploy/local`; `grep -rnE "mount_prefix|init-root|acl_backend" deploy/openshift deploy/local`
  prints nothing; on the development machine, `make k8s-local`, `make k8s-local-smoke` and `make
  k8s-local-down`.
- Dependencies: M11.10.
- Status: pending

#### M11.12 Documentation

- Intent: the user and operator documentation of the system as built, with the local cluster. The
  Helm chart and the production storage values are not delivered yet; the documentation says so
  and points to M11.13.
- Create or change:
  - `docs/operator.md`: the export rules; how to choose `U` and `G`; the restricted SCC and the
    pinned UID range; the API's mount; the upload pod and tusd's lock files with the init
    container; share groups and `provision-catalogs`; the `supplementalGroups` option for small
    sites (about 14 groups, and group-name resolution in the API pod); the install order
    ("Install order") with `provision-orgs` for `lake_path` and the organizations; the rule that
    the lake holds no symbolic link, with the `SYMLINK_IN_LAKE` answer and what the storage
    administrator does; who runs a complete `huron adm check` (an account in `G` and in every
    share group, or `U` with `oc exec deploy/huron -- huron adm check`); the findings table with
    `mode_drift`, `share_group_mismatch`, `unreadable` and `symbolic_link`; the sweep; the limit
    of AUTH_SYS (the read and write claims hold only against users who are not root on a client);
    the `hard` mount and readiness. No `local_lock` advice, no `flock` check, no NetworkPolicy.
  - `docs/operator.md`, section "Setgid measurement (pending)": the measurement is not recorded
    yet. The section gives the procedure of "Facts about the storage (measured 2026-11-06)": as
    root, make `t` on the real export with owner `U`, group `S` and mode `2750`, where `U` is not
    in `S`; as `U`, with `umask 022`, run `mkdir -m 0750 t/d; touch t/f; stat -c '%a %U %G' t/d
    t/f`, and expect `2750 U S` and `644 U S`; as root, run `chgrp S t/d; chmod 2750 t/d` and
    `stat -c '%a %G' t/d`, and expect `2750 S`; record the date, the `stat` lines and the volume
    security style (UNIX, NTFS or mixed) in that plan bullet.
  - `docs/operator.md`, section "Local cluster": `make k8s-local`, `make k8s-local-smoke` and
    `make k8s-local-down` on the kind cluster `ocp-test`, `K8S_LOCAL_CONTEXT` and
    `K8S_LOCAL_PURGE`, the `hostPath` lake and the Job `huron-lake-init`.
  - `docs/operator.md` and `deploy/README.md`, section "Helm: not yet delivered": the chart has
    no upload pod, lake volume or upload keys yet. The notes list what M11.13 adds (the values
    and their schema, the Route and the Ingress with the ingress-nginx defaults, the nginx
    ConfigMap, the lake volume and security context) and its gate, the recorded setgid
    measurement.
  - `docs/user-guide.md` (push without the mount, resuming, the 401 and 403 explanations, a final
    PATCH that answers 500, 502 or 504, `huron adm repair` with `reason` and `detail`, the
    share-group options), `docs/architecture.md`, `docs/concepts/raw-ingest.md`,
    `docs/concepts/how-huron-works.md`, `docs/concepts/access-and-roles.md`,
    `docs/web-design.md` and the other pages
    that say that the CLI writes the share or that the lake has ACLs, and `README.md`.
    `docs/api-errors.md` is complete (`SYMLINK_IN_LAKE` included, no `OUTSIDE_LAKE`, no
    `ACL_FAILED`).
  - The server side of an organization without a root is `<lake_path>/<name>`, not
    `<mount_prefix>/<name>`: `docs/operator.md` (the organization rules and the provisioning
    text) and `docs/architecture.md` (the organization directory). The CLI's `mount_prefix`
    stays only where a page describes the workstation's read-only mount or the provision
    commands (section 6.1).
  - Section 3, sections 4.1, 6 and 12, ADR 0008, `CONTEXT.md` and `AGENTS.md` already carry the
    revision. This task changes them only where the built system differs, with a line in its
    Execution notes.
  - Found in M11.8a's verification: `docs/concepts/access-and-roles.md` (about line 191) and
    `docs/concepts/raw-ingest.md` (about line 336) link to the removed anchor
    `/docs/reference/cli/adm/#huron-adm-apply-acl`. No check validates anchors, so remove or
    replace both links. `docs/architecture.md` (about line 199) still says the CLI writes
    `metadata.json`.
  - Found in M11.9a's verification: `deploy/README.md` (about line 107) has the comment "create
    <root>/<org>, apply the ACLs, write the marker", which the task's grep does not catch.
    `README.md` (about lines 163 and 173) still describes `acl_backend`.
- Verification: `make gate` (`scripts/ste_check.py` included); `make docs-check`;
  `grep -rniE "init-root|apply-acl|acl_backend|setfacl|getfacl|OUTSIDE_LAKE|version 1 migration" docs README.md deploy/README.md --exclude-dir=adr`
  prints nothing; `grep -c "Helm: not yet delivered" docs/operator.md deploy/README.md` counts
  at least 1 in each file; `grep -n "Setgid measurement (pending)" docs/operator.md` finds the
  section; `grep -nE "<mount_prefix>/<(name|org)>" docs/operator.md docs/architecture.md` prints
  nothing.
- Dependencies: M11.11.
- Status: pending

#### M11.13 The Helm chart and the production values

- Intent: the chart part of the old M11.11 and the production storage settings, after the setgid
  measurement on the production export is recorded.
- Create or change:
  - `deploy/helm/huron` (the chart of M10.6): `templates/uploads.yaml` with the init container,
    the `args:` and the environment of the base, and scheduling from `uploads.nodeSelector`,
    `uploads.tolerations` and `uploads.affinity`; its Route and its Ingress; the nginx ConfigMap
    from `files/nginx-uploads.conf.template`, a byte-identical copy of
    `deploy/openshift/nginx-uploads.conf.template`. `HURON_API_UPSTREAM` and tusd's
    `-hooks-http` use `{{ include "huron.fullname" . }}:{{ .Values.service.port }}`. The Ingress
    takes `uploads.ingress.annotations`, with the ingress-nginx defaults
    `nginx.ingress.kubernetes.io/proxy-body-size: "0"`,
    `nginx.ingress.kubernetes.io/proxy-request-buffering: "off"`, and
    `nginx.ingress.kubernetes.io/proxy-read-timeout` and `proxy-send-timeout` `"3600"`.
  - `templates/deployment.yaml`: the lake volume and the security context. `route.timeout`
    defaults to `300s`. The upload keys go into `huron.yaml` from `lake.*`, `serviceUser.*` and
    `uploads.*` unless `config` sets them. `values.yaml`; `values.schema.json` (uid, gid, group
    and claim required when `uploads.enabled`; hook timeout at most 55m);
    `ci/example-values.yaml` (uploads on); `NOTES.txt`. No NetworkPolicy template.
  - The chart text of the old layout: `NOTES.txt` names `huron adm provision-orgs` for
    `lake_path` and the organizations in place of `scripts/init-root.sh`. The `organizations`
    comment of `values.yaml` and the `root` description of `values.schema.json` say that an
    organization without a root lies directly below `lake_path`. The comment of `web.mountPrefix`
    in `values.yaml` says that it is where clients mount `lake_path`; the key stays, because the
    web shows client paths.
  - The production values follow the recorded measurement: when setgid inheritance or the
    `chgrp` step failed on the export, this task stops and the plan gets an escalation; it does
    not change the modes of "Catalog share group and directory modes".
  - `docs/operator.md`: the Helm and production storage sections, with the recorded result in
    place of "Setgid measurement (pending)". `docs/operator.md` and `deploy/README.md`: the
    sections "Helm: not yet delivered" go.
  - `tests/unit/test_nginx_config.py`: the two copies are equal.
- Verification: `make gate`; `helm lint --strict deploy/helm/huron -f
  deploy/helm/huron/ci/example-values.yaml` and `helm template huron deploy/helm/huron -f
  deploy/helm/huron/ci/example-values.yaml` (`helm` v3; where it is not installed, the same
  commands in `docker run --rm -v "$PWD:/w" -w /w alpine/helm:3.16.4`); `kubectl kustomize
  deploy/openshift`; `grep -rn "Helm: not yet delivered\|Setgid measurement (pending)" docs
  deploy` prints nothing; `grep -rnE "init-root|acl_backend|<mount_prefix>/|the CLI's mount_prefix"
  deploy/helm` prints nothing; `cmp deploy/openshift/nginx-uploads.conf.template
  deploy/helm/huron/files/nginx-uploads.conf.template`.
- Dependencies: M11.11, M11.12, and the setgid measurement recorded under "Facts about the storage
  (measured 2026-11-06)".
- Status: pending

## 12. Risk register

| Risk | Effect | Mitigation |
| --- | --- | --- |
| LDAP group changes propagate slowly to NFS clients and servers. | A newly granted user is refused on disk for a while. | Documented. The CLI's error on `EACCES` names the catalog's share group. |
| Another user commits a path between the API's link and its receipt. | The commit records the earlier hash while the disk holds the later bytes. | Accepted, no `placing` state. Receipts are per user and only the latest placement counts. `huron adm check --hash` reports `file_changed`. |
| Concurrent pushes to one collection. | Lost updates. | `base_version` on every commit; the working copy `flock`; the race test in M4.3. |
| Schema assignment turning many collections `incomplete` at once. | Surprise for contributors. | The assignment response reports counts; `huron check` lists them; drafts are unaffected. |
| Catalog names are global. | Two organizations want the same name. | Stated in D-2; organizations can prefix; revisiting it is a plan amendment. |
| A machine mounts an organization's export at another path, or not at all (amendment 2026-10-31). | The API writes into the wrong tree, or a check reads it. | Per-organization markers carry the instance and the organization and are checked inside `Mount`; `huron adm verify-mounts` lists every organization's state; hints name the configured `export`. |
| Replicas run different configurations during a rollout. | A replica of the old configuration that restarts reconciles the database back to it until the rollout ends. | Reconciliation runs under the bootstrap advisory lock and is idempotent; the Helm chart's `checksum/config` rolls every pod to one configuration; undeclared organizations are never deleted. |
| Loopback or device login unavailable on a cluster node. | No way to log in. | Both flows exist; `tokens.json` can be copied between machines of the same user (documented, mode checked). |
| The export trusts UIDs (AUTH_SYS). | Any process on a read-write client that claims `U` can write the lake. Root on any client can read every file, whatever the share groups say. | Read-write only for the clients of the API pod and the upload pod. The claim is bound to Huron's namespace. The restricted SCC keeps other namespaces out of `U`'s range. Kerberos (`sec=krb5`) is the upgrade path. |
| tusd runs one replica. | A rollout or a crash interrupts uploads. | `Recreate`, because tusd's test that a lock file's PID is alive works only inside one PID namespace. tus clients resume from the last offset. |
| The API holds the writable mount. A bug in the API, or a compromised API pod, can change any file of the lake. | Data loss that only ONTAP snapshots undo. | The API writes only through `core.storage.Storage` on `LakePath`, under `LakeDisk.hold`, which checks the marker first. Every path is built from validated names and opened from the root with no follow of a symbolic link, so no write leaves the lake. The API never deletes outside a collection's own entries. Snapshots stay the only history. The upload pod writes only `.tus-uploads`. |
| A symbolic link appears in the lake (made by root, or by a process on a read-write client). | A write or read through it could leave the lake, or reach another catalog's data. | The no-follow traversal (section 3, "Containment in the lake"): every lake path is opened one name at a time with `O_NOFOLLOW` from a descriptor of the root, so the kernel refuses a link at any step. The API answers 409 `SYMLINK_IN_LAKE` and changes nothing; repair reports `symbolic_link`; `huron adm check` reports the error finding `symbolic_link`. Huron calls `symlink` nowhere and places with hard links only. The storage administrator removes the link. |
| The API hashes each upload inside `pre-finish`, in the request. | A large file holds a disk worker and the client's final PATCH for minutes. tusd waits at most `upload_hook_timeout` for the hook, retries included, then answers the final PATCH with 500 while the API call continues. | `upload_hook_timeout` sized for the largest file (at most 55 minutes), nginx and Route timeouts of 3600 s, the hash outside the path lock, idempotent placement, the CLI's read of `GET /api/v1/uploads/{id}` after a 500, 502 or 504, and `huron adm check --hash`. |
| The receipt fails after the link (the collection was deleted, or the creator terminated the upload during the hash), or the API stops between the link and the receipt. | A placed file without a row that removes it. | A failed receipt unlinks the destination when its inode is the placed inode and removes the empty directories that the placement made. A stop between the link and the receipt is an accepted residual that `huron adm check` reports as `file_unrecorded`. |
| A removal races a placement of the same path on another API replica. | The removal unlinks the file the placement just linked. | The inode guard: a removal unlinks only the inode it recorded, which the receipt read with `fstat` on the hashed file. On one replica the path lock closes the race. Across replicas a narrow window between the `stat` and the unlink remains, and `huron adm check --hash` detects its result. |
| The inode guard compares numbers, and the filesystem can give a deleted file's inode number to a new file. | A removal can unlink a newer file at the same path. | Accepted: the guard is strong, not exact. `huron adm check` reports `file_missing` for a recorded file that a removal unlinked. A removal without an inode (a file committed by an API without a lake) finishes with no disk call (M11.6), so no unlink is unconditional. |
| Setgid inheritance of the group on the ONTAP export over NFSv3 is not measured. | New directories below a catalog do not get the share group, and readers cannot reach them. | The measurement of section 6.2, recorded before M11.13 starts. The API runs `stat` after each `mkdir`: a failed inheritance is `STORAGE_FAILED` or `mode_drift`, never silent. |
| tusd stops uncleanly. Its lock files (`<id>.lock`, which holds tusd's PID, and `<id>.stop`) stay in `.tus-uploads`. tusd is PID 1 in its container, so the new tusd sees its own PID as alive. | Every HEAD or PATCH of an affected upload ends in a lock timeout. | An init container of the upload pod (the tusd image, `sh -c`) deletes `*.lock`, `*.lock.*` and `*.stop` in `.tus-uploads` before tusd starts. This is safe with one replica. The sweep removes every entry older than `upload_ttl`. |
| An evicted upload pod's replacement starts while the old pod is still terminating. | The init container deletes a lock that the old tusd still holds, and an in-flight PATCH of the old pod can overlap a new request for the same upload. | Accepted. The old pod is out of the Service, so only a PATCH that was already in flight can overlap. tus clients resume from the offset that tusd reports. |
| An NFS outage on the `hard` mount. | Disk calls block without end, in the API and in the upload pod. | `/readyz` runs the lake probe in a thread with a 2 s limit and keeps the result for 10 s, so the API pods leave the Service. Browsing stops too. Disk work runs in its own pool of 8 workers, so blocked disk calls do not take the default executor. |
| Directory verbs on two API replicas race: a delete and a create of the same name. | A directory is missing for a row that exists. | A `mkdir` that meets an existing empty directory adopts it, and any other existing entry is `STORAGE_FAILED` with the rows kept. Repair reads rows only and checks them again before each `mkdir`, under each directory's path lock. A residual case reports `namespace_dir_missing` or `collection_dir_missing`, and `huron adm repair` fixes it. |
| `U` cannot `chgrp` a catalog directory to its share group. | New catalogs are readable by nobody until the group is set. | The create and set responses carry `SHARE_GROUP_PENDING`, `huron adm check` reports `share_group_mismatch`, and `huron adm provision-catalogs --emit-script` prints the root step. Small sites list the groups in the API pod's `supplementalGroups` (about 14 fit) and make the group names resolvable in the pod. |
| Production starts from scratch (decided 2026-11-07). The test-bed lake has entries that Huron did not make. | An install that reuses old data has entries with other owners and modes, which the plan does not convert. | The install order of section 3 ("Install order") starts from an empty `lake_path`: `provision-orgs` changes the owner of the lake path and the organization roots only, with no recursive step. Every later entry is made by `U` through the API. `huron adm check` reports `mode_drift`, `share_group_mismatch` and `symbolic_link` for any entry that does not fit. |
| The upload pod is down. | Uploads fail. Nothing else waits. | One replica with `Recreate`, readiness through `/readyz`. tus clients resume from the last offset. |
| The namespace's UID range changes (the namespace is created again). | Both pods run as another UID and cannot write the lake. | The cluster administrator pins `openshift.io/sa.scc.uid-range`. `/readyz` fails when `.tus-uploads` is not writable. |
| A cached allow of the upload proxy outlives a token or an upload. | For at most 30 seconds, a request passes nginx that the API would refuse. | Allows only, 30 s, cached in a memory-backed `emptyDir` that only nginx reads. The cache key holds the method, the upload id and the `Authorization` value, and a request without `Authorization` never uses the cache. nginx sends OPTIONS to tusd without a subrequest, so no OPTIONS answer is cached. The cache holds the token value for at most 60 seconds after the last request of that upload and token. tusd refuses an upload whose files are gone. |
| The bearer token is the only credential of an upload, and it lives `token_ttl_seconds` (8 hours by default). | A leaked token lets its holder upload to the collections of its user until it expires. | No change in this milestone. An operator can set a shorter `token_ttl_seconds`. The hooks route gives a direct caller nothing beyond their own rows. |
| A process in the upload pod reaches tusd on 127.0.0.1. | It bypasses the authorization. | Only Huron's containers run in the pod. No Service selects 1081. Accepted for `make app`. |

## 13. Definition of done

- Every task in section 11 is `complete` with a verifier's note.
- `make gate`, `uv run pytest -m contract` and `uv run pytest -m integration` are green on `main` after
  the merge; CI runs all three.
- The service deploys from `deploy/openshift` and from `deploy/helm/huron` and answers `/readyz`.
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

## Escalation

Written 2026-11-06 by the `/implement-markdown` orchestrator. Milestone 11's first task, M11.1 "The
uploads area, its stores and receipts in commits", failed its third verification, so the workflow
stopped as its iteration cap requires. M11.2–M11.8 were not started.

### State of the tree

Uncommitted on branch `tusd-integration`. The working tree builds and the full gate passes
(`make gate`: 1070 passed, TOTAL 8123 statements, 5 missed, all pre-existing; `pytest -m contract`:
46 passed, three runs). Nothing was reverted: every change is complete and green, and the open
items below are additions, not breakage. M11.1's status stays `in progress`.

### Verification reports

**Verification 1 — FAIL** (gate green).
1. (medium) A commit accepted a receipt that no longer described the file on disk: a later placement
   of the same key links new bytes over the destination, but any matching receipt of the committer
   was accepted. Reproduced: user A placed `a.txt` (sha `a…`), user B placed `a.txt` (sha `b…`), A's
   commit recorded `aaaa`.
2. (small) `claim_removals` did not bound its limit (`clamp_limit`).
3. (small) `uploads.commit_id` and `removals.commit_id` had no foreign key or index.
4. (small) No CHECK constraints tied an upload's state to its columns.
5. (small) Duplicated test helper (`settled_collection` vs `active_collection`).
6. (small) Misleading test name and variable.
7. (nit) One-line wrapper `_proves`.
Plan-level notes: a collection delete cascaded queued removals and placed uploads, stranding files;
removal cancellation by key on a case-sensitive share. Resolved by the orchestrator as the dated
refinements of the Removals bullet and the new "Latest placement wins" bullet.

**Verification 2 — FAIL** (gate green; items 1–8 of attempt 1 confirmed fixed).
1. (medium) A receipt landing during a collection delete left an orphaned file with no removal
   queued: the receipt locked only the upload row. Reproduced on PostgreSQL.
2. (small) Stale sentence in the M11.1 Execution notes.
3. (small) No nested-namespace test for `removal_still_valid`.
4. (nit) `Removal` built in two places; the directory and `rel_path` join repeated.
Risk judged plan-level and accepted by the orchestrator: between the sidecar's link and its receipt
the bytes on disk have already changed; recorded in the "Latest placement wins" bullet.

**Verification 3 — FAIL** (gate green; items 1–4 of attempt 2 confirmed fixed; race test proven to
fail without the fix, 12/12 green with it).
1. (small, blocking) `Uploads.begin` reads the collection without locking it, then inserts the
   upload row; a collection delete committing in between raises an unmapped
   `asyncpg.ForeignKeyViolationError` (a 500 at pre-create). Reproduced on PostgreSQL. Correction:
   lock the collection row in `begin` (`find_collection(..., lock=True)`), add a race test, extend
   the lock-order docstring and Execution notes. Verifier: fixable within the plan.
2. (small) The `UPLOAD_RECEIPT_MISSING` row of `docs/api-errors.md` omits that a later upload to the
   same path, by any user, cancels a receipt. Verifier: fixable within the plan.
3. (nit) The race test's `pg_locks` polling loop has no deadline and does not filter by database.
   Verifier: fixable within the plan.

### Diagnosis

The plan-as-written is implementable; the verifier of attempt 3 classed every open item as fixable
within the plan. What failed is the amendment's concurrency specification. It defined the upload
operations and their states but no lock discipline, so each verification found the next unguarded
interleaving in turn: stale receipts (attempt 1), receipt against collection delete (attempt 2),
begin against collection delete (attempt 3). M11.1 also combined a new domain area, two stores,
a migration and a change to commits, which made one pass large for one implementer.

### Design questions before implementation resumes

1. Lock discipline for every upload operation, stated once in the amendment: which operations lock
   the collection row (begin, receipt, commit, collection delete; placement, fail, terminate,
   claims), in what order, and how each race with a collection delete surfaces (a domain error, never
   a database error).
2. Whether the link-to-receipt window stays an accepted risk, or placement records a "placing" state
   that commits respect (and how a crashed sidecar releases it).
3. Whether the remaining tasks of Milestone 11 should be split smaller before they run (for example
   M11.2's routes apart from its settings, and M11.4's hooks apart from its workers).

### Resolution (2026-11-06)

The user answered the design questions in the session instead of through `/architectural-review`.
Question 1 is the amendment's "Lock order" bullet. Question 2 keeps the window as an accepted risk.
The user approved one fix pass and one verification beyond the cap for M11.1, limited to the three
open items of verification 3. On the evening of 2026-11-06 the user revised the design again. The
API holds the writable mount and places each upload itself. There is no sidecar and no task queue
for changes on disk. There are no ACLs, because the export does not support them. Read access on
disk is one POSIX group per catalog. Question 3 is answered by the new task list of Milestone 11:
each task fits one implementer in one pass. On 2026-11-07 the user accepted the review rulings
that changed design decisions: tusd locks with hard-linked lock files, not `flock`; tusd retries a
hook on a transport error or any 5xx inside one timeout; M11.11 and M11.12 wait for the setgid
measurement in "Facts about the storage"; there is no NetworkPolicy; nginx answers `OPTIONS`
without the auth check; `pre-finish` hashes outside the path lock; the old M11.2 is split, so the
milestone has M11.2 to M11.12. The user also kept the nginx check because the upload Route can
later be exposed to the internet.

**Verification 4 — FAIL** (gate green as measured by the verifier; items 1–3 of verification 3
confirmed fixed, the forced race test reproduced without the lock). One small item: the `uploads`
index `(collection_id, rel_path_key, created_by, state)` outlives the query that needed
`created_by`; the remaining queries use the `(collection_id, rel_path_key)` prefix, and `state`
changes on every transition. Correction: a two-column index, renamed in the unreleased migration.
Plan-level wording of the "Lock order" (finishing a removal is a plain delete) and "Removals" (the
latest-placement condition) bullets corrected by the orchestrator. A fix limited to the index and a
confirmation verification follow.

**Confirmation verification — PASS** (gate green as measured by the verifier: 1072 passed, 99.94%
coverage with the five pre-existing missed lines, 48 contract tests; the tree unchanged outside the
index files and the plan). M11.1 is complete. The remaining design decisions of 2026-11-06 (the
read-only share, per-request authorization in front of tusd) are recorded in the amendment's dated
bullets below this section's date, and the revised tasks M11.2 onward follow from them.

## Escalation (M11.5, 2026-11-07)

M11.5 "Directory verbs and repair in the API" failed verification 3 of 3. The workflow stopped
there, as the iteration cap requires. The working tree holds the uncommitted M11.5 code on top of
commit 5800e25a; the full gate passes on it (`make gate` exit 0, 1487 tests, 99.96% coverage, 59
contract tests, web check/test/lint), so no revert was needed. M11.1 to M11.4 are committed and
verified.

### Verification reports

**Verification 1 — FAIL** (gate green). Four medium and seven small defects, each reproduced with
a probe: (1) a recursive repair walked outside its target (a sibling namespace's directory went
from `2770` to `2750`); (2) repair ran `chmod 2750` on directories outside the service's groups,
which silently clears setgid under AUTH_SYS; (3) repair hid a failed `metadata.json` create; (4)
the `.huron-prev` backup was lost on a crash between the rename and the cleanup, then a refused
receipt; (5) organization repair did not restore `2751`; (6) `..` answered `OUTSIDE_LAKE` with a
lake and `NAME_INVALID` without; (7) a dry-run delete needed the lake; (8) the backup hook test did
not overwrite a committed file; (9) `LakeDirectory` used private members of `LakeDisk`; (10)
organization repair did not re-read the row before `mkdir`; (11) the pool test also passed with
one shared pool. All eleven were fixed in the next pass and confirmed fixed by verification 2.

**Verification 2 — FAIL** (gate green; all eleven items of verification 1 confirmed fixed). Two
medium and three small defects: (1) one unreadable directory stopped a whole recursive repair; (2)
a raw `PermissionError` from a walk escaped the verbs as 500 `INTERNAL`; (3) repair ran `chmod` on
a regular file at a planned directory path; (4) `organization_directory` did not read the
organization row (`%2E%2E` answered `OUTSIDE_LAKE` with a lake, 404 without); (5) `in_group`
trusted more than the 16 groups AUTH_SYS carries. All five were fixed in the last pass, which also
mapped every filesystem query of `PosixStorage` to `StorageError` (a same-class residual it had
reported itself). Verification 3 confirmed all five fixed.

**Verification 3 — FAIL** (gate green; verification 2's items and a spot check of verification 1's
items confirmed). One finding with two paths, both reproduced on real filesystems (the lake on one
tmpfs, a target on another):
1. medium — Schema assignment writes `metadata.json` through a symlink onto another filesystem.
   `assign_catalog_schema` locates only the catalog directory; each settled collection's write
   goes to `directory.joinpath(...)`, which nothing resolves or checks. A `PATCH` of the same
   collection answers 422 `OUTSIDE_LAKE`, but `PUT /catalogs/{catalog}/schema` answers 200 and
   rewrites the file on the other filesystem. Verifier: fixable within the plan (a filesystem
   check before each write, in the worker under the path lock; a mismatch after the commit
   answers `STORAGE_FAILED`).
2. small to medium — A recursive repair can `chmod` an unsearchable ancestor (`0o2000` to `2750`)
   and then, in a later step, write below it onto another filesystem: every planned directory is
   located once, before any disk work, and a path below an unsearchable directory is checked only
   at its nearest visible ancestor. Verifier: fixable within the plan (re-run the check for each
   step's path in the worker, under the lock, after `verify_marker`). The old `os.path.lexists`
   behaved the same way.
Residual risks noted, not failures: the recursive walk does not compare `st_dev`, so it would
enter a mount point below its target; a symlink to another organization on the same filesystem
passes the device check.

### Diagnosis

The defects of the three rounds share one cause: the plan states containment ("the API refuses a
path that resolves outside `lake_path` or onto another filesystem") as a single check before the
transaction, but M11.5's disk work is not a single write. Schema assignment writes many files, and
a recursive repair changes permissions and then writes below the directories it changed. A check
made once at the start does not hold for later writes (a time-of-check to time-of-use gap), and
the plan has no policy for symbolic links inside the lake. The version 1 directories make this a
real exposure, not a theoretical one: until the storage administrator's `chown` step, they belong
to the users who made them, so a user can plant a symlink or a mount point there. Each fix closed
the instance a verifier found, and the next verifier found another instance of the same gap.

A second cause is size. M11.5 grew to three parts in one pass (directory verbs and repair, the
separate hash pool, and the overwrite backup, the last two added on 2026-11-07), and the repair
walker alone needed rules for unreadable, unsearchable, vanishing, non-directory and
foreign-group entries that the plan specified only in outline.

### Design questions to answer before M11.5 resumes

1. Containment model: is the filesystem check made at every write, under the path lock, in the
   disk worker (per-write check), or does all disk work open paths component by component from a
   directory descriptor of `lake_path` with `O_NOFOLLOW` (or Linux `openat2` with `RESOLVE_BENEATH
   | RESOLVE_NO_XDEV`), so that a symlink or a mount point is refused by the kernel?
2. Symbolic links in the lake: refused everywhere (every write and every walk), refused only
   when they leave `lake_path` or the filesystem, or reported by `huron adm check` as a new
   finding?
3. Version 1 trees: may repair act at all on a directory that `U` does not own (before the
   storage administrator's step 2), or does it only report such directories, so that no repair
   can be steered through a user-controlled tree?
4. Mount points: does the recursive walk stop at a change of `st_dev`, and does any write refuse
   one?
5. Task size: should M11.5 be split (for example: directory verbs and `metadata.json`; repair and
   its walker; the overwrite backup and the hash pool), each verified on its own?

### Resolution input (2026-11-07, the user's answers to the design questions)

- Symbolic links: Huron never creates one. Placement uses hard links only (it "moves" a tus upload
  into its collection under its final name). No symbolic link is allowed anywhere in the lake: the
  API must not follow one, and data must never be outside the lake. The old NFS-copy write path of
  version 1 (the CLI copying bytes over the mount: `copy_in`, `.huron-part` pushes,
  `write_sidecar`, the CLI-side directory writes) is no longer used and is to be removed, not kept
  for compatibility.
- Version 1 directories: there are none. The current lake is test-bed data, and production is
  deployed from scratch. The plan's "Version 1 directories" migration (directories owned by
  their users, the `chown -R` root step for them, the `0660` file repair, the order of a version 1
  migration) is to be dropped.
- Mount point: the lake's mount point for a deployment does not change. Huron adds organizations,
  catalogs, namespaces, collections and files in collections, and nothing else. No mount-point or
  `st_dev` check per write is needed; containment comes from building every path from validated
  names below `lake_path` and refusing symbolic links.
- Task size: yes, split M11.5.
- Process: run the next steps under the workflow's rules (`/architectural-review`, then
  `/design-plan`), seeded with this section.

### Resolution (2026-11-08)

The user answered the design questions in "Resolution input (2026-11-07, the user's answers to the
design questions)". The architectural review then ran, and its record is `architectural_review.md`
at the repository root; its section "S: Synthesis" is binding where it resolves a conflict between
R1 to R6. On 2026-11-08 the user chose to save the whole uncommitted M11.5 tree on the branch
`m11.5-escalated` and to rebuild M11.5 from commit 5800e25a. No task deletes that branch. The
orchestrator deletes it only after the rebuild, and only when the user confirms.

Three statements of `architectural_review.md` are wrong, and this plan overrides them:

- "S: Synthesis", row 8, and the deletion list say that M11.5e deletes the branch
  `m11.5-escalated` and that `git branch --list m11.5-escalated` prints nothing. No task deletes
  the branch. M11.5e verifies that the branch still exists.
- The review says that the `os.walk` of `src/huron/applications/cli/sync.py` goes and that it is
  in `_copy_files`. The only `os.walk` in `sync.py` is in `_collect`. It walks the user's local
  source folder for push staging, and it stays.
- The review names the log event `disk.symlink_found`. The event is `disk.link_found` (M11.5d).

The new task list
of Milestone 11, M11.5a to M11.13, answers the questions:

1. Containment model: no per-write check. Every disk operation opens its `LakePath` from a
   descriptor of the root, one name at a time, with `O_NOFOLLOW` (section 3, "Containment in the
   lake"; M11.5c).
2. Symbolic links: refused everywhere. A write or read through a link answers 409
   `SYMLINK_IN_LAKE`; a walk reports a link and never enters it; `huron adm check` reports
   `symbolic_link`. Huron makes none and places with hard links only.
3. Version 1 trees: there are none. Production starts from scratch ("Install order"), and repair
   acts only on the directories that the rows plan, with no walk (M11.5e).
4. Mount points: the mount point never changes. No walk or write compares `st_dev`, and
   `OUTSIDE_LAKE` does not exist.
5. Task size: M11.5 is split into M11.5a to M11.5e. The removal of the NFS-copy path (M11.7), of
   the CLI's lake writes (M11.8a) and of the ACL code (M11.9a) runs before M11.5b. M11.11 is the
   kustomize base and the local-cluster overlay; M11.13 holds the Helm chart and the production
   values and waits for the setgid measurement.

The old text of M11.5 "Directory verbs and repair in the API", with its execution notes, is
replaced by these tasks. This escalation is resolved by the split.
