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

- A seal copies the bytes of a complete tusd upload into a new file in a private object area.
  The API syncs the file, opens it again, and measures the size and the SHA-256.
- The sealed file is never opened for a write again. tusd can keep a descriptor on its own file.
  That descriptor cannot change the copy.
- The object area of an organization is `<root>/<org>/.huron-objects/`, with mode 0700. It is
  inside the organization directory, because publication uses a hard link and a hard link fails
  across two mounts. `.huron-objects` is a reserved name. Every walk and `huron adm check` skip
  it.
- `.tus-uploads` can be on another filesystem. The seal copy can cross filesystems. A hard link
  is made only inside one organization directory.
- Readiness makes a real hard link from the object area into each organization directory, then
  removes it. A failure makes the API not ready.
- The API publishes with a hard link to a unique temporary name, then a rename over the target.
  Huron creates no symbolic link.

A seal starts from one of two places. tusd does not guarantee that its pre-finish hook runs, so
the hook alone is not sufficient.

- The pre-finish hook.
- The API's own check. It runs when the client reads the upload attempt and when a commit names
  the upload. A periodic scan is optional.

The API's own check seals an upload only when all of these are true: the `.info` file exists,
the length is not deferred, the data file size equals the `.info` size and the declared size, and
no `<id>.lock` file exists. A lock file means that tusd still works on the upload.

- One seal task runs for each upload ID. A second caller joins the same task.
- A seal starts only for a row in `receiving`, and only for the current upload ID of that row.
- The comparison of the server hash with the client's `sha256` at commit is the last defence.

### Uploads

- States: `receiving`, `sealing`, `ready`, `consumed`. End states before a commit: `failed`,
  `cancelled`, `expired`.
- The client sends an `attempt_id` (UUID) at creation. The key of an attempt is the subject and
  the `attempt_id`.
- tusd truncates the data file when an upload ID is created a second time. Thus Huron never
  gives one upload ID to tusd two times. The attempt row keeps every upload ID that Huron issued
  for it. One of them is the current ID. Only the current ID is authorized, sealed or published.
- The creation rule runs under the lock of the attempt row. Two first requests that race must
  give one row. The second request then gets case 3 or case 4.

| Case | Attempt row | Result |
| --- | --- | --- |
| 1 | No row | Create the row in `receiving` with a new UUID as the current ID |
| 2 | A row with different fields | 409 conflict |
| 3 | `receiving`, and the current ID has an `.info` file | 409 that names the current ID. The client resumes |
| 4 | `receiving`, and the current ID has no `.info` file | A new UUID becomes the current ID. The old ID is an orphan that cleanup removes by ID |
| 5 | `sealing`, `ready` or `consumed` | 409 with the state and the current ID |
| 6 | `failed`, `cancelled` or `expired` | 409 with the state. A new upload needs a new `attempt_id` |

- The pre-create hook also refuses a deferred length, a partial or final upload of a
  concatenation, and a creation request that carries a body.
- The pre-finish hook is short. It starts or joins the seal task. It answers with the result
  when the seal ends in approximately 20 s. If not, it answers with the header
  `Huron-Upload-State: sealing`, and the client polls the API.
- A failed, cancelled or timed-out pre-finish hook is not sent again by tusd, and tusd can
  finish the upload although the hook refused. The API's own check covers these cases.
- An upload expires `upload_ttl` after its last activity. Activity is a `PATCH` that the
  authorization check allowed, or the end of a seal. The default is 7 days. The value is a
  setting. A `receiving` row that is older than `upload_ttl` is treated as expired.
- A cancel goes through the API. It removes the tusd files of every upload ID of the attempt.
  tusd's own termination is disabled.
- A commit consumes an upload one time. A cancelled, expired or consumed upload is never
  published. A late tusd completion for such an upload, or for an ID that is not current, only
  makes private bytes to remove.

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
- After tusd is killed, a stale `<id>.lock` file makes each request for that upload fail with
  500. A step removes all lock files in `.tus-uploads` before tusd starts. This is safe only
  because one tusd runs and the old one is gone.
- At startup the API takes a PostgreSQL session advisory lock on a dedicated connection with TCP
  keepalives. A second API that finds the lock held serves reads only.
- When the connection drops, the API starts no new filesystem step and exits. The platform
  starts it again, and it takes the lock again.
- This is not a fence against a delayed NFS call from a dead process. The deployment must never
  run two writable pods. Plan 5 holds the stronger design.

### Capacity

- Settings: `max_upload_bytes` (one file), `max_staged_bytes` (all uploads that are not consumed,
  counted two times for the tusd file and the copy), `min_free_bytes` (from `statvfs`).
- The free-space check reads both filesystems: the one of `.tus-uploads` and the one of the
  organization's object area.
- `begin` refuses with 429 `CAPACITY_EXCEEDED` when a limit does not hold. The pre-create hook
  refuses an upload with no declared length.

### tusd and nginx settings

The S1 results give the full flag list and the nginx block. They bind. The rules:

- tusd: `-disable-download`, `-disable-termination`, `-disable-concatenation`,
  `-max-size=<max_upload_bytes>`, `-hooks-enabled-events=pre-create,pre-finish`,
  `-hooks-http-timeout=60s`, `-hooks-http-retry=3`, `-request-completion-timeout=60s`,
  `-network-timeout=2m`. No `post-receive` hook.
- The hook timeout is longer than the 20 s wait of the pre-finish route. The completion timeout
  is not shorter than that wait. The network timeout is longer than the hook timeout.
- nginx: `X-Forwarded-Host` and `X-Forwarded-Proto` have fixed configured values, never a value
  from the client. `Forwarded` is empty. `/_huron_auth` has `client_max_body_size 0`. `/files/`
  has `65m`, the creation request has `1m`. `proxy_request_buffering off`.
  `proxy_read_timeout 120s`.
- The client builds the upload URL from its configured `uploads_url` and the upload ID. It does
  not trust a `Location` header for the host. A chunk is at most 64 MiB.

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
- Status: complete (verification 3 of 3 passed, 2026-11-10)

### S2 Values and schema

- Create or change:
  - `src/huron/core/lake/publications/`: `models.py` (frozen dataclasses for the request, an
    entry, the outcome), `errors.py`, `planning.py` with `plan_entries(current, request)` that
    returns the entries in the fixed order: deepest removes first, parents before children for
    adds, a file-to-directory change as remove then add.
  - `src/huron/core/lake/uploads/`: the values for the new upload states, the attempt with its
    current upload ID and the list of every issued upload ID, and the creation refusal that
    carries the state and the current ID.
  - `migrations/versions/0004_publication.py` and the tables modules in `core/metastore/`.
    `staged_uploads` is unique on subject and `attempt_id`. The issued upload IDs are unique
    across all attempts.
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
    exclusive create, `link_once(source, destination)`, `sync_directory(location)`. The source
    of `copy_sealed` can be on another filesystem. `link_once` links only inside one
    organization directory. A link probe for readiness makes and removes a real hard link from
    the object area into the organization directory.
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
  two requests. Two first creations with the same subject and `attempt_id` give one row, and the
  second caller sees that row under its lock. A raw unique-violation error never reaches a
  caller.
- Verification: `make gate`, `uv run pytest -m contract`.
- Dependencies: S2.
- Status: pending

### S5 Domain operations

- Create or change:
  - `core/lake/uploads/attempts.py`: `begin`, `start_seal`, `finish_seal`, `cancel`, `expire`,
    `get`. `begin` implements the six cases of the creation rule in the design. It receives
    the fact "the current ID has an `.info` file" from its caller. `start_seal` accepts only a
    row in `receiving` and only its current upload ID.
  - `core/lake/publications/operations.py`: `submit`, `status`, `next_entries`, `mark_done`,
    `finalize`, `resolve`.
  - A refusal with a valid body is saved as `rejected`. Save it in a transaction that commits.
    Raise the error after the commit.
- Tests on the memory store and on PostgreSQL: each defect F1 to F6 as a test that fails on the
  current code path. One test for each of the six creation cases. No upload ID is issued two
  times. A seal of an ID that is not current is refused. A `receiving` row past `upload_ttl` is
  expired. Stale base, revoked privilege, bad tree, ineligible upload. The same request
  two times. Cancel against finish. Expiry at the boundary with a controlled clock. Finalize two
  times. `abandon` with zero and with one done step.
- Verification: `make gate`, `uv run pytest -m contract`.
- Dependencies: S3, S4.
- Status: pending

### S6 Orchestration in the API

- Create or change, in `src/huron/applications/api/disk/` and `runtime.py`:
  - `sealing.py`: one tracked task for each upload ID. A second caller joins the same task. The
    task does not depend on the hook request: it continues when the hook's client goes away.
    The completeness check of the design: `.info` exists, no deferred length, the sizes agree,
    no `<id>.lock`. An upload with a lock file is skipped, not failed.
  - `publications.py`: the materializer and `recover_pending` at startup.
  - `ownership.py`: the advisory lock, the keepalives, the exit on loss.
  - `capacity.py`: the three limits. The free-space check reads the filesystem of
    `.tus-uploads` and the filesystem of the object area.
  - `cleanup.py`: remove the objects and tusd files of uploads in an end state, the tusd files
    of every issued upload ID that is not current, and objects that no file row and no pending
    entry names. Select by database ID only. Never by age or by name.
  - No database transaction waits for a filesystem call.
- Tests: a storage error leaves the request pending and gives no success. A second run completes
  it one time. A foreign target blocks. A second runtime on the same database serves reads only.
  Loss of the lock connection stops new steps. Cleanup never touches a file that a row names.
  A complete upload with no hook call is sealed by the check. An upload with a lock file, a
  deferred length or a short data file is not sealed. Two callers get one seal. A full
  filesystem on each of the two sides refuses.
- Verification: `make gate`, `uv run pytest -m contract`.
- Dependencies: S5.
- Status: pending

### S7 Routes and removal of the old path

- Intent: one change of the wire protocol, with all its consumers.
- Create or change:
  - Routes: the commit route with the new body, the status route,
    `POST /api/v1/uploads/{id}/cancel`, the admin resolve route, `pending_request` in the
    collection view.
  - The pre-create hook: the six creation cases, and the refusal of a deferred length, a
    concatenation part or final, and a creation request with a body. Each 409 carries the state
    and the current upload ID where the case has them.
  - The pre-finish hook: start or join the seal, wait at most 20 s, then answer with the result
    or with `Huron-Upload-State: sealing`.
  - The authorization route for nginx: the token's subject is the owner, and the upload ID is
    the current ID of an attempt in `receiving`. An allowed `PATCH` records activity.
  - `GET /api/v1/upload-attempts/{attempt_id}`: returns the state and the current upload ID to
    the owner, and runs the API's own seal check.
  - A commit that names an upload that is not `ready` runs the seal check one time. If the
    upload is still not `ready`, the answer is 409 `UPLOAD_INELIGIBLE` with the state.
  - The CLI sends the new body with a new request ID and the upload IDs. Durable recovery is
    plan 3, task C3.
  - Remove: `Placer`, API `Placements`, `measure_destination`, the backup and undo code, the
    latest-placement lookup, the old upload and removal adapters, the version-1 commit body.
  - `migrations/versions/0005_drop_legacy_uploads.py`.
  - Update the memory seed, `docker/seed/run.mjs`, `web/e2e/support/`, `tests/support/`.
  - `make openapi`. From `web/`, `npm run generate:api`. Show the pending state on the collection
    page as read-only text.
- Tests: HTTP 200, 202, 404 and 409 on the real application. The old body is refused. Each
  creation case and each refusal through the hook route. The pre-finish answer before and after
  the 20 s limit, with a controlled clock. Another user's token and a non-current upload ID on
  the authorization route. The attempt read seals a complete upload that no hook reported.
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
  after each kill. A late tusd completion after a newer commit. A late completion of an upload
  ID that is not current. A pre-finish hook that answers 500, that answers 422, and that gets
  no answer before the timeout: the attempt read then seals the upload. A kill of the API
  during the pre-finish hook.
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

Run on 2026-11-10 with `tusproject/tusd:v2.10.1` (commit `388a27cb`) and `nginx:1.31.8`, both
`--pull=never`. A verifier ran the drivers again and added probes the same day. OBSERVED means
measured in one of these runs. REASONED means not measured. Times are in seconds. The scripts and
logs existed at session time only, so this section holds the requests, flags and results.

### Method

- OBSERVED setup: bridge network `huron-s1-net`, no published port. The host reached each
  container at its bridge address. Every container ran as `--user 1000:1000`, with a temporary
  lake at `/lake`. A standard-library Python stub was the hook endpoint and the nginx auth server.
  It listened on the bridge gateway (`172.23.0.1:18901` in this run, an address that depends on
  the host). Base tusd command, to which each case adds the flags that it names:

```text
docker run -d --pull=never --name huron-s1-tusd --network huron-s1-net --user 1000:1000
  -v <lake>:/lake tusproject/tusd:v2.10.1 -host=0.0.0.0 -port=1080 -base-path=/files/
  -upload-dir=/lake/.tus-uploads -hooks-http=http://<gateway>:18901/hooks
  -hooks-http-forward-headers=Authorization -hooks-http-timeout=2s -file-perms=0600 -dir-perms=0700
  -hooks-enabled-events=pre-create,post-create,post-receive,pre-finish,post-finish,pre-terminate,post-terminate
```

- OBSERVED requests, each with `Tus-Resumable: 1.0.0` and `Authorization: Bearer <user>`: creation
  `POST /files/` with `Upload-Length` and `Upload-Metadata: attempt <base64 UUID>`. Chunk
  `PATCH /files/<id>` with `Upload-Offset` and `Content-Type: application/offset+octet-stream`.
- OBSERVED hook answers, all HTTP 200: pre-create allow `{"ChangeFileInfo": {"ID": <attempt>}}`.
  Refusal `{"RejectUpload": true, "HTTPResponse": {"StatusCode": N, "Header": {...}, "Body": ...}}`.
  Pre-finish success `{"HTTPResponse": {"Header": {...}}}`. Pre-finish has no refusal field, so
  its "refusal" is `HTTPResponse` with `StatusCode 422`. A failing hook answered 500 or late.

### 1. Creation identity

| Request (pre-create answers the fixed ID) | Result |
| --- | --- |
| POST, PATCH 1,000 of 4,000 bytes, same POST again | `201`, same `Location`. Data file 0 bytes, HEAD `Upload-Offset: 0`, PATCH at 1000 gets `409` |
| Upload complete (post-finish fired), same POST again | `201`. Data file 0 bytes, HEAD `Upload-Offset: 0` |
| Same POST during a running 3,000,000-byte PATCH | POST `201`. PATCH `204 Upload-Offset: 3000000`, pre-finish `Offset 3000000`. File holds 2,000,000 bytes |
| Complete upload, hook refuses the repeat with 409 | `409`, our headers (`Location` too) and body. 4,000 bytes intact, `.info` `Size 4000` |
| Two concurrent POSTs, hook serialized by one lock, allows when no `.info` | Both `201` in 4 of 5 rounds, `201` and `409` in 1 |

- OBSERVED: a creation with an existing ID truncates the data file to 0 bytes, and tusd logs
  `UploadCreated` again. It does this also while `<id>.lock` exists for a running PATCH. REASONED:
  tusd writes `.info` again. Its content stayed the same in each run.
- REASONED cause of the concurrent result: the serialization ends when the hook answers, and tusd
  writes `.info` after that answer.
- OBSERVED: hook allows and tusd cannot write (upload directory mode `0500`): `500`, nothing on
  disk. tusd killed during the hook: closed connection, nothing on disk.
- REASONED: a kill between the hook answer and the file creation was not provoked. tusd makes the
  data file first, then `.info`. The result is nothing, a 0-byte data file only, or both.
- REASONED: no tusd path makes a creation safely repeatable. Only a refusal is safe.
- What the product must do (REASONED): the creation rule of Contradictions, 1. The row keeps each
  issued ID, so cleanup removes an orphan by its database ID. The CLI first reads
  `GET /api/v1/upload-attempts/{attempt_id}`. It resumes a `receiving` upload with HEAD and PATCH.
  A 409 for a `receiving` row names the upload to resume. A 409 that names another state tells
  the client to read the attempt and not to upload again. A 409 conflict for different fields is
  an error that the CLI shows to the user. When HEAD shows a complete upload, the client reads the
  attempt, and that read starts the API's own seal (Contradictions, 2). The seal never trusts the
  hook's `Offset`.

### 2. Zero bytes

- OBSERVED: `POST /files/` with `Upload-Length: 0`. All hooks carry `Method POST`, `URI /files/`.
  pre-create comes first. post-create and pre-finish start together, either one first (3 of 6
  runs each). post-finish comes last. pre-finish success gives `201`, `Location` and its headers.
  Pre-finish 422 gives `422`, our body and a `Location`, and post-finish still fires. A failing
  pre-finish (500, 2 calls) gives `500` with no `Location` and no post-finish. In each case the
  empty data file and `.info` exist. A later zero-length PATCH at 0 answers `204` with no hook.
- What the product must do (REASONED): seal an empty upload like any other. The CLI finds a failed
  empty creation through its `attempt_id`, because that 500 has no upload ID. Its read of the
  attempt starts the API's own seal (Contradictions, 2).

### 3. Extensions

- OBSERVED: `OPTIONS /files/` gives `Tus-Extension: creation,creation-with-upload,termination,
  concatenation,creation-defer-length`. No `expiration`. No response has `Upload-Expires`.
- OBSERVED: by default GET of the finished upload (10 of 10 bytes) gives `200` with the 10 bytes.
  GET of an upload at offset 0 of 10 gives `200` with an empty body. DELETE gives `204` and
  removes the files of a finished upload and of an upload at offset 0. `-disable-concatenation`
  answers `Upload-Concat` with `400` before any hook. `-disable-termination` and
  `-disable-download` answer DELETE and GET with `405`, no hook.
- OBSERVED: `-help` has no flag for deferred length or creation-with-upload. In the run with
  default flags, pre-create sees `Upload.SizeIsDeferred: true` and `Upload-Defer-Length`, a body
  as `Content-Length` above `"0"` with the offset content type, and concatenation as `IsPartial`,
  `IsFinal`, `PartialUploads`. It allowed each one.
- OBSERVED, default flags and a hook that refuses: a 400 pre-create refusal stopped deferred
  length, partial uploads and creation-with-upload. The hook did not refuse the final
  concatenation in that run. tusd answered `404 ERR_UPLOAD_NOT_FOUND` for the unknown parts, with
  no hook call. `-disable-concatenation` stops a final concatenation with `400` before any hook.
- What the product must do (REASONED): the three disable flags. Pre-create refuses
  `SizeIsDeferred`, `IsPartial`, `IsFinal`, a non-zero `Content-Length` and the offset content
  type. Cancel goes through the API, which removes the tusd files of each ID that the row issued.
  Expiry is `upload_ttl`.

### 4. The pre-finish hook

- OBSERVED defaults (`-help`): `-hooks-http-timeout 15s`, `-hooks-http-retry 3`,
  `-hooks-http-backoff 1s`, `-network-timeout 1m`, `-request-completion-timeout 10s`,
  `-acquire-lock-timeout 20s`, `-filelock-holder-poll-interval 5s`.
- OBSERVED requests: POST 2,000 bytes, PATCH 1,000 at 0, final PATCH 1,000 at 1000.

| tusd flags | pre-finish behaviour | Client gets for the final PATCH |
| --- | --- | --- |
| `-hooks-http-timeout=3s` | answers after 1 s | 1 call, `204` |
| `-hooks-http-timeout=3s` | answers after 5 s | 1 call, `500 context deadline exceeded` at 3.0 s |
| `-hooks-http-timeout=3s` | 500 once, then 200 | 2 calls 1 s apart, `204` |
| `-hooks-http-timeout=10s` | always 500 | calls at 0, 1, 2 s, `500 unexpected response code` |
| `-hooks-http-retry=0,1,2,5` | always 500 | 1, 1, 2, 5 calls (N is the total of calls, at least 1, not the retries) |
| `-hooks-http-timeout=2s` (item 5 run) | always 500 | 2 calls, `500 context deadline exceeded` at 2.0 s |
| `-hooks-http-timeout=3s` | 200 with `StatusCode 422` | `422`, our body. post-finish fires, HEAD 2000 of 2000 |
| `-network-timeout=2s -hooks-http-timeout=20s` | answers after 6 s | tusd logs `204`, client gets a closed connection at 6 s |

- REASONED from the `2s` row: one `-hooks-http-timeout` covers all calls of one hook, retries
  included. The third call was due at 2 s and did not start.
- OBSERVED after each pre-finish that answered 500 to the end or timed out: HEAD gives offset 2000
  of 2000 and post-finish does not fire. A repeated final PATCH gets `409 ERR_MISMATCHED_OFFSET`.
  A 0-byte or 1-byte PATCH at 2000 gets `204 Upload-Offset: 2000`. None runs pre-finish again. A
  422 still finishes the upload.
- OBSERVED cause chain of a cancel: a HEAD asks for the upload's lock. The PATCH that holds it
  notices at its next `-filelock-holder-poll-interval` tick (log `UploadInterrupted`). tusd cancels
  the request context after `-request-completion-timeout`. A client that leaves starts the same
  timeout (3 s cancel with `2s`). The poll and completion flags were varied in the table below.
  REASONED from that table: the hook call is cancelled only when that timeout is shorter than the
  hook's remaining time.

| Flags (8 s hook unless named) | Event at 1 s | Result |
| --- | --- | --- |
| poll 5 s (default), completion `2s`, lock `2s` | HEAD | HEAD `500` at 3 s. Interrupted at 5 s, PATCH `500 context canceled` at 7 s, no post-finish |
| poll `1s`, completion `2s`, lock `2s` | HEAD | HEAD `500` at 3 s. PATCH `500 context canceled` at 4 s |
| poll `1s`, completion `20s`, lock `2s` | HEAD | HEAD `500` at 3 s. Hook completes at 8 s, PATCH `204`, post-finish fires |
| completion `2s` | client leaves | Hook cancelled at 3 s, tusd logs `500`, no post-finish. Later HEAD 2000 of 2000 |
| completion 10 s (default), 6 s hook, `-network-timeout=2s` | client leaves, HEAD at 1.5 s | Interrupted at 5 s, hook completes at 6 s, tusd logs `204`, post-finish fires |

- What the product must do (REASONED): "the final PATCH timed out, resume later" works only when
  the API seals on its own (item 5). The API's own seal acts only on rows in state `receiving`,
  and only on the row's current ID. A 422 leaves a finished tusd upload, so a row that the hook
  refused (`failed`, `cancelled`, `expired`) is never sealed. `-request-completion-timeout` is at
  least the hook's wait. The hook is short (Contradictions, 4).

### 5. A completed upload that is not sealed

- OBSERVED, pre-finish always 500, and `docker kill` during a 4 s pre-finish: the data file holds
  all 2,000 bytes. `.info` has `Size 2000`, `SizeIsDeferred false`, `Offset 0`. Nothing in `.info`
  records the offset or a finish.
- OBSERVED: after the kill `<id>.lock` holds `1`. A new tusd with the lock in place answers HEAD
  `500` after `-acquire-lock-timeout=3s`. With the lock files removed before the start, HEAD gives
  2000 of 2000, and a zero-length PATCH gives `204` with no hook. REASONED: `1` is the old
  process ID, and the new tusd also runs as PID 1, so it cannot see that the lock is stale.
- OBSERVED, a 1,000,000-byte PATCH in 100,000-byte pieces with a 4 s pre-finish, sampled every
  0.25 s: `<id>.lock` exists from the first piece. pre-finish starts at 1.8 s. The data file
  shows 1,000,000 bytes from the 2.0 s sample. The PATCH answers `204` at 5.8 s. The lock exists
  until that answer and is gone after. REASONED: tusd calls pre-finish after the last byte. The
  samples are rounded to 0.1 s, so the 1.8 s sample (900,000 bytes) can come before the hook start
  at 1.80 s.
- OBSERVED: so "size equals `.info` `Size`, not deferred" also matches a PATCH still in pre-finish.
- What the product must do (REASONED): the detection rule of Contradictions, 2. The API reads the
  files from the mount, with no tus request. Its own seal skips an upload while `<id>.lock` exists.
  Stale locks are removed before tusd starts (the `clean-locks` step of `IMPLEMENTATION_PLAN.md`).
  Sealing on demand is sufficient and simpler than a periodic scan. On NFS a writer crash or
  out-of-order WRITE calls can show the full size with holes. The backstop is the server hash,
  which the commit compares with the client's `sha256`.

### 6. nginx `auth_request`

- OBSERVED setup: nginx in front of tusd `-behind-proxy` with the disable flags. The auth location
  calls the stub with `proxy_pass_request_body off`, `X-Original-Method` and `X-Original-URI`.
- OBSERVED: `OPTIONS /files/` without a token reaches tusd through `@tus_options` with no auth
  call. The auth stub gets the client's other headers and the two `X-Original-*` headers. Its
  `Host` is `api` (the upstream name), not the client's `uploads.example`, and it gets no
  `Content-Length`. On `/files/<id>` the owner gets HEAD `200`, PATCH `204`, DELETE and GET `405`
  (tusd's answers). Another user gets `403`, no token `401`.
- OBSERVED: a 64 MiB PATCH with a foreign token or none gets `403` or `401` before a body byte.
  With the owner's token it gives `204 Upload-Offset: 67108864`. 66 MiB against
  `client_max_body_size 65m` and a 2 MiB creation body against `1m` give `413`. Auth down: `500`.
- OBSERVED: without `client_max_body_size 0` in `location = /_huron_auth`, a 2 MiB PATCH gets
  `auth request unexpected status: 413` in the nginx log, and the client gets `500`. REASONED:
  the auth subrequest keeps the request's body length, and 1 MiB is nginx's default
  `client_max_body_size`. So each body over 1 MiB fails in the same way.
- OBSERVED `Location` of a creating POST through nginx:

| nginx forwarded headers | Client sends | `Location` authority |
| --- | --- | --- |
| tusd without `-behind-proxy` | `Host: uploads.example:8443` | `http://uploads.example:8443` |
| same | `Host: uploads.example`, `X-Forwarded-Proto: https` | `http://uploads.example` |
| Plan map, client value passed | `X-Forwarded-Host: evil.example`, proto `https` | `https://evil.example` |
| `X-Forwarded-Host $host`, proto map `https` only | `Host: evil.example`, proto `https` | `https://evil.example` |
| same | `Host: uploads.example:8443`, proto `https` | `https://uploads.example` (port lost) |
| same | `Host: uploads.example`, proto `https, https` | `http://uploads.example` |

- OBSERVED: `proxy_set_header Forwarded ""` clears `Forwarded`. `$host` comes from the client's
  `Host` header, so it is not a fixed value. REASONED: for a creating POST the auth call checks the
  token and the creation headers, not an owner. Pre-create decides.
- What the product must do (REASONED): send a configured fixed public authority (host and port) in
  `X-Forwarded-Host` and a configured fixed scheme in `X-Forwarded-Proto`. A fixed value with a
  port was not measured. Second defence: the CLI builds the upload URL from its configured
  `uploads_url` and the upload ID. It never uses the authority of `Location`.

### 7. Where `.tus-uploads` and the object area live

- OBSERVED in the code: `UPLOAD_DIR = ".tus-uploads"` is directly below the lake path, and
  `OrganizationPlace.base` is the organization's root, with the directory at `base / name`
  (`core/storage/layout.py`). `_places` (`applications/api/runtime.py`) sets `base` to the lake
  path, or to the declared root relative to `lake_path`. ADR 0007: the directory is `<root>/<name>`,
  and the example exports are organization directories (`/data1/huron/helio`). Placement links
  from `.tus-uploads` into the collection (`core/storage/placement.py`).
- OBSERVED (busybox `ln` in one container): a link inside one bind mount works. A link to a second
  bind mount of the same host filesystem (same `st_dev`) fails with `Cross-device link`. A link to
  a tmpfs fails too. A copy to the second mount, then a link inside it, works.
- OBSERVED, lake at `/lake` and a second mount at `/lake/orgx` (same `st_dev`):
  `ln /lake/.huron-objects/x /lake/orgx/coll/y` fails with `Cross-device link`.
  `ln /lake/orgx/.huron-objects/x /lake/orgx/coll/y` works.
- OBSERVED: pre-create can set `ChangeFileInfo.Storage.Path`. tusd writes the data file there and
  makes the directory. `.info` stays in `-upload-dir`. REASONED: the lock file was not checked.
- REASONED: `<base>/.huron-objects/` sits beside the organization directories. It works only when
  each export is mounted at its root, which ADR 0007's exports are not.
- What the product must do (REASONED): the object area of Contradictions, 3. The seal copies from
  `.tus-uploads` into the organization's object area, and that copy may cross a filesystem. Equal
  `st_dev` does not prove one mount, so the readiness probe makes a real hard link and removes it.
  Free space is checked on the filesystem of `.tus-uploads` and of each object area.
  `Storage.Path` is not needed.

### Contradictions with the design

1. Creation identity.
   - Design: "The same `attempt_id` with the same fields gives the same upload."
   - Evidence (item 1, OBSERVED): a second creation with an existing ID truncates the bytes, also
     of a completed upload. With the hook serialized by one lock (a stand-in for the row lock), two
     concurrent POSTs both got `201` in 4 of 5 rounds. REASONED: the lock ends when the hook
     answers, before tusd writes `.info`. OBSERVED: a 409 refusal kept a completed upload intact.
   - Corrected rule (REASONED): the same `attempt_id` with the same fields names the same attempt
     row. The API never hands out an upload ID twice. Pre-create takes the attempt row lock and
     applies the first case that matches:
     1. No row for this `attempt_id`: make the row in `receiving`, issue a fresh UUID, and store
        it as the row's current ID.
     2. The row exists with different fields: refuse with 409 (conflict).
     3. The row is in `receiving`, and its current ID has a `.info`: refuse with 409 and name the
        ID. The client resumes it.
     4. The row is in `receiving`, and its current ID has no `.info`: issue a fresh UUID and store
        it as the row's current ID. The earlier ID is an orphan that cleanup removes by its ID.
     5. The row is in `sealing`, `ready` or `consumed`: refuse with 409, the state and the current
        upload ID. Issue nothing.
     6. The row is in `failed`, `cancelled` or `expired`: refuse with 409 and the state. A new
        upload needs a new `attempt_id`.
   - Also (REASONED): the hooks, the nginx auth check, the API's own seal and the commit act only
     on the row's current ID. An earlier issued ID is never sealed or published. A client whose ID
     is no longer current gets a refusal and reads the attempt. The seal's own size measurement
     and the commit's server-hash check stay as backstops.
   - Evidence for the corrected rule (OBSERVED, verifier probe, tusd with
     `-hooks-http-timeout=10s`, a stub that applies cases 1, 3 and 4 under one lock):
     - Two concurrent creations, no delay inside the lock: two `201` with two distinct fresh IDs
       in 9 of 10 rounds, `201` and `409` in 1 round. In each two-`201` round the row's current
       ID was the later ID.
     - Two concurrent creations, 0.3 s inside the lock: `201` and `409` in all 10 rounds. Each
       `409` body named the ID of the `201`.
     - A repeated POST after a 1,000-byte PATCH, during a running 3,000,000-byte PATCH and after a
       complete 4,000-byte upload: `409` each time. The data files kept 1,000, 3,000,000 and
       4,000 bytes. The running PATCH answered `204` with `Upload-Offset: 3000000`.
     - So no ID was handed out twice, and no data file was truncated.
   - REASONED: with a cached auth answer (`proxy_cache_valid 204 30s` in the nginx block of
     `IMPLEMENTATION_PLAN.md`) a client can PATCH an orphan for a short time. That wastes work and
     loses no data, because pre-finish and the seal act only on the current ID.
2. How the API learns of a finish.
   - Design: "When tusd finishes an upload, the API copies the bytes into a new file."
   - Evidence (items 4, 5, OBSERVED): a failed, timed-out or cancelled pre-finish is never sent
     again. A 422 still finishes the upload. A kill during pre-finish leaves a full file and no
     finish record. `<id>.lock` exists for the whole final PATCH, pre-finish included.
   - Corrected rule (REASONED): the API also seals a `receiving` upload whose tusd file is
     complete: `.info` exists, not deferred, data size equal to `.info` `Size` and the declared
     size, and no `<id>.lock`. It checks on demand, when the client reads the upload or the
     attempt, or names it in a commit. A periodic scan is optional. One seal task for each upload
     ID serves the hook and the API's own check. The seal acts only on the row's current ID. A row
     in another state is never sealed. A commit that names an upload that is not `ready` gets 409
     `UPLOAD_INELIGIBLE`, and the client reads the attempt before it sends the commit again. The
     server hash checked at commit is the backstop for a file with holes.
3. Where the object area sits.
   - Design: "The object area must be on the same filesystem as the collection."
   - Evidence (item 7, OBSERVED): a hard link fails across two mounts of one filesystem. With the
     organization directory as its own mount, a link from `<base>/.huron-objects/` fails and a
     link from `<base>/<org>/.huron-objects/` works. ADR 0007's exports are organization
     directories.
   - Corrected rule (REASONED): the object area is `<root>/<org>/.huron-objects/`, inside the
     organization directory and its mount, mode 0700, a reserved name that walks and `adm check`
     skip. The readiness probe makes a real link from the object area into each organization
     directory.
4. Rules kept from `IMPLEMENTATION_PLAN.md` and ADR 0008.
   - Design: sections 3 to 9 stay. They include a pre-finish that hashes the file and waits up to
     55 minutes, `-hooks-http-retry=3`, an nginx block with no `client_max_body_size 0` in
     `/_huron_auth` and a client-chosen `X-Forwarded-Host`, and `pre-terminate` as a hook event.
   - Evidence (items 3, 4, 6, OBSERVED): a HEAD (noticed at the holder poll, default 5 s) or a
     disconnect cancelled the hook when `-request-completion-timeout` (default 10 s) was shorter
     than the remaining hook time. It did not cancel the hook when that timeout was longer. A
     `-network-timeout` below the hook time drops the answer.
     `-hooks-http-retry=3` gives three calls in total. A 2 MiB PATCH got `500` without
     `client_max_body_size 0` in the auth location. The client's `X-Forwarded-Host` or `Host`
     sets the `Location` authority. REASONED: each body over 1 MiB fails in the same way, because
     1 MiB is nginx's default `client_max_body_size`.
   - Corrected rule (REASONED): the seal task does not depend on the hook request. Pre-finish
     starts or joins the seal task. It answers with the receipt if the seal is done within a short
     wait, otherwise at once with `Huron-Upload-State: sealing`. The client polls the API. The
     API's on-demand seal recovers every case where the hook failed, timed out, or tusd died. The
     short hook does NOT remove the need for the API to seal on its own. Also: `-hooks-http-retry=3`
     means three calls, use the nginx block below, add `-disable-termination`, and remove
     `pre-terminate` from `-hooks-enabled-events`.

### Recommended tusd flags

```text
-host=127.0.0.1 -port=1081 -base-path=/files/ -upload-dir=${HURON_LAKE_PATH}/.tus-uploads
-behind-proxy -disable-download -disable-termination -disable-concatenation
-max-size=<max_upload_bytes> -file-perms=0600 -dir-perms=0700
-hooks-http=http://<api>/api/v1/uploads/hooks -hooks-http-forward-headers=Authorization
-hooks-enabled-events=pre-create,pre-finish
-hooks-http-timeout=60s -hooks-http-retry=3 -hooks-http-backoff=1s
-request-completion-timeout=60s -network-timeout=2m
```

- OBSERVED: the behaviour of the disable flags, `-behind-proxy` and the retry count (items 3, 4, 6).
- REASONED, not measured: `-port=1081` (from `IMPLEMENTATION_PLAN.md`), `-hooks-http-timeout=60s`,
  `-request-completion-timeout=60s`, `-network-timeout=2m`, `-max-size`, a 20 s short-hook wait.
- REASONED constraints: `-hooks-http-timeout` above the hook's wait (one timeout covers all
  calls). `-request-completion-timeout` at least the hook's wait, and equal to
  `-hooks-http-timeout` to cover the retries. `-network-timeout` above `-hooks-http-timeout`.
- REASONED: the flags enable no `post-receive`. The API records the activity of a chunk for
  `upload_ttl` when the auth check allows a PATCH. A cached auth answer delays that record by at
  most the cache time.

### Recommended nginx configuration

```nginx
proxy_set_header Host $http_host;
proxy_set_header X-Forwarded-Host "<public host>:<public port>";   # configured, fixed
proxy_set_header X-Forwarded-Proto "https";                        # configured, fixed
proxy_set_header Forwarded "";
location = /files/ { auth_request /_huron_auth; client_max_body_size 1m; proxy_request_buffering off; ... }
location /files/   { auth_request /_huron_auth; client_max_body_size 65m; proxy_request_buffering off;
                     proxy_buffering off; proxy_read_timeout 120s; ... }
location = /_huron_auth { internal; client_max_body_size 0; proxy_pass_request_body off;
    proxy_set_header Content-Length ""; proxy_set_header X-Original-Method $request_method;
    proxy_set_header X-Original-URI $request_uri; ... }
```

- OBSERVED: OPTIONS on `@tus_options` without `auth_request`, the body limits, the auth location
  lines and `Forwarded ""` (item 6).
- REASONED, not measured: the fixed forwarded values and `proxy_read_timeout 120s`. The read
  timeout must exceed the short hook's wait plus the write of one chunk.
- REASONED: `...` keeps the other lines of the nginx block of `IMPLEMENTATION_PLAN.md`: the
  OPTIONS rule to `@tus_options` in both `/files/` locations, `proxy_pass`, and the auth cache.
- REASONED: two values in `location /files/` differ on purpose from the nginx block of
  `IMPLEMENTATION_PLAN.md`. `client_max_body_size 65m` replaces `0`, and
  `proxy_read_timeout 120s` replaces `3600s`. Plan 4 tasks D2 and D3 apply these values on
  purpose. A client chunk must be at most 64 MiB, the largest PATCH that passed.

### Cleanup

- OBSERVED before (09:22): 23 containers (among them `huron-m11-production-a1` and
  `huron-p00-20261110t045227-pg`, both Exited), 8 networks, 20 volumes.
- OBSERVED after: the same names and states. Only the "Exited … ago" text differs. No
  `huron-s1-*` resource, stub or temporary lake is left. The verifier's run ended the same way.
