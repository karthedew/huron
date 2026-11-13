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
- Status: complete (verification 3 of 3 passed, 2026-11-12). Verifications 1 and 2 failed on small
  findings in the tests and the help text. Coverage: 11680 statements with 2 missed before,
  11755 with 0 missed after. `web/src/lib/cli.ts` did not change, so the web gate did not run.
  For D2: `docs/concepts/raw-ingest.md` and `docs/concepts/access-and-roles.md` still say that
  the CLI has no `adm provision-catalogs`.

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
- Status: complete (verification 8 passed, 2026-11-12). Verifications 1 to 7 failed on small
  findings, and the owner authorized each cycle after the third. The gate at the last
  verification: 4487 tests passed, 24 deselected, 0 skipped; 12332 statements, 0 missed; 68
  clones in 25 groups against the baseline of 69 in 25. See "Escalation (D2, 2026-11-12)" for
  the verification reports and the owner decisions. That section is a record: the escalation
  is closed.

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
- Status: complete (verification 5 passed, 2026-11-12). Verifications 1 to 4 failed. The owner
  raised the limit to 10 verifications after the third. The runs at the last verification:
  `make gate` with 4515 tests passed, 39 deselected, 0 skipped, 12332 statements, 0 missed and
  68 clones in 25 groups against the baseline of 69 in 25; `uv run pytest -m integration` with
  39 passed; the web gate; `scripts/e2e.sh`; `make demo-noaa` two times on a private stack,
  where the second run made no upload and no commit. `make app` and `make up` were not run
  with their default project names: their parts ran in private projects. See "Escalation (D3,
  2026-11-12)" for the verification reports, the owner decisions, a defect for a later task
  and an open question for the owner. The record of the fix passes follows. Verification 4
  failed on one documentation finding: the two
  development stacks share one lake and keep separate databases, and no document said so.
  - Fix pass 5, text only:
    - `README.md` has a section "One lake, two databases". It says that the catalog directories
      of one stack stop the seed, the demo or a create of the same catalog on the other stack
      with `STORAGE_FAILED`. It gives the two ways before a change: delete the directories as in
      step 2 of the reset procedure, or give one stack a lake of its own, with the variables for
      `make app`, `make api`, `make uploads` and `make demo-noaa`. It also says that a token of
      one stack is not valid on the other. The Quick start, the reset procedure,
      `web/README.md` and `examples/noaa/README.md` link to it.
    - The custom-lake paragraph of `README.md` says that each later `make app` needs the three
      variables again, that `make demo-noaa` needs `HURON_LAKE_PATH`, and that the variables must
      not be exported.
    - The repair command of `examples/noaa/README.md` uses `$HOME` in place of `~`.
    - An interaction review asked, for each ordered pair of the development commands, the
      custom lake, `scripts/e2e.sh`, the web e2e tests and the integration tier, whether the
      second still works as the documents say after the first. It looked at the shared lake and
      its markers, `.tus-uploads`, the two database volumes, the ports, the CLI configuration and
      tokens, the image tags and the owner of the files. It used the Makefile, the compose files,
      the scripts and the code, and ran no stack.
  - `make gate` after fix pass 5 exits 0: 4515 passed, 39 deselected, 0 skipped. 12332
    statements, 0 missed. 68 clones in 25 groups against the baseline of 69 in 25.
  - Earlier: verification 3 failed on one documentation finding in `README.md`: four places said
    to run `make app-reset` and then `make app` with no step between them. The owner raised the
    limit to 10 verifications for each D task on 2026-11-12.
  - Fix pass 4, text only:
    - `README.md` has one procedure, "Start again with an empty database": `make app-reset`,
      delete the catalog directories in the three organization directories and keep `.huron`
      and `.huron-objects`, then `make app`. The four places give it or link to it. It also says
      what to do when `make app` already failed in that way.
    - `examples/noaa/README.md` links to the procedure. It also tells how to continue after a
      load stopped and its catalog directory was deleted: `huron adm repair planetary
      --recursive` with the CLI of the demo, then `make demo-noaa` again. A run on a private
      stack confirmed the error and this recovery.
    - `docs/architecture.md` gives port 1080 for each stack: `make app` publishes it on
      127.0.0.1, and nginx of `make uploads` listens on each interface.
    - A sweep by behaviour listed what D3 changed in the development workflow. It then read the
      stack parts of `README.md`, `web/README.md`, `examples/noaa/README.md`,
      `docs/architecture.md`, `docs/operator.md`, `AGENTS.md`, `CONTEXT.md`, the `Makefile`, the
      compose files, `huron.dev.yaml`, `dev.env`, `web/.env.example`, the headers of the scripts
      and `docker/seed/run.mjs`. It fixed more sentences that D3 made false. Examples: the API
      of `make api` does not start without `/data1/huron`, and `make app` and `make uploads`
      stop each other first. It did not read the other files of the repository.
  - `make gate` after fix pass 4 exits 0: 4515 passed, 39 deselected, 0 skipped. 12332
    statements, 0 missed. 68 clones in 25 groups against the baseline of 69 in 25.
  - Earlier: fix pass 3 was done. Verification 2 failed on one documentation finding:
    `examples/noaa/README.md` said that `make app` takes no uploads and that `load.sh` reuses
    the directories of a load after `make app-reset`.
  - Fix pass 3, text only: `examples/noaa/README.md` now names the two stacks of
    `make demo-noaa`, its steps and the second run. After `make app-reset`, the load stops at
    the catalog directory that is not empty, so delete that directory and keep `.huron` and
    `.huron-objects`. `web/README.md` says that the seed with `make api` needs `make uploads`
    and a prepared lake. A sweep of the tracked text files found no other sentence that D3
    made false.
  - `make gate` after fix pass 3 exits 0: 4515 passed, 39 deselected, 0 skipped. 12332
    statements, 0 missed. 68 clones in 25 groups against the baseline of 69 in 25.
  - Earlier: verification 1 failed on three findings:
    - F1: no integration test of an overwrite beside a part file of an earlier attempt.
    - F2: the seed of `make app` did not send its files through the proxy and tusd.
    - F3: the containers of the upload stack leaked when the stack of the CLI test failed to
      start.
    - Fix pass 2:
      - F1: a new test pushes an overwrite of `a.txt` beside `.a.txt.<UUID>.huron-part`. The new
        bytes are published, and the part file keeps its bytes.
      - F2: `docker/seed/run.mjs` reads `uploads_url` and sends each file with tus (a creation,
        then `PATCH` requests of at most 64 MiB, the user's token on each). `seed.mjs` keeps the
        lake path for the web e2e stack, which has no tusd. The seed no longer mounts the lake,
        and it waits for the healthy proxy.
      - F3: `UploadStack.start` and the stack of the CLI test remove what they started when a
        step fails. Unit tests fake the container runtime at the `subprocess` boundary. A real
        failure (a held proxy port) left no container.
      - Also: tusd of `make app` starts after `lake-init`. The stale commit of the late-completion
        test must give `BASE_VERSION_CONFLICT`. The tests read the hook timeout from the compose
        file.
    - `make gate` exits 0: 4515 passed, 39 deselected, 0 skipped. 12332 statements, 0 missed. 68
      clones in 25 groups against the baseline of 69 in 25.
    - `uv run pytest -m integration`: 39 passed, 0 skipped, 119 s.
    - Web gate: `npm run check` 0 errors and 0 warnings, `npm test` 1649 passed, `npm run lint`
      and `npm run build` exit 0, `npm run test:e2e` 245 passed.
    - `scripts/e2e.sh`: exit 0 in 38 s. Both pushes went through the proxy and tusd
      ("version 2 → 3, +2 −0 files", then "version 3 → 4, +2 −1 files"), and it ended with
      "e2e: ok".
    - One private stack (project `huron-d3demo`, its own API image, a lake in a scratch
      directory, `HURON_DEV_CONFIG` with that lake as `lake_path` and as each root):
      - tusd started after `lake-init` ended. A second `docker compose up` ran `lake-init` again
        and did not restart tusd.
      - The seed: exit 0 in 9 s. The proxy answered 124 `POST /files/` with 201 and 124 `PATCH`
        with 204. All 124 attempts are consumed, and 3 commit requests succeeded.
      - `make demo-noaa` run 1: exit 0 in 53 s, six uploads and six commits.
      - `make demo-noaa` run 2: exit 0 in 30 s. Each collection printed "nothing to push" and
        "metadata unchanged". The commits (9), the upload attempts (130) and the requests to the
        proxy (130 `POST`, 130 `PATCH`) did not change. Each collection stayed at version 3.
    - Adaptations to plan 2, for the verifier to judge. A link in place of a namespace directory
      blocks the commit (202, state `blocked`, `PUBLICATION_BLOCKED` with the reason
      `symbolic_link`), because the pre-finish hook now only seals into the object area. A commit
      that names an upload that is not `ready` gets 409 `UPLOAD_INELIGIBLE`. This replaces the
      commit without a receipt.
    - Choices where the plan is silent or old. The lock step runs in the tusd container before
      `exec tusd`, not in a one-shot `uploads-init`: a second `docker compose up` starts a
      finished one-shot service again while tusd runs. The fixed forwarded host and scheme are two
      more template variables, `HURON_UPLOADS_HOST` and `HURON_UPLOADS_PROTO`. The integration
      tests have no skip without Docker: they fail.

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

## Escalation (D2, 2026-11-12)

Task D2 "The check and provisioning (old M11.9)" failed its third verification. The workflow
stopped there. D3 to D7 were not started. D1 is complete (commit `a433b469`).

### State of the tree

- The D2 work is in the working tree and is not committed: 39 paths against `a433b469`
  (34 changed files, one renamed file and 4 new files). The renamed test file is staged as a
  rename (`tests/unit/cli/test_check_and_acl.py` to `test_check.py`).
- The tree is not broken. `make gate` exits 0 on it in each verification. The last run (fix
  pass 5): 4455 passed, 24 deselected, 0 skipped; 12325 statements, 0 missed (11755 with 0
  missed before D2); duplication 68 clones in 25 groups against the baseline of 69 in 25.
- `uv run python scripts/cli_reference.py --check`, `make docs-check` and both acceptance greps
  of old M11.9 pass.
- Nothing was reverted, because the gate passes and each open finding is small.

### Verification 1 (FAIL: one medium, three small)

1. Medium. `check_organization` reported `unreadable` for a correctly closed `0700` object area
   to each account other than the service user. `huron adm check` then exited 1 for those
   accounts. This contradicted "the check skips `.huron-objects`".
2. Small. The `unreadable` row of `docs/operator.md` disagreed with the help of `adm check`.
3. Small. `ORGANIZATION_STEPS` and `CATALOG_STEPS` in `adm.py` were public and were used only
   in that module.
4. Small. One elliptical sentence in `docs/concepts/raw-ingest.md`.

Accepted in this verification: `provision-catalogs` without `--uid`; the `Owner` value;
`prepare_lake` in place of `mark_lake`; `walk` that yields `unreadable` (each caller was
checked); `--config` on `provision-orgs` only, with no API request; the check gets a read-only
`ShareReader`.

### Verification 2 (FAIL: one medium, three small)

All findings of verification 1 were fixed.

1. Medium. `provision_catalogs` selected a catalog that the CLI cannot read. Section 3 says
   that such a catalog is not selected for that reason only.
2. Small. Two finding details in `check.py` broke strict STE (a fragment, and "it" without an
   antecedent).
3. Small. The tests held only some `PermissionDenied` refusals to both adapters. One test name
   was stale. The docstring did not name `context["error"]`.
4. Small. `test_status_refuses_a_collection_directory_that_is_a_link` asserted `exit_code != 0`
   and a substring.

Confirmed in this verification: the new `PermissionDenied(StorageError)` changes no behaviour
at a `StorageError` catch site, and the API contract is the same; a refused object area gives
exit 0; the `NEEDS_SHELL` marker complies (0 skipped).

### Verification 3 (FAIL: three small)

All findings of verification 2 were fixed. The verifier judged each finding below "fixable
within the current plan" and "not a plan defect".

1. Small. `src/huron/core/storage/provision.py`, `Provisioner.provision`: the root check
   `self._is_directory(place.base)` runs before `with self._named():`. A refused root check
   prints a path relative to the lake (`permission denied on data1/root`). The class docstring
   says that a refusal names an absolute path. Correction: run the root check inside `_named`,
   and add a test for the absolute path and the context.
2. Small. `Provisioner._give` prints the same place two times, absolute and relative (`the CLI
   cannot give /projects/huron/helio/heliophysics the group readers: helio/heliophysics:
   Operation not permitted`). A `StorageError` that is not `PermissionDenied` still names a
   lake-relative path in the provision steps (`data1/helio/.huron-objects: File exists`).
   Correction: remove the relative path from the `_give` reason; make `_named` translate the
   path of each `StorageError`, or narrow the docstring. Update the literal assertions.
3. Small. `docs/concepts/raw-ingest.md`, the `pending_commit` row: "Until it ends" can refer to
   the collection. Correction: "Until the request ends", as in `docs/operator.md`.

Residual notes of this verification (not findings):

- `adm check` exits 8 for a share that is not mounted. Section 6.4 says 2. The test
  `test_check_needs_the_share` asserted 8 before D2.
- A temporary name of a publication that is younger than 1 hour gives no finding.
- A `.nfs*` file or a `.snapshot` directory directly in an organization directory gives no
  finding. The check reports them only below a catalog.
- An account outside the service group gets `unreadable` for each organization directory.
- The `find` line of `catalog_script` enters a `.snapshot` directory inside a catalog. D5 can
  measure whether the export lists one there.
- The duplication baseline can go down from 69 to 68.

### Diagnosis

The plan as written can be implemented. No verification found a defect in the design of D2.

- The task is too large for one implementation agent and three verifications. Old M11.9 was
  almost not built: the `unreadable` walk, `Stat.uid`, the rewrite of `check.py`, owner changes,
  `provision-catalogs`, the file mode, and six plan-4 changes. The first pass took about two
  hours and changed more than 30 files.
- Each verification found a new class of small finding in a different part of that surface.
  Each fix pass fixed its list in full. Findings 1 and 2 of verification 3 come from `_named`,
  which fix pass 2 added in its own audit.
- The STE paragraph and antecedent rules are not checked by `scripts/ste_check.py`. Each
  verifier reads the text again and finds a different sentence.
- One point of the plan was not specified: the file and format for provisioning with the API
  stopped. The implementation chose the service configuration file (`HURON_CONFIG_FILE` form)
  through `huron adm provision-orgs --config`. Two verifiers accepted this choice.

### Questions for the owner

1. Is one more fix pass and one more verification for the three small findings of
   verification 3 authorized, as for S7 of plan 2 and C1 and C3 of plan 3? This is the
   smallest way forward.
2. Path names in provisioning messages: does each failure name an absolute path, or is a
   lake-relative path allowed for an error that is not a permission refusal?
3. Is the choice for the file mode accepted (`provision-orgs --config <service configuration
   file>`, `provision-catalogs` always through the API)? D3 builds `scripts/dev-provision.py`
   on it.
4. Does `huron adm check` report a `.nfs*` file and a `.snapshot` directory directly in an
   organization directory, or only below a catalog?
5. Does this task change the exit code of `adm check` for a share that is not mounted from 8
   to 2 (section 6.4), or does that stay for a later task?

### Owner decisions (2026-11-12)

1. Two more fix and verification cycles for D2 are authorized.
2. A provisioning message can name a lake-relative path for an error that is not a permission
   refusal.
3. The file mode is accepted: `huron adm provision-orgs --config <service configuration file>`
   makes no API request, and `huron adm provision-catalogs` always uses the API.
4. `huron adm check` reports a `.nfs*` file and a `.snapshot` directory directly in an
   organization directory, as below a catalog. Only `huron adm check` reports them. No command
   at user level reports them.
5. D2 can change the exit code of `huron adm check` for a share that is not mounted, so that it
   agrees with section 6.4 of `IMPLEMENTATION_PLAN.md`.

### Verification 4 (2026-11-12): FAIL

All findings of verification 3 were fixed. Fix pass 5 addresses these findings.

1. F1, medium. A link in an organization directory or in its object area stopped the check of
   every catalog of that organization: `_organization_findings` blocked on each error finding.
2. F2, small. The `check_organization` docstring said that the check looks into the object area
   for probe files only. It also reports links and entries that it cannot stat there.
3. F3, small. The `from_file` docstring said that it refuses what the API refuses. It accepted
   `service_group: 1234`, and it does not refuse a key that occurs two times.
4. F4, small. The `stale_part` row of `docs/operator.md` named only a stopped publication. A
   stopped write of `metadata.json` also leaves a part file.
5. F5, small. Three texts said that the catalog step changes every directory. Direct mode does
   not enter a `.snapshot` or `.huron-objects` directory. The script does not skip them.
6. F6, small. A regular file named `.snapshot` directly in a catalog or namespace directory gave
   no finding.

### Verification 5 (2026-11-12): FAIL

Fix pass 5 cleared the six findings of verification 4. The verifier's `make gate` exited 0: 4455
tests passed, 24 deselected, 0 skipped; 12325 statements, 0 missed; 68 clones in 25 groups. The
work is in the working tree and is not committed. No fix pass followed.

1. Medium. `huron adm check` reports a recorded file that is on the share as `file_missing` and
   exits with code 1. The naming rule `check_rel_path` accepts `.nfsconfig` and
   `.snapshot/a.txt` as paths in a collection.
   - `_files` in `src/huron/core/storage/check.py` skips each name that `is_ignored_entry`
     matches before it looks for the record. Thus `_missing` reports a recorded `.nfs*` file.
   - No walk enters a `.snapshot` directory (`UNWALKED` in `layout.py`). Thus `_missing` reports
     a recorded file below that directory.
   - `_unnamed` in `src/huron/applications/cli/commands/context.py` hides an unrecorded user
     file named `.nfs*` from `huron status`. Its docstring says that a commit cannot record
     such a name. That is false.
   - `DirectoryWriter.remove_collection` does not enter a user `.snapshot` directory. The cause
     is the same.
   - Smallest fix: in `_files`, look for the record first and skip a `.nfs*` name only when no
     row records it. In `_missing`, do not report a recorded file below a directory that the
     walk does not enter. Apply the same rule in `_unnamed`. Add a test of each case on both
     adapters.
2. Small. The `from_file` docstring in `src/huron/applications/cli/provisioning.py` says that
   its list of checks is complete. The code accepts a key with a null value as an absent key.
   The API refuses `service_uid: null`. Smallest fix: write "when present and not null" in the
   docstring, or refuse null values, and add a test.

Residual notes, not findings:

- A marker in an organization directory that is a symbolic link, or that the check cannot read,
  gives `symbolic_link` or `unreadable`. The organization stays trusted and the check continues
  with its catalogs.
- The duplication baseline can go down from 69 to 68.

Questions for the owner:

1. Do you authorize one more fix pass and one more verification for these two findings?
2. Must the naming rule of section 3 refuse a `.snapshot` segment and a name that starts with
   `.nfs`? If it does, the check can skip these names with no record lookup. If it does not,
   the check must look for the record first.
3. Must a marker that is a symbolic link, or that the check cannot read, stop the check of the
   catalogs of that organization?

### Owner decisions after verification 5 (2026-11-12)

1. One more fix pass and one more verification for D2 are authorized.
2. The naming rule refuses a path in a collection with a segment named `.snapshot` or a segment
   that starts with `.nfs`. The refusal is `rel_path_reserved`, as for the names of Huron. This
   changes the naming rule of section 3 of `IMPLEMENTATION_PLAN.md`. No row can record such a
   name, so the check skips a `.nfs*` file and does not enter a `.snapshot` directory, with no
   look at the records. `huron add --recursive` does not stage an entry with such a name and
   gives a warning for it.
3. Huron does not support symbolic links. A marker in an organization directory that is a
   symbolic link stops the check of the catalogs of that organization. A marker that the check
   cannot read gives `unreadable`, and the check continues with the catalogs.

### Verification 6 (2026-11-12): FAIL

Fix pass 6 cleared the two findings of verification 5 and applied the owner decisions. The
verifier's `make gate` exited 0: 4487 tests passed, 24 deselected, 0 skipped; 12332 statements,
0 missed; 68 clones in 25 groups. The work is in the working tree and is not committed. No fix
pass followed.

1. Small. `tests/fakes/storage.py`, the `Subtree` docstring and `_rooted`. The docstring says
   that a link that a read meets is named by its path below `base`. Only `stat` and
   `read_bytes` translate the path. `walk`, `open_file` and `is_empty` give the path in the
   share, and `PermissionDenied` is not translated. No test asserts a wrong path. Smallest fix:
   make the docstring name `stat` and `read_bytes` only.

Residual notes, not findings:

- A directory named `.huron` in an organization directory gives `unreadable`, and the
  organization stays trusted.
- `layout.py` exports `NFS_PREFIX` and `SNAPSHOT_DIR` again after they moved to `naming.py`.
- The warning "a collection cannot have this name" can be read as the name of the collection.
  "A path in a collection cannot have this name" is clearer.

Questions for the owner:

1. Do you authorize one more fix pass and one more verification for this finding?
2. Must a directory named `.huron` in an organization directory count as a missing marker and
   stop the check of the catalogs of that organization?
3. Do you accept that `huron add --recursive` does not stage an entry named `.snapshot` or
   `.nfs*` and gives a warning, and that a named file with such a name stops the command?

### Owner decisions after verification 6 (2026-11-12)

1. One more fix pass and one more verification for D2 are authorized.
2. The owner gave no answer to question 2. A directory named `.huron` in an organization
   directory keeps its behaviour.
3. The owner gave no answer to question 3. `huron add --recursive` keeps its behaviour and the
   text of its warning.

### Verification 7 (2026-11-12): FAIL

Fix pass 7 cleared the finding of verification 6. It changed only the `Subtree` docstring and
this plan. The verifier's `make gate` exited 0: 4487 tests passed, 24 deselected, 0 skipped;
12332 statements, 0 missed; 68 clones in 25 groups. The work is in the working tree and is not
committed. No fix pass followed.

1. Small, docstring only. `src/huron/applications/cli/provisioning.py`, lines 1 to 7, the
   module docstring. It says that "the provision commands" get their input from the API or
   from the service configuration file, and that they send no request to the API in file mode.
   Only `huron adm provision-orgs` gets its input from this module and has a file mode.
   `huron adm provision-catalogs` always sends requests to the API. Smallest fix: write
   "`huron adm provision-orgs`" in the two places.

The verifier found no other defect. It wrote: "If you judge it a residual, nothing else blocks
D2."

Question for the owner:

1. Do you authorize one more fix pass and one more verification for this finding, or do you
   accept D2 with this docstring corrected and no further verification?

### Owner decisions after verification 7 (2026-11-12)

1. One more fix pass and one more verification for D2 are authorized.

## Escalation (D3, 2026-11-12)

Verification 3 of 3 failed. The workflow stopped. No fourth fix pass was made.

### State of the tree

The D3 work is in the working tree and is not committed. The tree is green. The verifier's
runs at verification 3:

- `make gate`: exit 0. 4515 tests passed, 39 deselected, 0 skipped. 12332 statements, 0
  missed. 68 clones in 25 groups against the baseline of 69 in 25.
- `uv run pytest -m integration`: 39 passed, 0 skipped.
- The web gate: `npm run check`, `npm test` (1649 passed), `npm run lint`, `npm run build` and
  `npm run test:e2e` (245 passed) all pass.
- `scripts/e2e.sh`: exit 0.
- `make demo-noaa` two times on a private stack: the two runs exit 0. The second run made no
  upload and no commit.
- `make app` itself was not run. It builds the web image again with a tag that the owner
  uses. Each part of it, but not the web, ran on a private stack.

### Verification 1 (FAIL: three findings)

1. The integration test "an overwrite over a part file left by an earlier attempt" of old
   M11.10 was missing.
2. The seed of `make app` did not go through the proxy and tusd. Old M11.10 says that a seeded
   file goes through them.
3. `tests/integration/test_cli_end_to_end.py` left its containers when the stack did not
   start.

Fix pass 2 cleared the three findings. Verification 2 confirmed this.

### Verification 2 (FAIL: one documentation finding)

1. `examples/noaa/README.md` said that the API of `make app` has no lake and no tusd. Its
   section "After `make app-reset`" said that the load uses the directories of an earlier
   load again. D3 made the two statements false.

Fix pass 3 cleared the finding. Verification 3 confirmed this.

### Verification 3 (FAIL: one documentation finding)

1. `README.md` tells the reader to run `make app-reset` and then `make app` with no step
   between them. D3 made this false in four places: line 295, lines 299 to 303, lines 346 to
   348 and line 362. A seed of `make app` now makes the catalog directories in the lake.
   `make app-reset` keeps the lake. The next seed then gets `STORAGE_FAILED`, because a create
   command adopts only an empty directory, and `make app` fails. The paragraph of D3 at lines
   305 to 310 gives the correct procedure and contradicts the four places. The verifier
   confirmed the failure and the correct procedure on a private stack. Smallest fix, text
   only: make the four places give the procedure of lines 305 to 310.

Residual notes, not findings:

- After a load stops, the catalog row stays in the database. If the reader then deletes the
  directory, the next load stops with a different error and a hint for `adm repair`.
- `docs/architecture.md` line 393 says that nginx listens on 127.0.0.1:1080 in the two stacks.
  With `make uploads`, nginx listens on each interface.

### Diagnosis

The plan is implementable. No verification found a defect in the stacks or the code after fix
pass 2. The findings of verifications 2 and 3 are of one class: D3 changed what `make app` and
`make app-reset` do, and an older text that D3 did not edit became false. The sweep of fix
pass 3 searched for terms. It did not find the four places, because the text there has none
of the terms.

### Questions for the owner

1. Do you authorize one more fix pass and one more verification for this finding?
2. `make app-reset` keeps the lake, and the next `make app` fails until the reader deletes the
   catalog directories. Is a procedure in `README.md` sufficient, or must `make app-reset`
   also empty the catalog directories of the development lake?

### Owner decisions (2026-11-12)

1. Each D task of this plan can have up to 10 verifications.
2. The owner gave no answer to question 2. So `make app-reset` keeps the lake, and `README.md`
   gives the procedure.

### Verification 4 (2026-11-12): FAIL

1. The two development stacks share one lake and keep separate databases, and no document said
   so. `make app` keeps its rows in the volume `huron-app_postgres-data`. `make up` and
   `make api` keep their rows in the volume `huron_postgres-data`. Both stacks read
   `huron.dev.yaml`, whose `lake_path` is `/data1/huron`. A seed, `make demo-noaa` or a create
   command on one stack makes catalog directories in the lake. The database of the other stack
   does not record them. A create command adopts only an empty directory. So the seed, the demo
   or a create on the other stack stops at its first catalog with `STORAGE_FAILED`. The
   verifier confirmed this with the host seed command of `web/README.md`: exit 1 with that 500.

### Defect for a later task

The verifier judged this defect outside D3. It comes from D1 (commit `a433b469`).

- `repair_hint` in `src/huron/applications/cli/errors.py` (lines 107 to 117) gives the hint "to
  make the directory again, run `huron … adm repair …`". `hint_repair` in
  `src/huron/applications/cli/commands/common.py` (line 261) applies it to `create org`,
  `create catalog` and `create namespace`. It gives the hint for each `STORAGE_FAILED`, also for
  "exists and is not an empty directory".
- A repair then adopts the directory that is not empty (`Repairer._run`,
  `src/huron/core/storage/repair.py` lines 161 to 172) and exits 0. The files that no row
  records stay in the catalog.
- Smallest fix: give no repair hint for that refusal, or make the repair refuse a directory that
  is not empty and that no row records. Add a test.

### Question for the owner (after verification 4)

1. Must `make app` and `make up` with `make api` have different default lake directories, so
   that one stack cannot stop the other?
