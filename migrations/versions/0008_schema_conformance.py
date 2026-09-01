"""Bring the metastore into conformance with the house PostgreSQL table-design
rules, closing the integrity gaps and constraint/index omissions the schema
audit proved on a live database.

A release cites a revision by ``revision_id`` alone today, independent of the
``dataset_id`` it also carries, so a release can anchor its citation to a
revision of an unrelated dataset - and releases are immutable, so the
mis-citation would be permanent. ``dataset_revisions_id_dataset_id_unique``
gives ``(id, dataset_id)`` a legal composite-FK target, and
``releases_revision_dataset_fk`` replaces the single-column
``releases_revision_id_fkey`` with one that checks both columns against it.
``releases_revision (revision_id, dataset_id)`` is the supporting index the
new FK needs, and by leading-column prefix also covers plain lookups on
``releases.revision_id``.

A sweep over the remaining foreign keys closes the rest of the gap: six
referencing columns had no supporting index, so a parent delete or a lookup
against them fell back to a sequential scan of a child table that grows with
usage, and ``role_bindings``' scope listing had nothing indexing
``scope_type`` at all. ``products_dataset_project``, ``product_versions_snapshot``,
``purge_records_revision``, ``snapshots_dataset``, ``api_keys_project`` and
``role_bindings_role`` add the missing indexes; ``role_bindings_scope`` adds
the scope-listing path. ``role_bindings_principal_scope`` is dropped as a
strict subset of ``role_bindings_no_duplicates``, which already leads with
the same column, and ``products_dataset_id_fkey`` is dropped as strictly
subsumed by the composite ``products_dataset_project_fk`` - the same
redundancy the release-citation fix above removes on ``releases``, on the
sibling table. Finally, the
role catalog is the one place a foreign key's parent key is natural text and
parent rows are really deleted, so its referential actions are restated as a
live choice rather than left as an unreachable default: deleting a role or a
capability must not silently revoke a live grant or narrow a role, so both
stay ``NO ACTION``; a role's own capability rows are its contents and are
dropped with it, so that edge alone is ``CASCADE``.

Eight columns across eight tables held a closed vocabulary in nothing but the
design record and application convention; each now carries a ``CHECK`` that
refuses anything outside it. ``organizations_lifecycle_state_vocabulary`` and
``projects_lifecycle_state_vocabulary`` pin the two hierarchy levels to
``ACTIVE``, today's only reachable value, so the first write of an
undocumented lifecycle value fails loudly instead of inventing a vocabulary
silently. ``datasets_lifecycle_state_vocabulary``,
``dataset_revisions_state_vocabulary``, ``snapshots_state_vocabulary`` and
``product_versions_state_vocabulary`` close the four vocabularies
``design/catalog-search.html`` already spells as a literal ``CHECK IN (…)``
list; this is the migration that makes that assertion true. ``products``
gets its own three-member lifecycle, distinct from a dataset's - a
deprecated product is still the product, discouraged, not a slug mistake
replaced by another row. ``purge_records_state_vocabulary`` closes the
three-point two-person purge. ``ingest_files.state``, ``jobs.state`` and
``reconciliation_findings.severity`` are the three columns this sweep
deliberately leaves unconstrained: none has a vocabulary the design record
has settled yet, and constraining one now would freeze a guess. None of the
eight rewrites existing data - every table is either empty in every real
database or already holds only values inside its new set - so none needs
``NOT VALID`` or a defensive backfill.

``science_profiles.document_sha256`` was the one ``*_sha256`` column in the
schema without the format CHECK every sibling digest column carries;
``science_profiles_document_sha256_format`` closes it.

Four more ``kind`` columns had no constraint at all. ``jobs.kind`` is a
dispatch key naming the digest-pinned container a job runner starts, so
``jobs_kind_vocabulary`` closes it to the seven documented workers -
``bronze_build``, ``canonicalize``, ``product_run``, ``validate``,
``polaris_sync``, ``retention`` and ``reconcile``. ``outbox_events.kind`` is
held to shape rather than enumerated: the outbox is written inside the
catalog-commit transaction and its consumer set grows a phase at a time, so
``outbox_events_kind_format`` requires the lowercase dotted-or-flat
snake-case form every machine-read identifier in this schema already uses,
without naming which kinds exist. ``audit_events.kind`` is open for the same
reason and gets the identical format, but that CHECK is deferred to the
revision that rebuilds ``audit_events``'s partitioned shape, so it is not
added here. ``lineage_edges.upstream_kind`` and ``lineage_edges.downstream_kind``
both draw on one closed vocabulary - ``raw_revision``, ``bronze_snapshot``,
``silver_snapshot`` and ``gold_version``, the four typed nodes the lineage
traversals resolve to a table each - and both get the full set on both ends,
because a recomputed product version's supersession edge is
``gold_version`` on both sides at once.

Fourteen ``jsonb`` columns had no top-level type of their own: a bare string,
number or boolean wrote and read back cleanly, and only a query against the
document's interior ever discovered otherwise. Thirteen get
``CHECK (jsonb_typeof(col) = 'object')``; ``ingest_files.completed_parts``, the
resume ledger for a multipart upload and the one column whose default is an
array rather than a record, gets ``CHECK (jsonb_typeof(col) = 'array')``
instead. ``snapshots.validation_evidence`` and ``lineage_edges.region`` are
nullable on purpose - SQL NULL is a real, distinct state in both, not an
absent object - so each is spelled ``col IS NULL OR jsonb_typeof(col) =
'object'`` rather than left to a bare CHECK's three-valued logic, making the
acceptance of SQL NULL visibly deliberate rather than an accident of it.
``snapshots.provenance`` gains this same top-level-type CHECK alongside
``0004``'s ``snapshots_provenance_states_an_origin`` and
``snapshots_gold_is_never_an_entry_layer``, neither of which this revision
touches. ``audit_events.payload`` is the fifteenth jsonb column and is
deliberately left out of this sweep: it belongs to the revision that rebuilds
``audit_events``'s partitioned shape.

``ingest_sessions.revision_id`` names a revision hours before that revision
exists - it is minted under the per-dataset ingest lock at ``begin_ingest``,
while the row it names is not written until the staging rename is durable, in
a later, separate transaction - so no declarative foreign key can express the
correspondence without also making ``PREPARING`` unrepresentable.
``ingest_session_revision_guard`` and the commit-time trigger
``ingest_sessions_revision_guard`` enforce it the only way that is
representable: at the moment a session claims success, the revision it names
must exist, belong to the session's dataset, carry the session's reserved
revision number, and hold the session's declared manifest digest. The trigger
fires only ``WHEN (NEW.state = 'COMMITTED')``, so every abort and failure
path - which name a revision that will never exist - is untouched.

Finally, ``ingest_sessions`` had carried a *total* ``UNIQUE (dataset_id,
revision_number)`` since ``0001``, which kept a reservation permanently spent
even when the session that made it never committed - contradicting the
gap-free numbering ``begin_ingest``'s ``max(committed) + 1`` allocator is
specified to produce, since a retry after an abort could only collide with
its own dead row. ``ingest_sessions_dataset_id_revision_number_key`` is
dropped and replaced by the partial unique index
``one_claim_per_revision_number``, whose predicate excludes exactly the two
terminal-failure states, ``ABORTED`` and ``FAILED`` - not ``COMMITTED``,
which stays inside the predicate because a number a session actually
committed must never become re-reservable. The dead session row itself is
kept, unchanged, as the record of the attempt.

Finally, ``audit_events`` stops being a partitioned table with one ``DEFAULT``
child and no writer. Nothing writes it yet and nothing that will ever create a
partition ahead of time exists either, so the partitioning bought nothing and
cost the one guarantee a partitioned table cannot express: ``PRIMARY KEY
(id, created_at)`` allowed two rows sharing an ``id`` at different
``created_at`` values, because a partitioned table's key must contain the
partition key. The table is renamed aside, rebuilt as a plain table with
``PRIMARY KEY (id)``, its rows copied across, and the old parent and its
``DEFAULT`` child dropped; ``audit_events_created_at`` on
``(created_at, id)`` - the first index ``created_at`` has ever had - replaces
the pruning a partitioned table would have offered, and serves both a
time-range filter and a keyset cursor. Renaming a table does not rename its
indexes, so without an explicit ``ALTER INDEX audit_events_pkey RENAME``
beside each ``ALTER TABLE ... RENAME``, the outgoing primary key's name stays
held by the relation being renamed away, and PostgreSQL silently names the
new primary key ``audit_events_pkey1`` instead of ``audit_events_pkey`` -
observed against a live database, not predicted, which is why both directions
rename the index they displace before creating its replacement. The two
constraints held back from the closed-vocabulary and jsonb-type sweeps above,
``audit_events_kind_format`` and ``audit_events_payload_is_an_object``, are
added last, against the rebuilt plain table, with their text unchanged from
what those sweeps would otherwise have written - a constraint added to the
partitioned parent would have been destroyed along with it.
"""

from migrations._ddl import execute_sql

revision = "0008_schema_conformance"
down_revision = "0007_roleless_service_accounts"
branch_labels = None
depends_on = None


DDL = r"""
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

-- science_profiles.document_sha256 is the digest of the document two columns
-- over; every other *_sha256 column in the schema already carries this format
-- CHECK (dataset_revisions, ingest_sessions, ingest_files, idempotency_records,
-- api_keys, local_credentials) and this was the one bare `text NOT NULL`.
ALTER TABLE science_profiles
    ADD CONSTRAINT science_profiles_document_sha256_format
        CHECK (document_sha256 ~ '^[0-9a-f]{64}$');

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

-- ------------------------------------------ ingest-session/revision guard
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

-- --------------------------------------------- reservation lifecycle (S7a)
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

-- audit_events.kind and audit_events.payload get the same shape and
-- top-level-type constraints as every other kind column and jsonb column in
-- the schema. They run here, against the plain table created above, because
-- a constraint added to the partitioned parent would have been destroyed
-- along with it.
ALTER TABLE audit_events
    ADD CONSTRAINT audit_events_kind_format
        CHECK (kind ~ '^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)*$'
               AND length(kind) BETWEEN 2 AND 63);

ALTER TABLE audit_events
    ADD CONSTRAINT audit_events_payload_is_an_object
        CHECK (jsonb_typeof(payload) = 'object');
"""


def upgrade() -> None:
    execute_sql(DDL)


def downgrade() -> None:
    execute_sql("""
    ALTER TABLE audit_events DROP CONSTRAINT IF EXISTS audit_events_payload_is_an_object;
    ALTER TABLE audit_events DROP CONSTRAINT IF EXISTS audit_events_kind_format;

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

    DROP INDEX IF EXISTS one_claim_per_revision_number;
    ALTER TABLE ingest_sessions
        ADD CONSTRAINT ingest_sessions_dataset_id_revision_number_key
            UNIQUE (dataset_id, revision_number);

    DROP TRIGGER IF EXISTS ingest_sessions_revision_guard ON ingest_sessions;
    DROP FUNCTION IF EXISTS ingest_session_revision_guard();

    ALTER TABLE reconciliation_findings
        DROP CONSTRAINT IF EXISTS reconciliation_findings_detail_is_an_object;
    ALTER TABLE lineage_edges DROP CONSTRAINT IF EXISTS lineage_edges_region_is_an_object;
    ALTER TABLE product_versions
        DROP CONSTRAINT IF EXISTS product_versions_derivation_record_is_an_object;
    ALTER TABLE snapshots
        DROP CONSTRAINT IF EXISTS snapshots_validation_evidence_is_an_object,
        DROP CONSTRAINT IF EXISTS snapshots_provenance_is_an_object;
    ALTER TABLE jobs DROP CONSTRAINT IF EXISTS jobs_payload_is_an_object;
    ALTER TABLE science_profiles
        DROP CONSTRAINT IF EXISTS science_profiles_document_is_an_object;
    ALTER TABLE idempotency_records
        DROP CONSTRAINT IF EXISTS idempotency_records_response_is_an_object;
    ALTER TABLE outbox_events DROP CONSTRAINT IF EXISTS outbox_events_payload_is_an_object;
    ALTER TABLE policies DROP CONSTRAINT IF EXISTS policies_spec_is_an_object;
    ALTER TABLE role_bindings DROP CONSTRAINT IF EXISTS role_bindings_conditions_is_an_object;
    ALTER TABLE ingest_files DROP CONSTRAINT IF EXISTS ingest_files_completed_parts_is_an_array;
    ALTER TABLE revision_amendments
        DROP CONSTRAINT IF EXISTS revision_amendments_document_is_an_object;
    ALTER TABLE projects DROP CONSTRAINT IF EXISTS projects_raw_retention_policy_is_an_object;

    ALTER TABLE lineage_edges
        DROP CONSTRAINT IF EXISTS lineage_edges_downstream_kind_vocabulary,
        DROP CONSTRAINT IF EXISTS lineage_edges_upstream_kind_vocabulary;
    ALTER TABLE outbox_events DROP CONSTRAINT IF EXISTS outbox_events_kind_format;
    ALTER TABLE jobs DROP CONSTRAINT IF EXISTS jobs_kind_vocabulary;

    ALTER TABLE science_profiles DROP CONSTRAINT IF EXISTS science_profiles_document_sha256_format;
    ALTER TABLE purge_records DROP CONSTRAINT IF EXISTS purge_records_state_vocabulary;
    ALTER TABLE product_versions DROP CONSTRAINT IF EXISTS product_versions_state_vocabulary;
    ALTER TABLE snapshots DROP CONSTRAINT IF EXISTS snapshots_state_vocabulary;
    ALTER TABLE dataset_revisions DROP CONSTRAINT IF EXISTS dataset_revisions_state_vocabulary;
    ALTER TABLE products DROP CONSTRAINT IF EXISTS products_lifecycle_state_vocabulary;
    ALTER TABLE datasets DROP CONSTRAINT IF EXISTS datasets_lifecycle_state_vocabulary;
    ALTER TABLE projects DROP CONSTRAINT IF EXISTS projects_lifecycle_state_vocabulary;
    ALTER TABLE organizations DROP CONSTRAINT IF EXISTS organizations_lifecycle_state_vocabulary;

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

    DROP INDEX IF EXISTS releases_revision;
    ALTER TABLE releases
        DROP CONSTRAINT IF EXISTS releases_revision_dataset_fk,
        ADD CONSTRAINT releases_revision_id_fkey
            FOREIGN KEY (revision_id) REFERENCES dataset_revisions (id);
    ALTER TABLE dataset_revisions DROP CONSTRAINT IF EXISTS dataset_revisions_id_dataset_id_unique;
    """)
