"""The shared SQLAlchemy metadata for schema ``huron``.

Table definitions live beside each area's adapter; calling :func:`load_all`
registers every one of them, which is what Alembic and the schema-map check need.
"""

from __future__ import annotations

import importlib

from sqlalchemy import MetaData

__all__ = ["SCHEMA", "load_all", "metadata"]

SCHEMA = "huron"

metadata = MetaData(
    schema=SCHEMA,
    naming_convention={
        "ix": "ix_%(table_name)s_%(column_0_N_name)s",
        "uq": "uq_%(table_name)s_%(column_0_N_name)s",
        "ck": "ck_%(table_name)s_%(constraint_name)s",
        "fk": "fk_%(table_name)s_%(column_0_name)s",
        "pk": "pk_%(table_name)s",
    },
)


def load_all() -> MetaData:
    """Import every area's tables and return the populated metadata."""
    for area in _AREAS:
        importlib.import_module(f"huron.core.metastore.{area}.tables")
    return metadata


_AREAS = (
    "audit",
    "catalogs",
    "collections",
    "files",
    "grants",
    "keys",
    "namespaces",
    "organizations",
    "schemas",
    "uploads",
)
