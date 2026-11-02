"""The shared SQLAlchemy metadata for schema ``huron``.

Table definitions live beside each area's adapter; importing this module's ``all_tables``
registers every one of them, which is what Alembic and the schema-map check need.
"""

from __future__ import annotations

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
    from huron.core.metastore.audit import tables as _audit  # noqa: F401
    from huron.core.metastore.catalogs import tables as _catalogs  # noqa: F401
    from huron.core.metastore.collections import tables as _collections  # noqa: F401
    from huron.core.metastore.files import tables as _files  # noqa: F401
    from huron.core.metastore.grants import tables as _grants  # noqa: F401
    from huron.core.metastore.keys import tables as _keys  # noqa: F401
    from huron.core.metastore.namespaces import tables as _namespaces  # noqa: F401
    from huron.core.metastore.organizations import tables as _organizations  # noqa: F401
    from huron.core.metastore.schemas import tables as _schemas  # noqa: F401

    return metadata
