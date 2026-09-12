# M1a validation and duplication cleanup — 2026-09-09

Current continuation: M1a independent functional verification passed on 2026-09-11;
see [the independent report](p3-evidence/m1a/verification1/report.md). The 2026-09-09
results and capacity limitation are preserved as history.

M1a has **independent functional acceptance**, and P3 remains **todo**. The native duplication
gate still fails. This work does not authorize deployment or implement the M1b/M1c
writer-exclusion, legacy-verification, cutover or startup workflows.

## Changes in this continuation

- Reviewed verified completion, immutable commit intents, concurrent retries,
  crash boundaries, and migration refusal against the implementation plan.
- Established disposable PostgreSQL 16 test containers through the running Podman
  machine and executed the real-adapter tests.
- Added completion admission: one copy per Raw-store instance by default, with a
  configurable 1 GiB free-space reserve. API configuration exposes both limits.
  Expected-byte reservations release after installation/cleanup, including failure
  and cancellation. Installed payload replay needs no new copy capacity.
- Consolidated complete-write handling and fixed zero-progress positional writes
  so they raise EIO instead of looping forever. Short-write tests preserve exact
  file contents, offsets and atomic pointer replacement.
- Shared hierarchy description invariants, adapter-specific conditional updates,
  and core generation publication without changing their transaction ordering.
- Shared discovery calculations, resource-scope resolution, binding transport
  mechanics, actor/claim checks, and owned-file resolution. Scope-specific policy,
  discovery-before-permission errors, and fresh core authorization remain explicit.
- Added a small HTTP integration test using the real PostgreSQL and POSIX adapters.
  Separate application lifetimes prove completed uploads persist, publication
  replays once, changed metadata conflicts, a foreign writer is rejected, and
  downloaded files retain their bytes. Authentication uses development headers;
  this test is not production identity-provider or real-socket acceptance evidence.

## Required behavior and evidence

| Contract | Evidence |
| --- | --- |
| Stale upload descriptors cannot alter final payload | `tests/unit/test_rawstore_materialize.py`: held-descriptor writes after publication; distinct installed inode; sealed files; no-replace races |
| Candidates are closed and durable before installation | Materialization tests inspect open descriptors, inject fsync/ENOSPC/cancellation failures, and kill a subprocess after copy, fsync and installation |
| COMPLETE records attest installed bytes | `tests/contract/test_ingest_process_death.py`: actual process death before/after PostgreSQL COMPLETE commit; retry retains the installed inode |
| Competing completion cannot regress the winner | Real PostgreSQL completion races with matching and corrupt attempts; installed inventory and final ledger remain consistent |
| Commit intent and retries agree on every byte | `tests/contract/test_commit_intents.py`: persisted immutable evidence; distinct clocks; same/different keys; mismatched commands conflict |
| Publication crashes preserve claims and replay once | PostgreSQL/process-death tests cover frozen intent, document installation and final rename; one revision, audit event and outbox event |
| Existing final evidence must match | Rawstore inspection and ingest crash/replay tests reject wrong identity, metadata, manifest, payload and inventory |
| Missing roots cannot be recreated by stale writers | Descriptor traversal/materialization tests cover relocated roots, ancestors, symlinks and delayed writers |
| Migration and recovery vocabulary preserve claims | Real PostgreSQL tests exercise 0011 nonterminal-session refusal, immutable intent constraints, RECOVERING state and revision-number predicates |
| Hierarchy updates retain domain and transaction rules | Shared hierarchy scenario plus direct entity/core tests cover stale versions, immutable slugs, no-ops, missing records, visibility and rollback; PostgreSQL executes the same contract |
| Authorization remains enforced at reusable operations | Core tests cover claim ownership, file membership, hidden targets, forbidden writers and refusal precedence; HTTP tests cover unchanged scopes and OpenAPI path parameters |
| Copy admission is bounded and recoverable | `test_rawstore_completion_admission.py` and `test_api_completion_capacity.py`: queuing, expected-byte reservations, low-disk refusal/replay, release on failures and configuration wiring |

## Duplication gate

The locked pyscn version remains **1.31.1**, and the required native score remains
**at least 90/100**. No exclusions, weaker thresholds, diagnostic suppressions or
replacement scoring formula were added.

| Measurement | Before this continuation | After the tested refactors |
| --- | ---: | ---: |
| Native duplication score | 45 | 50 |
| Cloned fragments | 249 / 790 | 241 / 800 |
| Clone pairs | 361 | 319 |
| Clone groups | 55 | 60 |

Group counts can increase as larger groups split; they are not a count of removed
business rules. The native score is calculated from the cloned-fragment fraction.
The [pinned analyzer](https://github.com/ludo-technologies/pyscn/blob/v1.31.1/domain/analyze.go)
uses the [shared scoring calculation](https://github.com/ludo-technologies/polyscan/blob/core/v0.2.7/core/domain/scoring.go).
Its rounding means a score of 90 requires a cloned fraction below 7.5%: with 800
fragments, at most 59 may be classified as clones.

Inspection also found structural matches that remain after behavior is shared:
26 unrelated DTO/value declarations, typed row decoders, protocol and pagination
methods, and one-line scope-specific guards and binding endpoints. An independent
inventory review counted 72 distinct examples of these structural matches in the
intermediate report `analyze_20260909_173258.json`. That is an assessment of this
code shape, not proof that no future design can meet the threshold. The 90 target
is unresolved; reaching it cannot be represented as a small remaining cleanup of
copied rules. Distinct domain types and public interfaces were not coalesced solely
to change a detector result.

## Final verification

These runs followed completion of the source edits. No selected tests were skipped.

| Gate | Result |
| --- | --- |
| `uv run pytest -m unit --cov=src/huron --cov-report=term-missing` | **1,423 passed**, **94.75%** coverage; unchanged requirement 94.71% |
| `uv run pytest -m 'contract or integration'` with the Podman environment below | **31 passed**: 30 contract tests and 1 integration test; real PostgreSQL 16 and local POSIX storage |
| `make lint` | **Failed only at duplication**: native score 50/100, requirement at least 90 |
| Static checks before duplication | Ruff lint/format, pydoclint, strict mypy, ty, nine import contracts, schema-map, radon, complexipy and `pyscn check` passed; both configured radon commands emitted no flagged entries |
| `make docs` | Strict build passed |
| `git diff --check` and new delivery-record links | Passed |
| `make test-acceptance` | **Not run**: about 5.8 GiB free, below the P3 25 GiB requirement |

The tests emitted existing testcontainers and FastAPI/Starlette deprecation
warnings. Earlier focused runs additionally established admission's 100% line and
branch coverage; the final full unit run covers both new completion admission and
shared materialization write handling at 100% line coverage.

Local command transcripts are `/tmp/huron-unit-final.log`,
`/tmp/huron-real-adapters-final.log`, `/tmp/huron-lint-final.log`, and
`/tmp/huron-docs-final.log`; these are temporary local evidence, not committed
test artifacts.

The final complete pyscn report is
`.pyscn/reports/analyze_20260909_173912.json`: all 109 source files analyzed,
none skipped. The separate overall health score is not the duplication gate.

## Real-adapter environment

The Podman machine was already running; PostgreSQL 16 and the testcontainers
reaper image were cached. No production database was selected or migrated.
Each test owns and removes its disposable PostgreSQL container.

For this machine, the test invocation used:

```sh
DOCKER_HOST=unix:///var/folders/3t/dsbbphj948x65zmvkftl97580000gn/T/podman/podman-machine-default-api.sock \
TESTCONTAINERS_DOCKER_SOCKET_OVERRIDE=/run/podman/podman.sock \
uv run pytest -m 'contract or integration'
```

The forwarded socket is machine-specific. Resolve it with
`podman machine inspect --format '{{.ConnectionInfo.PodmanSocket.Path}}'` rather
than assuming this path on another host. Podman inspection and test execution
needed access outside the Codex filesystem sandbox; automatic approval permitted
these scoped commands. No application deployment settings were changed for it.

## Independent review and limits

Separate agents reviewed M1a core/catalog/PostgreSQL behavior, hierarchy refactors,
authorization refactors, completion admission, write handling, and the integration
test. They reported no actionable correctness or security regressions. This does
not override failing gates.

The filesystem has approximately **5.8 GiB free**, below P3's **25 GiB** minimum
for the changed 9 GiB acceptance flow. `make test-acceptance` was not run. Smaller
filesystem and PostgreSQL tests do not substitute for that acceptance evidence.
No NFS cross-client behavior, old-writer exclusion, cutover, or deployment readiness
is certified. Completion capacity accounting is local to one store instance;
other replicas, uploads and held descriptors still affect available storage.

Validation was performed on an uncommitted working tree. Pre-existing M1a,
tooling, instruction and other working-tree changes were preserved.

## Local functional acceptance receipt — 2026-09-11

The existing M1a implementation now passes the full-size local acceptance test
and the real PostgreSQL/POSIX suites. Independent functional verification later
passed; its separate [report](p3-evidence/m1a/verification1/report.md) preserves
the independently rerun commands and source identity.
Overall repository gate: **FAIL — native duplication remains 55/100, below 90**.
The agreed execution priority allows functional progress with that reported
quality failure; it does not certify release or deployment readiness.

The seven M1a implementation requirements and crash/concurrency matrix were
checked against current source and tests. All 115 production Python files match
the independently verified D3a source identity; no production code or migration
was changed in this attempt. The scoped changes enforce the 25 GiB acceptance
prerequisite, test its refusal/boundary behavior, record completion/commit timing,
and correct the Makefile, repository instructions and testing guide.

| Gate | Result |
| --- | --- |
| `make test-acceptance` | Exit 0; **1 passed**, no skips; interrupted 9 GiB upload, 144 × 64 MiB parts, exact streamed download; 90.41 seconds |
| `uv run pytest --cov=src/huron --cov-report=term-missing` (also JSON output) | Exit 0; **1,434 passed**, **94.96%** coverage; floor remains 94.96% |
| `uv run pytest -m contract` | Retry exit 0; **30 passed**, real disposable PostgreSQL 16 and POSIX |
| `uv run pytest -m integration` | Retry exit 0; **13 passed**, real disposable PostgreSQL 16 and POSIX |
| `make lint` | Exit 2 at the final duplication gate only; all preceding commands exit 0 |
| Static lint constituents | Ruff lint/format, pydoclint, mypy, ty, all 9 import contracts, schema-map, radon and complexipy pass; both radon commands have no flagged entries; `pyscn check` exits 0 |
| Native duplication, `src/huron` and separate `src` scan | Both check scripts exit 1; **55/100**, **210/799 fragments**, **247 pairs**, **57 groups**; all 115 files analyzed, none skipped |
| `make docs` | Exit 0; strict build |
| `git diff --check` | Exit 0 |

The first contract/integration attempts failed because the prior Podman launcher
session had ended and its socket refused connections; these logs are retained.
Starting the existing VM and running both suites in the same live shell restored
the infrastructure. The suites then passed without test or application changes.
No production database was used. Existing third-party deprecation warnings remain.

The real-socket acceptance uses memory database stores, actual local APFS files,
and uvicorn/httpx with development headers. It is **separate evidence** from the
real PostgreSQL suites and does not establish a PostgreSQL-backed 9 GiB run.

| Observation | Measured value |
| --- | ---: |
| Free capacity before the run | 60,035,276,800 bytes / 55.91 GiB |
| Sampled peak allocated fixture-file blocks | 19,339,444,224 bytes / 18.01 GiB |
| Minimum sampled free filesystem capacity | 40,686,743,552 bytes / 37.89 GiB |
| Completion request duration | 25.140104 seconds |
| Commit request duration | 11.347745 seconds |

An external observer sampled `st_blocks * 512` across unique fixture inodes and
filesystem free space about every 0.2 seconds. The 441 retained samples are not an
exact instantaneous maximum: traversal is non-atomic, and the file-block total
excludes directories, filesystem internals and open-unlinked files. Filesystem
free space also includes unrelated consumers. No physical write amplification or
block-I/O counters were measured. Durations are single local client observations,
including the work of each HTTP request, not performance guarantees.

The single-run prerequisite allows 18 GiB for coexisting upload/candidate files
plus 7 GiB headroom, including the default 1 GiB completion reserve. The source is
sparse and the download streams. Concurrent runs or retained descriptors require
additional accounting; this check reserves no space against other writers.

Full command logs, source hashes, exact native analyzer reports, timing XML,
storage samples and the observation script are under
[`p3-evidence/m1a/attempt1/`](p3-evidence/m1a/attempt1/).
The [implementation audit](p3-evidence/m1a/attempt1/audit.md) maps every M1a item to
implementation and tests and states the measurement limits.

M1b/M1c writer exclusion, full legacy verification, cutover and startup gates
remain required before this protocol is deployable. No NFS cross-client or
old-writer deployment proof is claimed. P3 stays incomplete, and duplication
work stays paused before D3b. No commit, push or deployment was performed.
