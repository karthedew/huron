# Phase 007: PostgreSQL discovery and reproducible export

Status: BLOCKED — query/export prototype, 004 metadata and 006 publication.

## Context and outcome

Current catalog has hierarchy browse/keyset operations; search is planned and the
user-owned catalog/interface/catalog_search.py is empty. Current frontend has
synthetic search projections. Complete Raw MVP requires actual PostgreSQL search
and metadata export, not later LanceDB/arrays. Collection replaces Project.
Scientific metadata/schema is immutable per release; mutable catalog descriptive
fields serve browse, and export deliberately pins a submission-time descriptive
snapshot. Later omitted metadata inherits exact pinned-base pair, not latest.

Search must filter undiscoverable resources before LIMIT/count/facets/cursors;
source lineage disclosure remains independent from output visibility. Credentials
stay application/server-side; client.search is direct scientist-facing service.

## Prototype evidence

No search/export prototype run. 001 query owner creates/runs root
`uv run python roadmap/prototypes/search_plan.py` against disposable PostgreSQL 16.
Deterministic 10k-row corpus with visible/hidden collections, duplicate sort keys,
JSONB scientific fields and non-ASCII text. Test keyset walk at limit 1, modified
titles, concurrent publication, injection/invalid filters and permission revocation.
Capture EXPLAIN (ANALYZE, BUFFERS), index sizes and transaction timings. Recommend
synchronous publication search projection for committed-readability freshness;
qualify cost before accepting. Export twice around title/schema edits must produce
identical pinned payload/digest unless explicitly requested labelled live section.
Do not report prototype or performance PASS without actual output.

## Exact scope and ownership

- Post-002 `core/catalog/interface/{search,export,ports,errors}.py`,
  `_impl/{search,export}.py`; own cohesive query/filter/cursor/value contracts.
- `core/database/schema/search.py`, repositories/search.py and export.py,
  Alembic indexes/migration; 006 publication transaction projection hook.
  Current `core/metastore/{queries,hierarchy,rows}.py` are evidence for existing
  SQL visibility and keyset conventions, not caller-importable implementations.
- `applications/api/routes/v1/endpoints/search.py` and proposed exports.py,
  schema/search.py/export.py transport models; update complete OpenAPI artifact.
- Existing tests/hierarchy_contract.py and contract/test_catalog_store.py fixtures;
  add tests/unit/core/catalog/test_search.py, test_export.py,
  tests/contract/core/database/test_search.py and integration/test_search_export.py.
- SDK wire generation ownership 008; UI integration 009; no fixture data offered as
  backend result. Delete obsolete search placeholder response/tests, retaining
  supported error behavior. No LanceDB package, array schema or speculative vector DB.

Fresh deployment approved 2026-10-06: schema/index bootstrap is required, legacy
release backfill/conversion is not. Projection repair/rebuild for newly published
authoritative documents remains required; never invent metadata or select newest
schema for a pinned export. Nonempty bootstrap targets refuse with operator action,
not data/volume reset. Hidden stale-base losers have no published lineage/receipt
and never appear in search/export; atomic publication projection still applies.

## Interfaces and implementation examples

Proposed public signatures (not installed):

```python
async def search(actor, query: SearchQuery, cursor: Cursor | None) -> SearchPage: ...
async def export_release(actor, release_id, *, include_current: bool = False) -> ReleaseExport: ...
```

SearchQuery constrains text, typed filters, page size and declared sort. Use
parameterized direct asyncpg, explicit FTS language with matching GIN expression,
targeted JSONB operators/indexes and relational ancestry/FK indexes. Stable tie
breaker includes immutable ID; opaque cursor binds filter/sort/version and authority
semantics, never leaks hidden result count. Reject stale/mismatched cursor explicitly.
Schema-version differences require typed query rules, not unsafe text-to-number casts.

ReleaseExport owns release ID/manifest, scientific metadata, exact schema documents/
versions/digests, descriptive snapshot, lineage visibility and DTO version. Default
export is reproducible; current title/description is separate live section excluded
from pinned digest/retry fingerprint. Envelope is server-owned. Candidate uploads
never appear in search. A synchronous projection should join publication/lineage/
receipt transaction; if prototype instead selects asynchronous projection, specify
watermark/staleness/repair and revisit committed-search acceptance explicitly.
No silent staleness model. Authority changes must filter immediately even if text
projection is older. Reads re-authorize and return 404 for hidden dataset/release.

## Serial task slices

1. Pending: query/filter/keyset contract and real indexes/explain plans, preserve
   existing browse behavior. Unit+real PG contract gate below.
2. Pending: publication projection/repair and search HTTP/OpenAPI; verify commit/search
   and permission revocation under concurrent writes. Full integration gate.
3. Pending: immutable export DTO/snapshot versus live fields, lineage filtering and
   retries through metadata/title edits; remove placeholder handlers. Full gate.
Each slice serial, skills below, independent baseline/reviewer reruns max 3 reviews.

## Skills

`.agents/skills/oop-design/SKILL.md`, `.agents/skills/postgresql-table-design/SKILL.md`,
`.agents/skills/fastapi/SKILL.md`, `.agents/skills/implementation-plan/SKILL.md`.

## Acceptance and complete applicable gates

Root locked uv/Python >=3.12: `make lint`;
`uv run pytest -m unit --cov=src/huron --cov-report=term-missing`;
`uv run pytest -m contract`; `uv run pytest -m integration`; `make test-acceptance`
(publication transaction changes); `make docs`; `git diff --check`;
`uv run python scripts/check_openapi.py --check`;
`uv run python scripts/check_database_schema.py` (002/004-created scripts).
PG16/testcontainers; isolated Linux/Podman integration runner/historical object;
>=25 GiB acceptance disk. Missing infrastructure, empty suite or unrun query
prototype is BLOCKED. No web gate until frontend source changed.

Keep configured 96.01% floor, import/complexity/duplication gates; radon C+/MI B+
are findings and duplication permits no new/growing group at 0.80. Reuse scoped
fixtures; deterministic corpus/barriers, real PG query/visibility/index tests,
mock only external I/O, no skips/xfails/suppressions/weakened assertions. Record
EXPLAIN evidence and controlled load observations, not fabricated SLO. Every phase
acceptance includes hidden result/cursor/facet tests and reproducible export after
mutable descriptive update. Independent baseline and final reruns capture commands,
cwd/version/exit/coverage/logs and reviewer findings.

## Blockers and readiness

001 query/freshness/DTO experiment; 004 schema versions/descriptive snapshot;
006 release/lineage publication and fresh schema/index bootstrap proof. Recommend
synchronous small projection and default pinned export; prototype must qualify.
Independent review before `/implement-markdown roadmap/plans/007-search-export.md`.

## Execution ledger

Planning writer attempt 1; no application/prototype execution; review 0. Future
parent logs child/model/role/timestamps/commands/verdict, minute polls/15-minute
progress, one active writer/reviewer. Preserve unrelated dirty files.

## Escalation / final receipt

BLOCKED draft. Final receipt must include authoritative PostgreSQL visibility,
freshness and export reproducibility evidence, not screenshots of fixture search.
