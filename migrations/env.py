"""Alembic environment bound to Huron's SQLAlchemy Core tables.

The database URL comes from ``HURON_DATABASE_URL`` (``postgresql://…``), or from the
``sqlalchemy.url`` set on the Alembic config by a caller such as the schema-map check.
"""

from __future__ import annotations

import asyncio
import os

from alembic import context
from sqlalchemy import pool, text
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

from huron.core.metastore.tables import SCHEMA, load_all

config = context.config
target_metadata = load_all()


def database_url() -> str:
    """The async SQLAlchemy URL for the migration run."""
    url = config.get_main_option("sqlalchemy.url") or os.environ.get("HURON_DATABASE_URL", "")
    if not url:
        raise RuntimeError("set HURON_DATABASE_URL to run migrations")
    return url.replace("postgresql://", "postgresql+asyncpg://", 1)


def include_name(name: str | None, type_: str, parent_names: object) -> bool:
    """Only compare objects in Huron's schema."""
    if type_ == "schema":
        return name == SCHEMA
    return True


def run_migrations(connection: Connection) -> None:
    """Run migrations on one connection."""
    connection.execute(text(f"create schema if not exists {SCHEMA}"))
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        version_table_schema=SCHEMA,
        include_schemas=True,
        include_name=include_name,
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_async() -> None:
    """Run migrations through an asyncpg engine."""
    section = config.get_section(config.config_ini_section, {})
    section["sqlalchemy.url"] = database_url()
    engine = async_engine_from_config(section, poolclass=pool.NullPool)
    async with engine.begin() as connection:
        await connection.run_sync(run_migrations)
    await engine.dispose()


if context.is_offline_mode():
    context.configure(url=database_url(), target_metadata=target_metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()
else:
    asyncio.run(run_async())
