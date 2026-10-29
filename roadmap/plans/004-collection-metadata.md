# Phase 004: Collection catalog and immutable metadata schema registry

Status: BLOCKED — schema product-profile decision, bootstrap evidence and 002/003 prerequisites.

## Context and outcome

Current `core/catalog/types.py` has Project and Dataset.project_id;
`DescriptionChange` uses None to retain descriptive fields. Current Raw
MetadataSubmission is a shared Pydantic BaseModel with title/creators/optional
extensions. New domain metadata must not reuse that transport model. Current
Alembic env has target_metadata=None; schema-map script checks only a docstamp.

Target Organization → Collection → Dataset replaces Project, not adds a level.
Dataset title/description/core descriptive fields combine with organization required/
optional scientific fields and collection extensions. Organization owners publish
immutable versioned schemas and extensions. Accepted extensions ADD fields only,
never redefine/weaken organization fields. New dataset requires metadata AND schema.
Later omitted metadata inherits exact metadata/schema pair from PINNED BASE even
if newer schema exists; explicit null is not omission, empty object is validated.
Freeze bundle at submission, preserving historical validity. Client validation
and authoritative backend validation both apply.

## Prototype evidence

Current evidence (2026-10-06): schema restricted profile 2 independently qualified
at review 2, not approved product policy: 430 cases per seam / 860 outcomes plus
numeric/structural probes; shared validator leaves common-mode risk. Actual bounded
commands: `.venv/bin/python -B roadmap/prototypes/schema/schema_bundle.py` and
`.venv/bin/python -B roadmap/prototypes/schema/reproduce_numeric.py`, cwd root.
Numeric comparison recommends correct codec/canonical bytes authority instead of an
artificial 1e20 restriction; this is an unqualified, unapproved proposal. No database
or production SDK/backend parity follows from that receipt. Remaining target corpus:
Bounded proposed profile Draft 2020-12: disjoint explicit property maps + required
sets compiled into one closed object, controlled immutable digest-pinned refs,
network fetch prohibited. Reject overlapping names even if definitions are equal;
nested structure/format assertions/limits must be specified. Never naive allOf with
closed base additionalProperties=false. Corpus must prove base-only validity,
required extension field errors, weakening/overlap rejection, missing/null/empty,
unknown dialect, remote/cyclic refs, schema update during retries and historical
bundle validity. Cross-validator Python SDK/backend results must match exactly.
Product-profile approval and fresh bootstrap/drift evidence are still missing.

## Exact scope and ownership

- Current `core/catalog/{types,paths,ports,errors}.py`, `_impl/{creation,collections,documents}.py`
  → supported values/operations in `catalog/interface/` after 002. Rename Project
  and ProjectCollection, Dataset.project_id, ancestry and path segments deliberately.
- `core/security/{rules,roles,scopes,facts}.py` or their post-002 interface locations:
  PROJECT scope and project capability codes → Collection; binding constraints,
  IDs and permissions change coherently in code/schema, with role-invariant tests preserved.
- `core/database/schema/{catalog,metadata}.py` proposed SQLAlchemy Core definitions;
  `core/database/repositories/{hierarchy,metadata}.py` direct asyncpg mappings;
  `migrations/env.py` target_metadata, new versioned migration(s), schema.sql.
  Existing `core/metastore/{hierarchy,rows,queries}.py` are source evidence/002 inputs.
- Proposed `catalog/interface/metadata.py` values SchemaVersion/SchemaBundle/MetadataPair;
  `catalog/_impl/schema_registry.py`; `schema/metadata_profile.py` pure validation.
- API current `routes/v1/endpoints/{projects,organizations,datasets}.py`, schema DTOs
  and routers; add `collections.py` and `metadata_schemas.py`, delete project route
  module/export when all consumers migrated. New application Pydantic models map
  explicitly; server envelope is never scientific user metadata.
- `scripts/check_database_schema.py` new owner here for actual migrated-PG versus
  metadata drift; preserve `scripts/check_schema_map.py` docstamp, not substitute it.
- SDK wire artifact/mapping, web `api/{types,client,fixtures}.ts` and `[org]/[project]`
  route migration implementation belongs to 009; carry the exact route/type/fixture
  inventory in that handoff. This phase completes backend Collection cutover only;
  global rename completion requires 008 SDK and 009 UI, without a dependency cycle.
  The fixture prototype may retain clearly labelled historical Project vocabulary
  until then, but cannot call removed Project APIs or claim integration. No silent
  compatibility aliases. Server fixtures/tests migrate with the backend here.
- Tests extend hierarchy_contract.py, contract/test_hierarchy_store.py and
  test_catalog_store.py, integration/test_catalog_creation.py/descriptions.py;
  add owner-mirrored metadata tests, real migration/drift contracts.

Fresh deployment approved 2026-10-06: no legacy Project/ID/FK/path/role/history
conversion or data migration rehearsal is an MVP requirement. Fresh SQLAlchemy/
Alembic schema bootstrap, constraints and drift verification remain required.
Nonempty targets refuse and surface operator action; never delete/reset existing
datasets or volumes. Remove old owned Project code/schema definitions/tests only
at atomic replacement with meaningful behavior covered. Current implementation
remains authoritative until then; crash/recovery and controlled-runner gates remain.

## Interfaces and implementation examples

Existing `Dataset(id, project_id, slug, title, description, ...)` and
`MetadataSubmission(BaseModel)` versus proposed domain values:

```python
@dataclass(frozen=True)
class MetadataPair:
    scientific: Mapping[str, JsonValue]
    bundle: SchemaBundle

async def create_dataset(actor, collection_id, description, metadata: MetadataPair): ...
async def publish_schema(actor, organization_id, schema_document, version): ...
```

Illustrative signatures, not existing APIs. Keep deep immutable/canonical copies;
frozen dataclass alone does not freeze a nested mapping. Transport uses field-presence
information: absent+base inherits both; absent+no base rejects; null rejects; {} validates;
supplied metadata needs explicit bundle; schema-only rejects. Pin refs/digests at
submission in one transaction. Publish schemas by org-owner authorization only.
Relational IDs/ancestry/title/description plus JSONB scientific/schema documents
with object checks; explicit FK indexes, immutable published-version guards and
cross-parent consistency. Runtime queries/transactions only asyncpg; no SQLAlchemy
sessions/SQLModel/DB-Pydantic shared model.

Capture descriptive snapshot at submission with version in request fingerprint.
Later catalog edits affect browse, not published reproducible export/retry snapshot.
Envelope owns release IDs/actors/time/manifest/lineage; reject client attempts to set
those through metadata. No implicit schema latest adoption.

## Serial task slices

1. Pending: fresh bootstrap + Collection rename DB/domain/API/roles/storage path
   inventory; independent review and separate production approval. Full gate.
2. Pending: SQLAlchemy Table/MetaData and real drift contract, Alembic wiring. Validate
   upgrade/downgrade/upgrade and reject manually introduced drift. Full real DB gate.
3. Pending: immutable registry/additive composition/owner-only publishing, corpus
   and required metadata creation. Unit + real registry constraints + integration.
4. Pending: submission pair freeze/inheritance/export snapshot values and generated
   OpenAPI updates; consumer rename conformance checks. Full gate including acceptance
   because Raw metadata inputs change; frontend gate only when that boundary changes.
Each slice is serial writer/reviewer with skills below and maximum three reviews.

## Skills

`.agents/skills/oop-design/SKILL.md`, `.agents/skills/fastapi/SKILL.md`,
`.agents/skills/postgresql-table-design/SKILL.md`,
`.agents/skills/implementation-plan/SKILL.md`. If renaming frontend consumers now,
also `.agents/skills/svelte-code-writer/SKILL.md`,
`.agents/skills/svelte-core-bestpractices/SKILL.md`,
`.agents/skills/playwright-cli/SKILL.md`; Tailwind if styles change.

## Acceptance and complete applicable gates

Root locked uv/Python >=3.12: `make lint`;
`uv run pytest -m unit --cov=src/huron --cov-report=term-missing`;
`uv run pytest -m contract`; `uv run pytest -m integration`; `make test-acceptance`;
`make docs`; `git diff --check`; `uv run python scripts/check_openapi.py --check`
(002-owned prerequisite). New command owned here:
`uv run python scripts/check_database_schema.py` against disposable migrated PG16;
its script must compare reflected tables/FKs/indexes/constraints/defaults and
explicit trigger inventory with definitions, not just Alembic revision stamp.
Acceptance includes historical bundles/newer schema inheritance and descriptive
edit/retry stability. Keep 96.01% floor, import/complexity/duplication ratchets,
radon C+/MI B+ findings; no suppressions/skips/xfails or weakened assertions.

Prerequisites: PG16 testcontainers, isolated Linux/Podman full integration runner
and historical object, >=25 GiB acceptance disk, owned disposable fresh database.
Reuse scoped fixtures/helpers and meaningful existing behavioral tests. Inspect
coverage of changed failure branches. Record exits/logs/versions and independent
baseline/final reruns; no tests/services means BLOCKED.
For any frontend consumer changes, cwd web: autofixer each changed Svelte component,
`npm run check`, `npm test`, `npm run lint`, `npm run build`, `npm run test:e2e`;
named-session CLI QA mobile/816px/wide/light-dark/keyboard/error/empty/loading states.

## Blockers and readiness

001 schema product-profile decision and reconciled corpus, fresh bootstrap proof, 002 exact
schema/owner paths, 003 authority, explicit frontend rename handoff. Proposed
composition/export snapshots need prototype review; no evidence invented.
Independent plan review before `/implement-markdown roadmap/plans/004-collection-metadata.md`.

## Execution ledger

Planning writer attempt 1; no product/prototype execution; review count 0. Future
parent records sessions/models/time/commands, serial baseline/writer/reviewer, max
three reviews, progress every 15 minutes and minute polling. Preserve unrelated work.

## Escalation / final receipt

BLOCKED draft. Final receipt names actual table/FK/role/API/storage/SDK/UI rename
coverage, fresh bootstrap and validation/drift evidence; no “Collection done” by docs alone.
