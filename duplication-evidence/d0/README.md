# D0 execution baseline — tested; duplication target outstanding

Captured 2026-09-10 against HEAD `6082088dbcf0eda6309e099f122ef01588ead088`.
No source, tests, scanner configuration, thresholds, or import contracts changed.
All gates were freshly run; no previous test receipt was reused.

| Command | Outcome | Evidence |
| --- | --- | --- |
| `make lint` | Exit 2 at final make target: native duplication 50 below 90. All preceding checks passed. | `lint.log`, exact `duplication-src-huron.json` |
| `uv run --locked pytest -m unit --cov=src/huron --cov-report=term-missing` | 1,423 passed; 94.75% coverage ≥94.71% | `unit.log` |
| `uv run --locked pytest -m 'contract or integration'` | 31 passed: 30 contract, one integration; actual PostgreSQL 16 and temporary filesystems | `real-adapters.log` |
| `uv run --locked python scripts/check_duplication.py src` | Exit 1: valid native score 50, 241/800 fragments, 319 pairs, 60 groups | `duplication-src.log`, exact `duplication-src.json` |
| Source inventory reconciliation | 109 Python files; request paths exactly equal inventory; no skips | `source-inventory.txt`, `source-coverage.json` |
| Source/config/test identity | Hashes unchanged across fresh gates | `tree-hashes.json`, `tree-verification.json` |

Ruff lint/format, pydoclint, strict mypy and ty, all nine import contracts,
schema-map, complexipy and pyscn quality checks passed. Radon emitted no C-or-worse
complexity or B-or-worse maintainability findings. The lint target is **not green**:
its known duplication failure remains authorized only for intermediate slices.

## Reproduction and ownership

`initial-status.txt` and `initial-working.diff` preserve the preexisting working
changes; these belong to the user/earlier work and were not reverted. `head.txt`
records full commit identity; `environment.json` records locked tool versions.
`tree-hashes.json` covers src/tests/scripts/migrations and pyproject/lock/Makefile/CI.
D0 owns this evidence directory and only D0 checkboxes/ledger in the plan.

Actual `podman machine inspect` discovered the running default machine socket:
`/var/folders/3t/dsbbphj948x65zmvkftl97580000gn/T/podman/podman-machine-default-api.sock`.
The real-adapter invocation used:

```sh
DOCKER_HOST=unix:///var/folders/3t/dsbbphj948x65zmvkftl97580000gn/T/podman/podman-machine-default-api.sock TESTCONTAINERS_DOCKER_SOCKET_OVERRIDE=/run/podman/podman.sock uv run --locked pytest -m 'contract or integration'
```

Existing testcontainers fixtures create/dispose `postgres:16` containers, migrate
their temporary databases, and exercise real adapters. No deployment database was
used. Initial sandbox commands failed opening the existing uv cache; approved
escalated reruns produced the final logs. Podman inspection also required approved
local-machine access. Two existing deprecation warnings did not affect results.

## HTTP and consumer contracts

`openapi.json` is the complete unnormalized document from `create_app` with the
same dev-header/memory-store settings as the hierarchy/router tests; explicit
settings are in `runtime-settings.json`. `response-contracts.json` captures eight
actual TestClient results (unauthenticated, create/get/browse, missing target,
missing/stale precondition, validation), including response bodies and headers.
IDs, timestamps and request-instance IDs in captured responses are runtime values;
compare their contract rather than freezing those values. D5 may normalize only
unordered `required` arrays in OpenAPI comparison.

`consumer-map.md` maps responsibilities/callers to preserved behavioral suites.
`consumer-references.txt` includes exact symbol references plus typing and aliases.
`deletion-matrix.md` lists every old declaration; all rows remain open.
`clone-inventory.md` includes every one of the 241 `clone.clones` entries with
current symbol/range, independent of group IDs.

D1 may now start. No non-duplication baseline defect was found. D0 does not satisfy
D1 behavior at a new interface, D2 combined concurrency/filesystem evidence, native
90, P3/M1a completion, or large-file acceptance. No large-file gate applies to D0
because it changes no ingestion/durability behavior. No site documentation was
changed by D0, so application/docs builds do not validate these evidence files.
