"""Retire the legacy Raw catalog and browser credential persistence."""

from migrations._ddl import execute_sql

revision = "0014_retire_legacy_raw"
down_revision = "0013_retire_releases"
branch_labels = None
depends_on = None

DDL = """
DROP TABLE raw_catalog_publications, raw_external_datasets, ingest_recoveries,
           ingest_commit_intents, ingest_files, purge_records, revision_amendments,
           ingest_sessions, dataset_revisions;
DROP FUNCTION reject_raw_external_mutation(), reject_commit_intent_mutation(),
              protect_recovery_ownership(), ingest_session_revision_guard();
DROP TABLE audit_events;
DROP TABLE outbox_events;
DROP TABLE sessions, local_credentials;
DROP FUNCTION local_credentials_kind_guard();
DROP TABLE reconciliation_findings;
DELETE FROM lineage_edges
 WHERE upstream_kind = 'raw_revision' OR downstream_kind = 'raw_revision';
ALTER TABLE lineage_edges
  DROP CONSTRAINT lineage_edges_upstream_kind_vocabulary,
  DROP CONSTRAINT lineage_edges_downstream_kind_vocabulary,
  ADD CONSTRAINT lineage_edges_upstream_kind_vocabulary
    CHECK (upstream_kind IN ('bronze_snapshot','silver_snapshot','gold_version')),
  ADD CONSTRAINT lineage_edges_downstream_kind_vocabulary
    CHECK (downstream_kind IN ('bronze_snapshot','silver_snapshot','gold_version'));
"""


def upgrade() -> None:
    """Discard legacy tables and restrict lineage to surviving representations."""
    execute_sql(DDL)


def downgrade() -> None:
    """Refuse restoring tables whose contents were discarded.

    Raises:
        RuntimeError: Always; discarded legacy data cannot be restored.
    """
    raise RuntimeError("legacy Raw and credential tables cannot be restored")
