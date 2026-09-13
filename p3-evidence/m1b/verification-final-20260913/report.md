# M1b final independent verification — 2026-09-13

**Verdict: PASS**, with the deployment-script integration node
`tests/integration/test_protocol_cutover.py::test_actual_legacy_http_request_is_terminated_and_cannot_restart`
explicitly excluded as unrunnable on this host, and the M1b criteria that depend on it
listed in §4/§5 as *not verifiable here*.

Scope: M1b of `P3_IMPLEMENTATION_PLAN.md` as a whole (implement items 1–7, the Tests
bullets, the Exit criterion), the `## Escalation` section and its `### Resolution`, plus
the authority work delivered under `P3_M1B_AUTHORITY_IMPLEMENTATION_PLAN.md` §7. This is
the cross-cutting pass that §7 requires before M1b can be called verified — not a
per-milestone check.

Tree: HEAD `e22d0003cfd97f0f75df01c04b3c493bef5eeaf8`, working tree as recorded in
`git-status.log`. No file outside this directory was created, edited, staged or reverted;
`git status --porcelain` is byte-identical before and after this pass, and the
`src/huron` + `tests` `.py` inventory hashes to
`ab6ba00916c6f4ce63f8007afde942b14e693ad334cbb2f7a597380f4c347d58` (listing digest of
`source-inventory.sha256`) both before and after. `.pyscn/reports/` gained two
tool-generated JSON reports as a side effect of running `pyscn check`, which the gate
requires; that directory is untracked pre-existing user state and its `git status` line is
unchanged.

Scratch adversarial tests were written under the session scratchpad only, never in the
repository; copies of their source are retained here as `scratch-adversarial-*.py.txt` and
their output as `scratch-adversarial.log`.
`p3-evidence/m1b/verification3/test_authority_repro.py` was read but neither edited nor
collected (`testpaths = ["tests"]`; the full `--co` count is 1741 and `p3-evidence/` never
appears).

## 1. Gate table (every command rerun by this verifier)

| # | Command | Exit | Log | Observed |
| --- | --- | ---: | --- | --- |
| 1 | `uv run ruff check src` | 0 | `ruff-check.log` | `All checks passed!` |
| 2 | `uv run ruff format --check src` | 0 | `ruff-format.log` | `132 files already formatted` |
| 3 | `uv run ty check` | 0 | `ty.log` | `All checks passed!` |
| 4 | `uv run mypy` | 0 | `mypy.log` | `Success: no issues found in 132 source files` |
| 5 | `uv run lint-imports` | 0 | `lint-imports.log` | all 9 contracts kept |
| 6 | `uv run pytest tests/unit --cov=src/huron --cov-report=term-missing --cov-report=json` | 0 | `unit.log`, `coverage.json` | **1677 passed**, TOTAL **95.92%** (6895 stmts, 281 missed) vs. floor `fail_under = 95.92` |
| 7 | `uv run radon cc src --min C` | 0 | `radon-cc.log` | empty |
| 8 | `uv run radon mi src --min B` | 0 | `radon-mi.log` | empty |
| 9 | `uv run complexipy src --max-complexity-allowed 15` | 0 | `complexipy.log` | pass |
| 10 | `uv run --locked pyscn check src` | 0 | `pyscn.log` | `Code quality check passed`; 253 clones informational; no dead-code or structural findings |
| 11 | `uv run --locked python scripts/check_duplication.py src` | 1 | `duplication.log` | **60/100** (required >= 90); cloned fragments **213/937**, pairs **253**, groups **58** |
| 12 | `make lint` | **2** | `lint.log` | every earlier step clean (ruff, ruff format, **pydoclint**, mypy, ty, lint-imports, **check_schema_map.py**, radon cc/mi, complexipy, pyscn); fails only at `check_duplication.py` |
| 13 | `make docs` | 0 | `docs.log` | `zensical build --strict` -> `No issues found` |
| 14 | `git diff --check` | 0 | `diff-check.log` | empty |
| 15 | `docker ps` (before) | 0 | `docker-before.log` | empty (no running containers) |
| 16 | `uv run pytest -q -m contract` | 0 | `contract.log` | **49 passed**, 1692 deselected, 138.37s (disposable `postgres:16` + testcontainers Ryuk) |
| 17 | `uv run pytest -q -m integration -s` | **1** | `integration.log` | **1 failed, 13 passed** — the single environment-gap node (§4) |
| 18 | `... -m integration -s --deselect ...::test_actual_legacy_http_request_is_terminated_and_cannot_restart` | 0 | `integration-runnable.log` | **13 passed** |
| 19 | `docker ps` / `docker ps -a` (after) | 0 | `docker-after-running.log`, `docker-after.log` | no running containers; `-a` shows only the same pre-existing, unrelated stopped containers present before |
| 20 | `df -h .` (before acceptance) | — | `df.log` | **37G available** (>= 25 GiB precondition met) |
| 21 | `make test-acceptance` | 0 | `acceptance.log` | **1 passed**, 1740 deselected, 52.04s (9 GiB interrupted/resumed multipart round trip) |
| 22 | `df -h .` (after) | — | `df-after.log` | 28G, then 37G after the cleanup in §1.1 |
| 23 | `--co` unit/contract/integration/acceptance | — | `collect.log` | `1677`; `49/1741`; `14/1741`; (acceptance `1/1741`) |

Duplication is the single authorized exception (`P3_IMPLEMENTATION_PLAN.md` escalation,
preamble rule 2). It is measured and reported, not gated: 60/100 against the unchanged 90
threshold. Against the M0 baseline (213/935, 253 pairs, 58 groups) only the *denominator*
moved (935 -> 937); the cloned numerator, pair count and group count are identical, so the
score did not worsen. No threshold, exclusion, suppression, skip or xfail was added: the
only `# type: ignore` in `src` is the pre-existing
`src/huron/applications/api/settings.py:169`, outside the M1b surface, and there are no
`# noqa`, `# pragma: no cover`, `@pytest.mark.skip` or `@pytest.mark.xfail` anywhere in
`src` or `tests`.

Coverage of the whole M1b surface is 100.0% line coverage with zero missing lines on every
file: `core/integrity/{models,ports,cutover,generations,verification}.py`,
`applications/lakectl/{controller,server,exclusion,main,settings,wiring,engine}.py`,
`pkg/metastore/maintenance.py`, `pkg/rawstore/{maintenance,inspection}.py`.

### 1.1 Acceptance temporary-root cleanup

`/tmp/pytest-of-karl` held `pytest-118/119/120` before the run and
`pytest-120/121/122` after. `pytest-121` is this acceptance run's own root
(`test_a_nine_gib_file_round_tri0`, **9.1G**, mtime 15:01:59); `pytest-122` is this
verifier's scratch pytest invocation (100K); `pytest-118` and `pytest-119` were swept by
pytest's own 3-root retention, not by this verifier. Only `pytest-121` was removed, after
`chmod -R u+w` (the committed revision tree is deliberately mode `555`/`444`). Receipt:
`acceptance-fixture-check.log`. `df -h .` returned to **37G**. No other
`pytest-of-karl` directory was touched.

## 2. ADR-0001 consequences -> production lines -> tests

Every consequence was re-derived from the code, not from the milestone reports. All node
ids below were run by this verifier: `adr-consequence-nodes.log` (25 passed) and
`adr-nodes.log` (160 passed across the eight M1b test modules).

| ADR consequence | Production lines that implement it | Test node ids (all run, all pass) |
| --- | --- | --- |
| **C1** Revocation has exactly one form — the generation advances before the refusal; no endorsement state durable or in memory; `certify`/`validate_certificate` collapse into one stateless `validate`; a lost reply is resolved by calling `validate` again; controller restart advances and forces a rescan | `controller.py:273-280` `_advance()`; `:299-305` `_observing()`; `:52-54` `__init__` loads state then `_advance()`; `:182-196` `validate`; `:307-308` `_live`. `ports.py:106-166` — the port has exactly `establish/check/abandon/validate`; no `_certificate`, `certify`, `validate_certificate` or `CertificationIndeterminateError` exists anywhere in `src` or `tests` (grep is empty) | `test_controller_epoch.py::test_complete_record_validates_repeatedly_and_a_restarted_controller_refuses_it`; `::test_lost_return_after_release_keeps_the_record_admissible`; `test_controller_transport.py::test_lost_reply_is_resolved_by_validating_again`; `::test_real_transport_validates_exact_durable_evidence` |
| **C2a** Every failed observation ends the epoch — volume identity, engine transport (connect, timeout, status), writer inventory, the PostgreSQL role fence and database identity, storage I/O under the maintenance claim, and cancellation during any of these | `controller.py:299-305` is one `try/except BaseException: self._advance(); raise` guard; every observation is inside it — `:93`, `:107`, `:129-133`, `:140-142`, `:159-162`, `:200-204`, `:210-212`. `engine.py:60-67` `_request` raises `httpx.*` including via `raise_for_status()`; `metastore/maintenance.py:123-125` `_require_identity`; `rawstore/maintenance.py:137-...` `claim()` | `test_controller_epoch.py::test_failed_observation_ends_the_epoch_before_the_refusal[engine_connect\|engine_inventory\|foreign_writer\|volume_identity\|database_identity\|sql_error\|sql_pool\|store_owner\|cancelled]` (9); `test_managed_controller.py::test_engine_failure_during_describe_or_restart_ends_the_epoch[describe\|restart]`; `::test_establish_mints_before_terminating_and_a_survivor_ends_the_new_epoch` |
| **C2b** A mismatched argument (wrong run, stored record, report digest, operator or peer) refuses the presented receipt and does **not** end the epoch | `controller.py:163-166` (`_live`, operator) and `:193-194` (`run_id`) sit **outside** `_observing`; `:205-209` compares stored bytes and the report binding; `models.py:270-293` `validate_inventory` re-binds and compares whole | `test_controller_epoch.py::test_mismatched_receipt_is_refused_without_ending_the_epoch[peer\|operator\|run\|absent\|record\|report]` (6) — each asserts `generation_on_disk == record.fence.generation` and then re-validates successfully |
| **C3** The fence binds `<system_identifier>/<database_oid>/<datname>`, captured at `establish` via `DatabaseExclusion.identify()` and compared by the adapter at every database observation (client fence check, `exclude`, controller `validate`); private maintenance settings loaded once at start, never digested or emitted; restoring the old database stays invalid | `metastore/maintenance.py:11-15` `_IDENTITY_SQL`; `:48-61` `identify()`; `:123-125` `_require_identity`; `:80` first statement of `exclude`'s transaction; `:107` first statement of `check`. `controller.py:132-133` captures at `establish`; `:46` `MaintenanceSettings.load` once in `__init__`; `:214-217` `_database()` builds the pool from that one load. `models.py:154` `FenceEvidence.database` required with a strict pattern. `cutover.py:143` `exclude(evidence)`, `:228` `_Fence.check` -> `roles.check(self.evidence)`, `controller.py:212` `validate` -> `roles.check(transition.fence)` | `test_maintenance_adapters.py::test_role_adapter_identifies_the_primary_and_refuses_an_empty_identity`; `::test_role_adapter_refuses_a_foreign_fence_before_any_role_change[exclude\|check]`; `::test_role_adapter_observes_identity_before_every_role_statement`; `test_controller_epoch.py::test_failed_observation_ends_the_epoch_before_the_refusal[database_identity]`; contract `tests/contract/test_writer_exclusion.py::test_identify_binds_cluster_and_database_and_refuses_a_foreign_fence` (real PostgreSQL 16) |
| **C4** Every `prepare` appends a new report/record pair at the next sequence; report and record share the number; nothing is reused; a stranded report or record is history; `run_id` is only the audit/idempotence key | `cutover.py:187-192` `_next_sequence` -> `reports/{N:06d}.json` then `{N:06d}.json`; `:195-206` `_next_sequence`/`_occupied` scan both directories under the claim; `models.py:238-265` `bind` derives `report_path` from `sequence` | `test_integrity_cutover.py::test_cutover_writes_bound_report_before_record_and_a_second_run_appends`; `::test_stranded_report_is_history_and_retry_appends`; `::test_lost_fence_during_installation_retains_unusable_history_and_allows_fresh_scan[report\|record]`; `test_controller_epoch.py::test_interrupted_prepare_ends_the_real_controllers_epoch[post_install_fsync\|release_fence_loss]` (asserts `sequence == 2` and the earlier record's bytes are untouched) |
| **C5** Any failure after `establish` ends the epoch through `abandon(evidence)`, which advances only when the evidence names the live epoch; residual windows documented, not closed | `cutover.py:107` `async with self._abandoning(evidence)`; `:130-137` `_abandoning` swallows its own failure and re-raises the original; `controller.py:168-180` `abandon` = `authenticate` then `if self._live(evidence): self._advance()`, with no observation | `test_controller_epoch.py::test_abandon_ends_only_the_live_epoch`; `::test_interrupted_prepare_ends_the_real_controllers_epoch[...]`; `test_managed_controller.py::test_check_and_abandon_refuse_before_any_epoch_is_established`; `test_integrity_cutover.py::test_exclusion_loss_at_ownership_release_cannot_return_a_receipt[False\|True]` |
| **C6** `prepare` takes the storage claim **before** `establish`; the kernel lock is the coordinator mutex and the epoch is the writer mutex, so a second coordinator is refused without ending the first's epoch | `cutover.py:105-111` — `with self._storage.claim():` then `establish`, and `validate(result)` deliberately outside the claim (the controller's `_validate_evidence` takes its own claim at `controller.py:202`); `rawstore/maintenance.py:137-...` `claim()` is `O_NOFOLLOW\|O_NONBLOCK` `flock` on `protocol/.maintenance.lock` | `test_integrity_cutover.py::test_independent_cutovers_cannot_share_a_live_same_run_owner`; `test_controller_epoch.py::test_failed_observation_ends_the_epoch_before_the_refusal[store_owner]` |
| **C-restart** The controller mints generation 1 at every start and never issues it; the first `establish` mints 2 | `controller.py:52-54`; `:250` fresh state starts at `generation=0` | `test_managed_controller.py::test_controller_persists_exclusion_before_termination_and_refuses_restart` (asserts `generation_on_disk == 1` at start); `::test_establish_mints_before_terminating_and_a_survivor_ends_the_new_epoch` |

## 3. Re-derivation of the three verification-3 findings

Each answer is derived from the code, then probed with a scratch adversarial test written
in the scratchpad (`scratch-adversarial.log`: **11 passed**). No probe found any way to
admit stale evidence.

### 3.1 An observed engine transport failure advances the generation before the refusal, and the receipt is never admitted again

Derivation. `LocalEngine._request` (`engine.py:60-67`) raises `httpx.ConnectError`,
`httpx.ReadTimeout` and — through `response.raise_for_status()` — `httpx.HTTPStatusError`.
The controller no longer classifies exceptions at all: `_observing()`
(`controller.py:299-305`) is a bare `except BaseException: self._advance(); raise`, and
every engine call in `restart`, `describe`, `establish`, `check` and `_validate_evidence`
is inside it (`:93, :107, :129, :140, :159, :200, :210`). `_advance()` (`:273-280`)
persists first and only then assigns, so the refusal is reported after the write attempt.
`_live()` (`:307-308`) compares the presented receipt against `_evidence()`, which reads
the advanced generation — so the receipt is dead on every later `check`/`validate`,
including after the engine recovers.

Receipts. `test_failed_observation_ends_the_epoch_before_the_refusal[engine_connect]` and
`[engine_inventory]` assert `generation_on_disk == fence.generation + 1` **after the
monkeypatch context exits** (i.e. after the engine recovers) and then that a second
`validate` raises `"controller exclusion generation changed"`.
`test_engine_failure_during_describe_or_restart_ends_the_epoch[describe|restart]` covers
the two non-cutover operations.

Scratch probe added: the ADR names "status" explicitly but the repo matrix parametrizes
only connect and timeout. `test_http_status_error_ends_the_epoch` injects a real
`httpx.HTTPStatusError(500)` — the epoch ends and the receipt is refused afterwards.
**No defect; see finding Q5 for the test-coverage nit.**

### 3.2 A changed maintenance database identity is observed at establish, at the client fence check and at validate, and restoring the old database does not revive the receipt

Derivation. Three observation points, all reached:

1. **`establish`** — `controller.py:132-133` opens `_database()` and calls
   `roles.identify()` *before* `_advance` mints; the value is stored on the state (`:138`)
   and emitted in the receipt (`:320`). `identify()` (`metastore/maintenance.py:48-61`)
   runs `_IDENTITY_SQL`, which also refuses a standby (`NOT pg_is_in_recovery()` -> `NULL`
   -> `ValueError("maintenance database is not a primary")`).
2. **The client fence check** — `cutover.py:228` `_Fence.check` calls
   `roles.check(self.evidence)`; `PostgresRoleExclusion.check` (`:107`) runs
   `_require_identity` as its first statement, before any role probe. `exclude` does the
   same at `:80`, inside the transaction and before any `ALTER ROLE`.
3. **`validate`** — `controller.py:210-212` opens `_database()` inside `_observing` and
   calls `roles.check(transition.fence)`.

The settings are read once (`controller.py:46`) and never digested or emitted;
`private_document` (`settings.py:133-154`) is the only reader and its contract says the
bytes are never emitted as evidence. A configuration edit therefore takes effect only at
restart, and restart advances the generation. A *live* identity change is an observation
failure inside `_observing`, so the generation moves before the refusal; restoring the old
database cannot help because the comparison is against the already-advanced generation,
not against the database.

Receipts. `test_failed_observation_ends_the_epoch_before_the_refusal[database_identity]`
restores the identity when the monkeypatch context exits and still gets
`"generation changed"`. `test_role_adapter_refuses_a_foreign_fence_before_any_role_change[exclude|check]`
proves the identity check precedes every role statement.
`test_role_adapter_observes_identity_before_every_role_statement` pins the ordering.
The real-PostgreSQL receipt is
`tests/contract/test_writer_exclusion.py::test_identify_binds_cluster_and_database_and_refuses_a_foreign_fence`,
which ran green in this pass's contract suite (49 passed) — confirming review E.5 item 1
(`pg_control_system()` is executable by the non-superuser `probe` role), so the
contingency query was never needed.

### 3.3 There is no operation, RPC or CLI path by which an authorized maintenance caller can re-admit a revoked receipt without a fresh `prepare`

**The complete RPC surface** is `server.py::_dispatch` (`:74-95`), gated by
`_require_request_fields` (`:98-110`) which rejects any operation not in its table and any
request whose field set differs exactly:

| Operation | Controller method | Can it create admissibility? |
| --- | --- | --- |
| `authenticate` | `controller.py:56-74` | No — returns a grant; touches no state. |
| `describe` | `:97-115` | No — observes only; a failure ends the epoch. |
| `restart` | `:76-95` | No — and it is *refused outright* while `state.run_id is not None` (`:91`), which stays set for the life of the state. |
| `establish` | `:117-145` | It mints a **new** epoch (`_advance` at `:134`), which makes every earlier receipt inadmissible. It cannot revive one. |
| `check` | `:147-166` | No — `_live` refuses a receipt naming any other generation. |
| `abandon` | `:168-180` | Only *ends* epochs, and only when `evidence == self._evidence()`. |
| `validate` | `:182-196` | Admits only under `_live` plus fresh observations. |

There is no eighth branch: `_dispatch` falls through to `check`/`abandon` only after
`_require_request_fields` has already confirmed the operation is one of the seven.
`certify`, `validate_certificate` and `CertificationIndeterminateError` do not exist
anywhere in `src` or `tests`. The server test
`test_server_refuses_malformed_oversized_and_actor_supplied_requests` is parametrized with
a `{"operation":"certify",...}` payload and asserts `CONTROLLER_REFUSED`.

**The complete CLI surface** is `main.py:340-354`: `lakectl controller --config`,
`lakectl restart --socket`, and `lakectl protocol cutover` with a *required mutually
exclusive* `--prepare`/`--validate` group plus the cross-check at `:356-360`
(`--prepare` takes `--run-id`, `--validate` takes `--sequence`). `--prepare` is
`wiring.prepare` -> `CutoverService.prepare`, which always performs the full scan.
`--validate` is `wiring.validate` (`:44-58`) -> reads `protocol/{N:06d}.json` ->
`CutoverService.validate` -> `ControllerClient.validate` -> the same stateless controller
`validate`. Neither path can admit a receipt whose fence names an ended epoch.
`ControllerClient` (`exclusion.py`) exposes exactly the seven RPCs and nothing else.

**Scratch adversarial probes** (`scratch-adversarial.log`, all passed):

| Probe | Attempt | Outcome |
| --- | --- | --- |
| A1 | `establish` a fresh epoch, then present the previously admitted record | `ValueError: controller exclusion generation changed` |
| A2 | Forge a record whose `fence` is edited to the live generation while the bound report is not, write it over `protocol/000001.json`, present it | `ValueError: protocol record disagrees with its inventory` (`validate_inventory` re-binds and compares whole, `fence` included) |
| A3 | `abandon` with a receipt one generation stale, then `validate` | abandon is a no-op, generation unchanged, the live record still admits |
| A4 | `abandon` with a receipt naming a foreign operator under the live generation | no-op; the live record still admits |
| A5 | `abandon` the live receipt, then `check` and `validate` | both `"generation changed"` |
| A6 | Complete a real `prepare`, restart the controller, then `validate` through the restarted controller | `"generation changed"`; the on-disk generation advanced by exactly 1 |
| A7 | Second coordinator contends for the storage claim during a live `prepare` | `BlockingIOError`; the first coordinator's `prepare` completed and its record still validates (C6 holds) |
| A8 | Make `_persist` itself fail during an epoch-ending observation, then recover | the refusal is still raised, the receipt is refused afterwards by the live object, and a restart advances the disk generation (2 -> 3) and refuses again — see Q1 |
| A9 | Swap the bound report for a different *valid* report under the live epoch | `ValueError: protocol record disagrees with its inventory` |
| extra | Inject `httpx.HTTPStatusError(500)` during an observation | epoch ends on disk; receipt refused afterwards |
| extra | Probe the operator contract's "refuses every request" claim after a failed persist | `authenticate` and `describe` still answer — see Q2 |

**No way to admit stale evidence was found.** The one residual — a trusted maintenance
operator who can write both `protocol/reports/{N}.json` and `protocol/{N}.json` can
manufacture a self-consistent pair under a live epoch — is exactly the threat the ADR
excludes in its "Considered options" ("bytes cannot prove when exclusion held, and the
cutover operator who would present the signature is the same trusted operator who writes
both files") and that `docs/operations/controlled-cutover.md` places outside the
application-writer threat model. It is recorded in §7 as a residual risk, not a finding.

## 4. The unrunnable deployment-script node

`tests/integration/test_protocol_cutover.py::test_actual_legacy_http_request_is_terminated_and_cannot_restart`
was **run**, not skipped, xfailed or modified. Exact failure (`integration.log`):

```
sudo: a password is required
...
>           assert result.returncode == 0
E           AssertionError: assert 1 == 0
E            +  where 1 = CompletedProcess(args=['sudo', '-n', 'python3',
'/home/karl/repo/huron/tests/controlled_deployment.py', 'provision', '...',
'/home/karl/repo/huron/.pytest_cache/controlled-lo2n4n6g/legacy.tar'], returncode=1).returncode

tests/integration/test_protocol_cutover.py:86: AssertionError
1 failed, 13 passed, 1727 deselected, 2 warnings in 13.57s
```

Host probes rerun by this verifier: `sudo -n true` -> `sudo: a password is required`,
exit 1; `which podman` -> no output, exit 1; `docker --version` ->
`Docker version 27.2.1, build 9e34c9b`, exit 0. `_local_linux_invocation`
(`test_protocol_cutover.py:97-105`) requires `os.geteuid() == 0` or passwordless
`sudo -n`, and `tests/controlled_deployment.py` provisions a **private Podman** engine.
Neither is available here.

**M1b criteria that depend on this node and remain NOT VERIFIED on this host:**

1. **Old-artifact restart under revoked credentials.** M1b Tests bullet 2 ("Old release
   restart uses the actual old application artifact and revoked identity. Observe failed
   readiness/write access; do not spoof old version input to new startup code. Pin the
   pre-change artifact digest in the test fixture."). The pin exists
   (`_LEGACY_COMMIT = db5fc84...`, `_LEGACY_ARCHIVE_SHA256 = b1ad409f...`,
   `test_protocol_cutover.py:18-19,45`); the assertion
   `LEGACY_REVOKED_IDENTITY_STARTUP_REFUSED` (`controlled_deployment.py:431`) is
   unexecuted.
2. **Real process termination of a live writer.** M1b implement item 1 ("confirmed process
   termination") and Tests bullet 1 ("an old request that already passed its database
   check ... needs process shutdown evidence"). The assertions
   `LEGACY_HTTP_UPLOAD_ADMITTED`, `LEGACY_HTTP_WRITE_SURVIVED_SQL_FENCE` and
   `LEGACY_WRITER_TERMINATED_RESTART_EXCLUDED` are unexecuted. `LocalEngine.terminate`
   (`engine.py:105-120`) has unit coverage but no real-daemon receipt on this host.
3. **Real SQL-loss generation advance against a live PostgreSQL and a live controller
   process.** `controlled_deployment.py:496-515`: `ALTER ROLE new_app LOGIN` -> `validate`
   refused -> `_generation_on_disk(settings) == fence.generation + 1` -> `ALTER ROLE
   new_app NOLOGIN` -> still refused -> fresh `prepare` allocates `sequence == 2`. The
   in-process equivalents pass (`[database_identity]`, `[sql_error]`,
   `test_stranded_report_is_history_and_retry_appends`), but the cross-process one does
   not run.
4. **Restart delta across a real controller process.**
   `controlled_deployment.py:524-535`: `before = _generation_on_disk(settings)`, kill and
   relaunch the controller, `assert _generation_on_disk(settings) == before + 1`, then
   `check` refused, then an unreachable controller refused with `OSError`. In-process
   equivalents pass; the cross-process one does not run.
5. Also unexecuted here: the two `FOREIGN_DESCENDANT_WRITER_REFUSED` receipts and
   `CONTROLLER_FOREIGN_GENERATION_UNREACHABLE_REFUSED`, and the fixture's own real
   cleanup path.

A root (or passwordless-`sudo`) Linux host **with Podman installed**, or the macOS
Podman-VM path the same script supports, must still prove all five. The previous
verification-3 pass did execute this node on a Podman VM against the *pre-authority*
tree; it has never been executed against the current tree.

## 5. M1b acceptance criteria, item by item

| # | Criterion (`P3_IMPLEMENTATION_PLAN.md` M1b) | Status | Evidence |
| --- | --- | --- | --- |
| 1 | `WriterExclusion` port: authenticated operator/root identity, current writer inventory, termination and continuous restart/access exclusion evidence; controller-managed Compose first; unmanaged host writers and unreachable nodes are refusal; container absence never equals complete inventory | **Met (local)**; the *real termination* half is not verifiable here (§4 item 2) | `ports.py:106-166`; `controller.py:56-95, 117-166, 219-234`; `engine.py:69-79` uses `all=true`; `_exposes`/`_require_isolated_container` (`:338-353`). Tests: `test_managed_controller.py::test_complete_inventory_refuses_unmanaged_storage_and_host_authority` (10 params), `::test_engine_failure_during_describe_or_restart_ends_the_epoch`, `::test_controller_persists_exclusion_before_termination_and_refuses_restart` |
| 2 | Dedicated app/cutover DB identities separate from the development owner; disabled old login, no surviving sessions, effective access through inheritance/ownership, new-role exclusion; old binaries never get new credentials; tested against real PostgreSQL | **Met** for the SQL half (real PostgreSQL 16, contract suite 49 passed); **not verifiable here** for "old binaries never receive new credentials" (§4 item 1) | `metastore/maintenance.py:63-120, 143-198`; `deploy/controlled/roles.sql`. Tests: `tests/contract/test_writer_exclusion.py` (6 tests incl. `test_effective_public_and_inherited_write_paths_invalidate_exclusion`, `test_database_owner_and_administrative_roles_are_not_eligible_application_identities`, `test_identify_binds_cluster_and_database_and_refuses_a_foreign_fence`) |
| 3 | Full legacy verification streams every payload and validates document bytes, names, identity, seal, owner and regular-file link count; reports missing/corrupt accurately; imports use trustworthy identity only | **Met** | `core/integrity/verification.py`; `pkg/rawstore/maintenance.py:85-110, 286` (`st_nlink != 1`), `inspection.py`. Tests: `test_legacy_verification.py`, `test_integrity_storage.py::test_shared_inode_and_link_targets_are_never_certified`, `test_rawstore_inspection.py` |
| 4 | Canonical per-revision report entries and root/run identity; reports bound to numbered records by digest; report fsynced before record; exact membership determines VERIFIED; corruption recorded without certifying | **Met** | `models.py:96-143, 172-293`; `cutover.py:154-212`; `rawstore/maintenance.py:112-135` + `materialize.install`. Tests: `test_protocol_documents.py` (23), `test_integrity_cutover.py::test_cutover_writes_bound_report_before_record_and_a_second_run_appends`, `::test_corrupt_revision_does_not_prevent_exact_healthy_population_certification` |
| 5 | Narrowly scoped maintenance adapter for schema 0010; resolves legacy sessions and writes audit/findings before migration; not an API fallback | **Met** | `pkg/metastore/legacy.py:1, 166-169` (refuses anything but `0010_independent_raw`). Tests: `test_maintenance_adapters.py::test_legacy_adapter_reads_exact_hierarchy_paths_and_trusted_records`, `::test_legacy_resolution_preserves_findings_and_refuses_identity_races` |
| 6 | Process-exclusive storage ownership through settled writes; the controller's persisted generation is the verification epoch (ADR-0001); `establish` mints, every failed observation/`abandon`/restart ends it; stateless `validate` admits only a record naming the live generation and bound database identity; file presence never establishes admission; a lost reply is resolved by validating again | **Met** | §2 and §3 in full; `rawstore/maintenance.py:137-...` `claim()`; `cutover.py:241-251` `_settled_write`. 25 epoch node ids + 11 adversarial probes |
| 7 | Authenticated maintenance grants in core; CLI actor text alone cannot authorize certification; report evidence without credentials or file contents | **Met** | `models.py:158-163` `MaintenanceGrant`; `cutover.py:102-104, 123-127`; `main.py` has no actor argument and `:372-377` prints one fixed refusal line. Tests: `test_integrity_cutover.py::test_cutover_requires_an_authenticated_root_and_operation_grant`, `::test_consumer_requires_exact_root_and_operator_authority[root\|actor\|grant\|operation]`, `test_lakectl_main.py::test_command_failures_do_not_echo_connection_material` |
| T1 | SQL role rejection and termination tested separately from an old request that already passed its database check | **Partially met**: the SQL half is proven on real PostgreSQL; the "request past its database check" half needs process-shutdown evidence — **not verifiable here** (§4 item 2) | contract suite; `controlled_deployment.py` `LEGACY_HTTP_WRITE_SURVIVED_SQL_FENCE` unexecuted |
| T2 | Old release restart uses the actual old artifact and revoked identity; pinned digest | **Not verifiable here** (§4 item 1) — the fixture and digest pin exist and were read | `test_protocol_cutover.py:18-19, 45` |
| T3 | Foreign writer/startup, unreachable node, lost DB fence, changed database identity or lost proof mid-scan end the epoch; the record is refused afterwards even if the condition is restored | **Met** | `test_failed_observation_ends_the_epoch_before_the_refusal` (9 faults, each asserting refusal *after* the fault is removed); `test_integrity_cutover.py::test_observed_fence_loss_stays_invalid_after_external_observations_recover`; `::test_periodic_fence_loss_interrupts_an_incomplete_scan`; `::test_concurrent_observations_cannot_replace_a_lost_fence_with_recovered_state` |
| T4 | A report without its record is history; the next `--prepare` appends the next sequence number; any epoch end forces a full rescan | **Met** | `test_integrity_cutover.py::test_stranded_report_is_history_and_retry_appends`; `::test_failed_directory_sync_leaves_a_complete_record_that_no_epoch_admits`; `test_controller_epoch.py::test_interrupted_prepare_ends_the_real_controllers_epoch[...]` |
| T5 | Corrupt legacy payload is reported DEGRADED without blocking healthy inventory; ambiguous identity/missing parent blocks certification | **Met** | `test_integrity_cutover.py::test_corrupt_revision_does_not_prevent_exact_healthy_population_certification`; `test_integrity_generations.py::test_catalog_ambiguity_and_stale_acknowledged_state_block_certification`; `test_legacy_verification.py` orphan-certification test |
| Exit | The adapter has an enforceable complete deployment contract; if only local test evidence exists, record that limit and refuse unsupported deployment certification; no fabricated production readiness | **Met as documented; the enforcement receipt is incomplete on this host** | `docs/operations/controlled-cutover.md` states the supported boundary, the unsupported development stack and the disposable-evidence limit; `P3_IMPLEMENTATION_PLAN.md` M1b closing paragraph and `P3_DESIGN.md` §5.1 repeat it; no document in the tree claims production readiness or M1c delivery. §4 records exactly which enforcement evidence is unexecuted here |

Also confirmed against `P3_M1B_AUTHORITY_IMPLEMENTATION_PLAN.md` §7: the three
verification-3 behaviours are refused (§3); `certify`, `validate_certificate`,
`CertificationIndeterminateError`, endorsement state, same-run reuse and every
two-parameter `exclude`/`check` are gone from `src` and `tests`; the fence carries
`database`; both protocol schemas equal the model under unchanged `$id`s
(`test_protocol_documents.py` asserts byte equality and passes); every `prepare` appends
`reports/{N:06d}.json` and `{N:06d}.json`; suite counts are unit 1677 / contract 49 /
integration 14 collected; the coverage floor is `95.92` and the measured total is
95.92458%, so the ratchet is already at its floored value and nothing needed raising.

## 6. Code-quality findings

None of these is a functional defect or a gate failure. Small findings are still findings.

| # | Severity | Location | Finding |
| --- | --- | --- | --- |
| Q1 | Minor (accuracy of an invariant) | `controller.py:273-280`; ADR-0001 C1; `P3_DESIGN.md` §5.2; `docs/operations/controlled-cutover.md` "Verification epoch" | The stated invariant is "the generation advances **on disk** before the refusal is written". `_advance` is `try: self._persist(advanced) finally: self._state = advanced`, so when the state write itself fails the **in-memory** generation advances and the disk one does not. Probe A8 confirms: disk stayed at 2 while the refusal was raised, the receipt was refused by the live object, and a restart then advanced the disk generation 2 -> 3 and refused again. The safety property holds (the disk generation is never below any issued receipt's, so a restart always overtakes it), but the load-bearing reason — *the unconditional in-memory advance in the `finally`* — carries no comment, which the engineering standard reserves precisely for invariants like this. Suggested correction: one comment at `_advance` naming the invariant, and wording in the ADR/design/ops doc that says "advances the generation before the refusal, on disk when the state write succeeds and in memory unconditionally; a restart re-advances from disk". |
| Q2 | Minor (documentation) | `docs/operations/controlled-cutover.md`, "Verification epoch", last sentence | "If the controller cannot persist an advance it refuses every request until it is restarted." Probed directly: after a failed persist, `authenticate` and `describe` both still answer normally (`scratch-adversarial.log`). Only the generation-comparing operations (`check`, `validate`) and `restart` refuse. Reword to name those operations. |
| Q3 | Minor (design clarity / OOP) | `controller.py:91` vs. `:307-308` | Two different sentinels answer the same question, "has an epoch ever been established": `restart` tests `self._state.run_id is not None`, `_live` tests `self._state.database is not None`. They are set together by the same `_advance` call, so the behaviour is correct, but a reader has to prove that. `_live`'s guard exists because `_evidence()` would raise a `ValidationError` on `database=None`; that reason is invisible. One named predicate (or one sentinel plus a comment) would remove the ambiguity. |
| Q4 | Minor (typing) | `controller.py:273` | `def _advance(self, **changes: object)` types a keyword set that is in fact exactly `{run_id, operator, writers, database}`, and `model_copy(update=...)` bypasses pydantic validation. A frozen `ControllerState` is the invariant holder; an untyped `**changes` into `model_copy` is the one place that can put an unvalidated value on it. Explicit optional parameters, or constructing the successor state directly, would let `mypy`/`ty` check the four field names. |
| Q5 | Minor (test coverage vs. the ADR text) | `tests/unit/test_controller_epoch.py:193-206` | ADR-0001 C2 names engine transport failures as "(connect, timeout, **status**)". The matrix parametrizes `engine_connect` (`httpx.ConnectError`) and `engine_inventory` (`httpx.ReadTimeout`) but no `httpx.HTTPStatusError`, which is the class `LocalEngine._request`'s `raise_for_status()` actually produces and the only one of the three not raised by the transport layer. The behaviour is correct (this verifier's scratch probe confirms the epoch ends), but the ADR clause has no committed receipt for its third named case. One more matrix parameter closes it. |
| Q6 | Minor (retired vocabulary) | `tests/unit/test_integrity_cutover.py:360` | Docstring: "Installed bytes remain forensic history until a complete new preparation is **endorsed**." "Endorsed" is the retired authority vocabulary the clean sweep removed everywhere else; the correct word here is "admitted"/"validated". This is the only surviving instance in `src`/`tests`. (The `ProtocolInventory.certifies` / "certification" vocabulary elsewhere is the *legacy-membership* domain term from M1b item 4, not the deleted controller endorsement, and is correct.) |
| Q7 | Minor (test hygiene) | 18 findings across 7 M1b test files | Lint scope is `src/` only by the user's direction, so this is not a gate failure — but the testing standard says test files are held to the same quality bar as production code. `uv run ruff check tests` reports 22 findings tree-wide, **18 of them in files M1b touched**: `E501` over-long lines at `test_controller_epoch.py:1,299`, `test_managed_controller.py:191` (118 chars), `test_controller_transport.py:248,252,253,282,286,287`, `test_integrity_cutover.py:15,560`, `test_writer_exclusion.py:52`; `I001` unsorted import blocks at `test_controller_epoch.py:3`, `test_controller_transport.py:243,276`, `test_integrity_cutover.py:3`, `test_lakectl_main.py:3`. The pre-existing baseline in untouched test files is 4 findings. |
| Q8 | Minor (annotation hygiene) | `tests/controlled_deployment.py:564` | `F821 Undefined name 'ControllerSettings'` — `_generation_on_disk(settings: ControllerSettings)` annotates a name imported only inside `_socket_cutover`. Not a runtime bug: the module has `from __future__ import annotations`, and this verifier confirmed the module imports cleanly with the annotation left as the string `'ControllerSettings'`. Still an unresolvable annotation; a `TYPE_CHECKING` import at module level fixes it. |

Checked and **clean**: no leftover `certify`/`validate_certificate`/`_certificate`/
`CertificationIndeterminateError` in `src` or `tests`; no plan, phase, milestone or task
references in any `src`/`tests` file; no `TODO`/`FIXME`/`XXX`/`HACK`; no
`# noqa`/`# pragma: no cover`/`@pytest.mark.skip`/`@pytest.mark.xfail` anywhere, and the
only `# type: ignore` in `src` is pre-existing and outside the M1b surface; **no
private-attribute reads in any M1b test** (the durable generation is read through
`ControllerState.model_validate_json` in `generation_on_disk`; the two private-attribute
reads that exist in `tests/` are in unrelated, untouched modules); `pyscn check` reports
no dead code; no nondeterminism (no wall-clock, network, unseeded randomness or ordering
dependence — the clock is injected, the engine and SQL boundaries are the only doubles,
and the fixtures use `monkeypatch.context()` and `ExitStack`); `radon`, `complexipy` and
the import-linter contracts are clean; `core` still imports no concrete adapter (the
`DatabaseFence` structural Protocol in `pkg/metastore/maintenance.py:18-34` keeps `pkg`
free of a `core` import, and `lint-imports` confirms the
`applications -> core -> pkg -> schema` layering).

## 7. Residual risks

1. **The five deployment-script proofs in §4 have never been executed against this tree.**
   The in-process equivalents are strong (a real `ManagedComposeController` over a real
   `MaintenanceStore` on a real filesystem, with only the engine HTTP and SQL boundaries
   doubled), but process termination, an old artifact's startup under revoked credentials,
   and the cross-process restart/SQL-loss generation deltas are unproven here. M1b's Exit
   criterion is met only in its "record that limit" sense.
2. **A trusted maintenance operator can manufacture a self-consistent report/record pair
   under a live epoch** (probes A2/A9 show the *inconsistent* forgeries are refused, but a
   consistent re-bind is not detectable from bytes). ADR-0001 rejects signing for exactly
   this reason and the operator contract places that operator outside the threat model.
   Unchanged by this pass; recorded so it is not mistaken for something the epoch closes.
3. **The persist-failure window (Q1).** The invariant survives, but its proof lives in an
   uncommented `finally` and that branch has no committed test. A future refactor that
   moved the assignment inside the `try` would silently break admissibility after a failed
   state write, and nothing in the suite would notice.
4. **Residual epoch windows are bounded, not closed** — an unobserved writer loss between
   two fence checks, an `abandon` that fails against a live controller, and a client that
   dies before sending one. Documented in ADR-0001, `P3_DESIGN.md` §5.2 and the operator
   contract's "Residual windows" note; no test, by design (review E.5 item 7).
5. **`pg_is_in_recovery()` standby refusal is still unexercised** (review E.5 item 2): the
   predicate ships in `_IDENTITY_SQL` and its `NULL` -> `ValueError` path has unit
   coverage, but no standby fixture exists. `pg_control_system()` under a non-superuser
   *is* now proven on real PostgreSQL 16 (E.5 item 1 closed).
6. **Native duplication remains 60/100 against a 90 threshold.** Authorized exception;
   unchanged in substance from the M0 baseline; `make lint` therefore exits 2 and this is
   not a clean CI gate.
7. **`restart` is permanently excluded once any `establish` has run**, because `run_id` is
   never cleared and `abandon` deliberately does not un-fence. This is the documented
   contract (`ports.py:139-152`), not a defect — noted because an operator reading only the
   CLI help would not expect `lakectl restart` to be dead for the life of the state.

## 8. Cleanup and provenance

No commit, push, activation, deployment, production database or service change, and no
nested delegation. `make up`/`make stack` were never run. Containers: `docker ps` was
empty before, empty between the contract and integration suites, and empty after;
`docker ps -a` after shows only the same pre-existing, unrelated stopped containers that
were present before. The contract suite's disposable `postgres:16` containers and their
testcontainers Ryuk reaper started and exited within the run; nothing this pass started
remains. The acceptance run's own 9.1 GiB tmp root was removed (§1.1) and no other
`pytest-of-karl` directory was touched. `df -h .` is back to 37G.

This report records an independent rerun of every gate command on the current tree. It
does not certify NFS, production deployment, M1c, or P3.
