"""Make Raw revisions independent submissions rather than parent-derived manifests.

Identical content is valid in distinct revisions. Legacy hardlink ledgers require
an explicit offline copy/re-ingestion before this migration; it never pretends that
changing database labels makes existing filesystem hardlinks independent.
"""

from migrations._ddl import execute_sql

revision = "0010_independent_raw"
down_revision = "0009_ingest_ledger"
branch_labels = None
depends_on = None

DDL = """
DO $$ BEGIN
    IF EXISTS (SELECT 1 FROM ingest_files WHERE action = 'hardlink') THEN
        RAISE EXCEPTION 'Legacy hardlinks require offline copy/re-ingestion before upgrade';
    END IF;
END $$;
ALTER TABLE dataset_revisions DROP CONSTRAINT dataset_revisions_dataset_id_manifest_sha256_key;
ALTER TABLE ingest_sessions DROP COLUMN parent_revision_id;
ALTER TABLE ingest_files DROP CONSTRAINT ingest_files_part_count_matches_action;
ALTER TABLE ingest_files DROP CONSTRAINT ingest_files_action_check;
ALTER TABLE ingest_files ADD CONSTRAINT ingest_files_action_check CHECK (action = 'upload');
ALTER TABLE ingest_files ADD CONSTRAINT ingest_files_part_count_positive CHECK (part_count >= 1);
"""


def upgrade() -> None:
    """Require complete uploads and allow repeated content in separate revisions."""
    execute_sql(DDL)


def downgrade() -> None:
    """Restore parent-era constraints, refusing duplicate content rather than deleting it."""
    execute_sql("""
    ALTER TABLE dataset_revisions ADD CONSTRAINT dataset_revisions_dataset_id_manifest_sha256_key
        UNIQUE (dataset_id, manifest_sha256);
    ALTER TABLE ingest_sessions ADD COLUMN parent_revision_id uuid;
    ALTER TABLE ingest_sessions ADD CONSTRAINT ingest_sessions_parent_revision_fk
        FOREIGN KEY (parent_revision_id, dataset_id) REFERENCES dataset_revisions (id, dataset_id);
    CREATE INDEX ingest_sessions_parent_revision
        ON ingest_sessions (parent_revision_id, dataset_id);
    ALTER TABLE ingest_files DROP CONSTRAINT ingest_files_part_count_positive;
    ALTER TABLE ingest_files DROP CONSTRAINT ingest_files_action_check;
    ALTER TABLE ingest_files ADD CONSTRAINT ingest_files_action_check
        CHECK (action IN ('upload', 'hardlink'));
    ALTER TABLE ingest_files ADD CONSTRAINT ingest_files_part_count_matches_action
        CHECK ((action = 'hardlink' AND part_count = 0) OR (action = 'upload' AND part_count >= 1));
    """)
