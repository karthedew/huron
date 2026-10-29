# Agent instructions

These rules apply to every agent working in this repository. The implementation plan is
[`IMPLEMENTATION_PLAN.md`](IMPLEMENTATION_PLAN.md); its sections 3–9 are binding design. When this
file and the plan disagree, the plan wins and this file is corrected.

## Layout

```text
src/huron/
  pkg/             generic code with no Huron vocabulary (errors, paging, hashing, fs, acl)
  schema/          JSON Schema documents, validator, naming rules, schema composition
  core/
    security/      broker/ (OIDC exchange, Huron tokens) and rbac/ (roles, privileges, grants)
    lake/          the domain: one subpackage per area (organizations, catalogs, namespaces,
                   collections, files, schemas, audit)
    metastore/     PostgreSQL adapters and in-memory fakes, one subpackage per area
    storage/       share layout, ACL plans, POSIX storage, drift check (used by the CLI)
  applications/
    api/           FastAPI service; routes/v1/{endpoints,schema}
    cli/           Typer CLI; commands/ holds one module per verb group
migrations/        Alembic environment and versions
tests/             unit/ contract/ integration/ acl/ fakes/ support/
```

## Dependency rules

Enforced by import-linter (`pyproject.toml`):

- `pkg` imports nothing from `huron`; `schema` imports only `pkg`.
- `core.security` never imports `core.lake`, `core.metastore`, `core.storage` or `applications`.
- `core.lake` never imports `core.metastore`, `core.storage` or `applications`.
- Only `applications` import `core.metastore`.
- The API never imports the CLI or `core.storage`; the CLI never imports the API, the metastore or
  the broker.

## Code conventions

- No directory under `src/` or `tests/` contains an underscore. No `_impl`, `internal` or `private`
  directories; visibility is expressed by names inside modules and by `__init__.py` exports.
- In every module, public classes and functions come first, underscore-prefixed ones after.
  `tests/unit/test_conventions.py` enforces both rules.
- Values are frozen dataclasses; pydantic models only at the API and CLI edges. Operations are
  classes with explicit constructor dependencies; no module-level singletons.
- Ports are `typing.Protocol` classes owned by the package that calls them; adapters live in
  `core.metastore` and `core.storage`.
- Every domain error subclasses `huron.pkg.errors.HuronError` with a registered `ErrorCode`.
- The service is async (asyncpg, httpx.AsyncClient); the CLI is synchronous.
- Docstrings on every public class and function, in plain language.

## Skills by area

| Area | Skill |
| --- | --- |
| `src/huron/core/` | `oop-design` |
| `src/huron/applications/api/` | `fastapi` |
| `src/huron/core/metastore/`, `migrations/` | `postgresql-table-design` |
| Instruction files | `writing-for-agents` |

## Gate

Run from the repository root; every command must exit 0 and radon must print nothing. `make gate`
runs all of them.

```text
uv run ruff check src tests
uv run ruff format --check src tests
uv run mypy
uv run ty check
uv run lint-imports
uv run pytest -m "not integration" --cov=src/huron --cov-report=term-missing
uv run radon cc src --min C
uv run radon mi src --min B
uv run complexipy src --max-complexity-allowed 15
uv run python scripts/check_schema_map.py
```

The gate's pytest run includes the contract tier, so it needs PostgreSQL: `HURON_TEST_DATABASE_URL`
(a server URL whose user may create databases) when set, otherwise a `postgres:16` testcontainer.
`make test` runs the unit tier alone without a database; `uv run pytest -m integration` runs the
integration tier.

## Testing standard

- Every public function and class has direct tests: happy path, boundaries, empty inputs, every error.
- Tests assert behavior, not implementation. Fakes for stores and storage; mocks only at subprocess,
  network and clock boundaries.
- Test names describe behavior and never mention plan task numbers.
- Shared fixtures live in `tests/support/` and `conftest.py` files.
