# M1b independent verification attempt 2

**Functional: FAIL. Overall quality: FAIL.** Three independently reproduced evidence-finalization defects block M1b acceptance. Native duplication is separately below the unchanged 90 threshold under the user's authorized exception; it is not the reason for functional failure. No source, test, configuration or design files were edited by this verifier.

## Required corrections

1. **Large — failed pending-directory fsync leaves an installed record apparently usable.** `src/huron/pkg/rawstore/maintenance.py:150` unlinks the invalidation marker before `os.fsync(pending)` at line 151. If that fsync fails, `ProtocolCutover._ownership` (`src/huron/core/integrity/cutover.py:192`) propagates failure but the numbered record exists and the pending marker is absent. With the fence still valid, the documented validity predicate cannot distinguish this failed finalization from successful evidence. Reproduction `test_failed_pending_directory_fsync_must_not_leave_record_usable` injects failure at the real directory-fsync I/O boundary after actual unlink. Exact failure: `AssertionError: Failed finalization left installed record with no pending invalidator`. Redesign the durable completion/invalidation contract so every failure during marker clearance remains fail closed, including failures after the filesystem mutation; test restart/replay and consumer validity after this failure. Merely catching the error does not restore the invariant.

2. **Large — fence loss during final marker clearance returns success.** `_ownership` checks at `cutover.py:191`, clears at line 192, then `_record` returns and `prepare` stops its monitor (lines 111–114), without another proof check covering clearance. Reproduction `test_fence_loss_during_pending_clear_must_not_return_success` changes the actual injected exclusion boundary to invalid during the final `os.unlink`; the call returns a transition. Exact failure: `Failed: DID NOT RAISE <class 'ExceptionGroup'>`. Finalization must remain covered by exclusion, with loss during clearance preventing success and leaving evidence unusable even if the external fence later returns. Include before/after-clear and fsync-boundary tests; a post-check alone must not leave an unmarked failed record.

3. **Large — same-run concurrent invocations share and clear each other's pending ownership.** The `_pending` read at `cutover.py:120` is separated from the idempotent pending write at line 185. Two invocations can both pass admission, write identical marker bytes and independently remove that shared marker. Reproduction `test_concurrent_same_run_cannot_clear_another_live_installation` synchronizes database I/O so both enter, holds one real report write at the filesystem boundary, and observes the other return success with an installed numbered record and no pending marker while the held writer is still active. Exact failure: `AssertionError: One invocation cleared ownership while another writer remained live`. Establish exclusive ownership at the actual process/storage authority boundary, or reject conflicting invocations atomically, and prevent one invocation from finalizing another's work. Cover multiple service instances/processes, same-run retry, cancellation and interrupted-owner recovery while preserving immutable history. An instance-local lock does not prove this contract.

All three tests use the actual core workflow and MaintenanceStore, with fault/synchronization injection at filesystem, database and deployment I/O boundaries. Held work is released and awaited in `finally`. [Reproduction source](test_finalization_repro.py), [complete output](repro.log), [exit](repro.exit): **3 failed**, exit 1.

## Prior findings and review

All four attempt-1 reproductions now pass ([output](prior-reproductions.log)). Bidirectional ancestor/descendant bind exposure and relative/symlink refusal, live trusted Compose identity checking, behavioral CLI-to-wiring-to-storage tests, quoted-schema PostgreSQL effective privileges/unrelated grant preservation, and stale status prose were corrected. The previous continuous-exclusion finding is only partially fixed: the per-invocation loss latch and cancellation settlement address the earlier probes, but the new pending ownership/finalization design has the defects above.

Reviewed current plan/workflow, design and validation claims, the complete fix report/inventories, all four modified production modules and their affected tests, controlled deployment fixture, packaging/import and schema-map contracts. Prior M1b full legacy verification review remains applicable to unchanged source. No M1c startup/migration activation is required or certified here. Required legacy 0010 inspection remains narrow; source-only lint configuration and unchanged migration schema-map execution agree with the user's correction.

## Independent gates

| Command | Exit | Complete stdout/stderr |
| --- | --- | --- |
| `make lint` | 2 | [lint.log](lint.log) |
| `uv run ruff check src` | 0 | [ruff.log](ruff.log) |
| `uv run ruff format --check src` | 0 | [format.log](format.log) |
| `uv run pydoclint src` | 0 | [pydoclint.log](pydoclint.log) |
| `uv run ty check src` | 0 | [ty.log](ty.log) |
| `uv run mypy src` | 0 | [mypy.log](mypy.log) |
| `uv run lint-imports` | 0 | [imports.log](imports.log) |
| `uv run pytest --cov=src/huron --cov-report=term-missing` | 0 | [unit.log](unit.log) |
| `uv run coverage json -o p3-evidence/m1b/verification2/coverage.json` | 0 | [coverage.log](coverage.log) |
| `uv run radon cc src/huron --min C` | 0 | [radon-cc.log](radon-cc.log) |
| `uv run radon mi src/huron --min B` | 0 | [radon-mi.log](radon-mi.log) |
| `uv run complexipy src/huron --max-complexity-allowed 15` | 0 | [complexipy.log](complexipy.log) |
| `uv run --locked pyscn check src/huron` | 0 | [pyscn.log](pyscn.log) |
| `uv run --locked python scripts/check_duplication.py src/huron` | 1 | [duplication.log](duplication.log) |
| `make docs` | 0 | [docs.log](docs.log) |
| `git diff --check` | 0 | [diff-check.log](diff-check.log) |
| `uv run pytest -m contract` | 0 | [contract.log](contract.log) |
| `uv run pytest -m integration -s` | 0 | [integration.log](integration.log) |
| `make test-acceptance` | 0 | [acceptance.log](acceptance.log) |
| `uv run --locked pyscn analyze --json src` | 0 | [native-full.log](native-full.log) |
| `PYTHONPATH=. uv run pytest -q p3-evidence/m1b/verification1/test_review_repro.py` | 0 | [prior-reproductions.log](prior-reproductions.log) |
| `PYTHONPATH=. uv run pytest -q p3-evidence/m1b/verification2/test_finalization_repro.py` | 1 | [repro.log](repro.log) |

Unit suite: **1,606 passed**, 61 deselected, **95.84073416222617%** (6,475/6,756 statements; 281 unchanged baseline misses), meeting 95.84. All **17 M1b production files are 100%**. Contracts **46 passed**; integrations **14 passed**; full-size acceptance **1 passed**, unchanged 9 GiB / 144 × 64 MiB payload and required free-space precondition. Two existing dependency deprecation warnings are recorded in test logs. Radon CC C-or-higher and MI B-or-worse output is empty; cognitive maximum 15; Ruff, formatting, docstrings, both type checkers, all nine import contracts, schema-map, docs and diff checks passed.

`make lint` fails only at its native duplication gate; direct duplication command exits 1. Native **60/100**, **213/925** cloned fragments, **253 pairs**, **58 groups**. Fresh full analysis and both native clone reports cover exactly **132/132 source files**, zero skips, no complexity/dead-code/system error diagnostics. Default test/migration filename exclusions match no source file. Full raw reports: [full-src.json](full-src.json), [native-src.json](native-src.json), [native-src-huron.json](native-src-huron.json); independently validated inventory/counts: [native-inventory-validation.json](native-inventory-validation.json). Generic exploratory architecture/coupling scores in full analysis are not Huron's configured architecture gate; its nine explicit import contracts pass. No threshold, source exclusion or suppression was weakened.

## Identity, infrastructure and cleanup

Source inventory SHA-256: `0dedb64b30388547fd3220bc9a70890cb5f58813a2a66e1ad815d53aed31094b`. Independently checked all **132 source hashes** and **58 scoped file hashes** against fix1; all match before and after gates. All **115 prior production files remain unchanged**. [Identity and coverage](final-identity-coverage.json), [baseline comparison](baseline-comparison.json), scope/source/artifact checks accompany this report.

Real Linux controller integration passed using pinned historical application source and an actual built old image `sha256:bda3f52b6091ffc61a32d163b94e3fd7973c989c0c3660b135333e9f6b877ccc`. The `-s` transcript records healthy old API startup, admitted held HTTP upload, write continuing after SQL exclusion, controller termination/restart exclusion, and startup refusal for the same old identity after revocation. It also executes kernel UID refusal/grant, foreign descendant directory/file holders, generation change, unreachable controller and wired cutover checks. Historical artifact provenance and cleanup are preserved in [integration.log](integration.log), not inferred from a spoofed version or broken initial startup.

Podman startup/readiness and all service gates ran within one retained runner session using its discovered actual socket. No shared permission/SELinux policy was changed. Fixture `/var/lib/huron-controlled-test-0hp7s18m` was cleaned; final Linux check found no owned controlled-test/controller-test roots. Final container inventory contains only pre-existing unrelated containers. Both verifier runners and all reproduction tasks have finished; no verifier test/controller processes remain. [Container inventory](podman-final-containers.log), [Linux cleanup](linux-cleanup.log), [process snapshot](final-process-check.log). No production database or cutover was used, and no NFS durability or independently deployable M1b certification is claimed.
