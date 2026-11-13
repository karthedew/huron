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
