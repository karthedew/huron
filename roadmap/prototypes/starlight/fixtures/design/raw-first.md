# Raw-first datastore target

Status: agreed product direction, pending implementation. This record supersedes
the earlier planned Raw-to-Bronze file-layer rename, full-client-reupload rule,
revision-plus-release-tag model, and catalog-first array delivery scope. Existing
implementation receipts remain evidence of the behavior they tested, not evidence
that this target is delivered.

## Layers and delivery

| Layer | Storage contract |
| --- | --- |
| Raw | Original files on a local POSIX filesystem or NFS |
| Bronze | Zarr data managed by Icechunk on S3 |
| Silver | Zarr data managed by Icechunk on S3 |
| Gold | Zarr data managed by Icechunk on S3 |

Build the Raw landing zone first. Bronze, Silver and Gold storage and processing
remain later work. Arbitrary source files, including HDF5 files, can be Raw
payloads; they do not require a separate first-delivery storage capability.

The complete MVP includes metadata/schema governance, Collection catalog,
PostgreSQL search/export, identity/access, tus releases, the production scientist
SDK and an actual backend-integrated frontend for all delivered backend features.
A bounded backend interoperability slice remains useful but is not MVP completion.
The developer stack and hardware-qualified operations/load evidence are delivery
requirements. Array processing and storage remain later work.

## Releases and pushes

- A successful push publishes one new immutable **Raw release**. There is one
  version concept, without a separate revision entity or release-tag operation.
- A subsequent push names an exact base release. Files from that base remain in
  the new file set unless the client explicitly deletes or replaces them.
- The client transfers only new or replacement content. The server materializes
  retained content from the pinned base into the new release.
- Every published release owns a complete independent physical copy of its files.
  Reusing source content during construction does not mean sharing writable
  inodes, hardlinks, or depending on the old release for later reads.
- Deleting a file from the next release does not alter an earlier release.
- Every release has a complete manifest and required release metadata. Whole-file
  size and checksum verification applies to uploaded and retained content.
- Reading retained source content requires source access; creating the new release
  requires target write access. Publication rechecks authority and input validity.
- A retry with the same upload identity returns the same committed release; a
  distinct successful push creates a new release.

Atomicity means readers discover either an earlier complete release or the new
complete release. Private staging, verified independent payloads, storage-first
durability, publication recording and recovery must preserve that guarantee across
process failure. Filesystem publication and PostgreSQL recording are ordered,
recoverable operations, not a distributed transaction.

The base has a durable retention pin until materialization/recovery no longer needs
it; expiry/purge honors that pin. Paths reject traversal, aliases, symlink escapes,
duplicates and addition/deletion collisions. Replacements are explicit. Publication
records the release, lineage, audit and retry receipt in one asyncpg transaction
after durable storage installation. Storage success/database failure leaves a
recoverable, undiscoverable candidate; recovery must not publish after revocation.
Cancellation, ENOSPC and cleanup preserve previously published releases and receipt
identity. Exact crash/fencing behavior requires a bounded prototype. Stale-base
conflict handling and existing-data migration remain decision gates below.

Lineage pins input versions, code, parameters, origin, actors and outcomes where
applicable; original acquisitions do not invent processing evidence. Inaccessible
source details stay filtered. Later processing workers receive scoped input and
candidate grants, never broad authority for arbitrary scientist code.

## Transfer and concurrency

Use one tus upload resource per file whose content must be transferred. Resume from
the server's durable byte offset. Each file has sequential PATCH requests; different
files may upload concurrently. A transferred file, a verified file and a committed
release remain distinct completion states.

Semaphores bound active transfers. Client concurrency, API-worker admission and
verified-copy concurrency are separate budgets. A process-local semaphore is not
a cluster-wide limit or a same-file writer fence. The implementation must also
protect append offsets across processes and preserve durable progress through
disconnects and restarts. Local and NFS deployments need appropriate real-storage
evidence for locking, durability and recovery.

## Identity and access

Use OpenID Connect Authorization Code flow with PKCE, with Google as the first
configured login provider. External identities use `(issuer, subject)` and map to
stable Huron accounts. Matching email addresses do not establish account linkage.
The browser receives a server-managed session; credentials remain server-side.

Authentication and access control have separate replaceable interfaces.
Authentication establishes identity; access control decides whether that actor may
perform an operation on a resource. Core operations enforce access themselves,
including discoverability, source reads and publication. Provider replacement must
not change the Raw workflow's authorization contract.

Keep a small role-based access model. Remove the configurable policy-definition and
policy-attachment feature in the target implementation. This does not remove role
grants, discovery filtering or operation-level authorization. Google login does not
automatically supply institutional groups or API credentials intended for Huron;
those integrations need their own supported contracts.

The external directory mock is a separate dev container owning LDAP-group-like
facts and create-group/add-member/remove-member operations. **Separate authorities
are accepted:** the directory service itself authorizes writes using trusted
membership in a stable configured `huron-admin` group. Huron consumes trusted
group facts and owns scope-role bindings. Directory admin is not automatically
platform owner or data reader. A gateway UI does not transfer membership ownership.
Both systems map verified issuer+subject to stable account/directory identities,
never email alone. The proposed freshness contract is complete effective nested
membership with cycle rejection, versioned facts and a bounded cache; stale or
unavailable facts fail closed for writes/publication. The exact TTL, invalidation
and read-outage policy require qualification, not an invented guarantee. Local
Huron revocation must apply on the next operation across replicas.

Google ID tokens authenticate the login callback; they are not Huron API bearer
credentials. SDK credential-provider/token-broker selection remains blocked.

## Metadata and reproducibility

Catalog owns descriptive title/description/core fields plus an immutable registry
of organization JSON Schemas and collection extensions. Organization owners publish
both. Extensions are **additive only**: new fields, no redefinition or weakening
of organization fields. Keep scientific metadata separate from the server-owned
envelope (identity, actors, timestamps, manifest, lineage and publication state).

Proposed bounded implementation: JSON Schema Draft 2020-12, compiled from explicit
object `properties` and `required` sets, rejecting overlapping extension property
names. Close the final composed object once, rather than naive `allOf` with a base
`additionalProperties: false`. Resolve only registry-controlled, immutable,
digest-pinned `$ref` resources; reject network resolution, unsupported keywords and
unbounded reference cycles. Prototype must specify nested-field rules, format
assertions and limits, and prove identical Python SDK/backend validation. Browser
feedback is advisory; authoritative validation runs again on the backend. This
composition profile is proposed pending the validator corpus, not tested evidence.

New dataset creation requires metadata **and** a resolved schema bundle. Later
omitted metadata inherits the exact metadata/schema pair of the **pinned base**,
even when a newer schema exists. Null is rejected; `{}` is supplied metadata and
must validate. An explicit replacement requires an explicit schema bundle; schema
without metadata is rejected. Resolve/freeze at submission, never implicitly adopt
latest. Historical publications remain valid against their pinned versions.

Recommended export DTO: immutable release ID, manifest, scientific metadata, exact
schemas/versions/digests and a descriptive snapshot captured at submission. Catalog
titles remain mutable for browsing; current titles, if requested, are a separately
labelled live section, excluded from reproducible export/retry digests. JSONB is
the proposed storage for schema documents and scientific metadata; relational
columns retain identity, ancestry, title/description and constraint-bearing facts.

## PostgreSQL and model ownership

Use SQLAlchemy Core `Table`/`MetaData` definitions for PostgreSQL tables, foreign
keys, indexes and constraints, and Alembic for schema evolution. Execute application
queries and transactions directly through asyncpg. Alembic may retain its SQLAlchemy
migration environment using the asyncpg driver. Domain values and transport models
have different responsibilities from database table definitions.

The general database/schema grouping with asyncpg repositories is approved; exact
module moves require the cutover inventory. Proposed `core/database/schema/`
contains table definitions, not domain or shared DB/Pydantic models. Current
Alembic has `target_metadata=None`; `scripts/check_schema_map.py` checks only a
documentation stamp. New metadata and a real migrated-PostgreSQL drift check are
required, including constraints/indexes/triggers not covered by autogenerate.

## Catalog and code organization

`Client()` is the scientist-facing front door, like the Databricks SDK. Prefer
direct `client.search`, `client.datasets` and `client.rawstore` services, without
mandatory `client.catalog` indirection. Stable `huron.client` and `huron.catalog`
imports reexport supported classes/functions from their `interface/` subdirectories.
The SDK is a lightweight separate distribution, never an alias for server Core.

The selected hierarchy is **Organization → Collection → Dataset**. Collection
replaces Project throughout future DB tables/FKs, domain values, HTTP, storage
paths, role-scope codes, SDK, UI, fixtures and tests. Existing Project source is
evidence of pending migration, not an extra target hierarchy level.

Approved owners: catalog, combined **rawstore**, security, database/schema with
asyncpg repositories, and integrity. Raw workflows plus private filesystem adapters
belong in rawstore; remove the separate raw owner through an explicit migration.
Supported operations, values, errors and ports live in each owner's `interface/`,
reexported by root `__init__`. Cross-owner private imports, including type-only,
are forbidden. Move foundation members by actual responsibility. Applications own
transport models, mapping, credentials, composition and lifecycle, not reusable
scientific authorization. The actual `pyproject.toml` seven-owner graph remains
enforced until code, import contracts, tests and ADR history cut over together.
No speculative packages are created by this design update.

## Developer environment

Today `make up` starts PostgreSQL 16 (host 5433), MinIO (9000/9001) and Keycloak
(8081); `make stack` adds migrations and API (8080), **not frontend**. `make web`
serves 5173; browser tests use 4173. No directory mock, persistent Raw volume,
frontend container or k6 profile is currently delivered in Compose.

Target: PostgreSQL 16, migrations, API, persistent Raw volume, frontend with an
explicit same-origin/session arrangement, external directory mock, local OIDC
fixture/provider for automation and Google configuration for real login, plus a
pinned k6 profile. MinIO becomes optional later-layer infrastructure. Keeping
Keycloak as test provider versus Google broker remains an explicit auth decision.

## Test organization and scale target

Organize tests by verification type under `tests/`: unit, contract, integration,
acceptance, performance and load. Within a type, mirror paths beneath `src/huron/`
where there is a meaningful owner. Cross-domain scenarios follow the workflow they
prove rather than an arbitrary implementation file. Extend focused shared fixtures
at the narrowest useful scope and retain existing behavioral evidence when moving
tests.

Use k6 for the load workload:

- 50 distinct authenticated users, each uploading 10 GiB to a separate dataset:
  500 GiB total uploaded payload.
- Measure through committed, readable releases, separating admission wait,
  transfer, verification/copy and publication time.
- Exercise same-dataset conflicts separately as correctness scenarios.
- Establish a baseline on nominated local/NFS hardware before agreeing a
  completion-time or throughput SLO. Concurrency alone is not a performance result.
- Record deployment topology, network/storage capacity, API and load-generator
  resources, errors, retries, memory, queueing, database-pool pressure and disk I/O.
- Use bounded file buffers in the load generator rather than loading a 10 GiB body
  into each virtual user's memory. Pin and qualify the k6 filesystem API used for
  reading PATCH bodies. Drive tus HEAD/PATCH exchanges rather than a generic POST.
- Test retained-file copies separately from fresh uploads. Capacity planning
  includes base releases, upload staging and independent publication candidates;
  the final 500 GiB payload is not the peak storage requirement.

The existing 9 GiB acceptance test does not establish this new 50-user target.

Measure committed-readable verification, copy/commit and PostgreSQL search under
load, resource/capacity pressure and retries/errors; qualify both real NFS and the
load generator. Provision **more than 500 GiB peak capacity**, based on source,
staging, base retention and independent-copy candidate coexistence, not payload
size alone. No load run or prototype is claimed by this record.

## Decisions and execution blockers

| Decision | Status / owner | Recommendation and consequence |
| --- | --- | --- |
| Complete MVP, direct Client services, combined rawstore, Collection replacement | Accepted by user | Plan SDK and integrated UI as MVP, not indefinite backend-only follow-up. |
| Additive extensions; exact pinned-base metadata/schema inheritance | Accepted by user | Reject overlap/weakening; freeze bundle and preserve historical validity. |
| Separate directory/Huron authorities; hardware baseline before SLO | Accepted by user | Directory admin grants no automatic Huron role; do not invent time targets. |
| Existing data preservation/migration vs fresh deployment | **BLOCKED — user/data owner** | Recommend inventory + backed-up migration rehearsal; a fresh deployment requires explicit approval and disposition of existing data. No deletion authorization exists. |
| SDK API-token issuer/broker and Keycloak role | **BLOCKED — identity owner + user** | Qualify a replaceable credential provider and a broker issuing audience-bound API tokens; compare retained Keycloak broker vs other approved issuer. No Google ID-token bearer shortcut. |
| Stale-base concurrent publication | **BLOCKED — user/product owner** | Recommend fail with explicit stale-base conflict and retry/rebase; silent merge obscures provenance. |
| Target NFS hardware and eventual SLO | **BLOCKED — operator + user** | Nominate topology/capacity, benchmark first, then approve SLO. |
| Schema composition profile, authority freshness, fencing/recovery, SDK packaging | **BLOCKED — phase prototype owners** | Bounded reproductions and independent review precede affected implementation. |

Local phase plans use ignored `roadmap/plans/`; tracked documentation never depends
on their presence. Their status is DRAFT/BLOCKED until decisions, prototype evidence
and independent review close. Tooling verification is not MVP verification.

## References

- [Current architecture and package graph](architecture.html)
- [Current Raw implementation and durability record](layer-raw.html)
- [Historical delivery evidence](../docs/history.md)
- [Domain-owned workflow rationale](../docs/adr/0002-domain-owned-core-workflows.md)
- [tus 1.0 protocol](https://tus.io/protocols/resumable-upload)
- [k6 memory-efficient file API](https://grafana.com/docs/k6/latest/javascript-api/k6-experimental/fs/)
