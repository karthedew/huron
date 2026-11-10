# M11 plan 2: safe publication on the server

Read [M11_PLANS.md](M11_PLANS.md) first. This plan fixes defects F1 to F6 on the server.

## The defects

| ID | Defect in the current code | Result that this plan requires |
| --- | --- | --- |
| F1 | A refused or abandoned overwrite can lose the committed bytes | No public byte changes before a commit is accepted |
| F2 | The newest placement wins by timestamp | A commit names each upload by ID |
| F3 | A replay accepts other bytes of the same size | Only a sealed object with a server hash can be published |
| F4 | An upload that timed out can complete late and change public bytes | A late completion stays private |
| F5 | A lost answer is resolved by inference from the version | The server saves the outcome of each request ID |
| F6 | An expired or consumed upload can be used again | An upload has an explicit state and one consumer |

## Design

This section replaces decisions D-7 and D-8 of `IMPLEMENTATION_PLAN.md` and the upload flow of its
uploads amendment. All other rules of sections 3 to 9 stay: `LakePath`, no-follow traversal, the
one `Storage` port, the full `MemoryStorage`, the two pools, the marker checks, RBAC, naming bounds.

### Objects

- When tusd finishes an upload, the API copies the bytes into a new file in a private object
  area. The API syncs the file, opens it again, and measures the size and the SHA-256.
- The sealed file is never opened for a write again. tusd can keep a descriptor on its own file.
  That descriptor cannot change the copy.
- The object area must be on the same filesystem as the collection, because publication uses a
  hard link. Organizations can have different roots. Task S1 records where the object area is.
- The API publishes with a hard link to a unique temporary name, then a rename over the target.
  Huron creates no symbolic link.

### Uploads

- States: `receiving`, `sealing`, `ready`, `consumed`. End states before a commit: `failed`,
  `cancelled`, `expired`.
- The client sends an `attempt_id` (UUID) at creation. The same `attempt_id` with the same fields
  gives the same upload. Different fields give a conflict.
- An upload expires `upload_ttl` after its last activity. Activity is a received chunk or the end
  of a seal. The default is 7 days. The value is a setting.
- A commit consumes an upload one time. A cancelled, expired or consumed upload is never
  published. A late tusd completion for such an upload only makes private bytes to remove.

### Commit requests

- The commit body holds `request_id` (UUID), `base_version`, `adds` and `removes`. Each add holds
  `rel_path`, `size`, `sha256` and `upload_id`. At most 10,000 entries.
- The key is `(subject, request_id)`. The server stores a digest of the canonical body.
  The same key and digest return the saved outcome. The same key with a different digest is
  409 `REQUEST_ID_CONFLICT`.
- States: `rejected`, `accepted`, `blocked`, `succeeded`, `abandoned`.
- `GET /api/v1/commit-requests/{request_id}` returns the saved state to its creator. Another
  actor gets 404.
- `POST` answers 200 on success. After 5 s without a result it answers 202 with the status URL.

### Publication in two transactions

1. Acceptance transaction: check the base version, the tree, the privilege and each upload. Save
   the request, its entries, and `collections.pending_request_id`. A collection has at most one
   pending request. A second writer gets 409 `COLLECTION_BUSY`.
2. Outside a transaction, for each entry in a fixed order: do the filesystem step, sync the
   parent directory, then mark the entry done in its own short transaction.
3. Final transaction: write the file rows, the version, the count and the audit record. Clear
   the pending field. Mark the uploads consumed.

- The old object of a replaced or removed file stays on disk until the final transaction commits.
- A step retries safely. A target that already is the new object is done. A target that is
  neither the old object nor the new object blocks the request.
- At startup the API continues every `accepted` and `blocked` request with the same code path.
- A requested removal must be done before success. `KEPT` is not success.

### Operator exit

A platform administrator can resolve a blocked request through an admin route:

- `retry`: run the steps again.
- `abandon`: allowed only when no step is done. The request becomes `abandoned`, the collection
  is free, and the uploads return to `ready`.

A request with done steps and a lost object has no automatic exit. The operator guide (plan 4,
task D6) describes the manual procedure.

### One writer

- The deployment runs one API replica and one tusd.
- At startup the API takes a PostgreSQL session advisory lock on a dedicated connection with TCP
  keepalives. A second API that finds the lock held serves reads only.
- When the connection drops, the API starts no new filesystem step and exits. The platform
  starts it again, and it takes the lock again.
- This is not a fence against a delayed NFS call from a dead process. The deployment must never
  run two writable pods. Plan 5 holds the stronger design.

### Capacity

- Settings: `max_upload_bytes` (one file), `max_staged_bytes` (all uploads that are not consumed,
  counted two times for the tusd file and the copy), `min_free_bytes` (from `statvfs`).
- `begin` refuses with 429 `CAPACITY_EXCEEDED` when a limit does not hold. The pre-create hook
  refuses an upload with no declared length.

### Schema

- `0004_publication.py` adds `objects`, `staged_uploads`, `commit_requests`, `commit_entries`,
  `files.object_id` and `collections.pending_request_id`. These names are final.
- `0005_drop_legacy_uploads.py` drops the old `uploads` and `removals` tables in task S7. It
  refuses when one of them holds a row.
- `0003_uploads.py` does not change.

## Tasks

### S1 Experiment: the tusd handoff

- Intent: learn what tusd v2.10.1 does before the code depends on it.
- Do, in a scratch directory outside `src/` and `tests/`, with the two cached images, a private
  network, private ports and a temporary lake:
  1. Creation identity. Does a pre-create hook that returns a fixed upload ID make the creation
     repeatable? What does tusd do when that ID exists?
  2. Zero bytes. Which hooks fire for an empty upload, and in which order?
  3. Extensions. Find how to refuse a deferred length, concatenation, termination and download.
  4. The pre-finish hook. Measure the hook timeout and the retries. Find what the client receives
     when the hook fails, and if a repeated final `PATCH` runs the hook again.
  5. A completed upload whose pre-finish hook never ran. Find how the API can detect it.
  6. nginx `auth_request`: the token check runs before the body. The check for `HEAD` and `PATCH`
     compares the token's subject with the upload's owner.
  7. Where `.tus-uploads` and the object area must be for an organization on its own filesystem.
- Output: a section "S1 results" in this file with the answer and the command for each item.
  If an answer contradicts the design above, stop and correct the design before S2.
- Verification: an independent run of the same commands gives the same answers. Remove the
  containers, the network and the temporary lake that this task made. Touch no other container.
- Dependencies: plan 1.
- Status: pending

### S2 Values and schema

- Create or change:
  - `src/huron/core/lake/publications/`: `models.py` (frozen dataclasses for the request, an
    entry, the outcome), `errors.py`, `planning.py` with `plan_entries(current, request)` that
    returns the entries in the fixed order: deepest removes first, parents before children for
    adds, a file-to-directory change as remove then add.
  - `src/huron/core/lake/uploads/`: the values for the new upload states.
  - `migrations/versions/0004_publication.py` and the tables modules in `core/metastore/`.
  - `pyproject.toml`: add the new `core.lake` package to the import contracts.
  - Error codes `REQUEST_ID_CONFLICT`, `COMMIT_REQUEST_NOT_FOUND`, `COLLECTION_BUSY`,
    `UPLOAD_INELIGIBLE`, `CAPACITY_EXCEEDED` in the registry and `docs/api-errors.md`.
- Tests: the digest does not depend on entry order. A changed field changes the digest. 10,000
  entries pass and 10,001 fail. Duplicate keys after NFC and case folding fail. The plan order
  for case-only and file-to-directory changes. Migration: upgrade on an empty database,
  downgrade, upgrade again, schema map.
- Verification: `make gate`, `uv run pytest -m contract`.
- Dependencies: S1.
- Status: pending

### S3 Storage steps

- Create or change:
  - `src/huron/core/storage/ports.py`, `posix.py`, `memory.py`, `src/huron/pkg/fs/posix.py`:
    `copy_sealed(source, destination, expected_size) -> SealedFile(size, sha256, inode)` with an
    exclusive create, `link_once(source, destination)`, `sync_directory(location)`.
  - `src/huron/core/storage/publication.py`: `Publisher.apply(step) -> StepResult`. It uses only
    the `Storage` port. Steps: add or replace (link to a unique temporary name, sync, rename,
    sync), remove (unlink, sync), make directory, remove empty directory.
  - The value types of a step live in `core.storage`. `core.lake` must not import `core.storage`,
    so the API layer converts an entry to a step.
- Tests over both adapters: a retry after each point of a step. The target is the old object, the
  new object, a foreign file, missing. A link at each path component. A foreign file in a
  directory to remove blocks, and the file stays. `ENOSPC` and a failed sync give no success.
  The copy has a different inode from the source, and a later write to the source does not
  change the copy.
- Verification: `make gate`. The contract table of plan 1 has a row for each new port method.
- Dependencies: S2.
- Status: pending

### S4 Metastore adapters

- Create or change: memory and PostgreSQL adapters for objects, staged uploads, commit requests
  and entries, with ports owned by `core.lake`. Lock order in every transaction: collection row,
  request row, upload rows, object rows.
- Tests in the shared contract suite and `tests/contract/test_postgres_races.py`: two
  connections send the same request ID. Two requests for one collection. An upload consumed by
  two requests. A raw unique-violation error never reaches a caller.
- Verification: `make gate`, `uv run pytest -m contract`.
- Dependencies: S2.
- Status: pending

### S5 Domain operations

- Create or change:
  - `core/lake/uploads/attempts.py`: `begin`, `start_seal`, `finish_seal`, `cancel`, `expire`,
    `get`. The exact creation rule comes from S1.
  - `core/lake/publications/operations.py`: `submit`, `status`, `next_entries`, `mark_done`,
    `finalize`, `resolve`.
  - A refusal with a valid body is saved as `rejected`. Save it in a transaction that commits.
    Raise the error after the commit.
- Tests on the memory store and on PostgreSQL: each defect F1 to F6 as a test that fails on the
  current code path. Stale base, revoked privilege, bad tree, ineligible upload. The same request
  two times. Cancel against finish. Expiry at the boundary with a controlled clock. Finalize two
  times. `abandon` with zero and with one done step.
- Verification: `make gate`, `uv run pytest -m contract`.
- Dependencies: S3, S4.
- Status: pending

### S6 Orchestration in the API

- Create or change, in `src/huron/applications/api/disk/` and `runtime.py`:
  - `sealing.py`: one tracked task for each upload. A second hook call waits for the same task.
  - `publications.py`: the materializer and `recover_pending` at startup.
  - `ownership.py`: the advisory lock, the keepalives, the exit on loss.
  - `capacity.py`: the three limits.
  - `cleanup.py`: remove the objects and tusd files of uploads in an end state, and objects that
    no file row and no pending entry names. Select by database ID only. Never by age or by name.
  - No database transaction waits for a filesystem call.
- Tests: a storage error leaves the request pending and gives no success. A second run completes
  it one time. A foreign target blocks. A second runtime on the same database serves reads only.
  Loss of the lock connection stops new steps. Cleanup never touches a file that a row names.
- Verification: `make gate`, `uv run pytest -m contract`.
- Dependencies: S5.
- Status: pending

### S7 Routes and removal of the old path

- Intent: one change of the wire protocol, with all its consumers.
- Create or change:
  - Routes: the commit route with the new body, the status route, the upload hooks that only
    seal, `POST /api/v1/uploads/{id}/cancel`, `GET /api/v1/upload-attempts/{attempt_id}`, the
    admin resolve route, `pending_request` in the collection view.
  - The CLI sends the new body with a new request ID and the upload IDs. Durable recovery is
    plan 3, task C3.
  - Remove: `Placer`, API `Placements`, `measure_destination`, the backup and undo code, the
    latest-placement lookup, the old upload and removal adapters, the version-1 commit body.
  - `migrations/versions/0005_drop_legacy_uploads.py`.
  - Update the memory seed, `docker/seed/run.mjs`, `web/e2e/support/`, `tests/support/`.
  - `make openapi`. From `web/`, `npm run generate:api`. Show the pending state on the collection
    page as read-only text.
- Tests: HTTP 200, 202, 404 and 409 on the real application. The old body is refused.
- Verification: `make gate`, `uv run pytest -m contract`, the web gate of AGENTS.md.
  `grep -rnE "latest_placements|measure_destination|drop_backup|ReceiptMode" src tests` prints
  nothing.
- Dependencies: S6.
- Status: pending

### S8 Crash acceptance

- Intent: prove recovery on the real application, not on a model.
- Create: `tests/support/crash.py` and `tests/integration/test_publication_recovery.py`. The test
  starts the API as a child process with a storage wrapper that stops at a named point. The test
  kills the process, starts a new one, and reads the rows and the files.
- Cases: a kill before and after each of copy, seal commit, acceptance, link, rename, unlink,
  entry done, final transaction. A two-file replace with one remove. The same request sent again
  after each kill. A late tusd completion after a newer commit.
- Each case asserts the bytes, the version, the count, one audit record and the saved outcome.
- Verification: `make gate`, `uv run pytest -m integration`. No skip is added.
- Dependencies: S7.
- Status: pending

### S9 Restore dead-code and clone detection

- Intent: the owner wants `pyscn` in the gate again. Commit `8b3149a2` removed it on 2026-10-29
  with the old tool configuration. It runs after S8 because S7 deletes much old code.
- Create or change:
  - `pyproject.toml` and `uv.lock`: add `pyscn==1.31.1` as a development dependency. This task
    may add the package. No other dependency changes.
  - `scripts/check_duplication.py` and `tests/unit/test_check_duplication.py`: restore them from
    the parent of commit `8b3149a2`. Adapt them to the current layout.
  - `scripts/duplication_baseline.json`: measure a new baseline on the current code at similarity
    0.80. Do not restore the old file.
  - `Makefile` and the gate list in `AGENTS.md`: add `uv run --locked pyscn check src` and
    `uv run --locked python scripts/check_duplication.py src`. Load the `writing-for-agents`
    skill before the change to `AGENTS.md`.
  - Correct each dead-code finding that `pyscn check` reports. Do not add an exclusion.
- Verification: `make gate` runs both commands and exits 0. The gate list of
  `.claude/commands/implement-markdown.md` and the `Makefile` agree.
- Dependencies: S8.
- Status: pending

## S1 results

Task S1 writes its results here.
