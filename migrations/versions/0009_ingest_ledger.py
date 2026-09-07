"""Give the raw ingest ledger its declared vocabulary, and the allocator its lookup paths.

The per-file ledger's own state (``huron.pkg.catalog.ingest.FileState``: ``PENDING``/``COMPLETE``)
was left open at ``0008`` - the vocabulary depended on the upload-plane's own shape, which had not
yet settled which state described a file's own progress separately from its ``completed_parts``.
It has: a file is ``PENDING`` until every part is in the envelope and proven, ``COMPLETE`` once it
is, and never a third thing. ``ingest_files_state_vocabulary`` closes it. Alongside it,
``part_count`` records what the upload plan already decided about a file when the session opened -
zero for a hardlink, at least one for an upload - and ``ingest_files_part_count_matches_action``
ties the two columns together so a row cannot claim a part count its own action rules out.
``part_count`` lands ``NOT NULL`` without a default: the table had no writer anywhere under
``src/`` when this migration was written, so it was empty in every deployment it ran against, and
the one row-inserting caller left is a raw-SQL test fixture, updated in the same change to supply
``part_count``.

``ingest_sessions`` gains the third piece of what an upload plan needs recorded: the revision its
dedup plan was computed against, the dataset's highest committed revision at the moment the session
opened, whose bytes a hardlinked file is linked from. A session that later linked from a revision
of some other dataset would be linking bytes outside its own dataset's tree, so the citation is a
composite foreign key against ``(id, dataset_id)`` - the same shape ``releases_revision_dataset_fk``
uses one migration back - rather than a bare reference to ``dataset_revisions.id`` alone. ``NULL``
is legal and means exactly what it says: this is the dataset's first revision, with no parent to
link from.

Three indexes complete the ledger's read paths. ``ingest_sessions``'s two indexes to date are both
partial and both narrow to a state subset before they narrow to ``dataset_id``, so neither
``one_open_ingest_per_dataset`` (``0001``) nor ``one_claim_per_revision_number`` (``0008``) serves
a predicate-free "every session of this dataset" scan: the ``datasets`` foreign key's own delete
check, a plain per-dataset listing, and the new parent-revision foreign key's lookup would each
sequential-scan the whole table. ``ingest_sessions_dataset`` is the plain index that closes that
gap, and ``ingest_sessions_parent_revision`` is the same fix for the column this migration adds.
``ingest_sessions_lapsing`` closes a third, narrower gap: an expiry pass lists every session still
open whose lease has lapsed, oldest first -
``state IN ('PREPARING','UPLOADING','VERIFYING') AND expires_at <= now()`` - a predicate the plain
dataset index cannot serve (it carries neither ``expires_at`` nor ``state``), and the two unique
indexes cannot serve either: neither is keyed on ``expires_at``, so neither can filter or order by
it. Session rows are never deleted, so without this index every pass, on every replica, walks
every session ever opened; the partial predicate keeps the index itself small, since at most one
row per dataset is ever open at a time.
"""

from migrations._ddl import execute_sql

revision = "0009_ingest_ledger"
down_revision = "0008_schema_conformance"
branch_labels = None
depends_on = None


DDL = r"""
-- The parent a session's upload plan was computed against: the dataset's
-- highest committed revision at reservation time, whose payload a
-- hardlinked file is linked from. NULL means the dataset has no revision
-- yet. The composite key, as for releases one migration back, keeps the
-- citation inside the session's own dataset - a session cannot link bytes
-- from a revision belonging to someone else's tree.
ALTER TABLE ingest_sessions ADD COLUMN parent_revision_id uuid;
ALTER TABLE ingest_sessions
    ADD CONSTRAINT ingest_sessions_parent_revision_fk
        FOREIGN KEY (parent_revision_id, dataset_id) REFERENCES dataset_revisions (id, dataset_id)
        ON DELETE NO ACTION ON UPDATE NO ACTION;
CREATE INDEX ingest_sessions_parent_revision ON ingest_sessions (parent_revision_id, dataset_id);

-- The two partial unique indexes on this table both narrow to a state
-- subset before dataset_id, so neither serves a predicate-free lookup: the
-- datasets foreign key's delete check and a plain per-dataset listing would
-- otherwise sequential-scan every session ever opened.
CREATE INDEX ingest_sessions_dataset ON ingest_sessions (dataset_id);

-- The expiry sweep lists every open session whose lease has lapsed, oldest
-- first. That predicate carries expires_at and state, neither of which the
-- index above or the two partial unique indexes serve; this one is partial
-- on the open states alone, so it stays small even though session rows are
-- never deleted.
CREATE INDEX ingest_sessions_lapsing ON ingest_sessions (expires_at)
    WHERE state IN ('PREPARING', 'UPLOADING', 'VERIFYING');

-- A file's progress is a ledger of parts; the plan fixes how many. A
-- hardlinked file has no parts and no state beyond linked or not.
ALTER TABLE ingest_files ADD COLUMN part_count integer NOT NULL;
ALTER TABLE ingest_files
    ADD CONSTRAINT ingest_files_part_count_matches_action
        CHECK ((action = 'hardlink' AND part_count = 0) OR (action = 'upload' AND part_count >= 1));
ALTER TABLE ingest_files
    ADD CONSTRAINT ingest_files_state_vocabulary
        CHECK (state IN ('PENDING', 'COMPLETE'));
"""


def upgrade() -> None:
    """Give the ingest ledger its state vocabulary, part count, parent citation and indexes."""
    execute_sql(DDL)


def downgrade() -> None:
    """Drop the ingest ledger's ``0009`` additions, restoring ``0008``'s shape exactly."""
    execute_sql("""
    ALTER TABLE ingest_files DROP CONSTRAINT IF EXISTS ingest_files_state_vocabulary;
    ALTER TABLE ingest_files DROP CONSTRAINT IF EXISTS ingest_files_part_count_matches_action;
    ALTER TABLE ingest_files DROP COLUMN IF EXISTS part_count;

    DROP INDEX IF EXISTS ingest_sessions_lapsing;
    DROP INDEX IF EXISTS ingest_sessions_dataset;
    DROP INDEX IF EXISTS ingest_sessions_parent_revision;
    ALTER TABLE ingest_sessions DROP CONSTRAINT IF EXISTS ingest_sessions_parent_revision_fk;
    ALTER TABLE ingest_sessions DROP COLUMN IF EXISTS parent_revision_id;
    """)
