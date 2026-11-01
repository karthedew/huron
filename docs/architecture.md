# Architecture

Huron catalogs raw scientific data that lives on an NFS share and enforces who may read and write
it. It has four parts:

| Part | Runs on | Does |
| --- | --- | --- |
| `huron-api` (FastAPI) | OpenShift (Helm chart or Kustomize base) | Exchanges company logins for Huron tokens; holds organizations, catalogs, namespaces, collections, recorded files, the schema registry, role grants and the audit log; never touches file bytes. |
| PostgreSQL | OpenShift or managed | Schema `huron`, Alembic revisions under `migrations/versions/` (`0001_huron`, `0002_organization_catalog_roles`). |
| `huron` CLI | Machines that mount the share | Logs in, browses, walks users through metadata, creates directories with ACLs, copies files over the mount, commits them, reports drift. |
| `huron-web` (SvelteKit) | A Node.js server, one replica | Signs people in with the company IdP and shows the catalog in a browser: organizations, catalogs, namespaces, collections and search. Read-only; keeps its sessions in memory. |

## The model

```text
Organization ─┬─ Catalog (unique name, one assigned schema) ─┬─ Namespace ─┬─ Namespace …
              │                                              │             └─ Collection (draft → active ⇄ incomplete)
              └─ …                                           └─ …                  └─ recorded files
```

- Identifiers are dotted: `catalog.namespace.child.collection`. The organization appears only in the
  directory path: `<root>/<org>/<catalog>/<namespace…>/<collection>/`, where `<root>` is the
  organization's configured root or, without one, the CLI's mount prefix (see
  [Organizations and their roots](#organizations-and-their-roots)).
- A namespace holds collections only when `collections_allowed` is set. A namespace and a
  collection never share a name under one parent (a database trigger enforces it).
- A collection has one integer `version`, bumped by every change. It is the `ETag`, and every
  commit carries the version it was prepared against; a stale commit is refused with
  `BASE_VERSION_CONFLICT` until the user runs `huron pull`.

## Roles

Five fixed roles, each a bundle of named privileges (modeled on Polaris catalog roles), granted to
LDAP groups — never to individual users:

| Role | Scope | Highlights |
| --- | --- | --- |
| Platform Admin | platform | create organizations, publish platform schemas, rotate signing keys |
| Org Admin | organization | create catalogs, appoint catalog admins, publish organization schemas |
| Catalog Admin | catalog, or organization (every catalog of it) | namespaces, schema assignment, reader/contributor groups, delete any collection |
| Contributor | catalog, or organization (every catalog of it) | create collections, edit metadata, push files, delete their own collections |
| Reader | catalog, or organization (every catalog of it) | browse, search, read files, read the audit log |

The Huron token carries the user's LDAP groups as fetched at login. Every request maps those
groups to roles through the current grants, so a revoked grant takes effect immediately and a
changed LDAP membership at the next login. Objects the caller cannot see answer 404.

## Organizations and their roots

The service configuration may declare the organizations (`organizations` in the YAML file named by
`HURON_CONFIG_FILE`, or a Helm value): each with its display name, its `groups` (the exact LDAP
groups of each organization-wide role: `org_admin`, `catalog_admin`, `contributor`, `reader`) and,
optionally, a root, the parent directory of the organization's directory on its own NFS export. Every
catalog of the organization, existing or future, inherits the three catalog roles; a grant on one
catalog adds groups to them and cannot remove an inherited one. With a declaration the service is in
managed mode. At startup, under an advisory lock so replicas take turns, it creates the declared
organizations that are missing, updates their names and descriptions and sets all four
organization-scope role sets exactly, and writes nothing when nothing changed. An organization
removed from the configuration is logged and kept, never deleted. While managed, the API refuses to
create organizations, to delete declared ones and to edit any of their four organization-scope role
sets (409 `ORGANIZATION_DECLARED`).
Without a declaration organizations are created with `huron create org`, as before. The record is
[ADR 0007](adr/0007-declared-organizations.md).

Roots are configuration, not database rows, and the service never opens them. The API reports
paths relative to a root, starting with the organization's name (`helio/heliophysics/…`), and adds
the root: `root` and `path` on an organization, `share_root` on its catalogs, namespaces and
collections. The CLI and the web join `share_root` and the relative path, or use their own mount
prefix when `share_root` is `null`:

```text
organizations:                                 on the machines that run the CLI
  - {name: helio, root: /data1/huron}    ──▶   /data1/huron/helio/heliophysics/solar-wind/…
  - {name: geo,   root: /data1/huron}    ──▶   /data1/huron/geo/geoscience/…
  - {name: astro}  (no root)             ──▶   <mount_prefix>/astro/…
```

## Metadata schemas

The registry holds versioned JSON Schema documents at platform or organization scope. Every schema
extends `huron-base` (title and description required) directly or through another schema.
Composition merges properties and unions required fields; a child may not change the type of a
required property. Each catalog is assigned one registry entry; a collection may add an override
that is composed on top. Assigning a schema re-validates every settled collection of the catalog:
failures become `incomplete`, passes `active`.

## Request path

```text
huron CLI ──HTTPS──▶ Route ──▶ huron-api ──▶ Authorizer(grants) ──▶ lake operation ──▶ PostgreSQL
    │                           ▲
    └─ company OIDC login ──────┘ POST /api/v1/auth/exchange → Huron ES256 token (groups inside)

browser ──session cookie──▶ huron-web ──Bearer Huron token, GET only──▶ huron-api ──▶ …
   │                           ▲  │
   │                           │  └─ POST /api/v1/auth/exchange: company ID token → Huron token
   └─ company OIDC login ──────┘ code flow with PKCE
```

## The web

`huron-web` (`web/`) is a backend for the browser. Its server runs the company OIDC sign-in,
exchanges the ID token for a Huron token and keeps that token in a session in its own memory,
behind an opaque HttpOnly cookie, so the token never reaches the browser. Every page is rendered
from the server's own API calls with the user's token, so the API's grants, and its 404 for what
the user cannot see, apply unchanged. The web only reads: where the user could change something,
the page shows the `huron` command to run on a machine that mounts the share. Its sessions live in
one process, so it runs as one replica or behind sticky sessions, and a restart signs everyone
out. Its design is [web-design.md](web-design.md).

For development, `make up` runs PostgreSQL and Keycloak for an API on the host, and `make app` runs
PostgreSQL, the API, Keycloak, the group directory and the web in Docker
([docker-compose.app.yml](../docker-compose.app.yml)), for the CLI on the host.

## Push path

```text
huron add …            stage.json records local sources
huron push
  1. GET collection            refuse if version ≠ working copy's base version
  2. copy each file            <rel_path>.huron-part → fsync → rename (skipped when already copied)
  3. POST /commits             {base_version, adds[size, sha256], removes, host, message}
  4. unlink removed files      after the commit succeeds
```

## Enforcement on disk

The storage administrator prepares each declared or rooted organization's directory with
`huron adm provision-orgs`, which writes a marker `<root>/<org>/.huron` naming the service's
instance id and the organization; organizations without a root share the mount prefix's marker,
written by `scripts/init-root.sh`. The CLI's `Mount` resolves every absolute path and checks the
marker before every disk operation, so a CLI pointed at another service, or an export mounted at
the wrong root, writes nothing. Every directory below, created by the CLI as the user, gets a mode
and POSIX ACL derived from the catalog's effective groups, the organization-wide ones included
(`core/storage/aclplan.py`):

| Directory | Mode | Writable by | Readable by |
| --- | --- | --- | --- |
| organization | 2771 | platform and org admins | traverse only for others |
| catalog, namespace | 2770 | admins and catalog admins | contributors, readers |
| namespace allowing collections | 3770 (setgid + sticky) | admins, catalog admins, contributors | readers |
| collection | 2770 | admins, catalog admins, contributors (inherited by new files) | readers |

Platform and organization admin groups get an inherited `rwx` default ACL everywhere, so they can
clean up without elevated privileges. This is contain-and-detect: a contributor can still write into
their collection without the CLI, and the service trusts the hashes the CLI reports. `huron adm check`
finds the drift. See the [ADRs](adr/) for why.

## Code layout

`src/huron/{pkg,schema,core,applications}`; dependencies only point inward and are enforced by
import-linter. The web app is `web/`. See [AGENTS.md](../AGENTS.md).
