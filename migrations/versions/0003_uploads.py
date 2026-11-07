"""Uploads through tusd: upload rows, receipts, the removal outbox, inodes and share groups.

Revision ID: 0003_uploads
Revises: 0002_organization_catalog_roles
Create Date: 2026-11-06 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0003_uploads"
down_revision: str | None = "0002_organization_catalog_roles"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create ``uploads`` and ``removals``; add ``files.inode`` and ``catalogs.share_group``."""
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
    op.add_column("files", sa.Column("inode", sa.BigInteger(), nullable=True), schema="huron")
    op.add_column("catalogs", sa.Column("share_group", sa.Text(), nullable=True), schema="huron")


def downgrade() -> None:
    """Drop ``catalogs.share_group``, ``files.inode``, ``removals`` and ``uploads``."""
    op.drop_column("catalogs", "share_group", schema="huron")
    op.drop_column("files", "inode", schema="huron")
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
