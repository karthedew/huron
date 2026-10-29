---
title: Testing
---

> **Throwaway prototype — not shipped documentation.** Canonical source: `docs/getting-started/testing.md`. Generated rendering view; original source remains authoritative.

<a id="testing"></a>

Four registered suites currently answer different questions. A test in the wrong suite is either slow for no
reason or reassuring for no reason.

| Marker | Question | Needs | Speed |
|---|---|---|---|
| `unit` | Are rules and workflows correct? | injected doubles and temporary local filesystems | milliseconds to seconds |
| `contract` | Does an adapter honour its Protocol? | Docker (testcontainers) | seconds |
| `integration` | Do the pieces work together? | PostgreSQL testcontainers; isolated Linux/Podman for controlled cutover | seconds to minutes |
| `acceptance` | Does a phase gate hold end to end? | ≥ 25 GiB free disk | minutes |

`pyproject.toml` sets `addopts = "-m unit --strict-markers"`, so:

```bash
uv run pytest              # unit only — the default
make test                  # the same thing
uv run pytest -m contract  # needs a Docker daemon
uv run pytest -m ""        # everything, if you have the services
```

`--strict-markers` means an unregistered marker is an error rather than a silent skip. Register
new markers in `pyproject.toml`. `asyncio_mode = "auto"`, so `async def` tests need no decorator.

## Discover coverage and fixtures first

Follow the **Test and fixture reuse** rules in the root `AGENTS.md`. Search the
existing test cases and parametrization before adding coverage, then inspect the
fixtures available to the affected test module. For example:

```bash
uv run pytest --collect-only -m unit tests/unit/test_api_ingest_sessions.py
uv run pytest --fixtures -m unit tests/unit/test_api_ingest_sessions.py
uv run pytest --fixtures-per-test -m unit tests/unit/test_api_ingest_sessions.py
```

Choose the path and marker for the actual boundary being tested. Useful existing
entry points include:

- `tests/unit/conftest.py`: composable `stores` and `client` fixtures.
- `tests/unit/support.py`: `FakeClock`, fresh `memory_stores`, and ingest builders.
- `tests/ingest_client.py`: reusable HTTP ingestion operations and manifest builders.
- `tests/hierarchy_contract.py`: shared behavioral scenarios exercised by adapters.
- `tests/integration/conftest.py`: a disposable migrated PostgreSQL lifecycle.

Inspect each helper's assumptions and scope before reuse. Add a missing capability
to an appropriate factory/fixture instead of cloning its setup, while preserving
test isolation and genuine real-adapter coverage. Frontend tests likewise start
with the existing API-seam, browser and fixture helpers.

## Unit

Domain rules have deterministic tests; complete Core operations use injected ports.
The [import boundaries](/huron-docs/getting-started/conventions/#import-boundaries) separate those operations
from concrete infrastructure. Some unit tests deliberately use temporary real POSIX
storage or drive the composed API, so this marker does not promise zero local I/O.

High-value targets: the RBAC role matrix invariants (service accounts alone have silver and gold
write authority; administrative roles hold no `data.write` at all),
the layer promotion graph, path construction **and** the `parse(construct(x)) == x` round trip,
JCS canonicalisation stability, and the amendment fold.

The HTTP surface is unit-testable through `TestClient` against injected in-memory
stores and temporary POSIX storage. Direct tests such as
`tests/unit/test_security_authentication.py` and `tests/unit/test_integrity_controller.py`
exercise complete public workflows independently of HTTP or Unix-socket transport.

:::caution[Enter `TestClient` as a context manager]

Startup work — including the `HURON_BOOTSTRAP_PLATFORM_OWNER` grant — happens in the ASGI
lifespan, and Starlette only runs lifespan handlers when `TestClient` is used as a context
manager. `with TestClient(app) as client:`, not a bare constructor, or the app under test has
no bindings.

:::

## Contract

Exercises an adapter against the real thing its Protocol abstracts. `tests/contract/` spins up a
real PostgreSQL through `testcontainers`, runs the Alembic migrations, and drives the Postgres
stores through actual reads and writes.

The most valuable assertion there is the drift check: the roles and capabilities seeded by the
migration must reconstruct exactly `huron.core.security.roles.ROLES`. The Python model and the SQL seed
are written by hand in two files and nothing else keeps them in sync.

:::caution[Contract tests need a Docker daemon]

Without one, `testcontainers` fails immediately. This is the one suite that cannot run in a
sandbox with no container runtime. Integration also needs real services. When unavailable,
the honest report is "not run", not a
skip marker — and the SQL still needs verifying against a real PostgreSQL some other way
before it is trusted.

:::

:::note[Podman hosts disable Ryuk]

`testcontainers`' reaper container (Ryuk) does not start reliably against a Podman socket. On
a Podman host, run the suite as `TESTCONTAINERS_RYUK_DISABLED=true uv run pytest -m contract`.

:::

## Integration

`tests/integration/` exercises catalog creation/descriptions/releases and Raw upload
across real PostgreSQL and POSIX storage, including application restarts. Its
controlled-cutover test additionally provisions a private Podman engine on Linux and
requires root or noninteractive sudo, working container networking, and the pinned
historical Git object identified by the test. Run it on an isolated provisioned runner;
a working Docker endpoint alone does not satisfy that test's Podman prerequisite.

```bash
uv run pytest -m integration
```

Run every test. A missing historical Git object, unavailable authority, a deselected
cutover case or no collected tests is not evidence of an integration pass.

## Acceptance

Proves a phase gate holds end to end, at real sizes, over a real socket — the one suite too slow
and too disk-hungry to run on every push. `tests/acceptance/test_raw_ingest_gate.py` round-trips a
9 GiB file through an interrupted, resumed multipart upload and a streamed download, driven by
`httpx` against the real app over a loopback `uvicorn` socket (`memory_stores()` for the hierarchy,
the real `PosixRawStore` for storage) rather than `TestClient`, which would materialize the whole
response body in memory.

```bash
make test-acceptance       # needs ≥ 25 GiB free disk
uv run pytest -m acceptance
```

`.github/workflows/acceptance.yml` runs it nightly (`workflow_dispatch` also triggers it by hand)
on a runner with the disk to spare, and records a `df -h .` receipt in the job log before the test
runs.

The test refuses to start below 25 GiB free on its temporary-data filesystem.
Its sparse source occupies negligible blocks, but the 9 GiB upload and independent
9 GiB completion candidate coexist. The remaining 7 GiB allows the default 1 GiB
completion reserve plus filesystem overhead and other local consumers. This
preflight does not reserve space against concurrent writers; concurrent acceptance
runs require additional capacity. With `--junitxml=receipt.xml`, the test records
the completion and commit request durations as suite properties.

## Rules

- Test behaviour and contracts, not implementation. A test that breaks under a correct refactor is
  a defect in the test.
- Deterministic: no wall-clock, network, unseeded randomness, or ordering dependence.
- Mock only at genuine I/O boundaries. Never mock the code under test or its in-package collaborators.
- Delete tests for deleted code. Do not skip or comment them out.
- Never add `skip` or `xfail` to get a suite green.
- Name tests for the behaviour in plain language. Test names do not reference plans, phases, or
  task numbers.

## Complete applicable gates

Use the locked environment, root cwd, and retain the configured 96.01% coverage
floor, import contracts, complexity limits and duplication ratchet:

```sh
make lint
uv run pytest -m unit --cov=src/huron --cov-report=term-missing
uv run pytest -m contract
uv run pytest -m integration
make test-acceptance
```

Real-adapter suites apply to affected database/storage/workflow boundaries;
acceptance applies to ingest/durability and requires at least 25 GiB free. Integration
needs the isolated Linux/Podman controlled-cutover prerequisites above. CI's current
exit-5 tolerance is not proof of integration. Inspect radon diagnostics: C+ complexity
or B+ maintainability is a finding even with exit 0. No skips, xfails, weaker assertions,
suppressed diagnostics or increased duplication allowances to manufacture a pass.

From `web/`, autofix every changed component and run the complete frontend gate:

```sh
npx @sveltejs/mcp svelte-autofixer <path> --svelte-version 5
npm run check
npm test
npm run lint
npm run build
npm run test:e2e
```

The autofixer's `<path>` is each changed `.svelte` file, not a literal argument.
Visible interactions also require named-session local Playwright CLI QA: mobile,
816px, wide, light/dark, keyboard/focus, loading/empty/long content/validation/error/
unauthorized states, overflow, hydration and console checks. Prove endpoint ownership
before opening a browser. Missing infrastructure is BLOCKED, not PASS.

Docs-only changes use root `make docs`, `git diff --check`, new-text whitespace and
local Markdown/HTML link/fragment checks (including design pages outside the site).
Agent-asset cross references additionally use `.agents/` `npm run check` and `npm test`
with supported Node; the verified local version is 22.23.2.

## Planned verification organization and scale

Target directories are `tests/{unit,contract,integration,acceptance,performance,load}`.
Mirror `src/huron` owners where meaningful; cross-domain tests follow behavior.
Preserve meaningful current tests and scoped fixtures when moving them. Register new
markers before using them; SDK test/build and OpenAPI regeneration checks need owned
scripts before their proposed commands are runnable.

Keep the 9 GiB acceptance regression while replacing its numbered-part contract
deliberately. It is not evidence for tus or 50 distinct users × 10 GiB on 50 datasets.
Future pinned k6 qualification must stream bounded PATCH buffers, separate same-dataset
contention, measure through readable release commit plus search under load, and record
verification/copy/commit timing, capacity, resources, errors/retries, real NFS and
generator capacity. Peak space exceeds 500 GiB. Hardware baseline precedes agreed SLO.
