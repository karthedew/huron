-- ============================================================================
-- Huron metastore: table architecture summary
-- ============================================================================
-- HAND-MAINTAINED DOCUMENTATION. Not executed, and not generated: this is a
-- condensed map of what the Alembic revisions under migrations/versions/ build,
-- and the authoritative DDL is those revisions, never this file. The map exists
-- to carry what a schema dump cannot - the trigger annotations, the vocabularies,
-- and the invariant each rule serves. Do not replace it with pg_dump output.
--
-- Reflects: 0011_verified_raw
--
-- Every revision that changes the schema updates this file in the same commit
-- and moves the Reflects line to the new head. scripts/check_schema_map.py
-- fails when that line is not the Alembic head; it runs in `make lint` and as a
-- pre-commit hook.
--
-- Scope: every table and column appears, with types condensed. A constraint
-- appears where it carries a design rule; indexes and triggers appear as
-- `-- index ...` / `-- trigger ...` annotations inside the table block they
-- serve, never as standalone DDL.
-- A comment that states a property carries the marker design/catalog-search.html
-- §2 defines: [db] with the object that refuses the violating write, [app] with
-- the module that maintains it, [spec] where nothing does and no writer exists.
-- A bare adjective is not a marking.
-- PostgreSQL structural state only - no
-- metadata mirrors, no text search (invariant A: LanceDB owns matching;
-- sidecars authoritative).
-- ============================================================================
-- 1. Hierarchy: Organization -> Project -> Dataset -> revisions + release tags
-- ============================================================================

CREATE TABLE organizations (
    id uuid PRIMARY KEY,
    slug text UNIQUE NOT NULL,          -- ^[a-z0-9][a-z0-9-]{1,61}$, no '--'
    title text NOT NULL,
    description text NOT NULL DEFAULT '',
    lifecycle_state text NOT NULL DEFAULT 'ACTIVE',
    -- [db] organizations_lifecycle_state_vocabulary CHECK IN ('ACTIVE'):
    -- today's only reachable value; no transition is built or documented
    generation integer NOT NULL DEFAULT 1,  -- filesystem generation doc counter
    version integer NOT NULL DEFAULT 1,     -- optimistic-concurrency counter (ETag)
    created_at timestamptz NOT NULL,
    updated_at timestamptz NOT NULL
);

CREATE TABLE projects (
    id uuid PRIMARY KEY,
    organization_id uuid NOT NULL REFERENCES organizations,
    slug text NOT NULL,                 UNIQUE (organization_id, slug),
    title text NOT NULL,
    description text NOT NULL DEFAULT '',
    classification_default text NOT NULL,
    raw_retention_policy jsonb NOT NULL DEFAULT '{}',
    -- [db] projects_raw_retention_policy_is_an_object CHECK: object shape
    quota_bytes bigint,                 -- NULL = unlimited
    lifecycle_state text NOT NULL DEFAULT 'ACTIVE',
    -- [db] projects_lifecycle_state_vocabulary CHECK IN ('ACTIVE'):
    -- today's only reachable value; no transition is built or documented
    generation integer NOT NULL DEFAULT 1, version integer NOT NULL DEFAULT 1,
    created_at timestamptz NOT NULL, updated_at timestamptz NOT NULL
);

CREATE TABLE datasets (
    id uuid PRIMARY KEY,
    project_id uuid NOT NULL REFERENCES projects,
    slug text NOT NULL,                 UNIQUE (project_id, slug),
    title text NOT NULL,
    description text NOT NULL DEFAULT '',
    owner_group text,
    profile_name text NOT NULL,         -- science profile the dataset declares
    profile_version text NOT NULL,
    contract_version text,              -- canonical contract -> Silver membership
    entry_layer text NOT NULL DEFAULT 'raw',  -- raw | bronze | silver (CHECK); where this
                                        -- dataset's data first arrives. Above raw = the lake
                                        -- is not the origin: no revisions, no Bronze, ever.
                                        -- Gold excluded: products need a derivation record.
    data_classification text NOT NULL,
    lifecycle_state text NOT NULL DEFAULT 'ACTIVE',
    -- [db] datasets_lifecycle_state_vocabulary CHECK IN ('ACTIVE','RETIRED','SUPERSEDED'):
    -- RETIRED ends a dataset's working life; SUPERSEDED names a slug mistake
    -- replaced by another dataset
    generation integer NOT NULL DEFAULT 1, version integer NOT NULL DEFAULT 1,
    created_at timestamptz NOT NULL, updated_at timestamptz NOT NULL
);

CREATE TABLE dataset_revisions (
    -- [app] service.api.stores.ingest begin_ingest: linear and gap-free -
    -- max(revision_number) + 1 over every row, taken under
    -- SELECT ... FOR UPDATE on the datasets row; immutable (invariant E) -
    -- no constraint or trigger holds that; contrast releases_immutable below.
    id uuid PRIMARY KEY,
    dataset_id uuid NOT NULL REFERENCES datasets,
    revision_number integer NOT NULL,   -- 1..999999; UNIQUE (dataset_id, revision_number)
    manifest_sha256 text NOT NULL,      -- Identical manifests are allowed in distinct revisions.
    metadata_sha256 text NOT NULL,
    revision_path text UNIQUE NOT NULL, -- /data/.../dataset/{...}/raw/revision/000042--{id}
    file_count integer NOT NULL, total_bytes bigint NOT NULL,
    state text NOT NULL DEFAULT 'COMMITTED',
    committed_by text NOT NULL, committed_at timestamptz NOT NULL
    -- [db] UNIQUE (id, dataset_id) dataset_revisions_id_dataset_id_unique: the
    -- composite FK target for releases_revision_dataset_fk below
    -- [db] dataset_revisions_state_vocabulary CHECK IN ('COMMITTED',
    -- 'EXPIRED_PARTIAL','EXPIRED','PURGED','DEGRADED'): COMMITTED is ingest's
    -- only output; retention, purge and the reconciler write the rest
);

CREATE TABLE releases (               -- immutable tags on one revision (invariant M)
    id uuid PRIMARY KEY,
    dataset_id uuid NOT NULL REFERENCES datasets,
    tag text NOT NULL,                  UNIQUE (dataset_id, tag),
    revision_id uuid NOT NULL,
    title text, created_by text NOT NULL, created_at timestamptz NOT NULL,
    withdrawn_at timestamptz, withdrawn_reason text
    -- [db] trigger releases_immutable: every column except withdrawal is frozen;
    -- a wrong tag is withdrawn (tombstone), never repointed.
    -- [db] FOREIGN KEY (revision_id, dataset_id) REFERENCES dataset_revisions (id, dataset_id)
    -- releases_revision_dataset_fk: a release cites a revision of its own dataset only
);
-- [db] index releases_revision (revision_id, dataset_id)

CREATE TABLE revision_amendments (    -- project-admin metadata amendments, append-only
    id uuid PRIMARY KEY,
    revision_id uuid NOT NULL REFERENCES dataset_revisions,
    sequence integer NOT NULL,          UNIQUE (revision_id, sequence),
    changed_keys text[] NOT NULL, document jsonb NOT NULL,
    -- [db] revision_amendments_document_is_an_object CHECK: object shape
    reclassified boolean NOT NULL DEFAULT false,
    created_by text NOT NULL, created_at timestamptz NOT NULL
);

-- ============================================================================
-- 2. Raw ingest workflow
-- ============================================================================

CREATE TABLE ingest_sessions (
    id uuid PRIMARY KEY,
    dataset_id uuid NOT NULL REFERENCES datasets,
    revision_id uuid UNIQUE NOT NULL, revision_number integer NOT NULL,
    manifest_sha256 text NOT NULL,
    state text NOT NULL,  -- PREPARING|UPLOADING|VERIFYING|COMMITTING|RECOVERING|COMMITTED|ABORTED|FAILED
    -- [db] ingest_sessions_state_check: CHECK restricts state to the vocabulary above
    etag integer NOT NULL DEFAULT 1,
    expires_at timestamptz NOT NULL,
    created_by text NOT NULL, created_at timestamptz NOT NULL, updated_at timestamptz NOT NULL
    -- [db] trigger ingest_sessions_revision_guard: a session may claim
    -- COMMITTED only about the revision it reserved - same id, dataset,
    -- revision_number and manifest_sha256 - checked FOR KEY SHARE
);
-- [db] one_open_ingest_per_dataset: partial unique index, at most ONE open
-- ingest per dataset, excludes only COMMITTED/ABORTED/FAILED
-- [db] one_claim_per_revision_number: partial unique index on
-- (dataset_id, revision_number) excluding ABORTED/FAILED - a dead session's
-- number is freed for retry, a COMMITTED one stays spent forever
-- [db] index ingest_sessions_dataset (dataset_id) - neither partial unique
-- index above serves a predicate-free lookup
-- [db] index ingest_sessions_lapsing (expires_at) WHERE state IN
-- ('PREPARING','UPLOADING','VERIFYING') - the expiry sweep's listing

CREATE TABLE ingest_commit_intents (
    ingest_id uuid PRIMARY KEY REFERENCES ingest_sessions ON DELETE RESTRICT,
    command bytea NOT NULL,
    manifest bytea NOT NULL,
    metadata bytea NOT NULL,
    committed bytea NOT NULL,
    command_sha256 text GENERATED ALWAYS AS (encode(sha256(command), 'hex')) STORED,
    manifest_sha256 text GENERATED ALWAYS AS (encode(sha256(manifest), 'hex')) STORED,
    metadata_sha256 text GENERATED ALWAYS AS (encode(sha256(metadata), 'hex')) STORED,
    committed_sha256 text GENERATED ALWAYS AS (encode(sha256(committed), 'hex')) STORED,
    committed_by text NOT NULL,
    committed_at timestamptz NOT NULL
);
-- [db] trigger ingest_commit_intents_immutable: refuses UPDATE and DELETE

CREATE TABLE ingest_recoveries (
    ingest_id uuid PRIMARY KEY REFERENCES ingest_sessions ON DELETE RESTRICT,
    attempt_id uuid NOT NULL UNIQUE,
    original_path text NOT NULL CHECK (length(original_path) > 0),
    candidate_path text NOT NULL CHECK (length(candidate_path) > 0),
    checkpoint text NOT NULL CHECK (checkpoint IN ('CLAIMED', 'RELOCATED', 'MATERIALIZED', 'PUBLISHED', 'RECORDED')),
    actor text NOT NULL CHECK (length(actor) > 0),
    started_at timestamptz NOT NULL,
    updated_at timestamptz NOT NULL CHECK (updated_at >= started_at),
    CHECK (original_path <> candidate_path)
);

CREATE TABLE ingest_files (
    file_id uuid PRIMARY KEY,
    ingest_id uuid NOT NULL REFERENCES ingest_sessions ON DELETE CASCADE,
    path text NOT NULL,                 UNIQUE (ingest_id, path),
    size bigint NOT NULL, expected_sha256 text NOT NULL,
    action text NOT NULL CHECK (action = 'upload'),
    state text NOT NULL DEFAULT 'PENDING',
    -- [db] ingest_files_state_vocabulary CHECK IN ('PENDING','COMPLETE'):
    -- PENDING until every part is in the envelope and proven
    part_count integer NOT NULL,
    -- [db] ingest_files_part_count_positive CHECK: >= 1,
    completed_parts jsonb NOT NULL DEFAULT '[]'
    -- [db] ingest_files_completed_parts_is_an_array CHECK: array shape -
    -- the resume ledger for a multipart upload, the one jsonb column that
    -- is not an object
);

-- ============================================================================
-- 3. Identity and RBAC (0002)
--
--    principal --< role_bindings >-- roles --< role_capabilities >-- capabilities
--    Bindings inherit downward: SYSTEM > ORGANIZATION > PROJECT > DATASET.
--    Layer restrictions live on role_capabilities.layers. Roles are for
--    humans only (0007): no role carries silver/gold data.write, and
--    role_bindings_guard refuses any sa: principal outright - a service
--    account's authority (dataset CRUD + silver/gold read/write across its
--    owning organization) is intrinsic to the principal kind, synthesized
--    from its service_accounts row (rbac.roles.service_account_bindings),
--    never stored as a binding.
-- ============================================================================

CREATE TABLE principals (
    id uuid PRIMARY KEY,
    kind text NOT NULL,                 -- 'user' | 'service_account'
    subject text UNIQUE NOT NULL,       -- token subject; bindings use user:/sa: prefix
    display_name text NOT NULL DEFAULT '',
    idp_subject text UNIQUE,            -- OIDC sub claim; users only (CHECK)
    disabled_at timestamptz, created_at timestamptz NOT NULL
);

CREATE TABLE service_accounts (        -- owned by an organization; roleless (0007):
                                       -- this row IS the whole grant
    principal_id uuid PRIMARY KEY REFERENCES principals,
    organization_id uuid NOT NULL REFERENCES organizations,
    name text NOT NULL,                 UNIQUE (organization_id, name),
    created_by text NOT NULL, created_at timestamptz NOT NULL
    -- [db] trigger service_accounts_kind_guard: principal must be kind service_account
);

CREATE TABLE roles (                   -- seeded from huron.pkg.rbac.roles.ROLES
    code text PRIMARY KEY,              -- reader | developer | project_admin |
                                        -- organization_admin | platform_owner
                                        -- data_steward removed (0006);
                                        -- pipeline + ingest_pipeline removed (0007)
    title text NOT NULL, description text NOT NULL DEFAULT '',
    allowed_principal_kinds text[] NOT NULL,  -- post-0007: {user} for every role
    bindable_scopes text[] NOT NULL,          -- platform_owner: {SYSTEM}
    is_system boolean NOT NULL DEFAULT true
);

CREATE TABLE capabilities (
    code text PRIMARY KEY,               -- e.g. organization.update, data.write
    description text NOT NULL DEFAULT ''
);

CREATE TABLE role_capabilities (
    role_code text NOT NULL REFERENCES roles ON DELETE CASCADE,
    -- [db] role_capabilities_role_code_fkey ON DELETE CASCADE: a role's
    -- capability rows are its own contents and go with it, not a citation
    capability_code text NOT NULL REFERENCES capabilities,
    -- [db] role_capabilities_capability_code_fkey ON DELETE NO ACTION:
    -- deleting a capability must not silently narrow every role that grants it
    layers text[],                      -- NULL = all layers; e.g. {raw,bronze}
    PRIMARY KEY (role_code, capability_code)
);

CREATE TABLE role_bindings (           -- (principal, role, scope): the grant
    id uuid PRIMARY KEY,
    principal text NOT NULL,            -- user:{subject} | group:{name} | sa:{subject}
    role_code text NOT NULL REFERENCES roles,
    -- [db] role_bindings_role_fk ON DELETE NO ACTION: deleting a role
    -- must not silently revoke a live grant
    scope_type text NOT NULL,           -- SYSTEM | ORGANIZATION | PROJECT | DATASET
    scope_id uuid,                      -- NULL iff SYSTEM (CHECK)
    effect text NOT NULL,               -- ALLOW | DENY (DENY wins at decision time)
    conditions jsonb NOT NULL DEFAULT '{}',
    -- [db] role_bindings_conditions_is_an_object CHECK: object shape
    expires_at timestamptz,
    created_by text NOT NULL, created_at timestamptz NOT NULL,
    UNIQUE NULLS NOT DISTINCT (principal, role_code, scope_type, scope_id)
    -- [db] trigger role_bindings_guard: principal kind and scope level must be
    -- allowed by the role (the database half of the RBAC invariants)
);
-- [db] index role_bindings_role (role_code)
-- [db] index role_bindings_scope (scope_type, scope_id) - bindings_at's
-- scope listing; the old scope index is dropped as a strict subset of
-- role_bindings_no_duplicates, which already leads with the same column

CREATE TABLE api_keys (
    id uuid PRIMARY KEY,
    key_id text UNIQUE NOT NULL,        -- token format: hk_{key_id}_{secret}
    owner_subject text NOT NULL,
    owner_kind text NOT NULL DEFAULT 'user',
    name text NOT NULL,
    secret_sha256 text NOT NULL,        -- only the hash is stored
    scopes text[] NOT NULL,
    project_id uuid REFERENCES projects,
    expires_at timestamptz NOT NULL,    -- keys always expire
    last_used_at timestamptz, revoked_at timestamptz, created_at timestamptz NOT NULL
);
-- [db] index api_keys_project (project_id)

-- Password + session login (0005). local_credentials is admin-provisioned,
-- users only (trigger local_credentials_kind_guard); sessions is the
-- server-side half of the cookie login - the browser holds the secret,
-- only its SHA-256 lands here.
CREATE TABLE local_credentials (
    principal_id uuid PRIMARY KEY REFERENCES principals,
    password_hash text NOT NULL,        -- argon2id string (CHECK '$argon2id$%')
    updated_at timestamptz NOT NULL, updated_by text NOT NULL
);

CREATE TABLE sessions (
    id uuid PRIMARY KEY,
    secret_sha256 text NOT NULL,        -- CHECK ^[0-9a-f]{64}$
    csrf_token text NOT NULL,
    subject text NOT NULL, groups text[] NOT NULL DEFAULT '{}',
    authentication_method text NOT NULL,  -- 'oidc' | 'password'
    created_at timestamptz NOT NULL, last_seen_at timestamptz NOT NULL,
    idle_expires_at timestamptz NOT NULL, absolute_expires_at timestamptz NOT NULL,
    revoked_at timestamptz
    -- [db] CHECK (idle_expires_at <= absolute_expires_at)
);
-- [db] partial index sessions_subject_active (subject) WHERE revoked_at IS NULL

-- ============================================================================
-- 4. Governance: policies, purge, retention, profiles
-- ============================================================================

CREATE TABLE policies (
    id uuid PRIMARY KEY,
    policy_type text NOT NULL,          -- retention | layer_standard | access | ...
    name text NOT NULL,
    spec jsonb NOT NULL,                -- shape varies by policy_type
    -- [db] policies_spec_is_an_object CHECK: object shape - the whole of
    -- what the database can assert about an open, per-policy_type interior
    created_by text NOT NULL, created_at timestamptz NOT NULL
);

CREATE TABLE policy_attachments (      -- attach requires {org,project,dataset}.policy_attach
    policy_id uuid NOT NULL REFERENCES policies,
    scope_type text NOT NULL,           -- ORGANIZATION | PROJECT | DATASET
    scope_id uuid NOT NULL,
    attached_by text NOT NULL, attached_at timestamptz NOT NULL,
    PRIMARY KEY (policy_id, scope_type, scope_id)
);
-- [db] policy_attachments_scope: index on (scope_type, scope_id) - the same
-- scope-listing access path role_bindings_scope serves on the sibling table

CREATE TABLE purge_records (           -- two-person purge: approver <> requester (CHECK)
    id uuid PRIMARY KEY,
    revision_id uuid NOT NULL REFERENCES dataset_revisions,
    reason text NOT NULL,
    requested_by text NOT NULL, requested_at timestamptz NOT NULL,
    approved_by text, approved_at timestamptz, executed_at timestamptz,
    state text NOT NULL DEFAULT 'REQUESTED'
    -- [db] purge_records_state_vocabulary CHECK IN ('REQUESTED','APPROVED',
    -- 'EXECUTED'): one member per timestamp column above
);
-- [db] index purge_records_revision (revision_id)

CREATE TABLE retention_holds (
    id uuid PRIMARY KEY,
    scope_kind text NOT NULL,           -- PROJECT | DATASET | REVISION
    scope_id uuid NOT NULL,
    kind text NOT NULL,                 -- PIN | LEGAL_HOLD
    reason text NOT NULL,
    created_by text NOT NULL, created_at timestamptz NOT NULL, released_at timestamptz
);

CREATE TABLE science_profiles (        -- published (name, version) immutable
    name text NOT NULL, version text NOT NULL,  PRIMARY KEY (name, version),
    document jsonb NOT NULL, document_sha256 text NOT NULL,
    -- [db] science_profiles_document_is_an_object CHECK: object shape
    -- [db] science_profiles_document_sha256_format: ^[0-9a-f]{64}$,
    -- the format every other *_sha256 column in the schema already carries
    published_by text NOT NULL, published_at timestamptz NOT NULL
);

-- ============================================================================
-- 5. Published representations: bronze/silver/gold state
-- ============================================================================

CREATE TABLE snapshots (               -- one row per published Icechunk snapshot
    id uuid PRIMARY KEY,
    dataset_id uuid REFERENCES datasets,   -- NULL only for gold (CHECK); bronze/silver always name one
    layer text NOT NULL,                -- bronze | silver | gold
    repo_uri text NOT NULL, snapshot_id text NOT NULL,  UNIQUE (repo_uri, snapshot_id),
    state text NOT NULL, provenance jsonb NOT NULL,   -- urn:huron:snapshot-provenance:1
    validation_evidence jsonb, published_at timestamptz
    -- [db] snapshots_state_vocabulary CHECK IN ('CANDIDATE','PUBLISHED',
    -- 'SUPERSEDED','FAILED')
    -- [db] CHECK (layer = 'gold' OR dataset_id IS NOT NULL)
    -- [db] CHECK (provenance->>'kind' IS NOT NULL AND provenance->>'kind' IN
    --        ('promotion','external','derivation'))   -- invariant N; NULL-safe on purpose
    -- [db] CHECK (layer <> 'gold' OR provenance->>'kind' IS NOT DISTINCT FROM 'derivation')
    -- [db] snapshots_provenance_is_an_object CHECK: object shape, beside
    -- the two invariant-N CHECKs above, which 0008 does not touch
    -- [db] snapshots_validation_evidence_is_an_object CHECK: NULL (not
    -- yet validated) or object - never the JSON null literal
);
-- [db] index snapshots_dataset (dataset_id)

CREATE TABLE products (                -- gold products per project
    id uuid PRIMARY KEY,
    project_id uuid NOT NULL REFERENCES projects,
    dataset_id uuid,                    -- set: single-source (lives under the dataset);
                                        -- NULL: fused (lives under the project)
    slug text NOT NULL,                 UNIQUE (project_id, slug),
    title text NOT NULL, shape text NOT NULL,   -- array | tabular
    lifecycle_state text NOT NULL DEFAULT 'ACTIVE', created_at timestamptz NOT NULL
    -- [db] products_lifecycle_state_vocabulary CHECK IN ('ACTIVE',
    -- 'DEPRECATED','RETIRED'): a distinct vocabulary from datasets' - a
    -- deprecated product is still the product, discouraged, not a slug mistake
    -- [db] FOREIGN KEY (dataset_id, project_id) REFERENCES datasets (id, project_id):
    -- a single-source product's dataset must belong to its own project
    -- [db] products_dataset_id_fkey dropped: strictly subsumed by the
    -- composite FK above - a row satisfying (dataset_id, project_id) against
    -- datasets (id, project_id) necessarily satisfies dataset_id alone
);
-- [db] index products_dataset_project (dataset_id, project_id)

CREATE TABLE product_versions (
    id uuid PRIMARY KEY,
    product_id uuid NOT NULL REFERENCES products,
    semver text NOT NULL,               UNIQUE (product_id, semver),
    state text NOT NULL,
    -- [db] product_versions_state_vocabulary CHECK IN ('CANDIDATE',
    -- 'PUBLISHED','STALE','SUPERSEDED','WITHDRAWN'); the CHECK does not
    -- require stale_reason/withdrawn_at to agree with state
    snapshot_id uuid REFERENCES snapshots,
    derivation_record jsonb NOT NULL, stale_reason text,
    -- [db] product_versions_derivation_record_is_an_object CHECK: object shape
    published_at timestamptz, withdrawn_at timestamptz
);
-- [db] index product_versions_snapshot (snapshot_id)

CREATE TABLE lineage_edges (
    id uuid PRIMARY KEY,
    upstream_kind text NOT NULL, upstream_id uuid NOT NULL,
    downstream_kind text NOT NULL, downstream_id uuid NOT NULL,
    -- [db] lineage_edges_upstream_kind_vocabulary and
    -- lineage_edges_downstream_kind_vocabulary, both CHECK IN ('raw_revision',
    -- 'bronze_snapshot','silver_snapshot','gold_version'): one node kind per
    -- table an id lives in; both columns draw on the full set - a recomputed
    -- product version's supersession edge is gold_version on both ends at once
    region jsonb, created_at timestamptz NOT NULL,
    -- [db] lineage_edges_region_is_an_object CHECK: NULL (the whole
    -- upstream contributes) or object naming the named selectors that narrow it
    UNIQUE (upstream_kind, upstream_id, downstream_kind, downstream_id)
);

-- ============================================================================
-- 6. Operational plumbing
-- ============================================================================

CREATE TABLE audit_events (
    id uuid PRIMARY KEY, kind text NOT NULL,
    -- [db] audit_events_kind_format CHECK: lowercase dotted-or-flat
    -- snake-case name, length 2-63. Open on purpose, not enumerated: one entry
    -- per mutating route and per denied operation, so refusing an unforeseen
    -- kind would abort the transaction being recorded
    actor text NOT NULL, subject_kind text NOT NULL, subject_id uuid,
    payload jsonb NOT NULL,
    -- [db] audit_events_payload_is_an_object CHECK: object shape
    created_at timestamptz NOT NULL
);
-- [db] index audit_events_created_at (created_at, id)

CREATE TABLE outbox_events (           -- transactional outbox -> search projection etc.
    id uuid PRIMARY KEY, kind text NOT NULL, subject_id uuid NOT NULL,
    -- [db] outbox_events_kind_format CHECK: lowercase dotted-or-flat
    -- snake-case name, length 2-63. Open on purpose, not enumerated: the
    -- consumer set grows a phase at a time and refusing an unforeseen kind
    -- inside the catalog-commit transaction is worse than recording it
    payload jsonb NOT NULL, created_at timestamptz NOT NULL, processed_at timestamptz
    -- [db] outbox_events_payload_is_an_object CHECK: object shape
);
-- [db] outbox_unprocessed: partial index on (created_at, id) WHERE
-- processed_at IS NULL - the claim access path, FOR UPDATE SKIP LOCKED

CREATE TABLE idempotency_records (
    principal text NOT NULL, key text NOT NULL,  PRIMARY KEY (principal, key),
    request_sha256 text NOT NULL, status_code integer NOT NULL, response jsonb NOT NULL,
    -- [db] idempotency_records_response_is_an_object CHECK: object shape
    created_at timestamptz NOT NULL, expires_at timestamptz NOT NULL
);

CREATE TABLE jobs (
    id uuid PRIMARY KEY, kind text NOT NULL, subject_id uuid NOT NULL,
    -- [db] jobs_kind_vocabulary CHECK IN ('bronze_build','canonicalize',
    -- 'product_run','validate','polaris_sync','retention','reconcile'): one
    -- kind per documented job runner; a kind no runner claims is a work
    -- order that sits QUEUED forever rather than failing
    image_digest text NOT NULL, state text NOT NULL DEFAULT 'QUEUED',
    -- [spec] vocabulary undecided: only QUEUED is evidenced; whether state is
    -- the truth or a denormalization of claimed_at/completed_at/attempts is
    -- unresolved, so constraining it now would freeze the wrong answer
    payload jsonb NOT NULL DEFAULT '{}', attempts integer NOT NULL DEFAULT 0,
    -- [db] jobs_payload_is_an_object CHECK: object shape
    available_at timestamptz NOT NULL, claimed_at timestamptz, completed_at timestamptz,
    created_at timestamptz NOT NULL
);
-- [db] jobs_claim: partial index on (available_at, id) WHERE state = 'QUEUED' -
-- the claim access path, FOR UPDATE SKIP LOCKED

CREATE TABLE reconciliation_findings (
    id uuid PRIMARY KEY, code text NOT NULL, severity text NOT NULL,
    -- [spec] vocabulary undecided: no severity vocabulary exists in the design
    -- record yet; code already carries the finding type
    path text, subject_id uuid, detail jsonb NOT NULL,
    -- [db] reconciliation_findings_detail_is_an_object CHECK: object shape
    found_at timestamptz NOT NULL, resolved_at timestamptz
);
