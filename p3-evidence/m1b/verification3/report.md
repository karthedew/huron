# M1b independent verification — attempt 3 of 3

**Functional: FAIL. Overall quality: FAIL.** Three independently reproduced authority defects remain. All required existing behavioral gates pass; the new adversarial regressions fail. The valid complete native duplication score remains 60/100 under the user's explicit functional-progress exception, and is separately an overall quality failure. This is the final allowed verification attempt; no fourth fix/review or next-milestone implementation is authorized by this workflow.

## Required corrections and plan assessment

1. **Large — observed engine transport failure does not revoke endorsement.** `src/huron/applications/lakectl/controller.py:162`, `ManagedComposeController.check`, clears `_certificate` only for `OSError` and `ValueError`. `LocalEngine._request` uses HTTPX and propagates `httpx.ConnectError`, timeouts and HTTP status errors; these do not inherit either caught exception. The server catches HTTPX errors and returns refusal, so this is a real supported transport path. After an endorsed receipt, a `check` observes an unreachable engine and fails; when connectivity returns, ordinary `validate_certificate` still admits that receipt. The independently reproduced test `test_observed_unreachable_engine_permanently_revokes_receipt` fails with `Failed: DID NOT RAISE ValueError` at consumer admission. Revoke/poison authority for every supported failed exclusion observation, without allowing another public operation to revive it accidentally; cover connect, timeout and status-error paths through the controller transport and subsequent consumer validation.

   **Assessment: fixable within the current plan.** Unreachable nodes/lost proof must fail closed and observed loss must stay invalidated. This is an incomplete exception/lifecycle implementation of an explicit requirement, not an irreducible complexity or scope problem.

2. **Large — maintenance database configuration changes do not invalidate evidence.** `_validate_evidence` at `controller.py:211` reloads the current `maintenance_path` and checks whichever database URL it now contains. `_check_volume` binds live Compose identity, but no maintained evidence binds the maintenance database configuration or database identity. After endorsement, replacing the private maintenance file's URL with another database having safely excluded same-named roles still lets `validate_certificate` accept the original receipt. The test `test_changed_maintenance_database_configuration_invalidates_receipt` changes the actual private file, substitutes only the external SQL observations, and fails with `Failed: DID NOT RAISE ValueError`. Bind the independently checked database/configuration to the preparation authority and invalidate existing evidence when it changes; ensure preparation and consumption cannot silently switch clusters/databases. Test a distinct real PostgreSQL target and restoration of the old configuration after an observed change.

   **Assessment: fixable within the current plan.** Root/configuration changes already invalidate evidence by contract. Extending that binding to the newly introduced maintenance configuration requires no new product decision. This is not a demand to resist a malicious root administrator: legitimate administrator reconfiguration must invalidate prior evidence, just as the accepted Compose-change correction does.

3. **Large — an authorized caller can re-endorse revoked prepared evidence without full reverification.** `ManagedComposeController.certify` at `controller.py:166–176` accepts any stored matching record/report under the current observed fence; revocation removes only `_certificate`, leaving the same generation eligible for this operation. `server.py` exposes `certify` directly to every authenticated cutover UID. After a real observed writer violation revokes an endorsed receipt, removing the writer and calling `certify` on the same receipt succeeds without running `CutoverService.prepare`, inspecting legacy payload, or resolving any new scan. `test_revoked_receipt_cannot_be_reendorsed_without_full_reverification` fails with `Failed: DID NOT RAISE ValueError`. This operation can make stale VERIFIED membership usable after the interval in which a writer could have changed content. Define and enforce the authority transition that distinguishes freshly completed verification from presentation of previously prepared/revoked bytes. A consumer cache clear alone is not permanent invalidation. Require a fresh authoritative verification epoch/completion handoff after observed loss and prevent direct RPC retry from bypassing it. Test the complete public sequence: certify, observed loss, restoration, direct certify retry, and normal consumer admission; stale evidence must remain refused.

   **Assessment: PLAN DEFECT — missing authority/reverification decision.** The plan requires full rescanning after exclusion loss, but the redesigned procedure places full scanning in the client and makes the controller the final authority while its public endorsement contract accepts stored bytes plus current observations. It does not define a controller-verifiable connection to a freshly completed scan or distinguish a retry of failed prepared evidence from completion. The implementation follows that incomplete procedural split. Architectural review must settle the trusted completion/epoch handoff (or move the necessary workflow behind the authority) and its failure states. This is not an allegation of malicious trusted root: the reproduction uses the explicitly granted maintenance UID and exposed operations, without altering controller memory, bypassing kernel grants, or writing forged records.

[Independent reproduction source](test_authority_repro.py), [complete output](repro.log), [exit](repro.exit): **3 failed, exit 1**. Only genuine engine and SQL I/O boundaries are substituted; controller logic, models, private configuration reads, immutable storage and kernel claims are real. The failures are deterministic, with no timing-based races or source edits.

## Previous findings and redesigned finalization

All **four original verifier1 probes pass** unchanged ([output](prior-reproductions.log)). Foreign ancestor/descendant directory/file mount refusal, live Compose identity checking, real CLI wiring tests, effective quoted-schema PostgreSQL grant preservation and honest preparatory-only status remain addressed.

The removed pending-marker hooks are obsolete and were not demanded back. Independent replacement tests exercise actual core + controller + MaintenanceStore at the new authority boundary: post-install fsync acknowledgement failure, post-release close acknowledgement failure, and controller fence loss during ownership release. All **three pass**, including consumer refusal for stranded records and successful full-verification retry under restored conditions: [source](test_finalization_contract.py), [output](finalization-contract.log). Existing tests additionally cover cancellation settlement, restored-loss latching, same-run contention and lost RPC acknowledgement resolution. Real subprocess contracts prove nonblocking ownership conflict, normal exit, killed-owner recovery and immutable history preservation. Permanent inode ownership fixes the prior shared-marker race; it does not repair the three controller authority defects above.

The review covered all nine production modules changed since verifier2, all 17 M1b production files through current inspection plus independently unchanged prior review, new model/port/transport contracts, controller/CLI/wiring/settings tests, real ownership contracts, controlled Linux fixture, narrow schema-0010 adapters, schemas, packaging, import boundaries and documentation. Core continues to use consumer-owned capabilities without concrete I/O/framework imports. No frontend or API implementation change is in scope. Initialization, migration activation and startup delivery remain M1c work and are not demanded or certified here.

Read current AGENTS, the complete implementation plan/workflow, P3 design, fix2 report/validation and prior reports; applied the actual local OOP, codebase-design, PostgreSQL and instruction-writing guidance. The implemented architecture skill differs from the historical planning receipt's scaffold description; that historical statement is not treated as current methodology.

## Independent validation receipts

| Command | Exit | Complete combined stdout/stderr |
| --- | ---: | --- |
| `make lint` | 2 | [lint.log](lint.log) |
| `uv run ruff check src` | 0 | [ruff.log](ruff.log) |
| `uv run ruff format --check src` | 0 | [format.log](format.log) |
| `uv run pydoclint src` | 0 | [pydoclint.log](pydoclint.log) |
| `uv run ty check src` | 0 | [ty.log](ty.log) |
| `uv run mypy src` | 0 | [mypy.log](mypy.log) |
| `uv run lint-imports` | 0 | [imports.log](imports.log) |
| `uv run pytest --cov=src/huron --cov-report=term-missing` | 0 | [unit.log](unit.log) |
| `uv run coverage json -o p3-evidence/m1b/verification3/coverage.json` | 0 | [coverage.log](coverage.log) |
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
| `PYTHONPATH=. uv run pytest -q p3-evidence/m1b/verification3/test_finalization_contract.py` | 0 | [finalization-contract.log](finalization-contract.log) |
| `PYTHONPATH=. uv run pytest -q p3-evidence/m1b/verification3/test_authority_repro.py` | 1 | [repro.log](repro.log) |
| `python3 p3-evidence/m1b/verification3/audit.py` | 0 | [audit.log](audit.log) |

Full unit suite: **1,628 passed**, **95.88097332160656%** (6,541/6,822 statements; the same 281 baseline missing lines), meeting the **95.88** ratchet. All **17 M1b production files have 100% line coverage** without defensive-line exceptions. Contracts **48 passed**; integrations **14 passed**; full-size acceptance **1 passed**. Acceptance retains the **9 GiB / 144 × 64 MiB** interrupted/resumed real HTTP upload and complete download; its **25 GiB free-space precondition executed**. Existing testcontainers/Starlette dependency deprecation warnings remain in logs; no skipped or xfailed tests were introduced.

Ruff, format, docstrings, mypy, ty, all nine import contracts, migration schema-map, complexity/dead-code gates, strict docs and diff checks passed. Both radon threshold outputs are empty; maximum cognitive complexity is 15. Source-only lint is canonical in Makefile and CI, with tests and schema-map still independently required. No source thresholds, import contracts, suppressions or exclusions were weakened.

Exact outstanding native failure:

```text
pyscn 1.31.1 native duplication score: 60/100 (required: >=90/100)
Cloned fragments: 213/935; clone pairs: 253; clone groups: 58
make: *** [lint] Error 1
```

`make lint` exits 2; direct duplication exits 1. Fresh full analysis and both clone reports cover exactly **132/132 source files**, zero skips, no complexity/dead-code/system error diagnostics, zero high-complexity/dead-code findings. Default test/migration patterns match no source file. The strict native report parser independently accepts all three reports. Raw artifacts: [full-src.json](full-src.json), [native-src.json](native-src.json), [native-src-huron.json](native-src-huron.json), [inventory validation](native-inventory-validation.json). Exploratory architecture/coupling metadata in full analysis is not the configured Huron architecture gate; its explicit import contracts pass. Native quality remains separate from the functional findings, and D3b stays paused.

## Source identity, provenance and cleanup

Source-inventory SHA-256: `0a9ad1351a5f21902266e21e90884988b15d749e5cd72238327cfec3729efff8`. All **132 source hashes** and **60 scoped-file hashes** match fix2 before and after the gates; all **115 pre-existing production files match M1a**. [Independent identity/coverage](final-identity-coverage.json), source/scope input inventories and match reports are retained. Fix2 supplied no artifact-hashes.json; the first copied evidence runner stopped on that absent receipt before any command ran. The verifier then used the actual source/scope inventories and reran its full static runner successfully. This did not replace any gate with implementer claims. Independent evidence hashes accompany this report.

The historical fixture verified commit `db5fc84cd7bfe049692ef2abb16fb32570ccf5a2` and source archive SHA-256 `b1ad409fb8c193be2c03fb10aa63b0be4d11722cd0f364b52ba0aaab135de4dd`; the actual independent old image is `sha256:7aeb476f031e39dacbd07b785bd2ed73d8433b8897f49e4b1efbc6d7c65cb421`. The `-s` transcript records healthy old startup, admitted held HTTP upload, a further write after SQL fencing, actual controller termination/restart exclusion and startup refusal with revoked old credentials. It also records live SQL consumer revocation/fresh verification, both foreign descendant holder refusals, generation/unreachable-controller refusal and cleanup. This is an actual old artifact, not spoofed version input or an initially broken startup.

Podman startup/readiness and all service gates shared one retained runner, using the actual discovered socket and explicit owned-fixture cleanup with Ryuk disabled. No shared daemon permissions or SELinux policy changed. The fixture cleaned `/var/lib/huron-controlled-test-wv3ziemk`; final Linux inspection found no owned controlled-test or controller-test directories. Final container inventory contains only pre-existing unrelated stopped containers. Both retained runners, all probe tasks and subprocesses have finished. The VM started for this review is stopped; shutdown exited 0. [Linux cleanup](linux-cleanup.log), [container inventory](podman-final-containers.log), [VM shutdown](podman-stop.log), [final VM state](podman-final-inspect.json), [process snapshot](final-process-check.log).

No source/test/configuration/design files were changed by this verifier; only verification3 evidence was written, alongside routine tool-generated caches/reports. No commit, push, production DB/service mutation, cutover activation or nested delegation occurred. This result certifies neither NFS nor production deployment, independent M1b deployability, M1c completion or P3 completion. The iteration cap requires architectural escalation before further implementation.
