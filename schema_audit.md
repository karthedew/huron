# PostgreSQL schema audit against `postgresql-table-design`

Audit of the Huron metastore schema against `.claude/skills/postgresql-table-design/SKILL.md`,
performed 2026-08-31. Seed document for `/design-plan`; every finding below was **proven on a
live PostgreSQL 16**, not inferred from reading DDL.

## Method

Migrations `0001_foundations` … `0006_role_simplification` were extracted (each is a single
module-level `DDL` string) and applied in order to a scratch PG16 cluster with
`psql -v ON_ERROR_STOP=1`. Findings were then established two ways:

- **catalog queries** — `pg_constraint` / `pg_index` / `pg_attribute` joins for structural facts
  (which FK columns lack a supporting index, which text columns carry no CHECK, and so on);
- **negative writes** — an INSERT or UPDATE that the schema *should* refuse. Where one succeeded,
  that is recorded below as proof, not as an opinion.

`0007_roleless_service_accounts` was **not** included in the audited stack (it was untracked and
in flight at audit time). It adds no tables, columns, indexes, or CHECKs — it deletes the two
pipeline roles and replaces `role_binding_guard()` — so none of the findings below are affected
by it. **A migration implementing these fixes must be `0008`, with
`down_revision = "0007_roleless_service_accounts"`.**

## Conforms — do not re-flag

- `timestamptz` throughout; no `timestamp`, `timetz`, or precision specifications.
- `text` throughout; no `varchar(n)` or `char(n)`. No `serial` anywhere.
- `snake_case` identifiers throughout; nothing quoted or mixed-case.
- The role catalog (`roles` / `capabilities` / `role_capabilities`) is properly 3NF, with the one
  role-dependent attribute (`layers`) on the junction table where it belongs.
- Four well-targeted partial indexes: `one_open_ingest_per_dataset`, `jobs_claim`,
  `outbox_unprocessed`, `sessions_subject_active`.
- `role_bindings_no_duplicates` correctly uses `UNIQUE NULLS NOT DISTINCT`, which is exactly the
  skill's recommendation for a uniqueness key with a nullable column.

Two apparent violations that are **correct as they stand**:

- **`principals.idp_subject` permits multiple NULLs.** The skill prefers `NULLS NOT DISTINCT` by
  default, but here multiple NULLs are the point: service accounts have no IdP subject. Leave it.
- **UUID primary keys** rather than the skill's preferred `BIGINT GENERATED ALWAYS AS IDENTITY`.
  Ids are opaque, client-generated, and baked into storage paths; the skill's own carve-out
  ("`UUID` when global uniqueness/opacity is needed") applies. The absence of a database-side
  `DEFAULT gen_random_uuid()` is likewise deliberate — the application generates ids.

## Findings

### F1 — `releases` accepts a revision belonging to a different dataset

`releases.dataset_id` and `releases.revision_id` are independent foreign keys, so nothing ties the
cited revision to the citing dataset.

*Proof:* with `ds-one` and `ds-two` both under one project and revision `d1` belonging to `ds-one`,
`INSERT INTO releases (dataset_id, revision_id, ...) VALUES (ds-two, d1, ...)` **succeeded**.

Releases are citation anchors and are immutable once written (invariant M), so a mis-citation is
permanent and silent. Migration `0003` already established the fix pattern for exactly this class
of bug on `products` — `datasets_id_project_id_unique` plus a composite FK — and its own docstring
states the rationale: "a plain `FOREIGN KEY (dataset_id) REFERENCES datasets(id)` would happily
accept a dataset that belongs to a different project."

Indicated shape: `UNIQUE (id, dataset_id)` on `dataset_revisions`, plus
`FOREIGN KEY (revision_id, dataset_id) REFERENCES dataset_revisions(id, dataset_id)` on `releases`.

`revision_amendments` and `purge_records` are **not** affected — they carry only `revision_id`, so
no inconsistent pair is representable.

### F2 — twelve enum-like text columns carry no CHECK

The skill's rule: business-logic-driven, evolving values → `TEXT` + `CHECK`, or a lookup table.
These columns have neither:

| Table | Column |
|---|---|
| `organizations`, `projects`, `datasets`, `products` | `lifecycle_state` |
| `dataset_revisions`, `ingest_files`, `jobs`, `purge_records`, `snapshots`, `product_versions` | `state` |
| `reconciliation_findings` | `severity` |
| `jobs`, `audit_events`, `outbox_events`, `lineage_edges` | `kind` / `upstream_kind` / `downstream_kind` |

*Proof:* `UPDATE datasets SET lifecycle_state = 'BANANA'` **succeeded**; so did setting a project's
`lifecycle_state` to the empty string, and `dataset_revisions.state` to `'NOT_A_STATE'`, and
inserting a job with `state = 'WAT'`.

This is drift rather than house style: sibling columns in the same schema —
`ingest_sessions.state`, `snapshots.layer`, `retention_holds.kind`, `role_bindings.effect`,
`policy_attachments.scope_type`, `sessions.authentication_method` — all do carry CHECKs.

The design work is deciding the permitted vocabulary for each column (and, for the `kind` columns,
whether an open vocabulary is intentional — an event `kind` may legitimately be open-ended where a
`lifecycle_state` is not).

### F3 — nine foreign-key columns have no index

The skill states this twice, including the flat warning "PostgreSQL **does not** auto-index FK
columns. Add them." Unindexed:

- `api_keys.project_id`
- `product_versions.snapshot_id`
- `products.dataset_id`, and the composite `products (dataset_id, project_id)`
- `purge_records.revision_id`
- `releases.revision_id`
- `role_bindings.role_code`
- `role_capabilities.capability_code`
- `snapshots.dataset_id`

Beyond join cost, the skill notes the locking consequence: an unindexed referencing column forces a
scan on every parent delete or key update.

### F4 — the RBAC scope-listing query has no usable index

`src/huron/service/api/postgres_rbac.py:225-228` runs
`... FROM role_bindings WHERE scope_type = $1 AND scope_id IS NOT DISTINCT FROM $2`.

The only candidate index is `role_bindings_principal_scope (principal, scope_type, scope_id)`,
whose leading column the query does not constrain.

*Proof:* `EXPLAIN` with `enable_seqscan=off` shows a full scan of `role_bindings_no_duplicates`
with `Index Cond: (scope_type = ...)` on a non-leading column and `scope_id` demoted to a filter.

`policy_attachments_scope (scope_type, scope_id)` already applies the right pattern for the
identical access path on the sibling table; mirroring it on `role_bindings` is indicated.

### F5 — no jsonb column constrains its own shape

All fifteen `jsonb` columns lack the `CHECK (jsonb_typeof(col) = 'object')` guard the skill gives
verbatim, including the four with an `'{}'::jsonb` default that plainly intend an object.

*Proof:* `UPDATE projects SET raw_retention_policy = '"just a string"'::jsonb` **succeeded**, and
`jsonb_typeof` then reported `string`.

`snapshots.provenance` is the exception that shows the intent — `0004` added two NULL-safe CHECKs
on its `kind` key, and its docstring records that the naive spelling silently accepted `'{}'`.

**GIN indexes are deliberately *not* recommended here.** The application issues no jsonb
containment, key-existence, or path queries at all (`@>`, `?`, `->>` do not appear in
`src/huron`). Adding GIN indexes now would cost write throughput to accelerate queries that do not
exist. Add one when a query needs it.

### F6 — `audit_events` is partitioned but has only a DEFAULT partition

`audit_events` declares `PARTITION BY RANGE (created_at)` and then creates
`audit_events_default PARTITION OF audit_events DEFAULT`. With no bounded partitions, every row
lands in the default child and there is nothing for the planner to prune; the partitioning is
structure without benefit. There is also no index on `created_at` (the PK is `(id, created_at)`,
whose leading column is a random UUID, so it cannot serve a time-range scan).

Either commit to the partitioning (bounded RANGE partitions plus whatever creates them ahead of
time, and a retention story) or drop it until the volume justifies it. The skill's threshold is
">100M rows"; it also suggests BRIN for naturally-ordered time-series like an append-only audit log.

### F7 — twenty-one of twenty-three foreign keys leave ON DELETE implicit

Only `ingest_files.ingest_id` (`ON DELETE CASCADE`) and `role_capabilities.role_code`
(`ON DELETE CASCADE`) state a referential action. The rest default to `NO ACTION`, which is very
likely what is wanted for a catalog whose rows are withdrawn rather than deleted — the skill asks
for the choice to be explicit rather than inherited.

### F8 — `ingest_sessions.revision_id` has no foreign key

The column is `uuid NOT NULL UNIQUE` with no `REFERENCES`.

*Proof:* inserting an ingest session whose `revision_id` is an arbitrary UUID **succeeded**, leaving
a row that joins to no revision.

This is very likely deliberate: the `dataset_revisions` row is created at commit time, so a plain
FK would make the `PREPARING` state unrepresentable. **Karl has confirmed (2026-08-31) that the
integrity gap should nonetheless be closed** — the invariant that goes unenforced today is that at
commit, `ingest_sessions.revision_id` equals the revision actually created. Candidate mechanisms
(a `DEFERRABLE INITIALLY DEFERRED` FK, or a commit-time trigger asserting the correspondence) need
design against the actual ingest flow in `src/huron/pkg/catalog/ingest.py` and
`src/huron/pkg/rawstore/commit.py`.

## Lower priority — noted, not pushed

- `created_at` / `updated_at` carry no `DEFAULT now()` on 25 columns; the application supplies them.
- Free-text `title` / `description` columns have no `CHECK (length(...) <= n)`.
- `product_versions.snapshot_id` can reference a snapshot belonging to an unrelated dataset —
  the same class as F1, at lower stakes.

## Out of scope

`migrations/schema.sql` is generated documentation, not executed DDL, and its header currently
lists only `0001`–`0005`. Any migration landing these fixes must regenerate it.
