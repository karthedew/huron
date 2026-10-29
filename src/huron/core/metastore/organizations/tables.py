"""The ``organizations`` table."""

from __future__ import annotations

from sqlalchemy import Column, DateTime, Integer, Table, Text, Uuid

from huron.core.metastore.tables import metadata

__all__ = ["organizations"]

organizations = Table(
    "organizations",
    metadata,
    Column("id", Uuid, primary_key=True),
    Column("name", Text, nullable=False, unique=True),
    Column("display_name", Text, nullable=False),
    Column("description", Text, nullable=False),
    Column("version", Integer, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("created_by", Text, nullable=False),
)
