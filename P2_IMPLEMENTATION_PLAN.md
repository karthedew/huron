# Huron — P2 Raw ingest & commit: implementation plan

Companion to [`P2_DESIGN.md`](P2_DESIGN.md), which is the authoritative specification for
everything below. This file sequences that design into milestones and mechanically verifiable
tasks; it never restates the design. Every task names the `P2_DESIGN.md` heading that specifies
it, and an implementer is expected to read that heading before editing.

This plan is executed by `/implement-markdown P2_IMPLEMENTATION_PLAN.md`. It is named apart from
[`P1_IMPLEMENTATION_PLAN.md`](P1_IMPLEMENTATION_PLAN.md) (shipped) and the older shipped plans it
sits beside.

---

## 0. How an implementer reads this plan

**Authority.** `P2_DESIGN.md` decides; this plan sequences. Where a task and the design appear to
disagree, the design wins and the disagreement is a plan defect to report, not a choice to make.
Where this plan deliberately departs from a sentence in the design, § 3 says so and why. Where two
designs collided, Design 7 › "Collisions resolved" is the arbiter and the task cites the collision
number.

**The task is the atomic unit, not the milestone.** `/implement-markdown` runs the complete
validation gate after every task. A task therefore must leave the tree compiling, the gate green,
and no half-migrated surface behind it. One task (M5.1) is deliberately large because its parts do
not split without a broken tree; § 5 gives its pre-approved fallback split.

**Resolved package path: `src/huron`** (`[tool.hatch.build.targets.wheel] packages = ["src/huron"]`).

**The validation gate**, run from the repository root after every task:

```text
make lint                                                # every static check, verbatim from Makefile
uv run pytest --cov=src/huron --cov-report=term-missing  # the unit suite with the coverage floor
```

`make lint` is, in order: `ruff check .`, `ruff format --check .`, `pydoclint src migrations
scripts`, `mypy`, `ty check`, `lint-imports`, `python scripts/check_schema_map.py`, `radon cc
src/huron --min C`, `radon mi src/huron --min B`, `complexipy src/huron
--max-complexity-allowed 15`, `pyscn check src/huron`. It is a superset of the ten commands
`.claude/commands/implement-markdown.md:39-48` lists. `make test` (`uv run pytest -m unit`) is the
fast local loop and does not substitute for the gate's second line.

Facts about this repository's gate that the tasks below depend on, checked against
`pyproject.toml`, `Makefile` and `ci.yml` rather than assumed:

- `[tool.pytest.ini_options] addopts = "-m unit --strict-markers"`. **A bare `uv run pytest`, and
  the gate's coverage line, run the `unit` marker only** and never execute `tests/contract/` or
  `tests/acceptance/`. Every task that changes a store, a migration or a contract scenario carries an
  explicit `uv run pytest -m contract …` step (M3.1, M3.2, M3.3, M9.2); the later `-m` overrides
  `addopts`. That run needs the container runtime named under **Environment prerequisites**.
- Registered markers: `unit`, `contract`, `integration`, `acceptance`. No marker is added (Design 7
  › "Suite placement and CI"). `asyncio_mode = "auto"`.
- `[tool.coverage.report] fail_under = 89` — a ratchet, raised in M9.1 and never lowered. Every
  file a task creates or touches is at 100% line coverage in the unit run, with one standing
  exception the P1 plan already established: the `PostgresHierarchyStore` half of
  `src/huron/service/api/stores/hierarchy.py` (and, after M9.2, `stores/ingest.py`) is exercised
  by `-m contract`, which the coverage line does not measure; the verifier takes the contract run's
  pass as that adapter's coverage evidence and holds every other touched file to 100%.
- `radon cc src/huron --min C` **must print nothing** (`implement-markdown.md:59`). On `main` it
  prints four items while `make lint` still exits 0, because radon's exit status ignores findings.
  M0.1 removes them before any P2 task runs (decision D-20).
- `mypy` runs `strict = true` over `src/huron` and `ty` mirrors it. `asyncpg.*` has
  `ignore_missing_imports`; rows are narrowed in `stores/rows.py`.
- `lint-imports` enforces seven contracts. This plan adds **no contract**; M5.1 and M6.1 each add one
  module (`huron.service.api.ingest`, `huron.service.api.revisions`) to the `source_modules` of the
  existing contract "the stores package is entered through its public surface" (Design 4 › "Facade
  decision"; Design 5 › module table). `uv run lint-imports` reports "7 kept, 0 broken" after every
  task.
- `scripts/check_schema_map.py` compares `migrations/schema.sql`'s `Reflects:` stamp with the
  Alembic head. M3.1 moves both in one task; every other task leaves them untouched.
- Migrations are raw SQL through `migrations._ddl.execute_sql` (see `migrations/env.py`'s
  docstring on why one statement per call); revision ids are the file stems (`0008_schema_conformance`).
- Skills: a task touching `src/huron/service` loads `.claude/skills/fastapi/`; a task touching
  `migrations/` or `src/huron/schema` loads `.claude/skills/postgresql-table-design/`. M3.1 and M4.1
  say so again in place.

**The route dump.** Several tasks verify the live route table with this script, referred to below
as *the route dump* (verified to run on `main`: 52 operations):

```text
uv run python - <<'EOF'
import tempfile
from huron.service.api.app import create_app
from huron.service.api.settings import ApiSettings, ClassificationValue
from tests.unit.support import memory_stores
settings = ApiSettings(env="development", auth_mode="dev-headers", data_root=tempfile.mkdtemp(),
    database_url="postgresql://unused", bootstrap_platform_owner="root",
    classification_vocabulary=[ClassificationValue(code="public", order=0, discoverable=True)])
paths = create_app(settings=settings, stores=memory_stores()).openapi()["paths"]
print(sum(len(ops) for ops in paths.values()), "operations")
for path, ops in sorted(paths.items()):
    for method in ops:
        print(method.upper(), path)
EOF
```

**Environment prerequisites — check these once, before M0.1.** If any is unmet, stop and report;
none may be worked around by skipping, weakening or deleting a gate step.

- **A container runtime** (Docker or Podman) reachable by `testcontainers`: every module under
  `tests/contract/` migrates a `postgres:16` container with the repository's own Alembic. A task
  whose mandatory contract step cannot run is not done.
- **An `x86_64` or `darwin` host** (`pyscn`'s dependency marker).
- **A clean mypy cache.** Clear `.mypy_cache/` once before M0.1 and on any `INTERNAL ERROR`.
- **Working tree.** `main` at `c5e35c7` plus: `design/roadmap.html` modified (Drift 6 already
  applied by hand — the P1 row reads `done`, the OpenAPI/client deliverable moved to T0-1; M10.1
  confirms and leaves it), `CLAUDE.md` modified (the `### Code Design` section), untracked
  `.agents/skills/oop-encapsulation/` and `P2_DESIGN.md`. None of these is any task's to edit or
  discard.
- **Disk.** M8.3's acceptance test writes 9 GiB when *run*; no task in this plan runs it (§ 4 M8.3
  verifies collection only). The nightly workflow's runner needs ≥ 10 GiB free.

**Rules that bind every task in this plan.**

1. **No code comment, docstring, test name, commit note or user-facing string may reference this
   plan, its milestones, task numbers, the design document or checklist mechanics.** Comments
   explain enduring code intent and are rare. A test is named for the behavior it pins.
2. **Clean sweep.** No backwards-compatibility shim, no deprecation alias, no re-export left
   behind, no TODO, no speculative abstraction, no partial migration, no suppressed lint. `# noqa`,
   `# type: ignore`, `# pragma: no cover`, `skip` and `xfail` may not be introduced. If the gate
   cannot be satisfied without one, stop and report.
3. **Deletions land with the change that makes them dead**, in the same task, and **by symbol,
   never by line**: the implementer locates a symbol with `grep -n`, never with a line number from
   this plan (design line numbers cited below are for reading the design, not for editing code).
4. **No task waits on a decision.** Every open question is a `D-n` in § 2 with a default; every task
   is written against the defaults. A task whose content would change under the other answer says
   so in one line and its milestone is marked *gated on D-n* in § 3.
5. **Every Google-style docstring matches its signature** (`ruff` `D` rules and `pydoclint`): every
   new module, class, function and method documents `Args`/`Returns`/`Yields`/`Raises` as
   `docs/getting-started/docstrings.md` requires; tests carry a one-line summary. Route docstrings
   put caller-facing prose before `\f` (`pyproject.toml:95`).
6. **Subagents run serially**, one task at a time, in the order below.
7. **The in-memory store is the reference implementation.** A store behavior is done when it is
   pinned against `InMemoryHierarchyStore` in `tests/unit/` *and* against migrated `postgres:16` in
   `tests/contract/`, through the shared scenarios in `tests/hierarchy_contract.py`.
8. **`CLAUDE.md` § Code Design applies as Designs 5 and 6 applied it**: documents are structural
   value objects with validating creational classmethods; workflows are behavioral service classes;
   the sweep runner is a lifecycle object owning one task.

---

## 1. Goal and non-goals

**Goal.** Make the roadmap's P2 row and T2 milestone 8 true over real HTTP. When this plan is
complete, `POST /datasets/{id}/ingest-sessions` reserves a gap-free revision number under the
dataset lock and returns an upload plan with hardlink dedup (Designs 1, 3); parts stream from the
request body into the staging envelope, hashed in flight, resumable per part (Designs 2, 4);
`/verify` links parent inodes and `/commit` runs the POSIX protocol — documents, seal, `fsync`,
one atomic rename, root seal — then one short PostgreSQL transaction that persists
`dataset_revisions`, flips the session, and writes the audit and outbox rows (Designs 2, 3, 5); a
committed revision is readable through `GET /revisions/{id}`, its manifest and its files under a
per-request `data.read@raw` check (Design 5); an expiry sweep in every replica releases abandoned
locks (Design 6); and every P2 and milestone-8 gate clause that belongs to P2 has a named test in a
suite CI runs (Design 7). `INDEX.json` is written best-effort at commit (D-12); download
capabilities are the authorized responses themselves (D-13).

**Non-goals.** Out of scope for every task below:

- P3: the staging sweeper (fraction guard, dry-run, deleting `.staging/{hex}`), the reconciler,
  importing an orphaned `COMMITTED` envelope as a row, regenerating or rebuilding `INDEX.json`, and
  freeing the lock of a session whose driver crashed in `COMMITTING` (D-1).
- P4: the search-projection consumer. P2 writes the `revision.committed` outbox row and nothing
  reads it.
- P5: schema-registry envelope validation (P2 validates against the packaged `metadata-v1.json` by
  file name) and project quota (`QuotaExceeded` keeps its class and no raise site).
- P8: STS-vended or signed download credentials; nothing is minted (Design 5 › "The download
  capability, defined").
- T0-1: the committed `openapi/v1.json` artifact and the generated clients.
- The frontend (`web/`), a `lakectl` command, and any new deployable.
- A purge or retention path (D-7), an absolute session TTL (D-4), widening
  `SERVICE_ACCOUNT_LAYERS` (D-9), a `metadata_draft` column (D-3), a persisted commit instant (D-5),
  re-planning inside `create` on `parent_superseded` (§ 3, departure 5), a sweep-disable switch
  (D-17), leader election for the sweep, and a `create_app(clock=)` parameter (Design 7 collision 8).
- Any new pytest marker or `import-linter` contract; any change to `radon`/`complexipy` thresholds.

---

## 2. Decision register

Every open question Designs 1–7 left, plus the two Drift 4 questions Design 5 carried and the P1
decision P2 inherited. **Every task is written against the "Default / answer" column.** *Resolved
downstream* means a later design adopted the recommendation and built on it; *open — default*
means no design consumed it and the plan proceeds on the recommendation.

| # | Source | Question (one line) | Default / answer, and why (from the design) | Status | Binds |
|---|---|---|---|---|---|
| D-1 | D1 OQ1 | A driver crashed in COMMITTING holds the dataset lock until P3 | Accept for P2; allow `COMMITTING → COMMITTING` re-entry against the current etag so a `/commit` retry recovers the post-rename case | resolved downstream — D4 OQ3 adopts the edge; D2 › Requirements on D3 and D3 › "Etag and the other fences" assume it; D7 › Techniques (the committing-seed test) uses it | M1.2, M5.3, M8.1, M10.1 |
| D-2 | D1 OQ2 | Multipart in P2 or whole-file only | Multipart at `PART_BYTES = 64 MiB`: milestone 8's gate is "without re-sending completed parts" | resolved downstream — D4 › "Upload transport: decided" | M1.1, M5.2 |
| D-3 | D1 OQ3 | Where the metadata document is submitted | With `/commit`, when `committed_by`/`committed_at` are known; no draft column, the create body carries no draft | resolved downstream — D4 route 8 `CommitIngestSession.metadata`; D5 `MetadataSubmission` | M5.1, M5.3, M10.1 |
| D-4 | D1 OQ4 | Absolute TTL beside the renewable 2 h | None; a heartbeating client is alive; drop "or absolute" from the §7 row | resolved downstream — D4 › "§7 disposition column" adopts the meaning cell | M10.1 |
| D-5 | D2 OQ1 | What a post-rename retry builds the revision row from | Read-back of `final/COMMITTED` and `metadata.json`; no persisted instant | resolved downstream — D3 ("a commit-instant column — no"), D4 commit step 5, D5 `revision_from_storage` | M4.1, M5.3 |
| D-6 | D2 OQ2 | Multipart mechanics (range writes, `finish_file`) | Same decision as D-2 | resolved downstream — D4 | M2.2, M5.2 |
| D-7 | D3 OQ1 | A purged revision's manifest can never be re-ingested | Keep the total unique index and the total `max`; no purge exists in P2 | open — default: keep both | none (no task changes either) |
| D-8 | D3 OQ2 | Keep `Idempotency-Key` on `/commit` given the state-based replay | Keep it; convention 4 and `api.html` require it; the digest check costs one row | resolved downstream — D4 › "`/commit`, end to end" | M5.3 |
| D-9 | D4 OQ1 | Service accounts and `raw` | Keep `ensure_layer_writable`; a service account may mint a dataset, never upload to raw; write back milestone 8's parenthetical | open — default: keep the rule | M5.1 (`test_intake_authorization_matrix` expects 403 `LAYER_WRITE_FORBIDDEN`), M10.1 |
| D-10 | D4 OQ2 | The derived dataset claim key on route 2 | `IdempotencyClaim(key=f"{key}/dataset")` for the dataset half | open — default: take it | M5.1 (route 2) |
| D-11 | D4 OQ3 | `COMMITTING → COMMITTING` re-entry | One edge added to `TRANSITIONS`; `begin_commit` accepts COMMITTING as a source | resolved downstream — the same decision as D-1 | M1.2 |
| D-12 | D5 OQ1 (Drift 4) | `INDEX.json` ownership | Option A: P2 writes it best-effort after the transaction (step 8), P3 owns regeneration | open — default: A; D7 matrix row 9 and D5's index test are built on A | M4.1, M5.3, M8.1, M10.1 |
| D-13 | D5 OQ2 (Drift 4) | Download capabilities in milestone 8's "Adds" | Option A: R1–R3 shipped; the capability is per-request `data.read@raw` | open — default: A; D7 gate rows P1–P4, P14, P15, M3 prove clauses through R3 | M6.1, M10.1 |
| D-14 | D5 OQ3 | `data_classification`'s source | Option A: server-sourced from `project.data_classification` | open — default: A | M4.1 (`compose` keyword), M5.3 |
| D-15 | D5 OQ4 | `format: date-time` is unenforced | Add the `format-nongpl` extra so `rfc3339-validator` enforces it; pin with one test | open — default: add it | M4.1 |
| D-16 | D6 OQ1 | Sweep interval default | 60 s (`layer-raw` §9's 15 min is the P3 deletion sweeper's) | open — default: 60 s | M7.1 |
| D-17 | D6 OQ2 | A per-replica sweep-disable value | No; `gt=0` | open — default: no | M7.1 |
| D-18 | D7 OQ1 | A nightly full-size 9 GiB job | Option A: separate `acceptance.yml` on a nightly schedule plus manual dispatch | open — default: A | M8.3 |
| D-19 | D7 OQ2 | What "full stack" means for the acceptance test | Option A: in-process `TestClient` + `memory_stores()` + the real `PosixRawStore` | open — default: A | M8.3 |
| D-20 | D7 OQ3 | The four pre-existing radon C-grade items | Option A: reduce them to B first | open — default: A | M0.1 |
| D-21 | D7 OQ4 | Dedup 500 in `unit` | Option A: keep it in `unit` at the gate's number | open — default: A | M8.2 |
| D-22 | D7 OQ5 | `stores/hierarchy.py` maintainability rank | Option A: if `radon mi -s` reads below 25 after M3, move the ingest methods to `stores/ingest.py` behind the same port | open — default: A | M3.3 (measures), M9.2 (acts) |
| D-23 | P1 decision 9 (inherited) | `record_revision` vs `metadata_sha256 NOT NULL` | `RevisionRecord.metadata_sha256` is the digest of `metadata.json`'s canonical bytes; no column change | resolved downstream — D1 › "`RevisionRecord` ↔ `dataset_revisions`", D3 › "Migration `0009`", D5 › documents table | M1.1, M4.1 |

Counts: 9 resolved downstream (D-1, D-2, D-3, D-4, D-5, D-6, D-8, D-11, D-23; D-1 and D-11 are
one decision seen from two designs, D-2 and D-6 likewise), 14 open with a default (D-7, D-9, D-10,
D-12 … D-22).

---

## 3. Milestone sequence

Eleven milestones, twenty-one tasks. Each milestone leaves the tree compiling and the gate green;
each task is sized for one implementation subagent within 30k–50k tokens except where marked.

| # | Milestone | Design | Tasks | Gated on | Ends with |
|---|---|---|---|---|---|
| M0 | Preflight: the radon baseline | D7 › "Suite placement and CI" › Baseline; OQ3 | M0.1 | D-20 | `uv run radon cc src/huron --min C` prints nothing |
| M1 | Domain | D1 | M1.1–M1.3 | — | the state machine, per-file ledger, upload plan and revision factories exist and are pinned by 25 unit and 5 property tests; `Metastore` is gone |
| M2 | Raw store | D2 | M2.1–M2.2 | — | `RawStore` lists every P2 method with one `PosixRawStore` implementation each; 40 primitive tests including the crash-injection helpers |
| M3 | Persistence | D3, D6 back-contracts on D3 | M3.1–M3.3 | D-22 (measure only) | migration `0009` applied and round-tripped; both adapters implement the port additions; scenarios 10–16 green on both backends; the race pinned on PostgreSQL |
| M4 | Documents | D5 (the `pkg/catalog` and `schema/` half) | M4.1 | D-14, D-15 | the four documents have schemas, value objects and round-trip tests |
| M5 | The ingest surface | D4, carrying D5's back-contracts (a)–(f), (h) | M5.1–M5.3 | D-9, D-10, D-12 | nine ingest operations live; the write-intent stub gone; a revision committed over HTTP |
| M6 | The read side | D5 (the `service/api` half) | M6.1 | D-13 | three revision operations live; 416 is a framework status |
| M7 | Expiry sweep | D6 | M7.1 | D-16, D-17 | every replica reaps lapsed leases; two settings; the lifespan owns one task |
| M8 | Gate suites | D7 | M8.1–M8.3 | D-18, D-19, D-21 | the crash matrix, dedup 1-of-500, the acceptance module and its nightly workflow |
| M9 | Ratchet and maintainability | D7 › Coverage ratchet; OQ5 | M9.1–M9.2 | D-22 | `fail_under` raised to the measured floor; `stores/hierarchy.py` at rank A with margin |
| M10 | Documentation write-back | Roadmap Drift 1, 2, 5, 7, 8, 9; D2, D4, D5, D6 write-back text | M10.1 | D-9, D-12, D-13 | every design and docs sentence the designs corrected is corrected, each proven by `grep` |

**Ordering rationale and deliberate departures from the shape the designs suggest.**

1. **M0 exists because the gate as written and the gate as run disagree** (D7 OQ3). Without it
   every P2 task's verification would fail on `radon cc` before its own change is judged.
2. **Interfaces before implementations, deletions as early as the tree allows.** M1 owns every
   domain shape; M2 the port and its one implementation; M3 the persistence port and both adapters.
   `Metastore` (zero consumers) goes in M1.2; `register_revision`, `seed_revision`,
   `_insert_revision`, the two private `_FakeClock`s and the `schema.sql` `[spec]` blocks go in
   M3; `staging_root`, `write_once`'s public name, `seal`'s root chmod and
   `create_staging(ingest_id)` go in M2.2; the write-intent stub goes in M5.1, the task that lands
   the route replacing it — deleting it earlier would orphan the four `test_api_rbac.py` probes
   Design 4 replaces with route-1 assertions.
3. **Design 1's `Metastore.begin_ingest` docstring is not rewritten in place.** Design 3 deletes
   `Metastore`; the replacement text lands on `HierarchyWriter.begin_ingest` in M3.3, with an
   `Args` entry for the `files` parameter Design 3's signature adds (Design 1 anticipates the move:
   "the text moves with it unchanged").
4. **Design 3's port additions split in two tasks by table, not by adapter.** Both adapters must
   implement an addition in the same task (`ApiStores.hierarchy: HierarchyStore` is a structural
   check `mypy`/`ty` run at `app.py`'s assignment), so M3.2 lands the revision/audit/outbox half on
   both and M3.3 the session/file half on both.
5. **`IngestService.create` does not re-plan on `DatasetLocked(reason="parent_superseded")`.**
   Design 3 › Requirements on D4 (b) says the facade *may* re-plan once; the plan declines: the
   condition needs another session to commit between the parent read and the lock, the error
   already carries `latest_revision_id`, and the client's retry is the re-plan. One fewer branch in
   the largest task.
6. **Design 4's two commit-crash tests are born as matrix rows.** Collision 3 folds them into
   `test_api_ingest_crash_matrix.py` rows 6 and 7; M5.3 creates that module with those two rows
   (their assertions verbatim) because `IngestService.commit`'s failure branches must be covered
   in the task that writes them; M8.1 completes rows 1–5, 8, 9.
7. **`design/api.html` §7 is edited by two code tasks, not only by M10.1.** `test_error_contract.py`
   asserts a bijection between §7 and `wire_error_codes()`, so the `REQUESTED_RANGE_NOT_SATISFIABLE`
   row must appear in M6.1 when 416 joins `FRAMEWORK_STATUSES`. The disposition column's definition
   and the five `reserved → live` flips are M10.1's, together with the `ast` raise-site test that
   pins them.
8. **`AuditEvent` and `LedgerEntry` are placed where each fits.** Design 3's module table files both
   under `records.py` ("stdlib fields only") while its port block declares them in `stores/ports.py`
   and `LedgerEntry.file` is a catalog type. `AuditEvent` (stdlib fields) goes to `records.py`;
   `LedgerEntry` goes to `stores/ports.py` beside `Replay`; both are exported by `stores/__init__.py`.
9. **`expire_lapsed`, `ExpiryReport` and `SWEEP_ACTOR` land in M7.1, not M5.1**, though Design 6
   places them in `service/api/ingest.py` beside `abort`. They share `abort`'s `_audit` helper; M7.1
   adds them to the facade M5 built.
10. **`test_create_refuses_a_manifest_the_dataset_already_holds` is written in M5.3**, not M5.1: it
    needs a commit over HTTP.
11. **Design 5's R1 (`GET /revisions/{id}`) is kept**: Design 7's M3 row and D5's tests use it.
12. **`rows.ingest_file(row)` returns `IngestFile`, not `LedgerEntry`** as Design 3's module table
    says. `rows.py` decodes one table's row into one catalog value, as its other decoders do;
    `LedgerEntry` pairs that value with `ingest_id`, which the store composes in `ingest_file()`
    from the same row. The port's `ingest_file(file_id) -> LedgerEntry` is unchanged.

---

## 4. Per-milestone task breakdown

### M0 — Preflight: the radon baseline

#### Task M0.1 — Reduce the four C-grade symbols to grade B

**Intent.** Make `uv run radon cc src/huron --min C` print nothing, so every later task's gate
failure is attributable to that task.

**Design.** `P2_DESIGN.md` › Design 7 › "Suite placement and CI" › `radon` / `complexipy` and
"Baseline"; Open question 3 (D-20). The gate rule: `implement-markdown.md:59, 64` — decompose along
domain boundaries, never extract arbitrary helpers.

**Modify.** The four symbols the receipt names (`## Receipts` below):

- `src/huron/service/api/settings.py` › `ApiSettings.refuse_unsafe_combinations` (and thereby the
  class): split into validators with one concern each — the authentication combinations
  (`dev-headers` outside development, `oidc` without a provider, an unsigned login flow) and the
  classification vocabulary (a `field_validator` on `classification_vocabulary` checking unique
  codes, unique orders, non-empty). Messages and `ValueError` behavior unchanged;
  `tests/unit/test_api_settings.py` pins them.
- `src/huron/pkg/rbac/__init__.py` › `Binding.covers`: the three per-level branches are one rule —
  "the binding's `scope_id` equals the scope's ancestor id at the binding's level, or the scope is
  at that level and names it" — expressed once over a level → ancestry-field mapping. `SYSTEM` and
  the `scope_id is None` refusal stay explicit. `tests/unit/test_rbac_*.py` and
  `tests/unit/test_authorization_decisions.py` pin the coverage semantics.
- `src/huron/pkg/catalog/paths.py` › `parse_revision_dir`: the nine-segment layout check and the
  `NNNNNN--hex` component check become two named checks; a single `re.fullmatch` over
  `^([0-9]{6})--([0-9a-f]{32})$` replaces the five-condition chain. `tests/unit/test_catalog_paths.py`
  and `test_catalog_properties.py` pin the inverse property.

No public signature changes; no new module.

**Verification.**

- `uv run radon cc src/huron --min C` prints nothing.
- `uv run pytest -m unit tests/unit/test_api_settings.py tests/unit/test_rbac_roles.py tests/unit/test_rbac_visibility.py tests/unit/test_authorization_decisions.py tests/unit/test_catalog_paths.py tests/unit/test_catalog_properties.py` passes.
- Full gate.

**Dependencies.** None.

**Status: done**

### M1 — Domain

#### Task M1.1 — The per-file ledger, the upload plan and the two record shapes

**Intent.** Give the domain the values the ingest routes and stores will be written against:
`IngestFile` with its part ledger, an upload plan that carries `part_count`, and `RevisionRecord`
/ `OutboxEvent` reconciled with their DDL column by column.

**Design.** `P2_DESIGN.md` › Design 1 › Target design › "Types and interfaces" (`LEASE_TTL`,
`PART_BYTES`, `FileState`, `IngestFile`, `UploadPlanEntry`, `compute_upload_plan`;
`:1099-1153`), "Per-file model" (`:1257-1273`), the `models.py` block (`:1196-1211`), the two
column tables (`:1290-1316`); Explicit contracts › the `IngestFile` and `compute_upload_plan`
invariants and "Error behaviour" (`:1369-1385`); Deletions (`UploadPlanEntry.parent_path`).

**Create / modify / delete.**

- `src/huron/pkg/catalog/ingest.py`: add `LEASE_TTL`, `PART_BYTES`, `FileState`, `IngestFile`
  (`received`, `part_received`, `completed`, `linked`) exactly as the block declares them;
  `UploadPlanEntry(file, action, part_count)` — delete `parent_path`; `compute_upload_plan(manifest,
  parent_manifest=None, *, part_bytes=PART_BYTES)` with the hash-algorithm guard and
  `part_count = max(1, ceil(size / part_bytes))` for UPLOAD, `0` for HARDLINK.
- `src/huron/pkg/catalog/models.py`: `RevisionRecord.metadata_sha256`; `OutboxEvent.id`,
  `OutboxEvent.created_at`; `RevisionRecord` docstring "as the metastore records it" → "as the
  catalog records it" (Design 5 › Deletions). `grep -rn "RevisionRecord(\|OutboxEvent(" src tests`
  and update every constructor (expected: none outside these modules).
- `src/huron/pkg/catalog/errors.py`: `IllegalIngestTransition` docstring widened to "the session,
  or one of its files, is not in a state that permits the operation"; `context` carries
  `{"state", "operation"}`; `ManifestMismatch` carries the per-file observation (`path`,
  `expected_size`, `observed_size`, `expected_sha256`, `observed_sha256`). No new code.
- `src/huron/pkg/catalog/__init__.py`: re-export `FileState`, `IngestFile`, `UploadAction`,
  `UploadPlanEntry`, `LEASE_TTL`, `PART_BYTES`; `__all__` and the module docstring updated.

**Tests.** Append to `tests/unit/test_catalog_ingest.py` (the three existing lease tests stay until
M1.2) the Design 1 › Tests rows `test_part_received_records_the_part_and_is_idempotent`,
`test_part_received_refuses_a_part_outside_the_plan_a_hardlink_file_and_a_complete_file`,
`test_completed_refuses_before_every_part_has_arrived`,
`test_completed_marks_a_matching_observation_complete`,
`test_completed_refuses_a_size_or_digest_mismatch_with_the_observation_in_context`,
`test_linked_completes_a_hardlink_file_and_refuses_an_upload_file`,
`test_a_zero_byte_file_is_one_part_that_completes_on_the_empty_digest`,
`test_upload_plan_links_only_entries_the_parent_holds_identically`,
`test_upload_plan_uploads_everything_without_a_parent_or_under_another_hash_algorithm`,
`test_upload_plan_part_counts_follow_the_part_size`,
`test_revision_committed_event_carries_the_revision_identity` is M1.2's.

**Verification.**

- `grep -rn "parent_path" src tests` returns nothing.
- `grep -n "PART_BYTES\|LEASE_TTL\|class FileState\|class IngestFile" src/huron/pkg/catalog/ingest.py` shows all four.
- `uv run pytest -m unit tests/unit/test_catalog_ingest.py tests/unit/test_catalog_properties.py` passes.
- Full gate.

**Dependencies.** M0.1.

**Status: done**

#### Task M1.2 — `IngestSession`'s named operations, `TRANSITIONS`, the revision factories; `Metastore` deleted

**Intent.** Replace the guard-bypassing `transition()`/`heartbeat()` pair with the named operations
the route table calls, make the transition table public data with the re-entry edge, and add the
two factories a commit publishes through; remove the consumer-less `Metastore` port.

**Design.** `P2_DESIGN.md` › Design 1 › Target design › the `IngestSession`, `revision_record`,
`revision_committed` block (`:1155-1192`), "Transition table, edge by edge" and its decisions
(`:1213-1255`), "Milestone-8 route → domain operation" (`:1275-1288`); Explicit contracts
(`:1361-1385`); Deletions (`:1428-1439`); D-1/D-11 (`TRANSITIONS[COMMITTING]` is
`{COMMITTING, COMMITTED, FAILED}` and `begin_commit` accepts COMMITTING as a source with the same
digest check and `etag + 1`, Design 4 › Open question 3). Design 3 › Target design › first
paragraph and Deletions (`Metastore` in full).

**Create / modify / delete.**

- `src/huron/pkg/catalog/ingest.py`: `IngestState` docstring; `_TRANSITIONS` → public
  `TRANSITIONS: Mapping[IngestState, frozenset[IngestState]]` with the re-entry edge;
  `IngestSession` gains `created_by`, `parent_revision_id`, and `open`, `renew`, `require`,
  `verify`, `begin_commit`, `commit`, `fail`, `abort`, `expire`; delete `transition`, `heartbeat`
  and every `now: datetime | None = None` fallback (`now` is always required); add
  `revision_record(...)` and `revision_committed(...)`.
- `src/huron/pkg/catalog/ports.py`: delete `class Metastore` and the imports only it used
  (`RevisionRecord`, `OutboxEvent`, `RevisionRef`, `IngestLease` — keep any `RawStore`/`Clock`
  still needs); the module docstring's prose mention of the metastore (its opening paragraph)
  dropped.
- `src/huron/pkg/catalog/__init__.py`: re-export `revision_record`, `revision_committed`,
  `TRANSITIONS`.
- `tests/unit/test_catalog_ingest.py`: delete the three `transition`/`heartbeat` tests; add the
  `_session(state, *, expires_in)` helper and the Design 1 › Tests rows
  `test_every_operation_from_every_state_matches_the_transition_table` (7 states × {`open`,
  `verify`, `begin_commit`, `commit`, `abort`, `fail`}; with D-11, `begin_commit` from COMMITTING
  succeeds), `test_a_committing_session_refuses_abort_and_expire`,
  `test_abort_and_fail_ignore_a_lapsed_lease`, `test_commit_ignores_a_lapsed_lease`,
  `test_forward_edges_refuse_a_lapsed_lease`,
  `test_terminal_sessions_refuse_with_the_transition_error_even_when_lapsed`,
  `test_renew_moves_the_expiry_and_leaves_the_etag`,
  `test_renew_refuses_at_the_expiry_instant_and_after_and_when_terminal`,
  `test_require_refuses_another_state_and_a_lapsed_lease`,
  `test_expire_aborts_a_lapsed_session_and_refuses_a_live_one`,
  `test_verify_refuses_while_any_file_is_pending`, `test_verify_refuses_an_empty_ledger`,
  `test_begin_commit_refuses_a_different_manifest_digest`,
  `test_revision_record_takes_every_column_from_the_session_and_manifest`,
  `test_revision_record_refuses_a_foreign_manifest_or_a_session_not_committing`,
  `test_revision_committed_event_carries_the_revision_identity`.

**Verification.**

- `grep -rn "Metastore\|\.transition(\|\.heartbeat(\|_TRANSITIONS" src tests` returns nothing.
- `grep -n "def open\|def renew\|def require\|def verify\|def begin_commit\|def commit\|def fail\|def abort\|def expire\|def revision_record\|def revision_committed" src/huron/pkg/catalog/ingest.py` shows eleven.
- `uv run pytest -m unit tests/unit/test_catalog_ingest.py` passes.
- Full gate.

**Dependencies.** M1.1.

**Status: done**

#### Task M1.3 — Property tests over the state machine and the upload plan

**Intent.** Pin the invariants the two example suites cannot enumerate.

**Design.** `P2_DESIGN.md` › Design 1 › Tests › the `test_catalog_properties.py` table
(`:1541-1549`); Design 7 › Fixtures › `_property` (unchanged).

**Modify.** `tests/unit/test_catalog_properties.py`: append
`test_ingest_operations_never_leave_the_transition_table`,
`test_ingest_file_parts_are_a_subset_of_the_plan_and_complete_only_when_full`,
`test_upload_plan_is_one_entry_per_file_in_manifest_order_and_links_only_identical_entries`,
`test_upload_plan_part_counts_cover_every_byte_exactly_once`,
`test_validate_manifest_refuses_every_non_nfc_path`, each under the module's `_property` settings.

**Verification.**

- `grep -c "^def test_ingest\|^def test_upload_plan\|^def test_validate_manifest_refuses_every_non_nfc" tests/unit/test_catalog_properties.py` is 5.
- `uv run pytest -m unit tests/unit/test_catalog_properties.py` passes.
- Full gate.

**Dependencies.** M1.2.

**Status: done**

### M2 — Raw store

#### Task M2.1 — `commit_envelope` seals the published root; crash-injection helpers; the commit tests

**Intent.** Close the seal-then-rename defect Design 2 proved (a `0o555` root cannot be renamed by a
non-root user) by sealing the root after the parent fsync, and give every later crash test one
injection technique.

**Design.** `P2_DESIGN.md` › Design 2 › Target design › the paragraph after the `PosixRawStore`
block (`commit.commit_envelope` gains one step; `:1698-1701`), "The commit sequence" steps 4–6 and
*Retry* (`:1758-1774`), "`CrossDeviceCommitError` surfacing"; Explicit contracts › the
`commit_envelope` row; Tests › the helper paragraph (`:1954-1960`) and the
`test_rawstore_commit.py` table (`:1962-1981`); Design 7 › Fixtures › `crash_on`, `fsync_log`
(generic over any `os` attribute — collision 7).

**Create / modify.**

- `src/huron/pkg/rawstore/commit.py` › `commit_envelope`: after `fsync_dir(final.parent)`,
  `os.chmod(final, 0o555)` then `fsync_dir(final)`; the completed-retry branch applies the same two
  calls before returning. Docstrings state the new post-condition (`final` is `0o555`). Nothing
  else in the module changes.
- `tests/unit/support.py`: `crash_on(monkeypatch, name, *, call=1, errno_=errno.EIO) -> list[object]`
  and `fsync_log(monkeypatch) -> list[Path]` with the signatures Design 7's fixture table gives.
- `tests/unit/test_rawstore_commit.py` (new, `pytest.mark.unit`, `tmp_path`): the sixteen tests of
  the design's table, by name.

**Verification.**

- `grep -n "chmod(final, 0o555)" src/huron/pkg/rawstore/commit.py` shows two sites (the publish
  path and the retry branch).
- `grep -n "^def crash_on\|^def fsync_log" tests/unit/support.py` shows both.
- `uv run pytest -m unit tests/unit/test_rawstore_commit.py tests/unit/test_rawstore_generation.py` passes.
- Full gate.

**Dependencies.** M0.1.

**Status: done**

#### Task M2.2 — The `RawStore` port and `PosixRawStore`'s streaming, document and commit contract

**Intent.** Make `RawStore` the one type the service tier programs against, with a streaming,
range-addressed `write_part`, durable documents, idempotent links, and a seal that leaves the
envelope root renameable.

**Design.** `P2_DESIGN.md` › Design 2 › Target design › "The port" (the code block is the
specification, `:1598-1649`), "`PosixRawStore` — changed and added methods" (`:1654-1696`),
"Typed consumers", "`write_part` input contract" (`:1709-1743`), "Hardlink-then-seal",
"Parent-manifest read-back", "Sync or async"; Explicit contracts table (`:1820-1834`) and
"Lifecycle assumptions"; Deletions (`:1870-1881`); Tests › `test_rawstore_store.py` (`:1983-2010`).

**Create / modify / delete.**

- `src/huron/pkg/catalog/ports.py` › `RawStore`: rewritten to the block — `root` (property),
  `initialize`, `create_staging(staging)`, `write_part(staging_payload, rel_path, chunks, *, offset,
  length) -> str`, `finish_file`, `discard_file`, `hardlink_from_parent`, `read_document`,
  `write_document`, `atomic_replace(path, payload)`, `seal`, `commit_envelope`, `write_tag_once`,
  `write_generation`; every docstring states the row of the contracts table. Delete
  `create_staging(ingest_id)`.
- `src/huron/pkg/rawstore/store.py`: `PartLengthMismatch(ValueError)`; `create_staging(staging)`
  taking the path from `paths.staging_dir` (`ValueError` unless `staging.parent == root/.staging`;
  fsyncs of `.staging`, the envelope and `payload/`); `write_part` per the block (`O_WRONLY | O_CREAT`
  `0o600`, no `O_EXCL`/`O_TRUNC`, `_pwrite_all`, digest over the bytes written, `PartLengthMismatch`
  on short/long, fsync of the file and every directory from the file's parent up to
  `staging_payload`); `finish_file`; `discard_file`; `hardlink_from_parent` with the `samefile`
  no-op and unlink-then-link; `read_document`; `write_document` (`ValueError` unless `name` is one
  component and not `""`, `.`, `..`, `payload`; `atomic_replace(..., mode=0o444)` — the
  implementation keeps its `mode` keyword; the port declares the two-argument form);
  `_make_private_dirs`; `_pwrite_all`; `seal` without the final `root.chmod(0o555)`. Delete
  `staging_root` (use `self.root / ".staging"` where `initialize` needs it), rename `write_once` →
  `_write_once`, rewrite the class docstring (no "written at most once" claim).
- `src/huron/pkg/rawstore/__init__.py`: export `PartLengthMismatch`.
- `src/huron/service/api/repository.py` › `HierarchyRepository.__init__`: `raw_store: RawStore`
  (imported from `huron.pkg.catalog.ports`); drop the `PosixRawStore` import if unused; the class
  docstring names the port. `app.py` keeps constructing `PosixRawStore(settings.data_root)`.
- `tests/unit/test_rawstore_store.py` (new): the twenty-four tests of the design's table, by name,
  using `crash_on`/`fsync_log` from `tests/unit/support.py`.

**Verification.**

- `grep -rn "staging_root\|def write_once\|\.write_once(" src tests` returns nothing;
  `grep -n "def _write_once" src/huron/pkg/rawstore/store.py` shows one.
- `grep -n "root.chmod(0o555)" src/huron/pkg/rawstore/store.py` returns nothing.
- `grep -n "raw_store: RawStore" src/huron/service/api/repository.py` shows one; `grep -c "PosixRawStore" src/huron/service/api/repository.py` is 0.
- `grep -n "    def " src/huron/pkg/catalog/ports.py | sed -n '/class RawStore/,/class /p'` — or an equivalent read — shows the fourteen port members in the block's order.
- `uv run mypy` and `uv run ty check` pass (the `@property root` Protocol member against `PosixRawStore.root: Path`).
- `uv run pytest -m unit tests/unit/test_rawstore_store.py tests/unit/test_rawstore_commit.py tests/unit/test_rawstore_generation.py tests/unit/test_repository_hierarchy.py tests/unit/test_execution_model.py` passes.
- Full gate.

**Dependencies.** M2.1.

**Status: done**

### M3 — Persistence

#### Task M3.1 — Migration `0009_ingest_ledger`, the schema map, the contract pins

**Intent.** Give the ledger its declared vocabulary, its action-tied part count, the parent citation
and the three indexes the allocator, the FK check and the sweep need, and move the map's stamp.

**Design.** `P2_DESIGN.md` › Design 3 › Target design › "Migration `0009_ingest_ledger`" (the
SQL block is the specification, `:2247-2315`, including every `schema.sql` line named there);
Design 6 › Requirements on Design 3 (a) — `CREATE INDEX ingest_sessions_lapsing ON ingest_sessions
(expires_at) WHERE state IN ('PREPARING','UPLOADING','VERIFYING')` with its `DROP INDEX` and
`schema.sql` line (`:3977-3986`); Design 1 › Deletions (the `[spec]` block on `ingest_files.state`);
Design 3 › Deletions (`schema.sql:87-89` and `:160-162`); Tests › `test_catalog_store.py`
(`:2468-2478`). Load `.claude/skills/postgresql-table-design/` first.

**Create / modify / delete.**

- `migrations/versions/0009_ingest_ledger.py`: `revision = "0009_ingest_ledger"`,
  `down_revision = "0008_schema_conformance"`; `upgrade()`/`downgrade()` with the design's DDL plus
  the lapsing index, each statement through `migrations._ddl.execute_sql` as `0008` does; a module
  docstring in `0008`'s style explaining each block (the parent citation as a composite FK; why the
  two partial unique indexes serve neither the FK check nor the sweep; `ADD COLUMN … NOT NULL`
  without a default because the table has no writer in `src/` at `0008` — the one raw-SQL writer
  is the contract helper below, which this task updates).
- `migrations/schema.sql`: `-- Reflects: 0009_ingest_ledger`; `ingest_sessions` gains
  `parent_revision_id`, the `[db]` FK, the three index annotations (`ingest_sessions_parent_revision`,
  `ingest_sessions_dataset`, `ingest_sessions_lapsing`); `ingest_files` gains `part_count` with its
  CHECK annotation and the state vocabulary `[db]` line replacing the `[spec]` block;
  `dataset_revisions`'s `[spec] linear, gap-free` block becomes the `[app]` line the design gives.
- `tests/contract/test_catalog_store.py`: `_assert_ingest_files_state_vocabulary`,
  `_assert_ingest_files_part_count_matches_action`,
  `_assert_a_parent_revision_belongs_to_the_sessions_dataset`,
  `_assert_ingest_sessions_dataset_index_serves_a_bare_dataset_lookup`, and
  `_assert_ingest_sessions_lapsing_index_serves_the_sweep_predicate` (Design 6's "prove it the way
  Design 3's receipts did": `EXPLAIN` under `SET enable_seqscan = off` names
  `ingest_sessions_lapsing`); `_assert_round_trip` extended so `downgrade -1` from `0009` drops
  `parent_revision_id`, `part_count` and the three indexes and `upgrade head` restores them;
  `_insert_ingest_file` (the module's raw-SQL `ingest_files` writer) supplies `part_count` — `1`,
  the value the action-tied CHECK requires for its `'upload'` row — and any `state` literal it
  writes is in the new vocabulary, so every existing test that calls it stays green under the
  `NOT NULL` add; the module docstring's stale "has no Postgres-backed store of its own yet"
  sentence removed.

**Verification.**

- `uv run python scripts/check_schema_map.py` exits 0.
- `grep -c "\[spec\]" migrations/schema.sql` is 3 (the `jobs` and `reconciliation_findings` blocks
  and the header definition at `:23` remain; the two P2 blocks are gone).
- `grep -n "ingest_sessions_lapsing\|ingest_sessions_dataset\|ingest_sessions_parent_revision\|ingest_files_state_vocabulary\|ingest_files_part_count_matches_action" migrations/schema.sql migrations/versions/0009_ingest_ledger.py` shows each name in both files.
- `uv run pytest -m contract tests/contract/test_catalog_store.py` passes (the container migrates
  to head and round-trips `0009`).
- A manual round trip against a scratch container, recorded in the report:
  `podman run -d --name p2-pg -e POSTGRES_USER=huron -e POSTGRES_PASSWORD=huron -e POSTGRES_DB=huron -p 127.0.0.1:55432:5432 postgres:16`
  (or `docker run`), then `HURON_DATABASE_URL=postgresql://huron:huron@127.0.0.1:55432/huron uv run alembic upgrade head`,
  `… alembic downgrade -1`, `… alembic upgrade head`, then `podman rm -f p2-pg`.
- Full gate (`pydoclint src migrations scripts` covers the revision's docstrings).

**Dependencies.** M0.1.

**Status: done**

#### Task M3.2 — Revisions, audit and outbox on the port and both adapters; `register_revision` retired; one `FakeClock`

**Intent.** Make the revision row, the audit row and the outbox row writable through the hierarchy
writer on both backends, seed every existing scenario through that writer instead of a test-only
method and raw SQL, and give the in-memory store the injectable clock the sweep tests need.

**Design.** `P2_DESIGN.md` › Design 3 › Target design › "Port convention", "Module layout"
(`:2084-2093`), "The port additions" (`AuditEvent`, `LedgerEntry`, `Replay.kind`,
`insert_revision`, `insert_audit_event`, `insert_outbox_event`, `revision`,
`latest_committed_revision`; `:2095-2148`), "SQL-level semantics" rows `insert_revision`,
`insert_audit_event`/`insert_outbox_event`, `revision`, `latest_committed_revision`
(`:2160-2164`), "`DUPLICATE_CONTENT`"; Explicit contracts; Deletions (`register_revision` and its
call sites, `_revisions` re-keyed, `seed_revision`, `_insert_revision`); Requirements on Design 7
(`_HIERARCHY_TABLES` +4). Design 6 › Requirements on Design 3 (b) (`InMemoryHierarchyStore(*,
clock=None)`). Design 4 › Module layout (`_SystemClock` → `SystemClock`, exported). Design 7 ›
Fixtures (`FakeClock`, `memory_stores(*, clock=None)`); Collisions 1 and 6. § 3 departure 8
(placement of the two values).

**Create / modify / delete.**

- `src/huron/service/api/records.py`: `AuditEvent` (`@dataclass(slots=True)`, as the module's other
  records are declared; fields per the block).
- `src/huron/service/api/stores/ports.py`: `LedgerEntry(ingest_id, file: IngestFile)`;
  `Replay.kind` gains `"ingest_session"`, `"revision"`; `HierarchyWriter` +3 and `HierarchyStore` +2
  with the block's docstrings; `HierarchyStore`'s first docstring line widens to "The hierarchy's
  durable state and the ingest workflow that extends it".
- `src/huron/service/api/stores/rows.py`: `revision_record(row) -> RevisionRecord`.
- `src/huron/service/api/stores/hierarchy.py`: `_SystemClock` → `SystemClock`;
  `InMemoryHierarchyStore.__init__(self, *, clock: Clock | None = None)` defaulting to
  `SystemClock()`; `_revisions: dict[UUID, RevisionRecord]` (and the same in `_TransactionBuffer`),
  `revision_ref(dataset_id, number)` deriving the ref; `_audit`, `_outbox` lists; the three writer
  methods and two reads on both adapters (`DuplicateContent` from the manifest-key `UniqueViolation`
  by constraint name; `revision_number`/`revision_path` violations propagate). Delete
  `register_revision`.
- `src/huron/service/api/stores/__init__.py`: export `AuditEvent`, `LedgerEntry`, `SystemClock`.
- `tests/hierarchy_contract.py`: a `committed_revision(dataset_id, number, *, revision_id=None,
  manifest_sha256=None) -> RevisionRecord` builder; every scenario loses its `seed_revision`
  parameter and `del seed_revision`, and seeds through `async with store.transaction() as w: await
  w.insert_revision(...)`.
- `tests/unit/support.py`: `FakeClock` (`now()`, `advance(delta)`, `set(instant)`);
  `memory_stores(*, clock: Clock | None = None)` threading it to the hierarchy store.
- `tests/unit/test_hierarchy_store_memory.py`, `tests/contract/test_hierarchy_store.py`: delete
  both private `_FakeClock`s and import `FakeClock` from `tests.unit.support`; every
  `register_revision` call site (`grep -rn register_revision tests`, currently in
  `test_api_catalog_hierarchy.py`, `test_repository_hierarchy.py`, `test_hierarchy_store_memory.py`,
  `test_hierarchy_store.py`) becomes an `insert_revision` through the store's transaction; delete
  `_insert_revision`; the scenario runner calls `scenario(store)`; `_HIERARCHY_TABLES` gains
  `ingest_files`, `ingest_sessions`, `audit_events`, `outbox_events`.
- Tests: `tests/unit/test_stores_ports.py` — the exports list gains the three names;
  `tests/unit/test_stores_rows.py` — `revision_record` decodes a full row;
  `tests/unit/test_hierarchy_store_memory.py` — `test_insert_revision_refuses_a_manifest_the_dataset_already_holds`,
  `test_revision_and_latest_committed_revision_read_the_inserted_row`,
  `test_a_transaction_that_raises_after_insert_revision_leaves_no_revision_audit_or_outbox_row`,
  `test_the_in_memory_store_reads_its_clock_when_none_is_injected` (the default is `SystemClock`).

**Verification.**

- `grep -rn "register_revision\|seed_revision\|_insert_revision\|_FakeClock\|_SystemClock" src tests` returns nothing.
- `grep -n "^class FakeClock\|clock: Clock | None = None" tests/unit/support.py` shows both.
- `uv run pytest -m unit tests/unit/test_stores_ports.py tests/unit/test_stores_rows.py tests/unit/test_hierarchy_store_memory.py tests/unit/test_api_catalog_hierarchy.py tests/unit/test_repository_hierarchy.py` passes.
- `uv run pytest -m contract tests/contract/test_hierarchy_store.py` passes (the nine scenarios now seed through the port on PostgreSQL).
- Full gate.

**Dependencies.** M1.2, M3.1.

**Status: done**

#### Task M3.3 — Sessions and files on the port and both adapters; scenarios 10–16; the race

**Intent.** Land the allocator under the `datasets` row lock, the etag/lease/parts fences and the
sweep's list on both backends, prove them with one scenario set, and pin the race on PostgreSQL.

**Design.** `P2_DESIGN.md` › Design 3 › Target design › "The port additions" (`begin_ingest`,
`update_ingest_session`, `renew_ingest_session`, `expire_ingest_session`, `update_ingest_file`,
`ingest_session`, `ingest_files`, `ingest_file`, `lapsed_ingest_sessions`), "SQL-level semantics"
(the seven-statement `begin_ingest` and every other row, `:2150-2165`), "The allocator and the
race", "The expired-session rule", "Etag and the other fences", "`ingest_files` rows"; Explicit
contracts (`:2319-2335`); Tests (`:2450-2467`); Design 1 › the replacement `begin_ingest`
docstring (`:1322-1357`, plus an `Args` entry for `files`); Design 7 › Fixtures
(`_INGEST_SCENARIOS` with signature `(store, clock)`, `_wait_until_a_backend_blocks_on`);
Collision 5; Techniques › "Racing `begin_ingest`" (`:4255-4269`); Open question 5 (D-22).

**Create / modify.**

- `src/huron/service/api/stores/ports.py`: the five writer methods and four reads with the block's
  docstrings; `HierarchyWriter.begin_ingest` carries Design 1's replacement docstring.
- `src/huron/service/api/stores/rows.py`: `ingest_session(row) -> IngestSession`,
  `ingest_file(row) -> IngestFile` (the `LedgerEntry` is composed by the store from `ingest_id`).
- `src/huron/service/api/stores/hierarchy.py`: both adapters. In memory: `_sessions`, `_files`
  dicts (and in `_TransactionBuffer`), each SQL predicate as its one-line dict equivalent under the
  store's `asyncio.Lock`, `expires_at = clock.now() + LEASE_TTL`. Postgres: the statements as
  Design 3 lists them, except that every `uuid7()` inside a `VALUES` list is an `ids.uuid7()`
  generated in Python and bound as a parameter, as the existing store does — PostgreSQL 16 has no
  `uuid7()` SQL function; `unnest` for the file rows, `DatasetLocked`/`DuplicateContent`/`ResourceNotFound`/
  `PreconditionFailed`/`IngestSessionExpired` exactly as the refusal column maps them,
  `completed_parts` as sorted JSON arrays in both predicate and value.
- `tests/hierarchy_contract.py`: `_INGEST_SCENARIOS` — `scenario_10_begin_ingest_reserves_and_locks`
  … `scenario_16_a_hundred_sequential_ingests_number_gap_free` with signature `(store, clock)`,
  asserting exactly the design's rows; the file builder `planned_files(manifest) -> tuple[IngestFile, ...]`.
- `tests/contract/test_hierarchy_store.py`: a second loop after `_SCENARIOS` running
  `_INGEST_SCENARIOS` with `FakeClock` and `_reset_hierarchy_tables` between;
  `_wait_until_a_backend_blocks_staking_the_claim` generalised to
  `_wait_until_a_backend_blocks_on(pool, *, query_fragment, timeout=5.0)` (the existing caller
  passes `"INSERT INTO idempotency_records"`);
  `test_two_concurrent_begin_ingest_calls_serialize_on_the_dataset_row` per Design 7's technique.
- `tests/unit/test_hierarchy_store_memory.py`: seven `async def test_…` functions, one per
  scenario, each over `InMemoryHierarchyStore(clock=FakeClock(...))`, named for the scenario's
  behavior (`test_begin_ingest_reserves_and_locks`, …, `test_a_hundred_sequential_ingests_number_gap_free`).
- `tests/unit/test_stores_rows.py`: `ingest_session`, `ingest_file` decode full rows.

**Verification.**

- `grep -n "numbers are not reused" src` returns nothing; `grep -n "returns to the pool\|returns to the$" src/huron/service/api/stores/ports.py` shows at least one (the phrase may wrap).
- `grep -c "^async def scenario_1[0-6]_" tests/hierarchy_contract.py` is 7.
- `uv run pytest -m unit tests/unit/test_hierarchy_store_memory.py tests/unit/test_stores_rows.py` passes.
- `uv run pytest -m contract tests/contract/test_hierarchy_store.py` passes, including the race test.
- `uv run radon mi -s src/huron/service/api/stores/hierarchy.py` — record the reading in the report.
  It must be ≥ 20 for the gate; if it is below 20 this task performs D-22's split now (the ingest
  methods of both adapters move to `src/huron/service/api/stores/ingest.py` as mixin bases the two
  store classes inherit, behind the same port, exported through `stores/__init__.py` only); if
  between 20 and 25, M9.2 performs it; if ≥ 25, M9.2 records and does nothing.
- Full gate.

**Dependencies.** M3.2.

**Status: pending**

### M4 — Documents

#### Task M4.1 — `committed-v1`, `revision-index-v1`, `pkg/catalog/documents.py`, enforced `date-time`

**Intent.** Give every document a commit leaves on disk a schema, a validating value object, a
canonical byte form and a decoder that refuses anything not its own canonical form; make the
`format: date-time` assertion real.

**Design.** `P2_DESIGN.md` › Design 5 › Target design › "The four documents" (`:3172-3185`),
"`metadata-v1` required members, sourced" (`:3187-3205`; `data_classification` as a `compose`
keyword — D-14), "Schema fragments" (`:3207-3251`), "`pkg/catalog/documents.py`" (the block is
the specification, `:3253-3343`), "Design 4's five named callables, mapped", "`CONTRACT_MISMATCH`:
decided — taken"; Explicit contracts › "Document invariants" (`:3489-3497`); Deletions (the
`RevisionRecord` docstring — done in M1.1; confirm); Open question 4 (D-15); Tests ›
`test_catalog_documents.py`, `test_schema_committed.py`, `test_schema_revision_index.py`
(`:3655-3679`). Load `.claude/skills/postgresql-table-design/` is not needed; load nothing extra.

**Create / modify.**

- `src/huron/schema/documents/committed-v1.json`, `revision-index-v1.json`: the two fragments
  completed to full Draft 2020-12 documents (`$schema`, `$id`, `type: object`,
  `additionalProperties: false`, the listed `required` and `properties`), in the packaged
  documents' house style.
- `src/huron/schema/__init__.py`: only if `load_schema` needs the new file names registered; its
  docstring notes that `date-time` is enforced by `rfc3339-validator`.
- `pyproject.toml` › `[project].dependencies`: `"jsonschema"` → `"jsonschema[format-nongpl]"`;
  `uv lock` (the `uv.lock` change ships with the task).
- `src/huron/pkg/catalog/documents.py` (new): `METADATA_SCHEMA`, `COMMITTED_SCHEMA`,
  `INDEX_SCHEMA`, `SERVER_METADATA_MEMBERS`, `manifest_bytes`, `decode_manifest`,
  `MetadataDocument` (`compose`, `decode`, `as_dict`, `canonical`, `sha256`, `manifest_sha256`,
  `committed_by`, `committed_at`), `CommitRecord` (`of`, `decode`, `as_dict`, `canonical`,
  `revision_record(*, revision_path)`), `IndexEntry`, `RevisionIndex` (`empty`, `decode`,
  `including`, `as_dict`, `canonical`), `revision_from_storage(committed, metadata, *, session,
  revision_path)`, and the two private instant helpers (`Z`-suffixed render, tz-aware parse).
  `ContractMismatch` is raised in exactly one place (`MetadataDocument.compose`).
- `src/huron/pkg/catalog/__init__.py`: re-export the seven public names.
- Tests: `tests/unit/test_catalog_documents.py` (thirteen tests of the design's table, by name);
  `tests/unit/test_schema_committed.py` and `tests/unit/test_schema_revision_index.py` following
  `test_schema_snapshot_provenance.py` (`test_the_schema_itself_is_valid`,
  `test_every_required_member_is_required`, `test_unknown_members_are_refused`,
  `test_digests_and_ids_must_be_well_formed`, and for the index
  `test_the_directory_name_must_be_a_revision_directory`), plus in `test_schema_committed.py`
  `test_a_malformed_instant_is_refused` (D-15: `committed_at: "yesterday"` → refused).

Under D-15 (B): the `format-nongpl` extra, the `uv.lock` change and
`test_a_malformed_instant_is_refused` are dropped, and `schema/__init__.py`'s docstring says
`date-time` is documentary until a validator is installed; nothing else in the task changes.

**Verification.**

- `grep -n "format-nongpl" pyproject.toml` shows one; `uv run python -c "import rfc3339_validator"` exits 0.
- `grep -rn "raise ContractMismatch" src/huron` shows exactly one site, in `pkg/catalog/documents.py`.
- `ls src/huron/schema/documents/ | grep -c "committed-v1.json\|revision-index-v1.json"` is 2.
- `uv run pytest -m unit tests/unit/test_catalog_documents.py tests/unit/test_schema_committed.py tests/unit/test_schema_revision_index.py tests/unit/test_schema_snapshot_provenance.py` passes.
- `uv run lint-imports` reports 7 kept (`pkg/catalog` → `huron.schema` is the permitted direction).
- Full gate.

**Dependencies.** M1.2.

**Status: pending**

### M5 — The ingest surface

Load `.claude/skills/fastapi/` before every task in this milestone.

#### Task M5.1 — Sessions on the wire: schema twins, the facade, guards, routes 1–4 and 9, wiring; the write-intent stub deleted

**Intent.** Put a session on the wire end to end — create (on an existing raw dataset or minting one
at intake), read, heartbeat, abort — over one facade that never holds a store transaction across
file I/O, reached through the runtime like the repository is; and remove the unpersisted
write-intent stub the guard replaces. **This is the plan's one oversized task** (§ 5, risk 5 gives
the fallback split).

**Design.** `P2_DESIGN.md` › Design 4 › Target design › "Module layout" (`:2528-2542`), "Route
table" rows 1, 2, 3, 4, 9 (`:2549-2559`), "Error codes by route" › *Guards*, *Routes 1–2*, *Route
4*, *Route 9* (`:2561-2610`), "Schema twin" (`:2616-2667`), "The facade" (`SessionLedger`,
`IngestService.__init__`, `create`, `ledger`, `entry`, `heartbeat`, `abort`; `:2669-2702`),
"Guards" (`:2704-2737`), "Intake authorization matrix" (D-9), "Route 2's two claims" (D-10),
"Facade decision", "The write-intent stub: deleted"; Explicit contracts › "Invariants the surface
holds", "Lifecycle", *Audit rows*; Deletions (`:2934-2950`); Design 3 › Requirements on Design 4
(a), (e), (f); Design 5 › Requirements on Design 4 (a) (`MetadataSubmission` as the commit body's
type — the twin is created here, consumed in M5.3); Design 2 › Requirements on Design 4 (e)
(`asyncify` sites); Design 7 › Fixtures › `IngestClient`, Collision 2, 4 (`PART_BYTES` read at
call time from `huron.pkg.catalog.ingest`); § 3 departure 5 (no re-plan).

**Create / modify / delete.**

- `src/huron/service/api/routes/v1/schema/ingest_sessions.py` (new): `ManifestFile`,
  `CreateIngestSession`, `NewDataset`, `CreateIngestSessionInProject`, `CommitIngestSession`
  (`metadata: MetadataSubmission`), `IngestFileView`, `IngestSessionView`.
- `src/huron/service/api/routes/v1/schema/revisions.py` (new): `MetadataSubmission`
  (`extra="forbid"`), `RevisionView` — Design 5 › "`RevisionView` and `MetadataSubmission`".
- `src/huron/service/api/ingest.py` (new): `SessionLedger` with its read-only properties;
  `IngestService(raw_store: RawStore, hierarchy: HierarchyStore, *, clock: Clock)` with `create`,
  `ledger`, `entry`, `heartbeat`, `abort(ledger, *, actor, forced)`, and the `_audit` helper
  (`records.jsonable` for payload values). `create` is a sequence of three private methods, each
  one domain boundary, so the public method carries no branch of its own and every function
  stays under the gate's ceilings: `_plan(dataset, files) -> (Manifest, RevisionRecord | None,
  tuple[UploadPlanEntry, ...])` (validate → `entry_layer` check → parent
  `latest_committed_revision` + `read_document` + `decode_manifest` →
  `compute_upload_plan(..., part_bytes=ingest.PART_BYTES)`); `_reserve(dataset, manifest, parent,
  plan, *, created_by, claim) -> IngestSession` (tx A: `claim` → `begin_ingest` →
  `insert_audit_event(ingest.started)` → `remember`; a `Replay` short-circuits to `ledger`);
  `_open_envelope(session, manifest) -> SessionLedger` (`create_staging` →
  `write_document("manifest.json", manifest_bytes(manifest))` → tx B
  `update_ingest_session(session.open(now), expected_etag=1)`; on any raise, `_fail(session,
  actor)` — one transaction persisting `session.fail()` plus `ingest.failed`, shared with M5.3's
  commit — runs before the error propagates).
- `src/huron/service/api/authorization/guards.py`: `IngestDrive`, `_raw_write`,
  `dataset_raw_writer`, `project_intake`, `session_overseer`, `session_owner`; delete `LayerWrite`,
  `dataset_layer_writer`. `authorization/__init__.py`: exports follow.
- `src/huron/service/api/runtime.py`: `ApiRuntime.ingest: IngestService`; `api_ingest`;
  `Ingest = Annotated[IngestService, Depends(api_ingest)]`. `ApiStores` unchanged.
- `src/huron/service/api/app.py`: the lifespan builds `clock = SystemClock()`, passes it to
  `_postgres_stores(pool, clock)` and `IngestService(raw_store, wired.hierarchy, clock=clock)` over
  the one `PosixRawStore` instance shared with `HierarchyRepository`; publishes `ingest` on the runtime.
- `src/huron/service/api/routes/v1/endpoints/ingest_sessions.py` (new): routers
  `dataset_ingest_sessions` (`/datasets/{dataset_id}/ingest-sessions`), `project_ingest_sessions`
  (`/projects/{project_id}/ingest-sessions`), `router` (`/ingest-sessions`), tags `["ingest-sessions"]`;
  handlers `create_dataset_ingest_session`, `create_project_ingest_session`, `get_ingest_session`,
  `heartbeat_ingest_session`, `abort_ingest_session`; every session-view response sets
  `ETag: "{etag}"`; `responses={…}` through `problem_response`.
- `src/huron/service/api/routes/v1/__init__.py`: include the three routers after `datasets.router`.
- `pyproject.toml` › `[tool.importlinter]` stores contract `source_modules` += `"huron.service.api.ingest"`.
- Delete: `routes/v1/endpoints/datasets.py` › `create_write_intent` and its imports and the module
  docstring's write-intent sentence; `routes/v1/schema/datasets.py` › `WriteIntent`;
  `tests/unit/test_api_catalog_hierarchy.py`'s write-intent test; `tests/unit/test_api_rbac.py`'s
  four write-intent probes (replaced below); `tests/unit/test_execution_model.py`'s
  `"create_write_intent": True`; `tests/unit/test_authorization_guards.py`'s `dataset_layer_writer`
  /`LayerWrite` tests (replaced by `dataset_raw_writer`/`project_intake`/`session_owner`/
  `session_overseer` tests of the same guarantees: 404 before 403, kind rule before binding rule).
- `tests/ingest_client.py` (new, top level): `IngestClient` with `developer_dataset`, `create`,
  `get`, `heartbeat`, `abort`, `put_count`; module functions `manifest_file`, `declared_file`.
  (`put_part`, `complete`, `upload`, `verify`, `commit`, `upload_revision`, `download`,
  `sparse_file`, `zeros_sha256` arrive with their routes in M5.2, M5.3, M6.1, M8.3.)
- Tests (`tests/unit/test_api_ingest_sessions.py`, new; `client`/`stores` fixtures as
  `test_api_catalog_hierarchy.py:71-89`): `test_create_returns_the_plan_and_locks_the_dataset`,
  `test_create_replays_under_the_same_key_and_refuses_a_changed_manifest`,
  `test_create_refuses_every_manifest_rule_with_its_documented_code`,
  `test_create_refuses_a_dataset_whose_entry_layer_is_not_raw`,
  `test_create_in_project_mints_the_dataset_then_opens_the_session`,
  `test_intake_authorization_matrix`, `test_get_shows_progress_and_the_etag`,
  `test_heartbeat_moves_the_lease_and_not_the_etag`,
  `test_abort_releases_the_lock_for_the_owner_and_a_project_admin`,
  `test_every_session_route_hides_an_invisible_dataset` (routes 3, 4, 9 now; extended in M5.2 and
  M5.3), `test_create_plans_hardlinks_against_the_latest_committed_revision` (a revision seeded
  through the store with its `manifest.json` written under `revision_path` via `manifest_bytes`;
  the plan shows `hardlink`/`part_count 0` and `parent_revision_id`),
  `test_a_staging_failure_at_create_fails_the_session_and_frees_the_number` (`crash_on("mkdir")`
  or a store double → the session is FAILED, `ingest.failed` audited, a second create succeeds).
  `tests/unit/test_api_rbac.py`: `bob` → route 1 201; `alice` → 403 `FORBIDDEN`; the service
  account → 403 `LAYER_WRITE_FORBIDDEN` while `list_layers` still reports `caller_may.write` for
  `silver`/`gold` only. `tests/unit/test_execution_model.py`: `EXPECTED_COROUTINE_FUNCTION` gains
  the five handler names (56 operations).

Under the non-default answers: D-9 (widen `SERVICE_ACCOUNT_LAYERS`) flips the matrix's service
account rows to 201; D-10 (no dataset claim) removes the derived key and the "retry with the same
key → same session" assertion of the in-project test.

**Verification.**

- `grep -rn "write_intent\|WriteIntent\|dataset_layer_writer\|LayerWrite\b" src tests` returns nothing.
- `grep -n "huron.service.api.ingest" pyproject.toml` shows one; `uv run lint-imports` reports 7 kept.
- The route dump prints `56 operations` and contains `POST /api/v1/datasets/{dataset_id}/ingest-sessions`,
  `POST /api/v1/projects/{project_id}/ingest-sessions`, `GET /api/v1/ingest-sessions/{session_id}`,
  `POST /api/v1/ingest-sessions/{session_id}/heartbeat`, `POST /api/v1/ingest-sessions/{session_id}/abort`,
  and no path containing `write-intents`.
- `uv run pytest -m unit tests/unit/test_api_ingest_sessions.py tests/unit/test_api_rbac.py tests/unit/test_authorization_guards.py tests/unit/test_execution_model.py tests/unit/test_api_catalog_hierarchy.py tests/unit/test_api_app.py` passes.
- Full gate.

**Dependencies.** M2.2, M3.3, M4.1.

**Status: pending**

#### Task M5.2 — Upload transport: routes 5 and 6, the body bridge, `ClientDisconnect`, resume

**Intent.** Stream each part from the request body into its range of the payload file on a worker
thread with a two-chunk memory bound, record it in the ledger only after it is durable, and make
resume a rule the client derives from the session view.

**Design.** `P2_DESIGN.md` › Design 4 › Route table rows 5, 6; "Error codes by route" › *Route 5*,
*Route 6* (`:2584-2596`); "The facade" › `receive_part`, `complete_file`; "Guards" › `UploadTarget`,
`upload_owner`; "Upload transport: decided" (`:2756-2789`: range, resumability, the `syncify`
bridge, memory bound, execution-model rule); "Module layout" › `problems.py` seventh handler;
Deletions › `problems.py:98` "six handlers", `test_error_contract.py:5` "all six"; Design 2 ›
Requirements on Design 4 (a)–(e); Design 3 › Requirements on Design 4 (c); Design 7 › "Suite
placement and CI" (a) — `IngestService.upload_part` as three functions: the pre-read refusal that
returns `(offset, length)` or raises, the stream observation, the ledger update with its re-read
retry; Techniques › "Resume — only incomplete files re-sent" (P10); Tests (`:3064-3071`);
Design 2 › Tests › `test_execution_model.py` (`:2012-2014`).

**Create / modify.**

- `src/huron/service/api/ingest.py`: `receive_part(ledger, file, part, chunks, *, content_length)`
  decomposed as Design 7 requires; `complete_file(ledger, file)`; both renew the lease after the
  ledger write; `discard_file` on `ManifestMismatch`; `update_ingest_file` re-read and re-applied on
  `PreconditionFailed`. `PartLengthMismatch` → `ManifestMismatch` with the design's context. The
  part's `offset`/`length` derive from `part` and `huron.pkg.catalog.ingest.PART_BYTES` read at call
  time — never from a module-level import of the value (Design 7 › Collisions resolved › 4) — so
  the unit tests' `monkeypatch` of `PART_BYTES` takes effect.
- `src/huron/service/api/routes/v1/endpoints/ingest_sessions.py`: router `transfer`
  (`/transfer`, tags `["transfer"]`); `upload_part` (`PUT /uploads/{file_id}/parts/{part}`; a
  required integer `Content-Length` header parameter; the body pulled through a generator calling
  `syncify(request.stream().__aiter__().__anext__)()` per chunk inside the `asyncify`'d call —
  skipping empty chunks, ending on `StopAsyncIteration`), `complete_upload`
  (`POST /uploads/{file_id}/complete`). `routes/v1/__init__.py` includes `transfer`.
- `src/huron/service/api/authorization/guards.py`: `UploadTarget`, `upload_owner`; exports follow.
- `src/huron/service/api/problems.py`: the `ClientDisconnect` handler (400 `BAD_REQUEST`); the
  three handler-count docstrings say seven — `problems.py:3` ("registers six handlers"),
  `problems.py:98` ("Register the six handlers"), `tests/unit/test_error_contract.py:5` ("all six
  error handlers"), `tests/unit/test_api_problems.py:3` ("Covers the six handlers"); the
  `PathRuleViolation` helper's unrelated sentence at `problems.py:261` is not a handler count and
  stays. `tests/unit/test_api_problems.py` gains the disconnect handler's shape test if the module
  enumerates handlers.
- `tests/ingest_client.py`: `put_part(file_id, part, body, *, content_length=None)`,
  `complete(file_id)`, `upload(session, source) -> int` (every missing part of every `PENDING`
  upload file; increments `put_count`).
- Tests (`tests/unit/test_api_ingest_sessions.py`; multipart tests
  `monkeypatch.setattr(huron.pkg.catalog.ingest, "PART_BYTES", 4)`):
  `test_a_single_part_upload_completes_the_file`,
  `test_a_multipart_upload_resumes_without_resending_completed_parts`,
  `test_an_upload_refuses_a_content_length_that_disagrees_with_the_plan_before_reading`,
  `test_a_short_body_is_a_manifest_mismatch_and_leaves_the_part_pending`,
  `test_a_mismatched_single_part_file_is_discarded_and_back_to_pending`,
  `test_a_mismatched_multipart_file_is_discarded_at_complete`,
  `test_upload_refusals_happen_before_the_body_is_read`,
  `test_a_client_disconnect_mid_part_answers_400_and_keeps_the_ledger` (a raw ASGI drive with
  `http.disconnect`), `test_a_new_client_resumes_from_the_session_view_and_re_sends_only_pending_files`
  (P10), and `test_every_session_route_hides_an_invisible_dataset` extended to routes 5–6.
  `tests/unit/test_execution_model.py`: +`upload_part`, +`complete_upload` (58);
  `test_the_upload_route_s_write_part_executes_off_the_event_loop_thread`.

**Verification.**

- The route dump prints `58 operations` and contains `PUT /api/v1/transfer/uploads/{file_id}/parts/{part}` and `POST /api/v1/transfer/uploads/{file_id}/complete`.
- `grep -n "syncify" src/huron/service/api/routes/v1/endpoints/ingest_sessions.py` shows the bridge; `grep -rn "cancellable" src/huron` returns nothing.
- `grep -n "ClientDisconnect" src/huron/service/api/problems.py` shows the handler; `grep -n "six handlers\|all six\|registers six" src/huron/service/api/problems.py tests/unit/test_error_contract.py tests/unit/test_api_problems.py` returns nothing.
- `uv run complexipy src/huron --max-complexity-allowed 15` and `uv run radon cc src/huron --min C` are clean (the three-function decomposition).
- `uv run pytest -m unit tests/unit/test_api_ingest_sessions.py tests/unit/test_execution_model.py tests/unit/test_api_problems.py tests/unit/test_error_contract.py` passes.
- Full gate.

**Dependencies.** M5.1.

**Status: pending**

#### Task M5.3 — Verify and commit: routes 7 and 8, the six on-disk steps, the six-statement transaction, `INDEX.json`, the first two crash rows

**Intent.** Link the parent's inodes at `/verify` and publish a revision at `/commit` — documents,
seal, marker, one rename, one short transaction, a best-effort index — with a replay that returns
the same revision and a retry that converges from either side of the rename.

**Design.** `P2_DESIGN.md` › Design 4 › Route table rows 7, 8; "Error codes by route" › *Route 7*,
*Route 8* (`:2597-2608`); "The facade" › `verify`, `commit`; "`/commit`, end to end" (`:2791-2825`,
steps 1–7 and the `Idempotency-Key` digest — D-8); Design 3 › "The commit transaction"
(`:2218-2239`), Requirements on Design 4 (d); Design 2 › "The commit sequence"; Design 5 ›
Requirements on Design 4 (a) (the claim digest over `MetadataSubmission.model_dump(exclude_none=True)`),
(b) (`record` built before disk step 3), (c) (`Visibility.ALL` reads and
`project.data_classification` — D-14), (d), (e) (`ValueError` → 500 and `fail()` when the marker is
absent), (f) (step 8 — D-12), (h); Design 5 › "The four documents" table (the write primitive and
step per document); Design 1 › route table rows `/verify`, `/commit`; Design 7 › Collision 3 (the
two D4 crash tests as matrix rows 6, 7), Techniques › "The crash matrix" rows 6, 7 (`:4228-4229`);
Tests: Design 4 (`:3072-3078`), Design 5 (`:3698-3702`).

**Create / modify.**

- `src/huron/service/api/ingest.py`: `verify(ledger)` (parent read once, per PENDING HARDLINK file
  `hardlink_from_parent` → `linked()` → `update_ingest_file`, then `session.verify` →
  `update_ingest_session`); `commit(ledger, *, expected_etag, manifest_sha256, metadata,
  committed_by, claim)` implementing Design 4's steps 1–7 and Design 5's step 8. Like `create`,
  `commit` is a sequence of private methods, one per boundary, so no function crosses the gate's
  ceilings: step 1's COMMITTED short-circuit and step 2's etag check stay in `commit`;
  `_compose_commit(ledger, metadata, committed_by, now) -> (Manifest, MetadataDocument)` (step 3:
  `read_document(staging/manifest.json)` → `decode_manifest` → identity check → the three
  `Visibility.ALL` reads → `MetadataDocument.compose(..., data_classification=project's)`);
  `_fence_commit(session, manifest_sha256, now) -> IngestSession` (step 4: `begin_commit` in one
  transaction, VERIFYING or the COMMITTING re-entry); `_publish_envelope(committing, manifest,
  doc, *, committed_by, now) -> RevisionRecord` (step 5: `revision_record(...)` built first, then
  either the six disk steps with `CommitRecord.of(record).canonical` as the marker, or — when
  `final/COMMITTED` was already present — `revision_from_storage`; the `OSError`/`ValueError`
  fork is one `except` that calls `_fail` when the marker is absent and re-raises either way);
  `_record_revision(committing, record, claim, now) -> RevisionRecord` (step 6: the
  six-statement transaction with `revision_committed(record, event_id=uuid7(),
  created_at=now)`; a `Replay` returns `revision(id)`); `_write_index(record)` (step 8:
  `read_document(index_path)` → `RevisionIndex.empty` on `FileNotFoundError` →
  `including(record)` → `atomic_replace`, inside a `try` that logs and swallows every exception).
  The nine `asyncify` sites of Design 4 are all present after this task.
- `src/huron/service/api/routes/v1/endpoints/ingest_sessions.py`: `verify_ingest_session`,
  `commit_ingest_session` (`If-Match` through `IfMatchHeader`/`expected_version()` from
  `routes/v1/preconditions.py`;
  `Idempotency-Key`; body `CommitIngestSession`; 201 `RevisionView`).
- `tests/ingest_client.py`: `verify`, `commit(session_id, etag, metadata, *, key=None)`,
  `upload_revision(dataset_id, files) -> dict`.
- Tests (`tests/unit/test_api_ingest_sessions.py`): `test_verify_links_parent_files_and_moves_to_verifying`,
  `test_verify_refuses_while_a_file_is_pending`, `test_commit_publishes_the_revision_and_its_events`
  (documents asserted through `decode_manifest`, `MetadataDocument.decode`, `CommitRecord.decode` —
  D5 (h)), `test_commit_requires_the_current_etag_and_the_declared_digest`,
  `test_a_replayed_commit_returns_the_same_revision`,
  `test_create_refuses_a_manifest_the_dataset_already_holds`, and
  `test_every_session_route_hides_an_invisible_dataset` extended to routes 7–8.
  `tests/unit/test_api_revisions.py` (new; extended in M6.1):
  `test_commit_writes_the_three_documents_and_they_agree`,
  `test_commit_refuses_a_metadata_submission_the_schema_rejects_before_any_edge`,
  `test_metadata_carries_the_project_s_classification_and_the_hierarchy_refs`,
  `test_a_commit_writes_the_index_and_a_second_commit_extends_it`.
  `tests/unit/test_api_ingest_crash_matrix.py` (new): the parametrized
  `test_a_crash_after_each_commit_step_leaves_the_named_state_and_the_retry_converges` with rows 6
  (`crash_on("rename")` → 500, FAILED, `ingest.failed`, the number re-taken) and 7
  (`crash_on("fsync", call=call_of(final.parent))` after a rehearsal under `fsync_log` → 500,
  COMMITTING, retry with the new etag → 201, one revision, `committed_at`/`metadata_sha256`/
  `committed_by` equal to `COMMITTED`'s) as its first two rows, with the rehearsal helper
  `call_of(path)` Design 7 describes. Row 7 absorbs Design 5's
  `test_a_commit_retry_past_the_rename_rebuilds_the_record_from_the_marker` (collision 3: that
  name is not written; its assertions are row 7's last clause), so the P9 trace in § 6 resolves
  to row 7.
  `tests/unit/test_execution_model.py`: +`verify_ingest_session`, +`commit_ingest_session` (60);
  `test_the_commit_route_s_envelope_publication_executes_off_the_event_loop_thread`.

Under the non-default answers: D-12 (B) removes step 8 and the index test; D-14 (B) moves
`data_classification` into `MetadataSubmission` and out of `compose`'s keywords.

**Verification.**

- The route dump prints `60 operations` and contains `POST /api/v1/ingest-sessions/{session_id}/verify` and `POST /api/v1/ingest-sessions/{session_id}/commit`.
- `grep -c "asyncify(" src/huron/service/api/ingest.py` is at least 9.
- `uv run pytest -m unit tests/unit/test_api_ingest_sessions.py tests/unit/test_api_revisions.py tests/unit/test_api_ingest_crash_matrix.py tests/unit/test_execution_model.py tests/unit/test_api_catalog_hierarchy.py` passes (the last proves `GET /datasets/{id}/releases` can tag revision 1 of a committed session where the design's commit test asserts it).
- Full gate.

**Dependencies.** M5.2.

**Status: pending**

### M6 — The read side

#### Task M6.1 — `RevisionService`, `revision_raw_reader`, routes R1–R3, 416 as a framework status

**Intent.** Make a committed revision addressable and its bytes downloadable through the API under a
per-request `data.read@raw` check, serving only what the stored manifest lists, with `Range`
support for a resumable download.

**Design.** `P2_DESIGN.md` › Design 5 › Target design › "Module layout" (`:3150-3163`),
"`RevisionService`" (`:3383-3408`), "Guard" (`:3410-3430`), "The download capability, defined"
(D-13), "Route table" (`:3449-3453`), "Streaming response type: `FileResponse`" (`:3461-3476`);
Explicit contracts › "Read-side invariants", "Lifecycle"; Requirements on Design 4 (g); Deletions
› the `design/api.html` §7 `REQUESTED_RANGE_NOT_SATISFIABLE` row (code-coupled — § 3 departure 7);
Tests › `test_api_revisions.py` download rows (`:3688-3697`), `test_execution_model.py`,
`test_error_contract.py` (`:3704-3708`). Load `.claude/skills/fastapi/`.

**Create / modify.**

- `src/huron/service/api/revisions.py` (new): `PayloadFile`, `RevisionService(raw_store, hierarchy)`
  with `revision`, `manifest_file`, `payload_file` exactly as the block orders their checks
  (`validate_manifest_path` before any storage access; location composed from the validated entry;
  `stat` through `asyncify`; `st_size` mismatch → `RuntimeError`).
- `src/huron/service/api/authorization/guards.py`: `RevisionRead`, `revision_raw_reader`; exports.
- `src/huron/service/api/runtime.py`: `ApiRuntime.revisions`; `api_revisions`;
  `Revisions = Annotated[RevisionService, Depends(api_revisions)]`. `app.py`: the lifespan builds
  `RevisionService(raw_store, wired.hierarchy)` over the shared store after the repository.
- `src/huron/service/api/routes/v1/endpoints/revisions.py` (new): `router` (`/revisions`, tags
  `["revisions"]`); `get_revision`, `get_revision_manifest`, `get_revision_file`
  (`{path:path}`), each returning `FileResponse(..., stat_result=stat, headers={"ETag": …})` as
  the route table specifies. `routes/v1/__init__.py` includes it after `datasets.router`.
- `src/huron/service/api/problems.py`: `FRAMEWORK_STATUSES = (400, 404, 405, 416)`.
- `design/api.html` §7: the row `REQUESTED_RANGE_NOT_SATISFIABLE · 416 · live · a Range header
  names bytes outside the file; answered by the file response with an empty body and
  Content-Range, not a problem document` (the bijection test requires it in this task).
- `pyproject.toml` stores contract `source_modules` += `"huron.service.api.revisions"`.
- `tests/ingest_client.py`: `download(revision_id, path) -> Response` (streamed), `_committed`
  and `_reader` as methods (`committed(files)`, `reader(subject)`).
- Tests (`tests/unit/test_api_revisions.py`): the ten download tests of Design 5's table, by name
  (`test_get_revision_returns_the_view_and_hides_an_invisible_one` …
  `test_a_listed_file_missing_or_short_on_disk_is_a_server_error`).
  `tests/unit/test_execution_model.py`: +`get_revision`, +`get_revision_manifest`,
  +`get_revision_file` (63); `test_the_file_download_s_stat_executes_off_the_event_loop_thread`.
  `tests/unit/test_error_contract.py`: the 416 row round-trips through `wire_error_codes()`.

Under D-13 (B): this task is not executed; `FRAMEWORK_STATUSES` and §7 keep their three statuses;
the P2 gate's download clauses are proved by reading the sealed tree in
`test_api_ingest_sessions.py`, and `IngestClient.download` (M8's tests) reads the file under
`revision_path` instead of issuing a request.

**Verification.**

- The route dump prints `63 operations` and contains `GET /api/v1/revisions/{revision_id}`, `GET /api/v1/revisions/{revision_id}/manifest`, `GET /api/v1/revisions/{revision_id}/files/{path}`.
- `grep -n "FRAMEWORK_STATUSES = (400, 404, 405, 416)" src/huron/service/api/problems.py` shows one; `grep -n "REQUESTED_RANGE_NOT_SATISFIABLE" design/api.html` shows one.
- `grep -n "huron.service.api.revisions" pyproject.toml` shows one; `uv run lint-imports` reports 7 kept.
- `uv run pytest -m unit tests/unit/test_api_revisions.py tests/unit/test_execution_model.py tests/unit/test_error_contract.py tests/unit/test_authorization_guards.py` passes.
- Full gate.

**Dependencies.** M5.3.

**Status: pending**

### M7 — Expiry sweep

#### Task M7.1 — `expire_lapsed`, `ExpirySweep`, two settings, the lifespan task

**Intent.** Release the lock of every abandoned session from inside each API replica, on a clock the
tests own, with one background task the lifespan starts after the runtime is published and cancels
before the pool closes.

**Design.** `P2_DESIGN.md` › Design 6 › Target design (all of it: "Placement", "Module layout",
"The pass" (`:3775-3815`), "The runner" (`:3817-3861`), "Settings" (`:3863-3878`; D-16, D-17),
"Wiring" (`:3880-3905`), "The contract", "Multi-replica failure mode", "What the sweep does not
do"); Explicit contracts; Requirements on Design 4 (a)–(c), Design 7; Tests (`:4059-4099`). Load
`.claude/skills/fastapi/`.

**Create / modify.**

- `src/huron/service/api/ingest.py`: `SWEEP_ACTOR`, `ExpiryReport`, `IngestService.expire_lapsed(*, limit)`
  sharing `abort`'s `_audit` helper.
- `src/huron/service/api/expiry.py` (new): `ExpirySweep` with `run`, `__aenter__`, `__aexit__`
  exactly as the block declares; `logger = logging.getLogger(__name__)`.
- `src/huron/service/api/settings.py`: `ingest_sweep_interval_seconds: float = Field(default=60.0, gt=0)`,
  `ingest_sweep_limit: int = Field(default=100, ge=1)` with the `#:` comments.
- `src/huron/service/api/app.py`: `async with ExpirySweep(ingest, interval_seconds=…, limit=…):
  yield` after `_bootstrap`, inside the `try` whose `finally` closes the pool.
- Tests: `tests/unit/test_api_ingest_expiry.py` (eight tests of the pass, over
  `InMemoryHierarchyStore(clock=FakeClock(...))` and `IngestService(..., clock=...)` sharing one
  clock); `tests/unit/test_api_expiry.py` (four runner tests with a recording double,
  `interval_seconds=0`, driven by `await asyncio.sleep(0)`); `tests/unit/test_api_app.py` +
  `test_the_lifespan_sweeps_lapsed_sessions_before_serving_the_first_request`;
  `tests/unit/test_api_settings.py`: the defaults assertion extended, `test_sweep_interval_must_be_positive`,
  `test_sweep_limit_must_be_at_least_one`.

Under the non-default answers: D-16 changes the default literal and the defaults test; D-17
(`0` disables) adds a branch to the lifespan and a test.

**Verification.**

- `grep -n "ingest_sweep_interval_seconds\|ingest_sweep_limit" src/huron/service/api/settings.py src/huron/service/api/app.py` shows both names in both files.
- `grep -n 'name="ingest-expiry-sweep"' src/huron/service/api/expiry.py` shows one.
- `uv run pytest -m unit tests/unit/test_api_ingest_expiry.py tests/unit/test_api_expiry.py tests/unit/test_api_app.py tests/unit/test_api_settings.py tests/unit/test_execution_model.py` passes (`test_execution_model.py` is untouched by design and must stay green).
- Full gate.

**Dependencies.** M5.3.

**Status: pending**

### M8 — Gate suites

#### Task M8.1 — The crash matrix completed

**Intent.** Prove, over HTTP, that a fault after every protocol step leaves the on-disk state
`layer-raw.html` §5 names for that step and that the retry or a new session converges to exactly one
revision.

**Design.** `P2_DESIGN.md` › Design 7 › Gate coverage table rows P5, P6, P9; Techniques › "The
crash matrix" (`:4209-4239`: the nine rows, the rehearsal-under-`fsync_log` technique, `call_of`,
the kill-state test); Collision 3, 7.

**Modify.** `tests/unit/test_api_ingest_crash_matrix.py`: rows 1–5, 8 (`monkeypatch` the
in-memory writer's `insert_outbox_event` to raise once) and 9 added to the parametrization beside
rows 6–7 from M5.3, each asserting the "On disk afterwards", "Session row" and "Retry expectation"
columns; `test_a_session_left_committing_before_the_rename_completes_on_the_next_commit` (seed
COMMITTING with etag +1 on the in-memory row; `/commit` with that etag → 201; documents rewritten;
one revision). P6's assertions (`final` absent, `GET /revisions/{id}` 404,
`latest_committed_revision` unchanged) are part of rows 1–5.

**Verification.**

- `uv run pytest -m unit tests/unit/test_api_ingest_crash_matrix.py -v 2>/dev/null | grep -c "PASSED"` is at least 10 (nine rows plus the kill-state test).
- Full gate.

**Dependencies.** M6.1 (row 9 and P6 use `GET /revisions/{id}`).

**Status: pending**

#### Task M8.2 — Dedup 1-of-500 and the independently complete revision

**Intent.** Prove the gate's dedup clause at its own number in the suite every push runs.

**Design.** `P2_DESIGN.md` › Design 7 › Gate coverage table rows P14, P15; Techniques › "Dedup
1-of-500" (`:4241-4253`); Open question 4 (D-21).

**Create.** `tests/unit/test_api_ingest_dedup.py`:
`test_one_changed_file_of_five_hundred_uploads_one_and_links_the_rest` and
`test_the_linked_revision_survives_the_parent_s_names_being_removed`, through `IngestClient.upload_revision`.

Under D-21 (B) the module moves to `tests/acceptance/` with the `acceptance` marker.

**Verification.**

- `uv run pytest -m unit tests/unit/test_api_ingest_dedup.py --durations=2` passes; record the two
  durations in the report (the design's budget is ≤ 10 s; exceeding it is reported against D-21,
  not fixed by shrinking the count).
- Full gate.

**Dependencies.** M6.1.

**Status: pending**

#### Task M8.3 — The acceptance suite, its nightly workflow and `make test-acceptance`

**Intent.** Give the two full-size clauses (a 9 GiB round trip, an interrupted multi-GB upload that
resumes) a test that runs at the real `PART_BYTES` and a CI job that records a receipt.

**Design.** `P2_DESIGN.md` › Design 7 › Gate coverage table rows P4, M1; Techniques › "The 9 GiB
file" (`:4191-4207`); "Suite placement and CI" › the `acceptance` row and the `Makefile` bullet
(`:4305, 4332-4333`); Open questions 1, 2 (D-18, D-19); Fixtures › `sparse_file`, `zeros_sha256`.

**Create / modify.**

- `tests/ingest_client.py`: `sparse_file(path, size) -> Path`, `zeros_sha256(size) -> str`.
- `tests/acceptance/test_raw_ingest_gate.py` (`pytestmark = pytest.mark.acceptance`):
  `test_a_nine_gib_file_round_trips_byte_identically_after_an_interrupted_upload_resumes` — the
  first `IngestClient` stops after part 50 of 144, a second resumes from `GET`, `put_count` summed
  is 144, `/complete`, `/verify`, `/commit`, then R3 streamed and hashed in 64 MiB chunks.
- `.github/workflows/acceptance.yml`: nightly `cron: "0 3 * * *"` plus `workflow_dispatch`; one job
  with `timeout-minutes: 30`; checkout, `astral-sh/setup-uv` at the SHA `ci.yml` pins, `uv sync
  --all-groups`, `df -h .`, `uv run pytest -m acceptance --no-header -q`. `ci.yml` unchanged.
- `Makefile`: `test-acceptance: ## Run the acceptance suite (needs ≥ 10 GiB free disk).` →
  `uv run pytest -m acceptance`; the `.PHONY` list updated.

Under D-18 (B) the job moves into `ci.yml`; under (C) no workflow is written. Under D-19 (B) the
test targets the Compose stack through `httpx` and moves to `tests/integration/`.

**Verification.**

- `uv run pytest -m acceptance --co -q` collects exactly 1 test; `uv run pytest --co -q` still
  reports it deselected (the unit run is unaffected).
- `grep -n "test-acceptance" Makefile` shows the target and its `.PHONY` entry; `grep -n "setup-uv@" .github/workflows/acceptance.yml .github/workflows/ci.yml` shows the same SHA in both.
- The test is **not** run here (disk); the report says so and names the workflow as the runner.
- Full gate.

**Dependencies.** M6.1.

**Status: pending**

### M9 — Ratchet and maintainability

#### Task M9.1 — Raise the coverage floor to the measured value

**Intent.** Keep the ratchet honest after ~150 new unit tests.

**Design.** `P2_DESIGN.md` › Design 7 › "Suite placement and CI" › **Coverage ratchet**;
`pyproject.toml:260-263`'s own comment.

**Modify.** `pyproject.toml` › `[tool.coverage.report] fail_under`: the total the gate's coverage
line reports on the tree after M8.3, rounded down to an integer. Never lower than 89.

**Verification.**

- `uv run pytest --cov=src/huron --cov-report=term-missing 2>&1 | grep "TOTAL"` — the total is ≥ the new floor; `grep -n "fail_under" pyproject.toml` shows the new value.
- Full gate.

**Dependencies.** M8.3.

**Status: pending**

#### Task M9.2 — `stores/hierarchy.py`'s maintainability rank

**Intent.** Keep the largest store module at rank A with margin, acting on the reading M3.3 recorded.

**Design.** `P2_DESIGN.md` › Design 7 › Open question 5 (D-22); "Suite placement and CI" (b).

**Modify.** If M3.3's recorded `radon mi -s` reading for `src/huron/service/api/stores/hierarchy.py`
was below 25 and the split was not already performed there: move the ingest-session, file, revision,
audit and outbox methods of both adapters to `src/huron/service/api/stores/ingest.py` as two mixin
bases the store classes inherit, behind the same port, with no change to `stores/__init__.py`'s
exported names; the module docstrings of both files say which half each holds. If the reading was
≥ 25, this task records the current reading in the report and changes nothing.

**Verification.**

- `uv run radon mi -s src/huron/service/api/stores/` — every module rank A; record the readings.
- `uv run lint-imports` reports 7 kept (nothing outside `stores/` imports `stores.ingest`).
- `uv run pytest -m contract tests/contract/test_hierarchy_store.py` and `uv run pytest -m unit tests/unit/test_hierarchy_store_memory.py` pass.
- Full gate.

**Dependencies.** M9.1.

**Status: pending**

### M10 — Documentation write-back

#### Task M10.1 — Every correction the designs recorded, proven by `grep`; the §7 disposition column; the roadmap

**Intent.** Make `design/` and `docs/` describe what shipped, define the one undefined column and pin
it with a test, and set the P2 row and milestone 8 to their true status.

**Design.** `P2_DESIGN.md` › Roadmap Drift 1, 2, 5, 7, 8, 9; Design 2 › "Drift 9 write-back"
(`:1808-1816`); Design 4 › "§7 disposition column — definition and write-back" (`:2851-2861`),
"§3 write-back" (`:2863-2871`), Open question 1 (D-9 parenthetical), Tests › `test_error_contract.py`
(`:3096-3098`); Design 5 › Deletions (`:3553-3559`; D-12, D-13); Design 6 › "Documentation
write-back (plan milestone)" (`:3995-3999`); Design 7 › "Roadmap write-back (plan milestone)"
(`:4336-4338`); Design 1 › Open question 1 (the roadmap note). Drift 6 is already applied in the
working tree and is confirmed, not redone. The roadmap's P2 row and milestone 8 tags are set by
Phase 5 of the planning run to describe this plan; this task flips them to what shipped.

**Modify**, each with its confirmation:

| Edit | File | Confirmation |
|---|---|---|
| Drift 7: already applied 2026-09-05 at planning time (M6.3 `Status: done`; its stale "is 19" count corrected to the verified 14) — confirm only | `P1_IMPLEMENTATION_PLAN.md` | `grep -c "^\*\*Status: pending\*\*" P1_IMPLEMENTATION_PLAN.md` is 0 |
| Drift 2: confirm the port docstring shipped in M3.3 | `src/huron/service/api/stores/ports.py` | `grep -rn "numbers are not reused" src design docs` returns nothing |
| Drift 5 and Design 2's seal order: §5 step 5 → "Seal the envelope's contents: files 0444, directories below the envelope root 0555. The root keeps its write bit — `rename(2)` must update its `..` entry."; step 6 gains "then chmod the published root 0555 and fsync it"; §7 `O_EXCL` (never overwritten) → replaced through `atomic_replace`, "allocated under a PostgreSQL row lock" → the committed `UPDATE … WHERE version = $expected` compare-and-swap | `design/layer-raw.html` | `grep -n "dirs 0555" design/layer-raw.html` returns nothing; `grep -n "keeps its write bit" design/layer-raw.html` shows one; `grep -n "row lock" design/layer-raw.html` returns nothing |
| Drift 9: `{ingest_id}/` → `{ingest_id hex}/` with Design 2's annotation; "never descends into `orgs/`" → `organization/` | `design/layer-raw.html` | `grep -n "orgs/" design/layer-raw.html` returns nothing; `grep -n "{ingest_id hex}" design/layer-raw.html` shows one |
| §5 step 8 / `:141` `INDEX.json` "regenerated on commit" → "written best-effort at commit; regenerated by the reconciler" (D-12); `:311-312` "one small JSON" → "one small JCS document, `urn:huron:committed:1`"; `:192-193` "a client-supplied value is a 400" → "is 422 `REQUEST_INVALID`: the body model has no such member"; `:270-271` "within the TTL" → "within the TTL plus one sweep interval" | `design/layer-raw.html` | `grep -n "best-effort at commit\|urn:huron:committed:1\|422\|plus one sweep interval" design/layer-raw.html` shows all four |
| Drift 8: the definition sentence above the §7 table ("`live` means at least one shipped path operation can answer with the code; `reserved` means the code is part of the contract but no shipped route raises it yet"); rows `MANIFEST_MISMATCH`, `INGEST_SESSION_EXPIRED` (meaning → "ingest session passed its idle TTL, or is terminal and cannot be renewed (§3 ingest)" — D-4), `DATASET_LOCKED`, `DUPLICATE_CONTENT`, `CONTRACT_MISMATCH` (+ "— in P2 the registered contract is the packaged `metadata-v1.json`") flipped `reserved` → `live`; the 416 row from M6.1 confirmed | `design/api.html` | `grep -n "idle or absolute TTL (§3 ingest)" design/api.html` returns nothing; `grep -c "<td>live</td>" design/api.html` is the M6.1 count plus 5 minus the rows the raise-site row below flips; `grep -n "no shipped route raises it yet" design/api.html` shows one |
| Every pre-existing `live` row whose class has no raise site anywhere in `src/huron` on the final tree flips `live` → `reserved`, under the definition sentence's wording. `LAYER_WORKFLOW_VIOLATION` (`:231`) is the code of `LayerWorkflowError` (`pkg/catalog/layers.py:66-69`), already raised at `layers.py:165` and `:259`; a registry-based dry run on today's tree finds no `live` row lacking a raise site, so this row is expected to flip nothing — the test's own failure list on the final tree, not this plan, is the authority for which rows flip. | `design/api.html` | the raise-site test below passes; for each flipped row `grep -n "<td>CODE</td><td>NNN</td><td>reserved</td>" design/api.html` shows one |
| §3: the `POST /ingest-sessions` row becomes Design 4's two rows (no metadata draft — D-3); `:heartbeat`, `:complete`, `:verify` / `:commit` / `:abort` on the ingest rows → `/heartbeat` … `/abort`; the parts row gains the `Content-Length`/64 MiB/`completed_parts` sentence; the commit row's body → `{manifest_sha256, metadata}`. The `/layer-intake-sessions` row (`:148`) is another phase's and is left. | `design/api.html` | `grep -n "metadata draft\|:heartbeat\|:complete" design/api.html` returns nothing; `grep -n ":verify" design/api.html` shows only the layer-intake row; `grep -n "{manifest_sha256, metadata}" design/api.html` shows one |
| `:135`: `dataset.read_raw` → `data.read@raw`; "issues a short-lived download capability; re-authorized per file" → "authorised per request against `data.read@raw`; the response is the capability, nothing is minted" (D-13) | `design/api.html` | `grep -n "dataset.read_raw" design/api.html` returns nothing; `grep -n "data.read@raw" design/api.html` shows at least one |
| Milestone 8: the parenthetical → "humans with `dataset.create` and `data.write@raw`; an organization service account may mint the dataset but cannot upload to `raw`" (D-9); "Adds:" gains the three revision routes and the best-effort `INDEX.json` (D-12, D-13); the milestone's tag set to what shipped | `design/roadmap.html` | `grep -n "whose dataset-CRUD authority is intrinsic" design/roadmap.html` returns nothing; `grep -n "cannot upload to" design/roadmap.html` shows one |
| P2 row: each Delivers item names its module and test module so Drift 1's "unit-tested" is true by inspection; the D-1 note ("a session whose driver crashed in `COMMITTING` holds its dataset lock until the P3 reconciler; the owner's abort cannot release it"); the tag flips from `partial` to `done` only with the acceptance workflow's run URL recorded in the row (Design 7), otherwise stays `partial` with the per-item status and says why | `design/roadmap.html` | `grep -n "until the P3 reconciler" design/roadmap.html` shows one; `grep -n "P2 — Raw ingest" -A 1 design/roadmap.html` shows the tag and, if `done`, `grep -n "actions/runs" design/roadmap.html` shows the receipt |
| Drift 6: confirm only | `design/roadmap.html` | `grep -n "P1 — Foundations" -A 1 design/roadmap.html` shows `done`; `grep -c "TS + Python client cores generated" design/roadmap.html` is 0 |
| API row: Responsibility gains "reaps lapsed ingest leases"; Writes-to keeps "PostgreSQL" | `design/architecture.html` | `grep -n "reaps lapsed ingest leases" design/architecture.html` shows one |
| Environment table gains `HURON_INGEST_SWEEP_INTERVAL_SECONDS` and `HURON_INGEST_SWEEP_LIMIT` | `docs/getting-started/local-development.md` | `grep -c "HURON_INGEST_SWEEP" docs/getting-started/local-development.md` is 2 |
| The `acceptance` row describes `tests/acceptance/test_raw_ingest_gate.py`, `make test-acceptance`, the disk requirement and the nightly workflow | `docs/getting-started/testing.md` | `grep -n "test-acceptance\|acceptance.yml" docs/getting-started/testing.md` shows at least one |
| `test_live_rows_have_a_raise_site_and_reserved_rows_have_none` — the `ast` walk over `src/huron` `Raise` nodes collecting the names each raise calls; a §7 row is matched to its class by `code`, through the same registry `wire_error_codes()` reads (never by CamelCasing the code — `NOT_FOUND` is `ResourceNotFound`); every `live` row whose code is registered to a `DomainError` class has at least one raise site, every `reserved` row has none; framework-status rows (`FRAMEWORK_STATUSES`) are exempt | `tests/unit/test_error_contract.py` | `uv run pytest -m unit tests/unit/test_error_contract.py` passes |

Under the non-default answers: D-9 (B) writes milestone 8's parenthetical as a service account
that may upload to `raw`; D-12 (B) writes `INDEX.json` back to the P3 row and `layer-raw.html:141`
to "created and regenerated by the reconciler"; D-13 (B) leaves `api.html:135` as reserved intent
and moves the three revision routes out of milestone 8's "Adds".

**Verification.**

- Every confirmation in the table.
- `uv sync --group docs && make docs` builds with `--strict` (broken internal links fail it).
- `uv run pytest -m unit tests/unit/test_error_contract.py` passes.
- Full gate.

**Dependencies.** M9.2.

**Status: pending**

---

## 5. Risk register

| # | Change | Symptom to watch for | Fallback decision point |
|---|---|---|---|
| 1 | The `syncify` body bridge (M5.2) under a real ASGI server, not only `TestClient` | `NoEventLoopError` or a hang on the first chunk when the route runs under uvicorn; a truncated `Content-Length` body surfacing as something other than `http.disconnect` | If `TestClient` and `httpx.ASGITransport` pass but `make api` + a real `PUT` fails, the bridge moves to `anyio.from_thread.run` directly (the primitive `syncify` wraps) before any other change; if the disconnect shape differs, `PartLengthMismatch` still refuses the short stream (Design 4 receipts) and only the 400 code assertion moves |
| 2 | Two transaction disciplines in one tier (M5.3): the commit's file steps run outside any store transaction while `HierarchyRepository` holds one across its document write | A crash-matrix row where a revision row exists without its envelope (impossible by the order) or the session flips `COMMITTED` without step 2's row (the guard refuses it: `P0001`) | The order is proved on PostgreSQL (Design 3 receipts); a verifier seeing the guard fire in `scenario_14` has found a statement-order regression in `IngestService.commit`, not a design defect — fix the order, never widen the transaction |
| 3 | `rename(2)` of a `0o555` root refused on Linux/NFS as on darwin (M2.1, M2.2) | `EACCES` from the envelope publication in CI's `ubuntu-latest` unit job | The design already seals contents before and the root after the rename; if CI still refuses, the parent directory's mode is the next suspect (`raw/revision/` must be writable by the API user) — an environment fact for `docs/getting-started/local-development.md`, not a code change |
| 4 | `stores/hierarchy.py` maintainability falls below rank A after M3.3 adds ~550 lines of SQL and dict logic | `radon mi --min B` prints the module; the gate fails at M3.3 | D-22: the split to `stores/ingest.py` is pre-approved and M3.3's verification says when it is done there versus in M9.2 |
| 5 | M5.1 exceeds one subagent's budget | The implementation subagent stops with routes 1, 3, 4, 9 green and route 2 or the deletion unfinished | Pre-approved split: **M5.1a** — schema twins, facade (`create` on an existing dataset, `ledger`, `entry`, `heartbeat`, `abort`), `dataset_raw_writer`/`session_owner`/`session_overseer`, routes 1, 3, 4, 9, wiring, the write-intent deletion and its test replacements; **M5.1b** — `project_intake`, route 2, `test_create_in_project_mints_the_dataset_then_opens_the_session`, `test_intake_authorization_matrix`. Both leave the tree green; the route dump reads 55 then 56 |
| 6 | The nightly 9 GiB job (M8.3) exhausts the runner's disk or its 30-minute budget | The workflow's `df -h .` step shows < 10 GiB free, or the job times out | D-18 (C): run once by hand on a host with the disk, record the receipt in the roadmap row, keep the workflow on `workflow_dispatch` only until a runner with the disk exists |

---

## 6. Definition of done

The plan is complete when all of the following hold on the final tree:

1. Every task above carries `**Status: done**`.
2. The full gate (`make lint` and `uv run pytest --cov=src/huron --cov-report=term-missing`) is
   green; `uv run radon cc src/huron --min C` prints nothing; `uv run lint-imports` reports
   "7 kept, 0 broken"; `uv run pytest -m contract` is green against a fresh `postgres:16`.
3. Every P2 and milestone-8 gate clause Design 7 mapped has a passing named test — the eighteen:
   P1 (`test_file_download_round_trips_nfc_zero_byte_and_eight_level_files_byte_identically` with
   `test_file_download_refuses_traversal_and_non_nfc_spellings_before_touching_storage` and
   `test_create_refuses_every_manifest_rule_with_its_documented_code`), P2 (the same R3 test,
   `test_a_zero_byte_file_is_one_part_that_completes_on_the_empty_digest`,
   `test_decode_manifest_round_trips_nfc_zero_byte_and_eight_level_entries_with_the_same_identity`),
   P3 (the same R3 test, `test_write_part_fsyncs_the_file_and_every_directory_up_to_the_payload_root`),
   P4 (`test_a_nine_gib_file_round_trips_byte_identically_after_an_interrupted_upload_resumes`,
   collected; run by the nightly workflow), P5
   (`test_a_crash_after_each_commit_step_leaves_the_named_state_and_the_retry_converges`,
   `test_a_session_left_committing_before_the_rename_completes_on_the_next_commit`), P6 (matrix
   rows 1–5, `test_a_crash_in_the_tree_fsync_attempts_no_rename`,
   `test_a_crash_in_the_rename_leaves_staging_intact_and_final_absent`), P9 (matrix row 6 and 7,
   `test_commit_envelope_retry_after_the_rename_is_silent_and_reseals_the_root`), P10
   (`test_a_new_client_resumes_from_the_session_view_and_re_sends_only_pending_files`), P11
   (`test_two_concurrent_begin_ingest_calls_serialize_on_the_dataset_row`), P12
   (`scenario_16_a_hundred_sequential_ingests_number_gap_free` on both backends), P13
   (`test_a_replayed_commit_returns_the_same_revision`,
   `scenario_14_the_commit_transaction_is_atomic_and_replays`), P14
   (`test_one_changed_file_of_five_hundred_uploads_one_and_links_the_rest`), P15
   (`test_the_linked_revision_survives_the_parent_s_names_being_removed`), P16
   (`test_create_refuses_every_manifest_rule_with_its_documented_code`, the R3 refusal test,
   `test_validate_manifest_refuses_every_non_nfc_path`), M1 (the P4 acceptance test), M2
   (`test_create_returns_the_plan_and_locks_the_dataset`), M3
   (`test_commit_publishes_the_revision_and_its_events`,
   `test_get_revision_returns_the_view_and_hides_an_invisible_one`), M5
   (`test_commit_publishes_the_revision_and_its_events`).
4. The three excluded clauses — P7 (staging swept), P8 (post-rename orphan imported), M4 (search
   projection) — are recorded as P3, P3 and P4 in the roadmap's P2 row.
5. Every `D-n` in § 2 is recorded in the roadmap or design write-back with its answer or the
   default the tree implements.
6. The route dump prints `63 operations` and contains the nine ingest paths and the three revision
   paths named in M5.1, M5.2, M5.3 and M6.1, and no `write-intents` path.
7. `uv run alembic upgrade head`, `downgrade -1`, `upgrade head` round-trip on a clean database
   (M3.1's manual step and `_assert_round_trip`); `uv run python scripts/check_schema_map.py` exits 0.
8. `git diff main -- src tests | grep -c "# noqa\|# type: ignore\|# pragma: no cover\|pytest.mark.skip\|pytest.mark.xfail"` is 0.
9. Every `grep` confirmation in M10.1's table passes and `make docs` builds strictly.
10. `fail_under` is at or above the value M9.1 measured and never below 89.

---

## Receipts

Checked on `main` at `c5e35c7` (2026-09-04), working tree as described in § 0, before any task ran.

- `uv run radon cc src/huron --min C` → four items: `src/huron/service/api/settings.py`
  `C 55:0 ApiSettings - C`, `M 90:4 ApiSettings.refuse_unsafe_combinations - C`;
  `src/huron/pkg/rbac/__init__.py` `M 208:4 Binding.covers - C`;
  `src/huron/pkg/catalog/paths.py` `F 448:0 parse_revision_dir - C`.
- `uv run pytest --markers | grep -E "unit|contract|integration|acceptance"` → the four registered
  markers with their descriptions.
- `grep -n fail_under pyproject.toml` → `263:fail_under = 89`.
- `uv run radon mi -s src/huron/service/api/stores/hierarchy.py` → `A (30.06)`.
- `git diff --stat design/roadmap.html` → `1 file changed, 10 insertions(+), 12 deletions(-)` (the
  P1 row `done`, the OpenAPI/client deliverable moved to T0-1 — Drift 6 applied by hand).
- `git status --short` → `M CLAUDE.md`, `M design/roadmap.html`, `?? .agents/skills/oop-encapsulation/`,
  `?? P2_DESIGN.md`.
- `uv run pytest --co -q` → `674/684 tests collected (10 deselected)`.
- The route dump (§ 0) → `52 operations`; the only ingest-adjacent path is
  `/api/v1/datasets/{dataset_id}/layers/{layer}/write-intents`.
- `grep -rn "register_revision" tests src | wc -l` → 40 lines across `test_api_catalog_hierarchy.py`,
  `test_repository_hierarchy.py`, `test_hierarchy_store_memory.py`, `test_hierarchy_store.py`,
  `stores/hierarchy.py`; `grep -c seed_revision tests/hierarchy_contract.py` → 19;
  `_FakeClock` at `tests/unit/test_hierarchy_store_memory.py:54` and
  `tests/contract/test_hierarchy_store.py:102`; `_insert_revision` at `test_hierarchy_store.py:185`;
  `_wait_until_a_backend_blocks_staking_the_claim` at `:510`.
- `grep -rln "write_intent\|WriteIntent\|dataset_layer_writer\|LayerWrite\b" src tests` → seven
  files (`guards.py`, `authorization/__init__.py`, `schema/datasets.py`, `endpoints/datasets.py`,
  `test_api_catalog_hierarchy.py`, `test_execution_model.py`, `test_authorization_guards.py`).
- `grep -rn "Metastore" src tests` → `src/huron/pkg/catalog/ports.py:131` only.
- `grep -n "\[spec\]" migrations/schema.sql` → lines 23 (header), 87, 160, 457, 470; `Reflects:` at line 10.
- `grep -n "Status: pending" P1_IMPLEMENTATION_PLAN.md` → line 1130 is M6.3's status line.
- `design/api.html`: `:127-132` the ingest rows with `:verb` spellings and "metadata draft";
  `:135` `dataset.read_raw`; `:238-242` the four `reserved` ingest rows; `:248` `CONTRACT_MISMATCH`
  `reserved`; `:275` `SESSION_EXPIRED` also says "idle or absolute" (the login session's — kept).
  `design/layer-raw.html`: `:129` `{ingest_id}/`, `:141` "regenerated on commit", `:193` "is a 400",
  `:271` "within the TTL", `:285` "dirs 0555", `:312` "one small JSON", `:350-351` `O_EXCL` / "row
  lock", `:406` `orgs/`. `design/architecture.html:163` the API row. `design/roadmap.html:331`
  the P2 row (`partial`), `:559-560` the service-account parenthetical.
- `src/huron/service/api/problems.py:40` `FRAMEWORK_STATUSES = (400, 404, 405)`; `:3, :98` "six
  handlers"; `tests/unit/test_error_contract.py:5` "all six"; `tests/unit/test_execution_model.py:74`
  `"create_write_intent": True`.
- `tests/unit/support.py` holds `memory_stores()` only; no `tests/conftest.py`; `tests/integration/`
  and `tests/acceptance/` hold one `__init__.py` each.
- Not run: any container (per instructions), `make docs`, the acceptance test.

No split of this plan is needed; the scope fit the budget.

---

## Verification

### Cycle 1 — 2026-09-05

**3 defects.** Read in full: this plan; `P2_DESIGN.md` Phase 0–1 (`:1-700`), Design 1 › Target
design (`:1084-1358`), Design 7 in full (`:4142-4404`), every design's `### Deletions`, every
design's `### Open questions` (headings), and the four module-layout tables (D3, D4, D5, D6).
Extracted mechanically rather than read: every `test_*` and `scenario_*` name in the design (diffed
against the plan), the "resolved downstream" anchor headings, and the cross-design
"Requirements on the other designs" positions. Not read (budget): the Target-design bodies of
Designs 2–6 (the `RawStore` block, the `0009` SQL, the route table and facade, the documents block,
the pass and runner), every `### Explicit contracts`, `### Data flow` and `### Rejected
alternatives`, and the assertion columns of the `### Tests` tables — see Observations 1.

### Defects

1. **M5.2's docstring check cannot pass.** `grep -c "six" src/huron/service/api/problems.py
   tests/unit/test_error_contract.py` is required to be 0, but `problems.py:261` carries an
   unrelated, enduring sentence ("… disappearing the way the six it replaces once did", the
   `PathRuleViolation` code-reading helper's docstring) that no task rewords. The verifier reports 1
   and the task fails on a check the implementation cannot satisfy without an out-of-scope edit.
   Correction: make the check `grep -n "six handlers\|all six\|registers six"
   src/huron/service/api/problems.py tests/unit/test_error_contract.py tests/unit/test_api_problems.py`
   returns nothing, and add `tests/unit/test_api_problems.py:3` ("Covers the six handlers …") to
   M5.2's docstring edits — it is a third "six" the clean sweep must not leave.
2. **M3.1's mandatory contract step goes red on a writer the design missed.**
   `tests/contract/test_catalog_store.py::_insert_ingest_file` (`:865-876`) inserts an
   `ingest_files` row by raw SQL naming only `file_id, ingest_id, path, size, expected_sha256,
   action`. `0009` adds `part_count … NOT NULL` with no default ("because the table has no writer at
   `0008`" — true of `src/`, false of this helper), so every test that calls the helper fails with a
   not-null violation and `uv run pytest -m contract tests/contract/test_catalog_store.py` cannot
   pass. Correction: M3.1's Modify list gains "`_insert_ingest_file` supplies `part_count` (`1`, the
   value the action-tied CHECK requires for its `'upload'` row) and any `state` literal it writes is
   in the new vocabulary"; the docstring sentence about "no writer" says "no writer in `src/`".
3. **M10.1's `test_live_rows_have_a_raise_site_and_reserved_rows_have_none` fails on a row no task
   flips.** A dry run over today's §7 finds `LAYER_WORKFLOW_VIOLATION` (`design/api.html:231`)
   `live` with a class (`errors.py`) and no raise site anywhere in `src/huron` (the class is
   referenced nowhere outside its definition). The test as specified goes red, M10.1 does not
   authorize flipping a non-P2 row, and the confirmation `grep -c "<td>live</td>"` = "M6.1's count
   plus 5" is then off by one. The dry run also shows the test must map a row to its class through
   the registry `wire_error_codes()` uses (the `code` attribute), not by CamelCasing the code:
   `NOT_FOUND` → `ResourceNotFound`, `APIKEY_EXPIRED`, `INVALID_CREDENTIAL` do not round-trip by
   name. Correction: M10.1's table gains the row "every pre-existing `live` row whose class has no
   raise site in `src/huron` flips to `reserved` (today: `LAYER_WORKFLOW_VIOLATION`; the test's own
   failure list is the authority), with the definition sentence's wording"; the test's spec says
   "rows are matched to classes by `code`, through the same registry `wire_error_codes()` reads";
   the `<td>live</td>` confirmation becomes "M6.1's count plus 5 minus the rows so flipped".

### Observations

1. **Not verified here, by budget.** The plan's per-task fidelity to Designs 2–6's Target-design
   bodies (method-by-method port members, the `0009` DDL, route/guard/facade signatures, the
   documents block, the sweep's pass and runner) and to every `### Explicit contracts` table was not
   checked line by line; the module-layout tables, deletions, open questions and every named test
   were. A second cycle should read D2 `:1598-1743`, D3 `:2095-2239`, D4 `:2549-2825`, D5
   `:3253-3476` and D6 `:3775-3905` against M2.2, M3.2–M3.3, M5.1–M5.3, M4.1/M6.1 and M7.1
   respectively.
2. **PostgreSQL-dependent claims rest on Design 3's receipts, unverified here:** M3.1's round trip
   and the two `EXPLAIN` index proofs, M3.2's nine scenarios seeding through the port, M3.3's
   scenarios 10–16 and the race, `_HIERARCHY_TABLES` truncation with the four new names, M9.2's
   contract run. No container was started.
3. **Coverage of the design's tests** is by table reference, not by name, for D2's 40, D5's 13 and
   10, and D6's 12; the diff of every `test_*` name in the design against the plan found no name
   that lacks a task, given collision 3 (the two D4 crash tests → matrix rows 6–7) and D5's
   `test_a_commit_retry_past_the_rename_rebuilds_the_record_from_the_marker`, which collision 3
   folds into row 7. M5.3 should say that name is absorbed (its assertions are row 7's extension)
   so the P9 trace in § 6 has an answer.
4. **`ports.py`'s module docstring does not say "Nine Protocols"** (M1.2); it lists "the metastore"
   in prose (`:3-5`). The intent stands — drop that phrase — and the verification does not grep it.
5. **`rows.ingest_file(row) -> IngestFile`** (M3.3) departs from Design 3's module table
   (`-> LedgerEntry`); the plan composes `LedgerEntry` in the store. Reasonable, but it is a
   departure § 3 does not list.
6. **"returns to the pool"** (M3.3's grep) sits on one line of Design 1's docstring today; a
   re-wrap at another width would split it. Prefer `grep -n "returns to the pool\|returns to the$"`
   or a two-word anchor.
7. **Tasks silent under the other answer:** M4.1 (D-15 B drops `test_a_malformed_instant_is_refused`
   and the extra), M6.1 (D-13 B), M10.1 (D-9/D-12/D-13 change the write-back text). Rule 4 asks for
   one line each.
8. **Complexity exposure not pre-empted:** Design 7 (a) warned about route 5 only, but
   `IngestService.commit` (M5.3: eight steps, the re-entry branch, the `OSError` fork on `final`,
   the swallowed step 8) and `IngestService.create` (M5.1: two transactions with a compensating
   `fail()`) each carry more than ten decision points as described. M5.1 and M5.3 should name the
   domain-boundary split (e.g. `_publish_envelope` / `_record_revision` / `_write_index`) rather
   than leave it to the third attempt.
9. **D-4's "resolved downstream"** was checked only to the heading (`:2851`); the meaning cell's
   text was not read.
10. **Drift 6 is confirm-only** (`git diff --stat design/roadmap.html` → `10 insertions(+),
    12 deletions(-)`; the P1 row reads `done`; "TS + Python client cores generated" → 0 hits).
11. **`radon cc` baseline is exactly the four symbols M0.1 names**; `fail_under = 89` at
    `pyproject.toml:263`; `--min B` MI for `stores/hierarchy.py` is `A (30.06)`.
12. **`pytest_cov`, `hypothesis 6.165.10`, `testcontainers` import; `asyncer 0.0.18` exports
    `syncify`/`asyncify`; `starlette 1.6.0`'s `FileResponse` implements `Range`/`Content-Range`;
    `jsonschema 4.26.0` is pinned and `rfc3339_validator` is absent** — M4.1's `format-nongpl`
    extra is the right lever and is not yet in `uv.lock`.
13. M5.3's `IfMatchHeader`/`expected_version()` live at `routes/v1/preconditions.py`, not a
    top-level `preconditions.py`; the plan names symbols only, so nothing breaks.

### Receipts

- Tool spellings, each printing a version under `uv run`: `ruff 0.16.3`, `ty 0.0.75`,
  `mypy 2.3.1`, `import-linter 2.13`, `pytest 9.1.1`, `radon 6.0.1`, `complexipy 7.0.1`,
  `pyscn 1.30.0`; `alembic --help` usage line; `scripts/check_schema_map.py` rc 0; `make -n lint`
  → the eleven commands § 0 lists in that order; `make -n test` → `uv run pytest -m unit`;
  `make -n docs` → `uv run --group docs zensical build --strict`.
- `uv run pytest --markers` → the four markers; `uv run pytest --co -q tests/unit` → `674 tests
  collected`; `uv run lint-imports` → `Contracts: 7 kept, 0 broken`; `git status --short` → the
  four entries § 0 names plus `?? P2_IMPLEMENTATION_PLAN.md`.
- `uv run radon cc src/huron --min C` → the four items verbatim; `grep -n fail_under
  pyproject.toml` → `263:fail_under = 89`; `sed -n 39,48p;59p;64p .claude/commands/implement-markdown.md`
  → the ten commands, the empty-output rule, the decomposition rule.
- The route dump (§ 0) → `52 operations`; the only ingest-adjacent path is the write-intent one.
- Cited lines present: `Metastore` `ports.py:131`; `[spec]` at `schema.sql:23,87,160,457,470`,
  `Reflects:` at `:10`; `P1_IMPLEMENTATION_PLAN.md:1130` the only `^**Status: pending**`, "is 19"
  at `:1123`; `api.html:127-132,135,238-242,248,275`; `layer-raw.html:129,141,193,271,285,312,
  350-351,406`; `architecture.html:163`; `roadmap.html:221 (done),331 (partial),559-560`;
  `problems.py:3,40,98` (+`:261`, defect 1); `test_error_contract.py:5`; `test_execution_model.py:74`;
  `support.py` = `memory_stores` only, no `tests/conftest.py`; `register_revision` 40 lines / 5
  files; `seed_revision` 19; `_FakeClock` `:54`/`:102`; `_insert_revision` `:185`;
  `_wait_until_a_backend_blocks_staking_the_claim` `:510`; `_HIERARCHY_TABLES` `:71` (six names);
  the runner `await scenario(store, seed_revision)` `:262`; write-intent symbols in the seven files;
  `_SystemClock` `hierarchy.py:51`, `register_revision` `:700`, `_revisions` keyed
  `(dataset_id, number)` `:415`; `raw_store: PosixRawStore` `repository.py:101`;
  `staging_root`/`write_once`/`root.chmod(0o555)`/`create_staging(ingest_id)` in `store.py`;
  `_TRANSITIONS`/`transition`/`heartbeat`/`parent_path` in `ingest.py`; `ContractMismatch`
  `errors.py:244`; `uuid7` `ids.py:15`; `load_schema` resolves any file name under `documents/`;
  `ci.yml` pins `setup-uv@20cfd1bf…` four times; `test_catalog_properties.py:48 _property`;
  `test_schema_snapshot_provenance.py::test_the_schema_itself_is_valid`; every unit module M0.1–M9
  extends exists.
- `<td>live</td>` in `api.html` → 46 today; the strict raise-site dry run → live-with-class-and-no-
  site includes `LAYER_WORKFLOW_VIOLATION` (defect 3); reserved-with-site = `INGEST_SESSION_EXPIRED`
  (M10.1 flips it).
- Plan structure: 21 × `#### Task`, `**Status: pending**`, `**Intent.**`, `**Design.**`,
  `**Verification.**`, `**Dependencies.**`; no `noqa`/`type: ignore`/`skip`/`xfail`/TODO instruction
  outside rule 2's prohibition; § 6's eighteen gate tests = Design 7's 21 rows minus P7, P8, M4.
- Open-question headings per design: D1 4, D2 2, D3 2, D4 3, D5 4, D6 2, D7 5 — every one a
  `D-n`; anchors for the resolved rows found at `:2756` (D-2/D-6), `:2791` (D-8), `:2851` (D-4),
  `:3037` (D-1/D-11), `:2259` and `:3336` (D-5), D5 module table (D-3).
- `test_catalog_store.py:865-876` `_insert_ingest_file` (defect 2); D2's commit-test table
  (`:1954-2015`) reaches `0o555` through `commit_envelope`, never `PosixRawStore.seal`, so M2.1
  before M2.2 is green.

### Fix pass — 2026-09-05

All three defects and the concrete observations applied; the Defects, Observations and Receipts
text above is unchanged; no `**Status: pending**` changed; no other file touched.

1. Applied — M5.2 › Create/modify (the four handler-count docstrings named, `problems.py:261`
   excluded by name), M5.2 › Verification (the verifier's three-phrase grep over three files).
2. Applied — M3.1 › Create/modify (`_insert_ingest_file` supplies `part_count = 1` for its
   `'upload'` row and keeps any `state` literal in the vocabulary; the migration docstring says
   "no writer in `src/`").
3. Applied — M10.1 › table (a new row: every pre-existing `live` row without a raise site on the
   final tree flips to `reserved`, the test's failure list being the authority, with the note that
   M5.1's route-1 refusal is expected to give `LAYER_WORKFLOW_VIOLATION` its site; the raise-site
   test row now says rows are matched to classes by `code` through `wire_error_codes()`'s
   registry, framework statuses exempt; the `<td>live</td>` count is "plus 5 minus the rows so
   flipped").
- Observation 3 — Applied: M5.3 › Tests says row 7 absorbs D5's
  `test_a_commit_retry_past_the_rename_rebuilds_the_record_from_the_marker`.
- Observation 4 — Applied: M1.2 › `ports.py` bullet drops the "Nine Protocols" instruction for
  "the prose mention of the metastore".
- Observation 5 — Applied: § 3 departure 12 (`rows.ingest_file -> IngestFile`).
- Observation 6 — Applied: M3.3 › Verification grep tolerates a wrap.
- Observation 7 — Applied: one non-default line each in M4.1 (D-15 B), M6.1 (D-13 B), M10.1
  (D-9/D-12/D-13 B).
- Observation 8 — Applied: M5.1 names `_plan` / `_reserve` / `_open_envelope` / `_fail`; M5.3
  names `_compose_commit` / `_fence_commit` / `_publish_envelope` / `_record_revision` /
  `_write_index`, each one domain boundary, the public methods carrying no branch of their own.
- Observation 13 — Applied: M5.3 names `routes/v1/preconditions.py`.
- Observations 1, 2, 9 — not plan text (a second verification cycle's scope). Observations 10,
  11, 12 — receipts confirming the plan; nothing to change.

### Cycle 2 — 2026-09-05

**VERIFIED — 0 blocking defects; 6 non-blocking items for the owner.** Read against the fix pass:
the corrected text of M1.2, M3.1, M3.3, M4.1, M5.1, M5.2, M5.3, M6.1, M10.1 and § 3 departure 12.
Coverage pass, read in full: Design 2 `:1598-1743`, Design 3 `:2095-2239`, Design 4
`:2549-2825`, Design 5 `:3253-3476`, Design 6 `:3775-3905`, and every design's `### Explicit
contracts` with its "Requirements on the other designs" block (`:1818-1869`, `:2317-2374`,
`:2882-2933`, `:3487-3545`, `:3947-4000`). Not read, per instruction: Data flow, Rejected
alternatives, Receipts; the `0009` SQL block (`:2247-2315`) was checked by its DDL object names
only, and D5's schema fragments (`:3207-3251`) not at all.

**Disposition of cycle-1 defects.**

1. **Fixed.** M5.2's grep is now `"six handlers\|all six\|registers six"` over the three files;
   on today's tree it returns exactly the four lines M5.2 schedules to reword (`problems.py:3`,
   `:98`, `test_error_contract.py:5`, `test_api_problems.py:3`) and not `problems.py:261`.
2. **Fixed.** M3.1 updates `_insert_ingest_file` (`part_count = 1`, state literal in the
   vocabulary) and the docstring says "no writer in `src/`".
3. **Fixed, with a correction to the example, not the rule.** The registry rule, the flip row and
   the "plus 5 minus the rows so flipped" arithmetic are right. But the planner's reading — and
   cycle 1's example — are both wrong about the class: `LAYER_WORKFLOW_VIOLATION` is the code of
   `LayerWorkflowError` (`pkg/catalog/layers.py:66-69`, not `LayerWorkflowViolation`), which is
   already raised at `layers.py:165` and `:259`; M5.1's route-1 refusal does not give it its site,
   it adds a third. Cycle 1's finding was itself the CamelCase artefact the rule guards against. A
   registry-based dry run on today's tree (classes matched by `code` through `DomainError`'s
   subclass tree) finds **no** `live` row lacking a raise site and only `INGEST_SESSION_EXPIRED` as
   a `reserved` row with one — which M10.1 flips. The flip row is therefore a no-op today and
   correct as a rule; its note should say so (N2 below).

**Blocking defects.** None.

**Non-blocking (wording; no gate check or task depends on them).**

- **N1 — M5.3's "seven-statement transaction"** (task title and `_record_revision`) counts one
  more than Design 3's commit transaction (`:2218-2228`) and Design 4 step 6 (`:2813`), both
  "six-statement": `claim`, `insert_revision`, `update_ingest_session`, `insert_audit_event`,
  `insert_outbox_event`, `remember`. The "seven-statement" that is right is `begin_ingest`
  (M3.3). Correction: "six-statement" in M5.3's title and body.
- **N2 — M10.1's flip row** attributes `LAYER_WORKFLOW_VIOLATION`'s raise site to M5.1 and cites
  the cycle-1 dry run; replace the note with "the class is `LayerWorkflowError`, raised at
  `layers.py:165, 259`; the registry-based dry run on `c5e35c7` finds no pre-existing `live` row
  without a site, so this row is expected to flip nothing — the test's failure list on the final
  tree remains the authority".
- **N3 — M3.2 declares `AuditEvent` "frozen, slots, as the module's other records are
  declared"**; `records.py`'s records are `@dataclass(slots=True)` without `frozen` (`:21, :42,
  :65, :98, :118, :140`) and Design 3's block (`:2099`) is the same. Drop "frozen" or say
  `@dataclass(slots=True)`.
- **N4 — M5.2 does not cite Collision 4** for route 5's `offset`/`length`: Design 4 `:2698` has
  the facade import `PART_BYTES` and tests patch `huron.service.api.ingest.PART_BYTES`, while
  Collision 4 (the arbiter) has the facade read `huron.pkg.catalog.ingest.PART_BYTES` at call time
  and the tests patch that module — which M5.2's tests do. A `receive_part` written from D4's
  sentence binds the constant at import and every multipart test in M5.2 fails on
  `Content-Length != length`. Add "offset/length from `ingest.PART_BYTES` at call time
  (Collision 4)" to M5.2's `receive_part` bullet.
- **N5 — M5.3's Design list omits Design 5 › Requirements on Design 4 (a)** (`:3517-3519`): the
  claim digest's `content_identity(metadata)` is over `MetadataSubmission.model_dump(exclude_none=True)`;
  Design 4 `:2820-2821` (cited) does not say so. Add "(a)" to M5.3's citation.
- **N6 — Design 3's `begin_ingest` statement 6 writes `VALUES (uuid7(), $1, uuid7(), …)`**
  (`:2155`); PostgreSQL 16 has no `uuid7()` SQL function (`uuidv7()` arrives in 18). M3.3's
  "the statements verbatim" should say the two ids are `ids.uuid7()` bound as parameters, as
  the existing store does, or the first contract attempt fails on `function uuid7() does not
  exist`.

### Observations (cycle 2)

1. **Design 2 ↔ M2.1/M2.2.** All fourteen port members, `PartLengthMismatch`, `_make_private_dirs`,
   `_pwrite_all`, `create_staging`'s three fsyncs, `write_part`'s flags/range/digest/durability,
   `hardlink_from_parent`'s `samefile` no-op, `write_document`'s name rule and `mode=0o444`,
   `seal` minus the root chmod, `commit_envelope`'s two added calls on both branches, the typed
   `HierarchyRepository`, the contracts table and requirements (a)–(e) on D4 all map to M2.1/M2.2
   and M5.2, and M2.2's verification (fourteen members in order; `mypy`/`ty` on `root`) catches
   an omission.
2. **Design 3 ↔ M3.1–M3.3.** `AuditEvent`, `LedgerEntry`, `Replay.kind` +2, the 8 writer and 6
   reader methods, every row of the SQL-semantics table and its refusal mapping, the commit
   transaction's six statements (in M5.3's `_record_revision`), requirements (a)–(f) on D4
   (with departure 5 declining (b)), the D5/D6/D7 requirements, and `0009`'s objects
   (`parent_revision_id` + `ingest_sessions_parent_revision_fk`, `ingest_sessions_parent_revision`,
   `ingest_sessions_dataset`, `part_count` + `ingest_files_part_count_matches_action`,
   `ingest_files_state_vocabulary`, D6's `ingest_sessions_lapsing`, each with its `downgrade`
   twin) all map; M3.1's grep names the five, the round trip the columns and indexes.
3. **Design 4 ↔ M5.1–M5.3.** Routes 1–9 with their op orders, the seven twin models, the facade's
   ten members with the signatures in the block, the six guards and two proof records, the intake
   matrix, the bridge and memory bound, the nine `asyncify` sites, `/commit` steps 1–7 and the
   `Idempotency-Key` digest, the invariants, lifecycle and audit kinds, and requirements (a)–(d)
   on D5, on D6 (no `create_app(clock)`) and on D7 all map; M5.1's `_plan/_reserve/_open_envelope/_fail`
   and M5.3's five private methods each sit on one boundary of the design's sequence.
4. **Design 5 ↔ M4.1/M6.1 (and M5.1/M5.3).** Every name in the `documents.py` block with its
   methods and properties, the five-callable mapping, `MetadataSubmission`/`RevisionView`,
   `PayloadFile`/`RevisionService` with its three reads in the block's check order, `RevisionRead`/
   `revision_raw_reader`, R1–R3 with their `FileResponse` arguments, 416 + the §7 row, the
   document and read-side invariants, and requirements (a)–(h) on D4 all map (see N5 for (a)).
5. **Design 6 ↔ M7.1 (and M3.1/M3.2).** `SWEEP_ACTOR`, `ExpiryReport`, `expire_lapsed` sharing
   `_audit`, `ExpirySweep`'s three members and task name, the two settings with `#:` comments, the
   lifespan placement inside the `try`, the invariants/error behaviour/lifecycle, and the
   unanticipated requirements on D4 (a)–(c), D3 (a)–(b) and D7 all map; M7.1's greps catch the
   settings names and the task name.
6. **PostgreSQL-dependent, still unverified here:** M3.1's `EXPLAIN` proofs and round trip, the
   nine seeded scenarios, scenarios 10–16, the race, `_HIERARCHY_TABLES`, M9.2's contract run.
7. The load-bearing observation fixes hold: M5.1/M5.3's private-method splits name one domain
   boundary each with the public method carrying no branch; M4.1, M6.1 and M10.1 carry their
   non-default lines; departure 12 records `rows.ingest_file -> IngestFile`; M3.3's wrap-tolerant
   grep; M5.3 names `routes/v1/preconditions.py` and absorbs D5's retry test into row 7.

### Receipts (cycle 2)

- `grep -n "six handlers\|all six\|registers six" src/huron/service/api/problems.py
  tests/unit/test_error_contract.py tests/unit/test_api_problems.py` → `test_api_problems.py:3`,
  `test_error_contract.py:5`, `problems.py:3`, `problems.py:98`; `grep -c "six"` on the same three
  → 1, 1, 3 (the third includes `:261`).
- `sed -n 862,882p tests/contract/test_catalog_store.py` → `_insert_ingest_file` inserts
  `(file_id, ingest_id, path, size, expected_sha256, action)`; one `INSERT INTO ingest_files` in
  the module.
- `sed -n 55,80p src/huron/pkg/catalog/layers.py` → `class LayerWorkflowError(DomainError)`,
  `code, status_code = "LAYER_WORKFLOW_VIOLATION", 409`; `raise LayerWorkflowError(` at `:165`
  and `:259`; `design/api.html:231` the row, `live`.
- Registry dry run (walk `DomainError.__subclasses__()` after importing `pkg.catalog.errors`,
  `pkg.catalog.layers`, `service.api.errors`, `pkg.auth`; match `raise <Class>(` over
  `src/huron`) → live-with-class-and-no-site: `[]`; reserved-with-site: `['INGEST_SESSION_EXPIRED']`;
  live rows with no `DomainError` class: the six `PATH_*` codes (instance-level `code`), the
  four framework statuses, and the auth/role codes.
- `sed -n 2247,2316p P2_DESIGN.md | grep -o "CREATE … INDEX|ALTER TABLE|ADD COLUMN|ADD CONSTRAINT|DROP …"`
  → the objects listed in Observation 2, each with its `DROP` twin.
- `grep -n "six-statement\|seven-statement" P2_DESIGN.md P2_IMPLEMENTATION_PLAN.md` → design
  `:2354, :2813, :3530` "six-statement"; plan `:695` (begin_ingest, correct), `:987`, `:1022`
  "seven-statement" (N1).
- `grep -n "^class \|slots\|frozen" src/huron/service/api/records.py` → every record
  `@dataclass(slots=True)`, none frozen (N3).

### Post-cycle-2 corrections — 2026-09-05

Cycle 2's six non-blocking items applied by the orchestrator as surgical text edits, so no
implementation attempt is spent discovering them: N1 — M5.3 title and `_record_revision`
"seven-statement" → "six-statement" (`:695`'s `begin_ingest` count left as is); N2 — M10.1's flip
row now states the `LayerWorkflowError` facts and "expected to flip nothing"; N3 — M3.2's
`AuditEvent` is `@dataclass(slots=True)`, not frozen; N4 — M5.2's `receive_part` bullet reads
`PART_BYTES` at call time (Collision 4); N5 — M5.3's Design list cites Design 5 › Requirements on
Design 4 (a); N6 — M3.3's Postgres statements bind `ids.uuid7()` as parameters. No `Status` line
changed; 21 tasks remain `pending`.

## Execution notes — 2026-09-06

Recorded by the orchestrator as tasks verified, so later tasks build on what shipped rather
than on the design's literal text.

- **M2.2 / Design 2.** The part-length exception is `PartLengthMismatchError`, not
  `PartLengthMismatch`: ruff's `N818` applies to `src/huron/pkg/rawstore/store.py` (no per-file
  exemption, and the exemptions that exist cover names that mirror wire error codes, which this
  one never is), and the package's own `CrossDeviceCommitError` already carries the suffix. M5.2
  maps `PartLengthMismatchError` → `ManifestMismatch`.
- **M2.2 / Design 2 › Tests.** `_safe_relative` cannot refuse `"a/./b"` or `"a//b"`:
  `PurePosixPath` normalises both to `('a', 'b')` before the guard sees them, and neither escapes
  `staging_payload`. The test pins the normalising behaviour; the design row was wrong about
  `pathlib`, not about the guard.
- **M3.2 / Design 3 › Tests.** The rollback test is
  `test_a_rolled_back_transaction_leaves_no_revision_audit_or_outbox_row`: the design's 91-character
  name cannot fit an `async def` line under ruff's 100-column limit. The body raises inside the open
  transaction after all three inserts, so the pinned behaviour is unchanged. `radon mi -s
  stores/hierarchy.py` read A (25.61) after M3.2; M3.3 measures again for D-22.
