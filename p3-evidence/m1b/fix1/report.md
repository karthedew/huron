# M1b corrective implementation — attempt 2 / fix pass 1

**Local functional validation: PASS.** All five requested corrections are implemented and tested. Independent verification attempt 2 is pending. The native duplication gate remains a separately authorized quality failure; no clean lint, release readiness, M1c delivery or P3 completion is claimed.

## Corrections

1. **Complete mount overlap.** The controller compares normalized backing paths in both directions, rejecting foreign descendant directories and files as well as ancestors and daemon exposure. Relative or replaceable symlink aliases are refused rather than trusted as mounted-object identity. Existing privileged/host-namespace and named-volume image/source refusals remain. Focused tests cover descendants, normalization, relative paths and aliases; the actual Linux fixture starts foreign directory/file bind holders and verifies both check and establish refuse while those containers remain running.
2. **Live configuration identity.** Every root check/admission re-reads the private trusted Compose file and compares its digest with persisted deployment identity. Tests change the live command without reconstructing the controller and exercise check, describe, establish and restart.
3. **Owned evidence persistence.** Each database resolution and filesystem installation has a durable write-ahead pending marker. Checks occur after SQL resolution and around each installation. A per-invocation guard serializes checks and latches observed exclusion loss. Cancellation waits for the actual filesystem thread to finish. Only completed I/O and a valid, never-lost fence permit clearing the pending marker. Lost exclusion leaves installed reports/records pending and indeterminate, even after external observations recover. Marker-removal errors never return success; an uncleared marker conservatively requires a fresh run. A new run fully scans again and appends after pending records, preserving their immutable forensic bytes. Completed report-before-record failures under an intact fence replay with the same run. Tests cover both reported gaps, report installation loss, blocked-writer cancellation with intact/lost fences, recovered-looking observations after a monitor failure, finalization I/O failure, refusal to resurrect a pending run, and fresh-run progress.
4. **Behavioral verification.** The CLI test runs real CLI → wiring → core → filesystem behavior with only controller/SQL I/O substituted, asserting canonical output and its durable record. The exact REVOKE spelling assertions were removed. Real PostgreSQL checks now prove effective privilege removal in a quoted schema and preservation of unrelated schema/table and inherited-role grants. Public safe-error and refusal tests remain.
5. **Delivery status.** P3 design/plan, the Raw layout page, operator contract and validation receipt distinguish implemented preparatory evidence/legacy verification under review from planned initialization, migration activation/startup, recovery and cleanup. The evidence-validity predicate explicitly requires no pending marker, canonical report binding and matching live exclusion; future M1c consumers must enforce it.

No obsolete compatibility layer was added. The old unchecked final publication path, unlatching monitor checks, one-direction mount predicate, prepare receipt stub and SQL-string assertions were replaced. Required schema-0010 maintenance remains.

## Final gate receipts

The frozen-tree full unit suite passed **1,606 tests**, with **95.84073416222617%** line coverage (6,475/6,756 statements; 281 unchanged baseline missing lines). The coverage floor rose from 95.80 to **95.84**. Every one of the 17 M1b production files is at 100%. Full contracts: **46 passed**. Full integration: **14 passed**. Full-size acceptance: **1 passed**, retaining the 9 GiB file, 144 × 64 MiB parts, interrupted/resumed HTTP upload and exact download. No tests were skipped or xfailed. Complete stdout/stderr and exit/duration records are in `static-results.json` and `services-results.json`; earlier and intermediate receipts remain under `before-latched-guard/` and `intermediate-static/`. The intermediate mixed-tree coverage failure is not acceptance evidence: controller lines changed while that measurement was running. Source/tests were then frozen and the complete static/unit gate restarted.

| Command | Exit | Complete actual output |
| --- | ---: | --- |
| `make lint` | 2 | [lint.log](lint.log) |
| `uv run ruff check src` | 0 | [ruff.log](ruff.log) |
| `uv run ruff format --check src` | 0 | [format.log](format.log) |
| `uv run pydoclint src` | 0 | [pydoclint.log](pydoclint.log) |
| `uv run ty check src` | 0 | [ty.log](ty.log) |
| `uv run mypy src` | 0 | [mypy.log](mypy.log) |
| `uv run lint-imports` | 0 | [imports.log](imports.log) |
| `uv run pytest --cov=src/huron --cov-report=term-missing` | 0 | [unit.log](unit.log) |
| `uv run coverage json -o p3-evidence/m1b/fix1/coverage.json` | 0 | [coverage.log](coverage.log) |
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
| `PYTHONPATH=. uv run pytest -q tests/unit/test_integrity_cutover.py tests/unit/test_integrity_storage.py tests/unit/test_lakectl_main.py tests/unit/test_managed_controller.py tests/unit/test_maintenance_adapters.py p3-evidence/m1b/verification1/test_review_repro.py` | 0 | [focused-final.log](focused-final.log) |

Native pyscn **1.31.1** reports **60/100**, **213/925 cloned fragments**, **253 pairs**, **58 groups**. The unchanged required score is 90. `make lint` exits 2 only at that threshold; the direct duplication command exits 1. Ruff, format, pydoclint, both type checkers, all nine import contracts, migration schema-map, radon, complexipy and configured pyscn checks pass. Radon threshold output is empty; full native analysis has maximum cognitive complexity 15 and zero high-complexity/dead-code findings. The strict parser accepts all fresh clone reports, and the full module inventory exactly matches 132 on-disk source files with no omissions, unexpected modules, skips or errors. The native quality failure remains separate from functional acceptance; deferred D3b remains untouched.

The final old image was `sha256:a8465115151e30c15a11fee7263be39b492aecdb548531842bad8f2da1e3b503`, built from historical commit `db5fc84cd7bfe049692ef2abb16fb32570ccf5a2` with archive SHA-256 `b1ad409fb8c193be2c03fb10aa63b0be4d11722cd0f364b52ba0aaab135de4dd`. The sole old packaging adjustment copies README. The actual old API admitted a request and wrote 64 KiB before and another 64 KiB after SQL fencing; controller termination stopped it and excluded restart. The same revoked old credentials failed actual old-image startup. The real fixture additionally refused running descendant directory/file holders at both check and establish. The complete `-s` transcript is retained in [integration.log](integration.log).

## Scope, integrity and cleanup

The original 57-file milestone scope is retained and extended by `design/layer-raw.html` (58 files). Four M1b production files changed in this fix. All 115 pre-existing source files match the M1a verifier's hashes; all 17 M1b production files are fully covered. The exact source/scope hashes, strict complete native inventory and coverage audit are generated by `audit.py`.

No commit, push, production service/database mutation, activation, nested delegation, frontend work or deferred D3b work occurred. Static lint remained `src/`; thresholds and migration schema-map validation were preserved. Disposable local testing only. No NFS or production certification is claimed. The historical fixture emitted `CLEANED /var/lib/huron-controlled-test-p5pc5wpz`. Final engine inventory contains only pre-existing stopped containers. The final retained cleanup inspection found no controlled fixture graphroots or controller socket directories; VM shutdown succeeded. All test, controller, fixture and validation runners are finished. Pre-existing stopped containers and user processes were preserved.


Evidence: [source inventory](source-inventory.json), [58-file scope inventory](scoped-file-inventory.json), [fix scope comparison](fix-scope-changes.json), [M1a source comparison](baseline-source-comparison.json), [coverage](coverage.json), [all added-file coverage](touched-coverage.json), [full native JSON](full-src.json), [strict native inventory](native-inventory-validation.json), [cleanup](cleanup.log). The fix also changes only the affected Raw layout status paragraph beyond the original 57-file scope. Existing broader working-tree differences remain unrelated and preserved.

No independent verification verdict is asserted. The next step is independent verification attempt **2 of 3**.

Final [docs/diff/inventory receipts](handoff-results.json) all exit 0; [cleanup receipts](cleanup-results.json) all exit 0. Final focused regression/reproduction run: **86 passed**. Source-inventory SHA-256: `0dedb64b30388547fd3220bc9a70890cb5f58813a2a66e1ad815d53aed31094b`.
