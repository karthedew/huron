# D2 clone delta

Compared by enclosing file/symbol and fragment multiplicity, because ranges and group IDs move. The complete old and new ranges remain in their respective inventories.

Native score: 55 → 55; fragments: 218/798 → 212/797; pairs: 256 → 250; groups: 60 → 58.

9 previous cloned fragments cease to appear at their former symbol; 3 fragments newly appear at a symbol. Their net change is -6.

## Removed from clone inventory

| File | Symbol | Fragment count |
| --- | --- | ---: |
| `src/huron/core/_catalog.py` | `HierarchyRepository.patch_dataset` | 1 |
| `src/huron/core/_catalog.py` | `HierarchyRepository.patch_organization` | 1 |
| `src/huron/core/_catalog.py` | `HierarchyRepository.patch_project` | 1 |
| `src/huron/core/catalog.py` | `CatalogService.patch_dataset` | 1 |
| `src/huron/core/catalog.py` | `CatalogService.patch_organization` | 1 |
| `src/huron/core/catalog.py` | `CatalogService.patch_project` | 1 |
| `src/huron/pkg/metastore/hierarchy.py` | `_TransactionWriter.update_dataset` | 1 |
| `src/huron/pkg/metastore/hierarchy.py` | `_TransactionWriter.update_organization` | 1 |
| `src/huron/pkg/metastore/hierarchy.py` | `_TransactionWriter.update_project` | 1 |

## Newly cloned inventory

| File | Symbol | Fragment count |
| --- | --- | ---: |
| `src/huron/core/catalog_collections.py` | `_Collection.describe` | 1 |
| `src/huron/pkg/metastore/hierarchy.py` | `_MemoryDescriptionWriter.describe` | 1 |
| `src/huron/pkg/metastore/ingest.py` | `InMemoryIngestWriter.update_ingest_session` | 1 |

Remaining matches include creation, releases, governance, HTTP model/endpoint families, and unrelated Raw/auth adapter behavior. D3 and later slices own those responsibilities. New typed writer/protocol/construction matches remain visible to the unchanged scanner; they are not suppressed.
