-- ============================================================================
-- Huron metastore: table architecture summary
-- ============================================================================
-- GENERATED DOCUMENTATION, NOT EXECUTED. The Alembic migrations under
-- migrations/versions/ are the authoritative DDL (0001_foundations,
-- 0002_rbac, 0003_layer_paths, 0004_entry_layers, 0005_auth,
-- 0006_role_simplification, 0007_roleless_service_accounts); regenerate
-- against a migrated database with
--     pg_dump --schema-only --no-owner huron
-- Types/constraints below are condensed; CHECKs are shown where they carry a
-- design rule. PostgreSQL structural state only - no metadata mirrors, no
-- text search (invariant A: LanceDB owns matching; sidecars authoritative).
--
-- ============================================================================
-- 1. Hierarchy: Organization -> Project -> Dataset -> revisions + release tags
-- ============================================================================

CREATE TABLE organizations (
    id uuid PRIMARY KEY,
    slug text UNIQUE NOT NULL,          -- ^[a-z0-9][a-z0-9-]{1,61}$, no '--'
    title text NOT NULL,
    description text NOT NULL DEFAULT '',
    lifecycle_state text NOT NULL DEFAULT 'ACTIVE',
    generation integer NOT NULL,        -- filesystem generation doc counter
    version integer NOT NULL,           -- optimistic-concurrency counter (ETag)
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
    quota_bytes bigint,                 -- NULL = unlimited
    lifecycle_state text NOT NULL DEFAULT 'ACTIVE',
    generation integer NOT NULL, version integer NOT NULL,
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
    generation integer NOT NULL, version integer NOT NULL,
    created_at timestamptz NOT NULL, updated_at timestamptz NOT NULL
);

CREATE TABLE dataset_revisions (      -- linear, gap-free, immutable
    id uuid PRIMARY KEY,
    dataset_id uuid NOT NULL REFERENCES datasets,
    revision_number integer NOT NULL,   -- 1..999999; UNIQUE (dataset_id, revision_number)
    manifest_sha256 text NOT NULL,      -- UNIQUE (dataset_id, manifest_sha256)
    metadata_sha256 text NOT NULL,
    revision_path text UNIQUE NOT NULL, -- /data/.../dataset/{...}/raw/revision/000042--{id}
    file_count integer NOT NULL, total_bytes bigint NOT NULL,
    state text NOT NULL DEFAULT 'COMMITTED',
    committed_by text NOT NULL, committed_at timestamptz NOT NULL
);

CREATE TABLE releases (               -- immutable tags on one revision (invariant M)
    id uuid PRIMARY KEY,
    dataset_id uuid NOT NULL REFERENCES datasets,
    tag text NOT NULL,                  UNIQUE (dataset_id, tag),
    revision_id uuid NOT NULL REFERENCES dataset_revisions,
    title text, created_by text NOT NULL, created_at timestamptz NOT NULL,
    withdrawn_at timestamptz, withdrawn_reason text
    -- trigger releases_immutable: every column except withdrawal is frozen;
    -- a wrong tag is withdrawn (tombstone), never repointed.
);

CREATE TABLE revision_amendments (    -- project-admin metadata amendments, append-only
    id uuid PRIMARY KEY,
    revision_id uuid NOT NULL REFERENCES dataset_revisions,
    sequence integer NOT NULL,          UNIQUE (revision_id, sequence),
    changed_keys text[] NOT NULL, document jsonb NOT NULL,
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
    state text NOT NULL,  -- PREPARING|UPLOADING|VERIFYING|COMMITTING|COMMITTED|ABORTED|FAILED
    etag integer NOT NULL,
    expires_at timestamptz NOT NULL,
    created_by text NOT NULL, created_at timestamptz NOT NULL, updated_at timestamptz NOT NULL
);
-- partial unique index: at most ONE open ingest per dataset (per-dataset lock)

CREATE TABLE ingest_files (
    file_id uuid PRIMARY KEY,
    ingest_id uuid NOT NULL REFERENCES ingest_sessions ON DELETE CASCADE,
    path text NOT NULL,                 UNIQUE (ingest_id, path),
    size bigint NOT NULL, expected_sha256 text NOT NULL,
    action text NOT NULL,               -- upload | hardlink (dedup from parent)
    state text NOT NULL DEFAULT 'PENDING',
    completed_parts jsonb NOT NULL DEFAULT '[]'
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
    -- trigger service_accounts_kind_guard: principal must be kind service_account
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
    code text PRIMARY KEY               -- e.g. organization.update, data.write
);

CREATE TABLE role_capabilities (
    role_code text NOT NULL REFERENCES roles ON DELETE CASCADE,
    capability_code text NOT NULL REFERENCES capabilities,
    layers text[],                      -- NULL = all layers; e.g. {raw,bronze}
    PRIMARY KEY (role_code, capability_code)
);

CREATE TABLE role_bindings (           -- (principal, role, scope): the grant
    id uuid PRIMARY KEY,
    principal text NOT NULL,            -- user:{subject} | group:{name} | sa:{subject}
    role_code text NOT NULL REFERENCES roles,
    scope_type text NOT NULL,           -- SYSTEM | ORGANIZATION | PROJECT | DATASET
    scope_id uuid,                      -- NULL iff SYSTEM (CHECK)
    effect text NOT NULL,               -- ALLOW | DENY (DENY wins at decision time)
    conditions jsonb NOT NULL DEFAULT '{}',
    expires_at timestamptz,
    created_by text NOT NULL, created_at timestamptz NOT NULL,
    UNIQUE NULLS NOT DISTINCT (principal, role_code, scope_type, scope_id)
    -- trigger role_bindings_guard: principal kind and scope level must be
    -- allowed by the role (the database half of the RBAC invariants)
);

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
    -- CHECK (idle_expires_at <= absolute_expires_at)
);
-- partial index sessions_subject_active (subject) WHERE revoked_at IS NULL

-- ============================================================================
-- 4. Governance: policies, purge, retention, profiles
-- ============================================================================

CREATE TABLE policies (
    id uuid PRIMARY KEY,
    policy_type text NOT NULL,          -- retention | layer_standard | access | ...
    name text NOT NULL,
    spec jsonb NOT NULL,                -- shape varies by policy_type
    created_by text NOT NULL, created_at timestamptz NOT NULL
);

CREATE TABLE policy_attachments (      -- attach requires {org,project,dataset}.policy_attach
    policy_id uuid NOT NULL REFERENCES policies,
    scope_type text NOT NULL,           -- ORGANIZATION | PROJECT | DATASET
    scope_id uuid NOT NULL,
    attached_by text NOT NULL, attached_at timestamptz NOT NULL,
    PRIMARY KEY (policy_id, scope_type, scope_id)
);

CREATE TABLE purge_records (           -- two-person purge: approver <> requester (CHECK)
    id uuid PRIMARY KEY,
    revision_id uuid NOT NULL REFERENCES dataset_revisions,
    reason text NOT NULL,
    requested_by text NOT NULL, requested_at timestamptz NOT NULL,
    approved_by text, approved_at timestamptz, executed_at timestamptz,
    state text NOT NULL DEFAULT 'REQUESTED'
);

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
    -- CHECK (layer = 'gold' OR dataset_id IS NOT NULL)
    -- CHECK (provenance->>'kind' IS NOT NULL AND provenance->>'kind' IN
    --        ('promotion','external','derivation'))   -- invariant N; NULL-safe on purpose
    -- CHECK (layer <> 'gold' OR provenance->>'kind' IS NOT DISTINCT FROM 'derivation')
);

CREATE TABLE products (                -- gold products per project
    id uuid PRIMARY KEY,
    project_id uuid NOT NULL REFERENCES projects,
    dataset_id uuid REFERENCES datasets,   -- set: single-source (lives under the dataset);
                                            -- NULL: fused (lives under the project)
    slug text NOT NULL,                 UNIQUE (project_id, slug),
    title text NOT NULL, shape text NOT NULL,   -- array | tabular
    lifecycle_state text NOT NULL DEFAULT 'ACTIVE', created_at timestamptz NOT NULL
    -- FOREIGN KEY (dataset_id, project_id) REFERENCES datasets (id, project_id):
    -- a single-source product's dataset must belong to its own project
);

CREATE TABLE product_versions (
    id uuid PRIMARY KEY,
    product_id uuid NOT NULL REFERENCES products,
    semver text NOT NULL,               UNIQUE (product_id, semver),
    state text NOT NULL,
    snapshot_id uuid REFERENCES snapshots,
    derivation_record jsonb NOT NULL, stale_reason text,
    published_at timestamptz, withdrawn_at timestamptz
);

CREATE TABLE lineage_edges (
    id uuid PRIMARY KEY,
    upstream_kind text NOT NULL, upstream_id uuid NOT NULL,
    downstream_kind text NOT NULL, downstream_id uuid NOT NULL,
    region jsonb, created_at timestamptz NOT NULL,
    UNIQUE (upstream_kind, upstream_id, downstream_kind, downstream_id)
);

-- ============================================================================
-- 6. Operational plumbing
-- ============================================================================

CREATE TABLE audit_events (            -- partitioned by created_at range
    id uuid NOT NULL, kind text NOT NULL, actor text NOT NULL,
    subject_kind text NOT NULL, subject_id uuid,
    payload jsonb NOT NULL, created_at timestamptz NOT NULL,
    PRIMARY KEY (id, created_at)
);

CREATE TABLE outbox_events (           -- transactional outbox -> search projection etc.
    id uuid PRIMARY KEY, kind text NOT NULL, subject_id uuid NOT NULL,
    payload jsonb NOT NULL, created_at timestamptz NOT NULL, processed_at timestamptz
);

CREATE TABLE idempotency_records (
    principal text NOT NULL, key text NOT NULL,  PRIMARY KEY (principal, key),
    request_sha256 text NOT NULL, status_code integer NOT NULL, response jsonb NOT NULL,
    created_at timestamptz NOT NULL, expires_at timestamptz NOT NULL
);

CREATE TABLE jobs (
    id uuid PRIMARY KEY, kind text NOT NULL, subject_id uuid NOT NULL,
    image_digest text NOT NULL, state text NOT NULL DEFAULT 'QUEUED',
    payload jsonb NOT NULL DEFAULT '{}', attempts integer NOT NULL DEFAULT 0,
    available_at timestamptz NOT NULL, claimed_at timestamptz, completed_at timestamptz,
    created_at timestamptz NOT NULL
);

CREATE TABLE reconciliation_findings (
    id uuid PRIMARY KEY, code text NOT NULL, severity text NOT NULL,
    path text, subject_id uuid, detail jsonb NOT NULL,
    found_at timestamptz NOT NULL, resolved_at timestamptz
);
