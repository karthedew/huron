# D3b immutable releases — tested; duplication target outstanding

Implemented against source commit `548548aec67d39c95e291daa98b3258d5e37e851`
(the tip carrying the completed M1b authority work). No unrelated work was
reverted or staged; `.opencode/*`, `design/index.html`, `.pyscn/`, `minihuron/`,
`scripts/main.py`, and `tests/unit/test_books_upload_script.py` remain exactly
as found (`git-status.txt`, `baseline/initial-status.txt`).

## Fix pass 1 (response to verification 1's FAIL)

Verification 1 (`verification1/`, receipts untouched) confirmed the gate,
invariants, clone attribution and architecture ruling, and returned FAIL on
four points, all resolved here:

1. **Concurrent workflow coverage.** Added
   `tests/integration/test_catalog_releases.py`, exercising two concurrent
   `Releases.create_release` calls over real PostgreSQL and the real
   filesystem; see "Tests" below. The "Invariants preserved" section's
   claim that `scenario_4_idempotency`/`scenario_5_revisions` were
   complete-workflow concurrency evidence is corrected there.
2. **Orphaned `data_root`.** Deleted; see "Deleted interfaces".
3. **Clone attribution.** Corrected in "Native duplication before/after"
   below: baseline group 41 has three members, not four, and
   `catalog_creation` was never one of them.
4. **Alias collision.** Renamed `Release` to `ReleaseWorkflow`; see
   "What moved".

## What moved

`create_release`, `release` and `releases` are gone from `core/catalog.py`
(`CatalogService`) and `core/_catalog.py` (`HierarchyRepository`). A new
`core/releases.py` module owns them as `Releases`, an actor-bound workflow
with the same shape as D3a's `CatalogCreation`: it takes an `AccessPolicy`,
a focused `ReleaseStore` port and the raw store, and recomputes authorization
on every call. `core/catalog_ports.py` gained the two release ports the
architecture doc calls for — `ReleaseTransaction` (mutation: `insert_release`,
inherited from `RetryTransaction`) and `ReleaseStore` (read: `release`,
`releases`, `revision_ref`, plus the transaction that opens a
`ReleaseTransaction`) — following exactly how `CreationTransaction`/
`CreationStore` were shaped for creation. `core/ports.py` no longer declares
`insert_release`, `release`, `releases` or `revision_ref` itself; `HierarchyWriter`
and `HierarchyStore` compose `ReleaseTransaction`/`ReleaseStore` as additional
Protocol bases (the same composition `HierarchyStore(HierarchyFacts, Protocol)`
already used for read facts), so the two hierarchy adapters in
`pkg/metastore/hierarchy.py` needed no code change at all: their existing
`release`/`releases`/`revision_ref`/`insert_release` methods satisfy the new
focused ports structurally, exactly as the architecture doc's "memory
implements the same observable contract using its own data structures, not
SQL inheritance" calls for. `ty` and `mypy` both confirm the composition
type-checks with zero errors.

HTTP wiring: `applications/api/dependencies.py` gained `catalog_releases`/
`ReleaseWorkflow` (an `Annotated[Releases, Depends(...)]` alias, named to
match the existing `Catalog`/`Creation`/`Identity`/`Revisions` short-alias
convention). The alias was originally named `Release`, which collided with
the domain record of the same name already imported in the endpoint module
and forced an `import Release as ReleaseCatalog` there; fix pass 1 renamed
the alias itself to `ReleaseWorkflow` (a small, contained change — the
alias is defined and consumed nowhere but these two files) so the endpoint
module imports and uses `ReleaseWorkflow` directly, with no import alias
needed. The three dataset release handlers in
`applications/api/routes/v1/endpoints/datasets.py` (`create_release`,
`list_releases`, `resolve_release`) now depend on `ReleaseWorkflow` instead
of the general `Catalog` alias; `create_release` no
longer passes a caller-supplied `created_by` (it was already silently
overwritten by the authenticated actor's subject one layer up, in
`CatalogService.create_release`, before this slice — that derivation now
happens directly inside `Releases.create_release`). No route path, method,
schema, status code, header or streaming behavior changed.

## Invariants preserved

Dataset discovery, then project/organization ancestry reads at unrestricted
visibility, then revision resolution, then the idempotency-claim replay
check, then insert, then the write-once tag file, then the replay receipt —
the exact transaction order and exact exception mapping
(`ResourceNotFound`/`TagExists`/`IdempotencyKeyReused`/`Forbidden`) carried
over verbatim from `_catalog.HierarchyRepository.create_release` into
`Releases.create_release`; only the authorization check
(`release.create` at `ScopeType.DATASET`) and claim-ownership check, both
previously performed one layer up in `CatalogService`, now run inside the
same method, in the same order relative to `validate_tag`. Tag write and
receipt retain their transaction order (insert → write-once tag file →
remember, all before commit). `write_tag_once`'s `FileExistsError` →
`TagExists` translation is unchanged. Releases keep their own `tag`-ordered
cursor and gained no descriptive-update operation, per the architecture
doc's "releases retain their own key/cursor and do not gain a
descriptive-update operation." Sequential duplicate-claim and conflicting-tag
behavior is proven through the complete workflow (`releases_for(...)` +
`Releases.create_release`), not only the hierarchy store's `insert_release`
primitive, in the unit suite's real in-memory adapter
(`tests/unit/test_repository_hierarchy.py`'s `create_release` replay,
duplicate-tag, raw-store-collision and digest-reuse scenarios). Real
*concurrent* retry and conflict through the complete workflow, over actual
PostgreSQL and the actual filesystem, is proven separately by
`tests/integration/test_catalog_releases.py::test_concurrent_release_creation_replays_one_identity_and_refuses_conflicting_claims`,
added in this fix pass: it mirrors `test_catalog_creation.py`'s `_compete`
pattern — two `asyncio.gather`ed `Releases.create_release` calls,
synchronized on `writer.claim`, share one identity, write the tag file
exactly once (asserted off the event loop) and leave exactly one `releases`
row; the same key with a different fingerprint then raises
`IdempotencyKeyReused`; and two concurrent claims racing under distinct
keys to create a second, previously unused tag yield exactly one
`TagExists`. `tests/hierarchy_contract.py`'s `scenario_4_idempotency` and
`scenario_5_revisions` are *not* this evidence: an earlier revision of this
README cited them as complete-workflow concurrency coverage, which
overstated what they do. Both call `writer.claim`/`insert_release`/
`revision_ref` directly against `HierarchyStore`, never through
`Releases.create_release`; `scenario_4_idempotency`'s one concurrent race
(`asyncio.gather` of two claim attempts) is over an *organization* claim,
not a release, and `scenario_5_revisions` has no concurrency at all — it
sequentially proves `revision_ref` resolution and the revision-must-exist
check `insert_release` enforces. They remain valid evidence for the
`HierarchyStore` port's own sequential contract (driven by both
`tests/unit/test_hierarchy_store_memory.py` and
`tests/contract/test_hierarchy_store.py`), not for the `Releases` workflow's
concurrent behavior.

## Deleted interfaces

- `core/catalog.py`: `CatalogService.create_release`, `.release`, `.releases`.
- `core/_catalog.py`: `HierarchyRepository.create_release`, `.release`,
  `.releases`.
- `core/ports.py`: `HierarchyWriter.insert_release`; `HierarchyStore.release`,
  `.revision_ref`, `.releases` (all three now live once, in
  `catalog_ports.ReleaseStore`/`ReleaseTransaction`, and reach `HierarchyStore`/
  `HierarchyWriter` only through composition).
- `core/_catalog.py`: `HierarchyRepository.data_root` (fix pass 1). Its sole
  production caller was the deleted `create_release`; once that moved to
  `Releases`, which builds its own `self._root = PurePosixPath(storage.root)`
  from the raw store it is constructed with, the property survived only
  because six tests in `tests/unit/test_repository_hierarchy.py` (the two
  `patch_dataset` no-op tests, both `create_release` raw-store/tag-document
  tests, and the `patch_organization`/`patch_project` no-op tests) still
  called it to build expected filesystem paths. Those ten call sites now
  call a same-file test helper, `_data_root(repository) ->
  PurePosixPath(repository.raw_store.root)`, instead. D4's storage-
  initialization move (`HierarchyRepository.__init__` calling
  `raw_store.initialize()`) does not need `data_root`: that move only needs
  `raw_store.initialize()` to run from application startup, not a
  path-shaped view of `raw_store.root`.

No forwarding shims were left behind; every caller (the three HTTP handlers,
the unit-test call sites) moved to `Releases` in this slice.

## Tests

- `tests/unit/test_repository_hierarchy.py`: the eight `create_release`
  scenarios (replay, duplicate tag, raw-store tag collision, tag-document
  shape, title-none-vs-empty-string digest, digest-reuse, invisible dataset,
  unregistered revision) now drive `Releases` through a new
  `tests/catalog_release_support.py::releases_for` helper (mirroring the
  existing `catalog_creation_support.py::creation_for`) instead of calling
  `HierarchyRepository.create_release` with a raw `visibility`/`created_by`
  pair. `test_create_release_replay_with_a_different_created_by_is_a_reuse`
  is renamed `..._with_a_different_digest_is_a_reuse`: `created_by` is no
  longer a caller-supplied field once it is derived from the authenticated
  actor, so the test now documents what it actually exercises — two claims
  sharing a key whose fingerprints differ elsewhere still conflict. The
  invisible-dataset case now goes through `releases_for(repository,
  visible=False)`, so discovery is enforced by `Releases`' own
  `AccessPolicy.require` rather than by a bare `Visibility()` argument — this
  additionally proves the "hidden targets are 404 before permission errors"
  invariant now holds at the new interface (`AccessPolicy.require` resolves
  scope, which raises `ResourceNotFound` for an undiscoverable dataset,
  exactly the same ordering already proven for `CatalogCreation.create_dataset`
  under an invisible project).
- `tests/unit/test_core_workflows.py::test_catalog_does_not_accept_a_foreign_claim`
  now builds a `Releases` instance from the fixture's `access`/`repository`
  and calls `releases.create_release(...)` (no `created_by`) instead of
  `catalog.create_release(...)`.
- No test's *behavior* was removed; every scenario's assertion is preserved
  under the new call surface. `tests/hierarchy_contract.py`,
  `tests/unit/test_hierarchy_store_memory.py`,
  `tests/contract/test_hierarchy_store.py`, `tests/contract/test_catalog_store.py`,
  `tests/unit/test_api_catalog_hierarchy.py`, `tests/unit/test_api_visibility.py`
  and `tests/unit/test_execution_model.py` needed no changes: they exercise
  the hierarchy adapters directly or the HTTP surface, neither of which the
  interface move touches.
- New in fix pass 1: `tests/integration/test_catalog_releases.py`, mirroring
  `tests/integration/test_catalog_creation.py`'s `_compete` pattern over real
  PostgreSQL (testcontainers) and the real filesystem. Its one test,
  `test_concurrent_release_creation_replays_one_identity_and_refuses_conflicting_claims`,
  seeds a committed dataset revision directly through the store's writer,
  then: (1) `asyncio.gather`s two `Releases.create_release` calls sharing one
  claim, synchronized on `writer.claim` via a barrier so both transactions
  are genuinely concurrent, and asserts the same identity comes back twice,
  exactly one `releases` row exists for that tag, `write_tag_once` runs
  exactly once and off the event loop (the same `asyncio.get_running_loop()`
  idiom `test_the_generation_document_write_executes_off_the_event_loop_thread`
  at `tests/unit/test_repository_hierarchy.py:208` uses), and the tag file on
  disk holds exactly the written payload; (2) replays the same key with a
  changed title and asserts `IdempotencyKeyReused`; (3) `asyncio.gather`s two
  more `Releases.create_release` calls under distinct claims racing to
  create a second, previously unused tag, synchronized the same way, and
  asserts exactly one succeeds and the other raises `TagExists`, with
  exactly one row landing for that tag. `--co -m integration` now collects
  15 tests (was 14); this test is not parametrized, so it adds exactly one.
  An in-memory-only variant would not exercise the real transaction/claim
  race this invariant depends on, so none was substituted.

## Gate results

| Command | Result | Evidence |
| --- | --- | --- |
| `uv run ruff check src` / `ruff format --check src` | Clean | fixed two ruff findings introduced mid-edit (unsorted import in `_catalog.py`, unused `Visibility` in `ports.py`), both resolved before the final run |
| `uv run ty check` | `All checks passed!` | confirms `HierarchyStore`/`HierarchyWriter` structurally satisfy `ReleaseStore`/`ReleaseTransaction` through composition, with no new suppressions |
| `uv run mypy` | `Success: no issues found in 133 source files` | same |
| `uv run lint-imports` | `Contracts: 9 kept, 0 broken` | `core uses ports rather than concrete infrastructure` and `API endpoints cannot call internal workflow implementations` both hold unchanged |
| `uv run --locked pytest --cov=src/huron --cov-report=term-missing` | 1,677 passed, 64 deselected; 95.93% ≥ 95.92% ratchet floor. Per the ratchet rule (never lower, raise when a run exceeds it by two decimals), `fail_under` was raised 95.92 → 95.93 in `pyproject.toml` and the suite rerun to confirm it still passes exactly at the new floor | `unit.log`, `coverage.json`, `coverage-ratchet.log`; every touched production file (`core/_catalog.py`, `core/catalog.py`, `core/ports.py`, `core/catalog_ports.py`, `core/releases.py`) at 100% line coverage |
| `uv run radon cc src --min C` / `mi src --min B` | Empty (pass) | `lint.log` |
| `uv run complexipy src --max-complexity-allowed 15` | All functions within the allowed complexity | `lint.log` |
| `uv run --locked pyscn check src` | `✅ Code quality check passed` | `lint.log` |
| `make lint` | Exit 2, solely at the duplication checker; every preceding stage (ruff, format, pydoclint, mypy, ty, lint-imports, schema-map, radon, complexipy, pyscn check) passed | `lint.log`, `lint.exit` |
| `uv run --locked python scripts/check_duplication.py src` | Exit 1; native 60/100; 216/939 fragments; 254 pairs; 59 groups; 133 files analyzed, 0 skipped | `duplication-src.log`, `duplication-src-native.json` |
| `uv run --locked pytest -m contract` | 49 passed, 1692 deselected | `contract.log` |
| `uv run --locked pytest -m integration -s` (full) | 13 passed, 1 failed, 1727 deselected — the known `test_actual_legacy_http_request_is_terminated_and_cannot_restart`, failing on `sudo: a password is required` exactly as documented | `integration-full.log` |
| Same, `--deselect` that node | 13 passed, 1728 deselected, exit 0 | `integration-deselected.log` |
| `git diff --check` | Exit 0 | `git-diff-check.log` |
| OpenAPI comparison against D0 | Byte-for-byte identical (`md5sum` equal, `544e9bf5f1a010e89bacbec15a66b5df`), and a semantic deep-diff (normalizing only `required` array order, per plan) independently confirms exact equality | `openapi.json` (fresh capture from `create_app` with the same dev-header/memory-store settings as D0's own capture convention: `json.dumps(doc, indent=2, sort_keys=True)`), compared against `duplication-evidence/d0/openapi.json`; both release paths (`/api/v1/datasets/{dataset_id}/releases`, `.../releases/{tag}`) are present and unchanged |

The 9 GiB acceptance gate was not run: this slice touches no ingestion or
durability code (Raw's `write_tag_once`/`create_staging` etc. are unchanged;
only the caller that reaches `write_tag_once` moved).

## Native duplication before/after

| | Score | Cloned/total | Pairs | Groups | Files analyzed/skipped |
| --- | ---: | --- | ---: | ---: | --- |
| Before (this slice's baseline) | 60 | 213/938 | 253 | 58 | 132/0 |
| After | 60 | 216/939 | 254 | 59 | 133/0 |

The rounded score is unchanged, as D3a's was; `baseline/clone-inventory.md`
records the release-specific fragments/pairs identified before editing.
Comparing native JSON hashes directly (not just report-local ids, which are
not stable across runs):

**Removed** (exact hash no longer present): the three release HTTP handlers'
old fragment content (`create_release`, `list_releases`, `resolve_release` in
`endpoints/datasets.py`) — their *content* changed (dropped `created_by=`
from the `create_release` call; `Repository` → `ReleaseCatalog` in all three
signatures), so their old hashes vanish even though the handlers are still
clones of their organization/project siblings by shape (same fragments,
new hashes, listed below).

**Added**:
- The same three handlers under their new hashes (same clone relationships
  to `organizations.py`/`projects.py`'s equivalent CRUD handlers as before —
  this is the pre-existing, out-of-scope "HTTP handler shape" duplication
  the D5 HTTP/schema slice is meant to address, not something this slice's
  file list authorizes touching).
- `core/releases.py:34-47` (`Releases.__init__`), which clones with
  `core/_ingest.py:249-263` at 0.78 similarity: both bind an actor/access
  object, a focused store port and the raw storage root in the same
  four-line shape every workflow constructor in this codebase already uses
  (`CatalogCreation.__init__`, `_Collection.__init__`, `IngestService`'s own
  constructor). This is the same inherent, accepted constructor-boilerplate
  echo the architecture already tolerates elsewhere; unifying it would mean
  either forcing `Releases` to inherit from an unrelated ingest class or
  introducing a generic constructor-injection base with no other purpose,
  both explicitly against the plan's "do not restructure code merely to
  dodge clone detection" and "do not add a hierarchy of classes merely to
  reduce scanner matches."
- `applications/api/dependencies.py:62-76` (`catalog_releases`), which joins
  the pre-existing three-member structural clone group of DI factory
  functions in that file — baseline group 41, similarity 0.775:
  `catalog_service` (`dependencies.py:18`), `raw_ingestion_service`
  (`dependencies.py:61`), `revision_service` (`dependencies.py:104`) —
  as a fourth member. `catalog_creation` and `identity_service` construct
  their workflow object with extra positional arguments and are not part of
  this group at baseline or after. Every DI factory in this file has the
  same shape by design (build an `AccessPolicy` from `runtime`/`actor`,
  construct the workflow object); this is the established pattern, not a
  new abstraction opportunity, and consolidating it would require exactly
  the generic `execute(kind, action, **fields)`-style dispatcher the
  architecture doc rules out.

`revision_ref`, `release`, `releases` at the adapter level
(`pkg/metastore/hierarchy.py`) and `insert_release` are byte-identical to
baseline (same file, same lines, same hash) — `pkg/metastore/hierarchy.py`
was not touched, and the plan explicitly does not ask this slice to
consolidate memory/PostgreSQL adapter internals or to reach into
`pkg/metastore/rbac.py`/`ingest.py`, which is where most of `revision_ref`'s
and `insert_release`'s remaining pairs point (D6a/D6b territory). The
`releases`-vs-`browse` pair (moved from `core/ports.py:577` to
`core/catalog_ports.py:344`, still 0.804 similarity against
`CollectionReader.browse`) is unchanged in kind: it is a generic-shape match
against an unrelated typed collection reader, not a release self-duplication,
and the architecture doc explicitly says releases keep their own key/cursor
rather than reusing `CollectionReader`.

## Fix pass 1 — rerun gate and native scan

The complete validation gate and native scan were rerun on the final,
fixed tree; full command-by-command results are in `fix1/gate-results.md`
and `fix1/clone-inventory-diff.md` (`fix1/` receipts, verification 1's own
`verification1/` receipts left untouched). Summary:

| | Score | Cloned/total | Pairs | Groups | Files analyzed/skipped |
| --- | ---: | --- | ---: | ---: | --- |
| Before (this slice's baseline) | 60 | 213/938 | 253 | 58 | 132/0 |
| Attempt 1 / verification 1 | 60 | 216/939 | 254 | 59 | 133/0 |
| Fix pass 1 (final) | 60 | 216/939 | 254 | 59 | 133/0 |

Deleting `HierarchyRepository.data_root` (fix pass 1, item 2) changed
nothing here: the property was never itself part of a clone fragment, so
removing it moved no fragment/pair/group count. The alias rename
(`Release` → `ReleaseWorkflow`, item 4) shifted the three `datasets.py`
release-handler fragments up by one line each (ruff's import sort merged
two single-symbol `from ... import` lines once the alias no longer needed
`as ReleaseCatalog`), producing three new hashes for otherwise-identical
content — `fix1/clone-inventory-diff.md` records the exact before/after
hashes. Every other figure, and every group membership claim in this
section, is unchanged from attempt 1: `applications/api/dependencies.py`'s
`catalog_releases` still joins the same corrected three-member baseline
group 41 as its fourth member (`catalog_service`, `raw_ingestion_service`,
`revision_service`), and `core/releases.py`'s constructor still pairs only
with `core/_ingest.py`'s.

The full gate passed at fix pass 1 with the same shape as attempt 1: every
command exits 0 except `check_duplication.py`/`make lint`'s last stage
(native score below 90, unchanged and expected at this point in the plan)
and the documented Podman/root integration node. The unit suite's raw
coverage ratio moved from 95.93284% to 95.9298% (both round to the
`precision = 2` floor of 95.93, so the gate still passes; see
`fix1/gate-results.md`'s "Coverage ratchet note" for why deleting
`data_root`, a fully-covered property, can lower a *ratio* while nothing
regresses). `fail_under` stays at 95.93 — not lowered, and not raised again
since this run does not exceed it by two decimals. `--co -m integration`
now collects 15 (was 14), `contract` still 49, and the OpenAPI capture is
still byte-identical to D0's (`fix1/openapi.json`, same md5).

## Risks and limitations

- The native score did not cross 90 and did not move from 60; this slice's
  job per plan §4 is the architectural relocation, and D3a set the precedent
  that a correct relocation slice can leave the rounded score unchanged.
- No invariant required a contract change; nothing was deferred or left
  half-migrated. `core/_catalog.py` (`HierarchyRepository`) now holds only
  governance (RBAC) operations and Raw storage initialization, exactly as
  its updated module docstring states.
- `pkg/metastore/hierarchy.py`'s own coverage under the unit-only run is
  74.28% (Postgres-only code paths, exercised by the contract suite instead);
  this file was not touched by D3b and its coverage is unchanged from before
  this slice, consistent with every prior slice's evidence in this ledger.
- D4 (governance/retirement) and D6a (metastore read-mechanics consolidation)
  remain the owners of the RBAC- and cross-adapter-read clones this slice's
  scan still shows; none of them were touched here.
- `tests/integration/test_catalog_releases.py`'s concurrency proof depends
  on `asyncio.Barrier`-synchronized `writer.claim` calls to force two real
  Postgres transactions to overlap deterministically, the same technique
  `test_catalog_creation.py` already relies on; it needs Docker (via
  testcontainers) to run and is skipped wherever the contract/integration
  suites already are. It does not attempt to prove a specific interleaving
  beyond "both transactions are open when they stake their claim" — the
  database's own transaction isolation, not the test, is what forces exactly
  one winner at each of the two race points it exercises.
