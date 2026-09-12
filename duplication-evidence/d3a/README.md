# D3a catalog creation — tested; duplication target outstanding

Fresh stabilization on 2026-09-11 completed the existing creation slice without
further production refactoring. D3b–D7 are paused by the user's P3-first decision
in [P3 execution rules](../../P3_IMPLEMENTATION_PLAN.md#execution-rules).
The native 90 target remains unchanged and unmet. Independent full revalidation
of this checkpoint is pending; this is not completion of the duplication plan.

## Behavior and ownership

`CatalogCreation` owns the three explicit organization/project/dataset creation
operations, capability and claim-owner checks, parent discovery, validation,
claim replay, inserts, off-thread generation publication, and receipt ordering.
`CatalogService` and `HierarchyRepository` no longer expose their replaced three
creation operations. HTTP handlers and Raw `create_in_project` use the focused
collaborator. Existing claim fingerprints, stored profile strings, entry-layer
rules, transactions and provenance behavior are preserved.

The six real PostgreSQL/POSIX creation cases prove matching concurrent claims
return one identity with one generation, changed fingerprints conflict, failed
generation writes roll back identity and claim, and retries succeed for all three
entity kinds. The full integration run also covers descriptions and Raw restart.

## Fresh evidence

All paths below are within [stabilization-20260911](stabilization-20260911/).
Commands ran against the existing tree; only the coverage floor changed afterward.

| Command/evidence | Result |
| --- | --- |
| `preflight.json` | All nine required tools resolve; pyscn 1.31.1 |
| `make lint`, `lint.log` | Exit 2 solely at duplication checker; Ruff, formatting, pydoclint, mypy, ty, import contracts, schema map, radon, complexipy and pyscn check pass; radon outputs empty |
| `uv run --locked pytest --cov=src/huron --cov-report=term-missing`, `unit.log` | 1,429 passed, 44 deselected; 94.96%, 5,577 statements / 281 misses |
| `uv run --locked pytest -m contract`, `contract.log` | 30 passed, 1,443 deselected, exit 0 |
| `uv run --locked pytest -m integration`, `integration.log` | 13 passed, 1,460 deselected, exit 0 |
| `uv run --locked python scripts/check_duplication.py src`, `duplication-src.log` | Exit 1, valid native 55/100; 210/799 fragments, 247 pairs, 57 groups |
| `lint-native.json`, `duplication-src-native.json` | Exact fresh package and full-source native reports |
| `source-inventory.txt`, `source-coverage.json` | All 115 source paths match requested scan paths; zero skipped |
| `coverage-ratchet.log` | Parent reran `uv run --locked coverage report` after raising floor 94.71 → 94.96; exit 0 |

New creation/claim/port modules and touched core/HTTP creation modules have 100%
line coverage. No production or test code changed during stabilization. Raising
the coverage floor is the only configuration change, required by the workflow's
ratchet; no threshold was weakened. The independent verifier will rerun the full
gate using the new floor. Complete stdout logs are retained without truncation.

## Infrastructure recovery

Initial connectivity failed because the existing Podman machine was stopped and
its socket absent. A standalone start reported success but the machine stopped
when that tool process ended; the subsequent API/SSH checks refused connections.
Starting Podman and retaining its parent process through both suites solved this
session lifecycle problem. `podman-start.log` and `podman-connectivity.json` record
the successful startup and API ping; disposable PostgreSQL 16 testcontainers then
completed both suites. No production database was used, and no test timeout,
assertion or infrastructure fixture was weakened. The earlier saved PostgreSQL
startup timeout no longer blocks the D3a test receipt.

## Identity, review and limits

HEAD: `6082088dbcf0eda6309e099f122ef01588ead088`. Cumulative tracked and untracked
source/test/config changes are captured in `source-working.diff`; exact hashes in
`tree-hashes.json`. SHA-256 of sorted JSON hash map:
`7a612042d385e56f2a351375c82c0f86d56d1410062474402f970e39f651b791`.
Unrelated existing working-tree changes were preserved; nothing committed/pushed.

[Prior independent review](review.md) found no actionable creation defects but
did not execute gates. Its OpenAPI comparison remains historical evidence
(`openapi-comparison.json`); no fresh OpenAPI capture was made in stabilization.
[Fresh independent verification](verification-20260911/review.md) subsequently
reran all gates and the exact OpenAPI comparison, returning functional PASS with
no actionable findings. This receipt does not claim all repository gates pass:
duplication is 55, below 90. No large-file acceptance was run here;
P3's separate acceptance task now has sufficient reported disk space and remains
responsible for that evidence. No documentation-site content was edited, so
`make docs` was not applicable. Python tests do not validate this receipt's prose.
