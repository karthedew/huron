# D1 typed reads — tested; duplication target outstanding

Source HEAD `6082088dbcf0eda6309e099f122ef01588ead088` plus
[source-working.diff](source-working.diff), including the three new modules.
The [source hashes](tree-hashes.json) identify the final implementation.
D1 replaces reads only; D2 descriptions and later milestones remain pending.

| Gate | Actual outcome | Evidence |
| --- | --- | --- |
| `make lint` | All non-duplication gates pass; exits 2 because native score 55 is below 90 | `lint.log`, `duplication-src-huron.json` |
| `uv run --locked pytest -m unit --cov=src/huron --cov-report=term-missing` | 1,425 passed; 94.97% ≥94.71% | `unit.log` |
| `uv run --locked pytest -m 'contract or integration'` | 30 contract and one integration passed against disposable PostgreSQL 16 and real temporary filesystems | `real-adapters.log` |
| Post-protocol core/access/API/startup runtime check | 92 passed | `post-protocol-runtime.log` |
| Complete OpenAPI comparison | Exact unnormalized equality with D0 | `openapi.json`, `openapi-comparison.json` |
| `uv run --locked python scripts/check_duplication.py src` | Valid native 55/100; 218/798 fragments, 256 pairs, 60 groups; 112 analyzed, zero skipped | `duplication-src.log`, exact `duplication-src.json` |
| Source inventory reconciliation | All 112 actual paths equal report request paths | `source-inventory.txt`, `source-coverage.json` |
| `git diff --check` | Pass | Run after the final code and evidence edits |

Ruff, pydoclint, strict mypy, ty, all nine import contracts, schema-map,
complexipy and pyscn quality checks passed. Radon emitted no C-or-worse complexity
or B-or-worse maintainability grades. The known duplication failure is permitted
only for intermediate slices and is not a green final gate.

The final two-method declaration cleanup moved the existing `RbacStore`
`bindings_for` and `service_account_by_subject` contracts into `BindingFacts`,
with `RbacStore` inheriting them. Full unit and PostgreSQL evidence predates only
that declaration/docstring relocation, with no changed method implementation.
Final static/import/type checks and the 92-test runtime check ran afterward.
The latter command selected `test_core_workflows.py`,
`test_authorization_decisions.py`, `test_api_catalog_hierarchy.py`, and
`test_api_app.py`, with `--no-cov -q`.

## Implemented interface

`OrganizationCollection`, `ProjectCollection`, and `DatasetCollection` share
actor-bound `get(id)` and `browse(parent, limit=..., after=...)` operations.
Concrete constructors fix the reader and parent scope together. Organization
browse requires `PlatformRoot.ROOT`; child browse discovers the parent first.
Point reads retain visibility-based admission without adding a read capability.
The remaining `CatalogService` holds these concrete objects without forwarding
read methods. Creation, descriptions, releases and governance remain in their
existing workflows until their assigned slices.

`CatalogReaders`, `HierarchyFacts`, and `BindingFacts` belong in core.
Authorization now receives actual hierarchy and RBAC adapters, with current
bindings recomputed for each core operation. HTTP retains its separate request
cache. Internal dataset ancestry reads still discover the dataset first, then
resolve its project unrestricted; a narrow dataset grant needs no independent
project grant. Internal Raw, revision, creation, description and release consumers
now use typed reader objects.

Both hierarchy adapters expose typed `organizations`, `projects`, and `datasets`
readers. Memory shares lookup and page mechanics over committed dictionaries.
PostgreSQL uses fixed explicit projections and decoders in `queries.py`, with
visibility predicates before LIMIT, C collation and `(slug, UUID)` cursors.
Organization/project descendant-grant EXISTS clauses remain intact. No Python
post-filter, per-row SQL loop, unbounded page fetch or transaction change was added.

Deleted: six read implementations/declarations from each old core surface and
`HierarchyStore`, six repeated implementations from each adapter, four fact
forwards from `HierarchyRepository`, two fact declarations from `HierarchyStore`
relocated to `HierarchyFacts`, and two duplicated `RbacStore` declarations now
inherited from `BindingFacts`. See the updated D0 deletion matrix and consumer map.

## Behavior, coverage and limitations

The new direct-core tests exercise all three collections, narrow dataset grants,
ancestor scopes, hidden siblings, parent 404s, point missing-target errors,
visibility before limits, cursor continuation, and revocation using the same
collection instances. Existing unique shared memory/PostgreSQL, authorization,
HTTP, mutation, Raw/process-death and restart assertions remain.
Core collections, catalog ports, access, catalog and scopes each have 100% unit
line coverage. The PostgreSQL executor's SQL paths are covered by the real
hierarchy contract, not the unit coverage figure. The two uncovered runtime
provider returns (lines 125 and 174) are unchanged providers unrelated to D1.

During feedback, available disk temporarily fell below the existing 1 GiB Raw
completion reserve. One focused Raw test refused with ENOSPC as designed; no
threshold was changed and no user data was deleted. Capacity later recovered to
4.5 GiB, and the complete unit and real-adapter gates passed. Earlier feedback
logs are retained as feedback rather than pass evidence.

Native progress is 50 → 55 and 241/800 → 218/798, with 32 previously cloned
fragments absent at their old symbols and nine newly matched fragments. See
[complete clone inventory](clone-inventory.md) and [delta](clone-delta.md).
New matches include the real typed collection construction/interface and guard
contracts; they remain visible to the unchanged scanner. Native 90 remains
outstanding. No ingestion/durability guarantee changed, so the large-file
acceptance gate does not apply to D1; P3's separate large-file gap remains open.
No documentation-site page changed, so `make docs` was not applicable.

The PostgreSQL invocation used the running local Podman socket discovered in D0:
`DOCKER_HOST=unix:///var/folders/3t/dsbbphj948x65zmvkftl97580000gn/T/podman/podman-machine-default-api.sock`
and `TESTCONTAINERS_DOCKER_SOCKET_OVERRIDE=/run/podman/podman.sock`.
