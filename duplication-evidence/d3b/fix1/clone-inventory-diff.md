# D3b fix pass 1 — clone inventory diff against the slice's original baseline

Recomputed from `clone.clones` of two native JSON reports, keyed by fragment content hash:
`duplication-evidence/d3b/baseline/duplication-src-native.json` (source commit
`548548aec67d39c95e291daa98b3258d5e37e851`, before any D3b edits) against
`duplication-evidence/d3b/fix1/duplication-src-native.json` (this fix pass's
final tree, after resolving verification 1's four findings).

| Report | Score | Cloned/total | Pairs | Groups | Files |
| --- | ---: | --- | ---: | ---: | ---: |
| baseline (pre-D3b) | 60 | 213/938 | 253 | 58 | 132/0 |
| fix1 (this run) | 60 | 216/939 | 254 | 59 | 133/0 |

Identical to verification 1's own recomputation from the attempt-1 tree
(`duplication-evidence/d3b/verification1/clone-inventory-diff.md`): deleting
`HierarchyRepository.data_root` (2 statements, never itself a clone fragment)
did not change the fragment/pair/group counts.

## Removed cloned fragments (3)

- `src/huron/applications/api/routes/v1/endpoints/datasets.py:341-360` hash `32c0b603680ff709` — `async def resolve_release(`
- `src/huron/applications/api/routes/v1/endpoints/datasets.py:310-335` hash `37383bd8e1be4cb5` — `async def list_releases(`
- `src/huron/applications/api/routes/v1/endpoints/datasets.py:248-300` hash `387289410ce788cc` — `async def create_release(`

## Introduced cloned fragments (6)

- `src/huron/core/releases.py:34-47` hash `032abe5de3352373` — `def __init__(self, access: AccessPolicy, hierarchy: ReleaseStore, storage: RawStore) -> None:`
- `src/huron/applications/api/dependencies.py:62-76` hash `045237841e5bbb5e` — `def catalog_releases(runtime: Runtime, actor: CurrentPrincipal) -> Releases:`
- `src/huron/applications/api/routes/v1/endpoints/datasets.py:309-334` hash `1ba45cc3ab12a739` — `async def list_releases(` (one line earlier than verification 1's capture: the ruff import-sort fix that merged `Creation`/`ReleaseWorkflow` onto one `from ... import` line removed a line above)
- `src/huron/applications/api/routes/v1/endpoints/datasets.py:248-299` hash `c6e27880bcc723be` — `async def create_release(`
- `src/huron/applications/api/routes/v1/endpoints/datasets.py:340-359` hash `d6def09a882b2eb5` — `async def resolve_release(`
- `src/huron/core/_ingest.py:249-263` hash `f357f7313e7a622d` — `def __init__(self, raw_store: RawStore, hierarchy: HierarchyStore, *, clock: Clock) -> None:`

The three `datasets.py` handler hashes differ from verification 1's capture
(`934eed217cc1f085`, `97a67889bf005429`, `d9ed63f31f4b9794`) only because their
content shifted up one line: fix pass 1's alias rename
(`Release as ReleaseCatalog` → `ReleaseWorkflow`) let ruff's import sort merge
`from huron.applications.api.dependencies import Creation` and `... import
ReleaseWorkflow` onto adjacent single-symbol lines, same as before the fix —
no behavioral content changed, only the one-line offset. `core/releases.py`
and `core/_ingest.py`'s constructor-boilerplate echo, and
`dependencies.py`'s DI-factory group, are unchanged in kind from verification
1's finding and remain out of this slice's scope for the same reasons
recorded in `README.md`'s "Native duplication before/after" section.

## Per-file cloned-fragment delta

- `src/huron/applications/api/dependencies.py`: 3 -> 4
- `src/huron/core/_ingest.py`: 7 -> 8
- `src/huron/core/catalog_ports.py`: 1 -> 2
- `src/huron/core/ports.py`: 1 -> 0
- `src/huron/core/releases.py`: 0 -> 1

## Group membership around the new fragments

- fix1 group 41 size 4 sim 0.766: `src/huron/applications/api/dependencies.py:19`
  (`catalog_service`), `:62` (`catalog_releases`), `:82`
  (`raw_ingestion_service`), `:125` (`revision_service`) — the baseline
  three-member group (`catalog_service:18`, `raw_ingestion_service:61`,
  `revision_service:104`, similarity 0.775) plus `catalog_releases` as its
  fourth member, exactly as corrected in `README.md`'s clone-attribution fix.
- fix1 group 53 size 2 sim 0.781: `src/huron/core/_ingest.py:249`,
  `src/huron/core/releases.py:34`.
