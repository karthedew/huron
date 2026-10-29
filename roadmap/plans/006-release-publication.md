# Phase 006: full-copy releases, base pins and recoverable publication

Status: BLOCKED — atomic serialization/crash prototype, bootstrap and 003–005 results.

## Context and outcome

Current `core/raw/__init__.py` exports separate RawIngestionService,
RevisionReadService and Releases tag operations. Current revisions contain only
submitted files; existing independent-copy completion is useful but does not prove
pinned-base retention. Target one successful push → one immutable full independent
Raw release. Base exact retained files + explicit additions/deletions/replacements;
client uploads new content only, server copies retained files, no cross-release
hardlinks or dependency on base for subsequent reads. Required metadata/manifest,
path/size/checksum/transfer completeness are separate verification obligations.

New dataset requires metadata/schema; later omission inherits exact pinned base
pair, never latest; null rejects and empty object validates. Freeze schema bundle
and descriptive snapshot at submission. Rawstore owns workflow/private FS; Catalog
owns dataset identity/lineage; Security supplies current authorization; asyncpg
records lineage and publication receipt transactionally after durable storage.

## Prototype evidence

None run. 001 owner creates/runs root
`uv run python roadmap/prototypes/release_crash.py --root roadmap/prototypes/data --bytes 1048576`
against disposable PG16 and local real filesystem. Reproduce base retention/purge
race, add/delete/replace, independent inodes, mutate source candidate after copy,
ENOSPC/cancel, storage-install→DB-failure, commit→lost-response and authority revoke
at every publication boundary. Recovery must return same receipt or visible terminal
failure without exposing partial release. Repeat fencing/fsync on real NFS in 010.
Existing tests/contract/test_commit_intents.py and historical 9 GiB are regression
inputs, not this prototype's success. Explicit stale-base conflict was approved
2026-10-06; concurrency/crash proof of its algorithm is still missing.

## Exact scope and ownership

- After 002 combine: `core/rawstore/interface/{submissions,releases,ports,errors}.py`,
  `_impl/{submissions,publication,recovery,retention}.py`, private filesystem
  `{materialize,commit,inspection,maintenance}.py`; preserve existing verified-copy
  safety. Current `core/raw/_impl/{ingest,ingestion,revisions,releases,reader}.py`
  and `core/raw/{manifest,metadata,paths,documents,types}.py` are migration inputs.
- `core/database/schema/{releases,submissions}.py`, repositories/publication.py and
  retention.py; versioned Alembic fresh schema bootstrap, not legacy revision/tag/
  commit-intent conversion; catalog lineage interface/repository transaction contract.
- API `routes/v1/endpoints/{ingest_sessions,revisions,datasets}.py`/schema; proposed
  releases.py and submissions.py. Remove separate tag publication/withdraw endpoints
  and revision-only DTOs at explicit owned replacement/code cutover, not compatibility
  or legacy data conversion.
- Existing tests/ingest_client.py, contract/test_commit_intents.py,
  test_ingest_process_death.py, integration/test_verified_raw_ingest.py,
  test_catalog_releases.py, acceptance/test_raw_ingest_gate.py; extend behavior,
  add tests/integration/test_release_recovery.py and owner-mirrored unit/contract tests.
- Integrity admission (`core/integrity/{verification,generations,ports}.py` and
  `_impl/controller.py`) and applications/lakectl recovery wiring only as needed
  for recovery-owned fences; existing P3 cleanup/cutover debts must be reconciled,
  never declared solved by renaming classes. No array workers or broad data grants.

Fresh deployment approved 2026-10-06: legacy session/revision/tag/manifest/receipt
conversion is not required. Fresh schema bootstrap remains required, as do durable
pins/readers/receipts and crash recovery for new data. A nonempty target refuses and
surfaces operator action; never rewrite history, reset or drop existing rows/volumes.
Current revision/tag semantics remain until atomic owned code/schema/test cutover.

## Interfaces and implementation examples

Proposed domain API (illustrative, not installed):

```python
submission = await rawstore.submit(actor, dataset_id, base=exact_release,
                                  additions=files, deletions=paths,
                                  metadata=presence_aware_pair, claim=claim)
receipt = await rawstore.publish(actor, submission.id)
release = await rawstore.get_release(actor, receipt.release_id)
```

Submission identity/request digest includes base, explicit changes, pinned metadata/
schema and descriptive snapshot. Same identity/different request conflicts; same
identity after commit returns same receipt subject to current authorization, even
if head has advanced. Check authorized COMMITTED replay before stale-base rejection;
never turn a successful replay into a conflict or disclose an unauthorized receipt.
Receipt survives upload/session TTL; a retry cannot create a second release.
Proposed states: OPEN → TRANSFERRED → VERIFIED → STORAGE_INSTALLED → COMMITTED;
cancel/failure only where safe, with durable intents and idempotent cleanup. Exact
state names await crash probe; storage installed is not catalog-visible publication.

1. Authorize target + exact source; resolve immutable base and freeze bundle/snapshot;
   acquire durable base-retention pins and total-byte capacity reservation.
2. Materialize full candidate with independent ordinary copies, never hardlinks;
   verify all final manifest paths/sizes/digests. Reject traversal, symlink escape,
   duplicate/normalized collisions and inconsistent replace/delete instructions.
3. Fence dataset publication and recheck base/source and target authority. Approved
   rule: for an uncommitted attempt, compare immutable expected base against current
   head atomically in the catalog publication transaction under the chosen qualified
   serialization; concurrent first pushes require expected empty head. No implicit
   merge/rebase. An earlier preflight check alone is insufficient.
4. Install durable immutable storage with fsync/rename protocol under qualified
   writer exclusion; commit the head comparison/update and publication+lineage+audit+
   receipt on one asyncpg connection/transaction. A losing attempt returns typed
   stale-base conflict (illustrative HTTP 409); candidate stays hidden, no lineage
   or receipt is published and no unpublished result is acknowledged as success.
   Do not hold an unbounded DB transaction during full filesystem copying.
5. DB failure after install leaves hidden recoverable candidate and durable intent;
   recovery rechecks authority/current head before adoption, otherwise leaves terminal
   failure/quarantine for authorized recoverable cleanup. Recovery must distinguish
   authorized COMMITTED replay from uncommitted adoption; only the latter compares
   current head. Lost response after commit replays the receipt even after head advances.
6. Release pins/reservations only after recovery no longer needs base/candidate;
   cleanup checks ownership and live references, handles crash mid-cleanup/ENOSPC.

Lineage pins inputs, actor, code, parameters, origin and outcome when applicable;
Raw original acquisition does not invent processing code. Filter inaccessible source
details. Cancellation never unpublishes a committed release. Readers see old or new
complete release. Global capacity/copy admission differs from transfer semaphore
and same-file fencing. Qualify NFS locking, atomic rename and directory durability.

Explicit retry after conflict resolves a newer base and creates a new operation
identity/fingerprint; never mutate the original frozen attempt. Omitted metadata
inherits the exact newly pinned metadata/schema pair, not latest by accident. SDK/UI
surface the conflict for caller review, never automatic repin or changed-input reuse
of the old identity. Rawstore errors/ports and application mapping above own this
contract; the HTTP 409 shape is illustrative pending transport qualification.
Serialization choice, isolation/lock ordering and DB/FS crash-state evidence remain
technical blockers, not a reopened product-policy decision.

## Serial task slices

1. Pending: fresh schema bootstrap + submission/base pin/metadata freeze values;
   unit/real DB invariants, no publication shortcut. Full gate.
2. Pending: deterministic base-plus-explicit-changes manifest + independent retained copy + admission,
   path defenses/ENOSPC/cancel. Real filesystem contracts + acceptance.
3. Pending: fenced storage-first publication and atomic asyncpg lineage/receipt;
   remove tag/revision public paths and replace tested behaviors. Full gate.
4. Pending: crash/revocation/recovery/cleanup/retention races and reader visibility;
   operator runbook and idempotent retries. Full gate including controlled cutover.
Each slice serial, skills below, independent baseline/final rerun, max 3 reviews.

## Skills

`.agents/skills/oop-design/SKILL.md`, `.agents/skills/fastapi/SKILL.md`,
`.agents/skills/postgresql-table-design/SKILL.md`,
`.agents/skills/implementation-plan/SKILL.md`; read OOP behavioral reference for
state-machine decisions only if introducing that pattern. Preserve simple explicit
workflow methods where sufficient.

## Acceptance and complete applicable gates

Required new behavior cases: two attempts on one base and two first pushes on empty
head yield one committed winner and explicit loser conflict; no partial catalog
lineage/receipt, discoverable loser or unpublished success. Repeat around storage
install/DB failure and recovery. Advance head again, then replay the winner identity
under current authorization: original receipt, not stale conflict; revoked/hidden
replay discloses nothing. Caller-reviewed retry uses new identity/fingerprint/newly
pinned base pair; original remains frozen and omitted metadata never adopts latest.
Fresh bootstrap succeeds only on a suitable empty target; nonempty target refuses
without reset. These acceptance requirements have not yet been executed.

Root locked uv/Python >=3.12: `make lint`;
`uv run pytest -m unit --cov=src/huron --cov-report=term-missing`;
`uv run pytest -m contract`; `uv run pytest -m integration`; `make test-acceptance`;
`make docs`; `git diff --check`; `uv run python scripts/check_openapi.py --check`;
`uv run python scripts/check_database_schema.py` (002/004-owned scripts required).
Prerequisites PG16/testcontainers, real local disk, isolated Linux/Podman runner and
historical Git object, >=25 GiB free acceptance disk plus extra for retained-copy
scenarios. Missing infrastructure is BLOCKED. NFS evidence separately qualified in 010.

Retain 96.01% unit coverage floor, import contracts, complexipy 15, radon C+/MI B+
diagnostic findings and duplication ratchet at 0.80, no new/growing groups. Extend
meaningful fixtures/public behavior and deterministic barrier/fault cases; no skips,
xfails, suppressed diagnostics or weakened assertions. Real DB/FS prove transaction
and crash guarantees; mocks only external boundaries. Show changed line coverage,
retry outcomes, zero leaked partial publications and bounded cleanup/pin lifetimes.
No frontend gate for backend-only slice. Capture exact commands/cwd/version/exits/
counts/evidence and require independent reruns, not copied writer receipts.

## Blockers and readiness

Fresh deployment and stale-base conflict approved 2026-10-06. Prototype owner must
prove atomic head/publication serialization, concurrent empty-head conflict,
authorized committed replay after head advances, crash/fence/pins and cleanup;
003 authority, 004 schema pair and 005 durable tus prerequisites. Fresh bootstrap,
nonempty-target refusal, retention TTLs and independent review required before
`/implement-markdown roadmap/plans/006-release-publication.md`.

## Execution ledger

Planning writer attempt 1, no product/prototype execution; review count 0. Future
parent tracks model/role/session/times/current command/verdict, 15-minute progress,
minute polls and one writer/reviewer at a time. Preserve unrelated dirty work.

## Escalation / final receipt

BLOCKED draft. Publication is not verified until bytes are readable after receipt,
all crash/revocation/cancellation states recover and independent applicable gates pass.
