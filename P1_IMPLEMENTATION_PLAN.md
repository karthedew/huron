# Huron — P1 Foundations Implementation Plan

Companion to [`P1_DESIGN.md`](P1_DESIGN.md), which is the authoritative specification for
everything below; its **"Status addendum — 2026-09-03"** supersedes any earlier sentence it
contradicts. This file sequences that design into milestones and mechanically verifiable tasks; it
never restates the design. Every task names the `P1_DESIGN.md` heading that specifies it, and an
implementer is expected to read that heading before editing.

This plan is executed by `/implement-markdown P1_IMPLEMENTATION_PLAN.md`. It is deliberately named
apart from [`AUTH_IMPLEMENTATION_PLAN.md`](AUTH_IMPLEMENTATION_PLAN.md) (the shipped platform plan),
[`API_IMPLEMENTATION_PLAN.md`](API_IMPLEMENTATION_PLAN.md) (the shipped API clean sweep) and
[`FINDINGS_IMPLEMENTATION_PLAN.md`](FINDINGS_IMPLEMENTATION_PLAN.md), four of whose tasks
(M5.1, M5.2, M5.3, M4.2) this plan absorbs.

---

## 0. How an implementer reads this plan

**Authority.** `P1_DESIGN.md` decides; this plan sequences. Where a task and the design appear to
disagree, the design wins and the disagreement is a plan defect to report, not a choice to make.
Where this plan deliberately departs from a sentence in the design, § 3 says so and why.

**The task is the atomic unit, not the milestone.** `/implement-markdown` runs the complete
validation gate after every task. A task therefore must leave the tree compiling, the gate green,
and no half-migrated surface behind it. Where a change genuinely cannot be split without breaking
the tree, this plan says so and gives the milestone exactly one large task rather than pretending it
splits (M5.2 is that task).

**Resolved package path: `src/huron`** (`[tool.hatch.build.targets.wheel] packages = ["src/huron"]`).

**The validation gate**, run from the repository root after every task:

```text
make lint                                              # every static check, verbatim from Makefile
uv run pytest --cov=src/huron --cov-report=term-missing  # the unit suite with the coverage floor
```

`make lint` is, in order: `ruff check .`, `ruff format --check .`,
`pydoclint src migrations scripts`, `mypy`, `ty check`, `lint-imports`,
`python scripts/check_schema_map.py`, `radon cc src/huron --min C`, `radon mi src/huron --min B`,
`complexipy src/huron --max-complexity-allowed 15`, `pyscn check src/huron`. `make test` is
`uv run pytest -m unit` and is the fast local loop; it does not measure coverage and does not
substitute for the gate's second line.

Facts about this repository's gate that the tasks below depend on, checked against
`pyproject.toml` and `Makefile` rather than assumed:

- `[tool.pytest.ini_options] addopts = "-m unit --strict-markers"`. **A bare `uv run pytest`, and
  the gate's coverage line, run the `unit` marker only** and never execute `tests/contract/`. Every
  task that adds or changes a store, a port, or a contract test therefore carries an explicit
  `uv run pytest -m contract` step (M3.1, M3.2, M4.2, M5.2, M6.2) — which works because `addopts`
  is prepended to the command line and the later `-m contract` overrides the `-m unit`. That run needs the container
  runtime named under **Environment prerequisites**.
- Registered markers: `unit`, `contract`, `integration`, `acceptance`. No new marker may be added.
  `asyncio_mode = "auto"`, so `async def test_*` functions run without a decorator.
- `[tool.coverage.report] fail_under = 89`. A ratchet: never lower it. Every file a task creates or
  touches is at 100% line coverage unless a specific line is judged unreachable defensive code.
- `mypy` runs `strict = true` over `files = ["src/huron"]` and `[tool.ty.src] include` mirrors it:
  the service tier **is** type-checked by the gate. `asyncpg.*` has `ignore_missing_imports`, so
  every row is narrowed to a typed record at the store boundary (`stores/rows.py`).
- `lint-imports` enforces seven contracts. Two bind this plan directly: "Packages are independent
  of one another" (`huron.pkg.rbac` gains dataclasses, never an import of another package) and "the
  stores package is entered through its public surface" (`repository`, `app`, `authorization.**`
  and `routes.**` import from `huron.service.api.stores`, never from `stores.hierarchy` or
  `stores.rows`). No contract is added or edited by this plan: decision 1 puts the store in
  `service/api/stores/`, so no new package needs independence-checking.
- `scripts/check_schema_map.py` compares `migrations/schema.sql`'s `Reflects:` stamp to the
  Alembic head. This plan adds no migration, so the check must keep passing untouched.
- `hypothesis` is already in the `dev` dependency group (`pyproject.toml`); M6.1 adds no dependency.

**Environment prerequisites — check these once, before M1.1.** They are properties of the host,
not of the plan. If any is unmet, **stop and report**; none may be worked around by skipping,
weakening or deleting a gate step.

- **A container runtime** (Docker or Podman) reachable by `testcontainers`. All modules under
  `tests/contract/` (`test_auth_store.py`, `test_rbac_store.py`, `test_catalog_store.py`, and from
  M3.2 `test_hierarchy_store.py`) migrate a `postgres:16` container with the repository's own
  Alembic and drive it through `asyncpg`. Without a runtime they fail with `FileNotFoundError` on
  the daemon socket, for reasons unrelated to the change under test. A task whose mandatory
  contract step cannot run is not done: stop and report.
- **An `x86_64` or `darwin` host**, because `pyscn` is declared with the marker
  `platform_machine == 'x86_64' or sys_platform == 'darwin'`; elsewhere `make lint`'s last line
  fails with `Failed to spawn: pyscn`. Stop and report; do not drop `pyscn` from the gate.
- **A clean mypy cache.** A stale `.mypy_cache/` makes `uv run mypy` exit 2 with `INTERNAL ERROR`
  before any task has changed anything. Clear `.mypy_cache/` once before M1.1 and again on any
  `INTERNAL ERROR`. It is gitignored: a working-copy condition, never a gate failure to record
  against a task and never evidence of a defect in the change under test.
- **Working tree.** `main` at `2bcf604` plus uncommitted changes to seven files: `app.py` /
  `test_api_app.py` (lifespan hardening — pool closed when startup fails after it opens), `dev.env`
  (adds `HURON_DATA_ROOT=.data`), `src/huron/pkg/auth/oidc.py` / `tests/unit/test_auth_oidc.py`
  (discovery-document validation, the FINDINGS M2.1 work the design's addendum mentions),
  `FINDINGS_IMPLEMENTATION_PLAN.md` and `P1_DESIGN.md`. M4.2 rewrites that lifespan and must keep
  both of those tests' guarantees, and must keep the `HURON_DATA_ROOT` line in `dev.env`; M6.3's
  FINDINGS status counts depend on that file's uncommitted state. Do not discard any of these.

**Rules that bind every task in this plan.**

1. **No code comment, docstring, test name, commit note, or user-facing string may reference this
   plan, its milestones, task numbers, the design document, the FINDINGS plan or checklist
   mechanics.** Comments explain enduring code intent — invariants, lifecycle rules, security
   boundaries, tradeoffs — and are rare. A test is named for the behavior it pins.
2. **Clean sweep.** No backwards-compatibility shim, no deprecation alias, no re-export left
   behind, no TODO, no speculative abstraction, no partial migration, no suppressed lint. `# noqa`,
   `# type: ignore`, `# pragma: no cover`, `skip` and `xfail` may not be introduced to make the
   gate pass. If the gate cannot be satisfied without one, stop and report.
3. **No migration (decision 4).** No task may add, edit, or require a file under `migrations/` or
   `src/huron/schema`; no index, constraint, column or table is added, dropped or altered. The
   three `COLLATE "C"` slug indexes are a `0009` schema-track item, not work in this plan. All new
   SQL lives in `src/huron/service/api/stores/hierarchy.py` and is the text Design 1 gives. If a
   task appears to need a migration, that is a plan defect — escalate.
4. **Deletions land with the change that makes them dead**, in the same task, never deferred, and
   **by symbol, never by line**: a task names the function, class, attribute or test it removes;
   the implementer locates it with `grep -n`, never with a line number from this plan.
5. **No task waits on a decision.** All nine decisions and the three inherited ones are answered
   (§ 2); nothing is gated.
6. **Every Google-style docstring matches its signature** (`ruff` `D` rules and `pydoclint` in the
   gate): every new module, class, function and method documents `Args`/`Returns`/`Yields`/`Raises`
   as `docs/getting-started/docstrings.md` requires; tests carry a one-line summary.
7. **Subagents run serially**, one task at a time, in the order below.
8. **The in-memory store is the reference implementation** (Design 1, contract 9). A behavior is
   done when it is pinned against `InMemoryHierarchyStore` in `tests/unit/` *and* against the
   migrated `postgres:16` in `tests/contract/`. `tests/hierarchy_contract.py` holds the scenarios
   both runners execute so the two suites cannot drift apart.

---

## 1. Goal and non-goals

**Goal.** Make the roadmap's P1 row true for the only configuration that survives a restart. When
this plan is complete, the P1 gate of `design/roadmap.html` §2 — "Create org → project → dataset via
HTTP; generation docs and `CURRENT.json` at the exact documented paths; a release tag resolves to
one revision and a second write of the same tag is `409 TAG_EXISTS`; slug-change attempts 409;
API-key auth round-trip; a principal scoped to project A gets full-size pages with zero rows from B
and no evidence of B in counts or cursors; import-linter green" — holds with the hierarchy
persisted in PostgreSQL and its documents on the raw store (Design 1), visibility filtered in SQL
before `LIMIT` with `404` for anything undiscoverable (Design 2), one Postgres-only composition
root (Design 3), property tests over the pure core, a CI that runs the gate, and the roadmap and
plan documents rewritten to describe what shipped (Design 4). The release-tag clause is satisfied
against a revision row inserted by the contract test: nothing in P1 writes `dataset_revisions`
(Design 1, contract 7), and the P2 ingest path is what makes that clause reachable over HTTP.

**Non-goals.** Out of scope for every task below:

- Any DDL, `0009`, or edit under `migrations/` — including the three `COLLATE "C"` slug indexes
  (decision 4, schema track).
- The `dataset_revisions` writer, `Metastore.begin_ingest`/`record_revision`, and any ingest route
  (P2). Open question 9 (`record_revision` vs `metadata_sha256 NOT NULL`) is recorded for P2 and
  not touched here.
- A `pkg/metastore` package (decision 1: lift `stores/hierarchy.py` there in the P3 pass).
- The orphan-document reconciler and the expired-idempotency sweeper (P3). This plan deletes no
  `idempotency_records` row and imports or sweeps no orphan.
- Writers for `audit_events` and `outbox_events`, direct-vs-inherited grant reporting, the audit
  row per denial, and the route-table-wide authorization contract sweep (T0 milestone 3).
- The committed `openapi/v1.json` artifact and the TypeScript/Python client cores (T0 milestone 1).
- `POST /datasets/{id}:retire` and `POST …/releases/{tag}:withdraw` (T1 milestones 4 and 7).
- Any change to `pkg/rbac.decide`, the role model, or `visible_project_ids` beyond adding the
  `visibility()` method beside them (FINDINGS D-9 and D-10 stay in the FINDINGS plan).
- Any new pytest marker, coverage-floor change, or `import-linter` contract.

---

## 2. Decision register — all answered

Copied from `P1_DESIGN.md` § "Status addendum — 2026-09-03 › Decision register". **No task in this
plan is gated.**

| # | Question | Answer | Binds |
|---|---|---|---|
| 1 | Where the store lives | `service/api/stores/hierarchy.py`; lift to `pkg/metastore` in the P3 pass | M2.1, M3.1 |
| 2 | Precondition on API sweep M8.1 / M11.2 | Satisfied — shipped in `600ff2a` (`stores/`, `errors.py`, `authorization/` exist) | all |
| 3 | Idempotency TTL | 24 hours; an expired claim may be taken over; P1 deletes no rows | M2.1, M3.1, M6.3 |
| 4 | `COLLATE "C"` slug indexes | P1 ships no DDL; three `(… slug COLLATE "C", id)` indexes go to a `0009` schema-track item | § 0 rule 3 |
| 5 | Who owns visibility | P1 owns the `Visibility` value, the predicate and the 404 rule; T0-3 keeps the route-wide sweep, audit rows, direct-vs-inherited grants | M1.1, M2.2, M5.2, M5.3 |
| 6 | `store_backend` | Deleted; in-memory stores are a test seam reached only by injecting `ApiStores` | M4.2 |
| 7 | CI provider | GitHub Actions, `.github/workflows/ci.yml` | M6.2 |
| 8 | Contract stage required | Required | M6.2 |
| 9 | `Metastore.record_revision` vs `metadata_sha256 NOT NULL` | Deferred to P2, recorded as its starting point | non-goal |

Inherited from `FINDINGS_IMPLEMENTATION_PLAN.md` § 2, answered there and binding here:

| ID | Answer | Binds |
|---|---|---|
| D-7 | A `PATCH` that changes no field is a no-op: no `update_*`, no document, `200` with the current record | M2.1 (store never sees the call), M5.2, M5.3 |
| D-8 | `register_revision` refuses: unknown dataset → `ResourceNotFound`; duplicate `(dataset_id, number)` → `RuntimeError` | M2.1 |
| D-11 | Guards resolve the scope (404) before the layer rule (403) | M5.2 (B11: `dataset_layer_writer` resolves the scope before the layer rule) and M5.3 (B10: `_account_in_organization` → 404) |

---

## 3. Milestone sequence

Six milestones, fifteen tasks. Each milestone leaves the tree compiling and the gate green; each
task is sized for one implementation subagent within 30k–50k tokens except where marked.

| # | Milestone | Design | Tasks | Ends with |
|---|---|---|---|---|
| M1 | Ports and values | Design 1 › Layout, `stores/ports.py`; Design 2 › Computing it; Design 1 › `PosixRawStore.write_generation` | M1.1–M1.3 | `Visibility` and `HierarchyStore` exist and are tested; nothing in `src/` consumes them yet except `RevisionRef` and the generation write |
| M2 | In-memory reference store | Design 1 › `InMemoryHierarchyStore`; Design 2 › The three rules | M2.1–M2.2 | every Design 1 contract 2–6 behavior and every Design 2 rule pinned against the reference store, with the scenarios in a module both backends will run |
| M3 | Postgres store | Design 1 › `PostgresHierarchyStore` — the SQL; Design 2 › contract 3 | M3.1–M3.2 | the same scenarios green against migrated `postgres:16`, plus the Postgres-only pins |
| M4 | Composition root | Design 3 | M4.1–M4.2 | one production wiring (Postgres); `store_backend`, `_postgres_repository` and the repository's four auth attributes gone; tests inject `ApiStores` |
| M5 | The repository on the store | Design 1 › `HierarchyRepository` after, `pagination.py` after, Handlers after; Design 2 › Applying it; D-7, D-8, D-11; FINDINGS M5.1, M4.2 | M5.1–M5.3 | the hierarchy is Postgres rows; every list is visibility-filtered before `LIMIT`; every undiscoverable id is 404 |
| M6 | Verification debts | Design 4 | M6.1–M6.3 | property tests, CI, and the documents describing what shipped |

**Ordering rationale and four deliberate departures from the shape the design suggests.**

- Interfaces before implementations: M1 defines every value and Protocol; M2 and M3 implement
  them against the same scenario module; only then does M5 rewire the consumer.
- **The composition root (Design 3) lands before the repository rewire (Design 1's
  `HierarchyRepository` after).** Every `create_app(` call site in `tests/unit/` and every
  `HierarchyRepository(` construction there are reshaped by these two designs. Doing
  Design 3 first moves every test onto one helper (`tests/unit/support.py::memory_stores`) once;
  M5.2 then changes that helper and the two repository-level test modules instead of touching
  fourteen test files a second time. It also lands the deletions (`store_backend`,
  `_postgres_repository`, the four auth attributes) two milestones earlier, which is what § 0
  rule 4 asks. The cost is one transitional milestone (after M4, before M5) in which the sole
  production wiring is Postgres for RBAC and auth while the hierarchy is still process-local —
  exactly the state `store_backend="postgres"` opts into on `main` today, now for one milestone
  without the opt-in. The roadmap is not told the hierarchy is persistent until M6.3, so no
  document claims otherwise in between.
- **M5.2 is one large task.** The repository's method surface, the four hierarchy endpoint modules,
  the scope helpers, the guards and the execution-model test change together or the tree does not
  compile: a handler cannot `await` a repository that is still synchronous, and a synchronous
  handler cannot call a repository that is now `async`. § 5 (risk 1) gives the pre-approved
  fallback split if the budget is exhausted.
- **Design 1's Deletions row for `pagination.py` / `paginate` applies to the hierarchy call sites
  only.** `paginate` is also called by the binding, policy and service-account listings (and
  imported by `tests/contract/test_rbac_store.py`), which page whole `RbacStore` results — a port
  this plan does not change (§ 1). M5.2 deletes the four hierarchy call sites and keeps the function.
- **M5.1 moves the cursor arity/UUID check into `slug_cursor_key` / `tag_cursor_key`** rather than
  raising `InvalidCursor` "additionally by the handler" as Design 1 › "`routes/v1/pagination.py`
  after" says; the check exists once in the decoders and every handler gets it by calling them.
- `request_sha256` is introduced in M5.2 where it replaces `_fingerprint`, not in M1: a module
  function with no caller for four milestones is churn, and the FINDINGS M5.1 fingerprint cases
  are written once, against the claim-based repository.
- `readyz` is already `async def` and already probes `ApiRuntime.database_pool` (API sweep M8.2
  shipped); the design's "stays `def` until M8.2" is stale and this plan keeps `database_pool` on
  `ApiRuntime` (`None` when stores are injected) rather than removing it as Design 3's dataclass
  sketch would imply.
- `current_visibility` is memoized by FastAPI's own per-request dependency cache
  (`Depends(..., use_cache=True)`, the default) rather than by widening `request_binding_cache`'s
  `dict[frozenset[str], tuple[Binding, ...]]` to hold a second value type. The design's
  requirement — computed once per request however many guards and handlers declare it — holds
  without the type change.
- Both hierarchy stores take an optional `clock: Clock` (`huron.pkg.catalog.ports.Clock`, the
  house "injected so lease arithmetic is testable" Protocol) so the 24-hour take-over in
  contract 6 can be pinned on both backends without back-dating rows by SQL; the default is the
  system UTC clock and production passes nothing.

---

## 4. Per-milestone task breakdown

### M1 — Ports and values

#### Task M1.1 — `Visibility` and `RoleBindingAuthorizer.visibility()` in `pkg/rbac`

**Intent.** Give the tier one pure authorization result — the three id sets plus `unrestricted` —
computed in the one place that already evaluates deny-overrides, the scope walk and classification
clearance.

**Design.** `P1_DESIGN.md` › Design 2 › Target design › "Computing it — `pkg/rbac`"; Design 1 ›
`stores/ports.py` (the `Visibility` dataclass text, which lives here and is re-exported there).

**Create / modify.**

- `src/huron/pkg/rbac/__init__.py`: add `Visibility` (frozen, slots; `organization_ids`,
  `project_ids`, `dataset_ids`: `frozenset[UUID]`, `unrestricted: bool`; class attribute `ALL =
  Visibility(unrestricted=True)` assigned after the class body — a `ClassVar` on a slots dataclass
  is set on the class, not the instance) and `DatasetVisibility` (frozen, slots; `dataset_id`,
  `project_id`); add `RoleBindingAuthorizer.visibility(principal, bindings, projects, datasets, *,
  now=None) -> Visibility` implementing the four rules of the design's docstring: `unrestricted`
  iff `decide(..., "dataset.discover", Scope.system())` is `ALLOW`; `project_ids` is
  `frozenset(self.visible_project_ids(...))`; `organization_ids` is the set of `scope_id` of
  unexpired, matching `ORGANIZATION` bindings whose organization scope decides `ALLOW` for
  `dataset.discover`; `dataset_ids` holds each `DatasetVisibility` whose dataset scope (built from
  its project's `ProjectVisibility` for the organization ancestry) decides `ALLOW` and whose
  project's classification is in the vocabulary and discoverable or cleared (reuse
  `_has_clearance`). A dataset whose `project_id` is not among `projects` is never visible. Add
  both classes to `__all__`. Module docstring names the new value.
- No import is added: `pkg/rbac` stays framework-free and independent (`lint-imports`).

**Tests.** New `tests/unit/test_rbac_visibility.py` (`pytestmark = pytest.mark.unit`), one test per
rule: SYSTEM `dataset.discover` → `unrestricted` and nothing else populated; a project binding →
`project_ids` equals `visible_project_ids` and `organization_ids` empty; an organization binding →
`organization_ids` holds it and `project_ids` holds only projects the classification gate admits
(one discoverable, one not, same organization); a dataset binding → `dataset_ids` holds it only
when its project is discoverable or cleared, and never when its project is absent from `projects`;
an expired binding contributes to no set; a `DENY` at the organization removes it from
`organization_ids`; `Visibility.ALL.unrestricted is True` and `Visibility()` is empty.

**Verification.**

- `uv run pytest -m unit tests/unit/test_rbac_visibility.py tests/unit/test_authorization_decisions.py` passes.
- `uv run lint-imports` reports 7 kept, 0 broken.
- `grep -n "class Visibility\|class DatasetVisibility\|def visibility" src/huron/pkg/rbac/__init__.py` shows all three.
- Full gate.

**Dependencies.** None.

**Status: done**

#### Task M1.2 — The hierarchy port in `stores/ports.py`

**Intent.** Declare the consumer-owned Protocols and values every later milestone implements
against, so the two backends and the repository are written to one text.

**Design.** `P1_DESIGN.md` › Design 1 › Target design › "`stores/ports.py` — the hierarchy port"
(the code block is the specification: signatures, keyword-only markers, return types); Design 1 ›
Explicit contracts 1–8 (the docstrings state them).

**Create / modify.**

- `src/huron/service/api/stores/ports.py`: add `Window[ItemT]` (frozen, slots; `items:
  list[ItemT]`, `has_more: bool`), `IdempotencyClaim` (`principal`, `key`, `request_sha256`),
  `Replay` (`kind: Literal["organization", "project", "dataset", "release"]`, `resource_id:
  UUID`), `HierarchyWriter(Protocol)` and `HierarchyStore(Protocol)` exactly as the design's block
  declares them, with `from huron.pkg.rbac import Visibility` and `from
  huron.pkg.catalog.models import RevisionRef`. `transaction()` returns
  `AbstractAsyncContextManager[HierarchyWriter]` (`contextlib`). Every method docstring states
  the contract it carries: point reads raise `ResourceNotFound` when absent *or* invisible; windows
  are ordered by the cursor key and filtered by visibility before the window; `after` is exclusive;
  `claim` returns `Replay` for a live identical claim, raises `IdempotencyKeyReused` for a live
  different one, takes over an expired one; the writer validates nothing and writes no file
  (contract 8). Module docstring: "two Protocols" → the four it now owns.
- `src/huron/service/api/stores/__init__.py`: export `HierarchyStore`, `HierarchyWriter`,
  `IdempotencyClaim`, `Replay`, `Visibility`, `Window`; docstring updated.

**Tests.** The port has no behavior of its own; its contracts are pinned by M2 and M3. This task
adds `tests/unit/test_stores_ports.py` with two tests only: `Window`, `IdempotencyClaim` and
`Replay` are frozen (assignment raises `FrozenInstanceError`), and `huron.service.api.stores`
exports the six names (`__all__` membership).

**Verification.**

- `uv run pytest -m unit tests/unit/test_stores_ports.py` passes.
- `uv run mypy` and `uv run ty check` pass (the generic `Window[ItemT]` and the
  `AbstractAsyncContextManager[HierarchyWriter]` return type are accepted by both).
- `uv run lint-imports` reports 7 kept.
- Full gate.

**Dependencies.** M1.1 (`Visibility`).

**Status: done**

#### Task M1.3 — `RevisionSeed` → `RevisionRef`; `write_generation` replaces instead of refusing

**Intent.** Two independent one-symbol changes that later milestones build on: the service tier
names revisions with the catalog's own value, and a generation file is replaced rather than
`O_EXCL`-refused, because acknowledged immutability is the store's job from M5 on.

**Design.** `P1_DESIGN.md` › Design 1 › Target design › the sentence after the port block
("`RevisionRef` is `huron.pkg.catalog.models.RevisionRef` … `RevisionSeed` is deleted"); Design 1 ›
"`PosixRawStore.write_generation` — one behavioral change"; Design 1 › Deletions (rows
`records.py` / `RevisionSeed` and `pkg/rawstore/store.py` / `write_once` call).

**Modify / delete.**

- `src/huron/service/api/records.py`: delete `RevisionSeed`; module docstring "Nine dataclasses"
  → eight.
- `src/huron/service/api/repository.py`: `revisions: dict[tuple[UUID, int], RevisionRef]`,
  `register_revision(self, revision: RevisionRef)`, import from `huron.pkg.catalog.models`;
  `_write_generation` docstring no longer promises `FileExistsError` for an existing generation.
- `tests/unit/test_api_catalog_hierarchy.py`, `tests/unit/test_repository_hierarchy.py`: import
  `RevisionRef` from `huron.pkg.catalog.models` in place of `RevisionSeed` (same four fields, same
  keyword names).
- `src/huron/pkg/rawstore/store.py` › `PosixRawStore.write_generation`: the numbered generation file
  is written with `self.atomic_replace(generation_path, payload, mode=0o444)`; docstring rewritten
  to say why (an existing file at that number is provably unacknowledged; acknowledged generations
  are immutable because the store advances `generation` only through a committed update).
  `write_tag_once` and `write_once` are unchanged.

**Tests.** New `tests/unit/test_rawstore_generation.py`: `write_generation(dir, 1, a)` then
`write_generation(dir, 1, b)` succeeds and `generations/000001.json` holds `b`; `CURRENT.json`
names generation 1 after both; `write_generation(dir, 2, c)` leaves `000001.json` untouched and
repoints `CURRENT.json`; `write_tag_once` still raises `FileExistsError` on the second write; the
generation out-of-range `ValueError` is unchanged.

**Verification.**

- `grep -rn "RevisionSeed" src tests` returns nothing.
- `grep -n "write_once(generation_path" src/huron/pkg/rawstore/store.py` returns nothing.
- `uv run pytest -m unit tests/unit/test_rawstore_generation.py tests/unit/test_repository_hierarchy.py tests/unit/test_api_catalog_hierarchy.py` passes.
- Full gate.

**Dependencies.** None (independent of M1.1/M1.2; ordered here so M2 starts from `RevisionRef`).

**Status: done**

### M2 — In-memory reference store

#### Task M2.1 — `InMemoryHierarchyStore` and the write-side scenarios

**Intent.** Implement the port once in process memory as the reference every other implementation
is compared against, and pin the transaction, uniqueness, optimistic-concurrency, idempotency and
revision contracts in a scenario module both backends will run.

**Design.** `P1_DESIGN.md` › Design 1 › Target design › "`InMemoryHierarchyStore`"; Design 1 ›
Explicit contracts 1, 2, 3, 6, 7, 8, 9; Status addendum › D-8 (`register_revision` refuses).

**Create.**

- `src/huron/service/api/stores/hierarchy.py` (new module; both backends live here, M3.1 adds the
  second) with `class InMemoryHierarchyStore`:
  - `__init__(self, *, clock: Clock | None = None)` — five dicts (`_organizations`, `_projects`,
    `_datasets`, `_releases` keyed `(dataset_id, tag)`, `_revisions` keyed `(dataset_id,
    number)`), an idempotency dict `(principal, key) -> (request_sha256, Replay | None,
    expires_at)`, one `asyncio.Lock`; `clock` defaults to a private UTC system clock.
  - `transaction()` — an `@asynccontextmanager` that holds the lock for the block, yields a writer
    that buffers every write in an undo log, applies the buffer on clean exit and discards it on
    exception. `insert_*` raises `SlugExists`/`TagExists` against the live dicts *plus* the buffer;
    `insert_release` raises `ResourceNotFound` when `(dataset_id, revision_id)` names no registered
    revision (the composite-FK backstop, contract 7); `update_*` raises `PreconditionFailed` when
    the live `version` differs from `expected_version` and otherwise stores the item as given.
  - `claim` / `remember` per contract 6 with the 24-hour TTL measured by `clock.now()`: a live
    claim with the same `request_sha256` returns the remembered `Replay`; a live claim with a
    different `request_sha256` raises `IdempotencyKeyReused`; an expired claim is taken over (its
    `request_sha256` and `expires_at` rewritten, its `Replay` cleared). A claim made inside a
    transaction that raises is discarded with the buffer. Because `transaction()` holds the lock,
    no second transaction can observe a claim whose `remember` has not yet run, so the store has no
    "claimed, not remembered" branch to code.
  - The point reads, windows, `project_visibilities`, `dataset_parents` and `revision_ref` per the
    port (windows: `sorted` by `(slug, id)` / `tag`, `bisect` past `after`, slice `limit + 1`,
    `has_more = len > limit`). M2.2 pins these; M2.1 implements them so the class conforms to the
    Protocol from its first commit.
  - `register_revision(self, revision: RevisionRef) -> None` (not on the port): `ResourceNotFound`
    for an unknown dataset, `RuntimeError` for a duplicate `(dataset_id, number)` (D-8).
  - Visibility predicates: three private functions implementing Design 2's table, used by both the
    point reads and the windows, so the rule text exists once in this class.
- `src/huron/service/api/stores/__init__.py`: export `InMemoryHierarchyStore`.
- `tests/__init__.py` (new; a one-line docstring, rule 6). `tests/` has no `__init__.py` today, so
  pytest's `prepend` import mode puts `tests/` itself on `sys.path` and the suites import as
  `unit.*` / `contract.*`; with the marker they import as `tests.unit.*` / `tests.contract.*` with
  the repository root on `sys.path`, and the shared module below is importable by its package path.
- `tests/hierarchy_contract.py` (new; imported by both suites, so it lives in the `tests` package
  root beside `tests/unit/` and `tests/contract/`, and both suites import it as
  `from tests.hierarchy_contract import ...`): `async def` scenario functions taking
  `store: HierarchyStore` and `seed_revision: Callable[[RevisionRef], Awaitable[None]]` (the
  in-memory suite passes `store.register_revision`; the contract suite passes a SQL insert), plus
  a `seed_hierarchy(store, ...)` builder both suites call. Write-side scenarios in this task:
  1. a write is invisible until the `async with` block exits, and invisible forever if it raises
     (contract 1, the store's half);
  2. duplicate slug per parent → `SlugExists` at `insert_*`, same slug under a different parent
     succeeds; duplicate tag per dataset → `TagExists` (contract 2);
  3. `update_*` with the current version stores the successor; with a stale version raises
     `PreconditionFailed` and changes nothing (contract 3);
  4. identical claim within the TTL → `Replay` naming the original resource; different
     `request_sha256` → `IdempotencyKeyReused`; same key under another principal → a fresh claim;
     a claim whose transaction raised leaves nothing (a retry after `SlugExists` sees `SlugExists`
     again); a claim older than 24 hours by the injected clock is taken over; two concurrent
     identical transactions (`asyncio.gather`) end with exactly one resource and one `Replay`
     (contract 6);
  5. `revision_ref` returns the seeded `RevisionRef` and raises `ResourceNotFound` otherwise;
     `insert_release` citing an unseeded revision raises `ResourceNotFound` (contract 7).
- `tests/unit/test_hierarchy_store_memory.py` (`pytestmark = pytest.mark.unit`): one `async def
  test_*` per scenario, each building a fresh `InMemoryHierarchyStore` with a settable fake clock,
  plus the D-8 tests for `register_revision` (unknown dataset → `ResourceNotFound`; duplicate
  number → `RuntimeError`; a registered revision is what `revision_ref` returns).

**Verification.**

- `test -f tests/__init__.py`.
- `uv run pytest -m unit tests/unit/test_hierarchy_store_memory.py` passes (this is what proves
  `from tests.hierarchy_contract import ...` resolves; M3.2's `uv run pytest -m contract` proves it
  for the second suite).
- `grep -n "class InMemoryHierarchyStore\|def register_revision\|asyncio.Lock" src/huron/service/api/stores/hierarchy.py` shows all three.
- `uv run lint-imports` reports 7 kept (the new module imports `huron.pkg.*` and
  `huron.service.api.records` / `.errors` only).
- `uv run radon cc src/huron --min C` and `uv run complexipy src/huron --max-complexity-allowed 15`
  report nothing for `stores/hierarchy.py`.
- Full gate.

**Dependencies.** M1.2, M1.3.

**Status: done**

#### Task M2.2 — Window and visibility scenarios

**Intent.** Pin the ordering, the window arithmetic and the three visibility rules against the
reference store, in the shared scenario module, before any SQL exists to be compared with them.

**Design.** `P1_DESIGN.md` › Design 1 › Explicit contracts 4, 5; Design 2 › Target design › "The
three rules" (including the paragraph beginning "`organization_ids` alone does not…"); Design 2 ›
Explicit contracts 1, 3; Receipts › 1 (the six slugs).

**Create / modify.**

- `tests/hierarchy_contract.py`: add
  6. ordering — organizations, projects and datasets seeded with slugs `a-1 a1 a-b ab abc a-c`
     window in the order `a-1 a-b a-c a1 ab abc` (Receipt 1: Python `(slug, id)` order, which
     `COLLATE "C"` matches and the deployment default does not); releases order by tag the same
     way (contract 4);
  7. windows — `limit` items at most; `has_more` true iff a further visible row exists; `after` is
     exclusive; a `limit=1` walk enumerates every visible row exactly once and ends with
     `has_more=False`; a window over an invisible parent raises `ResourceNotFound` from the parent
     read the repository performs first (contract 5);
  8. visibility — the `seed_hierarchy` fixture (organizations A and B; projects A1, A2, B1;
     datasets under each; releases under one) evaluated under five `Visibility` values
     (`Visibility.ALL`; `project_ids={A1}`; `dataset_ids={A2d1}`; `organization_ids={A}` alone;
     `Visibility()`), returning the id set each level's window and point reads admit, and asserting
     the expected sets from Design 2's table: `project_ids={A1}` reveals A, A1 and A1's datasets
     only; `dataset_ids={A2d1}` reveals A, A2 and A2d1 only; `organization_ids={A}` reveals A and
     nothing beneath it; `Visibility()` reveals nothing and every point read is `ResourceNotFound`;
     a release is visible iff its dataset is (Design 2 rules and contract 1 — `has_more` and the
     last item's key never reflect an invisible row);
  9. `project_visibilities()` returns every project with its organization and
     `classification_default`; `dataset_parents(ids)` maps only the ids that exist.
  The visibility scenario returns the computed id sets so M3.2 can compare the two backends
  (Design 2 contract 3).
- `tests/unit/test_hierarchy_store_memory.py`: one test per new scenario.

**Verification.**

- `uv run pytest -m unit tests/unit/test_hierarchy_store_memory.py` passes.
- `grep -c "^async def scenario_\|^async def seed_" tests/hierarchy_contract.py` is at least 10
  (scenario functions are named `scenario_<n>_<behavior>`, builders `seed_*`, so the count is a
  real check).
- Full gate.

**Dependencies.** M2.1.

**Status: done**

### M3 — Postgres store

#### Task M3.1 — Row mappers and `PostgresHierarchyStore`

**Intent.** Implement the same port over `asyncpg` with the SQL Design 1 gives, translating
exactly the database refusals the design names and nothing else.

**Design.** `P1_DESIGN.md` › Design 1 › Target design › "`PostgresHierarchyStore` — the SQL"
(the SQL block is the specification, including the `COLLATE "C"` clauses, the `limit + 1` fetch,
the idempotency `INSERT … ON CONFLICT … WHERE expires_at <= …` and the `FOR UPDATE` comparison),
"Column mapping the store owns" and "Error mapping"; Design 1 › "The write mechanism" (the writer
runs inside one `asyncpg` transaction); Current State › Conventions (hand-written SQL, `$n`
parameters, row → record mapping functions, one `DomainError` per `asyncpg` exception class,
following `stores/rbac.py`).

**Create / modify.**

- `src/huron/service/api/stores/rows.py`: add `organization(row)`, `project(row)` (maps
  `classification_default` → `Project.data_classification`), `dataset(row)`, `release(row)`,
  `revision_ref(row)` (maps `revision_number` → `RevisionRef.number`). Module docstring: "seven"
  mappers → twelve.
- `src/huron/service/api/stores/hierarchy.py`: add `class PostgresHierarchyStore` with
  `__init__(self, pool: asyncpg.Pool, *, clock: Clock | None = None)`; `transaction()` acquires a
  connection, opens `connection.transaction()`, yields a private writer bound to that connection;
  every statement is the design's text. Writes: `INSERT … organizations/projects/datasets` with
  `lifecycle_state 'ACTIVE'`, `updated_at = created_at`; `datasets.data_classification` written
  from the value the repository passes (`insert_dataset(item, *, data_classification=...)`);
  `UPDATE … WHERE id = $1 AND version = $7 RETURNING id` with zero rows → `PreconditionFailed`;
  `updated_at` set to the patch time. Errors: `asyncpg.UniqueViolationError` whose
  `constraint_name` is `organizations_slug_key`, `projects_organization_id_slug_key` or
  `datasets_project_id_slug_key` → `SlugExists`; `releases_dataset_id_tag_key` → `TagExists`;
  `asyncpg.ForeignKeyViolationError` on `releases_revision_dataset_fk` → `ResourceNotFound`; every
  other `asyncpg` error propagates. Idempotency: the claim `INSERT … RETURNING key`; no row → `SELECT
  request_sha256, response FROM idempotency_records WHERE principal = $1 AND key = $2 FOR UPDATE`,
  equal digest → `Replay(response["kind"], UUID(response["id"]))`, different → `IdempotencyKeyReused`;
  `remember` is the `UPDATE … SET status_code = 201, response = $3::jsonb`. `created_at` for the
  claim is `clock.now()`. Reads: the four windows and four point reads with the visibility
  predicate text from the design, parameters `(unrestricted, organization_ids, project_ids,
  dataset_ids)` passed as `bool` and `list[UUID]`; `revision_ref`; `project_visibilities` (`SELECT
  id, organization_id, classification_default FROM projects`); `dataset_parents` (`SELECT id,
  project_id FROM datasets WHERE id = ANY($1::uuid[])`).
- `src/huron/service/api/stores/__init__.py`: export `PostgresHierarchyStore`.

**Tests.** `tests/unit/test_stores_rows.py`: one test per new mapper, following the module's
existing fake-`Record` pattern, including the `classification_default` and `revision_number`
renames and `Release.title` `None`. The store itself is pinned in M3.2.

**Verification.**

- `uv run pytest -m unit tests/unit/test_stores_rows.py` passes.
- `uv run pytest -m contract` passes (the three existing contract modules still hold; this proves
  the new module imports cleanly under the contract collection and that `stores/__init__` still
  exports what `test_rbac_store.py` imports).
- `grep -o 'COLLATE "C"' src/huron/service/api/stores/hierarchy.py | wc -l` is at least 12 (every text
  `ORDER BY` and keyset comparison in the four windows and their point-read twins).
- `grep -n "constraint_name" src/huron/service/api/stores/hierarchy.py` shows the four unique keys
  and the one foreign key named above.
- `uv run mypy` passes with no `type: ignore` added (the `asyncpg.*` override already exists).
- Full gate.

**Dependencies.** M2.1 (the module and its shared visibility predicate names), M1.2.

**Status: done**

#### Task M3.2 — `tests/contract/test_hierarchy_store.py`

**Intent.** Prove every scenario of `tests/hierarchy_contract.py` against a migrated
`postgres:16`, compare the two backends' visibility sets on the identical fixture, and pin the
Postgres-only properties the design records receipts for.

**Design.** `P1_DESIGN.md` › Design 1 › Explicit contracts 4, 6, 9; Design 2 › Explicit contract 3;
Receipts › 1, 2; Current State › Conventions › "Migrated-database contract tests".

**Create.** `tests/contract/test_hierarchy_store.py` (`pytestmark = pytest.mark.contract`),
modelled on `tests/contract/test_catalog_store.py`: `PostgresContainer("postgres:16")`, Alembic
`upgrade head` through the module's `_config`/`_migrate` pattern, one `asyncpg` pool, and:

1. `test_the_postgres_hierarchy_store_against_a_migrated_database` — runs every scenario in
   `tests/hierarchy_contract.py` (imported as `from tests.hierarchy_contract import ...`) against `PostgresHierarchyStore(pool, clock=fake)`, with
   `seed_revision` implemented as a direct `INSERT INTO dataset_revisions` supplying every `NOT
   NULL` column (`metadata_sha256`, `revision_path`, `file_count`, `total_bytes`, `committed_by`,
   `committed_at`, `state 'COMMITTED'`). Each scenario runs against distinct slugs so one database
   serves the whole module.
2. `test_both_backends_admit_the_same_ids_under_every_visibility` — seeds `InMemoryHierarchyStore`
   and the Postgres store with the identical fixture (same ids, same slugs) and asserts the id sets
   scenario 8 returns are equal, level by level, for all five `Visibility` values (Design 2
   contract 3).
3. `test_windows_order_by_the_c_collation_not_the_cluster_default` — the six Receipt-1 slugs
   inserted, `SELECT datcollate FROM pg_database WHERE datname = current_database()` recorded in
   the assertion message, the window order asserted equal to Python's `sorted`; a plain `ORDER BY
   slug` executed through the pool is asserted *different* when the cluster collation is not `C`,
   so a future image whose default is `C` reports the receipt as vacuous rather than passing silently.
4. `test_concurrent_identical_claims_serialize_on_the_row` — two transactions started with
   `asyncio.gather`, the first holding its claim across an `asyncio.Event` until the second has
   issued its `claim`; the second returns `Replay` only after the first commits, and exactly one
   organization row exists.
5. `test_a_rolled_back_claim_leaves_no_row_and_an_expired_one_is_taken_over` — `SELECT count(*)
   FROM idempotency_records` is `0` after a raising transaction; a claim, the fake clock advanced
   by 24 hours and one second, the same key with a different digest → a fresh claim and
   `request_sha256` rewritten in the row.
6. `test_stores_conform_to_their_ports_structurally_not_by_inheritance` — `HierarchyStore not in
   PostgresHierarchyStore.__mro__` and `not in InMemoryHierarchyStore.__mro__`, the same guard
   `test_rbac_store.py` keeps.

**Verification.**

- `uv run pytest -m contract tests/contract/test_hierarchy_store.py` passes.
- `uv run pytest -m contract` passes (all four modules).
- `uv run pytest -m unit tests/unit/test_hierarchy_store_memory.py` still passes (the shared
  scenario module was not bent to fit Postgres).
- `grep -c "COLLATE" tests/contract/test_hierarchy_store.py` is at least 1.
- Full gate (the contract module is collected under `--strict-markers` and lint-checked by `ruff`,
  `pydoclint` is scoped to `src migrations scripts`).

**Dependencies.** M3.1, M2.2.

**Status: done**

### M4 — Composition root

#### Task M4.1 — `ApiStores`, the auth stores on `ApiRuntime`, and the repository stripped of them

**Intent.** Move the four authentication stores and the authorizer from the repository to the
runtime, and replace the `repository=` test seam with an injected set of stores, so the
composition root has one shape to build and tests have one thing to inject.

**Design.** `P1_DESIGN.md` › Design 3 › Target design (the `ApiRuntime` dataclass and the
`create_app` signature); Design 3 › Explicit contracts (second bullet); Design 3 › Deletions
(`HierarchyRepository.api_keys/credentials/sessions/principals`); Design 1 › Deletions (the row
"`api_keys`, `credentials`, `sessions`, `principals` attributes and the four constructor keywords").

**Create / modify / delete.**

- `src/huron/service/api/runtime.py`: add `ApiStores` (frozen, slots): `rbac: RbacStore`,
  `api_keys: ApiKeyWriter`, `credentials: CredentialStore`, `sessions: SessionStore`, `principals:
  PrincipalStore` (M5.2 adds `hierarchy: HierarchyStore`). `ApiRuntime` gains `authorizer:
  RoleBindingAuthorizer`, `api_keys`, `credentials`, `sessions`, `principals` (same Protocol types)
  and keeps `settings`, `repository`, `oidc_resolver`, `oidc_client`, `database_pool`. Add the
  dependency functions and `Annotated` aliases `ApiKeys`, `Credentials`, `Sessions`, `Principals`
  beside `Repository`/`Settings`; extend `__all__`. Docstring: `database_pool` is `None` when
  stores were injected.
- `src/huron/service/api/app.py`: `create_app(*, settings, stores: ApiStores | None = None,
  oidc_verify=None)` — the `repository` keyword is deleted. Lifespan: `wired = stores` when
  injected, else `_postgres_stores(pool)` when `settings.store_backend == "postgres"`, else
  `_memory_stores()` (both private helpers return `ApiStores`; `_postgres_repository` is deleted);
  the repository is built here as `HierarchyRepository(PosixRawStore(settings.data_root),
  classification_vocabulary=…, rbac_store=wired.rbac)`; the authorizer as
  `RoleBindingAuthorizer(classifications=tuple(Classification(v.code, v.order, v.discoverable) for
  v in settings.classification_vocabulary))`; `ApiRuntime(...)` receives all of it. The
  try/finally that closes the pool and the HTTP client on any failure after they open is kept.
  `_bootstrap`, `_dependency_checks`, `readyz` unchanged.
- `src/huron/service/api/repository.py`: `__init__(self, raw_store, *, classification_vocabulary,
  rbac_store: RbacStore)` — `rbac_store` required, the four auth keywords and the four attributes
  deleted, the "fresh in-memory store when omitted" paragraph deleted, the `huron.pkg.auth` memory
  imports deleted; class docstring `Attributes` trimmed.
- Consumers switch from `repository.<store>` to the runtime alias:
  `authorization/credentials.py` (`runtime.api_keys`, `runtime.sessions` — it already holds
  `runtime`), `routes/v1/endpoints/users.py`, `routes/v1/endpoints/api_keys.py`,
  `routes/v1/endpoints/service_accounts.py`, `routes/auth/endpoints/login.py`,
  `routes/auth/endpoints/oidc.py` (declare `ApiKeys`/`Credentials`/`Sessions`/`Principals` as
  parameters).
- `tests/unit/support.py` (new): `memory_stores() -> ApiStores` building `InMemoryRbacStore()`,
  `MemoryApiKeyStore()`, `MemoryCredentialStore()`, `MemorySessionStore()`,
  `MemoryPrincipalStore()`; one-line module docstring.
- Every test that passed `repository=` to `create_app` now passes `stores=memory_stores()` and
  reaches the repository it needs through `client.app.state.runtime.repository` after the
  `TestClient` context has entered (every module `grep -rln "repository=" tests/unit` lists). Every
  test that read `repository.sessions` / `.credentials` / `.principals` / `.api_keys` reads the
  store it injected (or `app.state.runtime.<store>`): every module
  `grep -rln "repository\.\(api_keys\|credentials\|sessions\|principals\)" tests/unit` lists.
  Direct `HierarchyRepository(...)` constructions in `test_repository_hierarchy.py`,
  `test_repository_rbac.py`, `test_authorization_guards.py` and the fixtures of
  `test_api_catalog_hierarchy.py` pass `rbac_store=InMemoryRbacStore()`.

**Tests.** `tests/unit/test_api_app.py`: a test that injected `ApiStores` are the ones
`app.state.runtime` exposes (identity), and that `runtime.authorizer.classifications` mirrors
`settings.classification_vocabulary` in order. Existing lifespan tests keep their guarantees.

**Verification.**

- `grep -rn "repository\.\(api_keys\|credentials\|sessions\|principals\)" src tests` returns nothing.
- `grep -rn "api_key_store=\|credential_store=\|session_store=\|principal_store=" src tests` returns nothing.
- `grep -n "repository: HierarchyRepository | None" src/huron/service/api/app.py` returns nothing;
  `grep -n "_postgres_repository" src` returns nothing.
- `grep -n "class ApiStores" src/huron/service/api/runtime.py` shows it.
- `uv run lint-imports` reports 7 kept.
- Full gate; `uv run pytest -m contract` is not required (no store or port changed).

**Dependencies.** None on M1–M3 (deliberately: this task is independent of the hierarchy store and
could be reordered by an operator; it is placed here so M5 follows it directly).

**Status: done**

#### Task M4.2 — One production wiring: `store_backend` deleted

**Intent.** Make Postgres the only wiring `create_app` builds on its own, leaving the in-memory
stores reachable exclusively through injection.

**Design.** `P1_DESIGN.md` › Design 3 › Target design ("`store_backend` is deleted: production
wiring has one shape…"); Design 3 › Explicit contracts (first bullet: `main.py` always wires
Postgres); Design 3 › Deletions; Design 3 › Rejected alternatives; Status addendum › decision 6.

**Modify / delete.**

- `src/huron/service/api/settings.py`: delete `store_backend` and its comment block.
- `src/huron/service/api/app.py`: lifespan reads `stores` or opens the pool and calls
  `_postgres_stores(pool)`; `_memory_stores` and the `store_backend` branch deleted; every
  docstring sentence naming `store_backend` rewritten (`create_app`, the lifespan). `main.py`
  needs no change and must not gain one.
- `src/huron/service/api/runtime.py`: the `ApiRuntime` docstring sentence about `store_backend`
  rewritten ("`database_pool` is `None` only when the stores were injected").
- `dev.env`: delete only the `HURON_STORE_BACKEND=postgres` line; the uncommitted
  `HURON_DATA_ROOT=.data` line stays. `docs/getting-started/local-development.md`:
  delete the `HURON_STORE_BACKEND` table row, the admonition "`HURON_STORE_BACKEND` defaults to
  `memory`…" and the clause naming it near line 70; the surrounding prose says the API always
  connects to `HURON_DATABASE_URL`. (`site/` is a build output and is not edited.)
- `tests/unit/test_api_settings.py`: the `store_backend == "memory"` assertion becomes
  `"store_backend" not in ApiSettings.model_fields`.
- `tests/unit/test_api_app.py`: `test_lifespan_closes_an_already_open_pool_when_oidc_discovery_fails`
  and `test_lifespan_closes_the_pool_when_repository_construction_fails` drop their
  `store_backend="postgres"` settings (the un-injected path now opens the pool by default) and
  keep their assertions; every other `create_app(settings=…)` call in `tests/unit/` that expects a
  serving app gains `stores=memory_stores()` (`grep -rn "create_app(" tests/unit | grep -v
  stores=` must be empty except the two pool tests and any test that asserts a startup refusal
  before stores are touched).

**Tests.** `tests/unit/test_api_app.py`: with `asyncpg.create_pool` monkeypatched to a recording
fake, `create_app(settings=…)` with no `stores` opens exactly one pool from `settings.database_url`
and publishes `PostgresRbacStore`, `PostgresApiKeyStore`, `PostgresCredentialStore`,
`PostgresSessionStore`, `PostgresPrincipalStore` instances on the runtime; with `stores=` the fake
is never called and `runtime.database_pool is None`.

**Verification.**

- `grep -rn "store_backend\|STORE_BACKEND" src tests dev.env docs docker-compose.yml` returns nothing.
- `grep -rn "create_app(" tests/unit | grep -v "stores=" ` lists only the tests named above.
- `uv run pytest -m contract` passes (no change expected; run because the composition root that
  the contract suites' stores serve was rewritten).
- `make docs` builds (`uv run --group docs zensical build --strict`), proving the doc edit left no
  broken anchor.
- Full gate.

**Dependencies.** M4.1.

**Status: done**

### M5 — The repository on the store

#### Task M5.1 — `pagination.page` and the cursor-key decoders

**Intent.** Give the handlers the encoder-only pagination surface they switch to in M5.2, tested
on its own first.

**Design.** `P1_DESIGN.md` › Design 1 › Target design › "`routes/v1/pagination.py` after"; Design 1
› Explicit contracts 4, 5.

**Create / modify.**

- `src/huron/service/api/routes/v1/pagination.py`: add `page(window, view, *, key)` exactly as the
  design's block; add `after_key(cursor) -> tuple[str, ...] | None`; add two typed decoders built
  on it that keep the arity and id checks in one place — `slug_cursor_key(cursor) -> tuple[str,
  UUID] | None` (two parts, second a UUID; otherwise `InvalidCursor`) and `tag_cursor_key(cursor)
  -> tuple[str] | None` (one part; otherwise `InvalidCursor`). `paginate` stays: the binding, policy
  and service-account listings page whole `RbacStore` results with it until that port grows
  windows. Module docstring rewritten to describe both surfaces — `page` over a store `Window` for
  the hierarchy and `paginate` over a whole list for the `RbacStore`-backed listings (the
  "hierarchy lives in process dictionaries" paragraph goes).

**Tests.** `tests/unit/test_api_pagination.py`: `page` returns `next_cursor` encoding the last
item's key iff `has_more`; `page` over an empty window returns `next_cursor: null`; `after_key`
round-trips `encode_cursor`; `slug_cursor_key` rejects one-part and three-part cursors and a
non-UUID second part with `InvalidCursor`, accepts a valid one; `tag_cursor_key` rejects two parts.

**Verification.**

- `uv run pytest -m unit tests/unit/test_api_pagination.py` passes.
- `grep -n "^def page\|^def after_key\|^def slug_cursor_key\|^def tag_cursor_key" src/huron/service/api/routes/v1/pagination.py` shows four.
- Full gate.

**Dependencies.** M1.2 (`Window`).

**Status: done**

#### Task M5.2 — The repository, the handlers, the scope helpers and the guards move onto the store — **one large task**

**Intent.** Replace the process dictionaries with the `HierarchyStore`, make every hierarchy write
one store transaction with the document inside it, push `limit`/`after` and the caller's
`Visibility` down to the store, and make every undiscoverable id a `404` from every read, guard and
mutation. This task cannot be split without a broken tree; § 5 risk 1 gives the fallback.

**Design.** `P1_DESIGN.md` › Design 1 › Target design › "The write mechanism — row, then document,
then commit", "`HierarchyRepository` after this change", "Handlers after"; Design 1 › Explicit
contracts 1, 3, 6, 7, 8; Design 1 › Deletions (every `repository.py`, `pagination.py` and
`test_execution_model.py` / `test_repository_hierarchy.py` row); Design 2 › Target design ›
"Applying it — `service/api/authorization`", "Cost"; Design 2 › Explicit contracts 2, 4; Status
addendum › "What moved" second bullet (M5.1 digest over every settable argument; D-7 no-op patch;
D-11 scope before layer; M5.3 reads check existence).

**Modify / delete — `src/huron/service/api/repository.py`.**

- `__init__(self, raw_store, hierarchy: HierarchyStore, *, classification_vocabulary, rbac_store)`.
  Delete the five dicts, `_lock`, `_idempotency`, `_replay`, `_remember`, `_expect_type`,
  `register_revision`, `get_organization`/`get_project`/`get_dataset`,
  `list_organizations`/`list_projects`/`list_datasets`/`list_releases`, `resolve_release`, the
  `threading` and `hashlib`-for-`_fingerprint` uses that go with them. Module and class docstrings
  rewritten around the invariants that remain (slug immutability, classification vocabulary, the
  document written inside the store transaction, store purity).
- `request_sha256(operation: str, *parts: str | None) -> str` replaces `_fingerprint`: NUL-joined,
  `None` encoded by a sentinel byte distinct from the empty string (so `title=None` and
  `title=""` differ), SHA-256 hex. Public, because the handlers build the `IdempotencyClaim` with
  it (the claim's `principal` is the actor's subject the handler holds; the digest parts are the
  same keyword arguments the handler passes to the repository, covering every settable field:
  organization — slug, title, description; project — organization id, slug, title, description,
  data_classification; dataset — project id, slug, title, description, profile_name,
  profile_version, entry_layer; release — dataset id, tag, revision_number, title, created_by).
- Writes, all `async def`, each one `async with self._hierarchy.transaction() as writer`:
  validate (`validate_org_slug`/`validate_slug`/`validate_tag`, the classification vocabulary)
  before anything else; resolve the parent through the store with the *caller's* visibility
  (`create_project` → `organization(organization_id, visibility)`, `create_dataset` →
  `project` then its organization, `create_release` → `dataset` then `revision_ref`) so an
  invisible parent is `ResourceNotFound` (Design 2 contract 4); `replay = await writer.claim(claim)`
  and on a `Replay` return the named resource read with `Visibility.ALL`; build the record with
  `uuid7()` and `datetime.now(UTC)`; `await writer.insert_*(...)` (`insert_dataset` passes
  `data_classification=project.data_classification`); `await asyncify(self._write_generation)(dir,
  item)` — for a release, `await asyncify(self.raw_store.write_tag_once)(...)` with
  `FileExistsError` → `TagExists` as today; `await writer.remember(claim, Replay(kind, item.id))`.
  Nothing is written to disk before the row insert succeeded (the cheap refusals come first).
- Patches, all `async def`: `item = await self.<read>(id, visibility)`; a different `slug` →
  `SlugImmutable`; `item.version != expected_version` → `PreconditionFailed`; **D-7**: when
  `title` and `description` are each `None` or equal to the stored value, return `item` with no
  transaction and no document; otherwise `successor = dataclasses.replace(item, ..., generation=
  item.generation + 1, version=item.version + 1)`, and inside one transaction `await
  writer.update_*(successor, expected_version=item.version)` then the document write; return the
  successor. Parent slugs for the document path are read through the store with `Visibility.ALL`.
- Reads, all `async def`, delegating to the store with the visibility given: `organization`,
  `project`, `dataset`, `release`, `organizations`, `projects`, `datasets`, `releases`
  (`Window[...]`), plus `project_visibilities()` and `dataset_parents(ids)` pass-throughs for the
  visibility dependency. `projects`/`datasets`/`releases` first read the parent with the caller's
  visibility (the design's "checked first by `organization()`").
- `_require_scope` becomes `async def` and reads through the store with `Visibility.ALL`;
  `bindings_at` and `list_service_accounts` call it (FINDINGS M5.3's first half: an unknown scope
  is `ResourceNotFound`, not `[]`).

**Modify — `src/huron/service/api/authorization/`.**

- `decisions.py`: add `current_visibility(cache, repository, principal, runtime) -> Visibility`
  as the design's block (bindings via `bindings_for_principal`; `dataset_parents` only when a
  DATASET-scope binding exists; `runtime.authorizer.visibility(...)`) and `CurrentVisibility =
  Annotated[Visibility, Depends(current_visibility)]`; FastAPI's per-request dependency cache is
  the memoization. Export both from `authorization/__init__.py`.
- `scopes.py`: `organization_scope`, `project_scope`, `dataset_scope` become `async def
  (repository, id, visibility) -> Scope`, reading through the repository with the caller's
  visibility (404 before 403 now also covers the invisible).
- `guards.py`: the four `require_*` dependencies declare `visibility: CurrentVisibility` and
  `await` the scope helper; `dataset_layer_writer` resolves `dataset_scope` **before**
  `parse_layer`/`ensure_layer_writable` (**D-11**), so an unknown or invisible dataset is `404`
  before any layer refusal. `require_system` is unchanged.

**Modify — `src/huron/service/api/routes/v1/endpoints/`.**

- `organizations.py`, `projects.py`, `datasets.py`: every hierarchy handler is `async def`. The
  seven mutations bind the guard's principal (`actor: Annotated[Principal, Depends(require_*(…))]`
  where today only `dependencies=[…]` is declared), build `IdempotencyClaim(principal=actor.subject,
  key=idempotency_key, request_sha256=request_sha256(...))` for the creates, and pass
  `visibility: CurrentVisibility` to the patches and to `create_project`/`create_dataset`/
  `create_release`. The four `list_*` handlers pass `visibility`, `limit` and
  `slug_cursor_key(after)` / `tag_cursor_key(after)` down and render with `page(window, View,
  key=_key)`; the four `get_*`/`resolve_release` handlers and `list_layers` read with
  `visibility`. Each handler's `\f` prose sentence about the threadpool is deleted; the
  `responses=` maps are unchanged (`404` is already declared on every read).
- `pagination.py`: `paginate` **stays**. Delete only its four hierarchy call sites (in
  `organizations.py`, `projects.py` and the two in `datasets.py`; locate with `grep -n paginate`);
  the `RbacStore`-backed listings in `bindings.py`, `policies.py` and `service_accounts.py`, and
  `tests/contract/test_rbac_store.py`, keep calling it. `tests/unit/test_api_pagination.py` keeps
  its four `paginate` tests beside the `page` tests M5.1 added.

**Modify — `src/huron/service/api/runtime.py`, `app.py`, `tests/unit/support.py`.**
`ApiStores` gains `hierarchy: HierarchyStore` (first field); the lifespan passes `wired.hierarchy`
to the repository; `_postgres_stores(pool)` builds `PostgresHierarchyStore(pool)`;
`memory_stores()` builds `InMemoryHierarchyStore()`. `stores/__init__.py` needs no change
(everything is exported since M3.1).

**Tests.**

- `tests/unit/test_repository_hierarchy.py`: rewritten as `async def` tests over
  `HierarchyRepository(PosixRawStore(...), InMemoryHierarchyStore(), classification_vocabulary=
  ..., rbac_store=InMemoryRbacStore())`, passing `Visibility.ALL` and an `IdempotencyClaim` built
  with `request_sha256`. Delete the four `*_returns_a_snapshot_that_mutation_cannot_corrupt`
  tests, `test_create_organization_rejects_a_replay_whose_stored_result_has_the_wrong_type` (the
  `_expect_type` path is gone) and every `list_*`/`get_*`/`resolve_release`/`register_revision`
  caller (revisions are seeded through `InMemoryHierarchyStore.register_revision`). Keep and port
  every replay, duplicate-slug, classification, slug-immutability, stale-version, tag-collision and
  tag-document test. Add: **M5.1's** replay-with-one-changed-field case per previously omitted field
  (`create_project` `data_classification`; `create_dataset` `description`; `create_release`
  `title` `None` vs `""` and `created_by`) each raising `IdempotencyKeyReused`; **D-7**: a patch
  naming no field, and one naming the current values, returns an equal record, writes no new
  generation file (count the `generations/` directory) and leaves the old `If-Match` version
  valid; a failing document write (raw store patched to raise) leaves the store's record unchanged
  (the transaction rolled back — FINDINGS M5.2's durable-before-visible); a create whose document
  write raises leaves no row and no idempotency record; an invisible parent → `ResourceNotFound`
  from `create_project`/`create_dataset`/`create_release`; the document write runs off the event
  loop (patch `PosixRawStore.write_generation` to record `asyncio.get_running_loop()` raising
  `RuntimeError` in the worker thread).
- `tests/unit/test_repository_rbac.py`: `bindings_at(ScopeType.PROJECT, uuid4())` and
  `list_service_accounts(uuid4())` raise `ResourceNotFound`; repository constructions gain the
  in-memory hierarchy store.
- `tests/unit/test_authorization_guards.py`: scope helpers awaited with a visibility; a visible
  but unauthorized dataset → `Forbidden`; an invisible dataset → `ResourceNotFound` from
  `require_dataset` even for a caller who holds a binding elsewhere; `dataset_layer_writer` with an
  unknown dataset and `silver` → `ResourceNotFound`, not the layer error (D-11).
- `tests/unit/test_authorization_decisions.py`: `current_visibility` for a SYSTEM
  `platform_owner` is `unrestricted`; for a project-scoped reader holds exactly that project; for
  a dataset-scoped reader calls `dataset_parents` and holds that dataset; for a caller with no
  bindings is `Visibility()`.
- `tests/unit/test_api_catalog_hierarchy.py`: revisions seeded through
  `stores.hierarchy.register_revision`; the `repository` fixture becomes a `stores` fixture; all
  existing HTTP assertions (cursor walks, ordering, 404s, `TAG_EXISTS`, replay bodies, no `ETag`)
  keep passing under `root`.
- `tests/unit/test_execution_model.py`: every hierarchy row in `EXPECTED_COROUTINE_FUNCTION`
  becomes `True` (the table keeps 52 entries); delete `REPOSITORY_MODULE`, `_is_self_lock`,
  `test_no_await_appears_inside_a_mutating_hierarchy_repository_method`,
  `test_the_list_query_methods_never_acquire_the_lock`; the `ast` import goes if nothing else uses
  it.

**Verification.**

- `grep -n "RLock\|_idempotency\|def _replay\|def _remember\|def _expect_type\|def register_revision\|def get_organization\|def list_organizations\|def resolve_release\|self.organizations\b" src/huron/service/api/repository.py` returns nothing.
- `grep -n "paginate" src/huron/service/api/routes/v1/endpoints/organizations.py src/huron/service/api/routes/v1/endpoints/projects.py src/huron/service/api/routes/v1/endpoints/datasets.py` returns nothing.
- `grep -rn "_fingerprint" src tests` returns nothing.
- `grep -n "^def \|^    def " src/huron/service/api/routes/v1/endpoints/organizations.py src/huron/service/api/routes/v1/endpoints/projects.py src/huron/service/api/routes/v1/endpoints/datasets.py` lists only `_key`/`_release_key` and the nested `may` (every handler is `async def`).
- `grep -n "CurrentVisibility" src/huron/service/api/authorization/__init__.py src/huron/service/api/routes/v1/endpoints/*.py` shows the export and all fifteen hierarchy read/write declarations (4 lists + 4 point reads + 3 patches + 3 child creates + `list_layers`).
- `grep -n "ensure_layer_writable(" -B 3 src/huron/service/api/authorization/guards.py` shows `dataset_scope` awaited above it.
- `uv run pytest -m unit tests/unit/test_repository_hierarchy.py tests/unit/test_repository_rbac.py tests/unit/test_authorization_guards.py tests/unit/test_authorization_decisions.py tests/unit/test_api_catalog_hierarchy.py tests/unit/test_execution_model.py tests/unit/test_api_rbac.py tests/unit/test_api_pagination.py` passes.
- `uv run pytest -m contract` passes.
- `uv run lint-imports` reports 7 kept (routes import `request_sha256` from
  `huron.service.api.repository`, not from `stores.*`).
- Full gate, coverage floor held.

**Dependencies.** M2.1, M3.1, M4.2, M5.1.

**Status: done**

#### Task M5.3 — Visibility over HTTP, and 404 before 403 everywhere

**Intent.** Prove the roadmap's gate sentence through the API with bound principals on both
in-memory paths, and close FINDINGS M4.2's remaining half.

**Design.** `P1_DESIGN.md` › Design 2 › Explicit contracts 1, 2; Design 2 › Deletions ("listing
tests gain a bound principal"); Status addendum › D-11 / FINDINGS M4.2 (B10: `_account_in_organization`).

**Modify.**

- `src/huron/service/api/routes/v1/endpoints/service_accounts.py`: `_account_in_organization`
  raises `ResourceNotFound` for an account in another organization (its callers' `responses=`
  already declare only `404`; docstrings updated); the `Forbidden` import stays only if the
  disabled-account refusal still uses it.
- `design/api.html`: the two service-account rows say "named from the wrong organization: 404"
  (M4.2's own one-line doc edit; the larger write-back is M6.3).

**Tests.**

- `tests/unit/test_api_catalog_hierarchy.py` (or a new `tests/unit/test_api_visibility.py` if the
  module would exceed ~1000 lines — the implementer's call, stated in the commit): with `root`
  creating organizations A and B, projects A1/A2 (A2 under a non-discoverable classification in a
  two-level vocabulary) and B1, datasets under each, and a `reader` binding granted to
  `user:alice` at project A1 through `POST /api/v1/projects/{A1}/bindings`: as `alice`,
  `GET /api/v1/organizations?limit=1` returns A, `next_cursor: null`; `GET
  /api/v1/organizations/{A}/projects` returns A1 only; a `limit=1` walk over A1's datasets visits
  each exactly once with no B id in any page or cursor; `GET /api/v1/organizations/{B}`,
  `GET /api/v1/projects/{B1}`, `GET /api/v1/datasets/{B1d}`, `GET /api/v1/projects/{A2}` and `GET
  /api/v1/datasets/{A1d}/releases/{unknown}` under B answer `404 NOT_FOUND`; `PATCH
  /api/v1/projects/{B1}` with `If-Match` answers `404`, not `403`; `POST
  /api/v1/organizations/{B}/projects` answers `404`; `GET /api/v1/datasets/{B1d}/layers` answers
  `404`. A principal with no bindings gets empty pages and `404` for every id.
- `tests/unit/test_api_service_accounts.py`: the two cross-organization tests expect `404`.
- `tests/unit/test_api_catalog_hierarchy.py`: route-level twins of M5.1 (replay with one changed
  field → `409 IDEMPOTENCY_KEY_REUSED` for `data_classification`, dataset `description`, release
  `title`) and of D-7 (`PATCH` with `{}` → `200`, same `version`, no new generation file under
  `data_root`).

**Verification.**

- `grep -n "Forbidden(\"service account belongs" src/huron/service/api/routes/v1/endpoints/service_accounts.py` returns nothing.
- `uv run pytest -m unit tests/unit/test_api_catalog_hierarchy.py tests/unit/test_api_service_accounts.py tests/unit/test_api_rbac.py` passes (plus `tests/unit/test_api_visibility.py` if created).
- Full gate.

**Dependencies.** M5.2.

**Status: done**

### M6 — Verification debts

#### Task M6.1 — Property tests over the pure core

**Intent.** Pin the invariants the roadmap says "everything else leans on" with generated inputs
rather than seven examples.

**Design.** `P1_DESIGN.md` › Design 4 › first bullet ("Property tests"); Roadmap Drift › Drift 7.

**Create.** `tests/unit/test_catalog_properties.py` (`pytestmark = pytest.mark.unit`), using
`hypothesis` with an explicit `settings(deadline=None, max_examples=200)` profile applied per test
so a slow CI runner never turns a passing property into a flaky deadline failure:

1. `parse_revision_dir(root, revision_dir(root, organization, project, dataset, number, id))`
   is the identity for generated organization/project slugs (`^[a-z0-9][a-z0-9-]{1,61}$` without
   `--`), dataset slugs up to `DATASET_SLUG_MAX`, `1 <= number <= 999_999`, and `uuid7()` ids.
2. `validate_manifest` raises `PathCollision` for any two entries whose paths are equal under
   `unicodedata.normalize("NFC", …).casefold()` and accepts any set of paths pairwise distinct
   under it (generated from a small alphabet including a precomposed/decomposed pair and mixed
   case), holding every other rule satisfied.
3. `canonical_bytes` is invariant under key reordering of nested mappings and raises for any
   integer with `abs(n) >= 2**53` at any depth, accepting every integer below.
4. `uuid7()` carries version 7 and RFC 9562 variant bits, and a sequence of calls in one process is
   non-decreasing as integers.

**Verification.**

- `grep -rln "hypothesis" tests` lists `tests/unit/test_catalog_properties.py`.
- `uv run pytest -m unit tests/unit/test_catalog_properties.py` passes in under 60 seconds locally.
- Full gate.

**Dependencies.** None.

**Status: done**

#### Task M6.2 — `.github/workflows/ci.yml`

**Intent.** Make "green in CI" a fact: four stages on GitHub Actions, the contract stage required.

**Design.** `P1_DESIGN.md` › Design 4 › second bullet ("CI"); Status addendum › decisions 7, 8;
Roadmap Drift › Drift 5.

**Create.** `.github/workflows/ci.yml`, triggered on `push` to `main` and on `pull_request`, on
`ubuntu-latest`, installing `uv` (`astral-sh/setup-uv`) and `uv sync --all-groups`, with four jobs:
`lint` (`make lint`), `unit` (`uv run pytest --cov=src/huron --cov-report=term-missing`),
`contract` (`uv run pytest -m contract` — `ubuntu-latest` provides Docker for `testcontainers`),
`integration` (`uv run pytest -m integration`; zero tests today, so the job exists and passes on
"no tests ran" — pass `--no-header -q` and treat exit code 5 as success explicitly in the step, so
the stage is honest rather than green by accident). `contract` is not `continue-on-error`, and the
README/`docs` need no change. `python-version` taken from `.python-version` if the repository
has one, else `3.12` — the floor `requires-python` declares; `setup-uv` reads `.python-version` on
its own when present.

**Verification.**

- `test -f .github/workflows/ci.yml`.
- `uv run --with pyyaml python -c "import yaml, pathlib; yaml.safe_load(pathlib.Path('.github/workflows/ci.yml').read_text())"` exits 0 (`--with` supplies PyYAML for that one invocation whether or not the dev group carries it).
- Push the branch; all four jobs green on `github.com/karthedew/huron` Actions for the commit that
  adds the workflow. The plan is not done until that run exists (§ 6).
- Full gate locally (the file is not Python; the gate proves nothing regressed).

**Dependencies.** M3.2 (the contract stage must have the hierarchy module to run), M5.3.

**Status: done**

#### Task M6.3 — Documentation write-back

**Intent.** Make the roadmap and the plan documents describe the checkout again, in the one change
the roadmap's own rule assigns to whoever lands the store. Phase 5 of the `/design-plan` run that
produced this plan already rewrote the P1 row to describe what this *plan* commits to; this task
flips those sentences to what *shipped*.

**Design.** `P1_DESIGN.md` › Design 4 › third bullet ("Documentation write-back"); Roadmap Drift ›
Drifts 1–10; Status addendum › decision 3 (record the TTL in `design/api.html` §1).

**Modify** (surgically; confirm each current sentence with `grep -n` before replacing; match the
document's tag vocabulary `done` / `partial` / `todo`):

- `design/roadmap.html` §2, P1 row: hierarchy store, `RoleBindingAuthorizer` discovery gating,
  browse with keyset pagination and visibility → `done` with per-item status; the sentence
  naming `page()` in `routes/v1/common.py` deleted; the gate sentence kept verbatim, with a
  clause that the release-tag half is proven against a contract-test revision row until P2's
  ingest lands; the row tag `partial` → whatever remains open (OpenAPI artifact + client cores are
  T0-1's and stay `todo`, so the row stays `partial` with that as its only open item).
- `design/roadmap.html` §2, "Schema conformance — `0008`" row: `todo` → `done`.
- `design/roadmap.html` §2, "API tier clean sweep" row: "Nothing here has been implemented — every
  task is `Status: pending`" → shipped in `600ff2a`, 28 tasks done; "sixteen decisions … awaiting"
  → seventeen, all answered 2026-09-01.
- `design/roadmap.html` §1: "eleven packages" / "twelve services" → the four packages and one
  service the `import-linter` lists enforce, with the sentence that each deployable is added as it
  gains code; `ObjectRepoStore` removed from the `ports.py` sentence; "all five are checked in CI"
  → seven, and true (link the workflow). §2 P0 row: the CI clause is now backed; §4 "FIPS smoke and
  the OpenAPI-contract check run from P0 onward" → still `todo`, said plainly.
- `design/api.html` §2: `platform_admin` → `platform_owner`; §1 conventions paragraph gains one
  sentence: an `Idempotency-Key` is scoped to the acting principal, replays for 24 hours, and a
  reuse with a different request is `409 IDEMPOTENCY_KEY_REUSED`.
- `API_IMPLEMENTATION_PLAN.md`: the self-check table row `| 27 pending | grep -c
  '^\*\*Status: pending\*\*' | **27** |` and its companion rows updated to the counts `grep`
  reports today (28 `done`, 0 `pending`); the verification-cycle records above it are history and
  are not edited.
- `SCHEMA_IMPLEMENTATION_PLAN.md`: every `Status: pending` (39 lines) → `Status: done`, with one
  sentence at the top of § 4 recording that `0008` shipped in `da03ece` and this flip was made in
  the write-back.
- `FINDINGS_IMPLEMENTATION_PLAN.md`: Tasks M4.2, M5.1, M5.2, M5.3 marked
  `**Status: superseded**` with one line each naming the P1 task that delivered them (M5.3 / M5.2 /
  M5.2 / M5.2 + M2.1); the § 2 register is unchanged (its answers were consumed, not overturned).
- `docs/backend-design.md` needs no change (it defers to the roadmap).

**Verification.**

- `grep -n "common.py\|platform_admin\|eleven packages\|twelve services\|ObjectRepoStore" design/roadmap.html design/api.html` returns nothing.
- `grep -c "Status: pending" SCHEMA_IMPLEMENTATION_PLAN.md` is 0; `grep -c "^\*\*Status: superseded\*\*" FINDINGS_IMPLEMENTATION_PLAN.md` is 4; `grep -c "^\*\*Status: pending\*\*" FINDINGS_IMPLEMENTATION_PLAN.md` is 14.
- `grep -n "Schema conformance" -A 1 design/roadmap.html` shows the `done` tag.
- `make docs` builds with `--strict`.
- Full gate (unchanged code; proves the tree is still green at the end of the plan).

**Dependencies.** M6.2 (the CI link must point at a workflow that exists and has run), M5.3.

**Status: done**

---

## 5. Risk register

| # | Risk | Symptom | Fallback decision point |
|---|---|---|---|
| 1 | **M5.2 exceeds the token budget.** It rewrites the repository, three endpoint modules, the scope helpers, the guards and six test modules in one task. | The implementation subagent stops mid-task; or the third verification attempt fails on a surface it did not finish. | Revert to the pre-task commit and split into **M5.2a** — the async surface on the dict-backed repository (every hierarchy repository method `async def`, the three `create_*`/`patch_*` handlers `async def`, scope helpers `async def`, `test_execution_model.py` table flipped, the two lock tests deleted; the document write wrapped in `await asyncify(...)`) — and **M5.2b** — the store swap, visibility parameter, claims and `page`. M5.2a is green on its own; nothing else in the plan changes. Record the split in this file before running it. |
| 2 | **The NFS `fsync` inside the transaction holds a row lock across a slow mount.** Design 1 contract 1 makes this deliberate. | Contract-test wall time for the write scenarios climbs; in production, `PATCH` latency tracks the mount's `fsync`. | Not a plan change: the trade is a stated contract. If M3.2's write scenarios exceed the suite's existing per-module time by more than 2×, report the numbers; do not move the document write outside the transaction. |
| 3 | **`COLLATE "C"` ordering sorts rather than scans** because the unique indexes are built under `en_US.utf8` (Receipt 2). | `EXPLAIN` shows `Sort` under `Seq Scan` for every window; irrelevant at P1 row counts. | Already handed to the `0009` schema track (decision 4). If M3.2 timing makes it visible, note it in the `0009` hand-off; ship no DDL here. |
| 4 | **`current_visibility` costs one `projects` scan per hierarchy request** (Design 2 › Cost). | Request latency grows linearly with the number of projects; visible first at T1 milestone 5's thousands. | Accept for P1 (the design's stated price). The fallback — caching `project_visibilities()` per process with invalidation on project create/patch — is a design change and goes to the next `/design-plan`, not into a task here. |
| 5 | **The `def`→`async def` flip regresses the execution-model guarantee** by leaving a blocking call on the event loop (the document write, `write_tag_once`). | `test_the_document_write_executes_off_the_event_loop_thread` (added in M5.2) fails, or a handler shows `def` in `EXPECTED_COROUTINE_FUNCTION`'s assertion. | The test is the tripwire; every filesystem call in the repository goes through `asyncify`. If a call cannot (a sync context manager), stop and report rather than running it on the loop. |
| 6 | **Hypothesis flakiness** — deadline exceeded on a loaded CI runner, or a health-check failure from an over-filtered strategy. | M6.1 passes locally and fails intermittently in the `unit` job. | `deadline=None` is set from the start; if a health check fires, rewrite the strategy to build valid values rather than `assume()` them away. Never `suppress_health_check` past the two named there. |
| 7 | **The transitional state after M4.2** (Postgres for RBAC/auth, hierarchy in memory, no opt-in). | A developer running `make api` between M4.2 and M5.2 has a persistent binding store and a forgetful hierarchy. | Bounded to two tasks in sequence on one branch; nothing is published or documented as shipped until M6.3. If the branch must pause between M4.2 and M5.2, say so in the commit message of M4.2. |

---

## 6. Definition of done

The plan is complete when every task above is `**Status: done**` — **fifteen tasks across six
milestones** — and all of the following hold on `main`:

1. The roadmap P1 gate holds verbatim against a Postgres-backed process: *"Create org → project →
   dataset via HTTP; generation docs and `CURRENT.json` at the exact documented paths; a release
   tag resolves to one revision and a second write of the same tag is `409 TAG_EXISTS`;
   slug-change attempts 409; API-key auth round-trip; a principal scoped to project A gets
   full-size pages with zero rows from B and no evidence of B in counts or cursors; import-linter
   green."* The release-tag clause is proven against a `dataset_revisions` row the contract test
   inserts (Design 1, contract 7).
2. `make lint` and `uv run pytest --cov=src/huron --cov-report=term-missing` are green at the
   coverage floor of 89 or higher; `uv run pytest -m contract` is green with four modules; `uv run
   lint-imports` reports 7 kept, 0 broken; `uv run python scripts/check_schema_map.py` exits 0 with
   `migrations/` untouched (`git diff --stat main -- migrations/` empty).
3. Every Design 1 contract 2–6 behavior and every Design 2 rule is pinned twice: in
   `tests/unit/test_hierarchy_store_memory.py` and in `tests/contract/test_hierarchy_store.py`,
   both running `tests/hierarchy_contract.py`; the two backends admit identical id sets under every
   `Visibility` in the shared fixture.
4. `grep -rn "store_backend\|_postgres_repository\|RevisionSeed\|_fingerprint" src` returns nothing;
   `grep -rn "visible_project_ids" src/huron/pkg/rbac src/huron/service` returns lines in
   `src/huron/pkg/rbac/__init__.py` only (the definition, its docstring mentions, and the one call
   inside `RoleBindingAuthorizer.visibility`).
5. `create_app(settings=...)` with no `stores` opens exactly one `asyncpg` pool and wires the six
   Postgres stores; `main.py` is unchanged from `main` and injects nothing.
6. `.github/workflows/ci.yml` exists and the `lint`, `unit`, `contract` and `integration` jobs are
   green on GitHub for the merge commit of this plan, with `contract` required.
7. `tests/unit/test_catalog_properties.py` runs Hypothesis over `paths`, `manifest` and `ids`.
8. `design/roadmap.html`, `design/api.html`, `API_IMPLEMENTATION_PLAN.md`,
   `SCHEMA_IMPLEMENTATION_PLAN.md` and `FINDINGS_IMPLEMENTATION_PLAN.md` carry the write-back of
   M6.3, and `make docs` builds with `--strict`.
9. No comment, docstring, test name or user-facing string in the tree references this plan, its
   milestones, the design document or the FINDINGS plan.

---

## Verification

**2026-09-03, pass 1.** Checked against the working tree (`main` at `2bcf604` plus uncommitted
changes), `P1_DESIGN.md` in full including the Status addendum, `pyproject.toml`, `Makefile`,
`migrations/versions/0001_foundations.py` and `0008_schema_conformance.py`, and every source and
test module the tasks name. Test-configuration claims in § 0 were re-derived from `pyproject.toml`,
not trusted: `addopts = "-m unit --strict-markers"`, markers `unit`/`contract`/`integration`/
`acceptance`, `asyncio_mode = "auto"`, `fail_under = 89`, mypy `strict = true` over
`files = ["src/huron"]` with `[tool.ty.src] include` mirroring it, `asyncpg.*`
`ignore_missing_imports`, seven `[[tool.importlinter.contracts]]`, `hypothesis` in the `dev`
group — all as the plan states. The DDL names the SQL depends on hold: `organizations.slug UNIQUE`,
`projects UNIQUE (organization_id, slug)`, `datasets UNIQUE (project_id, slug)` and
`releases UNIQUE (dataset_id, tag)` are unnamed constraints whose PostgreSQL default names are
exactly `organizations_slug_key`, `projects_organization_id_slug_key`,
`datasets_project_id_slug_key`, `releases_dataset_id_tag_key`; `releases_revision_dataset_fk` is
added by `0008:170`; `idempotency_records` is `PRIMARY KEY (principal, key)` with
`request_sha256`, `status_code`, `response jsonb`, `created_at`, `expires_at`. Coverage in both
directions holds (every Design 1 contract 1–9, Design 2 contract 1–4, Design 3 contract, deletion
row and absorbed FINDINGS behavior maps to a task with a test; every task cites a heading that
exists and says what the task claims), the dependency graph has no cycle or forward reference, and
fifteen `#### Task` headings carry fifteen `**Status: pending**` lines. Defects follow.

**Not `VERIFIED`** — 2 blocking, 9 non-blocking.

### Defects

1. **BLOCKING — M5.2 deletes `paginate`, which six non-hierarchy call sites and a contract test
   still need.** Where: M5.2 › "Modify — `routes/v1/endpoints/`" last bullet ("`pagination.py`:
   delete `paginate`"), M5.2 › Verification bullet 2 (`grep -rn "paginate\|_fingerprint" src tests`
   returns nothing), M5.1 ("`paginate` stays until M5.2 deletes its last caller"), § 6 item 4.
   What is wrong: `paginate` is called by `routes/v1/endpoints/bindings.py` (lines 113, 314, 346,
   378), `policies.py:99`, `service_accounts.py:137` and imported by
   `tests/contract/test_rbac_store.py:66` (used at `:952`). Those listings page whole `list[...]`
   results from `RbacStore.bindings_at` / `list_policies` / `list_service_accounts`, a port this
   plan does not change (§ 1 non-goals). Why it breaks: deleting the function leaves three endpoint
   modules and one contract module failing to import, so M5.2's own `uv run pytest -m contract` step
   and the full gate cannot pass, and the verification grep can never return nothing. The design's
   Deletions row (`pagination.py` / `paginate` — "replaced by `page` + `after_key`") was written as
   if the hierarchy were its only caller; it is a factual error in the design, which § 0 says to
   record in § 3 as a deliberate departure. Correction: (a) M5.2 keeps `paginate` for the
   `RbacStore`-backed listings and deletes only the four hierarchy call sites
   (`organizations.py:95`, `projects.py:111`, `datasets.py:148`, `datasets.py:290`);
   `tests/unit/test_api_pagination.py` keeps its four `paginate` tests; (b) replace M5.2's
   verification bullet with: `grep -n "paginate" src/huron/service/api/routes/v1/endpoints/organizations.py src/huron/service/api/routes/v1/endpoints/projects.py src/huron/service/api/routes/v1/endpoints/datasets.py` returns nothing and
   `grep -rn "_fingerprint" src tests` returns nothing; (c) M5.1: "`paginate` stays until M5.2
   deletes its last caller" → "`paginate` stays: the binding, policy and service-account listings
   page whole `RbacStore` results with it until that port grows windows"; the M5.1 module docstring
   rewrite describes both surfaces; (d) § 3 gains a third deliberate departure recording that the
   Design 1 Deletions row for `paginate` applies to the hierarchy call sites only; (e) § 6 item 4
   drops `paginate` from its grep (see defect 6).

2. **BLOCKING — `tests/hierarchy_contract.py` is placed in "the `tests` package root", but
   `tests/` is not a package.** Where: M2.1 › Create › third bullet; M3.2 › Create (imports it);
   § 0 rule 8. What is wrong: `tests/` has no `__init__.py` and no `conftest.py`, and
   `pyproject.toml` sets no `pythonpath`; `tests/unit/__init__.py` and `tests/contract/__init__.py`
   do exist. Under pytest's default `prepend` import mode the first ancestor without an
   `__init__.py` — `tests/` — is inserted on `sys.path` and the suites import as `unit.test_*` /
   `contract.test_*`. Why it breaks: an implementer following "the `tests` package" writes
   `from tests.hierarchy_contract import ...`, which raises `ModuleNotFoundError` in both suites;
   the working spelling (`from hierarchy_contract import ...`, resolved only because pytest put
   `tests/` on `sys.path`) is not stated anywhere and `ruff`'s isort classification of that bare
   module is undefined without a `known-first-party` entry. Correction: M2.1 adds an empty
   `tests/__init__.py` (one-line docstring, per rule 6) so the suites become
   `tests.unit.*` / `tests.contract.*` with the repository root on `sys.path`, and states the import
   both suites use: `from tests.hierarchy_contract import ...`. M2.1's verification gains
   `test -f tests/__init__.py` and `uv run pytest -m unit tests/unit/test_hierarchy_store_memory.py`
   (already present) is what proves the import resolves; M3.2's `uv run pytest -m contract` proves
   it for the second suite. (If the operator prefers not to add the package marker, the alternative
   is `[tool.pytest.ini_options] pythonpath = ["."]` — but that edits the gate's configuration,
   which § 0 forbids; the `__init__.py` is the change that touches nothing the gate owns.)

3. **Non-blocking — the M2.1 sentence on the in-memory `claim` branches is muddled** (known
   defect a). Where: M2.1 › Create › first bullet › `claim` / `remember` sub-bullet. What is wrong:
   "a live identical claim → its `Replay` (or, when `remember` has not run — impossible under the
   lock, kept as the honest branch — `IdempotencyKeyReused` is *not* raised; the claim is simply
   re-taken)" contradicts itself and describes a branch the lock makes unreachable. Why it breaks:
   an implementer cannot tell whether the unreachable branch must exist (and be covered at 100%,
   § 0) or not. Correction: replace the sub-bullet with — "`claim` / `remember` per contract 6 with
   the 24-hour TTL measured by `clock.now()`: a live claim with the same `request_sha256` returns
   the remembered `Replay`; a live claim with a different `request_sha256` raises
   `IdempotencyKeyReused`; an expired claim is taken over (its `request_sha256` and `expires_at`
   rewritten, its `Replay` cleared). A claim made inside a transaction that raises is discarded with
   the buffer. Because `transaction()` holds the lock, no second transaction can observe a claim
   whose `remember` has not yet run, so the store has no 'claimed, not remembered' branch to code."

4. **Non-blocking — § 2 binds D-11 to M5.3 only; the guard-ordering half is M5.2's** (known defect
   b). Where: § 2, inherited table, row D-11, column Binds. What is wrong: M5.2 › "Modify —
   `authorization/`" › `guards.py` is where `dataset_layer_writer` resolves `dataset_scope` before
   `ensure_layer_writable` (FINDINGS B11), and M5.3 owns only `_account_in_organization` (B10).
   Why it breaks: the register is the place an implementer checks which task consumes a decision;
   M5.2 would appear to have no D-11 obligation. Correction: Binds → "M5.2 (B11: `dataset_layer_writer`
   resolves the scope before the layer rule) and M5.3 (B10: `_account_in_organization` → 404)".

5. **Non-blocking — M6.2's YAML-validation verification line is over-complicated** (known defect
   c). Where: M6.2 › Verification › second bullet. What is wrong: it hedges on PyYAML's presence
   with an unexecutable fallback ("a `yq`-free conversion is unavailable"). Why it breaks: a
   verification step must be a command with a pass/fail outcome. Correction: replace with —
   `uv run --with pyyaml python -c "import yaml, pathlib; yaml.safe_load(pathlib.Path('.github/workflows/ci.yml').read_text())"`
   exits 0 (`--with` supplies PyYAML for that one invocation whether or not the dev group carries
   it).

6. **Non-blocking — § 6 item 4's grep for `visible_project_ids` also matches
   `SearchProjection.query`'s unrelated parameter** (known defect d). Where: § 6 › item 4. What is
   wrong: `grep -rn visible_project_ids src` today returns `src/huron/pkg/catalog/ports.py:209,
   214, 218` (the `query(self, query, visible_project_ids)` signature and its docstring), plus the
   definition at `pkg/rbac/__init__.py:353` and a docstring mention at `:312`; "only the definition
   and its one caller" is false before the plan starts and after it ends. Why it breaks: the
   definition of done cannot be satisfied as written. Correction: split the item —
   `grep -rn "store_backend\|_postgres_repository\|RevisionSeed\|_fingerprint" src` returns nothing;
   `grep -rn "visible_project_ids" src/huron/pkg/rbac src/huron/service` returns lines in
   `src/huron/pkg/rbac/__init__.py` only (the definition, its docstring mentions, and the one call
   inside `RoleBindingAuthorizer.visibility`). (`paginate` is removed from the grep per defect 1.)

7. **Non-blocking — M3.1's `grep -c 'COLLATE "C"'` counts lines, not occurrences.** Where: M3.1
   › Verification › third bullet ("is at least 12"). What is wrong: the design's SQL puts both
   operands of each keyset comparison on one line (`(o.slug COLLATE "C", o.id) > ($5 COLLATE "C",
   $6::uuid)`), so the four windows yield eight matching *lines* (two per window) while carrying
   twelve *occurrences*. Why it breaks: a store written exactly to the design fails the check.
   Correction: `grep -o 'COLLATE "C"' src/huron/service/api/stores/hierarchy.py | wc -l` is at least
   12.

8. **Non-blocking — M5.2's "all fourteen hierarchy read/write declarations" is one short of the
   task's own text.** Where: M5.2 › Verification › fourth bullet. What is wrong: the task says
   "the four `get_*`/`resolve_release` handlers **and `list_layers`** read with `visibility`", so
   `CurrentVisibility` is declared by 4 lists + 4 point reads + 3 patches + 3 child creates +
   `list_layers` = fifteen handlers. Correction: "fifteen" (or drop the number and list the handler
   names).

9. **Non-blocking — three counts in § 3 and M4.1 are wrong as facts.** Where: § 3 second bullet
   ("Fifty-seven `create_app(` call sites and forty-four `HierarchyRepository(` constructions");
   M4.1 ("fourteen modules; `grep -rln "repository=" tests/unit`"). Actual on the working tree:
   58 `create_app(`, 32 `HierarchyRepository(`, 11 modules passing `repository=`, and only three
   modules (`test_authorization_credentials.py`, `test_api_login.py`, `test_api_users.py`) read
   `repository.<auth store>` — not the five M4.1 lists. Why it matters: an implementer who stops at
   the stated number leaves sites unconverted or looks for ones that do not exist. Correction:
   replace each number with the grep that produces it ("every `create_app(` call site in
   `tests/unit/`", "every `HierarchyRepository(` construction", "every module `grep -rln
   "repository=" tests/unit` lists", "every module `grep -rln "repository\.\(api_keys\|credentials\|sessions\|principals\)" tests/unit` lists").

10. **Non-blocking — the "Working tree" prerequisite understates the uncommitted changes.** Where:
    § 0 › Environment prerequisites › Working tree. What is wrong: besides `app.py` and
    `test_api_app.py`, the working tree modifies `dev.env` (adds `HURON_DATA_ROOT=.data`),
    `src/huron/pkg/auth/oidc.py` and `tests/unit/test_auth_oidc.py` (discovery-document
    validation — the FINDINGS M2.1 work the design's addendum mentions), `FINDINGS_IMPLEMENTATION_PLAN.md`
    and `P1_DESIGN.md`. Why it matters: M4.2 edits `dev.env` and must keep the `HURON_DATA_ROOT`
    line; M6.3's FINDINGS status counts depend on that file's uncommitted state.
    Correction: extend the bullet to name all five files and add to M4.2: "delete only the
    `HURON_STORE_BACKEND` line; the uncommitted `HURON_DATA_ROOT=.data` line stays".

11. **Non-blocking — M6.2 "Python version pinned to the one `pyproject.toml` declares".** Where:
    M6.2 › Create. What is wrong: `pyproject.toml` declares `requires-python = ">=3.12"`, a floor,
    not a pin. Correction: "`python-version` taken from `.python-version` if the repository has one,
    else `3.12` — the floor `requires-python` declares; `setup-uv` reads `.python-version` on its
    own when present".

### Observations

Judgment calls, not defects; none blocks execution.

- **Contract 8 (store purity) has no positive pin.** M1.2 states it in docstrings and M2.1/M3.1
  implement it, but no test asserts "the store accepts an invalid slug without complaint". A
  negative property of this kind is reasonably left to code review; if a pin is wanted, one
  scenario in `tests/hierarchy_contract.py` inserting a record whose slug `validate_slug` would
  refuse, on both backends, would do it.
- **M5.1 moves the arity/UUID check out of the handler.** Design 1 › "`routes/v1/pagination.py`
  after" says `InvalidCursor` is raised "additionally by the handler" for a wrong-arity or non-UUID
  cursor; M5.1 puts that in `slug_cursor_key` / `tag_cursor_key`. Better factored, but it is a
  departure and § 3 does not list it — a one-line entry there would keep § 0's "the design wins"
  rule honest.
- **`-m contract` and `addopts`.** `addopts = "-m unit ..."` is prepended to the command line, so
  `uv run pytest -m contract` works because the later `-m` wins. The plan relies on this in six
  places without saying so; a half-sentence in § 0 would spare the next reader the check.
- **M2.2's `grep -c "^async def scenario_\|^async def seed_"` presumes the naming.** The task calls
  them "scenario functions"; say "named `scenario_<n>_<behavior>`" so the count is a real check.
- **M4.2's grep names `docker-compose.yml`.** If the file does not exist, `grep` exits 2 on it and
  the "returns nothing" check reads as a failure; confirm the file at execution time or drop it
  from the list.
- **M4.1's `runtime.authorizer.classifications`** presumes the attribute name
  `RoleBindingAuthorizer` exposes; confirm against `pkg/rbac/__init__.py:308` before writing the
  test.
- **M6.3's document counts** (SCHEMA plan "39 lines", FINDINGS "19 pending", API plan "27 pending"
  row) are snapshots that the uncommitted working tree may already have moved; the task already
  says to `grep -n` first, which is the right instruction.
- **M5.2's `grep -n "ensure_layer_writable" -B 3 guards.py`** also matches the import at
  `guards.py:21`; harmless, but `grep -n "ensure_layer_writable(" -B 3` targets the call alone.
- **The assignment's status check is phrased as `### Task`**; the plan's task headings are
  `#### Task` (four hashes). Counted by the heading actually used: 15 headings, 15 pending statuses.
- **Transitional milestone (M4→M5).** Checked: `ApiRuntime` gains the auth stores in M4.1 while
  `HierarchyRepository` loses them in the same task, so no attribute exists on both at once; the
  M4.1 lifespan builds `HierarchyRepository(PosixRawStore(...), classification_vocabulary=…,
  rbac_store=wired.rbac)` against the M4.1 constructor; M4.2's un-injected path opens the pool while
  the hierarchy stays dict-backed until M5.2, exactly the state § 3 and risk 7 describe. The tree
  compiles at every task boundary as far as static reading can tell.

### Fix pass — 2026-09-03

All eleven corrections and four observations applied; the Defects and Observations text above is
unchanged.

1. Applied — M5.2 › Modify (`paginate` kept, four hierarchy call sites deleted), M5.2 › Verification
   (split grep), M5.1 › Create (why `paginate` stays; docstring covers both surfaces), § 3 (third
   departure), § 6 item 4.
2. Applied — M2.1 › Create (`tests/__init__.py`, `from tests.hierarchy_contract import ...`),
   M2.1 › Verification (`test -f tests/__init__.py`), M3.2 › Create (import spelling).
3. Applied — M2.1 › Create › `claim` / `remember` sub-bullet replaced.
4. Applied — § 2 inherited table, D-11 › Binds.
5. Applied — M6.2 › Verification, YAML line (`uv run --with pyyaml`).
6. Applied — § 6 item 4 split; `paginate` dropped from it.
7. Applied — M3.1 › Verification (`grep -o ... | wc -l`).
8. Applied — M5.2 › Verification ("fifteen", with the breakdown).
9. Applied — § 3 second bullet and M4.1 › Modify: counts replaced by the greps that produce them.
10. Applied — § 0 › Working tree names all seven files; M4.2 keeps `HURON_DATA_ROOT=.data`.
11. Applied — M6.2 › Create (`python-version` from `.python-version`, else `3.12`).
- (i) Applied — § 3 fourth departure: M5.1 moves the arity/UUID check into `slug_cursor_key` /
  `tag_cursor_key`.
- (ii) Applied — § 0 first gate fact: `-m contract` overrides the `-m unit` in `addopts`.
- (iii) Applied — M2.2 › Verification states `scenario_<n>_<behavior>` / `seed_*` naming.
- (iv) Applied — M5.2 › Verification grep targets `ensure_layer_writable(`.
- Confirmed on the working tree, so no hedge was needed outside the Verification section:
  `.python-version` exists; `docker-compose.yml` exists and contains no `STORE_BACKEND` (M4.2's grep
  list keeps it); `RoleBindingAuthorizer.classifications` is a real attribute (M4.1 stands).

### Pass 2 — 2026-09-03

Re-checked only that the eleven corrections and four observations above landed where the fix
pass says they did (each was applied as an exact single-occurrence text replacement, then
confirmed by `grep` against the plan body). Task headings and statuses still agree:
`grep -c '^#### Task'` = 15, `grep -c '^\*\*Status: pending\*\*'` = 15. No new defects.

**VERIFIED.**
