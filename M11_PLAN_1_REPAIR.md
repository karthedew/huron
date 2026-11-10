# M11 plan 1: finish and accept the repair task (M11.5e)

Read [M11_PLANS.md](M11_PLANS.md) first. This plan finishes the task that stopped the old plan.

## Context

The M11.5e work is uncommitted on `tusd-integration`, on top of commit `0dcdf1ff`. It failed three
verifications. The old plan records the findings in "Escalation (M11.5e, 2026-11-08)" and the
owner's answers in "Resolution (2026-11-08, the user's answers)". Those four rules bind this plan:

1. The contract suite is the specification of the storage port. `MemoryStorage` stays a full
   adapter and passes every row. `PosixStorage` is the reference.
2. A repair failure at `metadata.json` or at its part file sets `path` to that file.
3. The rules for `path`, `reason` and `detail` live only in the Field descriptions of
   `RepairFailureOut`. `docs/api-errors.md` links to that schema.
4. One fix pass, then a new verification cycle of at most three verifications.

The task text of M11.5e in `IMPLEMENTATION_PLAN.md` (the "Create or change" list and the
"Verification" greps) stays the definition of done.

Do not change these parts of the dirty tree in this plan: `.agents/`, `.opencode/`,
`opencode.json`, and any file that M11.5e does not name.

## Tasks

### R1 Baseline and inventory

- Intent: know what the dirty tree holds before a change.
- Do:
  - Run `git status` and `git diff --stat`. Sort each changed file into one of three groups:
    M11.5e product work, agent tooling, other.
  - Run `make gate` and `uv run pytest -m contract`. Record the counts and the coverage.
  - Read the dirty code for the two defects of verification 3. Record for each defect if the
    tree already holds a fix. The task resumed on 2026-11-08, so a fix can be present.
  - `git diff --check` reports trailing whitespace at `web/src/lib/api/openapi.ts:170`. That file
    is generated. Record it. Task R3 generates the file again.
- Verification: the record is in this file under "Ledger". No source file changed.
- Dependencies: none.
- Status: complete (verification 2 of 3 passed, 2026-11-10)

### R2 Part-file behaviour of `MemoryStorage.write_bytes`

- Intent: verification 3, defect 1. The two adapters must agree on the part file.
- Create or change:
  - Section 3 "The disk-access module" needs the table "Errors per port method" (rule 1). The old
    plan is not edited. Put the table in `tests/unit/storage/` as the parameter list of the
    contract test, with one row for each port method and case.
  - `src/huron/core/storage/memory.py`: `write_bytes` follows POSIX `atomic_write` in
    `src/huron/pkg/fs/posix.py`. A directory at `<name>.huron-part` is refused and nothing
    changes. With a directory at `<name>` and an old part file, the part file is removed and the
    write then fails.
  - Tests: the two cases over `MemoryStorage` and `PosixStorage(root=tmp_path)`. The remaining
    rows of rule 1 for every port method that the repair uses.
- Verification: `make gate`. No `startswith` assertion hides a path difference between adapters.
- Dependencies: R1.
- Status: complete (verification 2 of 3 passed, 2026-11-10)

### R3 One source for the repair failure contract

- Intent: verification 3, defect 2, under rules 2 and 3.
- Create or change:
  - `src/huron/core/storage/repair.py`: a failure at `metadata.json` or at its part file sets
    `path` to that file, in the API form.
  - `src/huron/applications/api/routes/v1/schema/repairs.py`: the Field descriptions of
    `RepairFailureOut` state the rules once.
  - `docs/api-errors.md`: link to the schema. Remove the restated cases.
  - Docstrings of `FailureReason`, `RepairFailure` and `_detail`: one sentence each, no case list.
  - `make openapi`. From `web/`, `npm run generate:api`.
  - Tests in `tests/unit/api/test_repair.py` and `tests/unit/storage/test_repair.py`: a directory
    at `metadata.json`, `EACCES` and `EIO` on it, a link at it and at its part file. Each asserts
    the exact `path`, `reason` and `detail`.
- Verification: `make gate`, `uv run pytest tests/unit/api/test_openapi_snapshot.py`, and from
  `web/` `npm run check` and `npm test`. `git diff --check` prints nothing.
- Dependencies: R2.
- Status: complete (verification 1 of 3 passed, 2026-11-10)

### R4 Accept M11.5e

- Intent: close the task with its original definition of done.
- Do:
  - Run every command in the "Verification" entry of M11.5e in `IMPLEMENTATION_PLAN.md`.
  - Run `uv run pytest -m contract`.
  - An independent verification reads the diff against the M11.5e task text and the four rules.
  - After a pass, commit the M11.5e product work. Leave the agent tooling files for the owner.
- Verification: all commands exit 0, the greps print what the task text states, the branch
  `m11.5-escalated` exists.
- Dependencies: R3.
- Status: complete (verification 2 of 3 passed, 2026-11-10)

## Ledger

Record the baseline of R1 and the result of each verification here.

### R1 baseline (2026-11-10)

The tree is on `0dcdf1ff`. R1 changed no file except this one.

#### Files

`git status --porcelain=v1 --untracked-files=all` lists 105 entries. Three are staged deletions
in `.agents/` (`git diff --cached --stat`: 3 files, 500 deletions). `git diff --stat` gives 73
tracked files, 3306 insertions and 1292 deletions.

| Group | Count | Files |
| --- | --- | --- |
| (a) M11.5e product work | 33 | See the list below |
| (b) Agent tooling | 41 | All entries in `.agents/` (36, with 4 new `huron-*` skills), `.opencode/` (4), `opencode.json` |
| (c) Plan and design documents | 14 | `IMPLEMENTATION_PLAN.md`, `IMPLEMENTATION_PLAN_LATEST.md`, `M11_PLANS.md`, `M11_PLAN_1` to `M11_PLAN_5`, `HANDOFF_M11_PLAN.md`, `HANDOFF_MEDIUM_WORKFLOW.md`, `REPOSITORY_READINESS.md`, three files in `design/` |
| (d) Other | 17 | See the table below |

Groups (c) and (d) together are the group "other" of the R1 task text.

Group (a), named by the "Create or change" list of M11.5e, its binding items, or rules 1 to 3:

- New: `src/huron/core/lake/repairs/` (`__init__.py`, `models.py`, `operations.py`),
  `src/huron/core/storage/repair.py`, `src/huron/applications/api/disk/repair.py`,
  `routes/v1/endpoints/repairs.py`, `routes/v1/schema/repairs.py`,
  `tests/unit/api/test_repair.py`, `tests/unit/lake/test_repairs.py`,
  `tests/unit/storage/test_repair.py`.
- Changed source: `pyproject.toml`, `core/lake/bootstrap.py`, `core/storage/__init__.py`,
  `core/storage/ports.py`, `core/storage/posix.py`, `core/storage/memory.py`, `pkg/fs/posix.py`,
  `schema/naming.py`, `applications/api/disk/__init__.py`, `applications/api/runtime.py`,
  `routes/v1/router.py`.
- Changed documents and generated files: `docs/api-errors.md`, `docs/openapi.json`,
  `web/src/lib/api/openapi.ts`.
- Changed tests: `tests/conftest.py`, `tests/support/disk.py`, `tests/unit/api/test_openapi_snapshot.py`,
  `tests/unit/lake/test_uploads.py`, `tests/unit/pkg/test_posix.py`,
  `tests/unit/schema/test_naming.py`, `tests/unit/storage/test_containment.py`,
  `tests/unit/storage/test_races.py`, `tests/unit/storage/test_storage.py`.

Group (d). The column "Tied to M11.5e" says if the change follows from the M11.5e work.

| File | Change | Tied to M11.5e |
| --- | --- | --- |
| `.gitignore` | Adds `/roadmap/` | No |
| `AGENTS.md` | Agent-tooling links and an "Offline and approved setup" rule | No |
| `docs/agents/domain.md` | New domain guide for agents | No |
| `docs/concepts/access-and-roles.md` | ACL text replaced by directory modes and share groups. New section "Grant changes and directory repair" describes the repair endpoints and links to the repair failure schema in `docs/api-errors.md` | Partly. The ACL removal is the M11.9a follow-up. The repair-endpoint text and the repair-schema link need M11.5e. Neither exists at HEAD |
| `docs/concepts/raw-ingest.md` | Segment limit 206 bytes, API makes the directory, ACL text removed. "Drift detection" adds repair-endpoint text and a link to the repair section of `access-and-roles.md` | Partly (the 206-byte binding item, the repair-endpoint text and the repair-section link) |
| `src/huron/core/storage/errors.py` | One docstring line: `SymlinkInLake` names the link in `context["path"]` | Yes |
| `src/huron/core/storage/placement.py` | `link` refuses a link at the source and prunes made directories on any failure | Yes (section 3 port table) |
| `src/huron/applications/api/disk/placements.py` | Docstring: a link at the upload's file fails the upload | Yes |
| `src/huron/core/lake/lookups.py` | New `rendered_sidecar` for the expected `metadata.json` | Yes (`Repairs.expected`) |
| `src/huron/core/lake/collections/lifecycle.py` | Uses `rendered_sidecar` | Yes |
| `tests/unit/api/test_lake_disk.py` | Expected path `""` becomes `.tus-uploads` | Yes (port table) |
| `tests/unit/api/test_lifespan.py` | Test that `Runtime` sets `SERVICE_UMASK` before the disk pools | Yes (umask note of the table) |
| `tests/unit/api/test_upload_hooks.py` | Test for a link at the upload's file after the hash | Yes (port table) |
| `tests/unit/storage/test_placement.py` | Tests for a link at the source and a missing `.tus-uploads` | Yes (port table) |
| `web/package.json` | `npm` calls become `node "$npm_execpath"` | No |
| `web/docs-site/package.json` | The same change | No |
| `web/scripts/npm-scripts.test.mjs` | New test of those scripts | No |

`IMPLEMENTATION_PLAN.md` (group c) already holds the table "Errors per port method" in section 3
(about lines 578 to 906). It also holds the escalation and resolution of M11.5e.

#### Gate

| Command | Exit | Result |
| --- | --- | --- |
| `UV_OFFLINE=1 UV_NO_SYNC=1 make gate` | 0 | `2636 passed, 2 deselected, 1 warning in 146.80s`. Coverage 99.98% (9691 statements, 2 missed, `cli/identifiers.py` 76-77) |
| `UV_OFFLINE=1 UV_NO_SYNC=1 uv run pytest -m contract` | 0 | `59 passed, 2579 deselected, 1 warning in 25.00s` |
| `uv run pytest tests/unit/api/test_openapi_snapshot.py` | 0 | `2 passed` |

The results agree with the orchestrator's baseline. The one warning is the `testcontainers.postgres`
deprecation.

#### Defects of verification 3

Defect 1, the part file of `MemoryStorage.write_bytes`: fixed in the tree, with tests.

- `core/storage/memory.py:204-212` follows `atomic_write` (`pkg/fs/posix.py:258-264`). The order:
  link at the name, part-file check (line 207), write permission, removal of an old part file,
  `EISDIR` for a directory at the name.
- A directory at `<name>.huron-part` raises `EISDIR` at the part file, and nothing changes.
- A directory at `<name>` with an old part file removes the part file, then raises `EISDIR` at `<name>`.
- The parametrized contract test (rule 1) exists:
  `test_each_port_method_answers_each_case_as_the_table_says` in `tests/unit/storage/test_containment.py:623`.
  It runs 253 rows over `PosixStorage(tmp_path)` and `MemoryStorage`.
- Its rows cover 16 methods: `stat`, `read_bytes`, `is_empty`, `walk`, `open_file`,
  `make_directory`, `make_inheriting_dir`, `set_mode`, `set_group`, `write_bytes`, `link`,
  `link source`, `rename`, `rename source`, `remove_file`, `remove_directory`.
- The two cases are rows `write_bytes`/`dir_at_part` (line 402) and `write_bytes`/`part_and_dir`
  (line 405). Combined rows are at lines 482, 531, 540 and 541. All 6 parametrized cases of the two rows and `old_part` pass.
- `test_each_pair_of_cases_that_can_hold_at_once_has_one_row` (line 617) checks the combined rows.
- `in_group` has no row. It has no error case.

Defect 2, the repair failure contract: fixed in the tree.

- Rule 2: `RepairFailure.of` (`core/storage/repair.py:69-74`) takes `path` from
  `error.context["path"]`. The storage errors at `metadata.json` and its part file name that file.
- Tests assert the exact `path`, `reason` and `detail` at the file:
  `tests/unit/storage/test_repair.py:220` (link at the file and at the part file),
  `:241` (directory at either), `:255` (`EACCES`), `:280` and `:313` (`EIO` and `EACCES` on the part file).
- API tests: `tests/unit/api/test_repair.py:269` (link at `metadata.json`), `:279` (directory at
  it), `:387` and `:412` (`EIO`, `EACCES`, `ENOSPC`, `ENOENT` on the part file and the rename).
- Gaps for R3:
  - No test injects `EIO` on a read of `metadata.json` itself. This gap is in `tests/unit/storage/test_repair.py` and `tests/unit/api/test_repair.py`.
  - No `fail_file_io` or `fail_write_cleanup` call in `tests/unit` targets the name `metadata.json`. All target the part file.
  - `tests/unit/api/test_repair.py` has no `EACCES` on `metadata.json` itself.
  - The storage test at `:255` does it on POSIX with mode 000 on the file. On `MemoryStorage` it denies the directory.
  - The API case `open`/`EACCES` (`:412`) is a gap too. The fault is on the create of the part file.
  - The directory refuses that create, so the error names `metadata.json`. It tests the path form, not an error on the file itself.
  - The API tests have no link at the part file.
- Rule 3: the rules are in the Field descriptions of `RepairFailureOut`
  (`routes/v1/schema/repairs.py:32-60`). `docs/openapi.json` and `web/src/lib/api/openapi.ts` match them.
- `docs/api-errors.md:70-76` links to the schema and restates no case.
- One-sentence docstrings: `FailureReason` (`repair.py:44`), `RepairFailure` (`:53`), `_detail` (`:239`).
- `RepairFailure.of` (`:63-67`) restates the base rule for `path`. Rule 3 does not name that docstring.
- The `Repairer.repair` docstring (`:134-148`) also restates rules. Its steps (`:136-142`) give the reason for each case.
- Lines `:145-147` of that docstring restate how a failure names its place.
- The module docstring line "A failure names the place that failed" (`:9`) restates a little.
- The `RepairResult.combine` docstring (`:90-94`) restates a little: a link above several steps fails each, reported once.

#### `git diff --check`

It prints nothing and exits 0. `git diff HEAD --check` and `git diff --cached --check` also print
nothing. The trailing whitespace in `web/src/lib/api/openapi.ts` (lines 215, 231, 267, 326) is in
lines that the diff does not change. Line 170 has no trailing whitespace.

#### Read-only commands of the M11.5e verification

| Command | Required result | Now |
| --- | --- | --- |
| `grep -rnE "\bon_error\b\|DirectoryPlan\|..." src/huron tests` | Nothing | Pass |
| `grep -rn "^MODE_DRIFT" src/huron` | Nothing | Pass |
| `grep -n "walk" core/storage/repair.py core/lake/repairs/*.py` | Nothing | Pass |
| `grep -rn "Level" src/huron/core/storage` | Nothing | Pass |
| `grep -n "symbolic_link" docs/openapi.json` | The reason enum | Pass. Line 736 is the enum. Lines 1744 and 1750 are descriptions |
| `grep -rn "symlink" ... \| grep -v "follow_symlinks=False"` | Only `MemoryStorage.symlink` and the literal `"symlink"` | Pass (`memory.py` 27, 83, 91, 350, 367, `directories.py` 104, `pkg/fs/posix.py` 7, 56, 490) |
| `git branch --list m11.5-escalated` | The branch | Pass |

`pkg/fs/posix.py:7` is a docstring that names the kind `symlink`. A verifier can read it as the literal.

#### Notes for R2 to R4

- R2: the fix and its contract rows exist and pass. R2 shrinks to a review of the rows against rule 1.
- R2: the old plan already holds the table, although R2 says not to edit the old plan.
- R2: `tests/unit/storage/test_repair.py:648` asserts `startswith` on a `MemoryStorage`-only detail.
- R2: `:632` asserts only `failed.detail.split(" ")[0]`, also on `MemoryStorage` only. Neither assertion compares adapters.
- R3: the code, Field descriptions, generated files and docs already follow rules 2 and 3.
  The docstrings above are the exception. They still restate some rules.
- R3 still has this work:
  - Storage and API tests: `EIO` on a read of `metadata.json` itself.
  - API test: `EACCES` on `metadata.json` itself.
  - API test: a link at the part file.
  - Remove the restated rules from the docstrings of `RepairFailure.of`, `Repairer.repair`, `RepairResult.combine` and the module (rule 3).
  - Run `make openapi`. From `web/`, run `npm run generate:api`, `npm run check` and `npm test`.
  - Run `uv run pytest tests/unit/api/test_openapi_snapshot.py` and `git diff --check`.
- R4: 9 files of group (d) are tied to M11.5e. Commit them with group (a).
- R4: two files of group (d) are tied in part: `docs/concepts/access-and-roles.md` and `docs/concepts/raw-ingest.md`.
  The commit split must decide their parts.
- R4: the commit split must also consider the `IMPLEMENTATION_PLAN.md` diff (481 insertions, 10 deletions).
  That diff holds the port table and the M11.5e escalation and resolution.

### R2 (2026-11-10)

No source file changed. The fix of `MemoryStorage.write_bytes` was already in the tree. The changes
are in `tests/unit/storage/`.

- Contract table (`test_containment.py`): 253 rows become 264. Before the change, the 253 rows
  agreed with the table in section 3 of `IMPLEMENTATION_PLAN.md`, one for one (checked by a
  script). The new rows are:
  - `make_directory` and `make_inheriting_dir` with a directory at the name: `False`.
  - `write_bytes` with a file at the name: `None`, P is a file, no part file.
  - `set_mode` with a file at the name: `True`. `set_group` with a file at the name: `PENDING`,
    `a/t: Operation not permitted`. Both again with no search permission on the parent: `EACCES`.
  - `link` with a file at the name: the backup, which is a file. `link` with the source missing:
    `SourceGone` at the source.
  - `rename` with a file at the name: `None`, and the source is gone. `rename` with the source
    missing: `ENOENT` at the source.
- The old plan's table does not have these 11 rows. The old plan was not edited.
- The table in section 3 of `IMPLEMENTATION_PLAN.md` is 11 rows behind the contract test, and the
  owner decides if it is updated.
- New test `test_each_part_of_a_combined_row_has_its_own_row`: a case in a combined row must also
  have its own row.
- Verification 3 cases, on both adapters: after `dir_at_part`, the lake is unchanged (the part
  directory and its entry stay). After `part_and_dir`, the part file is gone and the name is a
  directory.
- `test_repair.py`: the partial assertions now compare the full `RepairFailure`. They were in
  `test_a_link_above_the_steps_directory_fails_at_the_links_path`,
  `test_a_directory_that_did_not_inherit_is_mode_drift` and the memory-only test of the rooted
  base, `test_paths_are_relative_to_the_organizations_base`. That test was replaced by two tests
  on both adapters: `test_a_made_directory_is_named_relative_to_the_organizations_base` (a made
  catalog directory and a made collection directory) and
  `test_a_failure_is_named_relative_to_the_organizations_base_and_changes_nothing`, where each
  failure changes nothing. `Lake.frozen` compares the nodes and calls of `MemoryStorage`, and on
  POSIX a snapshot of the lake and of the directory outside it.
- The `match=` checks of storage errors in the tests on both adapters (`test_directories.py`,
  `test_storage.py`, `test_placement.py`) and the `in message` check of `test_organizations.py`
  now compare the exact message and context.

| Command | Exit | Result |
| --- | --- | --- |
| `UV_OFFLINE=1 UV_NO_SYNC=1 make gate` | 0 | `2685 passed, 2 deselected, 1 warning in 144.82s`. Coverage 99.98% (9691 statements, 2 missed, `cli/identifiers.py` 76-77). radon prints nothing |
| `UV_OFFLINE=1 UV_NO_SYNC=1 uv run pytest -m contract` | 0 | `59 passed, 2628 deselected, 1 warning in 25.29s` |

### R3 (2026-11-10)

No behaviour change. The repair reads `metadata.json` before it writes it:
`DirectoryWriter.write_metadata` calls `read_bytes` and writes only when the bytes differ.
`PosixStorage.read_bytes` opens the file, then reads it with `os.read`. `MemoryStorage` has no
I/O error and does not model the permission of a file, so the cases on the file itself run on
`PosixStorage` only.

- `core/storage/repair.py`: the docstrings of `RepairFailure.of`, `RepairResult.combine`,
  `Repairer.repair` and the module no longer restate the failure rules. `Repairer.repair` lists
  its steps and points to the Field descriptions of `RepairFailureOut`. The docstring of
  `RepairResult` now says that the API form applies to `changed`. Three docstrings lost a
  semicolon.
- `RepairFailureOut.reason`: `mode_drift` now also names a new directory that did not get the
  mode 2750 (the second check of `make_inheriting_dir`). The other cases agree with the code.
- `docs/openapi.json` and `web/src/lib/api/openapi.ts` regenerated. Only that text changed.
- `docs/api-errors.md`, `docs/concepts/access-and-roles.md` and `docs/concepts/raw-ingest.md`
  restate no failure case. No change.
- Storage tests (`tests/unit/storage/test_repair.py`):
  - `test_an_error_on_metadata_json_or_its_part_file_names_that_file_and_keeps_the_old_bytes`
    (was `test_a_part_inspection_error_names_the_part_and_preserves_metadata`) adds `EIO` and
    `EACCES` on the `read` of `metadata.json`, at both bases. Each case compares a snapshot of
    the lake.
  - `test_a_metadata_json_of_mode_000_on_the_disk_fails_at_that_file_and_changes_nothing`
    replaces the test with one mechanism for each adapter. It runs on `PosixStorage` only.
  - `test_a_new_directory_that_did_not_get_its_mode_is_mode_drift` (was
    `test_a_directory_that_did_not_inherit_is_mode_drift`) adds the umask case.
- API tests (`tests/unit/api/test_repair.py`):
  - `test_an_error_on_metadata_json_or_its_part_file_reports_that_file_and_keeps_it` (was
    `test_a_part_inspection_failure_reports_the_actual_api_path_and_keeps_metadata`) adds `EIO`
    and `EACCES` on the `read` of `metadata.json`, and compares a snapshot of the lake.
  - `test_a_metadata_json_of_mode_000_is_reported_at_that_file_and_kept`: `EACCES` on the file
    itself, for both organization forms.
  - `test_a_link_at_metadata_json_or_its_part_file_is_refused_and_changes_nothing` (was
    `test_a_link_at_metadata_json_is_refused`) adds the part file. It compares snapshots of the
    lake and of the directory outside it.

| Command | Exit | Result |
| --- | --- | --- |
| `UV_OFFLINE=1 UV_NO_SYNC=1 make gate` | 0 | `2696 passed, 2 deselected, 1 warning in 149.24s`. Coverage 99.98% (9691 statements, 2 missed, `cli/identifiers.py` 76-77). radon prints nothing |
| `UV_OFFLINE=1 UV_NO_SYNC=1 uv run pytest -m contract` | 0 | `59 passed, 2639 deselected, 1 warning in 24.70s` |
| `uv run pytest tests/unit/api/test_openapi_snapshot.py` | 0 | `2 passed` |
| `npm run check` (from `web/`) | 0 | 0 errors, 0 warnings |
| `npm test` (from `web/`) | 0 | 130 files, 1645 tests passed |
| `git diff --check` | 0 | Prints nothing |

### R4 (2026-11-10)

#### Part A: notes of the R3 verification

No behaviour change in `src/`. Only text and tests changed.

1. `RepairFailureOut.path` (`routes/v1/schema/repairs.py`) has a new sentence: "When the
   directory refuses to make or to delete the part file, or the rename of the part file fails,
   path is metadata.json." The code agrees:
   - `atomic_write` (`pkg/fs/posix.py`) gives a `PermissionError` on the create or the unlink of
     the part file, and any error of the `rename`, without the part-file name.
   - `PosixStorage.write_bytes` then names `metadata.json` (`_parent` maps the error).
   - `MemoryStorage.write_bytes` checks the permission of the directory before it removes the
     part file. Its error names `metadata.json`.
   - `RepairFailure.of` takes `path` from that error.
   - `docs/openapi.json` and `web/src/lib/api/openapi.ts` were regenerated.
2. `tests/unit/storage/test_repair.py`: the parametrized test is now
   `test_an_error_on_metadata_json_or_its_part_file_is_storage_failed_and_changes_nothing`.
   A new column gives the files in the directory before the repair. The test runs with `EIO` and
   `EACCES`, at both bases. The new rows:
   - `fstat-of-read`: the `fstat` of the read of `metadata.json`. It goes through `_guard`. The
     `open` of the read goes through the same mapping as the existing `read` row, so it has no
     row.
   - `lstat-of-write`: the `lstat` of `metadata.json` at the start of the write.
   - `removal-of-old-part`: an old part file that a crash left. `EIO` on its unlink names the
     part file. `EACCES` names `metadata.json`.
   - `part-fsync-of-new-file`: see item 5.
   - Each row asserts the exact `path`, `reason` and `detail`, an unchanged snapshot of the lake,
     and a second repair that writes the file and leaves no part file.
   - All cases use `fail_file_io`. No case needs a mock of the code under test.
3. `Repairer.repair`, item 2 of the docstring: "Below it, also check that the directory has the
   group of the catalog's directory."
4. `Repairer` class docstring: "Runs one RepairStep at a time and lists no directory. It deletes
   only one kind of directory: a directory that it made, without the mode 2750 or without the
   group of its parent." The docstring of `catalog_repair` (`routes/v1/endpoints/repairs.py`)
   also said "never deletes". That text is in `docs/openapi.json`. It now says: "It acts only on
   the directories that the rows plan and lists no directory. It deletes only a new directory
   that it made without the mode 2750 or without the group of its parent."
5. `test_an_input_output_error_while_syncing_metadata_names_the_part_file` is gone. The row
   `part-fsync-of-new-file` of the parametrized test replaces it: no `metadata.json` before the
   repair, and the error on the `fsync` of the part file.

Fix after verification 1: the text of item 4 said that a repair deletes only a new directory.
But `atomic_write` and `MemoryStorage.write_bytes` delete an old `metadata.json.huron-part`, and
`atomic_write` tries to delete its own part file after a failed write. The `catalog_repair` and
`Repairer` docstrings now say this, `docs/openapi.json` was regenerated (`openapi.ts` did not
change), and the gate counts did not change. `access-and-roles.md` now says that repair does
not change the permissions of data files and that a `metadata.json` it writes has mode `0644`
(`FILE_MODE`).

#### Part B: definition of done of M11.5e

| Command | Exit | Result |
| --- | --- | --- |
| `UV_OFFLINE=1 UV_NO_SYNC=1 make gate` | 0 | `2711 passed, 2 deselected, 1 warning in 151.07s`. Coverage 99.98% (9691 statements, 2 missed, `cli/identifiers.py` 76-77). radon prints nothing |
| `UV_OFFLINE=1 UV_NO_SYNC=1 uv run pytest -m contract` | 0 | `59 passed, 2654 deselected, 1 warning in 25.35s` |
| `uv run pytest tests/unit/api/test_openapi_snapshot.py` | 0 | `2 passed` |
| `npm run check` (from `web/`) | 0 | 0 errors, 0 warnings |
| `npm test` (from `web/`) | 0 | 130 files, 1645 tests passed |
| `git diff --check` | 0 | Prints nothing |
| Trailing whitespace in the 10 untracked product files | 1 (`grep`) | No match |

2711 is the R3 count 2696, plus 16 new cases (4 rows, 2 errors, 2 bases), minus the removed test.

The greps of the "Verification" entry:

| Command | Required result | Result |
| --- | --- | --- |
| `grep -rnE "\bon_error\b\|DirectoryPlan\|..." src/huron tests` | Nothing | Nothing |
| `grep -rn "^MODE_DRIFT" src/huron` | Nothing | Nothing |
| `grep -n "walk" core/storage/repair.py core/lake/repairs/*.py` | Nothing | Nothing |
| `grep -rn "Level" src/huron/core/storage` | Nothing | Nothing |
| `grep -n "symbolic_link" docs/openapi.json` | The reason enum | Line 736 is the enum. Lines 1744 and 1750 are descriptions |
| `grep -rn "symlink" ... \| grep -v "follow_symlinks=False"` | Only `MemoryStorage.symlink` and the literal `"symlink"` | `memory.py` 27, 83, 91, 350, 367, `directories.py` 104, `pkg/fs/posix.py` 7, 56, 490 |
| `git branch --list m11.5-escalated` | The branch | `m11.5-escalated` |

`pkg/fs/posix.py:7` is a docstring that names the kind `symlink`, as R1 records.

"Create or change" of M11.5e:

- `core/lake/repairs/`: done. `Level`, `PlannedDirectory`, `RepairPlan` with `catalog`,
  `PlannedRow` (`models.py`). `Repairs.plan`, `Repairs.organization`, `Repairs.expected` and
  `_Tree` (`operations.py`). `bootstrap.py` builds `Repairs`. `pyproject.toml` adds
  `huron.core.lake.repairs.models` and `huron.core.lake.repairs.operations` to the two lists of
  the `core.lake` contract.
- `core/storage/repair.py`: done. `FailureReason`, `RepairFailure`, `RepairResult.combine`,
  `RepairStep`, `Repairer.repair` with the order of the task text.
- `Storage.in_group`: done. `ports.py`, `PosixStorage.in_group` with `AUTH_SYS_GROUPS = 16`,
  `MemoryStorage.in_group` with `member_of`.
- `applications/api/disk/repair.py`: done. `LakeRepair.repair` locates every directory first,
  then runs one `hold` per directory, and a gone row gives no step. `Runtime` builds it only
  with `lake_path`.
- Routes: done. `catalog_repair` and `organization_repair` (`endpoints/repairs.py`),
  `RepairIn`, `RepairOut` and `RepairFailureOut` (`schema/repairs.py`), and `router.py`.
  `_require_lake` raises `LakeUnavailable` with the stated message and an empty `context`.
  `make openapi` and `npm run generate:api` ran.
- `tests/conftest.py`: done. `temporary_mode`.
- The branch `m11.5-escalated`: done. It exists.

"Tests" of M11.5e:

- `tests/unit/lake/test_repairs.py`: done.
  `test_a_recursive_plan_holds_every_namespace_and_settled_collection` (recursive plan, share
  group, `plan.catalog`), `test_a_plan_runs_from_the_catalog_down_to_its_target` (the row
  `sibling-prefix` is `solar` beside `solar-wind`), `test_a_target_must_be_a_directory_of_the_catalog`
  (other catalog, unknown, draft), `test_a_catalog_repair_needs_namespace_configure` and
  `test_an_organization_repair_needs_catalog_grant_admin`.
- `tests/unit/storage/test_repair.py`: done.
  - Missing: `test_a_missing_directory_is_made_with_its_mode`.
  - Wrong bits: `test_wrong_bits_are_set`. Right bits: `test_right_bits_get_no_chmod`.
  - Setgid bit and group: `test_a_missing_setgid_bit_is_mode_drift_with_no_chmod`,
    `test_a_directory_of_another_group_below_the_catalog_is_mode_drift`.
  - Outside the groups: `test_a_directory_outside_the_services_groups_gets_no_chmod`.
  - `chmod` that drops setgid: `test_a_chmod_that_still_drops_the_setgid_bit_is_mode_drift`.
  - Organization directory: `test_the_organization_directory_gets_its_mode`,
    `test_a_missing_organization_directory_is_made`.
  - Group attempt: `test_the_catalog_step_tries_the_share_group`,
    `test_the_catalog_step_keeps_a_matching_service_group`.
  - Non-directory: `test_a_non_directory_at_a_planned_path_is_storage_failed`.
  - Links: `test_a_link_at_the_steps_directory_is_symbolic_link_with_no_write`,
    `test_a_link_above_the_steps_directory_fails_at_the_links_path`.
  - Unreadable catalog directory: `test_an_unreadable_catalog_directory_is_storage_failed`.
  - Stale file: `test_a_stale_metadata_file_is_rewritten_and_an_equal_one_kept`.
  - Combine: `test_combine_keeps_each_path_warning_and_failure_once`. Idempotence:
    `test_a_repair_is_idempotent`.
- `tests/unit/storage/test_storage.py`: done.
  `test_posix_in_group_trusts_the_effective_group_and_the_first_16_groups`.
- `tests/unit/api/test_repair.py`: done.
  - Both routes: `test_a_catalog_repair_makes_a_missing_directory_and_sets_wrong_bits`,
    `test_the_organization_route_sets_the_mode_and_makes_a_missing_directory`.
  - Privileges and 503: `test_the_routes_check_the_privilege_first_and_need_a_lake`.
  - Gone row: `test_a_directory_whose_row_is_gone_before_its_step_is_not_made`.
  - Planned directories only: `test_a_recursive_repair_acts_only_on_planned_directories`.
    Siblings: `test_a_recursive_repair_of_a_namespace_leaves_its_siblings_alone`.
  - Real filesystem with a snapshot of `outside`:
    `test_an_unsearchable_namespace_is_repaired_and_a_link_below_it_is_refused`,
    `test_a_planned_directory_that_is_a_link_is_refused`,
    `test_a_link_above_two_planned_collections_fails_once_and_the_other_steps_run`,
    `test_a_link_at_metadata_json_or_its_part_file_is_refused_and_changes_nothing`.

"Found in M11.5c's verification (binding)":

1. Done. `change_mode` calls `os.chmod(name, mode, dir_fd=parent_fd, follow_symlinks=False)`.
   `change_group` calls `os.chown(name, -1, gid, dir_fd=parent_fd, follow_symlinks=False)`. The
   race tests in `tests/unit/storage/test_races.py` stay. The case over both adapters is
   `test_mode_and_group_change_on_a_directory_this_process_cannot_read` (`test_storage.py`,
   mode `02000`).
2. Done. `pkg/fs/posix.py` has no `is_symlink()`. It uses `statmodule.S_ISLNK`.
3. Done. `check_rel_path` refuses a segment longer than `REL_PATH_SEGMENT_MAX_BYTES` (206) with
   `rel_path_segment` (`schema/naming.py`). Tests: `tests/unit/schema/test_naming.py` and
   `test_begin_refuses_a_bad_path_a_long_name_and_a_negative_size` (`test_uploads.py`).
   `docs/concepts/raw-ingest.md` states the 206-byte limit.

No item is open.

#### Part C: the paths of the M11.5e commit

`git status --porcelain=v1 --untracked-files=all` lists 102 entries. 48 go into the commit.
54 stay out. No path is unplaced.

Include (48):

- Plans: `IMPLEMENTATION_PLAN.md`, `M11_PLAN_1_REPAIR.md`.
- Documents and generated files: `docs/api-errors.md`, `docs/concepts/access-and-roles.md`,
  `docs/concepts/raw-ingest.md`, `docs/openapi.json`, `web/src/lib/api/openapi.ts`.
- `pyproject.toml`.
- Source, changed: `src/huron/applications/api/disk/__init__.py`,
  `src/huron/applications/api/disk/placements.py`,
  `src/huron/applications/api/routes/v1/router.py`, `src/huron/applications/api/runtime.py`,
  `src/huron/core/lake/bootstrap.py`, `src/huron/core/lake/collections/lifecycle.py`,
  `src/huron/core/lake/lookups.py`, `src/huron/core/storage/__init__.py`,
  `src/huron/core/storage/errors.py`, `src/huron/core/storage/memory.py`,
  `src/huron/core/storage/placement.py`, `src/huron/core/storage/ports.py`,
  `src/huron/core/storage/posix.py`, `src/huron/pkg/fs/posix.py`, `src/huron/schema/naming.py`.
- Source, new: `src/huron/applications/api/disk/repair.py`,
  `src/huron/applications/api/routes/v1/endpoints/repairs.py`,
  `src/huron/applications/api/routes/v1/schema/repairs.py`,
  `src/huron/core/lake/repairs/__init__.py`, `src/huron/core/lake/repairs/models.py`,
  `src/huron/core/lake/repairs/operations.py`, `src/huron/core/storage/repair.py`.
- Tests, changed: `tests/conftest.py`, `tests/support/disk.py`,
  `tests/unit/api/test_lake_disk.py`, `tests/unit/api/test_lifespan.py`,
  `tests/unit/api/test_openapi_snapshot.py`, `tests/unit/api/test_upload_hooks.py`,
  `tests/unit/lake/test_uploads.py`, `tests/unit/pkg/test_posix.py`,
  `tests/unit/schema/test_naming.py`, `tests/unit/storage/test_containment.py`,
  `tests/unit/storage/test_directories.py`, `tests/unit/storage/test_organizations.py`,
  `tests/unit/storage/test_placement.py`, `tests/unit/storage/test_races.py`,
  `tests/unit/storage/test_storage.py`.
- Tests, new: `tests/unit/api/test_repair.py`, `tests/unit/lake/test_repairs.py`,
  `tests/unit/storage/test_repair.py`.

`tests/unit/storage/test_directories.py` and `tests/unit/storage/test_organizations.py` are not
in the R1 record. R2 changed them (exact message and context checks on both adapters).

The two concept documents are committed whole, because the repair text in `raw-ingest.md` links
to anchors that the same diff adds to `access-and-roles.md`.

Exclude (54):

- Agent tooling (41): every entry in `.agents/` (36, with the 4 untracked `huron-*` skills and
  the 3 staged deletions), `.opencode/` (4) and `opencode.json`. `.claude/` has no change.
- Other (13): `.gitignore`, `AGENTS.md`, `docs/agents/domain.md`, `web/package.json`,
  `web/docs-site/package.json`, `web/scripts/npm-scripts.test.mjs`,
  `IMPLEMENTATION_PLAN_LATEST.md`, `HANDOFF_M11_PLAN.md`, `HANDOFF_MEDIUM_WORKFLOW.md`,
  `REPOSITORY_READINESS.md` and the three files in `design/`.

The included set needs no excluded file:

- No included document links to an excluded file. `M11_PLAN_1_REPAIR.md` names excluded files
  as text only.
- The `IMPLEMENTATION_PLAN.md` diff names no excluded file.
- No test, script or `Makefile` target of the gate reads `AGENTS.md`, `.agents/`,
  `opencode.json`, `docs/agents/` or a `package.json`.
- The `pyproject.toml` diff is the two `huron.core.lake.repairs` lines.

The excluded files need nothing from the included set. No excluded file names a repair module,
route or schema. `web/scripts/npm-scripts.test.mjs` tests the scripts of `web/package.json`, and
both stay out together.
