"""The ``schemas`` table: the metadata schema registry."""

from __future__ import annotations

from sqlalchemy import Column, DateTime, ForeignKey, Integer, Table, Text, UniqueConstraint, Uuid
from sqlalchemy.dialects.postgresql import JSONB

from huron.core.metastore.tables import metadata

__all__ = ["schemas"]

schemas = Table(
    "schemas",
    metadata,
    Column("id", Uuid, primary_key=True),
    Column("organization_id", Uuid, ForeignKey("huron.organizations.id"), nullable=True),
    Column("name", Text, nullable=False),
    Column("version", Integer, nullable=False),
    Column("extends_id", Uuid, ForeignKey("huron.schemas.id"), nullable=True),
    Column("document", JSONB, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("created_by", Text, nullable=False),
    UniqueConstraint("organization_id", "name", "version", postgresql_nulls_not_distinct=True),
)
