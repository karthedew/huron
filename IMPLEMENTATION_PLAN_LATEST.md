# M11 production plan: accepted publication and exact recovery

Date: 2026-11-09. Target: a maintainable initial production service for about 50 scientists.
Status: **PLAN ACCEPTED through explicit prerequisite gates; R3-1 resolved by independent review**.
The original complete reviews remain **FAIL / FAIL / FAIL**. Section 12 is the unchanged historical
receipt. Section 13 records this substantive reconciliation and the user's one-time authorization
for ONE additional independent maximum-profile review after writer terminal, without automatic retries.
That review returned PASS; section 14 records the parent-observed terminal evidence.
P00 discovery ran on 2026-11-10 and returned BLOCKED. Section 10 records its baseline and ownership findings.
P01 remains blocked. Later slices require their listed prerequisites. The full design is not yet validated, and neither
implementation completion nor production qualification is claimed.

**Separation note (2026-11-10):** [Repository readiness](REPOSITORY_READINESS.md) owns the current
bounded repair of inherited M11.5e readiness and baseline failures. It is not P implementation progress.
The original P00 receipts remain historical diagnostics. Before any future P entry, the parent must
record independent maximum acceptance of that readiness boundary. P00, P01 and later phase acceptance
remain pending under their own contracts. The P01 umask ownership clarification remains valid.
Do not resume the historical M sequence or infer production qualification from readiness checks.

## 1. Execution authority and preserved work

This is the focused replacement M11 execution contract, not a copy of the old plan.
[IMPLEMENTATION_PLAN.md](IMPLEMENTATION_PLAN.md) is **HISTORICAL, UNMODIFIED** by this work.
Its sections 3–9 continue to govern everything except the enumerated supersessions below.
Its status marks and old green counts are historical evidence, not current acceptance.
The replacement contract takes execution authority only after the parent records independent
plan acceptance and dispatches a named slice. Do not resume the old M11 sequence automatically.

Baseline: branch `tusd-integration`, HEAD `0dcdf1ff6a8689f704a73a0758a886c18b5d3584`;
reference branch `m11.5-escalated` stays. Old-plan working-file Git blob:
`862e1bafc54c5ca88b0351ff7ee723662a1ac7f8`. Preserve migration 0003, blob
`83757f7e73640356639ae07c45d7885660b9a6e3`. The exact initial dirty/untracked inventory is
durable in [review evidence §2](design/m11-review-evidence.md). It includes user-owned agent
tooling and the unaccepted M11.5e repair work. **Nothing in that inventory is disposable.**
P01 can change only explicitly assigned repair hunks after a fresh ownership comparison.
No phase grants commit, branch, push, issue, data-deletion, or reference-branch deletion rights.

Read this whole document, [AGENTS.md](AGENTS.md), [domain guidance](docs/agents/domain.md),
the named local skills, and the orchestration/verification contracts before work. Each slice's
contract includes sections 1–6, its own subsection, and its acceptance rows in sections 8–10.
Those sections are inline execution context, not optional links. The durable
[architecture](design/m11-production-architecture.md) and
[prototype receipt](design/m11-prototype-evidence.md) supply supplementary detail and history.

### Exact supersession boundary

| ID | Old decision or amendment text superseded | Replacement; all other rules retained |
| --- | --- | --- |
| S1 | D-7; §5.4 synchronous apply; §6.3 pre-finish publication | A short acceptance/reservation transaction, recoverable per-file materialization, then one final transaction. No public byte changes before acceptance. |
| S2 | D-8; CLI `_recover` version/content inference | Required durable client request UUID, immutable canonical payload, exact saved outcome. No inference fallback, including removal-only/empty requests. |
| S3 | Upload flow/latest-placement-wins; timestamp receipts; backup dropped at receipt; hard-link-only tusd source placement | Private independent copy-and-seal; explicit upload/object IDs; retain old and new objects through finalization. No public-destination reconstruction or timestamp arbitration. Publication still uses hard links and rename, never symlinks. |
| S4 | Blanket “no disk tasks” in the uploads amendment | Only a normalized publication journal and identity-bound cleanup. No generic job platform, ingest sidecar, recursive server reconciler, or repair disk walk. |
| S5 | Two writable API replicas; lease/stat-unlink/old-tusd-overlap accepted residuals; unconditional clean-locks init | Initially one writable API process and one tusd process. No takeover until old accessors are proven quiescent or externally fenced. Recreate/lease expiry/pod deletion is not fencing. |
| S6 | Success despite failed public removes; inode-only outbox validity; case-only stale-name residual | Every requested remove must be durable before commit success. Unknown identity blocks the accepted operation. Ordered case/file/tree transitions are journal steps. |
| S7 | mtime/TTL sweep of arbitrary tusd files; timeout-forget; reuse of placed/committed | Explicit expiry, cancellation/supersession, reservation, quiescence and retention accounting. Timeout retains identity. Consumed upload recovery follows its operation. No mtime deletion. |
| S8 | Unlimited production size; worker counts as queue bounds; lake-only readiness deadline; startup-before-provision | Finite byte/count/inode and waiting-work admission; whole readiness deadline; tracked drain; offline provisioning before writer start. |
| S9 | Split unsynced CLI copy/stage files, push-only lock, mutable source at upload | One state-root mutation lock, atomic working-copy generation and durable UUID intent; private local copy-on-add spool with finite limits. |
| S10 | Edit unreleased 0003 in place; test-bed disposal by implication | Additive revisions only. Fresh paired database/empty lake by default. Existing byte-bearing data causes transactional refusal until a separately approved export/re-ingest/import plan. |
| S11 | Per-path ordering alone for metadata, repair, delete/group/schema operations; directory name reuse after kept cleanup | Shared organization/catalog/collection guards, current resource-ID/version/group rereads, busy refusal while affected publication is pending, identity-bound cleanup and name tombstones. Ordinary metadata still commits rows first and is repaired from current DB state. |
| S12 | Legacy four-field CLI token writers; old M11.11 raw token injection and §12 token-copy workaround | Approved fresh-login provenance and one locked atomic credential writer for CLI and repository development login. P27b replaces every CLI-state producer/caller; P34 authenticates separately at host and pod destinations, never copies or fabricates token JSON. Broker/web authentication remains separate. |

This also supersedes only the corresponding unsafe residual rows of old §12 and the matching
ADR 0008/2026-11-06 and 2026-11-08 amendment claims. It does not change the hierarchy, RBAC,
collection lifecycle, naming bounds, schema rules, read-only web, or the user-approved repair
resolution. No containment hole was found in M11.5e. Keep `LakePath`, descriptor-relative
no-follow traversal, fixed mount point, marker checks, server hashes, one `Storage` port, full
`MemoryStorage`, separate large/short pools, DB accounting and lock order, DB-planned repair,
no ACLs, and no CLI lake writes except explicit administrator provisioning. Keep CLI source
folder `os.walk`; keep the event name `disk.link_found`.

## 2. Evidence and readiness states

Discovery `ses_e41c0ac7fffenvXnJq83K0pRBh` statically confirmed F1–F7 and operational/task drift.
Architecture review1 failed on destructive prototype DB teardown and missing parent fsyncs;
the prose fix was followed by preparatory review2 PASS for the bounded handoff. Prototype
attempt1 failed to obtain a published loopback PG port. The parent authorized the retained
private bridge endpoint without changing networking. Attempt2 and its independent reruns
are narrow evidence; review1 FAIL on manifest-directory sync was fixed and review2 PASS
confirmed the bounded results, not the complete design.

Essential executed observations, independent of ignored artifacts:

- Actual POSIX `Placer` accepts a missing-source replay from unrelated same-size public bytes.
  An overwrite followed by `drop_backup` removes old bytes without a collection acceptance.
  This was not a full PostgreSQL application stale-commit/revocation test.
- Actual `StateDir` lost the parent's staged intent to a second process despite the parent's
  lock. This was public state methods, not two complete CLI commands.
- Actual CLI `_recover` returned success for a removal still present after an unrelated
  version bump, with remote API answers faked. Full HTTP loss/stage-clear was not exercised.
- A tiny real-PG/real-filesystem model held request uniqueness, digest conflict, collection
  reservation and retained old/new bytes over six logical interruption/reconnect points.
  Six operations succeeded once; a same-byte foreign inode left a seventh accepted/blocked.
  Eligibility was a pure model. Two allocation-directory fsync faults created no database.
- No killed-process, host power-loss, real Huron PG publication, real tusd/nginx, NFS/ONTAP,
  operational fencing, quota, full CLI-spool, or 50-user capacity qualification exists yet.

Exact commands, results, log hashes, excerpts, review IDs and retained resources are in the
durable prototype receipt. The container `ca0aac2e123e4f18dea1ece653ca62f4c6555a46059a46271cd9ca63ec206936`
was last recorded stopped/PID 0; its volume, network, four probe DBs and failures remain.
This plan authorizes no restart or deletion. The parent owns reconciliation and cleanup.

| State | Required evidence | Current state |
| --- | --- | --- |
| Design validated | Reviewed invariants plus P02–P05 prerequisite experiments; explicit directory replay, tus creation identity, cleanup and deadline decisions | Partial; blocked on those probes/assets |
| Plan ready | Independent maximum review, resolved per-slice inputs/ownership/gates; P06 freezes any probe-driven correction | Accepted through explicit prerequisite gates by the one user-authorized additional review (§14). Prior FAIL/FAIL/FAIL stands; P00 discovery is separately admissible, not run here |
| Implementation complete | P01 and code slices independently pass their full gates, obsolete owned paths removed, real application crash and integration gates pass | Not started by this assignment |
| Production qualified | Representative workload, ONTAP/security/durability/fence evidence, supported deployment/cutover rehearsal, final maximum review | Blocked; not inferred from local ext4 or a Helm render |

## 3. Inline protocol contract for every implementation slice

### 3.1 Values, outcomes, and authorization

Use frozen dataclasses and consumer-owned protocols in `core.lake`; Pydantic stays at HTTP/CLI
edges. Runtime SQL is asyncpg; tables are SQLAlchemy Core/Alembic. No new framework or dependency.
The proposed signatures below are **future interfaces**, not available APIs today:

```python
# core.lake.uploads.attempts.UploadAttempts
async def begin(actor: Actor, request: UploadBegin) -> UploadView: ...
async def start_seal(upload_id: UUID, owner: WriterOwner) -> SealTicket: ...
async def finish_seal(ticket: SealTicket, evidence: SealEvidence) -> UploadView: ...
async def cancel(actor: Actor, upload_id: UUID) -> UploadView: ...
async def get(actor: Actor, upload_id: UUID) -> UploadView: ...

# core.lake.publications.operations.Publications
async def submit(actor: Actor, collection_id: UUID,
                 request: PublicationRequest) -> CommitOutcome: ...
async def status(actor: Actor, request_id: UUID) -> CommitOutcome: ...
async def next_steps(operation_id: UUID, owner: WriterOwner,
                     limit: int) -> tuple[PublicationStep, ...]: ...
async def acknowledge(operation_id: UUID, ordinal: int,
                      evidence: StepEvidence, owner: WriterOwner) -> None: ...
async def finalize(operation_id: UUID, owner: WriterOwner) -> CommitOutcome: ...
```

`UploadBegin = (attempt_id, collection_id, rel_path, size, expected_sha256,
supersedes_upload_id?)`. `PublicationRequest = (request_id, base_version, adds, removes,
host, message?)`; each add is `(rel_path, size, sha256, upload_id, object_id)`. Keep original
path spelling; key uniqueness uses NFC/case-fold. At most 10,000 total entries, 16 MiB canonical
request, host at most 255 UTF-8 bytes, message at most 4,096 UTF-8 bytes. Validate bounded body
before JSON allocation; transport refusal creates no durable request. Reuse `pkg.canonical`.
Keep the captured dirty tree's **206-byte user rel_path component bound** (207 refuses),
1,024-byte whole rel_path, 63-byte hierarchy segment and 255-byte identifier. Raw `LakePath`
components still allow 255 bytes. Unique publication temps remove the basename-expansion cause,
but this plan does not incidentally relax the user naming contract back to 255.
Canonical digest includes collection ID and every semantic field; sort entries by validated key.
Different entry ordering with the same semantics is the same request; changed spelling is not.

Unique key is `(actor.subject, request_id)` per instance. An early nonlocking lookup can return
an existing outcome; the unique constraint decides concurrent first submissions. Resolve a
duplicate before stale-base or current-grant checks. Same key/digest returns the saved result;
different digest is `REQUEST_ID_CONFLICT` 409. Save authenticated, structurally valid semantic
refusals, including stale base, tree, permission, busy and eligibility refusal. No acceptance
reservation survives a rejection. Status is creator-only, otherwise 404, with a distinct
platform-admin `OPERATION_DIAGNOSE` privilege for diagnostic access. After revocation/deletion,
the creator gets only its minimal saved outcome, not payload or new collection data.
Authorization for a new operation is `COLLECTION_WRITE_FILES` at acceptance; later revocation
does not undo it. Invalid authentication, body, or failure before receipt is not a saved outcome.
A retry after an acknowledged terminal refusal uses a new UUID, even when only eligibility or
available capacity changed and the semantic payload stayed the same. Unknown work never does.

States: `accepted -> publishing -> succeeded`, with recoverable `blocked` between accepted and
success; `rejected` is terminal **before** acceptance. Accepted work never expires or user-aborts.
`CommitOutcome` contains request/operation IDs, state, target identity, terminal result
`(version, file_count, commit_id)` or bounded problem, timestamps and status URL. Retain key,
digest and terminal outcome for instance lifetime, even after collection deletion. Monitor DB
growth; active-work quotas do not bound lifetime history.

HTTP: POST commits is 200 only on finalized success; after a 5 s response wait return 202
for accepted/publishing/blocked with status URL and `Retry-After`. Disconnect does not cancel.
GET `/api/v1/commit-requests/{request_id}` gives the exact saved state; only a 404 in the verified
saved instance/principal binding (§3.5) permits retransmitting the **same** ID and body, not inferring success. Dry-run checks permission/base/tree without an ID,
reservation or audit; upload eligibility/capacity are explicitly provisional. Collection views
expose `pending_operation`; files/version remain last finalized until success. Mountless
production is read-only; explicit memory test/seed mode is not production receipt bypass.

Register errors at their owner and test the shared error registry/docs: `REQUEST_ID_CONFLICT`
409, `COMMIT_REQUEST_NOT_FOUND` 404, `COLLECTION_BUSY`/`CATALOG_BUSY` 409,
`UPLOAD_INELIGIBLE` 409 (bounded reason and operation/expiry fields), `UPLOAD_HASH_MISMATCH`
422, `CAPACITY_EXCEEDED` 429, `WRITER_UNAVAILABLE` 503. Preserve existing path/permission,
size/tree/version errors. A blocked operation carries its actual storage problem, not a
false terminal refusal. Scheduling conflict is not a fourth repair failure reason.
P27a also registers `RECOVERY_BINDING_MISMATCH` 409 for wrong expected instance/subject and
`RECOVERY_BINDING_REQUIRED` 422 for missing/malformed headers, before status lookup or mutation.

### 3.2 Persistence, ownership, and lock order

Target normalized logged relations, schema `huron`; no opaque JSON plan array:

| Relation | Key fields/constraints and access paths |
| --- | --- |
| `service_identity` | Singleton boolean PK with CHECK true; immutable non-null unique instance UUID. Explicit fresh-install initialization only; runtime compares configured UUID and refuses missing/mismatched identity. No runtime upsert/rebinding. |
| `lake_writers` | Instance PK, monotonic epoch, API/tusd owner IDs, config digest, active/draining/uncertain/quiescent state, handover/fence evidence. No time-based uncertain-to-quiescent transition. |
| `objects` | UUID PK, upload/seal attempt IDs, unique private locator, expected/measured size/hash, sealing/sealed/gc_pending/deleted state, manifest digest, diagnostic unsigned inode conversion; complete proof required for sealed. |
| `uploads` | UUID PK, unique actor/attempt ID, original scope IDs plus nullable live collection FK SET NULL, exact path/key, declared hash/size, object FK, expires_at, state, superseding upload FK, reserving operation FK, bounded failure. |
| `commit_operations` | UUID PK, unique actor/request UUID, original organization/catalog/collection IDs, live collection FK SET NULL, payload digest, base/target versions, state, owner epoch, times, bounded terminal result/problem. Never cascade outcomes. |
| `commit_entries` | PK operation/ordinal, unique operation/key, action, exact old/new spelling, old/new size/hash and object FKs, upload FK. Immutable after acceptance. |
| `publication_steps` | PK operation/ordinal, entry reference, kind, expected-before/desired-after identities, unique owned temp locator, pending/acknowledged state, bounded evidence/error/attempt count. Ordered remove/prune/create/install steps. |
| `object_references` | Typed owner/object unique rows for ready uploads, current files, pending old/new entries. Use concrete FK columns with exactly-one-owner CHECK, not unvalidated polymorphic IDs. Cleanup ownership is separate and does not self-pin. |
| `cleanup_entries` | UUID PK, original resource ID/path generation, object/owned locator, scope/charge links, reason/state/epoch/error. Survives live row deletion. |
| `path_tombstones` | Unique parent resource ID/name key, deleted resource ID/generation and cleanup owner. Block reuse until owned cleanup finishes. |
| `quota_scopes`, `quota_reservations` | Stable global/catalog/principal scope IDs, finite byte/inode/count limits and counters; unique owner/purpose/scope claim, nonnegative quantities, released/transferred state. Reconstruct counters from claims. |
| `collections`, `files` | Nullable unique `pending_operation_id` with FK; current file `object_id` FK, required in production. Current version/count change only at finalization. |

UUIDs are opaque identities, bytes/counters bigint, time timestamptz, hash/digest checked text,
required columns NOT NULL. Index each FK and actual pending/expiry/cleanup access path; partial
unfinished-operation index `(state, accepted_at, id)`. Add cyclic FKs after base tables (or
explicitly deferred where required). Cross-row quotas/references are transactions, not CHECK
claims. Tests must exercise PostgreSQL constraints/races, not only MemoryStore.

Process guards precede DB transactions: organization structural guard when needed, then sorted
catalog IDs, then sorted collection IDs. DB order is writer validation row -> sorted catalog
advisory locks -> sorted collection rows/files by key -> operation rows -> upload rows -> object
rows -> steps/references -> cleanup/removal rows -> quota scopes (global, catalog, principal).
Read candidate IDs unlocked, then recheck under ordered locks. Cleanup candidate selection must
not hold a cleanup-row lock while later seeking collection locks. **No DB transaction waits for
filesystem work, a process guard, HTTP, or a thread future.** Lost races produce domain outcomes.

Additive migration sequence is P09 `0004_publication_ownership.py`, then P28
`0005_publication_cutover.py`; `down_revision` starts at `0003_uploads`. Preserve 0003.
0004 refuses legacy file/upload/removal rows before any schema change; do not fabricate ownership
from a size/hash/inode. Test empty upgrade, populated refusal without loss, schema-map equality,
all constraints, and empty-only downgrade. Default rollout uses a **new paired database and empty
provisioned lake**. An old lake is never silently emptied. Reuse needs an explicitly owned
export/re-ingest or verified import design, with a byte/name/row inventory and independent review.

**Narrow, temporary staging exception:** build the new collaborators unexposed while P07 denies
production writes. To keep each intermediate gate executable, 0004 calls the new upload relation
`upload_attempts`, beside the unchanged legacy `uploads` used only by the old test composition.
P28 refuses nonempty legacy tables, drops legacy uploads/removals, and renames `upload_attempts`
to final `uploads`; it removes every legacy composition and code path. This is an implementation
staging mechanism, not supported backward compatibility, a live dual-write mode, or data conversion.
P06 must independently approve this schema/order detail before P09. No mixed old/new writers or
old wire/local-state compatibility is permitted at deployment.

### 3.3 Physical lifecycle and safety

Upload: receiving -> sealing -> ready -> reserved -> consumed. Before reservation it may end
failed/cancelled/expired/superseded. DB-clock expiry is `now >= expires_at`: initial policy 24 h
from begin for receiving/sealing, 24 h from ready for ready. HEAD/retry does not renew it.
Explicit same-owner/same-collection/key supersession atomically invalidates the old eligible
attempt and reserves a new one; never supersede reserved/consumed work or another user's upload.

Begin reserves **2S** physical bytes for source plus independent copy, and finite object/upload,
inode/directory/manifest/temp allowances, before tusd accepts data. Check global/catalog/principal
limits transactionally. Existing current files, retained old objects and cleanup backlog remain
charged. Zero bytes still consume count/inodes. Source charge is released only after durable
unlink **and** writer quiescence; an unlinked open FD can still hold/grow bytes. Failed copies
keep their charge; a second copy needs another charge unless the old attempt is proven quiescent.
Statvfs safety reserves supplement, not replace, DB accounting. ENOSPC/EDQUOT/inode exhaustion
remain errors. Do not evict accepted recovery objects to make space.

Persist object/seal attempt and unique locators before I/O. Check root/organization marker before
copy/hash. Through the one Storage boundary, copy tusd data into an exclusive new inode under
0700 `.huron-objects/`, sync/close, reopen no-follow, measure server hash and exact length/EOF.
Write an object/upload/attempt/content-bound manifest; sync its file and containing directories
before ready. The sealed inode is never opened for write again. Chmod does not revoke existing
tusd FDs; independent copying is essential. Duplicate hooks coalesce on one tracked future or
return stored state. Expired/cancelled seal completion becomes private cleanup, never ready/public.
Real tusd must prove creation retry identity before the exact attempt protocol is frozen in P06.

Acceptance retains all old/new objects, immutable entries/steps, and one collection reservation
in one DB transaction. Competing collection writes fail busy. Materialization and recovery use
the **same** step executor, outside transactions, under writer and scope guards:

1. Revalidate reservation, markers and retained identities before each physical unit.
2. For replace/add: exclusive operation-unique temp hard link to sealed object; sync parent;
   rename over the expected old target; sync parent. An existing retained-new association is a
   retry; same size/hash alone is not. A foreign inode or uncertain ownership blocks.
3. For remove: retain old object, verify target association, unlink, sync parent. Already absent
   is a journal-backed retry and still requires sync. `KEPT` is not successful requested removal.
4. Order deepest removes/empty-directory pruning before file↔subtree and case-only transitions;
   create add parents outermost first. Every mkdir/rmdir and owned private directory requires
   containing-directory fsync before descendants or acknowledgment. A retry must prove ownership
   and attributes of existing directories; uncertain/foreign directories block. P02 must settle
   the directory-evidence crash gap before production primitives are implemented.
5. All entries durably acknowledged: revalidate and finalize exactly once in a DB transaction;
   files/count/version, consumed uploads, commit/audit/outcome, reference/quota transfers, pending
   clear. An error before finalization leaves the same accepted operation recoverable.
6. GC selects DB-owned identities only, marks gc_pending with no references in one ordered
   transaction, unlinks/syncs outside it, then marks deleted/releases charge once in another.
   Tombstones survive obstruction. Never delete arbitrary public paths or suffix-matching files.

Direct NFS readers may see a mixture **during accepted work**, and old open FDs/cache entries
may show old bytes. API pending state warns of this. No all-file snapshot, PostgreSQL+filesystem
atomicity, rename-only power-loss proof, or instantaneous NFS visibility is claimed. Corrupt or
missing retained data requires verified operator recovery, not guessed rollback or fake success.

### 3.4 Runtime and adjacent mutations

One writable API process (one server worker) and one tusd process initially. A DB ownership row
and dedicated advisory-lock connection reject ordinary duplicate starts; loss marks ownership
uncertain and stops admission/scheduling. It never authorizes automatic reacquisition. A new
writer requires proven old API/tusd quiescence or externally verified export fencing. Service
removal, pod deletion, SIGKILL delivery and executor shutdown are not proof against delayed NFS
RPCs. Fail closed if proof is unavailable: write availability is deliberately lost.

Admission bounds apply **before waiting/submitting**, not only to executor workers. Initial
qualification hypotheses: large pool 4 active + 8 waiting; short pool 7 ordinary active + one
dedicated probe lane, 16 ordinary waiting; accepted operations 16 global/8 catalog/2 principal;
uploads 128 global/64 catalog/8 principal. All are candidate limits, not measurements. Production
values require P35/P37 evidence. Finite per-file/staging/live/retained bytes and inode safety
reserves are mandatory supplied values; no production zero/unlimited. Reject exhaustion 429,
unavailable ownership/storage 503. Recovery uses reserved capacity and a bounded priority queue.

One 2 s monotonic readiness deadline covers DB pool acquisition/ping, key reads and lake check.
At most one disk probe; cached success at most 10 s old; failure/ownership loss invalidates it
immediately. A late/hung probe cannot preserve expired success. Deployment probe timeout 3 s,
period 5 s, failureThreshold 1 initially. Liveness does no NFS I/O. Shutdown stops admission,
tracks seal/publication/cleanup futures beyond HTTP lifetimes, drains before closing DB/storage,
and records uncertainty if the configured drain deadline expires. Forced termination is an
operator action, not fencing. Failed startup disposes every owned acquired resource in reverse
order, including an internally opened PostgresStore.

Use shared guards for acceptance/steps, metadata/schema/group changes, repair and delete.
Pending collection: reject metadata/override/delete. Any affected pending collection: reject
catalog schema/group/catalog-wide repair before DB effects. Re-read resource ID/version/current
group/rendered metadata under the guard. A deleted/recreated row is not the same directory by
pathname. Ordinary metadata commits rows first, writes unique temp+sync afterward, and on disk
failure keeps rows for DB-planned repair. Repair has exactly mode_drift/symbolic_link/storage_failed;
`RepairFailureOut` Field descriptions remain authoritative; actual metadata/temp file is the
failure path. Delete requires empty files/no pending, cancels unreserved attempts and creates
cleanup/tombstone in its transaction. Unknown entries keep tombstones; no automatic reuse.

### 3.5 CLI local state

One stable state-root mutation lock covers add/rm/pull/checkout/context/config/drafts/push/token
refresh/logout/cleanup. Acquire **before** reading context/current copy. Reentrant use inside
one command avoids nested token-refresh deadlock; another process gets conflict, not stale-lock
stealing. Never unlink the lock. Every mutation is an atomic generation update, unique exclusive
0600 temp, file fsync, replace, directory fsync. Use one versioned working record with base,
stage, spool references, attempt IDs, pending UUID/body/digest and generation, not split copy/stage.
Old formats are preserved and refused with export/re-stage guidance; no silent conversion/discard.

**Recovery namespace (review1 correction; proposed, not implemented):** `RecoveryBinding =
(instance_id: UUID, subject: str, api_endpoint: str, uploads_endpoint: str | None)` is immutable
within a working-copy generation. Persist it at checkout/first authenticated working-copy creation,
in each upload-attempt record and PendingCommit before any network effect, including removal-only
and empty commits. Collection UUID/name and request UUID alone are not a recovery namespace.
Config/context/token files select a connection; they never overwrite a working copy's binding.

New authenticated GET `/api/v1/auth/recovery-identity` returns exactly
`{instance_id: UUID, subject: str}` from the validated service identity and `ActorDep.subject`.
No display name, login hint, unverified JWT decoding, cached login subject or unauthenticated health
answer establishes this binding. Today `/healthz` exposes configured instance_id and `/auth/whoami`
exposes subject separately; this new combined route does not exist. P09 creates service_identity;
P11 supplies `initialize_identity(instance_id)` (insert once, same ID idempotent, other ID refuses)
and `read_identity()`. P16 validates configuration against it on startup; P31's explicit offline
server-admin script initializes it before writer start. Tests initialize only their assigned DB.
0004 creates the empty singleton table, not a random default or a copied legacy identity. A restored
instance must restore its identity AND complete outcomes/objects; a new/discarded history requires
a new UUID. Reusing an instance UUID for an unrelated database is forbidden. Provisioned lake
markers and persistent server configuration must carry that same UUID. Read-only runtime does not
initialize it; until P09/P11 the P07 interlock uses existing configuration without this new route.

P23's `RecoveryIdentity.verify(saved, connection) -> RecoveryBinding` follows this strict order:
resolve file/env/global selections and canonicalize connection -> compare approved destinations
LOCALLY -> validate stored credential provenance -> permitted refresh -> authenticated identity
request -> bound operation. No token callback, refresh, exchange or authenticated identity request
may precede the local checks. TLS authenticates a host, not approval to send it a credential.
It runs before status, begin, HEAD/PATCH,
cancel/supersede, retransmit or accepting a terminal response. A token refresh invalidates the
verified session; reverify with its new token. Journal HTTP requests carry required
`X-Huron-Instance-ID` (UUID) and `X-Huron-Subject` (base64url of exact UTF-8 subject) expected values; P27a checks both against runtime and
authenticated actor before lookup/effects (409 `RECOVERY_BINDING_MISMATCH`, never 404). These are
assertions, not authentication. Upload authorization applies the same check, including forwarded
tus requests; P05/P06 freeze proxy/header and creation-metadata propagation. Hook identity comes
from the persisted attempt, never an untrusted claimed subject. Responses echo the binding in
upload/publication views; the CLI checks it before updating state. Thus an endpoint or principal
change between identity inspection and the next request cannot turn another namespace's 404 into
a replay. Failure/401/malformed identity or mismatch preserves all intent/spools and exits with
reconciliation guidance, without status lookup, resume, retransmit or automatic rebind.

Endpoint policy: production requires verified HTTPS, no insecure TLS switch, credentials/query/
fragment in base URLs, or automatic redirects. Canonicalize scheme and IDNA host to lowercase,
remove default port and one trailing slash; preserve case-sensitive base path. Reject dot segments,
encoded separators and ambiguous paths rather than normalize their meaning. Only explicit test/dev
loopback HTTP is allowed; it is never a production equivalent of HTTPS. Persist canonical API and
upload bases separately. A changed canonical endpoint, even for the same instance/subject, requires
explicit `huron context accept-endpoint --api-url URL [--uploads-url URL]` (new P27b command).
It first displays the canonical candidate API/upload bases, issuer and client ID and obtains explicit
informed destination approval before any credential-bearing request. It then uses fresh destination-
specific login (never copies the old bearer/refresh token), verifies the SAME instance/subject,
then atomically records the new endpoint under the root lock, without changing IDs/body/base/stage.
It cannot accept another actor
or instance. Never forward a token to a stored absolute upload/status URL under a different base:
use validated relative locators at the approved base; cross-origin upload bases require this same
explicit trust approval. Configuration overrides alone cannot approve a new base. A mismatched
actor must sign back in as the original actor; a different instance requires a separate checkout,
not rebinding pending work. If the original instance is unavailable, preserve the record for
operator reconciliation/export; there is no force-rebind or automatic new-ID escape.

P23 defines a versioned `TokenState` in `state.py`; P27b replaces `Tokens` at the complete producer/
reader cutover. It contains credential values plus canonical
API base, issuer, client ID, approved upload base (if any), and validated provider token endpoint.
Persist an explicit approved-destination record with it using P22's atomic state I/O. Provenance
comes from the approved login flow, never inferred from current config or decoded old tokens.
`Services` resolves one immutable connection snapshot; `Session.token(connection)` validates that
snapshot against approval AND provenance even for an unexpired bearer, before testing expiry.
Issuer/client/API/upload selection changes refuse reuse and refresh. Switching back to an unchanged
approved snapshot may reuse its matching credential; if replaced or logged out, fresh login is
required. Working-copy namespaces and pending intent are never changed by login/logout.
`ApiClient` validates the actual destination before invoking Session; ordinary API reads/writes obey
these same credential checks even without a working copy. Recovery additionally checks its saved
endpoints locally before Session, then authenticated instance/subject. Recheck after refresh and
invalidate cached identity on token/connection changes; do not silently retry with a different actor.

First login has no implicit trusted default: display and explicitly approve the resolved destinations,
issuer and client before authentication. Fetch discovery without credentials only from that approved
issuer, require matching discovery issuer, verified HTTPS and same-origin provider endpoints; an
off-origin provider endpoint requires separate explicit approval before any credential is sent.
Record the approved token endpoint; discovery changes cannot redirect refresh credentials silently.
No automatic HTTP redirects or cross-origin credential forwarding, including auth=False exchange
bodies carrying company tokens. This is the CLI connection/recovery seam, not a broker/web rewrite.
Approval during accept-endpoint is provisional to that invocation; abort, failed login, identity
mismatch or state-save failure leaves prior approvals, tokens and working intent intact. Commit the
new approval/credential snapshot and endpoint generation through one recoverable local transaction;
P03/P22 test interruption so no partial acceptance becomes active. No approval bypass via --yes.

P23 owns CLI errors in `errors.py`: `DestinationNotApproved` (ExitCode.USAGE, show destination and
explicit login/accept-endpoint guidance), `CredentialProvenanceMismatch` and `UnboundTokenState`
(ExitCode.NOT_LOGGED_IN, require fresh login), and `RecoveryBindingMismatch` (ExitCode.CONFLICT,
restore original instance/subject guidance). No secret in diagnostics; no request on local refusal.
Legacy tokens.json lacks provenance: preserve/refuse it, never migrate by stamping current settings.
An explicit successful fresh login may atomically replace that credential file; failure preserves it.
This is no legacy-token compatibility path and never converts/discards old working-copy state.

#### Development authentication is the same credential transaction

**Selected R3-1 design, future interfaces:** replace `scripts/dev-login.sh`, not its JSON line.
P23 adds repository-only `scripts/dev_login.py`; P27b deletes the shell helper and changes every
caller together with the CLI token-format cutover. There is no shell compatibility wrapper or
`dev_login USER PASSWORD` alias. Password grant exists only in that repository adapter, never in
installed `huron login`, the broker, an API setting or a production trust bypass.

The one public helper interface is:

```sh
uv run --offline --no-sync python scripts/dev_login.py --username USER --api-url API_URL --issuer ISSUER --client-id CLIENT_ID [--uploads-url UPLOADS_URL] [--approval-file APPROVAL_JSON] [--password-stdin]
```

All four named value options are required. Omitted uploads means explicitly no upload destination,
not permission to discover and trust one later. Require explicit absolute `XDG_CONFIG_HOME` and
`XDG_STATE_HOME`; never fall back to the developer's home. Options select candidates only; neither
CLI config, HURON_* variables, an old token nor a service answer approves them. The helper does not
change config or working-copy selection. Callers set matching CLI selection separately. P23 owns
new `Config.uploads_url: str | None`, the `uploads_url` config key and `HURON_UPLOADS_URL` override
(empty config value means None); P27b exposes them and updates their help/tests. A health response
can suggest an upload base, but cannot authorize it or replace the selected/approved base.

Default approval is interactive, default-decline, and distinct from ordinary `--yes` prompts.
Display canonical API/upload/issuer/client selections before credential-free discovery. Display
and approve every provider endpoint the selected flow will use before invoking that flow. For
deliberate noninteractive development/test login, `--approval-file` names an operator/test-owned
regular, no-follow, current-user-owned 0600 JSON file, bounded to 16 KiB with duplicate/unknown keys
refused. It is **explicit trust input**, not ordinary configuration or auto-generated from discovery.
Its complete version-1 shape for password grant is:

```json
{
  "version": 1,
  "purpose": "development-login",
  "api_endpoint": "http://127.0.0.1:8080",
  "uploads_endpoint": "http://127.0.0.1:1080/files",
  "issuer": "http://127.0.0.1:8081/realms/company",
  "client_id": "huron-cli",
  "token_endpoint": "http://127.0.0.1:8081/realms/company/protocol/openid-connect/token",
  "allow_loopback_http": true
}
```

This is an illustrative development tuple, not pre-approved deployment configuration. P27b adds
`scripts/dev-auth.example.json` with this nonsecret schema/example; no caller loads it by default.
The invoker reviews the exact assigned tuple and supplies its own file. No wildcards, origin-only
match, inferred provider path, trust-all, `--yes`, or config-to-approval copier. Match all canonical
selections locally before discovery, then require discovery issuer and full token endpoint to match
the explicit approval before any password request. An off-origin endpoint must be separately named
in the approved file (or explicitly confirmed interactively); it is not approved by trusting the
issuer alone. `allow_loopback_http` permits only literal loopback HTTP for this development flow,
not arbitrary HTTP, insecure TLS or redirects. Production remains verified HTTPS. For interactive
development HTTP, the separate approval explicitly names that limitation. Device/browser login
uses the same approval collaborator for its device/authorization/token endpoints, not password grant.

Read the password only **after** approvals, from a no-echo terminal, or bounded stdin when
`--password-stdin` is explicit (nonempty UTF-8, at most 4 KiB; remove one final newline). No password,
company token, bearer or refresh token in argv, environment values, shell tracing, logs, progress,
exception text or output. Workflow scripts open an owned 0600 password file and redirect its bytes
to stdin; only its pathname can appear in argv. Never shell out to curl with secret form arguments.
Helper success prints only JSON `{subject, instance_id}`; exit codes use the CLI error contract.
Invalid/missing trust is exit2, unsupported/unbound credentials exit3 on reuse, contention/binding
conflict exit6, other failed login/save exit1, interruption exit130. No token-output option exists.

Exact collaborator ownership below is **proposed**, not a claim about today's `Session.login`:

| Owner | Future symbols and responsibilities |
| --- | --- |
| P22 `applications/cli/localstate.py`, `stateio.py` | `LocalState.mutate() -> ContextManager[StateSession]`; atomic credential-only and combined endpoint generations via the same stable root lock/manifest. `StateSession.replace_credentials(expected_generation: int, document: bytes) -> None` changes only credential selection; `accept_endpoint(expected_generation: int, document: bytes, working: WorkingState) -> None` selects credentials and working endpoints together. Both share one durable publication primitive. |
| P23 new `applications/cli/credentials.py` | Frozen `ConnectionSnapshot`, `ApprovedDestinations`, `LoginCandidate`; consumer-owned `ApprovalSource` and `CompanyAuthenticator.acquire(approved: ApprovedDestinations) -> CompanyTokens` protocols; `DestinationApproval` validates selections/discovery before credentials; `CredentialStore.save(session: StateSession, candidate: LoginCandidate) -> None` serializes validated TokenState through P22, with no direct file writer. |
| P23 `applications/cli/login.py`, `identity.py`, `state.py` | `FreshLogin.prepare(connection: ConnectionSnapshot, approval: ApprovalSource, grant: CompanyAuthenticator, *, expected: RecoveryBinding | None = None) -> LoginCandidate` runs approved discovery, fresh acquisition, checked exchange and authenticated recovery identity, returning an unsaved candidate. Device/browser adapters wrap Oidc. Session refresh validates stored approval/provenance before expiry checks and saves through CredentialStore. TokenState records exact approved destinations and verified identity, not decoded/config-stamped provenance. |
| P23 new `scripts/dev_login.py` | `main(argv: Sequence[str] | None = None) -> int`, `DevelopmentPasswordGrant.acquire`, `FileApproval` implement only parsing, explicit developer approval, password input and the dev provider request. Acquire LocalState.mutate before state/connection resolution, call FreshLogin.prepare then CredentialStore.save. Import CLI collaborators, never broker/metastore/API and never write credential JSON itself. |

FreshLogin's caller holds the root session across approval/authentication/verification/save. It never
loads a stored credential as input to fresh authentication, even if valid or expiring. Exchange is
allowed only at the newly approved API; the identity request uses only the candidate Huron token.
Identity must be well-formed and agree with the exchange subject, not with an unverified username
hint. With `expected`, require the same instance/subject for endpoint acceptance. Without it, an
explicit fresh login can change identity **only in credential state**; every old bound working copy,
pending request, spool, base and draft stays unchanged. Recovery still refuses the wrong binding.

Decline, bad approval/discovery, failed grant/exchange/identity and an uncommitted save failure retain
the old approval/token/intent. Absent or owned malformed/legacy credential files may be replaced only
after explicit successful fresh login; never decode or stamp them into provenance. Unsafe ownership,
mode, symlink or a corrupt state transaction manifest refuses without overwrite. Keep prior credential
generation bytes through save/recovery; interruption before commit leaves old active, and interruption
after the durable manifest commit recovers the complete verified new selection, never half an approval.
An uncertain sync cannot be reported as login success; preserve both generations for recovery. All
working intent remains unchanged in either case. Endpoint acceptance retains its stronger combined
transaction requirement; ordinary fresh login cannot stand in for accept-endpoint or rebind work.

#### Credential cutover inventory and observable tests

| Present producer or consumer | Future transition owner (no changes in this planning assignment) |
| --- | --- |
| `commands/session.py::login/logout`, `login.py::Session.login/token`, `state.py::Tokens/StateDir.write_tokens`, Services/ApiClient and all ordinary/recovery callers | P22 primitives, P23 isolated collaborators, P27b command/format cutover and removal of old credential writer/type. No production writer may retain the four-field form. |
| `scripts/dev-login.sh::dev_login` and executable entry | P23 creates the replacement above; P27b deletes the entire old script, including curl grant/exchange and O_TRUNC JSON writer. |
| `scripts/e2e.sh::login_as`, `scripts/demo-noaa.sh` before describe-org, `examples/noaa/load.sh` login guidance | P27b invokes the Python helper with explicit target/approval and stdin password; no source/import of shell helper. P33 runs full identity-switch/e2e/NOAA workflows on real stack. load.sh stays a CLI consumer, not a credential producer. |
| `tests/support/cli.py::Cli.login_as`, `tests/integration/test_cli_end_to_end.py::Stack.login`, token fixtures in `test_login.py` and `test_foundation.py` | P27b replaces positive fixtures with approved fresh login through FakeIssuer/real exchange. Explicit malformed/legacy/invalid-token fixture documents remain negative inputs only. Convert Stack.login now even though the baseline integration skip is removed with the real stack in P33. No newly minted token stamped with settings as a fixture shortcut. |
| Makefile `demo-noaa`; README quick-start/host-CLI/NOAA/pre-release workflows; `examples/noaa/README.md` Log in; `docs/{architecture,user-guide,operator}.md` auth/state/pre-release text | P27b updates precise commands, trust/secret inputs and new state semantics at cutover, not P36. P33 fills in full stack/NOAA execution evidence and target resources. P36 retains the other M11.12 documentation obligations. |
| Historical M11.11:5220–5226 host login then raw pod token injection | Old plan unchanged. P34 implements separate fresh approved host and in-pod logins, each in isolated XDG state at its own exact destination tuple. No token copy or JSON injection. |
| `core/security/broker/{exchange,tokens}.py`, API auth routes and `tests/support/api.py` | Server issuer and API-only auth fixtures, not CLI-state producers. Retain their real verifier/exchange/PG coverage; only P27a/P27c's already owned identity/protocol changes apply. |
| `docker/seed/run.mjs::idToken`, `web/e2e/support/seed.mjs::huronToken/SeedClient`, web OIDC/exchange/session modules and fake IdP | Separate ephemeral seed or BFF credentials; none writes CLI XDG TokenState. No R3-1 auth rewrite. P27c/P33 keep existing protocol-consumer ownership; web/broker regression gates remain where those boundaries change. |

P23 adds `tests/unit/test_dev_login.py` and `tests/support/devauth.py` for subprocess/loopback
fixtures; extend `tests/fakes/issuer.py::FakeIssuer.handler` with controlled password-grant behavior
and request observations, not a second token issuer. Reuse Cli/Router/LoopThread, ScriptedPrompter,
frozen clock, tmp_path, and current login/foundation fixtures. Router.observe currently misses IdP
requests: the new observer must cover each boundary, including credential-bearing bodies, but
persist only sanitized delivery categories/counts, never raw secrets. Do not replace real PG/FS
tests with this fixture. P23 tests the helper/collaborators against an explicitly
test-owned identity-response fixture; P27b uses P27a's real isolated router and runs the actual CLI
executable. No earlier slice needs the future production route or P33 stack to pass its gate.

Required subprocess/public-behavior matrix, with separate HOME/XDG_CONFIG_HOME/XDG_STATE_HOME/
XDG_CACHE_HOME and owned loopback endpoints per test:

- Fresh explicitly approved helper login, then real `huron -o json whoami` and authenticated read;
  switch alice/bob/carol/dave/erin, assert actual roles/subject, and return to the original actor to
  recover unchanged pending work. Dev login is fresh even with valid or expiring saved credentials.
- Absent, malformed, legacy, wrong-owner/mode/symlink credential state; missing/malformed approval,
  declined prompt, noninteractive omission, password/grant/exchange/identity failure. Assert exit,
  no secret output and byte-for-byte old approval/credential/intent retention on failure.
- Parameterize valid/expiring tokens over changed API/upload/file/env/global URL, issuer, client,
  discovery issuer/token endpoint and missing/mismatched stored provenance. Observe **zero password,
  company-token, bearer or refresh-token delivery at unapproved endpoints**, including identity,
  exchange, refresh and ordinary reads. Requests to an approved destination after a deliberate fresh
  approval are different from forwarding an old credential. Redirects cannot carry credentials.
- Contend helper against helper and CLI add/config/logout/refresh/push in real processes; assert
  conflict before auth/write, stable lock inode and no lost generation. Interrupt credential-only
  and endpoint-acceptance saves before/after every file sync/replace/manifest-directory sync; reopen
  state, inspect old/new complete selection, retained old credentials and unchanged intent/spools.
  P29 repeats crash cases on the actual application, not just private helper call counts.

`huron add` copies local source into a private independent spool inode, hashes/syncs it, then
references it atomically. Enforce finite spool bytes/count/free reserve; old plus temporary data
counts. Check descriptor/path identity, size, mtime, ctime before/after and EOF. Observed changes
refuse; no claim that this catches every same-size edit or supplies a coherent multi-file snapshot.
The user must quiesce/snapshot actively written scientific inputs before add. Push always uses
that spool, never reopens the original path as its payload. Keep old spool until state is durable.

Save attempt ID before create and request UUID/body before commit POST. Resolve pending exact
outcome before preflight/pull/rebase/stage mutation; unknown/accepted/blocked keeps intent and
spools, terminal rejection keeps staged work. Only matching success atomically advances base and
clears that generation. New payload/rebase gets a new UUID after explicit terminal reconciliation.
Timeout preserves URL/IDs. Consumed state routes to its operation; expired ready state requires
new upload from spool; explicit restart uses durable supersession, never forget-and-retry.

Polling uses injected `time.monotonic`: `deadline = monotonic() + budget`; before every request
and sleep compute `remaining = deadline - monotonic()`. Include request time, cap each network
timeout and sleep by remaining, do not start another poll at/beyond deadline, and retain state
on a late response. HTTPX timeouts are per-I/O, not a hard process-kill deadline; P03 must measure
and document the slow-response/streaming limit rather than claim cancellation of a blocked local
read. A request timeout cannot cancel accepted server work. No token appears in logs/progress.

## 4. Dispatch, skills, testing and gates

Canonical resource dictionary: `*` means this entire worktree, all test/build/cache/log outputs,
and only the exact private services/ports/browser sessions named by the parent for that dispatch.
Every phase/check uses **`*:write`, serial** until the parent approves a narrower dictionary.
This is coordination, not a sandbox or authority to mutate all files/services. Each slice's file
list is its edit boundary. Unknown overlap stops admission. No worker delegates or resumes itself.
After the tooling restart in §15, ordinary source/config/test/tool fixes use implementation or fix / **code** / **medium**.
Explicitly selected **maximum** remains permitted. Code is exclusive against all workers/checks.
Ordinary review is verification/review/medium. Baseline is verification/discovery.
Planning and ignored prototypes use their declared activities. Final qualification
uses explicit verification/review/maximum Astra. Historical absent profiles remain not-recorded. Configured effort and
provider acceptance are separate fields.

Writer -> terminal evidence -> independent reviewer -> fix -> fresh reviewer, maximum three
reviews per slice. A self-check is not independent review. Missing tools, failing baselines or
unresolved design defects block downstream work; no exclusions/skips/xfails/suppressions or lower
thresholds to manufacture PASS. After review3 FAIL stop for design/plan reconciliation, preserve
work. Parent reconciles uncertain children/processes; no manual resume, replay, stale-lock
stealing, or dispatch-journal edits. For this plan reconciliation only, the later explicit user
authorization permits ONE additional independent maximum review after writer terminal (§13), not
a count reset or automatic retry. No other slice's three-review limit changes. Tooling is out of
this plan except separately authorized workflow corrections; `.agents` checks then need
`build:agent-tools:write`, quit/restart OpenCode,
and loaded-schema/agent inspection before further dispatch.

### Skills (canonical paths; load before changes and review)

All slices read `.agents/workflows/orchestration.md`, `.agents/workflows/verification.md`, and
`.agents/templates/assignment.md`. Planning/probe execution also loads the corresponding local
`design-plan`, `implementation-plan`, `prototype`, `implement-markdown` skill and template.

| Code | Required local skills |
| --- | --- |
| O | `.agents/skills/oop-design/SKILL.md` for core responsibilities/ports |
| P | `.agents/skills/postgresql-table-design/SKILL.md` for migrations/metastore |
| A | `.agents/skills/fastapi/SKILL.md` for API/runtime/routes |
| W | `.agents/skills/svelte-core-bestpractices/SKILL.md`, `.agents/skills/svelte-code-writer/SKILL.md`, `.agents/skills/tailwind-design-system/SKILL.md` for web boundaries; `.agents/skills/playwright-cli/SKILL.md` for visible QA |
| D | `asd-ste100` required for docs/messages, approved source `.claude/skills/asd-ste100/SKILL.md`. The current serving policy denies access. Corrected registration requires restart and load before formal qualification (§15). No direct-read bypass. |
| I | `writing-for-agents`, approved source `~/.agents/skills/writing-for-agents/SKILL.md`, is available and loaded for the separately assigned tooling migration. Load its skill mechanics before skill edits. The exact source must resolve on each workstation (§15). |

Testing standard for each assignment: Before adding tests, find existing public-behavior coverage,
parametrization, scoped conftest/fixtures and helpers; reuse or extend them. Discover fixtures with
`pytest --fixtures`/`--fixtures-per-test` when unclear. Test changed contracts, happy/error paths,
boundaries, permissions, retries, concurrency and recovery as applicable. Assert observable outcomes
rather than private call sequences. Control time/randomness, isolate mutable state, and mock only
external I/O. Real filesystem and PostgreSQL contracts prove durability/locking that fakes cannot.
Frontend pure behavior/API seams use Vitest; cross-route interactions use Playwright. Delete obsolete
owned tests instead of skipping them. Comments/docstrings/test names describe enduring behavior,
not plan phases. No suppressions, exclusions, skips, xfails, weakened assertions, thresholds or
contracts to manufacture a pass.

Reuse `tests/support/{api,cli,clock,disk,lake,postgres,tus,tusd}.py`, API/CLI/storage conftests,
`tests/contract/{conftest,suite,test_postgres_races,test_postgres_constraints,test_migration}.py`,
the shared storage matrix, `test_upload_hooks.py`, `test_push_tusd.py` and preflight tests.
`tests.support.api.service` is memory, not proof of PG behavior. For preservation-sensitive crash
work reuse only `with_database`/`alembic_config`, not `migrated_database`'s unconditional FORCE
teardown. Record intended owned DB/container/lake and sync the allocation manifest and both parent
directories before CREATE DATABASE. Preserve failed/uncertain runs. Never use dev.env or shared DBs
for destructive tests. Ordinary existing gate fixtures may tear down only their own disposable DBs
on the assigned isolated test server; they are not the crash-evidence fixture.

### Gate dictionary: exact commands, not shorthand for reduced checks

Every slice inherits G0 plus every gate named in its subsection. The parent copies these commands
verbatim into its assignment. All root commands use cwd `/home/karl/repo/huron-tusd`; web commands
use that root plus `/web`, docs tests plus `/web/docs-site`. Normal checks use installed assets.
Approved setup may restore existing locked dependencies with `npm ci`.
The project-installed Playwright CLI may install its matching Chromium only with `npx playwright install chromium`.
Verify the installed CLI first. Do not use a package-fetch fallback, unsolicited dependency/lock upgrade,
broad `npx --yes`, or automatic image pull. Cached containers require assigned isolated resources,
ownership and `--pull=never`. This exception permits no implicit developer-service mutation. The unavailable Svelte
autofixer has no installer exception and stays not run. This tooling assignment runs no setup/services.
Installed evidence: Python 3.12.4, asyncpg 0.32.0, FastAPI 0.162.0, Pydantic 2.14.1, pytest 9.2.0,
PG 16.14, Docker 27.2.1, Node 26.10.0/npm 11.19.1. Recapture versions at baseline, no auto-upgrade.

**G0 — all changes:** `git diff --check`, `git diff --cached --check`, plus
`git diff --no-index --check /dev/null <each-owned-untracked-text-file>` (exit 1 with no diagnostics
means new content, not whitespace failure). Inspect status/diff/references and actual ownership.
Root diff currently exits 2 at user-owned generated `web/src/lib/api/openapi.ts:170`; keep attribution.
For this planning slice only, the exact link gate is:

```sh
uv run --offline --no-sync python scripts/check_links.py HANDOFF_M11_PLAN.md IMPLEMENTATION_PLAN_LATEST.md design/m11-production-architecture.md design/m11-review-evidence.md design/m11-prototype-evidence.md
```

For the current reconciliation, run the new-text check separately on each of these five documents,
including the read-only handoff. Do not edit it to repair a check. Historical four-document receipts
below describe earlier checks; this five-document command is the current complete prose gate.

**GP — all Python source/test changes:** `UV_OFFLINE=1 UV_NO_SYNC=1 make gate`.
Actual Makefile expands to the following, all exit 0, **radon output empty**:

```text
uv run ruff check src tests scripts/cli_reference.py scripts/ste_check.py
uv run ruff format --check src tests scripts/cli_reference.py scripts/ste_check.py
uv run mypy
uv run mypy scripts/cli_reference.py scripts/ste_check.py
uv run ty check
uv run ty check scripts/cli_reference.py scripts/ste_check.py
uv run lint-imports
uv run python scripts/cli_reference.py --check
uv run python scripts/ste_check.py
uv run pytest -m "not integration" --cov=src/huron --cov-report=term-missing
uv run radon cc src --min C
uv run radon mi src --min B
uv run complexipy src --max-complexity-allowed 15
uv run python scripts/check_schema_map.py
```

Contract tier is included, so a parent-owned isolated PG server with create-database privilege
must be assigned via `HURON_TEST_DATABASE_URL`, or a cached isolated testcontainer explicitly
authorized. Preserve 90% overall floor, changed source 100% line coverage or a precise genuinely
unreachable-line explanation, complexity maximum 15, import boundaries and source scope.
No new coverage omission. Inspect diagnostics as well as status.

**GDEV — new repository development-auth script**, additive to GP/GD, from root after P23 creates it:

```sh
uv run --offline --no-sync ruff check scripts/dev_login.py
uv run --offline --no-sync ruff format --check scripts/dev_login.py
uv run --offline --no-sync mypy scripts/dev_login.py
uv run --offline --no-sync ty check scripts/dev_login.py
uv run --offline --no-sync pytest tests/unit/test_dev_login.py tests/unit/cli/test_credentials.py tests/unit/cli/test_identity.py tests/unit/cli/test_login.py tests/unit/cli/test_foundation.py
```

Current `make gate` checks only `scripts/cli_reference.py` and `scripts/ste_check.py`; it does not
lint/type-check arbitrary new scripts. GDEV is mandatory for P23/P27b/P33/P34/P39, not replaced by
`--help`, shell syntax or a product-only coverage run. Keep all thresholds and add direct coverage
of every helper entry/adapter and failure path; no new coverage omission or source-scope reduction.

**GC — persistence/real workflow boundaries**, additional root commands:

```sh
uv run --offline --no-sync pytest -m contract
uv run --offline --no-sync pytest -m integration
```

Current integration has only two selected tests, one skipped CLI test and a mountless API test.
These commands alone are not ingestion evidence; P29/P33 add the missing gates and P33 removes
the skip. P00 records that baseline explicitly; P01 repair can be accepted on its independently
verified repair boundary, never labeled complete ingestion. Before P33, legacy integration absence
is a named release blocker, not a new skip or a waived new test.

**GA — API snapshot/error boundary:** writer runs root
`UV_OFFLINE=1 UV_NO_SYNC=1 make openapi`, then web `npm run generate:api` (never hand-edit generated
types). Independent review checks outputs against source and runs:

```sh
uv run --offline --no-sync pytest tests/unit/api/test_openapi_snapshot.py tests/unit/test_error_contract.py
```

GA also requires GW and GD because docs/openapi.json is site input and web types are a consumer.
**GW**, from web: `npm run check`, `npm test`, `npm run lint`, `npm run build`,
`npm run test:e2e`; check must have 0 errors and 0 warnings. Chromium only; assign the five harness
ports explicitly if not using the serial default stack. For visible changes use Playwright captures
390×844, 816×900, 1440×900, light/dark, keyboard and forced colors; explorer also 1024 wide.
Inspect every capture, no sideways scroll/clipped focus. Svelte autofixer is unavailable; report
not run, never install it or label it passed.

**GD — site/docs/user-facing text:** root `UV_OFFLINE=1 UV_NO_SYNC=1 make docs-check`,
`uv run --offline --no-sync python scripts/ste_check.py`, and
`uv run --offline --no-sync python scripts/cli_reference.py --check`; web `npm run docs:build`;
web/docs-site `npm test`. Generate CLI reference with
`uv run --offline --no-sync python scripts/cli_reference.py` when command/help source changes.
Check anchors manually where the file-only checker cannot. Root/design-only planning prose uses
G0/link gate, not GP/GW/site builds.

**Workflow drift is explicit:** `pytest -m unit` is invalid under strict markers; valid unit-only
selection is `uv run --offline --no-sync pytest -m "not contract and not integration"`.
`make docs` is a no-op, not a strict build. `make test-acceptance` is absent until P35 creates it.
The workflow's pydoclint/pyscn/duplication guard are not current `make lint` commands; the agent-asset
owner must reconcile them separately. If restored, preserve similarity 0.80/no new or grown clone
groups, not a fabricated baseline. CI's pytest exit-5 allowance is not integration success.
No tooling correction is authorized by this prose assignment.

## 5. Sequence and coherent intermediate states

All slices are **serial P00 -> P01 -> ... -> P26 -> P27a -> P27b -> P27c -> P28 -> ... -> P39**,
each dependent on the preceding independently accepted slice; external blockers add dependencies,
never remove them. There are 42 slices; “P27” elsewhere means all three P27 slices. This total order
is intentionally acyclic. No parallel code/checks. Every phase below is pending unless stated ready.
Each new module includes its explicit exports/docstrings and direct behavior tests; no placeholder
TODO implementation is accepted. Existing file paths are anchored by repository inspection; new
paths and commands below are labeled **new/future**, not claims that they exist now.

P07 first makes PostgreSQL production mutation unavailable. P08–P26 build tested collaborators
without registering a writable production protocol. P07 creates the isolated legacy test-only composition below; it is a
temporary staging exception, not an alternate supported mode. New collaborators get direct and
real-adapter tests as they arrive. P27a–P27c separate HTTP adapters, CLI callers and final composition;
they are not a catch-all algorithm phase. Algorithms must already pass their earlier acceptance.
P28 deletes legacy
implementations/test assumptions/schema. P29 must prove the complete application crash protocol
before stack/deployment qualification. No intermediate build is released. P39 is the only production
enablement decision; external evidence cannot be deferred beyond it.

## 6. Serial executable phase contracts

### P00 — Untouched baseline and ownership receipt

**Ready for discovery only.** Role verification/discovery, maximum, `*:write`; no source edits.
Inspect actual files against initial status and the two owned design documents. Record hashes/refs,
versions, configured model/profile separately from provider effort, all owned output/service IDs.
The parent must assign an isolated PG endpoint and web harness ports before checks that need them.
Do not reuse the retained probe server or developer stack without separate reconciliation.

Commands: G0, `UV_OFFLINE=1 UV_NO_SYNC=1 make gate`, GC, GA snapshot check (no regeneration), GW,
GD. Read existing tests/fixtures before adding any later test. Record each exit/count/coverage,
diagnostic and skipped test; old green receipts are not this baseline. Existing OpenAPI whitespace,
CLI integration skip, missing assets/skills and workflow drift remain attributed baseline findings.
Unexpected baseline failure stops for an owned remediation or verified independent boundary; do not
reset unknown dirt. Output: parent-owned execution ledger only, with ready/blocked decision for P01.
Skills O/P/A/W/D (missing D recorded); no product qualification from this discovery.

### P01 — Finish and independently accept the dirty repair contract

Existing boundary: M11.5e is dirty/unaccepted, not a containment redesign. Own only the repair
hunks in `core/storage/{memory,posix,errors,repair,ports,__init__}.py`, `pkg/fs/posix.py`,
`core/lake/repairs/{models,operations,__init__}.py`, lake bootstrap/lookups/lifecycle repair wiring,
API `disk/repair.py`, runtime repair composition, repairs endpoints/schema/router, and their
existing `test_repair.py`, `test_repairs.py`, storage matrix/races/storage/posix/lifespan tests.
`tests/conftest.py` temporary-mode fixture and pyproject repair import-contract hunks only.
The existing M11.5e umask bundle also belongs to this acceptance scope:
`tests/conftest.py::fixed_umask`, its required `os` import and docstring,
`applications/api/runtime.py::SERVICE_UMASK/build_runtime`, and the corresponding
`tests/unit/api/test_lifespan.py` coverage. This assigns existing hunks, not new umask behavior.
`docs/api-errors.md`, `docs/openapi.json`, `web/src/lib/api/openapi.ts` only for authoritative
repair contract/regeneration. Any other pre-existing hunk remains unchanged.
The same acceptance inventory includes M11.5e's associated `schema/naming.py` 206-byte upload
component bound, `core/storage/placement.py` failure pruning, API `disk/placements.py` and disk
exports, and their existing schema-naming/upload/hook/storage-placement tests. P00 must resolve
every initial M11.5e product hunk, including its `docs/concepts/raw-ingest.md` text, before P01
claims the dirty slice accepted; unknown hunks are not silently adopted. This adds no permission
to modify the old plan or unrelated agent tooling. Preserve the current naming bound.

Keep full MemoryStorage and all 253 shared cases/pair coverage; POSIX is reference except a named
defect fixed on both. Assert exact code/status/path/detail and outside snapshots. Metadata or temp
failure names that actual file; `RepairFailureOut` is the one contract source. No startswith hiding,
no success-only fake. Repair is DB-planned with no disk listing, repeated current-row reads, correct
permissions, three failure reasons, and idempotence. No deletion of `m11.5-escalated`.
Acceptance: both historical verification3 defects closed; all present repair behavior directly
covered; no containment regression. The primitive counterexamples do not qualify this dirty work.
Skills O/P/A/W/D. Commands GP, GC, GA; focused root:
`uv run --offline --no-sync pytest tests/unit/storage/test_containment.py tests/unit/storage/test_repair.py tests/unit/storage/test_races.py tests/unit/api/test_repair.py tests/unit/lake/test_repairs.py`.
Independent medium review (or explicitly selected maximum) starts a new cycle, at most three
attempts. Do not reuse historical green results. Final complete qualification stays maximum.

### P02 — Prerequisite publication/directory crash experiment

Role implementation/prototype then verification/review; maximum selected for this prerequisite.
**New ignored throwaway** `roadmap/prototypes/m11-production/__pycache__/validation/publication.py`
and uniquely named run children only; a new parent-owned private PG/lake, not live source or the
retained attempt2 database. Parent records exact container/network/volume/ports and absent names.
Use real PostgresStore/API + PosixStorage for current F1/F2 controls: committed A, overwrite B,
stale/revoked/invalid-tree commit; two independent runtimes with reverse FS/receipt ordering.
Keep current failures as evidence, do not patch them. Tiny attempt2 logical reconnects are not
substitutes for this slice.

Candidate: two-file overwrite/remove plus foreign sentinel; process-kill before/after seal/manifest,
acceptance, link/rename/unlink, mkdir/rmdir and every containing-parent sync, ack/finalize/GC.
Settle how `DirectoryProof` identifies an already-created directory after death before DB ack;
foreign/uncertain directories block, and every ordinary owned crash window must resume. No automatic
adoption from pathname/emptiness. Use DB IDs, reserved private locators and durable evidence; reject
an approach that cannot preserve the retained old/new objects. Test 206-byte user components
and 207-byte refusal, raw Storage/LakePath 255-byte components and 256-byte refusal,
1,024-byte rel paths, case-only and file↔directory changes, symlink refusal/outside snapshots.

**Future command created here:** `PYTHONDONTWRITEBYTECODE=1 uv run --offline --no-sync python roadmap/prototypes/m11-production/__pycache__/validation/publication.py --run publication-a1 --deadline-seconds 900`.
Runner must refuse resource collisions, persist/sync allocation before DB creation, use 5 s
barriers/60 s ordinary cases/2 GiB cap/8 GiB free, preserve failures and report owned process exit.
Gate: G0, this exact probe and independent fresh-run rerun; no product gate for ignored-only code.
Skills O/P/A/prototype. Output durable evidence amendment via a separate planning writer after
terminal review. Unresolved directory identity or crash counterexample blocks P06 and P14–P21.

### P03 — Prerequisite CLI atomic-state and timeout experiment

New ignored `validation/local.py` plus unique owned state/spool/run children; no real XDG dirs.
Role prototype/review, maximum; skills O/prototype. Actual whole commands race add/rm/pull/checkout,
context/config/token writes with push to confirm F7 boundaries. Candidate one-root lock plus atomic
working record/spool is killed before/after file sync, replace, directory sync, send, and success
reconciliation. Test reentrant refresh, stable lock inode, absent/old-format state, pending intent,
ENOSPC, same-size edit/growth/truncation/path replacement and partial resume. Preserve original source.
Attempt2 only showed StateDir lost intent; no candidate local protocol was tested there.

Candidate binding tests use two service identities and two authenticated subjects: logout/login,
config/env/global URL override, same URL replaced by a different instance, refresh to another actor,
and approved same-instance endpoint move. Include removal-only and empty pending requests. Assert
no status/HEAD/PATCH/retransmit after mismatch, no stage/spool loss, and same binding/ID/body after
crash. Exercise endpoint canonicalization/TLS/redirect refusal and the inspection/request race
with expected-binding headers. These are new prerequisite experiments, not attempt2 results.
For valid and expiring tokens vary API file/env/global overrides, issuer, client ID and upload base.
Observe NO credential-bearing identity/refresh/exchange/request to an unapproved destination, not
merely no replay. Cover first login, legacy token refusal, ordinary API reads, discovery endpoint
changes, declined approval, failed candidate auth, acceptance-save crashes and switch back to the
original namespace. Only approved matching provenance permits refresh; preserve all old intent.
Include §3.5's repository-helper candidate: explicit reviewed approval file versus implicit config,
stdin secret input, fresh identity switches and credential-only saves sharing the root lock. No
production helper exists in P03; this is throwaway protocol evidence. P23 supplies the real adapter.

Settle monotonic polling with delayed status/slow streaming/clock jumps. Demonstrate precisely
what is bounded, include request time, retain identity at deadline; do not call HTTPX inactivity
timeouts a hard wall-clock interrupt. Document supported local filesystem/locking requirement;
an unsupported NFS-hosted state root fails with guidance, not an unproved lock guarantee.
Future command: `PYTHONDONTWRITEBYTECODE=1 uv run --offline --no-sync python roadmap/prototypes/m11-production/__pycache__/validation/local.py --run local-a1 --deadline-seconds 900`.
Same ignored resource/budget/preserve rules as P02, G0 plus exact runner and fresh independent rerun.
Unresolved source/deadline/state invariant blocks P06/P22–P26.

### P04 — Prerequisite bounded scheduler/ownership experiment

New ignored `validation/runtime.py`, isolated PG and controlled filesystem barriers. Role
prototype/review, maximum; skills O/P/A/prototype. Candidate admission must reject beyond finite
active+waiting counts before executor submission. Exhaust pool acquisition and key reads, stall
one lake probe and both work pools, lose DB ownership, drain while HTTP callers disappear, fail
startup at each acquisition. Observe whole readiness <=2 s plus measured scheduling tolerance,
no second probe, no stale success, no DB close before tracked work settlement.

Start two candidate writer processes on one isolated lake/DB; second refuses while first active
or uncertain. Drop ownership connection and resume old process; no step/finalize may be newly
authorized. This is fail-closed coordination, not proof of NFS fencing. Demonstrate conservative
reservation retention during hung/failing work. Tiny eligibility/reconnect model supplies no such
evidence. Future command: `PYTHONDONTWRITEBYTECODE=1 uv run --offline --no-sync python roadmap/prototypes/m11-production/__pycache__/validation/runtime.py --run runtime-a1 --deadline-seconds 900`.
G0 plus exact runner/fresh review rerun, same bounds and preserve-on-failure; no service install.
Any scheduling/ownership defect blocks P06/P16.

### P05 — Prerequisite real tusd/nginx handoff experiment

**Blocked on offline assets owner.** Pin tusd v2.10.1 and an approved exact nginx patch/digest;
record cached image IDs, no pulls. New ignored `validation/tus.py`, rendered config, private
lake/PG/API/ports/containers, no shared network/stack mutation. Prototype/review maximum; O/P/A.
Prove client attempt identity across lost/duplicate creation response (including zero bytes),
without creating two filestore writers for one ID. Test HEAD/resume, final PATCH timeout/duplicate
hook, cancellation during an active PATCH, post-finish source-FD mutation against independent
sealed copy, token/ownership before body, OPTIONS, spoofed Forwarded, hook refusal, restart.
Prove safe per-upload source/info/lock cleanup after request closure; otherwise explicitly select
drained/fenced tusd maintenance-only cleanup and preserve charges until then. No mtime shortcut.
Also prove expected-binding header propagation through nginx authorization for POST/HEAD/PATCH
and instance/subject verification against the durable attempt before body acceptance. Lost creation
and endpoint-change cases must not authorize another namespace. Freeze this wire contract in P06;
if tusd strips required identity, correct the proposal and re-review rather than bypass validation.

Existing commands after asset supply: `docker run --rm --pull=never tusproject/tusd:v2.10.1 -help`;
`docker run --rm --pull=never --entrypoint sh tusproject/tusd:v2.10.1 -c true`.
Future runner: `PYTHONDONTWRITEBYTECODE=1 uv run --offline --no-sync python roadmap/prototypes/m11-production/__pycache__/validation/tus.py --run tus-a1 --deadline-seconds 900`;
it must run `nginx -t` on rendered config in its exact owned pinned container. G0 plus all commands
and fresh independent rerun. Missing assets are BLOCKED, not fake-PASS. P06 freezes the evidenced
creation/cleanup protocol before production implementation; no speculative flag assumptions.

### P06 — Freeze prerequisites and approve the executable code contract

Planning writer then independent maximum reviewer; own this plan and the three `design/m11-*.md`
records only. Copy essential P02–P05 outcomes/commands/limits inline; retain earlier failures.
Resolve directory proof representation, exact tus creation attempt mapping and safe cleanup mode,
monotonic timeout semantics, recovery binding/endpoint/header contracts, §3.5's complete CLI/dev
credential producer inventory and explicit approval-file seam, P07's caller transition
inventory, temporary schema staging, and final interface fields against actual
installed APIs. Any changed invariant returns to design review, not a worker's quiet choice.
Parent/site owner supply finite candidate budgets for test runs and named production evidence owners.
G0/link gate; skills implementation-plan/design-plan/prototype/O/P/A/D. No product suites.
Accept only after prerequisites and independent maximum plan review; no “ready” with unresolved
protocol decisions. The remaining production workload/ONTAP gates can remain blocked as explicitly
later deployment prerequisites. Ordinary code/fix uses medium or explicitly selected maximum.
Conservative `*:write` remains mandatory. Explicit maximum prerequisite probes/reviews stay maximum.

### P07 — Interlock unqualified production writers

Own API `settings.py`, `dependencies.py`, `runtime.py`, `app.py`, `routes/health.py`; their settings,
service/lifespan tests; `web/e2e/support/stack.mjs` explicit memory-test environment and existing
harness checks; error docs/snapshots as needed. Introduce explicit write mode disabled/journal/
memory-test. Default PostgreSQL mode is disabled; journal refuses startup until its composition
exists and has a valid ownership/config contract. Memory-test requires MemoryStore and is explicitly
non-production. Central mutation guard denies old file/directory/admin bootstrap mutations in a
read-only production runtime; token exchange/browse/status stay available. No settings flag may
re-enable legacy PG mutation. Read-only start must not reconcile bootstrap configuration or GC.
This phase does not implement publication. Acceptance: real PG disabled/read-only startup and
every mutation route denied; externally supplied resources not closed by failure; no schema/data
rewrite. Skills A/P/O/D. Commands GP, GC, GA. Production stays disabled through P38.

**Gate-preserving transition owned here, not deferred to P27c:** create new
`tests/support/legacy.py` with `legacy_postgres_runtime(settings, *, store, http, groups, clock)`.
It explicitly assembles Runtime, bootstrap/build_lake and existing domain collaborators on an
already connected, assigned disposable PostgresStore; it does NOT call production build_runtime
with a bypass flag. A tests-only ASGI factory uses the real routes/auth/error handlers and a
test-local mutation dependency override. No environment/config option, production import of
tests, or production legacy-mode enum exists. The ordinary create_app/build_runtime path remains
closed; tests assert that supplying a PG store with memory-test still refuses. Keep resource
ownership/close behavior explicit in the helper, using existing API/auth fixtures.

P07 also owns `tests/integration/test_api_postgres.py`, `tests/contract/test_postgres_runtime.py`,
`tests/support/{api,cli,lake}.py`, and affected existing API lifespan/service/settings tests for
these transitions only. Move the integration workflow's runtime construction (currently lines26–32)
to the tests-only helper. Retain its real PostgreSQL HTTP organization/grant/catalog/namespace/
activation/commit/search/audit/permission/stale-base assertions (including lines88–98), unchanged
in strength and without skip. It remains legacy domain/API integration evidence, NOT production
ingestion evidence. The PG runtime contract keeps an ordinary build_runtime read-only startup/
readiness/close test; seed required keys/admin rows explicitly via isolated setup before startup,
and assert no bootstrap reconciliation or writes during startup. Direct PG build_lake/bootstrap
callers in support/lake, contract bootstrap/races/suite remain direct domain tests on isolated DBs,
not production runtime exceptions. Memory API/CLI helpers, lifespan fixtures, web e2e and memory
seed callers explicitly select memory-test. The existing skipped CLI integration remains recorded
baseline only until its P33 replacement, never new proof.

Before P07 acceptance, enumerate all build_runtime/create_app/bootstrap callers in tests, scripts,
web harness and docker seed; record each as production-disabled, direct domain, memory-test or
tests-only PG composition. Unknown callers block acceptance, not the gate. Add denial tests through
ordinary app construction for every mutation category. P08–P26 direct collaborator tests never
depend on enabling journal startup. P19/P20 changed domain contracts get matching legacy-fixture
inputs at those slices without a wire translator. P27a's new router fixture is separate, P27b uses
it for CLI, and P27c converts the PG integration to real journal create_app and deletes
tests/support/legacy.py plus its dependency override. P28 tightens schema only after those callers
and remaining direct legacy adapter tests have moved to explicit object fixtures. No gate command,
coverage threshold or existing observable role/domain coverage is removed at any transition.

### P08 — Publication values, canonical request and deterministic step planning

New `core/lake/publications/{__init__,models,ports,errors,planning}.py`; new upload-attempt values
in `core/lake/uploads/models.py` without changing legacy behavior; `schema/documents/commit-request-v2.json`;
`core/security/rbac/{privileges,roles}.py` diagnostic privilege; `core/lake/audit/models.py` acceptance
action; pyproject area-boundary entries only; error registry/docs and direct tests in new
`tests/unit/lake/test_publications.py` plus naming/error/schema/RBAC tests. No route or DB wiring.
Define §3.1 values and bounded canonical digest. `plan_entries(current, request)` returns immutable
ordered entries/steps; `validate_request(body, dry_run=False)` refuses duplicate keys, file-tree
conflicts, over 10,000 entries/16 MiB, bad hashes/IDs/host/message. Empty/removal-only work retains ID.
Case-only replacement is a single logical add with old spelling retained in its plan.
Include instance UUID/subject in UploadView and CommitOutcome values for the HTTP binding echo;
the actor remains server-authenticated, not a client authority field in the canonical commit body.
Acceptance: determinism/order independence where semantic, changed payload conflict digest,
boundaries and exact errors, explicit no-filesystem domain imports. No prototype literal digest
is reused. Skills O/P/D. Commands GP, GD; future focused command
`uv run --offline --no-sync pytest tests/unit/lake/test_publications.py`.

### P09 — Additive ownership/journal schema

New `migrations/versions/0004_publication_ownership.py`, tables modules under new metastore
`objects/`, `publications/`, `quotas/`, `writers/`, new `uploads/attempttables.py`; modify
`collections/tables.py`, `files/tables.py`, `metastore/tables.py` load list; extend migration and
PG constraint tests. Exactly §3.2 relations/columns/indexes, cyclic FK order and temporary
`upload_attempts` name; no runtime SQL yet. Preserve 0003 byte-for-byte. Migration refuses any
legacy byte-bearing files/uploads/removals transactionally; downgrade refuses owned publication
data. Fresh-schema gate fixtures remain disposable, not permission to reset test-bed data.
Also own new `core/metastore/writers/identitytables.py` for the §3.5 service_identity singleton;
include it in metadata/schema-map and empty/refusal migration tests. No configured UUID is inferred
by Alembic. Identity initialization and runtime validation are P11/P16, before the P27a route.
An initialized service_identity is durable instance history: downgrade refuses it too; do not
silently drop the binding while retaining configuration/markers that could reuse that UUID.
Acceptance: upgrade empty, populated refusal with rows unchanged, empty downgrade/re-upgrade,
schema map, uniqueness/FK/state/NOT NULL/negative quota failures and indexes. No JSON plan blob.
Skills P/O. Commands GP, GC;
`uv run --offline --no-sync pytest -m contract tests/contract/test_migration.py tests/contract/test_postgres_constraints.py`.

### P10 — Object, upload-attempt and quota adapters

New `core/lake/objects/{__init__,models,ports}.py`, `core/lake/quotas/{__init__,models,ports}.py`;
new metastore objects/quotas memory/postgres modules and `uploads/attemptmemory.py`
(`MemoryUploadAttempts`), `uploads/attemptpostgres.py` (`PostgresUploadAttempts`); `uploads/ports.py` new
AttemptStore; transaction/metastore memory/store/postgres composition properties; shared contract
cases; pyproject import-contract lists for these new lake areas only. Implement insert/get/ordered
lock/update by IDs; `reserve(scopes, owner, amounts)` and
`transfer/release` idempotently. Objects/attempt locators never reused; DB-clock expiry accessor
is part of the consumer-owned transaction port. No latest-placement lookup in the new adapter.
Acceptance: both stores same observable contract; PG race at exact quota boundary, rollback,
double release, zero-byte count/inodes, unsigned diagnostic inode >2^63. No public storage calls.
Skills O/P. Commands GP, GC;
`uv run --offline --no-sync pytest -m contract tests/contract/test_postgres_races.py tests/contract/test_postgres_constraints.py`.

### P11 — Request/step/reference/cleanup and writer adapters

New metastore publications/writers `{__init__,memory,postgres}.py`, publication ports and
transaction properties; extend shared contract/race/runtime tests. Methods: lookup(actor, request),
insert_once, lock operation, ordered entries/steps, acknowledge, bounded pending scan, reference
transfer, tombstone claim/finish, cleanup candidate read; writer `acquire_initial`, `mark_uncertain`,
`handover(expected_epoch, evidence)`. Dedicated ownership connection loss notification is distinct
from transaction locks. Unique request insert conflict re-reads exact outcome without leaking a
raw PG unique error. Never take cleanup-row locks then collection locks. No lease takeover method.
Own `ServiceIdentityStore` in core/lake/publications/ports.py and its frozen value in models.py,
with memory/PG implementations in metastore/writers and §3.5 insert-once
initialization/read methods. Tests prove concurrent different-ID initialization cannot replace the
winner, same-ID retry is idempotent, and reads never initialize. Setup fixtures initialize before
P16 runtime validation; no dependency on the later P31 operator command is needed for these gates.
Acceptance: two connections same/different requests/collections, deleted live collection retains
outcome/scope/cleanup, bounded scans, FK integrity, one writer and refusal after uncertain loss.
Skills O/P. Commands GP, GC; focused `tests/contract/test_postgres_races.py` and
`tests/contract/test_postgres_runtime.py` via `uv run --offline --no-sync pytest -m contract`.

### P12 — Durable upload eligibility, reservations and cancellation

New `core/lake/uploads/attempts.py` (`UploadAttempts`), exports/ports/models/errors and direct
`tests/unit/lake/test_upload_attempts.py`, shared PG race cases. It uses P10/P11 adapters, no disk.
Implement §3 lifecycle and exact begin identity from P05: repeat same attempt returns one row,
changed semantic fields conflict. Reserve 2S and counts before receive; start one seal ticket;
finish checks measured proof, expiry and current state under ordered locks. Cancellation/expiry/
supersession atomically makes eligibility false and creates charged cleanup, never public work.
Ready/reserved/consumed views expose expiry/reason/object/operation/superseded-by. Pending collection
blocks new begin, not completion of previously admitted private seal. Reserved cancellation refuses.
Acceptance: controlled DB time at expiry, cancel/finish/delete races on PG, double hook, late old
completion after newer attempt, all permission/error boundaries; no negative/leaked-by-release
charges. Attempt2 predicate is not implementation proof. Skills O/P/D. Commands GP, GC, GD and
`uv run --offline --no-sync pytest tests/unit/lake/test_upload_attempts.py` (new test).

### P13 — Commit acceptance, exact status and finalization

New `core/lake/publications/operations.py`; publication models/ports; minimal collection/file
model+store fields for pending/object identity and audit writer use; tests
`tests/unit/lake/test_publications.py`, new `tests/contract/test_publications.py`, existing race
fixtures. No API route or I/O executor. Implement §3.1 submit/status/next_steps/ack/finalize with
the §3.2 lock order. Persist semantic rejection without rolling it back by raising inside its
transaction. Persist accepted immutable plan, old/new references, pending and quota claims together.
No version increment until all durable step evidence acknowledged; finalize consumes once and
preserves outcome after deletion/revocation. No stored payload returned to a status reader.
Acceptance: stale/revoked/tree/ineligible refuses without effects, same request returns original
before current-base check, actor scope, concurrent double submit/finalize, rollback, busy metadata
reservation checks, removals/empty/case changes, count/audit/version exactly once on real PG.
Skills O/P/D. Commands GP, GC, GD and
`uv run --offline --no-sync pytest -m contract tests/contract/test_publications.py` (new).

### P14 — Durable storage copy, exclusive names and sync contracts

Own `core/storage/{ports,posix,memory,errors,__init__}.py`, `pkg/fs/posix.py`; new
`core/storage/objects.py`; extend shared matrix/storage/posix/race tests, new
`tests/unit/storage/test_objects.py`. Add exact storage signatures:
`copy_sealed(source, destination, *, temporary_name, expected_size, expected_sha256) -> SealedFile`,
`link_once(source, destination, *, inode) -> None`, `sync_directory(location) -> None`, and
`list_children(location) -> Iterator[Entry]` (genuinely shallow). Add
`capacity() -> Capacity(free_bytes: int, free_inodes: int)` behind the same port for the conservative
reserve guard; no route calls statvfs itself. `SealedFile` is measured size,
hash, inode and owned locator, not authority without DB/manifest association. Unique temps are
independent of basename, O_EXCL, never truncation of someone else's name. Add manifest write using
unique temp/file sync/replace/parent sync. Directory sync opens a usable directory FD, not fsync
on O_PATH. Preserve no-follow/error path precedence; extend full MemoryStorage contract for every
new case. Use P02's reviewed directory-proof algorithm, not the tiny candidate's pathname trust.
Acceptance: different inode from writable tusd FD, same bytes/EOF/hash, missing/wrong/link source,
foreign temp/destination, max name, ENOSPC/EIO/fsync faults; no ready proof on sync failure; outside
snapshot unchanged. Skills O. Commands GP plus
`uv run --offline --no-sync pytest tests/unit/storage/test_containment.py tests/unit/storage/test_objects.py tests/unit/storage/test_races.py tests/unit/pkg/test_posix.py`.

### P15 — Identity-bound publication and directory-step rules

New `core/storage/publication.py` (`Publisher.apply(step, objects) -> StepEvidence`), publication
proof values; extend `directories.py` for unique metadata temps and explicit containing-dir sync,
`removal.py` pruning for planned owned directories only; both adapters/matrix as required. New
`tests/unit/storage/test_publication.py`, existing directory/removal tests. Rule module has no
DB, asyncio, os or Path; uses only Storage/LakePath. It accepts a located immutable plan and
retained object evidence, never chooses the latest upload. Implement §3.3 ordered add/replace/
remove/mkdir/rmdir/retry and post-effect verification. Unknown target blocks; no backup recycling.
Acceptance: both adapters, existing-new retry, retained-old replacement, foreign same bytes,
case-only/file↔tree transitions, interrupted directory creation/removal with parent sync, every
required sync failure prevents acknowledgment. P02 must already have closed directory ownership.
Skills O. Commands GP and
`uv run --offline --no-sync pytest tests/unit/storage/test_publication.py tests/unit/storage/test_directories.py tests/unit/storage/test_removal.py tests/unit/storage/test_containment.py`.

### P16 — Single-writer ownership, bounded execution and lifecycle

New API `disk/admission.py`, `disk/ownership.py`, `disk/guards.py`; modify `disk/lake.py`, runtime,
app lifespan, settings and metastore readiness/ownership connection seams; their tests plus new
`tests/unit/api/test_writer.py` and PG runtime races. Assemble one WriterOwner(epoch, process ID,
config digest), bounded admission tokens/futures and scope guards. No generic work-queue framework.
Implement §3.4 readiness/drain/startup disposal, including borrowed-versus-owned store/client rules.
`measure(located, action)` checks markers before large work; all full reads/hashes stay off short
pool. `drain(deadline) -> DrainResult` tracks HTTP-independent futures. Uncertain owner never resumes
itself. No auto-fence by timeout. Keep production interlock.
Validate Settings.instance_id against persisted service_identity for PG runtime, including read-only
startup; fail missing/mismatch without modifying either. Explicit memory-test gets its configured
identity in its isolated store. Own PG runtime/setup fixtures for this new prerequisite, not a
production bootstrap exception. Restart keeps identity; lost history cannot silently keep its UUID.
Acceptance: P04 scenarios on actual runtime and PG, two independent runtimes, no new filesystem
unit after ownership loss, 2 s total deadline including exhausted DB pool/key read, one probe lane,
finite waiters, shutdown-resource ordering and startup failures. Skills A/O/P/D. Commands GP, GC,
GA if health schema changes; `uv run --offline --no-sync pytest tests/unit/api/test_lake_disk.py tests/unit/api/test_lifespan.py tests/unit/api/test_writer.py`.

### P17 — Private seal orchestration

New `applications/api/disk/sealing.py` (`Seals.seal(ticket) -> UploadView`, `recover_seals(owner)`),
runtime factory construction without public route wiring; new `tests/unit/api/test_sealing.py`
and new PG/FS contract cases in `tests/contract/test_sealing.py`. Call UploadAttempts for ticket/
finish; Storage object rules for bounded copy/manifest; LakeDisk for marker/admission/future life.
Normal and restart paths use the same ticket/evidence validation. One tracked future per upload,
duplicates cannot allocate another copy or bypass waiter limit. Cancelled caller does not cancel
an in-flight syscall; cancel/expiry wins eligibility and leaves private charged cleanup.
Acceptance: private only before acceptance, server hash re-opened, source FD mutation isolated,
lost ready transaction/response and manifest mismatch, marker checked before hash, capacity held
on failed copy. Skills A/O/P. Commands GP, GC;
`uv run --offline --no-sync pytest tests/unit/api/test_sealing.py tests/contract/test_sealing.py`.

### P18 — Accepted materialization and restart recovery

New API `disk/publications.py` (`Materializer.materialize(operation_id)` and
`recover_pending(owner, limit)`), `background.py` bounded recovery loop; runtime construction only;
new `tests/unit/api/test_publications.py`, extend real `tests/contract/test_publications.py`.
Use Publications.next_steps/ack/finalize and Publisher; no separate recovery algorithm and no
filesystem call within transaction. Polling/HTTP lifetime does not own tasks. Keep old/new object
references and reservation on every error. Clear pending only in finalization. Recovery gets
bounded priority over new work; blocked operations have explicit status and retry, not busy loops.
Acceptance: two-file add/remove, storage error leaves pending/no success, re-entry succeeds once,
foreign target blocks, audit/count/version stable; duplicate independent runtime refused by owner
before physical effects. Observe full PG adapters, not tiny model SQL. Skills A/O/P. Commands GP,
GC; `uv run --offline --no-sync pytest tests/unit/api/test_publications.py tests/contract/test_publications.py`.

### P19 — Metadata, schema, group and repair ordering

Own lake collections metadata/lifecycle, catalogs operations and repairs models/operations;
API disk directories/repair, affected directory routes and guard dependency; existing metadata/
directory/group/repair tests. Extend `Repairs.expected(planned) -> PlannedRow | None` to current
resource ID/version/catalog ID/version/share_group/rendered metadata. Plan's captured group is
not authoritative. Process guard encloses DB decision plus physical work; no process-lock wait
inside DB transaction. Refuse affected pending collection/catalog before rows change. All physical
units still marker/no-follow. Ordinary DB-first disk failure keeps rows for repair.
Acceptance: older metadata cannot write last, schema/group vs pending commit refusal, repair vs
group change and delete/recreate barriers, unplanned siblings untouched, exact failure paths and
three reasons remain. Unique temp failure path flows from Storage to RepairFailureOut; regenerate
its authoritative descriptions if the temp name changes. Skills O/P/A/W/D. Commands GP, GC, GA;
`uv run --offline --no-sync pytest tests/unit/api/test_directory_verbs.py tests/unit/api/test_repair.py tests/unit/lake/test_repairs.py tests/unit/api/test_catalog_share_group.py`.

### P20 — Delete reservations and name tombstones

Own lake collection/catalog/namespace/organization delete/create operations and the identity-bound
cleanup port; API directory delete orchestration; new `tests/unit/lake/test_cleanup.py` plus
existing delete and PG race tests. Delete transaction refuses pending/nonempty files, makes
unreserved uploads ineligible, saves owned cleanup and a path tombstone, then removes the row.
Outcomes/original scope/physical charges survive. Creation checks tombstone under structural/catalog
locks; no path-only adoption of a recreated resource. Privileges/dry-run semantics remain.
Acceptance: delete vs seal/accept/create on real PG, no FK exception, no orphaned charge, no name
reuse while cleanup kept/blocked, rooted organization admin ownership preserved. Old inode-only
Removal is not used by this new path. Skills O/P/A/D. Commands GP, GC, GD;
`uv run --offline --no-sync pytest tests/unit/lake/test_cleanup.py tests/contract/test_postgres_races.py`.

### P21 — Identity-bound cleanup and physical accounting release

New `core/lake/objects/cleanup.py`, `applications/api/disk/cleanup.py`, bounded background cleanup
loop, object/cleanup/quota adapter operations; new storage/API/contract cleanup tests. Use §3.3
two-transaction gc_pending/unlink-sync/release protocol. Source/info/tusd-lock cleanup uses only
the P05 proven safe mode; uncertain accessor retains bytes/counts and blocks reclamation.
Shallow inventory reconciles known IDs only. Unknown entries are reported, never adopted/deleted.
Delete directory cleanup removes only recorded owned metadata/temp/empty directories, stops at
foreign/unrecorded/symlink, retains tombstone. No mtime sweep or suffix backup purge.
Acceptance: cancel/expiry/supersede/finalize GC conservation, unlink-before-release crash retry,
new references forbidden after gc_pending, stale cleanup cannot touch newer public files, FD-held
source charge retained, blocked backlog exhausts new admission without losing recovery reserve.
Skills O/P/A. Commands GP, GC; future focused
`uv run --offline --no-sync pytest tests/unit/api/test_cleanup.py tests/contract/test_cleanup.py`.

### P22 — Local atomic generation and stable lock primitives

New CLI `localstate.py` (`LocalState`, `StateSession`, frozen `WorkingState`, `PendingCommit`),
`stateio.py` (local file I/O only, not lake port), new `tests/unit/cli/test_localstate.py`.
Implement §3.5 versioned `working.json`, unique exclusive 0600 temps, file/directory sync, stable
root lock and reentrancy. `LocalState.mutate() -> ContextManager[StateSession]` reloads generation;
`session.replace(expected_generation, state)` checks it. Include local draft and pending/spool
references in the generation. Token/config saves use the same lock and durable primitive, with
their own atomic files; context selection cannot drop old working-copy intent. No old format
conversion. Leave legacy callers unconnected until P27, as the explicit temporary staging exception.
For endpoint acceptance, own a durable transaction manifest selecting the old or new credential/
approval and working-state generations together. Publish one atomic manifest only after all new
files and parents are synced; readers use its selected generations, never partly replaced files.
Before manifest publication keep the old selection; afterward recover the new selection. Unselected
owned generations can be collected only after recovery. P03 validates these crash boundaries.
Implement §3.5's `replace_credentials` and `accept_endpoint` on StateSession now, independent of
P23's token schema: they take serialized credential bytes and never authenticate or infer provenance.
Keep the prior selection/generation recoverable on interrupted or failed save. Credential-only
publication must preserve all working/config selection references; combined endpoint publication
changes only the selected copy's endpoints and credential snapshot. Test real-process contention,
private file modes/ownership/no-follow access, malformed manifest refusal and every sync boundary.
Do not require the future dev script or identity route to test these primitives.
WorkingState, PendingCommit and each durable attempt include §3.5 RecoveryBinding, not just UUIDs.
Key working copies by instance/subject/collection identity, with endpoints recorded in their state;
never merge two bindings by collection name. Validate agreement of nested bindings before writing
or loading. Missing/partial binding is unsupported state, preserved with guidance. Test round trips,
all sync crash boundaries, removal-only intent, and mismatched/corrupt nested records.
Acceptance: two real processes, all sync/replace failures preserve a valid old or new generation,
no fixed temp collision or lock deletion, unsupported-format refusal preserves original files.
Skills D/O. Commands GP, GD and
`uv run --offline --no-sync pytest tests/unit/cli/test_localstate.py`.

### P23 — Mutation, fresh-login and development-auth collaborators

Own CLI `services.py`, `app.py`, `main.py`, `config.py`, `login.py`; new `credentials.py` and
command-session adapter in `localstate.py`; new `tests/unit/cli/test_mutation_lock.py`. Inventory
every writer in commands stage/context/change/create/delete/session/adm and walkthrough, PLUS
every external producer/caller in §3.5 before wiring. Provide
`Services.mutation()` acquiring root lock before Config/current resolution; nested token refresh
shares the session, external commands conflict. Pure read commands use one atomic snapshot;
implicit token refresh takes the same mutation boundary. Expose the adapter for P27 wiring,
not a partial policy where only push locks. No change to lake ShareReader typing.
Own new CLI `identity.py` (`RecoveryIdentity.verify`, canonical endpoint validation and explicit
same-binding endpoint acceptance collaborator), `client.py` request binding headers/response checks,
and `tests/unit/cli/test_identity.py`. Use the planned authenticated identity response as a network
fixture until P27a, not a production dependency on that later route. Config file/environment/global
override precedence is resolved before verification; logout/refresh/login never rewrite bindings.
Test TLS/redirect/URL boundaries, actor change, same-URL instance replacement, endpoint approval,
and token change between check and request. Failure preserves pending work and performs no recovery
request. Also own `state.py::TokenState`, `errors.py`, the §3.5 FreshLogin/DestinationApproval/
CredentialStore/protocols and Config.uploads_url/env selection, and existing `test_login.py` plus
new `tests/unit/cli/test_credentials.py`. Implement new collaborators additively and unconnected to
old commands until P27b: do not prematurely replace a live reader while old producers still run.
Legacy Tokens/Session call paths remain only for the already declared unreleased staging interval;
no new test uses them to claim new-contract evidence. P27b removes the old credential entry points
in the same slice that switches ALL producers. This staging is not legacy-state compatibility.

Create `scripts/dev_login.py::{main,DevelopmentPasswordGrant,FileApproval}` with exactly §3.5's
public options, explicit approval and secret-input rules. It imports the shared collaborators;
there is no standalone exchange/state serializer in the adapter. Create `tests/unit/test_dev_login.py`
and `tests/support/devauth.py`; extend FakeIssuer.handler and request observation, ScriptedPrompter
and scoped CLI fixtures only as needed for the new seam. P23's isolated network fixture supplies
the future recovery-identity response and real exchange behavior; it is not the future route or
an exposed application bypass. Independently test helper subprocess -> new credential reader now;
P27b adds helper -> installed CLI subprocess with the real P27a router. No backward dependency.

New Services/Session/Oidc/ApiClient paths enforce trust before credentials for ordinary calls and
recovery. Test §3.5's matrix at the new-collaborator/helper boundary here; whole installed-CLI rows
belong to P27b and full-application rows to P29. This avoids requiring unconnected commands or a
future route in P23; no matrix row is waived. Include valid/expiring state, approved/declined file/prompt inputs,
changed selections/provenance, discovery/redirect failures, identity mismatch, lock contention and
interrupted save. Observe requests at approved AND unapproved endpoints, including password,
company-token and refresh bodies. Assert state bytes/permissions and old intent, not private call
counts. Keep actual PG/FS/real-adapter coverage elsewhere. P06 freezes the wire contract first.
Acceptance: exhaustive writer inventory mapped to command handlers; races/reentrant refresh and
config switch preserve pending old copy; same-process fake helpers do not substitute for process
tests. No test-only bypass exposed as a user option. Skills D/O. Commands GP, GD, GDEV;
`uv run --offline --no-sync pytest tests/unit/cli/test_mutation_lock.py` (new).

### P24 — Copy-on-add local spools

New CLI `spool.py` (`SpoolStore.capture(source, budget) -> SpoolRef`, `open(ref)`,
`collect_unreferenced(state)`), staging collaborator in new `staging.py`; direct tests
`tests/unit/cli/test_spool.py`. Use §3.5 independent inode, streamed bounded copy/hash, source
stability checks/EOF, private mode/unique temps/syncs, quotas counting old and temporary copies.
Stage/spool publication is one WorkingState replacement under mutation lock. Preserve source path
for display only. Source folder traversal remains read-only and does not follow source symlinks.
GC uses durable references after recovery, not age; old staged spool survives a replacement failure.
Spool references belong to their bound WorkingState, even for removal-only pending work with older
unreferenced-looking spools. A binding mismatch is not permission to collect or transfer them;
test preservation across config/login/context changes and failed endpoint acceptance.
Acceptance: mutation after add cannot change upload bytes; same-size/growth/truncate/replaced path
observed changes refuse; no coherent snapshot claim; ENOSPC/fsync/crash source intact; count/byte
boundary including zero-byte files, unsupported cross-filesystem layout refusal. Skills D/O.
Commands GP, GD; `uv run --offline --no-sync pytest tests/unit/cli/test_spool.py`.

### P25 — Tus client with durable attempts and eligibility

New CLI `transfer.py` (`Transfer.upload(collection_id, staged, session, deadline)`), reusable
deadline/network seam in `client.py`/services, new `tests/unit/cli/test_transfer.py`, extend fake
transport in `tests/support/tus.py` with a **separate journal fixture**, not an old-wire translator.
Read only spool. Persist attempt identity before creation using P05 mapping, URL/upload/object
identity after replies; query attempt status after lost zero-byte creation. Poll exact expiry/
eligibility/consuming-operation fields. No reuse of consumed, superseded or expired ready data.
Timeout preserves identities; explicit restart cancels/supersedes durably. Retain 64 MiB chunk
default, HEAD offset checks and token-before-body behavior. Compare server sealed hash to spool.
Verify the saved RecoveryBinding before every resume/status/cancel/supersede/send, revalidate on
refresh, send expected-binding headers and check returned binding. Resolve relative tus locators
only within the explicitly approved upload base. Wrong actor/instance or endpoint change cannot
trigger HEAD/PATCH/new creation; preserve attempts and spools. Include same URL/new instance,
global/env URL override, refresh race, redirect and same-instance approved endpoint migration tests.
Repeat valid/expiring credential and issuer/client/API/upload-change cases from P03: local trust
and provenance checks precede Session refresh and identity; unapproved hosts receive no credentials
in any identity/refresh/exchange/tus request. Failed or declined approval preserves durable attempts.
Acceptance: empty POST loss, final PATCH 500/502/504/timeout, HEAD resume, wrong user/auth/hash,
late old hook after newer success, DB expiry boundaries, monotonic time spent in requests/sleep,
and no second upload from mere timeout. Skills D. Commands GP, GD;
`uv run --offline --no-sync pytest tests/unit/cli/test_transfer.py` (new).

### P26 — Exact commit recovery and staged mutation policy

New CLI `publication.py` (`Push.submit`, `resume`, `reconcile_pending`), `staging.py` pending
guards, new `tests/unit/cli/test_publication.py`; reuse ApiClient and LocalState, no API imports.
Save binding/UUID/canonical body/digest/generation before POST; verify binding then use GET exact
request on uncertainty before base fetch/preflight. Only same-binding missing outcome replays same
ID/body; 202/blocked/rejected retains intent;
matching success clears only that generation and advances base atomically. Rebase changes ID only
after terminal reconciliation. Pull/add/rm/checkout-base mutation cannot destroy unresolved intent;
context switch can preserve it and select another copy. Delete collection first uses exact
removal commit and waits for its success. No “version advanced” fallback, even for no adds.
Acceptance: lost-before-apply vs lost-after-apply, unrelated metadata version, removal-only/mixed/
empty payloads, consumed upload status, process kill around intent/send/success state replace.
Prototype `_recover` counterexample becomes a real workflow regression, not a copied private test.
Include removal-only/empty/mixed payloads after logout/login as another subject, config/env/global
URL changes, and replacement of a service at the same URL. No status/retransmit or local clear on
mismatch; the original actor/instance can later recover the unchanged intent exactly once. A
binding mismatch returned after inspection is not treated as not-found. Approved same-instance
endpoint acceptance preserves IDs and body; disallow cross-instance/actor acceptance.
Skills D/O. Commands GP, GD;
`uv run --offline --no-sync pytest tests/unit/cli/test_publication.py` (new).

### P27a — Journal HTTP adapters and schemas, still unexposed

Own new endpoints/schema `publications.py` and `uploadattempts.py`, API dependencies, a new
`routes/v1/publication.py` router factory, collection/health view conversion and dedicated API
tests. Compose P12/P13/P17/P18/P19–P21 collaborators, not new algorithms. Mount the real new router
in an isolated ASGI fixture for tests; production router registration stays disabled. New schema
requires upload/object/request IDs, exposes exact status/cancel/attempt lookup and pending, and
has no old-body alias. Hooks only seal; duplicate hook wait uses the tracked future. Commit POST
200/202/saved refusal and creator-only status obey §3.1, including bounded pre-parse body handling.
Also own endpoints/auth.py, schema/auth.py and new recovery-identity schema/route tests for §3.5's
authenticated combined identity. Use P11/P16's persisted/validated UUID, not a new random ID per
process. Own expected-binding dependency and RECOVERY_BINDING_MISMATCH error registry/docs, plus
binding fields on upload/publication outputs and tus authorization headers. The isolated router
fixture mounts this auth route too. Missing/malformed expected headers refuse before lookup/effects;
actor/instance mismatch is 409, not another actor's indistinguishable status 404. Existing ordinary
creator-only status authorization remains; possession of expected headers grants no privilege.

Use POST `/api/v1/uploads/{id}/cancel` and GET `/api/v1/upload-attempts/{attempt_id}` (creator key)
for cancellation and lost-creation recovery. Tus metadata keys are collection, rel_path,
attempt_id, sha256, subject to the proven creation rule frozen by P05/P06. Test the intended
schema with actual router generation; final application snapshot changes occur at P27c. Do not
publish a second API or runtime configuration switch for legacy writers.
Acceptance: HTTP/auth/path/expiry/dry-run/revocation/deletion/status/body bounds with real domain
collaborators, no route-built lake paths. Skills O/P/A/D. Commands GP, GC, GD;
`uv run --offline --no-sync pytest tests/unit/api/test_publications.py tests/unit/api/test_sealing.py`.

### P27b — One CLI and external credential-producer cutover

Own CLI sync/state/services and commands stage/context/change/create/delete/session/adm, login/
walkthrough call sites from the P23 inventory; CLI conftest and support fixtures; existing affected
CLI tests and generated CLI reference. Wire P22–P26, not new algorithms. All mutators lock before
context/current resolution; new WorkingState is the only new write format. Push uses Transfer and
exact Publications outcome, delete waits for its removal outcome. Replace obsolete private-helper/
copy-absence/unsafe same-size-source expectations with their earlier public regression tests.

The CLI tests use a separately named journal-service fixture mounting P27a's real router and
shared auth/error dependencies, plus a journal tus transport. It must not translate old bodies
or conceal server eligibility. Old API unit fixtures can remain isolated until P27c; no deployed
compatibility is supported. Acceptance: whole-command process races, token refresh/config/draft
writers, exact pending reconciliation, old-state refusal without data deletion, no lake writes.
Skills D/O. Commands GP, GD, GDEV;
`uv run --offline --no-sync pytest tests/unit/cli`.

**All credential producers switch here, not in P33.** Own `scripts/dev_login.py` composition
call sites, delete `scripts/dev-login.sh`, and change `scripts/e2e.sh::login_as` and
`scripts/demo-noaa.sh` to invoke the Python entry point. Remove shell sourcing, positional
passwords, raw curl exchange, truncating token writes and fallback development credentials.
Retire old `Tokens`, `StateDir.write_tokens/read_tokens/delete_tokens` credential entry points
and old Session.login exchange-and-save path once every caller below moves. Working-state cleanup
still belongs to P28; no user credential, old working file or unknown data is deleted by cutover.

Both scripts take candidate selections from required nonsecret `HURON_DEV_API_URL`,
`HURON_DEV_UPLOADS_URL`, `HURON_DEV_ISSUER`, `HURON_DEV_CLIENT_ID`. These are selectors, NOT trust.
They explicitly pass `--approval-file` only from reviewed `HURON_DEV_APPROVAL_FILE` (or e2e's
`--approval-file FILE`); absent approval uses a real terminal prompt or refuses noninteractive use.
For automation, `HURON_DEV_PASSWORD_FILE` (or e2e's `--password-file FILE`) is an owned 0600
regular no-follow file. Open it without tracing and redirect stdin to `--password-stdin`; never
pass its contents to argv or export them. Interactive demo uses the helper's no-echo prompt.
The e2e file covers the assigned realm's test identities; the demo can receive a different file
for its admin identity. Do not assume all dev users share a password in product code.

Scripts set matching API/uploads/issuer/client CLI config under their isolated XDG roots; clear
inherited `HURON_API_URL/HURON_UPLOADS_URL/HURON_ISSUER/HURON_CLIENT_ID/HURON_MOUNT_PREFIX` selection
overrides first. Config writes cannot grant approval. E2e fresh-authenticates each login_as identity;
demo authenticates before its first describe-org/read and retains its persistent isolated cache
state. Require `huron -o json whoami` after helper success and verify the expected development
identity. Neither a saved valid token nor a prior successful run bypasses fresh helper approval.

Own `Makefile::demo-noaa` help/required-input checks (same target, no token generation in Make),
new `scripts/dev-auth.example.json`, `examples/noaa/load.sh` login/reset comments and error guidance,
`examples/noaa/README.md` login/demo/state/reset instructions, README Quick start/CLI on host/NOAA/
pre-release sections and `docs/{architecture,user-guide,operator}.md` auth/state/pre-release
sections. Document the exact helper command, explicit approval versus config, stdin/terminal
secret input, legacy refusal and preservation, uploads selection, and no raw-token-copy workaround.
Remove the promise that a reset database may adopt a byte-bearing old lake; use a fresh pair or
the separately reviewed import path. These command/auth changes cannot wait for P36. Mark the full
journal stack/demo as awaiting P33 until actually qualified, without implying a passing workflow.
No change to NOAA fetch.py or unrelated broker/web authentication is owned here.

Own `tests/support/cli.py::Cli.login_as`, `tests/fakes/issuer.py`, CLI conftest, token tests in
`test_login.py`/`test_foundation.py`, and `tests/integration/test_cli_end_to_end.py::Stack.login`:
replace positive direct-mint/write fixtures with explicit fresh approval and real exchange through
the test transport. The skipped Stack body must still stop importing the removed Tokens API now;
P33 replaces its stack/skip, preserving every-role assertions. Faulty token/state documents are
explicit negative fixtures, not approval/provenance migration. Keep permission/owner tests and
existing device/browser/refresh/error coverage. Never make all prompts answer yes automatically.
Also own Stack's Services/state construction and the stale-base fixture accesses in
test_every_role_end_to_end so P28 removes old working-state APIs without leaving dangling callers.
This changes fixture setup, not role/outcome assertions or the P33 real-stack obligation.

Extend `tests/unit/test_dev_login.py` to invoke the actual helper and installed `huron` executable
over P27a's real isolated router with test-owned HTTP IdP endpoints. Run every §3.5 public matrix
row, real XDG filesystem and subprocess contention; positive login must immediately support a real
CLI read, with expected identity and no stage/spool changes. Scripts' argument/secret plumbing must
also have subprocess coverage there at the subprocess/network boundary, not syntax-only assurance.
P29 repeats full-app crash tests; P33 is the mandatory later real-stack e2e/demo gate. The total
serial order remains P22 primitives -> P23 seam -> P27a router -> P27b all producers/callers ->
P27c production composition -> P29 crash -> P33 stack -> P34 deployment; no release in between.

Additional root checks here:

```sh
bash -n scripts/e2e.sh scripts/demo-noaa.sh examples/noaa/load.sh
uv run --offline --no-sync python scripts/check_links.py README.md examples/noaa/README.md docs/architecture.md docs/user-guide.md docs/operator.md
```

Inventory all remaining `dev-login.sh`, `dev_login`, `tokens.json`, `Tokens`, `write_tokens` and
credential-state writes after cutover. Classify each result: new helper/reader, negative fixture,
unrelated broker/web/seed, or preserved history. No live legacy producer, shell alias or active
documented invocation may remain. Shell syntax and this inventory are additive, not acceptance
substitutes for GP/GD/GDEV, subprocess behavior or the later complete workflows.

Own the new `huron context accept-endpoint --api-url URL [--uploads-url URL]` command, its generated
help/reference and command tests. It uses P23's same-binding collaborator; it cannot force-rebind
another instance/principal. Checkout obtains authenticated identity before persisting a working
copy; config/logout/login only change selection/credentials, preserving every old bound copy.
Explicitly own `src/huron/applications/cli/commands/__init__.py::LAYOUT`: add `context` after
`config` in Settings, with PANEL_OF/VERBS derived as today. `commands/context.py::register` keeps
root org/catalog unchanged and registers exactly one Typer context group with accept-endpoint;
the central register calls it once, with no duplicate root/group registration. Own
`tests/unit/cli/test_panels.py::EXPECTED` and registration/help tests: retain all existing root
org/catalog assertions, five panels and unique verbs, add context and its nested help/command.
The existing scripts/cli_reference.py layout guard stays strict and unchanged. Generate reference
with the exact GD command and run every GP/GD help/reference/site gate; no unplaced visible verb.
Whole-command tests exercise §3.5 approval before login/token acquisition, first login, ordinary
API calls, valid/expiring tokens, issuer/client/URL overrides, abort and switch-back recovery.
No old credential is copied to the candidate; only verified same-binding acceptance changes the
working endpoint, with interrupted acceptance preserving a consistent old or new local transaction.

### P27c — Final application composition and contract consumers

Own `core/lake/bootstrap.py`, API app/runtime/dependencies/router, old files/uploads endpoint
registration, collection/health output models, affected API/seed/support fixtures, snapshots/error
docs, generated web types and bounded activity vocabulary. Fixture ownership includes
`tests/integration/test_api_postgres.py`, `tests/support/{api,lake,tus,tusd}.py`,
`web/e2e/support/{seed,stack,fixture}.mjs` and `docker/seed/run.mjs`, only their changed protocol
producers/consumers. Register P27a router as the **only**
file-mutation/upload protocol; use P27b CLI. Remove temporary router-fixture composition in favor
of the real `create_app`; explicit memory test/seed mode now uses sealed objects/new outcomes.
No production optional receipts, legacy route, dual body, or old/new test-wire translator remains.
Keep disabled PostgreSQL default; only assigned isolated test instances enable journal here.
Delete the P07 tests/support/legacy.py constructor/ASGI override here, not merely its last import.
Convert test_api_postgres to the real journal runtime with private sealed-object fixtures, fresh
request IDs for distinct stale/permission submissions and expected-binding headers. Preserve all
role/search/audit/version assertions with the new acceptance audit explicitly accounted for.
Register recovery-identity in the real auth router; regenerate OpenAPI/web types for its exact
schema and binding/error additions. Update all protocol consumers/seed fixtures with identity,
never defaults that hide a missing binding. Production default still cannot write.

Update existing API tests to the changed public contract, or remove superseded assertions with
replacement-test references; no new algorithm work hidden in composition. Acceptance: real
application HTTP 200/202/409/404, current route registry, all consumers and seeds agree, only new
writer reaches storage, pending read semantics visible. Skills O/P/A/W/D. Commands GP, GC, GA,
GD; `uv run --offline --no-sync pytest tests/unit/api tests/unit/cli`.

### P28 — Remove obsolete ownership paths and tighten cutover schema

New `migrations/versions/0005_publication_cutover.py`, update final uploads tables/SQL names and
schema map. Refuse any old uploads/removals rows, drop the empty old relations, rename
upload_attempts to uploads, tighten final file/object/state constraints. Refuse nonempty downgrade.
Delete old metastore uploads memory/postgres/tables modules after their last legacy caller is
removed; move attemptmemory.py/attemptpostgres.py/attempttables.py to those canonical filenames,
retaining the new classes and no alias to the old port. Update imports and direct contract fixtures
to supply explicit objects. The migrations retain their historical table creation statements.
Remove old `Placer`/API `Placements` public-placement modules and exports, `measure_destination`,
backup-drop/undo/link-into-place APIs and their superseded tests; remove latest_placements/proves/
receipt-mode and old removal lease APIs/SQL/fields; old CommitRequest v1 parser/schema when last
caller gone. Keep applicable no-follow and errno cases by migrating them to new methods, not by
deleting matrix coverage. Remove CLI `_recover`, `_PLACED`, forget-on-timeout branch, split state
writers and obsolete copy-absence assertions. Delete no user state or old lake data. Naming suffix
recognition may remain read-only for drift reporting; it is not cleanup authority.

Own corresponding storage/uploads/files/CLI modules, obsolete test modules/cases and imports only;
reference branches and old plan untouched. Acceptance: no live/test composition reaches old writers;
no old wire alias; new 0004->0005 empty/refusal tests; final schema-map; all preserved contracts
covered. Skills O/P/A/D. Commands GP, GC, GA if snapshot changes; inspect repository content for
`latest_placements`, `measure_destination`, `ReceiptMode`, `drop_backup`, `_recover` and classify
every remaining occurrence (historical docs allowed, production call sites none).

### P29 — Mandatory full-application crash, duplicate and CLI recovery acceptance

New `tests/support/crash.py` owned-subprocess/manifest/barrier fixture; new
`tests/integration/test_publication_recovery.py`, `test_writer_ownership.py`,
`test_cli_state_recovery.py`. No production fault endpoint: inject at constructor I/O/subprocess
boundaries, or use owned test process wrappers. Actual runtime, PostgresStore/migrations and
PosixStorage, then fresh process/reopened DB/files after kill. Include every row of section 8,
two independent runtimes, reverse timing and late actor, 2-file replace/remove/sentinel, real CLI
commands with private XDG/spools. Normal and recovery must call the same production executor.
Controls prove failures are observable; do not assert private call sequences alone.
Run the P03/P22–P26 binding matrix through real CLI processes and two isolated PG instances/users,
including removal-only intent. Replace the endpoint behind the same URL after lost response;
assert neither status nor retransmit reaches the replacement namespace and spools/intent survive.
Restore original instance/principal and prove exact once-only recovery. Test explicit approved
same-instance endpoint move, config/env/global overrides, refresh races and wrong-binding 404
controls. Observe rows/HTTP effects and local files, not just a private verify() call count.
Capture credential-bearing requests at both isolated approved/unapproved destinations with valid
and expiring credentials, changed issuer/client/API file/env/global selections and discovery token
endpoint changes. Assert zero bearer/refresh/company-token delivery to an unapproved destination,
including identity/refresh/exchange and ordinary API calls. Test fresh-login approval, legacy
unbound token refusal, declined/failed acceptance and crash recovery of its local transaction.
Include the actual repository helper as a second root-lock participant. Kill its owned subprocess
around credential-only save, and race fresh identity switches against CLI refresh/config/push.
Prove old credential generations and all working intent survive failed/declined/uncommitted login,
and only a fully verified committed login selects new credentials. Do not inject token JSON to
bootstrap a supposedly successful auth test; use P27b's approved helper/device fixture.

**Future gates created here**, root:
`uv run --offline --no-sync pytest -m integration tests/integration/test_publication_recovery.py tests/integration/test_writer_ownership.py tests/integration/test_cli_state_recovery.py`.
Also GP and GC. Each crash is bounded, records PID/signal/exit/rows/bytes/identities/count/version/
audit/charges, and preserves failed evidence. No FORCE teardown. Minimum 25 GiB free, plus run's
explicit allocation/reserve preflight. Skills O/P/A/D. This is a release-blocking acceptance gate,
not a future production-hardening task; tiny attempt2 results cannot satisfy it.

### P30 — Read-only drift checks with identity-aware pending reporting

Own `pkg/fs/posix.py`, storage ports/adapters/check, CLI inventory/context/adm/status; existing
check/storage/status tests; rename owned `test_check_and_acl.py` to `test_check.py` after preserving
nonobsolete cases. Add `Stat.uid`, `Entry.errno` and unreadable shallow/recursive traversal reporting
without entering links/unreadable directories. Expected mode/owner/group data comes from API and
layout; file groups are never compared. Keep all old §6.4 findings, add clear pending-operation/
retained-private-work diagnostics without calling accepted partial visibility corruption.
`stale_part` can report old suffix artifacts but never delete them. Check/status use ShareReader only.
Acceptance: all modes/groups/unreadable/links/owner and absent service_user cases over both adapters;
check no write, full-reader identity requirement, no misleading success on unreadable tree. Skills
O/D. Commands GP, GD;
`uv run --offline --no-sync pytest tests/unit/storage/test_check.py tests/unit/cli/test_check.py tests/unit/cli/test_status.py`.

### P31 — Offline provisioning and maintenance ownership

Also own new `scripts/initialize_instance.py` and `tests/unit/test_initialize_instance.py` for
explicit offline server-side DB identity initialization through P11's adapter (never a CLI import
of metastore). Future command: `uv run --offline --no-sync python scripts/initialize_instance.py
--config FILE`; FILE is the explicit server configuration, not implicitly dev.env. With writer
stopped, it checks the configured UUID, inserts only an absent identity on a fresh paired DB,
accepts the same ID idempotently, and refuses another ID or existing publication history without
identity. No UUID generation, history reset, marker rewrite or force option. Test real PG races,
refusal/no data loss and configuration validation. Run GP/GC and explicit ruff check/format,
mypy and ty check on this script, as for dev-provision.py below. CLI offline provision consumes
the same operator-persisted UUID but performs no DB connection; installation runs initialization
then marker provisioning before runtime start. P16/P27 test setup calls the adapter directly,
so the later operator script is not a backward dependency.

The exact additional script checks (root) are:
`uv run --offline --no-sync ruff check scripts/initialize_instance.py`,
`uv run --offline --no-sync ruff format --check scripts/initialize_instance.py`,
`uv run --offline --no-sync mypy scripts/initialize_instance.py`, and
`uv run --offline --no-sync ty check scripts/initialize_instance.py`.

Own storage `provision.py`, CLI `commands/adm.py`, new `scripts/dev-provision.py`, organization/
provision tests and new CLI offline-provision tests. Add `ProvisionSpec(instance_id, api_url,
lake_path, organizations, uid, gid)` from explicit offline file/options, never a required health
request at first install. Reuse Provisioner for direct/script/dev Job; no duplicate layout writer.
The new command form is `huron adm provision-orgs --offline FILE [--emit-script] [--dry-run]`.
FILE contains those ProvisionSpec fields, with organizations as name/root declarations; names,
absolute root containment, UUID, URL and nonnegative numeric IDs are validated before any I/O.
Explicit --uid/--gid overrides, introduced in this slice, win; offline mode makes no API request. Online maintenance
mode keeps the workstation mount_prefix interpretation. The private output directory and local
source-state lock remain separate from authority to provision a live export.
Extend the one Storage port/adapters and `pkg/fs/posix.py` with provisioning-only
`set_owner(location: LakePath, uid: int, gid: int) -> bool`; no-follow chown with exact mapped
errors, shared contract cases, never called by the API writer. Prepare root/organization markers,
.tus-uploads and private object area with exact owner/modes;
root must already exist, mismatched marker refuses. Numeric U:G, shell quoting, file/parent sync,
no recursive chown or file mode rewrite. Catalog provisioning selects wrong group/setgid on
directories only; requires a fresh ID/version/group plan and drained writer maintenance ownership.
Emitted scripts are not safe to run against changing live rows; include verification instructions.
Acceptance: API down first install succeeds offline on owned temp lake; wrong instance/link refuses;
clear share group selects service gid; no file changes; unknown directories not discarded.
Skills O/D. Commands GP, GD; separately lint/type-check new script with
`uv run --offline --no-sync ruff check scripts/dev-provision.py`,
`uv run --offline --no-sync ruff format --check scripts/dev-provision.py`,
`uv run --offline --no-sync mypy scripts/dev-provision.py`, and
`uv run --offline --no-sync ty check scripts/dev-provision.py`.

### P32 — CLI repair/share groups and actionable hints

Own CLI commands create/change/adm/errors, CLI reference generated output, existing directory/
foundation tests and new `tests/unit/cli/test_repair.py`; web `src/lib/cli.ts` and its tests and
catalog CLI page only if adding the corresponding hint. Implement create catalog --share-group,
set catalog --share-group/--no-share-group, adm repair target --recursive/--org. Print changed,
warnings and failed path/reason/detail; keep read-only ShareReader. Busy/pending hints say status/
resume, not repeat create. SHARE_GROUP_PENDING points to maintenance provisioning; symlink to
storage administrator then repair; storage failures distinguish committed DB rows from repair.
Acceptance: every privilege/form/conflict/503, exact generated help commands; no lake writes,
no ACL reminder. Skills D and W if web touched. Commands GP, GD; GW and visual QA for web hints;
`uv run --offline --no-sync pytest tests/unit/cli/test_directories.py tests/unit/cli/test_repair.py tests/unit/cli/test_foundation.py`.

### P33 — Development stacks and real ingestion integration

Blocked until P05 offline assets remain available. Own new `deploy/openshift/nginx-uploads.conf.template`,
`docker-compose.uploads.yml`, existing app compose, `huron.dev.yaml`, Makefile uploads targets,
`scripts/{e2e.sh,demo-noaa.sh,dev-provision.py}` stack lifecycle/provision calls, `examples/noaa/load.sh`
only for the journal workflow (not its data transformation), Makefile `demo-noaa` resource wiring,
README development/NOAA/pre-release sections, `examples/noaa/README.md`, docs/operator.md pre-release
instructions, seed only where real bytes are created. Add exact fixture path
`tests/support/uploadstack.py`, `tests/support/noaa.py`, `tests/integration/test_uploads_tusd.py`
and `tests/integration/test_demo_noaa.py`; rewrite `test_cli_end_to_end.py` removing its skip.
P27b has already replaced every authentication producer/caller; reuse scripts/dev_login.py unchanged
unless an independently owned defect is found. Do not postpone its format/trust cutover here.

Pinned images/no pull, isolated ports/volumes/lake; no auto-stop of developer make up/app. API identity
initialization and offline provisioning precede start; no online provision-orgs races a live writer.
E2e performs provisioning/idempotent provisioning while stopped, then verifies mounts after startup.
Demo requires this already provisioned stack and performs read-only mount verification, not a new
live provisioning pass. Real seeded bytes traverse proxy+tusd+acceptance protocol.
Disable auth allow caching initially; OPTIONS remains unauthed, every other request authorizes
before body. No unconditional lock cleanup: P05 safe per-upload rule or proven drained maintenance.

**Resource/input contract for full commands below (new at this slice):** parent assigns an absent
unique `HURON_DEV_PROJECT`, private absolute `HURON_DEV_RUN_ROOT`, `HURON_API_IMAGE` tag built only
from cached inputs, `HURON_DEV_INSTANCE_ID`, loopback API/upload/issuer URLs and client ID from P27b,
and free `HURON_DEV_POSTGRES_PORT`/`HURON_DEV_GROUPS_PORT` (plus an explicit web port only if used).
The URL ports are assigned too; refuse collisions, never stop their owner. Compose parameterization
must use these exact values, no hard-coded project/ports or automatic shared-stack teardown.
Retain the app compose's shared network namespace: each service listens on the same assigned port
that is published on host loopback. Set Keycloak's advertised KC_HOSTNAME and --http-port to the
assigned issuer origin/port, and API company_issuer to the exact same realm URL; discovery must not
advertise a different default/internal URL. No issuer rewriting or validation bypass for tests.
Set `HURON_LAKE_SOURCE` and `HURON_LAKE_PATH` to the same owned absolute lake under the run root so
host CLI read-only checks see the actual bytes. Use fresh paired PG/lake plus P31 provisioning, not
existing test-bed data. Record exact containers/networks/volumes/image IDs/PIDs and limits in the
run's durable allocation receipt before creation. Integration fixtures get their own assigned
create-database PG endpoint via HURON_TEST_DATABASE_URL and distinct endpoints/output roots.

The operator supplies reviewed `HURON_DEV_APPROVAL_FILE` for these exact destinations and owned
`HURON_DEV_PASSWORD_FILE` for e2e, plus `HURON_NOAA_PASSWORD_FILE` for the demo admin. Files contain
test credentials only; their contents never appear in command receipts. Each fixture explicitly
approves its independently allocated tuple, never promotes discovered/configured values to trust.
Assign a validated **already cached** `HURON_NOAA_RAW` directory from examples/noaa/fetch.py with
manifest, exact hashes and data. Set NOAA_RAW to it and NOAA_REFRESH=0: no NOAA request/download.
Missing cache is BLOCKED, not permission to fetch or skip NOAA. Keep HOME/XDG roots private; e2e
uses run-root/e2e/{config,state}, while demo keeps run-root/cache/huron/demo-noaa/{config,state}
across both runs. Include sentinel state outside these roots and prove it is untouched.

Acceptance: real PG+API+nginx+tusd+CLI new/overwrite/remove/empty/resume, old delayed finish after
new success, final PATCH timeout, creator/auth-before-body, Forwarded/header inheritance, scope
revocation, all directory/repair/check workflows, and meaningful every-role CLI test. No Docker
skip added; missing infrastructure is BLOCKED. Authentication must use the approved helper then
real CLI whoami/read for every identity. Exercise first run, identity switch, valid/expiring cached
state, and failed/declined login preserving the previous state. No direct token injection even in
the integration Stack. Keep P27b's unapproved-endpoint credential-observation tests.

NOAA acceptance is both a full first load and an **offline idempotent rerun** on the same provisioned
stack and persistent isolated state. test_demo_noaa invokes the real make target/script/loader,
records collection IDs/versions, file count/hash, metadata, commit/audit counts and staged intent
before/after rerun. No new upload/commit/metadata change or version increment on unchanged raw input;
no unapproved credential delivery, no outside-state change and no NOAA network access. An auth
failure stops before the first authenticated read and keeps the previous successful state intact.
Small cached-fixture tests supplement, never replace, the assigned complete NOAA_RAW workflow.

Skills A/O/P/D. Commands GP, GC, GD, GDEV plus these exact root commands after prerequisites:

```sh
docker run --rm --pull=never tusproject/tusd:v2.10.1 -help
docker run --rm --pull=never --entrypoint sh tusproject/tusd:v2.10.1 -c true
docker compose -f docker-compose.app.yml config --quiet
docker compose -f docker-compose.uploads.yml config --quiet
bash -n scripts/e2e.sh scripts/demo-noaa.sh examples/noaa/load.sh
uv run --offline --no-sync pytest -m integration tests/integration/test_uploads_tusd.py tests/integration/test_cli_end_to_end.py tests/integration/test_demo_noaa.py
UV_OFFLINE=1 UV_NO_SYNC=1 bash scripts/e2e.sh --keep-stack --approval-file "$HURON_DEV_APPROVAL_FILE" --password-file "$HURON_DEV_PASSWORD_FILE"
UV_OFFLINE=1 UV_NO_SYNC=1 XDG_CACHE_HOME="$HURON_DEV_RUN_ROOT/cache" HURON_DEV_PASSWORD_FILE="$HURON_NOAA_PASSWORD_FILE" NOAA_RAW="$HURON_NOAA_RAW" NOAA_REFRESH=0 make demo-noaa
UV_OFFLINE=1 UV_NO_SYNC=1 XDG_CACHE_HOME="$HURON_DEV_RUN_ROOT/cache" HURON_DEV_PASSWORD_FILE="$HURON_NOAA_PASSWORD_FILE" NOAA_RAW="$HURON_NOAA_RAW" NOAA_REFRESH=0 make demo-noaa
uv run --offline --no-sync python scripts/check_links.py README.md examples/noaa/README.md docs/operator.md
```

`--keep-stack` is a future e2e option owned here, used so both following demo commands use that same
isolated backend. Preserve all failed runs; success cleanup also needs explicit ownership/process
reconciliation. No unconditional trap that drops volumes or hides a failed check with `|| true`.
The fixture runs `nginx -t` inside its exact assigned pinned proxy container on rendered config and
records container/config/exit. Full script outputs plus before/after observable inventories are
required; syntax checks, the helper alone and a successful compose render are not workflow evidence.
If web seed/harness code changes, add GW and its prescribed QA where visible. Re-run P31's explicit
four dev-provision.py static checks when that script changes; make gate does not cover it.

### P34 — Single-writer kustomize and owned local deployment

Own openshift deployment/uploads/route/kustomization/huron config; new deploy/local overlay,
new scripts/k8s-local.sh and Makefile local targets, Containerfile script inclusion, manifest tests,
deploy README. Exactly one writable API replica/process and one tusd, Recreate plus fail-closed
handover; do not encode “Recreate is a fence”. Read-only replicas, if provided, cannot bootstrap/
recover/GC. Root provisioning Job precedes writer; fixed U/G, SCC/range, writable export nodes,
read-only rootfs/capability drops, tmp dirs, lake claim. API readiness 3/5/1 probes; liveness no NFS.
Proxy 1080 only, tusd loopback1081, streaming and hook timeout alignment. No unconditional lock sweep
or NetworkPolicy introduced to pretend that pod/port policy selects an HTTP hook path.

**Historical smoke replacement:** M11.11:5220–5226's raw token copy into pod XDG state is prohibited.
Own new `deploy/local/cli-smoke.yaml` for local-only read-only helper/approval ConfigMap mounts and
private CLI emptyDir at `/var/lib/huron-cli`; include it in local kustomization and manifest tests.
scripts/k8s-local.sh creates the ConfigMap from repository `scripts/dev_login.py` and the operator's
separately reviewed pod approval file, outside kustomize generation. Do not package the password
adapter in the production wheel or openshift/Helm resources; Containerfile's provisioning-script
inclusion remains as specified, not a production password-login entry point.

Host smoke fresh-authenticates with P27b's helper in owned host XDG roots, approving the host TLS API/
upload bases and port-forwarded issuer. Verify TLS with assigned SSL_CERT_FILE/CURL_CA_BUNDLE; no
insecure switch. After push/new/overwrite/empty/remove, run the same repository helper **as service
UID U inside the assigned API pod**, from `/opt/huron-dev/dev_login.py`. It uses a different owned
0600 approval file in its private emptyDir (copied by U from the nonsecret read-only ConfigMap),
the pod API/issuer/client tuple and explicit pod XDG config/state. Pod uploads_endpoint is null:
this session only reads/checks, so omit --uploads-url and set its CLI uploads selection to None.
Use literal loopback API HTTP only with explicit development approval. Keycloak listens at the
assigned K8S_LOCAL_IDP_FORWARD_PORT inside the API pod and advertises that same loopback origin;
the owned host port-forward maps that port to itself. Both sessions and the API company_issuer
therefore use the same exact issuer/discovery URL, without a host/pod issuer substitution.
Pass the password over
`kubectl exec -i` stdin from the owned file, not argv, env contents, a Secret dump or a shell command
containing it. Configure pod CLI selections separately, then real whoami and `huron adm check --hash`
as U at the pod lake mount. Check must print no findings. The host token is never forwarded to the
pod's different base; no process writes or copies raw token JSON. Each login establishes its own
provenance through shared FreshLogin/identity/atomic-state collaborators, with the same instance
and expected test actor checked against the allocation receipt. Host pending work stays host-bound.

Local overlay hostPath proves Linux only, not ONTAP. Exact context/namespace/PV/ports/node directory
must be explicitly assigned; existing `ocp-test` is not implicit authority. New k8s-local script
refuses context/resource collision, no default purge, preserves failed evidence/data. Acceptance:
render, private local smoke upload/overwrite/empty/remove/check, restart/handover refusal when old
owner uncertain, graceful drain, safe teardown only of assigned resources. Add exact
`tests/unit/test_deploy_manifests.py` local mount/production-absence assertions and
`tests/integration/test_local_smoke.py` public smoke/auth tests; the latter uses only an explicitly
assigned local deployment, never creates or attaches to the default shared context. Test declined/
changed pod approval before credentials, a failed second login preserving old state, and a smoke
rerun without copying credentials. No missing-cluster skip; missing assignment is BLOCKED.

Prerequisites: exported `K8S_LOCAL_CONTEXT`, `K8S_LOCAL_NAMESPACE`, `K8S_LOCAL_PV`,
`K8S_LOCAL_NODE_DIRECTORY`, `K8S_LOCAL_INGRESS_PORT`, `K8S_LOCAL_IDP_FORWARD_PORT`,
`K8S_LOCAL_RUN_ROOT`, `K8S_LOCAL_HOST_APPROVAL_FILE`, `K8S_LOCAL_POD_APPROVAL_FILE`, and
`HURON_DEV_PASSWORD_FILE`, with all exact resource IDs/URLs/client/instance/CA/image inputs recorded
by the parent. The script validates these rather than assuming ocp-test/8081/18443 or using wildcards.
Use cached images only, no installs/pulls. Skills A/D. Exact root commands (future targets/tests):

```sh
UV_OFFLINE=1 UV_NO_SYNC=1 make gate
kubectl kustomize deploy/openshift
kubectl kustomize deploy/local
bash -n scripts/k8s-local.sh
UV_OFFLINE=1 UV_NO_SYNC=1 make k8s-local
UV_OFFLINE=1 UV_NO_SYNC=1 make k8s-local-smoke
uv run --offline --no-sync pytest -m integration tests/integration/test_local_smoke.py
```

Also GC, GD and GDEV. After successful evidence and separate parent authorization for cleanup,
`UV_OFFLINE=1 UV_NO_SYNC=1 make k8s-local-down` removes only recorded resources and preserves the
node data directory; never run it automatically on failure. Render/syntax tests cannot replace
the full host/pod auth and byte/check/restart smoke. Deployment credentials never enter receipts.
Keep “Helm: not yet delivered”.

### P35 — Quantitative workload and operational acceptance harness

New `scripts/qualify_ingest.py`, `tests/support/workload.py`, `tests/unit/test_qualify_ingest.py`,
Makefile `test-acceptance` target; `applications/api/metrics.py` and `tests/unit/api/test_metrics.py`,
plus explicit call sites in
admission/seal/publication/cleanup/runtime. Scope is instrumentation/harness, not protocol repair.
`RuntimeMetrics.record(event: OperationMetric) -> None` and `snapshot() -> MetricsSnapshot` are
injected per runtime, not global. Emit a bounded `runtime.metrics` structured snapshot every 10 s
with controlled clock tests; the acceptance runner captures it. No new metrics dependency or
unauthenticated diagnostic endpoint is implied.
Counters: queued/active, rejected reason, reserved/live/retained bytes/inodes/counts, oldest pending/
blocked age, cleanup backlog, free reserves, DB/lake/readiness/cache age, drain and ownership refusal.
Bound labels to scopes/reasons; request/upload/operation IDs in structured logs, no token labels.

Runner input `HURON_ACCEPTANCE_MANIFEST` names an ignored owned manifest with run directory,
instance ID, private endpoints/resource IDs, image/version hashes, limits, workload selection and
absolute allocation cap. Credentials via environment only. Refuse unknown resources/nonempty
output, preflight >=25 GiB free **and** matrix's calculated capacity+reserve, deadlines and inode
budget. Preserve failures. **New future gate:** `UV_OFFLINE=1 UV_NO_SYNC=1 make test-acceptance`;
it runs `uv run --offline --no-sync python scripts/qualify_ingest.py --manifest "$HURON_ACCEPTANCE_MANIFEST"`.
Run all section 9 rows, not only fast cases. Record latency percentiles/throughput/RSS/FD/thread/
queue counts/storage and DB totals/recovery time; numeric limits remain candidates until measured.
Skills A/O/P/D. Commands GP, GC, new acceptance gate;
`uv run --offline --no-sync ruff check scripts/qualify_ingest.py`,
`uv run --offline --no-sync ruff format --check scripts/qualify_ingest.py`,
`uv run --offline --no-sync mypy scripts/qualify_ingest.py`, and
`uv run --offline --no-sync ty check scripts/qualify_ingest.py`. No zero-exit on missing scenarios.

### P36 — Deliver exact M11.12 documentation scope

Own docs/operator.md, user-guide.md, architecture.md, api-errors.md, concepts/{raw-ingest,
how-huron-works,access-and-roles,metadata-and-schemas}.md, docs/web-design.md affected dated
amendment only, docs/adr/0008-uploads-through-tusd.md supersession note preserving history,
README.md, deploy/README.md, CONTEXT.md affected upload/commit/push-lock terms. AGENTS.md authority
pointer only in a separately reconciled I-skill assignment; old IMPLEMENTATION_PLAN.md never edited.
No vague “other docs”: baseline search names any additional obsolete page for explicit ownership
revision before editing. This is documentation, **not** performance/acceptance implementation.
P27b already owns the credential/login/state and dev helper instructions in these shared documents;
P33 owns the full development/NOAA workflow instructions and P34 the deployment smoke. P36 checks
them for consistency but cannot be the first owner of those earlier cutover changes. The NOAA
example and Makefile demo target remain covered by P27b/P33, not silently outside the docs scope.

Carry **all** obligations: export ro/rw rules; fixed UID/GID/service/share group/SCC/pinned range;
API/upload mounts/ownership; safe tusd locks; group provisioning/supplementalGroups (~14 within
AUTH_SYS slots) and name resolution; offline install order; LakePath/no links/failure recovery;
all drift findings and who can run complete check; identity cleanup; AUTH_SYS root-client limit;
hard-NFS whole readiness/drain/uncertain writer/fence outage; setgid/security-style measurement
procedure; actual local-cluster commands/context/purge limits; “Helm: not yet delivered” until P38;
no replacement local_lock advice, flock-based tusd check, or path-selecting NetworkPolicy claim;
push/resume/401/403/final-PATCH500/502/504/repair failure fields/share-group options; server lake_path
versus client mount_prefix. Add accepted/pending mixed visibility, exact outcomes, spools/source
stability limits, quotas/alerts/backup and restore limitations. Remove obsolete ACL/CLI-lake-write
instructions, apply-acl broken anchors, init-root/acl_backend/OUTSIDE_LAKE claims outside historical
ADRs. `RepairFailureOut` stays sole failure-contract source, docs link instead of duplicating cases.
Skills D (availability is a blocker for formal qualification); W for web-design meaning, no Svelte
edit implied. Commands G0, GD and GP as the retained M11.12 task gate; manually inspect obsolete
terms/anchors and “Setgid measurement (pending)”/Helm status. Site builds cannot prove runtime claims.

### P37 — External ONTAP, fencing and site workload qualification

**Blocked on storage/cluster/site owners and owned infrastructure.** This is a maximum verification
assignment with any service/config mutations separately dispatched exclusive code or performed by
the authorized operator. No worker treats a document as authority to modify a shared export.
Evidence destination: production run manifests/logs in assigned ignored output; a separate planning
writer records new durable `design/m11-production-qualification.md` after terminal review. The
reviewer does not edit that document or product files.
Inspect exact NFS/ONTAP version/security style/export/snapshot settings. As root create private t
owner U/group S/mode2750 where U not in S; as U/umask022 run the old specified mkdir/touch/stat;
expect directory2750 U:S, file644 U:S; root chgrp/chmod verifies2750 S. Record actual date/stat
lines/security style, don't overwrite old plan history. Test AUTH_SYS supplemental-group behavior,
read-only client enforcement, directory/data sync and cache visibility, hard-mount outage with
in-flight operations, externally verified fence, old-node resume, backup/restore with DB/object
ownership reconciliation. Power-loss evidence is storage-owner evidence, not inferred local fsync.

Run P29/P33/P35 complete gates on representative owned infrastructure with approved production
sizes/budgets and 50 identities. Accept zero correctness/accounting failures, bounded admission,
measured readiness/drain/recovery within agreed objectives. If no enforceable fence exists, record
manual proven-quiescence replacement and write-outage policy; no unattended failover. If neither
can be demonstrated, production remains blocked. Skills O/P/A/D. No production-qualified claim
from local hostPath or model success. P38 waits for setgid/security-style result, as M11.13 required.

### P38 — Helm and production values

Blocked on P37 plus offline Helm v3 executable/image and pinned runtime assets. Own chart
templates/deployment/uploads/configmap/route/ingress/NOTES, values/schema/example-values, byte-identical
nginx template copy, nginx equality/manifest tests, operator/deploy documentation status. Validate
finite quotas, one writable process/replica, service UID/GID/group/claim/path, ownership/fence/runbook
references, hook maximum55m, ingress read3600/send3600 streaming defaults, API route300s, probe3/5/1.
No broad init cleanup, no two-writer default. Preserve web.mountPrefix for client paths only.
Setgid failure stops design, never mode weakening. Update pending measurement/Helm claims only
after actual qualification. Skills A/D/P. Commands GP, GD, `kubectl kustomize deploy/openshift`,
`helm lint --strict deploy/helm/huron -f deploy/helm/huron/ci/example-values.yaml`,
`helm template huron deploy/helm/huron -f deploy/helm/huron/ci/example-values.yaml`, and
`cmp deploy/openshift/nginx-uploads.conf.template deploy/helm/huron/files/nginx-uploads.conf.template`.
If only cached alpine/helm:3.16.4 is approved, run those exact Helm arguments through
`docker run --rm --pull=never -v "$PWD:/w" -w /w alpine/helm:3.16.4`; absence is BLOCKED.

### P39 — Cutover rehearsal and final complete qualification

Maximum verification/review, `*:write`, parent-owned isolated target and explicit enablement
authorization; independent reviewer edits no product source. Preconditions: every prior phase
independent PASS, no pending plan findings, all offline/ONTAP/workload/skills issues resolved or
formally reconciled by their owner without weakening required checks. Recapture tree ownership.
Rehearse no mixed writers: close admission, drain, prove old API/tusd access quiescent/fenced,
backup inventory, additive migration on the selected fresh pair, offline marker/provision check,
new epoch, seal/publication recovery/accounting audit, then enable journal writes. Rehearse refusal
with legacy data or uncertain old owner and rollback-to-read-only **without data downgrade**.
Existing-lake reuse requires its separately accepted import/export decision; no deletion by this plan.

Run G0, GP, GC, GA snapshot check (no unauthorized regeneration), GW, GD, GDEV, full P29 crash suites,
P33 real integration/e2e AND both cached-NOAA demo commands/idempotence assertions, P35 acceptance
matrix, both deployment renders/Helm lint/equality and
owned deployment smoke/upgrade/restart tests. All commands must succeed; no ingestion skip, exit5,
suppressed failure or missing infrastructure. Inspect every changed contract and retained invariant,
test current gates independently rather than copy writer receipts. Output final receipt with file/
deletion list, exact commands/versions/counts/coverage, actual deployment limits and evidence,
remaining accepted visibility/AUTH_SYS/single-writer outage limits. PASS authorizes only the agreed
production qualification, not commit/push/merge. FAIL/BLOCKED prevents enablement and preserves data.

## 7. Complete traceability

### All 19 M11 tasks

“Complete” in the history column is the old plan's recorded state, not a new verdict.
Each forward row is covered by the serial gate above; no task is silently dropped.

| Old task | Historical state | Forward contract and disposition |
| --- | --- | --- |
| M11.1 | Complete | P08–P13/P27/P28 replace receipt/latest-placement/outcome semantics; retain transactional accounting, race/error discipline and shared memory/PG contracts. S1–S3/S6/S7. |
| M11.2 | Complete | P09/P10/P11/P28 additive schema and inode diagnostic conversion; preserve share groups and 0003. S10. |
| M11.3 | Complete | P07/P16/P34 bound admission/readiness/drain/ownership and preserve two pools; health/settings snapshots in P27. S5/S8. |
| M11.4 | Complete | P05/P12/P17/P27/P33 hooks/auth/read routes become private seals, exact eligibility and real proxy proof. S3/S7. |
| M11.5a | Complete | P14–P18 replace backup lifetime/replay with retained objects; four large/eight short worker hypothesis kept for qualification. Reference branch retained. S3. |
| M11.7 | Complete | P22–P28 exact local state/spool/attempt/outcome and approved credential protocol; P27b switches CLI plus every external credential producer/caller, P33 restores real CLI integration. No lake-copy path restored. S2/S7/S9/S12. |
| M11.8a | Complete | P23/P27/P32 retain API-only CLI directory verbs/read-only mount boundary. No ACL or CLI lake writes return. |
| M11.9a | Complete | P28/P30/P36 keep ACL removals and ShareReader; remove remaining obsolete prose, not new compatibility. |
| M11.5b | Complete | P08/P13/P15/P27 preserve API path vs LakePath shapes and configured-root validation; object identities replace public-name receipt assumptions. |
| M11.5c | Complete | P01/P14/P15/P30/P31 extend the one port, shared matrix and no-follow traversal. No containment escape claim or device-check redesign. |
| M11.5d | Complete | P19/P20/P21 metadata/directory/delete ordering and durable cleanup; preserve DB-first ordinary directory failure semantics. S11. |
| M11.5e | In progress, dirty | P00/P01 new independent acceptance cycle retains full fake/error matrix/RepairFailureOut; P19 separately closes stale group/metadata ordering. No historical green promotion. |
| M11.6 | Pending | P13/P15/P18/P20/P21 deliver public removes before success, recovery and identity-bound cleanup. Old Unlinker/Sweeper/lease election not implemented as unsafe compatibility. S4–S7. |
| M11.8 | Pending | P32 repair/share-group commands and hints, generated CLI reference and web hints when touched; read-only CLI. |
| M11.9 | Pending | P30 drift/unreadable/uid/modes/groups; P31 offline root/org/catalog provisioning and maintenance rules. |
| M11.10 | Pending | P05 real handoff prerequisite; P27b development-auth caller cutover; P33 real nginx/tusd stacks, every-role CLI integration/skip removal, full e2e and cached NOAA offline idempotent rerun. |
| M11.11 | Pending | P34 single-writer kustomize/local overlay/smoke, separate fresh host/pod authentication without raw token injection, mount/security/probe/docs; uncertain old writer blocks restart. |
| M11.12 | Pending | P36 exact user/operator/design documentation scope, not mislabeled as performance work. P38 updates Helm/measurement status only after evidence. |
| M11.13 | Pending | P37 external setgid/security-style gate; P38 Helm/production values; P39 complete qualification. No local-filesystem substitute. |

### Findings to observable acceptance

| Finding | Required result | Phases/gate |
| --- | --- | --- |
| F1 rejected/abandoned replacement loses committed bytes | All pre-acceptance refusal/abandonment leaves public old bytes; accepted crash retains both | P02 control, P13/P17/P18, P29 real crash, P33 real tus |
| F2 receipt order disagrees with FS order | Explicit IDs, one fenced owner, reverse timing never picks latest timestamp | P02/P04 controls, P11–P13/P16/P18, P29 duplicate runtimes |
| F3 same-size replay/marker bypass/backup overwrite | Missing seal proof cannot become ready; foreign target blocked; retained old object never overwritten | P14/P15/P17/P29 |
| F4 old timed-out upload completes late | Timeout retains identity; cancellation/supersession durable; late completion stays private/ineligible | P05/P12/P17/P25/P29/P33 |
| F5 removal-only lost answer falsely succeeds | Exact instance/principal-bound UUID outcome; unrelated version or namespace never clears/replays intent | P03/P09/P11/P13/P16/P22–P27/P29/P33 |
| F6 expired/consumed upload reuse | Explicit eligibility/expiry/consuming operation; reupload expired from same spool | P12/P25/P26/P29/P33 |
| F7 local state/source races | Every mutation, including external dev login, locked before context/state; atomic credentials/intent/base/stage, independent spool and bounded source policy | P03/P22–P27/P29; real dev callers P33/P34 |
| O1/O2 unbounded executor queues/capacity | Active and waiting counts plus byte/inode/scoped quota rejection before effects | P04/P10/P12/P16/P21/P35 |
| O3/O4 readiness/probe drift | 2 s whole deadline, one probe, 3 s deployment timeout, stale success invalidation | P04/P16/P34/P38 |
| O5/O6/O7 hard-NFS/shutdown/startup ownership | Stop admission; tracked drain; reverse startup disposal; no new owner while uncertain | P04/P16/P29/P37/P39 |
| O8 provisioning cycle | API-down offline provisioning before writer startup | P31/P33/P34/P39 |
| O9 old tusd overlap/lock deletion | No automatic cleanup or takeover while old accessor uncertain | P05/P16/P21/P34/P37 |
| O10 public removal absent | Remove durable before success, foreign target blocks | P13/P15/P18/P29/P33 |
| O11 recursive sweep/mtime | True shallow inventory and identity/quiescence GC, unknown artifacts kept | P14/P21/P29/P33 |
| O12 durability order | File/manifest and each mkdir/rmdir/link/rename/unlink parent sync before ack | P02/P14/P15/P17/P18/P29/P37 |
| O13/O14 stale metadata/group repair | Same guards plus current resource-ID/version/group rereads, no stale write last | P19/P20/P29 |
| O15 workload/metrics absent | Complete candidate/representative matrix and bounded-label metrics | P35/P37/P39 |
| O16 obsolete production docs | All precise M11.12 obligations delivered with truthful status | P36/P38 |

## 8. Mandatory application interruption and concurrency matrix

P02 settles the unresolved design questions. P29 reruns **all** applicable rows against actual
production collaborators/PG/filesystem and whole CLI processes; P33 adds real tusd transport.
P37 adds actual NFS/outage/fencing evidence. A fake/model/control passing does not replace these.
At each physical/durable boundary inject failure **before and after**, kill only the owned test
process, prove it exited, then restart/reopen. Record rows, hashes, object IDs, pending, charges,
version/count/audit and sentinel; run normal/recovery parity. All waits need deadlines.

| Boundary/scenario | Observable required invariant |
| --- | --- |
| Begin committed; source absent/partial | No public change; same attempt receiving/expired, charges retained until owned cleanup |
| Source changed or late writable FD | Independent seal cannot be mutated later; changed copy hash/length refuses ready |
| Object row/temp created; copy partial; file fsync fails | Not ready/public; no second uncharged copy; recover or clean after quiescence |
| Private directory mkdir, before/after parent sync | Retry proves ownership/attributes, syncs before descendant/ready; foreign substitution blocks |
| Data synced; manifest absent/partial; manifest/file/parent sync fails | No ready; DB/object/attempt/hash proof mandatory, no destination fallback |
| Manifest durable, ready commit/response lost | Revalidate full proof and exact eligibility; cancel/expiry wins; ready returned exactly |
| Concurrent cancel/supersede/expire/finish | One eligible outcome, no resurrection; cleanup conserves physical claims |
| Request before receipt, receipt rejected, acceptance committed | Same ID yields absent/saved refusal/same accepted operation respectively; never infer from version |
| Two same UUID submissions, changed payload, actor mismatch | One result, conflict on changed digest, no cross-actor information leak |
| Two independent runtimes; reversed receipt/physical timing | Old race reproduced as control; journal owner excludes second writer; times not authority |
| Acceptance committed, no physical step | Pending and all old/new references/charges survive; recovery rolls forward |
| Temp link, parent sync, rename, parent sync, ack | All boundaries resume against exact retained identities; old bytes retained; foreign inode blocks |
| Unlink, parent sync, ack | Requested remove only succeeds once durable; absent retry backed by journal, KEPT not success |
| Planned rmdir, parent sync; file↔tree/case-only | Parent sync repeated on already absent; unknown child/identity blocks; no unrecorded child removed |
| Partial multi-entry operation | Pending remains; accepted mixed NFS visibility documented; final rows unchanged until all done |
| All steps done, finalize transaction fails/commits, response lost | One commit/audit/version/count and exact same request outcome after restart |
| GC marked, unlink/sync, accounting release lost | No new reference after gc_pending; release once; stale cleanup never touches reused public path |
| Delete/repair/group/schema/metadata vs pending | Busy before effects when required; guarded latest state wins otherwise; tombstones prevent reuse |
| Ownership connection lost, old work resumes | No newly authorized step/finalize; replacement refuses until proof/fence; delayed syscall not denied by fiction |
| Queue/DB/key/probe stall, shutdown and startup faults | Finite waiters/charges, deadline/readiness correct, resources stay until drain or uncertainty |
| CLI spool/temp/fsync/replace/dir-sync; all command races | Valid old/new atomic generation, no lost intent/source, stable lock, charged unreferenced spools retained |
| CLI before POST, after apply/lost answer, success local-save failure | Same ID/body resumes; unrelated update cannot clear stage; base+stage finalized atomically |
| CLI actor switch, URL overrides, same-URL new instance, refresh race; removal-only/empty work | Verify saved binding before recovery; mismatch preserves intent/spools, never replays on another namespace's 404; explicit same-binding endpoint move changes endpoints only |
| Repository helper vs CLI fresh login/refresh/config/push; valid/expiring or legacy credentials; changed/declined destination approval | Zero password/company/bearer/refresh delivery at unapproved endpoints; stable shared root lock; failed/uncommitted login retains old approval/credentials/intent; committed fresh login changes credential state only, endpoint acceptance stays one combined transaction |
| Late tusd PATCH/hook after timeout/new success | Cannot change public bytes or resurrect superseded attempt; real FD/request closure accounting |
| Symlink at root/marker/source/object/temp/public/ancestor | Exact error path, no follow/delete of link, outside-tree snapshot unchanged |

Also test permissions/authorization boundaries, empty inputs, exact limits, malformed status,
wrong instance marker, loss of a retained object, ENOSPC/EDQUOT/EIO and inode exhaustion.
Missing/corrupt retained content remains blocked for operator recovery, never fake rejection
after partial publication. Local process death is not power-loss/ONTAP persistence evidence.

## 9. Workload qualification matrix for approximately 50 identities

Everything numerical below is a **candidate qualification workload**, not a measured production
capacity or throughput promise. P35 implements it; site owner confirms/extends Lmax, aggregate,
concurrency and outage objectives before P37. Keep configured thresholds and every row; a missing
large-file resource blocks that row rather than reducing the file size and claiming success.

| Row | Inputs and load | Required measurement/acceptance |
| --- | --- | --- |
| W1 identity/authority | 50 distinct scientist identities across >=5 catalogs and >=2 organizations; reader, contributor and admin controls | No cross-owner uploads/status leak; correct scoped quotas and grants, no token in logs |
| W2 normal parallel | 8 simultaneous 64 MiB transfers from different identities; repeat >=20 waves; browse/status concurrently | Zero lost/changed bytes or false success; queues stay within 4+8 large and 7+16 short plus one probe hypothesis; report p50/p95/p99 timings |
| W3 burst/admission | 50 simultaneous creation attempts, then 100 simultaneous attempts; one hot collection and distinct collections | Expected busy/429 refusals before bytes, finite waiters; no unbounded executor backlog; recovery retains priority and reservation |
| W4 small files | 0/1/4,096 bytes and 1 MiB; one 10,000-entry commit, 10,001 refused; 50 clients each submitting small batches | Entry/count/inode budgets enforced, zero-byte charges, bounded request parsing <=16 MiB; no per-entry N+1 unbounded memory growth |
| W5 chunk edges | 64 MiB−1, exactly 64 MiB, +1; interrupted HEAD resume at beginning/middle/end; zero-byte creation response loss | Exact SHA-256/size/offset, no re-created timeout attempt, spool stable |
| W6 large/scientific | 1 GiB and 10 GiB, then site Lmax (candidate 100 GiB); 1 and 8 concurrent where approved budget permits | Streamed memory independent of file size apart from bounded 64 MiB client chunk; measure full source copy+verification duration and reserve 2S; no silent size reduction |
| W7 tree bounds | 206-byte user component/207 refused, raw LakePath255/256 contract, 1,024-byte rel path, nested branches, case-fold collisions, case-only replace, file↔subtree; 10,000 total entries | Same validation/bytes/outcomes across normal and recovery; temp names never extend user basename beyond limit |
| W8 retained capacity | Existing live A plus replacement B, delayed GC, cancelled/expired/sealing sources, accepted blocked operation | Physical/global/scoped reservations reconcile to actual owned bytes/inodes; old data never evicted; admission stops at configured high-water |
| W9 exhaustion | Dedicated owned limited filesystem or approved fault boundary: bytes full, inodes full, EDQUOT, directory-sync EIO | No public unaccepted effects, no negative/double-released counters, no ready/ack/success on failed durability; explicit recovery/operator outcome |
| W10 runtime pressure | Large pool full plus short queue full plus exhausted DB pool/key read; one hard-NFS probe stalled | Readiness whole budget2 s plus measured scheduler tolerance; cache invalidated; at most one probe; event loop/browse behavior recorded |
| W11 crash/recovery load | P29 matrix under W2/W4, delayed old completion, duplicate runtime, shutdown/restart, held-FD cleanup | Same bytes/identities/final outcome once; bounded recovery queue/age, conservative charges; no unsafe takeover |
| W12 representative export | W1–W11 on approved ONTAP settings with site Lmax/aggregate and snapshot load | Actual setgid/security/AUTH_SYS/cache/sync/outage/fence evidence; production values cannot exceed qualified envelope |

Capacity preflight is not “25 GiB is enough”: require at least
`live_bytes + retained_old_bytes + 2 * admitted_source_bytes + charged_retry_copies +
manifest/directory/temp_allowance + free_reserve`, and the corresponding counted inodes, on the
owned filesystem. ONTAP snapshots/other export users need an additional operator allowance.
For eight simultaneous 100 GiB replacements, source+new-copy reservation alone is 1,600 GiB;
the local prototype machine's space cannot qualify that row. Lower locally scaled tests remain
separate evidence. Select finite scope budgets, not zero/unlimited.

Candidate operational objectives, owner confirmation required: ordinary acceptance/status p95<1 s
when not deliberately saturated; whole readiness <=2 s with a recorded <=0.5 s scheduling tolerance;
stop admitting within one observed ownership-failure cycle; small-work shutdown drain<=30 s;
configured long drain<=hook budget+60 s before uncertain/maintenance outcome. Largest-file sealing
should complete in <=80% of configured hook budget on qualified hardware, else reduce the approved
Lmax/admission or revise the handoff design with review. No automatic fence follows any timer.
Recovery time/outage SLO and backup RPO/RTO are site inputs, not invented measured guarantees.

Record per row: exact command/config/versions/resource IDs, attempt counts, accepted/rejected
counts, content inventory, RSS/FD/thread maxima, queue maxima, bytes/inodes/PG counters, p50/p95/p99
latency and throughput, oldest pending/cleanup age, error logs, elapsed time and cleanup state.
Any missing measurement is unqualified, not zero. Fifty identities alone says nothing about capacity.

## 10. Blockers, execution ledger and handoff

| Blocker | Owner and next action | Blocks |
| --- | --- | --- |
| R3-1 planning defect resolved; implementation still pending | Independent maximum review accepted the reconciliation (§14). The named future slice owners must implement and qualify the producer/caller cutover; §12 and FAIL/FAIL/FAIL remain historical evidence | No remaining plan-acceptance blocker from R3-1; no implemented credential cutover claimed |
| Current dirty baseline unmeasured/M11.5e unaccepted | P00 independent gates, explicit repair-hunk ownership, P01 fix+new review cycle | Adoption of dirty repair, downstream port changes |
| Directory proof/process crash/duplicate runtime gaps | P02 actual-adapter controls/candidate process-crash protocol; P29 production rerun | P06 protocol freeze, production durability claims |
| CLI lock/spool/timeout gaps | P03 bounded whole-command candidate experiment; P22–P26/P29 real implementation acceptance | P06, CLI protocol code readiness |
| Runtime admission/uncertain writer gaps | P04 bounded experiments; P16/P29 runtime tests | P06, runtime code readiness |
| tusd/nginx absent offline | Asset owner supplies approved pinned images; P05 proves actual handoff and safe cleanup | P05/P06/P33 and all ingestion qualification |
| Cached NOAA data and isolated workflow/deployment inputs not assigned | Development/site owner supplies validated NOAA_RAW cache, reviewed destination approvals, secret-file inputs and fresh owned stack/cluster resource identities; no downloads or service assignment in this planning turn | P33 full demo/idempotence and P34 smoke, not current prose checks |
| Helm absent offline | Asset owner supplies Helm v3 or approved cached image, no downloads by workers | P38/P39 |
| Actual ONTAP setgid/security style/durability/AUTH_SYS/fence unknown | Storage and cluster operators assign an isolated export/client test, produce signed-off evidence and usable handover runbook | P37/P38/production enablement |
| Workload maximums/budgets/outage objectives unknown | Site owner confirms Lmax, total bytes/inodes, simultaneous attempts and RPO/RTO; P35/P37 measure | Writable production configuration/qualification |
| Skill activation and workflow drift | §15 records the separately authorized tooling correction. Writing-for-agents is available. ASD activation/load and independent Maximum review remain post-restart. Other recorded gate drift remains separately owned | Formal affected-language qualification and tooling acceptance. No direct-read permission bypass |
| Existing test-bed data/import decision | Data owner selects fresh paired isolated deployment or separately reviewed export/re-ingest/import with verification | Any reuse; never authorize discard implicitly |
| Retained probe resources | Parent owns eventual reconciliation/cleanup; current stopped state is recorded, not a future ownership proof | Reuse/restart/deletion, not prose synthesis |

Initial synthesis ledger (2026-11-09): implementation/planning attempt1, configured maximum,
`openai/gpt-6-astra`, dispatch `f33fd29c-853a-4abd-8cb6-41d03ddacda7`, child
`ses_e416d6114ffeSnhTOmiw4wDVwF`, parent `ses_e41c1bd18ffer6qYUucJS8u5Gw`, `*:write`.
Configured profile is recorded; provider effort acceptance is **not-proven**, not observed Max.
Only this plan, new prototype evidence and two owned design status/cross-links changed. No service,
code/test/config/old-plan/tooling/Git-history change or prototype promotion. No nested agent.

| Slice | Baseline | Writer | Independent review1/2/3 | Verdict/readiness |
| --- | --- | --- | --- | --- |
| This planning synthesis | Rules/evidence/gates inspected; root whitespace known | Attempt1 maximum; fixes1/2 preparatory planning; §13 reconciliation writer maximum | **FAIL / FAIL / FAIL**; one explicitly authorized additional maximum review **PASS** | Original cycle retained; reconciled plan accepted through prerequisite gates (§14), not product qualification |
| P00 | Current baseline captured on 2026-11-10; all assigned commands returned | No code writer | Maximum discovery, not review1 | BLOCKED on docs assets, ownership reconciliation and recorded baseline defects; see terminal receipt below |
| P01 | Depends P00 | Pending medium or explicit maximum code/fix | Pending / — / — | Dirty work not accepted |
| P02–P06 | Prerequisites/assets pending | Separate prototype/planning dispatches | Pending per subject | Later code readiness blocked |
| P07–P38 | Pending per slice | Medium or explicit maximum exclusive code when applicable | Pending per subject | Not started; external gates explicit |
| P39 | Full current baseline required | No product writer | Maximum final review pending | Not production qualified |

### P00 admission receipt (2026-11-10)

The user authorized P00 only. The requested assignment was verification/discovery, explicit maximum,
with serial `*:write`. The status tool returned no direct children before resource allocation.
The launch tool refused admission: `Only markdown-orchestrator may launch workflow children.`
No child ID or dispatch ID was returned. No baseline worker or P00 product gate ran.
The requested profile is not evidence of a configured or observed child model.
P00 remains incomplete, and P01 remains blocked on its baseline.

The parent allocated these isolated resources for the attempted admission:

- Container `huron-p00-20261110t045227-pg`, ID
  `83336a4ac0a5ee998b86f586d6b446f11ebe767ee81ae67af359b4d30db96eaf`.
- Cached PostgreSQL image
  `sha256:88a36c64c1003dad93f56daa12d1f8916ec66d1fa3e5fb1fb0ae7cb77efd56d1`, with `--pull=never`.
- Volume `huron-p00-20261110t045227-pgdata`, label `huron.assignment=p00-20261110t045227` on the container.
- Test endpoint `postgresql://huron_p00@127.0.0.1:25432/postgres`, using isolated test-only trust authentication.
- Web ports: IdP `28199`, proxy `28197`, API `28198`, web `24173`, demo `25173`.
  All were free at inspection. No harness started.

Container creation, `pg_isready`, and the corrected asyncpg connection check exited 0.
The connection check reported PostgreSQL 16.14. An initial Python check had a syntax error and exited 1.
After admission failed, `docker stop` exited 0. Inspection confirmed the container was stopped with PID 0.
The container and volume remain preserved. No developer service or retained prototype resource changed.
A later orchestrator assignment must reconcile these resources before reuse and recheck the ports.

The previous user-authorized maintenance changed five skill-link targets in `HANDOFF_M11_PLAN.md`
and `design/m11-review-evidence.md`. Their historical hashes no longer describe their current bytes.
The six-document link check passed after that maintenance. This is not P00 baseline evidence.
This admission attempt changes only this parent-owned ledger, with no product or tooling edits.

### P00 terminal baseline receipt (2026-11-10)

**BLOCKED. P01 is not admitted.** After the user selected Markdown-Orchestrator, the parent dispatched
verification/discovery attempt1, explicit maximum, serial `*:write`. This supersedes the admission
block above, not its historical record. Discovery does not consume a P01 review attempt.

- Child: `ses_e3c2f1fa5ffeAQiv3XEiq3Oyux`.
- Dispatch: `770f504b-2f33-4d8c-a796-bdb8115f1385`.
- Configured agent/model: `markdown-reviewer-max`, `openai/gpt-6-astra`, variant/effort `max`.
  Status reported the Astra model. Provider effort acceptance remains `not-proven`.
- First progress: 04:56:48Z. The parent polled at intervals below one minute.
- Terminal response completed at 05:14:35.804Z and was observed at 05:15:27.690Z.
  Idle plus the completed terminal response established BLOCKED, not an intermediate progress message.
- Evidence directory: `/tmp/opencode/p00-20261110t045227`.
  `*-receipts.json` and `*.receipt.json` retain exact commands, cwd, exit codes, log paths and gate times.
  `ownership-classification.log` lists every dirty path. No source or tooling edits occurred.

#### Gate results

Root is `/home/karl/repo/huron-tusd`. Web and docs commands used its `web/` and `web/docs-site/` directories.
All gate subprocesses inherited offline/no-sync settings and the assigned database and web ports.
The worker ran the exact P00 commands from section 4, without snapshot regeneration or installation.

| Gate / command | Exit and measured outcome | Evidence file in the directory above |
| --- | --- | --- |
| G0 `git diff --check` | 2, existing trailing whitespace at `web/src/lib/api/openapi.ts:170` only | `g0-diff-check.log`, `final-diff-check.log` |
| G0 cached check | 0 | `g0-cached-check.log` |
| G0 separate new-text checks | 21 files, each exit1 without whitespace diagnostics | `inventory-receipts.json`, `g0-untracked-01.log` through `g0-untracked-21.log` |
| Six-document link check, including both handoffs | 0, relative file links checked, not all anchors | `g0-links.log` |
| `UV_OFFLINE=1 UV_NO_SYNC=1 make gate` | 0, 2,201 passed, 2 deselected, no skips, 99.98% coverage | `gp-make-gate.log`, `gp-make-gate.receipt.json` |
| GP lint/type/import/complexity/schema constituents | All passed, 10 import contracts kept, radon output empty, complexity within 15 | `gp-make-gate.log` |
| `uv run --offline --no-sync pytest -m contract` | 0, 59 passed, 2,144 deselected | `gc-contract.log` |
| `uv run --offline --no-sync pytest -m integration` | 0, 1 passed, 1 skipped, 2,201 deselected | `gc-integration.log` |
| GA snapshot/error tests from section 4 | 0, 3 passed | `ga-snapshot.log` |
| Web `npm run check` | 0, zero errors and warnings | `gw-check.log` |
| Web `npm test` | 0, 130 files and 1,645 tests passed | `gw-test.log` |
| Web `npm run lint` | 0 | `gw-lint.log` |
| Web `npm run build` | 0 | `gw-build.log` |
| Web `npm run test:e2e` | 1, docs sync failed before Playwright started | `gw-e2e.log` |
| Root `UV_OFFLINE=1 UV_NO_SYNC=1 make docs-check` | 0 | `gd-docs-check.log` |
| Root `uv run --offline --no-sync python scripts/ste_check.py` | 0, zero hard findings and 17 advisories | `gd-ste.log` |
| Root `uv run --offline --no-sync python scripts/cli_reference.py --check` | 0 | `gd-cli-reference.log` |
| Web `npm run docs:build` | 1, missing github-slugger before rendering | `gd-docs-build.log` |
| Docs `npm test` | 1, 3 passed and 1 file-level import failure, no skips | `gd-docs-test.log` |

Coverage measured 9,649 statements with two missing lines in unchanged CLI `identifiers.py:76–77`.
All 22 dirty/new source files had 1,855/1,855 measured statements covered.
`gp-coverage.json` and `changed-source-coverage.log` retain the detail. No threshold or exclusion changed.
The shared storage specification retains 253 rows, both adapters, 16 method variants and 125 arrangeable pairs.
The gate exercised both historical verification3 regressions. These observations do not accept P01.

#### Findings and disposition

| ID | Finding | Required owner/action before further acceptance |
| --- | --- | --- |
| B1 | Missing locked docs packages: `@astrojs/starlight@0.42.6`, `astro@7.4.0`, `github-slugger@2.0.0`. `web/docs-site/scripts/sync.mjs:11` cannot import github-slugger. | Explicit setup assignment to restore locked dependencies, then rerun all affected gates. This discovery prohibited installation. |
| B2 | Dirty `tests/conftest.py:30–35` defines `fixed_umask`, with associated import/docstring changes. P01 currently names only the temporary-mode fixture. | Parent must explicitly assign or exclude the existing umask bundle, including runtime `SERVICE_UMASK/build_runtime` and lifespan coverage. No silent ownership expansion. |
| F1 | Existing generated `openapi.ts:170` whitespace fails G0. | P01 contract owner fixes the source and regenerates through GA, never hand-edits generated types. |
| F2 | `core/storage/repair.py:43–49` still lists reason cases in `FailureReason`. The old plan's preserved resolution requires a one-sentence description without cases. | P01 contract owner removes duplicate rules so `RepairFailureOut` remains authoritative, regenerates and reruns GA/GW/GD/G0. |
| L1 | CLI integration is skipped at `test_cli_end_to_end.py:34–37`. The passing API integration is mountless. | P33 retains real-ingestion and skip-removal ownership. Not ingestion or release qualification. |
| L2 | Top-level npm11.19.1 runs nested scripts through `/home/karl/node_modules/.bin/npm` version2.15.12. | Setup/environment owner reconciles resolution without unsolicited global changes. Missing docs packages remain the decisive observed failure. |

P00 is not green. No failure is waived and no remediation ran. An explicit ownership/setup decision and
the complete affected baseline rerun are required before P01 admission. F1/F2 remain assigned findings
for the P01 repair contract, not permission to proceed through unresolved prerequisites.
The known strict-marker, no-op `make docs`, absent acceptance-target and generic-lint workflow drift remains separately owned.

#### Ownership and preservation

The inventory contains 92 entries: 41 product paths, 43 tooling paths and 8 planning/document paths.
All 57 historical inventory entries remain with the same status classification. The additional 35
entries are tooling or planning work. Historical status alone does not prove historical byte equality.

- P01 product candidates: storage repair/parity/errors/ports/exports and POSIX primitives, placement
  pruning, lake repair/planning/lookups/lifecycle wiring, API repair/routes/schema/runtime wiring,
  their existing and new tests, and the two repair import-contract additions in `pyproject.toml`.
- The associated naming/upload tests and raw-ingest prose belong to the same candidate boundary.
  Preserve the 206-byte user component bound, 255-byte raw LakePath bound and 1,024-byte whole rel-path bound.
- API errors, OpenAPI and generated web types are P01 contract consumers. No generated file was rewritten.
- `tests/conftest.py::temporary_mode` is assigned by P01. `fixed_umask` remains the explicit B2 exception.
- `.agents/**`, `.opencode/**`, `opencode.json`, `.gitignore` and `AGENTS.md` remain tooling-owned.
  No `.agents` qualification ran. Plans, design records, handoffs and `docs/agents/domain.md` remain separate.

At 05:10:57Z, the worker confirmed all 947 captured file hashes, 92 status entries, references, staged
diffs and product diffs matched its initial capture. The three pre-existing staged deletions remain 500 removed lines.
HEAD remains `0dcdf1ff6a8689f704a73a0758a886c18b5d3584` on `tusd-integration`.
The old-plan and migration0003 blobs remain those recorded in section 1.
Reference `m11.5-escalated` remains `04958ad538eac69f16a6abdd3925350781e4d718`.
All seven retained prototype artifact hashes matched. See `final-preservation-receipts.json` and `retained-artifact-sha256.log`.
This parent-owned receipt changes the latest plan only after that preserved discovery baseline.

#### Resources, versions and limits

The worker used only the PostgreSQL resource and ports in the admission receipt above.
Before shutdown, only `postgres`, `template0` and `template1` remained, with no other client backends.
The container stopped at 05:10:05.135Z with PID0 and exit0. Parent inspection after terminal evidence
confirmed that state and the free assigned ports. Its volume remains preserved. No harness or browser started.
The worker found no owned residual check process. Developer services and the retained prototype remain untouched.

Recaptured versions: Python3.12.4, uv0.12.19, PostgreSQL16.14, asyncpg0.32.0, FastAPI0.162.0,
Pydantic2.14.1, pytest9.2.0, coverage7.17.0, Ruff0.17.3, mypy2.4.1, ty0.0.94,
import-linter2.15, radon6.0.1, complexipy8.3.0, Node26.10.0, top-level npm11.19.1,
Playwright1.62.1, Svelte5.56.10, SvelteKit2.70.3, Vite6.4.3, Vitest3.2.7,
Docker27.2.1 and OpenCode1.18.35. Matching cached Chromium exists, but was not exercised.

All required area skills, including ASD, loaded successfully. The historical ASD denial is obsolete for this worker.
The dirty web boundary contains generated repair declarations, not component/style/navigation changes.
No separate application visual target arose. Rendered docs remain unverified because their build failed.
The unavailable Svelte autofixer was not run or installed. Local POSIX/PG results do not establish
NFS/ONTAP, tusd/nginx ingestion, process-crash recovery, fencing or capacity qualification.

### P00 remediation ownership note (2026-11-10)

The user authorized a bounded remediation attempt for B1, B2, F1, F2 and L2.
Fix attempt1 uses code activity, medium Astra and serial `*:write`.
Dispatch: `66662fd7-9215-4cc4-af6c-61272294fef8`.
Child: `ses_e3bfe3984ffeQjv8Nxk6aMAchI`. Provider effort acceptance remains not-proven.

The parent explicitly assigned the existing umask bundle to P01, as enumerated in its clause above.
This resolves B2's ownership ambiguity only. This remediation does not change the bundle's behavior.
The other assigned changes restore locked docs dependencies, select the invoking npm for nested scripts,
and remove duplicate FailureReason rules through source regeneration.
The original P00 BLOCKED receipt remains unchanged. P01 remains pending independent acceptance.
No historical evidence hash, old plan, migration or unrelated dirty hunk belongs to this remediation.
Complete gate results and preservation evidence belong to the remediation's terminal self-check,
not an independent PASS. Logs use `/tmp/opencode/p00-remediation-20261110`.

For every later dispatch append: subject/attempt/profile/activity/claims, child ID, start time,
last progress time, observedAt/progress age, exact command/cwd/log/exit, owned diff, remaining work,
actual terminal response/process evidence, finding disposition and review count. Idle alone is not
completion. A writer may not write its own independent PASS. The parent records review outcomes
without changing historical failures. No fourth review without explicit plan reconciliation.

Progress contract for every assignment, including validation and resumes:

> Every implementation, fix, and verification subagent must send a brief progress update at least every 15 minutes of elapsed time while its assignment remains active, including during validation. Send blockers, repeated failures, and suspected hangs immediately rather than waiting for the next interval. These are progress messages, not final implementation reports or verification verdicts. Keep each update to 2-4 short lines containing the phase/task, agent role and attempt number, elapsed time, concrete progress since the previous update, current operation or command, and the next step or blocker. If nothing has advanced, say so and identify the last observed activity; do not substitute 'still working' for evidence. Parent polls asynchronously at least once per minute.

After independent plan acceptance, the exact invocation is
`/implement-markdown IMPLEMENTATION_PLAN_LATEST.md`, **initially P00 only**, with parent-resolved
resources and all blockers enforced. This planning assignment does not execute it. P06 must freeze
the evidence-driven code contract before P07. Final receipt must distinguish design validation,
plan acceptance, implementation completion and production qualification, and retain the accepted
single-writer outage, mixed in-progress visibility, source-consistency and AUTH_SYS limits.

## 11. Planning writer's validation receipt

These are this prose slice's checks, **not independent plan review or product qualification**.
All terminal commands used `/home/karl/repo/huron-tusd`; no product/site suite or service ran.

| Check | Observed outcome |
| --- | --- |
| `git diff --check` | Exit2, only pre-existing `web/src/lib/api/openapi.ts:170` trailing whitespace; unchanged and not owned here |
| `git diff --cached --check` | Exit0, no diagnostics |
| `git diff --no-index --check /dev/null IMPLEMENTATION_PLAN_LATEST.md` | Exit1 (new file differs), no whitespace diagnostics |
| Same new-text command for each of `design/m11-production-architecture.md`, `design/m11-review-evidence.md`, `design/m11-prototype-evidence.md` | Each exit1 (untracked content differs), no whitespace diagnostics |
| Four-document `uv run --offline --no-sync python scripts/check_links.py` command in G0 | Exit0, no output; checks relative file existence, not anchors |
| `rg -c '^### P[0-9]{2}[abc]? ' IMPLEMENTATION_PLAN_LATEST.md` | Exit0, 42 slices |
| `rg -c '^\| M11\.' IMPLEMENTATION_PLAN_LATEST.md` | Exit0, 19 task rows |
| `rg -c '^\| F[1-7] ' IMPLEMENTATION_PLAN_LATEST.md` | Exit0, seven finding rows; operational rows O1–O16 also manually checked |
| `make -n docs` | Exit0, “Nothing to be done”; confirms no strict site-build gate |
| `make -n test-acceptance` | Exit2, no rule; clearly future P35 command, not a current passing gate |
| Status/ref/branch/old-plan and 0003 hashes | Exit0; initial status retained plus the two new deliverables, earlier owned design files updated; HEAD/ref/reference branch and both preserved blobs unchanged |
| `git ls-files roadmap`; staged/unstaged 0003 diffs | Exit0, empty output |
| Probe report/script/result/log `sha256sum` | Exit0; hashes recorded in durable prototype evidence; no artifact changed |
| Manual reference/gate/dependency self-check | Actual Makefile/CI/package scripts and referenced existing source/test paths inspected. Future paths/commands labeled. Total serial dependency order has no backward prerequisite; later acceptance references are gates, not prerequisites to their own implementation. |

The writer refined only owned prose during self-check: explicit private capacity port, provisioning
owner primitive and offline command, temporary schema deletion/moves, all mutation/seed consumers,
and smaller API/CLI/composition slices. Three unmatched-context patch attempts made no change and
were followed by scoped successful patches. All four documents received the final link/new-text
check again after these refinements. No unknown work was reverted. Independent maximum review
was pending at that synthesis; it later returned FAIL as recorded below. Later evidence/asset/qualification blockers remain open.
The naming self-check distinguished the actual 206-byte user component rule in the dirty source
from the 255-byte raw LakePath bound; the plan preserves both instead of silently widening uploads.

### Planning fix1 after maximum review1 FAIL

Reviewer `ses_e414a07b4ffeiXZm8gPW2sUSqu` found the P07 gate/caller contradiction and missing
instance/principal recovery binding. Fix child `ses_e413f9417ffeT4PMGHHwxXjNpM`, dispatch
`b3f5cfb2-3585-43c6-94bf-35f0f73e356e`, is preparatory Low fix/planning under serial `*:write`.
Both contracts are writer-fixed proposals **awaiting independent maximum review2**, not accepted
design or implementation. Detailed dispositions and static code evidence are in review evidence §11.
P06 freezes the test staging and binding/wire contracts before P07 onward. The serial order stays
42 slices; early collaborator tests use declared network fixtures/direct identity initialization,
not the later API route/operator command. P27c removes the tests-only legacy composition; gates
and coverage remain unchanged. No probe results were added. Context-mismatched patch attempts
made no changes; successful patches touched only these four owned documents.

Fix1 validation from repository root: `git diff --check` exited 2 solely for existing generated
web/src/lib/api/openapi.ts:170 trailing whitespace; cached check exited 0. Each of the four exact
`git diff --no-index --check /dev/null` document checks exited 1 (additions) without diagnostics.
The full four-document G0 link command exited 0 without output. Count checks returned 42 slices,
19 M11 task rows and seven F rows; O1–O16 remain in their grouped traceability rows. Status and
staged/unstaged diff inspection preserve the original inventory; HEAD, tusd-integration,
m11.5-escalated and old-plan/0003 hashes still match §1, and both 0003 diffs are empty. The same
prose gate is rerun after this receipt. No application/site suite, service, install or new probe
applies or ran. Missing local language/instruction skills remain recorded, not silently passed.

### Planning fix2 after maximum review2 FAIL

Reviewer `ses_e41375e91ffeReJef3Uy9rhbnM` returned terminal FAIL for credential transmission before
local destination approval and missing context registry/panel ownership. Fix child
`ses_e412f6ce4ffer6joD6no6pwOVR`, dispatch `6d0c6f4b-86ac-4918-b170-0ade3e50eaf3`, is
fix/planning, configured preparatory Low, serial `*:write`; provider effort was not measured.
Both findings are writer-fixed **pending final maximum review3**, not independent acceptance.
Review1's resolved P07 and namespace corrections remain; no fourth review is authorized.

Static self-check traced ordinary ApiClient token acquisition, Services effective configuration,
Session refresh/exchange and provenance-free Tokens, then command registration and reference
layout validation. §3.5 now orders local trust/provenance before credentials; P22/P23 own atomic
acceptance and token format, P27b owns precise registration and live wiring. P03/P23/P25/P29
acceptance explicitly observes credential non-disclosure. First login, abort, refresh timing,
switch-back and duplicate registration are covered without changing server/broker/web scope.
The 42-slice serial order remains acyclic: P03 models the future state, P22 supplies primitives,
P23 supplies collaborators using network fixtures, and P27b wires P27a's route. No later route
or command is an earlier implementation prerequisite. All 19 M11 rows and F/O rows remain.

Root validation: git diff --check exit2 only at existing generated openapi.ts:170; cached check
exit0. Each of the four exact new-text checks exit1 for additions with no whitespace diagnostics.
The exact four-document G0 link command exit0, no output. Count commands returned 42/19/7 for
slices/M11/F rows; grouped O1–O16 rows retained. Existing referenced test_login.py and registry/
panel/reference paths verified. Status inventory, HEAD, branch/reference branch and old-plan/0003
hashes match §1; both 0003 diffs and git ls-files roadmap remain empty. No unknown work changed.
These checks are rerun after this receipt. No product/site suite, service, probe or install applies
or ran. Missing canonical language/instruction skills remain recorded; no new evidence claim.

## 12. Final independent review and escalation receipt

Parent-recorded on 2026-11-09 after terminal review3 evidence. Reviewer
`ses_e412ba125ffeV3Y9o1hLnuYhTi`, dispatch `35183e84-9e73-4a28-9bed-1ea7e0a7deb9`,
used verification/review, explicit maximum Astra, and serial `*:write`. Configured effort
was max; provider effort acceptance remains not-proven. Terminal FAIL completed at
2026-11-09T05:53:13.859Z and was observed at 05:53:43.997Z. Progress is not this verdict.

**Remaining finding R3-1 — medium, PLAN DEFECT, unresolved.** The proposed versioned
credential state refuses legacy tokens, but no slice assigns migration or retirement of
`scripts/dev-login.sh`. Its lines 23–40 directly acquire/exchange credentials and write the
old four-field token document. Its callers include `scripts/e2e.sh:77–81` and
`scripts/demo-noaa.sh:57–66`; the historical M11.11 smoke contract also uses it.
P27b's CLI cutover and P33's development/e2e gates therefore lack a required producer transition.

Owner: parent, CLI maintainer, and development-stack maintainer. Next action: reconcile the
plan through `/implementation-plan`, assigning the helper and every caller to a named cutover
slice. Either use fresh, explicitly approved development authentication through the new
credential/state collaborators and root lock, or explicitly retire and replace the helper
and all callers/documented targets. Specify subprocess/public-behavior coverage and retain
the complete e2e/smoke gates. Do not infer provenance from current configuration, weaken
legacy-token refusal, or bypass credential non-disclosure. This receipt records the defect;
it does not silently resolve or independently accept a new design.

Review3 confirmed the earlier P07 test transition, instance/principal binding, credential
trust ordering, and command registry ownership corrections. It confirmed 42 slices, all
19 M11 task rows, F1–F7/O1–O16 traceability, and all seven recorded prototype hashes.
The local experiments remain narrow evidence, not full application/process-crash/NFS proof.

The reviewer independently reran the four-document G0 link command (exit 0), cached
whitespace check (exit 0), and each new-document whitespace check (exit 1 for additions,
no diagnostics). Root `git diff --check` exited 2 solely for the preserved baseline
`web/src/lib/api/openapi.ts:170` whitespace. HEAD, old-plan and 0003 blobs, initial dirty
inventory, and `m11.5-escalated` were preserved. Product/site suites were not applicable
to the prose changes and were not run; no retained container was restarted.

**Disposition:** review limit reached; no review4 or production implementation is authorized.
This file is a substantial executable-phase draft with an explicit unresolved ownership
defect, not an accepted implementation-ready plan. P00 remains separately admissible discovery;
all other prerequisites and external production gates remain in force. The parent records
this outcome without modifying the reviewed technical contracts or historical failures.

## 13. R3-1 substantive planning reconciliation (2026-11-09)

**Writer proposal only; BLOCKED pending independent review.** Section 12 above remains the exact
historical review3 receipt, including its then-current prohibition on a fourth review. The later
user explicitly authorized substantive reconciliation followed by **ONE additional independent
maximum-profile review**, as a one-time exception to the exhausted three-review cycle, with no
automatic retries. This does not erase FAIL/FAIL/FAIL, accept this revision, authorize implementation
or change the review limit for another subject. The parent records writer terminal evidence and
separately dispatches that review; this worker cannot launch it or authorize any further review.

Current writer: role implementation/activity planning, reconciliation attempt1, configured profile
maximum, model `openai/gpt-6-astra`; provider effort acceptance **not-proven**. Dispatch
`74172ff5-25cb-4bbc-b53a-e76fab96563e`, child `ses_e410c833fffesQVUD7YKqcsdDO`, parent
`ses_e41163e2cffegYfUEyI61BqEIg`, envelope created `2026-11-09T06:16:30.623Z`. Claim `*:write`
coordinates the whole worktree/check outputs serially; edit ownership is only this file and the
three design/m11-*.md records. No ports/services are assigned. The parent reports that the previous
launch was refused (“Only markdown-orchestrator may launch workflow children”), status returned [],
and no child started. The user selected the orchestrator switch and Continue. This writer uses the
received ordinary v2 dispatch; it did not repair a journal, bypass admission or resume a child.

### Selected correction and future ownership

R3-1 is addressed **in the writer's proposal**, not marked independently resolved. The substantive
change is a complete producer transaction, not a four-field-to-versioned JSON edit:

1. P22 owns generic locked atomic credential-only/combined endpoint publication. It has no auth
   dependency. P23 supplies the typed approval/fresh-login/provenance/identity collaborators and
   independently testable repository password adapter, with an explicit approval-file interface
   and stdin/terminal secrets. Its network fixture does not depend on P27a's future route.
2. P27b is the single producer/reader cutover: installed CLI, external helper, both shell workflows,
   test login factories, Makefile demo target and active credential/workflow docs all change here.
   Delete scripts/dev-login.sh and old credential writer APIs with no compatibility alias. No
   positive fixture can mint a token and add config-derived provenance to evade the new flow.
3. P27c still converts production composition and deletes P07's temporary real-PG test constructor.
   P29 tests actual helper/CLI processes and save crashes. P33 runs the full real stack, every-role
   e2e, NOAA first load and cached offline idempotent rerun; its syntax checks are not acceptance.
4. P34 replaces historical raw pod token injection with independent fresh approved host and pod
   authentication in isolated XDG roots. It preserves real byte/check/restart/deployment obligations.
   P36 retains remaining M11.12 docs; P39 reruns the full helper/e2e/demo/deployment checks.

All contracts remain future work. Old working state is preserved/refused, not migrated. Ordinary
fresh login never rebinds it; endpoint acceptance still verifies the same durable instance/subject
and selects approval/credentials/working endpoints together. Local trust/provenance still precedes
all credentials, even with unexpired tokens. Required evidence observes zero credential delivery
at unapproved receivers and durable filesystem outcomes, not merely a private method call count.

The serial structure stays 42 slices, 19 M11 mappings, F1–F7 and grouped O1–O16. P07 test-only PG
composition/deletion at P27c, service identity, expected-binding headers, context LAYOUT/register/
test_panels and strict reference guard remain. No thresholds, gates, assertions or coverage scope
are reduced. Broker/web/ephemeral seed authentication is classified separately, not silently adopted
as CLI-state ownership. The detailed inspected inventory is in review evidence §13.

### Preservation and evidence limits

Before editing, HEAD/branch/reference and preserved blobs matched §1; the complete §2 inventory
in review evidence remains unchanged, plus the already present four documents and read-only
HANDOFF_M11_PLAN.md. Handoff initial Git blob is `83e6e675f2434297b6b6fc3470ee7ff1f4a4ef88`.
Initial owned-document blobs, in plan/architecture/review/prototype order:
`4eb1aa209bee073814d7921114244a94b96ca124`,
`5e0d2e694d52946f3d09ec855becb946ec6ad5ce`,
`7234c1ebffa6d7b6e38f16ba8b2772c6d0ab932c`,
`09514da602055c6d7eb001e625957ba38abb0325`.
An initial hash command used the nonexistent `0003_collection_upload.py` and failed with a
missing-file diagnostic; its exit was not separately captured. The corrected command read the
actual `migrations/versions/0003_uploads.py` and returned the preserved hash. No file was created
by that error. Both migration diffs remained empty.

No tests, probes, services, container operations, P00 run, installs, cleanup, tooling or Git-history
changes were made. Canonical asd-ste100/writing-for-agents are still absent; no fetch or formal
qualification claim. Prototype changes are history/status/untested limits only: all seven hashes,
the selected Placer/StateDir/_recover observations and six tiny real-PG/FS logical reconnects stay
intact. None proves process-crash, real tusd, NFS/ONTAP, workload or the new authentication seam.

### Current prose validation receipt

All commands below used cwd `/home/karl/repo/huron-tusd`. These are writer self-checks, **not
independent review or acceptance**. Each gate's exit was captured with `result=$?; declare -p result`
and returned unchanged. Parent-owned offline assets, qualification resources and every other blocker
in §10 remain; this assignment does not run or enable downstream phases.

| Exact command | Observed result |
| --- | --- |
| `uv run --offline --no-sync python scripts/check_links.py HANDOFF_M11_PLAN.md IMPLEMENTATION_PLAN_LATEST.md design/m11-production-architecture.md design/m11-review-evidence.md design/m11-prototype-evidence.md` | Exit0, no diagnostics; relative file links only |
| `git diff --check` | Exit2, solely preserved baseline `web/src/lib/api/openapi.ts:170: trailing whitespace`; not repaired |
| `git diff --cached --check` | Exit0, no diagnostics |
| `git diff --no-index --check /dev/null HANDOFF_M11_PLAN.md` | Exit1, additions only; no whitespace diagnostics; handoff hash unchanged |
| `git diff --no-index --check /dev/null IMPLEMENTATION_PLAN_LATEST.md` | Exit1, additions only; no whitespace diagnostics |
| `git diff --no-index --check /dev/null design/m11-production-architecture.md` | Exit1, additions only; no whitespace diagnostics |
| `git diff --no-index --check /dev/null design/m11-review-evidence.md` | Exit1, additions only; no whitespace diagnostics |
| `git diff --no-index --check /dev/null design/m11-prototype-evidence.md` | Exit1, additions only; no whitespace diagnostics |
| `rg -c '^### P[0-9]{2}[abc]? ' IMPLEMENTATION_PLAN_LATEST.md` | Exit0, 42 |
| `rg -c '^\| M11\.' IMPLEMENTATION_PLAN_LATEST.md` | Exit0, 19 |
| `rg -c '^\| F[1-7] ' IMPLEMENTATION_PLAN_LATEST.md` | Exit0, 7 |
| `rg -c '^\| O[0-9]' IMPLEMENTATION_PLAN_LATEST.md` | Exit0, 11 grouped rows; manual expansion covers O1–O16 |
| ``rg -c '^\| `.*` \| `[0-9a-f]{64}` \|' design/m11-prototype-evidence.md`` | Exit0, seven hash rows retained |
| `git status --porcelain=v1 --untracked-files=all`; `git diff --numstat`; `git diff --cached --numstat` | Exit0; initial dirty/untracked and tracked/cached change inventory unchanged. Only the four allowed untracked documents were edited |
| `git branch --show-current`; `git rev-parse HEAD`; `git rev-parse m11.5-escalated` | Exit0; tusd-integration and both supplied refs unchanged |
| `git hash-object IMPLEMENTATION_PLAN.md migrations/versions/0003_uploads.py HANDOFF_M11_PLAN.md` | Exit0; respectively 862e1bafc54c5ca88b0351ff7ee723662a1ac7f8, 83757f7e73640356639ae07c45d7885660b9a6e3, 83e6e675f2434297b6b6fc3470ee7ff1f4a4ef88 |
| `git diff -- migrations/versions/0003_uploads.py`; `git diff --cached -- migrations/versions/0003_uploads.py` | Exit0, empty |

Manual checks: review-evidence's §12 historical-receipt link still targets this file's unchanged
`12-final-independent-review-and-escalation-receipt` heading; section references resolve; the full
§12 text and review-evidence §2 inventory remain unchanged. All seven artifact hash values match
their initial text (no new probe hash capture claimed). Rechecked exact future helper/script/test/
target ownership, observed current Makefile checks and serial dependencies: P23 uses its test
response fixture, P27b uses P27a's router, and P33/P34 are later full-workflow gates, not early
implementation prerequisites. Original 42/19/F/O structure and every earlier correction remain.

The self-check clarified the explicit staging boundary, the baseline-skipped Stack's future state
API transition, sanitized receiver observations and identical advertised/forwarded issuer URLs.
Five unmatched-context patch attempts made no changes; successful apply_patch calls touched only
the four owned documents. The complete five-document link/whitespace set is rerun after this receipt.
No product/site suite applies to these prose-only changes, and none was run. Missing skills remain
policy drift; no formal qualification, acceptance or additional-review authorization is claimed.

## 14. Parent acceptance receipt after authorized independent review (2026-11-09)

**PASS for the reconciled planning contract. R3-1 is resolved.** This supersedes the pending
status of the writer's §13 receipt, not its history or §12's original FAIL. The user explicitly
authorized one additional maximum-profile review after substantive reconciliation. That exception
is now consumed; no automatic retry or reset of FAIL/FAIL/FAIL is authorized.

Writer `ses_e410c833fffesQVUD7YKqcsdDO`, dispatch
`74172ff5-25cb-4bbc-b53a-e76fab96563e`, completed at `2026-11-09T06:43:17.321Z`;
the parent observed terminal evidence at `06:43:26.684Z`. Independent reviewer
`ses_e40f2d2e1ffe6gF2TjxDaME7jm`, dispatch `b025e294-3d1f-479c-92a1-5064fd2418cd`,
then ran verification/review under serial `*:write`. Its terminal PASS completed at
`2026-11-09T06:55:25.790Z` and was observed at `06:55:55.711Z`. Both used configured maximum
`openai/gpt-6-astra`, effort max; provider effort acceptance remains not-proven. Historical
absent profiles remain not-recorded. The parent polled both children at bounded intervals;
terminal idle/completed responses, not intermediate progress, establish these outcomes.

The reviewer independently inspected the full plan and actual producer/caller seams. It found
no open fixable or plan defects within the four-document boundary. It confirmed the shared fresh
authentication transaction, explicit developer approval, all caller/test/doc cutover owners,
acyclic staging, credential non-disclosure tests, and full e2e/NOAA/host-and-pod smoke obligations.
It also confirmed every earlier correction, 42 slices, 19 M11 mappings, F1–F7/O1–O16, and all seven
prototype hashes against the retained artifacts. None of those artifacts proves the new auth flow.

Independent gate results, cwd `/home/karl/repo/huron-tusd`: the exact five-document link command
in §13 exited 0; `git diff --cached --check` exited 0; each of the five separate `/dev/null`
whitespace commands in §13 exited 1 for additions with no diagnostics. `git diff --check` exited
2 solely for the preserved unrelated `web/src/lib/api/openapi.ts:170` whitespace. This root failure
is not relabeled green: independent inspection established the clean owned prose boundary.
Structural counts, seven-artifact hashes, preservation refs/blobs/status, migration diffs and
ignore checks passed. The reviewer edited nothing and found no residual check process beyond
the inspection itself. No product/site suites, services, probes, installs or cleanup ran.

The parent accepts this plan **through its explicit prerequisite gates**. A future
`/implement-markdown IMPLEMENTATION_PLAN_LATEST.md` starts with separately admitted **P00 only**,
after resource assignment. It was not run here. P02–P05 evidence and P06 freeze remain mandatory;
offline assets, cached NOAA inputs, ONTAP/fencing/workload evidence and policy-drift reconciliation
remain enforced at their named gates. Complete design validation, product implementation and
production qualification are not claimed. Parent status/receipt edits record this actual verdict
only; they do not change the reviewed technical contracts or historical failure receipts.

## 15. Prospective tooling and setup amendment (2026-11-09)

The user separately authorized a bounded tooling migration. It includes these baseline corrections:

- Correct stale skill-policy checks.
- Correct the misspelled ASD allow rule/source registration.
- Add the missing root `/roadmap/` ignore rule.

This amendment governs prospective workflow only. It supersedes these clauses in design/m11-production-architecture.md without editing that historical design:

- Lines 604–607 contain the Max-only code/fix/review workflow clauses.
- Lines 623–624 contain the outdated missing-skill availability claim.

Sections 11–14, historical observed/configured profiles, the old IMPLEMENTATION_PLAN.md, migration
0003 and all product contracts remain unchanged. Explicit Maximum prerequisite probes/reviews
such as P00 and P02–P06 remain Maximum. Ordinary code/fix/review uses Medium after restart.
Final COMPLETE qualification must explicitly use verification/review/maximum and rerun all gates.

The migration worker is implementation/code attempt1, configured maximum Astra/max, dispatch
`2944a623-0fb7-424c-936a-b841133f94de`, child `ses_e408c796effeI227CS8VizNTvj`.
It has serial `*:write` and `build:agent-tools:write`, not permission to edit all files/services.
Its loaded configuration and this serving session remain unchanged until quit/restart. Provider effort
acceptance is not-proven. Medium is future configuration, not a claim about this worker.

Three fixed profiles select low/medium/max effort without fallback. New classified omission
defaults to medium. Omitted activity plus claims remains legacy-exclusive, with omitted profile
defaulting to maximum. Explicit Medium/Max may be legacy-exclusive, with the same exclusion.

The dispatcher refuses Low code/legacy-exclusive before journal/API effects. The v1 ledger container stays.
v1 profile absence stays not-recorded/configured null, and existing v2 profiles stay unchanged.

Reads never apply new-request defaults. Older two-profile readers reject Medium: no mixed
launchers, journal migration/backfill, or new Medium record before a quiescent restart.
Native child parentID, asynchronous prompt submission, navigable IDs, no Task bypass/nested
delegation, claims/admission/privacy/progress/terminal/lock/unknown-state rules remain intact.

The explicit approved skill directories are `.agents/skills`,
`~/.agents/skills/writing-for-agents`, and `.claude/skills/asd-ste100`. Skill permissions remain deny-by-default.
Normal root `opencode` startup retains external discovery. No launcher or scan-suppression flag is required.
The global writing skill is not vendored. Missing approved sources fail with supply/restart guidance.
Discovery does not grant permission to load unrelated skills.
The internal lifecycle skills use `huron-design-plan`, `huron-prototype`, `huron-implementation-plan`, and `huron-implement-markdown`.
Their public slash commands keep their unprefixed names. Generic internal aliases are removed.
The checker requires canonical Huron sources and approved area sources, but permits unrelated discovered skills.

Writing-for-agents and skill mechanics govern this instruction-policy work. The serving policy denied ASD.
The worker did not load it or read it directly. Its language qualification remains
pending a permitted post-restart load/review. This migration edits no site or product language.

The approved setup exception in §4 and AGENTS.md permits only existing-lockfile `npm ci` and
matching Chromium from the project-installed Playwright CLI. This exception authorizes no upgrade, broad npx fetch,
autofixer install, image pull, or implicit service mutation. This migration performs
none of these operations. Adding `/roadmap/` to the root ignore file deletes or moves no data.

Independent baseline `ses_e409cc5aaffeoZkOUKvxHtBStE` ended BLOCKED at 08:33:58Z, observed at 08:34:30.887Z.
The tooling check returned exit1 (TypeScript passed). Tests reported 108 total, 103 passing, and 5 stale-policy failures.
The resolved checker returned exit1 for denying the user-approved writing skill. The ignore rules did not cover roadmap. These are
owned remediations, not waived failures. Unrelated generated OpenAPI whitespace remains the
independently established excluded boundary. No product, frontend or site suite applies to this
tooling/instruction-only change. The complete assigned tooling and link gates still apply.

The writer stops after one implementation/self-check pass. The parent must then complete these steps:

1. Reconcile terminal children and owned processes.
2. Quit/restart with normal `opencode` from the repository root.
3. Inspect the loaded schema/agents/skills.
4. Arrange independent Maximum review.

Fresh CLI
checks do not activate the serving process. The legacy `.claude/commands/implement-markdown.md`
is not the resolved OpenCode entrypoint and remains out of scope, not an alternate launcher.
The exact self-check receipt and pending restart/review contract are in
[HANDOFF_MEDIUM_WORKFLOW.md](HANDOFF_MEDIUM_WORKFLOW.md). This amendment is not a PASS or product claim.
