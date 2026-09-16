# Huron duplication reduction — implementation plan

**Source-path reconciliation:** the approved [domain-owned Core migration](docs/plans/domain-owned-core.md)
replaces this plan's original `pkg`/flat-Core locations with domain-owned packages.
Historical slice paths and receipts below retain their original meaning; subsequent
work uses the migration's ownership map and current `AGENTS.md` dependency rules.
This reconciliation does not mark any outstanding duplication-plan slice complete.

Status: **D4 independently verified (2026-09-14); paused before D5 pending a decision on the native-90 target (see D4's feasibility analysis)**.
Written 2026-09-10 against source commit `6082088`. D0–D2 are tested; the native
90/100 target remains outstanding. On 2026-09-11 the user prioritized finishing
P3 functional and acceptance work after stabilizing D3a. See
[P3 execution rules](P3_IMPLEMENTATION_PLAN.md#execution-rules). D3b–D7 are paused,
not completed; scanner settings and thresholds remain unchanged.

Implement the architecture in
[design/duplication-architecture.md](design/duplication-architecture.md) until
pyscn's **native duplication score is at least 90/100** and all applicable
verification gates pass. Preserve observable behavior, authorization, persistence,
and durability throughout the refactor.

The completed authentication plan formerly at this path is preserved verbatim in
[AUTH_IMPLEMENTATION_PLAN.md](AUTH_IMPLEMENTATION_PLAN.md). It is historical
context, not part of this work.

## 1. Authority, scope, and completion

Read [AGENTS.md](AGENTS.md), the duplication architecture above, and the relevant
sections of [architecture](design/architecture.html), [RBAC](design/rbac.html),
and [Raw ingestion](design/layer-raw.html). For Raw changes also read
[P3_DESIGN.md](P3_DESIGN.md), M1a in
[P3_IMPLEMENTATION_PLAN.md](P3_IMPLEMENTATION_PLAN.md), and the implemented
evidence in [P3_M1A_VALIDATION.md](P3_M1A_VALIDATION.md).

This plan covers genuine duplication in `src`, the tests needed to prove the
refactors, application wiring, import contracts, and affected documentation.
It does not introduce new HTTP behavior, change the database schema or persisted
document formats, implement future compute/frontend features, execute deployment
or cutover, or implement M1b/M1c. A need to change a scientific or persistence
contract is a design issue to resolve before the dependent refactor proceeds.

Completion requires all of the following:

- A fresh, complete pyscn 1.31.1 report for the entire `src` tree that passes
  the regression guard in `scripts/check_duplication.py` (no growth in total
  clones, and no clone group with a file signature unknown to or larger than
  the committed `scripts/duplication_baseline.json`, at similarity 0.80); see
  D7's resolution for why this replaced the native-90 target.
- `make lint`, the configured unit coverage gate, all contract and integration
  tests, and any applicable acceptance/documentation gates pass on the final tree.
- Replaced interfaces and their forwarding implementations are removed; concrete
  application callers and both persistence adapters use the new interfaces.
- Direct core, HTTP, real PostgreSQL, and filesystem evidence establish the
  affected invariants. Independent review has no unresolved actionable defects.
- Delivery records state the actual score, source identity, test outcomes, and
  limitations. A duplication pass alone does not mark M1a or P3 complete.

Writing this plan is documentation work. None of these implementation criteria
are satisfied merely by producing the plan or its architecture proposal.

## 2. Baseline and measurement contract

The latest source scan is
`.pyscn/reports/analyze_20260910_070754.json`, produced by:

```sh
uv run --locked python scripts/check_duplication.py src
```

| Measurement | Recorded baseline |
| --- | ---: |
| Native duplication score | 50/100 |
| Cloned / total fragments | 241 / 800 |
| Cloned fraction | 30.125% |
| Clone pairs / groups | 319 / 60 |
| Python files analyzed / skipped | 109 / 0 |

The native curve requires a cloned fraction strictly below 7.5% for 90: at 800
fragments, at most 59 can remain cloned; at 700, at most 52; at 600, at most 44.
Deleting methods changes the denominator too. These numbers describe the target
as originally set, not a replacement score calculation or forecast of individual
milestone gains. **As resolved in D7 (2026-09-15), the native-90 target is
unreachable by measurement design and is no longer gated**; the regression guard
in `scripts/check_duplication.py`, checked against `scripts/duplication_baseline.json`
at clone-threshold 0.80, is the operative completion measure going forward.

An isolated three-view inheritance prototype preserved the complete OpenAPI
contract after normalizing `required` property ordering and measured 237/798
cloned fragments, still score 50. Recreate and test the useful change in D5;
temporary files under `/private/tmp/huron-common-caller-design/` are not a required
dependency for executing this plan.

Previous source validation recorded 1,423 unit tests at 94.75% coverage and 31
real-adapter tests (30 contract, one integration). Those are historical receipts,
not expected test-count assertions or proof for a later source tree. The configured
coverage floor is 94.71%; never lower it.

### Rules for each measured slice

1. Record the source commit and working diff; preserve unrelated work. Scan all
   of `src` using the locked checker. Compare analyzed file paths with the actual
   source inventory; new modules are allowed, skipped or omitted source is not.
2. Count inventory from `clone.clones`, identified by file and symbol/range.
   Group IDs are report-local and may change; group membership alone is not the
   full inventory. Inspect the matching behavior before deciding it is reusable.
3. After tests and static checks, capture the new native score, cloned/total
   fragments, pairs, groups, file coverage, deleted interfaces, remaining matches,
   and newly introduced matches. Preserve the exact reported JSON immediately
   under a unique slice label; do not select the newest report by directory order.
4. An unchanged rounded score can still accompany a useful fragment reduction.
   Keep a change only when it improves the architecture and retains its behavior
   evidence. A moved wrapper or new callback registry is not sufficient progress.
5. The known duplication failure may remain during intermediate work. Label the
   slice **tested; duplication target outstanding**, never green or deliverable
   as completion of this plan. Every other required gate must pass before building
   on the slice. Record scanner/tool failures separately from a valid score below 90.

Keep the scanner version, settings, detection scope, score threshold, coverage
and complexity thresholds, and import restrictions. Do not add exclusions,
suppression markers, skipped tests, denominator padding, or syntax/docstring
changes whose purpose is to evade clone detection.

## 3. Target responsibilities and fixed contracts

### Module destinations

The following records the original destinations used by the duplication slices.
Resolve them through the domain-owned migration map for current implementation;
introduce interfaces with real callers and tests rather than scaffolding future work.

| Responsibility | Current source | Target |
| --- | --- | --- |
| Authorized hierarchy reads/descriptions | `core/catalog.py`, `core/_catalog.py` | `core/catalog_collections.py`: shared typed collection implementation |
| Organization/project/dataset creation | Same two modules | `core/catalog_creation.py`: explicit creation workflows |
| Immutable releases | Same two modules | `core/releases.py`: release read/publication workflows |
| Binding, policy, service-account administration | Same two modules | `core/bindings.py`, `core/policies.py`, `core/service_accounts.py` |
| Current authorization facts and ancestry | `core/access.py`, `core/scopes.py`, `_catalog.py` forwards | Focused consumer ports; inject actual read/binding collaborators without another repository facade |
| Catalog persistence interfaces | `core/ports.py` | `core/catalog_ports.py`; other consumer ports move with their workflows |
| Repeated SQL result handling | `pkg/metastore/hierarchy.py`, later other adapters | Adapter-private `pkg/metastore/queries.py`, explicit typed projections and decoders |
| Runtime composition | `applications/api/app.py`, `runtime.py`, `dependencies.py` | Same application modules, wired to the focused workflows |

All historical paths in the table are relative to `src/huron/`. Current domain values
live with their Core owners; adapters live in `core/metastore`. `Window` belongs to
Catalog, retry identities/receipts to Foundation, and upload ledgers to Raw.

Use the project-local OOP guidance for Core work, PostgreSQL guidance for
adapters and transactions, and FastAPI guidance for HTTP/wiring. The
codebase-design vocabulary and deletion test govern the shared interfaces.

### Collection interface

A typed collection implements `get`, `browse`, then `describe` for organizations,
projects, and datasets. Results remain statically typed as the concrete entity;
pages retain `Window[T]` and the current cursor contract. An explicit platform-root
value represents the organization collection's parent. Releases retain their own
key/cursor and do not gain a descriptive-update operation.

Concrete construction binds resource kind, reader, update capability, and parent
scope together. Do not allow independently configurable combinations that authorize
one kind while reading another. Core receives the authenticated actor and injected
capabilities; it recomputes authority for each operation. Preserve the distinct
request-local HTTP binding-cache behavior; do not promote that cache into a
long-lived core permission snapshot.

Keep creation explicit. Do not introduce an `execute(kind, action, **fields)`
dispatcher, extensible sequencing callbacks, a generic CRUD manager, a reflection
codec, or generated HTTP routes. Shared SQL execution uses fixed trusted
projections and bound request parameters; domain/core interfaces expose no SQL.

### Invariants that every slice must retain

- **Discovery and authorization:** point reads retain visibility-based admission;
  do not invent an additional read capability. Hidden targets/parents remain 404
  before permission errors. Ancestry comes from the server. Dataset access through
  a narrow grant must not start requiring independent parent visibility.
- **Pagination:** apply visibility before limiting; preserve C collation,
  `(slug, UUID)` ordering for hierarchy pages, existing release cursors, and
  `has_more` based on visible results. No per-row query loop or unbounded fetch to
  perform filtering in Python for PostgreSQL pages.
- **Descriptions:** omitted/null title and description retain stored values;
  empty strings replace them. Changed slug fails before stale version; stale
  no-op fails. A valid no-op opens no mutation transaction and writes no generation.
  A change performs CAS, committed ancestry reads, durable generation writing,
  then database commit. Failed CAS writes no generation; write failure rolls back
  the row. Keep filesystem work off the event loop.
- **Creation and releases:** retain per-operation validation and error ordering,
  claim ownership, fingerprint/replay behavior, parent/revision checks, uniqueness,
  and durable generation/tag publication before database commit. Derive provenance
  from the actor. Dataset profiles are currently stored verbatim; do not introduce
  profile validation in this refactor.
- **Persistence:** keep required reads, optional reads, locking reads, and writes
  with `RETURNING` distinct where their error/atomicity contracts differ. Preserve
  explicit JSON, enum, UUID, join, and nested-value decoding. Each atomic mutation
  retains one acquired connection or staged memory transaction; do not silently
  change committed ancestry reads into transactional reads.
- **Raw:** retain file/session membership, lease fencing, owner/admin exceptions,
  verified installed-byte evidence, immutable intents, retry conflicts, and crash
  recovery. Intent freeze, filesystem publication, and final database publication
  remain separate phases. Revision/session/audit/outbox/receipt publication stays
  atomic within the final database transaction.
- **HTTP:** retain paths, methods, named schemas, serialization, redaction, headers,
  status/problem codes, ETags, Location, retry responses, and streaming behavior.
  HTTP guards never become the sole authorization for a core operation.

## 4. Dependency order

```text
D0 baseline and consumer map
  → D1 typed reads and authorization-facts seam
  → D2 descriptive updates
  → D3a creation → D3b releases
  → D4 governance and retirement of the mirrored catalog surface
  → D5 HTTP/schema simplification
  → D6 remaining persistence and forwarding, selected by the report
  → D7 residual inventory and final verification
```

D3a, D3b, and D6 sub-slices each receive their own measurements. Work on
independent tests or read-only review can run in parallel. Changes to
`core/ports.py`, `_catalog.py`, `metastore/hierarchy.py`, and application wiring
have one integration owner; do not have parallel implementers rewrite those
files. Complete each vertical slice through callers, adapters, and tests before
starting its dependent slice.

## D0 — Establish the execution baseline

- [x] Record HEAD, working-tree ownership, the locked environment, complete source
  inventory, native report, and current non-duplication gate outcomes. Inspect
  [Makefile](Makefile) and [CI](.github/workflows/ci.yml) before selecting commands.
- [x] Map every consumer of `CatalogService`, `HierarchyRepository`,
  `HierarchyStore`, and `HierarchyWriter`, including imports used only for typing.
  Include `AccessPolicy`, scope helpers, `RawIngestionService.create_in_project`,
  `IdentityService`, revision reads, HTTP authorization, bootstrap, and readiness.
  Maintain a deletion matrix: old symbol → new owner → migrated callers →
  preserved behavioral tests. Close a row only when the old implementation is gone.
- [x] Capture a baseline full OpenAPI document and representative response/error
  contracts from the same runtime settings. Add new behavioral coverage only for
  gaps needed by the first slice; do not freeze private forwarding call sequences.
- [x] Establish disposable PostgreSQL 16 through the local Docker-compatible
  socket and temporary filesystem tests. Record unavailable prerequisites; do
  not substitute in-memory results for real-adapter evidence.

**Exit evidence:** a reproducible baseline and consumer/test map, with duplication
explicitly failing at its measured native score. Do not label this a passing gate.

## D1 — Replace repeated hierarchy reads

**Files:** `core/catalog.py`, `_catalog.py`, `access.py`, `scopes.py`, `ports.py`;
new `core/catalog_collections.py`, `catalog_ports.py`; `pkg/metastore/hierarchy.py`,
`rows.py`, new `queries.py`; affected application dependencies/runtime/guards.
Paths are under `src/huron/`.

- [x] Give access/scope helpers focused hierarchy and binding-facts ports. Inject
  actual collaborators so authorization no longer requires the broad internal
  repository. Preserve internal classification and dataset-parent fact reads
  needed to calculate visibility before discovery. Resolve the addressed
  resource's full scope/storage ancestry only after its discovery decision;
  unrestricted ancestor lookup remains internal. Do not create a circular
  dependency between visibility calculation and visible resource lookup.
- [x] Implement typed organization/project/dataset `get` and `browse` through both
  memory and PostgreSQL adapters. Introduce the small query executor here, paired
  with explicit projections and existing decoders. Fix resource/policy selection
  in concrete construction; no caller-supplied model or table dispatch.
- [x] Migrate `organization/project/dataset` and
  `organizations/projects/datasets` callers across both current core surfaces,
  consumer declarations, and adapters. Update internal Raw/revision/ancestry
  consumers of replaced adapter reads too. Keep state-transition behavior intact.
- [x] Delete each replaced forward/declaration when its final caller migrates.
  Retain only unmigrated real responsibilities in the old modules; add no new
  compatibility layer. Verify precise return types and wiring conformance.

**Tests:** extend `tests/unit/test_core_workflows.py` with direct core point/page
reads, narrow grants, hidden parents, and permissions changed between operations.
Retain scenarios in `tests/hierarchy_contract.py`, driven by
`tests/unit/test_hierarchy_store_memory.py` and
`tests/contract/test_hierarchy_store.py`, especially backend visibility parity
and C-collation ordering. Run affected `test_api_catalog_hierarchy.py`,
`test_api_visibility.py`, `test_api_pagination.py`, scope/authorization tests,
and startup/wiring tests. Use real PostgreSQL for visibility and cursor behavior.

**Exit evidence:** same visible IDs, ordering, errors, and query behavior through
the new interfaces; replaced read wrappers gone; complete native remeasurement.

## D2 — Consolidate descriptive updates

**Files:** D1 collection/port/adapters; `core/_catalog.py` descriptive helpers;
`pkg/catalog/records.py`; organization/project/dataset PATCH handlers and inputs.

- [x] Introduce a typed `DescriptionChange` with today's PATCH semantics.
  Reuse the existing domain `describe` transition and closed entity dispatch.
- [x] Move `patch_organization/project/dataset`, `_patch_description`, and shared
  conditional persistence into one authorized workflow. Typed writers perform
  CAS; the workflow owns the exact validation, no-op, transaction, path, and
  generation order listed above. No sequencing hooks in resource definitions.
- [x] Migrate all three concrete callers and both adapters; remove the replaced
  patch/update delegators and declarations. Do not alter creation or Raw
  transaction contracts while introducing the description capability.
- [x] Add complete workflow evidence using PostgreSQL plus the real filesystem:
  two updates with one expected version produce one winner; losing CAS writes
  no generation; generation-write failure rolls back the row. Existing sequential
  adapter tests alone do not prove these combined guarantees.

**Tests:** `tests/unit/test_catalog_hierarchy_records.py`,
`test_repository_hierarchy.py` (migrate useful cases to the new interface),
`test_core_workflows.py`, `test_api_preconditions.py`, hierarchy HTTP tests, and
the shared memory/PostgreSQL hierarchy contract. Add
`tests/integration/test_catalog_descriptions.py` for combined adapter guarantees.
Retain stale/no-op/slug precedence and off-event-loop filesystem tests.

**Exit evidence:** complete descriptive behavior through all three typed
collections, with real concurrency/rollback evidence and a separate native scan.

## D3 — Move explicit creation and release workflows

### D3a — Catalog creation

**Files:** `core/catalog.py`, `_catalog.py`; new `core/catalog_creation.py`;
catalog transaction ports/adapters; `core/raw.py` creation collaborator;
application creation handlers and wiring.

- [x] Move `create_organization`, `create_project`, `create_dataset`, and their
  useful shared claim/generation mechanics into an authorized creation module.
  Use concrete inputs; do not force their different validation into a universal
  command or callback descriptor.
- [x] Preserve capability checks before claim-owner checks, current classification
  and entry-layer validation, and child-parent resolution before replay where it
  currently occurs. Reuse claim fingerprints and receipts without migration.
- [x] Keep claim arbitration, insert, generation publication, and receipt in the
  existing transaction order. Migrate `RawIngestionService.create_in_project`
  to the focused creation collaborator without changing upload semantics.
- [x] Remove the replaced creation forwards and update direct core/HTTP callers.
  Prove matching concurrent claims return one identity and changed commands
  conflict; add combined workflow evidence if claim orchestration changes.

**Tests:** creation/idempotency cases in `test_repository_hierarchy.py`,
`test_core_workflows.py`, `test_api_catalog_hierarchy.py`, shared hierarchy
scenarios, and real PostgreSQL concurrent-claim/rollback tests. Run affected Raw
creation tests and the restart integration test when its wiring changes.

**Exit evidence:** explicit creation workflows retain identity, validation,
claim/replay, generation, and provenance behavior; native scan recorded.

### D3b — Immutable releases

**Files:** `core/catalog.py`, `_catalog.py`; new `core/releases.py`; release
read/mutation ports; `pkg/metastore/hierarchy.py`; dataset release HTTP handlers.

- [ ] Move `create_release`, release resolution, and release browsing into the
  release module. Share read mechanics only where key/cursor semantics fit.
- [ ] Preserve dataset/revision discovery before replay, exact revision pinning,
  actor-derived provenance, tag uniqueness, and filesystem `write_tag_once`
  collision handling. Tag write and receipt retain their transaction order.
- [ ] Remove the replaced release forwards; verify concurrent retry and conflict
  behavior through the complete workflow, not only database claim primitives.

**Tests:** release scenarios in the hierarchy/repository/core/HTTP suites and
real PostgreSQL contracts; add combined PostgreSQL/filesystem release retry
coverage when reorganizing claim or tag publication.

**Exit evidence:** immutable releases retain their specific contract and cursor;
the separate release scan is recorded.

## D4 — Governance modules and catalog retirement

**Files:** `core/catalog.py`, `_catalog.py`, `access.py`, `identity.py`, `raw.py`,
`ports.py`; new `core/bindings.py`, `policies.py`, `service_accounts.py`;
`pkg/metastore/rbac.py`; application runtime/dependencies/bootstrap/readiness,
authorization guards, binding/policy/service-account handlers, `pyproject.toml`.

- [ ] Move binding grant/list/revoke, policy create/list/attach, and service-account
  operations into focused authorized modules. Pass exact scoped collections;
  verify membership before revocation. System, organization, project, and dataset
  admission rules remain explicit; service accounts do not gain human role rules.
- [ ] Move role compilation and policy decisions only when their existing owner
  belongs in the new module. Preserve atomic source-grant/compiled-binding writes,
  expiry, disabled-account handling, principal-kind restrictions, and error order.
  Policy definitions remain creatable/listable by any authenticated actor; only
  attachment requires the scope-specific permission. Exact-scope binding listings
  continue to include expired records. Service-account disabling retains
  `IdentityService`'s key revocation and already-disabled behavior; the internal
  catalog disable method alone is not a complete replacement workflow.
- [ ] Migrate `IdentityService`'s service-account collaborator, Raw creation,
  revision reads, access helpers, and every runtime consumer discovered in D0.
  Bootstrap and readiness use their actual capabilities, not an unauthorized
  workflow facade. Keep pools/stores/lifecycle ownership in the application.
  Move storage initialization currently performed by `HierarchyRepository`'s
  constructor into application startup before deleting it.
- [ ] Split remaining broad persistence ports by consumer and atomic operation.
  Raw freeze/publication retains its existing writer transaction grouping. Pass
  the same acquired connection to any helper inside an atomic mutation.
- [ ] Delete `CatalogService` and `HierarchyRepository` after all responsibilities
  and callers move. Remove empty retired modules rather than leaving aliases.
  Update import-linter's named-module contracts to the new implementation paths
  while preserving layer, framework, and package-independence restrictions.
- [ ] Search source/tests/config for retired names and imports; require zero live
  callers. Historical planning prose may still name the baseline implementation.

**Tests:** `test_core_workflows.py`, `test_repository_rbac.py`,
`test_api_bindings.py`, `test_api_policies.py`, `test_api_service_accounts.py`,
`test_api_api_keys.py`, `test_api_users.py`, `test_api_app.py`, relevant guards and
scope tests; `tests/contract/test_rbac_store.py` and `test_auth_store.py`;
row-decoding tests in `tests/unit/test_stores_rows.py`. If shared Raw writers or
their construction change, include `test_commit_intents.py`,
`test_ingest_process_death.py`, and `test_verified_raw_ingest.py`.

**Exit evidence:** the mirrored catalog surface is gone, all callers are wired,
typed adapters conform, affected real contracts pass, and full-source score is
recorded. Do not claim score improvement from port/file splitting alone.

## D5 — Simplify HTTP schema and result handling

**Files:** `applications/api/routes/v1/schema/organizations.py`, `projects.py`,
`datasets.py`, shared schema support; corresponding handlers plus bindings,
policies, and service accounts where their new interfaces remove transport glue.

- [ ] Recreate the measured common hierarchy response-field base. Keep distinct
  named leaf views/pages and entity-specific fields. Share PATCH validation only
  across the three genuinely identical descriptive contracts.
- [ ] Replace repeated explicit view conversion with `response_model=ExistingView`
  and typed domain returns where equivalent. Retain explicit adaptation for
  projection, nested values, headers, special statuses, or streaming that need it.
- [ ] Consume the focused authorized workflow/collection from each HTTP operation.
  Preserve explicit route definitions and existing guard/error precedence.
- [ ] Compare the full OpenAPI contract and actual responses with D0; normalize
  only semantically unordered `required` arrays. Investigate every other difference.
  Prove extra internal fields and credentials remain excluded.

**Tests:** existing hierarchy, pagination, preconditions, bindings, policy,
service-account, and router composition HTTP tests. Add focused named-schema and
response filtering assertions to those suites. The temporary prototype is useful
evidence, not a substitute for committed regression tests.

**Exit evidence:** HTTP contracts preserved, useful conversion/model duplication
removed, full native scan recorded. DTO inheritance alone did not raise the
prototype's rounded score; do not forecast a milestone score here.

## D6 — Reduce the remaining measured duplication

D1–D5 are a coherent catalog redesign, not proof that all of `src` will reach 90.
Inspect the new full report and create bounded sub-slices for the remaining real
opportunities below. If the target already passes, perform the residual review
and final gate without broadening the refactor unnecessarily.

| Priority | Candidate source | Allowed consolidation | Required preserved distinction |
| --- | --- | --- | --- |
| D6a | `pkg/metastore/rbac.py`, `principals.py`, `api_keys.py`, `sessions.py`, `credentials.py`, `rows.py` | Proven typed required/optional read execution, fixed projections, shared result mechanics | Missing-row errors, mutations/locks, joined fields, auth-specific conversions |
| D6b | `core/raw.py`, `_ingest.py`, `revisions.py`, `_revision_reader.py`, their ports/wiring | Put mandatory authorization and the complete named workflow in one module where a mirrored interface remains | Ownership, file/session membership, forced-abort exception, lease/state transitions, immutable intent, exact publication transactions |
| D6c | `pkg/auth/apikeys.py`, `sessions.py`, `principals.py`; `core/identity.py`; `pkg/rbac/`; remaining catalog value/document helpers | Shared calculations or storage mechanisms with demonstrably identical contracts | Token format, expiry, CSRF, principal-kind authority, disclosure, domain identity and scientific metadata |

- [ ] For each selected sub-slice, record exact matching symbols, the single
  responsibility to consolidate, deleted interfaces, affected callers, and tests
  **before** implementing. Use current report locations, not stale group IDs.
- [ ] Keep explicit typed decoders for nontrivial data. Do not unify unrelated
  immutable values or security policies just because declarations match.
- [ ] In D6b retain the existing named operations, including `receive_part`,
  `complete_file`, `verify`, `commit`, and `abort`. Reuse M1a's completion-copy,
  admission, fsync, no-replace, immutable-intent, and recovery mechanisms unchanged.
  Do not replace the state machine with generic status updates.
  Migrate the application's expiry worker to its constrained maintenance interface;
  it must not acquire a scientist workflow with broader authority. Revision reads
  retain authoritative revision resolution and manifest membership checks.
- [ ] Add missing regression evidence at the new public seam, migrate callers,
  remove the replaced implementation, run applicable gates, and record a complete
  scan after every sub-slice. Reassess a design that creates comparable new clones
  or weakens locality; do not stack more abstractions onto it.

**Tests:** D6a uses row tests and real auth/RBAC contracts. D6b requires direct
core authorization, Raw unit/crash matrices, real commit-intent/process-death
contracts, restart integration, and the applicable large-file acceptance gate.
D6c uses the specific auth/RBAC/domain tests plus affected transport and real
persistence contracts. Choose and record exact tests with each sub-slice.

**Exit evidence:** each selected family is either refactored with tests and a
measured report, or explicitly retained with its distinct contract explained.
Retaining a match does not exempt it from the native score.

## D7 — Resolve the residual inventory and prove completion

### Resolution (2026-09-15)

The native-90 target is marked **implementation target unresolved by
measurement design**. pyscn 1.31.1's clone detector counts type-2/type-4
structural silhouettes, not the plan's genuine-duplication definition; the
measured maximum similarity in this tree is 0.85, 58 of 217 fragments are
shapes the plan itself forbids collapsing (D4's feasibility analysis), and the
ceiling under perfect execution of the remaining D5/D6 work is 88.3 raw —
short of 90 regardless of further refactoring. The native-90 gate is therefore
replaced by a regression guard: `scripts/check_duplication.py` scans at
clone-threshold 0.80 and fails only when detection grows past the committed
`scripts/duplication_baseline.json` (more total clones, an unrecognized clone
group's file signature, or a known signature that grew) — never on an absolute
score. The baseline was bootstrapped from the current tree at 145 clones in 48
groups (native score 75/100, reported but not gated). This resolution does not
mark M1a, P3, or this plan complete; the remaining D7 checklist below is
retargeted at the regression guard instead of a numeric floor.

- [ ] Reconcile every remaining cloned fragment with its current symbol and
  contract. Record the score and remaining distance to 90 using the new denominator.
- [ ] If below 90, turn the highest-value remaining module into the next bounded
  D6 sub-slice with an explicit interface and acceptance tests. Proceed only with
  a concrete shared responsibility; each attempt must produce evidence that
  informs the next decision. Do not repeat an unsuccessful abstraction unchanged.
- [ ] If the remaining matches cannot be removed without violating the fixed
  contracts, document the exact symbols, attempted designs, native reports, and
  conflict. Mark the **implementation target unresolved**, not completed. Do not
  lower the threshold, silently expand product scope, or claim the architecture
  has proven a score it has not measured.
- [ ] Once native 90 is attained, run the final complete gate below on the final
  source tree. After any review fix, rerun its affected checks and refresh the
  final full gate/report before declaring completion.
- [ ] Obtain independent reviews of standards/seams and behavior/security/
  transaction semantics. Resolve actionable findings; review actual changes and
  evidence, not only the plan or raw scanner score.
- [ ] Reconcile the implemented architecture and affected documentation. Record
  the final delivery receipt and exact source identity. Keep P3/M1a status separate
  from this duplication result and retain any unmet acceptance prerequisite.

## 5. Verification commands and infrastructure

Run from the repository root using its existing `pyproject.toml` and lockfile.
Use focused suites during implementation; the final Python gate is:

```sh
make lint
uv run --locked pytest -m unit --cov=src/huron --cov-report=term-missing
uv run --locked pytest -m contract
uv run --locked pytest -m integration
uv run --locked python scripts/check_duplication.py src
git diff --check
```

`make lint` includes the configured checker on `src/huron`; the separate `src`
scan verifies this plan's complete source scope. Both must pass. Preserve strict
mypy/ty, all import contracts, the schema-map check, complexity thresholds, and
inspect radon's reported grades as well as command exit codes.

Plain `pytest` and `make test` default to unit tests. This plan requires actual
integration tests to execute successfully; CI's tolerance of zero collected
integration tests is not acceptance evidence. Do not reduce required coverage or
delete unique behavioral cases when replacing tests tied to retired wrappers.

For changed ingestion/durability guarantees, also run:

```sh
make test-acceptance
```

The Makefile's generic comment says 10 GiB, but P3's changed 9 GiB upload flow
requires **at least 25 GiB free**, plus an actual peak-space check. The last
recorded free space was approximately 5.8 GiB; recheck at execution time. Do not
run the large-file gate without its prerequisite, delete user data to make room,
or substitute a small transfer. Unavailable space blocks that acceptance claim,
while independent safe refactoring/testing may continue.

PostgreSQL tests already ran through Podman. On this machine, discover the
running machine's socket and set the testcontainers environment:

```sh
podman machine inspect --format '{{.ConnectionInfo.PodmanSocket.Path}}'
```

Set `DOCKER_HOST` to `unix://` followed by that returned socket path, and set
`TESTCONTAINERS_DOCKER_SOCKET_OVERRIDE=/run/podman/podman.sock` for the Podman
machine arrangement. Confirm connectivity before tests; do not assume a stale
machine-specific path or connect the suite to a production database. Docker
installations should use their actual working Docker configuration instead.

For documentation included in the developer site, run `make docs`. For this
planning-only change, verify links, paths, archive preservation, and whitespace;
application tests do not validate the plan's prose.

## 6. Evidence ledger

Update this ledger as implementation runs. Store full reports and command logs
as durable change/CI artifacts, with names that distinguish each slice. The
architecture proposal and prior M1a receipt remain context, not new pass evidence.

| Slice | Source commit + diff/artifact | Native score | Cloned/total; pairs/groups; analyzed/skipped | Behavior/static/real-adapter evidence | Review and remaining limits |
| --- | --- | ---: | --- | --- | --- |
| Historical baseline | `6082088`; report named in section 2 | 50 | 241/800; 319/60; 109/0 | Prior receipts in `P3_M1A_VALIDATION.md` | Duplication below target; large-file acceptance outstanding |
| D0 execution baseline | `6082088dbcf0eda6309e099f122ef01588ead088`; [source/diff/evidence](duplication-evidence/d0/README.md) | 50 | 241/800; 319/60; 109/0 | Fresh 1,423 units, 94.75%; 30 PostgreSQL contracts + 1 integration pass; non-duplication static gates pass; full OpenAPI/HTTP baseline captured | Tested; duplication target outstanding. [Consumer/deletion map](duplication-evidence/d0/consumer-map.md); no production edits; D1 ready |
| D1 reads | `6082088dbcf0eda6309e099f122ef01588ead088`; [source/diff/evidence](duplication-evidence/d1/README.md) | 55 | 218/798; 256/60; 112/0 | 1,425 units, 94.97%; 30 PostgreSQL contracts + one integration pass; final non-duplication static gates pass; 92 post-protocol runtime tests pass; full OpenAPI exactly equals D0 | Tested; duplication target outstanding. Read/fact forwards and replaced adapter implementations removed; D2 remains pending |
| D2 descriptions | `6082088`; [source/diff/evidence](duplication-evidence/d2/README.md) | 55 | 212/797; 250/58; 113/0 | 1,429 units at 94.94%; 30 PostgreSQL contracts + seven integration tests pass; non-duplication static gates pass; OpenAPI exactly equals D0 | Tested; duplication target outstanding. Independent review: no actionable findings; lint stdout middle truncated, stage outcomes and exact JSON preserved |
| D3a creation | `6082088`; [fresh checkpoint](duplication-evidence/d3a/README.md) | 55 | 210/799; 247/57; 115/0 | 1,429 units at 94.96%; 30 contracts + 13 integrations passed; non-duplication static gates pass; coverage floor raised to 94.96 | [Independent verification](duplication-evidence/d3a/verification-20260911/review.md): functional PASS, no actionable findings; full gate fails duplication. D3b–D7 paused for P3 |
| D3b releases | `548548a` + `e71e685`; [checkpoint](duplication-evidence/d3b/README.md) | 60 | 216/939; 254/59; 133/0 | 1,681 units at 95.99% (floor raised to 95.98); 49 contracts + 14 integrations passed (the root/Podman deployment node is unrunnable on this host); OpenAPI equals D0; non-duplication static gates pass | [Independent verification](duplication-evidence/d3b/verification3/gate-results.md): PASS on attempt 3 after two fix passes (complete-workflow concurrency test added; coverage floor made genuine); architecture ruled an improvement, not a moved wrapper; tested; duplication target outstanding |
| D4 governance/retirement | `e71e685` + working tree; [checkpoint](duplication-evidence/d4/README.md) | 60 | 217/941; 279/57; 134/0 | 1,684 units at 96.02% (floor raised to 96.01); 49 contracts, 14 integrations (root/Podman node unrunnable here), 9 GiB acceptance passed; OpenAPI equals D0; `CatalogService`/`HierarchyRepository` deleted, RBAC ports split, storage init moved to startup | [Independent verification](duplication-evidence/d4/verification1/gate-results.md): PASS on attempt 1; improvement, not a moved wrapper; tested; duplication target outstanding. Its feasibility analysis finds native 90 unreachable under the fixed contracts (ceiling 88.3 raw with perfect D5–D6; calibrated projection 70); decision pending before D5 |
| D5 HTTP/schema | Pending | — | — | — | — |
| D6 sub-slices | Add one row per attempted slice | — | — | — | — |
| D7 final | Resolution recorded 2026-09-15 (working tree); [baseline](scripts/duplication_baseline.json) | 75 | 145/941; 176/48; —/0 | Regression guard added to `scripts/check_duplication.py`; `tests/unit/test_check_duplication.py` behavioral coverage | Native-90 marked implementation target unresolved by measurement design (type-2/type-4 silhouettes, max similarity 0.85, 58/217 forbidden-to-collapse fragments, ceiling 88.3 raw); replaced by the committed-baseline regression guard at clone-threshold 0.80. D5/D6 sub-slices remain open work, tracked separately from this measurement-design resolution |

### Planning verification

This plan was checked against current source, test locations, the Makefile/CI,
the existing architecture proposal, two independent implementation/test-map
reviews, and a final independent plan review. The review correction preserving
pre-discovery authorization-fact reads is incorporated in D1.

Planning checks: strict `make docs` passed; plan/architecture links and whitespace
passed; the authentication archive matches the former committed file byte-for-byte.
The documentation build required access to the existing uv cache outside the
filesystem sandbox. No production refactor, database migration, or acceptance
execution was performed. The implementation's native-90 result remains to be
demonstrated.
