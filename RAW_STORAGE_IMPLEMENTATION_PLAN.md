# Huron Raw storage redesign — implementation plan

Status: Milestone 0 done; Milestones 1+ pending.

Branch `raw-storage`; baseline commit `8b6f270`; Milestones 1–14 start from `9882690`, the commit
that adds the design. Design of record: `RAW_STORAGE_DESIGN.md` (reviewed): its decision register
(§3: the owner decisions OD-1..OD-12 in §3.1 and the design decisions D-1..D-179), the delivery
order (D-81 with the §21 and §22 slices), deletions (§21), testing (§22), risks (§23) and the review
log (§25). The owner decisions bind every task. Milestone 0 holds the work the owner decided before
the design was complete, and was approved to start early on 2026-10-15.

## Goal and non-goals

Goal: implement `RAW_STORAGE_DESIGN.md` on `raw-storage`, one task at a time under the rules below.
A Raw dataset becomes one Polaris generic table under property standard 2, whose bytes live in its
catalog's own storage inside operator-allowlisted storage roots. Each tus 1.0.0 upload session
publishes at most one immutable, verified version, numbered without gaps and published by one
exclusive rename. Datasets (PENDING → ACTIVE ⇄ ARCHIVED → DELETED) and versions (AVAILABLE →
DELETED) park deleted bytes at once and purge them after the retention period. A Raw-owned metadata
schema registry, per-process and cluster-wide admission limits and a ten-duty maintenance loop
complete the engine. One Raw API under `/api/v1/raw` takes the BFF delegation as its only
credential and serves the web wizard, explorer and catalog settings. Migrations `0014`–`0017` and
`scripts/raw_reset.py` replace the legacy schema and data, every legacy Raw path the design deletes
(§21) is gone, and the documentation and the design record describe the built behaviour.

Non-goals:

- Everything the design defers or rules out (§1 "Non-goals", §9.8.7, §16.12, §23.2): layers,
  releases, tags, branches, amendments, delta or carry-forward in Raw; payload schemas; the
  ORGANIZATION and PROJECT schema scopes, `extends` composition and the non-Raw document kinds of
  design decision 16 (ADR 0003); any Huron call to Polaris (OD-5); migrating legacy Raw data instead
  of resetting it (OD-4); undelete; the tus `creation`, `creation-defer-length` and `concatenation`
  extensions; an asynchronous commit (R6); and any change to Catalog datasets, Catalog's layers or
  `Dataset.version`.
- The SDK and API-key upload path (OD-6, OD-8): only its `RawAuthority` seam is built (§12.12), and
  scripted uploads return with a follow-up plan.
- Object-store adapters: only the POSIX storage-roots adapter is built; the S3 mapping of §9.8.7
  stays documentation.
- Merging `raw-storage` into `main` before the 9 GiB acceptance gate has a recorded green run
  (OD-12 O-7); the Polaris parity run must have passed as well (D-143).

## Plan-wide rules

These apply to every task in this plan.

- **Gate.** Every implementation, fix and verification pass runs the complete gate below from the
  repository root. Every command must exit 0, and `radon cc` and `radon mi` must also print
  nothing: radon exits 0 even when it lists findings. Configured thresholds in `pyproject.toml`
  govern (`fail_under` is a ratchet; it moves down only under the "Coverage floor re-baseline"
  rule).

  ```text
  uv run ruff check src
  uv run ruff format --check src
  uv run pydoclint src
  uv run ty check
  uv run mypy
  uv run lint-imports
  uv run python scripts/check_schema_map.py
  uv run radon cc src --min C
  uv run radon mi src --min B
  uv run complexipy src --max-complexity-allowed 15
  uv run --locked pyscn check src
  uv run --locked python scripts/check_duplication.py src
  uv run pytest --cov=src/huron --cov-report=term-missing
  uv run pytest -m contract
  uv run pytest -m integration
  ```

  Tasks that change pages of the documentation site (`docs/`, `zensical.toml`) also run
  `make docs`. Every task that touches `web/` or the Playwright harness module
  (`tests/raw_web_support.py` until M5.1, then `tests/raw_e2e_support.py`) also runs, from `web/`,
  all five of `npm run check`, `npm test`, `npm run lint`, `npm run build` and `npm run test:e2e`;
  `npx @sveltejs/mcp svelte-autofixer <file> --svelte-version 5` on each changed Svelte file; and
  the AGENTS.md visual QA for visible changes (§20.1, §22.1). The Playwright harness builds its
  stores with `memory_stores()` and starts the API lifespan, so every task that changes what that
  lifespan builds or asserts also runs `npm run test:e2e` from `web/` (it builds the BFF itself;
  the other four npm commands run only when `web/` changed): the lifespan or `_build_runtime` in
  `src/huron/applications/api/app.py`, `src/huron/core/raw/runtime.py`, the conformance asserts in
  `src/huron/applications/api/capabilities.py`, `ApiStores` or `memory_stores()`. A broken harness
  start then fails the task that caused it, not the next web task.
- **Containers.** Contract and integration suites use Docker Desktop through testcontainers.
  Never start or stop the owner's local stack (`scripts/polaris-dev.sh`, the `huron-raw-local`
  container) and never use `make up`/`make stack`.
- **Long commands.** No single tool call may run longer than about two minutes without output:
  run the contract and integration suites (and any other long command) in the background and poll
  their output with short commands until they finish.
- **Acceptance (OD-12 O-7).** From M10.10 on, every task that touches the upload path also runs
  the 2 GiB rehearsal, `uv run pytest -m acceptance -k rehearsal`. The 9 GiB gate
  (`uv run pytest -m acceptance`) runs only on an APFS or ext4 volume with at least 25 GiB free
  (through `--basetemp`) or in the `Acceptance` workflow; otherwise the task reports it "not run"
  with the reason. It blocks the merge into `main`, never a task.
- **Polaris parity (D-143).** `uv run pytest -m polaris` is never a per-task gate. M2.5 runs it
  only if the owner's stack is already up, and otherwise records "not run: stack not available".
  It must pass before the merge into `main`.
- **Coverage.** Every file a task modifies (not deletes) reaches 100% line coverage, unless the
  verifier names a specific line as unreachable defensive code. PostgreSQL adapter modules are
  measured with `uv run pytest -m "unit or contract" --cov=src/huron --cov-report=term-missing
  --cov-fail-under=0` (§22.3). A deleting task removes every symbol whose only covering tests it
  deletes, or covers that symbol directly when it stays.
- **Coverage floor re-baseline (owner decisions, 2026-10-15).** The floor is a ratchet on the unit
  run. `fail_under` in `pyproject.toml` may be reset to the newly measured unit total, computed
  from the statement counts as `floor(10000 × covered / statements) / 100` (§22.4 step 3), only
  when the verifier confirms from covered and total statement counts before and after the task
  that the whole drop comes from deleted statements that were covered, new PostgreSQL adapter
  statements that `uv run pytest -m "unit or contract" --cov=src/huron` covers in full, or both —
  and that every new or modified file is at 100%. Record the before/after counts under "Execution
  notes". The floor rises again as tests are added. This matches the `pytest` pass condition in
  `.claude/commands/implement-markdown.md`.
- **Whole-file deletions and renames.** Implementation agents cannot delete tracked files; the
  orchestrator removes every whole file or directory a task lists (with `git rm`) before the
  implementation pass, and after it only when the task says the file must stay live until its
  replacement lands in that pass (D-123). Renames are orchestrator `git mv`s before the pass, and
  the implementer edits the new path (D-141). An implementer that finds another whole file to
  delete reports it and stops; it does not delete it. The verifier checks the lists against
  `git status`.
- **Duplication baseline (D-142, §22.5; owner decision O-2).** `--update-baseline` only ratchets
  the baseline down. A new or changed clone signature is accepted only through a bootstrap after
  the orchestrator `git rm`s `scripts/duplication_baseline.json`, or through a reviewed hand edit,
  and only when the verifier's four checks pass: at most 144 clones in total; no shared signature
  grown; each new signature traced to a deletion or rename, or to a reviewed new module; the edit
  and its traces recorded under "Execution notes". Slices 2–6 (M3, M4, M5–M7, M8, M12) take at
  most four new clones each, and the Execution notes keep a running total.
- **Problem codes and route tables.** A design/api.html §7 row lands with its first raiser and
  leaves with its last; the `Retry-After` column lands with the first added row (M2.4). Each task
  that adds or removes a router updates the OpenAPI tag-set test, the router-composition tests and
  the operation table of `tests/unit/test_execution_model.py`, and the design/api.html §3 rows land
  with their routes. The tag-set test's set, count and name follow the routers: 17 tags after M3.9,
  18 after M4.8, 17, 16 and 14 after M5.1, M5.2 and M5.3, 15 after M6.9, 16 after M7.7, and the end
  state of 17 after M8.3 (§19.7).
- **Composition root (§6.6, §8.6.8).** From M4.7 on, `RawRuntime` takes the adapter bundle
  `RawPorts` and its keywords as §8.6.8 gives them: `RawRuntime(ports, *, placement, admission,
  limits, public_api_url, clock)`. The fields and keywords arrive with their slices: M4.7
  (`datasets`, `schemas`, `work`, `archive`, `sweeper`; `placement`, `public_api_url`, `clock`),
  M6.7 (`admission`, `limits`), M6.9 (`uploads`, `ledger`, `area`), M7.3 (`trigger`) and M7.13
  (`versions`); the old engine's `storage` and `persistence` stay as keywords only until M5.3. A
  task that adds a `RawPorts` field, a `RawRuntime` keyword, a service `RawRuntime` composes or an
  `ApiStores` member edits, in the same pass, `src/huron/core/raw/runtime.py`,
  `src/huron/applications/api/runtime.py` and `app.py`, `tests/unit/support.py`
  (`memory_stores()`), and every test that builds `RawRuntime` or `ApiRuntime` directly:
  `tests/unit/test_authorization_credentials.py`, and `tests/unit/test_core_workflows.py` until
  M5.3 removes its old-engine fixture. It also runs `npm run test:e2e` (the "Gate" rule).
- **Migrations.** At most one Alembic revision per task, in the order `0014` → `0017`, with
  `migrations/schema.sql` and its `Reflects:` stamp in the same commit and contract proofs on
  `postgres:16` (§10.3).
- **Races (R15).** An intermittent failure of a named race or safety test is a failure and is
  never re-run to green. The first such failure, trigger refusal (SQLSTATE 23514) or Raw finding
  outside tests stops the milestone that owns the mechanism until a fix lands with a new named
  test; a repeat sends the mechanism to `/architectural-review`.
- **Byte-moving duties (R5).** `ReapStaging`, `SweepOrphanStaging`, `ParkDeleted`, `PurgeDeleted`
  and `EmptyTrash` land last (M12.3–M12.6), each only with its §18.6 test and a
  root-swapped-for-empty case passing on real temporary roots.
- **Transitions and merge.** Only the declared legacy-removal transition (M5.2–M5.7, D-137) may
  leave legacy code without callers: a legacy symbol whose last caller an earlier M5 task removes
  keeps its own tests until the M5 task that lists it deletes it, and none is left after M5.7. The
  web's part-upload path leaves whole in M10.2, before its successor (§21.1 rule 1), so no web
  transition is declared. `raw-storage` merges into `main` only after every task is verified, a
  green 9 GiB run is recorded and the Polaris parity test has passed.
- **Deviations.** The order follows D-81 as amended by D-137..D-139, with five delivery-order
  deviations, each recorded under "Execution notes" as it lands: (1) the fixture release pages
  leave in M1.2; (2) the legacy removal runs as seven measured, coverage-safe steps (M5.1–M5.7);
  (3) the browser acceptance runs in M10.10, after the wizard's tus tasks; (4) slice 6 (M12) runs
  after the web tasks; (5) the verifier and the maintenance loop (M7.3) land before the chunk
  protocol (M7.4). Three more deviations name or add what the design does not, each recorded under
  "Execution notes" by the task that lands it: (6) the tus modules are the owner's placeholders
  `routes/v1/endpoints/tus.py` and `routes/v1/schema/tus.py`, whose docstrings ("tus 1.0.0 upload
  routes for Raw versions", "Request and response models for the Raw tus upload routes") claim
  them, in place of the design's `raw_tus.py` (D-72, D-97, §11.14, §19.1); every check the design
  keys on `raw_*` module names names `tus.py` as well (M7.7, M11.4, M14.7); (7)
  `src/huron/core/metastore/raw_memory.py` (M3.5), the one in-memory Raw state that the in-memory
  Raw stores share as the PostgreSQL adapters share one database, which §6.4 and §8.7.5 do not
  list; (8) `SchemaPin(subject_id, number, schema_version_id)` on `UploadSession` (M6.2), which
  §8.4.2 and D-88's glossary lack, because `UploadSessionView.schema` (§19.4) needs the subject and
  the number on target-less reads without a second read.
- **Clean sweep.** No backwards compatibility, shims, TODOs, commented-out code, suppressions
  (`# noqa`, `# type: ignore`, `# pragma: no cover`, skip/xfail) or configuration exclusions.
  Comments, docstrings, test names and messages never mention this plan and cite no plan task,
  milestone, slice or design decision id (§22.4 step 5). Besides a `fail_under` reset, the one
  tool-configuration change any task makes is the type information M3.3 declares for its new
  runtime dependency `google-re2`, exactly as M3.3 spells it (the pattern of the existing
  `asyncpg.*` override). It is part of that task's specification, not a loosening of the gate;
  the verifier compares it with M3.3's text and accepts nothing broader.
- **Skills.** `oop-design` for `src/huron/core`; `fastapi` for `src/huron/applications/api`;
  `postgresql-table-design` for migrations and PostgreSQL adapters; `writing-for-agents` when
  editing `AGENTS.md` or `CLAUDE.md`; `svelte-core-bestpractices` and `svelte-code-writer` for
  Svelte; `tailwind-design-system` for styling; `domain-modeling` for `CONTEXT.md` and ADRs.
- **Owner's untracked files.** `scripts/test.py` and the empty placeholders
  `src/huron/applications/api/routes/v1/endpoints/tus.py` and
  `src/huron/applications/api/routes/v1/schema/tus.py` (each holds only a module docstring) belong
  to the owner. No task deletes, renames or stages them, and `git status` checks ignore them, with
  one exception: the tasks that implement the tus routes fill the two placeholders, under the
  owner's docstrings, in place of the design's `raw_tus.py` modules (D-25, D-97). M7.6 writes the
  tus header grammar and builders into `routes/v1/schema/tus.py`, M7.7 writes the tus routes into
  `routes/v1/endpoints/tus.py`, and M7.8 adds PATCH to both; the orchestrator's commit of each task
  then tracks the file, and the Execution notes record the module names.
- **Commits.** The orchestrator commits each task after its verification passes.

## Milestone 0 — decided deletions

### M0.1 Branch and baseline

- Intent: start from the owner's work in progress on a dedicated branch with a known-green gate.
- Done: branch `raw-storage`; commit `8b6f270` holds the owner's multi-realm organization work.
  The full gate, including contract (50 passed) and integration (16 passed) on Docker and the web
  gate, passed on this exact tree before the commit.
- Status: done

### M0.2 Retire the legacy integrity machinery, lakectl and the Books uploader

- Intent: delete the one-time v1→v2 cutover/integrity domain, its operator CLI and controller, the
  adapters and documents that exist only for them, and the API-key Books uploader.
- Delete:
  - `src/huron/core/integrity/` (all), `src/huron/applications/lakectl/` (all).
  - Adapters used only by them: `src/huron/core/metastore/legacy.py`,
    `src/huron/core/metastore/maintenance.py`, `src/huron/core/rawstore/maintenance.py`, and any
    symbol elsewhere whose only callers are deleted code (confirm with `rg`; `pyscn` dead-code
    findings must stay at zero).
  - Schema documents used only by them: `src/huron/schema/documents/protocol-inventory-v1.json`,
    `protocol-transition-v1.json` (confirm no remaining reference first).
  - Tests and helpers that exist only for the deleted code (removed by the orchestrator before the
    implementation pass): `tests/unit/test_integrity_controller.py`, `test_integrity_cutover.py`,
    `test_integrity_generations.py`, `test_integrity_storage.py`, `test_controller_engine.py`,
    `test_controller_epoch.py`, `test_controller_settings.py`, `test_controller_transport.py`,
    `test_lakectl_main.py`, `test_lakectl_wiring.py`, `test_legacy_verification.py`,
    `test_maintenance_adapters.py`, `test_managed_controller.py`, `test_protocol_documents.py`,
    `tests/contract/test_integrity_store.py`, `test_maintenance_ownership.py`,
    `test_writer_exclusion.py`, `tests/integration/test_protocol_cutover.py` and the helper
    `tests/controlled_deployment.py` (used only by the cutover integration test). Edit (not delete)
    shared tests that merely mention the deleted code: `tests/contract/test_catalog_store.py`,
    `tests/contract/test_commit_intents.py`, `tests/unit/test_api_login.py`,
    `tests/unit/test_catalog_documents.py`, `tests/unit/test_domain_import_contracts.py`, and any
    other `rg` hit.
  - Code left without callers by the deletions: `parse_revision_dir` in `core/raw/paths.py`, then
    `RevisionPath`, its private helpers and `foundation/names.split_component` if nothing else uses
    them, with their tests in `test_catalog_paths.py` and `test_catalog_properties.py` and the
    round-trip sentence in `docs/getting-started/testing.md`. `pyscn` must report no dead code.
  - `scripts/main.py` and `tests/unit/test_books_upload_script.py` (owner decision OD-8: scripted
    uploads return later with the SDK/API-key path).
  - `deploy/controlled/` (systemd units, role SQL and example configs for the controller/engine).
  - `docs/operations/controlled-cutover.md` and its `zensical.toml` navigation entry.
- Modify:
  - `pyproject.toml`: remove the `lakectl` console script and every import-linter reference to
    `huron.core.integrity` and `huron.applications.lakectl` (the layers contract, independence and
    forbidden lists, the `_impl` privacy contract). The application-independence contract would
    list only `huron.applications.api` and check nothing, so remove it; the AGENTS.md rule that
    applications never import each other stays, and the contract returns with a second application.
  - `docker-compose.yml` (its header comment links the cutover document) and `docs/history.md`
    (its link to the deleted cutover page) so the strict docs build passes.
  - `AGENTS.md`: remove `integrity/` from the package tree and the dependency table; keep the
    remaining rules intact (load `writing-for-agents`).
  - `README.md`, `docs/getting-started/repository-layout.md`, `docs/getting-started/testing.md`:
    remove integrity, lakectl and cutover references.
  - `docs/history.md`: record the retirement (date 2026-10-15, owner decision, what was removed).
  - `docs/adr/0001-controller-generation-is-the-verification-epoch.md`: front matter
    `status: superseded` and one sentence saying the controller epoch was retired with the legacy
    cutover machinery on 2026-10-15; the decision text stays as history.
  - `design/roadmap.html`: the P3 row and its gates no longer describe the retired controller,
    writer-exclusion and cutover workflows as pending work; record the retirement in that row,
    and remove `integrity`/`lakectl` from its package map (lines naming them). Remove them from the
    package maps in `design/architecture.html`, `design/core-map.html` and the Core map card of
    `design/index.html`. Pages that describe the cutover or lakectl as planned work —
    `design/layer-raw.html`, `design/api.html`, `design/catalog-search.html`, `design/rbac.html` —
    say it is retired instead. Mark `P3_DESIGN.md` and `P3_IMPLEMENTATION_PLAN.md` superseded at the
    top (one line each). Leave the UML atlases (dated snapshots) unchanged.
- Database: no migration in this task. Objects that only the deleted code used stay until the later
  legacy-retirement migration; list them under "Execution notes" (known: the
  `reconciliation_findings` table, the `DEGRADED` value of `dataset_revisions.state`, audit rows of
  kind `integrity.cutover`, and the manually created roles `huron_app_legacy`,
  `huron_app_verified` and `huron_cutover`). Kept on purpose for the Raw milestones:
  `committed-v1.json` decoding and `generation-v1.json`.
- Coverage: deleting about 1,390 fully covered statements lowers the unit total below 96.01; apply
  the "Coverage floor re-baseline" rule and record the numbers.
- Verification: the full gate (all commands exit 0); `make docs`; `rg -n "core\.integrity|lakectl|
  metastore\.legacy|metastore\.maintenance|rawstore\.maintenance" src tests pyproject.toml
  AGENTS.md README.md docs zensical.toml` returns nothing outside `docs/history.md` and ADR 0001;
  `uv run lint-imports` keeps every remaining contract; unit, contract and integration counts are
  reported against the baseline (1,837 / 50 / 16) with every removed test accounted for by a
  deleted module.
- Dependencies: M0.1.
- Status: done (verification passed on attempt 1, 2026-10-15)

### M0.3 Remove Raw release tags

- Intent: Raw keeps only full, numbered versions; delete release tags end to end.
- Delete:
  - `src/huron/core/raw/_impl/releases.py` and its export in `src/huron/core/raw/__init__.py`;
    `Release`, `RevisionRef` and any other release-only types in `core/raw/types.py`;
    `ReleaseStore`/`ReleaseTransaction` and `RawStore.write_tag_once` in `core/raw/ports.py`;
    `release_tag_file` in `core/raw/paths.py`; `TagExists`, `TagWithdrawn` and their error-code
    entries in `core/raw/errors.py`.
  - The release methods and constraint names in `src/huron/core/metastore/hierarchy.py` (and the
    in-memory counterparts and row mappers in `rows.py`); `PosixRawStore.write_tag_once` in
    `core/rawstore/store.py`.
  - The release routes and models in `applications/api/routes/v1/endpoints/datasets.py` and
    `routes/v1/schema/datasets.py`, and their wiring in `app.py`, `dependencies.py`,
    `capabilities.py`, `runtime.py` (confirm each hit with `rg`).
  - The `release.create` capability from `core/security/roles.py` role definitions.
  - Release tests and helpers: `tests/integration/test_catalog_releases.py`,
    `tests/catalog_release_support.py`, and the release parts of `tests/hierarchy_contract.py`,
    `tests/contract/test_hierarchy_store.py`, `tests/unit/test_api_catalog_hierarchy.py`,
    `test_repository_hierarchy.py`, `test_hierarchy_store_memory.py`, `test_rbac_roles.py`,
    `test_api_ingest_sessions.py` and any other `rg` hit.
- Migration: add the next Alembic revision after the current head (`0013_retire_releases`)
  that drops the `releases` table, its `releases_immutable` trigger function and its indexes, and
  removes `release.create` from `role_capabilities` and `capabilities`. Its downgrade raises, like
  0011 and 0012 (forward-only). Update `migrations/schema.sql` (the map and its `Reflects:` stamp)
  so `scripts/check_schema_map.py` passes, and add contract coverage proving the table and
  capability are gone after `upgrade head`.
- Documentation: remove the release routes and the `TAG_EXISTS`/`TAG_WITHDRAWN` rows from
  `design/api.html` (the error-contract test pins §7); remove `release.create` from
  `design/rbac.html`; mark invariant M retired in `design/architecture.html`; update the release
  sections of `design/layer-raw.html`, `design/index.html` and `design/workflows.html`, and the
  roadmap rows that cite releases, so no design page describes release tags as current behaviour.
  The fixture-backed web routes under `web/src/routes/[org]/[project]/[dataset]/[release]/` are not
  touched here; the web milestones remove them.
- Verification: the full gate; contract tests against `upgrade head` on Docker; `rg -n -i
  "release\.create|TagExists|TagWithdrawn|write_tag_once|release_tag_file|ReleaseStore"
  src tests` returns nothing; `rg -n "releases" src` returns nothing outside comments that describe
  history (there should be none).
- Dependencies: M0.2.
- Status: done (verification passed on attempt 2, 2026-10-15)

## Milestone 1 — Early retirements and shared foundations

Goal: delete the legacy pieces that replace nothing and that nothing else depends on (amendments,
the fixture release pages), and move the shared error and paging types into foundation, so
`core/raw` never needs to import `security` or `catalog`.

### M1.1 Retire amendments

- Intent: delete the amendment fold and its allow-list, which nothing writes (a version is
  immutable; a correction is a new version), together with its problem code. Row 7 replaces nothing
  and no module imports it, so it is the first deletion. The `revision_amendments` table stays until
  `0017_retire_legacy_raw` (M13.3).
- Delete (orchestrator `git rm` before the pass): `src/huron/core/raw/amendments.py`,
  `tests/unit/test_raw_amendments.py`.
- Create / Modify:
  - `src/huron/core/raw/errors.py`: remove `AmendmentFieldForbidden` and `AMENDMENT_FIELD_FORBIDDEN`
    from `ERROR_CODES` (confirm with `rg` that nothing else names either).
  - `design/api.html` §7 (`table#error-codes`): remove the `AMENDMENT_FIELD_FORBIDDEN` row, so the
    bijection `tests/unit/test_error_contract.py` asserts still holds. The §3 rows that mention
    amendments (`GET /datasets/{id}/revisions`, `POST /revisions/{id}:amend`) leave with the v1
    revision routes (M5.2).
  - `design/roadmap.html`: the P5 governance row stops listing project-admin amendments and stops
    claiming "The amendment fold and field allow-list are implemented (`core/raw/amendments.py`)"; it
    records that Raw amendments are retired (a version is immutable; a correction is a new version).
    UI milestones 7 and 21 drop "Built: the amendment fold and field allow-list" and their
    amendment-history promises for Raw.
  - `design/layer-raw.html` ("Amendments") and `design/core-map.html` (the `raw/metadata.py`,
    `amendments.py`, … row): state the retirement and drop the links to the deleted module. The UML
    atlases are dated snapshots and stay (M14.4–M14.6 re-render them).
  - `docs/getting-started/testing.md`: drop "and the amendment fold" from the high-value targets.
- Design: §21.1 Rules (rule 1); §21.2 Inventory, row 7 (Amendments); §21.3 Kept on purpose
  (`tests/contract/test_catalog_store.py`); §19.6 Problem codes, "Rows removed"; §22.4 Coverage: the
  total floor (OD-11); D-70, D-123.
- Verification:
  - The plan-wide gate and `make docs`.
  - `rg -n -i "amendment" src tests --glob '!tests/contract/test_catalog_store.py'` prints nothing.
  - `test_error_contract.py` passes unchanged in code: the class and the row leave together.
  - OD-11 floor reset (§22.4 steps 1–4): the verifier confirms from per-file unit reports at the
    starting commit and the result that the whole drop is the deleted, fully covered statements of
    `amendments.py` and the error class, every modified file stays at 100 %, and no surviving file
    gains a missed line; `fail_under = floor(10000 × covered / statements) / 100`; counts and the
    unit test-count change (exactly the deleted module's tests) go to Execution notes.
  - The duplication guard passes; a lower clone total is ratcheted down with
    `--update-baseline` and logged.
- Dependencies: none.
- Status: done (verification passed on attempt 2, 2026-10-21)

### M1.2 Retire the fixture release pages

- Intent: remove the fixture-backed release and revision pages, the release table of the fixture
  `[dataset]` page and the fixture helpers, types and data that only they use, so no web page
  presents releases or revisions of the legacy fixture model (requirement 3). The rest of the legacy
  fixture tree stays; the hook already redirects every signed-in request to it to `/browse`.
- Delete (orchestrator `git rm` before the pass):
  `web/src/routes/[org]/[project]/[dataset]/[release]/+page.svelte`,
  `web/src/routes/[org]/[project]/[dataset]/[release]/+page.ts`,
  `web/src/routes/[org]/[project]/[dataset]/[release]/[revision]/+page.svelte`,
  `web/src/routes/[org]/[project]/[dataset]/[release]/[revision]/+page.ts`.
- Create / Modify (load `svelte-code-writer` and `svelte-core-bestpractices`):
  - `web/src/routes/[org]/[project]/[dataset]/+page.svelte`: remove the "Releases" heading and its
    table, and the component imports only that table used (`DataTable`, `LayerBadges`,
    `EmptyState`; keep each import another part of the page still uses).
  - `web/src/routes/[org]/[project]/[dataset]/+page.ts`: load the dataset only (no `listReleases`).
  - `web/src/lib/api/client.ts`: remove `listReleases`, `getRelease`, `listRevisions`,
    `getRevision`, `getManifest` and their type imports.
  - `web/src/lib/api/types.ts`: remove `Release`, `Revision`, `ManifestEntry` and the fixture
    `Dataset.releaseCount` member; `web/src/lib/api/fixtures.ts`: remove the `releases`, `revisions`
    and `manifest` data, the two `releaseCount` values and the header comment's "unsealed release"
    state. Confirm each removal with `rg` over `web/src` and `web/e2e` first; anything with another
    user stays.
  - `design/roadmap.html` UI milestone 7: the fixture-backed release pages are removed (no longer
    "leave the web app with the web milestones").
- Design: §21.2 Inventory, row 15 (the release pages and their fixture helpers); §21.3 Kept on
  purpose (the rest of the legacy fixture tree); §2 Requirements traceability, requirement 3; D-124.
- Verification:
  - The plan-wide Python gate (no Python changes; it proves nothing else moved).
  - The web gate from `web/`: `npx @sveltejs/mcp svelte-autofixer
    'src/routes/[org]/[project]/[dataset]/+page.svelte' --svelte-version 5` with no applicable
    finding, then `npm run check`, `npm test`, `npm run lint`, `npm run build` and
    `npm run test:e2e`; `e2e/smoke.test.ts` "obsolete scientific fixture routes redirect into live
    browse" still sends `/example-org/example-study/example-sweep/run-0001` to `/browse`, now by the
    hook alone.
  - `test ! -e 'web/src/routes/[org]/[project]/[dataset]/[release]'`; `rg -n
    "getRelease|listReleases|listRevisions|getRevision|getManifest" web/src web/e2e` prints nothing.
  - No visual QA: the changed page is unreachable while signed in (hook redirect); report that.
- Dependencies: none.
- Status: done (verification passed on attempt 2, 2026-10-22)

### M1.3 Move shared errors and paging into foundation; Retry-After plumbing

- Intent: let `core/raw` raise the shared refusals and return windows without importing `security`
  or `catalog` (D-77). `Forbidden` and `AuthError` move to `huron.core.foundation.errors` and
  `Window` to the new `huron.core.foundation.paging`; every importer moves with them and no
  re-export remains (D-146). `DomainError` gains `retry_after`, which the problem handler renders as
  `Retry-After`, ready for the Raw classes that declare one (D-61).
- Delete: none.
- Create / Modify:
  - `src/huron/core/foundation/errors.py`: `Forbidden(DomainError)` (403 `FORBIDDEN`) and
    `AuthError(Exception)` (`INVALID_CREDENTIAL`, behaviour unchanged, still not a `DomainError`)
    move here, docstrings generalized beyond role bindings; `ERROR_CODES` gains `FORBIDDEN` and
    `INVALID_CREDENTIAL`; `DomainError.retry_after: ClassVar[int | None] = None`.
  - `src/huron/core/security/errors.py`: `Forbidden` leaves the module, `__all__` and `ERROR_CODES`;
    `INVALID_CREDENTIAL` leaves security's `ERROR_CODES` with its class (`APIKEY_*` stay).
    `src/huron/core/security/authentication_errors.py` keeps `ApiKeyExpired` and `ApiKeyRevoked`,
    now subclassing foundation's `AuthError`, with its docstring pointing there.
  - `src/huron/core/foundation/paging.py` (new): `Window[ItemT]`, moved verbatim out of
    `src/huron/core/catalog/types.py`.
  - Every importer, by `rg` (expected hits): `Forbidden` in `core/security/_impl/{access,identity,
    self_access}.py`, `core/security/raw_delegation.py`, `core/raw/web.py`,
    `core/raw/_impl/ingestion.py`, `applications/api/authorization/guards.py`; `AuthError` in
    `core/security/{password,dev,apikeys,sessions,oidc,raw_delegation}.py`,
    `core/security/_impl/{credential,oidc,password}_authentication.py`,
    `applications/api/{problems,raw_web}.py`, `applications/api/authorization/credentials.py`;
    `Window` in `applications/api/routes/v1/pagination.py`, `core/catalog/{ports,
    _impl/collections}.py`, `core/metastore/{hierarchy,queries}.py`. Tests: `test_authorization_
    guards.py`, `test_security_authentication.py`, `test_api_problems.py`, `test_core_workflows.py`,
    `test_repository_rbac.py`, `test_authorization_decisions.py`, `test_api_errors.py`,
    `test_authorization_credentials.py`, `test_auth_sessions.py`, `test_api_app.py`,
    `test_auth_oidc.py`, `test_error_contract.py`, `test_raw_web.py`, `test_api_pagination.py`,
    `test_stores_ports.py`.
  - `src/huron/applications/api/problems.py`: the `domain_error` handler passes
    `headers=_problem_headers(exc)`, a private helper returning `{"Retry-After": "<seconds>"}` or
    `None`; the `AuthError` handler keeps `WWW-Authenticate: Bearer`.
  - `tests/unit/test_api_problems.py`: `test_problem_headers_carry_retry_after`. Its test class
    subclasses an existing `DomainError` and sets only `retry_after`, inheriting `code`, so the
    error-contract walks (keyed on a class's own `code`) never see it; a class without
    `retry_after` answers without the header.
  - `tests/unit/test_domain_import_contracts.py`: the foundation-import test also imports `paging`.
  - Four of the modules whose imports move are below 100 % at `9882690` (`core/security/dev.py`
    line 45, `core/security/apikeys.py` lines 124 and 189, `applications/api/raw_web.py` line 83,
    `applications/api/authorization/guards.py` line 426), so this task adds their missing cases:
    `tests/unit/test_security_authentication.py` gains
    `test_dev_header_resolver_refuses_other_environments`,
    `test_api_key_ttl_outside_one_second_to_400_days_is_refused` and
    `test_unknown_api_key_is_an_invalid_credential` (the miss still hashes and answers
    `AuthError`); `tests/unit/test_raw_web.py` gains `test_raw_web_answers_404_while_unconfigured`;
    `tests/unit/test_authorization_guards.py` gains
    `test_upload_owner_refuses_another_actors_session`. The last two leave with their modules in
    M5.1 and M5.3.
  - `design/core-map.html`: the foundation rows name `paging` (`Window`), `Forbidden` and
    `AuthError`; the Catalog types row drops `Window`.
- Design: §8.2 Package placement ("Three moves keep `core/raw` free of `catalog` and `security`
  imports"); §17.6 `Retry-After` plumbing; §19.6 Problem codes, "Vocabularies and classes"; D-61,
  D-131, D-146.
- Verification:
  - The plan-wide gate; `uv run lint-imports` keeps all 16 contracts.
  - `rg -n "\b(Forbidden|Window)\b" src/huron/core/security/errors.py
    src/huron/core/catalog/types.py` prints nothing, so a stale import of either fails collection;
    `rg -n "authentication_errors import .*\bAuthError\b" src tests` prints nothing (that module
    still binds the name through its own import, so only this check catches a stale import).
  - `test_error_contract.py` passes with each of `FORBIDDEN` and `INVALID_CREDENTIAL` declared by
    exactly one class; `test_problem_headers_carry_retry_after` passes.
  - Every modified file at 100 % in the unit run, the five cases above included; statements only
    move, so the floor cannot drop.
- Dependencies: none.
- Status: pending

## Milestone 2 — Layout, documents, placement and storage roots (slice 1)

Goal: land the pure contracts every later slice depends on: the layout and placement values, the
packaged document contracts, Polaris placement, `RawSettings`, and the POSIX storage-roots adapter
with dataset-root claims.

### M2.1 Storage layout contract and placement values

- Intent: land the pure layout contract that core and rawstore share (`huron.schema.raw_layout`)
  and the first storage values and errors that the roots adapter and dataset creation need
  (`huron.schema.storage`). Nothing calls them yet; every later value lands with the first adapter
  method that returns or raises it.
- Delete: none.
- Create / Modify:
  - `src/huron/schema/raw_layout.py` (new; standard library only, no I/O): the constants `HIDDEN`,
    `ROOT_SENTINEL`, `STAGING`, `DELETED`, `TRASH`, `QUARANTINE`, `VERSIONS`, `PAYLOAD`,
    `VERSION_DOCUMENT`, `MANIFEST_DOCUMENT`, `METADATA_DOCUMENT`, `SCHEMA_DOCUMENT`, `NUMBER_WIDTH`,
    `MAX_NUMBER`, `VERSION_PATH_TEMPLATE` and the functions `version_dir`, `version_location`,
    `staging_dir`, `scratch_input`, `parked_dataset`, `parked_version`, `is_reserved`, with the
    §9.8.2 signatures: root-relative `PurePosixPath`s, ids as `uuid.UUID.hex`, a number outside
    `1..MAX_NUMBER` a `ValueError`. The staging children `upload`, `completion` and `envelope` stay
    private to rawstore.
  - `src/huron/schema/storage.py` (evolved; imports only the standard library and `raw_layout`):
    `DatasetPlacement(root, path, base_location)` with `__post_init__` (root key
    `^[a-z][a-z0-9-]{0,62}$`; `path` has no empty, `.` or `..` segment and is not reserved;
    `base_location` ends with `"/" + path + "/"` — the suffix only, D-175) and the property
    `placement_key` = `NFC(casefold(NFC(path)))`; `RootIdentity(uri, root_id)`;
    `StorageRootUnavailableError(root, reason)` keeping both as attributes, its eight reasons
    (`path_missing`, `sentinel_missing`, `sentinel_mismatch`, `cross_device`, `io_error`,
    `unconfigured`, `not_mounted`, `placement_mismatch`) a closed set the constructor enforces
    (`ValueError` otherwise); `DatasetRootOccupiedError`. `PartLengthMismatchError` stays until
    M5.7 removes it; its successor `ChunkLengthMismatchError` lands in M6.6.
  - `tests/unit/test_raw_layout.py` (new): every constant and function, the number bounds,
    `is_reserved` (`""`, `.huron`, `.huron/x`, `science/.huron`), and
    `test_version_path_spellings_agree`: `version_location(n)` equals
    `VERSION_PATH_TEMPLATE.format(number=f"{n:06d}")`, and `str(version_dir(p, n))` equals the
    trigger's `p || '/versions/' || lpad(n::text, 6, '0')` rendered in Python, for 1, 42 and
    999999. The Raw cases of `test_catalog_paths.py` stay with `core/raw/paths.py` until M5.6.
  - `tests/unit/test_schema_storage.py` (new): one refusal per `DatasetPlacement` rule, a foreign
    prefix that the suffix-only rule accepts, `test_placement_key_folds_case_and_normalization`
    (`Data`/`data` and NFC/NFD spellings fold equal; distinct names stay distinct; folding twice
    changes nothing), the eight reasons and a refused ninth, and the error classes.
- Design: §9.2 Storage roots: the allowlist; §9.3 The hidden area of each root (`.huron/`); §9.4 The
  dataset root and its versions; §9.8.1 `huron.schema.storage`; §9.8.2 `huron.schema.raw_layout`;
  §6.5 Composition rules the graph and the gates force (rule 3); D-14, D-15, D-16, D-93, D-164,
  D-172, D-175.
- Verification: the plan-wide gate; both modules at 100 % in the unit run; `uv run lint-imports`
  (the layers contract keeps `huron.schema` free of `huron.core`); the named tests above pass.
- Dependencies: none.
- Status: pending

### M2.2 Packaged Raw document schemas

- Intent: package the four new JSON Schema contracts of the redesign under `huron.schema`, exactly
  as the design gives them, so later tasks validate against files rather than restate them. A
  published contract never changes; a change is a new file.
- Delete: none.
- Create / Modify:
  - `src/huron/schema/documents/raw-version-v1.json` (`urn:huron:raw-version:1`, §9.6.1),
    `raw-root-v1.json` (`urn:huron:raw-root:1`, with `root_id`, §9.6.5), `raw-metadata-v1.json`
    (`urn:huron:raw-metadata:1`, the PLATFORM metadata schema, §16.11) and
    `raw-table-properties-v2.json` (`urn:huron:raw-table-properties:2`, §15.2): members, patterns,
    bounds and `$defs` verbatim from those sections.
  - `tests/unit/test_raw_documents_schema.py` (new):
    - each document loads through `huron.schema.validator(name)` (which runs `check_schema`), its
      `$id` is the documented URN, and the `schema` constant of `version.json` and `root.json`
      equals that URN;
    - golden instances validate: the §9.6.1 version-2 example with concrete digests, the exact
      §9.6.5 sentinel bytes, the §9.6.3 metadata example, the §15.2 create request;
    - the documented violations are refused: an uppercase or malformed uuid, a `location` outside
      `^versions/[0-9]{6}/$`, `number` 0 and 1000000, `file_count` 0, an unknown or missing member;
      a sentinel `uri` without its trailing `/` or of another scheme, a bad `key`; metadata without
      `title`, a 257-character `title`, an extra member; a create request with a `polaris.` key, a
      `huron.raw.standard` other than `"2"`, a `versions-url` whose tail is not
      `/api/v1/raw/datasets/<uuid>/versions`, a `created-at` with fractional seconds and a
      `base-location` without its trailing `/`.
- Design: §9.6 Immutable documents (9.6.1 `version.json`, 9.6.3 `metadata.json`, 9.6.5
  `.huron/root.json`, 9.6.6 Packaged schema files); §15.2 The create request; §16.11 PLATFORM seed;
  D-56, D-69, D-109, D-122, D-172.
- Verification: the plan-wide gate; `test_raw_documents_schema.py` passes with the format checker on
  (`uuid`, `date-time`); `git status --porcelain` shows exactly five new `??` entries (the four
  documents and the test module) beside the owner's untracked files, and no modified tracked file
  other than this plan (new files never appear in `git diff --stat`).
- Dependencies: none.
- Status: pending

### M2.3 Version document and manifest helpers in core

- Intent: give core the `version.json` value object (the publication marker) and move the manifest
  document helpers into `core/raw/manifest.py`, so `documents.py` can later shed its legacy
  documents without taking the manifest rules with it. `VersionDocument.compose` lands with the
  freeze decision (M7.12), whose inputs (`UploadSession`, `SchemaVersion`, `SchemaSubject`) do not
  exist yet; the root sentinel lands with `StorageRoot` (M2.4).
- Delete: none. Rename (orchestrator `git mv` before the pass):
  `tests/unit/test_catalog_documents.py` → `tests/unit/test_raw_documents.py`.
- Create / Modify:
  - `src/huron/core/foundation/canonical.py`: `decode_canonical(payload) -> dict[str, JsonValue]`,
    moved unchanged from `documents._decode_canonical` (refuses non-JSON, a non-object top level and
    bytes that are not their own RFC 8785 form); `documents.py`, `manifest.py` and, later,
    `SchemaDocument.stored` (M3.3) share it.
  - `src/huron/core/raw/manifest.py`: `manifest_bytes` and `decode_manifest` moved from
    `documents.py`, behaviour unchanged. `EMPTY_SHA256`, which §8.2 lists among the moved names,
    does not exist at HEAD; it lands with the zero-byte manifest rule (M5.5).
  - `src/huron/core/raw/documents.py`: `SchemaRef` and `VersionDocument` (§8.5 fields; `canonical()`
    renders JCS validated against `raw-version-v1.json`, `committed_at` through `_render_instant`;
    `decode(payload)` refuses non-canonical bytes, a schema violation and a `location` other than
    `raw_layout.version_location(number)`; `location`); the module docstring names the new contract
    beside the legacy documents that M5.5 and M5.6 remove.
  - Importers of the moved helpers: `core/raw/_impl/ingest.py`, `core/raw/_impl/reader.py`,
    `tests/unit/test_raw_documents.py`, `tests/contract/test_commit_intents.py`,
    `tests/unit/test_api_revisions.py`, `tests/unit/test_api_ingest_sessions.py`.
  - `core/raw/_impl/ingest.py` misses lines 622–624 and 631–633 at `9882690` (the
    `PreconditionFailed` retries of file completion), so `tests/unit/test_api_ingest_sessions.py`
    gains `test_file_completion_retries_after_a_concurrent_parts_update`, parametrized over a
    matching and a mismatching copy: the first `update_ingest_file` raises `PreconditionFailed`,
    and `complete_file` re-reads the file and settles it. The case leaves with the engine in M5.3.
  - `tests/unit/test_raw_documents.py`: the existing manifest cases import from `manifest.py`; new
    `test_version_document_golden_bytes` (the §9.6.1 example with concrete digests: exact JCS bytes,
    `decode` round trip, `location`), `test_version_document_decode_refusals` (pretty-printed bytes,
    a missing member, `location` naming another number, an uppercase id), and direct
    `decode_canonical` cases. Its legacy cases leave in M5.5 and M5.6.
- Design: §9.6.1 `version.json`; §9.6.2 `manifest.json`; §8.5 Commands and documents
  (`VersionDocument`, `SchemaRef`); §8.2 Package placement (`documents.py`, `manifest.py`); §9.9
  Tests (`test_raw_documents.py`); D-69, D-122, D-141.
- Verification: the plan-wide gate; `rg -nU 'from huron\.core\.raw\.documents import
  \([^)]*\b(manifest_bytes|decode_manifest)\b' src tests` and `rg -n 'from
  huron\.core\.raw\.documents import [^(].*\b(manifest_bytes|decode_manifest)\b' src tests` print
  nothing (`documents.py` still binds `decode_manifest` for its legacy `CommitIntent`, so a stale
  import would not fail); every modified file at 100 %; the verifier checks the rename with
  `git status` (a rename, not a delete and an add).
- Dependencies: M2.1, M2.2.
- Status: pending

### M2.4 Polaris names and storage locations

- Intent: the first half of `core/raw/locations.py`: Polaris names, the dataset locator, FILE
  storage locations normalized exactly as the Polaris fork normalizes them, the unparsed catalog
  storage claim and the configured root value. The root sentinel's bytes land here too, because
  `root_sentinel` takes a `StorageRoot`. This task adds the first new §7 row
  (`TARGET_NAME_UNSUPPORTED`), so the `Retry-After` column lands with it. Placement derivation
  follows in M2.5.
- Delete: none.
- Create / Modify (load `oop-design`):
  - `src/huron/core/raw/locations.py` (new):
    - `PolarisName.parse`: the fork's `EntityNameValidator` verbatim (empty, `.`, `..`, ISO control
      characters, ``/\:*?"<>|#+` ``), then Huron's URI rule (no whitespace anywhere, none of
      `% [ ] { } ^`), then at most 255 UTF-8 bytes; every refusal is
      `TargetNameUnsupported(context={"segment": text})`.
    - `DatasetLocator(realm, catalog, namespace, name)`: the §8.3.1 bounds as `ValueError`,
      `segments()`; it never holds the endpoint. `catalog_ref` lands with `CatalogRef` (M3.2).
    - `StorageLocation`: `parse` (leading `file:/+` or `/+` becomes `file:///`; any other scheme,
      `?`, `#`, `%`, `\`, an empty interior, `.` or `..` segment and more than 4096 characters raise
      the module-private `LocationInvalid`), `join`, `as_directory`, `contains` (the fork's
      `isChildOf`) and `relative_to`.
    - `CatalogStorage` (the claim, unparsed; 1..64 allowed locations) and `StorageRoot` (key
      pattern, slash-terminated `uri`).
    - Re-exports `DatasetPlacement` and `RootIdentity` from `huron.schema.storage` for metastore
      (§6.5 rule 5); later storage values join the re-export in their own tasks.
  - `src/huron/core/raw/errors.py`: `TargetNameUnsupported` (422 `TARGET_NAME_UNSUPPORTED`) in
    `ERROR_CODES`.
  - `src/huron/core/raw/documents.py`: `root_sentinel(root, *, root_id, created_at) -> bytes`: the
    JCS of `{schema, key, uri, root_id, created_at}`, `created_at` through `_render_instant`,
    validated against `raw-root-v1.json` (§9.6.5).
  - `design/api.html` §7: a `Retry-After` column between "Live/reserved" and "Meaning", `—` on
    every existing row; the `TARGET_NAME_UNSUPPORTED` row (422, live, `—`, the §19.6 meaning); the
    note's sentence "`Retry-After` is the delay in seconds the service sends with the code; `—`
    means none."
  - `tests/unit/test_error_contract.py`: `_ErrorTableParser` reads four leading cells and
    `_ErrorTableRow` gains `retry_after: int | None` (`—` is `None`); new
    `test_domain_error_rows_document_their_retry_after`: every row states the `retry_after` of the
    `DomainError` class that declares its code as its own, and `—` for `AuthError`, `RoleError`,
    path and framework codes.
  - `tests/unit/test_raw_locations.py` (new): a `PolarisName` table (each fork rule, each URI rule,
    255 against 256 bytes with multi-byte characters), `DatasetLocator` bounds, a `StorageLocation`
    table (`file:/x`, `file:///x`, `/x`, `//x`, `file://host/x` with `host` as the first segment,
    every refusal, `s3://`), `join`, `as_directory`, `contains` and `relative_to`; Hypothesis
    `test_storage_location_normalization_is_idempotent`.
  - `tests/unit/test_raw_documents.py`: `test_root_sentinel_golden_bytes` (the exact §9.6.5 bytes).
- Design: §8.3.1 Names, locators and locations (`core/raw/locations.py`); §9.5 The base-location URI
  ("Parity with Polaris", "Normal form and limits"); §9.6.5 `.huron/root.json`; §19.6 Problem codes
  ("Rows added", "`tests/unit/test_error_contract.py`", "Landing"); §6.5 rule 5; D-12, D-90,
  D-122, D-130, D-172.
- Verification: the plan-wide gate; the named tests pass; `test_error_contract.py` passes with the
  column, so every live class's `retry_after` (all `None` so far) is documented; `locations.py` and
  the touched modules at 100 %.
- Dependencies: M1.3, M2.1, M2.2, M2.3.
- Status: pending

### M2.5 Placement policy and Polaris parity

- Intent: derive a dataset's placement purely, as the location Polaris gives a table of that name,
  and refuse every unsafe location before anything is written (D-12, D-13); pin the derivation
  against the real fork in an opt-in test that is never a per-task gate (D-143).
- Delete: none.
- Create / Modify:
  - `src/huron/core/raw/locations.py`: `PlacementPolicy(roots)` (`ValueError` on a duplicate key or
    equal or nested root URIs; `roots`) and `derive(locator, storage)`, eight guard functions of
    cyclomatic complexity ≤ 4 run in §8.3.1's order, the first failure answering; the result is
    `DatasetPlacement(root=key, path=base.relative_to(root.uri), base_location=base.uri)` with
    `base = catalog_base.join(*segments).as_directory()`. `PlacementCheck` lands in M4.2: its
    `holder` is a `RawDataset` and its refusals are dataset codes.
  - `src/huron/core/raw/errors.py`: `StorageLocationRefused` (422 `STORAGE_LOCATION_REFUSED`,
    `context.reason` plus each reason's members: `value`, `expected`/`actual`) in `ERROR_CODES`;
    `design/api.html` §7 row (live, `—`, the §19.6 meaning).
  - `pyproject.toml`: register the marker `polaris` beside `unit`, `contract`, `integration` and
    `acceptance`.
  - `tests/unit/test_raw_locations.py`: the parity table of at least 12 cases (every §9.5 worked
    derivation, the fork's `file:/+` and `/+` rewrites and `isChildOf`, raw unencoded and non-ASCII
    segments, an explicit namespace location equal to the default, a base with and without its
    trailing `/`), one case per reason `derive` decides with its context, among them R2's
    `test_namespace_location_mismatch_refused` (a namespace whose own `location` differs from the
    default layout answers `namespace_location_mismatch` with `expected` and `actual`), and
    Hypothesis `test_derive_never_leaves_its_root` (an accepted placement's `base_location` starts
    with exactly one root's `uri` and `relative_to` round-trips).
  - `tests/integration/test_raw_polaris_parity.py` (new; `pytestmark = pytest.mark.polaris` only):
    against the owner's running local stack it reads `.local/polaris/credentials.json`, takes a
    token as `scripts/polaris_dev.py` `obtain_token` does, creates a namespace (one level
    non-ASCII) and an Iceberg table without a location in a FILE catalog below `local-storage`,
    reads the catalog's storage configuration and the table's location, asserts
    `derive(...).base_location == location.rstrip("/") + "/"`, and drops what it created.
- Design: §8.3.1 (`PlacementPolicy`, the guard table); §9.5 The base-location URI; §8.10 Complexity
  budget; §22.1 Gates per task ("The Polaris parity check is not a per-task gate"); D-12, D-13,
  D-82, D-143, D-164, D-175.
- Verification:
  - The plan-wide gate; `uv run pytest -m integration --collect-only -q` does not list the parity
    module, and neither does the default unit run.
  - `uv run pytest -m polaris` runs only when `curl -sf http://127.0.0.1:8182/q/health/ready`
    answers (never start or stop the stack); otherwise Execution notes record "not run: stack not
    available". Either way the result is recorded; it must pass before the merge into `main`.
  - Radon and complexipy show no guard above its budget.
- Dependencies: M2.4.
- Status: pending

### M2.6 Raw settings

- Intent: `RawSettings` (`ApiSettings.raw`, `HURON_RAW__*`) validates the storage-root allowlist,
  `PUBLIC_API_URL` and every limit, lease, grace, retention and cadence when the settings object is
  built, including relations T1–T8; the empty default allowlist fails every create closed. The D-101
  coupling (the URL is required while `HURON_RAW_BRIDGE_SECRET` is set) lands here rather than
  with the storage-root wiring (M4.7), because route 28 (M3.9) is the first answer that renders a
  URL from it.
- Delete: none.
- Create / Modify (load `fastapi`):
  - `src/huron/applications/api/settings.py`:
    - `RawStorageRoot`: `key` (`^[a-z][a-z0-9-]{0,62}$`), `uri` (parsed by `StorageLocation.parse`,
      so `file` only, stored slash-terminated), `path` (absolute), `require_mount: bool = False`.
    - `RawSettings` with the design's defaults: `storage_roots` (≤ 16, default `[]`; unique keys, no
      equal or nested URIs, no equal or nested paths), `public_api_url: str = ""` (empty means
      unset; otherwise an absolute `http(s)` URL without query, fragment or trailing `/`),
      `chunk_bytes` (a 4 MiB multiple, 8 MiB ≤ value ≤ `max_chunk_bytes`), `max_chunk_bytes`
      (`le=67108864`), `max_files`, `max_file_bytes`, `max_version_bytes` (`le=` the DDL bounds of
      §10.8), `body_idle_seconds`, `chunk_deadline_seconds` (≥ 60), `session_idle_seconds` (≥ 60),
      `session_max_seconds`, `process_streams` (≤ 1024), `process_verifiers` (≤ 64),
      `principal_streams` and `principal_open_sessions` (≤ 1024), `storage_reserve_bytes`,
      `verify_lease_seconds`, `commit_lease_seconds`, `staging_grace_seconds`,
      `deleted_retention_days`, `session_row_retention_days`, `maintenance_interval_seconds`,
      `maintenance_batch`, `orphan_scan_interval_seconds`; one model validator per group of T1–T8,
      each a small function.
    - `ApiSettings.raw: RawSettings = Field(default_factory=RawSettings)` and, in the existing
      model validator, the coupling: a set bridge secret requires a non-empty `public_api_url`.
  - Every place that sets the secret also sets the URL: `tests/raw_web_support.py`,
    `tests/unit/test_raw_web.py`, `tests/integration/test_raw_web_postgres.py`
    (`RawSettings(public_api_url="http://127.0.0.1:8099")`) and `scripts/polaris_dev.py`
    `raw_environment()` (`HURON_RAW__PUBLIC_API_URL=http://127.0.0.1:8080`).
  - `tests/unit/test_api_settings.py`: the defaults; `HURON_RAW__STORAGE_ROOTS` (JSON) and a scalar
    `HURON_RAW__*` read from the environment; each root refusal (17 entries, a non-`file` URI, a
    relative path, duplicate keys, equal and nested URIs and paths); each URL refusal; the `le=`
    caps; `test_settings_refuse_broken_ttl_relations` (one case per relation T1–T8);
    `test_public_api_url_required_with_bridge_secret`.
- Design: §6.6 Runtime composition (step 1); §9.2 Storage roots: the allowlist; §10.8 CHECK bounds
  are ceilings; §11.10 Chunk size and expiry; §17.8 Sizing and operations; §18.5 TTLs (T1–T8);
  §12.10 (Wiring); D-11, D-51, D-100, D-101, D-172.
- Verification: the plan-wide gate; the web gate (all five npm commands including
  `npm run test:e2e`), because `tests/raw_web_support.py` is the Playwright harness module;
  `rg -n "HURON_RAW__PUBLIC_API_URL" scripts/polaris_dev.py` finds the launcher's setting beside
  its bridge secret; `settings.py` at 100 %.
- Dependencies: M2.4.
- Status: pending

### M2.7 Storage roots adapter

- Intent: the POSIX adapter that maps each allowlisted root key to its mount and decides, at
  startup and on every probe, whether the root is the volume it was initialized as: sentinel
  creation only for a key without a recorded identity, atomic publication and adoption, comparison
  of `schema`, `key`, `uri` and `root_id`, `require_mount`, one device for the root and its hidden
  area, and an availability table. Rawstore composes no document and reads no database: sentinel
  bytes, recorded identities and referenced keys arrive from the wiring (M4.7). The per-call guard
  and absence confirmation land with the first placement-addressed methods (M2.8).
- Delete: none.
- Create / Modify:
  - `src/huron/core/rawstore/roots.py` (new): `PosixStorageRoots.open(mounts, *, sentinels,
    recorded, referenced, require_mount, reserve_bytes)`:
    - `sentinels` keyed other than `mounts`, or a `require_mount` key outside it, is a `ValueError`
      (a wiring bug); `recorded` and `referenced` may name keys no longer configured, and such a
      referenced key is UNAVAILABLE (`unconfigured`);
    - stray `.huron/root.json.*` candidates are removed first;
    - each key follows the §9.2 table: a missing `path` or one that is not a real directory is
      `path_missing` (a root path is never created); an unrecorded, unreferenced key without a
      sentinel (and, with `require_mount`, a mount point) gets `.huron/{staging,deleted,trash,
      quarantine}` at 0700 and its candidate published by `link(2)` (§9.6.5: candidate written
      `O_CREAT | O_EXCL | O_NOFOLLOW` at 0444 and fsynced, link, unlink, fsync of `.huron/`; on
      `EEXIST` the winner is re-read, compared on `schema`, `key` and `uri`, and its `root_id`
      adopted); `require_mount` on a non-mount is `not_mounted`; no sentinel with a record or a
      reference is `sentinel_missing`; a present sentinel (opened `O_NOFOLLOW`, ≤ 4 KiB, JSON valid
      against `raw-root-v1.json`) must equal the configuration and, when recorded, its `root_id`,
      else `sentinel_mismatch`, as is a recorded `uri` other than the configured one; an
      unrecorded equal sentinel is adopted; `path`, `.huron/` and its four children must share
      `st_dev`, else `cross_device`;
    - an UNAVAILABLE key is logged with its reason and never raises;
    - one `PosixRawStore(path, reserve_bytes=…)` per key; `identities()` gives, per AVAILABLE key,
      the identity found or written; one `threading.Lock` guards the state table, with every probe
      and I/O outside it;
    - `root_available(key)` re-runs the read-only rows, never creates a sentinel, records the
      result in both directions and answers `False` for an unknown key.
  - `src/huron/core/rawstore/store.py`: `PosixRawStore.__init__` takes `reserve_bytes` (renamed
    from `completion_reserve_bytes`) for its `CompletionAdmission`; `max_concurrent_completions`
    stays until the slot leaves (M5.7). Its two callers pass the new name:
    `src/huron/applications/api/app.py` and the `staged_upload` fixture of
    `tests/unit/test_rawstore_completion_admission.py` (`reserve_bytes=25`). The
    `ApiSettings.completion_reserve_bytes` field keeps its name until M5.7 removes it.
  - `src/huron/core/rawstore/__init__.py`: exports `PosixStorageRoots`.
  - `tests/unit/test_rawstore_roots.py` (new; temporary roots, stubbed `st_dev` and
    `os.path.ismount`, candidate bytes from `root_sentinel`): every §9.2 row, including a recorded
    key without a sentinel, adoption, another `root_id` and `require_mount` on a plain directory;
    `test_purged_root_never_gets_a_fresh_sentinel`; `test_sentinel_publication_is_atomic` (a crash
    between candidate and link leaves no `root.json` and the next `open` removes the candidate; the
    `link(2)` race leaves one complete sentinel whose `root_id` both openers adopt);
    `test_root_remap_refused_by_sentinel`; oversized, symlinked and non-JSON sentinels count as
    different; `identities()`; every availability transition through `root_available`.
- Design: §9.2 Storage roots: the allowlist (the sentinel table); §9.3 The hidden area of each root;
  §9.6.5 `.huron/root.json`; §9.8.6 The POSIX adapter (`open`, "Availability"); §6.5 rule 4; D-17,
  D-94, D-122, D-172, D-173, D-174.
- Verification: the plan-wide gate; `uv run lint-imports` keeps "rawstore uses schema only";
  `roots.py` at 100 % in the unit run, radon grade A and under about 400 lines; the named tests
  pass.
- Dependencies: M2.1, M2.2, M2.4.
- Status: pending

### M2.8 Dataset-root claims, the empty-root sweep and the per-call guard

- Intent: the two dataset-root calls that creation makes and the empty-root sweep the `CONFLICT`
  report needs, together with the sequence every placement-addressed call runs through
  `PosixStorageRoots`: refuse an unknown or UNAVAILABLE key, and a placement whose `base_location`
  is not the key's `uri` + `path` + `/`, before any I/O; re-read the sentinel before deciding on or
  creating directories outside `.huron/`; check the device under the placement; confirm every
  absence answer. The storage ports are declared with exactly the methods that exist.
- Delete: none.
- Create / Modify:
  - `src/huron/schema/storage.py`: `CrossDeviceCommitError(OSError)`, moved from
    `rawstore/commit.py`; `commit.py`, the `rawstore/__init__.py` re-export (beside
    `PosixRawStore`, as §9.8.1 lists it) and the test importers follow.
  - `src/huron/core/rawstore/materialize.py`: `descendant(..., mode=0o700)`; each directory it
    creates gets `fchmod(mode)` through its own descriptor right after `mkdir`; existing
    directories keep their mode and owner.
  - `src/huron/core/rawstore/store.py`: `claim_dataset_root(path)` (§9.8.4 steps 2–4: an
    `O_NOFOLLOW` walk, `ELOOP`/`ENOTDIR` → `DatasetRootOccupiedError`, the nearest existing
    directory's `st_dev` against `.huron/staging` → `CrossDeviceCommitError`, then the strict
    emptiness rule with its one empty, service-owned `versions/`) and `ensure_dataset_root(path)`
    (the device check, then parents, root and `versions/` through `descendant(create=True,
    mode=0o755)`, each new directory and its parent fsynced; idempotent).
  - `src/huron/core/rawstore/sweep.py` (new): `remove_empty_root` as a module function (§9.8.5).
  - `src/huron/core/rawstore/roots.py`: the §9.8.6 sequence (steps 1–5) and the methods
    `claim_dataset_root(placement)`, `ensure_dataset_root(placement)` and
    `remove_empty_root(placement)`; absence is confirmed by re-reading the sentinel (with
    `root_id`) and the nearest existing ancestor's `st_dev`; a missing `.huron/` child is
    `sentinel_missing`; a failed confirmation marks the root UNAVAILABLE, while `cross_device`
    under a placement and `placement_mismatch` refuse only that call (logged at ERROR).
  - `src/huron/core/raw/ports.py`: `VersionArchive` (`claim_dataset_root`, `ensure_dataset_root`)
    and `StorageSweeper` (`root_available`, `remove_empty_root`), consumer-owned Protocols that grow
    with their slices.
  - `tests/unit/test_rawstore_store.py`: the §9.9 claim and ensure cases (absent; empty; an empty
    service-owned `versions/` accepted; a `versions/` holding an entry or of another owner
    (stubbed) refused; non-empty; a symlink or a file on the path; another device (stubbed);
    0755 under a `0o077` umask; idempotent ensure; ensure refusing another device), including
    `test_existing_nonempty_dataset_root_refused` with its normalization case (an NFD-spelled
    claim of a non-empty NFC-named directory is refused wherever the filesystem folds the two,
    which the test probes first).
  - `tests/unit/test_rawstore_sweep.py` (new): `remove_empty_root` against an absent, an empty, a
    foreign-owned (stubbed) and a non-empty `versions/`.
  - `tests/unit/test_rawstore_roots.py`: `test_placement_with_foreign_prefix_refused`,
    `test_sub_mount_never_counts_as_absence` (a stubbed `st_dev` change at a namespace directory
    turns `remove_empty_root`'s absence into `cross_device`), a sentinel removed after `open` (the
    claim raises `sentinel_missing` and the root turns UNAVAILABLE), unknown and unconfigured keys.
  - `tests/unit/test_rawstore_materialize.py`: the `descendant(mode=)` cases.
- Design: §9.4 The dataset root and its versions; §9.8.1 (`CrossDeviceCommitError`); §9.8.4
  `VersionArchive` (`claim_dataset_root`, `ensure_dataset_root`); §9.8.5 `StorageSweeper`
  (`remove_empty_root`); §9.8.6 ("Every port method"); §8.7.4 Storage ports and the trigger; D-18,
  D-91, D-92, D-149, D-169, D-174, D-175.
- Verification: the plan-wide gate; every touched rawstore module at 100 % in the unit run;
  `rg -n "class CrossDeviceCommitError" src` finds only `src/huron/schema/storage.py`;
  `uv run lint-imports`; the named tests pass.
- Dependencies: M2.7.
- Status: pending

## Milestone 3 — Schema registry, PLATFORM half (slice 2)

Goal: migration `0014` with the PLATFORM seed, the one Raw credential on the v1 tree, and read
access to PLATFORM schemas, so the first Raw routes run under `raw_grant`.

### M3.1 Migration 0014_raw_schema_registry

- Intent: create the registry's two tables, the one trigger raise point and the PLATFORM seed in
  Alembic revision `0014`, statement for statement as §10.4 gives them, with contract proofs on
  `postgres:16`; the schema map and the two tests that pin a head revision follow.
- Delete: none.
- Create / Modify (load `postgresql-table-design`):
  - `migrations/versions/0014_raw_schema_registry.py` (new): `revision =
    "0014_raw_schema_registry"`, `down_revision = "0013_retire_releases"`; `DDL`, one `r"""…"""`
    block run through `migrations._ddl.execute_sql`: `raw_refuse(rule, detail)`,
    `raw_schema_subjects`, `raw_schema_versions`, the triggers `raw_schema_subjects_identity`,
    `raw_schema_versions_contiguous`, `raw_schema_versions_immutable` and the deferred constraint
    triggers `raw_schema_versions_counted` and `raw_schema_subjects_latest_recorded`; `SEED`, built
    in Python from `SEED_SUBJECT_ID`, `SEED_VERSION_ID` and the frozen `SEED_DOCUMENT` (the RFC 8785
    bytes of `raw-metadata-v1.json`, pasted as a bytes literal; the migration imports nothing from
    `huron`), with the §10.4 description, `huron-migration`, `now()` and the `latest_number` bump;
    `upgrade()` runs `DDL`, then `SEED`; `downgrade()` raises `RuntimeError("the Raw schema
    registry cannot be downgraded: versions pin its rows")`.
  - `migrations/schema.sql`: stamp `-- Reflects: 0014_raw_schema_registry`; new section "7. Raw
    storage" with the §10.12 header and the `raw_schema_subjects` and `raw_schema_versions` blocks.
  - `tests/contract/test_raw_schema.py` (new; one container per module, `upgrade head`):
    - `test_schema_map_names_every_raw_object`: for the eight Raw table names in one explicit list
      that never changes afterwards (`raw_schema_subjects`, `raw_schema_versions`,
      `raw_realm_bindings`, `raw_storage_roots`, `raw_datasets`, `raw_upload_sessions`,
      `raw_upload_files`, `raw_versions`; `relname = ANY($1)`, never `LIKE`, so a table a later
      revision creates is found once it exists), every non-internal trigger, every CHECK and
      UNIQUE not ending in `_check` or `_key` and every index not ending in `_pkey` or `_key`
      occurs in `migrations/schema.sql`;
    - one proof per trigger (SQLSTATE 23514 with `constraint_name` equal to the trigger's name):
      a renamed or deleted subject, `latest_number` + 2, a version number with a gap, a version born
      DEPRECATED, changed bytes, DEPRECATED → ACTIVE, a deleted version, and at `COMMIT` an uncounted
      version and a counter without its version;
    - one proof per CHECK and UNIQUE: scope shape, name pattern, description length, number and
      `latest_number` ranges, document of 1 and 262145 bytes, deprecation shape,
      `raw_schema_subjects_name` with NULLS NOT DISTINCT (two PLATFORM subjects of one name refused,
      one name in two catalogs allowed) and `raw_schema_versions_content`;
    - `test_platform_seed_matches_the_packaged_document`: the §16.11 rows, `latest_number` 1, and
      the stored document byte-equal both to the migration's `SEED_DOCUMENT` and to
      `canonical_bytes(load_schema("raw-metadata-v1.json"))`;
    - the downgrade raises and leaves `alembic_version` at `0014`.
  - `tests/contract/test_commit_intents.py`: the `0011`-refusal test upgrades to
    `"0012_raw_web_catalogs"` and asserts that revision (§10.3).
  - `tests/contract/test_catalog_store.py`:
    `test_retiring_release_tags_drops_their_objects_and_capability_and_refuses_a_downgrade` upgrades
    to `"0013_retire_releases"` instead of `head`, because its downgrade to `0012` would otherwise
    meet `0014`'s refusal first; its docstrings say so. The suite stays migration history (§21.3).
- Design: §10.1 Conventions; §10.2 Object inventory; §10.3 Migration chain; §10.4
  `0014_raw_schema_registry`; §10.12 `migrations/schema.sql` map update ("Map conformance"); §16.11
  PLATFORM seed; §22.3 Contract tests on Docker; D-56, D-67, D-68, D-111, D-120, D-140, D-176.
- Verification: the plan-wide gate, with `uv run python scripts/check_schema_map.py` green at the
  new head and `uv run pytest -m contract` and `-m integration` on Docker (background, polled);
  every database those suites migrate passes through `0014`. No adapter statement is added, so no
  floor reset.
- Dependencies: M2.2.
- Status: pending

### M3.2 Delegation claims and RawGrant

- Intent: widen the BFF delegation to the redesign's claims (six permissions; a nullable, possibly
  catalog-level target; the catalog storage facts) while `/api/raw-web` keeps verifying, and give
  core the transport-free authority value `RawGrant`, which checks scope before permission and
  enforces the realm binding (D-89).
- Delete: none.
- Create / Modify (load `oop-design`):
  - `src/huron/core/security/raw_delegation.py`: `RawPermissionName` (`read`, `write`, `create`,
    `manage`, `drop`, `schema`); `DelegationTarget.name: str | None` (a required key) with the model
    validator `(name is None) == (len(namespace) == 0)`; `CatalogStorageClaim` (§12.3 fields and
    bounds, frozen, `extra="forbid"`); `_Claims.target: DelegationTarget | None` (a required key),
    `permissions: frozenset[RawPermissionName]`, `catalog_storage: CatalogStorageClaim | None =
    None`; `RawDelegation` gains `catalog_storage`. Its raw-web members (`require`, `require_scope`,
    `verified_chunks`, `DelegatedBindings`, `raw_dataset_bindings`) leave with M5.1.
  - The raw-web path keeps answering dataset-level delegations only:
    `applications/api/raw_web.py` `signed_request` refuses a null or catalog-level target with
    `AuthError` (401), and `core/catalog/external.py` and `applications/api/routes/raw_web.py`
    narrow `delegation.target` where they read it (no `cast`, no `type: ignore`);
    `tests/unit/test_raw_web.py` gains that 401 case.
  - `src/huron/core/raw/grants.py` (new): `RawPermission`, `CatalogRef`, `RawGrant` (`catalog`,
    `require`, `dataset_target`, `require_target`, `require_catalog`, `require_owner`,
    `require_body_digest`) exactly as the §12.11 table states, using foundation's `Forbidden`,
    `AuthError` and `ResourceNotFound` and `hmac.compare_digest` for the digest.
  - `src/huron/core/raw/locations.py`: `DatasetLocator.catalog_ref`; `locations.py` names
    `CatalogRef` only under `TYPE_CHECKING` and imports it inside the property, because `grants.py`
    imports `locations.py` at module level.
  - `src/huron/core/raw/errors.py`: `RealmBindingConflict` (409 `REALM_BINDING_CONFLICT`) in
    `ERROR_CODES`; `design/api.html` §7 row (live, `—`, the §19.6 meaning). `RawGrant` is its first
    raiser.
  - `tests/unit/test_raw_delegation.py` (new): the six permissions and an unknown one (401); null,
    catalog-level and dataset-level targets; the shape rule both ways (401); `catalog_storage`
    bounds (0 and 65 locations and 4097-character values refused); unknown claims refused;
    `test_delegation_lifetime_rules` (§12.13: `exp − iat` of 0 and of 61 s, an expired token and
    an `iat` in the future each answer `401`, with zero leeway; 60 s passes).
  - `tests/unit/test_raw_grants.py` (new): the §12.11 table row by row; scope before permission (a
    foreign target without the permission answers 404, never 403); `dataset_target` on catalog and
    null targets (401); the digest rule (`sha1` under a delegated digest answers 401, any algorithm
    passes with `body_sha256=None`); `test_realm_binding_conflict_409`;
    `test_unbound_realm_404_except_create` at the grant (`require_catalog` with `endpoint=None`
    answers 404; the two pinning calls run through their services in M4.6 and M4.9).
- Design: §12.3 Delegation claims; §8.3.2 Authority (`core/raw/grants.py`); §12.11 `RawGrant`: what
  the services see; §12.14 Tests; D-10, D-33, D-34, D-89, D-101, D-159.
- Verification: the plan-wide gate; the raw-web suites (`test_raw_web.py`,
  `tests/integration/test_raw_web_postgres.py`) stay green; `grants.py`, `raw_delegation.py` and
  every touched module at 100 %; `uv run lint-imports` (core/raw imports neither `security` nor a
  framework).
- Dependencies: M1.3, M2.4.
- Status: pending

### M3.3 Schema documents and RE2 validation; ADR 0003

- Intent: the registry's document rules and the tenant-regex hardening: `SchemaDocument.parse`
  applies publish rules 1–6 and refuses with `422 SCHEMA_INVALID`, and `RawMetadataValidator`
  matches `pattern` and `patternProperties` with RE2, so no tenant regex can backtrack. `google-re2`
  becomes a runtime dependency, and ADR 0003 records the narrowed decision 16. Subjects and
  versions follow in M3.4.
- Delete: none.
- Create / Modify (load `oop-design`; `domain-modeling` for the ADR):
  - `pyproject.toml` and `uv.lock`: `google-re2` in `[project].dependencies` (through `uv add`, so
    `uv run --locked` keeps passing). Every use of `re2` stays behind two typed functions in
    `schemas.py`. If the installed package ships no `py.typed` marker, `pyproject.toml` gains
    exactly one `[[tool.mypy.overrides]]` table, `module = "re2"` with
    `ignore_missing_imports = true` and a comment in the manner of the existing `asyncpg.*`
    override, and, only if `uv run ty check` then reports `unresolved-import` for `re2`,
    `allowed-unresolved-imports = ["re2"]` under `[tool.ty.analysis]`. Nothing else in the tool
    configuration changes; the verifier checks these lines against this bullet (the "Clean sweep"
    rule) and records which of the two were needed in Execution notes.
  - `src/huron/core/raw/schemas.py` (new): `SchemaDocument(canonical, sha256)`; `parse(document)`
    composes one small function per §16.6 rule (a JSON object of 2..262144 JCS bytes with safe
    integers; the exact `$schema`; top-level `"type": "object"`; the Draft 2020-12 metaschema, with
    every error collected; every string `$ref` and `$dynamicRef` local; every `pattern` value and
    `patternProperties` name at most 1,024 characters and RE2-compilable, wherever it sits) and
    raises `SchemaInvalid(context={"errors": [...]})` with at most 20 `{pointer, message}` ordered
    by pointer; `stored(payload)` raises `ValueError` unless the bytes are their own canonical form
    (`decode_canonical`); `RawMetadataValidator` is
    `jsonschema.validators.extend(Draft202012Validator, {...})` with RE2-backed `pattern` and
    `patternProperties` that keep jsonschema's messages.
  - `src/huron/core/raw/errors.py`: `SchemaInvalid` (422 `SCHEMA_INVALID`) in `ERROR_CODES`;
    `design/api.html` §7 row (live, `—`).
  - `docs/adr/0003-raw-metadata-schema-registry.md` (new, `status: accepted`): the §16.12 narrowing
    (PLATFORM and CATALOG scopes, integer versions, ACTIVE/DEPRECATED, `schema.json` embedded in
    each version instead of a mirror, version-metadata schemas only); ORGANIZATION and PROJECT
    scopes and the other document kinds stay future work. Relative links stay inside `docs/` for
    the strict build; the design pages point at the ADR in M14.3.
  - `tests/unit/test_raw_schemas.py` (new): each rule's refusal with its pointer (a non-object, 1
    and 262145 bytes, an unsafe integer, another `$schema`, a non-object type, a metaschema
    violation, a remote `$ref`, a nested remote `$dynamicRef`; more than 20 errors cut and ordered);
    `raw-metadata-v1.json` passes and `canonical` is its JCS; `stored` refuses pretty-printed
    bytes; `test_regex_outside_re2_is_schema_invalid` (a backreference and a lookahead, under
    `items`, `$defs` and `propertyNames`); `test_overlong_regex_is_schema_invalid` (1,025
    characters); `test_backtracking_pattern_validates_in_linear_time` (`^(a|aa)+$` parsed, then
    `RawMetadataValidator` over `"a" * 1_000_000 + "b"` within 2 s through a property `pattern`,
    `patternProperties` and `propertyNames`).
- Design: §8.4.4 `SchemaSubject` and `SchemaVersion` (`SchemaDocument`, the validator bullet);
  §16.1 Model; §16.2 Identifiers; §16.6 Validation points (publish rules, "Tenant regexes run under
  RE2", "Dependency"); §16.12 Relation to design decision 16 (ADR 0003); §6.4 (`re2` in
  `schemas.py` only); D-55, D-56, D-59, D-110, D-161; OD-10 O-3.
- Verification: the plan-wide gate and `make docs`; `rg -n "^\s*(import|from) re2" src` finds only
  `core/raw/schemas.py`; `schemas.py` at 100 %; the named tests pass.
- Dependencies: M2.2, M2.3.
- Status: pending

### M3.4 Schema subjects and versions

- Intent: the registry aggregates: a subject owns a linear series of immutable versions, and the
  read, publish, bind and pin rules are its methods; a version validates metadata against itself
  on RE2 through a cache of 64 validators. The three refusals these rules raise land here with
  their §7 rows, since this is their first raiser.
- Delete: none.
- Create / Modify (load `oop-design`):
  - `src/huron/core/raw/schemas.py`: `SchemaScope`, `SchemaVersionState`, `SubjectDraft` (name
    pattern, description ≤ 4000; `ValueError`), `SchemaSubject` (§8.4.4 fields; `qualified`;
    `require_readable` passes PLATFORM and calls `grant.require_catalog` for CATALOG;
    `require_publishable` answers `Forbidden` for PLATFORM, then checks scope (`require_catalog`)
    before `require(SCHEMA)`, per D-89 and §12.11; `require_bindable(locator)`, which also refuses a
    null `latest_active_number` (D-151); `next_version`, a `ValueError` at 999999), `SchemaVersion`
    (`require_pinnable`, `deprecate` returning `False` when already DEPRECATED, `validate(metadata)
    -> bytes`: a module-level cache of 64 `RawMetadataValidator`s keyed by schema version id, each
    with `FormatChecker()` and an empty `referencing.Registry()`; errors from `iter_errors` ordered
    by `json_path`, cut to 20, as `{pointer, message}`; metadata whose JCS exceeds 1,048,576 bytes
    answers one error with pointer `""`), and `PLATFORM_METADATA_SUBJECT_ID`.
  - `src/huron/core/raw/errors.py`: `SchemaSubjectNotUsable`, `SchemaVersionNotUsable`,
    `MetadataInvalid` (each 422) in `ERROR_CODES`; their `design/api.html` §7 rows (live, `—`,
    the §19.6 meanings).
  - `tests/unit/test_raw_schemas.py`: the §16.3 table (PLATFORM readable by null, catalog and
    dataset targets; CATALOG readable only within its realm and catalog under the pinned endpoint,
    404 otherwise, 409 on another endpoint; publishing PLATFORM is 403, a foreign catalog or an
    unbound realm 404 even without `schema`, a missing `schema` then 403); the bind cases including
    a subject without an ACTIVE version; `next_version` and its ceiling; idempotent `deprecate`;
    `require_pinnable`; `validate` (canonical bytes back, ordered and capped errors, the 1 MiB cap,
    format checks, a stored document with a remote `$ref` failing closed with no network call, the
    cache holding 64 validators); the linear-time case again through `SchemaVersion.validate`.
- Design: §8.4.4; §16.3 Scopes and authority; §16.4 Version states; §16.6 (metadata validation at
  session start); §16.8 Core types, service and port; D-55, D-57, D-58, D-89, D-110, D-151, D-161.
- Verification: the plan-wide gate; `schemas.py` at 100 % and radon grade A (split rule helpers
  into module functions if it nears the 400-line budget of §8.10); the error-contract tests pass
  with the three rows.
- Dependencies: M3.2, M3.3.
- Status: pending

### M3.5 Registry ports and the in-memory store

- Intent: declare the shared Raw transaction protocols and the registry's store ports (without
  `bind_realm`, which needs `0015`), and give them an in-memory adapter that runs the scenarios the
  PostgreSQL adapter will run too (M3.6). The in-memory Raw stores share one state object, as the
  PostgreSQL adapters share one database, so the dataset store (M4.4) and catalog subject creation
  (M4.9) later see the same realm bindings.
- Delete: none.
- Create / Modify (load `oop-design`):
  - `src/huron/core/raw/ports.py`: `RawTransaction(RetryTransaction, Protocol)` (`now`,
    `append_audit`), `SchemaVersionRows` (`lock_schema_version`), `SchemaStore` (`transaction`,
    `subject`, `subjects`, `schema_version`, `schema_version_by_id`, `schema_versions`,
    `pinnable_version`) and `SchemaTransaction(RawTransaction, SchemaVersionRows, Protocol)`
    (`insert_subject`, `lock_subject`, `find_schema_version`, `insert_schema_version`,
    `deprecate_schema_version`), with the §8.7.1–§8.7.2 signatures and statement comments; list
    methods return `foundation.paging.Window`.
  - `src/huron/core/raw/errors.py`: `SchemaSubjectExists` (409 `SCHEMA_SUBJECT_EXISTS`,
    `context.subject_id` naming the holder) in `ERROR_CODES`; its `design/api.html` §7 row (live,
    `—`). The in-memory `insert_subject` is its first raiser; PostgreSQL maps it in M3.6.
  - `src/huron/core/metastore/raw_memory.py` (new): the shared in-memory Raw state: tables keyed as
    their PostgreSQL counterparts, idempotency receipts with today's semantics (24 h, a reused key
    with another fingerprint refused), audit rows, one `asyncio.Lock` serializing transactions, a
    snapshot committed on success and discarded on any exception, and `now()` constant within a
    transaction from an injected `Clock`. If the duplication guard pairs its claim logic with
    `InMemoryHierarchyStore`'s, extract one helper both use rather than accept a new signature.
    §6.4 and §8.7.5 do not list this module, so it is deviation 7 and its Execution note gives the
    reason (one shared state, as the PostgreSQL adapters share one database).
  - `src/huron/core/metastore/raw_schemas.py` (new): `InMemorySchemaStore` and its transaction:
    PLATFORM subjects plus the given catalog's, ordered by `(name, id)` in code-point order with a
    keyset after `(name, id)`; `latest_active_number` computed on read; versions newest first
    before a number; `pinnable_version` (a given number in any state, otherwise the highest ACTIVE,
    otherwise `None`); `insert_subject` refuses a taken `(realm, catalog, name)` (PLATFORM names
    form one name space); `insert_schema_version` also sets the subject's `latest_number`; unknown
    ids raise `ResourceNotFound`. Its constructor takes the rows a migrated database starts with
    (`seed`), so test builders stay synchronous. `metastore/__init__.py` exports the store.
  - `tests/raw_store_contract.py` (new): shared scenarios over any store that holds the PLATFORM
    seed, and `platform_seed()`, the PLATFORM subject and version 1 exactly as `0014` seeds them
    (ids, `huron-migration`, the packaged document's JCS). Scenarios: the seed's reads by
    id and by global version id; listing with and without a catalog, ordering and keyset windows;
    `insert_subject` uniqueness (PLATFORM, same catalog, another catalog); a registration in one
    transaction (`lock_subject`, `find_schema_version`, `insert_schema_version`, the counter);
    `pinnable_version`'s three answers; deprecation and the recomputed `latest_active_number`;
    `lock_schema_version` and unknown ids; rollback of rows, audit and receipt on an exception;
    `claim`/`remember` replay and `IdempotencyKeyReused` (any existing `Replay` kind: the registry's
    own kinds arrive with its writers in M4.9); `now()` constant within a transaction.
  - `tests/unit/test_raw_stores_memory.py` (new): a fresh in-memory store built with
    `platform_seed()` per scenario.
- Design: §8.7.1 Shared transaction protocols; §8.7.2 Family ports (`SchemaStore`,
  `SchemaTransaction`); §8.7.5 Adapters; §16.9 Store statements; §10.3 (the slice table); D-110,
  D-139.
- Verification: the plan-wide gate; the new modules at 100 % in the unit run; the duplication guard
  passes, with slice 2 (M3.x) taking at most four new clones in total (§22.5), the running total
  in Execution notes.
- Dependencies: M1.3, M3.4.
- Status: pending

### M3.6 PostgreSQL registry store

- Intent: the PostgreSQL registry store with every §16.9 statement, refusals mapped by constraint
  name, and the `RawTransaction` mixin that every Raw transaction will share; contract-tested on
  `postgres:16` against the same scenarios as the in-memory store. This is the first task whose
  adapter statements only the contract run covers, so it applies the first OD-12 O-8 reset.
- Delete: none.
- Create / Modify (load `postgresql-table-design`):
  - `src/huron/core/metastore/rows.py`: the `RawTransaction` mixin over one connection and a clock
    (`now()` from `SELECT now()`, constant within the transaction; `append_audit`; `claim`;
    `remember`). The claim, remember and audit statements move here out of `hierarchy.py`'s
    `_PostgresTransactionWriter`, which now uses them, so each statement exists once (D-77). New
    row mappers `schema_subject(row)` and `schema_version(row)`.
  - `src/huron/core/metastore/raw_schemas.py`: `PostgresSchemaStore(pool)` and its transaction:
    the subject read with its `latest_active_number` subquery; subjects ordered by
    `name COLLATE "C", id` with the `(name, id)` keyset, so both adapters order alike; versions
    newest first; the explicit and default pins and the `FOR SHARE` re-check; registration under
    `FOR UPDATE` on the subject; `deprecate … WHERE state = 'ACTIVE' RETURNING *`. A
    `raw_schema_subjects_name` violation becomes `SchemaSubjectExists` with the holder read back;
    trigger refusals (SQLSTATE 23514, `constraint_name` = the trigger) and deferred refusals at
    `COMMIT` are caller bugs and propagate (500). `metastore/__init__.py` exports the store.
  - `tests/contract/test_raw_stores_postgres.py` (new; one container per module at head, whose
    migration already holds the PLATFORM seed): every scenario of `tests/raw_store_contract.py`,
    plus two concurrent registrations of identical bytes from two pools (they serialize on the
    subject row; the second answers the first version),
    `test_fifty_concurrent_distinct_registrations_number_gap_free` (§10.6's allowed proof of
    `raw_schema_versions_contiguous`: 50 registrations of distinct documents on one new subject
    from two pools give the numbers exactly 1..50 and `latest_number` 50, with no trigger
    refusal), the `NULLS NOT DISTINCT` mapping, and a deferred counter refusal surfacing at
    `COMMIT`.
- Design: §16.9 Store statements; §8.7.5 Adapters; §10.7 Access paths (the registry rows); §22.3
  Contract tests on Docker; §22.4 Coverage (OD-12 O-8); D-77, D-84, D-133, D-154.
- Verification:
  - The plan-wide gate, with `-m contract` and `-m integration` on Docker.
  - `uv run pytest -m "unit or contract" --cov=src/huron --cov-report=term-missing
    --cov-fail-under=0`: `raw_schemas.py` and `rows.py` at 100 % (the moved claim's "row vanished"
    `RuntimeError` stays the one line the verifier may name as unreachable, as for `hierarchy.py`
    in M0.3); `hierarchy.py`'s missed count does not grow.
  - OD-12 O-8 reset: `fail_under = floor(10000 × covered / statements) / 100` of the new unit
    total, the verifier confirming every new adapter statement covered by the run above; counts in
    Execution notes. Slice-2 clone budget, running total recorded.
- Dependencies: M3.1, M3.5.
- Status: pending

### M3.7 Registry PLATFORM reads and their wiring

- Intent: the registry service's PLATFORM half: `SchemaRegistry` reads subjects and versions for
  any delegation under the PLATFORM read rule and is composed into `RawRuntime` beside the old
  engine (D-137), built from `ApiStores.raw_schemas` (PostgreSQL in production, a seeded in-memory
  store in tests). A CATALOG subject answers 404 until the catalog half (M4.9), which needs the
  realm bindings of `0015`.
- Delete: none.
- Create / Modify (load `oop-design`):
  - `src/huron/core/raw/_impl/schemas.py` (new): `SchemaRegistry(schemas)` with `subjects(grant, *,
    after, limit)` (PLATFORM subjects only in this half), `subject`, `versions(grant, subject_id, *,
    before, limit)`, `version` and `version_by_id`; every read runs
    `SchemaSubject.require_readable(grant, endpoint=None)`, so a CATALOG subject, its versions and
    its global version ids answer 404, as unknown ids do. M4.9 adds `datasets`, `clock` and the
    writes.
  - `src/huron/core/raw/__init__.py`: exports `SchemaRegistry`.
  - `src/huron/core/raw/runtime.py`: `RawRuntime(storage, persistence, *, schemas, clock)` exposes
    `schemas: SchemaRegistry` beside the legacy services.
  - `src/huron/applications/api/runtime.py` and `app.py`: `ApiStores.raw_schemas: SchemaStore`;
    `_postgres_stores` builds `PostgresSchemaStore(pool)`; `_build_runtime` passes it on.
  - `tests/unit/support.py`: `memory_stores()` adds an `InMemorySchemaStore` built with
    `platform_seed()`; the direct `RawRuntime(...)` constructions in `test_core_workflows.py` and
    `test_authorization_credentials.py` pass a store.
  - `tests/unit/test_raw_services.py` (new): registry reads for null, catalog-level and
    dataset-level grants; `(name, id)` windows and the newest-first version window with `before`;
    a version by number and by global id; unknown ids; a CATALOG subject placed in the store is
    absent from lists and answers 404 by id, by number and by global version id.
- Design: §8.6.6 `SchemaRegistry`; §8.6.8 `RawRuntime`; §16.3 Scopes and authority; §16.8; §6.6
  Runtime composition (step 2); D-110, D-137, D-139.
- Verification: the plan-wide gate (the integration suite starts the app on PostgreSQL, so the new
  wiring builds there); every touched module at 100 %.
- Dependencies: M3.4, M3.5, M3.6.
- Status: pending

### M3.8 Raw credential at the API

- Intent: the one Raw credential on the v1 tree: `DelegatedRawAuthority` verifies the BFF
  delegation from headers alone, reads at most the route's body limit only after the token passed
  (so a request without a valid delegation answers 401 before any body byte is read, D-156), and
  maps the verified claims to a `RawGrant`; `raw_grant` answers 404 while Raw is not configured.
  `RawAuthority` is the seam a later SDK authority fills (OD-6). No Raw route exists yet; the body
  cases run on a test route.
- Delete: none.
- Create / Modify (load `fastapi`):
  - `src/huron/applications/api/authorization/raw.py` (new): the constants `TUS_PREFIX`,
    `TUS_PATCH_BOUND`, `TUS_BOUND`, `JSON_BOUND`; the pure helpers `bound_header_names`,
    `streams_body`, `creates_dataset`, `body_limit` (16 MiB session start, 1 MiB for the three
    schema POSTs, 64 KiB dataset create and commit, 1 KiB every other POST, 0 for `GET`, `DELETE`,
    `HEAD` and `OPTIONS`; never consulted for the streamed PATCH) and `signed_path` (raw path plus
    `?query` when non-empty); `RawAuthority` (Protocol, `grant(request)`); `DelegatedRawAuthority`
    (checks 1–4 of §12.10, each a helper of complexity ≤ 4; the mapping gives a `DatasetLocator`, a
    `CatalogRef` or `None`, copies the delegated endpoint, maps the permission names, keeps
    `catalog_storage` only when `creates_dataset`, and sets `body_sha256` only when
    `streams_body`); `raw_grant`; `RawGrantDep`; `raw_body(shape)` (reads the bytes `read_capped`
    cached, validates with a `TypeAdapter`, raises `RequestValidationError` → 422).
  - `src/huron/applications/api/authorization/__init__.py`: exports `raw_grant`, `RawGrantDep`,
    `raw_body`, `RawAuthority` and `DelegatedRawAuthority`; its docstring names the Raw surface.
  - `src/huron/applications/api/streams.py`: `read_capped(request, limit) -> bytes` refuses a
    declared `Content-Length` above `limit` before reading and a streamed body as soon as its count
    passes `limit`, caches the bytes on `request.state` and returns them again on a repeat call.
  - `src/huron/applications/api/errors.py`: `RequestBodyTooLarge` (413 `REQUEST_BODY_TOO_LARGE`,
    `context.limit`) in `ERROR_CODES`; its `design/api.html` §7 row (live, `—`).
  - `src/huron/applications/api/runtime.py`: `ApiRuntime.raw_authority: RawAuthority | None = None`,
    `RawAuthority` imported only under `TYPE_CHECKING` (D-145); `app.py` `_build_runtime` builds
    `DelegatedRawAuthority(RawDelegationVerifier(secret))` once when the secret is set, importing it
    from `huron.applications.api.authorization`.
  - `tests/raw_client.py` (new): a delegation-signing test client for `/api/v1/raw` (actor, target
    or catalog target or `null`, permissions, `catalog_storage`, the bound headers of
    `bound_header_names`, a given PATCH digest), as `tests/raw_web_client.py` does for raw-web.
  - `tests/unit/test_raw_authority.py` (new): truth tables of `bound_header_names`, `streams_body`,
    `creates_dataset` and `body_limit` (one row per §12.2 route class); the claim-to-grant mapping
    for each target shape; `test_patch_body_not_read_by_dependency`;
    `test_head_and_delete_bodies_verified_empty`; `test_malformed_json_without_credential_is_401`
    (`WWW-Authenticate: Bearer`, never 422); `test_bound_header_tamper_is_401` (each of the five
    PATCH headers); `test_unauthenticated_oversized_body_refused_before_read` on test-only routes
    mounted under `/api/v1/raw` at paths no real route will take (no or a wrong delegation with a
    32 MiB body: 401 before `receive` yields a body message; a valid delegation: 413 for a declared
    length and for a chunked body, after at most the limit was read); `read_capped`'s cache;
    `raw_grant` answering 404 while the secret is empty. Per-route rows follow with each route task.
- Design: §12.4 Request binding; §12.10 How the v1 Raw routes accept the delegation; §12.12 The
  seam for a later API-key / SDK path; §6.5 Composition rules (rules 1–2); §12.14 Tests; §19.6
  (`REQUEST_BODY_TOO_LARGE`); D-35, D-101, D-145, D-156.
- Verification: the plan-wide gate; `uv run lint-imports` (routes and `app.py` import only the
  authorization package's surface; no import cycle with `runtime.py`); the named tests pass;
  `raw.py`, `streams.py` and every touched module at 100 %.
- Dependencies: M3.2.
- Status: pending

### M3.9 Raw router and registry read routes

- Intent: split the v1 router so the Raw routes take the delegation as their only credential under
  the same `/api/v1` prefix (OD-7, D-126), and mount the first Raw routes: the five registry reads
  of PLATFORM subjects (routes 26, 28, 29, 31, 32), with their composition tests, OpenAPI tag and
  `design/api.html` rows.
- Delete: none.
- Create / Modify (load `fastapi`):
  - `src/huron/applications/api/routes/v1/__init__.py`: a dependency-free `router` (prefix
    `/api/v1`) with two children: `principal_routes` (`Depends(current_principal)`,
    `AUTHENTICATED_ERRORS`, every existing include) and `raw_routes` (prefix `/raw`,
    `Depends(raw_grant)`, `RAW_ERRORS`, including `raw_schemas.router`).
  - `src/huron/applications/api/problems.py`: `RAW_ERRORS` = `UNIVERSAL_ERRORS` plus 401, 403 and
    404 with the §19.1 texts; exported.
  - `src/huron/applications/api/routes/v1/endpoints/raw_schemas.py` (new): `router =
    APIRouter(prefix="/schemas", tags=["raw-schemas"])` with `list_schema_subjects` (26),
    `get_schema_subject` (28), `list_schema_versions` (29), `get_schema_version` (31) and
    `get_schema_version_by_id` (32): declared response types, `limit` and `after` on the lists,
    path ids typed `UUID` and `number` bounded 1..999999; each takes `RawGrantDep` and `RawDep`;
    no route redeclares 401, 403, 404, 422 or 500.
  - `src/huron/applications/api/routes/v1/schema/raw_schemas.py` (new): `SchemaSubjectView` and
    `SchemaVersionView` as §16.10 gives them, each built by one small function (`registry_url` from
    `RawSettings.public_api_url`, which M2.6 requires whenever Raw routes are enabled; `document`
    `null` in list items). `CreateSchemaSubject` lands with route 27 (M4.10).
  - `src/huron/applications/api/routes/v1/pagination.py`: `number_cursor_key()` for route 29; the
    subject list reuses `slug_cursor_key` for `(name, id)`; `page()` also accepts a render function
    (the Raw views need more than the record), Catalog's calls unchanged. `created_cursor_key()`
    lands with route 2 (M4.8).
  - `src/huron/applications/api/runtime.py`: `RawDep` (the published `RawRuntime`).
  - `design/api.html`: in §3, a `/api/v1/raw` table with the rows of routes 26, 28, 29, 31 and 32
    (authority, request, success); in §7, the new `FORBIDDEN` and `NOT_FOUND` meanings of §19.6
    ("Rows kept, with new text or disposition").
  - `tests/unit/test_api_router_composition.py`: the tag-set test adds `raw-schemas` and becomes
    `test_the_openapi_document_carries_seventeen_resource_grained_tags`; new
    `test_raw_operations_carry_a_raw_tag_and_the_raw_error_set`,
    `test_raw_routes_accept_only_the_delegation` (an API key, an OIDC bearer and a cookie session
    each answer 401 `INVALID_CREDENTIAL`; every Raw route answers 404 while the secret is empty),
    `test_raw_routes_declare_no_body_parameter` (its body-documentation half gains a row as each of
    routes 1, 6, 10, 14, 27 and 30 lands),
    `test_every_raw_route_depends_on_raw_grant_and_not_current_principal`
    and `test_no_raw_operation_redeclares_a_status_the_raw_router_already_covers`; the two-level
    tests keep their assertions and their docstrings count three levels.
  - `tests/unit/test_execution_model.py`: the five handlers in the operation table (coroutines).
  - `tests/unit/test_raw_schemas_api.py` (new): routes 26, 28, 29, 31, 32 through `tests/raw_client.py`
    with null, catalog-level and dataset-level targets: the PLATFORM subject and its version 1
    (`latest_active_number`, `registry_url`, `document`), list pages and `next_cursor`,
    `400 INVALID_CURSOR`, 404 for unknown ids and for a CATALOG subject placed in the store, 401
    without a delegation, 422 for a malformed id or number.
- Design: §6.5 rule 1; §19.1 Router composition and the one Raw credential; §16.10 API; §19.3 New
  routes (26, 28, 29, 31, 32); §19.4 Models; §19.5 HTTP conventions; §19.6 ("Rows kept"); §19.7
  Tags, OpenAPI, readiness and documentation ("Tags", "Composition tests", "design/api.html outside
  §7": the §3 rows); D-58, D-72, D-126, D-128, D-129, D-130.
- Verification: the plan-wide gate; `uv run lint-imports`; the OpenAPI document holds the five
  operations under `raw-schemas`; the named tests pass; every touched module at 100 %; slice-2
  clone budget kept (running total recorded).
- Dependencies: M3.7, M3.8.
- Status: pending

## Milestone 4 — Datasets and registration (slice 3)

Goal: migration `0015` and the Raw dataset: locator, placement, realm binding, property standard 2,
create and the registration reports REGISTERED and CONFLICT, storage roots in the runtime and
readiness, and the catalog half of the registry.

### M4.1 Migration 0015_raw_datasets

- Intent: create the realm bindings, the storage-root identities and the dataset table in Alembic
  revision `0015`, statement for statement as §10.5 gives them, with a contract proof for every
  trigger rule, CHECK and partial unique index on `postgres:16`.
- Delete: none.
- Create / Modify (load `postgresql-table-design`):
  - `migrations/versions/0015_raw_datasets.py` (new): `down_revision = "0014_raw_schema_registry"`;
    one `r"""…"""` `DDL` block through `execute_sql`: `raw_realm_bindings` with
    `raw_realm_bindings_immutable`; `raw_storage_roots` with `raw_storage_roots_immutable`;
    `raw_datasets` (immutable locator and placement including `placement_key`, `base_location`
    admitting only `file:///…/`, the JCS `create_request` and its generated digest, lifecycle,
    `etag`, `latest_number`, deletion facts, work columns, and the CHECKs `…_placement_shape`,
    `…_registration_shape`, `…_pending_empty`, `…_deletion_shape`, `…_tombstone_shape`,
    `…_purge_shape`, `…_work_shape`); the indexes `raw_datasets_live_locator`,
    `raw_datasets_placement` (on `placement_key`), `raw_datasets_pending_owner`,
    `raw_datasets_park_due`, `raw_datasets_purge_due`, `raw_datasets_schema_subject`; the triggers
    `raw_datasets_identity` (with the etag-only `+1`) and `raw_datasets_discard`. `downgrade()`
    raises `RuntimeError("Raw datasets cannot be downgraded: their placements and Polaris tables
    remain")`.
  - `migrations/schema.sql`: stamp `0015_raw_datasets`; the §10.12 blocks of `raw_realm_bindings`,
    `raw_storage_roots` and `raw_datasets` and its index lines; the two `raw_datasets` annotations
    marked `(0016)` land with that revision.
  - `tests/contract/test_raw_schema.py`: the map test now sees the three new tables; one proof per
    trigger rule (SQLSTATE 23514 with the trigger's name as `constraint_name`): each frozen column
    of `raw_datasets` (title, storage path, `placement_key`, `create_request`, …), a forbidden
    state edge (PENDING → ARCHIVED, DELETED → ACTIVE, ACTIVE → PENDING), a lifecycle fact rewritten,
    `registered_at` set outside PENDING → ACTIVE, `latest_number` + 1 outside ACTIVE and + 2, the
    etag rule (a counted change without `+1`, `+2`, an etag-only `+1` accepted, a work-column update
    with the etag unchanged accepted), deleting a non-PENDING dataset, and updating or deleting a
    binding or a root identity; one proof per CHECK (the placement suffix rule, accepting a foreign
    prefix, and each `storage_path` refusal: leading or trailing `/`, `//`, `.`, `..`, `.huron`; a
    non-`file:///` or unterminated `base_location`; the shape CHECKs; the `raw_storage_roots`
    key, URI and unique `root_id`); the partial unique indexes (a second live locator refused and
    allowed after `released_at`; two occupying rows with one `placement_key` refused, freed once
    DELETED and parked).
- Design: §10.5 `0015_raw_datasets` (DDL and "Notes on `raw_datasets`"); §10.7 Access paths;
  §10.12 (the `0015` edit, "Map conformance"); D-5, D-6, D-7, D-16, D-67, D-68, D-108, D-120,
  D-121, D-164, D-172.
- Verification: the plan-wide gate with `check_schema_map.py` at the new head and the contract and
  integration suites on Docker (background, polled); the downgrade raises and leaves `0015`.
- Dependencies: M3.1.
- Status: pending

### M4.2 Dataset aggregate and the placement check

- Intent: the Raw dataset aggregate with its lifecycle as an enum and a transition table, every
  decision a small method that returns the target state or raises the gating refusal, plus the
  value the create transaction returns for the live-locator and overlap checks. The refusals land
  here with their §7 rows because these methods are their first raisers. The property standard
  follows in M4.3.
- Delete: none.
- Create / Modify (load `oop-design`):
  - `src/huron/core/raw/datasets.py` (new): `DatasetState`, `RegistrationState`,
    `RegistrationOutcome`, `DATASET_TRANSITIONS`, `DatasetDraft` (title 1..256, description ≤ 9000,
    optional subject id; `ValueError`), `DatasetQuery`, and `RawDataset` (the §8.4.1 fields incl.
    the joined `endpoint` and `committing`; `__post_init__` holding the §8.4.1 invariants;
    `create(...)` giving PENDING, `etag` 1; `registration_state`; `occupies_placement`;
    `require_etag`, `require_active`, `require_readable`; `register`, `discard`, `release`,
    `archive`, `unarchive`, `delete` per the §8.4.1 table; `next_number`), each target checked
    against `DATASET_TRANSITIONS` in one private helper so every decision stays at complexity ≤ 4.
  - `src/huron/core/raw/locations.py`: `PlacementCheck(holder, overlaps)` with `require_free()`: a
    DELETED, unreleased holder raises `TargetReleasing`, any other holder `DatasetExists`
    (`context.dataset_id`), an overlap `StorageLocationRefused(reason="overlaps_dataset")`;
    `RawDataset` named under `TYPE_CHECKING` only.
  - `src/huron/core/raw/errors.py`: `RegistrationStateConflict` (409, `context.state`),
    `DatasetNotActive` (409, `context.state`), `CommitInProgress` (409, `retry_after = 5`),
    `DatasetDeleted` (410), `VersionLimitReached` (409), `DatasetExists` (409), `TargetReleasing`
    (409) in `ERROR_CODES`; their `design/api.html` §7 rows (live; `Retry-After` 5 for
    `COMMIT_IN_PROGRESS`, `—` otherwise; the §19.6 meanings).
  - `tests/unit/test_raw_transitions.py` (new): `DATASET_TRANSITIONS` equals §14.1's edges (the
    same edges `raw_datasets_identity` enforces); every decision method against every state, cell
    by cell as the §8.4.1 table gives it, `archive` and `delete` with and without `committing`;
    `release` answering `True` then `False`; `next_number` and its 999999 ceiling;
    `require_etag`; the §14.1 registration-view table; `occupies_placement`; one refusal per
    invariant.
  - `tests/unit/test_raw_locations.py`: `PlacementCheck.require_free` for no holder, a live holder,
    a DELETED unreleased holder and an overlap.
- Design: §8.4.1 `RawDataset`; §14.1 Dataset (transitions, gating, registration view); §8.3.1
  (`PlacementCheck`); §8.8 Errors; §19.6 ("Rows added"); §17.6 (`COMMIT_IN_PROGRESS`'s
  `retry_after`); D-6, D-46, D-47, D-78, D-107, D-167.
- Verification: the plan-wide gate; `test_domain_error_rows_document_their_retry_after` passes
  with `COMMIT_IN_PROGRESS` at 5; `datasets.py` at 100 % and every method within the complexity
  budget (radon, complexipy, pyscn).
- Dependencies: M2.5.
- Status: pending

### M4.3 Polaris property standard 2

- Intent: build the exact generic-table create request of a dataset (standard 2: `format raw`,
  `base-location`, `doc` and the 13 fixed `huron.*` keys), validated against its packaged schema and
  checked for the relations the schema cannot express, so `DatasetService.create` stores its JCS
  bytes and the BFF re-sends them byte for byte.
- Delete: none.
- Create / Modify (load `oop-design`):
  - `src/huron/core/raw/properties.py` (new): `RawTableProperties(name, base_location, doc,
    properties)` with `for_dataset(*, dataset_id, locator, placement, title, description, subject,
    public_api_url, created_at)` (values from `raw_layout`'s constants and the §15.2 rules: `doc` is
    the title, or the title, a blank line and the description; `created-at` in whole seconds with
    `Z`; the two URLs on `public_api_url`), `request()` and `encode()` (JCS validated against
    `raw-table-properties-v2.json`); a broken relation (dataset root ≠ base location ≠
    `placement.base_location`, a name other than the locator's, a URL naming another id or not
    starting with `public_api_url`, a `public_api_url` with a trailing `/`) is a `ValueError`.
  - `tests/unit/test_raw_properties.py` (new): `test_standard_2_create_request_golden_bytes` (the
    §15.2 example as exact JCS bytes and as `request()`); `doc` with and without a description and
    with a 256-character title and a 9000-character description; `created-at` truncation; a
    CATALOG subject rendered `catalog/<name>`; each relation refusal; no `polaris.` key and none of
    the omitted members (actor, root key, `huron.layer`, `huron.raw.service`).
- Design: §15.1 Raw storage inside the Polaris namespace tree; §15.2 The create request; §8.5
  Commands and documents (`RawTableProperties`); §15.6 Versioning the standard; D-50, D-51, D-54,
  D-107, D-109.
- Verification: the plan-wide gate; `properties.py` at 100 %.
- Dependencies: M2.2, M2.4, M3.4.
- Status: pending

### M4.4 Dataset ports and in-memory stores

- Intent: declare the dataset store ports with exactly the slice-3 methods (D-139) and the root
  methods of `MaintenanceStore`, and implement them in memory over the shared Raw state of M3.5, so
  `DatasetService` and its route tests run without a database and the shared scenarios fix the
  behaviour the PostgreSQL adapter must match (M4.5).
- Delete: none.
- Create / Modify (load `oop-design`):
  - `src/huron/core/raw/ports.py`: `DatasetRows` (`lock_dataset(dataset_id, *, share=False)`,
    whose COMMITTING read arrives with `0016` and which reports `committing=False` until then;
    `transition_dataset(dataset, target, *, actor, at)` serving PENDING → ACTIVE: `registered_at`,
    `state_changed_by/at`, `etag + 1`, guarded by the expected etag; `retention`, the DELETED facts
    and the park lease join with delete in slice 5; `bump_dataset` with slice 4), `DatasetStore`
    (`transaction`, `dataset`, `dataset_at`, `datasets`, `realm_endpoint`; `record_parked` in slice
    5), `DatasetTransaction(RawTransaction, DatasetRows, Protocol)` (`bind_realm`,
    `reserve_placement`, `insert_dataset`, `discard_dataset`; `release_dataset` and
    `end_open_sessions` in slice 5) and `MaintenanceStore` (`referenced_roots`, `storage_roots`,
    `record_root`; the claim and duty methods join per slice), with the §8.7 comments.
  - `src/huron/core/metastore/raw_datasets.py` (new): `InMemoryDatasetStore` and its transaction
    and `InMemoryMaintenanceStore` (root methods), over `raw_memory`'s shared state:
    `reserve_placement` returns a `PlacementCheck` (the live holder of the locator, and the
    occupying placements on the same root whose `placement_key` equals, contains or lies inside the
    new one); `insert_dataset` refuses a live-locator or occupied-placement collision as the
    PostgreSQL indexes map them (`DatasetExists`/`TargetReleasing`, `overlaps_dataset`);
    `transition_dataset` raises `PreconditionFailed` on a stale etag; `bind_realm` keeps the first
    endpoint; `datasets(owner, query)` pages `(created_at, id)` newest first with the state
    filter; `referenced_roots` names the root of every unpurged dataset; `record_root` keeps the
    first identity of a key. `metastore/__init__.py` exports both stores.
  - `tests/raw_store_contract.py`: dataset scenarios: insert and read by id and by locator; the live
    locator's holder; placement overlap and nesting (equal, parent, child, a case alias and an
    NFC/NFD alias on one root; the same path on another root is free); realm pinning
    (`bind_realm` answers the first endpoint, `realm_endpoint` is `None` while unbound);
    `lock_dataset` (joined endpoint, `committing` false, unknown id); PENDING → ACTIVE and a stale
    etag; `discard_dataset`; the owner's PENDING list and its keyset; `record_root` idempotence,
    `storage_roots` and `referenced_roots`.
  - `tests/unit/test_raw_stores_memory.py`: runs the new scenarios.
- Design: §8.7.1 Shared transaction protocols (`DatasetRows`); §8.7.2 Family ports
  (`DatasetStore`, `DatasetTransaction`); §8.7.3 Maintenance port (root methods); §10.3 (the slice
  table); §10.7 (the overlap scan's semantics); D-13, D-139, D-164, D-172.
- Verification: the plan-wide gate; the new module at 100 % in the unit run; slice-3 clone budget
  (at most four new clones across M4.x), running total in Execution notes.
- Dependencies: M3.5, M4.2.
- Status: pending

### M4.5 PostgreSQL dataset store

- Intent: the PostgreSQL dataset store and the root methods of the PostgreSQL maintenance store:
  the `raw-placement:` lock with the `placement_key` overlap scan, the realm-binding statement
  shared with the schema store, and constraint-name mapping; contract-tested on `postgres:16`
  against the shared scenarios and the concurrent alias race.
- Delete: none.
- Create / Modify (load `postgresql-table-design`):
  - `src/huron/core/metastore/rows.py`: the `DatasetRows` mixin (`lock_dataset` as `SELECT … FOR
    UPDATE | FOR SHARE OF d` joining `raw_realm_bindings.endpoint`; `transition_dataset` as one
    `UPDATE … WHERE id = $1 AND etag = $2 RETURNING`, zero rows raising `PreconditionFailed`), the
    `bind_realm` mixin (`INSERT … ON CONFLICT DO NOTHING`, then `SELECT`; the schema transaction
    reuses it in M4.9) and the row mapper `raw_dataset(row)`, which builds `DatasetLocator` and
    `DatasetPlacement` through `huron.core.raw.locations` (§6.5 rule 5).
  - `src/huron/core/metastore/raw_datasets.py`: `PostgresDatasetStore` (reads; the owner's list in
    `raw_datasets_pending_owner` order; `realm_endpoint`) and its transaction (`reserve_placement`:
    `pg_advisory_xact_lock(hashtextextended('raw-placement:' || $root, 0))`, the live holder, then
    the §10.7 scan with `starts_with` on `placement_key`; `insert_dataset` writing
    `placement.placement_key`, mapping `raw_datasets_live_locator` to `DatasetExists` or
    `TargetReleasing` with the holder read back and `raw_datasets_placement` to `overlaps_dataset`;
    `discard_dataset`, whose trigger refusal propagates), and `PostgresMaintenanceStore` with the
    root methods (`SELECT DISTINCT storage_root … WHERE purged_at IS NULL`; all of
    `raw_storage_roots`; `INSERT … ON CONFLICT (key) DO NOTHING`, then `SELECT`).
    `metastore/__init__.py` exports both.
  - `tests/contract/test_raw_stores_postgres.py`: the dataset scenarios on PostgreSQL and
    `test_concurrent_alias_creates_refuse_the_second`: from two pools, two creates whose paths
    differ only in case, and two that differ only in NFC/NFD, race through `reserve_placement` and
    `insert_dataset`; one commits and the other answers `overlaps_dataset`; a create arriving after
    the first committed but before its directory exists (the commit-to-ensure window) is refused
    the same way.
- Design: §10.7 Access paths (the overlap scan, the index map); §8.7.5 Adapters (the `rows.py`
  mixins); §22.3 Contract tests on Docker; §22.4 (OD-12 O-8); D-13, D-150, D-164.
- Verification: the plan-wide gate with contract and integration on Docker;
  `uv run pytest -m "unit or contract" --cov=src/huron --cov-report=term-missing
  --cov-fail-under=0` shows `raw_datasets.py` and `rows.py` at 100 %; OD-12 O-8 reset of
  `fail_under` with counts in Execution notes; slice-3 clone budget recorded.
- Dependencies: M3.6, M4.1, M4.4.
- Status: pending

### M4.6 DatasetService: create, reads and registration reports

- Intent: the slice-3 half of `DatasetService`: create a PENDING dataset through the ten guards of
  §13.1 (replay checked before any storage access, the realm pinned by the create transaction, the
  root claimed before and ensured after it), read one by id, by target or in the creator's own list,
  and apply the `REGISTERED` and `CONFLICT` reports, the latter removing only empty directories
  (D-170). Archive, unarchive, delete and the `RELEASED` report land in slice 5.
- Delete: none.
- Create / Modify (load `oop-design`):
  - `src/huron/core/raw/_impl/datasets.py` (new): `DatasetService(datasets, schemas, archive,
    sweeper, placement, *, public_api_url, clock)` (`limits` joins with delete in slice 5) with:
    - `create(grant, draft, *, idempotency_key)`: `dataset_target()` then `require(CREATE)`; the
      pinned endpoint compared (`RealmBindingConflict`); the replay check in a transaction left by a
      private exception so nothing commits, a receipt answering the current dataset; `derive`; the
      subject (given or `PLATFORM_METADATA_SUBJECT_ID`; unknown or not `require_bindable` →
      `SchemaSubjectNotUsable`); `claim_dataset_root` on a worker thread (`asyncify`); the request
      from `RawTableProperties.for_dataset(...).encode()` and the row from `RawDataset.create`; one
      transaction (`claim` answering a receipt, `bind_realm` compared again, `reserve_placement` with
      `require_free()`, `insert_dataset`, the `raw.dataset.created` audit row with the §14.6
      payload, `remember(Replay("raw_dataset", id))`); after it, `ensure_dataset_root`, whose
      failure is logged, not raised;
    - `get`, `by_target` (DELETED-but-unreleased included), `mine` (target-less, the actor's own);
    - `report(grant, dataset_id, outcome)` for `REGISTERED` (under `lock_dataset`, `register()`,
      `transition_dataset`, audit `raw.dataset.registered`; unchanged when it answers `None`) and
      `CONFLICT` (`discard()` on the read row, then `remove_empty_root`; `False` aborts with
      `RegistrationStateConflict`, logged; otherwise lock, decide again, `discard_dataset` and audit
      `raw.dataset.discarded`; answers `None`), each needing `CREATE` after `require_target`;
      `RELEASED` is a caller bug (`ValueError`) until locator release lands.
    - Storage errors map as §8.8 and §9.8.1 give them: `StorageRootUnavailableError` and
      `PermissionError` → `RawStorageUnavailable` (root and reason logged, never sent),
      `DatasetRootOccupiedError` → `StorageLocationOccupied(context={"base_location": …})`,
      `CrossDeviceCommitError` → `StorageLocationRefused(reason="cross_device")`.
  - `src/huron/core/raw/retry.py`: `raw_claim(operation, principal, key, *parts)` over
    `request_sha256` with §8.9's `raw_dataset` parts (realm, catalog, the namespace joined by
    `\x1f`, name, title, description, the subject id or the PLATFORM id when none was given);
    `session_claim` stays until M5.3. `src/huron/core/foundation/retry.py`: `Replay.kind` gains
    `raw_dataset`.
  - `src/huron/core/raw/errors.py`: `StorageLocationOccupied` (409, `context.base_location`) and
    `RawStorageUnavailable` (503, `retry_after = 60`, no context) in `ERROR_CODES`; their
    `design/api.html` §7 rows (Retry-After 60 and `—`). `core/raw/__init__.py` exports
    `DatasetService`.
  - `tests/unit/test_raw_services.py` (in-memory dataset and schema stores over one shared state,
    `PosixStorageRoots` over two temporary roots): the guard order (401 for a catalog target before
    403 for a missing `create`; refusals before any storage call); `test_realm_binding_conflict_409`
    and `test_unbound_realm_404_except_create` (create pins the realm; get and by-target in an
    unbound realm answer 404); a replay answering the first dataset with its root made UNAVAILABLE
    (storage never touched); the `derive` refusals passing through; the subject cases (none, unknown,
    another catalog's, no ACTIVE version); UNAVAILABLE root → `RawStorageUnavailable`, occupied
    root → 409 with `base_location`, stubbed cross-device → `cross_device`; `DatasetExists` with the
    holder id and `overlaps_dataset`; the stored row (PENDING, etag 1, `create_request` equal to the
    properties' bytes, audit, receipt); a failing ensure logged with the row kept; the reads and the
    owner's list; `REGISTERED` (PENDING → ACTIVE with `registered_at` and etag 2; ACTIVE
    unchanged); `CONFLICT` (empty root removed then row discarded; a `versions/` holding an entry
    answers 409 and keeps the row; ACTIVE answers 409); a foreign target answering 404; §18.2 A16
    `test_conflict_on_unavailable_root_is_503` (`503 RAW_STORAGE_UNAVAILABLE`, the PENDING row
    unchanged) and A18 `test_replay_of_a_discarded_create_is_404` (a same-key create retried after
    a `CONFLICT` discard finds a receipt naming a deleted row and answers `404 NOT_FOUND`).
- Design: §8.6.1 `DatasetService`; §13.1 Create a dataset and register its Polaris table (guards,
  crash windows); §13.2 Get the dataset for a new version; §15.4 Registration timing and the BFF
  handshake; §8.8 Errors; §8.9 (Idempotency); §14.6 Audit rows; D-6, D-7, D-9, D-18, D-52, D-89,
  D-105, D-107, D-169, D-170.
- Verification: the plan-wide gate; `_impl/datasets.py`, `retry.py` and the touched modules at
  100 %; `create` stays a straight-line composition of guard methods (complexity ≤ 3, §8.10); the
  error-contract tests pass with both rows (`RAW_STORAGE_UNAVAILABLE` documenting 60).
- Dependencies: M2.8, M4.3, M4.4.
- Status: pending

### M4.7 Storage roots in the runtime, readiness and Catalog's store

- Intent: compose slices 1–3 into the API lifespan. Open the configured storage roots with their
  sentinels and recorded identities, record every new identity, build the placement policy and
  compose `DatasetService` into `RawRuntime`, so a configured deployment can create datasets once
  M4.8 mounts the routes. Rename Catalog's store and its readiness check, and gate `/readyz` on
  every root an unpurged dataset references. The public API URL has been required whenever the
  bridge secret is set since M2.6. The Playwright harness (`tests/raw_web_support.py`, until
  M5.1) starts this lifespan, so this task runs the web gate and Playwright.
- Delete: none.
- Create / Modify:
  - `src/huron/applications/api/app.py`:
    - a lifespan step `_open_storage_roots` runs after the stores exist and before `RawRuntime` is
      built. It reads `MaintenanceStore.referenced_roots()` and `storage_roots()`. Its `mounts`,
      `require_mount` and `reserve_bytes` come from `settings.raw`. Its `sentinels` are
      `root_sentinel(...)` candidates, each with a fresh `uuid4()` `root_id` and the clock's
      instant. It calls `PosixStorageRoots.open(...)` on a worker thread. It then calls
      `MaintenanceStore.record_root` for every key in `identities()` that `recorded` lacks;
    - `_build_runtime` builds `PlacementPolicy` over the configured `StorageRoot(key, uri)` values,
      fills `RawPorts` from `ApiStores` and the opened roots, and builds `RawRuntime` with the
      policy, `public_api_url` and the clock. The Catalog store is published as `catalog_store`;
    - readiness: the `raw_store` check becomes `data_root` (`_data_root_probe`/`_data_root_failure`
      over `runtime.catalog_store`). After it come `database` and then one `raw_root:<key>` check
      per key of `referenced_roots()`. A root check probes `runtime.raw_roots.root_available(key)`
      on a worker thread within `READINESS_TIMEOUT_SECONDS`. A referenced key that the settings no
      longer list fails. The root checks run only after the database check passed, or against the
      injected maintenance store when no pool is wired.
  - `src/huron/core/raw/runtime.py`: new `RawPorts` (§8.6.8) with the fields slices 1–3 provide:
    `datasets`, `schemas`, `work` (the maintenance store, root methods so far), and `archive` and
    `sweeper` (the one `PosixStorageRoots`). `RawRuntime(ports, *, placement, public_api_url, clock,
    storage, persistence)`: the §8.6.8 constructor, with the old engine's `storage` and
    `persistence` as keywords until M5.3 (the "Composition root" rule). It builds
    `SchemaRegistry(ports.schemas)` and `DatasetService` (M4.6) over `ports.datasets`,
    `ports.schemas`, `ports.archive`, `ports.sweeper`, the policy, `public_api_url` and the clock;
    `core/raw/__init__.py` exports `RawPorts`.
  - `src/huron/core/rawstore/roots.py`: `PosixStorageRoots.confirm_recorded(key, identity)`. The
    wiring passes the identity `record_root` returned. A `root_id` or `uri` that differs from the
    one `open` read marks the key UNAVAILABLE (`sentinel_mismatch`, logged), and later probes
    compare against it (§6.6 step 4).
  - `src/huron/applications/api/runtime.py`: `ApiRuntime.raw_store` → `catalog_store`. New
    `raw_roots`, typed by the capabilities Protocol below. `ApiStores` (the adapter bundle that
    tests inject), which has carried the schema store since M3.7, also carries the dataset store
    and the maintenance store.
  - `src/huron/applications/api/capabilities.py`: conformance Protocols for the PostgreSQL and
    in-memory dataset and maintenance stores (`DatasetStore`, the `MaintenanceStore` root methods)
    and for `PosixStorageRoots` as `VersionArchive` plus `StorageSweeper`. The lifespan asserts
    them (§6.6 step 8).
  - `src/huron/applications/api/dependencies.py` and `src/huron/applications/api/raw_web.py`
    (live until M5.1): `runtime.raw_store` → `runtime.catalog_store`.
  - `tests/unit/support.py`: `memory_stores()` also builds the in-memory dataset and maintenance
    stores. `tests/unit/test_authorization_credentials.py` and `tests/unit/test_core_workflows.py`:
    their direct `ApiRuntime(...)` and `RawRuntime(...)` constructions follow the new signatures
    (`catalog_store`, `raw_roots`, `RawPorts`).
  - `scripts/polaris_dev.py` `raw_environment()`: a `setdefault` for `HURON_RAW__STORAGE_ROOTS`
    (`local-storage` and `local-nasa-storage`, §20.8) beside the `HURON_RAW__PUBLIC_API_URL` that
    M2.6 set. The web process keeps receiving only its three `HURON_RAW_*` variables.
  - `scripts/polaris-dev.sh`: create `.local/polaris/storage` (mode 0755) before the Raw API
    starts; the status line becomes "Raw storage roots: .local/polaris/storage,
    .local/polaris/nasa-storage".
  - `design/api.html` §7: the `DEPENDENCY_UNAVAILABLE` meaning takes its §19.6 text.
  - Tests:
    - `tests/unit/test_api_app.py`: the readiness tests are renamed to `data_root`, plus
      `test_readyz_checks_every_referenced_storage_root`,
      `test_readyz_fails_on_an_unavailable_referenced_root`,
      `test_readyz_fails_on_a_referenced_root_no_longer_configured`,
      `test_readyz_ignores_an_unreferenced_root`, `test_readyz_root_probe_times_out` and
      `test_readyz_skips_root_checks_when_the_database_fails`;
    - lifespan wiring: `test_lifespan_opens_storage_roots_and_records_new_identities` (the
      sentinel is published, `record_root` runs once per new key, a second start adopts without
      recording) and `test_lifespan_marks_a_root_unavailable_when_the_recorded_identity_differs`;
    - `tests/unit/test_execution_model.py`: the readiness off-loop test is renamed to the
      `data_root` stat, plus a root-probe off-loop case;
    - `tests/unit/test_rawstore_roots.py`: the `confirm_recorded` cases.
- Design: §6.6 steps 1–5 and 8; §9.8.6 (wiring); §9.2 (the sentinel table); §19.7 (`/readyz`);
  §19.6 (rows kept, `DEPENDENCY_UNAVAILABLE`); §20.8; D-17, D-51, D-94, D-101, D-119, D-144,
  D-172.
- Verification: the plan-wide gate plus the web gate (`npm run check`, `npm test`,
  `npm run lint`, `npm run build`) and `npm run test:e2e`, because the Playwright harness builds
  its stores from `memory_stores()` and starts this lifespan;
  `bash -n scripts/polaris-dev.sh`; `uv run python -m py_compile scripts/polaris_dev.py`.
  Acceptance:
  - `rg -n "runtime\.raw_store|\"raw_store\"" src tests` prints nothing;
  - `/readyz` answers `503 DEPENDENCY_UNAVAILABLE` with `context.checks["raw_root:<key>"]` for a
    referenced root whose sentinel was removed, and `200` once only unreferenced roots fail;
  - every touched file is at 100 %.
- Dependencies: M2.6, M3.9, M4.5, M4.6.
- Status: pending

### M4.8 Dataset routes 1–6

- Intent: mount dataset creation, the creator's PENDING list, reads by id and by target, and the
  registration read and `REGISTERED`/`CONFLICT` report under `/api/v1/raw/datasets`, over the
  `DatasetService` that M4.7 wired. Bodies go through `raw_body` only. The OpenAPI component
  names avoid Catalog's.
- Delete: none.
- Create / Modify:
  - New `src/huron/applications/api/routes/v1/schema/raw_datasets.py`:
    - models `CreateRawDataset`, `RegistrationReport`, `RegistrationView`, `DatasetSchema`,
      `RawDatasetView` (`schema_binding` aliased `schema`) and `RegistrationDiscarded` (§19.4).
      `RegistrationReport.outcome` accepts `REGISTERED` and `CONFLICT`; `RELEASED` joins with
      route 6's `RELEASED` outcome in M8.9 and answers `422 REQUEST_INVALID` until then;
    - builders `dataset_view(dataset)` and `registration_view(dataset)`. `DatasetSchema` comes
      from the stored create request's `huron.raw.schema.*` properties, so a read touches no other
      row. `create_request` is decoded from its JCS bytes, and `create_request_sha256` is their
      SHA-256. The dataset view carries `create_request` only while PENDING.
  - New `src/huron/applications/api/routes/v1/endpoints/raw_datasets.py`:
    `router = APIRouter(prefix="/datasets", tags=["raw-datasets"])`, with one `Annotated` body
    alias per model through `raw_body(...)`. Handlers, with names unique in the tier:
    - `create_raw_dataset`: POST, `IdempotencyHeader`, `201` with `ETag`, and
      `openapi_extra=json_request_body(CreateRawDataset)`;
    - `list_pending_raw_datasets`: `state: Literal["PENDING"] = "PENDING"`, `limit`, `after`,
      returning `Page[RawDatasetView]` through `created_cursor_key`;
    - `get_raw_dataset_by_target` (`/by-target`, declared before `/{dataset_id}`);
    - `get_raw_dataset`;
    - `get_raw_dataset_registration`;
    - `report_raw_dataset_registration`: `RawDatasetView` with `ETag`, or
      `RegistrationDiscarded`.

    Each handler declares only its §19.3 route-specific statuses with `problem_response`, never
    the `RAW_ERRORS` set.
  - `src/huron/applications/api/routes/v1/__init__.py`: `raw_routes` includes `raw_datasets.router`.
  - `src/huron/applications/api/routes/v1/pagination.py`: `created_cursor_key()` for route 2, which
    M3.9 left to its first route.
  - `src/huron/applications/api/problems.py`: `json_request_body(model)` beside `problem_response`,
    referencing `#/components/schemas/<Model>`; `_HuronFastAPI.openapi()` in `app.py` registers
    those schemas, `$defs` hoisted, as it registers `Problem` (§12.10). Route 1 is its first user.
  - `design/api.html` §3: the rows for routes 1–6 (§19.7).
  - Tests:
    - new `tests/unit/test_raw_datasets_api.py` (TestClient, `tests/raw_client.py`, in-memory
      stores, two temporary roots);
    - `tests/unit/test_api_router_composition.py`: the tag set gains `raw-datasets` and the test
      becomes `test_the_openapi_document_carries_eighteen_resource_grained_tags`; the Raw
      no-redeclaration twin covers `raw_datasets`; `test_raw_routes_declare_no_body_parameter`
      now covers routes 1 and 6;
    - `tests/unit/test_execution_model.py`: the six handlers in `EXPECTED_COROUTINE_FUNCTION`;
    - `tests/unit/test_raw_authority.py`: `test_unauthenticated_oversized_body_refused_before_read`
      gains rows for route 1 (64 KiB) and route 6 (1 KiB).
- Design: §19.3 routes 1–6; §19.4; §19.5 (JSON routes, pagination, idempotency, preconditions
  and entity tags); §7.5; §12.2 (body limits); §13.1; D-72, D-127, D-128, D-129.
- Verification: the plan-wide gate. Acceptance (named cases in `test_raw_datasets_api.py`):
  - `test_create_answers_201_with_etag_and_a_pending_registration` (`create_request_sha256` is the
    SHA-256 of the returned request's JCS bytes);
  - `test_create_replay_answers_201_with_the_current_view` (also after REGISTERED) and the key
    reused for another body, which answers `409 IDEMPOTENCY_KEY_REUSED`;
  - `test_create_at_a_live_locator_is_409_dataset_exists` (`context.dataset_id`);
  - `test_create_outside_the_storage_roots_is_422`, plus `TARGET_NAME_UNSUPPORTED`,
    `SCHEMA_SUBJECT_NOT_USABLE` and `STORAGE_LOCATION_OCCUPIED`;
  - `RAW_STORAGE_UNAVAILABLE` with `Retry-After: 60`;
  - a catalog-level target on route 1 answers `401`;
  - `test_pending_list_is_the_actors_own_newest_first` with paging and `400 INVALID_CURSOR`;
  - `test_by_target_is_not_parsed_as_a_dataset_id`;
  - another locator's id answers `404`, and a different endpoint answers
    `409 REALM_BINDING_CONFLICT`;
  - `test_registered_report_activates_and_repeats_unchanged` (`etag` + 1, `ETag` header);
  - `test_conflict_report_discards_then_404`;
  - `test_conflict_with_content_in_versions_is_409`;
  - the route twins of M4.6's A16 and A18 cases:
    `test_conflict_report_on_an_unavailable_root_is_503` (route 6, `503 RAW_STORAGE_UNAVAILABLE`
    with `Retry-After: 60`, the dataset still PENDING) and
    `test_create_replay_after_a_discard_is_404` (route 1 with the discarded create's
    `Idempotency-Key`);
  - a report without `create` answers `403`.

  Also: `test_hierarchy_keeps_named_patch_and_response_schemas` still passes; `rg -n "class
  (DatasetView|CreateDataset)\b" src/huron/applications/api/routes/v1/schema/raw_*.py` prints
  nothing.
- Dependencies: M4.7.
- Status: pending

### M4.9 Registry catalog half

- Intent: catalog-scoped metadata schemas in core and both stores. Subject creation pins an
  unbound realm (OD-12 O-6). Registration deduplicates by content, deprecation is idempotent,
  catalog subjects are readable by any target of their realm and catalog, and PLATFORM writes
  answer `403`. Routes follow in M4.10.
- Delete: none.
- Create / Modify:
  - `src/huron/core/raw/ports.py`: `SchemaTransaction.bind_realm(realm, endpoint) -> str`. The
    other `SchemaTransaction` write methods have been declared since M3.5.
  - `src/huron/core/metastore/raw_schemas.py`:
    - the PostgreSQL schema transaction takes `bind_realm` from the `rows.py` realm-binding mixin
      of M4.5, so the statement exists once;
    - the in-memory schema transaction shares the in-memory dataset store's binding map, so a
      realm pinned by a subject is the realm dataset creation sees, and the reverse.

    `SchemaSubjectExists` (409, `context.subject_id`), its §7 row and both stores' refusal of a
    taken name exist since M3.5 and M3.6.
  - `src/huron/core/raw/_impl/schemas.py` (§8.6.6):
    - `SchemaRegistry(schemas, datasets, *, clock)` gains the dataset store for `realm_endpoint`;
    - new `create_subject`: the grant's catalog (`404` without a target), the endpoint
      comparison, `require(SCHEMA)`, a replay check, then one transaction with `claim`,
      `bind_realm`, the second comparison, `insert_subject`, `raw.schema.subject_created` and
      `remember`;
    - new `register`: `require_publishable`, then `SchemaDocument.parse`, then the dedup
      transaction. It returns `(version, created)`;
    - new `deprecate`;
    - `subjects`, `subject`, `versions`, `version` and `version_by_id` apply the CATALOG read rule
      with the realm's pinned endpoint, and `subjects` passes the grant's `CatalogRef` to
      `SchemaStore.subjects`.
  - `src/huron/core/foundation/retry.py`: `Replay.kind` gains `schema_subject` and
    `schema_version`, fingerprinted by `raw_claim` (§8.9).
  - `src/huron/core/raw/runtime.py`: the registry is built with `ports.datasets` (the `RawPorts`
    field M4.7 composes) and the clock.
  - Tests:
    - `tests/raw_store_contract.py`: `test_subject_creation_pins_an_unbound_realm` (the first
      `bind_realm` inserts the binding, and a second endpoint gets the pinned one back), run in
      `tests/unit/test_raw_stores_memory.py` and `tests/contract/test_raw_stores_postgres.py`;
    - `tests/unit/test_raw_services.py`: the registry write and read cases below.
- Design: §8.6.6; §16.3; §16.6 (the publish rules at register); §16.9; §16.10 (fingerprints and
  audit kinds); §24.1; D-110, D-150, D-151; OD-12 O-6.
- Verification: the plan-wide gate; the contract suite on Docker. Apply the OD-12 O-8 floor reset
  if the PostgreSQL schema store gains statements: 100 % of them under
  `uv run pytest -m "unit or contract" --cov=src/huron --cov-report=term-missing
  --cov-fail-under=0`, with the counts in Execution notes. This task draws on slice 3's clone
  budget. Acceptance, in `test_raw_services.py`:
  - `test_unbound_realm_404_except_create` (M4.6's case in this module) gains the registry half:
    `SchemaRegistry.create_subject` pins the realm;
  - `test_subject_creation_with_another_endpoint_is_409`;
  - a grant without a target answers `404`, and one without `schema` answers `403`;
  - a replay answers the same subject, and key reuse answers `409`;
  - `test_register_creates_then_answers_identical_content_unchanged` (`created` False, the same
    id, gap-free numbers);
  - `test_platform_register_and_deprecate_are_403`;
  - `test_deprecate_is_idempotent`;
  - `test_catalog_subject_hidden_from_other_catalogs` (`404`);
  - the audit rows of §14.6.
- Dependencies: M4.5, M4.7.
- Status: pending

### M4.10 Registry write routes

- Intent: mount subject creation, version registration and deprecation (routes 27, 30 and 33),
  and prove the catalog-target halves of the read routes 26 and 28 (and the version reads that
  share the read rule), over the registry of M4.9.
- Delete: none.
- Create / Modify:
  - `src/huron/applications/api/routes/v1/schema/raw_schemas.py`: `CreateSchemaSubject` (§16.10).
  - `src/huron/applications/api/routes/v1/endpoints/raw_schemas.py`:
    - `create_schema_subject` (route 27): `IdempotencyHeader`, the body through `raw_body`, and a
      `201 SchemaSubjectView`;
    - `register_schema_version` (route 30): the body is
      `document: Annotated[dict[str, JsonValue], Depends(raw_body(dict[str, JsonValue]))]` with
      `IdempotencyHeader`. It answers `201` for a new version and `200` for identical content or a
      replay (the returned status follows the registry's `created`);
    - `deprecate_schema_version` (route 33): an empty body, `200`, idempotent.

    Routes 27 and 30 document their bodies through `openapi_extra=json_request_body(...)`. Each
    handler declares only its route-specific statuses (§19.3: `409` and `422`; `403` for PLATFORM
    on routes 30 and 33).
  - `design/api.html` §3: rows for routes 27, 30 and 33, and the catalog-target note on route 26.
  - Tests:
    - `tests/unit/test_raw_schemas_api.py` (extended);
    - `tests/unit/test_api_router_composition.py`: `test_raw_routes_declare_no_body_parameter`
      covers routes 27 and 30;
    - `tests/unit/test_execution_model.py`: the three handlers;
    - `tests/unit/test_raw_authority.py`: oversized-body rows for routes 27 and 30 (1 MiB, both
      for a declared `Content-Length` and for a chunked body).
- Design: §16.10; §19.3 routes 26–33; §19.5 (idempotency table); §12.2 (1 MiB); D-58, D-150.
- Verification: the plan-wide gate. Acceptance, in `test_raw_schemas_api.py`:
  - `test_create_subject_201_and_replay` (also pinning an unbound realm through the route);
  - `test_create_subject_duplicate_name_409_schema_subject_exists` (`context.subject_id`);
  - `test_register_201_then_identical_200`, `test_register_replay_200` and
    `test_register_invalid_schema_422` (`context.errors` with pointers);
  - `test_platform_writes_are_403`;
  - `test_deprecate_twice_answers_200`;
  - `test_catalog_target_lists_platform_and_its_catalog_subjects`;
  - `test_other_catalog_subject_is_404` (routes 28, 29, 31, 32);
  - the oversized bodies answer `413 REQUEST_BODY_TOO_LARGE` with `context.limit`, and without a
    credential they answer `401` before any body byte is read.
- Dependencies: M4.8, M4.9.
- Status: pending

## Milestone 5 — Legacy Raw engine removal (opening of slice 4)

Goal: remove `/api/raw-web`, the shadow hierarchy, the v1 Raw routes and the old ingest engine, with
everything they leave without callers, before any task re-creates `raw/ingest.py`,
`raw/_impl/ingest.py`, `raw/_impl/ingestion.py` or `metastore/ingest.py` (D-137). The seven steps
follow the measured coverage-safe order (deviation 2).

### M5.1 Retire /api/raw-web and the shadow hierarchy; first e2e harness

- Intent: remove the second Raw HTTP tree, its shadow-hierarchy provisioning and its persistence,
  and point Playwright at a first `tests/raw_e2e_support.py` built from slices 1–3 (registry,
  datasets, storage roots). It is the first of the seven legacy-removal tasks (M5.1–M5.7). The
  BFF keeps calling `/api/raw-web` (now `404`) until M9.3, and no browser Raw upload path exists
  until M10.8.
- Delete (the orchestrator runs `git rm` before the pass):
  - `src/huron/applications/api/routes/raw_web.py`;
  - `src/huron/applications/api/raw_web.py`;
  - `src/huron/core/raw/web.py`;
  - `src/huron/core/raw/web_ports.py`;
  - `src/huron/core/metastore/raw_web.py`;
  - `src/huron/core/catalog/external.py`;
  - `tests/unit/test_raw_web.py`;
  - `tests/raw_web_client.py`;
  - `tests/raw_web_support.py`;
  - `tests/integration/test_raw_web_postgres.py`;
  - `web/e2e/ingestion.test.ts`.

  The implementer reads the deleted tests at the base commit with `git show <base>:<path>`.
- Create / Modify:
  - `src/huron/applications/api/app.py`: the `/api/raw-web` include, the `PostgresRawWebStore`
    import and the `raw_web=` wiring go.
  - `src/huron/applications/api/runtime.py`: `ApiStores.raw_web`, `ApiRuntime.raw_web` and the
    `RawWebPersistence` import go.
  - `src/huron/applications/api/capabilities.py`: `RawWebPersistence` and its imports go.
  - `src/huron/core/security/raw_delegation.py`: `RawDelegation.require`, `require_scope` and
    `verified_chunks` go, as do `DelegatedBindings`, `raw_dataset_bindings` and the imports only
    they used.
  - New `tests/raw_e2e_support.py`: `raw_e2e_app()` returns `create_app` with:
    - `memory_stores()` (in-memory registry, dataset and maintenance stores);
    - `ApiSettings(raw=RawSettings(...))` with two roots: `e2e-storage` at
      `HURON_E2E_STORAGE_ROOT` (the mock's `huron-local` catalog) and `e2e-tmp` at
      `/tmp/huron-browser-test`, both created if absent (Huron never creates a root path);
    - `public_api_url="http://127.0.0.1:8099"`, the bridge secret from `HURON_RAW_BRIDGE_SECRET`,
      and Catalog's data root from `HURON_E2E_DATA_ROOT`.
  - `web/playwright.config.ts`: the first web server runs
    `tests.raw_e2e_support:raw_e2e_app --factory` with `HURON_E2E_STORAGE_ROOT: storageRoot`,
    `HURON_E2E_DATA_ROOT` and the secret.
  - `web/e2e/organizations.test.ts`: delete the test "Raw uploads with identical catalog paths
    remain separate across organization realms" and its only helper, `publishRaw`.
  - Tests:
    - `tests/unit/test_raw_delegation.py` gains the delegation cases of `test_raw_web.py` that its
      M3.2 cases lack: signature, issuer and audience, the subject rule, method, path-and-query
      and bound-header binding, `verify_body`;
    - `tests/unit/test_api_settings.py` gains `test_bridge_secret_shorter_than_32_bytes_is_refused`;
    - `tests/unit/test_api_router_composition.py` drops the `raw-web` tag, and the tag-set test
      becomes `test_the_openapi_document_carries_seventeen_resource_grained_tags`;
    - `tests/unit/test_execution_model.py` drops the eleven raw-web handlers (`create_upload` …
      `revision`).
- Design: §21.1 rules 1–2; §21.2 rows 2b, 11 (code) and 13 (delegation); §22.6 (harness); §12.3;
  D-5, D-123, D-137, D-141, D-144.
- Verification:
  - the plan-wide gate, the web gate and `npm run test:e2e`;
  - the OD-11 floor reset, with before and after counts in Execution notes;
  - `src/huron/core/security/raw_delegation.py` and `src/huron/applications/api/settings.py` stay
    at 100 % (measured at HEAD: raw-web's suites alone covered 32 delegation lines and the
    short-secret line);
  - `rg -n "raw_web|raw-web|RawWebOperations|ExternalCatalog|PROVISIONER_SUBJECT|DelegatedBindings"
    src tests web/e2e web/playwright.config.ts` prints only the revision name
    `0012_raw_web_catalogs` in contract suites that migrate to it, and
    `tests/unit/test_foundation_retry.py`'s literal fixture string. The `web/src` operand waits
    for M9.3;
  - `git status` shows exactly the eleven deletions above.
- Dependencies: M4.8, M4.10.
- Status: pending

### M5.2 Retire the v1 revision read path

- Intent: remove the three `GET /api/v1/revisions/…` routes, their guard, their dependency and
  the two read services. The ingest commit route still answers `RevisionView` until M5.3, so that
  model moves into the module that dies with the route. Measured at HEAD: deleting the revision
  read suites leaves no surviving line uncovered.
- Delete (the orchestrator runs `git rm` before the pass):
  - `src/huron/applications/api/routes/v1/endpoints/revisions.py`;
  - `src/huron/applications/api/routes/v1/schema/revisions.py`;
  - `src/huron/core/raw/_impl/revisions.py`;
  - `src/huron/core/raw/_impl/reader.py`;
  - `tests/unit/test_api_revisions.py`;
  - `tests/unit/test_api_raw_revisions.py`.
- Create / Modify:
  - `src/huron/applications/api/authorization/guards.py`: `RevisionRead`, `revision_raw_reader`
    and the `Revisions` import go; `authorization/__init__.py` drops both exports and their
    docstring mention.
  - `src/huron/applications/api/dependencies.py`: `revision_service`, `Revisions` and the
    `RevisionReadService` import go.
  - `src/huron/applications/api/routes/v1/__init__.py`: the `revisions` include and import go.
  - `src/huron/core/raw/__init__.py`: the `RevisionReadService` export goes.
  - `src/huron/core/raw/runtime.py`: `RevisionService`, `RevisionReadService` and `revisions()`
    go.
  - `src/huron/applications/api/routes/v1/schema/ingest_sessions.py`: imports
    `MetadataSubmission` from `huron.core.raw.metadata` and now defines `RevisionView`. Its
    endpoint module imports it from there. Both modules leave whole in M5.3.
  - Tests:
    - `tests/unit/test_core_workflows.py`: the workspace fixture's `runtime.revisions(...)` and
      the revision reads inside `test_raw_checks_owner_target_metadata_and_revocation_before_commit`
      go; that test leaves in M5.3. `tests/unit/test_authorization_guards.py` holds no revision
      case, because its guard was covered only by the deleted suites;
    - `tests/unit/test_execution_model.py`: `get_revision`, `get_revision_manifest`,
      `get_revision_file` and `test_the_file_download_s_stat_executes_off_the_event_loop_thread`
      go;
    - `tests/unit/test_api_router_composition.py`: the `revisions` tag goes, and the tag-set test
      becomes `test_the_openapi_document_carries_sixteen_resource_grained_tags`;
    - `tests/unit/test_api_ingest_crash_matrix.py`: the download assertion goes, keeping the
      commit assertions. `tests/integration/test_verified_raw_ingest.py`: the download step goes,
      keeping the commit. Both called a deleted route, and both leave whole in M5.3.
  - `design/api.html` §3: the revision rows go, including the unimplemented
    `GET /datasets/{id}/revisions` and `POST /revisions/{id}:amend`.
- Design: §19.2 (revision rows); §21.2 rows 2a (revision routes), 12 (read services) and 13
  (revision guard); §7.4; D-137, D-141.
- Verification: the plan-wide gate; the OD-11 floor reset (counts in Execution notes). Acceptance:
  - `rg -n "revision_raw_reader|RevisionRead\b|RevisionReadService|RevisionService|/api/v1/revisions"
    src tests` prints only `tests/ingest_client.py` (deleted in M5.3);
  - `git status` shows exactly the six deletions;
  - no modified file loses its 100 %.
- Dependencies: M5.1.
- Status: pending

### M5.3 Retire the v1 ingest surface and the legacy engine services

- Intent: the engine's last surface and the engine services leave together, because the
  engine's coverage comes from that surface's tests. Measured at HEAD: deleting the ingest,
  transfer, expiry and crash-matrix suites leaves 9 lines of `core/raw/manifest.py`,
  `session_claim`, `SessionLedger` and eight in-memory lines of `core/metastore/ingest.py`
  uncovered. The manifest refusals and the eight in-memory lines get direct tests, and
  `session_claim` and `SessionLedger` go here. Deletions stop at the services: the session
  domain, its adapters and the revision documents keep their own tests and leave in M5.4–M5.7.
  The declared legacy transition therefore runs from M5.2 to M5.7, and code that this task leaves
  without callers stays tested until then. This task is deletion-dominated: about 1,300 changed
  lines, about nine tenths of them removals.
- Delete (the orchestrator runs `git rm` before the pass):
  - `src/huron/applications/api/routes/v1/endpoints/ingest_sessions.py`;
  - `src/huron/applications/api/routes/v1/schema/ingest_sessions.py`;
  - `src/huron/core/raw/_impl/ingest.py`;
  - `src/huron/core/raw/_impl/ingestion.py`;
  - `src/huron/applications/api/expiry.py`;
  - `tests/unit/test_api_ingest_sessions.py`;
  - `tests/unit/test_api_ingest_expiry.py`;
  - `tests/unit/test_api_ingest_crash_matrix.py`;
  - `tests/unit/test_api_completion_capacity.py`;
  - `tests/unit/test_api_expiry.py`;
  - `tests/ingest_client.py`;
  - `tests/acceptance/test_raw_ingest_gate.py`;
  - `tests/integration/test_verified_raw_ingest.py`;
  - `tests/contract/test_commit_intents.py`;
  - `tests/contract/test_ingest_process_death.py`.
- Create / Modify:
  - `src/huron/applications/api/authorization/guards.py`: `IngestDrive`, `_raw_write`,
    `dataset_raw_writer`, `project_intake`, `session_overseer`, `session_owner`, `UploadTarget`,
    `upload_owner` and their imports go. `authorization/__init__.py` drops their exports and the
    docstring list.
  - `src/huron/applications/api/dependencies.py`: `raw_ingestion_service`, `RawIngestion` and the
    `RawIngestionService` import go.
  - `src/huron/applications/api/routes/v1/__init__.py`: the four `ingest_sessions` includes go.
  - `src/huron/applications/api/app.py`: the `ExpirySweep` import and its `async with` go (the
    lifespan yields directly until M7.3 adds `MaintenanceLoop`). `RawRuntime` is built without
    the old engine's store and hierarchy, and the docstrings stop describing the sweep.
  - `src/huron/applications/api/streams.py`: `body_chunks` goes (M7.8 writes its successor;
    `read_capped` stays).
  - `src/huron/core/raw/__init__.py`: the `RawIngestionService` export goes.
  - `src/huron/core/raw/runtime.py`: `IngestService`, `ingestion()`, `expire_lapsed`, the
    old-engine constructor parameters and the `catalog`/`security` type-only imports go;
    `RawRuntime` keeps the registry and dataset services.
  - `src/huron/core/raw/retry.py`: `session_claim` goes (`raw_claim` stays).
  - `src/huron/core/raw/types.py`: `SessionLedger` and `ExpiryReport` go.
  - `src/huron/applications/api/routes/v1/schema/datasets.py`: Catalog's `CreateDataset.entry_layer`
    comment reads "… so its raw layer never receives data" (D-152).
  - Tests:
    - `tests/unit/test_authorization_guards.py`: the thirteen Raw guard cases
      (`dataset_raw_writer`, `project_intake`, `session_overseer` and `session_owner`), `_stack`,
      `_opened_session` and the `IngestService` import go;
    - `tests/unit/test_core_workflows.py`: `test_raw_checks_owner_target_metadata_and_revocation_before_commit`
      and the fixture's old-engine parts go, with its `RawRuntime(...)` construction and the
      `from huron.core.raw.ingest import FileState` import that only the deleted test used (tests
      are not linted, so a stale import would surface only when M5.5 deletes the module);
      `tests/unit/test_authorization_credentials.py` builds `RawRuntime` without the old-engine
      keywords;
    - `tests/unit/test_api_rbac.py`: the three ingest-session requests of
      `test_rbac_delegation_and_layer_writes` go (bob's `201`, alice's `403` and the service
      account's `LAYER_WRITE_FORBIDDEN`). Its service-account, layer-listing and dataset-creation
      assertions stay;
    - `tests/unit/test_api_router_composition.py`: the `ingest-sessions` and `transfer` tags go,
      and the tag-set test becomes
      `test_the_openapi_document_carries_fourteen_resource_grained_tags`;
    - `tests/unit/test_execution_model.py`: the nine ingest and transfer handlers, the upload and
      commit off-loop tests and the `IngestClient` import go (their successors: the L2 write case
      in M7.8, the L3 verified-copy case in M7.3 and the commit publication case in M7.15);
    - `tests/unit/test_api_app.py`: `test_the_lifespan_sweeps_lapsed_sessions_before_serving_the_first_request`
      goes;
    - `tests/unit/test_raw_documents.py`: direct `validate_manifest_path` and `validate_manifest`
      refusals for the lines only the v1 suites covered (PATH_NOT_NFC, PATH_TOO_LONG,
      PATH_TRAVERSAL, PATH_CONTROL_CHARS, PATH_SEPARATOR, the empty manifest, too many files, a
      file too large and a manifest too large);
    - `tests/hierarchy_contract.py` scenario 14: it also freezes a session through the in-memory
      `freeze_commit`, repeats the identical freeze (the replay branch) and reads the session with
      `lock_ingest_session`. These lines lost their only unit coverage with the API suites, and
      they leave with the module in M5.4 (the "Coverage" rule: cover a kept symbol directly).
  - `design/api.html` §3: the ingest and transfer rows and the `_session_view` paragraph go.
  - `docs/getting-started/testing.md` "Acceptance": the sentences describing
    `tests/acceptance/test_raw_ingest_gate.py` go. The command and the workflow lines stay, and
    M10.10 rewrites the section.
- Design: §19.2; §21.2 rows 2a, 5 (Python), 6 and 16 (code), 9, 10, 13 and 14 (tests); §7.3;
  §22.4; §22.5; §19.6; D-137, D-141, D-142, D-152, D-153.
- Verification: the plan-wide gate, `make docs` and `npm run test:e2e` (the lifespan changes;
  the "Gate" rule).
  - Apply the OD-11 floor reset. The verifier confirms from the per-file reports that every
    modified file is at 100 % and that no unmodified file gained a missed line: in particular
    `core/raw/manifest.py`, `core/raw/ingest.py` and `core/metastore/ingest.py`.
  - The deleted clone-group files go through §22.5's review. Record the totals and each accepted
    signature.
  - `rg -n "IngestSessionView|RevisionView|dataset_raw_writer|session_overseer|revision_raw_reader|RawIngestion|ExpirySweep|expire_lapsed|body_chunks|session_claim|SessionLedger|IngestClient" src tests --glob '!tests/contract/test_catalog_store.py'`
    prints nothing (the kept history suite's `_insert_ingest_session_claiming` would match
    `session_claim`).
  - `git status` shows exactly the fifteen deletions.
  - `uv run pytest -m acceptance` collects nothing until M10.10. Record this in Execution notes;
    it is not a per-task gate.
- Dependencies: M5.2.
- Status: pending

### M5.4 Retire the legacy ingest adapters

- Intent: remove the hierarchy stores' session half: `core/metastore/ingest.py`, the ingest
  methods it gave both hierarchy stores through inheritance, their port declarations, row
  mappers and scenarios. Measured at HEAD with the engine suites already gone: deleting these
  tests uncovers only the two row mappers this task deletes. The session domain
  (`core/raw/ingest.py`) keeps its own tests until M5.5. Deletion-dominated: about 1,150 changed
  lines, almost all removals, about 520 of them one contiguous scenario block.
- Delete (the orchestrator runs `git rm` before the pass): `src/huron/core/metastore/ingest.py`.
- Create / Modify:
  - `src/huron/core/metastore/hierarchy.py`:
    - `_TransactionWriter`, `InMemoryHierarchyStore`, `_PostgresTransactionWriter` and
      `PostgresHierarchyStore` stop inheriting the four ingest classes;
    - `TransactionBuffer.sessions`, `files` and `intents` go, with the store's `_sessions`,
      `_intents`, `_files` and their commit merge;
    - `latest_revision` moves in as a private helper of `latest_committed_revision`, which leaves
      in M5.6;
    - the docstrings stop describing ingest.
  - `src/huron/core/metastore/rows.py`: `ingest_session`, `ingest_file` and the
    `huron.core.raw.ingest` import go.
  - `src/huron/core/raw/ports.py`:
    - from `HierarchyWriter`: `lock_ingest_session`, `freeze_commit`, `begin_ingest`,
      `update_ingest_session`, `renew_ingest_session`, `expire_ingest_session` and
      `update_ingest_file` go;
    - from `HierarchyStore`: `ingest_session`, `ingest_files`, `ingest_file` and
      `lapsed_ingest_sessions` go;
    - the type-only imports of `IngestFile`, `IngestSession`, `CommitIntent` and `LedgerEntry`
      go, and `HierarchyWriter`'s docstring drops the reservation and freeze groups.
  - `src/huron/core/raw/types.py`: `LedgerEntry` goes.
  - `src/huron/core/raw/errors.py`: `DatasetLocked` and `DATASET_LOCKED` go; its only raisers
    were in the deleted module. `design/api.html` §7 drops the row.
  - Tests:
    - `tests/hierarchy_contract.py`: scenarios 10–16 go, with their helpers (`_manifest`,
      `planned_files`, `_complete_file`, `_walk_to_committing`, and the scenario-14 additions of
      M5.3) and the `huron.core.raw.ingest`, `DatasetLocked` and `IngestSessionExpired` imports.
      Their evidence returns in M7.14 (`tests/contract/test_raw_numbering.py`);
    - `tests/unit/test_hierarchy_store_memory.py`: the seven scenario wrappers and the three
      ingest point-read tests go;
    - `tests/contract/test_hierarchy_store.py`: `_INGEST_SCENARIOS`, its epoch and loop, section
      6 (`test_two_concurrent_begin_ingest_calls_serialize_on_the_dataset_row`), section 7
      (`test_begin_ingest_binds_expires_at_created_at_and_updated_at_to_one_instant`) and the
      `DatasetLocked`, `LEASE_TTL` and `IngestSession` imports go. The ingest tables leave
      `_HIERARCHY_TABLES` once no scenario writes them;
    - `tests/unit/test_stores_rows.py`: the `ingest_session` and `ingest_file` mapper tests go,
      with the `from huron.core.raw.ingest import FileState, IngestState, UploadAction` import that
      only they used;
    - `tests/unit/test_stores_ports.py`: `test_ledger_entry_pairs_a_file_with_the_session_it_belongs_to`
      goes;
    - `tests/unit/test_raw_documents.py`: `test_freezing_an_unknown_session_does_not_create_a_publication`
      goes, with the imports only it used (`InMemoryHierarchyStore`, `PreconditionFailed`): it
      drives the in-memory `freeze_commit` this task removes, and the `CommitIntent` it freezes
      leaves in M5.5.
- Design: §21.2 rows 10 (the adapters, the `DATASET_LOCKED` code and the mappers) and 17 (the
  ingest halves of the composition ports); §21.1 rule 6; §22.4; §22.5; §22.7; D-137, D-141, D-142.
- Verification: the plan-wide gate.
  - Apply the OD-11 floor reset. `core/metastore/hierarchy.py` is a D-84 adapter module and is
    measured under `-m "unit or contract"`; its missed statements must not grow.
  - The deleted clone-group file `core/metastore/ingest.py` goes through §22.5's review.
  - `rg -n "begin_ingest|freeze_commit|lock_ingest_session|LedgerEntry|DatasetLocked|DATASET_LOCKED|ingest_sessions|ingest_files" src tests --glob '!tests/contract/test_catalog_store.py' --glob '!src/huron/core/raw/ingest.py'`
    prints nothing (the session domain's docstring still names `begin_ingest`; that module leaves
    whole in M5.5).
  - `git status` shows the one deletion.
- Dependencies: M5.3.
- Status: pending

### M5.5 Retire the legacy session domain

- Intent: remove `core/raw/ingest.py` (the IngestSession model, its states including
  RECOVERING, the part plan), the commit command and the storage replay that name it, and the
  error classes it alone raised. Its last `ManifestMismatch` raisers go, so the D-25 zero-byte
  check in `validate_manifest` becomes that code's raiser and takes its new §7 meaning. Measured
  at HEAD: deleting this domain's suites uncovers nothing that survives.
- Delete (the orchestrator runs `git rm` before the pass): `src/huron/core/raw/ingest.py` and
  `tests/unit/test_catalog_ingest.py`.
- Create / Modify:
  - `src/huron/core/raw/documents.py`: `CommitIntent`, `revision_from_storage` and the type-only
    `IngestSession` import go. One of Raw's two `ContractMismatch` raise sites leaves with
    `require_same_command`, and the other leaves in M5.6.
  - `src/huron/core/raw/types.py`: the type-only `IngestFile`, `IngestSession` and `IngestState`
    imports go.
  - `src/huron/core/raw/errors.py`: `IngestSessionExpired`, `IllegalIngestTransition` and their
    codes go.
  - `src/huron/core/raw/manifest.py`: new `EMPTY_SHA256` (the SHA-256 of empty input), and
    `validate_manifest` refuses a zero-byte entry whose `sha256` is not `EMPTY_SHA256` with
    `ManifestMismatch` (D-25).
  - `design/api.html` §7:
    - the `INGEST_SESSION_EXPIRED` and `ILLEGAL_INGEST_TRANSITION` rows go;
    - `MANIFEST_MISMATCH` takes its §19.6 meaning;
    - the planned-P3 table loses `INGEST_RECOVERY_IN_PROGRESS`.
  - Tests:
    - `tests/unit/test_catalog_properties.py`: the three ingest properties go
      (`test_ingest_operations_never_leave_the_transition_table`,
      `test_ingest_file_parts_are_a_subset_of_the_plan_and_complete_only_when_full`,
      `test_upload_plan_requires_every_submitted_file`), with their helpers
      (`_predict_named_operation`, `_predict_require`, `_upload_plan_manifest`), their imports and
      the module docstring's mention;
    - `tests/unit/support.py`: `INGEST_NOW`, `INGEST_OPERATION_TARGETS`, `ingest_lease`,
      `ingest_session`, `ingest_file`, `run_ingest_operation` and the `huron.core.raw.ingest`
      import go, and the module docstring stops naming the ingest domain;
    - `tests/unit/test_raw_documents.py`: the `commit_intent` fixture and the `CommitIntent` and
      `revision_from_storage` cases go. New: `test_zero_byte_entry_must_carry_the_empty_digest`
      (`400 MANIFEST_MISMATCH` class and code) and an accepted zero-byte entry.
- Design: §21.2 rows 5 (`PART_BYTES`, `UploadAction`, `compute_upload_plan`), 9 (RECOVERING,
  `CommitIntent` leaving `documents.py`), 10 (the session model and its codes) and 16 (the
  removed and re-worded rows); §19.6; D-25, D-137, D-141.
- Verification: the plan-wide gate.
  - Apply the OD-11 floor reset (counts in Execution notes).
  - `core/raw/ingest.py` is a baseline clone-group file; its deletion goes through §22.5's
    review.
  - Row 9's check `rg -n "RECOVERING|ingest_recoveries|ingest_commit_intents|INGEST_RECOVERY" src`
    and row 10's check `rg -n "PREPARING|UPLOADING|VERIFYING|ExpirySweep|expire_lapsed|DATASET_LOCKED" src`
    print nothing.
  - `rg -n "PART_BYTES|IngestSession|IngestState|IngestLease|FileState|UploadAction|IllegalIngestTransition|IngestSessionExpired|CommitIntent" src tests`
    prints nothing. M6.2 brings `CommitIntent` back as the commit Command.
  - `rg -n "huron\.core\.raw\.ingest\b|from \.{1,2}ingest import" src tests` prints nothing, so no
    surviving module imports the deleted one (tests are not linted; M5.3 and M5.4 removed the
    imports of `tests/unit/test_core_workflows.py` and `tests/unit/test_stores_rows.py`).
  - `test_error_contract.py` passes with `MANIFEST_MISMATCH` raised only from `manifest.py`.
- Dependencies: M5.4.
- Status: pending

### M5.6 Retire revision documents, paths and the hierarchy's Raw half

- Intent: remove the revision document model, the legacy path helpers and packaged documents,
  and the Raw half the hierarchy stores still carry: revision rows, audit and outbox writes, the
  `ingest_commit` claim exemption, and the composition ports that declared them. Raw's last
  `ContractMismatch` raise site goes, so the row becomes reserved. Measured at HEAD with the
  engine and session suites gone: deleting these suites uncovers only code this task deletes,
  plus `Manifest.total_bytes`, which gets a direct test. Deletion-dominated: about 1,400 changed
  lines, almost all removals.
- Delete (the orchestrator runs `git rm` before the pass):
  - `src/huron/core/raw/paths.py`;
  - `src/huron/core/raw/metadata.py`;
  - `src/huron/schema/documents/revision-index-v1.json`;
  - `src/huron/schema/documents/committed-v1.json`;
  - `src/huron/schema/documents/committed-v2.json`;
  - `src/huron/schema/documents/metadata-v1.json`;
  - `tests/unit/test_schema_committed.py`;
  - `tests/unit/test_schema_revision_index.py`.
- Create / Modify:
  - `src/huron/core/raw/documents.py`:
    - `MetadataDocument`, `CommitRecord`, `IndexEntry`, `RevisionIndex`, `_entry_as_dict`,
      `_entry_from_dict`, `METADATA_SCHEMA`, `COMMITTED_SCHEMA`, `INDEX_SCHEMA` and
      `SERVER_METADATA_MEMBERS` go;
    - the private helpers that only they used go. A helper that `VersionDocument` or
      `root_sentinel` uses stays;
    - the `catalog.errors`, `names.Slugged` and `RevisionRecord` imports go;
    - the module docstring describes `version.json` and the root sentinel only.
  - `src/huron/core/raw/types.py`: `RevisionRecord`, `OutboxEvent` and `PayloadFile` go;
    `AuditEvent` stays.
  - `src/huron/core/raw/ports.py`: `HierarchyWriter`, `RevisionStore`, `HierarchyStore` and the
    `huron.core.catalog.ports` import go. `RawStore` leaves in M5.7.
  - `src/huron/core/metastore/hierarchy.py`:
    - `insert_revision`, `insert_audit_event`, `insert_outbox_event`, `revision` and
      `latest_committed_revision` leave both stores, with the private `latest_revision` and the
      `revisions`, `audit` and `outbox` buffers and their store fields;
    - the `ingest_commit` exemption leaves both `claim` implementations (the in-memory branch and
      the SQL predicate);
    - the docstrings describe Catalog's store only.
  - `src/huron/core/metastore/rows.py`: `revision_record` and the `RevisionRecord` import go.
  - `src/huron/core/foundation/retry.py`: `Replay.kind` loses `ingest_session`, `ingest_commit`
    and `revision`.
  - `src/huron/applications/api/capabilities.py`: `Mutation` and `HierarchyStore` drop
    `HierarchyWriter` and Raw's `HierarchyStore` (`RawPersistence`). `Storage` keeps `RawStore`
    until M5.7.
  - `design/api.html` §7: `CONTRACT_MISMATCH` becomes `reserved` with its §19.6 meaning.
  - Tests:
    - `tests/unit/test_raw_documents.py`: the metadata, commit-record, commit-marker and
      revision-index cases and their helpers (`_record`, `_submission`, `_compose`) go. New:
      a direct `Manifest.total_bytes` assertion in the manifest cases;
    - `tests/unit/test_catalog_paths.py`: the Raw half goes (the `revision_dir`, `staging_dir`
      and `staging_paths` cases and the `huron.core.raw.paths` import);
    - `tests/hierarchy_contract.py`: `scenario_5_revisions`, `committed_revision`, the
      revision, audit and outbox halves of the other scenarios, and the imports this leaves
      unused go;
    - `tests/unit/test_hierarchy_store_memory.py`: the scenario 5 wrapper,
      `test_an_unfinished_commit_claim_cannot_expire_before_its_revision_receipt`,
      `test_insert_revision_accepts_repeated_content_with_a_new_identity` and
      `test_a_rolled_back_transaction_leaves_no_revision_audit_or_outbox_row` go;
    - `tests/contract/test_hierarchy_store.py`: scenario 5 leaves `_SCENARIOS`, the
      structural-conformance test checks the remaining Catalog ports, and `dataset_revisions`
      leaves `_HIERARCHY_TABLES` (no scenario writes it any more, and the `TRUNCATE` of that list
      would fail once `0017` drops the table);
    - `tests/unit/test_stores_rows.py`: the `revision_record` case goes;
    - `tests/unit/test_stores_ports.py`: the module docstring stops naming `HierarchyWriter`;
    - any case of `tests/unit/test_foundation_retry.py` that names a removed replay kind goes
      (confirm with `rg`).
- Design: §21.2 rows 12 (documents, paths, mappers), 13 (Raw's `catalog` and `security`
  imports), 16 (`CONTRACT_MISMATCH`) and 17 (outbox and the composition ports); §19.6 (rows kept,
  `CONTRACT_MISMATCH`); §22.7; D-69, D-111, D-130, D-137.
- Verification: the plan-wide gate.
  - Apply the OD-11 floor reset. `core/metastore/hierarchy.py` is measured under
    `-m "unit or contract"`, and its missed statements must not grow.
  - Clone-group changes go through §22.5's review.
  - Row 12's check `rg -n "INDEX\.json|COMMITTED_SCHEMA|RevisionIndex|MetadataSubmission|split_component" src tests`
    prints nothing.
  - Row 13's check `rg -n "AccessPolicy|RoleBindingAuthorizer|huron\.core\.(security|catalog)" src/huron/core/raw`
    prints nothing.
  - `rg -n "RevisionRecord|OutboxEvent|insert_outbox_event|latest_committed_revision|ingest_commit|HierarchyWriter" src tests --glob '!tests/contract/test_catalog_store.py'`
    prints nothing (the kept history suite's `_insert_outbox_event` and `ingest_commit_intents`
    would match).
  - `test_error_contract.py` passes with `CONTRACT_MISMATCH` reserved.
  - `git status` shows exactly the eight deletions.
- Dependencies: M5.5.
- Status: pending

### M5.7 Retire the legacy storage primitives and settings

- Intent: close the legacy transition on the storage side. Remove the part-protocol and
  envelope methods of `PosixRawStore`, the `RawStore` port, the completion slot and the four
  settings the old engine read. Catalog's store keeps only what Catalog uses, and its
  `initialize()` stops creating `.staging/`. Two kept suites reach the kept primitives only
  through the deleted wrappers: measured at `9882690` with only the cases that survive
  unchanged (the rawstore commit and generation suites and the eleven `tmp_path` cases of the
  materialize suite), `inspection.py` falls to 28.12 % and `materialize.py` to 92.91 % (lines
  35–40, 134, 164 and 167). This task therefore re-points the inspection cases and rewrites the
  primitive cases of the materialize suite, so both modules stay at 100 %. The primitives
  `candidate`, `install` and `file_chunks` keep no `src` caller until M7.1 (`materialize`) and
  M7.9 (`install_documents`) reuse them; they are kept §9.8.6 primitives with direct tests, not
  legacy symbols. After this task no legacy Raw symbol remains in `src`, and slice 4 may
  re-create the names (D-137). This is the largest test rewrite of Milestone 5; the deletions and
  the rewrite stay one task, because re-pointing the suites first would leave the wrappers
  uncovered before they are deleted.
- Delete: none.
- Create / Modify:
  - `src/huron/core/rawstore/store.py`:
    - `create_staging`, `write_part`, `finish_file`, `_copy_file`, `discard_file`,
      `stat_document`, the path-based `read_document`, `write_document`, `seal`, the
      `verify_envelope` and `commit_envelope` wrappers, `_installed_payload`, `_safe_relative`,
      `_stream_part` and `_RESERVED_DOCUMENT_NAMES` go, with the imports only they used;
    - `initialize()` creates only `organization/` (D-94);
    - the constructor keeps `(root, *, reserve_bytes)`;
    - the class docstring describes what remains: Catalog's generation documents and the
      slice-1 dataset-root methods.

    `rawstore/commit.py`, `inspection.py` and `materialize.py` stay for M7.9 and M7.10.
  - `src/huron/core/rawstore/completion.py`: `slot()` and the `max_concurrent` argument go;
    `reserve` stays (§17.3).
  - `src/huron/schema/storage.py`: `PartLengthMismatchError` goes; its successor
    `ChunkLengthMismatchError` lands with `write_chunk` in M6.6. `src/huron/core/rawstore/__init__.py`
    drops its re-export and docstring mention.
  - `src/huron/core/raw/ports.py`: `RawStore` goes.
  - `src/huron/applications/api/capabilities.py`: `Storage` is `GenerationStorage` only.
  - `src/huron/applications/api/settings.py`: `completion_max_concurrent`,
    `completion_reserve_bytes`, `ingest_sweep_interval_seconds` and `ingest_sweep_limit` go.
  - `src/huron/applications/api/app.py`: Catalog's store is `PosixRawStore(settings.data_root)`.
  - `tests/repository_fixture.py`: its docstring and types follow `Storage`.
  - Tests:
    - `tests/unit/test_rawstore_store.py`: the legacy cases go (`create_staging`, the eight
      `write_part` cases, `finish_file`, `discard_file`, both `seal` cases, `write_document`,
      `read_document`, document short writes, `_safe_relative` and the `commit_envelope`
      delegation). The initialize case asserts `organization/` only;
    - `tests/unit/test_rawstore_completion_admission.py`: the slot and store-level cases go
      (positive concurrency, the copy count, the copy-failure release, and the store cases built
      on `finish_file`); the reservation cases stay;
    - `tests/unit/test_rawstore_inspection.py`: every case calls
      `huron.core.rawstore.inspection.verify_envelope(envelope, files, documents, sealed=…,
      anchor=<root>)` instead of `PosixRawStore(root).verify_envelope(...)`, passing the anchor the
      wrapper passed, with its assertions unchanged (M7.9 rewrites the suite to `FileEvidence`);
    - `tests/unit/test_rawstore_materialize.py`: the `storage` fixture (`PosixRawStore(tmp_path,
      max_concurrent_completions=2)` with `create_staging`) and `_finish` go, and with them the 21
      cases built on them or on a deleted method (43 call sites); the eleven `tmp_path` cases stay
      unchanged. A case whose subject is a kept primitive is rewritten against that primitive on
      `tmp_path`, without `PosixRawStore`: `candidate` and `install` (a closed, sealed,
      independent inode installed with no writable descriptor at the rename; a failed `fsync` or
      `fchmod` installing nothing; a zero-progress write removing the candidate; an installed file
      surviving a failed directory flush, then a retry; an existing different file never
      replaced), `observe` (a linked, special, foreign-owned or writable inode refused),
      `directory(..., anchor=)` and `descendant` (a `..` component refused; symlinks never
      followed), `write_all(..., offset=)` (a short `pwrite` continues at the advanced offset) and
      `commit.commit_envelope(staging, final, root)` called directly (a link in the final
      hierarchy refused). A case whose subject is the part-session protocol that leaves here
      (staging creation, two completions racing on one upload, relocated sessions and late
      operations, upload-id names, mismatch retention, process death between completion steps) is
      deleted without a rewrite; its successors are M6.6's staging and chunk cases, M7.1's
      `materialize` cases and the crash suites of M7.9, M7.14 and M7.15. The implementer names
      each deleted case and its successor in the report;
    - `tests/unit/test_catalog_ports.py`: the `RawStore` conformance case gives way to
      `PosixStorageRoots` conformance with `VersionArchive` and `StorageSweeper`. `UploadArea`
      joins in M6.6;
    - `tests/unit/test_api_settings.py`: `test_completion_capacity_configuration_refuses_invalid_limits`,
      `test_sweep_interval_must_be_positive` and `test_sweep_limit_must_be_at_least_one` go.
- Design: §21.2 rows 5 (`write_part`, `_stream_part`, `PartLengthMismatchError`), 12 (the
  `COMMITTED` and `INDEX.json` wrappers of `store.py`), 14 (settings, `slot()`) and 17
  (`RawStore`); §9.8.6 (module map); §17.3 (cleanup of the old gate); §22.7; D-94, D-137.
- Verification: the plan-wide gate and `npm run test:e2e` (`app.py` changes; the "Gate" rule).
  - Apply the OD-11 floor reset.
  - `core/rawstore/materialize.py`, `inspection.py` and `commit.py` stay at 100 % in the unit run;
    the verifier checks lines 35–40, 134, 164 and 167 of `materialize.py` by name.
  - `rawstore/store.py` keeps its name and clone group; any changed signature goes through
    §22.5's review.
  - Row 14's check `rg -n "completion_max_concurrent|completion_reserve_bytes|ingest_sweep|\.slot\(" src tests`
    prints nothing.
  - Row 5's `src` and `tests` operands
    (`rg -n -i "part_bytes|completed_parts|PART_BYTES|write_part" src tests --glob '!tests/contract/test_catalog_store.py'`)
    print nothing; the kept history suite's `ingest_files.completed_parts` assertions are
    migration history (§21.3). The `web/src` operand waits for M10.2.
  - `rg -n "RawStore\b|create_staging|finish_file|PartLengthMismatchError" src tests` prints
    nothing.
- Dependencies: M5.6.
- Status: pending

## Milestone 6 — Upload sessions and upload storage (slice 4)

Goal: migration `0016` and everything a session start needs: the session and version domain, the
session store and offset ledger, the upload area on each root, the admission limits,
`UploadService.start/get/mine/abort` and routes 10–13 and 15.

### M6.1 Migration 0016_raw_uploads

- Intent: the slice-4 tables in one forward-only revision:
  - `raw_upload_sessions`, `raw_upload_files` and `raw_versions`;
  - nine triggers (two of them on `raw_datasets`, two deferred constraint triggers);
  - twelve indexes, with the map, its stamp and the contract proofs.

  `lock_dataset` gains its second statement, the COMMITTING read after the row lock, in the
  PostgreSQL dataset store. The in-memory store gets the same flag from its upload store in M6.3.
- Delete: none.
- Create / Modify:
  - New `migrations/versions/0016_raw_uploads.py`: `down_revision = "0015_raw_datasets"`. The
    §10.6 DDL is one `r"""…"""` block through `migrations._ddl.execute_sql`, statement for
    statement. `downgrade()` raises the §10.6 `RuntimeError`.
  - `migrations/schema.sql`: `-- Reflects: 0016_raw_uploads` and the three table blocks, each
    trigger, CHECK and index on a `[db]` line (§10.12).
  - `src/huron/core/metastore/raw_datasets.py`: the PostgreSQL `lock_dataset` runs
    `SELECT EXISTS (SELECT 1 FROM raw_upload_sessions WHERE dataset_id = $1 AND state = 'COMMITTING')`
    as its own statement after the row lock and sets `RawDataset.committing` (D-167).
  - Tests:
    - `tests/contract/test_raw_schema.py`:
      - `test_schema_map_names_every_raw_object`, whose explicit list has named all eight Raw
        tables since M3.1, now finds the three new ones and checks all 66 objects;
      - one proof per §10.6 trigger row for the nine new triggers, each asserting
        `CheckViolationError.constraint_name`, the deferred ones refusing at `COMMIT`;
      - the unique cases `raw_upload_sessions_one_committing` and `raw_versions_number`;
      - the record transaction in §10.6's order is allowed;
      - the downgrade raises and leaves the version unchanged;
    - `tests/contract/test_raw_stores_postgres.py`:
      `test_lock_dataset_reads_committing_after_the_row_lock` (a COMMITTING row inserted by SQL
      sets the flag; with two pools, a freeze committed while `lock_dataset` waits on the row lock
      is seen).
- Design: §10.6 (with its trigger rules and contract proofs); §10.1; §10.7; §10.12; D-36, D-37,
  D-43, D-45, D-67, D-68, D-120, D-121, D-140, D-167, D-176.
- Verification: the plan-wide gate; the contract suite on Docker. Apply the OD-12 O-8 reset if
  the new adapter statement lowers the unit total; it must be 100 % under
  `-m "unit or contract"`. Acceptance:
  - `uv run python scripts/check_schema_map.py` passes at head `0016_raw_uploads`;
  - each of the nine new triggers has its named proof;
  - `alembic downgrade` from `0016` raises.
- Dependencies: M4.5, M5.7.
- Status: pending

### M6.2 Upload session and version domain

- Intent: re-create `core/raw/ingest.py` under its clone-group name, as the upload-session
  domain: the two state machines as enums and transition tables, the session and file values, the
  commit Command, the ledger read model and the chunk claim, plus the version aggregate in the new
  `core/raw/versions.py`. Decision methods that raise a Raw error land with their first caller
  and that error's §7 row (§19.6 Landing):
  - `UploadSession.abort()` with M6.8;
  - `FileProgress.require_open()` and `require_chunk()` with M7.4;
  - `UploadSession.commit_stage()`, `freeze()`, `lapsed()` and `pending()` with M7.12, which
    lands them with `freeze`'s §7 rows one task before their caller, the driver of M7.13, so
    each of the two commit tasks fits one implementation pass;
  - `Version.require_available()` and `delete()` with M8.2 and M8.8.

  `Verification` lands with `MaterializedFile` in M7.1. `FileEvidence` lands here, because
  `UploadFile` and `CommitIntent` carry it.
- Delete: none.
- Create / Modify:
  - Re-created `src/huron/core/raw/ingest.py` (§8.4.2, §8.5, §11.5, §11.8, §14.2, §14.3):
    - the states and tables: `UploadSessionState`, `SessionEndReason`,
      `UPLOAD_SESSION_TRANSITIONS`, `UploadFileState`, `FileResetReason` and
      `UPLOAD_FILE_TRANSITIONS`;
    - `UploadFile` with `planned(entry, *, file_id, empty)` (size 0: VERIFIED with its
      evidence; otherwise RECEIVING at offset 0, epoch 0) and `evidence()` (`ValueError` unless
      VERIFIED);
    - the session values `FrozenCommit` and `SchemaPin(subject_id, number, schema_version_id)`.
      The adapters fill `SchemaPin` by joining the pinned schema version, because
      `UploadSessionView.schema` (§19.4) needs the subject and the number on target-less reads.
      §8.4.2 has no such value, so `SchemaPin` is deviation 8 and its Execution note gives this
      reason;
    - `UploadSession` (the §8.4.2 fields plus `schema: SchemaPin`) and `CommitStage`;
    - the commands and queries `NewUploadSession`, `SessionRequest` and `SessionQuery`;
    - `CommitIntent` with `of(session, dataset, schema, *, token)` and `version()`. `of`
      decodes the frozen `version.json` with `VersionDocument.decode`, refuses every
      disagreement of §8.5 with `ValueError`, and maps the four documents and the files'
      evidence in manifest order;
    - the frozen values `FileProgress` (§11.5 fields) and `ChunkClaim` (§11.8).
  - New `src/huron/core/raw/versions.py`: `VersionState`, `VersionQuery` and `Version` (§8.4.3
    fields, `location` through `raw_layout.version_location`, and `descriptor()`).
  - `src/huron/schema/storage.py`: `FileEvidence(path, size, fingerprint)` (§9.8.1).
    `src/huron/core/raw/locations.py` re-exports it for metastore (§6.5 rule 5).
  - Tests:
    - `tests/unit/test_raw_transitions.py` gains the session and file tables cell by cell, each
      edge matching the `raw_upload_sessions_frozen` and `raw_upload_files_frozen` rules;
    - new `tests/unit/test_raw_upload_session.py`;
    - `tests/unit/test_schema_storage.py` gains the `FileEvidence` cases.
- Design: §8.4.2; §8.4.3; §8.5; §14.2–§14.5; §11.5 and §11.8 (`FileProgress`, `ChunkClaim`);
  §9.8.1 (`FileEvidence`); D-36, D-38, D-75, D-78, D-97.
- Verification: the plan-wide gate. `core/raw/ingest.py` is re-created under its clone-group
  name, and a new or changed signature goes through §22.5's review (slice 4 budget). Acceptance:
  - `test_zero_byte_file_is_planned_verified_with_its_evidence` and
    `test_evidence_refuses_an_unverified_file`;
  - `test_commit_intent_maps_four_documents_and_manifest_order`;
  - `test_commit_intent_refuses_each_disagreement` (parametrized over the members §8.5 lists);
  - `test_commit_intent_version_is_the_available_row` (the `raw_layout.version_dir` path);
  - `test_version_location_and_descriptor`;
  - the transition tables have no edge the triggers refuse.
- Dependencies: M4.2, M5.7.
- Status: pending

### M6.3 Upload ports and in-memory adapters

- Intent: declare the ports that session start, the chunk protocol and their PostgreSQL adapters
  share, and re-create `core/metastore/ingest.py` with the in-memory upload store, under the
  shared contract scenarios. Only methods that M6.4 and M6.5 also implement in PostgreSQL are
  declared now: a port method is declared in the task where every adapter that could be wired
  implements it. `settle_file` arrives with the verifier claims (M7.2), and `bump_dataset` with
  its PostgreSQL statement (M6.4). `insert_version` and the `VersionStore` replay reads arrive
  with the commit tasks.
- Delete: none.
- Create / Modify:
  - `src/huron/core/raw/ports.py`:
    - `UploadStore`: `transaction`, `session`, `sessions` and `known_sessions`;
    - `UploadTransaction(RawTransaction, DatasetRows, SchemaVersionRows)`:
      `count_open_sessions`, `outstanding_bytes`, `insert_session`, `lock_session` and
      `save_session`, as §8.7.2 gives them;
    - `OffsetLedger`: `transaction`, `progress` and `writer_epoch`;
    - `ChunkTransaction`: the seven methods of §11.8.
  - Re-created `src/huron/core/metastore/ingest.py`: `InMemoryUploadStore` fills `UploadStore`
    and `OffsetLedger`.
    - It shares one in-memory state and lock with `InMemoryDatasetStore` and `InMemorySchemaStore`,
      so `lock_dataset` and `lock_schema_version` see their rows, and the in-memory
      `lock_dataset` reports `committing` from the shared sessions (D-167, the in-memory half of
      M6.1).
    - Its reads fill `UploadSession.schema` and `FileProgress`, applying the §11.8 rules on the
      injected clock: `live`, `dataset_active`, `upload_offset < size` while RECEIVING, VERIFIED
      final, and an epoch that only grows.
  - `tests/raw_store_contract.py`: new shared scenarios:
    - `scenario_session_lifecycle`: insert with planned files and zero-byte VERIFIED rows; reads
      with and without files; `save_session` from OPEN to ABORTED, and to COMMITTING with a token
      and lease; a wrong `source` answers `False`;
    - `scenario_open_session_count`: only the actor's live OPEN sessions count;
    - `scenario_outstanding_bytes`: the §9.2 sum; a VERIFIED file and an expired OPEN session
      contribute nothing; another root's sessions are excluded;
    - `scenario_epoch_compare_and_set`: `open_stream` only at the stored offset of a RECEIVING
      file; `advance` needs the same epoch and offset and makes the file RECEIVED at size;
      `close_stream` and `reset_offset` are fenced by the epoch;
    - `scenario_newest_writer_wins`;
    - `scenario_session_pages`: the owner's list newest first, with filters and a cursor.

    `tests/unit/test_raw_stores_memory.py` runs them all now. The PostgreSQL runner adds each
    scenario in the task that implements its statements: the session scenarios in M6.4 (except
    the COMMITTING save, which joins in M7.11) and the ledger scenarios in M6.5.
- Design: §8.7.2 (`UploadStore`, `UploadTransaction`, `OffsetLedger`); §11.8; §8.7.5; §9.2 (the
  outstanding-bytes rule); D-37, D-97, D-139, D-162.
- Verification: the plan-wide gate. The in-memory adapter is at 100 % in the unit run, and the
  re-created clone-group file goes through §22.5's review. Acceptance:
  - each scenario above passes in memory;
  - a `ChunkTransaction` whose epoch was superseded records nothing and answers `None`;
  - the conformance of `InMemoryUploadStore` to `UploadStore` and `OffsetLedger` is asserted in
    `tests/unit/test_raw_stores_memory.py` (structural, no inheritance).
- Dependencies: M6.2.
- Status: pending

### M6.4 PostgreSQL session store and its caps

- Intent: the PostgreSQL session statements, with the per-principal session cap (L5) and the
  per-root outstanding-space sum exact across pools, plus `DatasetRows.bump_dataset` in both
  dataset stores and both upload transactions.
- Delete: none.
- Create / Modify:
  - `src/huron/core/raw/ports.py`: `DatasetRows.bump_dataset(dataset, *, latest)` (§8.7.1).
  - `src/huron/core/metastore/ingest.py`: `PostgresUploadStore` with `transaction()`, `session`
    (the pinned schema version joined), `sessions`, `known_sessions`, and a transaction class:
    - `count_open_sessions` takes the `raw-sessions:` advisory lock, then counts in a separate
      statement (§17.4);
    - `outstanding_bytes` takes the `raw-space:` lock, then runs the §10.7 sum;
    - `insert_session` sets `expires_at`/`deadline_at` on the database clock and inserts one file
      row per manifest file;
    - `lock_session` and `save_session` (OPEN → ABORTED; its COMMITTING entry and exit, with the
      `raw_upload_sessions_one_committing` mapping, arrive in M7.11);
    - the `DatasetRows` and `SchemaVersionRows` behaviour through the `rows.py` mixins.
  - `src/huron/core/metastore/raw_datasets.py` and `rows.py`: `bump_dataset` (etag + 1, plus
    `latest_number` + 1 when `latest`, under the etag guard) in the shared `DatasetRows` mixin and
    in the in-memory dataset store.
  - Tests:
    - `tests/raw_store_contract.py`: `scenario_bump_dataset`. On PostgreSQL only the etag-only
      bump runs; `latest=True` needs a version row at `COMMIT` (`raw_datasets_latest_recorded`)
      and is proved with the record transaction in M7.11;
    - `tests/contract/test_raw_stores_postgres.py` runs the session scenarios;
    - new `tests/contract/test_raw_upload_ledger.py` (two pools; M6.5 extends it).
- Design: §8.7.2; §17.4 (L5); §10.7 (the space sum); §17.10; D-60, D-112, D-162.
- Verification: the plan-wide gate; the contract suite on Docker. Apply the OD-12 O-8 floor
  reset: 100 % of the new adapter statements under `-m "unit or contract"`, counts in Execution
  notes. This task draws on slice 4's clone budget. Acceptance, in `test_raw_upload_ledger.py`:
  - `test_open_session_cap_exact_across_pools`: N concurrent inserting transactions of one actor
    against a cap of K commit exactly K;
  - `test_lapsed_open_session_not_counted`;
  - `test_start_counts_outstanding_bytes_of_open_sessions`, at store level: two transactions from
    the two pools, each fitting alone but not together against a fixed free value, insert exactly
    one session; a partly received, a RECEIVED and a VERIFIED file each contribute what §9.2 says.
- Dependencies: M6.1, M6.3.
- Status: pending

### M6.5 PostgreSQL offset ledger and stream leases

- Intent: the §11.8 statements in PostgreSQL. The offset advances by compare-and-set on epoch and
  offset, the stream lease is counted per principal (L4) exactly across pools, and expiry renews
  only with a recorded chunk. Contract cases replace the deleted writer-exclusion suite with
  epoch fencing (D-83).
- Delete: none.
- Create / Modify:
  - `src/huron/core/metastore/ingest.py`: `PostgresUploadStore` also fills `OffsetLedger`:
    - `progress` (the §11.8 join, no locks) and `writer_epoch` (one primary-key `SELECT`, no
      transaction held);
    - a `ChunkTransaction` class with `lock_file` (the session row `FOR SHARE OF s`) and
      `count_streams` (the `raw-streams:` lock, then the count excluding the claimed file);
    - `open_stream` (`writer_epoch + 1`, the lease of `CHUNK_DEADLINE_SECONDS`, `RETURNING
      writer_epoch`) and `renew_session` (`LEAST(now() + idle, deadline_at)` `WHERE state = 'OPEN'
      AND deadline_at > now()`);
    - `advance` (the epoch-and-offset compare-and-set, RECEIVED at size, clearing `last_error`
      and the lease), `close_stream` and `reset_offset`.

    Each adapter method is one statement with cyclomatic complexity ≤ 3 (§11.14).
  - Tests:
    - `tests/contract/test_raw_stores_postgres.py` runs the ledger scenarios of M6.3;
    - `tests/contract/test_raw_upload_ledger.py` gains the cases below.
- Design: §11.8; §11.9; §17.4 (L4); §17.5; §11.15 (contract); D-30, D-60, D-83, D-112, D-155.
- Verification: the plan-wide gate; the contract suite on Docker. Apply the OD-12 O-8 reset
  (counts in Execution notes). Acceptance:
  - `test_concurrent_patch_newest_writer_wins`: two begins at one offset from two pools; only the
    newer epoch's `advance` records, and the older answers `None`;
  - `test_finish_rolls_back_renewal_when_superseded`: the renewal and the failed advance share
    one transaction, and `expires_at` is unchanged;
  - `test_principal_stream_cap_exact_across_pools`;
  - `test_expired_stream_leases_stop_counting` (R9);
  - `test_retry_on_same_file_not_counted`;
  - the epoch-fencing cases `test_stale_epoch_cannot_advance_close_or_reset`,
    `test_open_stream_refuses_a_moved_offset_or_a_received_file` and
    `test_renewal_refused_after_deadline_or_end`.
- Dependencies: M6.4.
- Status: pending

### M6.6 Upload area: staging and chunk writes

- Intent: the first half of the `UploadArea` port on the POSIX adapter:
  - per-session staging under `.huron/staging/`;
  - positional, fsynced chunk writes hashing SHA-256 and SHA-1, with the per-chunk reserve check;
  - free-space measurement and the staging listing.

  `PosixStorageRoots` dispatches each call by root key and confirms every absence against the
  sentinel before answering.
- Delete: none.
- Create / Modify:
  - `src/huron/schema/storage.py`: `ChunkDigests`, `ChunkLengthMismatchError` (the successor of
    `PartLengthMismatchError`), `ScratchInputMissingError` and `StagingMissingError` (§9.8.1).
    `src/huron/core/rawstore/__init__.py` re-exports `ChunkLengthMismatchError`.
  - `src/huron/core/rawstore/store.py`: `PosixRawStore.open_staging(session_id, empty_paths)`,
    `write_chunk(session_id, tus_upload_id, chunks, *, offset, length, reserve)`, `free_bytes()`
    and `staging_ids()` (§9.8.3), with paths from `huron.schema.raw_layout`:
    - `open_staging`: `staging/<s>/{upload,completion,envelope/payload}` at 0700, and the
      zero-byte files installed empty and sealed. A repeat re-observes them;
    - `write_chunk`: the `statvfs` reserve check before opening anything; `O_WRONLY |
      O_NOFOLLOW`, with `O_CREAT` only at offset 0 and never `O_TRUNC`; `pwrite` of exactly
      `length` bytes, hashing both digests; fsync of the file and `upload/`;
    - `staging_ids`: entries named by 32 lowercase hex digits with their `st_mtime`. Other names
      are logged and skipped.
  - `src/huron/core/rawstore/roots.py`: `PosixStorageRoots` dispatches the four methods by key
    with §9.8.6's sequence. `ScratchInputMissingError` and `StagingMissingError` are confirmed
    against the sentinel and `root_id`; otherwise the root is recorded UNAVAILABLE and
    `StorageRootUnavailableError` replaces the answer. `ENOENT` on a `.huron/` child answers
    `sentinel_missing`.
  - `src/huron/core/raw/ports.py`: `UploadArea` with these four methods; M7.1 adds
    `materialize` and `discard_input`.
  - Tests:
    - `tests/unit/test_rawstore_store.py`:
      - `test_open_staging_creates_private_children_and_installs_empty_files`, with a repeat;
      - `test_write_chunk_writes_positionally_and_reports_both_digests`;
      - `test_write_chunk_creates_only_at_offset_zero`;
      - `test_write_chunk_refuses_short_and_long_streams` (`ChunkLengthMismatchError`; the
        written bytes stay unrecorded);
      - the missing input and the missing tree;
      - `test_chunk_refused_below_reserve` (a stubbed `statvfs`: `ENOSPC` before the input is
        opened);
      - the `staging_ids` filter;
    - `tests/unit/test_rawstore_roots.py`: dispatch, absence confirmed (`StagingMissingError`
      with the sentinel present, `StorageRootUnavailableError` once it is gone), an unknown key;
    - `tests/unit/test_catalog_ports.py`: `PosixStorageRoots` conforms to `UploadArea` as well;
    - `tests/unit/test_schema_storage.py`: the new values.
- Design: §9.8.3 (`open_staging`, `write_chunk`, `free_bytes`, `staging_ids`); §9.8.1; §9.8.6;
  §9.2 (free space); D-21, D-24, D-93, D-99, D-132, D-162.
- Verification: the plan-wide gate; every touched rawstore and schema module at 100 % on real
  temporary roots. `rawstore/store.py` keeps its clone group, and a changed signature goes
  through §22.5's review. Acceptance: the named cases above, and import-linter's "rawstore uses
  schema only" contract still holds (the new values live in `huron.schema.storage`).
- Dependencies: M2.8, M5.7.
- Status: pending

### M6.7 Raw limits and upload admission

- Intent: the per-process admission object (L1 streams, L2 write threads, L3 verify threads, L10
  read threads, and the per-upload writer registry of D-155) and the limits value. Both are built
  once in the lifespan from `RawSettings`. This task also adds the fail-fast and cap error classes
  their checks raise, with `Retry-After`.
- Delete: none.
- Create / Modify:
  - New `src/huron/core/raw/admission.py` (§8.3.3, §17.3):
    - `RawLimits` with the §8.3.3 fields; `stream_watch` defaults to 5 s and is not a setting;
    - `RawLimits.check_open_sessions`, `check_streams` and `check_free(free_bytes, total_bytes,
      *, outstanding=0)`;
    - `UploadAdmission(*, streams, verifiers)` with `stream()`, `writer(tus_upload_id, epoch)`,
      `write_threads`, `verify_threads` and `read_threads`.
  - `src/huron/core/raw/errors.py`: `UploadCapacityExhausted` (503, `retry_after` 2),
    `UploadStreamsExhausted` (429, 5), `TooManyOpenSessions` (429, 60) and `InsufficientStorage`
    (507, 60), each raised literally by its check, with their `ERROR_CODES` entries.
  - `src/huron/applications/api/app.py`: `_raw_limits(settings.raw)` builds `RawLimits`. The
    lifespan builds one `UploadAdmission(streams=process_streams, verifiers=process_verifiers)`
    and passes both to `RawRuntime` (§8.6.8, D-112).
  - `src/huron/core/raw/runtime.py`: `RawRuntime` gains the `admission` and `limits` keywords and
    exposes `admission`; `tests/unit/test_authorization_credentials.py` passes both (the
    "Composition root" rule).
  - `design/api.html` §7: the four rows with their `Retry-After` values.
  - Tests:
    - new `tests/unit/test_upload_admission.py` (§17.10 unit list);
    - `tests/unit/test_api_app.py`: the lifespan sizes admission from the settings.
- Design: §8.3.3; §17.1–§17.3; §17.6; §17.10 (unit); §8.9 (lifetimes); D-60, D-61, D-112,
  D-155, D-158.
- Verification: the plan-wide gate and `npm run test:e2e` (the lifespan changes; the "Gate"
  rule). Acceptance (named cases in `test_upload_admission.py`):
  - `test_stream_fails_fast_at_capacity` (`503`, `Retry-After: 2`);
  - `test_stream_releases_on_exception_and_cancellation`;
  - `test_write_threads_never_block_while_stream_tokens_are_held`;
  - `test_newer_epoch_cancels_the_older_writer_scope`, `test_late_older_epoch_starts_cancelled`,
    `test_other_uploads_untouched` and `test_exit_removes_only_its_own_entry`;
  - `test_check_free_counts_outstanding_and_the_reserve`;
  - the L4 and L5 boundaries (`count == cap` refuses);
  - `test_domain_error_rows_document_their_retry_after` passes with the new rows;
  - `UploadAdmission(streams=0, verifiers=1)` raises `ValueError`.
- Dependencies: M2.6, M6.2.
- Status: pending

### M6.8 UploadService: start, reads and abort

- Intent: re-create `core/raw/_impl/ingestion.py` under its clone-group name with
  `UploadService`'s session half. `start` composes the thirteen guards of §13.3, then `get`,
  `mine` and the idempotent owner `abort`. This task adds the error classes and §7 rows that
  route 10 and the abort raise first, and the vocabulary renames of the manifest rules. The
  service runs against the in-memory stores and temporary roots; M6.9 mounts and wires it.
- Delete: none.
- Create / Modify:
  - Re-created `src/huron/core/raw/_impl/ingestion.py` (§8.6.2):
    - `UploadService(uploads, datasets, schemas, area, *, limits, clock)`. The ledger, admission,
      trigger and commit collaborators join with their tasks;
    - `start(grant, dataset_id, request, *, idempotency_key)`, in §8.6.2's steps:
      - the target and `write` checks, a replay check before any storage access, and
        `require_active`;
      - `validate_manifest` with the `RawLimits` sizes;
      - the pin through `pinnable_version`, then `require_pinnable`;
      - `schema.validate` through `asyncify`;
      - the unlocked L5 and free-space pre-checks, then `open_staging`;
      - one transaction: `claim`, `lock_dataset(share=True)`, `lock_schema_version`,
        `count_open_sessions`, `outstanding_bytes`, a fresh `free_bytes`, `insert_session`,
        `raw.session.started` and `remember(Replay("upload_session", id))`.

      Session and file ids are `uuid7()`; zero-byte files are planned VERIFIED with their
      `open_staging` evidence;
    - `get` (owner), `mine` (the owner's `SessionQuery` page) and `abort` (one transaction:
      `lock_session`, `require_owner`, `session.abort()`, then `save_session(source=OPEN)` and
      `raw.session.aborted` when it changed).
  - `src/huron/core/raw/ingest.py`: `UploadSession.abort()` (True on OPEN, False on ABORTED,
    `UploadSessionClosed` otherwise).
  - `src/huron/core/raw/errors.py`:
    - new `UploadSessionClosed` (409, `context.state` and `context.reason`);
    - `EmptyRevision` → `EmptyVersion` (`EMPTY_VERSION`) and `RevisionTooLarge` →
      `VersionTooLarge` (`VERSION_TOO_LARGE`).

    `SchemaVersionNotUsable` and `MetadataInvalid` exist since M3.4, raised by
    `require_pinnable` and `validate`.
  - `src/huron/core/raw/manifest.py`:
    - the renamed raises;
    - `PATH_TOO_LONG` also refuses a path segment over 255 UTF-8 bytes (D-90);
    - `max_revision_bytes` and `DEFAULT_MAX_REVISION_BYTES` become `max_version_bytes` and
      `DEFAULT_MAX_VERSION_BYTES`;
    - no "revision" wording is left in the module.
  - `src/huron/core/foundation/retry.py`: `Replay.kind` gains `upload_session`.
  - `design/api.html` §7:
    - the `UPLOAD_SESSION_CLOSED` row;
    - the two renamed rows;
    - `TOO_MANY_FILES` with its §19.6 meaning.
  - Tests:
    - `tests/unit/test_raw_services.py` (the session half);
    - `tests/unit/test_raw_documents.py`: the renamed classes and the 255-byte segment rule.
- Design: §8.6.2 (start, get, mine, abort); §13.3; §16.6 (validation at start); §8.8; §19.6
  (rows added, renamed and re-worded); §14.2 (abort gating); D-24, D-42, D-57, D-90, D-105,
  D-112, D-149, D-161, D-162.
- Verification: the plan-wide gate. The re-created clone-group file goes through §22.5's review,
  and the D-1 vocabulary holds in `manifest.py`. Acceptance, in `test_raw_services.py`:
  - `test_start_refusals_in_guard_order` (one case per §13.3 guard, from
    `404`/`409 REALM_BINDING_CONFLICT`/`403` through `507`);
  - `test_start_replays_before_touching_storage` (no staging tree for a replay);
  - `test_open_session_cap_refused_before_staging` (the L5 pre-check creates no tree);
  - `test_start_pins_the_highest_active_version` and `test_start_refuses_a_deprecated_pin`;
  - `test_metadata_invalid_lists_pointer_errors` (at most 20, ordered);
  - `test_metadata_over_one_mib_is_invalid` (pointer `""`);
  - `test_zero_byte_files_start_verified`;
  - `test_start_never_creates_the_dataset_root` (D-149);
  - `test_abort_is_idempotent_and_owner_only` (another actor gets `404`; COMMITTING is
    represented in memory and answers `409 UPLOAD_SESSION_CLOSED`);
  - the `raw.session.started` and `raw.session.aborted` audit payloads of §14.6.
- Dependencies: M3.4, M4.6, M6.3, M6.6, M6.7.
- Status: pending

### M6.9 Upload session routes 10–13 and the limits route

- Intent: mount session start, the owner's session list and read, abort, and the limits route
  under `/api/v1/raw`. Wire the PostgreSQL upload store and ledger, and `PosixStorageRoots` as
  `UploadArea`, into the lifespan with conformance asserts. Route 10 hands out each file's
  `upload_url`; the tus routes behind it arrive in M7.7 and M7.8.
- Delete: none.
- Create / Modify:
  - New `src/huron/applications/api/routes/v1/schema/raw_upload_sessions.py`:
    - `ManifestFile`: free now that its legacy namesake is gone; `media_type` gets the 1..255
      bound;
    - `StartUploadSession`, `UploadFileView`, `SessionSchema`, `UploadSessionView`
      (`schema_pin` aliased `schema`, plus `file_count`, `total_bytes`, and `files: null` in list
      items) and `RawLimitsView`;
    - builders: `upload_url = "/api/v1/raw/tus/<tus_upload_id>"`, with `chunk_bytes` from
      `RawLimits`.
  - New `src/huron/applications/api/routes/v1/endpoints/raw_upload_sessions.py`: the routers
    `dataset_sessions` (prefix `/datasets/{dataset_id}/upload-sessions`), `router`
    (`/upload-sessions`) and `limits` (`/limits`), all tagged `raw-uploads`. Handlers:
    - `start_upload_session`: `IdempotencyHeader`, the body through `raw_body` (16 MiB),
      `openapi_extra`, `201`, and a replay with the current view;
    - `list_upload_sessions`: `dataset_id`, `state`, `limit` and `after`, newest first through
      `created_cursor_key`;
    - `get_upload_session`;
    - `abort_upload_session`: an empty body, `200`, and `200` again when already ABORTED;
    - `get_raw_limits`.
  - `src/huron/applications/api/routes/v1/__init__.py`: the three includes.
  - `src/huron/applications/api/app.py`: `PostgresUploadStore` on the pool, placed in `RawPorts`.
  - `src/huron/core/raw/runtime.py`: `RawPorts` gains `uploads` and `ledger` (the one upload store,
    which fills both ports) and `area` (the `PosixStorageRoots`); `RawRuntime` composes
    `UploadService(ports.uploads, ports.datasets, ports.schemas, ports.area, limits=…, clock=…)`
    and exposes it as `uploads`; `tests/unit/test_authorization_credentials.py` fills the new
    fields (the "Composition root" rule).
  - `src/huron/applications/api/capabilities.py`: conformance of the PostgreSQL and in-memory
    upload stores to `UploadStore` and `OffsetLedger` (with their transactions), and of
    `PosixStorageRoots` to `UploadArea`, asserted in the lifespan.
  - `src/huron/applications/api/runtime.py` and `tests/unit/support.py`: `ApiStores` carries the
    upload store beside the Raw stores of M3.7 and M4.7, and `memory_stores()` builds the
    in-memory one.
  - `design/api.html` §3: rows for routes 10–13 and 15.
  - Tests:
    - new `tests/unit/test_raw_upload_sessions_api.py`;
    - `tests/unit/test_api_router_composition.py`: the tag set gains `raw-uploads` and the test
      becomes `test_the_openapi_document_carries_fifteen_resource_grained_tags`, the Raw
      no-redeclaration twin covers the module, and `test_raw_routes_declare_no_body_parameter`
      covers route 10;
    - `tests/unit/test_execution_model.py`: the five handlers;
    - `tests/unit/test_raw_authority.py`: the route-10 oversized-body row (16 MiB).
- Design: §19.3 routes 10–13 and 15; §19.4 (`raw_upload_sessions.py`); §19.5 (pagination and
  idempotency); §7.5; §12.2 (16 MiB); §6.6 step 8; D-42, D-127, D-128.
- Verification: the plan-wide gate; the contract suite (the PostgreSQL store wired through the
  lifespan); `npm run test:e2e` (the lifespan, its conformance asserts, `ApiStores` and
  `memory_stores()` change; the "Gate" rule). Acceptance, in `test_raw_upload_sessions_api.py`:
  - `test_start_answers_201_with_upload_urls_and_chunk_bytes` (`expires_at ≤ deadline_at`,
    zero-byte files VERIFIED);
  - `test_start_replay_answers_201_with_the_current_view`;
  - `test_start_problem_codes` (`400 EMPTY_VERSION` and `PATH_*`, `409 PATH_COLLISION`, `413`,
    `422 METADATA_INVALID`, `429 TOO_MANY_OPEN_SESSIONS` with `Retry-After: 60`, `507` with
    `Retry-After: 60`, `409 DATASET_NOT_ACTIVE` for a PENDING dataset);
  - `test_session_list_is_the_owners_with_files_null`;
  - `test_another_actors_session_is_404`;
  - `test_abort_twice_answers_200` and `test_abort_of_a_committing_session_is_409` (seeded in
    memory);
  - `test_limits_view_reflects_the_settings`;
  - `test_hierarchy_keeps_named_patch_and_response_schemas` still passes.
- Dependencies: M6.5, M6.8.
- Status: pending

## Milestone 7 — Verification, tus and commit (slice 4)

Goal: bytes move by tus 1.0.0, become verified independent copies, and publish as immutable versions
by one exclusive rename, with leases, takeover and the ported crash evidence.

### M7.1 Verified copies

- Intent: the second half of `UploadArea`. `materialize` makes the verified independent copy of
  a received scratch input and installs it in the envelope only when it matches the manifest.
  `discard_input` trashes the scratch input, fenced by the inode the copy read (D-171). The
  verifier's outcome value `Verification` lands here with `MaterializedFile`, which it reads.
- Delete: none.
- Create / Modify:
  - `src/huron/schema/storage.py`: `MaterializedFile(size, sha256, fingerprint, input)` (§9.8.1).
  - `src/huron/core/rawstore/store.py`:
    - `PosixRawStore.materialize(session_id, tus_upload_id, path, *, size, sha256)`, under
      `CompletionAdmission.reserve(size)`:
      - copy `upload/<u>` into a fresh `completion/` candidate, seal it 0444, fsync it and
        re-read its SHA-256;
      - install it at `envelope/<path>` by exclusive rename only on a match. An equal installed
        file is re-observed (`input=None`), and a differing installed file is a `ValueError`;
      - return the fingerprint or `None`, and `input` as the scratch input's `st_dev:st_ino`;
    - `discard_input(session_id, tus_upload_id, *, input=None)`: rename `upload/<u>` into the
      root's `.huron/trash/<uuid4 hex>`, only while the name holds that identity when `input` is
      given. An absent input or tree, or another inode at the name, is a no-op. Both directories
      are fsynced.

    It reuses the `materialize.py` primitives.
  - `src/huron/core/rawstore/roots.py`: dispatch of both methods by key. `materialize`'s absence
    answers are confirmed against the sentinel; `discard_input` needs no confirmation (§9.8.6).
  - `src/huron/core/raw/ports.py`: `UploadArea` gains `materialize` and `discard_input`.
  - `src/huron/core/raw/ingest.py`: `Verification` with `of(progress, observed)` (VERIFIED only
    for an installed copy whose size and SHA-256 equal the manifest entry, otherwise RECEIVING
    with `DIGEST_MISMATCH`) and `lost()` (RECEIVING, `SCRATCH_LOST`).
  - Tests:
    - `tests/unit/test_rawstore_store.py`:
      - `test_materialize_installs_a_matching_copy_sealed`;
      - `test_materialize_mismatch_installs_nothing` (`fingerprint=None`);
      - `test_materialize_replay_reobserves_the_installed_copy`;
      - `test_materialize_enospc_from_the_reservation`;
      - `test_materialize_differing_installed_file_is_value_error`;
      - `test_discard_input_moves_into_trash`;
      - `test_discard_input_leaves_a_newer_inode` (D-171);
    - `tests/unit/test_rawstore_roots.py`: dispatch, with `ScratchInputMissingError` and
      `StagingMissingError` confirmed;
    - `tests/unit/test_raw_upload_session.py`: the `Verification.of` and `lost` cases;
    - `tests/unit/test_catalog_ports.py`: conformance still holds with the larger `UploadArea`.
- Design: §9.8.3 (`materialize`, `discard_input`); §9.8.1 (`MaterializedFile`); §8.4.2
  (`Verification`); §13.5; §17.3 (the reservation stays); D-22, D-96, D-171.
- Verification: the plan-wide gate, with every touched module at 100 % on real temporary roots.
  Acceptance: the named cases above. A copy whose bytes changed between the reads is never
  installed. `CompletionAdmission` reservations return after every failure.
- Dependencies: M6.6.
- Status: pending

### M7.2 Work claims and findings

- Intent: the one claim primitive of D-63 for the two leased slice-4 duties (verify a received
  file, finish a commit), its heartbeat and token-fenced completion, the deduplicated Raw finding
  report, and the verifier's settle statement. Both stores implement all of it.
- Delete: none.
- Create / Modify:
  - `src/huron/core/raw/types.py` (§8.7.3):
    - `WorkKind` with `VERIFY_FILE` and `FINISH_COMMIT`; later kinds join with their duties
      (M12);
    - `WorkItem`, and `FindingCode` with the D-66 codes as §8.7.3 lists them;
    - `Finding`.
  - `src/huron/core/raw/ports.py`:
    - `MaintenanceStore` gains `claim(kind, *, roots, batch, lease, older_than, ids)`,
      `heartbeat(item, *, lease)`, `complete(item, *, audit=None)` and `report(finding)`;
    - `UploadTransaction` gains `settle_file(item, outcome: Verification)`.
  - `src/huron/core/metastore/raw_datasets.py`:
    - the PostgreSQL `MaintenanceStore`: one claim statement shape keyed by a closed mapping of
      `WorkKind` to constant SQL fragments. It uses `FOR UPDATE OF <alias> SKIP LOCKED`, a fresh
      `work_token`, `work_expires_at = now() + lease`, `raw_datasets.storage_root = ANY($roots)`,
      the lease clause and the due-column order of §8.7.3. Its predicates:
      - `VERIFY_FILE`: RECEIVED files of OPEN sessions;
      - `FINISH_COMMIT`: COMMITTING sessions, optionally limited to `ids`;
    - `heartbeat`: fenced by the token, and for `VERIFY_FILE` also by an OPEN session;
    - `complete`: clears the token only, for these two kinds;
    - `report`: the `raw-finding:` advisory lock and the deduplicated insert of §10.9;
    - the in-memory `MaintenanceStore` with the same semantics on the injected clock.
  - `src/huron/core/metastore/ingest.py`: `settle_file` in both upload transactions. It writes
    VERIFIED with the fingerprint and `verified_at`, or RECEIVING at 0 with `last_error` and
    `received_at` cleared. It clears the token `WHERE work_token = $token AND state = 'RECEIVED'`
    and answers `False` on 0 rows.
  - Tests:
    - `tests/raw_store_contract.py`: claim, heartbeat, complete, report and `settle_file`
      scenarios, run in memory and on PostgreSQL;
    - new `tests/contract/test_raw_maintenance_claims.py`.
- Design: §8.7.3; §18.3 (claims of the leased duties, completions); §10.9 (the finding insert);
  §14.6; D-63, D-106, D-115, D-117.
- Verification: the plan-wide gate; the contract suite on Docker. Apply the OD-12 O-8 reset
  (counts in Execution notes). Acceptance, in `test_raw_maintenance_claims.py`:
  - `test_claim_skips_locked_rows_across_pools`: two concurrent claims from two pools get
    disjoint items;
  - `test_claim_respects_the_lease_and_takes_over_after_it`;
  - `test_claim_only_on_available_roots`;
  - `test_verify_claim_ignores_files_of_closed_sessions`;
  - `test_stale_token_cannot_heartbeat_complete_or_settle`;
  - `test_settle_file_requires_the_token_and_a_received_row`;
  - `test_report_deduplicates_per_root_code_and_path_across_pools`: two replicas report the same
    orphan once, and the same path on another root is a second finding.
- Dependencies: M6.4, M7.1.
- Status: pending

### M7.3 FileVerifier, RawMaintenance and the maintenance loop

- Intent: the asynchronous verifier and the per-replica maintenance loop that drives it.
  `MaintenanceLoop` is built before `RawRuntime` as its `VerificationTrigger` and started after
  the conformance asserts, so the chunk protocol (M7.4) wakes a real trigger (deviation 5).
  `RawMaintenance` runs only `VerifyFiles` for now; the other duties join in M7.16 and M12.
- Delete: none.
- Create / Modify:
  - New `src/huron/core/raw/_impl/verifier.py`: `FileVerifier(uploads, ledger, work, area,
    admission, *, limits)`.
    - `run(batch, *, roots)` claims `VERIFY_FILE` items with `work.claim(VERIFY_FILE, roots=roots,
      batch=…, lease=limits.verify_lease)`, up to
      `min(batch, floor(verify_threads.available_tokens))`, and copies them concurrently, one
      task per file. §8.6.4's `run(batch)` names no roots, while `claim` requires them (§8.7.3)
      and §18.3 claims nothing on an UNAVAILABLE root, so the available roots arrive from
      `VerifyFiles`.
    - `_verify_one` follows §8.6.4 steps 1–5: `materialize` on `verify_threads` with a 60 s
      heartbeat beside it. A mismatch first confirms the claim by heartbeat, then calls
      `discard_input(input=…)`, then settles RECEIVING (`DIGEST_MISMATCH`).
      `ScratchInputMissingError` settles `SCRATCH_LOST`. `StagingMissingError` aborts the session
      `STAGING_LOST` with `raw.session.aborted`, through `UploadSession.abort(reason=…)`, whose
      reason parameter (default `CLIENT`) lands here. `ENOSPC` and `StorageRootUnavailableError`
      release the claim. A match settles VERIFIED and discards only when `settle_file` returned `True`.
  - New `src/huron/core/raw/maintenance.py` (§8.6.7, §18.3): `MaintenanceDuty`,
    `RawMaintenance(duties, *, batch)` with `run_pass` (each duty isolated in its own `try`) and
    `verify_now`, `RENAME_LEASE_SECONDS = 120`, and:
    - the root-availability helper every storage duty shares (§18.3 "Root availability", §9.8.6
      "Availability"): `READINESS_TIMEOUT_SECONDS = 2.0` (core cannot import the API's constant of
      that name and value) and `available_roots(sweeper, keys) -> tuple[str, ...]`, which probes
      every configured key concurrently, each with `asyncify(sweeper.root_available,
      abandon_on_cancel=True)(key)` under `anyio.fail_after(READINESS_TIMEOUT_SECONDS)`, counts a
      timeout as UNAVAILABLE, and answers the AVAILABLE keys in configuration order;
    - `VerifyFiles(verifier, sweeper, keys)`, whose run calls `available_roots` first and passes
      the answer to `FileVerifier.run(batch, roots=…)`, so `verify_now` probes too. `FinishCommits`
      (M7.16) and every M12 storage duty obtain their roots the same way.
  - `src/huron/core/raw/types.py`: `DutyReport(name, claimed, done, failed)`.
  - `src/huron/core/raw/ports.py`: `VerificationTrigger` (§8.7.4).
  - New `src/huron/applications/api/maintenance.py`: `MaintenanceLoop(*, interval_seconds)`.
    `wake()` never blocks or raises. `running(maintenance)` starts one `raw-maintenance` task. It
    runs a pass at once, then whichever comes first of the wake event (`verify_now`) and the
    interval after the last pass ended (`run_pass`). A wake during a run is served after it, and
    leaving cancels the task and awaits it.
  - `src/huron/applications/api/app.py`: the lifespan builds the loop first with the configured
    cadence (default 30 s) and places it in `RawPorts.trigger`. `async with
    loop.running(runtime.raw.maintenance)` wraps the `yield` after the conformance asserts, inside
    the block that closes the pool (§6.6 steps 6–9).
  - `src/huron/core/raw/runtime.py`: `RawPorts` gains `trigger`; `RawRuntime` builds one
    `FileVerifier(ports.uploads, ports.ledger, ports.work, ports.area, admission, limits=limits)`
    and `RawMaintenance((VerifyFiles(verifier, ports.sweeper, keys),), batch=…)` (batch
    `maintenance_batch`), the configured `keys` being those of `placement.roots`, and exposes
    `maintenance`; `tests/unit/test_authorization_credentials.py` fills `trigger` (the
    "Composition root" rule).
  - Tests:
    - new `tests/unit/test_raw_verifier.py`;
    - new `tests/unit/test_raw_maintenance.py` (`run_pass` order and isolation, `verify_now`,
      `available_roots` and the duty-level root cases below; M12 extends it);
    - new `tests/unit/test_api_maintenance.py` (the loop);
    - `tests/unit/test_execution_model.py`: the L3 case of §22.7 (the successor of the off-loop
      tests M5.3 deleted);
    - new `tests/unit/test_raw_capacity_settings.py` (the successor of the deleted
      `test_api_completion_capacity.py`): through the lifespan, `PROCESS_VERIFIERS` sizes L3,
      `PROCESS_STREAMS` sizes L1, L2 and L10, and `STORAGE_RESERVE_BYTES` reaches every root's
      `CompletionAdmission` and `RawLimits`.
- Design: §8.6.4; §8.6.7; §8.6.8; §8.7.3 (`claim` takes the roots); §18.3 (including "Root
  availability" and the pass-order table); §18.4 duty 2; §18.5 (the root-availability row);
  §9.8.6 ("Availability"); §6.6 steps 6–9; §13.5; §22.7; D-22, D-63, D-94, D-96, D-114, D-171.
- Verification: the plan-wide gate, `uv run pytest -m integration` (lifespan wiring) and
  `npm run test:e2e` (the lifespan now runs the loop; the "Gate" rule). Acceptance:
  - in `test_raw_maintenance.py`: `test_verify_files_skips_an_unavailable_root` (a RECEIVED file
    whose dataset lies on an UNAVAILABLE root is not claimed, while one on an AVAILABLE root is)
    and `test_root_probe_timeout_counts_as_unavailable` (a `root_available` that blocks past the
    bound: that key is left out and the run returns within about the bound);
  - in `test_execution_model.py`: `test_verified_copy_runs_off_the_loop_inside_verify_threads`
    (`FileVerifier`'s `materialize` runs on a worker thread holding an `admission.verify_threads`
    token, never on the event loop);
  - in `test_raw_verifier.py`:
    - `test_matching_copy_verifies_then_discards`;
    - `test_digest_mismatch_discards_input_before_reset`;
    - `test_stale_verifier_never_discards_a_resumed_input` (the heartbeat fails, so nothing is
      discarded, and `discard_input` with the old inode leaves the new input);
    - `test_scratch_lost_resets_the_file`;
    - `test_staging_lost_aborts_the_session`;
    - `test_unavailable_root_or_enospc_records_nothing`;
    - `test_verifier_stops_when_its_session_ends` (the heartbeat is fenced by an OPEN session);
    - `test_claims_never_exceed_free_verify_threads`;
  - in `test_api_maintenance.py`:
    - `test_loop_runs_a_pass_at_start`;
    - `test_wake_serves_verify_now`;
    - `test_wake_during_a_run_is_served_after_it`;
    - `test_exit_cancels_and_awaits_the_running_pass`;
  - in `test_raw_maintenance.py`: `test_a_raising_duty_is_logged_and_the_next_runs`.
- Dependencies: M6.7, M6.9 (the upload store and the roots in `RawPorts`), M7.1, M7.2.
- Status: pending

### M7.4 Chunk claims, finishes and the offset state machine

- Intent: the transactional half of the tus PATCH in core:
  - `describe_file`, the HEAD read model;
  - `begin_chunk`: ownership, state, offset, bounds, the L4 cap, the new epoch and the stream
    lease;
  - `finish_chunk`: renewal plus compare-and-set, waking the verifier when a file becomes
    RECEIVED;
  - `release_chunk`.

  It adds the `FileProgress` rules and the error classes they and `finish_chunk` raise first,
  with their §7 rows, and a Hypothesis state machine over the in-memory ledger.
- Delete: none.
- Create / Modify:
  - `src/huron/core/raw/ingest.py`: `FileProgress.require_open()` and `require_chunk(offset,
    length)`. `require_open` raises `UploadGone` with `{session_id, state, reason}`, the reason
    chosen as §11.5 says. `require_chunk` raises `UploadOffsetConflict` (`upload_offset` = size
    for RECEIVED or VERIFIED files), then `UploadLengthExceeded` (`size`). Each is cyclomatic
    complexity ≤ 4.
  - `src/huron/core/raw/_impl/ingestion.py`: `UploadService` takes `ledger` and `trigger`
    (§8.6.2) and gains:
    - `describe_file(grant, tus_upload_id)`: `progress`, then `require_owner` (`404`), then
      `require_open`;
    - `begin_chunk(grant, tus_upload_id, *, offset, length)`: one `ChunkTransaction` in the
      §11.8 order, `lock_file` → `require_owner` → `require_open` → `require_chunk` →
      `count_streams` → `limits.check_streams` → `open_stream` (`None` answers
      `UploadOffsetConflict`), returning a `ChunkClaim`;
    - `finish_chunk(claim, new_offset)`: one transaction of `renew_session` (`None` answers
      `UploadGone`) and `advance` (`None` answers `UploadSuperseded` and rolls the renewal back).
      `trigger.wake()` runs after the commit when the file became RECEIVED;
    - `release_chunk(claim)`: `close_stream` in its own transaction.

    Each method has cyclomatic complexity ≤ 5 (§11.14).
  - `src/huron/core/raw/errors.py`: `UploadOffsetConflict` (409, `context.upload_offset`),
    `UploadGone` (410, `context.session_id`, `state`, `reason`), `UploadLengthExceeded` (413,
    `context.size`) and `UploadSuperseded` (409; `finish_chunk` raises it first, and
    `write_chunk` reuses it in M7.5), with their `ERROR_CODES` entries.
  - `src/huron/core/raw/runtime.py`: `RawRuntime` passes `ports.ledger` and `ports.trigger` (the
    loop, since M7.3) to `UploadService`; `app.py` needs no change, because `RawPorts` already
    carries both.
  - `design/api.html` §7: the four rows.
  - Tests:
    - `tests/unit/test_raw_services.py` (the chunk half, with a recording trigger stub);
    - new `tests/unit/test_raw_upload_machine.py`: a Hypothesis `RuleBasedStateMachine` over the
      in-memory ledger. Its rules are begin and finish from two writers, a verifier reset
      (`settle_file` to RECEIVING through a claimed item), abort and expiry (a clock advance).
      Its invariants: the offset is monotone except on a reset, only the newest epoch records,
      VERIFIED is final, and the offset never exceeds the size.
- Design: §8.6.2 (chunk methods); §11.5; §11.6 steps 5 and 8; §11.8; §11.9; §17.5; §11.15;
  §14.3; D-28, D-30, D-97, D-99, D-162.
- Verification: the plan-wide gate and `npm run test:e2e` (`RawRuntime`'s composition changes;
  the "Gate" rule). Acceptance, in `test_raw_services.py`:
  - `test_describe_file_is_404_for_another_actor`;
  - `test_describe_file_gone_reasons` (ABORTED with its end reason, EXPIRED for a lapsed OPEN
    session, and `null` for COMMITTING);
  - `test_begin_refuses_a_moved_offset_with_the_stored_offset`;
  - `test_begin_on_a_received_file_reports_its_size`;
  - `test_begin_past_the_size_is_413`;
  - `test_begin_over_the_principal_cap_is_429`;
  - `test_finish_superseded_records_nothing_and_keeps_expiry`;
  - `test_finish_after_abort_is_410`;
  - `test_last_chunk_wakes_the_verifier_once`;
  - `test_finish_clears_last_error`;
  - `test_release_is_a_no_op_after_supersession`;
  - the state machine runs with its default settings and no failure.
- Dependencies: M6.5, M6.8, M7.3.
- Status: pending

### M7.5 Supervised chunk writes and supersession

- Intent: the streaming step of the PATCH in core. The positional write runs on the L2 thread
  pool, supervised so that a newer epoch of the same tus upload ends the older stream at once on
  this process and within `stream_watch` on another (D-155). Each storage outcome maps to its
  problem code.
- Delete: none.
- Create / Modify:
  - `src/huron/core/raw/_impl/ingestion.py`: `UploadService` takes `admission` (§8.6.2).
    - `write_chunk(claim, chunks)` calls
      `asyncify(area.write_chunk, limiter=admission.write_threads)` with
      `reserve=limits.storage_reserve_bytes`. It is one `try` with an `except` per storage
      outcome, each delegating to a module function `_on_<error>(…)` (cyclomatic complexity ≤ 7):
      - `ChunkLengthMismatchError` → `TusBodyIncomplete`;
      - `ScratchInputMissingError` → `reset_offset`, then `UploadOffsetConflict(upload_offset=0)`;
      - `StagingMissingError` → `_on_staging_missing` aborts the session through the D-42 abort
        path in one `UploadStore` transaction (`lock_session`, `UploadSession.abort(reason=
        STAGING_LOST)`, `save_session(source=OPEN)` when it changed, and the `raw.session.aborted`
        audit row with the §14.6 payload `{"dataset_id", "end_reason": "STAGING_LOST"}`), then
        raises `UploadGone`;
      - `StorageRootUnavailableError` → `RawStorageUnavailable`;
      - `OSError` with `ENOSPC` → `InsufficientStorage`; any other `OSError` is re-raised.
    - The private `_supervised_write` enters `admission.writer(claim.tus_upload_id, claim.epoch)`
      and runs the write in a task group beside `_watch_epoch`. The watcher re-reads
      `ledger.writer_epoch` every `limits.stream_watch` and cancels once the epoch moved; a
      failed read is logged and retried next period. Whatever leaves once `scope.cancel_called`
      is true (also the worker's `concurrent.futures.CancelledError`, or an `ExceptionGroup`
      wrapping it) becomes `UploadSuperseded`, and anything else passes unchanged. Both
      functions have cyclomatic complexity ≤ 3.
  - `src/huron/core/raw/errors.py`: `TusBodyIncomplete` (400) and its `ERROR_CODES` entry.
  - `src/huron/core/raw/runtime.py`: `RawRuntime` passes its `admission` (the process
    `UploadAdmission`, since M6.7) to `UploadService`.
  - `design/api.html` §7: the `TUS_BODY_INCOMPLETE` row.
  - Tests:
    - `tests/unit/test_raw_services.py`;
    - `tests/contract/test_raw_upload_ledger.py`.
- Design: §8.6.2 (`write_chunk`, supersession); §11.6 step 6; §11.11 (the mapping table, "through
  the D-42 abort path"); §14.6 (audit rows); §17.3; §17.10; §8.10 (budget); D-42, D-99, D-155,
  D-162.
- Verification: the plan-wide gate; the contract suite on Docker; `npm run test:e2e`
  (`RawRuntime`'s composition changes; the "Gate" rule). Acceptance:
  - `test_superseded_write_releases_admission` (unit, in-memory ledger): a pull that never
    yields, then the epoch moves. The answer is `UploadSuperseded`, the L1 and L2 tokens return,
    and the worker thread ends;
  - `test_newer_writer_on_this_process_cancels_the_older_stream`;
  - one case per mapping row: `test_short_stream_is_tus_body_incomplete`,
    `test_scratch_lost_resets_offset_and_answers_409`, `test_staging_lost_aborts_and_answers_410`
    (the session ABORTED with `end_reason` `STAGING_LOST`, `ended_at` set, and exactly one
    `raw.session.aborted` row whose payload is `{"dataset_id": …, "end_reason": "STAGING_LOST"}`),
    `test_unavailable_root_is_503`, `test_enospc_is_507`;
  - contract `test_superseded_stream_releases_admission_promptly`: two services, each with its
    own `UploadAdmission`, over the two pools, with `stream_watch` 0.2 s and N concurrent PATCH
    flows (L1 gate, begin, write) on one tus upload, some trickling one byte per second. Each
    process holds at most one L1 token for that upload at a time, only one holds one
    cluster-wide one watcher period after the last begin, and every superseded flow answers
    `UploadSuperseded`.
- Dependencies: M6.6, M6.7, M7.4.
- Status: pending

### M7.6 tus headers and the Tus-Resumable middleware

- Intent: the HTTP-shaped half of tus before any tus route exists:
  - the request-header grammar in §11.2's evaluation order;
  - the chunk policy and the constant-time digest check;
  - the pure response-header builders;
  - the path-scoped outermost middleware that stamps `Tus-Resumable` and `Cache-Control:
    no-store` on every tus response, including the router's `404`/`405` and the outermost `500`;
  - the seven tus transport error classes with their §7 rows.
- Delete: none.
- Create / Modify:
  - `src/huron/applications/api/routes/v1/schema/tus.py`, the owner's untracked placeholder, filled
    under its docstring (the design's `schema/raw_tus.py`; §11.2, §11.3, §11.14):
    - `ChunkHeaders`;
    - `TusPatchHeaders.parse(headers)`, composed of `_version`, `_media_type`, `_decimal(name)`
      (for `upload-offset` and `content-length`) and `_checksum`;
    - `ChunkPolicy(max_chunk_bytes).check(length)`, `verify_chunk_digest(headers, digests)` and
      `require_tus_version(headers)`;
    - the builders `discovery_headers(limits)`, `head_headers(progress)` and
      `patch_headers(progress)`: `Upload-Expires` as an IMF-fixdate through
      `email.utils.format_datetime(..., usegmt=True)`, `Upload-Metadata` as `path <b64>,sha256
      <b64>`, and `Huron-Upload-State`. Each unit has cyclomatic complexity ≤ 4.
  - New `src/huron/applications/api/tus.py`: `TusResumableHeaders(app, *, prefix="/api/v1/raw/tus")`,
    pure ASGI with no `BaseHTTPMiddleware`. It wraps `send` and edits `http.response.start`
    through `MutableHeaders`, adding `Tus-Version: 1.0.0` on `412`.
  - `src/huron/applications/api/app.py`: `_HuronFastAPI.build_middleware_stack()` returns
    `TusResumableHeaders(super().build_middleware_stack())` (§11.12, §19.7 Mounting).
  - `src/huron/applications/api/errors.py`: `TusHeaderInvalid` (400, `context.header`),
    `ChecksumRequired` (400), `ChecksumAlgorithmUnsupported` (400), `TusVersionUnsupported`
    (412), `TusContentTypeInvalid` (415), `ChunkTooLarge` (413) and `ChecksumMismatch` (`status_code = 460`).
    Each is raised by name (§19.6 point 3) and listed in `ERROR_CODES`.
  - `design/api.html` §7: the seven rows.
  - Tests:
    - new table-driven `tests/unit/test_raw_tus_headers.py`;
    - `test_tus_resumable_on_404_405_and_500`, in the same module, through `create_app`: an
      unknown path under the prefix (`404`), a test route under the prefix called with another
      method (`405`) and raising (`500`) each carry `Tus-Resumable: 1.0.0` and
      `Cache-Control: no-store`; a `412` also carries `Tus-Version`; a path outside the prefix
      carries neither.
- Design: §11.2; §11.3; §11.11 (transport rows); §11.12; §11.13; §11.14; §19.5 (tus
  exceptions); §19.6 (rows added); D-31, D-97, D-98, D-99.
- Verification: the plan-wide gate. Acceptance:
  - every §11.2 row and the evaluation order, with the first failure winning:
    - a missing or wrong `Tus-Resumable` is `412`;
    - `Content-Type` with parameters is accepted;
    - a missing `Content-Length` is `400 TUS_HEADER_INVALID` naming `content-length`;
    - 20 digits fail, and 19 digits up to `9223372036854775807` pass;
    - no `Upload-Checksum` is `CHECKSUM_REQUIRED`; `md5` is `CHECKSUM_ALGORITHM_UNSUPPORTED`;
    - a wrong-length or unpadded digest is `TUS_HEADER_INVALID` naming `upload-checksum`;
  - `ChunkPolicy` refuses `max + 1`;
  - `verify_chunk_digest` answers `460` for both algorithms;
  - the builders' exact strings (IMF-fixdate in GMT, base64 metadata);
  - `ChecksumMismatch` reaches the wire as status 460 with its problem document, and the error
    contract test passes.
- Dependencies: M6.9.
- Status: pending

### M7.7 tus OPTIONS, HEAD and DELETE routes

- Intent: open the tus resource with its three bodiless operations (discovery, the offset read and
  session-wide termination) over `UploadService.describe_file` and `abort`, so a client can probe,
  resume and cancel before the append route lands in M7.8. HEAD reads PostgreSQL only and never
  renews the session; DELETE aborts the whole session.
- Delete: none.
- Create / Modify:
  - `src/huron/applications/api/routes/v1/endpoints/tus.py`, the owner's untracked placeholder,
    filled under its docstring (the design's `endpoints/raw_tus.py`):
    `router = APIRouter(prefix="/tus", tags=["raw-tus"])`, `TusUploadId`
    (`Annotated[UUID, Path(...)]`) and three `async` handlers with `response_class=Response`,
    each returning a `Response` and declaring only its route-specific statuses with
    `problem_response(...)`, never the router's 401, 403, 404, 422 or 500:
    - `discover(limits: RawSettingsDep)`: `OPTIONS /api/v1/raw/tus` (route 16), `204` with
      `discovery_headers(limits)`; it touches neither PostgreSQL nor storage.
    - `describe(tus_upload_id, request, grant, raw)`: `HEAD /tus/{tus_upload_id}` (route 17):
      `require_tus_version(request.headers)`, then `raw.uploads.describe_file(grant,
      tus_upload_id)` (owner `404`, then `410 UPLOAD_GONE`), `200` with `head_headers(progress)`;
      declares `410` and `412`.
    - `terminate(...)`: `DELETE /tus/{tus_upload_id}` (route 19): `require_tus_version`,
      `describe_file`, then `raw.uploads.abort(grant, progress.session_id)` (`CLIENT`); `204`;
      declares `409`, `410` and `412`.
    Each handler stays at cyclomatic complexity ≤ 3 (§11.14).
  - `routes/v1/__init__.py`: `raw_routes.include_router(tus.router)` in §19.1's order.
  - `applications/api/dependencies.py`: the handlers take `RawGrantDep`, `RawDep` and
    `RawSettingsDep`; add `RawSettingsDep` (the `RawSettings` of `ApiSettings.raw`) only if the
    limits route of M6.9 did not.
  - `design/api.html` §3 (Raw storage): the rows of routes 16, 17 and 19, and the condensed note on
    the tus exceptions of §19.5 if the section lacks it.
  - Tests:
    - New `tests/unit/test_raw_tus.py`: a TestClient app built as `test_raw_upload_sessions_api.py`
      builds it (in-memory stores, a temporary storage root, `tests/raw_client.py` signing), with a
      fake `OffsetLedger` only where a state cannot be reached through the services; every
      §11.11 row these three routes can answer.
    - `tests/unit/test_api_router_composition.py`: the OpenAPI tag-set test gains `raw-tus` and
      becomes `test_the_openapi_document_carries_sixteen_resource_grained_tags`; the Raw
      composition tests (Raw tag and error set, no body parameter, `raw_grant` and never
      `current_principal`, no redeclared status) cover the three operations. Because the module is
      `endpoints/tus.py`, not `raw_*.py` (deviation 6), the no-redeclaration twin and the Raw-tag
      test name `huron.applications.api.routes.v1.endpoints.tus` explicitly in their module lists,
      and no check selects Raw modules by a `raw_*` pattern alone.
    - `tests/unit/test_execution_model.py`: `discover`, `describe` and `terminate` join
      `EXPECTED_COROUTINE_FUNCTION` as coroutine functions.
- Design: §11.1; §11.3; §11.4; §11.5; §11.7; §11.11; §11.13 (rows 6–9); §19.3 routes 16, 17
  and 19; §19.5 (tus exceptions); §19.7 (tags, composition tests); D-25, D-26, D-27, D-29, D-98.
- Verification:
  - The plan-wide gate; every touched file at 100 % line coverage. A new clone signature from the
    endpoint module goes through §22.5's review and counts against slice 4's budget.
  - Named tests in `test_raw_tus.py`:
    - `test_options_answers_discovery_without_a_store`: `204` with `Tus-Version: 1.0.0`,
      `Tus-Max-Size` equal to `max_file_bytes`, `Tus-Extension: checksum,expiration,termination`,
      `Tus-Checksum-Algorithm: sha256,sha1`, `Tus-Resumable: 1.0.0` and `Cache-Control: no-store`;
      no store method is called.
    - `test_head_reports_the_durable_offset`: `200` with `Upload-Offset`, `Upload-Length`,
      `Upload-Expires` (the IMF-fixdate of `expires_at`), `Upload-Metadata` (`path`, `sha256`) and
      `Huron-Upload-State`; a RECEIVED, a VERIFIED and a zero-byte file report
      `Upload-Offset = Upload-Length`.
    - `test_head_never_renews`: after several HEADs the session's `expires_at` and the file's
      `writer_epoch` are unchanged.
    - `test_another_actors_upload_is_404`: HEAD and DELETE of another actor's upload answer
      `404 NOT_FOUND`, exactly as an unknown id does.
    - `test_gone_upload_410_carries_its_reason` (parametrized): an ABORTED session (its
      `end_reason`), an OPEN session past `expires_at` (`EXPIRED`), COMMITTING and COMMITTED
      (`reason: null`) and a dataset that is not ACTIVE each answer `410 UPLOAD_GONE` with
      `context {session_id, state, reason}`.
    - `test_missing_tus_resumable_is_412_with_tus_version`; `test_malformed_upload_id_is_422`.
    - `test_delete_after_abort_is_410`: the first DELETE answers `204` and the session is ABORTED
      (`CLIENT`); a second DELETE and a HEAD of any upload of that session answer
      `410 {state: "ABORTED", reason: "CLIENT"}`.
    - `test_delete_racing_an_abort_answers_204_twice`, and
      `test_delete_racing_a_freeze_answers_409_then_410` (a fake ledger reports OPEN while the
      stored session is already COMMITTING: `409 UPLOAD_SESSION_CLOSED`, then `410`).
    - `test_tus_bound_header_tamper_is_401`: a HEAD or DELETE whose `Tus-Resumable` differs from the
      signed bound header answers `401 INVALID_CREDENTIAL`.
  - `GET` and `POST` on `/api/v1/raw/tus/{id}` answer `405` with `Tus-Resumable` (M7.6's
    middleware test now also passes against a real tus route).
  - The Execution notes record deviation 6 (the module names and the owner's docstrings).
- Dependencies: M7.4, M7.6.
- Status: pending

### M7.8 tus PATCH and tuspy interop

- Intent: route 18 appends one checksum-proven chunk at the stored offset, whole or not at all,
  streaming the body into the scratch input without buffering it, and every refusal of steps 1–5
  happens before the first body byte is read. A stock tus client (tuspy, sha1 checksums) completes
  an upload through the authority seam a later SDK path will use.
- Delete: none.
- Create / Modify:
  - `src/huron/applications/api/streams.py`: new `body_chunks(request, *, idle_timeout: float,
    deadline_seconds: float) -> Iterator[bytes]` beside `read_capped`. It is a plain function that
    fixes `deadline = anyio.current_time() + deadline_seconds` on the event loop when it is called
    (a generator function would defer that line to the worker thread) and returns the generator.
    Each pull runs `with anyio.fail_after(min(idle_timeout, deadline - anyio.current_time()))`
    around `await body.__anext__()` through the one-chunk-in-flight `syncify` bridge; empty chunks
    are skipped; `TimeoutError` and Starlette's `ClientDisconnect` become the core
    `TusBodyIncomplete`; every other exception, including the cancellation that ends a superseded
    stream (D-155), passes through unconverted. The pull stays at cyclomatic complexity ≤ 4.
  - `routes/v1/schema/tus.py`: `EMPTY_DIGESTS`, the `ChunkDigests` of empty input.
  - `routes/v1/endpoints/tus.py`: `append` (route 18,
    `@router.patch("/{tus_upload_id}", status_code=204, response_class=Response, ...)`), declaring
    `400`, `409`, `410`, `412`, `413`, `415`, `429`, `460`, `503` and `507`, and documenting the
    `application/offset+octet-stream` body as `{type: string, format: binary}` through
    `openapi_extra`. It composes exactly as §11.6 shows: `TusPatchHeaders.parse`,
    `grant.require_body_digest`, `ChunkPolicy(limits.max_chunk_bytes).check`, then
    `_empty_patch` for `Content-Length: 0` (`describe_file`, the offset comparison
    (`409 UPLOAD_OFFSET_CONFLICT`), `verify_chunk_digest(headers, EMPTY_DIGESTS)`; no L1 token, no
    epoch bump, no renewal) or `_append_chunk` (`raw.admission.stream()`, `begin_chunk`,
    `write_chunk(claim, body())`, `verify_chunk_digest`, `finish_chunk`, and a `finally` that runs
    `release_chunk` in a shielded cancel scope when the finish did not complete, logging and
    suppressing its own failure); `_body(request, limits)` builds `body_chunks` with
    `body_idle_seconds` and `chunk_deadline_seconds`; the answer is `204` with
    `patch_headers(progress)`. Units within §11.14's budgets.
  - No error class is added: `ChecksumMismatch` (460) and its §7 row landed with their first
    raiser, `verify_chunk_digest`, among M7.6's tus transport classes (§19.6 landing rule), and
    the core classes come from M7.4 and M7.5; this route makes them reachable over HTTP, with the
    `status_code = 460` reaching the wire unchanged through `domain_error`.
  - `pyproject.toml`: `"tuspy==1.1.0"` in the `dev` dependency group (`uv add --dev tuspy==1.1.0`;
    the regenerated `uv.lock` is not counted in the task size).
  - `design/api.html` §3: the route 18 row.
  - Tests:
    - `tests/unit/test_raw_tus.py`: every §11.11 row route 18 can answer, including each §11.2
      header refusal through the route; direct `body_chunks` cases; a fake `RawAuthority`
      installed as `ApiRuntime.raw_authority` that returns grants with `body_sha256=None` (§12.12).
    - New `tests/integration/test_raw_tus_interop.py` (marker `integration`): PostgreSQL from
      testcontainers at `upgrade head`, one temporary storage root, `create_app` served by uvicorn on
      a free port in a background thread, and a test `RawAuthority` that maps a fixed bearer to a
      non-delegated `RawGrant` (`create`, `read`, `write` on one locator, a `catalog_storage` in the
      root, `body_sha256=None`). It creates and registers a dataset and starts a session (routes 1,
      6 and 10) with a three-chunk file and a zero-byte file, then uploads with tuspy's `Uploader`
      (`url` = the absolute `upload_url`, `chunk_size` = `chunk_bytes`, `upload_checksum=True`).
    - `tests/unit/test_execution_model.py`: `append` joins `EXPECTED_COROUTINE_FUNCTION`; the
      module's off-loop tripwire covers the PATCH's `UploadArea.write_chunk` (a worker thread under
      `admission.write_threads`).
- Design: §11.2; §11.6; §11.6.1; §11.10; §11.11; §11.13; §11.15; §12.4; §12.6; §12.12; §19.3
  route 18; §19.5 (tus exceptions); D-28, D-30, D-31, D-33, D-98, D-99, D-155.
- Verification:
  - The plan-wide gate, including the new integration module; every touched file at 100 %;
    `uv run --locked pyscn check src` passes with the updated lockfile.
  - Named tests in `test_raw_tus.py`:
    - `test_patch_refuses_before_reading_body`: `413 CHUNK_TOO_LARGE`, `429 UPLOAD_STREAMS_EXHAUSTED`
      (`Retry-After: 5`) and `503 UPLOAD_CAPACITY_EXHAUSTED` (`Retry-After: 2`, an
      `UploadAdmission(streams=1)` whose token is held) each answer while a recording ASGI
      `receive` was never asked for a body message.
    - `test_patch_records_a_chunk_and_renews_expiry`: `204` with `Upload-Offset` and a later
      `Upload-Expires`; HEAD shows the new offset; the last chunk makes the file RECEIVED and the
      recording `VerificationTrigger` was woken.
    - `test_zero_length_patch_is_read_only`: `204` with the current offset while L1 is exhausted;
      epoch and `expires_at` unchanged; a wrong offset answers `409`, a non-empty digest `460`.
    - `test_checksum_mismatch_keeps_offset`: `460 CHECKSUM_MISMATCH`; HEAD shows the old offset and
      the stream lease is cleared.
    - `test_sha1_checksum_needs_a_non_delegated_grant`: `sha1` under the delegation answers `401`;
      under the fake authority (`body_sha256=None`) the chunk records; a sha256 digest other than
      the signed `body_sha256` answers `401`.
    - `test_offset_conflict_reports_the_stored_offset` (a RECEIVED file reports its size) and
      `test_upload_length_exceeded_is_413` (`context.size`).
    - `test_scratch_lost_resets_offset`: with the scratch input removed at offset > 0 the PATCH
      answers `409 UPLOAD_OFFSET_CONFLICT` with `upload_offset` 0 and the file shows `SCRATCH_LOST`.
    - `test_staging_lost_aborts_only_with_sentinel`: the staging tree removed and the sentinel
      present gives `410 UPLOAD_GONE` and a session ABORTED `STAGING_LOST` with one
      `raw.session.aborted` audit row (`{"dataset_id", "end_reason": "STAGING_LOST"}`); the
      sentinel removed too gives `503 RAW_STORAGE_UNAVAILABLE` (`Retry-After: 60`), the session
      stays OPEN and no audit row is written.
    - `test_enospc_maps_to_507`: a stubbed `statvfs` below the reserve answers
      `507 INSUFFICIENT_STORAGE` (`Retry-After: 60`) with the offset unchanged.
    - `test_body_incomplete_is_400`: a short body, a body idle past `body_idle_seconds` and one
      trickling past `chunk_deadline_seconds` (both shortened) answer `400 TUS_BODY_INCOMPLETE` and
      record nothing.
    - `test_newer_patch_supersedes_an_older_stream`: the older request answers
      `409 UPLOAD_SUPERSEDED` and only the newer chunk records.
    - `test_long_patch_outlives_token`: the delegation's `exp` passes while the body streams, and
      the chunk still records (R7).
    - `test_patch_documents_its_binary_body`: the OpenAPI operation documents the binary body and
      the ten declared statuses, `460` among them.
    - `body_chunks` cases: chunks in order with empty ones skipped; the deadline is fixed when
      `body_chunks` is called; idle, deadline and `ClientDisconnect` become `TusBodyIncomplete`; a
      cancelled pull propagates unconverted.
  - `test_tuspy_uploads_and_resumes_with_sha1_checksums` (`test_raw_tus_interop.py`): a first
    `Uploader` stops after one chunk (`stop_at`); a second resumes from HEAD and finishes; HEAD
    then reports `Upload-Offset = Upload-Length`, and the file reaches VERIFIED once the
    maintenance loop's wake path ran.
- Dependencies: M7.5, M7.7.
- Status: pending

### M7.9 Envelope sealing and fingerprint verification

- Intent: the publication primitives of D-23, ready for M7.10's decision table to compose: install
  the four control documents with `version.json` last; verify the envelope by attributes and
  recorded fingerprints without reading one payload byte; rename it into the catalog location with
  `version.json` as the marker, creating no parent directory (D-169).
- Delete: none.
- Create / Modify:
  - `CrossDeviceCommitError(OSError)` has lived in `huron.schema.storage` (§9.8.1), re-exported by
    `huron.core.rawstore`, since M2.8; `commit.py` keeps raising it from there.
  - `src/huron/core/rawstore/inspection.py`: `verify_envelope(envelope, files:
    Sequence[FileEvidence], documents: Mapping[str, bytes], *, anchor)`:
    - the exact inventory: the four documents, `payload/`, every manifest path and its parent
      directories, and nothing else;
    - each payload file, through an `O_NOFOLLOW` descriptor and `fstat` only: regular, owned by
      the service user, `nlink == 1`, mode `0444`, size and fingerprint
      (`<st_ino>:<st_mtime_ns>`, as `materialize` records it) equal to its `FileEvidence`;
    - each document: the same attribute checks, and bytes equal to `documents`;
    - any disagreement raises `ValueError`.
    This is §9.8.4's `digests=False`. No hashing mode and no `sealed=` mode remain: `FileEvidence`
    carries no digest, and the sealed re-verification is gone (D-23).
  - `src/huron/core/rawstore/commit.py`:
    - new `install_documents(envelope: int, completion: int, documents: Mapping[str, bytes])`
      (publication step 1): each document a `candidate` in the session's `completion/`, installed
      into the envelope by exclusive rename through `materialize.install`, in the order
      `manifest.json`, `metadata.json`, `schema.json`, `version.json`; an existing equal file
      passes (a retry), a different one raises `ValueError` (damage); `documents` must hold exactly
      the four names, else `ValueError` (a caller bug);
    - `commit_envelope(staging, final, root)` (step 4): the marker check reads `version.json`
      where it read `COMMITTED`; it walks to the target's parent with `create=False`, so a missing
      `versions/` propagates `FileNotFoundError` (D-169); the exclusive rename, the fsync of both
      parents, `fchmod(0o555)` and the retry branch that reseals an already published target stay.
  - Tests:
    - `tests/unit/test_rawstore_inspection.py` rewritten to `FileEvidence` and fingerprints;
      fixtures install payload with `materialize` (M7.1) or seal files themselves and record
      `<st_ino>:<st_mtime_ns>`.
    - `tests/unit/test_rawstore_commit.py`: the sealing, document and crash-matrix cases ported
      from `COMMITTED` to `version.json` (fault injection through `tests.unit.support.crash_on` and
      `fsync_log`).
- Design: §9.8.1; §9.8.4 (`publish` steps 1–4, `_reseal`); §9.8.6 (module map); §9.9;
  D-23, D-69, D-93, D-169.
- Verification:
  - The plan-wide gate; every touched file at 100 %. If the removed hashing branch of
    `verify_envelope` lowers the unit total, apply the OD-11 reset and record the counts.
  - Named tests:
    - `test_inspection_never_reads_payload_bytes`: with `os.read` patched to fail on payload
      descriptors, a valid envelope verifies.
    - `test_inspection_refuses_fingerprint_disagreement` (an `os.utime` on a payload file) and
      `test_inspection_refuses_size_disagreement`.
    - `test_inspection_rejects_untrusted_file_inodes` (writable, hard-linked, FIFO, symlink and a
      stubbed foreign owner, for payload files and documents).
    - `test_inspection_rejects_inventory_disagreement` (a missing or extra document, payload file
      or directory) and `test_inspection_rejects_changed_document_bytes`.
    - `test_documents_install_version_json_last` (the rename order is recorded) and
      `test_document_install_retry_passes_equal_and_refuses_different`.
    - `test_commit_envelope_requires_version_json` and `test_commit_envelope_creates_no_parent`.
    - The ported crash matrix: `test_a_crash_in_the_tree_fsync_attempts_no_rename`,
      `test_a_crash_in_the_rename_leaves_staging_intact_and_final_absent`,
      `test_a_crash_in_the_parent_fsync_leaves_the_envelope_published_and_the_retry_silent`,
      `test_commit_envelope_retry_after_the_rename_is_silent_and_reseals_the_root`, and the two
      cross-device cases.
  - `rg -n "COMMITTED" src/huron/core/rawstore tests/unit/test_rawstore_commit.py
    tests/unit/test_rawstore_inspection.py` prints nothing.
- Dependencies: M2.3, M5.7, M6.2 (`FileEvidence`), M7.1 (fingerprints of installed copies).
- Status: pending

### M7.10 The publication decision table

- Intent: `VersionArchive.publish` observes the staged envelope, then the target, and dispatches the
  pair to one row function each. A concurrent or fenced-out publisher, a vanished envelope, an I/O
  error or foreign content never fails a published session; a session's own version and another
  dataset's version are never quarantined; and only positive evidence counts as damage (D-39 as
  amended by D-164 to D-166).
- Delete: none.
- Create / Modify:
  - `src/huron/schema/storage.py`: `PublishOutcome` (StrEnum: `PUBLISHED`, `ALREADY_PUBLISHED`,
    `STAGING_LOST`, `CLAIMED`, `HELD`) and `PublishResult(outcome, quarantined=None, damage=None,
    claimed_by=None)`, `damage` at most 1024 characters.
  - `src/huron/core/rawstore/commit.py`: `publish_version(root: Path, dataset_path: str,
    session_id: UUID, number: int, *, files, documents, confirm: Callable[[str], None]) ->
    PublishResult`:
    - validates `documents` (exactly the four names) and `files` before any observation
      (`ValueError`, a caller bug);
    - observes the envelope (`raw_layout.staging_dir(session_id)` + `/envelope`: PRESENT or
      ABSENT), then the target (`raw_layout.version_dir(dataset_path, number)`): ABSENT, EQUAL,
      CLAIMED (a real directory whose `version.json` parses as JSON and names another
      `dataset_id`), HELD (its `version.json` equals the frozen bytes while another control
      document is missing or differs) or DIFFERENT (positive evidence only: a file, a symlink, an
      entry the service user does not own, or a real directory whose control documents were read,
      or found absent, and differ). Every ABSENT answer, and the ABSENT/ABSENT row, calls `confirm`
      first; any other `OSError` while observing is raised after `confirm`;
    - dispatches to `_publish_new` (M7.9's steps 1–4 with `flush_tree(seal=True)` between
      verification and rename), `_drop_envelope` (envelope into `.huron/trash/<uuid4 hex>`, then
      `_reseal`), `_quarantine` (a Huron-owned `0555` directory made `0755` first, then renamed into
      `.huron/quarantine/<uuid4 hex>`, both parents fsynced; `PermissionError` propagates), then
      `_publish_new` for PRESENT/DIFFERENT, `_reseal` (both parents fsynced, `0555` on the version
      root), `_refuse_claimed` and `_hold` (nothing moves);
    - after `ENOENT` anywhere in steps 1–4, or `ENOENT` or `EEXIST` from the rename, observes once
      more and dispatches an ABSENT envelope through its row; a still PRESENT envelope, or a change
      met during that second dispatch, propagates `FileNotFoundError`;
    - on a `ValueError` from step 1 or 2 observes again, and trashes the envelope with
      `STAGING_LOST` and `damage` only while it is still at its staging name and the target is
      ABSENT or DIFFERENT; any other pair dispatches as above;
    - every other `OSError` in steps 1–4 propagates unchanged after `confirm`, and nothing is
      trashed or quarantined.
    `publish_version` stays at cyclomatic complexity ≤ 4 and each row function at ≤ 6 (§8.10);
    `commit.py` stays at radon grade A.
  - `src/huron/core/rawstore/store.py`: `PosixRawStore.publish(...)`, the per-root call.
  - `src/huron/core/rawstore/roots.py`: `PosixStorageRoots.publish(placement, session_id, number, *,
    files, documents)`: the placement-prefix check before any I/O (`placement_mismatch`), then the
    per-root call with `confirm` bound to the absence confirmation the adapter already applies (the
    sentinel and its `root_id` re-read, the nearest existing ancestor on the `.huron/staging`
    device; a mismatch marks the root UNAVAILABLE, or refuses this call with `cross_device`);
    `CrossDeviceCommitError` or `EXDEV` becomes `StorageRootUnavailableError(root, "cross_device")`
    without changing the root's recorded state.
  - `src/huron/core/raw/ports.py`: declare `VersionArchive.publish` with §9.8.4's signature.
  - Tests: the decision table in `tests/unit/test_rawstore_commit.py` on real temporary roots,
    with another driver's rename injected at named points (monkeypatched observation helpers or
    `crash_on`); the dispatch cases in `tests/unit/test_rawstore_roots.py`.
- Design: §9.8.1 (`PublishOutcome`, `PublishResult`); §9.8.4 (`publish`); §9.8.6 (every port
  method, availability); §9.9; §18.2 E (E4, E6, E8–E12, E15–E17); D-39, D-95, D-164, D-165,
  D-166, D-174.
- Verification:
  - The plan-wide gate; every touched file at 100 %.
  - Named tests, one per D-39 row and race:
    - `test_publish_new_version` (PRESENT/ABSENT gives `PUBLISHED`, the target sealed `0555`/`0444`
      and byte-equal to the frozen documents) and `test_present_equal_drops_the_envelope` and
      `test_absent_equal_reseals` (`ALREADY_PUBLISHED`).
    - `test_foreign_version_directory_quarantined` (PRESENT/DIFFERENT gives `PUBLISHED` with
      `quarantined`; ABSENT/DIFFERENT gives `STAGING_LOST` with `quarantined`).
    - `test_damaged_envelope_fails_session` (a payload whose fingerprint differs, target ABSENT:
      `STAGING_LOST` with `damage`, envelope in trash).
    - `test_publish_never_quarantines_another_datasets_version` (`CLAIMED` with `claimed_by`,
      nothing moved, envelope kept) and `test_held_target_is_never_quarantined` (`HELD` with
      `damage` naming the document, nothing moved).
    - `test_concurrent_publishers_never_fail_a_published_session` (the other driver's rename
      injected between the observation and step 1, and between step 1 and the step-2 open:
      `ALREADY_PUBLISHED`, envelope never trashed) and `test_lost_rename_race_is_already_published`
      (`ENOENT` from the step-4 rename).
    - `test_io_error_is_not_damage` (`EIO` on a target read and on a step-1 document write: the
      error propagates; nothing trashed or quarantined).
    - `test_eexist_rename_is_observed_again`,
      `test_both_absent_is_staging_lost_only_after_confirmation` (`confirm` raising leaves the
      envelope and target untouched),
      `test_second_storage_change_propagates`, `test_reseal_after_a_crash_between_rename_and_fchmod`,
      `test_quarantine_opens_a_sealed_directory_first`,
      `test_unmovable_foreign_target_raises_permission_error` and
      `test_publish_validates_documents_before_observing`.
    - In `test_rawstore_roots.py`: `test_publish_refuses_a_foreign_placement_prefix` (no I/O),
      `test_publish_exdev_is_cross_device_and_keeps_the_root_available` and
      `test_publish_absence_with_a_missing_sentinel_is_unavailable`.
- Dependencies: M7.9.
- Status: pending

### M7.11 Commit persistence in both stores

- Intent: the persistence of the freeze and record transactions in both stores, with every
  database refusal mapped: a session enters COMMITTING with its frozen commit and a token lease,
  leaves it only under that token, and the record writes the version row with its counter, read
  back by the replay. It lands before the driver (M7.13): `CommitDriver`'s record step calls
  `UploadTransaction.insert_version`, which the PostgreSQL transaction must implement before the
  runtime can compose the driver under mypy, and line coverage needs the contract run of those
  statements in the same task.
- Delete: none.
- Create / Modify:
  - `src/huron/core/raw/ports.py`: declare `UploadTransaction.insert_version(version: Version)`
    and `VersionStore.version(dataset_id, number)`, which M6.3 left to the commit tasks.
  - `src/huron/core/metastore/ingest.py`, both adapters, one rule set:
    - `save_session` into COMMITTING (`source=OPEN`): writes the `FrozenCommit` columns (`number`,
      `version_id`, `version_document`, `committing_at`), `work_token = token` and
      `work_expires_at = now() + lease`; a second COMMITTING session of the dataset raises
      `CommitInProgress` (PostgreSQL: the unique violation of `raw_upload_sessions_one_committing`);
      a dataset that is not ACTIVE raises `DatasetNotActive` (PostgreSQL: the
      `raw_upload_sessions_freeze_guard` refusal, which only a writer that skipped `lock_dataset`
      meets).
    - `save_session` out of COMMITTING (`source=COMMITTING`, `token`): matches only
      `AND work_token = $token`, clears `work_token` and `work_expires_at`, sets `ended_at` on a
      terminal state; `False` when another holder rotated the token.
    - `insert_version`: the in-memory store mirrors `raw_versions_contiguous` (dataset ACTIVE,
      `number = latest_number + 1`, the layout path, born AVAILABLE, matching the session's frozen
      commit); PostgreSQL inserts and lets the trigger decide. Its refusals, and the deferred
      `raw_versions_counted` and `raw_datasets_latest_recorded` refusals that surface at `COMMIT`,
      raise `RuntimeError` naming the rule: a caller bug, `500` (D-176). The in-memory store
      applies the deferred rules when its transaction commits.
    - New `PostgresVersionStore` and `InMemoryVersionStore` with `version(dataset_id, number)`
      (`ResourceNotFound`), the row mapper in `core/metastore/rows.py`; the in-memory store sees
      the rows the in-memory `insert_version` writes.
    - `bump_dataset(latest=True)` (M6.4) is used unchanged; confirm it moves `latest_number` and
      `etag` by exactly one under the dataset row lock.
  - `CommitInProgress` (409, `retry_after = 5`) and its §7 row exist since M4.2; the adapters
    raise it here.
  - Tests:
    - `tests/raw_store_contract.py`, shared scenarios run by `test_raw_stores_memory.py` and
      `tests/contract/test_raw_stores_postgres.py`: `scenario_commit_freeze_record_replay` (freeze,
      then record: COMMITTED, one version row, `latest_number` 1, `etag` + 1, and `version(...)`
      returns the row with the frozen bytes); `scenario_second_committing_session_refused`;
      `scenario_leaving_committing_needs_the_token` (a stale token changes nothing);
      `scenario_failed_commit_records_no_version` (COMMITTING → FAILED leaves `latest_number`).
    - `tests/contract/test_raw_stores_postgres.py`, PostgreSQL only:
      `test_freeze_on_a_dataset_that_is_not_active_is_refused` (the dataset ARCHIVED by SQL; the
      freeze skips `lock_dataset`), `test_version_without_its_counter_fails_at_commit`,
      `test_counter_without_its_version_fails_at_commit` (nothing persists either way),
      `test_version_out_of_sequence_is_a_caller_bug` (a gap, and a document that does not match
      the frozen commit) and `test_concurrent_freezes_leave_one_committing_session` (two pools).
- Design: §8.7.1; §8.7.2 (`UploadTransaction`, `VersionStore`); §8.7.5; §10.6 (trigger rules and
  their contract proofs); §10.7; §13.6 (freeze guards, record transaction); §14.5; §22.3; §22.4;
  D-37, D-43, D-45, D-154, D-167, D-176.
- Verification:
  - The plan-wide gate; `core/metastore/ingest.py` and `rows.py` at 100 % over
    `uv run pytest -m "unit or contract" --cov=src/huron --cov-report=term-missing
    --cov-fail-under=0`, every other touched file at 100 % in the unit run.
  - OD-12 O-8: reset `fail_under` from statement counts when the new adapter statements lower the
    unit total; record before and after counts in Execution notes.
  - The named shared scenarios pass on both stores and the five PostgreSQL cases pass on
    `postgres:16`; a deferred refusal surfaces as `RuntimeError`, never as a `DomainError`.
  - Slice 4's clone budget applies to new adapter signatures (§22.5).
- Dependencies: M6.3, M6.4.
- Status: pending

### M7.12 Commit decisions and the version document

- Intent: the pure half of commit, split from the driver so that each task fits one
  implementation pass: the session's commit decisions, which M6.2 left to the commit, and
  `VersionDocument.compose`, which M2.3 left to the freeze. `freeze` is the first raiser of
  `VERIFICATION_PENDING` and `LATEST_VERSION_CHANGED`, so their classes and §7 rows land here
  (§19.6 "Landing"). The driver that calls these decisions, `UploadService.commit` and the wiring
  follow in M7.13.
- Delete: none.
- Create / Modify (load `oop-design`):
  - `src/huron/core/raw/documents.py`: `VersionDocument.compose(session, *, number, version_id,
    schema, subject, committed_at)` per §8.5 and §9.6.1: `dataset_id`, `session_id`,
    `manifest_sha256`, `file_count` and `total_bytes` from the session and its manifest;
    `metadata_sha256` of the session's metadata bytes; `schema_ref` built from the pinned
    `SchemaVersion` and its `SchemaSubject` (`subject_id`, the subject's qualified name, `number`,
    `schema_version_id` and the SHA-256 of `schema.json`); `committed_by = session.created_by`
    (commit requires the owner, D-38 step 0).
  - `src/huron/core/raw/ingest.py`: the `UploadSession` decisions of §8.4.2, each within §8.10's
    budget (`CommitStage` exists since M6.2):
    - `lapsed(now)` (OPEN and `expires_at ≤ now`) and `pending()` (the files not VERIFIED);
    - `commit_stage(now)`, the D-38 step 1 table: COMMITTED gives `REPLAY`; ABORTED and FAILED
      raise `UploadSessionClosed` (`context.state`, `context.reason`); COMMITTING gives
      `TAKE_OVER` when `work_expires_at ≤ now` and raises `CommitInProgress` otherwise; OPEN gives
      `FREEZE`;
    - `freeze(dataset, *, expected_latest_number, version_id, schema, subject, committed_at) ->
      FrozenCommit`: §13.6 guards 1 and 3–6 in order (`dataset.require_active()`;
      `VerificationPending(context={"pending": …})`; `LatestVersionChanged(context=
      {"latest_number": …})` when a given `expected_latest_number` differs; `CommitInProgress`
      while `dataset.committing`; `dataset.next_number()`, whose ceiling raises
      `VersionLimitReached`), then `version_document = VersionDocument.compose(...).canonical()`
      and `committing_at = committed_at`. Guard 2, expiry, stays with the driver, which aborts the
      session and commits before raising (§8.6.2).
  - `src/huron/core/raw/errors.py`: `VerificationPending` (409, `retry_after = 2`,
    `context.pending`) and `LatestVersionChanged` (409, `context.latest_number`) in `ERROR_CODES`,
    with their `design/api.html` §7 rows (`Retry-After` 2 and `—`, the §19.6 meanings).
    `VersionLimitReached`, `CommitInProgress` and `UploadSessionClosed` exist since M4.2 and M6.8.
  - Tests:
    - `tests/unit/test_raw_documents.py`: `test_version_document_compose_round_trips` (compose,
      then `canonical()`, then `decode` gives the composed value; from the §9.6.1 golden inputs the
      bytes equal the golden), and a CATALOG subject's qualified name in `schema_ref.subject`;
    - `tests/unit/test_raw_upload_session.py`: `commit_stage` in every state (a live and a lapsed
      lease), `lapsed` at the `expires_at` boundary, `pending`, `test_freeze_guards_run_in_order`
      (each refusal with every earlier guard passing) and `test_freeze_returns_the_frozen_commit`
      (`number = latest_number + 1`, the given `version_id`, `committing_at`, and
      `version_document` equal to the composed bytes).
- Design: §8.4.2 (`lapsed`, `pending`, `commit_stage`, `freeze`); §8.5 (`VersionDocument.compose`);
  §9.6.1; §13.6 (the freeze guards); §19.6 (rows added, "Landing"); §8.10; D-38, D-44, D-69.
- Verification: the plan-wide gate; `documents.py`, `ingest.py` and `errors.py` at 100 %;
  `test_error_contract.py` passes with both rows and
  `test_domain_error_rows_document_their_retry_after` with `VERIFICATION_PENDING` at 2; the
  named tests pass.
- Dependencies: M6.2, M6.8.
- Status: pending

### M7.13 CommitDriver

- Intent: commit end to end in core over the ports M7.11 completed and the decisions M7.12 added:
  replay, takeover or freeze; publication on worker threads under a 30 s heartbeat; record or
  fail fenced by the token; every publication result and storage error turned into findings and
  problem codes; the commit request's authorization in `UploadService.commit`; and the version
  store in the composition root.
- Delete: none (`core/raw/_impl/ingest.py` was removed whole by M5.3 and is re-created here).
- Create / Modify:
  - New `src/huron/core/raw/_impl/ingest.py`: `CommitDriver(uploads, datasets, versions, schemas,
    work, archive, *, limits, clock)` per §8.6.3:
    - `commit(session, dataset, *, expected_latest_number) -> CommitResult`:
      `{REPLAY: _replay, TAKE_OVER: _take_over, FREEZE: _freeze}[session.commit_stage(now)]`, each
      branch at cyclomatic complexity ≤ 3. `_replay` answers from `versions.version(dataset.id,
      number)` before any storage access; `_take_over` claims through `work.claim(FINISH_COMMIT,
      roots=(placement.root,), batch=1, lease=limits.commit_lease, ids=(session.id,))` (none:
      `CommitInProgress`).
    - `_freeze`: one transaction: `lock_dataset`, `lock_session(files=True)`, `tx.now()`; a lapsed
      session is saved ABORTED/`EXPIRED` with its `raw.session.aborted` audit row and
      `UploadSessionClosed` is raised after the commit; otherwise `session.freeze(...)` (guards 1
      and 3–6, `version.json` bytes from `VersionDocument.compose`, `version_id = uuid7()`), then
      `save_session(source=OPEN, token=uuid4(), lease=limits.commit_lease)`.
    - `_drive`: in an `anyio` task group that heartbeats every 30 s (`work.heartbeat(item,
      lease=limits.commit_lease)`; `False` marks the run lost): `CommitIntent.of(...)`, then
      `asyncify(archive.ensure_dataset_root)` and `asyncify(archive.publish)`, neither started
      once the run is lost (D-169); a lost run raises `CommitInProgress` and records nothing.
    - Outcomes: `PUBLISHED` and `ALREADY_PUBLISHED` go to `_record`; `STAGING_LOST` to `_report`,
      then `_fail`; `CLAIMED` and `HELD` to `_report`, the lease released and
      `RawStorageUnavailable`; `StorageRootUnavailableError` → `RawStorageUnavailable` (with
      `cross_device`, the finding `RAW_CROSS_DEVICE_PLACEMENT`); `ENOSPC` →
      `InsufficientStorage`; `PermissionError` and any other `OSError` → `RawStorageUnavailable`,
      logged at ERROR; `FileNotFoundError` (a second storage change) → `CommitInProgress`;
      `DatasetRootOccupiedError` from `ensure_dataset_root` → `500`, logged. Every stop other
      than a lost lease releases the lease first (D-106): `work.heartbeat(item,
      lease=timedelta(0))`, so `work_expires_at = now()` under the token.
    - `_record`: `lock_dataset`, `save_session(COMMITTED, source=COMMITTING, token)` (`False`:
      re-read and answer as `_stage` would), `insert_version(intent.version())`,
      `bump_dataset(latest=True)`, audit `raw.version.committed` as the frozen `committed_by`.
    - `_fail`: `save_session(FAILED, end_reason STAGING_LOST, source=COMMITTING, token)`,
      `raw.session.failed`, then `UploadSessionClosed` (`state` FAILED, `reason` STAGING_LOST).
    - `_report`: §9.8.4's result-to-finding table through `work.report(Finding(...))`, with
      `detail.root` in each and the session id as `subject_id`.
    - `resume(item) -> CommitResult | None`: steps 3–4 from the frozen row (session with files,
      dataset, pinned schema version), for `FinishCommits` (M7.16); `None` when the run was lost
      or the session left COMMITTING.
  - `src/huron/core/raw/types.py`: `CommitResult(session, version)`. The lease is
    `RawLimits.commit_lease` (M6.7).
  - `src/huron/core/raw/_impl/ingestion.py`: `UploadService.commit(grant, session_id, *,
    expected_latest_number) -> CommitResult`: read the session (with files) and its dataset, then
    `require_target(dataset.locator, endpoint=dataset.endpoint)`, `require_owner(created_by)`,
    `require(WRITE)` (§12.11 order), then `CommitDriver.commit`; the constructor gains
    `commits: CommitDriver`.
  - `src/huron/core/raw/runtime.py`: `RawPorts` gains `versions`; `RawRuntime` builds one
    `CommitDriver`, hands it to `UploadService` and keeps it for the duty of M7.16.
  - The version store in the composition root (the "Composition root" rule):
    `src/huron/applications/api/runtime.py`: `ApiStores.raw_versions: VersionStore` beside
    `raw_schemas`; `app.py`: `_postgres_stores` builds `PostgresVersionStore(pool)` and
    `_build_runtime` places it in `RawPorts.versions`; `capabilities.py`: the lifespan asserts the
    PostgreSQL and in-memory version stores' conformance to `VersionStore`;
    `tests/unit/support.py`: `memory_stores()` builds an `InMemoryVersionStore` over the same
    shared in-memory Raw state as the upload store, so the app-level in-memory tests (route 14 in
    M7.15) and the Playwright harness compose `CommitDriver`;
    `tests/unit/test_authorization_credentials.py` fills `RawPorts.versions`.
  - Errors: no new class and no change to `src/huron/core/raw/errors.py` (`VerificationPending`
    and `LatestVersionChanged` landed with `freeze` in M7.12); the driver adds literal raise sites
    where it decides (`CommitInProgress`, `RawStorageUnavailable`, `InsufficientStorage`,
    `UploadSessionClosed`).
  - Tests: new `tests/unit/test_raw_commit_driver.py` (in-memory stores, `PosixStorageRoots` on a
    temporary root, `tests.unit.support.FakeClock`, faults injected into the archive or with
    `crash_on`); `tests/unit/test_raw_services.py` gains the `UploadService.commit` authority cases.
- Design: §8.5; §8.6.2 (`commit`); §8.6.3; §8.7.3 (`claim`, `heartbeat`, `report`, `CommitResult`);
  §8.8; §9.8.4 (the result-to-finding table); §13.6; §18.2 E; D-38, D-40, D-41, D-44, D-106,
  D-164, D-165, D-166, D-167, D-169, D-174.
- Verification:
  - The plan-wide gate; every touched file at 100 %; each `CommitDriver` unit within §8.10's
    budget; slice 4's clone budget for the re-created module (§22.5); `npm run test:e2e` (the
    lifespan, its conformance asserts, `ApiStores` and `memory_stores()` change; the "Gate"
    rule).
  - Named tests in `test_raw_commit_driver.py`:
    - `test_freeze_refuses_in_guard_order` (parametrized: a dataset not ACTIVE `409`/`410`; a lapsed
      session aborted `EXPIRED` and committed before `409 UPLOAD_SESSION_CLOSED`; an unverified file
      `409 VERIFICATION_PENDING` with `context.pending` and `Retry-After: 2`; a stale
      `expected_latest_number` `409 LATEST_VERSION_CHANGED` with `context.latest_number`; another
      COMMITTING session `409 COMMIT_IN_PROGRESS`; number 999999 `409 VERSION_LIMIT_REACHED`).
    - `test_commit_publishes_and_records_once`: `PUBLISHED`, then COMMITTED, one version row,
      `latest_number` + 1, `etag` + 1, one `raw.version.committed` row, the version directory
      sealed.
    - `test_replay_answers_the_recorded_version_without_storage` (the staging tree trashed and the
      root UNAVAILABLE: the same `CommitResult`).
    - `test_live_lease_answers_commit_in_progress` and
      `test_lapsed_lease_is_taken_over_from_the_frozen_bytes`.
    - `test_staging_lost_fails_the_session`, `test_quarantine_is_reported_and_the_version_recorded`
      and `test_damage_is_reported_and_the_session_failed`.
    - `test_claimed_target_releases_the_lease_and_answers_503` (`RAW_ALIASED_VERSION_DIRECTORY`;
      the session stays COMMITTING) and `test_held_target_records_commit_stalled`
      (`RAW_COMMIT_STALLED`, `published_version_differs`).
    - `test_io_error_releases_the_lease_without_damage` (`EIO` gives `503`, `ENOSPC` `507`; the
      session stays COMMITTING with `work_expires_at` at now),
      `test_cross_device_placement_is_reported` and
      `test_second_storage_change_answers_commit_in_progress`.
    - `test_lost_run_starts_no_storage_step` (the token rotates before `_drive`'s storage calls:
      neither `ensure_dataset_root` nor `publish` runs) and
      `test_resume_drives_a_lapsed_commit_to_its_record`.
  - In `test_raw_services.py`: `test_commit_rechecks_write` (R10: a grant without `write` answers
    `403` after the target and owner checks; another owner `404`; another target `404`).
- Dependencies: M7.2, M7.10, M7.11, M7.12.
- Status: pending

### M7.14 Commit contract, crash and numbering evidence

- Intent: prove the commit protocol on PostgreSQL and real storage with the evidence of the deleted
  suites: the frozen intent, replay and lease fencing (`test_commit_intents.py`, which needs the
  driver of M7.13), process death at every publication step (`test_ingest_process_death.py`), and
  gap-free numbering (hierarchy scenarios 10–16). Any adapter defect these expose is fixed here
  with its named test (the "Races" rule, R15).
- Delete: none.
- Create / Modify:
  - New `tests/contract/test_raw_commit.py` (PostgreSQL stores on `postgres:16`, a temporary
    storage root, two pools where two drivers contend):
    - `test_frozen_commit_rebuilds_the_intent_from_the_row`: `CommitIntent.of` over a session read
      back from PostgreSQL equals the freezing driver's intent, and the published `version.json`,
      `manifest.json` and `metadata.json` equal the frozen bytes.
    - `test_replayed_commit_returns_the_recorded_version`: after the record, with the staging tree
      trashed and the root marked UNAVAILABLE, a commit answers the same `CommitResult`.
    - `test_commit_lease_takeover_fences_old_driver`: driver A freezes and stalls before publish;
      the lease is expired by SQL; driver B takes over and records; A's record matches no row, A
      answers `CommitInProgress`, and one version row and one version directory exist.
    - `test_freeze_and_verifier_reset_serialize` (§18.4 duty 2, D-37): the verifier's transaction
      on one pool (`lock_session`, then `settle_file` of the session's last RECEIVED file) and
      `_freeze` on the other contend for the session row lock, in both orders. Verifier first: a
      reset to RECEIVING makes the freeze answer `409 VERIFICATION_PENDING`, and a VERIFIED
      settle lets it freeze. Freeze first: the verifier's transaction finds the session no longer
      OPEN and settles nothing (its reset matches no row). In every order a COMMITTING session
      holds only VERIFIED files.
    - `test_max_files_commit_timing` (R6's integration timing): a session of `MAX_FILES` (10,000)
      zero-byte files, VERIFIED at start, commits; one version row with 10,000 manifest entries is
      recorded, and the test records the freeze, publication and record durations with
      `record_property`.
  - New `tests/contract/test_raw_commit_crash.py`: a child process (`sys.executable -c`, as the
    deleted suite ran one) builds the PostgreSQL stores, `PosixStorageRoots` over the test's root
    and a `CommitDriver`, commits a verified session and exits with `os._exit` at one boundary:
    after the freeze transaction commits; after the first control document is installed in the
    envelope; after the rename and before the record transaction. The parent expires the lease by
    SQL and finishes through `work.claim(FINISH_COMMIT, ...)` and `CommitDriver.resume(item)`, and
    separately through a commit retry.
  - New `tests/contract/test_raw_numbering.py`. Sessions of zero-byte files (VERIFIED at start)
    keep commits fast; the test's `RawLimits` raise `principal_open_sessions` and lower the
    storage reserve.
  - Adapter or driver fixes in `src/` only for a defect a test above exposes, each with that test.
- Design: §10.6 (trigger rules and their contract proofs); §13.6 (takeover); §18.2 E (E3–E6,
  E9, E10, E13); §18.4 duty 2 (the freeze and the verifier serialize); §18.6 rule 7; §22.2;
  §22.3; §22.7 (ported suites); §23.2 R6 (the 10,000-file timing); D-37, D-40, D-43, D-45, D-83,
  D-165, D-167.
- Verification:
  - The plan-wide gate; every touched `src` file at 100 % (adapters over unit and contract).
  - `test_abrupt_commit_death_is_finished_by_takeover` (parametrized over the three boundaries):
    exactly one version row at number N, `latest_number` N, one `versions/<N>` whose control
    documents equal the frozen bytes, the session COMMITTED, and the commit retry answers the same
    version.
  - In `test_raw_numbering.py`:
    - `test_numbers_are_allocated_at_freeze` (many OPEN sessions; numbers follow freeze order, not
      start order; one COMMITTING session per dataset at a time).
    - `test_failed_commit_without_a_row_frees_its_number` (a `STAGING_LOST` failure at N; the next
      commit takes N).
    - `test_deleted_versions_keep_their_numbers` (a version set DELETED by SQL; the next commit
      takes `latest_number + 1`).
    - `test_record_transaction_is_atomic_and_replays` (a fault inside the record transaction leaves
      COMMITTING and nothing recorded; the retry records once).
    - `test_hundred_sequential_commits_number_gap_free` (a forced `STAGING_LOST` every tenth
      attempt).
    - `test_100_concurrent_commits_gap_free`: 100 sessions of one dataset commit concurrently from
      two pools; losers answer `COMMIT_IN_PROGRESS` and retry; numbers 1..100 occur exactly once.
  - Scenario 13's file-ledger fences already live in `test_raw_upload_ledger.py` (M6.5) and
    scenario 15's expiry evidence returns with `ExpireSessions` (M12.1); the Execution notes map
    every ported test to its source.
  - `test_freeze_and_verifier_reset_serialize` passes in both orders.
  - R6's timing: `uv run pytest -m contract -k test_max_files_commit_timing
    --junitxml=<a path outside the repository>` passes, and the Execution notes record its three
    durations from the report's `<property>` elements against the BFF's 300 s window. Above
    300 s the browser first sees a gateway error, then "Another request is finishing this
    commit", which the design accepts up to the wizard's 600 s commit budget; above 600 s the
    task reports R6's decision point to the owner (lower `HURON_RAW__MAX_FILES`, or an
    asynchronous commit), and the test itself asserts no duration.
  - A named race test that fails intermittently is a failure and is never re-run to green
    (the "Races" rule).
- Dependencies: M7.13.
- Status: pending

### M7.15 Commit route and the API crash matrix

- Intent: route 14 answers `200 CommitView` with `Content-Location` on the first call and on every
  replay, with neither `Idempotency-Key` nor `If-Match`, and publication faults met through the
  route converge on one frozen commit (the ported API crash matrix). The `FinishCommits` duty and
  the two-process takeover follow in M7.16.
- Delete: none.
- Create / Modify:
  - New `src/huron/applications/api/routes/v1/schema/raw_versions.py` with `SchemaRef`, `VersionView`
    (§19.4) and a builder from `Version` plus optional `metadata.json` bytes (`schema_ref` from
    `version.descriptor()`): `CommitView` needs `VersionView`, so the module lands here, and M8.3
    adds the list and read rendering.
  - `routes/v1/schema/raw_upload_sessions.py`: `CommitUploadSession` (`expected_latest_number`,
    0..999999 or null) and `CommitView {session, version}` (its legacy namesake left with M5.1),
    built from `CommitResult`, with `version.metadata` from the frozen metadata bytes.
  - `routes/v1/endpoints/raw_upload_sessions.py`: `commit_upload_session` on `router`,
    `POST /upload-sessions/{session_id}/commit` (route 14): the body through a
    `raw_body(CommitUploadSession)` alias with `openapi_extra=json_request_body(...)` (the 64 KiB
    `body_limit`); `raw.uploads.commit(...)`; `200 CommitView` with `Content-Location:
    /api/v1/raw/datasets/{dataset_id}/versions/{number}`; no `Idempotency-Key`, no `If-Match`;
    declares `409`, `410`, `503` and `507`.
  - `design/api.html` §3: the route 14 row (no `Idempotency-Key`, no `If-Match`, the
    `expected_latest_number` precondition, `200` on the first call and on a replay; D-147).
  - Tests:
    - `tests/unit/test_raw_upload_sessions_api.py`: the route 14 cases.
    - `tests/unit/test_raw_authority.py`: route 14 joins
      `test_unauthenticated_oversized_body_refused_before_read`.
    - `tests/unit/test_api_router_composition.py`: route 14 joins the documented-body list of
      `test_raw_routes_declare_no_body_parameter`; `tests/unit/test_execution_model.py`:
      `commit_upload_session`, and `test_commit_publication_runs_off_the_loop` (through route 14,
      the commit's `ensure_dataset_root` and `publish` run on worker threads, never on the event
      loop: §22.7, the successor of the commit off-loop test M5.3 deleted).
    - New `tests/unit/test_raw_commit_crash_matrix.py`, ported from the deleted
      `test_api_ingest_crash_matrix.py`: through route 14 with in-memory stores and a temporary
      root, faults injected with `tests.unit.support.crash_on`.
- Design: §13.6; §18.2 E (E1–E4, E6, E12, E16); §19.3 route 14; §19.4 (`CommitUploadSession`,
  `CommitView`, `VersionView`, `SchemaRef`); §19.5 (idempotency, entity tags); §22.7 (ported
  suites); D-41, D-44, D-147.
- Verification:
  - The plan-wide gate; every touched file at 100 %.
  - In `test_execution_model.py`: `test_commit_publication_runs_off_the_loop`.
  - In `test_raw_upload_sessions_api.py`: `test_commit_answers_commit_view_and_location` (`200`,
    the `Content-Location` path, `version.metadata` present, `schema_ref` equal to the frozen
    `version.json`'s), `test_commit_replay_is_identical`,
    `test_commit_needs_no_idempotency_key_or_if_match`, the `409` rows (`UPLOAD_SESSION_CLOSED`,
    `COMMIT_IN_PROGRESS` with `Retry-After: 5`, `DATASET_NOT_ACTIVE`, `VERIFICATION_PENDING` with
    `Retry-After: 2` and `context.pending`, `LATEST_VERSION_CHANGED` with `context.latest_number`,
    `VERSION_LIMIT_REACHED`), `410 DATASET_DELETED`, `503` (`Retry-After: 60`) and `507`; a body
    over 64 KiB answers `413 REQUEST_BODY_TOO_LARGE`, an extra member `422`, another owner `404`
    and a grant without `write` `403`.
  - In `test_raw_commit_crash_matrix.py`:
    `test_document_durability_failure_keeps_one_frozen_commit` (parametrized `fsync`, `fchmod` and
    `write` on a control document: `503` or `507`, the session COMMITTING with its lease released,
    then the retry answers `200` with the same version),
    `test_publication_rechecks_after_a_filesystem_race` (`ENOENT` at a step-1 open and `EEXIST` at
    the rename: `200`, one version),
    `test_modified_published_document_holds_the_commit` (`HELD`: `503`, `RAW_COMMIT_STALLED`, the
    session COMMITTING) and `test_takeover_fences_a_driver_after_the_final_rename` (one version
    row, one directory, the fenced driver records nothing).
- Dependencies: M7.8, M7.13.
- Status: pending

### M7.16 FinishCommits and the two-process takeover

- Intent: any replica finishes a commit whose driver died, through the `FinishCommits` duty of the
  maintenance loop, from the frozen bytes and fenced by a rotated token; a takeover that keeps
  failing is reported as `RAW_COMMIT_STALLED`; proven across two processes on PostgreSQL and a real
  root.
- Delete: none.
- Create / Modify:
  - `src/huron/core/raw/maintenance.py`: the `FinishCommits` duty: claims one COMMITTING session
    with a lapsed lease at a time (`work.claim(FINISH_COMMIT, roots=..., batch=1,
    lease=commit_lease)`) on the roots that M7.3's `available_roots(sweeper, keys)` answers at the
    start of its run (a timed-out probe counts as UNAVAILABLE), at most `batch` claims per pass,
    and runs `CommitDriver.resume(item)`. A failed takeover logs at ERROR
    and, once the session has been COMMITTING longer than ten commit leases (from
    `FrozenCommit.committing_at`, on the database clock), records `RAW_COMMIT_STALLED` with
    `detail.reason` = the error class through `work.report` (deduplicated); a raising duty stays
    isolated in `run_pass`.
  - `src/huron/core/raw/runtime.py`: `RawRuntime` adds `FinishCommits` after `VerifyFiles` in D-64
    order, sharing the one `CommitDriver`.
  - Tests:
    - `tests/unit/test_raw_maintenance.py` (created by M7.3): the `FinishCommits` cases.
    - New `tests/integration/test_raw_takeover.py` (marker `integration`).
- Design: §8.6.7 (`FinishCommits`); §13.6 (takeover); §18.3 (claims of the leased duties); §18.4
  duty 3; §18.6 rule 7; §22.2 (two-process takeover); D-40, D-63, D-106, D-165, D-166.
- Verification:
  - The plan-wide gate, including the new integration module; every touched file at 100 %;
    `npm run test:e2e` (`RawRuntime`'s composition changes; the "Gate" rule).
  - In `test_raw_maintenance.py`:
    `test_finish_commits_claims_only_lapsed_sessions_on_available_roots` (a live lease and an
    UNAVAILABLE root are skipped), `test_finish_commits_records_from_the_frozen_bytes`,
    `test_staging_lost_decision_never_races_publisher` (another driver's rename injected between
    the envelope and target observations: the version is recorded, never FAILED) and
    `test_commit_stalled_only_after_ten_commit_leases`.
  - `test_two_process_takeover_records_one_version` (`test_raw_takeover.py`): PostgreSQL from
    testcontainers and one temporary root; a child process serves the app with uvicorn and,
    through a fault hook it installs before serving (as `test_raw_commit_crash.py`'s child does),
    exits with `os._exit` after the publication rename of a commit the parent sent over HTTP
    (`tests/raw_client.py`); a second app on the same database and root, with the lease expired by
    SQL, finishes it through `FinishCommits`; the parent's commit retry answers `200` with that
    version; one version row and one `versions/000001` exist.
- Dependencies: M7.3, M7.13, M7.15.
- Status: pending

## Milestone 8 — Versions, downloads and lifecycle (slice 5)

Goal: read versions back (metadata, manifest, Range downloads through the checked descriptor) and
the dataset and version lifecycle with immediate parking and locator release.

### M8.1 Version reads in rawstore

- Intent: read a published version back through checked descriptors only: control documents as
  exact bytes, and payload files as the very descriptor that was checked, so no path is re-opened
  after the check and a namespace writer cannot swap a symlinked tree into place (D-158).
- Delete: none.
- Create / Modify:
  - `src/huron/schema/storage.py`: `StoredObject(size: int, fd: int)` with `close()` (closes the
    descriptor exactly once); `huron.core.raw.locations` re-exports it (§9.8.1).
  - `src/huron/core/rawstore/store.py`, per root:
    - `open_object(dataset_path, number, name)`: `name` is one of the four document names or a
      manifest path; segments re-checked (no empty, `.` or `..` segment); a descriptor walk from
      the root through the dataset path, `versions` and `<NNNNNN>` with
      `O_DIRECTORY | O_NOFOLLOW`; the file opened `O_RDONLY | O_NOFOLLOW` relative to that walk;
      `fstat` on the open descriptor: regular, owned by the service user, `nlink == 1`, mode
      `0444`, else the descriptor is closed and `ValueError` raised; returns
      `StoredObject(size, fd)`.
    - `read_document(dataset_path, number, name)`: the four document names only; the same walk and
      checks; a file above 16 MiB refused (`ValueError`); returns the exact bytes and closes its
      descriptor.
  - `src/huron/core/rawstore/roots.py`: `PosixStorageRoots.open_object` and `read_document`
    (`placement`, `number`, `name`): the placement-prefix check first; a `FileNotFoundError` is
    raised only after the absence confirmation (sentinel and `root_id`, device), otherwise
    `StorageRootUnavailableError`.
  - `src/huron/core/raw/ports.py`: declare `VersionArchive.open_object` and `read_document`.
  - Tests: new `tests/unit/test_rawstore_open_object.py`; `read_document` cases in
    `tests/unit/test_rawstore_store.py`; dispatch cases in `tests/unit/test_rawstore_roots.py`.
- Design: §9.7 (9.7.1–9.7.2); §9.8.1 (`StoredObject`); §9.8.4 (`open_object`, `read_document`);
  §9.8.6; §9.9; D-95, D-158.
- Verification:
  - The plan-wide gate; every touched file at 100 %.
  - Named tests:
    - `test_open_object_returns_the_checked_descriptor` (reading it yields the version file's
      bytes; `StoredObject.size` equals the file size).
    - `test_open_object_refuses_untrusted_inodes` (parametrized: a symlink at the dataset
      directory, at `versions`, at the number directory and at the file; a FIFO; a second hard
      link; a stubbed foreign owner; a mode other than `0444`): `ValueError`, and the descriptor
      it opened is closed (an `fstat` on it raises `EBADF`).
    - `test_download_does_not_follow_swapped_dataset_root`: after `open_object` returned, the
      dataset directory is renamed away and a symlinked tree pointing at a `0700` staging file is
      put in its place; the returned descriptor still reads the version file's bytes.
    - `test_read_document_reads_only_the_four_documents` and
      `test_read_document_refuses_more_than_16_mib`.
    - In `test_rawstore_roots.py`: a missing version file with the sentinel present raises
      `FileNotFoundError`; with the sentinel missing, `StorageRootUnavailableError`; a foreign
      placement prefix is refused before any I/O.
- Dependencies: M7.10.
- Status: pending

### M8.2 VersionReadService and VersionFiles

- Intent: the version reads in core: pages from PostgreSQL alone, single versions with their
  metadata checked against the digest `version.json` names, the exact manifest bytes, and payload
  files as checked descriptors. A version or dataset that is DELETED answers `410`, a storage miss
  re-reads PostgreSQL before it answers, and an integrity failure is a logged `500`.
- Delete: none.
- Create / Modify:
  - `src/huron/core/raw/versions.py`: `Version.require_available()`, which M6.2 left to this
    task, its first caller; `VersionRead(version, metadata: bytes)` and
    `FileRead(entry: ManifestEntry, stored: StoredObject)` (public, because route 24 consumes
    `FileRead`).
  - New `src/huron/core/raw/_impl/version_reader.py`: `VersionFiles(archive, *, manifests=64)`:
    - `document(placement, version, name)`: `asyncify(archive.read_document)`, then the SHA-256
      against the digest `version.json` names (`manifest_sha256`, `metadata_sha256`,
      `schema_ref.sha256`); a mismatch, a `ValueError` from the adapter, or a missing file on an
      available root raises `RuntimeError` (`500`), logged;
    - `open(placement, version, path)`: the path's `ManifestEntry` from the decoded manifest
      (`decode_manifest` after the digest check), cached in an LRU of 64 keyed by version id; a
      path not listed raises `ResourceNotFound` (`404`); `asyncify(archive.open_object)`; a size
      that differs from the entry is an integrity failure; the descriptor is closed on that
      refusal, on any other exception and on a cancellation before `FileRead` is returned.
  - New `src/huron/core/raw/_impl/versions.py`: `VersionReadService(versions, datasets, files)`
    with `page`, `latest`, `get`, `manifest` and `open_file` (§8.6.5): `require_target`,
    `require(READ)`, `dataset.require_readable()` (`410 DATASET_DELETED`), and
    `version.require_available()` for single-version reads (`410 VERSION_DELETED`); `page` touches
    PostgreSQL only; `latest` raises `ResourceNotFound` when no version is AVAILABLE. A
    `FileNotFoundError` from storage re-reads the dataset and version rows and answers `410` when
    either is now DELETED, else the integrity `500` (F12); `StorageRootUnavailableError` and
    `PermissionError` become `RawStorageUnavailable`. The constructor grows with `delete` in M8.8.
  - `src/huron/core/raw/runtime.py`: `RawRuntime.versions`; `src/huron/core/raw/__init__.py`
    exports what the API needs.
  - `src/huron/core/raw/ports.py`: `VersionStore.versions(dataset_id, query) -> Window[Version]`
    and `latest(dataset_id) -> Version | None`; both adapters in `core/metastore/ingest.py` (the
    `raw_versions_number` statements of §10.7: keyset `number < $before ORDER BY number DESC`, an
    optional `state` filter, and the highest AVAILABLE number).
  - `src/huron/core/raw/errors.py`: `VersionDeleted` (`410 VERSION_DELETED`) with its §7 row;
    `Version.require_available` is its first raiser.
  - Tests: `tests/unit/test_raw_services.py` (service and `VersionFiles` cases, in-memory stores and
    a temporary root with versions published through the driver); shared scenarios in
    `tests/raw_store_contract.py` (paging and the `state` filter on both stores); a PostgreSQL case
    in `tests/contract/test_raw_stores_postgres.py` for `latest` and `state=AVAILABLE` skipping a
    version set DELETED by SQL.
- Design: §8.6.5 (reads); §8.7.2 (`VersionStore`); §9.7.2; §10.7; §13.7; §18.2 F (F11, F12);
  D-48, D-118, D-158.
- Verification:
  - The plan-wide gate; every touched file at 100 % (`core/metastore/ingest.py` over unit and
    contract); OD-12 O-8 reset if the new PostgreSQL statements lower the unit total, with counts
    recorded.
  - Named tests:
    - `test_page_reads_postgresql_only` (the archive is never called; `metadata` stays unread).
    - `test_get_checks_metadata_against_its_digest` and
      `test_document_digest_mismatch_is_an_integrity_failure` (`RuntimeError`, logged).
    - `test_deleted_dataset_and_version_answer_410`, and
      `test_read_after_park_answers_410_not_500` (the bytes parked and the rows DELETED between the
      row read and the storage read).
    - `test_unlisted_path_is_404`, `test_size_mismatch_closes_the_descriptor` and
      `test_cancelled_open_closes_the_descriptor`.
    - `test_manifest_cache_holds_64_versions` (the 65th version evicts the least recently used).
    - `test_unavailable_root_answers_503_and_pages_still_answer`.
    - The shared scenarios `scenario_version_pages_newest_first` and
      `scenario_version_state_filter` on both stores.
- Dependencies: M7.11, M7.13, M8.1.
- Status: pending

### M8.3 Version read routes 20–23

- Intent: serve version history, the latest version, one version with its metadata and the exact
  manifest bytes under `/api/v1/raw/datasets/{dataset_id}/versions`, completing the OpenAPI tag set
  at its end state of 17.
- Delete: none.
- Create / Modify:
  - New `src/huron/applications/api/routes/v1/endpoints/raw_versions.py`:
    `router = APIRouter(prefix="/datasets/{dataset_id}/versions", tags=["raw-versions"])`, with
    `number: Annotated[int, Path(ge=1, le=999_999)]` and handler names unique across the tier
    (for example `list_raw_versions`, `latest_raw_version`, `get_raw_version`,
    `get_raw_version_manifest`):
    - route 20, `GET ""`: `limit: PageLimit = 50`, `after: PageCursor = None`,
      `state: Literal["AVAILABLE", "DELETED"] | None`; the cursor through `number_cursor_key`;
      `200 Page[VersionView]`, newest first, every `metadata: null`; declares `400`, `410`;
    - route 21, `GET /latest`, declared before `/{number}`: the highest AVAILABLE version with its
      metadata; declares `410`, `503`;
    - route 22, `GET /{number}`: `VersionView` with `metadata` loaded and checked; declares `410`,
      `503`;
    - route 23, `GET /{number}/manifest`: a `Response` of the exact `manifest.json` bytes after the
      digest check, `application/json`, `ETag: "<manifest_sha256>"`, no `Range`; declares `410`,
      `503`.
  - `routes/v1/schema/raw_versions.py` (created in M7.15): the list-item rendering
    (`metadata: null`, DELETED versions as tombstones with `deleted_at`, `purge_after` and
    `purged_at`), which route 25 reuses in M8.9.
  - `routes/v1/__init__.py`: `raw_routes.include_router(raw_versions.router)` in §19.1's order.
  - `design/api.html` §3: the rows of routes 20–23.
  - Tests:
    - New `tests/unit/test_raw_versions_api.py`.
    - `tests/unit/test_api_router_composition.py`: the tag-set test reaches §19.7's 17 tags and
      becomes `test_the_openapi_document_carries_seventeen_resource_grained_tags`; the Raw
      composition tests cover the four operations.
    - `tests/unit/test_execution_model.py`: the four handlers.
- Design: §19.3 routes 20–23; §19.4 (`VersionView`, `SchemaRef`); §19.5 (pagination, entity tags);
  §19.7 (tags); §13.7; D-72, D-127, D-128, D-129.
- Verification:
  - The plan-wide gate; every touched file at 100 %; slice 5's clone budget for the endpoint module.
  - Named tests in `test_raw_versions_api.py`:
    - `test_versions_page_newest_first_with_cursor` (a two-page walk through `next_cursor`; an
      invalid cursor answers `400 INVALID_CURSOR`).
    - `test_state_filter_hides_tombstones` (with `state=AVAILABLE`, DELETED versions are absent).
    - `test_latest_is_declared_before_number` (`/latest` answers, never `422`) and
      `test_latest_404_when_none_is_available`.
    - `test_number_bounds_are_422` (0 and 1000000).
    - `test_get_version_carries_checked_metadata` (and `schema_ref` equal to the stored
      `version.json`'s).
    - `test_manifest_answers_the_exact_bytes_with_etag` (byte-equal to the published
      `manifest.json`; `ETag` is the quoted digest; a `Range` header is ignored).
    - `test_versions_of_a_deleted_dataset_are_410`, `test_deleted_version_reads_are_410` and
      `test_storage_unavailable_is_503_with_retry_after`.
    - Another target answers `404`; a grant without `read` answers `403`.
- Dependencies: M7.15, M8.2.
- Status: pending

### M8.4 Range downloads and the end-to-end flow

- Intent: route 24 serves a version's payload file from the descriptor `open_object` checked, with
  one byte range or the whole file and the descriptor closed on every path; and the composed
  application proves the whole write and read path end to end on PostgreSQL and two real storage
  roots, including a storage-only reader that never calls Huron.
- Delete: none.
- Create / Modify:
  - New `src/huron/applications/api/downloads.py`:
    - `ByteSpan` (frozen: `start`, `length`, `partial`) with the pure
      `ByteSpan.select(headers, *, size, etag)`: no `Range` gives the whole file; one satisfiable
      `bytes=` range (`a-b`, `a-` or `-n`) a partial span; several ranges or a malformed header
      the whole file; an `If-Range` that is not equal to the strong `ETag` the whole file; an
      unsatisfiable single range raises Starlette's `HTTPException(416)` with
      `Content-Range: bytes */<size>`.
    - `DescriptorResponse(stored, *, span, media_type, etag, filename, limiter)`: a Starlette
      `Response` that sends `Content-Type` (the manifest `media_type`), `Content-Length`,
      `ETag: "<sha256>"`, `Accept-Ranges: bytes`, `Content-Disposition: attachment` (RFC 5987
      form for a non-ASCII name, built as Starlette's `FileResponse` builds it) and, for a partial
      span, `206` with `Content-Range`; it reads with `os.pread` in 64 KiB pieces on `limiter`
      (`raw.admission.read_threads`, L10) and closes the descriptor in a `finally`, also when the
      client disconnects. No `Last-Modified`.
  - `routes/v1/endpoints/raw_versions.py`: route 24, `GET /{number}/files/{path:path}` (for
    example `download_raw_version_file`): `raw.versions.open_file(...)`, then `ByteSpan.select`
    (on `416` the descriptor is closed before the exception leaves), then `DescriptorResponse` with
    the manifest path's last segment as `filename`; declares `410`, `416` and `503`.
  - `applications/api/problems.py`: the `FRAMEWORK_STATUSES` comment names route 24's
    `ByteSpan.select` as the `416` source, rendered by `http_error` as the problem document
    `REQUESTED_RANGE_NOT_SATISFIABLE` with the exception's `Content-Range`.
  - `design/api.html` §3: the route 24 row.
  - Tests:
    - New `tests/unit/test_raw_downloads.py`.
    - `tests/unit/test_execution_model.py`: the route 24 handler, and the descriptor reads off the
      loop thread inside `read_threads`.
    - New `tests/integration/test_raw_flow.py` (marker `integration`): PostgreSQL from
      testcontainers at `upgrade head`; two storage roots under the test's base directory, each
      the root of one catalog whose `default-base-location` lies inside it; the app with its
      lifespan (so the maintenance loop verifies files); `tests/raw_client.py` signing each request
      with a `catalog_storage` claim for the create. For each root: create (route 1) → register
      (route 6, REGISTERED) → start (route 10) → tus PATCHes with sha256 checksums (route 18) →
      verification → commit (route 14) → list, latest, get and manifest (routes 20–23) → a full
      and a ranged download (route 24).
- Design: §9.7.3; §13.7; §19.3 route 24; §19.5 (entity tags, downloads); §22.2 (composed
  application); D-129, D-158.
- Verification:
  - The plan-wide gate, including the new integration module; every touched file at 100 %.
  - Named tests in `test_raw_downloads.py`:
    - `test_byte_span_select_truth_table` (every row of the rule above).
    - `test_single_range_answers_206_with_content_range` and
      `test_several_ranges_serve_the_whole_file`.
    - `test_if_range_must_match_the_strong_etag`.
    - `test_unsatisfiable_range_is_a_416_problem_with_content_range`.
    - `test_descriptor_closed_after_success_disconnect_and_416` (each path leaves the descriptor
      closed: an `fstat` on it raises `EBADF`).
    - `test_non_ascii_filename_uses_rfc_5987`.
  - In `test_raw_flow.py`: `test_version_round_trip_on_two_roots` (the downloaded bytes and the
    `206` slice equal the source; each dataset's `base_location` lies under its own root) and
    `test_storage_only_reader_resolves_version` (§9.7.3 steps 1–6 from the stored create
    request's properties and the root directory alone: the newest valid `versions/<NNNNNN>/`,
    `version.json` identity, the three document digests, and each payload size and SHA-256).
- Dependencies: M7.15, M8.3.
- Status: pending

### M8.5 Parking in rawstore

- Intent: move a deleted dataset's versions, or one deleted version, out of the catalog location
  into `.huron/deleted/` by exclusive rename, but only directories whose `version.json` names this
  dataset (and number); foreign entries stay and are reported, and a swapped entry is renamed back
  (D-168, D-178).
- Delete: none.
- Create / Modify:
  - `src/huron/schema/storage.py`: `ParkReport(moved: bool, foreign: tuple[str, ...] = ())` and
    `VersionIdentityError(Exception)` with `claimed_by: str | None`.
  - `src/huron/core/rawstore/sweep.py`:
    - one shared identity step for the parks (and for `purge_parked_version` in M12.5): open the
      version directory `O_DIRECTORY | O_NOFOLLOW`, read its `version.json` through that
      descriptor (at most 64 KiB, parsed as JSON), require this `dataset_id` and number; after the
      rename, `fstat` the moved entry at its new name and compare `(st_dev, st_ino)` with the
      descriptor, renaming it back on a mismatch;
    - `park_dataset(...) -> ParkReport`: lists `versions/` and checks each six-digit entry; when
      every entry is a version of this dataset (and `deleted/<dataset hex>` does not exist yet),
      `versions/` moves whole to `deleted/<dataset hex>`; otherwise each of the dataset's versions
      gets `fchmod(0o755)` and moves to `deleted/<dataset hex>/<NNNNNN>` (that directory created
      `0700` when absent) and every other entry stays and is named in `foreign`; then
      `rmdir <path>/versions` and `rmdir <path>`, ignoring `ENOTEMPTY` and `ENOENT`;
      `ParkReport(moved=False)` when `versions/` is absent or holds none of its versions;
    - `park_version(...) -> bool`: the identity step, `fchmod(0o755)`, then the move to
      `deleted/<dataset hex>.<NNNNNN>`; `False` when the version directory is absent;
      `VersionIdentityError` when it names another dataset or number, or the swap check fails.
    Each function at cyclomatic complexity ≤ 6 (§8.10).
  - `src/huron/core/rawstore/roots.py`: `PosixStorageRoots.park_dataset(placement, dataset_id)` and
    `park_version(placement, dataset_id, number)`: the placement-prefix check, then the sweep
    function; a `False` or `moved=False` answer is returned only after the absence confirmation
    (sentinel, `root_id`, device); `EXDEV` becomes `StorageRootUnavailableError(root,
    "cross_device")` without changing the root's state.
  - `src/huron/core/raw/ports.py`: declare `StorageSweeper.park_dataset` and `park_version`.
  - Tests: `tests/unit/test_rawstore_sweep.py` on real temporary roots, and the dispatch cases in
    `tests/unit/test_rawstore_roots.py`.
- Design: §9.8.1 (`ParkReport`, `VersionIdentityError`); §9.8.5 (`park_dataset`, `park_version`,
  the identity check, why the parks change a mode); §9.8.6; §9.9; D-19, D-168, D-174, D-178.
- Verification:
  - The plan-wide gate; every touched file at 100 %.
  - Named tests:
    - `test_dataset_park_moves_versions_whole` (all entries this dataset's; `versions/` and the
      empty dataset directory gone).
    - `test_dataset_park_leaves_foreign_entries` (a `versions` table's files and a non-version name
      stay; the dataset's versions move to `deleted/<hex>/<NNNNNN>`; `foreign` lists the rest;
      `versions/` and the dataset directory stay).
    - `test_dataset_park_after_a_crash_finishes_the_rmdirs` and
      `test_dataset_park_continues_per_entry_after_an_earlier_pass`.
    - `test_version_park_opens_the_sealed_directory_first` (`0755` before the move) and
      `test_version_park_of_an_absent_directory_is_false`.
    - `test_version_park_refuses_another_datasets_version` (another `dataset_id`, another number,
      a missing or unreadable `version.json`: `VersionIdentityError`, nothing moved).
    - `test_park_renames_back_a_swapped_entry` (the entry replaced between the identity read and
      the rename is renamed back and refused).
    - `test_sub_mount_never_counts_as_absence` (from M2.8) covers both parks (a stubbed `st_dev`
      change at a namespace directory turns an absent source into `cross_device`).
    - In `test_rawstore_roots.py`: the placement-prefix refusal, `EXDEV` as `cross_device`, and an
      absence with a missing sentinel raising `StorageRootUnavailableError`.
- Dependencies: M7.10.
- Status: pending

### M8.6 Dataset archive and unarchive

- Intent: archive blocks new versions and aborts the dataset's OPEN sessions; unarchive reverses
  it; both under the row lock and `If-Match`, refusing while a session is COMMITTING, decided in a
  statement issued after the row lock (D-167).
- Delete: none.
- Create / Modify:
  - `src/huron/core/raw/_impl/datasets.py`: `DatasetService.archive` and `unarchive` (`MANAGE`)
    through one private `_transition(grant, dataset_id, decide, reason)`, which also receives the
    `If-Match` value and the permission to check: read the dataset and `require_target`, then
    `require(permission)` (scope before permission); one transaction: `lock_dataset` (its
    `committing` flag), `require_etag(if_match)`, `decide(locked)` (`None` returns the locked row
    unchanged); otherwise `end_open_sessions(id, reason)` when `reason` is given,
    `transition_dataset`, and the audit row (`raw.dataset.archived` with `aborted_sessions`,
    `raw.dataset.unarchived`). Delete reuses `_transition` in M8.7.
  - `src/huron/core/raw/ports.py`: `DatasetTransaction.end_open_sessions(dataset_id, reason) ->
    tuple[UUID, ...]`.
  - `src/huron/core/metastore/raw_datasets.py`, both adapters: `end_open_sessions` (OPEN sessions
    to ABORTED with the reason and `ended_at`, returning their ids, never touching a COMMITTING
    one); `transition_dataset` for ACTIVE ⇄ ARCHIVED; PostgreSQL maps the
    `raw_datasets_commit_guard` refusal to `CommitInProgress` (the in-memory store mirrors it).
  - Tests: `tests/unit/test_raw_services.py`; a shared scenario in `tests/raw_store_contract.py`
    (`scenario_end_open_sessions_spares_committing`); in `tests/contract/test_raw_commit.py`, the
    archive half of `test_archive_and_delete_refused_while_committing`.
- Design: §8.6.1 (`_transition`, archive, unarchive); §8.7.1 (`lock_dataset`); §8.7.2
  (`end_open_sessions`); §13.8; §14.1; §14.5; §18.2 E14 and F (F1–F3); D-46, D-47, D-115, D-167.
- Verification:
  - The plan-wide gate; adapters at 100 % over unit and contract; OD-12 O-8 reset if the new
    PostgreSQL statements lower the unit total.
  - Named tests:
    - `test_archive_aborts_open_sessions` (their state ABORTED, `DATASET_ARCHIVED`; the audit row
      lists their ids; `etag` + 1).
    - `test_archive_and_unarchive_are_idempotent_when_if_match_matches` (ARCHIVED archive and
      ACTIVE unarchive answer the unchanged view).
    - `test_archive_refuses_pending_and_deleted` (`409 DATASET_NOT_ACTIVE`, `410 DATASET_DELETED`)
      and `test_stale_if_match_is_412`.
    - `test_archive_refused_while_committing` (in-memory: `409 COMMIT_IN_PROGRESS`,
      `Retry-After: 5`).
    - `test_archive_and_delete_refused_while_committing` (contract, archive half): a freeze holds
      the dataset row lock and commits while the archive waits for it; the archive answers
      `409 COMMIT_IN_PROGRESS`; the commit then records. Also the trigger backstop: an ARCHIVED
      transition written by SQL that skips the service while a session is COMMITTING is refused
      by `raw_datasets_commit_guard`.
- Dependencies: M7.13, M7.14.
- Status: pending

### M8.7 Dataset delete and locator release

- Intent: delete makes a dataset DELETED, aborts its OPEN sessions and parks its versions out of the
  catalog location at once; the `RELEASED` report then frees the locator for a new dataset that
  numbers from 1. Refused while COMMITTING; idempotent on DELETED; a retried delete parks again
  while `parked_at` is NULL (D-115); foreign entries keep the name blocked and are left to
  `ParkDeleted` (D-178).
- Delete: none.
- Create / Modify:
  - `src/huron/core/raw/_impl/datasets.py`:
    - `DatasetService.delete(grant, dataset_id, *, if_match)` (`DROP`): F4's check before the
      transaction (`asyncify(sweeper.root_available)(placement.root)`; `False` answers
      `503 RAW_STORAGE_UNAVAILABLE` with nothing changed), then `_transition` with
      `RawDataset.delete` and `SessionEndReason.DATASET_DELETED`; `transition_dataset` to DELETED
      stamps `deleted_at`, `purge_after = now() + retention` and the park lease (`work_token`,
      `work_expires_at = now() + RENAME_LEASE_SECONDS`); audit `raw.dataset.deleted` with
      `aborted_sessions`. After the commit, while the row's `parked_at` is NULL (also on an
      idempotent repeat): `asyncify(sweeper.park_dataset)(placement, id)`, then
      `datasets.record_parked(id)` only when the `ParkReport` lists no foreign entry; any storage
      failure is logged and leaves `parked_at` NULL for `ParkDeleted`.
    - `report` gains `RELEASED` (`DROP` after `require_target`): under `lock_dataset`,
      `RawDataset.release()`; `True` runs `release_dataset` (`released_at`, `etag` + 1) and
      `raw.dataset.released`; `False` answers the unchanged view. After the commit,
      `asyncify(sweeper.remove_empty_root)(placement)` runs and its answer is ignored; a failure is
      logged (D-169).
  - `src/huron/core/raw/ports.py`: `DatasetTransaction.release_dataset(dataset)` and
    `DatasetStore.record_parked(dataset_id) -> bool`.
  - `src/huron/core/metastore/raw_datasets.py`, both adapters: `transition_dataset` to DELETED
    with the deletion facts and the park lease (PostgreSQL maps `raw_datasets_commit_guard` to
    `CommitInProgress`, as for archive); `release_dataset` (`WHERE state = 'DELETED' AND
    released_at IS NULL`); `record_parked` (`parked_at = now()` and the work columns cleared on the
    dataset, and, in the same statement through a CTE, on its DELETED versions whose `parked_at`
    is NULL, D-168).
  - `DatasetService` takes the `limits` that M4.6 left to this task, for
    `RawLimits.deleted_retention` (M6.7); `src/huron/core/raw/runtime.py` passes `RawRuntime`'s
    `limits` to it (the "Composition root" rule).
  - Tests: `tests/unit/test_raw_services.py`; `tests/unit/test_raw_maintenance.py`; shared
    scenarios in `tests/raw_store_contract.py`; the delete half of
    `test_archive_and_delete_refused_while_committing` in `tests/contract/test_raw_commit.py`.
- Design: §8.6.1 (delete, `RELEASED`); §8.7.2 (`record_parked`, `release_dataset`); §9.8.5
  (`park_dataset`, `remove_empty_root`); §13.9; §14.1; §15.5; §18.2 F (F2–F8, F14, F15); D-19, D-47,
  D-53, D-115, D-168, D-169, D-178.
- Verification:
  - The plan-wide gate; adapters at 100 % over unit and contract; OD-12 O-8 reset if the new
    PostgreSQL statements lower the unit total.
  - Named tests:
    - `test_delete_parks_at_once` (DELETED, `deleted_at`, `purge_after`, `parked_at`; the dataset
      directory gone; its versions under `.huron/deleted/<dataset hex>`; OPEN sessions ABORTED with
      `DATASET_DELETED`).
    - `test_delete_refused_while_committing` (`409 COMMIT_IN_PROGRESS`, nothing changed).
    - `test_delete_is_idempotent_and_parks_again_while_unparked` and
      `test_delete_with_foreign_entries_leaves_parked_at_null`.
    - `test_delete_storage_failure_is_logged_not_raised` and
      `test_delete_on_an_unavailable_root_is_503_and_changes_nothing`.
    - `test_released_report_frees_the_locator` (`by_target` answers `404`; a create at the same
      locator gets a new id and the same `base_location`),
      `test_released_report_is_unchanged_when_already_released` and `test_released_needs_drop`.
    - `test_late_ensure_never_blocks_name_reuse` (`test_raw_maintenance.py`): a stalled driver's
      `ensure_dataset_root` after the takeover recorded and the dataset was deleted, parked and
      released recreates an empty `versions/`; the `RELEASED` report's `remove_empty_root` removes
      it, and when the report ran first, a create at the locator still claims the root.
    - Shared scenarios on both stores: `scenario_record_parked_stamps_deleted_versions` and
      `scenario_release_dataset_once`.
    - `test_archive_and_delete_refused_while_committing`, delete half: a freeze commits while the
      delete waits for the row lock; the delete answers `409 COMMIT_IN_PROGRESS`; the commit then
      records; the trigger backstop refuses a DELETED transition written by SQL.
- Dependencies: M8.5, M8.6.
- Status: pending

### M8.8 Version delete

- Intent: a version becomes DELETED under the dataset's `If-Match`, keeps its number and row
  forever, and its directory is parked at once, only after its identity is confirmed; an already
  DELETED version answers unchanged (D-48, D-108).
- Delete: none.
- Create / Modify:
  - `src/huron/core/raw/versions.py`: `Version.delete()`, which M6.2 left to this task, its first
    caller.
  - `src/huron/core/raw/_impl/versions.py`: `VersionReadService.delete(grant, dataset_id, number,
    *, if_match) -> Version` (`DROP` after `require_target`); F4's check before the transaction (as
    `DatasetService.delete`); one `VersionStore` transaction: `lock_dataset`, `require_etag`,
    `require_readable` (`410 DATASET_DELETED`), `lock_version` (`404`); when `version.delete()`
    returns `True`, `delete_version(version, actor, retention)` (with the park lease),
    `bump_dataset(latest=False)` (etag only) and `raw.version.deleted`. Then, outside the
    transaction and while the version's `parked_at` is NULL (also on a repeat):
    `asyncify(sweeper.park_version)(placement, dataset_id, number)`; `True` or a confirmed absence
    (`False`) runs `versions.record_parked(version.id)`; `VersionIdentityError` and storage errors
    are logged and record nothing, leaving the version to `ParkDeleted`. The constructor gains
    `sweeper`, `limits` and `clock`.
  - `src/huron/core/raw/ports.py`: `VersionStore.transaction()` with `VersionTransaction`
    (`RawTransaction`, `DatasetRows`, `lock_version`, `delete_version`) and
    `VersionStore.record_parked(version_id) -> bool`.
  - `src/huron/core/metastore/ingest.py`, both adapters: the version transaction, `delete_version`
    (`state = 'DELETED'`, `deleted_by`, `deleted_at`, `purge_after = now() + retention`, the park
    lease; `WHERE state = 'AVAILABLE'`) and `record_parked` (`WHERE state = 'DELETED' AND parked_at
    IS NULL`, work columns cleared).
  - `src/huron/core/raw/runtime.py`: `VersionReadService` built with the sweeper.
  - Tests: `tests/unit/test_raw_services.py`; shared scenarios in `tests/raw_store_contract.py`.
- Design: §8.6.5 (`delete`); §8.7.2 (`VersionStore`, `VersionTransaction`); §9.8.5 (`park_version`);
  §13.9; §14.4; §14.5; §18.2 F (F4, F10, F13); D-48, D-108, D-115, D-168.
- Verification:
  - The plan-wide gate; adapters at 100 % over unit and contract; OD-12 O-8 reset if the new
    PostgreSQL statements lower the unit total.
  - Named tests:
    - `test_version_delete_parks_at_once` (DELETED with `deleted_by`, `deleted_at`, `purge_after`,
      `parked_at`; the directory at `.huron/deleted/<hex>.<NNNNNN>`; dataset `etag` + 1 and
      `latest_number` unchanged; `latest` moves back to the next AVAILABLE number).
    - `test_version_delete_is_idempotent_when_if_match_matches` and `test_stale_if_match_is_412`.
    - `test_version_delete_needs_drop_and_a_live_dataset` (`403` without `drop`; `410` on a DELETED
      dataset; `404` for an unknown number).
    - `test_misidentified_version_directory_is_not_recorded` (`VersionIdentityError` logged;
      `parked_at` stays NULL; nothing moved) and `test_version_delete_on_an_unavailable_root_is_503`.
    - Shared scenarios on both stores: `scenario_delete_version_stamps_the_park_lease` and
      `scenario_record_parked_version_once`; deleted versions keep their numbers
      (`raw_versions_append_only` allows only the deletion facts).
- Dependencies: M8.2, M8.7.
- Status: pending

### M8.9 Lifecycle and version-delete routes

- Intent: expose archive, unarchive, dataset delete, the `RELEASED` registration report and version
  delete under their `If-Match` precondition, and prove the lifecycle end to end through the
  composed application, down to re-creating a released name that numbers from 1.
- Delete: none.
- Create / Modify:
  - `routes/v1/endpoints/raw_datasets.py`: route 7 `POST /{dataset_id}/archive` and route 8
    `POST /{dataset_id}/unarchive` (`IfMatchHeader` through `expected_version()`, a missing or
    malformed header `422`; `200 RawDatasetView` with `ETag`; declare `409`, `410`, `412`); route 9
    `DELETE /{dataset_id}` (`200 RawDatasetView` with `ETag`; declares `409`, `412`, `503`); route 6
    accepts `RELEASED` (`200 RawDatasetView` with `ETag`; `409 REGISTRATION_STATE_CONFLICT` with
    `context.state` for any state it does not match). Handler names unique across the tier (for
    example `archive_raw_dataset`, `unarchive_raw_dataset`, `delete_raw_dataset`).
  - `routes/v1/endpoints/raw_versions.py`: route 25 `DELETE /{number}` (`If-Match` on the dataset
    `etag`; `200 VersionView` without `ETag`; declares `410`, `412`, `503`), for example
    `delete_raw_version`.
  - `design/api.html` §7: `PRECONDITION_FAILED` adds "; on Raw routes the number is the dataset's
    `etag`" (§19.6, the first Raw lifecycle route); §3: the rows of routes 7–9 and 25 and route 6's
    `RELEASED` outcome.
  - Tests:
    - `tests/unit/test_raw_datasets_api.py` and `tests/unit/test_raw_versions_api.py`: lifecycle
      and version-delete cases.
    - `tests/unit/test_execution_model.py`: the new handlers; the Raw composition tests cover the
      new operations.
    - `tests/integration/test_raw_flow.py`: `test_lifecycle_round_trip`.
- Design: §19.3 routes 6 (`RELEASED`), 7–9 and 25; §19.5 (preconditions, entity tags, idempotent
  repeats); §19.6 (`PRECONDITION_FAILED`); §13.8; §13.9; §14.1; §14.4; D-46, D-47, D-48, D-53,
  D-129.
- Verification:
  - The plan-wide gate, including the extended integration module; every touched file at 100 %.
  - Named tests:
    - `test_archive_and_unarchive_routes_carry_etag` (`200`, `ETag` equal to the body's `etag`;
      a repeat with the current `If-Match` answers the unchanged view).
    - `test_lifecycle_routes_require_if_match` (missing or malformed: `422 REQUEST_INVALID`;
      stale: `412 PRECONDITION_FAILED`).
    - `test_archive_while_committing_is_409_with_retry_after` and
      `test_lifecycle_of_a_deleted_dataset_is_410`.
    - `test_delete_route_parks_and_answers_deleted`, and `test_released_report_route` (a `drop`
      grant; a `create`-only grant answers `403`).
    - `test_version_delete_route_answers_the_tombstone_without_etag` and
      `test_deleted_version_download_is_410`.
    - `test_lifecycle_round_trip` (`test_raw_flow.py`): archive, then an open session's PATCH
      answers `410 UPLOAD_GONE`; unarchive; delete a version (its download `410`, `latest` moves
      back); delete the dataset (its bytes parked under `.huron/deleted/`); report `RELEASED`;
      re-create the same locator: a new id, the same `base_location`, and the next commit is
      version 1.
- Dependencies: M8.4, M8.8.
- Status: pending

## Milestone 9 — Web: BFF bridge and registration

Goal: the SvelteKit BFF speaks the one Raw API: six permissions and catalog-storage claims, the
route table and JSON entry, the streamed tus PATCH and downloads, and registration at creation with
the property-standard classification.

### M9.1 BFF permissions and catalog storage

- Intent: the BFF evaluates all six Raw permissions from the §12.11 privilege table at catalog,
  namespace and table level, authorizes catalog-level targets for the schema routes, and reads a
  catalog's storage facts with the user's own Polaris client for dataset creation, signing nothing
  when Polaris refuses.
- Delete: none.
- Create / Modify:
  - `web/src/lib/server/raw-authorization.ts`:
    - `RawPermission` (`'read' | 'write' | 'create' | 'manage' | 'drop' | 'schema'`) and
      `RawPermissions` (`Record<RawPermission, boolean>`, six flags);
    - the privilege sets and grant levels of §12.11: `create` never from a table-level grant,
      `schema` only from a catalog-level grant, the rest at all three levels; `TABLE_WRITE_DATA`
      confers `manage`;
    - `RawCatalogTarget` (`{organization, catalog}`) and `RawBoundCatalog` (`{endpoint, realm,
      catalog, namespace: [], name: null}`); `applies()` admits only catalog grants for a catalog
      target; `rawGrantPermissions(grants, target)` returns all six flags for either target kind;
      `boundRawTarget` binds both kinds; a parser for the catalog-target query form;
    - `requireRawPermissions(client, user, target, required)` gains its catalog branch: the
      organization pin, then `client.catalog(catalog)`, skipping the generic-table and namespace
      probes; it still runs once per browser request and returns all six flags;
    - `CatalogStorageClaim` and `readCatalogStorage(client, target)` (§12.9): `storage_type` from
      `storageConfigInfo.storageType`; `default_base_location` from the catalog property (1–4096
      characters, else `503`); `allowed_locations` verbatim, or `[default_base_location]` when
      empty, more than 64 refused with `422 STORAGE_LOCATION_REFUSED`, `context.reason =
      "invalid_location"`; `namespace_location` from the namespace's `location` property or
      `null`; a Polaris `403` or `404` from either read propagates and nothing is signed;
    - `RawRefusal` (`status`, `code`, `detail`, `context`), the BFF's coded refusal, first thrown
      for the `422` above; M9.2's `rawProblem` renders it.
  - Callers adapted: `raw-api.ts`, `raw-inspection.ts` and `raw-registration.ts` compile against the
    six-flag type; the `requireRawPermissions` fixtures of `raw-api.test.ts` and
    `raw-registration.test.ts` return six flags.
  - `web/src/lib/server/raw-authorization.test.ts`: the truth table and the new cases.
- Design: §12.2 (catalog-level targets, "computed" permissions); §12.9; §12.11 (the privilege
  table); §12.14 (`raw-authorization.test.ts`); §20.2; §20.3; D-34, D-104, D-159.
- Verification:
  - The plan-wide Python gate; from `web/`: `npm run check`, `npm test`, `npm run lint`,
    `npm run build` and `npm run test:e2e`, all passing; no Svelte file changes.
  - Vitest cases in `raw-authorization.test.ts`:
    - `maps every privilege at every grant level to the six permissions` (each §12.11 privilege at
      catalog, namespace and table level against each permission, including `TABLE_WRITE_DATA`
      conferring `manage`, a table-level `TABLE_CREATE` conferring no `create`, and no namespace-
      or table-level grant conferring `schema`; plus the grants `applies()` rejects).
    - `authorizes a catalog-level target without probing tables or namespaces`.
    - `reads catalog storage verbatim`, `falls back to the default base location when
      allowedLocations is empty`, `refuses more than 64 allowed locations as invalid_location` and
      `answers 503 without a default base location`.
    - `signs nothing when Polaris answers 403 or 404`.
- Dependencies: M8.9.
- Status: pending

### M9.2 Delegation signing and the JSON bridge request

- Intent: the BFF signs delegations for the one Raw API (a nullable target, all six permissions,
  `catalog_storage`, and a given checksum digest in place of a body digest) with exactly the bound
  headers the API expects, and its JSON request passes every API answer through verbatim within a
  300 s window.
- Delete: none.
- Create / Modify:
  - `web/src/lib/server/raw-bridge.ts`:
    - `RawDelegation`: `target: RawBoundTarget | RawBoundCatalog | null`, `permissions:
      RawPermissions | null`, `method: 'GET' | 'HEAD' | 'OPTIONS' | 'POST' | 'PATCH' | 'DELETE'`,
      `body: Uint8Array | { sha256: string }`, `headers`, `catalogStorage?`;
    - `signRawDelegation`: signs `target` (`null` allowed), `permissions` (`null` as `[]`, else the
      true flags), `body_sha256` (the SHA-256 of the bytes, or the given digest), and
      `catalog_storage` when present;
    - `boundHeaders(method, path, headers)` mirroring the API's `bound_header_names`: the five tus
      PATCH headers, `tus-resumable` for tus `HEAD` and `DELETE`, none for `OPTIONS`,
      `idempotency-key` and `if-match` for every other request (present ones only); it replaces the
      private `boundHeaders` of `raw-api.ts`;
    - `rawBridgeRequest(request, configuration, fetcher)`: the guard `/api/v1/raw/` (and no `#`),
      `redirect: 'error'`, `signal: AbortSignal.timeout(300_000)`, `Content-Type:
      application/json` and `Content-Length` for a body, the bound headers; every upstream status
      and body returned verbatim, with no `PolarisApiError` mapping; a connect failure, a timeout or
      a refused redirect answers `rawProblem(503, 'DEPENDENCY_UNAVAILABLE', ...)` with
      `Retry-After: 5`;
    - `rawProblem(status, code, detail, options)`: an `application/problem+json` response with
      `type`, `title`, `status`, `code`, `detail` and `context`, `Retry-After` when given, and
      `Tus-Resumable: 1.0.0` with `Cache-Control: no-store` when the given browser or API path is
      `…/api/v1/raw/tus` or below it (D-163); it also renders a `RawRefusal`.
  - Callers adapted: `raw-api.ts` (`forward`) and `raw-inspection.ts` check `response.ok`
    themselves and throw the `PolarisApiError` they threw before. Their `/api/raw-web/` paths, dead
    since M5.1, now stop at the guard; M9.3 rewrites both.
  - `web/src/lib/server/raw-bridge.test.ts`: the cases below replace the raw-web ones.
- Design: §12.3 (BFF side); §12.4; §12.7; §12.8 (problem documents, BFF-originated failures, tus
  headers on BFF answers); §20.2; §20.3.1; D-101, D-103, D-157, D-163.
- Verification:
  - The plan-wide Python gate and the web gate with `npm run test:e2e`.
  - Vitest cases in `raw-bridge.test.ts`: `refuses a path outside /api/v1/raw/`,
    `signs a null target and no permissions as []`, `signs catalog_storage for dataset creation`,
    `signs body_sha256 from a given digest`, `bound headers mirror the API by request shape`
    (a table over PATCH, HEAD, DELETE, OPTIONS and JSON requests), `passes problem documents
    through verbatim`, `answers 503 DEPENDENCY_UNAVAILABLE with Retry-After 5 after 300 s` (fake
    timers), `refuses a redirect with 503`, and `adds tus headers to a BFF problem only on a tus
    path`.
  - `rg -n "raw-web" web/src/lib/server/raw-bridge.ts web/src/lib/server/raw-bridge.test.ts`
    prints nothing.
- Dependencies: M9.1.
- Status: pending

### M9.3 BFF route table and the JSON entry

- Intent: the BFF mirrors the API's route table in one typed `RAW_ROUTES` table: every JSON route
  and the tus `OPTIONS`, `HEAD` and `DELETE` pass-through, each with its authority, signed target
  and body limit, behind `callRaw`, the one server-side signing entry for JSON; `upload_url` and
  `Content-Location` are rewritten for the browser; anything else answers `404`. The streamed
  PATCH, downloads and the hook's early refusals follow in M9.4, and the three composite rows of
  §15.4 become composites in M9.6 (create and delete land here as signed passes).
- Delete (orchestrator, before the pass; the successors are written fresh at the same paths):
  `web/src/lib/server/raw-api.ts`, `web/src/lib/server/raw-api.test.ts`.
- Create / Modify:
  - `web/src/lib/server/raw-api.ts` (successor): `RAW_ROUTES` (method, path pattern, kind, the
    permission the BFF requires or none, the target kind `dataset`, `catalog` or none, and the body
    limit: 16 MiB for session start, 1 MiB for the schema POSTs, 64 KiB for create and commit,
    1 KiB for every other POST, none for `GET`, `HEAD`, `OPTIONS` and `DELETE`); `handleRawApi`
    (route match or `404 NOT_FOUND`; `?organization=` on every request and a validated `?target=`
    on targeted ones; the body read under its limit, `413 REQUEST_TOO_LARGE` before signing;
    only the D-72 query parameters forwarded, rebuilt from validated values); `RawCall`,
    `RawContext` and `callRaw(context, call)` (one `requireRawPermissions` for a targeted call,
    `403 FORBIDDEN` when the required flag is false, `boundRawTarget`, one signed
    `rawBridgeRequest`); the JSON and tus response-header allowlists of §12.8 with
    `Cache-Control: private, no-store` on JSON; the pure rewrites (`files[].upload_url` to
    `/ingestion/api/v1/raw/tus/{id}?organization=<slug>` in every `UploadSessionView` returned,
    commit's `Content-Location` gaining `organization` and `target`, any other shape `503`);
    `POST /datasets` signed with `readCatalogStorage`'s claim; and the BFF-only
    `GET /ingestion/api/targets` (destination browsing through `loadRawTargetBranch`, kept).
    `requestBytes`, `MAX_PART_BYTES`, `registerReceipt`, `forward` and `allowedOperation` do not
    return.
  - `web/src/routes/ingestion/api/[...path]/+server.ts`: exports `GET`, `POST`, `HEAD`, `DELETE` and
    `OPTIONS`; `PUT` goes (`PATCH` arrives in M9.4).
  - `web/src/lib/server/raw-inspection.ts`: its reads go through `callRaw` to
    `/api/v1/raw/datasets/{id}/versions`, `…/versions/{n}` and `…/versions/{n}/manifest`; its
    parsers and result type stay until M10.3 and M11.1 rewrite them.
  - `web/src/lib/server/raw-api.test.ts` (successor): the cases below.
- Design: §12.2; §12.7; §12.8; §19.3 (the route table it mirrors); §20.2; §20.3.1; §21.2 row 2b
  (web operand) and row 15 (`raw-api.ts` symbols); D-102, D-103, D-157, D-163.
- Verification:
  - The plan-wide Python gate and the web gate with `npm run test:e2e`.
  - Vitest cases in `raw-api.test.ts`: `serves every RAW_ROUTES row and answers 404 otherwise`,
    `target-less routes make no Polaris call`, `refuses a targeted route without its permission
    before any upstream call`, `requires a valid target and organization` (`400 REQUEST_INVALID`;
    an organization pin mismatch `404`), `enforces per-route body limits before signing`,
    `callRaw signs exactly one delegation per call`, `rewrites upload_url and Content-Location`
    (and fails closed on another shape), `passes problem documents through`, `forwards tus OPTIONS,
    HEAD and DELETE with their bound header`, and `BFF tus refusals carry Tus-Resumable` (an unknown
    tus route and a `503` on a tus path carry `Tus-Resumable: 1.0.0` and `Cache-Control:
    no-store`; a JSON refusal carries neither).
  - Row 2b's `web/src` operand passes: `rg -n "raw_web|raw-web|RawWebOperations|ExternalCatalog|
    PROVISIONER_SUBJECT|DelegatedBindings" web/src` prints nothing; `rg -n "requestBytes|
    MAX_PART_BYTES|registerReceipt|allowedOperation" web/src` prints nothing.
- Dependencies: M9.2.
- Status: pending

### M9.4 Streamed tus PATCH, downloads and early refusals through the BFF

- Intent: the BFF forwards a tus PATCH as a stream it never buffers, signed with the checksum digest
  instead of a body digest, and streams version-file downloads with unsigned range headers and no
  total timer on the body; its own early refusals on Raw paths become problem documents that carry
  the tus headers on tus paths.
- Delete: none.
- Create / Modify:
  - `web/src/lib/server/raw-bridge.ts`:
    - `TusPatchForwardHeaders`, `RawStreamRequest` and `rawBridgeStream(request, configuration,
      transport)` (§12.5 steps 2–7): signs `{method: 'PATCH', path, body: {sha256:
      checksumSha256}, headers, target: null, permissions: null}`; one `node:http` request with the
      browser's `Content-Length`, exactly the five bound headers and `Authorization`, and
      `signal: AbortSignal.any([request.signal, AbortSignal.timeout(300_000)])`;
      `stream.pipeline(Readable.fromWeb(body), upstream)`; on the response, at most 64 KiB of body
      read and every status from 200 to 599 (`460` included) returned with the tus header
      allowlist; an early answer stops piping and destroys the upstream request; a refused
      connection, a reset before the response or the 300 s timeout answers
      `503 DEPENDENCY_UNAVAILABLE` (`Retry-After: 5`, tus headers).
    - `RawDownloadRequest` and `rawBridgeDownload(request, configuration, fetcher)` (§20.3.4):
      signed as `rawBridgeRequest` signs (`headers: {}`); `Range`, `If-Range` and `If-None-Match`
      forwarded unsigned; the fetch signal `AbortSignal.any([request.signal, headersTimer.signal,
      idle.signal])` with the 300 s timer cleared when the headers arrive; the body passed through a
      `ReadableStream` whose `pull` arms a 60 s idle timer while it waits on the API; `200`, `206`,
      `304`, `416` and problem documents passed through with the download allowlist plus
      `Cache-Control: private, no-store` and `X-Content-Type-Options: nosniff`; a refused redirect,
      a connect failure or the header wait answers `503 DEPENDENCY_UNAVAILABLE`.
  - `web/src/lib/server/raw-api.ts`: `RAW_ROUTES` gains the PATCH row (the Huron session only, no
    Polaris call; §12.5 step 1's pre-checks through `rawProblem` with the browser path:
    `Content-Type` other than `application/offset+octet-stream` `415 TUS_CONTENT_TYPE_INVALID`, a
    `Content-Length` outside `^[0-9]{1,19}$` `400 TUS_HEADER_INVALID` or above `BODY_SIZE_LIMIT`
    `413 CHUNK_TOO_LARGE`, an absent or non-sha256 `Upload-Checksum` `400 CHECKSUM_REQUIRED`, a
    malformed digest `400 TUS_HEADER_INVALID`) and the download row (`read` evaluated once,
    `boundRawTarget`, `rawBridgeDownload` with `event.request.signal`).
  - `web/src/routes/ingestion/api/[...path]/+server.ts`: exports `PATCH`.
  - `web/src/hooks.server.ts`: the early refusals on `/ingestion/api/v1/raw/` paths (signed out
    `401 INVALID_CREDENTIAL`, a cross-origin mutation `403 FORBIDDEN`, a missing `?organization`
    `400 REQUEST_INVALID`, an organization failure with its status) become `rawProblem` documents
    built with the browser path, so tus paths carry `Tus-Resumable` and `Cache-Control: no-store`;
    the `/ingestion/api/uploads` `uploadNotStarted` case is deleted; other `/ingestion/api/` paths
    keep their current answers.
  - Tests: `web/src/lib/server/raw-bridge.test.ts` and `raw-api.test.ts` extended; new
    `web/src/hooks.server.test.ts`.
- Design: §12.4; §12.5; §12.6; §12.8 (forwarded and returned headers, tus headers on BFF answers);
  §12.14 (Vitest); §20.2; §20.3.4; R16 (measured in M10.10); D-32, D-103, D-157, D-163.
- Verification:
  - The plan-wide Python gate and the web gate with `npm run test:e2e`.
  - Vitest in `raw-bridge.test.ts`: `signs body_sha256 from Upload-Checksum`, `streams PATCH
    without buffering` (the fake transport sees the first chunk before the source ends),
    `destroys the upstream request on browser abort`, `answers 503 DEPENDENCY_UNAVAILABLE on
    connect failure`, `passes 460 and tus headers through`, `stops piping on an early answer`,
    `ranged download is signed without range and returns 206` (the claim's `headers` is `{}`; the
    fake fetch sees `Range` and `If-Range`), `a download streaming past 300 s is not aborted`
    (fake timers, one chunk every 30 s for 400 s), `a download whose upstream stalls 60 s is
    aborted` and `a slow reader never trips the idle timer`.
  - Vitest in `raw-api.test.ts`: `refuses PATCH without a sha256 checksum before contacting the
    API` and each other pre-check (all with `Tus-Resumable` and `Cache-Control: no-store`),
    `streams a PATCH without a Polaris call`, and `evaluates read once for a download and forwards
    Range unsigned`.
  - `web/src/hooks.server.test.ts`: the three early refusals on `/ingestion/api/v1/raw/tus/{id}`
    carry `Tus-Resumable: 1.0.0` and `Cache-Control: no-store`, and on a JSON path they do not;
    no answer carries `uploadNotStarted`.
- Dependencies: M9.3.
- Status: pending

### M9.5 Raw table classification and the retired manual registration

- Intent: the BFF classifies Raw tables by their property standard (§15.3), so destination
  browsing offers only Huron-managed standard-2 datasets and the explorer resolves them by
  `huron.raw.dataset-id`; and manual "Register a Raw collection" leaves the product (OD-10 O-4).
  It lands before the registration handshake (M9.6) because `raw-targets.ts`, `raw-inspection.ts`
  and the ingestion page's server load must stop using `managedRawDatasetId` before M9.6 deletes
  it.
- Delete (orchestrator, before the pass): `web/src/lib/server/polaris-raw-actions.ts`.
- Create / Modify:
  - `web/src/lib/server/polaris-raw.ts`: an exported pure classifier (for example
    `rawManagement(table)`) returning `{management: 'managed' | 'unmanaged' | 'unsupported',
    standard, datasetId}` by §15.3's rows (standard `2` with a lowercase UUID id: managed; a decimal
    standard above 2: unsupported; Raw-like without a standard, or anything else: unmanaged);
    `DISPLAY_PROPERTIES` gains the 13 standard-2 `huron.*` keys and loses `huron.raw.service`.
    Hiding `huron.layer` on Raw tables, the layer column and their Playwright test stay with
    M11.4, which owns "Raw rows carry no layer".
  - `web/src/lib/server/raw-targets.ts`: each Raw table's `kind` from the classifier and its
    `datasetId` only when managed, with no Huron call per table; `canCreate` is `create` evaluated
    for the browsed namespace (catalog and namespace grants). `web/src/lib/api/raw-ingestion-types.ts`:
    `RawTargetBranch.datasets[]` gains `kind` and the branch gains `canCreate` (§20.3.3).
  - `web/src/lib/server/raw-inspection.ts`: the dataset id comes from the classifier; the dataset
    is read through `callRaw` under the table's own target first, and a `404` (another locator's
    id, D-9) renders as unmanaged.
  - `web/src/routes/ingestion/+page.server.ts` (it imports `managedRawDatasetId` to preselect the
    `?table=` destination): the page loads that generic table with the user's client, as
    `raw-inspection.ts` does, and passes it to the classifier. A managed table gives
    `initialDatasetId`; a missing table still answers SvelteKit's `404`; an unmanaged or
    unsupported table sets `ingestError` to "This catalog entry is not a Raw dataset managed by
    this Huron service." The wizard keeps receiving `initialDatasetId: string | null`, and M10.5
    replaces this load.
  - `web/src/lib/server/polaris-actions.ts`: `registerRawTable` leaves `POLARIS_ACTION_NAMES` and the
    switch; `web/src/routes/browse/+page.server.ts`: it leaves `allowedActions`.
  - `web/src/lib/design/components/polaris/NamespaceContents.svelte`: the "Register a Raw
    collection" disclosure is removed; the Iceberg registration stays.
  - Tests: `web/src/lib/server/polaris-raw.test.ts` (the `registerRawTable` cases deleted; the
    §15.3 rows and the 13 display keys added); new `web/src/lib/server/raw-targets.test.ts`;
    `web/e2e/dataset-types.test.ts`: "a Writer registers a persistent Raw collection while files and
    revision publication remain explicit" and "Raw registration rejects conflicting processing
    stages before creating a catalog asset" are deleted, `openRegistration` loses its Raw branch,
    and the Reader test's forged-action loop keeps only `registerIcebergTable` (M11.4 retitles it).
- Design: §15.3; §15.6; §20.2; §20.3.3; §20.5.2 (managed, unmanaged and foreign ids); §20.7;
  §21.2 row 15 (`polaris-raw-actions.ts`, `registerRawTable`, the `huron.raw.service` display key,
  the two manual-registration tests); D-9, D-54, D-109; OD-10 O-4.
- Verification:
  - The plan-wide Python gate and the web gate with `npm run test:e2e`; `npx @sveltejs/mcp
    svelte-autofixer web/src/lib/design/components/polaris/NamespaceContents.svelte
    --svelte-version 5` clean; the AGENTS.md visual QA of the namespace view (three widths, both
    themes, keyboard) without the removed block.
  - Vitest: `classifies Raw tables by property standard` (every §15.3 row, including a non-integer
    standard and a standard-2 table with an uppercase or malformed id as unmanaged), `shows the 13
    standard-2 keys and never huron.raw.service`, and in `raw-targets.test.ts` `labels managed,
    unmanaged and unsupported tables without a Huron call` and `derives canCreate from namespace
    grants`.
  - `rg -n "registerRawTable|polaris-raw-actions|Register a Raw collection" web/src web/e2e`
    prints nothing.
  - `rg -n "managedRawDatasetId" web/src` lists only `web/src/lib/server/raw-registration.ts` and
    `raw-registration.test.ts`, which M9.6 replaces.
- Dependencies: M9.3.
- Status: pending

### M9.6 Registration handshake

- Intent: the BFF registers a dataset's Polaris generic table at creation, under the user's own
  principal, by sending the stored standard-2 create request verbatim, and reports `REGISTERED`
  or `CONFLICT`; it repairs, finishes or releases registrations by the §15.4 table, and on delete
  drops only a table it owns (R4), including one created after a released delete (D-179). The
  composite create, registration and delete rows replace M9.3's signed passes.
- Delete (orchestrator, before the pass; the successors are written fresh at the same paths):
  `web/src/lib/server/raw-registration.ts`, `web/src/lib/server/raw-registration.test.ts`.
- Create / Modify:
  - `web/src/lib/server/raw-registration.ts` (successor), each Huron call a fresh `callRaw`:
    - `createRawDataset(context, target, body, idempotencyKey)`: `preflightRawTarget` (the user's
      client loads the Iceberg, Icechunk and generic table of that name; any hit answers
      `409 TARGET_TAKEN` without calling Huron), `requireRawPermissions(..., 'create')`,
      `readCatalogStorage`, `POST /api/v1/raw/datasets` with `catalogStorage` and the browser's
      `Idempotency-Key`, then `registerStoredRequest`; it answers `201 RawDatasetView` (ACTIVE, or
      PENDING after a Polaris failure) or the problem of a failed step.
    - `registerStoredRequest(context, dataset)`: sends `JSON.stringify(create_request)` only when
      its SHA-256 equals `create_request_sha256` (else `503 DEPENDENCY_UNAVAILABLE` and nothing
      created); Polaris `200` reports `REGISTERED`; `409` loads the table: ours reports
      `REGISTERED`, a foreign table or a `404` (an Iceberg or Icechunk name) reports `CONFLICT` and
      answers `409 TARGET_TAKEN`; a `5xx` leaves PENDING without a report. When the `REGISTERED`
      report answers `409 REGISTRATION_STATE_CONFLICT` with `context.state = "DELETED"`, it loads
      the table again: ours and the user holds `drop`, it drops the table and reports `RELEASED`;
      otherwise it answers that problem with the detail "This dataset was deleted while it was
      being registered. A user with drop permission must finish the deletion." (D-179).
    - `reconcileRawRegistration(context, target, datasetId)`: reads `GET …/registration` and loads
      the table, then applies the one §15.4 row that matches (Finish or Repair registration with
      `create`; `CONFLICT`; Finish deletion with `drop`, also on a released tombstone whose table
      is still ours); a `RawDatasetView`, or `409 TARGET_TAKEN` after a discard.
    - `deleteRawDataset(context, target, datasetId, ifMatch)`: `DELETE` with `If-Match`, then the
      load: ours is dropped and `RELEASED` reported, a `404` reports `RELEASED`, a foreign table
      reports `RELEASED` without a drop; the view answers `RELEASED` when the release finished,
      else DELETED with its registration unchanged.
    - `classifyRawTable(loaded, dataset)`: `ours` when the loaded `name`, `format = raw` and
      `huron.raw.dataset-id` all match, `absent` on `404`, else `foreign`; the only place that
      decides a drop.
    - No hidden retries: a Polaris failure ends the composite call and leaves the state the API
      holds. `registerCommittedRawDataset`, `managedRawDatasetId`, `RAW_SERVICE_PROPERTY` and
      `RAW_SERVICE_ID` do not return.
  - `web/src/lib/server/raw-api.ts`: `POST /datasets` dispatches to `createRawDataset`;
    `DELETE /datasets/{id}` to `deleteRawDataset`; the new row `POST /datasets/{id}/registration`
    (body `{}`, 1 KiB; `read`, then `create` or `drop` by the dataset's state) to
    `reconcileRawRegistration`. `TARGET_TAKEN` is answered through `rawProblem`.
  - Tests: `web/src/lib/server/raw-registration.test.ts` (successor); the composite rows in
    `raw-api.test.ts`.
- Design: §13.1; §15.2 (the create request); §15.4; §15.5; §18.2 A (A12–A19) and F (F8, F9);
  §20.3.1; §20.3.2; §21.2 row 15 (registration symbols); §23.1 R4; D-52, D-53, D-107, D-148,
  D-179.
- Verification:
  - The plan-wide Python gate and the web gate with `npm run test:e2e` (the creation scenarios
    arrive with the wizard in M10.5).
  - Vitest in `raw-registration.test.ts`: `create: Polaris 200 reports REGISTERED`, `409 with our
    table reports REGISTERED`, `409 with a foreign or Iceberg table reports CONFLICT and answers
    TARGET_TAKEN`, `5xx leaves PENDING without a report`, `never sends a create request whose
    SHA-256 mismatches`, `preflight answers TARGET_TAKEN without calling Huron`, every §15.4
    reconcile row (table-driven), `drops only its own table` (ours dropped then `RELEASED`; `404`
    `RELEASED`; foreign `RELEASED` without a drop), `drops an own table created after a released
    delete` (a drop holder's create that lands after the delete's `404` load meets
    `409 REGISTRATION_STATE_CONFLICT`, loads, drops and reports `RELEASED`; a `create`-only user
    gets the must-finish-the-deletion problem; the released tombstone's reconcile row drops our
    table), and `signs a fresh delegation per API call`.
  - Vitest in `raw-api.test.ts`: the three composite rows dispatch with the permission the
    dataset's state requires.
  - `rg -n "huron-raw-v1|registerCommittedRawDataset|managedRawDatasetId|RAW_SERVICE" web/src`
    prints nothing.
- Dependencies: M9.1, M9.3, M9.5.
- Status: pending

## Milestone 10 — Web: wizard and browser acceptance

Goal: the part-upload path leaves first; the ingest wizard then creates and registers datasets,
validates metadata against the pinned schema, uploads through tus-js-client 4.3.1 with server-side
resume, commits, and passes the 2 GiB rehearsal (and the 9 GiB gate where capacity exists).

### M10.1 Wizard protocol modules

- Intent: the wizard's protocol logic as plain, DOM-free TypeScript modules that Vitest pins: the
  tus-js-client 4.3.1 options and retry policy, the checksum `httpStack` that sends
  `Upload-Checksum: sha256 <base64>` of the exact chunk, a per-upload hashing worker, the
  localStorage drafts with exactly four members, and the problem texts. No component uses them
  yet; M10.5 to M10.9 do.
- Delete: none.
- Create / Modify:
  - `web/package.json` and `web/package-lock.json`: `"tus-js-client": "4.3.1"` in `dependencies`,
    pinned exactly (`npm install --save-exact tus-js-client@4.3.1`); `hash-wasm` stays.
  - New `web/src/lib/ingestion/tus.ts`: `RETRY_DELAYS` (`[0, 1000, 3000, 5000, 10000, 30000,
    60000]`); `shouldRetry(error, checksumFailures)` (status 0 while `navigator.onLine`; `460` at
    most three times per chunk; `400` only for `TUS_BODY_INCOMPLETE`, read from the problem body;
    never 401, 403, 404, 410, 412, 413 or 415; otherwise 409, 429 and 5xx); `checksumHeader(hex)`;
    `checksumHttpStack(inner, hasher)` wrapping PATCH requests only, hashing the exact Blob before
    `send` (the empty-input digest for an empty body), setting the header before the transfer, and
    sending nothing after an abort during hashing; `uploadOptions(file, session, hooks, hasher)`
    with `uploadUrl`, `endpoint: null`, `chunkSize` from `chunk_bytes` (refused outside 8–64 MiB),
    `retryDelays`, `onShouldRetry`, `onChunkComplete` resetting the 460 counter, `onProgress`,
    `onSuccess`, `onError`, `storeFingerprintForResuming: false`, `removeFingerprintOnSuccess:
    false`, `parallelUploads: 1`, `metadata: {}` and the checksum stack. Its parameters are
    structural (`{upload_url}`, `{chunk_bytes}`), so the view types M10.3 writes satisfy them
    without an import from this task.
  - New `web/src/lib/ingestion/chunk-hash.ts` (`ChunkHasher`: one module Worker per running upload,
    requests `{id, blob}` answered `{id, sha256}`, `dispose()`) and `chunk-hash.worker.ts`
    (computes with the existing `hashBlob` in 4 MiB windows).
  - New `web/src/lib/ingestion/drafts.ts`: the key `huron.raw-upload.v1:<session_id>`, a value of
    exactly `session_id`, `dataset_id`, `expected_latest_number` and `files` (`name`, `size`,
    `lastModified`); read, write, remove and prune by the OPEN session ids; corrupt JSON or
    another member set reads as no draft; every storage access in `try`/`catch`.
  - New `web/src/lib/ingestion/problems.ts`: one sentence per problem code the wizard can receive
    (the §19.6 codes of the dataset, session, commit, tus and version routes, the kept `PATH_*`,
    `PATH_COLLISION`, `FILE_TOO_LARGE`, `TOO_MANY_FILES`, `MANIFEST_MISMATCH`, `EMPTY_VERSION`,
    `VERSION_TOO_LARGE`, `IDEMPOTENCY_KEY_REUSED`, `INVALID_CREDENTIAL`, `FORBIDDEN`, `NOT_FOUND`
    and `REQUEST_INVALID`, and the BFF's `TARGET_TAKEN`, `REQUEST_TOO_LARGE` and
    `DEPENDENCY_UNAVAILABLE`), using `context` where the code defines one, one sentence per
    `STORAGE_LOCATION_REFUSED` reason (with `expected` and `actual`, and the reset-the-namespace
    remedy for `namespace_location_mismatch`); an unknown code falls back to the problem's
    `title`, and nothing outside the problem document is shown.
  - Tests: new `tus.test.ts`, `chunk-hash.test.ts`, `drafts.test.ts` and `problems.test.ts` beside
    their modules.
- Design: §17.7; §20.1 (protocol logic in plain modules); §20.2; §20.4.4; §20.4.5; §20.4.6;
  §20.4.8; §22.6 (Vitest); D-62, D-74, D-113.
- Verification:
  - The plan-wide Python gate and the web gate with `npm run test:e2e`; `npm ci` reproduces the
    lockfile; no Svelte file changes.
  - Vitest: `uploadOptions sets every field` (no `endpoint`, the chunk-size bounds,
    `storeFingerprintForResuming: false`), `shouldRetry truth table` (every §11.11 status plus
    status 0 online and offline), `retries a network error from HEAD` (§12.13: an upload driven
    by `uploadOptions` over a fake `httpStack` whose PATCH fails with status 0 is retried while
    online, and the recorded retry starts with a HEAD before the next PATCH), `resets the 460
    counter on chunk completion`, `sets Upload-Checksum from the exact Blob on PATCH`, `sends the
    empty-input digest on an empty PATCH`
    (`sha256 47DEQpj8HBSa+/TImW+5JCeuQeRkm5NMpJWZG3hSuFU=`), `leaves HEAD and DELETE untouched`,
    `sends nothing after an abort during hashing`, `hashes through a fake Worker` (request and
    answer ids, dispose), `keeps exactly the four draft members`, `ignores corrupt drafts`,
    `tolerates storage exceptions`, `prunes drafts of closed sessions`, `has one sentence per
    problem code and refusal reason` and `falls back to the title for an unknown code`.
- Dependencies: M9.4.
- Status: pending

### M10.2 Retire the part-upload wizard path

- Intent: delete the browser half of the part protocol before its tus successor is built. The
  wizard's replacement spans more than two tasks (M10.3–M10.9), so §21.1 rule 1 deletes the old
  path first, and no transition between the two upload paths is declared. Every function
  removed here has been unreachable since M9.3, whose route table answers `404` for
  `/ingestion/api/uploads…`. The wizard keeps its four steps without an upload action until M10.8.
- Delete (orchestrator `git rm` before the pass):
  - `web/src/lib/ingestion/upload.ts`: its whole content is the part driver (`rawUploadApi`,
    `submitRawUpload`, `discardRawUpload`, `canReleaseRejectedDraft`, `confirmedBytes`,
    `UploadDraft`, `UploadProgress`); M10.7 writes the session driver at this path.
  - `web/src/lib/ingestion/upload.test.ts`. Its cases of the surviving `files.ts` and `hash.ts`
    move first (see below).
  - `web/src/lib/api/raw-ingestion-client.test.ts`, unconditionally: at `9882690` all three of its
    cases drive `beginRawUpload` and the `uploadNotStarted` flag. It also imports the surviving
    `RawApiError`, but only to assert against those cases, so no case survives, and §21.1 rule 2
    forbids leaving an emptied file (Vitest also fails on a file without tests). M10.3 writes its
    successor.
- Create / Modify:
  - New `web/src/lib/ingestion/files.test.ts` and `web/src/lib/ingestion/hash.test.ts`: the cases
    of the deleted `upload.test.ts` (read at the base commit with `git show`) whose subjects
    survive move verbatim: "preserves relative directory paths and accepts equal basenames in
    different folders" and "normalizes Unicode and rejects casefold and byte-length collisions"
    (`sourcePath`, `sourceError`) into `files.test.ts`, and "hashes bounded reads with the same
    SHA-256 as the complete bytes, including empty files" (`hashBlob`, `HASH_CHUNK_BYTES`) into
    `hash.test.ts`, each file keeping the `// @vitest-environment node` directive. They are the
    only Vitest cases of those two modules, and M10.6 changes `sourceError`.
  - `web/src/lib/api/raw-ingestion-client.ts`: delete `beginRawUpload`, `getRawUpload`,
    `uploadRawPart`, `completeRawFile`, `operateRawUpload`, `commitRawUpload`,
    `registerRawUpload` and their parsers `parseRawRegistration`, `parseRawFile`,
    `parseRawSession`, `parseRawReceipt`; `RawApiError` and the private `request()` lose
    `uploadNotStarted`, whose only source (the hook's `/ingestion/api/uploads` case) left in M9.4.
    `browseRawTargets`, `parseRawBranch`, `rawApiPath` and the explorer's revision reads
    (`listRawRevisions`, `parseRawRevision`, `parseRawRevisions`, `parseRawManifest`,
    `rawFileDownloadUrl`) stay until M10.3 and M11.1.
  - `web/src/lib/api/raw-ingestion-types.ts`: delete `RawIngestFile`, `RawRegistration`,
    `RawIngestSession`, `RawCommitReceipt`, `RawRevisionMetadata` and `RawErrorResponse`.
  - `web/src/lib/api/client.ts`, `web/src/lib/api/types.ts`: their export lists drop the same names.
  - Any `web/src/lib/server` module that still imports a deleted parser
    (`rg -n "parseRawFile|parseRawReceipt|parseRawRegistration|parseRawSession" web/src/lib/server`)
    is adapted here; the BFF rewrites `upload_url` on the raw JSON (§12.8) and needs none of them.
  - `web/src/lib/design/components/ingestion/RawIngestWizard.svelte`: remove `upload()`,
    `discard()`, the draft, progress, busy and failure state, `registered`, `pending`, `locked`,
    `terminal`, `canDiscard`, `browseQuery`, the `beforeNavigate`/`beforeunload` guard, the
    progress and completion panels and the footer's upload and abandon buttons, with the imports
    only they used. The Review step keeps its summary; header and step copy stop describing parts,
    registration after commit and same-submission retries. Steps 1–3 stay as they are (M10.5 and
    M10.6 rewrite them).
- Design: §21.1 rules 1–2; §21.2 rows 5 (Web) and 15 (wizard symbols: `upload.ts`, the client,
  the types, `RawErrorResponse.uploadNotStarted`, `canReleaseRejectedDraft`); §20.2
  (`upload.ts`, `raw-ingestion-client.ts`, `client.ts`, `types.ts`); D-32, D-52, D-137.
- Verification:
  - The plan-wide gate; the web gate (`npm run check`, `npm test`, `npm run lint`,
    `npm run build`, `npm run test:e2e` from `web/`), the Svelte autofixer on
    `RawIngestWizard.svelte`, and the visual QA of the ingest page (narrow mobile, about 816 px and
    desktop, light and dark, keyboard only).
  - `rg -n "uploadNotStarted|canReleaseRejectedDraft|submitRawUpload|discardRawUpload|confirmedBytes|UploadDraft|beginRawUpload|getRawUpload|uploadRawPart|completeRawFile|operateRawUpload|commitRawUpload|registerRawUpload|RawIngestFile|RawIngestSession|RawCommitReceipt|RawRevisionMetadata|RawErrorResponse" web/src web/e2e`
    prints nothing.
  - Row 5's check `rg -n -i "part_bytes|completed_parts|PART_BYTES|write_part|uploadRawPart|MAX_PART_BYTES" src tests web/src --glob '!tests/contract/test_catalog_store.py'`
    prints nothing (the kept history suite's `ingest_files.completed_parts` assertions are
    migration history, §21.3).
  - `npm test` runs the moved cases in `files.test.ts` and `hash.test.ts`.
  - `git status` shows exactly the listed deletions plus the two new test modules and edits to
    the files named above.
- Dependencies: M9.3.
- Status: pending

### M10.3 Raw browser views, parsers and problem errors

- Intent: the browser-safe contract layer of the one Raw API: the D-72 views as TypeScript
  types, one strict parser per view, and `RawApiError` built from problem documents, before any
  wizard or explorer code consumes them.
- Delete: none (M10.2 removed `raw-ingestion-client.test.ts`; this task writes it anew).
- Create / Modify:
  - `web/src/lib/api/raw-ingestion-types.ts`: add `RawDatasetView` (its `schema` member typed
    `RawDatasetSchema`, its `registration` member `RawRegistrationView`), `RawRegistrationView`,
    `RawUploadSessionView` (`schema: RawSessionSchema`, `files: RawUploadFileView[] | null`),
    `RawUploadFileView`, `RawCommitView`, `RawVersionView` (`schema_ref: RawSchemaRef`),
    `RawLimitsView`, `RawSchemaSubjectView`, `RawSchemaVersionView`, `RawPage<T>`
    (`{items, next_cursor}`) and `RawProblem` (`{type, title, status, code, detail, context}`),
    member for member as the §19.4 and §16.10 wire models give them, and `RawCatalogTarget`
    (`{organization, catalog}`), moved here from `raw-authorization.ts` (M9.1), which then
    imports it. `RawRevisionManifest` becomes `RawManifest` (the same `urn:huron:manifest:1`
    document) and `RawInspection` follows the rename. `RawTarget`, `RawManifestFile`,
    `RawTargetBranch` and the explorer's `RawRevision`, `RawRevisionPage` and `RawInspection` stay
    (M11.1 replaces the last three).
  - `web/src/lib/api/raw-ingestion-client.ts`: `parseRawDatasetView`, `parseRawRegistrationView`,
    `parseRawUploadSessionView`, `parseRawUploadFileView`, `parseRawCommitView`,
    `parseRawVersionView`, `parseRawLimitsView`, `parseRawSchemaSubjectView`,
    `parseRawSchemaVersionView`, `parseRawPage(value, item)`, `parseRawProblem`, and
    `parseRawManifest` returning `RawManifest`. Each refuses a missing or mistyped member, an
    enumeration value outside its `Literal` set (dataset, registration, session, end reason, file,
    `last_error`, version and schema-version states), a UUID that is not lowercase canonical, an
    unsafe or negative integer and an unparseable RFC 3339 instant. `upload_url` must have the
    BFF's rewritten shape `/ingestion/api/v1/raw/tus/<uuid>?organization=<slug>` (§12.8), so no tus
    request can leave the origin.
  - `RawApiError` rewritten: `status`, `code`, `context`, `retryAfter` and `problem`, built by
    `rawApiError(response)`. `code`, `context` and `problem` come from a valid problem document and
    are `null` when the body is none; `retryAfter` is a delay-seconds `Retry-After` value, else
    `null`; `message` is the problem's `detail`, else its `title`. The private `request()` behind
    `browseRawTargets` and the explorer reads throws it.
  - `web/src/lib/api/types.ts`: exports the new types and `RawManifest`; `client.ts` keeps
    exporting `RawApiError`.
  - `web/src/lib/ingestion/problems.ts` and `tus.ts` (M10.1) import `RawProblem`,
    `RawUploadFileView` and `RawUploadSessionView` from here, replacing the structural
    parameter types M10.1 declared; `web/src/lib/server/raw-inspection.ts` follows the rename.
  - New `web/src/lib/api/raw-ingestion-client.test.ts`.
- Design: §20.2 (`raw-ingestion-types.ts`, `raw-ingestion-client.ts`, `types.ts`); §19.4; §16.10;
  §12.8 (problem pass-through, the `upload_url` rewrite); §22.6 (`raw-ingestion-client.test.ts`);
  D-72, D-113.
- Verification:
  - The plan-wide gate; the web gate (the e2e suite runs unchanged).
  - Vitest `raw-ingestion-client.test.ts`: `parses every Raw view` (one golden JSON per view and
    for `RawPage<RawVersionView>`); `refuses malformed members of <view>` (per view, a table of
    one-member mutations, including an absolute or foreign `upload_url` and an unknown state);
    `RawApiError from a problem document carries code, context and Retry-After`; a non-problem
    `503` body gives `code === null`; `Retry-After: 5` gives `retryAfter === 5` and an HTTP-date
    gives `null`.
  - `npm run check` passes with `tus.ts` and `problems.ts` typed against these views.
- Dependencies: M10.2.
- Status: pending

### M10.4 Raw browser calls and the retry policy

- Intent: the browser functions the wizard calls through the BFF, and `requestWithRetry`, the
  D-62/D-113 policy for JSON calls.
- Delete: none
- Create / Modify:
  - `web/src/lib/api/raw-ingestion-client.ts`:
    - A scope is `{organization}` (target-less), a `RawCatalogTarget` or a `RawTarget`.
      `rawApiUrl(path, scope)` builds `/ingestion/api/v1/raw/<path>?organization=<slug>`, adding
      `&target=<JSON>` for a dataset or catalog target and nothing for a target-less call (§12.2);
      `rawApiPath` and `request()` follow it.
    - The calls, each parsing its answer with its M10.3 parser: `findRawDataset(target)`
      (`GET …/datasets/by-target`), `readRawDataset(target, datasetId)`,
      `submitRawDataset(target, body, idempotencyKey)` (`POST …/datasets`, the BFF composite
      create), `reconcileRawDataset(target, datasetId)` (`POST …/datasets/{id}/registration`,
      body `{}`), `discardRawDataset(target, datasetId, etag)` (`DELETE …/datasets/{id}` with
      `If-Match: "<etag>"`), `listRawSchemaSubjects(scope, after)`,
      `readRawSchemaSubject(scope, subjectId)`, `readRawSchemaVersion(scope, subjectId, number)`,
      `startRawUploadSession(target, datasetId, body, idempotencyKey)`,
      `listRawUploadSessions(organization, {datasetId, state, after})`,
      `readRawUploadSession(organization, sessionId)`, `abortRawUploadSession(organization,
      sessionId)` (body `{}`), `commitRawUploadSession(target, sessionId, expectedLatestNumber)`
      (no `Idempotency-Key`, no `If-Match`, D-147) and `readRawLimits(organization)`. The names
      differ from the server composites of `raw-registration.ts`; no function sends a tus request.
    - `requestWithRetry<T>(call, budgetMs, options?)` with `options.beforeRetry(error)`: retries
      only a `RawApiError` with `409 COMMIT_IN_PROGRESS`, `409 VERIFICATION_PENDING`, `429`, `503`
      or `507`; sleeps `min(retryAfter, 60)` s, or 2 s when the header was lost; rethrows the last
      error when the next sleep would pass the budget; restarts the budget whenever a
      `VERIFICATION_PENDING`'s `context.pending` is lower than the previous one; awaits
      `beforeRetry` before each sleep (the driver re-sends reset files there, §20.4.7 step 4).
      Constants `START_BUDGET_MS = 120_000` and `COMMIT_BUDGET_MS = 600_000`.
  - `web/src/lib/api/client.ts`: exports the calls, `requestWithRetry` and the two budgets.
  - `web/src/lib/api/raw-ingestion-client.test.ts`: extended.
- Design: §20.2 (`raw-ingestion-client.ts`, `client.ts`); §17.7; §12.2 (browser paths and query
  parameters); §20.4 and §13.2–§13.4 (the calls the wizard makes); D-62, D-113, D-147.
- Verification:
  - The plan-wide gate; the web gate.
  - Vitest: `each Raw call uses its BFF path, method, headers and body` (a table over the 14 calls
    against a stubbed `fetch`: `Idempotency-Key` on create and start only, `If-Match` on discard,
    `target` on targeted calls only, `organization` on every call);
    `requestWithRetry` under `vi.useFakeTimers()`: `honors Retry-After capped at 60 s`,
    `waits 2 s when Retry-After is missing`,
    `does not retry 400, 404, 409 LATEST_VERSION_CHANGED or 410`,
    `gives up after the budget with the last error` (120 s and 600 s),
    `restarts the commit budget while pending falls`, `calls beforeRetry before each wait`.
- Dependencies: M10.3.
- Status: pending

### M10.5 Wizard destination and dataset creation

- Intent: the wizard's first step chooses or creates a standard-2 dataset, registered in Polaris
  when it is created (OD-5), and the ingest page renders every §20.4.1 state from the dataset
  view.
- Delete: none
- Create / Modify:
  - `web/src/routes/ingestion/+page.server.ts`: for the destination in the URL
    (`?organization=&catalog=&namespace=&table=`) load, through `callRaw`, the dataset
    (`GET /api/v1/raw/datasets/by-target`, `read`), the actor's OPEN sessions for it
    (`GET /api/v1/raw/upload-sessions?state=OPEN&dataset_id=<id>`, target-less) and
    `RawLimitsView` (`GET /api/v1/raw/limits`); "Raw disabled" when `rawBridgeConfiguration()`
    throws or `/limits` answers `404`; an undiscoverable catalog or namespace is SvelteKit's 404
    page. A by-target `404` opens the create dialog with the name when Polaris has no table of
    that name, and shows the destination read-only and not selectable when it has one (a foreign
    or unmanaged table, §13.2). Returns `{dataset, openSessions, limits}` beside the branch fields
    the picker needs.
  - `web/src/lib/design/components/ingestion/IngestDestinationPicker.svelte`: lists the
    standard-2 branch (`kind`, `datasetId`, `canCreate`); only `managed` rows are selectable,
    `unmanaged` and `unsupported` rows show disabled with their labels; a "New dataset" control,
    shown when `canCreate`, opens `RawDatasetCreate` in place.
  - New `web/src/lib/design/components/ingestion/RawDatasetCreate.svelte`: table name, title
    (1..256), description (≤ 9000) and metadata schema: the PLATFORM subjects from a target-less
    `listRawSchemaSubjects` plus the catalog's from a catalog-target call, only those with
    `latest_active_number` set; a `404` on the catalog call lists none (unbound realm, D-150).
    Submits `submitRawDataset` with a fresh `Idempotency-Key` per user action, and renders every
    outcome row of §20.4.2 through `problems.ts`: `201 ACTIVE` selects the dataset and moves to
    step 2; `201 PENDING` shows the Polaris error with "Finish registration"; `TARGET_TAKEN`;
    `DATASET_EXISTS` selects the holder and offers "Repair registration" when its table is
    missing; `TARGET_RELEASING` offers "Finish deletion" to `drop` holders;
    `STORAGE_LOCATION_OCCUPIED` with `context.base_location`; one sentence per
    `STORAGE_LOCATION_REFUSED` reason with `expected`/`actual`; `TARGET_NAME_UNSUPPORTED` with
    `context.segment`; `SCHEMA_SUBJECT_NOT_USABLE` reloads the subject list; `403`; `503`. Finish
    registration, Repair registration and Finish deletion call `reconcileRawDataset`.
  - `web/src/lib/design/components/ingestion/RawIngestWizard.svelte`: the §20.4.1 states from the
    `$state.raw` dataset view: Raw disabled (`Callout` "Raw storage is not configured for this
    Huron deployment", no steps); loading (`aria-busy`, controls disabled); no destination (step
    1); ACTIVE (steps 1–4); PENDING ("Finish registration" for `create`, "Discard" for `drop`
    through `discardRawDataset`, no upload); ARCHIVED ("Archived: uploads are disabled" and an
    explorer link); DELETED (not selectable; "Finish deletion" while the name is held). Picking a
    destination loads its view with `findRawDataset` and writes the destination into the URL
    with `replaceState`. The free-text "Dataset name" field and its new/existing toggle go. The
    Review step names the dataset and the version this upload expects to become
    (`latest_number + 1`).
  - New `web/e2e/ingestion.test.ts` (M5.1 deleted its predecessor) with the creation scenarios.
- Design: §20.4 (introduction); §20.4.1; §20.4.2; §20.3.3; §20.1; §13.1; §13.2; §15.3; §18.2 A;
  D-44, D-52, D-150, D-151.
- Verification:
  - The plan-wide gate; the web gate; the autofixer on `IngestDestinationPicker.svelte`,
    `RawDatasetCreate.svelte` and `RawIngestWizard.svelte`; visual QA of every state and of the
    create dialog with its errors at the three widths in both themes, keyboard only.
  - Playwright `e2e/ingestion.test.ts`: `creates a Raw dataset whose Polaris table carries
    standard 2` (the table's properties show `huron.raw.standard` `2` and a `base-location` under
    the e2e storage root); `a name held by the Iceberg table observations answers Another table
    already uses this name`; `the S3 catalog ocean-data is refused with the unsupported storage
    type text`; `a reload keeps the chosen destination`.
- Dependencies: M9.5, M9.6, M10.1, M10.4.
- Status: pending

### M10.6 Wizard metadata step

- Intent: metadata follows the dataset's pinned schema: a structured form for the PLATFORM
  `huron.raw.metadata` v1, a JSON editor beside the read-only document for any other subject,
  and the state of a subject left without an ACTIVE version.
- Delete: none
- Create / Modify:
  - New `web/src/lib/ingestion/metadata.ts` (a plain module, §20.1): `platformMetadata(fields)`
    builds the PLATFORM object (title; description; creators one per line; tags comma-separated
    and deduplicated; `source.description`; empty members omitted; no `coverage` or
    `extensions`) and `parseMetadataText(text)` accepts only a JSON object of at most 1 MiB.
  - New `web/src/lib/design/components/ingestion/RawMetadataForm.svelte`: reads the bound subject
    (`readRawSchemaSubject` under the dataset's target) and, when `latest_active_number` is set,
    that version with its document (`readRawSchemaVersion`). PLATFORM `huron.raw.metadata`: the
    structured form, title required. Any other subject: a monospace `textarea` (initially `{}`)
    beside the formatted read-only document. `latest_active_number` null: "No active metadata
    schema", no document fetched, Continue disabled, and for `schema` holders a link to
    `/settings/catalog?tab=schemas` (the tab lands in M11.7). A `METADATA_INVALID` problem the
    wizard hands back lists `context.errors` as "pointer: message" with focus on the list;
    `SCHEMA_VERSION_NOT_USABLE` reloads the subject and asks the user to review.
  - `RawIngestWizard.svelte`: step 3 hosts `RawMetadataForm`; the wizard keeps the metadata object
    and the pinned `schema_version` number for session start; the Review step lists the subject,
    the schema version and the metadata summary; no label on the page says "revision".
  - `web/src/lib/ingestion/files.ts`: `sourceError` says "version" (§20.2); its cases in
    `web/src/lib/ingestion/files.test.ts` (moved there in M10.2) follow the new messages, and one
    asserts that no message says "revision".
  - New `web/src/lib/ingestion/metadata.test.ts`; `web/e2e/ingestion.test.ts` gains the
    metadata scenarios.
- Design: §20.4.3; §20.6 (the link target); §16.6; §16.11; §13.2; D-55, D-57, D-151.
- Verification:
  - The plan-wide gate; the web gate; the autofixer on `RawMetadataForm.svelte` and
    `RawIngestWizard.svelte`; visual QA of the form, the JSON editor, the error list and the
    no-active-version state.
  - Vitest `metadata.test.ts`: `builds the PLATFORM metadata object` (creators per line, tags
    deduplicated, empty members omitted) and `accepts only a JSON object of at most 1 MiB`.
  - Playwright: `a PLATFORM-bound dataset gets the structured metadata form` (Continue stays
    disabled without a title); `a catalog subject gets the JSON editor beside its document` (the
    subject and its version created with `page.request` through the BFF's
    `POST /ingestion/api/v1/raw/schemas/subjects` and `…/versions`, the dataset bound to it in
    `RawDatasetCreate`); `a subject without an active version disables the metadata step` (its
    only version deprecated through `…/versions/1/deprecate`).
- Dependencies: M10.5.
- Status: pending

### M10.7 Upload session driver

- Intent: the protocol logic of one upload session, free of Svelte and the DOM: hash, start,
  transfer, commit, resume and discard over injected factories, with `UploadRun` as the reactive
  state the wizard renders.
- Delete: none (M10.2 removed `upload.ts` and `upload.test.ts` whole; both are written fresh)
- Create / Modify:
  - New `web/src/lib/ingestion/upload.ts` over an injected `UploadApi` (the M10.4 calls it uses)
    and `CreateUpload` (`(file, options) => UploadLike`, tus-js-client's `Upload` in production):
    - `startSession(run, request, limits)`: first, before any hashing, refuses a selection of
      more than `limits.max_files` files, any file above `limits.max_file_bytes` or a total above
      `limits.max_version_bytes` (§17.2 L7: the wizard checks the `GET /limits` sizes the page
      loaded in M10.5), with the `problems.ts` sentence of `TOO_MANY_FILES`, `FILE_TOO_LARGE` or
      `VERSION_TOO_LARGE`; then hashes each file with `hashFile` ("Calculating checksums k of
      n"); calls `startRawUploadSession` through `requestWithRetry(…, START_BUDGET_MS)` with one
      `Idempotency-Key` held in memory for that request; on `201` writes the draft (`drafts.ts`).
    - `transferFiles(run, session, sources)`: one upload per `RECEIVING` file, built by
      `uploadOptions` (`tus.ts`) with its own `ChunkHasher`, two at a time; inside
      `navigator.locks.request('huron-raw-upload:<session_id>', {ifAvailable: true}, …)`, where a
      held lock ends with "This upload is running in another tab"; without the Web Locks API it
      proceeds (the writer epoch fences tabs).
    - `commitSession(run, session, expectedLatestNumber, confirm)`: `commitRawUploadSession`
      through `requestWithRetry(…, COMMIT_BUDGET_MS, {beforeRetry})`. On each
      `VERIFICATION_PENDING` it reads the session and re-sends, from its HEAD offset, every file
      back in `RECEIVING` with `last_error` `DIGEST_MISMATCH` or `SCRATCH_LOST` ("File x failed
      verification and is being sent again"); phases "Verifying k of n" (from `context.pending`),
      "Publishing" and "Another request is finishing this commit" (`COMMIT_IN_PROGRESS`).
      `LATEST_VERSION_CHANGED` calls `confirm(context.latest_number)`, rewrites the draft's
      `expected_latest_number` and retries with the confirmed value. `200` removes the draft.
      `409 UPLOAD_SESSION_CLOSED`, `410 UPLOAD_GONE`, `409 DATASET_NOT_ACTIVE` and
      `410 DATASET_DELETED` end the run with the session's or dataset's state and reason, and
      remove the draft where §20.4.6 says.
    - `resumeSession(run, session, sources, draft)`: maps each re-selected file by `sourcePath`
      to its manifest entry, compares name, size and `lastModified` with the draft fingerprint
      when a draft exists, re-hashes every file still `RECEIVING` with `upload_offset < size` and
      refuses a mismatch with "This is not the file this upload started with", then transfers.
    - `discardSession(run, session)`: `upload.abort(false)` on running uploads, then
      `abortRawUploadSession`, then removes the draft; never a tus `DELETE`.
  - New `web/src/lib/ingestion/upload-run.svelte.ts`: class `UploadRun` with `$state` fields
    `phase`, `files` (per `tus_upload_id`: state, sent bytes, size, last error) and `problem`
    (`RawProblem | null`), `$derived` totals, and the methods the driver calls.
  - New `web/src/lib/ingestion/upload.test.ts`.
- Design: §20.4.7; §20.4.4–§20.4.6 (consumed); §13.3; §13.4; §17.2 (L7); §17.7; §20.1 (shared
  state as a class; protocol logic in plain modules); D-44, D-74, D-113.
- Verification:
  - The plan-wide gate; the web gate; the autofixer on `upload-run.svelte.ts`.
  - Vitest `upload.test.ts` with fake `UploadApi` and `CreateUpload`: `start, transfer and commit
    publish the next version` (the draft written after `201` and removed after `200`; at most two
    uploads at once; zero-byte and already received files get none); `refuses a selection over
    the limits before hashing` (one case each for `max_files`, `max_file_bytes` and
    `max_version_bytes`; no file is hashed and no API call is made); `a DIGEST_MISMATCH reset
    during VERIFICATION_PENDING re-sends that file before the next commit`;
    `LATEST_VERSION_CHANGED asks, then retries with the new number`; `resume maps files by path,
    fingerprint and SHA-256 and refuses a different file`; `a held Web Lock stops a second tab`;
    `discard stops uploads, aborts the session and removes the draft`; `closed and gone sessions
    end with their state and reason`.
- Dependencies: M10.1, M10.4.
- Status: pending

### M10.8 Wizard transfer and commit

- Intent: the wizard runs the driver end to end (start, two parallel tus transfers with
  progress, commit and its outcomes), so the web has a working Raw upload path again, proven
  through the adapter-node BFF in Playwright (the wizard's tus task).
- Delete: none
- Create / Modify:
  - New `web/src/lib/design/components/ingestion/RawUploadProgress.svelte`: per file, keyed by
    `tus_upload_id`, its state, sent bytes, last error and, after `onError`, "Paused" with a
    Resume control that calls `upload.start()` again; totals; the `UploadRun` phases
    ("Calculating checksums k of n", transfer, "Verifying k of n", "Publishing", "Another request
    is finishing this commit"); outcomes: "Version N committed" with a link to its explorer
    detail (`/browse?…&format=raw&tab=files&version=N`) and focus on the message; the
    `LATEST_VERSION_CHANGED` confirmation naming `context.latest_number`; closed, gone and
    dataset-state outcomes in words with "Start a new upload"; problem texts from `problems.ts`.
  - `RawIngestWizard.svelte`: the Review step's "Upload and commit" (disabled unless the dataset
    is ACTIVE with an active schema version) runs `startSession` (with the page's
    `RawLimitsView`), `transferFiles` and `commitSession`, with `expected_latest_number` equal to
    the `latest_number` the Review step showed; a `METADATA_INVALID` start returns to step 3 with
    its errors; one `UploadRun` per page; the API views stay `$state.raw` and are replaced, never
    mutated.
  - `tests/raw_e2e_support.py`: the explicit `RawSettings(...)` that `raw_e2e_app()` passes as
    `raw=` gains `chunk_bytes=8388608` (a 20 MiB file takes three PATCHes), beside its two roots
    `e2e-storage` and `e2e-tmp` and `public_api_url="http://127.0.0.1:8099"` (both since M5.1).
    An environment variable cannot do this: pydantic-settings ignores `HURON_RAW__CHUNK_BYTES`
    when `raw=` is passed explicitly, and §22.6's `HURON_RAW__CHUNK_BYTES=8388608` names the value,
    not the mechanism. Nothing else in the harness changes: `memory_stores()` has carried the
    maintenance store since M4.7, the upload store with its offset ledger since M6.9 and the
    version store since M7.13, and the lifespan has run `MaintenanceLoop`, which verifies files as
    in production, since M7.3.
  - `web/.env.example` and `web/scripts/start.mjs`: the `BODY_SIZE_LIMIT` comments say that
    64 MiB is the largest tus chunk the Raw API accepts (`HURON_RAW__MAX_CHUNK_BYTES`), not a part
    size; the value stays.
  - `web/e2e/ingestion.test.ts` gains the transfer scenarios.
- Design: §20.4.7 (steps 1–5); §20.4.4; §20.8 (web text); §22.6 (harness; the ingestion spec);
  §13.3–§13.6; D-32, D-44, D-74, D-137.
- Verification:
  - The plan-wide gate; the web gate; the autofixer on `RawUploadProgress.svelte` and
    `RawIngestWizard.svelte`; visual QA of the transfer and commit panel with long paths, a
    paused file and every outcome.
  - Playwright `e2e/ingestion.test.ts`: `a directory with a zero-byte file becomes version 1`;
    `a second version holds only its own files` (its manifest read through
    `GET /ingestion/api/v1/raw/datasets/{id}/versions/2/manifest`); `an uncertain commit response
    retried gives the same version` (a route handler aborts the first commit response after the
    API answered); `LATEST_VERSION_CHANGED asks before committing as the next number` (another
    session commits first); `conflicting paths and missing metadata are refused` (the
    `METADATA_INVALID` errors listed on step 3); `the transfer panel at mobile, about 816 px and
    desktop widths in both themes`. The first scenario also asserts that the session start
    answered `chunk_bytes` 8388608, so the harness setting reached the API.
  - `rg -n "64 MiB Raw part|one bounded 64 MiB part" web` prints nothing.
- Dependencies: M9.4, M10.6, M10.7.
- Status: pending

### M10.9 Wizard resume and the leave-page guard

- Intent: an interrupted upload resumes after a reload from the server's OPEN sessions, the
  page asks before leaving a running transfer, and the open-session cap shows what to resume or
  discard.
- Delete: none
- Create / Modify:
  - New `web/src/lib/design/components/ingestion/RawResumeList.svelte`: the destination's OPEN
    sessions from the page load, keyed by session id (started, files, bytes, expires), each with
    "Resume" (`readRawUploadSession`, a request for the same files or directory, then
    `resumeSession`) and "Discard" (`discardSession`); a draft only adds the fingerprint check
    (§20.4.6), and drafts of sessions absent from the list are pruned. The commit after a resume
    takes `expected_latest_number` from the draft; without a draft (§20.4.6), the wizard reads the
    dataset view (`readRawDataset`) before `commitSession`, asks the user to confirm "Commit as
    version N + 1" with N its current `latest_number`, and commits with N; declining leaves the
    session OPEN for a later resume.
  - `RawIngestWizard.svelte`: "Unfinished uploads" for an ACTIVE dataset with OPEN sessions of
    the actor; `beforeNavigate` and `beforeunload` ask while a transfer runs: "Leaving pauses this
    upload; it can be resumed from this dataset until <expires_at>"; after the start budget a
    `429 TOO_MANY_OPEN_SESSIONS` lists all the actor's OPEN sessions (`listRawUploadSessions`,
    target-less) with Discard for each and Resume for those of this dataset.
  - `web/e2e/ingestion.test.ts`: the resume scenario. `web/e2e/organizations.test.ts`: the
    cross-realm scenario, the successor of the Raw-upload test M5.1 deleted, with an upload
    helper that drives the new wizard (create, select, upload, commit, download URL).
- Design: §20.4.7 (resume, leaving the page, step 2's `429` list); §20.4.6 (including the
  draftless commit confirmation); §13.4; §22.6 (the resume scenario; `e2e/organizations.test.ts`);
  D-44, D-74, D-113.
- Verification:
  - The plan-wide gate; the web gate; the autofixer on `RawResumeList.svelte` and
    `RawIngestWizard.svelte`; visual QA of the resume list and the cap list.
  - Playwright `resumes an interrupted upload after a reload`: a 20 MiB file; a route handler lets
    the first PATCH through and aborts every later one; the test reloads once the first `204`
    arrives, removes the handler, opens "Resume", re-selects the same file and waits for the
    commit; it asserts that the resume HEAD returned `Upload-Offset: 8388608`, that exactly two
    PATCHes followed, that the localStorage draft held only `session_id`, `dataset_id`,
    `expected_latest_number` and `files`, and that the committed file's SHA-256, downloaded
    through the BFF, equals the source's.
  - Playwright `a resume without its draft asks to commit as version N + 1`: the same interruption
    with localStorage cleared before the reload; the resume shows "Commit as version N + 1" for
    the dataset's current `latest_number` before any commit request, and confirming commits that
    version.
  - Playwright `Raw uploads with identical catalog paths remain separate across organization
    realms`: a dataset and a version in each of `E2E_RAW_ALPHA` and `E2E_RAW_BETA`, distinct
    `base_location`s from distinct catalog bases, and the download URL of one realm answering
    `404` under the other organization and target.
  - Playwright `leaving a running upload asks first and names the expiry`.
- Dependencies: M10.8.
- Status: pending

### M10.10 Browser acceptance: rehearsal and the 9 GiB gate

- Intent: the acceptance runs drive the real wizard through the real BFF: create, upload, kill
  and restart the API past half the file, resume, commit, download and verify. The 2 GiB
  rehearsal runs here and in every later upload-path task; the 9 GiB gate runs where capacity
  exists and blocks the merge into `main`, not this task (OD-12 O-7). This task takes R16's
  decision (deviation 3).
- Delete: none (M5.3 removed the old gate; this task writes its successor at the same path)
- Create / Modify:
  - `tests/acceptance_support.py`: `require_upload_capacity(path, *, minimum=MINIMUM_FREE_BYTES)`,
    whose message names the minimum in GiB; `tests/unit/test_acceptance_capacity.py` gains the
    `minimum` cases.
  - New `tests/raw_resume_harness.py`, one harness for both runs (§22.8 steps 2–6):
    `postgres:16` through testcontainers and `alembic upgrade head`; the API
    (`uvicorn huron.applications.api.main:app`) as a subprocess with one storage root under the
    test's base directory, the bridge secret and `HURON_RAW__PUBLIC_API_URL`;
    `node e2e/polaris-mock.mjs` and the built BFF (`node scripts/start.mjs`); a sparse source
    file; `npx playwright test -c playwright.acceptance.config.ts` launched without waiting;
    polling `raw_upload_files.upload_offset` and, past half the size, `SIGKILL` of the API, three
    seconds, and a restart on the same port; then the spec's end, the downloaded SHA-256 against
    the source's, and the published `version.json` and `manifest.json` under the root. It samples
    the BFF's resident memory once a second (`ps -o rss= -p <pid>`) and records the idle value
    (before the upload) and the peak with the timings through `record_testsuite_property`.
  - `tests/acceptance/test_raw_ingest_gate.py`:
    `test_a_two_gib_rehearsal_resumes_through_the_bff_across_an_api_restart` (precheck
    `minimum=8 GiB`) and `test_a_nine_gib_file_resumes_through_the_bff_across_an_api_restart`
    (`MINIMUM_FREE_BYTES`, 25 GiB); a missing capacity is a `RuntimeError`, never a skip.
  - New `web/playwright.acceptance.config.ts` (`testDir: 'e2e-acceptance'`,
    `testMatch: '**/*.acceptance.ts'`, no web servers: the harness owns the processes; base URL
    and source path from the environment) and new `web/e2e-acceptance/raw-resume.acceptance.ts`
    (sign in, create a catalog whose base lies in the harness's root, create the dataset in the
    wizard, select the file, start; ride out the restart, which tus-js-client retries as the
    BFF's `503`; commit; download through the BFF into SHA-256 and hand the digest to the
    harness).
  - `.github/workflows/acceptance.yml`: Node 22 through `actions/setup-node`, `npm ci`,
    `npx playwright install --with-deps chromium` and `npm run build` in `web/`, and pytest with
    `--basetemp` on the runner volume that its `df -h` steps show with room.
  - `docs/getting-started/testing.md`: the new gate (what it drives, the two sizes, where each
    runs, the 25 GiB precondition, `--basetemp`).
  - R16: when the rehearsal's peak exceeds idle by more than one chunk per in-flight PATCH, or a
    hang appears that the §12.14 cases do not reproduce, `rawBridgeStream` switches to buffering
    each chunk (at most `HURON_RAW__MAX_CHUNK_BYTES`) with unchanged headers and delegation, and
    `web/README.md` states the cost (one chunk of memory per in-flight PATCH). If that switch
    does not fit this task, it becomes the next web task, before any later task relies on the
    measurement.
- Design: §22.8; §22.1; §24.2; §23.1 R16; §12.14; D-82, D-134, D-138, D-154; OD-12 O-7.
- Verification:
  - The plan-wide gate; `make docs`; the web gate; `uv run pytest tests/unit/test_acceptance_capacity.py`.
  - `uv run pytest -m acceptance -k rehearsal --junitxml=<a path outside the repository>` passes
    on this host, run in the background and polled. The idle and peak RSS and the timings are read
    from that report's `<property>` elements, the only output `record_testsuite_property`
    reaches, and go to the Execution notes with the R16 decision.
  - `uv run pytest -m acceptance` runs with `--basetemp` on an APFS or ext4 volume with ≥ 25 GiB
    free, or in the `Acceptance` workflow once the owner pushes the branch; otherwise the task
    records "not run" with the measured free space. Its absence never fails the task.
- Dependencies: M10.9.
- Status: pending

## Milestone 11 — Web: explorer, lifecycle and metadata schemas

Goal: the explorer recognizes property standard 2, shows versions, manifests and downloads, offers
the lifecycle and registration actions, and catalog administrators publish metadata schemas.

### M11.1 Raw inspection and version files

- Intent: the explorer resolves a loaded generic table into a managed, unmanaged or unsupported
  inspection, and a managed dataset's Files tab lists the selected version's manifest with
  downloads that resume with `Range` (it closes row 15).
- Delete: none. Rename (orchestrator, before the pass, D-141):
  `git mv web/src/lib/design/components/ingestion/RawRevisionBrowser.svelte web/src/lib/design/components/ingestion/RawVersionBrowser.svelte`.
- Create / Modify:
  - `web/src/lib/server/raw-inspection.ts`, rewritten under its name:
    `loadRawInspection(client, user, target, {version, versionsAfter})` returns the §20.5.2
    `RawInspection`. The classification comes from the loaded properties (§15.3). A standard-2
    table resolves `GET /api/v1/raw/datasets/{huron.raw.dataset-id}` through `callRaw` under the
    table's own target, and a `404` there is `unmanaged` (D-9); a standard above 2 is
    `unsupported` with `versionsUrl` as untrusted text. One `requireRawPermissions` evaluation per
    load yields the six flags. A managed load reads the version page (`GET …/versions` with
    `after`), the selected version (the requested `version`, else the highest AVAILABLE, with its
    metadata), its manifest (`GET …/versions/{n}/manifest`) and the actor's OPEN sessions for the
    dataset. A `503 RAW_STORAGE_UNAVAILABLE` keeps the PostgreSQL facts with "Files are temporarily
    unavailable"; a `500` gives "This version cannot be read; an operator has been notified"
    without upstream detail.
  - `web/src/routes/browse/+page.server.ts`: `version` (an integer 1..999999) and `versionsAfter`
    (the opaque cursor) replace `revision` and `rawBefore`; a malformed value answers `400`.
  - `web/src/lib/api/raw-ingestion-types.ts`: `RawInspection` as §20.5.2 gives it; the
    `RawPermissions` interface moves here from `web/src/lib/server/raw-authorization.ts` (which
    imports it), because a browser-visible type carries it; `RawRevision` and `RawRevisionPage`
    leave.
  - `web/src/lib/api/raw-ingestion-client.ts`: new `rawVersionFileUrl(target, datasetId, number,
    path)` (`/ingestion/api/v1/raw/datasets/{id}/versions/{n}/files/{path}?organization=…&target=…`,
    §20.3.4); `listRawRevisions`, `parseRawRevision`, `parseRawRevisions` and `rawFileDownloadUrl`
    leave; `client.ts` and `types.ts` follow.
  - `RawVersionBrowser.svelte` (renamed), rewritten for versions. Files mode: the selected version
    (number, files, bytes, manifest SHA-256), manifest rows with size, media type, SHA-256 and a
    `download` link from `rawVersionFileUrl`, a path filter, at most 500 rows rendered with a
    count of the rest. History mode: the loaded page (number, committed at, files, bytes), each
    row linking `version=N`; paging, tombstones and the selected version's metadata follow in
    M11.3. `{#each}` keyed by `version_id` and path.
  - `web/src/lib/design/components/polaris/RawDatasetDetail.svelte`: uses `RawVersionBrowser`
    with the new inspection for the Files and History tabs; the header and overview follow in
    M11.2.
  - New `web/src/lib/server/raw-inspection.test.ts`; `web/e2e/ingestion.test.ts` gains the
    download scenario.
- Design: §20.5.2 (the inspection type, the Files row, the states below the table); §20.3.4;
  §15.3; §21.2 row 15 (explorer symbols); §22.6 (`raw-inspection.test.ts`); D-9, D-109, D-141,
  D-160.
- Verification:
  - The plan-wide gate; the web gate; the autofixer on `RawVersionBrowser.svelte` and
    `RawDatasetDetail.svelte`; visual QA of the Files tab (500-row cap, long paths, the
    unavailable state).
  - Vitest `raw-inspection.test.ts`: `classifies managed, unmanaged and unsupported tables`
    (including `a standard-2 id answering 404 is unmanaged` and a non-integer standard);
    `pages versions by cursor`; `selects the highest AVAILABLE version unless a number is
    requested`; `maps 503 and 500 to their texts without upstream detail`; `one permission
    evaluation yields the six flags`.
  - Playwright `the Files tab downloads exact bytes, including a Range request`: a committed
    file's `download` link returns its bytes, and a `Range` request through the BFF answers `206`
    with the exact slice.
  - Row 15's check `rg -n "registerRawTable|huron-raw-v1|uploadNotStarted|RawRevision|/api/raw-web|/ingestion/api/uploads|getRelease|listReleases" web/src web/e2e`
    prints nothing, and `test ! -e 'web/src/routes/[org]/[project]/[dataset]/[release]'`.
- Dependencies: M9.4, M10.3, M10.8.
- Status: pending

### M11.2 Raw dataset detail page

- Intent: the dataset page shows a managed dataset's state, registration and overview, and
  renders unmanaged and newer-standard tables read-only with every Polaris property value as
  inert text.
- Delete: none
- Create / Modify:
  - `web/src/lib/design/components/polaris/RawDatasetDetail.svelte`, rewritten (header, overview,
    states):
    - Header for a managed dataset: title; a `Badge` with the state (PENDING warn, ACTIVE ok,
      ARCHIVED neutral, DELETED danger); "Polaris table: registered / pending / unregistered"
      (RELEASED reads "unregistered", D-148); the latest version number; "Upload a new version"
      for ACTIVE with `write`, linking `/ingestion?…&table=`; "Resume upload" when `openSessions`
      is not empty. Unmanaged and newer standard: name and type label, no Huron actions.
    - Overview: description, `base_location`, `catalog_base_location` only when it differs from
      the selected catalog's current `default-base-location` (D-16), the schema subject with a
      link to `/settings/catalog?tab=schemas`, and the standard-2 properties in a "Catalog
      properties" disclosure. Unmanaged and newer standard: Polaris metadata only (format,
      `base-location`, `doc`, the display properties) and "Not managed by Huron: it has no
      versions. Create a Raw dataset under a new name to publish versions."; a newer standard
      shows `huron.raw.versions-url` as plain copyable text. Files: "Files are not listed for
      tables Huron does not manage"; History: "No Huron versions".
    - The "Processing layer" row leaves (§20.7). `base-location`, `doc` and every property value
      render as text, never as an `href` or `src` (D-160).
  - New `web/src/lib/design/components/polaris/RawDatasetDetail.test.ts`
    (`@testing-library/svelte`, jsdom); `web/e2e/ingestion.test.ts` gains the detail scenario.
- Design: §20.5.2 (header, overview and unmanaged columns; the states below the table); §15.3;
  §20.7; D-16, D-109, D-148, D-160.
- Verification:
  - The plan-wide gate; the web gate; the autofixer on `RawDatasetDetail.svelte`; visual QA of
    each state (PENDING, ACTIVE, ARCHIVED, DELETED, unmanaged, newer standard) at the three widths
    in both themes, keyboard only.
  - Vitest `RawDatasetDetail.test.ts`: `a javascript: versions-url on a newer-standard table
    renders as inert text`; `no rendered element carries a javascript: href or src`; `a released
    dataset reads Polaris table: unregistered`; `catalog_base_location shows only when it differs`.
  - Playwright: `the dataset page shows its state, registration and latest version` for the
    dataset the spec created, and `source_files` shows the unmanaged texts.
- Dependencies: M11.1.
- Status: pending

### M11.3 Version history and the Raw permissions row

- Intent: the History tab pages a dataset's versions with tombstones and the selected version's
  metadata and schema, and the Permissions tab names the six Raw permissions.
- Delete: none
- Create / Modify:
  - `RawVersionBrowser.svelte`, history mode: newest first, 20 per page, "Older versions" from
    `next_cursor` (the `versionsAfter` URL parameter); each row with number, committed by and at,
    files and bytes; a DELETED version is a tombstone ("Deleted <deleted_at>, purged after
    <purge_after>" or "Purged <purged_at>"); the selected version shows its metadata as formatted
    read-only JSON and its `schema_ref` (subject, number, schema version id, SHA-256).
  - `web/src/lib/server/raw-inspection.ts`: the version page asks for `limit=20` with no `state`
    filter, so tombstones are listed.
  - `web/src/lib/design/components/polaris/DatasetGovernance.svelte`: for a Raw dataset, a "Raw
    operations" row of Read versions, Upload versions, Create datasets, Archive, Delete and
    Publish metadata schemas, each "Granted" or "Not granted" from the inspection's permissions
    (passed by `RawDatasetDetail.svelte`).
  - `raw-inspection.test.ts` extended; `web/e2e/ingestion.test.ts` gains the history scenario.
- Design: §20.5.2 (the History and Permissions rows); §19.3 routes 20, 22 and 25; §14.4; D-48,
  D-148.
- Verification:
  - The plan-wide gate; the web gate; the autofixer on `RawVersionBrowser.svelte`,
    `DatasetGovernance.svelte` and `RawDatasetDetail.svelte`; visual QA of a long history and a
    tombstone.
  - Vitest: `keeps DELETED versions as tombstones`, `pages 20 versions with the next cursor`.
  - Playwright `the History tab pages versions and shows a tombstone`: the selected version's
    metadata and schema are shown; a version deleted with `page.request` through
    `DELETE /ingestion/api/v1/raw/datasets/{id}/versions/{n}` (with `If-Match`) shows as a
    tombstone with its purge date; the Permissions tab lists the six Raw operations.
- Dependencies: M11.2.
- Status: pending

### M11.4 Namespace view without layers

- Intent: namespace rows carry the four Raw type labels from their loaded properties, and Raw
  rows take no part in the layer column, filter or footnote (requirement 5).
- Delete: none
- Create / Modify:
  - `web/src/lib/api/catalog-datasets.ts`: `datasetTypeLabel` returns "Raw dataset" (standard 2),
    "Unmanaged Raw table" (no standard, or standard 2 with an invalid id), "Raw (newer standard)"
    (a standard above 2) or "Generic" (a non-Raw generic table); "Iceberg" and "Icechunk"
    unchanged; `datasetLayer` unchanged and never called for Raw rows.
  - `web/src/lib/api/polaris-raw-types.ts`: `PolarisRawTableIdentifier` and `PolarisRawTable`
    carry `management`, `standard` and `datasetId`, filled by `rawTable()` in
    `web/src/lib/server/polaris-raw.ts` from M9.5's classifier, and a Raw table's displayed
    properties drop `huron.layer` (M9.5 left that to this task).
  - `web/src/lib/design/components/polaris/NamespaceContents.svelte`: Raw rows show "—" in the
    Layer column with the title "Raw datasets have no processing layer"; a bronze, silver, gold,
    unassigned or conflict filter excludes them; the footnote reads "Layer comes from namespace
    placement or loaded `huron.layer` metadata. Raw datasets have no processing layer."
  - Tests: `web/src/lib/api/catalog-datasets.test.ts` (the four labels);
    `web/src/lib/server/polaris-raw.test.ts` ("a Raw table shows no huron.layer");
    `web/e2e/dataset-types.test.ts`: the type-and-layer filter test keeps Raw rows out
    of every layer filter and labels `source_files` "Unmanaged Raw table"; the Reader test becomes
    "a Reader cannot create a Raw dataset or register an Iceberg table and cannot discover another
    catalog's Raw datasets".
- Design: §20.5.1 (classification; no layer for Raw); §20.7; §21.2 row 6 (Web, Tests, Check);
  §22.6 (`dataset-types.test.ts`); D-71, D-109.
- Verification:
  - The plan-wide gate; the web gate; the autofixer on `NamespaceContents.svelte`; visual QA of
    the table and filters.
  - Row 6's check, with the tus endpoint module added because it is not named `raw_*.py`
    (deviation 6): `rg -n "Layer\.RAW|entry_layer|ensure_layer_writable" src/huron/core/raw src/huron/applications/api/routes/v1/endpoints/raw_*.py src/huron/applications/api/routes/v1/endpoints/tus.py src/huron/applications/api/authorization/guards.py`
    prints nothing, and the Vitest case "a Raw table shows no huron.layer" passes.
  - Playwright `dataset-types.test.ts` passes with the rewritten filter and Reader tests.
- Dependencies: M9.5, M11.3.
- Status: pending

### M11.5 Lifecycle actions: archive, unarchive and deletes

- Intent: archive, unarchive, dataset delete and version delete from the explorer, each with its
  confirmation and the retention consequences stated.
- Delete: none
- Create / Modify:
  - New `web/src/lib/server/raw-actions.ts`: SvelteKit actions `archiveRawDataset`,
    `unarchiveRawDataset`, `deleteRawDataset` and `deleteRawVersion`. Each reads the dataset id,
    the target and the loaded `etag` from the form, evaluates its permission once
    (`requireRawPermissions`: `manage`, `manage`, `drop`, `drop`), then calls `callRaw`
    (`POST …/archive`, `POST …/unarchive`, `DELETE …/versions/{n}`) or the composite
    `deleteRawDataset` of `raw-registration.ts`, with `If-Match: "<etag>"`, and reports through
    the existing notice cookie. `412 PRECONDITION_FAILED` says "This dataset changed; review and
    retry" and the page reloads its view; `409 COMMIT_IN_PROGRESS` says "A version is being
    published; retry in a few seconds"; other problems use `problems.ts`.
  - `web/src/routes/browse/+page.server.ts`: `actions` combine `createPolarisActions(...)` with
    the Raw actions.
  - New `web/src/lib/design/components/polaris/RawDatasetActions.svelte`: `PolarisForm`s for
    Archive (ACTIVE, `manage`; says that open uploads are cancelled), Unarchive (ARCHIVED,
    `manage`), Delete (PENDING, ACTIVE or ARCHIVED, `drop`; the user types the dataset name; the
    text says versions leave the catalog location now, are purged after 30 days, and that delete
    cannot be undone in Huron) and Delete version (an AVAILABLE version of an ACTIVE or ARCHIVED
    dataset, `drop`; the user types the version number; the same retention text). Controls render
    only with their permission; user-facing text says "unregistered", never "released".
  - `RawDatasetDetail.svelte` mounts it in the header; `RawVersionBrowser.svelte` offers "Delete
    version" on the selected AVAILABLE version.
  - New `web/src/lib/server/raw-actions.test.ts`; new `web/e2e/raw-lifecycle.test.ts`.
- Design: §20.5.3 (the archive, unarchive, delete and delete-version rows; the `412` and `409`
  texts); §20.1 (retention consequences); §13.8; §13.9; §15.5; §22.6 (`raw-lifecycle.test.ts`);
  D-46, D-47, D-48, D-53, D-148.
- Verification:
  - The plan-wide gate; the web gate; the autofixer on `RawDatasetActions.svelte`,
    `RawDatasetDetail.svelte` and `RawVersionBrowser.svelte`; visual QA of each confirmation.
  - Vitest `raw-actions.test.ts`: `sends If-Match from the loaded etag`, `412 asks to review and
    retry`, `409 COMMIT_IN_PROGRESS asks to retry`, `a missing permission answers 403 before
    calling the API`.
  - Playwright `e2e/raw-lifecycle.test.ts`: `archiving cancels an open upload and its next PATCH
    answers 410` (the wizard names the archived dataset); `unarchive allows a new upload`;
    `deleting a version leaves a tombstone and its download answers 410`; `deleting the dataset
    needs its typed name and drops the Polaris table`; `the same name can be created again and
    numbers from 1`; `a Reader sees history and downloads but no upload, archive or delete
    control, and a forged POST answers 403`.
- Dependencies: M10.9, M11.4.
- Status: pending

### M11.6 Registration actions and the pending callout

- Intent: users finish or repair a registration and finish a deletion from the explorer, and a
  namespace lists the actor's unfinished datasets.
- Delete: none
- Create / Modify:
  - `web/src/lib/server/raw-actions.ts`: action `reconcileRawRegistration`, calling the composite
    `reconcileRawRegistration` of `raw-registration.ts`: "Finish registration" (PENDING,
    `create`), "Repair registration" (ACTIVE or ARCHIVED without a Polaris table, `create`),
    "Finish deletion" (DELETED and not released, `drop`; and DELETED and released while the loaded
    table is still ours, reached through the table's `huron.raw.dataset-id`, D-179).
  - `RawDatasetActions.svelte`: the reconcile form under those conditions; the detail page
    offers it when the inspection's dataset and loaded table match a row of §20.5.3 (an absent
    table is reached through the wizard, which M10.5 already covers).
  - `web/src/lib/api/polaris-browse-types.ts`: `PolarisBrowseData.rawPending: RawDatasetView[]`;
    `web/src/routes/browse/+page.server.ts` loads `GET /api/v1/raw/datasets?state=PENDING`
    (route 2, target-less) through `callRaw` when Raw is configured, filtered to the selected
    catalog and namespace; `NamespaceContents.svelte` renders the callout above the table with
    "Finish registration" and "Discard" (`RawDatasetActions`); nothing renders when the list is
    empty or Raw is disabled.
  - `web/e2e/polaris-mock.mjs`: `POST /__mock/fail-next-generic-table-create` makes the next
    generic-table create answer one `503`.
  - `raw-actions.test.ts` extended; `web/e2e/raw-lifecycle.test.ts` gains the registration
    scenarios.
- Design: §20.5.3 (the reconcile row); §20.5.1 (pending callout); §15.4; §20.3.2; §19.3 route 2;
  §22.6 (the mock hook; "Finish registration" after the injected `503`); D-52, D-53, D-179.
- Verification:
  - The plan-wide gate; the web gate; the autofixer on `RawDatasetActions.svelte` and
    `NamespaceContents.svelte`; visual QA of the callout with several pending datasets.
  - Vitest: `reconcile offers Finish deletion on a released tombstone whose table is ours`;
    `the pending list is filtered to the catalog and namespace`; `a disabled Raw API renders no
    callout`.
  - Playwright: `Finish registration after an injected Polaris 503` (the hook armed, the dataset
    created PENDING, the callout lists it, Finish registration makes it ACTIVE and the callout
    empties); `Discard removes a pending dataset`.
- Dependencies: M11.5.
- Status: pending

### M11.7 Metadata schemas settings tab

- Intent: catalog administrators list, create, publish and deprecate metadata schemas from the
  catalog settings, including before the organization's first Raw dataset (OD-12 O-6).
- Delete: none
- Create / Modify:
  - New `web/src/lib/server/raw-schemas.ts` on `callRaw`: the load reads the PLATFORM subjects
    (target-less), the catalog's subjects (catalog target; `404` means an unbound realm and lists
    none), the selected subject's versions and the selected version's document; the writes
    `createSchemaSubject`, `publishSchemaVersion` and `deprecateSchemaVersion` require `schema`
    from catalog-level grants and send the `Idempotency-Key` the load rendered.
  - `web/src/routes/settings/catalog/+page.server.ts`: tab `schemas`, shown when the catalog
    target yields `schema`; the load adds the panel's data and three fresh `Idempotency-Key`s as
    hidden form values; the three actions join the existing ones.
  - `web/src/routes/settings/catalog/+page.svelte`: a fourth tab, "Metadata schemas".
  - New `web/src/lib/design/components/polaris/MetadataSchemasPanel.svelte`: subjects with
    qualified name, description, latest number and latest ACTIVE number (PLATFORM read-only,
    "Maintained by Huron"; "Not bindable: publish a version first" without an ACTIVE version);
    the selected subject's versions, newest first, with state, short SHA-256, creator and date,
    and the selected document as formatted read-only JSON; Create subject (the name pattern
    checked as feedback only; `409 SCHEMA_SUBJECT_EXISTS` names the existing subject); Publish
    version (a `.json` file or pasted text, a JSON object of at most 256 KiB checked in the
    browser; `422 SCHEMA_INVALID` lists `context.errors`; `200` says "Identical to version n; no
    new version was created"); Deprecate on an ACTIVE catalog version after a confirmation that
    pinned sessions can still commit, warning when no ACTIVE version would remain. An unbound
    realm shows the PLATFORM subjects and keeps Create subject.
  - New `web/src/lib/server/raw-schemas.test.ts`; `web/e2e/raw-lifecycle.test.ts` gains the
    schema scenario.
- Design: §20.6; §16.10; §16.3; §24.1; §19.3 routes 26–33; D-150, D-151.
- Verification:
  - The plan-wide gate; the web gate; the autofixer on `MetadataSchemasPanel.svelte` and the
    settings `+page.svelte`; visual QA of the tab with a long document, an empty catalog and the
    error lists.
  - Vitest `raw-schemas.test.ts`: `PLATFORM reads are target-less and catalog reads carry a
    catalog target`; `a 404 catalog read lists no catalog subjects`; `writes send the rendered
    Idempotency-Key`; `writes need schema`.
  - Playwright `metadata schemas: create, publish, identical content, deprecate, bind and invalid
    metadata`: create a subject, publish a version, publish identical content and see the `200`
    text, publish a second version and deprecate the first, create a dataset bound to the
    subject, and see an upload whose metadata violates it list its `METADATA_INVALID` errors;
    plus `the first catalog subject of a new organization pins its realm`.
- Dependencies: M11.6.
- Status: pending

## Milestone 12 — Maintenance duties (slice 6)

Goal: all ten duties run in `MaintenanceLoop` in D-64 order; the report-only and row duties land
first and the byte-moving duties last, each only with its named safety tests on real temporary roots
(R5). The milestone follows the web tasks (deviation 4).

### M12.1 ExpireSessions and PruneRows

- Intent: the two duties that change only PostgreSQL: OPEN sessions past `expires_at` end
  ABORTED with `EXPIRED`, and reaped session rows and expired idempotency records are pruned.
  They land first in slice 6 because they move no bytes (R5).
- Delete: none
- Create / Modify:
  - `src/huron/core/raw/ports.py`: `MaintenanceStore.expire_sessions(*, batch) -> tuple[UUID, ...]`
    and `prune(*, batch, retention) -> int`.
  - `src/huron/core/metastore/raw_datasets.py`: `PostgresMaintenanceStore.expire_sessions`
    (§18.4 duty 1's statement in one transaction: OPEN with `expires_at < now()`, ordered by
    `expires_at`, `LIMIT $batch FOR UPDATE SKIP LOCKED`; `ended_at = now()`; one
    `raw.session.aborted` audit row per returned id as `huron-raw-maintenance` with payload
    `{"dataset_id", "end_reason": "EXPIRED"}`; never a COMMITTING row) and `prune` (§10.9's two
    statements, each in its own transaction, each at most `batch` rows: sessions whose
    `staging_reaped_at` is older than the retention, their file rows by cascade; then
    `idempotency_records` past `expires_at`; no new index); the in-memory maintenance store
    applies the same rules to the in-memory upload state it shares, on its clock.
  - `src/huron/core/raw/maintenance.py`: duties `ExpireSessions` and `PruneRows`, reporting
    `DutyReport(name, claimed, done, failed)`; `PruneRows` takes its retention from
    `RawLimits.session_row_retention` (M6.7).
  - `src/huron/core/raw/runtime.py`: `RawMaintenance` composes `ExpireSessions` first and
    `PruneRows` last, in D-64 order around the existing `VerifyFiles` and `FinishCommits`.
  - `src/huron/core/metastore/hierarchy.py`: `_PostgresTransactionWriter.claim()`'s docstring
    says that only `PruneRows` deletes `idempotency_records` rows, and only expired ones (§18.4
    duty 10; M5.6 removed the claim's `ingest_commit` exemption, §10.9); the Raw claim helper in
    `core/metastore/rows.py` follows if it repeats the sentence.
  - Tests: shared scenario `test_expire_sessions_never_selects_committing` in
    `tests/raw_store_contract.py` (an expired OPEN session becomes ABORTED `EXPIRED` with one
    audit row; a COMMITTING session past `expires_at` and an unexpired OPEN one are untouched), run
    by `tests/unit/test_raw_stores_memory.py` and `tests/contract/test_raw_stores_postgres.py`;
    contract `test_prune_rows_keeps_live_idempotency_records` in
    `tests/contract/test_raw_maintenance_claims.py` (only rows reaped before the retention go,
    with their files; unreaped terminal rows and live idempotency records stay; a record another
    transaction holds through a conflicting claim is skipped, not deleted); unit
    `tests/unit/test_raw_maintenance.py` (extended; slice 4 created it): the duties' reports and
    order, `test_maintenance_fails_closed_without_database` for the duties that exist so far (a
    store that raises a connection error changes no storage, and `run_pass` logs it and runs the
    next duty), and `test_commit_after_prune_is_404` (D-116, §18.4 duty 10: once `PruneRows`
    deleted a reaped COMMITTED session's row, a commit retry on that session id answers
    `404 NOT_FOUND` through `UploadService.commit`).
- Design: §18.4 duties 1 and 10; §18.5 (session row retention, T6); §18.6 (rule 6; the
  refinements); §10.9 (prune, the idempotency claim); §8.7.3 (`expire_sessions`, `prune`);
  §8.6.7; §14.6; D-63, D-64, D-116, D-117, D-118.
- Verification:
  - The plan-wide gate; `uv run pytest -m "unit or contract" --cov=src/huron --cov-report=term-missing --cov-fail-under=0`
    shows every new PostgreSQL statement covered; the OD-12 O-8 floor reset and its counts in the
    Execution notes; the slice 6 clone budget (at most four new clones across M12, a running total
    in the Execution notes).
  - `uv run pytest -m acceptance -k rehearsal` passes (session expiry is on the upload path).
  - The named tests above pass; a named race test that fails intermittently stops the milestone
    (the "Races" rule).
- Dependencies: M7.3, M11.7.
- Status: pending

### M12.2 ReportOrphans

- Intent: the report-only duty that compares each dataset's recorded versions with its
  `versions/` listing and records orphans in both directions as findings, never moving or
  deleting anything. It precedes the byte-moving duties (R5).
- Delete: none
- Create / Modify:
  - `src/huron/core/raw/types.py`: `PlacementInventory` (`dataset_id`, `placement`, `available`,
    `expected`).
  - `src/huron/core/raw/ports.py`: `StorageSweeper.version_numbers(placement) -> tuple[int, ...]`
    and `MaintenanceStore.inventory(root, *, after, limit) -> tuple[PlacementInventory, ...]`.
  - `src/huron/core/rawstore/sweep.py`: `version_numbers` (the sorted numbers of `versions/`
    entries named by exactly six digits in 1..999999, whatever their type; `()` for an absent
    `versions/`); `src/huron/core/rawstore/roots.py` dispatches it after the placement-prefix
    check and confirms an absent `versions/` (sentinel, `root_id`, device) before answering `()`.
  - `src/huron/core/metastore/raw_datasets.py`: `inventory` in both stores: the root's datasets
    that are not DELETED, in id order after the cursor, at most `limit`, each with its AVAILABLE
    numbers and its expected numbers (a version row in any state, plus a COMMITTING session's
    number); one statement in PostgreSQL.
  - `src/huron/core/raw/maintenance.py`: `ReportOrphans`. Per process it keeps a cursor per root
    and scans only the roots that M7.3's `available_roots(sweeper, keys)` answers at the start of
    its run (a timed-out probe counts as UNAVAILABLE); a cycle starts with the first pass and
    then once `ORPHAN_SCAN_INTERVAL_SECONDS` have passed since the previous cycle started (an
    injected monotonic clock); a pass scans at most `batch` datasets per root. For each dataset
    it reads the AVAILABLE numbers, then the listing, then the expected numbers again after the
    listing.
    Unrecorded = listed − expected, each re-checked for presence, reported
    `RAW_UNRECORDED_VERSION_DIRECTORY` (warning; `path = <storage_path>/versions/<NNNNNN>`,
    `subject_id` = the dataset id). Missing = AVAILABLE − listed, each re-read, reported
    `RAW_VERSION_DIRECTORY_MISSING` (error; `subject_id` = the version id) only while the version is
    still AVAILABLE, its dataset is not DELETED and the sentinel is present. Every finding carries
    `detail.root` and goes through `MaintenanceStore.report`; nothing resolves findings.
    `RawMaintenance` places it ninth, before `PruneRows`.
  - `src/huron/core/raw/runtime.py`: composes it.
  - Tests: `tests/unit/test_rawstore_sweep.py` (`version_numbers` ignores foreign names and keeps
    six-digit entries of any type; an absent `versions/` answers `()` only with the sentinel);
    `tests/unit/test_raw_maintenance.py` (unrecorded and missing decisions, the cycle interval,
    the cursor wrapping, an UNAVAILABLE root skipped); shared `inventory` scenarios on both
    stores; contract `test_orphan_report_ignores_concurrent_commit_and_delete` (a version
    published and recorded between the listing and the expected read is not reported, a
    COMMITTING number is not reported, and a version deleted and parked between the AVAILABLE
    read and the listing is not reported missing; the interleavings injected through a wrapped
    sweeper).
- Design: §18.4 duty 9; §8.7.3 (`PlacementInventory`, `inventory`, `report`); §9.8.5
  (`version_numbers`); §9.8.6 (confirmation); §10.9 (findings); §18.2 H6, H7; D-66, D-116,
  D-117.
- Verification:
  - The plan-wide gate; the adapter coverage run as in M12.1 with the OD-12 O-8 reset recorded;
    the slice 6 clone budget.
  - The named tests above pass.
- Dependencies: M12.1.
- Status: pending

### M12.3 ReapStaging and SweepOrphanStaging

- Intent: staging trees leave the upload area: a terminal session's tree after the grace, and a
  tree without a live row past the grace. Both duties only rename into `.huron/trash/`, and each
  lands only with its §18.6 tests and the root-swap case passing on real temporary roots (R5).
- Delete: none
- Create / Modify:
  - `src/huron/core/raw/ports.py`: `StorageSweeper.trash_staging(root, session_id) -> bool`.
  - `src/huron/core/rawstore/sweep.py`: `trash_staging` renames `.huron/staging/<hex>` to
    `.huron/trash/<uuid4 hex>` exclusively and fsyncs both parents; `False` for an absent tree;
    `roots.py` dispatches it and confirms the absence (sentinel, `root_id`) before `False`.
  - `src/huron/core/metastore/raw_datasets.py`, both stores: `claim(WorkKind.REAP_STAGING, …)`
    (terminal, `staging_reaped_at IS NULL`, `ended_at < now() - older_than`, by `ended_at`, the
    rename lease) and its fenced `complete` (`staging_reaped_at = now()`, work columns cleared,
    `WHERE staging_reaped_at IS NULL` and the token).
  - `src/huron/core/metastore/ingest.py`, both stores: `known_sessions(ids)` returns only ids
    with a row whose `staging_reaped_at` is NULL, so a reaped row's tree counts as garbage
    (changed here if M6.4 counted reaped rows), with a shared scenario.
  - `src/huron/core/raw/maintenance.py`, both duties on the roots that M7.3's
    `available_roots(sweeper, keys)` answers at the start of their run (a timed-out probe counts
    as UNAVAILABLE): `ReapStaging` (claim on those roots with `RENAME_LEASE_SECONDS` and the
    staging grace, `trash_staging`, `complete`; a `StorageRootUnavailableError` completes
    nothing) and `SweepOrphanStaging` (per such root: `UploadArea.staging_ids(root)`, only 32-hex
    names with an mtime older than the grace on the host clock, oldest first, at most `batch`,
    minus `known_sessions`, then `trash_staging`); the grace is `RawLimits.staging_grace` (M6.7).
    `RawMaintenance` places them fourth and fifth; `runtime.py` composes them.
  - Tests: `tests/unit/test_rawstore_sweep.py` (`trash_staging` moves; an absent tree answers
    `False` only with the sentinel; a missing sentinel raises); `tests/unit/test_raw_maintenance.py`:
    `test_reap_waits_for_terminal_state_and_grace`, `test_orphan_sweep_spares_young_and_recorded_trees`
    (young trees, trees of live rows and non-hex names stay; row-less and reaped-row trees past
    the grace go), `test_late_patch_after_reap_records_nothing` (a chunk admitted before its
    session ended writes after the reap into the moved tree, and its finish records nothing),
    `test_commit_retry_after_staging_reap_returns_same_version`,
    `test_unmounted_root_never_fails_sessions` (without the sentinel nothing is reaped, swept or
    recorded and no session changes state), and
    `test_byte_moving_duties_skip_a_root_swapped_for_an_empty_directory` (parametrized; here
    `ReapStaging` and `SweepOrphanStaging`: the root directory replaced by an empty one between
    two passes, the second pass changes nothing); contract: the `REAP_STAGING` claim predicate,
    lease and fence in `tests/contract/test_raw_maintenance_claims.py`.
- Design: §18.4 duties 4 and 5; §18.6 rules 3–5; §18.3 (claims, `RENAME_LEASE_SECONDS`); §9.8.5
  (`trash_staging`); §9.8.3 (`staging_ids`); §18.2 B2–B7, C9, C11, D5, E1, E5; §23.1 R5; D-65,
  D-115, D-116, D-118.
- Verification:
  - The plan-wide gate; the adapter coverage run with the OD-12 O-8 reset recorded; the slice 6
    clone budget.
  - `uv run pytest -m acceptance -k rehearsal` passes.
  - The named tests and `test_root_remap_refused_by_sentinel` pass on real temporary roots before
    either duty joins `RawMaintenance` (the "Byte-moving duties" rule); a finding that a duty
    acted on a root whose sentinel did not verify removes the duty until a fix with a named test
    lands.
- Dependencies: M12.2.
- Status: pending

### M12.4 ParkDeleted

- Intent: the duty that finishes a dataset or version park whose delete request died or whose
  park left foreign entries, without ever moving another dataset's version.
- Delete: none
- Create / Modify:
  - `src/huron/core/metastore/raw_datasets.py`, both stores: `claim(WorkKind.PARK_DATASET, …)`
    (`state = 'DELETED' AND parked_at IS NULL`, by `deleted_at`) and
    `claim(WorkKind.PARK_VERSION, …)` (`raw_versions` joined to its dataset:
    `v.state = 'DELETED' AND v.parked_at IS NULL AND (d.state <> 'DELETED' OR d.parked_at IS NULL)`,
    by `deleted_at`), both under the rename lease and `roots = ANY($available)`, the roots
    that M7.3's `available_roots(sweeper, keys)` answers at the start of `ParkDeleted`'s run;
    their fenced `complete` sets `parked_at = now()` and clears the work columns
    `WHERE parked_at IS NULL`, and a
    `PARK_DATASET` completion also stamps the dataset's unparked DELETED versions in the same
    statement (D-168).
  - `src/huron/core/raw/maintenance.py`: `ParkDeleted`. A dataset item runs `park_dataset` on a
    worker thread, reports `RAW_FOREIGN_VERSIONS_ENTRY` (warning,
    `path = <storage_path>/versions/<name>`) for each `ParkReport.foreign` entry, then completes,
    since none of the dataset's versions remains. A version item runs `park_version`.
    `VersionIdentityError` reports `RAW_ALIASED_VERSION_DIRECTORY` (error, `detail.step = "park"`)
    and completes nothing; a `cross_device` refusal reports `RAW_CROSS_DEVICE_PLACEMENT`;
    `StorageRootUnavailableError` changes nothing. `RawMaintenance` places it sixth; `runtime.py`
    composes it.
  - Tests: `tests/unit/test_raw_maintenance.py`: `test_version_park_never_moves_a_recreated_datasets_version`
    (a version park pending when its dataset is deleted, parked, released and re-created at the
    same locator: no claim selects it, and a forced `park_version` is refused by its identity
    check, leaving the new dataset's `versions/000001` in place); `ParkDeleted takes over a delete
    that crashed before its park` (F5, after the lease); foreign entries leave warnings and
    `parked_at` (F7); the aliased and cross-device refusals; the root-swap parametrization gains
    `ParkDeleted`. Contract, in `tests/contract/test_raw_maintenance_claims.py`: the two park
    claims (lease, the D-168 join) and the dataset completion stamping its versions.
- Design: §18.4 duty 6; §18.3 (claims and completions); §8.7.3; §9.8.5 (`park_dataset`,
  `park_version`, identity before a move); §18.2 F5–F7, F14; D-19, D-115, D-168, D-174, D-178.
- Verification:
  - The plan-wide gate; the adapter coverage run with the OD-12 O-8 reset recorded; the slice 6
    clone budget.
  - The named tests, `test_unmounted_root_never_fails_sessions`, `test_root_remap_refused_by_sentinel`
    and the root-swap case pass on real temporary roots before the duty joins `RawMaintenance`
    (the "Byte-moving duties" rule).
- Dependencies: M8.7, M12.3.
- Status: pending

### M12.5 PurgeDeleted

- Intent: parked bytes past their retention move into trash, once and only once, and the
  composed flow reaches purge.
- Delete: none
- Create / Modify:
  - `src/huron/core/raw/ports.py`: `StorageSweeper.purge_parked_dataset(root, dataset_id) -> bool`
    and `purge_parked_version(root, dataset_id, number) -> bool`.
  - `src/huron/core/rawstore/sweep.py`: `purge_parked_dataset` renames
    `.huron/deleted/<dataset hex>` to `.huron/trash/<uuid4 hex>`; `purge_parked_version` opens
    `.huron/deleted/<dataset hex>.<NNNNNN>` with `O_DIRECTORY | O_NOFOLLOW`, reads its
    `version.json` (≤ 64 KiB) through that descriptor, moves it only when it names this dataset
    and number, compares `(st_dev, st_ino)` after the rename and renames back on a mismatch,
    raising `VersionIdentityError`; both answer `False` for an absent source after `roots.py`
    confirms it (sentinel, `root_id`).
  - `src/huron/core/metastore/raw_datasets.py`, both stores: `claim(WorkKind.PURGE_DATASET | PURGE_VERSION, …)`
    (`state = 'DELETED' AND parked_at IS NOT NULL AND purged_at IS NULL AND purge_after < now()`,
    by `purge_after`, the rename lease, on the roots that M7.3's `available_roots(sweeper, keys)`
    answers at the start of `PurgeDeleted`'s run) and `complete(item, audit=…)`
    (`purged_at = now()`, work columns cleared, `WHERE purged_at IS NULL` and the token, with the
    `raw.dataset.purged` or `raw.version.purged` audit row as `huron-raw-maintenance`).
  - `src/huron/core/raw/maintenance.py`: `PurgeDeleted`. An absent parked directory reports
    `RAW_PARKED_DIRECTORY_MISSING` (warning) and completes, except for a version of a DELETED
    dataset, which completes without a finding (G3); `VersionIdentityError` reports
    `RAW_ALIASED_VERSION_DIRECTORY` (`detail.step = "purge"`) and a `cross_device` refusal
    `RAW_CROSS_DEVICE_PLACEMENT`, neither completing. `RawMaintenance` places it seventh;
    `runtime.py` composes it.
  - Tests: `tests/unit/test_rawstore_sweep.py` (both purges move into trash; the identity refusal
    leaves the parked directory; an absent source answers `False` only with the sentinel);
    `tests/unit/test_raw_maintenance.py`: `test_version_purge_after_dataset_park_has_no_finding`
    (G3), the G1 and G2 warnings, the aliased refusal, and the root-swap parametrization gains
    `PurgeDeleted`; contract `test_purge_never_touches_live_dataset` (ACTIVE, ARCHIVED and
    unparked DELETED datasets and versions are never claimed, and nothing under a live placement
    moves) and `test_two_replicas_purge_once` (two pools and two duties race: one rename, one
    `purged_at`, one audit row); both stamp each deletion with a zero retention through the
    store's transition call, because `purge_after` is write-once.
  - `tests/integration/test_raw_flow.py` (`test_lifecycle_round_trip`, or a sibling case): after
    the dataset delete and park, one maintenance pass through a pool whose sessions resolve
    `now()` 31 days ahead (a test-only `now()` in a schema placed before `pg_catalog` on that
    pool's `search_path`) purges the parked tree into trash and records `purged_at` and
    `raw.dataset.purged`.
- Design: §18.4 duty 7; §9.8.5 (purges, identity before a move); §18.3 (claims and completions);
  §18.2 G1–G4; §14.6 (`raw.*.purged`); §22.2 (the composed flow to purge); D-49, D-115, D-116,
  D-168.
- Verification:
  - The plan-wide gate; the adapter coverage run with the OD-12 O-8 reset recorded; the slice 6
    clone budget.
  - The named tests and the root-swap case pass on real temporary roots before the duty joins
    `RawMaintenance` (the "Byte-moving duties" rule); `uv run pytest -m integration` passes with
    the extended flow.
- Dependencies: M12.4.
- Status: pending

### M12.6 EmptyTrash

- Intent: the only code that unlinks: it empties `.huron/trash/` without following links or
  crossing devices, and the ten duties are complete.
- Delete: none
- Create / Modify:
  - `src/huron/core/rawstore/materialize.py`: new `remove_tree(parent_fd, name)`, iterative with
    an explicit stack and descriptor-relative under `O_NOFOLLOW`: symlinks and files are unlinked
    without being followed; a directory Huron owns gets `fchmod(0o700)` before its entries are
    unlinked; a directory whose `st_dev` differs from the trash directory's is never entered;
    `ENOENT` counts as done, `ENOTEMPTY` leaves the entry for the next pass, and `EACCES` or
    `EPERM` logs the entry at ERROR and skips it.
  - `src/huron/core/rawstore/sweep.py`: `empty_trash(root, limit) -> int` runs `remove_tree` on the
    first `limit` entries of `.huron/trash/` in name order; `StorageSweeper.empty_trash` declared
    in `src/huron/core/raw/ports.py` and dispatched by `roots.py`.
  - `src/huron/core/raw/maintenance.py`: `EmptyTrash` per root that M7.3's
    `available_roots(sweeper, keys)` answers at the start of its run (a timed-out probe counts as
    UNAVAILABLE); `RawMaintenance` now holds all ten duties in D-64 order; `runtime.py` composes
    it.
  - Tests: `tests/unit/test_rawstore_materialize.py`: `test_empty_trash_never_follows_links_or_crosses_devices`
    (symlinks to a file and to a directory outside trash leave their targets intact; a directory
    with a different `st_dev`, stubbed, is not entered), sealed `0555`/`0444` trees are removed,
    and the `ENOENT`, `ENOTEMPTY` and `EACCES` cases; `tests/unit/test_rawstore_sweep.py`
    (`empty_trash` order and limit); `tests/unit/test_raw_maintenance.py`:
    `test_maintenance_fails_closed_without_database` across all ten duties (no rename, no unlink,
    no row), `test_run_pass_follows_the_duty_order` with the ten names, and the root-swap
    parametrization gains `EmptyTrash`.
- Design: §18.4 duty 8; §18.6 rules 1 and 6; §9.8.5 (`empty_trash`, `remove_tree`); §9.8.6
  (module map); §18.2 G5–G8; D-65, D-116.
- Verification:
  - The plan-wide gate; the slice 6 clone total recorded.
  - The named tests and the root-swap case pass on real temporary roots before the duty joins
    `RawMaintenance` (the "Byte-moving duties" rule); `uv run pytest -m integration` passes.
- Dependencies: M12.5.
- Status: pending

## Milestone 13 — Legacy schema retirement and the local reset (slice 7)

Goal: the destructive half of OD-4: a development reset that clears legacy rows, shadow data, legacy
bytes and beta Polaris tables, then the guarded migration that drops the legacy tables.

### M13.1 Local reset: database and bytes

- Intent: the destructive half of OD-4 for one database and its data root: a development-only,
  idempotent script that clears the legacy Raw rows, the shadow hierarchy and the legacy bytes,
  dry by default (steps 1–2 of §10.11; the Polaris step follows in M13.2).
- Delete: none
- Create / Modify:
  - New `scripts/raw_reset.py` (usage `raw_reset.py [--apply]`; the Polaris flags arrive in
    M13.2): without `--apply` it prints every action as "would …" and changes nothing.
    `HURON_ENV` must be `development`, checked before any connection; `HURON_DATABASE_URL` and
    `HURON_DATA_ROOT` are required; exit 0 when done or nothing to do, 1 when refused or failed
    (nothing half-applied in the database), 2 on a usage error. It uses asyncpg.
    - Step 1, one transaction with `SET LOCAL lock_timeout = '5s'`: one `TRUNCATE` of the legacy
      tables that exist (`to_regclass`), naming `releases` too while it exists (D-177); delete the
      idempotency receipts of principal `huron-raw-web-provisioner` or of kind `ingest_session`,
      `ingest_commit`, `revision` or `release`, and the `revision.committed` outbox rows; find the
      shadow organizations, projects and datasets by their `pc-`/`ns-`/`ds-` plus 48-hex slugs
      and print their ids; delete their `role_bindings` and `policy_attachments`, then the
      datasets, projects and organizations. A foreign-key violation (23503) prints the
      referencing table and exits 1 with the transaction rolled back.
    - Step 2, after step 1 commits: `.staging/`, every `organization/*/project/*/dataset/*/raw/`
      and `…/releases/`, and every `organization/pc-<48 hex>--<32 hex>/` under `HURON_DATA_ROOT`
      are renamed, without following symlinks, into `<HURON_DATA_ROOT>/.raw-reset/<uuid4 hex>/<n>`
      and removed bottom-up, each directory made `0700` first and symlinks unlinked, never
      followed; a crashed run's `.raw-reset/` is emptied first. Catalog generation documents of
      every other entity stay.
  - New `tests/contract/test_raw_reset.py` (`postgres:16`, a temporary `HURON_DATA_ROOT`; the
    script run as a subprocess): the fixture is a database migrated to `0016_raw_uploads` holding
    one row in every legacy table `0017` will drop (the trigger-protected ones included), a shadow
    organization, project and dataset with a role binding, and an ordinary Catalog dataset with a
    sealed `raw/` subtree and generation documents. Cases: `test_reset_dry_run_changes_nothing`;
    `test_reset_apply_removes_exactly_the_legacy_state` (the legacy rows, receipts, shadow rows
    and legacy bytes go; the ordinary dataset row and every non-shadow generation document stay);
    `test_reset_apply_twice_has_nothing_to_do`; `test_reset_refuses_a_foreign_keyed_reference` (a
    `snapshots` row on the shadow dataset exits 1 with the database unchanged);
    `test_reset_from_below_0013` (a database at `0012` holding a legacy revision and a release:
    the dry run changes nothing, `--apply` truncates `releases` with the legacy tables, and
    `upgrade head` then succeeds; M13.3 adds the refusal that precedes the reset).
  - New `tests/unit/test_raw_reset_script.py` (the script imported with `scripts/` on
    `sys.path`, as it imports `polaris_dev`): the `HURON_ENV` refusal before any connection, exit
    2 on usage errors, the dry-run action list.
- Design: §10.11 (interface, steps 1–2, tests); §10.10 (reset, then upgrade); §21.2 rows 3, 11
  and 14 (data), 17 (the outbox rows); D-80, D-125, D-177; OD-4.
- Verification:
  - The plan-wide gate; `uv run ruff check scripts/raw_reset.py` and
    `uv run ruff format --check scripts/raw_reset.py`.
  - `uv run pytest -m contract` runs the five cases on Docker; `scripts/` lies outside
    `--cov=src/huron`, so these tests prove behaviour and count toward no coverage.
  - The contract tests name legacy tables and columns on purpose; the §21.2 closing checks in
    M14.7 exclude `tests/contract/test_raw_reset.py` as they exclude
    `tests/contract/test_catalog_store.py` (§21.3), and the Execution notes record it.
- Dependencies: M5.7, M12.6.
- Status: pending

### M13.2 Local reset: Polaris tables and the seed

- Intent: the reset's third step drops every generic table marked Raw that carries no property
  standard (the beta `huron-raw-v1` tables, the seeded NASA example and manual registrations),
  and the seed stops re-creating one (OD-10 O-4).
- Delete: none
- Create / Modify:
  - `scripts/raw_reset.py`: `--drop-polaris-tables` (acts only with `--apply`; otherwise it lists
    what it would drop) and `--polaris-state PATH` (default `<repo>/.local/polaris`; reads
    `admin.clientId` and `admin.clientSecret` from `credentials.json`). With
    `polaris_dev.obtain_token`, `request`, `REALM` and `BASE_URL`, it walks every catalog, every
    namespace breadth-first (levels joined by `%1F`) and every generic table (following
    `next-page-token`), loads each, and drops a table when it is marked Raw (its `format` is
    `raw`, or its `huron.dataset-type` is `raw`) and lacks `huron.raw.standard`; a `404` on drop
    counts as gone. It prints each dropped table with its `base-location`, marks a location that still holds
    files "left in place", and never prints a credential payload.
  - `scripts/seed_catalog_types.py`: stops registering its Raw table and keeps its Iceberg half
    (the Raw create body, its path constants and the retained-copy step only it uses go; the
    module docstring and the receipt follow); `scripts/test_catalog_types.py` follows.
  - `web/README.md` (the seed section, :59-81 at the baseline): the seed registers no Raw table;
    existing example registrations are dropped by the reset.
  - `tests/unit/test_raw_reset_script.py`: the walk against a stub `request` (catalog, nested
    namespace and table pages) and the drop rule's truth table over five tables (a beta
    `huron.raw.service = huron-raw-v1` table, the seeded NASA sample, a manual registration, a
    standard-2 table, a non-Raw table: only the first three drop); `--drop-polaris-tables` without
    `--apply` drops nothing.
- Design: §10.11 (step 3, tests); §15.6; §21.2 row 11 (data; the seed); D-80, D-125; OD-10 O-4.
- Verification:
  - The plan-wide gate; ruff check and format check on `scripts/raw_reset.py` and
    `scripts/seed_catalog_types.py`; `uv run pytest tests/unit/test_raw_reset_script.py`.
  - `scripts/test_catalog_types.py` with the Icechunk SDK runtime when it exists
    (`cd scripts && ../.local/polaris/icechunk-venv/bin/python -m unittest test_catalog_types`);
    otherwise it is reported not run with the reason.
  - Row 11's check `rg -n "raw_external_datasets|raw_catalog_publications|huron-raw-v1|huron\.raw\.service" src scripts web/src`
    prints only `scripts/raw_reset.py` lines.
- Dependencies: M13.1.
- Status: pending

### M13.3 Migration 0017_retire_legacy_raw

- Intent: the one destructive revision drops the nine legacy tables and four functions, refusing
  while legacy rows exist unless the operator consents, so the order is reset, then upgrade.
- Delete: none
- Create / Modify:
  - New `migrations/versions/0017_retire_legacy_raw.py` (`down_revision = "0016_raw_uploads"`):
    `upgrade()` refuses while any of the six guarded tables holds a row, unless
    `-x raw_reset=yes`: online a `RuntimeError` naming `scripts/raw_reset.py`; offline (`--sql`) a
    `DO $$ … RAISE EXCEPTION … $$` block ahead of the first drop. Then one DDL block through
    `migrations._ddl.execute_sql` drops `raw_catalog_publications`, `raw_external_datasets`,
    `ingest_recoveries`, `ingest_commit_intents`, `ingest_files`, `purge_records`,
    `revision_amendments`, `ingest_sessions` and `dataset_revisions` in that order without
    CASCADE, then `reject_raw_external_mutation()`, `reject_commit_intent_mutation()`,
    `protect_recovery_ownership()` and `ingest_session_revision_guard()`. `downgrade()` raises.
  - `migrations/schema.sql`: the twelve `0017` edits of §10.12 (the stamp; section 1's title; the
    `dataset_revisions`, `revision_amendments`, section 2, `purge_records` and trailing raw-web
    blocks deleted; the `retention_holds`, `lineage_edges`, `outbox_events`, `idempotency_records`
    and `reconciliation_findings` annotations; sections renumbered so Raw storage is section 6).
  - Tests that pin the previous head move to `0017_retire_legacy_raw`
    (`rg -n "0016_raw_uploads" tests`).
  - `tests/contract/test_catalog_store.py`: `test_postgres_catalog_constraints_at_head` migrates to
    `head` through `_migrate` and then `_assert_against` writes `dataset_revisions`,
    `purge_records`, `revision_amendments`, `ingest_sessions` and `ingest_files`, all of which
    this revision drops. It upgrades to `"0016_raw_uploads"` instead and becomes
    `test_postgres_catalog_constraints_before_the_legacy_raw_retirement`, its docstring saying
    why, as M3.1 pinned the release-retirement test to `0013`; `_migrate` goes once nothing calls
    it. The suite then migrates only to fixed revisions. §10.10 says the suite "migrates only to
    `0010_independent_raw`/`0011_verified_raw`, never to `head`", and §21.3 repeats "`0010`/`0011`";
    at `9882690` that was false (this test migrated to `head`, and M3.1 adds a pin to `0013`). This
    pin restores what that sentence was there to guarantee, §10.10's precondition that no test
    migrating to `head` names a dropped table, and the Execution notes record the correction.
  - Kept on purpose, not dropped by this revision or by the reset (D-123, D-124, §21.3):
    `reconciliation_findings`, where Raw writes its findings since M7.2; the `integrity.cutover`
    rows of `audit_events`, which keeps its rows forever; and the hand-made roles
    `huron_app_legacy`, `huron_app_verified` and `huron_cutover`, which stay with their
    administrator. M0.2's Execution note lists them as "dropped by the later legacy-retirement
    migration"; that clause is wrong, and this task's Execution note records the correction
    (the `DEGRADED` value of `dataset_revisions.state` does leave, with its table).
  - `design/api.html`: the "Planned P3 error codes" heading and the rest of its table
    (`#planned-p3-error-codes`: `RAW_REMOVAL_PENDING`, `RAW_CONTENT_REMOVED` and
    `REVISION_DEGRADED`; M5.5 removed `INGEST_RECOVERY_IN_PROGRESS`) and the "P3 integrity read
    admission (planned)" section (`#p3-read-admission`) leave with the tables of rows 8 and 9
    (§19.6, rows removed); `tests/unit/test_error_contract.py` parses only `table#error-codes`
    and is unaffected.
  - New `tests/contract/test_raw_retire_legacy.py`, the §10.10 cases: a fresh `upgrade head`
    reaches `0017_retire_legacy_raw` with `to_regclass` NULL for the nine tables and the four
    functions absent from `pg_proc`; a row in each guarded table in turn makes `upgrade head`
    raise naming the script, with `alembic_version` still `0016_raw_uploads` and the tables
    intact; the same with `Config.cmd_opts = Namespace(x=["raw_reset=yes"])` reaches head and
    leaves the fixture's shadow rows; offline `upgrade 0012:head --sql` renders the `DO $$` guard
    before the first `DROP TABLE`; at `0016` the reset, then `upgrade head` without the flag,
    reaches head.
  - `tests/contract/test_raw_reset.py::test_reset_from_below_0013` first asserts that
    `upgrade head` from `0012` refuses and leaves `0012` and `releases` in place (D-177).
- Design: §10.10; §10.12 (the `0017` edits); §10.1; §19.6 (rows removed: the planned P3 table);
  §21.1 rule 3; §21.2 rows 5, 7, 8, 9, 10 and 11 (SQL) and 17; §21.3 (kept on purpose); D-79,
  D-123, D-124, D-177.
- Verification:
  - The plan-wide gate (`uv run python scripts/check_schema_map.py` sees the new head);
    `uv run pytest -m contract` on Docker, including `tests/contract/test_raw_schema.py`
    unchanged over its eight Raw tables.
  - §10.10's precondition `rg -n "\b(dataset_revisions|ingest_sessions|ingest_files|ingest_commit_intents|ingest_recoveries|revision_amendments|purge_records|raw_external_datasets|raw_catalog_publications)\b" src/huron/core/metastore`
    prints nothing.
  - The same names in `tests`: `rg -n "\b(dataset_revisions|ingest_sessions|ingest_files|ingest_commit_intents|ingest_recoveries|revision_amendments|purge_records|raw_external_datasets|raw_catalog_publications)\b" tests --glob '!tests/contract/test_catalog_store.py' --glob '!tests/contract/test_raw_reset.py' --glob '!tests/contract/test_raw_retire_legacy.py' --glob '!tests/unit/test_raw_reset_script.py'`
    prints nothing (a straggler it finds is fixed in this task), and
    `rg -n '"head"' tests/contract/test_catalog_store.py` prints nothing, so every remaining
    legacy-table use there runs at a pinned revision.
  - Row checks print nothing: `rg -n "RECOVERING|ingest_recoveries|ingest_commit_intents|INGEST_RECOVERY" src`,
    `rg -n "PREPARING|UPLOADING|VERIFYING|ExpirySweep|expire_lapsed|DATASET_LOCKED" src` and
    `rg -n "purge_records|RAW_REMOVAL_PENDING|RAW_CONTENT_REMOVED|REVISION_DEGRADED" src design/api.html`.
  - `tests/contract/test_raw_retire_legacy.py` names legacy objects on purpose; M14.7's closing
    checks exclude it like `test_raw_reset.py`.
- Dependencies: M6.1, M13.2.
- Status: pending

## Milestone 14 — Documentation and closing gates (slices 8–9)

Goal: reconcile every statement the change made false, then prove the closing gates.

### M14.1 Vocabulary, agent rules and operator docs

- Intent: the glossary, the agent rules, the developer and operator documentation and the web
  docs describe the built Raw storage in version vocabulary, and the operator procedures the
  decisions point at exist (row 18's documents outside `design/`).
- Delete: none
- Create / Modify:
  - `CONTEXT.md`: exactly the §7.1 text (load `domain-modeling`); the owner's Organization,
    Polaris realm and Catalog entries and their two relationship lines stay byte for byte.
  - `AGENTS.md` (load `writing-for-agents`): the `raw/` package line (datasets, upload sessions,
    tus transfer, version publication and reads, the metadata schema registry and maintenance);
    "Raw owns storage-first publication and its single-connection transaction recording version,
    session outcome, audit and retry receipt" (no outbox, D-71); the scientific-workflow contracts
    in version vocabulary (a successful upload creates a new immutable version; required version
    metadata validated against the dataset's pinned schema; a retry of the same upload identity
    returns the same version), without the `0010_independent_raw` ledger sentence as current
    behaviour; the acceptance line names the 2 GiB rehearsal (`uv run pytest -m acceptance -k
    rehearsal`) beside the 25 GiB gate.
  - `README.md`: Raw datasets are immutable versions in each catalog's storage under Polaris
    grants, not a revisioned NFS layer.
  - `docs/backend-design.md` (:14-17, :31 and the Polaris row), `docs/index.md` (:15-16) and
    `docs/getting-started/*`: `local-development.md` (the `HURON_RAW__*` settings, the two local
    storage roots, reset then upgrade; the retired `HURON_INGEST_SWEEP_*` rows gone),
    `conventions.md` (`huron.schema.raw_layout` instead of `core/raw/paths.py`),
    `repository-layout.md` (the `core/raw` and `core/rawstore` lines; versions instead of
    revisions), `testing.md` (the Raw suites by boundary).
  - `docs/history.md`: a "Raw storage redesign" receipt (date, owner decisions, what replaced
    revisions, parts, raw-web and the shadow hierarchy, releases, Raw layers and amendments, and
    `0017_retire_legacy_raw`); a superseded note only where it links a removed page.
  - New `docs/operations/raw-storage.md` and its `zensical.toml` nav entry (an "Operations"
    section): configuring `HURON_RAW__STORAGE_ROOTS` and reading a root's `.huron/root.json`
    (D-11, D-17, D-172); the local reset and its order, reset then upgrade, including
    `-x raw_reset=yes` (§10.10, §10.11); restoring parked bytes by hand within the retention
    period (D-49); inspecting `.huron/quarantine/` and the Raw findings, including separating two
    aliased datasets, a HELD target and a cross-device placement (§18.2 E8, E15–E17; D-66);
    rewriting a `raw_realm_bindings` row in a reviewed SQL step, with §10.5's statement block
    verbatim (D-7). It also carries every rule the design assigns to "the operator docs":
    - every catalog's `default-base-location` lies strictly below its storage root, never equal to
      it (§9.3 "Operator rule: catalogs sit below a root", D-91);
    - a referenced root keeps its `key` and `uri` while an unpurged dataset names it, and its
      mount (`path`) may move, because the sentinel travels with the storage (§9.3, D-17, D-91);
    - other table writers in namespace directories Huron created get a shared group with write
      access there (§9.4, D-91);
    - volumes are mounted before the API starts (`require_mount: true` for mounted roots), and
      re-initializing a recorded root key is an explicit operator step (§9.2, D-172);
    - catalogs that enable Polaris's non-default location modes
      (`DEFAULT_LOCATION_OBJECT_STORAGE_PREFIX_ENABLED`, `DEFAULT_UNIQUE_TABLE_LOCATION_ENABLED`)
      are out of scope (§9.5);
    - the §23.2 operator thresholds: R3 (after a `RAW_FOREIGN_VERSION_QUARANTINED` finding, write
      access to Raw dataset roots is restricted to the API's account), R6 (lower
      `HURON_RAW__MAX_FILES` until a `MAX_FILES` commit fits the wizard's 600 s budget), R7
      (`HURON_RAW__CHUNK_BYTES` of 8 MiB for links slower than about 0.9 Mbit/s) and R9
      (`HURON_RAW__CHUNK_DEADLINE_SECONDS` of 300 while the BFF is the only client).
  - `web/README.md`: tus uploads and versions instead of parts and revisions, property standard 2
    instead of `huron-raw-v1`, the storage roots (`file://<repo>/.local/polaris/storage/<catalog>/`
    for catalogs created in the web admin), seeding, and no layers for Raw (rows 6, 11 and 14:
    :189-195 and :219-223 at the baseline); the R16 sentence stays if M10.10 adopted buffering.
  - `web/src/lib/api/README.md` (:19-27): the Raw seam (`raw-ingestion-types.ts`,
    `raw-ingestion-client.ts`: views, parsers, `RawApiError`, `requestWithRetry`, the browser
    calls).
- Design: §7.1; §7.3; §21.2 row 18 (CONTEXT.md, AGENTS.md, README.md, `docs/backend-design.md`,
  the web docs) and rows 6, 11, 14 (text); §21.4; §20.8; §4 rows 19–22; §9.2–§9.5 and §10.5 (the
  operator rules); §23.2 (R3, R6, R7, R9); D-4, D-87, D-91, D-148, D-172.
- Verification:
  - The plan-wide gate; `make docs` (strict); the web gate.
  - `diff <(awk '/^````markdown$/{f=1;next} /^````$/{f=0} f' RAW_STORAGE_DESIGN.md) CONTEXT.md`
    prints nothing.
  - `rg -n -i "revision" CONTEXT.md AGENTS.md README.md docs/index.md docs/backend-design.md docs/getting-started docs/operations web/README.md web/src/lib/api/README.md`
    prints nothing about Raw (Catalog's own uses, if any, stay); `git diff --check` is clean.
- Dependencies: M13.3.
- Status: pending

### M14.2 Design record: API, Polaris, frontend and Raw layer pages

- Intent: the four design pages that describe the Raw surface, its bridge and its layout match
  the built behaviour.
- Delete: none
- Create / Modify:
  - `design/api.html` outside §7, per §19.7's table: the preamble (`If-Match` gains "(a Raw
    dataset's `etag`)"; "Idempotency-Key on POSTs that create a resource whose identity the
    caller cannot name in advance"; the sentence on the Raw delegation and the tus exceptions);
    §1's sentence that Raw routes accept none of its credentials; §2 without release rows; §3
    "3. Raw storage" (`id="raw"`) checked complete against the 33 routes, with its three notes
    and without the `_session_view` paragraph; §4's Bronze intake rows without `/transfer` and
    "the same session shape as raw ingest"; §6's `/schemas` rows pointing to ADR 0003 and
    `/api/v1/raw/schemas/...`, the two-person purge row removed, the reconciliation-report row
    without the lakectl sentence and with Raw's `RAW_*` findings, and the `/readyz` row text.
  - `design/polaris.html` (:92-94, :98, :102-103, :136 at the baseline): no internal hierarchy;
    registration at creation by the BFF under the user's principal, which drops the table on
    delete; "and Raw identities" removed; standard 2 instead of `huron.raw.service`, and no
    `huron.layer` validation for Raw; the example registrations cleared by the reset.
  - `design/frontend.html` (:87, :94, :100, :105): the tus wizard with server-side resume;
    registration at creation; no layer for Raw; an upload completes as a committed version of an
    already registered dataset.
  - `design/layer-raw.html`: :93-98 and its layout, part-protocol, release and layer sections
    rewritten to the built design (storage roots and `.huron/`, the dataset root at the catalog
    location, `versions/<NNNNNN>/` with `version.json`, tus 1.0.0 transfer and the commit
    protocol, the dataset and version lifecycles with park and purge, the maintenance duties);
    Catalog's raw entry layer recorded as filled by no route (D-153).
- Design: §19.7 (design/api.html outside §7); §21.2 row 18 (the four pages); §4 rows 9–14 and 18;
  §12; §15; §20; D-147, D-153.
- Verification:
  - The plan-wide gate (`tests/unit/test_error_contract.py` still parses `table#error-codes`);
    `git diff --check`.
  - Every `href="#…"` in the four pages names an existing `id`, and every cross-page link
    resolves (a short script over the pages, run and discarded).
  - `rg -n -i "revision|/api/raw-web|huron-raw-v1|raw-web|part protocol|release tag" design/api.html design/polaris.html design/frontend.html design/layer-raw.html`
    prints only sentences that name retired behaviour as retired.
- Dependencies: M14.1.
- Status: pending

### M14.3 Design record: decisions, roadmap, catalog search, architecture and core map

- Intent: the decision index, the roadmap and the architecture pages record what the redesign
  built and retired.
- Delete: none
- Create / Modify:
  - `design/index.html`: decisions 7 (Polaris catalogs each Raw dataset as one generic table,
    OD-1), 14 (release tags retired; full versions only), 15 (entry layers are Catalog's; Raw has
    none), 16 (narrowed for Raw by ADR 0003: PLATFORM and CATALOG scopes, the rest future work),
    a note on 17 (a Raw dataset is PENDING only until its table is registered: a system state,
    not an approval gate); the Core map card where it names Raw responsibilities.
  - `design/roadmap.html`: the Raw rows P2, P3, P5, P10, T1 and T2 (what was built, what was
    retired), the package map (:114), the SDK line (:143-145: only the `RawAuthority` seam;
    scripted uploads return with the SDK and API-key path, OD-8) and :368-382.
  - `design/catalog-search.html`: decision 16 points to `docs/adr/0003-raw-metadata-schema-registry.md`.
  - `design/architecture.html` and `design/core-map.html`: Raw's responsibilities (datasets,
    upload sessions, tus, versions, the registry, maintenance), its modules (`core/raw`;
    `core/metastore/raw_datasets.py`, `raw_schemas.py`, `raw_memory.py` (the shared in-memory Raw
    state, deviation 7) and `ingest.py`; `core/rawstore/{roots,sweep}.py`; the tus modules
    `routes/v1/{endpoints,schema}/tus.py`, deviation 6), PostgreSQL's Raw tables, and the
    invariants that changed.
- Design: §21.2 row 18 (index, roadmap, catalog-search); §16.12; §4 rows 1–8, 15–17, 20–22;
  D-59, D-153.
- Verification:
  - The plan-wide gate; `git diff --check`; anchors and cross-page links resolve as in M14.2.
  - `rg -n -i "revision" design/index.html design/roadmap.html design/catalog-search.html design/architecture.html design/core-map.html`
    prints only sentences that name retired behaviour as retired.
- Dependencies: M14.2.
- Status: pending

### M14.4 UML atlas: rawstore

- Intent: the rawstore atlas, a dated implementation snapshot, is re-traced against the built
  `core/rawstore` and re-rendered (row 18).
- Delete: none
- Create / Modify:
  - `design/rawstore-uml.md`: the snapshot line names the date and commit traced; the sections
    describe `PosixStorageRoots` (mounts, sentinels, availability, confirmation, dispatch),
    `PosixRawStore`'s `UploadArea` and `VersionArchive` mechanics, `sweep.py`, `publish_version`
    and `commit_envelope`, `verify_envelope(..., digests=False)`, `materialize.py` with
    `descendant(..., mode=)` and `remove_tree`, `CompletionAdmission.reserve`, and the
    `huron.schema.storage` values and errors they share; the retired sections (the `RawStore`
    port, part receipt, tags and the revision index, maintenance inspection and the integrity
    port) leave.
  - `scripts/render_uml_atlas.py`: the `rawstore` entry of `ATLASES` (lead, description, badges,
    hints) stops naming revisions and integrity evidence.
  - `design/rawstore-uml.html`: re-rendered with
    `uv run python scripts/render_uml_atlas.py rawstore --chrome "<local Chrome or Chromium>"`
    (Mermaid CLI 11.17.0 through `npx`, or `--mmdc`); the HTML is never edited by hand.
- Design: §21.2 rows 1 and 18 (the UML atlases); §9.8 (the storage port contract and the POSIX
  adapter); §9.8.6 (module map).
- Verification:
  - The plan-wide gate; the renderer exits 0, and `git diff --stat design/rawstore-uml.html`
    shows the regenerated page.
  - Every class and method the atlas names exists in `src/huron/core/rawstore` or
    `src/huron/schema/storage.py` (the verifier checks each against the source);
    `rg -n -i "revision|write_part|write_tag_once|INDEX\.json|integrity port|core\.integrity" design/rawstore-uml.md`
    prints nothing.
  - If Chrome or Mermaid CLI is unavailable, the task stops and reports it; it does not edit the
    HTML by hand.
- Dependencies: M14.3.
- Status: pending

### M14.5 UML atlas: metastore

- Intent: the metastore atlas is re-traced against the built adapters and re-rendered (row 18).
- Delete: none
- Create / Modify:
  - `design/metastore-uml.md`: the snapshot line; the Raw adapters
    (`core/metastore/raw_datasets.py`: the dataset and maintenance stores, in memory and
    PostgreSQL; `raw_schemas.py`; `raw_memory.py`, the one state the in-memory Raw stores share
    (deviation 7); the re-created `ingest.py`: the upload store with its offset ledger and the
    version store; the `rows.py` mixins, `bind_realm` included); the hierarchy
    adapter without revisions, sessions or outbox writes; section 9 (maintenance and the legacy
    cutover) and section 5 (the ingest-ledger mixins) replaced; the conformance and composition
    sections follow `ApiRuntime` and `RawPorts`.
  - `scripts/render_uml_atlas.py`: the `metastore` entry of `ATLASES` stops naming the Raw ledger
    and maintenance adapters of the old design and counts the adapter declarations again.
  - `design/metastore-uml.html`: re-rendered with `render_uml_atlas.py metastore`, never edited by
    hand.
- Design: §21.2 row 18 (the UML atlases); §8.7.5 (adapters); §10 (the Raw tables); §22.3.
- Verification:
  - The plan-wide gate; the renderer exits 0; every class and method the atlas names exists in
    `src/huron/core/metastore`; `rg -n -i "revision|ingest_sessions|metastore\.legacy|cutover|raw_web" design/metastore-uml.md`
    prints nothing.
  - A missing Chrome or Mermaid CLI stops the task, as in M14.4.
- Dependencies: M14.4.
- Status: pending

### M14.6 UML atlases: catalog and rbac

- Intent: the catalog atlas's Raw half and the rbac atlas are re-traced against the built
  `core/raw` and Security, and both are re-rendered (row 18).
- Delete: none
- Create / Modify:
  - `design/catalog-uml.md`: the snapshot line; the Raw half re-traced: the aggregates
    (`RawDataset`, `UploadSession` and `UploadFile`, `Version`, `SchemaSubject` and
    `SchemaVersion`), the values (`locations.py`, `grants.py`, `admission.py`, `properties.py`,
    the documents, and `UploadSession`'s `FrozenCommit` and `SchemaPin`, deviation 8), the
    services (`DatasetService`, `UploadService`, `CommitDriver`, `FileVerifier`,
    `VersionReadService` and `VersionFiles`, `SchemaRegistry`, `RawMaintenance` and its ten
    duties, `RawRuntime` and `RawPorts`), the ports and the errors; sections 2, 6, 7 and 8 no longer
    show revisions, releases, `core/raw/paths.py`, amendments or layer rules for Raw (Catalog's
    layers stay); the composition sections follow `ApiRuntime` and `RawRuntime`.
  - `design/rbac-uml.md`: no Raw guards, no `release.create`, no Raw use of Huron role bindings;
    the `raw` layer qualifier stays (§21.3).
  - `scripts/render_uml_atlas.py`: the `catalog` and `rbac` entries of `ATLASES` follow.
  - `design/catalog-uml.html` and `design/rbac-uml.html`: re-rendered with
    `render_uml_atlas.py catalog rbac`, never edited by hand.
- Design: §21.2 row 18 (the UML atlases); §8 (the domain model); §8.2 (package placement); §21.3.
- Verification:
  - The plan-wide gate; the renderer exits 0; every class and method the two atlases name exists
    in `src/huron`; `rg -n -i "revision|release tag|release\.create|amendment|IngestService|RawWebOperations" design/catalog-uml.md design/rbac-uml.md`
    prints nothing.
  - A missing Chrome or Mermaid CLI stops the task, as in M14.4.
- Dependencies: M14.5.
- Status: pending

### M14.7 Closing gates

- Intent: prove the end state: the vocabulary gate, every §21.2 row check and every gate pass on
  the final tree, and record the numbers the merge into `main` depends on.
- Delete: none (a straggler that needs a whole-file deletion is reported to the orchestrator)
- Create / Modify: only stragglers the checks find, each fixed in the file it belongs to.
- Design: §7.3; §21.1 rule 5; §21.2 (every row's check); §21.3; §22.1; D-1, D-152.
- Verification:
  - The D-1 gate `rg -n -i "revision" src/huron/core/raw src/huron/core/rawstore src/huron/applications/api/routes/v1 src/huron/schema/raw_layout.py`
    prints nothing, comments and docstrings included.
  - Every §21.2 row check prints nothing outside `migrations/versions/`, `docs/history.md` and the
    design documents, with `tests/contract/test_raw_reset.py` and
    `tests/contract/test_raw_retire_legacy.py` excluded beside `tests/contract/test_catalog_store.py`
    because they exercise the retirement itself: rows 1, 2a, 2b, 3, 4, 5, 6 (with its Vitest
    case), 7, 8, 9, 10, 11 (only `scripts/raw_reset.py`), 12, 13, 14 and 15 (with
    `test ! -e 'web/src/routes/[org]/[project]/[dataset]/[release]'`); the commands are run as
    written in §21.2, except that row 6's check also names
    `src/huron/applications/api/routes/v1/endpoints/tus.py` beside `endpoints/raw_*.py`
    (deviation 6), as in M11.4.
  - The full plan-wide gate; the web gate with `npm run test:e2e`; `make docs`;
    `uv run pytest -m acceptance -k rehearsal`.
  - The Execution notes record the final unit, contract, integration, Vitest and Playwright
    counts, the coverage floor, the clone total against 144, and the status of the 9 GiB gate and
    of `uv run pytest -m polaris` (each "passed" with its run, or "not run" with the reason); both
    must pass before `raw-storage` merges into `main` (OD-12 O-7, D-143).
- Dependencies: M14.6.
- Status: pending

## Risk register

The entries draw on §23.1's five risks, as §23 requires: R15 (entry 2), R16 (entry 3), R5
(entry 4), R11 (entry 6, with its legacy-removal case as entry 1) and R4 (entry 7). Entry 5 is an
addition for the merge gate of OD-12 O-7.

1. **Legacy engine removal and same-name re-creation (M5.1–M5.7, then M6.2, M6.3, M6.8, M7.13).**
   Symptom: collection or import errors in surviving tests; `check_duplication.py` reporting a
   changed signature for the clone groups of `raw/_impl/ingest.py`, `raw/_impl/ingestion.py` or
   `metastore/ingest.py`; newly missed lines in a kept module once a legacy suite is gone (measured
   for `core/raw/manifest.py` and `streams.py`); the unit total under `fail_under`.
   Fallback decision point: a signature the baseline lacks is accepted only through §22.5's
   bootstrap or hand-edit review; if the result would exceed 144 clones or grow a known signature
   and refactoring does not fit the task's three attempts, the task escalates under
   implement-markdown. If M5.3 overruns its attempts on size alone, anything it removes that keeps
   its own tests moves into M5.4, inside the declared transition; the v1 ingest surface and the
   engine services never split.
2. **Commit, ledger and claim races (M6.5, M7.4, M7.5, M7.10–M7.16, M8.6, M8.7, M12; R15).**
   Symptom: SQLSTATE 23514 from `raw_versions_contiguous` or a deferred counter trigger surfacing
   as `500`; `RAW_UNRECORDED_VERSION_DIRECTORY`, `RAW_STAGING_DAMAGED` or `RAW_COMMIT_STALLED`
   findings; an intermittent named race test (`test_concurrent_patch_newest_writer_wins`,
   `test_100_concurrent_commits_gap_free`,
   `test_concurrent_publishers_never_fail_a_published_session`).
   Fallback decision point: the first occurrence stops the milestone owning the mechanism until a
   fix lands with a new named test reproducing the interleaving; a repeat on the same mechanism
   goes to `/architectural-review` before any later task of that milestone starts.
3. **The streamed tus PATCH through the BFF (M9.4, measured in M10.10; R16).** Symptom: in the
   rehearsal the BFF's resident memory grows with the chunk size or the number of parallel
   uploads; PATCHes end in `503 DEPENDENCY_UNAVAILABLE` after 300 s; the API logs
   `TUS_BODY_INCOMPLETE` for streams the browser completed; the resume spec's two-PATCH assertion
   fails. Fallback decision point: a recorded peak more than one chunk per in-flight PATCH above
   idle, or a hang the §12.14 cases do not reproduce, switches the BFF to per-chunk buffering (at
   most `HURON_RAW__MAX_CHUNK_BYTES`) with unchanged headers and delegation, in M10.10 or the next
   web task, and `web/README.md` states the memory cost.
4. **Byte-moving storage steps (M8.5, M12.3–M12.6; R5).** Symptom: `/readyz` failing on a
   referenced root; Raw routes answering `503 RAW_STORAGE_UNAVAILABLE` with `Retry-After: 60`;
   `RAW_VERSION_DIRECTORY_MISSING` or `RAW_PARKED_DIRECTORY_MISSING` findings after a remount.
   Fallback decision point: each duty lands only when its §18.6 test and the root-swapped-for-empty
   case pass on real temporary roots; a finding that a duty acted on a root whose sentinel did not
   verify removes that duty from `MaintenanceLoop` until a fix with a named test lands, and the
   operator restores parked bytes by hand per `docs/operations/raw-storage.md`.
5. **The 9 GiB acceptance gate (M10.10; OD-12 O-7).** Symptom: `require_upload_capacity` raises on
   this host (about 12 GiB free), or the `Acceptance` workflow's `df -h .` shows less than 25 GiB,
   or the job exceeds its 30-minute timeout. Fallback decision point: every upload-path task from
   M10.10 on runs the 2 GiB rehearsal; the 9 GiB run is reported not run with the reason until the
   owner provides a ≥ 25 GiB APFS/ext4 volume or pushes the branch for the workflow (raising
   `timeout-minutes` once the rehearsal's timings are known); `raw-storage` is not merged into
   `main` without a recorded green run.
6. **A gate fails on arithmetic rather than on a defect (every task; R11).** Symptom: `Coverage
   failure: total of X is less than fail-under=Y` while every touched file passes the per-file
   rule; `check_duplication.py` reporting a changed signature of a known clone group after a
   rename or deletion; radon reporting a C-grade function, complexipy a score above 15, or pyscn a
   cyclomatic complexity above 10. Fallback decision point:
   - Coverage: when the verifier's comparison (§22.4 step 2) attributes the whole shortfall to
     deleted covered statements, to new statements in D-84 adapter modules that the
     unit-and-contract run covers in full, or to both, the task resets the floor (OD-11,
     OD-12 O-8) and records the counts; any other shortfall is a missing test, which the task adds.
   - Duplication: the task first refactors the duplicate away; otherwise the baseline is replaced
     by a bootstrap after the orchestrator's `git rm` or by a reviewed hand edit, accepted only
     under §22.5's four checks. When the result would exceed 144 clones, grow a known signature
     or keep a new one the verifier cannot trace, and refactoring does not fit the task's three
     attempts, the task escalates under implement-markdown.
   - Complexity: the task splits the function along its domain boundaries; it never adds a
     suppression.
7. **The BFF drops a table it does not own (M9.6; R4).** Symptom: a table created at a Raw
   dataset's former name disappears seconds after that dataset's delete or "Finish deletion", and
   its owner reports lost grants. Fallback decision point: `classifyRawTable` decides every drop
   and the Vitest case `drops only its own table` pins it, leaving a one-round-trip window. If a
   Polaris release offers a conditional drop (by entity id or ETag), the next web task adopts it in
   `deleteRawDataset`. The first observed foreign drop goes to the owner, who alone decides
   whether the drop moves to the user, who would drop the table by hand in Polaris (OD-5), or the
   window is accepted.

## Definition of done

- Every task passed verification: each of M1.1–M14.7 passed with the full Python gate (lint chain,
  unit coverage at or above the recorded `fail_under` with every touched file at 100 %, contract
  and integration on Docker) plus its web, docs and rehearsal gates, and was committed by the
  orchestrator.
- The full gate is clean on the final tree: the plan-wide Python gate, `make docs`, the web gate
  with `npm run test:e2e` and the 2 GiB rehearsal all pass on the commit that closes M14.7.
- Execution notes record every floor reset with before/after counts, every duplication-baseline
  edit with the running clone total (≤ 144), every whole-file deletion and rename, every
  deviation, the R16 decision, and the status of the Polaris parity and 9 GiB runs.
- The D-1 gate prints nothing, and every §21.2 row check prints nothing outside
  `migrations/versions/`, `docs/history.md`, the design documents and the contract suites that
  exercise the retirement itself (`tests/contract/test_catalog_store.py`, `test_raw_reset.py` and
  `test_raw_retire_legacy.py`).
- The Alembic head is `0017_retire_legacy_raw`; contract tests prove `0014`–`0017` on
  `postgres:16` (66 Raw objects in the map test; the nine legacy tables and four functions gone);
  `scripts/raw_reset.py` works dry and with `--apply`.
- The 33 routes of §19.3 live under `/api/v1/raw` with the BFF delegation as the only credential;
  `/api/raw-web` and the v1 ingest, transfer and revision routes are gone; the OpenAPI document
  carries 17 tags; design/api.html §7 matches the live error classes, with the `Retry-After`
  column.
- Integration proves create → register → start → tus PATCH → verify → commit → read and Range
  download → archive → delete → park → purge, the two-process takeover and tuspy interop; all ten
  duties run in `MaintenanceLoop` with the §18.6 safety tests green.
- The web gate passes with Playwright (ingestion with resume, lifecycle, metadata schemas,
  organizations, dataset types), and the Svelte autofixer is clean on every changed component.
- The 2 GiB rehearsal passes locally, and before `raw-storage` merges into `main`,
  `uv run pytest -m polaris` passed against the owner's stack or a CI job.
- The 9 GiB acceptance gate is recorded per OD-12 O-7: a green `uv run pytest -m acceptance` run
  on an APFS or ext4 volume with at least 25 GiB free, or in the `Acceptance` workflow once the
  branch is pushed, is recorded under "Execution notes" with where it ran and its timings. Until
  then the 2 GiB rehearsal runs locally, the 9 GiB gate is recorded as not run with the reason,
  and `raw-storage` is not merged into `main`.
- CONTEXT.md, AGENTS.md, README.md, `docs/` (with `docs/operations/raw-storage.md` in the nav and
  `make docs` strict), ADR 0003, the design pages, the roadmap and the UML atlases describe the
  built behaviour; none describes revisions, parts, releases, layers, raw-web or the shadow
  hierarchy as current Raw behaviour.

## Verification

This section records how the plan answers the plan review of 2026-10-21: coverage findings
COV-01 to COV-19 and execution findings EX-01 to EX-17, of which COV-01, EX-01, EX-02, EX-03 and
EX-04 were blocking. Task numbers are the current ones. Splitting the commit driver (EX-14)
inserted a new M7.12, so the former M7.12–M7.15 are now M7.13–M7.16, and every reference was
renumbered; a finding's "M7.12" now reads M7.12 or M7.13, and its "M7.13", "M7.14" and "M7.15"
read M7.14, M7.15 and M7.16. The Execution notes were left unchanged. Where a finding asked for
an entry there, the task that lands the change now writes it.

Fixed:

- COV-01 (blocking): M7.3 adds `READINESS_TIMEOUT_SECONDS` and `available_roots(sweeper, keys)`
  to `core/raw/maintenance.py`. Each configured key (from `placement.roots`) is probed with
  `asyncify(sweeper.root_available, abandon_on_cancel=True)` under `anyio.fail_after`, and a
  timeout counts as UNAVAILABLE. The answer reaches `work.claim(..., roots=…)` through
  `VerifyFiles(verifier, sweeper, keys)` and `FileVerifier.run(batch, *, roots)`. Two tests
  cover it: `test_verify_files_skips_an_unavailable_root` and
  `test_root_probe_timeout_counts_as_unavailable`. M7.16, M12.2, M12.3, M12.4, M12.5 and M12.6
  cite the helper.
- COV-02: a plan-wide "Composition root" rule. M4.7 introduces `RawPorts` and the §8.6.8
  constructor, keeping the old engine's keywords until M5.3. M6.7, M6.9, M7.3, M7.4, M7.5, M7.13
  and M8.7 list `core/raw/runtime.py` with the field or keyword each adds.
- COV-03: M7.13 adds `ApiStores.raw_versions`, `PostgresVersionStore` in `_postgres_stores`,
  the in-memory version store in `memory_stores()` and the conformance asserts. M10.8's harness
  bullet now says what changes.
- COV-04 and EX-12: the plan-wide "Gate" rule runs `npm run test:e2e` in every task that changes
  the lifespan, `_build_runtime`, `core/raw/runtime.py`, the conformance asserts, `ApiStores` or
  `memory_stores()`. M5.3, M5.7, M6.7, M6.9, M7.3, M7.4, M7.5, M7.13 and M7.16 also name it.
- COV-05: M7.14 adds `test_freeze_and_verifier_reset_serialize` in both lock orders. The optional
  in-memory twin was not added: the in-memory store runs every transaction under one lock, so it
  would prove nothing beyond the contract case.
- COV-06 and EX-14: the new M7.12 holds `VersionDocument.compose` (listing
  `core/raw/documents.py`, with `test_version_document_compose_round_trips`), the session's commit
  decisions and the two error classes `freeze` raises first. M7.13 keeps the driver,
  `UploadService.commit` and the wiring. M2.3 and M6.2 point at M7.12.
- COV-07: M14.1's `docs/operations/raw-storage.md` bullet adds catalogs below a root, immutable
  keys and URIs with movable mounts, the shared group, mounting before start and re-initializing
  a recorded key, the out-of-scope Polaris location modes, the §10.5 SQL verbatim, and the R3,
  R6, R7 and R9 thresholds.
- COV-08: the risk register names its §23.1 sources and adds entry 6 (R11, with its coverage,
  duplication and complexity fallbacks) and entry 7 (R4). The 9 GiB entry stays as an addition.
- COV-09: M3.6 adds `test_fifty_concurrent_distinct_registrations_number_gap_free`.
- COV-10: M7.14 adds `test_max_files_commit_timing` and records its durations against the BFF's
  300 s window, with R6's decision point.
- COV-11: M10.7's `startSession` refuses a selection over the `GET /limits` sizes before
  hashing, with a Vitest case, and M10.8 passes it the limits.
- COV-12: on a resume without a draft, M10.9 asks "Commit as version N + 1", with a Playwright
  case.
- COV-13: M7.3 adds the L3 case `test_verified_copy_runs_off_the_loop_inside_verify_threads`, and
  M7.15 adds `test_commit_publication_runs_off_the_loop`. M5.3 names both as successors.
- COV-14: deviation 6 in the plan-wide "Deviations" rule. M7.7 names the tus module explicitly in
  the Raw composition tests, and M11.4 and M14.7 add `endpoints/tus.py` to row 6's check.
- COV-15: `test_delegation_lifetime_rules` (M3.2), `retries a network error from HEAD` (M10.1)
  and `test_namespace_location_mismatch_refused` (M2.5).
- COV-16: M4.6 adds `test_conflict_on_unavailable_root_is_503` and
  `test_replay_of_a_discarded_create_is_404`, and M4.8 adds their route twins. M12.1 adds
  `test_commit_after_prune_is_404`.
- COV-17: M7.5's `_on_staging_missing` runs the D-42 abort transaction with its
  `raw.session.aborted` row, which the named tests of M7.5 and M7.8 assert.
- COV-18: deviations 7 (`raw_memory.py`) and 8 (`SchemaPin`) are added to the plan-wide rule and
  noted in M3.5 and M6.2 for their Execution notes. M14.3, M14.5 and M14.6 name both.
- COV-19: M13.3 states that `reconciliation_findings`, the `integrity.cutover` audit rows and the
  three hand-made roles are kept (D-123, D-124, §21.3). Its Execution note records the correction
  of M0.2's note, which stays as written because the Execution notes are a record.
- EX-01 (blocking): M9.5 moves `web/src/routes/ingestion/+page.server.ts` to the classifier and
  says what the wizard receives. M9.5's verification lists the remaining `managedRawDatasetId`
  users, so M9.6's existing check prints nothing once M9.6 deletes the function.
- EX-02 (blocking): M13.3 pins and renames `test_postgres_catalog_constraints_at_head`, adds the
  tests-scoped grep and a `"head"` check, and corrects the "0010/0011" claim. M5.6 removes
  `dataset_revisions` from `_HIERARCHY_TABLES`.
- EX-03 (blocking): M5.7 lists both suites with direction. The inspection cases are re-pointed
  with their anchor; each materialize case is rewritten against a kept primitive or deleted with
  a named successor. The false measurement claim gives way to the measured figures, re-measured
  here (28.12 % and 92.91 %, lines 35–40, 134, 164 and 167), and a coverage check is added.
- EX-04 (blocking): the checks in M5.3, M5.6, M5.7 and M10.2 exclude
  `tests/contract/test_catalog_store.py`, and M5.6 edits the `test_stores_ports.py` docstring.
- EX-05: M5.4 deletes the `freeze_commit` case from `test_raw_documents.py` and excludes
  `core/raw/ingest.py` from its grep.
- EX-06: M5.3 and M5.4 remove the two stale imports. M5.5's grep adds `IngestLease`, `FileState`
  and `UploadAction`, plus a check that nothing imports the deleted module; that check replaces
  the suggested `FileResetReason`, a name the legacy module never had.
- EX-07: the "Composition root" rule and the task bullets above. These include both test modules
  in M4.7 and M5.3, `ApiStores.raw_versions` in M7.13, `limits` in M8.7, and the
  `test_rawstore_completion_admission.py` caller in M2.7.
- EX-08: M1.3 names five cases for the inherited gaps (`dev.py` line 45, `apikeys.py` lines 124
  and 189, `raw_web.py` line 83, `guards.py` line 426). M2.3 names
  `test_file_completion_retries_after_a_concurrent_parts_update` for `_impl/ingest.py`. No
  verifier exception is used: implement-markdown allows only unreachable defensive lines.
- EX-09: `raw-ingestion-client.test.ts` is an unconditional orchestrator `git rm` in M10.2.
- EX-10: M10.2 moves the `files.ts` cases into `files.test.ts`, and the `hashBlob` case, likewise
  found only in `upload.test.ts`, into `hash.test.ts`. M10.6 updates them.
- EX-11: radon must print nothing (the plan-wide "Gate" rule). M2.2 uses `git status
  --porcelain`. M10.10 and M7.14's timing run pass `--junitxml`.
- EX-13: M3.3 names the exact mypy override and the conditional ty setting, and the "Clean sweep"
  rule makes them the one configuration change the plan specifies. They are not labelled
  owner-approved, because no owner approval is on record; the plan specifies them as part of the
  task instead.
- EX-15: M10.8 sets `chunk_bytes=8388608` in the harness's explicit `RawSettings`, and its first
  scenario asserts the value. A probe confirmed that the environment variable is ignored when
  `raw=` is passed.
- EX-16, second half: M4.9 depends on M4.7, and its runtime bullet names `ports.datasets`.
- EX-17: (a) M3.1 lists the eight names once, and M6.1 no longer says the list grows. (b) M4.8,
  M5.1, M5.2, M5.3, M6.9 and M7.7 rename the tag-set test at each count change, as the plan-wide
  rule already required. (c) M10.8's harness bullet is rewritten.

Rejected or adopted differently:

- EX-16, first half (M1.1 as a dependency of M1.3): wrong. `core/raw/amendments.py` neither
  imports nor raises `Forbidden`. It raises `AmendmentFieldForbidden` from `.errors`, and
  `rg "\bForbidden\b"` matches only its docstring ("Forbidden fields"). M1.3 moves nothing that
  module uses, so the edge is not added.
- EX-03's suggestion to split M5.7: not adopted. The wrappers and the cases that cover them must
  leave together. Re-pointing the suites first would leave the wrappers uncovered; deleting first
  would leave kept primitives uncovered. M5.7's intent records this and the task's size.
- EX-17(b)'s count-free test name: not adopted. §19.7 names the end state
  `test_the_openapi_document_carries_seventeen_resource_grained_tags`, so the test is renamed at
  each count change, the finding's first option.

Every blocking defect (COV-01, EX-01, EX-02, EX-03 and EX-04) is resolved.

VERIFIED

## Execution notes

Deviations from the literal plan text, baseline edits and leftover database objects are recorded
here as tasks complete.

### M0.2

- Coverage floor (deletion rule). Unit coverage before: 7,239 of 7,521 statements covered
  (96.25%, 1,837 tests at `8b6f270`). After: 5,804 of 6,086 (95.366%, 1,532 tests). All 1,435
  removed statements were covered — 1,390 in the deleted files, 36 in `core/raw/paths.py`, 9 in
  `core/foundation/names.py` — and the 282 missing statements are unchanged. `fail_under` was
  reset from 96.01 to 95.36, and its `pyproject.toml` comment now states when the floor may drop.
  Both modified source files are at 100%.
- Test counts against the baseline. Unit 1,837 → 1,532 (−305): 288 in the fifteen deleted unit
  modules, 15 revision-path parsing tests in `test_catalog_paths.py`, the parsing round-trip
  property in `test_catalog_properties.py` and the Integrity private-surface case in
  `test_domain_import_contracts.py`. Contract 50 → 31 (−19: `test_integrity_store.py` 4,
  `test_maintenance_ownership.py` 2, `test_writer_exclusion.py` 13). Integration 16 → 15
  (−1: `test_protocol_cutover.py`). Import-linter: 19 → 16 contracts, all kept.
- Duplication: the guard passes without a baseline edit (132 clones / 43 groups against the
  baseline's 144 / 48). The baseline was not regenerated, so one group signature in
  `scripts/duplication_baseline.json` still names the deleted `core/rawstore/maintenance.py`.
- Deviations: the `parse_revision_dir` round-trip sentence was in
  `docs/getting-started/conventions.md` (removed there, "constructors/parsers" became
  "constructors"); `testing.md` only listed the `parse(construct(x)) == x` target, also removed.
  Of the shared tests the plan names, `test_commit_intents.py` and `test_api_login.py` mention only
  retained behaviour (migration 0011's legacy-session refusal, API-key header parsing) and are
  unchanged; `test_catalog_store.py` and `test_catalog_documents.py` each had one docstring
  reworded. Beyond the listed files: `IMPLEMENTATION_PLAN.md` drops its controlled-cutover runner
  requirement; `AGENTS.md` and `repository-layout.md` no longer claim an application-independence
  contract; `AGENTS.md`, `architecture.html` and the core map no longer list maintenance adapters
  in Metastore or Rawstore; the roadmap's domain-owned Core receipt and P2 row note the
  retirement; `docker-compose.yml` loses its whole header comment. The module docstring of
  `test_catalog_properties.py` now lists only the facts that module tests (it also claimed an
  untested NFC refusal and a stale parent-linking upload plan). ADR-0002 still lists Integrity
  among the owners it decided; it was left as an accepted decision record.
- Leftover database objects (dropped by the later legacy-retirement migration): the
  `reconciliation_findings` table, the `DEGRADED` value of `dataset_revisions.state`, audit rows
  of kind `integrity.cutover`, and the manually created roles `huron_app_legacy`,
  `huron_app_verified` and `huron_cutover`. Kept on purpose: `committed-v1.json` decoding and
  `generation-v1.json` (now validated by no code; only the schema package docstring names it).
- Untracked leftovers: `src/huron/applications/lakectl/` and `src/huron/core/integrity/` still
  hold ignored `__pycache__` bytecode from before the deletion; removing it was refused in this
  session. Nothing tracked remains there and no gate command reads it.

### M0.3

- Coverage floor (ratchet). Unit coverage before: 5,804 of 6,086 statements (95.37%, 1,532
  tests at `248f7bf`, re-measured). After: 5,623 of 5,880 (95.629%, 1,510 tests). Of the 206
  removed statements, 183 were covered and 23 were the PostgreSQL release reads and writes in
  `core/metastore/hierarchy.py`, which only the contract suite exercised; two previously missed
  refusal lines of `core/raw/manifest.py` are now covered. The total rose, so `fail_under` was
  raised from 95.36 to 95.62. Every modified source file is at 100% in the unit run except
  `core/metastore/hierarchy.py`, which is at 99.60% under `-m "unit or contract"`: its one
  missing line (761) is the pre-existing `RuntimeError` for an idempotency claim that vanishes
  mid-transaction, which its docstring calls unreachable because nothing deletes an
  `idempotency_records` row.
- Test counts against `248f7bf` (1,532 / 31 / 15). Unit 1,510 (−22). Removed 33: 14 release API
  tests in `test_api_catalog_hierarchy.py` (its combined dataset/release no-ETag test became a
  dataset-only test), 8 in `test_repository_hierarchy.py`, 3 tag-cursor tests in
  `test_api_pagination.py`, 3 in `test_hierarchy_store_memory.py` (two release reads, plus the
  revision-read test now shared by both backends as `scenario_5_revisions`, unknown-dataset check
  included), 2 tag-path tests in `test_catalog_paths.py`, 2 row mappers in `test_stores_rows.py`
  and the tag-file test in `test_rawstore_generation.py`. Added 11: 3 `validate_manifest` refusal
  cases in `test_catalog_documents.py` and 8 request-fingerprint cases in the new
  `test_foundation_retry.py`. Contract 32 (+1: the release-retirement migration test).
  Integration 14 (−1: `test_catalog_releases.py`). Import-linter keeps 16 contracts.
- Duplication: the guard passes without a baseline edit (123 clones / 41 groups against the
  baseline's 144 / 48).
- Migration contract: `test_catalog_store.py` seeds a tagged revision at `0012`, upgrades to head
  and checks that every relation, constraint, trigger and function named for `releases` is gone,
  no capability or grant matching `release.%` remains, the capability table equals
  `CAPABILITIES`, the developer role's description matches `ROLES`, the revision survives, and the
  downgrade raises without moving the version. It matches the retired capability by that `LIKE`
  pattern, so the verification `rg` stays empty. `test_commit_intents.py` pins the new head. The
  `0008` round-trip probe `releases_revision_dataset_fk` stays: that test runs at `0010`, where the
  release DDL of `0008` still exists.
- Deviations beyond the listed code: `foundation/names.py` loses the tag pattern and
  `validate_tag`, `foundation/retry.py` the `release` replay kind and `routes/v1/pagination.py`
  `tag_cursor_key` (each had only release callers). `request_sha256` now takes only string
  fields: the release route was its only caller to pass `None` (the optional title), so the
  absent-field marker went with it. Digests of string fields are byte-for-byte unchanged, so
  stored fingerprints stay valid; the five unit-test `_claim` helpers take string parts, and the
  new `test_foundation_retry.py` pins the encoding. `core/metastore/hierarchy.py` also loses
  `_REVISION_MANIFEST_CONSTRAINT`, unused since migration `0010` dropped that constraint.
  Docstrings in `catalog/retry.py`, `raw/manifest.py`, `api/app.py` (the pool "releases" became
  "closes") and `api/runtime.py` no longer mention releases. The developer role description
  changes from "create and tag datasets" to "create and update datasets" in `roles.py` and in
  the seeded row (migration `0013`). `tests/raw_web_support.py` paged revisions through the
  deleted `revision_ref`; its `MemoryRawWebStore.revision_ids` now reads the in-memory
  hierarchy's revisions directly, as other tests do, mirroring the PostgreSQL query, and
  `raw_web_stores()` builds that `InMemoryHierarchyStore` itself, so the fake's annotation
  matches what its caller passes.
- Documentation beyond the listed pages: `catalog-search.html`, `core-map.html`, `frontend.html`,
  `layer-gold.html` and `python-client.html` drop release tags; `rbac.html` also drops tagging
  from the developer's duties and the action table and now counts sixteen capabilities;
  `architecture.html` drops releases from Raw's and PostgreSQL's responsibilities; the roadmap
  also updates its package map, the P3 rebuild gate and UI milestone 7. `AGENTS.md`,
  `docs/backend-design.md`, `docs/index.md` and `docs/getting-started/` (`conventions.md`,
  `repository-layout.md`, `testing.md`) drop releases from Raw's scope; `docs/history.md` records
  the retirement; `IMPLEMENTATION_PLAN.md`'s fixed contracts drop release cursors and tag
  ordering. ADR-0002 still lists release tags among Raw's responsibilities; it was left as an
  accepted decision record. The web's fixture-backed release routes are untouched, as planned.
- Leftovers: the `dataset_revisions_id_dataset_id_unique` constraint (redundant with the primary
  key; only the dropped release foreign key cited it), idempotency receipts of kind `release` in
  `idempotency_records`, and tag documents already written under each dataset's `releases/`
  directory on the data root. No foreign key cites the constraint any more, and nothing reads the
  tag documents. The claim path still reads a live `release` receipt, as it reads every receipt,
  and refuses reuse of its key for another request until it expires 24 hours after its claim; no
  current request can replay it.

### M1.1

- Coverage floor (deletion rule). Unit coverage before: 5,623 of 5,880 statements covered
  (95.63%, 257 missed, 1,510 tests at `338728d`, re-measured; equal to M0.3's result). After:
  5,590 of 5,847 (95.604%, 257 missed, 1,508 tests). All 33 removed statements were covered: 31
  in the deleted `core/raw/amendments.py` and 2 in `core/raw/errors.py` (`AmendmentFieldForbidden`).
  No other file's statement count or missed lines changed. `fail_under` was reset from 95.62 to
  95.60 (floor(10000 × 5,590 / 5,847) / 100). The one modified source file, `core/raw/errors.py`
  (21 statements), is at 100%.
- Test counts against `338728d` (1,510 / 32 / 14). Unit 1,508 (−2: the two tests of the deleted
  `test_raw_amendments.py`). Contract 32 and integration 14, unchanged. `test_error_contract.py`
  passes unchanged.
- Duplication: the deletion changed no clone group. The scan shows 123 clones in 41 groups both at
  `338728d` and after (fragments 826 → 823). The baseline was ratcheted down with
  `--update-baseline` from 144 clones / 48 groups to 123 / 41, with no new or grown signature. Six
  signatures left it (14 clones, 6 groups): the two naming the deleted
  `core/rawstore/maintenance.py` (with `store.py`, and with `materialize.py` and `store.py`),
  `catalog/_impl/collections.py`, `foundation/names.py`, `catalog/ports.py` with `raw/ports.py`,
  and `routes/v1/schema/{datasets,organizations,projects}.py`. Three groups shrank (5 clones):
  `api/dependencies.py` 7 → 6, `routes/v1/endpoints/{datasets,organizations,projects}.py` 4 → 3
  and `metastore/{hierarchy,ingest,rbac}.py` 15 → 12. One of the two identical
  `metastore/{memory_apikeys,memory_sessions}.py` groups (size 2) left (2 clones, 1 group); the
  signature stays with the other. Together that is −21 clones and −7 groups. The cap stays 144, a
  headroom of 21 clones.
- Deviations in the listed pages: the roadmap's P5 tag moves from partial to todo (the fold was its
  only built part), UI milestone 7 promises each revision's metadata (its immutable
  `metadata.json`) in place of the effective metadata and its amendment history, UI milestone 21
  becomes "Validation & retention", and the P3 rebuild gate no longer lists amendments. The
  roadmap, `layer-raw.html` and the core map word the retirement in the pages' current vocabulary
  ("a correction is a new revision"). `layer-raw.html` also drops `amendments/0001.json` from the
  envelope layout and amendments from its purge, rebuild and governance-record paragraphs.
- Documentation beyond the listed pages: `architecture.html` (the NFS row, the query split and
  invariant D), `catalog-search.html` (the query table and both rebuild bullets), `index.html`
  (the Amendment glossary row and `amendments/` in Envelope), `rbac.html` (the project admin's
  acts, the Raw action table, the capability note and the recommended policy) and `workflows.html`
  (the governance journeys) no longer describe amendments. Left for their own tasks: the two §3
  rows of `design/api.html` (M5.2) and the amendment sentence of its "P3 integrity read admission
  (planned)" section (removed with that section), the `revision_amendments` DDL in
  `catalog-search.html` (the table still exists), the UML atlases (dated snapshots) and the
  fixture revision page under `web/src/routes/[org]/[project]/[dataset]/[release]/` (M1.2).
- Leftover database objects (dropped by the later legacy-retirement migration): the
  `revision_amendments` table, which nothing writes.

### M1.2

- Delivery-order deviation (1): the fixture-backed `[release]` and `[revision]` pages leave here,
  with the release table of the fixture `[dataset]` page and the fixture helpers, types and data
  that only they used, ahead of the rest of §21.2 row 15, which stays with the web milestones.
- Beyond the listed text: the `[dataset]` page also loses its `Callout` import, which nothing on
  the page used, and keys its tags `{#each}` by the tag, the svelte-autofixer's one remaining
  finding on that file (its two other findings, an unkeyed `{#each}` and an `href` without
  `resolve()`, left with the release table). The private `layers()` helper of `fixtures.ts` loses
  its `'~'` (building) code, whose only input was the unsealed `run-0002` release.
  `web/src/lib/reserved-slugs.ts` derived the reserved root slugs from "design/frontend.html §1"
  and quoted deep links of the form `/{org}/{project}/{dataset}/{release}`; that page has not
  said so since `8286b2e` and the `{release}` route is gone, so the comment now names
  `/{org}/{project}/{dataset}` without the citation.
  `web/src/lib/design/components/DataTable.svelte` lost all three of its users, the release table
  and the two deleted pages; implementers cannot delete tracked files, so it was reported, and
  the orchestrator removed it with `git rm`.
- Kept on purpose: `web/src/lib/design/components/Callout.svelte` has no user now. The deleted
  `[release]` page was the only one that rendered it (the `[dataset]` page only imported it). It
  stays because §20.1 names it among the existing components the web tasks reuse, and the
  wizard's Raw-disabled state renders it again (§20.4.1, M10.5).
- Left in place, because none is used only by the release pages: the `/queue` fixture page still
  shows each fixture ingest job's release slug (`IngestJob.release`); `SearchHit.kind` still
  admits `'release'`, though no fixture hit uses it; and `LayerState` still admits `building`,
  which `LayerBadges` renders, though no fixture layer is building any more. Like the fixture
  tree, `/queue` redirects every signed-in request to `/browse`.
- Counts: no Python file changed. Unit 1,508, contract 32 and integration 14, unchanged; unit
  coverage 5,590 of 5,847 statements (95.60%), as after M1.1, so `fail_under` stays 95.60. The
  duplication guard passes at 123 clones in 41 groups without a baseline edit. Vitest 269 tests in
  25 files, unchanged (no case covered the removed helpers). Playwright 48 scenarios; "obsolete
  scientific fixture routes redirect into live browse" passes, now by the hook alone.
- No visual QA: the changed page is unreachable while signed in, because the hook sends every
  signed-in request outside the workspace routes to `/browse` (and an anonymous one to `/login`).
- Machine load: the first `npm test` and `npm run test:e2e` coincided with heavy memory pressure
  (load average up to 37 on 8 cores, about 10.4 of 11.2 GB swap in use, Docker's VM holding 4 GiB).
  Vitest timed out one password-hashing case of `huron-accounts.test.ts` at its 5 s limit (the run
  took 955 s), and Playwright timed out four sign-in and user-creation scenarios at 30 s
  (`ingestion.test.ts:186`, `organizations.test.ts:131`, `polaris.test.ts:88`, `smoke.test.ts:42`).
  None exercises the fixture page or the removed helpers. Re-run, Vitest passed 269/269 in 4.5 s
  and Playwright 48/48 in 55 s. A later `npm run test:e2e`, with about 10 of 11 GB of swap in use,
  timed out three scenarios at their 5 s expectations, each its worker's first mutation while the
  freshly started servers had not yet answered (the pages still showed "Uploading…" or "Waiting
  for Polaris…"): `ingestion.test.ts:31`, `organizations.test.ts:76` and `polaris.test.ts:16`.
  None touches the fixture tree; re-run, Playwright passed 48/48 in 58 s.
