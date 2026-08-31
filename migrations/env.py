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


async def run_async_migrations() -> None:
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    async with connectable.connect() as connection:
        await connection.run_sync(
            lambda sync_connection: context.configure(
                connection=sync_connection, target_metadata=target_metadata
            )
        )
        async with connectable.begin() as connection:
            await connection.run_sync(lambda _connection: context.run_migrations())
    await connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_async_migrations())
