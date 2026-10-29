"""The ``signing_keys`` table."""

from __future__ import annotations

from sqlalchemy import Column, DateTime, Table, Text
from sqlalchemy.dialects.postgresql import JSONB

from huron.core.metastore.tables import metadata

__all__ = ["signing_keys"]

signing_keys = Table(
    "signing_keys",
    metadata,
    Column("kid", Text, primary_key=True),
    Column("private_pem", Text, nullable=False),
    Column("public_jwk", JSONB, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("retired_at", DateTime(timezone=True), nullable=True),
)
