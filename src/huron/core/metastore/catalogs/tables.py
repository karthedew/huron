"""The ``catalogs`` table."""

from __future__ import annotations

from sqlalchemy import Column, DateTime, ForeignKey, Integer, Table, Text, Uuid

from huron.core.metastore.tables import metadata

__all__ = ["catalogs"]

catalogs = Table(
    "catalogs",
    metadata,
    Column("id", Uuid, primary_key=True),
    Column(
        "organization_id", Uuid, ForeignKey("huron.organizations.id"), nullable=False, index=True
    ),
    Column("name", Text, nullable=False, unique=True),
    Column("display_name", Text, nullable=False),
    Column("description", Text, nullable=False),
    Column("schema_id", Uuid, ForeignKey("huron.schemas.id"), nullable=False),
    Column("version", Integer, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("created_by", Text, nullable=False),
)
