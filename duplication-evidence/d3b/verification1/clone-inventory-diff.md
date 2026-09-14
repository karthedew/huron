# D3b verification 1 — independent clone inventory diff

Recomputed from `clone.clones` of two native JSON reports, keyed by fragment content hash.

| Report | Score | Cloned/total | Pairs | Groups | Files |
| --- | ---: | --- | ---: | ---: | ---: |
| baseline (implementer, pre-edit) | 60 | 213/938 | 253 | 58 | 132/0 |
| verification1 (this run) | 60 | 216/939 | 254 | 59 | 133/0 |

## Removed cloned fragments (3)

- `src/huron/applications/api/routes/v1/endpoints/datasets.py:341-360` hash `32c0b603680ff709` — `async def resolve_release(`
- `src/huron/applications/api/routes/v1/endpoints/datasets.py:310-335` hash `37383bd8e1be4cb5` — `async def list_releases(`
- `src/huron/applications/api/routes/v1/endpoints/datasets.py:248-300` hash `387289410ce788cc` — `async def create_release(`

## Introduced cloned fragments (6)

- `src/huron/core/releases.py:34-47` hash `032abe5de3352373` — `def __init__(self, access: AccessPolicy, hierarchy: ReleaseStore, storage: RawStore) -> None:`
- `src/huron/applications/api/dependencies.py:62-76` hash `045237841e5bbb5e` — `def catalog_releases(runtime: Runtime, actor: CurrentPrincipal) -> Releases:`
- `src/huron/applications/api/routes/v1/endpoints/datasets.py:341-360` hash `934eed217cc1f085` — `async def resolve_release(`
- `src/huron/applications/api/routes/v1/endpoints/datasets.py:310-335` hash `97a67889bf005429` — `async def list_releases(`
- `src/huron/applications/api/routes/v1/endpoints/datasets.py:249-300` hash `d9ed63f31f4b9794` — `async def create_release(`
- `src/huron/core/_ingest.py:249-263` hash `f357f7313e7a622d` — `def __init__(self, raw_store: RawStore, hierarchy: HierarchyStore, *, clock: Clock) -> None:`

## Per-file cloned-fragment delta

- `src/huron/applications/api/dependencies.py`: 3 -> 4
- `src/huron/core/_ingest.py`: 7 -> 8
- `src/huron/core/catalog_ports.py`: 1 -> 2
- `src/huron/core/ports.py`: 1 -> 0
- `src/huron/core/releases.py`: 0 -> 1

## Group membership around the new fragments

- baseline group 41 size 3 sim 0.775: src/huron/applications/api/dependencies.py:18, src/huron/applications/api/dependencies.py:61, src/huron/applications/api/dependencies.py:104
- verification1 group 53 size 2 sim 0.781: src/huron/core/_ingest.py:249, src/huron/core/releases.py:34
- verification1 group 41 size 4 sim 0.766: src/huron/applications/api/dependencies.py:19, src/huron/applications/api/dependencies.py:62, src/huron/applications/api/dependencies.py:82, src/huron/applications/api/dependencies.py:125
