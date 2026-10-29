"""The ``namespaces`` table."""

from __future__ import annotations

from sqlalchemy import (
    Boolean,
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

from huron.core.metastore.tables import metadata

__all__ = ["namespaces"]

namespaces = Table(
    "namespaces",
    metadata,
    Column("id", Uuid, primary_key=True),
    Column("catalog_id", Uuid, ForeignKey("huron.catalogs.id"), nullable=False),
    Column("parent_id", Uuid, ForeignKey("huron.namespaces.id"), nullable=True),
    Column("name", Text, nullable=False),
    Column("path", Text, nullable=False),
    Column("collections_allowed", Boolean, nullable=False),
    Column("version", Integer, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("created_by", Text, nullable=False),
    UniqueConstraint("catalog_id", "path"),
    Index(None, "catalog_id", "parent_id"),
    Index(None, "parent_id"),
)
