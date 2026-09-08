# Backend restructuring

## Contract and scope

Implement the agreed `applications → core → pkg → schema` architecture. Keep the
existing HTTP resource contract except for Raw ingest's removed parent/dedup semantics.
The scientist SDK and Ray/Zarr integrations remain future work: this change supplies
reusable server operations and records their intended interfaces, not fabricated clients.

Raw revisions are independent complete submissions. An identical new submission is
valid; only retries sharing an idempotency identity reuse a revision. Required metadata
is validated before publication. Preserve upload streaming, checksums, lease/concurrency
fences, storage-first publication, and crash recovery.

## Responsibility decisions

- Move workflow services and consumer-owned persistence protocols into core.
- Move records/errors to the catalog domain; move concrete database adapters into
  metastore. Metastore may import domain packages to encode/decode their types;
  domain packages remain mutually independent and cannot import metastore. This is
  an explicit infrastructure-to-domain dependency, not a reverse core dependency.
- API retains HTTP schemas, transport, credentials/cookies, and composition.
- Move authorization decisions into reusable core objects and enforce them at core
  entry points; retain transport dependencies only as adapters.
- Use cohesive objects and immutable values where appropriate; retain pure utilities.

## Implementation and verification

1. Establish baseline; move modules/imports and deployment entry points; enforce layers.
2. Remove parent planning, hardlink paths and duplicate-content rejection; update storage
   constraints and tests for complete copies and repeated-content submissions.
3. Extract reusable authorization and operation coordination from routes; test direct
   core use, including denial without FastAPI.
4. Reconcile architecture/Raw design and instructions with executable implementation.
5. Run static checks, unit coverage, contracts, integration and Raw acceptance gates;
   report infrastructure blockers separately from code failures.

## Baseline

Working tree includes user-owned instruction and skill changes plus GPT_AGENT.md;
retain them. The default uv cache is inaccessible in the sandbox; validation uses
UV_CACHE_DIR=/tmp/huron-uv-cache and UV_NO_SYNC=1 with the installed environment.

## Delivered and verified

- API entry point: `huron.applications.api.main:app`; `make api` updated.
- Authorized core catalog, identity, Raw intake/upload and revision-read services;
  private workflow mechanics; domain-owned immutable hierarchy updates; metastore adapters.
- Required shared Pydantic metadata contract. Every new Raw submission uploads its
  complete files; identical content may have separate revision identities.
- Migration 0010 rejects legacy hardlink ledgers and refuses a downgrade when repeated
  content would violate the old constraint. Disposable PostgreSQL tests prove both
  failures preserve schema and data. No deployed database was migrated.
- `make lint` passes, including both type checkers, import contracts, schema map,
  complexity gates and informational clone analysis. No C-grade cyclomatic results
  or B-or-lower maintainability results were emitted.
- Unit suite: 990 passed, coverage 94.32% (94% gate retained).
- PostgreSQL contract suite: 13 passed, including migration failure and round-trip tests.
- Raw acceptance: the 9 GiB interrupted upload resumes and downloads byte-identically.
- Integration marker: no tests collected; this is not integration coverage.
- Documentation build and diff whitespace checks pass.

The SDK's `dataset.upload(...)`, Ray/Zarr publication and transformation lineage
workflows remain planned. Existing historical P1/P2 plans retain their original
snapshots; current design pages and AGENTS.md describe the implemented boundaries.
