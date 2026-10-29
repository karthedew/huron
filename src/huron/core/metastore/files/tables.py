"""The ``commits`` and ``files`` tables."""

from __future__ import annotations

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    PrimaryKeyConstraint,
    String,
    Table,
    Text,
    Uuid,
)

from huron.core.metastore.tables import metadata

__all__ = ["commits", "files"]

commits = Table(
    "commits",
    metadata,
    Column("id", Uuid, primary_key=True),
    Column(
        "collection_id",
        Uuid,
        ForeignKey("huron.collections.id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column("base_version", Integer, nullable=False),
    Column("new_version", Integer, nullable=False),
    Column("adds", Integer, nullable=False),
    Column("removes", Integer, nullable=False),
    Column("host", Text, nullable=False),
    Column("message", Text, nullable=True),
    Column("actor", Text, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Index(None, "collection_id", "id"),
)

files = Table(
    "files",
    metadata,
    Column("collection_id", Uuid, ForeignKey("huron.collections.id"), nullable=False),
    Column("rel_path", Text, nullable=False),
    Column("rel_path_key", Text, nullable=False),
    Column("size", BigInteger, nullable=False),
    Column("sha256", String(64), nullable=False),
    Column("recorded_at", DateTime(timezone=True), nullable=False),
    Column("recorded_by", Text, nullable=False),
    Column("commit_id", Uuid, ForeignKey("huron.commits.id"), nullable=False),
    PrimaryKeyConstraint("collection_id", "rel_path_key"),
    CheckConstraint("size >= 0", name="size"),
    Index(None, "commit_id"),
)
