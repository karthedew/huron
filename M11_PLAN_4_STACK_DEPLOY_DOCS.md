# M11 plan 4: CLI verbs, check, stacks, deployment and documentation

Read [M11_PLANS.md](M11_PLANS.md) first. This plan delivers the old tasks M11.8 to M11.13.

## How to read this plan

Each task below points to a task in `IMPLEMENTATION_PLAN.md`. The text of that old task binds:
its "Create or change" list, its tests and its "Verification" entry. This plan lists only the
changes to that text. Read the old task in full before the work.

M11.6 "Removals, the background runner and the sweep" has no task here. Plan 2 replaces it:
a removal is a step of a commit, and cleanup selects by database ID. Do not build `Unlinker`,
`Sweeper`, the removal lease or a sweep by modification time.

## Tasks

### D1 Share group and `adm repair` in the CLI (old M11.8)

- Changes to the old task:
  - A busy collection (409 `COLLECTION_BUSY`) gets a hint that names `huron status`.
  - No ACL reminder in any message.
- Verification: the old task's entry, and the web gate when `web/src/lib/cli.ts` changes.
- Dependencies: plans 1 to 3.
- Status: pending

### D2 The check and provisioning (old M11.9)

- Changes to the old task:
  - `huron adm check` reports a pending commit as information, not as drift. During a pending
    commit a directory can hold a mix of old and new files.
  - The check reports these entries and never removes them: a temporary name of a publication, a
    `.nfs*` file, a `.snapshot` directory, a file that no row names.
  - Provisioning also prepares `<root>/<org>/.huron-objects/` (mode 0700, service UID) for each
    organization, and `.tus-uploads`.
  - `huron adm check` skips `.huron-objects`. It is a reserved name, not drift.
  - `huron adm check` reports a `.huron-link-probe-*` file that is older than one hour, in an
    organization directory or its object area. A killed readiness probe can leave one. The
    check does not remove it.
  - Provisioning must work with the API stopped. It reads its input from a file and makes no
    API request in that mode.
- Verification: the old task's entry.
- Dependencies: D1.
- Status: pending

### D3 Development stacks and the integration tier (old M11.10)

- Changes to the old task:
  - Images: `tusproject/tusd:v2.10.1` and `nginx:1.31.8`, with `--pull=never`.
  - The tusd flags and the nginx block are those of "Recommended tusd flags" and "Recommended
    nginx configuration" in the S1 results of plan 2.
  - A step removes the stale `*.lock` files in `.tus-uploads` before tusd starts. This is safe
    only with one tusd, after the old one is gone. The stack must not start a second tusd.
  - Tests through nginx: a chunk of 64 MiB passes, and a `PATCH` of 2 MiB passes the
    authorization location.
  - `scripts/dev-login.sh` stays as it is.
  - The integration tests cover: new, overwrite, remove, empty file, resume after an interrupted
    `PATCH`, a final `PATCH` with no answer, a late completion after a newer commit, a token of
    another user on `HEAD` and `PATCH`.
  - Remove the skip of `tests/integration/test_cli_end_to_end.py`.
  - The NOAA demo runs two times on the same stack. The second run makes no upload and no commit.
- Verification: the old task's entry, `uv run pytest -m integration`, `scripts/e2e.sh`,
  `make demo-noaa` two times.
- Dependencies: D2.
- Status: pending

### D4 Kustomize base and the local cluster (old M11.11)

- Changes to the old task:
  - One API replica with the `Recreate` strategy. The manifest test fails on a replica count
    other than 1.
  - One tusd, in the same pod or with the same `Recreate` rule. A step before tusd starts
    removes the stale `*.lock` files in `.tus-uploads`. The manifest test fails when this step
    is present and the replica count is not 1.
  - Readiness includes the hard-link probe of plan 2 for each organization directory.
  - `terminationGracePeriodSeconds` is longer than the longest seal that the settings allow.
  - Readiness: probe timeout 3 s, period 5 s, failure threshold 3. Liveness does no NFS call.
  - The smoke test logs in on the host only. It copies no token into a pod. It runs
    `huron adm check --hash` from the host mount.
- Open item: `kubectl` is on this workstation. A local cluster tool is not. The owner supplies a
  cluster context before this task starts.
- Verification: the old task's entry.
- Dependencies: D3.
- Status: pending

### D5 Measurements on the ONTAP export (part of old M11.13)

- Intent: the facts that only the real export can give. This task needs the storage operator.
- Measure on a private directory of the export, and record the commands and the output:
  1. Setgid inheritance: the procedure of the old plan (directory `2750 U:S`, then `mkdir`,
     `touch`, `stat` as the service UID).
  2. A hard link from the object area to a collection directory of each organization root.
  3. A rename over a file that a reader on another client holds open, and a removal of a file
     that a process on the same client holds open. Record what the directory then lists.
  4. The time to copy and hash 10 GiB through the mount. Compare it with the tusd hook timeout.
  5. What `statvfs` reports with the export's quota and snapshot settings.
- A result that contradicts the design of plan 2 stops this plan. Correct the design first.
- Verification: the record is in `docs/operator.md` under a dated heading.
- Dependencies: D2. This task can run as soon as the operator is available.
- Status: pending

### D6 Documentation (old M11.12)

- Changes to the old task. Add:
  - The publication model: accepted, pending, mixed visibility during a pending commit.
  - The single-writer rule: never two writable pods, and what the API does when it loses its lock.
  - The blocked request: how to read it, `retry`, `abandon`, and the manual procedure for a
    request with done steps and a lost object.
  - Capacity settings and the upload lifetime.
  - Backup: PostgreSQL and the lake must be restored to the same point. A restore of one of them
    alone is not supported.
  - A reader on another client can get a stale-handle error after a file is replaced.
  - Add a supersession note to `docs/adr/0008-uploads-through-tusd.md`. Keep its history.
- Verification: the old task's entry, `make docs-check`, `uv run python scripts/ste_check.py`.
- Dependencies: D4, D5.
- Status: pending

### D7 Helm chart and production values (old M11.13)

- Changes to the old task:
  - The chart allows one writable replica only. The schema refuses another value.
  - The values include the capacity settings and the upload lifetime, with no unlimited default.
- Open item: Helm is not on this workstation. The owner supplies Helm 3 or a cached image.
- Verification: the old task's entry.
- Dependencies: D5, D6.
- Status: pending
