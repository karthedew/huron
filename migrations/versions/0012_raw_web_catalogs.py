"""Map external catalogs to Raw datasets and retain registration acknowledgements."""

from migrations._ddl import execute_sql

revision = "0012_raw_web_catalogs"
down_revision = "0011_verified_raw"
branch_labels = None
depends_on = None

DDL = """
CREATE TABLE raw_external_datasets (
    target_key text PRIMARY KEY CHECK (target_key ~ '^[0-9a-f]{64}$'),
    endpoint text NOT NULL CHECK (length(endpoint) BETWEEN 1 AND 2048),
    realm text NOT NULL CHECK (length(realm) BETWEEN 1 AND 256),
    catalog text NOT NULL CHECK (length(catalog) BETWEEN 1 AND 256),
    namespace text[] NOT NULL CHECK (cardinality(namespace) <= 32),
    name text NOT NULL CHECK (length(name) BETWEEN 1 AND 256),
    dataset_id uuid NOT NULL UNIQUE REFERENCES datasets(id) ON DELETE RESTRICT
);
CREATE TABLE raw_catalog_publications (
    revision_id uuid PRIMARY KEY REFERENCES dataset_revisions(id) ON DELETE RESTRICT,
    registered_at timestamptz NOT NULL DEFAULT now()
);
CREATE FUNCTION reject_raw_external_mutation() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'Raw catalog identity and registration evidence are immutable'
        USING ERRCODE = '23514';
END $$;
CREATE TRIGGER raw_external_datasets_immutable BEFORE UPDATE OR DELETE ON raw_external_datasets
    FOR EACH ROW EXECUTE FUNCTION reject_raw_external_mutation();
CREATE TRIGGER raw_catalog_publications_immutable BEFORE UPDATE OR DELETE ON raw_catalog_publications
    FOR EACH ROW EXECUTE FUNCTION reject_raw_external_mutation();
"""


def upgrade() -> None:
    """Install immutable mappings and publication receipts."""
    execute_sql(DDL)


def downgrade() -> None:
    """Refuse dropping identities while their Raw revisions still exist.

    Raises:
        RuntimeError: Always; recovery requires retaining registered identities.
    """
    raise RuntimeError("Raw catalog mappings require an explicit offline migration")
