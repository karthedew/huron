# Testing

Four suites, each answering a different question. A test in the wrong suite is either slow for no
reason or reassuring for no reason.

| Marker | Question | Needs | Speed |
|---|---|---|---|
| `unit` | Is the logic correct? | nothing external | milliseconds |
| `contract` | Does an adapter honour its Protocol? | Docker (testcontainers) | seconds |
| `integration` | Do the pieces work together? | the Compose stack | seconds to minutes |
| `acceptance` | Does a phase gate hold end to end? | ≥ 10 GiB free disk | minutes |

`pyproject.toml` sets `addopts = "-m unit --strict-markers"`, so:

```bash
uv run pytest              # unit only — the default
make test                  # the same thing
uv run pytest -m contract  # needs a Docker daemon
uv run pytest -m ""        # everything, if you have the services
```

`--strict-markers` means an unregistered marker is an error rather than a silent skip. Register
new markers in `pyproject.toml`. `asyncio_mode = "auto"`, so `async def` tests need no decorator.

## Unit

Where most of the effort belongs. `pkg/` has no I/O, so its tests need no fixtures — that is the
payoff of the [import boundaries](conventions.md#import-boundaries).

High-value targets: the RBAC role matrix invariants (service accounts alone have silver and gold
write authority; administrative roles hold no `data.write` at all),
the layer promotion graph, path construction **and** the `parse(construct(x)) == x` round trip,
JCS canonicalisation stability, and the amendment fold.

The HTTP surface is unit-testable too, through `TestClient` against an in-memory repository —
`tests/unit/test_api_rbac.py` walks a full delegation chain from bootstrap platform owner down to
a service account writing Silver, with no services running.

!!! warning "Enter `TestClient` as a context manager"

    Startup work — including the `HURON_BOOTSTRAP_PLATFORM_OWNER` grant — happens in the ASGI
    lifespan, and Starlette only runs lifespan handlers when `TestClient` is used as a context
    manager. `with TestClient(app) as client:`, not a bare constructor, or the app under test has
    no bindings.

## Contract

Exercises an adapter against the real thing its Protocol abstracts. `tests/contract/` spins up a
real PostgreSQL through `testcontainers`, runs the Alembic migrations, and drives the Postgres
stores through actual reads and writes.

The most valuable assertion there is the drift check: the roles and capabilities seeded by the
migration must reconstruct exactly `huron.pkg.rbac.roles.ROLES`. The Python model and the SQL seed
are written by hand in two files and nothing else keeps them in sync.

!!! warning "Contract tests need a Docker daemon"

    Without one, `testcontainers` fails immediately. This is the one suite that cannot run in a
    sandbox with no container runtime. When that happens, the honest report is "not run", not a
    skip marker — and the SQL still needs verifying against a real PostgreSQL some other way
    before it is trusted.

!!! note "Podman hosts disable Ryuk"

    `testcontainers`' reaper container (Ryuk) does not start reliably against a Podman socket. On
    a Podman host, run the suite as `TESTCONTAINERS_RYUK_DISABLED=true uv run pytest -m contract`.

## Acceptance

Proves a phase gate holds end to end, at real sizes, over a real socket — the one suite too slow
and too disk-hungry to run on every push. `tests/acceptance/test_raw_ingest_gate.py` round-trips a
9 GiB file through an interrupted, resumed multipart upload and a streamed download, driven by
`httpx` against the real app over a loopback `uvicorn` socket (`memory_stores()` for the hierarchy,
the real `PosixRawStore` for storage) rather than `TestClient`, which would materialize the whole
response body in memory.

```bash
make test-acceptance       # needs ≥ 10 GiB free disk
uv run pytest -m acceptance
```

`.github/workflows/acceptance.yml` runs it nightly (`workflow_dispatch` also triggers it by hand)
on a runner with the disk to spare, and records a `df -h .` receipt in the job log before the test
runs.

## Rules

- Test behaviour and contracts, not implementation. A test that breaks under a correct refactor is
  a defect in the test.
- Deterministic: no wall-clock, network, unseeded randomness, or ordering dependence.
- Mock only at genuine I/O boundaries. Never mock the code under test or its in-package collaborators.
- Delete tests for deleted code. Do not skip or comment them out.
- Never add `skip` or `xfail` to get a suite green.
- Name tests for the behaviour in plain language. Test names do not reference plans, phases, or
  task numbers.
