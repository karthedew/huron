# M11 production architecture: accepted commits before public file changes

Status as of 2026-11-09: **reconciled plan accepted through explicit prerequisite gates**.
The serial [replacement phase plan](../IMPLEMENTATION_PLAN_LATEST.md) retains maximum review
**FAIL/FAIL/FAIL**. Section 15 records the substantive R3-1 writer proposal; the one later
user-authorized independent maximum review returned PASS. The parent receipt in
[plan §14](../IMPLEMENTATION_PLAN_LATEST.md#14-parent-acceptance-receipt-after-authorized-independent-review-2026-11-09)
records resolution of R3-1 and the remaining prerequisite gates, with no automatic retries. The
[durable prototype receipt](m11-prototype-evidence.md) records only narrow preparatory results.
No product or complete-design acceptance is claimed.

Initial status was “proposal for independent architecture and prototype review”, written
2026-11-09 by planning writer attempt 1. Sections 1–11 retain that proposal's history and intent;
the dated updates in sections 12–15 govern current status and next action.

## 1. Scope, authority, and evidence

The approved direction is a focused correction to publication and recovery, not a lake rewrite.
An upload must not replace committed bytes before the collection commit is accepted. A client
must resolve a lost answer through its own durable request identity, not another write's version.

This proposal selects engineering decisions within that direction. Acceptance of this document
must precede replacement phase planning. It does not silently amend or resume
[IMPLEMENTATION_PLAN.md](../IMPLEMENTATION_PLAN.md). That file remains exactly as found.
Its sections 3–9, dated amendments, and the M11.5e user resolution remain the historical binding
contract until the parent records the reviewed supersession. All unaffected rules remain.

The [evidence record](m11-review-evidence.md) contains the unchanged ownership inventory, discovery
provenance, findings, all 19 M11 dispositions, exact gates, and the bounded prototype assignment.
Discovery inspected code but executed no product tests. This writer checked the key producers
and consumers again; neither inspection nor self-check is independent acceptance.

### Explicit supersessions proposed

| Old contract | Selected replacement and scope |
| --- | --- |
| D-7: one synchronous transaction for a commit | Short DB acceptance/reservation, recoverable file materialization, then one final DB transaction. The request may finish synchronously, but a bounded wait can return an in-progress operation. |
| D-8: no idempotency keys; infer success from version/files | A required client-generated request UUID binds one canonical payload and one durable outcome. There is no version/content inference fallback. |
| Upload flow and ADR 0008: pre-finish places public bytes | Pre-finish only creates a private, independently copied and sealed object. A later accepted commit controls public names. |
| Hard-link-only placement from the tusd inode | Copy the tusd data to a new private inode before sealing. Publication can hard-link that sealed inode. No symbolic link is introduced. |
| No disk tasks | Permit only the durable commit-publication journal and identity-bound cleanup described here. No generic job platform, ingest sidecar, or filesystem repair walker. |
| Two writable API replicas; inode/lease residuals | Initially one writable API process per lake and one tusd process. Replacement requires proven quiescence or external fencing. No accepted overlap window. |
| Receipt TTL and mtime sweep | Explicit expiry, reservation, retention, and cleanup ownership. Neither elapsed time nor mtime authorizes deletion of live work. |
| Commit success despite failed removes | Success requires every requested public add and remove to be finalized. Only private garbage collection may remain outstanding. |
| In-place edits to unreleased 0003 | An additive next revision preserves 0003. Existing test-bed data is never reset or converted without a separate owner decision. |

The terms *publication* and *generation* below describe an internal materialization protocol,
not a new user-visible file-version feature. `CONTEXT.md` has older, conflicting commit-state
and write-path definitions (lines 35–39 and 53–57). Its future owner must reconcile only affected
terms after review; this assignment does not edit it or adopt its unrelated reconciler design.

## 2. Preserved foundations and invariants

Preserve `LakePath`, validated names, descriptor-relative no-follow traversal, and marker checks.
The mount point stays fixed. Do not restore `resolve`, per-write `st_dev` checks, symlink creation,
CLI lake writes, ACLs, or the removed copy-to-share workflow. The privileged provisioning commands
remain the existing exception; they run under maintenance ownership, not alongside API writers.

Keep one `Storage` port, full `MemoryStorage`, real `PosixStorage`, server-computed hashes, frozen
domain values, consumer-owned ports, asyncpg transactions, and the existing package/import rules.
Keep separate hash/large-copy and short-disk pools. Repair remains planned from database rows.
The complete error matrix and the authoritative `RepairFailureOut` Field descriptions remain
binding. New storage methods extend that matrix on both adapters, rather than weakening it.

The protocol must maintain these observable invariants:

1. No unaccepted upload or rejected commit changes a public collection name or its bytes.
2. An add references an explicit upload and its sealed object. Size, time, inode, or a public
   filename alone cannot establish that relationship.
3. The request UUID is saved by the client before POST. Its payload cannot change after first
   submission. The server retains the same terminal outcome for the lifetime of the instance.
4. Acceptance durably reserves the collection and all required new and previous objects before
   any public effect. A collection has at most one pending file operation.
5. While pending, competing writes to that collection fail with an explicit conflict. Timeouts,
   disconnects, lease loss, and client cancellation do not release this reservation.
6. Accepted work rolls forward. A storage problem leaves it blocked and recoverable, not rejected
   after some files changed. No automatic rollback guesses which public bytes belong to it.
7. Final success means all requested public names have the accepted bytes, all requested removes
   are absent, required durability calls succeeded, and DB file rows/count/version/audit/outcome
   finalized once. This does not promise an all-file NFS snapshot or control existing reader FDs.
8. Old bytes and every object needed for recovery remain retained until durable finalization.
   Cleanup failures consume capacity but cannot erase the operation's meaning.
9. A DB lease is not filesystem fencing. An uncertain old writer prevents a replacement writer.
10. No local CLI mutation loses staged or unresolved intent through concurrency or a crash.

### Visibility contract

Direct readers can observe mixed names during an **accepted** multi-file operation. Each replace
is per-file; a reader with an old open FD may continue reading the old inode. NFS client caches
can delay observation. The API exposes `pending_operation` and continues to return the last
finalized file rows/version until finalization. Those rows are not a promise that the live mount
is a snapshot while pending. Clients that need a stable read must wait for no pending operation
and use their own read-consistency discipline; a subsequent commit can still begin.

There is no claim of atomic PostgreSQL plus filesystem commit, power-loss safety from rename
alone, or instantaneous visibility on every NFS client. Strict all-file snapshot reads would
require a separate approved read contract, such as immutable directory generations and indirection.

## 3. Owners and proposed interfaces

Keep the existing collaboration direction:

```text
CLI durable intent -> API route -> lake domain acceptance/status/finalization
                                  | normalized metastore ports
                     API disk orchestration and writer ownership
                                  | marker + bounded execution
                     storage rules -> one Storage port -> POSIX primitives
```

The following signatures are **proposed**, not available functions. Values are frozen dataclasses;
HTTP Pydantic models remain at the edge. Domain paths stay API-form strings, not `LakePath`.

```python
# core.lake.uploads: explicit attempts and ready-object eligibility
async def begin(actor, collection_id, rel_path, size, *, attempt_id,
                expected_sha256, supersedes_upload_id=None) -> UploadView: ...
async def start_seal(upload_id, owner) -> SealTicket: ...
async def finish_seal(ticket, evidence) -> UploadView: ...
async def cancel(actor, upload_id) -> UploadView: ...
async def get(actor, upload_id) -> UploadView: ...

# core.lake.files: no filesystem I/O in these operations
async def submit(actor, collection_id, request) -> CommitOperation: ...
async def status(actor, request_id) -> CommitOutcome: ...
async def next_steps(operation_id, owner, limit) -> tuple[PublicationStep, ...]: ...
async def acknowledge(operation_id, ordinal, evidence, owner) -> None: ...
async def finalize(operation_id, owner) -> CommitOutcome: ...

# applications.api.disk: assembled once; not exposed as a general work queue
async def seal(ticket) -> SealEvidence: ...
async def materialize(operation_id) -> CommitOutcome: ...
async def recover_pending(owner) -> RecoverySummary: ...
```

`CommitRequest` contains `request_id`, `base_version`, `adds`, `removes`, `host`, and optional
`message`. Each add contains `rel_path`, `size`, `sha256`, `upload_id`, and `object_id`.
The server checks both IDs belong together, to that actor, collection, and exact path spelling.
Client hashes are comparisons only; the recorded hash always comes from the sealed server object.
Keep the 10,000 total-entry limit, tree validation, case-fold uniqueness, and remove-exists checks.
Bound the canonical request to 16 MiB, including host/message; test the full entry boundary.

`POST /api/v1/collections/{id}/commits` returns 200 only for a final successful result. A durable
accepted operation that outlives a 5-second response wait returns 202 with `request_id`, operation
state, and the status URL. Disconnecting does not cancel it. A terminal domain refusal returns
its recorded problem. `GET /api/v1/commit-requests/{request_id}` returns the exact outcome,
including `accepted`, `publishing`, `blocked`, `succeeded`, or `rejected`. The exact HTTP schemas
and registered error classes are a later owned API slice, not generated in this planning pass.

The request key is unique by `(actor_subject, request_id)` in one instance. The canonical digest
includes the target collection ID and every semantic payload field; entries are ordered by their
validated case-fold keys before hashing. Same key and digest returns the original operation before
rechecking its old base version. Same key with another digest gives `REQUEST_ID_CONFLICT` (409).
A new payload, including a rebase, always gets a new UUID.

Persist semantic refusals for authenticated, structurally valid requests. Invalid transport
bodies, failed authentication, and failures before any durable receipt do not create an operation.
A status 404 in the verified saved instance/principal namespace means no durable record was found,
not permission to invent success: resend the **same** ID and payload. Section 13 defines the
required binding checks; another namespace's 404 is never replay authority.
A concurrent original submission is resolved by the unique constraint.
Status is creator-only (otherwise 404), with an explicit administrative diagnostic privilege.
The creator can recover a minimal saved outcome after grant revocation or collection deletion;
this exception reveals no new collection content or stored request body. New submissions still
require current `COLLECTION_WRITE_FILES`. Authorization is decided at acceptance; later grant
revocation does not reverse accepted work. Existing token/group freshness limits remain.

Dry-run remains non-reserving and unaudited, with no operation ID consumption. It checks the
current base/tree/permission and reports that upload eligibility and capacity are provisional.
Production never uses optional receipts. A mountless read-only deployment refuses mutations;
the explicit in-memory test/seed mode is not a production fallback.

### Storage additions, not an alternate storage boundary

The prototype must settle the smallest additions to `Storage` needed for these operations:

```python
def copy_sealed(source: LakePath, destination: LakePath, *, temporary_name: str,
                expected_size: int, expected_sha256: str) -> SealedFile: ...
def link_once(source: LakePath, destination: LakePath, *, inode: int) -> None: ...
def sync_directory(location: LakePath) -> None: ...
def list_children(location: LakePath) -> Iterator[Entry]: ...
```

These names are illustrative interface commitments, not permission to bypass the port in routes.
`copy_sealed` uses an exclusive new inode, streams bounded chunks, checks exact length/EOF,
syncs/closes it, then measures the sealed bytes. It never truncates an existing destination.
`link_once` never replaces an existing link/backup. `list_children` is shallow by construction;
filtering recursive `walk()` output is not equivalent. File/manifest writes and rename/unlink
must expose directory-sync failures, mapped through the existing storage-error contract.
Use operation-unique reserved temp names independent of the user's basename, avoiding the current
255-byte part-name expansion. Do not relax existing user naming limits as incidental work.

## 4. Durable data model and lock order

Use logged PostgreSQL 16 tables, not unlogged tables or an opaque JSON array journal. UUIDs identify
externally referenced requests/uploads/objects/operations. Use `bigint` for bytes, `timestamptz`
for instants, non-null required fields, state CHECKs, foreign keys, and explicit FK indexes.
Retain the current unsigned-inode conversion for diagnostic/storage guards, not object identity.

| Relation | Required fields and constraints | Recovery/access path |
| --- | --- | --- |
| `lake_writers` | One row per lake/instance; monotonic owner epoch; API/tusd owner identities; configuration digest; state `active`, `draining`, `uncertain`, or `quiescent`; last verified handover/fence record. No timeout changes uncertain to quiescent. | Startup ownership check and operator-approved handover. A row is coordination evidence, never proof that NFS has fenced a process. |
| `commit_operations` | ID; actor/request UUID unique; original collection/catalog/organization IDs; nullable live collection FK with `SET NULL`; payload digest; base/target version; state; accepted/final times; owner epoch; bounded terminal result/problem. No cascade deletes outcomes. | Unique request lookup; partial `(state, accepted_at, id)` index for unfinished work. |
| `commit_entries` | PK `(operation_id, ordinal)`; unique `(operation_id, rel_path_key)`; action; exact old/new spellings; old/new size/hash; old/new object FKs; upload FK; planned outcome. At most 10,000 logical entries, checked by the operation. | Fetch ordered immutable plan; index object/upload references. No new object for a remove. |
| `publication_steps` | PK `(operation_id, ordinal)` with entry reference; step kind; expected-before identity; desired-after identity; server-generated temporary locator; state/evidence; attempt count/error. Separate ordered steps handle remove/prune/add dependencies. | Ordered pending steps and blocked diagnostics. No claiming a lower-order row before collection locking. |
| `objects` | ID; upload/seal-attempt identity; unique private locator; expected and measured size/hash; state `sealing`, `sealed`, `gc_pending`, `deleted`; seal-manifest digest; diagnostic inode; creator and scope IDs. A sealed row has complete evidence. | By ID; recovery of incomplete seals; GC eligibility. Deleted identities are never reused. |
| `uploads` | Existing aggregate revised in the new migration: client attempt UUID unique per actor; explicit object FK; expiry; superseding upload FK; reservation operation FK; state; failure. State constraints replace placed/latest-receipt semantics. | Creator status; expiry index; explicit object lookup, not latest timestamp per path. |
| `collections` and `files` | Collection has nullable `pending_operation_id`; final files reference their object IDs. Pending operation owns exactly one collection, with a uniqueness constraint. Collection version stays final until finalize. | Reservation check on every collection mutation; file/object reference indexes. |
| `object_references` | Unique typed owner/object pair for ready uploads, current files, and pending old/new entries. A transaction creates/transfers/deletes retention references with its domain change. Cleanup ownership is recorded separately, not as a self-blocking retention reference. | Anti-join for no retention references before GC; no refcount-only deletion decision. |
| `cleanup_entries` and path tombstones | Stable ID; original resource UUID/path generation; object or owned locator; reason; state; writer epoch; retry/error; scope/charge references. Survive row deletion. A tombstone prevents directory-name reuse until owned cleanup is resolved. | Bounded pending scan; indexes for original scope and object. Unknown files are never adopted as cleanup work. |
| `quota_scopes` and `quota_reservations` | Stable scope key; finite byte/count limits and used/reserved amounts; unique reservation by owner/purpose/scope; nonnegative amounts; explicit release/transfer state. | Lock scope rows in deterministic order; reconstruct counters from reservations to audit leaks. |

Only bounded result/problem documents belong in JSONB here. Actual plans, references, cleanup, and
quota claims are normalized rows. Check constraints express row-local facts; multi-row state and
reference rules are domain transactions with PostgreSQL race/constraint tests. Never claim that
a CHECK constraint enforces a cross-row quota by itself.

Keep deleted object/upload identity tombstones while referenced by retained outcomes; do not cascade
their history with a collection. After successful cleanup, bulky step evidence may be compacted,
but the request key, digest, target identity, and terminal outcome remain. Monitor this DB growth;
finite active-work quotas are not a claim that lifetime outcome storage is bounded.

Fix the extended transaction lock order once:

```text
writer row, shared validation for a mutating transaction; exclusive for handover
  -> catalog advisory lock(s), sorted ID, when required
  -> collection rows, sorted ID (then their file rows, sorted key)
  -> operation rows, sorted ID
  -> upload rows, sorted ID -> object rows, sorted ID
  -> publication-step/reference rows -> removal/cleanup rows, sorted ID
  -> quota scope rows in global, catalog-ID, principal-ID order
```

The relative catalog → collection → upload → removal order is preserved. Locks not needed may
be omitted; no method later goes backwards. Read a candidate ID without a lock, then recheck it
after acquiring the ordered locks. A cleanup scan may select candidates without locking, or
claim only cleanup rows in a transaction that ends before a fresh ordered validation transaction.
All state changes that can release an object or quota claim follow this same discipline, including
expiry, cancel, delete, supersede, and recovery. No transaction waits on filesystem I/O.

### Migration and rollout

Use an additive revision, provisionally `migrations/versions/0004_publications.py`, dependent on
`0003_uploads`. 0003 currently has no staged or unstaged diff; that observation does not authorize
rewriting it. Preserve it and all existing dirty work. Do not fabricate object identity for old
file/receipt rows from their size or inode. The migration must fail transactionally and clearly
if pre-existing file/upload/removal data needs conversion. The default production install is a
new database and empty provisioned lake. Reuse of test-bed data needs a separate, explicitly
owned export/re-ingest or migration decision; there is no automatic reset.

Test empty upgrade, refusal with legacy byte-bearing rows without data loss, schema-map equality,
constraints, and an empty-only downgrade. Refuse downgrade when it would discard operations or
object ownership. Stop/fence old API and tusd writers before migration and code cutover. There is
no mixed-version rolling write deployment and no compatibility path for old commit bodies or
unsafe local state. Preserve unsupported local state and give an actionable refusal, never delete it.

## 5. Lifecycle, retention, and physical publication

### Upload and seal

`receiving -> sealing -> ready -> reserved -> consumed` is the normal upload lifecycle.
Before reservation it may instead become `failed`, `cancelled`, `expired`, or `superseded`.
Terminal upload records retain their reason and any consuming operation identity.

At begin, validate privilege/state/path/declared size/hash and reserve capacity **before** tusd
receives data. The client attempt UUID makes repeated pre-create deliveries refer to one attempt;
real tusd must prove this reuse is compatible with its create behavior. Do not authorize duplicate
filestore writers on the strength of the DB row alone. Every non-OPTIONS tus request still passes
nginx authorization. Initially disable cached mutation allows so cancellation/expiry is not delayed
by a cached allow; an already-running PATCH remains tracked until quiescent.

A new upload begin refuses while its collection has a pending operation. A previously admitted
upload may finish sealing privately, or be cancelled, without changing that operation's payload.
Only objects named and reserved by the accepted plan can reach its public names.

Before copying, persist the object/seal attempt and its unique locators. Check the root and owning
organization marker before the read/copy, not after a receipt. Copy into the private object area
under `.huron-objects/` (0700 directories), with a distinct inode from tusd's source. Sync the file,
close its writable handle, reopen without follow, verify its server hash/size against the expected
upload values, and persist a seal manifest bound to object/upload/attempt and content. Sync the
manifest and parent directories before `finish_seal` records ready. A manifest is not a secret or
a substitute for DB ownership; recovery must match both and hash the named object.

One durable seal attempt and one tracked in-process future own an upload at a time. Duplicate
hooks coalesce on that future within bounded admission, or return its stored state; they do not
start another copy. An expired wait does not replace a still-running sealer. A retry may reuse an
owned incomplete temp only after the old sealer is quiescent, with its charge still held. Otherwise
it must reserve the extra copy capacity before creating another inode. This keeps the 2S budget
honest even during failed copies. Full-byte copy/hash/verification uses the large-work pool, never
the short-disk pool; ownership guards can span awaits, but database transactions cannot.

The sealed inode is immutable **by the service protocol**, not by a claim that chmod revokes open
writers. It is never reopened for writing. Files can use mode 0644 behind private 0700 ancestors,
then be linked into public 2750 directories without changing their content. tusd keeps only its
upload-area access and never receives a sealed-object locator. Narrow its mounted write surface
where deployment supports it. The fixed trusted UID and AUTH_SYS threat limits remain.

Copy-and-seal prevents a later write to a tusd FD from changing a sealed inode. It does not prove
the source was a coherent scientific snapshot while being read. The CLI spool hash must match;
another client is responsible for the content it declares. An incomplete source, hash mismatch,
symlink, or missing seal proof never falls back to hashing the public destination.

### Acceptance, materialization, and finalization

1. Under the catalog admission guard and ordered DB locks, resolve duplicate request identity
   first. For new work validate current permission, settled state, base version, full file tree,
   explicit ready objects, expiry, no pending operation, and all capacity reservations.
2. Persist the immutable entries/steps, reserve the collection, and retain all old and new object
   references in **one transaction**. Set the target version to base + 1 but do not expose it as
   the collection version yet. Audit acceptance separately from the final collection commit.
3. A single materializer applies ordered steps outside transactions, under the writer ownership
   and collection guard. Verify markers, operation reservation, and retained identities before
   each physical unit. Previous objects already have private retained links; never recycle a
   shared backup name or delete the only previous link to make a retry work.
4. For an add/replace: link the identified sealed object to an operation-unique reserved sibling
   temp name, sync the directory, then rename over the expected public old object and sync again.
   A target already linked to this retained new object is a retry, not another replace. Verify
   bytes/size/hash and the retained-object association before acknowledging. A foreign target,
   including one with the same size or hash but no owned association, blocks instead of being adopted.
5. For a remove: retain the old object, verify the public target is that object, unlink, and sync
   its parent before acknowledging. If it is already absent, the journal plus retained old identity
   permits retry. An unexpected target is blocked, not counted as a successful `KEPT` removal.
6. Plan deepest removals and required empty-directory pruning before adds that change a file into
   a subtree or a subtree into a file. Create add parents outermost first with existing inheritance
    checks. After each mkdir, verify the directory's identity, mode, and inherited group, then sync
    its containing directory before creating descendants or acknowledging the step. This includes
    every private object/operation directory created during sealing, before ready is recorded.
    After each rmdir, sync its containing directory before the next dependent step or acknowledgment.
    Existing `make_inheriting_dir` does not perform this parent sync; inheritance checks alone are
    not durability evidence. On retry after interruption, an already-existing directory must match
    recorded ownership and required attributes; an already-missing directory must match the planned
    removal. Re-sync the containing directory in either case before proceeding. Foreign or uncertain
    state blocks. Any required sync failure prevents step acknowledgment, ready, and final success;
    retain the operation for recovery. Never remove an unrecorded child.
    Case-only spelling changes are explicit old-name
   removal/new-name installation steps under the same reservation, not timestamp arbitration.
7. Once all steps are verified and durable, finalize in one ordered DB transaction. Check ownership
   and reservation again, replace file rows, set count/version, consume uploads, write the existing
   commit/audit record exactly once, save the terminal outcome, and clear pending. Transfer quota
   and object references atomically. Only now is 200/success possible.
8. GC later removes unreferenced private objects and operation temps through recorded locators.
   Cleanup never visits an arbitrary public name just because it once had the same inode number.

An accepted operation does not expire. `blocked` retains its reservation, evidence, bytes, and
capacity. A retry resumes that same operation. Missing/corrupt retained data needs operator recovery
from verified backup or a separately approved repair procedure; the API cannot manufacture it or
silently turn a partially applied operation into failure. No user abort is offered after acceptance.

### Cancellation, expiry, supersession, and quotas

Receiving/sealing attempts expire 24 hours after begin; ready objects expire 24 hours after ready.
These are explicit initial policy choices, configurable positive durations. The DB clock defines
expiry (`now >= expires_at`), not mtime or application-clock ordering. Retries/HEAD do not renew it.
At `finish_seal` and acceptance, recheck expiry/state under locks. An in-flight copy that loses to
cancel/expiry may finish only as owned cleanup; it cannot become ready or public.

Before reservation, creator cancellation is idempotent and makes an upload ineligible immediately.
An explicit replacement creation may atomically mark one same-owner, same-collection/key attempt
superseded while reserving the new one. It cannot supersede a reserved or consumed attempt.
Nothing implicitly supersedes another user's object or every earlier upload at a pathname.
A timeout alone neither cancels nor supersedes. The status exposes `expires_at`, eligibility/reason,
`object_id`, `superseded_by`, and `operation_id` when reserved/consumed.

Capacity policy is finite and mandatory for a writable deployment. Operators configure per-file,
global, catalog, and principal byte/count budgets plus a free-byte/inode safety reserve. There is
no production `0 = unlimited` setting. Limits are checked transactionally, not estimated from a TTL.
The prototype uses scaled limits; production values require the measured workload and storage budget.

| Transition | Accounting rule |
| --- | --- |
| Begin size S | Reserve 2S physical bytes for tusd source plus independent sealed copy, and upload/object counts in every scope. Zero-byte uploads still consume counts and inode budget. Reject before bytes if any scope is full. |
| Source fully removed and its writer proven closed | Release the source S portion only after unlink/directory sync and quiescence evidence. A missing pathname alone does not free capacity while an FD may still hold or grow data. |
| Ready -> reserved | Transfer the object claim to the accepted operation with no gap. Retain old-current objects; no physical byte discount for pending replacements. |
| Finalize | Transfer new S from staging to live ownership. Old live bytes become retained cleanup charges, not immediately free bytes. Adds/removes update logical file count exactly once. |
| Cancel/expiry/failure/supersede | Eligibility ends now; physical charges remain until cleanup actually completes. New work cannot reuse the old reservation while an old writer may continue. |
| GC completes | In one ordered transaction verify no retention reference and mark `gc_pending`, which forbids new references. End the transaction. Unlink only that object's private names and sync. In a new ordered transaction mark deleted and release exactly once. Crash before accounting release leaks capacity conservatively; replay repairs it. |

Reserve a finite extra directory/manifest/temp-entry allowance per object and operation. Count each
physical inode's bytes once globally even if several references retain it; scope attribution does
not disappear when a user or collection is deleted. Treat a statvfs safety check as a second,
conservative guard, not as protection from other users of the export. ENOSPC, EDQUOT, and inode
exhaustion remain mapped failures. Existing accepted work gets reserved recovery capacity; a full
queue or cleanup backlog rejects new work rather than evicting its objects.

## 6. Crash and interruption matrix

Each row needs a real-filesystem/PostgreSQL process-crash probe at both sides of the boundary.
Local process death does not prove host power-loss or ONTAP durability.

| Last durable boundary / interruption | Permitted recovery and observable outcome |
| --- | --- |
| Begin committed; tusd file absent or partial | Same attempt remains receiving or expires; no public change. Do not inspect a public destination as evidence. |
| Object row exists; copy incomplete | Keep private data charged. Resume/restart only that owned seal attempt after quiescence, with exclusive temp creation. |
| Data synced; manifest absent/incomplete | Not ready. Revalidate owned source/object or quarantine for cleanup; never publish. |
| Complete synced seal manifest; ready transaction lost | Match DB attempt, manifest, locator, full size/hash; finish ready idempotently if still eligible. Cancel/expiry wins otherwise. |
| Ready committed; hook response lost | Status returns ready and exact eligibility. No public effect occurred. |
| Commit request lost before DB receipt | Status missing; retransmit same ID/payload. An unrelated version increase cannot imply success. |
| Semantic refusal committed; response lost | Same request returns the same refusal; previous public bytes remain. Rebase needs a new request ID. |
| Accepted plan committed; worker has not run | Pending collection and retained references survive. Recover the same operation; no competing mutation. |
| Public-parent or private-directory mkdir done; containing-directory sync absent | Verify recorded ownership and attributes if already present, or recreate the owned missing directory. Sync its container before descendants, ready, or step acknowledgment. Sync failure blocks progress. |
| Planned empty-directory rmdir done; containing-directory sync absent | Verify the recorded removal; already absent is an idempotent retry, not proof of durability. Sync its container before dependent steps or acknowledgment. Unexpected children or identity block. |
| Temp link made/synced; replace not done | Verify owned temp/object and expected old target, then continue. Do not replace a retained old object with a new backup. |
| Replace/unlink done; directory sync or step acknowledgment absent | Inspect owned old/new object associations and journal; sync and reapply idempotently. Unexplained state blocks. |
| Some entries acknowledged; process dies | Keep the collection pending; roll forward remaining entries. Direct readers may already see a mixture. |
| All physical work done; finalize transaction lost | Recheck complete physical evidence, then finalize once. Do not increment version/audit twice. |
| Finalize committed; HTTP response or local CLI save lost | Exact request status returns its saved success. Reconcile the matching local intent generation atomically. |
| GC unlink done; DB release lost | Retry sees that owned object absent, completes accounting once. It never touches a newer public file. |
| DB connection lost or NFS thread hangs | Stop scheduling new physical work. An already-issued syscall may complete. Reservation stays; replacement waits for quiescence or external fence. |
| Old process resumes after lease loss | It cannot authorize another step/finalization. A new writer must not yet exist unless the old process was externally fenced. Lease expiry alone fails this test. |

## 7. Metadata, repair, groups, deletes, and ownership

One writable process does not remove in-process races. Add a catalog mutation guard shared by
commit acceptance, every public file step, directory verbs, schema assignment, share-group change,
repair, and cleanup. Acquire process guards before starting DB transactions. When multiple scopes
are needed, take organization structural guard, then catalog IDs, then collection IDs in stable
order. Never wait for a process guard while holding a DB transaction.

A file operation releases the catalog guard between bounded steps but retains its durable collection
reservation. Another collection's safe work may run. Metadata/override/delete on the pending
collection refuses `COLLECTION_BUSY` (409). Catalog schema assignment, share-group changes, and
catalog-wide repair refuse `CATALOG_BUSY` if any affected collection is pending; they do not apply
half of a DB change first. Catalog and namespace deletion also check reservations/tombstones before
changing rows. A repair that includes a pending target refuses before running its steps; unaffected
targets can be repaired separately. No fourth repair failure reason is invented for scheduling.

Retain the narrower existing semantics for ordinary metadata/directory verbs: rows commit first;
a disk failure keeps rows and requires repair. Hold the catalog guard across the DB change and
physical work. Re-read current identity/version/schema/group under that guard before each step.
Repair plans enumerate resource IDs from the DB, but a captured `share_group` is not authoritative
later. `Repairs.expected` must return current catalog identity/version/group and current rendered
metadata; gone/recreated resource IDs are skipped, never matched merely by reused pathname.
Use unique metadata temp names and file/directory syncs. Repair remains idempotent, DB-planned,
non-recursive on disk, and preserves exact error paths and the three existing failure reasons.

This does not turn every metadata write into a new durable job. If its process dies after the DB
commit, a later repair renders the current rows. It cannot overwrite a later version because all
writers use the same guard and stale old processes are fenced. Catalog grant changes do not change
disk groups. Revocation affects future acceptance, not an already accepted file operation.

File removes belong to the commit journal and must finish before its success. Keep the durable
removal/outbox principle, but replace inode-only public cleanup with object/operation identities.
Collection delete still requires an empty file set and no pending operation. Its DB transaction
cancels unreserved uploads, records cleanup identities and a path tombstone, then deletes the row.
Directory cleanup waits for its owned uploads/sealers to become quiescent. Retained operation
outcomes/cleanup survive deletion. Name reuse is blocked until cleanup has finished. A `KEPT`
result for unknown entries preserves the tombstone until the operator resolves the obstruction
under maintenance ownership; an unknown nonempty directory is not auto-adopted for a new resource.
Namespace/catalog/organization deletes use the same tombstone discipline for their owned empty
directory effects. No recursive purge, no arbitrary suffix-based backup deletion, no unknown data loss.

GC selects DB-owned identities in bounded batches. A shallow upload listing is only an inventory
for reconciling known tusd artifacts. Do not delete active `.lock`, `.stop`, `.info`, or data files
by mtime. The real-tusd probe must prove safe per-upload termination/deletion after request closure;
otherwise retain them until a drained/fenced tusd maintenance window. Unknown artifacts are
reported/quarantined for the operator, never silently reclaimed.

## 8. CLI durable state and source policy

Select **copy-on-add local spooling**, not a mutable source path at push time. `huron add` copies
the selected bytes to a new private local inode, hashes them, syncs the data and its directory,
then atomically references that spool in the working-copy state. Push/resume always sends that
spool and compares the server hash. A later source edit requires another explicit add. A hard link
to the user's source is not a snapshot. Do not restore share copying: this spool is local state.

The source must be quiescent while add reads it. Compare descriptor/path identity, size, mtime and
ctime before/after and check EOF; refuse observed changes. This detects many edits, not every
same-size concurrent write and not a coherent multi-file snapshot. Applications must close or
snapshot their source themselves before staging if scientific consistency requires it. State this
limit in help; never advertise a copy as a filesystem snapshot of an actively modified source.

Use one state-root mutation lock initially, encompassing every local write: add, rm, pull,
checkout/context/config changes, metadata drafts, push progress, token-state changes, and cleanup.
This coarse local serialization is deliberate for roughly 50 users on separate workstations; it
does not serialize different users. Acquire it **before** resolving current context or reading
copy/stage state. No separate local command may mutate it during a push. Readers use one atomic
state generation. Keep the lock file stable; do not unlink it or steal it by age/PID.

Replace split `copy.json`/`stage.json` updates with a versioned atomic working-copy record holding
base version, stage, spool references, attempt IDs, pending request UUID/payload/digest, and local
generation. Use unique exclusive temp files mode 0600, file fsync, atomic replace, directory fsync.
Store a push intent before sending any operation request. Freeze that payload through uncertain
outcomes. On restart resolve its exact status **before** pulling a new base or reusing uploads.
Only success for that ID clears its stage and advances its base in one durable state replace.
Rejected/blocked/unknown outcomes retain intent. A changed payload after terminal refusal gets a
new ID; consumed uploads are resolved through their operation, not submitted again as ready.

Any local command that would change that working copy's stage or base first resolves its pending
request. If the outcome is still unknown, accepted, or blocked, refuse that mutation without
clearing the intent; status/resume remain available. Switching context may select another working
copy, but must preserve the old copy's pending record and spools.

Attempt timeout preserves URL/IDs and exits with a pending explanation. A later push resumes or
polls the same attempt. Explicit upload restart first supersedes/cancels through the server and
records both identities; an old hook completing afterward remains private and ineligible.
Expired objects require a new upload from the same spool, not an endless reuse loop.

Require finite spool byte/count limits and a free-space reserve, checked under the same lock before
copying. Existing plus temporary copies both count; keep the old staged spool until new state is
durable. ENOSPC/fsync failure preserves the old state. Reclaim only unreferenced owned spools after
state recovery; never delete an unresolved push's data or the user's source. Cross-filesystem spool
placement and unsupported old state fail with instructions, not a silent unsafe fallback.

## 9. Operational bounds and writer replacement

Initial production topology: one writable API **process**, one worker process in its server, one
tusd process, no auto-scaling writable fleet. A startup DB ownership record/advisory lock prevents
ordinary duplicate starts, but cannot authorize takeover after connection loss. Store a writer
epoch and an operational handover record. Once ownership is uncertain, stop admitting mutations
and do not reacquire it automatically. Optional read-only API replicas can serve browse/status,
but have explicit mutation denial and cannot run bootstrap reconciliation, recovery, or GC writes.

Replacement procedure:

1. Stop mutation admission and new tus requests; mark writer readiness false. Track running hooks,
   uploads, filesystem futures, materialization steps, and DB finalizations independently of HTTP.
2. Drain accepted work and tusd requests within an operational deadline. Keep DB/storage resources
   alive until tracked work has completed or been handed to recovery. Dispose resources acquired
   during failed startup in reverse order, including an internally opened PostgreSQL store.
3. If any old API or tusd accessor is uncertain, fail closed. Removing it from a Service, deleting
   a pod object, SIGKILL delivery, or `shutdown(wait=False)` is not proof it cannot later write.
   An operator must prove process death with no surviving filesystem work, or fence the old node's
   access to the export by an externally verified mechanism. NFS in-flight RPCs require storage-side
   confirmation, not just a new DB lease.
4. Only after that evidence may the new owner use a new epoch, clear identified stale tusd locks,
   recover seals/accepted operations, reconcile charges, and resume admission. `Recreate` is useful
   deployment configuration, not the fence itself. Failure to fence means a write outage.

Keep four large-copy/hash workers and eight short-disk workers as initial hypotheses, not capacity
proof. Bound waiting before submitting to either executor. Reserve one short-disk lane for a single
readiness probe; never enqueue repeated probes behind a hung one. Give recovery priority without
letting its queue grow unbounded. Production configuration must supply finite pending seal count,
short-work count, accepted-operation count, and request-body/concurrency limits. Use immediate 429
for quota/admission exhaustion (with retry guidance), and 503 for unavailable writer/storage.

Set one 2-second total monotonic readiness deadline covering pool acquisition, DB ping, key reads,
and the lake probe. Cached lake results can be at most 10 seconds old, with their age visible;
an observed failure/ownership loss invalidates success immediately. No expired success is returned
when a new probe hangs. Set the deployment probe `timeoutSeconds` to 3, period to 5, and failure
threshold to 1 initially; test timings with scheduling tolerance. Liveness does not attempt NFS I/O
or promise safe automatic restart. Queue bounds do not make a blocked kernel syscall cancellable.

Metrics/logs must expose: admitted/rejected uploads and reasons; reserved/live/retained bytes and
counts by bounded scope; queued/active hashes and disk units; oldest pending/blocked operation age;
cleanup backlog; free-byte/inode reserve failures; readiness dependency latency/cache age; drain
state; ownership/fencing refusal; recovery attempts/outcomes. Correlate by request/operation/upload
ID, never token or full credentials. Alert on blocked publication and accounting disagreement.

Provision **before** starting writable service: generate root/organization instructions offline
from explicit instance ID, API URL, organization declarations, lake path, UID, and GID. Reuse
`Provisioner` rules, not a second layout implementation. This removes the current startup/health
dependency cycle. The storage administrator verifies markers and ownership, then starts the writer.
Catalog group provisioning and any other administrative disk write require drained ownership and
a fresh versioned plan; do not run stale scripts concurrently with group changes or publication.

### Workload hypotheses, not demonstrated capacities

The intended site is about 50 scientists, with occasional parallel pushes, a few large files,
and bursts of many small files. Measure rather than promise throughput. The local probe covers
50 identities, 8 simultaneous transfers, queue saturation above 4/8 workers, zero-byte files,
64 MiB chunk boundaries, and the 10,000-entry limit. A later owned acceptance harness must test
the operator-selected largest file and aggregate budget on representative hardware.

Copy-and-seal costs an additional full read/write plus sealed-byte verification and up to 2S
temporary physical occupancy while tusd's source remains. Current public data, retained old bytes,
manifests, and ONTAP snapshots add further space pressure. No throughput number or largest-file
support is proven here. Admission values must fit measured storage and recovery time; missing
values block writable startup. Avoid deduplication and compression as speculative scope additions.

## 10. Rejected alternatives and change sequence

| Alternative | Why it is not selected |
| --- | --- |
| Keep backups longer, otherwise keep pre-finish publication | Still changes public bytes before acceptance; delayed/duplicate attempts can corrupt backup ownership. |
| Use DB timestamps for latest placement | Row order does not establish filesystem effect order. |
| Hard-link tusd inode and chmod it | An existing writable descriptor can mutate the inode. Copy-and-seal is the default unless a later real-tusd proof justifies a reviewed optimization. |
| Singleton only | Does not solve late hooks, rejected commits, crash windows, or local-state loss. |
| DB transaction held across NFS | Can hold locks/pool connections forever and still cannot commit DB and FS atomically. |
| Lease expiry enables another writer | An issued old syscall can complete after expiry. |
| Infer lost response from version/hash/removes | Even checking removes cannot identify which request caused the state. |
| Roll back a partly published commit automatically | Adds ambiguous compensation and requires old ownership proof; roll-forward retains one immutable accepted plan. |
| Directory-generation/symlink switch | Changes the direct-reader contract, violates the no-symlink rule in that form, and is outside the approved focused correction. |
| Full filesystem repair walk or success-only MemoryStorage | Contradicts the explicit M11.5e resolution and obscures exact failure behavior. |

Reviewable sequence, **not executable phase instructions**:

1. Independent architecture review, then isolated prototypes and independent evidence review.
2. Plan durable request/object/reservation persistence and contracts, preserving all existing dirt.
3. Plan private sealing, bounded execution, and storage error-matrix extensions together with
   their actual callers. Remove public pre-finish placement and same-size replay, not containment.
4. Plan accepted publication/recovery/finalization, identity-bound removal/GC, and mutation guards.
   Replace latest-placement selection and inode-only public cleanup; keep accounting/lock tests.
5. Plan CLI atomic state/spools/exact outcome recovery. Remove timeout-forget, consumed-upload reuse,
   version inference, fixed temp files, and obsolete copy-absence tests only in an owned test slice.
6. Finish and qualify the preserved repair resolution, CLI repair/group features, drift checks,
   offline provisioning, runtime drain/readiness, and observability.
7. Add real tusd/nginx integration and an explicit durability/workload acceptance harness. Replace
   the existing skipped CLI integration test with real coverage, not another skip.
8. Deliver owned deployment changes, operator/user documentation, and external ONTAP qualification.
   Preserve the exact pending M11.12 documentation obligations and M11.13 external prerequisites.

Each future phase needs a self-contained file, exact symbol/file ownership, no compatibility by
default, baseline, complete gates, and serial independent maximum-profile review. Actual code/fixes
require a new exclusive `activity: code`, maximum-profile dispatch. This planning dispatch cannot
authorize them. The [prototype specification](m11-review-evidence.md) is the next bounded work input.

## 11. Remaining review and external gates

Engineering choices above are explicit proposals, not unanswered product questions. Independent
review must test their consistency before phase writing. The following cannot be settled by prose:

- A prototype must prove the local state/crash model and current counterexamples on real filesystem
  and private PostgreSQL. No probes have been written or run in this pass.
- The asset owner must supply pinned tusd/nginx images offline. Real handoff, duplicate pre-create,
  final PATCH timeout, source FD lifetime, auth-before-body, and safe cleanup are not proven.
- The storage/operator owner must approve the actual single-writer outage/fencing runbook and
  demonstrate ONTAP security style, setgid inheritance, AUTH_SYS behavior, directory/data sync
  semantics, client-cache effects, and hard-NFS outage/replacement safety on an owned export.
- The site owner must provide representative maximum-file/aggregate workload and disk budgets.
  These are deployment qualification inputs, not a reason to leave protocol decisions unspecified.
- Workflow/skill asset drift is parent-owned. Missing `asd-ste100` and `writing-for-agents` are
  recorded, not fetched. Nonexistent acceptance targets are not treated as passing gates.

If strict all-file snapshot visibility, overlapping writable replicas, or continuing service without
an external fence is required, stop for a new approved design. Do not quietly broaden this one.

## 12. Dated handoff update (2026-11-09)

Architecture preparatory review1 (`ses_e41912c8effefzK43sk1bh9L4w`) returned FAIL for the
destructive prototype database helper and missing containing-directory sync after mkdir/rmdir.
Planning fix `ses_e418f28b5ffe4YOAVFr7gf3YAW` corrected those contracts without product edits.
Preparatory review2 (`ses_e418d3df1ffemcl49SpFu2Fxh7`) returned PASS for the bounded architecture
and prototype handoff. It was not a complete maximum-profile product/design qualification.

Prototype attempt1 was blocked by absent loopback port publication on its private internal
Docker network. After parent-authorized access to the same private bridge endpoint, attempt2
produced narrow observations. Its first review failed the resource-manifest directory-sync
claim despite a successful rerun. The fix added both required directory syncs, fault assertions
and run-specific verification. Preparatory review2 (`ses_e41701208ffeePja0AkjkcfOrw`) returned
terminal PASS for that bounded evidence. The durable receipt preserves exact commands, hashes,
results, resource identities, failed attempts and evidence limits.

The actual scope is smaller than the original prototype specification in this architecture:

- Real Placer/PosixStorage replay and backup-drop primitives, not a complete PG rejected commit.
- Actual two-process StateDir lost intent and actual `_recover` with remote API answers faked,
  not complete command/crash coverage.
- Tiny real PG/filesystem model with six **logical interruption/reconnect** cases, retained old
  bytes, request/reservation conflicts, and foreign-inode blocking; eligibility is a pure model.
- Two allocation-directory fsync faults proved no probe DB allocation. No process-kill,
  power-loss, NFS, full application protocol, runtime bounds, or workload claim follows.

Thus section 9's workload list is **intended qualification coverage**, not an executed local
probe result. Section 11's “no probes ... in this pass” describes the initial writer's pass;
the later bounded experiment is recorded above. Unexecuted original cases remain mandatory
prerequisite or pre-release acceptance in the replacement plan, never implicitly passed.

The selected direction remains private copy-and-seal, request/object identity, accepted
reservation before public effects, retained old/new objects, roll-forward, finite admission,
single fenced writer and atomic local spooling. The replacement plan enumerates only the unsafe
M11/D-7/D-8/amendment supersessions; it preserves the old plan unchanged, every unaffected rule,
the M11.5e full-adapter/error-matrix/RepairFailureOut resolution and all 19 M11 obligations.
No containment escape was found. No live code/config/test or ignored probe was changed by this
handoff update.

Next action is **independent maximum review of the replacement plan**, then scoped baseline
and its prerequisite validation slices. Directory-ownership crash replay, real tus creation/
cleanup, local-state deadlines and runtime ownership still need their stated evidence before
code readiness. Actual application process-crash/duplicate-runtime tests are release gates.
Offline tusd/nginx/Helm assets, actual ONTAP setgid/security-style/AUTH_SYS/durability/fencing,
and site workload/budget inputs have named owners in the plan. They are not deferred beyond
production qualification. The stopped probe's data remains parent-owned; no cleanup is authorized.

This update records review outcomes and links, not independent acceptance of its own prose.
Design validated, plan ready, implementation complete and production qualified remain separate.

## 13. Replacement-plan review1 correction proposal (2026-11-09)

Maximum plan reviewer `ses_e414a07b4ffeiXZm8gPW2sUSqu` returned **FAIL**, not acceptance.
Planning fix1 is preparatory Low, writer-fixed **awaiting maximum review2**. This section and the
replacement plan's §3.5/P07 correct the reviewed proposal; they are not new prototype evidence.

### Executable interlock transition

P07 must close the ordinary PostgreSQL runtime without breaking the required real-PG integration
gate. The current test_api_postgres workflow constructs build_runtime directly and then performs
organization/grant/catalog/namespace/activation/legacy commit mutations. Merely scheduling its
conversion at P27c made P07 impossible to accept. P07 now owns a temporary tests/support/legacy.py
constructor that explicitly assembles existing domain/runtime collaborators on its isolated PG
store, and a tests-only ASGI mutation dependency override. It uses actual routes/auth/PG semantics,
not fake success or a production setting. Production build_runtime and create_app remain closed;
memory-test still requires MemoryStore. No source imports tests or exposes a legacy-write switch.

P07 switches that integration constructor while preserving its behavior assertions; direct PG
domain/bootstrap tests remain direct. Production runtime contract tests exercise disabled startup
with explicitly preseeded disposable fixtures and no startup writes. All memory helpers/harness
callers select memory-test explicitly. A caller inventory covers tests/scripts/web/docker seed and
blocks acceptance on an unclassified caller. P08–P26 test new collaborators directly; P27a mounts
the new journal router in separate tests, P27b moves CLI callers, P27c moves the PG integration to
the real journal app and deletes the temporary constructor/override. P28 then removes old adapters
and tightens schema after direct fixtures convert. No coverage, gate, threshold or role assertion
is waived. This is an unreleased test staging exception, not backward compatibility.

### Exact recovery includes authenticated instance and principal

Persist immutable `RecoveryBinding(instance_id, subject, api_endpoint, uploads_endpoint)` in every
working copy, upload attempt and pending commit before effects, including empty/removal-only work.
The server key remains actor/request per instance. A UUID and payload alone cannot distinguish
logout/login as another user or a different instance at the same URL.

The proposed authenticated GET `/api/v1/auth/recovery-identity` returns the persisted/validated
instance UUID and exact Actor.subject in one response. Today only configured instance_id on
unauthenticated /healthz and subject on /auth/whoami exist; neither a new route nor durable binding
is claimed implemented. P09's additive 0004 creates an empty singleton service_identity table;
P11 supplies insert-once initialization/read ports and PG/memory adapters; P16 refuses missing or
configuration-mismatched identity. P31 adds an explicit offline server-admin initialization script,
separate from the CLI (which cannot import metastore). Tests initialize their assigned DB directly
through P11, avoiding a dependency on that later script. Configuration, DB and provisioned marker
UUID must agree. Restores preserve identity only with complete history/objects; new history uses a
new UUID. No startup upsert, auto-rebind or random per-process ID is allowed.

Before status/upload resume/cancel/retransmit, P23 resolves/canonicalizes the effective connection,
compares saved approved destinations LOCALLY, validates credential issuer/client/API provenance,
then permits refresh, authenticated identity inspection and finally the bound request, in that order.
No token callback or credential-bearing identity/refresh/exchange request precedes local trust.
TLS host authentication does not approve a credential audience. Refresh invalidates
that verification. P27a checks expected UUID/subject headers before lookup/effects; the subject is
base64url-encoded UTF-8, not a login/display-name comparison. Wrong binding returns 409, missing/
malformed binding 422, never replay-authorizing 404. Upload authorization forwards/checks them too;
P05/P06 must freeze its actual proxy/tus propagation. Views echo binding for CLI validation. These
checks close the inspection/request race; a caller's claimed header never grants authority.

Canonical endpoints require verified HTTPS in production, no credentials/query/fragment or
redirects; lowercase scheme/IDNA host, remove default port and trailing slash, preserve base-path
case and reject ambiguous paths. Test/dev loopback HTTP is not a production equivalent. Changed
canonical API/upload bases require explicit same-instance/same-subject endpoint acceptance under
the state lock; URL overrides alone cannot authorize it. The new P27b `huron context accept-endpoint`
command obtains informed destination approval BEFORE authentication, then uses fresh destination-
specific login, never the old bearer/refresh credential. Only verified same instance/subject permits
atomic endpoint acceptance, never changing IDs/body/intent. Abort/failure preserves previous state.
Stored upload/status locators stay within the explicitly approved bases; do not forward tokens to
arbitrary absolute URLs. A cross-origin upload base requires explicit approval. Another principal
must sign back in as the original; another instance needs a separate checkout, not rebind. Mismatch,
unavailable identity or malformed responses preserve spools and pending intent for reconciliation.

P03 tests the candidate namespace/endpoint matrix; P22–P26 implement durable values, validation,
spool preservation and exact recovery; P27a/P27c own API schema/registry/snapshot consumers;
P27b connects whole commands; P29 repeats the matrix with actual CLI/PG processes, including
removal-only work and same-URL replacement. P06 freezes these interfaces and staging contracts
before downstream code. All 42 slices, 19 M11 tasks, F1–F7 and O1–O16 remain represented. No new
probe was run and no global design-ready, implementation-ready or production claim follows.

## 14. Replacement-plan review2 correction proposal (2026-11-09)

Maximum reviewer `ses_e41375e91ffeReJef3Uy9rhbnM` returned FAIL. Review1's P07 transition and
instance binding were resolved, but trust-before-authentication and exact command registry ownership
were not. Fix2 is preparatory Low planning, pending final maximum review3 (maximum three reviews).

The plan §3.5 now governs credentials for ordinary API calls as well as recovery: Services freezes
the selected connection; ApiClient checks the actual destination before calling Session.token;
Session checks approval and stored provenance even when the bearer is not near expiry. P23 owns
versioned TokenState replacing state.py's current Tokens, approval persistence, Session/Oidc and
CLI errors. API/issuer/client/upload selection changes refuse reuse/refresh. Legacy unbound token
files are preserved and refused until explicit fresh login; no provenance inferred from settings.
First login displays and requires approval of destinations/issuer/client before authentication.
Trusted-issuer discovery is credential-free, issuer-matched, HTTPS and same-origin; off-origin
provider endpoints require separate explicit approval. Changed discovery cannot silently redirect
refresh. No automatic HTTP redirect or cross-origin credential forwarding, including company-token
exchange bodies. This is a bounded CLI seam correction, not a generic broker/web security rewrite.

Endpoint acceptance uses provisional informed approval and fresh destination-specific credentials.
Only same-instance/same-subject verification publishes new approval/credential and working endpoint
generations together via P22's atomic transaction manifest. Failure/abort keeps old active state;
crash recovery selects a complete old or new generation. IDs/body/stage/spools remain unchanged.
Switching back may use a still-matching approved credential; otherwise fresh login is required,
never a new working namespace or automatic rebind. P03/P23/P25/P27b/P29 must observe no bearer,
refresh or company token sent to an unapproved host across valid/expiring credential, URL override,
issuer/client/discovery-change, ordinary API, login, abort and recovery cases. No probe proves this yet.

P27b explicitly owns commands/__init__.py::LAYOUT, placing context after config in Settings;
commands/context.py::register retains root org/catalog and adds the context group exactly once.
It owns test_panels.py expectations/help/registration coverage and generated reference, with all
GP/GD gates unchanged. The strict cli_reference layout guard is not weakened. All 42 slices,
19 M11 tasks and F/O traceability remain; no product or global-ready verdict is made.

## 15. R3-1 development credential-producer reconciliation (2026-11-09)

Maximum plan review3 `ses_e412ba125ffeV3Y9o1hLnuYhTi` returned **FAIL**. It confirmed the earlier
corrections but found the external token writer unowned. scripts/dev-login.sh still password-grants,
exchanges, and truncates a legacy four-field tokens.json; e2e and the persistent NOAA demo source
it. Historical M11.11 also injects a host token into pod state. Changing only the JSON fields would
not supply destination approval, fresh provenance, the root lock or a durable state transaction.

The selected correction is **replace the shell helper with repository-only scripts/dev_login.py**.
No old wrapper/positional-password alias survives P27b. P23 builds it using the same new CLI
FreshLogin, DestinationApproval, CredentialStore, LocalState and recovery-identity collaborators.
The adapter's `DevelopmentPasswordGrant.acquire(approved) -> CompanyTokens` is the only new password
grant implementation. It is not installed in the production CLI or implemented in broker/API code.
Its public interface is future, not a current API:

```sh
uv run --offline --no-sync python scripts/dev_login.py --username USER --api-url API_URL --issuer ISSUER --client-id CLIENT_ID [--uploads-url UPLOADS_URL] [--approval-file APPROVAL_JSON] [--password-stdin]
```

Require explicit absolute XDG_CONFIG_HOME and XDG_STATE_HOME; the helper changes credential state
only. Required endpoint/client options are candidates, not trust. Omitted uploads means None, not
implicit approval of a health-response upload URL. P23/P27b add the explicit uploads_url config key
and HURON_UPLOADS_URL selection; ordinary file/env/global precedence still grants no approval.

Interactive trust is default-decline and separate from ordinary --yes prompts. Noninteractive trust
requires an explicitly supplied, owned 0600 no-follow regular JSON file, at most 16 KiB, with exact
version-1 fields: purpose=`development-login`, api_endpoint, uploads_endpoint (or null), issuer,
client_id, token_endpoint and allow_loopback_http. Reject duplicate/unknown keys and any mismatched
canonical destination; no wildcard or origin-only approval. The new scripts/dev-auth.example.json
documents this schema but is never automatically consumed. An operator/test owner reviews and
supplies its exact tuple; scripts cannot derive approval from config, discovery or an old token.
Loopback HTTP is a deliberate development-only allowance for literal loopback, not insecure TLS
or arbitrary HTTP; production remains verified HTTPS without redirects.

Ordering is invariant, including valid/expiring stored tokens:

1. Acquire the stable root mutation lock before reading state/selection. Validate local candidate
   trust before any credential-bearing request. Fetch discovery without credentials only from the
   approved issuer; require matching issuer and approval for the full provider endpoint. A changed
   or off-origin endpoint is not implicitly trusted; interactive approval or the exact reviewed file
   must cover it before use. Device/browser adapters approve their corresponding endpoints too.
2. Only then read a password from no-echo terminal or explicit bounded stdin, and acquire fresh
   company credentials. No password/token in argv, environment values, shell trace, output or logs.
   Repository workflows open an owned password file and redirect stdin, not curl form arguments.
   Never reuse, refresh or forward the previous credential during this fresh-login transaction.
3. FreshLogin.prepare performs checked exchange at the approved API and authenticates the proposed
   recovery identity with the candidate Huron token. Verify returned subject against exchange, not
   a username hint or JWT decode. Only then form LoginCandidate/TokenState with real provenance.
4. CredentialStore.save uses P22's manifest transaction under the same lock. Plain login changes
   credentials only; endpoint acceptance additionally requires the same saved instance/subject and
   atomically selects credentials/approval/working endpoints together. Login cannot rebind intent.

Declined approval, invalid discovery, failed auth/exchange/identity or uncommitted save failure
preserves previous approvals, credentials, attempts, stage/base, drafts and spools. Absent or owned
malformed/legacy credential files can be replaced only by explicit successful fresh authentication;
they cannot be decoded or stamped with current settings as provenance. Unsafe ownership/mode/link
or corrupt transaction manifest refuses without overwrite. Keep prior generation bytes through
interrupted save/recovery: before commit use old; after durable commit recover the complete verified
new credential selection. Never report an uncertain sync as success. Working intent survives either
outcome; identity changes still refuse recovery until the original actor/instance is restored.

### Acyclic implementation and caller ownership

- **P22:** generic credential-only/combined endpoint atomic primitives, stable root lock and real-FS
  fault/concurrency tests. No dependency on authentication or a future route.
- **P23:** new credentials.py values/protocols/approval/store, login.py FreshLogin and device/browser
  adapters, identity/state/config collaborators, scripts/dev_login.py entry/adapter/FileApproval,
  tests/unit/test_dev_login.py and tests/support/devauth.py using controlled network identity
  responses. Keep new collaborators unconnected until the one cutover; no production bypass.
- **P27b:** remove scripts/dev-login.sh and legacy credential APIs; switch CLI, e2e.login_as,
  demo-noaa before its first read, test Cli.login_as/Stack.login, and active instructions/targets.
  Own README, examples/noaa README/load guidance, Makefile demo-noaa, auth/state/pre-release text
  in docs/architecture, user-guide and operator. Positive fixtures use fresh auth, not direct mint
  plus invented provenance. Test actual helper then real CLI against P27a's isolated real router.
- **P27c/P29:** retain the real-PG composition transition/deletion and full application/process-crash
  gates. Include helper-vs-CLI lock races and interrupted credential-only/endpoint saves.
- **P33:** complete real PG/API/nginx/tusd/IdP every-role e2e and NOAA first load plus unchanged cached
  NOAA_RAW offline rerun on persistent isolated state. No downloads, skips, destructive shared-stack
  teardown or syntax-only acceptance. Compare versions, rows, hashes, metadata and commit counts.
- **P34:** separate approved host and in-pod fresh login using the same helper (local-only ConfigMap
  mount, not production packaging), private XDG state and stdin secrets. No host token copying or
  raw JSON injection at the pod API base. Keep actual upload/overwrite/empty/remove/check/restart smoke.

The phase plan §3.5 defines exact symbols, file/input schemas and the full public-behavior matrix;
P23/P27b/P33/P34 define exact gates, including arbitrary-script Ruff/format/mypy/ty checks absent
from today's make gate. Tests observe **zero credential delivery at unapproved endpoints**, not
private call counts, with valid/expiring state, first/failed/declined auth, destination/issuer/client/
discovery/provenance changes, identity switches, contention and interruption. Reuse FakeIssuer,
ScriptedPrompter, Cli transport/clock/scoped fixtures; retain real PG/FS tests. Broker/web sessions
and ephemeral seed tokens never write CLI state and are classified separately, not redesigned.

Reconciliation writer attempt1 is implementation/planning, configured maximum, dispatch
74172ff5-25cb-4bbc-b53a-e76fab96563e, model openai/gpt-6-astra; provider effort is not-proven.
This is a writer proposal, not independent review. The user's later one-time exception allows
the parent to dispatch ONE independent maximum review after writer terminal, no automatic retry;
the original three failures and phase-plan §12 historical receipt remain. No new probe/test/service
ran. All 42 slices, 19 mappings, F/O traceability and earlier binding/P07/context corrections stay.
Missing canonical language/instruction skills and all external evidence blockers remain recorded.
