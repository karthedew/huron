# M1b corrective implementation — attempt 3 / fix pass 2

**Local functional validation: PASS.** All three requested corrections are implemented and tested. Independent verification attempt 3 of 3 is pending. This report does not claim M1c activation, independent deployability, P3 completion or a clean native quality gate.

## Contract correction

All three verifier2 findings shared one defect: absence of a removable pending file was being treated as authoritative completion. That mechanism, `clear_pending`, and its marker-specific tests were removed. Restoring a marker after failed I/O is not the replacement contract.

1. **Mutation followed by failure.** Report and numbered-record files are immutable *prepared evidence*. Their existence never proves successful preparation. The controller endorses their exact digest only after every local write, ownership release and independent validation has completed. Its final endorsement is in the current authoritative controller process; no filesystem mutation follows it. Failure after an actual file installation, directory fsync, or actual lock close leaves no endorsement. `CutoverService.validate` / `ControllerClient.validate_certificate` refuse such files even when exclusion appears healthy. Immutable bytes remain available for diagnosis and a fully verified retry.
2. **Loss during finalization.** Core checks both fences after database resolution and around installation, latches observed loss and waits for cancelled filesystem writers to settle. After local ownership release, the controller independently checks the exact durable record/report/root/run binding, live PostgreSQL role exclusion and current controller generation under its own exclusive claim. It releases that claim and performs its last controller check before endorsing. Consumers require endorsement and repeat those complete live checks. Failed authorized validation revokes endorsement; restored observations cannot revive it. Controller restart discards endorsement and advances the generation. Tests inject loss before/after actual ownership close, failure after close has really released the lock, storage mutation followed by fsync error, and observed-loss/recovery races.
3. **Concurrent same-run owners.** `MaintenanceStore.claim` uses nonblocking kernel `flock` on a permanent, no-follow, private, independently linked, locally owned regular inode. The inode is never unlinked, and ownership has no timer. Core holds the claim through database resolution and all settled filesystem writers. Independent coordinators and independent processes cannot share it. The serialized authoritative controller reacquires the same claim before endorsement or consumer admission. Real subprocess tests prove contention, normal exit, process-kill recovery and preservation of immutable history. Service tests prove same-run conflict, cancellation settlement and retry progress.

A lost RPC acknowledgement after a true endorsement is explicitly **indeterminate acknowledgement**, not evidence of either success or failure. A real Unix-transport test drops the response after endorsement and resolves the outcome through fresh consumer validation. Failed local finalization never asks for endorsement. Report-before-record replay remains possible only after a complete scan under intact exclusion and exact immutable-byte agreement. Changed generations require a fresh run, appending after immutable history.

The controller now reads the private `maintenance_path` configuration for independent SQL checks. Templates, core consumer-owned ports, client/server wiring, CLI safe-error handling and operator/design documentation reflect that contract. Controller serialization and its separately held durable-state lock are the authority boundary; no instance-local lock is offered as cross-process proof. Only the supported private local Linux deployment is certified; no NFS claim is made.

Verifier1 corrections remain: bidirectional trustworthy mount overlap, live Compose digest validation, post-SQL and installation fence checks, behavioral real CLI wiring, real quoted-schema PostgreSQL privilege checks, and honest preparatory-only delivery status.

## Final validation

The frozen-tree full unit suite passed **1,628 tests**, with **95.88097332160656%** coverage: **6,541/6,822** statements, with the same **281** unchanged baseline missing lines. All **17 M1b production files are 100% covered**. The floor was raised from 95.84 to **95.88**, and the saved full-suite coverage passes that ratchet. Full real contracts passed **48 tests**. Full integration passed **14 tests**, including live SQL consumer revocation and fresh re-verification. Full-size acceptance passed **1 test**, retaining the unchanged **9 GiB / 144 × 64 MiB** interrupted/resumed transfer and exact download. No skips or xfails were introduced.

Source lint is confined to `src/`; the migration schema-map remains required. Ruff, format, pydoclint, mypy, ty, import-linter, radon, complexipy, configured pyscn checks, docs and diff checks pass. Radon threshold output is empty. Complete native pyscn **1.31.1** analysis reports **60/100**, **213/935 fragments**, **253 pairs**, **58 groups**, against the unchanged threshold **90**. `make lint` exits 2 and direct duplication exits 1 at that known quality failure. Native overall quality is not claimed clean. The strict parser accepts the complete native reports; full module inventory is exactly **132/132**, with zero skips/errors, zero high-complexity/dead-code findings and maximum cognitive complexity 15.

The original 57-file scope is extended by the Raw design status page and two test files (60 files). All 115 pre-existing source files match the M1a verifier hashes. `source-inventory.json`, `scoped-file-inventory.json`, `baseline-source-comparison.json`, `touched-coverage.json`, `native-inventory-validation.json` and their actual generation logs contain the audit.

## Preserved independent probes

All four verifier1 probes pass unchanged. Verifier2 probes are preserved and were run unchanged: the pending-directory-fsync probe and pending-unlink-loss probe fail because their removed marker hooks no longer describe the completion boundary. The concurrency probe's barrier requires two admitted owners, so it cannot progress under exclusive ownership; its owned subprocess group was terminated after 20 seconds and recorded as exit 124. These are not reported as passing tests. Replacement tests exercise the actual new authority contract, consumer refusal, real filesystem failures, same-run concurrency and real cross-process ownership. See `reproduction-results.json` and each complete probe log.

Development logs are retained, including the initial RPC alias failure and mixed-development-tree coverage run (not acceptance evidence), partial-suite coverage below the global floor, and the audit invocation missing `PYTHONPATH` before its corrected successful invocation. Final source/tests were frozen before complete gates, and their hashes remain unchanged.

## Cleanup and limits

All runners finished. The retained Linux cleanup inspection found no controlled fixture roots or controller socket directories; inspection and VM shutdown both exited 0. Pre-existing stopped containers and user processes were preserved. No commit, push, production service/database mutation, activation, nested delegation, frontend work or deferred D3b change occurred. User processes, unrelated working-tree changes, learning files and prior evidence are preserved. Trusted host/engine/database administrators remain outside the application-writer threat model. Initialization, activation/startup, recovery and cleanup product capabilities remain planned.


The real historical image was `sha256:8fb3570d7546d50bfd3d207c978828250de72f634fce5d12ddb3420f7843df4f`, built from commit `db5fc84cd7bfe049692ef2abb16fb32570ccf5a2`, archive SHA-256 `b1ad409fb8c193be2c03fb10aa63b0be4d11722cd0f364b52ba0aaab135de4dd`. The old request wrote 64 KiB before SQL fencing and 64 KiB afterward, then was stopped by actual controller termination; the actual old image with revoked credentials failed startup. The fixture emitted `LIVE_SQL_CONSUMER_REVOCATION_AND_FRESH_VERIFICATION_PROVED`, both running descendant-holder refusals, and `CLEANED /var/lib/huron-controlled-test-dlxh3eg3`. Full provenance and cleanup output is retained in [integration.log](integration.log).

## Complete command receipts

| Command | Exit | Actual complete output |
| --- | ---: | --- |
| `make lint` | 2 | [lint.log](lint.log) |
| `uv run ruff check src` | 0 | [ruff.log](ruff.log) |
| `uv run ruff format --check src` | 0 | [format.log](format.log) |
| `uv run pydoclint src` | 0 | [pydoclint.log](pydoclint.log) |
| `uv run ty check src` | 0 | [ty.log](ty.log) |
| `uv run mypy src` | 0 | [mypy.log](mypy.log) |
| `uv run lint-imports` | 0 | [imports.log](imports.log) |
| `uv run pytest --cov=src/huron --cov-report=term-missing` | 0 | [unit.log](unit.log) |
| `uv run coverage json -o p3-evidence/m1b/fix2/coverage.json` | 0 | [coverage.log](coverage.log) |
| `uv run radon cc src/huron --min C` | 0 | [radon-cc.log](radon-cc.log) |
| `uv run radon mi src/huron --min B` | 0 | [radon-mi.log](radon-mi.log) |
| `uv run complexipy src/huron --max-complexity-allowed 15` | 0 | [complexipy.log](complexipy.log) |
| `uv run --locked pyscn check src/huron` | 0 | [pyscn.log](pyscn.log) |
| `uv run --locked python scripts/check_duplication.py src/huron` | 1 | [duplication.log](duplication.log) |
| `make docs` | 0 | [docs.log](docs.log) |
| `git diff --check` | 0 | [diff-check.log](diff-check.log) |
| `uv run --locked pyscn analyze --json src` | 0 | [native-full-final.log](native-full-final.log) |
| `uv run pytest -m contract` | 0 | [contract.log](contract.log) |
| `uv run pytest -m integration -s` | 0 | [integration.log](integration.log) |
| `make test-acceptance` | 0 | [acceptance.log](acceptance.log) |
| `make lint` | 2 | [ratchet-lint.log](ratchet-lint.log) |
| `uv run coverage report` | 0 | [ratchet-coverage.log](ratchet-coverage.log) |
| `PYTHONPATH=. uv run python p3-evidence/m1b/fix2/audit.py` | 0 | [audit-final.log](audit-final.log) |

Nine existing M1b production files changed in this correction; their before/after hashes are in [source-changes-from-verification2.json](source-changes-from-verification2.json). The new behavioral files are `tests/unit/test_controller_certificates.py` and `tests/contract/test_maintenance_ownership.py`. Existing core, storage, transport, CLI, settings, wiring and Linux service tests were extended; obsolete pending-marker tests were removed. The old clear/unlink mechanism and its pending admission helpers are gone. Required schema-0010 maintenance remains intact.

Final handoff docs, diff and inventory checks all exited 0; see [handoff-results.json](handoff-results.json). Source/test freeze validation found no changes. Source-inventory SHA-256: `0a9ad1351a5f21902266e21e90884988b15d749e5cd72238327cfec3729efff8`. Scope-inventory SHA-256: `70b5d01c10302f83d064a3da45f30242729d99d10bc0c3f580cb084d29dcacb5`. The next step is independent verification **3 of 3**, not an implementation self-verdict.
