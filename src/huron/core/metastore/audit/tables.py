"""The append-only ``audit`` table."""

from __future__ import annotations

from sqlalchemy import BigInteger, Column, DateTime, Identity, Index, Table, Text, Uuid
from sqlalchemy.dialects.postgresql import JSONB

from huron.core.metastore.tables import metadata

__all__ = ["audit"]

audit = Table(
    "audit",
    metadata,
    Column("id", BigInteger, Identity(always=True), primary_key=True),
    Column("at", DateTime(timezone=True), nullable=False),
    Column("actor", Text, nullable=False),
    Column("action", Text, nullable=False),
    Column("object_type", Text, nullable=False),
    Column("object_id", Uuid, nullable=True),
    Column("catalog_id", Uuid, nullable=True),
    Column("organization_id", Uuid, nullable=True),
    Column("detail", JSONB, nullable=False),
    Index(None, "object_id", "id"),
    Index(None, "catalog_id", "id"),
)
