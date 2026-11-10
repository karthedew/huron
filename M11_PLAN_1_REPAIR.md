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
- Status: pending

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
- Status: pending

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
- Status: pending

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
