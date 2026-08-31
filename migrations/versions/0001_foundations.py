"""P1 foundations plus registries required by later phases."""

from migrations._ddl import execute_sql

revision = "0001_foundations"
down_revision = None
branch_labels = None
depends_on = None


DDL = r"""
CREATE TABLE organizations (
    id uuid PRIMARY KEY,
    slug text NOT NULL UNIQUE CHECK (slug ~ '^[a-z0-9][a-z0-9-]{1,61}$' AND slug !~ '--'),
    title text NOT NULL,
    description text NOT NULL DEFAULT '',
    lifecycle_state text NOT NULL DEFAULT 'ACTIVE',
    generation integer NOT NULL DEFAULT 1 CHECK (generation > 0),
    version integer NOT NULL DEFAULT 1 CHECK (version > 0),
    created_at timestamptz NOT NULL,
    updated_at timestamptz NOT NULL
);

CREATE TABLE projects (
    id uuid PRIMARY KEY,
    organization_id uuid NOT NULL REFERENCES organizations(id),
    slug text NOT NULL CHECK (slug ~ '^[a-z0-9][a-z0-9-]{1,61}$' AND slug !~ '--'),
    title text NOT NULL,
    description text NOT NULL DEFAULT '',
    classification_default text NOT NULL,
    raw_retention_policy jsonb NOT NULL DEFAULT '{}'::jsonb,
    quota_bytes bigint CHECK (quota_bytes IS NULL OR quota_bytes >= 0),
    dataset_creation_mode text NOT NULL DEFAULT 'steward_approval',
    lifecycle_state text NOT NULL DEFAULT 'ACTIVE',
    generation integer NOT NULL DEFAULT 1 CHECK (generation > 0),
    version integer NOT NULL DEFAULT 1 CHECK (version > 0),
    created_at timestamptz NOT NULL,
    updated_at timestamptz NOT NULL,
    UNIQUE (organization_id, slug)
);

CREATE TABLE datasets (
    id uuid PRIMARY KEY,
    project_id uuid NOT NULL REFERENCES projects(id),
    slug text NOT NULL CHECK (slug ~ '^[a-z0-9][a-z0-9-]{1,79}$' AND slug !~ '--'),
    title text NOT NULL,
    description text NOT NULL DEFAULT '',
    owner_group text,
    profile_name text NOT NULL,
    profile_version text NOT NULL,
    contract_version text,
    data_classification text NOT NULL,
    lifecycle_state text NOT NULL DEFAULT 'DRAFT',
    generation integer NOT NULL DEFAULT 1 CHECK (generation > 0),
    version integer NOT NULL DEFAULT 1 CHECK (version > 0),
    created_at timestamptz NOT NULL,
    updated_at timestamptz NOT NULL,
    UNIQUE (project_id, slug)
);

CREATE TABLE dataset_revisions (
    id uuid PRIMARY KEY,
    dataset_id uuid NOT NULL REFERENCES datasets(id),
    revision_number integer NOT NULL CHECK (revision_number BETWEEN 1 AND 999999),
    manifest_sha256 text NOT NULL CHECK (manifest_sha256 ~ '^[0-9a-f]{64}$'),
    metadata_sha256 text NOT NULL CHECK (metadata_sha256 ~ '^[0-9a-f]{64}$'),
    revision_path text NOT NULL UNIQUE,
    file_count integer NOT NULL CHECK (file_count > 0),
    total_bytes bigint NOT NULL CHECK (total_bytes >= 0),
    state text NOT NULL DEFAULT 'COMMITTED',
    committed_by text NOT NULL,
    committed_at timestamptz NOT NULL,
    UNIQUE (dataset_id, revision_number),
    UNIQUE (dataset_id, manifest_sha256)
);

CREATE TABLE releases (
    id uuid PRIMARY KEY,
    dataset_id uuid NOT NULL REFERENCES datasets(id),
    tag text NOT NULL CHECK (tag ~ '^[a-z0-9][a-z0-9._-]{1,62}$'),
    revision_id uuid NOT NULL REFERENCES dataset_revisions(id),
    title text,
    created_by text NOT NULL,
    created_at timestamptz NOT NULL,
    withdrawn_at timestamptz,
    withdrawn_reason text,
    UNIQUE (dataset_id, tag),
    CHECK ((withdrawn_at IS NULL) = (withdrawn_reason IS NULL))
);

CREATE FUNCTION releases_immutable() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF (NEW.id, NEW.dataset_id, NEW.tag, NEW.revision_id, NEW.title, NEW.created_by, NEW.created_at)
       IS DISTINCT FROM
       (OLD.id, OLD.dataset_id, OLD.tag, OLD.revision_id, OLD.title, OLD.created_by, OLD.created_at)
    THEN RAISE EXCEPTION 'release tags are immutable';
    END IF;
    RETURN NEW;
END $$;
CREATE TRIGGER releases_immutable_before_update BEFORE UPDATE ON releases
FOR EACH ROW EXECUTE FUNCTION releases_immutable();

CREATE TABLE revision_amendments (
    id uuid PRIMARY KEY,
    revision_id uuid NOT NULL REFERENCES dataset_revisions(id),
    sequence integer NOT NULL CHECK (sequence > 0),
    changed_keys text[] NOT NULL,
    document jsonb NOT NULL,
    reclassified boolean NOT NULL DEFAULT false,
    created_by text NOT NULL,
    created_at timestamptz NOT NULL,
    UNIQUE (revision_id, sequence)
);

CREATE TABLE ingest_sessions (
    id uuid PRIMARY KEY,
    dataset_id uuid NOT NULL REFERENCES datasets(id),
    revision_id uuid NOT NULL UNIQUE,
    revision_number integer NOT NULL CHECK (revision_number BETWEEN 1 AND 999999),
    manifest_sha256 text NOT NULL CHECK (manifest_sha256 ~ '^[0-9a-f]{64}$'),
    state text NOT NULL CHECK (state IN (
      'PREPARING','UPLOADING','VERIFYING','COMMITTING','COMMITTED','ABORTED','FAILED'
    )),
    etag integer NOT NULL DEFAULT 1 CHECK (etag > 0),
    expires_at timestamptz NOT NULL,
    created_by text NOT NULL,
    created_at timestamptz NOT NULL,
    updated_at timestamptz NOT NULL,
    UNIQUE (dataset_id, revision_number)
);
CREATE UNIQUE INDEX one_open_ingest_per_dataset ON ingest_sessions (dataset_id)
WHERE state NOT IN ('COMMITTED', 'ABORTED', 'FAILED');

CREATE TABLE ingest_files (
    file_id uuid PRIMARY KEY,
    ingest_id uuid NOT NULL REFERENCES ingest_sessions(id) ON DELETE CASCADE,
    path text NOT NULL,
    size bigint NOT NULL CHECK (size >= 0),
    expected_sha256 text NOT NULL CHECK (expected_sha256 ~ '^[0-9a-f]{64}$'),
    action text NOT NULL CHECK (action IN ('upload','hardlink')),
    state text NOT NULL DEFAULT 'PENDING',
    completed_parts jsonb NOT NULL DEFAULT '[]'::jsonb,
    UNIQUE (ingest_id, path)
);

CREATE TABLE role_bindings (
    id uuid PRIMARY KEY,
    principal text NOT NULL,
    role text NOT NULL,
    capabilities text[] NOT NULL,
    scope_type text NOT NULL CHECK (scope_type IN ('SYSTEM','ORGANIZATION','PROJECT','DATASET')),
    scope_id uuid,
    effect text NOT NULL CHECK (effect IN ('ALLOW','DENY')),
    conditions jsonb NOT NULL DEFAULT '{}'::jsonb,
    expires_at timestamptz,
    created_by text NOT NULL,
    created_at timestamptz NOT NULL,
    CHECK (
      (scope_type = 'SYSTEM' AND scope_id IS NULL)
      OR (scope_type <> 'SYSTEM' AND scope_id IS NOT NULL)
    )
);
CREATE INDEX role_bindings_principal_scope ON role_bindings (principal, scope_type, scope_id);

CREATE TABLE api_keys (
    id uuid PRIMARY KEY,
    key_id text NOT NULL UNIQUE,
    owner_subject text NOT NULL,
    name text NOT NULL,
    secret_sha256 text NOT NULL CHECK (secret_sha256 ~ '^[0-9a-f]{64}$'),
    scopes text[] NOT NULL,
    project_id uuid REFERENCES projects(id),
    expires_at timestamptz NOT NULL,
    last_used_at timestamptz,
    revoked_at timestamptz,
    created_at timestamptz NOT NULL
);

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

CREATE TABLE outbox_events (
    id uuid PRIMARY KEY,
    kind text NOT NULL,
    subject_id uuid NOT NULL,
    payload jsonb NOT NULL,
    created_at timestamptz NOT NULL,
    processed_at timestamptz
);
CREATE INDEX outbox_unprocessed ON outbox_events (created_at, id) WHERE processed_at IS NULL;

CREATE TABLE idempotency_records (
    principal text NOT NULL,
    key text NOT NULL,
    request_sha256 text NOT NULL CHECK (request_sha256 ~ '^[0-9a-f]{64}$'),
    status_code integer NOT NULL,
    response jsonb NOT NULL,
    created_at timestamptz NOT NULL,
    expires_at timestamptz NOT NULL,
    PRIMARY KEY (principal, key)
);

CREATE TABLE science_profiles (
    name text NOT NULL,
    version text NOT NULL,
    document jsonb NOT NULL,
    document_sha256 text NOT NULL,
    published_by text NOT NULL,
    published_at timestamptz NOT NULL,
    PRIMARY KEY (name, version)
);

CREATE TABLE purge_records (
    id uuid PRIMARY KEY,
    revision_id uuid NOT NULL REFERENCES dataset_revisions(id),
    reason text NOT NULL,
    requested_by text NOT NULL,
    requested_at timestamptz NOT NULL,
    approved_by text,
    approved_at timestamptz,
    executed_at timestamptz,
    state text NOT NULL DEFAULT 'REQUESTED',
    CHECK (approved_by IS NULL OR approved_by <> requested_by)
);

CREATE TABLE retention_holds (
    id uuid PRIMARY KEY,
    scope_kind text NOT NULL CHECK (scope_kind IN ('PROJECT','DATASET','REVISION')),
    scope_id uuid NOT NULL,
    kind text NOT NULL CHECK (kind IN ('PIN','LEGAL_HOLD')),
    reason text NOT NULL,
    created_by text NOT NULL,
    created_at timestamptz NOT NULL,
    released_at timestamptz
);

CREATE TABLE jobs (
    id uuid PRIMARY KEY,
    kind text NOT NULL,
    subject_id uuid NOT NULL,
    image_digest text NOT NULL,
    state text NOT NULL DEFAULT 'QUEUED',
    payload jsonb NOT NULL DEFAULT '{}'::jsonb,
    attempts integer NOT NULL DEFAULT 0,
    available_at timestamptz NOT NULL,
    claimed_at timestamptz,
    completed_at timestamptz,
    created_at timestamptz NOT NULL
);
CREATE INDEX jobs_claim ON jobs (available_at, id) WHERE state = 'QUEUED';

CREATE TABLE snapshots (
    id uuid PRIMARY KEY,
    dataset_id uuid REFERENCES datasets(id),
    layer text NOT NULL CHECK (layer IN ('bronze','silver','gold')),
    repo_uri text NOT NULL,
    snapshot_id text NOT NULL,
    state text NOT NULL,
    provenance jsonb NOT NULL,
    validation_evidence jsonb,
    published_at timestamptz,
    UNIQUE (repo_uri, snapshot_id)
);

CREATE TABLE products (
    id uuid PRIMARY KEY,
    project_id uuid NOT NULL REFERENCES projects(id),
    slug text NOT NULL,
    title text NOT NULL,
    shape text NOT NULL CHECK (shape IN ('array','tabular')),
    lifecycle_state text NOT NULL DEFAULT 'ACTIVE',
    created_at timestamptz NOT NULL,
    UNIQUE (project_id, slug)
);

CREATE TABLE product_versions (
    id uuid PRIMARY KEY,
    product_id uuid NOT NULL REFERENCES products(id),
    semver text NOT NULL,
    state text NOT NULL,
    snapshot_id uuid REFERENCES snapshots(id),
    derivation_record jsonb NOT NULL,
    stale_reason text,
    published_at timestamptz,
    withdrawn_at timestamptz,
    UNIQUE (product_id, semver)
);

CREATE TABLE lineage_edges (
    id uuid PRIMARY KEY,
    upstream_kind text NOT NULL,
    upstream_id uuid NOT NULL,
    downstream_kind text NOT NULL,
    downstream_id uuid NOT NULL,
    region jsonb,
    created_at timestamptz NOT NULL,
    UNIQUE (upstream_kind, upstream_id, downstream_kind, downstream_id)
);

CREATE TABLE reconciliation_findings (
    id uuid PRIMARY KEY,
    code text NOT NULL,
    severity text NOT NULL,
    path text,
    subject_id uuid,
    detail jsonb NOT NULL,
    found_at timestamptz NOT NULL,
    resolved_at timestamptz
);
"""


def upgrade() -> None:
    execute_sql(DDL)


def downgrade() -> None:
    execute_sql("""
    DROP TABLE IF EXISTS reconciliation_findings, lineage_edges, product_versions, products,
      snapshots, jobs, retention_holds, purge_records, science_profiles, idempotency_records,
      outbox_events, audit_events, api_keys, role_bindings, ingest_files, ingest_sessions,
      revision_amendments, releases, dataset_revisions, datasets, projects, organizations CASCADE;
    DROP FUNCTION IF EXISTS releases_immutable();
    """)
