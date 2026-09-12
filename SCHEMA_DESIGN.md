# Huron PostgreSQL schema — design record

Design target: `migrations/` and the PostgreSQL schema surface it defines, plus the
application code in `src/huron/` that queries it.

Primary design goal: bring the schema into conformance with
`.claude/skills/postgresql-table-design/SKILL.md`, closing the proven integrity gaps and
constraint/index omissions recorded in `schema_audit.md`.

Escalation context: `schema_audit.md` (findings F1–F8). Every finding there was proven on a
live PostgreSQL 16 by catalog query or by a negative write that succeeded. **Those findings
are established. Do not re-derive them and do not re-run the database verification.**

Plan file: `SCHEMA_IMPLEMENTATION_PLAN.md`. (`DESIGN.md` / `AUTH_IMPLEMENTATION_PLAN.md` are
deliberately *not* used here — `AUTH_IMPLEMENTATION_PLAN.md` holds the already-shipped auth plan
and must not be clobbered.)

---

## Constraints that bind every task in this document

1. **The fix migration is `0008`.** The working tree is dirty with a large in-flight change
   set, and both `migrations/versions/0006_role_simplification.py` and
   `migrations/versions/0007_roleless_service_accounts.py` are **untracked** — `0007` is the
   current head. Any migration implementing these findings is therefore
   `migrations/versions/0008_*.py` with `down_revision = "0007_roleless_service_accounts"`.
2. **DDL authoring convention is fixed.** `migrations/_ddl.py` documents why: `migrations/env.py`
   runs over asyncpg, whose extended query protocol refuses a `Parse` containing more than one
   command, so `op.execute(one_big_block)` fails on any multi-statement revision. Every revision
   authors its DDL as one module-level `DDL = r"""…"""` string and calls
   `execute_sql(DDL)`, which splits at top-level `;` boundaries (aware of `--` comments,
   `''`-escaped single-quoted literals, and `$tag$` dollar-quoted bodies). **`0008` must follow
   this exactly** — one `DDL` string, no `op.create_check_constraint`/`op.create_index` calls,
   no second DDL constant.
3. **`migrations/schema.sql` is generated documentation, not executed DDL.** Its header lists
   only `0001`–`0005` and is already stale. Any plan must include regenerating it.
4. **Seed convention.** `roles` / `capabilities` / `role_capabilities` rows mirror
   `src/huron/pkg/rbac/roles.py`, which is the source of truth; `tests/contract/test_rbac_store.py`
   diffs the two against a migrated database. If any finding touches that data, **the Python
   module changes first**, in the same change as the migration (`0002`/`0004`/`0005`/`0006`/`0007`
   all say so in their docstrings).
5. **Clean sweep.** No backwards-compatibility shims, no TODOs, no speculative abstractions, no
   suppressed lints. No comment, docstring, test name, or user-facing string may reference this
   plan, its phases, or checklist mechanics.

---

## Current State

### 1. Migration stack

| Revision | `down_revision` | Tracked | Adds |
|---|---|---|---|
| `0001_foundations` | `None` | yes | Hierarchy, revisions, releases, amendments, ingest, governance, published representations, operational plumbing |
| `0002_rbac` | `0001_foundations` | yes | Principals, service accounts, role catalog, guarded bindings, policies |
| `0003_layer_paths` | `0002_rbac` | yes | `products.dataset_id` + composite FK; bronze/silver must name a dataset |
| `0004_entry_layers` | `0003_layer_paths` | yes | `datasets.entry_layer`; invariant-N CHECKs on `snapshots.provenance`; `ingest_pipeline` role |
| `0005_auth` | `0004_entry_layers` | yes | `local_credentials`, `sessions`, `user.manage` capability |
| `0006_role_simplification` | `0005_auth` | **no** | Deletes `data_steward`; datasets ACTIVE on creation; drops `projects.dataset_creation_mode` |
| `0007_roleless_service_accounts` | `0006_role_simplification` | **no** | Deletes `pipeline`/`ingest_pipeline`; replaces `role_binding_guard()` to refuse `sa:` principals |

31 tables in five entity groups.

### 2. Entity groups

**Catalog hierarchy (0001).** `organizations` → `projects` → `datasets` → `dataset_revisions`,
with `releases` (immutable citation tags on one revision) and `revision_amendments`
(append-only metadata amendments). Slugs are regex-CHECKed; `generation` and `version` are
positive-integer counters (filesystem generation doc counter and optimistic-concurrency ETag).
`dataset_revisions` is linear, gap-free and immutable: `revision_number` 1..999999 unique per
dataset, `manifest_sha256`/`metadata_sha256` regex-CHECKed, `revision_path` globally unique.

**Ingest (0001).** `ingest_sessions` (one row per in-flight raw ingest, state machine
`PREPARING|UPLOADING|VERIFYING|COMMITTING|COMMITTED|ABORTED|FAILED` enforced by CHECK, `etag`
counter, `expires_at` lease) and `ingest_files` (per-file upload plan; `action` CHECKed to
`upload|hardlink`, `completed_parts jsonb`). A partial unique index
`one_open_ingest_per_dataset` is the per-dataset ingest lock.

**RBAC / auth (0001, 0002, 0005, 0006, 0007).** `principals` → `service_accounts`,
`local_credentials`, and the role catalog `roles` → `role_capabilities` → `capabilities`, with
`role_bindings` as the grant. `api_keys` and `sessions` are the two credential surfaces.
Post-`0007` the vocabulary is five roles (`reader`, `developer`, `project_admin`,
`organization_admin`, `platform_owner`), all user-only; a service account's authority is
intrinsic to its `service_accounts` row and synthesized at decision time by
`huron.pkg.rbac.roles.service_account_bindings`, never stored as a binding.

**Governance and published representations (0001, 0003, 0004).** `policies` /
`policy_attachments`, `purge_records` (two-person: `approved_by <> requested_by` by CHECK),
`retention_holds`, `science_profiles`; then `snapshots` (one row per published Icechunk
snapshot, `layer` CHECKed to `bronze|silver|gold`, `provenance jsonb` carrying invariant N),
`products` / `product_versions`, and `lineage_edges`.

**Operational (0001).** `audit_events` (declared `PARTITION BY RANGE (created_at)`),
`outbox_events`, `idempotency_records`, `jobs`, `reconciliation_findings`.

### 3. Table relationships

```mermaid
erDiagram
    organizations   ||--o{ projects           : "organization_id"
    organizations   ||--o{ service_accounts   : "organization_id"
    projects        ||--o{ datasets           : "project_id"
    projects        ||--o{ products           : "project_id"
    projects        ||--o{ api_keys           : "project_id (nullable)"
    datasets        ||--o{ dataset_revisions  : "dataset_id"
    datasets        ||--o{ releases           : "dataset_id"
    datasets        ||--o{ ingest_sessions    : "dataset_id"
    datasets        ||--o{ snapshots          : "dataset_id (NULL only for gold)"
    datasets        ||--o{ products           : "dataset_id (NULL = fused)"
    dataset_revisions ||--o{ releases         : "revision_id (F1: not tied to dataset_id)"
    dataset_revisions ||--o{ revision_amendments : "revision_id"
    dataset_revisions ||--o{ purge_records    : "revision_id"
    ingest_sessions ||--o{ ingest_files       : "ingest_id ON DELETE CASCADE"
    ingest_sessions }o..o| dataset_revisions  : "revision_id — NO FK (F8)"
    products        ||--o{ product_versions   : "product_id"
    snapshots       ||--o{ product_versions   : "snapshot_id (nullable)"
    policies        ||--o{ policy_attachments : "policy_id"
```

```mermaid
erDiagram
    principals      ||--o| service_accounts   : "principal_id (PK/FK)"
    principals      ||--o| local_credentials  : "principal_id (PK/FK)"
    roles           ||--o{ role_capabilities  : "role_code ON DELETE CASCADE"
    capabilities    ||--o{ role_capabilities  : "capability_code"
    roles           ||--o{ role_bindings      : "role_code"
    principals      }o..o{ role_bindings      : "principal text, no FK by design"
    principals      }o..o{ sessions           : "subject text, no FK by design"
    principals      }o..o{ api_keys           : "owner_subject text, no FK by design"
```

`role_bindings.principal`, `sessions.subject` and `api_keys.owner_subject` are prefixed text
subjects (`user:` / `group:` / `sa:`), not FKs — groups have no `principals` row at all, so a
FK is not representable. `role_bindings_principal_format` CHECKs the prefix instead.

### 4. Constraint and trigger mechanisms already in use

The schema is not constraint-poor; it is *unevenly* constrained. The mechanisms available and
already idiomatic here:

- **Regex CHECKs on identifiers and digests** — slugs (`^[a-z0-9][a-z0-9-]{1,61}$` plus a
  `!~ '--'` clause), release tags, role/capability codes, all `*_sha256` columns
  (`^[0-9a-f]{64}$`), `password_hash LIKE '$argon2id$%'`.
- **`IN (...)` CHECKs on closed vocabularies** — `ingest_sessions.state`, `ingest_files.action`,
  `snapshots.layer`, `retention_holds.scope_kind`, `retention_holds.kind`,
  `role_bindings.effect`, `role_bindings.scope_type`, `policy_attachments.scope_type`,
  `sessions.authentication_method`, `principals.kind`, `api_keys.owner_kind`,
  `products.shape`, `datasets.entry_layer`.
- **Range CHECKs** — `revision_number BETWEEN 1 AND 999999`, `generation > 0`, `version > 0`,
  `file_count > 0`, `total_bytes >= 0`, `quota_bytes IS NULL OR quota_bytes >= 0`.
- **Cross-column CHECKs** — `(withdrawn_at IS NULL) = (withdrawn_reason IS NULL)`,
  `approved_by IS NULL OR approved_by <> requested_by`,
  `idle_expires_at <= absolute_expires_at`, `kind = 'user' OR idp_subject IS NULL`,
  `layer = 'gold' OR dataset_id IS NOT NULL`.
- **jsonb-path CHECKs, written NULL-safe on purpose** — the two `snapshots.provenance`
  constraints from `0004`, whose docstring records that the naive spelling silently accepted
  `'{}'`. These are the only shape constraints on any jsonb column.
- **Array containment CHECKs** — `role_capabilities.layers <@ ARRAY['raw','bronze','silver','gold']`,
  and the `allowed_principal_kinds` / `bindable_scopes` guards on `roles`.
- **Composite FK against a redundant unique key** — `0003`'s
  `datasets_id_project_id_unique` + `products (dataset_id, project_id) REFERENCES datasets (id, project_id)`.
  This is the house pattern for "the child's grandparent must match the parent's grandparent".
- **`UNIQUE NULLS NOT DISTINCT`** — `role_bindings_no_duplicates`.
- **Partial indexes** — `one_open_ingest_per_dataset`, `jobs_claim`, `outbox_unprocessed`,
  `sessions_subject_active`.
- **`plpgsql BEFORE INSERT OR UPDATE` trigger guards** — `releases_immutable()`,
  `service_account_kind_guard()`, `local_credentials_kind_guard()`, `role_binding_guard()`
  (replaced in `0007`). These carry rules a CHECK cannot express because they read another table.

### 5. Application code that touches the schema

This is the single most important structural fact for scoping, and it is not in the audit.

**Only two modules issue SQL at all:**

| Module | Lines | Tables written / read |
|---|---|---|
| `src/huron/service/api/postgres_rbac.py` | 433 | `role_bindings`, `roles`(via `role_capabilities` join), `principals`, `service_accounts`, `policies`, `policy_attachments`, `api_keys` |
| `src/huron/service/api/postgres_auth.py` | 256 | `principals`, `local_credentials`, `sessions` |

`src/huron/service/api/repository.py` (`HierarchyRepository`) is **in-memory and synchronous** —
it holds the hierarchy in dicts and writes generation documents to a path tree. There is no
PostgreSQL implementation of the catalog hierarchy.

**Consequently, 20 of the 31 tables have zero references anywhere in `src/huron/`:**
`dataset_revisions`, `revision_amendments`, `ingest_sessions`, `ingest_files`, `snapshots`,
`product_versions`, `lineage_edges`, `purge_records`, `retention_holds`, `science_profiles`,
`audit_events`, `outbox_events`, `idempotency_records`, `jobs`, `reconciliation_findings`
(plus `organizations`/`projects`/`datasets`/`releases`/`products`, which appear only as
in-memory dataclasses in `repository.py`).

The schema is **ahead of the application**, deliberately: `0001` is titled "P1 foundations plus
registries required by later phases". Design work on those tables must take its vocabulary from
the `design/*.html` record and from the pure-domain enums in `src/huron/pkg/`, not from SQL that
does not exist yet.

**The pure-domain enums that do exist** (`src/huron/pkg/`, no database dependency):
`catalog.ingest.IngestState` (7 members, with an explicit `_TRANSITIONS` map and
`TERMINAL_STATES`), `catalog.ingest.UploadAction` (`upload|hardlink`),
`catalog.layers.Layer`, `catalog.layers.LayerAction`, `rbac.Decision`, `rbac.Effect`,
`rbac.ScopeType`. `IngestState` and `UploadAction` are already mirrored exactly by the
`ingest_sessions.state` and `ingest_files.action` CHECKs — that is the house pattern for a
state vocabulary: **a `StrEnum` in `pkg/`, mirrored by an `IN (...)` CHECK in the migration.**

**The ingest/commit flow, for F8.** `src/huron/pkg/catalog/ingest.py` (114 lines) is a pure
state machine and upload planner — no I/O. `src/huron/pkg/rawstore/commit.py` (71 lines) is
pure POSIX (`fsync_tree`, atomic `rename`). The database half is declared only as a
`typing.Protocol` in `src/huron/pkg/catalog/ports.py`:

```
class Metastore(Protocol):
    async def begin_ingest(self, dataset_id: UUID, manifest_sha256: str) -> IngestLease: ...
    async def record_revision(...) -> ...: ...
    async def resolve_tag(self, dataset_id: UUID, tag: str) -> RevisionRef: ...
```

`IngestLease` already carries `revision_id` — it is minted at `begin_ingest`, in `PREPARING`,
which is precisely why `ingest_sessions.revision_id` cannot carry a plain FK. **No
implementation of this Protocol exists.** `design/layer-raw.html` is the authority on the
commit sequence and states it explicitly: step 7 is "ONE short PG transaction: revision row,
session → COMMITTED", and "no database transaction is ever held across file I/O", under
invariant G ("storage leads; the catalog follows").

### 6. Test and verification surface

`tests/contract/test_rbac_store.py` applies the migrations to a live database and asserts the
`roles`/`capabilities`/`role_capabilities` seed matches `huron.pkg.rbac.roles.ROLES`, then
exercises the trigger guards with negative writes (`_assert_trigger_rejects_*`). It is the
existing, working template for "prove a database rule with a write that must fail" and is where
new constraint tests belong. `tests/contract/test_auth_store.py` does the same for the auth
tables. There is no contract test for the catalog hierarchy, because there is no PostgreSQL
implementation of it.

---

## Roadmap Drift

Concrete mismatches between `design/roadmap.html` (plus `design/rbac.html`,
`design/architecture.html`) and what the schema and code actually do.

1. **`audit_events` partitions — roadmap claims what the DDL does not do.** `design/roadmap.html`
   §2, phase **P1 — Foundations**, tagged `done`, lists deliverables including
   "migrations (hierarchy, role_bindings, api_keys, **audit with pre-created partitions**,
   outbox)". `0001` creates `audit_events` `PARTITION BY RANGE (created_at)` and then exactly
   one child, `audit_events_default PARTITION OF audit_events DEFAULT`. There are no pre-created
   bounded partitions and nothing that creates them. This is the roadmap-facing half of **F6**,
   and it means F6 is not merely a performance observation — it is a `done` phase whose stated
   deliverable was not delivered.

2. **`pkg/metastore/` does not exist.** `design/roadmap.html` §1 lays out the package inventory
   and lists `metastore/ — PostgreSQL structural state and the outbox` as one of the eleven
   independent `pkg/` packages, with the one-way rule `service → pkg → schema`. There is no
   `src/huron/pkg/metastore/`. All SQL lives in `src/huron/service/api/postgres_rbac.py` and
   `postgres_auth.py` — that is, in the service tier, not in a package. The `Metastore` Protocol
   in `pkg/catalog/ports.py` has no implementation anywhere. This is not something migration
   `0008` fixes, but it determines where any new schema-touching code would go, and any task
   proposing application code must say which surface it lands on.

3. **Role count.** `design/roadmap.html` §3, milestone 3 ("Authorization & discoverability")
   says under *Built*: "the `pkg/rbac` engine (**8 roles**, deny-overrides, scope walk, layer
   restrictions), request-cached `check()`, **DB-trigger-enforced service-account-only
   silver/gold writes**". After `0006` (removes `data_steward`) and `0007` (removes `pipeline`
   and `ingest_pipeline`), `src/huron/pkg/rbac/roles.py` defines **five** roles, and
   `design/rbac.html` correctly says "Every picker lists exactly the five roles". Both halves of
   the roadmap sentence are stale: the trigger no longer enforces "service-account-only
   silver/gold writes" — `0007`'s `role_binding_guard()` refuses **any** `sa:` principal
   outright, and no role in the vocabulary carries silver/gold `data.write` at all, so the
   invariant now holds by construction rather than by trigger. `design/rbac.html` is current
   here; `design/roadmap.html` is not.

4. **`migrations/schema.sql` header.** The file's own header declares it "GENERATED
   DOCUMENTATION, NOT EXECUTED" and names the authoritative migrations as
   "(0001_foundations, 0002_rbac, 0003_layer_paths, 0004_entry_layers, **0005_auth**)". `0006`
   and `0007` have landed since; the body reflects some of their effects (it describes roles as
   post-`0007` roleless-service-account) but the header list was never updated. The header also
   instructs regeneration via `pg_dump --schema-only --no-owner huron`, which cannot be the
   actual provenance — the file is a hand-condensed map with explanatory comments and
   `-- trigger …` annotations that `pg_dump` never emits. **The stated regeneration procedure
   does not produce the file it describes.** Any plan landing `0008` must regenerate this file
   and settle what "regenerate" means.

5. **Where there is no drift.** `design/rbac.html` matches `0006`/`0007` (five roles, roleless
   service accounts, the removed steward gate). `design/layer-raw.html`'s commit protocol
   matches `pkg/catalog/ingest.py`'s state machine exactly (same seven states, same terminal
   set). `design/layer-gold.html`'s single-source/fused product split matches `0003`'s
   `products.dataset_id` nullable-attachment pattern. `design/architecture.html` makes no
   schema-level claims that the DDL contradicts. And the in-memory `HierarchyRepository` is
   **not** drift: roadmap milestone 4 ("Every field the catalog pages render is served from
   PostgreSQL") is tagged `todo`, so the roadmap correctly reports that this is not built.

---

## Design Tasks

Eight tasks. Each is sized for one design subagent within 30k–50k tokens. The **Kind** column
says whether the task is settled from DDL alone or requires reading application code and the
design record.

| # | Task | Findings | Kind |
|---|---|---|---|
| S1 | Cross-parent referential integrity | F1 (+ the `product_versions.snapshot_id` sibling) | Pure DDL |
| S2 | Closed state and lifecycle vocabularies | F2 (`lifecycle_state`, `state`, `severity`) | **Needs app code + design docs** |
| S3 | Event `kind` vocabularies — open or closed | F2 (`kind`, `upstream_kind`, `downstream_kind`) | **Needs design docs** |
| S4 | Foreign-key access paths and referential actions | F3, F4, F7 | Pure DDL (one query to read) |
| S5 | jsonb object-shape constraints | F5 | Pure DDL |
| S6 | `audit_events` partitioning: commit or drop | F6 | **Needs a human decision** |
| S7 | Ingest-session ↔ revision correspondence | F8 | **Needs the ingest/commit flow** |
| S8 | `migrations/schema.sql` as a generated artifact | (F-adjacent; roadmap drift 4) | Convention |

---

### S1 — Cross-parent referential integrity

**Findings:** F1. Also decide the explicitly lower-priority sibling the audit names:
`product_versions.snapshot_id` can reference a snapshot belonging to an unrelated dataset.

**Scope.** `releases.dataset_id` and `releases.revision_id` are independent FKs, so a release
can cite a revision belonging to a different dataset — proven by a successful INSERT, and
permanent, because releases are immutable citation anchors (invariant M) and are withdrawn
rather than repointed. `0003` already established the house fix for this exact bug class on
`products`, and its docstring states the rationale. The audit's indicated shape is
`UNIQUE (id, dataset_id)` on `dataset_revisions` plus a composite FK on `releases`.

Confirm the audit's scoping that `revision_amendments` and `purge_records` are unaffected
(they carry only `revision_id`, so no inconsistent pair is representable), and decide whether
`product_versions.snapshot_id` gets the same treatment now or is explicitly left — with the
reason recorded either way, not silently dropped.

**Acceptance criteria.**
- The target DDL for the `releases` fix is written out, including the redundant unique key it
  requires on `dataset_revisions` and what that adds to the existing index set.
- A decision on `product_versions.snapshot_id`, with a stated reason. If it is fixed, the chain
  it needs (`snapshots` has a nullable `dataset_id`, and `product_versions` has no `dataset_id`
  at all) is worked through, not assumed.
- The interaction with the `releases_immutable()` trigger is stated: the trigger freezes every
  column except withdrawal, so a composite FK on an immutable row can never be violated by a
  later UPDATE — say whether that makes the constraint cheap or redundant.
- Rejected alternatives (at most 2–3, one line each) — e.g. a trigger instead of a composite FK.

**Files to inspect.** `migrations/versions/0001_foundations.py` (releases, dataset_revisions),
`migrations/versions/0003_layer_paths.py` (the house pattern and its docstring),
`migrations/versions/0004_entry_layers.py` (snapshots), `migrations/schema.sql` §1 and §5.

---

### S2 — Closed state and lifecycle vocabularies

**Findings:** F2, for the columns whose vocabulary is clearly closed:
`organizations|projects|datasets|products.lifecycle_state` (4),
`dataset_revisions|ingest_files|jobs|purge_records|snapshots|product_versions.state` (6),
`reconciliation_findings.severity` (1).

**This is real investigation, not a rote CHECK-adding exercise.** The permitted vocabulary must
be *decided per column* from how the value is actually produced and consumed. Two facts make
that harder than it looks, and the task must confront both:

- **Most of these columns have no writer.** Per Current State §5, only `products` and the three
  hierarchy tables appear in application code at all, and there only as in-memory dataclasses
  (`repository.py:97` is the sole `lifecycle_state` reference in `src/huron/`).
  `dataset_revisions`, `ingest_files`, `jobs`, `purge_records`, `snapshots`,
  `product_versions` and `reconciliation_findings` have **zero** references in `src/huron/`.
  The vocabulary for those must come from `design/*.html` and from the `pkg/` enums, and the
  task must say for each column which source it took the vocabulary from.
- **The audit's count and the column list do not obviously agree.** F2's prose says "twelve
  enum-like text columns"; its table's four rows span 14 tables and 16 (table, column) pairs
  once the `kind` row (S3's scope) is included. Enumerate the columns explicitly rather than
  inheriting a count, and note the discrepancy if it survives enumeration.

The house pattern to follow, where a writer will exist: a `StrEnum` in `pkg/` mirrored by an
`IN (...)` CHECK — exactly as `catalog.ingest.IngestState` is mirrored by the
`ingest_sessions.state` CHECK. Say for each column whether it should acquire such an enum now
or whether the CHECK stands alone until the writer is built.

`lifecycle_state` is the clearest case that an open vocabulary is *not* intentional: the four
tables share a `DEFAULT 'ACTIVE'`, `0006` lifted every `DRAFT` row to `ACTIVE` and dropped the
approval switch, and roadmap milestone 4 names `retire`/`archive` and "project archive and
delete-when-empty" as the transitions to come. Whether a CHECK should be written against a
vocabulary whose transitions are not yet built is a judgment this task must make and defend.

**Acceptance criteria.**
- Every column enumerated with its decided permitted set and the evidence for it (file and
  symbol, or design document and section).
- For each, an explicit statement of whether it needs a `pkg/` `StrEnum` companion, and where.
- Any column where the vocabulary genuinely cannot be settled today is named, with what would
  settle it — not silently given a permissive CHECK.
- Rejected alternatives (lookup tables vs. `TEXT` + CHECK vs. a native `enum` type), one line
  each. Note that the skill and the whole existing schema use `TEXT` + CHECK; a departure needs
  a strong reason.

**Files to inspect.** `src/huron/pkg/catalog/ingest.py`, `src/huron/pkg/catalog/layers.py`,
`src/huron/service/api/repository.py`, `src/huron/service/api/routes/v1/schema/`,
`migrations/versions/0001_foundations.py`, `migrations/versions/0006_role_simplification.py`,
`design/roadmap.html` (§3 milestone 4), `design/layer-raw.html`, `design/layer-bronze.html`,
`design/layer-gold.html`, `design/workflows.html`, `web/src/lib/api/types.ts`.

---

### S3 — Event `kind` vocabularies: open or closed

**Findings:** F2, for the columns the audit itself flags as possibly-intentionally open:
`jobs.kind`, `audit_events.kind`, `outbox_events.kind`,
`lineage_edges.upstream_kind` and `lineage_edges.downstream_kind`.

**Scope.** Separated from S2 because it is a different decision, not a different set of columns.
S2 asks "what are the legal values"; S3 asks "**is a fixed value set the right model here at
all**". The audit is explicit: "an event `kind` may legitimately be open-ended where a
`lifecycle_state` is not." An audit log that refuses to record an event kind nobody thought of
is worse than one that records it — but `lineage_edges.upstream_kind`/`downstream_kind` name
entity types (revision, snapshot, product version), which is a closed set the schema already
knows, and a typo there silently orphans a lineage edge.

Also settle the format question: if a vocabulary stays open, does it still get a *format*
constraint (the schema already does this — `policies.policy_type` carries
`~ '^[a-z][a-z0-9_]{1,62}$'` with no `IN` list, and `capabilities.code` carries a dotted-name
regex). "Open" and "unconstrained" are not the same thing, and `policies.policy_type` is the
existing proof.

**Acceptance criteria.**
- A per-column verdict: closed `IN (...)`, open-with-format-regex, or genuinely unconstrained,
  each with a one-line reason.
- If any column stays unconstrained, say what would make it constrainable later and why now is
  not that time.
- The `lineage_edges` pair is decided together with the entity-kind vocabulary it draws on.
- Rejected alternatives, one line each.

**Files to inspect.** `migrations/versions/0001_foundations.py` (`jobs`, `audit_events`,
`outbox_events`, `lineage_edges`, and `policies.policy_type` as the precedent),
`design/architecture.html` (the lineage model), `design/layer-gold.html` (lineage edges and
derivation records), `design/workflows.html`, `design/roadmap.html` §2 P4/P6/P9.

---

### S4 — Foreign-key access paths and referential actions

**Findings:** F3 (nine unindexed FK columns), F4 (the RBAC scope-listing query has no usable
index), F7 (21 of 23 FKs leave `ON DELETE` implicit).

**Scope.** Grouped because they are one pass over the same object: every foreign key in the
schema, asked two questions — does the referencing side have a supporting index, and is its
referential action stated. F4 is the one access-path finding that is not about a FK, but it
lands on `role_bindings`, is fixed by the same kind of index, and the sibling table already
shows the answer (`policy_attachments_scope (scope_type, scope_id)` applies exactly the right
pattern for the identical access path).

F3's unindexed columns, from the audit: `api_keys.project_id`, `product_versions.snapshot_id`,
`products.dataset_id` and the composite `products (dataset_id, project_id)`,
`purge_records.revision_id`, `releases.revision_id`, `role_bindings.role_code`,
`role_capabilities.capability_code`, `snapshots.dataset_id`.

F7's judgment is largely pre-made by the audit — `NO ACTION` "is very likely what is wanted for
a catalog whose rows are withdrawn rather than deleted"; the skill asks for the choice to be
**explicit rather than inherited**. The design work is confirming that per FK and naming the
exceptions. `ingest_files.ingest_id` and `role_capabilities.role_code` already state `CASCADE`;
`role_capabilities.capability_code` conspicuously does not, and that asymmetry needs a verdict.
Also consider whether any FK wants `ON UPDATE` stated — `roles.code` and `capabilities.code`
are natural text keys, unlike every other parent key in the schema.

Note the interaction with S1: if S1 adds a composite FK on `releases`, that FK needs its own
supporting index, and it may subsume the `releases.revision_id` index F3 asks for. Whichever
task is designed second must reconcile, not duplicate.

**Acceptance criteria.**
- A single table of all 23 FKs (24+ if S1 lands one) with, per row: referencing column(s),
  supporting index (existing, to-add, or subsumed by an existing leading-column match), and the
  decided `ON DELETE` / `ON UPDATE` action with a one-line reason.
- Where an existing index already covers a FK by leading-column prefix, say so and add nothing —
  the goal is a correct index set, not nine new indexes.
- The `role_bindings` scope index is specified and its relationship to the existing
  `role_bindings_principal_scope` and `role_bindings_no_duplicates` is stated: which queries
  each serves, and whether any becomes redundant.
- Rejected alternatives, one line each.

**Files to inspect.** `migrations/versions/0001_foundations.py`,
`migrations/versions/0002_rbac.py`, `migrations/versions/0003_layer_paths.py`,
`src/huron/service/api/postgres_rbac.py` (`bindings_at` at ~line 220, `bindings_for`, the
`role_capabilities` join), `src/huron/service/api/postgres_auth.py`, `migrations/schema.sql`.

---

### S5 — jsonb object-shape constraints

**Findings:** F5.

**Scope.** All fifteen `jsonb` columns lack the `CHECK (jsonb_typeof(col) = 'object')` guard,
including the four whose `'{}'::jsonb` default plainly intends an object. Proven:
`UPDATE projects SET raw_retention_policy = '"just a string"'::jsonb` succeeded.
`snapshots.provenance` is the exception that shows the intent — `0004` added two NULL-safe
CHECKs on its `kind` key and recorded in its docstring that the naive spelling silently
accepted `'{}'`.

Not every jsonb column is an object: `ingest_files.completed_parts` defaults to `'[]'` and is
plainly an array. Enumerate all fifteen and decide the expected top-level type per column, not
one blanket rule. Two columns need thought beyond the type: `policies.spec` ("shape varies by
policy_type") and `revision_amendments.document`, whose real shape is validated in Python
against `src/huron/schema/documents/`. State the division of labor the schema already uses —
`0004`'s docstring puts it exactly: "the full shape is validated in Python against
`huron.schema`; the database keeps the part that a bad writer must not be able to bypass."

The audit's **GIN-index decision is settled and must be carried forward, not revisited**: the
application issues no jsonb containment, key-existence or path queries (`@>`, `?`, `->>` do not
appear in `src/huron`), so a GIN index would cost write throughput for queries that do not
exist. Restate it as a design decision with its trigger condition ("add one when a query needs
it"), so it does not get re-litigated.

**Acceptance criteria.**
- All fifteen jsonb columns enumerated with their expected top-level type and the constraint
  text, written NULL-safe where the column is nullable (`0004`'s docstring explains why this is
  not optional).
- The Python-validation vs. database-constraint boundary stated as a rule, not per-column
  improvisation.
- The no-GIN decision restated with its reversal condition.
- Rejected alternatives, one line each.

**Files to inspect.** `migrations/versions/0001_foundations.py`,
`migrations/versions/0004_entry_layers.py` (the NULL-safe CHECK precedent and its docstring),
`src/huron/schema/documents/`, `src/huron/schema/__init__.py`,
`tests/unit/test_schema_snapshot_provenance.py`.

---

### S6 — `audit_events` partitioning: commit or drop

**Findings:** F6. Also closes roadmap drift item 1.

**Scope.** `audit_events` declares `PARTITION BY RANGE (created_at)` and creates exactly one
child, `audit_events_default PARTITION OF audit_events DEFAULT`. Every row lands in the default
child; there is nothing for the planner to prune; the partitioning is structure without benefit.
There is also no index on `created_at` — the PK is `(id, created_at)` whose leading column is a
random UUID, so it cannot serve a time-range scan.

The audit frames the choice as binary: **commit to the partitioning** (bounded RANGE partitions,
whatever creates them ahead of time, and a retention story) **or drop it** until volume justifies
it. The skill's threshold is >100M rows, and it suggests BRIN for a naturally-ordered
append-only time series like an audit log.

Weigh honestly: nothing writes `audit_events` today (zero references in `src/huron/`), and the
roadmap makes audit-row-per-mutation a `todo` gate in milestone 3. So there is no production
data to migrate and no measured volume to extrapolate from. Note also that dropping the
partitioning is the more literal reading of the clean-sweep rule ("prefer deletion over
accommodation"; a DEFAULT-only partitioned table is a speculative abstraction), while committing
to it is what the `done` P1 roadmap row already promised.

**This task must flag an open question for a human**, per the design-plan contract. Recommend
one option with its reasoning; do not silently pick.

**Settled.** Karl chose to drop the partitioning on 2026-08-31; `## S6 — \`audit_events\`
partitioning (design)` records the decision, the accepted DDL and the proof.

**Acceptance criteria.**
- Both options written out concretely enough to implement: for "commit", the partition bounds,
  what creates them ahead of time and where that lives, the retention/detach story, and the
  index (BRIN on `created_at` vs. btree); for "drop", the DDL that de-partitions and what
  index replaces the pruning.
- A recommendation with reasoning, and the reversal cost of each direction stated.
- The open question explicitly flagged for a human decision.
- A note that `design/roadmap.html`'s P1 row must be corrected either way (Phase 4 of
  `/design-plan` owns that edit; this task only records it).
- Rejected alternatives, one line each.

**Files to inspect.** `migrations/versions/0001_foundations.py` (the `audit_events` block),
`migrations/schema.sql` §6, `design/roadmap.html` §2 P1 and §3 milestone 3,
`design/architecture.html`, `.claude/skills/postgresql-table-design/SKILL.md` (partitioning
and BRIN guidance).

---

### S7 — Ingest-session ↔ revision correspondence

**Findings:** F8.

**Scope.** `ingest_sessions.revision_id` is `uuid NOT NULL UNIQUE` with no `REFERENCES`;
inserting a session whose `revision_id` is an arbitrary UUID succeeds, leaving a row that joins
to no revision. The audit records that this is very likely deliberate — the `dataset_revisions`
row is created at commit time, so a plain FK would make `PREPARING` unrepresentable — **and
that Karl has confirmed (2026-08-31) the gap should nonetheless be closed.** The invariant that
goes unenforced is: *at commit, `ingest_sessions.revision_id` equals the revision actually
created.* Candidate mechanisms named by the audit: a `DEFERRABLE INITIALLY DEFERRED` FK, or a
commit-time trigger asserting the correspondence.

**Understand the flow before choosing the mechanism.** The flow is documented but only
partly built, and the design subagent must not assume otherwise:

- `src/huron/pkg/catalog/ingest.py` is a **pure** state machine — `IngestSession.transition()`,
  `TERMINAL_STATES`, the `_TRANSITIONS` map, an `etag` counter — with no database access.
  `IngestLease` carries `revision_id` alongside `revision_number`, minted at `begin_ingest`
  while the session is `PREPARING`. That is the fact that rules out a plain FK.
- `src/huron/pkg/rawstore/commit.py` is **pure POSIX** — `fsync_tree`, a single atomic
  `rename`, `commit_envelope` refusing an envelope without `COMMITTED`. No database access.
- The database half exists only as the `Metastore` Protocol in
  `src/huron/pkg/catalog/ports.py` (`begin_ingest`, `record_revision`, `resolve_tag`).
  **There is no implementation.** So the mechanism is being designed for a writer that does not
  exist yet, and the design must say what contract that future writer must honor.
- `design/layer-raw.html` is the authority on the sequence: the filesystem rename is the
  durability point, then step 7 is "ONE short PG transaction: revision row, session →
  COMMITTED"; "no database transaction is ever held across file I/O"; invariant G, "storage
  leads; the catalog follows — a revision row is never [written before the storage is durable]".
  A single transaction that inserts the revision and flips the session is exactly the shape in
  which a `DEFERRABLE INITIALLY DEFERRED` FK checks cleanly at COMMIT.

Weigh the two mechanisms against that: a deferrable FK is declarative and needs no plpgsql, but
`NOT NULL` + deferred means every non-committed session must still satisfy it at transaction
end, so it likely also forces `revision_id` to become nullable-until-commit — which changes
`IngestLease`. A trigger keyed on the transition to `COMMITTED` matches the existing house style
(`releases_immutable()`, `role_binding_guard()`) and leaves the column shape alone, but is
imperative and only fires on the state flip. Decide, and say what it costs in each direction.

Note also that `one_open_ingest_per_dataset` (the per-dataset ingest lock) and the
`ingest_sessions.state` CHECK are the neighboring constraints; whatever is chosen must not
conflict with either, and must survive the ABORTED/FAILED terminal states where no revision is
ever created.

**Acceptance criteria.**
- The chosen mechanism, written as concrete DDL, with the ABORTED/FAILED paths shown to be
  satisfiable.
- The contract the future `Metastore` implementation must honor, stated as invariants on the
  commit transaction — including whether `IngestLease.revision_id` or the column's `NOT NULL`
  has to change, and where that change lands.
- A Mermaid diagram of the commit sequence showing where the constraint is checked relative to
  the filesystem rename.
- Rejected alternatives (at most 2–3), one line each — including the one not chosen.
- Any residual gap the mechanism does not close, flagged.

**Spun out.** The abort/retry question this task uncovered — an `ABORTED`/`FAILED` session holding
its reserved revision number against a `max(committed) + 1` allocator — was settled by Karl on
2026-08-31 and is designed in `## S7a — Abort and retry semantics (design)`.

**Files to inspect.** `src/huron/pkg/catalog/ingest.py`, `src/huron/pkg/rawstore/commit.py`,
`src/huron/pkg/catalog/ports.py`, `src/huron/pkg/catalog/errors.py`,
`migrations/versions/0001_foundations.py` (`ingest_sessions`, `ingest_files`,
`one_open_ingest_per_dataset`, `releases_immutable()` as the trigger precedent),
`design/layer-raw.html` (the commit protocol and invariant G), `design/workflows.html`,
`design/roadmap.html` §2 P2.

---

### S8 — `migrations/schema.sql` as a generated artifact

**Findings:** none directly; closes roadmap drift item 4, and every other task depends on it.

**Scope.** Small but real, and it must be settled before the plan is written, because every
other task changes this file. `migrations/schema.sql` calls itself generated documentation and
tells the reader to regenerate with `pg_dump --schema-only --no-owner huron`, but its contents
are a hand-condensed map with prose comments (`-- trigger releases_immutable: every column
except withdrawal is frozen`) that `pg_dump` cannot emit. The header's authoritative-migration
list stops at `0005` while `0006` and `0007` have landed. So the file is neither generated nor
reliably maintained, and the instruction printed at its top does not produce it.

Decide what it is: a hand-maintained condensed architecture map (in which case the `pg_dump`
line is wrong and should go, and updating it becomes an explicit task in every schema change),
or genuine `pg_dump` output (in which case the commentary is lost and a script under
`scripts/` should own it). Do not propose both.

**Acceptance criteria.**
- One decision, stated, with what changes in the file's header to match it.
- If it stays hand-maintained: the rule that says when it must be updated, and how a reviewer
  can tell that it was not.
- If it becomes generated: where the generation script lives and what invokes it.
- Rejected alternative (the option not chosen), one line.

**Files to inspect.** `migrations/schema.sql` (header and structure), `scripts/`, `Makefile`,
`.pre-commit-config.yaml`, `migrations/env.py`, `migrations/_ddl.py`, `alembic.ini`.

---

## Notes carried forward for the planning phase

- **Lower-priority items the audit deliberately did not push**, so no task above owns them.
  If the planning phase wants them, they need a design task first: `created_at`/`updated_at`
  carry no `DEFAULT now()` on 25 columns (the application supplies them — that is a house
  convention, not an oversight); free-text `title`/`description` columns have no
  `CHECK (length(...) <= n)`.
- **Do not re-flag what the audit cleared**: `timestamptz` and `text` throughout, `snake_case`
  identifiers, the 3NF role catalog, the four partial indexes (`jobs_claim`,
  `one_open_ingest_per_dataset`, `outbox_unprocessed`, `sessions_subject_active` — enumerated and
  confirmed; S7a adds a fifth, `one_claim_per_revision_number`),
  `role_bindings_no_duplicates`'s `UNIQUE NULLS NOT DISTINCT`, `principals.idp_subject`
  permitting multiple NULLs (service accounts have no IdP subject — that is the point), and
  UUID primary keys without a database-side `DEFAULT gen_random_uuid()` (ids are
  client-generated and baked into storage paths).
- **Every task's DDL lands in one migration, `0008`.** The design tasks are separated for
  thinking; they are not separate revisions. Whether the plan splits them into more than one
  revision is a planning decision, but the `down_revision` chain starts at
  `0007_roleless_service_accounts` either way.
- **New constraints need negative-write tests.** `tests/contract/test_rbac_store.py`'s
  `_assert_trigger_rejects_*` helpers are the working template, and the audit proved every
  finding the same way. A constraint added without a test that proves the bad write now fails
  has not been verified.

---

## S1 — Cross-parent referential integrity (design)

### Target design

Two objects for `releases`, plus the supporting index the new FK needs. All of it lands in the
single `DDL` string of `0008`, in this order (the unique key must exist before the FK that
targets it).

```sql
-- A release cites a revision of the dataset it belongs to. `releases.dataset_id` and
-- `releases.revision_id` were independent references, so a release could anchor a citation
-- to a revision of an unrelated dataset - and releases are immutable, so the mis-citation
-- would be permanent. The redundant unique key exists only to be a legal composite FK
-- target; `dataset_revisions.id` is already unique on its own.
ALTER TABLE dataset_revisions
    ADD CONSTRAINT dataset_revisions_id_dataset_id_unique UNIQUE (id, dataset_id);

ALTER TABLE releases
    DROP CONSTRAINT releases_revision_id_fkey,
    ADD CONSTRAINT releases_revision_dataset_fk
        FOREIGN KEY (revision_id, dataset_id) REFERENCES dataset_revisions (id, dataset_id)
        ON DELETE NO ACTION ON UPDATE NO ACTION;

CREATE INDEX releases_revision ON releases (revision_id, dataset_id);
```

and the matching `downgrade()`, which must restore the single-column reference `0001` created:

```sql
DROP INDEX IF EXISTS releases_revision;
ALTER TABLE releases
    DROP CONSTRAINT IF EXISTS releases_revision_dataset_fk,
    ADD CONSTRAINT releases_revision_id_fkey
        FOREIGN KEY (revision_id) REFERENCES dataset_revisions (id);
ALTER TABLE dataset_revisions DROP CONSTRAINT IF EXISTS dataset_revisions_id_dataset_id_unique;
```

**What the unique key adds to the index set.** `dataset_revisions` currently carries four
btrees: `PRIMARY KEY (id)`, `UNIQUE (dataset_id, revision_number)`,
`UNIQUE (dataset_id, manifest_sha256)`, `UNIQUE (revision_path)`. None of them is a legal target
for a FK on `(id, dataset_id)` — a composite FK requires a unique constraint on exactly those
columns — so a fifth is unavoidable. It costs one extra btree entry per revision insert;
`dataset_revisions` is append-only and immutable, so there is no update churn to amortize. It
also serves the FK's own probe as an index-only scan, and answers "which dataset owns this
revision" without a heap fetch.

**Why `releases.revision_id` alone is dropped.** `dataset_revisions.id` is the primary key, so
a row satisfying `(revision_id, dataset_id)` necessarily satisfies `(revision_id)`. Keeping both
would mean two constraint entries and two index probes per release insert for one invariant.
This mirrors `0003`, which added `products_dataset_project_fk` alongside a plain
`dataset_id uuid REFERENCES datasets(id)` only because the column was being created in the same
statement; here the weaker constraint already exists and is strictly subsumed.

**Index ownership, reconciling with S4.** `releases_revision (revision_id, dataset_id)` is the
supporting index for the new FK and by leading-column prefix it also satisfies F3's
`releases.revision_id` entry. **S4 must not add a second index on `releases (revision_id)`** —
F3's row for this column is discharged here. Likewise the `ON DELETE`/`ON UPDATE` action on
`releases_revision_dataset_fk` is stated inline above because the FK is being written fresh;
it is `NO ACTION` on both, consistent with F7's expected uniform answer (releases are withdrawn,
never deleted; `dataset_revisions` keys are immutable, so `ON UPDATE` never fires). If S4's
sweep reaches a different verdict for catalog FKs, this row moves with it.

### Explicit contracts

**Invariant.** For every `releases` row, the cited `dataset_revisions` row belongs to the same
dataset the release belongs to. Formally: `releases.dataset_id = (SELECT dataset_id FROM
dataset_revisions WHERE id = releases.revision_id)`, and that revision exists.

**Totality.** `releases.dataset_id` and `releases.revision_id` are both `NOT NULL`, so the
default `MATCH SIMPLE` semantics never short-circuit — unlike `products_dataset_project_fk`,
where a NULL `dataset_id` (a fused product) legitimately skips the check. This FK is checked on
every row, always.

**Error behavior.** A violating INSERT raises SQLSTATE `23503` (`foreign_key_violation`),
surfaced by asyncpg as `asyncpg.exceptions.ForeignKeyViolationError` — *not* the
`asyncpg.exceptions.RaiseError` that the plpgsql guards produce. Any test or handler that
distinguishes them must use the FK class.

**Migration-time behavior.** The constraint is added without `NOT VALID`, so `0008` validates
every existing `releases` row and fails loudly on any that already mis-cites. That is the
intended behavior: such a row is a silent corruption of a citation anchor and must be seen, not
carried forward. It cannot arise in practice today — per Current State §5 no PostgreSQL writer
for `releases` exists, so the table is empty in every real database.

**What it assumes about writers.** Only that a writer supplies `dataset_id` and `revision_id`
consistently in the same INSERT; it imposes no ordering, no deferral, and no transaction shape.
It does assume a release is never repointed at a different revision, which the
`releases_immutable()` trigger already guarantees (below). No `pkg/` or `service/` change is
required by this task.

**Interaction with `releases_immutable()` — the constraint is cheap, and is not redundant.**
The trigger is `BEFORE UPDATE FOR EACH ROW` and freezes
`(id, dataset_id, tag, revision_id, title, created_by, created_at)`, leaving only the withdrawal
pair writable. Two consequences:

- *Not redundant.* The trigger does not fire on INSERT at all, and F1's proof was an INSERT that
  succeeded. Nothing in the schema examines the `(dataset_id, revision_id)` pair at insert time;
  the composite FK is the only mechanism that ever will.
- *Cheap.* Because the pair is frozen the instant the row exists, the FK is evaluated exactly
  once per release, at INSERT, and never again — the withdrawal UPDATE touches no FK column, so
  PostgreSQL skips the re-check entirely. One index probe per release created, against a table
  that gains rows at human pace. And validating at insert validates for the row's whole
  lifetime, because no repointing path exists.

**`revision_amendments` and `purge_records` — the audit's scoping confirmed.** Both carry
`revision_id uuid NOT NULL REFERENCES dataset_revisions(id)` and no `dataset_id` column, so
there is no second parent reference for the first to disagree with; no inconsistent pair is
representable and there is nothing to constrain. Confirmed by reading the `0001` DDL for both
tables; no change.

### `product_versions.snapshot_id` — decision: explicitly left, not fixed in `0008`

The composite-FK pattern needs a column the child and the disputed parent both carry and that
is `NOT NULL` on the child. Working the chain through rather than assuming it:

- `product_versions` has `product_id` and `snapshot_id`, and **no `dataset_id` and no
  `project_id`**. Applying the pattern would first require denormalizing a parent key down onto
  it, plus a second composite FK pinning that copy to the product — two new columns' worth of
  machinery, not one constraint.
- The only key the two sides could share is `dataset_id`, and it is **nullable on both**:
  `products.dataset_id` is NULL for a fused product (`0003`), `snapshots.dataset_id` is NULL for
  a gold snapshot (`snapshots_dataset_required_below_gold`). Under `MATCH SIMPLE` a NULL in the
  referencing tuple skips the check outright, so the constraint would be vacuous in exactly the
  fused case — where a stray `snapshot_id` is most likely. `MATCH FULL` does not rescue it: it
  demands all-or-none NULL, which would make a fused product's versions unrepresentable.
- The invariant one actually wants for a fused product is "the snapshot belongs to this
  *project*" — and **`snapshots` has no `project_id` column at all.** For a fused gold snapshot
  (`dataset_id IS NULL`) there is no path from the snapshot to any project. The correspondence
  is therefore not merely unconstrained; it is **not representable** in the current model.

So the honest fix is not a constraint, it is a modeling change to `snapshots` (see Open
questions), which is gold-layer design work and outside S1's scope. Fixing it half-way — a
composite FK that is vacuous for fused products — would buy the appearance of an invariant
without the invariant, which is worse than the recorded gap. The stakes are as the audit rated
them: a product version is not an immutable citation anchor the way a release is, it carries
`withdrawn_at`, and `derivation_record` (invariant K) records the real provenance in a document
that Python validates. Recorded as deliberately deferred, not dropped.

### Deletions

- `releases_revision_id_fkey` — the implicit single-column FK constraint created by
  `migrations/versions/0001_foundations.py` (the `REFERENCES dataset_revisions(id)` clause on
  `releases.revision_id`, line 81). Dropped as subsumed; the constraint name is the PostgreSQL
  default and must be spelled exactly, since `0001` never named it.
- No application code, no `pkg/` symbol, and no test is made obsolete — nothing in `src/huron/`
  reads or writes `releases`.
- `migrations/schema.sql` §1 (the `releases` block at line 75-83, and `dataset_revisions` at
  line 63) becomes stale on this change. S8 owns what "regenerate" means; this task only records
  that the file must reflect the new FK and unique key.

### Negative-write test

There is no contract test for the catalog hierarchy (Current State §6), so this needs a new
module — `tests/contract/test_catalog_store.py` — built on the `tests/contract/test_rbac_store.py`
shape: apply the migrations to a live database, insert fixtures directly (the file's existing
`_insert_organization` / `_insert_project` helpers are the template; `_insert_dataset` and
`_insert_dataset_revision` equivalents are new, and whether they are shared or duplicated is a
planning decision). The assertion mirrors `_assert_trigger_rejects_*` with one substitution —
the expected exception is `asyncpg.exceptions.ForeignKeyViolationError`, since this is a
constraint rather than a plpgsql `RAISE`:

```python
async def _assert_a_release_cannot_cite_another_datasets_revision(
    pool: asyncpg.Pool, *, citing_dataset_id: UUID, foreign_revision_id: UUID
) -> None:
    with pytest.raises(asyncpg.exceptions.ForeignKeyViolationError):
        await pool.execute(
            """
            INSERT INTO releases (id, dataset_id, tag, revision_id, created_by, created_at)
            VALUES ($1, $2, 'v1', $3, 'constraint-test', now())
            """,
            uuid7(),
            citing_dataset_id,
            foreign_revision_id,
        )
```

It must be paired with a positive write — the same insert against the revision's *own* dataset,
which must succeed — otherwise a constraint that rejects everything would pass the test. This is
the exact INSERT the audit proved succeeds today, so the test fails against `0007` and passes
against `0008`.

### Rejected alternatives

- **A `BEFORE INSERT` trigger looking up the revision's `dataset_id`** — imperative, one plpgsql
  function and one `SELECT` per insert, to express what a declarative FK expresses for free; the
  house already chose the FK for this bug class in `0003`.
- **Drop `releases.dataset_id` and reach the dataset through `revision_id`** — normalizes the
  redundancy away entirely, but breaks `UNIQUE (dataset_id, tag)` (tag uniqueness per dataset
  becomes unenforceable without a trigger) and forces a join on the citation-resolution path.
- **Add the composite FK `NOT VALID` and validate separately** — the online-migration hedge; the
  table is empty in every real database and a mis-citing row must fail the migration, not be
  grandfathered in.

### Open questions

1. **Should `snapshots` carry a `project_id`, mirroring the nullable-attachment split `0003`
   gave `products`?** Flagged for a human. Today a gold snapshot with `dataset_id IS NULL` has
   no ancestor of any kind — no dataset, no project, no organization — so a fused product
   version's snapshot reference cannot be tied to anything, and `product_versions.snapshot_id`
   is unfixable as a consequence, not as an oversight. Adding `snapshots.project_id NOT NULL`
   (a snapshot always belongs to some project, whether or not it belongs to a dataset), plus
   `snapshots_dataset_project_fk` against `datasets_id_project_id_unique` — the `0003` pattern
   again — would give both `product_versions` and every future gold consumer a real anchor.
   This is a gold-layer modeling change with a column addition, not a constraint fix, so it
   belongs in its own design task against `design/layer-gold.html`, not in S1. **Not resolved
   here, and `0008` does not touch `snapshots` on S1's account.**

---

## S2 — Closed state and lifecycle vocabularies (design)

### The enumeration, and F2's count

F2's prose says "twelve enum-like text columns"; its table lists **sixteen** `(table, column)`
pairs across fourteen tables. The gap is arithmetic, not substance: 4 `lifecycle_state` + 6
`state` + 1 `severity` + 5 in the `kind` family (`jobs.kind`, `audit_events.kind`,
`outbox_events.kind`, `lineage_edges.upstream_kind`, `lineage_edges.downstream_kind`) = 16, and
"twelve" is reachable only by collapsing that fourth row to one entry (11 + 1). **The table is
right and the prose is wrong.** S2 owns exactly **eleven** columns; S3 owns the other five. No
column in F2's table is unaccounted for by the two tasks, and no column outside it was found.

### Target design

Evidence sources, abbreviated below: **CS §2** = `design/catalog-search.html` §2 "PostgreSQL
schema (delta)", which spells several of these as literal `CHECK IN (...)` lists; **RBAC §3** =
`design/rbac.html` §3 "Dataset lifecycle and policy inheritance"; **GOLD §2** =
`design/layer-gold.html` §2 resource identity/mutable table; **RAW §8/§9** =
`design/layer-raw.html` §8 "Retention" and §9 "Sweeper and reconciler"; **API §4/§6** =
`design/api.html`; **RM m4/P3/P6** = `design/roadmap.html` §3 milestone 4 and §2 phases P3/P6.

| # | Column | Verdict | Permitted set | Evidence | `pkg/` `StrEnum` |
|---|---|---|---|---|---|
| 1 | `organizations.lifecycle_state` | constrain to today's reality | `ACTIVE` | `0001` `DEFAULT 'ACTIVE'`; no transition documented anywhere; RM m4 lists "organization lifecycle" as `todo` | no |
| 2 | `projects.lifecycle_state` | constrain to today's reality | `ACTIVE` | `0001` `DEFAULT 'ACTIVE'`; RM m4/m15 name the *transitions* ("project archive and delete-when-empty") but no stored vocabulary | no |
| 3 | `datasets.lifecycle_state` | closed, settled | `ACTIVE`, `RETIRED`, `SUPERSEDED` | CS §2 spells the CHECK verbatim; RBAC §3 independently: "lifecycle is `ACTIVE` → `RETIRED` (plus `SUPERSEDED` for slug mistakes)"; `0006` removed `DRAFT` | **yes, now** — `huron.pkg.catalog.lifecycle.DatasetLifecycle` |
| 4 | `products.lifecycle_state` | closed, settled | `ACTIVE`, `DEPRECATED`, `RETIRED` | GOLD §2, Product row: "lifecycle (`ACTIVE` / `DEPRECATED` / `RETIRED`)"; corroborated by `design/polaris.html` §4 ("`RETIRED` products are dropped from Polaris") | not yet — no writer |
| 5 | `dataset_revisions.state` | closed, settled | `COMMITTED`, `EXPIRED_PARTIAL`, `EXPIRED`, `PURGED`, `DEGRADED` | CS §2 spells the CHECK verbatim; RAW §8 produces `EXPIRED_PARTIAL`/`EXPIRED`, RAW §8 purge produces `PURGED`, RAW §9 reconciler produces `DEGRADED`; `0001` `DEFAULT 'COMMITTED'` | not yet — no writer |
| 6 | `ingest_files.state` | **cannot be settled today** | — | none: CS §2 names the column and CHECKs `action` on the same line while leaving `state` bare; `pkg/catalog/ingest.py` has no per-file state (`UploadPlanEntry` carries only `file`, `action`, `parent_path`) | no |
| 7 | `jobs.state` | **cannot be settled today** | — | CS §2 CHECKs `jobs.kind` and leaves `state` bare; only `QUEUED` is evidenced (`0001` default + the `jobs_claim` partial index `WHERE state = 'QUEUED'`); RM P6 is `todo` | no |
| 8 | `purge_records.state` | closed, settled | `REQUESTED`, `APPROVED`, `EXECUTED` | RAW §8 "Purge": request → a different admin approves → execution; API §6 exposes exactly `:request-purge` and `:approve`; the column set `requested_at` / `approved_at` / `executed_at` maps 1:1; `0001` `DEFAULT 'REQUESTED'` | not yet — no writer |
| 9 | `snapshots.state` | closed, settled | `CANDIDATE`, `PUBLISHED`, `SUPERSEDED`, `FAILED` | CS §2 spells the CHECK verbatim; API §4 corroborates ("snapshot `CANDIDATE` → validated → `PUBLISHED` (or `FAILED` …)") | not yet — no writer |
| 10 | `product_versions.state` | closed, settled | `CANDIDATE`, `PUBLISHED`, `STALE`, `SUPERSEDED`, `WITHDRAWN` | CS §2 spells the CHECK verbatim (as `status`); GOLD §2 independently: "`CANDIDATE` → `PUBLISHED` → `STALE` / `SUPERSEDED` / `WITHDRAWN`"; the `stale_reason` and `withdrawn_at` columns corroborate two members | not yet — no writer |
| 11 | `reconciliation_findings.severity` | **cannot be settled today** | — | none: RAW §9 names findings and alerts but every vocabulary word there (`DEGRADED`) is a *revision* state, not a finding severity; `code` already carries the finding type; RM P3 is `todo` | no |

Two vocabularies deliberately differ where a careless reading would unify them:

- **`datasets` gets `SUPERSEDED`, `products` gets `DEPRECATED`.** They are not synonyms and not
  interchangeable: a superseded dataset is a slug mistake replaced by another dataset (RBAC §3);
  a deprecated product is still the product, discouraged (GOLD §2). Four separate CHECKs, not one
  shared vocabulary.
- **`snapshots` and `product_versions` share `CANDIDATE`/`PUBLISHED`/`SUPERSEDED` but diverge**
  (`FAILED` for a snapshot that failed validation; `STALE`/`WITHDRAWN` for a version whose input
  was superseded or whose publication was retracted). Again two CHECKs.

**Naming discrepancy, recorded so nobody "fixes" it later.** CS §2 calls the
`product_versions` column `status`; `0001` calls it `state`, consistently with every sibling
table. The migration name wins — the schema is the source of truth per CS §2's own preamble
("the Alembic migrations are the source of truth"). `0008` does not rename anything.

**A vocabulary word that is not a state.** API §4 and RM P6 both write "`CANDIDATE` → validated →
`PUBLISHED`". *Validated* is a gate in the flow, not a stored value — CS §2's explicit CHECK list
for `snapshots.state` omits it, and `validation_evidence jsonb` is where the gate's output lands.
It is not in the permitted set.

#### DDL

All of it lands in the single module-level `DDL` string of `0008`, per the binding convention.
Constraint names follow the house's descriptive style (`snapshots_dataset_required_below_gold`,
`role_bindings_principal_format`), because an `ALTER TABLE ADD CONSTRAINT` must name what `0001`
left to PostgreSQL's inline defaults.

```sql
-- ------------------------------------------------------- hierarchy lifecycle
-- Organizations and projects have no lifecycle transition built and no
-- vocabulary in the design record: ACTIVE is the complete set of values the
-- system can produce. Milestone 4, which defines retire/archive, widens these
-- two lists in the migration that defines the transitions.
ALTER TABLE organizations
    ADD CONSTRAINT organizations_lifecycle_state_vocabulary
        CHECK (lifecycle_state IN ('ACTIVE'));

ALTER TABLE projects
    ADD CONSTRAINT projects_lifecycle_state_vocabulary
        CHECK (lifecycle_state IN ('ACTIVE'));

-- A dataset is ACTIVE from creation (0006); RETIRED is the end of its working
-- life; SUPERSEDED names the slug mistake replaced by another dataset.
ALTER TABLE datasets
    ADD CONSTRAINT datasets_lifecycle_state_vocabulary
        CHECK (lifecycle_state IN ('ACTIVE','RETIRED','SUPERSEDED'));

ALTER TABLE products
    ADD CONSTRAINT products_lifecycle_state_vocabulary
        CHECK (lifecycle_state IN ('ACTIVE','DEPRECATED','RETIRED'));

-- ----------------------------------------------------------- revision state
-- COMMITTED is the only state ingest produces. Retention writes EXPIRED_PARTIAL
-- or EXPIRED, purge writes PURGED, and the reconciler writes DEGRADED for a
-- disagreement it will not silently repair.
ALTER TABLE dataset_revisions
    ADD CONSTRAINT dataset_revisions_state_vocabulary
        CHECK (state IN ('COMMITTED','EXPIRED_PARTIAL','EXPIRED','PURGED','DEGRADED'));

-- --------------------------------------------------- published representations
ALTER TABLE snapshots
    ADD CONSTRAINT snapshots_state_vocabulary
        CHECK (state IN ('CANDIDATE','PUBLISHED','SUPERSEDED','FAILED'));

ALTER TABLE product_versions
    ADD CONSTRAINT product_versions_state_vocabulary
        CHECK (state IN ('CANDIDATE','PUBLISHED','STALE','SUPERSEDED','WITHDRAWN'));

-- ---------------------------------------------------------------- governance
-- The three points of the two-person purge, one per timestamp column.
ALTER TABLE purge_records
    ADD CONSTRAINT purge_records_state_vocabulary
        CHECK (state IN ('REQUESTED','APPROVED','EXECUTED'));
```

and the matching `downgrade()`:

```sql
ALTER TABLE purge_records DROP CONSTRAINT IF EXISTS purge_records_state_vocabulary;
ALTER TABLE product_versions DROP CONSTRAINT IF EXISTS product_versions_state_vocabulary;
ALTER TABLE snapshots DROP CONSTRAINT IF EXISTS snapshots_state_vocabulary;
ALTER TABLE dataset_revisions DROP CONSTRAINT IF EXISTS dataset_revisions_state_vocabulary;
ALTER TABLE products DROP CONSTRAINT IF EXISTS products_lifecycle_state_vocabulary;
ALTER TABLE datasets DROP CONSTRAINT IF EXISTS datasets_lifecycle_state_vocabulary;
ALTER TABLE projects DROP CONSTRAINT IF EXISTS projects_lifecycle_state_vocabulary;
ALTER TABLE organizations DROP CONSTRAINT IF EXISTS organizations_lifecycle_state_vocabulary;
```

`IN ('ACTIVE')` rather than `= 'ACTIVE'` for the two single-member lists is deliberate: it keeps
all eight constraints one shape, and widening one at milestone 4 is then a visibly ordinary edit
rather than a rewrite.

**Downgrade ordering matters and Alembic already enforces it.** `0006`'s `downgrade()` restores
`datasets.lifecycle_state DEFAULT 'DRAFT'`, a value `datasets_lifecycle_state_vocabulary`
refuses. Alembic runs `0008`'s downgrade first, so the CHECK is gone before the default returns;
no cross-revision coupling has to be written down anywhere but here.

#### The `pkg/` `StrEnum` companions

The house pattern is a `StrEnum` in `pkg/` mirrored by an `IN (...)` CHECK — `IngestState` and
`ingest_sessions.state`, `UploadAction` and `ingest_files.action`. The rule this task applies:
**an enum lands when it has a consumer, and otherwise lands with the writer that first needs it,
in the same change as the writer** — the same "Python module changes first, in the same change"
convention `0002`/`0004`/`0005`/`0006`/`0007` state in their docstrings. Nine dead enums mirroring
nine CHECKs would be exactly the speculative abstraction the clean-sweep rule forbids, and the
CHECK is a perfectly good written record of the vocabulary in the meantime.

Exactly one column has a consumer today:

- **`DatasetLifecycle`**, new, in **`src/huron/pkg/catalog/lifecycle.py`** — a pure-domain module
  beside `ingest.py` and `layers.py`, which is where this codebase keeps domain vocabularies
  (`models.py` holds dataclasses only, no enums). Members `ACTIVE`, `RETIRED`, `SUPERSEDED`,
  mirroring the CHECK exactly. Its consumers exist now:
  `src/huron/service/api/repository.py:97` types the `Dataset` dataclass field as `str`, and
  `repository.py:542` writes the bare literal `"ACTIVE"` at dataset creation — the only
  `lifecycle_state` reference in `src/huron/`. Both become the enum.
- `lifecycle.py` is also the decided home for `ProductLifecycle` and `RevisionState` when their
  writers land, so that placement is not re-litigated. Neither is created by `0008`.

`Organization` and `Project` in `repository.py` carry **no** `lifecycle_state` field at all, so
there is nothing for an organization/project enum to type even if the vocabulary were settled.

#### What `0008` must do about pre-existing data

Nothing — and that is a decision, not an omission. Compare `0006`, which is the only precedent
for narrowing one of these columns: it ran
`UPDATE datasets SET lifecycle_state = 'ACTIVE' WHERE lifecycle_state = 'DRAFT';` **before**
`ALTER COLUMN … SET DEFAULT 'ACTIVE'`. That UPDATE was a *semantic* migration — `DRAFT` was being
abolished along with the steward role, and existing drafts had to become something — not a
defensive guard against unknown data.

`0008` needs no equivalent because every CHECK is satisfiable by construction:

- `datasets` was already lifted by `0006`, and the only writer since is the in-memory repository,
  which writes `"ACTIVE"`.
- The other seven columns are in tables with **zero PostgreSQL writers** (Current State §5), so
  they hold their `DEFAULT` or nothing at all. Each default is inside its permitted set:
  `ACTIVE` (organizations, projects, products), `COMMITTED` (dataset_revisions),
  `REQUESTED` (purge_records). `snapshots.state` and `product_versions.state` are `NOT NULL`
  with no default, in tables that are empty in every real database.

So the constraints are added **without `NOT VALID`**: each validates every existing row at
migration time and fails loudly on anything else. That is the intended behavior and matches S1's
posture on the composite FK. A defensive `UPDATE … SET state = '…'` would silently rewrite rows
whose provenance nobody can explain, which is strictly worse than a migration that stops.

### Explicit contracts

**The invariant, uniformly.** Each CHECK enforces exactly one thing: *this column holds a value
the design record names, spelled exactly as the design record spells it.* Nothing more. In
particular none of these constraints enforces a transition, an ordering, or agreement with a
sibling column.

**What each CHECK assumes about writers.**

| Constraint | Assumes |
|---|---|
| `organizations_…`, `projects_…` | that no writer transitions these rows at all — true today by construction (no PostgreSQL writer; the in-memory dataclasses have no such field). The constraint is the tripwire that turns milestone 4's first `retire`/`archive` write into a loud failure instead of a silently invented vocabulary. |
| `datasets_lifecycle_state_vocabulary` | that a writer supplies one of the three literals uppercase. The in-memory repository already does. A future PostgreSQL hierarchy writer must use `DatasetLifecycle`, not a string. |
| `dataset_revisions_state_vocabulary` | that the retention worker, the purge executor and the reconciler are the only things that ever move a revision off `COMMITTED`, each writing its documented value. |
| `snapshots_…`, `product_versions_…` | that the intake/product job pipeline writes `CANDIDATE` at creation and the publish/withdraw/staleness paths write the rest. `product_versions` additionally has `stale_reason`, `published_at` and `withdrawn_at`; the CHECK does **not** require them to agree with `state`. |
| `purge_records_state_vocabulary` | that the request/approve/execute endpoints advance the value alongside `requested_at`/`approved_at`/`executed_at`. The CHECK does **not** require that agreement either. |

**What these CHECKs deliberately do not enforce.** Three of these tables carry both a `state`
column and the timestamps that encode the same progression (`purge_records`, `jobs`,
`product_versions`). Whether `state = 'APPROVED'` implies `approved_at IS NOT NULL` is a
cross-column invariant of exactly the kind `0001` already writes elsewhere
(`(withdrawn_at IS NULL) = (withdrawn_reason IS NULL)`), but no finding raises it and no writer
exists to violate it. Named here so it is a deferral rather than an oversight; it belongs with
the design task that builds each writer.

**Three-valued logic is not a hole here.** The skill warns that a NULL passes any CHECK. All
eleven columns are `NOT NULL` in `0001`, so every row is genuinely tested; none of these
constraints needs the NULL-safe spelling `0004` required for `snapshots.provenance`.

**Error behavior.** A violating INSERT or UPDATE raises SQLSTATE `23514` (`check_violation`),
surfaced by asyncpg as `asyncpg.exceptions.CheckViolationError` — *not* the
`asyncpg.exceptions.RaiseError` the plpgsql guards produce. This refines the note S1 recorded:
`tests/contract/test_auth_store.py:209` and `:248` already assert exactly this class, so the
template exists and needs no invention.

### Negative-write tests

Eight constraints, eight rejected writes, each paired with a permitted write that must succeed —
otherwise a constraint that rejects everything would pass. They belong in the new
`tests/contract/test_catalog_store.py` that S1 introduces, on the
`tests/contract/test_rbac_store.py` `_assert_trigger_rejects_*` shape with
`asyncpg.exceptions.CheckViolationError` substituted for `RaiseError`. Two of them are the audit's
own proofs replayed and must now fail: `UPDATE datasets SET lifecycle_state = 'BANANA'`, and the
empty-string update against `projects` — the empty string is the case a format regex would also
catch and a vocabulary CHECK catches for free. `dataset_revisions.state = 'NOT_A_STATE'` is the
third audit proof in S2's scope; the fourth (`jobs.state = 'WAT'`) stays passing on purpose, and
that is recorded below rather than hidden.

### Deletions

- **None.** No constraint, index, trigger or table is made removable by this task; every CHECK
  here is additive over a column that had none.
- Two **replacements**, not deletions, in `src/huron/service/api/repository.py`: the bare
  `lifecycle_state: str` annotation at line 97 and the bare `"ACTIVE"` literal at line 542 become
  `DatasetLifecycle`. They are the entire application-side footprint of this task.
- `migrations/schema.sql` §1, §2, §4, §5 and §6 become stale (the `lifecycle_state`, `state` and
  `severity` lines gain or conspicuously lack a vocabulary comment). **S8 owns what "regenerate"
  means**; recorded here only so the file is not forgotten.

### Rejected alternatives

- **Native `CREATE TYPE … AS ENUM` per vocabulary** — the skill reserves enum types for "small,
  stable sets (US states, days of week)" and sends "business-logic-driven and evolving values" to
  `TEXT` + CHECK; `lifecycle_state` is *known* to be evolving (milestone 4 widens it), a value can
  never be removed from an enum type, and all thirteen existing closed vocabularies in this schema
  are `TEXT` + CHECK. A departure would need a strong reason and there is none.
- **Lookup tables** — the schema already has this pattern where it earns its keep (`roles` /
  `capabilities` carry titles, descriptions, `allowed_principal_kinds`, and are administered at
  runtime). These eleven vocabularies carry no attributes and are never administered; a lookup
  table buys a join, an FK, and an index per column in exchange for nothing.
- **One shared `lifecycle_state` vocabulary, or a `CREATE DOMAIN`, across all four tables** — the
  evidence refutes it: the union would permit a `DEPRECATED` dataset and a `SUPERSEDED` product,
  neither of which the design record defines.
- **A format regex (`~ '^[A-Z][A-Z_]{1,31}$'`) for the three unsettled columns** — that is S3's
  open-vocabulary pattern (`policies.policy_type` is the precedent) and it is wrong here: it would
  accept `'BANANA'`, the exact value F2 proved must be refused, while looking like a decision. If
  a column's set is closed, a format constraint is a placeholder pretending to be an invariant.
- **Deferring the whole task until the writers exist** — rejected: seven of the eleven columns
  have their vocabulary fixed in the design record today, and the record is where a writer would
  read it from anyway. Writing the CHECK now makes the migration the enforcement point rather
  than a convention each future writer re-derives.

### Open questions

1. **The organization and project lifecycle vocabulary — flagged for milestone 4, not for
   `0008`.** RM m4 promises "retire / archive as bare, permission-checked transitions" and
   "project archive and delete-when-empty; organization lifecycle", but never says what is
   *stored*. Three questions have to be answered together: does `archive` write an `ARCHIVED`
   value distinct from `RETIRED`, or is archiving the deletion path for an empty project and not
   a state at all; can an organization be suspended (the only source for `SUSPENDED` anywhere is
   the `<select>` in `web/src/routes/settings/organization/+page.svelte`, in a file whose own
   header calls itself a placeholder "shaped to the design record, not to any running endpoint",
   and which contradicts `web/src/lib/api/types.ts:13`'s `Lifecycle = 'ACTIVE' | 'RETIRED'` and
   the `Active/Draft/Retired` list in the sibling project page); and does a project inherit
   `SUPERSEDED` from datasets. **`0008` takes no position beyond `IN ('ACTIVE')`**, which is the
   complete set of values the system can produce today.
2. **`ingest_files.state` — vocabulary undecided, and the column itself may be redundant.** Beyond
   having no documented values (`PENDING` is only its default), it overlaps
   `completed_parts jsonb`, which RAW §4 makes the authority on resume ("Interrupted transfers
   resume via `completed_parts`"), and `action`, which already says whether a file is uploaded or
   hardlinked. Settled by the P2 upload-plane design answering whether per-file progress is
   *derived* from `completed_parts` — in which case the column should be dropped, not CHECKed — or
   stored. Note CS §2's version of this table also carries an `observed_sha256` that `0001` does
   not, so the row shape here is not final.
3. **`jobs.state` — same shape, and the design record points at a sibling that has no state
   column at all.** Only `QUEUED` is evidenced. CS §2 says jobs are "claimed `FOR UPDATE SKIP
   LOCKED`, like the outbox", and `outbox_events` has no `state`: it uses `processed_at IS NULL`
   with the `outbox_unprocessed` partial index. `jobs` already has `claimed_at`, `completed_at`
   and `attempts`, so the real question P6 must answer is whether `state` is the truth or a
   denormalization of those three. Constraining it now would freeze the wrong answer.
4. **`reconciliation_findings.severity` — no vocabulary exists to adopt.** RAW §9 is the findings
   table in prose (orphan envelope → import; row without envelope → `DEGRADED` + alert; digest
   mismatch → `DEGRADED`; missing payload without a `PURGED`/`EXPIRED` marker → `DEGRADED`; stale
   `INDEX.json` → regenerate; torn `CURRENT.json` → repoint), and every vocabulary word in it is a
   *revision* state, not a finding severity. `code` already carries the finding type. Settled by
   RM P3 ("reconciler implementing the findings table"), which must assign each of those
   conditions a severity — the natural split being self-repairing versus alerting — and that is
   that task's decision to make, not this one's.

---

## S3 — Event `kind` vocabularies (design)

### The question, and the rule that answers it

S2 asked *what are the legal values*. S3 asks *is a fixed value set the right model here at
all*. The five columns do not answer that question the same way, and the discriminator is not
"is it an event" — it is **what a reader does with a value it does not recognize**:

- If an unrecognized value is **still a useful record**, the column is open. An audit log that
  refuses to record an event kind nobody thought of has destroyed the only evidence that the
  unforeseen thing happened. The refusal aborts the writing transaction, which for an audit row
  means aborting the mutation it was auditing.
- If an unrecognized value is **unusable** — it names a container that cannot be started, or a
  table that cannot be joined — the column is closed. The row is not a record of something that
  happened; it is an instruction nothing can carry out, and it fails silently by sitting there.

**Open is not unconstrained, and the schema already proves it.** `policies.policy_type` carries
`~ '^[a-z][a-z0-9_]{1,62}$'` with no `IN` list; `capabilities.code` carries a dotted-name regex
`'^[a-z][a-z0-9_]*\.[a-z][a-z0-9_]*$'`; `roles.code` carries the same flat form as
`policy_type`. Three existing columns whose value set is administered rather than enumerated,
all three format-constrained. That is the precedent the two open columns follow.

The division of labour that follows: **a closed `IN (...)` says which values exist; a format
regex says nothing about which values exist and everything about what a value is allowed to
look like** — non-empty, lowercase, bounded, no whitespace, no punctuation surprises. The second
is worth having on its own, because a `kind` is a routing key and a grouping key: it is filtered
on, faceted over, rendered in a UI and printed into logs. The audit's own proof that
`lifecycle_state` accepted the empty string is the shape of bug a format CHECK catches here.

### Target design

Evidence sources, abbreviated as in S2: **CS §2** = `design/catalog-search.html` §2 "PostgreSQL
schema (delta)"; **CS §3** = the same document's §3 "Lineage"; **ARCH §** =
`design/architecture.html` (the component table at lines 165–200 and the walkthrough at 217–224);
**GOLD §3** = `design/layer-gold.html` §3 "The derivation record"; **SILVER §** =
`design/layer-silver.html` (the publish step and "Lineage roots at the entry layer");
**RM m3/T18/P4/P6/P9/P10** = `design/roadmap.html` §3 milestones and §2 phases.

| # | Column | Verdict | Value set / format | Evidence | One-line reason |
|---|---|---|---|---|---|
| 1 | `jobs.kind` | **closed `IN (...)`** | `bronze_build`, `canonicalize`, `product_run`, `validate`, `polaris_sync`, `retention`, `reconcile` | CS §2 spells the `CHECK IN` verbatim; ARCH § names a worker for each of the seven | A job kind is a dispatch key naming a digest-pinned container — a kind no runner claims is an undispatchable work order, not a record. |
| 2 | `audit_events.kind` | **open, format-constrained** | `^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)*$`, length 2–63 | CS §2 elides this table's columns entirely; RM m3 requires "an audit row for every mutation **and every denied operation**" | The vocabulary is one entry per mutating route plus every denial — it grows with the API surface, and refusing an unforeseen kind would abort the mutation being audited. |
| 3 | `outbox_events.kind` | **open, format-constrained** | same regex and bound | CS §2 elides this table's columns too; consumers arrive a phase at a time — projection (P4/RM m6), bronze builder (ARCH §, P6), Polaris sync (P10), notification fan-out (RM T18) | The outbox is written inside the catalog-commit transaction, so a too-narrow CHECK converts "unknown event kind" into "revision not recorded despite durable bytes" — the exact failure invariant G exists to prevent. |
| 4 | `lineage_edges.upstream_kind` | **closed `IN (...)`** | `raw_revision`, `bronze_snapshot`, `silver_snapshot`, `gold_version` | CS §3: "typed nodes (`raw_revision`, `bronze_snapshot`, `silver_snapshot`, `gold_version`)"; GOLD §3 and SILVER § independently write the same chain | A node kind names the table the id lives in — a fourth value is an edge no traversal can resolve, and the edge is written once at publication and never revisited. |
| 5 | `lineage_edges.downstream_kind` | **closed `IN (...)`** | the same four | as above | Same vocabulary, same table, same argument — see below for why it is *the same* list and not a narrower one. |

Nothing in scope is left genuinely unconstrained. Every one of the five gets a constraint; the
decision that varies is whether the constraint enumerates or shapes.

#### The `lineage_edges` pair, decided together

The two columns draw on **one** vocabulary and get **two identical CHECKs**, not one shared list
and not a narrower list on either side.

- **The vocabulary is closed and stated twice.** CS §3 calls them "typed nodes" and names four.
  GOLD §3 writes the chain `gold_version ← silver_snapshot ← bronze_snapshot ← raw_revision`;
  SILVER § writes `silver snapshot ← bronze snapshot ← raw revision` for the publish step. CS §2's
  worked example is `(silver_snapshot S119) ─derives_from→ (bronze_snapshot B187) region run-0042`.
  Three documents, one vocabulary, spelled identically. This is stronger evidence than S2 had for
  most of its closed columns.
- **Each kind resolves to exactly one table**, which is what makes the set closed:
  `raw_revision` → `dataset_revisions.id`; `bronze_snapshot` and `silver_snapshot` →
  `snapshots.id`, disambiguated by that row's `layer`; `gold_version` → `product_versions.id`.
  The kind is layer-qualified because `snapshots` is one table for three layers, so the layer
  cannot be recovered from the id alone without a join the traversal is trying to avoid.
- **`gold_snapshot` is deliberately not a node.** A published Gold snapshot exists — GOLD §3's
  derivation record carries `"produced_snapshot": "G021"`, and `product_versions.snapshot_id`
  references it — but the citable Gold identity is the *version*, and both CS §3 and GOLD §3 stop
  at `gold_version`. Adding a fifth member on the strength of a column that already reaches the
  snapshot by FK would invent a node the traversals do not define.
- **Both columns get the full four.** A tempting narrowing — `gold_version` can only ever be
  downstream, `raw_revision` only ever upstream — is wrong, and the counterexample is in the
  design record: GOLD §5 says a recomputation "is a new version whose record points at both its
  inputs **and the version it supersedes**", which is a `gold_version → gold_version` edge. Since
  a layer-ordering constraint has to permit that, it stops being an ordering constraint. See
  Rejected alternatives.
- **Naming discrepancy, recorded so nobody "fixes" it.** CS §2 calls the columns
  `from_kind` / `to_kind`; `0001` calls them `upstream_kind` / `downstream_kind`. Same convention
  question S2 settled for `status` vs `state`, same answer: the migration is the source of truth
  and `0008` renames nothing.
- **A different `kind` that must not be unified with this one.** `web/src/lib/api/types.ts:96`
  declares `SearchHit.kind: 'dataset' | 'release' | 'product'`. That is the search-projection
  facet vocabulary (RM m6, "facets for type, layer, …"), over resources rather than lineage
  nodes. Two vocabularies, no overlap in members, no relationship. Neither constrains the other.

#### DDL

All of it lands in the single module-level `DDL` string of `0008`, per the binding convention.
Constraint names follow the house's split: `*_vocabulary` for an enumerated set (S2's eight
constraints), `*_format` for a shape constraint (`role_bindings_principal_format`).

```sql
-- ------------------------------------------------------------------------ jobs
-- A job kind is a dispatch key: it names the digest-pinned container the job
-- runner starts. One kind per documented worker; a kind no runner claims is a
-- work order that sits QUEUED forever rather than failing.
ALTER TABLE jobs
    ADD CONSTRAINT jobs_kind_vocabulary
        CHECK (kind IN ('bronze_build', 'canonicalize', 'product_run', 'validate',
                        'polaris_sync', 'retention', 'reconcile'));

-- ---------------------------------------------------------- audit and outbox
-- Both vocabularies are open on purpose. The audit vocabulary is one entry per
-- mutating route and per denied operation; the outbox fans out to a consumer
-- set that grows a phase at a time. Refusing an unforeseen kind would abort the
-- transaction being recorded, which is a worse outcome than recording it.
-- Open is not unconstrained: a kind is a routing and grouping key, so it is held
-- to the lowercase dotted-name shape used for every machine-read identifier here.
ALTER TABLE audit_events
    ADD CONSTRAINT audit_events_kind_format
        CHECK (kind ~ '^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)*$'
               AND length(kind) BETWEEN 2 AND 63);

ALTER TABLE outbox_events
    ADD CONSTRAINT outbox_events_kind_format
        CHECK (kind ~ '^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)*$'
               AND length(kind) BETWEEN 2 AND 63);

-- --------------------------------------------------------------- lineage_edges
-- A node kind names the table its id lives in: raw_revision -> dataset_revisions,
-- bronze_snapshot and silver_snapshot -> snapshots (disambiguated by that row's
-- layer), gold_version -> product_versions. Both ends draw on the same set: a
-- recomputed product version cites the version it supersedes, so gold_version
-- appears upstream as well as downstream.
ALTER TABLE lineage_edges
    ADD CONSTRAINT lineage_edges_upstream_kind_vocabulary
        CHECK (upstream_kind IN ('raw_revision', 'bronze_snapshot',
                                 'silver_snapshot', 'gold_version')),
    ADD CONSTRAINT lineage_edges_downstream_kind_vocabulary
        CHECK (downstream_kind IN ('raw_revision', 'bronze_snapshot',
                                   'silver_snapshot', 'gold_version'));
```

and the matching `downgrade()`:

```sql
ALTER TABLE lineage_edges
    DROP CONSTRAINT IF EXISTS lineage_edges_downstream_kind_vocabulary,
    DROP CONSTRAINT IF EXISTS lineage_edges_upstream_kind_vocabulary;
ALTER TABLE outbox_events DROP CONSTRAINT IF EXISTS outbox_events_kind_format;
ALTER TABLE audit_events DROP CONSTRAINT IF EXISTS audit_events_kind_format;
ALTER TABLE jobs DROP CONSTRAINT IF EXISTS jobs_kind_vocabulary;
```

The `\.` in the regex is a literal backslash-dot under the default
`standard_conforming_strings = on`, and `migrations/_ddl.py` holds the DDL in a raw string, so it
survives both layers. `0002`'s `capabilities.code` CHECK already contains exactly this escape and
applies cleanly, so the pattern is proven in this codebase, not assumed.

**The regex was executed, not reasoned about.** Against PostgreSQL 16, the CHECK accepts
`revision.committed`, `dataset.created`, `raw_committed`, `policy.attachment.replaced`,
`x_y.z_0`, and a 63-character name; it refuses `BANANA`, the empty string, `a`,
`Revision.Committed`, `revision committed`, `revision.`, `.revision`, `1revision`,
`ingest-committed`, `data.write:denied`, and a 64-character name. The hyphen and colon
rejections are deliberate: hyphens are the *slug* convention (`^[a-z0-9][a-z0-9-]{1,61}$`,
user-authored display names), and every machine-read identifier in this schema — `roles.code`,
`capabilities.code`, `policies.policy_type` — is snake and dotted. If a future audit kind wants
to encode an outcome, `data.write.denied` is available and `data.write:denied` is not; that is a
convention decision the constraint makes on purpose rather than by accident.

The 2–63 length bound is not arbitrary either: `policy_type`'s `{1,62}` after its leading
character is exactly a 2–63 character name, so the two open vocabularies and the existing open
vocabulary agree on bounds. Expressing it as a second conjunct rather than folding it into the
regex is the house spelling for a two-part format CHECK — `0001`'s slug constraints are
`slug ~ '…' AND slug !~ '--'`.

#### `audit_events` is partitioned — what that costs, and the S6 dependency

Adding a CHECK to a partitioned parent is supported and behaves well; this was verified on
PostgreSQL 16 rather than assumed:

- `ALTER TABLE audit_events ADD CONSTRAINT … CHECK (…)` **recurses to every existing partition**.
  After the statement, `pg_constraint` holds three rows for the constraint name: the parent
  (`conislocal = t`, `coninhcount = 0`) and each child (`conislocal = f`, `coninhcount = 1`),
  all with `convalidated = t`.
- **A partition created afterwards inherits it automatically.** Creating
  `audit_events_2026_09 PARTITION OF audit_events FOR VALUES FROM … TO …` after the ALTER
  produced the constraint on the new child with no further DDL. So if S6 commits to bounded
  monthly partitions, whatever creates them ahead of time needs to know nothing about this
  constraint, now or ever.
- **Cost.** The ALTER takes `ACCESS EXCLUSIVE` on the parent and every partition for the duration
  of validation. Today that is the parent plus one empty `audit_events_default`, and nothing in
  `src/huron/` writes `audit_events` at all (Current State §5), so the lock is held for the time
  it takes to scan zero rows.

**Cross-task dependency on S6 — stated, not assumed.** S3 does not need S6's outcome and does not
predict it, but `0008`'s single `DDL` string has one statement order and the two tasks touch the
same relation:

- If **S6 keeps the partitioning** (bounded partitions, or the status quo), the DDL above is
  correct as written and its position in the string does not matter.
- If **S6 de-partitions** `audit_events`, the surviving relation is a new or renamed plain table,
  and `audit_events_kind_format` must be created **after** that DDL, against the surviving
  relation. A constraint added to the old partitioned parent would be dropped along with it.

The verdict itself is unaffected either way: the vocabulary is open because of what an audit row
is, not because of how the table is stored. **Whichever of S3/S6 is sequenced second in
`SCHEMA_IMPLEMENTATION_PLAN.md` owns placing this statement after the `audit_events` structural
DDL.**

### Explicit contracts

**What `jobs_kind_vocabulary` guarantees.** Every `jobs` row names one of seven workers that
`design/architecture.html` documents. It does **not** guarantee that `subject_id` refers to
anything of the right type for that worker (there is no `subject_kind` column on `jobs` in
`0001`, though CS §2's version of the table has one — see Open questions), that a runner for that
kind is deployed, or that `payload` matches the kind's expected shape.

**What the two `*_kind_format` CHECKs guarantee.** Every `audit_events.kind` and
`outbox_events.kind` is a non-empty, lowercase, bounded, whitespace-free dotted or flat snake
name — safe to use as a filter key, a facet value, a metric label, and a log field without
escaping or truncation. They guarantee **nothing whatsoever about which kinds exist**. They will
accept `revision.committed` and `banana.happened` with equal willingness, and that is the point:
the constraint is a shape contract with the consumers, not an enumeration of the producers.

**The specific thing the open verdict deliberately does not do.** An unroutable outbox event —
a kind no consumer recognizes — will not be refused at write time. It stays `processed_at IS NULL`
and accumulates in the `outbox_unprocessed` partial index. That is a **visible** failure (index
size, consumer lag, the projection watermark RM m6 already requires on every search response),
not a silent one, and it is the failure mode the design chose when it made the outbox the event
backbone rather than a closed enum. A CHECK would convert it into an aborted catalog-commit
transaction, which under invariant G ("storage leads; the catalog follows") means durable bytes
on disk with no revision row — strictly worse.

**What the `lineage_edges` CHECKs guarantee, and the residual gap.** They guarantee that each end
of every edge names a table the schema knows, so a typo can never orphan an edge by naming a
nonexistent node type. They do **not** guarantee that `upstream_id` exists in that table: the pair
`(kind, id)` is a polymorphic reference, and PostgreSQL has no declarative foreign key for one.
So `('raw_revision', <a random uuid>)` is still accepted after `0008`. This is a real residual
gap, named rather than papered over; what would close it is in Open questions.

**What they also do not constrain:** the `UNIQUE (upstream_kind, upstream_id, downstream_kind,
downstream_id)` from `0001` prevents a duplicate edge, but nothing prevents a self-edge
(`upstream = downstream`) or a cycle. Neither is raised by any finding and neither has a writer;
recorded as a deferral, not an oversight, and both belong with the P9 task that builds the
traversals.

**Three-valued logic is not a hole.** All five columns are `NOT NULL` in `0001`, so every row is
genuinely tested and none of these CHECKs needs the NULL-safe spelling `0004` required for
`snapshots.provenance`.

**Error behavior.** A violating INSERT or UPDATE raises SQLSTATE `23514` (`check_violation`),
surfaced by asyncpg as `asyncpg.exceptions.CheckViolationError` — the same class S2 recorded, and
already asserted at `tests/contract/test_auth_store.py:209` and `:248`.

**What `0008` must do about pre-existing data: nothing.** All four tables have zero PostgreSQL
writers (Current State §5) and are empty in every real database, so the constraints are added
**without `NOT VALID`** and validate every existing row at migration time — the same posture S1
took for the composite FK and S2 for the eight vocabulary CHECKs. Uniform across the migration.

**The `pkg/` `StrEnum` companions — none in `0008`.** S2's rule applies unchanged: an enum lands
with the writer that first needs it, in the same change as the writer, because a dead enum
mirroring a CHECK is the speculative abstraction the clean-sweep rule forbids. None of these four
tables has a writer. The homes are decided here so they are not re-litigated:

- **`JobKind`** → `src/huron/pkg/jobrunner/`, the package `design/roadmap.html` §1 already
  reserves for "digest-pinned container dispatch". It lands with the `JobDispatcher`
  implementation of the Protocol declared in `pkg/catalog/ports.py`.
- **The lineage node kinds** → a new `src/huron/pkg/catalog/lineage.py`, beside `ingest.py` and
  `layers.py`, which is where this codebase keeps domain vocabularies (and beside the
  `lifecycle.py` S2 introduces). Lineage spans all four layers, so it belongs to `catalog/`, not
  to any one layer's package.
- **`audit_events.kind` and `outbox_events.kind` get no enum, ever** — an open vocabulary has no
  enum by definition. Each producer names its own kind at the call site; the format CHECK is the
  whole of the shared contract.

### Negative-write tests

Four constraints, and the pairing rule from S1 and S2 holds: every rejected write needs a
permitted write beside it, or a constraint that rejects everything would pass. They belong in the
`tests/contract/test_catalog_store.py` module S1 introduces, on the
`tests/contract/test_rbac_store.py` `_assert_trigger_rejects_*` shape with
`asyncpg.exceptions.CheckViolationError` substituted for `RaiseError`.

The open columns need a **third** case that the closed columns do not, and it is the one that
proves the verdict rather than the constraint:

| Constraint | Must be refused | Must be accepted |
|---|---|---|
| `jobs_kind_vocabulary` | `kind = 'BANANA'`, `kind = ''` | each of the seven |
| `audit_events_kind_format` | `'BANANA'`, `''`, `'has space'`, a 64-character name | `'revision.committed'` — **and `'something.nobody.designed'`**, which must succeed |
| `outbox_events_kind_format` | the same four | the same two, including the undesigned kind |
| `lineage_edges_*_kind_vocabulary` | `upstream_kind = 'gold_snapshot'` (a plausible near-miss, not a nonsense string), and the same on `downstream_kind` | all four members on both ends, including a `gold_version → gold_version` supersession edge |

The "undesigned kind must be accepted" assertions are what make the open verdict a tested
decision instead of a comment. Without them, narrowing these columns to an `IN` list later would
be a green-test change.

The audit's fourth proof, `INSERT INTO jobs … state = 'WAT'`, is **not** in S3's scope and stays
passing — S2 records why (`jobs.state` has no settled vocabulary). The `jobs.kind` half of the
same row is what `0008` closes.

### Deletions

**None.** No constraint, index, trigger, table, column, `pkg/` symbol or test is made removable
by this task; all four constraints are additive over columns that had none, and nothing in
`src/huron/` reads or writes `jobs`, `audit_events`, `outbox_events` or `lineage_edges`.

`migrations/schema.sql` §5 (`lineage_edges`) and §6 (`jobs`, `audit_events`, `outbox_events`)
become stale on this change. **S8 owns what "regenerate" means**; recorded here only so the file
is not forgotten.

### Rejected alternatives

- **Close `audit_events.kind` / `outbox_events.kind` to today's documented events, and widen per
  phase** — every widening is a migration on the critical path of the feature that needs it, and
  the failure mode of being one kind short is an aborted mutation or an aborted catalog commit,
  not a missing log line.
- **A layer-ordering CHECK on `lineage_edges` (upstream must sit strictly below downstream)** —
  refuted by the design record itself: GOLD §5's recomputation cites "the version it supersedes",
  a `gold_version → gold_version` edge, so the ordering has to admit its own exception and stops
  constraining anything.
- **Per-kind nullable FK columns on `lineage_edges` (`revision_id`, `snapshot_id`,
  `product_version_id`) with an exactly-one-non-null CHECK, replacing the polymorphic pair** — the
  only shape that makes a lineage edge referentially sound, but it is four new columns and a
  rewrite of `UNIQUE (upstream_kind, upstream_id, downstream_kind, downstream_id)` on a table with
  no writer, which is a lineage-model redesign rather than a constraint fix (see Open questions).

### Open questions

1. **`jobs.kind` is closed against a list that is very likely one member short — deliberately, as
   a tripwire.** `design/architecture.html`'s component table lists a **Layer intake service** as
   a "Job runner (1–N)" — peer to the Bronze builder, Canonicalizer, Product runner and Validator,
   all four of which have a kind in CS §2's list — executing the manual bronze/silver intake that
   `design/api.html:144` exposes as `POST /datasets/{id}/layers/{layer}/intake-sessions`. CS §2's
   seven kinds contain no member for it. Two readings are available and only one is honest:
   inventing `layer_intake` bakes a string the design record never wrote, whereas adopting the
   seven means P6's first intake-job insert fails loudly with a `check_violation` naming the
   constraint, and is fixed by adding one literal in the migration that builds the writer — with
   `JobKind` landing in `pkg/jobrunner/` in the same change, per the house convention. **`0008`
   adopts the documented seven.** This is the same posture S2 took with `IN ('ACTIVE')` for
   `organizations` and `projects`: constrain to what the record actually says, and let the first
   write of an undocumented value be visible rather than silently correct. Flagged so the failure,
   when it comes, is recognized as designed rather than as a bug in `0008`.
2. **The polymorphic `(kind, id)` reference in `lineage_edges` is unenforceable as modelled, and
   closing it is a lineage-model decision for P9.** The CHECKs stop a typo in the kind; they
   cannot stop `('raw_revision', <a uuid that is not a revision>)`. The fix is the rejected
   alternative above — three nullable typed FK columns plus an exactly-one-non-null CHECK, which
   is how PostgreSQL expresses a polymorphic reference soundly — and it would also let CS §3's two
   recursive-CTE traversals join directly instead of casting through a text discriminator. It is
   not `0008` work: it changes the table's shape and its uniqueness key, it needs the traversal
   queries to exist before their access paths can be designed, and `snapshots` would first need
   the `project_id` question S1's open question 1 raises. **Deferred to the P9 design task that
   builds lineage writing and traversal, with the residual gap recorded above.**
3. **`audit_events.subject_kind` is an entity-kind column in the same family, and `0008`
   deliberately does not touch it.** F2 does not list it, so it is outside both S2's and S3's
   scope, but it is the same modelling question one column over: it names what the audited
   subject *is*, drawing on a vocabulary at least as wide as `lineage_edges`' four typed nodes
   plus every RBAC and hierarchy resource. It cannot simply reuse the lineage vocabulary — an
   audit subject can be a project, a role binding or an API key, none of which is a lineage node —
   and no design document enumerates it. Settled by RM m3, which builds "an audit row for every
   mutation and every denied operation" and therefore has to decide what a subject can be. Named
   here so a later reader does not conclude it was missed. (CS §2 also gives `jobs` a
   `subject_kind` that `0001` does not have; whether `jobs` gains one is the same question and the
   same phase's answer.)

---

## S4 — Foreign-key access paths and referential actions (design)

### Target design

One sweep over every foreign key in the schema, asked the two questions F3/F7 pose. The count
is **23 before `0008` and 22 after** — S1 *replaces* `releases_revision_id_fkey` with
`releases_revision_dataset_fk` rather than adding a twenty-fourth, and this task drops one
strictly-subsumed constraint (below). Fourteen of the twenty-three already have a supporting
index by leading-column prefix and need nothing.

Legend for the index column: **existing** = already the leading-column prefix of an index or
constraint created by `0001`–`0005`; **S1** = the index S1's section already specifies;
**new** = created by `0008` here; **none** = deliberately not indexed, reason in the row.

| # | Referencing column(s) → parent | Supporting index | `ON DELETE` / `ON UPDATE` | Reason |
|---|---|---|---|---|
| 1 | `projects (organization_id)` → `organizations (id)` | existing `projects_organization_id_slug_key` | `NO ACTION` / `NO ACTION` | Catalog rows are withdrawn through `lifecycle_state`, never deleted; the parent key is an immutable client-generated UUID. |
| 2 | `datasets (project_id)` → `projects (id)` | existing `datasets_project_id_slug_key` | `NO ACTION` / `NO ACTION` | As #1. |
| 3 | `dataset_revisions (dataset_id)` → `datasets (id)` | existing `dataset_revisions_dataset_id_revision_number_key` | `NO ACTION` / `NO ACTION` | Revisions are the immutable history; cascading a dataset delete into them would erase the record a purge is supposed to leave behind (`purge_records`). |
| 4 | `releases (dataset_id)` → `datasets (id)` | existing `releases_dataset_id_tag_key` | `NO ACTION` / `NO ACTION` | As #1; a release is a citation anchor (invariant M). |
| 5 | `releases (revision_id, dataset_id)` → `dataset_revisions (id, dataset_id)` | **S1** `releases_revision (revision_id, dataset_id)` | `NO ACTION` / `NO ACTION` | Stated inline by S1. This sweep reaches the same verdict for catalog FKs, so S1's row stands unchanged and **no second index on `releases (revision_id)` is added**. |
| 6 | `revision_amendments (revision_id)` → `dataset_revisions (id)` | existing `revision_amendments_revision_id_sequence_key` | `NO ACTION` / `NO ACTION` | Append-only amendments; as #3. |
| 7 | `ingest_sessions (dataset_id)` → `datasets (id)` | existing `ingest_sessions_dataset_id_revision_number_key` (also partial `one_open_ingest_per_dataset`) | `NO ACTION` / `NO ACTION` | As #1. |
| 8 | `ingest_files (ingest_id)` → `ingest_sessions (id)` | existing `ingest_files_ingest_id_path_key` | **`CASCADE`** / `NO ACTION` | Already stated by `0001` and correct: an upload plan row is *part of* its session, has no identity without it, and an abandoned session's plan is garbage. The one true ownership relation in the schema. |
| 9 | `products (project_id)` → `projects (id)` | existing `products_project_id_slug_key` | `NO ACTION` / `NO ACTION` | As #1. |
| 10 | `products (dataset_id)` → `datasets (id)` — `products_dataset_id_fkey` | — | — | **Dropped.** Strictly subsumed by #11; see Deletions. |
| 11 | `products (dataset_id, project_id)` → `datasets (id, project_id)` | **new** `products_dataset_project (dataset_id, project_id)` | `NO ACTION` / `NO ACTION` | One index discharges both F3 rows for this table: `dataset_id` leads it, so the single-column access path is covered by prefix. |
| 12 | `product_versions (product_id)` → `products (id)` | existing `product_versions_product_id_semver_key` | `NO ACTION` / `NO ACTION` | Versions carry `withdrawn_at`; they are withdrawn, not deleted. |
| 13 | `product_versions (snapshot_id)` → `snapshots (id)` | **new** `product_versions_snapshot (snapshot_id)` | `NO ACTION` / `NO ACTION` | Nullable until published; `SET NULL` on a snapshot delete would silently detach a published version from its bytes. Refusing is right. |
| 14 | `purge_records (revision_id)` → `dataset_revisions (id)` | **new** `purge_records_revision (revision_id)` | `NO ACTION` / `NO ACTION` | A purge record must outlive what it purges — `CASCADE` here would delete the audit of the deletion. |
| 15 | `snapshots (dataset_id)` → `datasets (id)` | **new** `snapshots_dataset (dataset_id)` | `NO ACTION` / `NO ACTION` | Nullable for gold (`snapshots_dataset_required_below_gold`); as #1 otherwise. |
| 16 | `api_keys (project_id)` → `projects (id)` | **new** `api_keys_project (project_id)` | `NO ACTION` / `NO ACTION` | Nullable for an unscoped key. `SET NULL` would silently *widen* a key's scope from one project to none on a project delete — the worst available failure mode for a credential. |
| 17 | `service_accounts (principal_id)` → `principals (id)` | existing `service_accounts_pkey` | `NO ACTION` / `NO ACTION` | Principals are disabled (`disabled_at`), never deleted; `postgres_auth.disable()` is an UPDATE. |
| 18 | `service_accounts (organization_id)` → `organizations (id)` | existing `service_accounts_organization_id_name_key` | `NO ACTION` / `NO ACTION` | As #1; this index also serves `list_service_accounts`' filter *and* its `ORDER BY sa.name`. |
| 19 | `local_credentials (principal_id)` → `principals (id)` | existing `local_credentials_pkey` | `NO ACTION` / `NO ACTION` | As #17. |
| 20 | `policy_attachments (policy_id)` → `policies (id)` | existing `policy_attachments_pkey` | `NO ACTION` / `NO ACTION` | Detaching is an explicit act; a policy with live attachments must not vanish. |
| 21 | `role_capabilities (role_code)` → `roles (code)` | existing `role_capabilities_pkey` | **`CASCADE`** / `NO ACTION` | Kept, and now stated on both halves. A `role_capabilities` row is the *contents* of a role bundle and has no meaning without it — ownership, exactly like #8. |
| 22 | `role_capabilities (capability_code)` → `capabilities (code)` | **none** — see below | `NO ACTION` / `NO ACTION` | The asymmetry is deliberate and is made explicit here. A junction row *cites* the capability vocabulary rather than being owned by it: `CASCADE` would let one `DELETE FROM capabilities` silently narrow every role that grants it, an authorization change nobody wrote down. |
| 23 | `role_bindings (role_code)` → `roles (code)` — `role_bindings_role_fk` | **new** `role_bindings_role (role_code)` | `NO ACTION` / `NO ACTION` | Same rule as #22 one level out: deleting a role must not silently revoke live grants. `0006`'s own docstring describes the correct procedure — delete the bindings first, deliberately, and re-grant. |

Plus F4's access-path index, which is not a foreign key:

| — | `role_bindings (scope_type, scope_id)` | **new** `role_bindings_scope` | n/a | The `bindings_at` listing constrains `scope_type`, which led no index. Mirrors `policy_attachments_scope` on the sibling table for the identical access path. |

**Seven new indexes, six of them for foreign keys.** Of F3's nine columns, three are discharged
without an index of their own: `releases.revision_id` (S1's `releases_revision` covers it by
prefix), `products.dataset_id` (covered by the leading column of `products_dataset_project`, and
its own FK is dropped), and `role_capabilities.capability_code` (declined, below).

**Why `role_capabilities.capability_code` gets no index.** The table is a seed junction bounded
by |roles| × |capabilities| — five by seventeen today, about fifty rows, one heap page, written
only by migrations and read by exactly one query (`bindings_for`'s join, which uses the
`role_code` leading column of the primary key). Both costs the skill's rule exists to avoid are
absent at that cardinality: no query filters on `capability_code`, and the parent-delete scan the
rule warns about reads a single page. The planner would never choose the index over a sequential
scan, so it would exist only to be maintained. The bound is structural — the capability
vocabulary is enumerated in `src/huron/pkg/rbac/roles.py` and diffed by a contract test — not
incidental, so this does not become wrong as the system grows. Recorded here so a later sweep
does not re-flag it as an oversight.

**The `ON UPDATE` verdict: `NO ACTION` everywhere, and it is a real choice in exactly three
places.** For the twenty UUID-keyed foreign keys `ON UPDATE` is unreachable — ids are
client-generated, opaque and baked into storage paths, so no parent key is ever updated. For the
three that reference the natural text keys `roles.code` and `capabilities.code` (#21, #22, #23)
it is live, and `NO ACTION` is deliberate: the codes *are* the vocabulary, mirrored by
`huron.pkg.rbac.roles.ROLES`. `0004`, `0006` and `0007` change that vocabulary by
`DELETE`-then-`INSERT`, never by `UPDATE roles SET code = …` — the only `UPDATE roles` statements
in the migration stack touch `description` and `allowed_principal_kinds`. `ON UPDATE CASCADE`
would make a stray rename silently repoint every `role_capabilities` and `role_bindings` row,
changing who can do what with no seed change and no contract-test diff. `NO ACTION` makes that
attempt fail loudly, which is the behavior the seed convention already assumes.

### The DDL

Statements for the single module-level `DDL` string of `0008`, in this order. The
`ALTER TABLE`s carry each constraint's exact existing name. Twenty-one of the twenty-three
foreign keys carry PostgreSQL's generated name because the migrations never spelled one; only
`products_dataset_project_fk` (`0003`) and `role_bindings_role_fk` (`0002`) were named by hand,
so the default names below must be written exactly, the same hazard S1 records for
`releases_revision_id_fkey`.

```sql
-- PostgreSQL does not index a referencing column for you, so an unindexed one
-- turns every parent delete into a sequential scan of the child table.
CREATE INDEX products_dataset_project ON products (dataset_id, project_id);
CREATE INDEX product_versions_snapshot ON product_versions (snapshot_id);
CREATE INDEX purge_records_revision ON purge_records (revision_id);
CREATE INDEX snapshots_dataset ON snapshots (dataset_id);
CREATE INDEX api_keys_project ON api_keys (project_id);
CREATE INDEX role_bindings_role ON role_bindings (role_code);

-- Bindings are listed by scope, and `scope_type` led no index, so the listing
-- read every binding in the table. `policy_attachments_scope` is the same
-- access path on the sibling table.
CREATE INDEX role_bindings_scope ON role_bindings (scope_type, scope_id);

-- Subsumed by role_bindings_no_duplicates, which leads with the same column
-- and cannot be dropped: it backs the uniqueness constraint.
DROP INDEX role_bindings_principal_scope;

-- The single-column reference 0003 created in the same ADD COLUMN statement as
-- the composite one. A row satisfying (dataset_id, project_id) against
-- datasets (id, project_id) necessarily satisfies (dataset_id) against
-- datasets (id).
ALTER TABLE products DROP CONSTRAINT products_dataset_id_fkey;

-- The role catalog is the one place where a parent key is natural text and
-- parent rows are really deleted (0004, 0006 and 0007 each retire a role), so
-- the referential action is a live choice rather than an unreachable default.
-- Deleting a role must not silently revoke a grant, and deleting a capability
-- must not silently narrow a role; a role's capability rows, by contrast, are
-- the role's own contents and go with it.
ALTER TABLE role_bindings
    DROP CONSTRAINT role_bindings_role_fk,
    ADD CONSTRAINT role_bindings_role_fk
        FOREIGN KEY (role_code) REFERENCES roles (code)
        ON DELETE NO ACTION ON UPDATE NO ACTION;

ALTER TABLE role_capabilities
    DROP CONSTRAINT role_capabilities_role_code_fkey,
    DROP CONSTRAINT role_capabilities_capability_code_fkey,
    ADD CONSTRAINT role_capabilities_role_code_fkey
        FOREIGN KEY (role_code) REFERENCES roles (code)
        ON DELETE CASCADE ON UPDATE NO ACTION,
    ADD CONSTRAINT role_capabilities_capability_code_fkey
        FOREIGN KEY (capability_code) REFERENCES capabilities (code)
        ON DELETE NO ACTION ON UPDATE NO ACTION;
```

and the matching `downgrade()`, which restores `0001`/`0002`/`0003` exactly:

```sql
ALTER TABLE role_capabilities
    DROP CONSTRAINT IF EXISTS role_capabilities_capability_code_fkey,
    DROP CONSTRAINT IF EXISTS role_capabilities_role_code_fkey,
    ADD CONSTRAINT role_capabilities_role_code_fkey
        FOREIGN KEY (role_code) REFERENCES roles (code) ON DELETE CASCADE,
    ADD CONSTRAINT role_capabilities_capability_code_fkey
        FOREIGN KEY (capability_code) REFERENCES capabilities (code);
ALTER TABLE role_bindings
    DROP CONSTRAINT IF EXISTS role_bindings_role_fk,
    ADD CONSTRAINT role_bindings_role_fk FOREIGN KEY (role_code) REFERENCES roles (code);
ALTER TABLE products
    ADD CONSTRAINT products_dataset_id_fkey FOREIGN KEY (dataset_id) REFERENCES datasets (id);
CREATE INDEX role_bindings_principal_scope ON role_bindings (principal, scope_type, scope_id);
DROP INDEX IF EXISTS role_bindings_scope;
DROP INDEX IF EXISTS role_bindings_role;
DROP INDEX IF EXISTS api_keys_project;
DROP INDEX IF EXISTS snapshots_dataset;
DROP INDEX IF EXISTS purge_records_revision;
DROP INDEX IF EXISTS product_versions_snapshot;
DROP INDEX IF EXISTS products_dataset_project;
```

### Explicit contracts

**What the index set guarantees.** After `0008`, every foreign key in the schema has its
referencing columns reachable by a btree whose leading column is the first referencing column,
with one named exception (`role_capabilities.capability_code`, reasoned above). Equivalently:
**no parent delete and no parent-key update anywhere in the schema falls back to a sequential
scan of a child table that grows with usage.** The two remaining sequential scans are both on
tables bounded to a single heap page — `role_capabilities` on a capability delete, and `roles`
and `capabilities` themselves as parents.

**The four role-binding indexes, and which query each serves.** This is the F4 accounting the
task asks for.

| Index | Serves |
|---|---|
| `role_bindings_pkey (id)` | `revoke_role` and `get_role_binding`, both `WHERE id = $1`. |
| `role_bindings_no_duplicates (principal, role_code, scope_type, scope_id)` `UNIQUE NULLS NOT DISTINCT` | The uniqueness rule `grant_role` relies on — it catches `asyncpg.UniqueViolationError` and raises `DomainError` — **and** `bindings_for`'s `rb.principal = ANY($1::text[])`, on its leading column. |
| `role_bindings_principal_scope (principal, scope_type, scope_id)` | **Nothing.** Dropped — see below. |
| `role_bindings_scope (scope_type, scope_id)` *(new)* | `bindings_at`, the scope-listing query F4 names. |
| `role_bindings_role (role_code)` *(new)* | The `role_bindings_role_fk` parent-delete check, and the `DELETE FROM role_bindings WHERE role_code = …` that `0004`, `0006` and `0007` each run when retiring a role — a query site in the migrations themselves, not a hypothetical. |

**Why `role_bindings_principal_scope` becomes redundant.** It exists to serve a lookup by
principal narrowed by scope, and no such query exists: `bindings_for` constrains `principal`
alone and deliberately leaves scope inheritance to `decide()` in Python (its own docstring says
so), while `bindings_at` constrains scope and not principal. For the one query that does use a
`principal`-leading index, `role_bindings_no_duplicates` has the same leading column, the same
selectivity, and the same need for a heap fetch to reach `id`, `effect` and `expires_at` —
neither index covers the projection. `role_bindings_principal_scope` is therefore a second copy
of a prefix the uniqueness constraint already maintains. The unique index cannot be dropped (it
backs a constraint the application depends on); the plain one can, and is. If a future query
filters `(principal, scope_type, scope_id)` together — a per-principal scope walk pushed into
SQL — it comes back, and that is the trigger to reinstate it.

**What `role_bindings_scope` does *not* fix, stated plainly.** `bindings_at` is spelled
`WHERE scope_type = $1 AND scope_id IS NOT DISTINCT FROM $2`. `IS NOT DISTINCT FROM` is not a
btree-searchable predicate — PostgreSQL builds it as a `DistinctExpr`, which index matching does
not consider — which is exactly what F4's proven `EXPLAIN` shows when it reports `scope_id`
"demoted to a filter" while `scope_type` survives as an `Index Cond`. So the new index delivers
what F4 asks for and no more: `scope_type` becomes a leading-column index condition instead of a
whole-table read, and `scope_id` stays a filter over the rows at that scope type. That is a real
win — `SYSTEM`, `ORGANIZATION`, `PROJECT` and `DATASET` partition the table four ways and the
listing pages are per-scope — but it is not the point lookup the index shape suggests. Closing
the second half needs the *query* respelled, which is application code and not this task's
(see Open questions).

**Locking behavior the referential actions imply.**

- `ON DELETE NO ACTION` (twenty of twenty-two FKs after `0008`): deleting a parent row runs a
  `SELECT … FOR KEY SHARE` against the child on the referencing columns. With the index it is a
  probe; without one it reads the whole child table. Nothing cascades, so a delete of a parent
  with children raises SQLSTATE `23503` and the transaction is the caller's to fix — the
  behavior the catalog wants, since catalog rows are withdrawn through `lifecycle_state` rather
  than deleted.
- `ON DELETE CASCADE` (`ingest_files.ingest_id`, `role_capabilities.role_code`): deleting the
  parent takes a row lock on and deletes every matching child in the same transaction. Both have
  their supporting index already, so neither cascade scans. Note that no migration actually
  relies on the `role_capabilities` cascade — `0004`, `0006` and `0007` all delete the junction
  rows explicitly before the role. That is not an argument for removing the cascade: it is the
  guard rail for a `DELETE FROM roles` issued outside the migration stack, where the alternative
  is a role row that fails to delete for a reason the operator has to go and find.
- `ON UPDATE NO ACTION` everywhere: no parent key is updated by any code path that exists, so
  this action never fires. It is written on the role-catalog FKs because there it *could*.

**`CREATE INDEX CONCURRENTLY` is neither usable nor needed here, and `0008` must not reach for
it.** It cannot run inside a transaction block; `migrations/env.py` runs the whole revision in
one, and `execute_sql` splits statements at top-level `;` without committing between them. It is
also unnecessary: `products`, `product_versions`, `snapshots` and `purge_records` have no
PostgreSQL writer anywhere in `src/huron/` (Current State §5) and are empty in every real
database, and `role_bindings` and `api_keys` hold tens of rows. A plain `CREATE INDEX` takes a
`SHARE` lock — readers proceed, writers wait — for a build measured in microseconds at that size.
The `ALTER TABLE … DROP/ADD CONSTRAINT` statements take `ACCESS EXCLUSIVE` on the child and
`SHARE ROW EXCLUSIVE` on the parent while the re-added constraint validates, on the same
near-empty tables. Restructuring `0008` to permit `CONCURRENTLY` — autocommit blocks, a split
revision — would buy nothing and break the house DDL convention.

**No application change is required by this task.** `bindings_at`, `bindings_for` and
`ApiKeyStore.add` keep their current SQL; the dropped `products_dataset_id_fkey` and
`role_bindings_principal_scope` are invisible to every caller, and no code reads a constraint
name. `ApiKeyStore.add` catches `asyncpg.ForeignKeyViolationError` by class, not by name, so
recreating constraints does not disturb it.

**Negative-write coverage.** The referential actions are provable with the existing
`tests/contract/test_rbac_store.py` shape and belong there, since they concern the role catalog:
deleting a `roles` row that still has a binding must raise
`asyncpg.exceptions.ForeignKeyViolationError`; deleting a `capabilities` row still named by a
`role_capabilities` row must do the same; and deleting a `roles` row whose bindings were removed
first must succeed **and** take its `role_capabilities` rows with it, which is the positive half
that proves the cascade is real rather than the delete merely failing. Index presence is not a
behavioral rule and needs no test.

### Deletions

- **`role_bindings_principal_scope`** — the index `0001` created. Strictly subsumed by
  `role_bindings_no_duplicates` for every query that exists; reasoned above.
- **`products_dataset_id_fkey`** — the implicit single-column foreign key `0003` created by the
  `ADD COLUMN dataset_id uuid REFERENCES datasets(id)` clause, alongside
  `products_dataset_project_fk` in the same statement. It is strictly subsumed: when
  `dataset_id` is NULL both constraints are skipped under `MATCH SIMPLE`, and when it is not
  NULL, `project_id` is `NOT NULL`, so the composite check runs and requires
  `(dataset_id, project_id)` to exist in `datasets (id, project_id)` — which implies
  `dataset_id` exists in `datasets (id)`. Keeping both means two constraint entries and two
  index probes per product insert for one invariant. This is the same removal S1 makes on
  `releases`, for the same reason and by the same argument; S1's section states the precedent
  and this sweep is where the sibling case surfaces.
- **No index becomes redundant by the seven additions** — each new index is the only one leading
  with its column, and none duplicates a prefix of an existing constraint index.
- No application code, no `pkg/` symbol and no test is made obsolete.
- `migrations/schema.sql` §1 (`products`), §2 (`role_bindings`, `role_capabilities`, `api_keys`)
  and §5 (`snapshots`, `product_versions`, `purge_records`) become stale on this change — the
  index list and the FK annotations both. **S8 owns what "regenerate" means**; recorded here only
  so the file is not forgotten.

### Rejected alternatives

- **Drop and re-add all twenty-one inherited foreign keys with explicit `ON DELETE NO ACTION
  ON UPDATE NO ACTION`** — the maximal reading of F7. It changes no behavior (`NO ACTION` is
  already what every one of them means), costs twenty-one statements that must respell
  PostgreSQL's generated constraint names exactly, and buys a documentation property that this
  table and the regenerated `migrations/schema.sql` deliver instead; `0008` writes the action out
  only where the parent key is natural text and parent deletes demonstrably happen.
- **`ON DELETE CASCADE` on `role_capabilities.capability_code`, for symmetry with `role_code`** —
  the asymmetry is the design, not an omission: a role owns its capability rows, a capability is
  merely cited by them, and cascading would let one delete silently narrow every role that grants
  the capability without a seed change or a contract-test diff.
- **Partial indexes (`WHERE … IS NOT NULL`) on the four nullable referencing columns** —
  `products.dataset_id`, `snapshots.dataset_id`, `api_keys.project_id`,
  `product_versions.snapshot_id`. The foreign-key probe never searches for NULL, so the partial
  form is sufficient and smaller; on tables that are empty or hold tens of rows the saving is
  nil and the extra predicate is a speculative optimization the schema does not need.

### Open questions

1. **Should `bindings_at` be respelled so `scope_id` becomes an index condition rather than a
   filter?** Flagged, and deliberately not taken here — S4 is a DDL task and this is a change to
   `src/huron/service/api/postgres_rbac.py:225-230`. The schema already guarantees the fact that
   makes it safe: `role_bindings`' own CHECK says `scope_id IS NULL` if and only if
   `scope_type = 'SYSTEM'`, so `IS NOT DISTINCT FROM` is defending against a state the table
   cannot hold. Spelled as two indexable predicates — `scope_type = $1 AND scope_id = $2` for the
   three scoped cases, and `scope_type = 'SYSTEM'` alone for the fourth, where `scope_id` is
   necessarily NULL and adds nothing — `role_bindings_scope` becomes a genuine point lookup
   instead of a partition scan. Left open because it is a behavior-preserving refactor of
   application code whose value is unmeasurable until `role_bindings` holds more than tens of
   rows, and because whoever takes it should decide whether the branch lives in `postgres_rbac.py`
   or in the `pkg/metastore/` package that Roadmap Drift 2 says does not exist yet. **`0008` adds
   the index regardless — it is the correct index for the access path either way, and it fixes
   the leading-column half of F4 on its own.**

---

## S5 — jsonb object-shape constraints (design)

### The enumeration, and F5's count

Fifteen `jsonb` columns, read off the migration DDL rather than taken from the audit's prose.
Fourteen are objects, one is an array, none is anything else.

F5 says "the four with an `'{}'::jsonb` default that plainly intend an object". There are
**three** — `projects.raw_retention_policy`, `role_bindings.conditions`, `jobs.payload`. The
fourth defaulted jsonb column is `ingest_files.completed_parts DEFAULT '[]'::jsonb`, whose
default is an *array*, and it is exactly the column that makes a blanket
`CHECK (jsonb_typeof(col) = 'object')` sweep wrong. The miscount is one entry, and it is the one
entry that matters; the column list itself is as F5 gives it.

### Target design

| Column | Added by | Nullable | Default | Top-level type | Constraint |
|---|---|---|---|---|---|
| `projects.raw_retention_policy` | `0001` | no | `'{}'` | object | `projects_raw_retention_policy_is_an_object` |
| `revision_amendments.document` | `0001` | no | — | object | `revision_amendments_document_is_an_object` |
| `ingest_files.completed_parts` | `0001` | no | `'[]'` | **array** | `ingest_files_completed_parts_is_an_array` |
| `role_bindings.conditions` | `0001` | no | `'{}'` | object | `role_bindings_conditions_is_an_object` |
| `policies.spec` | `0002` | no | — | object | `policies_spec_is_an_object` |
| `audit_events.payload` | `0001` | no | — | object | `audit_events_payload_is_an_object` |
| `outbox_events.payload` | `0001` | no | — | object | `outbox_events_payload_is_an_object` |
| `idempotency_records.response` | `0001` | no | — | object | `idempotency_records_response_is_an_object` |
| `science_profiles.document` | `0001` | no | — | object | `science_profiles_document_is_an_object` |
| `jobs.payload` | `0001` | no | `'{}'` | object | `jobs_payload_is_an_object` |
| `snapshots.provenance` | `0001` | no | — | object | `snapshots_provenance_is_an_object` |
| `snapshots.validation_evidence` | `0001` | **yes** | — | object or SQL NULL | `snapshots_validation_evidence_is_an_object` |
| `product_versions.derivation_record` | `0001` | no | — | object | `product_versions_derivation_record_is_an_object` |
| `lineage_edges.region` | `0001` | **yes** | — | object or SQL NULL | `lineage_edges_region_is_an_object` |
| `reconciliation_findings.detail` | `0001` | no | — | object | `reconciliation_findings_detail_is_an_object` |

**Why `completed_parts` is an array and nothing else is.** It is the resume ledger for a
multipart upload — `design/layer-raw.html` §4 and `design/python-client.html` both describe
"interrupted transfers resume via `completed_parts`", and `design/catalog-search.html` §2 lists
it beside `expected_sha256` on the per-file upload plan. A resume ledger is an ordered list of
part numbers, and the `'[]'` default is the empty ledger of a file no part of which has landed.
Nothing else in the fifteen is a sequence: every other column is a named record, and each of the
four that has a `'{}'`-shaped sibling in Python (`policies.spec` is `dict[str, object]`,
`snapshots.provenance` is `urn:huron:snapshot-provenance:1`, `science_profiles.document` is
`urn:huron:science-profile:1`, `revision_amendments.document` is a metadata patch keyed by
`changed_keys`) is an object at the top level by the schema it is validated against.

**The two nullable columns, and what NULL means in each.**

- `snapshots.validation_evidence` — SQL NULL is "this snapshot has not been validated", which is
  a real and distinct state from "validated, and the evidence record is empty". `0001` left it
  nullable deliberately: `design/catalog-search.html` §2 lists it beside `published_at`, also
  nullable, on the candidate→published path. Keep it nullable; constrain the non-NULL case.
- `lineage_edges.region` — SQL NULL is "the whole upstream contributes", which is the common
  edge; a value narrows the edge to a part of it (`design/catalog-search.html` §2's own example:
  *(silver_snapshot S119) ─derives_from→ (bronze_snapshot B187) region run-0042*). A region that
  names a part needs named selectors, so it is an object when present. Keep it nullable;
  constrain the non-NULL case.

Neither becomes `NOT NULL DEFAULT '{}'`. Collapsing "absent" onto "empty object" would destroy
the distinction the nullability exists to carry, and it is the distinction, not the storage, that
a reader of `lineage_edges` needs.

**`policies.spec` — shape varies by `policy_type`, and that is why the constraint stops at the
type.** `policies` is one of the few tables with a live PostgreSQL writer:
`postgres_rbac.py:329` inserts `$4::jsonb` from `json.dumps(record.spec)`, and the request model
`CreatePolicy.spec` is typed `dict[str, object]`, so the API edge already refuses a non-object.
The interior is genuinely open — `policy_type` is a `^[a-z][a-z0-9_]{1,62}$` regex, not a closed
vocabulary, so there is no fixed set of specs to switch on and no `documents/*.json` for any of
them. A database rule that tried to follow `policy_type` would have to be rewritten for every
policy type ever added. The type check is the whole of what the database can honestly assert
here, and it is not nothing: it is the assertion the API's Pydantic model makes, restated where a
writer that is not the API cannot skip it.

**`revision_amendments.document` — validated in Python, typed in the database.** An amendment is
a partial metadata patch: `changed_keys text[]` names the keys it touches, `reclassified boolean`
flags the permissioned case, and `design/api.html` describes `POST /revisions/{id}:amend` as
"project_admin; field allow-list; reclassification separately permissioned", with
`design/catalog-search.html` §1 serving "effective metadata of a revision (base + amendments)"
by folding them. The allow-list, the per-key value types and the fold are `huron.schema` work
against `documents/metadata-v1.json`; there is no `documents/amendment-*.json` today and this
task does not invent one. The database asserts that the patch is a keyed record — the one
property the fold cannot proceed without and the one a bad writer must not be able to bypass.

**`snapshots.provenance` — what it still needs, which is one line and no disturbance.** `0004`
already added `snapshots_provenance_states_an_origin` and
`snapshots_provenance_gold_is_derivation`, both NULL-safe on purpose. **`0008` does not touch
either.** It adds `snapshots_provenance_is_an_object` beside them. The origin CHECK does already
exclude every non-object transitively — on PostgreSQL 16 `'"x"'::jsonb ->> 'kind'` and
`'[1,2]'::jsonb ->> 'kind'` both return SQL NULL, which the constraint's
`provenance->>'kind' IS NOT NULL` clause then rejects — so the new constraint refuses no row the
old ones accept. It is added anyway, for three reasons: the shape guarantee should not be an
inference about `->>`'s behaviour on non-object jsonb, it should not be a side effect of a
constraint whose subject is invariant N and which could be respelled or widened later, and a
floor that holds for thirteen columns by CHECK and for the fourteenth by implication is the
per-column improvisation this task exists to replace. This is not the redundancy S1 and S4 delete:
those were a duplicate FK and a duplicate index, each costing an index probe or an index write on
every row; a second CHECK on a jsonb datum already in memory costs a type-tag comparison and no
I/O.

#### The DDL

Fifteen constraints, one statement per table, all inside `0008`'s single module-level `DDL`
string. Order within the string is irrelevant except for `audit_events` (see the S6 dependency
below).

```sql
-- Every jsonb column states its own top-level type. Thirteen of the fifteen were writable
-- with a bare string, number or boolean: `UPDATE projects SET raw_retention_policy =
-- '"just a string"'::jsonb` succeeded, and jsonb_typeof then reported `string`. The two
-- nullable columns spell the NULL case out rather than leaning on a CHECK's three-valued
-- logic, so that the acceptance of SQL NULL is visibly deliberate. `completed_parts` is the
-- one array: it is the resume ledger for a multipart upload, and its default is '[]'.
ALTER TABLE projects
    ADD CONSTRAINT projects_raw_retention_policy_is_an_object
        CHECK (jsonb_typeof(raw_retention_policy) = 'object');
ALTER TABLE revision_amendments
    ADD CONSTRAINT revision_amendments_document_is_an_object
        CHECK (jsonb_typeof(document) = 'object');
ALTER TABLE ingest_files
    ADD CONSTRAINT ingest_files_completed_parts_is_an_array
        CHECK (jsonb_typeof(completed_parts) = 'array');
ALTER TABLE role_bindings
    ADD CONSTRAINT role_bindings_conditions_is_an_object
        CHECK (jsonb_typeof(conditions) = 'object');
ALTER TABLE policies
    ADD CONSTRAINT policies_spec_is_an_object
        CHECK (jsonb_typeof(spec) = 'object');
ALTER TABLE outbox_events
    ADD CONSTRAINT outbox_events_payload_is_an_object
        CHECK (jsonb_typeof(payload) = 'object');
ALTER TABLE idempotency_records
    ADD CONSTRAINT idempotency_records_response_is_an_object
        CHECK (jsonb_typeof(response) = 'object');
ALTER TABLE science_profiles
    ADD CONSTRAINT science_profiles_document_is_an_object
        CHECK (jsonb_typeof(document) = 'object');
ALTER TABLE jobs
    ADD CONSTRAINT jobs_payload_is_an_object
        CHECK (jsonb_typeof(payload) = 'object');
ALTER TABLE snapshots
    ADD CONSTRAINT snapshots_provenance_is_an_object
        CHECK (jsonb_typeof(provenance) = 'object'),
    ADD CONSTRAINT snapshots_validation_evidence_is_an_object
        CHECK (validation_evidence IS NULL
               OR jsonb_typeof(validation_evidence) = 'object');
ALTER TABLE product_versions
    ADD CONSTRAINT product_versions_derivation_record_is_an_object
        CHECK (jsonb_typeof(derivation_record) = 'object');
ALTER TABLE lineage_edges
    ADD CONSTRAINT lineage_edges_region_is_an_object
        CHECK (region IS NULL OR jsonb_typeof(region) = 'object');
ALTER TABLE reconciliation_findings
    ADD CONSTRAINT reconciliation_findings_detail_is_an_object
        CHECK (jsonb_typeof(detail) = 'object');

-- Recurses to every existing partition and is inherited by every partition created later.
ALTER TABLE audit_events
    ADD CONSTRAINT audit_events_payload_is_an_object
        CHECK (jsonb_typeof(payload) = 'object');
```

and the matching `downgrade()`:

```sql
ALTER TABLE audit_events DROP CONSTRAINT IF EXISTS audit_events_payload_is_an_object;
ALTER TABLE reconciliation_findings DROP CONSTRAINT IF EXISTS reconciliation_findings_detail_is_an_object;
ALTER TABLE lineage_edges DROP CONSTRAINT IF EXISTS lineage_edges_region_is_an_object;
ALTER TABLE product_versions DROP CONSTRAINT IF EXISTS product_versions_derivation_record_is_an_object;
ALTER TABLE snapshots
    DROP CONSTRAINT IF EXISTS snapshots_validation_evidence_is_an_object,
    DROP CONSTRAINT IF EXISTS snapshots_provenance_is_an_object;
ALTER TABLE jobs DROP CONSTRAINT IF EXISTS jobs_payload_is_an_object;
ALTER TABLE science_profiles DROP CONSTRAINT IF EXISTS science_profiles_document_is_an_object;
ALTER TABLE idempotency_records DROP CONSTRAINT IF EXISTS idempotency_records_response_is_an_object;
ALTER TABLE outbox_events DROP CONSTRAINT IF EXISTS outbox_events_payload_is_an_object;
ALTER TABLE policies DROP CONSTRAINT IF EXISTS policies_spec_is_an_object;
ALTER TABLE role_bindings DROP CONSTRAINT IF EXISTS role_bindings_conditions_is_an_object;
ALTER TABLE ingest_files DROP CONSTRAINT IF EXISTS ingest_files_completed_parts_is_an_array;
ALTER TABLE revision_amendments DROP CONSTRAINT IF EXISTS revision_amendments_document_is_an_object;
ALTER TABLE projects DROP CONSTRAINT IF EXISTS projects_raw_retention_policy_is_an_object;
```

`snapshots_provenance_gold_is_derivation` and `snapshots_provenance_states_an_origin` appear in
neither list. They belong to `0004` and `0008` leaves them exactly as they are.

The two nullable constraints are spelled `col IS NULL OR jsonb_typeof(col) = 'object'` even
though `jsonb_typeof(NULL)` is SQL NULL and a NULL CHECK result already passes. The bare form
would be correct today by accident of three-valued logic; the explicit form says that accepting
SQL NULL is the design, and it survives unchanged in meaning if either column is ever made
`NOT NULL`. `0004`'s docstring is the reason the accident is not left to stand: the same
three-valued logic, pointed the other way, is what silently accepted `provenance = '{}'`.

### Explicit contracts

#### The rule: what the database keeps, and what `huron.schema` keeps

`0004`'s docstring states the division and this task adopts it verbatim as the rule for all
fifteen columns: *"the full shape is validated in Python against `huron.schema`; the database
keeps the part that a bad writer must not be able to bypass."* Spelled out so it decides cases
rather than describing one:

**A jsonb property belongs in a database CHECK when all three hold.**

1. **Row-local and cheap** — decidable from the one datum, with no lookup and no function that
   would have to be kept in step with a file elsewhere in the tree.
2. **Version-independent** — true of every row of the column regardless of which document
   version it holds. `documents/*.json` are versioned by URN (`urn:huron:metadata:1`,
   `urn:huron:snapshot-provenance:1`); a required-key or enum check in SQL would have to be
   edited every time a version lands, and a migration that must be written whenever a JSON
   Schema changes is a second source of truth, not a constraint.
3. **Load-bearing for the database itself, or for the reader that cannot run Python** — either
   another database rule keys off it, or the column is unusable without it.

**Everything else is Python's.** Required keys, value types, enum members inside the document,
cross-field conditionals, `unevaluatedProperties: false` — all of it lives in
`src/huron/schema/documents/` and is enforced by `huron.schema.validate(name, document)`, which
reports a JSON path on failure. A CHECK can only say *no*.

Applying the rule to the fifteen gives exactly two things in the database:

- **The top-level type**, on all fifteen — criterion 3's second clause. A jsonb column whose
  top-level type is unknown cannot be read by anything: `spec['retention_days']` and
  `completed_parts[0]` are both errors against a bare string, and the reader finds out at read
  time, arbitrarily far from the write. This is the whole of what `0008` adds.
- **`provenance->>'kind'`**, already present from `0004` — criterion 3's first clause, and the
  only interior key in the schema that qualifies: a *database* rule keys off it
  (`layer <> 'gold' OR provenance->>'kind' IS NOT DISTINCT FROM 'derivation'`), which is a
  cross-column rule that `huron.schema` cannot see, because `layer` is not in the document.

And it excludes, deliberately, the thing that looks most tempting: **pinning the `schema` URN**
(`CHECK (document->>'schema' = 'urn:huron:metadata:1')`) on `science_profiles.document`,
`revision_amendments.document`, `snapshots.provenance` or `product_versions.derivation_record`.
It fails criterion 2 outright — the URN is the version, so the constraint would forbid
`urn:huron:metadata:2` and would have to be rewritten by migration as part of every schema
version bump. Versioning documents in files and pinning their version in DDL are the same
decision made twice, in two places, that then have to agree.

#### What each CHECK guarantees, and what it does not

**Guarantees.** For the fourteen object columns: the stored value is a JSON object — `{}`
included — for every row, on every INSERT and every UPDATE, for every writer, including `psql`.
For `ingest_files.completed_parts`: the stored value is a JSON array. For the two nullable
columns: SQL NULL or an object, and nothing else.

**Does not guarantee.** That the object has any particular key; that a required key is
non-empty; that `spec` matches its `policy_type`; that `document` validates against its
`documents/*.json`; that `completed_parts` holds part *numbers* rather than arbitrary elements,
or that they are unique or ordered. Every one of those is Python's, by the rule above.

**SQL NULL is not JSON `null`, and the constraint separates them.** `'null'::jsonb` is a
perfectly legal value of a `NOT NULL jsonb` column — `jsonb_typeof` reports `'null'` — and it
passes every constraint the schema has today. After `0008` it is refused on all fifteen columns,
including the two nullable ones, where the legal way to say "absent" is SQL NULL. That is a
narrowing worth naming, because a Python writer that serialises `None` with `json.dumps` rather
than passing SQL `None` produces exactly this value, and it currently stores silently.

**Error behaviour.** A violating write raises SQLSTATE `23514` (`check_violation`), surfaced by
asyncpg as `asyncpg.exceptions.CheckViolationError` — the same class S2 and S3 use, and *not*
the `asyncpg.exceptions.RaiseError` the plpgsql guards produce or the `ForeignKeyViolationError`
S1's composite FK produces.

#### Migration-time behaviour, and the writers that exist

Every constraint is added **without `NOT VALID`**: `0008` validates every existing row and fails
loudly on anything that is not the declared type, matching S1's and S2's posture. Each is
satisfiable by construction:

- Eleven of the fifteen columns are in tables with **zero PostgreSQL writers** (Current State
  §5) — they are empty in every real database.
- `projects.raw_retention_policy` has no PostgreSQL writer either (`repository.py` is in-memory),
  so it holds its `'{}'` default or nothing.
- `role_bindings.conditions` is never named by `grant_role`'s INSERT
  (`postgres_rbac.py:111-114` lists nine columns and `conditions` is not among them), so every
  row carries the `'{}'` default. No application change; the column is written only by its
  default and read by nothing.
- `policies.spec` is the one column with a live writer on both sides:
  `create_policy` inserts `json.dumps(record.spec)` from a `dict[str, object]`, and
  `list_policies` reads it back through `json.loads`. Both already assume an object. The
  constraint is the second line for a writer that is not the API — a future `pkg/metastore/`
  implementation (Roadmap Drift 2), an operator at `psql`, a data fix.
- `idempotency_records.response` has no writer today, and when one lands it is safe by
  construction: every return annotation under
  `src/huron/service/api/routes/v1/endpoints/` is `dict[str, object]` or `dict[str, str]`, and
  RFC 9457 problem documents are objects too.

**No application code, no `pkg/` symbol and no test changes on this task's account.** Nothing in
`src/huron/` reads a constraint name, and the one live writer already satisfies its constraint.

#### The S6 ordering dependency on `audit_events`

S3 verified on PostgreSQL 16, rather than assuming, that `ALTER TABLE audit_events ADD
CONSTRAINT … CHECK (…)` recurses to every existing partition (`pg_constraint` then holds the
parent row with `conislocal = t` and a child row with `coninhcount = 1`, all `convalidated = t`)
and that a partition created afterwards inherits it with no further DDL. That result carries to
`audit_events_payload_is_an_object` unchanged, so:

- If **S6 keeps the partitioning**, the statement is correct as written and its position in
  `0008`'s `DDL` string does not matter.
- If **S6 de-partitions** `audit_events`, the surviving relation is a new or renamed plain table
  and this statement must run **after** that structural DDL, against the surviving relation — a
  constraint on the old partitioned parent is dropped with it.

S5's verdict is unaffected either way: an audit payload is a keyed record because of what an
audit row is, not because of how the table is stored. **Whichever of S3/S5/S6 is sequenced last
in `SCHEMA_IMPLEMENTATION_PLAN.md` owns placing both `audit_events` statements after the
structural DDL.** This is the same dependency S3 records, not a second one.

#### The no-GIN decision, restated as a decision

**`0008` adds no GIN index on any jsonb column, and this is settled, not deferred pending
measurement.** The reason is a property of the application, not a guess about cost: `src/huron/`
issues **no** jsonb containment (`@>`), key-existence (`?`, `?|`, `?&`) or path (`->>`, `#>`,
`@?`, `@@`) query against any of the fifteen columns. The only jsonb operator anywhere in
`src/huron/` is the `$4::jsonb` cast in `create_policy`'s INSERT. Every jsonb column is read
whole — `json.loads(row["spec"])` — or not at all. A GIN index on a column nothing searches
costs write amplification and index maintenance on every insert to buy nothing.

**Reversal condition, stated so this does not get re-litigated by inspection.** Add a GIN index
when, and only when, a query in `src/huron/` filters rows by the *contents* of a jsonb column —
the first `WHERE col @> …`, `WHERE col ? …` or `WHERE col->>'k' = …` in a code path, not in a
migration or a test. At that point:

- containment-only workload → `USING GIN (col jsonb_path_ops)`, which is smaller and faster than
  the default opclass and loses only key-existence support;
- one hot scalar field → a `GENERATED ALWAYS AS ((col->>'k')) STORED` column with a plain btree,
  which the skill recommends over a GIN index for equality and range on a known key, and which is
  also the point at which to ask whether that field should simply be a column.

The type constraints this task adds are orthogonal to that choice and do not have to be revisited
when it arrives.

#### Negative-write tests

Fifteen constraints, fifteen refused writes, each paired with a permitted write — the pairing
rule S1, S2 and S3 all apply, since a constraint that rejects everything would otherwise pass.
The shape is `tests/contract/test_rbac_store.py`'s `_assert_trigger_rejects_*` with
`asyncpg.exceptions.CheckViolationError` substituted for `RaiseError`.

| Module | Columns | Must be refused | Must be accepted |
|---|---|---|---|
| `tests/contract/test_rbac_store.py` | `policies.spec`, `role_bindings.conditions` | `'"just a string"'::jsonb`, `'[]'::jsonb`, `'null'::jsonb` | `'{}'::jsonb` and a populated object |
| `tests/contract/test_catalog_store.py` (S1 introduces it) | the other thirteen | as above, per column | `'{}'::jsonb`, plus `'[]'::jsonb` for `completed_parts` |

Three cases carry more weight than the rest and must be written explicitly rather than folded
into a loop:

- **`UPDATE projects SET raw_retention_policy = '"just a string"'::jsonb`** — F5's own proof,
  replayed. It succeeds against `0007` and must fail against `0008`.
- **`ingest_files.completed_parts = '{}'::jsonb`** must be *refused* while
  `'[]'::jsonb` is accepted — the assertion that proves the array column was not swept up in the
  object rule. Its object-column mirror (`'[]'` refused, `'{}'` accepted) proves the converse.
- **`'null'::jsonb` refused on `snapshots.validation_evidence` and `lineage_edges.region`, with
  SQL `NULL` accepted on both** — the assertion that proves the NULL-safe spelling admits absence
  without admitting the JSON null literal. Without it, the two nullable constraints are the only
  ones in the set whose behaviour is untested in the direction that matters.

`snapshots.provenance` needs no new test for invariant N: `0004`'s constraints are untouched, and
`tests/unit/test_schema_snapshot_provenance.py` continues to cover the document shape in Python.
Its new type constraint gets the same refused/accepted pair as the other twelve.

### Deletions

- **None.** No constraint, index, trigger, table, column, `pkg/` symbol or test is made removable
  by this task. All fifteen CHECKs are additive over columns that had none, and the two `0004`
  constraints on `snapshots.provenance` are deliberately left in place — see the target design
  for why the new one is not a replacement for them.
- `migrations/schema.sql` §1 (`projects`, `revision_amendments`, `ingest_files`), §2
  (`role_bindings`, `policies`), §4 (`science_profiles`), §5 (`snapshots`, `product_versions`,
  `lineage_edges`) and §6 (`audit_events`, `outbox_events`, `idempotency_records`, `jobs`,
  `reconciliation_findings`) all become stale — every jsonb line in the file gains a constraint.
  The hand-written comments already there (`-- shape varies by policy_type` on `policies.spec`,
  `-- urn:huron:snapshot-provenance:1` on `snapshots.provenance`) are exactly the annotations the
  regeneration question turns on. **S8 owns what "regenerate" means**; recorded here only so the
  file is not forgotten.

### Rejected alternatives

- **One blanket `CHECK (jsonb_typeof(col) = 'object')` on all fifteen** — the shape F5's prose
  suggests; it would refuse every legal `ingest_files.completed_parts` row, including its own
  `'[]'` default, and would fail the migration on the first ingest ever recorded.
- **A domain type (`CREATE DOMAIN json_object AS jsonb CHECK (jsonb_typeof(VALUE) = 'object')`)
  applied to fourteen columns** — one definition instead of fourteen, but it changes every
  column's declared type, so `ALTER TABLE … ALTER COLUMN … TYPE` on fourteen columns, a domain
  that `pg_dump` and `migrations/schema.sql` must both explain, and asyncpg codec behaviour to
  re-verify, all to express what a one-line CHECK expresses per column.
- **Pin each document's `schema` URN in SQL (`document->>'schema' = 'urn:huron:…:1'`), extending
  `0004`'s key-pinning precedent** — it makes the DDL a second, weaker copy of
  `src/huron/schema/documents/`, and forbids version 2 of every document until a migration says
  otherwise.

### Open questions

1. **`science_profiles.document_sha256` is the one `*_sha256` column in the schema with no
   format CHECK — noticed here, owned by no task.** Every other digest column carries
   `CHECK (col ~ '^[0-9a-f]{64}$')`: `dataset_revisions.manifest_sha256` and `.metadata_sha256`,
   `ingest_sessions.manifest_sha256`, `ingest_files.expected_sha256`,
   `idempotency_records.request_sha256`, `api_keys.secret_sha256` (`0001`) and
   `local_credentials.secret_sha256` (`0005`). `science_profiles.document_sha256` is bare `text
   NOT NULL`. It surfaced because it is the digest *of* `science_profiles.document`, the jsonb
   column two lines above it, but it is a text column and so falls outside F5, and the audit's
   F2 table does not list it either. Adding
   `science_profiles_document_sha256_format CHECK (document_sha256 ~ '^[0-9a-f]{64}$')` to
   `0008` is a one-line change against a table with no writer, entirely in keeping with house
   style — **but it is not in any task's scope, so `0008` does not add it on S5's account.**
   Flagged for the planning phase to fold into S2's constraint sweep or to leave; it needs a
   decision, not a design.

---

## S6 — `audit_events` partitioning (design)

### Decision

**Settled 2026-08-31 by Karl: option B, drop the partitioning.** `audit_events` becomes a plain
table with `PRIMARY KEY (id)` and a btree on `(created_at, id)`. The recommendation below was
accepted as written; it is kept because it is the record of *why*, and the option that was not
taken is kept in one short section so nobody re-derives it. Nothing in this section is open.
The DDL has been executed against a live PostgreSQL 16 — see Proof, below.

### What the record actually says, and the one fact the audit did not carry

F6 frames this as "commit or drop", and Roadmap Drift item 1 records that `design/roadmap.html`
§2's `done` P1 row promised "audit with pre-created partitions". There is a **second** design
document making the same claim, and it is more specific than the roadmap:
`design/catalog-search.html` §2's table sketch reads

```
audit_events(… range-partitioned by month; partitions pre-created ahead of time
         plus a monitored DEFAULT backstop)
```

So the intended shape is on the record in detail: **monthly** bounds, pre-created, with the
DEFAULT partition retained deliberately as a monitored backstop rather than as the accident F6
found. `0001` delivered the backstop and nothing else — so both documents are wrong today, one
describing an undelivered design and, now that the decision has gone the other way, both
describing a design that was dropped. Phase 4 owns both edits (Open questions, below).

Two structural facts bound the decision, and neither is in the audit:

- **Nothing writes `audit_events`, and nothing will until roadmap milestone 3** ("an audit row for
  every mutation and every denied operation"), which is `todo`. There is no data to migrate and no
  measured rate to extrapolate from.
- **Whatever would create partitions ahead of time does not exist either.** The natural home is
  the retention worker — `design/architecture.html` §2 lists it as a daily CronJob that already
  "executes raw TTL expiration and approved purges … writes markers and audit events", and
  `jobs.kind` already carries `'retention'` in S3's closed vocabulary, so no new job kind is
  needed. But the retention worker lands in **P5**, which is `partial` with "the rest is not
  started". Audit writes therefore begin (milestone 3) **before** the maintainer exists (P5).
  In-database automation is not an escape: the compose stack runs the stock `postgres:16` image,
  which ships neither `pg_cron` nor `pg_partman`, and no migration issues `CREATE EXTENSION`.

### Proof

The target design below was **executed against a live PostgreSQL 16.13 on 2026-08-31**, on a
database built by applying `0001`–`0007` in order (each migration's module-level `DDL` string,
run through `psql -v ON_ERROR_STOP=1`). Verified there:

- the de-partitioning block runs end to end;
- the surviving `audit_events` is `relkind = 'r'` — a plain table — with `PRIMARY KEY (id)` and
  `audit_events_created_at` on `(created_at, id)`;
- S3's `audit_events_kind_format` and S5's `audit_events_payload_is_an_object` apply to that
  relation **with their text unchanged**, and enforce: `'BANANA'` and `'has space'` are refused,
  `'something.nobody.designed'` is accepted, a `'[]'` payload is refused;
- `PRIMARY KEY (id)` refuses a second row with the same `id` at a different `created_at` — the
  write the partitioned shape allowed;
- a keyset page plans as `Limit → Index Scan Backward using audit_events_created_at`;
- upgrade → downgrade round-trips to `0001`'s exact shape: partitioned parent, `DEFAULT` child,
  composite primary key, no index.

**That run also found a defect in the first spelling of the block, corrected below.** `ALTER TABLE
audit_events RENAME TO audit_events_partitioned` renames the *table* and not its indexes, so the
name `audit_events_pkey` was still occupied when the new table was created, and PostgreSQL silently
named the new primary key **`audit_events_pkey1`** — a permanent artifact in the schema, with the
same hazard in the downgrade. The block now renames the old index alongside the old table, and the
primary key comes out `audit_events_pkey`. This is exactly the class of defect that reading the DDL
does not catch.

**Re-verified independently on PostgreSQL 16.13, including the negative control.** A second run,
on a fresh database built the same way — `0001`–`0007` applied in order, then the S6 block exactly
as written under Target design — confirms all four of the following:

- with `ALTER INDEX audit_events_pkey RENAME TO audit_events_partitioned_pkey` present, the rebuilt
  table's primary key is named **`audit_events_pkey`**;
- with that one line removed and nothing else changed, the primary key comes out
  **`audit_events_pkey1`** — the defect reproduces exactly, which is what establishes the statement
  as **load-bearing rather than defensive**, and is why the plan asserts the key's *name* and not
  merely its shape;
- S3's `audit_events_kind_format` and S5's `audit_events_payload_is_an_object` both apply cleanly
  to the rebuilt plain table, in that order, positioned after the structural block as Ordering
  requires;
- the downgrade round-trips: after upgrade-then-downgrade, a nine-row catalog comparison —
  relations, constraints, index definitions, and the partition key — against a pristine
  `0001`–`0007` database is **byte-identical**.

S3's verified result — `ALTER TABLE … ADD CONSTRAINT … CHECK` recurses to every partition and is
inherited by partitions created afterwards — is carried forward as established, and is now
irrelevant to `audit_events`, which has no partitions.

### Not chosen — option A: commit to the partitioning

Recorded so the reasoning survives without a reader mistaking it for live design.

Monthly RANGE bounds exactly as `design/catalog-search.html` §2 specifies, with bound literals
carrying an explicit UTC offset; a plpgsql `audit_events_ensure_partitions(months_ahead integer)`
in the schema, called by the migration to lay a twelve-month runway and thereafter daily by the
retention worker to keep a rolling quarter ahead; `audit_events_default` kept as the monitored
backstop; `ALTER TABLE … DETACH PARTITION … CONCURRENTLY` from the worker (never a migration, which
Alembic runs in a transaction block) as the retention story; and the same btree on
`(created_at, id)` created on the parent before the first child, since BRIN cannot order rows and
so cannot serve a keyset page.

**Why it was not chosen, in one line:** it buys pruning at a volume Huron will not reach for years
and O(1) retention for a window nobody has written down, and charges for both a standing liveness
requirement — a runway extended forever by a worker that does not exist until P5, for a table that
starts being written in milestone 3, whose failure mode is a manual `ACCESS EXCLUSIVE` repair of
the audit log before the missed month's partition can be created at all — while permanently
forgoing `PRIMARY KEY (id)`, which a partitioned table cannot express. The full argument is in
*The reasoning behind the decision*, below.

### Target design

A partitioned table cannot be altered into a plain one; the shape change is a rebuild. It is a
rebuild of an empty table, and the `INSERT … SELECT` is there so the statement is correct rather
than merely correct-today.

```sql
-- ------------------------------------------------------------- audit_events
-- The audit log is a plain table. It is append-only and read newest-first, so
-- one btree over (created_at, id) serves both the time-range filter and the
-- keyset cursor; an event id is unique on its own, which is what the primary
-- key now says.
ALTER TABLE audit_events RENAME TO audit_events_partitioned;
ALTER INDEX audit_events_pkey RENAME TO audit_events_partitioned_pkey;

CREATE TABLE audit_events (
    id uuid PRIMARY KEY,
    kind text NOT NULL,
    actor text NOT NULL,
    subject_kind text NOT NULL,
    subject_id uuid,
    payload jsonb NOT NULL,
    created_at timestamptz NOT NULL
);

INSERT INTO audit_events (id, kind, actor, subject_kind, subject_id, payload, created_at)
SELECT id, kind, actor, subject_kind, subject_id, payload, created_at
FROM audit_events_partitioned;

ALTER TABLE audit_events_partitioned DETACH PARTITION audit_events_default;
DROP TABLE audit_events_default;
DROP TABLE audit_events_partitioned;

CREATE INDEX audit_events_created_at ON audit_events (created_at, id);
```

The detach-then-drop spelling is deliberate: dropping a partitioned parent does remove its
children, but writing it out means the migration says which relations it destroys instead of
relying on a cascade the reader has to know about.

**The `ALTER INDEX` beside each `ALTER TABLE … RENAME` is not decoration.** Renaming a table does
not rename its indexes, so without it `audit_events_pkey` is still held by the old relation when
the new one is created, and PostgreSQL quietly names the new primary key `audit_events_pkey1` —
observed, not predicted. Renaming the outgoing index first frees the name and the new key comes out
`audit_events_pkey`, matching every other primary key in the schema.

**The index that replaces the pruning** is the same btree the commit option uses,
`audit_events_created_at ON audit_events (created_at, id)`, for the same reasons — and it is the
first index `created_at` has ever had. That is worth being explicit about: today the only index on
`audit_events` is the `(id, created_at)` primary key, whose leading column is a random UUID, so
*neither* option is a regression against the status quo. Partition pruning and a btree range scan
converge on the same work for a time-bounded query; pruning's advantage shows up when the table is
large enough that the index itself stops fitting comfortably in cache.

**The primary key changes, and that is a gain, not a side effect.** `PRIMARY KEY (id, created_at)`
exists only because a partitioned table's unique constraints must contain the partition key. It
does not guarantee that an audit event id is unique — two rows sharing an `id` with different
`created_at` values are legal today, and nothing else in the schema forbids them. `PRIMARY KEY
(id)` restores the guarantee the column obviously intends, and the milestone-25 keyset cursor
`(created_at, id)` needs it: without unique `id`, a page boundary landing inside a tie is not a
total order and rows can repeat or vanish across pages.

**Downgrade** restores `0001`'s exact shape — partitioned parent, DEFAULT child, composite primary
key, no index (`0001` created none):

```sql
ALTER TABLE audit_events RENAME TO audit_events_plain;
ALTER INDEX audit_events_pkey RENAME TO audit_events_plain_pkey;

CREATE TABLE audit_events (
    id uuid NOT NULL,
    kind text NOT NULL,
    actor text NOT NULL,
    subject_kind text NOT NULL,
    subject_id uuid,
    payload jsonb NOT NULL,
    created_at timestamptz NOT NULL,
    PRIMARY KEY (id, created_at)
) PARTITION BY RANGE (created_at);
CREATE TABLE audit_events_default PARTITION OF audit_events DEFAULT;

INSERT INTO audit_events (id, kind, actor, subject_kind, subject_id, payload, created_at)
SELECT id, kind, actor, subject_kind, subject_id, payload, created_at
FROM audit_events_plain;

DROP TABLE audit_events_plain;
```

### The reasoning behind the decision

This is the argument that was put to Karl and accepted. **Neither thing partitioning buys is
available here, and the one thing it costs is live before the maintainer that would pay it
exists.**

Partitioning a time-series table buys two things: pruning at volume, and O(1) retention by
detaching a whole period instead of deleting rows.

- *Pruning at volume.* The skill's threshold is >100M rows. Milestone 3's rule is one audit row
  per mutation and per denied operation. Huron's mutations are catalog CRUD, ingest commits,
  release tags, publishes, and binding changes — human- and pipeline-paced, not event-stream-paced.
  At 10k audit rows a day that is 3.6M a year and 100M rows in ~27 years; at a deliberately
  pessimistic 100k a day, ~3 years. **This is an estimate with no measurement behind it and it is
  labelled as one** — but it is one to two orders of magnitude short of the threshold, and the
  error bars would have to be wrong by that much to change the answer. Audit volume also accrues
  at an observable, near-constant rate once milestone 3 ships, so the day partitioning becomes
  necessary is a day visible years in advance, not one that arrives by surprise.
- *O(1) retention.* No audit retention window exists anywhere in `design/` (see Open questions).
  Detaching months is the cheap way to enforce a window that has not been written down, for a
  policy nobody has stated.

Against that, committing installs a **standing operational dependency**: the runway must be
extended forever, by a worker that does not exist until P5, for a table that starts being written
in milestone 3. Its failure mode is not "slower queries" — it is a manual, `ACCESS EXCLUSIVE`
repair of the audit log before the missed month's partition can be created at all. Adding a
liveness requirement to the one table whose job is to still be correct when everything else went
wrong is the wrong trade at this volume.

Two supporting reasons, neither decisive alone:

- **Dropping strengthens the schema.** Option B replaces a composite key that guarantees nothing
  about `id` with `PRIMARY KEY (id)`, which the partitioned shape cannot express, and which the
  milestone-25 keyset cursor depends on. Option A permanently forgoes it. In a document whose
  subject is integrity gaps, giving up a uniqueness guarantee to buy pruning nobody needs is
  backwards.
- **Clean sweep reads this way.** A partitioned table with one DEFAULT child and no writer is the
  house definition of a speculative abstraction, and "prefer deletion over accommodation" is the
  standing bias. This argument is listed last on purpose: it is a tiebreaker, not the reason.

**What the decision is not.** It is not a claim that the design record is wrong about
Huron's eventual shape. If audit volume or an audit retention policy ever justifies monthly
partitions, the sketch above is what to re-derive from.

**Reversal cost, both directions.** Today they are identical and near zero: both are a rebuild of
an empty table, and the whole of option A or option B is one migration against a relation with no
writer. The asymmetry is entirely in the future.

- *B, later reversed to A* — partition a populated audit table: create the partitioned parent,
  copy every row, swap names, drop the old table. Cost scales with row count, needs a window in
  which the audit stream is locked, and rewrites a compliance record. At the 3.6M-rows-a-year
  estimate that is minutes of exclusive lock after a few years — real, schedulable, and preceded
  by years of visible warning.
- *A, later reversed to B* — de-partition a populated audit table: the same rebuild, the same
  scaling, the same window, plus first draining any rows the maintainer let accumulate in DEFAULT.
  Slightly worse, not categorically.

Neither direction is a trap. That is why the decision should be made on which shape is right,
not on which preserves the most optionality — **optionality is equal, so it is not a tiebreaker.**

**Is there a defensible third option?** I looked; there is not. The only genuine middle is *keep
the DEFAULT-only shell, add just the `(created_at, id)` index, and decide when milestone 3's
writer lands.* It is not defensible for a specific reason: **no new information arrives between
now and then.** Nothing writes the table, so the deferral accumulates no data, no rate, and no
measurement — milestone 3 would face the identical decision with the identical evidence, having
carried F6's structure-without-benefit and both stale design documents through the whole interval.
The other near-misses are variants of option A rather than options in their own right — yearly
instead of monthly bounds (a longer hand-laid runway; the same maintainer, the same silent
expiry), and a fixed literal runway with no maintainer at all (a fixed runway expires silently the month
after its last literal bound, putting every row back in DEFAULT — today's bug with extra tables). `pg_cron`/`pg_partman` is a different mechanism for
option A, not a third answer, and is unavailable in the stock image regardless.

### Explicit contracts

- **Write availability.** Every `INSERT INTO audit_events` succeeds whenever the database accepts
  writes. There is no partition that can be missing, so no audit write can fail for want of
  maintenance, and no mutation can be aborted by the failure of its own audit row. This holds
  with no CronJob, no worker, and no operator awake — which under option A holds only while the
  runway is ahead of `now()`, and degrades to a manual repair once it is not.
- **Query cost.** A time-bounded audit query — `WHERE created_at >= $1 AND created_at < $2`, or a
  keyset page `WHERE created_at < $cursor ORDER BY created_at DESC LIMIT n` — is an index range
  scan over `audit_events_created_at` whose cost is proportional to the rows returned, not to the
  size of the table. `(created_at, id)` is a total order because `id` is unique, so keyset paging
  neither repeats nor skips a row at a page boundary.
- **What is not guaranteed.** An unbounded query on `actor`, `kind`, or `subject_id` is a
  sequential scan; those columns carry no index, deliberately, because no code filters on them
  yet. The reversal discipline is S5's, restated: add the index when the first query in
  `src/huron/` needs it — a filtered audit stream is always time-bounded first, and
  `(created_at, id)` serves the filter's time slice; a genuinely global "everything this actor
  ever did" query is the trigger for `audit_events (actor, created_at)`, not this migration.
- **Uniqueness.** `PRIMARY KEY (id)` guarantees one row per audit event id across the entire log.
  Option A cannot guarantee this at all.

### Ordering

`0008` is one `DDL` string with one statement order. Under the decision, `audit_events` is dropped and
rebuilt, so a constraint added to the old parent would be destroyed
with it:

1. The target-design block above, in full — rename, `CREATE TABLE audit_events`, `INSERT … SELECT`,
   detach and drop the two old relations, `CREATE INDEX audit_events_created_at`.
2. **Then** S3's `audit_events_kind_format` and S5's `audit_events_payload_is_an_object`, as the
   `ALTER TABLE … ADD CONSTRAINT` statements those tasks wrote, **unchanged in text**. Only their
   position in the string is fixed here; neither task's DDL needs editing.

Placing the two CHECKs after the `INSERT … SELECT` rather than inlining them in the `CREATE TABLE`
is deliberate: S3's and S5's statements stay verbatim, and a pre-existing row that violated either
constraint (there are none) would surface as a failed `ALTER` naming the constraint rather than as
a failed row copy.

In `downgrade()`, the mirror: S3's and S5's `DROP CONSTRAINT IF EXISTS` statements run **before**
the structural rebuild. `IF EXISTS` makes the other order harmless, but reverse-of-upgrade is the
house ordering and does not depend on that.

**Confirmed by execution, not by reading.** On the live run described under Proof, both CHECKs were
added in that order after the rebuild and both applied to the surviving plain table with their text
unchanged, and both then refused the writes S3 and S5 say they must. Adding either before the
rebuild attaches it to the relation step 1 destroys, so the requirement is real rather than
defensive.

**One edit to S5's block follows from this, and S5 owns it.** The comment above S5's
`audit_events_payload_is_an_object` statement reads "Recurses to every existing partition and is
inherited by every partition created later" — a true statement about a relation that no longer
exists. The constraint text stays exactly as S5 wrote it; the comment goes.

### Deletions

The partitioned `audit_events` parent, its `audit_events_default` child,
and the composite `PRIMARY KEY (id, created_at)` — replaced by a plain table with
`PRIMARY KEY (id)`. Nothing else in the schema references `audit_events`; no migration after
`0001` touches it, and no foreign key points at it. `0001`'s `downgrade()` drops `audit_events`
by name and continues to work unchanged against the rebuilt table.

`migrations/schema.sql` §6 carries the comment `-- partitioned by created_at range` on
`audit_events` and must go; S8 owns that file.

### Rejected alternatives

- **Commit to the partitioning (option A)** — recorded, reduced, above; monthly bounds buy pruning at
  a volume years away and O(1) retention for an unwritten policy, and charge a standing liveness
  requirement whose failure mode is a manual `ACCESS EXCLUSIVE` repair of the audit log.
- **Keep the DEFAULT-only shell, add only the index, decide at milestone 3** — the deferral
  gathers no evidence, because nothing writes the table between now and then.
- **BRIN on `created_at` instead of btree** — BRIN cannot order rows, so it cannot serve a keyset
  page, and its newest ranges stay unsummarized until autovacuum — exactly the rows the audit
  stream reads first.
- **`pg_cron` or `pg_partman` to maintain the runway in-database** — neither ships in the stock
  `postgres:16` image the compose stack runs, and no migration issues `CREATE EXTENSION`; adopting
  one is an infrastructure decision, not a schema decision.

### Open questions

The partitioning decision itself is **closed** (see Decision, above); `0008` may be authored.
Two things remain, neither of which gates it.

1. **Forward-looking, not a gate: is there an audit retention window?** This is the one fact that
   would have flipped the recommendation, and it is still not in `design/` anywhere:
   `design/roadmap.html` §2 P5 specifies retention only for raw payload ("per-category TTL, pins,
   legal holds, `EXPIRED` markers"), and `design/architecture.html`'s invariant B is about published
   `revisions/` prefixes. Audit rows are therefore kept forever by default, which is a policy nobody
   wrote down rather than a policy anybody chose. It is recorded here because the plain table makes
   enforcing such a policy a `DELETE` over a time range rather than a `DETACH PARTITION`, and
   because if a window is ever adopted *and* the volume estimate below turns out an order of
   magnitude low, the partitioned shape becomes correct on that ground alone. Neither condition
   holds today, and both would be visible years in advance.
2. **Two design documents must be corrected; Phase 4 of `/design-plan` owns the edits, this task
   only records them.** `design/roadmap.html` §2's P1 row is tagged `done` and lists "audit with
   pre-created partitions" among its deliverables — that deliverable is withdrawn, and it was never
   true of the `done` phase as shipped. `design/catalog-search.html` §2's `audit_events` sketch
   ("range-partitioned by month; partitions pre-created ahead of time plus a monitored DEFAULT
   backstop") is the more specific claim and needs the same correction. Both lines are replaced by
   the plain-table shape: a plain append-only table, `PRIMARY KEY (id)`, one btree on
   `(created_at, id)`.

---

## S7 — Ingest-session ↔ revision correspondence (design)

### The fact that decides the mechanism

`ingest_sessions.revision_id` is minted at `begin_ingest`, under the per-dataset ingest lock,
while the session is `PREPARING`. The `dataset_revisions` row it names is not written until step 7
of the commit protocol — after the staging rename is durable, which may be hours later and is
always a **different transaction** (`design/layer-raw.html` §5: "no database transaction is ever
held across file I/O"; invariant G, "storage leads; the catalog follows").

`DEFERRABLE INITIALLY DEFERRED` defers a foreign-key check **to the end of the transaction that
made the row dirty** — it does not, and cannot, defer across transactions. So a deferred FK on a
`NOT NULL` column is violated at the `COMMIT` of `begin_ingest` itself, exactly as an immediate
one would be. Deferral buys nothing here, because the dependency is not circular: inside the
commit transaction the natural statement order already inserts the revision before it flips the
session, so an *immediate* FK would check cleanly at that point too. What deferral would actually
have to buy is nullability — a NULL referencing value skips the check under `MATCH SIMPLE`, and
that, not the deferral, is the only thing that makes a declarative FK representable across the
session's life.

That price is not payable. `IngestLease.revision_id: UUID` is what makes the sentence in
`design/layer-raw.html` §4 true — "the revision number is allocated at `BeginIngest` … and the
final path is known before any byte is written". The final path is
`revisions/{nnnnnn}--{revision_id}`; the prepare worker hardlinks into a staging envelope whose
rename target is computed from it. A `revision_id` that is NULL until commit means the rename
target is unknown until commit, which is a change to the storage protocol, not to a column.

So the declarative-FK family is out on its own merits, and the choice is not "declarative versus
imperative" but "constrain the reservation, or constrain the claim". **The mechanism is a
commit-time trigger**, in the shape the house already uses for rules that read another table
(`service_account_kind_guard()`, `role_binding_guard()`).

### Target design

One function and one trigger, in the single `DDL` string of `0008`. They depend on nothing else
in `0008` and nothing in `0008` depends on them, so they may sit anywhere in the string.

```sql
-- An ingest session names the revision it will become before that revision
-- exists: begin_ingest mints revision_id and revision_number under the
-- per-dataset ingest lock, so the final storage path is known before any byte
-- is written, while the revision row is not written until the staging rename
-- is durable. A foreign key would therefore make PREPARING unrepresentable,
-- and deferral does not reach across the hours between the two transactions.
-- What a session actually claims, and what is enforceable at the moment it
-- claims it, is this: the revision reserved at BeginIngest is the revision
-- that was created. ABORTED and FAILED claim nothing, so their reservation is
-- simply never redeemed. FOR KEY SHARE takes the row lock a foreign key would
-- have taken, so the revision cannot be deleted out from under a session that
-- is committing.
CREATE FUNCTION ingest_session_revision_guard() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    PERFORM 1 FROM dataset_revisions
     WHERE id = NEW.revision_id
       AND dataset_id = NEW.dataset_id
       AND revision_number = NEW.revision_number
       AND manifest_sha256 = NEW.manifest_sha256
       FOR KEY SHARE;
    IF NOT FOUND THEN
        RAISE EXCEPTION
            'ingest session % claims revision %, which is not revision % of dataset %',
            NEW.id, NEW.revision_id, NEW.revision_number, NEW.dataset_id;
    END IF;
    RETURN NEW;
END $$;

CREATE TRIGGER ingest_sessions_revision_guard BEFORE INSERT OR UPDATE ON ingest_sessions
FOR EACH ROW WHEN (NEW.state = 'COMMITTED')
EXECUTE FUNCTION ingest_session_revision_guard();
```

and the matching `downgrade()`:

```sql
DROP TRIGGER IF EXISTS ingest_sessions_revision_guard ON ingest_sessions;
DROP FUNCTION IF EXISTS ingest_session_revision_guard();
```

**Why the guard matches on four columns rather than one.** A bare existence check
(`WHERE id = NEW.revision_id`) is only what the rejected FK would have given. The invariant F8
names is stronger — *the revision actually created* — and every column of it is already carried
by both tables:

| Clause | Why it is checkable, and what it catches |
|---|---|
| `id = NEW.revision_id` | Existence. Catches the audit's proof case verbatim — a session committed against a UUID that joins to nothing. |
| `dataset_id = NEW.dataset_id` | The same cross-parent bug S1 fixes on `releases`, one table over: a session of `ds-two` committing against a revision of `ds-one`. |
| `revision_number = NEW.revision_number` | Both tables carry `UNIQUE (dataset_id, revision_number)`; the session's number is the reservation invariant E depends on. A mismatch means the number the lock allocated is not the number that landed. |
| `manifest_sha256 = NEW.manifest_sha256` | The digest declared at `BeginIngest` is the digest committed — step 2 of the commit protocol asserts it in application code, and `dataset_revisions` carries `UNIQUE (dataset_id, manifest_sha256)`. This is the one clause with a live coupling: it holds because no path re-declares a session's manifest (`IngestSession.manifest_sha256` is a frozen field and `transition()` never rewrites it), and a design that later lets a client amend a manifest mid-session must move this clause with it. |

**Why `BEFORE INSERT OR UPDATE` and not `BEFORE UPDATE`.** The normal path only ever reaches
`COMMITTED` by update — `0001`'s `state` CHECK permits any of the seven values on INSERT, so a
row could be inserted straight into `COMMITTED` by a backfill or a reconciler import. The `WHEN`
clause makes the INSERT arm free on every real insert (sessions are born `PREPARING`), so
covering it costs nothing and closes the hole. This follows `service_accounts_kind_guard` and
`role_bindings_guard` rather than `releases_immutable_before_update`, which is update-only
because it compares `OLD` to `NEW`; this guard reads only `NEW`, so `WHEN` is legal on both arms.

**ABORTED and FAILED are satisfiable, by construction.** The `WHEN` clause is false for every
state but `COMMITTED`, so the trigger does not fire on `PREPARING → ABORTED`,
`UPLOADING → FAILED`, or any other terminal transition. Those rows keep a `revision_id` that
names a revision which will never exist, and that is correct: it is a reservation that was never
redeemed. `revision_id` stays `uuid NOT NULL UNIQUE` — nothing about the column changes, so the
`NOT NULL` is satisfied by the value `begin_ingest` already wrote.

**No conflict with the neighboring constraints.**

- `one_open_ingest_per_dataset` is a partial unique index excluding the three terminal states.
  A `BEFORE` row trigger runs before index maintenance, so a guard that raises aborts the
  transaction with the session still in the open set — the dataset lock is *not* released by a
  failed commit, which is the behavior wanted. A guard that passes lets the flip to `COMMITTED`
  drop the row out of the partial index and release the lock, unchanged from today.
- The `ingest_sessions.state` CHECK is untouched; the guard's `WHEN` clause names `'COMMITTED'`,
  one of the seven values that CHECK already permits and that `IngestState` already spells.
- S4's foreign-key sweep is unaffected: this adds no foreign key, so its count stands at
  **23 before `0008` and 22 after**. It adds no index either — the guard's lookup is an
  index-only probe of `dataset_revisions_pkey` with two heap-checked equalities, and
  `ingest_sessions.revision_id` already carries a unique index from `0001`.

### Explicit contracts

**Invariant.** For every `ingest_sessions` row in state `COMMITTED`, there exists a
`dataset_revisions` row whose `(id, dataset_id, revision_number, manifest_sha256)` equals the
session's. Equivalently: a session reports success only about a revision that exists, belongs to
the session's dataset, carries the number the ingest lock allocated, and holds the manifest
digest the session declared.

**What the future `Metastore` implementation must honor.** The port is declared but unimplemented
(`src/huron/pkg/catalog/ports.py`), so these are requirements on code that does not exist yet:

1. **One transaction, revision first.** The commit transaction of `design/layer-raw.html` step 7
   must `INSERT INTO dataset_revisions` **before** it updates the session to `COMMITTED`. This is
   the one thing a deferrable FK would have relaxed and a trigger does not: statement order
   inside the transaction is load-bearing. The order is the natural one and the one the protocol
   already describes ("revision row, session → COMMITTED"), so this is a documented requirement,
   not a new constraint on the writer's shape.
2. **The transaction begins after the rename.** Unchanged from invariant G, and the guard cannot
   enforce it — it only ever sees database state. Stated so the ordering requirement above is not
   mistaken for permission to open the transaction earlier.
3. **The session is flipped in that same transaction.** `Metastore.record_revision(revision,
   outbox)` as declared carries no ingest identity, but none is needed: `ingest_sessions.
   revision_id` is `UNIQUE`, so the session is derivable as
   `UPDATE ingest_sessions SET state = 'COMMITTED', etag = etag + 1, updated_at = $now
   WHERE revision_id = $revision_id`. An implementation that instead grows the port's signature
   is free to, but is not forced to by this task.
4. **The reconciler is a second writer bound by the same rule.** `design/layer-raw.html`'s
   crash-after-step-6 row has the reconciler importing a revision row from the `COMMITTED`
   marker. If that import also flips a surviving session, it is the same transaction shape and
   the same ordering; if the session was already swept, it inserts the revision alone and the
   guard never fires (see residual gap 2).

**No Python change is required.** `IngestLease.revision_id` stays `UUID`, not `UUID | None`;
`src/huron/pkg/catalog/ingest.py`, `src/huron/pkg/catalog/ports.py` and
`src/huron/pkg/catalog/models.py` are untouched by S7. This is the substantive difference from
the rejected FK, which would have forced `IngestLease.revision_id: UUID | None` and, with it, a
`revision_path` that cannot be computed until commit. Because no `pkg/` symbol moves, the
"Python module changes in the same change as the migration" convention that binds the
`roles.py`/seed pair (Constraint 4) has nothing to bind here.

**Error behavior.** A violating flip raises SQLSTATE `P0001` via plpgsql `RAISE`, surfaced by
asyncpg as `asyncpg.exceptions.RaiseError` — the same class the existing guards produce, and
*not* the `ForeignKeyViolationError` S1's constraint produces. Tests and handlers must
distinguish accordingly. The domain error a service layer should map it to already exists:
nothing in `src/huron/pkg/catalog/errors.py` needs adding, since this failure is an internal
invariant breach rather than a client-visible outcome — a client cannot construct it, because a
client never supplies `revision_id`.

**Migration-time behavior — and the one way this is weaker than a constraint.** `CREATE TRIGGER`
does not validate existing rows. A `COMMITTED` session already carrying a bogus `revision_id`
survives `0008` silently, where S1's FK would have failed the migration loudly. This cannot arise
today — per Current State §5 no PostgreSQL writer for `ingest_sessions` exists, so the table is
empty in every real database — and adding a backfill check for a row that cannot exist would be
speculative. Recorded so the asymmetry with S1 is deliberate rather than overlooked.

**Concurrency.** The `FOR KEY SHARE` is what keeps the guard equivalent to a foreign key rather
than merely similar to one. A bare `SELECT` proves the revision existed in the guard's snapshot,
which a concurrent `DELETE` committing before the session's transaction does would falsify;
`FOR KEY SHARE` takes exactly the row lock PostgreSQL's own RI trigger takes, blocking such a
delete until the commit transaction resolves. In the ordinary path the revision was inserted by
this same transaction moments earlier, so the lock is already held and the clause is free.

### Data flow

Where the guard sits in `design/layer-raw.html` §5, relative to the durability point.

```mermaid
sequenceDiagram
    participant C as CommitIngest
    participant FS as Raw store [NFS]
    participant PG as PostgreSQL

    C->>PG: 1-3. idempotency replay; lock session row; assert VERIFYING, ETag, digest
    Note over C,PG: no transaction is held past here
    C->>FS: 4. write manifest.json, metadata.json, COMMITTED; fsync
    C->>FS: 5. seal payload 0444, dirs 0555
    C->>FS: 6. rename .staging/ingest_id to revisions/nnnnnn--revision_id
    Note over FS: durability point - storage leads, invariant G
    rect rgb(238, 238, 238)
        Note over C,PG: 7. ONE short PG transaction
        C->>PG: INSERT dataset_revisions
        C->>PG: UPDATE ingest_sessions SET state = COMMITTED
        PG-->>PG: BEFORE UPDATE, WHEN state = COMMITTED: ingest_session_revision_guard
        PG-->>PG: PERFORM ... FOR KEY SHARE on the row just inserted
        C->>PG: audit event, outbox event, idempotency record
    end
    C->>FS: 8. best-effort INDEX.json; reconciler owns it
```

The guard fires **inside** step 7 and **after** the rename, so it can never delay or gate file
I/O, and a guard failure aborts a transaction that touches no filesystem state. The staging tree
is already published at that point; a failed step 7 is exactly the crash-after-6 row of the
protocol's recovery table, which the reconciler already names.

### Negative-write tests

`tests/contract/test_catalog_store.py` (introduced by S1) is where these land, on the
`_assert_trigger_rejects_*` shape from `tests/contract/test_rbac_store.py`, with
`asyncpg.exceptions.RaiseError` as the expected class:

- **the audit's proof case** — a session in `COMMITTING` flipped to `COMMITTED` while its
  `revision_id` names no `dataset_revisions` row: rejected;
- **the cross-dataset case** — a real revision, but of another dataset: rejected;
- **the wrong-number case** — the right dataset and id, a `revision_number` that differs from the
  session's: rejected. (Constructing it takes a session whose reserved number is not the number
  the revision landed with, which the schema permits today.)
- **the positive control** — the same flip against the revision the session reserved: succeeds.
  Without it, a guard that rejected everything would pass;
- **the terminal-state control** — `PREPARING → ABORTED` and `UPLOADING → FAILED` on a session
  whose `revision_id` names nothing: both succeed, which is the ABORTED/FAILED path proven rather
  than asserted.

### Deletions

None. No constraint, index, trigger, function, `pkg/` symbol or test is made obsolete;
`ingest_sessions.revision_id`'s `NOT NULL` and `UNIQUE` both stay and are both relied on.
`migrations/schema.sql`'s `ingest_sessions` block becomes stale on this change, as it does for
every other task; S8 owns what regenerating it means.

### Rejected alternatives

- **`DEFERRABLE INITIALLY DEFERRED` FK on `ingest_sessions.revision_id`** — deferral does not span
  transactions, so it fails at `begin_ingest`'s own COMMIT unless the column goes nullable; and
  once it is nullable an immediate FK would do the same job, so the deferral is decoration on a
  change that costs `IngestLease.revision_id` its type and the storage protocol its
  known-in-advance rename target.
- **Immediate FK on a nullable `revision_id`, plus `CHECK (state <> 'COMMITTED' OR revision_id IS
  NOT NULL)`** — the honest form of the option above and genuinely declarative, but it pays the
  same Python and storage-protocol price and enforces strictly less: existence only, with no
  dataset, number or digest correspondence.
- **Add `dataset_revisions.ingest_id` with a plain FK back to the session** — the reverse edge is
  a legal plain FK (the session always exists first), but it constrains a different thing (which
  session produced this revision, not which revision this session claims), leaves
  `ingest_sessions.revision_id` exactly as unconstrained as F8 found it, adds a column to an
  immutable table plus a field to `RevisionRecord`, and must be nullable anyway for a
  reconciler-imported orphan whose session was swept.

### Open questions

1. **Residual gap, accepted: the reverse direction is not enforced.** The guard says "if a session
   is `COMMITTED` then its revision exists and matches". It does not say "if a revision exists
   then some session claims it", and it must not: a crash between steps 6 and 7 leaves an orphan
   envelope that the reconciler imports as a revision row whose session may already have been
   swept by the TTL sweeper. An orphan revision with no session, and a revision beside a session
   stuck in `COMMITTING`, both remain representable by design — they are states the reconciler is
   specified to name and resolve, not corruption. What keeps the second of those lawful rather than
   a stranding is S7a's contract 6 (§ "S7a — … ### The stranded envelope after the durability point
   — resolved"): a session in `COMMITTING` holds its revision number until somebody consults
   storage, and only a proven-absent envelope may be failed.
2. **Residual gap, accepted: post-commit divergence.** Once the flip succeeds the guard never
   fires again on that row unless it is updated. Nothing stops a later `DELETE FROM
   dataset_revisions` or an `UPDATE` of the revision's `dataset_id`/`revision_number` from
   breaking the correspondence a real FK would have kept enforcing. Both are already excluded by
   convention — S4 #3 and #14 record that revisions are never deleted (a purge is a `state`
   transition to `PURGED`, and `purge_records` must outlive what it purges), and revisions are
   immutable — but neither exclusion is enforced by the schema. `dataset_revisions` has no
   immutability trigger of the `releases_immutable()` kind. Whether it should acquire one is a
   real question, and a broader one than F8; **not resolved here, and `0008` does not add one.**
3. **Resolved by S7a — the reservation is released on abort.** `ingest_sessions` carried a *total*
   `UNIQUE (dataset_id, revision_number)`, so an `ABORTED`/`FAILED` session kept the number it
   reserved, and since `design/layer-raw.html` §4 allocates as `max(committed) + 1`, the retry
   re-allocated that number and its `INSERT` collided with the dead row. Reproduced verbatim against
   a live PostgreSQL 16.13 (see S7a). **Karl settled the semantics on 2026-08-31:** the number is
   freed, the dead session row is kept, and the retry is a whole new session. So `0008` **does**
   touch `ingest_sessions_dataset_id_revision_number_key` — it replaces it with the partial unique
   index `one_claim_per_revision_number`. The DDL, the contract this imposes on the allocator and
   the TTL sweeper, the proof that gap-free revision numbering survives, and the one residual
   hazard it exposes are in **`## S7a — Abort and retry semantics (design)`**.

4. **Noted, not blocking: `Metastore.record_revision` does not name the session it closes.** The
   guard does not require the port to change (contract 3 derives the session from the `UNIQUE`
   `revision_id`), but the port as declared also does not *say* that flipping the session is part
   of `record_revision`'s job, and the invariant now depends on it. Whoever implements the
   Protocol should settle whether that obligation is expressed in the signature or in its
   docstring. Not a `0008` concern.

---

## S7a — Abort and retry semantics (design)

### The decision

**Settled 2026-08-31 by Karl.** On abort, or on an error committing an ingestion, the reserved
revision number is **freed**. The retry starts the whole process again from a new session. The
aborted or failed session row is **kept** — it survives as the record of what was attempted — and
the number is freed by replacing `0001`'s total unique constraint with a **partial unique index
excluding the terminal-failure states**, mirroring the existing `one_open_ingest_per_dataset`
pattern. If the ingestion was for a **brand-new dataset**, the dataset is **kept, empty**:
`ACTIVE`, zero revisions, and the retry opens a fresh ingest against it. It is not deleted, because
slugs are immutable and are baked into storage paths, so a delete-and-recreate would force a new
dataset id.

This resolves S7 open question 3, which recorded the bug and could not settle it because the
semantics were a statement about an unimplemented allocator.

### The bug, reproduced

Against a live PostgreSQL 16.13 database built by applying `0001`–`0007` in order: a session
reserving revision number 1 on `ds-one`, driven to `ABORTED`, then a new session inserted for the
same `(dataset_id, revision_number)` — the exact shape of a retry — fails.

```
ERROR:  duplicate key value violates unique constraint "ingest_sessions_dataset_id_revision_number_key"
DETAIL:  Key (dataset_id, revision_number)=(…c1, 1) already exists.
```

**This is not merely inconvenient; the total constraint contradicts invariant E.**
`design/layer-raw.html` §4 allocates at `BeginIngest` as `max(committed) + 1` under the per-dataset
lock and calls the result "gap-free per dataset (invariant E)"; `design/roadmap.html` §2's P2 row
pins it as "100 sequential ingests number 1..100 gap-free"; `design/index.html` and
`docs/backend-design.md` repeat it. Under a total constraint there is no way to satisfy both:
either the retry is refused (today's behaviour), or the allocator must skip to `max(committed) + 2`
and open a permanent gap. **Freeing the number is what makes gap-free reachable, not a concession
against it.**

### Target design

```sql
-- A session reserves its revision number at BeginIngest, hours before the
-- revision exists. A reservation that ends ABORTED or FAILED was never
-- redeemed, so the number returns to the pool and the next session takes it
-- again; the dead row stays as the record of the attempt. Uniqueness is
-- therefore a property of live and committed claims, not of every row that
-- ever held the number - which is also what makes max(committed) + 1 a
-- gap-free allocator rather than one that burns a number per failed attempt.
ALTER TABLE ingest_sessions
    DROP CONSTRAINT ingest_sessions_dataset_id_revision_number_key;

CREATE UNIQUE INDEX one_claim_per_revision_number
    ON ingest_sessions (dataset_id, revision_number)
    WHERE state NOT IN ('ABORTED', 'FAILED');
```

and the matching `downgrade()`:

```sql
DROP INDEX IF EXISTS one_claim_per_revision_number;
ALTER TABLE ingest_sessions
    ADD CONSTRAINT ingest_sessions_dataset_id_revision_number_key
        UNIQUE (dataset_id, revision_number);
```

These statements depend on nothing else in `0008` and nothing in `0008` depends on them, so they
may sit anywhere in the single `DDL` string.

**The predicate, against the `state` CHECK vocabulary.** `0001`'s CHECK admits exactly seven
values: `PREPARING`, `UPLOADING`, `VERIFYING`, `COMMITTING`, `COMMITTED`, `ABORTED`, `FAILED`;
`TERMINAL_STATES` in `src/huron/pkg/catalog/ingest.py` is `{COMMITTED, ABORTED, FAILED}`. The
predicate excludes the two **terminal-failure** states and keeps `COMMITTED`, so the index covers
five of the seven. Keeping `COMMITTED` inside the predicate is the load-bearing part: a number a
session actually committed is spent forever and must never become re-reservable. Excluding all
three terminal states — the reflex, since that is `one_open_ingest_per_dataset`'s predicate — would
be the bug.

**The two partial indexes guarantee different things and neither implies the other.**

| Index | Predicate | What it guarantees |
|---|---|---|
| `one_open_ingest_per_dataset` (`0001`) | `state NOT IN ('COMMITTED','ABORTED','FAILED')` — the four in-flight states | **At most one in-flight ingest per dataset.** It is the per-dataset ingest lock: concurrency control, keyed on `dataset_id` alone. It says nothing about revision numbers. |
| `one_claim_per_revision_number` (`0008`) | `state NOT IN ('ABORTED','FAILED')` — the four in-flight states **plus `COMMITTED`** | **Within a dataset, a revision number is claimed by at most one session that either still holds it or committed it.** It is number stewardship, keyed on `(dataset_id, revision_number)`. It says nothing about how many ingests are open. |

They overlap only in excluding `ABORTED` and `FAILED`, and for the same underlying reason: a dead
session holds neither the lock nor the number. Beyond that they are independent — the first would
be satisfied by a schema with no revision numbers at all, the second by a schema that permitted
unlimited concurrent ingests per dataset.

### Uniqueness among committed sessions, and the race

**Is `revision_number` uniqueness among `COMMITTED` sessions still guaranteed? Yes, twice over.**
`one_claim_per_revision_number` includes `COMMITTED` in its predicate, so two committed sessions
cannot share a number and a new live session cannot take a committed one — proved: inserting a
`PREPARING` session at `(ds-one, 1)` after a session committed that number is refused, naming
`one_claim_per_revision_number`. Independently, `dataset_revisions` carries its own **total**
`UNIQUE (dataset_id, revision_number)`, and S7's commit-time guard requires a `COMMITTED` session's
`revision_number` to equal its revision's, so a committed session's number is pinned to a globally
unique revision row. The partial index is the better-placed of the two: it refuses the collision at
`BeginIngest` instead of after hours of upload.

**What prevents two live sessions racing for the same number — and it is not this index.**
`one_claim_per_revision_number` does **not** close that race. `one_open_ingest_per_dataset` already
did, and still does: two live sessions on one dataset cannot coexist at all, whatever numbers they
hold. Proved — a second `PREPARING` insert on `ds-one` carrying a *different* number is refused
naming `one_open_ingest_per_dataset`, not the new index. So `max(committed) + 1` is computed under
a lock that admits one holder, and two concurrent `BeginIngest` calls serialize on that index entry
rather than racing: the loser blocks on the winner's uncommitted index tuple and is then rejected.
Dropping the total constraint removes no part of that guarantee, because the total constraint was
never what provided it. Across datasets there is no race to close — `dataset_id` leads both keys.

### The allocator, and the gap-free property

**`max(committed) + 1` is still correct — and under this rule it is correct for the first time.**
Freeing a number can neither open a gap nor cause a reuse, and the argument is short enough to
check:

- A number enters the committed set only by a commit. Freeing happens only to sessions that never
  committed, because `COMMITTED` is terminal and `_TRANSITIONS` gives it no successor, so freeing
  can never remove a number from the committed set.
- The allocator reads the committed set. A freed number is therefore still `max + 1`, and the
  retry re-issues **the same** number rather than the next one.
- Nothing else consumes numbers. There is no sequence, no identity column and no `nextval` anywhere
  near `revision_number` — numbers exist only as `dataset_revisions.revision_number` values and as
  reservations on sessions — so the gappiness PostgreSQL sequences are documented to have has no
  way in.
- The committed set never shrinks. Revisions are never deleted (S4 #3 and #14: a purge is a `state`
  transition to `PURGED`, an expiry to `EXPIRED`; the row stays), so `max` never goes backwards and
  a number is never vacated after the fact.

Therefore the committed set is `{1..N}` with no holes, which is invariant E. **Proved end to end:**
two dead attempts at number 1 (one `ABORTED`, one `FAILED`), a third attempt committing 1, then a
fourth session committing 2 — `dataset_revisions` holds exactly `{1, 2}`, while `ingest_sessions`
holds `ABORTED {1}`, `FAILED {1}`, `COMMITTED {1, 2}`. Gap-free survives; the dead reservations stay
visible in the session table and invisible to the allocator.

**Finding: the allocator must read `dataset_revisions`, not `ingest_sessions`.** "`max(committed)`"
is ambiguous between the two tables and the difference is load-bearing. A reconciler-imported
orphan — `design/layer-raw.html`'s crash-after-step-6 row — is a revision whose session may already
have been swept, so it exists in `dataset_revisions` and not among `COMMITTED` sessions. An
allocator reading the session table would not see it, would re-issue its number, and the whole
ingest would run to completion before `dataset_revisions_dataset_id_revision_number_key` refused it
at step 7. The allocation is therefore:

```sql
SELECT coalesce(max(revision_number), 0) + 1
  FROM dataset_revisions
 WHERE dataset_id = $1;
```

`coalesce(…, 0)` is what makes a dataset with no revisions allocate 1 — the brand-new-dataset case
and the kept-empty-after-abort case are the same case, and both were exercised.

### Explicit contracts

**Invariant.** For every `(dataset_id, revision_number)` pair, at most one `ingest_sessions` row in
a state other than `ABORTED` or `FAILED` carries it. Equivalently: a revision number is held by the
session currently working toward it, or by the session that committed it, or by nobody.

**What the future `Metastore` implementation must honor.** `src/huron/pkg/catalog/ports.py`
declares `begin_ingest`, `record_revision` and `resolve_tag`, and nothing implements them, so these
are requirements on an author who has not written the code yet.

1. **Allocate from `dataset_revisions`, under the lock, with `coalesce`.** The query above, issued
   in the same transaction as the session `INSERT`, which is what takes
   `one_open_ingest_per_dataset` and makes the read-then-write safe.
2. **Abort writes a terminal state; it does not delete the row and does not touch the number.**
   `UPDATE ingest_sessions SET state = 'ABORTED', etag = etag + 1, updated_at = $now WHERE id = $1`
   — `'FAILED'` on a commit error. The number is freed as a *consequence* of that state write, by
   the index predicate. There is no separate release step and no column to clear: `revision_number`
   and `revision_id` both stay exactly as `begin_ingest` wrote them.
3. **The TTL sweeper and force-abort must write that state, not merely let `expires_at` pass.**
   This is the contract most easily missed. Freeing is state-based, not time-based: a session
   abandoned in `UPLOADING` with a long-expired lease still holds both the dataset lock and the
   number, forever, because both index predicates read `state` and neither reads `expires_at`.
   `design/layer-raw.html` §4's "a crashed client releases the dataset lock within the TTL" is a
   statement about a writer that must exist, not about the database doing it unaided.
   **And that writer must not blindly fail an expired `COMMITTING` session — see item 6.** Expiry
   is the sweeper's trigger; it is not evidence about the filesystem. A session that ran out its
   lease in `PREPARING`, `UPLOADING` or `VERIFYING` may be failed on the spot, because none of those
   states can have renamed anything. A session that ran it out in `COMMITTING` may not, because it
   may already be durable. This is the one contract of the six whose two halves must be written
   together: the sweeper that never writes a terminal state strands the lock forever, and the
   sweeper that writes one unconditionally strands a sealed envelope.
4. **The retry is a new session and mints a new `revision_id`.** Only `revision_number` is freed.
   `ingest_sessions.revision_id` keeps its **total** `UNIQUE` from `0001` and is untouched by
   `0008`: a fresh UUID per session, never reused, and the dead session keeps the one it reserved.
   So the retry's storage path `revisions/{nnnnnn}--{revision_id}` differs from the dead attempt's
   even though the number is identical, and the two can never collide on disk.
5. **A brand-new dataset survives its failed first ingest, empty.** The `datasets` row is created by
   the first `BeginIngest` naming a new slug and is not rolled back by the abort; it stays `ACTIVE`
   with zero `dataset_revisions` rows. No constraint in the schema requires a dataset to have a
   revision, so **`0008` adds no DDL for this clause** — the state is already representable, and
   was confirmed so. Its consequences fall on readers: anything computing a dataset's latest
   revision must handle the empty case rather than assume a row, which is the same `coalesce` the
   allocator needs.

6. **Nothing moves a session out of `COMMITTING` into a failure state without first determining
   whether the rename happened.** This is what keeps a freed number safe past the durability point,
   and it is the one contract here that no DDL could express: durability is a filesystem fact and
   PostgreSQL never sees the filesystem. Before writing `FAILED` on a session in `COMMITTING` —
   whether the writer is the commit path's own error handler, the TTL sweeper, a force-abort or the
   reconciler — the writer must determine whether `revisions/{nnnnnn}--{revision_id}` exists.
   **If it does, the resolution is roll-forward, not failure:** `design/layer-raw.html` §5's crash
   table mandates "Orphan commit. Reconciler imports the row from `COMMITTED`", and records that "a
   retry of step 6 finds staging gone and the target present → treats the rename as done
   (idempotent)". Only a **proven-absent** envelope may go to `FAILED`. The check is cheap and its
   writers already have what it needs: the sweeper is a filesystem actor by definition
   (§9 — it "deletes `.staging/{ingest_id}` directories whose session is terminal or expired"), and
   `pkg/catalog/paths.py` is the single source of the path it must stat. See
   § "### The stranded envelope after the durability point — resolved" for why this one edge is the
   whole of it, and why `0008`'s DDL needs no change to accommodate it.

**Where this interacts with S7's commit-time trigger.** They compose without conflict, and were
executed together on the same database.

- `ingest_sessions_revision_guard` fires only `WHEN (NEW.state = 'COMMITTED')`, so it never sees an
  abort. The `PREPARING → ABORTED` and `UPLOADING → FAILED` transitions that free a number pass
  untouched — proved.
- The guard is a `BEFORE` row trigger, so it runs before index maintenance. A flip to `COMMITTED`
  that the guard rejects never reaches `one_claim_per_revision_number`, and the session keeps both
  the dataset lock and its number, which is the right outcome for a failed commit.
- A dead session cannot be resurrected into `COMMITTED` to take a number back from the retry that
  succeeded: its `revision_id` names no revision, so the guard raises first. Proved —
  `ingest session … claims revision …, which is not revision 1 of dataset …`.
- After a successful retry the dead row's `(dataset_id, revision_number)` duplicates the committed
  row's, and that is intended: the partial index permits it and the guard never fires on the dead
  row.

**Error behavior.** A refused claim raises SQLSTATE `23505` (`unique_violation`), surfaced by
asyncpg as `asyncpg.exceptions.UniqueViolationError` and naming `one_claim_per_revision_number` in
its message — distinct from the `RaiseError` S7's guard produces and from the
`ForeignKeyViolationError` S1's constraint produces. Handlers that map a lost `BeginIngest` race to
a client-visible error must read the index name, not the SQLSTATE, since
`one_open_ingest_per_dataset` raises the same class for a different reason.

**Migration-time behavior.** Dropping a constraint and creating a strictly narrower index cannot
fail on existing data: every row the total constraint admitted also satisfies the partial index.
`0008` therefore applies to any database, unlike S1's FK.

**Downgrade round-trips on a clean database, and refuses loudly on a dirty one.** Verified both
ways. On a database with no `ingest_sessions` rows, upgrade → downgrade → upgrade round-trips
exactly, which is the standard `design/roadmap.html` §2's P1 row states. On a database that has
actually exercised a retry, restoring the total constraint **fails** — `could not create unique
index "ingest_sessions_dataset_id_revision_number_key" … Key (dataset_id, revision_number)=(…, 1)
is duplicated`. That is correct behaviour rather than a defect: those rows are lawful under the new
rule and unlawful under the old one, so the downgrade refuses instead of silently destroying
attempt history. An operator who genuinely wants `0007`'s shape back must first decide what becomes
of the dead sessions.

### Data flow

The abort → retry path, and what each state write does to the two index predicates.

```mermaid
flowchart TD
    A["BeginIngest on dataset D<br/>n := coalesce(max(revision_number), 0) + 1<br/>over dataset_revisions"]
    B["INSERT ingest_sessions: PREPARING,<br/>revision_number = n, fresh revision_id<br/>takes one_open_ingest_per_dataset<br/>and one_claim_per_revision_number"]
    C{"the attempt"}
    D["UPDATE state = COMMITTED<br/>S7 guard passes: revision n exists and matches"]
    E["UPDATE state = ABORTED or FAILED<br/>the row is kept, unchanged otherwise"]
    F["both predicates stop matching:<br/>dataset lock released, number n freed"]
    G["dataset D survives - ACTIVE, and empty<br/>if this was its first ingest"]
    H["n is spent forever: COMMITTED stays inside<br/>one_claim_per_revision_number, and<br/>dataset_revisions holds n under a total UNIQUE"]
    I{"did step 6 rename the staging tree into<br/>the revision directory? the rename is<br/>idempotent, so the target's presence<br/>is the answer"}
    J["reconciler imports the row from the<br/>COMMITTED marker - roll forward.<br/>The number is never freed"]
    A --> B
    B --> C
    C -->|"upload, verify, rename durable,<br/>step 7 commits"| D
    D --> H
    C -->|"client aborts, admin force-aborts, or the TTL<br/>sweeper reaps, in PREPARING, UPLOADING or<br/>VERIFYING - all before the durability point"| E
    C -->|"crash or error in COMMITTING:<br/>consult storage first (contract 6)"| I
    I -->|"present: past the durability point"| J
    I -->|"proven absent"| E
    J --> H
    E --> F
    F --> G
    G -->|"retry: a whole new session,<br/>which re-derives the same n"| A
```

The loop back to `BeginIngest` is the whole point: because the allocator reads the committed set
and the freed number never entered it, the retry computes the same `n` it computed the first time.

### Deletions

`ingest_sessions_dataset_id_revision_number_key` — `0001`'s total `UNIQUE (dataset_id,
revision_number)` on `ingest_sessions`, replaced by `one_claim_per_revision_number`. Note that
`dataset_revisions` keeps its own identically-shaped total unique constraint; only the session
table's is narrowed.

Nothing else. No Python symbol, no test and no other constraint is made obsolete: `IngestLease`,
`IngestSession`, `TERMINAL_STATES` and `_TRANSITIONS` in `src/huron/pkg/catalog/ingest.py` are
untouched, because the rule is expressed entirely in the index predicate and the state machine
already forbids leaving a terminal state. `migrations/schema.sql`'s `ingest_sessions` block goes
stale, as it does for every other task; S8 owns it.

### Negative-write tests

`tests/contract/test_catalog_store.py` (introduced by S1), alongside S7's cases:

- **the retry, which is the point** — a session driven to `ABORTED`, then a new session inserted for
  the same `(dataset_id, revision_number)`: succeeds. The same again with `FAILED`, on a session
  that reached `COMMITTING` first.
- **the dead row survives** — after that retry, the `ABORTED` row is still present, still carrying
  its original `revision_number` and `revision_id`.
- **a committed number is spent** — a session committed at number `n`, then a new `PREPARING`
  session at `(dataset_id, n)`: rejected with `UniqueViolationError` naming
  `one_claim_per_revision_number`. This is the case that pins `COMMITTED` inside the predicate; a
  predicate excluding all three terminal states would pass every other test here and fail this one.
- **the dataset lock still holds** — a second live session on the same dataset at a *different*
  number: rejected, naming `one_open_ingest_per_dataset`. Asserting on the index name is what stops
  the two guarantees being mistaken for one.
- **the empty dataset** — a dataset whose only ingest aborted: still `ACTIVE`, zero revisions, and
  `coalesce(max(revision_number), 0) + 1` over `dataset_revisions` is 1.
- **gap-free, end to end** — two dead attempts at 1, a third committing 1, a fourth committing 2:
  `dataset_revisions` holds exactly `{1, 2}`.

### Rejected alternatives

- **Delete the aborted session row** — frees the number with no schema change at all, and destroys
  the record of what was attempted; `ingest_files` would cascade away with it (`ON DELETE CASCADE`),
  taking the per-file evidence of where the ingest failed. Keeping the row is Karl's decision, and
  the evidence is why.
- **Null out `revision_number` on abort** — frees the number under the existing total constraint,
  but costs `NOT NULL` on a column that always holds a real value and erases which number the
  attempt reserved, which is half of what the kept row is for.
- **Allocate over both tables (`max` across `dataset_revisions` and `ingest_sessions`)** — the other
  candidate S7 named; it makes every failed attempt burn a number permanently, which is exactly the
  gap invariant E forbids.
- **A sequence or identity column per dataset** — PostgreSQL sequences are documented to be gappy on
  rollback, which invariant E forbids, and it is one database object per dataset.

### The stranded envelope after the durability point — resolved

An earlier draft of this section flagged this for a human, as open question 1: freeing a revision
number is safe only for a session that has not yet renamed its staging tree into
`revisions/{nnnnnn}--{revision_id}`, so an abort granted after that rename frees a number the retry
then commits, and the sealed envelope can never be imported. **It is settled**, and two facts
already on the record settle it. Neither changes `0008`.

**Fact 1 — the transition map is asymmetric where the freeing predicate is not.**
`src/huron/pkg/catalog/ingest.py` line 39 reads
`IngestState.COMMITTING: frozenset({IngestState.COMMITTED, IngestState.FAILED})`. `ABORTED` is
**unreachable** from `COMMITTING`; `FAILED` is reachable. `one_claim_per_revision_number`'s
predicate `state NOT IN ('ABORTED', 'FAILED')` treats the two as equivalent, and they are not:

- An `ABORTED` session **provably never reached the durability point.** The only states that lead
  to `ABORTED` are `PREPARING`, `UPLOADING` and `VERIFYING`, every one of which precedes step 6.
  Freeing its number is unconditionally safe, always.
- A `FAILED` session **may or may not** have passed step 6, because `COMMITTING → FAILED` exists.
  Freeing its number is safe only in the first case.

**The single edge `COMMITTING → FAILED` is the entire hole.** Every other path into a
terminal-failure state departs from a state that cannot have renamed anything, so it carries no
question to answer.

**Fact 2 — the record already mandates roll-forward on that edge.** `design/layer-raw.html` §5
annotates step 6, `rename(.staging/{ingest_id}, …/revisions/{nnnnnn}--{revision_id})`, as the
**durability point**, and step 6 sits inside `COMMITTING` (steps 4–7). The same section's crash
table gives the mandated resolution per window: a crash after steps 4–5, envelope still under
`.staging/`, is "Session expires → sweeper deletes the staging dir"; a crash after step 6 is
"**Orphan commit. Reconciler imports the row from `COMMITTED`**", with "a retry of step 6 finds
staging gone and the target present → treats the rename as done (idempotent)". Invariant G states
the same rule from the other side: "Storage leads; the catalog follows — a revision row is never
published before the rename is durable." So a commit path that answers a generic error by writing
`FAILED` contradicts `design/layer-raw.html` **regardless of what any index then does with the
number**. The stranded envelope is the symptom; writing a failure state over a durable commit is
the defect.

**The resolution is a contract on the writer, recorded as § "### Explicit contracts" item 6.**
Nothing may move a session out of `COMMITTING` into a failure state without first determining
whether the rename happened. The design already specifies how to determine it — step 6 is
idempotent, so the target's presence *is* the answer — and what to do when it did: import the row
from the `COMMITTED` marker and roll forward. Only a proven-absent envelope may go to `FAILED`.
This cannot be DDL and must not be attempted as DDL: durability is a filesystem fact, and the
database never sees the filesystem.

**`0008`'s DDL is unchanged, and that is the finding rather than a concession.** A session stuck in
`COMMITTING` sits **inside** `one_claim_per_revision_number`'s predicate — `COMMITTING` is not in
`('ABORTED','FAILED')` — so it keeps holding its revision number for exactly as long as its fate is
unknown, which is exactly right, because it may be durable. The index already refuses to free a
number whose outcome nobody has established. What was missing was never the index; it was the rule
about who may end that unknowing, and on what evidence. Narrowing the predicate cannot help either,
because it cannot distinguish a durable `FAILED` from a non-durable one — that distinction does not
exist in the database.

**The failure is loud, not silent.** If the contract is violated and a durable session's number is
freed and taken by a retry, `dataset_revisions` carries its own **total**
`UNIQUE (dataset_id, revision_number)` from `0001`, so the reconciler's later import of the stranded
envelope fails on that key — proved on the live database: `duplicate key value violates unique
constraint "dataset_revisions_dataset_id_revision_number_key"`. The catalog cannot grow a second
revision 1 and stays consistent; no committed revision is lost, because the stranded envelope never
became one. What remains is one sealed envelope under `revisions/` with no row and no way to acquire
one — a disagreement between storage and catalog, which is precisely what `reconciliation_findings`
already models. `design/layer-raw.html` §9 gives the reconciler a finding for every disagreement it
cannot resolve ("Row without an envelope → DEGRADED", "Digest mismatch → DEGRADED") and states the
governing rule: it "never silently rewrites catalog history — disagreements become findings, alerts,
and report entries". The residual of a violated contract is therefore an unresolvable finding
needing manual intervention, not corruption and not silent data loss.

### Open questions

1. **Resolved — see § "### The stranded envelope after the durability point — resolved", directly
   above.** What remains is narrower than the original question and is still not a schema question:
   **who performs the storage consult, and what is written when the envelope turns out to be
   present.** The contract fixes that the check must happen and what its two outcomes mean; it does
   not fix ownership. Two shapes are viable and `0008` is correct under both: the TTL sweeper stats
   the target itself before writing any terminal state — it is already a filesystem actor and
   already keyed on terminal-or-expired sessions — or an expired `COMMITTING` session is left
   untouched for the nightly reconciler, which walks `revisions/` anyway. **Recommended: the
   sweeper performs the stat, with the reconciler as the backstop it already is.** The reconciler
   alone would leave a dataset locked and its number held until the next nightly walk, which breaks
   `design/layer-raw.html` §4's "a crashed client releases the dataset lock within the TTL"; the
   stat is one syscall on a path `pkg/catalog/paths.py` already builds. **Flagged: this is a P3
   sweeper-and-reconciler design decision, owed to the task that writes those two components.**
   Related and open on its own account: `reconciliation_findings.severity` has no vocabulary yet
   (§ "S2 — … ### Open questions" item 4), so the severity a refused orphan import should raise
   cannot be pinned here either.
2. **Considered, with a verdict: `_TRANSITIONS[COMMITTING]` should *not* be narrowed to
   `{COMMITTED}`.** Since the `COMMITTING → FAILED` edge is the entire hole, deleting it from
   `src/huron/pkg/catalog/ingest.py` is the obvious mechanical guard, and it is the wrong one:

   - **The edge is legitimate.** The reconciler must be able to move a session stuck in
     `COMMITTING` to `FAILED` once it *has* consulted storage and found no envelope. Otherwise that
     session holds the dataset lock and its revision number forever, which is the exact failure
     § "### Explicit contracts" item 3 exists to prevent. Removing the edge does not remove the need
     for that write; it removes the map's ability to describe it.
   - **So narrowing pushes the dangerous write outside the checked path.** The reconciler would
     reach for a raw `UPDATE` or a bypass around `_TRANSITIONS`, making the one transition that most
     needs supervision the one place the state machine is not consulted. An edge guarded by a stated
     contract is stronger than an edge that has been legislated out of the model and back in through
     the side door.
   - **The map cannot carry the condition that matters.** Legality of `COMMITTING → FAILED` depends
     on a filesystem fact; a `frozenset` cannot express "if and only if the rename is absent".
     Narrowing swaps an under-specified edge for an unmodelled one.

   **Recommendation: keep the edge, and constrain the call site instead.** If a mechanical guard is
   wanted beyond the contract — and one is worth having, since the whole defect is a generic error
   handler reaching a specific edge — the right shape is a transition helper that cannot take this
   edge without being handed the storage verdict: a distinct entry point (`fail_committing(session,
   *, envelope_present: bool)`, or an explicit reconciler-action argument) so that a caller holding
   only an exception has no way to spell the transition. That is a `pkg/catalog` API decision
   belonging to the P2/P3 task that writes the sweeper and the reconciler, not to `0008`, which
   neither needs it nor blocks it. **A human who prefers the narrower map must also design the
   reconciler's post-check action as a modelled transition of its own** — narrowing without that is
   a net loss.
3. **Noted, not blocking: nothing in the database enforces the transition map.** `_TRANSITIONS`
   forbids leaving a terminal state, and the freeing rule leans on that: if an `ABORTED` row could
   be walked back to `UPLOADING`, it would try to re-take a number the retry already holds.
   `one_claim_per_revision_number` and `one_open_ingest_per_dataset` would both refuse the
   resurrection, so the failure is safe rather than silent — but it fails at the index rather than
   at the illegal transition, with a message about uniqueness rather than about the state machine.
   The map lives only in `src/huron/pkg/catalog/ingest.py`, which is also why items 1 and 2 above
   are contracts and API shapes rather than DDL. Whether the schema should carry a transition guard
   of the `releases_immutable()` kind is a broader question than this task, and `0008` does not add
   one.

---

## S8 — `migrations/schema.sql` as a generated artifact (design)

### Target design

**It is a hand-maintained condensed architecture map. The `pg_dump` line is wrong and comes
out; keeping the file current becomes a mechanically checked obligation of every revision.**

Four facts decide it, and they all point the same way.

1. **The file is not a condensed `pg_dump`; it is a different document.** `pg_dump
   --schema-only` emits every index, every constraint by its generated name, the partition
   children, and the full `plpgsql` bodies of `releases_immutable`, `service_accounts_kind_guard`
   and `role_binding_guard`. `migrations/schema.sql` contains **zero** `CREATE INDEX` statements
   against the six the revisions create, names no constraint, and reduces each trigger to one
   line of intent (`-- trigger releases_immutable: every column except withdrawal is frozen;
   a wrong tag is withdrawn (tombstone), never repointed.`). 351 lines against the ~1,500 a dump
   would produce. The gap is not compression — the map answers "what is the shape and why", the
   dump answers "what exactly is installed". Only one of those questions is already answered
   elsewhere: `migrations/versions/` is the exact installed truth, and a dump would be a third
   copy of it with no reader.
2. **The prose is load-bearing for six of the seven sibling tasks.** S1, S2, S3, S4, S5, S6 and
   S7 each record that a named *block* or *annotation* of this file goes stale — "the
   `lifecycle_state`, `state` and `severity` lines gain or conspicuously lack a vocabulary
   comment" (S2), "the index list and the FK annotations both" (S4), "`-- partitioned by
   created_at range` … must change either way" (S6). S4 goes further and *discharges* a finding
   against it: it declines to respell twenty-one foreign keys with explicit `ON DELETE NO ACTION`
   because "this table and the regenerated `migrations/schema.sql` deliver [the documentation
   property] instead". A `pg_dump` artifact cannot carry any of that, and S4's rejection would
   have to be reopened.
3. **The rest of the repository already made this decision; only the file's own header
   dissented.** `docs/getting-started/local-development.md` line 125 says "`migrations/schema.sql`
   is a hand-maintained summary of the whole metastore for reading — it is documentation and is
   never executed." `docs/getting-started/repository-layout.md` line 9 says "schema.sql is a
   read-only summary of the whole metastore". Nothing in `src/huron/`, `tests/`, `migrations/env.py`,
   `migrations/_ddl.py`, `alembic.ini`, `Makefile` or `.pre-commit-config.yaml` reads, executes,
   diffs or generates the file. The `pg_dump` line describes a provenance no part of this
   repository has ever had.
4. **Generation has nowhere to run.** A dump needs a migrated database — `make up` then
   `make migrate` against `postgresql://huron:huron@localhost:5433/huron`, which `alembic.ini`
   hard-codes. There is **no `.github/workflows/` directory in this repository**, and every hook
   in `.pre-commit-config.yaml` is a database-free `uv run` static check. So a generation script
   would run on one developer's laptop, against whatever head that laptop's database happens to
   sit at, and nothing anywhere could verify its output was current. "Generated" would be exactly
   as manual as hand-maintenance, plus a script asserting otherwise — and `pg_dump`'s output is
   server-version- and locale-sensitive, so the committed result would also diff between
   contributors for reasons unrelated to the schema.

The header's enumerated migration list (`0001_foundations … 0005_auth`) is deleted rather than
extended. An enumeration duplicates `ls migrations/versions/` and must be edited on every
revision — which is precisely the edit that was skipped twice. It is replaced by a **single
`Reflects:` line naming the Alembic head the map was last written against**, which is one token,
is what a reader actually wants to know, and is mechanically comparable to the real head without
a database.

#### Exact header text

The file opens with exactly this, replacing lines 1–12 of the current file (the `0006`/`0007`
body content the map already carries is unaffected; only the banner changes):

```sql
-- ============================================================================
-- Huron metastore: table architecture summary
-- ============================================================================
-- HAND-MAINTAINED DOCUMENTATION. Not executed, and not generated: this is a
-- condensed map of what the Alembic revisions under migrations/versions/ build,
-- and the authoritative DDL is those revisions, never this file. The map exists
-- to carry what a schema dump cannot - the trigger annotations, the vocabularies,
-- and the invariant each rule serves. Do not replace it with pg_dump output.
--
-- Reflects: 0007_roleless_service_accounts
--
-- Every revision that changes the schema updates this file in the same commit
-- and moves the Reflects line to the new head. scripts/check_schema_map.py
-- fails when that line is not the Alembic head; it runs in `make lint` and as a
-- pre-commit hook.
--
-- Scope: every table and column appears, with types condensed. A constraint
-- appears where it carries a design rule; indexes and triggers appear as
-- `-- index ...` / `-- trigger ...` annotations inside the table block they
-- serve, never as standalone DDL. PostgreSQL structural state only - no
-- metadata mirrors, no text search (invariant A: LanceDB owns matching;
-- sidecars authoritative).
-- ============================================================================
```

When `0008` lands, `Reflects:` reads `0008_<slug>` — the same string as that revision module's
`revision =` value, which in this repository always equals its filename stem.

### Explicit contracts

**The obligation.** A revision that changes the schema is not complete until
`migrations/schema.sql` reflects it and the `Reflects:` line names that revision. This is a
property of the commit, not of anyone's memory.

**How it is enforced.** `scripts/check_schema_map.py`, a database-free check:

- It reads the head from the revision files themselves —
  `ScriptDirectory.from_config(Config("alembic.ini")).get_current_head()`, which parses
  `migrations/versions/` and never opens a connection or executes `env.py`.
- It reads the `Reflects:` line from the first 30 lines of `migrations/schema.sql`.
- It exits non-zero, printing both values, when they differ; when the line is absent or
  malformed; or when `get_current_head()` raises because the revision graph has more than one
  head (a branchpoint is itself a defect here, since `0008` extends a linear chain).

**What invokes it.** A new line in `make lint`, whose four existing lines are the repository's
declared static-check set, plus a mirrored `schema-map-current` hook in `.pre-commit-config.yaml`
(`entry: uv run python scripts/check_schema_map.py`, `language: system`, `pass_filenames: false`,
`files: ^migrations/`). Every one of the four existing hooks is also a `make lint` line; this
preserves that 1:1 correspondence. `make lint` is the guarantee — `pre-commit` is not a declared
dependency in `pyproject.toml`'s `dev` group and is not documented anywhere, so the hook is an
early warning for developers who have installed it, not the enforcement. When a CI workflow is
added it runs `make lint` and inherits the check with no extra wiring and **no database service**,
which is the concrete advantage of a stamp comparison over a dump diff.

**What the check guarantees, and what it does not.** It guarantees the file cannot be left
untouched by a change that adds a revision: the stamp can only be made current by editing
`migrations/schema.sql` in the same change, which puts the map's diff in front of the reviewer
next to the migration's diff. It does **not** and cannot prove the body is accurate — no
database-free check can. That limit is stated here rather than papered over; the check kills the
drift class that actually occurred (a header stranded behind the head, twice) and forces human
review of the rest.

**How a reviewer tells it was not updated.** Two ways, both one glance. Mechanically: `make lint`
fails with the two revision ids printed. By eye: the last entry of `ls migrations/versions/` and
the `Reflects:` line must be the same string, and a schema-touching commit whose diff does not
include `migrations/schema.sql` is incomplete on its face.

**What this obligates in `0008`.** `0008` is a schema change, so it carries the map update: the
new header above, the seven sibling tasks' block edits (S1 `releases`/`dataset_revisions`,
S2 the `lifecycle_state`/`state`/`severity` vocabularies, S3 the `kind` annotations, S4 the index
and FK-action annotations, S5 the jsonb shape annotations, S6 the rebuilt `audit_events` without
`-- partitioned by created_at range`, S7 the `ingest_sessions` block), and `Reflects: 0008_<slug>`.
The map update is part of `0008`'s change, not a follow-up.

### Deletions

From `migrations/schema.sql`'s header only — the body is edited by the sibling tasks, not by this
one:

- **The words "GENERATED DOCUMENTATION"** — false, and the source of the confusion.
- **The `pg_dump --schema-only --no-owner huron` regeneration instruction** (two lines) — it names
  a procedure that does not produce this file and never did.
- **The enumerated migration list `(0001_foundations, 0002_rbac, 0003_layer_paths,
  0004_entry_layers, 0005_auth)`** — replaced by the single `Reflects:` head line.

Nothing else in the repository is deleted or changed by this decision. `docs/getting-started/
local-development.md` and `docs/getting-started/repository-layout.md` already describe the file as
hand-maintained read-only documentation and stay correct verbatim. No application code, `pkg/`
symbol, test or migration references the file.

### Rejected alternative

**Make it genuine `pg_dump --schema-only --no-owner` output owned by a script under `scripts/`** —
it deletes the design rationale that six sibling tasks depend on and that S4 explicitly relies on
to discharge a finding, in exchange for a fidelity guarantee it cannot actually deliver, because
the dump requires a migrated database that only a developer laptop (compose on host port 5433)
provides and no CI exists to verify against.

### Open questions

**None.** The `Reflects:` stamp format, the check's location and its two invocation points are all
settled above; the only judgement left to the planning phase is `0008`'s revision slug, which the
stamp copies verbatim from that revision module's `revision =` value.

---

## Phase 0 grill — database documentation (2026-08-31)

Scope: the documentation record *about* the database, not the DDL. `schema_audit.md` (F1–F8) and
the design records S1–S8/S7a above are established and are not re-derived here. The settled
decisions — dropping `audit_events` partitioning, the abort/retry partial unique index
`one_claim_per_revision_number`, and `migrations/schema.sql` staying hand-maintained with a
`Reflects:` stamp — are treated as closed.

**Authority order used.** `CLAUDE.md` and `README.md` put `design/` first ("the authoritative
architecture record"; "where code and design disagree, the design wins"); `design/roadmap.html`
carries plan *and* status (`done` / `partial` / `todo`) and is the only status copy, per
`docs/backend-design.md` § "Where build status lives"; `docs/` is repository documentation and is
derived; `migrations/versions/*.py` docstrings are authoritative for what each revision installs;
`migrations/schema.sql` is a derived map; `site/` is retired build output and was not read.
`AUTH_IMPLEMENTATION_PLAN.md` and `RBAC_IMPLEMENTATION_PLAN.md` are historical records of shipped work.

**Method.** Migrations `0001`–`0007` were extracted (`ast.literal_eval` of each module's single
`DDL` string) and applied in order to a scratch PostgreSQL 16.13 with `psql -v ON_ERROR_STOP=1`.
Every claim below was checked against that live database by catalog query or by a write the
documentation implies should be refused. Where a claim could only be checked against another
document, that is said explicitly.

### Drift 6 — the authoritative schema sketch asserts CHECK constraints that were never created

**Claim.** `design/catalog-search.html` §2 "PostgreSQL schema (delta)":
`datasets(… lifecycle_state CHECK IN ('ACTIVE','RETIRED','SUPERSEDED') …)`,
`dataset_revisions(… state CHECK IN ('COMMITTED','EXPIRED_PARTIAL','EXPIRED','PURGED','DEGRADED') …)`,
`snapshots(… state CHECK IN ('CANDIDATE','PUBLISHED','SUPERSEDED','FAILED') …)`,
`product_versions(… status CHECK IN ('CANDIDATE','PUBLISHED','STALE','SUPERSEDED','WITHDRAWN') …)`,
`jobs(… kind CHECK IN ('bronze_build','canonicalize','product_run','validate','polaris_sync','retention','reconcile') …)`.

**Reality.** `select conname, pg_get_constraintdef(oid) from pg_constraint where contype='c'`
against the migrated database returns 56 CHECK constraints and **none** of these five. There is no
CHECK on `datasets.lifecycle_state`, `dataset_revisions.state`, `snapshots.state`,
`product_versions.state` or `jobs.kind`. (`product_versions` has no `status` column at all — the
column is `state`.) This is the design-record half of **F2**, which proved the same thing from the
write side: `UPDATE datasets SET lifecycle_state = 'BANANA'` succeeded.

**Class.** Code has diverged — the design states the intended vocabulary and the design wins.

**Consequence.** Highest-value finding in this pass, and it changes S2/S3 from open design
questions into transcription: the authoritative document already fixes four of the five
vocabularies, so S2 must adopt them rather than invent them, and any deviation (for example
`datasets.lifecycle_state` no longer needing `DRAFT` after `0006`, which the working tree already
edited out of this same sketch) is a design change that belongs back in `catalog-search.html`.
`jobs.kind` is the one S3 must still settle, and the sketch's seven values are the starting set.

### Drift 7 — the derived-layer registry in the authoritative design was never built as described

**Claim.** `design/catalog-search.html` §2 declares a `layer_repos` table
(`layer_repos(id PK, layer CHECK IN ('bronze','silver','gold'), dataset_id FK NULL, project_id FK
NULL, product_id FK NULL, bucket, prefix, UNIQUE (dataset_id, layer), …)`) and a `snapshots` table
keyed to it: `snapshots(id PK, repo_id FK, icechunk_snapshot_id, tag, state …, source_revision_id
FK NULL, contract_version NULL, validation_evidence jsonb, built_by_job FK, published_at, …)`.

**Reality.** `select to_regclass('public.layer_repos')` → `NULL`; the table does not exist and no
migration creates it. The shipped `snapshots` is
`(id, dataset_id, layer, repo_uri, snapshot_id, state, provenance, validation_evidence,
published_at)` — the repository is an inline `repo_uri` text column, not a foreign key to a
registry, and `tag`, `source_revision_id`, `contract_version` and `built_by_job` do not exist;
their information now lives inside the `provenance` jsonb document, which `0004` constrained.
`layer_repos` is named in exactly one file in the repository (`design/catalog-search.html`).

**Class.** Documentation is wrong. This is **not** "not yet built": `snapshots` shipped in `0001`
and was reshaped by `0003` and `0004`, so the design describes a superseded plan for a table that
exists, rather than a future table.

**Consequence.** A design pass reading `catalog-search.html` for the derived-layer model would plan
against a registry table and a `repo_id` join that do not exist, and would miss that
snapshot-to-source linkage is a jsonb document under a CHECK rather than a foreign key — which is
precisely the surface S1 (cross-parent integrity) and S5 (jsonb shape) touch.

### Drift 8 — five more tables in the schema sketch do not match what shipped

**Claim.** `design/catalog-search.html` §2, same code block:
`role_bindings(id PK, principal_type, principal_name, role, scope CHECK IN (…), organization_id
NULL, project_id NULL, dataset_id NULL, effect …)`;
`api_keys(id PK, principal_subject, key_id UNIQUE, secret_hash, name, scopes text[],
project_ids uuid[] NULL, …)`;
`idempotency_records(principal_subject, operation, key, request_sha256, response_status,
response_body, PK (principal_subject, operation, key))`;
`jobs(… subject_kind, subject_id, state, attempts, claimed_by, claimed_at, container_digest,
failure jsonb, …)`;
`lineage_edges(id PK, from_kind, from_id, to_kind, to_id, region jsonb NULL, …)`;
`ingest_files(… action …, state, observed_sha256, completed_parts jsonb, …)`;
`retention_holds(… placed_by, placed_at, released_at NULL)`.

**Reality.** Column lists read from `pg_attribute` on the migrated database:

| Table | Shipped columns |
|---|---|
| `role_bindings` | `id, principal, role_code, scope_type, scope_id, effect, conditions, expires_at, created_by, created_at` |
| `api_keys` | `id, key_id, owner_subject, name, secret_sha256, scopes, project_id, expires_at, last_used_at, revoked_at, created_at, owner_kind` |
| `idempotency_records` | `principal, key, request_sha256, status_code, response, created_at, expires_at` (PK `(principal, key)`) |
| `jobs` | `id, kind, subject_id, image_digest, state, payload, attempts, available_at, claimed_at, completed_at, created_at` |
| `lineage_edges` | `id, upstream_kind, upstream_id, downstream_kind, downstream_id, region, created_at` |
| `ingest_files` | `file_id, ingest_id, path, size, expected_sha256, action, state, completed_parts` |
| `retention_holds` | `id, scope_kind, scope_id, kind, reason, created_by, created_at, released_at` |

`role_bindings` collapsed three scope columns into `(scope_type, scope_id)` and two principal
columns into one prefixed `principal` (this is what `0002` shipped and what
`RBAC_IMPLEMENTATION_PLAN.md` §R4 documents); `api_keys.project_ids uuid[]` became a single
`project_id` FK; `idempotency_records` has no `operation` column, so its PK is two columns, not
three; `jobs` has no `subject_kind`, `claimed_by` or `failure`, and `container_digest` is
`image_digest`; `lineage_edges` uses `upstream_*`/`downstream_*`, not `from_*`/`to_*`;
`ingest_files` has no `observed_sha256`; `retention_holds` uses `created_by`/`created_at`.

**Class.** Documentation is wrong (the shapes were deliberately settled in `0001`/`0002`/`0003`).

**Consequence.** `catalog-search.html` §2 calls itself a "Skeleton — the Alembic migrations are the
source of truth", so a careful reader is warned; but the sketch is the only *narrative* account of
the schema in the authoritative design record, and it is wrong about the primary key of one table,
the cardinality of one relationship, and the column names of three more. Any design or query
written from it needs correcting before it compiles.

### Drift 9 — the schema map omits the unique constraint the abort/retry decision turns on

**Claim.** `migrations/schema.sql` §2, the `ingest_sessions` block, lists in full:
`id uuid PRIMARY KEY`, `dataset_id uuid NOT NULL REFERENCES datasets`,
`revision_id uuid UNIQUE NOT NULL, revision_number integer NOT NULL`, … followed by one trailing
comment, `-- partial unique index: at most ONE open ingest per dataset (per-dataset lock)`.

**Reality.** The shipped table carries a *total* `UNIQUE (dataset_id, revision_number)`
(`ingest_sessions_dataset_id_revision_number_key`, created by `0001`), which the map never shows.
Comparing every `pg_constraint` row of `contype='u'` against the map, this is the **only** unique
constraint in the database that `schema.sql` does not represent — every other one is present
inline or as a `UNIQUE (…)` clause.

**Class.** Documentation is wrong.

**Consequence.** Direct and immediate: this constraint is the reason a retry after an `ABORTED`
session collides, which is what S7a and `design/roadmap.html` §2's `0008` row describe
("under the total unique constraint `0001` shipped, the retry was refused outright"). A reader
working from the schema map alone cannot see the constraint the fix replaces, and would read the
`one_open_ingest_per_dataset` comment as the only uniqueness rule on the table.

### Drift 10 — the schema map calls `dataset_revisions` immutable and gap-free; the database enforces neither

**Claim.** `migrations/schema.sql` §1: `CREATE TABLE dataset_revisions (      -- linear, gap-free, immutable`.

**Reality.** No trigger exists on `dataset_revisions` (`select … from pg_trigger where
tgrelid='dataset_revisions'::regclass and not tgisinternal` returns 0 rows) and no constraint
enforces contiguity. Against the migrated database, with one revision numbered 1 present:

- `UPDATE dataset_revisions SET manifest_sha256 = repeat('c',64), revision_number = 7 WHERE revision_number = 1;` → `UPDATE 1`
- `INSERT INTO dataset_revisions (… revision_number …) VALUES (…, 99, …);` → `INSERT 0 1`

leaving revisions `{7, 99}` for that dataset — a mutated digest, a renumbered revision, and a gap.
The only rules present are `UNIQUE (dataset_id, revision_number)`, `UNIQUE (dataset_id,
manifest_sha256)`, and a `1..999999` range CHECK.

**Class.** Documentation is wrong — about what the *database* does. The property itself is real
design intent (invariant E, `design/architecture.html` §5; `design/layer-raw.html` §4), enforced by
the application under the per-dataset ingest lock.

**Consequence.** Two tables above it in the same file, `releases`, carries the comment
`-- trigger releases_immutable: every column except withdrawal is frozen`, and that trigger does
exist and does fire (verified). The asymmetry teaches the reader that bare adjectives in this file
mean database enforcement. A design that assumed `dataset_revisions` is DB-immutable would skip
exactly the guard that is missing.

### Drift 11 — the schema map contains no index at all

**Claim.** `migrations/schema.sql` header: "Huron metastore: table architecture summary … Types/
constraints below are condensed; CHECKs are shown where they carry a design rule."

**Reality.** The file contains **zero** `CREATE INDEX` statements and mentions two of the six
non-constraint indexes the migrations create, both only in prose: `one_open_ingest_per_dataset`
(§2) and `sessions_subject_active` (§3). `jobs_claim`, `outbox_unprocessed`,
`role_bindings_principal_scope` and `policy_attachments_scope` appear nowhere in the file. Live
list: `select indexrelid::regclass from pg_index … where not exists (select 1 from pg_constraint
where conindid = indexrelid)` → six rows.

**Class.** Documentation is wrong (by omission of a whole category).

**Consequence.** F3 (nine unindexed FK columns) and F4 (the scope-listing query with no usable
index) are both invisible from the schema map — a reader cannot tell which access paths are
supported, and the map cannot be used to review an index decision. This is the concrete gap S8's
`Reflects:` stamp does not by itself close: a stamp proves the file matches a revision, not that
the file represents indexes at all.

### Drift 12 — the RBAC document's example binding is refused by the database

**Claim.** `design/rbac.html` §4, immediately after "Bindings live in `role_bindings` (scope
`SYSTEM | ORGANIZATION | PROJECT | DATASET`) with conditions and expiry:"

```json
{"principal": "group:mcnp-analysts", "role": "developer",
 "scope_type": "project", "scope_id": "project-41", "effect": "allow",
 "conditions": {"maximum_classification": "internal",
                "expires_at": "2027-01-01T00:00:00Z"}}
```

**Reality.** Inserting that row into the migrated database fails:

```
INSERT INTO role_bindings (…, scope_type, …, effect, …) VALUES (…,'project',…,'allow',…);
ERROR:  role developer cannot be bound at project scope
CONTEXT:  PL/pgSQL function role_binding_guard() line 26 at RAISE
```

`roles.bindable_scopes` stores `{ORGANIZATION,PROJECT,DATASET}` and the guard compares case
sensitively; had it passed the guard, `role_bindings_scope_type_check` and
`role_bindings_effect_check` both require the upper-case spellings. The example also nests
`expires_at` inside `conditions` while the table has its own `expires_at` column.

**Class.** Documentation is wrong.

**Consequence.** Low-to-moderate and cheap to fix, but the sentence introduces the example as what
a binding *is*, and the case convention is the kind of thing a client author copies verbatim.

### Drift 13 — the schema map hides the partitioning of `audit_events`

**Claim.** `migrations/schema.sql` §6:
`CREATE TABLE audit_events (            -- partitioned by created_at range` followed by a plain
column list ending `PRIMARY KEY (id, created_at)`.

**Reality.** The shipped object is `PARTITION BY RANGE (created_at)` with exactly one child,
`audit_events_default PARTITION OF audit_events DEFAULT` — the 32nd relation in the database and
the only table the map does not name. The map shows neither the `PARTITION BY` clause nor the
default child, so the structure F6 and S6 are about is not visible in it.

**Class.** Documentation is wrong.

**Consequence.** Low today, because S6 already decided to drop the partitioning, but it is the
same category as Drift 11: the map represents columns and constraints and silently drops storage
structure, so it cannot be used to review that class of decision.

### Drift 14 — the schema map drops `DEFAULT 1` from five counter columns

**Claim.** `migrations/schema.sql` §1 and §2 declare `generation integer NOT NULL` and
`version integer NOT NULL` for `organizations`, `projects` and `datasets`, and
`etag integer NOT NULL` for `ingest_sessions`, with no default.

**Reality.** All five carry `DEFAULT 1` in the database (`pg_attrdef`:
`datasets.generation`, `datasets.version`, `organizations.generation`, `organizations.version`,
`projects.generation`, `projects.version`, `ingest_sessions.etag`). Comparing every default in the
database against the map, these are the only ones the map omits — the other 24 (`lifecycle_state`,
`state`, `owner_kind`, `conditions`, `completed_parts`, `attempts`, …) are all shown.

**Class.** Documentation is wrong.

**Consequence.** Cosmetic to a reader, but it is a counter-example to the map's implicit promise
that a shown column list is complete; ranked last of the map findings.

### Addition to Drift 4 — `docs/` and `schema.sql` say opposite things about the same file

Drift 4 above already records that `schema.sql`'s header names `0001`–`0005` and prescribes
`pg_dump --schema-only --no-owner huron`. Two further facts, both new:

- **The prescribed command was verified not to produce the file.** Run against the migrated
  database, `pg_dump --schema-only --no-owner huron` emits 1381 lines beginning with a `\restrict`
  preamble and `CREATE TABLE public.api_keys (…)` in alphabetical order; `schema.sql` is 351 lines,
  thematically ordered under six ASCII section banners, with prose comments and `-- trigger …`
  annotations. No `Makefile` target regenerates it and `make lint` does not check it, so the
  instruction has never been executed.
- **The repository already contradicts its own header.** `docs/getting-started/local-development.md`:
  "`migrations/schema.sql` is a hand-maintained summary of the whole metastore for reading — it is
  documentation and is never executed." `docs/getting-started/repository-layout.md`:
  "Alembic; schema.sql is a read-only summary of the whole metastore." The derived `docs/` pages
  are correct and the file's own header is the false one — so S8 is correcting the header toward
  what `docs/` already says, and needs to touch nothing in `docs/`.

### Drift 15 — low: stale specifics in the two historical plans

**Claim.** `RBAC_IMPLEMENTATION_PLAN.md` §R4 (`✅ implemented, applied on PG16`):
"Verified rejections: pipeline→user, platform_owner→ORGANIZATION scope, bad prefix, exact
duplicate" and "`migrations/schema.sql` is the human-readable summary of the whole metastore
(0001+0002, all six sections)". `AUTH_IMPLEMENTATION_PLAN.md` §A5 is titled "Migration `0004_auth` +
`migrations/schema.sql`".

**Reality.** The `pipeline` role was deleted by `0007` (`select code from roles` returns exactly
`developer, organization_admin, platform_owner, project_admin, reader`), so that negative case can
no longer be reproduced as written; `schema.sql` now spans `0001`–`0007`; and the auth migration
shipped as `0005_auth`, not `0004_auth` (`0004` is `0004_entry_layers`).

**Class.** Documentation is wrong, in records of completed work.

**Consequence.** Nearly none — both files are history, and `RBAC_IMPLEMENTATION_PLAN.md`'s
capability matrix was already corrected for `0007` in the working tree and now matches the seeded
`role_capabilities` rows exactly, row for row and scope for scope (verified against the migrated
database). Recorded only so a future reader tracing "which trigger rejected what" is not sent after
a role that no longer exists. The matrix does omit two of the seventeen seeded capabilities,
`dataset.discover` and `user.manage`.

### Drift 16 — low: the schema sketch no longer names a table that exists

**Claim.** `design/catalog-search.html` §2 previously listed
`science_profiles / extension_schemas(namespace, version, document, state, …)`. The working tree
replaced that entry with the new `schema_registry` block.

**Reality.** `science_profiles(name, version, document, document_sha256, published_by,
published_at)` exists in the database, created by `0001`; `schema_registry` does not exist.

**Class.** Documentation is wrong (by omission), and it is an in-flight edit — `git diff
design/catalog-search.html` shows the substitution was made today alongside the schema-registry
decision.

**Consequence.** Low, and it resolves itself when P5 lands. Noted only so the substitution is a
recorded choice rather than an accident: today the authoritative sketch names a future table and
no longer names the shipped one, and `migrations/schema.sql` §4 is the only place
`science_profiles` is documented.

### Explicitly not drift

- **`schema_registry`** (`design/catalog-search.html` §2 and its new "The schema registry" section,
  and the link added to `design/architecture.html` §1's PostgreSQL row). `design/roadmap.html` §2
  **P5 — Governance** is tagged `partial`, lists "the unified schema registry (decision 16)" among
  its deliverables, and says in the same row "The amendment fold and field allow-list are
  implemented (`pkg/catalog/amendments.py`); **the rest is not started**." The table's absence is
  the roadmap working correctly.
- **`audit_events` as "a plain append-only table: PRIMARY KEY (id), one btree on (created_at, id)"**
  (`design/catalog-search.html` §2). The same parenthetical names `0008` as what makes it so, and
  `design/roadmap.html` §2's "Schema conformance — `0008`" row is tagged `todo`. Forward statement,
  correctly marked.
- **Everything `design/rbac.html` §2 files under "Design intent not yet built"** — raw-payload read
  as a capability distinct from dataset read, and classification-gated discovery. Marked, deferred,
  no capabilities in the seeded vocabulary. Correct.
- **`pkg/metastore/`** — already recorded as Drift 2 above; not re-derived.

### Checked, no drift found

Each of these was checked against the migrated PostgreSQL 16, by catalog query or by a write the
document implies should be refused, not by comparison with another document.

- **All seven migration docstrings.** Every invariant they claim to install is installed and fires:
  `0002` — `role_bindings_guard` refuses a role bound outside `roles.bindable_scopes`
  (`ERROR: role reader cannot be bound at SYSTEM scope`), `service_account_kind_guard` refuses a
  `service_accounts` row pointing at a non-service-account principal; its "a contract test compares
  the two against a migrated database" is real (`tests/contract/test_rbac_store.py:137
  _assert_seed_matches_roles`, read not run — it needs a Docker daemon).
  `0003` — `products_dataset_project_fk` composite FK present; `snapshots_dataset_required_below_gold`
  refuses a silver snapshot with a NULL `dataset_id`.
  `0004` — `datasets.entry_layer` defaults to `raw` and its CHECK excludes `gold`;
  `snapshots_provenance_states_an_origin` refuses `provenance = '{}'`, and
  `snapshots_gold_is_never_an_entry_layer` refuses a gold snapshot claiming `promotion`.
  `0005` — `local_credentials_kind_guard` refuses a password on a service-account principal;
  `sessions_check` is verbatim `CHECK (idle_expires_at <= absolute_expires_at)`; `secret_sha256`
  carries the `^[0-9a-f]{64}$` CHECK; `user.manage` is held by `platform_owner` and no other role.
  `0006` — no `data_steward` row in `roles`; `datasets.lifecycle_state` defaults to `'ACTIVE'`;
  `projects.dataset_creation_mode` is gone.
  `0007` — no `pipeline` or `ingest_pipeline` row; every remaining role has
  `allowed_principal_kinds = {user}`; no `role_capabilities` row pairs `data.write` with `silver`
  or `gold` (`developer` is the only holder, at `{raw,bronze}`); binding an `sa:` principal fails
  with `ERROR: service accounts hold no roles; their authority is intrinsic`.
- **`design/auth.html` §2 and §5.** The session model's database half is exactly as described.
- **`design/rbac.html` §2, §3, §6 and §8.** The five roles, their capabilities, their bindable
  scopes and the roleless-service-account rule all match the seed row for row. "Datasets are ACTIVE
  on creation" matches the `0006` default. The §4 example is the one exception (Drift 12).
- **`design/layer-raw.html` §4 and §6.** "one open ingest session per dataset (partial unique index
  in PostgreSQL)" — `one_open_ingest_per_dataset UNIQUE (dataset_id) WHERE state <> ALL
  (ARRAY['COMMITTED','ABORTED','FAILED'])`. "a *different* one approves (enforced by a database
  CHECK constraint, not convention)" — `purge_records_check`. The seven-state session machine
  matches `ingest_sessions_state_check` exactly.
- **`design/architecture.html` §5 invariants J, M and N.** J holds by construction post-`0007`
  (query above); M is enforced by `releases_immutable`, which freezes every column except
  `withdrawn_at`/`withdrawn_reason` and was verified to fire; N is enforced by `0004`'s two
  provenance CHECKs.
- **`design/roadmap.html` §2, the P1 withdrawal note and the "Schema conformance — `0008`" row.**
  Both accurately describe the shipped `audit_events` shape and the `0008` scope, including the
  total unique constraint on `ingest_sessions`, which is present as stated.
- **`design/roadmap.html` §3, milestone 3.** Drift 3 above (the "8 roles" / "DB-trigger-enforced"
  sentence) is **already corrected in the working tree** — the row now reads "exactly the five roles
  of RBAC" and "service-account-free by construction rather than by trigger". Verified against the
  seed; Phase 5 has nothing left to do on that item.
- **`migrations/schema.sql` at column level.** Every table but the partition child `audit_events_default`
  is present; a column-by-column diff against `pg_attribute` found exactly one omission
  (`capabilities.description`); every unique constraint but one (Drift 9) and every foreign key,
  including the `0003` composite, is represented; the NOT NULL and default declarations match apart
  from Drift 14. The map's *content* is in good shape — its problems are categorical omissions
  (indexes, partitioning) and a false header, not per-column inaccuracy.
- **`design/index.html`, `docs/index.md`, `docs/backend-design.md`, `docs/getting-started/testing.md`,
  `README.md`.** No falsifiable claim about the database structure that the database contradicts.

### Judgment — is the database documentation adequate? (goal 3)

**This is a judgment, not a drift finding.** No: a reader who needs to understand the Huron
database today has three artifacts and no fourth, and the gap between them is a specific one.

What exists. `migrations/schema.sql` is a good map of *columns and constraints* and, at that level,
is accurate (see the clean list). The seven migration docstrings are unusually good — each explains
why a change exists and what invariant it installs, and every one of those claims survived checking.
`design/catalog-search.html` §2 is the only narrative account of the schema, and Drift 6/7/8 show it
has not tracked `0001`–`0007`.

The gap is not coverage; it is that **nothing states which invariants the database enforces and
which the application enforces.** That single missing distinction produced three of the findings
above and two of the eight audit findings:

- `schema.sql` writes `-- linear, gap-free, immutable` over `dataset_revisions` (nothing enforced)
  two tables after `-- trigger releases_immutable: …` over `releases` (fully enforced) — same
  register, opposite reality (Drift 10).
- `catalog-search.html` §2 writes `CHECK IN (…)` for five vocabularies that only the application
  restricts (Drift 6), which is F2.
- `architecture.html` §5's invariant list is the closest thing to an enforcement register, but it is
  about the *system*: E (contiguous revision numbers) is application-enforced, M (release
  immutability) is a trigger, N (snapshot origin) is a CHECK, J is now structural, and the document
  distinguishes none of them.
- F8 (`ingest_sessions.revision_id` with no FK) is exactly this shape: a deliberate choice, made for
  a real reason, recorded nowhere until the audit found it by inserting a dangling UUID.

What should exist and does not: one register, in the authoritative design record, mapping each
database-level invariant to its enforcement mechanism (constraint, trigger, index, or "application
only, and why"). `design/architecture.html` §5's invariant table is the natural place — it already
enumerates A–N and already promises each has an acceptance test — and it costs one column. The
alternative home is a "what the database enforces" subsection of `catalog-search.html` §2, which
would keep the schema narrative and the enforcement story in one file.

The second, smaller gap: **`design/catalog-search.html` §2 has no rule that keeps it current.**
`schema.sql` is about to get a `Reflects:` stamp that `make lint` checks (S8), and the RBAC seed is
pinned by a contract test — but the sketch that Drift 6/7/8 are about has neither, and it is the
document the design phase reads first. Whatever S8 lands should say, in one line, whether
`catalog-search.html` §2 is expected to track migrations or is explicitly a conceptual model that
does not; today it silently claims to be the former.

Neither belongs in `0008`. Both belong in Phase 5's roadmap reconciliation or a small follow-up,
and are recorded here because they are the answer to goal 3.

### Could not be checked

- **`tests/contract/test_rbac_store.py`** was read, not run: it requires a Docker daemon
  (`testcontainers`), which this environment does not have. Its seed-versus-`ROLES` assertions were
  instead confirmed indirectly — the seeded rows were compared against
  `RBAC_IMPLEMENTATION_PLAN.md`'s capability matrix and matched exactly — but that is a
  document-level check and is reported as such, not as verification of the test.
- **`src/huron/pkg/rbac/roles.py` as "the source of truth" for the seed** (claimed by five migration
  docstrings) is a claim about two artifacts agreeing; it was checked one way only, from the
  migrated database's seed rows. Running the contract test is the check that closes it.
- **Adjacent, out of scope:** the design record's own document count is stated three ways —
  `README.md` "Thirteen", `docs/getting-started/repository-layout.md` "13", `docs/backend-design.md`
  and `docs/index.md` "fourteen" (with a fourteen-row table) — against fifteen `design/*.html` files
  in the working tree, `workflows.html` being untracked and absent from every list. Not a database
  claim; flagged once so Phase 5 can pick it up if it wants it.

---

## S9 — The enforcement record (design)

The grill's goal-3 judgment: coverage is fine, and **nothing states which invariants the database
enforces and which the application enforces.** That single absence produced Drift 6 (five
`CHECK IN (…)` lists asserted in the authoritative design, none installed), Drift 10 (`-- linear,
gap-free, immutable` over a table with no rule of any kind), the undistinguished mechanisms behind
`design/architecture.html` §5's invariant list, and audit findings F2 and F8. The shape of every one
of them is the same: a property was asserted in a register where assertion and installed fact are
written identically, so nobody could see that nothing was behind it.

Drift 12 — `design/rbac.html` §4's example binding, which the live guard and two CHECKs refuse — is
**not** in scope here and is not closed by this task. It is a wrong example, not an unmarked
enforcement claim; an example is not a rule line and carries no marker. It belongs with the other
content corrections named under *Explicit contracts* below.

This task does not add a register. It changes the grammar of the two documents that assert
database properties, so that **an enforcement claim cannot be written without saying who refuses
the violating write.** An omission becomes an assertion, and reviewers catch assertions.

### Target design

#### Where it lives

Four edits, one owner, one vocabulary defined once.

1. **`design/catalog-search.html` §2** gains `<h3 id="enforcement">What the database enforces</h3>`,
   placed immediately after the skeleton `<pre>` and immediately before the existing
   `<h3 id="schema-registry">` — the same structural slot that subsection already occupies. It
   holds the legend, the reader contracts, the currency rule, and the residue table.
2. **The `<pre>` skeleton itself** gains a marker on every line that states a rule. This is the
   half that matters: the skeleton is what a reader reads, and a legend three screens away does
   not stop `CHECK IN ('ACTIVE','RETIRED','SUPERSEDED')` from being read as installed.
3. **`design/architecture.html` §5** gains one sentence under the heading and **no new column**
   (see below).
4. **`migrations/schema.sql`** adopts the same three markers for its own `--` annotations, via one
   paragraph added to the header S8 already rewrites. This is where Drift 10 is fixed.

**Why `catalog-search.html` §2.** It is in `design/`, which is authoritative and wins over code; it
is already the whole-database narrative rather than a catalog-only one (its skeleton carries
`role_bindings`, `api_keys`, `audit_events`, `outbox_events`, `purge_records`,
`idempotency_records`, `retention_holds`, and defers only detail to the RBAC doc with
`-- auth (see RBAC doc)`); it is the document the design phase reads first; and it is the document
where the drift actually occurred. Critically, it is the only place where the marker can sit
**adjacent to the assertion it qualifies**, which is the whole mechanism.

**Why not a new column on `design/architecture.html` §5.** The grill named this as the natural home
and, on inspection of the table, it is not. Three reasons, in order of weight:

- **It cannot hold the finding it was proposed for.** Drift 6 / F2 is about five column
  vocabularies. "`datasets.lifecycle_state` is one of three values" is not an invariant and will
  never be a row in A–N. The highest-value drift has nowhere to go.
- **Half the table would be blank.** Enumerating the fourteen rows against the schema: **A, B, C,
  F, H, L name no database object at all** — they are about NFS deletion paths, atomic renames,
  client behaviour, search authorization and credential vending. Of the eight that do touch
  PostgreSQL, only **J** (`role_binding_guard`), **M** (`releases_immutable`) and **N**
  (`snapshots_provenance_states_an_origin`, `snapshots_gold_is_never_an_entry_layer`) have anything
  installed; **D, E, G, I, K** have nothing. A column reading "not a database property" on six of
  fourteen rows is noise that teaches readers to skip it.
- **Row granularity is wrong.** N bundles three claims held by two different CHECKs plus one that
  nothing holds. J bundles a credentials fact with a catalog fact. One cell per invariant would
  have to average over them, which is how "linear, gap-free, immutable" was written in the first
  place.

What §5 gets instead is one sentence, replacing the second sentence of its lead paragraph:

> An invariant is a property of the system, not of any one store; several below are held by no
> database rule at all. Where a PostgreSQL rule is what holds an invariant — or where none does —
> <a href="catalog-search.html#enforcement">Catalog §2, What the database enforces</a> names it.

No new column, no new CSS, no reflow of a fourteen-row table.

#### The marker vocabulary

Three markers and one qualifier. The mechanism class (CHECK, FK, unique index, partial unique
index, trigger) is **not** a marker category: the marker says *who refuses the write*, and the
mechanism is identified by naming the object, which is strictly more informative than a category
because the reader can then read it. Five db-flavoured markers would still leave them looking it up.

| Marker | Means | A reader may conclude | A reader may **not** conclude |
|---|---|---|---|
| `[db]` | A named database object refuses the violating write, and it is installed at the revision `migrations/schema.sql`'s `Reflects:` line names. | Every client is refused — API, worker, migration, `psql`. The named object exists in `migrations/versions/`. | That the rule is *sufficient* for the invariant it serves. For a trigger, that it fires on operations its annotation does not name — `releases_immutable` is `BEFORE UPDATE` and does not see INSERT. |
| `[app: <module>]` | No database rule. The named module in `src/huron/` is the only thing that maintains the property, and the marker states in one clause why the database does not. | A hand-written `UPDATE` breaks it silently; reconciliation, not the engine, is the recovery path. | That a test covers it. That the module is the *only* writer, unless the marker says so. |
| `[spec]` | Nothing enforces it and no writer exists. The property is a requirement on whoever builds the writer. | Nothing today prevents a violation and there is no code to blame. This is a specification, not a status report. | That the property is aspirational or negotiable — it binds the future author exactly as a signature does. |

`[spec]` is the marker the schema's real shape demands: **20 of the 31 tables have zero references
anywhere in `src/huron/`** (Current State §5). For those tables, "the application enforces it" is
not a weaker guarantee than a constraint — it is *no guarantee at all*, because the application
does not exist. Collapsing them into `[app]` would restate the exact dishonesty this task exists to
remove.

**The landing-point qualifier.** `design/` leads the schema and wins where they disagree, so §2
will *always* contain rules the database does not have yet. That is the document working, not
drifting — Drift 6 was not "the design ran ahead", it was "the design ran ahead and did not say
so". The qualifier is therefore permanent, not scaffolding for `0008`:

- `[db 0008]` — committed to a named Alembic revision, not installed. Legal while
  `migrations/versions/0008_*.py` exists or is the revision being written.
- `[db P5]` — scheduled, no revision written. The qualifier is a phase id from
  `design/roadmap.html` §2.

Both forms are the house idiom already: §2 writes "`0008` drops it — see roadmap §2, P1" for
`audit_events`, and roadmap §2 carries `done` / `partial` / `todo` per phase. The grill classified
both as "forward statement, correctly marked". The qualifier generalizes them.

**The marking rule, stated once and binding.** *A `db` marker must be accompanied by its mechanism —
either the DDL spelled inline (as in the §2 skeleton) or the object named (as in
`migrations/schema.sql` and the residue table). A `db` marker with neither is not a legal marking.
Every line of §2 that states a rule carries a marker; an unmarked rule is a defect in the document,
not a fact about the database.* Plain column lists are not rules and carry nothing.

Markers render as `<span class="inv">[db]</span>`; `.inv` is already defined in
`design/catalog-search.html`'s style block (accent2, bold) and currently unused there, so no
stylesheet change is needed and `<pre>` handles the span without reflow.

#### Worked examples, from the live skeleton

Five real lines of §2, before and after. These are the lines, verbatim, not illustrations.

```
-- before
releases(id PK, dataset_id FK, tag, revision_id FK, title, purpose, campaign,
         created_by, created_at, withdrawn_at NULL, withdrawn_reason NULL,
         UNIQUE (dataset_id, tag))   -- rows are never UPDATEd except to withdraw
-- after
         UNIQUE (dataset_id, tag))   -- [db] rows are never UPDATEd except to withdraw:
                                     -- trigger releases_immutable freezes every other column
```

```
-- before
         lifecycle_state CHECK IN ('ACTIVE','RETIRED','SUPERSEDED'), …,
-- after
         lifecycle_state CHECK IN ('ACTIVE','RETIRED','SUPERSEDED'),   -- [db 0008] (S2)
```

```
-- before
ingest_sessions(…, dataset_id FK, …)         -- partial unique index: one open per dataset
-- after
ingest_sessions(…, dataset_id FK, …)         -- [db] one_open_ingest_per_dataset:
                                             -- partial unique index, one open per dataset
```

```
-- before
purge_records(… approved_by <> requested_by enforced by CHECK)
-- after
purge_records(… [db] approved_by <> requested_by, purge_records_check)
```

```
-- before
         state CHECK IN ('DRAFT','PUBLISHED','DEPRECATED','WITHDRAWN'),
         -- PUBLISHED rows are immutable: fixes are new semvers; a trigger refuses
         -- UPDATE of document/namespace/name/semver once state='PUBLISHED'
-- after
         state CHECK IN ('DRAFT','PUBLISHED','DEPRECATED','WITHDRAWN'),   -- [db P5]
         -- [db P5] PUBLISHED rows are immutable: fixes are new semvers; a trigger refuses
         -- UPDATE of document/namespace/name/semver once state='PUBLISHED'
```

The last one is the case that proves the notation: `schema_registry` does not exist, and today the
block reads exactly like the blocks for tables that do.

#### The residue table

The skeleton can only mark properties that have a line in it. Properties asserted elsewhere in
`design/` that are *about* the database but have no column to hang on — the class F8 belongs to,
"a deliberate choice, made for a real reason, recorded nowhere until the audit found it" — go in a
table in the new subsection. Four columns, and every row carries its provenance.

| Property | Asserted in | Marker | Mechanism, or what it would be |
|---|---|---|---|
| Committed revision numbers within a dataset are contiguous `1..N` (invariant E) | ARCH §5 E; RAW §4 | `[spec]` | None. `one_open_ingest_per_dataset` `[db]` serializes allocation, but nothing checks contiguity and `dataset_revisions` has no writer. A gap is representable and was inserted. |
| A committed revision is immutable | schema.sql §1; ARCH §5 D | `[spec]` | None. `releases_immutable` is the shape it would take; the schema has exactly four trigger guards (Current State §4) and none is on this table. An `UPDATE` rewrote a committed digest and revision number. |
| A catalog row is never published before its storage state is durable (invariant G) | ARCH §5 G; RAW §5 | `[spec]` | Not expressible as a constraint: an ordering between a filesystem rename and a later, separate transaction. The reconciler is a detection path, not a guard. |
| A Gold version resolves to exact input snapshot ids, a container digest and parameters (invariant K) | ARCH §5 K; GOLD §3 | `[spec]`, with `[db 0008] product_versions_derivation_record_is_an_object` | `0008` checks the column holds a jsonb object. Nothing checks that the object names its inputs. |
| An ingest session that reaches `COMMITTED` claims the revision that was created | audit F8 | `[db 0008] ingest_sessions_revision_guard` | S7. Today a session commits against a dangling UUID; a plain FK is not representable because `revision_id` is minted hours earlier, in `PREPARING`. |
| A release cites a revision of its own dataset | audit F1 | `[db 0008] releases_revision_dataset_fk` | S1. Today the two FKs are independent and a cross-dataset citation inserts cleanly — permanently, since releases are withdrawn, never repointed. |
| Every role is user-only, and no role carries `data.write` at silver or gold | RBAC §2, §6 | `[app: src/huron/pkg/rbac/roles.py]` | Seed rows, not constraints. `role_binding_guard` `[db]` refuses `sa:` principals, but the seed's own shape is held by the module and pinned by `tests/contract/test_rbac_store.py`. |

Seven rows, bounded by provenance: each is a property some artifact in `design/`,
`schema_audit.md` or `SCHEMA_DESIGN.md` already asserts. The table is not a sweep of every property
the system has.

#### The one paragraph added to `migrations/schema.sql`

S8 fixed that file's header text verbatim and owns it. S9 adds exactly one paragraph, after
"never as standalone DDL." in the `Scope:` block, so the write-back phase produces one header and
not two:

```sql
-- A comment that states a property carries the marker design/catalog-search.html
-- §2 defines: [db] with the object that refuses the violating write, [app] with
-- the module that maintains it, [spec] where nothing does and no writer exists.
-- A bare adjective is not a marking.
```

and the one body edit S9 owns — line 63, the Drift 10 comment. S1 separately adds a unique key to
this block; the two edits do not collide.

```sql
-- before
CREATE TABLE dataset_revisions (      -- linear, gap-free, immutable

-- after
CREATE TABLE dataset_revisions (
    -- [spec] linear, gap-free, immutable (invariant E) - allocated under the
    -- per-dataset ingest lock by a writer that does not exist yet. No constraint
    -- or trigger holds any of the three; contrast releases_immutable below.
```

This is the asymmetry the grill named — a bare adjective two tables above a named trigger, in the
same register, with opposite realities — closed by making the bare adjective illegal in this file.

### Explicit contracts

**What a reader may conclude from each marker** is the third column of the legend table above, and
what they may not is the fourth. Three further contracts govern the record as a whole.

**The record claims enforcement, not correctness.** `[db]` says a violating write is refused. It
does not say the rule is the right rule, that it is sufficient for the invariant it serves, or that
its vocabulary is complete. `snapshots_provenance_states_an_origin` refuses `'{}'`; it does not
verify that the referenced snapshot exists. That distinction is the point of naming the object
rather than asserting the invariant.

**Absence of a marker is a document defect, not a statement about the database.** This is what
makes the notation reviewable: there is no silent state. A rule with no marker is incomplete in the
same way a function with no return type annotation is incomplete in this codebase, and it is caught
the same way — by the reader of the diff.

**The record does not make §2 a schema mirror.** §2 remains a skeleton whose preamble already says
"the Alembic migrations are the source of truth", and it remains *ahead* of the migrations by
design. What changes is that being ahead is now stated per rule instead of being indistinguishable
from being installed. Drift 7 (`layer_repos`), Drift 8 (six tables with wrong column lists) and
Drift 16 (`science_profiles`) are content errors in §2 that this task does **not** own and does not
fix; likewise S2 owns the `product_versions.status` → `state` correction and S5 owns
`derivation` → `derivation_record`. **S9 owns the marking, never the content.** Apply markers after
those corrections, or accept re-marking the corrected lines.

**A `[db]` marker is a contract-test specification.** `tests/contract/test_rbac_store.py`'s
`_assert_trigger_rejects_*` is the existing house template for "prove a database rule with a write
that must fail". The set of unqualified `[db]` markers is exactly the set of properties for which
such a test can be written, and is where new ones belong. The record does not claim such a test
exists for any given marker.

### Currency

**The honest answer is review discipline, given teeth by the marker's grammar — not a new check.**
Stated as a rule inside the subsection it governs, so it is not a convention someone has to
remember:

> §2 leads the schema; it states what must be true. It is **not** stamped to an Alembic head and is
> not expected to track migrations. Its obligation is different: every rule it states carries a
> marker naming who refuses a violation today, and every landing point names a revision under
> `migrations/versions/` or a phase in the roadmap. A rule with no marker is a defect in this
> section.

This answers the grill's second gap directly — §2 today "silently claims" to track migrations, and
the answer is that it does not and should not. Stamping a design document to the current head would
institutionalize the opposite of "design wins": it would make being ahead a lint failure.

**Why no script.** The check that would matter is "this bare `[db]` marker's rule is actually
installed", and that needs the DDL applied — a migrated database, which S8 established this
repository has nowhere to run (no `.github/workflows/`, every pre-commit hook database-free,
`alembic.ini` hard-coding one laptop's port). The check that is cheap — "this landing point names a
revision or phase that exists" — catches a typo, not the drift class. Adding this repository's
first design-document linter to catch typos is machinery out of proportion to a hand-written HTML
record, and it would give false assurance about the claim it cannot test.

**What actually changed, and why it is enough.** Under this notation Drift 6 could not have been
written the way it was. An author asserting `CHECK IN ('ACTIVE','RETIRED','SUPERSEDED')` must
choose: `[db]`, which is checkable by one `grep` of `migrations/versions/` and false; `[db 0008]`,
which is true and names the work; or `[spec]`. Every option is a visible claim. The failure that
occurred was an *omission*, and omissions are invisible in review; this converts the whole class
into assertions.

**Who notices when it stops being true.** Three readers, in order of how soon:

- **The reviewer of any schema-changing commit.** S8's `scripts/check_schema_map.py` already forces
  `migrations/schema.sql` into that same commit, and `schema.sql` now carries the same markers on
  the same tables. An author converting `[db 0008]` to `[db]` in the map has §2's corresponding
  line in front of them by table name. The coupling is by table, not automatic — stated as such.
- **The author of a contract test**, for whom the unqualified `[db]` set is the work list.
- **The next grill pass**, which now has a falsifiable target instead of a prose judgment: every
  `[db]` marker is one negative write away from being proven or disproven, which is exactly the
  method the Phase 0 grill already used.

### Sequencing

**Write it now, before `0008`, in the marked form. The form does not depend on the order.**

- **The qualifier is permanent, not scaffolding.** `design/` leads the schema by charter, so §2 will
  carry unlanded rules after `0008` exactly as it does before it. Deferring the record until `0008`
  lands does not avoid the present-versus-committed problem; it postpones it to `0009`.
- **`0008`'s implementers are the primary readers.** S2 and S3 are transcribing vocabularies *out of
  §2* into DDL. A marked §2 tells them which of its assertions are the specification they are
  implementing and which are already installed — which is precisely the confusion that made Drift 6
  survive seven revisions.
- **It cannot conflict with `0008`.** S9 produces no DDL and touches no migration module. Its only
  contact with `0008`'s change set is one paragraph in a `migrations/schema.sql` header that S8 is
  already rewriting, and one comment on line 63 that no sibling task claims.
- **If the write-back phase runs after `0008` instead, nothing about the design changes** — the
  `0008` landing points are simply already bare. The record is written the same way either way.

**What `0008` inherits.** When `0008` lands, every `[db 0008]` marker in `design/catalog-search.html`
§2 and in `migrations/schema.sql` drops its qualifier, and the residue table's F1, F8 and K rows
move with it. That is a mechanical edit over a greppable string. It belongs on `0008`'s completion
list beside the map update S8 already puts there, and should be named there explicitly rather than
left to memory — a stranded `[db 0008]` after `0008` has landed is the same defect class as S8's
stranded header, and neither `check_schema_map.py` nor any other check will catch it.

### Deletions

Three, all comment text; no document, section or table is removed.

- **`migrations/schema.sql` line 63, the words `-- linear, gap-free, immutable`** — replaced by the
  marked block above. This is Drift 10, and it is deleted rather than corrected because the register
  it was written in no longer permits a bare adjective.
- **`design/architecture.html` §5, the sentence "Each has a corresponding acceptance test in the
  roadmap."** — not deleted but *replaced* by the routing sentence given above. It is the clause
  that implies uniform backing across fourteen rows with three installed mechanisms between them.
  (Whether the acceptance tests it promises exist was not checked here and is not this task's
  question; the replacement neither asserts nor denies them.)
- **`design/catalog-search.html` §2, the trailing prose `-- rows are never UPDATEd except to
  withdraw` in its unattributed form** — subsumed by the `[db]` marking that names
  `releases_immutable`.

Nothing in `docs/` changes: `local-development.md` and `repository-layout.md` describe
`migrations/schema.sql` as hand-maintained read-only documentation and stay correct verbatim. No
application code, `pkg/` symbol, test or migration references any of this.

### Rejected alternatives

- **An enforcement column on `design/architecture.html` §5's A–N table** — six of the fourteen
  invariants name no database object at all, and the finding that motivated the work (five column
  vocabularies, F2) is not an invariant and could never be a row in it.
- **A standalone register table mapping every invariant to its mechanism, in §2 or a new
  `design/` page** — a second copy of the schema facts, which drifts from the skeleton exactly as
  the skeleton drifted from the migrations, and which leaves the skeleton's own `CHECK IN (…)`
  lines unmarked for the reader who never scrolls to it.
- **Stamping `design/catalog-search.html` §2 with a `Reflects:` head and a lint check, mirroring
  S8** — it would make the authoritative design document's legitimate lead over the schema a build
  failure, inverting "where code and design disagree, the design wins".

### Open questions

**One, with a recommendation.**

**Does `migrations/schema.sql` adopt the markers, or do they stay in `design/` only?** S8 has
already fixed that file's header verbatim, so this is a cross-task amendment rather than a free
choice, and it is the reviewer of a future migration — not the reader of the design record — who
would use them.

*Recommended: yes, adopt them,* for the paragraph and the line-63 edit quoted above and nothing
else. Three reasons. Drift 10 is a `schema.sql` defect and cannot be closed anywhere else. It is the
one artifact of the three with a mechanical currency check, so markers there ride along with an
obligation that already exists. And a marker vocabulary used in one of the two documents that
assert database properties leaves the other free to keep writing bare adjectives, which is the
habit this task exists to break. The cost is four lines of header and one comment, both inside
edits `0008` is already making.

---

## Phase 5 write-back (2026-09-01)

The corrections the Phase 0 grill classified as *documentation is wrong*, plus S9's three
`design/` edits. Nothing here changes a design decision; every item is a text correction or the
marking S9 specifies. `migrations/` was not touched — Drifts 9, 11, 13, 14 and the addition to
Drift 4 are `migrations/schema.sql` edits owned by `SCHEMA_IMPLEMENTATION_PLAN.md` M1.

### `design/catalog-search.html` — 351 → 503 lines

| Change | Discharges |
|---|---|
| New `<h3 id="enforcement">What the database enforces</h3>` between the §2 skeleton and `<h3 id="schema-registry">`: the three-marker legend with its "may conclude / may not conclude" columns, the mechanism-naming rule, the landing-point qualifiers, the currency rule as a `.note`, the enforcement-not-correctness contract, and the seven-row residue table. | S9 § "Where it lives" 1; plan § 7 item 21 |
| Markers applied to every rule-stating line of the §2 skeleton. The five lines S9 gives verbatim (`releases`, `datasets.lifecycle_state`, `ingest_sessions`, `purge_records`, `schema_registry.state` and its trailing trigger prose) are used exactly as written. | S9 § "Where it lives" 2 |
| Drift 7: the `layer_repos` block is gone and `snapshots` is the shipped table — `(id, dataset_id, layer, repo_uri, snapshot_id, state, provenance, validation_evidence, published_at)` with `UNIQUE (repo_uri, snapshot_id)`. Three lines of prose say there is no registry table and that `tag`, the source revision, the contract version and the building job are fields of `provenance`, not columns. | Drift 7 |
| Drift 8: `role_bindings` → `(principal, role_code, scope_type, scope_id, effect, conditions, expires_at, created_by, created_at)`; `api_keys` → one `project_id` FK, `owner_subject`/`owner_kind`/`secret_sha256`; `idempotency_records` → no `operation`, PK `(principal, key)`; `jobs` → `subject_id, image_digest, payload, available_at, completed_at` and no `subject_kind`/`claimed_by`/`failure`; `lineage_edges` → `upstream_*`/`downstream_*`; `ingest_files` → `observed_sha256` removed; `retention_holds` → `created_by`/`created_at`. | Drift 8 |
| Drift 16: `science_profiles(name, version, document, document_sha256, published_by, published_at, PK (name, version))` restored, above the `schema_registry` block that is scheduled to absorb it. | Drift 16 |
| `product_versions.status` → `state`, `product_versions.derivation` → `derivation_record` (`0001` line 291). | Plan § 1, the two unowned column-name corrections |

**The five `CHECK IN (…)` vocabularies were kept, not deleted.** `datasets.lifecycle_state`,
`dataset_revisions.state`, `snapshots.state`, `product_versions.state` (renamed from `status`) and
`jobs.kind` are the specification `0008` implements — Drift 6 is classed *code has diverged, design
wins* — so each carries `[db 0008]` with its owning design record (`(S2)`, `(S3)`) rather than
being weakened to match the database. `schema_registry`'s five rules and its immutability trigger
carry `[db P5]`; `science_profiles_document_sha256_format` carries `[db 0008] (S5)`.

**Marking convention, where S9 does not spell a line out.** A `[db]` marker sits adjacent to the
rule it qualifies and carries its mechanism — the DDL inline where the skeleton already spells it
(`CHECK IN (…)`, `UNIQUE (…)`), the object named otherwise (`one_open_ingest_per_dataset`,
`jobs_claim`, `outbox_unprocessed`, `role_bindings_guard`, `role_bindings_no_duplicates`,
`role_bindings_principal_format`, `snapshots_provenance_states_an_origin`,
`snapshots_dataset_required_below_gold`, `snapshots_gold_is_never_an_entry_layer`,
`purge_records_check`, `releases_immutable`). Per S9, primary keys, foreign keys and structural
`UNIQUE (…)` clauses are part of the column list rather than rules, and carry nothing — this is
what S9's own worked example for `releases` does, where the marker attaches to the immutability
prose and not to the `UNIQUE (dataset_id, tag)` beside it. The two claims about a `FOR UPDATE SKIP
LOCKED` claimant (`jobs`, `outbox_events`) are `[spec]`: neither table is referenced anywhere in
`src/huron/`, so no module can be named.

### `design/architecture.html` — 296 → 298 lines

The §5 lead paragraph's second sentence ("Each has a corresponding acceptance test in the
roadmap.") is replaced by S9's routing sentence, which now reads: *"An invariant is a property the
system must never violate — a property of the system, not of any one store; several below are held
by no database rule at all. Where a PostgreSQL rule is what holds an invariant — or where none does
— Catalog §2, What the database enforces names it."* S9's quoted replacement opens by restating
"An invariant is a property", which would have duplicated the surviving first sentence verbatim;
the two were merged with an em dash so every clause of S9's text survives and nothing is said
twice. No new column, no CSS, no reflow of the A–N table. (S9 § "Deletions" notes that whether the
promised acceptance tests exist was not checked; the replacement neither asserts nor denies them.)

### `design/rbac.html` — Drift 12

The §5 example binding (the grill calls it §4) is respelled so the live database would accept it:
`role` → `role_code`, `scope_type` `project` → `PROJECT`, `effect` `allow` → `ALLOW`, a UUID
`scope_id`, and `expires_at` lifted out of `conditions` into its own key, which is where the column
is. `developer`'s `bindable_scopes` include `PROJECT`, so the row now passes `role_binding_guard`,
`role_bindings_scope_type_check` and `role_bindings_effect_check`. Line count unchanged.

### `RBAC_IMPLEMENTATION_PLAN.md` and `AUTH_IMPLEMENTATION_PLAN.md` — Drift 15

- §R4's verified-rejection list no longer cites `pipeline→user`; `0007` deleted the role. The
  principal-kind case is now stated as it reproduces today — any `sa:` principal against any role,
  since all five surviving roles are user-only. `platform_owner→ORGANIZATION scope`, bad prefix and
  exact duplicate are unchanged and still reproduce (`platform_owner.bindable_scopes = {SYSTEM}`).
- §R4's `migrations/schema.sql` sentence says the map covered `0001`+`0002` when that step landed
  and now spans `0001`–`0007`, rather than asserting `0001`+`0002` in the present tense.
- §A5's title and the two other references to the auth migration say `0005_auth`; it shipped as
  `0005`, `0004` being `0004_entry_layers`. The `user.manage` seed reference moved with it
  (`0005_auth.py:82`).

### The design-document count — `README.md`, `docs/`

Fifteen `design/*.html` files exist. `README.md` said thirteen, `docs/getting-started/repository-layout.md`
said 13, `docs/index.md` and `docs/backend-design.md` said fourteen; all four now say fifteen, and
`docs/backend-design.md`'s per-document table gains the row it was missing —
`workflows.html`, the end-to-end scientist journey. No prose was restructured; each was a single
number, and the table gained one row.

**Flagged rather than fixed: `design/workflows.html` is untracked in git** (`git status
--untracked-files=all design/` shows `?? design/workflows.html`). The counts are now correct for a
working tree and would be wrong for a fresh clone until the file is committed. Committing it is
outside this pass.

### `design/roadmap.html` — nothing to do

Checked and left untouched, deliberately. Roadmap Drift 1 (P1's "audit with pre-created
partitions") is already withdrawn in the working tree, with the S6 option-B reasoning and the
`0008` row spelling out the de-partitioning; Roadmap Drift 3 (§3 milestone 3's role count and
trigger claim) already reads "exactly the five roles" and "service-account-free by construction
rather than by trigger". Neither the design nor the plan supports any further roadmap item, and S9
produces no DDL and no phase deliverable, so no entry was invented for it.

### Deliberately not changed

- **`migrations/schema.sql`** and everything else under `migrations/` — Drifts 9, 11, 13, 14, the
  addition to Drift 4, and S9's header paragraph and line-63 `[spec]` block are M1's, not this
  phase's. `migrations/schema.sql` therefore still carries `-- linear, gap-free, immutable` over
  `dataset_revisions`, and the notation is installed in one of the two documents that assert
  database properties, exactly as plan § 7 item 21 says it will be.
- **The `[db 0008]` qualifiers.** `0008` has not landed, so every one of them is currently true.
  Item 21's qualifier drop — here, in the residue table's F1, F8 and K rows, and in the map — is
  owed when it does, and nothing mechanical will catch a stranded one.
- **`one_claim_per_revision_number` (S7a)** was not added to the §2 skeleton. §2 states no
  uniqueness rule for `ingest_sessions` beyond the partial index it already names, so there was no
  existing assertion to mark; adding the new index would be new content, which S9 explicitly does
  not own ("S9 owns the marking, never the content").
- **`releases.purpose`/`campaign`, `product_versions.iceberg_ref`/`polaris_synced_at`** — columns
  the §2 skeleton names that `0001` does not create. No grill finding classifies them, they state
  no rule, and §2 legitimately leads the schema, so they were left as written rather than resolved
  in either direction on this pass.
- **Roadmap Drift 2 (`pkg/metastore/` does not exist)** — roadmap §1's package inventory is a
  statement of intended layout, not a `done` claim, and no plan item assigns it here.
