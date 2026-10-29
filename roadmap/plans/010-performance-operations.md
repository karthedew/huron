# Phase 010: performance, NFS and operations qualification

Status: BLOCKED — nominated hardware/capacity, 001 early probes and implemented 002–009 prerequisites.

## Context and outcome

Existing acceptance/test_raw_ingest_gate.py transfers one interrupted/resumed 9 GiB
file with local real POSIX storage and in-memory hierarchy over a real socket. It
does not prove NFS, PostgreSQL workflow load, tus, 50 users or production SDK/UI.
Complete target now requires 50 distinct authenticated users × 10 GiB across 50
datasets = 500 GiB newly uploaded content. Measure through committed readable
full-copy releases and search under load, not final PATCH. Same-dataset contention
is a separate correctness scenario. User approved hardware baseline BEFORE time SLO.

Raw uses POSIX/NFS with independent copies, base pins and storage-first/DB receipt
recovery; no cross-release hardlinks. Developer stack target includes PG16/migrations/
API/persistent Raw/frontend/directory/local OIDC and Google config/pinned k6 profile.
MinIO optional later. All must be implemented/verified in prior phases, not assumed
because make stack runs today's backend containers.

Fresh deployment approved 2026-10-06: no legacy-data conversion/rehearsal requirement.
Fresh schema bootstrap/Alembic still applies; nonempty deployment targets refuse and
surface operator action, never reset files/data/volumes. This does not waive existing
controlled-cutover, crash/recovery, authorization, durability or replay coverage;
no-sudo runner is still a provisioning blocker, not grounds to delete tests.

## Prototype evidence

None run. Phase 001 performance owner supplies the exact k6 version/image digest,
version-matched official filesystem API and minimal fixture-based buffer receipt:
root `k6 run --vus 2 --iterations 2 roadmap/prototypes/k6-buffers.js` after explicit
provisioning. Phase 002 consumes that pin in its minimal opt-in profile. This phase
owns actual-stack generator qualification and scale measurements, not the initial
pin/API selection. Repeat the bounded probe against implemented tus and measure RSS,
fd lifecycle, shared-file semantics and retries before scaling. No k6 version or
receipt is claimed installed/qualified today; pin changes require renewed bounded
API proof and profile review before any run, not retroactive evidence for 002.

This phase owns the first actual-NFS evidence: repeat 001 local tus/release crash
scripts on nominated actual NFS mount (dedicated owned
test directory) and verify locking/fencing/fsync/rename across at least two API
processes/hosts as deployment requires. Local ext4 evidence is not NFS evidence.
Operator/user must supply hardware/topology/capacity, then approve eventual SLO
after observing baseline. No arbitrary throughput/completion-time promise.

## Exact scope and ownership

- Proposed `tests/performance/` deterministic micro/workflow benchmarks and
  `tests/load/raw_mvp.js`, load fixtures/README, `tests/load/thresholds.json` after SLO
   approval; extend the 002-owned minimal pinned k6 Compose profile with the full
   workload using the 001-qualified image digest, no broad service restart.
- `pyproject.toml` performance/load marker registration only for actual Python tests;
  Makefile and CI dedicated opt-in tasks, no plain unit command secretly running load.
- `scripts/qualify_raw_capacity.py` and `scripts/check_load_receipts.py` new owned
  scripts: preflight topology/free-space/generator capability; verify all expected
  users/datasets/release receipts/read checks and emit machine-readable evidence.
- `docs/operations/raw-mvp.md` new runbook and current controlled-cutover docs update;
  metrics from applications API settings/runtime and rawstore/database public seams
  only through separately reviewed instrumentation slice if absent. No weakening
  thresholds or exposing credentials/full inaccessible metadata in telemetry.
- Existing tests/acceptance/test_raw_ingest_gate.py, tests/contract process-death/
  writer-exclusion/maintenance ownership, integration/test_protocol_cutover.py remain
  regression obligations. Preserve meaningful tests/scoped fixtures during type/owner
  organization; tests/{unit,contract,integration,acceptance,performance,load} target.
- No removal of user datasets/volumes; cleanup only manifest-listed owned load data
  after captured evidence and approved retention window. No production promotion.

No migration shims. Operator explicit capacity reservation/disposition before runs;
retained base releases, staging and independent candidates can multiply storage.
Provision >500 GiB peak capacity, calculate real worst-case coexistence plus reserve,
database/WAL/log space and generator source space. 500 GiB alone is insufficient.

## Interfaces and implementation examples

Proposed receipt/metrics contract, illustrative:

```text
run_id, user_id, dataset_id, submission_id, release_id
admission_wait_ms, transfer_ms, verify_copy_ms, commit_ms, readable_ms
bytes_sent, retries, errors_by_code, search_latency, search_freshness
```

Each VU obtains a distinct approved authenticated identity mapped to directory and
Huron grants; never emulate 50 users with one admin bearer or untrusted dev headers.
Directory admin is not Huron data reader. Credential refresh/revocation/outage cases
use the qualified 003 broker and local fixture; Google real login configuration
separate from automated load credentials. No secrets in reports.

VU creates/names its dataset with valid metadata+schema and sends only new content,
sequential tus PATCH per file with bounded buffer, across-file concurrency limit.
HEAD reconciles ambiguous offsets; completion polls until receipt committed/readable.
Verify manifest and streamed downloads/digests, query visibility-filtered PostgreSQL
search during transfers/copies/commits. Additional retained-base-copy run measures
copy amplification and pins/purge interference. Separate same-dataset race asserts
approved stale-base conflict, not silent merge. Keep the upload base immutable;
assert expected-base/current-head comparison is atomic with catalog publication under
qualified serialization, including concurrent first pushes against expected empty
head. Loser candidate stays hidden, no lineage/receipt published, cleanup recoverable,
no unpublished success acknowledgement. Authorized same-identity COMMITTED replay
must still return its original outcome after head advances. Explicit retry resolves
a newer base with new identity/fingerprint and exact pinned metadata/schema inheritance;
no auto-repin, implicit rebase or changed-input identity reuse. Verify typed conflict
(illustrative HTTP 409) through SDK/UI without hidden-source disclosure. Technical
serialization and DB/FS crash evidence remain blocked until actually qualified.
Include cancel, ENOSPC, DB outage
after storage install, restart/recovery and cleanup; published releases stay intact.

Record API worker/process topology, client/file/copy/global limits and same-file
fences, PG pool/WAL/locks/query plans, NFS client/server/mount options/network/disk
bandwidth, generator CPU/RAM/network/fd pressure, peak free/used/reserved bytes,
error/retry breakdown and fair queueing. A saturated generator is not server capacity
evidence. Establish repeatable baseline before agreeing thresholds, then rerun against
approved SLO with same nominated hardware, recorded warm/cold/cache conditions.

## Serial task slices

1. Pending: verify operator nomination/capacity reservation and 001 pin/buffer receipt;
   qualify the 002 profile's bounded generator against the actual stack, finalize
   command/script ownership and metrics contract. No 500 GiB run before preflight.
2. Pending: real NFS multi-process durability/fencing/crash/cleanup qualification,
   persistent-volume restart and operator recovery rehearsal. Full correctness gate.
3. Pending: 50-user/50-dataset 500 GiB fresh-upload baseline plus search, then separate
   retained-copy and same-dataset contention scenarios. Capture complete receipts.
4. Pending: user/operator review baseline and approve SLO; rerun qualification and
   operations runbook restoration/revocation/outage. No automatic production promotion.
All slices serial writer/reviewer, skills below, independent baseline/final reruns
and max 3 reviews. Hardware failures/capacity shortage are immediate blockers.

## Skills

`.agents/skills/oop-design/SKILL.md`, `.agents/skills/fastapi/SKILL.md`,
`.agents/skills/postgresql-table-design/SKILL.md`,
`.agents/skills/implementation-plan/SKILL.md`, `.agents/skills/playwright-cli/SKILL.md`
for operational UI QA; both Svelte skills and Tailwind if UI instrumentation changes.
Consult official pinned k6 documentation, no invented filesystem API.

## Acceptance and complete applicable gates

Root locked uv/Python >=3.12: `make lint`;
`uv run pytest -m unit --cov=src/huron --cov-report=term-missing`;
`uv run pytest -m contract`; `uv run pytest -m integration`; `make test-acceptance`;
`make docs`; `git diff --check`; `uv run python scripts/check_openapi.py --check`;
`uv run python scripts/check_database_schema.py` (002/004 prerequisites).
PG16/testcontainers, isolated Linux/Podman integration runner/historical Git object,
>=25 GiB single acceptance plus separately calculated >500 GiB load capacity and
owned real NFS/generator. No unavailable-infra PASS or exit-5 integration pass.
Keep 96.01% floor, import/complexity/duplication ratchets, radon C+/MI B+ findings;
no skips/xfails/exclusions/suppressions/weaker assertions to pass.

Proposed new commands owned here, NOT currently runnable: root
`uv run python scripts/qualify_raw_capacity.py --profile tests/load/profile.json`;
`k6 run --config tests/load/options.json tests/load/raw_mvp.js`;
`uv run python scripts/check_load_receipts.py --run roadmap/evidence/load-run`.
Author creates/validates profile/options formats, credentials injection and run-path
ownership before execution; no placeholder SLO in options. Add
`uv run pytest -m performance` only after actual marked tests/registration exist.
Pinned image profile command replaces host k6 command if selected; exact pin/command
must be filled before the relevant run slice is READY. Full 50×10 GiB counts and all readable/digest receipts
are pass criteria; throughput/time assessed only against later approved thresholds.

If frontend changes: web cwd autofixer every changed Svelte, `npm run check`,
`npm test`, `npm run lint`, `npm run build`, `npm run test:e2e`; named-session CLI
mobile/816px/wide/light-dark/keyboard/all states with owned endpoint/browser. Reuse
existing fixtures/public behavior, deterministic failure controls and real adapters.
Independent reviewer runs complete applicable gate and qualification, captures
versions/cwd/exits/resources/logs/coverage/limitations, not copied receipts.

## Blockers and readiness

**Entry prerequisites:** operator/user-nominated hardware topology and capacity,
001 local storage and minimal pinned-k6 API/buffer receipts, implemented and verified
002–009 functional stack, independent reviewed bounded assignment and separate run
authorization. No actual-NFS result or approved eventual time SLO is required to
start this phase; producing those results is its job. No run is authorized here.

**Per-slice prerequisites:** slice 1 verifies capacity and creates/qualifies metrics,
scripts, exact profile command and failure-run ownership. Slice 2 requires that
preflight and an owned actual NFS mount, and produces NFS correctness/recovery
evidence. Slice 3 requires slices 1–2, confirmed worst-case capacity reservation
and the implemented stack; it produces the 50-user baseline with no invented time
threshold. Slice 4 first presents that baseline for user/operator SLO approval;
only its qualification rerun requires the approved SLO. Missing SLO approval blocks
that rerun and final qualification, not the baseline that informs the decision.

**Completion criteria:** actual NFS correctness, full baseline receipts, approved
SLO and same-hardware qualification rerun, recovery/runbook evidence and independent
complete gates. Baseline before time thresholds is accepted; the threshold is not.
Independent plan review before `/implement-markdown roadmap/plans/010-performance-operations.md`.

## Execution ledger

Planning writer attempt 1; no load/infra/prototype executed; review 0. Parent logs
role/model/session/times/commands/verdict, one writer/reviewer, minute polls and
15-minute progress even during long load validation; report hangs/errors immediately.

## Escalation / final receipt

BLOCKED draft. No MVP performance PASS from 9 GiB acceptance or concurrent VU count.
Receipt must include hardware, capacity, bounded generator memory, real NFS,
500 GiB authenticated committed-readable results, search/recovery and approved SLO.
