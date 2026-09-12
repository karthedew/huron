# M1b independent verification — attempt 1 of 3

**Functional acceptance: FAIL. Overall repository quality: FAIL.**

The complete mandatory validation gate ran independently. Existing tests pass, but four additional behavioral reproductions expose three exclusion/certification defects. Two smaller test/documentation corrections also remain. The unchanged native duplication score is 60/100 against 90; that separately authorized exception is not the reason for the functional failure.

No implementation, application test, configuration, or design file was edited by this verifier. Review evidence is confined to this directory. No commit, push, production cutover, migration activation, or nested delegation occurred. Model/reasoning settings were inherited.

## Precise fix list

1. **Large — foreign descendant bind mounts escape the complete writer inventory.** `src/huron/applications/lakectl/controller.py:150`, `ManagedComposeController._writers`, and `_exposes` at line 245 only detect a mount source equal to or containing the protected path. A foreign image with writable bind source `<volume>/organization` is neither collected nor refused: `establish()` returns evidence with no terminated writers while the foreign container remains. This contradicts the required daemon-wide foreign volume-holder refusal and can leave a process able to modify verified bytes. Refuse overlapping access in both directions, using trustworthy normalized backing-path identity; add descendant-directory and descendant-file cases to the real Linux fixture as well as focused tests. Preserve refusal of ancestors, daemon exposure, and privileged holders. The existing test covers ancestor/socket/unrelated mounts, but omits descendants.

2. **Medium — live deployment-file changes do not invalidate an existing fence.** `src/huron/applications/lakectl/controller.py:188`, `_check_volume`, compares persisted `composition` with `self._composition`, which was read only during construction. After a fence is established, replacing the fixed Compose command in the root-owned configuration still lets `check()` accept the old evidence. The current test named `test_storage_replacement_and_deployment_change_invalidate_controller_state` changes only the backing directory, not the deployment configuration. Revalidate the actual trusted configuration identity when checking/admitting operations, or implement an enforceable configuration-generation mechanism that detects changes; test a live file change without reconstructing the controller. This is an evidence-invalidation contract, not a claim that the controller can defend against a malicious trusted root administrator.

3. **Large — final persistence boundaries can publish evidence after exclusion is lost.** `src/huron/core/integrity/cutover.py:137` through line 148 and `prepare()` lines 104–111 leave gaps around database resolution and final installation. If the database boundary loses the fence while `resolve()` completes, the workflow still installs `reports/<run>.json` before the next check refuses. If exclusion is lost while `000001.json` is installed, `_record()` returns immediately and `prepare()` stops the monitor; the call can return a successful receipt even though a fresh check fails. Both cases reproduce deterministically without timing sleeps. Keep exclusion validation/ownership coupled to the persistence boundaries: recheck after database work and before report publication, and ensure a lost fence during final installation cannot yield success or usable certification. Account explicitly for an in-flight filesystem operation under cancellation, rather than assuming cancellation revokes its thread or write. Add regressions for both boundaries and the corresponding interrupted-write outcome. A report-before-record crash under an intact fence must remain resumable.

4. **Small — tests depend on internal calls or SQL spelling rather than observable contracts.** `tests/unit/test_lakectl_main.py:83` replaces the same-package `prepare` workflow with a receipt stub and asserts its arguments; the requested testing standard forbids replacing package collaborators that are not genuine I/O boundaries. Run the real CLI-to-wiring workflow with controller/database I/O substituted, or through the disposable deployment, and assert its actual canonical output and durable result. `tests/unit/test_maintenance_adapters.py:58` and line 60 assert exact REVOKE statement strings; an equivalent correct revocation implementation would fail these tests. Exercise quoted schema names against real PostgreSQL and assert effective privileges and preservation of unrelated grants. Keep tests for safe public error output and boundary failures.

5. **Small — affected status prose still says implemented protocol storage is planned.** `P3_DESIGN.md:72` says protocol areas remain planned, and `design/layer-raw.html:166` says protocol directories and maintenance workflows remain planned. These disagree with the newly added M1b implementation description and the actual report/record writer. Update the status distinction to identify preparatory protocol evidence/legacy verification as implemented and under verification, while initialization, activation/startup, recovery and cleanup remain planned. Do not mark M1b independently deployable or P3 complete.

The independently added reproductions are [test_review_repro.py](test_review_repro.py). Run:

```sh
PYTHONPATH=. uv run pytest -q p3-evidence/m1b/verification1/test_review_repro.py
```

Actual exit: **1**, four failures. [Complete output](repro.log), [exit receipt](repro.exit). The exact failures are:

```text
FAILED test_foreign_descendant_mount_must_block: DID NOT RAISE ValueError
FAILED test_changed_live_compose_must_invalidate: DID NOT RAISE ValueError
FAILED test_lost_fence_during_database_resolution_must_not_publish_report: report path exists
FAILED test_lost_fence_during_record_installation_must_not_return_success: DID NOT RAISE ExceptionGroup
4 failed
```

These reproductions use the existing engine/database I/O fixtures and real controller/core/filesystem behavior. They do not replace the controller or core decision methods under review. They were written only as review evidence, not added to the application test tree.

## Source identity and scope

All **57 scoped files** exactly match the supplied scope hashes; all **132 production Python files** match the supplied source hashes. The 115 pre-existing production files also independently match the M1a verifier's final source hashes; M1b adds 17 production files. Every one of those 17 is at 100% measured line coverage. No source exceptions were judged necessary.

Independent source-inventory SHA-256:

```text
af507148a60f858e91fb5c806c1a8e9ed50827a8d1d0fdfb5ac056f068fbe5f9
```

Evidence: [source inventory](source-inventory.json), [scope match](scoped-file-inventory-check.json), [source match](source-inventory-check.json), [baseline comparison](baseline-source-comparison.json), [artifact hash check](artifact-hashes-check.json), [coverage JSON](coverage.json), [touched coverage](touched-coverage.json). Supplied artifact hashes were checked, but their validation claims were not substituted for independent runs.

Read the full P3 plan/design, AGENTS, implementation workflow, relevant architecture/Raw/API/roadmap sections, deployment contract, actual source, tests, schemas, packaging, Makefile, and CI configuration. Applied the actual OOP, codebase-design, PostgreSQL, and instruction-writing skills at their respective boundaries. The current architecture skill is implemented; the design's scaffold statement belongs to its historical planning receipt. No frontend or API implementation change is part of M1b.

The implementation otherwise has meaningful consumer-owned interfaces, no concrete I/O imports in core, scoped external maintenance authority, independent SQL/process fences, canonical immutable evidence, streaming no-follow payload inspection, complete acknowledged hierarchy checking, and a narrow schema-0010 adapter with atomic imports/audit/findings/session resolution. Schema loading/runtime parity tests and the migration schema-map gate pass. The findings above prevent those mechanisms from constituting complete M1b acceptance.

## Independent gates

The following table links complete combined stdout/stderr, not implementer excerpts. Exact commands, exit codes and durations are also in [static-results.json](static-results.json), [services-results.json](services-results.json), and [historical-proof-results.json](historical-proof-results.json). [Tool versions](tool-versions.log) include pyscn 1.31.1.

| Command | Exit | Complete output |
| --- | ---: | --- |
| `make lint` | 2 | [lint.log](lint.log) |
| `uv run ruff check src` | 0 | [ruff.log](ruff.log) |
| `uv run ruff format --check src` | 0 | [format.log](format.log) |
| `uv run pydoclint src` | 0 | [pydoclint.log](pydoclint.log) |
| `uv run ty check src` | 0 | [ty.log](ty.log) |
| `uv run mypy src` | 0 | [mypy.log](mypy.log) |
| `uv run lint-imports` | 0 | [imports.log](imports.log) |
| `uv run pytest --cov=src/huron --cov-report=term-missing` | 0 | [unit.log](unit.log) |
| `uv run coverage json -o p3-evidence/m1b/verification1/coverage.json` | 0 | [coverage.log](coverage.log) |
| `uv run radon cc src/huron --min C` | 0 | [radon-cc.log](radon-cc.log) |
| `uv run radon mi src/huron --min B` | 0 | [radon-mi.log](radon-mi.log) |
| `uv run complexipy src/huron --max-complexity-allowed 15` | 0 | [complexipy.log](complexipy.log) |
| `uv run --locked pyscn check src/huron` | 0 | [pyscn.log](pyscn.log) |
| `uv run --locked python scripts/check_duplication.py src/huron` | 1 | [duplication.log](duplication.log) |
| `make docs` | 0 | [docs.log](docs.log) |
| `git diff --check` | 0 | [diff-check.log](diff-check.log) |
| `uv run pytest -m contract` | 0 | [contract.log](contract.log) |
| `uv run pytest -m integration` | 0 | [integration.log](integration.log) |
| `make test-acceptance` | 0 | [acceptance.log](acceptance.log) |
| `uv run pytest -m integration -s tests/integration/test_protocol_cutover.py` | 0 | [historical-proof.log](historical-proof.log) |
| `uv run --locked pyscn analyze --json src` | 0 | [full-src.log](full-src.log) |

Unit result: **1,587 passed**, 61 marker-deselected, **95.80158374421038%** coverage (6,412/6,693 statements; 281 baseline missing lines). The configured 95.80 floor was met. All 17 added production files have zero missing lines. Contract result: **46 passed**. Integration result: **14 passed**. Acceptance result: **1 passed**, exercising the unchanged 9 GiB file, 144 × 64 MiB parts, interrupted/resumed real HTTP transfer and whole-file download; its 25 GiB minimum-capacity check executed. No tests were skipped or xfailed. Existing testcontainers/Starlette deprecation warnings are retained in the logs.

Ruff, format, pydoclint, both strict type checks, all nine import contracts and migration schema-map validation passed. Radon's C-or-worse complexity and B-or-worse maintainability outputs were empty. Complexipy passed; the full native analysis has maximum cognitive complexity 15, zero high-complexity/dead-code findings and empty diagnostic/error lists. Strict docs and diff checks passed. The user-authorized static scope is consistently `src/`; no teaching/test/script/migration files were subjected to an expanded lint scope, and no thresholds were lowered.

Full native scan evidence: [full-src.json](full-src.json), [native-src.json](native-src.json), [native-src-huron.json](native-src-huron.json), [inventory validation](native-inventory-validation.json). Exact on-disk source inventory and analysis module inventory are **132/132**, with no missing, unexpected or skipped files. Clone analysis is enabled and successful; the existing strict report parser independently accepted the reports. Native score: **60/100**; **213/919** cloned fragments, **253** pairs, **58** groups. The full scan's additional architecture/coupling/cohesion scores are diagnostic metadata, not configured gates.

Exact final quality-gate failure text:

```text
pyscn 1.31.1 native duplication score: 60/100 (required: >=90/100)
Cloned fragments: 213/919; clone pairs: 253; clone groups: 58
make: *** [lint] Error 1
```

`make lint` exited 2; the direct duplication command exited 1. The native quality failure remains separate from the five requested corrections above. Per the explicit execution exception, duplication reduction is not added to this M1b fix scope and D3b remains paused. Neither clean lint/CI nor release readiness is claimed.

## Historical artifact and deployment evidence

The normal full integration run passed, then the historical test was rerun with `-s` to retain its successful fixture transcript, which its default pytest capture otherwise hides. [Historical proof output](historical-proof.log) records the independently built image:

```text
sha256:3fd1ce32fff5404fd4aa0b3ab7efa0e19d4792e8be9244dbc5095c1addcfe61a
```

The test verifies archived historical commit `db5fc84cd7bfe049692ef2abb16fb32570ccf5a2` against source archive SHA-256 `b1ad409fb8c193be2c03fb10aa63b0be4d11722cd0f364b52ba0aaab135de4dd`. Inspection confirms the sole historical packaging adjustment copies README; historical application source is not replaced with current code. The runtime invokes the actual historical API module. The image first becomes healthy, admits a real multipart HTTP request, writes the first 64 KiB, and then writes another 64 KiB after SQL fencing. The real controller terminates it and excludes restart. A trusted fixture administrator separately launches the same old artifact with revoked old credentials and observes the specific old-role login refusal and failed startup. Replacement credentials are absent from its specification.

The same local Linux fixture demonstrates authenticated root grants, unauthorized kernel-UID refusal, actual volume device/inode identity, wired core/database/storage cutover, foreign whole-volume-holder refusal, changed controller generation and unreachable-controller refusal. Those passing cases do not cover the descendant-mount and persistence-boundary defects reported above.

No NFS environment was available or tested, and no NFS/production certification is claimed. The supported private-engine provisioning contract is explicit about trusted host/engine/database administrators and forbids alternate ordinary application/automation daemon or storage grants. Ordinary development Compose remains unsupported. M1c initialization, migration activation and startup enforcement remain later scope; M1b and P3 are not declared complete or independently deployable.

## Cleanup and handoff

Both retained validation runners and the targeted historical runner have finished; no verifier-owned test/controller/fixture processes remain. The historical fixture emitted `CLEANED /var/lib/huron-controlled-test-h2ydkp1g`. [Linux cleanup inspection](linux-cleanup.log) found no remaining controlled-fixture graphroots or controller socket directories. [Final engine inventory](podman-final-containers.log) contains only older pre-existing stopped containers, which were preserved. Testcontainers resources were context-managed with explicit teardown while Ryuk was disabled. No shared Podman permission/SELinux configuration was changed; the fixture labels and removes only its own private graphroot. User uv/nvim processes were untouched.

All mandatory checks are complete. The next authorized step is an implementation fix pass addressing items 1–5, followed by independent verification attempt 2; this report is the completed attempt-1 verdict, not a checkpoint.
