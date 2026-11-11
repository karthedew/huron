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
- Status: complete (2026-11-11). Three verifications failed on small findings. The owner
  authorized one more fix pass and the commit; see "Escalation".

### C2 Source checks

- Create or change: `commands/stage.py` and `sync.py` record and check the size, the modification
  time and the hash. The source walk does not follow links and reports each skipped entry.
- Tests: a file that grows, shrinks, or changes with the same size after `add` stops the push.
  A file removed after `add`. A link, a FIFO and an unreadable file in the source folder.
  Two names that are equal after NFC and case folding. A component of 206 and of 207 bytes.
- Verification: `make gate`.
- Dependencies: C1.
- Status: complete (2026-11-11). Verification 1 failed on four small findings. Verification 2
  passed after one fix pass.
  - The work added `src/huron/applications/cli/sources.py` and changed `uploads.py`: the
    uploader does not hash, it sends from the descriptor that the check opened, and
    `attempt_state` is `"ready"` after the service sealed the upload.
  - The format version of `working.json` stays 1. A file from C1 with staged adds that have no
    `mtime_ns` and `sha256` is refused as not valid and is not changed.
  - `sha256_file` in `src/huron/pkg/hashing.py` had no caller left and was removed.
  - Coverage on the unit run: 11463 statements and 2 missed before, 11524 statements and 2
    missed after (`applications/cli/identifiers.py` 76-77). `fail_under` did not change.
  - Gate of verification 2: `make gate` exit 0, 4086 passed, 24 deselected, duplication 69
    clones in 25 groups. `uv run pytest -m integration`: 23 passed, 1 skipped.

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

## Escalation

Recorded 2026-11-11. Task C1 "Atomic state and the state lock" failed its third verification.
The workflow stops here. C2 to C4 did not start.

### State of the tree

- HEAD is `b1aabee3` (plan 2, task S9), pushed. Plan 2 is complete.
- The C1 work is in the working tree and is not committed. It was not reverted, because the tree
  is not broken: the third verifier ran every gate on it with exit code 0.
  - `make gate`: 4038 passed, 24 deselected. 11456 statements, 2 missed
    (`applications/cli/identifiers.py` 76-77, not touched by the task). `pyscn check` passes.
    Duplication: 69 clones, 25 groups, equal to the baseline.
  - `uv run pytest -m contract`: 216 passed. `uv run pytest -m integration`: 23 passed, 1 skipped
    (the old skip of `test_cli_end_to_end.py`).

### The three verifications

1. FAIL. No test showed that token and draft writes take the state lock. One message used a
   progressive verb form. A fixture was copied a third time.
2. FAIL. `collections/` did not get mode 0700, and new text said that it did.
3. FAIL. One finding: the read error and the save error give a hint that does not fit each case.
   `_cannot_read` always says "correct the permissions". `_cannot_save` always says "make free
   space or correct the permissions". When the cause is a path of the wrong kind (`ENOTDIR`,
   `EISDIR`, `EEXIST`), for example an `XDG_STATE_HOME` that is a file, the hint does not help.
   The correction: select the hint from `error.errno`, or give one neutral hint, with a test for
   each hint.

Each verifier confirmed the design of C1: the atomic write, the two locks, the NFS refusal, the
format refusal and the removal of the old state code. The third verifier ran 20 mutations, and
the tests caught each one.

### Diagnosis

- The plan is sound. No verification found a defect in a behaviour that the task text requires.
- The finding of verification 3 is in code that the orchestrator added to the second fix pass,
  beyond the finding of verification 2: clear refusals of state that the CLI cannot read or save.
  This extra scope made new messages, and the last verification had no pass left to correct them.
- The task text has no rule for an I/O error on the state files other than a full disk.

### Questions

1. Does the owner accept C1 with one more bounded correction (the hints of `_cannot_read` and
   `_cannot_save`) and one more verification, as for S7 of plan 2?
2. Does C1 own the refusal of unreadable state, or does a later task own it? If a later task
   owns it, the correction can be to remove the two general errors from C1.
3. Does a fix pass get a rule that it corrects the findings only, with nothing added?

### Next steps

1. The rule of the workflow: run
   `/architectural-review src/huron/applications/cli M11_PLAN_3_CLI_RECOVERY.md`, with this
   section as its input.
2. Then run `/design-plan` for the same area. Give it this section and the output of the review.

### Resolution

Recorded 2026-11-11. The owner did not run the review. The owner authorized one more fix pass,
then the commit and the push of C1, with no further verification agent.

- Fix pass 3 changed `localstate.py` and `tests/unit/cli/test_localstate.py` only. The read error
  and the save error now select their hint from the error number: permissions (`EACCES`,
  `EPERM`, `EROFS`), free space (`ENOSPC`, `EDQUOT`), a path of the incorrect type (`ENOTDIR`,
  `EISDIR`, `EEXIST`), and a neutral hint for each other cause.
- The implementer showed that a selection that always gives the permissions hint fails 28 tests.
- The orchestrator ran `make gate` on the final tree: exit 0, 4057 passed, 24 deselected, 11463
  statements, 2 missed (`applications/cli/identifiers.py` 76-77), `pyscn check` passes,
  duplication 69 clones in 25 groups.
- No independent verification ran after fix pass 3. The first task of the next session can
  read the hint selection again when it starts C2.

## Handoff

Recorded 2026-11-11 for a new session. Read [M11_PLANS.md](M11_PLANS.md) first.

- Plans 1 and 2 are complete and pushed. C1 is complete and pushed. The next task is C2.
- Rules of the owner for the execution:
  - The orchestrator stays on the model of the session. Each child is an Agent with
    `subagent_type: general-purpose`, `model: "opus"`, `effort: "high"`, one at a time, with no
    nested delegation. Children make no git state changes.
  - Commit after each task that passes verification, with explicit paths. Push at the end of
    each plan. About 52 unrelated uncommitted entries stay out of each commit: `.agents/`
    (with staged deletions), `.opencode/`, `opencode.json`, `.gitignore`, other sections of
    `AGENTS.md`, `docs/agents/`, `web/package.json`, `web/docs-site/package.json`,
    `web/scripts/npm-scripts.test.mjs`, `IMPLEMENTATION_PLAN_LATEST.md`, `HANDOFF_*.md`,
    `REPOSITORY_READINESS.md`, `design/`.
  - Containers: only the cached images `tusproject/tusd:v2.10.1` and `nginx:1.31.8` with
    `--pull=never`, and the postgres:16 test container. Touch no other container, network or
    volume.
  - A fix pass corrects the findings of its verification only. Added scope caused the third
    failure of C1.
- Open notes for later tasks:
  - C2: `mtime_ns` and `sha256` of a staged add are in `working.json` and are empty until C2.
  - C3: `_recover` in `sync.py` remains. A file that the user unstages during its upload is
    still committed by that push. The pending commit closes this.
  - C3, from the verifications of C2:
    - `attempt_state` of a staged add holds only `"ready"` or nothing. C3 extends it.
    - After the service refuses a commit because an upload holds a different file
      (`UPLOAD_INELIGIBLE`), each push repeats the refusal until the user runs `huron add` again.
      The message has no hint to stage the file again.
    - The push check runs for each file immediately before its send, not for all files before
      the first send. A change in a later file stops the push after the earlier uploads.
    - The hint `huron rm <rel_path>` is not correct for a path that starts with `-`.
  - C4, from the verifications of C2:
    - `docs/concepts/raw-ingest.md` lines 128-132 say that `add` reads only the size. No task
      owns these lines. Correct them in C4 or in plan 4, task D6.
    - `IMPLEMENTATION_PLAN.md` line 2969 names `sha256_file`, which C2 removed.
  - Owner decisions that C2 left open, not in a task:
    - A named directory that the CLI cannot list gives a warning and exit code 0. A named file
      that the CLI cannot read stops the command with exit code 2.
    - The help of `add` says "The CLI does not follow symbolic links". A link in a parent
      component of a named path is followed, and the file is recorded at its real location.
    - `huron add a.txt a.txt` gives a collision message that names the same path two times.
    - `src/huron/pkg/hashing.py` keeps `EMPTY_SHA256`, which only tests use, and a
      `from __future__ import annotations` line that it does not need.
  - C4: the exit-code table of `docs/user-guide.md` does not name the busy locks (exit code 6)
    or the format, read and save errors (exit code 1). `mount_prefix` matters to `huron adm`
    only.
  - Not in a task: a `current_collection` in `config.yaml` that is not a string gives an
    unexpected `TypeError`. `delete_tokens` and `delete_draft` give an unexpected failure when
    the unlink fails. The push steps in `docs/concepts/raw-ingest.md` and
    `docs/adr/0008-uploads-through-tusd.md` describe the old copy path (plan 4, task D6).
  - Plan 4: D4 needs a cluster context, D5 needs the storage operator, D7 needs Helm 3.
