# Huron Raw data lake — implementation plan

Status: pending

Branch `raw-storage`; baseline commit `fa51f46`. Milestones M1–M19 start from the commit that adds
`RAW_LAKE_SPEC.md`, `RAW_LAKE_DESIGN.md` and this plan (task M0.1). Spec of record: `RAW_LAKE_SPEC.md`.
Its "Owner decisions (2026-10-23)" items 1–12 bind every task and amend the spec body where they differ:

1. Reach: Raw only. The Raw engine, `/api/raw-web`, the BFF Raw delegation, the web upload wizard and the
   Raw explorer leave; web login, sessions, API keys and the Polaris org/project/dataset API keep running,
   and the lake's tables live apart from the legacy ones.
2. Persistence: hand-written DDL Alembic revisions, asyncpg SQL adapters and the `migrations/schema.sql`
   map.
3. Commit: asynchronous. `POST /collections/{id}/commit` answers 202 with a commit id; a bounded worker
   re-hashes from the mount and commits rows and audit entries in one transaction; the CLI polls.
4. NFS mock: a plain directory with a marker file behind the `Volume` and `DirectoryPermissions` ports
   with a recording fake; a real NFS server and ACL checks run as a Linux-only tier.
5. Mocks: the company OIDC provider, the LDAP-groups endpoint and the ONTAP NFS volume are mocked for local
   development and tests.
6. Catalog store: option A. Huron's PostgreSQL is the only Raw catalog; no Polaris client, credential or
   compose service for Raw (OD-5 stands); the projection seam is named, not built.
7. Role check: the token's `groups` are re-mapped through the current `group_role_map` on every request;
   the `roles` claim stays for `whoami` and other services.
8. Administration: audited API routes and CLI verbs for catalogs, catalog configs, metadata schema
   versions, role mappings and signing-key rotation; a configured LDAP group is seeded as global Platform
   Owner at startup.
9. Plan files: this design and plan live on `raw-storage`; `RAW_STORAGE_DESIGN.md` and
   `RAW_STORAGE_IMPLEMENTATION_PLAN.md` carry a superseded banner and keep their M0–M1 notes as history.
10. Legacy credentials: the web keeps its own sessions and account store; the Python password login,
    cookie sessions and server code flow leave; API keys, service accounts and dev headers stay for the
    legacy `/api/v1` routes; lake routes accept only the Huron JWT.
11. No backwards compatibility of any kind: no shims, re-exports, aliases or deprecated names, no old key,
    variable or route beside its replacement, no second request or response form, no data-preserving
    migration or refusal flag, no interim state for old clients or data (the design's "Owner decision 11:
    no backwards compatibility", B-n rows).
12. Every open question is settled on its recommended option or its decision-11 revision; the company IdP
    is a standard OIDC provider; local development and tests never reach the institutional IdP and use
    only the Keycloak `company` realm and the fake issuer; answers that rest on facts outside the
    repository are assumptions confirmed before production ("External assumptions to confirm before
    production" below).

Design of record: `RAW_LAKE_DESIGN.md`: its Roadmap Drift and Current State (conventions 1–13, structural
observations), the twenty-six design sections "DT-1 design" … "DT-26 design" with their decisions,
interfaces, tests, deletions and handoffs, "Owner decision 11: no backwards compatibility", and the "Open
questions register" (OQ-1.1 … OQ-26.1, every entry settled by owner decision 12).
`RAW_STORAGE_DESIGN.md` and `RAW_STORAGE_IMPLEMENTATION_PLAN.md` are superseded (Owner decision 9): their
Milestones 0–1 shipped (`248f7bf` … `fa51f46`) and stay as history; nothing else in them is work. This plan
borrows only their format.

## Goal and non-goals

Goal: implement `RAW_LAKE_DESIGN.md` on `raw-storage`, one task at a time under the rules below. The
legacy Raw engine, its web wizard and explorer, the Raw bridge and the Python password login, cookie
sessions and server code flow leave first (migration `0014_retire_legacy_raw`), and the binding rules,
glossary and ADRs are rewritten before any lake code. Huron then gains its Raw lake: an auth broker in
`huron.core.security.broker` (company-token exchange, LDAP-group directory, Huron-signed ES256 JWTs with
JWKS and discovery, per-request re-mapping of `groups` through `lake.group_role_map`); the lake domain in
`huron.core.lake` (catalogs with immutable config versions, `extends`-composed metadata schemas,
namespaces, collections from draft to activation and deletion, file rows, asynchronous commits re-hashed
by a bounded worker, metadata publish and `mv`, an append-only audit log, audited administration with a
seeded global Platform Owner, and a CronJob reconciler); its PostgreSQL adapters and fakes in
`huron.core.metastore.lake` over schema `lake` (revisions `0015`–`0018`); the Volume and
DirectoryPermissions adapters in `huron.core.rawstore`; the lake router under `/api/v1` (DT-18's 37
rows); the Typer CLI `huron` in `huron.applications.cli` that logs in, browses, walks a scientist through
a collection, stages files and pushes bytes over the NFS mount; and the local mocks (Keycloak `company`
realm, fake issuer, `fake-ldap-groups`, the plain-directory volume stand-in), the `stack` and `nfs` test
tiers and the plain-directory large-file gate. The design record, roadmap and operator docs describe the
built behaviour when the plan completes, and `raw-storage` merges into `main` by a merge commit.

Non-goals:

- Raw versioning of any kind: revisions, releases, tags, amendments, per-file versions or etags
  (`RAW_LAKE_SPEC.md` principles; OQ-1.2; OQ-13.3). ONTAP snapshots are the recovery path; snapshot
  policy and SnapLock stay the owner's open questions (`spec` "Build order and open questions").
- The Polaris projection (option C, DT-24, deferred): no `RawCatalogProjection` adapter, no
  `polaris_projection` table, no outbox or audit cursor for it, and no Polaris client, credential,
  compose service or marker for Raw (Owner decision 6; OD-5 stands). Only the closing check of "DT-24
  explicitly not built in this plan" runs (M19).
- A lake WebUI or BFF delegation (spec "Out of scope"; DT-3, DT-26 `frontend.html` §3), the Icechunk +
  Zarr analytical store, processing pipelines and service-account credentials for Raw, and a Python SDK
  (a later SDK registers verb groups on the `huron` CLI, L-31).
- Changes to the legacy org/project/dataset `/api/v1` surface, its RBAC, API keys, service accounts or
  dev headers other than DT-2's removals and the rules this plan applies to both routers (the strict
  If-Match parse, the Idempotency-Key bound, the company bearer's subject and group source, the freed
  ingestion and queue slugs) (owner decision 11, B-12).
- Migrating, converting or exporting legacy Raw data: `0014_retire_legacy_raw` drops it unconditionally
  (L-18 (a), Owner decision 11, B-5).
- Everything a DT section defers or rules out: emergency signing-key revocation (OQ-5.1), admin-entry
  read routes (OQ-7.2), collection-, namespace- or file-level grants (L-25 (a)), `huron check --repair`
  (OQ-16.2), typed `label` values (OQ-18.3), a Windows CLI (OQ-19.2), server dependency extras (L-31),
  editing the spec body in place (OQ-25.1), and the staging tier against the real ONTAP volume and company
  IdP, which is a manual release runbook (DT-23 tier table, DT-26), not a plan task.
- Merging `raw-storage` into `main` before every task is verified, every required CI check is green and
  the last two `nightly.yml` runs on the pull request, started by its `nightly` label, are green (DT-23
  "Gates"; "Plan-time resolutions of design text" below).

### Settled open questions

Every open question in the design's register (OQ-1.1 … OQ-26.1) is settled by owner decision 12 on its
recommended option, or on its decision-11 revision where owner decision 11 resolved or revised it
(`RAW_LAKE_DESIGN.md` "## Open questions register"); a task that rests on one names it in a "- Decisions:"
line, and the milestone table below collects them.

### External assumptions to confirm before production

Owner decision 12 adopts these answers about systems outside the repository as assumptions. The plan builds
and tests them against the mocks only (the Keycloak `company` realm, the fake issuer, `fake-ldap-groups`
and the plain-directory volume); each is confirmed with its owner before the production rollout, and a
contrary answer is a new design change with new tasks, never an edit of a done one.

- ONTAP ACL behaviour (OQ-11.1): the export honours NFSv4.1 ACLs with numeric principals under UNIX
  security style and `root_squash`, and the OpenShift SCC pins the API pods' `runAsUser` — M11.4, M11.11,
  M11.12, M15.2, M15.3, M16.4, M17.5, M19.3.
- Inherited ACEs under permissive create modes on ONTAP (OQ-21.3): files created `0o666` and directories
  `0o777` receive exactly the inherited NFSv4 ACEs — M14.3, M15.3, M15.4, M19.3.
- The real group-directory contract (OQ-6.1): `GET …/users/{username}/groups` answers `{"groups": [...]}`,
  needs no authentication and answers 404 for an unknown user — M5.1, M5.6, M9.1.
- Group counts against header limits (OQ-6.2): every directory group fits in the Huron JWT behind the
  OpenShift router (a warning is logged above 100) — M5.6.
- The organization claim (OQ-20.3): the company ID token may carry a non-standard `organization` string
  that the walkthrough uses as a prefill — M5.2, M12.1, M12.3.
- The production IdP's client registration (OQ-22.1, OQ-19.1): a standard OIDC provider (discovery, JWKS,
  the device authorization grant, the code flow with PKCE on a loopback redirect) with a public `huron-cli`
  client that allows the device grant and `http://127.0.0.1` loopback redirects and accepts or ignores PKCE
  on the device request — M5.2, M5.3, M5.4, M10.1, M10.2, M10.4, M19.2.

## Plan-wide rules

These apply to every task in this plan.

- **Gate.** Every implementation, fix and verification pass runs the complete gate below from the
  repository root (it is `make lint`, `Makefile:58-70`, plus the three pytest tiers CI runs). Every
  command must exit 0, and `radon cc` and `radon mi` must also print nothing: radon exits 0 even when it
  lists findings. Configured thresholds in `pyproject.toml` govern.

  ```text
  uv run ruff check src
  uv run ruff format --check src
  uv run pydoclint src
  uv run mypy
  uv run ty check
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

  Additions by what a task touches:
  - `web/` (M1 only): from `web/`, `npx @sveltejs/mcp svelte-autofixer <file> --svelte-version 5` on each
    changed Svelte file until no applicable finding remains, `npx prettier --write` on the changed files,
    then all five of `npm run check`, `npm test`, `npm run lint`, `npm run build` and `npm run test:e2e`.
    `web/playwright.config.ts` needs the Icechunk SDK runtime (`HURON_ICECHUNK_PYTHON`); when it is
    absent the task reports `test:e2e` "not run" with that reason and never starts `scripts/polaris-dev.sh`
    to obtain it.
  - `docs/`, `design/`, `README.md` or `zensical.toml`: `make docs` (DT-26 "Gate"); from the M19 task that
    adds `scripts/check_design_links.py`, `make docs` also checks `design/` links. Instruction-only
    Markdown (`AGENTS.md`, `CONTEXT.md`, `docs/adr/`, the plan and spec files): `git diff --check` and the
    closing checks the task names (AGENTS.md "Commands and gates").
  - `design/api.html` §7: `uv run pytest tests/unit/test_error_contract.py` passes (it is part of the unit
    run; the task names it because code and rows change together, convention 1).
  - New tiers, only from the task that creates them (M15): `uv run pytest -m "acceptance and not nfs"`
    (`make test-acceptance` after M15) runs when the pytest base temp has at least 12 GiB free and is
    otherwise reported "not run" with the measured free space; `make test-stack` needs a running
    `make stack` and `make test-nfs` needs Linux with passwordless sudo, so on the owner's macOS a task
    that adds or changes `stack` or `nfs` tests runs `uv run pytest -m "stack or nfs" --collect-only -q`
    and the tier guard (`tests/unit/test_test_tiers.py`) locally, and the first green CI run of the job is
    recorded under "Execution notes" as its receipt (DT-23 "Not verifiable on this machine"). The merge
    task requires those receipts.
  - `scripts/` changes: the script's own unit tests (`tests/unit/test_check_*.py` pattern) and, for a shell
    script, `bash -n <script>`.
- **Long commands.** A tool call that runs more than about two minutes without output is killed. Run the
  contract and integration suites (and any other long command) in the background and poll their output
  with short commands until they finish.
- **Containers and the owner's stack.** Contract and integration suites use Docker Desktop through
  testcontainers (`postgres:16`); with podman, Ryuk must be disabled. Never start, stop or reset the
  owner's local stack: `scripts/polaris-dev.sh`, the `huron-raw-local` container, `make up`, `make stack`,
  `make down`, `make keycloak-reset`, `docker compose up/down`. A task may edit `docker-compose.yml`,
  `Makefile`, `dev.env` and `scripts/check-stack.sh`; it validates them with
  `docker compose config --quiet` (and `make -n <target>`), never by starting services, unless the task
  text says otherwise.
- **Coverage.** Every file a task creates or modifies (not deletes) reaches 100 % line coverage, unless
  the verifier names a specific line as unreachable defensive code. PostgreSQL adapter modules (legacy and
  `huron.core.metastore.lake`) are measured with
  `uv run pytest -m "unit or contract" --cov=src/huron --cov-report=term-missing --cov-fail-under=0`. A
  deleting task removes every symbol whose only covering tests it deletes, or covers that symbol directly
  when it stays.
- **Coverage floor.** `fail_under` (`pyproject.toml`, `[tool.coverage.report]`, 95.69 at `fa51f46`) is a
  ratchet on the unit run.
  - D2-1 … D2-5 (M1) apply DT-2's "Coverage floor procedure" exactly: before/after JSON reports, the
    three pass conditions, then `fail_under = floor(10000 × covered / statements) / 100` of the after
    totals.
  - From M2 to M18 the floor is not raised (DT-23 "Coverage ratchet"). It moves down only by
    `.claude/commands/implement-markdown.md`'s re-baseline: the verifier confirms from covered and total
    statement counts before and after the task that the whole drop comes from deleted covered statements,
    new PostgreSQL adapter statements that the "unit or contract" run covers in full, or both, and that
    every new or modified file is at 100 %.
  - M19's closing task re-measures once with DT-2's rule (never past the measured total).
  - Every change of `fail_under` records the before and after covered and total counts and the unit
    test-count change under "Execution notes".
- **Migrations and the schema map.** Hand-written DDL in Alembic revisions through
  `migrations/_ddl.py` `execute_sql`; no autogenerate, no import of `huron` from a migration (seeds are
  literals). At most one revision per task, in the order `0014_retire_legacy_raw` (M1),
  `0015_lake_catalog` (M8), `0016_lake_collections` (M11), `0017_lake_commits` (M13),
  `0018_lake_reconciler` (M17) (DT-2 "decisions", DT-17 "revision list"). Each revision lands in the
  same milestone as the code that writes its tables and their contract tests, and updates
  `migrations/schema.sql` (its tables and the `-- Reflects:` stamp, which `scripts/check_schema_map.py`
  checks in `make lint`) in the same commit. Lake SQL is always `lake.`-qualified and lake DDL follows
  DT-17 "DDL" sections; downgrades follow DT-17 "decisions" (`refuse_if_rows`, OQ-17.1). Constraint
  proofs run on `postgres:16` through the migrate helper of the time: the per-module `_migrate` copies
  until M8, then `tests/postgres.py` (`migrate`, `downgrade`, `migrated_postgres`) only.
- **Import contracts.** `uv run lint-imports` keeps every contract at every commit. Each contract edit
  lands in the commit that makes the package change it admits, so no contract names a missing module and
  no module escapes the exhaustive sibling list (DT-1 "import-linter contract set", final paragraph):
  16 kept at `fa51f46`; 14 after D2-2; the rename (M2) changes contracts 2, 4–6, 9, 10, 11, 13, 14 without
  changing the count (contract 9 forbids `huron.core.catalog`, which becomes `huron.core.hierarchy`); contract 7, the lake entries of the others and DT-17's contract 19 arrive with
  the first `huron.core.lake` and `huron.core.metastore.lake` modules (M4.1: 17, because contract 19 is
  written as two `forbidden` tables, `independence` being unable to express it over legacy modules that
  import one another); contract 16 with the first `huron.core.lake._impl` module (M7.3: 18); contract 9's
  `rawstore → lake` edge with the first such `rawstore` module (M11.2, count unchanged); contracts 17, 18
  and the Ruff `TC` entry with the first CLI module (M10.1: 20, the end state). Each task's verification
  states the expected count.
- **Composition root.** A task that adds or removes an `ApiStores` member, an `ApiRuntime` field, a
  lifespan task or an `ApiSettings` field edits, in the same pass, `src/huron/applications/api/runtime.py`,
  `app.py` (`_postgres_stores`, `_build_runtime`, the lifespan, `/readyz`), `settings.py`,
  `tests/unit/support.py` (`memory_stores()` and, from M9, the default lake test settings) and every test
  that builds `ApiRuntime`, `ApiStores` or `ApiSettings` directly. From M9, every app the tests compose
  starts the lake lifespan (bootstrap, signing keys, and from M11 the volume), so the default test
  settings carry DT-22's identity values, the seed and a `tmp_path` volume with its marker.
- **Problem codes and route tables.** A `design/api.html` §7 row lands with its first raiser and leaves with
  its last (convention 1; DT-18 "error-code table rows"). DT-18's route table is the only lake route
  table; each row lands with its owning task, in DT-18's shape (paths, Min role, headers, status codes,
  problem codes, audit action), and `design/api.html` §1/§3 copy it as rows land. A task that adds or
  removes routes updates `tests/unit/test_api_router_composition.py` (tag set, credential-dependency and
  segment invariants), `tests/unit/test_execution_model.py`'s operation table and, from M9,
  `tests/unit/test_lake_routes.py` (the derived anonymous-401 sweep and the role-ladder table cover each
  new row). Legacy `/api/v1` counts: 52 at `fa51f46`, 40 after D2-2, 38 after D2-4 (OQ-2.2); the end
  state is DT-18's 21 tags and 34 lake routes behind `current_actor`.
- **Documentation landing.** A line that states a constraint lands in T-docs-0 (M0); a line that names a
  command, marker or file lands with the task that creates it; a design-record or docs line lands in the
  same commit as the code that makes it true, in the task its "Lands with" cell names (DT-25 "Landing
  rule", DT-26 "Landing rule"); T-docs-Z (M19) runs last. The task that finishes a spec build step flips
  its tag in `design/roadmap.html`'s RL row. A change to a decision cited by an AGENTS.md B-rule, a
  `CONTEXT.md` entry, an ADR or a spec amendment item updates that text in the same change.
- **Whole-file deletions and renames.** Implementation agents cannot delete tracked files: the orchestrator
  removes every whole file or directory a task lists (`git rm`) before the implementation pass, and
  performs every listed rename (`git mv`) before the pass, so the implementer edits the new path and
  reads deleted files with `git show <base>:<path>`. An implementer that finds another whole file to
  delete reports it and stops. The verifier checks the lists against `git status`.
- **Duplication baseline.** `scripts/duplication_baseline.json` (123 clones at `fa51f46`) only ratchets
  down through `uv run --locked python scripts/check_duplication.py src --update-baseline`. A new or
  changed clone signature is accepted only through a reviewed hand edit of the baseline, traced to a
  deletion, a rename or a reviewed new module. `check_duplication.py` (`_regressions`) reports every file
  tuple the baseline lacks as a new group: deleting one member file of a clone group leaves a subset
  signature and a rename leaves a re-pathed one, and each needs a hand edit. Two kinds of entry are
  exempt from the cap: a subset signature left by a deletion, no larger than the baseline group it came
  from, and a pure re-path of an existing signature at the same size. Every other new or grown signature
  counts against a cap of four per planning group (see "Planning groups"). M1.4 and M1.6 each carry this
  reviewed hand-edit step. Each edit, its kind (subset, re-path or capped) and the group's running total of
  capped signatures are recorded under "Execution notes".
- **Races.** An intermittent failure of a named race or crash-matrix test (DT-14 crash matrix, DT-17
  `test_etag_cas_race`, DT-10 bootstrap and last-owner races, DT-21 push matrix) is a failure and is never
  re-run to green; it stops the milestone that owns the mechanism until a fix lands with a named test.
- **Settled decisions.** Owner decision 12 settled every open question, so nothing in this plan waits on
  an owner answer. A task whose content rests on a settled question carries the line
  "- Decisions: OQ-x.y (settled, owner decision 12)" for traceability only. An external assumption that
  proves false (see "External assumptions to confirm before production") is a new design change with new
  tasks.
- **Design references.** Tasks cite `RAW_LAKE_DESIGN.md` by section heading ("DT-12 design: Collections
  lifecycle and activation" → "DT-12 activation sequence and failure table") and never restate it. Where
  sections disagree, the later, consolidating one wins: DT-17 "resolved disagreements between sections"
  (D-1 … D-8) for tables, adapters, locks and the store bundle; DT-18 for routes, paging spellings, status
  codes and the merged `ApiSettings`; DT-15 for `Volume.rename_collection` (replaced); DT-25 and DT-26 for
  binding-rule and document wording; DT-2 for the deletion order (it overrides DT-1's tree where R2-3
  keeps `PosixGenerationStore`). A planner greps `RAW_LAKE_DESIGN.md` for the DT ids a task covers to
  collect every handoff addressed to them.
- **Clean sweep.** No compatibility shims, aliases, re-exports, transitional names, TODOs,
  commented-out code or partial migrations; no old configuration key, environment variable, route path or
  URL fragment kept beside its replacement; no request or response shape accepted in two forms; no
  migration that preserves, converts or exports legacy data, and no refusal flag guarding its loss; no
  interim state kept for old clients or old data; obsolete paths are deleted, not hidden (owner
  decision 11, B-4); no suppressions (`# noqa`, `# type: ignore`,
  `# pragma: no cover`, skip or xfail) or configuration exclusions. Comments, docstrings, test names and
  messages never cite a plan task, milestone, DT, OQ or design-receipt id. The only tool-configuration
  changes are the ones the design specifies, exactly as specified: `fail_under` under the rules above;
  the import-linter contract set (DT-1, DT-17); the Ruff `TC` per-file ignore for the CLI (DT-1); the
  `google-re2` dependency and its one mypy/ty override (DT-9); `typer`, `rich`, `questionary` and
  `[project.scripts]` (DT-1, DT-19); the `stack` and `nfs` markers (DT-23). One repository convention
  extends with the design's names: a module that declares a design-named exception without an `Error`
  suffix gets a Ruff `N818` per-file ignore beside the existing errors-module entries, in the task that
  creates the class (`core/metastore/lake/memory.py` M7.1, `core/lake/errors.py` M7.2,
  `core/metastore/lake/_db.py` M7.3, `core/lake/admin.py` M7.8, and whichever of `core/lake/commits.py`
  (M13.3, `LeaseLost`) and the CLI's `errors.py`, `walkthrough.py`, `staging.py` and `writer.py` (M10.1,
  M10.7, M14.1, M14.3) `uv run ruff check src` flags); an entry whose module is deleted leaves with it.
- **No backwards compatibility.** Owner decision 11 binds every task: Huron keeps nothing working for an
  old client, an old binding, old data or an old name. A task adds no shim, alias, re-export, deprecated
  name, second accepted request or response shape, data-preserving migration (or flag guarding data loss)
  or interim state; development rows in dropped tables are discarded. When a task removes or renames a
  name, route, setting, environment variable, header form or error code, it deletes or rewrites every
  caller, test, fixture, document line and configuration entry that names the old one in the same task.
  The live legacy surface of Owner decisions 1 and 10 (the org/project/dataset `/api/v1` routes and their
  credentials, the web's own login and accounts) stays because it is in use and may change shape; a
  choice made only to keep its existing clients, bindings, data or names working is a compatibility
  provision. Safety checks on the new system's own data (lake downgrade refusals, state-file version
  refusals) and history notes in superseded documents are not compatibility (owner decision 11).
- **Skills.** `oop-design` for `src/huron/core`; `fastapi` for `src/huron/applications/api`;
  `postgresql-table-design` for migrations and PostgreSQL adapters; `codebase-design` for
  `src/huron/applications/cli` (no area skill covers it, DT-19); `writing-for-agents` for `AGENTS.md`
  and `CLAUDE.md`; `domain-modeling` for `CONTEXT.md` and ADRs; `svelte-core-bestpractices` and
  `svelte-code-writer` for Svelte; `tailwind-design-system` for styling.
- **Commits.** The orchestrator commits each task after its verification passes: one task per commit,
  authored by the configured `karthedew <35015336+karthedew@users.noreply.github.com>`, with a message
  that ends with the trailer
  `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`. Nothing is pushed except by the merge task.
- **Merge.** `raw-storage` merges into `main` with a merge commit, never a squash (DT-25 D-2: the P3 links
  are pinned at `f1c44e3`), only after every task is verified, every required CI check (lint, unit,
  contract, integration, stack, nfs, large-file) is green and the last two `nightly.yml` runs on the pull
  request are green. GitHub starts `schedule` and `workflow_dispatch` only for workflows on the default
  branch, and `nightly.yml` exists only on `raw-storage` until the merge, so `nightly.yml` also triggers on
  `pull_request` (types `labeled`, `synchronize`) with the job-level condition
  `if: github.event_name != 'pull_request' || contains(github.event.pull_request.labels.*.name, 'nightly')`;
  M19.5 opens the pull request, adds the `nightly` label and polls `gh run list` until two consecutive
  runs show `nfs-large` and `unit-macos` both succeeded (a run whose jobs were skipped does not count). The
  `schedule` trigger stays and runs on `main` after the merge.

### Plan-time resolutions of design text

Each line below is a place where this plan deliberately differs from `RAW_LAKE_DESIGN.md`'s text. The design
file is not edited for them; an implementer follows the plan, and the named tasks carry the detail.

- **`LakeStore` method names (DT-13, DT-14, DT-16, DT-17).** A method on the composite `LakeStore` whose bare verb would collide carries its resource noun, so DT-17's no-shared-name test and MRO hold: `CommitQueue`'s `claim`, `extend`, `checks`, `release`, `fail`, `expire`, `prune` are `claim_commit`, `extend_commit`, `commit_checks`, `release_commit`, `fail_commit`, `expire_commits`, `prune_commits` (M13.3, M13.5, M13.7); `FileStore.page` is `file_page` (M13.2, M13.4, M13.6); `FindingStore.page` and `FindingStore.prune` are `finding_page` and `prune_findings` (M17.1); `AccessResetQueue` keeps `claim`, `extend`, `complete` on the root only; the transaction composes only the `AccessResetWriter` half, because `RetryTransaction.claim` is on it (M11.1, M11.8, M11.12). Every task, test name and contract-test scenario uses the new spellings.
- **Contract 19 (DT-17).** Written as two `forbidden` tables, because `independence` cannot express it over legacy modules that import one another (M4.1), so `lint-imports` counts 17 after M4.1, 18 after M7.3 and 20 at the end (M10.1).
- **Contract 9 at the rename (DT-1).** DT-1's landing list changes 2, 4–6, 10, 11, 13 and 14 at the rename; contract 9 also forbids `huron.core.catalog`, so M2.1 re-paths it to `huron.core.hierarchy` in the same commit.
- **Contract 9 and `huron.schema` (DT-1, DT-11).** Contract 9 keeps forbidding `rawstore → huron.schema` although DT-11's `probe_mount` parses the marker and mountinfo with `huron.schema.volume`: the caller injects `VolumeRules(VolumeMarker.parse, mount_entry)` (M11.2, M11.11).
- **Catalog and schema store methods (DT-8, DT-9, DT-17).** The store halves take unique names: DT-8's `list` and `create` are `CatalogStore.catalogs` and `CatalogWriter.insert_catalog`, and DT-9's `list` and `insert` are `MetadataSchemaStore.schemas` and `MetadataSchemaWriter.insert_schema` (M7.2, M7.3). DT-8's compare-and-set config publish becomes DT-17's lock-then-check: `lock_catalog_config` (`FOR UPDATE`, version compared in Python) then `append_config` under `AND config_version = $n`, zero rows raising `LockContractBroken` (M7.3, M7.4, M8.5).
- **`Services.prompter` (DT-19, DT-20).** A factory, `Callable[[], Prompter]`, not a `Prompter` instance, because `QuestionaryPrompter` refuses a non-TTY `stdin` at construction (M10.7).
- **`huron check` JSON and YAML (DT-20, DT-21).** One object, `{"catalogs": [...], "pending_pushes": [...]}`, because an array cannot carry DT-21's `pending_pushes` "beside the per-catalog items" (M18.3).
- **Mount key spellings (DT-19, DT-21, DT-23, DT-26).** `mount_prefix` and `mount_policy` with `_`, the later sections winning over DT-19's `mount-prefix`; the three connection keys keep DT-19's spelling (M10.1, M14.3).
- **CLI guide §5 placement (DT-26).** `docs/raw-lake/cli.md` §5 says the partial is placed by `link` (by `rename` only with `--overwrite`), the built behaviour, where DT-26's outline says "place by `rename`" (M14.4).
- **`Collections.search` (DT-12, DT-18).** Takes the `label` filter as a parsed `Mapping[str, str]`; the route model parses DT-18's grammar and raises its 422 `REQUEST_INVALID` (M11.9, M11.13).
- **Access-reset outcome (DT-7, DT-11, DT-16, DT-17).** `AccessResetWorker` logs one structured record carrying the `ResetReport` per finished reset and writes no audit entry, superseding DT-11's audit bullet: DT-7 does not audit ACL resets and DT-17 seeds no `access_reset` pair (M11.12).
- **Commit serialization failures (DT-14, DT-17).** DT-14's in-attempt retry on `40001`/`40P01` is not built: DT-17 lets those errors propagate and `huron.core.lake` cannot import `asyncpg`, so such a failure ends in the transient release path (M13.7; Risk register 2).
- **Commits.submit result (DT-14, DT-18).** `submit` returns `Submission(view: CommitView, replayed: bool)` instead of DT-14's bare `CommitView`, so the commit route can tell a fresh 202 from an `Idempotency-Key` replay and calls `CommitWorker.wake()` only when `replayed` is false (M13.6, M13.9).
- **Role-mapping `role_scope` test case (DT-10).** DT-10's test row has a PA mapping `organization_admin` on a catalog answer `role_scope`, but its order of checks refuses that PA at step 2 (the ceiling, 403) before step 3; the plan keeps the order, tests that PA case as 403 and drives the 422 `role_scope` case with a global OA (M7.6, M9.5).
- **Signing-key idempotency receipts (DT-10).** `rotate`'s receipt is `Replay("signing_key", uuid5(<module namespace>, kid))`, where the design keys the receipt by UUID and the key by `kid` without naming the mapping (M7.7).
- **Ruff `N818` per-file ignores.** A module declaring a design-named exception without an `Error` suffix gets an `N818` per-file ignore beside the existing errors-module entries, a tool-configuration change the design does not list ("Clean sweep"; M7.1, M7.2, M7.3, M7.8, M10.1, M10.7, M13.3, M14.1, M14.3).
- **Web test count and DT-3's case-insensitive check (DT-3 R3-3, "Closing checks").** R3-3 counts two tests in `polaris-raw.test.ts`'s `describe('Raw collection registration')`; it holds six Vitest cases (two `it` and a four-row `it.each`), so after D2-0 `npm test` reports 19 files and 215 tests, not 219 (M1.1, M1.2). DT-3's first closing check runs `isRaw` under `-i`, which also matches `PolarisRawTable` and `PolarisRawTableIdentifier` until D2-0b renames them, so M1.1 accepts exactly those lines and checks `\bisRaw\b` case-sensitively, and M1.2 re-runs the full check (owner ruling, 2026-10-24).
- **Nightly runs before the merge (DT-23 "Gates", "CI workflow job outlines").** `nightly.yml` keeps `schedule` and `workflow_dispatch` and also triggers on `pull_request` (types `labeled`, `synchronize`) behind the job-level `if` in the "Merge" rule, so the last two nightly runs come from the pull request's `nightly` label instead of a dispatch the default branch would refuse (M19.5).

## Milestone sequence

Milestones run in this order; each leaves the full gate green. "Depends on" names the milestones whose
code a milestone builds on (the order already satisfies them). Design sections are headings in
`RAW_LAKE_DESIGN.md`, abbreviated "DT-n" for "DT-n design: …".

| Milestone | Title | Intent | Design sections | Depends on | Settled OQs (owner decision 12) |
| --- | --- | --- | --- | --- | --- |
| M0 | Baseline and binding documents | M0.1 commits `RAW_LAKE_SPEC.md`, `RAW_LAKE_DESIGN.md`, this plan, the owner's two uncommitted banner lines in `RAW_STORAGE_*.md` and `design/roadmap.html` as `/design-plan` Phase 5 left it (the RL row, the pinned P3 links, P0's D-1 withdrawal, Milestone 23's D-7 move), all as they stand, and records the baseline (gate, 16 contracts, test counts, coverage totals). T-docs-0 then rewrites everything review enforces before any code changes: `AGENTS.md` AG-1 … AG-11 (B-1 … B-9), the whole `CONTEXT.md`, ADR 0002's amendment and ADRs 0003–0007, one superseded banner per old file in DT-25's wording (replacing the owner's interim line), the three D-2 links outside `design/roadmap.html` and the `docs/history.md` archive row, the spec's "Design amendments (2026-10-23)" A-1 … A-30, and DT-26's T-docs-0 lines (`catalog-search.html` §1 GIN lift, `rbac.html` §4 overwrite, Bronze/Silver lineage pins, `layer-silver.html:247`, the roadmap's M1.1, P9 and milestones 9–10 (the RL row arrived with M0.1 and is only verified), and the five status lines). T-docs-0 may be split into consecutive tasks; all of them precede M1. | DT-25 (all); DT-26 decisions, "design record pages" (T-docs-0 cells), "roadmap rows", "developer docs, README and history" (T-docs-0 cells), handoffs | — | OQ-1.2, OQ-4.1, OQ-4.2, OQ-5.2, OQ-8.1, OQ-8.2, OQ-8.3, OQ-9.1, OQ-13.1, OQ-13.2, OQ-13.3, OQ-14.1, OQ-14.2, OQ-14.3, OQ-15.1, OQ-15.3, OQ-16.1, OQ-16.2, OQ-16.3, OQ-18.1, OQ-18.3, OQ-20.2, OQ-20.3, OQ-25.1 |
| M1 | Legacy Raw deletion | DT-2's order, one task per step: D2-0 (web Raw surface, DT-3), D2-0b (generic rename), D2-1 (Raw bridge, `raw_environment`), D2-2 (Raw engine and its v1 surface; `acceptance.yml` becomes `nightly.yml` in the same commit, holding only DT-23's `unit-macos` job until M15 adds `nfs-large`, because no `acceptance` test exists after the old gate leaves), D2-3 (`rawstore` reduced to `PosixGenerationStore` and the surviving primitives), D2-4 (Owner decision 10 credentials and the whole `/auth` router; owner decision 11, B-13), D2-5 (`0014_retire_legacy_raw`, schema map, `test_retire_legacy_raw.py`). Each step applies the coverage-floor procedure, its closing `rg` checks and the DT-26 page lines DT-2/DT-3 own (layer-raw §11–§12 and status line, P2/P3/M7/M8 retirements, UI-α/β and P10, `polaris.html`, `frontend.html`, `auth.html` §2–§4, the `api.html` P3 section). | DT-3 (all); DT-2 (all); DT-22 decisions (`raw_environment` in D2-1); DT-23 deletions; DT-26 rows naming DT-2 or DT-3 | M0 | OQ-1.1, OQ-2.1, OQ-2.2 |
| M2 | Hierarchy rename and shared route modules | `huron.core.catalog` → `huron.core.hierarchy` with its symbol renames and contracts 2, 4–6, 9, 10, 11, 13, 14 (count stays 14); `routes/v1/{preconditions,pagination}.py` → `routes/`; the `applications` and `routes` docstrings; `catalog-search.html`'s two code links (`core/catalog/` and the deleted `core/raw/`) and `repository-layout.md`'s tree. No lake module yet. | DT-1 decisions, "target package tree", "import-linter contract set", "deletions and renames"; DT-18 deletions (moved modules); DT-26 handoffs to DT-1 | M1 | — |
| M3 | Broker values, keys and tokens | Pure `huron.core.security.broker`: the rank ladder, `Grants`, the `RoleMappingReader` port and the roles-claim grammar (`ladder.py`); signing-key values, `KeyRing`, `HuronKeys`, `SigningKeySource` with `FileSigningKeySource`, `SigningKeyReader`, the rotation rule and `SigningKeyUnavailable`/`RotationRefused` (`keys.py`); `HuronClaims`, issuer and verifier and `tests/lake_tokens.py` (`tokens.py`). Nothing is wired into the app. | DT-4 decisions, "ladder and every spec route", `broker/ladder.py`; DT-5 (all but `routes/discovery.py` and the settings/composition part) | M2 | OQ-4.2, OQ-5.1 |
| M4 | In-memory lake store and request-time authentication | The first `huron.core.lake` module (`ports.py`: the `LakeStore`/`LakeTransaction` composites, D-2) with contract 7 and the lake entries of the other contracts and DT-17's contract 19 (contract 16 follows with the first `huron.core.lake._impl` module, M7 at the latest); `huron.core.metastore.lake` `memory.py` (`InMemoryLakeStore`, `InMemoryLakeTransaction`, `LakeTables`, `LakeBuffer`, lock registry) with the role-mapping and signing-key read halves; `tests/lake_store_contract.py` and `test_lake_memory_store.py`; `Actor` and `LakeAuthentication` (`broker/access.py`). | DT-4 `broker/access.py`, "logical tables", "tests this design requires"; DT-17 decisions, "target module layout", "interfaces and contracts", "port → adapter → fake", "resolved disagreements" D-2 | M3 | OQ-4.2 |
| M5 | Identity mocks and the token exchange | DT-22's `tests/fakes/` (`identities.yaml`, `ldap_groups.py`, `oidc_issuer.py`), `tests/conftest.py` fixtures and the three `test_fake_*` modules first (with `scripts/keycloak/company-realm.json`, which the realm-drift test pins); then `DependencyUnavailable` into foundation, the async `CompanyTokenVerifier` with the legacy bearer re-wired over it, `GroupDirectory`/`HttpGroupDirectory`/`parse_groups_response`, and the `TokenExchange` workflow, all tested against the fakes with no bypass. No route and no settings change yet. | DT-22 decisions, "target layout", "shared fixture and the `company` realm", "interfaces and contracts", "tests this design requires", build order; DT-6 (all but the route and settings diff) | M4 | OQ-6.1, OQ-6.2, OQ-20.3, OQ-22.1 |
| M6 | Shared rules in `huron.schema` | The rules the server and the CLI share: `naming.py` (segment, slugify, reserved names, depth, `Identifier`'s four forms) with Hypothesis properties; `catalog_config.py` and `catalog-config-v1.json`; the RE2-backed `_validator.py` with `google-re2` and its type override; `metadata.py` (DT-7's `field_changes`, DT-9's `compose`, `ComposedSchema`, `MetadataValidator`) and `org-base-v1.json`. | DT-8 `huron.schema.naming`, `huron.schema.catalog_config`, `catalog-config-v1.json`; DT-9 decisions, "composition algorithm and worked example", `huron.schema._validator`, `huron.schema.metadata`; DT-7 `huron.schema.metadata` (field diff) | M2 | OQ-8.1, OQ-8.3, OQ-9.2 |
| M7 | Audit, catalogs, schemas and administration | The step-1/2 lake domain over the in-memory store: DT-7's vocabulary, entries, `AuditWriter` and idempotency claims half (M8.5 writes the paging-only `PostgresAudit.collection_log`; `collection_catalog`, the `AuditReader` port and its in-memory half are M16.1's); DT-8's `NamespacePath` and `Catalogs` (create, publish config, naming translation, `require_on_catalog`); DT-9's `MetadataSchemas` registry and `Validation`; DT-10's `RoleMappings`, `SigningKeyAdmin` and `LakeBootstrap`. Completeness recompute over collections waits for M11. | DT-7 (all but the table section); DT-8 "ltree encoding", `huron.core.lake.catalogs`, logical shapes; DT-9 `huron.core.lake.schemas` (registry, validation and cache); DT-10 (all but the route table); DT-4 `core/lake`: applying the grants | M4, M5, M6 | OQ-1.1, OQ-4.1, OQ-4.2, OQ-5.2, OQ-7.1, OQ-8.1, OQ-8.2, OQ-9.1, OQ-9.2, OQ-10.1, OQ-10.2 |
| M8 | Lake persistence, revision 0015 | `tests/postgres.py` replaces the four `_migrate` copies; `refuse_if_rows`; `0015_lake_catalog` with the `lake` section of `schema.sql` (and its header's G-21 rewording); `PostgresLakeStore`/`PostgresLakeTransaction`, `_db`, `locks`, the connection-class pool boundary and the Postgres halves for role mappings, signing keys, audit, idempotency, catalogs, configs and schemas; `ApiStores.lake`, `_postgres_stores`, `memory_stores()` and `/readyz` `"lake"`; the contract tests of DT-17 for these tables. | DT-17 (decisions, revision list, DDL `0015_lake_catalog`, resolved disagreements, layout, interfaces, port → adapter → fake, `ApiStores` diff, migrate helper and tests, `schema.sql` and import rules, handoffs); DT-7 table, index and trigger; DT-18 "store outage boundary" | M1, M7 | OQ-1.1, OQ-4.1, OQ-4.2, OQ-5.2, OQ-7.1, OQ-7.2, OQ-8.3, OQ-17.1, OQ-17.2, OQ-18.1 |
| M9 | API composition for auth, catalogs and administration | In one step with DT-6's settings diff: DT-22's realm swap, compose, `Makefile` (`dev-keys`, `HURON_UID`), `dev.env`, `check-stack.sh` and `scripts/dev_signing_key.py`; the lifespan (`LakeBootstrap` before `HuronKeys`, the two `AsyncClient`s); discovery and `/auth/exchange` (re-creating the `/auth` router M1.6 deleted, with the exchange only; owner decision 11, B-13); the lake router, `current_actor` and its composition tests; routes rows 1–22 (catalogs, configs, schemas, role mappings, signing keys) with their §7 rows and DT-26 page lines. | DT-18 decisions, layout, route table rows 1–22, models, "interfaces and contracts", error-code rows, settings diff, tests; DT-5 `routes/discovery.py`, "settings, composition, errors and readiness"; DT-6 `routes/auth/endpoints/exchange.py`, "settings diff, startup refusals and composition"; DT-10 "administration route table"; DT-22 "compose, Makefile, `dev.env` and `check-stack.sh`" | M5, M7, M8 | OQ-4.2, OQ-5.2, OQ-5.3, OQ-7.2, OQ-10.1, OQ-10.2, OQ-18.1, OQ-22.1 |
| M10 | CLI foundation, login, browsing and administration verbs | `huron.applications.cli` with `[project.scripts] huron`, `typer`/`rich`/`questionary`, contracts 17 and 18 and the Ruff `TC` entry; `errors`, `services`, `state` (XDG, lock, atomic 0600 writes), `output`; the client-side `CompanyOidcProvider` (device grant with PKCE, loopback) and the login session (refresh then re-exchange, `whoami`, `logout`); `HuronClient`, `resolve.py`, `catalog use`, `config view/set/unset`, `get catalogs`, `explain catalog`; DT-20's administration verbs behind the `Prompter` seam and `meta template`/`meta validate`. Lands DT-26's README CLI bullet, `python-client.html`, roadmap P0 (contract 17) and P8 lines, and CLI guide §1–§2, §10; flips RL steps 1 and 2. | DT-19 (all); DT-20 decisions, "command signatures, routes and exit codes" (admin and `meta` rows), `commands/admin.py`, `commands/meta.py` (template, validate); DT-1 `huron.applications.cli` | M6, M9 | OQ-5.2, OQ-18.1, OQ-19.1, OQ-19.2, OQ-22.1 |
| M11 | Volume, permissions and collections | Spec step 3 on the server: `huron.schema.volume` (marker, and the shared `mount_entry`); `rawstore` `anchored.py` (from `materialize.py`), `mount.py`, `PosixVolume`, `RecordingPermissions`/`Nfs4AclPermissions`, `completion.py` deleted; the lake `Volume`, `DirectoryPermissions`, `CatalogAccessReader`, `AccessResetQueue` ports and `Directories`; `0016_lake_collections` with the namespaces, collections and access-reset halves and their contract tests; `Collections` (draft, merge-patch save, activate, get, search, delete) with `MetadataFile`, `apply_merge_patch` and `require_on_collection`; completeness recompute on config and schema publish; the lifespan volume, `/readyz` `"volume"`, `AccessResetWorker`, and `map`/`unmap` requesting resets (D-6); DT-23's stand-in (`tests/fakes/ontap_volume.py`, `make raw-lake-init`, `make raw-lake-snapshot`, the compose `/projects` bind, `dev.env` volume settings, `check-stack.sh volume`); routes rows 23–30 with the `label` filter and `test_label_search_uses_gin`. | DT-11 (all); DT-12 (all); DT-17 DDL `0016_lake_collections`; DT-9 "validation, the cache and the Incomplete computation"; DT-18 rows 23–30, "paging keys and the `label` filter"; DT-23 "the volume stand-in", "make targets, compose, `dev.env` and `check-stack.sh`"; DT-10 and DT-17 D-6 | M1, M8, M9 | OQ-4.1, OQ-9.1, OQ-11.1, OQ-11.3, OQ-11.4, OQ-12.1, OQ-17.1, OQ-17.2, OQ-18.2, OQ-18.3, OQ-20.1, OQ-21.1 |
| M12 | CLI collection creation and browsing | DT-20's walkthrough (plan, sinks, state machine, `--resume`, `--no-input --set`; the `Prompter` seam and `QuestionaryPrompter` are M10.7's), `create collection [-f]`, the draft list, `delete collection`; DT-19's `get namespaces`, `get collections`, `describe collection`. CLI guide §3–§4; flips RL step 3. | DT-20 "walkthrough: plan, prompts, sinks and the state machine", "walkthrough as a state machine", command rows for create, draft and delete; DT-19 browse verbs | M10, M11 | OQ-12.1, OQ-18.2, OQ-20.3 |
| M13 | Files and asynchronous commit | Spec step 4 on the server: the `rel_path` rule in `huron.schema.naming` with its Hypothesis properties; `lake/files.py` values and the decision table, `commit-request-v1.json` and the lake codes it raises; `0017_lake_commits` with the files, commits and commit-checks halves and their contract tests (C15, C17, `test_rel_path_check`); `Commits` (submit, status, work, housekeep) with `Volume.verify` stamps and the `FaultingLakeStore` crash matrix; `CommitWorker` in the lifespan with its settings, the commit prune and `prune_claims`; routes rows 31–33 and row 32's `test_lake_openapi.py` case (M11.14 creates the module). | DT-13 (all); DT-14 (all); DT-17 DDL `0017_lake_commits`; DT-18 rows 31–33 | M11 | OQ-1.2, OQ-2.1, OQ-13.1, OQ-13.2, OQ-13.3, OQ-14.1, OQ-14.2, OQ-14.3, OQ-17.1, OQ-17.3 |
| M14 | CLI working copy and push | DT-20's working copy (`staging.py`, `collections/<uuid>/` files, conflict rules, `sync.pull` with the three-way metadata rebase) with `checkout`, `switch`, `add`, `rm`, `status`, `diff`, `discard`; DT-21's `writer.py` (mount probe, traversal, partial copy and resume, `link`/`rename` placement) and `push.py` (step algorithm, `staged.push`, `Idempotency-Key`, polling, unlink) with the push crash matrix. CLI guide §5, §6, §8. | DT-20 "working copy: `collections/<uuid>/` schemas and the write rules", conflict rules, `staging.py`, staging command rows; DT-21 (all) | M12, M13 | OQ-20.2, OQ-21.1, OQ-21.2, OQ-21.3 |
| M15 | Test tiers, large-file gate and CI jobs | DT-23's markers `stack` and `nfs` with the tier guard and B-10; the plain-directory large-file gate (`tests/acceptance/`, `acceptance_support.py` at 12 GiB, the CI `large-file` job, `make test-acceptance`, B-11's 12 GiB line; flips RL step 4); the loopback NFS harness (`scripts/loopback_nfs.sh`, `tests/nfs_support.py`, `tests/linux/` with DT-11's cases 1–5, OQ-21.3's case and DT-21's writer cases, the CI `nfs` job, `make test-nfs`, `nightly.yml` `nfs-large`); the stack tier (`tests/stack/test_stack_push.py`, `make test-stack`, the CI `stack` job) and AG-14 (the integration job's exit-5 tolerance removed); `testing.md` per DT-23. | DT-23 (all but the stand-in sections M11 landed); DT-25 AG-12 … AG-14, B-10, B-11; DT-22 "how each test tier reaches each mock" | M11, M14 | OQ-11.1, OQ-11.2, OQ-21.3, OQ-22.2, OQ-23.1, OQ-23.2 |
| M16 | Metadata publish and `mv` | Spec step 5 on the server: `PUT …/metadata` (row 34) with the field-diff audit `detail`; bulk metadata edits (row 10); `mv` (row 35) with the staged move replacing `Volume.rename_collection`, `Directories.place_moved`, relocation and namespace pruning, its failure table and the DT-15 cases on the `nfs` tier; the collection log route (row 36). `layer-raw.html` §6, §8, §9 (CLI guide §7 lands with the verbs it names: M12.3, M14.2, M18). | DT-15 (all); DT-7 `GET /api/v1/collections/{id}/log` and the reader; DT-18 rows 10, 34–36 | M13, M15 | OQ-7.1, OQ-11.1, OQ-15.1, OQ-15.2, OQ-15.3 |
| M17 | Reconciler | Spec step 6 on the server: `0018_lake_reconciler` with the findings and status halves and their contract tests; the pure scan classifiers and DT-16's `Volume` additions; `Reconciler` and `ReconciliationFindings` (metadata repair, stale drafts, access drift and resets); `applications/api/reconcile.py` `main()` with its settings and exit codes; route row 37; DT-16's `nfs` cases and the nightly `test_reconciler_scale.py`. `layer-raw.html` §10, runbook §5. | DT-16 (all); DT-17 DDL `0018_lake_reconciler`; DT-18 row 37; DT-23 "placement of the handed-off tests" (DT-16 rows) | M15, M16 | OQ-1.1, OQ-11.1, OQ-11.3, OQ-12.2, OQ-12.3, OQ-16.1, OQ-16.2, OQ-16.3, OQ-17.1 |
| M18 | CLI metadata editing, `mv`, log and check | DT-20's `sync.publish_metadata` (pull and rebase are M14.1's), `meta update` staged and published by `push`, `meta bulk-update`, `diff`; `mv --set`, `log`, and `check` (findings, Incomplete collections, pending pushes; no `--repair`). Flips RL steps 5 and 6. | DT-20 "`sync.py`: pull, rebase and publish", command rows for meta, mv, log and check; DT-21 handoffs to DT-20 | M14, M16, M17 | OQ-15.1, OQ-15.2, OQ-16.1, OQ-16.2, OQ-20.1, OQ-20.4 |
| M19 | Closing documentation, verification and merge | T-docs-Z (overview pages, README lede, `docs/index.md`, `backend-design.md`, `history.md`, the dated atlases and the retired `rawstore-uml`, roadmap P4, the sketch and the RL row's `done` tag (P0 and Milestone 23 were corrected at planning time and are only verified), `auth.html` §7, the rest of the two `docs/raw-lake/` pages and their navigation group, B-1 and the status lines removed) and `scripts/check_design_links.py` in `make docs` and CI's lint job; then the final verification (DT-24's closing check, every closing `rg` check, the coverage re-measure, the CI receipts) and the merge into `main` by a merge commit. | DT-26 (all T-docs-Z rows, "interfaces and contracts", "broken links and their fixes"); DT-24 "explicitly not built in this plan", handoffs; DT-23 "Gates", coverage-ratchet decision; DT-25 D-2 merge condition | M18 | OQ-2.3, OQ-5.1, OQ-7.1, OQ-11.1, OQ-11.2, OQ-11.4, OQ-16.2, OQ-16.3, OQ-21.3, OQ-22.1, OQ-22.2, OQ-23.1, OQ-23.2, OQ-24.1, OQ-24.2, OQ-26.1 |

### Planning groups

Each group is detailed by one planner. Every planner also reads this head, `RAW_LAKE_SPEC.md`'s owner
decisions, the design's "Current State" → "Conventions the design must follow", the register entries
of the OQs its milestones carry, and DT-26's "Lands with" cells that name its DTs (grep `DT-n task`).

| Group | Milestones | Read in full | Also read | Notes |
| --- | --- | --- | --- | --- |
| G1 | M0, M1, M2 | DT-1, DT-2, DT-3, DT-25 | DT-26 decisions, "design record pages", "roadmap rows", "developer docs, README and history", handoffs; DT-22 decisions (`raw_environment`); DT-23 deletions | T-docs-0 precedes D2-0. D2-0 … D2-5 run before the rename (DT-2 "Order with DT-1"). Re-count the Raw test files before D2-2. |
| G2 | M3, M4, M5 | DT-4, DT-5, DT-6, DT-22 | DT-1 "interfaces and contracts" (`broker`, contract set); DT-17 decisions, "target module layout", "interfaces and contracts", "port → adapter → fake", D-2 | Nothing is wired into `create_app` before M9. No `ApiStores.role_mappings` or `.signing_keys` (D-2). The fakes land before the tests that use them. |
| G3 | M6, M7 | DT-7, DT-8, DT-9, DT-10 | DT-4 "`core/lake`: applying the grants"; DT-17 D-1, D-4, D-6, D-7 | Postgres halves and `0015` are M8. Completeness over collections and `request_access_reset` are M11. Lifespan bootstrap and routes are M9. |
| G4 | M8, M9 | DT-17, DT-18 | DT-5 `routes/discovery.py`, "settings, composition, errors and readiness"; DT-6 route, settings diff; DT-7 table section; DT-10 route table and bootstrap; DT-22 "compose, Makefile, `dev.env` and `check-stack.sh`", build order | `0015` lands with every half that writes its tables. DT-22's realm and `dev.env` step and DT-6's settings diff are one task. Routes rows 1–22 only. |
| G5 | M11, M13 | DT-11, DT-12, DT-13, DT-14 | DT-17 DDL `0016`, `0017`, D-3, D-6, D-8; DT-18 rows 23–33, "paging keys and the `label` filter"; DT-9 Incomplete computation; DT-15 "the `Volume` port, `rename_collection` replaced"; DT-23 stand-in sections | Do not build `Volume.rename_collection` (DT-15 replaces it). Linux-only cases wait for M15's `tests/linux/`. |
| G6 | M10, M12, M14, M18 | DT-19, DT-20, DT-21 | DT-1 `huron.applications.cli`; DT-18 route table and handoffs to DT-19–DT-21; DT-22 handoff to DT-19; DT-8 `Identifier` | Milestones are not consecutive. Each depends on the server milestone named in the table. The CLI imports `huron.schema` only. |
| G7 | M15, M16, M17, M19 | DT-15, DT-16, DT-23, DT-24, DT-26 | DT-17 DDL `0018`; DT-18 rows 10, 34–37; DT-25 AG-12 … AG-14, B-10, B-11; DT-11 and DT-21 Linux cases; DT-7 reader and log route | Tests marked `stack` or `nfs` take their receipts from CI. M19 checks every receipt before the merge. |

## Milestone 0 — Baseline and binding documents

Commit the spec, the design and this plan as the owner left them, measure the baseline every later task
compares against, and then rewrite everything review enforces before any code changes: `AGENTS.md`'s
binding rules, the whole `CONTEXT.md`, ADR 0002's amendment and ADRs 0003–0007, the superseded banners,
the five dangling P3 links, the spec's design amendments, and DT-26's constraint lines on the design
record. T-docs-0 is split into four consecutive tasks (M0.2–M0.5) by document family; M0.5 runs the
combined T-docs-0 closing check. No file under `src/`, `tests/`, `migrations/`, `web/` or
`.github/` changes in this milestone, so the code gate only has to stay green.

### M0.1 Commit the binding documents and record the baseline

- Intent: make the spec, the design, this plan and the planning-time roadmap reconciliation tracked history
  before anything acts on them, keep the owner's two interim banner lines exactly as they stand (T-docs-0
  replaces them in M0.4), and record the measurements the coverage-floor procedure, the router counts and
  the web counts of M1 compare against.
- Planning base: at the owner's request (2026-10-24) the six files below were committed and pushed before
  execution as "Plan the Raw data lake". M0.1 no longer stages them: it writes the baseline entry on that
  commit's tree and commits the plan alone.
- Delete: none.
- Create: none (the three files are tracked since the planning base).
- Modify: none by the implementer. The planning base holds exactly `RAW_LAKE_SPEC.md`,
  `RAW_LAKE_DESIGN.md`, `RAW_LAKE_IMPLEMENTATION_PLAN.md` (the assembled plan), the owner's uncommitted edits to `RAW_STORAGE_DESIGN.md` and
  `RAW_STORAGE_IMPLEMENTATION_PLAN.md` (one `> **Superseded 2026-10-23** …` line each) and
  `design/roadmap.html` as `/design-plan` Phase 5 left it (the "RL: Raw lake" row with its six `todo`
  step tags, P3's two D-2 links pinned at `f1c44e3`, P0's D-1 clauses withdrawn and Milestone 23's D-7
  "Built" claim moved into "Adds"), byte for byte. M0.1's own commit changes only
  `RAW_LAKE_IMPLEMENTATION_PLAN.md`: this task's baseline entry under "Execution notes" and its status.
- Baseline entry ("Execution notes", written before the commit): the plan-wide gate's result on
  `fa51f46`'s tree; `uv run lint-imports` "16 kept, 0 broken"; the pass counts of
  `uv run pytest -q`, `uv run pytest -m contract -q` and `uv run pytest -m integration -q`; the unit
  coverage totals (`covered_lines`, `num_statements`, `percent_covered`) from
  `uv run pytest --cov=src/huron --cov-report=json:<scratch>/baseline.json`; the duplication guard's
  reported groups and clones (41 groups, 123 clones in `scripts/duplication_baseline.json`); the
  legacy `/api/v1` operation count of `create_app(settings=<dev-headers settings>, stores=memory_stores())`
  measured by a scratch script outside the repository (52, R2-1); from `web/`, `npm test` (25 files,
  269 tests, R3-3) and `rg -c "^test\(" e2e/*.ts` (39 top-level Playwright tests).
- Design: "Roadmap Drift" → "Authority order", "Findings" (D-1, D-2, D-7); "DT-25 design: Binding rules,
  glossary, ADRs and lineage pins" → "DT-25 decisions" (G-21 row, "Spec amendments" row), "DT-25
  superseded banners and the D-2 links"; "DT-26 design: …" → "DT-26 roadmap rows (`design/roadmap.html`)"
  (RL row; P0 D-1; Milestone 23 D-7); `RAW_LAKE_SPEC.md` "Owner decisions (2026-10-23)" item 9.
- Verification:
  - The plan-wide gate exits 0 on the commit; `uv run lint-imports` keeps all 16 contracts.
  - `git show --stat --format= HEAD` lists only `RAW_LAKE_IMPLEMENTATION_PLAN.md`, and
    `git show --stat --format= HEAD~1` (the planning base) lists exactly the six files above;
    `git status --porcelain -- RAW_LAKE_SPEC.md RAW_LAKE_DESIGN.md RAW_LAKE_IMPLEMENTATION_PLAN.md RAW_STORAGE_DESIGN.md RAW_STORAGE_IMPLEMENTATION_PLAN.md design/roadmap.html`
    prints nothing.
  - `git diff -U0 fa51f46 HEAD -- design/roadmap.html | rg -c '^@@'` reports 6 (P0's two D-1 regions and
    its withdrawal note, the RL row, P3's D-2 links, Milestone 23); `rg -n 'RL: Raw lake' design/roadmap.html`
    prints the row; `rg -c 'id="rl-step-[1-6]"><strong>Step [1-6] — [^<]+</strong> <span class="tag">todo</span>' design/roadmap.html`
    reports 6; `rg -n '\.\./P3_|standing in for NFS|Built: the write-intent' design/roadmap.html` prints
    nothing.
  - `git diff fa51f46 HEAD -- RAW_STORAGE_DESIGN.md RAW_STORAGE_IMPLEMENTATION_PLAN.md` shows only the
    owner's two inserted banner lines and their blank lines; `git diff --check HEAD~1 HEAD` prints nothing.
  - The baseline entry carries every number listed above, each with the command that produced it.
- Dependencies: none.
- Status: done

### M0.2 T-docs-0a: `AGENTS.md` binding rules

- Intent: replace every `AGENTS.md` rule that would reject conforming lake code (G-21): the package tree
  and dependency table become DT-1's target behind one status bullet, the Raw engine's revision rules
  become the lake contracts, and the lineage, client and no-bypass rules are worded as DT-25 fixes them.
- Delete: none (text only; the removed lines are DT-25 "deletions": `AGENTS.md:29-30`, `:48-49`,
  `:83-85`, `:107-119`).
- Create: none.
- Modify: `AGENTS.md`, applying rows AG-1 … AG-11 of "DT-25 `AGENTS.md`: sections replaced" with the
  wording of B-1 … B-9 from "DT-25 `AGENTS.md`: the binding rules, worded" (line numbers there are at
  `fa51f46`, which is still this file's state): AG-1 B-1 status bullet; AG-2 B-2 tree; AG-3 "Hierarchy"
  for "Catalog" plus B-3; AG-4 B-4; AG-5 the new subsection B-5 after `:72` (the `:71-72` independence
  line stays); AG-6 B-6; AG-7 the client sentence quoted in its row; AG-8 B-7; AG-9 "pinned Raw inputs
  (see the lineage-pin rule)"; AG-10 B-8's first sentence plus the lineage-pin bullet from "DT-25 the
  lineage-pin rule (L-38 (a))"; AG-11 B-9's rule sentences only. B-9's last two sentences ("Two checks
  enforce this: …") name `tests/unit/test_fake_identities.py`, which M5 creates, so they land with that
  task (DT-25 handoffs, "Plan (later tasks)"). AG-12 … AG-14 (B-10, B-11, the integration-tolerance line)
  are not touched: they land with M15. AG-15: no change.
- Design: "DT-25 design: Binding rules, glossary, ADRs and lineage pins" → "DT-25 decisions" (Landing
  rule, Target-state tree, L-38 (a), Writing), "DT-25 `AGENTS.md`: sections replaced", "DT-25
  `AGENTS.md`: the binding rules, worded", "DT-25 the lineage-pin rule (L-38 (a))", "DT-25 interfaces and
  contracts" (`AGENTS.md`); "DT-1 design: …" → "DT-1 dependency graph" (table B-6 copies).
- Skills: `writing-for-agents`.
- Verification:
  - `git diff --check` prints nothing.
  - `rg -n -i 'raw revision|verified payload|removal intent|pending removal|git-like|dataset\.upload|0010_independent_raw' AGENTS.md`
    prints nothing (DT-25's vocabulary check minus `25 GiB`, which names the acceptance gate that still
    exists until M1.4 deletes it; M1.4 removes that line).
  - `rg -n '^\s+(catalog|raw)/\s|`(catalog|raw)`' AGENTS.md` prints nothing.
  - `rg -n 'Until .RAW_LAKE_IMPLEMENTATION_PLAN.md. completes' AGENTS.md` prints exactly B-1's line.
  - `rg -n 'test_fake_identities|make test-stack|make test-nfs|12 GiB' AGENTS.md` prints nothing (each
    lands with the task that creates what it names).
  - `CLAUDE.md` is unchanged (`git diff --quiet HEAD -- CLAUDE.md`).
- Dependencies: M0.1.
- Decisions: OQ-1.2 (settled, owner decision 12)
- Status: done

### M0.3 T-docs-0b: `CONTEXT.md` glossary, ADR 0002 amendment and ADRs 0003–0007

- Intent: give review and agents the lake's vocabulary and its five hard-to-reverse decisions before the
  first lake task: the whole glossary is replaced, ADR 0002 records the new owners by a dated amendment,
  and five accepted ADRs state `extends` composition, the catalog of record, no Raw versioning,
  asynchronous commit and the reconciler.
- Delete: all forty lines of today's `CONTEXT.md` (replaced; DT-25 "deletions").
- Create: `docs/adr/0003-metadata-schemas-compose-by-extends.md`,
  `docs/adr/0004-raw-catalog-of-record-is-huron-postgresql.md`, `docs/adr/0005-no-raw-versioning.md`,
  `docs/adr/0006-asynchronous-raw-commit.md`, `docs/adr/0007-raw-reconciler.md`, each with YAML
  front matter `status: accepted`, its title and the decision text of "DT-25 ADRs" verbatim (ADR-FORMAT
  of `domain-modeling`; 0002's file is the house example).
- Modify:
  - `CONTEXT.md`: the fenced block of "DT-25 `CONTEXT.md`: the replacement glossary", with its two-space
    indent stripped, is the whole file.
  - `docs/adr/0002-domain-owned-core-workflows.md`: the "*Amended 2026-10-23.*" block inserted directly
    under the title, above the 2026-09-15 text, which stays byte-identical; `status: accepted` unchanged.
- Design: "DT-25 design: …" → "DT-25 decisions" (D-4, ADR set, Handoff terms), "DT-25 `CONTEXT.md`: the
  replacement glossary", "DT-25 ADRs", "DT-25 interfaces and contracts" (`CONTEXT.md`, ADRs).
- Skills: `domain-modeling`.
- Verification:
  - `git diff --check` prints nothing; `make docs` exits 0 (Zensical builds every file under `docs/`,
    including `docs/adr/`, R25-3).
  - `ls docs/adr | wc -l | rg -v '^ *7$'` prints nothing;
    `rg --files-without-match '^status: accepted$' docs/adr/000[2-7]-*.md` prints nothing (ripgrep's `-L`
    is `--follow`, not files-without-match).
  - `git diff HEAD~1 -- docs/adr/0002-domain-owned-core-workflows.md` adds only the amendment block.
  - `rg -n -i 'raw revision|verified payload|removal intent|pending removal|git-like|dataset\.upload|0010_independent_raw' CONTEXT.md`
    prints nothing; `rg -n '^  (#|\*\*|- |> )' CONTEXT.md` prints nothing (the block's indent was
    stripped) and `rg -c '^\*\*' CONTEXT.md` counts one line per glossary entry.
  - Each OQ-dependent clause names its OQ: `rg -o 'OQ-[0-9]+\.[0-9]+' docs/adr/0003-*.md docs/adr/0006-*.md docs/adr/0007-*.md | sort -u`
    lists exactly OQ-9.1 (0003); OQ-14.1, OQ-14.2, OQ-14.3, OQ-18.1 (0006); OQ-16.1, OQ-16.2 (0007).
- Dependencies: M0.1.
- Decisions: OQ-8.1 (settled, owner decision 12)
- Decisions: OQ-8.2 (settled, owner decision 12)
- Decisions: OQ-8.3 (settled, owner decision 12)
- Decisions: OQ-9.1 (settled, owner decision 12)
- Decisions: OQ-13.3 (settled, owner decision 12)
- Decisions: OQ-14.1 (settled, owner decision 12)
- Decisions: OQ-14.2 (settled, owner decision 12)
- Decisions: OQ-14.3 (settled, owner decision 12)
- Decisions: OQ-15.1 (settled, owner decision 12)
- Decisions: OQ-15.3 (settled, owner decision 12)
- Decisions: OQ-16.1 (settled, owner decision 12)
- Decisions: OQ-16.2 (settled, owner decision 12)
- Decisions: OQ-16.3 (settled, owner decision 12)
- Decisions: OQ-18.1 (settled, owner decision 12)
- Decisions: OQ-18.3 (settled, owner decision 12)
- Decisions: OQ-20.3 (settled, owner decision 12)
- Status: done

### M0.4 T-docs-0c: Spec amendments, superseded banners, D-2 links and the history row

- Intent: make the spec of record agree with the design without moving any line the design cites
  (OQ-25.1 (a)), replace the owner's interim banners with DT-25's wording, and repoint the three links to
  the deleted P3 files outside `design/roadmap.html` at the pinned commit `f1c44e3` (the roadmap's two
  were pinned at planning time and arrive with M0.1).
- Delete: `docs/getting-started/repository-layout.md:7-8` (the two `P3_*.md` tree lines, D-2).
- Create: none.
- Modify:
  - `RAW_LAKE_SPEC.md`: appends "## Design amendments (2026-10-23)" after "Owner decisions (2026-10-23)",
    with DT-25's opening sentence and the A-1 … A-30 table of "DT-25 spec amendments" copied verbatim;
    every line above the new heading stays byte-identical.
  - `RAW_STORAGE_DESIGN.md`: the owner's interim `> **Superseded 2026-10-23** …` line is replaced by
    DT-25's banner for this file (line 3, above "Status: Design — not implemented …").
  - `RAW_STORAGE_IMPLEMENTATION_PLAN.md`: the owner's interim line and "Status: Milestone 0 done;
    Milestones 1+ pending." are replaced by DT-25's single status banner for this file. Nothing else in
    either file changes.
  - The D-2 table of "DT-25 superseded banners and the D-2 links": `design/layer-raw.html:694` (both P3
    links → `PIN/…`; `design/roadmap.html:376`'s two links are already `PIN/…` in M0.1's commit, so this
    task does not edit `design/roadmap.html` and only verifies them), `design/catalog-search.html:494`
    (`PIN/P3_DESIGN.md`), `docs/history.md:112-116` (the sentence rewritten and the "Archived plans" row
    `| Integrity services | [P3 design](PIN/P3_DESIGN.md), [P3 execution plan](PIN/P3_IMPLEMENTATION_PLAN.md) |`),
    where `PIN` is `https://github.com/karthedew/huron/blob/f1c44e3d56b10806c05373fce5b51c7a44abf146`.
  - `docs/getting-started/repository-layout.md`: the root tree gains `RAW_LAKE_SPEC.md` (spec of record),
    `RAW_LAKE_DESIGN.md`, `RAW_LAKE_IMPLEMENTATION_PLAN.md`, then `RAW_STORAGE_DESIGN.md` and
    `RAW_STORAGE_IMPLEMENTATION_PLAN.md` ("superseded, kept as history") (DT-26 developer-docs row,
    T-docs-0).
- Design: "DT-25 design: …" → "DT-25 decisions" (D-2, Owner decision 9 and D-8, Spec amendments), "DT-25
  spec amendments (`RAW_LAKE_SPEC.md`, new final section)", "DT-25 superseded banners and the D-2 links",
  "DT-25 interfaces and contracts" (Spec amendments); "DT-26 design: …" → "DT-26 developer docs, README
  and history" (`repository-layout.md` rows marked T-docs-0); OQ register "DT-25 design" (OQ-25.1).
- Verification:
  - `git diff --check` prints nothing; `make docs` exits 0.
  - `git diff HEAD~1 -- RAW_LAKE_SPEC.md | rg '^-[^-]'` prints nothing (append only), and
    `rg -c '^\| A-[0-9]+ \|' RAW_LAKE_SPEC.md` reports 30.
  - `rg -n '\.\./P3_|── P3_' design docs` prints nothing;
    `rg -o 'f1c44e3d56b10806c05373fce5b51c7a44abf146/P3_[A-Z_]+\.md' design/roadmap.html design/layer-raw.html design/catalog-search.html docs/history.md`
    lists both P3 targets for `roadmap.html`, `layer-raw.html` and `history.md`, and `P3_DESIGN.md` for
    `catalog-search.html`; `git diff --quiet HEAD~1 HEAD -- design/roadmap.html` succeeds (M0.1 carried
    the roadmap's two links).
  - `rg -n 'Milestones 1\+ pending' RAW_STORAGE_IMPLEMENTATION_PLAN.md` prints nothing;
    `git diff -U0 HEAD~1 -- RAW_STORAGE_DESIGN.md | rg -c '^@@'` reports 1, and
    `git diff -U0 HEAD~1 -- RAW_STORAGE_IMPLEMENTATION_PLAN.md | rg -c '^@@'` reports 1 (one changed region
    per file).
  - `git cat-file -e f1c44e3:P3_DESIGN.md && git cat-file -e f1c44e3:P3_IMPLEMENTATION_PLAN.md` succeeds
    (the pin resolves).
- Dependencies: M0.1.
- Decisions: OQ-25.1 (settled, owner decision 12)
- Decisions: OQ-1.2 (settled, owner decision 12)
- Decisions: OQ-4.1 (settled, owner decision 12)
- Decisions: OQ-4.2 (settled, owner decision 12)
- Decisions: OQ-5.2 (settled, owner decision 12)
- Decisions: OQ-8.1 (settled, owner decision 12)
- Decisions: OQ-8.2 (settled, owner decision 12)
- Decisions: OQ-8.3 (settled, owner decision 12)
- Decisions: OQ-9.1 (settled, owner decision 12)
- Decisions: OQ-13.1 (settled, owner decision 12)
- Decisions: OQ-13.2 (settled, owner decision 12)
- Decisions: OQ-13.3 (settled, owner decision 12)
- Decisions: OQ-15.1 (settled, owner decision 12)
- Decisions: OQ-16.1 (settled, owner decision 12)
- Decisions: OQ-16.2 (settled, owner decision 12)
- Decisions: OQ-16.3 (settled, owner decision 12)
- Decisions: OQ-20.2 (settled, owner decision 12)
- Decisions: OQ-20.3 (settled, owner decision 12)
- Status: done

### M0.5 T-docs-0d: DT-26's constraint lines on the design record and the T-docs-0 closing check

- Intent: carry the design-record lines that state constraints (DT-26 "T-docs-0" cells) so no lake task is
  reviewed against a page that forbids it: the `catalog-search.html` §1 GIN lift, the `rbac.html` §4
  overwrite line, the Bronze and Silver lineage pins, the roadmap's lineage rows (its RL row arrived with
  M0.1 and is only verified here), and the five temporary status lines; then run the combined T-docs-0
  closing check.
- Delete: none.
- Create: none.
- Modify:
  - `design/catalog-search.html` §1: the one rule replaced by DT-26's bold T-docs-0 line ("PostgreSQL holds
    no metadata mirror and no text search, except the lake: …").
  - `design/rbac.html` §4 (`:283`, `:439`): the "Overwrite committed files" cell becomes DT-26's bold
    T-docs-0 line; the rest of the Raw matrix is DT-4's (M3/M7).
  - `design/layer-bronze.html` §1–§2 (`:93-115`) and `:135`, `:204`, `:220`, `:259`, `:288-315`: DT-26's
    lineage-pin wording and the listed replacements (`build/{run_id}`, `raw_inputs: [RawPin…]`, no
    `raw/{revision_number}` tag, explicit build request, the corrections sentence).
  - `design/layer-silver.html` `:229-233`, `:294` (Raw-pin wording) and `:247` (`layer-raw.html#retention`
    → `layer-raw.html#recovery`; the target id arrives with M16's `layer-raw.html` §9, DT-26 "broken
    links").
  - `design/roadmap.html`: the "RL: Raw lake" phase row after "API tier clean sweep" (status `todo`, its
    six step tags `todo`, the step/gate table of "DT-26 roadmap rows") is already in place from M0.1's
    commit; this task verifies it and does not write it again. It edits only P5's M1.1 rationale
    (`:404-406` at `fa51f46`), which becomes the "Retired 2026-10-21: …" sentence (the rest of P5 is
    T-docs-Z's), and P9's gate (`:454-462`) and milestones 9–10 (`:619-646`), which take their Raw-pin
    wording. Line numbers are at `fa51f46`; the RL row shifts everything after `:274` by its own length.
  - The five status lines: `design/layer-raw.html`, `design/index.html`, `design/architecture.html`,
    `design/workflows.html` and `design/core-map.html` each gain, under the title, "Raw sections describe
    the engine being replaced by the Raw lake (`RAW_LAKE_DESIGN.md`)." (DT-26 "design record pages:
    overview, client, derived-layer pages and atlases"; M1.3 changes `layer-raw.html`'s line).
- Design: "DT-26 design: Design record, roadmap and operator documentation" → "DT-26 decisions" (Landing
  rule, "T-docs-0 carries two DT-26 lines"), "DT-26 design record pages: the Raw-facing six" (rows marked
  T-docs-0), "DT-26 design record pages: overview, client, derived-layer pages and atlases" (status line;
  `layer-bronze`, `layer-silver` rows), "DT-26 roadmap rows (`design/roadmap.html`)" (RL row; P5 M1.1
  sentence, P9, milestones 9–10), "DT-26 broken links and their fixes" (`layer-silver.html:247`), "DT-26
  handoffs" (Given → Plan); "DT-25 design: …" → "DT-25 `AGENTS.md`: sections replaced" (G-21 paragraph
  after the table), "DT-25 interfaces and contracts" (Closing check of T-docs-0).
- Verification:
  - `git diff --check` prints nothing; `make docs` exits 0.
  - DT-25's closing check, run over the state M0.2–M0.5 leave, prints nothing for every line except the
    first, whose `25 GiB` alternative still matches `AGENTS.md`'s acceptance comment until M1.4:
    `rg -n -i 'raw revision|verified payload|removal intent|pending removal|git-like|dataset\.upload|0010_independent_raw' AGENTS.md CONTEXT.md`;
    `rg -n '^\s+(catalog|raw)/\s|`(catalog|raw)`' AGENTS.md`; `rg -n '\.\./P3_|── P3_' design docs`;
    `rg -n 'Milestones 1\+ pending' RAW_STORAGE_IMPLEMENTATION_PLAN.md`; `ls docs/adr | wc -l | rg -v '^ *7$'`.
  - `rg -c 'describe the engine being replaced' design/layer-raw.html design/index.html design/architecture.html design/workflows.html design/core-map.html`
    reports 1 for each file.
  - `rg -n -i 'raw revision|revision_id|raw/\{revision|source_revision_id' design/layer-bronze.html design/layer-silver.html`
    prints nothing; `rg -n 'collections_metadata_gin' design/catalog-search.html` prints the §1 line;
    `rg -n 'overwrite: true' design/rbac.html` prints the §4 line; `rg -n 'RL: Raw lake' design/roadmap.html`
    prints exactly one row, and
    `rg -c 'id="rl-step-[1-6]"><strong>Step [1-6] — [^<]+</strong> <span class="tag">todo</span>' design/roadmap.html`
    reports 6 (the row M0.1 committed, unchanged by this task:
    `git diff HEAD~1 HEAD -- design/roadmap.html | rg '^[-+].*(RL: Raw lake|rl-step-)'` prints nothing).
- Dependencies: M0.2, M0.3, M0.4.
- Decisions: OQ-1.2 (settled, owner decision 12)
- Decisions: OQ-18.3 (settled, owner decision 12)
- Status: done

## Milestone 1 — Legacy Raw deletion

Delete the legacy Raw engine and everything that exists only for it, in DT-2's order and one task per
step: the web Raw surface (D2-0) and its vocabulary rename (D2-0b), the Raw bridge (D2-1), the Raw engine
and its `/api/v1` surface (D2-2), the reduction of `rawstore` to the hierarchy's generation store (D2-3),
Owner decision 10's Python password login, cookie sessions and server code flow with the whole `/auth`
router (D2-4; owner decision 11, B-13), and migration
`0014_retire_legacy_raw` (D2-5). Every step runs the plan-wide gate, its closing `rg` checks and, for the
Python steps D2-1 … D2-5, DT-2's coverage-floor procedure exactly; each lands the DT-26 page lines that
DT-2 and DT-3 own in the same commit as the code that makes them true. Two ordering gaps in DT-2's step
lists are resolved here, so that each step's closing check holds at its own commit: `capabilities.Storage`
loses its `RawStore` base when `core/raw/ports.py` leaves, so the `ApiRuntime.raw_store` →
`generations: GenerationStorage` change and the probe renames move from D2-3 into D2-2; and
`huron/schema/storage.py` keeps its last importer (`rawstore`'s `write_part`) until D2-3, so its deletion
and the `huron\.schema\.storage`, `PartLengthMismatch` and `completion_reserve` terms of D2-2's closing
check move to D2-3. Afterwards the legacy `/api/v1` router serves 38 operations, `lint-imports` keeps 14
contracts, `0014` is head, and the web calls no Python service.

### M1.1 D2-0: Web Raw surface

- Intent: delete the whole web Raw surface (the `/ingestion` wizard and BFF proxy, the managed Raw detail,
  Raw registration and the Raw server modules) in one step ahead of the server half, and make every
  Polaris generic table render as Generic permanently, while the web's own sessions, accounts,
  organizations and non-Raw Polaris pages stay byte-for-byte unchanged.
- Delete (orchestrator `git rm` before the pass; read them with `git show fa51f46:web/<path>`): the 28
  whole files of "DT-3 target design: step D2-0" → "Whole files (28; R3-2)" (the `src/routes/ingestion/`
  tree, `src/lib/design/components/ingestion/`, `src/lib/ingestion/*`,
  `src/lib/api/raw-ingestion-{client,client.test,types}.ts`, `src/lib/server/raw-*.ts` with their tests,
  `src/lib/server/polaris-raw-actions.ts`, `e2e/ingestion.test.ts`, `scripts/start.mjs` and so
  `web/scripts/`), and the `/queue` ingest-job page `src/routes/queue/` (`+page.svelte`, `+page.ts`)
  (owner decision 11, B-25).
- Rename (orchestrator `git mv` before the pass): `web/src/lib/design/components/polaris/RawDatasetDetail.svelte`
  → `web/src/lib/design/components/polaris/GenericTableDetail.svelte`.
- Modify (paths under `web/`): every partial source edit of DT-3's "Partial edits, source (by symbol)"
  (`src/hooks.server.ts`, `src/routes/+layout.svelte`, `src/routes/browse/+page.server.ts`,
  `src/routes/browse/+page.svelte`, `GenericTableDetail.svelte` to its contract,
  `src/lib/server/{polaris-actions,polaris-raw,polaris-client,polaris-browse}.ts`,
  `src/lib/api/{polaris-raw-types,polaris-browse-types,catalog-datasets,client,types}.ts`,
  `NamespaceContents.svelte`, the three copy lines in `AuthShell.svelte`,
  `src/routes/admin/+page.svelte` and `src/routes/+page.svelte`, `package.json` (`hash-wasm` removed with
  `npm uninstall hash-wasm`, which rewrites `package-lock.json`; `"start"` →
  `node --env-file-if-exists=.env build/index.js`), `.env.example`, `playwright.config.ts`); every
  partial test edit of DT-3's "Partial edits, tests" (`src/lib/server/polaris-raw.test.ts`,
  `src/lib/api/catalog-datasets.test.ts`, `src/lib/server/polaris-browse.test.ts`,
  `src/lib/server/polaris-dataset-governance.test.ts`, `e2e/dataset-types.test.ts`,
  `e2e/organizations.test.ts`, `e2e/polaris-mock.mjs`, `e2e/smoke.test.ts`); DT-3's "Docs" edits to
  `web/README.md` (`:5`, `:67`, `:79-80`, `:97`, `:152-154`, `:178-187`, `:189-195`, `:219-223`; DT-3's
  paths are relative to `web/`) and `web/src/lib/api/README.md` (`:19-26`, `:47-49`); the repository's
  root `README.md` is not touched in M1.1. `src/lib/reserved-slugs.ts` loses
  `'ingestion'` and `'queue'` (`src/lib/reserved-slugs.test.ts` stays unchanged and requires one
  reservation per route directory); `e2e/smoke.test.ts` loses only the Ingestion nav assertion, and no
  `/ingestion` entry is added to its obsolete-routes test, whose existing `/queue` entry stays because it
  exercises the hook's unchanged catch-all redirect (owner decision 11, B-24, B-25). The `/queue` page's
  data path leaves with it (owner decision 11, B-25): `src/lib/api/client.ts` loses `listIngestJobs` and
  its `IngestJob` import, `src/lib/api/fixtures.ts` loses `ingestJobs` and its `IngestJob` import, and
  `src/lib/api/types.ts` loses `interface IngestJob`. `e2e/polaris-mock.mjs`
  reshapes `source_files` into an ordinary generic table: format `parquet`, properties
  `{ 'huron.layer': 'bronze' }`, no `huron.dataset-type`; every `polaris-raw.test.ts` input is non-Raw
  (owner decision 11, B-6).
- Design record (DT-26 rows landing with DT-3 D2-0): `design/frontend.html` §2–§3 per the DT-3 decisions
  row (the `:87`, `:94`, `:100`, `:105` text removed, generic tables render as Generic) plus DT-26's §3
  record ("A later Raw browser reads the lake API (`GET /api/v1/catalogs…`) with a Huron JWT; no BFF
  delegation is reintroduced."); `design/polaris.html` "Managed Raw uploads" → "Raw stays outside
  Polaris" with id `raw-outside-polaris`, its inbound links updated (owner decision 11, B-39), and no
  operator note about generic tables the old path left in Polaris (owner decision 11, B-6);
  `design/roadmap.html` UI-α/UI-β and P10 rows (both `partial`)
  per "DT-26 roadmap rows".
- Design: "DT-3 design: Web Raw surface deletion" (all: decisions, "DT-3 target design: step D2-0", "DT-3
  interfaces and contracts", deletions); "DT-2 design: …" → "DT-2 deletion steps" (D2-0); "DT-26 design:
  …" → "DT-26 design record pages: the Raw-facing six" (`polaris.html`), "… overview, client,
  derived-layer pages and atlases" (`frontend.html`), "DT-26 roadmap rows" (UI-α/β, P10).
- Skills: `svelte-code-writer`, `svelte-core-bestpractices`.
- Verification:
  - The plan-wide gate with its `web/` addition: from `web/`, `npx @sveltejs/mcp svelte-autofixer <file>
    --svelte-version 5` on each of the seven changed `.svelte` files DT-3's "Gate" names (its eighth,
    `queue/+page.svelte`, is deleted; owner decision 11, B-25) until no
    applicable finding remains, `npx prettier --write` on the changed files, then `npm run check`,
    `npm test` (19 files, 215 tests), `npm run lint`, `npm run build` and `npm run test:e2e` (30
    top-level tests: `rg -c "^test\(" e2e/*.ts` sums to 30). No Python file changes, so `make lint`, the
    three pytest tiers and the Python floor are unchanged and green; `make docs` exits 0.
  - DT-3's closing checks, run from `web/`, each print nothing unless stated:
    `rg -n -i "raw-web|rawBridge|raw_bridge|HURON_RAW|raw-ingestion|rawInspection|RawInspection|isRaw|registerRawTable|Raw files|hash-wasm|BODY_SIZE_LIMIT|raw_web_support|E2E_RAW" . --glob '!node_modules' --glob '!build' --glob '!.svelte-kit'`
    prints only lines naming `PolarisRawTable` or `PolarisRawTableIdentifier` (its case-insensitive `isRaw`
    matches "Polar**isRaw**Table"; M1.2 renames both, after which it prints nothing) and
    `rg -n '\bisRaw\b' . --glob '!node_modules' --glob '!build' --glob '!.svelte-kit'` prints nothing;
    `rg -n "ingestion" src e2e` prints nothing (owner decision 11, B-24);
    `test ! -e src/routes/ingestion -a ! -e src/lib/ingestion -a ! -e scripts`; `test ! -e src/routes/queue`
    and `rg -n 'listIngestJobs|ingestJobs|IngestJob\b' src e2e` prints nothing (owner decision 11, B-25);
    DT-2's D2-0 check `rg -n "raw-web|rawBridge|raw_bridge" src e2e`; from the repository root,
    `rg -n 'raw-publication' design docs --glob '!*-uml.*'` prints nothing (`layer-raw.html:93` links
    `polaris.html#raw-outside-polaris`) (owner decision 11, B-39).
  - The untouched-surface invariant: `git diff --stat fa51f46 -- <each path of DT-3's "Untouched-surface
    invariant" lists>` prints nothing, including `DatasetDetail.svelte` and `NamespaceExplorer.svelte`
    (D2-0b renames inside them next); `npm run test:e2e` passes `smoke`, `polaris` and the non-Raw
    `organizations` and `dataset-types` tests with their bodies unchanged except DT-3's named edits.
  - `e2e/dataset-types.test.ts`'s first test pins the Generic rule: `source_files` (the reshaped `parquet`
    table) and `external_delta`, two non-Raw generic tables, are both labelled Generic, both match the
    `generic` filter, and the type filter has no `raw` option (owner decision 11, B-6).
- Dependencies: M0.5.
- Review correction (owner approved): `web/src/routes/+layout.svelte` also replaces the desktop
  footer's "Raw · Iceberg · Icechunk" with "Generic · Iceberg · Icechunk". Verification attempt 1
  found this omitted copy line; its interrupted browser failures did not reproduce in the unchanged
  full rerun (36 passed). Verification attempt 2 passed with the footer correction.
- Status: done (verification passed on attempt 2, 2026-10-24)

### M1.2 D2-0b: Generic-table vocabulary rename

- Intent: remove the last place where "raw" names something other than the lake: the web's Polaris
  generic-table names, transport token and URL parameters become `generic`, behaviour unchanged, with no
  alias for old `format=raw` URLs. Its own commit, so D2-0 stays a deletion review.
- Delete: none.
- Rename (orchestrator `git mv`): `web/src/lib/api/polaris-raw-types.ts` → `polaris-generic-types.ts`;
  `web/src/lib/server/polaris-raw.ts` → `polaris-generic.ts`; `web/src/lib/server/polaris-raw.test.ts`
  → `polaris-generic.test.ts`.
- Modify: every name in the table of "DT-3 target design: step D2-0b" (OQ-3.1 decided (b); owner
  decision 11, B-26)
  (`PolarisGenericTableIdentifier`, `PolarisGenericTable`, `'generic'` for the transport token and the
  `PolarisTableFormat` member in `polaris-governance-types.ts`, `genericTable()`,
  `PolarisClient.genericTables()`/`.genericTable()`, the browse fields and branch tokens, the error key,
  the URL parameters `format=generic` and `genericPageToken`) in exactly the files
  `rg -l "PolarisRawTable|rawTables?\b|rawPageToken|loadedRawTable|format === 'raw'|'raw'" src e2e`
  lists after M1.1, minus DT-3's named exceptions (the medallion layer `raw` in `LayerBadges.svelte`,
  `types.ts:9` (`Layer`) and `fixtures.ts:142` (the `{ value: 'raw', count: 2 }` facet), line numbers at
  `fa51f46`; `types.ts:94` and `fixtures.ts:101` left with `IngestJob` in M1.1, and no Polaris fixture
  stores `format: 'raw'` after M1.1)
  (owner decision 11, B-6); `datasetTypeLabel` maps `'generic'` to
  `'Generic'`, and `NamespaceContents.svelte`'s type mapping becomes `dataset.format ?? 'icechunk'`.
  `DatasetDetail.svelte` (`rawPageToken` at `:141`) and `NamespaceExplorer.svelte` (`:235-236`) take the
  rename only.
- Design: "DT-3 design: …" → "DT-3 target design: step D2-0b", "DT-3 interfaces and contracts" (every
  contract holds with the new names); OQ register "DT-3 design" (OQ-3.1, decided (b)).
- Skills: `svelte-code-writer`, `svelte-core-bestpractices`.
- Verification:
  - The plan-wide `web/` gate: the autofixer on `NamespaceContents.svelte`, `NamespaceExplorer.svelte`,
    `DatasetDetail.svelte`, `GenericTableDetail.svelte` and `src/routes/browse/+page.svelte`; prettier;
    `npm run check`, `npm test` (19 files, 215 tests: the renamed `polaris-generic.test.ts` keeps its
    count), `npm run lint`, `npm run build`, `npm run test:e2e`. No Python file changes.
  - DT-3's closing check from `web/`:
    `rg -n "PolarisRawTable|rawTables?\b|RawPageToken|rawPageToken|loadedRawTable|format=raw|format === 'raw'" src e2e`
    prints nothing, and M1.1's case-insensitive DT-3 check (`rg -n -i "raw-web|…|isRaw|…|E2E_RAW" .` with its
    three globs) now prints nothing.
  - A browse URL with `format=raw` answers 400 "Choose a supported table format." like any unknown format
    (`polaris-browse.ts:33-35`): one assertion inside an existing `polaris-browse.test.ts` test pins it,
    so the file and test counts stay 19 and 215. The assertion builds its URL with
    `url.searchParams.set('format', 'raw')`, so no literal `format=raw` remains under `src`.
  - `git diff --stat HEAD~1 -- <DT-3's untouched-surface paths other than DatasetDetail.svelte and
    NamespaceExplorer.svelte>` prints nothing.
- Dependencies: M1.1.
- Status: done (verification passed on attempt 2, 2026-10-24)

### M1.3 D2-1: The Raw bridge and the launcher's Raw half

- Intent: remove the server half of the Raw bridge now that no web client calls it (L-22 (a)): the
  `/api/raw-web` router, its HS256 delegation, the Raw publication store and the external-dataset port,
  their settings and wiring, and the dev launcher's Python API, Raw database and bridge secret, together
  with `raw_environment`, which calls `bridge_secret` and so leaves in the same change (DT-22 "Launcher").
  This is DT-2's first deletion step, so `layer-raw.html` loses its engine sections here.
- Delete (orchestrator `git rm`): the eleven whole files of DT-2's D2-1 (`routes/raw_web.py`,
  `applications/api/raw_web.py`, `core/raw/web.py`, `core/raw/web_ports.py`, `core/metastore/raw_web.py`,
  `core/catalog/external.py`, `core/security/raw_delegation.py`, `tests/unit/test_raw_web.py`,
  `tests/raw_web_client.py`, `tests/raw_web_support.py`, `tests/integration/test_raw_web_postgres.py`).
- Modify:
  - `src/huron/applications/api/app.py`: the `raw_web_router` import and include (`:358-361`), the
    `PostgresRawWebStore` import and the `raw_web=` argument of `_build_runtime`.
  - `src/huron/applications/api/runtime.py`: `ApiStores.raw_web`, `ApiRuntime.raw_web` and the
    `RawWebPersistence` import. `src/huron/applications/api/capabilities.py`: `RawWebPersistence` and its
    `ExternalDatasetStore`/`RawPublicationStore` imports.
  - `src/huron/applications/api/settings.py`: `raw_bridge_secret` and its validator (`:90,134-148`).
  - `src/huron/applications/api/problems.py`: any code whose last raiser left (none of the deleted modules
    declares a code; `test_error_contract.py` decides, and a row it reports as "live with no raise site"
    leaves `design/api.html` §7 with its class and its `ERROR_CODES` entry) (owner decision 11, B-15).
  - `src/huron/core/raw/__init__.py` and `src/huron/core/catalog/__init__.py`: re-exports of the deleted
    names, if any (DT-2 lists both; `rg` at `fa51f46` finds none, so normally nothing changes here).
  - `scripts/polaris-dev.sh`: `raw_database` (`:13`), the Raw API launch and migration (`:102-113`),
    `owns_raw_database`/`start_raw_database` (`:126-150`), the `raw-api` and Raw-database lines of
    the status and stop commands (`:164,166,179-191`), and the status command's
    `Committed Raw revisions: …/.local/huron/raw` line (`:172`; owner decision 11).
    `scripts/polaris_dev.py`: `bridge_secret` and the
    `raw-postgres.env` write (`:71-92`), `raw_environment` (`:94-113`), the `web` branch's copy of the
    three `HURON_RAW_*` values (`:183-185`), the `raw-api` branch (`:186-188`) and the `raw-command` verb
    (`:213-219`). The rest of the Polaris launcher stays.
  - Tests: `tests/unit/test_api_settings.py` (bridge-secret cases out); `tests/unit/test_error_contract.py`
    with `design/api.html` §7 rows as above; `tests/unit/test_api_router_composition.py`: the tag
    assertion drops `raw-web` (15 tags) and its test is renamed
    `test_the_openapi_document_carries_the_resource_grained_tags` (no count in the name, so later steps
    edit only the set), and two new tests pin DT-2's surviving-surface invariant:
    `test_the_legacy_v1_router_serves_exactly_its_operations` (52 operations at this step) and
    `test_every_legacy_v1_operation_refuses_an_anonymous_request` (each `/api/v1` operation, path
    parameters filled with fresh UUIDs, answers 401 `application/problem+json` without a credential), plus
    `test_the_retired_bridge_prefix_has_no_route` (`GET /api/raw-web/…` answers 404; the name carries no
    `raw_web`, so DT-2's closing check below and its M19.4 re-run stay clean).
  - Design record (DT-26 rows landing with DT-2 D2-1): `design/layer-raw.html` as DT-26 sequences it:
    §1–§11 are removed (the kept ids `layout` and `commit` return with the new §2 and §5 in M11 and M13;
    their inbound links stay as written), the new lede, §11 Polaris
    (`polaris`, linking `polaris.html#raw-outside-polaris` and ADR 0004; owner decision 11, B-39) and §12
    History (`history`, with the
    two P3 links pinned at `f1c44e3` moved here from `:694`) are written, and the M0.5 status line becomes
    "Target design; sections land with their tasks in `RAW_LAKE_IMPLEMENTATION_PLAN.md`.";
    `design/catalog-search.html:495` `layer-raw.html#p3-integrity` → `layer-raw.html#history`.
- Coverage-floor procedure (DT-2 "DT-2 interfaces and contracts" → "Coverage floor procedure"; the same
  four steps apply in M1.4–M1.7): (1) at the task's base, before the orchestrator's `git rm`, the verifier
  runs `uv run pytest --cov=src/huron --cov-report=json:<scratch>/before.json` and
  `uv run pytest -m "unit or contract" --cov=src/huron --cov-report=json:<scratch>/before-contract.json --cov-fail-under=0`;
  (2) after the pass, the same two runs into `after.json` and `after-contract.json`; (3) pass conditions:
  no file present in both reports gains a line in `missing_lines`, every modified file is at 100 %
  (PostgreSQL adapter modules from the contract run), and the drop in covered statements equals the
  covered statements of the deleted files and symbols as computed from `before.json`; (4) then
  `fail_under = floor(10000 × covered / statements) / 100` of `after.json`'s totals is written to
  `pyproject.toml` `[tool.coverage.report]`, and the before/after covered and total counts and the unit
  test-count change go to "Execution notes".
- Design: "DT-2 design: Python legacy Raw deletion and the drop migration" → "DT-2 decisions" (L-22,
  Order with DT-3), "DT-2 deletion steps" (D2-1), "DT-2 interfaces and contracts" (Coverage floor
  procedure, Surviving-surface invariant); "DT-22 design: …" → "DT-22 decisions" (Launcher), "DT-22
  deletions" (`scripts/polaris_dev.py`); "DT-26 design: …" → "DT-26 design record pages: the Raw-facing
  six" (`layer-raw.html` sequence, §11, §12), "DT-26 broken links and their fixes" (`catalog-search.html:495`,
  `layer-raw.html:694`); "DT-18 design: …" → "DT-18 deletions" (the `raw-web` tag entry).
- Skills: `fastapi` (`applications/api`); `oop-design` (`core/`).
- Verification:
  - The plan-wide gate; `uv run lint-imports` keeps 16 contracts; `make docs` exits 0;
    `bash -n scripts/polaris-dev.sh`; `uv run python -m py_compile scripts/polaris_dev.py`.
  - DT-2's closing check `rg -n "raw_web|RawWeb|raw_delegation|raw_bridge|ExternalDataset|RawPublication" src tests scripts`
    prints only `tests/contract/test_catalog_store.py`'s three lines naming the Alembic revision id
    `0012_raw_web_catalogs` (`:1980`, `:2006`, `:2050`), a temporary exception that lasts until M1.7
    deletes those tests (owner decision 11, B-18);
    `rg -n "raw_environment|bridge_secret|raw-command|raw-api|raw_database|HURON_RAW_|Committed Raw revisions" scripts`
    prints nothing.
  - The three new router tests pass; `uv run pytest tests/unit/test_error_contract.py` passes with the §7
    table as edited.
  - `rg -n 'id="(ingest|contracts|generations|flow-new-revision|flow-concurrent-writers|upload-modes|retention|sweeper|p3-integrity)"' design/layer-raw.html`
    prints nothing; `rg -n 'id="(polaris|history)"' design/layer-raw.html` prints both sections;
    `rg -n 'Target design; sections land' design/layer-raw.html` prints the status line.
  - The coverage-floor procedure's three pass conditions hold and the new `fail_under` is recorded.
- Dependencies: M1.2.
- Status: done (verification passed on attempt 1, 2026-10-24)

### M1.4 D2-2: The Raw engine, its `/api/v1` surface and the nightly workflow

- Intent: delete `huron.core.raw`, the Raw `/api/v1` operations, their guards, dependencies, adapters,
  documents, settings and tests in one step (nothing coexists any more), drop the two `raw` import-linter
  contracts, and replace the nightly acceptance workflow, whose only test leaves here, by `nightly.yml`
  holding DT-23's `unit-macos` job until M15 adds `nfs-large`, runnable on the pull request through its
  `nightly` label (plan-wide "Merge" rule). The largest task of the milestone; almost
  all of it is orchestrator deletions.
- Pre-step (orchestrator, before the `git rm`): re-count the Raw test files at the task's base with
  `rg -l 'huron\.core\.raw\b|huron\.applications\.api\.(expiry|streams)|ingest_client|IngestSession|RawRuntime|RevisionRecord' tests scripts`
  and reconcile the result with DT-2's D2-2 lists (whole-file and partial); any file the design does not
  list is recorded under "Execution notes" and handled as a partial edit, never silently deleted.
- Delete (orchestrator `git rm`): DT-2's D2-2 whole files: `src/huron/core/raw/` (package and `_impl`),
  `src/huron/core/metastore/ingest.py`, `src/huron/applications/api/{expiry,streams}.py`,
  `routes/v1/endpoints/{revisions,ingest_sessions,tus}.py`, `routes/v1/schema/{revisions,ingest_sessions,tus}.py`,
  `src/huron/schema/documents/{manifest-v1,committed-v1,committed-v2,revision-index-v1,metadata-v1}.json`,
  `scripts/test.py`; and the 15 test files
  `tests/unit/test_api_{revisions,raw_revisions,ingest_sessions,ingest_expiry,ingest_crash_matrix,completion_capacity,expiry}.py`,
  `tests/unit/test_catalog_ingest.py`, `tests/unit/test_schema_{committed,revision_index}.py`,
  `tests/ingest_client.py`, `tests/acceptance/test_raw_ingest_gate.py`,
  `tests/integration/test_verified_raw_ingest.py`, `tests/contract/test_{commit_intents,ingest_process_death}.py`.
  `src/huron/schema/storage.py` stays until M1.5 (its last importer is `rawstore`'s `write_part`).
- Rename (orchestrator `git mv`): `.github/workflows/acceptance.yml` → `.github/workflows/nightly.yml`.
- Modify:
  - Every partial source edit of DT-2's D2-2 "Partial, source" (`routes/v1/__init__.py` the six Raw
    `include_router` lines; `authorization/guards.py` the Raw guards `:196-479`; `dependencies.py`;
    `runtime.py` `ApiRuntime.raw`; `app.py` the expiry sweep and Raw wiring, and `PosixRawStore` built
    with its constructor defaults now that the two completion settings leave; `capabilities.py`
    `RawPersistence`, `HierarchyWriter` and `RawStore` leave `HierarchyStore`'s and `Mutation`'s bases;
    `settings.py` the four ingest/completion fields; `problems.py` the `RAW_ERROR_CODES` import and entry;
    `core/metastore/hierarchy.py` and `core/metastore/rows.py` the ingest writer bases and record
    builders, and in `hierarchy.py` both `insert_outbox_event` methods (`:262`, `:945`),
    `TransactionBuffer.outbox` (`:98`) and the in-memory `_outbox` and its flush (`:504`, `:544`), because
    Raw ingest is the outbox's only writer (owner decision 11, B-2); `core/catalog/ports.py` and
    `core/catalog/paths.py` the Raw members whose last caller left;
    `scripts/seed_catalog_types.py` the `ace_source_files` registration; `src/huron/schema/__init__.py`
    docstrings name `generation-v1.json` instead of `manifest-v1.json`).
  - `src/huron/core/catalog/errors.py`: `ContractMismatch`, any re-export of it and its `ERROR_CODES`
    entry, because its only raisers are in `core/raw/documents.py` (owner decision 11, B-15).
    `src/huron/core/foundation/names.py`: `"ingestion"` and `"queue"` leave `RESERVED_ROOT_SLUGS`
    (`:21`, `:32`), the server half of M1.1's web edit (owner decision 11, B-24, B-25).
  - `src/huron/core/foundation/retry.py`: `Replay.kind` loses `"ingest_session"`, `"ingest_commit"` and
    `"revision"`, whose writers leave with `core/raw`; the `Replay` docstring loses "unfinished ingest
    commits retain their reservation beyond TTL" and `RetryTransaction.claim`'s docstring its "except for
    unfinished ingest-commit reservations" clause ("DT-14 deletions"). With it, `core/metastore/hierarchy.py`
    drops DT-2's `ingest_commit` claim exemption and its docstring lines (in-memory `:135`, `:155`;
    PostgreSQL `:712`, `:742`), and `tests/unit/test_hierarchy_store_memory.py` loses
    `test_an_unfinished_commit_claim_cannot_expire_before_its_revision_receipt` (`:160-179`).
    `tests/unit/test_foundation_retry.py` asserts no `Replay.kind` and needs no change.
  - `src/huron/core/foundation/errors.py`: `PathRuleViolation.__init__` (`:89-101`, the code-override
    mode) is deleted in the same change as `core/raw/manifest.py`, its only user of that mode ("DT-8
    deletions", R8-4); the class keeps `code = "PATH_RULE_VIOLATION"` and `status_code = 400` and
    inherits `DomainError.__init__(detail, *, context=None)`, which the detail-only raise sites in
    `core/foundation/names.py` and `core/catalog/paths.py` already match. `tests/unit/test_catalog_errors.py`
    loses `test_path_rule_violation_carries_a_more_specific_code_with_a_path` (`:31-36`, the
    two-argument case); its detail-only test stays.
  - Moved here from D2-3 (`capabilities.Storage` subclasses `core.raw.ports.RawStore`, which leaves now):
    `capabilities.Storage` is deleted; `ApiRuntime.raw_store: Storage` → `generations: GenerationStorage`;
    `app.py` `_raw_store_probe`/`_raw_store_failure` → `_generation_store_probe`/`_generation_store_failure`
    typed `GenerationStorage` (the `TYPE_CHECKING` import of `huron.core.raw.ports.RawStore` leaves), and
    the `/readyz` check key `"raw_store"` → `"generations"`; `dependencies.py` and
    `tests/unit/test_api_app.py`'s readiness and lifespan cases follow.
  - `pyproject.toml`: the `core/raw/errors.py` per-file ignore; the contracts "raw uses catalog security
    foundation and schema only" and "raw implementations are private to their owner" deleted;
    `huron.core.raw` leaves contract 2's layers (`foundation:security:catalog:metastore:rawstore`), the
    forbidden lists of 4, 5, 6 and 9 and the sources of 10, 11 and 13; contract 8 is renamed "metastore
    uses catalog security and foundation only".
  - Tests: every partial test edit of DT-2's D2-2 "Partial, tests" (`tests/hierarchy_contract.py`
    scenarios 5 and 10–16; `tests/unit/support.py`; `tests/contract/test_hierarchy_store.py`;
    `tests/unit/test_{hierarchy_store_memory,stores_rows,stores_ports,authorization_guards,catalog_documents,catalog_paths,catalog_ports,catalog_properties,core_workflows,execution_model,domain_import_contracts,schema_loading}.py`),
    plus `tests/unit/test_authorization_credentials.py` (its `ApiRuntime` builds lose `raw=RawRuntime(…)`)
    and `tests/unit/test_error_contract.py:131` (the `huron.core.raw.manifest` import); in
    `test_domain_import_contracts.py` `raw` leaves `OWNERS`, `PRIVATE_OWNERS`, the edge table and the
    contract names, and its planted violations name surviving owners;
    `tests/unit/test_api_router_composition.py` expects 40 operations and 12 tags (`revisions`,
    `ingest-sessions`, `transfer` leave); `tests/unit/test_catalog_paths.py:150` drops `"ingestion"` from
    its parametrize list (owner decision 11, B-24); `tests/hierarchy_contract.py` and
    `tests/unit/test_hierarchy_store_memory.py` lose their `insert_outbox_event` and `_outbox` uses with the
    writer (owner decision 11, B-2).
  - `.github/workflows/nightly.yml`: `name: Nightly`, the `schedule` (`cron: "0 3 * * *"`) and
    `workflow_dispatch` triggers kept, plus `pull_request: {types: [labeled, synchronize]}` (GitHub starts
    `schedule` and `workflow_dispatch` only for workflows on the default branch, and this file exists only
    on `raw-storage` until the merge; plan-wide "Merge" rule), and exactly one job, DT-23's `unit-macos`
    (`runs-on: macos-latest`, `timeout-minutes: 20`, the job-level
    `if: github.event_name != 'pull_request' || contains(github.event.pull_request.labels.*.name, 'nightly')`,
    the pinned `actions/checkout@v7` and
    `astral-sh/setup-uv@20cfd1bf945f4377ade1205e4dbc17946fc9a30d # v10.0.1` steps,
    `uv sync --all-groups`, `uv run pytest -m unit --no-header -q`). The `acceptance` job goes: no
    `acceptance` test exists until M15, whose `nfs-large` job carries the same job-level `if`.
  - `design/api.html`: the §7 rows `EMPTY_REVISION`, `PATH_OUTSIDE_PAYLOAD`, `PATH_NOT_NFC`,
    `PATH_TOO_LONG`, `PATH_TRAVERSAL`, `PATH_CONTROL_CHARS`, `PATH_SEPARATOR`, `PATH_COLLISION`,
    `ILLEGAL_INGEST_TRANSITION`, `FILE_TOO_LARGE`, `TOO_MANY_FILES`, `REVISION_TOO_LARGE`,
    `MANIFEST_MISMATCH`, `INGEST_SESSION_EXPIRED`, `DATASET_LOCKED` leave with their classes;
    `CONTRACT_MISMATCH` leaves with `ContractMismatch`, whose only raisers are in
    `core/raw/documents.py` (owner decision 11, B-15);
    `#planned-p3-error-codes` and `#p3-read-admission` leave. (`api.html` §3 is replaced by DT-18's
    route table in M9.)
  - Design record and docs (DT-26 rows naming DT-2): `design/rbac.html` "P3 integrity authority
    (planned)" (`p3-maintenance`) removed; `design/roadmap.html` P3, Milestone 7 and Milestone 8 become
    `retired` with DT-26's one-paragraph texts (P3 keeps the 2026-10-15 paragraph and the pinned P3
    links; M8 keeps run 34177077449), and the tag sentence at `:148-149` gains the `retired` tag; its §1
    tree loses the `core/raw/` line (`:113` at `fa51f46`) and §5's step 2 (`:851`) loses
    `core/raw/paths.py` and `core/raw/manifest.py` (plan-wide "No backwards compatibility" rule);
    `docs/getting-started/local-development.md` "Running the API" loses the `HURON_COMPLETION_*` rows
    (`:162-163`, the two completion settings leave `settings.py` here), the `HURON_INGEST_SWEEP_*` rows and
    the upload-capacity paragraph; `docs/getting-started/testing.md` loses the 9 GiB acceptance
    description (`:83-108`) and `:73`'s "Raw upload" (DT-26 deletions; M15 writes the large-file gate's
    section), and the tier table's `acceptance` row (`:11`) has its "Needs" cell "≥ 25 GiB free disk"
    replaced by "—" (no acceptance test exists until M15, which rewrites the tier table from DT-23 with
    12 GiB); `docs/getting-started/repository-layout.md` loses the `core/raw/` tree line; `AGENTS.md`'s
    commands block loses the `make test-acceptance` line and its "25 GiB" comment, and the `Makefile`
    `test-acceptance` help loses "(needs ≥ 25 GiB free disk)", because the gate they describe is deleted
    (B-11 and DT-23's Makefile row write the 12 GiB lines in M15).
  - `scripts/duplication_baseline.json` (reviewed hand edit, after the code edits): deleting
    `core/metastore/ingest.py` and `core/raw/` leaves subset signatures of baseline clone groups, which
    `check_duplication._regressions` reports as new or grown. The implementer runs
    `uv run --locked python scripts/check_duplication.py src`; every reported group must be a baseline
    signature minus files this task deletes. The owner approved one additional, exact regrouping
    on 2026-10-24: the six unchanged `core/metastore/rbac.py` fragments from pre-task group 16
    (`hierarchy`/`ingest`/`rbac`, size 12) may form an `rbac.py`-only signature of size 6 after the
    Raw revision methods leave `hierarchy.py`. This exception requires fragment-hash proof and
    `rbac.py` byte identity with `1519c98`; it permits no other regrouping or clone growth. Each is
    added to `groups` with its scanned size, then
    `uv run --locked python scripts/check_duplication.py src --update-baseline` ratchets the baseline down
    to the scan (the groups naming deleted files leave). Any other new or grown group stops the task. Each
    added signature, the group it came from and the running total go under "Execution notes"; these
    deletion subsets and this one unchanged-fragment regrouping are exempt from the per-group cap.
- Design: "DT-2 design: …" → "DT-2 decisions" (Raw path rules and errors, Order with DT-1), "DT-2
  deletion steps" (D2-2), "DT-2 interfaces and contracts" (Coverage floor procedure, Surviving-surface
  invariant), "DT-2 deletions"; "DT-1 design: …" → "DT-1 import-linter contract set (diff against the
  sixteen)" (the two removals); "DT-23 design: …" → "DT-23 CI workflow job outlines" (`nightly.yml`
  `unit-macos`), "DT-23 deletions"; "DT-18 design: …" → "DT-18 deletions"; "DT-14 design: …" → "DT-14
  deletions" (`retry.py`); "DT-8 design: …" → "DT-8 deletions" (`PathRuleViolation.__init__`); "DT-26
  design: …" → "DT-26 roadmap rows" (tag vocabulary, P3, Milestones 7 and 8), "DT-26 developer docs,
  README and history" (`local-development.md` "Running the API"), "DT-26 deletions".
- Skills: `fastapi` (`applications/api`); `oop-design` (`core/`); `postgresql-table-design`
  (`core/metastore/hierarchy.py`, `rows.py`).
- Verification:
  - The plan-wide gate; `uv run lint-imports` reports "Contracts: 14 kept, 0 broken"; `make docs` exits 0;
    `uv run pytest tests/unit/test_error_contract.py` passes with code and rows leaving together;
    `uv run python -m py_compile scripts/seed_catalog_types.py` (its `scripts/test_catalog_types.py`
    needs `pyiceberg`, which the uv environment lacks, and has no Raw case: reported "not run" with
    that reason).
  - DT-2's closing checks, scoped by this task's resolution (the `rawstore` package and its tests are
    M1.5's): `rg -n "huron\.core\.raw\b|IngestSession|RevisionRecord|RawRuntime|ExpirySweep|ingest_sweep|completion_reserve|DATASET_LOCKED|INGEST_SESSION" src tests scripts pyproject.toml --glob '!src/huron/core/rawstore/**' --glob '!tests/unit/test_rawstore_*.py'`
    and `rg -n "\b(dataset_revisions|ingest_sessions|ingest_files|ingest_commit_intents|ingest_recoveries|revision_amendments|purge_records|raw_external_datasets|raw_catalog_publications|audit_events|outbox_events)\b" src/huron`
    print nothing; `rg -n "raw_store|class Storage\b|: Storage\b" src/huron/applications/api` prints
    nothing; `rg -n 'ContractMismatch|CONTRACT_MISMATCH' src tests design/api.html` prints nothing
    (owner decision 11, B-15); `rg -n 'insert_outbox_event|OutboxEvent|_outbox\b' src tests` prints
    nothing outside `tests/contract/test_catalog_store.py`, whose outbox helpers leave in M1.7 (owner
    decision 11, B-2).
  - `rg -n '"(ingest_session|ingest_commit|revision)"' src/huron` and
    `rg -n "unfinished ingest|'ingest_commit'" src` print nothing (DT-14 deletions, DT-2's exemption);
    `rg -n "code_or_detail" src tests` prints nothing (DT-8 deletions);
    `rg -n 'HURON_COMPLETION_|HURON_INGEST_SWEEP_' dev.env docker-compose.yml Makefile docs/getting-started`
    prints nothing.
  - `tests/unit/test_api_router_composition.py` passes with 40 legacy operations, every one 401 without a
    credential, and the 12-tag set.
  - `uv run python -c "import yaml; d = yaml.safe_load(open('.github/workflows/nightly.yml')); assert list(d['jobs']) == ['unit-macos'], d['jobs']"`
    exits 0, and the triggers and the label gate hold (PyYAML reads the `on` key as `True`):
    `uv run python -c "import yaml; d = yaml.safe_load(open('.github/workflows/nightly.yml')); t = d.get('on', d.get(True)); j = d['jobs']; assert t['pull_request']['types'] == ['labeled', 'synchronize'], t; assert {'schedule', 'workflow_dispatch'} <= set(t), t; assert \"contains(github.event.pull_request.labels.*.name, 'nightly')\" in j['unit-macos']['if'], j"`
    exits 0; `rg -n 'pytest -m acceptance' .github` prints nothing; `test ! -e .github/workflows/acceptance.yml`.
  - `rg -n '25 GiB' AGENTS.md Makefile docs/getting-started/testing.md` prints nothing.
  - `uv run --locked python scripts/check_duplication.py src` exits 0 against the hand-edited baseline;
    every signature added to it is a subset of a pre-task signature that lost only deleted files,
    or the exact six-fragment `rbac.py` regrouping explicitly approved above, and
    "Execution notes" lists each with its source group and the running total.
  - The coverage-floor procedure as in M1.3; the new `fail_under` and the unit test-count change are
    recorded.
- Dependencies: M1.3.
- Decisions: OQ-2.1 (settled, owner decision 12)
- Status: complete

### M1.5 D2-3: `rawstore` reduced to `PosixGenerationStore` and the surviving primitives

- Intent: leave `huron.core.rawstore` holding only what the legacy hierarchy still writes through
  (`CURRENT.json` generations, R2-3) and the descriptor-level primitives DT-11 will adapt, under a name
  that says what is left; `huron/schema/storage.py` leaves with its last importer (moved here from D2-2).
- Delete (orchestrator `git rm`): `src/huron/core/rawstore/commit.py`, `src/huron/core/rawstore/inspection.py`,
  `src/huron/schema/storage.py`, `tests/unit/test_rawstore_inspection.py`, `tests/unit/test_rawstore_commit.py`
  (its `fsync_dir` cases move to `test_rawstore_materialize.py`), `tests/unit/test_rawstore_store.py` (its
  generation-half cases move to the existing `tests/unit/test_rawstore_generation.py`; the implementer
  reads it with `git show <base>:tests/unit/test_rawstore_store.py`).
- Rename (orchestrator `git mv`): `src/huron/core/rawstore/store.py` → `src/huron/core/rawstore/generations.py`.
- Modify:
  - `generations.py`: class `PosixGenerationStore` to the contract of "DT-2 interfaces and contracts"
    (`__init__(self, root: Path)`, `root`, `initialize` creating only `organization/`, `write_generation`,
    private `_atomic_replace`); every other member of DT-2's D2-3 list leaves, each first proved
    caller-free with `rg` (`create_staging`, `write_part`, `finish_file`, `_copy_file`, `discard_file`,
    `stat_document`, `read_document`, `write_document`, `seal`, `verify_envelope`, `commit_envelope`,
    `_installed_payload`, `_safe_relative`, `_stream_part`, the `CompletionAdmission` member and the two
    constructor keywords). Its docstrings describe the generation store only.
  - `materialize.py`: gains `fsync_dir` (moved verbatim from `commit.py`); loses `candidate`, `install`,
    `file_chunks`, `flush_tree` and the sealing helpers. `completion.py` unchanged.
  - `rawstore/__init__.py`: exports `PosixGenerationStore`, `directory`, `descendant`, `observe`,
    `write_all`, `rename_exclusive`, `fsync_dir` and `CompletionAdmission`; its docstring says so.
  - `src/huron/applications/api/app.py`: builds `PosixGenerationStore(Path(settings.data_root))`.
  - Tests: `tests/unit/test_rawstore_materialize.py` and `tests/unit/test_rawstore_completion_admission.py`
    keep every case for a survivor and drop the rest (the store-integration cases at
    `test_rawstore_completion_admission.py:161` and `test_rawstore_materialize.py:36` go);
    `test_rawstore_generation.py` gains the moved cases; every importer of `PosixRawStore` that
    `rg -l PosixRawStore tests` lists at the base (`tests/{catalog_creation_support,repository_fixture}.py`,
    `tests/integration/test_catalog_{creation,descriptions}.py`, `tests/unit/test_{api_app,authorization_credentials,authorization_decisions,authorization_guards,catalog_lifecycle,catalog_ports,core_workflows,execution_model,repository_hierarchy,repository_rbac}.py`
    as far as they survive M1.4) switches to `PosixGenerationStore`.
  - `docs/getting-started/repository-layout.md`: the `core/rawstore/` tree line becomes "the hierarchy's
    generation store and the POSIX primitives the Volume adapter adopts".
  - `design/roadmap.html` §1 tree (`:114` at `fa51f46`): the `core/rawstore/` line describes the
    generation store (`core/rawstore/  generation files and the anchored POSIX primitives`) instead of
    "POSIX staging, checksums, atomic publication and sealing" (plan-wide "No backwards compatibility" rule).
- Design: "DT-2 design: …" → "DT-2 decisions" (`PosixRawStore` (R2-3), `fsync_dir`, Surviving
  primitives), "DT-2 deletion steps" (D2-3), "DT-2 interfaces and contracts" (`PosixGenerationStore`,
  Surviving primitives, Coverage floor procedure); "DT-1 design: …" → "DT-1 target package tree"
  (`rawstore`, as DT-2 corrects it).
- Skills: `oop-design` (`core/rawstore`); `fastapi` (`app.py`).
- Verification:
  - The plan-wide gate; `uv run lint-imports` keeps 14 contracts; `make docs` exits 0.
  - DT-2's closing check `rg -n "PosixRawStore|RawStore\b|commit_envelope|assert_same_filesystem|CrossDeviceCommitError|verify_envelope|flush_tree|file_chunks|\.staging" src tests`
    and the terms moved here from M1.4,
    `rg -n "huron\.schema\.storage|PartLengthMismatch|completion_reserve|max_concurrent_completions" src tests scripts pyproject.toml`,
    print nothing.
  - The surviving-primitives contract: `uv run pytest tests/unit/test_rawstore_materialize.py tests/unit/test_rawstore_completion_admission.py tests/unit/test_rawstore_generation.py --cov=huron.core.rawstore --cov-report=term-missing --cov-fail-under=0`
    shows `materialize.py`, `completion.py` and `generations.py` at 100 % from those three modules alone;
    `rg -n "from huron\.core\.rawstore|import huron\.core\.rawstore" src` lists only `app.py` (no
    production importer of a primitive before M11).
  - `test_rawstore_generation.py` pins `write_generation`'s contract (generation outside `1..999_999` is
    `ValueError`; the numbered file is durable before `CURRENT.json` moves; an existing file at the
    number is replaced) and `initialize` creating `organization/` and nothing else.
  - The coverage-floor procedure as in M1.3; duplication-baseline signatures that change only because
    `store.py` became `generations.py` (a pure re-path) or because a member file was deleted (a subset)
    are a reviewed hand edit, made as in M1.4 and recorded with the running total for G1; both kinds are
    exempt from the per-group cap.
- Dependencies: M1.4.
- Status: complete

### M1.6 D2-4: Owner decision 10's password login, cookie sessions and server code flow

- Intent: delete the Python password login, cookie sessions with CSRF, the server authorization-code
  flow and the whole `/auth` router with its `GET /auth/session` and `GET /auth/providers`, which no
  client calls, with their stores, settings, `dev.env` lines and tests; keep API keys, service accounts,
  dev headers, the legacy bearer verifier (`JwksVerifier`, `OidcResolver`, `OidcUser`, `OidcClient`
  discovery) and `POST /api/v1/users/{id}/disable` (OQ-2.2 (a)) for DT-6 and the legacy surface (owner
  decision 11, B-12, B-13). M9.3 re-creates `routes/auth` with the exchange only.
- Delete (orchestrator `git rm`): `src/huron/core/security/{sessions,password}.py`,
  `src/huron/core/security/_impl/{password_authentication,oidc_authentication}.py`,
  `src/huron/core/metastore/{sessions,memory_sessions,credentials,memory_password}.py`,
  `src/huron/applications/api/authorization/cookies.py`,
  the whole `src/huron/applications/api/routes/auth/` package (`__init__.py`,
  `endpoints/{__init__,login,oidc,session}.py`, `schema/{__init__,login,session}.py`) and
  `src/huron/core/security/_impl/self_access.py` (owner decision 11, B-13); tests
  `tests/unit/test_api_login.py`,
  `tests/unit/test_authorization_cookies.py`, `tests/unit/test_auth_password.py`,
  `tests/unit/test_auth_sessions.py`, and `tests/unit/test_postgres_credential_conflicts.py` once the
  verifier confirms at the base that it pins only `local_credentials`.
- Modify:
  - Every partial source edit of DT-2's D2-4 "Partial, source" (`core/security/oidc.py` keeps discovery,
    `OidcProviderConfig`, `OidcResolver`, `JwksVerifier`, `OidcUser`; `_impl/credential_authentication.py`
    precedence bearer then development headers; `_impl/identity.py` loses `create_user` and
    `set_password`, `disable_user` stops revoking sessions; `authorization/credentials.py` loses
    `current_session` and `_enforce_csrf`; `app.py` loses the `routes.auth` import (`:40`) and its
    include in `create_app` (owner decision 11, B-13); `routes/v1/endpoints/users.py` keeps only
    `disable_user` and `routes/v1/schema/users.py` its models;
    `runtime.py` and `app.py` lose the credential and session stores, `oidc_client`,
    `password_authentication`, `oidc_authentication` and `_configure_oidc`'s client half; `settings.py`
    the seven fields; `scripts/keycloak/huron-realm.json` the `/auth/oidc/callback` redirect URI).
    `scripts/keycloak/huron-realm.json`'s `huron-web` client `description` (`:22`) no longer names
    `/auth/oidc/start` or `/auth/oidc/callback`: it reads "Client whose ID is the audience of the bearer
    tokens the API's legacy verifier accepts. Dev-only secret, valid only for the Keycloak instance
    docker-compose.yml runs locally."
  - Following from those deletions: the password-user members of `core/security/principals.py`'s
    `PrincipalStore` and their implementations in `core/metastore/{principals,memory_principals}.py`;
    the credential and session row builders in `core/metastore/rows.py`; the re-exports in
    `core/security/__init__.py` (with `self_access_summary`), `core/metastore/__init__.py` and
    `authorization/__init__.py`; the `SelfAccessSummary` and `ScopeCapabilities` types
    (`core/security/types.py:50-63`; `ScopeRoles` leaves with the `routes/auth` package) and the
    `/auth/session` docstring mentions in `routes/v1/endpoints/api_keys.py:5` and
    `authorization/credentials.py:100` (owner decision 11, B-13); `OidcNotConfigured` with its
    `ERROR_CODES` entry, its `design/api.html` §7 row and the
    `tests/unit/test_api_errors.py:33` case, because its only raiser (`_impl/oidc_authentication.py`)
    leaves here (convention 1; the DT-6 ledger line is then already met); the §7 rows of every code
    declared by a deleted module (`PASSWORD_REJECTED`, `SESSION_EXPIRED`, `SESSION_REVOKED` and the CSRF
    and login codes that `test_error_contract.py` reports) leave with their classes; docstrings that say
    "password" about the deleted login are rewritten.
  - `pyproject.toml`: the Ruff N818 per-file ignores for the deleted `src/huron/core/security/password.py`
    and `src/huron/core/security/sessions.py` leave with their files.
  - Tests: every partial test edit of DT-2's D2-4 "Partial, tests"
    (`tests/unit/{test_api_oidc,test_auth_oidc,test_authorization_credentials,test_security_authentication,test_api_users,test_api_app,test_api_router_composition,test_api_settings,test_execution_model}.py`,
    `tests/contract/test_auth_store.py`), plus `tests/unit/{test_auth_principals,test_stores_rows,test_api_errors}.py`
    and the docstring at `tests/contract/test_rbac_store.py:361`; every `/auth/session` and
    `/auth/providers` case in `tests/unit/test_api_{users,oidc,rbac}.py` (`test_api_login.py` is deleted
    whole) and the
    `self_access_summary` cases of `tests/unit/test_security_authentication.py` go;
    `test_api_router_composition.py` expects 38 v1 operations, no `/auth` path, and 11 tags (the D2-2 set
    without `authentication`) (owner decision 11, B-13).
  - `dev.env`: the `HURON_LOGIN_FLOW_SECRET`, `HURON_WEB_APP_URL`, `HURON_OIDC__CLIENT_SECRET` and
    `HURON_OIDC__REDIRECT_URL` lines leave in the commit that deletes their settings fields, with any
    reference in `docker-compose.yml` or `docs/getting-started/local-development.md` (owner decision 11,
    B-16). In `local-development.md` (line numbers at `fa51f46`) that is: the `HURON_LOGIN_FLOW_SECRET`
    (`:165`), `HURON_PASSWORD_LOGIN_ENABLED` (`:167`), `HURON_SESSION_COOKIE_NAME` (`:168`) and
    `HURON_WEB_APP_URL` (`:169`) rows leave; the `HURON_OIDC__*` row (`:166`) keeps
    `HURON_OIDC__ISSUER` and `HURON_OIDC__CLIENT_ID` as its examples (the bearer verifier's settings stay)
    and drops `HURON_OIDC__CLIENT_SECRET` and `HURON_OIDC__REDIRECT_URL`; the dev-headers curl example
    (`:183-186`) targets `http://localhost:8080/api/v1/organizations` instead of `/auth/session`; and
    `:211-212` drops the "`/auth/oidc/callback` sends the browser after login (`HURON_WEB_APP_URL` in
    `dev.env`)" clause, keeping the side-by-side instructions. The `Makefile`'s `web` help (`:81`) loses
    "(the URL HURON_WEB_APP_URL in dev.env points at)", and `design/api.html` §1 loses its
    `GET /auth/session` row (`:116`).
  - Design record (DT-26 row landing with DT-2 D2-4): `design/auth.html` §2 Sessions (`sessions`), §3 CSRF
    (`csrf`) and §4 Admin-provisioned passwords (`passwords`) removed (§1, §5 and §6 are DT-6's and DT-22's).
  - `design/roadmap.html` (line numbers at `fa51f46`; plan-wide "No backwards compatibility" rule):
    integration milestone 2 (`:509-520`) becomes `retired`, its text one paragraph saying that the Python
    login, sessions and CSRF were deleted on 2026-10-23 and that the web keeps its own sessions;
    milestone 12 (`:664-668`) loses "admin-provisioned users" (`create_user` leaves here).
  - `scripts/duplication_baseline.json` (reviewed hand edit, after the code edits, as in M1.4): every
    group `uv run --locked python scripts/check_duplication.py src` reports as new or grown must be a
    baseline signature minus files this task deletes (expected: `core/metastore/api_keys.py` +
    `memory_principals.py` + `principals.py` from the six-file `api_keys`/`credentials`/
    `memory_principals`/`memory_sessions`/`principals`/`sessions` group); each is added to `groups` with
    its scanned size, then `--update-baseline` ratchets the baseline down to the scan. Any other new or
    grown group stops the task. Each added signature, its source group and the running total go under
    "Execution notes"; deletion subsets are exempt from the per-group cap.
    Narrow owner-approved exception (2026-10-25): admit the size-2 signature
    `core/metastore/api_keys.py` + `core/metastore/memory_principals.py` from that size-7
    six-file group. Its two fragments are unchanged; deleting `principals.py`'s
    `get_user_by_subject` within the surviving file accounts for the narrower signature.
    This exception admits no other regrouping or growth and consumes no capped signature.
- Design: "DT-2 design: …" → "DT-2 decisions" (Item 10 boundary), "DT-2 deletion steps" (D2-4), "DT-2
  interfaces and contracts" (Coverage floor procedure, Surviving-surface invariant), "DT-2 deletions";
  "DT-6 design: …" → "DT-6 the L-5 reading and the credential ledger" (what stays for DT-6); "DT-26
  design: …" → "DT-26 design record pages: the Raw-facing six" (`auth.html` §2–§4), "DT-26 decisions"
  (Auth page reach); OQ register "DT-2 design" (OQ-2.2).
- Skills: `fastapi` (`applications/api`); `oop-design` (`core/security`, `core/metastore`);
  `postgresql-table-design` (`core/metastore` adapters).
- Verification:
  - The plan-wide gate (contract and integration in the background); `uv run lint-imports` keeps 14
    contracts; `make docs` exits 0; `uv run pytest tests/unit/test_error_contract.py` passes.
  - DT-2's closing check over `src tests`,
    `rg -n "SessionStore|SessionRecord|session_cookie|csrf|CSRF|LoginFlow|login_flow|password|local_credentials|/auth/login|/auth/logout|/auth/oidc|web_app_url|client_secret|redirect_url" src tests`,
    prints nothing; over `scripts` it prints only lines that are not Huron's legacy credentials:
    `scripts/keycloak/huron-realm.json`'s Keycloak user credentials and `resetPasswordAllowed` (the file is
    replaced by the `company` realm in M9), `scripts/polaris_dev.py`'s `db-password` for the Polaris
    launcher's own database (`:47-50`, `:60`) and its Polaris bootstrap `client_secret` (`:160`),
    `scripts/polaris-dev.sh`'s Polaris `initdb --pwfile` (`:82`) and its two status lines for the web's own
    account store, "Huron administrator password" (`:168`) and "Topic demo passwords" (`:170`), which
    owner decision 10 keeps, and the secret-redaction pattern and fixture in
    `scripts/inspect_icechunk.py` and `scripts/test_icechunk_inspector.py` (line numbers at `fa51f46`);
    `rg -n 'auth/oidc/callback' scripts` prints nothing; `rg -n "OidcNotConfigured|OIDC_NOT_CONFIGURED" src tests design/api.html` prints nothing.
  - `tests/unit/test_api_router_composition.py` passes with 38 v1 operations, every one 401 without a
    credential, no `/auth` path and 11 tags;
    `test ! -e src/huron/applications/api/routes/auth -a ! -e src/huron/core/security/_impl/self_access.py`;
    `rg -n "/auth/session|/auth/providers|self_access|SelfAccessSummary|ScopeCapabilities|ScopeRoles" src tests`
    prints nothing (owner decision 11, B-13); `POST /api/v1/users/{id}/disable` keeps its path, statuses
    and body (`tests/unit/test_api_users.py`).
  - `rg -n 'HURON_LOGIN_FLOW_SECRET|HURON_WEB_APP_URL|HURON_OIDC__CLIENT_SECRET|HURON_OIDC__REDIRECT_URL|HURON_PASSWORD_LOGIN_ENABLED|HURON_SESSION_COOKIE_NAME|HURON_COMPLETION_|/auth/session|/auth/oidc' dev.env docker-compose.yml Makefile docs/getting-started design/api.html`
    prints nothing, then
    `uv run --env-file dev.env python -c "from huron.applications.api.settings import ApiSettings; ApiSettings()"`
    exits 0 (owner decision 11, B-16).
  - `rg -n 'id="(sessions|csrf|passwords)"' design/auth.html` prints nothing;
    `rg -n 'security/(password|sessions)\.py' pyproject.toml` prints nothing;
    `rg -n '/auth/(login|logout|oidc|session|providers)' design/roadmap.html` prints nothing.
  - `uv run --locked python scripts/check_duplication.py src` exits 0 against the hand-edited baseline;
    every signature added to it is a subset of a pre-task signature that lost only deleted files,
    except the exact size-2 signature approved above, and
    "Execution notes" lists each with its source group and the running total.
  - The coverage-floor procedure as in M1.3 (adapter modules measured from the "unit or contract" run).
- Dependencies: M1.4.
- Decisions: OQ-2.2 (settled, owner decision 12)
- Status: complete

### M1.7 D2-5: Migration `0014_retire_legacy_raw` and the schema map

- Intent: drop the nine Raw tables, their four guard functions, `audit_events`, `outbox_events`,
  `sessions`, `local_credentials` with its guard and the writer-less `public.reconciliation_findings`
  unconditionally in one forward, irreversible revision before the first lake revision, now that no
  adapter names a dropped table, discarding their development rows; remove the dead `raw_revision` kind
  from `lineage_edges`; bring the schema map and the contract tests to the new head; and retire the
  roadmap's P2 row (owner decision 11, B-2, B-5, B-17).
- Delete: none.
- Create:
  - `migrations/versions/0014_retire_legacy_raw.py`: the contract of "DT-2 interfaces and contracts" →
    "Migration `0014_retire_legacy_raw`" (`revision`, `down_revision = "0013_retire_releases"`,
    `def upgrade() -> None: execute_sql(DDL)` from `migrations/_ddl.py` with no refusal, flag or `DO $$`
    block, one transaction, no `CASCADE`, no `IF EXISTS`, no import of `huron`, `downgrade()` raising
    `RuntimeError("legacy Raw and credential tables cannot be restored")`); the DDL includes
    `DROP TABLE outbox_events;`, the `reconciliation_findings` drop (OQ-1.1 (a)), and `DELETE FROM
    lineage_edges WHERE upstream_kind = 'raw_revision' OR downstream_kind = 'raw_revision';` followed by
    the `ALTER TABLE lineage_edges` that drops and re-adds `lineage_edges_upstream_kind_vocabulary` and
    `lineage_edges_downstream_kind_vocabulary` as `CHECK (… IN ('bronze_snapshot','silver_snapshot','gold_version'))`;
    it touches only objects this Alembic chain created (owner decision 11, B-2, B-5, B-17, B-19).
  - `tests/contract/test_retire_legacy_raw.py` (`postgres:16` through testcontainers, with this module's
    own copy of the `_config`/`_migrate` helper until M8's `tests/postgres.py`):
    `test_upgrade_drops_every_legacy_table_and_function` (a fresh `upgrade head` leaves `to_regclass`
    NULL for every dropped table, `outbox_events` included, `pg_proc` lacks the five functions, and a
    `lineage_edges` insert of kind `raw_revision` fails with `check_violation`),
    `test_upgrade_drops_populated_legacy_tables` (with one row in every dropped table, a plain
    `upgrade head` reaches head and every table is gone), `test_offline_sql_renders_the_drops`
    (renders through the Alembic CLI, not a `Config` object, so it survives M8.1's helper consolidation:
    `subprocess.run([sys.executable, "-m", "alembic", "upgrade", "0013_retire_releases:0014_retire_legacy_raw", "--sql"], cwd=<repository root>, capture_output=True, text=True, check=True)`
    and asserts the `DROP` statements in `stdout`; the explicit range end keeps the case valid after later
    revisions move head),
    `test_downgrade_from_the_retirement_raises` (owner decision 11, B-2, B-5, B-17).
- Modify:
  - `migrations/schema.sql`: every edit of DT-2's D2-5 "Partial" (the `-- Reflects: 0014_retire_legacy_raw`
    stamp; the dropped tables leave sections 1, 2 (deleted), 3, 4 and 6 and the trailing Raw-web block;
    the `outbox_events` block deleted (owner decision 11, B-2); the `lineage_edges` vocabulary note lists
    `bronze_snapshot`, `silver_snapshot` and `gold_version`, with no annotation (owner decision 11, B-17);
    D-9's `roles` note "seeded from `huron.core.security.roles.ROLES`"; sections renumbered).
  - `tests/contract/test_catalog_store.py`: every test that writes a table 0014 drops is deleted with
    the helpers only those tests use, including `_insert_outbox_event` and
    `_assert_outbox_events_kind_format` (`:456-552`), their call at `:73`, the outbox payload case
    (`:826-844`), the `:1564` docstring reference, and the `0012_raw_web_catalogs` round trip at
    `:2035-2050`; `_LINEAGE_KINDS` (`:436`) loses `"raw_revision"`; the module's `_migrate` (`:43-45`) stays
    for `test_postgres_catalog_constraints_at_head` (`:1807-1811`) and pins `"0014_retire_legacy_raw"`
    instead of `"head"`; M8.1 replaces it with `migrated_postgres()`. The remaining tests that pin the previous head
    (`rg -n "0013_retire_releases" tests`) and mean "head" pin `0014_retire_legacy_raw`; outside
    `test_retire_legacy_raw.py`'s offline `0013_retire_releases:0014_retire_legacy_raw --sql` case, no test pins
    `0013_retire_releases` (owner decision 11, B-2, B-17, B-18).
  - `tests/contract/test_hierarchy_store.py`: `_HIERARCHY_TABLES` (`:82-92`) names only tables that
    survive 0014; its `"outbox_events"` entry (`:85`) leaves (owner decision 11, B-2).
  - `design/roadmap.html`: P2 Raw ingest & commit becomes `retired` with DT-26's paragraph, keeping the
    archived P2 plan link and run 34177077449 (DT-2's final deletion step).
- Design: "DT-2 design: …" → "DT-2 decisions" (L-18, OQ-1.1 consequence), "DT-2 deletion steps" (D2-5),
  "DT-2 interfaces and contracts" (Migration `0014_retire_legacy_raw`, Coverage floor procedure), "DT-2
  deletions" (Tables and functions); "DT-26 design: …" → "DT-26 roadmap rows" (P2); OQ register "DT-1
  design" (OQ-1.1) (owner decision 11, B-22).
- Skills: `postgresql-table-design`.
- Verification:
  - The plan-wide gate, with `uv run pytest -m contract` run in the background and polled; `make docs`
    exits 0; `uv run python scripts/check_schema_map.py` exits 0 naming `0014_retire_legacy_raw`.
  - The four `test_retire_legacy_raw.py` cases pass on `postgres:16`; `rg -n 'CASCADE|IF EXISTS|^from huron|^import huron' migrations/versions/0014_retire_legacy_raw.py`
    prints nothing; `rg -n 'legacy_reset|GUARDED|RESET_FLAG|x_arguments|cmd_opts' migrations tests` prints
    nothing (owner decision 11, B-5).
  - DT-2's closing checks: `rg -n '"head"' tests/contract/test_catalog_store.py` prints nothing;
    `rg -n "\b(dataset_revisions|ingest_sessions|ingest_files|ingest_commit_intents|ingest_recoveries|revision_amendments|purge_records|raw_external_datasets|raw_catalog_publications|audit_events|outbox_events)\b" tests`
    prints nothing outside `tests/contract/test_retire_legacy_raw.py`; `rg -n "0013_retire_releases" tests`
    prints only `tests/contract/test_retire_legacy_raw.py`;
    `rg -n "\b(local_credentials|reconciliation_findings|audit_events|outbox_events|raw_revision)\b" migrations/schema.sql`
    prints nothing (owner decision 11, B-2, B-17, B-18).
  - `rg -n 'retired' design/roadmap.html` shows P2, P3, Milestone 7 and Milestone 8 retired.
  - The coverage-floor procedure as in M1.3 (no `src` statements change, so the floor moves only if a
    deleted test case was the last cover of a line, which the pass conditions forbid).
- Dependencies: M1.4, M1.6.
- Decisions: OQ-1.1 (settled, owner decision 12)
- Status: complete

## Milestone 2 — Hierarchy rename and shared route modules

Give "catalog" and "collection" one meaning each in code before any lake module exists: the legacy
organization/project/dataset package becomes `huron.core.hierarchy` with its `*Collection` and `Catalog*`
symbols renamed, the import-linter contracts that name it change without changing the count (14), and the
two route helpers both routers will share move out of `routes/v1/`. No lake module, contract entry or
route is added; contract 7, the lake entries of the others and contract 19 arrive with M4.

### M2.1 Rename `huron.core.catalog` to `huron.core.hierarchy`

- Intent: rename the legacy hierarchy package, its listing classes and its reader and creation symbols so
  that `Catalog` and `Collection` are free for the Raw lake (L-21 (a)), with every importer rewritten and
  no alias, re-export or compatibility module left behind.
- Delete: none.
- Rename (orchestrator `git mv` before the pass): `src/huron/core/catalog/` → `src/huron/core/hierarchy/`;
  then `src/huron/core/hierarchy/_impl/collections.py` → `src/huron/core/hierarchy/_impl/listings.py`.
- Modify:
  - Every importer that `rg -l 'huron\.core\.catalog' src tests scripts` lists at the base (51 files at
    `fa51f46`, 37 after M1's deletions), rewritten to `huron.core.hierarchy`.
  - The symbol table of "DT-1 deletions and renames": `_Collection`, `OrganizationCollection`,
    `ProjectCollection`, `DatasetCollection` → `_Listing`, `OrganizationListing`, `ProjectListing`,
    `DatasetListing` (with `applications/api/dependencies.py`); `CollectionReader` → `ListingReader`;
    `CatalogReaders` → `HierarchyReaders`; `CatalogCreation` → `HierarchyCreation`;
    `applications/api/problems.py`'s alias `CATALOG_ERROR_CODES` → `HIERARCHY_ERROR_CODES`. The package's
    docstrings (`__init__.py`, `_impl/__init__.py`, `ports.py`, `errors.py`) say "hierarchy", not
    "Catalog". Test module file names stay (DT-1 renames none).
  - `pyproject.toml`: the per-file ignores for `src/huron/core/catalog/{errors,layers}.py` → `hierarchy`;
    contracts per "DT-1 import-linter contract set" restricted to what exists now: 2 layers
    `foundation:security:hierarchy:metastore:rawstore`; 4 forbids `huron.core.{security,hierarchy,metastore,rawstore}`,
    `huron.schema`, `huron.applications`; 5 forbids `huron.core.{hierarchy,metastore,rawstore}`, `huron.schema`;
    6 renamed "hierarchy uses security and foundation only" with source `huron.core.hierarchy` and
    forbidden `huron.core.{metastore,rawstore}`, `huron.schema`; 9 ("rawstore uses schema only", name and
    the rest unchanged until its DT-1 row lands with the first `rawstore` module importing `lake`) has
    its forbidden `huron.core.catalog` → `huron.core.hierarchy`, so it forbids
    `huron.core.{foundation,security,hierarchy,metastore}`; 10 and 13 sources
    `huron.core.{foundation,security,hierarchy}`; 11 renamed "only security performs credential HTTP and
    token cryptography directly", sources `huron.core.{foundation,hierarchy,metastore,rawstore}`,
    forbidden `httpx`, `jwt`, `cryptography`; 14 renamed "hierarchy implementations are private to their
    owner" over `huron.core.hierarchy._impl`; contract 8's name becomes "metastore uses hierarchy security
    and foundation only" (text only; its `lake` entry is M4's).
  - `tests/unit/test_domain_import_contracts.py`: `OWNERS`, `PRIVATE_OWNERS`, the edge table, the contract
    names and the planted violations name `hierarchy`.
  - `scripts/duplication_baseline.json`: the clone groups whose files moved
    (`src/huron/core/catalog/_impl/creation.py`, `src/huron/core/catalog/types.py`, and any other renamed
    path the guard reports) are re-pathed by a reviewed hand edit, recorded under "Execution notes" with
    the running total of changed signatures for G1; pure re-paths (same files under the new path, same
    size) are exempt from the per-group cap of four, like M1.4–M1.6's deletion subsets (plan-wide
    "Duplication baseline" rule), and any other new or grown signature counts toward that cap.
  - Docs (DT-26 handoff to DT-1): `design/catalog-search.html:91`'s link and label → `../src/huron/core/hierarchy/__init__.py`
    "Hierarchy", and `:93`'s link to the deleted `core/raw/__init__.py` goes with its "Raw owns uploads and
    revisions;" clause (both of the page's code links, DT-26 "broken links"); `docs/getting-started/repository-layout.md:28`
    `core/catalog/` → `core/hierarchy/` (the legacy organization/project/dataset hierarchy, as DT-1's
    tree); `docs/getting-started/conventions.md:97`'s path follows the rename (its sentence is DT-8's in
    M6); `design/roadmap.html` `core/catalog/` → `core/hierarchy/` at `:112` (the §1 tree), `:170` (P0),
    `:175` (P1), `:634` (milestone 10) and `:851` (§5), line numbers at `fa51f46` (plan-wide "No backwards
    compatibility" rule).
- Design: "DT-1 design: Architecture skeleton: package homes, dependency graph and cross-cutting API
  conventions" → "DT-1 decisions" (L-21), "DT-1 target package tree" (`hierarchy/`, `_impl/listings.py`),
  "DT-1 import-linter contract set (diff against the sixteen)" (rows 2, 4–6, 9, 10, 11, 13, 14 and the final
  paragraph's landing order), "DT-1 deletions and renames"; "DT-2 design: …" → "DT-2 decisions" (Order with
  DT-1); "DT-26 design: …" → "DT-26 broken links and their fixes" (`catalog-search.html` row), "DT-26
  developer docs, README and history" (`repository-layout.md:29` tree), "DT-26 handoffs" (Given → DT-1).
- Skills: `oop-design` (`core/hierarchy`); `fastapi` (`applications/api`).
- Verification:
  - The plan-wide gate; `uv run lint-imports` reports "Contracts: 14 kept, 0 broken" and lists contracts 6,
    11 and 14 under their new names; `make docs` exits 0.
  - `rg -n 'huron\.core\.catalog|core/catalog' src tests scripts pyproject.toml docs/getting-started design/catalog-search.html design/roadmap.html`
    prints nothing (the dated UML atlases and `design/core-map.html` keep theirs until M19, under their
    status line); `rg -n '\b(_Collection|OrganizationCollection|ProjectCollection|DatasetCollection|CollectionReader|CatalogReaders|CatalogCreation|CATALOG_ERROR_CODES)\b' src tests scripts`
    prints nothing; `rg -n '\bCatalog\b' src/huron/core/hierarchy` prints nothing;
    `test ! -e src/huron/core/catalog`.
  - `tests/unit/test_domain_import_contracts.py` passes with the planted `hierarchy` violations each
    breaking exactly its contract.
  - Every modified file at 100 % (PostgreSQL adapter modules from
    `uv run pytest -m "unit or contract" --cov=src/huron --cov-report=term-missing --cov-fail-under=0`);
    statements only move, so `fail_under` is unchanged and the covered and total counts equal M1.7's
    (recorded).
  - `uv run --locked python scripts/check_duplication.py src` exits 0 against the hand-edited baseline.
- Dependencies: M1.5, M1.7.
- Status: complete

### M2.2 Shared route modules and the application docstrings

- Intent: move the precondition and pagination helpers out of the legacy `routes/v1/` package so the lake
  router can share them without importing the legacy surface (DT-1, DT-18), and correct the two package
  docstrings DT-1 names; the docstrings describe what exists now.
- Delete: none (the moved files leave `routes/v1/` with no re-export).
- Rename (orchestrator `git mv`): `src/huron/applications/api/routes/v1/preconditions.py` →
  `src/huron/applications/api/routes/preconditions.py`; `src/huron/applications/api/routes/v1/pagination.py`
  → `src/huron/applications/api/routes/pagination.py`.
- Modify:
  - Every importer `rg -l 'routes\.v1\.(preconditions|pagination)' src tests` lists at the base
    (`routes/v1/endpoints/{api_keys,bindings,datasets,organizations,policies,projects,service_accounts}.py`;
    `tests/unit/test_api_{pagination,preconditions,visibility}.py`; `tests/contract/test_rbac_store.py`),
    rewritten to `huron.applications.api.routes.{preconditions,pagination}`.
  - `src/huron/applications/__init__.py`: the stale `pkg` sentence is deleted and the docstring names the
    `api` application (M10 adds `cli` with its package).
  - `src/huron/applications/api/routes/__init__.py`: the docstring names `v1` (the legacy `/api/v1`
    surface) and the two shared modules `preconditions` and `pagination`; the `auth` package left with
    M1.6, and M9.4 names `auth`, `discovery` and `lake` once M9.3 and M9.4 have created them.
  - `design/roadmap.html:198`: `routes/v1/pagination.py` → `routes/pagination.py`.
- Design: "DT-1 design: …" → "DT-1 target package tree" (`routes/`), "DT-1 deletions and renames" (the
  route modules and both docstring rows); "DT-18 design: Lake API contract" → "DT-18 deletions" (moved
  modules, no re-export).
- Skills: `fastapi`.
- Verification:
  - The plan-wide gate; `uv run lint-imports` keeps 14 contracts (contract 12 covers the moved modules as
    `routes.**`); `make docs` exits 0.
  - `rg -n 'routes\.v1\.(preconditions|pagination)|routes/v1/(preconditions|pagination)' src tests design docs --glob '!*-uml.*'`
    prints nothing; `test ! -e src/huron/applications/api/routes/v1/pagination.py -a ! -e src/huron/applications/api/routes/v1/preconditions.py`.
  - `rg -n '\bpkg\b' src/huron/applications/__init__.py` prints nothing.
  - The legacy surface is unchanged by the move: `tests/unit/test_api_router_composition.py` still pins
    38 operations and 11 tags (no `/auth` router after M1.6; owner decision 11, B-13); every moved or
    modified file at 100 %; `fail_under` unchanged.
- Dependencies: M2.1.
- Status: complete

## Milestone 3 — Broker values, keys and tokens

Intent: build the pure half of the auth broker inside `huron.core.security.broker`, a new public
subpackage of `security`: the rank ladder and the per-actor `Grants` with the `RoleMappingReader` port
and the roles-claim grammar (`ladder.py`), the signing-key values, the immutable `KeyRing`, the
rotation rule, the key-source and key-reader ports with the file adapter and the refreshing `HuronKeys`
(`keys.py`), and the Huron JWT issuer and verifier (`tokens.py`) with the shared test-key fixture
`tests/lake_tokens.py`. Nothing here is wired into `create_app`, `ApiStores` or `ApiRuntime` (M9), no
table exists yet (M8), and the broker imports neither the legacy RBAC modules nor anything outside
`security` and `foundation`. Every task keeps the 14 import-linter contracts M2 left, because the
subpackage sits inside `security` and contract 5 already confines it. The two new problem codes land
with their raise sites and their `design/api.html` §7 rows (convention 1).

### M3.1 The rank ladder, grants and the roles-claim grammar

- Intent: give every later lake operation one authorization vocabulary: five ranked roles, catalog or
  all-catalog grants, the one `require` that refuses with foundation `Forbidden`, the SQL-ready
  readability filter, the port that reads mapping rows, and the claim strings the issuer signs and
  `whoami` shows.
- Delete: none.
- Create:
  - `src/huron/core/security/broker/__init__.py`: the subpackage's public surface (docstring says
    `lake`, `metastore` and `applications.api` import from here, never from its modules); exports
    `Role`, `CatalogRef`, `Grant`, `Grants`, `ReadableCatalogs`, `RoleMappingReader`, `ClaimedRole`,
    `ROLE_CLAIM_PREFIX`.
  - `src/huron/core/security/broker/ladder.py`: `Role(IntEnum)` with `code`, `title`,
    `catalog_scoped` and `from_code` (`ValueError` on an unknown code); frozen `CatalogRef(id, name)`,
    `Grant(role, catalog)` and `ReadableCatalogs(every, ids)`; `Grants(subject, grants)` with
    `role_on`, `require`, `readable(minimum: Role = Role.READER)` (DT-18's handoff to DT-4: `every` only
    for a global grant ≥ `minimum`, otherwise the catalogs whose effective role is ≥ `minimum`),
    `__iter__` (global first, then catalogs by name) and `__bool__`; the constructor keeps the highest
    role per scope and raises `ValueError` for a catalog grant of a global-only role; `require` raises
    foundation `Forbidden` with DT-4's exact `detail` and `context` (`subject`, `role`, `scope`,
    `held`) and never `ResourceNotFound`; the `RoleMappingReader` Protocol
    (`roles_for_groups(groups) -> tuple[Grant, ...]`); `ROLE_CLAIM_PREFIX` and the frozen
    `ClaimedRole(role, catalog)` with `of(grant)`, `parse(claim)` (case-sensitive, no trimming,
    `ValueError` naming the broken rule, including the Polaris principal-role rule) and `__str__`.
    Imports: `foundation.errors`, standard library only; the legacy `core/security/roles.py`,
    `rules.py`, `principal.py`, `facts.py`, `scopes.py` and `_impl/` are neither imported nor edited
    (C-23).
  - `tests/unit/test_lake_ladder.py` (`pytestmark = pytest.mark.unit`, as every new module in this
    group: `addopts = "-m unit"` deselects unmarked tests): the vocabulary pin
    `{r.code: r.title for r in Role} == {c: d.title for c, d in ROLES.items()}` (legacy `ROLES` imported
    by the test only); `from_code` round trip and refusal; the Grants-level rows of DT-4's unit table
    (all-catalog grant with the exact `Forbidden.context` for a refused `PROJECT_ADMIN`, catalog grant,
    global plus catalog with iteration order, global-only role, global requirement with
    `scope == "global"` and `held is None`, unknown groups giving a falsy `Grants` and
    `readable() == ReadableCatalogs(False, frozenset())`); `readable(Role.DEVELOPER)` under a global
    Reader plus a catalog Developer grant; constructor normalization of duplicate scopes and its
    `ValueError`; `role_on` comparing catalogs by `id` only.
  - `tests/unit/test_role_claims.py`: every row of DT-5's grammar table (four accepted, eight refused,
    each refusal asserting the rule its `ValueError` names) and the round trip both ways over `Role` ×
    {`None`, `heliophysics`, `solar_wind-2`}, skipping global-only roles with a catalog, which `of`
    refuses; `of` refuses an empty catalog name and one containing `.`.
- Modify: none.
- Design: DT-4 design → "DT-4 decisions" (L-8, L-25, C-23, Visibility), "DT-4 the ladder and every spec
  route", "DT-4 interfaces and contracts" → "`broker/ladder.py`: roles, grants and the mapping port",
  "Tests this design requires" (unit cases); DT-5 design → "DT-5 decisions" (L-6, G-5 claim), "DT-5
  the roles-claim grammar (L-6 a)"; DT-18 design → "DT-18 handoffs" (row DT-4: `readable(minimum)`);
  DT-1 design → "DT-1 interfaces and contracts" → "`huron.core.security.broker`: the request-time
  actor" (public-surface rule).
- Verification:
  - The plan-wide gate; `uv run lint-imports` keeps all 14 contracts.
  - `uv run pytest tests/unit/test_lake_ladder.py tests/unit/test_role_claims.py` passes.
  - `rg -n "security\.(roles|rules|principal|facts|scopes|_impl)|from \.\.(roles|rules|principal|facts|scopes|_impl)" src/huron/core/security/broker`
    prints nothing (the broker shares no code with the legacy RBAC, C-23).
  - `src/huron/core/security/broker/{__init__,ladder}.py` at 100 % line coverage in the unit run.
- Dependencies: M2.
- Decisions: OQ-4.2 (settled, owner decision 12)
- Status: pending

### M3.2 Signing-key values, the key ring and the rotation rule

- Intent: model a signing key and its derived lifecycle as pure values, so that every answer about
  which key signs, which keys verify and what the JWKS lists is a function of one immutable snapshot
  and an instant, and so that a rotation is planned (and refused) without touching a store.
- Delete: none.
- Create:
  - `src/huron/core/security/broker/keys.py` (first half): `SigningAlgorithm`, `PrivateSigningKey`, the
    seven time constants (`TOKEN_TTL_MAX`, `VERIFY_LEEWAY`, `RETENTION`, `REFRESH_INTERVAL`,
    `MAX_RING_AGE`, `JWKS_MAX_AGE`, `MIN_PUBLICATION_LEAD`); the RFC 7638 thumbprint routine as a module
    function (`jwk_thumbprint(members) -> str`, the one `from_private` and M3.3's load check use);
    frozen `PublicSigningKey(kid, alg, members)` with `from_private` (EC SECP256R1 → ES256, RSA ≥ 2048
    bits → RS256, `ValueError` otherwise; RSA `key_ops` dropped, R5-1) and `as_jwk`; `KeyState`;
    frozen `SigningKeyRecord` with `state(at)`; frozen `KeyRing(records, private_keys, loaded_at)` with
    `signer`, `verification_key`, `jwks` and `algorithms`; frozen `Rotation`; `plan_rotation` and
    `initial_record`. No revocation state or `revoked_at` field exists (OQ-5.1).
  - `tests/unit/test_signing_keys.py` (first half): the state table at the six instants of DT-5's
    test list; exactly one signer either side of a rotation; `signer` raising
    `SigningKeyUnavailable` with `reason` `stale`, `no_active_key` and `not_loaded`;
    `verification_key` and `jwks` over pending, active, retiring and retired records (ascending
    `active_from`, `kid`/`alg`/`use` added only on render); `algorithms` sorted and distinct;
    `plan_rotation` refusing `lead_too_short`, `pending_key_exists` and `key_already_registered` (by
    `kid` and by `private_ref`) as `RotationRefused` with `context["reason"]`, and a valid plan whose
    `retired_at == insert.active_from`; `initial_record` with `active_from == at` and no `retired_at`;
    the timing invariant on the constants (`MIN_PUBLICATION_LEAD > MAX_RING_AGE` and
    `MIN_PUBLICATION_LEAD ≥ REFRESH_INTERVAL + JWKS_MAX_AGE`); `jwk_thumbprint` reproducing RFC 7638
    §3.1's `NzbLsXh8uDCcd-6MNwXF4W_7noWXFZAfHkxZsRGC9Xs` from the RFC's members; `from_private`
    refusing P-384 and RSA-1024 and giving equal values for two loads of one key. Keys are generated
    in the test; no PEM is committed.
- Modify:
  - `src/huron/core/security/errors.py`: `SigningKeyUnavailable(DomainError)` (`SIGNING_KEY_UNAVAILABLE`,
    503, `retry_after = 30`) and `RotationRefused(DomainError)` (`ROTATION_REFUSED`, 409); both join
    `__all__` and security's `ERROR_CODES` (the file already carries Ruff's N818 per-file ignore).
  - `src/huron/core/security/broker/__init__.py`: exports the names above.
  - `design/api.html` §7 (`<table id="error-codes">`): the `ROTATION_REFUSED` and
    `SIGNING_KEY_UNAVAILABLE` rows, verbatim from DT-18's ready-to-paste block.
  - `tests/unit/test_api_errors.py`: `_CLASSES` gains both classes; a case asserts
    `SigningKeyUnavailable.retry_after == 30` and `RotationRefused.retry_after is None`.
- Design: DT-5 design → "DT-5 decisions" (Algorithm, `kid`, Key set on the request path, No key can
  sign, Lifetime, Module split), "DT-5 signing keys: logical shape and lifecycle", "DT-5 interfaces
  and contracts" → "`broker/keys.py`: keys, the ring, the source and the rotation rule" (values,
  `KeyRing`, `plan_rotation`, `initial_record`) and "Settings, composition, errors and readiness"
  (Errors only), "DT-5 failure behaviour", "DT-5 tests this design requires"
  (`test_signing_keys.py`), "DT-5 open questions" (OQ-5.1); DT-18 design → "DT-18 error-code table rows
  (`design/api.html` §7, ready to paste)".
- Verification:
  - The plan-wide gate; `uv run lint-imports` keeps all 14 contracts.
  - `uv run pytest tests/unit/test_signing_keys.py tests/unit/test_api_errors.py tests/unit/test_error_contract.py`
    passes: `test_error_contract.py` finds each of `ROTATION_REFUSED` and `SIGNING_KEY_UNAVAILABLE`
    declared by exactly one class, documented with its status and marked live, and raised in the tree
    (`KeyRing.signer`, `plan_rotation`). `make docs` passes (a `design/` page changed).
  - `rg -n "revoked_at|REVOKED" src/huron/core/security/broker` prints nothing (OQ-5.1 (a): no
    revocation state).
  - `keys.py` and the modified `errors.py` at 100 % line coverage in the unit run.
- Dependencies: M3.1.
- Decisions: OQ-5.1 (settled, owner decision 12)
- Status: pending

### M3.3 Key source, key reader and the refreshing `HuronKeys`

- Intent: keep request paths free of I/O by loading private keys only at startup, on a 60-second
  refresh and on rotation, behind a source port whose production adapter reads one bare file name
  under one directory (a Kubernetes Secret volume in production), and give the tests a fixed key, an
  in-memory key source and a scripted key reader that can fail on demand.
- Delete: none.
- Create:
  - `tests/lake_tokens.py` (a support module: no `test_` prefix, and no callable in it is named
    `test_*`, because pytest collects an imported `test_*` callable as a test): `TEST_KEY`
    (`ec.derive_private_key(<fixed scalar literal>, SECP256R1())`), `TEST_KEY_REF = "test-es256.pem"`,
    `TEST_KID` (the 43-character thumbprint as a literal), `TEST_EPOCH = datetime(2026, 1, 1,
    tzinfo=UTC)`, `TEST_RECORD` (the `SigningKeyRecord` of `TEST_KEY` active from `TEST_EPOCH`, open
    ended); `InMemorySigningKeySource` (DT-5's second `SigningKeySource` adapter, a dict of keys,
    `SigningKeyUnavailable` when a ref is absent); `ScriptedSigningKeyReader` (records list, optional
    exception to raise, call counter). The scripted reader stands in for DT-5's `InMemorySigningKeys`
    here and stays: that fake becomes a half of `InMemoryLakeStore` in M4 (DT-17 D-2) and cannot fail on
    demand, while the `HuronKeys` failure rows need a reader that does.
- Modify:
  - `src/huron/core/security/broker/keys.py` (second half): the `SigningKeySource` Protocol
    (`load(private_ref)`); `FileSigningKeySource(directory)` (the bare-file-name rule of the column,
    symlinks followed, the resolved path kept under `directory.resolve()`, at most 16 KiB read,
    unencrypted PKCS#8 or traditional PEM; every failure a `SigningKeyUnavailable` with
    `context = {"private_ref", "reason"}`; synchronous, no cache, no file-mode policing); the
    `SigningKeyReader` Protocol (`unexpired(retired_after)`); `HuronKeys(reader, source, clock, *,
    refresh_interval: timedelta = REFRESH_INTERVAL)` with `ring`, `refresh()` (reuse loaded keys by
    `kid`, load the rest, refuse a thumbprint or `alg` mismatch, leave an unloadable pending key out
    and log its `kid` and ref, let store failures propagate), `__aenter__` (the first refresh refuses
    on a store failure, no active key, or any active or pending key that fails to load or match; then
    the loop starts) and `__aexit__` (cancels and awaits the loop). The `refresh_interval` keyword is
    the one addition to DT-5's signature: the loop body is reachable in a unit test only with a
    millisecond interval (the lifecycle pattern of convention 6); production composition never passes
    it. Logging uses the standard library `logging` (contract 10 forbids `structlog` in domains).
  - `src/huron/core/security/broker/__init__.py`: exports `SigningKeySource`, `FileSigningKeySource`,
    `SigningKeyReader`, `HuronKeys`.
  - `tests/unit/test_signing_keys.py` (second half): `TEST_KID ==
    PublicSigningKey.from_private(TEST_KEY).kid` (a derivation change fails here);
    `FileSigningKeySource` over `tmp_path` loading a Secret-shaped layout (`..data/` directory with
    per-key symlinks) and refusing, each with its `reason`, a symlink escaping the directory, the ref
    `../x.pem`, a P-384 key, RSA-1024, an encrypted PEM, a non-PEM file and a missing file; `HuronKeys`
    first refresh refusing an unloadable pending key, a thumbprint mismatch and an empty store; a
    runtime refresh failure keeping the previous ring, after which `ring.signer` raises `stale` once the
    clock passes `loaded_at + MAX_RING_AGE`; a record removed from the scripted reader taking effect at
    the next `refresh()`; the loop calling the reader again under `refresh_interval=timedelta(
    milliseconds=1)`, logging a failing pass (`caplog`) and stopping at exit.
- Design: DT-5 design → "DT-5 decisions" (L-2, Key set on the request path), "DT-5 interfaces and
  contracts" → "`broker/keys.py`: keys, the ring, the source and the rotation rule"
  (`FileSigningKeySource`, `SigningKeyReader`, `HuronKeys`), "DT-5 failure behaviour", "DT-5 tests this
  design requires" (shared fixture and `test_signing_keys.py`); DT-17 design → "DT-17 resolved
  disagreements between sections" (D-2: why the reader double is not the fake).
- Verification:
  - The plan-wide gate; `uv run lint-imports` keeps all 14 contracts.
  - `uv run pytest tests/unit/test_signing_keys.py` passes; `rg -n "^def test_|^async def test_" tests/lake_tokens.py`
    prints nothing.
  - `rg -n "monkeypatch" tests/unit/test_signing_keys.py` prints nothing (the seams are the source, the
    reader, the clock and `refresh_interval`).
  - `keys.py` at 100 % line coverage in the unit run.
- Dependencies: M3.2.
- Status: pending

### M3.4 The Huron JWT: claims, issuer and verifier

- Intent: mint and verify the token every lake request carries: ES256 (or RS256) under the ring's
  signer, `aud` always an array containing `huron-api`, `roles` rendered in `Grants` order and never
  used for authorization, every time rule checked against the injected `Clock`, and every failure one
  `AuthError` (401 `INVALID_CREDENTIAL`) that costs no signature check when the `kid` is unknown.
- Delete: none.
- Create:
  - `src/huron/core/security/broker/tokens.py`: `HURON_API_AUDIENCE`; frozen `HuronClaims` and
    `IssuedToken`; `HuronTokenIssuer(keys, *, issuer, audience, ttl, clock)` (construction
    `ValueError`s for an issuer with a trailing slash, query or fragment, an audience without
    `huron-api`, a `ttl` outside 60 s … `TOKEN_TTL_MAX`; `issue` synchronous, store-free, propagating
    `SigningKeyUnavailable` from `ring.signer`, refusing an empty subject or group name with
    `ValueError`, `groups` sorted and de-duplicated, `roles` as `str(ClaimedRole.of(g))`);
    `HuronTokenVerifier(keys, *, issuer, clock)` (`verify` in DT-5's check order: unverified header,
    `kid` lookup, PyJWT `decode` with `algorithms=[record.alg]` and `verify_exp`/`verify_iat` off, then
    the time rules with `VERIFY_LEEWAY` and the 3600 s lifetime ceiling, then the `sub`, `groups` and
    `roles` shapes; every `jwt.PyJWTError`, `ValueError` and `KeyError` becomes `AuthError`). Keep each
    function's cognitive complexity within 15 (complexipy) by splitting the rule checks into private
    helpers; M5.4's company-token verifier reuses the time-rule helper rather than restating it (the
    duplication gate).
  - `tests/unit/test_huron_tokens.py`: the golden token (a compact token minted once with `TEST_KEY`,
    `sub` `karl`, `groups` `["helio-scientists"]`, `roles`
    `["PRINCIPAL_ROLE:heliophysics.developer"]`, `iat` 2026-10-23T12:00:00Z, `exp` + 3600 s, committed as
    a string literal; under a `FakeClock` at 12:00:30Z `verify` returns the expected `HuronClaims` and
    the unverified header is `{"alg": "ES256", "kid": TEST_KID, "typ": "JWT"}`); issue then verify for
    each `Grants` case of DT-4's table; the whole rejection matrix of DT-5's test list (each
    `AuthError` with `code == "INVALID_CREDENTIAL"`; the hostile headers built with `jwt.encode` in the
    test, never through `mint`); the boundaries (`exp + 29 s` accepted, `exp + 31 s` refused; a retiring
    key's token verifying until `retired_at + RETENTION` and not after; a pending key's token
    verifying); construction refusals; `issue` raising `SigningKeyUnavailable` on a stale ring.
- Modify:
  - `src/huron/core/security/broker/__init__.py`: exports `HURON_API_AUDIENCE`, `HuronClaims`,
    `IssuedToken`, `HuronTokenIssuer`, `HuronTokenVerifier`.
  - `tests/lake_tokens.py`: `TEST_ISSUER = "https://huron.test"`; `refreshed_test_keys(clock)` (DT-5's
    `test_keys`, renamed so pytest never collects it): a `HuronKeys` over
    `ScriptedSigningKeyReader([TEST_RECORD])` and `InMemorySigningKeySource({TEST_KEY_REF: TEST_KEY})`,
    refreshed once, no loop; `mint(keys, clock, *, subject="karl", groups=frozenset({"helio-scientists"}),
    grants=None)` through the production `HuronTokenIssuer` (never a hand-built JWT).
- Design: DT-5 design → "DT-5 decisions" (`aud`, G-30, Lifetime), "DT-5 the Huron JWT: claims and
  validation on verify", "DT-5 interfaces and contracts" → "`broker/tokens.py`: claims, issuer and
  verifier", "DT-5 failure behaviour", "DT-5 tests this design requires" (shared fixture,
  `test_huron_tokens.py`); DT-4 design → "`broker/access.py`: the actor per request" (the verifier stays
  synchronous for `LakeAuthentication`).
- Verification:
  - The plan-wide gate; `uv run lint-imports` keeps all 14 contracts.
  - `uv run pytest tests/unit/test_huron_tokens.py tests/unit/test_role_claims.py tests/unit/test_signing_keys.py`
    passes.
  - `rg -n "monkeypatch|PyJWKClient" tests/unit/test_huron_tokens.py tests/lake_tokens.py` prints
    nothing (DT-22's no-bypass rule: real tokens through the production verifier).
  - `rg -n "^def test_|^async def test_" tests/lake_tokens.py` prints nothing.
  - `tokens.py` at 100 % line coverage in the unit run.
- Dependencies: M3.3.
- Status: pending

## Milestone 4 — In-memory lake store and request-time authentication

Intent: open the lake's two packages and the store contract every later lake task builds on. The first
`huron.core.lake` module, `ports.py`, declares the composite `LakeStore` (the store root) and
`LakeTransaction` (one open transaction carrying every writer port), so that one object satisfies all
the ports an operation needs (DT-17 D-2: no `ApiStores.role_mappings` or `.signing_keys`, ever). The
first `huron.core.metastore.lake` module, `memory.py`, is the in-memory fake: `InMemoryLakeStore`,
`InMemoryLakeTransaction`, the committed `LakeTables`, the staging `LakeBuffer` and the lock registry,
with the role-mapping and signing-key read halves composed into the root as mixins. The shared scenario
module `tests/lake_store_contract.py` runs against the fake here and against Postgres from M8. The
import-linter set grows with these packages: contract 7, the lake entries of contracts 2, 4, 5, 6, 8, 9,
10, 11 and 13, and DT-17's contract 19 (17 contracts after M4.1; contract 16 waits for the first
`huron.core.lake._impl` module, M7). `Actor` and `LakeAuthentication` then turn a Huron JWT into a
request-scoped actor whose grants are re-mapped through the current mappings on every call. Nothing is
added to `ApiStores` or `ApiRuntime` and nothing is wired into `create_app` (M8, M9).

### M4.1 The lake store root, the in-memory transaction and the import contracts

- Intent: give the lake its owner package and its adapter package with the boundaries enforced from the
  first commit, and give the fake its transaction model (staged writes applied atomically on a clean
  exit, discarded on an exception, refused after exit or when nested) before any writer port exists.
- Delete: none.
- Create:
  - `src/huron/core/lake/__init__.py` (docstring: the Raw lake domain; each later task exports its own
    operations and values) and `src/huron/core/lake/ports.py`: `LakeStore(Protocol)` with
    `transaction() -> AbstractAsyncContextManager[LakeTransaction]` and `async ping() -> None`;
    `LakeTransaction(Protocol)` with DT-17's docstring and, for now, no base port: no lake writer port
    exists yet, and each owning task adds its port to the bases (M7: `AuditWriter`,
    `RoleMappingWriter`, `SigningKeyWriter`, `CatalogWriter`, `MetadataSchemaWriter`,
    `RetryTransaction`; later milestones the rest of DT-17's list). `prune_claims` joins `LakeStore`
    with the PostgreSQL idempotency half (M8.3).
  - `src/huron/core/metastore/lake/__init__.py` (exports `InMemoryLakeStore`) and
    `src/huron/core/metastore/lake/memory.py`: `InMemoryLakeStore(*, seed: bool = True)` exposing
    `tables` (the committed `LakeTables`, which the scenario module's seeder writes), `ping()` and
    `transaction()`; `InMemoryLakeTransaction` (owns one `LakeBuffer` and the locks it took; a use after
    its block raises `RuntimeError`; a second `transaction()` opened in the same task while one is open
    raises `RuntimeError`); `LakeTables` with committed dicts for `lake.roles` (seeded with the five
    rows derived from `Role` when `seed=True`, the constants M8's drift test compares with `0015`),
    `lake.ldap_groups`, `lake.group_role_map` and `lake.signing_keys`, each keyed by its table's primary
    or unique key, with row dataclasses that mirror DT-4's and DT-5's logical shapes; `LakeBuffer`
    (staged puts and deletes per table, reads through own writes first, `apply` synchronous with no
    `await` so a commit is atomic to other tasks); the lock registry (an `asyncio.Lock` per exclusive
    key and a readers-writer lock per shared key, held until the transaction exits, released on an
    exception). The constructor takes no `clock` yet: no M4 half reads time, and `SystemClock` lives in
    the legacy `huron.core.metastore.hierarchy`, which contract 19 forbids to this package (M7.1 moves
    it into foundation and adds the keyword). No `IntegrityViolation` (M7.1), no `LockContractBroken`
    (M7.3), no `LockClass` (M8.3) and no Postgres module yet (M8).
  - `tests/lake_store_contract.py`: the shared scenario module (support module; no callable named
    `test_*`), opened here with the store-root scenarios: `ping()` answers `None`; a `transaction()`
    block exits cleanly; an exception raised inside the block propagates unchanged.
  - `tests/unit/test_lake_memory_store.py`: runs the store-root scenarios against `InMemoryLakeStore`;
    fake-only cases: `seed=True` yields exactly the five `(code, title, rank, scope)` rows of `Role`
    and `seed=False` none; a row staged into `ldap_groups` through an open transaction's buffer is
    read back inside it, is invisible to the root until exit, is applied on a clean exit and discarded
    on an exception; use after exit and a nested open raise `RuntimeError`; two tasks taking one
    exclusive key serialize, two shared holders coexist, a shared holder blocks an exclusive one, and
    every lock is released when the block raises (each wait bounded by `asyncio.timeout`); structural
    conformance: `LakeStore not in InMemoryLakeStore.__mro__` and `LakeTransaction not in
    InMemoryLakeTransaction.__mro__`, and every public member of each Protocol exists on its fake with
    the same parameters (names and kinds, from `inspect.signature`).
- Modify:
  - `pyproject.toml` `[tool.importlinter]`: contract 2's layer becomes
    `foundation:security:hierarchy:lake:metastore:rawstore`; contracts 4, 5 and 6 forbid
    `huron.core.lake` (DT-1 rows 4-6); contract 7 added ("lake uses security foundation and schema
    only", direct, source `huron.core.lake`, forbidden `huron.core.hierarchy`, `huron.core.metastore`,
    `huron.core.rawstore`); contract 8 renamed "metastore uses hierarchy lake security and foundation
    only" (forbidden list unchanged); contract 9 forbids `huron.core.lake` until M11 adds the
    `rawstore → lake` edge; contracts 10, 11 and 13 gain `huron.core.lake` among their sources;
    DT-17's contract 19 as two tables, because import-linter's `independence` type makes every listed
    module independent of every other and the legacy metastore modules import one another (`rbac`,
    `queries`, `principals` and `api_keys` import `rows`), and a layer cannot mix `|` and `:`
    elements: "lake adapters stay apart from the legacy hierarchy" (forbidden, source
    `huron.core.metastore.lake`, forbidden `huron.core.hierarchy` and the legacy modules
    `huron.core.metastore.{api_keys,hierarchy,memory_apikeys,memory_principals,principals,queries,rbac,rows,security_facts}`,
    each spelled out because a module expression's wildcard replaces whole segments only) and "legacy
    metastore modules never import the lake adapters" (forbidden, sources those nine modules, forbidden
    `huron.core.metastore.lake`). If M1 left a different set of legacy metastore modules, the list is
    `ls src/huron/core/metastore/*.py` minus `__init__.py` at the start of this task.
  - `tests/unit/test_domain_import_contracts.py`: the sandbox builds `huron.core.lake`,
    `huron.core.metastore.lake` and the legacy metastore module files contract 19 names; the
    allowed-edges case gains `lake → security, foundation, schema` and `metastore.lake → lake, security,
    foundation`; the forbidden-edges table gains `lake → hierarchy` ("lake uses security foundation
    and schema only"), `hierarchy → lake` ("hierarchy uses security and foundation only", contract
    6), `metastore.lake → metastore.rbac` and `metastore.lake → hierarchy` (the first contract-19
    table), `metastore.rbac → metastore.lake` (the second), `foundation → lake` and `rawstore → lake`
    (contract 9 at this step; M11.2 replaces this case when the edge becomes allowed).
  - `docs/getting-started/repository-layout.md`: the tree gains the `core/lake/` (the Raw lake domain) and
    `core/metastore/lake/` (its PostgreSQL adapters and in-memory fakes) lines, as DT-1's tree words them
    (the landing rule: a line naming a package lands with the task that creates it).
- Design: DT-17 design → "DT-17 decisions" (Store bundle, Adapter layout), "DT-17 resolved
  disagreements between sections" (D-2), "DT-17 target module layout", "DT-17 interfaces and contracts"
  (the composites, Lifecycle, "The fake (`memory.py`)"), "DT-17 `migrations/schema.sql` and the import
  rules" (contract 19), "DT-17 the shared migrate helper and the tests" (unit tier); DT-1 design →
  "DT-1 import-linter contract set (diff against the sixteen)" (contract 7 and the lake entries, final
  paragraph); DT-4 design → "Logical tables (DT-17 writes the DDL; R4-2 proves the constraints)"; DT-5
  design → "DT-5 signing keys: logical shape and lifecycle" (row shape).
- Verification:
  - The plan-wide gate and `make docs`; `uv run lint-imports` reports 17 contracts kept (14 + contract 7
    + the two contract-19 tables).
  - `uv run pytest tests/unit/test_domain_import_contracts.py tests/unit/test_lake_memory_store.py`
    passes, each new forbidden case failing with its own contract's name `BROKEN`.
  - `rg -n "metastore\.(api_keys|hierarchy|memory_|principals|queries|rbac|rows|security_facts)|core\.hierarchy|SystemClock" src/huron/core/metastore/lake`
    prints nothing; `rg -n "metastore\.lake|from \.lake" src/huron/core/metastore --glob '!**/lake/**'`
    prints nothing.
  - `rg -n "role_mappings|signing_keys" src/huron/applications/api/runtime.py tests/unit/support.py`
    prints nothing (D-2).
  - `src/huron/core/lake/{__init__,ports}.py` and `src/huron/core/metastore/lake/{__init__,memory}.py`
    at 100 % line coverage in the unit run.
- Dependencies: M3.4; M2 (the renamed contracts this task edits).
- Status: pending

### M4.2 Role-mapping and signing-key read halves

- Intent: make the fake answer the two read ports the broker owns, with the same per-table half layout
  the Postgres adapter follows from M8, and give the scenario module a seeding seam so the same
  scenarios can later run against Postgres without a writer port.
- Delete: none.
- Create:
  - `src/huron/core/metastore/lake/role_mappings.py`: the `InMemoryRoleMappings` half (a mixin over
    the root's `LakeTables`): `roles_for_groups(groups)` returns one `Grant` per `group_role_map` row
    whose group is in `groups`, carrying the catalog's id and name, in any order; an empty `groups`
    returns `()`; a group with no row contributes nothing. The fake row holds the catalog as a
    `CatalogRef`, because `lake.catalogs` has no fake half before M7; that is equivalent to DT-4's join
    because catalogs refuse a name change and a delete (DT-17 triggers). M7.6 replaces the reference with
    the catalog id joined to its catalogs half and adds the writer methods; M8 adds
    `PostgresRoleMappings` to this module.
  - `src/huron/core/metastore/lake/signing_keys.py`: the `InMemorySigningKeys` half:
    `unexpired(retired_after)` returns every record with no `retired_at` or a `retired_at` after
    `retired_after`, ascending `active_from`. M7 adds the writer methods and M8 `PostgresSigningKeys`.
- Modify:
  - `src/huron/core/lake/ports.py`: `LakeStore` gains the bases `RoleMappingReader` and
    `SigningKeyReader` (imported from `huron.core.security.broker`).
  - `src/huron/core/metastore/lake/memory.py`: `InMemoryLakeStore` composes the two halves;
    `group_role_map` stays keyed by `(ldap_group, catalog id or None)`, one role per group per scope
    (DT-4's `UNIQUE NULLS NOT DISTINCT` key).
  - `tests/lake_store_contract.py`: a `LakeSeed` Protocol (`ldap_group(name, gid)`,
    `role_mapping(group, catalog: CatalogRef | None, role)`, `signing_key(record, created_by)`) and its
    `MemorySeed(store)`, the one place tests write the fake's tables directly (M8 adds the Postgres
    seeder); the role-mapping scenarios (a catalog row and an all-catalog row returned with their
    catalog id and name; unknown and unasked groups contribute nothing; an empty set returns `()`; the
    union over several groups) and the signing-key scenarios (the `unexpired` filter at, before and
    after a `retired_at`, the open-ended row included, ascending `active_from`, records equal to the
    seeded `SigningKeyRecord`). Until M7.6 a catalog-scoped `role_mapping` takes a bare `CatalogRef`
    and seeds no catalog. M7.6 joins the fake's `group_role_map` to its catalogs table and adds
    `LakeSeed.catalog(ref)`; from then a catalog-scoped mapping needs its catalog seeded first. M7.6
    moves these scenarios, `tests/unit/test_lake_access.py` and `tests/unit/test_token_exchange.py`
    (M5.6) to that order.
  - `tests/unit/test_lake_memory_store.py`: runs the new scenarios against `InMemoryLakeStore`; the
    structural-conformance case covers the two new bases; a case asserts that no two halves composed
    into `InMemoryLakeStore` define the same public name (DT-17 "Name collisions").
- Design: DT-17 design → "DT-17 target module layout" (halves, "Name collisions"), "DT-17 port →
  adapter → fake" (rows `RoleMappingReader` and `SigningKeyReader`), "DT-17 resolved disagreements
  between sections" (D-2); DT-4 design → "`broker/ladder.py`: roles, grants and the mapping port"
  (`roles_for_groups` contract), "DT-4 open questions" (OQ-4.2); DT-5 design → "`broker/keys.py`: keys,
  the ring, the source and the rotation rule" (`SigningKeyReader.unexpired` contract). DT-17's
  per-area scenario functions in one module supersede DT-4's `tests/lake_role_mapping_contract.py`
  and DT-5's `tests/lake_signing_key_contract.py`, which are not created.
- Verification:
  - The plan-wide gate; `uv run lint-imports` keeps 17 contracts.
  - `uv run pytest tests/unit/test_lake_memory_store.py` passes.
  - `test -e tests/lake_role_mapping_contract.py || test -e tests/lake_signing_key_contract.py` exits
    non-zero (neither superseded module exists).
  - `role_mappings.py`, `signing_keys.py` and the modified `memory.py` and `ports.py` at 100 % line
    coverage in the unit run.
- Dependencies: M4.1.
- Decisions: OQ-4.2 (settled, owner decision 12)
- Status: pending

### M4.3 `Actor` and `LakeAuthentication`

- Intent: turn a presented Huron JWT into the immutable, request-scoped `Actor` every lake operation
  receives, verifying the token before the store is touched and re-mapping the signed `groups` through
  the current mappings on every call, never reading the `roles` claim and never caching across calls.
- Delete: none.
- Create:
  - `src/huron/core/security/broker/access.py`: frozen `Actor(subject, groups, grants)`;
    `LakeAuthentication(verifier: HuronTokenVerifier, mappings: RoleMappingReader)` with
    `async authenticate(token) -> Actor` in DT-4's order (verify, then one `roles_for_groups` call,
    then `Grants(claims.sub, rows)`); store failures propagate unchanged and never become empty grants.
  - `tests/unit/test_lake_access.py`: real tokens from `tests/lake_tokens.py` (`refreshed_test_keys`,
    `mint`) through the production `HuronTokenVerifier`, and `InMemoryLakeStore` seeded through
    `MemorySeed` as the `RoleMappingReader` (D-2; a catalog-scoped row seeded here gets its
    `LakeSeed.catalog` call in M7.6, see M4.2). Cases: a valid token gives the token's `sub` and
    `groups` and the seeded grants; unknown groups give a falsy `Grants`; DT-4's "Emptied mapping"
    (the seeded row removed between two `authenticate` calls with the same unexpired token: the second
    actor holds no role); "`roles` claim ignored" (a token minted with a `platform_owner` grant over an
    empty mapping yields a falsy `Grants`); "Store outage" (a test-local reader raising
    `ConnectionError` propagates it); "Invalid token" (expired, and signed by another key: `AuthError`
    and zero reader calls, counted by a test-local wrapper around the fake); exactly one reader call per
    `authenticate`.
- Modify:
  - `src/huron/core/security/broker/__init__.py`: exports `Actor`, `LakeAuthentication`.
  - `tests/lake_store_contract.py`: `LakeSeed.remove_role_mapping(group, catalog)` and its
    `MemorySeed` implementation (DT-4's "the fake's rows are cleared").
- Design: DT-4 design → "DT-4 decisions" (L-7), "`broker/access.py`: the actor per request", "Tests
  this design requires" (rows Emptied mapping, `roles` claim ignored, Store outage, Invalid token,
  Unknown groups); DT-1 design → "DT-1 interfaces and contracts" → "`huron.core.security.broker`: the
  request-time actor"; DT-17 design → "DT-17 resolved disagreements between sections" (D-2). The
  `require_on_catalog`/`require_on_collection` rows of DT-4's table belong to M7 and M11, and the
  "Below minimum" row to M13.
- Verification:
  - The plan-wide gate; `uv run lint-imports` keeps 17 contracts.
  - `uv run pytest tests/unit/test_lake_access.py tests/unit/test_lake_memory_store.py` passes.
  - `rg -n "\.roles\b" src/huron/core/security/broker/access.py` prints nothing (Owner decision 7: the
    claim is never read here); `rg -n "monkeypatch" tests/unit/test_lake_access.py` prints nothing.
  - `access.py` at 100 % line coverage in the unit run.
- Dependencies: M4.2.
- Status: pending

## Milestone 5 — Identity mocks and the token exchange

Intent: build the local stand-ins for the two company services first, then the production code that
talks to them, proven against those stand-ins with no bypass. DT-22's `tests/fakes/` package holds the
one identity fixture (`identities.yaml`), the LDAP-groups fake (`ldap_groups.py`, standalone so compose
can serve it from M9) and the fake company issuer (`oidc_issuer.py`); `tests/conftest.py` hands both
fakes and one shared clock to every tier, and `scripts/keycloak/company-realm.json` lands beside the
fixture it is pinned to (compose keeps importing the `huron` realm until M9's switch).
`DependencyUnavailable` then moves into foundation so `security` can raise it; the asynchronous
`CompanyTokenVerifier` (lazy discovery, a per-`kid` cache with a refetch floor, the injected clock)
replaces `JwksVerifier` and the legacy company bearer on `/api/v1` is re-wired over it, deleting the
code D2-4 left dead; finally the group directory (`GroupDirectory`, `HttpGroupDirectory`,
`parse_groups_response`) and the stateless `TokenExchange` workflow. No route, no `ApiSettings` field
and no lake wiring changes here: `POST /auth/exchange`, the settings diff, the compose and `dev.env`
switch and `lake_settings()` are M9's. The only composition changes are the legacy bearer's: `create_app`
loses `oidc_verify` and gains `company_idp_transport` and `clock`. Import-linter stays at 17 contracts
throughout.

### M5.1 The shared identity fixture and the groups fake

- Intent: give every tier one definition of the mock people and their groups, and an in-process groups
  endpoint that serves exactly the v1 shape the production parser will accept, with failure injection
  controlled from Python only.
- Delete: none.
- Create:
  - `tests/fakes/__init__.py` (empty) and `tests/fakes/identities.yaml` (DT-22's fixture verbatim:
    `version: 1`, `organization: Huron Development`, users `karl`, `sam`, `rita` with their fixed ids,
    names, emails and groups).
  - `tests/fakes/ldap_groups.py`: `DEFAULT_IDENTITIES`, `GroupsFailure`, frozen `FakeUser` and
    `Identities` (`load` enforcing DT-22's invariants with a `ValueError` naming the entry, `with_user`,
    `user`), `FakeGroupDirectory` (`app`, `inject(failure, *, username=None)` with per-user precedence,
    `requests`; one `threading.Lock` over all state) and `app_from_environment()` (reads
    `FAKE_IDENTITIES`, else `DEFAULT_IDENTITIES`). One route, `GET /users/{username}/groups`: 200
    `{"groups": [...]}` sorted, 404 `{"detail": "unknown user"}`; injected statuses, `"timeout"` and
    `"unreachable"` raised as `httpx.ReadTimeout`/`httpx.ConnectError` from the route, `"malformed"`
    as `{"groups": "not-a-list"}`; every header ignored. Imports only the standard library,
    `starlette`, `yaml` and `httpx`; the username rule is restated as a pattern literal.
  - `tests/conftest.py`: fixtures `clock` (the one `FakeClock` from `tests/unit/support.py`, at
    `tests/lake_tokens.py`'s `TEST_EPOCH`), `identities`, `fake_groups` and `fake_groups_transport`
    (`httpx.ASGITransport(app=fake_groups.app)`), visible to the unit, contract and integration tiers.
  - `tests/unit/test_fake_ldap_groups.py`: DT-22's row: the 200 body and its order; 404 for an unknown
    user; `karl%40corp` decoded after `with_user`; every injection (`404`, `500`, `401`, `"timeout"`,
    `"unreachable"`, `"malformed"`), global and per user, cleared by `None`; `requests` order; one
    instance reached by an `httpx.AsyncClient` and a `TestClient` in one test; `app_from_environment`
    honouring `FAKE_IDENTITIES`.
  - `tests/unit/test_fake_identities.py`: `Identities.load` refusing a duplicate `id`, a duplicate
    `username`, a username outside the pattern, an empty, over-256-character or control-character group,
    an unknown or missing key and a wrong `version`; `test_src_never_imports_tests` (an AST walk of every
    module under `src/huron` failing on `import tests…` or `from tests…`); an AST check that
    `ldap_groups.py` imports only `sys.stdlib_module_names`, `starlette`, `yaml` and `httpx`.
- Modify: none.
- Design: DT-22 design → "DT-22 decisions" (L-33, One fixture, Users, Fake issuer scope, Controls, No
  bypass), "DT-22 target layout", "DT-22 the shared fixture and the `company` realm" (the fixture),
  "DT-22 interfaces and contracts" → "`tests/fakes/ldap_groups.py`: the identities value and the groups
  fake", "`tests/conftest.py` and `tests/unit/support.py`: how tests obtain the fakes" (the
  `tests/conftest.py` half; `lake_settings()` is M9's), "The no-bypass rule", "DT-22 tests this design
  requires", "DT-22 handoffs" (build order); DT-6 design → "DT-6 open questions" (OQ-6.1).
- Verification:
  - The plan-wide gate; `uv run lint-imports` keeps 17 contracts.
  - `uv run pytest tests/unit/test_fake_ldap_groups.py tests/unit/test_fake_identities.py` passes.
  - `uv run python -I -c "import sys; sys.path.insert(0, 'tests/fakes'); import ldap_groups; print(type(ldap_groups.app_from_environment()).__name__)"`
    prints `Starlette` (the module loads standalone, as compose's `uvicorn --app-dir /fakes` will).
  - `uv run pytest -m "contract or integration" --collect-only -q` exits 0 (the root conftest imports
    in every tier).
- Dependencies: M4.3; M3.3 (`TEST_EPOCH`).
- Decisions: OQ-6.1 (settled, owner decision 12)
- Status: pending

### M5.2 The fake company issuer: discovery, keys and ID tokens; the `company` realm

- Intent: give server-side tests a company IdP whose discovery document, JWKS and ID tokens have the
  development Keycloak's structure, driven by the shared clock, with key rotation, forged tokens and
  failure injection on demand, and pin the hand-written Keycloak realm to the same fixture.
- Delete: none.
- Create:
  - `tests/fakes/oidc_issuer.py` (first half): `Endpoint`, `IdpFailure`, `FakeCompanyIdp(identities,
    clock, *, issuer="https://idp.test/realms/company", client_id="huron-cli", token_ttl, device_ttl,
    interval, revocation)` with read-only `issuer` and `client_id`, `app`, and the routes under the
    issuer's path: the discovery document with every member of DT-22's route table (the endpoints it
    names for authorize, token, device and revocation are served from M5.3; `revocation_endpoint`
    omitted when `revocation=False`) and `…/certs` (non-retired keys, public members plus `kid`, `kty`,
    `alg`, `use: "sig"`); the default RS256 key generated once per process (`functools.cache`, `kid`
    `fake-rs256-1`), `rotate_key(*, retire_previous=False)` (P-256 keys `fake-es256-<n>`),
    `id_token(username, *, claims=None, drop=(), kid=None, forged=False)` (DT-22's claim set: `aud`
    the client id as a string, `sub` the fixture `id`, `preferred_username`, names, `email`,
    `organization`, `sid`, `typ: "ID"`, never `groups`), `inject(endpoint, failure)` (statuses,
    `"timeout"`, `"unreachable"`, `"malformed"` as the body `not json`, `"issuer_mismatch"` on
    `"discovery"` only, else `ValueError`) and `hits`. All state behind one `threading.Lock`; times only
    from the injected clock. May import `jwt`, `cryptography` and `tests.fakes.ldap_groups`.
  - `scripts/keycloak/company-realm.json`: DT-22's `company` realm (display name, `sslRequired: none`,
    `loginWithEmailAllowed: false`, `accessTokenLifespan: 300`, `oauth2DeviceCodeLifespan: 600`,
    `oauth2DevicePollingInterval: 5`, `revokeRefreshToken: true`, `refreshTokenMaxReuse: 0`, no realm
    roles, no client scopes; the public `huron-cli` client with standard flow and the device grant on,
    implicit, direct-access and service accounts off, `pkce.code.challenge.method: S256`,
    `redirectUris: ["http://127.0.0.1/*"]` and one `oidc-hardcoded-claim-mapper` for `organization`;
    users `karl`, `sam`, `rita` with the fixture's ids, names and emails, `emailVerified: true` and the
    `<username>-dev-password` development literal). `docker-compose.yml` keeps importing
    `huron-realm.json` until M9 swaps the mount and deletes the old realm. No `huron-integration`
    client: OQ-22.2 belongs to M9/M15, which add it and its drift clause.
  - `tests/unit/test_fake_company_idp.py` (first half): the discovery members and the
    `revocation=False` variant; the JWKS carrying public members only (no `d`, `p`, `q`); ID-token
    claims verified with PyJWT against the served JWKS (`aud`, `sub` equal to the fixture `id`, no
    `groups`, `organization`); `claims`/`drop` overrides; `rotate_key` with and without retiring the
    previous key; `forged=True` failing verification; every `inject` kind on `discovery` and `jwks`,
    `"issuer_mismatch"` refused elsewhere; the clock set to 2030 giving `iat` in 2030.
- Modify:
  - `tests/conftest.py`: fixtures `fake_issuer` and `fake_issuer_transport`.
  - `tests/unit/test_fake_identities.py`: realm drift: `company-realm.json`'s users equal the fixture on
    `id`, `username`, `firstName`/`given_name`, `lastName`/`family_name` and `email`; no realm role, no
    `oidc-usermodel-realm-role-mapper` and no claim named `groups`; `huron-cli`'s `publicClient`, its
    device-grant attribute, `pkce.code.challenge.method == "S256"`, `redirectUris ==
    ["http://127.0.0.1/*"]` and `directAccessGrantsEnabled is False`; the `organization` mapper's
    `claim.value` equal to the fixture's `organization`; `revokeRefreshToken` set and
    `refreshTokenMaxReuse == 0`; no client other than `huron-cli`.
- Design: DT-22 design → "DT-22 decisions" (L-32, C-12, `huron-cli` client, `organization`, Fake issuer
  scope), "DT-22 the shared fixture and the `company` realm" (realm table), "DT-22 interfaces and
  contracts" → "`tests/fakes/oidc_issuer.py`: the fake company issuer" (routes discovery and certs, ID
  token, Keys, Failure injection, Invariants and lifecycle), "DT-22 tests this design requires"
  (`test_fake_company_idp.py`, the realm-drift clauses), "DT-22 open questions" (OQ-22.1); DT-20 design
  → "DT-20 handoffs" (row DT-22, OQ-20.3).
- Verification:
  - The plan-wide gate; `uv run lint-imports` keeps 17 contracts.
  - `uv run pytest tests/unit/test_fake_company_idp.py tests/unit/test_fake_identities.py` passes.
  - `uv run python -m json.tool scripts/keycloak/company-realm.json > /dev/null` exits 0;
    `git diff --exit-code docker-compose.yml dev.env Makefile scripts/check-stack.sh` exits 0 (the
    switch is M9's).
- Dependencies: M5.1.
- Decisions: OQ-20.3 (settled, owner decision 12)
- Decisions: OQ-22.1 (settled, owner decision 12)
- Status: pending

### M5.3 The fake company issuer: authorize, token, device and revocation

- Intent: complete the fake issuer with the interactive protocol the CLI's login will drive in M10
  (authorization code with PKCE on a loopback redirect, refresh rotation with reuse detection, the
  device grant paced by the clock, and revocation), so DT-22's build order holds: the fakes exist, whole
  and tested, before any consumer.
- Delete: none.
- Create: none.
- Modify:
  - `tests/fakes/oidc_issuer.py` (second half): `DeviceStep`, `Approve`, `login_as` (default `karl`);
    the routes `…/auth` (400 without redirect for an unknown client or a redirect that is not
    `http://127.0.0.1:<port>/<path>`; a 302 `error=invalid_request` without a `code_challenge` or with a
    method other than `S256`; `deny_authorize`; otherwise a single-use 60-second code bound to the
    client, redirect, challenge, `nonce` and `login_as`, redirected with `code`, echoed `state` and
    `iss`), `…/auth/device` (challenge required, as the realm requires under OQ-22.1 (a)), `…/token`
    (`authorization_code`, whose `id_token` carries the code's `nonce` when the authorize request sent
    one and no `nonce` claim otherwise; `refresh_token` with family rotation, a new `id_token` without
    `nonce`, and family revocation on reuse;
    `urn:ietf:params:oauth:grant-type:device_code` with scripted steps first and RFC 8628 §3.5 by the
    clock otherwise; `invalid_client` for a foreign `client_id`; `unsupported_grant_type`) and
    `…/revoke` (always 200, recording, a refresh token revoking its family); `approve`,
    `script_device`, `deny_authorize`, `revoked`. Form bodies are parsed with
    `urllib.parse.parse_qs(await request.body())` (`python-multipart` is not installed, R22-2). A user
    named in `approve`, `Approve` or `login_as` must exist, else `KeyError`.
  - `tests/unit/test_fake_company_idp.py` (second half): DT-22's remaining cases: authorize (foreign
    redirect, a `localhost` redirect refused, missing PKCE, `deny_authorize`, success with `state` and
    `iss`); code reuse, an expired code, a wrong verifier and a wrong `redirect_uri` each `invalid_grant`;
    device (challenge required, `script_device` steps in order, natural `slow_down` with the interval
    growing by 5 s, `expired_token` after `device_ttl`, `approve` then tokens then `invalid_grant`);
    refresh rotation, and reuse revoking the family; the `nonce` echo, each `id_token` verified with
    PyJWT against the served JWKS (DT-22 test table `aud`, `nonce`; DT-19 handoff row DT-22): the
    `authorization_code` grant's `id_token` carries the authorize request's `nonce`, an authorize
    without `nonce` gives an `id_token` with no `nonce` claim, and the `refresh_token` grant's new
    `id_token` carries no `nonce`; revocation recording; every `inject` kind on
    `authorize`, `token`, `device` and `revoke`; one instance reached by an `httpx.AsyncClient` and a
    `TestClient` in one test.
- Design: DT-22 design → "DT-22 interfaces and contracts" → "`tests/fakes/oidc_issuer.py`: the fake
  company issuer" (routes authorize, device, token, revoke), "DT-22 tests this design requires"
  (`test_fake_company_idp.py`), "DT-22 open questions" (OQ-22.1), "DT-22 handoffs" (row DT-19); DT-19
  design → "DT-19 handoffs" (row DT-22: what the fake must provide).
- Verification:
  - The plan-wide gate; `uv run lint-imports` keeps 17 contracts.
  - `uv run pytest tests/unit/test_fake_company_idp.py` passes; no case sleeps on the wall clock
    (`rg -n "time\.sleep|asyncio\.sleep\([1-9]" tests/unit/test_fake_company_idp.py tests/fakes`
    prints nothing).
- Dependencies: M5.2.
- Decisions: OQ-22.1 (settled, owner decision 12)
- Status: pending

### M5.4 `DependencyUnavailable` in foundation and the company-token verifier

- Intent: let `security` report an unreachable remote party with the API's existing 503 code, and verify
  company tokens without blocking the event loop: discovery and the JWKS fetched lazily through an
  injected `httpx.AsyncClient`, keys cached by `kid` with a refetch floor, every time rule on the
  injected clock, 401 for a token that cannot be trusted and 503 for an IdP that cannot be reached.
- Delete: none.
- Create:
  - `src/huron/core/security/broker/exchange.py` (first half): `COMPANY_USERNAME`, `JWKS_TTL`,
    `JWKS_REFETCH_FLOOR`, `COMPANY_ALGORITHMS` and `CompanyTokenVerifier(http, *, issuer, audiences,
    clock)` (construction `ValueError`s; nothing fetched at construction; discovery cached for the
    process under one `asyncio.Lock`; `verify` in DT-6's order, reusing M3.4's time-rule helper with
    `VERIFY_LEEWAY`; claims returned unchanged; `AuthError` for every untrusted token;
    `DependencyUnavailable` with `context = {"dependency": "company_idp", "reason": …}` for `timeout`,
    `unreachable`, `status`, `malformed` and `issuer_mismatch`, keeping any cache it already holds; the
    caller's client never closed).
  - `tests/unit/test_company_tokens.py`: the verifier over `httpx.AsyncClient(transport=
    fake_issuer_transport)` and the root `clock`: every 401 row of DT-6's failure table (malformed JWS,
    no `kid`, `alg` outside RS256/ES256, unknown `kid` after a refetch, bad signature via
    `forged=True`, wrong `iss`, `aud` outside `audiences`, expired, `iat` in the future, each required
    claim dropped); the five 503 reasons through the fake's injection on discovery and JWKS, with
    `context`; a cached key verifying while the fake is down; a rotated `kid` triggering exactly one
    refetch and a second unknown `kid` inside `JWKS_REFETCH_FLOOR` none (`fake_issuer.hits`), another
    after the floor; a refetch after `JWKS_TTL`; concurrent first calls making one discovery fetch; an
    ES256 key from `rotate_key` accepted; the client still open after use; construction refusals.
- Modify:
  - `src/huron/core/foundation/errors.py`: `DependencyUnavailable(DomainError)` (`DEPENDENCY_UNAVAILABLE`,
    503, `retry_after = 30`; docstring covering readiness probes and remote dependencies, `context`
    naming `dependency` and `reason`), joining foundation's `ERROR_CODES`.
  - `src/huron/applications/api/errors.py`: the class and its code leave the module and its
    `ERROR_CODES` (moved, not copied; no re-export); module docstring says HTTP parsing only.
  - `src/huron/applications/api/app.py`: `/readyz` imports the class from foundation; its
    `context={"checks": …}` shape is unchanged.
  - `src/huron/core/security/broker/__init__.py`: exports `COMPANY_USERNAME`, `CompanyTokenVerifier`.
  - `design/api.html` §7: the `DEPENDENCY_UNAVAILABLE` row re-worded for its raisers at this point (the
    `/readyz` database probe with `checks`; `company_idp` with `dependency`, `reason`; retry after
    `Retry-After`); DT-18's final wording lands as its later raisers do.
  - `tests/unit/test_api_errors.py`: imports the class from foundation and asserts `retry_after == 30`;
    `tests/unit/test_api_app.py`: the `/readyz` 503 cases also assert `Retry-After: 30`.
  - `tests/unit/test_fake_identities.py`: `ldap_groups.py`'s username pattern literal equals
    `COMPANY_USERNAME.pattern`.
- Design: DT-6 design → "DT-6 decisions" (C-1, Discovery timing, `DependencyUnavailable`), "DT-6 target
  module layout", "DT-6 interfaces and contracts" → "`broker/exchange.py`: the company-token
  verifier", "DT-6 failure behaviour (`POST /auth/exchange`)" (verifier rows), "DT-6 tests this design
  requires" (`test_company_tokens.py`); DT-5 design → "DT-5 the Huron JWT: claims and validation on
  verify" (`VERIFY_LEEWAY`, R5-5); DT-18 design → "DT-18 error-code table rows (`design/api.html` §7,
  ready to paste)" (the `DEPENDENCY_UNAVAILABLE` line).
- Verification:
  - The plan-wide gate; `uv run lint-imports` keeps 17 contracts (`httpx` and `jwt` stay inside
    `security`, contract 11).
  - `uv run pytest tests/unit/test_company_tokens.py tests/unit/test_api_errors.py tests/unit/test_error_contract.py tests/unit/test_api_app.py tests/unit/test_fake_identities.py`
    passes; `test_error_contract.py` finds `DEPENDENCY_UNAVAILABLE` declared exactly once.
    `make docs` passes.
  - `rg -n "DependencyUnavailable" src/huron/applications/api/errors.py` and
    `rg -n "api\.errors import .*DependencyUnavailable|from \.errors import DependencyUnavailable" src tests`
    print nothing; `rg -n "monkeypatch" tests/unit/test_company_tokens.py` prints nothing.
  - `exchange.py` and the modified `foundation/errors.py`, `applications/api/errors.py` and `app.py`
    at 100 % line coverage in the unit run.
- Dependencies: M5.3; M3.4.
- Status: pending

### M5.5 The legacy company bearer over `CompanyTokenVerifier`

- Intent: keep the company bearer JWT, the only production way into the legacy `/api/v1` after D2-4,
  re-wired over the new verifier, naming the principal by the company username (the `subject_claim`
  value fullmatched against `COMPANY_USERNAME`, as in the exchange; groups stay the token's own claim
  until M9.1 wires the group directory) (owner decision 11, B-28), stop contacting the IdP at startup, and
  delete what D2-4 left dead: the
  thread-blocking `JwksVerifier`, the server-side discovery client and the code-flow user upsert.
- Delete: none (whole files). If M1 left `tests/unit/test_api_oidc.py` without a case, this task fills it
  as below rather than the orchestrator removing it.
- Create: none.
- Modify:
  - `src/huron/core/security/oidc.py`: only `OidcResolver` remains; its `verify` is
    `Callable[[str], Awaitable[Mapping[str, object]]]` and `resolve` awaits it; it takes a keyword-only
    `subject_claim: str` with no `"sub"` default and names the principal by that claim's value,
    fullmatched against `COMPANY_USERNAME` (401 otherwise) (owner decision 11, B-28); `JwksVerifier`,
    `OidcClient` (what D2-4 left: `discover`, `provider`),
    `OidcProviderConfig`, `OidcUser`, `_REQUIRED_DISCOVERY_FIELDS` and `_validate_discovery_document`
    are deleted; the module docstring describes the legacy bearer only.
  - `src/huron/applications/api/app.py`: `_configure_oidc` builds, when `settings.oidc` is set,
    `httpx.AsyncClient(transport=company_idp_transport)` (httpx's default 5 s timeout until M9's
    `company_idp.timeout_seconds`), `CompanyTokenVerifier(http, issuer=…, audiences=frozenset({audience
    or client_id}), clock=clock)` and `OidcResolver(verifier.verify, groups_claim=…,
    subject_claim="preferred_username")`, contacting nothing (owner decision 11, B-28); `create_app`
    loses `oidc_verify` and gains `company_idp_transport: httpx.AsyncBaseTransport | None = None` and
    `clock: Clock | None = None` (`None` → `SystemClock()`;
    DT-22 has the test's clock reach `create_app`'s composition but names no seam, and the fake issuer
    and the app must share one clock or they reject each other's tokens); the lifespan's `finally` still
    closes the client; docstrings follow.
  - `src/huron/applications/api/runtime.py`: the `ApiRuntime` docstring (the resolver is `None` only when
    no company IdP is configured; M9 makes it required).
  - `src/huron/core/security/principals.py`: `PrincipalStore.upsert_oidc_user` and its `OidcUser` import
    leave the port; `src/huron/core/metastore/principals.py` and `memory_principals.py`: their
    `upsert_oidc_user`. `PrincipalSubjectExists` is deleted too if `rg -n "raise PrincipalSubjectExists" src`
    then finds no raiser.
  - `scripts/render_uml_atlas.py:110`: the search box's placeholder names `OidcResolver` instead of
    `OidcClient`, because DT-6's closing check covers `scripts/` (the atlases themselves are T-docs-Z's,
    M19).
  - Tests: `tests/unit/test_auth_oidc.py` loses the `private_key`, `jwks_document`, `serve_jwks` and
    `provider` fixtures, `_id_token` and every `JwksVerifier` and discovery case (their behaviour is
    `test_company_tokens.py`'s); its `OidcResolver` cases pass an `async def` stub (they test claim
    mapping, not verification). `tests/unit/test_api_oidc.py`: the cases M1 left are replaced by the
    legacy bearer over `create_app(…, company_idp_transport=fake_issuer_transport, clock=clock)`
    with `oidc` settings naming `fake_issuer.issuer`: `fake_issuer.id_token("karl")` on a legacy route
    resolves to the principal `karl`, not karl's fixture `id` (OQ-6.3 (b), owner decision 11, B-28); a
    `forged=True`
    token answers 401 with `WWW-Authenticate: Bearer`; an unknown `kid` while discovery is injected
    `"unreachable"` answers 503 `DEPENDENCY_UNAVAILABLE` with `Retry-After: 30`; its `private_key`,
    `serve_jwks`, `_id_token` and `_mock_discovery` helpers go. `tests/unit/test_api_app.py`: the
    discovery-at-startup cases become "startup makes no request to the IdP" (`fake_issuer.hits` all
    zero after the lifespan starts) and "the company client closes at shutdown and when startup fails
    after it opened" (a transport subclass recording `aclose`); the injected-verifier case and both
    `monkeypatch.setattr(httpx, "AsyncClient", …)` uses are deleted. `tests/unit/test_authorization_credentials.py`
    and `tests/unit/test_security_authentication.py`: `OidcResolver` stubs become `async def` (they test
    credential precedence). `tests/unit/test_auth_principals.py` and `tests/contract/test_auth_store.py`:
    the `upsert_oidc_user` cases and `OidcUser` imports go. (`OidcNotConfigured`, its row and its cases
    left with their only raiser in M1.6.)
  - `AGENTS.md`: B-9's last two sentences ("Two checks enforce this: …") from "DT-25 `AGENTS.md`: the
    binding rules, worded", now that both checks hold: M5.1's `test_src_never_imports_tests` and the
    no-bypass `rg` below, which prints nothing from this task on (M0.2 landed B-9's rule sentences).
  - `design/roadmap.html`: integration milestone 12 (`:664-668` at `fa51f46`) loses "OIDC upsert-on-login"
    with `upsert_oidc_user` (plan-wide "No backwards compatibility" rule).
- Design: DT-6 design → "DT-6 decisions" (C-1, Discovery timing, L-5), "DT-6 the L-5 reading and the
  credential ledger" (rows `OidcClient` discovery, `JwksVerifier`, `OidcResolver`, `OidcUser`,
  `OidcNotConfigured`, Company bearer on legacy routes), "DT-6 interfaces and contracts" → "`oidc.py`:
  the legacy bearer, re-wired", "Settings diff, startup refusals and composition" (the
  `company_idp_transport` seam and the company client only; the settings diff is M9's), "DT-6 failure
  behaviour (`POST /auth/exchange`)" (the legacy-bearer paragraph), "DT-6 deletions" (owner decision 11,
  B-28: no OQ-6.3 pointer); DT-22 design → "DT-22 deletions" (the test helpers), "The no-bypass rule",
  "`tests/conftest.py` and `tests/unit/support.py`: how tests obtain the fakes" (`clock`).
- Verification:
  - The plan-wide gate, the contract tier included (`test_auth_store.py` changed); `uv run lint-imports`
    keeps 17 contracts.
  - `uv run pytest tests/unit/test_auth_oidc.py tests/unit/test_api_oidc.py tests/unit/test_api_app.py tests/unit/test_authorization_credentials.py tests/unit/test_security_authentication.py tests/unit/test_auth_principals.py tests/unit/test_error_contract.py`
    passes.
  - `rg -n "JwksVerifier|PyJWKClient|OidcClient|OidcProviderConfig|OidcUser|upsert_oidc_user|OidcNotConfigured|OIDC_NOT_CONFIGURED|oidc_verify|_REQUIRED_DISCOVERY_FIELDS|_validate_discovery_document" src tests scripts`
    prints nothing (DT-6's closing check, less the names M9 removes);
    `uv run python -m py_compile scripts/render_uml_atlas.py` exits 0 (the script has no unit tests).
  - `rg -n "monkeypatch\.setattr\((jwt|httpx|.*PyJWKClient|.*(Verifier|GroupDirectory|OidcProvider))" tests`
    prints nothing (DT-22's no-bypass closing check).
  - `rg -n 'test_src_never_imports_tests' AGENTS.md` prints one line; `git diff --check` prints nothing.
  - Every modified source file at 100 % line coverage in the unit run; `metastore/principals.py` in the
    "unit or contract" run. The floor moves only by the re-baseline rule (deleted covered statements).
- Skills: `writing-for-agents` (`AGENTS.md`).
- Dependencies: M5.4; M1 (D2-4's state of `oidc.py`, `app.py` and the OIDC tests).
- Status: pending

### M5.6 The group directory and the token exchange

- Intent: complete the broker's server half: one adapter that asks the company groups endpoint for a
  user's groups (the only code that knows the endpoint's JSON shape), and the stateless exchange that
  turns a verified company ID token into a Huron JWT carrying the user's verbatim username, every
  directory group and the roles current at that instant, writing nothing.
- Delete: none.
- Create:
  - `src/huron/core/security/broker/groups.py`: the `GroupDirectory` Protocol (`groups_for(username) ->
    frozenset[str] | None`, `None` only for an unknown user); `HttpGroupDirectory(http, *,
    url_template)` (construction `ValueError` unless an absolute `http(s)` URL with exactly one
    `{username}` outside the host; the name inserted with `urllib.parse.quote(username, safe="")`; one
    `GET` with `Accept: application/json`; 200 → `parse_groups_response`, 404 → `None`, any other
    status, a timeout, any other transport error and a refused body → `DependencyUnavailable` with
    `dependency="group_directory"` and `reason` `status` (with `status`), `timeout`, `unreachable`,
    `malformed`; no retry); `parse_groups_response(body)` (exactly `{"groups": [<string>, …]}`, other
    top-level keys ignored, each element non-empty, at most 256 characters and free of control
    characters, duplicates collapsed, `ValueError` naming the offending element).
  - `tests/unit/test_group_directory.py`: parser vectors (valid, duplicates, non-object body, non-list,
    non-string, empty string, over 256 characters, control character, extra keys ignored); status
    mapping (200, 404, 500, 401) and the `timeout`, `unreachable` and `malformed` injections through
    `fake_groups_transport`; `karl@corp` (added with `Identities.with_user`) arriving decoded; template
    refusals.
  - `tests/unit/test_token_exchange.py`: `TokenExchange` with the real `CompanyTokenVerifier` over
    `fake_issuer_transport`, `HttpGroupDirectory` over `fake_groups_transport`, `InMemoryLakeStore` as
    the `RoleMappingReader` seeded through `MemorySeed` (a catalog-scoped row seeded here gets its
    `LakeSeed.catalog` call in M7.6, see M4.2), a `HuronTokenIssuer` over
    `refreshed_test_keys(clock)` and the root `clock`: the happy path for `karl` (`sub` is `karl`, the
    `preferred_username`, not the fixture UUID; `groups` sorted; roles from the seeded mappings;
    `exp == iat + ttl`); a user with no groups and one with only unmapped groups, both issued with
    `roles == []`; an unknown user and a missing or non-matching `subject_claim` value (`AuthError`
    whose message names the claim, not its value); the company token's own `groups` claim ignored; an
    emptied mapping issuing `roles == []`; `SigningKeyUnavailable` from a stale ring propagating; a
    directory outage giving `DependencyUnavailable` and no token; a refused company token making no
    directory request (`fake_groups.requests`); two exchanges making two directory requests (no cache);
    the `auth.exchange` record's fields (`caplog`) and the token never logged; OQ-6.2 (a): a user with
    101 groups gets all 101 signed and one warning.
- Modify:
  - `src/huron/core/security/broker/exchange.py` (second half): `TokenExchange(verifier, directory,
    mappings, issuer, *, subject_claim)` with `exchange(company_token) -> IssuedToken` in DT-6's five
    steps, each failing before the next starts; no store write, no cache, no retry; one structured
    `auth.exchange` record through the standard library `logging` (`subject`, `outcome`,
    `group_count`, `role_count`, `kid`), plus a warning when the directory returns more than 100 groups.
  - `src/huron/core/security/broker/__init__.py`: exports `GroupDirectory`, `HttpGroupDirectory`,
    `parse_groups_response`, `TokenExchange`.
  - `tests/unit/test_fake_identities.py`: for every fixture user, `parse_groups_response` on the groups
    fake's body returns the fixture's groups.
- Design: DT-6 design → "DT-6 decisions" (L-3, L-1, Groups source, G-25, G-30), "DT-6 interfaces and
  contracts" → "`broker/groups.py`: the group directory", "`broker/exchange.py`: the exchange
  workflow", "DT-6 failure behaviour (`POST /auth/exchange`)" (directory, mapping and signing rows),
  "DT-6 tests this design requires" (`test_group_directory.py`, `test_token_exchange.py`), "DT-6 data
  flow", "DT-6 open questions" (OQ-6.1, OQ-6.2); DT-22 design → "DT-22 handoffs" (row DT-6); DT-17
  design → "DT-17 resolved disagreements between sections" (D-2: the exchange reads mappings from the
  lake store).
- Verification:
  - The plan-wide gate; `uv run lint-imports` keeps 17 contracts.
  - `uv run pytest tests/unit/test_group_directory.py tests/unit/test_token_exchange.py tests/unit/test_fake_identities.py`
    passes.
  - `rg -n "monkeypatch" tests/unit/test_group_directory.py tests/unit/test_token_exchange.py` prints
    nothing, and DT-22's no-bypass closing check (M5.5's `rg`) still prints nothing.
  - `rg -n "transaction\(|audit" src/huron/core/security/broker/exchange.py` prints nothing (the
    exchange writes nothing, L-1 (a)).
  - `groups.py` and `exchange.py` at 100 % line coverage in the unit run.
- Dependencies: M5.5; M4.3 (`MemorySeed`, the in-memory `RoleMappingReader`).
- Decisions: OQ-6.1 (settled, owner decision 12)
- Decisions: OQ-6.2 (settled, owner decision 12)
- Status: pending

## Milestone 6 — Shared rules in `huron.schema`

The rules the server and the CLI must agree on land first, as pure `huron.schema` code with no Huron
import: the identity-segment rule, slugify, reserved names, depth and the four identifier forms
(`naming.py`); the catalog-config value, its packaged contract and the path resolver (`catalog_config.py`,
`catalog-config-v1.json`); one RE2-backed validator class that every packaged and composed schema uses
(`_validator.py`, the `google-re2` dependency and its one type-checker override); and the metadata module
that diffs documents (DT-7's `field_changes`), checks a schema part against the publish rules, composes the
org base, an extension and a config into one flattened document, and validates metadata against it, with
the seed `org-base-v1.json`. Nothing in `huron.core` changes and no import-linter contract changes (17 kept
throughout, the count M4 leaves). Every module is covered by unit tests, Hypothesis properties included, so
M7 (server) and M10/M12 (CLI) build on one copy of each rule.

### M6.1 Naming rules in `huron.schema.naming`

- Intent: give the lake one copy of the identity-segment rule, slugify, the reserved-name predicate, the
  depth bound and the four identifier forms with their conversions, pure and stdlib-only, so the server
  (through `lake`) and the CLI decide every name the same way. DT-13 adds the `rel_path` rule to the same
  module in M13.
- Delete: none.
- Create:
  - `src/huron/schema/naming.py`: `NamingError(ValueError)` with `rule` and `value` and DT-1's
    `__init__(rule, value, detail)` (rules `segment`, `slug_empty`, `depth`, `empty_segment`,
    `outside_prefix`, `no_catalog`); `SEGMENT_PATTERN`; `MAX_DEPTH`; `check_segment`; `slugify` (NFKD of the
    casefolded value, keep `[a-z0-9_-]`, strip leading `-`/`_`, never truncate); `is_reserved`; `Identifier`
    (frozen, slotted, `order=True`; `parse` with the four-row form-detection table, `from_canonical`,
    `canonical`, `fully_qualified`, `catalog_rooted`, `mount_path`; `__post_init__` checks every segment and
    `1 + len(path) <= MAX_DEPTH`). Imports `re`, `unicodedata` and `pathlib.PurePosixPath` only.
  - `tests/unit/test_schema_naming.py` (marker `unit`): every row of "DT-8 tests this design requires" for
    `slugify` (property and examples), `check_segment`, depth, form round trips (property) and form
    detection, promoted from R8-2's prototype. Named cases include
    `test_slugify_is_total_idempotent_and_the_identity_on_segments` (Hypothesis `st.text()` and
    `st.from_regex(SEGMENT_PATTERN, fullmatch=True)`; never returns a reserved name),
    `test_every_identifier_round_trips_through_all_four_forms`,
    `test_valid_canonical_strings_round_trip_byte_for_byte`,
    `test_nine_to_twelve_segments_are_refused_with_rule_depth` (checked before segments, in every form),
    `test_form_detection_precedence` (`/projects` → `outside_prefix`; `/projectsx/a` is catalog-rooted;
    `/psp/` without a catalog → `no_catalog`; one trailing `/` dropped; `a//b`, `a..b`, `.a`, `a.` →
    `empty_segment`; `a/../b` → `segment`).
- Modify:
  - `src/huron/schema/__init__.py`: the module docstring says the package holds the packaged contracts, the
    three loader functions and the pure rule modules the server and the CLI share (`naming` first; the
    others arrive with M6.3–M6.5), and the sentence on versioned file names ends "so a reader always
    knows which contract a document follows; a breaking change replaces the file and every caller in one
    change." instead of "a new file rather than an edit under an existing caller's feet" (owner decision
    11, B-32). No code change.
- Design: "DT-8 design: Catalog config, naming rules and paths" → "DT-8 decisions" (Segment rule, G-28,
  Depth, Slug collisions), "DT-8 interfaces and contracts" → "`huron.schema.naming`", "DT-8 tests this design
  requires"; "DT-1 design: …" → "DT-1 interfaces and contracts" → "`huron.schema.naming`: the shared naming
  rules (C-17)".
- Verification:
  - The plan-wide gate; `uv run lint-imports` keeps all 17 contracts.
  - `uv run pytest tests/unit/test_schema_naming.py -q` passes, including the five named cases and R8-2's
    example table (`"Campaign 17"` → `campaign17`, `"Müller_ß"` → `muller_ss`, `"v1.2"` and `"v12"` → `v12`,
    `""`, `"..."`, `"日本"`, `"-_-"` → `slug_empty`, 65 kept characters → `segment`).
  - `rg -n "^(from|import) huron" src/huron/schema/naming.py` prints nothing (schema imports no Huron
    package); `rg -n "a-z0-9_-\]\{0,63\}" src` prints only `src/huron/schema/naming.py` (one copy of the
    rule; M6.3's document copy is pinned to it by a test).
  - `naming.py` and `schema/__init__.py` at 100 % line coverage in the unit run.
- Dependencies: M2.
- Decisions: OQ-8.3 (settled, owner decision 12)
- Status: pending

### M6.2 RE2-backed validator for every schema `huron.schema` builds

- Intent: make every validator the package builds match `pattern` and `patternProperties` with RE2 and
  resolve no remote reference, so a catalog extension written by an Organization Admin can never make a
  Developer's metadata validation exponential (S-7, R9-2). `huron.schema.validator` keeps its name, cache
  and contract and returns the one extended class; no second factory or flag exists.
- Delete: none as files. `huron.schema.validator`'s `Draft202012Validator` return type is replaced by
  `HuronValidator` ("DT-9 deletions").
- Create:
  - `src/huron/schema/_validator.py`: `MAX_REGEX_LENGTH`; `compile_regex(pattern)` (RE2 compile with
    `re2.Options().log_errors = False`, `ValueError(message)` on refusal or above 1,024 characters); the RE2
    `pattern` and `patternProperties` keyword functions (jsonschema's messages and descend paths, matching
    with `re2.search`); `HuronValidator = jsonschema.validators.extend(Draft202012Validator, …)`;
    `build(document)` (`HuronValidator.check_schema`, then `HuronValidator(document,
    format_checker=FormatChecker(), registry=referencing.Registry())`). The only `import re2` in the
    repository.
  - `tests/unit/test_schema_validator.py` (marker `unit`): DT-9's `_validator` row:
    `test_re2_matches_a_pathological_pattern_in_linear_time` (`^(a|aa)+$` against `"a" * 1_000_000 + "b"`
    through `pattern`, a `patternProperties` key and `propertyNames`, each under 2 s);
    `test_compile_regex_refuses_backreferences_lookaround_and_length_silently` (`(a)\1`, `(?=a)b`,
    `(?<=a)b`, 1,025 characters; `capfd` sees nothing on stderr);
    `test_packaged_validators_are_huron_validators` (`validator("snapshot-provenance-v1.json")` is a
    `HuronValidator`); `test_a_remote_ref_fails_closed` (a `$ref` to an `https://` URL raises without any
    network access, because the registry is empty).
- Modify:
  - `pyproject.toml`: `[project].dependencies` gains `"google-re2>=1.1"`, added with
    `uv add "google-re2>=1.1"` so `uv.lock` moves in the same commit; one `[[tool.mypy.overrides]]` entry
    after the `asyncpg.*` one, `module = "re2"`, `ignore_missing_imports = true`, its comment naming
    `huron.schema._validator` as the only importer (the package ships no `py.typed`, R9-1). ty resolves
    untyped installed packages as it resolves `asyncpg` today, so no `[tool.ty]` entry is added; if
    `uv run ty check` reports `unresolved-import` for `re2`, the single permitted ty entry is a
    `[[tool.ty.overrides]]` scoped to `src/huron/schema/_validator.py`, and the task records which form it
    needed under "Execution notes".
  - `uv.lock`: `google-re2` and nothing else changes.
  - `src/huron/schema/__init__.py`: `validator(name)` returns `_validator.build(load_schema(name))`, annotated
    `jsonschema.protocols.Validator`, still `@cache`d; its docstring states RE2 matching and the closed
    registry; `validate` unchanged.
- Design: "DT-9 design: Metadata schemas, composition, vocabularies and validation" → "DT-9 decisions"
  (S-7, old M3.3), "DT-9 target module layout", "DT-9 interfaces and contracts" → "`huron.schema._validator`
  and `huron.schema.validator`", "DT-9 tests this design requires" (`_validator` row), "DT-9 deletions".
- Verification:
  - The plan-wide gate (mypy strict and ty pass with the override; `uv run --locked pyscn check src` and
    `uv run --locked python scripts/check_duplication.py src` prove the lock file is current);
    `uv run lint-imports` keeps all 17 contracts.
  - `uv run pytest tests/unit/test_schema_validator.py -q` passes with the four named cases; the existing
    document tests (`tests/unit/test_schema_loading.py`, `tests/unit/test_schema_snapshot_provenance.py`)
    pass unchanged.
  - `rg -n "^\s*(import re2|from re2)" src tests` prints only `src/huron/schema/_validator.py`;
    `rg -n "Draft202012Validator" src` prints only `src/huron/schema/_validator.py`.
  - `_validator.py` and `schema/__init__.py` at 100 % line coverage.
- Dependencies: M1 (D2-2 deletes the Raw documents and repoints `test_schema_loading.py`).
- Status: pending

### M6.3 Catalog config value, `catalog-config-v1.json` and the path resolver

- Intent: one immutable value for a catalog config, loaded from the packaged contract plus the four
  cross-field rules JSON Schema cannot state, with the walkthrough's `choices` and the path resolver
  `place`, so the server's placement and the CLI's path preview are the same code.
- Delete: none.
- Create:
  - `src/huron/schema/catalog_config.py`: `SchemaRef`, `FieldName`, `Generated`, `CollectionNameRule`,
    `Vocabulary` (`allowed`), `Placement` (`identifier`), `Problem`, `ConfigError`, `PlacementError`,
    `CatalogConfig` (`from_document`, `identity_fields`, `choices`, `place`). `from_document` validates
    through `huron.schema.validator("catalog-config-v1.json")`, turns each JSON Schema failure into a
    `Problem` (`where` = instance pointer, `rule` = failing keyword), then applies `vocabulary_field`,
    `vocabulary_parent`, `vocabulary_key` and `collection_name_field`, all collected into one `ConfigError`
    sorted by `where`. `place` reports every problem together (`required`, `type`, `vocabulary`, `parent`,
    and a slugify `NamingError` as its `rule`) as one `PlacementError` in config field order. Imports
    `huron.schema.naming`, the package's `validator` and the standard library only.
  - `src/huron/schema/documents/catalog-config-v1.json`: DT-8's outline exactly, `$id`
    `urn:huron:schema:catalog-config-v1`, plus a `title` and a `description` annotation per property and
    nothing else.
  - `tests/unit/test_schema_catalog_config.py` (marker `unit`): DT-8's rows `CatalogConfig.from_document`
    and `place`, promoted from R8-3: the amended spec example (YAML parsed with PyYAML, the declared
    `pyyaml` dependency) loads and its `{generate: collection_id}` variant loads; the literal spec YAML fails
    only at `/schema`; `catalog: "space science"` fails at `/catalog`; seven namespace fields fail
    `maxItems`; one minimal failing document per semantic rule, problems aggregated and sorted;
    `place` resolves `heliophysics.psp.fields.enc17.run042`; `solo` + any instrument → `vocabulary`; missing
    mission → `required` with instrument → `parent`, together; `{generate}` → the UUID string; a Hypothesis
    property that any successful placement has depth `2 + len(namespace_fields)` and round-trips through
    `Identifier.from_canonical`. Also `test_choices_serves_the_walkthrough` (flat list, dependent list,
    missing parent answer → `()`, open field → `None`),
    `test_document_segment_pattern_is_the_naming_rule` (`$defs.segment.pattern == "^" + SEGMENT_PATTERN +
    "$"`) and `test_catalog_config_validator_is_a_huron_validator`.
- Modify:
  - `src/huron/schema/__init__.py`: the module docstring names `catalog_config` among the rule modules.
- Design: "DT-8 decisions" (L-16 (a), L-23 (a), L-40 (c), Spec "vocabularies", Depth, Slug collisions,
  Config change rule); "DT-8 interfaces and contracts" → "`huron.schema.catalog_config`: the config value
  and the path resolver", "`catalog-config-v1.json`: outline and example"; "DT-8 tests this design
  requires"; "DT-8 target module layout".
- Verification:
  - The plan-wide gate; `uv run lint-imports` keeps all 17 contracts.
  - `uv run pytest tests/unit/test_schema_catalog_config.py -q` passes with the named cases.
  - `rg -n "^(from|import) huron\.(core|applications)" src/huron/schema` prints nothing.
  - `uv run python -c "from huron.schema import load_schema; load_schema('catalog-config-v1.json')"`
    exits 0.
  - `catalog_config.py` at 100 % line coverage; `complexipy` keeps `place` and `from_document` at or below
    15 (private per-rule helpers where needed).
- Dependencies: M6.1, M6.2.
- Decisions: OQ-8.1 (settled, owner decision 12)
- Decisions: OQ-8.3 (settled, owner decision 12)
- Status: pending

### M6.4 `huron.schema.metadata`: the field diff and the schema publish rules

- Intent: the one JSON field diff that both the server's audit `changes` and the CLI's `huron diff` call,
  so the diff a user sees before `push` is the diff the log records; and the document-level publish rules
  (2–8) a metadata schema part must pass, as a keyword-aware walk over schema positions only.
- Delete: none.
- Create:
  - `src/huron/schema/metadata.py`: `JsonValue` (structurally foundation's, no Huron import); `Absent`;
    `FieldChange` (`pointer`, `old`, `new`, `as_json`; `__post_init__` refuses both absent); `field_changes`
    (member-wise recursion into objects on both sides, whole-value comparison of arrays and scalars by JSON
    type and value, `bool` never equal to a number, RFC 6901 escaping, sorted by pointer code point);
    `BASE_SCHEMA_NAME`, `DRAFT_2020_12`; `SchemaDocumentError(ValueError)` with `problems` (DT-8's `Problem`);
    `check_schema_document` applying publish rules 2–8 (`dialect`, `root_type`, `metaschema` through
    `HuronValidator.check_schema`, `ref`, `regex` through `compile_regex`, `closed`, `field_name`) over the
    Draft 2020-12 applicator positions DT-9 lists, every problem collected.
  - `tests/unit/test_schema_metadata.py` (marker `unit`): DT-7's `field_changes` cases (added, removed,
    replaced, nested, an array compared whole, `true` vs `1`, `1` vs `1.0` equal, pointer escaping of `~`
    and `/`, sorted order, identical documents → `()`), `FieldChange` refusing both sides absent and
    `as_json` omitting the absent side; DT-9's `check_schema_document` row (one minimal failing document per
    rule 2–8 with its pointer, aggregated and sorted; a lookahead under `const`, `enum`, `default` or
    `examples` accepted; `$ref: "#/properties/x"`, `"other.json#/x"`, `$anchor` and a nested `$id` refused
    as `ref`).
- Modify:
  - `src/huron/schema/__init__.py`: the module docstring names `metadata`.
- Design: "DT-7 design: Audit log" → "DT-7 interfaces and contracts" → "`huron.schema.metadata`: the field
  diff (shared by the server's audit and the CLI's `huron diff`)", "DT-7 the vocabulary: action ×
  object_type and `detail`" (the `changes` encoding); "DT-9 decisions" (Publish rules, Schema naming); "DT-9
  interfaces and contracts" → "`huron.schema.metadata`" (the publish-rules table, rows 2–8).
- Verification:
  - The plan-wide gate; `uv run lint-imports` keeps all 17 contracts.
  - `uv run pytest tests/unit/test_schema_metadata.py -q` passes.
  - `rg -n "^(from|import) huron\.(core|applications)" src/huron/schema` prints nothing.
  - `metadata.py` at 100 % line coverage; `radon mi src --min B` prints nothing for it.
- Dependencies: M6.2, M6.3.
- Status: pending

### M6.5 Composition, `MetadataValidator` and the org base seed

- Intent: compose the org base, an optional extension and a catalog config's identity rules and
  vocabularies into one self-contained, closed Draft 2020-12 document (L-19 (a)), list its fields for the
  CLI, and validate metadata against it with stable problem pointers; ship the first org base as a
  packaged document for M7's bootstrap.
- Delete: none.
- Create:
  - `src/huron/schema/documents/org-base-v1.json`: DT-9's worked-example org base, verbatim.
  - `tests/unit/test_schema_composition.py` (marker `unit`): every DT-9 row for `compose`,
    `MetadataValidator`, `ComposedSchema` and `org-base-v1.json`:
    `test_worked_example_composes_to_the_golden_document` (RFC 8785 bytes, through the declared `rfc8785`
    dependency, equal a module-level golden literal of DT-9's flattened document) and
    `test_worked_example_outcomes` (the eight-row outcomes table, R9-3 and R9-4: `{"enum": []}` reports at
    `/instrument`); base and extension `$defs` with one key stay apart; an extension `if`/`then` survives;
    `org` alone; `identity_field` for an undeclared, a non-string and a conflicting-type identity field,
    reported together; `config=None` writes the null `x-huron` members;
    `test_composition_is_deterministic_and_always_a_valid_schema` (Hypothesis: equal inputs, equal bytes;
    every result passes `check_schema`); pointer escaping, `partial=True` dropping only root `required`,
    a non-object as one `type` problem, `(where, rule, message)` order; `fields()` order and hoisted
    annotations; `from_document` refusing a document without `x-huron`; the org base passing
    `check_schema_document` and rule 1 (its `huron.core.foundation.canonical.canonical_bytes` length is
    within 2..262,144), and composing alone and with the worked-example extension.
- Modify:
  - `src/huron/schema/metadata.py`: `CompositionError(ValueError)` with `problems`; `compose(base,
    extension, config, *, schema, base_version)` (steps 1–8 of the algorithm; `config=None` skips 6 and 7);
    `FieldSpec`; `ComposedSchema` (`document`, `from_document`, `fields`, `validator`); `MetadataValidator`
    (`problems(metadata, *, partial=False)`, built through `_validator.build`, synchronous and thread-safe).
    If `radon mi` rates `metadata.py` below A, the composition steps move into a private
    `src/huron/schema/_compose.py` that only `metadata.py` imports, with every public name unchanged.
- Design: "DT-9 decisions" (L-19 (a), Identity vs descriptive, Org base content); "DT-9 composition
  algorithm and worked example"; "DT-9 interfaces and contracts" → "`huron.schema.metadata`"; "DT-9 tests
  this design requires" (`compose`, `MetadataValidator`, `ComposedSchema`, `org-base-v1.json` rows).
- Verification:
  - The plan-wide gate; `uv run lint-imports` keeps all 17 contracts.
  - `uv run pytest tests/unit/test_schema_composition.py tests/unit/test_schema_metadata.py -q` passes.
  - `rg -n "^\s*(import re2|from re2)" src` still prints only `_validator.py`; `rg -n "metadata-v1" src`
    prints nothing.
  - `metadata.py` (and `_compose.py` if created) at 100 % line coverage; `complexipy` keeps every step at or
    below 15.
  - The duplication baseline: any new clone signature from the composition walks is accepted only by the
    reviewed hand edit the plan-wide rule describes, counted toward this group's four.
- Dependencies: M6.3, M6.4.
- Decisions: OQ-8.1 (settled, owner decision 12)
- Decisions: OQ-9.2 (settled, owner decision 12)
- Status: pending

## Milestone 7 — Audit, catalogs, schemas and administration

Spec build steps 1 and 2 as lake domain code over M4's in-memory store, with no route, no settings change
and no Postgres half (those are M8 and M9). DT-7's closed audit vocabulary, entry values and the
transaction writer land first, with the lake's own idempotency claims, so every later operation records
its entry and its receipt in the transaction of its change. Then DT-9's metadata schema registry, DT-8's
catalog values, store half and `Catalogs` (with DT-4's `require_on_catalog` in the first
`huron.core.lake._impl` module, which brings import-linter contract 16), DT-9's `Validation`, and DT-10's
`RoleMappings`, `SigningKeyAdmin` and `LakeBootstrap`. Each lake error code lands with its first raise site
and its `design/api.html` §7 row (convention 1). Each task adds its ports to DT-17's `LakeStore` and
`LakeTransaction` composites and its in-memory halves to `huron.core.metastore.lake`, and extends
`tests/lake_store_contract.py` with that area's scenarios, which `tests/unit/test_lake_memory_store.py` runs
now and M8 runs on PostgreSQL. Out of this milestone: `require_on_collection`, `CollectionStore`,
`IDENTITY_UNRESOLVED`, the completeness recompute (`recompute_completeness`, `CompletenessWriter`) and
`request_access_reset` in `map`/`unmap` (all M11, D-4, D-6); DT-7's `AuditReader` and `collection_log`
(M16); the lifespan bootstrap, `PlatformOwnerSeed` as a setting and every route (M9).

### M7.1 Audit vocabulary, entries and the in-memory audit and claim halves

- Intent: the closed set of fourteen `(action, object_type)` pairs, one frozen event class per pair and the
  `AuditEntry` value with its invariants and `detail()` encoding, plus the two in-memory transaction halves
  that make "no change without its entries" and "one claim per `(subject, key)`" true, so every audited
  operation in M7 and later writes entries and receipts in the transaction of its change. The
  `IdempotencyClaim` used is `foundation.retry.IdempotencyClaim` over the lake's own table (D-7, OQ-1.1).
- Delete: none.
- Create:
  - `src/huron/core/lake/audit.py`: `AuditAction`, `AuditObject`, `SYSTEM_BOOTSTRAP`, `AUDIT_REASON_MAX`;
    the fourteen frozen, keyword-only event classes `CollectionCreated`, `CollectionActivated`, `FileAdded`,
    `FileOverwritten`, `FileRemoved`, `MetadataPublished`, `CollectionMoved`, `CollectionDeleted`,
    `CatalogCreated`, `CatalogConfigChanged`, `SchemaPublished`, `RoleMapped`, `KeyRotated`, `KeyWithdrawn`,
    each declaring `ACTION`, `OBJECT` and `KEY` as class variables; the `AuditEvent` union;
    `AUDIT_VOCABULARY` derived from the classes; `AuditEntry` (`object_id`, `catalog_id`, `detail()`, the
    `__post_init__` invariants) and `AuditRecord`. No I/O and no clock. Imports `huron.schema.metadata`
    (`FieldChange`, `JsonValue`) and `huron.core.security.broker` (`COMPANY_USERNAME`, `Role`).
  - `src/huron/core/lake/types.py`: `CollectionState` (DT-12's enum with `settled`), needed now by
    `CollectionDeleted`; M7.2 and M7.3 add their values beside it and M11 adds the collection records.
  - `src/huron/core/metastore/lake/audit.py`: the `InMemoryAudit` transaction half. `append_audit(entries)`
    raises `ValueError` on an empty sequence, stages entries in the transaction buffer in call order, applies
    the table's rules when staging (`audit_log_vocabulary`: the pair is in the seeded `audit_actions`;
    `audit_log_collection_has_catalog`; the `actor`, `object_id` and `reason` length CHECKs) by raising
    `IntegrityViolation(constraint)` (DT-17's fake-only `RuntimeError`, added to `memory.py` here) with the
    PostgreSQL constraint name, and assigns ids from one counter when the
    transaction applies; a raising block discards them. `PostgresAudit` is M8's.
  - `src/huron/core/metastore/lake/idempotency.py`: the `InMemoryClaims` transaction half (`claim`,
    `remember`, `foundation.retry.RetryTransaction`) over `idempotency_records`: claims live 24 h by the
    injected `Clock`, an expired claim is replaced, no `Replay.kind` is exempt from expiry, the receipt CHECKs
    of `lake.idempotency_records` hold (`replay_kind` one of the five lake kinds; kind and resource both or
    neither), and rollback discards the claim with the mutation. `PostgresClaims` and `LakeStore.prune_claims`
    are M8.3's; M13.7's housekeeping calls the prune.
  - `tests/unit/test_lake_audit.py` (marker `unit`): DT-7's `test_audit.py` row: `detail()` of each event
    class equals its vocabulary row (keys exactly, UUIDs canonical, instants `isoformat()` in UTC, role codes,
    nulls present, never omitted); `AuditEntry` refuses a naive `at`, a blank or 1,001-character `reason`, an
    actor matching neither `COMPANY_USERNAME` nor `system:`, `version` 0 and an empty `changes`; `RoleMapped`
    refuses equal or both-`None` roles; `AUDIT_VOCABULARY` is exactly the fourteen pairs, `key_withdraw`
    included; `test_no_audit_mutation_in_src` (a Python scan of every `src/huron/**/*.py` finds no
    `UPDATE lake.audit_log`, `DELETE FROM lake.audit_log` or `TRUNCATE lake.audit_log`).
- Modify:
  - `src/huron/core/lake/ports.py`: `AuditWriter`; `LakeTransaction` gains `AuditWriter` and
    `foundation.retry.RetryTransaction` among its bases (DT-17's composite).
  - `src/huron/core/lake/__init__.py`: exports the audit names and `CollectionState`.
  - `src/huron/core/metastore/lake/memory.py`: `LakeTables` gains `audit_actions` (loaded from
    `AUDIT_VOCABULARY` when `seed=True`), `audit_log` and `idempotency_records`; `LakeBuffer` stages entries
    and claims; `InMemoryLakeTransaction` composes `InMemoryAudit` and `InMemoryClaims`; `IntegrityViolation`;
    `InMemoryLakeStore` gains DT-17's keyword `clock: Clock | None = None` (`None` → `SystemClock()`), which
    the claims half reads.
  - `src/huron/core/foundation/clock.py`: `SystemClock` moves here from `huron.core.metastore.hierarchy`,
    because contract 19 forbids `huron.core.metastore.lake` to import the legacy module; every importer
    (`core/metastore/__init__.py`, `core/metastore/hierarchy.py`, `applications/api/app.py` and the tests that
    `rg -l SystemClock tests` lists) imports it from foundation, with no re-export left in `metastore`.
  - `pyproject.toml`: `[tool.ruff.lint.per-file-ignores]` gains `"src/huron/core/metastore/lake/memory.py" =
    ["N818"]` beside the other error-name entries (DT-17 names the fake's `IntegrityViolation`).
  - `src/huron/core/foundation/retry.py`: `Replay.kind`, which M1.4 left at the three legacy kinds
    (`"organization"`, `"project"`, `"dataset"`; the Raw kinds and their `ingest_commit` exemption left with
    their writers, DT-14 deletions), gains `"catalog"`, `"metadata_schema"` and `"signing_key"` (DT-17's
    handoff to DT-18; M8.2 adds `"collection"` and `"commit"` with 0015's `replay_kind` CHECK, which lists
    all five); the `Replay` docstring names the lake receipts, and neither it nor `RetryTransaction.claim`'s
    docstring exempts any kind from expiry.
  - `tests/unit/test_foundation_retry.py`: `test_replay_kinds_cover_the_lake_admin_creating_calls`.
  - `tests/lake_store_contract.py`: audit and claim area functions: entries commit with their transaction
    and vanish with a raising block; ids ascend in call order and in commit order; empty `entries` refused;
    an unseeded pair (a test-only event class) refused naming `audit_log_vocabulary` (M8 asserts SQLSTATE
    23503 on PostgreSQL); a collection entry without a catalog refused; same key and fingerprint replays the
    remembered `Replay`, a different fingerprint raises `IdempotencyKeyReused`, an expired claim is replaced
    under a moved `FakeClock`, and a rolled-back claim leaves no row.
  - `tests/unit/test_lake_memory_store.py`: runs those functions against `InMemoryLakeStore`.
- Design: "DT-7 design: Audit log" → "DT-7 decisions", "DT-7 the vocabulary: action × object_type and
  `detail`", "DT-7 interfaces and contracts" → "`huron.core.lake.audit`: vocabulary, events and entries" and
  "The writer seam: `AuditWriter` (used by DT-10, DT-12, DT-14 and DT-15)", "DT-7 tests this design
  requires" (unit and static rows), "DT-7 retention and hardening"; "DT-17 design: …" → "DT-17 interfaces and
  contracts" ("The fake", "Constraint violations"), "DT-17 port → adapter → fake" (`AuditWriter`,
  `RetryTransaction` rows), "DT-17 DDL: `0015_lake_catalog`" (constraint names), "DT-17 resolved
  disagreements between sections" (D-7); "DT-14 the idempotency rule" (Lifetime); "DT-18 interfaces and
  contracts" → "Composition and readiness" (replay kinds).
- Verification:
  - The plan-wide gate; `uv run lint-imports` keeps all 17 contracts.
  - `uv run pytest tests/unit/test_lake_audit.py tests/unit/test_lake_memory_store.py
    tests/unit/test_foundation_retry.py -q` passes.
  - `rg -n "UPDATE lake\.audit_log|DELETE FROM lake\.audit_log|TRUNCATE lake\.audit_log" src/huron` prints
    nothing; `rg -n "core\.raw|insert_audit_event" src/huron/core/lake src/huron/core/metastore/lake` prints
    nothing (no reuse of the deleted legacy audit path).
  - M4's structural-conformance case still holds: `InMemoryLakeTransaction` satisfies `LakeTransaction`.
  - `rg -n "class SystemClock" src` prints only `src/huron/core/foundation/clock.py`;
    `rg -n "metastore import .*SystemClock|from \.hierarchy import .*SystemClock" src tests` prints nothing.
  - `rg -n -i "ingest" src/huron/core/foundation/retry.py` prints nothing (no Raw kind and no expiry
    exemption); `rg -n '"(ingest_session|ingest_commit|revision)"' src/huron` prints nothing.
  - Every created or modified file at 100 % line coverage. The fourteen event dataclasses add no clone
    signature beyond the reviewed hand edit of `scripts/duplication_baseline.json` the plan-wide rule allows
    (recorded under "Execution notes").
- Dependencies: M4, M5, M6.4.
- Decisions: OQ-1.1 (settled, owner decision 12)
- Decisions: OQ-4.1 (settled, owner decision 12)
- Decisions: OQ-5.2 (settled, owner decision 12)
- Decisions: OQ-7.1 (settled, owner decision 12)
- Status: pending

### M7.2 Metadata schema registry and the lake error vocabulary

- Intent: publish, read, list and resolve metadata schema versions with DT-9's preconditions and refusal
  codes, the identical-republish no-op and the gap-free version rule decided by the insert, the
  `schema_publish` entry in the same transaction; and open `core/lake/errors.py` with its first two codes,
  wired into the service's error vocabulary.
- Delete: none.
- Create:
  - `src/huron/core/lake/errors.py`: `SchemaInvalid` (422, context `problems`, `total`),
    `SchemaVersionExists` (409, context `name`, `version`, `latest_version`) and `ERROR_CODES` (DT-1's
    vocabulary; later tasks add their classes here).
  - `src/huron/core/lake/schemas.py`: `MetadataSchemas(store, clock, *, row_cache=256)` with `publish`,
    `get`, `list`, `resolve`, `parts`, and `Published`. `publish` runs preconditions 1–8 in DT-9's order
    (rule 1 through `foundation.canonical.canonical_bytes`, rules 2–8 through `check_schema_document`, rule 9
    through `compose`; problems capped at 50 plus `total`), then one transaction: claim (receipt
    `Replay("metadata_schema", id)`), `insert_schema`, `SchemaPublished` audit entry, remember. `id` is
    `foundation.identifiers.uuid7()` and `sha256` is `foundation.canonical.content_identity`. `get` and
    `list` take any authenticated actor; `list(actor, after, limit)` takes `after: tuple[str, int] | None`,
    the full sort key of DT-18's `("metadata-schemas", name, str(version))` cursor. Rows read by id are
    cached (LRU, `row_cache`); `by_ref` is never cached.
  - `tests/unit/test_lake_schemas.py` (marker `unit`, `InMemoryLakeStore`, `FakeClock`): DT-9's
    `MetadataSchemas` row: base then extension; one case per refusal-table row (1 `FORBIDDEN` below
    Organization Admin; 2 a replay answers the first result and a different body is
    `IDEMPOTENCY_KEY_REUSED` at 409, as DT-18 supersedes DT-9's 422; 3 `name`, `version`; 4 `extends`; 5 the
    publish rules with the 50-problem cap and `total`; 6 identical republish → `created=False`, no row, no
    entry; 7 `SCHEMA_VERSION_EXISTS` with `latest_version`; 8 `version_gap`); an extension of an extension →
    `extends`; the `schema_publish` entry rolls back with its row; unknown `get` → `NOT_FOUND`; `list`
    keyset by `(name, version)`; `parts` answers from the row cache after the first read.
- Modify:
  - `src/huron/core/lake/types.py`: `MetadataSchemaRecord` (`ref`) and `SchemaParts` (`referenced`); and
    `is_segment(value) -> bool`, which wraps `huron.schema.naming.check_segment` (`False` on its
    `NamingError`). It is the fake's only path to the segment rule: contract 8 forbids
    `huron.core.metastore` to import `huron.schema`, and DT-1 and DT-8 allow one copy of `SEGMENT_PATTERN`
    (design: `lake/types.py` exists "so metastore never imports huron.schema"). Every in-memory
    `name ~ '^<SEGMENT>$'` CHECK (here, M7.3's catalogs and M11's collections and namespaces) calls it.
  - `src/huron/core/lake/ports.py`: `MetadataSchemaStore` (`by_ref`, `by_id`, `latest`, and `schemas(after,
    limit)` for DT-9's `list`), `MetadataSchemaWriter` (`insert_schema(record)` for DT-9's `insert`), and
    `SchemaResolver` (`resolve(ref) -> SchemaParts | None`, DT-8's consumer port). The renames keep every
    public name unique across the halves of one composite (DT-17's no-shadowing rule: `CatalogStore` also
    lists). `LakeStore` gains `MetadataSchemaStore`; `LakeTransaction` gains `MetadataSchemaWriter`.
  - `src/huron/core/lake/__init__.py`: exports `MetadataSchemas`, `Published` and the two record values.
  - `src/huron/core/metastore/lake/catalogs.py` (new module, DT-17's layout): the `InMemoryMetadataSchemas`
    half. `insert_schema` decides precondition rows 7 and 8 as DT-9's insert statement does (an existing
    `max(version) >= version` → `SchemaVersionExists`; otherwise a gap → `SchemaInvalid` with rule
    `version_gap`) and applies `metadata_schemas_name_version_key`, `metadata_schemas_org_is_the_base`,
    the name CHECK (through `lake.types.is_segment`, as `IntegrityViolation("metadata_schemas_name_check")`,
    PostgreSQL's default name for the column CHECK), the `sha256` CHECK and the one-level rule
    (`metadata_schemas_one_level`) as `IntegrityViolation`s naming their PostgreSQL constraint; `schemas`
    orders by `(name, version)` in `str` order.
  - `src/huron/core/metastore/lake/memory.py`: `LakeTables.metadata_schemas` with its `(name, version)`
    secondary key; root and transaction compose `InMemoryMetadataSchemas`.
  - `src/huron/applications/api/problems.py`: `wire_error_codes()` unions `huron.core.lake.errors`'s
    `ERROR_CODES` as `LAKE_ERROR_CODES` beside foundation, hierarchy, security and transport (DT-1 "Error
    codes"; DT-18).
  - `pyproject.toml`: `[tool.ruff.lint.per-file-ignores]` gains `"src/huron/core/lake/errors.py" =
    ["N818"]` beside the other errors modules (the design's class names, `SchemaInvalid` and the rest, carry
    no `Error` suffix and ruff's N818 flags every `DomainError` subclass without one).
  - `design/api.html` §7: DT-18's `SCHEMA_INVALID` and `SCHEMA_VERSION_EXISTS` rows verbatim, and the prose
    sentence under the table that lake codes are live only on lake routes (this is the first lake code).
  - `design/catalog-search.html`: §2's registry part replaced by `lake.metadata_schemas` with `extends_id`
    (ADR 0003 linked), and the lines DT-26 lists for this task (`:123`, `:165-166`, `:180`, `:377`, `:444`,
    `:467` at `fa51f46`; re-located by text after M0 and M2) adapted as its row says.
  - `tests/lake_store_contract.py` and `tests/unit/test_lake_memory_store.py`: schema-half scenarios
    (insert then `by_ref`, `by_id`, `latest`; `schemas` keyset order; the exists-or-gap decision; the
    one-level, org-base and name rules naming their constraints, an extension of `org` named `Ext` refused
    as `metadata_schemas_name_check`).
- Design: "DT-9 decisions" (Schema naming, Publish rules, Error codes); "DT-9 interfaces and contracts" →
  "`huron.core.lake.schemas`: the registry" (preconditions table), "`lake.metadata_schemas`: logical shape",
  "Errors, routes and the CLI's use of `huron.schema`"; "DT-9 tests this design requires" (`MetadataSchemas`
  row, in-memory half); "DT-17 port → adapter → fake" (`MetadataSchemaStore` / `MetadataSchemaWriter`);
  "DT-18 error-code table rows (`design/api.html` §7, ready to paste)"; "DT-18 paging keys and the `label`
  filter" (`/metadata-schemas`); "DT-26 design record pages: the Raw-facing six" (the two
  `catalog-search.html` rows naming "DT-9 schema task").
- Verification:
  - The plan-wide gate; `uv run lint-imports` keeps all 17 contracts; `uv run pytest
    tests/unit/test_error_contract.py` passes with `SCHEMA_INVALID` and `SCHEMA_VERSION_EXISTS` each declared
    by exactly one class, documented with their status and live with a raise site; `make docs` passes.
  - `uv run pytest tests/unit/test_lake_schemas.py tests/unit/test_lake_memory_store.py -q` passes.
  - `rg -n "VALIDATION_FAILED|SCHEMA_SUBJECT|DEPRECATED" src/huron/core/lake` prints nothing.
  - `rg -n "huron\.schema" src/huron/core/metastore` prints nothing (the fake reaches the segment rule only
    through `lake.types.is_segment`); `rg -n --type py "a-z0-9_-\]\{0,63\}" src` still prints only
    `src/huron/schema/naming.py` (the one Python copy; `catalog-config-v1.json`'s `$defs.segment.pattern`
    is the packaged contract's copy, pinned by M6.3's `test_document_segment_pattern_is_the_naming_rule`).
  - Every created or modified file at 100 % line coverage.
- Dependencies: M7.1, M6.5.
- Decisions: OQ-1.1 (settled, owner decision 12)
- Status: pending

### M7.3 Catalog values, the catalog store half and `require_on_catalog`

- Intent: the values that cross the catalog ports (`NamespacePath`'s ltree encoding, `CatalogRecord`,
  `CatalogConfigRecord`), the catalog store and writer ports with their in-memory half (immutable configs,
  fixed names, no deletion, the deferred current-config link, the readable filter before `LIMIT`), and DT-4's
  catalog visibility rule in the first `huron.core.lake._impl` module, which brings import-linter
  contract 16.
- Delete: none.
- Create:
  - `src/huron/core/lake/_impl/__init__.py` (docstring only) and `src/huron/core/lake/_impl/access.py`:
    `require_on_catalog(actor, catalogs, name, minimum)`: `naming.check_segment(name)` first (a
    `NamingError` is `ResourceNotFound` with the detail of an absent catalog, DT-8's path-parameter
    translation), then `catalogs.get_ref(name)`; `None` or no role on it is `ResourceNotFound`; otherwise
    `actor.grants.require(minimum, ref)` (403) and the ref is returned. `require_on_collection` is M11's.
  - `tests/unit/test_lake_types.py` (marker `unit`): DT-8's `NamespacePath` row (`from_ltree(p.ltree()) ==
    p`; `of(placement)` drops catalog and name; `from_ltree` re-checks labels and refuses `Psp`, `''` and
    seven labels); `CatalogRecord.ref`; a collection's canonical identifier is
    `f"{catalog}.{path.ltree()}.{name}"`.
- Modify:
  - `src/huron/core/lake/types.py`: `NamespacePath`, `CatalogRecord` (`ref`), `CatalogConfigRecord`.
  - `src/huron/core/lake/ports.py`: `CatalogStore` (`get_ref`, `current`, `config`, and `catalogs(readable,
    after, limit) -> Window[tuple[CatalogRecord, CatalogConfigRecord]]` for DT-8's `list`) and DT-17's
    `CatalogWriter` (`insert_catalog(record, config)`; `lock_catalog_config(catalog_id) -> int`, the row lock
    `FOR UPDATE` that returns the current `config_version` and records it for the version guard, distinct
    from DT-12's `CollectionWriter.lock_catalog` `FOR SHARE`; `append_config(config)`, which inserts version
    N+1 and moves `catalogs.config_version` under the recorded version, `LockContractBroken` when the row
    was not locked or its version moved). `LakeStore` gains `CatalogStore`; `LakeTransaction` gains
    `CatalogWriter`.
  - `src/huron/core/lake/errors.py`: `CatalogExists` (409, context `name`), raised by the store half on
    `catalogs_name_key`.
  - `src/huron/core/metastore/lake/catalogs.py`: the `InMemoryCatalogs` half over `LakeTables.catalogs` and
    `catalog_configs`: the name CHECK (`IntegrityViolation` naming `catalogs_name_check`, PostgreSQL's
    default name, decided through M7.2's `lake.types.is_segment`), `catalogs_name_key` → `CatalogExists`,
    append-only configs, the `catalogs_guard` rules (fixed columns, no lower `config_version`, no delete),
    the deferred `catalogs_current_config` link checked when the transaction applies, the config `document`'s
    `config_version` CHECK, `catalogs` filtered by `ReadableCatalogs` before the limit in `str` order of
    `name`, and `lock_catalog_config` through M4's per-catalog readers-writer lock (exclusive).
  - `src/huron/core/metastore/lake/memory.py`: the two tables; root and transaction compose
    `InMemoryCatalogs`.
  - `src/huron/core/metastore/lake/_db.py` (new): DT-17's `LockContractBroken(RuntimeError)`, raised by the
    fake from here on and by the PostgreSQL halves from M8.3, which adds the module's asyncpg helpers;
    `src/huron/core/metastore/lake/__init__.py` exports it; `pyproject.toml` gains
    `"src/huron/core/metastore/lake/_db.py" = ["N818"]` beside the other error-name entries.
  - `pyproject.toml`: contract 16, "lake implementations are private to their owner" (`protected`,
    `protected_modules = ["huron.core.lake._impl"]`, `allowed_importers = ["huron.core.lake"]`).
  - `tests/unit/test_domain_import_contracts.py`: `PRIVATE_OWNERS` gains `"lake"`; the forbidden-edge table
    gains `{"huron/core/metastore/public.py": "import huron.core.lake._impl.operations\n"}` → "lake
    implementations are private to their owner".
  - `tests/unit/test_lake_access.py` (M4's module): `require_on_catalog` over DT-4's case table (catalog
    grant, all-catalog grant, unknown groups, below minimum is 403, global-only role); an unknown catalog, a
    catalog without a role and a non-segment name give one indistinguishable 404 body. The cases create
    their catalogs through the fake's own `insert_catalog` (catalog with its version-1 config) in a
    committed transaction, because `LakeSeed` has no catalog method until M7.6.
  - `design/api.html` §7: DT-18's `CATALOG_EXISTS` row verbatim.
  - `tests/lake_store_contract.py` and `tests/unit/test_lake_memory_store.py`: catalog-half scenarios
    (insert then `get_ref`, `current`, `config`; `catalogs` keyset and the readable filter applied before the
    limit; a duplicate name → `CatalogExists`; a non-segment name → `catalogs_name_check`;
    `append_config` without the lock, and with a moved version →
    `LockContractBroken`; a catalog whose current config is missing fails at apply naming
    `catalogs_current_config`).
- Design: "DT-8 interfaces and contracts" → "The ltree encoding (G-6) and `huron.core.lake.types`",
  "`huron.core.lake.catalogs`: catalog operations and naming application" (store requirements, naming
  translation), "`lake.catalogs` and `lake.catalog_configs`: logical shapes"; "DT-4 design: …" → "DT-4
  interfaces and contracts" → "`core/lake`: applying the grants (convention 6)"; "DT-17 interfaces and
  contracts" (lock-then-check, version-guarded; the fake), "DT-17 port → adapter → fake" (`CatalogStore` /
  `CatalogWriter`), "DT-17 DDL: `0015_lake_catalog`" (constraint and trigger names); "DT-1 import-linter
  contract set (diff against the sixteen)" (contract 16).
- Verification:
  - The plan-wide gate; `uv run lint-imports` keeps all 18 contracts (contract 16 added);
    `tests/unit/test_domain_import_contracts.py` passes with the new case; `uv run pytest
    tests/unit/test_error_contract.py` passes with `CATALOG_EXISTS` live.
  - `uv run pytest tests/unit/test_lake_types.py tests/unit/test_lake_access.py
    tests/unit/test_lake_memory_store.py -q` passes.
  - `rg -n "_impl" src/huron/core/metastore src/huron/applications | rg "core\.lake\._impl"` prints nothing.
  - `rg -n "huron\.schema" src/huron/core/metastore` prints nothing (the catalogs name CHECK goes through
    `lake.types.is_segment`).
  - Every created or modified file at 100 % line coverage.
- Dependencies: M7.2, M6.3, M4.
- Status: pending

### M7.4 Catalog operations: create, publish config, get and list

- Intent: DT-8's `Catalogs`: an Organization Admin creates a catalog with its first config and publishes
  new immutable config versions under `If-Match`; Readers get the current or a pinned config; listings show
  only readable catalogs. Every write records its audit entry, a create records its idempotency receipt, an
  unchanged config is a no-op, and the identity layout is frozen across versions.
- Delete: none.
- Create:
  - `src/huron/core/lake/catalogs.py`: `Catalogs(store, schemas, clock)` with `create`, `publish_config`,
    `get`, `get_config`, `list`, and `CatalogView`. The first parameter is DT-17's `LakeStore` (the store
    root that reads `CatalogStore` and opens the transaction, as DT-18's `catalogs(runtime)` builds it from
    `runtime.stores.lake`); `schemas` is the `SchemaResolver` port (M7.2's `MetadataSchemas`). Min roles,
    the `create` and `publish_config` sequences, the publish checks (`ConfigError` problems, `read_only`,
    `catalog_mismatch`, `schema_ref`, `identity_field` through `compose` with the new config, and
    `identity_layout` against version 1), the no-op rule and the naming translation are DT-8's; `create`
    claims with receipt `Replay("catalog", catalog_id)` and a replay answers the current view;
    `publish_config` compares `expected_version` with `lock_catalog_config` and raises `PreconditionFailed`
    with `current_version`; the `catalog_config` entry's `changes` is `field_changes` over the two config
    documents. The `CatalogConfig` cache is keyed by `(catalog_id, config_version)` and filled only from
    committed reads (DT-9's cache rule). M11 adds the completeness recompute when `schema_id` changes.
  - `tests/unit/test_lake_catalogs.py` (marker `unit`, `InMemoryLakeStore`, M7.2's `MetadataSchemas` with
    `org` and the DT-9 worked-example extension published): DT-8's catalogs row (create then get; duplicate
    name → `CATALOG_EXISTS`; stale `expected_version` → 412 with `current_version`; identical body → no new
    version and no entry; `identity_layout` refused); a replayed create answers the same view and writes
    nothing, another body under the key → `IDEMPOTENCY_KEY_REUSED`; a body carrying `config_version`
    (`read_only`) or another catalog (`catalog_mismatch`), an unpublished schema (`schema_ref`) and a
    non-string identity field (`identity_field`) reported together in one `CATALOG_CONFIG_INVALID`; a bad
    create name → foundation `PathRuleViolation` (`PATH_RULE_VIOLATION`, 400) built through the inherited
    `DomainError.__init__(detail, *, context=...)` with `error.context == {"rule": "segment", "value":
    name}` (M1.4 deleted the code-override constructor, DT-8 deletions); a non-segment `{catalog}` name on
    `get` → 404;
    `create` and `publish_config` → 403 below Organization Admin; `get` and `get_config` → 404 without a
    role and for an unknown version; `list` returns only readable catalogs and pages by name; each write's
    entry is the exact pair, `object_id`, `catalog_id` and `detail` of DT-7's vocabulary.
- Modify:
  - `src/huron/core/lake/errors.py`: `CatalogConfigInvalid` (422, context `problems`).
  - `src/huron/core/lake/__init__.py`: exports `Catalogs` and `CatalogView`.
  - `design/api.html` §7: DT-18's `CATALOG_CONFIG_INVALID` row verbatim.
  - `docs/getting-started/conventions.md:98`: DT-26's replacement line for this task, verbatim (its
    `rel_path` clause names the rule M13 adds to `huron.schema.naming`).
- Design: "DT-8 decisions" (G-22, L-16 (a), L-23 (a), Config change rule, Error codes); "DT-8 interfaces and
  contracts" → "`huron.core.lake.catalogs`: catalog operations and naming application"; "DT-8 tests this
  design requires" (catalogs row, in-memory half); "DT-9 interfaces and contracts" → "`huron.core.lake.schemas`:
  validation, the cache and the Incomplete computation" (the cache rule); "DT-7 the vocabulary: action ×
  object_type and `detail`" (`create`/`catalog`, `catalog_config`/`catalog`); "DT-18 interfaces and
  contracts" → "Lake service dependencies", "Composition and readiness"; "DT-26 developer docs, README and
  history" (`conventions.md:98`); "DT-8 deletions" (`PathRuleViolation` keeps `code` and `status_code`
  and inherits `DomainError.__init__`; M1.4 deletes its code-override constructor with D2-2).
- Verification:
  - The plan-wide gate; `uv run lint-imports` keeps all 18 contracts; `uv run pytest
    tests/unit/test_error_contract.py` passes with `CATALOG_CONFIG_INVALID` live; `make docs` passes.
  - `uv run pytest tests/unit/test_lake_catalogs.py -q` passes; its bad-create-name case asserts
    `error.code == "PATH_RULE_VIOLATION"`, `error.status_code == 400` and `error.context == {"rule":
    "segment", "value": name}`.
  - `rg -n "code_or_detail" src tests` prints nothing (DT-8 deletions, landed in M1.4).
  - `rg -n "grants\.(role_on|require)" src/huron/core/lake/catalogs.py` shows only the global
    `require(Role.ORGANIZATION_ADMIN)` calls; every catalog-scoped check goes through `require_on_catalog`.
  - Every created or modified file at 100 % line coverage.
- Dependencies: M7.3, M7.2, M7.1.
- Decisions: OQ-1.1 (settled, owner decision 12)
- Decisions: OQ-8.1 (settled, owner decision 12)
- Decisions: OQ-8.2 (settled, owner decision 12)
- Status: pending

### M7.5 Validation: resolved schemas, the validator cache and `require_valid`

- Intent: the one function that turns a catalog's current config and a collection's pinned config into the
  composed document, its digest and a cached validator (L-17 (a)), plus the problem check and the refusal
  every metadata write uses; `GET /catalogs/{c}/schema` (M9) is `resolved(current, current)`. The
  completeness recompute over collections lands with them in M11.
- Delete: none.
- Create:
  - `tests/unit/test_lake_validation.py` (marker `unit`, `InMemoryLakeStore`): DT-9's `Validation` row:
    equal compositions across two catalogs share one validator object (`is`); a pinned config with other
    vocabularies yields another digest; `require_valid` raises `METADATA_INVALID` with the first 50 problems,
    `total` and `schema` (the digest); metadata whose RFC 8785 bytes exceed 1,048,576 is one `("", "size",
    …)` problem before validation; `check(partial=True)` drops only root `required`; `current` and `pinned`
    of different catalogs raise `ValueError`; `resolved(c, c).digest` equals
    `foundation.canonical.content_identity` of the composed document; the LRU evicts by size only.
- Modify:
  - `src/huron/core/lake/schemas.py`: `ResolvedSchema` and `Validation(schemas, *, cache_size=128)` with
    `resolved`, `check` (problems computed through `asyncio.to_thread`) and `require_valid`. The cache key is
    the digest alone.
  - `src/huron/core/lake/errors.py`: `MetadataInvalid` (422, context `problems`, `total`, `schema`).
  - `src/huron/core/lake/__init__.py`: exports `Validation` and `ResolvedSchema`.
  - `design/api.html` §7: DT-18's `METADATA_INVALID` row, less the `frozen` and `not_identity` rules, which
    M16.3 and M16.5 add with their first raisers (the row names `size` and `type` now).
- Design: "DT-9 decisions" (L-17 (a), G-8, Metadata publish); "DT-9 interfaces and contracts" →
  "`huron.core.lake.schemas`: validation, the cache and the Incomplete computation" (`resolved`, the cache
  key and its rule, `check`, `require_valid`; not `recompute_completeness`); "DT-9 tests this design
  requires" (`Validation` row); "DT-18 error-code table rows (`design/api.html` §7, ready to paste)".
- Verification:
  - The plan-wide gate; `uv run lint-imports` keeps all 18 contracts; `uv run pytest
    tests/unit/test_error_contract.py` passes with `METADATA_INVALID` live.
  - `uv run pytest tests/unit/test_lake_validation.py -q` passes.
  - `rg -n "recompute_completeness|CompletenessWriter|scan_settled" src` prints nothing (M11's).
  - Every created or modified file at 100 % line coverage.
- Dependencies: M7.2, M7.3, M6.5.
- Decisions: OQ-8.2 (settled, owner decision 12)
- Decisions: OQ-9.1 (settled, owner decision 12)
- Status: pending

### M7.6 Role mappings: `apply_mapping`, `RoleMappings` and the mapping write half

- Intent: audited group-to-role mapping writes at catalog and global scope with DT-10's order of checks
  (scope, ceiling on the new role, input, seed, then the locked write with the ceiling on the old role),
  one write path shared with the bootstrap, a POSIX gid fixed per group, the last-Platform-Owner and
  seeded-mapping refusals, and scope-exact listings. A committed change only changes request-time
  authorization until M11 adds the access reset (D-6).
- Delete: none.
- Create:
  - `src/huron/core/lake/admin.py`: `RoleMappingView`, `MappingWrite`, `RoleMappings(store, clock, seed)`
    (`list`, `map`, `unmap`) and `PlatformOwnerSeed` (`check_group_name` and the gid range
    1 .. 2**31 − 1 in `__post_init__`; M9 makes it the `ApiSettings` field type).
  - `src/huron/core/lake/_impl/mappings.py`: `apply_mapping(tx, *, group, catalog, role, posix_gid, writer,
    at, reason, permit)`, steps 1–6 (scope lock, read and `permit(old)`, the no-op return with no entry,
    the gid rules, the last owner, then the row write followed by one `RoleMapped` entry).
  - `tests/unit/test_lake_role_mappings.py` (marker `unit`, `InMemoryLakeStore`): every case of DT-10's
    `test_lake_role_mappings.py` row (PA maps `developer` on their catalog → created and one entry; the same
    write again → unchanged and no entry; PA mapping `project_admin` while holding Developer → 403; PA
    mapping `organization_admin` on a catalog → 403 (the ceiling, step 2, refuses before the input step);
    OA (global) mapping `organization_admin` on a catalog → 422 `ROLE_MAPPING_INVALID` with
    `rule = "role_scope"` (step 3); PA on catalog A addressing B → 404; OA mapping
    a global `platform_owner` → 403; unmapping the only global PO → `last_platform_owner`; the seed group →
    `seeded_mapping`; a first mapping without a gid → `gid_required`; a second gid → `gid_mismatch`; a taken
    gid → `gid_taken` naming the holder; each refusal leaves rows and audit log unchanged), plus: a catalog
    list needs PA there and a global list needs OA, and neither lists another scope; a committed mapping
    change shows in the next `roles_for_groups` (no cache); a PA cannot remove an all-catalog row.
- Modify:
  - `src/huron/core/lake/ports.py`: `RoleMappingWriter` (`lock_mapping_scope`, `mapping`, `global_owners`,
    `group_gid`, `insert_group`, `put_mapping`, `delete_mapping`) and `RoleMappingLister` (`mappings`,
    `global_owners`). `LakeStore` gains `RoleMappingLister`; `LakeTransaction` gains `RoleMappingWriter`.
  - `src/huron/core/lake/errors.py`: `RoleMappingInvalid` (422, context `rule`, `value`) and
    `RoleMappingRefused` (409, context `reason`, `ldap_group`, and `posix_gid`, `current_gid` or `held_by`
    where they apply).
  - `src/huron/core/lake/__init__.py`: exports the mapping names and `PlatformOwnerSeed`.
  - `src/huron/core/security/broker/groups.py` (M5's): DT-6's element rule becomes the public
    `check_group_name(value)`; `parse_groups_response` calls it per element. `broker/__init__.py` exports it.
  - `src/huron/core/metastore/lake/role_mappings.py` (M4's read half): `InMemoryRoleMappings` gains the
    writer and lister methods over `LakeTables.ldap_groups` and `group_role_map`: the scope lock through M4's
    lock registry, one key per catalog id and one for the global scope (the fake's counterpart of D-1's
    `MAPPING_SCOPE` class, which M8's `locks.py` writes); `insert_group` as insert-if-absent then re-read;
    `ldap_groups_gid_key` → `RoleMappingRefused(reason="gid_taken", held_by=…)`; `group_role_map_key`,
    `group_role_map_role`, `group_role_map_global_roles_are_global`, the group and catalog foreign keys and
    the `posix_gid > 0` CHECK as `IntegrityViolation`s; `put_mapping` rewrites `created_at` and
    `created_by`; `mappings` keyset by `ldap_group` joined to the group's gid and the catalog's name; the
    fake `group_role_map` row's `CatalogRef` (M4.2) becomes the catalog id joined to `InMemoryCatalogs`.
  - `src/huron/core/metastore/lake/memory.py`: the `ldap_groups` table and its gid secondary key.
  - `tests/unit/test_group_directory.py` (M5's): direct `check_group_name` cases (empty, 256 and 257
    characters, a control character, `CN=Ops/EU,OU=g` accepted).
  - `design/api.html` §7: DT-18's `ROLE_MAPPING_INVALID` and `ROLE_MAPPING_REFUSED` rows verbatim.
  - `tests/lake_store_contract.py` and `tests/unit/test_lake_memory_store.py`: the mapping write scenarios
    (DT-10's "shared scenarios gain the write methods": upsert per scope, gid insert-if-absent, gid clash
    naming the holder, delete, scope-exact listing order, the raw-rule refusals naming their constraints).
  - `tests/lake_store_contract.py`: M4.2's `LakeSeed` gains `catalog(ref: CatalogRef)`; `MemorySeed.catalog`
    writes a `CatalogRecord` row (with its version-1 `CatalogConfigRecord`, so the deferred
    `catalogs_current_config` link holds) into `LakeTables` directly. A catalog-scoped
    `role_mapping` now requires that row, because the fake joins it for the catalog's name. M4.2's
    role-mapping scenarios seed each catalog before mapping it; M8.4's `PostgresSeed.catalog` inserts the
    catalog with its config and schema rows, as the FKs require.
  - `tests/unit/test_lake_access.py` (the M4.3 cases; M7.3's cases move from `insert_catalog` to
    `LakeSeed.catalog`) and `tests/unit/test_token_exchange.py` (M5.6): each catalog-scoped mapping's
    catalog is seeded first.
- Design: "DT-10 design: Administration surfaces and bootstrap" → "DT-10 decisions", "DT-10 interfaces and
  contracts" → "`core/lake/admin.py`: role mappings" (order of checks, `apply_mapping`, invariants, `list`,
  errors, lifecycle), "DT-10 tests this design requires" (`test_lake_role_mappings.py` row); "DT-4 decisions"
  (G-5 key, L-34, Visibility) and "DT-4 interfaces and contracts" → "Logical tables"; "DT-17 resolved
  disagreements between sections" (D-1, D-2, D-6); "DT-17 port → adapter → fake" (`RoleMappingLister`,
  `RoleMappingWriter` rows); "DT-17 DDL: `0015_lake_catalog`" (`ldap_groups`, `group_role_map`).
- Verification:
  - The plan-wide gate; `uv run lint-imports` keeps all 18 contracts (`_impl/mappings.py` is imported only by
    `huron.core.lake`); `uv run pytest tests/unit/test_error_contract.py` passes with both codes live.
  - `uv run pytest tests/unit/test_lake_role_mappings.py tests/unit/test_group_directory.py
    tests/unit/test_lake_memory_store.py tests/unit/test_lake_access.py tests/unit/test_token_exchange.py -q`
    passes (the catalog-scoped mappings of M4.2, M4.3, M5.6 and M7.3 seeded on joined catalogs).
  - `rg -n "hashtextextended|request_access_reset" src` prints nothing (D-1's single scheme is M8's; the
    reset call is M11's); `rg -n "core\.security\._impl|bindings|bootstrap_platform_owner" src/huron/core/lake`
    prints nothing (the lake imports no legacy RBAC).
  - Every created or modified file at 100 % line coverage.
- Dependencies: M7.1, M7.3, M4, M5.
- Decisions: OQ-4.1 (settled, owner decision 12)
- Decisions: OQ-4.2 (settled, owner decision 12)
- Decisions: OQ-10.1 (settled, owner decision 12)
- Decisions: OQ-10.2 (settled, owner decision 12)
- Status: pending

### M7.7 Signing-key administration: list, rotate and withdraw

- Intent: the write half of DT-5's key store as one audited Platform Owner operation: `rotate` follows
  DT-5's procedure (load the key, refresh the ring, `plan_rotation`, update-then-insert, `key_rotate`,
  refresh after commit), `withdraw` removes a still-pending key and re-opens its predecessor (OQ-5.2 (a)),
  and `list` shows the unexpired keys with their state.
- Delete: none.
- Create:
  - `tests/unit/test_lake_signing_key_admin.py` (marker `unit`, `InMemoryLakeStore`, M3's fixed test keys
    and in-memory key source from `tests/lake_tokens.py`, `FakeClock`): every case of DT-10's
    `test_lake_signing_key_admin.py` row (rotate at the default lead → the old key's `retired_at` equals the
    new `active_from` and one `key_rotate` entry; rotate again → `pending_key_exists`; withdraw the pending
    key → the predecessor's `retired_at` is cleared and one `key_withdraw` entry; withdraw inside
    `MAX_RING_AGE` of `active_from` → `not_pending`; all three operations 403 for an Organization Admin),
    plus: an unloadable `private_ref` → `key_unloadable` with nothing written; a reused ref →
    `key_already_registered`; a lost race (zero rows retired) → `concurrent_rotation`; a replayed rotation
    answers the first key's view and writes nothing, another body under the key →
    `IDEMPOTENCY_KEY_REUSED`; a failing refresh after commit is logged through stdlib `logging` and the
    answer still returns; an unknown `kid` on withdraw → 404.
- Modify:
  - `src/huron/core/lake/admin.py`: `SigningKeyView` and `SigningKeyAdmin(store, keys, source, clock)` with
    `list`, `rotate`, `withdraw`. `rotate`'s receipt is `Replay("signing_key", uuid.uuid5(<module
    constant namespace>, kid))`, and a replay answers the view of the row whose `kid` maps to that receipt,
    read through `SigningKeyReader.unexpired` with the earliest instant (the table holds a handful of rows).
    The design keys the receipt by UUID and the key by `kid` without saying how one names the other; this
    mapping is the plan's (Risk register).
  - `src/huron/core/lake/ports.py`: `SigningKeyWriter` (`any_signing_key`, `insert_initial_key`,
    `apply_rotation`, `withdraw_pending`); `LakeTransaction` gains it.
  - `src/huron/core/metastore/lake/signing_keys.py` (M4's read half): `InMemorySigningKeys` gains the writer
    methods: `apply_rotation` retires then inserts (zero rows retired → `RotationRefused(reason=
    "concurrent_rotation")`; the `kid` primary key or `signing_keys_private_ref_key` →
    `RotationRefused(reason="key_already_registered")`; overlap with another signing interval →
    `signing_keys_one_signer`, mapped to DT-5's `RotationRefused`); `withdraw_pending` deletes first and then
    re-opens exactly one predecessor; `insert_initial_key` inserts the first row.
  - `src/huron/core/lake/__init__.py`: exports `SigningKeyAdmin` and `SigningKeyView`.
  - `tests/lake_store_contract.py` and `tests/unit/test_lake_memory_store.py`: the signing-key write
    scenarios (update-then-insert keeps one signer at every instant; delete-then-reopen restores
    contiguity; the two refusals mapped above).
- Design: "DT-10 interfaces and contracts" → "`core/lake/admin.py`: signing-key administration (the write
  half of DT-5's key store)"; "DT-10 tests this design requires" (`test_lake_signing_key_admin.py` row);
  "DT-5 design: …" → "DT-5 signing keys: logical shape and lifecycle", "DT-5 interfaces and contracts"
  (`plan_rotation`, `KeyRing`, `HuronKeys.refresh`, `RotationRefused`), "DT-5 failure behaviour"; "DT-17
  interfaces and contracts" (signing-key constraint mapping); "DT-17 port → adapter → fake"
  (`SigningKeyWriter`).
- Verification:
  - The plan-wide gate; `uv run lint-imports` keeps all 18 contracts (no `structlog` in `huron.core.lake`,
    contract 10).
  - `uv run pytest tests/unit/test_lake_signing_key_admin.py tests/unit/test_lake_memory_store.py -q`
    passes.
  - `rg -n "revoked_at|revoke" src/huron/core/lake src/huron/core/metastore/lake` prints nothing (no
    revocation in v1).
  - Every created or modified file at 100 % line coverage.
- Dependencies: M7.1, M7.6 (`admin.py`), M3, M4.
- Decisions: OQ-1.1 (settled, owner decision 12)
- Decisions: OQ-5.2 (settled, owner decision 12)
- Status: pending

### M7.8 Lake bootstrap: first key, org base and the Platform Owner seed

- Intent: DT-10's idempotent "ensure" as one operation that M9's lifespan runs before `HuronKeys` is
  entered: under one bootstrap lock it makes (K) a signing key exist, (S) `org` version 1 exist (from
  `org-base-v1.json`) and (P) the seed group hold the global Platform Owner mapping with its gid, each
  missing fact written with exactly one `system:bootstrap` entry; without a seed it refuses an
  unadministrable lake.
- Delete: none.
- Create:
  - `tests/unit/test_lake_bootstrap.py` (marker `unit`, `InMemoryLakeStore`, M3's test key source): every
    case of DT-10's `test_lake_bootstrap.py` rows (`test_fresh_install_then_rerun_is_a_no_op`: the three
    entries `key_rotate` with `retired_kid` null, `schema_publish` (`org`, 1) and `role_map` (`owners`,
    NULL, null → `platform_owner`, 70001), all by `system:bootstrap`, and a second `run()` leaves every
    table, the audit log included, equal; `test_seed_promotes_a_lower_global_role`; `test_refusals` with
    `no_platform_owner`, `seed_gid_mismatch`, `seed_gid_taken`, `no_initial_key` and no mapping row written
    for the gid cases; `test_no_seed_with_an_existing_owner_starts`), plus `SigningKeyUnavailable` from an
    unloadable `initial_key` propagating, and two concurrent `run()` calls on one store serialized by the
    bootstrap lock (one set of entries).
- Modify:
  - `src/huron/core/lake/admin.py`: `BootstrapRefused(RuntimeError)` with `reason`, `LakeBootstrap(store,
    schemas, source, clock, *, initial_key, seed)` with `run()`, and the private `_SYSTEM_ACTOR` used only in
    step 2. Step 2 loads `org-base-v1.json` with `huron.schema.load_schema` and publishes it through
    `MetadataSchemas.publish` with the claim `IdempotencyClaim(SYSTEM_BOOTSTRAP, "bootstrap:org:1",
    request_sha256(...))`; step 3 calls `apply_mapping` with a permit that allows, mapping `gid_mismatch` and
    `gid_taken` to `BootstrapRefused`.
  - `src/huron/core/lake/ports.py`: `BootstrapLock` (`bootstrap_lock()`); `LakeStore` gains it.
  - `src/huron/core/metastore/lake/memory.py`: `InMemoryLakeStore.bootstrap_lock()` over one
    `asyncio.Lock`.
  - `src/huron/core/lake/__init__.py`: exports `LakeBootstrap` and `BootstrapRefused`.
  - `pyproject.toml`: `[tool.ruff.lint.per-file-ignores]` gains `"src/huron/core/lake/admin.py" =
    ["N818"]` (DT-10 names `BootstrapRefused`, a `RuntimeError` without an `Error` suffix).
- Design: "DT-10 decisions" (Bootstrap rule, Seed absent, Legacy bootstrap); "DT-10 interfaces and
  contracts" → "`core/lake/admin.py`: the startup bootstrap" (the bootstrap rule, steps 1–3,
  `_SYSTEM_ACTOR`; not "Composition", "Settings added" or "Operating it", which are M9's); "DT-10 tests this
  design requires" (`test_lake_bootstrap.py` rows); "DT-7 decisions" (Bootstrap); "DT-9 decisions" (Org
  base content); "DT-17 resolved disagreements between sections" (D-1, `bootstrap_lock`).
- Verification:
  - The plan-wide gate; `uv run lint-imports` keeps all 18 contracts.
  - `uv run pytest tests/unit/test_lake_bootstrap.py -q` passes.
  - `rg -n "bootstrap_platform_owner|_impl\.bootstrap" src/huron/core/lake` prints nothing (no shared code
    with the legacy seed); `rg -n "LakeBootstrap" src/huron/applications` prints nothing (wiring is M9's).
  - Every created or modified file at 100 % line coverage.
- Dependencies: M7.2, M7.6, M7.7.
- Decisions: OQ-4.1 (settled, owner decision 12)
- Decisions: OQ-9.2 (settled, owner decision 12)
- Decisions: OQ-10.1 (settled, owner decision 12)
- Status: pending

## Milestone 8 — Lake persistence, revision 0015

Spec steps 1 and 2 get their storage. The milestone adds the shared migrate helper, revision
`0015_lake_catalog` with the `lake` section of the schema map, and every PostgreSQL half that writes those
ten tables. The halves are composed into `PostgresLakeStore` and `PostgresLakeTransaction` behind one pool
boundary, which turns connection-class failures into `DependencyUnavailable("database")`. The API then
gains its single store member, `ApiStores.lake`, and `/readyz` probes it. The in-memory halves and the
domain operations already exist (M4, M7). This milestone proves them on `postgres:16` through the shared
scenarios in `tests/lake_store_contract.py`. No lifespan builds a lake service yet (that is M9). When the
milestone ends, every 0015 table has a writer, a fake and a contract test (plan-wide "Migrations and the
schema map").

### M8.1 One migrate helper: `tests/postgres.py`

- Intent: replace the per-module `_migrate` copies with DT-17's single Alembic helper before any lake
  contract module exists. From then on, every lake contract test, the integration tier and the `0014`
  retirement test migrate through one function. Constraint proofs go through `tests/postgres.py` only
  (plan-wide "Migrations and the schema map").
- Delete: no whole file. Symbols: the `_migrate` function and its module-level `MIGRATIONS_DIR` in
  `tests/contract/test_auth_store.py`, `tests/contract/test_hierarchy_store.py`,
  `tests/contract/test_rbac_store.py` and, if D2-5 kept it, `tests/contract/test_catalog_store.py`; the
  line `from tests.contract.test_hierarchy_store import _migrate` in `tests/integration/conftest.py`; every
  Alembic `Config` that `tests/contract/test_retire_legacy_raw.py` (M1) builds for itself.
- Create:
  - `tests/postgres.py`, a support module with no `test_` function. It holds `MIGRATIONS_DIR: Final[Path]`;
    `PostgresUrls` (frozen, slotted: `sqlalchemy`, `asyncpg`); `migrate(sqlalchemy_url, revision="head")`
    (`command.upgrade`); `downgrade(sqlalchemy_url, revision)` (`command.downgrade`); and the context
    manager `migrated_postgres(revision="head") -> Iterator[PostgresUrls]` over
    `PostgresContainer("postgres:16")`. The signatures are exactly DT-17's (owner decision 11, B-5).
- Modify:
  - The four contract modules call `migrated_postgres()` (owner decision 11, B-18).
  - `tests/integration/conftest.py` `catalog_database` is built on `migrated_postgres()`.
  - `tests/contract/test_retire_legacy_raw.py` uses `migrate` and `downgrade`, with no opt-in case (owner
    decision 11, B-5). Its `test_offline_sql_renders_the_drops` (M1.7) cannot go through either helper,
    because a revision range is valid only offline. It renders through the Alembic CLI in a subprocess,
    with no `Config` and no `command.` call:
    `subprocess.run([sys.executable, "-m", "alembic", "upgrade", "0013_retire_releases:0014_retire_legacy_raw", "--sql"], cwd=MIGRATIONS_DIR.parent, capture_output=True, text=True, check=True)`,
    and asserts the `DROP` statements in its stdout.
- Design: "DT-17 the shared migrate helper and the tests" (the helper block and its first bullet); "DT-17
  deletions" (first bullet); Current State "Conventions the design must follow", item 10.
- Verification:
  - The plan-wide gate. `uv run lint-imports` keeps all 18 contracts.
  - `rg -n 'def _migrate|^MIGRATIONS_DIR|command\.(upgrade|downgrade)' tests` prints lines of
    `tests/postgres.py` only, and `rg -n 'alembic\.config|Config\(' tests/contract/test_retire_legacy_raw.py`
    prints nothing.
  - `rg -n '^def test_' tests/postgres.py` prints nothing; `rg -n "0013_retire_releases" tests/contract/test_catalog_store.py`
    prints nothing (owner decision 11, B-18).
  - `uv run pytest -m "contract or integration" --collect-only -q` reports the same test count before and
    after the task (record both), and both suites pass.
- Dependencies: M1.
- Status: pending

### M8.2 Revision `0015_lake_catalog`, `refuse_if_rows` and the `lake` map

- Intent: create schema `lake` with the step 1–2 tables exactly as DT-17 writes them: DT-7's audit block
  spliced in, and `<SEGMENT>` written as the literal text of `huron.schema.naming.SEGMENT_PATTERN`. Add
  the downgrade guard that every lake revision shares, and the `lake` section of the schema map. No
  adapter exists yet, so each constraint, trigger and seed is proved on `postgres:16` with raw SQL.
- Delete: none.
- Create:
  - `migrations/versions/0015_lake_catalog.py`: `revision = "0015_lake_catalog"`,
    `down_revision = "0014_retire_legacy_raw"`, and a module docstring that names the invariants.
    - `upgrade()` runs one triple-quoted block through `execute_sql`, in DT-17's creation order. Seeds are
      literal `INSERT`s (`lake.roles`, and `lake.audit_actions` with `key_withdraw`), and nothing imports
      `huron`.
    - `downgrade()` first calls `refuse_if_rows("lake.group_role_map", "lake.catalog_configs",
      "lake.catalogs", "lake.metadata_schemas", "lake.idempotency_records", "lake.audit_log",
      "lake.signing_keys", "lake.ldap_groups")`, children before the parents their foreign keys name, so
      the guard names the table under test rather than a parent row its FK required. It then drops the
      objects in reverse order.
  - `tests/contract/conftest.py`:
    - the module-scoped `lake_db` fixture over `tests.postgres.migrated_postgres()`, one container per
      module;
    - the helper that truncates the non-seeded lake tables. It leaves out `lake.audit_log`, which refuses
      `TRUNCATE`.
  - `tests/contract/test_lake_schema.py` (marker `contract`) holds the 0015 cases of DT-17's contract
    table:
    - `test_upgrade_downgrade_round_trip`. Every case runs in a fresh database (its own `CREATE DATABASE`
      on the module's container, migrated through `tests.postgres.migrate`), because an `audit_log` row
      cannot be removed and would reach every later case:
      - on an empty database, `0014_retire_legacy_raw → head → 0014_retire_legacy_raw → head`, with
        exactly ten tables in schema `lake` after each upgrade (the count is the head's: M11.5 sets
        thirteen at `0016`, M13.4 sixteen at `0017`, M17.1 eighteen at `0018`);
      - for each writer table, in a database migrated to head, insert one row there plus the minimal rows
        its foreign keys require; `downgrade` raises `RuntimeError` naming the first table in the guard's
        list that holds a row, which is the table itself, except that a `lake.catalogs` row always comes
        with its `lake.catalog_configs` row and is reported as `lake.catalog_configs`; `alembic_version`
        stays at head;
      - the `-- Reflects:` stamp of `migrations/schema.sql` equals the head.
    - `test_audit_trigger`.
    - The 0015 part of `test_immutability_triggers`:
      - `catalog_configs` and `metadata_schemas` refuse `UPDATE` and `DELETE`;
      - `catalogs` refuse `DELETE`, a `name` change and a lower `config_version`;
      - a schema that extends an extension is refused, and so is an `org` row with an `extends_id`.
    - The `group_role_map` part of `test_nullable_key_uniqueness`.
    - The 0015 part of `test_settled_check_and_fks`:
      - a catalog without its config fails at `COMMIT` with 23503 (R17-6);
      - `signing_keys_one_signer` refuses a second open interval (R17-4).

    Each assertion names its constraint or trigger and its SQLSTATE. The namespace, collection, file and
    findings parts land with `0016`–`0018` (M11, M13, M17).
  - `tests/contract/test_lake_roles.py` (marker `contract`; DT-4's file):
    - `lake.roles` equals `Role` in both directions;
    - `lake.audit_actions` equals `AUDIT_VOCABULARY` in both directions;
    - the set in the `idempotency_records.replay_kind` CHECK is contained in `Replay.kind`;
    - DT-4's raw-insert refusals, each naming its constraint.

    The findings `code` case lands with `0018` (M17).
  - `tests/unit/test_lake_ddl_sync.py` (marker `unit`):
    - every segment CHECK in the lake revisions embeds `SEGMENT_PATTERN` verbatim (DT-8's DDL sync);
    - every `CREATE TABLE lake.<name>` in `migrations/versions/*_lake_*.py` appears in the `lake` section
      of `schema.sql`;
    - the `replay_kind` CHECK literals are a subset of `typing.get_args` of `Replay.kind`.
  - `docs/raw-lake/operations.md`: the page title "Operating the lake" and §1 "Database prerequisites"
    (DT-26 runbook row; DT-17's handoff to DT-26). Later tasks add the other sections; M19 adds the "Raw
    lake" navigation group (`make docs` builds pages outside the navigation, as it does `docs/adr/` today).
    The page has no section on upgrading from the Raw engine (owner decision 11, B-22).
- Modify:
  - `migrations/_ddl.py`: add `refuse_if_rows(*tables: str) -> None`, whose docstring says that table
    names are module literals and never input.
  - `migrations/schema.sql`:
    - set the stamp to `-- Reflects: 0015_lake_catalog`;
    - reword the header's "no metadata mirrors, no text search" (G-21, DT-25's handoff to DT-17) (M1.7
      already fixed D-9's `roles` note);
    - add the final section `-- ===== lake (0015_lake_catalog … 0018_lake_reconciler) =====`. It holds
      the ten tables in revision order, in the map's compressed style. Each CHECK, trigger and index gets
      a `-- [db]` note naming the invariant it serves, and each spec amendment a `-- [spec]` note;
    - give that section the header sentences that are true at 0015: catalog of record (ADR 0004),
      written only by `core/metastore/lake`, never references `public`, and `audit_log` is append-only by
      trigger. The `ltree` and `collections_metadata_gin` sentences land with `0016` (M11).
  - `src/huron/core/foundation/retry.py`: `Replay.kind` holds the three legacy kinds (`organization`,
    `project`, `dataset`; M1.4 removed the Raw kinds) and the five lake kinds: `catalog`,
    `metadata_schema`, `signing_key`, `collection` and `commit`: this task adds `collection` and `commit`
    (M7.1 added the other three), because the 0015 CHECK lists all five.
  - `design/layer-raw.html` §3 "Catalog model (`model`)" (DT-26: it lands with the first lake revision).
    The section links `migrations/schema.sql`.
  - `design/catalog-search.html` (`:423` at `fa51f46`, the "Mirrored to storage" bullet, located by text):
    `layer-raw.html#contracts` → `layer-raw.html#model` (DT-26 broken links, DT-17 row); nothing to do if
    M7.2 removed the sentence.
- Design:
  - "DT-17 decisions";
  - "DT-17 revision list";
  - "DT-17 DDL: `0015_lake_catalog`" and its three notes;
  - "DT-7 table, index and append-only trigger (DT-17 writes this into the first lake revision)";
  - "DT-17 the shared migrate helper and the tests" (the rows named above);
  - "DT-17 `migrations/schema.sql` and the import rules";
  - DT-4 "Tests this design requires" (seed drift and backstops);
  - "DT-8 tests this design requires" (DDL sync row);
  - "DT-26 design record pages: the Raw-facing six" (§3), "DT-26 the two new pages" (runbook §1), and
    "DT-26 developer docs, README and history" (the `schema.sql` row), "DT-26 broken links and their
    fixes" (the `catalog-search.html:423` row);
  - "DT-25 handoffs" (DT-17 row).
- Verification:
  - The plan-wide gate, which includes `scripts/check_schema_map.py`, then `make docs` and
    `git diff --check`.
  - `rg -n 'layer-raw\.html#contracts' design docs` prints nothing.
  - `uv run alembic heads` prints `0015_lake_catalog (head)`.
  - `uv run alembic upgrade 0014_retire_legacy_raw:0015_lake_catalog --sql` runs offline, exits 0, and
    prints `CREATE SCHEMA lake` before the first `CREATE TABLE lake.` (R17-8).
  - `uv run pytest -m contract tests/contract/test_lake_schema.py tests/contract/test_lake_roles.py` and
    `uv run pytest tests/unit/test_lake_ddl_sync.py` pass.
  - `rg -n '^(from|import) huron' migrations` prints nothing.
  - `rg -n 'COLLATE "C"' migrations/versions/0015_lake_catalog.py` hits `metadata_schemas.name` and
    `catalogs.name`.
  - `rg -n 'CREATE INDEX' migrations/versions/0015_lake_catalog.py` lists exactly
    `idempotency_records_expiry_idx`, `audit_log_object`, `metadata_schemas_extends_idx`,
    `catalog_configs_schema_idx` and `group_role_map_catalog_idx`. There is no index for administration
    entries (OQ-7.2 (a)).
- Dependencies: M8.1; M1 (`0014_retire_legacy_raw`), M3 (`Role`), M6 (`SEGMENT_PATTERN`), M7
  (`AUDIT_VOCABULARY`).
- Decisions: OQ-1.1 (settled, owner decision 12)
- Decisions: OQ-4.1 (settled, owner decision 12)
- Decisions: OQ-4.2 (settled, owner decision 12)
- Decisions: OQ-5.2 (settled, owner decision 12)
- Decisions: OQ-7.1 (settled, owner decision 12)
- Decisions: OQ-7.2 (settled, owner decision 12)
- Decisions: OQ-8.3 (settled, owner decision 12)
- Decisions: OQ-17.1 (settled, owner decision 12)
- Decisions: OQ-17.2 (settled, owner decision 12)
- Status: pending

### M8.3 Pool boundary, lock key space, store root and transaction, and claims

- Intent: start the PostgreSQL side of the composite store with these pieces:
  - the connection boundary that every lake adapter method enters through (OQ-18.1 (a));
  - the repository's text-bound jsonb convention;
  - the single advisory-lock key space;
  - `PostgresLakeStore` and `PostgresLakeTransaction`, with the transaction lifecycle, `ping()` and
    `bootstrap_lock()`;
  - `PostgresClaims`, with `prune_claims` over `lake.idempotency_records`.
- Delete: none.
- Create, or extend where M4 or M7 already created the module for its in-memory half (names and contents
  are DT-17's):
  - `src/huron/core/metastore/lake/_db.py`: `Db`, the asyncpg surface that `Pool` and `Connection`
    share; `jsonb_param`, `jsonb_value` and `constraint_of(error) -> str`, beside the `LockContractBroken`
    that M7.3 put in this module for the fake.
  - `src/huron/core/metastore/lake/_pool.py`: `connection(pool)`, the async context manager of DT-18's
    outage boundary.
    - It turns these into foundation `DependencyUnavailable(dependency="database", reason=<class name>)`:
      `asyncpg.PostgresConnectionError`; `asyncpg.InterfaceError` from a closed connection; `OSError`;
      `TimeoutError` on acquire; `asyncpg.QueryCanceledError`.
    - Every other exception propagates unchanged.
  - `src/huron/core/metastore/lake/locks.py`: `LockClass` with DT-17's `MAPPING_SCOPE = 3` and
    `BOOTSTRAP = 4`, the two classes this milestone takes (M11.6 adds `LAYOUT = 1` and `METADATA_FILE = 2`
    with their first users), and `xact_lock(db, cls, key)`. These are the only places a lock class number
    is written.
  - `src/huron/core/metastore/lake/store.py`:
    - `PostgresLakeStore(pool, clock)`:
      - `transaction()` takes one connection through `connection()` and opens one `READ COMMITTED`
        transaction. The yielded object raises `RuntimeError` when used after the block.
      - `ping()` runs a single `SELECT 1`.
      - `bootstrap_lock()` holds the session-level `BOOTSTRAP` lock on one pooled connection and
        unlocks before releasing it, also on error.
      - `prune_claims(expired_before, *, limit)`.
    - `PostgresLakeTransaction(connection, clock)`, which only `transaction()` builds.
  - `src/huron/core/metastore/lake/idempotency.py`: `PostgresClaims`, next to M7's `InMemoryClaims`. It
    implements `RetryTransaction.claim` and `remember` on the transaction. TTL replacement uses the
    injected `Clock`, and a fingerprint conflict raises foundation `IdempotencyKeyReused`.
  - `tests/contract/test_lake_store.py` (marker `contract`, over `lake_db`) runs the claim and
    transaction-lifecycle scenarios of `tests/lake_store_contract.py` against `PostgresLakeStore`. It
    adds these PostgreSQL-only cases:
    - two pools' `bootstrap_lock()` blocks run one after the other;
    - a pool created with `min_size=0` against a port nothing listens on makes `ping()` and
      `transaction()` raise `DependencyUnavailable`, with `context["dependency"] == "database"`;
    - a unique violation inside a statement propagates as itself, not as a 503.
  - `tests/unit/test_lake_pool_boundary.py` (marker `unit`):
    - `connection()` over a stub pool, with one case for each mapped exception class and for
      `asyncpg.UniqueViolationError` and `ValueError`, which propagate;
    - `jsonb_param` and `jsonb_value` round-trip non-ASCII text, and `jsonb_param` refuses NaN;
    - `constraint_of` reads the constraint name.
- Modify:
  - `src/huron/core/metastore/lake/__init__.py` also exports `PostgresLakeStore` (`LockContractBroken` is
    exported since M7.3).
  - `src/huron/core/lake/ports.py`: `LakeStore` gains `prune_claims(expired_before, *, limit)`;
    `src/huron/core/metastore/lake/idempotency.py`'s in-memory root half implements it over
    `idempotency_records`, so both roots keep conforming.
  - `tests/lake_store_contract.py` gains the prune scenario (`prune_claims` deletes at most `limit` expired
    rows and keeps the unexpired ones), run on both adapters, and any claim or lifecycle scenario that M7
    did not write. Scenarios that need real concurrency are marked PostgreSQL-only in the scenario table.
- Design:
  - "DT-17 decisions" (Keys, Advisory locks, Store bundle, Adapter layout, Time);
  - "DT-17 target module layout";
  - "DT-17 interfaces and contracts": the store, the transaction, `LockClass`, `xact_lock`,
    `LockContractBroken`, **Lifecycle**, and **Correctness model** (constraint violations, time, encoding,
    reads on the root);
  - "DT-17 port → adapter → fake" (the `RetryTransaction` and `BootstrapLock` rows);
  - "DT-17 resolved disagreements between sections" D-1;
  - "DT-18 interfaces and contracts" → "Store outage boundary (OQ-18.1 (a))";
  - "DT-18 handoffs" (DT-17 row);
  - DT-10 "`core/lake/admin.py`: the startup bootstrap" (`BootstrapLock`).
- Verification:
  - The plan-wide gate. `uv run lint-imports` keeps 18 contracts, and contract 19 holds: no
    `huron.core.hierarchy` or legacy metastore import from `huron.core.metastore.lake`.
  - `uv run pytest -m contract tests/contract/test_lake_store.py` passes, and so does
    `uv run pytest tests/unit/test_lake_pool_boundary.py tests/unit/test_lake_memory_store.py`.
  - `uv run pytest -m "unit or contract" --cov=src/huron --cov-report=term-missing --cov-fail-under=0`
    shows `_db.py`, `_pool.py`, `locks.py`, `store.py` and `idempotency.py` at 100 %.
  - `rg -nP 'FROM (?!lake\.)\w+|JOIN (?!lake\.)\w+' src/huron/core/metastore/lake` prints nothing except
    CTE names.
  - `rg -n 'pg_advisory_xact_lock' src/huron/core/metastore/lake` prints `locks.py` only.
  - `rg -n 'set_type_codec|search_path' src/huron` prints nothing.
- Dependencies: M8.2; M4, M5 (`DependencyUnavailable` in foundation), M7.
- Decisions: OQ-1.1 (settled, owner decision 12)
- Decisions: OQ-18.1 (settled, owner decision 12)
- Status: pending

### M8.4 PostgreSQL role-mapping and signing-key halves

- Intent: add the PostgreSQL halves of the identity tables and compose them into the root and the
  transaction. `PostgresRoleMappings` carries DT-4's per-request read, and DT-10's lister and writer under
  the per-scope advisory lock. `PostgresSigningKeys` carries DT-5's reader, and DT-10's initial key,
  rotation and withdrawal. DT-5's constraint backstops are proved on `postgres:16`.
- Delete: none.
- Create or extend:
  - `src/huron/core/metastore/lake/role_mappings.py` gains `PostgresRoleMappings`, next to M4/M7's
    `InMemoryRoleMappings`:
    - `roles_for_groups`;
    - `RoleMappingLister.mappings` (keyset by `ldap_group`) and `global_owners`;
    - the writer methods `lock_mapping_scope` (D-1's two-key form through `locks.xact_lock`), `mapping`,
      `group_gid`, `insert_group`, `put_mapping` and `delete_mapping`.

    `mappings_for_catalog` (DT-11) belongs to M11.
  - `src/huron/core/metastore/lake/signing_keys.py` gains `PostgresSigningKeys`:
    - DT-5's `SigningKeyReader` methods;
    - DT-10's writer methods `any_signing_key`, `insert_initial_key`, `apply_rotation` (update, then
      insert) and `withdraw_pending`;
    - inside a savepoint, a primary-key or `signing_keys_private_ref_key` violation maps to DT-5's reason,
      and `signing_keys_one_signer` maps to `RotationRefused`.
  - `tests/contract/test_lake_signing_keys.py` (marker `contract`; DT-5's file):
    - the R5-2 backstops by raw SQL, each naming its constraint;
    - the order of the rotation statements;
    - a losing concurrent rotation updates 0 rows.
- Modify:
  - `src/huron/core/metastore/lake/store.py` composes both halves into `PostgresLakeStore` and
    `PostgresLakeTransaction`.
  - `tests/lake_store_contract.py`: `PostgresSeed`, the PostgreSQL implementation of M4.2's `LakeSeed`
    (`ldap_group`, `role_mapping`, `signing_key`, `remove_role_mapping`, and M7.6's `catalog(ref)`) by raw
    SQL on the test's pool, the one place the contract tier writes these tables directly.
    `PostgresSeed.catalog` inserts, in one transaction, the `lake.catalogs` row, its
    `lake.catalog_configs` row at `config_version` 1 (a minimal document that passes the table's CHECK;
    the deferred `catalogs_current_config` FK) and, when absent, the `org` version 1
    `lake.metadata_schemas` row the config's `schema_id` references, as the FKs require. A catalog-scoped
    `role_mapping` needs that row first, as it does on `MemorySeed` since M7.6.
  - `tests/contract/test_lake_store.py` runs the role-mapping and signing-key scenarios of
    `tests/lake_store_contract.py`. DT-4's "collection in an unreadable catalog" scenarios wait for
    collections (M11).
- Design:
  - "DT-17 port → adapter → fake" (the `RoleMappingReader`, `RoleMappingLister`/`RoleMappingWriter`,
    `SigningKeyReader` and `SigningKeyWriter` rows);
  - "DT-17 DDL: `0015_lake_catalog`" (the note on the `roles_for_groups` statement);
  - "DT-17 resolved disagreements between sections" D-1 and D-2;
  - "DT-17 interfaces and contracts" → **Correctness model** (constraint violations);
  - DT-4 "Logical tables (DT-17 writes the DDL; R4-2 proves the constraints)";
  - "DT-5 signing keys: logical shape and lifecycle", "`broker/keys.py`: keys, the ring, the source and
    the rotation rule", and "DT-5 tests this design requires" (`test_lake_signing_keys.py`);
  - DT-10 "`core/lake/admin.py`: role mappings" and "`core/lake/admin.py`: signing-key administration
    (the write half of DT-5's key store)".
- Verification:
  - The plan-wide gate.
  - `uv run pytest -m contract tests/contract/test_lake_signing_keys.py tests/contract/test_lake_store.py`
    passes.
  - The "unit or contract" coverage run shows `role_mappings.py` and `signing_keys.py` at 100 %.
  - `rg -n 'hashtextextended' src tests` prints nothing (D-1).
- Dependencies: M8.3; M3, M7.
- Decisions: OQ-4.1 (settled, owner decision 12)
- Decisions: OQ-4.2 (settled, owner decision 12)
- Decisions: OQ-5.2 (settled, owner decision 12)
- Status: pending

### M8.5 PostgreSQL audit, catalog and metadata-schema halves

- Intent: add the last 0015 writers:
  - `PostgresAudit`: DT-7's writer on the transaction and its `collection_log` read on the root (M16.1
    adds `collection_catalog`, the `AuditReader` port and the in-memory reader half);
  - `PostgresCatalogs`: a catalog and its immutable configs, published lock-then-check under the version
    guard;
  - `PostgresMetadataSchemas`: append-only schema versions.

  DT-7's, DT-8's and DT-9's PostgreSQL cases come with them, and so does the catalog half of DT-17's CAS
  race.
- Delete: none.
- Create or extend:
  - `src/huron/core/metastore/lake/audit.py` gains `PostgresAudit`:
    - `AuditWriter` appends with the `at` the writer supplies;
    - on the root, DT-7's adapter read
      `collection_log(collection_id: UUID, *, before: int | None, limit: int) -> Window[AuditRecord]`:
      the entries with `object_type = 'collection'` and `object_id` = the id, `id < before` when `before`
      is given, `ORDER BY id DESC`, fetching `limit + 1` for `has_more`, on `audit_log_object`. It is
      the only reader method this task writes; `collection_catalog`, the `AuditReader` port on
      `LakeStore` and the in-memory half are M16.1's;
    - no statement updates or deletes `lake.audit_log`.
  - `src/huron/core/metastore/lake/catalogs.py` gains `PostgresCatalogs` and `PostgresMetadataSchemas`:
    - `CatalogStore` (M7.3's port): `get_ref`, `current`, `config`, and
      `catalogs(readable, after, limit)`, keyset by `name` with `ReadableCatalogs` applied in SQL before
      `LIMIT`;
    - `CatalogWriter` (M7.3's port; the head's "Catalog and schema store methods" resolution):
      - `insert_catalog(record, config)` inserts the catalog and its version-1 config under the deferred
        FK, and maps `catalogs_name_key` to `CatalogExists` in a savepoint;
      - `lock_catalog_config(catalog_id)` runs `SELECT config_version … FOR UPDATE` and records the
        version it returns;
      - `append_config(config)` inserts version N+1 and runs
        `UPDATE … WHERE id = $1 AND config_version = $2` with the recorded version; zero rows or an id
        that was not locked raise `LockContractBroken`;
    - `MetadataSchemaStore` (`by_ref`, `by_id`, `latest`, `schemas(after, limit)`) and
      `MetadataSchemaWriter.insert_schema` (M7.2's port).
  - `tests/contract/test_lake_audit_store.py` (marker `contract`; DT-7's file):
    - `test_audit_log_rejects_update_delete_truncate`;
    - the FK half of `test_audit_vocabulary_matches_python`: an unseeded pair raises 23503 and leaves no
      row;
    - `test_audit_is_written_with_the_change`, on a catalog config publish. The collection form needs
      `lake.collections` (M11);
    - `test_collection_log_paging`, limited to its paging clauses through `PostgresAudit.collection_log`,
      over collection entries appended directly (the table has no FK to the collection row): seven
      entries across two collections; `limit=3` walks one collection newest first with no repeats or
      gaps; an entry committed between two page reads appears only at the head of a fresh read. Its
      `collection_catalog` clauses ("still answers after the collection row is deleted") land with M16.1,
      with the method.
- Modify:
  - `src/huron/core/metastore/lake/store.py` composes the three halves.
  - `tests/contract/test_lake_store.py` runs the audit, catalog and metadata-schema scenarios of
    `tests/lake_store_contract.py`. They include DT-8's catalogs row, and DT-9's `MetadataSchemas` and
    `lake.metadata_schemas` rows (`content_identity(row.json_schema) == row.sha256` after the jsonb round
    trip, over Hypothesis JSON).
  - `tests/contract/test_lake_schema.py` gains the catalog half of `test_etag_cas_race`, a named race
    test. The collection half lands with M11.
    - Two concurrent publishes carry the same `If-Match: N`. The second blocks until the first commits,
      then reads `N+1`, and the domain refuses it with 412 `PRECONDITION_FAILED`.
    - `append_config` without `lock_catalog_config` raises `LockContractBroken`, and so does a stale
      recorded version.
- Design:
  - "DT-17 port → adapter → fake" (the `AuditWriter`/`AuditReader`, `CatalogStore`/`CatalogWriter` and
    `MetadataSchemaStore`/`MetadataSchemaWriter` rows);
  - "DT-17 interfaces and contracts" → **Correctness model**;
  - "DT-17 the shared migrate helper and the tests" (`test_etag_cas_race`);
  - "DT-7 interfaces and contracts" (the writer seam, the reader) and "DT-7 tests this design requires";
  - DT-8 "`huron.core.lake.catalogs`: catalog operations and naming application", "`lake.catalogs` and
    `lake.catalog_configs`: logical shapes", and "DT-8 tests this design requires" (catalogs row);
  - DT-9 "`lake.metadata_schemas`: logical shape" and the DT-9 test rows named above;
  - "DT-18 paging keys and the `label` filter" (the orders of rows 4 and 17).
- Verification:
  - The plan-wide gate.
  - `uv run pytest -m contract tests/contract/test_lake_audit_store.py tests/contract/test_lake_store.py
    tests/contract/test_lake_schema.py` passes.
  - The "unit or contract" coverage run shows `audit.py` and `catalogs.py` at 100 %.
  - `rg -n 'UPDATE lake\.audit_log|DELETE FROM lake\.audit_log|TRUNCATE lake\.audit_log' src/huron`
    prints nothing.
- Dependencies: M8.4; M7.
- Decisions: OQ-7.1 (settled, owner decision 12)
- Decisions: OQ-17.2 (settled, owner decision 12)
- Status: pending

### M8.6 The store complete: conformance, administration races and `ApiStores.lake`

- Intent: every 0015 half now exists. This task:
  - pins the four composites structurally;
  - proves DT-10's serialization on PostgreSQL;
  - gives the API its one lake store member, `ApiStores.lake`, which `/readyz` probes.

  The lifespan still builds no lake service (M9).
- Delete: none.
- Create:
  - `tests/contract/test_lake_admin_store.py` (marker `contract`; DT-10's file) holds three named race
    tests:
    - `test_concurrent_bootstrap`: two `LakeBootstrap.run()` calls on separate pools under
      `asyncio.gather` leave one signing key, one `org` row, one seed mapping and three audit entries;
    - `test_last_owner_race`;
    - `test_first_mapping_gid_race`.
- Modify:
  - `tests/unit/test_lake_ddl_sync.py`:
    - no two halves of `PostgresLakeStore`, `PostgresLakeTransaction`, `InMemoryLakeStore` or
      `InMemoryLakeTransaction` define the same public name;
    - no root or transaction has `LakeStore` or `LakeTransaction` in its MRO, following the
      `test_stores_conform_to_their_ports_structurally_not_by_inheritance` pattern;
    - a runtime conformance check, M4.1's `inspect.signature` form: every public member of `LakeStore`
      and of `LakeTransaction` exists, with the same parameter names and kinds, on `PostgresLakeStore`
      and `InMemoryLakeStore`, and on `PostgresLakeTransaction` and `InMemoryLakeTransaction`. (mypy and
      ty read `src` only, `[tool.mypy] files` and `[tool.ty.src] include` in `pyproject.toml`, so a typed
      assignment in a test is never type-checked.)
  - `src/huron/applications/api/runtime.py`:
    - `ApiStores.lake: LakeStore`;
    - `ApiRuntime.stores: ApiStores`, the bundle as wired, so that `/readyz` and the lake dependencies
      (M9) reach `runtime.stores.lake` as DT-18 spells it. DT-17's "`ApiRuntime` gains no store member"
      is read as "no per-port member"; record that reading under "Execution notes".
  - `src/huron/applications/api/app.py`:
    - `_postgres_stores` adds `lake=PostgresLakeStore(pool, clock)`;
    - `_build_runtime` publishes `stores`;
    - `_dependency_checks` adds `("lake", …)`, which calls `stores.lake.ping()` within
      `READINESS_TIMEOUT_SECONDS` and reports like the `database` check.
  - `tests/unit/support.py`: `memory_stores()` adds `lake=InMemoryLakeStore(clock=clock)`. Every test
    that builds `ApiStores(` or `ApiRuntime(` directly changes too (list them with `rg` at task start).
  - `tests/unit/test_api_app.py`:
    - `/readyz` is ready over the in-memory lake;
    - it reports the `lake` check (503 `DEPENDENCY_UNAVAILABLE`, `context.checks.lake`) when `ping()`
      raises, and when `ping()` hangs past the timeout;
    - `_postgres_stores` wires one `PostgresLakeStore` over the shared pool.
- Design:
  - "DT-17 `ApiStores` diff and `memory_stores()`";
  - "DT-17 resolved disagreements between sections" D-2;
  - "DT-17 deletions" (planned names that are not created);
  - "DT-17 the shared migrate helper and the tests" (the unit-tier paragraph);
  - "DT-18 interfaces and contracts" → "Composition and readiness" and "Lake service dependencies";
  - "DT-10 tests this design requires" (contract tier).
- Verification:
  - The plan-wide gate.
  - `uv run pytest -m contract tests/contract/test_lake_admin_store.py` passes.
  - D-2 holds: `rg -n '^\s+(role_mappings|signing_keys):' src/huron/applications/api/runtime.py` and
    `rg -n 'stores\.(role_mappings|signing_keys)' src tests` print nothing.
  - mypy and ty accept `_postgres_stores` building `ApiStores(lake=PostgresLakeStore(pool, clock))`; the
    in-memory side is covered by the runtime check, and `uv run pytest tests/unit/test_lake_ddl_sync.py`
    passes.
  - `uv run pytest -m integration` passes.
  - Every modified `src/` file is at 100 % in the unit run.
- Dependencies: M8.5; M7.
- Decisions: OQ-4.1 (settled, owner decision 12)
- Decisions: OQ-4.2 (settled, owner decision 12)
- Status: pending

## Milestone 9 — API composition for auth, catalogs and administration

This milestone wires spec steps 1 and 2 into the API.

- `ApiSettings` takes DT-18's identity, token and seed rows in place of `auth_mode` and `oidc`. The same
  change brings in the development environment those required settings need: DT-22's `company` realm,
  the `fake-ldap-groups` service, `make dev-keys`, `dev.env` and the stack probes.
- Every composed app then runs the lake lifespan. `LakeBootstrap` runs before `HuronKeys` is entered,
  then come the token issuer and verifier, the group directory, `TokenExchange` and
  `LakeAuthentication`.
- The public discovery documents and `POST /auth/exchange` arrive; M9.3 re-creates the `/auth` router,
  which M1.6 deleted with `/auth/session` and `/auth/providers`, with the exchange only (owner decision 11,
  B-13).
- The lake router under `/api/v1` sits behind `current_actor` (Huron JWT only). It serves DT-18's rows
  4–9 and 11–22: catalogs, configs, the composed schema, role mappings, metadata schemas and signing keys.
  Each row lands with its `design/api.html` §3 and §7 entries and DT-26's page lines.

Rows 10 and 23–37 belong to M11, M13, M16 and M17. When this milestone ends, the derived lake route set
has 18 members, all behind `current_actor`, and the OpenAPI tag set is the 11 legacy tags plus
`authentication`, `discovery`, `catalogs`, `role-mappings`, `metadata-schemas` and `signing-keys`, 17 in
all.

### M9.1 Identity settings and the development environment (one step)

- Intent: `ApiSettings` gains DT-6's `company_idp` and `group_directory`, DT-5's `tokens`, DT-10's
  `platform_owner_seed` and `dev_headers`, in place of `auth_mode` and `oidc`. The legacy company bearer
  is composed from `company_idp` and the group directory, with one company identity on both surfaces: the
  principal is the `subject_claim` value and its groups come from `GroupDirectory.groups_for` (owner
  decision 11, B-28). In the same change (DT-22's build order), the development environment
  gets what those required fields need:
  - the import of the `company` realm;
  - the `fake-ldap-groups` service;
  - the read-only key mount and `HURON_UID`;
  - `make dev-keys` with `scripts/dev_signing_key.py`;
  - the identity diff of `dev.env`;
  - the `groups` and `keys` probes.

  Nothing on the lake side starts yet.
- Delete:
  - Whole files (orchestrator `git rm`): `scripts/keycloak/huron-realm.json`.
  - Symbols:
    - in `src/huron/applications/api/settings.py`: `OidcSettings`, `ApiSettings.auth_mode`,
      `ApiSettings.oidc`, and the refusals keyed on `auth_mode`;
    - in `app.py`: `_configure_oidc` (M5.5 already removed the `oidc_verify` keyword and the
      `OidcClient`/`JwksVerifier` wiring);
    - in `runtime.py`: the `auth_mode == "dev-headers"` branch;
    - in `tests/unit/test_api_settings.py`: the `auth_mode` and `HURON_OIDC__` cases;
    - in `docker-compose.yml`: the `huron-realm.json` mount, and the comment's references to the
      `huron-web` secret and the "flow secret";
    - in `dev.env`: `HURON_AUTH_MODE`, `HURON_OIDC__ISSUER` and `HURON_OIDC__CLIENT_ID`; M1.6 already
      deleted the other four variables DT-22's table removes (owner decision 11, B-16);
    - in `scripts/check-stack.sh`: the `realms/huron` probe and its issuer string.
- Create:
  - `scripts/dev_signing_key.py`, with DT-22's contract, options, exit codes and messages.
  - `tests/unit/test_dev_signing_key.py` (marker `unit`). It loads the script through `importlib.util`,
    as `test_check_schema_map.py` does, and checks:
    - the created directory and file modes;
    - a second run prints `exists` and leaves the bytes unchanged;
    - refusals of a `0750` directory, a path-shaped `--name` and a target that is not a regular file;
    - the key loads through M3's `FileSigningKeySource`, and its `kid` is the thumbprint.
- Modify:
  - `src/huron/applications/api/settings.py`:
    - `CompanyIdpSettings` (no `groups_claim`; `subject_claim` serves the exchange and the legacy bearer)
      and `GroupDirectorySettings` (DT-6), and `TokenSettings` (DT-5) (owner decision 11, B-28);
    - the fields `dev_headers`, `company_idp`, `group_directory`, `tokens` and
      `platform_owner_seed: PlatformOwnerSeed | None` (M7's `huron.core.lake.admin.PlatformOwnerSeed`;
      both fields or neither);
    - startup refusals 1 and 2 of DT-18's list, in that order: DT-6's refusals, then DT-5's `tokens`
      refusals;
    - docstrings.
  - `src/huron/core/security/oidc.py` (DT-6 "`oidc.py`: the legacy bearer, re-wired"):
    `OidcResolver(verify, groups: GroupDirectory, *, subject_claim: str)` names the principal by
    `subject_claim`, fullmatched against `COMPANY_USERNAME` as M5.5 left it, and takes its groups from
    `await groups.groups_for(subject)`: `None` raises `AuthError` (401) and `DependencyUnavailable`
    propagates (503). The `groups_claim` parameter and attribute are deleted, and the module docstring
    follows (owner decision 11, B-28).
  - `src/huron/applications/api/app.py`:
    - `create_app` keeps M5.5's keywords `company_idp_transport=None` and `clock=None` (`clock` defaults to
      `SystemClock()`; M5.5 recorded it under "Execution notes" as the seam DT-22's root `clock` fixture
      needs) and gains `group_directory_transport=None`.
    - The lifespan holds an `AsyncExitStack` that owns the pool,
      `company_http = httpx.AsyncClient(transport=company_idp_transport,
      timeout=settings.company_idp.timeout_seconds)` and `directory_http` over
      `group_directory_transport`.
    - `CompanyTokenVerifier(company_http, issuer=…, audiences=frozenset(…), clock=clock)`, one
      `directory = HttpGroupDirectory(directory_http, …)` (M9.2's `TokenExchange` shares it) and
      `OidcResolver(company_tokens.verify, directory, subject_claim=settings.company_idp.subject_claim)`
      replace `_configure_oidc`; `groups_claim` is deleted (owner decision 11, B-28).
  - `src/huron/applications/api/runtime.py`: `ApiRuntime.oidc_resolver: OidcResolver` becomes
    non-optional; `settings.dev_headers` selects the dev-header resolver.
  - `tests/unit/support.py`: `FAKE_GROUPS_URL`, `SEED_GROUP`, `SEED_GID`, and
    `lake_settings(**overrides) -> ApiSettings` with the identity half of DT-22.
  - `tests/unit/conftest.py`'s `client` fixture, and every test that builds `ApiSettings(` (list them
    with `rg` at task start), build through `lake_settings(…)`. Where they set
    `auth_mode="dev-headers"` they now set `dev_headers=True`.
  - `tests/unit/test_api_settings.py`: one case for each added refusal, and the boundary that passes.
  - `tests/unit/test_api_main.py`, which builds settings from the environment and so escapes the
    `ApiSettings(` sweep: the import case drops `HURON_AUTH_MODE` and sets `HURON_COMPANY_IDP__ISSUER`,
    `HURON_COMPANY_IDP__AUDIENCES`, `HURON_GROUP_DIRECTORY__URL_TEMPLATE`, `HURON_TOKENS__ISSUER` and
    `HURON_TOKENS__KEY_DIRECTORY`; the no-environment case's cleared list drops `HURON_AUTH_MODE` and
    gains the same five names.
  - `tests/unit/test_auth_oidc.py`: the `OidcResolver` cases take their groups from a `GroupDirectory`
    stub (or `fake_groups_transport`) instead of a token `groups` claim, with an unknown user (401) and
    an outage (`DependencyUnavailable`) case; `CLIENT_ID = "huron-web"` goes.
  - `tests/unit/test_authorization_credentials.py` and `tests/unit/test_security_authentication.py`:
    their `OidcResolver(…)` constructions gain the directory stub as the second argument.
  - `tests/unit/test_api_oidc.py`: the legacy bearer cases go through
    `create_app(…, company_idp_transport=fake_issuer_transport,
    group_directory_transport=fake_groups_transport, clock=clock)` and use the fake issuer's
    `id_token(…)`: `karl`'s token resolves to principal `karl` with the directory's groups; a user the
    directory does not know answers 401 `INVALID_CREDENTIAL` and a directory outage answers 503
    `DEPENDENCY_UNAVAILABLE` on a legacy route (owner decision 11, B-28).
  - `tests/unit/test_api_app.py`: the lifespan cases about OIDC discovery become company-client cases. The
    client closes at shutdown and on a failed startup, and a pool that is already open still closes.
  - `tests/unit/test_fake_identities.py`: adds DT-22's **Seed** case, because `dev.env` gets the seed values
    here: `HURON_PLATFORM_OWNER_SEED__GROUP` is a group of a fixture user, and
    `HURON_BOOTSTRAP_PLATFORM_OWNER` is a fixture username (owner decision 11, B-28, which revises DT-22's
    "fixture `id`").
  - `docker-compose.yml`, `Makefile`, `dev.env` and `scripts/check-stack.sh` follow DT-22's outline and
    tables, with three exceptions:
    - the readiness message of `check-stack.sh api` changes in M9.2, with the check that makes it true;
    - the `volume` pieces belong to M11;
    - the three CLI variables in `dev.env` and their header sentence belong to M10, whose `huron` command
      reads them.

    `HURON_BOOTSTRAP_PLATFORM_OWNER` stays `karl` (legacy surface; a company username), not karl's
    fixture `sub` (owner decision 11, B-28).
  - `design/auth.html` §6 "Local development" (DT-26: the DT-22 mocks task).
  - `docs/getting-started/local-development.md`:
    - Prerequisites and Compose stack: `make hosts`; `keycloak` with the `company` realm;
      `fake-ldap-groups`; no `realms/huron` and no `huron-web`;
    - "Running the API": the rows for the company issuer, the groups endpoint and the signing-key
      directory;
    - "Authenticating in development": dev headers work only on legacy `/api/v1`, behind `dev_headers`;
    - the new section "Raw lake development": the `make dev-keys` lines (`KEY=` included), the users and
      their development passwords, and `make keycloak-reset` after realm edits.
- Design:
  - DT-6 "Settings diff, startup refusals and composition", "`oidc.py`: the legacy bearer, re-wired" and
    "DT-6 deletions" (the settings, `app.py`, `runtime.py` and test items);
  - DT-5 "Settings, composition, errors and readiness" (`TokenSettings` and its refusals);
  - DT-10 "`core/lake/admin.py`: the startup bootstrap" (settings added);
  - "DT-18 settings: the merged `ApiSettings` diff" (rows `dev_headers` through `platform_owner_seed`,
    refusals 1–2);
  - "DT-22 decisions", "`tests/conftest.py` and `tests/unit/support.py`: how tests obtain the fakes",
    "`scripts/dev_signing_key.py` and `make dev-keys`", "The no-bypass rule", "DT-22 compose, Makefile,
    `dev.env` and `check-stack.sh`", "DT-22 deletions", and the build order in "DT-22 handoffs";
  - "DT-26 design record pages: the Raw-facing six" (`auth.html` §6) and "DT-26 developer docs, README
    and history" (the `local-development.md` rows).
- Skills: `fastapi` (`applications/api`); `oop-design` (`core/security/oidc.py`).
- Verification:
  - The plan-wide gate, then `make docs` and `bash -n scripts/check-stack.sh`.
  - `uv run pytest tests/unit/test_dev_signing_key.py tests/unit/test_api_settings.py
    tests/unit/test_fake_identities.py tests/unit/test_api_oidc.py tests/unit/test_api_app.py
    tests/unit/test_api_main.py tests/unit/test_auth_oidc.py tests/unit/test_authorization_credentials.py
    tests/unit/test_security_authentication.py` passes.
  - `docker compose config --quiet` exits 0.
  - `make -n up stack dev-keys api` shows:
    - `dev-keys` runs before the commands of `stack` and `api`;
    - `up` builds and starts `fake-ldap-groups`.

    `make -n` never prints `export` directives, so the exports are checked apart:
    `rg -n '^export HURON_(UID|GID) := \$\(shell id -[ug]\)' Makefile` prints two lines, and
    `make -pn up | rg '^HURON_(UID|GID) :?='` shows both variables defined. Do not start the owner's
    stack.
  - `uv run --env-file dev.env python -c "from huron.applications.api.settings import
    settings_from_environment as s; s()"` exits 0. This shows that the settings `make api` reads
    validate.
  - `test ! -e scripts/keycloak/huron-realm.json`.
  - `rg -n 'realms/huron|huron-web|huron-realm' docker-compose.yml Makefile dev.env scripts src tests docs
    design/auth.html` prints nothing.
  - `rg -n 'auth_mode|AUTH_MODE|HURON_OIDC__|oidc_verify|OidcSettings|groups_claim' src tests scripts dev.env`
    prints nothing; `rg -n '^HURON_BOOTSTRAP_PLATFORM_OWNER=karl$' dev.env` prints one line (owner
    decision 11, B-28).
  - DT-22's closing check,
    `rg -n "monkeypatch\.setattr\((jwt|httpx|.*PyJWKClient|.*(Verifier|GroupDirectory|OidcProvider))" tests`,
    prints nothing.
  - Every modified `src/` file is at 100 % in the unit run.
- Dependencies: M8.6; M3, M5, M7.
- Decisions: OQ-22.1 (settled, owner decision 12)
- Status: pending

### M9.2 The lake lifespan: bootstrap, signing keys, tokens and the exchange workflow

- Intent: every app now starts the lake.
  - `LakeBootstrap` makes sure the first signing key, `org` version 1 and the seeded Platform Owner
    mapping exist before `HuronKeys` is entered.
  - The token issuer and verifier, the group directory, `TokenExchange` and `LakeAuthentication` are
    built once, over `stores.lake`.
  - `/readyz` reports `signing_keys`.

  No lake route exists yet.
- Delete: none.
- Modify:
  - `src/huron/applications/api/app.py`:
    - `create_app` gains the keyword `key_source: SigningKeySource | None = None`
      (`group_directory_transport` came with M9.1's legacy-bearer directory).
    - After the stores, inside the `AsyncExitStack`, the lifespan builds in this order:
      1. `MetadataSchemas(stores.lake, clock)` and `Validation(metadata_schemas)`.
      2. `LakeBootstrap(…).run()` with `source = key_source or FileSigningKeySource(…)`.
      3. `HuronKeys(stores.lake, source, clock)`, entered into the stack. Its first refresh may refuse
         startup.
      4. `HuronTokenIssuer` and `HuronTokenVerifier`.
      5. The one `HttpGroupDirectory` M9.1 built for the legacy bearer, so
         `OidcResolver(company_tokens.verify, directory, subject_claim=settings.company_idp.subject_claim)`
         and the exchange name one person with one group set (owner decision 11, B-28).
      6. `TokenExchange(company_tokens, directory, stores.lake, token_issuer, subject_claim=…)`.
      7. `LakeAuthentication(token_verifier, stores.lake)`.
    - The legacy `bootstrap_platform_owner(runtime.rbac, …)` call stays beside the bootstrap; its setting
      names a company username (owner decision 11, B-28).
    - `/readyz` gains the `signing_keys` check: a `keys.ring.signer(now)` that raises is a failure. The
      check reads the ring only.
  - `src/huron/applications/api/runtime.py`: `ApiRuntime` gains `keys`, `key_source`, `token_issuer`,
    `token_verifier`, `token_exchange`, `lake_authentication`, `metadata_schemas` and `validation`. These
    are policies built once. `RoleMappings`, `SigningKeyAdmin` and `Catalogs` are not members (DT-18,
    "Lake service dependencies").
  - Every `create_app(` call under `tests/`, and `tests/unit/conftest.py`'s `client` fixture, passes
    `key_source=InMemorySigningKeySource({TEST_KEY_REF: TEST_KEY})` from M3's `tests/lake_tokens.py`.
    Tests that check time also pass the root `clock`.
  - `tests/unit/test_api_app.py`:
    - a fresh in-memory start leaves (K), (S) and (P) in place, with exactly the entries `key_rotate`,
      `schema_publish` and `role_map` by `system:bootstrap`;
    - a second app over the same stores writes no row and no entry (OQ-10.1 (a));
    - `BootstrapRefused` (`no_initial_key`, `no_platform_owner`) and an unloadable `initial_key` refuse
      startup, and both clients and the pool still close;
    - `/readyz` reports `signing_keys` while the ring cannot sign;
    - `runtime.lake_authentication.authenticate` accepts a token from `mint(runtime.keys, clock)`. After
      its group's mapping is removed in the store, the same token's next authentication carries no grant.
  - `scripts/check-stack.sh`: the `api` message becomes "ready (database and signing keys)", as DT-22's
    table states. It is true from this task on.
  - `docs/raw-lake/operations.md` §3 "Deploying the API" (DT-26: the DT-10 bootstrap task) covers the
    signing-key Secret mounted with `defaultMode: 0400`, `envFrom` with the settings landed so far, and
    the seeded Platform Owner group (Owner decision 8). The volume mount line lands with M11 and the
    first `huron catalog apply` line with M10.
  - `docs/getting-started/local-development.md`, section "Raw lake development": the key-reset note.
- Design:
  - DT-5 "Settings, composition, errors and readiness" (the composition order, `/readyz`) and "DT-5
    failure behaviour" (the startup rows);
  - DT-6 "Settings diff, startup refusals and composition" (the composition bullets, the `create_app`
    seam);
  - DT-10 "`core/lake/admin.py`: the startup bootstrap" (composition);
  - DT-4 "`applications.api`: the lake credential dependency";
  - "DT-17 resolved disagreements between sections" D-2 (`stores.lake` as `SigningKeyReader` and
    `RoleMappingReader`);
  - "DT-18 interfaces and contracts" → "Lake service dependencies";
  - "DT-22 how each test tier reaches each mock" (unit and contract rows);
  - "DT-26 the two new pages" (runbook §3).
- Verification:
  - The plan-wide gate, then `make docs` and `bash -n scripts/check-stack.sh`.
  - `uv run pytest tests/unit/test_api_app.py` passes, and `uv run pytest -m integration` passes with
    the lake lifespan over PostgreSQL.
  - `rg -l 'create_app\(' tests | xargs rg --files-without-match key_source` prints nothing: every
    module that composes an app injects the key source.
  - Every modified `src/` file is at 100 % in the unit run.
- Dependencies: M9.1; M3, M4, M5, M7.
- Decisions: OQ-10.1 (settled, owner decision 12)
- Status: pending

### M9.3 Discovery and `POST /auth/exchange` (rows 1–3)

- Intent: add the two public discovery documents and the token-exchange route, re-creating the
  `routes/auth` package that M1.6 deleted with `/auth/session` and `/auth/providers`, so the `/auth`
  family is exactly `POST /auth/exchange` (RL step 1's gate) (owner decision 11, B-13).
- Delete: none.
- Create:
  - `src/huron/applications/api/routes/auth/__init__.py` (the router, which includes `exchange.router`
    only and carries the `authentication` tag (DT-18)), `routes/auth/endpoints/__init__.py` and
    `routes/auth/schema/__init__.py` (owner decision 11, B-13, B-36).
  - `src/huron/applications/api/routes/discovery.py`: DT-5's router and its response models
    `DiscoveryDocument` and `JsonWebKeySet`, with no credential dependency.
  - `src/huron/applications/api/routes/auth/endpoints/exchange.py`: DT-6's route, with no credential
    dependency.
  - `src/huron/applications/api/routes/auth/schema/exchange.py`: `ExchangeRequest` and
    `ExchangeResponse`, as DT-6 writes them.
  - `tests/unit/test_discovery.py`: DT-5's five cases.
  - `tests/unit/test_api_exchange.py`: DT-6's cases, run through `fake_issuer_transport` and
    `fake_groups_transport`:
    - 200 with the body and `Cache-Control: no-store`;
    - an `Authorization` header and dev headers have no effect;
    - 401 for a bad company token, an unknown user and a bad `subject_claim`;
    - 503 `DEPENDENCY_UNAVAILABLE` (`company_idp`, `group_directory`) with `Retry-After: 30`, and 503
      `SIGNING_KEY_UNAVAILABLE`;
    - 422, every refusal as a problem document;
    - a removed mapping changes the `roles` of the next exchange.
- Modify:
  - `app.py` includes `discovery.router` first, then the re-created auth router and the legacy routers
    (DT-1's order).
  - `tests/unit/test_api_router_composition.py`: the `/auth` family is exactly `POST /auth/exchange`; the
    tag set gains `authentication` and `discovery` (13 tags), and `auth` is absent (owner decision 11,
    B-13).
  - `tests/unit/test_execution_model.py`: the three operations, each async.
  - `design/api.html` §3 becomes "Raw lake (`lake`)", with DT-18's reading notes and rows 1–3.
  - `design/auth.html` §5: the route list (`POST /auth/exchange`, discovery, JWKS).
- Design:
  - DT-5 "`routes/discovery.py`: the public documents" and "DT-5 tests this design requires"
    (`test_discovery.py`);
  - DT-6 "`routes/auth/endpoints/exchange.py`: the route", "DT-6 failure behaviour (`POST
    /auth/exchange`)" and "DT-6 tests this design requires" (`test_api_exchange.py`); the old `/auth`
    routes, schemas, self-access summary and their tests left in M1.6 (owner decision 11, B-13);
  - "DT-18 decisions" (Exchange tag, OpenAPI tags) and "DT-18 route table" rows 1–3;
  - DT-1 "Route prefixes (L-27)";
  - "DT-26 design record pages: the Raw-facing six" (the `api.html` §3 and `auth.html` §5 rows).
- Verification:
  - The plan-wide gate, then `make docs`.
  - `uv run pytest tests/unit/test_discovery.py tests/unit/test_api_exchange.py
    tests/unit/test_api_router_composition.py tests/unit/test_execution_model.py` passes.
  - DT-6's closing check prints nothing: `rg -n "JwksVerifier|PyJWKClient|OidcSettings|OidcUser|OidcClient|upsert_oidc_user|OidcNotConfigured|OIDC_NOT_CONFIGURED|self_access|SelfAccessSummary|/auth/session|/auth/providers|auth_mode|AUTH_MODE|HURON_OIDC__|oidc_verify" src tests scripts dev.env`.
  - Every new and modified `src/` file is at 100 % in the unit run.
- Dependencies: M9.2.
- Decisions: OQ-5.3 (settled, owner decision 12)
- Status: pending

### M9.4 The lake router, `current_actor` and the catalog routes (rows 4–9)

- Intent: add the lake router under `/api/v1`, behind `current_actor` (Huron JWT only), with catalog rows
  4–9. The lake error vocabulary joins the wire. This task also starts the derived anonymous-401 sweep and
  the role-ladder table, which every later lake row extends.
- Delete: none.
- Create:
  - `src/huron/applications/api/authorization/actors.py`: `current_actor` and `CurrentActor` (DT-1's
    contract).
  - `src/huron/applications/api/routes/lake/__init__.py`: `AUTHENTICATED_ERRORS` and the router. There is
    one include for each endpoints module and no route on the router itself.
  - `src/huron/applications/api/routes/lake/dependencies.py`: `catalogs`, `metadata_schemas` and
    `validation`, with their `Annotated` aliases. They are built from `runtime.stores.lake` and the
    lifespan's policies.
  - `src/huron/applications/api/routes/lake/schema/__init__.py`.
  - `src/huron/applications/api/routes/lake/schema/catalogs.py`: `CatalogBody`, `CatalogConfigBody` and
    `CatalogCreate`, each response built `from_view` and each request `extra="forbid"`. `CatalogBody.volume`
    lands with M11's `VolumeSettings`.
  - `src/huron/applications/api/routes/lake/endpoints/__init__.py`.
  - `src/huron/applications/api/routes/lake/endpoints/catalogs.py`: rows 4–9 in DT-18's shape. Row 7 is
    answered from `Validation`. Row 8 claims with `Replay` kind `catalog`. No catalog-log route exists
    (OQ-7.2 (a)), and row 10 belongs to M16.
  - `tests/unit/test_lake_routes.py` (marker `unit`):
    - `test_every_lake_route_refuses_an_anonymous_request`: the route set is derived from `app.routes`,
      has 6 members now, and is called with all five credential variants; a spy store sees no call;
    - `test_role_ladder`: rows 4–9, with the sentinel that the table equals the derived set;
    - `test_etag_on_reads_and_if_match_on_writes`: rows 5 and 9, and row 8 without `Idempotency-Key`;
    - `test_idempotent_replay`: row 8.
  - `tests/unit/test_api_lake_admin.py` (marker `unit`; DT-10's file), one parametrized case for each of
    DT-18 rows 4–6, 8 and 9 (DT-10 administration rows 1–5), covering the success status and each listed
    problem code with its status:
    - row 4: 200; row 5: 200 with `ETag: "<config_version>"`, and 404; row 6: 200, and 404 for an unknown
      catalog and for an unknown version;
    - row 8: 201 with `Location` and `ETag: "1"`; 400 `PATH_RULE_VIOLATION`; 403 `FORBIDDEN`; 409
      `CATALOG_EXISTS` and `IDEMPOTENCY_KEY_REUSED`; 422 `CATALOG_CONFIG_INVALID`;
    - row 9: 200 with `ETag: "N+1"` (`"N"` and no entry when unchanged); 403; 404; 412
      `PRECONDITION_FAILED`; 422 `CATALOG_CONFIG_INVALID`;
    - after each write of rows 8 and 9, the audit entry's pair (`create` / `catalog`, `catalog_config` /
      `catalog`), `object_id`, `catalog_id` and `detail`.
- Modify:
  - `src/huron/applications/api/authorization/__init__.py` exports `current_actor` and `CurrentActor`.
  - `routes/pagination.py` gains `listing_cursor` and `listing_key`. A cursor from another listing raises
    `InvalidCursor`.
  - `routes/preconditions.py` gains `entity_tag` and accepts only the strong If-Match form on both
    routers: `_IF_MATCH` becomes `"(?P<version>\d{1,19})"`, the comment about the bare form and existing
    callers is deleted, and the `expected_version` docstring and its 422 message name one form, `"N"`;
    `W/"N"` and a bare `N` answer 422 like any malformed `If-Match` (owner decision 11, B-11).
    `IdempotencyHeader` is tightened to 1–255 printable ASCII on both routers.
  - `app.py` includes `lake.router` last. The `routes/__init__.py` docstring names the four route
    packages.
  - `design/api.html`:
    - §7 is unchanged: each lake code's row and the "live only on lake routes" prose landed with its first
      raiser in M7.2–M7.6, and M7.2 already joined `LAKE_ERROR_CODES` to `wire_error_codes()`;
      `IDENTITY_UNRESOLVED` lands with its raiser in M11.10.
    - §3 gets rows 4–9.
    - §1 "Authentication surface" gets DT-26's three rules. DT-26 assigns it to the exchange task, but
      its lake-route rule becomes true only here.
  - `design/auth.html` §1 "Credentials by surface", here for the same reason.
  - `docs/getting-started/local-development.md`, "Authenticating in development": lake routes take a
    Huron JWT from `POST /auth/exchange`.
  - `tests/unit/test_api_router_composition.py`:
    - the tag set gains `catalogs` (14 tags);
    - every `/api/v1` route has exactly one of `current_principal` and `current_actor`;
    - the lake first segments are within DT-1's seven and disjoint from the legacy set;
    - a Huron JWT on a legacy route and an API key on a lake route both answer 401;
    - a Huron JWT from `POST /auth/exchange` is accepted on a lake route, and the company token is
      refused there (DT-6's composition case);
    - a source scan finds no module under `routes/lake` that reads `grants` (DT-4);
    - `Problem` is the only error schema.
  - `tests/unit/test_execution_model.py`: six async operations.
  - `tests/unit/test_api_pagination.py`, for the catalogs listing:
    - a cursor issued by another listing answers 400 `INVALID_CURSOR`;
    - 50 items by default, and `limit=201` answers 422;
    - a walk of 3 items with `limit=1` visits each once and ends with `next_cursor: null`.
  - `tests/unit/test_api_preconditions.py`: `entity_tag`, the bounds of `Idempotency-Key`, and a bare `N`
    and a weak `W/"N"` each answering 422 (owner decision 11, B-11).
  - `tests/unit/test_api_{catalog_hierarchy,rbac,visibility}.py`: every legacy request that sends a bare
    or weak `If-Match` sends `"N"` (owner decision 11, B-11).
- Design:
  - "DT-18 decisions" (One paging spelling, Bad cursor, OpenAPI tags);
  - "DT-18 target module layout";
  - "DT-18 route table" rows 4–9 and its notes;
  - "DT-18 request and response models" (`catalogs.py`);
  - "DT-18 paging keys and the `label` filter" (the `/catalogs` row);
  - "DT-18 interfaces and contracts" → "The lake router and its credential dependency", "Lake service
    dependencies", "Preconditions and media types (`routes/preconditions.py`)" and "Composition and
    readiness";
  - "DT-18 error-code table rows (`design/api.html` §7, ready to paste)";
  - "DT-18 tests this design requires" (the tests named above);
  - DT-1 "Route prefixes (L-27)";
  - DT-4 "`applications.api`: the lake credential dependency";
  - DT-9 "`huron.core.lake.schemas`: validation, the cache and the Incomplete computation" (row 7);
  - "DT-10 administration route table" rows 1–5, and "DT-10 tests this design requires"
    (`test_api_lake_admin.py`);
  - "DT-26 design record pages: the Raw-facing six" (`api.html` §1, §3, §7 and `auth.html` §1).
- Verification:
  - The plan-wide gate, then `make docs`.
  - `uv run lint-imports` keeps 18 contracts. Contract 12 holds: `routes.lake` enters `authorization`
    through its public surface.
  - `uv run pytest tests/unit/test_lake_routes.py tests/unit/test_api_lake_admin.py
    tests/unit/test_api_router_composition.py tests/unit/test_api_pagination.py
    tests/unit/test_api_preconditions.py tests/unit/test_error_contract.py
    tests/unit/test_execution_model.py` passes.
  - `rg -n 'grants' src/huron/applications/api/routes/lake` prints nothing; `rg -n 'existing callers|<bare>' src/huron/applications/api/routes/preconditions.py`
    and `rg -nF '(?:W/)' src/huron/applications/api/routes/preconditions.py` print nothing (owner
    decision 11, B-11).
  - Every new and modified `src/` file is at 100 % in the unit run.
- Dependencies: M9.3; M7.
- Decisions: OQ-7.2 (settled, owner decision 12)
- Decisions: OQ-18.1 (settled, owner decision 12)
- Status: pending

### M9.5 Role-mapping routes (rows 11–16)

- Intent: serve the catalog and global role-mapping rows through DT-10's `RoleMappings`. Writes are a
  total `PUT` with no `If-Match`. The ceiling, last-owner and seeded-mapping refusals reach the wire, and
  every write is audited.
- Delete: none.
- Create:
  - `src/huron/applications/api/routes/lake/schema/role_mappings.py`: `RoleCode`, `RoleMappingWrite` and
    `RoleMappingBody`. The shared `Reason` type goes in `routes/lake/schema/__init__.py`; this is its
    first user.
  - `src/huron/applications/api/routes/lake/endpoints/role_mappings.py`: rows 11–16 in DT-18's shape. The
    group parameter is `{group:path}`, and `reason` travels as `?reason=` on a DELETE.
- Modify:
  - `tests/unit/test_api_lake_admin.py` (M9.4's file) extends to rows 11–16:
    - one parametrized case for each mapping row, covering the success status and each listed problem
      code with its status (row 12's 422 `role_scope` case is a global OA mapping `organization_admin` on
      a catalog, because a PA gets DT-10's step-2 ceiling 403 first, as in M7.6);
    - after each write, the audit entry's pair, `object_id`, `catalog_id` and `detail`;
    - `CN=Ops/EU,OU=g` round-trips through rows 12, 13, 15 and 16 (R10-1);
    - the test seed group's global mapping is refused with `seeded_mapping`.
  - `routes/lake/dependencies.py`: `role_mappings` and its alias.
  - `routes/lake/__init__.py`: the include.
  - `tests/unit/test_lake_routes.py`:
    - the sweep now has 12 members;
    - ladder rows 11–16;
    - `test_role_mapping_ceiling`;
    - a mapping removed through row 13 refuses the next request of a token minted before it (Owner
      decision 7, RL step 1's gate).
  - `tests/unit/test_api_router_composition.py`: the tag `role-mappings` (15 tags).
  - `tests/unit/test_execution_model.py`.
  - `tests/unit/test_api_pagination.py`: the role-mapping listing's cursor.
  - A unit case asserts that the literal of `RoleCode` equals `{r.code for r in Role}`.
  - `design/api.html` §3 rows 11–16.
  - `design/rbac.html` (DT-26 rows naming the DT-4 task, true from here: mappings are administered and
    re-read per request): §2 Roles (the rank ladder, `group_role_map`, the seeded global Platform Owner, the
    minimum role per route linked to `api.html` §3) and §4's Raw matrix cells, each linking the route
    table (M0.5's overwrite line stays).
- Design:
  - "DT-18 route table" rows 11–16;
  - "DT-18 request and response models" (`Reason`, `role_mappings.py`, the `RoleCode` note);
  - "DT-18 paging keys and the `label` filter" (the role-mappings row);
  - "DT-18 tests this design requires" (`test_role_mapping_ceiling`);
  - "DT-10 decisions";
  - "DT-10 administration route table" rows 9–14;
  - DT-10 "`core/lake/admin.py`: role mappings";
  - "DT-10 tests this design requires" (`test_api_lake_admin.py`).
- Verification:
  - The plan-wide gate, then `make docs`.
  - `uv run pytest tests/unit/test_lake_routes.py tests/unit/test_api_lake_admin.py
    tests/unit/test_api_router_composition.py tests/unit/test_api_pagination.py` passes.
  - `rg -n 'If-Match|IfMatchHeader' src/huron/applications/api/routes/lake/endpoints/role_mappings.py`
    prints nothing (OQ-10.2 (a)).
  - Every new and modified `src/` file is at 100 % in the unit run.
- Dependencies: M9.4; M7.
- Decisions: OQ-4.2 (settled, owner decision 12)
- Decisions: OQ-10.1 (settled, owner decision 12)
- Decisions: OQ-10.2 (settled, owner decision 12)
- Status: pending

### M9.6 Metadata-schema and signing-key routes (rows 17–22) and the store-outage answer

- Intent: serve the metadata-schema rows through DT-9's `MetadataSchemas`, and the Platform-Owner
  signing-key rows through DT-10's `SigningKeyAdmin`. The withdraw row is included under OQ-5.2 (a). The
  shared fault wrapper lands too, and with it the pinned 503 answer to a store outage on a lake read and
  a lake write. The milestone's 18 lake routes are then complete.
- Delete: none.
- Create:
  - `src/huron/applications/api/routes/lake/schema/metadata_schemas.py`: `SchemaRefBody`,
    `MetadataSchemaPublish` and `MetadataSchemaBody`.
  - `src/huron/applications/api/routes/lake/schema/signing_keys.py`: `KeyRotation`, `SigningKeyBody` and
    `SigningKeyList`.
  - `src/huron/applications/api/routes/lake/endpoints/metadata_schemas.py`: rows 17–19. Row 19 claims
    with `Replay` kind `metadata_schema`.
  - `src/huron/applications/api/routes/lake/endpoints/signing_keys.py`: rows 20–22. Row 21 claims with
    `Replay` kind `signing_key`.
  - `tests/lake_faults.py`: `FaultingLakeStore(inner, crash_on, fault=…)` and `InjectedFault`, as DT-17
    describes the shared double. Its `fault` argument can be `DependencyUnavailable("database")`. M13
    and M16 reuse it with `crash_on`.
- Modify:
  - `routes/lake/dependencies.py`: `signing_keys`, which builds
    `SigningKeyAdmin(runtime.stores.lake, runtime.keys, runtime.key_source, runtime.clock)`, and its
    alias.
  - `routes/lake/__init__.py`: the includes.
  - `tests/unit/test_lake_routes.py`:
    - the sweep now has 18 members;
    - ladder rows 17–22;
    - `test_idempotent_replay` for rows 19 and 21;
    - `test_etag_on_reads_and_if_match_on_writes`: rows 19 and 21 without `Idempotency-Key` answer 422
      `REQUEST_INVALID`;
    - `test_store_outage_is_503` on rows 5 and 8, through `FaultingLakeStore`: 503 with `Retry-After: 30`
      and `context.dependency == "database"`. Row 25 joins in M11.
  - `tests/unit/test_api_lake_admin.py` extends to rows 17–22 (DT-10 administration rows 6–8 and 15–17),
    one parametrized case for each row's success status and each listed problem code with its status:
    - row 17: 200; row 18: 200 with `ETag: "<sha256>"`, and 404;
    - row 19: 201 with `Location` and one `schema_publish` / `metadata_schema` entry (its `object_id`,
      `catalog_id` and `detail` checked); 200 and no entry for an identical republish; 403 `FORBIDDEN`;
      409 `SCHEMA_VERSION_EXISTS` and `IDEMPOTENCY_KEY_REUSED`; 422 `SCHEMA_INVALID`;
    - rotating gives 201 with `retired_kid` and one `key_rotate` entry;
    - a second rotation answers 409 `pending_key_exists`;
    - withdrawing restores the predecessor's `retired_at` and writes one `key_withdraw` entry;
    - withdrawing inside `MAX_RING_AGE` answers 409 `not_pending`;
    - row 20 answers 200 `SigningKeyList`, row 21 also answers 409 `IDEMPOTENCY_KEY_REUSED`, and row 22
      answers 204, and 404 for an unknown `kid`;
    - every key route answers 403 to an Organization Admin.
  - `tests/unit/test_api_router_composition.py`: the tags `metadata-schemas` and `signing-keys` (17
    tags).
  - `tests/unit/test_execution_model.py`.
  - `tests/unit/test_api_pagination.py`: the metadata-schema listing's cursor.
  - `design/api.html`: §3 rows 17–22, and §6's sentence that the lake's admin routes are in §3 (DT-26:
    the DT-10 task).
  - `design/auth.html` §5 gets the "Signing keys" subsection: rotation through
    `POST /api/v1/signing-keys`, and the Secret mounted with `defaultMode: 0400`. The `huron key rotate`
    mention lands with M10.
- Design:
  - "DT-18 route table" rows 17–22;
  - "DT-18 request and response models" (`metadata_schemas.py`, `signing_keys.py`);
  - "DT-18 paging keys and the `label` filter" (the `/metadata-schemas` row);
  - "DT-18 interfaces and contracts" → "Store outage boundary (OQ-18.1 (a))" and "Composition and
    readiness" (`Replay.kind` per route);
  - "DT-18 tests this design requires" (`test_store_outage_is_503`, `test_idempotent_replay`,
    `test_etag_on_reads_and_if_match_on_writes`);
  - "DT-17 port → adapter → fake" (the paragraph on shared test doubles);
  - "DT-10 administration route table" rows 6–8 and 15–17;
  - DT-10 "`core/lake/admin.py`: signing-key administration (the write half of DT-5's key store)";
  - "DT-10 tests this design requires" (`test_api_lake_admin.py`, and `test_lake_signing_key_admin.py`
    rows through the routes);
  - the DT-9 routes table under "DT-9 interfaces and contracts";
  - "DT-26 design record pages: the Raw-facing six" (`api.html` §3 and §6, `auth.html` §5).
- Verification:
  - The plan-wide gate, then `make docs`.
  - `uv run pytest tests/unit/test_lake_routes.py tests/unit/test_api_lake_admin.py
    tests/unit/test_api_router_composition.py tests/unit/test_api_pagination.py
    tests/unit/test_error_contract.py tests/unit/test_execution_model.py` passes.
  - The derived lake route set has exactly 18 members, and the OpenAPI tag set has 17 entries.
  - `rg -n '/log' src/huron/applications/api/routes/lake` prints nothing: there is no read route for
    administration entries (OQ-7.2 (a)).
  - Every new and modified `src/` file is at 100 % in the unit run.
- Dependencies: M9.5; M3, M7.
- Decisions: OQ-5.2 (settled, owner decision 12)
- Decisions: OQ-7.2 (settled, owner decision 12)
- Decisions: OQ-18.1 (settled, owner decision 12)
- Status: pending

## Milestone 10 — CLI foundation, login, browsing and administration verbs

Spec build steps 1 and 2 on the client. `huron.applications.cli` arrives as a Typer application with
`[project.scripts] huron`, import-linter contracts 17 and 18 and the Ruff `TC` entry, together with every
layer later verbs reuse: the exit-code table and its error boundary, the injected `Services`, the XDG
state directory and its write rules, the company OIDC client (device grant with PKCE, loopback redirect),
the Huron client with the CLI's one retry and paging rule, and the login session that refreshes and then
re-exchanges under one lock. The context and session verbs, `get catalogs`, `explain catalog`,
`meta template`, `meta validate --catalog` and all of DT-20's administration verbs (behind the `Prompter`
seam) are built on those layers. Every test runs the production code against DT-22's fake issuer and groups fake (M5)
and the real `create_app` over `memory_stores()` (M9), with no bypass. The CLI imports `huron.schema` and
no other Huron package. The milestone starts `docs/raw-lake/cli.md` (§1, §2, §10 and the step-2 lines of
§3 and §4), adds the README bullet, `python-client.html`, roadmap P0 and P8, and flips RL steps 1 and 2.
Every new test module under `tests/unit/cli/` sets `pytestmark = pytest.mark.unit`, as the existing unit
modules do.

### M10.1 CLI package, entry point, error boundary and the state directory

- Intent: give the CLI its home and the seams every verb uses (DT-1 L-30, L-31; DT-19 "Seam"). This means the
  console script and declared dependencies; contracts 17 and 18 and the Ruff `TC` entry, in the commit that
  adds the first CLI module; `ExitCode` and the error boundary; and `Services` as the one composition seam,
  with `main()` the only reader of the environment, the real clock and `argv`. It also adds the state
  directory with its write rules 1–4 and 6, the output renderers, and the three `config` verbs that need
  no network.
- Delete: none.
- Create:
  - `src/huron/applications/cli/__init__.py`: `main()` as "`services.py` and `main()`" specifies. It refuses
    `sys.platform == "win32"` with one stderr line and exit 1 (OQ-19.2 (a)). It builds the two
    `httpx.Client`s (`Timeout(30.0, connect=10.0)`, `follow_redirects=False`,
    `User-Agent: huron-cli/<importlib.metadata.version("huron")>`) inside an `ExitStack`. It builds
    `Services` from `StateDir.locate(os.environ, sleep=time.sleep, monotonic=time.monotonic)`,
    `os.environ`, `datetime.now(UTC)`, `time.sleep` and `webbrowser.open`, then runs `app.app` with
    `obj=services`.
  - `src/huron/applications/cli/app.py`: the root `typer.Typer(no_args_is_help=True)`, `commands.register(app)`
    and the boundary. A `CliError` prints `error: <message> [<code>]` and `hint: …` on stderr and exits
    with its `exit_code`; under `-o json|yaml` it also writes the `ApiProblem` document to stderr.
    `KeyboardInterrupt` exits 130. Any other exception prints one line naming `HURON_DEBUG=1` and exits 1,
    or re-raises when `Services.environ` has `HURON_DEBUG=1`.
  - `src/huron/applications/cli/services.py`: `Services` (`state`, `environ`, `idp_http`, `api_http`,
    `clock`, `sleep`, `open_browser`, `cwd`). `prompter` (M10.7) and `hostname` (M14.2) arrive with
    their first users.
  - `src/huron/applications/cli/errors.py`: `ExitCode` (0–7, 130), `ApiProblem` with `from_response`,
    `CliError`, `UsageError`, `StateError`, `NotLoggedIn`, `LoginFailed` (its `reason` literal),
    `Unavailable`, `ApiError` and `exit_code_for`. `INVALID_CURSOR` and 415 `UNSUPPORTED_MEDIA_TYPE` map to
    `FAILED` (DT-18 handoff to DT-19).
  - `src/huron/applications/cli/state.py`:
    - `StateDir` (`locate`, `locked`, `write_bytes`, `read_bytes`, `collection`), constructed as
      `StateDir(root, *, sleep: Callable[[float], None], monotonic: Callable[[], float])` and
      `StateDir.locate(environ, *, sleep, monotonic)`. `locked` polls `LOCK_NB` every 100 ms through the
      injected `sleep` and raises `StateError` once the injected `monotonic` reading is 60 s past the first
      attempt (rule 3). DT-19's `StateDir(root)` and `locate(environ)` give the wait no seam, and the `rg`
      check below allows `time.sleep` only in `__init__.py`; the two keywords are the plan's.
    - `CurrentCatalog` (the name; M12.1 adds its `VolumeCoordinates`, because `CatalogBody.volume` is
      served from M11.11), `CurrentCollection` and `Effective`.
    - `Config` with `load`, `save`, `effective` (the `HURON_API_URL`, `HURON_IDP_ISSUER` and
      `HURON_IDP_CLIENT_ID` overrides, each value recording its source, OQ-19.1 (a)) and `local_prefix`,
      the package's only `os.path.realpath` of the prefix (from `mount_prefix` only here; M12.1 adds the
      `catalog.volume.prefix` fallback with `CurrentCatalog.volume`).
    - `CollectionDir` (`ensure`, `read_json`, `write_json`).
    - Rules 1–4 and 6; rule 1 includes the `tokens.json` owner and mode check.
    - Private module-level `_stat` and `_getaddrinfo` aliases: the owner seam and resolver seam that tests
      replace.
    - `StoredTokens`, `HuronToken` and rule 5 are M10.4's.
  - `src/huron/applications/cli/output.py`: `OutputFormat`, `OutputOption`, `Column`, `render_list`,
    `render_document`, and the stdout/stderr `rich.Console` pair built from `Services` (`NO_COLOR` and a
    non-TTY turn styling off).
  - `src/huron/applications/cli/commands/__init__.py`: `register(app)`, which adds the `config` group;
    later tasks add their groups here.
  - `src/huron/applications/cli/commands/context.py`:
    - `config view`: default `-o yaml`; prints the effective settings with their sources, the current
      catalog, the local prefix and the current collection. The login-state line arrives with
      `StoredTokens` (M10.4) and the volume line with `VolumeCoordinates` (M12.1).
    - `config set` and `config unset`: `ConfigKey` ∈ `api-url`, `idp-issuer`, `idp-client-id`,
      `mount_prefix`; `UnsetKey` adds `catalog`. A changed connection key prints the stderr note that it
      needs `huron login` (state rule 5).
  - `tests/unit/cli/__init__.py` (empty) and `tests/unit/cli/conftest.py`: `CliHarness` and the `cli`
    fixture from DT-19's outline.
    - State: `StateDir(tmp_path / "state", sleep=harness.sleep, monotonic=harness.monotonic)`; the root
      `clock` fixture (M5). `harness.sleep` records every sleep and advances the clock by it, and
      `harness.monotonic` reads the clock (`clock.now().timestamp()`); `Services.sleep` is the same
      recorded sleep.
    - Remote parties: `idp_http = TestClient(fake_issuer.app, follow_redirects=False)` and
      `api_http = TestClient(create_app(…))`. The app is composed the way M9's lake route tests compose it
      (`lake_settings()`, `memory_stores()`, the `tests/lake_tokens.py` key source, `fake_issuer_transport`,
      `fake_groups_transport`) and entered, so its lifespan runs.
    - `invoke(*argv)` runs `typer.testing.CliRunner` with `obj=services`.
  - `tests/unit/cli/test_cli_state.py`: DT-19's row except `bound_to` (M10.4).
  - `tests/unit/cli/test_cli_errors.py`: `exit_code_for` over every status and listed code; `ApiProblem` from
    a problem body, from a `Retry-After` delta and date, and from a non-JSON proxy 502.
  - `tests/unit/cli/test_cli_output.py`: golden `table` and `wide` text; `json` and `yaml` print the body
    verbatim; an empty list prints its note on stderr and exits 0.
  - `tests/unit/cli/test_cli_context.py`: `config set`/`unset`/`view` round trips; a bad key or value exits
    2; the environment overrides and their recorded sources.
  - `tests/unit/cli/test_cli_entry.py`: DT-19's row (`--help` exits 0; the `[project.scripts]` target, read
    with `tomllib`, imports; no arguments exits 2 and prints help; an unexpected exception prints one line
    and exits 1 and re-raises under `HURON_DEBUG=1`) plus `test_main_refuses_on_windows`.
  - `docs/raw-lake/cli.md`: "Using the `huron` CLI" with §1 Set up as DT-26 outlines it (`config set` for
    the server and `mount_prefix`, `config view`, mount advice NFSv4.1 with `nconnect=8`).
- Modify:
  - `pyproject.toml`:
    - `uv add "typer>=0.27" "rich>=15" "questionary>=2"` into `[project].dependencies`.
    - `[project.scripts] huron = "huron.applications.cli:main"`.
    - `"src/huron/applications/cli/**" = ["TC001", "TC002", "TC003"]` beside the API's per-file entry.
    - Import-linter contract 17, "applications never import a sibling application" (`independence`,
      modules `huron.applications.api` and `huron.applications.cli`).
    - Import-linter contract 18, "the CLI imports schema only and no server stack" (`forbidden`, indirect;
      source `huron.applications.cli`; forbidden `huron.core`, `fastapi`, `starlette`, `uvicorn`, `asyncpg`,
      `sqlalchemy`, `alembic`, `aiobotocore`, `boto3`, `botocore`). Both are worded exactly as DT-1's table
      words them.
    - `uv.lock` is updated to match.
  - `tests/unit/test_domain_import_contracts.py`:
    - `_sandbox` creates `huron.applications.cli`.
    - `test_declared_edges_and_owner_root_reexports_are_allowed` gains the edge `cli → huron.schema`.
    - `test_forbidden_edges_and_unclassified_owners_fail` gains three cases: `cli` importing
      `huron.core.foundation` (contract 18), `cli` importing `huron.applications.api` (contract 17), and
      `cli` reaching `starlette` through a `huron.schema` module (contract 18, indirect).
  - `design/roadmap.html` P0 row: the D-3 clause gains "(contract 17, reinstated with `applications/cli`)".
  - `src/huron/applications/__init__.py`: the docstring names `cli` beside `api`;
    `docs/getting-started/repository-layout.md`: the tree gains the `applications/cli/` line (the landing
    rule: both name the package this task creates).
  - `README.md`: the bullet "**The `huron` CLI:** `uv run huron --help`; the guide is `docs/raw-lake/cli.md`."
    after the design-record bullet.
- Design: DT-1 decisions (L-30, L-31, "Ruff `TC` for the CLI"); DT-1 import-linter contract set (rows 17,
  18); DT-1 interfaces and contracts → "`huron.applications.cli`: package, entry point and imports (L-30,
  L-31)"; DT-19 decisions; DT-19 target module layout; DT-19 local state: layout, schemas and the write
  rules; DT-19 interfaces and contracts → "`errors.py`: exit codes and the CLI's error types",
  "`services.py` and `main()`: the composition seam", "`state.py`", "`output.py`"; DT-19 command signatures
  and exit codes (the `config` rows); DT-18 handoffs (DT-19 row); DT-26 the two new pages (CLI guide §1);
  DT-26 roadmap rows (P0); DT-26 developer docs, README and history (README bullet).
  - Key spelling: DT-21 (`huron config set mount_policy`) and DT-23/DT-26 (`huron config set mount_prefix`)
    spell the mount keys with `_`. They are later sections, so they win over DT-19's `mount-prefix`. The
    three connection keys keep DT-19's spelling.
- Verification:
  - The plan-wide gate. `uv run lint-imports` reports 20 contracts kept (18 before this task: contract 19
    is two tables, M4.1).
  - `uv lock --check` exits 0, `uv run huron --help` exits 0, and `uv run huron` exits 2 and prints the
    help.
  - `rg -n "^\s*(from|import) huron\.(core|applications\.api)\b" src/huron/applications/cli` prints nothing.
  - `rg -n "os\.environ|sys\.argv|datetime\.now\(|time\.(sleep|monotonic)|httpx\.Client\(" src/huron/applications/cli`
    prints only `__init__.py` lines.
  - `uv run pytest tests/unit/cli tests/unit/test_domain_import_contracts.py -q` passes. It includes
    `test_locate_precedence`, `test_state_files_are_0600_under_umask_022`,
    `test_tokens_file_with_group_bits_is_refused`, `test_foreign_owner_is_refused`,
    `test_interrupted_write_keeps_the_old_document`, `test_lock_contention_times_out_with_state_error`
    (a second `flock` holds `.lock`; the 60 s bound is reached through the recorded sleeps, about 600 of
    0.1 s, with no wall-clock wait), `test_unknown_member_wrong_version_or_bad_url_is_refused`,
    `test_transport_rule_allows_http_only_to_loopback`, `test_exit_code_for_every_status_and_code`,
    `test_main_refuses_on_windows`, `test_unexpected_exception_reraises_under_debug` and the three new
    contract cases.
  - `make docs` and `git diff --check` pass. Every created or modified file is at 100 % line coverage.
- Dependencies: M5, M6, M9.
- Decisions: OQ-19.1 (settled, owner decision 12)
- Decisions: OQ-19.2 (settled, owner decision 12)
- Status: pending

### M10.2 Company OIDC client: discovery, device and loopback flows

- Intent: the client half of the company login (DT-19 "L-30", "ID token on the client", "Flow choice").
  Discovery checks the issuer exactly. The RFC 8628 device grant sends PKCE S256 on the device request and
  `code_verifier` on every poll (OQ-22.1 (a)). The RFC 8252 loopback flow runs on `127.0.0.1`. Refresh
  rotates tokens and revocation is best effort. Everything goes through `Services.idp_http`.
- Delete: none. The server copies of `code_challenge_s256` and the discovery check left with D2-4 (M1) and
  DT-6 (M5).
- Create:
  - `src/huron/applications/cli/oidc.py`:
    - `SCOPE`, `ID_TOKEN_LEEWAY` and `id_token_claims`.
    - `code_challenge_s256`, verbatim from `git show fa51f46:src/huron/core/security/oidc.py` (lines
      459–470).
    - `Discovery.parse`: DT-19's rule. `issuer`, `token_endpoint` and `jwks_uri` are required, with an
      exact issuer match (the check of `fa51f46` `oidc.py:201-219` without `authorization_endpoint`);
      any failure is `LoginFailed(reason="discovery")`. `authorization_endpoint`,
      `device_authorization_endpoint` and `revocation_endpoint` are optional; a flow whose endpoint is
      absent raises `LoginFailed(reason="flow_unsupported")` before any prompt. Every endpoint passes
      `state.py`'s transport rule.
    - `DevicePrompt`; `CompanyTokens` with `identity_hints()` (`name`, `email`, `preferred_username`;
      M12.1 adds `organization`).
    - `CompanyOidcProvider` (`discovery`, `device_login`, `browser_login`, `refresh`, `revoke`) and
      `LoopbackReceiver`.
  - `tests/unit/cli/test_cli_oidc.py`: DT-19's row.
    - `test_code_challenge_s256_matches_the_rfc7636_worked_example`, restored from
      `git show fa51f46:tests/unit/test_auth_oidc.py` (lines 492–496); the test left with D2-4.
    - `test_device_request_and_every_poll_carry_pkce`, against `fake_issuer`.
    - The `Discovery.parse` table: each missing required member and an issuer mismatch raise
      `LoginFailed(reason="discovery")`; a document without `authorization_endpoint`, or without
      `device_authorization_endpoint`, parses, and the flow that needs it raises
      `LoginFailed(reason="flow_unsupported")` before any prompt.
    - The device matrix: pending ×N; `slow_down` adds 5 s to the recorded sleeps; `access_denied`;
      `expired_token`; the local deadline; three transport failures then success; four failures then
      `Unavailable(dependency="company_idp")`.
    - The loopback matrix, through the fake browser: no browser; a tampered `state` answered 400, failing
      closed; an IdP `error` redirect; `/favicon.ico` first; no callback until the clock passes the
      deadline.
    - ID-token checks: `iss`; `aud` as a string and as a list; `exp` with leeway; `nonce`.
    - Refresh with and without rotation; `invalid_grant` raises `NotLoggedIn`; revoke when advertised, when
      not advertised and when it fails.
    - `respx` on a plain `httpx.Client`, DT-22's one permitted exception, only for malformed or
      foreign-issuer discovery, discovery without a flow endpoint, a 5xx, `httpx.ConnectTimeout` and a
      token response without `id_token`.
- Modify:
  - `tests/unit/cli/conftest.py`: the fake browser (`CliHarness.browser`). It GETs the authorization URL
    through the IdP `TestClient`, reads the `302 Location`, then GETs that URL with a real `httpx.Client()`
    against the `LoopbackReceiver`. It supports the variants above.
  - `tests/unit/test_fake_identities.py`: DT-22's "fakes against production parsers" clause that
    `Discovery.parse` accepts the fake issuer's discovery document.
- Design: DT-19 decisions ("L-30", "ID token on the client", "Flow choice"); DT-19 interfaces and contracts →
  "`oidc.py`: the company OIDC provider (client side)"; DT-19 data flow: the login sequence (device and
  loopback) and refresh then re-exchange; DT-19 tests this design requires (`test_cli_oidc.py`, the fake
  browser, `respx`); DT-19 deletions (the RFC 7636 vector); DT-22 open questions (OQ-22.1); DT-22 handoffs
  (DT-19 row: 127.0.0.1, the fixtures, `slow_down` by the clock); DT-22 interfaces and contracts → "The
  no-bypass rule".
- Verification:
  - The plan-wide gate. `uv run pytest tests/unit/cli/test_cli_oidc.py -q` passes, including the named
    tests.
  - `rg -n "def code_challenge_s256|_REQUIRED_DISCOVERY_FIELDS|_validate_discovery_document" src` prints only
    the `code_challenge_s256` definition in `src/huron/applications/cli/oidc.py`.
  - `rg -n "monkeypatch\.setattr\((jwt|httpx|.*PyJWKClient|.*(Verifier|GroupDirectory|OidcProvider))" tests`
    prints nothing (DT-22's closing check).
  - `rg -n "localhost" src/huron/applications/cli/oidc.py` prints nothing: the receiver binds and advertises
    `127.0.0.1` (R22-3).
  - `oidc.py` is at 100 % line coverage.
- Dependencies: M10.1.
- Decisions: OQ-22.1 (settled, owner decision 12)
- Status: pending

### M10.3 Huron API client: problems, ETags, retries and paging

- Intent: the only module that builds a Huron request (DT-1). It takes the bearer from an injected
  `Credentials`, turns a problem+json body into an `ApiError` by `code`, and reads versions from strong
  ETags. It holds the CLI's one retry rule (503 and transport errors; a write only with `Idempotency-Key`;
  OQ-18.1 (a)), one forced re-exchange on a 401, and the one paging loop over `after`/`next_cursor` (DT-18
  handoff).
- Delete: none.
- Create:
  - `src/huron/applications/cli/client.py`: `Credentials`, `Reply`, `ExchangeResult` and `HuronClient`
    (`exchange`, `get`, `send`, `pages`). M14.1 adds `page_bodies`, which yields whole page bodies, and
    re-expresses `pages` over it, so the loop stays one.
  - `tests/unit/cli/test_cli_client.py`: DT-19's row, less `exit_code_for` and problem parsing (both in
    M10.1's `test_cli_errors.py`).
    - The retry table, through `respx` on a plain `httpx.Client`: 503 with and without `Retry-After`; the
      60 s budget exhausted; a transport error on `GET`; a transport error on a keyless `POST`, which
      raises at once; a keyed `POST` retried with the same `Idempotency-Key`. Waits are read from the
      recorded sleeps.
    - Against the real app, with a `Credentials` test double that hands out tokens minted with
      `tests/lake_tokens.py` (the first one expired): `exchange` sends no `Authorization` header and
      returns the projection; a 401 triggers one `bearer(force_exchange=True)` and one replay; a second
      401 raises `NotLoggedIn`.
    - ETags: `"7"` gives `version == 7`; `W/"7"` and a digest give `None` (rows 5 and 7).
    - `pages` over row 4; through `respx`, following `next_cursor` to `null` and raising on a repeated
      cursor.
    - A non-JSON 2xx raises `CliError`. `if_match=N` sends `If-Match: "N"`.
- Modify: none.
- Design: DT-19 decisions ("Seam", "Retries", "ETags"); DT-19 interfaces and contracts → "`client.py`: the
  Huron API client"; DT-18 decisions ("One paging spelling"); DT-18 route table (rows 3–7); DT-18 handoffs
  (DT-19 and DT-21 rows); DT-1 decisions (L-29).
- Verification:
  - The plan-wide gate. `uv run pytest tests/unit/cli/test_cli_client.py -q` passes.
  - `rg -n "api_http" src/huron/applications/cli` names only `__init__.py` and `services.py`. From M10.4 it
    also names `login.py`, which hands the client to `HuronClient`.
  - `client.py` is at 100 % line coverage.
- Dependencies: M10.1.
- Decisions: OQ-18.1 (settled, owner decision 12)
- Status: pending

### M10.4 Login session, `login`/`logout`/`whoami` and `catalog use`

- Intent: spec build step 1 on the client (G-26). `Session` exchanges the company ID token at
  `POST /auth/exchange` and writes both token sets atomically under the state lock. Every request goes
  through `bearer()`'s decision table, so a refresh token is presented at most once across concurrent
  processes. The session verbs and `catalog use` land with it. This task finishes RL step 1.
- Delete: none.
- Create:
  - `src/huron/applications/cli/login.py`: `HURON_REFRESH_MARGIN`, `COMPANY_REFRESH_MARGIN`, `Identity` with
    `roles_by_catalog` (display only), `open_session`, `Session` (`client`, `login`, `bearer`, `identity`,
    `logout`) and `LogoutOutcome`.
  - `src/huron/applications/cli/commands/session.py`: `login` (`--device`, `--browser`, `--api-url`,
    `--issuer`, `--client-id`, `-o`; the flow is picked by DT-19's "Flow choice" table), `logout`, and
    `whoami` (`--refresh`, `-o`).
  - `tests/unit/cli/test_cli_login.py`: DT-19's row.
    - `huron login --device` (approved through `fake_issuer.approve`) and `huron login --browser` exit 0 and
      write a `tokens.json` whose `huron` part equals the exchange response.
    - `--api-url/--issuer/--client-id` are persisted only on success; `--device --browser` exits 2.
    - The `bearer` decision table, row by row, counting requests per endpoint; the cached-JWT row makes
      none.
    - `test_two_sessions_past_expiry_make_exactly_one_refresh_request` (two threads). The
      `StateDir` over their one state root takes `time.sleep` and `time.monotonic` (M10.1's keywords),
      because the recorded sleep would run
      the waiting thread through its 60 s budget, and move the shared clock, before the holder finishes.
    - An exchange 401 for a user the groups fake does not know deletes `tokens.json` and exits 3. An
      exchange 503 (the groups fake injecting 500) keeps it and exits 7.
    - `whoami`: offline; marked expired once past `expires_at`; with `--refresh` after a role-mapping change
      through row 15, it shows the new roles.
    - `logout` revokes at the fake (checked against its recorded tokens) and deletes only `tokens.json`,
      also when offline.
- Modify:
  - `src/huron/applications/cli/state.py`: `StoredTokens` (`load`, `save`, `delete`, `bound_to`),
    `HuronToken` and rule 5. `tests/unit/cli/test_cli_state.py` gains the `bound_to` truth table.
  - `src/huron/applications/cli/commands/context.py`:
    - `catalog use <catalog>` (row 5) stores `CatalogBody.name` and leaves `collection` unchanged (M12.1
      also stores `CatalogBody.volume`, served from M11.11).
    - `config view` gains the login state (subject and `expires_at`, never a token).
    - `tests/unit/cli/test_cli_context.py` covers both: an unreadable catalog exits 4, and a non-segment
      exits 2.
  - `src/huron/applications/cli/commands/__init__.py`: registers the session verbs and the `catalog` group.
  - `docs/raw-lake/cli.md` §2 Log in, from DT-26's outline (Owner decision 7: access is re-checked on every
    request).
  - `design/python-client.html`: the lede, §1, §2 and §4, from DT-26's row (L-31).
  - `design/roadmap.html`: the P8 row text from DT-26's row; the RL step 1 tag becomes `done`.
  - `docs/getting-started/local-development.md`, "Raw lake development": the
    `uv run --env-file dev.env huron login --device` (or `--browser`) line, which is also the manual
    Keycloak smoke. The section's key and user lines are M9's. "Authenticating in development" gains
    DT-26's clause that lake routes take the Huron JWT "that `huron login` stores" (M9.4 wrote the rest).
  - `dev.env`: DT-22's CLI rows `HURON_API_URL=http://localhost:8080`,
    `HURON_IDP_ISSUER=http://keycloak:8081/realms/company` and `HURON_IDP_CLIENT_ID=huron-cli`, with the
    header sentence that the `huron` command reads them (M9.1 left them to the task whose command reads
    them); `uv run --env-file dev.env python -c "from huron.applications.api.settings import
    settings_from_environment as s; s()"` still exits 0.
- Design: DT-19 decisions ("G-26", "Context", "IdP coordinates"); DT-19 local state (the `tokens.json` schema
  and rule 5); DT-19 interfaces and contracts → "`login.py`: the session (login, refresh then re-exchange,
  logout)", "`state.py`" (`StoredTokens`, `HuronToken`); DT-19 command signatures and exit codes (`login`,
  `logout`, `whoami`, `catalog use`, `config view`); DT-19 data flow: the login sequence; DT-26 roadmap
  rows (P8, RL step 1); DT-26 design record pages (`python-client.html`); DT-26 the two new pages (§2);
  DT-26 developer docs, README and history (`local-development.md` new §).
- Verification:
  - The plan-wide gate. `uv run pytest tests/unit/cli -q` passes, including the named race test; a failure
    of it stops the milestone (plan rule "Races").
  - The no-monkeypatch `rg` from M10.2 prints nothing.
  - `make docs` and `git diff --check` pass. Every created or modified file is at 100 % line coverage.
  - RL step 1's manual smoke (`uv run --env-file dev.env huron login --device` against the compose
    Keycloak `company` realm) needs the owner's stack, which no task starts. The task reports it as
    "not run" and records it under "Execution notes" as an owner receipt, which M19 checks.
- Dependencies: M10.2, M10.3.
- Decisions: OQ-19.1 (settled, owner decision 12)
- Status: pending

### M10.5 Identifier resolution, the schema cache, `get catalogs`, `explain` and `meta template`/`validate`

- Intent: DT-8's CLI obligations (`.`, `./x` and `../x` made absolute; the prefix realpath'd once; only
  canonical identifiers sent), the composed-schema cache revalidated with `If-None-Match`, and the step-2
  read verbs: `get catalogs`, `explain catalog [<c>[.<field>]]`, `meta template`, and
  `meta validate --catalog`, whose verdict equals the server's.
- Delete: none.
- Create:
  - `src/huron/applications/cli/resolve.py`: `resolve_identifier`. `resolve_collection` needs the
    collection routes and lands in M12.2.
  - `src/huron/applications/cli/schemas.py`: the schema cache. The design names the cache and its key
    (`cache/schemas/<digest>.json`) but gives no module and no lookup rule; this module and its per-path
    lookup are the plan's placement.
    - `SchemaCache` over `cache/schemas/<digest>.json`; each entry records the route path, the `ETag` and
      the document.
    - `fetch_composed_schema(client, cache, path) -> ComposedSchema` sends the path's cached `ETag` as
      `If-None-Match`. It reuses the entry on 304, replaces it on 200, and parses with
      `ComposedSchema.from_document`; a refused document raises `CliError` (exit 1).
  - `src/huron/applications/cli/commands/browse.py`:
    - `get catalogs` (row 4, paged): columns `CURRENT`, `NAME`, `TITLE`, `CONFIG`; wide adds `CREATED`
      (M12.2 adds `VOLUME` and `PREFIX` once `CatalogBody.volume` is served).
    - `explain catalog` (rows 5, 6 and 7): prints the field table. A `.field` target splits at the first
      `.`, and the catalog part passes through `check_segment`. An unknown field exits 2 and lists the
      known ones. Vocabulary values come from `CatalogConfig.vocabularies`.
  - `src/huron/applications/cli/commands/meta.py`:
    - `meta template` (rows 5 and 7, default `-o json`): one member per `fields()` entry, identity fields
      first, `null` values.
    - `meta validate <file> --catalog <c>` (rows 5, 6 and 7): schema problems plus `place` problems,
      printed as `where  rule  message` sorted by `where`; exit 0 or 1. The `-c`/current-collection form
      (row 30) is M12.3's.
  - `tests/unit/cli/test_cli_resolve.py`: the four-forms table; `.` and `../x` from a `tmp_path` working
    directory under a prefix reached through a symlink (realpath'd once); every `NamingError` rule exits 2
    with its message.
  - `tests/unit/cli/test_cli_browse.py`: two catalogs, a Reader and a Developer.
    - `get catalogs` × `table`/`wide`/`json`/`yaml`: golden text for tables, and `json.loads` equality
      with the API body.
    - `explain` with and without a field, and with a dependent vocabulary.
    - `test_schema_cache_revalidates_with_if_none_match`: the second call is answered 304.
    - A corrupted cache entry answered 304 exits 1: the "`huron.schema` refuses what was served" row.
  - `tests/unit/cli/test_cli_meta.py`:
    - `meta template` equals DT-9's skeleton.
    - `meta validate --catalog` exits 0 and exits 1.
    - `test_meta_validate_agrees_with_the_server_validator`: on the shared fixture documents (valid,
      missing required, wrong type, a vocabulary violation), the CLI's problems equal those of M7's lake
      validation over the same `memory_stores()`.
- Modify:
  - `src/huron/applications/cli/commands/__init__.py`: registers `get`, `explain` and `meta`.
  - `docs/raw-lake/cli.md`: the §3 lines for `get catalogs` and `explain`, and the §4 lines for
    `meta template` and `meta validate`.
- Design: DT-8 interfaces and contracts → "`huron.schema.naming`" (`Identifier.parse` form detection, CLI
  obligations); DT-19 interfaces and contracts → "`resolve.py`: the four identifier forms (consuming
  DT-8)"; DT-19 command signatures and exit codes (`get catalogs`, `explain catalog`) and its verb rules;
  DT-19 local state (`cache/schemas/`); DT-20 command signatures, routes and exit codes (`meta template`,
  `meta validate`); DT-9 `huron.schema.metadata` (`ComposedSchema`, `fields()`, `MetadataValidator`);
  DT-9's CLI list (rows 7 and 30); DT-26 the two new pages (§3, §4).
- Verification:
  - The plan-wide gate. `uv run pytest tests/unit/cli -q` passes, including the named tests.
  - `rg -n "realpath" src/huron/applications/cli` prints only `state.py`.
  - `make docs` passes. Every created or modified file is at 100 % line coverage.
- Dependencies: M10.4.
- Status: pending

### M10.6 Catalog and schema administration verbs

- Intent: Owner decision 8 for catalogs, catalog configs and metadata schema versions. `catalog show`,
  `catalog apply`, `schema list`, `schema show` and `schema publish` live in `commands/admin.py`, each a
  thin wrapper over its DT-18 row. Rows 8 and 19 get a fresh `Idempotency-Key` (`uuid4().hex`) per
  invocation, which the client reuses across its own retries.
- Delete: none.
- Create:
  - `src/huron/applications/cli/commands/admin.py`:
    - `catalog show` (rows 5 and 6, default `-o yaml`): the config document with its `catalog` and
      `config_version` members, the form `apply` accepts.
    - `catalog apply -f`: reads row 5 first. With no `config_version` in the file and a 404 from row 5,
      it creates (row 8). With `config_version: N`, it publishes (row 9), sending `If-Match: "N"` and
      removing the field from the body. Any other combination exits 2 before a write. A 412 prints the
      current version and `field_changes(current config, file)`; a 422 lists its problems.
    - `schema list` (row 17, paged); `schema show NAME@VERSION` (row 18; JSON prints `json_schema`, YAML
      prints the whole body).
    - `schema publish NAME@VERSION -f [--extends NAME@VERSION]` (row 19): a 200 prints "identical; nothing
      to do", and a 409 prints `latest_version`.
    - `show` and `apply` register on the `catalog` group that M10.4 created.
  - `tests/unit/cli/test_cli_admin.py`:
    - Each verb against its row with the role ladder: exit 5 below Organization Admin, exit 3 when logged
      out.
    - `catalog apply`: create, publish, the 412 diff, an invalid combination and `CATALOG_EXISTS`.
    - `test_catalog_show_output_round_trips_through_apply`.
    - `schema publish` answered 201, 200, 409 and 422.
    - One audit entry per admin write, read from the in-memory lake store's committed
      `tables.audit_log` (M7.1); the `AuditReader` port arrives with M16.1.
- Modify:
  - `src/huron/applications/cli/commands/__init__.py`: registers `schema`.
  - `docs/raw-lake/cli.md`: the §3 `catalog show` line.
  - `docs/raw-lake/operations.md` §3: the "first `huron catalog apply`" line. This task creates the verb;
    M9 writes the rest of §3.
- Design: DT-20 decisions ("Administration verbs (Owner decision 8)"); DT-20 command signatures, routes and
  exit codes (the administration table rows `catalog show`, `catalog apply`, `schema list`, `schema show`,
  `schema publish`, and the paragraph saying rows 8 and 9 take no `--reason`); DT-20 deletions (no
  `catalog list`); DT-10 "administration route table" and its CLI verb list; DT-18 route table (rows 5–9,
  17–19); DT-7 `huron.schema.metadata` (field diff).
- Verification:
  - The plan-wide gate. `uv run pytest tests/unit/cli/test_cli_admin.py -q` passes.
  - `uv run huron catalog --help` lists exactly `use`, `show` and `apply`: no second verb serves row 4
    (`get catalogs` does, DT-20 deletions).
  - The duplication baseline is unchanged, or any new signature is recorded within G6's four.
  - `make docs` passes. Every created or modified file is at 100 % line coverage.
- Dependencies: M10.5.
- Status: pending

### M10.7 The `Prompter` seam and the role-mapping and signing-key verbs

- Intent: the TTY seam that every confirming or interactive verb uses (DT-20 keeps `questionary` behind
  `QuestionaryPrompter` only). With it come the remaining administration verbs, `role list`, `role map`,
  `role unmap`, `key list`, `key rotate` and `key withdraw` (OQ-5.2 (a)), and `RoleChoice`, pinned to the
  served `RoleCode`. This task finishes RL step 2.
- Delete: none.
- Create:
  - `src/huron/applications/cli/walkthrough.py`, its prompt half only (the plan, sinks and state machine are
    M12.1's): `AnswerKind` (members only; `of` and `parse_answer` follow in M12.1), `Question`, `Aborted`,
    `Prompter` and `QuestionaryPrompter`.
    - Choices render with `questionary.select`, with type-to-filter above 15 entries; free text renders
      with `questionary.text` and its `default`, with the description and examples on stderr.
    - Prompts use `unsafe_ask`, so Ctrl-C or EOF raise `Aborted`. The constructor raises `UsageError` when
      `stdin` is not a TTY.
  - `tests/unit/cli/test_cli_prompter.py`: drives `QuestionaryPrompter` through `prompt_toolkit`'s
    `create_pipe_input()` and `DummyOutput` inside `create_app_session(...)`, with a `stdin` stand-in that
    reports a TTY. Cases: a text answer; a default accepted by Enter; an empty optional answer returning
    `None`; a select; a select with filter; Ctrl-C raising `Aborted`; a non-TTY `stdin` raising `UsageError`.
- Modify:
  - `src/huron/applications/cli/commands/admin.py`:
    - `role list [--catalog]` (row 14, or row 11 with `--catalog`).
    - `role map GROUP ROLE [--catalog] [--gid] [-m]` (row 15 or 12): the group is percent-encoded as one
      path segment; 201 prints "created", 200 prints "replaced or unchanged".
    - `role unmap GROUP [--catalog] [-m] [--yes]` (row 16 or 13), a **confirm** verb.
    - `key list` (row 20).
    - `key rotate PRIVATE_REF [--active-from] [-m]` (row 21, fresh `Idempotency-Key`): a naive
      `--active-from` exits 2.
    - `key withdraw KID [-m] [--yes]` (row 22), a **confirm** verb.
    - `RoleChoice`.
  - `src/huron/applications/cli/services.py`: `prompter: Callable[[], Prompter]`, a factory. The design gives
    the field as `prompter: Prompter`, but `QuestionaryPrompter`'s constructor refuses a non-TTY `stdin`:
    built eagerly in `main()`, it would refuse every piped run of every verb. So construction waits until
    a verb first asks.
  - `src/huron/applications/cli/__init__.py`: binds the factory to
    `QuestionaryPrompter(sys.stdin, <stderr console>)`.
  - `src/huron/applications/cli/commands/__init__.py`: `ReasonOption` and `YesOption`; registers `role` and
    `key`. A confirm verb without `--yes` calls the factory, so with no TTY it exits 2 before any write.
  - `tests/unit/cli/conftest.py`: `ScriptedPrompter` (records each `Question` and replays scripted answers
    and choices), bound as the harness's factory.
  - `tests/unit/cli/test_cli_admin.py`:
    - The role and key verbs against their rows with the role ladder (exit 5 below each row's minimum).
    - Group percent-encoding with `/` and spaces.
    - `test_role_choice_equals_the_served_role_code`: `{c.value for c in RoleChoice}` equals the `RoleCode`
      enum in `create_app()`'s OpenAPI document.
    - 409 `ROLE_MAPPING_REFUSED` (`last_platform_owner`, `seeded_mapping`) exits 6, and so do
      `ROTATION_REFUSED` and withdrawing a non-pending key (`not_pending`).
    - Confirm verbs exit 2 without a TTY and proceed with `--yes`.
  - `docs/raw-lake/cli.md` §10, Administration by role: every admin verb with its minimum role taken from
    DT-18's table; `withdraw` asks for confirmation.
  - `docs/raw-lake/operations.md` §4 "Rotating signing keys", the whole section from DT-26's outline (the
    new key file added to the Secret first, then `huron key rotate <private_ref> [--active-from]`, and
    `huron key withdraw <kid>` for a pending key): every line names a verb this task creates, so no earlier
    task writes §4.
  - `design/auth.html` §5 "Signing keys": the `huron key rotate` mention that M9.6 left to this task.
  - `docs/getting-started/local-development.md`, "Raw lake development": `make dev-keys KEY=dev-es256-2.pem`,
    then `huron key rotate dev-es256-2.pem` (DT-26 row).
  - `design/roadmap.html`: the RL step 2 tag becomes `done`.
- Design: DT-20 decisions ("Administration verbs (Owner decision 8)", "No new exit codes"); DT-20 target
  module layout; DT-20 interfaces and contracts → "`walkthrough.py`: plan, prompts, sinks and the state
  machine" (`Question`, `Prompter`, `QuestionaryPrompter`, `Aborted`, the `Prompter` contract); DT-20
  command signatures, routes and exit codes (shared options, the **confirm** convention, the role and key
  rows, `RoleChoice`); DT-20 handoffs (DT-19 row: `Services.prompter`); DT-10 "administration route table";
  DT-18 route table (rows 11–16, 20–22); DT-26 the two new pages (CLI guide §10, operations §4); DT-26
  developer docs (`local-development.md` new §); DT-26 roadmap rows (RL step 2).
- Verification:
  - The plan-wide gate. `uv run pytest tests/unit/cli -q` passes, including the named tests.
  - `uv run python -c "import importlib.resources as r; assert r.files('questionary').joinpath('py.typed').is_file()"`
    exits 0, so mypy strict needs no override. If it fails, the task stops and reports, because the design
    adds no override.
  - `rg -ln "questionary|prompt_toolkit" src/huron/applications/cli` prints only
    `src/huron/applications/cli/walkthrough.py`.
  - RL step 2's gate holds: `test_meta_validate_agrees_with_the_server_validator` (M10.5), the 409
    `SCHEMA_VERSION_EXISTS` case (M10.6) and one audit entry per admin write (M10.6 and this task) pass.
  - `make docs` and `git diff --check` pass. Every created or modified file is at 100 % line coverage.
- Dependencies: M10.6.
- Decisions: OQ-5.2 (settled, owner decision 12)
- Status: pending

## Milestone 11 — Volume, permissions and collections

Spec build step 3 on the server. The shared marker and mountinfo rules land in `huron.schema.volume` and the
RFC 7396 merge patch in `huron.schema.metadata`; `rawstore` turns its surviving primitives into `anchored.py`,
gains the mount probe, `PosixVolume` and both `DirectoryPermissions` adapters, and loses
`CompletionAdmission`, with contract 9 taking its DT-1 form; the lake gains its volume, permission, access-reset
and collection ports, `Directories`, `Collections` (draft, merge-patch save, activate, get, search, delete),
`MetadataFile`, `require_on_collection` and the Incomplete recompute on config publish; revision
`0016_lake_collections` lands with every half that writes its tables and their contract tests; the API opens
the volume in its lifespan, reports it in `/readyz`, runs the `AccessResetWorker`, and serves DT-18 rows 23–30;
DT-23's plain-directory stand-in (`tests/fakes/ontap_volume.py`, `make raw-lake-init`, `make raw-lake-snapshot`,
the compose bind, `dev.env`, `check-stack.sh volume`) makes the development stack carry a volume. Nothing here
builds `Volume.rename_collection` or `Directories.place_moved` (DT-15, M16); the Linux-only NFS cases wait for
M15's `tests/linux/`. Group G5 may add at most four duplication-baseline signatures across M11 and M13, each
recorded under "Execution notes".

### M11.1 Shared volume and merge-patch rules; the step-3 lake ports and values

- Intent: land the pure rules and port shapes every later step-3 task builds on: the marker format and the
  mountinfo parsing shared by the server probe and the CLI, RFC 7396 merge patch shared by draft saves and the
  CLI's bulk-edit preview, and the lake-owned volume, permission, access-reset, collection and completeness
  ports with their values. No adapter, composite or operation changes: `LakeStore`/`LakeTransaction` gain
  these bases only in the tasks whose adapters satisfy them, so the structural-conformance test stays green.
- Delete: none.
- Create:
  - `src/huron/schema/volume.py` (stdlib only, no I/O): `MARKER_NAME`, `MARKER_FORMAT`, `MAX_MARKER_BYTES`,
    `MarkerError` (`reason`, `detail`), `VolumeMarker` (`parse`, `render`), and under OQ-21.1 (a)
    `MountEntry` (mount point, filesystem type, mount options) and `mount_entry(mountinfo, mount_point)`
    (field split, the ` - ` separator, octal unescaping, last entry for the mount point wins).
  - `tests/unit/test_schema_volume_marker.py`: DT-11's marker cases (round trip; > 4 KiB, not JSON, not an
    object, unknown key, wrong `format`, non-canonical or missing `volume_id`, empty or 65-character `label`)
    plus `mount_entry` cases: an `nfs4` and an `nfs` entry, no entry, an over-mount (last wins), a `\040`
    escape, the options field carrying `nconnect=8`.
  - `tests/unit/test_schema_merge_patch.py`: RFC 7396 appendix A examples and R12-1's two cases.
  - `tests/unit/test_lake_volume_ports.py`: `Access.for_role` over every `Role`; `AccessList.derive` (max role
    per gid, unique ascending gids, empty list legal, a non-positive gid raises `ValueError`); `removable` over
    every `EntryKind`, `metadata.json` only at the collection root, the `.part` suffix, dot-files;
    `CollectionState.settled`; `CollectionRecord.volume_path` (`None` for a draft, `(catalog, *labels, name)`
    when settled).
- Modify:
  - `src/huron/schema/metadata.py`: `apply_merge_patch(target, patch)` (OQ-20.1 (a): here, not
    `lake/_impl/merge_patch.py`, which is never created).
  - `src/huron/core/lake/ports.py`: values `VolumePath`, `Access`, `GroupMapping`, `GroupAccess`, `AccessList`,
    `DirectoryKind`, `FileOutcome`, `FileCheck` (no `stamp` yet; M13.3 adds it), `EntryKind`, `DiskEntry`,
    `Removal`, `removable`, `AccessResetClaim`, `SettledCollection`; Protocols `Volume` (`volume_id`, `check`,
    `create_directories`, `verify`, `write_metadata`, `walk`, `remove_part`, `remove_collection`; no
    `rename_collection`), `DirectoryPermissions`, `CatalogAccessReader`, `AccessResetQueue`,
    `AccessResetWriter` (`request_access_reset`), `CollectionStore` (`catalog_of`, `collection`, `settled_at`,
    `namespaces`; `search` and `active_paths` join it in M11.7 with their halves), `CollectionWriter`
    (DT-12's methods except `unfinished_commits`, which M13.5 adds with `lake.commits`), `CompletenessWriter`
    (`scan_settled(catalog_id, after: str | None, limit)` per D-4, `set_states`).
  - `src/huron/core/lake/types.py`: `CollectionRecord`, `NamespaceRecord`, `CollectionQuery` (beside M7.1's
    `CollectionState`).
  - `src/huron/core/lake/__init__.py`: the new public names.
- Design: "DT-11 the marker and the mount policy"; "DT-11 interfaces and contracts" (`lake/ports.py`:
  port-owned values; the `Volume` port; `DirectoryPermissions`, `CatalogAccessReader`, `AccessResetQueue`);
  "DT-12 interfaces and contracts" (`lake/types.py` and `lake/ports.py`: values and the store methods DT-17
  implements; `apply_merge_patch`; `Volume.remove_collection` and `removable`); "DT-15 interfaces and
  contracts" (`lake/ports.py`: the `Volume` port, `rename_collection` replaced); "DT-18 paging keys and the
  `label` filter" (`CollectionQuery`; `CollectionStore.search` is M11.7's); "DT-9 interfaces and contracts"
  (`huron.core.lake.schemas`: validation, the cache and the Incomplete computation); "DT-17 resolved
  disagreements between sections" (D-4); "DT-21 open questions" (OQ-21.1); "DT-20 open questions" (OQ-20.1).
- Verification:
  - The plan-wide gate; `uv run lint-imports` keeps all 20 contracts (`huron.schema.volume` is stdlib only;
    `lake → schema` is already admitted).
  - `uv run pytest tests/unit/test_schema_volume_marker.py tests/unit/test_schema_merge_patch.py
    tests/unit/test_lake_volume_ports.py` passes; `volume.py`, `metadata.py`, `ports.py` and `types.py` are at
    100 % line coverage in the unit run.
  - `rg -n "rename_collection|merge_patch\.py" src tests` prints nothing.
- Dependencies: M4, M6, M7.
- Decisions: OQ-20.1 (settled, owner decision 12)
- Decisions: OQ-21.1 (settled, owner decision 12)
- Status: pending

### M11.2 Anchored primitives, the mount probe and contract 9

- Intent: turn the surviving `rawstore` primitives into the internal seam of the volume adapters, add the
  mount probe, and delete what no server operation needs (`CompletionAdmission`, `rename_exclusive`, the
  sealed/owner/`nlink` refusals). `anchored.observe` returns lake's `FileOutcome`, so this is the first
  `rawstore → lake` import and contract 9 takes its DT-1 form in the same commit.
- Delete (orchestrator `git rm` before the pass): `src/huron/core/rawstore/completion.py`,
  `tests/unit/test_rawstore_completion_admission.py`. Rename (orchestrator `git mv` before the pass):
  `src/huron/core/rawstore/materialize.py` → `src/huron/core/rawstore/anchored.py`;
  `tests/unit/test_rawstore_materialize.py` → `tests/unit/test_rawstore_anchored.py`.
- Create:
  - `src/huron/core/rawstore/mount.py`: `MountPolicy`, `MountReport`, `probe_mount(prefix, policy, expected,
    *, rules, mountinfo=None)` running the probe table's checks 1–7 and the `io_error` row in order, each
    raising foundation `DependencyUnavailable` with DT-11's context; and `VolumeRules`, a frozen value of two
    callables (marker parsing, mount lookup) whose results rawstore types with local structural Protocols.
    Design conflict (Risk register): contract 9 forbids `huron.core.rawstore → huron.schema`
    while DT-11 and OQ-21.1 (a) have `probe_mount` use `VolumeMarker.parse` and `mount_entry`; this plan keeps
    contract 9 exactly as DT-1 states it and has the caller (the API lifespan, tests, the stand-in) pass
    `VolumeRules(VolumeMarker.parse, mount_entry)`. Nothing in `rawstore` imports `huron.schema`.
  - `tests/unit/test_rawstore_mount.py`: DT-11's cases; the strict policy through mountinfo fixtures, so it
    runs on macOS; `unsupported_platform` by making the `/proc/self/mountinfo` read raise
    `FileNotFoundError` (no platform skip); a prefix symlink is `not_a_directory`.
- Modify:
  - `src/huron/core/rawstore/anchored.py`: `descendant(…, create_mode: int | None)`, new `make_directory`
    (mkdir, open `O_NOFOLLOW`, `fchmod`, `fsync` parent; `ELOOP`/`ENOTDIR` classified by `lstat` as
    `NotADirectoryError`), `observe(…, expected_size)` returning `(FileOutcome, size, sha256)` with the size
    short-circuit, the before/after `fstat` stability test and 8 MiB reads; `rename_exclusive` and the
    `ctypes`/`sys` imports go; `directory`, `write_all`, `fsync_dir` unchanged.
  - `src/huron/core/rawstore/generations.py`: imports `write_all` and `fsync_dir` from `.anchored`.
  - `src/huron/core/rawstore/__init__.py`: exports `PosixGenerationStore`, `MountPolicy`, `probe_mount`,
    `VolumeRules`; the primitives and `CompletionAdmission` are no longer exported.
  - `pyproject.toml` contract 9: name "rawstore uses lake and foundation only", `allow_indirect_imports =
    true`, forbidden `huron.core.security`, `huron.core.hierarchy`, `huron.core.metastore`, `huron.schema`.
  - `tests/unit/test_rawstore_anchored.py`: DT-11's anchored cases (kept `directory`/`descendant`/
    `write_all`/`fsync_dir`; `make_directory` under umask 022; `observe`: present, size mismatch with a
    monkeypatched `os.read` that fails if called, FIFO → `NOT_REGULAR` without blocking, symlink, directory,
    a foreign-owned and an `nlink == 2` file accepted through a monkeypatched `os.fstat`, an append during
    the hash → `UNSTABLE`); the `rename_exclusive` cases go. `tests/unit/test_rawstore_generation.py` follows
    any moved import.
  - `tests/unit/test_domain_import_contracts.py` (its sandbox copies the real `pyproject.toml`): in the
    allowed-edges table `"rawstore": ("schema",)` becomes `("core.lake", "core.foundation")`; the
    forbidden `rawstore → lake` case (M4.1) is replaced by `rawstore → schema` and `rawstore → security`,
    each expecting "rawstore uses lake and foundation only" BROKEN.
- Design: "DT-11 decisions" (Primitives, Bounded re-hash, Mount policy); "DT-11 target module layout"; "DT-11
  the marker and the mount policy"; "DT-11 interfaces and contracts" (`rawstore/anchored.py`: the adapted
  primitives); "DT-11 deletions"; "DT-1 import-linter contract set (diff against the sixteen)" (contract 9);
  "DT-2 decisions" (Surviving primitives).
- Verification:
  - The plan-wide gate; `uv run lint-imports` keeps all 20 contracts, contract 9 under its new name.
  - `uv run pytest tests/unit/test_rawstore_anchored.py tests/unit/test_rawstore_mount.py
    tests/unit/test_rawstore_generation.py` passes; `anchored.py` and `mount.py` at 100 %;
    `uv run pytest tests/unit/test_domain_import_contracts.py` passes.
  - `rg -n "CompletionAdmission|rename_exclusive|from \.materialize|rawstore\.materialize|completion_max_concurrent|sealed=" src tests`
    prints nothing; `rg -n "ctypes|huron\.schema" src/huron/core/rawstore` prints nothing;
    `test ! -e src/huron/core/rawstore/completion.py`.
  - The verifier checks the delete and rename lists against `git status`.
- Dependencies: M11.1; M1 (D2-3's `rawstore`), M5 (foundation `DependencyUnavailable`).
- Decisions: OQ-21.1 (settled, owner decision 12)
- Status: pending

### M11.3 `PosixVolume` and the volume stand-in module

- Intent: build the only `Volume` adapter (unit, contract, development and production) over a descriptor held
  on the prefix, with the bounded hash, the common error table and DT-12's `remove_collection`; and land
  `tests/fakes/ontap_volume.py`, because the `.snapshot` walk case and the stand-in's own tests are its first
  users (DT-23's handoff to DT-11). The make targets, compose and `dev.env` follow with the lifespan (M11.11).
- Delete: none.
- Create:
  - `src/huron/core/rawstore/volume.py`: `PosixVolume` with an async `open(prefix, volume_id, *, policy, rules,
    max_concurrent_hashes)` (probe on a worker thread; refuses on failure; rawstore cannot import
    `ApiSettings`, so the lifespan passes the values), `close`, `volume_id`, `check` (2 s probe timeout,
    `st_dev` comparison → `remounted`), `create_directories`, `verify` (private `asyncio.Semaphore`; outcomes,
    never exceptions, for file problems), `write_metadata` (`.part`, rename, directory `fsync`), `walk`
    (worker-thread batches of 1,000, `.snapshot` never entered, symlinks yielded not followed, descriptors
    closed on `aclose`), `remove_part`, `remove_collection` (DT-12: `removable` scan, bottom-up removal,
    `containers` `rmdir`ed ignoring `ENOENT`/`ENOTEMPTY`, a missing collection is `Removal(True, ())`); the
    common error table (`io_error`, `permission_denied`, `directory_missing`, `unexpected_entry`, `timeout`
    after `VOLUME_OPERATION_TIMEOUT` 30 s); `ValueError` on a `VolumePath` that breaks the traversal facts.
  - `tests/fakes/ontap_volume.py`: `DEV_LABEL`, `SNAPSHOT_DIR`, `SNAPSHOT_NAME`, `StandInError`, `init_volume`,
    `take_snapshot`, `main` (stdlib and `huron.schema.volume` only).
  - `tests/unit/test_rawstore_volume.py`: DT-11's cases except `rename_collection` (DT-15 replaces it in
    M16), with the `.snapshot` walk fixture built by `take_snapshot`; `UNREADABLE` through a monkeypatched
    `os.open` raising `PermissionError` on that name (no root skip); DT-12's `remove_collection` cases
    (removes `metadata.json`, `.part` files and empty subdirectories; keeps everything when one user file
    exists; ignores `ENOTEMPTY` containers; a missing collection counts as removed).
  - `tests/unit/test_fake_ontap_volume.py`: DT-23's cases, including `probe_mount(MARKER_ONLY)` accepting
    `init_volume`'s marker and `PosixVolume.walk` yielding nothing below any `.snapshot`.
- Modify: `src/huron/core/rawstore/__init__.py` exports `PosixVolume`.
- Design: "DT-11 interfaces and contracts" (`lake/ports.py`: the `Volume` port, its common error table and
  Lifecycle); "DT-11 tests this design requires" (`test_rawstore_volume.py` row); "DT-12 interfaces and
  contracts" (`Volume.remove_collection` and `removable`); "DT-12 tests this design requires" (Volume row);
  "DT-23 the volume stand-in: `tests/fakes/ontap_volume.py`"; "DT-23 handoffs" (DT-11 row); "DT-15 interfaces
  and contracts" (`rename_collection` replaced).
- Verification:
  - The plan-wide gate; `uv run lint-imports` keeps all 20 contracts.
  - `uv run pytest tests/unit/test_rawstore_volume.py tests/unit/test_fake_ontap_volume.py` passes;
    `volume.py` at 100 %. The concurrency case (`max_concurrent_hashes=1`, two `verify` calls on a blocking
    reader overlap zero times) passes.
  - `p=$(mktemp -d)/projects; uv run python -m tests.fakes.ontap_volume init --prefix "$p" --id
    0b8f3c1e-6a52-4c39-9f43-2f7d5e0a9c11` exits 0, the same command again exits 0 and leaves the marker
    byte-identical, and another `--id` exits non-zero naming both ids (`marker_conflict`).
  - DT-11's closing check prints nothing (as in M11.2); `rg -n "rename_collection" src tests` and
    `rg -n "tests\.fakes" src` print nothing (DT-22's guard test passes).
  - The real-NFS behaviour (DT-11 cases 4–5) is M15's `tests/linux/test_nfs_volume.py`.
- Dependencies: M11.2; M5 (`tests/fakes/` and its import guard).
- Status: pending

### M11.4 Directory permissions adapters, `Directories` and `mappings_for_catalog`

- Intent: land the domain rule "role → access" and its top-down ordering in `lake.Directories`, both
  `DirectoryPermissions` adapters (the NFSv4 ACL encoder and the recording fake), and the role-mapping read
  `Directories` needs, so a provision or a reset writes exactly the derived access.
- Delete: none.
- Create:
  - `src/huron/core/rawstore/permissions.py`: `Ace`, pure `encode_acl`/`decode_acl` (Linux `system.nfs4_acl`
    XDR), `Nfs4AclPermissions` (constructor refuses unless `sys.platform == "linux"`; `U = os.geteuid()`;
    canonical ACE order; read, compare, write on the `O_NOFOLLOW` descriptor; `acl_unsupported` on
    `ENOTSUP`/`EOPNOTSUPP`; `apply_content` skips `.snapshot` and symlinks, skips per-entry `ENOENT`, collects
    `EACCES` and raises once), `RecordingPermissions` (`calls: list[Applied]`, last access per target,
    `apply_content` returning the entry count a `PosixVolume.walk` would visit).
  - `src/huron/core/lake/directories.py`: `ResetReport`, `Directories(volume, permissions, mappings)` with
    `provision` and `reset(catalog, collections, *, heartbeat=None)`; not `place_moved` (DT-15, M16).
  - `tests/unit/test_rawstore_permissions.py`: `encode_acl`/`decode_acl` round trip; the access table's ACE
    lists byte for byte per `DirectoryKind` and role (golden hex masks); canonical ordering; the constructor
    with `sys.platform` monkeypatched to `darwin` (refused) and `linux` (built); `apply`/`apply_content` over
    monkeypatched `os.getxattr`/`os.setxattr` (`raising=False`), covering change detection, `acl_unsupported`
    and the collected `permission_denied`; `RecordingPermissions` change detection.
  - `tests/unit/test_lake_directories.py`: `PosixVolume` on `tmp_path` + `RecordingPermissions` +
    `InMemoryRoleMappings`: `AccessList.derive` through real mappings (global rows on every catalog; Reader,
    Developer, Platform Owner); `provision` order (containers top-down, then the collection) and idempotence;
    `reset` order (catalog directory first), `heartbeat` after each collection, a missing collection counted;
    a mapping change followed by `reset` changes exactly the affected targets.
- Modify:
  - `src/huron/core/metastore/lake/role_mappings.py`: `mappings_for_catalog` on `PostgresRoleMappings` and
    `InMemoryRoleMappings` (rows for the catalog or global, joined to `lake.ldap_groups` for `posix_gid`).
  - `src/huron/core/lake/ports.py`: `LakeStore` gains `CatalogAccessReader`.
  - `tests/lake_store_contract.py` (the role-mapping area; DT-17's single scenario module replaces DT-4's
    `tests/lake_role_mapping_contract.py`, which M4.2 never creates): `mappings_for_catalog` scenarios
    (catalog and global rows, gid from `ldap_groups`, another catalog's rows excluded), run against both
    adapters by `tests/unit/test_lake_memory_store.py` and `tests/contract/test_lake_store.py`.
  - `src/huron/core/rawstore/__init__.py` exports `Nfs4AclPermissions`, `RecordingPermissions`;
    `src/huron/core/lake/__init__.py` exports `Directories`, `ResetReport`.
- Design: "DT-11 the access table"; "DT-11 interfaces and contracts" (`DirectoryPermissions`,
  `CatalogAccessReader`, `AccessResetQueue`; `lake/directories.py`: `Directories`); "DT-11 tests this design
  requires" (permissions and directories rows; the contract paragraph); "DT-17 port → adapter → fake"
  (`CatalogAccessReader` row); "DT-17 DDL: `0015_lake_catalog`" (the `mappings_for_catalog` note); "DT-15
  interfaces and contracts" (`Directories.place_moved` is DT-15's).
- Verification:
  - The plan-wide gate; `uv run lint-imports` keeps all 20 contracts (`lake.directories` imports nothing from
    `rawstore`, contract 13).
  - `uv run pytest tests/unit/test_rawstore_permissions.py tests/unit/test_lake_directories.py` passes;
    `permissions.py` and `directories.py` at 100 %.
  - Run in the background and poll: `uv run pytest -m contract tests/contract/test_lake_roles.py
    tests/contract/test_lake_store.py`; the Postgres half reaches 100 % in `uv run pytest -m "unit or
    contract" --cov=src/huron --cov-report=term-missing --cov-fail-under=0`.
  - `rg -n "place_moved" src` prints nothing. DT-11 cases 1–3 (golden ACLs on NFSv4.2, Reader/Developer
    access, downgrade and unmap) are M15's `tests/linux/test_nfs_permissions.py`.
- Dependencies: M11.3; M8 (role-mapping halves and their contract scenarios).
- Decisions: OQ-4.1 (settled, owner decision 12)
- Decisions: OQ-11.1 (settled, owner decision 12)
- Status: pending

### M11.5 Revision `0016_lake_collections`

- Intent: create `lake.namespaces`, `lake.collections` and `lake.access_resets` exactly as DT-17 writes them,
  with the schema map and the DDL-level contract tests; the adapters that write the three tables land in
  M11.6–M11.8 of this milestone.
- Delete: none.
- Create: `migrations/versions/0016_lake_collections.py`: `revision = "0016_lake_collections"`,
  `down_revision = "0015_lake_catalog"`, a module docstring naming the invariants, one `execute_sql` block
  holding DT-17's DDL verbatim (`<SEGMENT>` written literally from `naming.SEGMENT_PATTERN`; the namespaces
  trigger reuses 0015's `lake.reject_mutation()`); `downgrade()` calls `refuse_if_rows("lake.namespaces",
  "lake.collections", "lake.access_resets")` and then drops the objects in reverse order. No import of
  `huron`.
- Modify:
  - `migrations/schema.sql`: the `lake` section gains the three tables in the map's compressed style with
    `-- [db]` notes for the settled CHECK, both triggers and the partial indexes, and `-- [spec]` notes for
    `version` replacing `etag` and the added columns; the section header gains the `ltree` and
    `collections_metadata_gin` sentences that M8.2 left to this revision; `-- Reflects: 0016_lake_collections`.
  - `tests/contract/test_lake_schema.py`: `test_upgrade_downgrade_round_trip` reaches the new head, expects
    exactly thirteen tables in schema `lake` after each upgrade (M8.2's ten plus the three), and the
    downgrade refuses with a row in each of the three tables; `test_immutability_triggers` gains the
    collections guard (fixed columns, return to draft, lower `version`) and the namespaces update refusal;
    `test_settled_check_and_fks` gains the settled CHECK in each direction and `collections_pinned_config`;
    this task creates `test_ltree_subtree_with_hyphens` (M8.2 does not) with its raw-SQL half (R17-1's `<@`
    results and the GiST plan with `enable_seqscan = off`).
  - `tests/unit/test_lake_ddl_sync.py`: 0016's segment CHECKs embed `naming.SEGMENT_PATTERN`; its three
    tables appear in `schema.sql`'s `lake` section.
- Design: "DT-17 DDL: `0016_lake_collections`"; "DT-17 decisions" (Types, Extension, Immutability, Downgrade);
  "DT-17 revision list"; "DT-17 `migrations/schema.sql` and the import rules"; "DT-17 resolved disagreements
  between sections" (D-3, D-6); "DT-12 `lake.collections` and `lake.namespaces`: logical shapes (DT-17 writes
  the DDL)"; "DT-17 the shared migrate helper and the tests".
- Verification:
  - The plan-wide gate (`scripts/check_schema_map.py` sees the new stamp).
  - `uv run pytest tests/unit/test_lake_ddl_sync.py tests/unit/test_check_schema_map.py` passes.
  - Run in the background and poll: `uv run pytest -m contract tests/contract/test_lake_schema.py`.
  - `rg -n "^(from|import) huron" migrations/versions/0016_lake_collections.py` prints nothing;
    `rg -n "INDEX \w+ ON lake\.collections \(namespace_id" migrations/versions/0016_lake_collections.py`
    prints nothing (D-3).
- Dependencies: M8 (`0015_lake_catalog`, `refuse_if_rows`, `tests/postgres.py`, the two test modules), M6.
- Decisions: OQ-17.1 (settled, owner decision 12)
- Decisions: OQ-17.2 (settled, owner decision 12)
- Status: pending

### M11.6 Collection and namespace store halves

- Intent: implement `CollectionStore` and `CollectionWriter` on Postgres and in memory with DT-12's
  lock-then-check semantics, the layout and metadata-file advisory locks, and the `CollectionExists` mapping
  from the identity unique keys.
- Delete: none.
- Create: `src/huron/core/metastore/lake/collections.py`: `PostgresCollections` and `InMemoryCollections`
  halves with `catalog_of`, `collection`, `settled_at`, `namespaces` (keyset by `path`, `under` exclusive),
  `lock_catalog` (`FOR SHARE`, returns `config_version`), `lock_layout`, `lock_collection`, `insert_draft`,
  `update_draft`, `attach_namespace`, `settle` (inside a savepoint; a unique violation becomes
  `CollectionExists` naming the holder), `delete_collection`, `prune_namespaces`, `lock_metadata_file`.
- Modify:
  - `src/huron/core/metastore/lake/locks.py`: `LockClass.LAYOUT`, `LockClass.METADATA_FILE`.
  - `src/huron/core/metastore/lake/store.py`, `memory.py`: compose the halves; the fake's lock registry gains
    per-collection locks and advisory `(class, key)` locks (M4.1's per-catalog readers-writer lock serves
    `lock_catalog`).
  - `src/huron/core/lake/ports.py`: `LakeStore` gains `CollectionStore`; `LakeTransaction` gains
    `CollectionStore` and `CollectionWriter`.
  - `src/huron/core/lake/errors.py`: `CollectionExists` (409 `COLLECTION_EXISTS`, context `{identifier,
    collection_id}`) and its `ERROR_CODES` entry; `design/api.html` §7 gains DT-18's `COLLECTION_EXISTS` row.
  - `tests/lake_store_contract.py`: a collections area (a write without `lock_collection`, and a stale
    recorded version, raise `LockContractBroken`; `attach_namespace` keeps the table prefix-closed;
    `prune_namespaces` returns deepest first and keeps a namespace with a settled collection beneath;
    `namespaces` order equals `NamespacePath.labels` order (R17-2); `identifier` equals the joined form after
    `settle`; drafts with NULL identity never collide; Postgres-only: a `settle` race raises
    `CollectionExists` with the holder).
  - `tests/lake_store_contract.py` (collections area): DT-4's `catalog_of` scenarios ("collection in an
    unreadable catalog", "unknown id").
  - `tests/contract/test_lake_schema.py`: `test_etag_cas_race` gains its collections half;
    `test_ltree_subtree_with_hyphens` gains `namespaces(under=…)` against the store.
- Design: "DT-12 interfaces and contracts" (`lake/types.py` and `lake/ports.py`: lock-then-check, lock order,
  `lock_layout`, `attach_namespace`, `settle`, `delete_collection`, `prune_namespaces`, `lock_metadata_file`,
  `settled_at`); "DT-12 invariants the aggregate enforces" (I-12.4, I-12.5, I-12.10); "DT-17 interfaces and
  contracts" (Correctness model, The fake); "DT-17 port → adapter → fake" (`CollectionStore`,
  `CollectionWriter` rows); "DT-17 target module layout"; "DT-4 interfaces and contracts" (`core/lake`:
  applying the grants: the `catalog_of` statement); "DT-18 error-code table rows".
- Verification:
  - The plan-wide gate and `make docs`; `uv run pytest tests/unit/test_lake_memory_store.py tests/unit/test_lake_ddl_sync.py
    tests/unit/test_error_contract.py` passes (structural conformance of both roots and transactions; no two
    halves share a public name).
  - Run in the background and poll: `uv run pytest -m contract tests/contract/test_lake_store.py
    tests/contract/test_lake_schema.py`. `test_etag_cas_race` is a named race test: an intermittent failure
    stops the milestone and is never re-run to green.
  - `rg -nP 'FROM (?!lake\.)\w+|JOIN (?!lake\.)\w+' src/huron/core/metastore/lake` prints only CTE names.
  - `collections.py` reaches 100 % in `uv run pytest -m "unit or contract" --cov=src/huron
    --cov-report=term-missing --cov-fail-under=0`; any floor re-baseline follows the plan-wide rule.
- Dependencies: M11.1, M11.5; M8.
- Decisions: OQ-17.2 (settled, owner decision 12)
- Status: pending

### M11.7 Collection search, active paths and the Incomplete recompute

- Intent: add the listing reads (`search` with the visibility and draft rules and the `label` containment
  filter, `active_paths` for resets) and DT-9's completeness half over collections, and call the recompute
  from config publish when `schema_id` changes, so I-9 holds from this milestone on.
- Delete: none.
- Create: `tests/unit/test_lake_completeness.py`: DT-9's Incomplete cases over the in-memory store (a publish
  whose schema adds a required field turns conforming-before collections `incomplete` with `version + 1` and
  leaves others untouched; a publish that changes only `title` or vocabularies recomputes nothing; a later
  publish that removes the problem returns them to `active`, T6), and `Completeness` counts.
- Modify:
  - `src/huron/core/metastore/lake/collections.py`: `search(query, readable, drafts, after, limit)` (settled
    rows keyset by `identifier`, drafts by `id`; `metadata @> $n::jsonb`; visibility applied before `LIMIT`),
    `active_paths(catalog_id)`, `scan_settled(catalog_id, after, limit)` (by `identifier`, D-4; each batch
    selected `FOR UPDATE`, the fake taking the per-collection locks, and every returned row's `id → version`
    recorded in the transaction's lock record as `lock_collection` records it) and `set_states(changes)`
    (each id must be in the lock record, else `LockContractBroken`; guarded on the recorded version,
    `version + 1` each, the new version recorded), on both halves. DT-17's correctness model names only
    `lock_collection`, `lock_collections` and `lock_commit` as recorders and `recompute_completeness` cannot
    call `lock_collection`, so this plan makes `scan_settled` the recompute's recorder; its row locks also
    serialize the recompute with a commit's final transaction, which bumps `version` without the catalog
    lock.
  - `src/huron/core/lake/ports.py`: `CollectionStore` gains `search` and `active_paths` (declared in this
    commit with their two halves above, so the structural-conformance test stays green); `LakeTransaction`
    gains `CompletenessWriter`.
  - `src/huron/core/lake/schemas.py`: `Completeness` and `Validation.recompute_completeness`.
  - `src/huron/core/lake/catalogs.py`: `Catalogs.publish_config` calls the recompute in its transaction after
    the catalog update when `schema_id` changed (trigger 1).
  - `tests/lake_store_contract.py`: search (catalog, `under` subtree, `identifier` exact, labels AND, string
    values only, settled by default, drafts only from the `drafts` set, keyset paging), `active_paths`,
    `scan_settled` order and `set_states` version bumps; `set_states` on an id that `scan_settled` did not
    return in this transaction raises `LockContractBroken`.
  - `tests/contract/test_lake_store.py`: `test_label_search_uses_gin` (10,000 collections; `EXPLAIN (FORMAT
    JSON)` with `enable_seqscan = off` names `collections_metadata_gin`; the result equals the fake's) and
    DT-9's 10,000-collection recompute timing, reported, not asserted.
- Design: "DT-9 interfaces and contracts" (`huron.core.lake.schemas`: validation, the cache and the Incomplete
  computation: I-9, triggers, serialization); "DT-9 tests this design requires" (Incomplete row); "DT-17
  resolved disagreements between sections" (D-4); "DT-18 paging keys and the `label` filter"; "DT-18
  decisions" (Drafts in the collection listing; `label` grammar); "DT-11 interfaces and contracts"
  (`applications/api`: the `AccessResetWorker` bullet, `active_paths`); "DT-11 handoffs" (DT-17 row:
  `active_paths`); "DT-17 interfaces and contracts" (Correctness model: lock-then-check, version-guarded).
- Verification:
  - The plan-wide gate; `uv run pytest tests/unit/test_lake_completeness.py tests/unit/test_lake_memory_store.py`
    passes.
  - Run in the background and poll: `uv run pytest -m contract tests/contract/test_lake_store.py`; the
    adapter reaches 100 % in the "unit or contract" run.
  - The metadata-publish race and "a valid metadata publish returns the collection to `active`" need DT-15's
    publish and land in M16.
- Dependencies: M11.6; M7 (`Catalogs.publish_config`, `Validation`), M3 (`Grants.readable(minimum)`).
- Decisions: OQ-9.1 (settled, owner decision 12)
- Decisions: OQ-18.2 (settled, owner decision 12)
- Decisions: OQ-18.3 (settled, owner decision 12)
- Status: pending

### M11.8 Access-reset queue and the mapping-write reset request

- Intent: make `lake.access_resets` a durable lease queue on both adapters and have every applied role-mapping
  change request a reset in its own transaction (D-6), so revocation reaches the volume through the worker of
  M11.12 rather than waiting for the reconciler.
- Delete: none.
- Create: `src/huron/core/metastore/lake/access_resets.py`, two halves per adapter:
  - the queue halves `PostgresAccessResets` and `InMemoryAccessResets` (`AccessResetQueue`), composed into
    the store root only: `claim` (the oldest unleased or lease-expired row, `FOR UPDATE SKIP LOCKED`, its
    own short transaction), `extend` (`PreconditionFailed` when the lease was lost), `complete` (deletes
    only while `requested_at` equals the claim's). Lease arithmetic uses the injected `Clock`;
  - the writer halves `PostgresAccessResetWriter` and `InMemoryAccessResetWriter` (`AccessResetWriter`),
    composed into the transaction only: `request_access_reset(catalog_id | None)` (upsert `requested_at`;
    `None` requests every catalog). The transaction never carries the queue half, because its
    `claim(owner, lease)` would meet `RetryTransaction.claim(claim)` from the claims halves (head,
    "`LakeStore` method names").
- Modify:
  - `src/huron/core/metastore/lake/store.py`, `memory.py`: compose the queue halves into the root and the
    writer halves into the transaction.
  - `src/huron/core/lake/ports.py`: `LakeStore` gains `AccessResetQueue`; `LakeTransaction` gains
    `AccessResetWriter`.
  - `src/huron/core/lake/_impl/mappings.py`: `apply_mapping` calls `tx.request_access_reset(catalog_id)` for
    every applied change (map, unmap and the bootstrap's seed path); a refused or no-op write requests none.
  - `tests/lake_store_contract.py`: an access-reset area (claim then lease expiry under `FakeClock`; complete
    keeps a row re-requested meanwhile; `extend` after a lost lease; a global request covers every catalog;
    Postgres-only: two concurrent claims take different rows and neither blocks).
  - `tests/unit/test_lake_role_mappings.py`: map and unmap write exactly one reset row in their transaction; a
    refusal rolls it back with the mapping. `tests/contract/test_lake_admin_store.py` gains the same
    assertion on Postgres. `tests/unit/test_lake_bootstrap.py`'s re-run case stays byte-identical.
- Design: "DT-11 interfaces and contracts" (`AccessResetQueue` bullet); "DT-11 decisions" (G-16); "DT-17 DDL:
  `0016_lake_collections`" (`lake.access_resets`); "DT-17 resolved disagreements between sections" (D-6);
  "DT-17 decisions" (Time); "DT-10 interfaces and contracts" (`core/lake/admin.py`: role mappings).
- Verification:
  - The plan-wide gate; `uv run pytest tests/unit/test_lake_role_mappings.py tests/unit/test_lake_bootstrap.py
    tests/unit/test_lake_memory_store.py` passes.
  - Run in the background and poll: `uv run pytest -m contract tests/contract/test_lake_store.py
    tests/contract/test_lake_admin_store.py`; `access_resets.py` reaches 100 % in the "unit or contract" run.
- Dependencies: M11.6; M7 (`RoleMappings`, `apply_mapping`), M8.
- Decisions: OQ-11.3 (settled, owner decision 12)
- Status: pending

### M11.9 Collections: drafts, reads, namespaces and `metadata.json`

- Intent: build the aggregate's creating, saving and reading operations, the single writer of `metadata.json`
  and DT-4's collection visibility check, all over the in-memory store and a real `PosixVolume` on
  `tmp_path`. Activation and deletion follow in M11.10.
- Delete: none.
- Create:
  - `src/huron/core/lake/collections.py`: `CollectionView`, `NamespaceView`, `MetadataFile` (`CONTRACT`,
    `render`, `sync`), and `Collections` with `create_draft`, `save_draft`, `get`, `namespaces`, `search` and
    `schema` (the read behind DT-9's `GET /collections/{id}/schema`: `resolved(current, pinned)`; a draft needs
    Developer, as `get`). `search` takes the label filter as a parsed `Mapping[str, str]`: the grammar's
    refusals are 422 `REQUEST_INVALID`, a transport code, so the route model raises them (M11.13); a malformed
    `under` is `PATH_RULE_VIOLATION` here. DT-18 heads its `search` signature `core/lake/_impl/collections.py`;
    the class lives in `lake/collections.py` (DT-1's tree, DT-12's layout), outside contract 16's private
    package.
  - `tests/unit/test_lake_collections.py`: T1 with its exact `create` entry (pair, `object_id`, `catalog_id`,
    `detail`) and version 1; a replayed key returns the first result and a reused key with another body is
    `IDEMPOTENCY_KEY_REUSED`; non-object or > 1 MiB metadata is `METADATA_INVALID` (`type`, `size`); T2 is not
    audited and bumps `version` even for an empty patch; `COLLECTION_STATE` (`allowed: ["draft"]`); a stale
    version is 412 with `current_version`; a Reader gets 403 on a draft and 404 on a hidden catalog's
    collection; `get` problems are `()` for `active` and full for `draft`/`incomplete`; `render` is
    byte-identical under key order, omits `state`/`version`/`file_count`/timestamps and refuses a draft;
    `sync` writes `render(row)` through `PosixVolume`, returns `False` for a draft or a missing row, and lets
    `DependencyUnavailable` propagate; `namespaces` refuses a malformed `under` with `PATH_RULE_VIOLATION`
    whose `context` equals the `NamingError`'s `{"rule": …, "value": …}` (the inherited
    `DomainError.__init__`; M1.4 deleted the code-override constructor, "DT-8 deletions"), is
    404 for a namespace without a row and lists rows strictly beneath; `search` filters on the fake.
- Modify:
  - `src/huron/core/lake/_impl/access.py`: `require_on_collection`.
  - `src/huron/core/lake/errors.py`: `CollectionStateConflict` (409 `COLLECTION_STATE`, context `{state,
    allowed}`) and its `ERROR_CODES` entry; `design/api.html` §7 gains DT-18's `COLLECTION_STATE` row.
  - `src/huron/core/lake/__init__.py`: the new public names.
  - `tests/unit/test_lake_access.py`: `require_on_collection` (an unknown id and an unreadable catalog give the
    same 404 detail; below the minimum is 403).
- Design: "DT-12 decisions"; "DT-12 the state machine" (T1, T2 and the shared rules); "DT-12 interfaces and
  contracts" (`huron.core.lake.collections.Collections`; `MetadataFile`); "DT-12 tests this design requires"
  (unit and pure rows); "DT-4 interfaces and contracts" (`core/lake`: applying the grants); "DT-9 interfaces
  and contracts" (Errors, routes and the CLI's use of `huron.schema`: the collection schema route); "DT-18
  paging keys and the `label` filter" (`Collections.search`); "DT-7 the vocabulary: action × object_type and
  `detail`"; "DT-17 resolved disagreements between sections" (D-7).
- Verification:
  - The plan-wide gate and `make docs`; `uv run pytest tests/unit/test_lake_collections.py tests/unit/test_lake_access.py
    tests/unit/test_error_contract.py` passes; `collections.py` and `_impl/access.py` at 100 %.
  - `rg -n "class Collections" src/huron/core/lake` names only `collections.py`.
- Dependencies: M11.3, M11.7; M7 (`Validation`, `Catalogs`, `AuditWriter`), M8.
- Decisions: OQ-18.2 (settled, owner decision 12)
- Decisions: OQ-20.1 (settled, owner decision 12)
- Status: pending

### M11.10 Collections: activation and deletion

- Intent: add T3, T4 and T11 with DT-12's sequences and failure tables: provision before the activation
  transaction, `metadata.json` after it, and a settled delete that refuses before any change while anything
  but removable entries is on disk.
- Delete: none.
- Create: none.
- Modify:
  - `src/huron/core/lake/collections.py`: `activate` (authorize; state checked before version; current and
    pinned configs; `require_valid`; `place`; `settled_at`; `Directories.provision`; the transaction in lock
    order with every re-check and `require_valid` again when `config_version` moved; `attach_namespace`,
    `settle`, the `activate` entry; `MetadataFile.sync` after the commit, a `DependencyUnavailable` there logged
    as `lake.collection.volume_deferred`) and `delete(actor, collection_id, expected_version, *, reason)` (a
    draft: Developer, row lock, delete, entry; a settled collection: Project Admin, `file_count = 0`, the
    `walk` pre-check with `removable`, the transaction with layout lock, `delete_collection`,
    `prune_namespaces` and the entry, then `remove_collection` with the pruned containers, its failure logged).
    `COLLECTION_NOT_EMPTY`'s `unfinished_commits` is 0 until M13.6 adds the commit count.
  - `src/huron/core/lake/errors.py`: `IdentityUnresolved` (422 `IDENTITY_UNRESOLVED`, context `{problems}`;
    DT-8's code, first raised by `activate`'s `place`) and its `ERROR_CODES` entry; `design/api.html` §7
    gains DT-18's `IDENTITY_UNRESOLVED` row.
  - `src/huron/core/lake/errors.py`: `CollectionNotEmpty` (409 `COLLECTION_NOT_EMPTY`, context `{file_count,
    unfinished_commits, unrecorded}`) and its `ERROR_CODES` entry; `design/api.html` §7 gains DT-18's
    `COLLECTION_NOT_EMPTY` row.
  - `tests/unit/test_lake_collections.py`: T3, T4, T11 with exact `activate`/`delete` entries and versions;
    metadata that `place` cannot resolve (a missing namespace field) is 422 `IDENTITY_UNRESOLVED` with its
    problems and leaves the draft unchanged;
    the recorded call order (provision before the transaction, `sync` after); a provision failure leaves the
    row `draft` and answers 503 with `Retry-After: 30`; a `sync` failure still returns the active view; a
    retried activation is 409 `COLLECTION_STATE` with `state: active`; a taken identifier is 409
    `COLLECTION_EXISTS`; a config publish between the read and the transaction re-runs `require_valid`; a
    settled delete with an unrecorded entry (a user file, a dot-file, a symlink) refuses before any change and
    lists at most 20; a removable-only directory is removed with its pruned containers; a post-commit removal
    failure leaves the answer unchanged.
  - `tests/lake_store_contract.py` (collections area, Postgres-only where real concurrency is needed): two
    concurrent activations of one identifier give one success, one `COLLECTION_EXISTS` and one directory; an
    activation racing a delete that prunes the same namespace, in both orders, never fails with 23503 and
    leaves I-12.10 true; an activation racing a config publish satisfies I-9 in both commit orders.
- Design: "DT-12 activation sequence and failure table"; "DT-12 deletion sequence and failure table"; "DT-12
  invariants the aggregate enforces"; "DT-12 tests this design requires"; "DT-11 handoffs" (DT-12 row); "DT-9
  interfaces and contracts" (Serialization); "DT-7 the vocabulary: action × object_type and `detail`".
- Verification:
  - The plan-wide gate and `make docs`; `uv run pytest tests/unit/test_lake_collections.py
    tests/unit/test_error_contract.py` passes; `collections.py` at 100 %.
  - `tests/contract/test_lake_audit_store.py` (M8.5's): `test_audit_is_written_with_the_change` gains its
    collection form (an activation's entry commits with the row, and a raising block leaves neither), and
    `test_collection_log_paging` its clause that the entries still page after the collection row is deleted.
  - Run in the background and poll: `uv run pytest -m contract tests/contract/test_lake_store.py
    tests/contract/test_lake_audit_store.py`. The race
    scenarios are treated as named races: an intermittent failure stops the milestone.
  - "Two `sync`s racing two publishes end with the newer document" needs DT-15's publish and lands in M16.
- Dependencies: M11.4, M11.9.
- Decisions: OQ-9.1 (settled, owner decision 12)
- Decisions: OQ-12.1 (settled, owner decision 12)
- Status: pending

### M11.11 The volume in the API, readiness and the development stand-in

- Intent: open `PosixVolume` in the lifespan with the configured permissions adapter and `Directories`, report
  the volume in `/readyz`, refuse the relaxed policies outside development, publish the volume coordinates on
  `CatalogBody`, and give the development stack its plain-directory volume (DT-23's make targets, compose bind,
  `dev.env` and `check-stack.sh`). From here every composed test app starts with a `tmp_path` volume.
- Delete: none.
- Create: none.
- Modify:
  - `src/huron/applications/api/settings.py`: `VolumeSettings` (prefix, `id`, `mount_policy`, `permissions`,
    `max_concurrent_hashes`, `access_reset_interval_seconds`) as the required `ApiSettings.volume`; the
    after-validator's refusal 3 (`marker_only` or `recording` outside `env=development`).
  - `src/huron/applications/api/app.py`: the lifespan opens `PosixVolume` with
    `VolumeRules(VolumeMarker.parse, mount_entry)` (a failed probe refuses startup), picks
    `Nfs4AclPermissions` or `RecordingPermissions` by setting, builds `Directories(volume, permissions,
    stores.lake)`, closes the volume on shutdown; `/readyz` gains `("volume", …)` after the generation-store
    check, mapped from `volume.check()`, under the existing 2 s bound.
  - `src/huron/applications/api/runtime.py`: `ApiRuntime.volume`, `ApiRuntime.directories`.
  - `src/huron/applications/api/routes/lake/schema/catalogs.py`: `VolumeRef`; `CatalogBody.volume`;
    `src/huron/applications/api/routes/lake/endpoints/catalogs.py` rows 4, 5, 8 and 9 fill it from the runtime.
  - `tests/unit/support.py`: the default lake test settings gain a `VolumeSettings` whose prefix is a
    `tmp_path` directory initialised by `tests.fakes.ontap_volume.init_volume` (`marker_only`, `recording`);
    every test that builds `ApiSettings`, `ApiRuntime` or `ApiStores` directly (including
    `tests/integration/conftest.py`) follows.
  - `tests/unit/test_api_settings.py`: `marker_only` and `recording` refused outside development, with the
    passing development case; `volume.id` required. `tests/unit/test_api_app.py`: `/readyz` reports `volume`
    with the reason once the prefix directory is replaced (`remounted`); startup refused on a bad marker;
    `CatalogBody.volume` equals the settings. `tests/unit/test_execution_model.py`: the volume probe runs off
    the event-loop thread.
  - `Makefile`: `RAW_LAKE_PREFIX`, `NAME ?=`, `AT ?= .`; targets `raw-lake-init` and `raw-lake-snapshot` with
    DT-23's help lines; `up`, `api` and `stack` gain the `raw-lake-init` prerequisite; `api`'s recipe sets
    `HURON_VOLUME__PREFIX=$(RAW_LAKE_PREFIX)`; `stack`'s probe list gains `volume`; `.PHONY` gains both
    targets. (`test-acceptance`, `test-stack`, `test-nfs` are M15's.)
  - `docker-compose.yml`: the `api` service mounts `./.local/raw-lake/projects:/projects`.
  - `dev.env`: `HURON_VOLUME__PREFIX=/projects`, `HURON_VOLUME__ID=0b8f3c1e-6a52-4c39-9f43-2f7d5e0a9c11`,
    `HURON_VOLUME__MOUNT_POLICY=marker_only`, `HURON_VOLUME__PERMISSIONS=recording`.
  - `scripts/check-stack.sh`: the `volume` probe and hint; the `api` readiness message "ready (database,
    signing keys and volume)"; the default list, usage line and `case` gain `volume`.
  - `design/api.html` §7: the `DEPENDENCY_UNAVAILABLE` row names `volume` among its dependencies.
  - `design/layer-raw.html`: §1 Why NFS (`why-nfs`) and §2 Volume layout (`layout`).
  - `docs/raw-lake/operations.md` §3 "Deploying the API": the volume mount line (M9.2 wrote the rest of §3).
  - `docs/getting-started/local-development.md`: "Raw lake development" gains `make raw-lake-init`,
    `make raw-lake-snapshot NAME=… [AT=…]` and deleting the development volume; "Running the API" gains the
    volume id and prefix rows; the stack's service list names the `volume` probe.
- Design: "DT-11 interfaces and contracts" (`applications/api`: settings, wiring, readiness and the reset
  worker: the settings, lifespan and `/readyz` bullets); "DT-11 decisions" (Marker, Mount policy, Startup);
  "DT-18 settings: the merged `ApiSettings` diff" (the `volume` row, refusal 3); "DT-18 decisions" (Volume
  coordinates); "DT-18 request and response models" (`VolumeRef`, `CatalogBody`); "DT-23 decisions" (Fixed
  development volume id, uid rule, Host-mode API); "DT-23 make targets, compose, `dev.env` and
  `check-stack.sh`"; "DT-26 design record pages: the Raw-facing six" (layer-raw §1, §2); "DT-26 developer
  docs, README and history" (`local-development.md` rows).
- Verification:
  - The plan-wide gate and `make docs`.
  - `uv run pytest tests/unit/test_api_settings.py tests/unit/test_api_app.py tests/unit/test_execution_model.py`
    passes.
  - `docker compose config --quiet` exits 0; `make -n raw-lake-init raw-lake-snapshot NAME=n1 api up stack`
    prints the init recipe, the snapshot recipe, the prefix override and the `volume` probe; `make -n
    raw-lake-snapshot` fails with the `NAME` error; `bash -n scripts/check-stack.sh` exits 0. No target that
    starts, stops or populates the owner's stack is run.
  - The composition-root rule: every test that builds `ApiSettings`, `ApiRuntime` or `ApiStores` directly
    passes unchanged in intent.
- Dependencies: M11.4; M9 (the lake lifespan, `CatalogBody`, the default lake test settings).
- Decisions: OQ-21.1 (settled, owner decision 12)
- Status: pending

### M11.12 The access-reset worker and the permissions pages

- Intent: drain `lake.access_resets` in every API process so a mapping change reaches the volume within one
  interval (catalog directory first, then every collection and its content), and land the design-record and
  operator lines that describe directory permissions.
- Delete: none.
- Create:
  - `src/huron/applications/api/access_resets.py`: `AccessResetWorker` (one task per process; owner hostname
    plus pid; lease 5 min; every `access_reset_interval_seconds`: `claim`, the catalog's `CatalogRef`,
    `active_paths`, `Directories.reset` with `heartbeat` extending the lease, `complete`; a failure is logged,
    leaves the row and lets the lease lapse; cancelled between collections on shutdown; one structured log
    record per finished reset carrying the `ResetReport`). No audit entry: DT-7 "What is not audited" lists ACL
    resets, DT-16 restates it and DT-17's revisions seed no `access_reset` pair, which supersedes DT-11's audit
    bullet (reported).
  - `tests/unit/test_api_access_resets.py`: one pass over `InMemoryLakeStore`, `PosixVolume` on `tmp_path` and
    `RecordingPermissions` with `FakeClock`: a mapping change is claimed, applied catalog directory first, then
    each collection and its content, and completed; a re-request during the pass leaves the row; a volume
    `DependencyUnavailable` leaves the row until the lease lapses; a lost lease stops the pass; shutdown cancels
    between collections; through the app, a catalog role-mapping `PUT` (row 12) followed by one interval leaves
    the recording fake with the reset applied.
- Modify:
  - `src/huron/applications/api/app.py`: the lifespan starts the worker after the pool and the volume and
    stops it on shutdown; `tests/unit/support.py` keeps the composed test apps' interval short.
  - `design/layer-raw.html`: §7 Directory permissions (`permissions`).
  - `design/rbac.html`: §7's Raw half; the `:266` link becomes `layer-raw.html#permissions`.
  - `docs/raw-lake/operations.md`: §2 Preparing the volume.
- Design: "DT-11 interfaces and contracts" (`applications/api`: the `AccessResetWorker` bullet); "DT-11
  decisions" (G-16, Huron's own principal); "DT-11 data flow"; "DT-7 decisions" (What is not audited); "DT-17
  DDL: `0016_lake_collections`"; "DT-26 design record pages: the Raw-facing six" (layer-raw §7, `rbac.html`
  §7); "DT-26 the two new pages" (`operations.md` §2); "DT-26 broken links and their fixes"
  (`rbac.html:266`).
- Verification:
  - The plan-wide gate and `make docs`.
  - `uv run pytest tests/unit/test_api_access_resets.py tests/unit/test_api_app.py` passes;
    `access_resets.py` at 100 %.
  - `rg -n 'layer-raw.html#generations' design` prints nothing.
- Dependencies: M11.8, M11.11; M8 (`docs/raw-lake/operations.md`).
- Decisions: OQ-11.1 (settled, owner decision 12)
- Decisions: OQ-11.3 (settled, owner decision 12)
- Decisions: OQ-11.4 (settled, owner decision 12)
- Status: pending

### M11.13 Lake routes: namespaces and collection reads (rows 23, 24, 28, 30)

- Intent: serve the namespace subtree, the collection search with its `label` grammar and draft rule, a
  collection, and its pinned composed schema, in DT-18's shapes.
- Delete: none.
- Create:
  - `src/huron/applications/api/routes/lake/endpoints/namespaces.py` (row 23) and
    `src/huron/applications/api/routes/lake/endpoints/collections.py` (rows 24, 28 and 30; the ETag on 28;
    the digest ETag and the `If-None-Match` 304 on 30, as row 7).
  - `src/huron/applications/api/routes/lake/schema/namespaces.py` (`NamespaceBody`) and
    `src/huron/applications/api/routes/lake/schema/collections.py` (`CollectionQuery` with validators for the
    `label` grammar, a `catalog`/`under` disagreement and `identifier` with `state=draft`, each 422
    `REQUEST_INVALID`; `CollectionBody` with `path`, `null` for a draft).
  - `tests/unit/test_lake_collections_search.py`: DT-18's grammar cases (`a=b`; `a=b=c`; the same key twice,
    9 labels and a bad key each 422), `under` with a disagreeing `catalog` (422), `identifier` with
    `state=draft` (422), and results matching `@>` semantics on the fake.
- Modify:
  - `src/huron/applications/api/routes/lake/__init__.py` includes both routers;
    `src/huron/applications/api/routes/lake/dependencies.py` gains `collections()` and `CollectionsDep`;
    `src/huron/applications/api/routes/pagination.py` gains the `namespaces` and `collections` listings (settled and
    draft keys).
  - `tests/unit/test_lake_routes.py`: the derived anonymous-401 sweep grows by exactly four; the role-ladder
    table gains rows 23, 24, 28, 30; `test_draft_visibility`; row 28's `ETag` equals `version`.
  - `tests/unit/test_api_router_composition.py` (tags `namespaces` and `collections`; their first segments);
    `tests/unit/test_execution_model.py` (the four operations); `tests/unit/test_api_pagination.py` (a cursor
    from another listing is 400 `INVALID_CURSOR`; 50 items by default; `limit=201` is 422; a 3-item set at
    `limit=1` visits each once and ends with `next_cursor: null`).
  - `design/api.html` §3: rows 23, 24, 28 and 30 of DT-18's table.
- Design: "DT-18 route table" (rows 23, 24, 28, 30 and the reading notes); "DT-18 request and response
  models"; "DT-18 paging keys and the `label` filter"; "DT-18 interfaces and contracts" (The lake router and
  its credential dependency; Lake service dependencies); "DT-18 tests this design requires"; "DT-12 interfaces
  and contracts" (Routes); "DT-9 interfaces and contracts" (Errors, routes and the CLI's use of
  `huron.schema`); "DT-26 design record pages: the Raw-facing six" (`api.html` §3).
- Verification:
  - The plan-wide gate and `make docs`.
  - `uv run pytest tests/unit/test_lake_routes.py tests/unit/test_lake_collections_search.py
    tests/unit/test_api_router_composition.py tests/unit/test_execution_model.py tests/unit/test_api_pagination.py
    tests/unit/test_error_contract.py` passes; every new route module at 100 %.
- Dependencies: M11.9, M11.11; M9.
- Decisions: OQ-18.2 (settled, owner decision 12)
- Decisions: OQ-18.3 (settled, owner decision 12)
- Status: pending

### M11.14 Lake routes: drafts, activation and deletion (rows 25, 26, 27, 29)

- Intent: serve draft creation, merge-patch saves, activation and deletion in DT-18's shapes, with the
  merge-patch media-type rule and its 415, and land the lifecycle section of the design record.
- Delete: none.
- Create: `tests/unit/test_lake_openapi.py`: row 26's `requestBody` declares only
  `application/merge-patch+json` (M13.9 adds row 32's case, M16 row 36's).
- Modify:
  - `src/huron/applications/api/routes/lake/endpoints/collections.py`: `POST /collections` (IK; 201,
    `Location`, `ETag: "1"`), `PATCH /collections/{id}/draft` (IM; `MergePatch`),
    `POST /collections/{id}/activate` (IM; 503 with `Retry-After: 30`), `DELETE /collections/{id}?reason=`
    (IM; 204); `src/huron/applications/api/routes/lake/schema/collections.py` gains `DraftCreate`.
  - `src/huron/applications/api/routes/preconditions.py`: `merge_patch_body` and `MergePatch` (media type
    compared without parameters; 415 before the body is read; a parse failure is 422).
  - `src/huron/applications/api/errors.py`: `UnsupportedMediaType` (415 `UNSUPPORTED_MEDIA_TYPE`) and its
    entry in the module's transport `ERROR_CODES`; `design/api.html` §7 gains its DT-18 row.
  - `tests/unit/test_lake_routes.py`: the sweep grows by exactly four; ladder rows 25, 26, 27, 29;
    `test_etag_on_reads_and_if_match_on_writes` for rows 25–29; `test_idempotent_replay` for row 25;
    `test_merge_patch_media_type`; `test_store_outage_is_503` gains row 25.
  - `tests/unit/test_api_preconditions.py` (`merge_patch_body` cases); `tests/unit/test_execution_model.py`
    (the four operations); `tests/unit/test_api_router_composition.py` (every new route carries exactly
    `current_actor`).
  - `design/api.html` §3: rows 25, 26, 27 and 29.
  - `design/layer-raw.html`: §4 Collection lifecycle (`lifecycle`).
- Design: "DT-18 route table" (rows 25, 26, 27, 29; the row-26 note); "DT-18 decisions" (`PATCH …/draft`
  media type); "DT-18 interfaces and contracts" (Preconditions and media types; Composition and readiness);
  "DT-18 error-code table rows"; "DT-18 tests this design requires"; "DT-12 interfaces and contracts"
  (Routes); "DT-26 design record pages: the Raw-facing six" (layer-raw §4).
- Verification:
  - The plan-wide gate and `make docs`; `uv run pytest tests/unit/test_error_contract.py` passes with the
    four M11 codes and `UNSUPPORTED_MEDIA_TYPE` each declared once, raised and documented.
  - `uv run pytest tests/unit/test_lake_routes.py tests/unit/test_lake_openapi.py
    tests/unit/test_api_preconditions.py tests/unit/test_execution_model.py` passes.
  - Milestone close: DT-11's closing check prints nothing; `rg -n 'rename_collection' src tests` prints
    nothing; `rg -n 'place_moved' src` prints nothing (scoped to this commit: M16.4 adds
    `Directories.place_moved`, so M19.4 re-runs only the `rename_collection` half); `uv run lint-imports`
    keeps all 20 contracts; the contract and integration suites pass.
- Dependencies: M11.10, M11.13.
- Decisions: OQ-12.1 (settled, owner decision 12)
- Status: pending

## Milestone 12 — CLI collection creation and browsing

Spec build step 3 on the client, against M11's routes 23–30. DT-20's walkthrough drives
`huron create collection` from a server draft to activation, saving every accepted answer before the next
question. It covers the plan, the per-answer validation, the draft and file sinks, prefill, the state
machine and `--resume`. `--no-input --set` scripts the walkthrough, and `meta init` reuses it for a local file.
`delete collection`, `get namespaces`, `get collections [--state draft]` and `describe collection`
complete browsing. The working copy does not exist yet (M14). A created collection becomes the current
collection, and from M14.2 on, creation also checks it out. `describe collection`'s last-change line reads
row 36, which M16 serves, so it lands in M18.3. CLI guide §3 and §4 are completed here, and RL step 3 flips.

### M12.1 Walkthrough: plan, answer rules, draft and file sinks, and the state machine

- Intent: DT-20's question loop. Fields are asked in `fields()` order with select lists narrowed by earlier
  answers. An answer is accepted only when partial validation and `place` raise nothing at its field, and
  an accepted answer is persisted through an `AnswerSink` before the next question (P1). A resume asks only
  the fields still missing or failing. Identity hints prefill `pi`, `contact` and `organization`
  (OQ-20.3 (a)).
- Delete: none.
- Create:
  - `tests/unit/cli/test_cli_walkthrough.py`: DT-20's row, run with `ScriptedPrompter` against the real API
    (drafts are created through row 25 during setup).
    - Question order: namespace fields in config order, then required fields, then optional ones. Select
      lists are narrowed by the parent answer.
    - A refused answer is re-asked with its problems shown and is never sent: a request-recording
      `event_hooks` entry on the API `TestClient` sees no PATCH.
    - One PATCH per accepted answer, with `If-Match` incrementing. Every row-26 request carries
      `Content-Type: application/merge-patch+json` (DT-18: 415 never arises).
    - Prefill shows as the `default` for `pi`, `contact` and `organization` only when the field is absent,
      and only in `create` and `init` modes.
    - `Aborted` after three answers; a new `Walkthrough` over the re-read draft then asks only the rest.
    - A teammate's save of another field between two answers (412) is merged, and a second 412 exits 6.
    - `revisit(fields)` asks only the fields it names. `WalkPlan.build("update")` keeps non-identity fields
      only.
    - `AnswerKind.of` resolves through `$ref` and `allOf`; `parse_answer` per kind, and malformed JSON
      exits 2.
    - `FileSink`'s atomic rewrite: mode 0644, and the old file stays intact when the write is interrupted
      before `os.replace`.
- Modify:
  - `src/huron/applications/cli/walkthrough.py` gains:
    - `AnswerKind.of` and `parse_answer`.
    - `WalkPlan.build` for the `create`, `init` and `update` modes; it never touches the network.
    - `AnswerSink`.
    - `DraftSink`: a row-26 merge patch with `If-Match` that keeps the reply's version. A 412 triggers one
      re-read (row 28) and one resend; a second 412 exits 6. After a transport error it re-reads: an equal
      member counts as saved, otherwise it resends once. A 409 `COLLECTION_STATE` ends the walkthrough with
      "already activated".
    - `FileSink`, `Summary` and `PREFILL`.
    - `Walkthrough` with `run` and `revisit`, through the states Next, Ask, Check, Save, Summary, Confirm
      and Paused. The Summary preview is `Identifier(...).mount_path(volume.prefix)`, or
      `<generated at activation>`.
  - `src/huron/applications/cli/state.py`: `VolumeCoordinates` and `CurrentCatalog.volume` (no reader of the
    earlier shape is kept: `version: 1` stays refuse-only, owner decision 11, B-37); `Config.local_prefix()`
    returns `os.path.realpath(mount_prefix or catalog.volume.prefix)` (as DT-19's `PurePosixPath`), and
    `None` only when neither is set; `src/huron/applications/cli/commands/context.py`:
    `catalog use` also stores `CatalogBody.volume` (M11.11's field) and `config view` shows it;
    `tests/unit/cli/test_cli_state.py` and `test_cli_context.py` cover both, and `test_cli_state.py` gains a
    `local_prefix` case covering the fallback to `catalog.volume.prefix` and `mount_prefix` taking
    precedence over it.
    - Activation and the Finish answers belong to `create collection` (M12.3), which calls `revisit` after
      a refused activation. `CheckoutSink` and update mode in use are M18.1's.
  - `src/huron/applications/cli/oidc.py`: `CompanyTokens.identity_hints()` also returns `organization` when
    the ID token carries it as a string (OQ-20.3 (a)). `test_cli_oidc.py` gains the case with and without
    the claim.
- Design: DT-20 decisions ("Where a walkthrough persists", "Resume without a cursor", "Per-answer
  validation", "Answer parsing", "L-44 (b), G-18"); DT-20 interfaces and contracts → "`walkthrough.py`:
  plan, prompts, sinks and the state machine"; DT-20 the walkthrough as a state machine; DT-20 handoffs
  (DT-19 and DT-22 rows: `organization`); DT-9 `huron.schema.metadata` (`fields()` order,
  `problems(partial=)`); DT-8 `huron.schema.catalog_config` (`choices`, `place`); DT-18 route table
  (rows 26, 28) and handoffs (DT-21 row: 415); DT-19 interfaces and contracts → `state.py`
  (`local_prefix`).
- Verification:
  - The plan-wide gate. `uv run pytest tests/unit/cli/test_cli_walkthrough.py tests/unit/cli/test_cli_oidc.py -q`
    passes.
  - `rg -ln "questionary" src/huron/applications/cli` still prints only `walkthrough.py`, and
    `rg -n "questionary\." src/huron/applications/cli/walkthrough.py` shows uses only inside
    `QuestionaryPrompter`.
  - Every modified file is at 100 % line coverage.
- Dependencies: M10.7; M11.
- Decisions: OQ-20.3 (settled, owner decision 12)
- Status: pending

### M12.2 Collection resolution, `get namespaces`, `get collections` and `describe collection`

- Intent: DT-19's browsing over the collection routes, together with the one resolution rule that every
  server-addressing verb uses for `<path>` and `-c`. The draft list is `get collections --state draft`
  (OQ-18.2 (a)), never a second verb (DT-20 decisions).
- Delete: none.
- Create: none.
- Modify:
  - `src/huron/applications/cli/resolve.py`: `resolve_collection`.
    - With no text it uses `config.collection`. A canonical lowercase hyphenated UUID reads row 28. Any
      other text goes through `resolve_identifier`.
    - An identifier of fewer than three segments raises `UsageError`. Otherwise it reads row 24 with
      `identifier=`; no item raises `ApiError` `NOT_FOUND` (exit 4).
  - `src/huron/applications/cli/commands/browse.py`:
    - `get namespaces [PATH] [-R]` (row 23, `under=<canonical>`, paged): without `-R` it keeps only the
      children, filtering on `Identifier.from_canonical`; wide adds `DEPTH`; no path and no current
      catalog exits 2.
    - `get collections [PATH] [-l k=v]… [--state]` (row 24, paged): `StateFilter` takes row 24's
      `settled`, `active`, `incomplete` and `draft`; labels pass through as `label=`; with no path and no
      current catalog it lists across every readable catalog.
    - `describe collection [PATH|ID]` (row 24 with `identifier=`, or row 28): the DT-19 view without its
      last-change line. JSON and YAML print `{"collection": CollectionBody}`. The `last_change` member and
      line read row 36 (M16) and are added in M18.3.
  - `src/huron/applications/cli/commands/__init__.py`: registers the `describe` group (`get namespaces`
    and `get collections` join M10.5's `get` group).
  - `tests/unit/cli/test_cli_resolve.py`: the `resolve_collection` cases (current collection, UUID,
    identifier hit, identifier miss exiting 4, too-short identifier exiting 2).
  - `tests/unit/cli/test_cli_browse.py`: catalogs, namespaces and collections seeded through the API, with
    a Reader and a Developer.
    - Every new verb × `table`/`wide`/`json`/`yaml`.
    - Path defaults with and without a current catalog; `--recursive` versus children only.
    - A label passes through, and a malformed label is the server's 422 (exit 2).
    - `test_drafts_are_listed_only_under_state_draft`.
    - `describe` of a draft as Reader exits 5.
  - `get catalogs` wide output gains `VOLUME` and `PREFIX` from `CatalogBody.volume`; its golden text in
    `tests/unit/cli/test_cli_browse.py` follows.
  - `docs/raw-lake/cli.md` §3 is completed: `huron get collections [--state draft] [--label key=value]` and
    `describe`, which replace DT-10's `catalog list` and DT-18's `ls`/`draft list`.
- Design: DT-19 interfaces and contracts → "`resolve.py`" (`resolve_collection`); DT-19 command signatures
  and exit codes (`get namespaces`, `get collections`, `describe collection`) and its verb rules; DT-18
  route table (rows 23, 24, 28), "paging keys and the `label` filter", handoffs (DT-20 row); DT-20
  decisions ("Administration verbs": `ls` and `draft list` are `get collections`); DT-20 handoffs (DT-26
  row); DT-26 the two new pages (§3).
- Verification:
  - The plan-wide gate. `uv run pytest tests/unit/cli -q` passes, including the named tests.
  - `uv run huron --help` lists `describe` and no `ls` and no `draft` verb.
  - `make docs` passes. Every modified file is at 100 % line coverage.
- Dependencies: M10.5; M11.
- Decisions: OQ-18.2 (settled, owner decision 12)
- Status: pending

### M12.3 `create collection`, `meta init`, `meta validate -c` and `delete collection`

- Intent: the scientist's creation path, interactive and scripted. It runs the draft create, the
  walkthrough and activation with DT-12's answers, including a lost response, then sets the current
  collection. `meta init` writes a validated metadata file. `meta validate` gains the collection's pinned
  validator, and `delete collection` deletes with confirmation. This task finishes RL step 3.
- Delete: none.
- Create:
  - `src/huron/applications/cli/commands/collections.py`:
    - `create collection` with `-f`, `--catalog`, `--resume`, `--set`, `--no-input` and `-o`.
      - Usage errors (exit 2): `--resume` together with `--catalog` or `-f`; no catalog; no TTY without
        `--no-input`, raised through the prompter factory.
      - Reads: rows 5 and 6 (at the draft's `config_version`); row 25 with a fresh `Idempotency-Key`,
        printing "draft <id> created" at once, or row 28 under `--resume`; row 30 through the schema
        cache.
      - Activation: the walkthrough, then row 27 with `If-Match: DraftSink.version`. 200 → Done.
        409 `COLLECTION_STATE` (`state: active`) on a retry → Done. 409 `COLLECTION_EXISTS` → revisit the
        name field, or the last namespace field when names are generated. 422 `METADATA_INVALID` or
        `IDENTITY_UNRESOLVED` → revisit the fields that `context.problems` names. 412 → re-read row 28 and
        return to Summary. 503 `volume` → Paused, exit 7. A transport error → re-read row 28: `active` is
        Done, and `draft` resends once.
      - Done saves `Config.collection` through `replace(...).save` under the lock and prints the
        `describe collection` view. The pull into `collections/<uuid>/` is added in M14.2.
      - `--no-input`: `-f` and `--set` form one patch, applied in order with the later value winning. It
        becomes row 25's `metadata` for a new draft, or one row-26 merge patch under `--resume`. Summary
        runs once. With problems, missing required fields print first and the command exits 1, keeping the
        draft. Without problems it activates with no confirmation. Prefill never applies here.
      - Paused prints "draft <id> saved; resume: huron create collection --resume <id>".
    - `delete collection PATH|ID [-m] [--yes]`, a **confirm** verb.
      - Requests: R, then row 28 for the version, then row 29 with `If-Match` and `?reason=`.
      - Success unsets the current collection when it was this one. Removing the local working copy is
        added with `Checkout` (M14.2).
      - 409 `COLLECTION_NOT_EMPTY` prints `file_count`, `unfinished_commits` and every `unrecorded` path,
        exit 6 (OQ-12.1 (a)). 412 exits 6, and 503 `volume` exits 7. A lost response whose re-read answers
        404 exits 0.
  - `tests/unit/cli/test_cli_collections.py`, the `create` and `delete` rows of DT-20's table:
    - Create end to end to an active collection: its directory exists on the `tmp_path` volume, the
      current collection is set, and the describe view is printed.
    - `test_no_input_lists_missing_required_fields_and_keeps_the_draft`, then `--resume --no-input --set`
      completes it. Also the `-f` file path, and prefill never applying under `--no-input`.
    - `test_retried_activation_answered_active_is_success`: a response hook raises a transport error after
      the app handled row 27.
    - `COLLECTION_EXISTS` revisits the name field. 503 `volume` (the marker removed) exits 7 and keeps the
      draft.
    - Delete: without a TTY it exits 2; `--yes` deletes; `COLLECTION_NOT_EMPTY` lists a file written
      straight into the collection directory; a lost response re-read as 404 exits 0.
- Modify:
  - `src/huron/applications/cli/commands/meta.py`:
    - `meta init` with `--catalog`, `-f` (default `metadata.json`), `--force`, `--set` and `--no-input`
      (rows 5, 6, 7; `FileSink`). An existing file is resumed unless `--force` starts empty; an existing
      non-object exits 1. Paused prints "resume: huron meta init --catalog <c> -f <file>".
    - `meta validate` gains `-c` and the current collection (row 30 through the schema cache).
      `--catalog` with `-c` exits 2, and so does giving no target.
  - `src/huron/applications/cli/commands/__init__.py`: `SetOption` (split at the first `=`),
    `NoInputOption` and `CollectionOption`; registers `create` and `delete`.
  - `tests/unit/cli/test_cli_meta.py`: `meta init` resumed from an existing file and with `--force`, and
    problems under `--no-input` (file written, exit 1); `meta validate -c` through row 30, and `--catalog`
    with `-c` exiting 2.
  - `docs/raw-lake/cli.md` §4 is completed: the walkthrough, `--resume` after an interrupted run, scripted
    creation with `--no-input --set key=value`, and `meta init`. §7 gets its `delete collection` line; the
    rest of §7 lands with the verbs that make it true (M14.2, M18).
  - `design/roadmap.html`: the RL step 3 tag becomes `done`.
- Design: DT-20 decisions ("`create collection` ends checked out", read together with M14.2); DT-20
  command signatures, routes and exit codes (`create collection`, `delete collection`, `meta init`,
  `meta validate`); DT-20 the walkthrough as a state machine (Finish, Paused, the activation answers,
  `--no-input`); DT-20 data flow: create, stage, publish (steps up to activation); DT-12 (T1–T4, T11 and
  the lost-response row, as DT-20 cites them); DT-18 route table (rows 25–30); DT-26 the two new pages
  (§4, §7 `delete collection`); DT-26 roadmap rows (RL step 3).
- Verification:
  - The plan-wide gate. `uv run pytest tests/unit/cli -q` passes, including the named tests.
  - `make docs` and `git diff --check` pass. Every created or modified file is at 100 % line coverage.
  - RL step 3's gate clause "on loopback NFS in the `nfs` job" is M15's job. This task flips the tag on
    the unit-tier proof (activation creates the directory and its ACL through the recording permissions,
    M11) and names the `nfs` receipt as M19's check.
- Dependencies: M12.1, M12.2.
- Decisions: OQ-20.3 (settled, owner decision 12)
- Decisions: OQ-12.1 (settled, owner decision 12)
- Status: pending

## Milestone 13 — Files and asynchronous commit

Spec build step 4 on the server. The one `rel_path` rule (with `rel_path_key` and `partial_name`) lands in
`huron.schema.naming` with its Hypothesis properties, and the commit body's wire contract in
`commit-request-v1.json`; `lake/files.py` holds the commit request, the pure decision table and the
verification mapping with their six problem codes; `Volume.verify` gains file stamps (ctime included) and a hash
slot that outlives a cancelled caller, and `Volume.stamps` re-checks without reading; revision
`0017_lake_commits` lands with the file, commit and checkpoint halves and their contract tests (C15, C16, C17,
`test_rel_path_check`); `Commits` accepts a commit synchronously (202), re-hashes it in a bounded per-replica
`CommitWorker`, applies rows, the version bump, `file_count` and the audit entries in one transaction, and
recovers from crashes, as the `FaultingLakeStore` crash matrix proves; the worker's housekeeping also prunes
expired idempotency claims; and the API serves DT-18 rows 31–33. Concurrent `mv` (crash-matrix case C13) waits
for DT-15 in M16; the large-file push and the real-NFS cases wait for M15.

### M13.1 The `rel_path` rule and the commit request document

- Intent: give server and CLI one `rel_path` rule, one case-fold key and one partial-file spelling, proven by
  Hypothesis properties, and publish the commit body's JSON Schema that the CLI builds against and the route
  validates with. The old manifest rules are rewritten from `git show fa51f46:src/huron/core/raw/manifest.py`
  (OQ-2.1 (a)); nothing imports or aliases an old name.
- Delete: none.
- Create:
  - `src/huron/schema/documents/commit-request-v1.json`: DT-13's outline verbatim.
  - `tests/rel_path_strategies.py` (support module, no `test_` prefix): the tricky alphabet, the valid-path
    generator, the per-rule mutations and R13-1's fixed accept and refuse lists, shared with M13.4's
    `test_rel_path_check`.
  - `tests/unit/test_lake_rel_path_properties.py`: DT-13's property table under `@settings(max_examples=300,
    deadline=None, derandomize=True)` plus the fixed cases (`sub/metadata.json`, `metadata.json.d/x`,
    `x.part.bin` accepted; `metadata.jſon` refused by the function).
  - `tests/unit/test_schema_commit_request.py`: R13-5 (the document passes `check_schema`; the amended spec
    example, a removes-only body and host `Karls-MacBook-Pro.local` are valid; `base_etag`, both lists empty,
    an upper-case hash and a negative size are invalid).
- Modify: `src/huron/schema/naming.py`: `REL_PATH_MAX_BYTES`, `REL_PATH_SEGMENT_MAX_BYTES`, `METADATA_FILE`,
  `check_rel_path` (rule ids `rel_path_nfc`, `rel_path_length`, `rel_path_segment`, `rel_path_control`,
  `rel_path_separator`, `reserved`, in DT-13's order), `rel_path_key`, `partial_name`.
- Design: "DT-13 decisions"; "DT-13 the `rel_path` rule"; "DT-13 the commit request contract"; "DT-13 tests
  this design requires"; "DT-23 placement of the handed-off tests" (DT-13 row); "DT-8 interfaces and
  contracts" (`huron.schema.naming`: `is_reserved`, `NamingError`).
- Verification:
  - The plan-wide gate; `uv run pytest tests/unit/test_lake_rel_path_properties.py
    tests/unit/test_schema_commit_request.py tests/unit/test_schema_loading.py` passes deterministically;
    `naming.py` at 100 %.
  - `rg -n "PATH_NOT_NFC|PATH_TOO_LONG|PATH_TRAVERSAL|PATH_CONTROL_CHARS|PATH_SEPARATOR|PATH_OUTSIDE_PAYLOAD|validate_manifest" src`
    prints nothing; `uv run lint-imports` keeps all 20 contracts (contract 18: the CLI reaches the rule
    through `huron.schema` only).
- Dependencies: M6.
- Decisions: OQ-2.1 (settled, owner decision 12)
- Decisions: OQ-13.1 (settled, owner decision 12)
- Decisions: OQ-13.2 (settled, owner decision 12)
- Status: pending

### M13.2 Commit decisions: the request, the plan and the verification outcome

- Intent: build the pure rules of a commit (request parsing with its limits, the per-entry decision table, the
  mapping from a `FileCheck` to `FILE_MISMATCH`, and the audit events of a plan) and declare the six codes they
  raise with their `design/api.html` §7 rows, before any store or worker exists.
- Delete: none.
- Create:
  - `src/huron/core/lake/files.py`: `FileRecord` (`view`), `FileView`, `FileAdd`, `FileRemove`, `CommitLimits`,
    `CommitRequest` (`parse`, `keys`, `to_document`), `Added`, `Overwritten`, `Removed`, `FileChange`,
    `CommitPlan` (`file_count_delta`, `to_verify`, `audit_events`), `plan_commit`, `require_verified`.
  - `tests/unit/test_lake_files.py`: `CommitRequest.parse` rows 5–10 one case each, each asserting the
    table's `context` exactly (rows 7–8: `PATH_RULE_VIOLATION` with `{"rule": <rule id>, "value": rel_path}`
    through the inherited `DomainError.__init__`, M1.4 having deleted the code-override constructor per "DT-8
    deletions"), `to_document` equal for two entry orders, a blank `reason` becomes `None`; `plan_commit`
    rows 11–20 one case each over a dict of `FileRecord`s, plus one precedence case per adjacent stage pair
    (draft with a stale version → `COLLECTION_STATE`; a stale version with a `PATH_EXISTS` entry → 412; two
    failing entries → the first in byte order); `require_verified` once per `FileOutcome` plus `hash_mismatch`; `CommitPlan.audit_events`
    field values for each change kind against DT-7's `FileAdded`, `FileOverwritten`, `FileRemoved`.
- Modify:
  - `src/huron/core/lake/errors.py`: `PathExists`, `ChangedSinceRead` (DT-1's classes, first raised here),
    `PathCollision`, `TooManyFiles`, `FileTooLarge`, `FileMismatch`, and their `ERROR_CODES` entries.
  - `src/huron/core/lake/ports.py`: `FileStore` and `FileWriter` Protocols (DT-13's signatures, except that
    `FileStore.page` is named `file_page`: a `LakeStore` root method whose bare verb would collide carries its
    resource noun, and M17's `FindingStore` brings `finding_page`; a design override the head records).
  - `src/huron/core/lake/__init__.py`: the new public names.
  - `design/api.html` §7: DT-18's rows for `PATH_EXISTS`, `CHANGED_SINCE_READ`, `PATH_COLLISION`,
    `TOO_MANY_FILES`, `FILE_TOO_LARGE`, `FILE_MISMATCH`.
- Design: "DT-13 interfaces and contracts" (`lake/files.py`: values; the decision; `lake/errors.py`: the codes
  this task adds; `lake/ports.py`: store requirements); "DT-13 decision table"; "DT-13 concurrent pushes to one
  path (G-27)"; "DT-1 interfaces and contracts" (Error codes (L-28)); "DT-7 the vocabulary: action ×
  object_type and `detail`"; "DT-18 error-code table rows".
- Verification:
  - The plan-wide gate and `make docs`; `uv run pytest tests/unit/test_lake_files.py
    tests/unit/test_error_contract.py` passes (each of the six codes declared once, raised, documented
    with its status); `files.py` at 100 %.
- Dependencies: M13.1; M11.1, M11.9 (`CollectionRecord`, `CollectionStateConflict`), M7 (DT-7's event classes).
- Decisions: OQ-1.2 (settled, owner decision 12)
- Decisions: OQ-2.1 (settled, owner decision 12)
- Decisions: OQ-13.3 (settled, owner decision 12)
- Status: pending

### M13.3 File stamps, `Volume.stamps` and the commit values

- Intent: apply DT-14's amendments to the volume (a stamp taken after the hash, ctime in the stability test, a
  re-check that opens and `fstat`s without reading, a hash slot held until its thread returns), and define the
  commit values and the three commit store Protocols that the adapters and the workflow share.
- Delete: none.
- Create:
  - `src/huron/core/lake/commits.py` (values only; `Commits` arrives in M13.6): `CommitState` (`finished`),
    `CommitResult`, `CommitRecord`, `CommitProgress`, `CommitView`, `CommitLease`, `VerifiedFile`,
    `CommitPolicy` (`hash_timeout`, the backoff instant), `HousekeepingReport`, `LeaseLost`.
  - `tests/unit/test_lake_commit_values.py`: `hash_timeout` (floor plus size over rate); the backoff sequence
    doubling per failure and capped; `CommitState.finished`; `CommitView` and `CommitRecord` carrying
    `result`, `problem` and `finished_at` exactly as the table's CHECKs pair them.
- Modify:
  - `src/huron/core/lake/ports.py`: `FileStamp`; `FileCheck.stamp`; `Volume.stamps`; `CommitStore`,
    `CommitWriter`, `CommitQueue` Protocols. `CommitQueue` takes DT-14's signatures under the names
    `claim_commit`, `extend_commit`, `commit_checks`, `release_commit`, `fail_commit`, `expire_commits` and
    `prune_commits` (DT-14's `claim`, `extend`, `checks`, `release`, `fail`, `expire`, `prune`): `LakeStore`
    also composes `AccessResetQueue` (`claim`, `extend`, `complete`, which keep their names) and, from M17,
    `FindingStore`, so a root method whose bare verb would collide carries its resource noun (a design
    override the head records; DT-14's port block and DT-17's port table read with these names).
  - `src/huron/core/rawstore/anchored.py`: `observe` returns the stamp and compares `st_ctime_ns` too.
  - `src/huron/core/rawstore/volume.py`: `verify` fills `FileCheck.stamp`; the thread future is shielded inside
    the semaphore slot; `stamps(collection, rel_paths)` (one worker thread, `O_NOFOLLOW` open and `fstat`, one
    entry per input in order, `None` for anything not a regular file reachable without a symlink, DT-11's
    directory errors, no hash slot).
  - `tests/unit/test_rawstore_anchored.py`: R14-1's same-size rewrite with the mtime restored, and a `chmod`
    alone, are `UNSTABLE`. `tests/unit/test_rawstore_volume.py`: `stamps` cases; the stamp equals the `fstat`
    after the last read; with `max_concurrent_hashes=1` a cancelled or timed-out `verify` keeps its slot until
    its thread returns (C14 at the adapter).
- Design: "DT-14 interfaces and contracts" (`lake/commits.py`: values; `lake/ports.py`: store and volume
  requirements, including `Volume.verify` (amended) and `Volume.stamps`); "DT-14 decisions" (Hash-to-row gap,
  Bound); "DT-14 handoffs" (DT-11 row); "DT-14 target module layout".
- Verification:
  - The plan-wide gate; `uv run pytest tests/unit/test_lake_commit_values.py tests/unit/test_rawstore_anchored.py
    tests/unit/test_rawstore_volume.py` passes; `commits.py`, `anchored.py` and `volume.py` at 100 %.
- Dependencies: M13.2; M11.3.
- Decisions: OQ-14.2 (settled, owner decision 12)
- Decisions: OQ-14.3 (settled, owner decision 12)
- Status: pending

### M13.4 Revision `0017_lake_commits` and the file-row store halves

- Intent: create `lake.files`, `lake.commits` and `lake.commit_checks` exactly as DT-17 writes them, with the
  schema map and the DDL contract tests, and implement the file-row reads and the plan application on both
  adapters; the commit halves follow in M13.5.
- Delete: none.
- Create:
  - `migrations/versions/0017_lake_commits.py`: `down_revision = "0016_lake_collections"`; DT-17's DDL verbatim
    (including D-8's `commits_finished_idx`) in one `execute_sql` block; `downgrade()` calls
    `refuse_if_rows("lake.files", "lake.commits", "lake.commit_checks")` and then drops in reverse order. No
    import of `huron`.
  - `src/huron/core/metastore/lake/files.py`: `PostgresFiles` and `InMemoryFiles` halves: `file_page` (collection
    version and window in one statement, `rel_path` in byte order, `limit + 1`), `files_by_key` (`= ANY`,
    batched above 1,000 keys; the fake asserts the collection was locked), `apply_plan` (guarded deletes,
    updates and inserts, then the version-guarded collection update adding `file_count_delta`; a guard that
    matches nothing raises `LockContractBroken`).
- Modify:
  - `migrations/schema.sql`: the three tables in the `lake` section (`-- [db]` notes for the rel_path CHECK,
    the four commit CHECKs, `fillfactor = 90` and the partial indexes; `-- [spec]` for no `files.id`/`etag`);
    `-- Reflects: 0017_lake_commits`.
  - `src/huron/core/metastore/lake/store.py`, `memory.py`; `src/huron/core/lake/ports.py` (`LakeStore` gains
    `FileStore`, `LakeTransaction` gains `FileWriter`).
  - `tests/contract/test_lake_schema.py`: the round trip reaches the new head, expects exactly sixteen tables
    in schema `lake` after each upgrade (M11.5's thirteen plus the three), and the downgrade refuses with a
    row in each table; `test_rel_path_check` (every value the shared strategies accept passes
    `files_rel_path_rule`; R13-1's refusal list is refused under that constraint name); C17 (rows breaking
    `commits_lease_iff_verifying`, `commits_finished_iff_terminal`, `commits_result_iff_succeeded`,
    `commits_problem_iff_failed` are refused); `test_settled_check_and_fks` gains "deleting a collection with a
    file row fails 23503".
  - `tests/unit/test_lake_ddl_sync.py`: the `files_rel_path_rule` text equals DT-13's; 0017's tables appear in
    `schema.sql`.
  - `tests/lake_store_contract.py`: a files area (`apply_plan` row effects per change kind, `version + 1` and
    the `file_count` delta; `file_page` order for `["B", "a", "é", "z", "a/b", "a.b"]` identical in both
    adapters; a fold duplicate inserted past the lock fails on `files_rel_path_key`; Postgres-only, a named race:
    `apply_plan` on a collection that a running recompute (M11.7's `scan_settled`/`set_states`) has locked,
    in both orders, where one transaction waits on the row lock and both apply with consecutive versions).
- Design: "DT-17 DDL: `0017_lake_commits`"; "DT-17 resolved disagreements between sections" (D-8); "DT-17
  decisions" (Types, Downgrade); "DT-13 `lake.files`: logical shape (current state only; DT-17 writes the
  DDL)"; "DT-13 interfaces and contracts" (`lake/ports.py`: store requirements); "DT-14 `lake.commits` and
  `lake.commit_checks`: logical shapes (DT-17 writes the DDL)"; "DT-17 interfaces and contracts" (Correctness
  model, Encoding); "DT-17 the shared migrate helper and the tests"; "DT-17 `migrations/schema.sql` and the
  import rules".
- Verification:
  - The plan-wide gate; `uv run pytest tests/unit/test_lake_ddl_sync.py tests/unit/test_lake_memory_store.py
    tests/unit/test_check_schema_map.py` passes.
  - Run in the background and poll: `uv run pytest -m contract tests/contract/test_lake_schema.py
    tests/contract/test_lake_store.py`; `files.py` reaches 100 % in `uv run pytest -m "unit or contract"
    --cov=src/huron --cov-report=term-missing --cov-fail-under=0`. The `apply_plan`-versus-recompute race is
    a named race test: an intermittent failure stops the milestone and is never re-run to green.
  - `rg -n "^(from|import) huron" migrations/versions/0017_lake_commits.py` prints nothing; DT-17's grep proof
    over `src/huron/core/metastore/lake` prints only CTE names.
- Dependencies: M13.2; M11.6, M11.7 (`scan_settled`, `set_states` for the recompute race), M8.
- Decisions: OQ-1.2 (settled, owner decision 12)
- Decisions: OQ-13.3 (settled, owner decision 12)
- Decisions: OQ-14.3 (settled, owner decision 12)
- Decisions: OQ-17.1 (settled, owner decision 12)
- Status: pending

### M13.5 Commit store halves: state, queue and leases

- Intent: implement durable commit state, the lease queue and the verification checkpoint on both adapters,
  with the lease fence and FIFO-with-express claim order, and give DT-12's delete guard its unfinished-commit
  count.
- Delete: none.
- Create: `src/huron/core/metastore/lake/commits.py`: `PostgresCommits` and `InMemoryCommits` halves:
  `commit`, `commit_progress`; `insert_commit`, `unfinished_total`, `lock_commit` (`LeaseLost` unless
  `verifying` under this owner), `finish_commit` (deletes the checks); `claim_commit` (fails over-limit and
  past-deadline candidates first, then the oldest eligible by `(submitted_at, id)` with the express filter,
  `SKIP LOCKED`, a lapsed lease counted as a failure), `extend_commit` (flushes `VerifiedFile`s with `ON
  CONFLICT DO UPDATE` under the owner guard; a lost guard is `LeaseLost` and rolls the flush back),
  `commit_checks`, `release_commit` (backoff and `last_problem`; a lost guard is a no-op), `fail_commit`,
  `expire_commits`, `prune_commits` (M13.3's names for DT-14's `claim` … `prune`). `ino` round-trips as
  `numeric(20,0)` through `::text`. Lease arithmetic uses the injected `Clock` in both adapters (DT-17's Time
  decision, which governs DT-14's `clock_timestamp()` sentence).
- Modify:
  - `src/huron/core/metastore/lake/collections.py`: `unfinished_commits(collection_id)` (`queued` and
    `verifying` only); `src/huron/core/lake/ports.py`: `CollectionWriter` gains it; `LakeStore` gains
    `CommitStore` and `CommitQueue`, `LakeTransaction` gains `CommitWriter`.
  - `src/huron/core/metastore/lake/store.py`, `memory.py`: compose the halves.
  - `tests/lake_store_contract.py`: a commits area (C16: after A's lease lapses and B claims, A's
    `extend_commit`, `release_commit`, `fail_commit` and `lock_commit` are `LeaseLost` or no-ops and B's state
    is untouched; `claim_commit` order and the express filter; `extend_commit` flushes and replaces checks;
    the backoff sequence on `release_commit`; `fail_commit` and `finish_commit` delete the checks;
    `expire_commits` and `prune_commits` honour `limit`; `unfinished_total` and
    `unfinished_commits` count only `queued` and `verifying`; the fake refuses `lock_commit`/`finish_commit`
    before the commit's collection is locked).
  - `tests/contract/test_lake_store.py`: C15 (two queues call `claim_commit` concurrently on one eligible
    commit: exactly one claim, the other `None` without blocking).
- Design: "DT-14 interfaces and contracts" (`lake/ports.py`: store and volume requirements: `claim` …
  `unfinished_total`, under M13.3's names; the fake); "DT-14 commit state diagram"; "DT-14 crash-matrix test
  plan" (C15, C16); "DT-17 interfaces and contracts" (Correctness model, Time); "DT-17 port → adapter →
  fake" (`CommitStore`, `CommitQueue` / `CommitWriter` row); "DT-12 handoffs" (DT-14 row).
- Verification:
  - The plan-wide gate; `uv run pytest tests/unit/test_lake_memory_store.py tests/unit/test_lake_ddl_sync.py`
    passes (structural conformance with the grown composites; no two halves share a public name, so
    `AccessResetQueue`'s `claim`/`extend` and the commit queue's methods stay distinct).
  - `rg -n "def (claim|extend|checks|release|fail|expire|prune|page)\(" src/huron/core/metastore/lake/commits.py src/huron/core/metastore/lake/files.py`
    prints nothing.
  - Run in the background and poll: `uv run pytest -m contract tests/contract/test_lake_store.py`. C15 is a
    named race test and is never re-run to green. `commits.py` and `collections.py` reach 100 % in the "unit
    or contract" run.
- Dependencies: M13.3, M13.4.
- Decisions: OQ-14.3 (settled, owner decision 12)
- Status: pending

### M13.6 Commit acceptance, status and the file listing

- Intent: accept a commit in one transaction (parse, authorize, claim the key, lock the collection, apply the
  queue cap, run the advisory plan with the `If-Match` value, insert the commit, remember the replay), read its
  status, list a collection's files, and make a settled collection's delete wait for its unfinished commits.
- Delete: none.
- Create: `tests/unit/test_lake_commits.py`: `submit` (rows 5–10 refuse synchronously and store nothing; a
  fresh accept returns `replayed=False`; the same key and body replay the same commit's current view with
  `replayed=True` and add no row; the same key with another body is
  `IDEMPOTENCY_KEY_REUSED`; authorization precedes the claim, so a replay by an actor who lost Developer is
  403; at `max_unfinished` the answer is 503 `{dependency: "commit_queue", reason: "saturated"}` with
  `Retry-After: 30`; the advisory plan's rows 11–20 including 412 `current_version`; the stored record:
  `queued`, `failures` 0, `not_before` = `submitted_at`, `deadline`, `verify_files`/`verify_bytes` from
  `to_verify()`); `status` (404 for a commit of another collection and for an invisible catalog; `progress`
  from the checks).
- Modify:
  - `src/huron/core/lake/commits.py`: `Submission(view: CommitView, replayed: bool)`; `Commits.__init__`,
    `submit`, `status` (`work` and `housekeep` in M13.7). `submit` returns `Submission`, not DT-14's bare
    `CommitView`, so the route can tell a fresh accept from an `Idempotency-Key` replay (on a replay, `view`
    is that commit's current status and `replayed` is true); a design override the head records against
    DT-14's `Commits` block.
  - `src/huron/core/lake/files.py`: `FilePage`, `Files.list` (Reader through `require_on_collection`; a draft
    is an empty window; keyset by `rel_path` through `FileStore.file_page`; `collection_version` from the same
    read).
  - `src/huron/core/lake/collections.py`: the settled delete reads `unfinished_commits` in its pre-check and
    re-checks it under the row lock (409 `COLLECTION_NOT_EMPTY` with the count).
  - `tests/unit/test_lake_files.py`: `Files.list` cases. `tests/unit/test_lake_collections.py`: a delete with an
    unfinished commit is refused with `unfinished_commits: 1`; an acceptance and a delete serialize on the row
    lock.
  - `design/api.html` §7: the `DEPENDENCY_UNAVAILABLE` row reaches DT-18's wording (`commit_queue` added).
  - `src/huron/core/lake/__init__.py`: `Commits`, `Submission`, `Files`, `FilePage`.
- Design: "DT-14 interfaces and contracts" (`lake/commits.py`: `Commits`: `submit`, `status`); "DT-14 the
  idempotency rule"; "DT-14 decisions" (Run sites, L-14 (a)); "DT-14 failure table" (F1–F3); "DT-13 interfaces
  and contracts" (`lake/files.py`: `GET /api/v1/collections/{id}/files`); "DT-12 deletion sequence and failure
  table"; "DT-18 error-code table rows" (`DEPENDENCY_UNAVAILABLE`).
- Verification:
  - The plan-wide gate and `make docs`; `uv run pytest tests/unit/test_lake_commits.py tests/unit/test_lake_files.py
    tests/unit/test_lake_collections.py tests/unit/test_error_contract.py` passes; the modified modules at
    100 %.
  - `rg -n '"commit"' src/huron/core/foundation/retry.py` shows `Replay.kind` already holding `commit`.
- Dependencies: M13.5; M11.10.
- Decisions: OQ-14.1 (settled, owner decision 12)
- Status: pending

### M13.7 The commit attempt, housekeeping and the crash matrix

- Intent: run one attempt of one commit (claim, heartbeat with checkpoint flushes, bounded verification in
  byte order, the final transaction with the applied plan and the in-transaction re-stamp, terminal versus
  transient outcomes), expire and prune commits and expired idempotency claims, and prove convergence under
  injected faults.
- Delete: none.
- Create: `tests/unit/test_lake_commit_crash_matrix.py`: DT-14 cases C1–C12 and C14 with `crash_on`
  (`tests/unit/support.py`), `FaultingLakeStore` (`tests/lake_faults.py`) at `lock_commit`, `files_by_key`,
  `apply_plan`, `append_audit` and `finish_commit`, `FakeClock`, and cancellation without release for a process
  death; each case asserts convergence and evidence (rows, version, `file_count`, audit entries, commit state).
  C13 needs DT-15's `mv` and lands in M16.
- Modify:
  - `src/huron/core/lake/commits.py`: `Commits.work(owner, *, express)` and `Commits.housekeep()`, calling
    the queue under M13.3's names (`work`: `claim_commit`, `extend_commit`, `commit_checks`,
    `release_commit`, `fail_commit`; `housekeep`: `expire_commits` and `prune_commits` where DT-14 writes
    `queue.expire` and `queue.prune`); `housekeep` also calls `store.prune_claims(now, limit=10_000)` on the
    same tick (OQ-17.3 (a)). DT-14's in-attempt retry on `40001`/`40P01` has no port-level signal (DT-17
    lets them propagate and `lake` cannot import `asyncpg`), so such a failure takes the transient release
    that F13 ends in (reported).
  - `tests/unit/test_lake_commits.py`: the heartbeat extends every `lease / 3` and flushes; `LeaseLost` drops
    the attempt and writes nothing; `work` raises nothing but `CancelledError`; `housekeep` reports expired,
    pruned and claim counts.
- Design: "DT-14 interfaces and contracts" (`Commits`: `work`, `housekeep`, invariants, lock order); "DT-14
  data flow: submit, re-hash, transaction and poll"; "DT-14 failure table"; "DT-14 crash-matrix test plan";
  "DT-13 interfaces and contracts" (the run-site contract); "DT-17 open questions" (OQ-17.3); "DT-17 port →
  adapter → fake" (`FaultingLakeStore`).
- Verification:
  - The plan-wide gate; `uv run pytest tests/unit/test_lake_commit_crash_matrix.py tests/unit/test_lake_commits.py`
    passes; `commits.py` at 100 %. A crash-matrix case that fails intermittently is a failure, never re-run to
    green, and stops the milestone until a fix lands with a named test.
- Dependencies: M13.6; M9 (`tests/lake_faults.py`), M8 (`prune_claims`).
- Decisions: OQ-14.1 (settled, owner decision 12)
- Decisions: OQ-14.2 (settled, owner decision 12)
- Decisions: OQ-14.3 (settled, owner decision 12)
- Decisions: OQ-17.3 (settled, owner decision 12)
- Status: pending

### M13.8 The commit worker and its settings in the API

- Intent: run `commit_workers` slots per replica (the last an express slot) and the housekeeping loop in the
  lifespan, configured by `LakeSettings` with DT-14's bounds and DT-18's startup refusals; `Commits` is built
  once and shared by the routes and the worker.
- Delete: none.
- Create:
  - `src/huron/applications/api/commits.py`: `CommitWorker(commits, *, owner, slots, idle_seconds,
    housekeeping_seconds)` with `wake`, `__aenter__`, `__aexit__`.
  - `tests/unit/test_api_commit_worker.py`: slot `i == slots - 1` claims express only when `slots >= 2`;
    `wake()` ends an idle wait; a failing housekeeping pass is logged with its traceback and the next runs on
    schedule; exit cancels every task and the cancellation path releases leases within 5 s.
- Modify:
  - `src/huron/applications/api/settings.py`: `LakeSettings` (DT-13's `commit_max_entries`,
    `commit_max_file_bytes` and DT-14's `commit_*` fields with DT-18's bounds) as `ApiSettings.lake` with its
    three validators; the after-validator's refusal 4 (`lake.commit_workers > volume.max_concurrent_hashes`).
  - `src/huron/applications/api/runtime.py`: `ApiRuntime.commits`, `ApiRuntime.commit_worker`.
  - `src/huron/applications/api/app.py`: the lifespan builds `CommitPolicy` from the settings
    (`hashes_per_commit = max_concurrent_hashes // commit_workers`) and `Commits` once, enters `CommitWorker`
    after the pool, the `PosixVolume` and the `AccessResetWorker`, and leaves it first.
  - `tests/unit/support.py` and every test that builds `ApiSettings` or `ApiRuntime` directly;
    `tests/unit/test_api_settings.py` (each inequality refused, one case each, and the boundary that passes);
    `tests/unit/test_api_app.py` (the worker is entered and left with the lifespan).
- Design: "DT-14 settings" (the field table and `applications/api/commits.py`: `CommitWorker`); "DT-18 settings:
  the merged `ApiSettings` diff" (`LakeSettings`, startup refusals 4 and 5); "DT-18 interfaces and contracts"
  (Lake service dependencies: `runtime.commits`); "DT-14 decisions" (Bound, Fairness, Recovery and replicas).
- Verification:
  - The plan-wide gate; `uv run pytest tests/unit/test_api_commit_worker.py tests/unit/test_api_settings.py
    tests/unit/test_api_app.py` passes; `commits.py` (API) and `settings.py` at 100 %.
- Dependencies: M13.7; M11.12.
- Decisions: OQ-17.3 (settled, owner decision 12)
- Status: pending

### M13.9 Lake routes: files, commit and commit status (rows 31–33)

- Intent: serve the file listing, commit acceptance (202 with `Location` and `Retry-After`, the packaged
  request schema in OpenAPI, `wake()` after a fresh accept) and commit status in DT-18's shapes, and land the
  push-and-commit section of the design record.
- Delete: none.
- Create:
  - `src/huron/applications/api/routes/lake/endpoints/commits.py`: `POST /collections/{id}/commit` (IM, IK;
    the raw body validated against `commit-request-v1.json`, 422 `REQUEST_INVALID` per DT-13 row 1; the
    document attached through `openapi_extra`; 202, `Location`, `Retry-After: commit_poll_after_seconds`;
    `runtime.commit_worker.wake()` only after a fresh 202, that is when M13.6's `Submission.replayed` is
    false) and `GET /collections/{id}/commits/{commit_id}`
    (200; `Retry-After` while unfinished).
  - `src/huron/applications/api/routes/lake/schema/commits.py`: `CommitProgressBody`, `CommitResultBody`,
    `CommitBody` (`from_view`; the shared `Problem` schema for `problem` and `last_problem`).
  - `tests/unit/test_api_lake_commits.py`: each DT-13 refusal code rendered with its `context`; a failed commit
    is 200 with `state: "failed"` and `problem`; another collection's commit id and an invisible catalog are
    404; `CommitBody` for each state.
- Modify:
  - `src/huron/applications/api/routes/lake/endpoints/collections.py`: `GET /collections/{id}/files` (row 31).
  - `src/huron/applications/api/routes/lake/schema/collections.py`: `FileBody`, `FilePage`.
  - `src/huron/applications/api/routes/lake/dependencies.py`: `files()`, `commits()` (returns `runtime.commits`).
  - `src/huron/applications/api/routes/lake/__init__.py` includes the commits router;
    `src/huron/applications/api/routes/pagination.py` gains the `files` listing.
  - `tests/unit/test_lake_routes.py`: the sweep grows by exactly three; ladder rows 31–33;
    `test_commit_accept_and_poll` (`wake()` called once); `test_idempotent_replay` for row 32 (a replay
    answers the same commit and does not call `wake()`) and the IM/IK cases for row 32.
    `tests/unit/test_lake_openapi.py`: row 32's request schema equals the packaged document.
    `tests/unit/test_api_router_composition.py` (tag `commits`); `tests/unit/test_execution_model.py` (the three
    operations); `tests/unit/test_api_pagination.py` (the files cursor).
  - `design/api.html` §3: rows 31–33. `design/layer-raw.html`: §5 Push and commit (`commit`).
    `design/catalog-search.html:347`: `layer-raw.html#ingest` becomes `layer-raw.html#commit`.
    `design/rbac.html` `:144` and `:431` (DT-26 rows naming the DT-4 task, true once commits are served):
    "commit raw revisions" (`:144`) becomes "push and commit Raw files in a catalog where they hold
    Developer", and "commits raw revisions" (`:431`) becomes "pushes and commits Raw files in a catalog where
    they hold Developer".
- Design: "DT-18 route table" (rows 31–33 and their notes); "DT-18 decisions" (Commit body schema, OpenAPI
  tags); "DT-18 request and response models"; "DT-18 tests this design requires"; "DT-14 interfaces and
  contracts" (`applications/api`: the two routes); "DT-13 interfaces and contracts" (`lake/files.py`: `GET
  /api/v1/collections/{id}/files`); "DT-26 design record pages: the Raw-facing six" (layer-raw §5, `api.html`
  §3); "DT-26 broken links and their fixes" (`catalog-search.html:347`).
- Verification:
  - The plan-wide gate and `make docs`; `uv run pytest tests/unit/test_lake_routes.py
    tests/unit/test_api_lake_commits.py tests/unit/test_lake_openapi.py tests/unit/test_api_router_composition.py
    tests/unit/test_execution_model.py tests/unit/test_api_pagination.py tests/unit/test_error_contract.py`
    passes; every new route module at 100 %.
  - `rg -n 'layer-raw.html#ingest' design/catalog-search.html` and `rg -n -i 'commits? raw revisions' design/rbac.html`
    print nothing.
  - Milestone close: the contract and integration suites pass; `uv run lint-imports` keeps all 20 contracts.
- Dependencies: M13.8; M11.14.
- Decisions: OQ-14.1 (settled, owner decision 12)
- Status: pending

## Milestone 14 — CLI working copy and push

Spec build step 4 on the client, against M13's routes 31–33 and its commit worker. Each collection gets a
working copy under `collections/<uuid>/`: `base.json` as the commit point, `metadata.json`, the paged
`files.jsonl` listing and `staged.json`. `sync.pull` rebases the working copy three-way and re-marks stale
entries, and the staging verbs run locally without a token. DT-21's write path follows: the mount probe,
one collection directory descriptor, a token-scoped partial per add, resume by read-back and append, and
placement by `link` (or by `rename` with `--overwrite`). `push` is DT-21's step algorithm with the
`Idempotency-Key` ticket persisted before the POST, polling, and cleanup. Its crash matrix proves that a
second `huron push` after a kill at any step finishes with exactly one commit. A staged metadata change is
carried by pulls and shown by `status` and `diff`; `push` publishes it once M16's row 34 exists, which is
M18.1's change. The large-file acceptance case on this path belongs to M15. CLI guide §5, §6 and §8 land
here, together with the §7 lines for `discard` and `switch`.

### M14.1 Working copy and pull

- Intent: one collection's working copy as DT-20 specifies it. Values are immutable, every write is
  atomic under the state lock, `base.json` is written last as the commit point, and the listing is read by
  one streaming scan. With it comes `sync.pull`, the single pull that `checkout`, `switch`, `push` and
  later `mv` and `publish_metadata` share: a three-way metadata rebase per JSON pointer, identity values
  from the server, staged entries re-marked stale rather than dropped, and nothing written on a conflict.
- Delete: none.
- Create:
  - `src/huron/applications/cli/staging.py`: `StaleReason`, `PulledFile`, `Base` (with `from_body`),
    `StagedAdd`, `StagedRemove`, `StagingConflict` (exit 6), `Staged`, `WorkingCopy` and `Checkout`. The
    working-copy rules 1–4 apply.
    - `Staged`: `with_add`, `with_remove`, `without`, `remarked`, `is_empty` and `commit_body`.
      `commit_body` builds a `commit-request-v1.json` body and refuses stale or empty stagings.
    - `WorkingCopy`: `metadata_changes` through `field_changes`, and `is_clean`.
    - `Checkout`: `all`; `load`, under the shared lock; `save`, under the exclusive lock in rule 2's order,
      streaming `files.jsonl` to `files.jsonl.<pid>.tmp`; `scan`, O(rows) time and O(hits) memory; `delete`.
  - `src/huron/applications/cli/sync.py`: `Conflict` (using DT-7's `Absent` marker), `Rebase`,
    `rebase_metadata` (pure), `PullOutcome` and `pull`. `publish_metadata` comes in M18.1.
    - Network first: row 28, then row 31 through `HuronClient.page_bodies` (below) into a temporary
      listing. If the last page body's `collection_version` differs from row 28's version, or the
      listing's line count differs from `file_count`, the pull starts again once and then refuses with
      exit 6 ("the collection is changing; try again").
    - A draft is refused (exit 6). A rebase conflict refuses the pull and writes nothing.
    - The write is one exclusive-lock section that re-loads the copy, rebases, re-marks with `exists`,
      `collides`, `changed` or `gone`, and saves; `staged.push` is kept unchanged. If `base.json` changed
      in between, the pull starts again once. When no copy exists, it saves a fresh one.
  - `tests/unit/cli/test_cli_staging.py` (DT-20's row, the value and file part):
    - The `Staged` laws: a re-add replaces; a key collision; an add over a staged remove, with and without
      `overwrite`; `rm` of a staged add un-stages it.
    - `test_commit_body_validates_against_commit_request_v1`: a Hypothesis property over generated stagings,
      checked with `huron.schema.validator("commit-request-v1.json")`. Stale and empty stagings are refused.
    - `Checkout.save` order, and `test_crash_before_base_json_leaves_the_previous_copy`.
    - Strict-schema refusals: a wrong `version`, an unknown member, a `collection_id` that differs from the
      directory name, a non-object `metadata.json`.
    - `scan` over a 10,000-line listing finds case variants and `under` prefixes.
  - `tests/unit/cli/test_cli_sync.py`, the `rebase_metadata` and `pull` part of DT-20's row:
    - The rebase table (local-only, server-only, same-value, conflicting, nested-prefix and identity cases),
      plus `rebase(x, x, y) == y` and `rebase(x, y, x) == y` minus identity edits.
    - `pull` against the in-memory API, with files committed in setup by writing bytes onto the `tmp_path`
      volume and posting row 32 directly: fresh; clean refresh; rebase with entries re-marked `exists`,
      `collides`, `changed` and `gone`; a conflict writes nothing; a draft is refused.
    - `test_listing_that_changes_between_pages_is_retried_once`: a second client's commit is injected by a
      response hook on the first row-31 page.
- Modify:
  - `src/huron/applications/cli/client.py`: `HuronClient.page_bodies(path, *, params)` yields each page
    body (the envelope, `items` included) through M10.3's `after`/`next_cursor` loop, and `pages` is
    re-expressed over it (yielding each body's `items`), so the CLI keeps one paging loop. `pull` reads
    `FilePage.collection_version` and M18.3's `check` reads `FindingsPage.status` through it. DT-19's
    `HuronClient` lists only `pages`, which yields items; `page_bodies` is the plan's addition.
  - `tests/unit/cli/test_cli_client.py`: `page_bodies` over row 31 yields every envelope with its
    `collection_version`; through `respx`, `pages` yields the concatenation of the bodies' `items`, and a
    repeated cursor still raises.
- Design: DT-20 decisions ("Pull, rebase and conflicts", "The pulled file listing"); DT-20 the working copy:
  `collections/<uuid>/` schemas and the write rules; DT-20 interfaces and contracts → "`staging.py`: the
  working copy", "`sync.py`: pull, rebase and publish" (`rebase_metadata`, `pull`); DT-21 handoffs (DT-20
  row: `pull` keeps `staged.push`); DT-13 (`rel_path_key`, `commit-request-v1.json`, via M13); DT-7
  `huron.schema.metadata` (field diff); DT-18 route table (rows 28, 31; `FilePage` and `FindingsPage`
  envelopes); DT-19 interfaces and contracts → "`client.py`: the Huron API client" (`pages`).
- Verification:
  - The plan-wide gate. `uv run pytest tests/unit/cli/test_cli_staging.py tests/unit/cli/test_cli_sync.py
    tests/unit/cli/test_cli_client.py -q` passes, including the named tests.
  - `rg -n "next_cursor" src/huron/applications/cli` names only `client.py`: one paging loop.
  - `rg -n "readlines\(|\.read_text\(|\.read\(\)" src/huron/applications/cli/staging.py` prints nothing:
    `files.jsonl` is read only by line streaming (R20-2).
  - Every created or modified file is at 100 % line coverage.
- Dependencies: M12.3; M13.
- Decisions: OQ-20.2 (settled, owner decision 12)
- Status: pending

### M14.2 Staging verbs, `checkout`, `switch`, and created collections checked out

- Intent: the Git-style verbs over the working copy. `add`, `rm`, `status`, `diff` and `discard` resolve
  `-c` locally and need no token, hashing runs before the lock, and staging is all or nothing. `checkout`
  and `switch` follow DT-20's conflict table. `create collection` now ends checked out (P2), and
  `delete collection` removes the local copy. Staging refuses only while a push commit or unlink is pending
  (OQ-21.2 (a)).
- Delete: none.
- Create:
  - `src/huron/applications/cli/commands/staging.py`:
    - `add SOURCES… [--to REL_DIR] [--overwrite] [-c]`, by DT-20's "`add` sources" rule.
      - A file stages `<to>/<basename>`, and a directory stages `<to>/<dirname>/<relative path>`.
      - A symlink to a file is followed and its `realpath` recorded; a symlinked directory is never
        descended; any other entry type refuses the whole `add` (exit 1).
      - `check_rel_path` failures exit 2. One `Checkout.scan` decides `exists` and `collides`.
      - Each file is hashed with `hashlib.file_digest` before the lock, with a stderr progress bar.
        `size_bytes`, `mtime_ns`, `host` and `staged_at` are recorded.
    - `rm REL_PATHS… [-r] [-c]`: an exact row stages `expected_sha256`; `-r` stages every row under the
      directory. A case variant exits 4 and names the row's spelling. A path that is neither listed nor
      staged exits 4.
    - `status [-c] [-o]`: DT-20's status document. `source_changed` comes from one `stat`. Row 28 is read
      best effort; a failed read prints a warning and still exits 0.
    - `diff [-c] [-o]`: `pointer  old → new` lines (`-` for absent); JSON and YAML print
      `[FieldChange.as_json()]`.
    - `discard [PATHS…] [--files] [--metadata] [--force] [-c]`: with no flag and no path it drops both
      kinds. `staged.push` set without `--force` exits 6. With `--force`, stderr says that placed bytes stay
      for the reconciler and that a commit may still finish on the server. Discarding an entry clears its
      `stale` mark.
    - While `staged.push.commit` or `staged.push.unlink` is set, `add`, `rm` and `discard` (without
      `--force`) exit 6. The copy phase is allowed (OQ-21.2 (a); DT-21 P-4).
    - Local resolution: a UUID names `collections/<uuid>/`; any other text goes through
      `resolve_identifier` and is matched against the checkouts' `base.json` identifiers; with no text,
      `config.collection` applies. A collection that is not checked out exits 2.
- Modify:
  - `src/huron/applications/cli/commands/collections.py`:
    - `checkout PATH|ID`: R, then `sync.pull`, by the conflict table. A non-null `staged.push`, a draft, a
      rebase conflict or a listing that kept changing each exit 6. Stderr prints "checked out <identifier>
      at version N (M files)", the stale entries, and the staged counts kept for other collections.
    - `switch PATH|ID`: a local match first, otherwise R and the pull. One best-effort row 28 read prints
      "behind by N versions".
    - `create collection`'s Done now runs `sync.pull` and sets the current collection (P2).
    - `delete collection` removes the working copy with `Checkout.delete`.
  - `src/huron/applications/cli/services.py` and `__init__.py`: `hostname: Callable[[], str]`, bound to
    `socket.gethostname`. `tests/unit/cli/conftest.py` gets a fixed hostname.
  - `src/huron/applications/cli/commands/__init__.py`: registers `add`, `rm`, `status`, `diff`, `discard`,
    `checkout` and `switch`.
  - `tests/unit/cli/test_cli_staging.py`, the verbs:
    - The `add` rules: a FIFO refused with exit 1; `metadata.json`, `.snapshot` and `x.part` refused with
      exit 2; the `exists` and `collides` conflicts; `--overwrite` over a staged remove; all or nothing
      on a failure mid-list.
    - `test_two_concurrent_adds_both_record_their_entry` (threads).
    - The `rm` rules.
    - `status` with `source_changed` after touching the source, and with the API unreachable.
    - `diff` after a `metadata.json` saved through `Checkout.save`.
    - The `discard` matrix.
    - `test_staging_refused_while_a_commit_is_in_flight`, using a `staged.json` push member the test
      writes.
  - `tests/unit/cli/test_cli_collections.py`: the `checkout`/`switch` matrix, one case per row of the
      conflict table; `create collection` ends checked out; `delete collection` removes the copy.
  - `docs/raw-lake/cli.md`: the §5 lines for `checkout`, `add`, `rm` and `status` (the push lines are
    M14.4's), and the §7 lines for `discard` and `switch`.
- Design: DT-20 decisions ("Staged work is per collection", "Local verbs stay local", "`create collection`
  ends checked out"); DT-20 the working copy (conflict rules; "a pull with rebase"); DT-20 command
  signatures, routes and exit codes (`checkout`, `switch`, `add`, `rm`, `status`, `diff`, `discard`, and the
  verb rules for `add`, `rm` and the status document); DT-20 handoffs (DT-19 row: `hostname`); DT-21
  decisions ("Staging while a push is unfinished"); DT-21 the progress document (P-4); DT-21 handoffs
  (DT-20 row); DT-26 the two new pages (§5, §7).
- Verification:
  - The plan-wide gate. `uv run pytest tests/unit/cli -q` passes, including the named tests.
  - A test asserts that `add`, `rm`, `status`, `diff` and `discard` make no request: a request-recording
    hook on both injected clients stays empty (apart from `status`'s one row-28 read).
  - `make docs` passes. Every created or modified file is at 100 % line coverage.
- Dependencies: M14.1.
- Decisions: OQ-21.2 (settled, owner decision 12)
- Status: pending

### M14.3 Mount writer and the push progress document

- Intent: DT-21's deep module, `writer.py`, is everything push does to the mount, behind two calls:
  `probe_volume`, which runs DT-11's table over `huron.schema.volume` (OQ-21.1 (a)), and
  `CollectionDirectory.place`, the resume rules W2–W6 with descriptor-relative `link` or `rename`, fsyncs,
  and permissive create modes (OQ-21.3 (a)). With it comes the push progress document that `staged.json`
  carries (rules P-1 to P-4), and the `mount_policy` member DT-21 hands to DT-19.
- Delete: none.
- Create:
  - `src/huron/applications/cli/writer.py`:
    - `COPY_BUFFER_BYTES`, `MountPolicy`, `ProbeReason`, `MountReport`, `SourceChanged`,
      `PlacementConflict`, `VolumeRefused`, `PlaceJob` and `Placement`.
    - `probe_volume` follows DT-11's table row for row, with the same reason strings, using
      `VolumeMarker`, `MARKER_NAME`, `MountEntry` and `mount_entry`. It reports `nconnect`. Under `strict`
      with no mountinfo it answers `unsupported_platform`, with the hint
      `huron config set mount_policy marker_only`. It never creates or repairs anything.
    - `CollectionDirectory`: `open` traverses with `O_RDONLY | O_DIRECTORY | O_NOFOLLOW` and checks the
      device; `place` follows invariants 1–4 and W2–W6; `discard_partial`, `unlink` and `close` (also a
      context manager).
    - Missing parent directories are created `0o777` and files `0o666`. `check_rel_path` is re-checked
      first; the source is `fstat`ed before and after the copy; `stop` is honoured between buffers. The
      errno mapping is DT-21's.
    - Module-level `_link`, `_rename`, `_unlink` and `_fsync` aliases of the `os` calls are the
      crash-matrix seams.
  - `src/huron/applications/cli/push.py`, its state half: `FileProgress`, `CommitTicket`, `PushProgress`
    (`from_json` with P-1 and P-2, `to_json`, `reconciled`, `with_placed`), `PendingPush` and
    `pending_pushes`. `pending_pushes` reads under the shared lock and touches neither network nor volume.
    `run_push` is M14.4's.
  - `tests/unit/cli/test_cli_writer.py`: DT-21's row.
    - `probe_volume`: each reason in DT-11's order; `strict` with mountinfo fixtures (`nfs4` with and without
      `nconnect=8`, `ext4`, an octal-escaped mount point, last entry wins); `unsupported_platform`.
    - `CollectionDirectory.open` refuses `..`, a symlinked segment and a missing directory.
    - `place`, a fresh copy: the digest, the size, mode `0o666 & ~umask`, the partial gone, the directory
      entry durable.
    - `place`, the resume rules: `test_hard_linked_partial_is_unlinked_and_the_final_is_unchanged` (W2);
      `test_resume_appends_at_an_odd_offset_on_the_same_inode` (W3, R21-4); W3 with a corrupted prefix,
      truncated and recopied once; W3 with an over-long partial; W4 ours versus foreign; W5 `EEXIST`
      keeping the verified partial; `test_symlink_swapped_for_the_partial_is_refused` (W5, R21-6); W6
      overwrite renaming over an existing file.
    - `place`, failures: the source changing during the copy (`unstable`); `stop` honoured between
      buffers; a regular file where a parent directory should be. `EACCES` on a `0o555` directory raises
      `VolumeRefused` (exit 5). `ENOSPC` and `EIO` raised through the `_fsync` alias give exit 1 and
      `VolumeUnavailable("io_error")`.
  - `tests/unit/cli/test_cli_push.py`, the state part of DT-21's row: `PushProgress` P-1 and P-2 refusals;
    `reconciled` (kept, re-staged with a new token, orphans returned); `with_placed`; `pending_pushes` in
    the copy, commit and cleanup phases.
- Modify:
  - `src/huron/applications/cli/errors.py`: `VolumeUnavailable(Unavailable)` with `dependency = "volume"`,
    `reason`, `prefix` and `found`. No exit code is added.
  - `src/huron/applications/cli/state.py`: the `config.yaml` member `mount_policy` (default `strict`),
    `Config.mount_policy`, and the `HURON_MOUNT_POLICY` override in `Config.effective`, recorded with its
    source.
  - `src/huron/applications/cli/commands/context.py`: `ConfigKey` gains `mount_policy`, and `config view`
    shows it. `test_cli_context.py` covers set, unset and the environment override.
- Design: DT-21 decisions ("L-30 (a)", "Mount check", "Where bytes go", "Copy", "Partial identity",
  "Resume rule (owned)"); DT-21 target module layout; DT-21 the progress document: `staged.json` `push`;
  DT-21 the push algorithm (the W-rule table); DT-21 interfaces and contracts → "`writer.py`: the mount",
  "`push.py`: the protocol" (values, `reconciled`, `pending_pushes`); DT-21 handoffs (DT-19 row); DT-21
  open questions (OQ-21.1, OQ-21.3); DT-11 (the probe table and `huron.schema.volume`, via M11); DT-13
  (`partial_name`, `check_rel_path`, via M13).
- Verification:
  - The plan-wide gate. `uv run pytest tests/unit/cli/test_cli_writer.py tests/unit/cli/test_cli_push.py -q`
    passes, including the named tests.
  - `rg -n "huron\.core|rawstore" src/huron/applications/cli` prints nothing (L-30 (a)).
  - `rg -n "^\s*(from|import) " src/huron/applications/cli/writer.py` shows only the standard library,
    `huron.schema` and the CLI's own `errors`.
  - `writer.py` stays within complexipy 15 and radon C for each function, so the W-rules are split into
    their own functions.
  - Every created or modified file is at 100 % line coverage.
- Dependencies: M14.1; M11, M13.
- Decisions: OQ-21.1 (settled, owner decision 12)
- Decisions: OQ-21.3 (settled, owner decision 12)
- Status: pending

### M14.4 `huron push`

- Intent: DT-21's step algorithm S0–S8: lock, route by phase, token, fresh read by UUID, mount, re-hash,
  place, commit, cleanup. The `Idempotency-Key` ticket is persisted before the POST and reused for every
  retry of an unknown outcome. Polls follow `Retry-After`, synchronous refusals are resubmitted at most
  twice, and the failure table is honoured. A second `huron push` after a kill at any point finishes with
  exactly one commit. Spec build step 4's client half is complete once M15's large-file gate runs it.
- Delete: none.
- Create:
  - `src/huron/applications/cli/commands/push.py`: `push(-m/--message, --jobs/-j 1..16, -c, -o)`, thin over
    `run_push`. stdout gets one result line, or the `PushResult` document under `-o json|yaml`.
  - `tests/unit/cli/test_cli_push.py`, the protocol part of DT-21's row. The mount is the API's own
    `tmp_path` volume, with `mount_policy: marker_only` and `mount_prefix` set to it.
    - The happy path: adds, an overwrite, a remove and `-m`. A removes-only push: no partial, no probe
      before S8 (c), and an unlink only when the listing has no row.
    - Every X-row the unit tier can produce. The concurrent-`mv` variant of X9 needs row 35 (M16) and is
      added in M18.2. X9 here is a colleague's commit through the API, injected between placement and the
      POST.
    - `test_push_crash_matrix`, parametrized over DT-21's nine kill points K1–K9 with descriptive ids
      (`after_token_write`, `mid_copy`, …), since test names and ids never cite design ids (plan rule
      "Clean sweep"). A `BaseException` subclass is raised at the writer's `_link`, `_rename`, `_unlink`
      or `_fsync` alias, or from an `event_hooks` entry on the API `TestClient` (the injected
      `httpx.Client`) at the chosen request. Each kill is followed by a second `huron push` that exits 0,
      with server rows equal to the bytes on disk, exactly one commit in the audit log, and no partial
      left.
    - `test_second_push_of_a_collection_exits_6`: the push lock is held through another descriptor (R21-3).
- Modify:
  - `src/huron/applications/cli/push.py`: `PushResult` and `run_push`, S0–S8, with the push lock
    (`flock(LOCK_EX | LOCK_NB)` on the `collections/<uuid>/` descriptor), the P-3 write discipline, the
    resubmission bound, polling with `services.sleep(min(max(retry_after or 5, 1), 60))`, and every
    failure-table outcome.
    - S1's "only a metadata change" route and S9 (`publish_metadata`) need row 34 (M16) and are added in
      M18.1. Until then, a staged metadata change stays staged across pushes and pulls, and `status` and
      `diff` show it.
  - `src/huron/applications/cli/commands/__init__.py`: registers `push`.
  - `tests/unit/cli/test_cli_entry.py`: `test_every_commit_body_validates_against_commit_request_v1`. Every
    body `run_push` sends during the push tests is captured by a request hook and validated against the
    packaged schema.
  - `docs/raw-lake/cli.md`:
    - §5: the push lines. The four-line sequence is copy to the token-scoped partial, place it by `link`
      (by `rename` with `--overwrite`), commit (202), and poll until `succeeded` or `failed`. Also
      `--jobs`, resuming by running `huron push` again, and `huron config set mount_policy marker_only`
      with the stand-in prefix for development. DT-26's outline says "place by `rename`"; the page follows
      the built behaviour (DT-21 L-11 (b); spec amendment A-26).
    - §6 When push stops: one row per X1–X21, using the CLI's message strings.
    - §8 Recover a file: copy it back from `.snapshot`, then `huron add --overwrite` and `huron push`.
- Design: DT-21 design (all), in particular: DT-21 decisions; DT-21 the push algorithm; DT-21 interfaces and
  contracts → "`push.py`: the protocol" and `commands/push.py`; DT-21 failure table; DT-21 tests this
  design requires; DT-21 data flow; DT-14 (the CLI rule for `Idempotency-Key`, the 202 and polling
  protocol, via M13); DT-18 route table (rows 5, 28, 31–33) and handoffs (DT-21 row); DT-20 handoffs (DT-21
  row); DT-26 the two new pages (§5, §6, §8) and the DT-21 handoff ("a change to a push failure message
  updates CLI guide §6 in the same change").
- Verification:
  - The plan-wide gate. `uv run pytest tests/unit/cli -q` passes, including the named tests and all nine
    crash-matrix cases. A crash-matrix failure stops the milestone and is never re-run to green (plan rule
    "Races").
  - `rg -n "dir_fd=|os\.link\(" src/huron/applications/cli` prints only `writer.py` lines: the volume is
    written only through `writer.py`, below one collection descriptor (B-5).
  - `rg -n "metadata\.json" src/huron/applications/cli/push.py src/huron/applications/cli/writer.py` prints
    nothing: push never writes `metadata.json`.
  - `make docs` and `git diff --check` pass. Every created or modified file is at 100 % line coverage.
- Dependencies: M14.2, M14.3; M13.
- Decisions: OQ-21.2 (settled, owner decision 12)
- Status: pending

## Milestone 15 — Test tiers, large-file gate and CI jobs

DT-23's test tiers, built on M11's plain-directory stand-in (`tests/fakes/ontap_volume.py`, `make raw-lake-init`,
the compose bind, `dev.env`'s volume half, `check-stack.sh volume`) and M14's `huron push`. The two new markers
`stack` and `nfs` arrive with the AST tier guard and B-10, and the integration job loses its exit-5 tolerance
(AG-14). Then the loopback NFS harness (`scripts/loopback_nfs.sh`, `tests/nfs_support.py`, `tests/linux/`) with
DT-11's cases 1–5, OQ-21.3's create-mode case and DT-21's write-path cases, the CI `nfs` job and `make test-nfs`;
the plain-directory large-file gate (`tests/acceptance/`, 12 GiB, the CI `large-file` job, `nightly.yml`
`nfs-large`, `make test-acceptance`, RL step 4); and the stack tier (`tests/stack/`, the realm's
`huron-integration` client, `make test-stack`, the CI `stack` job). Each B-11 command line, each
`testing.md` tier row and section lands with the task that creates its target (DT-25 and DT-26 landing rules).
On the owner's macOS every task that adds `stack` or `nfs` tests verifies them by
`uv run pytest -m "stack or nfs" --collect-only -q` and the tier guard; their first CI runs happen when M19.5
pushes the branch, and those runs are the receipts M19.5 records (plan-wide rule "Gate", DT-23 "Not verifiable
on this machine"). Two assertions need verbs that arrive later: `huron log` (row 36, M16; the verb, M18) and a
Reader's metadata publish (row 34, M16; `meta update` and push's publish, M18). They are added to the large-file
and stack tests by M19.1, not stubbed here. Group G7 may add at most four duplication-baseline signatures across
M15–M19, each with its running total under "Execution notes".

### M15.1 Markers `stack` and `nfs`, the tier guard, B-10 and the integration job

- Intent: register DT-23's two environment markers so that selection by marker is selection by environment,
  pin the no-silent-skip rule in a unit test that runs on every `make test`, state it as B-10 and in
  `testing.md`'s rules, and make "no integration test collected" a CI failure again (AG-14), because
  `tests/integration/` keeps the legacy workflow tests after DT-2.
- Delete:
  - `.github/workflows/ci.yml` `integration` job: the `set +e` … `exit "$status"` block and its step name
    "(no tests collected is success)" (DT-23 deletions).
  - `AGENTS.md` "Commands and gates": the sentence "The CI integration job currently tolerates no collected
    tests; that is not evidence of integration coverage." (AG-14 replaces it).
- Create:
  - `tests/unit/test_test_tiers.py` (`pytestmark = pytest.mark.unit`; parses with `ast`, imports no test
    module): DT-23's four rules as functions over a root directory, each run against the real `tests/` tree
    and against planted `tmp_path` trees that break it once each:
    - every `test_*.py` under `tests/linux/` has a module `pytestmark` containing `pytest.mark.nfs` and not
      `pytest.mark.unit`; every `test_*.py` under `tests/stack/` the same with `pytest.mark.stack`;
    - `pytest.mark.nfs` and `pytest.mark.stack` occur as AST attribute nodes nowhere else, except the `nfs`
      param mark of the `live_lake` fixture in `tests/acceptance/conftest.py` (DT-23's outline places that
      fixture there, so the guard's one exception names that file rather than `test_push_large_file.py`);
    - no module under `tests/linux/`, `tests/stack/` or `tests/acceptance/` calls `pytest.skip` or
      `pytest.importorskip` or uses `skipif`;
    - the guard is vacuous for an absent directory and says so in its assertion message, and a planted
      `tests/linux/test_x.py` without a `pytestmark` fails it.
- Modify:
  - `pyproject.toml` `[tool.pytest.ini_options]` `markers`: DT-23's six lines verbatim (the `unit`,
    `integration` and `acceptance` descriptions change; `stack` and `nfs` are new); `addopts` unchanged. This is
    the one tool-configuration change the plan's "Clean sweep" rule names for this task.
  - `.github/workflows/ci.yml`: `unit` gains `timeout-minutes: 15`, `contract` `timeout-minutes: 20`,
    `integration` `timeout-minutes: 20` and the single step `run: uv run pytest -m integration --no-header -q`.
  - `AGENTS.md`: B-10 appended to "Verification by boundary" in DT-25's wording (AG-12); AG-14's sentence in
    place of the deleted one.
  - `docs/getting-started/testing.md`: the "Rules" list gains B-10's line ("A `stack` or `nfs` test fails,
    never skips, without its environment"), linked to `AGENTS.md`; "Integration" is reworded to say the tier
    composes the application over testcontainers PostgreSQL, never compose (DT-23 deletions); the tier table
    (`:9-11`) is rewritten from "DT-23 the tier table": DT-23's columns with the Unit, Contract and
    Integration rows, and M1.4's placeholder `acceptance` row (Needs "—") is dropped (later M15 tasks add
    their own rows; M15.4 adds the two large-file rows with 12 GiB).
- Design: "DT-23 design: Volume stand-in, test tiers, CI jobs and the large-file gate" → "DT-23 decisions"
  (Markers, No silent skip), "DT-23 markers and the tier guard", "DT-23 CI workflow job outlines"
  (`ci.yml` lint to integration), "DT-23 the tier table", "DT-23 deletions"; "DT-25 design: …" → "DT-25
  `AGENTS.md`: sections replaced" (AG-12, AG-14), "DT-25 `AGENTS.md`: the binding rules, worded" (B-10);
  "DT-26 design: …" → "DT-26 developer docs, README and history" (`testing.md` rows).
- Skills: `writing-for-agents` (`AGENTS.md`).
- Verification:
  - The plan-wide gate, `make docs` and `git diff --check`.
  - `uv run pytest tests/unit/test_test_tiers.py -q` passes, including each planted-violation case.
  - `uv run pytest --markers | rg '^@pytest.mark.(stack|nfs):'` prints two lines;
    `uv run pytest -m "stack or nfs" --collect-only -q` exits 5 (nothing is marked yet).
  - `rg -n 'set \+e|-eq 5|no tests collected' .github/workflows/ci.yml` prints nothing, and
    `uv run python -c "import yaml; j = yaml.safe_load(open('.github/workflows/ci.yml'))['jobs']; assert [j[k]['timeout-minutes'] for k in ('unit', 'contract', 'integration')] == [15, 20, 20], j"`
    exits 0.
  - `rg -n 'currently tolerates no collected tests' AGENTS.md` prints nothing; `rg -n 'never skips' AGENTS.md
    docs/getting-started/testing.md` prints one line in each.
- Dependencies: M11, M14.
- Decisions: OQ-11.2 (settled, owner decision 12)
- Status: pending

### M15.2 The loopback NFS harness, the volume cases and the `nfs` job

- Intent: give the Linux tier its environment: one script that exports a runner-local directory through kernel
  nfsd and mounts it at `/projects` over NFSv4.2 with `root_squash`, the three fixed test users and the marker;
  a support module that reads that mount from the environment and fails, never skips, without it; the
  `tests/linux/` fixtures; DT-11's volume cases 4–5 as the tier's first tests; the merge-gating CI `nfs` job;
  and `make test-nfs` with its B-11 line.
- Delete: none.
- Create:
  - `scripts/loopback_nfs.sh` (bash, `set -euo pipefail`; mode 0755, committed as `100755`: `chmod +x`,
    checked with `git ls-files -s scripts/loopback_nfs.sh`): `up | remount | down` exactly as DT-23's verb table;
    exit 2 naming the missing prerequisite on a non-Linux host or without passwordless `sudo -n`, checked
    before any other command; `NFS_EXPORT` (default `/srv/huron-nfs`), `NFS_MOUNT` (default `/projects`),
    `NFS_VOLUME_ID` (required by `up`); `up` ends by printing the three `HURON_TEST_NFS_*` lines, and every
    other line it or its commands print goes to stderr, because CI appends stdout to `$GITHUB_ENV`.
  - `tests/nfs_support.py` (support module, collects nothing): `NfsMount` and
    `nfs_mount_from_environment(environ=os.environ)`, which probes `prefix` with `MountPolicy.STRICT` and the
    volume id and calls `pytest.fail` with the reason and the line `scripts/loopback_nfs.sh up`.
  - `tests/linux/__init__.py` (empty) and `tests/linux/conftest.py`: the session `nfs_mount` fixture,
    `lake_root` (a fresh `<prefix>/t-<12 hex>/` catalog directory made through `PosixVolume`, removed after
    `chmod u+w`), `RunAs` with `attempt(op, path)` (the fixed `-I -c` snippet importing only `os`, `sys` and
    `errno`; 30 s timeout; a `sudo` failure or timeout raises, never reads as a denial), the `run_as` factory and
    `remount` (`sudo -n scripts/loopback_nfs.sh remount`).
  - `tests/linux/test_nfs_volume.py` (`pytestmark = pytest.mark.nfs`): DT-11 case 4 (`probe_mount(STRICT)`
    accepts the mount; `verify`, `write_metadata` and `walk` behave as on `tmp_path`; a `.snapshot` made by
    `take_snapshot` on the export side is skipped by `walk`) and case 5 (an unmounted directory gives
    `not_mounted` under `strict` and `marker_missing` under `marker_only`). DT-11's `rename_collection` clause
    is not written: DT-15 replaced the method, and M16.4 adds the staged-move cases here.
  - `tests/unit/test_nfs_support.py` (`unit`): a missing variable and a failed probe (a `tmp_path` directory
    without a marker) each fail through `pytest.fail` with the reason and the `scripts/loopback_nfs.sh up` line;
    neither path calls `pytest.skip`.
- Modify:
  - `Makefile`: target `test-nfs` with DT-23's help line and this one-line recipe, which exports the three
    `HURON_TEST_NFS_*` lines `up` prints (DT-23's Makefile row discards them, so its recipe fails on every
    Linux developer machine; this plan's recipe overrides that row):
    `nfs_env="$$(NFS_VOLUME_ID=$$(uuidgen) ./scripts/loopback_nfs.sh up)" && set -a && eval "$$nfs_env" && set +a && uv run pytest -m "nfs and not acceptance"`
    (the `&&` chain keeps `up`'s exit status, so a refused `up` stops the recipe); `.PHONY` gains it.
  - `.github/workflows/ci.yml`: job `nfs` (`timeout-minutes: 20`) with DT-23's three steps after the shared
    checkout, `setup-uv` and `uv sync --all-groups` steps.
  - `AGENTS.md` "Commands and gates": B-11's `make test-nfs` line and its comment, in B-11's position.
  - `docs/getting-started/testing.md`: the tier table's NFS row; a new section "NFS (Linux)" (`make test-nfs`,
    passwordless sudo, what the harness creates and that `down` keeps users and data for a quick re-`up`).
- Design: "DT-23 design: …" → "DT-23 the loopback NFS harness", "DT-23 decisions" (Real NFS gates merge, No
  silent skip), "DT-23 make targets, compose, `dev.env` and `check-stack.sh`" (`test-nfs` row: help line; the
  recipe is overridden above), "DT-23 CI
  workflow job outlines" (`nfs`), "DT-23 placement of the handed-off tests" (DT-11 cases 4–5); "DT-11 design:
  …" → "DT-11 tests this design requires" (handed to DT-23, cases 4–5); "DT-15 design: …" → "`lake/ports.py`:
  the `Volume` port, `rename_collection` replaced"; "DT-25 … the binding rules, worded" (B-11).
- Verification:
  - The plan-wide gate, `make docs`, `git diff --check`, `bash -n scripts/loopback_nfs.sh` and
    `test -x scripts/loopback_nfs.sh`.
  - On darwin, `NFS_VOLUME_ID=0b8f3c1e-6a52-4c39-9f43-2f7d5e0a9c11 ./scripts/loopback_nfs.sh up; test $? -eq 2`
    exits 0 and the message names Linux (the refusal precedes every `sudo` call).
  - `uv run pytest -m "stack or nfs" --collect-only -q` lists the `tests/linux/test_nfs_volume.py` cases and
    nothing else; `uv run pytest tests/unit/test_test_tiers.py tests/unit/test_nfs_support.py -q` passes.
  - `make -n test-nfs` prints one line holding the `loopback_nfs.sh up` call, `set -a`, `eval "$nfs_env"` and
    `uv run pytest -m "nfs and not acceptance"`;
    `uv run python -c "import yaml; j = yaml.safe_load(open('.github/workflows/ci.yml'))['jobs']['nfs']; assert j['timeout-minutes'] == 20, j"`
    exits 0.
  - CI receipt: the first green `nfs` run, recorded by M19.5.
- Dependencies: M15.1; M11.
- Decisions: OQ-11.1 (settled, owner decision 12)
- Decisions: OQ-11.2 (settled, owner decision 12)
- Status: pending

### M15.3 NFS permission and write-path cases

- Intent: prove on a real NFSv4.2 mount, with real Reader, Developer and outsider users, the mechanism
  production uses: the golden ACLs `Nfs4AclPermissions` writes, the access each role gets after
  `Directories.provision`, downgrade and unmap through `reset`, the permissive create mode under inherited ACEs
  (OQ-21.3), and the write-path system calls the CLI writer relies on.
- Delete: none.
- Create:
  - `tests/linux/test_nfs_permissions.py` (`pytestmark = pytest.mark.nfs`): DT-11 cases 1–3 and OQ-21.3's case,
    over `lake_root`, `Nfs4AclPermissions`, `Directories` and `InMemoryRoleMappings` mapping `helio-readers`
    (gid 70011) to Reader and `helio-developers` (gid 70012) to Developer:
    - golden ACLs read back identically after `apply` and `apply_content`; `apply` on the runner's `tmp_path`
      raises `acl_unsupported`;
    - `run_as("lake-reader")`: create in the collection `EACCES`, read `ok`; `run_as("lake-dev")`: create,
      overwrite and delete `ok`; neither creates in a namespace directory nor deletes the collection directory;
      `run_as("lake-outsider")` cannot traverse; a Developer's file carries the inherited Huron ACE;
    - the Developer group downgraded to Reader and `reset`: writes fail on the collection and an existing file;
      unmapped and `reset`: traversal of the catalog directory fails;
    - a file the CLI writer (`huron.applications.cli.writer.CollectionDirectory.place`) creates `0o666` under
      the provisioned ACL is readable by `lake-reader` and overwritable by `lake-dev`.
  - `tests/linux/test_nfs_writer.py` (`pytestmark = pytest.mark.nfs`): DT-21's write-path cases: `link` onto an
    existing name gives `EEXIST` and onto an absent one succeeds; `rename` replaces; `fsync` of a file and its
    directory succeed; a partial written by the test user is resumed by append on the same inode after
    `remount()`; `probe_volume`'s `nconnect` parse on the real `/proc/self/mountinfo` reports 8.
- Modify: none (the fixtures are M15.2's).
- Design: "DT-23 design: …" → "DT-23 placement of the handed-off tests" (DT-11 cases 1–3, OQ-21.3 (a), DT-21
  rows), "DT-23 the loopback NFS harness" (users, gids, `RunAs`); "DT-11 design: …" → "DT-11 the access
  table", "DT-11 tests this design requires" (handed to DT-23, cases 1–3); "DT-21 design: …" → "DT-21 tests
  this design requires" (handed to DT-23), "DT-21 open questions" (OQ-21.3).
- Verification:
  - The plan-wide gate.
  - `uv run pytest -m "stack or nfs" --collect-only -q` lists the cases of the three `tests/linux/` modules;
    `uv run pytest tests/unit/test_test_tiers.py -q` passes.
  - `rg -n 'pytest\.skip|mark\.skip|importorskip|skipif' tests/linux` prints nothing (a test name such as
    `test_walk_skips_snapshot` for DT-11 case 4 does not match).
  - CI receipt: the first green `nfs` run containing these modules, recorded by M19.5.
- Dependencies: M15.2; M11, M14.
- Decisions: OQ-11.1 (settled, owner decision 12)
- Decisions: OQ-21.3 (settled, owner decision 12)
- Status: pending

### M15.4 The plain-directory large-file gate

- Intent: replace the deleted 9 GiB HTTP gate with L-39's push gate: one test, parametrised by mount, that kills
  a real `huron push` subprocess mid-copy of a 9 GiB sparse source, resumes it by append and reads the slow-lane
  re-hash through the commit route. The plain case is a merge gate (CI `large-file`), the NFS case runs nightly
  (`nightly.yml` `nfs-large`), and the free-space prerequisite falls from 25 GiB to 12 GiB. The step-7
  `huron log` assertion is M19.1's (the verb is M18's). Spec build step 4 is complete: RL step 4 flips.
- Delete:
  - `tests/acceptance_support.py`: `MINIMUM_FREE_BYTES`, `require_upload_capacity` and the docstring about
    upload and completion coexisting (DT-23 deletions).
  - `tests/unit/test_acceptance_capacity.py`: the `require_upload_capacity` cases (rewritten below).
- Create:
  - `tests/acceptance/conftest.py`: `LiveLake` (`api_url`, `prefix`, `volume_id`, `state_dir`, `stores`, `cli`,
    `spawn`) and `live_lake`, parametrised `plain` and `nfs` (`pytest.param("nfs", marks=pytest.mark.nfs)`), with
    DT-23's contract: `require_free_bytes` first (a failure, never a skip); `create_app(lake_settings(volume=…,
    tokens.issuer=api_url), stores=memory_stores(), key_source=…, company_idp_transport=…,
    group_directory_transport=…)` served by `uvicorn.Server` on a daemon thread at `127.0.0.1:0`, `/readyz` 200
    within 20 s, stopped within 10 s; setup through `cli` (an in-process `CliRunner` over DT-19's `Services`
    whose API client is an `httpx.Client` on `api_url` and whose IdP client reaches the fake issuer): `karl`
    creates the catalog, config and schema and maps `helio-developers` to Developer; `sam` runs `catalog use`,
    creates and activates a collection and `add`s the source; `spawn` runs the venv's `huron` console script with
    `HURON_STATE_DIR`, `HURON_API_URL` and `HURON_MOUNT_POLICY` only, after asserting more than 30 minutes of
    token life remain.
  - `tests/acceptance/test_push_large_file.py` (`pytestmark = pytest.mark.acceptance`):
    `test_interrupted_push_resumes_and_server_rehashes(live_lake)`, DT-23's steps 1–7 except the `huron log`
    clause of step 7.
- Modify:
  - `tests/acceptance_support.py`: `LARGE_FILE_FREE_BYTES: Final = 12 * 1024**3` and
    `require_free_bytes(path, need)` raising `RuntimeError` naming `need`, the path and the available bytes.
  - `tests/unit/test_acceptance_capacity.py`: enough space passes; too little raises naming all three values;
    `disk_usage` failing propagates.
  - `Makefile` `test-acceptance`: recipe `uv run pytest -m "acceptance and not nfs"` and DT-23's help line.
  - `.github/workflows/ci.yml`: job `large-file` (`timeout-minutes: 30`): the free-space step and
    `uv run pytest -m "acceptance and not nfs" --basetemp="${RUNNER_TEMP}/pytest" --no-header -q`.
  - `.github/workflows/nightly.yml`: job `nfs-large` (`ubuntu-latest`, `timeout-minutes: 60`, and M1.4's
    job-level `if: github.event_name != 'pull_request' || contains(github.event.pull_request.labels.*.name, 'nightly')`,
    so a pull request runs it only under the `nightly` label; plan-wide "Merge" rule): the free-space
    step on the export filesystem, `loopback_nfs.sh up | tee -a "$GITHUB_ENV"`,
    `uv run pytest -m "acceptance and nfs" --no-header -q`, and `loopback_nfs.sh down` under `if: always()`.
    The `reconciler-scale.json` summary step is M17.5's, with the test that writes the file. `unit-macos`
    (M1.4) is unchanged.
  - `AGENTS.md` "Commands and gates": B-11's 12 GiB comment and `make test-acceptance` line, in B-11's position.
  - `docs/getting-started/testing.md`: "Acceptance" becomes the plain-directory push gate (≥ 12 GiB free, the
    kill-and-resume sequence in one paragraph, `make test-acceptance`, the CI `large-file` job, the nightly
    `nfs-large` case); the tier table's two large-file rows from "DT-23 the tier table" ("Large file, plain"
    with "developer machines with 12 GiB free", and "Large, NFS").
  - `design/roadmap.html`: RL step 4's tag becomes `done`.
- Design: "DT-23 design: …" → "DT-23 the large-file acceptance test" (`LiveLake`, `live_lake`, the test outline,
  resource needs), "DT-23 decisions" (L-39), "DT-23 CI workflow job outlines" (`large-file`, `nfs-large`), "DT-23
  make targets, compose, `dev.env` and `check-stack.sh`" (`test-acceptance` row), "DT-23 deletions", "DT-23 open
  questions" (OQ-23.1); "DT-21 design: …" → "DT-21 tests this design requires" (the large-file case); "DT-22
  design: …" → "`tests/conftest.py` and `tests/unit/support.py`: how tests obtain the fakes"; "DT-25 … the
  binding rules, worded" (B-11); "DT-26 design: …" → "DT-26 roadmap rows" (RL step 4), "DT-26 developer docs,
  README and history" (`testing.md` rows).
- Verification:
  - The plan-wide gate, `make docs` and `git diff --check`.
  - `uv run pytest -m "acceptance and not nfs" --collect-only -q` lists exactly
    `test_interrupted_push_resumes_and_server_rehashes[plain]`, and `uv run pytest -m "acceptance and nfs"
    --collect-only -q` exactly `…[nfs]`; `uv run pytest tests/unit/test_acceptance_capacity.py
    tests/unit/test_test_tiers.py -q` passes.
  - Free space under pytest's base temp is measured with
    `uv run python -c "import shutil, tempfile; print(shutil.disk_usage(tempfile.gettempdir()).free)"`. At
    12 GiB or more, `make test-acceptance` runs in the background (polled) and passes; below, it is reported
    "not run" with the measured bytes, and the `large-file` receipt in M19.5 is the gate's evidence.
  - `make -n test-acceptance` prints `uv run pytest -m "acceptance and not nfs"`;
    `uv run python -c "import yaml; c = yaml.safe_load(open('.github/workflows/ci.yml'))['jobs']; n = yaml.safe_load(open('.github/workflows/nightly.yml'))['jobs']; assert c['large-file']['timeout-minutes'] == 30 and set(n) == {'nfs-large', 'unit-macos'} and n['nfs-large']['timeout-minutes'] == 60, (c, n); assert all(\"contains(github.event.pull_request.labels.*.name, 'nightly')\" in n[k]['if'] for k in n), n"`
    exits 0.
  - `rg -n '25 GiB|MINIMUM_FREE_BYTES|require_upload_capacity' tests Makefile AGENTS.md docs` prints nothing;
    `rg -n 'at least 12 GiB free' AGENTS.md` prints one line.
  - CI receipts: the first green `large-file` run and the first green `nfs-large` run, recorded by M19.5.
- Dependencies: M15.1, M15.2; M13, M14.
- Decisions: OQ-23.1 (settled, owner decision 12)
- Decisions: OQ-21.3 (settled, owner decision 12)
- Status: pending

### M15.5 The stack tier

- Intent: the one automated check of a real IdP's keys and claims against `CompanyTokenVerifier`, of the
  container's view of the host volume and of the uid rule: a mock-realm-only `huron-integration` client gives the
  test a real Keycloak ID token without a browser, and the host CLI drives the compose API through
  `fake-ldap-groups` and the plain-directory volume. The CI `stack` job is a required merge check (OQ-23.2).
  Step 3's `huron log` clause and step 4 (a Reader's refused publish) are M19.1's.
- Delete: none.
- Create:
  - `tests/stack/__init__.py` (empty) and `tests/stack/conftest.py`: the `stack` fixture: load `dev.env`; fail
    (never skip) unless `GET {HURON_API_URL}/readyz` answers 200 and `scripts/check-stack.sh volume` exits 0;
    for `karl`, `sam` and `rita` a password grant on `huron-integration` at the `company` realm's token endpoint
    (from its discovery document), the ID token written into a per-user `tmp_path` state directory through
    `huron.applications.cli.state`'s own writer, and `huron whoami --refresh` run as a subprocess with the
    `dev.env` variables plus `HURON_STATE_DIR`; `mount_prefix` set to the host's `.local/raw-lake/projects`.
  - `tests/stack/test_stack_push.py` (`pytestmark = pytest.mark.stack`): DT-23's outline steps 1–3 and 5:
    `karl` creates catalog `it-<8 hex>` with its config and schema and maps `helio-developers` to Developer and
    `helio-readers` to Reader; `sam` creates and activates a collection and pushes two small files; the bytes are
    on the host under the prefix at the collection's path and the commit read through row 33 is `succeeded`; on
    `sys.platform == "linux"` the collection directory's `st_uid` equals `os.getuid()` (an assertion branch,
    not a skip).
- Modify:
  - `scripts/keycloak/company-realm.json`: the `huron-integration` client (public, direct-access grants only,
    standard flow and device grant off, exactly one mapper: `oidc-audience-mapper` with
    `included.client.audience: huron-cli` on the ID token). No earlier task adds it: M5.2's drift clause
    refuses every client but `huron-cli` until this task.
  - `tests/unit/test_fake_identities.py`: the realm-drift clause "no client other than `huron-cli` exists,
    except `huron-integration`", which is public, has direct-access grants only and exactly that mapper.
  - `dev.env`: `HURON_MOUNT_POLICY=marker_only` (DT-23's CLI row; the host CLI writes the plain directory).
  - `Makefile`: target `test-stack` with DT-23's recipe and help line; `.PHONY` gains it.
  - `.github/workflows/ci.yml`: job `stack` (`timeout-minutes: 25`) with DT-23's steps; the log upload uses
    `actions/upload-artifact@cf430e030ddbb5b0abf93d22962f4752f3646cd9 # v7.0.2` (resolved with
    `gh api repos/actions/upload-artifact/git/ref/tags/v7.0.2`; re-resolve if a newer release exists at task
    time).
  - `AGENTS.md` "Commands and gates": B-11's `make test-stack` line and its comment, in B-11's position.
  - `docs/getting-started/testing.md`: the tier table's Stack row; a new section "Stack" (`make stack` then
    `make test-stack`, what it proves, `make keycloak-reset` after the realm edit).
  - `docs/getting-started/local-development.md` "Raw lake development": the single line
    `huron config set mount_prefix "$PWD/.local/raw-lake/projects"` and that `dev.env` sets
    `HURON_MOUNT_POLICY=marker_only` for the host CLI (DT-23 handoff to DT-26, not landed by M11.11).
- Design: "DT-23 design: …" → "DT-23 placement of the handed-off tests" (`tests/stack/test_stack_push.py`
  outline), "DT-23 the tier table" (Stack row), "DT-23 CI workflow job outlines" (`stack`, Notes), "DT-23 make
  targets, compose, `dev.env` and `check-stack.sh`" (`test-stack`, the `dev.env` CLI row), "DT-23 open questions"
  (OQ-23.2); "DT-22 design: …" → "DT-22 the shared fixture and the `company` realm" (Clients row), "DT-22 tests
  this design requires" (realm drift), "DT-22 how each test tier reaches each mock", "DT-22 open questions"
  (OQ-22.2); "DT-25 … the binding rules, worded" (B-11).
- Verification:
  - The plan-wide gate, `make docs`, `git diff --check`, `docker compose config --quiet` and
    `bash -n scripts/check-stack.sh`. `make stack`, `make up` and `make keycloak-reset` are not run; the owner
    re-imports the realm with `make keycloak-reset` (recorded under "Execution notes").
  - `uv run pytest tests/unit/test_fake_identities.py tests/unit/test_test_tiers.py -q` passes;
    `uv run pytest -m "stack or nfs" --collect-only -q` lists the stack cases beside the `tests/linux/` ones.
  - `make -n test-stack` prints `uv run --env-file dev.env pytest -m stack`;
    `uv run python -c "import yaml; j = yaml.safe_load(open('.github/workflows/ci.yml'))['jobs']['stack']; s = str(j['steps']); assert j['timeout-minutes'] == 25 and 'make stack' in s and 'make test-stack' in s and 'docker compose down -v' in s, j"`
    exits 0.
  - `uv run --env-file dev.env python -c "from huron.applications.api.settings import settings_from_environment as s; s()"`
    exits 0 with the new `dev.env` line.
  - CI receipt: the first green `stack` run, recorded by M19.5.
- Dependencies: M15.1; M9, M10, M11, M14.
- Decisions: OQ-22.2 (settled, owner decision 12)
- Decisions: OQ-23.2 (settled, owner decision 12)
- Status: pending

## Milestone 16 — Metadata publish and `mv`

Spec build step 5 on the server. The collection log comes first: DT-7's reader on both store roots, the
`collection_log` operation and row 36, so every later step-5 write is visible in the log its tests read. Then
DT-15's three writer methods on both adapters, `CollectionMetadata.publish` and `publish_many` with rows 34 and
10, the staged move on the volume (`stage_move`, `finish_move`, `staged_moves`, `remove_containers`) with
`Directories.place_moved` and its NFS cases, and finally `move` and `recover_move` with row 35, the failure-table
matrix and DT-14's three commit-interplay cases. `Volume.rename_collection` was never built (M11 follows DT-15),
so nothing is deleted for it; each task re-checks that no such name appears. `layer-raw.html` gains §8 Audit,
§6 Metadata publish and `mv` and §9 Recovery and lineage, and the runbook its retention table. CLI guide §7 is
not written here: every verb it names (`meta update`, `meta bulk-update`, `diff`, `log`, `mv`) is M18's, and
the line lands with its verb (DT-26 landing rule). No new problem code arises: `METADATA_INVALID`'s §7 row
gains its `frozen` rule in M16.3 and its `not_identity` rule in M16.5, the tasks that first raise them (M7.5
landed the row with `size` and `type`), and `COLLECTION_EXISTS` with `collection_id: null` is M11's row.

### M16.1 The collection log: reader halves and row 36

- Intent: let a Reader page one collection's audit entries newest first, also after the collection is
  deleted, through DT-7's `collection_log` operation and one route with no wrapping class. DT-4's 404/403 split
  stays in `require_on_collection`, fed by a private adapter whose `catalog_of` reads the catalog recorded on
  the collection's own entries.
- Delete: none.
- Create:
  - `tests/unit/test_api_lake_log.py`: DT-7's `test_collection_log_route`: 404 for an unknown id and for a
    collection in a catalog the actor cannot read (same body); 200 for a Reader, including after `delete`; a
    cursor round trip newest first; `limit=0` is 422; a cursor that breaks the `PageCursor` pattern is 422 and a
    well-formed cursor of another listing is 400 `INVALID_CURSOR` (DT-18's paging decision supersedes DT-7's
    single 422).
- Modify:
  - `src/huron/core/lake/ports.py`: `AuditReader` (`collection_catalog`, `collection_log(collection_id, *,
    before, limit) -> Window[AuditRecord]`) on `LakeStore`. M8.5 wrote `PostgresAudit.collection_log` with
    exactly this signature; this task completes `PostgresAudit` to the port by adding `collection_catalog`
    only, and does not rewrite `collection_log`.
  - `src/huron/core/lake/audit.py`: the `collection_log(actor, reader, collection_id, *, before, limit)`
    operation; `src/huron/core/lake/_impl/access.py`: the private adapter whose `catalog_of` calls
    `reader.collection_catalog`.
  - `src/huron/core/metastore/lake/audit.py`: `PostgresAudit.collection_catalog` (the catalog of the entries,
    joined to `lake.catalogs` for the name), beside M8.5's `collection_log`; the in-memory root reader half on
    `InMemoryAudit` (`collection_catalog` and `collection_log` with M8.5's paging semantics:
    `object_type = 'collection'`, `id < before`, newest first, `limit + 1` for `has_more`), composed by
    `InMemoryLakeStore`.
  - `tests/contract/test_lake_audit_store.py`: `test_collection_log_paging` gains DT-7's `collection_catalog`
    clauses (it answers after the collection row is deleted, and is `None` for a never-created id); M8.5 wrote
    its paging clauses.
  - `tests/lake_store_contract.py` audit area: newest-first paging with no repeat or gap across pages, an entry
    committed between two reads appears only at the head of a fresh read, `collection_catalog` answers after the
    collection row is deleted and is `None` for a never-created id; run by `tests/unit/test_lake_memory_store.py`
    and `tests/contract/test_lake_store.py`.
  - `tests/unit/test_lake_audit.py`: `collection_log` authorizes at Reader through the private adapter.
  - `src/huron/applications/api/routes/lake/endpoints/collections.py`: `GET /collections/{id}/log` (row 36),
    calling `collection_log(actor, runtime.stores.lake, id, before=…, limit=…)` directly;
    `src/huron/applications/api/routes/lake/schema/collections.py`: `AuditEntryBody`, whose `detail` OpenAPI
    schema is a `oneOf` with one `$defs` entry per DT-7 vocabulary row (`json_schema_extra`);
    `src/huron/applications/api/routes/pagination.py`: the `log` listing (`("log", str(id))`, decoded to
    `before`).
  - `tests/unit/test_lake_routes.py` (the anonymous sweep grows by exactly one; ladder row 36);
    `tests/unit/test_lake_openapi.py` (row 36's `detail` `oneOf`); `tests/unit/test_api_pagination.py` (the log
    pages newest first; a 3-entry log at `limit=1` visits each once); `tests/unit/test_api_router_composition.py`
    and `tests/unit/test_execution_model.py` (the operation).
  - `design/api.html` §3: row 36. `design/layer-raw.html`: §8 Audit (`audit`), linking DT-7's vocabulary by
    reference. `docs/raw-lake/operations.md`: §6 Retention with the `lake.audit_log` row (never deleted; covered
    by PostgreSQL backups, not ONTAP snapshots), the ONTAP snapshot row (the storage admin's policy, the spec's
    open question) and the lineage-pin consequence; the findings row is M17.5's.
- Design: "DT-7 design: Audit log" → "DT-7 decisions" (Collection log contents, Deleted collections), "The
  reader: `AuditReader` and `collection_log`", "`GET /api/v1/collections/{id}/log` (DT-18 renders it; `huron log`
  is its client, DT-20)", "DT-7 tests this design requires", "DT-7 retention and hardening"; "DT-18 design: …" →
  "DT-18 route table" (row 36), "DT-18 paging keys and the `label` filter" (the log row), "DT-18 request and
  response models" (`AuditEntryBody`), "DT-18 interfaces and contracts" → "Lake service dependencies", "DT-18
  tests this design requires", "DT-18 handoffs" (DT-7 row); "DT-26 design: …" → "DT-26 design record pages: the
  Raw-facing six" (layer-raw §8, `api.html` §3), "DT-26 the two new pages" (`operations.md` §6), "DT-26
  decisions" (Retention side by side).
- Skills: `oop-design` (`core/lake`); `postgresql-table-design` (`metastore/lake/audit.py`); `fastapi` (routes).
- Verification:
  - The plan-wide gate and `make docs`.
  - `uv run pytest tests/unit/test_api_lake_log.py tests/unit/test_lake_audit.py tests/unit/test_lake_routes.py
    tests/unit/test_lake_openapi.py tests/unit/test_api_pagination.py tests/unit/test_api_router_composition.py
    tests/unit/test_execution_model.py tests/unit/test_lake_memory_store.py -q` passes.
  - In the background, polled: `uv run pytest -m contract tests/contract/test_lake_audit_store.py
    tests/contract/test_lake_store.py`; `src/huron/core/metastore/lake/audit.py` reaches 100 % in the
    "unit or contract" coverage run; every other modified `src/` file is at 100 % in the unit run.
  - `rg -n 'UPDATE lake\.audit_log|DELETE FROM lake\.audit_log|TRUNCATE lake\.audit_log' src/huron` prints
    nothing; `rg -n 'id="audit"' design/layer-raw.html` prints one line.
- Dependencies: M11, M13.
- Decisions: OQ-7.1 (settled, owner decision 12)
- Status: pending

### M16.2 Writer halves: `publish_metadata`, `relocate` and `lock_collections`

- Intent: give the collection transaction DT-15's three writes on both adapters: a metadata-only update that
  never touches identity columns, an identity switch valid only under the layout lock that maps a unique
  violation to `CollectionExists` with the holder, and a multi-row lock in ascending id order that extends
  DT-12's lock order without a deadlock.
- Delete: none.
- Create: none.
- Modify:
  - `src/huron/core/lake/ports.py`: `CollectionWriter` gains `publish_metadata`, `relocate` and
    `lock_collections`.
  - `src/huron/core/metastore/lake/collections.py`: `PostgresCollections` and `InMemoryCollections` implement
    them: one statement each, every versioned `UPDATE` with `AND version = $n` from the locked record (zero rows
    raise `LockContractBroken`); `relocate` maps a violation of either identity unique key to `CollectionExists`
    naming the holder; `lock_collections` is `SELECT … WHERE id = ANY($1) ORDER BY id FOR UPDATE`; the fake takes
    its per-collection locks in id order and asserts that `relocate` runs under `lock_layout` on a row this
    transaction locked.
  - `tests/lake_faults.py`: `FaultingLakeStore` can raise before each of the three methods.
  - `tests/lake_store_contract.py` collections area: `publish_metadata` sets `state = 'active'`, bumps `version`
    and leaves `namespace_id`, `name` and `identifier` unchanged; `relocate` keeps I-12.4 (the identifier equals
    the joined form) and raises `CollectionExists` with the holder on both unique keys; a write without the row
    lock, and one with a stale recorded version, raise `LockContractBroken`; `lock_collections` returns the
    present rows in id order and omits absent ids; Postgres-only: two transactions locking the same three rows in
    opposite request orders both complete.
- Design: "DT-15 design: Metadata publish and mv" → "`lake/ports.py`: the writer methods DT-17 implements (beside
  DT-12's `CollectionWriter`)", "DT-15 handoffs" (DT-17 row); "DT-17 design: …" → "DT-17 decisions" (Entity
  versions), "DT-17 port → adapter → fake" (`CollectionWriter` row), "DT-17 interfaces and contracts"; "DT-12
  design: …" → the lock order in "DT-12 interfaces and contracts".
- Skills: `postgresql-table-design`; `oop-design` (`lake/ports.py`).
- Verification:
  - The plan-wide gate; `uv run pytest tests/unit/test_lake_memory_store.py tests/unit/test_lake_ddl_sync.py -q`
    passes (structural conformance of both roots and transactions; no two halves share a public name).
  - In the background, polled: `uv run pytest -m contract tests/contract/test_lake_store.py`. The opposite-order
    lock case is a named race: an intermittent failure stops the milestone and is never re-run to green.
  - `src/huron/core/metastore/lake/collections.py` reaches 100 % in the "unit or contract" coverage run;
    `rg -nP 'FROM (?!lake\.)\w+|JOIN (?!lake\.)\w+' src/huron/core/metastore/lake` prints only CTE names.
- Dependencies: M11, M13.
- Decisions: OQ-15.1 (settled, owner decision 12)
- Status: pending

### M16.3 Metadata publish and bulk edits (rows 34 and 10)

- Intent: publish a settled collection's complete metadata document as one audited version, with identity
  fields frozen, validation against the pinned config re-run only when the catalog's config moved, an empty diff
  as a no-op and `metadata.json` synced after the commit; and apply one merge patch to an explicit list of
  `{id, version}` pairs all or nothing, one `meta_publish` entry per changed collection. `CollectionMetadata` is
  created here with its full constructor, so the move task adds operations only.
- Delete: none.
- Create:
  - `src/huron/core/lake/metadata.py`: `STAGING_PREFIX`, `MAX_BULK_EDIT`, `MetadataEdit`, `EditOutcome` and
    `CollectionMetadata(store, catalogs, validation, volume, directories, metadata_file, clock)` with `publish`
    and `publish_many`, each authorizing first through DT-4, taking `at` from the clock once and appending its
    entries after the write that locked the row.
  - `tests/unit/test_lake_metadata.py`: DT-15's unit publish and bulk cases: T7 and T8 with the exact
    `meta_publish` entry (`version`, sorted `changes`, `reason`); an empty diff keeps the version, writes no entry
    and no `metadata.json`; an identity change is 422 `METADATA_INVALID` with one `frozen` problem per field; a
    draft is `COLLECTION_STATE`; a stale `If-Match` is 412 before the diff; `sync` after the commit, and a `sync`
    failure still answers the active view; bulk: one invalid member changes nothing and writes no entry;
    `missing`, draft and `stale` are each reported for the whole list in the contract's order; unchanged members
    keep their version; one entry per changed member; a top-level identity key in the patch is `frozen`.
  - `tests/unit/test_api_lake_metadata.py`: rows 34 and 10 rendered: the envelopes, `ETag` `"N+1"` and `"N"`
    for a no-op, the 404 `missing`, 409 and 412 `stale` contexts, and 422 `METADATA_INVALID` with
    `collection_id`.
- Modify:
  - `src/huron/core/lake/__init__.py`: the new public names.
  - `src/huron/applications/api/routes/lake/endpoints/collections.py`: `PUT /collections/{id}/metadata`
    (row 34, IM); `src/huron/applications/api/routes/lake/endpoints/catalogs.py`:
    `POST /catalogs/{catalog}/metadata-edits` (row 10); `routes/lake/schema/collections.py`: `MetadataPublish`;
    `routes/lake/schema/catalogs.py`: `MetadataEditItem`, `MetadataEdits` (bounded by `MAX_BULK_EDIT` imported
    from `huron.core.lake`), `MetadataEditOutcome`, `MetadataEditsResult`;
    `routes/lake/dependencies.py`: `collection_metadata()` and `CollectionMetadataDep`, built from
    `runtime.stores.lake`, `runtime.volume` and `runtime.directories` the way `collections()` builds
    `Collections`.
  - `tests/lake_store_contract.py` collections area: a publish racing a config publish keeps I-9 in both
    commit orders; two `sync`s racing two publishes end with the newer document (M11.10 handed it here).
  - `tests/unit/test_lake_routes.py` (the sweep grows by exactly two; ladder rows 10 and 34; row 34 in
    `test_etag_on_reads_and_if_match_on_writes`); `tests/unit/test_api_router_composition.py` and
    `tests/unit/test_execution_model.py` (the two operations).
  - `design/api.html` §3: rows 10 and 34; §7: the `METADATA_INVALID` row names the `frozen` rule (an identity
    field outside `mv`), first raised here.
- Design: "DT-15 design: Metadata publish and mv" → "DT-15 decisions" (Publish body, Identity frozen, Validation,
  Bulk edits, Reasons), "DT-15 route contracts" (`PUT …/metadata`, `POST …/metadata-edits`), "`huron.core.lake.metadata`:
  the operations" (`publish`, `publish_many`, invariants), "DT-15 the metadata diff recorded in audit `detail`
  (shape owned by DT-7)", "DT-15 tests this design requires" (unit publish and bulk; contract publish row);
  "DT-18 design: …" → "DT-18 route table" (rows 10, 34), "DT-18 request and response models", "DT-18 interfaces
  and contracts" → "Lake service dependencies"; "DT-9 design: …" → the serialization rule of "DT-9 interfaces
  and contracts"; "DT-26 design: …" → "DT-26 design record pages: the Raw-facing six" (`api.html` §3).
- Skills: `oop-design` (`core/lake`); `fastapi` (routes).
- Verification:
  - The plan-wide gate and `make docs`.
  - `uv run pytest tests/unit/test_lake_metadata.py tests/unit/test_api_lake_metadata.py tests/unit/test_lake_routes.py
    tests/unit/test_api_router_composition.py tests/unit/test_execution_model.py tests/unit/test_error_contract.py -q`
    passes; `metadata.py` and the modified route modules are at 100 % in the unit run.
  - In the background, polled: `uv run pytest -m contract tests/contract/test_lake_store.py`; the two race
    scenarios are named races.
  - `rg -n 'publish_metadata\(' src/huron --glob '!src/huron/core/metastore/**' --glob '!src/huron/core/lake/ports.py'`
    names only `src/huron/core/lake/metadata.py` (DT-15: the only caller).
- Dependencies: M16.1, M16.2; M11, M13.
- Decisions: OQ-15.1 (settled, owner decision 12)
- Status: pending

### M16.4 The staged move on the volume and `Directories.place_moved`

- Intent: give the `Volume` port the four methods DT-15 puts in place of `rename_collection`: a rename of the
  collection directory to a private dot-named staging entry in its catalog directory, a finish that creates the
  missing container levels and renames staging onto the committed path, a read-only listing of staging entries
  for the reconciler, and a container `rmdir` that `remove_collection` shares; and the `Directories` operation
  that gives newly created levels the container ACL, failing closed. The real-NFS proof of both renames joins
  `tests/linux/`.
- Delete: none (no `rename_collection` exists; DT-15 deletions are satisfied by its absence).
- Create: none.
- Modify:
  - `src/huron/core/lake/ports.py`: `Volume` gains `stage_move`, `finish_move`, `staged_moves` and
    `remove_containers`.
  - `src/huron/core/rawstore/volume.py`: `PosixVolume` implements them over the held descriptors (staging name
    `STAGING_PREFIX + str(collection_id)` built internally from `huron.core.lake.metadata`; parents `fsync`ed;
    DT-11's common error table; `ValueError` for the preconditions); `remove_collection`'s `containers` argument
    runs the same `remove_containers` routine.
  - `src/huron/core/lake/directories.py`: `Directories.place_moved(catalog, created)`.
  - `tests/unit/test_rawstore_volume.py`: DT-15's Volume row: `stage_move` refuses an existing target (an
    empty one included), a missing source and an existing staging entry, changing nothing; `finish_move` returns
    `None` with nothing staged, creates and returns missing levels at `0o700`, refuses an existing target;
    `staged_moves` lists only well-formed staging names; `remove_containers` ignores `ENOENT` and `ENOTEMPTY`
    and refuses a catalog-level path.
  - `tests/unit/test_lake_directories.py`: `place_moved` with `()` reads no mapping; created levels get the
    container access shortest first through `RecordingPermissions`; a repeat changes nothing; a
    `DependencyUnavailable` propagates with the levels already done left done.
  - `tests/linux/test_nfs_volume.py`: DT-15's cases on the loopback mount: `stage_move` and `finish_move` keep
    the collection's ACL; created levels carry the container ACL after `place_moved`; a writer holding an open
    partial keeps writing to the moved inode across both renames.
- Design: "DT-15 design: Metadata publish and mv" → "`lake/ports.py`: the `Volume` port, `rename_collection`
  replaced", "`lake/directories.py`: `Directories.place_moved` (DT-11 named it; its contract)", "DT-15 tests this
  design requires" (Volume and Linux-tier rows), "DT-15 deletions", "DT-15 open questions" (OQ-15.3); "DT-11
  design: …" → the common error table in "`lake/ports.py`: the `Volume` port", "DT-11 the access table"; "DT-23
  design: …" → "DT-23 placement of the handed-off tests" (DT-15 row).
- Skills: `oop-design` (`core/lake`, `core/rawstore`).
- Verification:
  - The plan-wide gate; `uv run lint-imports` keeps all 20 contracts (`rawstore → lake` is admitted).
  - `uv run pytest tests/unit/test_rawstore_volume.py tests/unit/test_lake_directories.py
    tests/unit/test_test_tiers.py -q` passes; `volume.py` and `directories.py` are at 100 % in the unit run.
  - `uv run pytest -m "stack or nfs" --collect-only -q` lists the new `test_nfs_volume.py` cases.
  - `rg -n 'rename_collection' src tests` prints nothing; `rg -n 'huron-mv-|STAGING_PREFIX' src/huron` prints
    lines only from `core/lake/metadata.py`, `core/lake/__init__.py` and `core/rawstore/volume.py`.
  - CI receipt: the `nfs` run containing the DT-15 cases, recorded by M19.5.
- Dependencies: M16.3; M11, M15.
- Decisions: OQ-15.3 (settled, owner decision 12)
- Decisions: OQ-11.1 (settled, owner decision 12)
- Status: pending

### M16.5 `mv`: `move`, `recover_move` and row 35

- Intent: move a settled collection to the placement its new identity values resolve to, under one catalog,
  with the UUID unchanged: stage, switch and finish, so that at no instant does its directory sit at an
  identifier no row holds, and recovery is the one idempotent action "put the staging directory where the
  committed row says", run after every `mv`, before every `mv` of the same collection, and later by the
  reconciler. A commit in flight is neither waited for nor failed. The design record gains §6 and §9.
- Delete: none.
- Create: none.
- Modify:
  - `src/huron/core/lake/metadata.py`: `MoveRecovery`; `CollectionMetadata.move` (DT-15's sequence: recover
    first; read and refuse; the transaction holding `lock_catalog`, `lock_layout`, `lock_collection`;
    `stage_move` inside it; `attach_namespace`, `relocate`, `prune_namespaces` and the `mv` entry; then
    `recover_move`, `place_moved`, `metadata_file.sync` and `remove_containers` deepest first; a database-only
    `mv` for an unchanged `Placement`; a no-op for an unchanged `set`) and `recover_move` (`NOTHING_STAGED`,
    `PLACED`, `BLOCKED`, `ORPHANED`, never deleting anything but a removable orphan at the target).
  - `tests/unit/test_lake_metadata.py`: DT-15's `mv` cases: T9 with the exact `mv` entry; directory,
    `metadata.json` and namespaces at the target afterwards; UUID, `catalog_id`, `config_version` and
    `file_count` unchanged; emptied source containers removed and shared ones kept; a database-only `mv`; a `set`
    naming a non-identity field is `not_identity`; a target held by a row is 409 with its id; a target directory
    present is 409 with `collection_id: null` and nothing changed; the recorded call order (stage inside the
    transaction; finish and `place_moved` after it). The fault matrix
    `test_move_converges_after_a_fault_at_each_step`, parametrized over steps 6–14 through `crash_on`
    (`tests/unit/support.py`) and `FaultingLakeStore`: the directory ends at the committed row's path in every
    case; `relocate` raising `CollectionExists` after the stage leaves it back at the source; an orphan at the
    target is removed and the move finished; non-removable content at the target is `BLOCKED` and stays staged;
    `recover_move` twice in a row and concurrently gives one `PLACED` and one `NOTHING_STAGED`.
  - `tests/unit/test_lake_commit_crash_matrix.py`: DT-14's C13 (an `mv` between the hash and the final
    transaction ends `succeeded` with stamps re-read at the target), a file opened while the directory is staged
    (transient, then `succeeded`) and a commit submitted with the pre-`mv` version (412).
  - `tests/lake_store_contract.py` collections area, Postgres-only: an `mv` racing an activation of its target
    identifier has exactly one winner and the loser's directory never holds the winner's files; an `mv` racing a
    `delete` of a collection sharing its source namespace keeps I-12.10.
  - `src/huron/applications/api/routes/lake/endpoints/collections.py`: `POST /collections/{id}/move` (row 35, IM;
    503 with `Retry-After: 30` when the volume refuses the stage; 200 when only the post-commit volume step was
    deferred); `routes/lake/schema/collections.py`: `MoveRequest`.
  - `tests/unit/test_api_lake_metadata.py` (row 35's renderings); `tests/unit/test_lake_routes.py` (the sweep
    grows by exactly one; ladder row 35 at Project Admin; row 35 in `test_etag_on_reads_and_if_match_on_writes`);
    `tests/unit/test_api_router_composition.py` and `tests/unit/test_execution_model.py`.
  - `design/api.html` §3: row 35; §7: the `METADATA_INVALID` row names the `not_identity` rule (`mv` names a
    non-identity field), first raised here, and so reaches DT-18's wording. `design/layer-raw.html`: §6
    Metadata publish and `mv` (`metadata`) and §9
    Recovery and lineage (`recovery`, linking ADR 0005, `layer-bronze.html` §1 and `AGENTS.md` B-8), which also
    resolves `layer-silver.html`'s `#recovery` link from M0.5.
- Design: "DT-15 design: Metadata publish and mv" → "DT-15 decisions" (`mv` scope, `mv` with an unchanged
  identifier, `mv` order, Recovery owner, `.part` files during `mv`, Commits in flight), "DT-15 route contracts"
  (`POST …/move`), "`huron.core.lake.metadata`: the operations" (`move`, `recover_move`, invariants), "DT-15 `mv`
  sequence and failure table", "DT-15 the rule for a commit in flight during `mv`, and staged CLI work", "DT-15
  tests this design requires", "DT-15 handoffs" (DT-14, DT-24 rows); "DT-14 design: …" → "DT-14 crash-matrix
  test plan" (C13); "DT-24 design: …" → "DT-24 invariants the lake keeps now" (P-1, P-2, P-7); "DT-18 design: …"
  → "DT-18 route table" (row 35); "DT-26 design: …" → "DT-26 design record pages: the Raw-facing six"
  (layer-raw §6, §9; `api.html` §3).
- Skills: `oop-design` (`core/lake`); `fastapi` (routes).
- Verification:
  - The plan-wide gate and `make docs`.
  - `uv run pytest tests/unit/test_lake_metadata.py tests/unit/test_lake_commit_crash_matrix.py
    tests/unit/test_api_lake_metadata.py tests/unit/test_lake_routes.py tests/unit/test_api_router_composition.py
    tests/unit/test_execution_model.py -q` passes, including every parametrized fault step and C13. A matrix or
    race failure is never re-run to green and stops the milestone (plan rule "Races").
  - In the background, polled: `uv run pytest -m contract tests/contract/test_lake_store.py`; `uv run pytest -m
    integration`.
  - `metadata.py` and the modified route modules are at 100 % in the unit run.
  - `rg -n 'relocate\(|lock_collections\(|stage_move\(|finish_move\(|remove_containers\(|place_moved\(' src/huron --glob '!src/huron/core/metastore/**' --glob '!src/huron/core/lake/ports.py' --glob '!src/huron/core/rawstore/**'`
    names only `core/lake/metadata.py` and `core/lake/directories.py` (the `place_moved` definition) at this
    commit (DT-15: `CollectionMetadata` is the only caller; M17.3's reconciler adds its `remove_containers` call
    under DT-16, the later section).
  - `rg -n 'rename_collection' src tests` prints nothing; `rg -n 'id="(metadata|recovery)"' design/layer-raw.html`
    prints two lines.
- Dependencies: M16.3, M16.4; M13, M15.
- Decisions: OQ-15.2 (settled, owner decision 12)
- Decisions: OQ-15.3 (settled, owner decision 12)
- Status: pending

## Milestone 17 — Reconciler

Spec build step 6 on the server. Revision `0018_lake_reconciler` lands with the two store halves that write its
tables and their contract tests; DT-16's `Volume` additions and the pure scan classifiers follow; then the
`Reconciler` (staged moves through M16's `recover_move`, per-collection walks with batch probes, the layout scan,
orphan removal, stale drafts and the access reset, mark-and-sweep findings) and `ReconciliationFindings`; the
CronJob entry point `python -m huron.applications.api.reconcile` with its settings and exit codes and route
row 37; and last the real-NFS cases, the nightly scale case and the pages that describe the reconciler. The
reconciler takes no `Actor`, writes no audit entry, and is constructed only in its entry point. `huron check` is
M18's.

### M17.1 Revision `0018_lake_reconciler` and the findings store halves

- Intent: store findings with an open/resolved lifecycle deduplicated by the open key, one status row per
  catalog, and the read side the reconciler walks by (catalog layouts, settled rows by identifier, batch file
  probes, pending commit paths, stale drafts), on PostgreSQL and in memory, with DT-17's DDL and downgrade
  guard. The finding vocabulary arrives here because the `code` CHECK and its drift tests need it.
- Delete: none.
- Create:
  - `migrations/versions/0018_lake_reconciler.py` (`down_revision = "0017_lake_commits"`): DT-17's DDL through
    `execute_sql`, the fourteen codes written literally, a module docstring naming the invariants; `downgrade()`
    calls `refuse_if_rows("lake.reconciliation_findings", "lake.reconciliation_status")` first, then drops in
    reverse order.
  - `src/huron/core/metastore/lake/findings.py`: `PostgresFindings` and `InMemoryFindings`, the halves for
    `ReconcileReads` and `FindingStore`: `observe` as the `ON CONFLICT … WHERE resolved_at IS NULL` upsert (at most
    500 per call), a repaired observation resolving the open row or inserting a resolved one, `finish` sweeping
    `cleared` except `unswept` and never for `ABORTED`, `prune_findings` bounded by `limit`, `finding_page`
    keyset by `id` with `limit + 1`; database time (`clock_timestamp()`) for `begin` and the seen/resolved
    stamps, the injected `Clock` in the fake; `files_at` refusing more than 1,000 paths; `pending_paths` over
    `lake.commits.request`.
  - `tests/contract/test_reconciliation_store.py` (marker `contract`, `postgres:16` through `tests.postgres`): the
    findings scenarios of `tests/lake_store_contract.py` plus the Postgres-only cases: R16-1's upsert with NULL
    `path` and NULL `collection_id`; two overlapping runs' sweeps keep each other's fresh rows; the catalog delete
    cascades both tables; the CHECKs (`code`, `resolution` iff `resolved_at`, `path` or `collection_id`, path
    length).
- Modify:
  - `src/huron/core/lake/types.py`: `FindingCode` (with `severity` and `repairable` from one `Final` mapping),
    `Severity`, `Resolution`, `CatalogOutcome` and `CatalogStatus`. DT-16 lists them among `lake/reconcile.py`'s
    values; they live here because the port-owned `Observation`, `FindingRecord` and `FindingStore.status`
    name them and `ports.py` cannot import the operation module that imports it.
  - `src/huron/core/lake/ports.py`: `CatalogLayout`, `Observation`, `FindingRecord`, `ReconcileReads` and
    `FindingStore`; `LakeStore` gains both Protocols. DT-16's `FindingStore.page` and `FindingStore.prune` are
    named `finding_page` and `prune_findings` (same signatures): on the composite `LakeStore` a bare verb
    carries its resource noun, as M13 already named DT-13's `FileStore.page` `file_page` and DT-14's
    `CommitQueue.prune` `prune_commits` (a design override the head records).
  - `src/huron/core/metastore/lake/store.py` and `memory.py`: compose the halves; `src/huron/core/lake/__init__.py`
    exports the new names.
  - `migrations/schema.sql`: the `lake` section gains both tables in the map's style (`-- [db]` notes for the
    open key, the fillfactor, the CHECKs and the cascade); `-- Reflects: 0018_lake_reconciler`.
  - `tests/lake_store_contract.py`: a findings area (dedup while open, a repaired observation, sweep scope and
    `unswept`, `ABORTED` sweeps nothing, `prune_findings` limit, `finding_page` paging with `has_more`, the five
    read methods), run by
    `tests/unit/test_lake_memory_store.py` and the new contract module.
  - `tests/unit/test_lake_ddl_sync.py`: the revision's code list equals `FindingCode` both ways; both tables
    appear in `schema.sql`'s `lake` section. `tests/contract/test_lake_roles.py`: the database CHECK's list
    equals `FindingCode` both ways. `tests/contract/test_lake_schema.py`: `test_upgrade_downgrade_round_trip`
    runs through `0018` and the downgrade refuses while either table holds a row;
    `test_nullable_key_uniqueness` gains the open-key half. `tests/unit/test_lake_types.py`: the severity
    mapping and the repairable set pinned.
- Design: "DT-16 design: Reconciler" → "DT-16 decisions" (Findings store, Resolution by sweep), "DT-16 the
  finding vocabulary", "DT-16 `lake.reconciliation_findings` and `lake.reconciliation_status`: logical shapes
  (DT-17 writes the DDL)", "`lake/ports.py`: `ReconcileReads` and `FindingStore`", "DT-16 tests this design
  requires" (contract row), "DT-16 handoffs" (DT-17 row); "DT-17 design: …" → "DT-17 revision list", "DT-17 DDL:
  `0018_lake_reconciler`", "DT-17 decisions" (Downgrade, Time), "DT-17 target module layout" (`findings.py`,
  which supersedes DT-16's `reconciliation.py` name), "DT-17 port → adapter → fake" (`ReconcileReads`,
  `FindingStore` row), "DT-17 the shared migrate helper and the tests", "DT-17 `migrations/schema.sql` and the
  import rules", "DT-17 resolved disagreements between sections" (D-4, D-5).
- Skills: `postgresql-table-design` (revision and adapter); `oop-design` (`lake/ports.py`, `lake/types.py`).
- Verification:
  - The plan-wide gate (`scripts/check_schema_map.py` sees the moved stamp).
  - `uv run pytest tests/unit/test_lake_memory_store.py tests/unit/test_lake_ddl_sync.py tests/unit/test_lake_types.py -q`
    passes.
  - In the background, polled: `uv run pytest -m contract tests/contract/test_reconciliation_store.py
    tests/contract/test_lake_roles.py tests/contract/test_lake_schema.py tests/contract/test_lake_store.py`; the
    overlapping-sweep case is a named race.
  - `src/huron/core/metastore/lake/findings.py` reaches 100 % in the "unit or contract" coverage run; any floor
    re-baseline follows the plan-wide rule.
  - `rg -n '^-- Reflects: 0018_lake_reconciler$' migrations/schema.sql` prints one line;
    `rg -nP 'FROM (?!lake\.)\w+|JOIN (?!lake\.)\w+' src/huron/core/metastore/lake` prints only CTE names.
  - `rg -n 'def (page|prune)\(' src/huron/core/lake/ports.py src/huron/core/metastore/lake` prints nothing, and
    `rg -n 'def (finding_page|prune_findings)\(' src/huron/core/lake/ports.py` prints two lines.
- Dependencies: M13, M16.
- Decisions: OQ-1.1 (settled, owner decision 12)
- Decisions: OQ-17.1 (settled, owner decision 12)
- Decisions: OQ-12.3 (settled, owner decision 12)
- Status: pending

### M17.2 `Volume` walk depth, `changed_at`, `metadata_matches` and the scan classifiers

- Intent: let the reconciler walk any catalog, container or collection with an optional depth bound and age
  entries by `max(changed_at, modified_at)`, compare `metadata.json` with its rendering without reading a file
  of the wrong size, and classify entries by pure rules (layout depth, partial patterns, non-conforming subtrees
  reported once at their top, drift reasons, grace periods, pending paths) that tests reach without a volume.
- Delete: none.
- Create:
  - `src/huron/core/lake/_impl/reconcile_scan.py` (no I/O): `classify_layout` and `ContentScan` (a `DiskEntry`
    stream in, batched probes of at most 1,000 conforming non-directory paths, findings and partials out).
  - `tests/unit/test_lake_reconcile_scan.py`: DT-16's pure row: depth below D is a container and depth D a
    collection; staging names skipped with their subtree; `check_segment` failures and files at container depth
    are `ENTRY_UNEXPECTED`; `x.<32 hex>.part` and the root `metadata.json.part` are partials while `x.part`,
    `x.<31 hex>.part` and `sub/metadata.json.part` are unexpected; `.git/` with three children is one
    `ENTRY_UNEXPECTED` with `entries_beneath: 3`; empty directories in walk order over R16-2's names; pending
    paths excluded; drift reasons (`size`, `modified` beyond the skew and not within it, `symlink`,
    `not_regular`); young entries skipped; a non-UTF-8 name rendered with backslash escapes and
    `undecodable: true`.
- Modify:
  - `src/huron/core/lake/ports.py`: `DiskEntry.changed_at`; `Volume.walk(root, *, max_depth=None)`;
    `Volume.metadata_matches(collection, document)`.
  - `src/huron/core/rawstore/volume.py`: `PosixVolume` implements the three (`changed_at` from the same `lstat`
    as `modified_at`; `max_depth < 1` is `ValueError`; a 503 raised at the failing directory with the entries
    already yielded valid; `metadata_matches` opens with `O_NOFOLLOW` and decides a different size from `fstat`
    without reading). Every existing `walk` caller keeps its behaviour.
  - `tests/unit/test_rawstore_volume.py`: `walk` from a catalog, a container and a collection root; `max_depth`
    stops descent; an unreadable directory (monkeypatched `os.open` raising `PermissionError`, the M11.3 pattern,
    no root skip) raises after the earlier entries; `changed_at` set; `metadata_matches` true for equal bytes and
    false for a missing file, a symlink, a directory and a different size (a monkeypatched `os.read` fails if
    called), and `directory_missing` for an absent collection.
- Design: "DT-16 design: Reconciler" → "`lake/ports.py`: additions to DT-11's `Volume`", "DT-16 the finding
  vocabulary" (conditions and exclusions), "DT-16 decisions" (Walk shape, G-28, Age, Drift), "`lake/reconcile.py`:
  `Reconciler`" (steps 4–5, the classification parts), "DT-16 tests this design requires" (pure row), "DT-16
  handoffs" (DT-11, DT-13 rows); "DT-13 design: …" → the partial-name rule and `check_rel_path`; "DT-8 design:
  …" → the segment rule and reserved names.
- Skills: `oop-design` (`core/lake`, `core/rawstore`).
- Verification:
  - The plan-wide gate; `uv run lint-imports` keeps all 20 contracts (the new module is private to `lake`,
    contract 16).
  - `uv run pytest tests/unit/test_lake_reconcile_scan.py tests/unit/test_rawstore_volume.py
    tests/unit/test_lake_collections.py tests/unit/test_lake_directories.py -q` passes; `reconcile_scan.py`,
    `ports.py` and `volume.py` are at 100 % in the unit run.
  - `rg -n '^\s*(import|from) ' src/huron/core/lake/_impl/reconcile_scan.py` shows no `os`, `pathlib` I/O or
    `rawstore` import.
- Dependencies: M17.1; M11, M13.
- Status: pending

### M17.3 `Reconciler` and `ReconciliationFindings`

- Intent: one idempotent pass per catalog under deployment authority: recover staged moves first, walk each
  settled collection and probe its rows in batches, run the row pass only when counts or the version disagree,
  re-sync `metadata.json`, scan the layout, remove orphans holding only removable entries and empty orphan
  containers, list stale drafts, reset access last, then sweep what was not seen; `--report-only` changes
  nothing on the volume. A Project Admin reads the findings and the catalog's freshness through one paged read.
- Delete: none.
- Create:
  - `src/huron/core/lake/reconcile.py`: `ReconcilePolicy` (with its `__post_init__` bounds), `CatalogReport`,
    `RunReport` (`ok`), `FindingView`, `FindingsPage`, `Reconciler(reads, collections, files, findings, volume,
    directories, metadata_file, moves, clock, policy)` with `run(catalogs=(), *, repair=True)` following DT-16's
    steps 0–9 and invariants, and `ReconciliationFindings(catalogs, findings)` with `page(actor, catalog, *,
    open_only, after, limit)` (Project Admin on the catalog first; `limit` 1..500). It writes the structured
    records `lake.reconcile.repaired` before each `observe` batch and `lake.reconcile.catalog` per catalog.
    Where DT-16's steps write `files.page(…)` and `findings.prune(…)`, the code calls `files.file_page` (M13)
    and `findings.prune_findings` (M17.1); `ReconciliationFindings.page` keeps its name (an operation, not a
    `LakeStore` method) and reads `findings.finding_page`.
  - `tests/unit/test_lake_reconcile.py` (`PosixVolume` on `tmp_path` with `marker_only`, `RecordingPermissions`,
    the in-memory store, a fixed `Clock` moved forward for ages): DT-16's `tmp_path` and "idempotency and sweep"
    rows. `.snapshot` copies are made with `tests.fakes.ontap_volume.take_snapshot` at the catalog root, a
    collection root and a subdirectory, each holding a `.part` and a dot-file, and yield no finding (DT-23's
    handoff replaces DT-16's `copytree` fixtures). An unreadable subdirectory is made by a monkeypatched `os.open`
    raising `PermissionError` (no root skip): `ENTRY_UNREADABLE`, outcome `partial`, and that collection's earlier
    findings stay open. A volume-wide 503 mid-catalog: `ABORTED`, nothing swept, the remaining catalogs skipped.
    Two runs over an unchanged tree: zero repairs in the second, the same open ids and `first_seen_at`.
    `repair=False`: the tree byte-identical before and after, repairs open with `repair: pending`, then resolved
    `repaired` by a repairing run. `ReconciliationFindings.page`: Project Admin 200 with `status`; Developer 403;
    no role 404; `open_only=False` pages resolved rows; `limit` 501 raises `ValueError`.
- Modify:
  - `src/huron/core/lake/__init__.py`: the new public names.
  - `tests/lake_faults.py`: the store fault hooks the row-pass and orphan cases need (a version change between
    the walk and the re-read; `settled_at` turning non-`None` at the re-check), if `FaultingLakeStore` cannot
    express them already.
- Design: "DT-16 design: Reconciler" → "DT-16 decisions" (Authority inside the code, Repairs, Resolution by sweep,
  Walk shape, `--report-only`), "DT-16 the finding vocabulary", "`lake/reconcile.py`: values", "`lake/reconcile.py`:
  `Reconciler`", "`lake/reconcile.py`: `ReconciliationFindings` and the route `huron check` reads", "Scale",
  "DT-16 tests this design requires" (`tmp_path`, idempotency and sweep rows), "DT-16 data flow", "DT-16
  handoffs" (DT-12, DT-13, DT-14 rows); "DT-15 design: …" → "DT-15 handoffs" (DT-16 row); "DT-7 design: …" →
  "DT-7 decisions" (What is not audited); "DT-23 design: …" → "DT-23 handoffs" (DT-16 row).
- Skills: `oop-design`.
- Verification:
  - The plan-wide gate.
  - `uv run pytest tests/unit/test_lake_reconcile.py tests/unit/test_lake_reconcile_scan.py -q` passes;
    `reconcile.py` is at 100 % in the unit run.
  - `rg -n 'append_audit|Actor' src/huron/core/lake/reconcile.py` shows `Actor` only on its import line and in
    `ReconciliationFindings.page`'s signature, and no `append_audit` (no audit; no actor for the run).
  - `rg -n 'Reconciler\(' src/huron` prints nothing outside `lake/reconcile.py` (the entry point arrives in
    M17.4).
- Dependencies: M17.1, M17.2; M16.
- Decisions: OQ-11.3 (settled, owner decision 12)
- Decisions: OQ-12.2 (settled, owner decision 12)
- Decisions: OQ-12.3 (settled, owner decision 12)
- Decisions: OQ-16.1 (settled, owner decision 12)
- Status: pending

### M17.4 The CronJob entry point, its settings and row 37

- Intent: run the reconciler as a separate process from the API image with the API pods' settings, store and
  volume wiring and no HTTP app or lifespan worker, exiting 0, 1, 2 or 3 as OpenShift's alerting hook; and serve
  the one Project-Admin read `huron check` uses, completing DT-18's route table (34 lake routes behind
  `current_actor`, 21 tags).
- Delete: none.
- Create:
  - `src/huron/applications/api/reconcile.py`: `main(argv=None) -> int` (`--catalog NAME` repeatable,
    `--report-only`, parsed before anything else; `ApiSettings()` from the environment; the pool, `PosixVolume`, the configured
    `DirectoryPermissions` and the lake store root through the lifespan's own composition functions;
    `Directories`, `MetadataFile`, `CollectionMetadata` and `Reconciler` with `ReconcilePolicy` from
    `LakeSettings`; `asyncio.run`; everything closed in `finally`) and the `__main__` guard.
  - `src/huron/applications/api/routes/lake/endpoints/reconciliation.py`: `GET /reconciliation/findings`
    (row 37; `catalog` required, `state=open|all`, `after`, `limit` capped at 200);
    `src/huron/applications/api/routes/lake/schema/reconciliation.py`: `ReconcileStatusBody`, `FindingBody`,
    `FindingsPage` (`from_view`).
  - `tests/unit/test_api_reconcile_main.py`: exit 2 on an unknown `--catalog` with no status row written and on
    a bad argument; exit 3 when the marker is missing; exit 0 on a clean tree; exit 1 when a catalog aborts;
    `--report-only` leaves the tree byte-identical; no lifespan worker factory is called; the `__main__` guard
    through `runpy.run_module(…, run_name="__main__")`.
  - `tests/unit/test_api_lake_reconciliation.py`: DT-16's route row (Project Admin 200 with `status`, Developer
    403, no role 404, `state=all` pages resolved rows); `limit=201` is 422 (DT-18's 200 cap supersedes DT-16's
    `limit 501` example).
- Modify:
  - `src/huron/applications/api/settings.py`: `LakeSettings` gains the six `reconcile_*` fields with DT-18's
    bounds; `tests/unit/test_api_settings.py`: each bound refused once and the boundary that passes.
  - `src/huron/applications/api/app.py`: the store and volume wiring `reconcile.main` reuses becomes callable from
    it (made public where needed, every reference updated in the same change); nothing is copied (DT-16
    "Composition").
  - `src/huron/applications/api/routes/lake/dependencies.py`: `findings()` and its alias;
    `routes/lake/__init__.py` includes the router; `routes/pagination.py`: the `findings` listing
    (`("findings", state, str(id))`).
  - `tests/unit/test_lake_routes.py`: the anonymous sweep asserts exactly 34 members; ladder row 37; the sentinel
    equals the derived lake route set. `tests/unit/test_api_router_composition.py`: the 21-tag set including
    `reconciliation`. `tests/unit/test_execution_model.py`; `tests/unit/test_api_pagination.py` (the findings
    cursor; a cursor of another listing is 400 `INVALID_CURSOR`).
  - `design/api.html` §3: row 37, which completes the 37-row table.
- Design: "DT-16 design: Reconciler" → "`applications/api/reconcile.py`: the job entry point" (Composition, What it
  does not start, Exit codes, Logging, Authority, Settings), "`lake/reconcile.py`: `ReconciliationFindings` and
  the route `huron check` reads", "DT-16 tests this design requires" (`test_api_reconcile_main.py` and route
  rows), "DT-16 open questions" (OQ-16.1, OQ-16.2); "DT-18 design: …" → "DT-18 route table" (row 37), "DT-18
  request and response models" (`reconciliation.py`), "DT-18 paging keys and the `label` filter" (findings row),
  "DT-18 settings: the merged `ApiSettings` diff" (`reconcile_*`), "DT-18 tests this design requires", "DT-18
  handoffs" (DT-16 row); "DT-26 design: …" → "DT-26 design record pages: the Raw-facing six" (`api.html` §3).
- Skills: `fastapi` (`applications/api`).
- Verification:
  - The plan-wide gate and `make docs`.
  - `uv run pytest tests/unit/test_api_reconcile_main.py tests/unit/test_api_lake_reconciliation.py
    tests/unit/test_api_settings.py tests/unit/test_lake_routes.py tests/unit/test_api_router_composition.py
    tests/unit/test_execution_model.py tests/unit/test_api_pagination.py tests/unit/test_api_app.py -q` passes;
    every created or modified `src/` file is at 100 % in the unit run.
  - `rg -n 'Reconciler\(' src/huron` names only `applications/api/reconcile.py`;
    `rg -n 'reconciliation/runs|--repair' src` prints nothing.
  - `uv run python -m huron.applications.api.reconcile --bogus; test $? -eq 2` exits 0 without touching a
    database.
- Dependencies: M17.3; M9, M11, M13.
- Decisions: OQ-16.1 (settled, owner decision 12)
- Decisions: OQ-16.2 (settled, owner decision 12)
- Status: pending

### M17.5 The reconciler on NFS, the nightly scale case and its pages

- Intent: prove on the loopback mount that a stripped ACE isolates one collection and that the reset repairs
  access, measure entries per second on a large tree every night for the runbook's sizing rule, and land the
  design-record and operator text that the reconciler now makes true.
- Delete: none.
- Create:
  - `tests/linux/test_reconciler_scale.py` (`pytestmark = [pytest.mark.nfs, pytest.mark.acceptance]`): 500
    collections × 100 files on the mount; one `Reconciler.run` with `Nfs4AclPermissions`; entries per second for
    the scan and for the reset written as `{"entries", "scan_eps", "reset_eps", "mount": "nfs4"}` to
    `$RUNNER_TEMP/reconciler-scale.json` (else `tmp_path`); it asserts completion only.
- Modify:
  - `tests/linux/test_nfs_volume.py`: DT-16's cases: Huron's ACE is removed from a file `lake-dev` created
    (written in-process with `encode_acl` while the inherited ACE still allows it; the ACL left is the one an
    owner's edit leaves, OQ-11.4), giving
    `ENTRY_UNREADABLE` for that collection while the catalog finishes `partial`, and an open `ACCESS_DRIFT` with
    `count`; a reset after a mapping change, then `run_as("lake-reader")` gets `EACCES` on write.
  - `.github/workflows/nightly.yml` `nfs-large`: the `if: always()` step
    `cat "${RUNNER_TEMP}/reconciler-scale.json" >> "$GITHUB_STEP_SUMMARY"` before `loopback_nfs.sh down`.
  - `design/layer-raw.html`: §10 Reconciler (`reconciler`), linking ADR 0007 and the runbook.
    `design/api.html` and `design/catalog-search.html`: every `layer-raw.html#sweeper` link becomes
    `layer-raw.html#reconciler`; `catalog-search.html` §3–§5's Raw-revision lineage examples become pins
    (`layer-bronze.html` §1).
  - `docs/raw-lake/operations.md`: §5 The reconciler (the CronJob manifest from DT-16, the first run with
    `--report-only`, reading `lake.reconciliation_status`, `kubectl create job --from=cronjob/huron-reconcile
    <name>` for on-demand runs, exit codes 1, 2 and 3 as alerts, the 39,600 s sizing rule over the nightly
    `reconciler-scale.json`, restoring `FILE_MISSING` and `FILE_DRIFT` from `.snapshot` by CLI guide §8); §6's
    findings row (`reconcile_finding_retention_days`, 90).
  - `docs/getting-started/testing.md`: the reconciler's entries per second are read from the nightly
    `nfs-large` job summary.
- Design: "DT-16 design: Reconciler" → "DT-16 tests this design requires" (Linux-tier row), "Scale", "DT-16
  handoffs" (DT-23, DT-26 rows), "`applications/api/reconcile.py`: the job entry point" (CronJob manifest);
  "DT-23 design: …" → "DT-23 placement of the handed-off tests" (DT-16 rows), "DT-23 CI workflow job outlines"
  (`nfs-large`); "DT-26 design: …" → "DT-26 design record pages: the Raw-facing six" (layer-raw §10,
  `catalog-search.html` §3–§5), "DT-26 the two new pages" (`operations.md` §5, §6), "DT-26 broken links and their
  fixes" (`#sweeper` rows), "DT-26 decisions" (Reconciler threshold).
- Verification:
  - The plan-wide gate, `make docs` and `git diff --check`.
  - `uv run pytest -m "stack or nfs" --collect-only -q` lists the new `test_nfs_volume.py` cases and
    `test_reconciler_scale.py`; `uv run pytest -m "nfs and not acceptance" --collect-only -q` omits the scale
    case; `uv run pytest tests/unit/test_test_tiers.py -q` passes.
  - `rg -n 'layer-raw.html#sweeper' design docs` prints nothing; `rg -n 'id="reconciler"' design/layer-raw.html`
    prints one line; `rg -n --glob '!docs/adr/**' -e '--repair' docs design/layer-raw.html` prints nothing
    (ADR 0007, from M0.3, records the flag's removal and keeps the words).
  - `uv run python -c "import yaml; s = str(yaml.safe_load(open('.github/workflows/nightly.yml'))['jobs']['nfs-large']['steps']); assert 'reconciler-scale.json' in s, s"`
    exits 0.
  - CI receipts: the `nfs` run with the DT-16 cases and two green `nfs-large` runs with the summary, recorded by
    M19.5.
- Dependencies: M17.3, M17.4; M15.
- Decisions: OQ-11.1 (settled, owner decision 12)
- Decisions: OQ-16.2 (settled, owner decision 12)
- Decisions: OQ-16.3 (settled, owner decision 12)
- Status: pending

## Milestone 18 — CLI metadata editing, `mv`, log and check

Spec build steps 5 and 6 on the client, against M16's rows 10 and 34–36 and M17's row 37. `meta update`
stages edits in `metadata.json` through the walkthrough's checkout sink, and `push` publishes them last
through `sync.publish_metadata`, the only sender of row 34 (OQ-20.4 (a)). On a 412, `publish_metadata`
pulls and rebases, then resends once. `meta bulk-update` previews the merge patch per collection with
the shared `apply_merge_patch` before one all-or-nothing post. `mv` previews the new path, then refreshes
any local copy so staged work survives. `log` and `describe collection`'s last change read the audit route.
`check` reports freshness, open findings, Incomplete collections and this machine's unfinished pushes,
and has no `--repair`. The milestone completes CLI guide §7 and §9 and flips RL steps 5 and 6.

### M18.1 Metadata publish, `meta update` and push's publish step

- Intent: staged metadata (OQ-20.4 (a)). `meta update` edits the checkout's `metadata.json` per answer
  through `CheckoutSink`, while identity fields stay `mv`'s. `publish_metadata` validates locally with
  the collection's pinned validator, sends the full pulled document with `If-Match`, and rebases on 412.
  `push` gains its last step S9 and the metadata-only route, so a metadata change is published also when
  nothing else is staged.
- Delete: none.
- Create: none.
- Modify:
  - `src/huron/applications/cli/sync.py`: `PublishOutcome` and `publish_metadata`.
    - With no metadata change it sends nothing.
    - It validates locally first, with row 30's validator through the schema cache. Problems raise
      `CliError` (exit 1), list each problem, and send nothing.
    - It sends `PUT …/metadata` with `{"metadata": <full document>, "reason"}` and
      `If-Match: base.collection_version`. A 200 saves `base.metadata = metadata = body.metadata` and the
      new version.
    - A 412 pulls with rebase and resends once; a second 412 exits 6, and a rebase conflict exits 6 with
      the conflicts listed.
    - A transport error with an unknown outcome re-reads row 28. If the server's metadata equals the local
      document, the publish counts as done; otherwise it resends once with the version read.
    - 422 `METADATA_INVALID` exits 1, and 409 `COLLECTION_STATE` exits 6.
  - `src/huron/applications/cli/walkthrough.py`: `CheckoutSink` replaces `metadata.json` through
    `Checkout.save` under the exclusive lock. Update mode is put to use: non-identity fields only,
    `Summary.changes`, and the finish action "keep".
  - `src/huron/applications/cli/commands/meta.py`: `meta update [-c] [-f] [--set]… [--no-input]`.
    - It reads row 6 and row 30, the latter through the schema cache, and resolves `-c` locally.
    - An identity field in `--set` or `-f` exits 2 ("use huron mv").
    - Problems under `--no-input` write nothing and exit 1.
    - stderr shows the summary with its changes.
  - `src/huron/applications/cli/push.py`: S1 routes a metadata-only change to S9. S9 calls
    `publish_metadata(reason=-m)` after S8, and `PushResult.metadata_published` reports it.
  - `tests/unit/cli/test_cli_sync.py`: the `publish_metadata` cases.
    - A no-op makes no request; a 200 saves.
    - `test_publish_412_rebases_and_resends_once`, and a second 412 exits 6.
    - `test_lost_publish_response_with_equal_metadata_is_success`.
    - Local problems send nothing.
  - `tests/unit/cli/test_cli_walkthrough.py`: update mode with `CheckoutSink`, with `metadata.json` written
    per answer.
  - `tests/unit/cli/test_cli_meta.py`: `meta update` refuses identity fields and writes nothing when there
    are problems.
  - `tests/unit/cli/test_cli_push.py`:
    - The happy path now asserts that metadata is published last with `If-Match: result.version`.
    - A metadata-only push makes no probe and no commit.
    - `test_push_killed_during_publish_republishes_on_rerun`.
    - `diff` shows the change after `meta update` and nothing after `push`.
  - `docs/raw-lake/cli.md` §7: the lines for `meta update`, publishing by `push`, and `diff`.
- Design: DT-20 decisions ("Staged metadata", "Pull, rebase and conflicts"); DT-20 interfaces and
  contracts → "`sync.py`: pull, rebase and publish" (`publish_metadata`), "`walkthrough.py`" (`CheckoutSink`,
  update mode); DT-20 command signatures, routes and exit codes (`meta update`); DT-20 data flow: create,
  stage, publish; DT-20 open questions (OQ-20.4); DT-20 handoffs (DT-21 row: `push` ends with
  `publish_metadata`); DT-21 the push algorithm (S1, S9); DT-15 handoffs (DT-20 row: the full pulled
  document with `If-Match`, rebase on 412); DT-18 route table (rows 28, 30, 34); DT-26 the two new pages
  (§7).
- Verification:
  - The plan-wide gate. `uv run pytest tests/unit/cli -q` passes, including the named tests and the full
    crash matrix (plan rule "Races").
  - `rg -n "/metadata\"|/metadata'" src/huron/applications/cli` prints only `sync.py`: one sender of row 34.
  - `make docs` passes. Every modified file is at 100 % line coverage.
- Dependencies: M14.4; M16.
- Decisions: OQ-20.4 (settled, owner decision 12)
- Status: pending

### M18.2 `meta bulk-update` and `mv`

- Intent: the two Project Admin metadata verbs. `meta bulk-update` turns a `get collections -o json`
  listing into one row-10 request; it previews each collection's change through the shared
  `apply_merge_patch` (OQ-20.1 (a)) and never chunks, because the route is all or nothing (OQ-15.1 (a)).
  `mv` changes identity fields only: it previews the new path with `place`, sends row 35 with `If-Match`
  from a fresh read, and refreshes the local copy so staged work survives. This task also adds push's
  concurrent-`mv` case, where the bytes follow the directory descriptor (OQ-15.2 (a)).
- Delete: none.
- Create: none.
- Modify:
  - `src/huron/applications/cli/commands/meta.py`: `meta bulk-update -f/--from LISTING [--set]… [--patch FILE]
    [-m] [--yes]`, a **confirm** verb.
    - Usage errors (exit 2): an empty or mixed-catalog listing; neither or both of `--set` and `--patch`;
      an identity field in the patch.
    - The patch: `--set` pairs become one merge-patch object, each value parsed through `AnswerKind`
      against the catalog's current schema (row 7, through the cache); `--patch` takes an RFC 7396
      document instead.
    - Preview: row 6 once per distinct `config_version`, then `apply_merge_patch` from
      `huron.schema.metadata` and `field_changes` for each collection.
    - The request is row 10 with `{"collections": [{id, version}], "patch", "reason"}`. The output lists
      `IDENTIFIER`, `VERSION` and `CHANGED` from `MetadataEditsResult`.
    - Answers: 412 lists the stale ids ("re-list and retry") and exits 6; 409 `COLLECTION_STATE` exits 6;
      422 `METADATA_INVALID` exits 1; 422 `REQUEST_INVALID` above `MAX_BULK_EDIT` exits 2.
  - `src/huron/applications/cli/commands/collections.py`: `mv PATH|ID --set f=v… [-m] [--yes]`, a **confirm**
    verb.
    - Requests: R, a fresh row 28, and row 6 for the pinned config. A key that is not an identity field
      of that config exits 2. A local `place` problem exits 1.
    - stderr shows "<old> → <new>" before confirming. Row 35 then gets `{"set", "reason"}` with `If-Match`
      from the fresh read.
    - Outcomes: a no-op exits 0. A lost response whose re-read shows the target identifier is success; a
      412 otherwise exits 6. 409 `COLLECTION_EXISTS` and `COLLECTION_STATE` exit 6; 422 exits 1; 503
      `volume` exits 7.
    - After success, `Config.collection.identifier` is updated when it was this collection, an existing
      local copy is pulled, and the new mount path is printed.
  - `src/huron/applications/cli/commands/__init__.py`: registers `mv`.
  - `tests/unit/cli/test_cli_meta.py`: `bulk-update` — the preview equals each collection's `field_changes`;
    `test_bulk_update_412_lists_the_stale_ids`; mixed catalogs and identity fields are refused; below
    Project Admin exits 5.
  - `tests/unit/cli/test_cli_collections.py`: `mv` — the preview, a no-op,
    `test_mv_lost_response_showing_the_target_is_success`,
    `test_mv_refreshes_the_local_copy_and_staged_work_survives`, a non-identity key exiting 2, and below
    Project Admin exiting 5.
  - `tests/unit/cli/test_cli_push.py`: `test_concurrent_mv_bytes_follow_the_descriptor` (X9's `mv` variant). An `mv` through
    the API between placement and the POST makes push resubmit, and the rows land at the new path.
  - `docs/raw-lake/cli.md` §7: the lines for `meta bulk-update` and `mv`.
- Design: DT-20 command signatures, routes and exit codes (`mv`, `meta bulk-update`, and the verb rules for
  `mv` and `meta bulk-update`); DT-20 open questions (OQ-20.1); DT-15 handoffs (DT-20 and DT-21 rows); DT-21
  failure table (X9); DT-18 route table (rows 6, 7, 10, 28, 35); DT-12 and DT-17 handoffs under OQ-20.1
  (`apply_merge_patch` in `huron.schema.metadata`, landed in M11); DT-26 the two new pages (§7).
- Verification:
  - The plan-wide gate. `uv run pytest tests/unit/cli -q` passes, including the named tests.
  - `rg -n "def apply_merge_patch" src` prints only `src/huron/schema/metadata.py`: the CLI holds no copy.
  - `uv run huron --help` lists `mv`.
  - `make docs` passes. Every modified file is at 100 % line coverage.
- Dependencies: M18.1.
- Decisions: OQ-15.1 (settled, owner decision 12)
- Decisions: OQ-15.2 (settled, owner decision 12)
- Decisions: OQ-20.1 (settled, owner decision 12)
- Status: pending

### M18.3 `log`, `describe`'s last change and `check`

- Intent: the read side of steps 5 and 6. `huron log` pages row 36, newest first, up to `--limit`, and
  `describe collection` gains its last change from the same route. `huron check` makes DT-16's two reads
  per catalog, adds DT-21's "pushes in progress on this machine", and exits 1 when anything is open; there
  is no `--repair` (OQ-16.2). This task finishes RL steps 5 and 6.
- Delete: none.
- Create: none.
- Modify:
  - `src/huron/applications/cli/commands/collections.py`:
    - `log [PATH|ID] [-n/--limit] [-o]`: R, then row 36 paged until `--limit`.
      - Columns: `AT`, `ACTOR`, `ACTION`, `SUMMARY` and `REASON`; wide adds `ID` and `OBJECT`.
      - `SUMMARY` comes from `detail`: the `rel_path`, the `from → to` identifier, or the changed pointers.
      - JSON and YAML print the items verbatim.
    - `check [--catalog] [-o]`: per catalog, row 37 (paged) and row 24 with `state=incomplete` (paged).
      With neither `--catalog` nor a current catalog, it reads row 4 first and repeats both per catalog.
      Row 37 is read through M14.1's `HuronClient.page_bodies`: `status` comes from the first page body
      (`FindingsPage.status`) and the findings from every body's `items`; no second paging loop.
      - Freshness: "never reconciled" for a null status. A warning when `finished_at` is more than 48 h
        old by `Services.clock`, or `outcome` is not `complete`.
      - Findings are grouped `error`, `warning`, `info`, followed by the Incomplete collections.
      - The group "pushes in progress on this machine" comes from `push.pending_pushes(state)`: identifier,
        phase, placed/total, commit id.
      - A 403 or 404 on row 37 is a stderr note ("findings need Project Admin on <c>", OQ-16.1 (a)), not
        a failure.
      - JSON and YAML print `{"catalogs": [<DT-20's per-catalog items>], "pending_pushes": [...]}`.
        DT-21's handoff puts `pending_pushes` "beside the per-catalog items" of DT-20's array, which an
        array cannot carry, so the plan wraps the two lists in one object.
      - Exit codes: 0 when nothing is open, nothing is Incomplete and no push is pending; 1 otherwise; 2;
        4 for a named catalog.
  - `src/huron/applications/cli/commands/browse.py`: `describe collection` reads row 36 with `limit=1` and
    shows the last change (action, actor, at, reason). JSON and YAML become
    `{"collection": CollectionBody, "last_change": AuditEntryBody | null}`.
  - `src/huron/applications/cli/commands/__init__.py`: registers `log` and `check`.
  - `tests/unit/cli/test_cli_collections.py`:
    - `log` paging across pages up to `--limit`, and `SUMMARY` for `add`, `mv` and `meta_publish`.
    - `test_log_shows_one_entry_per_accepted_write_and_none_for_a_no_op`.
    - `check` exits 0 when clean, and exits 1 for each of: an open finding (from a run of M17's
      `Reconciler` over the `tmp_path` volume after an unrecorded file is placed), an Incomplete collection,
      and a pending push.
    - The Reader note; the "never reconciled" line; the freshness warning after the clock advances 49 h.
    - `test_check_has_no_repair_option` (`huron check --repair` exits 2).
  - `tests/unit/cli/test_cli_browse.py`: `describe` with `last_change` after a metadata publish.
  - `docs/raw-lake/cli.md`: the §7 `log` line, which completes §7, and §9 Check a catalog (freshness,
    findings by severity, Incomplete collections, pushes in progress on this machine).
  - `design/roadmap.html`: the RL step 5 and step 6 tags become `done`.
- Design: DT-20 command signatures, routes and exit codes (`log`, `check`); DT-19 command signatures and exit
  codes (`describe collection`); DT-21 decisions ("`huron check` (client side)"); DT-21 handoffs (DT-20
  row); DT-16 (the `huron check` paragraph: two reads, freshness; and its DT-20 handoff); DT-7 (`GET
  /api/v1/collections/{id}/log` and its reader, via M16); DT-18 route table (rows 4, 24, 36, 37;
  `FindingsPage.status`, read through M14.1's `page_bodies`) and handoffs (DT-20 row); DT-26 the two new pages (§7, §9); DT-26 roadmap rows (RL steps 5 and 6).
- Verification:
  - The plan-wide gate. `uv run pytest tests/unit/cli -q` passes, including the named tests.
  - `rg -n "repair" src/huron/applications/cli` prints nothing.
  - `uv run huron --help` lists every top-level verb of DT-19, DT-20 and DT-21 and no `ls` or `draft`;
    `uv run huron catalog --help` lists exactly `use`, `show` and `apply`.
  - RL step 5's audit gates are M16's tests and step 6's reconciler gates are M17's (the nightly scale
    receipt is checked in M19). This task adds the CLI's `log` case above.
  - `make docs` and `git diff --check` pass. Every modified file is at 100 % line coverage.
- Dependencies: M18.2; M17.
- Decisions: OQ-16.1 (settled, owner decision 12)
- Decisions: OQ-16.2 (settled, owner decision 12)
- Status: pending

## Milestone 19 — Closing documentation, verification and merge

The plan's last five tasks. M19.1 completes the two environment-tier tests with the step-5 verbs that M16 and
M18 made available. T-docs-Z follows in two tasks: the overview pages, `auth.html` §7 and the roadmap; then the
developer docs, the runbook's staging section, the navigation group, the dated atlases with `rawstore-uml`
retired, B-1 removed, and `scripts/check_design_links.py` added to `make docs` and to CI's `lint` job, after
the link fixes, so its first run is green (OQ-26.1). M19.4 verifies the end state on the local tree (DT-24's
closing check, the lineage and documentation closing checks, every earlier closing check, the coverage
re-measure). M19.5 is the only task that pushes: it opens the pull request, records the CI receipts every
`stack`, `nfs` and `large-file` task deferred to it, waits for two green nightly runs, and merges into `main`
with a merge commit, which keeps the `f1c44e3` P3 pins reachable (DT-25 D-2). Nothing in DT-24's "explicitly
not built in this plan" list is created by any task; M19.4's closing check proves it.

### M19.1 Stack and large-file tests: the step-5 assertions

- Intent: finish DT-23's two test outlines with the clauses that need row 34, row 36 and M18's verbs: the stack
  test's log check and its Reader refusal, which is owner decision 7's per-request re-mapping through the real
  groups fake, and the large-file test's log check.
- Delete: none.
- Create: none.
- Modify:
  - `tests/stack/test_stack_push.py`: step 3 gains "`huron log` on the collection shows exactly the entries of
    one commit (two `add` entries)"; step 4: `rita` stages a descriptive edit with `huron meta update` and her
    `huron push` exits with DT-19's permission exit code (5), while her `huron get collections` and
    `huron describe collection` on it succeed.
  - `tests/acceptance/test_push_large_file.py`: step 7 gains "`huron log` lists exactly one `add` entry, naming
    `big.bin`".
- Design: "DT-23 design: …" → "DT-23 placement of the handed-off tests" (the stack outline, steps 3–4), "DT-23 the
  large-file acceptance test" (step 7); "DT-7 design: …" → "DT-7 decisions" (Collection log contents); "DT-19
  design: …" → the exit-code table.
- Verification:
  - The plan-wide gate.
  - `uv run pytest -m "stack or nfs" --collect-only -q` and `uv run pytest -m "acceptance and not nfs"
    --collect-only -q` collect the changed tests; `uv run pytest tests/unit/test_test_tiers.py -q` passes.
  - `make test-acceptance` runs in the background when the measured free space under pytest's base temp is at
    least 12 GiB, and is otherwise reported "not run" with the measured bytes.
  - CI receipts: the green `stack` and `large-file` runs of the pull request, recorded by M19.5.
- Dependencies: M15.4, M15.5; M16, M18.
- Decisions: OQ-22.2 (settled, owner decision 12)
- Status: pending

### M19.2 T-docs-Z: overview pages, `auth.html` §7 and the roadmap

- Intent: make the design record's summary pages describe what was built, replace every Raw-engine passage
  with the lake's, remove the temporary status lines that T-docs-0 added, and close the roadmap's RL phase.
- Delete:
  - `design/core-map.html` §7 Revision reads (`reads`).
  - The status line "Raw sections describe the engine being replaced by the Raw lake (`RAW_LAKE_DESIGN.md`)." on
    `index.html`, `architecture.html`, `workflows.html` and `core-map.html`, and `layer-raw.html`'s "Target
    design; sections land with their tasks in `RAW_LAKE_IMPLEMENTATION_PLAN.md`." line.
  - The links to `rawstore-uml.html` and their sentences at `architecture.html:87`, `core-map.html:168` and
    `index.html:334`, and `index.html` §4's document-map row for that atlas (the file leaves in M19.3).
- Create: none.
- Modify (each row of DT-26's tables whose "Lands with" cell is T-docs-Z, plus the sections marked "outside
  DT-26's rows", which the closing check needs):
  - `design/index.html`: §2 the two resource trees; §3 decisions 2, 3, 6, 7, 8, 10, 11, 14 and 16 with their
    numbers kept and retired rows as one dated line; §5's MCNP step; §6's Raw terms replaced by a link to
    `CONTEXT.md`. Outside DT-26's rows, because the closing check below matches them and the status line
    that covered them goes (DT-26 "interfaces and contracts", Page contracts): §1's "immutable Raw
    revisions" and the Raw row's "Contributors, through the API" become files in collections on the lake,
    written by `huron push`; decision 15's manual-intake clause (`:276`, "linked to a raw revision of the
    same dataset") becomes "linked to Raw pins (collection id, `rel_path`, sha256) when its bytes came from
    the lake, external-provenance otherwise", and its rationale loses the Raw retention clock (decision 10
    is retired); §4's `layer-raw.html` card (`:336-338`) becomes "Raw Layer: the lake" with a one-line
    outline of that page's sections; the Authentication card (`:354-356`) names the surviving credential
    kinds and the broker's Huron JWT instead of the session model, CSRF and passwords (M1.6); the REST API
    card (`:357-359`) names the lake routes instead of "ingest". Each card links its page rather than
    restating it.
  - `design/architecture.html`: "Implemented backend boundaries" and "Domain-owned Core workflows" naming DT-1's
    owners by link to `AGENTS.md`; §1–§6 adapted (the volume plus schema `lake`; the commit worker, the
    access-reset worker, the reconciler CronJob and the broker; Raw enters by `huron push`; asynchronous commit and
    the nightly reconciliation; invariant N; the CronJob, Secret mode, `ltree` and volume mount linking the
    runbook).
  - `design/workflows.html`: §1, §3, §4 as "Step 2, path A: a Raw collection through the CLI" (linking
    `docs/raw-lake/cli.md` and `layer-raw.html` §4–§6), §5, §7 and §8; its `layer-raw.html` links at `:151`
    (`#ingest` → `#commit`), `:152`, `:153` and `:162` (→ `#commit`, the concurrent-writers sentence →
    `#lifecycle`). §6 (`publish`, outside DT-26's row): the materialization-state sentence ("per-revision
    materialization state (raw: committed · …)") names Raw pins and derived snapshots, and "raw commits
    atomically with checksums" becomes the lake's asynchronous commit with the server's re-hash.
  - `design/core-map.html`: §2 module map (`lake`, `hierarchy`, `applications/cli`); §4 the rank ladder beside
    `RoleBindingAuthorizer`; §6 "Lake commit: the filesystem/database crossing" (id `commit`); §9 the lake ports
    and their PostgreSQL, memory and recording adapters; §10's reading guide; its 41 links into
    `../src/huron/core/{raw,catalog,rawstore}/` rewritten with the page. Outside DT-26's row, because M1.6
    deleted what they describe and M19.3's link check would report `../src/huron/core/security/sessions.py`:
    §1 Orientation without `IngestService`, `RawRuntime`, Raw ingestion and the trusted `expire_lapsed()`,
    and its dependency graph with `hierarchy` and `lake` instead of `catalog` and `raw`; §3 Class
    relationships without the Ingest, Revision, Raw-runtime and Session classes and with the lake classes;
    §5 Catalog operations without "creation alone does not produce a Raw revision", its "Raw commit below"
    pointing at §6 Lake commit; §8 Identity operations limited to the surviving operations (API keys,
    service accounts, the platform-owner bootstrap) and the broker, with no `create_user`, `set_password`,
    `PasswordAuthentication`, `OidcAuthentication`, `SessionResolver` or `terminate_session` and no
    `sessions.py` link.
  - `design/layer-silver.html` `:244-248` (§4 "Direct entry", outside DT-26's rows; M0.5 changed only the
    `:247` link): the entry-layer sentence loses "no ingest session, no manifest" and the Raw retention clock
    (decision 10 is retired): entry above Raw means the bytes did not come from the lake, carry no pins and
    have no Raw recovery, and the sentence keeps M0.5's `layer-raw.html#recovery` link.
  - `design/auth.html` §7 Known gaps: PKCE on the device grant (checked in staging), the company bearer kept on
    legacy routes only, the actor-only audit.
  - `design/roadmap.html`: P4's text and gate; P5's remaining Raw items and its gate clause; the dependency
    sketch (`:157`) and §4 sequencing (`:816`, `:823`); the RL row's own tag becomes `done` (its six step
    tags are `done` from M15.4 and M18.3). P0's D-1 clauses and Milestone 23's D-7 "Built" line were
    corrected at planning time and committed by M0.1; this task verifies them and does not edit them.
    Line numbers are at `fa51f46`; earlier tasks' edits shift them.
- Design: "DT-26 design: Design record, roadmap and operator documentation" → "DT-26 design record pages:
  overview, client, derived-layer pages and atlases" (the `index`, `architecture`, `workflows` and `core-map`
  rows), "DT-26 design record pages: the Raw-facing six" (`auth.html` §7), "DT-26 roadmap rows" (P0, P4, P5,
  Milestone 23, the sketch, RL), "DT-26 broken links and their fixes" (the `workflows.html`, `core-map.html` and
  `rawstore-uml` rows), "DT-26 interfaces and contracts" (Page contracts: status lines, ids, one source per
  fact, lands with its code), "DT-26 deletions"; the overview group's closing check (end of "DT-26 design
  record pages: overview, client, derived-layer pages and atlases") is the basis for the sections scheduled
  above outside DT-26's rows (`index` §1, decision 15 and three §4 cards; `core-map` §1, §3, §5 and §8;
  `workflows` §6; `layer-silver` `:244-248`).
- Verification:
  - `make docs` and `git diff --check`.
  - `rg -n 'security/sessions\.py|PasswordAuthentication|OidcAuthentication|SessionResolver|SessionStore|terminate_session|create_user|set_password|IngestService|RawIngestionService|RawRuntime|\bRawStore\b|Revision(Read)?Service|RevisionStore' design/core-map.html`
    prints nothing; `rg -n -i 'ingest session|independent revisions|session model|CSRF|admin-provisioned passwords|TTL expiration|immutable <em>Raw</em> revisions' design/index.html`
    prints nothing (today it matches `:91`, `:337-338` and `:355-356`).
  - `rg -n 'describe the engine being replaced|Target design; sections land' design` prints nothing.
  - `rg -n 'standing in for NFS|Built: the write-intent' design/roadmap.html` prints nothing, and
    `rg -U -n 'buckets and\s+volumes' design/roadmap.html` prints nothing (D-1 and D-7 stay corrected);
    `rg -c 'id="rl-step-[1-6]"><strong>Step [1-6] — [^<]+</strong> <span class="tag">done</span>' design/roadmap.html`
    reports 6 and `rg -n 'RL: Raw lake<br><span class="tag">done</span>' design/roadmap.html` prints the row.
  - `rg -n 'rawstore-uml' design --glob '!rawstore-uml.*'` prints nothing; `rg -n '\.\./src/huron/core/(raw|catalog)/' design/core-map.html`
    prints nothing (links into the surviving `rawstore` are checked by M19.3's link check); `rg -n 'id="reads"' design/core-map.html` prints nothing.
  - `rg -n -i 'raw revision|revision_id|raw/\{revision|rev-1|ingest session|dataset\.upload|raw-web|huron-web|realms/huron' design --glob '!*-uml.*'`
    prints only lines of `layer-raw.html` §12 History.
  - `rg -n 'raw-publication' design docs --glob '!*-uml.*'` prints nothing.
- Dependencies: M19.1; M18.
- Decisions: OQ-7.1 (settled, owner decision 12)
- Decisions: OQ-22.1 (settled, owner decision 12)
- Decisions: OQ-16.3 (settled, owner decision 12)
- Status: pending

### M19.3 T-docs-Z: developer docs, dated atlases, B-1 and the design-link check

- Intent: finish the documentation sweep (README lede, the docs site's index, backend page, history entry,
  repository layout and runbook §7, the "Raw lake" navigation group), date and pin the four kept UML atlases and
  retire `rawstore-uml`, delete B-1, and add the mechanical design-link check to `make docs` and to CI's `lint`
  job once every link resolves.
- Delete:
  - Whole files (orchestrator `git rm`): `design/rawstore-uml.html`, `design/rawstore-uml.md`.
  - `scripts/render_uml_atlas.py`: the `rawstore` entry of `ATLASES`.
  - `AGENTS.md`: bullet B-1.
- Create:
  - `scripts/check_design_links.py` (stdlib only): `BrokenLink`, `broken_links(root)` and `main(argv)` with DT-26's
    scope, output and exit codes (0, 1, 2).
  - `tests/unit/test_check_design_links.py` (`unit`): a missing file and a missing anchor are found with their
    `source:line -> target (reason)` lines sorted by source then line; `http(s):`, `mailto:` and in-page `#…`
    links in Markdown are skipped; a fragment on a `design/*.html` target must equal an `id` on that page; an
    existing file and anchor pass; exit 0 for a clean tree, 1 with findings, 2 on a usage error; the real
    repository has no finding.
- Modify:
  - `README.md:3-4`: DT-26's lede.
  - `docs/index.md:15-16`; `docs/backend-design.md:14`, `:17`, `:31`; `docs/getting-started/repository-layout.md`
    `:46`; `docs/history.md`: the dated entry "2026-10-23: the Raw lake replaces the Raw engine" (what DT-2, DT-3
    and DT-6 deleted, by area, with `git show fa51f46:<path>` as the recovery path; `audit_events` dropped
    without export; the superseded `RAW_STORAGE_*` plans and the M3 registry parts not carried over) and the
    "Archived plans" row for the raw storage redesign.
  - `docs/raw-lake/operations.md`: §7 Staging verification (each check with its pass condition; no
    upgrade-from-the-engine section). `docs/getting-started/testing.md`: the tier table's Staging row, naming
    the runbook section.
  - `zensical.toml`: the "Raw lake" navigation group with the two pages, and the header comment's second
    paragraph in DT-26's wording.
  - The four kept atlases, both editions (`design/{auth,catalog,metastore,rbac}-uml.{md,html}`): DT-26's banner
    under each title; every relative `../src` and `../tests` link rewritten to PIN-A; the 12 links that do not
    resolve at `fa51f46` as plain `<code>`. The `.md` edition is the source and the `.html` gets the identical
    textual edit; no re-render (a link-only edit needs none).
  - `Makefile` `docs`: a second line `uv run python scripts/check_design_links.py` after the strict build.
  - `.github/workflows/ci.yml` `lint`: a step `make docs` after `make lint`.
- Design: "DT-26 design: Design record, roadmap and operator documentation" → "DT-26 decisions" (UML atlases,
  Link check), "DT-26 developer docs, README and history" (T-docs-Z rows), "DT-26 the two new pages"
  (`operations.md` §7), "DT-26 target layout" (`zensical.toml`), "DT-26 broken links and their fixes" (atlas
  and `rawstore-uml` rows), "DT-26 interfaces and contracts" (`scripts/check_design_links.py`, Page contracts),
  "DT-26 open questions" (OQ-26.1), "DT-26 deletions"; "DT-25 design: …" → "DT-25 interfaces and contracts"
  (B-1's lifecycle), "DT-25 handoffs" (DT-26 row); "DT-23 design: …" → "DT-23 the tier table" (Staging row).
- Skills: `writing-for-agents` (`AGENTS.md`).
- Verification:
  - `uv run pytest tests/unit/test_check_design_links.py -q` passes; `uv run python scripts/check_design_links.py`
    exits 0 and prints nothing; `make docs` exits 0 with both commands; `git diff --check`.
  - `uv run python -m py_compile scripts/render_uml_atlas.py scripts/check_design_links.py`;
    `rg -n 'rawstore' scripts/render_uml_atlas.py` prints nothing; `test ! -e design/rawstore-uml.html && test
    ! -e design/rawstore-uml.md`.
  - `rg -n 'href="\.\./(src|tests)/|\]\(\.\./(src|tests)/' design/auth-uml.md design/auth-uml.html design/catalog-uml.md design/catalog-uml.html design/metastore-uml.md design/metastore-uml.html design/rbac-uml.md design/rbac-uml.html`
    prints nothing (the other pages keep relative code links, which the link check resolves).
  - DT-26's closing checks: `rg -n -i 'raw revision|revision_id|raw/\{revision|rev-1|ingest session|dataset\.upload|raw-web|huron-web|realms/huron' design docs/getting-started docs/raw-lake docs/index.md docs/backend-design.md README.md --glob '!*-uml.*'`
    prints only `layer-raw.html` §12 History lines; `rg -n 'Until .RAW_LAKE_IMPLEMENTATION_PLAN.md. completes'
    AGENTS.md` prints nothing.
  - `uv run python -c "import yaml; s = str(yaml.safe_load(open('.github/workflows/ci.yml'))['jobs']['lint']['steps']); assert 'make docs' in s, s"`
    exits 0.
  - The plan-wide gate (the unit run includes the new test).
- Dependencies: M19.2.
- Decisions: OQ-26.1 (settled, owner decision 12)
- Decisions: OQ-2.3 (settled, owner decision 12)
- Decisions: OQ-11.1 (settled, owner decision 12)
- Decisions: OQ-11.4 (settled, owner decision 12)
- Decisions: OQ-21.3 (settled, owner decision 12)
- Decisions: OQ-22.1 (settled, owner decision 12)
- Status: pending

### M19.4 Final verification on the local tree

- Intent: prove the end state before anything leaves the machine: nothing of the deferred Polaris projection
  exists, no Raw versioning vocabulary remains in the lake, every closing check of the plan still holds, the
  documentation is green and link-clean, and the coverage floor is re-measured once with DT-2's rule.
- Delete: none.
- Create: none.
- Modify:
  - `pyproject.toml` `[tool.coverage.report]` `fail_under`: `floor(10000 × covered / statements) / 100` of the
    unit run's totals (`uv run pytest --cov=src/huron --cov-report=json:<scratch>/final.json`), never past the
    measured total and never lowered; the before and after covered and total counts and the unit test-count
    change go under "Execution notes".
  - `RAW_LAKE_IMPLEMENTATION_PLAN.md` "Execution notes": the results below and the duplication-baseline total
    for G7 (at most four signatures).
- Design: "DT-24 design: Polaris projection seam (option C, deferred)" → "DT-24 explicitly not built in this
  plan" (closing check), "DT-24 deletions", "DT-24 handoffs" (Plan row); "DT-25 design: …" → "DT-25 interfaces
  and contracts" (closing check of T-docs-0; the lineage rule's own check); "DT-26 design: …" → "DT-26
  interfaces and contracts" (Gate); "DT-23 design: …" → "DT-23 decisions" (Coverage ratchet), "DT-23 the tier
  table" (Gates); "DT-2 design: …" → "Coverage floor procedure".
- Verification (each command prints nothing unless stated):
  - The plan-wide gate, with the contract and integration suites run in the background and polled;
    `uv run lint-imports` reports 20 contracts kept.
  - DT-24's closing check, all five commands as written; `rg -il polaris src/huron` lists only
    `core/foundation/names.py`, `core/security/broker/ladder.py` (the claim grammar's Polaris
    principal-role rule, M3.1) and any lake module whose comments cite DT-5's principal-role name rule;
    `test ! -e src/huron/core/lake/projection.py`; `rg -n 'polaris_projection|RawCatalogProjection|CatalogProjection'
    src tests migrations`.
  - The lineage rule's check `rg -n -i revision src/huron/core/lake`; OQ-5.1's absence of key revocation
    `rg -n 'revoked_at' src/huron/core/security/broker src/huron/core/lake src/huron/core/metastore/lake migrations/versions/0015_lake_catalog.py`;
    OQ-16.2's `rg -n --glob '!docs/adr/**' -e '--repair' src docs` prints nothing (ADR 0007 records the flag's removal).
  - DT-25's T-docs-0 closing check, its five `rg`/`ls` lines as M0.5 runs them; DT-26's closing checks as M19.3
    runs them; `make docs` (with the link check) exits 0.
  - Every closing check written in the Verification of M0.5, M1.1–M1.7, M2.1, M9.1, M11.3, M11.14, M13.9 and
    M14.4 re-run unchanged on the final tree, except clauses those tasks scope to their own commit and these
    clauses, which later tasks invert and which are not re-run (each listed again under "Execution notes" with
    the clause that replaces it):
    - M0.5's `rg -c 'describe the engine being replaced' …` count of 1 per file, and M1.3's
      `rg -n 'Target design; sections land' design/layer-raw.html` printing the status line (M1.3 and M19.2
      delete those lines; M19.2's `rg` printing nothing replaces both);
    - M1.4's `nightly.yml` job list `['unit-macos']` (M15.4 adds `nfs-large`; M15.4's job-set assertion
      replaces it);
    - the operation and tag counts of M1.3 (52 operations, 15 tags), M1.4 (40 operations, the 12-tag set) and
      M1.6 (11 tags; its 38 operations still hold), replaced by this task's 38 operations and 21 tags below;
    - every `uv run lint-imports` contract count of M1.1–M1.7 and M2.1 (14 or 16), replaced by this task's
      20 contracts kept;
    - the `rg -n 'place_moved' src` half of M11.14's milestone close (M16.4 adds `Directories.place_moved`);
      its `rg -n 'rename_collection' src tests` half is re-run and prints nothing;
    - the `\.staging` alternative of M1.5's DT-2 closing check (M14.1 creates `cli/staging.py`, whose imports
      match); the rest of that `rg` is re-run and prints nothing;
    - M1.5's surviving-primitives clause (its pytest run names `test_rawstore_materialize.py` and
      `test_rawstore_completion_admission.py`, which M11.2 renames and deletes) and its importer `rg` listing
      only `app.py`, replaced by M11.2's `uv run pytest tests/unit/test_rawstore_anchored.py
      tests/unit/test_rawstore_mount.py tests/unit/test_rawstore_generation.py` with `anchored.py` and
      `mount.py` at 100 %;
    - the `password` alternative of M1.6's DT-2 closing check and its `scripts` half (M5.2's
      `company-realm.json` credentials, M15.2's passwordless `sudo` and M15.5's password grant in
      `tests/stack/conftest.py`); the pattern without `password` is re-run over `src tests` and prints
      nothing outside `tests/contract/test_retire_legacy_raw.py` (M1.7's drop test names `local_credentials`
      and its guard), and `rg -n 'auth/oidc/callback' scripts` is re-run and prints nothing;
    - M1.6's `test ! -e src/huron/applications/api/routes/auth …` and "no `/auth` path" clauses (M9.3
      re-creates `routes/auth` with `POST /auth/exchange`), replaced by
      `test -e src/huron/applications/api/routes/auth/endpoints/exchange.py && test ! -e src/huron/core/security/_impl/self_access.py`
      and "the `/auth` family is exactly `POST /auth/exchange`" in `test_api_router_composition.py`;
    - the `reconciliation_findings` alternative of M1.7's `migrations/schema.sql` check (M17.1 adds
      `lake.reconciliation_findings`), replaced by the pattern without it, which prints nothing, plus
      `rg -n '^CREATE TABLE reconciliation_findings ' migrations/schema.sql`, which prints nothing.
  - `uv run pytest tests/unit/test_api_router_composition.py tests/unit/test_lake_routes.py -q` passes with 38
    legacy operations, 21 tags and 34 lake routes behind `current_actor`; `rg -n '^-- Reflects: 0018_lake_reconciler$'
    migrations/schema.sql` prints one line.
  - `uv run pytest -m "stack or nfs" --collect-only -q` collects every `tests/linux/` and `tests/stack/` case;
    `make test-acceptance` runs in the background when at least 12 GiB are free under pytest's base temp, else
    "not run" with the measured bytes.
  - `git status --short` prints nothing after the commit, and every task before this one reads "Status: done".
- Dependencies: M19.3.
- Decisions: OQ-5.1 (settled, owner decision 12)
- Decisions: OQ-16.2 (settled, owner decision 12)
- Decisions: OQ-24.1 (settled, owner decision 12)
- Decisions: OQ-24.2 (settled, owner decision 12)
- Status: pending

### M19.5 Pull request, CI receipts, nightly runs and the merge commit

- Intent: the only task that pushes. It opens the pull request, records the first green CI run of every job
  as the receipt that M15.2–M15.5, M16.4, M17.5 and M19.1 deferred to it, obtains two consecutive green
  `nightly.yml` runs on the pull request through its `nightly` label (plan-wide "Merge" rule: GitHub starts
  `schedule` and `workflow_dispatch` only for workflows on the default branch), and merges `raw-storage` into
  `main` with a merge commit, never a squash (DT-25 D-2).
- Delete: none.
- Create: none.
- Modify: `RAW_LAKE_IMPLEMENTATION_PLAN.md` "Execution notes" (the receipts), committed on `raw-storage` before
  the merge.
- Steps:
  1. `git push -u origin raw-storage`; `gh pr create --base main --head raw-storage` with a body written by the
     `pr` skill, ending with the attribution line the session gives.
  2. Poll `gh pr checks <number>` with short commands (plan rule "Long commands") until every check finishes.
     Branch protection is unavailable on this repository's plan (`gh api
     repos/karthedew/huron/branches/main/protection` answers 403), so "required" means this task confirms by
     name that `lint`, `unit`, `contract`, `integration`, `stack`, `nfs` and `large-file` each concluded
     `success`, and records each run id and job URL as a receipt. A red check stops the task: the failure goes to
     the milestone that owns the test as a new fix task, and a named race or matrix failure is never re-run to
     green. The owner's receipt for M10.4's manual smoke (`uv run --env-file dev.env huron login --device`
     against the compose Keycloak `company` realm, RL step 1) must be under "Execution notes"; without it the
     task stops and asks the owner, because no task starts the owner's stack.
  3. Two consecutive nightly runs on the pull request, started by its `nightly` label (M1.4's
     `pull_request` trigger, types `labeled` and `synchronize`, and the job-level
     `if: github.event_name != 'pull_request' || contains(github.event.pull_request.labels.*.name, 'nightly')`
     on `unit-macos` and `nfs-large`):
     - `gh label create nightly --description "Run nightly.yml on this pull request" --force`, then
       `gh pr edit <number> --add-label nightly`; this `labeled` event starts the first run.
     - Poll `gh run list --workflow nightly.yml --branch raw-storage --event pull_request --limit 3 --json databaseId,status,conclusion,createdAt`
       with short commands until that run completes, then
       `gh run view <id> --json jobs --jq '.jobs[] | [.name, .conclusion]'` must show `nfs-large` and
       `unit-macos` both `success`. A run whose jobs were skipped does not count.
     - Start the second run with `gh pr edit <number> --remove-label nightly` then
       `gh pr edit <number> --add-label nightly`, and check it the same way.
     - The `nfs-large` summary of each carries `reconciler-scale.json`; record each run id and the second
       run's `scan_eps` for the runbook's sizing rule.
     - After the second green run, `gh pr edit <number> --remove-label nightly`, so the receipts commit
       starts only nightly runs whose jobs are skipped, which the count ignores.

     A label that starts no run, or a run whose jobs are skipped while the label is present, is a defect in
     `nightly.yml`'s trigger or condition: it becomes a fix task for M1.4's and M15.4's `nightly.yml` lines
     before the merge (Risk 5). A red job becomes a fix task in the milestone that owns the test, and the
     count of consecutive green runs restarts. The `schedule` trigger stays, and after the merge it runs on
     `main`.
  4. `gh pr merge <number> --merge`, with a merge-commit body that ends with the commit trailer the session
     gives.
- Design: "DT-23 design: …" → "DT-23 the tier table" (Gates; the head's "Merge" rule and its "Nightly runs
  before the merge" override say how the two pre-merge runs start), "DT-23 CI workflow job outlines";
  "DT-25 design: …" → "DT-25 superseded banners and the D-2 links" (Condition); "DT-26 design: …" → "DT-26
  decisions" (Reconciler threshold).
- Verification:
  - Before the merge, "Execution notes" names two consecutive `nightly.yml` run ids on the pull request
    (`event` `pull_request`), each with `nfs-large` and `unit-macos` concluded `success`, and no red nightly
    run on the pull request after the first of them.
  - After the merge, `git fetch origin` and
    `git merge-base --is-ancestor f1c44e3d56b10806c05373fce5b51c7a44abf146 origin/main && git merge-base --is-ancestor raw-storage origin/main`
    exits 0; `git log -1 --merges --format=%P origin/main | wc -w` prints 2.
  - The CI run of the push to `main` concludes `success` (`gh run list --branch main --workflow CI --limit 1
    --json conclusion`). This receipt, the `merge-base` results and M19.5's "Status: done" are reported by the
    orchestrator in its session report and are not pushed (nothing is pushed after the merge; Definition of
    done, "Every task done").
- Dependencies: M19.4.
- Decisions: OQ-11.2 (settled, owner decision 12)
- Decisions: OQ-23.1 (settled, owner decision 12)
- Decisions: OQ-23.2 (settled, owner decision 12)
- Status: pending

## Risk register

The five changes most likely to stop the plan, each with the symptom that shows it and the point at which
the fallback is decided. A fallback that changes a design decision goes back through the design (a new
DT-section change and new tasks), never as an edit of a done task.

1. **The legacy deletions, D2-2 and D2-4 (M1.4, M1.6).** The two largest tasks delete `huron.core.raw`,
   the Raw `/api/v1` surface, the `/auth` router, the password login and the cookie sessions in one commit
   each, under DT-2's coverage-floor procedure.
   - Symptom: the pre-step re-count finds importers DT-2 does not list; mypy or ty fails in a surviving
     module; the drop in covered statements does not equal the covered statements of the deleted files
     (pass condition 3); the router-composition test counts other than 40 or 38 operations.
   - Fallback decision point: before the orchestrator's `git rm`. An unlisted file is recorded under
     "Execution notes" and edited, never deleted silently. A step whose closing check cannot hold at its
     own commit is split along the ordering gap it exposes, as M1.4 and M1.5 already split D2-2 and D2-3.
     The floor is never lowered to make a step pass.

2. **The asynchronous commit and its crash matrix (M13.4–M13.8).** The lease queue, the bounded re-hash
   worker, the in-transaction re-stamp and the FIFO-with-express claim order are the lake's most
   concurrent code. DT-14's in-attempt retry on `40001`/`40P01` is not built, because DT-17 lets those
   errors propagate and `huron.core.lake` cannot import `asyncpg` (M13.7).
   - Symptom: an intermittent failure of C15, C16 or a crash-matrix case; contract runs that end commits in
     the transient-release path under serialization failures; a cancelled `verify` that frees its hash
     slot before its thread returns.
   - Fallback decision point: the first intermittent failure stops M13 (plan rule "Races") until a fix
     lands with a named test. If serialization failures recur on PostgreSQL, the decision before M13.8
     starts is a port-level retry signal from the store (a DT-17 change), not a retry hidden in the worker.

3. **The NFS tier and the ONTAP assumptions (M11.4, M15.2–M15.5, M16.4, M17.5).** On the owner's macOS the
   `nfs`, `stack` and `large-file` tests only collect; their first real runs happen when M19.5 pushes the
   branch. The NFSv4 ACL encoding, the inherited ACEs under `0o666`/`0o777` create modes and the uid rule
   are proven against loopback kernel nfsd, not ONTAP (owner decision 12's external assumptions).
   - Symptom: the first `nfs` or `nfs-large` CI run at M19.5 is red; `acl_unsupported` or `EACCES` where
     the access table expects success; `nconnect` not parsed from the runner's mountinfo.
   - Fallback decision point: each red job becomes a fix task in the milestone that owns the test, before
     the merge. Because the failure surfaces only at M19.5, the owner decides at M15.3 whether the branch
     may be pushed earlier for CI receipts only; the plan as written pushes nothing before M19.5. A
     production-side contradiction of OQ-11.1 or OQ-21.3 found during the staging runbook is a design
     change to DT-11 and DT-21.

4. **Decisions the plan takes where the design is silent or self-contradictory.** Contract 9 forbids
   `rawstore → huron.schema`, while DT-11 has `probe_mount` parse the marker and mountinfo with
   `huron.schema.volume`; M11.2 keeps contract 9 and injects `VolumeRules`. Contract 19 is written as two
   `forbidden` tables (M4.1). The signing-key receipt is `uuid5(<namespace>, kid)` (M7.7). The Ruff `N818`
   per-file ignores extend to the lake and CLI modules that declare design-named exceptions (plan-wide
   "Clean sweep"). `google-re2` (M6.2) and `questionary`'s `py.typed` (M10.7) are assumed to install and
   type-check without further overrides. The head's "Plan-time resolutions of design text" lists every
   place the plan's text deliberately differs from the design's.
   - Symptom: `lint-imports` or ruff fails on a planned edge or name; the injected rules duplicate the
     marker parser; `uv add` cannot resolve a wheel; mypy needs an override the design does not list.
   - Fallback decision point: the task that meets it stops and reports (M10.7 already says so for
     `questionary`); the owner rules before the task is retried, and the ruling updates the design section
     and this plan's text in the same change.

5. **The merge gate (M19.5).** GitHub branch protection is unavailable on this repository's plan, so the
   seven required checks are confirmed by name; `nightly.yml` exists only on `raw-storage` until the merge
   (M1.4 renamed `acceptance.yml`) and GitHub starts `schedule` and `workflow_dispatch` only for workflows
   on the default branch, so the two pre-merge nightly runs come from the pull request's `nightly` label
   (`pull_request` types `labeled`, `synchronize`, behind the job-level `if` of the head's "Merge" rule);
   the manual Keycloak login smoke of RL step 1 needs the owner's stack.
   - Symptom: adding the `nightly` label starts no `nightly.yml` run, or a run's jobs are skipped by the
     job-level `if`; `nfs-large` exceeds its 60-minute timeout on the hosted runner; a required check is
     missing from `gh pr checks`; no owner receipt for the M10.4 smoke under "Execution notes".
   - Fallback decision point: M19.5 step 3. A run that does not start, or skips its jobs, is a defect in
     `nightly.yml`'s trigger or condition and becomes a fix task before the merge; a red job becomes a fix
     task in the milestone that owns the test. The merge waits for two consecutive green runs (DT-23
     "Gates") and never squashes.

## Definition of done

The plan is complete when all of the following hold on `raw-storage` and then on `main` after the merge.

- **Every task done.** Each task M0.1 … M19.4 reads "Status: done" on `main`, was committed alone by the
  orchestrator after its verification passed, and recorded its deviations, its `fail_under` change (before and after
  covered and total counts, unit test-count change) and each duplication-baseline hand edit with its kind
  and the group's running total of capped signatures (at most four per group; subset signatures left by
  deletions and pure re-paths are exempt, plan-wide "Duplication baseline") under "Execution notes".
  M19.5's own status and its post-merge receipts (the `merge-base` checks and the CI run of the push to
  `main`) are reported by the orchestrator in its session report: the orchestrator commits a task only after
  its verification, and nothing is pushed after the merge, so they never reach `main`.
- **The full gate.** On the final commit every command of the plan-wide gate exits 0 (`ruff check`,
  `ruff format --check`, `pydoclint`, `mypy`, `ty check`, `lint-imports`, `scripts/check_schema_map.py`,
  `complexipy`, `pyscn`, `scripts/check_duplication.py`, the unit run with coverage, `pytest -m contract`,
  `pytest -m integration`), `radon cc --min C` and `radon mi --min B` print nothing, `uv run lint-imports`
  reports 20 contracts kept, `make docs` (strict build plus `scripts/check_design_links.py`) exits 0, and
  the coverage floor was re-measured once by DT-2's rule in M19.4.
- **CI receipts.** The pull request's `lint`, `unit`, `contract`, `integration`, `stack`, `nfs` and
  `large-file` jobs concluded `success`, two consecutive `nightly.yml` runs on the pull request, started by
  its `nightly` label (`nfs-large` with the `reconciler-scale.json` summary, and `unit-macos`), are green, the owner's receipt for M10.4's manual
  `huron login --device` smoke is recorded, and the CI run of the push to `main` is green; every pre-merge
  run id is under "Execution notes", and the post-merge run id is in the orchestrator's report.
- **End-state facts.** The legacy `/api/v1` router serves 38 operations; the lake router serves DT-18's 34
  routes, every one behind `current_actor` and refusing an anonymous request; the OpenAPI document has 21
  tags; the `/auth` family is exactly `POST /auth/exchange`; Alembic head is `0018_lake_reconciler`,
  revisions `0014`–`0018` landed in milestone order and `migrations/schema.sql` reflects the head; the
  `huron` console script lists every verb of DT-19–DT-21 and no `ls`, `draft` or `--repair`.
- **Closing checks.** Every closing `rg` check the design names prints what its task states, re-run on the
  final tree by M19.4: DT-3's (M1.1, M1.2), DT-2's (M1.3–M1.7), DT-22's no-bypass check (M5.5), DT-6's
  (M9.3), DT-11's (M11.14), DT-25's T-docs-0 check (M0.5), DT-26's (M19.3), DT-24's "explicitly not built
  in this plan" check with no projection module, table, client or marker (M19.4), the lineage rule's
  `rg -n -i revision src/huron/core/lake`, no `revoked_at`, and no `--repair` in `src`, or in `docs` outside
  the ADR that records its removal (`docs/adr/0007-raw-reconciler.md`); clauses a task scoped to its own
  commit are named under "Execution notes".
- **Documentation and the design record.** The design pages describe the built lake and carry no
  temporary status line; `design/roadmap.html`'s RL row and its six step tags are `done` and P2, P3,
  Milestones 7 and 8 are `retired`; `design/api.html` §1, §3 (DT-18's 37 rows) and §7 match the code
  (`tests/unit/test_error_contract.py` passes); `docs/raw-lake/operations.md` and `docs/raw-lake/cli.md`
  are complete and in the "Raw lake" navigation group; `AGENTS.md` carries B-2 … B-11 without B-1;
  `CONTEXT.md`, ADR 0002's amendment and ADRs 0003–0007 are in place; `RAW_LAKE_SPEC.md` ends with the
  "Design amendments (2026-10-23)" A-1 … A-30 and its body is byte-identical above them; the two
  `RAW_STORAGE_*.md` files carry DT-25's banners.
- **Owner decisions honoured.** 1: no Raw engine, `/api/raw-web`, wizard or explorer remains, and the
  Polaris org/project/dataset surface and the web's own login still pass their tests. 2: every lake table
  comes from a hand-written revision and is written by asyncpg adapters in `huron.core.metastore.lake`.
  3: commits answer 202 and finish in the worker. 4 and 5: development and tests use the plain-directory
  volume with the recording permissions, the Keycloak `company` realm, the fake issuer and
  `fake-ldap-groups`, and `src/` imports no test module. 6: DT-24's check passes. 7: a removed mapping
  refuses the next request of an unexpired token (M4.3, M9.5). 8: every administration write is audited
  and the seeded Platform Owner exists after a fresh start. 9: the plan files and banners are as above.
  10: no Python password login, cookie session or server code flow remains, API keys, service accounts and
  dev headers serve legacy `/api/v1` only, and lake routes accept only the Huron JWT. 11: no shim, alias,
  re-export, second request form, data-preserving migration, refusal flag or interim state exists
  (M1.7's and M9.4's checks, B-2 … B-40). 12: no task carries a "Gate:" line, and the external assumptions
  of the head stay listed for confirmation before the production rollout, which is outside this plan.
- **The merge.** `raw-storage` is merged into `main` by a merge commit (two parents), `f1c44e3` is an
  ancestor of `origin/main`, and nothing was pushed before M19.5.

## Verification (cycle 1)

Verdict: DEFECTS. 42 defects: 13 blocking and 29 non-blocking. Seven scoped verifiers (G1 to G7) and one
plan-wide verifier checked the plan against the design, the spec's owner decisions 1–12 and the repository
at `fa51f46`. Two verifiers reported the M19.5 nightly-dispatch defect independently; it appears here once,
as defect 42. Each blocking claim was re-checked against the plan, the design or the repository before it
was kept. Defects are numbered in plan order within each milestone group (G1 M0–M2, G2 M3–M5, G3 M6–M7,
G4 M8–M9, G5 M11 and M13, G6 M10, M12, M14 and M18, G7 M15–M17 and M19). "plan :N" is a line of this
file, which this section follows and so does not shift; `design:N` is a line of `RAW_LAKE_DESIGN.md`.

### Defects (cycle 1)

1. **Blocking. M0.3 (G1), plan :466.**
   - What: the check `rg -L '^status: accepted$' docs/adr/000[2-7]-*.md`, expected to print nothing, uses `-L`. In
     ripgrep 15.2.0, `-L` is `--follow` (follow symlinks), not files-without-match, and no short flag for
     files-without-match exists. The command prints each ADR's matching `status: accepted` line. Run at HEAD
     on 0002 alone, it printed that line.
   - Why: when the files are correct the command prints six lines, never nothing, so a verifier who reads
     the plan literally fails M0.3 every time.
   - Correction: `rg --files-without-match '^status: accepted$' docs/adr/000[2-7]-*.md` prints nothing.

2. **Non-blocking. M0.4 (G1), plan :531-532.**
   - What: `git diff HEAD~1 --stat -- RAW_STORAGE_DESIGN.md RAW_STORAGE_IMPLEMENTATION_PLAN.md` is said to
     show "one changed region per file", but `--stat` prints only per-file line counts.
   - Why: the command cannot establish the property it claims, namely that nothing else in either
     superseded file changed.
   - Correction: `git diff -U0 HEAD~1 -- RAW_STORAGE_DESIGN.md | rg -c '^@@'` and the same for
     `RAW_STORAGE_IMPLEMENTATION_PLAN.md`; each reports `1`.

3. **Blocking. M1.1 (G1), plan :653-654.**
   - What: the task applies "DT-3's 'Docs' edits to the repository `README.md`". DT-3 says its paths are
     relative to `web/` (design:2339-2340). The README lines it cites (`:5`, `:67`, `:79-80`, `:97`,
     `:152-154`, `:178-187`, `:189-195`, `:219-223`) exist only in `web/README.md` (252 lines). The root
     `README.md` has 18 lines and none of that text.
   - Why: an implementer who follows the plan edits the root README, which has no such lines, and may add
     DT-3's "Raw is reached through the huron CLI" sentence there. `web/README.md` keeps describing the
     deleted wizard, bridge and `BODY_SIZE_LIMIT`, and DT-3's closing `rg` (run from `web/`) fails.
   - Correction: "DT-3's 'Docs' edits to `web/README.md` (`:5`, `:67`, `:79-80`, `:97`, `:152-154`,
     `:178-195`, `:219-223`) and `web/src/lib/api/README.md`". M1.1 does not touch the root `README.md`:
     its lede is T-docs-Z's, and its CLI bullet is M10's.

4. **Non-blocking. M1.1, with M1.2's exception list (G1), plan :632-638, :717-718.**
   - What: deleting `src/routes/queue/` (B-25) leaves its data path with no consumer: `listIngestJobs`
     (`web/src/lib/api/client.ts:53-55`, its `IngestJob` import at `:14`), `fixtures.ingestJobs`
     (`fixtures.ts:94-115`, import `:12`) and `interface IngestJob` (`types.ts:88-97`). M1.2 then keeps
     `types.ts:94` and `fixtures.ts:101` as named `raw` exceptions, and both are fields of the dead
     `IngestJob`/`ingestJobs`.
   - Why: owner decision 11 deletes obsolete paths rather than hiding them, and B-25 removes the queue
     because its data source has no writer. No web check catches unused exports, so the dead code would
     stay.
   - Correction: M1.1 Modify adds "`src/lib/api/client.ts` loses `listIngestJobs` and its `IngestJob`
     import; `src/lib/api/fixtures.ts` loses `ingestJobs` and its import; `src/lib/api/types.ts` loses
     `IngestJob`". M1.2's exception list becomes `LayerBadges.svelte`, `types.ts:9` and `fixtures.ts:142`.

5. **Non-blocking. M1.3 (G1), plan :765-767.**
   - What: the `scripts/polaris-dev.sh` edit lists `:164,166,179-191` for the status and stop commands. It
     misses `:172` (`echo "Committed Raw revisions: ${repo_dir}/.local/huron/raw"`), which reports the data
     root of the Raw API this task stops launching. The closing `rg` does not match that line.
   - Why: a stale status line about a deleted feature survives, and no check catches it (owner decision 11).
   - Correction: add `:172` to the `polaris-dev.sh` status lines M1.3 removes.

6. **Blocking. M1.4 (G1), plan :906-907 (Modify) and :939 (Verification).**
   - What: M1.4 removes only `:83-108` and `:73`'s "Raw upload" from `docs/getting-started/testing.md`.
     Its check `rg -n '25 GiB' AGENTS.md Makefile docs/getting-started/testing.md` must print nothing, but
     the tier-table row at `:11` (`| acceptance | … | ≥ 25 GiB free disk | minutes |`) lies outside both
     edited ranges.
   - Why: executed as written, the check fails. Passing it means editing a line the task does not list,
     with wording that neither the plan nor DT-23 gives for M1.4–M15, the interval in which the acceptance
     tier has no test.
   - Correction: add to M1.4's `testing.md` edit: "`:11`: the `acceptance` row's requirement cell loses
     '≥ 25 GiB free disk' and reads '—'; M15 rewrites the tier table from DT-23 with the 12 GiB
     requirement".

7. **Non-blocking. M1.4, D2-2 (G1), plan :846-871; follow-on text at :2432-2434 (M7.1) and :3010-3012 (M8.2).**
   - What: no task removes the Raw idempotency receipt kinds from `src/huron/core/foundation/retry.py`. At
     `fa51f46`, `Replay.kind` is `Literal['organization', 'project', 'dataset', 'ingest_session',
     'ingest_commit', 'revision']`, and the `Replay` docstring says "unfinished ingest commits retain their
     reservation beyond TTL". The only writers (`core/raw/_impl/ingest.py`,
     `routes/v1/endpoints/ingest_sessions.py`) and the `ingest_commit` exemption
     (`core/metastore/hierarchy.py:155`) leave in M1.4. M7.1 and M8.2 only add lake kinds, and M8.2 says the
     literal "holds the five lake kinds" without saying that the Raw kinds go. M1.4's closing checks are
     case-sensitive (`IngestSession|INGEST_SESSION`) and do not match the string `"ingest_session"`.
   - Why: a design deletion has no task. "DT-14 deletions" (design:8818-8820) deletes the docstring line
     with DT-2's exemption and says the literal "keeps only kinds that still have a writer". Without the
     edit, three dead literal values survive to the end state (owner decision 11), and no check catches
     them.
   - Correction: add to M1.4 Modify: "`src/huron/core/foundation/retry.py`: `Replay.kind` loses
     `"ingest_session"`, `"ingest_commit"` and `"revision"` (their writers leave in this task); the `Replay`
     docstring loses 'unfinished ingest commits retain their reservation beyond TTL' with the
     `ingest_commit` exemption (DT-14 deletions; DT-2 D2-2); `tests/unit/test_foundation_retry.py`
     follows." Add to M1.4 Verification: `rg -n '"(ingest_session|ingest_commit|revision)"' src/huron`
     prints nothing. Reword M8.2 :3010 to "`Replay.kind` holds the three legacy kinds and the five lake
     kinds".

8. **Non-blocking. M1.4 and M1.6 (G1), plan :905-906 (M1.4) and :1057-1062 (M1.6).**
   - What: lines that name deleted settings or routes survive the tasks that delete those settings and
     routes, and no check scans them. M1.4 deletes `completion_max_concurrent` and
     `completion_reserve_bytes` but removes only the `HURON_INGEST_SWEEP_*` rows, so
     `local-development.md:162-163` (`HURON_COMPLETION_*`) stay. M1.6 deletes `password_login_enabled`,
     `session_cookie_name`, `OidcSettings.client_secret`/`redirect_url`/`scopes` and the `/auth` router,
     but its doc edits cover only the four `dev.env` variables. That leaves `local-development.md:166-168`
     (`HURON_OIDC__CLIENT_SECRET` and the other deleted OIDC fields, `HURON_PASSWORD_LOGIN_ENABLED`,
     `HURON_SESSION_COOKIE_NAME`), `local-development.md:185` (`curl … /auth/session`), the `Makefile:81`
     help ("the URL HURON_WEB_APP_URL in dev.env points at") and `design/api.html:116` (the
     `GET /auth/session` row). DT-26 schedules the api.html §1 and "Authenticating in development" rewrites
     with DT-6 (M9).
   - Why: the plan-wide clean-sweep rule (owner decision 11) deletes every document line that names a
     removed setting, route or variable in the same task. Read literally, M1.4 and M1.6 leave operator
     docs, a Makefile help line and the design record describing removed things for up to seven
     milestones.
   - Correction: M1.4 Modify: `local-development.md` also loses the `HURON_COMPLETION_MAX_CONCURRENT` and
     `HURON_COMPLETION_RESERVE_BYTES` rows. M1.6 Modify: `local-development.md` loses every row naming a
     deleted field (`:166-168`) and the `/auth/session` curl example (`:183-186`; DT-6 writes the
     replacement in M9); the `Makefile:81` help drops the `HURON_WEB_APP_URL` clause; `design/api.html` §1
     loses the `/auth/session` row (DT-6 rewrites §1 in M9). Extend the verification `rg` to
     `dev.env docker-compose.yml Makefile docs/getting-started design/api.html` and add
     `HURON_PASSWORD_LOGIN_ENABLED|HURON_SESSION_COOKIE_NAME|HURON_COMPLETION_|/auth/session` to its
     pattern.

9. **Blocking. M1.4, M1.5, M1.6 and M2.1: the duplication baseline (G1), plan :254-258 (rule), :997-998
   (M1.5), :1209-1212 (M2.1); M1.4 (:824-944) and M1.6 (:1002-1096) have no baseline step.**
   - What: the plan caps hand-edited new or changed clone signatures at four for G1, and only M1.5 and
     M2.1 schedule baseline edits. `scripts/check_duplication.py` `_regressions` (`:352-371`) reports any
     scanned signature whose file tuple is absent from the baseline as "new clone group". Deleting files
     out of a multi-file clone group therefore leaves a subset signature that counts as new, even though
     the total falls. A scratch run of pyscn 1.31.1 at threshold 0.80, on a copy of `src` with M1.3–M1.6's
     whole-file deletions and the M1.5 and M2.1 renames, classified against
     `scripts/duplication_baseline.json` with `_regressions`, reported: new `('core/hierarchy/_impl/creation.py',)`
     (as `core/catalog/…` after M1.4); new `('core/hierarchy/types.py',)`; new
     `(metastore/hierarchy.py, metastore/principals.py)` (M1.4); new
     `(metastore/api_keys.py, metastore/memory_principals.py, metastore/principals.py)` (M1.6); new
     `(rawstore/generations.py, rawstore/materialize.py)` (M1.5); grown
     `(metastore/hierarchy.py, metastore/rbac.py)` from 2 to 8 (M1.4). The simulation did not apply the
     partial edits, so these counts are approximate.
   - Why: M1.4 and M1.6 end with a red duplication guard and no step that edits the baseline. Across G1
     the likely total is about six signatures, two more than the plan-wide rule allows. The fifth
     acceptance is forbidden, so execution stops at M1.6 or M2.1.
   - Correction: in M1.4 and M1.6 add a step: "clone groups that lose a deleted member are re-signed by a
     reviewed hand edit of `scripts/duplication_baseline.json` (expected: hierarchy+principals and
     hierarchy+rbac in M1.4; api_keys+memory_principals+principals in M1.6), each recorded under Execution
     notes". In the plan-wide rule (:254-258), either exempt from the four-signature cap the signatures
     whose files are a subset of a baseline signature that lost a deleted file, together with pure
     re-paths of renamed files, or raise G1's cap to eight.

10. **Non-blocking. M1.6 (G1), plan :1031, :1075-1080.**
    - What: the scripts half of the closing check lists the lines it may still print, and the list is
      incomplete. At HEAD, after M1.3's removals, it also prints `scripts/polaris_dev.py:160`
      (`"client_secret": credentials["clientSecret"]`, Polaris bootstrap credentials),
      `scripts/polaris-dev.sh:82` (Polaris `initdb --pwfile`), and `:168` and `:170` (the web account
      store's `initial-admin.json` and `topic-demo-accounts.json` password files). Separately,
      `scripts/keycloak/huron-realm.json:22` (the client description naming `/auth/oidc/start,
      /auth/oidc/callback`) must change for `rg -n 'auth/oidc/callback' scripts` to print nothing, but
      Modify names only the redirect URI.
    - Why: a verifier comparing the output with the listed exceptions fails the task. An implementer told
      to remove the extra lines could delete the web account-store messages, which owner decision 10 keeps.
    - Correction: extend the exception list with `scripts/polaris_dev.py:160` (Polaris `client_secret`),
      `scripts/polaris-dev.sh:82` (Polaris `--pwfile`) and the web account-store status lines (`:168`,
      `:170`). Add to Modify: "`huron-realm.json`'s client description (`:22`) no longer names
      `/auth/oidc/start` or `/auth/oidc/callback`".

11. **Blocking. M2.1 (G1), plan :1196-1206; head line :219.**
    - What: the rename's contract edits cover 2, 4–6, 10, 11, 13 and 14, plus contract 8's name. Contract 9,
      "rawstore uses schema only" (`pyproject.toml:229-234`), still forbids `"huron.core.catalog"` after
      M1.4 removes `huron.core.raw` from it.
    - Why: `lint-imports` silently skips a forbidden module that is missing from the graph (import-linter
      `forbidden.py:99-102`), so the gate stays green. But M2.1's own check
      `rg -n 'huron\.core\.catalog|core/catalog' … pyproject.toml …` (:1229) must print nothing, and it
      prints contract 9's line. The clean-sweep rule allows only the tool-config changes the plan names, so
      an implementer cannot both keep to the contract list and pass the check.
    - Correction: add to M2.1's `pyproject.toml` list: "9: forbidden `huron.core.catalog` →
      `huron.core.hierarchy` (the rest of 9 is unchanged until M11.2)". Change head line :219 to "the
      rename (M2) changes contracts 2, 4–6, 9 (the renamed forbidden entry), 10, 11, 13 and 14 without
      changing the count".

12. **Non-blocking. M4.1 (G2), plan :1583-1589 (Modify, contracts) and :1532 (M4 intent); M2 at :1200-1201.**
    - What: contract 6 never gets `huron.core.lake` in its forbidden list. DT-1's contract table row 6
      (design:1556) sets the end state to forbidden `huron.core.{lake,metastore,rawstore}`, `huron.schema`
      for source `huron.core.hierarchy`. M2 rightly leaves `lake` out because the package does not exist
      yet. M4.1 then adds `lake` only to contracts 4 and 5, and the M4 intent lists the lake entries of 2,
      4, 5, 8, 9, 10, 11 and 13. No later task touches contract 6. DT-1's landing paragraph (design:1578)
      leaves 6 out too, so the gap starts in the design.
    - Why: a designed contract has no task. Nothing else stops a `hierarchy → lake` edge: contract 2 is an
      exhaustive sibling list, contract 3 sees no cycle because contract 7 already forbids
      `lake → hierarchy`, and contract 13 forbids only `metastore` and `rawstore`. The plan would end
      without DT-1's row-6 guard, and the gate would stay green.
    - Correction: in M4.1 Modify `pyproject.toml`, write "contracts 4, 5 and 6 forbid `huron.core.lake`"
      (contract 6's forbidden list becomes `huron.core.{lake,metastore,rawstore}`, `huron.schema`). In the
      `tests/unit/test_domain_import_contracts.py` bullet, add the forbidden edge `hierarchy → lake`
      ("hierarchy uses security and foundation only" BROKEN). Add 6 to the lake entries at :1532. The count
      stays at 17.

13. **Non-blocking. M5.3 (G2), plan :1878-1885 (`tests/unit/test_fake_company_idp.py`, second half).**
    - What: no task pins the fake issuer's `nonce` echo. DT-22's test table (design:13982) verifies
      ID-token claims "(`aud`, `nonce`, `sub` = fixture `id`, …)", and DT-19's handoff row to DT-22
      (design:12345) requires "ID tokens with … the `nonce` echoed". DT-22's token route also requires a
      refreshed `id_token` "without `nonce`". M5.2's first half rightly omits nonce because no authorize
      route exists yet. M5.3 binds the code to `nonce`, but its case list asserts neither the echo nor its
      absence after a refresh.
    - Why: a test from DT-22's test table has no task. M10's CLI login checks the nonce against this fake
      (DT-19). A fake that never echoes it, or echoes it on refresh, would pass M5's gate and fail first in
      M10, far from its cause.
    - Correction: add to M5.3's `tests/unit/test_fake_company_idp.py` (second half): "the
      `authorization_code` grant's `id_token`, verified with PyJWT against the served JWKS, carries the
      authorize request's `nonce`; an authorize request without `nonce` yields an `id_token` without one; a
      `refresh_token` grant's new `id_token` carries no `nonce`".

14. **Non-blocking. M7.2 and M7.3 (G3), plan :2514-2518 (M7.2 `InMemoryMetadataSchemas`: "the name and
    `sha256` CHECKs") and :2581-2587 (M7.3 `InMemoryCatalogs`: "the name CHECK").**
    - What: the in-memory halves must apply the `name ~ '^<SEGMENT>$'` CHECKs of `lake.metadata_schemas`
      and `lake.catalogs`, because DT-17's fake checks every CHECK a Python value can violate. Contract 8
      ("metastore uses hierarchy lake security and foundation only", which forbids `huron.core.rawstore` and
      `huron.schema` and which M4.1 and DT-1 keep) forbids `huron.core.metastore.lake` to import
      `huron.schema.naming` directly. DT-1 and DT-8 forbid a second copy of `SEGMENT_PATTERN` in `src/`. The
      plan names no permitted path to the rule.
    - Why: the obvious implementation, importing `SEGMENT_PATTERN` or `check_segment` from
      `huron.schema.naming` in `metastore/lake/catalogs.py`, turns `uv run lint-imports` red. The other
      obvious option, copying the regex, breaks the one-copy rule. The implementer has to invent a lake-side
      seam the plan does not name.
    - Correction: in M7.2 (or M7.3), give `src/huron/core/lake/types.py` the way the fake checks a segment
      through `huron.core.lake`, which contract 8 allows: for example `CatalogRecord.__post_init__` and
      `MetadataSchemaRecord.__post_init__` call `naming.check_segment`, or a public
      `lake.types.is_segment(value)` wraps it. State that the fake's name CHECKs go through it and raise
      `IntegrityViolation` with the PostgreSQL constraint name. Add to both tasks' verification:
      `rg -n "huron\.schema" src/huron/core/metastore` prints nothing.

15. **Blocking. M7.4, with its root in M1.4's D2-2 (G3), plan :2621-2677 (M7.4) and M1.4 Modify (:845-900);
    design:4890, :5193, :5255-5259 (DT-8 deletions).**
    - What: DT-8 deletes `PathRuleViolation.__init__`'s code-override constructor
      (`src/huron/core/foundation/errors.py:89-101`) "in the same change as DT-2's removal of
      core/raw/manifest.py", so that the class inherits `DomainError.__init__(detail, *, context=None)`. No
      task does this; `PathRuleViolation` and `code_or_detail` appear nowhere in the plan. At HEAD the
      constructor is `__init__(self, code_or_detail, path=None)` and sets only `context={"path": path}`.
      M7.4's `Catalogs.create` must raise `PATH_RULE_VIOLATION` with `context={"rule", "value"}` (DT-8's
      naming translation; M7.4's test "a bad create name → PATH_RULE_VIOLATION with {rule, value}"), and the
      constructor has no `context` keyword.
    - Why: M7.4 cannot pass its own test with the files it lists: the call raises `TypeError` or carries
      the wrong context. A design deletion has no task, the dead per-instance-code mode survives (owner
      decision 11), and M11's `?under=` translation inherits the same gap.
    - Correction: add to M1.4 (D2-2) Modify: "`src/huron/core/foundation/errors.py`:
      `PathRuleViolation.__init__` (the code-override mode, `:89-101`) is deleted; the class keeps
      `code = "PATH_RULE_VIOLATION"` and `status_code = 400` and inherits
      `DomainError.__init__(detail, *, context=None)` (DT-8 deletions, R8-4); `tests/unit/test_catalog_errors.py:33`'s
      two-argument case is deleted." Add to M1.4 Verification: `rg -n "code_or_detail" src tests` prints
      nothing. In M7.4 Design, cite "DT-8 deletions". In M7.4 Verification, the bad-name case asserts
      `error.context == {"rule": "segment", "value": <name>}`.

16. **Non-blocking. M7.6 (G3), plan :2742-2766 (Modify: `role_mappings.py`, `memory.py`,
    `tests/lake_store_contract.py`); seeding seam created at :1656-1663 (M4.2) and used at :1698 (M4.3) and
    :2070 (M5.6).**
    - What: M7.6 changes the fake's `group_role_map` row from a stored `CatalogRef` to "the catalog id
      joined to `InMemoryCatalogs`" and adds the catalog FK as an `IntegrityViolation`. It never updates
      M4.2's `LakeSeed.role_mapping(group, catalog: CatalogRef | None, role)` or `MemorySeed`. Earlier tests
      seed catalog-scoped mappings for catalogs with no `catalogs` row: M4.2's role-mapping scenarios ("a
      catalog row … returned with their catalog id and name"), M4.3's `test_lake_access.py` (DT-4 "Catalog
      grant" and "Emptied mapping") and M5.6's exchange tests.
    - Why: once the join exists, `roles_for_groups` cannot produce the catalog name for those rows. The
      scenarios in `tests/unit/test_lake_memory_store.py` (M7.6's own verification command) and the earlier
      access and exchange tests then fail, so the unit gate goes red, and the file list does not say which
      seam fixes it. M8.4's `PostgresSeed` faces the same FK.
    - Correction: add to M7.6 Modify: "`tests/lake_store_contract.py`: `LakeSeed` gains
      `catalog(ref: CatalogRef)`; `MemorySeed.catalog` writes a `CatalogRecord` row into
      `LakeTables.catalogs` directly. `role_mapping` with a catalog requires that row (the fake now joins
      it). M4.2's role-mapping scenarios, `tests/unit/test_lake_access.py` (the M4.3 and M7.3 cases) and
      M5.6's `tests/unit/test_token_exchange.py` seed the catalog before mapping it." Add to M8.4 that
      `PostgresSeed.catalog` inserts the catalog together with its config and schema rows, as the FKs
      require.

17. **Non-blocking. M8.1 (G4), plan :2911-2915 (delete every Alembic `Config` in
    `test_retire_legacy_raw.py`), :2925 (use `migrate` and `downgrade`), :2931-2932 (`rg` check).**
    - What: M1.7's `test_offline_sql_renders_the_drops` renders `upgrade 0013_retire_releases:head --sql`
      (design:2197, B-18), which needs an Alembic `Config` and `command.upgrade(..., sql=True)`. DT-17's
      helpers `migrate(url, revision)` and `downgrade(url, revision)`, whose signatures M8.1 calls exact,
      cannot render offline SQL, because a range revision is invalid online. M8.1 also deletes the module's
      `Config` and requires `rg -n 'def _migrate|^MIGRATIONS_DIR|command\.(upgrade|downgrade)' tests` to
      print only `tests/postgres.py` lines.
    - Why: the offline case cannot survive M8.1 as written. Keeping it fails the `rg` check, converting it
      to `migrate()` is impossible, and dropping it deletes a test DT-2 requires (B-5: "tests cover …
      offline rendering").
    - Correction: add to M8.1 Modify: `test_offline_sql_renders_the_drops` renders through the Alembic CLI
      in a subprocess, with no `Config` and no `command.` call:
      `subprocess.run([sys.executable, "-m", "alembic", "upgrade", "0013_retire_releases:0014_retire_legacy_raw", "--sql"], cwd=<repo root>, capture_output=True, text=True, check=True)`,
      then asserts the `DROP` statements in stdout. `uv run python -m alembic heads` works at HEAD.

18. **Non-blocking. M8.2 (G4), plan :2953-2955 (`refuse_if_rows` argument order) and :2963-2967
    (`test_upgrade_downgrade_round_trip`).**
    - What: the plan fixes the guard order parents-first (`ldap_groups`, `signing_keys`, `audit_log`,
      `idempotency_records`, `metadata_schemas`, `catalogs`, `catalog_configs`, `group_role_map`) and
      requires that "with one row in each writer table in turn, downgrade raises RuntimeError naming that
      table". A `group_role_map` row needs an `ldap_groups` row (FK), and a `catalogs` row needs its
      `catalog_configs` row (the deferred `catalogs_current_config` FK) and a `metadata_schemas` row. So the
      guard names `ldap_groups` or `metadata_schemas`, never the table under test. An `audit_log` row also
      cannot be removed: the statement-level `audit_log_append_only` trigger refuses `DELETE` and
      `TRUNCATE`, and the downgrade that would drop the table refuses. Running the cases "in turn" in one
      database contaminates every later case.
    - Why: the assertion cannot hold for `group_role_map`, `catalogs` or `catalog_configs` under the
      dictated order, and every case after the `audit_log` case sees `audit_log` non-empty. The implementer
      must break either the argument list or the test.
    - Correction: write the guard children-first, matching the reverse-order drops:
      `refuse_if_rows("lake.group_role_map", "lake.catalog_configs", "lake.catalogs", "lake.metadata_schemas", "lake.idempotency_records", "lake.audit_log", "lake.signing_keys", "lake.ldap_groups")`.
      State the case as: "for each writer table, in a fresh database migrated to head, insert one row there
      plus the minimal rows its foreign keys require; downgrade raises `RuntimeError` naming the first table
      in the guard's list that holds a row, which is the table itself, except that a `lake.catalogs` row
      always comes with its `lake.catalog_configs` row and is reported as `lake.catalog_configs`;
      `alembic_version` stays at head."

19. **Non-blocking. M8.5 (G4), plan :3201, :3210-3213, :3229-3230; conflicts with the plan head (:332) and
    M16.1 (:6242-6250).**
    - What: M8.5 gives `PostgresAudit` "AuditReader on the root", which reads one object's history newest
      first, and creates `test_collection_log_paging`. The head (:332) and M16.1 say the `AuditReader` port
      and `collection_log` are M16.1's, and M16.1 adds `PostgresAudit.collection_catalog` and
      `collection_log` again. M8.5 never names its reader method or signature and adds no port or in-memory
      reader. DT-7's `test_collection_log_paging` row (design:4726) also asserts `collection_catalog`, which
      M8.5 does not create.
    - Why: a fresh implementer cannot tell which method M8.5 writes or what M16.1 then adds. With no port
      and no fake, the reader also breaks DT-17's port → adapter → fake pairing. M16.1's "completed, not
      duplicated" note does not say which names already exist.
    - Correction: in M8.5, name DT-7's method:
      `PostgresAudit.collection_log(collection_id: UUID, *, before: int | None, limit: int) -> Window[AuditRecord]`
      (`object_type = 'collection'`, `id < before`, `ORDER BY id DESC`, `limit + 1`), and limit
      `test_collection_log_paging` to its paging clauses, without `collection_catalog`. In M16.1, the
      `audit.py` bullet adds only `PostgresAudit.collection_catalog`, the `AuditReader` port on `LakeStore`,
      the in-memory reader half and the `collection_catalog` clauses of the test. The alternative is to move
      the reader and `test_collection_log_paging` to M16.1 entirely, with M11's clause.

20. **Non-blocking. M8.6 (G4), plan :3287 ("typed assignments to the two composites, which mypy and ty
    check") and :3317-3318.**
    - What: `pyproject.toml` sets `[tool.mypy] files = ["src"]` and `[tool.ty.src] include = ["src"]`, and
      the gate runs `uv run mypy` and `uv run ty check` without paths. Neither checker reads
      `tests/unit/test_lake_ddl_sync.py` or `tests/unit/support.py` (`memory_stores()`), so the typed
      assignments and "mypy and ty accept … `memory_stores()` building `ApiStores(lake=…)`" are never
      type-checked. Only `_postgres_stores` in `app.py` is, which covers `PostgresLakeStore` and, through
      `transaction()`'s return type, `PostgresLakeTransaction`.
    - Why: the verification claims a structural conformance of `InMemoryLakeStore` and
      `InMemoryLakeTransaction` that no gate command checks, so a verifier cannot confirm it.
    - Correction: replace the typed-assignment bullet with a runtime check in `test_lake_ddl_sync.py`,
      using M4.1's `inspect.signature` conformance: every public member of `LakeStore` and `LakeTransaction`
      exists, with the same parameter names and kinds, on `PostgresLakeStore`, `InMemoryLakeStore`,
      `PostgresLakeTransaction` and `InMemoryLakeTransaction`. Reword the verification to "mypy and ty
      accept `_postgres_stores` building `ApiStores(lake=PostgresLakeStore(pool, clock))`", with the
      in-memory side covered by the runtime check.

21. **Non-blocking. M9.1 (G4), plan :3386-3445 (Modify) against :3406-3407 and :3475.**
    - What: the task changes the constructor to
      `OidcResolver(company_tokens.verify, directory, subject_claim=…)` and deletes `groups_claim`, and the
      legacy bearer takes its groups from `GroupDirectory.groups_for` (401 for an unknown user, 503 for an
      outage; DT-6, design:4083-4093; B-28). The Modify list does not name
      `src/huron/core/security/oidc.py`, where the class lives; at HEAD its constructor takes
      `subject_claim="sub"` and `groups_claim="groups"`. The list also omits the tests that construct
      `OidcResolver` (`tests/unit/test_auth_oidc.py:126,135`, `tests/unit/test_authorization_credentials.py:226`,
      `tests/unit/test_security_authentication.py:230`) and `tests/unit/test_api_main.py`, which builds
      settings from the environment with `HURON_AUTH_MODE` (`:28`, `:55`) rather than through
      `ApiSettings(`, so the task's `rg ApiSettings\(` sweep misses it.
    - Why: mypy fails on `app.py` until `oidc.py` changes. The task's own checks
      (`rg … groups_claim|AUTH_MODE … src tests`, and `CLIENT_ID = "huron-web"` at `test_auth_oidc.py:44`
      under the realm `rg`) cannot pass without editing unlisted files. The cited design section
      ("`oidc.py`: the legacy bearer, re-wired") lets an implementer recover the core change, but the file
      list does not.
    - Correction: add to M9.1 Modify: `src/huron/core/security/oidc.py`:
      `OidcResolver(verify, groups: GroupDirectory, *, subject_claim: str)` resolves the principal by
      `subject_claim`, fullmatched against `COMPANY_USERNAME`, and takes groups from
      `await groups.groups_for(subject)`: `None` raises `AuthError` (401) and `DependencyUnavailable`
      propagates (503); the `groups_claim` parameter and attribute are deleted and the module docstring
      follows. Also add: `tests/unit/test_auth_oidc.py` (resolver cases use a `GroupDirectory` stub or
      `fake_groups_transport` rather than a token groups claim; `CLIENT_ID` `'huron-web'` goes);
      `tests/unit/test_authorization_credentials.py` and `tests/unit/test_security_authentication.py` (the
      constructions gain the directory); `tests/unit/test_api_main.py` (drops `HURON_AUTH_MODE` and sets
      `HURON_COMPANY_IDP__ISSUER`, `HURON_COMPANY_IDP__AUDIENCES`, `HURON_GROUP_DIRECTORY__URL_TEMPLATE`,
      `HURON_TOKENS__ISSUER` and `HURON_TOKENS__KEY_DIRECTORY` in both cases). Add the `oop-design` skill
      for the core edit.

22. **Non-blocking. M9.1 (G4), plan :3463-3466 ("`make -n up stack dev-keys api` shows … HURON_UID and
    HURON_GID are exported").**
    - What: `make -n` prints recipe commands only, never `export VAR := …` directives. A scratch Makefile
      with `export HURON_UID := $(shell id -u)` printed only its recipe line under `make -n`.
    - Why: the stated evidence cannot appear in that command's output.
    - Correction: replace the sub-bullet with: `rg -n '^export HURON_(UID|GID) := \$\(shell id -[ug]\)' Makefile`
      prints two lines, and `make -pn up | rg '^HURON_(UID|GID) :?='` shows both variables defined.

23. **Non-blocking. M9.4, M9.5 and M9.6 (G4), plan :3638-3643 (M9.4 tests), :3727-3732 (M9.5 creates
    `test_api_lake_admin.py` for mapping rows only), :3803-3808 (M9.6 "for the schema-publish and key rows"
    lists key cases only).**
    - What: DT-10's `test_api_lake_admin.py` (design:6352) requires "one parametrized case per row of the
      administration route table: its success status, and each listed problem code with its HTTP status",
      with the audit pair, `object_id`, `catalog_id` and `detail` checked after each write. That table is
      DT-10 rows 1–17, which are DT-18 rows 4–6, 8, 9 and 11–22. The plan assigns only the mapping rows
      (M9.5) and the key rows (M9.6). The catalog rows have no per-code cases anywhere: row 8's 400
      `PATH_RULE_VIOLATION`, 409 `CATALOG_EXISTS` and 422 `CATALOG_CONFIG_INVALID` with its create/catalog
      entry; row 9's 404 and 422 `CATALOG_CONFIG_INVALID` with its catalog_config/catalog entry; row 6's 404
      for an unknown version. Row 19 (schema publish: 201, 200 for an identical republish, 409
      `SCHEMA_VERSION_EXISTS`, 422 `SCHEMA_INVALID`, the schema_publish entry) is named in M9.6's lead-in
      but none of its cases are listed. The schema reads (rows 17 and 18, with 404 and the `sha256` ETag)
      are absent.
    - Why: a design-required test is only partly mapped, so the route-level pins of those problem codes and
      audit entries are never written.
    - Correction: M9.4 creates `tests/unit/test_api_lake_admin.py` (marker `unit`; DT-10's file) with the
      parametrized cases for DT-18 rows 4–6, 8 and 9: each success status, each listed problem code with its
      status, and after rows 8 and 9 the audit entry's pair, `object_id`, `catalog_id` and `detail`. M9.5
      extends the file (Modify, not Create) with rows 11–16. M9.6 lists row 19's 201, 200 republish (no
      entry), 403, 409 `SCHEMA_VERSION_EXISTS`, 409 `IDEMPOTENCY_KEY_REUSED` and 422 `SCHEMA_INVALID` with
      the schema_publish entry, and row 17's success and row 18's 404 and `ETag: "<sha256>"`, beside the key
      cases.

24. **Non-blocking. M9.6 (G4), plan :3797-3802 (`test_lake_routes.py` additions).**
    - What: DT-18's `test_etag_on_reads_and_if_match_on_writes` (design:11431) pins "Rows 8, 19, 21, 25 and
      32 without Idempotency-Key answer 422". Rows 8, 25 and 32 are assigned (M9.4, M11, M13). Rows 19
      (`POST /metadata-schemas`) and 21 (`POST /signing-keys`) land in M9.6, which adds only
      `test_idempotent_replay` for them, and no later task adds them.
    - Why: a design-required pin for two creating routes has no task.
    - Correction: add to M9.6's `tests/unit/test_lake_routes.py` bullet:
      "`test_etag_on_reads_and_if_match_on_writes`: rows 19 and 21 without `Idempotency-Key` answer 422
      `REQUEST_INVALID`".

25. **Non-blocking. M11.5, with M8.2 and M13.4 (G5), plan :4598-4599; :2964-2965 (M8.2) and :5388
    (M13.4).**
    - What: `test_ltree_subtree_with_hyphens` "gains its raw-SQL half", but no earlier task creates it.
      M8.2 creates only the 0015 parts of `test_lake_schema.py` and says the namespace parts land with 0016.
      Separately, M8.2's `test_upgrade_downgrade_round_trip` asserts "exactly ten tables in schema `lake`",
      which becomes 13 at 0016 and 16 at 0017, and neither M11.5 nor M13.4 says so.
    - Why: the task points at a test function that does not exist, and the stale table count turns the
      contract suite red until the implementer works out the new number.
    - Correction: M11.5: "creates `test_ltree_subtree_with_hyphens` with its raw-SQL half" and
      "`test_upgrade_downgrade_round_trip` expects thirteen lake tables". M13.4: "… sixteen lake tables".

26. **Blocking. M11.6, with M11.1 and M11.7 (G5), plan :4634-4635 (M11.6 ports change), :4392-4393 (M11.1
    `CollectionStore`), :4679-4683 (M11.7 adds `search` and `active_paths`).**
    - What: M11.1 declares `CollectionStore` with `catalog_of`, `collection`, `settled_at`, `namespaces`,
      `search` and `active_paths`. M11.6 makes `LakeStore` and `LakeTransaction` inherit `CollectionStore`,
      but its halves implement only `catalog_of`, `collection`, `settled_at` and `namespaces`; `search` and
      `active_paths` arrive in M11.7.
    - Why: M4.1's structural-conformance case requires every public member of each Protocol on its fake
      with the same parameters, and M11.6's verification runs it, so `tests/unit/test_lake_memory_store.py`
      fails. `uv run mypy` also fails on `_postgres_stores` (`ApiStores(lake=PostgresLakeStore(...))`)
      because `search` and `active_paths` are missing. The gate is red at M11.6.
    - Correction: M11.1 declares `CollectionStore` with `catalog_of`, `collection`, `settled_at` and
      `namespaces` only. M11.7 Modify adds "`src/huron/core/lake/ports.py`: `CollectionStore` gains `search`
      and `active_paths`", in the same commit as their halves. The alternative is to move the `search` and
      `active_paths` halves into M11.6's Create list.

27. **Non-blocking. M11.7 (G5), plan :4679-4682.**
    - What: `set_states(changes)` is "version-guarded", but nothing says where the guard version comes from.
      DT-17's correctness model lists `set_states` among the writes whose ids must already be in the
      transaction's lock record, which only `lock_collection`, `lock_collections` (M16) and `lock_commit`
      fill. DT-9's `SettledCollection` carries no `version`, and
      `recompute_completeness(tx: CompletenessWriter, …)` cannot call `lock_collection`. DT-14's final
      commit transaction bumps `version` without the catalog lock, so an unlocked scan can race a commit.
    - Why: applied literally, DT-17's rule makes every recompute raise `LockContractBroken`. With an
      unlocked scan, a commit landing mid-recompute makes the guarded update match zero rows, a 500 on
      `PUT /catalogs/{c}/config`. The implementer must invent the locking scheme.
    - Correction: M11.7: `scan_settled` selects each batch `FOR UPDATE` (the fake takes the per-collection
      locks) and records `id → version` in the transaction's lock record, and `set_states` guards on the
      recorded version. Add a store-contract scenario: `set_states` on an id that `scan_settled` did not
      return raises `LockContractBroken`. Add to M13.4's files area a Postgres-only race: `apply_plan`
      against a running recompute, where one waits and both apply.

28. **Blocking. M13.5, with M11.8, M13.3, M13.7 and M11.12 (G5), plan :5426-5438 (M13.5 `claim` and
    `extend` on `PostgresCommits`/`InMemoryCommits`; `LakeStore` gains `CommitQueue`) and :4717-4725 (M11.8
    `claim`, `extend` and `complete` on the access-reset halves; `LakeStore` gains `AccessResetQueue`).**
    - What: both queue ports sit on the `LakeStore` root and share method names with different signatures:
      `AccessResetQueue.claim(owner, lease) -> AccessResetClaim | None` and `extend(claim, lease)`
      (design:6813-6816); `CommitQueue.claim(owner, lease, *, max_verify_bytes) -> tuple[CommitRecord, CommitLease] | None`
      and `extend(lease, duration, flushed)` (design:8555-8565). Neither the plan nor the design renames
      either.
    - Why: mypy and ty reject the `LakeStore` Protocol because its bases define incompatible `claim` and
      `extend`. DT-17's test that no two halves of a composite define the same public name (M8.6 :3283;
      M13.5's verification) fails. In the mixin MRO one queue's method shadows the other, so
      `AccessResetWorker` or `CommitWorker` would call the wrong `claim`. The gate is red at M13.5.
    - Correction: rename one queue's methods in the task that declares them. Recommended: in M13.3,
      `CommitQueue` gets `claim_commit`, `extend_commit`, `commit_checks`, `release_commit`, `fail_commit`,
      `expire_commits` and `prune_commits`; M13.5's halves and contract area (C15, C16), M13.7's
      `Commits.work` and `housekeep`, and the crash-matrix text follow. Record the rename in DT-14's port
      block and DT-17's port table in the same change. The alternative is `claim_access_reset`,
      `extend_access_reset` and `complete_access_reset` in M11.1, M11.8 and M11.12.

29. **Blocking. M13.4 and M13.5, failing at M17's findings half (G5), plan :5377-5381 and :5386-5387 (M13.4
    `FileStore.page` on `LakeStore`), :5426-5432 (M13.5 `CommitQueue.prune` on `LakeStore`), M17.1
    (:6539-6542, `PostgresFindings`/`InMemoryFindings` with `prune` and `page`).**
    - What: DT-16's `FindingStore` (`page(catalog_id, *, open_only, after, limit)` and
      `prune(resolved_before, *, limit)`, design:9624-9631) is another `LakeStore` root port (DT-17's port
      table). It reuses the names that M13 gives `FileStore.page(collection_id, *, after, limit)`
      (design:8060) and `CommitQueue.prune(finished_before, *, limit)`, with different signatures.
    - Why: when M17 composes the findings half into `PostgresLakeStore` and `InMemoryLakeStore`, the same
      incompatible-base error (mypy, ty), the same no-shared-name test failure and the same shadowing occur.
      The gate is red at M17, and the fix reaches into done M13 tasks.
    - Correction: choose distinct names where M13 declares them, for example `FileStore.file_page` (M13.2
      port, M13.4 halves, M13.6 `Files.list`) and `prune_commits` (defect 28). Alternatively M17 names its
      methods `finding_page` and `prune_findings`. Either way the plan states the choice, and DT-13, DT-14
      or DT-16 and DT-17's port table are updated in the same change.

30. **Non-blocking. M13.9, with M13.6 (G5), plan :5577-5578 (M13.9 `wake()` only after a fresh 202) and
    :5477 (M13.6 `submit`).**
    - What: DT-14's `Commits.submit` returns a bare `CommitView` for both a fresh accept and an
      `Idempotency-Key` replay. M13.9 calls `runtime.commit_worker.wake()` only after a fresh 202, and
      `test_commit_accept_and_poll` asserts exactly one wake (DT-18: "A replayed key does not call it").
    - Why: with the interface as designed the route cannot tell a replay from a fresh accept, so the
      implementer must change a design interface without guidance.
    - Correction: M13.6: `submit` returns a value that carries the distinction, for example
      `Submission(view: CommitView, replayed: bool)`, recorded in DT-14's `Commits` block. M13.9 calls
      `wake()` only when `not replayed`, and `test_idempotent_replay` for row 32 asserts that a replay does
      not wake the worker.

31. **Non-blocking. M13.9 (G5), plan :5598-5599, :5610.**
    - What: the closing check `rg -n -i 'commit raw revisions' design/rbac.html` cannot detect the `:431`
      line, which reads "commits raw revisions" at HEAD.
    - Why: the check passes even if the `:431` replacement is never made.
    - Correction: `rg -n -i 'commits? raw revisions' design/rbac.html` prints nothing.

32. **Non-blocking. M10.1 (G6), plan :3889-3903 (`state.py`), :3974-3975 (`rg` check), :3981
    (`test_lock_contention_times_out_with_state_error`).**
    - What: DT-19 rule 3 polls `LOCK_NB` every 100 ms for at most 60 s. `StateDir(root)` has no injected
      sleep or clock, and the check
      `rg -n "os\.environ|sys\.argv|datetime\.now\(|time\.sleep|httpx\.Client\(" src/huron/applications/cli`
      allows those names only in `__init__.py`. The plan names the `_stat` and `_getaddrinfo` seams but no
      seam for the lock's wait.
    - Why: a `time.sleep` in `state.py`, or a module alias `_sleep = time.sleep`, fails the check. Without
      an injected wait, the contention test sleeps 60 s of real time. The implementer must invent an
      interface that neither the plan nor the design gives.
    - Correction: in M10.1's `state.py` bullet add: "`StateDir(root, *, sleep: Callable[[float], None], monotonic: Callable[[], float])`
      and `StateDir.locate(environ, *, sleep, monotonic)`; the lock waits through them; `main()` passes
      `time.sleep` and `time.monotonic`; the harness passes the recorded sleep and a monotonic reading of
      the root `clock`". State that `test_lock_contention_times_out_with_state_error` reaches the 60 s
      bound through the recorded sleeps.

33. **Non-blocking. M10.2 (G6), plan :4003-4004 (Create, `oidc.py`, `Discovery.parse`).**
    - What: the plan says `Discovery.parse` is "the four-member check and exact issuer match of `fa51f46`
      `oidc.py:193-219`". At `fa51f46`, `_REQUIRED_DISCOVERY_FIELDS` is (`issuer`,
      `authorization_endpoint`, `token_endpoint`, `jwks_uri`). DT-19 ("`oidc.py`: the company OIDC
      provider") requires only `issuer`, `token_endpoint` and `jwks_uri`, makes `authorization_endpoint` and
      `device_authorization_endpoint` optional, and has the flow that needs a missing endpoint raise
      `LoginFailed(reason="flow_unsupported")` before any prompt.
    - Why: implemented literally, a discovery document without `authorization_endpoint` is refused with
      reason `discovery`, and DT-19's `test_cli_oidc.py` row, which M10.2 adopts ("flow endpoint absent →
      flow_unsupported"), fails. Plan and design disagree, and the implementer must stop and pick one.
    - Correction: "`Discovery.parse`: DT-19's rule. `issuer`, `token_endpoint` and `jwks_uri` are required,
      with an exact issuer match (the check of `fa51f46` `oidc.py:201-219` without
      `authorization_endpoint`). `authorization_endpoint`, `device_authorization_endpoint` and
      `revocation_endpoint` are optional; a flow whose endpoint is absent raises
      `LoginFailed(reason="flow_unsupported")` before any prompt. Every endpoint passes `state.py`'s
      transport rule."

34. **Non-blocking. M12.2, M18.2 and M18.3 (G6), plan :5122-5150 (M12.2 Modify), :6880-6890 (M18.2
    Modify), :6945-6975 (M18.3 Modify).**
    - What: every other task that adds a top-level verb or group names its registration in
      `src/huron/applications/cli/commands/__init__.py` (M10.4, M10.5, M10.6, M10.7, M12.3, M14.2, M14.4).
      M12.2 creates the `describe` group (`describe collection`), M18.2 adds `mv` and M18.3 adds `log` and
      `check`, and none of them lists the registration.
    - Why: unregistered verbs are unreachable. M18.3's check that `uv run huron --help` lists every
      top-level verb of DT-19, DT-20 and DT-21 fails, as do the CliRunner tests of `describe`, `mv`, `log`
      and `check`. The file that must change is missing from each list.
    - Correction: add `src/huron/applications/cli/commands/__init__.py` to each Modify list: M12.2 registers
      the `describe` group, M18.2 registers `mv`, and M18.3 registers `log` and `check`.

35. **Non-blocking. M14.1, also M18.3, with the root in M10.3 (G6), plan :5650-5653 (`sync.pull`: the last
    page's `collection_version`), :6960 (`check`: row 37's `status`), :4063-4064 (M10.3 "the one paging
    loop").**
    - What: `HuronClient.pages` yields items only (M10.3; DT-19 `pages(...) -> Iterator[Mapping]`). Two
      later tasks need members of the page envelope: `pull` needs `FilePage.collection_version` from row
      31, and `check` needs `FindingsPage.status` from row 37 (DT-18: `FilePage(Page[FileBody])` with
      `collection_version`; `FindingsPage(...)` with `catalog` and `status`). Neither task says how it
      reads them.
    - Why: the implementer of M14.1 or M18.3 either writes a second `after`/`next_cursor` loop over
      `client.get`, contradicting M10.3's "one paging loop" and DT-18's handoff, or changes `client.py`,
      which DT-19 says verbs never touch. Either way they decide an interface the plan leaves open.
    - Correction: M14.1 Modify adds `src/huron/applications/cli/client.py`:
      `HuronClient.page_bodies(path, *, params)` yields each page body (envelope) through the existing loop,
      and `pages` is re-expressed over it, keeping one loop; add a case to
      `tests/unit/cli/test_cli_client.py`. `sync.pull` reads `collection_version` from the last body. M18.3
      says that `check` reads `status` from row 37's first page body through `page_bodies`.

36. **Non-blocking. M15.2 (G7), plan :6012 (`Makefile`: target `test-nfs` with DT-23's recipe);
    design:14256.**
    - What: DT-23's recipe is
      `NFS_VOLUME_ID=$$(uuidgen) ./scripts/loopback_nfs.sh up && uv run pytest -m "nfs and not acceptance"`.
      `up` only prints the three `HURON_TEST_NFS_*` lines to stdout, and
      `tests/nfs_support.nfs_mount_from_environment()` reads them from the environment. CI works because it
      appends stdout to `$GITHUB_ENV`; the make recipe never exports them.
    - Why: on a Linux developer machine `make test-nfs`, the B-11 command that AGENTS.md documents, always
      fails with "missing variable" before any NFS case runs. No local gate catches it, because macOS runs
      only `make -n`.
    - Correction: the recipe, as one shell line:
      `set -a; eval "$$(NFS_VOLUME_ID=$$(uuidgen) ./scripts/loopback_nfs.sh up)"; set +a; uv run pytest -m "nfs and not acceptance"`.
      Amend DT-23's Makefile row the same way. M15.2's `make -n test-nfs` expectation stays valid.

37. **Non-blocking. M17.3 (G7), plan :6685-6686.**
    - What: `rg -n 'append_audit|Actor' src/huron/core/lake/reconcile.py` is expected to show `Actor` only in
      `ReconciliationFindings.page`. The module must also import `Actor`, and the import line matches.
    - Why: no correct implementation produces the expected output, so a literal verifier fails the task.
    - Correction: "…shows `Actor` only on its import line and in `ReconciliationFindings.page`'s signature,
      and no `append_audit`".

38. **Blocking. M17.5 and M19.4, and the Definition of done (G7), plan :6799 (M17.5), :7192 (M19.4), :7346
    (Definition of done).**
    - What: both verifications require `rg -n -- '--repair'` over `docs` to print nothing. M0.3 (:450-454)
      creates `docs/adr/0007-raw-reconciler.md` with DT-25's ADR text verbatim, and that text says "the
      spec's `huron check --repair` is dropped (OQ-16.2 (a))" (design:15491-15492).
    - Why: both commands print the ADR line on every correct tree, so neither verification can pass as
      written.
    - Correction: M17.5 :6799: `rg -n -- '--repair' docs design/layer-raw.html --glob '!docs/adr/**'` prints
      nothing. M19.4 :7192: `rg -n -- '--repair' src docs --glob '!docs/adr/**'`. Definition of done :7346:
      "no `--repair` in `src` or `docs` outside the ADR that records its removal".

39. **Blocking. M19.2, T-docs-Z overview pages, re-run in M19.3 and M19.4 (G7), plan :7058-7072 (Modify)
    against :7089-7090 (closing check) and :7149-7150.**
    - What: the check
      `rg -n -i 'raw revision|…|ingest session|…' design --glob '!*-uml.*'` must print only lines of
      `layer-raw.html` §12. At HEAD it also matches lines that no task rewrites: `design/index.html:276`
      (decision 15, "linked to a raw revision of the same dataset"; DT-26 schedules decisions 2, 3, 6, 7,
      8, 10, 11, 14 and 16, says 17 is unchanged and never mentions 15); `design/index.html:337` (the §4
      document-map card "Raw Layer — NFS Store … ingest sessions, independent revisions, sealing, TTL
      expiration, purge"; M19.2 removes only the `rawstore-uml` card row); `design/core-map.html:217` (§5,
      "creation alone does not produce a Raw revision"; M19.2 adapts only §2, §4, §6, §7, §9 and §10); and
      `design/layer-silver.html:246` ("no ingest session, no manifest … retention clock"; M0.5 changes only
      `:229-233`, `:294` and the `:247` href). The same unscheduled sections carry other stale engine text:
      index §1 ("immutable Raw revisions"), the §4 Authentication card ("session model, CSRF,
      admin-provisioned passwords") and REST API card ("ingest"), and workflows §6 ("per-revision
      materialization state (raw: committed …").
    - Why: M19.2's verification fails as written, and so does the DT-26 closing check that M19.3 and M19.4
      repeat. The implementer must edit sections the task does not list, or stop.
    - Correction: extend M19.2's Modify. `design/index.html`: decision 15 becomes "linked to Raw pins
      (collection id, rel_path, sha256) when its bytes came from the lake, external-provenance otherwise";
      §1's "immutable Raw revisions" becomes collections on the lake; the §4 `layer-raw.html` card becomes
      "Raw Layer: the lake" with a one-line outline of its §1–§12; the Authentication and REST API cards
      name the surviving credentials and the lake routes. `design/core-map.html` §5 drops the "Raw
      revision" sentence. `design/workflows.html` §6: the materialization-state sentence names pins and
      derived snapshots. `design/layer-silver.html:244-248`: the entry-layer sentence is rewritten without
      ingest sessions or the Raw retention clock (here, or in M0.5 beside the `:247` link fix). Cite DT-26
      "interfaces and contracts" (Page contracts) and its closing check as the design basis.

40. **Blocking. M19.2's `core-map.html` rewrite, breaking M19.3's link check (G7), plan :7070-7072
    (core-map Modify) and :7142-7143 (M19.3: `check_design_links.py` exits 0 and prints nothing; the unit
    test "the real repository has no finding").**
    - What: `design/core-map.html` §8 "Identity operations" (`:326-343`) documents
      `PasswordAuthentication.login()`, `OidcAuthentication.begin()/finish()`, `SessionResolver` and
      `terminate_session()`, and links `../src/huron/core/security/sessions.py#L248` (`:339`). M1.6 (D2-4)
      deletes all of these, including `core/security/sessions.py` (plan :1046-1047; design:2087). Neither
      DT-26's core-map row nor M19.2 schedules §8. §1 Orientation (`IngestService`, ingestion) and §3 Class
      relationships (`IngestService`, `RevisionService`, `RevisionStore`, `RevisionReadService`,
      `SessionStore`) are unscheduled too. M19.2 rewrites only the links into `core/{raw,catalog,rawstore}/`.
    - Why: after M19.2, `scripts/check_design_links.py` reports `design/core-map.html:339 ->
      ../src/huron/core/security/sessions.py#L248 (missing file)`. M19.3's verification and its "no
      finding" unit test fail, and `make docs` (with the link check) is red from M19.3 on. The page also
      keeps describing deleted classes after its status line is removed.
    - Correction: add to M19.2's core-map Modify: §1 without the Raw ingestion service; §3's diagram without
      the Ingest, Revision and Session classes and with the lake classes; §8 limited to the surviving
      identity operations (API keys, service accounts, bootstrap) and the broker, without the `sessions.py`
      link. Add the check
      `rg -n 'security/sessions\.py|PasswordAuthentication|OidcAuthentication|SessionResolver|IngestService|Revision(Read)?Service|RevisionStore' design/core-map.html`
      prints nothing.

41. **Non-blocking. M19.4 (G7), plan :7195-7197.**
    - What: "Every closing check … of M0.5, M1.1–M1.7, … M11.14 … re-run unchanged on the final tree"
      includes clauses that later tasks invert on purpose, and the earlier tasks do not mark them as scoped
      to their own commit: M0.5's `rg -c 'describe the engine being replaced' …` must report 1 per page
      (:597), but M19.2 deletes those lines; M1.4's `nightly.yml` jobs must equal `['unit-macos']` (:937),
      but M15.4 adds `nfs-large`; M1.4's "40 legacy operations … 12-tag set" (:935) becomes 38 operations
      and 21 tags; M11.14's `rg -n "rename_collection|place_moved" src` must print nothing (:5031), but
      M16.4 adds `Directories.place_moved`.
    - Why: a strict verifier reading "unchanged" fails M19.4, and the exception mechanism rests on the
      implementer's judgement because nothing in those tasks scopes the clauses.
    - Correction: list the exceptions in M19.4: M0.5's status-line count (superseded by M19.2's own `rg`),
      M1.4's nightly job list and its 40-operation/12-tag clause (superseded by M19.4's 38/21/34 check), and
      the `place_moved` half of M11.14's `rg` (keep `rg -n 'rename_collection' src tests`).

42. **Blocking. M19.5, with the plan-wide Merge rule, Non-goals, Definition of done and Risk 5 (G7; found
    by the G7 and the plan-wide verifiers), plan :7233-7237 (step 3), :92-94 (Non-goals), :313-315 (Merge
    rule), :7332-7336 (Definition of done, "CI receipts"), :7305-7316 (Risk 5); design:14381-14384 (DT-23
    "Gates").**
    - What: the merge needs two green `nightly.yml` runs on `raw-storage`, and step 3 gets them with
      `gh workflow run nightly.yml --ref raw-storage`. GitHub dispatches `workflow_dispatch` only for
      workflows on the default branch, and scheduled runs also use only the default branch. `nightly.yml`
      exists only on `raw-storage` (M1.4 renames `acceptance.yml`) and has only `schedule` and
      `workflow_dispatch` triggers, so it never runs before the merge. Checked: `git ls-tree origin/main
      .github/workflows/` holds only `acceptance.yml` and `ci.yml`, and `gh workflow list --all` lists only
      "Acceptance" (352347222, `acceptance.yml`) and "CI". Dispatching the registered `acceptance.yml` with
      `--ref raw-storage` also fails, because that path no longer exists on `raw-storage` after M1.4. The
      plan's step 3 and Risk 5 already expect the refusal and send it to the owner.
    - Why: the final task, and with it the Definition of done, cannot complete without asking the owner, so
      the whole run ends at a question known in advance. That contradicts the head's rule that nothing waits
      on an owner answer (owner decision 12).
    - Correction: settle the mechanism before execution and write it into DT-23 "CI workflow job outlines"
      and "Gates", M19.5, the Merge rule, the Non-goals bullet, the Definition of done ("CI receipts", "The
      merge") and Risk 5. Two routes:
      (a) keeps DT-23's pre-merge gate and needs no new owner ruling: `nightly.yml` (M15.4, or M1.4 where
      the file is created) also triggers on `pull_request: {types: [labeled]}`, and both jobs carry
      `if: github.event_name != 'pull_request' || github.event.label.name == 'nightly'`, so a pull-request
      event runs the branch's own workflow file. Step 3 becomes `gh pr edit <n> --add-label nightly`, with
      the label removed and re-added for the second run, polled with
      `gh run list --workflow nightly.yml --branch raw-storage --limit 2 --json databaseId,conclusion`.
      M1.4's `list(d['jobs']) == ['unit-macos']` check still holds.
      (b) needs an owner ruling because it changes DT-23 "Gates": the two nightly runs become a post-merge
      condition. After `gh pr merge <n> --merge`, run `gh workflow run nightly.yml --ref main` twice in
      sequence, poll `gh run list --workflow nightly.yml --branch main --limit 2 --json databaseId,conclusion`,
      and record both green runs (`nfs-large` with `reconciler-scale.json`, and `unit-macos`) as the last
      receipts; a red run becomes a fix task on `main`, and the merge needs only the seven pull-request
      checks.
      Keeping the file at `.github/workflows/acceptance.yml` so that it stays dispatchable would also work,
      but it departs from DT-23's file name, needs its own ruling before M1.4 and needs a rename after the
      merge.

### Observations (cycle 1)

These are judgement calls, harmless inconsistencies and receipts. None of them stops execution, and none
needs a plan change before execution starts.

**G1 (M0–M2)**

1. M0.4 :524: the append-only check `git diff HEAD~1 -- RAW_LAKE_SPEC.md | rg '^-[^-]'` misses removed
   blank lines and removed `- ` list lines, which show as `-` and `-- …`. `git diff --numstat HEAD~1 --
   RAW_LAKE_SPEC.md` showing 0 deletions is exact.
2. M0.1 and M0.4 against DT-25's spec amendments (design:15488-15490, handoff :15707): DT-25 wants the
   amendment section in the commit that first tracks the spec, but the plan tracks the spec unamended in
   M0.1 and appends A-1…A-30 in M0.4. Both precede any code, so the split is deliberate and harmless.
3. M0.2 :435: `rg -n 'Until .RAW_LAKE_IMPLEMENTATION_PLAN.md. completes' AGENTS.md` matches only if the
   implementer keeps B-1's line wrap. AGENTS.md wraps near 85 columns, and a rewrap could split "Until" from
   the file name.
4. M1.1 :632-633 cites a DT-3 heading "Whole files (28; R3-2)". The heading is "Whole files (30: R3-2's 28
   and the two /queue files)" (design:2400). :677 speaks of an "eighth" Gate file, but DT-3's Gate lists
   seven. Neither affects execution.
5. M1.1 :691-692: the empty-diff check over "each path of DT-3's Untouched-surface invariant lists" also
   reaches the invariant's "Behaviour-preserving edits only" bullet (`hooks.server.ts`, `AuthShell`,
   `admin/+page.svelte`, `+page.svelte` and three e2e files), and those files do change in M1.1. Limit the
   check to the first three bullets (web login, sessions and accounts; Organizations; non-Raw Polaris).
6. M1.4: `tests/unit/test_api_settings.py` (`:37-50`, `:144-150`: ingest-sweep and completion defaults and
   refusals) is missing from the partial test list, though M1.4 deletes those four fields; DT-2's D2-2 list
   misses it too. The closing `rg` (`ingest_sweep|completion_reserve` over tests) catches it.
7. M1.4 :847: DT-2 says the Raw `include_router` lines are six, but `routes/v1/__init__.py:40-44` has five
   (tus is mounted through `ingest_sessions.transfer`).
8. M1.5 :974-976: the parenthetical importer list names `tests/{catalog_creation_support,repository_fixture}.py`
   and `test_api_app.py`, none of which imports `PosixRawStore` at `fa51f46`, and omits
   `test_catalog_ports.py`. The governing instruction (`rg -l PosixRawStore tests` at the base) is right.
9. M1.5: most surviving `test_rawstore_materialize.py` cases take the `storage` fixture
   (`PosixRawStore(tmp_path, max_concurrent_completions=2)` plus `.staging/session`), so "keep every case
   for a survivor" means rewriting that fixture over a plain directory, not only dropping `:36`.
10. M1.6: `tests/unit/test_repository_rbac.py:540-552` (`MemorySessionStore` passed positionally to the
    credential authenticator) and `tests/unit/test_api_rbac.py:291` (`csrf_token`) are missing from the
    Modify lists. The closing `rg` catches both.
11. M1.7: the tests half of the closing `rg` omits `reconciliation_findings`, `sessions` and
    `local_credentials`. The `reconciliation_findings` case at `tests/contract/test_catalog_store.py:795`
    runs against the `0010_independent_raw` pin and keeps passing, so its required deletion goes
    unverified.
12. M1.6 to M2.2: the `src/huron/applications/api/routes/__init__.py` docstring describes the deleted `auth`
    login package for two commits (M1.7, M2.1) until M2.2 rewrites it.
13. M2.1 :1213-1215 deletes `catalog-search.html:93`'s `core/raw/` link with its clause, while DT-26's
    handoff repoints both code links to `core/hierarchy/`. The plan's choice is better, because `core/raw`
    has no hierarchy counterpart.
14. DT-25's ADR 0002 amendment text, copied verbatim in M0.3, cites "(M0.2–M0.3, DT-2)". Those are the
    superseded RAW_STORAGE plan's milestones, and this plan's own M0.2–M0.3 make the citation ambiguous.
15. The duplication guard: G2 found that a fall in the clone total passes `check_duplication.py`. That is
    true of the total only; `_regressions` still classifies each signature by its file tuple, so a subset
    signature left by a deletion is "new" (defect 9).
16. Coverage both ways holds for DT-1, DT-2, DT-3 and DT-25 apart from the defects above, and for the
    owner-decision-11 rows that name them (B-2, B-5, B-6, B-11 → M9, B-12, B-13, B-15–B-19, B-22, B-24–B-26,
    B-39, B-40). Items that land outside G1: DT-1's strict `If-Match` parser, `entity_tag` and the legacy
    test edits (M9 :3648-3682); DT-1's lake segment and credential invariants (M9 :3668-3669);
    `NamingError` (M6); `PathExists`/`ChangedSinceRead` (M13); the B-9 enforcement sentence (M5 :2017);
    AG-12…AG-14 and B-10/B-11 (M15); the lineage rule's `rg -i revision src/huron/core/lake` (M19 :7190).
17. Ordering in G1 holds: `polaris.html#raw-outside-polaris` (M1.1) precedes its link from layer-raw §11
    (M1.3); ADR 0004 (M0.3) precedes its links; 0014 (M1.7) follows M1.4 and M1.6; the rename (M2.1)
    follows all deletions. `make docs` does not check design links until M19, so the interim dangling
    anchors (`#recovery`, `#layout`, `#commit`) leave the gate green.

**G2 (M3–M5)**

18. Coverage for DT-4, DT-5, DT-6 and DT-22 is otherwise complete, and the items outside G2 are placed:
    Postgres halves, `test_lake_roles.py` and `test_lake_signing_keys.py` (M8); `routes/discovery.py`,
    `/auth/exchange`, the settings diff, `key_source`, `lake_settings()`, the realm swap,
    `dev_signing_key.py`, compose, Makefile, `dev.env`, `check-stack.sh`, the DT-6 closing `rg` and DT-22's
    Seed case (M9); `require_on_catalog` (M7); `catalog_of` and `require_on_collection` (M11); the
    Below-minimum row (M13's 403 replay case and the role-ladder table); `Discovery.parse` against the fake
    (M10); `huron-integration` and its drift clause (M15.5); `OidcNotConfigured`, `self_access` and the
    self-access types (M1.6).
19. Contract 19 is written as two `forbidden` tables, and the plan does not say whether each checks
    indirect imports (DT-1 states direct or indirect for every contract). Both settings pass today, but an
    explicit choice removes a guess.
20. M4.1 renames contract 8. The existing parametrized `metastore → schema` case in
    `tests/unit/test_domain_import_contracts.py` asserts the name M2 set. M4.1's bullet does not say to
    update it, but its own verification forces the edit.
21. Design-signature deviations, each justified in the plan: `HuronKeys(..., *, refresh_interval=REFRESH_INTERVAL)`
    (M3.3); `ScriptedSigningKeyReader` instead of DT-5's `InMemorySigningKeys` for the `HuronKeys` failure
    rows (M3.3); `test_keys` renamed `refreshed_test_keys` (M3.4); `InMemoryLakeStore(*, seed)` without
    `clock` until M7.1 (M4.1); `create_app(clock=...)` (M5.5, from DT-22's shared-clock rule);
    `tests/lake_store_contract.py` replacing the per-port scenario modules (DT-17 layout); `groups_claim`
    kept from M5.5 until M9.1 deletes it (B-14 "keep").
22. M4.2 puts DT-17's halves name-collision assertion in `test_lake_memory_store.py`, while DT-17
    (design:10780-10786) lists it under `test_lake_ddl_sync.py`; M8 may end up with a duplicate.
23. M5.6's closing check `rg -n "transaction\(|audit" src/huron/core/security/broker/exchange.py` also
    matches a docstring that mentions "audit". Keep the word out of the module, or narrow the pattern to
    `audit_|AuditWriter`.
24. M5.5's closing `rg` also matches docstrings (`tests/unit/test_api_app.py:7` names `OidcClient`;
    `tests/unit/test_api_oidc.py:9` names `oidc_verify`). The bullets do not list these rewrites, but the
    check forces them unless M1.6 already rewrote them.
25. Verified at HEAD: `OidcResolver.resolve` is already async and `credential_authentication.py:110` awaits
    it; `security/errors.py` already has the N818 ignore; `DomainError.retry_after` exists and
    `problems.py` emits `Retry-After`; `AuthError.code == 'INVALID_CREDENTIAL'`; `ROLES[...].title` exists;
    `DependencyUnavailable` is imported only by `app.py` and `test_api_errors.py`;
    `scripts/render_uml_atlas.py:110` is the `OidcClient` placeholder; DT-18's ready-to-paste §7 rows for
    `ROTATION_REFUSED` and `SIGNING_KEY_UNAVAILABLE` exist (design:11320-11321); the nine legacy metastore
    modules named for contract 19 are what remains after M1.

**G3 (M6–M7)**

26. M7.1 moves `SystemClock` from `core/metastore/hierarchy.py` into `core/foundation/clock.py` with no
    explicit design basis; it follows from `InMemoryLakeStore(clock: Clock | None = None)` and contract 19.
    `design/core-map.html:167`, `:354` and `design/metastore-uml.md:345-1208` still place it in metastore.
    Under the owner-decision-11 rule, M7.1 could name those lines or defer them explicitly to T-docs-Z.
27. M7.1 puts `IntegrityViolation` in `metastore/lake/memory.py`, which composes the halves that raise it,
    so top-level imports in both directions create a cycle. A function-level import (PLC0415 is not
    selected) or a definition in `_db.py` solves it; moving it also moves the N818 per-file entry pinned to
    `memory.py`.
28. M7.1's shared audit scenarios must read rows back on both adapters before M16.1's `AuditReader` exists,
    and M4.2's `LakeSeed` has only write methods. An adapter-agnostic read helper (for example
    `LakeSeed.audit_rows()`) is implied but not named; M8.5's `PostgresSeed` needs the same.
29. DT-9's `Validation` case "equal compositions across two catalogs share one validator object" (M7.5)
    cannot arise with two real catalogs, because compose step 8 embeds the catalog in `$id`, `title` and
    `x-huron.catalog`. The test can only pass with two `CatalogConfigRecord`s that differ only in
    `catalog_id`.
30. M2.1 :1217 says the `conventions.md` sentence "is DT-8's in M6", but the plan lands it in M7.4 (:2656),
    matching DT-26's "DT-8 task". The replacement line names the `rel_path` rule, which `huron.schema.naming`
    gains only in M13 (DT-26's choice; the plan notes it).
31. M7.6 says `memory.py` gains "the `ldap_groups` table and its gid secondary key", but M4.1 already
    created `LakeTables.ldap_groups`; only the gid key is new.
32. M7.2's `MetadataSchemas.list(actor, after: tuple[str, int] | None, …)` departs from DT-9's
    `after: str | None` to follow DT-18's paging key, which the plan's precedence rule allows.
33. M6.2's check `rg -n "Draft202012Validator" src` (only `_validator.py`) is not repeated in M6.4 or M6.5.
    DT-9's compose step 8 names `Draft202012Validator.check_schema`; M6.5's composer should use
    `HuronValidator.check_schema`, and repeating the check in M6.5 would pin the single-class rule.
34. M7.2's `publish` claims inside its transaction, so DT-9's precondition 2 (replay) is checked after rows
    3–5 rather than in table order. Rows 3–5 are pure, so this is harmless.
35. Coverage both ways otherwise holds for DT-7, DT-8, DT-9 and DT-10, with their later parts in M8, M9,
    M11 and M16. Ordering in M6–M7 holds, and the contract counts are 17 through M7.2 and 18 from M7.3.

**G4 (M8–M9)**

36. M8.6 adds `ApiRuntime.stores` and reads DT-17's "ApiRuntime gains no store member" as "no per-port
    member". DT-18 and DT-17's layout line use `runtime.stores.lake`, so the design is inconsistent and the
    plan's reading is necessary; record it under Execution notes.
37. M9.2 puts `metadata_schemas` and `validation` on `ApiRuntime`, while DT-18's `dependencies.py` builds
    `metadata_schemas` per request. DT-9's process caches and DT-10's composition justify the plan.
38. `design/api.html` §7's `DEPENDENCY_UNAVAILABLE` row: no task adds `group_directory` (raised from M5.6)
    or `dependency: "database"` (raised from M8.3's `_pool.py`, on the wire from M9.3/M9.4), and M9.4 says
    "§7 is unchanged". `test_error_contract.py` does not parse the prose, so it stays green. Under the
    landing rule, M9.4 (or M8.3) should add `database` and M5.6 `group_directory`.
39. M8.3 and DT-18 write `DependencyUnavailable(dependency=…, reason=…)`, and M9.6 writes
    `DependencyUnavailable("database")`. `DomainError.__init__` is `(detail=None, *, context=None)` and
    M5.4 adds no constructor, so the implementer passes `context={"dependency": "database", "reason": …}`.
40. M8.2 lands runbook §1 with the `CREATE EXTENSION ltree` prerequisite at 0015 but defers `schema.sql`'s
    `ltree` and GIN header sentences to 0016 (M11) by the truth rule; inconsistent but harmless.
41. M8.4 does not restate that the Postgres `insert_group` maps a unique violation on `ldap_groups_gid_key`
    to `RoleMappingRefused(gid_taken, held_by)`. DT-10 step 4 (design:6190-6196) states it, and M7.6's
    shared "gid clash naming the holder" scenario runs on Postgres in M8.4, so it is enforced.
42. M8.1's `rg -n "0013_retire_releases" tests/contract/test_catalog_store.py`: if M1.7 deleted the module,
    `rg` exits 2 with an error rather than printing nothing. Say "or the file is absent".
43. M9.4's row 7 (`GET /catalogs/{c}/schema`) 304 branch has no listed unit case. The coverage rule forces
    one, and M10's `test_schema_cache_revalidates_with_if_none_match` exercises it later.
44. `CatalogBody.volume` is omitted until M11.11. That is sequencing of new code, not a compatibility
    provision under owner decision 11.
45. Tag and route counts check out: 16 tags at `fa51f46`, 11 after M1, then 13, 14, 15 and 17 in M9, and 21
    at the end; lake routes are 6, 12 and 18 in M9 and 34 at the end, matching DT-18.
46. Coverage is otherwise complete both ways for DT-17 and DT-18, every M8–M9 symbol exists at HEAD or is
    created earlier, and import-linter stays at 18 contracts through M8 and M9.

**G5 (M11, M13)**

47. Coverage holds both ways for DT-11, DT-12, DT-13 and DT-14, apart from the defects above. Deferred by
    design: Linux cases 1–5 (M15), `rename_collection`/`place_moved` (M16), "two syncs racing two
    publishes" (M16), C13 (M16) and the large-file case (M15).
48. Declared departures, each recorded in the plan: `VolumeRules` injection (contract 9 against DT-11, Risk
    4); `apply_merge_patch` in `huron.schema.metadata` (OQ-20.1 (a)); routes in `endpoints/commits.py`
    (DT-18 layout); `scan_settled` by identifier (D-4); the injected lease clock (DT-17 Time);
    `commits_finished_idx` (D-8); no separate `namespace_id` index (D-3).
49. M11.12 drops DT-11's per-reset `audit_log` entry (`access_reset`/`catalog`), which matches DT-7's "What
    is not audited" (design:4398) and DT-17's seeded vocabulary. DT-11's handoff row to DT-7/DT-10 and its
    `AccessResetWorker` bullet (design:6916-6917, :7111) still say otherwise and should be corrected in the
    design.
50. M13.7 does not build DT-14's "at most 3 tries on 40001/40P01" (step 4, F13). This follows DT-17's
    correctness model (40P01 propagates) and contract 10; Risk 2 names the fallback.
51. The milestone table's M11 intent says "completeness recompute on config and schema publish". DT-9 binds
    only config publish, and M11.7 correctly recomputes on config publish only; drop "and schema" from the
    table.
52. M11.9 and M11.13 move the `label` grammar parsing from `Collections.search` into the route model,
    because the refusal is the transport code `REQUEST_INVALID`; recorded in M11.9.
53. M13.6's settled delete reads `unfinished_commits` "in its pre-check", but `CollectionWriter` is
    transaction-only and DT-12 checks it inside the delete transaction. A pre-check needs its own read
    transaction; harmless but unspecified.
54. The scenario modules named by DT-11, DT-12 and DT-14 are folded into `tests/lake_store_contract.py` and
    `tests/contract/test_lake_store.py`, following DT-17's single-module rule; C17 lives in
    `test_lake_schema.py`.
55. DT-12 hands DT-18 the `metadata.json` contract string `huron:collection-metadata:1` to document beside
    the API. No M11 task names that line; layer-raw §2 (M11.11) is the natural home.
56. `rbac.html` `:144`, `:266` and `:431` are HEAD line numbers. M0 and M1 edit `rbac.html` first, so
    M11.12 and M13.9 should match those lines by text.
57. DT-26 lands layer-raw §5 with "the DT-14 commit-worker task"; the plan lands it in M13.9, when the
    section becomes true. Acceptable.
58. The budget of four duplication-baseline signatures across M11 and M13 is tight for six Postgres and
    in-memory half pairs plus five route modules. It cannot be checked without running the guard.

**G6 (M10, M12, M14, M18)**

59. M10.7 makes DT-20's `Services.prompter` a factory `Callable[[], Prompter]`, because building
    `QuestionaryPrompter(sys.stdin, …)` eagerly would refuse every piped run. The departure is recorded.
60. M18.3 prints `check -o json|yaml` as `{"catalogs": [...], "pending_pushes": [...]}`, resolving DT-20's
    bare array against DT-21's `pending_pushes` "beside" the items; a recorded judgement call.
61. Config keys mix separators: `api-url`, `idp-issuer` and `idp-client-id` keep DT-19's hyphens, while
    `mount_prefix` and `mount_policy` use underscores (plan :3966). It follows the precedence rule, but users
    see both spellings.
62. RL step 1 flips to `done` in M10.4 while the manual Keycloak `login --device` smoke is "not run", and RL
    step 3 flips in M12.3 before the `nfs` receipt exists. Both rely on M19 checking the receipts, so M19's
    list must name both.
63. M18.3's `rg -n "repair" src/huron/applications/cli` also matches design-faithful prose (DT-19 rule 1
    "never silently repaired"; DT-21's `probe_volume` "never creates or repairs anything"). Narrowing it to
    `rg -n -- '--repair' src/huron/applications/cli` keeps the intent.
64. pydoclint (`skip-checking-short-docstrings = false`) requires Args/Raises sections on every Typer
    command function, and Typer shows the whole docstring in `--help`. The API hides those sections with
    `\f` and a D301 per-file ignore, which the clean-sweep rule does not grant the CLI; pass `help=` to each
    `@app.command`.
65. M10.2 and M10.4's fake browser GETs the loopback callback inside `open_browser`, which DT-19 calls
    before `LoopbackReceiver.wait`. Unless the receiver serves from `__enter__` or the fake browser GETs on a
    thread, the test deadlocks; M10.2 should say which.
66. M14.4 puts `test_every_commit_body_validates_against_commit_request_v1` in `test_cli_entry.py`,
    "captured during the push tests". A test cannot observe requests made by another module's tests, so it
    must run its own push scenarios.
67. The CLI harness's `api_url` must be `https://…` (for example `https://huron.test`). TestClient's default
    `http://testserver` fails state rule 6, because `testserver` does not resolve to loopback.
68. M10.5's `rg -n "realpath" src/huron/applications/cli` "prints only state.py" holds only when it runs;
    M14.2's `add` records `os.path.realpath(source)` as DT-20 requires.
69. `writer.py` rewrites `write_all` and `fsync_dir` rather than importing them (DT-21 L-30 (a)), which can
    register clone signatures against `rawstore/anchored.py` that count against G6's budget; only M10.6
    mentions the budget.
70. M10.4 edits `dev.env`, but its verification omits the `docker compose config --quiet` that the
    plan-wide containers rule names for `dev.env` edits.
71. M10.1's `uv add "questionary>=2"` needs network access, because questionary and prompt-toolkit are not
    in `uv.lock` at `fa51f46`.
72. Push polling advances the shared `FakeClock` by 5 s or more per poll, and the API's commit worker reads
    the same clock for leases and `commit_deadline_seconds`. Crash-matrix tests that poll for long should
    allow for it.
73. Coverage holds both ways for DT-19, DT-20 and DT-21; ordering holds; contracts stay at 20 from M10.1;
    no G6 task conflicts with owner decisions 1–12 (M12.1 changes `CurrentCatalog` with no reader of the
    old shape, per B-37).

**G7 (M15–M17, M19)**

74. Coverage is complete both ways for DT-15, DT-16, DT-23 and DT-24 (`rename_collection` is never built
    and its absence is checked), and every creator a G7 task depends on exists in an earlier task.
75. The plan moves `FindingCode`, `Severity`, `Resolution`, `CatalogOutcome` and `CatalogStatus` into
    `lake/types.py` rather than DT-16's `lake/reconcile.py`, because `ports.py` needs them and cannot
    import the operation module. DT-17 names the adapter `findings.py` rather than DT-16's
    `reconciliation.py`.
76. The tier guard's one `nfs` exception names `tests/acceptance/conftest.py`, while DT-23's rule table
    says `test_push_large_file.py`. The plan follows DT-23's own fixture outline, which puts `live_lake` and
    its param marks in `conftest.py`.
77. DT-15 names `tests/unit/lake/test_metadata.py` and `tests/lake_collections_contract.py`; the plan uses
    the repository's flat `tests/unit/test_lake_metadata.py` and DT-17's shared
    `tests/lake_store_contract.py`, consistent with the later-section rule.
78. Owner decision 4 says "a real NFS-server container"; DT-23 builds a loopback kernel nfsd on the runner
    (OQ-11.2 (a), settled by decision 12, with the privileged container rejected). This is not a
    contradiction, but the plan head's restatement of decision 4 quietly drops "container".
79. M15.4 flips RL step 4 to `done` even when `make test-acceptance` is "not run" for lack of 12 GiB on the
    owner's Mac, so the step's real evidence arrives only with M19.5's large-file receipt.
80. M17.4's `test_api_reconcile_main.py` "exit 0 on a clean tree" needs a seam that replaces the asyncpg
    pool with memory stores. None is named; monkeypatching the app's store-composition function is the
    evident route.
81. M19.3's `docs/history.md` entry must avoid `huron-web` and `realms/huron`, because M19.4 re-runs M9.1's
    `rg … docs`, which, unlike DT-26's check, does not exclude `history.md`.
82. layer-raw §8 Audit lands in M16.1 (the collection-log task) rather than with M7's audit writer; DT-26's
    "DT-7 task" admits both.
83. A scratch copy confirmed that `zensical build --strict` accepts pages under `docs/` that are not in the
    nav, so `operations.md` (M8) and `cli.md` (M10) before M19.3's "Raw lake" nav group do not break
    `make docs`.
84. DT-24's closing-check commands already print nothing at HEAD, except the docker one, which was not run;
    `rg -il polaris src/huron` lists only files DT-2 deletes plus `core/foundation/names.py`.
85. M19.5 also depends on the owner's M10.4 `login --device` smoke receipt; that is a designed owner action
    (the RL step 1 gate), not an open question.

**Plan-wide**

86. Structure: 112 tasks (M0.1 … M19.5) with unique ids; each has exactly one `- Status: pending` and one
    `- Dependencies:` line; every dependency exists and comes earlier; the milestone table's "Depends on"
    column agrees with the task-level dependencies.
87. Migrations `0014_retire_legacy_raw` (M1.7), `0015_lake_catalog` (M8.2), `0016_lake_collections` (M11.5),
    `0017_lake_commits` (M13.4) and `0018_lake_reconciler` (M17.1) are each created once, in order; each
    sets the `-- Reflects:` stamp that `scripts/check_schema_map.py` reads; each lands before the first store
    half that uses its tables.
88. Import-linter counts agree throughout: 16 at `fa51f46` (verified), 14 from M1.4, 17 at M4.1, 18 at
    M7.3 and 20 from M10.1 to the Definition of done.
89. Contract 9 against `probe_mount`: injecting `VolumeRules(VolumeMarker.parse, mount_entry)` keeps every
    edge, and M11.2's `rg -n 'ctypes|huron\.schema' src/huron/core/rawstore` proves it. M15.2's
    `tests/nfs_support.py` probe must also pass `rules=`; the text does not say so, but the keyword-only
    signature and mypy force it.
90. No access-reset audit pair, no in-attempt retry on 40001/40P01, the signing-key receipt
    `uuid5(namespace, kid)`, the Ruff N818 per-file ignores (a scratch `ruff check --select N818` flags
    `SchemaInvalid`, `LeaseLost` and `BootstrapRefused`), contract 19 as two tables (20 contracts at the
    end), and the in-plan resolutions (prompter factory, `check` JSON object, `mount_prefix`/`mount_policy`,
    guide §5 "link", a `Mapping` for `Collections.search`) are all acceptable.
91. DT-23 "Gates" confirmed by name is necessary: `gh api repos/karthedew/huron/branches/main/protection`
    answers 403 ("Upgrade to GitHub Pro").
92. Nothing is pushed before M19.5, as the commit rule and Definition of done say. Risk 3 says "the owner
    decides at M15.3 whether the branch may be pushed earlier", but M15.3 has no such step and the head
    says nothing waits on an owner answer; drop the clause or add the step.
93. Sequencing gaps under B-14 and B-38 are acceptable: `design/` links are unchecked until M19.3 adds
    `check_design_links.py`, after M11.11 and M13.9 restore `#layout` and `#commit` (inbound links at HEAD:
    `catalog-search.html:360`, `layer-gold.html:154`, `workflows.html:173`). `make test-acceptance` exits 5
    between M1.4 and M15.4, but it is not part of the plan-wide gate.
94. Partly verified external assumptions: google-re2 1.1.20251105, typer 0.27.3, rich 15.0.0 and questionary
    2.1.1 resolve for Python 3.12 with binary wheels for aarch64-apple-darwin and x86_64-manylinux_2_28;
    questionary, typer and rich ship `py.typed` and re2 does not, so DT-9's single mypy/ty override is
    required; `docker compose config --quiet` exits 0 at HEAD; `make -n docs` and `make -n lint` print the
    plan's commands. Not verified: the web npm gates and svelte-autofixer, an actual `make docs` build, ty's
    behaviour on re2, `loopback_nfs.sh` and the `nfs` and `stack` tiers (not yet created), and every `gh`
    write command.
95. The data volume has 5.8 GiB free, below the 12 GiB threshold, so the plain large-file tier will be
    "not run" locally at M15.4, M19.1 and M19.4, and its only receipt will be the CI large-file job at
    M19.5.
96. `test_catalog_*.py` modules are not renamed (M2.1: DT-1 renames no test module; B-33). Ten exist at
    HEAD, and `test_catalog_ingest.py` leaves in M1.4.
97. Owner decisions 1–12: no compatibility provision in the head, the risk register or the Definition of
    done; a grep for alias, deprecated, compat, re-export, legacy_reset, interim and "both forms" finds only
    prohibitions, renames and `Annotated` dependency aliases.
98. The plan-wide gate inputs exist at HEAD (Makefile `lint` at `:58-70`, `docs`, `test-acceptance`; markers
    `unit`, `contract`, `integration`, `acceptance`; `addopts = "-m unit --strict-markers"`;
    `fail_under = 95.69`; 123 baseline clones; `ci.yml`'s lint, unit, contract and integration jobs;
    `web/package.json`'s check, test, lint, build and test:e2e). The new tiers are created before use
    (`stack`/`nfs` markers and the tier guard in M15.1; `test-nfs`, the CI `nfs` job and `loopback_nfs.sh`
    in M15.2; the large-file job and nightly `nfs-large` in M15.4; `test-stack` in M15.5;
    `check_design_links.py` in M19.3).
99. The integration gate stays non-empty after the Raw deletions (`tests/integration/test_catalog_creation.py`
    and `test_catalog_descriptions.py` survive), and `tests/contract/test_auth_store.py` survives M1.6, so
    M8.1's four `_migrate` modules exist.

### Unread ranges (cycle 1)

Each group verifier read its own milestones' task bodies in full, and the G3, G4, G5 and G6 verifiers
reported no unread range. The ranges below are the ones the other verifiers did not read, as they reported
them.

- G1: `RAW_LAKE_DESIGN.md:15295-15420` and `:15530-15640` (DT-25's glossary, ADR and amendment rows) were
  read with each line cut at 220–300 characters, so long glossary entries and amendment rows A-1…A-30 were
  not read past that column.
- G1: `RAW_LAKE_DESIGN.md:15716-15745`, `:15761-15799`, `:15949-15981`, `:16008-16057` and `:16078-16131`
  (DT-26 sections outside G1's read list) were not read; `:15800-15948` was read with lines cut at 900
  characters.
- G1: the DT-22 and DT-23 bodies apart from the grepped launcher, nightly and deletion lines
  (`RAW_LAKE_DESIGN.md:13562-13613`, `:14002-14004`, `:14455-14485`, `:14610-14625`). The G2 verifier
  covered DT-22 and the G7 verifier covered DT-23.
- G2: `RAW_LAKE_DESIGN.md:1653-1821` (DT-1's interfaces and contracts beyond the broker actor and the
  routers header).
- G2: `RAW_LAKE_DESIGN.md:10111-10505` (DT-17's revision list and DDL) and `:10711-10743` (DT-17's
  `ApiStores` diff, skimmed through the plan's references only). The G4 verifier covered DT-17.
- G7: `RAW_LAKE_DESIGN.md:16199-16346` (the open-questions register entries for the G7 open questions;
  only OQ-11.2's DT-11 text at `:7069-7078` and the OQ sections of DT-15, DT-16, DT-23, DT-24 and DT-26 were
  read).
- G7: the design's Current State section "Conventions the design must follow" (not located or read).
- G7: `RAW_LAKE_DESIGN.md:15025-15716` (DT-25; only `:15089-15120`, `:15205-15230`, `:15480-15496`,
  `:15534` and `:15566-15710` were read).
- G7: `RAW_LAKE_DESIGN.md:10050-10916` (DT-17; only the 0018 DDL at `:10458-10506` and grep hits) and
  `:10916-11542` (DT-18; only grep hits for rows 10 and 34–37 and the `reconcile_*` settings). The G4
  verifier covered both.
- Plan-wide: the plan-wide verifier read these plan ranges only through grep hits and short excerpts:
  `RAW_LAKE_IMPLEMENTATION_PLAN.md:362-771`, `:946-1159`, `:1200-2546`, `:2601-2787`, `:2846-2904`,
  `:2941-3004`, `:3017-4088`, `:4157-4419`, `:4476-4792`, `:4849-4912`, `:4956-5499`, `:5536-5905` and
  `:6041-7211`. The group verifiers read each of them in full. It read the design only by grep outside
  `RAW_LAKE_DESIGN.md:608-1365` and the sections it lists as checked, and that includes the
  open-questions register (`:16199-16346`).

## Verification (cycle 2)

Verdict: DEFECTS. 19 defects: 5 blocking and 14 non-blocking. Seven scoped verifiers (G1 to G7) and one
plan-wide verifier checked the corrected plan against the design, the spec's owner decisions 1–12 and the
repository at `fa51f46`. Defects that more than one verifier reported appear once: the M19.4 exception list
(G1, G7, plan-wide) is defect 17, the `catalog-search.html:423` link (G4, G7) is defect 8, and the M8.5 catalog
method names (G4, plan-wide) are defect 9. Each blocking claim was re-checked against the plan, the design or
the repository before it was kept. Cycle-1 defect 38 is still not effective (defect 16) and cycle-1 defect 41
is only partly corrected (defect 17); every other cycle-1 defect is corrected. Defects are numbered in plan
order within each milestone group (G1 M0–M2, G2 M3–M5, G3 M6–M7, G4 M8–M9, G5 M11 and M13, G6 M10, M12, M14
and M18, G7 M15–M17 and M19, then cross-plan). "plan :N" is a line of this file, which this section follows and
so does not shift; `design:N` is a line of `RAW_LAKE_DESIGN.md`.

### Defects (cycle 2)

1. **Non-blocking. M1.2 (G1), plan :776-780.**
   - What: M1.2 adds one assertion to `web/src/lib/server/polaris-browse.test.ts`: a browse URL with
     `format=raw` answers 400. The same task's closing check, run from `web/`,
     `rg -n "…|format=raw|format === 'raw'" src e2e`, must print nothing. At `fa51f46` the file writes every
     browse URL as a string literal (`'http://localhost/browse?…&format=raw'` at `:96`, `:130` and `:150`), so an
     assertion written in the file's own style matches the check.
   - Why: the natural implementation fails the task's own closing check. Passing it needs a URL form the plan
     does not mention.
   - Correction: at :778-780 add "the assertion builds its URL with `url.searchParams.set('format', 'raw')`, so
     no literal `format=raw` remains under `src`".

2. **Blocking. M1.3 (G1), plan :825 against :855-858; re-run by M19.4 (:7601).**
   - What: M1.3 names a new router test `test_the_raw_web_prefix_has_no_route`. Its closing check
     `rg -n "raw_web|RawWeb|raw_delegation|raw_bridge|ExternalDataset|RawPublication" src tests scripts` may
     print only the three `0012_raw_web_catalogs` lines of `tests/contract/test_catalog_store.py`. The new
     test's `def` line in `tests/unit/test_api_router_composition.py` contains `raw_web`, so the check prints it
     too. The test survives to the final tree, where M19.4 re-runs the check unchanged after M1.7 has deleted
     the three exempted lines and expects nothing.
   - Why: two explicit instructions in one task contradict each other. The name the plan dictates fails the
     closing check in M1.3 and again in M19.4. Passing either check means departing from the dictated name.
   - Correction: at :825 rename the test `test_the_retired_bridge_prefix_has_no_route`, or any name without
     `raw_web` or `RawWeb`. Its body stays (`GET /api/raw-web/…` answers 404); the hyphenated path does not match
     the pattern.

3. **Non-blocking. M1.4, M1.5, M1.6, M2.1 and M5.5 (G1), `design/roadmap.html`. No task edits these lines:
   M2.2 edits only `:198`, and M19.2 (:7473-7475) edits only P0's D-1 clauses, P4, P5, Milestone 23, the
   sketch, §4 and RL.**
   - What: after M1.4, M1.5 and M2.1, the roadmap's §1 source tree still lists `core/catalog/` (`:112`),
     `core/raw/` (`:113`) and `core/rawstore/ POSIX staging, checksums, atomic publication and sealing`
     (`:114`). The P0 and P1 rows (`:170`, `:175`), integration milestone 10 (`:634`) and §5 (`:851`) still name
     `core/catalog/…`, `core/raw/paths.py` and `core/raw/manifest.py`. After M1.6, integration milestone 2
     (`:509-520`) still lists as built the `/auth` login, logout, OIDC start/callback, `GET /auth/session`,
     providers, the session cookie and the CSRF echo. Milestone 12 (`:664-668`) still lists "admin-provisioned
     users" (M1.6 deletes `create_user`) and "OIDC upsert-on-login" (M5.5 deletes `upsert_oidc_user`). DT-26's
     roadmap table omits these rows.
   - Why: the plan-wide "No backwards compatibility" rule (:300-305) requires a task that removes or renames a
     name or route to rewrite every document line naming it in the same task. These lines describe deleted or
     renamed code until the end state, and no check catches them.
   - Correction: M1.4 Modify: roadmap `:113` (the `core/raw/` tree line) goes, and so do `:851`'s
     `core/raw/paths.py` and `core/raw/manifest.py`. M1.5 Modify: `:114` describes the generation store
     (`core/rawstore/  generation files and the anchored POSIX primitives`). M1.6 Modify: milestone 2
     (`:509-520`) becomes `retired`, with one paragraph saying that the Python login, sessions and CSRF were
     deleted on 2026-10-23 and that the web keeps its own sessions; milestone 12 loses "admin-provisioned users".
     M5.5 Modify: milestone 12 loses "OIDC upsert-on-login". M2.1 Modify: `core/catalog/` becomes
     `core/hierarchy/` at `:112`, `:170`, `:175`, `:634` and `:851`. Extend M2.1's `rg` (:1358) to
     `design/roadmap.html`, and add `rg -n '/auth/(login|logout|oidc|session|providers)' design/roadmap.html`
     printing nothing to M1.6's Verification.

4. **Non-blocking. M1.7 (G1), plan :1261-1262 against :1281.**
   - What: M1.7 says the module's `_migrate` to `head` "goes if nothing else calls it", and its closing check
     `rg -n '"head"' tests/contract/test_catalog_store.py` must print nothing. At `fa51f46`, `_migrate`
     (`tests/contract/test_catalog_store.py:43-45`) is called by `test_postgres_catalog_constraints_at_head`
     (`:1807-1811`), which survives once the dropped tables' helpers leave `_assert_against`. So `_migrate`
     stays, and its `"head"` literal makes the check print.
   - Why: the two clauses conflict for this file. The implementer has to guess whether to delete the at-head
     test (and lose its constraint coverage) or re-pin the helper.
   - Correction: replace the `_migrate` clause at :1261-1262 with "`_migrate` stays for
     `test_postgres_catalog_constraints_at_head` and pins `"0014_retire_legacy_raw"` instead of `"head"`;
     M8.1 replaces it with `migrated_postgres()`".

5. **Non-blocking. M2.1 (G1), plan :1365.**
   - What: the verification says "Every modified file at 100 % in the unit run". The import rewrite modifies
     the PostgreSQL adapter modules `core/metastore/{hierarchy,queries,rows,security_facts}.py`, whose
     PostgreSQL halves the unit run does not execute. `pyproject.toml` has no coverage omit.
   - Why: read literally, the clause fails, and it contradicts the plan-wide "Coverage" rule (:187-190), which
     measures adapter modules from the "unit or contract" run.
   - Correction: at :1365 write "Every modified file at 100 % (PostgreSQL adapter modules from
     `uv run pytest -m "unit or contract" --cov=src/huron --cov-report=term-missing --cov-fail-under=0`)".

6. **Blocking. M7.2 (G3), plan :2696-2698; conflicts with M6.3 :2385-2387 and :2397-2398; design:5075.**
   - What: M7.2's verification says `rg -n "a-z0-9_-\]\{0,63\}" src` "still prints only
     `src/huron/schema/naming.py`". M6.3 creates `src/huron/schema/documents/catalog-config-v1.json` from DT-8's
     outline "exactly". That outline's `$defs.segment.pattern` is the literal `^[a-z0-9][a-z0-9_-]{0,63}$`
     (design:5075), and M6.3's own `test_document_segment_pattern_is_the_naming_rule` pins it. From M6.3 on,
     the command prints two files. The match was reproduced with ripgrep 15.2.0 on a scratch copy of both lines.
     M6.1's identical check (:2309) is correct only because M6.1 runs before M6.3, and its note says the
     document copy is pinned by a test.
   - Why: on a correct tree the M7.2 check always fails, and the implementer cannot make it pass without
     breaking M6.3's verbatim contract and its pinning test. This is the class of cycle-1 defect 1.
   - Correction: in M7.2's Verification, replace the clause with "`rg -n --type py "a-z0-9_-\]\{0,63\}" src`
     still prints only `src/huron/schema/naming.py` (the one Python copy; `catalog-config-v1.json`'s
     `$defs.segment.pattern` is the packaged contract's copy, pinned by M6.3's
     `test_document_segment_pattern_is_the_naming_rule`)".

7. **Blocking. M7.6 (G3), plan :2903-2904 against :2888-2890; design:6153-6168 (order of checks), :6353 (the
   DT-10 test row), :2896-2900 (DT-4 `Grants.require`).**
   - What: M7.6 binds DT-10's order of checks, in which each step runs only if the previous one passed:
     1 scope, 2 the ceiling on the new role, 3 input (`role_scope`), 4 seed. The task's test list also requires
     "PA mapping `organization_admin` on a catalog → `role_scope`" (422). A Project Admin passes step 1
     (`require_on_catalog(…, PROJECT_ADMIN)`). Step 2 then calls `actor.grants.require(Role.ORGANIZATION_ADMIN,
     ref)`; `role_on(ref)` is PA, below OA, so DT-4's `require` raises `Forbidden` (403) before step 3 can answer
     `role_scope`. The plan copied the inconsistency from DT-10's own test row.
   - Why: two binding statements in one task contradict each other. An implementer who follows the order gets
     403, so the required case in `tests/unit/test_lake_role_mappings.py` fails and the unit gate is red.
     Making the case pass means reordering steps 2 and 3 against the order the task binds.
   - Correction: in M7.6's test list, replace the case with two: "PA mapping `organization_admin` on a catalog
     → 403 (the ceiling, step 2)" and "OA (global) mapping `organization_admin` on a catalog → 422
     `ROLE_MAPPING_INVALID` with `rule = "role_scope"` (steps 1–2 pass through the global grant; step 3
     refuses)". Keep the order of checks as written. Any `role_scope` case M9.5 writes in
     `tests/unit/test_api_lake_admin.py` uses the same OA actor.

8. **Non-blocking. M8.2 (G4), plan :3207-3208; design:15992 (DT-26 "broken links and their fixes", DT-17 row);
   the failure surfaces at M19.3 (:7515-7519, :7546-7547).**
   - What: DT-26 sends `design/catalog-search.html:423`'s `<a href="layer-raw.html#contracts">Raw §3</a>` to
     `layer-raw.html#model`, landing with DT-17's first lake revision. M1.3 removes layer-raw §1–§11 and with them
     the id `contracts` (`design/layer-raw.html:212` at `fa51f46`). M8.2 writes the new §3 "Catalog model
     (`model`)" but repoints no inbound link, and no other task does: the plan never mentions `#contracts` or
     `catalog-search.html:423`. M7.2's §2 registry rewrite (:2676-2678) lists `:123`, `:165-166`, `:180`, `:377`,
     `:444` and `:467`, not `:423`, and M17.5 repoints only `#sweeper` and the §3–§5 lineage examples. At
     `fa51f46` this link is the only inbound reference to the anchor.
   - Why: a DT-26 fix has no task. Unless M7.2's implementer happens to delete the "Mirrored to storage" bullet
     that holds the link, M19.3's new `scripts/check_design_links.py` reports the missing anchor, and M19.3's
     "the real repository has no finding", its `make docs` and its own check fail on an edit M19.3 does not
     list. The finding names the file and DT-26 gives the fix, so the M19.3 implementer can recover.
   - Correction: add to M8.2's Modify, beside the layer-raw §3 line: "`design/catalog-search.html` (`:423` at
     `fa51f46`, the 'Mirrored to storage' bullet, located by text after M7.2): `layer-raw.html#contracts` →
     `layer-raw.html#model` (DT-26 'broken links and their fixes', DT-17 row); nothing to do if M7.2's §2
     registry rewrite removed that sentence". Add "DT-26 broken links and their fixes (`catalog-search.html:423`)"
     to M8.2's Design list, and add `rg -n 'layer-raw\.html#contracts' design docs` printing nothing to M8.2's
     Verification.

9. **Non-blocking. M8.5 (G4), plan :3419-3427 and :3450-3451, against the head resolution :340 and M7.3's port
   :2724-2731.**
   - What: M8.5 still writes the PostgreSQL catalog half with DT-8's names. Its `CatalogWriter` has "`create`
     inserts the catalog and config pair …" and "`publish` is lock-then-check with `AND config_version = $n`",
     and it leaves the listing unnamed ("the keyset listing by `name`"). The head's binding resolution names
     M8.5 and fixes these as `CatalogStore.catalogs`, `CatalogWriter.insert_catalog`, `lock_catalog_config`
     (`FOR UPDATE`, version compared in Python) and `append_config` (`AND config_version = $n`, zero rows →
     `LockContractBroken`), and M7.3 declares exactly those port methods. The race bullet's "A publish without
     the lock" has the same problem.
   - Why: the head says the named tasks carry the detail, but the named task contradicts it. Read literally,
     M8.5's half would not implement M7.3's Protocol: M8.6's runtime conformance check and the shared M7.3
     catalog scenarios that M8.5 runs on PostgreSQL would fail. The implementer has to reconstruct the names
     from M7.3 and the head.
   - Correction: replace M8.5's catalog bullets with: "`CatalogStore`: `get_ref`, `current`, `config` and
     `catalogs(readable, after, limit)` (keyset by `name` `COLLATE "C"`, `ReadableCatalogs` applied in SQL
     before `LIMIT`); `CatalogWriter`: `insert_catalog(record, config)` inserts the catalog and its version-1
     config in one transaction under the deferred `catalogs_current_config` FK and maps `catalogs_name_key` to
     `CatalogExists` inside a savepoint; `lock_catalog_config(catalog_id)` is `SELECT config_version FROM
     lake.catalogs WHERE id = $1 FOR UPDATE` and records the version; `append_config(config)` inserts version
     N+1 and runs `UPDATE lake.catalogs SET config_version = $3 WHERE id = $1 AND config_version = $2` with the
     recorded N, and zero rows (or an unlocked id) raise `LockContractBroken`; `MetadataSchemaStore.schemas` and
     `MetadataSchemaWriter.insert_schema` as M7.2 declares them." In the `test_etag_cas_race` bullet write
     "`append_config` without `lock_catalog_config` raises `LockContractBroken`, and so does an `append_config`
     whose recorded version is stale".

10. **Non-blocking. M11.2 (G5), plan :4731-4732 (contract 9's new form) and :4743-4747 (its verification); M4.1
    :1729-1735; `tests/unit/test_domain_import_contracts.py:98` at `fa51f46`.**
    - What: M11.2 gives contract 9 its DT-1 form: "rawstore uses lake and foundation only", which admits
      `huron.core.lake` and newly forbids `huron.schema` and `huron.core.security`. M11.2 does not list
      `tests/unit/test_domain_import_contracts.py`, and no later task edits its `rawstore` rows (M10.1, :4214,
      runs earlier and adds only `cli` rows). The test's sandbox copies the real `pyproject.toml` (`:14-15`). Two
      of its cases then fail: the allowed-edges case still plants `rawstore → schema` (`"rawstore":
      ("schema",)`, kept through M1, M2 and M4.1), so contract 9 is BROKEN and `returncode == 0` fails; and
      M4.1's forbidden case `rawstore → lake` expects "rawstore uses schema only" BROKEN, but the edge is now
      allowed, so `returncode != 0` fails.
    - Why: M11.2's unit gate goes red and the fix is in a file the task does not list. M4.1 created a case whose
      expectation expires at M11.2, and nothing schedules its replacement. The failing assertions point at the
      fix, so the implementer can recover.
    - Correction: add to M11.2's Modify: "`tests/unit/test_domain_import_contracts.py`: in the allowed-edges
      table `"rawstore": ("schema",)` becomes `("core.lake", "core.foundation")`; M4.1's forbidden case
      `rawstore → lake` is replaced by `rawstore → schema` and `rawstore → security`, each expecting "rawstore
      uses lake and foundation only" BROKEN." Add `uv run pytest tests/unit/test_domain_import_contracts.py` to
      M11.2's Verification, and a note to M4.1's bullet that M11.2 replaces the `rawstore → lake` case.

11. **Non-blocking. M11.8 (G5), plan :5009-5015, from the head's rename resolution :336; M8.3 :3283-3284, M8.6
    :3492-3493.**
    - What: the resolution keeps `AccessResetQueue`'s `claim`, `extend` and `complete` because it checks only the
      `LakeStore` root. M11.8 creates one `PostgresAccessResets` and one `InMemoryAccessResets` half that carries
      `claim`, `extend`, `complete` and also the transaction's `request_access_reset`, and then says "compose the
      halves". A half that serves the transaction must be composed into `PostgresLakeTransaction` and
      `InMemoryLakeTransaction`, which already carry `RetryTransaction.claim(claim: IdempotencyClaim) -> Replay |
      None` from the claims halves (M7.1, M8.3). The queue's `claim(owner, lease) -> AccessResetClaim | None`
      would then meet it there.
    - Why: composed as written, mypy and ty reject the transaction classes for incompatible base definitions of
      `claim`, M8.6's "no two halves define the same public name" test fails, and whichever `claim` the MRO picks
      breaks either idempotent creates or the reset queue. The existing pattern (separate root and transaction
      halves, as in `idempotency.py`) shows the way out, so the implementer can recover.
    - Correction: in M11.8, give each adapter two classes in `access_resets.py`: the queue half (`claim`,
      `extend`, `complete`), composed into the root only, and a writer half (`PostgresAccessResetWriter`,
      `InMemoryAccessResetWriter`: `request_access_reset`), composed into the transaction only. Change :336's
      clause to "`AccessResetQueue` keeps `claim`, `extend`, `complete` on the root only; the transaction
      composes only the `AccessResetWriter` half, because `RetryTransaction.claim` is on it (M11.1, M11.8,
      M11.12)".

12. **Non-blocking. M13.6 (G5), plan :5794-5798 against the head's "Plan-time resolutions" :331-350; M13.9
    :5903.**
    - What: M13.6 says `Commits.submit` returning `Submission(view, replayed)` instead of DT-14's `CommitView` is
      "a design override the head records against DT-14's `Commits` block". The head's list has no such entry,
      and the design file is never edited for plan overrides, so neither document records it. M13.9's
      `wake()`-only-on-a-fresh-accept rule depends on it.
    - Why: the head says it lists the places where the plan differs from the design. A reader who checks
      M13.6's cross-reference, or a later task that reads DT-14 (where `submit` returns `CommitView`), finds no
      entry. M13.6 itself carries the detail, so its execution is not blocked.
    - Correction: add to the head's "Plan-time resolutions of design text", after the "Commit serialization
      failures" line: "- **`Commits.submit` result (DT-14, DT-18).** `submit` returns `Submission(view:
      CommitView, replayed: bool)` instead of DT-14's bare `CommitView`, so the commit route can tell a fresh 202
      from an `Idempotency-Key` replay and calls `CommitWorker.wake()` only when `replayed` is false (M13.6,
      M13.9)."

13. **Non-blocking. M12.1 (G6), plan :5384-5387; root in M10.1 :4159-4161; design:11824, :11857, :12344,
    :13153.**
    - What: DT-19 defines `Config.local_prefix()` as `realpath(mount_prefix or catalog.volume.prefix)`, computed
      once. M10.1 cannot build the fallback, because `CurrentCatalog` has no volume until M12.1. M12.1 adds
      `VolumeCoordinates` and `CurrentCatalog.volume` but never extends `local_prefix` to fall back on
      `catalog.volume.prefix`, and no other task does (`local_prefix` appears in the plan only at :4160).
    - Why: a design interface clause has no task. On a designated machine that mounts the volume at the server's
      prefix and leaves `mount_prefix` unset, `local_prefix()` returns None, so `huron push` S4 calls
      `probe_volume(None, …)` and `resolve_identifier` loses the mount-path form. Every planned test sets
      `mount_prefix` (M10.5, M14.4), so nothing catches the gap.
    - Correction: add to M12.1's `state.py` bullet: "`Config.local_prefix()` returns
      `os.path.realpath(mount_prefix or catalog.volume.prefix)` (DT-19 `state.py`), and None only when neither is
      set"; to its tests: "`tests/unit/cli/test_cli_state.py`: `local_prefix` falls back to the stored
      `catalog.volume.prefix`, and `mount_prefix` wins when both are set"; and "DT-19 interfaces and contracts →
      `state.py` (`local_prefix`)" to its Design line.

14. **Non-blocking. M15.2 (G7), plan :6331-6335 (Create `scripts/loopback_nfs.sh`), :6358-6359 (CI `nfs` job),
    :6371-6372 (the non-Linux check).**
    - What: the task never says the new script must be executable. Every caller invokes it as
      `./scripts/loopback_nfs.sh`: the non-Linux check, the Makefile recipe, the CI steps and
      `tests/linux/conftest.py`'s `remount`. Every `scripts/*.sh` at `fa51f46` is mode 100755, and a file created
      with the Write tool is 0644.
    - Why: `./scripts/loopback_nfs.sh up; test $? -eq 2` then sees exit 126 instead of 2, and the CI `nfs` job
      fails before `up` runs. The error is plain, so the implementer can recover.
    - Correction: add to the Create bullet "mode 0755, committed as 100755 (`chmod +x`; checked with
      `git ls-files -s scripts/loopback_nfs.sh`)", and add `test -x scripts/loopback_nfs.sh` to the Verification.

15. **Non-blocking. M15.3 (G7), plan :6418.**
    - What: `rg -n 'skip|importorskip' tests/linux` must print nothing, but `skip` matches any substring. M15.2's
      `tests/linux/test_nfs_volume.py` implements DT-11 case 4 (a `.snapshot` entry "is skipped by `walk`",
      :6346), and DT-16's Linux cases describe skipped entries too. A natural test name or docstring such as
      `test_walk_skips_snapshot` matches although no skip call exists.
    - Why: a correct tree can fail the check, and the fix would rename a test in a file M15.3 does not modify
      ("Modify: none"). The AST tier guard already enforces the real rule.
    - Correction: replace the clause with `rg -n 'pytest\.skip|importorskip|skipif' tests/linux` printing
      nothing, or drop it and rely on `uv run pytest tests/unit/test_test_tiers.py -q`.

16. **Blocking. M17.5 and M19.4 (G7), plan :7164 (M17.5) and :7596 (M19.4). Cycle-1 defect 38 is not
    effectively corrected.**
    - What: the corrected checks put `--` before `--glob`: `rg -n -- '--repair' docs design/layer-raw.html
      --glob '!docs/adr/**'` and `rg -n -- '--repair' src docs --glob '!docs/adr/**'`. After `--`, ripgrep reads
      every later argument as a path, so `--glob` and `!docs/adr/**` become missing paths and the ADR is still
      searched. Run with ripgrep 15.2.0 on a scratch tree shaped like `docs/adr/0007-…`, the M19.4 form printed
      `rg: --glob: No such file or directory`, `rg: !docs/adr/**: No such file or directory` and the ADR line,
      and exited 2. With the glob before the pattern (`rg -n --glob '!docs/adr/**' -e '--repair' src docs`) it
      exited 1 and printed nothing.
    - Why: ADR 0007 (M0.3) records the dropped flag, so both checks print the ADR line and exit 2 on every
      correct tree. Neither M17.5 nor M19.4 can pass as written, and M19.5 depends on M19.4.
    - Correction: M17.5 :7164: `rg -n --glob '!docs/adr/**' -e '--repair' docs design/layer-raw.html` prints
      nothing. M19.4 :7596: `rg -n --glob '!docs/adr/**' -e '--repair' src docs` prints nothing. The glob goes
      before the pattern, and `-e` carries the pattern in place of `--`.

17. **Blocking. M19.4 (G7), plan :7599-7613 (the re-run clause and its exceptions) against M1.5 :1078 and
    :1082-1085, M1.6 :1189-1197 and :1199-1201, and M1.7 :1285. Cycle-1 defect 41 is only partly corrected.**
    - What: M19.4 re-runs every closing check of M1.1–M1.7 "unchanged on the final tree", apart from clauses a
      task scopes to its own commit and the five listed exceptions. These further clauses are inverted on
      purpose by later tasks, are not scoped and are not listed:
      - M1.5's DT-2 check `rg -n "PosixRawStore|…|\.staging" src tests` (:1078): M14.1 creates
        `src/huron/applications/cli/staging.py` (:5969), and every `huron.applications.cli.staging` import in
        `src` and in `tests/unit/cli/test_cli_staging.py` matches `\.staging`.
      - M1.5's surviving-primitives clause (:1082-1085): its pytest run names `tests/unit/test_rawstore_materialize.py`
        and `tests/unit/test_rawstore_completion_admission.py`, which M11.2 renames and deletes (:4706-4709), and
        expects `materialize.py` and `completion.py` at 100 %; its importer `rg` expects only `app.py`, which by
        its own words holds only before M11.
      - M1.6's `password` alternative over `src tests` (:1189) and its `scripts` half (:1190-1197): M15.5's
        `tests/stack/conftest.py` makes a password grant on `huron-integration` (:6511); M5.2's
        `scripts/keycloak/company-realm.json` carries the users' `<username>-dev-password` credentials (:1955)
        and replaces the `huron-realm.json` the exception list names; M15.2's `scripts/loopback_nfs.sh` names
        passwordless `sudo -n` (:6332).
      - M1.6's `test ! -e src/huron/applications/api/routes/auth -a ! -e …/_impl/self_access.py` (:1201) and the
        composition clause "no `/auth` path" (:1200): M9.3 re-creates `routes/auth` with `POST /auth/exchange`
        (:3798-3811). The listed exception covers only M1.6's operation and tag counts.
      - M1.7's `rg -n "\b(local_credentials|reconciliation_findings|audit_events|outbox_events|raw_revision)\b"
        migrations/schema.sql` (:1285): M17.1 adds `lake.reconciliation_findings` to the map's `lake` section
        (:6918), which `\breconciliation_findings\b` matches.
    - Why: on a correct final tree each clause prints lines or names missing files, so a verifier who reads
      M19.4 literally fails the last verification task, and the merge (M19.5) depends on it. The Definition of
      done's "Closing checks" (:7787-7792) defers to M19.4's re-run.
    - Correction: append to M19.4's list of clauses "which later tasks invert and which are not re-run", each
      listed again under "Execution notes" with the clause that replaces it:
      - the `\.staging` alternative of M1.5's DT-2 check (M14.1 adds `applications/cli/staging.py`); the rest of
        that `rg` is re-run unchanged;
      - M1.5's surviving-primitives clause and its importer `rg` (M11.2 renamed and deleted its files), replaced
        by M11.2's `uv run pytest tests/unit/test_rawstore_anchored.py tests/unit/test_rawstore_mount.py
        tests/unit/test_rawstore_generation.py` with `anchored.py` and `mount.py` at 100 % (:4745-4746);
      - the `password` alternative of M1.6's DT-2 check and its `scripts` half (M5.2's realm credentials, M15.2's
        passwordless `sudo`, M15.5's password grant); the pattern without `password` is re-run over `src tests`
        and prints nothing, and `rg -n 'auth/oidc/callback' scripts` is re-run unchanged;
      - M1.6's `test ! -e …/routes/auth` and "no `/auth` path" (M9.3), replaced by
        `test -e src/huron/applications/api/routes/auth/endpoints/exchange.py && test ! -e
        src/huron/core/security/_impl/self_access.py` and the composition test's "the `/auth` family is exactly
        `POST /auth/exchange`";
      - the `reconciliation_findings` alternative of M1.7's schema-map check (M17.1 adds
        `lake.reconciliation_findings`), replaced by the pattern without it and
        `rg -n '^CREATE TABLE reconciliation_findings ' migrations/schema.sql` printing nothing (no `public`
        table remains).

18. **Non-blocking. M19.4 (G7), plan :7590-7591; M3.1 :1442-1443.**
    - What: `rg -il polaris src/huron` is expected to list only `core/foundation/names.py` and "lake modules whose
      comments cite DT-5's principal-role name rule". M3.1 puts that rule in
      `src/huron/core/security/broker/ladder.py`: `ClaimedRole.parse` raises a `ValueError` "naming the broken
      rule, including the Polaris principal-role rule". That file is a broker module, not a `huron.core.lake`
      module, and the mention is a message, not a comment.
    - Why: a literal verifier sees `core/security/broker/ladder.py` in the listing and fails M19.4 on a correct
      tree.
    - Correction: change the expected listing to "lists only `core/foundation/names.py`,
      `core/security/broker/ladder.py` (the claim grammar's Polaris principal-role rule) and any lake module
      whose comments cite that rule".

19. **Non-blocking. M19.5 and the Definition of done (cross), plan :7683-7687 (M19.5 post-merge
    verification), :7764-7768 (Definition of done, "Every task done"), :315-319 ("Commits").**
    - What: three timing rules conflict. M19.5's verification includes post-merge checks: the merge-base, the
      two-parent merge and the CI run of the push to `main`, "recorded as the last receipt". The orchestrator
      commits a task only after its verification passes, and "Commits" allows no push outside the merge task.
      So M19.5's "Status: done" and its last receipt can land only in a local commit after the merge, which never
      reaches `main`. The Definition of done requires every task, M19.5 included, to read done "on `raw-storage`
      and then on `main`".
    - Why: the Definition of done cannot hold as written, and the last receipt has no committed home.
    - Correction: either (a) add an M19.5 step 5: after the post-merge checks, the orchestrator commits M19.5's
      "Status: done" and the post-merge receipts on `main` as one commit and pushes it, the merge task's last
      push, and the CI run of that push is reported in the final session report, not in this file; or (b)
      narrow the Definition of done so that "Every task done" holds on `main` for M0.1–M19.4, and M19.5's status
      and post-merge receipts are reported by the orchestrator.

### Observations (cycle 2)

Judgment calls and confirmations. None of these blocks execution, and none is a defect above.

G1 (M0–M2):

1. Cycle-1 G1 defects confirmed corrected: 1 (:502, `--files-without-match`), 2 (:567-568), 3 (:691-694), 4
   (:698-701; exceptions :764-767), 5 (:812), 6 (:975-977), 7 (:911-918; checks :1007-1008, :1017-1018; M8.2
   :3203-3206), 8 (:971-972, :1153-1166; check :1206-1208), 9 (rule :126-136; baseline steps :981-994,
   :1086-1089, :1170-1177, :1339-1343), 10 (:1126-1129; exceptions :1192-1196), 11 (:1325-1328; head :220,
   :338), 15 (:919-925; M7.4 :2811-2813), 17 (:1246-1249; M8.1 :3106-3109), 40 (:7457-7466; check :7487) and 42
   (M1.4 :948-958, :1016-1020, :1026; Merge rule :319-329; M19.5 :7651-7672). Defect 38 is not effective
   (defect 16) and defect 41 is partly corrected (defect 17).
2. Import-linter counts hold: `uv run lint-imports` at HEAD reports 16 kept; 16 through M1.3, 14 from M1.4
   through M2.2, 17 at M4.1, 18 at M7.3, 20 from M10.1. M2.1's contract 11 holds: no direct
   `httpx|jwt|cryptography` import exists in foundation, catalog, metastore or rawstore at HEAD.
3. Cycle-1 observations still true: M1.4 omits `tests/unit/test_api_settings.py` (`:37-51`, `:144-150`) and
   `src/huron/applications/api/authorization/__init__.py`'s re-exports of the ten Raw guards (`:28-40`,
   `:49-68`); M1.6 omits `tests/unit/test_repository_rbac.py:540-552`. The gate and the closing `rg` surface
   all three.
4. M0.5 :613-617 says the first closing line still matches through its `25 GiB` alternative, but the printed
   command omits `25 GiB` (DT-25's original at design:15602 includes it). The command prints nothing, so the
   exception clause is moot.
5. The head's "Plan-time resolutions" (:331) omit several deliberate G1 departures: the offline render range
   `0013_retire_releases:0014_retire_legacy_raw --sql` where B-18 and DT-2 say `0013_retire_releases:head`;
   M0.1 committing the spec before M0.4 appends the amendments (DT-25 handoff design:15709 lands them
   together); the D2-2→D2-3 moves of `capabilities.Storage` and `schema/storage.py`, recorded only in M1's
   intro (:653-659).
6. Interim documentation lag that DT-26 itself schedules: `design/auth.html` §5 (`:250-276`, `:304`) and
   `docs/getting-started/local-development.md:71`, `:91-95` describe the deleted `/auth` login, code flow and
   session routes from M1.6 until M9. From M1.3, inbound links into removed `layer-raw.html` ids
   (`workflows.html:151-153`, `:162`; `rbac.html:266`; `catalog-search.html:347`, `:423`, `:512`;
   `api.html:334`) dangle until the DT-11/14/16/17 tasks and T-docs-Z. This contradicts DT-26's "Ids are an
   interface" (design:16034-16036), but no gate checks links before M19.3.
7. Between M1.4 and M15, `tests/acceptance_support.py` (`require_upload_capacity`, 25 GiB) and
   `tests/unit/test_acceptance_capacity.py` survive with no acceptance caller, and `make test-acceptance` selects
   no test. DT-23 (design:14613) schedules the replacement for M15.
8. Coverage both ways for DT-1, DT-2, DT-3 and DT-25 holds apart from defects 1–5; ordering in G1 holds (ADR
   0004 before its links, `polaris.html#raw-outside-polaris` before layer-raw §11, Playwright's
   `tests.raw_web_support` server removed in M1.1 before M1.3 deletes the module, 0014 after M1.4 and M1.6, the
   rename after every deletion).

G2 (M3–M5):

9. Cycle-1 defects 12 (M4 intent :1661; M4.1 :1713-1714, :1733), 13 (M5.3 :2004-2006, :2019-2023) and 16 (M4.2
   :1792-1796, M4.3 :1831-1832, M5.6 :2210-2211, M7.6 :2936-2944, M8.4 :3364-3370) are corrected. The fix
   edits introduce no new defect inside M3–M5, and coverage both ways holds for DT-4, DT-5, DT-6 and DT-22.
10. M5.5 (:2112-2117, :2139-2154) makes `OidcResolver`'s `subject_claim` a required keyword, but the existing
    constructions at `tests/unit/test_auth_oidc.py:126`, `:135`, `tests/unit/test_authorization_credentials.py:226`
    and `tests/unit/test_security_authentication.py:230` omit it; the bullets say only that the stubs become
    `async def`. The task's pytest command fails with a `TypeError` until each passes `subject_claim="sub"`.
11. Cycle-1 observations 20 (M4.1 renames contract 8 without updating the `metastore → schema` case's expected
    name) and 38 (no task rewords `design/api.html` §7's `DEPENDENCY_UNAVAILABLE` row for `group_directory`)
    still stand.
12. M9.1 :3617-3619 says "M5.5 recorded it under 'Execution notes'" (the `create_app(clock=…)` seam), but M5.5
    has no such instruction. M5.2 :1956-1957 says OQ-22.2 "belongs to M9/M15", but only M15.5 adds
    `huron-integration` (:6524).
13. M0.2 :455 and M5.5 :2157 both defer "B-9's last two sentences", which also pulls the rule sentence "`src/`
    never imports `tests`, and no setting names a mock" into M5.5. The two tasks agree.
14. M4.2's role-mapping scenarios do not say to call `LakeSeed.ldap_group` before `role_mapping`. The fake never
    checks that FK, but `PostgresSeed.role_mapping` (M8.4) hits `group_role_map`'s FK to `lake.ldap_groups`
    unless the group row is seeded first. M8.4 edits the scenario module and can add the calls.
15. Duplication: `CompanyTokenVerifier` (M5.4) and `HttpGroupDirectory` (M5.6) both map
    `httpx.TimeoutException`/`TransportError`/non-200 to `DependencyUnavailable`, a likely new clone group
    against G2's cap. M5.5's removal of `upsert_oidc_user` touches baseline clone groups without naming the
    reviewed hand edit, which the plan-wide rule permits.
16. The head line :339 says contract 9 "keeps forbidding `rawstore → huron.schema`"; at HEAD contract 9 ("rawstore
    uses schema only") allows `huron.schema`, and forbids it only from M11.2.
17. `refreshed_test_keys(clock)` (M3.4 :1631-1633) must be `async` because `HuronKeys.refresh()` is; its callers
    in M4.3 and M5.6 await it.
18. M4.1 adds a `core/metastore/lake/` line to `repository-layout.md`, beyond DT-26's row (design:15936), which
    names only top-level packages. The G2 design-signature deviations (`HuronKeys(…, refresh_interval)`,
    `ScriptedSigningKeyReader`, `refreshed_test_keys`, `InMemoryLakeStore` without `clock` until M7.1,
    `create_app(clock=…)`, `groups_claim` kept until M9.1) are justified inline but absent from the head list.

G3 (M6–M7):

19. Cycle-1 defects 7, 14 (M7.2 :2646-2653, :2662-2663, M7.3 :2734-2736; contract 8 has `allow_indirect_imports
    = true`), 15 and 16 are corrected. Renames, N818 entries and import-linter counts (17 through M7.2, 18 from
    M7.3) are consistent in M6–M7, and coverage both ways holds for DT-7, DT-8, DT-9 and DT-10.
20. M7.4's test (:2807-2810) asks for `read_only`, `catalog_mismatch`, `schema_ref` and `identity_field` reported
    together in one `CATALOG_CONFIG_INVALID`. `identity_field` needs the composed schema, which cannot exist when
    `schema_ref` fails, so the case must be split: the first three in one body, `identity_field` against a
    resolvable schema in another.
21. Cycle-1 observations 26–29 and 31 still stand: no explicit design basis or doc-line plan for the
    `SystemClock` move (M7.1); the `memory.py` ↔ halves import cycle for `IntegrityViolation`; no
    adapter-neutral audit read helper for M7.1's shared scenarios; the "share one validator" case needs two
    configs that differ only in `catalog_id`; M7.6's redundant `ldap_groups` wording.
22. M6.2's dependency claims hold at HEAD: `snapshot-provenance-v1.json`'s patterns compile under RE2, the two
    schema tests never assert the `Draft202012Validator` type, `rfc8785`, `pyyaml`, `hypothesis` and
    `jsonschema[format-nongpl]` are declared, and the `asyncpg.*` mypy override exists for `re2` to follow.

G4 (M8–M9):

23. Cycle-1 defects 7 and 16–25 are corrected (M8.1 :3105-3110; M8.2 :3138-3160, :3203-3206; M8.4 :3363-3370;
    M8.5 :3400-3439; M8.6 :3496-3500, :3530-3532; M9.1 :3610-3645, :3688, :3700-3703; M9.4 :3879-3889; M9.5
    :3976-3981; M9.6 :4049-4065). A scratch Makefile under GNU Make 3.81 confirms the M9.1 `make -pn up` check;
    `uv run python -m alembic heads` prints `0013_retire_releases (head)` at HEAD.
24. M9.2 :3788-3789 says "`uv run pytest -m integration` passes with the lake lifespan over PostgreSQL", but the
    surviving integration modules (`test_catalog_creation.py`, `test_catalog_descriptions.py`) never call
    `create_app`, so the qualifier is unverifiable. Reword it, or add one integration case that composes
    `create_app` over `migrated_postgres()` and asserts `/readyz` is ready.
25. M9.1 does not say that `tests/unit/test_api_oidc.py`'s `CLIENT_ID = "huron-web"` (`:64`) goes; its own
    `rg 'realms/huron|huron-web|huron-realm'` check forces it. M8.1's `rg` forces every surviving
    `command.upgrade/downgrade(_config(url), …)` call in `test_catalog_store.py` (`:53`, `:1740-1857`) to become
    `migrate`/`downgrade` and leaves the `_config` helpers unused; the Modify bullet names only
    `migrated_postgres()`.
26. M8.6 :3501-3505 adds `ApiRuntime.stores` against DT-17's "ApiRuntime gains no store member". The reading is
    deliberate (DT-18 spells `runtime.stores.lake`) and recorded under Execution notes, but missing from the
    head's resolutions list.
27. Cycle-1 observation 43 (no unit case for DT-18 row 7's 304 branch) still stands. Repository claims for M8 and
    M9 hold at HEAD, and the test-tag counts (16 at HEAD, 11 after M1, then 13, 14, 15, 17) are right.

G5 (M11, M13):

28. Cycle-1 defects 15, 25 (M11.5 :4875-4880, M13.4 :5695-5697), 26 (M11.1 :4673-4674, M11.7 :4971-4972), 27
    (M11.7 :4961-4969, :4985-4986; M13.4 :5706-5708), 28 and 29 (M13.2 :5612-5614, M13.3 :5645-5652, M13.5
    :5739-5769, M17.1 :6912-6915), 30 in the task text (M13.6, M13.9; the head entry is defect 12), 31 (:5939)
    and the M11.14 half of 41 are corrected. Outside the cycle-1 section, no task text still uses `queue.claim`,
    `queue.release`, `FileStore.page` or a bare `prune`.
29. M11.2 renames `rawstore/materialize.py` to `anchored.py`. If the baseline clone group
    (`rawstore/materialize.py`, `rawstore/store.py`), re-pathed by M1.5, survives, the rename is a re-path the
    plan-wide rule exempts, but M11.2 does not name the reviewed hand edit as M1.4–M1.6 do.
30. M11.10's edits to `tests/contract/test_lake_audit_store.py` (:5130-5133) appear only under Verification, not
    Modify.
31. M13.6 (:5800-5801) has the settled delete read `unfinished_commits` in its pre-check, but DT-12's
    `unfinished_commits` is a `CollectionWriter` (transaction) method checked under the row lock. A short
    transaction for the pre-check, or the in-transaction re-check alone, satisfies DT-12.
32. DT-11 says tests inject the volume and `Directories` through `create_app`'s injection parameters; M11.11 uses
    a `tmp_path` `marker_only`/`recording` volume from the default test settings instead. A test that composes an
    `env="production"` app through the lifespan, if one survives to M11.11, would need DT-11's seam.
33. DT-26's "Lands with" cells name the DT-12 activation, DT-14 commit-worker and DT-11 permissions tasks for
    layer-raw §4, §5, §7 and `rbac.html` §7; the plan lands them with the routes or the worker (M11.14, M13.9,
    M11.12), when the behaviour becomes reachable.
34. `FaultingLakeStore` (M9.6 :4037) "delegates every port method". M13.7's crash matrix injects at methods added
    after M9 (`lock_commit`, `files_by_key`, `apply_plan`, `append_audit`, `finish_commit`); a generic
    `__getattr__` delegation covers them, an explicit per-method wrapper would need an unlisted M13.7 edit of
    `tests/lake_faults.py`.
35. Coverage both ways holds for DT-11, DT-12, DT-13 and DT-14, and ordering holds in M11 and M13; the contract
    count stays 20.

G6 (M10, M12, M14, M18):

36. Cycle-1 defects 15, 32 (M10.1 :4134, :4151-4157, :4181-4184, :4231-4238; M10.4 :4391-4394), 33 (M10.2
    :4272-4291), 34 (M12.2 :5433, M18.2 :7285, M18.3 :7344) and 35 (M10.3 :4338-4339, M14.1 :6005-6012) are
    corrected. The binding renames do not reach G6.
37. M14.4's crash matrix names only the writer's `_link`/`_rename`/`_unlink`/`_fsync` aliases and the TestClient
    hooks; none runs mid-copy, so K2 (`mid_copy`) needs a recipe, for example killing at the partial's `_fsync`
    and truncating the partial to an odd offset before the second push, or a `_write` alias.
38. The head's resolutions omit the `StateDir` sleep/monotonic keywords (M10.1), `HuronClient.page_bodies`
    (M14.1) and the `schemas.py` placement (M10.5). The N818 entry names M10.1, M10.7, M13.3, M14.1 and M14.3,
    but none of those tasks' `pyproject.toml` lists names the per-file ignore; the plan-wide rule covers them.
39. M14.3 :6145-6146 "ENOSPC and EIO … give exit 1 and `VolumeUnavailable("io_error")`" means "respectively":
    ENOSPC is `VolumeRefused` with exit 1, EIO is `VolumeUnavailable` with exit 7 (DT-21 writer errors).
40. M11.11 (:5162-5165) updates every test that builds the API settings or runtime directly; the CLI harness
    (M10.1 conftest, :4186-4188) builds its app through `lake_settings()` and is not named. The gate would flag it.
41. Cycle-1 observations 63, 65, 66 and 67 are still unaddressed in the plan text. Coverage both ways holds for
    DT-19, DT-20 and DT-21 apart from defect 13, and ordering holds; the contract count stays 20 from M10.1.

G7 (M15–M17, M19):

42. Cycle-1 defects 6, 19, 29, 36 (M15.2 :6353-6357), 37 (:7050-7051), 39 (:7432-7489) and 40 are corrected.
    `actions/upload-artifact` v7.0.2 resolves to `cf430e030ddbb5b0abf93d22962f4752f3646cd9`, as M15.5 pins.
43. The head's resolutions and Risk 4 (:7740-7741) claim to list every departure, but omit M15.2's `test-nfs`
    recipe overriding DT-23's Makefile row, the tier guard's `nfs` exception naming
    `tests/acceptance/conftest.py` instead of `test_push_large_file.py`, `FindingCode` living in `lake/types.py`
    rather than `lake/reconcile.py`, and DT-15's `tests/unit/lake/test_metadata.py` and
    `tests/lake_collections_contract.py` folded into `tests/unit/test_lake_metadata.py` and
    `tests/lake_store_contract.py`. Each task records its own departure.
44. M15.1 :6273-6274 and :6295 delete only the second sentence of the AGENTS.md bullet at `:233-235` and put
    AG-14's text in its place; AG-14 (design:15110) replaces the whole bullet and repeats its first sentence, so
    read literally the bullet says it twice.
45. M19.1 :7397-7399: rita's `huron meta update` needs a working copy, so `huron checkout` comes first; the step
    implies it without saying so.
46. Cycle-1 observations 80 (M17.4's "exit 0 on a clean tree" needs a seam over `reconcile.main`'s composition)
    and 81 (M19.3's `docs/history.md` entry must avoid `huron-web` and `realms/huron`, because M19.4 re-runs
    M9.1's `rg … docs`) still stand.
47. The CI `nfs` and `nfs-large` steps `loopback_nfs.sh up | tee -a "$GITHUB_ENV"` follow the design; without
    `pipefail`, a refused `up` surfaces only as the next step's `pytest.fail`, still red.
48. Coverage both ways holds for DT-15, DT-16, DT-23, DT-24 and DT-26 apart from defect 8; every HEAD match of
    DT-26's closing `rg` and every other inbound `layer-raw.html#…` link has a scheduling task, and ordering holds.

Cross-plan:

49. Task structure is sound: 112 task headings (M0.1–M19.5), unique ids, no numbering gaps, exactly one
    "- Status: pending" each, every "- Dependencies:" reference earlier, and no "- Gate:" line.
50. The migration chain is ordered: 0014 (M1.7), 0015 (M8.2), 0016 (M11.5), 0017 (M13.4), 0018 (M17.1), each
    `down_revision` naming the one before and each moving the `-- Reflects:` stamp before its users.
    `tests/unit/test_lake_ddl_sync.py` is created in M8.2. M8.2 (:3154-3155) says M17.1 raises
    `test_upgrade_downgrade_round_trip` to eighteen lake tables, but M17.1 (:6926) does not state the number.
51. The binding renames are consistent; an extraction of every base port of DT-17's `LakeStore` and
    `LakeTransaction` with the renames applied finds no public name defined twice on either composite apart from
    defect 11's transaction-side `claim`.
52. The nightly `pull_request` label trigger is consistent everywhere it appears (M1.4, M15.4, M17.5, M19.5, the
    Merge rule, :350, Non-goals :94, Risk 5, the Definition of done), and the `gh` flags used exist.
    `origin/main` has no commit missing from `raw-storage`.
53. Owner decisions 1–12 are honoured: no alias, shim, re-export or second form survives in task text; dev
    headers stay behind `dev_headers` (owner decision 10); every traced B-row of the design's "Owner decision 11"
    table has a task.
54. OQ-3.1, OQ-3.2 and OQ-6.3 have no "- Decisions:" line and no milestone-table entry; owner decision 11
    resolved them (B-26, B-6, B-28), and M1.2, M1.1 and M5.5/M9.1 implement them.
55. M10 flips RL step 1 to `done` although its design gate (design:15899, the manual `login --device` smoke) is
    collected only at M19.5 step 2; asking the owner at M10.4 would remove a late stop. Risk 3 (:7728-7730) leaves
    an earlier push to the owner at M15.3, which would contradict the Definition of done's "nothing was pushed
    before M19.5"; the default (no early push) is defined.
56. The assembler's unresolved-items list was empty.

### Unread ranges (cycle 2)

Each verifier read its own milestones in full and the design sections they cite. These are the ranges a
verifier did not read line by line; where another verifier covered a range, it says so.

- G1: `RAW_LAKE_DESIGN.md:1585-1644` (DT-1 interfaces `huron.schema.naming`, `security.broker`; headings only),
  `:1720-1821` (DT-1 error codes, preconditions, PostgreSQL placement, CLI package; headings only; G2 read
  `:1583-1821`), `:1841-1925` (DT-1 data flow, rejected alternatives, open questions), `:2270-2330` (DT-2 data flow,
  rejected alternatives, open questions), `:2520-2616` (DT-3 interfaces after the untouched-surface invariant;
  `:2595-2611` read), `:2662-2724` (DT-3 data flow, rejected alternatives, open questions), `:15300-15403` (DT-25
  glossary second half, through an `rg` filter), `:15420-15500` (DT-25 ADR 0003–0007 texts; grepped for OQ
  references and headings), `:15512-15529` (DT-25 spec amendments A-3 to A-19), `:15645-15686` (DT-25 data flow,
  rejected alternatives), `:16167-16198` (Owner decision 11 B-table; only the "Section" and "Now" columns; the
  plan-wide verifier read it in full).
- G2: `RAW_LAKE_DESIGN.md:1365-1542` (DT-1 decisions, target tree, dependency graph), `:10111-10505` (DT-17
  revision list and DDL; G4 read `:10050-10290`), `:10825-10916` (DT-17 data flow, rejected alternatives, open
  questions; handoffs by grep); `RAW_LAKE_SPEC.md` beyond the owner decisions restated in the plan head;
  `RAW_LAKE_IMPLEMENTATION_PLAN.md` outside `:1-396`, `:1407-2252` and `:7818-8885`, read only by grep hits and the
  excerpts it lists (`:938-946`, `:1095-1140`, `:1330-1340`, `:2545-2565`, `:2886-2944`, `:3279-3300`,
  `:3334-3375`, `:3488-3496`, `:3583-3627`, `:4668-4760`, `:5005-5030`, `:5832-5842`).
- G3: `RAW_LAKE_DESIGN.md:4757-4793` (DT-7 data flow, rejected alternatives), `:5060-5100` (DT-8
  `catalog-config-v1.json` outline tail and example YAML; `:5070-5080` re-read for defect 6), `:5265-5306` (DT-8
  data flow, rejected alternatives), `:5307-5345` (DT-8 open questions; recommendations by grep), `:5891-5935`
  (DT-9 data flow, rejected alternatives), `:5936-5962` (DT-9 open questions; by grep), `:6378-6430` (DT-10 data
  flow, rejected alternatives), `:6431-6459` (DT-10 open questions; by grep).
- G4: `RAW_LAKE_DESIGN.md:10291-10505` (DT-17 DDL for 0016, 0017 and 0018; table counts only; G5 and G7 read
  their own revisions), `:10825-10860` (DT-17 data-flow diagram).
- G5: `RAW_LAKE_IMPLEMENTATION_PLAN.md:397-4619` (other groups' milestones; spot reads only), `:5333-5539` (M12;
  G6 read it), `:5946-7817` (M14–M19; spot read `:7594-7618`; G6 and G7 read them), `:7818-8885` (cycle-1
  section; only defects 9, 15, 25-31, 41 and the headings); `RAW_LAKE_DESIGN.md:7044-7054` (DT-11 rejected
  alternatives), `:7464-7495` (DT-12 activation sequence diagram; its failure table read), `:7599-7630` (DT-12
  data flow, rejected alternatives), `:7850-7914` (DT-13 commit-request JSON outline), `:8079-8134` (DT-13
  decision table; rows 23-25 by grep), `:8159-8239` (DT-13 data flow, rejected alternatives, open questions),
  `:8330-8393` (DT-14 state diagram and logical shapes), `:8701-8773` (DT-14 data flow, failure table),
  `:8826-8888` (DT-14 rejected alternatives, open questions, handoffs); `RAW_LAKE_SPEC.md` (owner decisions taken
  from the plan head).
- G6: `RAW_LAKE_IMPLEMENTATION_PLAN.md:397-4104` (M0–M9; spot reads at `:915-925`, `:1096-1200`, `:1890-1970`,
  `:2372-2386`, `:2806-2840`), `:4626-5332` (M11; spot reads `:4718-4724`, `:5160-5206`), `:5540-5945` (M13; grep
  only), `:6245-7175` (M15–M17; grep only), `:7375-7817` (M19, Definition of done, risks; spot reads
  `:7565-7578`, `:7785-7792`), `:7830-8042`, `:8064-8323`, `:8386-8699`, `:8761-8885` (other groups' cycle-1
  items); `RAW_LAKE_DESIGN.md:13404-13453` (DT-21 data flow and rejected alternatives; headings only), and all
  design sections outside DT-19–DT-21 apart from grep-hit lines (handoff rows, the DT-18 route table
  `:11003-11040`, DT-8 `CatalogConfig` `:5005-5030`, the DT-11 probe row `:6614`, DT-26 CLI-guide rows
  `:15957-15966`, Owner decision 11 B-rows).
- G7: `RAW_LAKE_DESIGN.md:14822-14935` (DT-24 target design and interfaces for the later C milestone; reserved,
  not built), `:14944-14978` (DT-24 data flow, rejected alternatives), `:16080-16103` (DT-26 data flow),
  `:16199-16346` (open questions register; only the OQ lines G7 tasks cite, through their Decisions lines).
- Plan-wide: `RAW_LAKE_IMPLEMENTATION_PLAN.md:397-7693` task bodies apart from the excerpts it lists (`:786-800`,
  `:870-962`, `:1018-1032`, `:1038-1095`, `:1186-1200`, `:1278-1292`, `:1320-1366`, `:1478-1515`, `:2540-2552`,
  `:2720-2735`, `:3085-3100`, `:3186-3190`, `:3280-3290`, `:3419-3430`, `:3562-3590`, `:4426-4437`, `:4670-4678`,
  `:4949-4980`, `:5207-5225`, `:5640-5672`, `:5822-5860`, `:6245-6263`, `:6276-6290`, `:6452-6499`,
  `:6895-6935`, `:7375-7388`, `:7568-7693`), checked otherwise by grep (the group verifiers read each in full);
  `:7830-7890`, `:8010-8042`, `:8064-8122`, `:8142-8229`, `:8306-8406` (cycle-1 defects outside the cross-plan
  scope) and `:8516-8874` (cycle-1 observations and unread ranges); `RAW_LAKE_DESIGN.md:1-608` and `:665-1364`
  apart from the "Depends on" lines, `:1365-16166` apart from `:1543-1582`, `:7132-7136`, `:8055-8066`,
  `:9603-9640`, `:10570-10600`, `:15899-15900` and grep hits, and `:16199-16346` (register, grep only);
  `RAW_LAKE_SPEC.md` (owner decisions taken from the plan head's verbatim copy).
- Collation: the collator re-read the plan lines each defect cites (:333-351, :776-782, :818-862, :1072-1092,
  :1180-1212, :1240-1292, :1360-1368, :1422-1446, :1722-1740, :2305-2311, :2380-2400, :2674-2700, :2886-2908,
  :3205-3212, :3276-3306, :3355-3363, :3417-3452, :3486-3506, :3796-3811, :4158-4162, :4212-4222, :4700-4760,
  :5000-5030, :5382-5400, :5792-5800, :5900-5905, :6328-6336, :6414-6420, :6506-6514, :6905-6930, :7160-7166,
  :7512-7550, :7578-7625, :7672-7693, :7762-7797) and `RAW_LAKE_DESIGN.md:2876-2902`, `:5070-5080`,
  `:6150-6170`, `:6350-6355`, and reproduced defect 16 with ripgrep 15.2.0; it read nothing else in full.

## Verification (cycle 3, targeted)

On 2026-10-24 the owner approved a targeted third pass over the 19 cycle-2 corrections only.

Verdict: DEFECTS. 1 residual defect (blocking). The other 18 corrections hold, and so do the fixer's
amendments (the head's "Role-mapping `role_scope` test case" resolution, M9.5's row-12 case, M4.1's note,
M10.1's `local_prefix` clause and the access-reset queue names). The fixed command forms of defects 6, 15 and 16
were reproduced on a scratch tree with ripgrep 15.2.0. "plan :N" is a line of this file; this section follows
them, so they do not shift.

1. **Blocking. M19.4 (cycle-2 defect 17, clause 3), plan :7678-7681; M1.7 :1235-1236, :1253-1257; M1.6 :1202.**
   - What: the new replacement clause says M1.6's DT-2 pattern without `password`
     (`SessionStore|…|local_credentials|…|redirect_url`) is re-run over `src tests` and prints nothing. But
     M1.7 creates `tests/contract/test_retire_legacy_raw.py`, and no later task deletes it. That file asserts
     that every dropped table is gone and seeds a row in each, and `local_credentials` (with its guard
     `local_credentials_kind_guard`, `migrations/schema.sql:290-294` at `fa51f46`) is one of those tables. So
     the file names `local_credentials`, and the re-run prints those lines. M1.7's own `tests` check already
     makes the same exception for the file, for the other dropped tables.
   - Why: M19.4's verification contains a check that cannot pass on the final tree, so the last
     verification task fails as written.
   - Correction: at :7680-7681, write "the pattern without `password` is re-run over `src tests` and prints
     nothing outside `tests/contract/test_retire_legacy_raw.py` (M1.7's drop test names `local_credentials`
     and its guard)".
   - Applied 2026-10-24 by the orchestrator after this check, as worded (M19.4's clause 3). With it, all 19
     cycle-2 corrections hold. The same pass aligned the Milestone sequence rows M0 and M19 with Phase 5's
     roadmap reconciliation (`design/roadmap.html` arrives with M0.1; M0.4 and M19.2 only verify the lines
     Phase 5 wrote).

## Execution notes

Entries are appended as tasks run, newest last, each headed by its task id: M0.1's baseline first, then
every deviation, receipt, `fail_under` change, duplication-baseline edit and owner receipt the tasks above
name. Nothing is recorded here before M0.1 runs.

### M0.1 baseline (measured 2026-10-24 on the planning base `6f4afd8`; `src/`, `tests/`, `migrations/` and `web/` are `fa51f46`'s)

- Plan-wide gate on `fa51f46`'s tree: all fifteen commands exit 0, `radon cc` and `radon mi` print nothing
  (the commands run in the order listed in "Plan-wide rules"): GATE PASS.
- `uv run lint-imports`: "Contracts: 16 kept, 0 broken."
- `uv run pytest -q`: 1524 passed, 47 deselected. `uv run pytest -m contract -q`: 32 passed, 1539 deselected.
  `uv run pytest -m integration -q`: 14 passed, 1557 deselected.
- Unit coverage, `uv run pytest -q --cov=src/huron --cov-report=json:<scratch>/baseline.json`
  (`totals`): `covered_lines` 5602, `num_statements` 5854, `percent_covered` 95.69525111035189 (252 missed;
  term-missing TOTAL 95.70 %). `fail_under` in `pyproject.toml` is 95.69 and was reached.
- Duplication guard, `uv run --locked python scripts/check_duplication.py src`: 123 clones in 41 groups
  (clone threshold 0.8, pyscn 1.31.1; 123 of 824 fragments cloned, 144 clone pairs, native score 75/100,
  reported and not gated), equal to `scripts/duplication_baseline.json` (`total_clones` 123, `clone_groups` 41).
- Legacy `/api/v1` operation count: 52 (paths x methods under `/api/v1` in `create_app(settings=<dev-headers
  settings>, stores=memory_stores()).openapi()["paths"]`, from a scratch script outside the repository run
  as `PYTHONPATH=. uv run python <scratch>/opcount.py`).
- From `web/`: `npm test`: 25 test files passed, 269 tests passed. `rg -c "^test\(" e2e/*.ts`: 39 top-level
  Playwright tests (ingestion 6, organizations 5, smoke 10, dataset-types 5, polaris 13).
- Gate summary, verbatim:

  ```text
  PASS  1 rc=0    1s     1 lines  uv run ruff check src
  PASS  2 rc=0    0s     1 lines  uv run ruff format --check src
  PASS  3 rc=0    0s     0 lines  uv run pydoclint src
  PASS  4 rc=0    1s     1 lines  uv run mypy
  PASS  5 rc=0    0s     1 lines  uv run ty check
  PASS  6 rc=0    1s    36 lines  uv run lint-imports
  PASS  7 rc=0    0s     0 lines  uv run python scripts/check_schema_map.py
  PASS  8 rc=0    0s     0 lines  uv run radon cc src --min C
  PASS  9 rc=0    1s     0 lines  uv run radon mi src --min B
  PASS 10 rc=0    0s   995 lines  uv run complexipy src --max-complexity-allowed 15
  PASS 11 rc=0    0s   230 lines  uv run --locked pyscn check src
  PASS 12 rc=0    1s    19 lines  uv run --locked python scripts/check_duplication.py src
  PASS 13 rc=0   66s   269 lines  uv run pytest --cov=src/huron --cov-report=term-missing
  PASS 14 rc=0   95s    28 lines  uv run pytest -m contract
  PASS 15 rc=0   19s    25 lines  uv run pytest -m integration
  GATE PASS
  ```

### M0.3 deviation: ADR 0006's Consequences list

- `docs/adr/0006-asynchronous-raw-commit.md` has one blank line between "Consequences:" and its first `-`
  item, which "DT-25 ADRs" does not have. Without it Zensical's Markdown (`make docs`) renders the four
  consequences as one paragraph with literal `- ` runs (checked in `site/adr/0006-asynchronous-raw-commit/`),
  where the design means a Consequences list. Every word and every other line break of the five ADRs,
  the ADR 0002 amendment block and `CONTEXT.md` is the design's text: the new ADRs without the design's
  `> ` quote markers, the ADR 0002 amendment keeping them as its block, and `CONTEXT.md` with the
  two-space indent stripped.

### M0.4 follow-up (orchestrator): the stale P3 sentence in `docs/backend-design.md`

- M0.4's verification found that `docs/backend-design.md:65-66` still says "The remaining P3 design and
  implementation plan stay at the repository root"; it has been false since `fa51f46` removed both files.
  No task, D-2 row or DT-26 row names that line, so M0.4 left it alone (task scope). M19.3, which edits
  `docs/backend-design.md` (`:14`, `:17`, `:31`), also rewrites this sentence: it points at the pinned P3
  links in `docs/history.md`'s "Archived plans" table instead of the repository root.

### M0.5 deviations: the `rbac.html` §8 default and the Bronze, Silver and Gold pages' remaining Raw coupling

- `design/rbac.html:439` (§8 "Recommended default policy") gets no wording of its own in DT-26's row, which
  words only §4's cell. Its "nobody overwrites committed raw" becomes "committed Raw files are overwritten
  only by a Developer's audited `overwrite` commit (§4)", linking §4 instead of restating the cell, so
  `rg -n 'overwrite: true' design/rbac.html` prints only the §4 line.
- `design/layer-bronze.html` (line numbers at `fa51f46`, unchanged at `HEAD` for this file): DT-26's
  replacements are applied wherever the page states the same Raw coupling, also outside the cited lines:
  the manual-intake validator check (`:232`, "raw link resolves to a COMMITTED revision of this dataset")
  becomes "each Raw pin resolves (§1): its collection's current file row, or an overwrite/rm audit entry
  for that rel_path, carries its sha256 (when asserted)", DT-25's resolution order, so a pin whose file
  has since been overwritten or removed still resolves; and §4b's seams sentence (`:279-280`) and "manual
  intake with a raw link" (`:283`) name the explicit build request and Raw pins. Inside the cited lines,
  the builder reads the pinned bytes through the mount (`:292`, DT-26's pin wording); both provenance
  examples drop `source_revision_number`, the first also `source_dataset` and `source_files` (a pin
  carries `rel_path` and `sha256`); the "Linked to Raw" bullet drops its cross-dataset sentence, because
  collections do not live under datasets; and the failed-build branch drops "raw retained for diagnosis"
  and the "Raw: committed" dataset state.
- `design/layer-bronze.html` tag model: DT-26 removes the `raw/{revision_number}` tag (`:115`) and names
  no replacement, and none is invented. §2's branch/tag bullet (`:112-117`) says every manual-intake
  snapshot, whichever provenance assertion it carries (Raw pins or external origin), is tagged
  `intake/{nnnnnn}`, and a Raw-derived build snapshot carries no tag and is resolved through its catalog
  row; §4b's builder publish step (`:304`) drops "tag, ", and §4a's manual-intake publish step (`:235`)
  keeps it.
- `design/layer-silver.html` and `design/layer-gold.html` (line numbers at `fa51f46`): beyond DT-26's rows
  (`:229-233`, `:294`, the `:247` href), the Silver page's other Raw-revision lineage and correction lines
  and the Gold page's lineage line take the Bronze page's pin and build wording, because DT-26 makes
  derived-layer lineage wording a T-docs-0 constraint (B-8) and no later task names them (M19.2 takes
  only Silver's `:244-248`; no task, DT-26 row or broken-links row names the Gold page beyond its kept
  `:154` `#layout` link). Silver: `:102` "raw-revision and Bronze-snapshot references" becomes "Raw-pin
  and Bronze-snapshot references"; `:108` "Bronze (per revision, …)" becomes "Bronze (per build, …)"; in
  `:155` and `:164` the correcting event is a new Bronze snapshot built after an `overwrite` of a pinned
  file; `:238` says B187 was built from new pins instead of "(revision 2)"; and `:316-317` shows
  materialization state per Bronze snapshot (`bronze: B187 published · silver: S118`) without
  "per-revision" or "raw: committed". Gold: `:193` (§3 `lineage`) ends its lineage chain
  `gold_version ← silver_snapshot ← bronze_snapshot ← Raw pins` instead of `← raw_revision`, as Silver
  and roadmap P9 do; the rest of the Gold page is unchanged (`:152-154` is hierarchy wording whose
  `#layout` link DT-26's broken-links table keeps).
  `rg -n -i 'revision' design/layer-gold.html design/layer-silver.html design/layer-bronze.html` prints
  nothing.

### M0.5 follow-up (orchestrator): Raw-revision wording no task names

M0.5's verification found these lines still describing Raw revisions or Raw-layer search. They lie outside
M0.5's cited lines and no task or DT-26 row names them, so each is routed to the task whose scope fits; that
task rewrites them in the lake's terms (pins, `overwrite`, the lake's own search) in its own commit.

- `design/catalog-search.html`: §1's "One index, all four layers" paragraph ("One LanceDB projection covers
  raw, Bronze, Silver and Gold"), the lede (`:83` at `fa51f46`) and the §1 question-table rows that name
  revisions or Raw metadata sidecars → M7.2, which already rewrites this page's DT-9 rows.
- `design/roadmap.html`: P6's same-dataset raw link and `--link-raw-revision 1` (`:471`, `:475-476`) and P7's
  gate ("a corrected revision of run-0042", `:485`) → M19.2, which edits the roadmap's remaining Raw items.
- `design/layer-bronze.html`: "feeds Raw retention" (`:164`), "same transfer surface as raw ingest"
  (`:224`) and the Raw TTL text (`:341-345`) → M19.2 (derived-layer pages, T-docs-Z).
- `design/api.html` §4: "per-revision materialization" (`:171`) and the intake body's `raw_revision_number`
  (`:175`) → M19.2.

### M1.1 deviations and receipts: the web Raw surface

- `web/src/lib/api/catalog-datasets.test.ts` asserts `datasetTypeLabel({ format: 'raw' })` is `'Generic'`, not
  DT-3's `datasetTypeLabel({ format: 'parquet' })`. `format` is the generic-table transport token (`'raw'` until
  M1.2 renames it), not Polaris's storage format, and DT-3's own contract (`format 'raw' -> 'Generic'; 'iceberg'
  -> 'Iceberg'; otherwise 'Icechunk'`) and source edit make `{ format: 'parquet' }` `'Icechunk'`. The contract
  ships unchanged; M1.2's rename turns the assertion's token into `'generic'`.
- `web/src/lib/server/polaris-browse.test.ts` and `polaris-dataset-governance.test.ts`: besides DT-3's named
  edits (no `isRaw`, no "Raw" in case names), the Polaris responses' storage `format: 'raw'` becomes
  `'parquet'`, so every generic-table input is non-Raw (owner decision 11, B-6), as in `polaris-raw.test.ts`.
  `polaris-raw.test.ts`'s metadata case passes the three dropped display properties with neutral values and
  asserts the exact returned key set.
- `design/polaris.html`: beyond the replaced section (`raw-outside-polaris`), the page's other Raw-surface
  lines leave so the page agrees with the web after D2-0 (AGENTS.md "Sources of truth"): "Raw generic tables"
  in `#icechunk-workspace`, "Raw identities", "Raw requests" and "Raw delegation" in `#organizations`, the Raw
  label rule, managed entries and Raw registration in `#dataset-types` (now the Generic rule), the Raw bridge
  sentence in `#architecture` and the Raw ingest sentences in `#samples`. Iceberg and Icechunk text is unchanged.
- `design/layer-raw.html`: the "Polaris web integration" note (`:93-101` at `fa51f46`), which described the
  deleted wizard and bridge, becomes a two-line note linking `polaris.html#raw-outside-polaris`, rather than
  only re-pointing its link; M1.3 rewrites the page.
- `web/README.md` `:128` ("or Raw identities") leaves with DT-3's cited lines, for the same reason. Its
  `ace_source_files` bullet (`:67`) now describes a generic-table registration labelled Generic, which stays
  true until M1.4 removes that registration from `scripts/seed_catalog_types.py`; M1.4 does not edit
  `web/README.md`, so that bullet and "all three dataset types" (`:53`) need M1.4's attention.
- Receipt, `npm test`: 19 files, 215 tests (the owner-approved plan-time resolution corrects DT-3 R3-3's 219). The deleted
  `describe('Raw collection registration')` holds six Vitest cases (two `it` and a four-row `it.each`), not
  two: 269 − 48 − 6 = 215. Every adapted case keeps its count (`polaris-raw.test.ts` 5, `catalog-datasets.test.ts`
  9). M1.1 and M1.2 both expect 215 under that resolution.
- Receipt, DT-3's first closing check: with `-i`, its `isRaw` term matches `PolarisRawTable` and
  `PolarisRawTableIdentifier` ("Polar**isRaw**Table"), so after M1.1 it prints exactly those lines in
  `polaris-raw-types.ts`, `polaris-browse-types.ts`, `types.ts:155`, `GenericTableDetail.svelte`,
  `polaris-raw.ts` and `polaris-client.ts`, the names DT-3's D2-0b table lists as present after D2-0. Every
  other term prints nothing; the owner-approved resolution permits only these matches until M1.2 and requires
  the case-sensitive whole-word `isRaw` check to print nothing. M1.2's rename removes those lines, so M19.4's
  re-run prints nothing.
- Resumed implementation audit (2026-10-24): the seven Svelte autofixer runs report no issues. The layout's
  sole suggestion is to consider an attachment instead of `bind:this`; it does not apply to this deletion:
  the unchanged dialog reference is used by the navigation buttons to call `showModal()` and `close()`.
  Formatting the changed web files changes no bytes. `npm run check`, `npm test`, `npm run lint`,
  `npm run build` and `npm run test:e2e` exit 0. Playwright executes 36 cases: 30 top-level declarations
  and six cases generated by the existing viewport loops. The closing checks and the untouched-surface
  diffs against `fa51f46` satisfy M1.1's expectations. Independent verification was pending at that point.
- Resumed Python/docs receipts: `make lint` exits 0 (16 kept import contracts; empty radon CC/MI output;
  no dead-code or structural findings; duplication unchanged at 123 clones / 41 groups, native score 75).
  The unit coverage run passes 1524 tests with 47 deselected: 5602 covered / 5854 statements, 95.70%,
  against the unchanged 95.69 floor. Contract: 32 passed; integration: 14 passed; `make docs` and
  `git diff --check` exit 0. No Python source, tests, configuration or root README changes.
- Resumed browser QA: isolated Chromium checks cover the home, admin, folder and Generic detail pages at
  390, 816 and 1440 px in both themes, Generic filtering and its empty state, all Generic tabs through
  keyboard Enter with visible focus, and concealed 404s for missing tables and unsupported version selectors.
  No document overflow or runtime/hydration errors were observed. The scratch check initially expected 400
  for a version selector; the existing contract requires 404, and the corrected scratch check passes.
  Screenshots expose unchanged sidebar footer copy, "Raw · Iceberg · Icechunk", outside DT-3's named
  layout edit; this was reported to the orchestrator for a scope ruling rather than changed silently.
- Independent verification attempt 2 (2026-10-24): PASS. The Codex verifier
  `m11_verification_2` was explicitly configured as `gpt-6-astra` with `medium` reasoning.
  It independently reran the full gate: `make lint` (16 import contracts, empty radon output,
  123 clones / 41 groups), 1,524 unit tests (5,602 / 5,854 statements, 95.70%, floor 95.69
  unchanged), 32 contract tests, 14 integration tests and `make docs`. All seven Svelte
  autofixers, changed-file formatting checks, `npm run check`, `npm test` (215 tests in
  19 files), `npm run lint`, `npm run build` and `npm run test:e2e` (36 cases) passed.
  Closing checks, protected-surface diffs against `fa51f46` and `git diff --check` passed.
- Independent browser QA: 38 observations passed against fresh isolated state, at 390, 816
  and 1440 px in both themes. The verifier inspected Generic detail screenshots for all six
  viewport/theme combinations and home, admin, folder and empty states; keyboard tabs retained
  visible focus, filters and concealed 404s worked, and there was no document overflow or
  runtime/hydration error. The corrected desktop footer was visible in both themes. The
  owner's stack was untouched, and all validation and QA processes stopped before handoff.
- Verification tooling recovery: sandbox restrictions initially blocked the uv cache and npm
  lookup. Authorized reruns passed; the interrupted autofixer batch was confirmed stopped
  before resuming the same verification attempt. No source edits or additional verification
  attempt resulted. Exact outputs, the report and screenshots are retained locally under
  `/tmp/huron-m11-v2/` and `/tmp/huron-m11-v2-*.log`. No findings remain; M1.2 is still pending.


### M1.2 execution notes — implementation attempt 1 (2026-10-24)

- Renamed the three generic-table modules and all callers, transport tokens, browse fields/error keys,
  pagination fields and URL parameters to `generic`. The namespace type mapping now reads the format
  directly. Medallion-layer `raw` values and opaque fixture locations/page tokens are preserved.
- Extended the existing invalid browse-selection test to assert the old format returns 400 with
  "Choose a supported table format." before an upstream request; no alias is accepted. The existing
  Reader e2e deep link uses the new token. Vitest remains 19 files and 215 tests.
- Full Python gate passed: all 12 static commands, 16 import contracts, empty radon findings,
  duplication guard at 123 clones/41 groups (native score 75/100), 1,524 unit tests at 95.70%
  (5,602/5,854 statements), 32 contract tests and 14 integration tests. No Python or floor change.
- Five Svelte autofixer runs, changed-file formatting, check, Vitest, lint, build and all 36 e2e
  tests passed. Autofixer's existing external provenance-link suggestion in `DatasetDetail.svelte`
  is inapplicable to an http/https URL; `NamespaceExplorer.svelte`'s Map is built within `$derived.by`
  and replaced on recomputation, so it needs no independently reactive mutation. No suppressions added.
- Real Chromium QA passed at 390, 816 and 1440 px, light and dark: generic detail and filters, empty
  state, keyboard tabs with visible focus, generic pagination, old-format 400, and concealed missing
  table/version-selector 404. Screenshots were inspected; no clipping, horizontal overflow or
  hydration errors. The isolated mock's scratch copy adds a next-page token for paging QA only.
  An initial scratch selector incorrectly scoped pagination inside the table region; correcting the
  `/tmp` harness produced a full pass without source changes.
- `make docs`, both closing greps (no matches), the untouched-surface `HEAD~1` diff (empty), and
  `git diff --check` passed. Full command outputs, autofixer rationale, browser screenshots and the
  report are in `/tmp/huron-m12-i1/`. Sandbox cache/network failures were retried escalated and the
  failed logs retained. All launched validation/QA processes exited; the owner's stack was untouched.
- Status remains pending for independent verification; no additional deletions or renames requested.


### M1.2 execution notes — fix/revalidation pass 1 (2026-10-24)

- Independent verification attempt 1 returned FAIL: its required e2e gate passed 35/36, with a
  5-second catalog-create status timeout in the unchanged organization-admin setup. Original failed
  output and DOM evidence remain in `/tmp/huron-m12-v1/`; the verifier's later traced diagnostic
  36/36 pass does not erase the failure or establish its cause.
- A bounded scratch browser harness repeated the exact catalog-create navigation, inputs, click and
  5-second status expectation 20 times across four concurrent browser contexts and organization
  realms. Every form was natively valid, every POST returned 200, and all 20 status assertions passed
  in 326–1,206 ms. It captures validity and request/response timing without credentials or bodies.
  This narrowed trigger workload does not reproduce every full-suite scheduling condition.
- Root cause remains unproven. No source, protected test, timeout, assertion or configuration was
  changed; no speculative fix or misleading regression test was added. The first failure remains
  part of the record, rather than being described as fixed.
- One fresh complete gate passed without retries: all 12 static commands, 16 import contracts,
  empty radon findings, unchanged 123-clone/41-group duplication guard; 1,524 unit tests at 95.70%
  (5,602/5,854), 32 contract tests and 14 integration tests; all five autofixer reviews, formatting
  check, Svelte check, 215 Vitest tests, lint, build and all 36 e2e tests. Existing non-applicable
  autofixer observations are unchanged. `make docs`, both closing greps, untouched-surface and
  Python-unchanged checks, and `git diff --check` passed. Coverage floor and before JSONs are untouched.
- Fresh real-browser QA passed generic paging, old-format 400, concealed errors, filters/empty state,
  keyboard focus and tabs at 390/816/1440 px in both themes, with no overflow or hydration errors.
  Scratch services/browser and all validation processes exited; no owner-stack operation occurred.
- Full fresh receipts and diagnosis: `/tmp/huron-m12-fix1/report.md`, `diagnosis.md`, numbered
  Python/frontend logs, `diagnostic-results.json`, `qa.log` and screenshots. Status remains pending
  for independent verification attempt 2. This pass changed only these execution notes.

- Independent verification attempt 2: PASS. The Astra/Medium verifier reran the full gate and
  browser QA independently: 1,524 unit / 32 contract / 14 integration tests, 95.70% unit coverage,
  215 frontend tests and 36 end-to-end cases, all passed. The required browser gate passed on its
  first invocation; the original attempt-1 timeout remains recorded with unknown cause. Static,
  Svelte, formatting, build, docs, closing and protected-surface checks passed; no source changes
  or weakened tests were needed. Report and exact outputs: `/tmp/huron-m12-v2/report.md`.
  All launched sessions exited, and the orchestrator confirmed no validation processes remained.
- Pre-deletion coverage evidence for M1.3 was captured by the independent verifier before any
  Python changes: `/tmp/huron-m13-before.json` (5,602 / 5,854 statements) and
  `/tmp/huron-m13-before-contract.json` (5,833 / 5,854, 1,556 unit/contract tests). M1.2 changes
  no Python files, so these reports remain the M1.3 starting baseline.

### M1.3 execution notes — implementation attempt 1 (2026-10-24)

- Removed the Raw bridge's router, HS256 delegation, external-dataset/publication ports and adapter,
  settings and composition wiring. The orchestrator removed the eleven named whole files; this pass
  removed the remaining symbols and the launcher's Raw API/database/secret branches, including
  `raw_environment`. The Polaris launcher was not run, and the owner's stack was untouched.
- The router tests pin the exact 52 legacy path/method operations, anonymous 401 problem responses for
  every operation, 15 resource tags, and the retired prefix's absence/404 with or without a legacy
  credential. The execution-model inventory drops the eleven bridge handlers. The shared store builder
  and direct settings tests contained no bridge arguments/cases; they need no edits. The existing error
  contract passes unchanged: no error class or §7 row lost its last raise site.
- Replaced the Raw engine design sections with the lake lede, target-design status, Polaris and History;
  moved the pinned P3 links to History and updated the catalog-search inbound link. The DT-26 outline's
  past-tense claim that the whole engine was deleted on 2026-10-23 would be inaccurate at this step:
  History instead records the bridge's removal and the remaining engine's retirement in progress.
  The intentionally retained inbound `layout`/`commit` fragments return with their owning later tasks.
- Independent before reports are preserved in `/tmp/huron-m13-i1/before.json` and
  `before-contract.json`. Unit: 5,602 covered / 5,854 statements → 5,222 / 5,450; missing statements
  252 → 228. The seven deleted source files account for 364 covered / 388 total statements; deleted
  statements in app/capabilities/runtime/settings account for another 16 covered / 16 total. The exact
  covered drop is therefore 380 and total drop 404. Surviving statement identities were mapped against
  `91a768d`, including the edited capabilities import, rather than comparing shifted line numbers.
  No surviving statement gains a miss, no coverage gain masks a loss, and every modified source file
  is at 100% (app 107/107, capabilities 10/10, runtime 67/67, settings 56/56).
- Unit+contract: 5,833 / 5,854 → 5,436 / 5,450 (99.74%); exactly 397 covered / 404 total statements
  removed, no new misses or gains. Unit count: 1,524 → 1,500 (27 removed bridge cases, three added
  invariant tests); contract: 32 → 31 and integration: 14 → 13 (both lost cases were in the removed
  integration module). Combined measurement passes 1,531 tests. The coverage floor is now
  `floor(10000 × 5222 / 5450) / 100 = 95.81`, up from 95.69; the subsequent configured unit gate
  passes 1,500 tests at 95.82%. Detailed per-file/line evidence is in `coverage-evidence*.json`.
- All twelve static commands pass; import-linter keeps 16 contracts; both radon outputs are empty.
  Duplication remains 123 clones / 41 groups (native score 75/100), so no baseline edit was needed.
  Standalone contract and integration gates, `make docs`, `bash -n scripts/polaris-dev.sh`,
  `uv run python -m py_compile scripts/polaris_dev.py`, local design-link target checks and closing
  greps pass. The sole bridge-name grep output is the three allowed migration-revision references.
  No web files changed, so frontend checks do not apply.
- Validation recovery: the initial focused test call hit the uv-cache sandbox restriction and passed
  on the immediate escalated retry. One initial coverage receipt was invalid because removal of a
  stale settings comment shifted line numbers after module import; it is retained as
  `invalid-during-comment-edit.*` and is not used for the floor. Frozen-source unit and combined
  receipts, plus the final configured unit receipt, agree. Concurrent coverage runs used separate
  coverage data files. No assertion, exclusion or suppression was weakened or added.
- Full outputs and implementation report: `/tmp/huron-m13-i1/`. All launched validation processes
  exited. Task status remains pending for independent verification; no additional file deletion or
  rename is requested.

- Independent verification attempt 1: PASS. The Astra/Medium verifier independently ran all
  static checks (16 import contracts, unchanged 123-clone/41-group baseline), 1,500 unit tests,
  31 contract tests, 13 integration tests, combined coverage, docs and script checks. Its own
  statement mapping confirms 380 covered / 404 total unit statements removed and 397 covered /
  404 total combined statements removed, with no surviving loss and all four edited source
  modules at 100%. The 95.81 floor is exact. Report: `/tmp/huron-m13-v1/report.md`; complete
  outputs: `/tmp/huron-m13-v1/full-gate-output.txt`. All runner sessions exited and the parent
  confirmed no validation processes remained.
- Next-task baseline captured before M1.4 deletions: `/tmp/huron-m14-before.json`
  (5,222 / 5,450 statements) and `/tmp/huron-m14-before-contract.json` (5,436 / 5,450).

### M1.4 execution notes — implementation attempt 1 (2026-10-24, stopped)

- The pre-step inventory at `1519c98` found 28 matching test files: 12 whole-file matches,
  16 partial matches and no unlisted matches. Inspection found `test_catalog_documents.py`
  wholly obsolete (all Raw document/manifest/revision/frozen-commit tests); the orchestrator
  reclassified and deleted it. `test_api_settings.py` additionally required partial removal
  of assertions for the four deleted settings. No additional whole files were deleted by
  the implementer. Rawstore and credential workflows remain for their next assigned tasks.
- Removed Raw engine wiring, guards, routes, settings, error codes, metastore ingest state,
  retry exemptions and associated named tests; retained generation storage through the
  renamed `ApiRuntime.generations`. Updated the requested nightly workflow and document
  handoffs, including the stale layer-raw history and web seed instructions. This is an
  incomplete working tree, not a completed task.
- The duplication scan triggered the task's stop rule before any baseline edit: 89 clones,
  30 groups, native score 70. The new creation-only signature (size 3 from creation/Raw-ingest
  size 4) and hierarchy/principals (size 4 from hierarchy/ingest/principals size 5) are literal
  deletion subsets. The grown rbac-only signature (size 6; prior singleton size 3) is not:
  its possible size-12 parent also contains surviving hierarchy.py. It therefore cannot be
  admitted under the rule allowing only loss of whole files deleted in this task. Baseline
  remains untouched; no signature was added and the capped-signature running total is zero.
- Independent before coverage remains 5,222 / 5,450 unit statements (1,500 tests) and
  5,436 / 5,450 combined statements (1,531 tests). No after measurement or floor adjustment
  was made; `fail_under` remains 95.81. Feedback collection initially selected 1,181 unit
  tests before six additional settings/slug cases were retired. Ruff and mypy feedback passed,
  as did 18 app-lifecycle/readiness tests. A leftover Raw transaction flush was fixed; the
  next feedback failure is `test_api_rbac.py` calling a removed ingest route and still needs
  adaptation. Full gates, coverage proof, documentation/closing checks and frontend checks
  remain outstanding due to the stop condition.
- Tool recovery: uv-cache access succeeded on immediate escalation. Automatic approval review
  rejected one broad scripted edit; it never ran. Smaller exact module edits and visible
  patches were accepted. No owner stack was operated, no files staged or committed by the
  implementer, and no launched process remains. Full handoff and exact logs:
  `/tmp/huron-m14-i1/report.md`. Task status remains pending.

### M1.4 execution notes — resumed implementation attempt 1 (2026-10-24)

- The owner explicitly approved the narrow regrouping exception after the mandated stop.
  All six current `rbac.py` fragments retain their pre-task hashes and originate in group 16
  (size 12, hierarchy/ingest/rbac); the file itself remains byte-identical to `1519c98`
  (`496885925375030b69773287aa9c23c21a9f4a02`). Evidence:
  `/tmp/huron-m14-preflight/rbac-regrouping-proof.json`, pre-scan
  `.pyscn/reports/analyze_20261024_224655.json`, post-scan
  `.pyscn/reports/analyze_20261024_230400.json`. Only this size-6 signature is additionally
  permitted; the total-clone ratchet, all other signature rules and all quality thresholds remain.
  M1.4's task-specific wording now records that exception. No generalized exception was added.
- The reviewed baseline admits exactly three scanned signatures: creation.py alone, size 3,
  from creation.py/Raw ingest.py size 4; hierarchy.py/principals.py, size 4, from
  hierarchy.py/metastore ingest.py/principals.py size 5; and the explicitly approved rbac.py
  singleton size 6 above. The intermediate signature inventory was 44 (41 + 3), with the
  total-clone ceiling held at 123; the successful ratchet is 89 clones / 30 groups,
  538 fragments, 92 pairs, native score 70/100. Capped-signature running total remains zero.
  Original baseline and exact entry receipt: `/tmp/huron-m14-i1/duplication-before.json`
  and `duplication-approved-entries.json` in that directory. An initial ratchet rejected
  stale group-count metadata (41); correcting it to 44 permitted the reviewed ratchet.
- Finished the surviving API RBAC test's partial adaptation and removed only obsolete settings
  cases. Contrary to the task's environment/test note, `scripts/test_catalog_types.py` did
  contain an exclusive Raw source-copy test. Removed that method with `preserve_file`, keeping
  the three live SDK cases. All three pass in the existing Icechunk SDK environment; uv still
  lacks pyiceberg. No local stack was started, stopped, reset or installed.
- Final frozen-source measurements: unit 3,729 / 3,873 statements, 1,175 tests (from
  5,222 / 5,450 and 1,500 tests); combined unit/contract 3,863 / 3,873, 1,193 tests
  (from 5,436 / 5,450 and 1,531 tests). Diff-aware statement maps account for exactly
  1,493 covered / 1,577 total unit statements removed and 1,573 covered / 1,577 total
  combined statements removed, with no surviving coverage loss and no offsetting gains.
  Renamed generation capability statements, narrowed base lists and the simplified claim
  condition are explicitly mapped. Existing canonical-order and document-read tests were
  extended to retain direct evidence for `content_identity` and `stat_document`, whose
  covering Raw tests left. No new duplicate test case or production-code change was needed.
- The exact floor is `floor(10000 * 3729 / 3873) / 100 = 96.28`, raised from 95.81.
  All modified source files have 100% unit coverage except PostgreSQL hierarchy.py, measured
  with contracts: its sole missed line is 661, the unchanged claim-vanished defensive
  `RuntimeError` (base line 762, already missed). The transaction retains the conflicting
  claim row lock, so its subsequent SELECT cannot lose that row through a concurrent delete.
  This specific preexisting unreachable branch is submitted for the independent verifier's
  judgment; no exclusion or mock test was added to conceal it.
- Required checks passed: all 12 Python static commands (14 import contracts, no radon
  findings, no dead-code/complexity findings, duplication guard green), docs, 14 error-code
  tests, script compilation, 18 standalone contract tests and 12 integration tests. The
  README-only frontend gate passed check, 215 unit tests, lint, build and 36 e2e tests.
  All exact closing greps have no matches with the task's explicit exclusions; nightly YAML
  has the exact single job, triggers, label gate and pinned steps. No acceptance test remains;
  only its Makefile dry-run was inspected. Source hashes remained frozen during coverage.
- Evidence: `/tmp/huron-m14-i1/after.json`, `after-contract.json`, and the two
  `coverage-evidence*.json` files preserve reusable measurements and per-statement mappings.
  Full gate receipts and final configured coverage run are in that directory's report and
  `full-gate-output.txt`. Task remains pending for independent verification.
- The configured final unit gate passed 1,175 tests at the new 96.28 floor;
  `after-final.json` exactly matches the measured unit report's executed/missing lines.
  All task validation processes exited. The preexisting Vite server (PID 66410, started
  2026-10-13) was left untouched; process provenance is in the implementation report.

### M1.4 execution notes — browser diagnosis after verification attempt 2 (2026-10-25)

- Verification attempt 2 remains FAIL: 31 browser cases passed and five failed; all
  Python, static, documentation and other frontend checks passed. Original evidence
  is preserved in `/tmp/huron-m14-v2/`; no failed case was retried during diagnosis.
- Independent macOS lifecycle evidence identifies an interrupted test environment.
  The unified power log records `kIOMessageSystemWillSleep` at 07:38:03.735 MDT;
  all three `ERR_NETWORK_IO_SUSPENDED` artifacts were created at 07:38:04. Idle
  Sleep ran from 07:38:33 to 07:38:57; the namespace timeout and admin-navigation
  timeout artifacts were created at 07:38:57 and 07:38:58. The admin refusal
  snapshot is expected content for the test's final HTTP 403 assertion. Current
  test names were checked because emitted source locations were inconsistent.
- Diagnosis evidence and ranked falsifiable alternatives are recorded in
  `/tmp/huron-m14-fix2/diagnosis.md`, with original artifact timestamps, unified
  logs and `pmset` logs beside it. No application, test, timeout, assertion or
  configuration change was justified or made. Deliberately putting the owner's
  machine to sleep was not used as a reproduction experiment.
- The single fresh complete gate passed with process-scoped `caffeinate -i`:
  all 12 static commands, docs, 14 error-contract tests, script compilation, three
  SDK tests, 1,175 unit tests, 18 contract tests, 12 integration tests, and 1,193
  combined unit/contract tests; frontend check, 215 unit tests, lint, build and all
  36 browser cases passed. Exact closing greps/YAML checks and `git diff --check`
  passed. Unit coverage remains 3,729/3,873 (96.28%); combined remains 3,863/3,873.
  Every measured source hash and executed/missing coverage line matches attempt 2.
- Fresh OS logs show no sleep during validation; captured assertions prove the
  temporary sleep prevention was active. The browser suite ran once, with no test
  retries. All test-owned processes and assertions exited; ports 4173 and 8189
  have no listeners. The owner stack and preexisting Vite PID 66410 remain untouched.
  Exact outputs and report are in `/tmp/huron-m14-fix2/`. The environmental control
  should also cover independent verification. M1.4 remains pending that verification;
  attempt 3 has not been used.

## Escalation

### M1.4 — verification cap reached (2026-10-25)

M1.4 is **incomplete and uncommitted**. M1.1–M1.3 are committed through
`1519c98`; M1.5–M4 have not started. The third verifier returned FAIL, so the
invoked `.claude/commands/implement-markdown.md` iteration cap stops execution.
No fourth fix pass, subsequent task, or M1.4 commit was attempted.

Verification reports:

1. `/tmp/huron-m14-v1-recovery/report.md`: four small cleanup findings. All
   gates passed; all four findings were corrected in fix pass 1. This report
   recovers the interrupted original verification attempt, not an extra attempt.
2. `/tmp/huron-m14-v2/report.md`: five browser failures while macOS entered
   sleep. `/tmp/huron-m14-fix2/diagnosis.md` correlates the OS sleep notification
   with all three network-suspended artifacts and wake with the two timeout
   artifacts. One fresh full gate under process-scoped `caffeinate -i` passed
   without application, test, assertion, timeout or threshold changes.
3. `/tmp/huron-m14-v3/report.md`: one small remaining cleanup issue, explicitly
   classified as fixable within the current plan: three empty section headings
   for deleted `dataset_raw_writer`, `project_intake`, and
   `session_overseer/session_owner` at
   `tests/unit/test_authorization_guards.py:411,414,417`.

The final complete gate is green: all static checks and docs; 1,175 unit tests,
18 contract tests, 12 integration tests, 1,193 combined unit/contract tests;
215 frontend unit tests and 36 browser tests. Unit coverage is 3,729/3,873
(96.28%); combined is 3,863/3,873. Independent diff mapping establishes no
surviving coverage losses or offsetting gains. The approved narrow duplication
regrouping is verified; the guard reports 89 clones in 30 groups. The only
review finding is the three orphaned comments. All owned validation processes
have stopped; the owner's stack and preexisting Vite were untouched.

The working tree builds and its automated gate passes, so no revert or isolation
is necessary. The partial M1.4 source/test/document changes, staged deletions and
workflow rename remain intact and uncommitted; unrelated workflow and research
changes remain preserved. The task's status remains pending. The preceding
fix-pass note that attempt 3 was unused describes that earlier checkpoint and
is superseded by this escalation.

Diagnosis: the prescribed cap was exhausted by incremental cleanup findings and
an independently evidenced environmental interruption. There is no demonstrated
architectural defect, ambiguous business contract or irreducible complexity.
The concrete remaining correction is deletion of three stale test comments.
The workflow's mandatory architectural escalation is procedural; this report
does not invent a design defect to justify it.

Questions before resumption: does review confirm that the three headings are
purely obsolete and require no retained behavior, and how should the execution
plan resume after this exhausted verification cycle? No scientific-domain or
runtime design decision has been identified as unresolved.

Required next prompt invocation (Codex reads this command file; it is not a shell
executable):

```text
./.claude/commands/architectural-review.md tests/unit/test_authorization_guards.py RAW_LAKE_M14_ARCHITECTURAL_REVIEW.md "Assess the remaining retired-guard comment cleanup and whether any actual architectural issue exists; preserve unrelated work" RAW_LAKE_IMPLEMENTATION_PLAN.md#escalation
```

After that review, the workflow recommends a focused companion plan rather than
overwriting the existing partially delivered plan:

```text
./.claude/commands/design-plan.md tests/unit/test_authorization_guards.py RAW_LAKE_M14_RECOVERY_DESIGN.md RAW_LAKE_M14_RECOVERY_PLAN.md "Resolve the capped M1.4 cleanup and specify resumption of RAW_LAKE_IMPLEMENTATION_PLAN.md without reopening settled domain decisions" design/roadmap.html "RAW_LAKE_IMPLEMENTATION_PLAN.md#escalation; RAW_LAKE_M14_ARCHITECTURAL_REVIEW.md"
```

### M1.4 owner-authorized completion (2026-10-25)

The owner explicitly authorized fixing the three stale test headings and moving
on to M1.5 after the capped review. An Astra/medium cleanup agent removed exactly
those headings and trailing whitespace; AST comparison confirms executable test
code is unchanged, and `git diff --check` passes. Parent independently confirmed
the three retired headings are absent. The final verifier's full green gate and
coverage evidence remain applicable: no executable source/test statement changed.
M1.4 is complete under this explicit owner-authorized resolution; the historical
FAIL reports above remain preserved rather than relabeled PASS. The escalation
stop and proposed review/replanning commands are superseded by this instruction.

### M1.5 execution notes — implementation attempt 1 (2026-10-25)

- Base `990ca2a`; Codex implementation agent assigned Astra/medium, no nested agents.
  The orchestrator performed the six listed whole-file deletions and the store rename first.
  Deleted generation-half and `fsync_dir` tests were read from the base before adaptation.
  Task status remains **pending** until independent verification.
- Reduced `PosixGenerationStore` has the specified Path-only constructor, read-only root,
  organization-only initialization, generation writer and private atomic replacement.
  Existing-file replacement, durable generation-before-pointer ordering, complete writes and
  failure cleanup are directly tested. API construction and surviving concrete-store callers use
  the new name and Path argument. The readiness timeout test injects its stalled filesystem read
  through `Path.exists` instead of assigning the now read-only root.
- The six descriptor primitives and `CompletionAdmission` have unchanged ASTs; `fsync_dir`
  moved verbatim. Dedicated survivor tests pass: 58 tests; `materialize.py`, `completion.py`,
  `generations.py` and the public exports are each 100% covered by those three modules alone.
  Pre-edit searches found no external production callers of retired members; post-edit searches
  for each retired member and both exact closing checks print nothing. The production rawstore
  importer search lists only `applications/api/app.py`.
- Full gate: `make lint` passes (14 import contracts; no radon findings); 1,067 unit tests,
  18 contract tests and 12 integration tests pass. The combined unit/contract measurement passes
  1,085 tests. `make docs` reports no issues. No frontend files changed, so frontend gates do not
  apply. Only ephemeral PostgreSQL testcontainers were used; the owner's stack was untouched.
- Coverage baseline JSONs are `/tmp/huron-m15-before.json` and
  `/tmp/huron-m15-before-contract.json`. Frozen-source after reports and the diff-aware proof
  are under `/tmp/huron-m15-i1/`. Unit counts move from 3,729/3,873 to 3,481/3,625;
  combined counts move from 3,863/3,873 to 3,615/3,625. The mapped store rename, moved
  `fsync_dir`, narrowed signatures and retained organization creation show no surviving coverage
  loss or offsetting gain. All 144 unit misses and ten combined misses are unchanged. The net
  248-covered-statement reduction is 256 removed/reexpressed covered statements minus eight
  fully covered required import/export/root-property statements. Every changed source file is
  100%. Unit test count changes from 1,175 to 1,067 (-108). The exact floor is
  `floor(10000 × 3481 / 3625) / 100 = 96.02`; the final enforced-floor run passes (96.03% displayed).
- Duplication ratchets from 89 clones / 30 groups to 87 / 29, native score 70/100.
  The old `(rawstore/materialize.py, rawstore/store.py)` group disappears entirely, so no
  re-path, subset hand edit or capped signature is required. G1's capped-signature running
  total remains zero; no broader exception was applied.
- Exact commands, output, exit statuses, caller proofs, source hashes and the implementation
  report are in `/tmp/huron-m15-i1/`. Initial feedback exposed a missing import, old string
  constructor arguments and the obsolete root assignment; those were corrected before the
  successful complete runs. Source remained frozen across the final coverage measurements.
  Validation used process-scoped `caffeinate -i`; all owned validation processes exit at handoff.

### M1.5 independent completion

Verification attempt 1 passed with no findings: `/tmp/huron-m15-v1/report.md`.
All full gates and coverage/clone proofs passed; independent M1.6 before reports
are `/tmp/huron-m16-before.json` and `/tmp/huron-m16-before-contract.json`.
The verifier also confirmed that `test_postgres_credential_conflicts.py` covers
only the retiring local credential store, satisfying M1.6 deletion preflight.

### M1.6 implementation evidence — 2026-10-25 (verification pending)

Implementation at base `528bfe8` removes the Python login/session/code-flow surface,
its stores/settings and `/auth` router while preserving bearer discovery/verification,
API keys, service-account keys, dev headers and user disablement. The parent reviewed
`test_api_oidc.py` and deleted it whole: all twelve cases were browser-flow tests;
bearer and discovery tests remain in their dedicated modules. The caller-free
`api_settings`/`Settings` wiring also leaves with its only route consumers. The mixed
RBAC delegation scenario retains its supported operations and checks key revocation
through the layers route instead of retired introspection.

The duplication guard initially stopped on a size-2 signature, not the predicted
size-3 one. The owner explicitly approved only
`src/huron/core/metastore/api_keys.py` + `src/huron/core/metastore/memory_principals.py`:
base scan group 16 had seven fragments across six files; current group 17 has two.
The surviving fragments are byte-identical: `api_keys.py:47–70`, pyscn hash
`5b34c9c982c37e22`, and `memory_principals.py:85–100` → `41–56`, hash
`337c5a776ab6cbee`. The third surviving-file member was
`principals.py:56–81` (`get_user_by_subject`), deleted by this task. The approved
signature was added at size 2, then the updater ratcheted the baseline from
87 clones/29 groups to 76 clones/26 groups. No other new signature was admitted;
this task adds zero capped signatures, leaving G1's capped running total unchanged
at zero. The exact task rule above records this narrow exception.

Frozen-source coverage maps retain reduced imports, tuple arities and call signatures
explicitly. Unit coverage moves from 3481/3625 to 2832/2958: exactly 667 statements
removed, 649 covered, zero surviving coverage losses or gains, and zero new missed
statements. The floor moves from 96.02 to
`floor(10000 × 2832 / 2958) / 100 = 95.74`. The unit inventory moves from 1067 to 899.
Combined unit-or-contract coverage moves from 3615/3625 to 2955/2958: 667 covered
statements deleted and seven independently listed gains in surviving PostgreSQL
adapter error/empty-input paths, with zero losses. Extended existing real-PostgreSQL
contracts cover repeated binding revocation, empty binding lookup, service-account
subject lookup and a principal primary-key collision with a controlled UUID source.
Every modified source module reaches 100% at its prescribed measurement tier; no
unreachable-code exception is needed. Baseline reports remain unchanged.

Evidence lives under `/tmp/huron-m16-i1`: `coverage.py`, `coverage-proof*.json`,
`touched-coverage.json`, `source-freeze.json`, `duplication-provenance.json`, preserved
before/current clone scans and final command logs. The implementation report records
final gate receipts and process shutdown. Task status remains pending until independent
verification. No frontend files changed and no owner stack lifecycle operation ran.

### M1.6 fix pass 1 — 2026-10-25 (verification 2 pending)

Verification 1's two findings are fixed: removed orphan `T0` from
`tests/unit/test_auth_oidc.py`, preserving used datetime imports; corrected the
stale disablement and malformed lookup descriptions in `test_auth_store.py`.
The partial-test prose sweep also removed that file's obsolete “admin provisioning”
heading phrase. No test behavior or production source changed.

All twelve static commands, unit (899), contract (18), integration (12), combined
unit-or-contract (917), docs, compose syntax, Makefile dry-run, focused error/router/
disable tests (38), exact closing checks and diff whitespace checks passed. Fourteen
import contracts remain; radon outputs are empty; duplication remains 76 clones/26
groups, native score 70. Unit 2832/2958 and combined 2955/2958 match verification 1
exactly, including every file's coverage data. Source hashes, coverage floor, clone
baseline and all saved before JSON reports are unchanged. Evidence and exact output
live in `/tmp/huron-m16-fix1/report.md`, `validation-output.txt`, command manifests,
`proof.json` and their adjacent logs. All launched validation processes and scoped
caffeinate exited. No frontend files changed; independent verification 2 is pending.

### M1.6 independent completion

Verification attempt2 passed with no findings: `/tmp/huron-m16-v2/report.md`.
All required static,899unit,18contract,12integration,917combined,docs and closing
checks pass. Final coverage and exact owner-approved duplication provenance were
independently verified. The next-task baseline reports remain
`/tmp/huron-m17-before.json` and `/tmp/huron-m17-before-contract.json`.


### M1.7 implementation evidence — 2026-10-25 (verification pending)

Added the unconditional, irreversible `0014_retire_legacy_raw` revision after
`0013_retire_releases`, dropping all fourteen legacy tables and five guard functions,
deleting obsolete lineage edges and narrowing both endpoint vocabularies. Updated the
schema map and retired roadmap P2 while preserving its archived plan and run receipt.
Removed tests and helpers for discarded tables; surviving catalog lifecycle, JSON,
jobs and lineage checks run at the pinned new head. The hierarchy fixture already
listed only surviving tables at base `ea6a4e6`, so it needed no change.

Four new PostgreSQL 16 testcontainer cases prove empty/populated upgrades, every dropped
object, rejection of both Raw lineage endpoint kinds, preservation of hierarchy,
principals, RBAC seeds and a surviving lineage edge, explicit-range offline CLI SQL,
and the exact downgrade refusal. Tests used only disposable test-owned containers;
the owner's stack and database were not started, stopped, reset or migrated.

Implementation gate: `make lint` (14 import contracts, empty radon output), 899 unit,
15 contract, 12 integration, 914 combined unit/contract tests, `make docs`, and all
closing checks passed. Source hashes, source diff, coverage floor and duplication
baseline are unchanged. Duplication remains 76 clones / 26 groups, native score 70.
Unit covered/total statements stay 2,832/2,958 (95.74%; 899 tests before and after).
Combined covered/total statements stay 2,955/2,958 (99.90%). No surviving file gains
missing lines; the measured unit floor remains 95.74. Exact logs, JSON reports and
proofs: `/tmp/huron-m17-i1/`; report: `/tmp/huron-m17-i1/report.md`.

The task remains pending until independent verification passes.

### M1.7 independent completion

Verification attempt1 passed without findings: `/tmp/huron-m17-v1/report.md`.
Full static,899unit,15contract,12integration,914combined,docs and focused migration
checks passed. Changed Python files have100%coverage; source hashes and coverage
line sets are unchanged. All Milestone1 tasks are complete. Fresh M2.1 baseline
reports are `/tmp/huron-m21-before.json` and `/tmp/huron-m21-before-contract.json`.

### M2.1 implementation evidence — 2026-10-25 (verification pending)

Renamed the legacy `core/catalog` package to `core/hierarchy` and its private
`collections.py` to `listings.py`; rewrote all specified importers and symbol names,
without aliases or compatibility modules. Test filenames and behavior are unchanged.
The fourteen import contracts now name hierarchy; the credential-library contract
also covers `jwt`, `cryptography`, Metastore and Rawstore as specified. Updated the
assigned current-source links, repository layout, conventions and roadmap paths;
removed the obsolete Raw ownership link and clause from `catalog-search.html`.

The duplication baseline has exactly three reviewed path substitutions: the size-3
`core/catalog/_impl/creation.py` entry now names `core/hierarchy/_impl/creation.py`,
and both size-3 `core/catalog/types.py` entries now name `core/hierarchy/types.py`.
All files and sizes otherwise remain identical to `12f579b`; these are pure re-paths,
exempt from the cap. G1 adds zero capped signatures and its running total remains
zero. The guard reports unchanged 76 clones, 26 groups and native score 70/100.

Implementation gates pass: `make lint` (14 kept, 0 broken; empty radon findings),
899 unit, 15 contract, 12 integration and 914 combined unit/contract tests, and
`make docs`. All exact closing scans are empty, `core/catalog` is absent, and
`git diff --check` passes. No frontend files changed. Validation used only disposable
test-owned containers; no owner stack actions occurred. Validation-scoped caffeinate
exited with the gate runner.

Source equivalence evidence compares all 99 Python modules against `12f579b`:
ASTs are identical after only the specified renames, docstrings and import/export
sorting. Coverage remains 2,832/2,958 unit (95.74%) and 2,955/2,958 combined (99.90%);
the floor stays 95.74. Mapped per-file counts and missing-line content are identical.
The touched `metastore/hierarchy.py:661` retains its existing defensive failure if a
locked idempotency claim vanishes mid-transaction; independent verification must
explicitly assess this uncovered line. Every other touched module is fully covered
at the appropriate unit/contract tier.

Twenty isolated planted-import cases reject the expected contracts. All twelve
new credential owner/library combinations break exactly the credential contract,
and hierarchy's private-implementation violation breaks exactly its contract.
The task's phrase "each breaking exactly its contract" needs qualification for two
pre-existing schema-bridge cases: the adapter bridge breaks the layering, hierarchy
and domain-to-adapter contracts, and the FastAPI bridge breaks the hierarchy and
framework contracts. A separate baseline run proves all eight original violation
sets are unchanged after name normalization. No test assertions or contracts were
weakened; independent verification must assess this literal acceptance discrepancy.

Exact commands, exit statuses, full logs, before/after source hashes, AST and coverage
proofs and planted-import results are in `/tmp/huron-m21-i1/`; implementation report:
`/tmp/huron-m21-i1/report.md`. The original baseline reports remain untouched at
`/tmp/huron-m21-before.json` and `/tmp/huron-m21-before-contract.json`.
The task remains pending until independent verification passes.

### M2.1 independent completion

Verification attempt1 passed: `/tmp/huron-m21-v1/report.md`. Full gates and
99-module normalized AST/coverage equivalence pass. Exactly three duplication
path substitutions were verified. The pre-existing overlapping import violations
and unchanged defensive claim branch were independently assessed without weakening
contracts. Fresh M2.2 baseline JSONs are `/tmp/huron-m22-before.json` and
`/tmp/huron-m22-before-contract.json`.

### M2.2 independent completion

Verification attempt1 passed without findings: `/tmp/huron-m22-v1/report.md`.
All gates pass; moved helpers are byte-identical, normalized source ASTs and
coverage unchanged, all touched source fully covered. Milestones1 and2 are now
complete. Fresh M3.1 before reports are `/tmp/huron-m31-before.json` and
`/tmp/huron-m31-before-contract.json`.
