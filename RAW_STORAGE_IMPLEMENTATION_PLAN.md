# Huron Raw storage redesign — implementation plan

Status: **Milestone 0 in progress (M0.1, M0.2 done).** Branch `raw-storage`, baseline commit `8b6f270`.
Design: `RAW_STORAGE_DESIGN.md` (being finalized; Milestones 1+ are added from it once it is
reviewed). Milestone 0 holds only work the owner decided independently of the remaining design
sections, and was approved to start early on 2026-10-15.

## Goal and non-goals

Goal of Milestone 0: delete the code, tests, tooling and documentation that the owner's decisions
make obsolete before the Raw redesign begins — the legacy integrity/cutover machinery and its
operator CLI (decision OD-3), the API-key Books uploader (OD-8) and Raw release tags (owner
requirement 3: only full versions, no tags or releases).

Non-goals of Milestone 0: any change to Raw ingestion, storage layout, the upload protocol, the
Polaris bridge, lifecycle or the schema registry; any web change; dropping database objects other
than those named in task M0.3. Database objects used only by the retired integrity code stay until
the legacy-retirement migration of a later milestone, which also drops them.

## Plan-wide rules

These apply to every task in this plan.

- **Gate.** Every implementation, fix and verification pass runs the complete gate below from the
  repository root. Every command must exit 0. Configured thresholds in `pyproject.toml` govern
  (`fail_under = 96.01`; never lower it).

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
  `make docs`. Tasks that change `web/` also run, from `web/`: `npm run check`, `npm test`,
  `npm run lint`, `npm run build`, and `npm run test:e2e` for user-visible changes.
- **Containers.** Contract and integration suites use Docker Desktop through testcontainers.
  Never start or stop the owner's local stack (`scripts/polaris-dev.sh`, the `huron-raw-local`
  container) and never use `make up`/`make stack`.
- **Long commands.** No single tool call may run longer than about two minutes without output:
  run the contract and integration suites (and any other long command) in the background and poll
  their output with short commands until they finish.
- **Coverage.** Every file a task modifies (not deletes) reaches 100% line coverage, unless the
  verifier names a specific line as unreachable defensive code. PostgreSQL adapter modules are
  measured with `uv run pytest -m "unit or contract" --cov=src/huron --cov-report=term-missing`.
- **Coverage floor on deletions (owner decision, 2026-10-15).** When a task deletes code,
  `fail_under` in `pyproject.toml` may be reset to the newly measured unit total, rounded down to
  two decimals, provided the drop comes entirely from deleted covered statements (compare covered
  and total statement counts before and after) and every new or modified file is at 100%. Record
  the before/after numbers under "Execution notes". The floor rises again as tests are added.
- **Whole-file deletions.** Implementation agents cannot delete tracked files; the orchestrator
  removes every whole file or directory a task lists (with `git rm`) before the implementation pass.
  An implementer that finds another whole file to delete reports it and stops; it does not delete it.
- **Duplication baseline (owner decision O-2).** When the duplication guard fails only because a
  deleted or renamed file changed the signature of a known clone group, the task may regenerate
  the baseline with `uv run --locked python scripts/check_duplication.py src --update-baseline`,
  and only if the regenerated baseline has at most 144 total clones and no clone group larger than
  before. The verifier reviews every such edit; the task records it under "Execution notes".
- **Clean sweep.** No backwards compatibility, shims, TODOs, commented-out code, suppressions
  (`# noqa`, `# type: ignore`, `# pragma: no cover`, skip/xfail) or configuration exclusions.
  Comments, docstrings, test names and messages never mention this plan, its tasks or milestones.
- **Skills.** `oop-design` for `src/huron/core`; `fastapi` for `src/huron/applications/api`;
  `postgresql-table-design` for migrations and PostgreSQL adapters; `writing-for-agents` when
  editing `AGENTS.md` or `CLAUDE.md`.
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
  the "Coverage floor on deletions" rule and record the numbers.
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
- Status: pending

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
