# D3b verification 2 — independent full gate rerun (fix pass 1)

Source commit `548548aec67d39c95e291daa98b3258d5e37e851`, branch `p3/m1b-authority`,
working tree as delivered by fix pass 1. No file outside this directory was written.

| Command | Exit | Result |
| --- | ---: | --- |
| `uv run ruff check src` | 0 | All checks passed |
| `uv run ruff format --check src` | 0 | 133 files already formatted |
| `uv run ty check` | 0 | All checks passed |
| `uv run mypy` | 0 | no issues |
| `uv run lint-imports` | 0 | 9 kept, 0 broken |
| `uv run pytest --cov=src/huron --cov-report=term-missing` | 0 | 1677 passed, 65 deselected; TOTAL 6904 statements, 281 missed, covered 6623 = **95.92989571%**. Terminal prints `FAIL Required test coverage of 95.93% not reached. Total coverage: 95.93%` yet the process exits 0 (coverage.py compares the value rounded to `precision = 2`). See ratchet ruling. |
| `uv run radon cc src --min C` | 0 | empty |
| `uv run radon mi src --min B` | 0 | empty |
| `uv run complexipy src --max-complexity-allowed 15` | 0 | within allowed complexity |
| `uv run --locked pyscn check src` | 0 | passed (254 informational clones) |
| `uv run --locked python scripts/check_duplication.py src` | 1 | 60/100; 216/939 fragments; 254 pairs; 59 groups; 133 files analyzed |
| `make lint` | 2 | fails only at `check_duplication.py`; every prior stage passed |
| `uv run --locked pytest -m contract` | 0 | 49 passed, 1693 deselected; `docker ps` empty before and after |
| `uv run --locked pytest --co -m integration -q` | 0 | 15/1742 collected; `tests/integration/test_catalog_releases.py::test_concurrent_release_creation_replays_one_identity_and_refuses_conflicting_claims` present |
| `uv run --locked pytest -m integration -s` (full) | 1 | 14 passed, 1 failed — the documented `test_actual_legacy_http_request_is_terminated_and_cannot_restart` with `sudo: a password is required` |
| same, that node `--deselect`ed | 0 | 14 passed, 1728 deselected |
| `git diff --check` | 0 | clean |
| `uv run --locked pytest -q -m integration tests/integration/test_catalog_releases.py -s` x3 | 0,0,0 | 1 passed each (3.08s / 3.06s / 3.08s) — deterministic. NOTE: without `-m integration` the command exits 5 (`1 deselected`) because `addopts = "-m unit"`. |
| OpenAPI vs D0 | — | byte-identical, md5 `544e9bf5f1a010e89bacbec15a66b5df` |

Native scan JSON copied from `.pyscn/reports/analyze_20260913_162616.json`
(newest by mtime immediately after the standalone run; see
`duplication-src-native-source.txt`).

## Coverage ratchet ruling — DEFECT

The floor rule is "never lower `fail_under`; raise it to the measured value
floored to two decimals when a run exceeds it". Measured 95.92989571%; its
two-decimal floor is **95.92**, below the configured `fail_under = 95.93`
that this slice itself introduced (95.92 -> 95.93 in `pyproject.toml`). The
tree therefore does not meet its own configured floor under the floor rule;
the gate exits 0 only because coverage.py's `should_fail_under` compares
`round(95.9298, 2) = 95.93` rather than the raw ratio, which is why the same
run prints `FAIL Required test coverage of 95.93% not reached`. The
correction is to raise real coverage, not to lower `fail_under`: covering one
currently-missed line gives 6624/6904 = 95.94438% (floor 95.94); the four
missed pure-logic lines in `src/huron/pkg/rbac/roles.py` (297-298, 327, 333 —
`UnknownRole`, unknown-principal-kind and disallowed-principal-kind error
paths) give 6627/6904 = 95.98783% (floor 95.98). Then set `fail_under` to the
new floor.

## Concurrency test assessment — accepted

`tests/integration/test_catalog_releases.py` drives the real
`Releases.create_release` workflow (authorization + claim ownership + the
store transaction), over real PostgreSQL via testcontainers
(`catalog_database`, module-scoped `PostgresContainer("postgres:16")` with
alembic migration) and the real filesystem (`PosixRawStore(tmp_path)`). The
`asyncio.Barrier(2)` is installed on `writer.claim` inside an already-open
transaction, so neither call can complete before the other has staked its
claim (a serialized execution would time out at 10s). All four required
assertions are present and load-bearing: exactly one `releases` row proven by
`pool.fetchval("SELECT count(*) FROM releases ...") == 1` on a separate
connection; the tag file proven on disk by
`Path(str(tag_path)).read_bytes() == payload`; the `write_tag_once` call
count proven by `len(writes) == 1`; off-loop execution proven by
`ran_on_the_event_loop == [False]` via `asyncio.get_running_loop()`
inside the tracked write. `IdempotencyKeyReused` on a changed fingerprint and
exactly one `TagExists` among two concurrent distinct-claim writers to a
fresh tag are both asserted. Three consecutive standalone runs passed.

## Docker

`docker ps` empty before and after the contract suite, after the full gate,
and before/after each determinism run.
