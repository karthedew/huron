# D3b fix pass 1 — complete validation gate

Source commit `548548aec67d39c95e291daa98b3258d5e37e851`; working tree carries
the D3b implementation plus this fix pass's four corrections. Protected user
work untouched (`git-status-after.txt` differs from `git-status-before.txt`
only by the evidence directory growing under `duplication-evidence/d3b/`, and
new files this fix pass itself created:
`tests/integration/test_catalog_releases.py`).

| Command | Exit | Result |
| --- | ---: | --- |
| `uv run ruff check src` | 0 | All checks passed |
| `uv run ruff format --check src` | 0 | 133 files already formatted |
| `uv run ty check` | 0 | All checks passed |
| `uv run mypy` | 0 | no issues in 133 source files |
| `uv run lint-imports` | 0 | 9 kept, 0 broken |
| `uv run pytest --cov=src/huron --cov-report=term-missing` | 0 | 1677 passed, 65 deselected (was 64: the new integration test adds one non-unit-marked collected item); raw total 6623/6904 = 95.9298...%, which `coverage.py`'s own `should_fail_under` rounds to the configured `precision = 2` before comparing (`round(95.9298, 2) = 95.93`, not `< fail_under = 95.93`), so the gate passes at exit 0. `pytest-cov`'s terminal-summary line prints a cosmetic `FAIL Required test coverage of 95.93% not reached. Total coverage: 95.93%` banner because that one line compares the *unrounded* total against `fail_under` with strict `<`; it does not affect `session.testsfailed` or the process exit code (verified directly: `unit.exit` contains `0`). See "Coverage ratchet note" below. |
| `uv run radon cc src --min C` | 0 | empty |
| `uv run radon mi src --min B` | 0 | empty |
| `uv run complexipy src --max-complexity-allowed 15` | 0 | within allowed complexity |
| `uv run --locked pyscn check src` | 0 | quality check passed (254 informational clones) |
| `uv run --locked python scripts/check_duplication.py src` | 1 | native 60/100; 216/939 fragments; 254 pairs; 59 groups; 133 analyzed / 0 skipped — unchanged from verification 1 |
| `make lint` | 2 | fails only at `check_duplication.py`; ruff/format/pydoclint/mypy/ty/lint-imports/schema-map/radon/complexipy/pyscn all passed |
| `uv run --locked pytest -m contract` | 0 | 49 passed, 1693 deselected; `docker ps` empty before and after |
| `uv run --locked pytest -m integration -s` (full) | 1 | 14 passed, 1 failed — `test_actual_legacy_http_request_is_terminated_and_cannot_restart`, `sudo: a password is required`, exactly as documented; the new `test_catalog_releases.py::test_concurrent_release_creation_replays_one_identity_and_refuses_conflicting_claims` passed |
| same, that node `--deselect`ed | 0 | 14 passed, 1728 deselected |
| `uv run --locked pytest --co -m integration -q` | 0 | 15/1742 collected (1727 deselected) — was 14 before this fix pass; the new test is not parametrized, so it added exactly one |
| `git diff --check` | 0 | clean |
| OpenAPI vs D0 | — | byte-identical, md5 `544e9bf5f1a010e89bacbec15a66b5df`, regenerated fresh from `create_app` with dev-headers/memory-store settings identical to D0's and verification 1's capture convention |

## Coverage ratchet note

`fail_under` stays at `95.93` (unchanged from attempt 1 — the ratchet rule
forbids lowering it, and this run does not exceed it by two decimals either,
so it is not raised again). The raw ratio moved from 95.93284% (verification
1, `TOTAL` 6909 statements) to 95.9298% (this run, `TOTAL` 6904 statements)
purely because deleting `HierarchyRepository.data_root` (fix pass 1, item 2)
removed 2 fully-covered statements from the denominator without touching any
missed line (`missed` stays 281 in both runs) — removing covered lines from a
ratio's denominator can lower the ratio even though nothing regressed. Both
values round to `95.93` at the configured `precision = 2`, which is what
`coverage.py`'s actual pass/fail decision (`should_fail_under`) compares
against `fail_under`, so both runs pass at the same floor.

Touched production files, line coverage: `core/_catalog.py` 100%,
`core/catalog.py` 100%, `core/catalog_ports.py` 100%, `core/ports.py` 100%,
`core/releases.py` 100%, `applications/api/dependencies.py` 100%,
`applications/api/routes/v1/endpoints/datasets.py` 100%.

Native JSON copied from `.pyscn/reports/analyze_20260913_161516.json`
(identified by mtime immediately after the standalone `check_duplication.py`
run; see `duplication-src-native-source.txt`).

## Docker

`docker ps` before this fix pass's gate run: empty (`docker-ps-before.txt`).
Before/after the contract suite: empty/empty
(`docker-ps-contract-before.txt`/`docker-ps-contract-after.txt`). After the
full gate: empty (`docker-ps-after.txt`). Testcontainers tears its container
down at the end of each run in every case.
