# D3a independent verification — attempt 1 of 3

Functional checkpoint: **PASS** under the explicit P3 execution-rule exception.
Overall repository gate: **FAIL — native duplication 55/100 remains below 90**.
No actionable findings in the D3a creation slice. No source or tests were edited.

## Independently executed validation

All logs are complete in this directory. `gate-results.json` records exits.

| Command | Exit and outcome |
| --- | --- |
| `make lint` | 2, solely the final native duplication check; all preceding constituents exited 0 |
| `uv run ruff check .` | 0, no diagnostics, executed by make |
| `uv run ruff format --check .` | 0, no reformatting, executed by make |
| `uv run pydoclint src migrations scripts` | 0, executed by make |
| `uv run mypy` | 0, strict configuration, executed by make |
| `uv run ty check` | 0, executed by make |
| `uv run lint-imports` | 0, 9 kept / 0 broken, executed by make |
| `uv run python scripts/check_schema_map.py` | 0, executed by make |
| `uv run radon cc src/huron --min C` | 0, empty findings, executed by make |
| `uv run radon mi src/huron --min B` | 0, empty findings, executed by make |
| `uv run complexipy src/huron --max-complexity-allowed 15` | 0, executed by make |
| `uv run --locked pyscn check src/huron` | 0, no dead-code/structural failure, executed by make |
| `uv run --locked python scripts/check_duplication.py src/huron` | 1, valid native 55; executed by make |
| `uv run --locked pytest --cov=src/huron --cov-report=term-missing` | 0; 1429 passed, 44 deselected; 94.96% |
| `uv run --locked pytest -m contract` | 0; 30 passed, 1443 deselected |
| `uv run --locked pytest -m integration` | 0; 13 passed, 1460 deselected |
| `uv run --locked python scripts/check_duplication.py src` | 1; valid native 55 |
| `make docs` | 0, strict build |
| `git diff --check` | 0 |
| Fresh OpenAPI capture and D0 comparison | 0; exact JSON equality, no normalization |

`lint-native.json` and `duplication-src-native.json` are copied from the exact
report paths announced by those invocations. Both cover all 115 source Python
files with zero skipped; `source-coverage.json` compares requested paths to the
actual source inventory. Each reports 210/799 cloned fragments, 247 pairs and 57
groups. No scanner settings, thresholds or exclusions changed.

`preflight.json` independently confirms all nine required tools resolve, including
pyscn 1.31.1. Unit `coverage.json` shows all 13 D3a-touched source files at 100%
line coverage; no defensive-line exception was needed. Total is 5577 statements,
281 misses, 94.96%, satisfying the raised floor. Deselection is marker selection;
no tests skipped or xfailed. Two existing third-party deprecation warnings remain.

## Source and behavior inspection

Compared the D2 and stabilized source hash maps to scope the actual creation
slice; inspected the cumulative diff and old/new creation behavior. Current
source/test/config hashes exactly match stabilization (`identity.json`,
`tree-hashes.json`, `d3a-changed-files.json`). HEAD remains
6082088dbcf0eda6309e099f122ef01588ead088; unrelated working-tree work is preserved.

- CatalogCreation owns complete authorized operations. Capability admission
  precedes claim-owner validation; discovery and current visibility remain
  authoritative. Project/dataset ancestry is resolved before claim replay.
- Slug, classification and entry-layer validation retain ordering and errors;
  profile strings remain verbatim and dataset classification comes from parent.
- Claim, insert, off-thread durable generation, receipt and commit retain their
  atomic transaction order. Matching retries return the existing identity and
  changed fingerprints conflict. Real PostgreSQL/POSIX tests prove claim
  concurrency and publication-failure rollback for all three entity kinds.
- The two old creation surfaces have no remaining create_organization,
  create_project or create_dataset methods. HTTP and Raw callers use the focused
  creation collaborator; no compatibility forward was added. Remaining old
  responsibilities are explicitly reserved for paused D3b/D4.
- Consumer-owned typed ports preserve both memory and PostgreSQL conformance.
  API construction owns infrastructure; core imports no adapter or HTTP types.
  Public workflows are exercised directly, using real domain behavior and
  injected I/O adapters. New integration synchronization wraps the real database
  claim rather than replacing its behavior; assertions prove identity/documents.
- Existing creation, validation, collision, authorization, claim and Raw behavior
  assertions are migrated, not suppressed; new integration coverage adds six
  cases. No new ignores, skip/xfail, exclusion, TODO or debug scaffolding found.

## Infrastructure and limits

Podman was stopped initially. Started the existing machine and retained the same
shell through both suites; socket discovered via machine inspect, confirmed by
`podman info`. Tests used disposable PostgreSQL 16 testcontainers, not dev or
production databases. Startup and connectivity logs are retained. No retry or
fixture weakening was needed.

No large-file acceptance ran: verification was explicitly bounded to the D3a
checkpoint; P3 acceptance is the next separate task. No P3 milestone is certified
by this report. D3b–D7 remain paused. The 90 requirement is unchanged and unmet;
this is not a passing make lint/CI or completion of the duplication plan.
