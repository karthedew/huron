# P3 — Integrity services: implementation plan

**Superseded 2026-10-15:** the owner retired the legacy cutover, controller and writer-exclusion machinery; this document is kept as history and `design/roadmap.html` owns current status.

Status: **implementation partial; M1c activation/startup and M2–M7 remain open.**
Verified completion and local controller/cutover workflows have
[recorded verification](docs/history.md), including the domain-owned Core migration.
[ADR-0001](docs/adr/0001-controller-generation-is-the-verification-epoch.md) supersedes
the earlier failed endorsement design. Read [P3_DESIGN.md](P3_DESIGN.md) first;
`design/` owns architecture and `design/roadmap.html` owns delivery status.

M1a/M1b sections retain prerequisite contracts; file lists reflect the original
planning tree and must be resolved through the current [Core map](design/core-map.html).
Earlier execution/escalation reports are archived through [Implementation history](docs/history.md).

## Acceptance outcome

An old upload descriptor cannot alter published bytes. An offline, externally
fenced cutover establishes the same invariant for verified legacy revisions.
Abandoned commits recover once without releasing an unsafe revision-number claim.
Integrity failures remain visible and block affected payload reads. Staging cleanup
cannot delete live or published content. A fresh database reconstructs the Raw
inventory, lawful removals and amendments from storage without inventing parents,
authorization history or healthy status for damaged content.

## Execution rules

- **Lint scope agreed 2026-09-11:** static lint targets `src/`; test suites and
  migration schema-map validation remain required separately. Source thresholds,
  coverage ratchets and import contracts are unchanged. `make lint` is canonical.

- Use current [AGENTS.md](AGENTS.md) gates and the committed duplication regression
  contract. The old native-score exception and machine-specific gate receipts are
  historical; they do not override current configuration. Duplication improvement
  remains a separate workstream under `IMPLEMENTATION_PLAN.md`.
- This is implementation guidance, not permission from the planning task to run
  migrations, revoke roles, stop services or delete data. Execute actual cutover
  only in the deployment explicitly selected for implementation/acceptance.
- Preserve unrelated edits, including the existing untracked project OOP skill.
- Use the actual project-local OOP skill for core/catalog/rawstore code, PostgreSQL
  skill for migrations/adapters, and FastAPI skill exclusively for API wiring.
- Do not change frontend or future P4–P10 workflows to satisfy this phase.
- Create consumer-owned ports and wire real adapters in each slice; avoid a pile
  of uncalled infrastructure methods. Keep the existing ingestion adapter split.
- Migration names below are proposed, not already present. Rebase numbering if
  another migration lands; do not rewrite applied migrations.
- Stop a slice when its safety proof fails; revise the implementation/design
  rather than adding timing sleeps, a bypass flag, weakened constraints or skips.

## Dependency order and deployable slices

```text
M1a contracts/storage/ingestion ─┐
M1b exclusion/legacy verifier ──┼─ M1c cutover/startup/acceptance ── first deployable slice
                               │
                               └─ M2 governance/evidence/read state
                                      ├─ M3 recovery
                                      ├─ M4 reconciliation/findings
                                      └─ M5 staging cleanup
                                              │
                                  M6 rebuild/activation
                                              │
                                  M7 full acceptance and handoff
```

Implementation can progress in the listed order without delegation. M1a and M1b
are prerequisites within one release, not independently deployable protocol
changes. Ship the first cutover release only after M1c passes; do not wait for
search or governance workflows. M2–M6 extend the certified protocol.

## M1 — Verified publication and mechanical cutover

### M1a. Materialize payload at completion and freeze commit documents

**Files:**

- `src/huron/pkg/rawstore/store.py`, `commit.py`; new `materialize.py` and
  `inspection.py` for closed-candidate installation and streaming verification.
- `src/huron/pkg/catalog/ingest.py`, `documents.py`, `paths.py`, `ports.py`.
- `src/huron/core/_ingest.py`, `raw.py`, `ports.py`.
- `src/huron/pkg/metastore/ingest.py`, `hierarchy.py`, `rows.py`.
- `src/huron/schema/documents/committed-v2.json` plus schema loading/tests.
- `migrations/versions/0011_verified_raw.py`, `migrations/schema.sql`.

**Implement:**

1. Add explicit upload/completion/envelope paths and BeginIngest-only root
   creation. Split write-part input from installed payload. Every later write
   refuses missing session roots, including nested-path and retry helpers.
2. Replace hash-only `finish_file` with verified materialization: stream into a
   private candidate, hash/check exact bytes, fsync, seal, close, then install
   without replacement. Candidates live outside the publishable envelope.
3. Make overlapping completions idempotent. A losing/mismatching attempt cleans
   only its candidate, never another installed file. Persist COMPLETE after
   durable installation; recover install-before-row crashes. Preserve required
   part retry and digest-mismatch behavior with operation-local cleanup.
4. Freeze canonical commit intent on first COMMITTING transition. Retry reads
   frozen bytes; different metadata is a conflict. Stop using mutable replacement
   for immutable manifest/metadata/marker documents. Validate existing final
   evidence before treating publication as replay.
5. Emit COMMITTED v2 and retain explicit v1 decoding for legacy inspection.
   Keep commit as durable rename of `envelope/`; do not move upload/candidate
   areas into final. Correct same-filesystem checks for every publication path.
6. Migration 0011 refuses all nonterminal legacy sessions; add RECOVERING to the
   state CHECK, immutable commit-intent persistence and recovery ownership data.
   Preserve both partial uniqueness predicates: one excludes COMMITTED/ABORTED/
   FAILED, the number claim excludes only ABORTED/FAILED. Update domain state
   transitions and revision-record creation for recovery, not via fake COMMITTING.
7. Update schema-map constraint annotations and conformance tests; do not imply
   that adding RECOVERING requires weakening uniqueness or immutable identities.

**Tests:** extend `test_rawstore_store.py`, `test_rawstore_commit.py`,
`test_catalog_ingest.py`, `test_catalog_documents.py`, `test_api_ingest_sessions.py`,
`test_api_ingest_crash_matrix.py`, `tests/hierarchy_contract.py` and real adapter
contracts; add focused materialization tests.

- A trickled part request retains its descriptor while another copy is received,
  completed and published; finishing the held write cannot change published bytes.
- Two completions install exactly one valid independent file; failed completion
  cannot delete a concurrent winner or reset a completed ledger.
- Crash after copy, after fsync, after installation, before/after COMPLETE row;
  retries converge, no temporary file enters final, no row attests missing bytes.
- Delayed document writer and delayed completion cannot recreate staging after
  relocation/publication. Verified candidates are closed before installation.
- Concurrent commit attempts use identical document bytes/instant; mismatched
  metadata conflicts; stale attempts cannot overwrite an installed document.
- Existing final marker with wrong revision, manifest or metadata is refused.
- All no-replace installation crash points preserve canonical/independent-file
  rules. Zero-byte files, nesting, path attacks, ENOSPC and cancellation covered.

**Exit:** focused unit and real filesystem/PG contracts pass. No production
cutover yet; M1b/M1c are required to run the new protocol.

### M1b. Exclusion adapters and a complete legacy verifier

**Files:** new `src/huron/core/integrity/{ports,cutover,verification,models}.py`,
`src/huron/applications/lakectl/{main,settings,wiring,exclusion}.py`,
rawstore `inspection.py`/`maintenance.py`, schema protocol record/report files,
`pyproject.toml` entry point and import-linter contracts; deployment configuration
in `docker-compose.yml`, `deploy/controlled/`, and operator documentation.

**Implement:**

1. `WriterExclusion` port exposes authenticated operator/root identity, current
   writer inventory, termination and continuous restart/access exclusion evidence.
   Implement controller-managed Compose evidence first. Treat unmanaged host
   writers and unreachable nodes as refusal until a suitable provider supplies
   actual termination/storage fencing. Do not silently equate container absence
   with complete writer inventory.
2. Separate dedicated app/cutover DB identities from the development database
   owner. Verify disabled old login, no surviving old sessions, effective access
   through role inheritance/ownership, and new-role exclusion during verification.
   Old binaries never receive new credentials. Test against real PostgreSQL.
3. Full legacy verification streams every payload and validates document bytes,
   names, identity, seal, owner and regular-file link count. Report missing or
   corrupt documents accurately. Imports use trustworthy identity only.
4. Create canonical per-revision report entries and a root/run identity; bind
   reports to numbered cutover records by digest, fsync report before record.
   Exact membership determines VERIFIED legacy status. Record findings for
   corruption without certifying those entries.
5. Use a narrowly scoped maintenance adapter for schema 0010. It resolves legacy
   sessions and writes existing audit/findings before migration; it is not an
   API fallback or general old-schema compatibility layer.
6. Require process-exclusive storage ownership through settled writes. The
   controller's persisted generation is the verification epoch (ADR-0001):
   `establish` mints it, every failed observation, `abandon` and restart end
   it, and a stateless `validate` admits only a record whose fence names the
   live generation and the bound database identity. File presence never
   establishes admission; a lost reply is resolved by validating again.
7. Define authenticated maintenance grants in core; CLI actor text alone cannot
   authorize certification. Report evidence without credentials or file contents.

**Tests:** new `tests/unit/test_integrity_cutover.py`,
`test_protocol_documents.py`, `tests/contract/test_writer_exclusion.py`,
`test_integrity_store.py`, `tests/integration/test_protocol_cutover.py`.

- SQL role rejection and termination tested separately from an old request that
  already passed its database check; the latter needs process shutdown evidence.
- Old release restart uses the actual old application artifact and revoked
  identity. Observe failed readiness/write access; do not spoof old version input
  to new startup code. Pin the pre-change artifact digest in the test fixture.
- Foreign writer/startup, unreachable node, lost DB fence, changed database
  identity or lost proof mid-scan end the epoch; the record is refused
  afterwards even if the condition is restored.
- A report without its record is history; the next `--prepare` appends the
  next sequence number; any epoch end forces a full rescan.
- Corrupt legacy payload is reported DEGRADED without blocking healthy inventory;
  ambiguous identity/missing parent blocks certification.

**Exit:** the adapter has an enforceable complete deployment contract. If only
local test evidence exists, record that limit and refuse unsupported deployment
certification; no fabricated production readiness.

The implemented local provider uses a private root-owned Linux engine and named
volume, with a serialized controller as the application's only restart authority.
See [the operator contract](docs/operations/controlled-cutover.md). Trusted host,
engine and database administrators provision that boundary; ordinary application
or automation users have no alternate daemon/storage grant. The development
Compose stack remains explicitly unsupported for certification. The earlier failed
M1b attempts and authority redesign are [archived](docs/history.md); ADR-0001 and the
current Integrity/controller tests describe the implemented model. Local verification
does not mark M1c delivered or certify an NFS deployment.

### M1c. Cutover, migration and startup as one deliverable

**Files:** M1a/M1b files; `src/huron/applications/api/app.py`, `settings.py`,
API error mappings; `.github/workflows/acceptance.yml`, acceptance fixtures and
`docs/getting-started/` operator instructions as appropriate.

**Implement:**

1. Wire `lakectl protocol init` for genuinely empty roots. **Roadmap drift
   (2026-09-12):** `lakectl protocol cutover --validate --sequence N` moves out
   of this item into the M1b authority plan, because it is the only operator
   resolution of a lost `validate` reply that does not rescan
   (see the [archived authority design](docs/history.md#archived-plans-and-investigations));
   `protocol init` and API startup gating stay here. API startup
   requires a valid initialized/cutover root and compatible schema head before
   serving. Do not let startup certify a legacy root.
2. Prepare verifies final orphans and terminalizes legacy sessions under exclusion.
   An ambiguous final identity blocks, not fails-and-reuses its number. Migration
   refuses remaining nonterminal sessions. Validate before re-enabling the new app.
3. Gate schema 0010 support to the maintenance command. New app uses supported
   head/protocol; old binary exclusion remains external. Establish crash receipts
   across prepare/report/record/migration/activation without a distributed transaction.
4. Update current entry points and deployment defaults coherently; `make stack`
   must not start an uninitialized writer automatically. Provide explicit init/
   cutover instructions rather than weakening startup for development.
5. Raise calculated acceptance disk requirements for verified completion; keep
   the interrupted 9 GiB real-socket upload/download gate at the real part size.

**Acceptance:** new `tests/acceptance/test_raw_protocol_cutover.py` plus the
existing `test_raw_ingest_gate.py`.

- Orphan final, all COMMITTING storage states, lapsed upload, corrupted legacy
  revision: exact terminal states, spent/free claims, DEGRADED inventory exceptions.
- 0011 fails until sessions resolved. Empty-root init and legacy-root rejection.
- Backdated v1 planted after cutover is unknown; modifying COMMITTED invalidates
  report membership. No historical marker rewrite.
- New v2 normal commit and legacy reads work after activation; no lingering writer
  can mutate verified legacy bytes. Crash each ordered cutover boundary and resume.
- NFS multi-client verification of no-replace install, directory rename, stale
  handles and writer shutdown is mandatory before shipping to an NFS deployment.

**Exit/release:** `make lint`, unit coverage, contract, integration, acceptance
and docs gates pass. Operator evidence names actual storage/deployment tested.
This is the first deployable P3 slice; the remaining phase stays incomplete.

## M2 — Governance evidence, lifecycle and read admission

**Files:** new catalog `governance.py`/`integrity.py`; governance/protocol JSON
schemas; core `integrity/governance.py`, `revisions.py`, `_revision_reader.py`,
ports; metastore `integrity.py`; proposed `0012_integrity_evidence.py`; API
revision DTO/error mapping; `pkg/rbac/roles.py` and corresponding role migration.

**Implement:**

1. Versioned PURGED, expiry and amendment document values with canonical decoding,
   full identity binding, disjoint sequence selections and reused amendment fold.
   Keep intent/start separate from completion. Match exact retained manifest
   entries. PURGED precedence explains intentional loss of expiry documents.
2. Persist mirrors and digests, lifecycle/integrity observations, pending state,
   run receipts and findings. Do not synthesize genuine purge approvals, audit or
   holds from a reconstructed marker. Persist a governance-restored readiness gate.
3. Implement the legal-removal state evaluator once for scans, reads and rebuild.
   DEGRADED overlays derived lifecycle; clearing health must not undo lawful removal.
4. Add SYSTEM integrity.read/maintain for platform_owner and distinct externally
   authenticated maintenance grants; no broad Raw write grant for service accounts.
5. Apply D-7/D-10/D-11/D-15 at core admission. Resolve visibility first, preserve
   404/403 semantics, distinguish 409 pending/recovery/integrity and 410 removal.
   Metadata/manifest need their own trust checks. Do not cancel admitted streams.
6. Rename latest_committed query/port to latest_revision and align memory/PG on
   highest revision number regardless of state. Allocation continues over all
   spent revisions; it must not reuse PURGED, EXPIRED or DEGRADED numbers.

**Tests:** domain properties for canonicalization/sequence/set membership,
`tests/unit/test_governance_documents.py`, `test_revision_integrity.py`,
`test_core_revision_access.py`; real mirror/constraint contracts and API tests.

- Wrong revision/digest, gaps/duplicates, overlap, absent intent, pending/complete
  expiry/purge, purged expiry evidence and partial mirror cleanup.
- Lost amendment reclassification never broadens access; valid DB history fallback
  is independently checked. DEGRADED blocks every new payload read.
- Held download completes while a new blocked download fails. Latest returns the
  newest identity without silently selecting an older healthy revision.
- Missing governance after rebuild does not authorize continuation.

**Exit:** one shared evaluator governs scans/reads/rebuild; all adapters agree.

## M3 — Abandoned commit recovery

**Files:** core `integrity/recovery.py`, ingestion heartbeat, recovery ports,
rawstore maintenance/materialization, metastore recovery claims; CLI recover;
API recovery-in-progress error mapping.

**Implement:**

1. Dedicated 30-second heartbeat during storage work, 5-minute candidate grace;
   heartbeat does not change client etag. Fence COMMITTING → RECOVERING.
2. Persist a unique attempt and paths, claim by relocating the whole session tree;
   never time-expire recovery ownership. Validate actual observed storage state.
3. Marker-present recovery retains one validated document set, checks file ledger,
   copies/hashes into fresh candidate inodes, closes/seals/publishes and records
   exactly once. Matching final v2 import has no redundant payload copy.
4. Marker-absent owned tree can fail; unexplained missing tree, invalid marker or
   identity disagreement stays locked. Every stale database mutation is fenced.
5. Enforce automatic 100 GiB cap, one copy at a time and reserve checks. Explicit
   large-copy command still respects capacity and ownership. A stopped recoverer
   needs external process/fencing proof before a new attempt can resume.

**Tests:** unit decision matrix, real PG CAS/claims, real filesystem descriptor
races, `tests/integration/test_raw_recovery.py`.

- Delayed writer in fsync, metadata installation, part stream and post-rename row
  transaction; exactly one revision, no changed published bytes or reused identity.
- Old descriptor writes into relocated original after publication; candidate stays
  byte-identical. Metadata replacement during scan never publishes a mixed set.
- Two recoverers; driver retry vs recovery; recovery crash at every checkpoint;
  lost response after successful transaction; no premature lock release.
- Capacity refusal/ENOSPC/cancellation; no marker invented and no partial final.

**Exit:** full crash/race matrix passes against real adapters, not mocks alone.

## M4 — Reconciler, findings and guarded continuation

**Files:** core `integrity/{reconcile,verification,findings,governance}.py`,
rawstore inspection/maintenance, metastore integrity/findings, CLI commands,
API read-only `/admin/reconciliation/report` and DTOs; proposed
`0013_integrity_runs.py` if not already covered by M2.

**Implement:**

1. Streaming fast scan + budgeted full hashing with durable file progress, oldest
   first, oversize-file handling and explicit overdue reporting. Full completion
   stamps require every relevant check; invalidated evidence resets progress.
2. Implement every finding/action row from design §8. Only validate-and-import
   missing records, repair derived pointers/indexes, reseal verified known content,
   and continue validated authorized intents. No silent history overwrite/chown.
3. Dedupe open findings and preserve occurrences, acknowledgements and verified
   resolutions. Separate severity from repair outcome and public revision state.
4. Shared mutation coordination for derived writes and current generation snapshots.
   Do not repoint CURRENT past an invalid conflicting newer generation.
5. Implement continuation of existing intents only behind authoritative governance
   and a shared mutation barrier. Lost ownership is indeterminate and cannot be
   time-reclaimed. P5 future hold/pin/reclassification writers must share this
   contract. No P3 policy selection, request/approval or scheduler for new removal.
6. Purge cleanup includes expiry documents/mirrors; audit/findings avoid retaining
   removed file details. Rebuild remains non-destructive regardless of flags.
7. CLI JSON/text results and exit codes; read-only scoped keyset report through core
   authorization. No HTTP apply route. Schedule nightly/on demand; do not claim
   object-store scans, telemetry exporters or P4 projection exist.

**Tests:** `test_integrity_reconcile.py`, `test_integrity_findings.py`,
`test_governance_continuation.py`, real PG concurrent findings/import contracts,
API report authorization/pagination, integration tests with real POSIX + PG.

- Byte flip, truncation, noncanonical/invalid document, unexplained absence,
  hardlink, wrong owner, seal, extra/symlink entry, CURRENT/INDEX variants.
- Partial scan never resolves omitted findings; acknowledgement changes no health;
  repaired purge returns PURGED, not COMMITTED; no starvation past byte budget.
- Existing purge/expiry intent interrupted at each unlink/fsync/database edge;
  pending vs complete lawful outcomes. Hold blocks subsequent deletion, missing
  governance blocks all deletion, DB disconnect does not allow unsafe takeover.
- Concurrent scans/imports produce one record and one open finding occurrence.

**Exit:** findings table is mechanically complete; every automatic repair has an
observable regression test and current-authority proof where destructive.

## M5 — Staging-only cleanup

**Files:** core `integrity/sweep.py`, rawstore maintenance traversal/claims,
metastore cleanup receipts, CLI sweep and scheduling config.

**Implement:**

1. Eligibility over terminal session trees, grace, 24-hour unknown trees and
   authoritative ledger coverage. Refuse during database loss/rebuild ambiguity.
2. Guard from design §10, with exact reported numerator/denominator/floor.
3. Recheck candidates, claim/rename into trash, fsync, no-follow recursive removal;
   durable identity supports interrupted cleanup. Never follow final-tree links.
4. Distinguish recovered originals, active candidates, existing trash and unknown
   names. No arbitrary path input or root recreation. Dry-run mutates nothing.

**Tests:** real temporary filesystem sweeper contract and concurrent integration.

- Active upload/recovery never deleted; late stream cannot resurrect session root;
  published bytes unaffected. Link/path escape rejected.
- Fraction guard at boundary, small-population floor, no-session age, terminal
  grace, dead DB, renamed trash recovery and dry-run immutability.
- Cleanup may leave open-unlinked bytes allocated; reporting does not promise free
  disk merely because names are gone.

**Exit:** every deletion is demonstrably inside staging with fresh eligibility.

## M6 — Storage-only rebuild and controlled activation

**Files:** core `integrity/rebuild.py`, run/checkpoint ports; metastore rebuild
batches; CLI rebuild/validate/activate; protocol/governance inventory readers.

**Implement:**

1. Claim a fresh migrated target by run/root ID. Same run can resume; unrelated
   populated targets are refused. Exclusion remains active across all phases.
2. Inventory protocol → hierarchy → revisions/governance → amendments → releases
   → indexes. Use ID/digest idempotency and transactional batch checkpoints.
3. Restore consistent structural inventory and explicit DEGRADED/pending states.
   Never synthesize parents, grants, approval rows, old audit/outbox or open sessions.
   Recognize valid later purge of a legacy verified manifest through retained
   marker/inventory digests. Expiry mirrors removed by purge stay removed.
4. Report activation blockers separately from retained corruption. Access restore
   gates activation; governance readiness independently gates deletion workers.
5. Bind validation receipt to source inventory/run/target. Activate marks readiness,
   never silently switches the deployment. Revalidate stale receipts/fences.
6. First full reconciler run must match the validated inventory/findings. Include
   exact state/metadata/release/amendment comparisons, not row counts alone.

**Tests:** `tests/integration/test_storage_rebuild.py`,
`tests/acceptance/test_integrity_rebuild_gate.py` with real PostgreSQL and storage.

- Drop database, migrate, rebuild exact hierarchy/revisions/releases/amendments,
  lawful purge/expiry, pending intent and corrupted revision.
- Kill each batch/phase and resume the same run with no duplication; wrong run,
  wrong root, changed report or unrelated target refused.
- Missing parents and identity collisions block activation; DEGRADED payload with
  trusted identity/access does not. Lost RBAC and unknown classification do block.
- Storage-only pending purge removes nothing; restored hold prevents continuation.
  Unknown backdated v1 remains an operator finding after rebuild.

**Exit:** the P3 database-loss gate passes with full inventory comparisons and
no fabricated governance authority.

## M7 — Phase acceptance, design reconciliation and release

- Run the entire verification matrix below after affected slices pass focused
  feedback. Re-run only when changes or failures justify it.
- Reconcile `design/layer-raw.html`, `architecture.html`, `catalog-search.html`,
  `api.html`, `rbac.html`, `roadmap.html` against final code and actual receipts.
- Update `Makefile` acceptance description, disk checks and operator commands;
  CI must execute the new integration tests, not succeed with none collected.
- Keep P2's historical passing receipt; record P3 protocol change and fresh gates.
  Mark P3 complete only when every applicable gate and real deployment proof passes.
- Document tuning defaults and acceptance storage/environment, measured copy cost,
  any unresolved environmental limit, and the cutover/activation rollback boundary.
  After the cutover, rollback to an unfenced P2 writer is prohibited.

## Commands and evidence

Use the current repository gates. Deployment certification additionally requires
the actual exclusion and storage proofs; local functional acceptance does not
establish production or NFS support.

```sh
make lint
uv run pytest -m unit --cov=src/huron --cov-report=term-missing
uv run pytest -m contract
uv run pytest -m integration
make test-acceptance
make docs
git diff --check
```

`make lint` includes Ruff/format, pydoclint, strict mypy, ty, import-linter,
schema-map, radon, complexipy and pyscn; inspect reported grades, not only exit
codes. Plain pytest and `make test` select unit tests. Preserve coverage thresholds.
Acceptance requires at least 25 GiB free disk for the changed 9 GiB flow and more
for concurrent cases; calculate each fixture's peak. Do not reduce part size or
file size merely to evade the gate. Real PostgreSQL and real NFS tests need their
actual services and deployment evidence. Report missing infrastructure as an
unpassed gate, never as a pass or a skipped test added to green CI.

For this planning-only change: validate local links/anchors, paths, plan/design
consistency and `git diff --check`; run strict docs build if site content changes.
Python/application tests do not validate these documents and are not required
until implementation starts.

## Historical execution and escalation

The original planning receipts, failed M1b attempts and authority redesign are
linked from [Implementation history](docs/history.md). The
[archived escalation](https://github.com/karthedew/huron/blob/7846d67a4c404a00830a6bb7d9255978ee5cfe32/P3_IMPLEMENTATION_PLAN.md#escalation)
records why endorsement was replaced by the controller generation as verification
epoch. [ADR-0001](docs/adr/0001-controller-generation-is-the-verification-epoch.md)
contains the accepted rationale and continuing failure/retry semantics.
