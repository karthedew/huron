"""The ``collections`` table."""

from __future__ import annotations

from sqlalchemy import (
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Table,
    Text,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.dialects.postgresql import JSONB

from huron.core.metastore.tables import metadata

__all__ = ["collections"]

collections = Table(
    "collections",
    metadata,
    Column("id", Uuid, primary_key=True),
    Column("catalog_id", Uuid, ForeignKey("huron.catalogs.id"), nullable=False),
    Column("namespace_id", Uuid, ForeignKey("huron.namespaces.id"), nullable=False),
    Column("name", Text, nullable=False),
    Column("identifier", Text, nullable=False, unique=True),
    Column("state", Text, nullable=False),
    Column("version", Integer, nullable=False),
    Column("metadata", JSONB, nullable=False),
    Column("schema_override", JSONB, nullable=True),
    Column("file_count", Integer, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("created_by", Text, nullable=False),
    Column("updated_at", DateTime(timezone=True), nullable=False),
    Column("activated_at", DateTime(timezone=True), nullable=True),
    UniqueConstraint("namespace_id", "name"),
    CheckConstraint("state in ('draft', 'active', 'incomplete')", name="state"),
    CheckConstraint("file_count >= 0", name="file_count"),
    Index(None, "catalog_id", "state"),
    Index(
        "ix_collections_metadata",
        "metadata",
        postgresql_using="gin",
        postgresql_ops={"metadata": "jsonb_path_ops"},
    ),
)
