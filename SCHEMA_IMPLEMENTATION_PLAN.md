# Huron PostgreSQL schema — implementation plan

Companion to [`SCHEMA_DESIGN.md`](SCHEMA_DESIGN.md), which is authoritative for every design
decision referenced below. This file is the execution order and the verification contract; it
**never restates the design**. Where a task says "per `SCHEMA_DESIGN.md` § …", the DDL, the
constraint names and the reasoning are there, in full, and must be copied from there rather
than re-derived.

Seed findings: [`schema_audit.md`](schema_audit.md), findings **F1–F8**, each proven on a live
PostgreSQL 16. Do not re-derive them and do not re-run the audit's database verification.

**The revision this plan builds.** One Alembic revision:

```
migrations/versions/0008_schema_conformance.py
revision      = "0008_schema_conformance"
down_revision = "0007_roleless_service_accounts"
```

The slug is settled here (it is the one judgement `SCHEMA_DESIGN.md` § "S8 — … ### Open
questions" leaves to this phase) because `migrations/schema.sql`'s `Reflects:` stamp copies it
verbatim.

**No human decision gates this plan.** Both decisions it once waited on were settled by Karl on
2026-08-31 — the `audit_events` partitioning (option B, drop it) and the abort/retry semantics
of an ingest reservation. See § Gates below, which is now a record rather than a queue. Every
milestone may be executed in order without waiting on anything.

---

## 1. Goal and non-goals

### Goal

Bring the Huron metastore into conformance with
`.claude/skills/postgresql-table-design/SKILL.md` by closing the proven integrity gaps and
constraint/index omissions F1–F8, in one migration (`0008_schema_conformance`), with every new
rule pinned by a write that must fail and a write that must succeed, and with
`migrations/schema.sql` turned from stale prose into a mechanically checked obligation.

**And a second goal, added after the Phase 0 grill: the documentation must stop asserting
database properties that nothing enforces.** The grill's goal-3 judgment was that coverage is
adequate and the distinction is missing — nothing states which invariants the database holds and
which the application holds — and that single absence produced Drift 6, Drift 10, F2 and F8. S9
answers it by changing the grammar of the two documents that assert database properties, so that a
rule cannot be written without naming who refuses the violating write. This plan owns the
`migrations/schema.sql` half of that change (M1); the `design/` half is the write-back phase's,
named in the non-goals below with the ordering it must respect.

Concretely, on completion:

| Finding | Closed by | Milestone |
|---|---|---|
| F1 — a release can cite another dataset's revision | S1 composite FK + redundant unique key | M3 |
| F2 — enum-like text columns with no CHECK | S2 (11 columns) + S3 (5 columns) | M5, M6, M9 |
| F3 — unindexed foreign-key columns | S4 index sweep (+ one index discharged by S1) | M3, M4 |
| F4 — RBAC scope listing has no usable index | S4 `role_bindings_scope` | M4 |
| F5 — no jsonb column constrains its shape | S5 (15 columns) | M7, M9 |
| F6 — `audit_events` partitioned with only a DEFAULT child | S6 — drop the partitioning | M9 |
| F7 — referential actions left implicit | S4 (stated where the choice is live) | M4 |
| F8 — `ingest_sessions.revision_id` has no FK | S7 commit-time guard | M8 |

One design task lands **no DDL at all**: **S9**, the enforcement record. It closes no audit
finding and appears in no row above, because what it fixes is a defect in the register rather than
in the schema — Drift 10 (`-- linear, gap-free, immutable` written over a table with no rule of any
kind) and the grill's goal-3 judgment. Its `migrations/schema.sql` half lands in **M1**, folded into
the header S8 already rewrites; `SCHEMA_DESIGN.md` § "S9 — The enforcement record (design)".

One change in `0008` closes no audit finding, because the audit did not reach it: **S7a**, the
abort-and-retry semantics of a revision-number reservation. It was raised as S7 open question 3,
excluded from an earlier draft of this plan as a statement about an allocator that does not exist,
and settled by Karl on 2026-08-31 with the design proved on a live PostgreSQL 16.13. It lands in
M8 beside the S7 guard that shares its table. `SCHEMA_DESIGN.md` § "S7a — Abort and retry
semantics (design)".

### Non-goals

**Out of scope for `0008` because a human must decide first.** These are recorded, not dropped;
each names what would settle it.

- **`snapshots.project_id`** — whether a snapshot should carry a project anchor, which is what
  makes `product_versions.snapshot_id` fixable at all. `SCHEMA_DESIGN.md` § "S1 — … ### Open
  questions". Picked up by a gold-layer design task against `design/layer-gold.html`; `0008`
  does not touch `snapshots` on S1's account.

**No longer out of scope: `ingest_sessions` abort/retry.** An earlier draft of this plan excluded
the reservation collision — S7 open question 3 — as "a statement about an allocator that does not
exist yet", and recorded that `0008` would not touch
`ingest_sessions_dataset_id_revision_number_key`. Karl settled the semantics on 2026-08-31 and
`SCHEMA_DESIGN.md` § "S7a — Abort and retry semantics (design)" proves the DDL on a live database,
so that exclusion is withdrawn: **M8 replaces that constraint with the partial unique index
`one_claim_per_revision_number`.** The four follow-ups S7a raises are contracts on future code
rather than DDL and are carried forward below; the hazard an earlier draft flagged as an open
question — the stranded envelope — is now the fourth of them, settled.

**Out of scope because the vocabulary does not exist to adopt.** `ingest_files.state`,
`jobs.state` and `reconciliation_findings.severity` get no CHECK — `SCHEMA_DESIGN.md` §
"S2 — … ### Open questions" items 2–4 state what settles each (P2, P6, P3 respectively). One
consequence is pinned by test in M10: the audit's fourth proof, `INSERT INTO jobs … state =
'WAT'`, still succeeds after `0008`, on purpose.

**Out of scope because it is a model change, not a constraint fix.** The polymorphic
`(kind, id)` reference in `lineage_edges` (S3 open question 2, deferred to P9);
`audit_events.subject_kind` (S3 open question 3, deferred to roadmap milestone 3);
a `dataset_revisions` immutability trigger (S7 open question 2); an `ingest_sessions` transition
guard of the `releases_immutable()` kind (S7a open question **3** — renumbered in cycle 4 when
item 1 was resolved; the transition map lives only in `src/huron/pkg/catalog/ingest.py`, and an
illegal resurrection of a terminal row is refused by both partial indexes anyway, so the failure is
safe rather than silent, if wrongly worded). Narrowing that map in Python is a separate question
and has its own verdict — S7a open question 2 recommends **against** narrowing
`_TRANSITIONS[COMMITTING]` to `{COMMITTED}`, because the reconciler legitimately needs the
`COMMITTING → FAILED` edge once it has consulted storage, and deleting the edge would push that
write outside the state machine rather than remove it.

**Out of scope because it is application code, not DDL.** Respelling `bindings_at`
(`src/huron/service/api/postgres_rbac.py`) so `scope_id` becomes an index condition rather than
a filter — `SCHEMA_DESIGN.md` § "S4 — … ### Open questions" item 1 states why the schema already
makes it safe and why it is left open. M4 adds `role_bindings_scope` regardless; it is the
correct index for the access path either way.

**Settled since an earlier draft, and now a contract rather than an open question — an abort
written over a session that is already durable.** Freeing a revision number is safe only for a
session that has not yet renamed its staging tree into `revisions/{nnnnnn}--{revision_id}`, and
`SCHEMA_DESIGN.md` § "S7a — … ### The stranded envelope after the durability point — resolved"
settles what follows, on two facts already in the record. `src/huron/pkg/catalog/ingest.py` line 39
makes `ABORTED` **unreachable** from `COMMITTING` while `FAILED` is reachable, so an `ABORTED`
session provably never passed the durability point and **the single edge `COMMITTING → FAILED` is
the entire hole**; and `design/layer-raw.html` §5's crash table already mandates roll-forward for
that window ("Orphan commit. Reconciler imports the row from `COMMITTED`", the step-6 retry being
idempotent), so a commit path that answers a generic error by writing `FAILED` contradicts the
design record regardless of what any index does with the number. The resolution is a contract on
the writer — nothing leaves `COMMITTING` for a failure state without first determining whether the
rename happened — and it is carried in the brief below. **No DDL changes, and none should be
invented for it:** a session stuck in `COMMITTING` sits *inside* `one_claim_per_revision_number`'s
predicate and so keeps holding its number while its fate is unknown, which is the correct
behaviour, and the database can never see the filesystem. Violating the contract is loud rather
than silent — `dataset_revisions` keeps its own total `UNIQUE (dataset_id, revision_number)` from
`0001`, so a wrongly reused number makes the reconciler's later import fail on that key instead of
creating a second revision 1, leaving a `reconciliation_findings`-shaped disagreement rather than
corruption. **What is still open is narrower and belongs to P3:** who performs the storage consult
— the TTL sweeper before it writes any terminal state (recommended: it is already a filesystem
actor, and the dataset lock must be released within the TTL) or the nightly reconciler — and,
dependent on that, what severity a refused orphan import raises, which
`reconciliation_findings.severity` has no vocabulary for yet. `SCHEMA_DESIGN.md` § "S7a — …
### Open questions" items 1 and 2; item 2 also records the verdict that
`_TRANSITIONS[COMMITTING]` should **not** be narrowed to `{COMMITTED}`, which is a `pkg/catalog`
API question rather than a schema one.

**Carried forward as a brief, not implemented here.** S7's guard imposes four requirements on
the `Metastore` implementation that does not exist yet — one transaction with the revision
inserted before the session flip, the transaction opened only after the staging rename, the
session flipped in that same transaction, and the reconciler bound by the same shape
(`SCHEMA_DESIGN.md` § "S7 — … ### Explicit contracts", "What the future `Metastore`
implementation must honor"). No task here implements them; they must be seeded into the P2
design task that builds `src/huron/pkg/catalog/ports.py`'s implementation, together with S7 open
question 4 (whether `record_revision`'s obligation to close the session is expressed in its
signature or its docstring).

S7a adds four more to the same brief, and all four are contracts on code rather than DDL —
`0008` makes each of them *necessary* without being able to enforce any of them
(`SCHEMA_DESIGN.md` § "S7a — … ### Explicit contracts", "What the future `Metastore`
implementation must honor"):

- **The allocator must read `dataset_revisions`, not `ingest_sessions`** —
  `SELECT coalesce(max(revision_number), 0) + 1 FROM dataset_revisions WHERE dataset_id = $1`,
  issued in the same transaction as the session `INSERT`. Reading the session table instead would
  miss a reconciler-imported orphan revision, re-issue its number, and run a whole ingest to
  completion before `dataset_revisions_dataset_id_revision_number_key` refused it at step 7.
- **The TTL sweeper and force-abort must write a terminal state, not merely let `expires_at`
  pass.** Freeing is state-based: both index predicates read `state` and neither reads
  `expires_at`, so a session abandoned in `UPLOADING` with a long-expired lease holds the dataset
  lock and the revision number forever. `design/layer-raw.html` §4's "a crashed client releases the
  dataset lock within the TTL" is a statement about a writer that must exist.
- **The retry is a whole new session and mints a new `revision_id`.** Only `revision_number` is
  freed; `ingest_sessions.revision_id` keeps `0001`'s total `UNIQUE` and is untouched by `0008`,
  so the retry's storage path differs from the dead attempt's even at the same number.
- **Nothing moves a session out of `COMMITTING` into a failure state without first determining
  whether the rename happened.** The writer — the commit path's own error handler, the TTL sweeper,
  a force-abort, or the reconciler — must stat `revisions/{nnnnnn}--{revision_id}` first. Present
  means the session is past the durability point and the resolution is **roll-forward**: import the
  row from the `COMMITTED` marker, per `design/layer-raw.html` §5's crash table, and never free the
  number. Only a **proven-absent** envelope may be written `FAILED`. This composes directly with the
  sweeper contract above and the two must be implemented together: a sweeper that never writes a
  terminal state strands the dataset lock forever, and one that writes a terminal state
  unconditionally over an expired `COMMITTING` session strands a sealed envelope. An expired session
  in `PREPARING`, `UPLOADING` or `VERIFYING` needs no check — those states cannot have renamed
  anything.

Like S7's four, these must be seeded into the P2 design task that builds
`src/huron/pkg/catalog/ports.py`'s implementation, not rediscovered there.

**Out of scope because the design settled it as a decision, not a deferral.** No GIN index on
any jsonb column — `SCHEMA_DESIGN.md` § "S5 — … #### The no-GIN decision, restated as a
decision" states the reversal condition; do not add one and do not re-litigate it. No
`pkg/` `StrEnum` for a column whose writer does not exist (`SCHEMA_DESIGN.md` § "S2 — … #### The
`pkg/` `StrEnum` companions"); exactly one enum lands here, in M2. No `CREATE INDEX
CONCURRENTLY`. No `NOT VALID` constraints. No `ON DELETE`/`ON UPDATE` respelling of the
eighteen foreign keys whose action is unreachable.

**Out of scope because another phase owns it — and the handover, enumerated.** Everything below
belongs to Phase 5 of `/design-plan`, the roadmap-reconciliation subagent (the phases were
renumbered; the design record and `SCHEMA_DESIGN.md` § "S6 — … ### Open questions" still say
Phase 4), driven by `SCHEMA_DESIGN.md` § "Roadmap Drift" and § "Phase 0 grill — database
documentation (2026-08-31)". **No milestone here edits `design/`**, and none of the following is
implementation work — each is a text correction to a document, listed so the write-back has a
complete list rather than a sample.

- `design/roadmap.html` §2 P1 ("audit with pre-created partitions"), superseded by S6's option B.
- `design/catalog-search.html` §2's `audit_events` sketch, same cause.
- `design/roadmap.html` §3 milestone 3's stale role count and trigger claim — **already corrected
  in the working tree**; the grill re-checked it against the seed and records "Phase 5 has nothing
  left to do on that item". Kept here so it is struck rather than re-done.
- **Drift 7** — `layer_repos`, a registry table `design/catalog-search.html` §2 declares and no
  migration creates, with a `snapshots` keyed to it that does not match the shipped table.
- **Drift 8** — six tables in the same §2 skeleton with wrong column lists, one wrong primary key
  and one wrong cardinality (`role_bindings`, `api_keys`, `idempotency_records`, `jobs`,
  `lineage_edges`, `ingest_files`, `retention_holds`).
- **Drift 12** — `design/rbac.html` §4's example binding, which the live `role_binding_guard` and
  two CHECKs refuse. `SCHEMA_DESIGN.md` § "S9 — …" states explicitly that this is a wrong example
  rather than an unmarked enforcement claim, and that S9 does not close it.
- **Drift 15** — stale specifics in `RBAC_IMPLEMENTATION_PLAN.md` §R4 and `IMPLEMENTATION_PLAN.md`
  §A5, both records of shipped work.
- **Drift 16** — `design/catalog-search.html` §2 no longer names `science_profiles`, which exists,
  and names `schema_registry`, which does not.
- **Two `design/catalog-search.html` §2 column-name corrections that no drift finding carries and
  that this plan therefore hands over explicitly**, both named in `SCHEMA_DESIGN.md` § "S9 — …
  ### Explicit contracts": `product_versions.status` → `state` (the members are right, the column
  name is not — see M5), and `product_versions.derivation` → `derivation_record` (verified: `0001`
  line 291 and `migrations/schema.sql` line 305 both spell it `derivation_record`). S9 assigns the
  first to S2 and the second to S5, but neither S2 nor S5 has a task here that edits `design/`, so
  without this bullet they are owned by nobody.
- The design-record document count, stated as thirteen, 13 and fourteen across `README.md`,
  `docs/getting-started/repository-layout.md`, `docs/backend-design.md` and `docs/index.md`
  against fifteen `design/*.html` files. `SCHEMA_DESIGN.md` § "Phase 0 grill — … ### Could not be
  checked" flags it as adjacent and out of scope; it is a documentation correction like the rest.

**Out of scope here, and the one item on that list with a hard ordering constraint: S9's `design/`
half.** The markers in `design/catalog-search.html` §2's skeleton, the new
`<h3 id="enforcement">What the database enforces</h3>` subsection that defines them, and the
one-sentence replacement in `design/architecture.html` §5 are the other three of S9's four edits.
They are `design/` edits and so are not milestones here, but two orderings bind whoever writes them
and are stated here because nothing else states them:

1. **They must land before an implementation subagent executes M5 or M6.** `SCHEMA_DESIGN.md`
   § "S9 — … ### Sequencing" gives this as the reason for writing the record now rather than after
   `0008`: S2 and S3 are transcribing vocabularies *out of* §2, and a marked §2 is what tells them
   which of its assertions are the specification they are implementing and which are already
   installed. Phase 5 runs after this plan is verified and before any milestone is executed, so
   the ordering is satisfied by the normal sequence — but it is a requirement, not a coincidence.
2. **They must land after the §2 content corrections above**, or accept re-marking the corrected
   lines. § "S9 — … ### Explicit contracts": "S9 owns the marking, never the content."

M1's `migrations/schema.sql` header paragraph cites `design/catalog-search.html` §2 by section for
the marker definitions, so the citation is stable under (2) but is a dangling reference until the
subsection exists — which is the second reason the two halves must not be separated by a long gap.

**Out of scope because no finding raises it.** `DEFAULT now()` on the 25 `created_at`/
`updated_at` columns (the application supplies them — house convention); `CHECK (length(…) <= n)`
on free-text `title`/`description`. Both are `SCHEMA_DESIGN.md` § "Notes carried forward for the
planning phase"; neither has a design task, so neither is implemented.

**Folded in rather than excluded.** `science_profiles.document_sha256` — the one `*_sha256`
column in the schema with no format CHECK, surfaced by `SCHEMA_DESIGN.md` § "S5 — … ### Open
questions" item 1 and owned by no design task. **Planning decision: it lands in `0008`, in M5**,
as `science_profiles_document_sha256_format`. It is one line, it is the house pattern applied to
the one column that lacks it, the table has no writer so the constraint validates trivially, and
leaving it would strand a known one-line gap behind a future design task that has no other
reason to exist.

---

## 2. Gates — the decisions this plan waited on, and what is left

**Nothing in this plan is gated.** Both decisions are settled; this section is the record.

### Gate D1 — `audit_events`: commit or drop? — settled 2026-08-31, option B

**Karl chose option B: drop the partitioning.** `audit_events` becomes a plain table with
`PRIMARY KEY (id)` and one btree on `(created_at, id)`. `SCHEMA_DESIGN.md` § "S6 — …
### Decision" records the decision and § "S6 — … ### Proof" records its execution against a live
PostgreSQL 16.13. Option A is kept in the design as a short "Not chosen" section so nobody
re-derives it; **no task in this plan may execute it.** M9 is therefore ungated, carries the
option-B branch only, and may run as soon as M8 is complete.

**Why M9 is still last-but-one.** Nothing else changed about the ordering: the one load-bearing
requirement is that the two `audit_events` CHECKs follow the structural rebuild that would
otherwise destroy them, and M9 owns both halves. Placing it after M8 costs nothing.

### D0 — is there an audit retention window? — open, and no longer a gate

`SCHEMA_DESIGN.md` § "S6 — … ### Open questions" item 1. Still unanswered, and still not stated
anywhere in `design/`: §2 P5 specifies retention for raw payload only, and
`design/architecture.html`'s invariant B is about published `revisions/` prefixes, so audit rows
are kept forever by default — a policy nobody wrote down rather than a policy anybody chose.

It is recorded here as a forward-looking note, not a blocker. Under the plain table, enforcing a
window is a `DELETE` over a time range rather than a `DETACH PARTITION`; a window would only make
the partitioned shape correct again if audit volume also turned out an order of magnitude above
the estimate, and both conditions would be visible years ahead. **No milestone waits on it and
`0008` does not anticipate it.**

---

## 3. Conventions every milestone obeys

**The validation gate.** Every task's verification runs the full gate from
`.claude/commands/implement-markdown.md`, with the resolved package path `src/huron`:

```
uv run ruff check .
uv run ruff format --check .
uv run ty check
uv run mypy
uv run lint-imports
uv run pytest --cov=src/huron --cov-report=term-missing
uv run radon cc src/huron --min C
uv run radon mi src/huron --min B
uv run complexipy src/huron --max-complexity-allowed 15
uv run pyscn check src/huron
```

Below, "**the gate**" means exactly those ten commands, all green, with no suppressed lint, no
`# noqa`, no `# type: ignore`, no `# pragma: no cover`, no skip or xfail, and no lowered
threshold. `make lint` is the first five minus `ty`, `pytest`, `radon`, `complexipy` and
`pyscn`; `make test` is `uv run pytest -m unit`. Both are conveniences — the gate is the
contract.

**Two scopes that matter when reading the gate.** `--cov`, `radon`, `complexipy` and `pyscn`
measure `src/huron` only: `tests/` and `scripts/` are not scanned by them, so repeated
`_assert_*` helpers across contract modules will not trip clone or complexity detection, and
`scripts/check_schema_map.py` is not coverage-measured. `ruff` checks the whole tree, and
`mypy`/`ty` check `src/huron/pkg` and `src/huron/schema` only.

**Contract tests are not in the gate's pytest run.** `pyproject.toml` sets
`addopts = "-m unit --strict-markers"`, so `uv run pytest --cov=…` runs the unit suite alone.
Every milestone that changes DDL must therefore *also* run its contract suite explicitly:

```
uv run pytest -m contract tests/contract/test_catalog_store.py
uv run pytest -m contract tests/contract/test_rbac_store.py
```

These require Docker: each module spins a real `postgres:16` through `testcontainers` and
applies the project's own Alembic revisions with `command.upgrade(config, "head")`. **A
contract run that applies `0008` is itself the verification that every statement in it is
valid and that every `DROP CONSTRAINT` / `DROP INDEX` named an object that exists** — none of
them carries `IF EXISTS` in `upgrade()`, so a misspelled PostgreSQL-generated constraint name
fails the migration loudly rather than passing silently.

**One migration, amended across milestones.** `0008` is created in M3 and appended to by M4–M9.
It is unreleased and in flight (as are the untracked `0006` and `0007`), so amending it is
legitimate; each milestone must leave `upgrade()` and `downgrade()` mutually inverse and the
contract suites green. A developer holding a database already at `0008` runs
`uv run alembic downgrade 0007_roleless_service_accounts` then `make migrate` after each such
milestone.

**Statement order inside `0008` is a task-level concern, and this is the rule.** The file holds
one module-level `DDL = r"""…"""` string and one `downgrade()` block (house convention, per
`SCHEMA_DESIGN.md` § "Constraints that bind every task in this document" item 2; read
`migrations/versions/0005_auth.py` as the shape model). Each milestone **appends** its block to
the end of `DDL` and **prepends** the mirror to the start of `downgrade()`, so the file's
statement order is the milestone order and `downgrade()` is the exact reverse of `upgrade()`.
That yields, and every milestone must preserve, this block order:

```
1. S1  cross-parent referential integrity            (M3)
2. S4  index set, subsumed objects, referential actions (M4)
3. S2  state / lifecycle vocabularies + digest format (M5)
4. S3  kind constraints: jobs, outbox_events, lineage_edges (M6)
5. S5  jsonb top-level types, every table except audit_events (M7)
6. S7  ingest session -> revision guard               (M8)
7. S7a reservation lifecycle: one_claim_per_revision_number (M8)
8. S6  audit_events structural DDL                    (M9)
9.     audit_events_kind_format, audit_events_payload_is_an_object (M9)
```

**`0008` holds nine `DDL` blocks.** Only one of those orderings is load-bearing: **9 must follow
8**, because the old `audit_events` relation is dropped and a constraint added to it would go
with it (`SCHEMA_DESIGN.md` § "S6 — … ### Ordering"). Blocks 1–7 are order-independent among
themselves except that block 1's `dataset_revisions_id_dataset_id_unique` precedes the FK that
targets it, which is internal to block 1. Block 7 in particular is free: `SCHEMA_DESIGN.md`
§ "S7a — … ### Target design" states that its two statements depend on nothing else in `0008` and
that nothing in `0008` depends on them; it sits beside block 6 because both belong to
`ingest_sessions` and to M8, not because the order matters.

**Every new rule is pinned by a paired write.** A refused write **and** a permitted write, or a
constraint that rejects everything would pass. Expected exception classes, which differ by
mechanism: `asyncpg.exceptions.ForeignKeyViolationError` for a foreign key,
`asyncpg.exceptions.CheckViolationError` for a CHECK,
`asyncpg.exceptions.RaiseError` for a plpgsql guard. The working template is
`tests/contract/test_rbac_store.py`'s `_assert_trigger_rejects_*` helpers;
`tests/contract/test_auth_store.py` already asserts `CheckViolationError`.

**The `migrations/schema.sql` obligation.** From M1 onward, `scripts/check_schema_map.py` runs
in `make lint` and fails when the map's `Reflects:` line is not the Alembic head. Every
milestone from M3 on therefore edits `migrations/schema.sql` in the same change as its DDL.
The stamp reads `0007_roleless_service_accounts` until M3 and `0008_schema_conformance`
thereafter.

**The marker obligation, binding from M1 on every map edit this plan makes.** M1 installs the
paragraph in `migrations/schema.sql`'s header that adopts S9's notation for that file, so from that
point **an annotation in the map that states a property carries a marker**: `[db]` with the object
that refuses the violating write, `[app: <module>]` with the module that maintains it, `[spec]`
where nothing does and no writer exists, and the qualifier `[db 0008]` for a rule this revision
installs but the database does not have yet. `SCHEMA_DESIGN.md` § "S9 — … #### The marker
vocabulary" is the definition and is not restated here. Two consequences for the map-updating tasks
T3.5, T4.3, T5.4, T6.3, T7.3, T8.3, T9.4 and T10.3: every annotation they add carries a marker, and
every marker they add for an object `0008` creates is written **`[db 0008]`**, not `[db]`, because
the map is committed alongside a revision that has not been applied to any database at the moment
the line is written. T10.4 drops those qualifiers when `0008` lands. A bare adjective — the Drift 10
defect — is not a marking. Plain column lists are not properties and carry nothing.

**The one ambiguity in that rule, resolved here rather than left to an implementer.** § "S9 — …
#### The marker vocabulary" defines `[db]` as installed "at the revision `migrations/schema.sql`'s
`Reflects:` line names", and T3.5 moves that line to `0008_schema_conformance` before any of
`0008`'s objects exist in a database — read strictly, that would make every `0008` object bare
`[db]` in the map from M3 on, and § "S9 — … ### Sequencing" would have nothing to drop in this
file. **Planning decision: the qualifier tracks whether the revision has landed, not what the stamp
says**, so map annotations for objects `0008` creates read `[db 0008]` from M3 through M9 and go
bare at T10.4. The reason is that `0008` is unreleased and in flight for the whole of M3–M9 (§ 3,
"One migration, amended across milestones"), so during that window the map is committed beside a
revision no database has applied — which is exactly what the qualifier is for — and it keeps the
map's markers and §2's markers saying the same thing about the same object at the same time.

**Clean sweep.** No backwards-compatibility shims, no TODOs, no speculative abstractions, no
suppressed lints. **No comment, docstring, test name or user-facing string may reference this
plan, its milestones, its tasks, or any checklist mechanics.** Comments explain enduring intent;
migration docstrings follow the house shape (`0005_auth.py`) — what the change is for and which
invariant it serves.

---

## 4. Milestone sequence

`0008_schema_conformance` shipped in commit `da03ece`, and every milestone below is marked done.

| # | Milestone | Touches a migration | Discharges |
|---|---|---|---|
| M1 | The schema-map obligation and the enforcement notation | no | S8; S9 (`migrations/schema.sql` half); drifts 4 and 10 |
| M2 | Dataset lifecycle vocabulary in `pkg/` | no | S2 (Python half) |
| M3 | `0008` skeleton + cross-parent referential integrity | creates | F1; part of F3 |
| M4 | Foreign-key access paths, referential actions, deletions | appends | F3, F4, F7 |
| M5 | Closed state and lifecycle vocabularies | appends | F2 (11 columns) |
| M6 | Event `kind` vocabularies outside `audit_events` | appends | F2 (4 of 5 columns) |
| M7 | jsonb top-level types outside `audit_events` | appends | F5 (14 of 15 columns) |
| M8 | Ingest-session ↔ revision correspondence, and the reservation lifecycle | appends | F8; S7a |
| M9 | `audit_events`: structure and its two constraints | appends | F6; F2 and F5 remainder |
| M10 | Round-trip, deferral pins, final map reconciliation | no | whole-plan closure; drifts 11, 14 and the `[db 0008]` qualifier drop |

Ordering rationale, against the four rules the command sets:

- **Contracts before dependents.** M1 installs the lint check every later milestone must
  satisfy, **and the marker notation every later map edit must obey** — which is the second reason
  S9's `migrations/schema.sql` half belongs in M1 and not in a milestone of its own: a notation
  adopted after M3–M9 have written eight unmarked annotations is a notation that arrives with a
  backlog. M2 lands the `pkg/` vocabulary before the CHECK that mirrors it. M3 creates the
  migration file, fixes the revision slug the stamp copies, and introduces the contract-test
  module M5–M9 all write into.
- **Deletions early.** Three of the four objects `0008` removes —
  `releases_revision_id_fkey` (M3), `role_bindings_principal_scope` and
  `products_dataset_id_fkey` (M4) — land in the two earliest migration milestones, so no later
  block is written against an object slated for removal. M4's index sweep is deliberately
  second, before any CHECK milestone, because it also settles which indexes exist. The fourth,
  `ingest_sessions_dataset_id_revision_number_key`, cannot move earlier: it is dropped only
  because `one_claim_per_revision_number` replaces it in the same block, and nothing between M3
  and M8 is written against it.
- **No broken intermediate state.** Every milestone ends with the gate green and, from M3, both
  contract suites green against a freshly migrated `postgres:16`.
- **Sized for one subagent.** The largest are M4 (10 DDL statements, 3 contract assertions) and
  M7 (14 constraints, table-driven tests); both are mechanical, with the DDL already written out
  in `SCHEMA_DESIGN.md` to be copied rather than composed. M8 carries two DDL blocks after S7a
  was folded into it and is still the third-largest: four statements in total (a function, a
  trigger, a `DROP CONSTRAINT` and a `CREATE UNIQUE INDEX`), all copied verbatim, against one
  table and one contract module.

---

## 5. Per-milestone task breakdown

### M1 — The schema-map obligation and the enforcement notation

Design: `SCHEMA_DESIGN.md` § "S8 — `migrations/schema.sql` as a generated artifact (design)",
subsections "### Target design", "#### Exact header text", "### Explicit contracts",
"### Deletions"; and § "S9 — The enforcement record (design)", subsections
"#### The marker vocabulary", "#### The one paragraph added to `migrations/schema.sql`",
"### Explicit contracts", "### Currency", "### Sequencing", "### Deletions".

**Why S9's `migrations/schema.sql` half is folded into M1 rather than given its own milestone.**
Not a preference — the file's header can only be written once. § "S9 — … #### The one paragraph
added to `migrations/schema.sql`" states that its paragraph goes into "the header S8 already
rewrites… so the write-back phase produces one header and not two", and T1.1 is the task that
writes that header. A separate S9 milestone would either rewrite the twelve lines T1.1 just wrote
or be rewritten by them, which is the two-headers failure S9 names. S9's own sequencing verdict —
"write it now, before `0008`" — is satisfied by M1, the first milestone in the plan, and M1 is also
where the notation has to be installed for the seven later map edits to obey it (§ 3, "The marker
obligation"). The `design/` three-quarters of S9 stay out of this plan for the reason § 1 gives:
no milestone here edits `design/`, and the marking must follow the §2 content corrections the
write-back phase owns.

**T1.1 — Replace the `migrations/schema.sql` header, with S8's text and S9's paragraph inside it.**
Intent: the file stops claiming to be `pg_dump` output, starts carrying a head stamp, and states
the marker grammar its own annotations must use from here on.
Files: `migrations/schema.sql`, lines 1–12 only (the banner). T1.5 is the only body edit in this
milestone.
Design: § "S8 — … #### Exact header text" — copy the block verbatim, with
`Reflects: 0007_roleless_service_accounts` (the head at this milestone) — **and then insert
§ "S9 — … #### The one paragraph added to `migrations/schema.sql`"'s four comment lines verbatim
into it**, immediately after the sentence ending "never as standalone DDL." inside the `Scope:`
block, before the "PostgreSQL structural state only" sentence. One header, written once, in one
task. Do not append it after the closing `-- ====` rule and do not open a second banner.
Verification: `grep -c 'GENERATED DOCUMENTATION\|pg_dump --schema-only\|0005_auth'
migrations/schema.sql` returns `0`, and `grep -c 'Do not replace it with pg_dump output'
migrations/schema.sql` returns `1`. The removal pattern is narrowed to the regeneration
instruction rather than the bare word `pg_dump` because the S8 banner being installed itself
ends with "Do not replace it with pg_dump output." — a bare `pg_dump` pattern can never return
`0` against the header this task copies in. Also: the first 30 lines contain exactly one line
matching `^-- Reflects: `.
S9's half adds four more, all mechanical: `grep -c 'A comment that states a property carries the
marker' migrations/schema.sql` returns `1`; `grep -c 'A bare adjective is not a marking'
migrations/schema.sql` returns `1`; `grep -c 'HAND-MAINTAINED DOCUMENTATION' migrations/schema.sql`
returns `1` (one header, not two); and `sed -n '1,30p' migrations/schema.sql | grep -c '^-- Reflects: '`
still returns `1` — the insertion is four lines and the header is 23, so `Reflects:` stays inside
the 30-line window `scripts/check_schema_map.py` reads. **The `Scope:` sentence boundary falls
mid-line in S8's block** ("serve, never as standalone DDL. PostgreSQL structural state only - no"),
so the insertion splits that line; that is the intended edit, not a transcription error.
Dependencies: none.
Status: done

**T1.2 — Add `scripts/check_schema_map.py`.**
Intent: make "the map was updated" a machine-checkable property of a commit.
Files: create `scripts/check_schema_map.py`.
Design: § "S8 — … ### Explicit contracts", the four bullets under "How it is enforced" — head
from `ScriptDirectory.from_config(Config("alembic.ini")).get_current_head()` (no connection, no
`env.py` execution); stamp from the first 30 lines of `migrations/schema.sql`; non-zero exit
printing both values on mismatch, on an absent or malformed line, and when `get_current_head()`
raises on a multi-head graph.
Verification: `uv run python scripts/check_schema_map.py` exits `0` and prints nothing on
success; `uv run ruff check scripts/check_schema_map.py` clean. Structure it as a pure
`reflected_revision(text: str) -> str` plus a `main() -> int` so T1.4 can test the parser
without a subprocess.
Dependencies: T1.1 (the stamp it reads must exist).
Status: done

**T1.3 — Wire the check into `make lint` and pre-commit.**
Intent: the obligation runs where the repository's declared static checks run.
Files: `Makefile` (`lint` target, one new line `uv run python scripts/check_schema_map.py`);
`.pre-commit-config.yaml` (new local hook `schema-map-current`, `entry: uv run python
scripts/check_schema_map.py`, `language: system`, `pass_filenames: false`, `files: ^migrations/`).
Design: § "S8 — … ### Explicit contracts", "What invokes it" — including the note that
`make lint` is the guarantee and the hook is an early warning, since `pre-commit` is not a
declared dependency.
Verification: `make lint` exits 0 and its output shows the new command running; the hook's
1:1 correspondence with a `make lint` line holds for all five hooks.
Dependencies: T1.2.
Status: done

**T1.4 — Pin the check's contract.**
Intent: prove the check fails for the drift class that actually occurred.
Files: create `tests/unit/test_check_schema_map.py`. `scripts/` is not a package: load the
module with `importlib.util.spec_from_file_location`.
Assertions: three, every one of them against a `tmp_path` fixture header built inside the test,
and **none against the real `migrations/schema.sql`** — a header whose `Reflects:` line names a
revision parses to exactly that revision id; a stamp naming a revision other than the head exits
non-zero; a header with no `Reflects:` line exits non-zero. Drive the parse through
`reflected_revision(text)` and the two exit codes through `main()`, with the map path and the
head value supplied by the test (argument or `monkeypatch`), never read from
`migrations/versions/`.
**Scope decision — fixture-only, and it must not be relaxed.** This is a *unit* test, so it runs
inside the gate's `pytest -m unit` on every later task in the plan. Pinning the literal
`0007_roleless_service_accounts` against the real map would go red the instant T3.5 moves that
stamp to `0008_schema_conformance`, taking the gate down for the remainder of M3–M10 for a
reason no task budgets a fix for. The alternative — comparing the real map's stamp against
`ScriptDirectory.from_config(Config("alembic.ini")).get_current_head()` — was rejected because
it is not hermetic either: `0006` and `0007` are untracked, so on a checkout without them the
computed head is `0005_auth` while the committed stamp is ahead of it, and the assertion fails
on a working tree that is correct. Fixture-only assertions hold under both. End-to-end coverage
of the real file is not lost: `uv run python scripts/check_schema_map.py` runs in `make lint`
from T1.3 on, and every map-touching task from T3.5 onward lists it.
Verification: the gate. The three assertions are the mechanical acceptance criteria.
Dependencies: T1.2.
Status: done

**T1.5 — Mark the map's own annotations, and close Drift 10.**
Intent: the file that now carries the marker rule in its header obeys it, and the bare adjective
the grill found is replaced rather than corrected.
Files: `migrations/schema.sql`, body only. **Locate every line below by its text, not by its line
number** — the working tree is dirty and S1's unique key lands in the same block as the first of
them (§ "S9 — … #### The one paragraph …" notes the two edits do not collide).
Design: § "S9 — … #### The one paragraph added to `migrations/schema.sql`" for the `dataset_revisions`
replacement — copy the four-line marked block verbatim; § "S9 — … #### The marker vocabulary" for
the notation; § "S9 — … ### Deletions", first bullet, for why the words
`-- linear, gap-free, immutable` are replaced rather than qualified.

The edits, enumerated so this task is bounded:

1. `CREATE TABLE dataset_revisions (      -- linear, gap-free, immutable` → the `[spec]` block
   S9 spells out, naming invariant E, the per-dataset ingest lock, the absent writer, and the
   contrast with `releases_immutable` below. **This is Drift 10 and it is closed nowhere else.**
2. The three `-- trigger …` annotations (`releases_immutable`, `service_accounts_kind_guard`,
   `role_bindings_guard`) each gain a leading `[db]`. Each already names its object, so the edit
   is a token, not a rewrite.
3. The two index annotations (`-- partial unique index: at most ONE open ingest per dataset …`,
   `-- partial index sessions_subject_active (subject) WHERE revoked_at IS NULL`) each gain a
   leading `[db]` and, for the first, the object name `one_open_ingest_per_dataset`, which the
   annotation does not currently give and which the marking rule requires.
4. The restated constraints — `sessions`' `CHECK (idle_expires_at <= absolute_expires_at)`,
   `snapshots`' three provenance/layer CHECKs, and `products`' composite `FOREIGN KEY (dataset_id,
   project_id)` annotation — each gain a leading `[db]`. Their DDL is already spelled inline, which
   the marking rule accepts in place of an object name.

**Planning decision, recorded because it exceeds what S9 assigns itself.** § "S9 — … ### Deletions"
gives this file exactly one body edit, item 1 above. Items 2–4 are added here because the paragraph
T1.1 installs makes an unmarked property-stating annotation a defect *in this file*, and shipping
that rule beside ten annotations that break it is the S8 failure mode in miniature — a header whose
claims the body does not support. The set is enumerated rather than described so the sweep cannot
grow: no other comment in the file states a property. Column lists, section banners, path examples,
the RBAC narrative in §3 and the removed-role notes are not rules and are not marked.

Verification, all mechanical and all runnable without a database:
`grep -c 'CREATE TABLE dataset_revisions (      -- linear' migrations/schema.sql` returns `0`;
`grep -c '\[spec\] linear, gap-free, immutable' migrations/schema.sql` returns `1`;
`grep -- '-- trigger ' migrations/schema.sql | grep -vc '\[db\]'` returns `0`;
and every marker in the file is one of the three legal forms —
`grep -oE '\[(db|app|spec)[^]]*\]' migrations/schema.sql | grep -vcE '^\[(db|db [0-9A-Za-z_]+|app: src/huron/[^]]+|spec)\]$'`
returns `0`. **The pattern is anchored on the three marker words on purpose**: a bare
`\[[a-z][^]]*\]` also matches the two regex character classes the file already carries in its slug
CHECKs (`[a-z0-9]` and `[a-z0-9-]` — verified, they are the only bracketed tokens in the file
today), which would make the criterion impossible to pass. `make lint` still passes and the
`Reflects:` line is untouched by this task.
**What these checks do not do, stated rather than implied.** They prove no bare `[db]` in this file
names an object that is actually installed. § "S9 — … ### Currency" is explicit that the check which
would prove it needs the DDL applied to a database, and § "S8 — … ### Explicit contracts" already
established this repository has nowhere to run one (no `.github/workflows/`, every pre-commit hook
database-free, `alembic.ini` hard-coding one laptop's port). The cheap checks catch an unmarked
rule and an illegal marker — the two failure modes that actually occurred — and nothing here should
be read as catching the third. The partial substitute available now, and worth running once for the
ten markers this task adds: every object name they carry appears in `migrations/versions/*.py`
(`grep -l one_open_ingest_per_dataset migrations/versions/*.py`, and the same for each). That is
the one `grep` § "S9 — … ### Currency" says would have falsified Drift 6, and it proves the object
was written, not that it survived a later revision.
Dependencies: T1.1 (the header rule must exist before the body obeys it).
Status: done

---

### M2 — Dataset lifecycle vocabulary in `pkg/`

Design: `SCHEMA_DESIGN.md` § "S2 — … #### The `pkg/` `StrEnum` companions". Note the rule
stated there: exactly one enum lands now, because exactly one column has a consumer. Do not
create `ProductLifecycle` or `RevisionState`.

**T2.1 — Create `huron.pkg.catalog.lifecycle.DatasetLifecycle`.**
Intent: give the one lifecycle vocabulary with a live consumer a typed home, beside the other
pure-domain vocabularies.
Files: create `src/huron/pkg/catalog/lifecycle.py` with `DatasetLifecycle(StrEnum)`, members
`ACTIVE`, `RETIRED`, `SUPERSEDED`, mirroring the CHECK M5 adds. Follow
`src/huron/pkg/catalog/ingest.py`'s `IngestState` for module and docstring shape.
Design: § "S2 — … #### The `pkg/` `StrEnum` companions" (members and evidence) and § "S2 — …
### Target design" row 3 (the vocabulary and its two independent sources).
Verification: the gate, with `mypy --strict` and `ty` covering the new module and
`lint-imports` still green (`huron.pkg.catalog` is framework-free; a `StrEnum` adds no import).
Dependencies: none.
Status: done

**T2.2 — Type the repository's dataset lifecycle.**
Intent: replace the two bare strings that are the entire application-side footprint of S2.
Files: `src/huron/service/api/repository.py` — the `Dataset` dataclass field
`lifecycle_state: str` (line 97 as read) becomes `DatasetLifecycle`, and the bare `"ACTIVE"`
literal in `create_dataset` (line 542 as read) becomes `DatasetLifecycle.ACTIVE`. Locate both by
symbol, not by line number; the working tree is dirty and lines may have moved.
Design: § "S2 — … ### Deletions", the two replacements named there.
Verification: the gate. Acceptance: no API response shape changes — `DatasetLifecycle` is a
`str` subclass, so serialization is byte-identical; `web/src/lib/api/types.ts` is not edited and
the existing unit suite passes unmodified.
Dependencies: T2.1.
Status: done

**T2.3 — Pin the vocabulary.**
Intent: the enum's members are a contract, not an implementation detail.
Files: create `tests/unit/test_catalog_lifecycle.py`; extend the existing dataset-creation
assertion in `tests/unit/` if one names the literal `"ACTIVE"`.
Assertions: the member set is exactly `{ACTIVE, RETIRED, SUPERSEDED}`; each member's value
equals its name; a newly created dataset's `lifecycle_state` **is** `DatasetLifecycle.ACTIVE`
and compares equal to `"ACTIVE"`.
Verification: the gate, with `src/huron/pkg/catalog/lifecycle.py` at 100% line coverage.
Dependencies: T2.1, T2.2.
Status: done

---

### M3 — `0008` skeleton and cross-parent referential integrity

Design: `SCHEMA_DESIGN.md` § "S1 — Cross-parent referential integrity (design)", subsections
"### Target design", "### Explicit contracts", "### Deletions", "### Negative-write test".
Closes F1, and discharges F3's `releases.revision_id` row (S1's index covers it by prefix —
M4 must not add a second index there).

**T3.1 — Create the revision.**
Intent: establish the file, the chain, and the DDL string every later milestone appends to.
Files: create `migrations/versions/0008_schema_conformance.py` with
`revision = "0008_schema_conformance"`, `down_revision = "0007_roleless_service_accounts"`,
`branch_labels = None`, `depends_on = None`, `from migrations._ddl import execute_sql`, one
module-level `DDL = r"""…"""`, `upgrade()` calling `execute_sql(DDL)`, and a `downgrade()`
calling `execute_sql` on its own inline block. Shape model: `migrations/versions/0005_auth.py`.
Write a module docstring in house style — what the revision closes and which invariants it
serves — with no reference to this plan.
Design: § "Constraints that bind every task in this document", items 1 and 2.
Verification: `uv run python -c "from alembic.config import Config; from
alembic.script import ScriptDirectory; print(ScriptDirectory.from_config(Config('alembic.ini'))
.get_current_head())"` prints `0008_schema_conformance`; exactly one `DDL` constant and no
`op.create_check_constraint` / `op.create_index` call appears in the file.
Dependencies: M1 (the stamp check now demands T3.5 in the same change).
Status: done

**T3.2 — The S1 DDL block.**
Intent: a release can only cite a revision of its own dataset.
Files: `migrations/versions/0008_schema_conformance.py` — block 1 of `DDL`, and its mirror in
`downgrade()`.
Design: § "S1 — … ### Target design" — copy both SQL blocks verbatim, including the comment.
Three objects up (`dataset_revisions_id_dataset_id_unique`, the `releases` constraint swap,
`releases_revision (revision_id, dataset_id)`), and a downgrade that restores `0001`'s
single-column `releases_revision_id_fkey`. Note the deletion recorded in § "S1 — …
### Deletions": `releases_revision_id_fkey` is PostgreSQL's generated name and must be spelled
exactly; `upgrade()` drops it without `IF EXISTS` so a wrong name fails loudly.
Verification: `uv run pytest -m contract tests/contract/test_rbac_store.py` (which migrates to
head) passes — proving the block applies and the dropped name existed. Acceptance: after
migration, `pg_constraint` holds `releases_revision_dataset_fk` and
`dataset_revisions_id_dataset_id_unique`, and holds no `releases_revision_id_fkey`.
Dependencies: T3.1.
Status: done

**T3.3 — Introduce `tests/contract/test_catalog_store.py`.**
Intent: the catalog hierarchy gets the contract-test surface it has never had, and M5–M9 write
into it.
Files: create `tests/contract/test_catalog_store.py` — module docstring in the shape of
`tests/contract/test_rbac_store.py`'s, `pytestmark = pytest.mark.contract`, a
`PostgresContainer("postgres:16")` entry point, a `_migrate` that upgrades to head, and fixture
helpers `_insert_organization`, `_insert_project`, `_insert_dataset`, `_insert_dataset_revision`.
Design: § "S1 — … ### Negative-write test", which leaves the shared-versus-duplicated question
to this phase. **Planning decision: duplicate, do not share.** The two existing contract modules
each spin their own container and carry their own fixture helpers; a shared `conftest.py` would
couple three modules' schema assumptions to one helper set for no runtime saving, and `pyscn`
does not scan `tests/`, so the duplication costs nothing in the gate.
Verification: `uv run pytest -m contract tests/contract/test_catalog_store.py` passes.
Dependencies: T3.2.
Status: done

**T3.4 — Pin the composite foreign key.**
Intent: the audit's F1 proof must now fail, and the legitimate write must still succeed.
Files: `tests/contract/test_catalog_store.py`.
Design: § "S1 — … ### Negative-write test" — the refused insert (a release citing a revision of
another dataset under the same project) expecting
`asyncpg.exceptions.ForeignKeyViolationError`, paired with the same insert against the
revision's own dataset, which must succeed.
Verification: `uv run pytest -m contract tests/contract/test_catalog_store.py` passes; the
refused case fails against `0007` and passes against `0008` (check by running the module once
with `down_revision`-level migration if in doubt — this is the audit's proven insert).
Dependencies: T3.3.
Status: done

**T3.5 — Update the map and move the stamp.**
Intent: keep `make lint` green and put the map's diff beside the migration's.
Files: `migrations/schema.sql` — the `dataset_revisions` and `releases` blocks in §1
(new unique key, new composite FK, new index annotation), and `Reflects:
0008_schema_conformance`.
Design: § "S8 — … ### Explicit contracts", "What this obligates in `0008`"; § "S1 — …
### Deletions", final bullet.
Verification: `uv run python scripts/check_schema_map.py` exits 0; `make lint` passes.
Dependencies: T3.1, T3.2.
Status: done

---

### M4 — Foreign-key access paths, referential actions, and the subsumed objects

Design: `SCHEMA_DESIGN.md` § "S4 — Foreign-key access paths and referential actions (design)",
subsections "### Target design" (the 23-row table), "### The DDL", "### Explicit contracts",
"### Deletions". Closes F3, F4, F7.

**T4.1 — The S4 DDL block.**
Intent: every foreign key that grows with usage becomes reachable by index, the two strictly
subsumed objects go, and the referential action is stated where the choice is live.
Files: `migrations/versions/0008_schema_conformance.py` — block 2 of `DDL`, mirror prepended to
`downgrade()`.
Design: § "S4 — … ### The DDL" — copy both blocks verbatim: seven `CREATE INDEX`,
`DROP INDEX role_bindings_principal_scope`, `ALTER TABLE products DROP CONSTRAINT
products_dataset_id_fkey`, and the three re-declared role-catalog foreign keys. Do **not** add
an index on `releases (revision_id)` (discharged by M3) or on
`role_capabilities.capability_code` (declined, with reasons, in § "S4 — … ### Target design",
"Why `role_capabilities.capability_code` gets no index"). Do **not** use `CONCURRENTLY`.
Verification: both contract suites pass — proving the block applies and that
`products_dataset_id_fkey`, `role_capabilities_role_code_fkey` and
`role_capabilities_capability_code_fkey` were spelled as PostgreSQL generated them.
Acceptance, by catalog query on a migrated database: `pg_indexes` lists
`products_dataset_project`, `product_versions_snapshot`, `purge_records_revision`,
`snapshots_dataset`, `api_keys_project`, `role_bindings_role`, `role_bindings_scope`, and does
**not** list `role_bindings_principal_scope`; `pg_constraint` shows `confdeltype = 'c'` for
`role_capabilities_role_code_fkey` and `'a'` for the other two re-declared keys.
Dependencies: M3 (block 1 precedes block 2; S1 owns the `releases` index).
Status: done

**T4.2 — Pin the referential actions.**
Intent: prove the role catalog's delete behaviour, which is the only place in the schema where a
parent row is really deleted.
Files: `tests/contract/test_rbac_store.py` — new `_assert_*` helpers alongside the existing
trigger assertions, registered in `_assert_against`.
Design: § "S4 — … ### Explicit contracts", "Negative-write coverage" — three assertions:
deleting a `roles` row that still has a binding raises
`asyncpg.exceptions.ForeignKeyViolationError`; deleting a `capabilities` row still named by a
`role_capabilities` row raises the same; deleting a `roles` row whose bindings were removed
first succeeds **and** takes its `role_capabilities` rows with it. The third is the positive
control that proves the cascade is real. Index presence is not a behavioural rule and gets no
test.
Verification: `uv run pytest -m contract tests/contract/test_rbac_store.py` passes. Restore the
deleted seed rows within the test's own container or perform the deletes on a purpose-made role
so the seed-diff assertions in the same module still hold.
Dependencies: T4.1.
Status: done

**T4.3 — Update the map.**
Files: `migrations/schema.sql` — `role_bindings`, `role_capabilities`, `api_keys` (§3),
`purge_records` (§4), `snapshots`, `products`, `product_versions` (§5): the `-- index …`
annotations and the FK-action annotations.
Design: § "S4 — … ### Deletions", final bullet; § "S8 — … ### Explicit contracts". That bullet
places `products` in §1; it is wrong — the map carries `products` in §5
(`-- 5. Published representations`). The section numbers above are the file's, not the design's,
and are the ones to edit against.
Verification: `make lint` passes (the stamp is already `0008_schema_conformance`).
Dependencies: T4.1.
Status: done

---

### M5 — Closed state and lifecycle vocabularies

Design: `SCHEMA_DESIGN.md` § "S2 — Closed state and lifecycle vocabularies (design)",
subsections "### Target design" (the eleven-row table), "#### DDL", "#### What `0008` must do
about pre-existing data", "### Explicit contracts", "### Negative-write tests". Closes F2 for
the eleven S2 columns — eight of them by CHECK, three named as unsettleable.

**Drift 6 makes four of these eight a transcription, not a design choice — and the authority is
`design/catalog-search.html` §2.** The grill classified Drift 6 "code has diverged, design wins":
the authoritative schema sketch already spells `CHECK IN (…)` for five columns the database does
not carry, and this milestone plus M6 are what make those five assertions true. So the vocabulary
for `datasets.lifecycle_state`, `dataset_revisions.state`, `snapshots.state` and
`product_versions.state` is **copied from §2**, not derived here; § "S2 — … ### Target design"
already cites it as "CS §2 spells the CHECK verbatim" on all four rows, and no task may widen or
narrow one of them without the change going back into `design/catalog-search.html` §2 first.

**Checked member for member against §2's current text, and the result is one disagreement, which
is not a vocabulary.** Reading the live skeleton rather than the grill's transcription of it:

| Column | `design/catalog-search.html` §2 | This plan's DDL | Agrees? |
|---|---|---|---|
| `datasets.lifecycle_state` | `('ACTIVE','RETIRED','SUPERSEDED')` | same, same order | yes |
| `dataset_revisions.state` | `('COMMITTED','EXPIRED_PARTIAL','EXPIRED','PURGED','DEGRADED')` | same, same order | yes |
| `snapshots.state` | `('CANDIDATE','PUBLISHED','SUPERSEDED','FAILED')` | same, same order | yes |
| `product_versions.` **`status`** | `('CANDIDATE','PUBLISHED','STALE','SUPERSEDED','WITHDRAWN')` | same, same order, on the column named **`state`** | members yes; **column name no** |

The one disagreement is the column name, and it is already settled in both directions rather than
left hanging: § "S2 — … ### Target design", "Naming discrepancy, recorded so nobody 'fixes' it
later", rules that the migration wins and `0008` renames nothing — the shipped column is `state`,
consistent with every sibling table — and Drift 6's own text records the same fact
("`product_versions` has no `status` column at all"). **What this plan cannot do is leave §2 saying
`status`.** That correction is a `design/` edit, it is not carried by any drift finding as its own
item, and § 1's non-goals now hand it to the write-back phase explicitly. Note the asymmetry and do
not collapse it: on the *members* the design wins and the code changes here; on the *column name*
the code wins and the document changes there.

**The other four constraints in this milestone are not transcriptions and §2 does not carry them.**
§2 leaves `lifecycle_state` bare on `organizations`, `projects` and `products`, and writes
`purge_records(… approved_by <> requested_by enforced by CHECK)` with no state vocabulary at all.
Their evidence is § "S2 — … ### Target design" rows 1, 2, 4 and 8 — GOLD §2 for `products`, RAW §8
and API §6 for `purge_records`, and "today's reality" for the two `IN ('ACTIVE')` tripwires. Those
four are rules `0008` adds *ahead of* the authoritative sketch, which is §2 working as designed and
is exactly what S9's `[db 0008]` qualifier exists to mark; adding them to §2 is the write-back's
business, not M5's.

**T5.1 — The S2 DDL block.**
Intent: eight columns stop accepting values the design record does not define.
Files: `migrations/versions/0008_schema_conformance.py` — block 3 of `DDL`, mirror prepended to
`downgrade()`.
Design: § "S2 — … #### DDL" — copy both blocks verbatim, including the comments and the
`IN ('ACTIVE')` spelling for the two single-member lists. No `NOT VALID`, no defensive
`UPDATE … SET state = …` (§ "S2 — … #### What `0008` must do about pre-existing data" states
why). Three columns get nothing: `ingest_files.state`, `jobs.state`,
`reconciliation_findings.severity`.
**Four of the eight are transcribed from `design/catalog-search.html` §2** (see this milestone's
header): if a member in the copied DDL differs from §2's `CHECK IN (…)` for `datasets`,
`dataset_revisions`, `snapshots` or `product_versions`, that is a design change and not a typo —
stop and report rather than picking a side. The column `product_versions.status` in §2 is the one
known divergence and is settled: the constraint goes on `state`.
Verification: both contract suites pass. Acceptance: `pg_constraint` holds the eight
`*_vocabulary` names, all with `convalidated = true`.
Dependencies: M4 (block order); M2 (the `datasets` vocabulary is already typed in `pkg/`).
Status: done

**T5.2 — The folded-in digest format CHECK.**
Intent: the one `*_sha256` column in the schema without the house format constraint acquires it.
Files: same block 3, appended after the eight vocabulary constraints; mirror in `downgrade()`.
Constraint: `science_profiles_document_sha256_format CHECK (document_sha256 ~ '^[0-9a-f]{64}$')`.
Design: `SCHEMA_DESIGN.md` § "S5 — … ### Open questions" item 1, which specifies the constraint
and hands the decision to this phase; § "Current State" §4, "Regex CHECKs on identifiers and
digests", for the pattern every sibling column already carries.
Verification: both contract suites pass. Acceptance: `pg_constraint` holds
`science_profiles_document_sha256_format`.
Dependencies: T5.1.
Status: done

**T5.3 — Pin the nine constraints.**
Intent: nine refused writes, nine permitted writes.
Files: `tests/contract/test_catalog_store.py`.
Design: § "S2 — … ### Negative-write tests" — expect
`asyncpg.exceptions.CheckViolationError`. Three of the refusals are the audit's own proofs
replayed and must now fail: `UPDATE datasets SET lifecycle_state = 'BANANA'`, the empty-string
update against `projects.lifecycle_state`, and `dataset_revisions.state = 'NOT_A_STATE'`. Each
refusal is paired with a permitted write of a member of that column's set. The digest CHECK gets
the same treatment: a 63-character or uppercase digest refused, a valid 64-hex digest accepted.
Verification: `uv run pytest -m contract tests/contract/test_catalog_store.py` passes.
Dependencies: T5.1, T5.2, M3 (the fixture helpers).
Status: done

**T5.4 — Update the map.**
Files: `migrations/schema.sql` — the `lifecycle_state`, `state` and `severity` lines in §1, §2,
§4, §5 and §6 gain their vocabulary comment, or conspicuously lack one where the column is
deliberately unconstrained; `science_profiles.document_sha256` gains its format annotation.
Verification: `make lint` passes.
Dependencies: T5.1, T5.2.
Status: done

---

### M6 — Event `kind` vocabularies outside `audit_events`

Design: `SCHEMA_DESIGN.md` § "S3 — Event `kind` vocabularies (design)", subsections
"### Target design" (the five-row verdict table), "#### The `lineage_edges` pair, decided
together", "#### DDL", "### Explicit contracts", "### Negative-write tests". Closes F2 for four
of S3's five columns; `audit_events.kind` is held to M9, which rebuilds the relation it applies
to.

**T6.1 — The S3 DDL block, minus `audit_events`.**
Intent: a job kind names a runner that exists, a lineage node names a table that exists, and an
outbox kind is held to a shape without being held to a list.
Files: `migrations/versions/0008_schema_conformance.py` — block 4 of `DDL`, mirror prepended to
`downgrade()`.
Design: § "S3 — … #### DDL" — copy `jobs_kind_vocabulary`, `outbox_events_kind_format` and the
two `lineage_edges_*_kind_vocabulary` constraints verbatim, with their comments. **Omit the
`audit_events_kind_format` statement**; it belongs to M9, after the structural rebuild that
would otherwise destroy it, per § "S3 — … #### `audit_events` is partitioned — what that costs,
and the S6 dependency" and § "S6 — … ### Ordering". `jobs.kind` adopts the documented seven and no eighth member (§ "S3 — …
### Open questions" item 1 records that this is a deliberate tripwire).
**`jobs_kind_vocabulary` is the fifth of Drift 6's five and is transcribed, not designed.**
`design/catalog-search.html` §2 spells all seven values — `bronze_build`, `canonicalize`,
`product_run`, `validate`, `polaris_sync`, `retention`, `reconcile` — and they were checked
member for member against § "S3 — … ### Target design" row 1 and agree exactly, in the same order.
The design wins and this constraint is what makes §2's assertion true; a member that differs is a
design change belonging back in §2, not a correction to make here.
**The two `lineage_edges` constraints are not transcribed from §2 and disagree with it on column
names.** Their vocabulary comes from `design/catalog-search.html` **§3** ("typed nodes"), which §2
does not restate; §2's own skeleton line spells the columns `from_kind` / `to_kind` against `0001`'s
`upstream_kind` / `downstream_kind`. § "S3 — … #### The `lineage_edges` pair", "Naming discrepancy",
settles it the same way S2 settles `status`: the migration wins, `0008` renames nothing, and the §2
correction is Drift 8's, handed to the write-back phase in § 1.
Verification: both contract suites pass. Acceptance: `pg_constraint` holds the four names;
`audit_events` carries no new constraint yet.
Dependencies: M5 (block order).
Status: done

**T6.2 — Pin the four constraints, including the open verdict.**
Intent: prove both the enumeration and the deliberate non-enumeration.
Files: `tests/contract/test_catalog_store.py`.
Design: § "S3 — … ### Negative-write tests", the four-row table — expect
`asyncpg.exceptions.CheckViolationError`. Two assertions carry more weight than the rest and
must be written explicitly: **`outbox_events.kind = 'something.nobody.designed'` must be
accepted** (without it, narrowing the column later would be a green-test change), and
`lineage_edges.upstream_kind = 'gold_snapshot'` — a plausible near-miss, not a nonsense string —
must be refused on both ends. The permitted set includes a `gold_version → gold_version`
supersession edge.
Verification: `uv run pytest -m contract tests/contract/test_catalog_store.py` passes.
Dependencies: T6.1.
Status: done

**T6.3 — Update the map.**
Files: `migrations/schema.sql` — the `kind` annotations on `jobs`, `outbox_events` (§6) and
`lineage_edges` (§5).
Verification: `make lint` passes.
Dependencies: T6.1.
Status: done

---

### M7 — jsonb top-level type constraints outside `audit_events`

Design: `SCHEMA_DESIGN.md` § "S5 — jsonb object-shape constraints (design)", subsections
"### The enumeration, and F5's count", "### Target design" (the fifteen-row table),
"#### The DDL", "### Explicit contracts" (all four subsections), "#### Negative-write tests".
Closes F5 for fourteen of the fifteen columns; `audit_events.payload` is held to M9, which
rebuilds the relation it applies to.

**T7.1 — The S5 DDL block, minus `audit_events`.**
Intent: every jsonb column states its own top-level type, so no reader discovers at read time
that a column holds a bare string.
Files: `migrations/versions/0008_schema_conformance.py` — block 5 of `DDL`, mirror prepended to
`downgrade()`.
Design: § "S5 — … #### The DDL" — copy both blocks verbatim, with the comment. Fourteen
constraints: thirteen `= 'object'`, one `= 'array'` for `ingest_files.completed_parts`, and the
two nullable columns spelled `col IS NULL OR jsonb_typeof(col) = 'object'`. **Omit the
`audit_events_payload_is_an_object` statement**; it belongs to M9 (§ "S5 — … #### The S6
ordering dependency on `audit_events`"). `0004`'s two `snapshots.provenance` constraints are not
touched and appear in neither list.
Verification: both contract suites pass. Acceptance: `pg_constraint` holds the fourteen names,
and still holds `snapshots_provenance_states_an_origin` and
`snapshots_provenance_gold_is_derivation` unchanged.
Dependencies: M6 (block order).
Status: done

**T7.2 — Pin the fourteen constraints.**
Intent: fourteen refused writes, fourteen permitted writes, and four cases that carry the
design's actual decisions.
Files: `tests/contract/test_catalog_store.py` for twelve columns;
`tests/contract/test_rbac_store.py` for `policies.spec` and `role_bindings.conditions`, which
live in that module's table set.
Design: § "S5 — … #### Negative-write tests" — expect
`asyncpg.exceptions.CheckViolationError`. A table-driven helper over `(table, column, insert
template)` is the right shape for the bulk (`tests/` is not scanned by `pyscn`, `radon` or
`complexipy`, so neither a loop nor its absence is a gate concern), but four cases must be
written explicitly because each pins a decision rather than a constraint:
`UPDATE projects SET raw_retention_policy = '"just a string"'::jsonb` (F5's own proof,
replayed); `ingest_files.completed_parts = '{}'::jsonb` refused while `'[]'::jsonb` is accepted,
with the converse on any object column; and `'null'::jsonb` refused on
`snapshots.validation_evidence` and `lineage_edges.region` while SQL `NULL` is accepted on both.
Verification: `uv run pytest -m contract tests/contract/test_catalog_store.py` and
`… test_rbac_store.py` both pass.
Dependencies: T7.1.
Status: done

**T7.3 — Update the map.**
Files: `migrations/schema.sql` — every jsonb line in §1 (`projects`, `revision_amendments`),
§2 (`ingest_files`), §3 (`role_bindings`), §4 (`policies`, `science_profiles`), §5 (`snapshots`,
`product_versions`, `lineage_edges`) and §6 (`outbox_events`, `idempotency_records`, `jobs`,
`reconciliation_findings`) gains its shape annotation. The existing hand-written comments
(`-- shape varies by policy_type`, `-- urn:huron:snapshot-provenance:1`) stay.
Verification: `make lint` passes.
Dependencies: T7.1.
Status: done

---

### M8 — Ingest-session ↔ revision correspondence, and the reservation lifecycle

Design: `SCHEMA_DESIGN.md` § "S7 — Ingest-session ↔ revision correspondence (design)",
subsections "### The fact that decides the mechanism", "### Target design", "### Explicit
contracts", "### Data flow", "### Negative-write tests"; and § "S7a — Abort and retry semantics
(design)", subsections "### The decision", "### Target design", "### Explicit contracts",
"### Deletions", "### Negative-write tests". Closes F8 and lands S7a.

**Why S7a extends M8 rather than getting its own milestone.** Both changes are one table's
lifecycle rules — S7 says what a `COMMITTED` session must be true of, S7a says what an
`ABORTED`/`FAILED` one releases — and they interact in ways a reader must hold in one head:
the guard's `WHEN (NEW.state = 'COMMITTED')` is precisely what keeps it off the abort path that
frees the number, and `SCHEMA_DESIGN.md` § "S7a — … ### Explicit contracts", "Where this
interacts with S7's commit-time trigger" was proved with both objects on the same database. They
touch the same table, the same contract module (`tests/contract/test_catalog_store.py`), the same
`migrations/schema.sql` block (§2), and the same fixture helpers. Splitting them would duplicate
all four and separate two halves of one argument, for four DDL statements in total — comfortably
inside one subagent's budget. A separate milestone would be justified if S7a needed application
code; it needs none (§ "S7a — … ### Deletions": no Python symbol is made obsolete).

**Intra-milestone order:** T8.1 → T8.2 → T8.4 → T8.5 → T8.3. T8.3 updates the map for both
blocks and therefore runs last.

**T8.1 — The S7 guard.**
Intent: a session reports success only about a revision that exists, belongs to its dataset,
carries the number the ingest lock allocated, and holds the manifest digest it declared.
Files: `migrations/versions/0008_schema_conformance.py` — block 6 of `DDL`, mirror prepended to
`downgrade()`.
Design: § "S7 — … ### Target design" — copy `ingest_session_revision_guard()` and the
`ingest_sessions_revision_guard` trigger verbatim, with the comment, including the four-column
match and the `FOR KEY SHARE`. `BEFORE INSERT OR UPDATE … WHEN (NEW.state = 'COMMITTED')`, not
`BEFORE UPDATE`. **No Python change**: `IngestLease.revision_id` stays `UUID`,
`ingest_sessions.revision_id` stays `uuid NOT NULL UNIQUE`, and
`src/huron/pkg/catalog/{ingest,ports,models}.py` are untouched. No foreign key and no index is
added, so S4's count stands at 23 before `0008` and 22 after.
Verification: both contract suites pass; `migrations/_ddl.py`'s splitter handles the
dollar-quoted body (it already does for `0005`'s guards). Acceptance: `pg_trigger` holds
`ingest_sessions_revision_guard` on `ingest_sessions` with a `WHEN` clause naming `'COMMITTED'`.
Dependencies: M7 (block order).
Status: done

**T8.2 — Pin the guard, including the paths it must not block.**
Intent: prove the invariant and prove that ABORTED/FAILED remain representable.
Files: `tests/contract/test_catalog_store.py`.
Design: § "S7 — … ### Negative-write tests" — five assertions, expecting
`asyncpg.exceptions.RaiseError` (a plpgsql `RAISE`, **not** a foreign-key or check violation):
the audit's proof case (`COMMITTING → COMMITTED` with a `revision_id` naming nothing), the
cross-dataset case, the wrong-`revision_number` case, the positive control (the flip against the
revision the session reserved, which must succeed), and the terminal-state control
(`PREPARING → ABORTED` and `UPLOADING → FAILED` on a session whose `revision_id` names nothing,
both of which must succeed).
Verification: `uv run pytest -m contract tests/contract/test_catalog_store.py` passes.
Dependencies: T8.1, M3 (the `_insert_dataset_revision` helper).
Status: done

**T8.4 — The S7a reservation lifecycle.**
Intent: a revision number reserved by a session that ended `ABORTED` or `FAILED` returns to the
pool, so a retry can take it again, while a number a session committed stays spent forever.
Files: `migrations/versions/0008_schema_conformance.py` — block 7 of `DDL`, mirror prepended to
`downgrade()`.
Design: § "S7a — … ### Target design" — copy both SQL blocks verbatim, with the comment. Two
statements up: `ALTER TABLE ingest_sessions DROP CONSTRAINT
ingest_sessions_dataset_id_revision_number_key` (no `IF EXISTS`, per the house rule — the name is
`0001`'s and PostgreSQL-generated, so a misspelling must fail loudly) and `CREATE UNIQUE INDEX
one_claim_per_revision_number ON ingest_sessions (dataset_id, revision_number) WHERE state NOT IN
('ABORTED', 'FAILED')`. The downgrade drops the index and restores the total `UNIQUE`.
**The predicate excludes two states, not three.** `COMMITTED` stays *inside* it, so a committed
number can never be re-reserved; copying `one_open_ingest_per_dataset`'s three-state predicate is
the specific bug § "S7a — … ### Target design" warns against. No `CONCURRENTLY`. **No Python
change**: `IngestSession`, `IngestLease`, `TERMINAL_STATES` and `_TRANSITIONS` in
`src/huron/pkg/catalog/ingest.py` are untouched, and `ingest_sessions.revision_id` keeps its
total `UNIQUE` from `0001`.
**What makes this index safe past the durability point is a contract on future code, not DDL — do
not invent a DDL task for it.** A session stuck in `COMMITTING` is *inside* this predicate and keeps
holding its number, which is correct because it may already be durable; the rule that nothing may
move it out of `COMMITTING` into a failure state without first stating whether
`revisions/{nnnnnn}--{revision_id}` exists is carried in § 1's brief, alongside the allocator and
sweeper contracts, and settled in `SCHEMA_DESIGN.md` § "S7a — … ### The stranded envelope after the
durability point — resolved" and § "S7a — … ### Explicit contracts" item 6. Nothing in this task
changes on its account; it is recorded here so an implementer does not re-open it as a missing
constraint. `_TRANSITIONS` is *not* narrowed either — S7a open question 2 records that verdict and
why.
Verification: both contract suites pass — proving the block applies and that the dropped
constraint name existed. Acceptance, by catalog query on a migrated database: `pg_constraint`
holds no `ingest_sessions_dataset_id_revision_number_key`; `pg_indexes` lists
`one_claim_per_revision_number` and still lists `one_open_ingest_per_dataset`; the new index's
`pg_index.indpred` is not null.
Dependencies: T8.1 (block order; the two blocks are otherwise independent).
Status: done

**T8.5 — Pin the reservation lifecycle, including the write that must now succeed.**
Intent: prove that a retry after an abort works, that a committed number is still spent, and that
the dataset lock is a different guarantee from the number claim.
Files: `tests/contract/test_catalog_store.py`, alongside T8.2's cases.
Design: § "S7a — … ### Negative-write tests" — six assertions. Two carry more weight than the
rest and must be written explicitly:

- **The retry, which is the point, and which must now SUCCEED.** A session driven to `ABORTED`,
  then a new session inserted for the same `(dataset_id, revision_number)`: succeeds. This is the
  exact insert that fails against `0007` with `duplicate key value violates unique constraint
  "ingest_sessions_dataset_id_revision_number_key"`. The same again with `FAILED`, on a session
  that reached `COMMITTING` first.
- **A committed number is still refused.** A session committed at number `n`, then a new
  `PREPARING` session at `(dataset_id, n)`: rejected with
  `asyncpg.exceptions.UniqueViolationError` **naming `one_claim_per_revision_number` in its
  message**. This is the assertion that pins `COMMITTED` inside the predicate — a predicate
  excluding all three terminal states passes every other case here and fails this one.

The other four: the `ABORTED` row survives the retry still carrying its original
`revision_number` and `revision_id`; a second live session on the same dataset at a *different*
number is rejected **naming `one_open_ingest_per_dataset`**, not the new index (asserting on the
index name is what stops the two guarantees being mistaken for one); a dataset whose only ingest
aborted is still `ACTIVE` with zero revisions and
`coalesce(max(revision_number), 0) + 1` over `dataset_revisions` is 1; and, end to end, two dead
attempts at 1, a third committing 1 and a fourth committing 2 leave `dataset_revisions` holding
exactly `{1, 2}`.
**Not testable here, and deliberately not attempted: the durability-point contract.** No assertion
in this suite can pin "a failure state was written over a durable envelope" — the write that would
be wrong depends on a filesystem the database cannot see, and creating a sealed envelope is outside
a contract test's reach. What the schema keeps is the loud backstop: `dataset_revisions`' own
**total** `UNIQUE (dataset_id, revision_number)` from `0001`, which `0008` does not touch and which
turns a wrongly reused number into a refused reconciler import rather than a second revision 1. Do
not add a constraint or a trigger to close the gap; § 1's brief closes it, on the P2/P3 code.

**Leave the database clean, or T10.1 fails.** These assertions create rows that duplicate
`(dataset_id, revision_number)` across a dead and a live session — lawful under `0008`, unlawful
under `0007` — and the module shares one container with T10.1's round trip. Delete the sessions
these assertions create before the test returns, per R2.
Verification: `uv run pytest -m contract tests/contract/test_catalog_store.py` passes.
Dependencies: T8.4, M3 (the fixture helpers).
Status: done

**T8.3 — Update the map.**
Files: `migrations/schema.sql` — the `ingest_sessions` block in §2 gains a
`-- [db 0008] trigger ingest_sessions_revision_guard: …` annotation in the house one-line-of-intent
style, and gains a `-- [db 0008] one_claim_per_revision_number: …` annotation stating in one line
what the predicate buys, beside the existing `one_open_ingest_per_dataset` annotation that T1.5
marked.
**Corrected here on Drift 9's evidence: there is no `UNIQUE (dataset_id, revision_number)` line in
the map to replace.** An earlier draft of this task said to replace one. `SCHEMA_DESIGN.md`
§ "Phase 0 grill — … ### Drift 9" proves the map never carried that constraint — it is the only
unique constraint in the database `migrations/schema.sql` does not represent — and the
`ingest_sessions` block was re-read to confirm it: the block runs from `id uuid PRIMARY KEY` to
`updated_at`, followed by the single trailing `-- partial unique index: at most ONE open ingest per
dataset (per-dataset lock)` comment, and the total unique key appears nowhere in it. An implementer
following the old wording would search for a line that does not exist. **So this task adds two
annotations and replaces none**, and the drop of
`ingest_sessions_dataset_id_revision_number_key` is invisible in the map's diff — which is itself
the Drift 9 defect, closed here by the new annotation naming what now holds the number.
Design: § "S7 — … ### Target design"; § "S7a — … ### Deletions"; § "Phase 0 grill — … ### Drift 9".
Verification: `make lint` passes. Acceptance, mechanical:
`grep -c 'one_claim_per_revision_number' migrations/schema.sql` returns `1` and
`grep -c 'ingest_sessions_revision_guard' migrations/schema.sql` returns `1`; both lines carry a
`[db 0008]` marker; and no line of the file matches
`UNIQUE (dataset_id, revision_number)` for `ingest_sessions` either before or after this task.
Dependencies: T8.1, T8.4.
Status: done

---

### M9 — `audit_events`: structure and its two constraints

Design: `SCHEMA_DESIGN.md` § "S6 — `audit_events` partitioning (design)", subsections
"### Decision", "### Proof", "### Target design", "### Explicit contracts", "### Ordering",
"### Deletions". **Settled 2026-08-31: option B, drop the partitioning.** This milestone is not
gated and has one branch. § "S6 — … ### Not chosen — option A" is kept in the design as the record
of what was rejected; **no task here executes any part of it**, and nothing in this milestone is
conditional on a decision.

The design's DDL was executed end to end against a live PostgreSQL 16.13 (§ "S6 — … ### Proof"),
so the three behaviours an earlier draft of this milestone listed as unexercised — all of them
option-A behaviours — no longer arise.

**T9.1 — The de-partitioning block.**
Intent: `audit_events` stops being structure without benefit and acquires the uniqueness
guarantee and the ordered index its readers need.
Files: `migrations/versions/0008_schema_conformance.py` — block 8 of `DDL`, mirror prepended to
`downgrade()`.
Design: § "S6 — … ### Target design" — copy both SQL blocks verbatim, with the comment. Upgrade:
`ALTER TABLE audit_events RENAME TO audit_events_partitioned`, **`ALTER INDEX audit_events_pkey
RENAME TO audit_events_partitioned_pkey`**, `CREATE TABLE audit_events (… id uuid PRIMARY KEY …)`,
`INSERT … SELECT`, `ALTER TABLE audit_events_partitioned DETACH PARTITION audit_events_default`,
`DROP TABLE audit_events_default`, `DROP TABLE audit_events_partitioned`, `CREATE INDEX
audit_events_created_at ON audit_events (created_at, id)`. Downgrade: the mirror, restoring
`0001`'s exact shape — partitioned parent, `audit_events_default` child, composite
`PRIMARY KEY (id, created_at)`, no index — and it too renames the outgoing index
(`ALTER INDEX audit_events_pkey RENAME TO audit_events_plain_pkey`) beside its
`ALTER TABLE … RENAME`.

**The two `ALTER INDEX` statements are load-bearing and must not be dropped as noise.** Renaming
a table does not rename its indexes. Without them the name `audit_events_pkey` is still held by
the outgoing relation when the new one is created, and PostgreSQL silently names the new primary
key **`audit_events_pkey1`** — observed on the live run, not predicted, and a permanent artifact
in the schema with the same hazard in the downgrade. Neither statement carries `IF EXISTS` in
`upgrade()`, so a misspelled index name fails loudly.

Verification: both contract suites pass. Acceptance, by catalog query on a migrated database:
`pg_class` shows `audit_events` with `relkind = 'r'`; `SELECT count(*) FROM pg_inherits WHERE
inhparent = 'audit_events'::regclass` is `0`; `pg_class` holds no `audit_events_default` and no
`audit_events_partitioned`; `pg_indexes` lists `audit_events_created_at` over `(created_at, id)`;
and the primary key is a **single-column key on `id` named exactly `audit_events_pkey`** — assert
the name, not just the shape. That name assertion is what catches a regression on the `ALTER
INDEX` statements: drop either one and the migration still succeeds, the key is still on `id`
alone, and only the name betrays it as `audit_events_pkey1`. **This is a regression check against a
reproduced defect, not a hypothetical one.** `SCHEMA_DESIGN.md` § "S6 — … ### Proof" records an
independent re-verification on PostgreSQL 16.13: with the `ALTER INDEX` line present the key comes
out `audit_events_pkey`; with that one line removed and nothing else changed it comes out
`audit_events_pkey1`. A test that only asserts the key exists, or that it is on `id` alone, passes
in both runs and is therefore not the acceptance criterion. The same run re-confirmed that S3's and
S5's constraints apply cleanly to the rebuilt table in T9.2's order, and that upgrade-then-downgrade
is byte-identical to a pristine `0001`–`0007` database across a nine-row catalog comparison.
Dependencies: M8 (block order).
Status: done

**T9.2 — The two held-back constraints, after the rebuild.**
Intent: the audit kind is shape-constrained without being enumerated, and the payload is an
object — on the relation T9.1 leaves behind.
Files: same file — block 9 of `DDL`, immediately after block 8; in `downgrade()` the two
`DROP CONSTRAINT IF EXISTS` statements run **before** the structural reversal.
Design: § "S3 — … #### DDL" for `audit_events_kind_format` and § "S5 — … #### The DDL" for
`audit_events_payload_is_an_object` — **the constraint text is unchanged**; only their position is
fixed here, by § "S6 — … ### Ordering". Both were applied in this order on the live run and both
enforced their rules against the plain table with their text unchanged; adding either before the
rebuild attaches it to a relation block 8 destroys, so the requirement is real rather than
defensive.
**One comment does not come across.** The line above S5's statement reads "Recurses to every
existing partition and is inherited by every partition created later" — a true statement about a
relation that no longer exists. § "S6 — … ### Ordering" records that it goes; the design's S5 DDL
listing still carries it, so copy the `ALTER TABLE` statement and leave that comment behind.
Verification: both contract suites pass. Acceptance: `pg_constraint` holds
`audit_events_kind_format` and `audit_events_payload_is_an_object`, **exactly one row each**
(the relation has no children), both `convalidated`.
Dependencies: T9.1.
Status: done

**T9.3 — Pin the audit rules.**
Files: `tests/contract/test_catalog_store.py`.
Design: § "S3 — … ### Negative-write tests" row 2 and § "S5 — … #### Negative-write tests";
§ "S6 — … ### Explicit contracts", "Uniqueness".
Assertions: `audit_events.kind` refuses `'BANANA'`, `''`, `'has space'` and a 64-character name,
and **accepts both `'revision.committed'` and `'something.nobody.designed'`** — the second is
what makes the open verdict a tested decision; `audit_events.payload` refuses
`'"just a string"'::jsonb`, `'[]'::jsonb` and `'null'::jsonb`, and accepts `'{}'::jsonb`.
Plus the assertion that pins what the rebuild bought: two rows sharing an `id` with different
`created_at` values must be refused with `asyncpg.exceptions.UniqueViolationError` — the write the
partitioned shape allowed, and the guarantee the composite key could not make.
Verification: `uv run pytest -m contract tests/contract/test_catalog_store.py` passes.
Dependencies: T9.2.
Status: done

**T9.4 — Update the map.**
Files: `migrations/schema.sql` §6 — the `audit_events` block: the
`-- partitioned by created_at range` comment goes (§ "S6 — … ### Deletions"), the primary key
becomes `id PK`, and the `(created_at, id)` index is annotated.
Verification: `make lint` passes.
Dependencies: T9.1, T9.2.
Status: done

---

### M10 — Round-trip, deferral pins, and final map reconciliation

No new DDL. This milestone proves the revision is reversible, pins the deferrals that were
decided rather than overlooked, reconciles the map against the finished migration — including the
three omissions the Phase 0 grill proved and no other task owns — and discharges `0008`'s one
completion obligation under S9's notation.

**T10.1 — Prove the round trip.**
Intent: `downgrade()` is the exact inverse of `upgrade()`, across all nine blocks.
Files: `tests/contract/test_catalog_store.py` — one assertion that upgrades to head, downgrades
to `0007_roleless_service_accounts`, and upgrades to head again, in one container.
Acceptance: the probe set is **one object name per `DDL` block this revision creates**, and every
name in it is present after the first upgrade, absent after the downgrade, and present again
after the second. There is one probe set and no branch — all nine blocks ship. That is these
eight names: `releases_revision_dataset_fk` (block 1), `role_bindings_scope` (2),
`datasets_lifecycle_state_vocabulary` (3), `jobs_kind_vocabulary` (4),
`projects_raw_retention_policy_is_an_object` (5), `ingest_sessions_revision_guard` (6),
`one_claim_per_revision_number` (7) and `audit_events_created_at` (8 — block 9's two constraints
ride on the same relation and are covered by it).
**Two preconditions this assertion owns, both of which will fail the round trip if ignored.**

- **`ingest_sessions` must hold no duplicate `(dataset_id, revision_number)` pair when the
  downgrade runs.** The downgrade restores `0001`'s total `UNIQUE`, and rows left behind by
  T8.5's retry assertions are lawful under `0008` and unlawful under `0007`, so index creation
  fails — verified behaviour, and correct behaviour, per § "S7a — … Downgrade round-trips on a
  clean database, and refuses loudly on a dirty one". T8.5 cleans up after itself; this
  assertion must additionally assert the table is clean before it downgrades rather than
  assuming it, since the two tests share a container. See R2.
- **An `audit_events` row inserted before the downgrade must survive both directions.** Block 8
  rebuilds the relation with `INSERT … SELECT` in each direction; a row lost either way is R3's
  symptom and this is where it is caught.

Downgrade only to `0007`: § "S2 — … #### DDL", "Downgrade ordering matters", explains why going
further is fine but is `0006`'s concern, not this revision's.
Verification: `uv run pytest -m contract tests/contract/test_catalog_store.py` passes.
Dependencies: M9.
Status: done

**T10.2 — Pin the one audit proof that still succeeds.**
Intent: record `jobs.state`'s deferral as a tested decision rather than an oversight.
Files: `tests/contract/test_catalog_store.py` — one assertion that
`INSERT INTO jobs (… kind, state …) VALUES (…, 'reconcile', 'WAT', …)` **succeeds** after
`0008`, with a docstring explaining that the job state vocabulary is not settled and that
`kind` is what this revision closes.
Design: § "S3 — … ### Negative-write tests", final paragraph; § "S2 — … ### Open questions"
item 3.
Verification: `uv run pytest -m contract tests/contract/test_catalog_store.py` passes.
Dependencies: M6 (`jobs_kind_vocabulary` must exist for the row's `kind` to be legal).
Status: done

**T10.3 — Final map and gate reconciliation, including the three map omissions the grill proved.**
Intent: the map is accurate as a whole, not merely stamped.
Files: `migrations/schema.sql` — a full read-through against the finished `0008`, correcting any
block the incremental edits left inconsistent; the header's `Reflects:` line reads
`0008_schema_conformance`.
**Three enumerated corrections, from `SCHEMA_DESIGN.md` § "Phase 0 grill — database documentation
(2026-08-31)", each in this file and each owned by nobody else.** They are documentation fixes, not
implementation, and they are here rather than in the write-back phase only because
`migrations/schema.sql` is a file this plan already edits in eight tasks.

1. **Drift 11 — the map contains no index at all.** T3.5, T4.3, T8.3 and T9.4 add annotations for
   the indexes `0008` creates, which closes the finding only for new objects. The pre-existing
   non-constraint indexes the file still does not name are `jobs_claim`, `outbox_unprocessed` and
   `policy_attachments_scope`; `one_open_ingest_per_dataset` and `sessions_subject_active` appear in
   prose and were given `[db]` markers and, for the first, its object name by T1.5. The sixth,
   `role_bindings_principal_scope`, is **dropped by T4.1** and must not be added. Each of the three
   gains a `-- [db] <name>: <one line of what access path it serves>` annotation inside the table
   block it serves, per the header's `-- index …` convention.
2. **Drift 14 — `DEFAULT 1` is missing from the counter columns.** The grill's heading says five;
   its own body enumerates **seven** from `pg_attrdef` — `organizations.generation`,
   `organizations.version`, `projects.generation`, `projects.version`, `datasets.generation`,
   `datasets.version` and `ingest_sessions.etag`. Seven is the count to work from; re-derive it
   against the file rather than trusting either number. These are the only defaults in the database
   the map omits.
3. **`capabilities.description` is missing from the map.** The grill's column-by-column diff against
   `pg_attribute` found exactly one omitted column in the whole file and this is it — recorded under
   "Checked, no drift found", where it is easy to miss.

Also confirm what earlier milestones already discharged, and do not redo it: **Drift 13** (the map
hides `audit_events`' partitioning) is closed by T9.4, which removes the
`-- partitioned by created_at range` comment from a table that is no longer partitioned, and
**Drift 10** is closed by T1.5.
Verification: the full gate; `make lint`; both contract suites; `uv run python
scripts/check_schema_map.py` exits 0. Acceptance: `git diff --stat` shows
`migrations/schema.sql` touched in the same change set as
`migrations/versions/0008_schema_conformance.py`, which is the reviewer-visible property
§ "S8 — … ### Explicit contracts" asks for. For the three corrections, mechanically:
`grep -c 'jobs_claim\|outbox_unprocessed\|policy_attachments_scope' migrations/schema.sql` returns
`3`; `grep -c 'role_bindings_principal_scope' migrations/schema.sql` returns `0`;
`grep -oE 'DEFAULT 1( |,|$)' migrations/schema.sql | wc -l` returns `7` — **occurrences, not
lines**: the map writes `generation integer NOT NULL, version integer NOT NULL,` as one line, so a
line count returns four and would pass on a half-done edit; and
`grep -A 6 'CREATE TABLE capabilities' migrations/schema.sql | grep -c 'description'` returns `1`.
Dependencies: T10.1, T10.2.
Status: done

**T10.4 — Drop the `[db 0008]` qualifiers.**
Intent: `0008` has landed, so the markers that said "committed, not installed" now say something
false, and the notation's whole value is that a marker means what it says.
Files: `migrations/schema.sql` — every `[db 0008]` becomes `[db]`, the object name and the rest of
the annotation unchanged. Nothing else in the file changes.
Design: `SCHEMA_DESIGN.md` § "S9 — … ### Sequencing", "What `0008` inherits" — which puts this on
`0008`'s completion list "beside the map update S8 already puts there" and says it must be named
explicitly rather than left to memory; § "S9 — … #### The marker vocabulary" for what the two forms
mean.
**Carried from S9, and not softened: nothing mechanical catches a stranded qualifier.** A `[db 0008]`
left in the file after `0008` has landed is the same defect class as S8's stranded header — a
document asserting a state of the world that is no longer true — and `scripts/check_schema_map.py`
does not look at markers, `make lint` does not, and no other check in this repository does. The grep
below is a check this task runs once; it is not a check anything runs afterwards. Do not add a
linter for it: § "S9 — … ### Currency", "Why no script", declines that trade for a hand-written
record, and the check that would actually matter needs a migrated database this repository has
nowhere to run.
**The same edit is owed in `design/catalog-search.html` §2 and in S9's residue table (its F1, F8 and
K rows), and this plan does not make it** — no milestone here edits `design/`. It is listed in § 7
as an obligation of the whole change set with its owner named, so that "0008 has landed" does not
quietly mean "landed in one of the two documents that carry the markers".
Verification: `grep -c '\[db 0008\]' migrations/schema.sql` returns `0`; `grep -c '\[db\]'
migrations/schema.sql` returns the count T1.5 established plus every marker T3.5–T9.4 added, with no
annotation losing its object name in the edit (`grep -- '-- \[db\]' migrations/schema.sql` shows
each line still naming a constraint, index or trigger). `make lint` passes and
`uv run python scripts/check_schema_map.py` exits 0.
Dependencies: T10.3.
Status: done

---

## 6. Risk register

**R1 — PostgreSQL-generated constraint names.** `0008` drops five constraints the migrations
never named: `releases_revision_id_fkey` (M3), `products_dataset_id_fkey`,
`role_capabilities_role_code_fkey`, `role_capabilities_capability_code_fkey` (M4) and
`ingest_sessions_dataset_id_revision_number_key` (M8). None carries `IF EXISTS` in `upgrade()`,
by design.
*Symptom:* the contract run aborts with `constraint "…" of relation "…" does not exist`, and
every assertion in the module errors at migration time rather than failing an assert.
*Fallback decision point:* read the real name from a container migrated to `0007` —
`SELECT conname FROM pg_constraint WHERE conrelid = 'releases'::regclass` — and spell what is
there. **Do not** switch the statement to `DROP CONSTRAINT IF EXISTS` to get past it: that
converts a loud, correct failure into a migration that silently leaves the old constraint in
place.

**R2 — S7a's downgrade refuses on a database that exercised a retry, and T10.1 shares its
container with the test that exercises one.** Block 7's `downgrade()` restores `0001`'s total
`UNIQUE (dataset_id, revision_number)`. The rows T8.5's retry assertions create — a dead session
and a live one holding the same number — are lawful under `0008` and unlawful under `0007`, and
`tests/contract/test_catalog_store.py` spins **one** container for the whole module.
*Symptom:* every assertion in T8.5 passes, and T10.1 then fails inside `alembic downgrade` with
`could not create unique index "ingest_sessions_dataset_id_revision_number_key" … Key
(dataset_id, revision_number)=(…, 1) is duplicated`. The failure surfaces in the round-trip test
and points at the migration, which is the wrong place to look.
*Fallback decision point:* the migration is correct and the test fixture is not — the refusal is
the designed behaviour (§ "S7a — … Downgrade round-trips on a clean database, and refuses loudly
on a dirty one"), because those rows have no lawful representation under `0007` and an operator
must decide what becomes of them. **Do not soften the downgrade** to `CREATE UNIQUE INDEX …
WHERE` or to a `DELETE` of the dead sessions: that would silently destroy attempt history on a
real database. Fix it in the tests — T8.5 deletes the sessions it creates, and T10.1 asserts
`ingest_sessions` holds no duplicate pair before it downgrades. If test isolation proves
awkward, give T10.1 its own container rather than changing the DDL.

**R3 — M9 rebuilds a table; the downgrade must not lose rows.** M9 drops and recreates
`audit_events` and its DEFAULT child in each direction, moving rows with `INSERT … SELECT`.
*Symptom:* rows present before `upgrade()` are absent after `downgrade()`, or the second
`upgrade()` in T10.1 fails because `audit_events_default` still exists.
*Fallback decision point:* T10.1 inserts an `audit_events` row **before** the downgrade and
asserts it survives both directions — its acceptance now carries that requirement explicitly, so
this risk has a named owner rather than living only here. If the `INSERT … SELECT` round trip
cannot be made row-preserving in both directions, stop and report: a rebuild that cannot be
reversed is a different change from the one § "S6 — … ### Target design" describes and proved.

**R4 — A green gate that hides a red contract suite.** `addopts = "-m unit"` means the gate's
`pytest` run never executes a contract test, so a broken constraint or a migration that does not
apply can leave all ten gate commands green.
*Symptom:* the gate passes and `uv run pytest -m contract` fails, or is never run because Docker
is unavailable in the execution environment.
*Fallback decision point:* every milestone from M3 on lists its contract command explicitly and
is **not** complete without it. If Docker is unavailable, stop and report — do not mark a DDL
milestone verified on the unit gate alone, and do not add the contract marker to `addopts`
(that would make every developer's `make test` require Docker).

**R5 — `IN ('ACTIVE')` on `organizations` and `projects` is a deliberate tripwire.** M5
constrains two columns to a single value, and `web/src/routes/settings/organization/+page.svelte`
already renders a `SUSPENDED` option that contradicts `web/src/lib/api/types.ts`.
*Symptom:* a write path that reaches those columns — none exists today, since
`HierarchyRepository` is in-memory — raises `check_violation` and surfaces as a 500.
*Fallback decision point:* the constraint is correct and the writer is wrong; the fix is the
milestone-4 migration that defines the transitions and widens the list, per
§ "S2 — … ### Open questions" item 1. Do **not** widen the CHECK to accommodate a placeholder
`<select>`, and do not soften it to a format regex (§ "S2 — … ### Rejected alternatives"
explains why a regex here is a placeholder pretending to be an invariant).

---

## 7. Definition of done

The plan is complete when all of the following hold.

**The migration.**

1. `migrations/versions/0008_schema_conformance.py` exists with
   `down_revision = "0007_roleless_service_accounts"`, one module-level `DDL = r"""…"""`
   executed by `upgrade()` through `execute_sql`, and a `downgrade()` that is its exact inverse
   in reverse block order. No `op.create_check_constraint`, no `op.create_index`, no second DDL
   constant, no `NOT VALID`, no `CONCURRENTLY`.
2. `uv run alembic upgrade head` → `uv run alembic downgrade 0007_roleless_service_accounts` →
   `uv run alembic upgrade head` succeeds against a clean `postgres:16`, proven by T10.1 rather
   than by hand.

**The findings.**

3. F1, F3, F4, F5, F7 and F8 are closed as specified in `SCHEMA_DESIGN.md` §§ S1, S4, S5, S7.
4. F2 is closed for the eight S2 columns and for the four S3 columns outside `audit_events` —
   three by enumeration (`jobs.kind`, both `lineage_edges` ends) and one by format alone
   (`outbox_events.kind`, open by decision, not by omission). The three columns left with no
   constraint at all — `ingest_files.state`, `jobs.state`, `reconciliation_findings.severity` —
   are each named in this plan's non-goals with what settles them.
5. F6 and the `audit_events` halves of F2 and F5 are closed by M9's option-B rebuild:
   `audit_events` is a plain table with `PRIMARY KEY (id)` named `audit_events_pkey`, one btree on
   `(created_at, id)`, and both held-back CHECKs applied to it.
6. S7a is landed: `ingest_sessions_dataset_id_revision_number_key` is gone,
   `one_claim_per_revision_number` is present with a predicate excluding `ABORTED` and `FAILED`
   only, and `one_open_ingest_per_dataset` is untouched.

**The proofs.**

7. Every constraint, index-backed referential action and trigger `0008` adds is pinned by a
   refused write **and** a permitted write, in `tests/contract/test_catalog_store.py` or
   `tests/contract/test_rbac_store.py`, asserting the correct exception class for its mechanism.
8. The three audit proofs that must now fail do (`datasets.lifecycle_state = 'BANANA'`, the
   empty-string `projects.lifecycle_state`, `dataset_revisions.state = 'NOT_A_STATE'`), the two
   F1 and F8 inserts are refused, `projects.raw_retention_policy = '"just a string"'::jsonb` is
   refused, and the one proof that still succeeds by design (`jobs.state = 'WAT'`) is asserted to
   succeed.
9. Both open-vocabulary columns accept an undesigned kind, asserted explicitly.
10. The one write that must now **succeed** where `0007` refused it is asserted to succeed: a new
   `ingest_sessions` row taking the `(dataset_id, revision_number)` of a session that ended
   `ABORTED`. The write that must still be refused — the same insert against a `COMMITTED`
   session's number — is asserted to raise `UniqueViolationError` naming
   `one_claim_per_revision_number`.

**The gate.**

11. All ten gate commands green, on every milestone, with no `# noqa`, `# type: ignore`,
   `# pragma: no cover`, skip, xfail, or lowered threshold anywhere in the change set. Coverage
   at or above `fail_under = 75`, and every file touched at 100% line coverage unless a specific
   line is judged unreachable defensive code.
12. `uv run pytest -m contract tests/contract/test_catalog_store.py` and
    `… test_rbac_store.py` both pass against a live `postgres:16`.

**The map.**

13. `migrations/schema.sql` carries the S8 header verbatim **with S9's four-line marker paragraph
    inside its `Scope:` block** — one header, not two — no `pg_dump` instruction, no enumerated
    migration list, and `Reflects: 0008_schema_conformance`.
14. `scripts/check_schema_map.py` exists, runs in `make lint` and as a `schema-map-current`
    pre-commit hook, and is pinned by `tests/unit/test_check_schema_map.py`.
15. Every table block the nine DDL blocks touched is updated in the map, in the same change set
    as the migration, and the three map omissions the Phase 0 grill proved are closed: the three
    unrepresented indexes (Drift 11), the seven `DEFAULT 1` counter columns (Drift 14) and
    `capabilities.description`.

**The sweep.**

16. The four objects `0008` removes are gone and nothing references them:
    `releases_revision_id_fkey`, `products_dataset_id_fkey`, `role_bindings_principal_scope` and
    `ingest_sessions_dataset_id_revision_number_key`. The partitioned `audit_events` parent, its
    `audit_events_default` child and the composite `PRIMARY KEY (id, created_at)` are gone too.
17. No shim, no TODO, no speculative abstraction, no dead `pkg/` enum mirroring a CHECK whose
    writer does not exist. Exactly one enum lands: `huron.pkg.catalog.lifecycle.DatasetLifecycle`.
18. No comment, docstring, test name or user-facing string anywhere in the change set references
    this plan, its milestones, its tasks, or any checklist mechanics.

**The enforcement record.**

19. `migrations/schema.sql` states no property in a bare adjective. Every annotation in it that
    states a property carries a legal marker — `[db]` with the object that refuses the violating
    write, `[app: <module>]`, or `[spec]` — and `-- linear, gap-free, immutable` over
    `dataset_revisions` is gone, replaced by the `[spec]` block naming invariant E, the ingest lock
    and the absent writer. That is Drift 10, and it is closed in no other file.
20. **No `[db 0008]` qualifier survives in `migrations/schema.sql`.** `0008` has landed, so every
    one of them is now a false statement. **Nothing mechanical catches a stranded one** — not
    `scripts/check_schema_map.py`, not `make lint`, not any check this repository has — so T10.4's
    `grep -c '\[db 0008\]' migrations/schema.sql` returning `0` is a check someone runs, not a
    check that runs. `SCHEMA_DESIGN.md` § "S9 — … ### Sequencing" is the source of that warning and
    it is not softened here.
21. **Not discharged by this plan, and named so it is not mistaken for discharged.** The same
    qualifier drop is owed in `design/catalog-search.html` §2 and in S9's residue table (its F1, F8
    and K rows), and the three `design/` edits S9 designs — the §2 skeleton markers, the
    `<h3 id="enforcement">` subsection that defines them, and the `design/architecture.html` §5
    routing sentence — are not milestones here. No milestone in this plan edits `design/`. § 1's
    non-goals name their owner and the two orderings that bind them. **This plan is complete with
    those four items outstanding**; what it may not do is finish while claiming the notation is
    installed in both documents when it is installed in one.

---

## Verification — defects corrected

**Scope note, added 2026-08-31.** This section and `## Verification — cycle 2` below are the
record of two verification passes run **before** Karl settled gate D1 and the S7a abort/retry
semantics. Both therefore discuss an option-A branch, a gate D1 and an R2 fallback that the plan
above no longer contains. They are kept as history, unedited except where noted; where they
disagree with §§ 1–7, §§ 1–7 govern, and `## Verification — cycle 3` records what was re-checked
after the change. No D1 gate, option-A branch or R2 fallback survives anywhere outside these two
sections.

The six defects raised by the Phase 3 verification pass are corrected in place. One line each,
naming what changed and where.

1. **T1.4 no longer pins the real map's stamp** (`§5 M1, T1.4`). All three assertions are now
   `tmp_path` fixture headers exercised through `reflected_revision()` and `main()` with the head
   value supplied by the test, so the gate's `pytest -m unit` stays green after T3.5 moves the
   stamp to `0008_schema_conformance`; the task text states why the fixture-only scope was chosen
   over a `get_current_head()` comparison against the real file (that comparison is red on any
   checkout lacking the untracked `0006`/`0007`), and T3.1/T3.5 therefore stay separate tasks.
2. **T1.1's verification is now satisfiable** (`§5 M1, T1.1`). The removal grep is narrowed to
   `'GENERATED DOCUMENTATION\|pg_dump --schema-only\|0005_auth'` returning `0`, with a positive
   check that `'Do not replace it with pg_dump output'` matches exactly one line — the S8 banner
   contains that sentence, so the old bare-`pg_dump` pattern could never return `0`.
3. **T9.1's option-A index acceptance asserts attachment, not name** (`§5 M9, T9.1`). Child
   indexes are named after their partition, so the acceptance now compares
   `count(*) FROM pg_inherits WHERE inhparent = 'audit_events_created_at'::regclass` against the
   partition count and checks each child index's `indkey` over `(created_at, id)`; the child count
   is also corrected to thirteen bounded partitions plus `audit_events_default`.
4. **T9.2's option-A constraint count is computed, not literal** (`§5 M9, T9.2`). The acceptance
   now asserts `1 + count(*) FROM pg_inherits WHERE inhparent = 'audit_events'::regclass` rows per
   constraint name — fifteen after `audit_events_ensure_partitions(12)` — replacing the "three"
   carried over from S3's measurement on the one-child table.
5. **The R2 fallback and T10.1's probe set now agree** (`§5 M10, T10.1` and `§6, R2`). T10.1's
   probe set is redefined as one object name per `DDL` block the revision actually creates: the
   seven listed names with all eight blocks shipped, the first six under the R2 fallback, with
   `audit_events_created_at` explicitly excluded there; T10.1's dependency line and R2's fallback
   text both name the reduced set, so either path is mechanically checkable.
6. **Three `migrations/schema.sql` section references corrected** (`§5 M4, T4.3` and
   `§5 M7, T7.3`). `products` moves from §1 to §5 (with a note that `SCHEMA_DESIGN.md`
   § "S4 — … ### Deletions" carries the same error and the file's numbering governs);
   `ingest_files` moves from §1 to §2 and `policies` from "§2/§3" to §4.

No acceptance criterion was weakened and no milestone, gate construction or design decision was
changed.

---

## Verification — cycle 2

Second and final verification cycle. Every claim in `## Verification — defects corrected` was
re-checked against the source files rather than against the corrective pass's quotations.

**Result: VERIFIED for execution.** All six corrections hold, none weakened an acceptance
criterion, and no new coverage gap, ordering violation or broken cross-reference was introduced.
Five residual items are listed below; **all five are non-blocking** — an implementation subagent
executing this plan top to bottom will not fail or produce wrong work on any of them. There are
**no blocking defects**.

### The six corrections, re-checked against source

1. **T1.4 — fixture-only scope (defect 1).** Confirmed applied and confirmed consistent
   everywhere the stamp is referenced. `git ls-files migrations/versions/` returns
   `0001`–`0005` only; `0006_role_simplification` and `0007_roleless_service_accounts` exist on
   disk and are untracked, so the corrective pass's stated reason is factually true. It is,
   however, only the weaker half of the argument (see item 1 of the residuals). The decisive
   reason holds independently: between T3.1 (which makes the head `0008_schema_conformance`) and
   T3.5 (which moves the stamp), a real-file comparison is red on the canonical working tree
   too, taking the gate down for T3.2–T3.4. Fixture-only is correct under both readings.
   T1.4's text now says `tmp_path` fixture headers, "none against the real
   `migrations/schema.sql`", and head supplied by the test; no other task pins a literal stamp.
   **The end-to-end guarantee is not lost:** `scripts/check_schema_map.py` reads the real
   `migrations/schema.sql` and the real `ScriptDirectory` head, T1.3 wires it into `make lint`
   (verified: `Makefile:35` currently holds exactly four commands, so the new line is the fifth),
   and every map-touching task runs it — T3.5 names the script explicitly, and T4.3, T5.4, T6.3,
   T7.3, T8.3, T9.4 each require `make lint` to pass, with T10.3 naming the script again. The
   real stamp is therefore checked nine times across M1–M10.
2. **T1.1's grep (defect 2).** Verified against the actual file and the actual banner.
   `migrations/schema.sql:4` reads `GENERATED DOCUMENTATION, NOT EXECUTED`, `:6` is the only
   occurrence of `0005_auth` in the file, `:8` is the only `pg_dump --schema-only`, and all three
   sit inside lines 1–12, which the S8 banner replaces — so the new pattern returns `0` and is
   satisfiable. `SCHEMA_DESIGN.md` § "S8 — … #### Exact header text" does end with
   "Do not replace it with pg_dump output.", confirming the old bare-`pg_dump` pattern was
   unsatisfiable. The positive checks also hold: that sentence occurs once in the banner, and
   the banner carries exactly one line matching `^-- Reflects: ` (the prose line reads
   "and moves the Reflects line to the new head", which does not match the anchored pattern),
   inside a 24-line header, well within T1.2's first-30-lines window.
3. **T9.1's option-A index acceptance (defect 3).** Correct. `SCHEMA_DESIGN.md` § "S6 — …
   ### Target design — option A" creates `audit_events_created_at` on the parent before
   `SELECT audit_events_ensure_partitions(12)`, and the function's loop is
   `FOR month_offset IN 0..months_ahead` — thirteen bounded children, plus the pre-existing
   `audit_events_default`, is fourteen, which is the count T9.1 now asserts on both
   `pg_inherits` queries. The attachment-not-name assertion is the right mechanical form.
4. **T9.2's computed constraint count (defect 4).** Correct, and it generalizes: under option A
   `1 + 14 = 15`, under option B `pg_inherits` returns no children so the same expression yields
   `1`. The acceptance is therefore branch-independent, which is what the D1 gate requires.
5. **T10.1's conditional probe set (defect 5).** Both paths are enumerated and checkable. Each
   of the seven names was confirmed to be created by the block it is assigned to:
   `releases_revision_dataset_fk` (S1 target design), `role_bindings_scope` (S4 DDL),
   `datasets_lifecycle_state_vocabulary` (S2 DDL, one of exactly eight `*_vocabulary` names),
   `jobs_kind_vocabulary` (S3 DDL), `projects_raw_retention_policy_is_an_object` (S5 DDL),
   `ingest_sessions_revision_guard` (S7 trigger name — note the function is
   `ingest_session_revision_guard()`, singular, and T8.1 spells both correctly), and
   `audit_events_created_at`. The probe is sound under **both** D1 branches: option A creates it
   on the parent and its downgrade ends `DROP INDEX IF EXISTS audit_events_created_at`; option B
   creates the identical index and its downgrade drops `audit_events_plain`, taking the index
   with it. So it is present → absent → present either way, and T10.1 does not depend on the D1
   answer. R2's fallback text and T10.1's dependency line both name the six-name reduced set and
   both exclude `audit_events_created_at` for the same stated reason; they agree.
6. **The three `migrations/schema.sql` section references (defect 6).** Verified against the
   file's own section banners: §1 Hierarchy (`organizations`…`revision_amendments`), §2 Raw
   ingest (`ingest_sessions`, `ingest_files`), §3 Identity and RBAC (`role_bindings`,
   `role_capabilities`, `api_keys`), §4 Governance (`policies`, `purge_records`,
   `science_profiles`), §5 Published representations (`snapshots`, `products`,
   `product_versions`, `lineage_edges`), §6 Operational plumbing (`audit_events`,
   `outbox_events`, `idempotency_records`, `jobs`, `reconciliation_findings`). T4.3, T5.4, T6.3,
   T7.3, T8.3 and T9.4 are each correct against that numbering.

### Coverage, ordering and the S6 gate, re-confirmed after the edits

- **Coverage.** The design's eight S2 `*_vocabulary` constraints, five S3 constraints (four
  outside `audit_events`), seven S4 indexes plus two deletions plus three re-declared foreign
  keys, fifteen S5 constraints (fourteen outside `audit_events`, of which thirteen are
  `= 'object'` and one `= 'array'`), S1's three objects and one deletion, S7's function and
  trigger, and S8's header/script/hook all still map to a task. The schema carries exactly
  fifteen `jsonb` columns, matching S5's count and T7.3's table list (thirteen tables, with
  `snapshots` contributing two).
- **Ordering.** Block order 1–8 is unchanged, the one load-bearing rule (8 after 7) is still
  stated in T9.2, and the deletions still land in M3 and M4. R1's four generated names are still
  the four the design names.
- **The S6 gate holds.** No milestone before M9 writes a statement whose correctness depends on
  the D1 answer. The edits added no `audit_events` reference to M3–M8; the only edit outside M9
  that touches `audit_events` is T10.1's probe set, which was shown above to be branch-
  independent and which explicitly stands down under the R2 fallback.
- **Environment.** Every gate command is installed (`ruff`, `mypy`, `import-linter`, `ty`,
  `radon`, `complexipy`, `pyscn`, `testcontainers[postgres]` in `pyproject.toml`);
  `addopts = "-m unit --strict-markers"` and `fail_under = 75` are as §3 states; the `contract`
  marker is declared; `tests/contract/test_rbac_store.py` carries `PostgresContainer("postgres:16")`,
  `_migrate`, `_assert_against` and five `_assert_trigger_rejects_*` helpers as T3.3/T4.2 assume;
  `tests/contract/test_auth_store.py` asserts `CheckViolationError`; `migrations/_ddl.py`
  defines `execute_sql`; `scripts/` has no `__init__.py`, so T1.4's `importlib` note is right;
  `.pre-commit-config.yaml` has four hooks, so T1.3's "all five hooks" is right after it lands.

### Residual defects — all non-blocking

1. **T3.1's verification command is a syntax error as printed** (`§5 M3, T3.1`). The
   `uv run python -c "…"` string is wrapped between `from` and `alembic.script`, which raises
   `SyntaxError: invalid syntax` when run verbatim (confirmed by execution). *Correction:* break
   the line only inside the parentheses, e.g. `uv run python -c "from alembic.config import
   Config; from alembic.script import ScriptDirectory; print(ScriptDirectory.from_config(`
   `Config('alembic.ini')).get_current_head())"`, or replace it with
   `uv run alembic heads`, which prints the same fact in one word. *Non-blocking:* an
   implementation subagent will reflow the statement or reach for `alembic heads`; the intent
   is unambiguous. It should still be fixed, because a verification line is meant to be
   copy-pasted.
2. **§3's `make lint` description goes stale at T1.3** (`§3`). It is accurate today —
   `Makefile:35` is exactly `ruff check`, `ruff format --check`, `mypy`, `lint-imports`, which is
   the gate's first five minus `ty` — but T1.3 adds a fifth line and the sentence stops being
   true for every milestone from M1 on. *Correction:* append "and, from T1.3 on, the schema-map
   check". *Non-blocking:* nothing keys off the sentence; the gate is defined by its own ten
   commands.
3. **T2.3's third assertion has no designated home** (`§5 M2, T2.3`). Confirmed: nothing under
   `tests/` matches `"ACTIVE"` or `lifecycle_state`, so the task's conditional "extend the
   existing dataset-creation assertion in `tests/unit/` if one names the literal `"ACTIVE"`"
   evaluates to false and the assertion "a newly created dataset's `lifecycle_state` **is**
   `DatasetLifecycle.ACTIVE`" is left without a file. `src/huron/service/api/repository.py`
   does carry both targets (`lifecycle_state: str` at line 97, the `"ACTIVE"` literal at line
   542), so the assertion is writable. *Correction:* replace the conditional clause with a
   directive — a new `tests/unit/test_repository_dataset_lifecycle.py` driving
   `HierarchyRepository.create_dataset` and asserting the returned `lifecycle_state` is
   `DatasetLifecycle.ACTIVE` and equals `"ACTIVE"`. *Non-blocking:* an implementation subagent
   will place the assertion in the module T2.3 does create.
4. **T1.2 does not declare the seams T1.4 needs** (`§5 M1, T1.2` / `T1.4`). T1.4 drives `main()`
   "with the map path and the head value supplied by the test (argument or `monkeypatch`)", but
   T1.2 specifies only `reflected_revision(text) -> str` and `main() -> int`, with the map path
   and the head read from hard-coded locations. *Correction:* give T1.2 the signature
   `main(map_path: Path = MAP_PATH, head: str | None = None) -> int`, or state that the map path
   and the head accessor are module-level names T1.4 monkeypatches. *Non-blocking:* the
   `monkeypatch` route works against whatever module-level names the implementation chooses.
5. **R3 imposes a requirement on T10.1 that T10.1's own text does not carry** (`§6 R3` /
   `§5 M10, T10.1`). R3 says "T10.1 must insert an `audit_events` row **before** the downgrade
   and assert it survives both directions" under option B; T10.1 describes only the object-name
   probe set. *Correction:* add that row-survival assertion to T10.1's acceptance, conditioned on
   the option-B branch. *Non-blocking:* the implementation subagent is given the whole plan, and
   R3 is unambiguous about what T10.1 owes. **Fixed 2026-08-31** — option B is now the only
   branch, so the requirement is unconditional and T10.1's acceptance carries it in its own text.

Two smaller notes, recorded but not counted as defects. T4.3's parenthetical says
`SCHEMA_DESIGN.md` § "S4 — … ### Deletions" "places `products` in §1; it is wrong" — that bullet
in fact miscites all three groups (`products` as §1, the RBAC tables as §2, and it puts
`purge_records` in §5); T4.3's own actionable list is correct, so only the note under-describes
the design's error. And T1.4 pins three of the four failure modes S8's "How it is enforced"
specifies — the malformed-`Reflects:`-line case and the multi-head `get_current_head()` raise are
implemented by T1.2 but unpinned by any test; `scripts/` is outside `--cov=src/huron`, so this
costs nothing in the gate.

**Judgment: the plan is executable as it stands.** The six corrections hold, the S6/D1 gate is
intact, the round-trip probe set is valid under both D1 branches and under the R2 fallback, and
the real `migrations/schema.sql` stamp remains mechanically checked nine times across the plan.
The five residuals are cosmetic or self-correcting; item 1 is worth a one-line fix before
execution purely so no verification line in this plan is un-runnable as printed.

---

## Verification — cycle 3

Run 2026-08-31, after Karl settled gate D1 (option B) and the S7a abort/retry semantics. This
cycle checks only what those two decisions changed; cycles 1 and 2 stand for everything else,
under the scope note at the head of `## Verification — defects corrected`.

**Result: VERIFIED.** No blocking defect. Four cycle-2 residuals remain open and remain
non-blocking; one was discharged by this edit. Three items found during this pass are recorded
below, all fixed in place.

### S7a coverage, checked in both directions

Every element of `SCHEMA_DESIGN.md` § "S7a — Abort and retry semantics (design)" maps to a task,
and every new task has a design basis.

| S7a element | Task |
|---|---|
| `DROP CONSTRAINT ingest_sessions_dataset_id_revision_number_key` | T8.4; § 7 item 16 |
| `CREATE UNIQUE INDEX one_claim_per_revision_number … WHERE state NOT IN ('ABORTED','FAILED')` | T8.4, with the two-state-not-three predicate called out explicitly |
| The `downgrade()` mirror | T8.4; round-tripped by T10.1 |
| Six negative-write cases | T8.5 — the retry that must now succeed, the committed number still refused, the surviving dead row, the dataset lock asserted by index name, the empty dataset, and gap-free end to end |
| Error behavior (`UniqueViolationError` naming the index) | T8.5, on both the refusal and the lock case |
| Deletions ("nothing else"; no Python symbol obsolete) | T8.4 states `ingest.py` is untouched |
| `migrations/schema.sql` goes stale | T8.3 |
| Contract: allocate from `dataset_revisions` with `coalesce` | § 1 non-goals, "Carried forward as a brief" |
| Contract: TTL sweeper must write a terminal state | same brief |
| Contract: the retry mints a new `revision_id` | same brief |
| Contract: a brand-new dataset survives its failed first ingest, empty — no DDL | brief, and asserted by T8.5's empty-dataset case |
| Open question 1 — the stranded sealed envelope | § 1, its own flagged paragraph, not inside a brief — **superseded in cycle 4: resolved, and now the fourth bullet of the S7a brief** |
| Open question 2 — no transition guard in the database | § 1, the model-change bullet |
| Downgrade refuses on a dirty database | R2, and T10.1's first precondition |
| Probe coverage of the new block | T10.1, `one_claim_per_revision_number` as block 7's name |

**Placement.** S7a extends M8 rather than taking its own milestone. The reasoning is written into
M8's header: one table, one contract module, one map block, one set of fixture helpers, four DDL
statements in total, and two halves of a single argument — the S7 guard's
`WHEN (NEW.state = 'COMMITTED')` is exactly what keeps it off the abort path S7a defines, and the
design proved the two objects together on one database. M8 remains sized for one subagent and is
still smaller than M4 or M7.

### M9's option-A remnants are gone

Searched §§ 1–7 for every option-A artifact and found none: no `audit_events_ensure_partitions`,
no `months_ahead`, no bounded-partition count (thirteen/fourteen/fifteen), no `pg_inherits`
child-count acceptance, no `tableoid::regclass` assertion, no BRIN, no idempotency assertion on a
partition-creating function, and no branch-conditional acceptance criterion anywhere. M9's header,
its four tasks, the § 4 milestone table and the § 3 block list each describe exactly one path.
Three mentions of option A survive on purpose and are not remnants: § 2 and M9's header both say
it is kept in the design as a "Not chosen" record and that **no task here may execute it**, and
§ 5 M7's "thirteen `= 'object'`" is S5's constraint count, unrelated.

Every `audit_events` mention in a milestone other than M9 was re-read. M3–M5 have none. M6 and
M7 hold their one `audit_events` statement back to M9 because M9 rebuilds the relation they would
attach to — re-worded from "by the D1 gate", which is the only change either needed. M8 has none.
M10's single mention is T10.1's probe of `audit_events_created_at`, which block 8 creates and
block 8's downgrade drops.

**The corrected S6 DDL is reflected.** T9.1 now names both `ALTER INDEX … RENAME` statements — in
the upgrade and in the downgrade — explains that renaming a table does not rename its indexes, and
records that `audit_events_pkey1` was observed rather than predicted. **The acceptance criterion
catches a regression on exactly that:** it asserts the primary key is named `audit_events_pkey`,
not merely that it is a single-column key on `id`. Dropping either `ALTER INDEX` leaves a migration
that succeeds and a key that is still on `id` alone, so the name is the only thing that betrays it,
and the old acceptance text — which checked `relkind`, `pg_inherits` and the key's shape — would
have passed.

### Gate D1 and risk R2

No reference to an open gate D1 or to the old R2 fallback survives in §§ 1–7. Enumerated:

- **D1** appears twice outside the historical sections, both in § 2, both as the settled record
  ("settled 2026-08-31, option B"). The § 4 milestone table's `Gated` column is removed rather
  than filled with ten `no`s. The `⛔ GATED ON D1` marker on M9's heading is gone.
- **D0** is kept as a forward-looking note under its own subheading, explicitly "open, and no
  longer a gate", with the reason it no longer blocks anything.
- **R2** is not deleted. It is replaced by a real risk found during this pass (below), so the
  register still has five entries and R3–R5 keep their numbers and their inbound references. Four
  entries would have been within the 3–5 range, but renumbering would have broken cycle 2's
  citations of `§6 R3` for no gain, and the replacement risk is genuine rather than promoted to
  fill a slot.
- The two `## Verification` sections from cycles 1 and 2 still discuss D1, option A and the old R2
  throughout. They are the record of passes run before the decision and are marked as such by a
  dated scope note at the head of the first, which states that §§ 1–7 govern on any disagreement.
  Cycle 2's residual 5 is annotated "Fixed 2026-08-31" where this edit discharged it.

### The DDL block count

`0008` holds **nine** blocks. Checked at every point the count or a block number appears:
§ 3's block list (1–9, with "9 must follow 8" as the one load-bearing rule and block 7 stated as
order-free per S7a's own text); the per-task `block N of DDL` lines, which are unique and cover
1–9 with no gap and no duplicate (T3.2=1, T4.1=2, T5.1=3, T6.1=4, T7.1=5, T8.1=6, T8.4=7, T9.1=8,
T9.2=9); T10.1's intent line ("all nine blocks"); T10.1's probe set, which is **eight** names —
one per block, block 9's two constraints riding on block 8's relation — and is now unconditional;
and § 7 item 15 ("the nine DDL blocks"). § 7 item 16's deletion list went from three objects to
four, and § 4's "deletions early" rationale and R1's generated-name list were reconciled to match
(R1 now names five generated constraints, not four).

### Found during this pass, and fixed

1. **T8.5 and T10.1 share a container, and T8.5's rows make T10.1's downgrade fail.**
   `tests/contract/test_catalog_store.py` spins one `PostgresContainer` for the whole module. The
   retry assertions leave a dead session and a live session holding the same
   `(dataset_id, revision_number)` — lawful under `0008`, unlawful under `0007` — so the round
   trip fails inside `alembic downgrade` with `could not create unique index … is duplicated`,
   pointing at the migration when the fixture is at fault. This is the new **R2**, with the
   explicit instruction not to soften the downgrade (the refusal is designed behaviour, per
   § "S7a — … Downgrade round-trips on a clean database, and refuses loudly on a dirty one"), plus
   a cleanup obligation in T8.5 and a precondition assertion in T10.1.
2. **The design's S5 DDL listing still carries a comment that S6 retired.** The line above
   `audit_events_payload_is_an_object` reads "Recurses to every existing partition and is inherited
   by every partition created later" — true of a relation `0008` destroys.
   `SCHEMA_DESIGN.md` § "S6 — … ### Ordering" records that it goes and assigns the edit to S5, but
   the S5 block is unedited, so an implementation subagent copying "verbatim" would carry it in.
   T9.2 now says to copy the `ALTER TABLE` statement and leave that comment behind. The constraint
   text itself is unchanged, as both S3 and S6 require.
3. **The plan cited "Phase 4" for roadmap reconciliation.** The `/design-plan` phases were
   renumbered and it is now Phase 5; § 1's "another phase owns it" bullet is corrected, with a note
   that `SCHEMA_DESIGN.md` § "S6 — … ### Open questions" still says Phase 4.

### Carried, not fixed

Cycle 2's residuals 1–4 are untouched and remain non-blocking: T3.1's verification command is a
syntax error as printed; § 3's `make lint` description goes stale at T1.3; T2.3's third assertion
has no designated file; T1.2 does not declare the seams T1.4 monkeypatches. None interacts with
either decision, and each is self-correcting for an implementation subagent holding the whole plan.
Residual 1 is still worth a one-line fix before execution.

### What this cycle did not do

It did not apply `0008`, run either contract suite, or start a database. The DDL claims it relies
on are the ones `SCHEMA_DESIGN.md` records as executed against a live PostgreSQL 16.13 — S6's
de-partitioning block including the `ALTER INDEX` correction, and S7a's constraint swap, the retry,
the committed-number refusal and the dirty-downgrade refusal. Everything above is a check of the
plan against the design and against the repository's own files.

---

## Verification — cycle 4

Run 2026-08-31, after S7a's stranded-envelope open question was resolved and S6's corrected DDL was
re-verified on a live database. This cycle checks only what those two changes touch; cycles 1–3
stand for everything else, under the scope note at the head of `## Verification — defects
corrected`. **Result: VERIFIED.** No blocking defect, no new risk, no change to the milestone
sequence, the task list, or the nine DDL blocks.

### What changed

1. **S7a open question 1 is resolved and is now a contract, not a question.**
   `SCHEMA_DESIGN.md` gains § "S7a — … ### The stranded envelope after the durability point —
   resolved" and § "S7a — … ### Explicit contracts" item 6. The resolution rests on two facts in the
   record: `src/huron/pkg/catalog/ingest.py` line 39 makes `ABORTED` unreachable from `COMMITTING`
   while `FAILED` is reachable, so **the single edge `COMMITTING → FAILED` is the entire hole**; and
   `design/layer-raw.html` §5's crash table already mandates roll-forward past step 6. The contract:
   nothing leaves `COMMITTING` for a failure state without first determining whether the rename
   happened; only a proven-absent envelope may be failed. **The DDL is unchanged** — `COMMITTING`
   sits inside `one_claim_per_revision_number`'s predicate, so a session of unknown fate keeps its
   number, which is correct — and the backstop is loud: `dataset_revisions`' own total
   `UNIQUE (dataset_id, revision_number)` turns a wrongly reused number into a refused reconciler
   import rather than a second revision 1.
2. **§ 1 carries it as the fourth S7a brief bullet**, replacing the flagged open-question paragraph,
   and the sentence that introduced "the three follow-ups" now reads four. The sweeper bullet and
   the new bullet are marked as one obligation implemented together: never writing a terminal state
   strands the dataset lock, writing one unconditionally over an expired `COMMITTING` session
   strands a sealed envelope.
3. **T8.4 and T8.5 carry it in the plan's existing form for contracts on future code.** T8.4 states
   that no DDL expresses this and none is to be invented, and that `_TRANSITIONS` is not narrowed;
   T8.5 states that the contract is not testable from a contract suite (the database cannot see the
   filesystem) and that the schema-side backstop is `dataset_revisions`' untouched total `UNIQUE`.
   Neither task's files, DDL, dependencies or acceptance criteria change.
4. **T9.1's acceptance criterion is tied to the reproduced defect.** It already asserted the primary
   key is named exactly `audit_events_pkey`; it now records why that assertion and not a weaker one
   — `SCHEMA_DESIGN.md` § "S6 — … ### Proof" gains an independent re-verification on PostgreSQL
   16.13 showing the key comes out `audit_events_pkey` with the `ALTER INDEX` line and
   `audit_events_pkey1` with that one line removed, plus the two CHECKs applying cleanly in T9.2's
   order and a byte-identical nine-row catalog comparison after upgrade-then-downgrade. A test
   asserting only that the key exists, or that it is single-column on `id`, passes in **both** runs
   and is therefore not the criterion.

### Re-checked, and not stale

- **S7a's open-question numbering.** Resolving item 1 renumbered the transition-guard note from 2 to
  3, and § 1's model-change bullet — the only live citation of it — is corrected. The new item 2 is
  the `_TRANSITIONS` narrowing verdict; § 1's bullet now names both. Cycle 3's coverage table keeps
  its historical rows, with the stranded-envelope row annotated as superseded here.
- **The S7a coverage table's other rows still hold.** All four DDL rows, the six negative-write
  cases, the error-behaviour row, the deletions row, `migrations/schema.sql`, and the three original
  brief contracts are unchanged; the table gains no obligation, because the new contract is code,
  not DDL, and lands in the brief the table already points at.
- **Nine blocks, unchanged.** No block is added, removed or reordered; T8.4 is still block 7, T9.1
  block 8, T9.2 block 9, and T10.1 still probes eight names. § 7 item 15 and § 7 item 16's
  four-object deletion list are unaffected.
- **The risk register is unaffected.** R2 (T8.5's rows versus T10.1's downgrade) is untouched, and
  the new contract adds no execution risk to `0008` because it constrains code that does not exist.
- **The gates are unaffected.** D1 stays settled (option B); D0 stays open and non-gating; no new
  gate is created — the residual P3 question (which component performs the storage consult, and the
  finding severity it raises) blocks nothing in this plan and is recorded in § 1 and in
  `SCHEMA_DESIGN.md` § "S7a — … ### Open questions" item 1.
- **Cycle 2 and 3 residuals are unchanged.** T3.1's syntax-error verification command, § 3's
  `make lint` description, T2.3's undesignated file, and T1.2's undeclared seams all remain open and
  non-blocking; none interacts with either change.
- **No `migrations/`, `design/`, skill or command file was edited.** The two design-document
  corrections S6 raises are still Phase 5's, and the `design/layer-raw.html` text this cycle relies
  on was read, not rewritten.

---

## Verification — cycle 5

Run 2026-08-31, after the Phase 0 documentation grill added eleven drift findings (6–16) plus an
addition to Drift 4, and after S9 — the enforcement record — was designed in response. This cycle
checks only what those two additions touch; cycles 1–4 stand for everything else, under the scope
note at the head of `## Verification — defects corrected`.

**Result: VERIFIED, with one plan defect found and fixed and four obligations recorded as
outstanding by design.** No DDL changed, no milestone was added or removed, the nine `DDL` blocks
are untouched, and no decision cycles 1–4 settled was reopened.

### Where S9 was placed, and why

**The `migrations/schema.sql` half is folded into M1. The `design/` three-quarters are not in this
plan at all.**

M1, not a new milestone, because the header can only be written once. § "S9 — … #### The one
paragraph added to `migrations/schema.sql`" requires its paragraph to go inside "the header S8
already rewrites… so the write-back phase produces one header and not two", and T1.1 is the task
that writes that header. A separate S9 milestone would either overwrite T1.1's twelve lines or be
overwritten by them. M1 also satisfies S9's own sequencing verdict — "write it now, before `0008`"
— by being first, and it is where the notation must exist for the seven later map edits to obey it:
adopted after M3–M9, the notation arrives with a backlog of eight unmarked annotations.

The `design/` edits stay out because no milestone in this plan edits `design/`, and because
§ "S9 — … ### Explicit contracts" requires the marking to follow the §2 content corrections
(Drifts 7, 8, 16 and the two column-name fixes) that only the write-back phase owns — "S9 owns the
marking, never the content. Apply markers after those corrections, or accept re-marking the
corrected lines." Splitting on that seam costs one thing, and § 1 now names it: the header paragraph
M1 installs cites `design/catalog-search.html` §2 for the marker definitions, so it is a dangling
reference until the subsection exists. The citation is by document and section rather than by line,
so it survives the content corrections; and the write-back phase runs before any implementation
subagent executes a milestone, so the ordering holds in the normal sequence. It is recorded as a
requirement rather than left to that coincidence.

### S9 coverage, checked in both directions

| S9 element | Where it lands |
|---|---|
| The four-line paragraph inside `migrations/schema.sql`'s `Scope:` block | T1.1, with the mid-line sentence boundary called out |
| One header, not two | T1.1; § 7 item 13; `grep -c 'HAND-MAINTAINED DOCUMENTATION'` returns 1 |
| Line 63 → the `[spec]` block (Drift 10) | T1.5 item 1; § 7 item 19 |
| The marker vocabulary binding on every later map edit | § 3, "The marker obligation" |
| `[db 0008]` vs `[db]` on map annotations | § 3, "The one ambiguity in that rule, resolved here" |
| `0008`'s completion obligation — drop every `[db 0008]` | T10.4; § 7 item 20 |
| S9's warning that nothing mechanical catches a stranded qualifier | T10.4 and § 7 item 20, both unsoftened |
| "Why no script" — the deep check has nowhere to run | T1.5's stated limits; T10.4's instruction not to add a linter |
| `design/catalog-search.html` §2 skeleton markers | § 1 non-goals, write-back phase, with two orderings |
| `<h3 id="enforcement">` subsection: legend, reader contracts, currency rule, residue table | same bullet |
| `design/architecture.html` §5 routing sentence | same bullet |
| Residue table's F1, F8 and K rows moving when `0008` lands | § 7 item 21 |
| Drift 12 explicitly **not** S9's to close | § 1's Phase 5 handover, stated as such |
| Deletions: line 63; §5's acceptance-test sentence; §2's unattributed `releases` prose | first in T1.5, other two in the § 1 handover |

Reverse direction: every task added this cycle has an S9 basis, with **one exception, marked as a
planning decision in the task itself** — T1.5 items 2–4, which mark the ten property-stating
annotations already in `migrations/schema.sql`. § "S9 — … ### Deletions" gives that file exactly one
body edit. The extension is justified in T1.5 and bounded there by enumeration: the header paragraph
T1.1 installs makes an unmarked property-stating annotation a defect *in that file*, so shipping the
rule beside ten annotations that break it reproduces the S8 failure mode — a header the body does
not support.

**Receipts taken this pass, against the working tree rather than against the design's account of
it.** `.inv` is defined at `design/catalog-search.html:51` and `class="inv"` occurs **0** times in
that file, so S9's "already defined… and currently unused, so no stylesheet change is needed" holds.
`<h3 id="schema-registry">` is at line 233, so the placement slot S9 names exists.
`design/architecture.html:245–246` carries the sentence S9 replaces, and its invariant table has
exactly fourteen rows. `migrations/schema.sql:63` is verbatim
`CREATE TABLE dataset_revisions (      -- linear, gap-free, immutable`. The file holds three
`-- trigger` annotations and **zero** `-- index` annotations, which is Drift 11 from the other side.

### Acceptance criteria for the new work, and what they honestly do not cover

Every criterion added this cycle runs without a database and without Docker: four greps on T1.1,
four on T1.5, two on T8.3, four on T10.3, and two on T10.4. They catch the two failure modes that
actually occurred — **an unmarked rule** (Drift 10's bare adjective; Drift 6's unqualified
`CHECK IN (…)`) and **an illegal or stranded marker** — plus, at T10.3, three proven map omissions.

They do **not** catch the third and most valuable one: whether a bare `[db]`'s named object is
actually installed. § "S9 — … ### Currency" says why in as many words — that check needs the DDL
applied, and § "S8 — … ### Explicit contracts" already established this repository has nowhere to
apply it (no `.github/workflows/`, every pre-commit hook database-free, `alembic.ini` hard-coding
one laptop's port). T1.5 states the gap in the task rather than in this section, so an implementer
reading only the task is not misled, and offers the one partial substitute that exists: every object
name a marker carries appears somewhere in `migrations/versions/*.py` — the single `grep` S9 says
would have falsified Drift 6 — which proves the object was written, not that a later revision left
it standing. For the objects `0008` itself creates the deep check *is* discharged, by the contract
suites M3–M9 already run; for the pre-existing objects it is not discharged at all, and no criterion
here pretends otherwise.

### M5 and M6 reconciled against Drift 6 — one disagreement, and it is not a vocabulary

Drift 6 is classed "code has diverged, design wins", which makes M5 and M6 the tasks that turn five
assertions in `design/catalog-search.html` §2 into facts. All five vocabularies were re-read from
the live skeleton — not from the grill's transcription of it — and compared member for member
against the DDL this plan carries:

| Column | §2 | Plan | Verdict |
|---|---|---|---|
| `datasets.lifecycle_state` | 3 members | identical, same order | agrees |
| `dataset_revisions.state` | 5 members | identical, same order | agrees |
| `snapshots.state` | 4 members | identical, same order | agrees |
| `product_versions.status` | 5 members | identical, same order, on `state` | **members agree, column name does not** |
| `jobs.kind` | 7 members | identical, same order | agrees |

**No member anywhere disagrees.** The single disagreement is the column name `status` vs `state`,
and it is settled in opposite directions from the vocabularies, which is the part worth not
collapsing: on the members the design wins and `0008` changes the database; on the name the
migration wins and `design/` changes. Both § "S2 — … ### Target design"'s naming-discrepancy note
and Drift 6's own parenthetical already say so; what was missing is that the §2 correction had no
owner, and § 1 now hands it to the write-back phase by name. M5's header carries the comparison
table, and T5.1 carries the standing instruction that a member which differs is a design change to
report, not a typo to fix.

Two further things the reconciliation surfaced. **Four of M5's eight constraints are not
transcriptions**: §2 leaves `lifecycle_state` bare on `organizations`, `projects` and `products` and
gives `purge_records` no state vocabulary at all, so those four are rules `0008` adds *ahead of* the
authoritative sketch — §2 working as designed, and exactly what S9's `[db 0008]` qualifier is for.
And **M6's `lineage_edges` pair is sourced from §3, not §2**, while §2's skeleton spells the columns
`from_kind` / `to_kind` against `0001`'s `upstream_kind` / `downstream_kind` — the same shape of
divergence as `status`, settled the same way, and already Drift 8's to correct.

### The one plan defect found this cycle, and fixed

**T8.3 told an implementer to replace a line that does not exist.** It read: "its `UNIQUE
(dataset_id, revision_number)` line is replaced by the `one_claim_per_revision_number` partial
index". Drift 9 proves `migrations/schema.sql` never carried that constraint — it is the only unique
constraint in the database the map does not represent — and the `ingest_sessions` block was re-read
to confirm it: `id uuid PRIMARY KEY` through `updated_at`, then one trailing `-- partial unique
index: at most ONE open ingest per dataset (per-dataset lock)` comment, and no total unique key
anywhere in it. T8.3 now **adds two annotations and replaces none**, states the Drift 9 evidence
inline so the correction is not re-reverted, and carries a mechanical acceptance criterion. The
consequence Drift 9 names — that the drop of `ingest_sessions_dataset_id_revision_number_key` is
invisible in the map's diff — is closed by the new `one_claim_per_revision_number` annotation
naming what holds the number instead.

### Where the remaining drift findings were routed

Most of Drifts 7–16 are documentation corrections, and **no implementation task was invented for
any of them.** The split:

| Finding | Routing |
|---|---|
| Drift 6 | M5 and M6 are what make its five assertions true; the §2 `status` → `state` correction goes to the write-back |
| Drift 7 (`layer_repos`), 8 (six wrong column lists), 12 (rejected RBAC example), 15 (stale historical plans), 16 (`science_profiles`) | Write-back phase, enumerated in § 1 |
| Drift 9 (map omits the total unique key) | **Fixed as a plan defect** in T8.3, above |
| Drift 10 (`-- linear, gap-free, immutable`) | **T1.5**, S9's own edit, and closable in no other file |
| Drift 11 (no index in the map) | Partly by T3.5/T4.3/T8.3/T9.4 for the objects `0008` creates; the three still-unrepresented pre-existing indexes go to **T10.3**, with `role_bindings_principal_scope` excluded because T4.1 drops it |
| Drift 13 (map hides the partitioning) | **Already closed by T9.4**, which removes the `-- partitioned by created_at range` comment from a table that is no longer partitioned; noted in T10.3 so it is not redone |
| Drift 14 (`DEFAULT 1` on the counter columns) | **T10.3** |
| Addition to Drift 4 (`docs/` and `schema.sql` disagree) | **Already closed by T1.1**; the grill's own finding is that `docs/` is correct and needs no edit, which the plan already assumed |
| `capabilities.description`, the one omitted column | **T10.3** — recorded under the grill's "Checked, no drift found", where it is easy to miss |
| The thirteen/13/fourteen design-document count | Write-back phase, § 1 |

**Two counts in the grill were re-derived rather than inherited, per the design skill's rule, and
one is wrong.** Drift 14's heading says "five counter columns"; its own body enumerates seven from
`pg_attrdef` (`organizations`, `projects` and `datasets` each contributing `generation` and
`version`, plus `ingest_sessions.etag`). T10.3 states seven, says to re-derive against the file, and
its acceptance criterion counts **occurrences rather than lines**, because the map writes
`generation integer NOT NULL, version integer NOT NULL,` on one line and a line count returns four —
passing on a half-done edit. Drift 11's "six non-constraint indexes" was confirmed: two named in
prose, four absent, one of the four dropped by `0008`, leaving three for T10.3.

### Left unowned, and surfaced rather than absorbed

Two `design/catalog-search.html` §2 content errors are named **only** in
`SCHEMA_DESIGN.md` § "S9 — … ### Explicit contracts", which assigns them to S2 and S5 — neither of
which has a task in this plan that edits `design/`. No drift finding carries either as its own item,
so without an explicit handover both are owned by nobody:

- `product_versions.status` → `state`. Inside Drift 6's finding, but not as a listed correction.
- `product_versions.derivation` → `derivation_record`. Verified this pass: `0001_foundations.py`
  line 291 and `migrations/schema.sql` line 305 both spell it `derivation_record`; §2 writes
  `derivation jsonb NOT NULL`. Carried by no drift finding at all.

Both are now bulleted in § 1's Phase 5 handover. The four S9 obligations that this plan cannot
discharge — the §2 markers, the `enforcement` subsection, the `architecture.html` §5 sentence, and
the `[db 0008]` drop in §2 and the residue table — are in § 7 item 21 as outstanding by design.

### Re-checked, and not stale

- **Nine `DDL` blocks, unchanged.** S9 produces no DDL and touches no migration module. The nine
  `block N of DDL` lines are unique and cover 1–9 with no gap (T3.2=1, T4.1=2, T5.1=3, T6.1=4,
  T7.1=5, T8.1=6, T8.4=7, T9.1=8, T9.2=9); § 3's block list, T10.1's "all nine blocks" and § 7
  item 15 all still say nine.
- **T10.1's probe set is still eight names, unconditional, one per block with block 9 riding on
  block 8's relation.** Nothing this cycle adds a block, and T10.4 creates no object to probe.
- **Both contract suites, the gate, and every DDL acceptance criterion are untouched.** No task's
  files, dependencies or exception classes changed except T8.3's, which gained criteria and lost a
  false instruction.
- **Settled decisions were not reopened.** Gate D1 (option B), the S7a abort/retry semantics and the
  stranded-envelope contract, the `_TRANSITIONS` non-narrowing verdict, the no-GIN decision, the
  one-enum rule, T3.3's duplicate-don't-share decision, T1.4's fixture-only scope, and M9's
  `audit_events_pkey` name assertion are all as cycles 3 and 4 left them.
- **Task and milestone numbering is stable.** M1 gains T1.5, M10 gains T10.4; no existing task was
  renumbered, and § 7's items 1–18 keep their numbers so cycles 3 and 4's citations of "item 15" and
  "item 16's deletion list" still resolve. The new items are 19–21 under a new heading.
- **The risk register stays at five, deliberately.** S9 adds no execution risk to `0008` — no DDL, no
  Python, no migration statement — and its one failure mode, a stranded `[db 0008]`, is a
  documentation defect with a named owner (T10.4) and an explicit warning in § 7 item 20. Promoting
  it to R6 would push the register past the 3–5 the command specifies and would renumber nothing
  usefully; leaving R2–R5 untouched keeps cycles 2–4's inbound citations valid.
- **Cycle 2 and 3 residuals are unchanged and remain non-blocking**: T3.1's verification command is
  a syntax error as printed, § 3's `make lint` description goes stale at T1.3, T2.3's third
  assertion has no designated file, and T1.2 does not declare the seams T1.4 monkeypatches. None
  interacts with S9 or with any drift finding.

### What this cycle did not do

It did not apply `0008`, run either contract suite, run the gate, or start a database — the
environment has no Docker daemon, which the grill records for the same reason. It did not edit
`SCHEMA_DESIGN.md`, `design/`, `docs/`, `migrations/`, or any skill or command file: every fact
above about those files was read from them, and every correction they need is routed to a task or
to the write-back phase rather than made here.
