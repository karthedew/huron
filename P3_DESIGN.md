# P3 — Integrity services: final design

Status: design agreed 2026-09-08; M1a passed independent verification on 2026-09-11 ([P3_M1A_VALIDATION.md](P3_M1A_VALIDATION.md)). M1b's authority model is superseded by [ADR-0001](docs/adr/0001-controller-generation-is-the-verification-epoch.md) and designed in [P3_M1B_AUTHORITY_DESIGN.md](P3_M1B_AUTHORITY_DESIGN.md); its delivery is tracked by that design's implementation plan and `design/roadmap.html`.
Implementation follows the separately authorized [P3_IMPLEMENTATION_PLAN.md](P3_IMPLEMENTATION_PLAN.md). `design/` remains the architecture authority; its affected pages
are reconciled in this change. [P3_PROPOSAL.md](P3_PROPOSAL.md) is historical
interview input and is superseded wherever this final design differs.

## 1. Outcome and scope

P3 makes Raw publication resistant to stale upload writers, provides a mechanical
offline protocol cutover, recovers abandoned commits, detects integrity failures,
cleans staging, and reconstructs the Raw catalog from storage. No future search,
array-store or compute implementation is implied.

Included: governance document schemas and mirrors; recognition and guarded
continuation of existing removal intents; amendment reconstruction; findings;
operator commands; a read-only administrative report; admission rules for reads.
P5 still owns amendment submission, purge request/approval, TTL selection,
retention scheduling and policy changes. P3 never initiates a new removal intent.
Continuation is inert without authoritative governance and authorization, and is
proved using fixtures until P5 supplies production workflows.

Excluded: clone optimization, register-in-place implementation, SDK work, search
projection, derived-layer registry/lineage reconstruction, UI work, recovery of
credentials/holds/audit from thin air, repairing corrupt payload bytes, replacing
catalog identities, and bypass flags that certify unsafe storage.

The first deployable slice is the verified-completion protocol plus its offline
cutover and startup gates. Its development includes schema and verifier
prerequisites; operators must not cut over before the entire slice is available.

## 2. Settled decisions

| ID | Contract |
| --- | --- |
| D-1 | Recognize future purge, expiry and amendment records now; P5 owns their originating workflows. |
| D-2 | Recovery copies relocated staging into fresh verified inodes; it never publishes the relocated original. |
| D-3 | Normal file completion materializes verified independent payload; commit remains a rename. |
| D-4 | Offline cutover is the first deployable P3 slice; no unfinished legacy session enters the new protocol. |
| D-5 | Legacy verification is membership in a digest-bound inventory, never a timestamp comparison. |
| D-6 | Certification requires proven writer shutdown and enforced exclusion, including permanent old-release exclusion. |
| D-7 | Incomplete amendment history cannot broaden access; an untrusted prefix is not current metadata. |
| D-8 | Storage-only recovery preserves pending removal; current governance must be restored before resumption. |
| D-9 | Purge includes expiry files and mirrored per-file details, preserving only operation-level audit evidence. |
| D-10 | Pending purge blocks payload/manifest; pending expiry blocks its selected payload entries. |
| D-11 | Already-authorized downloads may finish; new admissions enforce removal restrictions. |
| D-12 | Acknowledgement does not resolve findings; verification does. |
| D-13 | Rebuild never invents missing parents. |
| D-14 | Known DEGRADED revisions do not block activation if identity, hierarchy and access are unambiguous. |
| D-15 | DEGRADED blocks all new payload downloads; trustworthy metadata/findings remain inspectable. |

Remaining routine choices are resolved below using the user's authorization to
adopt recommendations. There are no pending product questions. Deployment-specific
proofs are implementation gates, not claims that infrastructure already exists.

## 3. Trust, identity and storage layout

The single-writer storage boundary is the trust root. No signatures or HMACs.
Ownership and seals detect boundary violations; they do not defeat a privileged
process with the storage identity. JCS detects noncanonical bytes, not arbitrary
replacement with other canonical bytes. Compare canonical document digests with
PostgreSQL when available and with the legacy inventory where applicable.

The publication invariant is: every published payload inode was verified with no
writable handles remaining, and has not subsequently been opened for writing.
Completers create this condition for new data; a fenced cutover establishes it
for VERIFIED legacy entries. Removal unlinks payload; it never rewrites bytes.
Directory link counts are not file link counts: require `st_nlink == 1` for
regular owned files, not directories. Refuse symlinks, special files, escaping
paths, wrong owners and unexpected entries; do not follow them during scans.

Storage layout: normal upload/completion/envelope separation is implemented. Preparatory protocol evidence and legacy verification follow §5.2 and ADR-0001, with delivery status in `design/roadmap.html`; initialization, activation/startup, recovery and cleanup remain planned:

```text
/data/
  protocol/
    000001.json                  immutable cutover record, points to report digest
    reports/<run-id>.json         immutable canonical inventory and fence evidence
    .maintenance.lock            permanent kernel ownership inode; never unlinked
  .staging/
    <ingest-id>/
      upload/<file-id>            request-writable inputs, never published
      completion/<candidate-id>   private candidate files, closed before installation
      envelope/
        manifest.json
        metadata.json
        COMMITTED
        payload/<manifest-path>  only verified installed files
    recovery/<ingest-id>/<attempt-id>/
      original/                  relocated session tree; never published
      candidate/                 independently materialized recovery envelope
    trash/<claim-id>/            resumable cleanup, original identity in claim
  organization/.../dataset/.../raw/revision/<number>--<revision-id>/
    manifest.json, metadata.json, COMMITTED, payload/
    amendments/0001.json
    expired/0001.json             multiple disjoint expiry selections
    PURGED                       optional write-ahead purge intent
```

Only BeginIngest may create the session root and fixed staging children. Every
later write requires the existing session root. Never recreate it after rename,
abort or sweep. Creating deeper manifest directories is allowed only relative to
an already-validated existing root; stale operations cannot reconstruct the root.
Traversal uses bounded descriptors and no-follow checks. `protocol/` is never
sweeper territory; the sweeper is restricted to `.staging/`, not dot-directories
in general.

The absence of undeclared entries is checked as well as the presence of declared
ones. File completion and recovery compare the digest after closing their write
descriptor; later inspection opens published payload read-only. Temporary
installation links must be gone before final seal/publication checks pass.

## 4. Verified file completion and immutable commit attempts

1. Upload requests open only `upload/<file-id>`. Preserve streaming, part-size,
   digest, retry and authorization contracts. A pre-existing descriptor may
   finish writing this inode after the session advances; it cannot reach payload.
2. A completion attempt copies to its own file outside `envelope/`, hashes bytes
   written, checks exact size/digest, fsyncs, seals and closes its writer. A failed
   attempt deletes only its own candidate; it cannot remove another completed file.
3. Install only that verified closed inode into payload, durably, without replacing
   an installed file. If another completion won, verify its identity/content and
   return the same COMPLETE result. A conflicting installed file is a finding.
   Temporary candidates are never inside the tree that commit publishes.
4. Persist COMPLETE after installation. An install-before-row crash is recovered
   by checking the installed file; a row must never attest an absent installation.
   Delete upload input after durable installation/ledger completion. Open upload
   handles can retain space until they close, so no hard one-file space bound is
   promised; bound concurrent completions and account for disk reserve.
5. Session verification remains a ledger operation. Publication additionally
   checks the installed inventory and absence of candidate/temporary files.

Completion admission defaults to one copy per Raw-store instance (normally one
per API process) and a 1 GiB free-space reserve. Configure these with
`HURON_COMPLETION_MAX_CONCURRENT` and `HURON_COMPLETION_RESERVE_BYTES`. Before
creating a candidate, compare free capacity on its held directory descriptor
against all expected copy bytes reserved by this instance plus the reserve.
Keep each reservation through installation and cleanup; release it on failure
or cancellation. Queued retries recheck installed payload before reserving, and
already-installed replay needs no copy capacity. This accounting is conservative:
written candidate bytes remain reserved until the operation finishes. It does
not coordinate other processes or reserve space against uploads and external
writers, so deployment capacity must still account for those consumers and ENOSPC
must leave unpublished candidates safe. This is not a root-wide writer fence.

Arbitrate the principal-scoped idempotency key before freezing or publishing.
In the same transaction as the first freeze, bind the key to the ingest session
with an unfinished-commit receipt. That binding does not expire while publication
is unresolved; otherwise a long interruption could let another session take the
key before the original publisher records its revision. The revision transaction
replaces the pending binding with the final revision receipt. Conflicting keys
leave the losing session and its staging envelope unchanged. A legitimate replay
still validates the frozen documents and final payload before returning success.

Freeze a commit's canonical metadata, commit instant and identity once in a
session-owned commit-intent row when first entering COMMITTING. A retry uses that
same document set and returns a conflict for a different metadata command; it
must not recompute `committed_at` or replace documents. Persist its digest and
COMMITTED v2 digest with the intent. This deliberately supersedes P2's absence
of persisted commit intent: concurrent attempts must agree on every byte.

Immutable document installation must expose complete, fsynced, closed candidates
without replacing an existing document. Equal existing bytes are an idempotent
success; unequal or partial documents are findings. Keep `atomic_replace` for
CURRENT/INDEX only. The implementation uses native exclusive rename:
`renameat2(RENAME_NOREPLACE)` on Linux and `renameatx_np(RENAME_EXCL)` on Darwin.
Unsupported platforms, system libraries and filesystems refuse installation.
Unlike a temporary link/unlink pair, this leaves no second name after an install
crash; publication requires regular-file link counts of one throughout. Real NFS
cross-client proof remains mandatory before deployment to that filesystem.

Commit keeps its short database fence, seals the complete envelope, durably
renames `envelope/` to final, seals the final root and records revision/session,
audit, outbox and idempotency in one database transaction. It never recopies
payload. Retries and recovery use the same frozen documents. An existing final
path is accepted only after matching the full claimed identity and documents,
not merely finding a file named COMMITTED.

Register-in-place remains future work and means no second upload, not no second
storage copy. Clone support is deferred; any later clone must provide independent
write isolation and pass the same verification as a copy. Measure completion
latency/I/O; do not promise a fixed multiplier.

## 5. Offline cutover and version fences

### 5.1 Certification prerequisites

Writers include every API replica, host-run process, reconciler, sweeper and any
future retention process with this root. A deployment provider supplies a complete
writer inventory, controller identities, restart exclusion and confirmed process
termination. An unreachable node requires actual storage fencing; absence from a
pod/container listing or expiration of a timer is insufficient proof.

Rotate application database roles: old roles cannot log in, have no effective
write access and have no surviving sessions. The new application role is also
excluded for the verification interval; only the cutover identity has application
write access. Check inherited privileges and ownership, not just direct grants.
Trusted DB/storage administrators are explicitly outside the application-writer
threat model. Replacement credentials never go to an old release. Database
exclusion prevents new work but cannot stop requests past their database check;
that is why independent shutdown proof is mandatory.

Periodically recheck evidence and check immediately before certification. These
checks detect violations; enforced exclusion supplies continuous protection.
Evidence contains names, identities, generations and outcomes, never secrets.
There is no `--trust-me`, timeout-only or missing-provider certification mode.
Optional storage-identity rotation can strengthen the fence and is recorded.

The repository ships Compose/host development workflows, not Kubernetes tooling.
The first adapter targets a controller-managed Compose deployment with dedicated
application roles; host/unmanaged writers must be stopped and evidenced through
an approved provider or cutover refuses. A Kubernetes provider is an independent
deployment adapter, required before that environment is supported. Providers
implement the same contract; a user-supplied JSON assertion is not live proof.

The local implementation provisions a private root-owned Podman engine, local
named volume and serialized restart controller. Kernel peer UIDs select separate
maintenance/restart grants. Application users and automation have no alternate
daemon endpoint, host storage access or privileged restart path. The controller
persists exclusion before confirmed process removal and invalidates prior evidence
on generation change. Its complete inventory includes stopped containers and
refuses foreign volume holders, exposing mounts and host-privileged containers.
The database owner remains distinct from both application identities and the
private cutover identity. The [operator contract](docs/operations/controlled-cutover.md)
and `deploy/controlled/` templates specify this boundary; ordinary development
Compose remains unsupported for certification. M1b evidence is local and disposable,
not production readiness, and does not implement M1c activation/startup.

### 5.2 Ordered, resumable procedure

1. `lakectl protocol cutover --prepare` takes the storage claim, then asks the
   controller to establish exclusion. `establish` mints a new controller
   generation — the verification epoch — and returns fence evidence naming
   that generation, the run, the operator and the maintenance database
   identity. It supports exactly schema 0010 as a legacy maintenance mode,
   never as an API startup compatibility mode.
2. Verify structural generation documents and every legacy final envelope, full
   payload included. Resolve final orphans from verified documents. Resolve
   COMMITTING sessions with valid matching final envelopes as COMMITTED; fail
   every other nonterminal legacy session with an audited reason. Conflicting or
   unverifiable final evidence gets a DEGRADED record only if structural identity
   is trustworthy; identity conflicts stop certification rather than free an
   ambiguous number. Claims belonging to known final revisions remain spent.
3. Record findings for corrupt legacy revisions and exclude them from VERIFIED.
   A corrupt byte does not block the healthy population; unresolvable identities,
   missing parents or exclusion failure do. Preserve corrupt content for diagnosis.
4. Write and fsync a canonical report, then a numbered write-once record binding
   its digest. Recheck fences after database resolution and before/after each
   installation. Kernel ownership remains held until actual filesystem writers
   settle, including cancellation. All local finalization precedes the
   controller's `validate`; the report and record alone never establish that
   their epoch is live.

5. Migration 0011 refuses nonterminal sessions, adds RECOVERING and the new
   ingestion contracts. Apply later P3 migrations as required by the release.
   Migrations do not inspect an assumed filesystem path; startup checks storage
   and database compatibility together.
6. `--validate --sequence N` asks the controller to admit record `N` under the
   live epoch; this command is delivered by the M1b authority plan, not M1c
   (see `P3_IMPLEMENTATION_PLAN.md` M1c item 1). Database head, migration and
   activation prerequisites remain M1c checks. Only then enable the new
   application role/deployment. Old roles remain disabled. The activation
   receipt binds this run/report/database.

Prepared report and numbered-record files are immutable forensic evidence, not a
certificate. Their presence, or absence of another file, never establishes success.
A permanently named private no-follow lock inode gives one process exclusive
maintenance ownership. The kernel releases ownership on process death; no marker
is removed and no lease expires. Cancellation waits for actual filesystem writers
before releasing ownership. A competing invocation is refused, including the same
run submitted through another process.

After all local writes, monitor shutdown and ownership release succeed, `prepare`
asks the controller to validate the record. The controller's durably persisted
generation is the verification epoch and its only authority state
([ADR-0001](docs/adr/0001-controller-generation-is-the-verification-epoch.md)).
`validate` is stateless: under its own claim the controller re-reads the record and
report, checks the exact record/report/root/run binding, the live PostgreSQL role
fence and database identity and its live deployment/writer generation, and admits
the record only if its fence names the live generation. Because `establish` is the
first step of `prepare` and every failure after it ends the epoch, an admitted record
proves that the scan producing it completed under the live epoch. A lost reply is
resolved by calling `validate` again (step 6); it is neither success nor failure.

An epoch ends in exactly three ways, each advancing the generation on disk before
any refusal is reported: the controller observes a loss (volume identity, engine
transport, writer inventory, storage I/O under its claim, the role fence or the
database identity, or cancellation during any of these); the client declares one
through `abandon`, which `prepare` sends for any failure after `establish`; or the
controller restarts. Apparently restored observations revive nothing, because the
generation already moved. A mismatched argument (wrong run, stored record, report
digest, operator or peer) refuses the presented record without ending the epoch.
The controller mints generation 1 at every start and never issues it; the first
`establish` mints 2 and every epoch end adds one. The fence binds the maintenance
database as `<system_identifier>/<database_oid>/<datname>`, captured at `establish`
and compared at every later database observation; the private maintenance settings
are read once at controller start and are never digested or emitted. Future
initialization and activation consumers must call the same `validate`; they cannot
infer admission from JSON files alone. No M1c activation is implemented here.

Every `prepare` performs a full scan and appends a new report/record pair at the
next free sequence number; report and record share the number and nothing under
`protocol/` is reused or rewritten. A report without its record is history left by a
failed run, not something a later run resumes. A retry after any epoch end is a
fresh `prepare` under a fresh generation; `run_id` remains only the audit and
database-idempotence key, so the same run identity may be resubmitted. Residual
windows — an unobserved loss between fence checks, an `abandon` that fails against
a live controller, a client that dies before sending it — are bounded by the
fence-check interval and the controller's next observation; the operator contract
documents them, nothing closes them.

A fresh empty root gets an explicit protocol-initialization record with an empty
inventory before API startup. Starting the API does not silently bless an
unrecognized root. New API, worker and CLI runtimes check exact supported schema
head(s) and protocol before serving or mutating. Old binaries lack that check;
only the external fence excludes them. Test the actual old binary, not a version
label fed to new code.

### 5.3 Legacy evidence

Report entry: revision ID, dataset ID, number, relative path, byte digests of
COMMITTED/manifest/metadata, outcome `VERIFIED` or `DEGRADED`, and finding codes.
Unreadable/missing documents have explicit absence/error evidence, not fabricated
digests. A v1 envelope is legacy-verified only through a VERIFIED inventory entry
whose identity/path/documents still agree. Unknown v1 orphans are operator findings.
New markers use `urn:huron:committed:2`; v1 decoders remain read-only.

Subsequent valid purge may intentionally remove a legacy manifest. Validate the
retained COMMITTED/metadata against the inventory and the purge against its
manifest digest, then apply lawful-removal rules. Do not demand a purged manifest
or silently drop legacy membership; this is the explicit exception for later
lawful removal. Report document digests contain no per-file paths or digests.

## 6. Governance document and persistence contracts

All schemas refuse unknown fields, invalid IDs/digests/timestamps and noncanonical
encoding. Files are write-once with fsynced contents and parent directories; the
writer publishes complete bytes. Names and identity fields must agree. Sequences
are gap-free from 1, ordered numerically, not by timestamps; filenames are
zero-padded to at least four digits and never sorted lexicographically as authority.

| Document | Required content beyond schema |
| --- | --- |
| `COMMITTED` v2 | Existing v1 fields; schema ID distinguishes the verified-materialization protocol. |
| `PURGED`, `urn:huron:purged:1` | revision/dataset IDs, manifest digest, purge-record ID, requester, approver (different), request/approval/start instants, reason, authorization audit-event ID, explicit removal scope: payload, manifest, expiry records and mirrors. No per-file details or duplicate counts. |
| `expired/N.json`, `urn:huron:expired:1` | record ID, revision/dataset IDs, manifest digest, sequence, started_at, initiating actor, policy reference, authorization audit-event ID; entries with path, size, digest, category, reason. |
| `amendments/N.json`, `urn:huron:amendment:1` | Amendment ID, revision/dataset IDs, manifest digest, sequence, created_by/at, changes; reuse the existing allow-list and fold, including separate reclassification authorization. |
| `protocol/N.json` | schema, sequence, root identity, before/after protocol, instant, actor, code digest, report relative path/digest, verified counts/bytes, degraded revision IDs, verified fence identities. |
| protocol report | run/root identity, exact legacy inventory, findings, fence evidence and outcome. |

Protocol record/report schema IDs are `urn:huron:protocol-transition:1` and
`urn:huron:protocol-inventory:1`. Protocol versions are integers: legacy 1,
verified-materialization 2, and before-version 0 only for a proved-empty root.
Future transitions append records; unsupported versions refuse mutation.

Expiry selections are nonempty, individually unique and disjoint across records.
Every entry must match the retained manifest. Selected entries may be present
(pending) or absent (removed); unselected entries must exist and verify. Duplicate
selection, gaps or disagreement block continuation and become findings. Partial
removal never makes an invalid record valid. Validate PURGED first: it explains
expiry-file removal and prevents interpreting intentional sequence loss as corruption.

A valid intent is durable before the first unlink. `started_at` means intent/start;
completion is an observed database timestamp. Authorization references are
traceability, not evidence that lost hold/audit rows never existed. Do not
synthesize an EXECUTED purge authorization row from a storage-only rebuild.
Rebuild preserves marker evidence separately until authentic governance is restored.

P3 persistence additions (exact migration numbering after 0011 may change):

- `ingest_commit_intents`: session PK/FK, exact canonical command/document bytes in `bytea`,
  generated SHA-256 digests and commit instant/actor; immutable after insertion.
  Storing canonical bytes avoids JSON re-encoding changing the frozen evidence. Index/FK ownership is
  with core ingestion's port, not a catalog-wide repository.
- `ingest_recoveries`: session PK/FK, unique attempt ID, original/candidate paths,
  checkpoint, actor, start/update times. One owner; no expiry-based takeover.
- `revision_governance_documents`: document ID, revision FK, kind, sequence, digest,
  canonical document JSON, pending/completion observation. Unique revision/kind/
  sequence; purge uses sequence 1. Exact canonical digest is stored and checked.
  P5 purge-record rows additionally reference their marker digest; keep genuine
  authorization rows separate from reconstructed evidence.
- `revision_integrity`: revision PK/FK, derived lifecycle state, metadata trust,
  pending removal kind, verification cursor and last full verification evidence.
  Payload health is separate from lifecycle: DEGRADED is an overlay in the
  existing public state vocabulary. Purged/expired state can be recovered when
  damage is repaired without falsely restoring COMMITTED.
- Extend `reconciliation_findings` with root identity, stable resource key,
  last-seen run/time and occurrence data; constrain severity. Separate immutable
  acknowledgement events and run receipts. A unique open finding key prevents
  duplicate open findings under concurrent scans.
- `integrity_runs` and `rebuild_runs`: UUID identity, kind/root, status, checkpoints,
  source inventory/report digest and timings. Rebuild claims a previously empty
  target; only its same run may resume a partly populated target.

Use existing UUID identities, timezone-aware instants, non-null required fields,
FK indexes and checked status vocabularies. No broad JSONB indexes without query
need. Preserve all existing revision/claim constraints and immutable identity
triggers; extend state rules deliberately. Correct the schema map's missing
state-CHECK annotation. PostgreSQL 16 is the current Compose target.

## 7. Abandoned commit recovery

Heartbeat every 30 seconds during storage work; eligibility after 5 minutes
without a heartbeat is a configurable detector, never permission to take over.
Heartbeat updates have a dedicated timestamp and do not invalidate client etags.
Only COMMITTING enters RECOVERING through a compare-and-swap. RECOVERING is
nonterminal in both uniqueness predicates; COMMITTED retains its number claim.
Client commit retries get `INGEST_RECOVERY_IN_PROGRESS` (409).

A recovery attempt durably records its unique paths, then renames the entire
session tree to its recovery `original/`. The original staging name cannot be
recreated. A failed CAS stops the attempt. A conflicting final and staging state,
wrong identity, or unexplained ENOENT leaves RECOVERING locked with a finding.

| Owned/observed state | Action |
| --- | --- |
| Matching final with v2 COMMITTED | Validate protocol, identities/documents, seals and inventory; import once and complete session. Normal periodic payload verification still applies. |
| Matching legacy final | Apply cutover membership and lawful-removal rules; unknown v1 is operator-only. |
| Relocated original has a complete valid marker set | Verify documents against session/intent/file ledger, retain that exact set, copy/hash all payload into fresh candidate, close/seal/publish, then record COMMITTED. |
| Relocated original has no COMMITTED | Fail session after successful relocation proves original-path publication is impossible; keep original for cleanup. |
| Marker exists but is incomplete/invalid, or final is ambiguous | Finding, RECOVERING remains locked; no invented commit or number release. |

Recovery publication writes revision, session completion, audit, outbox and retry
receipt once in one transaction. A post-publication crash resumes from the exact
matching candidate/final evidence. Old writers cannot delete/fail/renew RECOVERING
through stale etags. An already COMMITTED session is an idempotent result.

A stalled recoverer never loses ownership merely by timeout. Operator resumption
first proves the old recovery process stopped or was storage-fenced, then uses a
new attempt and fresh candidate. Never share candidates between attempts. This
also applies to timed-out background threads; cancellation is not process death.

Default automatic recovery copy cap: 100 GiB per revision, one copy at a time.
Above it, report and keep the lock; explicit `recover --allow-large-copy` can
start the copy after the capacity check. Reserve at least expected copy bytes
plus max(10 GiB, 10% of copy bytes). These are tunable operational defaults, not
performance guarantees. ENOSPC retains resumable evidence and never publishes
partial content. A lower limit or refusal is not an integrity defect.

## 8. Reconciliation and findings

Every run verifies names/identities, schemas/canonical bytes, document digests,
expected payload presence, sizes, owner, seals and independent regular-file
ownership. INDEX is derived and optional; it is not a required envelope document.
Complete PURGED envelopes legitimately lack payload and manifest. Scan findings
must distinguish unreadable storage from actual absence.

Hash verification uses a 1 TiB per-run default budget and a 7-day target interval,
configurable per deployment. Oldest/never fully verified revisions go first.
Persist completed-file progress so a file set larger than one run is not starved;
a single file larger than the budget receives a scheduled isolated full pass
with an explicit reported overrun, not endless deferral. Stamp full verification
only after the complete expected retained set passes with stable document/state
evidence. A changing governance state invalidates affected progress. Report
missed target intervals; a budget does not promise sufficient throughput.

| Finding family | Automatic action | Integrity consequence |
| --- | --- | --- |
| Eligible orphan envelope/document/release | Validate then import missing row, exact identity only | Report repair; conflicts never overwritten |
| Missing envelope/document; digest, size, identity or link mismatch; unknown extra content | Preserve bytes and rows, report | DEGRADED when revision-scoped; structural conflict can block activation |
| Wrong owner | Report, never automatically chown | DEGRADED |
| Known contents but unsealed envelope | Restore restrictive modes after identity/content checks and mutation coordination | Resolve seal finding after recheck; payload health requires its own checks |
| Invalid/torn CURRENT | Repoint to highest valid consistent generation; never skip invalid newer generations silently | Ambiguous chain is operator-only |
| Stale/missing INDEX | Rebuild from authoritative rows under dataset serialization | WARNING repaired; no revision damage implied |
| Valid pending removal | Track, restrict reads, resume only through guarded continuation | Pending, not unexplained corruption |
| Invalid amendment chain | Keep valid prefix for restricted inspection | Block reads if classification cannot be established |
| Unknown legacy final | No import or certification | Operator finding |

Automatic repairs never overwrite disagreeing history. Disagreeing database rows
are not silently replaced just because storage generally leads. Concurrent derived
writes coordinate with the normal writer through the same dataset/generation
revision check; a stale index can be retried, not declared repaired prematurely.

Findings separate severity (`INFO`, `WARNING`, `ERROR`) from outcome (`OPEN`,
`REPAIRED`, `RESOLVED`). REPAIRED is not a severity and DEGRADED is a revision
state. Key open findings by root + resource identity/path + code. Reobserving
updates last_seen; reappearance after resolution creates a new occurrence.
Acknowledgement is attributed, reasoned and audited, without closing the finding.
Only a complete relevant check resolves it. Never resolve from absence in a
partial, filtered, failed or budget-limited scan. Clear DEGRADED only when all
relevant checks pass, using lawful-removal evidence to derive the lifecycle.

Alerts on new/worsened ERROR conditions, sweep-guard refusal, incomplete runs,
and verification overdue; deduplicate unchanged occurrences. Structured CLI/run
reports and process exit codes are P3's alert integration; no invented telemetry
service. Summary counts and digest references avoid copying sensitive file
inventories into audit messages, especially for purged revisions.

## 9. Governance continuation and read contracts

Storage reconstruction never deletes outside staging. Online continuation of an
existing validated intent needs authoritative restored governance, current actor
permission, pins/holds checks and a compatible continuation implementation.
P5 owns the originating workflow and uses this same continuation contract.
No existing intent can grant arbitrary path deletion.

Use a project-scoped mutation barrier shared by continuation and P5 hold/pin/
reclassification writers. It serializes authorization/hold check plus each
bounded deletion step; database row locking is permitted, NFS advisory locking
is not the safety proof. Lost DB ownership during an in-flight storage operation
must not allow a competing writer to bypass it: mark the operation indeterminate,
retain its claim, and require process/fencing evidence before takeover. A timeout
alone never releases destructive authority. P3 must not enable continuation for
a governance writer that does not implement the barrier.

Durable intent precedes opening payload directories for deletion. Validate identity
and scope; delete only named expiry entries, or the purge's fixed permitted set;
fsync affected directories and reseal before recording observed completion. Purge
removes expiry mirrors as well. Check current governance before every step.
An interrupted operation is pending; holds can stop subsequent steps. Missing
hold/audit data after rebuild means unknown authority, not an empty hold set.

Authorization and lifecycle checks occur at core download admission. No HTTP-only
protection. Existing open streams may finish. New requests behave as follows:

| Condition after discovery/authorization | Payload | Manifest / metadata |
| --- | --- | --- |
| COMMITTED, trusted | Normal | Normal |
| Pending expiry | Only unselected entries | Valid manifest and trustworthy metadata readable |
| EXPIRED_PARTIAL / EXPIRED | Retained entries only / none | Valid manifest and metadata remain readable |
| Pending purge / PURGED | None | Manifest blocked; trustworthy retained metadata readable |
| DEGRADED | None | Only independently validated documents/metadata; findings visible to authorized readers |
| Effective classification unknown | None | No normal revision reads; restricted operator inspection only |

HTTP: unknown/undiscoverable remains 404; normal permission denial remains 403;
RECOVERING and pending-removal blocks are 409 with distinct codes; completed
lawful removal returns 410 `RAW_CONTENT_REMOVED`; DEGRADED or untrusted document
returns 409 `REVISION_DEGRADED`. No sensitive diagnostic detail before discovery.
Do not fall back to lower classification or an older revision. `latest_revision`
is the highest numbered published revision regardless of lifecycle/health state;
rename the misleading latest_committed port and make both adapters agree.

## 10. Staging sweeper

Runs every 15 minutes. The existing API lease expiry sweep remains separate.
Only terminal session trees (ABORTED, FAILED, COMMITTED) older than a 15-minute
cleanup grace and unclaimed orphan trees older than 24 hours qualify. A session
age is not expiry: the existing expiry workflow must first transition it safely.
RECOVERING/COMMITTING and active recovery candidates never qualify. The sweeper
requires an authoritative session ledger; it refuses all deletion during DB loss,
rebuild or uncertain restore completeness.

Identify candidates, apply the guard, recheck eligibility/identity, atomically
move each tree into `.staging/trash/<claim-id>`, fsync the rename, then remove it
without following links. No API path can recreate its root. Persist cleanup claim
identity so a crash resumes trash deletion without guessing its former owner.
Late open descriptors cannot modify published payload and may hold disk space
until close; successful namespace cleanup does not promise immediate byte release.

Guard uses eligible session-tree count divided by all managed session-tree count
(excluding trash; recovery trees grouped by owning session). Refuse if candidates
exceed max(10, floor(25% of the denominator)). Both defaults are configurable and
reported. Unknown/unparseable trees are findings, never silently counted as safe
trash. `--dry-run` reports every candidate and guard verdict and changes neither
database nor storage. No automatic guard override; an operator can select a
smaller scope or change the explicit configured limit.

## 11. Rebuild

Offline only, with the same enforced writer-exclusion contract. P3 rebuilds Raw
organizations, projects, datasets, revisions, amendments, releases and lifecycle/
integrity observations. It does not rebuild search, arrays or derived lineage.
RBAC, identities/credentials, audit, idempotency, original outbox, jobs, holds,
authorization records and open sessions require backups. Do not fabricate these
from descriptive markers or emit historical events as newly performed actions.

Create a fresh migrated target and claim it with a rebuild ID/root identity.
Refuse unrelated structural rows; allow partial rows only for that same persisted
rebuild identity. Snapshot a document inventory under exclusion. Phases: protocol
and legacy evidence → generation hierarchy → revisions/governance observations →
amendments → releases → derived indexes → full inventory validation. Each batch
is transactional and idempotent by identity/digest; conflict is a report, never an
upsert that overwrites different content. Checkpoints advance with each batch.

No placeholder parents. Missing parent or conflicting ID/slug/path/number blocks
activation. A structurally valid corrupt revision can be represented DEGRADED;
invalid identity cannot. Known corruption is reported but does not prevent healthy
inventory recovery. Purged/expired records are lawful; pending intents remain
pending and do not trigger deletion. Purge recovery suppresses restoration of
sensitive expiry mirrors from stale backups before declaring cleanup complete.

`rebuild --validate` produces a durable report/receipt binding source inventory,
target identity, run and blockers. `rebuild --activate` validates that same receipt,
checks current fences and restored access policy, and marks the target ready for
application startup. It does not silently redirect a deployment or enable roles.
The operator then configures the deployment under the controlled fence. No
activation when RBAC/classification is ambiguous. Governance readiness is a
separate gate: read service may resume while destructive workers stay disabled.
A first full reconciler pass must reproduce known findings without new unexplained
ones; retained DEGRADED entries do not imply a failed rebuild.

## 12. Responsibilities, interfaces and operator surface

| Boundary | Planned responsibility / files |
| --- | --- |
| `pkg/catalog` | `governance.py`, `integrity.py`, document values and pure validators/folds; extend `documents.py`, `ingest.py`. No I/O/framework imports. |
| `pkg/rawstore` | `materialize.py`, `inspection.py`, `maintenance.py`; bounded filesystem reads/copies/claims/seals/deletes behind capability ports. Extend `store.py`, `commit.py`. No catalog imports. |
| `core` | `integrity/` package containing reconciliation, recovery, sweep, cutover, rebuild, governance continuation, commands/results and consumer-owned ports. Extend existing ingestion and read services. |
| `pkg/metastore` | `integrity.py` for integrity/governance/run persistence; extend ingestion adapter for intents/recovery. Preserve adapter independence from core. |
| `applications/lakectl` | argument parsing, settings, authenticated local operator/deployment identity, controller adapters, factories and exit/output mapping. No import of API application. |
| `applications/api` | runtime checks, updated ingestion/read error mapping, read-only report route; reusable authorization remains core. |

Use focused services, not one integrity repository/manager containing every
operation. Proposed public operations are `reconcile(actor, scope, options)`,
`recover(actor, ingest_id, options)`, `sweep(actor, options)`,
`cutover(actor, command)` and `rebuild(actor, command)`, returning typed reports.
Inject clock, ID source, cancellation/budget, storage, persistence, deployment
exclusion and maintenance authorization. Filesystem scanners stream entries;
core receives relative identities/evidence, not concrete filesystem adapters.
Verify adapter conformance in application wiring. Extend import-linter application
independence to lakectl; never use dynamic imports to evade the boundary.

Normal online commands require SYSTEM-scope `integrity.read` or
`integrity.maintain`; grant them to platform_owner without granting data.write.
Maintenance identity is separate from scientist authority. Scheduled commands use
an authenticated deployment identity scoped to this root and allowed operations,
not a fabricated scientist or broad service account. Offline cutover/rebuild use
that externally authenticated operator authority plus the fence evidence, since
lost RBAC cannot authorize itself. Core checks those grants; a CLI `--actor`
string or ownership of files is not authentication. Actor/audit provenance is
recorded for each operation; restored historical attribution is kept distinct.

```text
lakectl protocol init
lakectl protocol cutover --prepare | --validate
lakectl reconcile [--dataset ID | --revision ID] [--verify metadata|full] [--dry-run]
lakectl recover INGEST_ID [--allow-large-copy]
lakectl sweep [--dry-run]
lakectl findings list [--open]
lakectl findings acknowledge FINDING_ID --reason TEXT
lakectl findings verify FINDING_ID
lakectl rebuild --from-storage --run-id ID
lakectl rebuild --validate --run-id ID
lakectl rebuild --activate --run-id ID
```

Default `reconcile` runs metadata checks plus budgeted hashing; explicit `metadata`
disables hashing, `full` requires the requested scope's full verification. All
mutating commands support a read-only preview where meaningful; preview must not
acquire write claims or persist audit/findings. Exit codes: 0 complete/no open
ERROR or blocker, 2 completed with findings/pending action, 3 refused by safety or
capacity guard, 1 execution failure/incomplete. JSON and concise text reports
share one typed result. A completed rebuild validation can be activatable while
returning 2 for retained corruption; automation must inspect the activation flag.

`GET /admin/reconciliation/report` is read-only, scoped and keyset-paginated,
requiring core integrity.read. HTTP apply/plan mutations are not part of P3.
No user-facing findings page is included. Document all configured defaults and
whether a command is inspecting, repairing or waiting on external authority.

## 13. Verification and delivery limits

The implementation plan maps each contract to observable tests and files.
Required proofs include real PostgreSQL contention/constraints, real temporary
filesystem durability and descriptors, old-writer restart exclusion, and real NFS
cross-client behavior for every deployment claiming NFS support. Local POSIX
success is not NFS certification. Controller/storage credentials are supplied by
that deployment; missing evidence must fail closed, not skip a gate.

The current integration directory has no substantive coverage; P3 must add it.
Keep `make lint`, unit coverage, affected contract/integration/acceptance and
strict docs gates. The 9 GiB completion-copy gate needs more free space than P2's
10 GiB minimum: provision at least 25 GiB and calculate actual peak requirements
for concurrent cases. Preserve P2's historical receipt rather than claiming it
proved the new protocol. No runtime, migration or infrastructure change has been
executed as part of this design task.

## 14. Inspected baseline and planning evidence

The design was checked against the source tree, not inferred solely from the
roadmap: `core/_ingest.py` performs hash-only completion and per-attempt commit
composition; `pkg/rawstore/store.py` writes to payload and creates parents in
`atomic_replace`; `pkg/rawstore/commit.py` publishes by rename; migration 0001
constrains the session vocabulary; migrations 0008/0009 define the claim indexes
and ledger; the two `latest_committed_revision` adapters differ once non-COMMITTED
states exist. `pkg/catalog/amendments.py` allows separately authorized
reclassification and refuses sequence gaps. Governance document schemas and
operator applications are not yet shipped. Compose is the concrete deployment
configuration available in the repository.

The project-local codebase-design and grill-with-docs copies are scaffolds, not
implemented methodologies. This planning followed the user-invoked personal
grill-with-docs skill and the repository's actual OOP, PostgreSQL and FastAPI
guidance at their respective boundaries. No scaffold gate or unimplemented
methodology is claimed as validation.
