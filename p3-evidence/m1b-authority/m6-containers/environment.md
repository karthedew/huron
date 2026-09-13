# M6 environment facts

Recorded before running any container-based suite.

## Commands run and output

### `which podman`
```
$ which podman
(no output)
exit: 1
```
Podman is not installed on this host.

### `sudo -n true`
```
$ sudo -n true
sudo: a password is required
exit: 1
```
Non-interactive sudo is unavailable; the current user cannot escalate to root without a
password prompt.

### `docker --version`
```
$ docker --version
Docker version 27.2.1, build 9e34c9b
exit: 0
```

### `id -u`
```
$ id -u
1000
exit: 0
```
The current user is not root (uid 1000).

### `docker ps` (before any suite)
```
CONTAINER ID   IMAGE     COMMAND   CREATED   STATUS    PORTS     NAMES
```
Empty — no containers running before this milestone's work started.

## Implications for M6

- `tests/contract/test_writer_exclusion.py` opens a disposable
  `PostgresContainer("postgres:16")` per test via `testcontainers`, which uses Docker
  directly. Docker is installed and reachable by this user (`docker ps` succeeds with no
  sudo), so the contract suite can run on disposable containers as required by plan rule 5.
- `tests/integration/test_protocol_cutover.py` runs `tests/controlled_deployment.py`
  through `_local_linux_invocation`, which on Linux requires either root or `sudo -n`
  (neither is available here) because the script itself provisions a private Podman
  engine (`tests/controlled_deployment.py:50,278`) and Podman is not installed on this
  host. This test therefore CANNOT run in this environment. This is an environment gap,
  not a code defect: the test, `tests/controlled_deployment.py`, and the M4.8 assertions
  it exercises are not modified, skipped, or xfailed to work around the gap.
- The recipe's file names `podman-before.log`/`podman-after.log` are kept per the plan's
  §5 evidence convention even though the command actually run is `docker ps` (Docker is
  the container runtime available and used here; Podman is not installed).

## Confirmation after running the suites

- `uv run pytest -q -m contract` (49 collected): 49 passed, exit 0. See `contract.log`/`contract.exit`.
  `test_identify_binds_cluster_and_database_and_refuses_a_foreign_fence` (the non-superuser
  `probe` identity test) is among the 49 passing tests. T4 §6.1's contingency (fallback
  query) was NOT triggered; branch (a) of T5b §2's decision rule applies: the primary
  `pg_control_system()` query ships as designed. No production code was changed.
- `uv run pytest -q -m integration -s` (14 collected): 1 failed, 13 passed, exit 1. The
  three Docker-based integration modules (`test_catalog_creation.py`,
  `test_catalog_descriptions.py`, `test_verified_raw_ingest.py`) passed. The failure is
  `tests/integration/test_protocol_cutover.py::test_actual_legacy_http_request_is_terminated_and_cannot_restart`,
  which invokes `tests/controlled_deployment.py` through `_local_linux_invocation`. Quoted
  evidence from `integration.log`:

  ```
  sudo: a password is required
  ...
  >           assert result.returncode == 0
  E           AssertionError: assert 1 == 0
  E            +  where 1 = CompletedProcess(args=['sudo', '-n', 'python3',
  '/home/karl/repo/huron/tests/controlled_deployment.py', 'provision', ...],
  returncode=1).returncode
  tests/integration/test_protocol_cutover.py:86: AssertionError
  ```

  This is the sudo/podman environment boundary described above (non-interactive sudo
  unavailable, Podman not installed), not a code defect. `tests/controlled_deployment.py`'s
  new M4.8 assertions (`validate` called twice, generation advance after a real SQL
  connection loss, pure refusal, `sequence == 2` on a fresh `prepare`, and the restart
  generation delta) remain UNEXECUTED on this host. Running them requires either a Linux
  root/`sudo -n` environment with Podman installed, or the macOS Podman-VM path the test
  also supports (`tests/controlled_deployment.py:50,278` and `_local_linux_invocation`'s
  counterpart for macOS). No test file was edited, skipped, or xfailed to work around this.
- `uv run pytest -q -m integration -s --deselect tests/integration/test_protocol_cutover.py::test_actual_legacy_http_request_is_terminated_and_cannot_restart`
  (the exact command used; `test_protocol_cutover.py` has exactly one test function, so this
  deselect collects cleanly): 13 passed, exit 0. See `integration-runnable.log`/`.exit`.
  This isolates "failed because of the environment" (the one deselected test) from "failed
  because of the code" (none — the runnable subset is fully green).
- `docker ps` was empty both before (`podman-before.log`) and after (`podman-after.log`)
  all suites; `docker ps -a` showed no `postgres:16` or testcontainers/Ryuk container
  attributable to this run — every disposable container the contract suite started was
  stopped and removed automatically (testcontainers' Ryuk reaper).
