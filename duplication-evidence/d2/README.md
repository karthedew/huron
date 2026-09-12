# D2 descriptive updates — tested; duplication target outstanding

D2 consolidates organization, project and dataset descriptive changes in the
actor-bound typed collections. All applicable D2 behavior and non-duplication gates pass. The unchanged native
90 target remains outstanding for later slices.

## Implementation and deleted interfaces

`DescriptionChange` carries the expected version, optional current slug, and
optional title/description. The collection's shared `describe` operation owns
current authorization, visible reads, the existing domain transition, no-op
handling, CAS, committed ancestry resolution, off-thread generation publication,
and commit. Concrete collection construction fixes entity, reader and capability.

`DescriptionStore`, `DescriptionTransaction` and `DescriptionWriter[T]` are
consumer-owned contracts in `core/catalog_ports.py`. Transaction writers expose
fixed typed organization/project/dataset writers. Both adapters share CAS
execution without changing transaction ownership or SQL atomicity.
`GenerationDocuments` owns canonical generation serialization and durable storage
installation for descriptions and existing creation workflows.

Removed from the final source:

- `CatalogService.patch_organization`, `patch_project`, `patch_dataset`.
- `HierarchyRepository.patch_organization`, `patch_project`, `patch_dataset`,
  `_patch_description`, `_update_description`, `_write_generation`.
- `HierarchyWriter.update_organization`, `update_project`, `update_dataset`.
- Both adapters' three transaction-writer `update_*` methods, replaced by their
  typed `describe` writers; the old memory `_stage_update` and PostgreSQL
  `_update_description` helpers are also gone.

HTTP PATCH handlers retain their named schemas, routes, headers and errors but
call `collection.describe(id, DescriptionChange(...))`. Existing unique
repository/adapter tests now exercise the authorized collections and typed CAS
writers. Their generation failure/off-thread checks use the injected storage
boundary. No compatibility forwarders remain.

## Verified behavior already available

- Focused migrated workflow/memory/HTTP feedback: 138 tests passed.
- Parent-created real PostgreSQL 16 + POSIX integration tests: six passed,
  parameterized over all three entity kinds. The contenders synchronize after
  actually reading the same version and before CAS. Exactly one succeeds,
  the loser raises `PreconditionFailed`, and only the winner writes generation 2.
  Generation-write failure leaves the independent committed row and generation 1
  unchanged; a retry from the same version succeeds. See
  `descriptions-integration.log`.
- Full OpenAPI exactly equals D0 without normalization. Parent owns the captured
  `openapi.json` and `openapi-comparison.json`.
- Independent inspection found no actionable findings. See `review.md`; this is
  an inspection receipt, separate from the pending full gates.

The six integration cases initially failed fixture setup because the dataset
insert omitted its required classification. The parent corrected the fixture
without changing production behavior or weakening assertions; all six then passed.

Additional direct-core coverage proves valid no-op requests open no transaction,
stale no-op rejection, slug-before-version error ordering, null retention, empty
string replacement, independent authorization beyond discovery, and hidden target
behavior after revocation. The final unit gate must establish these results on the
complete tree.

## Final gate results available

| Gate | Actual outcome | Evidence |
| --- | --- | --- |
| `make lint` | All non-duplication gates pass; exit 2 solely for native 55 below 90 | `lint.log`, exact `duplication-src-huron.json` |
| Unit coverage | 1,429 passed; 94.94% (5,551 statements, 281 missed), above 94.71% | Complete `unit.log` |
| Source-wide native scan | 55/100; 212/797 fragments, 250 pairs, 58 groups; 113 files, zero skipped | `duplication-src.log`, exact `duplication-src.json` |
| Inventory reconciliation | All 113 actual source paths exactly match report request paths | `source-inventory.txt`, `source-coverage.json` |
| Full contract/integration suite | 37 passed: 30 contract + seven integration (including six description cases), 95.27s | Complete `real-adapters.log` |

The captured lint transcript is truncated in its middle informational complexipy
and clone listings; it is **not a complete stdout transcript**. The retained
output records the passing stage sequence, all nine import contracts, empty
radon findings, quality-check success and final native duplication failure.
Exact native JSON reports are preserved independently. Root executed and observed
the gate; no missing stdout has been reconstructed or represented as complete.

The final source identity is HEAD plus cumulative `source-working.diff`, including
new modules/tests, with `tree-hashes.json` and exact D1-to-D2 changed-file hashes in
`changes-since-d1.json`. All 212 clone entries are in `clone-inventory.md`.
`clone-delta.md` compares D1 to D2: nine old matched fragments removed from their
former symbols and three new matches, a net reduction of six. The rounded native
score remains 55; the unchanged final target of 90 remains outstanding.

## Handoff and limits

D2 is tested with independent review finding no actionable defects.
`git diff --check` passed after evidence and ledger updates. No ingestion or
filesystem durability guarantee was changed; D2 proves catalog mutation rollback
and publication ordering, so the separate large-file P3 acceptance gap remains
unchanged. No documentation-site page changed; `make docs` was not applicable.
D3a may proceed under the plan's intermediate duplication exception. D3b and
later slices remain pending; this is not completion of the native-90 objective.
