# D3b baseline — clone entries touching release code

Source: `duplication-src-native.json` (native scan, `analyze_20260913_152121.json`),
before any D3b edits. HEAD `548548aec67d39c95e291daa98b3258d5e37e851`. Native
score 60/100; 213/938 cloned fragments; 253 pairs; 58 groups; 132 files
analyzed, 0 skipped. Group/pair ids below are report-local, per plan §2.

## Fragments naming release symbols or the release-adjacent HTTP/RBAC modules

| id | file | lines | symbol |
| ---: | --- | --- | --- |
| 98 | `applications/api/routes/v1/endpoints/datasets.py` | 248-300 | `create_release` handler |
| 99 | `applications/api/routes/v1/endpoints/datasets.py` | 310-335 | `list_releases` handler |
| 100 | `applications/api/routes/v1/endpoints/datasets.py` | 341-360 | `resolve_release` handler |
| 155 | `applications/api/routes/v1/schema/datasets.py` | 90-102 | `ReleaseView` |
| 429 | `core/ports.py` | 577-594 | `HierarchyStore.releases` |
| 685 | `pkg/metastore/hierarchy.py` | 1051-1094 | `_PostgresTransactionWriter.insert_release` |
| 666 | `pkg/metastore/hierarchy.py` | 618-643 | `InMemoryHierarchyStore.revision_ref` |
| 693 | `pkg/metastore/hierarchy.py` | 1239-1266 | `PostgresHierarchyStore.revision_ref` |

`create_release`/`release`/`releases` on `core/catalog.py` and `core/_catalog.py`
(the two internal implementations D3b moves) do not appear as individual
`clone.clones` fragments at the current size/similarity thresholds; their
duplication is architectural (two near-identical forwarding layers), not a
pyscn-detected clone pair, so removing them changes ownership without
necessarily changing the native count.

## Pairs the above fragments participate in

`releases` (429) pairs only with `catalog_ports.py:31-53` (`CollectionReader.browse`,
id 355, similarity 0.804) — a generic-shape match against the unrelated typed
collection reader, not a release-to-release duplication. `revision_ref`
(666, 693) each pair with generic single-argument point-read methods in
`pkg/metastore/rbac.py`, `pkg/metastore/ingest.py`, and each other, and with
`hierarchy.py`'s own `revision`/`get` methods — cross-adapter read-shape
matches that are D6a/D6b territory (`pkg/metastore/rbac.py`, `ingest.py` are
outside this slice's file list) and are not expected to change from moving
release ownership alone. `insert_release` (685) has no paired fragment in this
report at the id-based pairing but sits in the same clone group as the other
`insert_*` writer methods in the Postgres transaction writer (D4/D6a scope,
since consolidating inserts crosses into non-release writer methods).

None of these fragments are removable within D3b's file list without
violating "share read mechanics only where key/cursor semantics fit" (the
architecture doc's explicit instruction that releases keep their own key/
cursor) or reaching into `pkg/metastore/rbac.py` / `ingest.py`, which are out
of scope for this slice.
