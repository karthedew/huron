# D3b verification 1 — independently rerun gate

Source commit `548548aec67d39c95e291daa98b3258d5e37e851`; working tree as found
(protected user work untouched, `git-status-before.txt` == `git status --porcelain`
after the run).

| Command | Exit | Result |
| --- | ---: | --- |
| `uv run ruff check src` | 0 | All checks passed |
| `uv run ruff format --check src` | 0 | 133 files already formatted |
| `uv run ty check` | 0 | All checks passed |
| `uv run mypy` | 0 | no issues in 133 source files |
| `uv run lint-imports` | 0 | 9 kept, 0 broken |
| `uv run pytest --cov=src/huron --cov-report=term-missing` | 0 | 1677 passed, 64 deselected; total 95.93284122159503%; fail_under 95.93 |
| `uv run radon cc src --min C` | 0 | empty |
| `uv run radon mi src --min B` | 0 | empty |
| `uv run complexipy src --max-complexity-allowed 15` | 0 | within allowed complexity |
| `uv run --locked pyscn check src` | 0 | quality check passed |
| `uv run --locked python scripts/check_duplication.py src` | 1 | native 60/100; 216/939; 254 pairs; 59 groups; 133 analyzed / 0 skipped |
| `make lint` | 2 | fails only at `check_duplication.py`; ruff/format/pydoclint/mypy/ty/lint-imports/schema-map/radon/complexipy/pyscn all passed |
| `uv run --locked pytest -m contract` | 0 | 49 passed, 1692 deselected; `docker ps` empty before and after |
| `uv run --locked pytest -m integration -s` (full) | 1 | 13 passed, 1 failed — `test_actual_legacy_http_request_is_terminated_and_cannot_restart`, `sudo: a password is required` |
| same, that node `--deselect`ed | 0 | 13 passed, 1728 deselected |
| `git diff --check` | 0 | clean |
| OpenAPI vs D0 | — | byte-identical, md5 `544e9bf5f1a010e89bacbec15a66b5df` |

Touched production files, line coverage: `core/releases.py` 100%,
`core/catalog_ports.py` 100%, `core/ports.py` 100%, `core/catalog.py` 100%,
`core/_catalog.py` 100%, `applications/api/dependencies.py` 100%,
`applications/api/routes/v1/endpoints/datasets.py` 100%.

Native JSON copied from `.pyscn/reports/analyze_20260913_155229.json`
(identified by mtime immediately after the scan; see
`duplication-src-native-source.txt`).
