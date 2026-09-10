"""Freeze verified Raw publication evidence and reserve exclusive recovery ownership."""

from migrations._ddl import execute_sql

revision = "0011_verified_raw"
down_revision = "0010_independent_raw"
branch_labels = None
depends_on = None

DDL = """
DO $$ BEGIN
    IF EXISTS (SELECT 1 FROM ingest_sessions
               WHERE state NOT IN ('COMMITTED', 'ABORTED', 'FAILED')) THEN
        RAISE EXCEPTION 'Nonterminal legacy ingests require fenced offline resolution';
    END IF;
END $$;
ALTER TABLE ingest_sessions DROP CONSTRAINT ingest_sessions_state_check;
ALTER TABLE ingest_sessions ADD CONSTRAINT ingest_sessions_state_check
    CHECK (state IN ('PREPARING', 'UPLOADING', 'VERIFYING', 'COMMITTING', 'RECOVERING',
                     'COMMITTED', 'ABORTED', 'FAILED'));

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
CREATE FUNCTION reject_commit_intent_mutation() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'Commit intent is immutable' USING ERRCODE = '23514';
END $$;
CREATE TRIGGER ingest_commit_intents_immutable BEFORE UPDATE OR DELETE ON ingest_commit_intents
    FOR EACH ROW EXECUTE FUNCTION reject_commit_intent_mutation();

CREATE TABLE ingest_recoveries (
    ingest_id uuid PRIMARY KEY REFERENCES ingest_sessions ON DELETE RESTRICT,
    attempt_id uuid NOT NULL UNIQUE,
    original_path text NOT NULL CHECK (length(original_path) > 0),
    candidate_path text NOT NULL CHECK (length(candidate_path) > 0),
    checkpoint text NOT NULL CHECK (checkpoint IN
        ('CLAIMED', 'RELOCATED', 'MATERIALIZED', 'PUBLISHED', 'RECORDED')),
    actor text NOT NULL CHECK (length(actor) > 0),
    started_at timestamptz NOT NULL,
    updated_at timestamptz NOT NULL CHECK (updated_at >= started_at),
    CHECK (original_path <> candidate_path)
);
CREATE FUNCTION protect_recovery_ownership() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF ROW(NEW.ingest_id, NEW.attempt_id, NEW.original_path, NEW.candidate_path,
           NEW.actor, NEW.started_at) IS DISTINCT FROM
       ROW(OLD.ingest_id, OLD.attempt_id, OLD.original_path, OLD.candidate_path,
           OLD.actor, OLD.started_at) THEN
        RAISE EXCEPTION 'Recovery ownership is immutable' USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END $$;
CREATE TRIGGER ingest_recoveries_ownership BEFORE UPDATE ON ingest_recoveries
    FOR EACH ROW EXECUTE FUNCTION protect_recovery_ownership();

"""


def upgrade() -> None:
    """Require terminal legacy sessions and install verified publication persistence."""
    execute_sql(DDL)


def downgrade() -> None:
    """Refuse rollback that would admit an incompatible upload writer.

    Raises:
        RuntimeError: Always; reverting the publication protocol requires fenced migration.
    """
    raise RuntimeError("verified Raw publication cannot be downgraded online")
