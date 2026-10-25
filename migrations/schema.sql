-- ============================================================================
-- Huron metastore: table architecture summary
-- ============================================================================
-- HAND-MAINTAINED DOCUMENTATION. Not executed, and not generated: this is a
-- condensed map of what the Alembic revisions under migrations/versions/ build,
-- and the authoritative DDL is those revisions, never this file. The map exists
-- to carry what a schema dump cannot - the trigger annotations, the vocabularies,
-- and the invariant each rule serves. Do not replace it with pg_dump output.
--
-- Reflects: 0014_retire_legacy_raw
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
-- 1. Hierarchy: Organization -> Project -> Dataset
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

-- ============================================================================
-- 2. Identity and RBAC (0002)
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

CREATE TABLE roles (                   -- seeded from huron.core.security.roles.ROLES
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
    code text PRIMARY KEY,               -- e.g. organization.update, data.write;
                                         -- release.create removed (0013)
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

-- ============================================================================
-- 3. Governance: policies, purge, retention, profiles
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
-- 4. Published representations: bronze/silver/gold state
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
    -- lineage_edges_downstream_kind_vocabulary, both CHECK IN
    -- ('bronze_snapshot','silver_snapshot','gold_version'): one node kind per
    -- table an id lives in; both columns draw on the full set - a recomputed
    -- product version's supersession edge is gold_version on both ends at once
    region jsonb, created_at timestamptz NOT NULL,
    -- [db] lineage_edges_region_is_an_object CHECK: NULL (the whole
    -- upstream contributes) or object naming the named selectors that narrow it
    UNIQUE (upstream_kind, upstream_id, downstream_kind, downstream_id)
);

-- ============================================================================
-- 5. Operational plumbing
-- ============================================================================

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
