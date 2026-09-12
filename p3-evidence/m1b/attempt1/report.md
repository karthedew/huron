# M1b implementation attempt 1

Local functional acceptance: **PASS**. Independent verification: **pending**.
Repository native duplication gate: **FAIL, 60/100 below unchanged 90**. This is
the explicitly accepted functional-progression exception, not release readiness.
No commit, push, production database/service change or application activation was
performed. M1c startup/activation and later P3 milestones remain unimplemented.

## Delivered behavior

- `core/integrity` authenticates root-scoped maintenance, coordinates independent
  writer/database fences, continuously rechecks exclusion, verifies the complete
  structural hierarchy and every revision, and publishes an fsynced report before
  its immutable numbered record. Exact VERIFIED membership determines certification.
- `applications/lakectl` provides a real root-run Linux controller, kernel UID
  grants, private engine inspection/termination and durable restart admission.
  Foreign storage holders, exposed engine/storage mounts, host privileges, stale
  generations and unreachable authority are refusals. Fixed resolved Compose
  configuration cannot be replaced by request-supplied images, mounts or commands.
- `pkg/metastore/maintenance.py` separates dedicated old/new application identities
  from owner/cutover authority, disables login, terminates sessions and verifies
  effective membership, ownership, column, sequence, security-definer-function,
  schema and database write paths. Unsafe PUBLIC/owner access is refused rather
  than revoked broadly from unrelated users.
- `pkg/metastore/legacy.py` supports exactly schema 0010. It imports only trusted
  revisions, detects import/session identity conflicts, fails unmatched or corrupt
  sessions, and records revision/session audit plus corruption findings atomically.
- `pkg/rawstore/maintenance.py` uses no-follow directory/file descriptors and
  streams all payload bytes. It checks exact inventory, owners, seals, independent
  regular-file inodes and structural documents. Known corrupt/absent/unsafe final
  envelopes retain DEGRADED identity; untrusted orphan identities block the run.
- Versioned protocol JSON Schemas, explicit loading/parity tests, the CLI entry
  point and application-independence contract are wired. Container packaging now
  includes README for wheel metadata and uses the current API module entry point.
- `deploy/controlled/` and the operator guide define the supported private Linux
  deployment, separate database identities and root-protected configuration. The
  ordinary development Compose stack remains explicitly noncertifiable.

## Validation receipts

| Command / boundary | Exit and result | Evidence |
| --- | --- | --- |
| `uv run pytest --cov=src/huron --cov-report=term-missing` | 0; 1,587 passed, 61 marker-deselected, 69.33 s; 95.80% | [unit log](unit-delivery.log), [coverage JSON](coverage-delivery.json) |
| Added production coverage | Every added file 100%; 6,412/6,693 source statements overall; 281 baseline missing lines | [per-file coverage](touched-production-coverage.json) |
| `uv run pytest -m contract -v` | 0; 46 passed, 114.80 s | [contract log](contract-full.log) |
| Expanded PostgreSQL maintenance cases | 0; 16 passed, 28.19 s | [maintenance log](maintenance-contract-expanded.log) |
| `uv run pytest -m integration -v -s` on final production source | 0; 14 passed, 84.41 s | [integration log](integration-delivery.log) |
| `make test-acceptance` | 0; 1 passed, 113.86 s; full interrupted/resumed 9 GiB transfer | [acceptance log](acceptance-full.log) |
| `make lint` after user-directed source scoping | 2 only at final native duplication threshold; preceding constituents pass | [canonical lint log](lint-source-scope.log) |
| Ruff lint/format, pydoclint, mypy, ty, imports, schema map | 0; source scope `src/`; no new diagnostics or suppressions | [canonical lint log](lint-source-scope.log) |
| Radon CC/MI | 0; empty flagged output | [CC](delivery-radon-cc.log), [MI](delivery-radon-mi.log) |
| Complexipy / pyscn configured checks | 0; no over-limit complexity or dead code | [complexipy](delivery-complexipy.log), [pyscn](delivery-pyscn-check.log) |
| Full `src` analysis | 0; 132/132 files, zero skips, zero dead/high-complexity findings | [full JSON](delivery-full-src.json), [full log](delivery-full-src.log) |
| Native duplication on `src` | 1; 60/100, 213/919 fragments, 253 pairs, 58 groups | [native JSON](delivery-native-src.json), [native log](delivery-native-src.log), [canonical lint JSON](source-scope-native.json) |
| `make docs` | 0, strict | [docs log](docs-final.log) |
| `git diff --check` | 0 | [diff log](diff-check.log) |

No tests were skipped or xfailed. Marker deselection separates unit, contract,
integration and acceptance suites; it is not missing required coverage. The
coverage floor increased from 94.96 to 95.80. Source checks retain all prior
thresholds and native pyscn configuration. Full-analysis coupling/community scores
remain diagnostic metadata; configured import contracts and complexity/dead-code
gates pass.

The 115 pre-existing production files match the independently verified M1a source;
this milestone adds 17 production files. The final legacy-only unreadable-envelope
classification was followed by full unit and integration refreshes; it does not
change ingestion code exercised by the full-size acceptance run.
See [source comparison](baseline-source-comparison.json),
[source inventory](source-inventory.json), [tool versions](tool-versions.log) and
[artifact hashes](artifact-hashes.json).

## Actual old-artifact and authority proof

The durable test archives historical commit
`db5fc84cd7bfe049692ef2abb16fb32570ccf5a2` and verifies archive SHA-256
`b1ad409fb8c193be2c03fb10aa63b0be4d11722cd0f364b52ba0aaab135de4dd`.
The final built old image is
`sha256:2d8455ee70189bf72b0e396b0b8346b0b581f05466e9593cc1a7d3e611233071`.
The only historical packaging adjustment includes its README; the runtime command
selects the actual old API module rather than using the stale broken Containerfile
command as exclusion evidence. Historical application source is unchanged.

The old API becomes ready and admits an actual HTTP multipart upload. The first
64 KiB reaches its staging file. After SQL login/session fencing, another 64 KiB
of that already-admitted HTTP request still reaches disk. Independent controller
termination then ends the writer and denies restart. A trusted test administrator
separately starts the same old image with its revoked old credentials: startup
fails, no replacement credentials are present, and it cannot become ready to write.

The same fixture exercises kernel-authenticated authorized and denied UIDs,
controller-supplied actual Linux volume identity, fully wired core/database/storage
preparation, a foreign volume holder, changed controller generation and unreachable
controller. It removes all owned containers, volumes, network, image and temporary
graphroot; the final log records
`CLEANED /var/lib/huron-controlled-test-vobv8kf6`. Podman VM startup, readiness and
tests remain in one retained process. Testcontainers use explicit context teardown
with Ryuk disabled. Signal interruption invokes owned-fixture cleanup; no production
resource is part of the fixture.

## Limits and scope

This is local disposable Linux deployment evidence. The provider requires trusted
administrator provisioning of a private engine with no alternate application or
automation daemon/storage grant. Trusted root/engine/database administrators can
override the boundary and are explicitly outside its threat model. Remote engines,
NFS, arbitrary host writers and ordinary development Compose are refused or
unsupported; container absence and polling are not substituted for exclusion.

The operator surface prepares schema-0010 cutover and emits the first bound protocol
record. It does not initialize a fresh protocol, migrate/activate a new deployment,
validate API startup, repair arbitrary protocol histories or implement later P3
retention/rebuild capabilities. Canonical reports contain evidence identities,
digests and finding codes, not credentials or payload bytes.

The user explicitly changed static lint scope to `src/` during this attempt.
Makefile, mypy/ty roots, CI wording, AGENTS, the implementation workflow and current
developer documentation were reconciled. Test execution and migration schema-map
validation remain required. Earlier teaching-file Ruff/format failures are retained
as historical evidence; no teaching file was edited by this implementation.
