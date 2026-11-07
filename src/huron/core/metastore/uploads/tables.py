"""The ``uploads`` and ``removals`` tables."""

from __future__ import annotations

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Index,
    String,
    Table,
    Text,
    Uuid,
)
from sqlalchemy.dialects.postgresql import JSONB

from huron.core.metastore.tables import metadata

__all__ = ["removals", "uploads"]

uploads = Table(
    "uploads",
    metadata,
    Column("id", Uuid, primary_key=True),
    Column(
        "collection_id",
        Uuid,
        ForeignKey("huron.collections.id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column("rel_path", Text, nullable=False),
    Column("rel_path_key", Text, nullable=False),
    Column("size", BigInteger, nullable=False),
    Column("state", Text, nullable=False),
    Column("sha256", String(64), nullable=True),
    Column("failure", JSONB, nullable=True),
    Column("created_by", Text, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("placed_at", DateTime(timezone=True), nullable=True),
    Column("commit_id", Uuid, ForeignKey("huron.commits.id"), nullable=True),
    Column("inode", BigInteger, nullable=True),
    CheckConstraint(
        "state in ('pending', 'placed', 'failed', 'terminated', 'committed')", name="state"
    ),
    CheckConstraint("size >= 0", name="size"),
    CheckConstraint(
        "state not in ('placed', 'committed') or (sha256 is not null and placed_at is not null)",
        name="receipt",
    ),
    CheckConstraint("(state = 'committed') = (commit_id is not null)", name="commit"),
    CheckConstraint("state <> 'failed' or failure is not null", name="failure"),
    CheckConstraint("(state in ('placed', 'committed')) = (inode is not null)", name="inode"),
    Index(None, "collection_id", "rel_path_key"),
    Index(None, "commit_id"),
)

removals = Table(
    "removals",
    metadata,
    Column("id", Uuid, primary_key=True),
    Column(
        "collection_id",
        Uuid,
        ForeignKey("huron.collections.id", ondelete="SET NULL"),
        nullable=True,
    ),
    Column("path", Text, nullable=False),
    Column("rel_path", Text, nullable=False),
    Column("rel_path_key", Text, nullable=False),
    Column("sha256", String(64), nullable=False),
    Column("commit_id", Uuid, ForeignKey("huron.commits.id", ondelete="SET NULL"), nullable=True),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("claimed_at", DateTime(timezone=True), nullable=True),
    Column("inode", BigInteger, nullable=True),
    Index(None, "collection_id", "rel_path_key"),
    Index(None, "commit_id"),
)
