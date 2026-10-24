# Huron Raw Data Lake — CLI, Auth Broker & Catalog Spec

Oct 23, 2026 · @Karl

> Spec of record for the Raw data lake. The owner decisions at the end amend it; where they
> differ from the body, the decisions win.

> Owner note (2026-10-23): the institutional IdP connection is not available here. Mock the company
> OIDC provider, the LDAP-groups endpoint and the ONTAP NFS volume for local development, testing
> and building.

## Overview and scope

Huron's raw data lake is three components: a Typer CLI that writes files directly over NFS, an auth broker that turns a company OIDC login into a Huron token, and a Postgres catalog that records what exists, who owns it and what it means.

**In scope**

- CLI for creating collections, filling and editing metadata, and adding or removing files
- Auth broker: company OIDC login, LDAP group lookup, Huron-issued JWTs
- Raw catalog: catalogs, namespaces, collections, files, metadata, audit log
- A small backend API for metadata and commits only

**Out of scope for now**

- Polaris, Iceberg and the Icechunk + Zarr analytical store
- Processing pipelines and service-account credentials
- The WebUI (it will read the same catalog API later)

**Principles**

- File bytes never travel over HTTP. The CLI writes over the NFS mount; the API carries only metadata.
- No versioning of raw data. Postgres holds current state; ONTAP snapshots are the recovery path, as with Databricks Volumes and Snowflake stages.
- Postgres is the source of truth. A file is real only once its row commits.
- Paths come from metadata. A collection's location is derived from required, vocabulary-controlled fields defined by its catalog.

## Architecture

The CLI on a designated machine moves file bytes over the NFS mount; the Huron API on OpenShift handles login, catalog and commits, and never touches file bytes.

[embedded content: raw data lake architecture · 6 components]

The CLI logs in with the company identity provider, exchanges that token at Huron, then talks to Huron only for metadata and commits. Huron reads LDAP groups to resolve roles, stores everything in Postgres, and touches the volume only to verify hashes, create directories and set permissions.

**Assumptions**

- The CLI refuses to upload unless the volume is mounted at the configured prefix (for example `/projects`).
- The volume is an ONTAP NFS export reachable from the designated machines and from the Huron pods. If Trident provisioned it, it is imported or re-exported so both sides mount the same filesystem.
- Postgres runs on OpenShift beside the API.

## Auth broker

Huron exchanges a company OIDC token for a short-lived Huron JWT that carries the user's Huron roles, resolved from LDAP groups at the moment of exchange.

**Login and exchange**

1. `huron login` runs the company OIDC flow (device code over SSH, browser otherwise) and receives the company JWT plus a refresh token.
2. The CLI sends the company JWT to `POST /auth/exchange`.
3. Huron verifies its signature, issuer, audience and expiry against the company provider's keys.
4. Huron calls the company LDAP-groups endpoint for that user.
5. Huron maps groups to roles using the `group_role_map` table, per catalog.
6. Huron mints a Huron JWT (about 1 hour) and returns it.
7. The CLI caches both tokens and re-runs the exchange when the Huron JWT expires.

**Huron JWT claims**

| Claim | Example | Purpose |
| --- | --- | --- |
| `iss` | `https://huron.example` | Huron as issuer |
| `sub` | `karl` | Company username |
| `aud` | `huron-api` | Leaves room to add other services later |
| `roles` | `["PRINCIPAL_ROLE:helio_developer"]` | Role grants, in a format other services can reuse |
| `groups` | `["helio-scientists"]` | Source groups, for audit and POSIX mapping |
| `exp` / `iat` | 1 hour lifetime | Bounds how long a removed group keeps access |

**Signing**

- Asymmetric keys (RS256 or ES256), never a shared secret.
- Publish `/.well-known/openid-configuration` and `/jwks.json` now, even though only Huron's API verifies tokens today.
- Rotate keys by publishing the new key in the JWKS before signing with it.

**Roles**

| Role | Can do |
| --- | --- |
| Reader | List, describe and search collections; read files |
| Developer | Create collections, add and remove files, edit descriptive metadata |
| Project Admin | Everything above plus `mv`, bulk metadata edits and role mappings for their catalog |
| Organization Admin | Manage catalogs and their configs |
| Platform Owner | Keys, global settings, all catalogs |

**Enforcement on the volume**

The same group mapping sets POSIX groups and ACLs when Huron creates catalog and collection directories: Readers get read, Developers get write. On NFS this is the only check that actually stops a direct file access, so the API and the filesystem must agree.

## Catalog model

Each science domain is a catalog whose config defines its metadata schema and the ordered fields that build a collection's namespace path.

**Objects**

- **Catalog** — one per domain: heliophysics, geophysics, space science.
- **Namespace** — any number of levels, created from a collection's metadata, never by hand.
- **Collection** — the unit of ownership, metadata and permissions. Only collections contain files.
- **File** — one row per file, current state only.

**Catalog config**

```yaml
catalog: heliophysics
config_version: 1
schema: heliophysics-v1          # extends the org base schema
namespace_fields: [mission, instrument, campaign]
collection_name: { field: run_id }
vocabularies:
  mission: [psp, solo, soho]
  instrument: { psp: [fields, sweap, isois] }
snapshot_class: standard
```

**Identifiers and paths**

| Form | Example | Used by |
| --- | --- | --- |
| Canonical | `heliophysics.psp.fields.enc17.run042` | Postgres, API, future catalogs |
| Catalog-rooted | `/psp/fields/enc17/run042` | CLI, with `huron catalog use heliophysics` |
| Fully qualified | `heliophysics/psp/fields/enc17/run042` | CLI, ignores current catalog |
| Mount path | `/projects/heliophysics/psp/fields/enc17/run042` or `.` | CLI, run from inside the directory |

**Naming rules**

- Segments match `[a-z0-9_-]+`, lowercase, no dots, so slash and dot forms convert both ways.
- Values are slugified from metadata: "Campaign 17" becomes `campaign17`.
- Reserved: `.snapshot`, anything starting with `.`, anything ending in `.part`.
- Maximum depth 8 segments including catalog and collection.

**Collection lifecycle**

1. **Draft** — `huron create collection` makes a UUID and a row. No path, no directory, no uploads. Partial metadata can be saved and resumed.
2. **Resolved** — every namespace field is valid; the CLI shows the path preview for confirmation.
3. **Active** — namespace rows and the directory are created with POSIX permissions, `metadata.json` is written beside the data, uploads unlock.
4. **Incomplete** — an active collection whose catalog schema later gained a required field. Uploads still work; `huron check` lists them.

**Field rules**

- Namespace fields are required, single-valued and vocabulary-controlled.
- Identity fields (namespace fields and the collection name) are frozen once active. Changing them takes a privileged `huron mv`.
- Descriptive fields stay editable through pull, update and publish.
- Changes to a catalog config apply only to new collections. Each collection records the `config_version` it was created under.

## Postgres schema

Nine tables hold the whole raw catalog; schemas and metadata are JSONB so a new science standard never needs a new table. Definitions live in SQLAlchemy Core with Alembic migrations; the runtime uses asyncpg.

| Table | Key columns | Notes |
| --- | --- | --- |
| `catalogs` | `id`, `name`, `config` (JSONB), `config_version`, `created_at` | One row per domain; config holds namespace fields, vocabularies, snapshot class |
| `metadata_schemas` | `id`, `name`, `version`, `extends_id`, `json_schema` (JSONB) | Org base schema plus catalog extensions |
| `namespaces` | `id`, `catalog_id`, `path` (ltree), `created_at` | `ltree` gives cheap subtree queries; unique on (`catalog_id`, `path`) |
| `collections` | `id` (UUID), `catalog_id`, `namespace_id`, `name`, `identifier`, `state`, `config_version`, `metadata` (JSONB), `updated_at`, `etag` | `state` in draft, active, incomplete; `identifier` null until resolved; unique on (`namespace_id`, `name`) |
| `files` | `id`, `collection_id`, `rel_path`, `size_bytes`, `sha256`, `uploaded_by`, `uploaded_at`, `etag` | Current state only; unique on (`collection_id`, `rel_path`) |
| `audit_log` | `id`, `at`, `actor`, `action`, `object_type`, `object_id`, `detail` (JSONB), `reason` | Append-only; actions: create, add, overwrite, rm, meta_publish, mv, delete |
| `roles` | `id`, `name`, `scope` | Reader, Developer, Project Admin, Organization Admin, Platform Owner |
| `group_role_map` | `ldap_group`, `role_id`, `catalog_id` (nullable) | Null catalog = applies to all catalogs |
| `signing_keys` | `kid`, `alg`, `public_jwk`, `private_ref`, `active_from`, `retired_at` | Private key held in a secret store; only the reference is stored here |

**Constraints worth enforcing in the database, not just the API**

- `etag` changes on every write to `collections` and `files`; updates use `WHERE etag = $expected`.
- `audit_log` grants INSERT and SELECT only to the application role.
- `files.rel_path` is checked against the naming rules with a CHECK constraint.
- Search on metadata uses a GIN index on `collections.metadata`.

## Backend API

The API is a small FastAPI service that carries only metadata, auth and commits; every write call requires a Huron JWT and an `If-Match` etag.

| Method | Path | Purpose | Min role |
| --- | --- | --- | --- |
| POST | `/auth/exchange` | Company JWT in, Huron JWT out | Any authenticated user |
| GET | `/.well-known/openid-configuration`, `/jwks.json` | Issuer discovery and public keys | Public |
| GET | `/catalogs`, `/catalogs/{c}` | List catalogs, read config and schema | Reader |
| GET | `/catalogs/{c}/schema` | Resolved JSON Schema for the walkthrough | Reader |
| GET | `/namespaces?under={ident}` | Subtree listing | Reader |
| GET | `/collections?catalog=&under=&label=` | Search and filter | Reader |
| POST | `/collections` | Create a draft | Developer |
| PATCH | `/collections/{id}/draft` | Save partial draft metadata | Developer |
| POST | `/collections/{id}/activate` | Validate, resolve path, create directory | Developer |
| GET | `/collections/{id}` | Metadata, state, etag, file count | Reader |
| GET | `/collections/{id}/files` | Current file rows | Reader |
| POST | `/collections/{id}/commit` | Record adds and removes after the CLI wrote the bytes | Developer |
| PUT | `/collections/{id}/metadata` | Publish descriptive metadata | Developer |
| POST | `/collections/{id}/move` | Change identity fields and relocate | Project Admin |
| GET | `/collections/{id}/log` | Audit entries | Reader |

**Commit request**

```json
{
  "base_etag": "c7e1…",
  "host": "sci-node-03",
  "adds": [
    {"rel_path": "scans/0423_001.bin", "size_bytes": 2147483648,
     "sha256": "9f3c…", "overwrite": false}
  ],
  "removes": [
    {"rel_path": "scans/bad_01.bin", "expected_sha256": "41ab…"}
  ],
  "reason": "replace miscalibrated scan"
}
```

**What the server checks before committing**

- The caller holds Developer on the collection's catalog.
- Each added file exists at its final path on the mount with the stated size and hash. The server re-hashes every added file from the mount and rejects the commit on any mismatch; this reads each file once more, so large commits take longer to confirm.
- An add to an existing path without `overwrite: true` fails; an overwrite records the old hash in the audit log.
- A remove whose current hash differs from `expected_sha256` fails.
- Then one transaction updates `files`, bumps the etag and writes the audit entries.

**Conflict responses**

- `409 path_exists` — names the path and its current uploader.
- `409 changed_since_read` — returns the current row so the CLI can show the difference.
- `412 etag_mismatch` — the collection's metadata changed since it was pulled.

## CLI reference

The CLI uses `oc`-style verbs for browsing the catalog and Git-style verbs for working on one collection; Git-style commands act on the current checkout unless given `-c <collection>`.

**Session and context**

| Command | Does |
| --- | --- |
| `huron login` | Company OIDC login, then token exchange |
| `huron logout` | Drops cached tokens |
| `huron whoami` | User, groups and Huron roles per catalog |
| `huron catalog use <c>` | Sets the current catalog, like `oc project` |
| `huron config view` | Current context and settings |

**Browsing (`oc` style)**

| Command | Does |
| --- | --- |
| `huron get catalogs` | Lists catalogs you can read |
| `huron get namespaces <path> [--recursive]` | Subtree listing |
| `huron get collections <path> [-l k=v] [-o wide\|json\|yaml]` | Search by path and metadata |
| `huron describe collection <path>` | Metadata, state, file count, last change |
| `huron explain catalog <c>[.<field>]` | Schema fields, descriptions and vocabularies |
| `huron create collection [-f metadata.json]` | New draft; runs the walkthrough if no file given |
| `huron check [--catalog <c>]` | Incomplete collections and orphaned `.part` files |

**Working on a collection (Git style)**

| Command | Does |
| --- | --- |
| `huron checkout <path>` | Pulls metadata and file list, sets current collection |
| `huron switch <path>` | Changes current collection; staged work is kept per collection |
| `huron add <files…> [--to <rel_dir>] [--overwrite]` | Stages files to upload |
| `huron rm <rel_path…>` | Stages removals |
| `huron status` | Current collection, staged adds, removes and metadata changes |
| `huron diff` | Field-level metadata diff |
| `huron discard` | Drops staged changes |
| `huron push [-m <reason>]` | Validates, writes files over NFS, commits, publishes metadata |
| `huron log [<path>]` | Audit trail |

**Metadata**

| Command | Does |
| --- | --- |
| `huron meta init --catalog <c>` | Walkthrough for a new `metadata.json` |
| `huron meta template --catalog <c>` | Blank skeleton for editing by hand |
| `huron meta validate <file>` | Checks a file against the catalog schema |
| `huron meta update` | Walks the editable fields of the checked-out metadata |
| `huron mv <path> --set <field>=<value>` | Changes an identity field; Project Admin only |

**Walkthrough behaviour**

- Namespace fields first, in catalog order, as select lists; later choices narrow by earlier ones.
- Then required fields, then optional ones; Enter skips an optional field.
- Prefills PI, organization and contact from the login identity.
- Shows each field's schema description and examples; validates as each answer is given.
- Saves after every answer to the draft; `--resume <draft-id>` continues.
- Ends with a summary and the path preview.
- `--no-input --set field=value` runs without prompts and lists missing required fields.

**Local state** (XDG state directory, not the working directory)

```
~/.local/state/huron/
  config.yaml              # current catalog, current collection, API URL
  tokens.json              # mode 0600: Huron JWT, company refresh token
  collections/<uuid>/
    metadata.json          # pulled copy being edited
    base.json              # etag and time of the pull
    staged.json            # adds (source path, size, sha256, host) and removes
```

Built with Typer for commands, `questionary` for prompts, `jsonschema` for validation and `rich` for output.

## Write path and storage semantics

The CLI writes bytes to their final directory over NFS, renames them into place, then asks the API to commit; snapshots are the only history.

**`huron push`, step by step**

1. Check the volume is mounted and writable at the configured prefix; refuse otherwise.
2. Refresh the Huron token if needed.
3. Re-hash each staged source file and compare with `staged.json`; refuse if a source changed after `add`, or if the host differs.
4. For each add, stream to `<final path>.part` with 8–16 MB buffers, hashing as it goes, then `fsync`.
5. Check the hash, then `rename` `.part` to the final name. A rename within one filesystem is atomic.
6. Call `POST /collections/{id}/commit` with adds, removes and the base etag.
7. On success, unlink removed files and rewrite `metadata.json` (also via `.part` and `rename`) if metadata changed.
8. Clear the staged state.

**Failure cases**

- Copy interrupted: only a `.part` file is left. The next push resumes by hashing what exists and appending.
- Commit refused after the rename: the new file sits on disk with no row. Nothing reads it, and `huron check` reports it.
- Overwrite of an existing name: the old bytes survive only in snapshots taken before the write.

**Throughput**

Mount with `nconnect=8` (several TCP connections per mount) and copy multiple files in parallel. For a single 10 GB file the NFS client and network are the limit, not the CLI.

**Snapshots, retention and audit**

- ONTAP snapshot policy on the volume is the undo window. Set it longer than the time it takes someone to notice a bad delete.
- Retention for data that must be kept is a separate decision: a SnapLock volume, chosen up front, since a volume cannot be converted in place.
- The audit log records every add, overwrite, remove, metadata publish and move, with actor, time and reason. It tells you which snapshot to restore from.
- Restoring a file is a copy out of `.snapshot/<name>/…`, followed by `huron add --overwrite` so the catalog matches.

**Reconciler**

A periodic `huron check --repair` job (admin only) compares the volume with Postgres:

- File row with no file on disk: flag it.
- File on disk with no row, older than a grace period: list it for removal.
- Stale `.part` files older than a day: remove them.
- Directory permissions that differ from the role mapping: reset them.

## Build order and open questions

Build auth first, because every other command needs a token.

1. **Auth:** `/auth/exchange`, signing keys, JWKS, `group_role_map`; `huron login`, `whoami`, `catalog use`.
2. **Catalog config and schemas:** `catalogs` and `metadata_schemas` tables, `explain`, `meta template`, `meta validate`.
3. **Collections:** draft, walkthrough, activate, path resolution, directory creation with POSIX permissions; `create collection`, `get`, `describe`.
4. **Files:** `checkout`, `add`, `rm`, `status`, `push`, the commit endpoint and the `.part` and `rename` write path.
5. **Metadata editing and audit:** `meta update`, publish, `diff`, `log`, `mv`.
6. **Maintenance:** `huron check` and the reconciler.

**Open questions**

- [ ] Confirm with the storage admin that the volume can be exported to the designated machines, or created on ONTAP and brought into OpenShift with `tridentctl import volume`.
- [ ] Snapshot policy for the raw volume: how many hourly, daily and weekly copies.
- [ ] Whether any catalog needs a SnapLock volume for retained data.
- [ ] Which LDAP groups map to which roles for the first catalog.
- [ ] Whether `collection_name` is chosen by the scientist or generated.

## Owner decisions (2026-10-23)

1. Reach (L-24): Raw only. Delete the Raw engine, /api/raw-web, the BFF raw delegation, the web upload
   wizard and the Raw explorer. Web login, sessions, API keys and the Polaris org/project/dataset API keep
   running; the auth broker is added beside them, and the new tables live apart from the legacy ones.
   The owner added: investigate Huron's own PostgreSQL catalog for Raw entries versus Polaris generic
   tables. In production Polaris will be backed only by StorageGRID S3, so Raw generic tables (whose
   bytes sit on ONTAP NFS) would be tables Huron has to manage itself.
2. Persistence: the repository's convention (hand-written DDL Alembic revisions, asyncpg SQL adapters,
   migrations/schema.sql map). The spec's "SQLAlchemy Core" is amended.
3. Commit (L-12): asynchronous. POST /collections/{id}/commit answers 202 with a commit id; a bounded
   worker re-hashes from the mount and commits rows and audit entries in one transaction; the CLI polls.
4. NFS mock: a plain directory at the configured prefix with a marker file for dev and unit tests, behind
   Volume and DirectoryPermissions ports with a recording fake; a real NFS-server container and ACL
   checks run as a Linux-only test tier.
5. Mocks (owner note): the company OIDC provider, the LDAP-groups endpoint and the ONTAP NFS volume are
   mocked for local development and tests.
6. Catalog store (owner's investigation; the catalog-store study): option A. Huron's own PostgreSQL is
   the only Raw catalog. No Polaris client, credential or compose service for Raw; OD-5 stands. The design
   names the seam where a Huron-managed Polaris projection (option C: an S3 catalog, no base-location,
   the mount path and collection UUID in `huron.*` properties) could be added later. Option B rejected:
   generic tables have no update, rename, search or compare-and-set, and from the next Polaris release an
   S3-only catalog refuses file:// or POSIX base-locations (upstream #5748).
7. Role check (L-7): re-map the token's `groups` through the current group_role_map on every request;
   the `roles` claim stays for whoami and other services.
8. Administration (L-10): API routes and CLI verbs for catalogs, catalog configs, metadata schema
   versions, role mappings and signing-key rotation, each audited; a configured LDAP group is seeded as
   global Platform Owner at startup.
9. Plan files: /design-plan writes RAW_LAKE_DESIGN.md and RAW_LAKE_IMPLEMENTATION_PLAN.md on the
   raw-storage branch; RAW_STORAGE_DESIGN.md and RAW_STORAGE_IMPLEMENTATION_PLAN.md get a one-line
   superseded banner and keep their M0–M1 execution notes as history.
10. Legacy credentials (L-5, clarified 2026-10-23): the web app keeps its own sessions and account store
   (web/src/lib/server/auth.ts, huron-accounts.ts), which are unaffected. Delete the Python password
   login, cookie sessions and server code flow, which no client calls. Keep API keys, service accounts
   and dev headers for the legacy /api/v1 routes and their tests. Lake routes accept only the Huron JWT.
11. Backwards compatibility: none. No compatibility shims, re-exports, aliases or deprecated names; no old
   configuration keys, environment variables or route paths kept beside new ones; no request or response
   shapes accepted in two forms; no migration that preserves, converts or exports legacy data, and no
   refusal flag guarding its loss; no transition periods or interim states kept for old clients or old data.
   Development data in dropped tables is discarded. Decisions 1 and 10 still say what stays as live
   functionality (the Polaris org/project/dataset API, its /api/v1 routes and their credentials, and the
   web's own login); it stays because it is in use, not for compatibility, and may change shape freely.
12. Open questions and the company IdP: every open question in the design's register (OQ-1.1..OQ-26.1) is
   settled on its recommended option, or on the revised recommendation where decision 11 changed it. The
   company IdP is a standard OIDC provider (discovery, JWKS, the device authorization grant, and the
   authorization code flow with PKCE on a loopback redirect). Local development and tests never reach the
   institutional IdP: they run against a Keycloak `company` realm and the in-repo fake issuer. Answers
   that rest on facts outside this repository are adopted as assumptions and confirmed before production
   rollout: ONTAP ACL behaviour (OQ-11.1, OQ-21.3), the real group-directory contract (OQ-6.1), group
   counts against header limits (OQ-6.2), an organization claim (OQ-20.3), and the production IdP's
   client registration (a public `huron-cli` client with the device grant and loopback redirects).

Every other entry in the planning gap memo's register (L-1..L-44) takes that memo's recommendation as the default
unless the design finds a reason to differ, in which case it flags the entry as an open question.

## Design amendments (2026-10-23)

These amend the body as the owner decisions do; each item names the design task, and the open question
whose recommended option it assumes.

| # | Spec lines | Amendment | Source |
| --- | --- | --- | --- |
| A-1 | `:34`, `:145` | "vocabulary-controlled" → "vocabulary-controlled where the catalog defines a vocabulary; a field without one is open and slugified" | DT-8, OQ-8.1 (a) |
| A-2 | `:69-71` | `aud` example `["huron-api"]` (always an array); `roles` example `["PRINCIPAL_ROLE:heliophysics.developer"]`. Grammar: `PRINCIPAL_ROLE:<catalog>.<role_code>` or `PRINCIPAL_ROLE:<role_code>`. Lake routes never read `roles` (Owner decision 7). | DT-5 L-6 (a), G-30 |
| A-3 | `:87` | Project Admin's "bulk metadata edits" is `POST /api/v1/catalogs/{catalog}/metadata-edits` (1–200 `{id, version}` pairs, one merge patch, all or nothing) and the CLI `meta bulk-update` | DT-15, OQ-15.1 (a) |
| A-4 | `:109-118` | Config `schema: heliophysics-v1` → `schema: {name: heliophysics, version: 1}`. Optional `title`. `collection_name` is `{field: <name>}` or `{generate: collection_id}`. | DT-8 L-23 (a), G-22, L-40 (c) |
| A-5 | `:131` | Segments match `^[a-z0-9][a-z0-9_-]{0,63}$` | DT-8, OQ-8.3 (a) |
| A-6 | `:133` | Reserved also: `metadata.json` at a collection root (case-folded). Partials are named `<name>.<token>.part`, with a 32-hex token per staged add. | DT-12 L-42 (a); DT-13 G-27 |
| A-7 | `:136-141` | Three stored states: `draft`, `active`, `incomplete`. "Resolved" is a validation outcome shown as the path preview, not a state. Active and Incomplete are *settled*. Activation provisions the directory, then commits, then the server writes `metadata.json`. Incomplete means the metadata fails the collection's validator after a schema change (a missing field or one that no longer conforms). | DT-12 G-2; DT-9, OQ-9.1 (a) |
| A-8 | `:148` | "Changes to a catalog config apply only to new collections", plus: `namespace_fields` and `collection_name` are equal in every version of a catalog | DT-8, OQ-8.2 (a) |
| A-9 | `:152` | "Nine tables" → the lake tables of DT-17's revisions `0015`–`0018`, all in Postgres schema `lake`, PostgreSQL ≥ 16 (hyphenated ltree labels). Owner decision 2 already replaces SQLAlchemy Core. | DT-1 L-20 (a); DT-8 R8-1; DT-17 |
| A-10 | `:157` | `metadata_schemas.version` is per `name`; `name` is a segment; `org` is the base series | DT-9 |
| A-11 | `:159` | `collections.etag` → `version` (bigint). `identifier` is null until activation, and `identifier` is unique. The table gains `file_count`, `created_at` and `created_by`, and a foreign key from `(catalog_id, config_version)` to the stored config. | DT-1 L-29 (a); DT-12; DT-17 `0016` |
| A-12 | `:160` | `files` has no `id` and no `etag`. Key `(collection_id, rel_path)`, plus `rel_path_key` unique per collection. | OQ-13.3 (a); OQ-1.2 (a); DT-13 |
| A-13 | `:161` | `audit_log` gains `catalog_id`. Actions are the fourteen `(action, object_type)` pairs of DT-7 (`activate`, `catalog_config`, `schema_publish`, `role_map`, `key_rotate`, `key_withdraw` added). File actions are recorded against the collection. | DT-7; OQ-5.2 (a) for `key_withdraw` |
| A-14 | `:162-163` | `roles(code, title, rank, scope)` with `scope` ∈ {catalog, global}. `group_role_map` holds one row per (group, catalog or all). Group gids are in `ldap_groups`. | DT-4 C-5; OQ-4.2 (a); OQ-4.1 (a) |
| A-15 | `:164` | `private_ref` names a PKCS#8 PEM file in a mounted Secret directory. `kid` is the RFC 7638 thumbprint. | DT-5 L-2 (a) |
| A-16 | `:168` | "`version` increments on every write to a collection (draft save, publish, `mv`, commit); updates use `WHERE version = $expected`. Files carry no version; their preconditions are `overwrite` and `expected_sha256`." | DT-1 L-29 (a); OQ-1.2 (a) |
| A-17 | `:169` | Append-only is enforced by a trigger that refuses `UPDATE`, `DELETE` and `TRUNCATE`. The grant split is deployment hardening. | DT-7 L-43 |
| A-18 | `:170` | The CHECK mirrors the `rel_path` rule (NFC, ≤ 1024 bytes, ≤ 200 per segment, no empty/`.`/`..`, no `Cc`, no backslash, no reserved segment), not the segment rule | DT-13 L-13 (b), G-1; OQ-13.1 (a), OQ-13.2 (a) |
| A-19 | `:175`, `:177-193` | Lake routes live under `/api/v1`. `POST /auth/exchange` and the discovery documents are at the root. Updates send `If-Match: "N"`, and creating calls send `Idempotency-Key`. The route table is DT-18's, which adds commit status, `DELETE /collections/{id}`, the administration routes, bulk edits and findings. | DT-1 L-27 (a), L-29 (a); DT-18 |
| A-20 | `:199` | `base_etag` is removed; the collection version travels in `If-Match` | DT-1 L-29 (a) |
| A-21 | `:218` | "Then one transaction …" → "The commit answers 202 with a commit id; a worker re-hashes the adds and then one transaction updates `files`, bumps the version, writes the audit entries and marks the commit `succeeded`; the CLI polls `GET …/commits/{commit_id}`." | DT-14, Owner decision 3 |
| A-22 | `:222-224` | `409 PATH_EXISTS`, `409 CHANGED_SINCE_READ`, `412 PRECONDITION_FAILED` (stale `If-Match`). The lowercase names survive as the problem `type` suffix. Also `409 PATH_COLLISION` and `409 FILE_MISMATCH`, and `413 TOO_MANY_FILES` and `413 FILE_TOO_LARGE`. | DT-1 L-28 (a); DT-13 |
| A-23 | `:226-275` | The CLI reference gains `delete collection`, `meta bulk-update`, the administration verbs (catalogs, configs, schema versions, role mappings, signing keys) and `discard [paths] [--files] [--metadata]`. `create collection` ends with the new collection checked out. `--set` parses each value by its field's kind. | DT-20; DT-10 |
| A-24 | `:250` | `huron check` reads the reconciler's findings and the catalog's Incomplete collections (Project Admin); there is no `--repair` | DT-16, OQ-16.1 (a), OQ-16.2 (a) |
| A-25 | `:288-296` | `collections/<uuid>/` gains `files.jsonl` (the paged file listing). `staged.json` also holds push progress and each add's partial token. | DT-20, OQ-20.2 (c); DT-21 |
| A-26 | `:302`, `:309-312` | Step 4 streams to the token-scoped partial. Step 5 places it by link (by rename with `--overwrite`). Step 6 submits the commit with `If-Match` and `Idempotency-Key`, then polls it. Step 7 unlinks removed files and publishes changed metadata with `If-Match` set to the commit's resulting version; there is no `metadata.json` rewrite. | DT-21; DT-12; DT-14 |
| A-27 | `:317-318` | "Copy interrupted: only this push's partial is left; the next push resumes it by hashing what exists and appending." "Commit refused after placement: the file has no row; the reconciler reports it as `FILE_UNRECORDED`." | DT-21; DT-16 |
| A-28 | `:334-339` | "A nightly CronJob from the API image (`python -m huron.applications.api.reconcile`), not a CLI command." Its findings are the fourteen DT-16 codes. Partials older than a day are removed. Unrecorded files are listed, never deleted. ACL drift is reset. | DT-16, L-15 (b), OQ-16.3 (a) |
| A-29 | `:280` | No change under OQ-20.3 (a): `organization` is prefilled only when the company ID token carries that claim. Under (b) it is dropped from the prefill list. | DT-20, OQ-20.3 |
| A-30 | `:5-6` | The quoted preface gains: "The design amendments after the owner decisions amend it in the same way." | this section |
