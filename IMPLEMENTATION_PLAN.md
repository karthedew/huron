# Huron duplication improvement backlog

Status: **D5 and selected D6 improvements remain open.** The domain-owned Core
migration is complete; [its receipt](docs/history.md#domain-owned-core) records the
verified source and code removals. The former D0–D4 execution logs and full original
plan are [archived](docs/history.md#archived-plans-and-investigations).

This is a behavior-preserving improvement backlog, not permission to implement
future product capabilities. Select work only when a current report and actual
callers demonstrate a shared responsibility worth consolidating. Some original
Raw, authentication and forwarding candidates were already replaced by the Core
migration; reassess them before assigning further work.

## Authority and working method

- [AGENTS.md](AGENTS.md) owns engineering rules and the permitted package graph.
  [Architecture](design/architecture.html#domain-owned-core), [Raw](design/layer-raw.html),
  [API](design/api.html) and [Security](design/rbac.html) own the behavior contracts.
- Use OOP guidance for Core, PostgreSQL guidance for persistence, and FastAPI
  guidance for transport. Interfaces belong to consumers and should hide useful
  behavior rather than merely forward calls.
- Establish the current working-tree baseline and preserve unrelated changes.
  Record exact matching symbols, their responsibility, retained distinctions,
  affected callers and tests before each selected slice. Use current paths and
  fragments rather than historical scanner group IDs.
- Complete each slice through operations, adapters, callers and tests. Give shared
  files one integration owner. Remove superseded interfaces after their final
  caller and unique behavioral coverage have moved.
- Preserve distinct domain types, explicit routes and typed decoders. A similar
  declaration or scanner silhouette alone does not justify a common abstraction.

## Fixed behavioral contracts

- **Discovery:** preserve hidden/missing 404 ordering, dataset-only grants, server
  ancestry and fresh authority per operation. Keep request-local HTTP caches local.
- **Pagination:** apply visibility before limits; retain C-collation `(slug, UUID)`
  hierarchy order and visible-result `has_more` semantics.
- **Descriptions:** omitted/null fields retain values; empty strings replace them.
  Changed slug fails before stale version; stale no-op fails. Valid no-op writes
  nothing. CAS, ancestry reads, durable generation write and database commit retain
  their ordering and rollback behavior; filesystem work stays off the event loop.
- **Creation:** preserve validation, exact targets, claim ownership, fingerprints,
  replay, uniqueness, actor attribution and generation ordering.
  Dataset profile strings remain verbatim; this cleanup introduces no registry check.
- **Persistence:** required/optional/locking reads and writes with `RETURNING`
  retain their different failure/atomicity semantics. Preserve explicit conversion
  of JSON, enums, UUIDs, joins and nested values, and one connection per transaction.
- **Raw:** preserve file membership, owner/admin exceptions, lease/CAS fences,
  verified independent payload, frozen intents, retries and crash recovery. Freeze,
  filesystem publication and final database recording remain separate phases;
  revision/session/audit/outbox/receipt recording is atomic.
- **HTTP/authentication:** preserve paths, methods, named schemas, filtering,
  redaction, headers, status/problem codes, ETags, Location, retries and streaming.
  Credential deadlines are checked after lookup; core authority remains independent
  of early HTTP guards.

## D5 — Simplify HTTP schema and result handling

Current scope: `src/huron/applications/api/routes/v1/schema/` and the corresponding
hierarchy/governance handlers.

- [ ] Share genuinely identical hierarchy response fields and PATCH validation
  while retaining named leaf views/pages and entity-specific contracts.
- [ ] Use existing response models with typed domain returns where equivalent;
  retain explicit conversion when projection, nested values, headers, special
  statuses or streaming require it.
- [ ] Preserve explicit route definitions, workflow ownership and guard/error order.
- [ ] Compare complete OpenAPI and actual responses; only semantically unordered
  `required` arrays may be normalized. Verify internal fields and credentials stay
  excluded. Investigate every other difference.

Use the existing hierarchy, pagination, precondition, binding, policy, service-account
and router-composition tests. Add observable schema/filtering evidence where missing.
Exit: the HTTP contract is preserved and useful duplication has been removed, with
a fresh complete scan. No predicted numeric score is an acceptance criterion.

## D6 — Reassess remaining measured duplication

| Candidate | Current owner | Preserve |
| --- | --- | --- |
| D6a: repeated persistence result mechanics | `core/metastore/` | Required/optional errors, locking and mutations, fixed projections, joined/auth-specific conversions. |
| D6b: remaining Raw forwarding or publication orchestration | `core/raw/`, application wiring | Named authorized operations, membership, forced-abort exception, state/lease rules, immutable intent, exact transaction grouping and trusted expiry. |
| D6c: shared credential/identity or domain calculations | `core/security/`, relevant Catalog/Raw/Foundation modules | Token formats, post-lookup expiry, CSRF, principal-kind authority, disclosure, identities and scientific metadata. |

- [ ] Select a bounded family only after confirming it still contains real duplicated
  behavior. Retain distinct contracts explicitly when consolidation would harm them.
- [ ] Keep nontrivial decoders and domain transitions explicit; avoid generic CRUD,
  reflection codecs, unrelated-value inheritance and callbacks that hide ordering.
- [ ] Move relevant behavioral evidence to the new public interface, migrate callers,
  delete replaced implementation, and run the affected gate and complete-source scan.
- [ ] Reconsider a design that creates comparable new duplication or disperses
  responsibility; do not stack abstractions onto an unsuccessful approach.

D6a needs row tests and real auth/RBAC adapters. D6b needs direct authorization,
Raw crash matrices, PostgreSQL commit-intent/process-death contracts, restart
integration and large-file acceptance when durability changes. D6c needs its
credential/domain tests plus affected transport and real persistence contracts.

## D7 — Resolve the residual inventory and prove completion

### Measurement resolution

The former native-90 objective was retired on 2026-09-15. The active contract is
`scripts/check_duplication.py` against `scripts/duplication_baseline.json`, using
pyscn 1.31.1 at similarity 0.80. It rejects increased total clones and unknown or
grown group signatures; the native score is reported, not gated. Preserve scanner
settings, complete-source scope, coverage/complexity thresholds and import rules.

Path-only moves require explicit fragment-backed reconciliation. Splits/merges
need review of their actual contents. Do not regenerate a permissive baseline or
change code merely to evade detection. Ratchet allowances down only after a real
decrease; do not expand them to hide a failed refactor.

The Catalog publication consolidation narrowed one existing allowance: the group
containing `_Collection.describe`, all three `CatalogCreation` operations and Raw
reservation lost `describe`. Its signature now contains only `catalog/_impl/creation.py`
and `raw/_impl/ingest.py`, and its size allowance fell from five to four. The total
baseline consequently fell from 145 to 144; all other allowances and scanner settings
were preserved. This is a reviewed contraction of an existing family, not a new group.

- [ ] Account for remaining matches by current symbol and responsibility, including
  those deliberately retained because their contracts differ.
- [ ] Run the complete applicable gate on the final tree and inspect findings as
  well as exit codes; refresh affected checks after review fixes.
- [ ] Obtain independent standards and behavior/security/transaction reviews and
  resolve actionable findings.
- [ ] Record a concise final receipt with source identity and update affected
  architecture/status documents. Keep bulk logs in CI artifacts or external storage.

## Verification

Use the repository environment and lockfile. Focused tests provide feedback;
completion uses [AGENTS.md's gates](AGENTS.md#commands-and-gates): `make lint`, unit
coverage, contract and integration suites, plus Raw acceptance when ingestion or
durability changes and `make docs` for site documentation. Inspect radon findings,
not only its exit status. Preserve unique behavioral evidence when retiring tests
that only asserted old wrappers or namespaces.

PostgreSQL tests require disposable real adapters; zero collected or deselected
integration tests are not a pass. Raw acceptance requires at least 25 GiB free on its
actual test-data filesystem, with extra capacity for concurrent cases. See
[Testing](docs/getting-started/testing.md) for current commands and infrastructure;
historical machine-specific paths are not configuration.
