# D1 clone delta

Compared by enclosing file/symbol and fragment multiplicity, because ranges and group IDs move. The complete old and new ranges remain in their respective inventories.

Native score: 50 → 55; fragments: 241/800 → 218/798; pairs: 319 → 256; groups: 60 → 60.

32 previous cloned fragments cease to appear at their former symbol; 9 fragments newly appear at a symbol. Their net change is -23.

## Removed from clone inventory

| File | Symbol | Fragment count |
| --- | --- | ---: |
| `src/huron/core/_catalog.py` | `HierarchyRepository.bindings_for` | 1 |
| `src/huron/core/_catalog.py` | `HierarchyRepository.dataset_parents` | 1 |
| `src/huron/core/_catalog.py` | `HierarchyRepository.datasets` | 1 |
| `src/huron/core/_catalog.py` | `HierarchyRepository.organizations` | 1 |
| `src/huron/core/_catalog.py` | `HierarchyRepository.projects` | 1 |
| `src/huron/core/_catalog.py` | `HierarchyRepository.releases` | 1 |
| `src/huron/core/access.py` | `AccessPolicy.__init__` | 1 |
| `src/huron/core/catalog.py` | `CatalogService.dataset` | 1 |
| `src/huron/core/catalog.py` | `CatalogService.datasets` | 1 |
| `src/huron/core/catalog.py` | `CatalogService.organization` | 1 |
| `src/huron/core/catalog.py` | `CatalogService.organizations` | 1 |
| `src/huron/core/catalog.py` | `CatalogService.project` | 1 |
| `src/huron/core/catalog.py` | `CatalogService.projects` | 1 |
| `src/huron/core/catalog.py` | `CatalogService.release` | 1 |
| `src/huron/core/catalog.py` | `CatalogService.releases` | 1 |
| `src/huron/core/ports.py` | `HierarchyStore.datasets` | 1 |
| `src/huron/core/ports.py` | `HierarchyStore.organizations` | 1 |
| `src/huron/core/ports.py` | `HierarchyStore.projects` | 1 |
| `src/huron/pkg/metastore/hierarchy.py` | `InMemoryHierarchyStore.dataset` | 1 |
| `src/huron/pkg/metastore/hierarchy.py` | `InMemoryHierarchyStore.datasets` | 1 |
| `src/huron/pkg/metastore/hierarchy.py` | `InMemoryHierarchyStore.organization` | 1 |
| `src/huron/pkg/metastore/hierarchy.py` | `InMemoryHierarchyStore.organizations` | 1 |
| `src/huron/pkg/metastore/hierarchy.py` | `InMemoryHierarchyStore.project` | 1 |
| `src/huron/pkg/metastore/hierarchy.py` | `InMemoryHierarchyStore.projects` | 1 |
| `src/huron/pkg/metastore/hierarchy.py` | `InMemoryHierarchyStore.releases` | 1 |
| `src/huron/pkg/metastore/hierarchy.py` | `PostgresHierarchyStore.dataset` | 1 |
| `src/huron/pkg/metastore/hierarchy.py` | `PostgresHierarchyStore.datasets` | 1 |
| `src/huron/pkg/metastore/hierarchy.py` | `PostgresHierarchyStore.organization` | 1 |
| `src/huron/pkg/metastore/hierarchy.py` | `PostgresHierarchyStore.organizations` | 1 |
| `src/huron/pkg/metastore/hierarchy.py` | `PostgresHierarchyStore.project` | 1 |
| `src/huron/pkg/metastore/hierarchy.py` | `PostgresHierarchyStore.projects` | 1 |
| `src/huron/pkg/metastore/hierarchy.py` | `PostgresHierarchyStore.release` | 1 |

## Newly cloned inventory

| File | Symbol | Fragment count |
| --- | --- | ---: |
| `src/huron/applications/api/authorization/guards.py` | `dataset_raw_writer` | 1 |
| `src/huron/applications/api/authorization/guards.py` | `project_intake` | 1 |
| `src/huron/core/access.py` | `AccessPolicy.dataset` | 1 |
| `src/huron/core/catalog_collections.py` | `DatasetCollection` | 1 |
| `src/huron/core/catalog_collections.py` | `OrganizationCollection` | 1 |
| `src/huron/core/catalog_collections.py` | `ProjectCollection` | 1 |
| `src/huron/core/catalog_collections.py` | `_Collection.get` | 1 |
| `src/huron/core/catalog_ports.py` | `CollectionReader.browse` | 1 |
| `src/huron/pkg/metastore/hierarchy.py` | `_MemoryCollection.get` | 1 |

Matches retained in this slice include creation, descriptions, releases, governance, HTTP model/endpoint families, and unrelated Raw/auth adapter behavior. D2 and later slices own those responsibilities. New reader protocol/construction matches are real typed contracts and remain visible to the unchanged scanner; they are not suppressed.
