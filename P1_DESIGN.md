# P1 — Foundations: design record

Phase 0 (this section and `## Roadmap Drift`) is a documentation grill only: it records where the
project's own documents describe P1 — Foundations differently from what the code does. Nothing
below proposes a design; the design and the implementation plan build on top of it.

## Authority order

- **Authoritative:** `design/` (per `CLAUDE.md`). `design/roadmap.html` is the living roadmap and
  carries *status* as well as intent — every `done` / `partial` / `todo` tag is a claim about this
  checkout. The P1 row goes one step further and delegates: "Where this row and the code disagree,
  the code wins." That sentence is honored below — code wins on *status*; `design/` still wins on
  *intent*.
- **Derived:** `docs/backend-design.md` (explicitly defers to the roadmap, `docs/backend-design.md:50`),
  `migrations/schema.sql` (a hand-maintained map with a checked `Reflects:` stamp).
- **Sibling design records with their own grills:** `API_DESIGN.md` § "Roadmap Drift" (ten
  findings against the API tier, 2026-08-31) and `SCHEMA_DESIGN.md` / `schema_audit.md` (F1–F8).
  Findings already recorded there are cited, not repeated.
- **Checkout state:** the grill is against the **working tree**, which carries 48 modified files
  and 24 untracked files of uncommitted API-tier work (`git status`, 2026-09-01). Two findings
  below are only true of the working tree; they are marked.

Verification levels used: **L1** ran it (migrations applied to a disposable `postgres:16`; the
app driven through `TestClient`; `lint-imports`; `scripts/check_schema_map.py`), **L2** read the
code that would run, **L3** read a generated artifact (the live route table / OpenAPI schema),
**L4** read another document.

## Roadmap Drift

Ranked by consequence for a P1 design.

### Drift 1 — the hierarchy has no persistent store; every `done` P1 HTTP deliverable is in-process only

**Claim.** `design/roadmap.html` §2, P1 row: deliverables include "migrations (hierarchy,
role_bindings, api_keys, audit, outbox)" and "org/project/dataset CRUD with generation documents
**done**; release tags **done**"; gate: "Create org → project → dataset via HTTP".
**Reality.** (L2) `src/huron/service/api/repository.py:82-86` — `HierarchyRepository` holds
`organizations`, `projects`, `datasets`, `revisions` and `releases` as `dict`s; no code path reads
or writes the `organizations` / `projects` / `datasets` / `dataset_revisions` / `releases` tables
`0001` creates. `src/huron/service/api/app.py:40-44` says so in a docstring: "The
organization/project/dataset hierarchy stays in-memory until it gets its own store, so this is only
safe once the rows those foreign keys target (organizations, projects) are real Postgres rows".
`tests/contract/test_catalog_store.py:12-15` and `tests/contract/test_rbac_store.py:24-27` insert
hierarchy rows by raw SQL "standing in for the (still in-memory) catalog". (L1) The probe created
two orgs, two projects and two datasets over HTTP with `store_backend="memory"`; the documents landed
on disk at the documented paths, and nothing reached a database. With `store_backend="postgres"`
(`settings.py:54`), `service_accounts.organization_id REFERENCES organizations(id)`
(`0002_rbac.py:45`) and `api_keys.project_id REFERENCES projects(id)` (`0001_foundations.py:172`)
target rows the API never writes, so an organization created over HTTP cannot own a service account
or scope an API key in that mode.
**Class.** Claimed done, not done — for the only configuration that survives a restart. Roadmap §1
does say `metastore/` is "planned, not built", so the two statements are individually true; the P1
`done` tags and the gate sentence are what mislead.
**Consequence.** A P1 plan that treats hierarchy CRUD as finished ships a catalog that forgets every
organization on restart and cannot bind service accounts or API keys in Postgres mode. The
hierarchy store is P1's largest open deliverable and the row does not name it.

### Drift 2 — the P1 gate's authorization clause fails: "discovery gating" is a function with zero callers

**Claim.** P1 row: "`RoleBindingAuthorizer` with discovery gating"; gate: "a principal scoped to
project A gets full-size pages with zero rows from B and no evidence of B in counts or cursors".
**Reality.** (L2) `src/huron/pkg/rbac/__init__.py:131` defines
`RoleBindingAuthorizer.visible_project_ids`; `grep -rn visible_project_ids src` finds its only
other mention in a Protocol signature (`pkg/catalog/ports.py:48`). No service code calls it.
`routes/v1/endpoints/organizations.py:53-59`, `projects.py:52-58`, `datasets.py:85-91`: the three
`list_*` operations and the three `get_*` operations declare no authorization dependency and pass
the unfiltered repository result to `paginate()`. (L1) A principal `user:nobody` with no bindings
at all received `200` with every organization, every project of the other organization, every
dataset of the other project, and `200` on direct `GET /datasets/{id}` for the other dataset.
**Class.** Claimed done, not done. The pure authorizer is delivered; the gating it is named for is
not wired to anything. (The row separately tags browse `todo` and assigns "the filter-then-paginate
rule" to T0 milestone 3 — that half is honest.)
**Consequence.** A design that reads "with discovery gating" as shipped builds listings on a
visibility layer that does not exist; the P1 gate's most important clause is currently false.

### Drift 3 — the roadmap says the API clean sweep is untouched; thirteen of its tasks have landed *(working tree)*

**Claim.** §2, "API tier clean sweep" row: "**Nothing here has been implemented — every task is
`Status: pending`.**" P1 row: "`page()` in `routes/v1/common.py` returns `next_cursor: null`
unconditionally, so no cursor is ever issued". §2 preamble: "landing work updates its tag in the
same change".
**Reality.** (L2/L3, working tree) `API_IMPLEMENTATION_PLAN.md` carries 13 `**Status: done**` and 14
`**Status: pending**` (`grep -c`), while its own line 2542 still asserts "23 `**Status: pending**`,
zero non-`pending` statuses". `routes/v1/common.py` is deleted (`git status`: `D`);
`routes/v1/pagination.py` exists and issues cursors — (L1) `GET /api/v1/organizations?limit=1`
returned `next_cursor: "v1:b3JnLWEf…"`, and `tests/unit/test_api_catalog_hierarchy.py:153,236,346`
walk the cursor. (L1) Anonymous `GET /api/v1/organizations` now answers `401 INVALID_CREDENTIAL`,
which `API_DESIGN.md` Drift 1 recorded as *not* the case on 2026-08-31. `design/roadmap.html` has
no working-tree modification and was last committed 2026-08-31 (`9b293c1`).
**Class.** Documentation is wrong (stale against uncommitted work). Both the roadmap and the plan's
own self-check line are false for this checkout.
**Consequence.** A P1 design reading the roadmap would re-plan keyset cursors and the anonymous
guard, and would cite a file that no longer exists. Whoever commits the sweep work must update the
roadmap row, the P1 row's browse paragraph, and `API_IMPLEMENTATION_PLAN.md:2542` in that change.

### Drift 4 — `0008_schema_conformance` is tagged `todo`; it is committed, applied, and round-trips

**Claim.** §2, "Schema conformance — `0008`" row tagged **`todo`**; `SCHEMA_IMPLEMENTATION_PLAN.md`
milestones M1–M10 all `Status: pending` (27 occurrences, zero `done`).
**Reality.** (L1) `migrations/versions/0008_schema_conformance.py` exists (553 lines), committed in
`da03ece` "Add 0008_schema_conformance migration and close 10-milestone gap"; `alembic heads` →
`0008_schema_conformance (head)`. Against a fresh `postgres:16`: `upgrade head` succeeded;
`audit_events` is `relkind r` (plain table) with `audit_events_pkey` (`contype p`) and
`audit_events_created_at` on `(created_at, id)`, plus `audit_events_kind_format` and
`audit_events_payload_is_an_object` — exactly what the P1 row's "Withdrawn" paragraph describes; a
second INSERT with the same `id` was refused (`duplicate key value violates unique constraint
"audit_events_pkey"`); `downgrade base` → `upgrade head` round-tripped. (L1)
`scripts/check_schema_map.py` exits 0 and `migrations/schema.sql:10` reads
`-- Reflects: 0008_schema_conformance`. `da03ece` touched no file under `design/`.
**Class.** Documentation is wrong — the inverse of "claimed done": claimed todo, actually done.
**Consequence.** A P1 plan would re-schedule ten milestones of finished work. The row should read
`done`, and the schema plan's statuses should be flipped, by the owner of that change.

### Drift 5 — no CI exists; "all five are checked in CI" and P0's CI stages are unbacked

**Claim.** §1: "Five import-linter contracts hold this in place, and **all five are checked in
CI**". §2, P0 (tagged **`done`**): "CI with lint → unit → contract → integration stages"; gate:
"Green CI on the empty tree". P1 gate: "import-linter green".
**Reality.** (L1) No `.github/`, `.gitlab-ci.yml`, `.circleci/`, `.drone.yml`, `.woodpecker*`, or
`.forgejo/` anywhere in the tree (`ls -a`, `find`). The contracts do exist and pass locally:
`uv run lint-imports` → "Contracts: 5 kept, 0 broken"; `make lint` runs it (`Makefile:39`). §4 also
claims "FIPS smoke and the OpenAPI-contract check run from P0 onward" — nothing runs either.
**Class.** Claimed done, not done (P0), and documentation is wrong (§1).
**Consequence.** Every "green in CI" gate in the roadmap, P1's included, is a local convention
nobody enforces. The P1 plan's definition of done must either add the CI or stop citing it.

### Drift 6 — release tags are `done`, but no HTTP path can create the revision a tag needs

**Claim.** P1 row: "release tags **done** — both verified route by route against the built route
table and against API §2"; gate: "a release tag resolves to one revision and a second write of the
same tag is `409 TAG_EXISTS`".
**Reality.** (L3) `POST/GET /api/v1/datasets/{id}/releases` and `GET …/releases/{tag}` are in the
live route table. (L2) `create_release` looks the revision up in `self.revisions`
(`repository.py:277`), which is populated only by `register_revision` (`repository.py:306`);
`grep -rn register_revision src tests` finds callers exclusively in tests
(`test_api_catalog_hierarchy.py:443` — "called on the repository directly - there is no HTTP
route"). (L1) Over HTTP, creating a release on a freshly created dataset answers `404 NOT_FOUND`.
`TAG_EXISTS` and the one-revision resolution are asserted only against test-seeded revisions
(`test_repository_hierarchy.py:279-335`).
**Class.** Claimed done, not done — the routes and the write-once tag file are real; the gate is
unreachable end to end until P2 milestone 8 lands ingest.
**Consequence.** Modest and known: P2 owns the missing half. The finding matters because the P1 gate
sentence cannot be executed as written, and a P1 plan should not promise it.

### Drift 7 — "with their property tests": Hypothesis is declared and never used

**Claim.** §5, First moves: "Build the pure core first: `pkg/catalog/ids.py`, `pkg/catalog/paths.py`,
`pkg/catalog/manifest.py` **with their property tests**".
**Reality.** (L2) `hypothesis` is in `pyproject.toml:43`; `grep -rln hypothesis tests` finds no
test file. `ids.py`'s `uuid7()` has no direct unit test (its only test references are as a
fixture-ID generator); the manifest rejection matrix is covered by seven example-based assertions in
`tests/unit/test_catalog_paths.py`, with no property over the NFC/case-fold collision rule or the
JCS integer bound.
**Class.** Claimed done, not done (property tests). The modules themselves are current — see below.
**Consequence.** The invariants the roadmap calls "everything else leans on them" are pinned by
examples only. Low urgency; worth a task in the plan rather than a design change.

### Drift 8 — the independence contracts cover four packages and one service, not "eleven" and "twelve"

**Claim.** §1: "an *independence* contract across the eleven packages; an *independence* contract
across the twelve services".
**Reality.** (L2) `pyproject.toml` `[[tool.importlinter.contracts]]`: `modules = ["huron.pkg.auth",
"huron.pkg.catalog", "huron.pkg.rawstore", "huron.pkg.rbac"]` and `modules = ["huron.service.api"]`,
with the comment "re-add each deployable here as it gains real code".
**Class.** Documentation is wrong (the sentence describes the intended list as if enforced).
**Consequence.** A new package — the `metastore/` P1 needs, above all — is *not* independence-checked
until someone adds it to the list; the plan must include that edit.

### Drift 9 — `catalog/ports.py` does not declare `ObjectRepoStore`

**Claim.** §1, `catalog/`: "in `ports.py`, the Protocols it depends on: RawStore, ObjectRepoStore,
Metastore, SearchProjection, CredentialVendor, JobDispatcher, PrincipalResolver, Clock".
**Reality.** (L2) `src/huron/pkg/catalog/ports.py` defines `Clock`, `RawStore`, `Metastore`,
`SearchProjection`, `ScopedCredentials`, `CredentialVendor`, `JobDispatcher`, `Principal`,
`PrincipalResolver` — no `ObjectRepoStore`.
**Class.** Documentation is wrong. Cosmetic for P1 (object storage is P6).

### Drift 10 — API §2 names a role that does not exist

**Claim.** `design/api.html` §2: "`POST/GET /organizations` — **platform_admin** creates".
**Reality.** (L1) `GET /api/v1/roles` → `reader, developer, project_admin, organization_admin,
platform_owner`; (L2) `pkg/rbac/roles.py` and `0006_role_simplification.py` know no
`platform_admin`; `design/rbac.html` and `design/roadmap.html` contain zero occurrences of it.
`organizations.py:31` guards creation with `require_system("organization.create")`.
**Class.** Documentation is wrong. Cosmetic.

### Already recorded elsewhere — not repeated

`API_DESIGN.md` § "Roadmap Drift" Drifts 1, 4, 5, 6, 8, 9 (anonymous `/api/v1`, binding `GET` at
two of four scopes, missing error-code bijection test and `PATH_RULE_VIOLATION` row, `/readyz`
checking one dependency, `/auth/session` roles, `/metrics`) all still stand on the working tree
except Drift 1, which the sweep has since fixed (see Drift 3 above). `API_DESIGN.md` Drift 10 (P1
had no per-item status) has been fixed in the roadmap and is closed.

## Checked, no drift found

- **`catalog/paths.py` — construction, parsing, slug limits.** `ORG_PROJECT_SLUG_MAX = 62`,
  `DATASET_SLUG_MAX = 80` (`paths.py:17-18`); `parse_revision_dir` inverts construction. (L1) The
  probe's on-disk layout matches `design/layer-raw.html` §2 byte for byte:
  `organization/{slug}--{hex}/CURRENT.json`, `…/generations/000001.json`, `…/project/{slug}--{hex}/…`,
  `…/dataset/{slug}--{hex}/…`; release tags go to `…/releases/{tag}.json` (`paths.py:130-138`).
- **Generation documents and `CURRENT.json`.** `PosixRawStore.write_generation` writes the numbered
  generation `O_EXCL` and atomically replaces `CURRENT.json` (`store.py:88-97`) — the protocol
  `layer-raw.html:350` specifies.
- **Slug immutability → `409 SLUG_IMMUTABLE`.** `tests/unit/test_api_rbac.py:299-309` pins it for
  datasets and projects with `If-Match` present. (A `PATCH` without `If-Match` is `422`, which is
  the precondition contract, not a slug bug.)
- **Manifest / JCS rejection matrix.** Every rule in `layer-raw.html` "Path rules" has a code:
  `PATH_OUTSIDE_PAYLOAD`, `PATH_NOT_NFC`, `PATH_TOO_LONG` (1024 bytes), `PATH_TRAVERSAL` (empty /
  `.` / `..` segments, which also covers trailing slashes), `PATH_CONTROL_CHARS`, `PATH_SEPARATOR`;
  NFC-or-case-fold collisions → `PathCollision` (`manifest.py:93-146`); `EmptyRevision`,
  `TooManyFiles`, `FileTooLarge`, `RevisionTooLarge`; integers asserted below 2⁵³ (`manifest.py:68`).
- **UUIDv7.** `ids.py:8-16` lays out the RFC 9562 bits (48-bit ms timestamp, version 7, variant
  `10`) by hand.
- **`PosixRawStore`** exists in `pkg/rawstore/store.py:18` with `commit.py` holding the fsync /
  same-filesystem / atomic-rename primitives.
- **Migrations (hierarchy, role_bindings, api_keys, audit, outbox).** All seven named tables exist
  after `upgrade head` (L1 count = 7). `0001_foundations.py:188-189` matches the P1 row's account of
  the withdrawn partitioning (`PARTITION BY RANGE (created_at)` + one `DEFAULT` child).
- **Resolvers.** `ApiKeyResolver` (`auth/apikeys.py:92`), `OidcResolver` (`auth/oidc.py:26`),
  `DevHeaderResolver` (`auth/dev.py:14`, refuses non-development at `:17`); all seven `auth/` modules
  §1 lists are present; the four packages §1 says exist are the four that exist.
- **Import-linter.** Five contracts, all `KEPT` locally.
- **Route table vs API §2.** Every §2 hierarchy route is live except `POST /datasets/{id}:retire`
  and `POST …/releases/{tag}:withdraw`, which T1 milestones 4 and 7 own as `todo` — not drift.
- **`openapi/v1.json` and client cores.** Absent, tagged `todo` — not drift.
- **Audit / outbox writers.** `grep -rn "audit_events\|outbox_events" src` → zero hits. The P1 row
  claims only the migrations; T0 milestone 3 owns the writers as `todo` — not drift, but a P1
  design should know that no row has ever been written to either table.
- **`docs/backend-design.md`** defers to the roadmap as the roadmap says it does.
- **P0 settings refusals** (dev headers outside development) — implemented at `auth/dev.py:17`.

---

## Current State

What is there, structurally, as of the working tree on 2026-09-01. Facts only; the design starts at
`## Design Tasks`. Read fully: `migrations/versions/0001`, `0003`, `0004`, `0008`;
`pkg/catalog/{models,ports,paths,manifest,ids,lifecycle,layers}.py`; `pkg/rbac/__init__.py`,
`pkg/rbac/roles.py`; `pkg/rawstore/store.py`; `service/api/{repository,records,ports,runtime,app,
settings,authorization,memory_rbac}.py`; `routes/v1/pagination.py`; the three hierarchy endpoint
modules; `tests/unit/test_execution_model.py`; `API_DESIGN.md` Designs 1, 3, 6, 10 and the answered
decision register; `SCHEMA_DESIGN.md` § "Notes carried forward". Skimmed: `postgres_rbac.py` (as the
house pattern for an asyncpg store), `tests/contract/test_catalog_store.py` (as the house pattern for
a migrated-database contract test). Skipped: `web/`, `uv.lock`, the `design/*.html` layer documents
beyond the lines cited, `RBAC_*`, `CONTROL_PLANE_PLAN.md`, `schema_audit.md`.

### The P1 surface, module by module

| Module | Exists | State |
|---|---|---|
| `pkg/catalog/paths.py`, `manifest.py`, `ids.py` | yes | Complete for P1 (grill: current). Example-tested only; no property tests. |
| `pkg/catalog/models.py` | yes | Four frozen values: `EntityRef`, `RevisionRef`, `RevisionRecord`, `OutboxEvent`. **The hierarchy records — `Organization`, `Project`, `Dataset`, `Release`, `RevisionSeed` — do not live here.** They are `service/api/records.py`, mutable `slots` dataclasses, with `jsonable()` producing the generation document. |
| `pkg/catalog/ports.py` | yes | `Metastore` (P2's `begin_ingest` / `record_revision` / `resolve_tag`) has **no implementation**; nothing in `src/` references it. `RawStore` is satisfied by `PosixRawStore`. |
| `pkg/rawstore/store.py` | yes | `write_once` (`O_EXCL` + `fsync`), `atomic_replace` (tmp + `rename`), `write_generation` (`write_once` the numbered file, `atomic_replace` `CURRENT.json`), `write_tag_once`. |
| `pkg/rbac/__init__.py` | yes | `RoleBindingAuthorizer.decide` (used everywhere), `.visible_project_ids` (**zero callers in `src/`**), `ProjectVisibility`, `Classification`. All five roles carry `dataset.discover`. |
| `pkg/metastore/` | **no** | Roadmap §1 says "planned, not built". |
| `service/api/repository.py` | yes | `HierarchyRepository`: five process `dict`s under one `threading.RLock`; idempotency as a `dict[key -> (fingerprint, result)]`, keyed by key alone (the DDL keys `idempotency_records` by `(principal, key)`); sync writes, sync point reads, sync list reads returning whole ordered sequences; RBAC delegated to an injected `RbacStore`; four auth stores hung off it as attributes. Writes the generation/tag documents before mutating the dict. |
| `service/api/ports.py` | yes | `RbacStore`, `ApiKeyWriter` — consumer-owned Protocols; both backends conform structurally. |
| `service/api/memory_rbac.py`, `postgres_rbac.py`, `postgres_auth.py` | yes | The port-pair pattern: one in-process reference store, one asyncpg store, contract-tested against the migrated database. |
| `service/api/settings.py` | yes | `store_backend: Literal["memory","postgres"] = "memory"`; `"postgres"` wires RBAC/auth to asyncpg and leaves the hierarchy in memory — the docstring itself calls this unsafe. |
| `service/api/runtime.py` | yes | `ApiRuntime(settings, repository, oidc_resolver, oidc_client)`; `Repository`/`Settings` dependency aliases. |
| `routes/v1/pagination.py` | yes | `Page[T]`, `encode_cursor`/`decode_cursor` (`v1:` + base64url of `\x1f`-joined key), `paginate()` windows an in-memory sequence; its docstring already says `limit`/`after` descend into the store "when the hierarchy gets a persistent store". |
| Hierarchy endpoints | yes | `create_*`/`patch_*`/`create_release` are `def` (threadpool, per Design 1); `list_*`/`get_*` are `async def` with **no authorization dependency at all**. |
| `tests/unit/test_execution_model.py` | yes | Pins the 47-operation `def`/`async def` table, and two AST invariants on `repository.py`: no `await` under `self._lock`, list queries never take the lock. Both invariants are about the in-memory design and die with it. |
| `migrations/` | 0001–0008 | Hierarchy tables complete for P1's needs; no migration is required by this design (see Design 1, "Column mapping"). |
| `idempotency_records` | table exists | **No writer, no reader.** |
| `audit_events`, `outbox_events` | tables exist | **No writer, no reader** (T0 milestone 3 and P4 own them). |
| `dataset_revisions` | table exists | No writer in `src/`; contract tests insert rows by SQL. |
| CI | **none** | `make lint` / `make test` exist; nothing runs them. |

### Conventions the design follows

- **Consumer-owned Protocols, structural conformance, one reference implementation + one asyncpg
  implementation per port**, proven equal by `tests/contract/`. (`pkg/catalog/ports.py`,
  `service/api/ports.py`, `memory_rbac.py` ↔ `postgres_rbac.py`.)
- **asyncpg with hand-written SQL, `$n` parameters, row → record mapping functions, one named
  `DomainError` per `asyncpg` exception class** (`postgres_rbac.py:34-67`, `:117-122`).
- **Timestamps and ids are application-supplied** (`SCHEMA_DESIGN.md` § "Notes carried forward":
  no `DEFAULT now()`, no `gen_random_uuid()`); ids are `uuid7()` and are baked into storage paths.
- **Execution model** (Design 1, shipped in M1.1): `async def` iff the body awaits; blocking calls
  inside an `async def` go through `await asyncify(...)`.
- **Ordering** (Design 10, D-17): every `ORDER BY` over text is `COLLATE "C"`, because the cursor is
  compared in Python. Receipt 1 below re-proves it for slugs specifically.
- **Errors**: Design 6 (M8.1, pending) gives the tier `service/api/errors.py` with `SlugExists`,
  `ClassificationUnknown`, etc.; this design uses those names.
- **Layout**: Design 10 (M11.2, pending) moves the five adapters into `service/api/stores/`,
  organized by port, with `stores/ports.py` and `stores/rows.py`.
- **Migrated-database contract tests** use `testcontainers` `PostgresContainer("postgres:16")`,
  run Alembic to head, insert fixture rows by SQL, and pin every constraint with a write that
  must fail and one that must succeed (`tests/contract/test_catalog_store.py:150-200`).
- **Generation documents**: `jsonable(record)` + `"schema": "urn:huron:generation:1"`, JCS bytes,
  written to `generations/{n:06d}.json` with `CURRENT.json` pointing at it (`repository.py:518`).

### Data flow today — `POST /api/v1/organizations`

```mermaid
sequenceDiagram
    participant H as handler (def, threadpool)
    participant R as HierarchyRepository
    participant D as process dicts
    participant F as PosixRawStore (NFS)
    H->>R: create_organization(slug, ..., idempotency_key)
    R->>R: acquire RLock; replay check (key only)
    R->>D: any(slug == item.slug)  -- duplicate → DomainError 400
    R->>F: write_generation(): O_EXCL 000001.json, fsync, replace CURRENT.json
    R->>D: organizations[id] = item   -- "visible" from here
    R-->>H: Organization
    Note over D: restart empties every dict; the row tables are never touched
```

### Emptiness findings that shape the design

1. The hierarchy tables have a schema, constraints, and a 0008 contract suite, and no writer.
2. `visible_project_ids` is a complete, tested pure function with no caller.
3. `idempotency_records` has a `(principal, key)` primary key the in-memory replay does not honor.
4. `catalog.ports.Metastore.record_revision(RevisionRecord, ...)` cannot be implemented against
   `dataset_revisions` as shipped: the table requires `metadata_sha256 NOT NULL` and
   `RevisionRecord` has no such field. Not P1's to fix — recorded for P2 (Open question 9).

## Design Tasks

| # | Task | One decision? | Settled from | Owns |
|---|---|---|---|---|
| D1 | The persistent hierarchy store: port, two backends, transaction + document ordering, keyset push-down, idempotency | One decision (how a hierarchy write becomes durable) | code + DDL + Designs 1/3/10 | the store port, `HierarchyRepository`'s new shape, `pagination.page` |
| D2 | Visibility: computing `Visibility` from bindings, applying it in SQL before `LIMIT`, and 404-for-undiscoverable | One decision (what "discoverable" means per level) | `design/rbac.html`, `pkg/rbac` | the `Visibility` value, the SQL predicates, the request dependency; **touches D1's queries — D1 owns the query signatures, D2 owns the predicate text** |
| D3 | Composition root: Postgres-only wiring, auth stores onto `ApiRuntime`, `store_backend` deleted | One decision | Design 2/3 OQ3 | `app.py`, `runtime.py`, `settings.py` |
| D4 | Verification debts P1 carries: property tests for the pure core, CI, the documentation write-back | Three small independent items | grill | `tests/`, `.github/workflows/`, `design/roadmap.html` and the two plans' status lines |

D1 and D2 are designed together below because the SQL cannot be written twice; the ownership split
is stated in each contract. Sizing: D1+D2 is one implementation milestone with several tasks; D3
and D4 are one task each.

## Design 1 — The persistent hierarchy store

### Target design

#### Layout

Under Design 10's `stores/` package (M11.2), two new modules; nothing else moves.

```text
src/huron/service/api/stores/
├── ports.py         + HierarchyStore, HierarchyWriter, Visibility, Window, IdempotencyClaim, Replay
├── hierarchy.py     InMemoryHierarchyStore, PostgresHierarchyStore   (one port, both backends, adjacent)
└── rows.py          + organization, project, dataset, release, revision_ref  (asyncpg.Record -> record)
```

`records.py` keeps `Organization`, `Project`, `Dataset`, `Release`, `RevisionSeed` unchanged
(Open question 1 records the `pkg/metastore` alternative and why it is not taken now).

#### `stores/ports.py` — the hierarchy port

```python
@dataclass(frozen=True, slots=True)
class Visibility:
    """What one principal may discover, as three id sets (Design 2 computes it).

    ``unrestricted`` short-circuits every predicate; it is true only for a
    principal holding ``dataset.discover`` at SYSTEM scope.
    """
    organization_ids: frozenset[UUID] = frozenset()
    project_ids: frozenset[UUID] = frozenset()
    dataset_ids: frozenset[UUID] = frozenset()
    unrestricted: bool = False

    ALL: ClassVar[Visibility]          # Visibility(unrestricted=True)


@dataclass(frozen=True, slots=True)
class Window[ItemT]:
    """``limit`` items after a keyset position, and whether more follow."""
    items: list[ItemT]
    has_more: bool


@dataclass(frozen=True, slots=True)
class IdempotencyClaim:
    principal: str          # the acting principal's subject, e.g. "user:alice"
    key: str                # the Idempotency-Key header
    request_sha256: str     # hex digest over the operation name and its arguments


@dataclass(frozen=True, slots=True)
class Replay:
    kind: Literal["organization", "project", "dataset", "release"]
    resource_id: UUID


class HierarchyWriter(Protocol):
    """One transaction's write surface; obtained from ``HierarchyStore.transaction()``.

    Every method runs inside the same transaction; nothing is visible to a
    reader until the ``async with`` block exits without an exception.
    """
    async def claim(self, claim: IdempotencyClaim) -> Replay | None: ...
    async def remember(self, claim: IdempotencyClaim, replay: Replay) -> None: ...
    async def insert_organization(self, item: Organization) -> None: ...
    async def insert_project(self, item: Project) -> None: ...
    async def insert_dataset(self, item: Dataset, *, data_classification: str) -> None: ...
    async def insert_release(self, item: Release) -> None: ...
    async def update_organization(self, item: Organization, *, expected_version: int) -> None: ...
    async def update_project(self, item: Project, *, expected_version: int) -> None: ...
    async def update_dataset(self, item: Dataset, *, expected_version: int) -> None: ...


class HierarchyStore(Protocol):
    def transaction(self) -> AbstractAsyncContextManager[HierarchyWriter]: ...

    # point reads: ResourceNotFound when absent OR not visible (Design 2)
    async def organization(self, organization_id: UUID, visibility: Visibility) -> Organization: ...
    async def project(self, project_id: UUID, visibility: Visibility) -> Project: ...
    async def dataset(self, dataset_id: UUID, visibility: Visibility) -> Dataset: ...
    async def release(self, dataset_id: UUID, tag: str, visibility: Visibility) -> Release: ...
    async def revision_ref(self, dataset_id: UUID, revision_number: int) -> RevisionRef: ...

    # windows: ordered by the cursor key, filtered by visibility BEFORE the window
    async def organizations(
        self, visibility: Visibility, *, limit: int, after: tuple[str, UUID] | None
    ) -> Window[Organization]: ...
    async def projects(
        self, organization_id: UUID, visibility: Visibility, *, limit: int, after: tuple[str, UUID] | None
    ) -> Window[Project]: ...
    async def datasets(
        self, project_id: UUID, visibility: Visibility, *, limit: int, after: tuple[str, UUID] | None
    ) -> Window[Dataset]: ...
    async def releases(
        self, dataset_id: UUID, visibility: Visibility, *, limit: int, after: tuple[str] | None
    ) -> Window[Release]: ...

    # inputs to Design 2's visibility computation
    async def project_visibilities(self) -> list[ProjectVisibility]: ...
    async def dataset_parents(self, dataset_ids: frozenset[UUID]) -> dict[UUID, UUID]: ...
```

`RevisionRef` is `huron.pkg.catalog.models.RevisionRef` (`id, dataset_id, number, manifest_sha256`)
— the service tier's `RevisionSeed` is deleted in favor of it (same four fields).

#### The write mechanism — row, then document, then commit

```mermaid
sequenceDiagram
    participant H as handler (async def)
    participant R as HierarchyRepository
    participant S as HierarchyWriter (tx)
    participant P as PostgreSQL
    participant F as PosixRawStore (NFS, via asyncify)
    H->>R: await create_organization(..., claim)
    R->>S: async with store.transaction()
    S->>P: BEGIN
    R->>S: await claim(claim)
    S->>P: INSERT idempotency_records ... ON CONFLICT DO NOTHING RETURNING
    alt conflict, same request_sha256
        S-->>R: Replay → re-read resource, return it (no new row, no new document)
    else conflict, different request_sha256
        S-->>R: IdempotencyKeyReused (409)
    end
    R->>S: await insert_organization(item)
    S->>P: INSERT organizations ...  -- UniqueViolation → SlugExists (409), nothing on disk
    R->>F: await asyncify(write_generation)(dir, 1, bytes)  -- 000001.json + CURRENT.json, fsync
    R->>S: await remember(claim, Replay("organization", id))
    S->>P: UPDATE idempotency_records SET status_code=201, response={"kind","id"}
    S->>P: COMMIT   -- the durability point; the row becomes visible here
    Note over F,P: crash before COMMIT leaves a document with no row: an orphan the P3 reconciler imports or sweeps, never a row without its document
```

The order is chosen so the cheap refusals (`SlugExists`, `IdempotencyKeyReused`,
`PreconditionFailed`) happen before any byte touches NFS, and so that a committed row always has
its document. The transaction holds a row lock across one NFS `fsync`; at P1's write rates that is
the correct trade and it is stated as a contract below so a later author does not "optimize" the
document write out of the transaction.

#### `PostgresHierarchyStore` — the SQL

Every text `ORDER BY` and every keyset comparison is `COLLATE "C"` (Receipt 1). Windows fetch
`limit + 1` rows and report `has_more = len(rows) > limit`, returning the first `limit`.

```sql
-- organizations(visibility, limit, after)
SELECT id, slug, title, description, generation, version, created_at
FROM organizations o
WHERE ($1::boolean                                             -- unrestricted
       OR o.id = ANY($2::uuid[])                               -- organization_ids
       OR EXISTS (SELECT 1 FROM projects p
                  WHERE p.organization_id = o.id AND p.id = ANY($3::uuid[]))
       OR EXISTS (SELECT 1 FROM datasets d JOIN projects p ON p.id = d.project_id
                  WHERE p.organization_id = o.id AND d.id = ANY($4::uuid[])))
  AND ($5::text IS NULL OR (o.slug COLLATE "C", o.id) > ($5 COLLATE "C", $6::uuid))
ORDER BY o.slug COLLATE "C", o.id
LIMIT $7;                                                      -- limit + 1

-- projects(organization_id, visibility, limit, after)
--   the organization itself must be visible, checked first by organization(); then:
WHERE p.organization_id = $1
  AND ($2::boolean OR p.id = ANY($3::uuid[])
       OR EXISTS (SELECT 1 FROM datasets d WHERE d.project_id = p.id AND d.id = ANY($4::uuid[])))
  AND ($5::text IS NULL OR (p.slug COLLATE "C", p.id) > ($5 COLLATE "C", $6::uuid))
ORDER BY p.slug COLLATE "C", p.id LIMIT $7;

-- datasets(project_id, visibility, limit, after)
WHERE d.project_id = $1
  AND ($2::boolean OR d.project_id = ANY($3::uuid[]) OR d.id = ANY($4::uuid[]))
  AND ($5::text IS NULL OR (d.slug COLLATE "C", d.id) > ($5 COLLATE "C", $6::uuid))
ORDER BY d.slug COLLATE "C", d.id LIMIT $7;

-- releases(dataset_id, visibility, limit, after): dataset() is checked first; then
WHERE r.dataset_id = $1
  AND ($2::text IS NULL OR r.tag COLLATE "C" > $2 COLLATE "C")
ORDER BY r.tag COLLATE "C" LIMIT $3;

-- point reads apply the same predicate for their level with LIMIT 1; zero rows → ResourceNotFound
-- revision_ref(dataset_id, number)
SELECT id, dataset_id, revision_number, manifest_sha256 FROM dataset_revisions
WHERE dataset_id = $1 AND revision_number = $2;

-- writer
INSERT INTO organizations (id, slug, title, description, lifecycle_state, generation, version,
                           created_at, updated_at)
VALUES ($1, $2, $3, $4, 'ACTIVE', $5, $6, $7, $7);                -- UniqueViolation → SlugExists
INSERT INTO projects (id, organization_id, slug, title, description, classification_default,
                      lifecycle_state, generation, version, created_at, updated_at)
VALUES ($1, $2, $3, $4, $5, $6, 'ACTIVE', $7, $8, $9, $9);        -- UniqueViolation → SlugExists
INSERT INTO datasets (id, project_id, slug, title, description, profile_name, profile_version,
                      entry_layer, data_classification, lifecycle_state, generation, version,
                      created_at, updated_at)
VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $13);  -- UniqueViolation → SlugExists
INSERT INTO releases (id, dataset_id, tag, revision_id, title, created_by, created_at)
VALUES ($1, $2, $3, $4, $5, $6, $7);    -- UniqueViolation → TagExists; FK → ResourceNotFound

UPDATE organizations SET title = $2, description = $3, generation = $4, version = $5, updated_at = $6
WHERE id = $1 AND version = $7 RETURNING id;                   -- zero rows → PreconditionFailed
-- projects, datasets: same shape

-- idempotency
INSERT INTO idempotency_records (principal, key, request_sha256, status_code, response, created_at, expires_at)
VALUES ($1, $2, $3, 0, '{}'::jsonb, $4, $4 + interval '24 hours')
ON CONFLICT (principal, key) DO UPDATE
    SET request_sha256 = EXCLUDED.request_sha256, status_code = 0, response = '{}'::jsonb,
        created_at = EXCLUDED.created_at, expires_at = EXCLUDED.expires_at
    WHERE idempotency_records.expires_at <= EXCLUDED.created_at    -- take over an expired claim
RETURNING key;
-- no row returned → a live claim exists: SELECT request_sha256, response FOR UPDATE, compare;
-- equal → Replay(response.kind, response.id); different → IdempotencyKeyReused.
-- status_code = 0 with response '{}' means "claimed, not yet remembered": a concurrent duplicate
-- blocks on the row until the first transaction commits or rolls back (ON CONFLICT waits), then
-- sees either the remembered response or no row at all.
UPDATE idempotency_records SET status_code = 201, response = $3::jsonb
WHERE principal = $1 AND key = $2;                             -- response = {"kind": ..., "id": ...}
```

Column mapping the store owns, so the records and the API do not change:
`Project.data_classification` ↔ `projects.classification_default`; `datasets.data_classification`
is written from the parent project's `classification_default` at creation (API §2: "under
inherited policy") and is not exposed on `Dataset`; `updated_at` is written (`created_at` on
insert, the patch time on update) and not exposed. No migration.

Error mapping, following `postgres_rbac.py`: `asyncpg.UniqueViolationError` on the slug keys →
`SlugExists`; on `releases_dataset_id_tag_key` → `TagExists`; `asyncpg.ForeignKeyViolationError`
on `releases_revision_dataset_fk` → `ResourceNotFound` (cannot happen after `revision_ref`, kept as
the backstop). Every other `asyncpg` error propagates.

#### `InMemoryHierarchyStore`

Same port; five `dict`s and an idempotency `dict[(principal, key) -> (request_sha256, Replay | None,
expires_at)]`; `transaction()` acquires one `asyncio.Lock` and buffers writes in an undo log applied
on success, discarded on exception, so `SlugExists` is raised at `insert_*` time by checking the
live dicts plus the buffer. Windows are computed by `sorted(..., key=(slug, id))`, `bisect` past
`after`, slice `limit + 1`. It carries one method that is not on the port —
`register_revision(RevisionRef)` — the seed D-14 pinned, replacing `HierarchyRepository.register_revision`.
Visibility predicates are the three rules in Design 2, applied identically to the SQL.

#### `HierarchyRepository` after this change

```python
class HierarchyRepository:
    def __init__(
        self,
        raw_store: PosixRawStore,
        hierarchy: HierarchyStore,
        *,
        classification_vocabulary: tuple[str, ...],
        rbac_store: RbacStore,
    ): ...

    @property
    def data_root(self) -> PurePosixPath: ...

    # writes: async; one store transaction each; the document write goes through asyncify
    async def create_organization(self, *, slug, title, description, claim: IdempotencyClaim) -> Organization: ...
    async def patch_organization(self, organization_id, visibility, *, expected_version, slug, title, description) -> Organization: ...
    async def create_project(self, organization_id, visibility, *, slug, title, description, data_classification, claim) -> Project: ...
    async def patch_project(self, project_id, visibility, *, expected_version, slug, title, description) -> Project: ...
    async def create_dataset(self, project_id, visibility, *, slug, title, description, profile_name, profile_version, entry_layer=Layer.RAW.value, claim) -> Dataset: ...
    async def patch_dataset(self, dataset_id, visibility, *, expected_version, slug, title, description) -> Dataset: ...
    async def create_release(self, dataset_id, visibility, *, tag, revision_number, title, created_by, claim) -> Release: ...

    # reads: async; delegate to the store with the caller's visibility
    async def organization(self, organization_id, visibility) -> Organization: ...
    async def project(self, project_id, visibility) -> Project: ...
    async def dataset(self, dataset_id, visibility) -> Dataset: ...
    async def release(self, dataset_id, tag, visibility) -> Release: ...
    async def organizations(self, visibility, *, limit, after) -> Window[Organization]: ...
    async def projects(self, organization_id, visibility, *, limit, after) -> Window[Project]: ...
    async def datasets(self, project_id, visibility, *, limit, after) -> Window[Dataset]: ...
    async def releases(self, dataset_id, visibility, *, limit, after) -> Window[Release]: ...

    # RBAC: unchanged, except _require_scope reads through the store with Visibility.ALL
    #   (a grant targets a scope that must exist; the granting principal's own visibility is
    #   checked by the require_* guard before the handler runs)
```

The slug-immutability check, the classification-vocabulary check, `validate_slug`/`validate_tag`,
and the "document before visible" sequencing stay in the repository; the store never validates a
slug and never writes a document. `_fingerprint` becomes `request_sha256(operation, *parts)` in the
same module and feeds `IdempotencyClaim`; the claim's `principal` is the actor's subject, supplied by
the handler.

#### `PosixRawStore.write_generation` — one behavioral change

The numbered generation file is written with `atomic_replace`, not `write_once`. Immutability of
an *acknowledged* generation is guaranteed by the store — `generation` only advances through a
committed `UPDATE ... WHERE version = $expected` — not by `O_EXCL`. The one case where the file
already exists is a crashed attempt that wrote `generations/N.json` and never committed; that file
is provably unacknowledged (a committed row at generation N would have made the store hand out
N+1), so replacing it loses nothing a client was told succeeded. `write_tag_once` keeps `O_EXCL`:
a tag is a citation that must never be repointed (invariant M), and `FileExistsError` stays
`TagExists` — the existing pinned behavior.

#### `routes/v1/pagination.py` after

`paginate(records, view, key=..., limit=..., after=...)` is deleted. In its place:

```python
def page[RecordT, ViewT: BaseModel](
    window: Window[RecordT], view: type[ViewT], *, key: Callable[[RecordT], tuple[str, ...]]
) -> Page[ViewT]:
    return Page(
        items=[view.model_validate(item) for item in window.items],
        next_cursor=encode_cursor(key(window.items[-1])) if window.has_more else None,
    )


def after_key(cursor: str | None) -> tuple[str, ...] | None:
    return None if cursor is None else decode_cursor(cursor)
```

Handlers decode `after` into the store's `(slug, UUID)` / `(tag,)` tuple; `InvalidCursor` is raised
by `decode_cursor` as today, and additionally by the handler when the decoded tuple has the wrong
arity or a non-UUID id. `CURSOR_VERSION`, `encode_cursor`, `decode_cursor`, `PageLimit`,
`PageCursor`, `Page` are unchanged.

#### Handlers after

All seven hierarchy mutations become `async def` (they await the repository, which awaits the store
and `asyncify`s the document write); the six reads and the four lists gain the `Visibility`
dependency from Design 2 and pass `limit` and `after_key(after)` down. `readyz` stays `def` until
M8.2. The `EXPECTED_COROUTINE_FUNCTION` table in `test_execution_model.py` changes accordingly and
the two lock-invariant tests are deleted with the lock.

### Explicit contracts

1. **Durability and visibility.** A hierarchy resource is visible to any reader if and only if its
   row is committed. A committed row's generation document (and, for a release, its tag file) exists
   on the raw store, `fsync`'d, before the commit. A document with no committed row is an orphan
   and is lawful; the P3 reconciler owns importing or sweeping it. **Future authors must not move
   the document write outside the transaction in either direction.**
2. **Uniqueness.** Slug uniqueness per parent and tag uniqueness per dataset are enforced by the
   database's unique keys; the store translates the violation. The in-memory store enforces the same
   uniqueness at `insert_*` time. No caller pre-checks uniqueness.
3. **Optimistic concurrency.** `update_*` succeeds only when the stored `version` equals
   `expected_version`; it bumps `generation` and `version` by exactly one. Zero matched rows is
   `PreconditionFailed`. The repository reads the row (with the caller's visibility) before the
   update, so an invisible or absent id is `ResourceNotFound` rather than `PreconditionFailed`.
4. **Ordering.** `organizations`/`projects`/`datasets` are ordered by `(slug COLLATE "C", id)`;
   `releases` by `tag COLLATE "C"`. These are total orders (slug and tag are unique within their
   parent). The cursor key published by the handler is exactly this order; the in-memory store
   sorts by Python `(slug, id)`, which Receipt 1 proves equals `COLLATE "C"` order and differs from
   the deployment default.
5. **Windows.** `limit` is `1..200` (validated at the boundary). A window returns at most `limit`
   items and `has_more` is true iff at least one further visible row follows. `after` is exclusive.
   A cursor walk at `limit=1` enumerates every visible row exactly once and ends at
   `next_cursor: null` (this is the API sweep's own gate, now satisfied at the store).
6. **Idempotency.** A claim is `(principal, key)`. The same claim with the same `request_sha256`
   inside 24 hours replays the original resource with the original status; a different
   `request_sha256` is `IdempotencyKeyReused` (409). After 24 hours a claim may be taken over. A
   claim rolled back with its transaction leaves no record, so a retry after a `SlugExists` sees
   the same `SlugExists`. Two concurrent identical requests serialize on the claim row: one creates,
   the other replays. Expired rows are never deleted by this design (P3's sweeper).
7. **Revisions.** `revision_ref` is the only revision read; nothing in P1 writes
   `dataset_revisions`. The contract for the P2 author: `create_release` resolves
   `(dataset_id, revision_number)` through `revision_ref` and cites `RevisionRef.id`; the composite FK
   `releases_revision_dataset_fk` is the backstop.
8. **Store purity.** The store validates nothing about slugs, tags, classifications or entry layers
   and writes no files. Everything it refuses, it refuses because the database refused.
9. **The in-memory store is the reference implementation.** Every behavior in contracts 2–6 is
   pinned twice: in `tests/unit/` against `InMemoryHierarchyStore` and in
   `tests/contract/test_hierarchy_store.py` against the migrated `postgres:16`. A behavior proven
   on one backend and not the other is not done.

### Deletions

| File | Symbol | Why |
|---|---|---|
| `service/api/repository.py` | `organizations`, `projects`, `datasets`, `revisions`, `releases` dicts; `_lock`; `_idempotency`; `_replay`; `_remember`; `_expect_type`; `register_revision`; `get_*`; `list_*`; `resolve_release` | replaced by the store port |
| `service/api/repository.py` | `api_keys`, `credentials`, `sessions`, `principals` attributes and the four constructor keywords | move to `ApiRuntime` (Design 3) |
| `service/api/records.py` | `RevisionSeed` | `catalog.models.RevisionRef` is the same four fields |
| `routes/v1/pagination.py` | `paginate` | replaced by `page` + `after_key` |
| `pkg/rawstore/store.py` | the `write_once` call inside `write_generation` | `atomic_replace`, per the generation contract |
| `service/api/settings.py` | `store_backend` | Design 3 |
| `service/api/app.py` | `_postgres_repository`'s "only safe once" docstring and the `store_backend` branch | Design 3 |
| `tests/unit/test_execution_model.py` | `REPOSITORY_MODULE`, `_is_self_lock`, `test_no_await_appears_inside_a_mutating_hierarchy_repository_method`, `test_the_list_query_methods_never_acquire_the_lock`; the seven `False` rows for hierarchy mutations | the lock is gone; the handlers are `async def` |
| `tests/unit/test_repository_hierarchy.py` | the `_replay`/lock-shaped tests (`..._returns_a_snapshot_that_mutation_cannot_corrupt` ×4) | snapshot semantics were a property of dict iteration |

### Rejected alternatives

- **Document first, then row.** Keeps NFS out of the transaction, but a duplicate slug then leaves
  an orphan directory on every refusal, and the common failure becomes the expensive one.
- **Write the document after `COMMIT`.** Violates "a committed row has its document"; a crash then
  leaves a row whose `CURRENT.json` lags, which the reconciler must repair before P3 exists.
- **`O_EXCL` for generation files, raising a new `GENERATION_CONFLICT`.** Correct but wedges every
  `PATCH` on the entity until a reconciler exists; the file it protects is provably unacknowledged.
- **Idempotency keyed by `key` alone (today's behavior).** The DDL's primary key is
  `(principal, key)`; keying by `key` lets one principal replay another's response.
- **Push `limit`/`after` into `paginate` and keep whole-collection reads.** Design 3 OQ1 already
  ruled this out for the persistent store: an unbounded `SELECT` is not a design.
- **A `pkg/metastore` package now.** See Open question 1.

### Open questions

1. **Where does the store live: `service/api/stores/hierarchy.py` (recommended) or a new
   `pkg/metastore/`?** Roadmap §1 plans `pkg/metastore/` and says the SQL "lives in the api service
   tier" as a deviation. But the package-independence contract means `pkg/metastore` could not import
   `service/api/records.py` *or* `pkg/catalog` — the record types would first need a home in
   `huron/schema` (as the Python types of the generation document), which is a design of its own,
   and today the API is the only consumer. **Recommendation: `stores/hierarchy.py` now, following
   Design 10 and the port-pair convention; lift it into `pkg/metastore` in the P3 design pass, when
   `lakectl rebuild` becomes the second consumer and forces the records question.** The move is
   mechanical: the SQL and the port do not change.
2. **P1 depends on the API sweep's pending M8.1 (named errors) and M11.2 (`stores/` layout).
   Finish those first, or fold them into P1's first milestone?** **Recommendation: finish the
   sweep's M8–M11 first** — 14 tasks, all decisions answered, and M11.3/M11.4 are small; P1's plan
   then states "M11.2 complete" as a mechanical precondition (`stores/ports.py` exists).
3. **Idempotency TTL of 24 hours and take-over of expired claims.** No document names a number.
   **Recommendation: 24 hours**, matching the longest plausible client retry window for a create;
   record it in `design/api.html` §1's conventions paragraph when the write-back lands.
4. **Slug indexes under `COLLATE "C"`.** `organizations_slug_key`, `projects_organization_id_slug_key`
   and `datasets_project_id_slug_key` are built under `en_US.utf8`, so the `COLLATE "C"` `ORDER BY`
   cannot use them (Receipt 2 shows a Sort node). At hundreds of rows this is free; at T1 milestone
   5's thousands it is a sort per page. **Recommendation: hand a `0009` schema-track item three
   indexes `(... slug COLLATE "C", id)`, exactly as Design 10 OQ3 handed its three; P1 ships no DDL.**

## Design 2 — Visibility

### Target design

`design/rbac.html` §"Resolution order" is the specification: *"Listing is authorization:
`visible_project_ids` is applied in SQL before pagination, never as a post-filter; where existence
is sensitive the API returns 404, not 403."* The roadmap assigns the "filter-then-paginate" helper
to T0 milestone 3, but the store D1 builds is the one place the predicate can be born in SQL, and
the P1 gate names it. This design gives P1 the predicate and the 404; T0-3 keeps direct-vs-inherited
grant reporting, the audit row per denial, and the contract-test sweep over every route.

#### The three rules

| Level | Visible iff |
|---|---|
| dataset | `unrestricted` ∨ `project_id ∈ project_ids` ∨ `id ∈ dataset_ids` |
| project | `unrestricted` ∨ `id ∈ project_ids` ∨ ∃ visible dataset in it (via `dataset_ids`) |
| organization | `unrestricted` ∨ `id ∈ organization_ids` ∨ ∃ visible project in it ∨ ∃ visible dataset in it |
| release | its dataset is visible |

`organization_ids` alone does not make an organization's projects visible: an organization-scope
`dataset.discover` binding is already walked down by `visible_project_ids` for every project whose
classification permits, so a project outside `project_ids` under a visible organization is one the
classification gate hid, and it stays hidden. This is `rbac.html:94` — "Organization membership
grants discovery of org-public projects — nothing more."

#### Computing it — `pkg/rbac`

```python
@dataclass(frozen=True, slots=True)
class DatasetVisibility:
    dataset_id: UUID
    project_id: UUID


class RoleBindingAuthorizer:
    def visibility(
        self,
        principal: Principal,
        bindings: Sequence[Binding],
        projects: Sequence[ProjectVisibility],
        datasets: Sequence[DatasetVisibility],   # only the datasets named by DATASET-scope bindings
        *,
        now: datetime | None = None,
    ) -> Visibility:
        """
        unrestricted    := decide(bindings, principal, "dataset.discover", Scope.system()) is ALLOW
        project_ids     := visible_project_ids(principal, projects, bindings, now=now)
        organization_ids:= {b.scope_id for b in bindings if b.scope_type is ORGANIZATION
                            and b.matches(principal) and not b.is_expired(now)
                            and decide(bindings, principal, "dataset.discover",
                                       Scope(ORGANIZATION, b.scope_id, organization_id=b.scope_id)) is ALLOW}
        dataset_ids     := {d.dataset_id for d in datasets
                            if decide(bindings, principal, "dataset.discover", dataset_scope(d)) is ALLOW
                            and classification of d's project is discoverable or cleared}
        """
```

`Visibility` is defined in `pkg/rbac` (the value is a pure authorization result) and re-exported
by `stores/ports.py` for the store's signature — no `pkg` import direction changes. `RawStore`
precedent: the consumer names the type it needs; here the type already exists in `pkg/rbac`.

#### Applying it — `service/api/authorization`

```python
async def current_visibility(
    cache: BindingCache, repository: Repository, principal: CurrentPrincipal, runtime: Runtime
) -> Visibility:
    """One Visibility per request, memoized beside the bindings."""
    actor = as_rbac_principal(principal)
    bindings = await bindings_for_principal(cache, repository, actor)
    dataset_scoped = frozenset(b.scope_id for b in bindings if b.scope_type is ScopeType.DATASET and b.scope_id)
    projects = await repository.project_visibilities()
    parents = await repository.dataset_parents(dataset_scoped) if dataset_scoped else {}
    return runtime.authorizer.visibility(
        actor, bindings, projects, [DatasetVisibility(d, p) for d, p in parents.items()]
    )


CurrentVisibility = Annotated[Visibility, Depends(current_visibility)]
```

Memoized per request through the same `request_binding_cache` map (key: `("visibility",
actor.identifiers)`), so a route that runs a `require_*` guard and then a listing computes it once.
`runtime.authorizer` is the `RoleBindingAuthorizer(classifications=...)` the composition root
builds from `settings.classification_vocabulary` (Design 3).

The four scope helpers (`organization_scope`, `project_scope`, `dataset_scope`) take the visibility
and read through the store with it, so an undiscoverable id is `404` from every guarded route
before the capability check can answer `403`. The four `list_*` and four `get_*` handlers declare
`CurrentVisibility` and pass it through; they gain no other authorization — being able to discover a
resource is the whole requirement for reading its catalog entry.

#### Cost

One `SELECT id, organization_id, classification_default FROM projects` per request that reads the
hierarchy, plus one `dataset_parents` lookup for principals holding dataset-scope bindings. That is
the price of evaluating deny-overrides, scope walk and classification clearance in exactly one
place (`pkg/rbac`). Pushing the evaluation into SQL would be the second implementation of the role
model Design 10 warns against.

### Explicit contracts

1. **No leak through shape.** For a principal with visibility `V`, every list, count, cursor and
   404 is computed from the `V`-filtered set. A page is full-size when enough visible rows exist;
   `has_more` never reflects an invisible row; a cursor never encodes an invisible row's key.
2. **404 before 403.** A resource outside `V` is `ResourceNotFound` from point reads and from the
   scope helpers; `Forbidden` is only ever answered about a resource inside `V`.
3. **The predicate is the same text on both backends.** The three rules above are the SQL in
   Design 1 and the Python in `InMemoryHierarchyStore`; the contract test drives the same fixture
   through both and compares the id sets.
4. **Mutations do not use the caller's visibility to authorize** — `require_*` does — but they do
   use it to resolve the target (rule 2), so a create under an invisible parent is `404`.

### Deletions

None in `src/`. `test_api_catalog_hierarchy.py`'s listing tests gain a bound principal; the current
tests run as `root` (platform owner, `unrestricted`) and keep passing.

### Rejected alternatives

- **Post-filter the page.** Short pages and cursors that skip; the roadmap forbids it by name.
- **Visibility as a SQL join over `role_bindings`.** A second implementation of `decide`.
- **Leave it to T0 milestone 3.** Ships a store whose every listing is unbounded and unfiltered,
  then rewrites the SQL a milestone later; the roadmap's own sequencing rule ("born
  authorization-filtered rather than retrofitted") argues against it.

### Open questions

5. **Does P1 own visibility, or T0 milestone 3?** **Recommendation: P1 owns the predicate, the
   `Visibility` computation and the 404 rule (this design); T0-3 keeps the route-table-wide
   contract sweep, audit rows, and direct-vs-inherited grants.** The roadmap P1 gate cannot pass
   otherwise, and the store cannot be written twice.

## Design 3 — Composition root

### Target design

```python
@dataclass(frozen=True, slots=True)
class ApiRuntime:
    settings: ApiSettings
    repository: HierarchyRepository
    authorizer: RoleBindingAuthorizer
    api_keys: ApiKeyWriter
    credentials: CredentialStore
    sessions: SessionStore
    principals: PrincipalStore
    oidc_resolver: OidcResolver | None
    oidc_client: OidcClient | None
```

`create_app(settings, *, runtime_stores: ApiStores | None = None, oidc_verify=...)`: the lifespan
opens one `asyncpg.Pool` from `settings.database_url` and wires `PostgresHierarchyStore`,
`PostgresRbacStore`, `PostgresApiKeyStore`, `PostgresCredentialStore`, `PostgresSessionStore`,
`PostgresPrincipalStore` — unless a test injects `ApiStores` (a frozen dataclass of the six store
objects) built on the in-memory implementations. `store_backend` is deleted: production wiring has
one shape, and the memory stores are a test seam reached only through injection.
`bootstrap_platform_owner` is unchanged. The four `Annotated` aliases `ApiKeys`, `Credentials`,
`Sessions`, `Principals` join `Repository`/`Settings` in `runtime.py`, and `login.py`, `oidc.py`,
`users.py`, `api_keys.py`, `service_accounts.py` and `authorization` read them from the runtime
instead of through the repository.

### Explicit contracts

- `main.py` (D-1) reads the environment and calls `create_app(settings=...)` with no injection; it
  therefore always wires Postgres. `readyz` (M8.2) is where the pool is probed.
- `HierarchyRepository` no longer exposes any auth store; every test that reached
  `repository.sessions` etc. reaches `runtime.sessions`.

### Deletions

`ApiSettings.store_backend` and its docstring; `app._postgres_repository`; the "memory" branch of
the lifespan; `HierarchyRepository.api_keys/credentials/sessions/principals`.

### Rejected alternatives

- Keep `store_backend="memory"` as a runnable mode: it is precisely the mode that lost every
  organization on restart, and it would keep two production wirings alive for one deployable.

### Open questions

6. **Delete `store_backend` (recommended) or flip its default to `"postgres"`?** Deleting removes a
   footgun and a branch; flipping keeps a "no database" demo mode nobody has asked for.

## Design 4 — Verification debts

- **Property tests** (`hypothesis` is already a dev dependency): `paths.parse_revision_dir ∘
  revision_dir` is the identity over generated slugs and UUIDs; `validate_manifest` refuses any two
  entries equal under `NFC + casefold` and accepts any set distinct under it; `canonical_bytes` is
  invariant under key reordering and refuses integers ≥ 2⁵³; `uuid7()` carries version 7 and variant
  `10` and is monotone non-decreasing across calls in one process. One module,
  `tests/unit/test_catalog_properties.py`.
- **CI**: `.github/workflows/ci.yml` (the remote is `github.com:karthedew/huron`) with the four
  stages the roadmap P0 row names: `lint` (`make lint`), `unit` (`make test`), `contract`
  (`uv run pytest -m contract`, on `ubuntu-latest` where Docker serves `testcontainers`),
  `integration` (`uv run pytest -m integration`, currently zero tests, runs so the stage exists).
  The five import-linter contracts run inside `lint`.
- **Documentation write-back**, one change, owned by whoever lands the store (the roadmap's own
  rule): P1 row — hierarchy store, visibility and browse to `done` with per-item status; the
  `routes/v1/common.py` sentence deleted; "Schema conformance — `0008`" → `done`; the API sweep row
  to per-milestone status and "sixteen decisions … awaiting" → "seventeen, all answered
  2026-09-01"; §1 — "eleven packages / twelve services" → the enforced lists, `ObjectRepoStore`
  dropped from the `ports.py` sentence, "checked in CI" made true by the workflow above;
  `design/api.html` §2 `platform_admin` → `platform_owner`; `API_IMPLEMENTATION_PLAN.md:2542`;
  `SCHEMA_IMPLEMENTATION_PLAN.md` M1–M10 statuses.

### Open questions

7. **GitHub Actions?** The only remote is GitHub. **Recommendation: yes.**
8. **Is the contract stage allowed to be required?** It needs Docker on the runner; GitHub-hosted
   `ubuntu-latest` has it. **Recommendation: required.**
9. **For P2, not P1:** `catalog.ports.Metastore.record_revision(RevisionRecord, …)` cannot satisfy
   `dataset_revisions.metadata_sha256 NOT NULL`; either `RevisionRecord` gains the field or the
   column becomes nullable. Recorded here so the P2 design starts from it.

## Receipts

**Environment.** Disposable `postgres:16` via `podman run` (image default locale), migrated to
`0008_schema_conformance` with the repository's own Alembic; app driven through
`fastapi.testclient.TestClient` with `auth_mode="dev-headers"`. Container stopped afterwards;
nothing under `src/`, `tests/` or `migrations/` was modified by the grill or the design.

1. **Collation.** `SELECT datcollate FROM pg_database` → `en_US.utf8`. Ordering six slugs:
   default → `a-1 a1 a-b ab abc a-c`; `COLLATE "C"` → `a-1 a-b a-c a1 ab abc`; Python `sorted` →
   `a-1 a-b a-c a1 ab abc`. The deployment default disagrees with the cursor comparison on
   hyphenated slugs; `COLLATE "C"` agrees.
2. **Keyset + optimistic update.** Three organizations inserted; `WHERE (slug COLLATE "C", id) >
   ('a-b', <id>) ORDER BY slug COLLATE "C", id LIMIT 2` → `ab, abc`. `UPDATE … WHERE id=$1 AND
   version=1 RETURNING version` → `2`; the same statement again → `UPDATE 0`, and no row carries the
   second title. `EXPLAIN` shows `Sort Key: slug COLLATE "C", id` under a `Seq Scan` — the
   `en_US.utf8` unique indexes are not used (Open question 4).
3. **The hierarchy is in-process.** Two organizations, two projects, two datasets created over HTTP;
   files landed at the documented paths; the `organizations` table stayed empty (the app ran with
   `database_url="postgresql://unused"`).
4. **No visibility.** `user:nobody` with zero bindings listed both organizations, the other
   organization's project, the other project's dataset, and read the other dataset directly, all
   `200`.
5. **Cursor issued.** `GET /api/v1/organizations?limit=1` → `next_cursor: "v1:b3JnLWEf…"`.
6. **Anonymous refused.** `GET /api/v1/organizations` without a credential → `401
   INVALID_CREDENTIAL`.
