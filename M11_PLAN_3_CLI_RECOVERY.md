# M11 plan 3: CLI state and exact recovery

Read [M11_PLANS.md](M11_PLANS.md) first. This plan fixes defects F5 and F7 in the CLI.

## The defects

| ID | Defect in the current code | Result that this plan requires |
| --- | --- | --- |
| F5 | `_recover` in `sync.py` infers success from the collection version. A removal that is still present was reported as done | The CLI asks the server for the outcome of its request ID |
| F7 | A second process can overwrite staged work. Only `push` takes a lock. The state is in separate files | One lock for every change and one atomic state file |
| F4, F6 | A timeout forgets the upload. A used upload can be sent again | The CLI keeps the upload ID and asks the server for its state |

## Design

This section replaces the CLI recovery rules of decision D-8 and the state files of M11.7 in
`IMPLEMENTATION_PLAN.md`. Login, tokens and `scripts/dev-login.sh` do not change.

### Local state

- One file for each working copy: `working.json`, with a format version, the base version, the
  staged adds and removes, the upload attempts and the pending commit.
- Every write is: a unique temporary file with mode 0600, sync the file, rename, sync the
  directory.
- An unknown format version is refused with a message. The file is not changed.

### Locks

- A state lock in the state root, taken with `flock`. Every command that changes local state
  takes it for the read-change-write only. A second process waits up to 10 s, then fails with
  exit code 6.
- A push lock for each working copy, held for the whole `push`. A second `push` of the same
  working copy fails at once. A `push` of another working copy can run.
- The kernel releases both locks when the process ends. The CLI never removes a lock file and
  never takes a lock from another process.
- `flock` needs a local filesystem. When the state root is on NFS, the CLI stops with a message
  that names `XDG_STATE_HOME`.

### Source files

- `huron add` records the size, the modification time and the SHA-256 of each file.
- `huron push` checks the size and the modification time before it sends a file. A change stops
  the push with the file name. The server compares the hash of the sealed bytes with the
  recorded hash.
- The CLI makes no private copy of a source file. Plan 5 holds that design.

### Uploads and commits

- The CLI saves the `attempt_id` before it creates an upload, and the upload ID after the answer.
- After a timeout the CLI keeps both IDs. The next `push` asks the server for the upload state
  and continues, waits, or starts a new attempt. It never forgets an upload.
- The CLI saves the request ID and the exact body before it sends a commit.
- While a pending commit exists, `add`, `rm`, `pull` and `checkout` of that working copy refuse.
  `push` first reads the status:
  - `succeeded`: set the new base and clear the stage in one state write.
  - `accepted` or `blocked`: wait with a deadline, then report the status and keep the state.
  - `rejected` or `abandoned`: keep the staged work, clear the pending commit, report the reason.
  - 404: send the same request ID and body again.
- The CLI never infers an outcome from the collection version.
- A stage with more than 10,000 entries is refused with a message that tells the user to push in
  parts.
- The wait uses `time.monotonic` with one deadline. Each request timeout and each sleep is
  limited by the time that remains.

## Tasks

### C1 Atomic state and the state lock

- Create or change:
  - `src/huron/applications/cli/localstate.py`: `LocalState`, `WorkingState`, the atomic write,
    the state lock, the push lock, the NFS check.
  - `services.py` and the commands that write state. Build the list from the code first: every
    caller of the write functions in `state.py`, in `commands/`, `sync.py`, `login.py` and
    `walkthrough.py`. Token and config writes take the state lock too.
  - Remove the separate copy and stage files and their writers.
- Tests in `tests/unit/cli/test_localstate.py` and the command tests: two real processes that
  change the stage give two changes, not one. A kill before and after the file sync, the rename
  and the directory sync leaves a complete old or new file. The lock file keeps its inode.
  An old format and an unknown version are refused and not changed. A full disk keeps the old
  file.
- Verification: `make gate`. `uv run python scripts/cli_reference.py --check`.
- Dependencies: plan 1.
- Status: pending

### C2 Source checks

- Create or change: `commands/stage.py` and `sync.py` record and check the size, the modification
  time and the hash. The source walk does not follow links and reports each skipped entry.
- Tests: a file that grows, shrinks, or changes with the same size after `add` stops the push.
  A file removed after `add`. A link, a FIFO and an unreadable file in the source folder.
  Two names that are equal after NFC and case folding. A component of 206 and of 207 bytes.
- Verification: `make gate`.
- Dependencies: C1.
- Status: pending

### C3 Durable attempts and exact commit recovery

- Create or change:
  - `uploads.py`: save the attempt before creation, keep the IDs on a timeout, ask for the state
    before a resume. The rules, from the design of plan 2:
    - Read the attempt (`GET /api/v1/upload-attempts/{attempt_id}`) before each creation and
      each resume.
    - Build the upload URL from the configured `uploads_url` and the upload ID. Do not use the
      host of a `Location` header.
    - Handle each 409 of the creation rule: resume on the named current ID, wait on `sealing`,
      use the upload on `ready`, start a new `attempt_id` after an end state.
    - After a `HEAD` that shows a complete upload, after a failed final `PATCH`, and after the
      answer `Huron-Upload-State: sealing`: read the attempt and poll it with the one deadline.
    - An empty file is recovered through its `attempt_id` in the same way.
    - A chunk is at most 64 MiB.
  - `sync.py`: the pending commit, the status read, the same-body resend. Remove `_recover`,
    `_PLACED` and the branch that forgets an upload after a timeout.
  - `commands/status.py`: show the pending commit and the upload states.
  - The messages follow the `asd-ste100` skill in strict mode.
- Tests in `tests/unit/cli/` on the real router of plan 2: the answer is lost before the server
  applies the commit, and after. A removal-only commit and an empty commit. Another user changes
  the collection version between the send and the retry: the stage stays until the status says
  `succeeded`. A kill before the send, after the send, and before the state write of a success.
  A final `PATCH` that answers 500, 502, 504 or nothing. A timeout does not make a second upload.
  The deadline includes the request time. Each 409 kind of the creation rule. A `Location`
  header with another host is not followed.
- Verification: `make gate`. `grep -rnE "_recover|_PLACED" src/huron` prints nothing.
- Dependencies: C2, and plan 2 task S7.
- Status: pending

### C4 User guide

- Change `docs/user-guide.md`: what `push` does after an interruption, what a pending commit
  blocks, the 10,000-entry limit, the state root on a local filesystem, the source checks.
- Verification: `make gate`, `make docs-check`.
- Dependencies: C3.
- Status: pending
