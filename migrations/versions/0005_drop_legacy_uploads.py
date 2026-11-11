"""Drop the tables of the first upload path: ``uploads`` and ``removals``.

Revision ID: 0005_drop_legacy_uploads
Revises: 0004_publication
Create Date: 2026-11-11 00:00:00.000000

Upload attempts and commit requests replace both tables. The upgrade refuses to run while one of
them holds a row, so that no data is lost without notice.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0005_drop_legacy_uploads"
down_revision: str | None = "0004_publication"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: The tables that this revision drops, in the order of the drop.
LEGACY_TABLES = ("removals", "uploads")


def upgrade() -> None:
    """Drop ``removals`` and ``uploads``; refuse when one of them holds a row."""
    connection = op.get_bind()
    for table in LEGACY_TABLES:
        if connection.execute(sa.text(f"select exists (select 1 from huron.{table})")).scalar():
            raise RuntimeError(
                f"table huron.{table} holds rows. Huron does not drop a table with data."
                f" Remove the rows of huron.{table}, then run the migration again"
            )
    op.drop_index(op.f("ix_removals_commit_id"), table_name="removals", schema="huron")
    op.drop_index(
        op.f("ix_removals_collection_id_rel_path_key"), table_name="removals", schema="huron"
    )
    op.drop_table("removals", schema="huron")
    op.drop_index(op.f("ix_uploads_commit_id"), table_name="uploads", schema="huron")
    op.drop_index(
        op.f("ix_uploads_collection_id_rel_path_key"), table_name="uploads", schema="huron"
    )
    op.drop_table("uploads", schema="huron")


def downgrade() -> None:
    """Create the empty ``uploads`` and ``removals`` tables of revision ``0003_uploads`` again."""
    _create_uploads()
    _create_removals()


def _create_uploads() -> None:
    op.create_table(
        "uploads",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("collection_id", sa.Uuid(), nullable=False),
        sa.Column("rel_path", sa.Text(), nullable=False),
        sa.Column("rel_path_key", sa.Text(), nullable=False),
        sa.Column("size", sa.BigInteger(), nullable=False),
        sa.Column("state", sa.Text(), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=True),
        sa.Column("failure", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("created_by", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("placed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("commit_id", sa.Uuid(), nullable=True),
        sa.Column("inode", sa.BigInteger(), nullable=True),
        sa.CheckConstraint(
            "state in ('pending', 'placed', 'failed', 'terminated', 'committed')",
            name=op.f("ck_uploads_state"),
        ),
        sa.CheckConstraint("size >= 0", name=op.f("ck_uploads_size")),
        sa.CheckConstraint(
            "state not in ('placed', 'committed') or (sha256 is not null and placed_at is not null)",
            name=op.f("ck_uploads_receipt"),
        ),
        sa.CheckConstraint(
            "(state = 'committed') = (commit_id is not null)", name=op.f("ck_uploads_commit")
        ),
        sa.CheckConstraint(
            "state <> 'failed' or failure is not null", name=op.f("ck_uploads_failure")
        ),
        sa.CheckConstraint(
            "(state in ('placed', 'committed')) = (inode is not null)",
            name=op.f("ck_uploads_inode"),
        ),
        sa.ForeignKeyConstraint(
            ["collection_id"],
            ["huron.collections.id"],
            name=op.f("fk_uploads_collection_id"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["commit_id"], ["huron.commits.id"], name=op.f("fk_uploads_commit_id")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_uploads")),
        schema="huron",
    )
    op.create_index(
        op.f("ix_uploads_collection_id_rel_path_key"),
        "uploads",
        ["collection_id", "rel_path_key"],
        unique=False,
        schema="huron",
    )
    op.create_index(
        op.f("ix_uploads_commit_id"), "uploads", ["commit_id"], unique=False, schema="huron"
    )


def _create_removals() -> None:
    op.create_table(
        "removals",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("collection_id", sa.Uuid(), nullable=True),
        sa.Column("path", sa.Text(), nullable=False),
        sa.Column("rel_path", sa.Text(), nullable=False),
        sa.Column("rel_path_key", sa.Text(), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("commit_id", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("claimed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("inode", sa.BigInteger(), nullable=True),
        sa.ForeignKeyConstraint(
            ["collection_id"],
            ["huron.collections.id"],
            name=op.f("fk_removals_collection_id"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["commit_id"],
            ["huron.commits.id"],
            name=op.f("fk_removals_commit_id"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_removals")),
        schema="huron",
    )
    op.create_index(
        op.f("ix_removals_collection_id_rel_path_key"),
        "removals",
        ["collection_id", "rel_path_key"],
        unique=False,
        schema="huron",
    )
    op.create_index(
        op.f("ix_removals_commit_id"), "removals", ["commit_id"], unique=False, schema="huron"
    )
