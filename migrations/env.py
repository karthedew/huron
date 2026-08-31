from __future__ import annotations

import asyncio
import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool
from sqlalchemy.ext.asyncio import async_engine_from_config

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = None

# The containerized `migrate` service (docker-compose.yml, "app" profile) has
# no alembic.ini override mechanism of its own, so it passes the database URL
# the same way the API does - HURON_DATABASE_URL. Prefer it when set,
# rewriting the plain "postgresql://" scheme to the asyncpg driver this file
# requires; fall back to alembic.ini's own sqlalchemy.url (host port 5433)
# when the variable is unset, which is what `make migrate` on the host does.
if (env_url := os.environ.get("HURON_DATABASE_URL")) is not None:
    config.set_main_option(
        "sqlalchemy.url", env_url.replace("postgresql://", "postgresql+asyncpg://", 1)
    )


def run_migrations_offline() -> None:
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def _do_run_migrations(connection) -> None:  # type: ignore[no-untyped-def]
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    # One connection, configured and migrated in the same `run_sync` call:
    # `context.run_migrations()` executes against whatever connection was
    # last passed to `context.configure()`, not whatever connection happens
    # to be open around the call site. A previous version of this function
    # configured the context on one connection but ran migrations (and
    # opened its transaction) on a second, separate one from the pool -
    # every statement executed there against the *first*, never-committed
    # connection, so `alembic upgrade head` logged success and committed
    # nothing.
    async with connectable.connect() as connection:
        await connection.run_sync(_do_run_migrations)
    await connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_async_migrations())
