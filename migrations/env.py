"""The Alembic environment that runs the metastore's revision scripts.

Alembic executes this module for every command that connects to a database
or renders SQL for one - ``upgrade``, ``downgrade``, ``stamp``, ``current``.
It settles two things before any revision under ``versions/`` runs: which
database to reach and how.

The database URL is ``HURON_DATABASE_URL`` whenever that variable is set -
the same variable the API reads, so the containerized ``migrate`` service,
which cannot override ``alembic.ini``, passes it the same way - with a plain
``postgresql://`` scheme rewritten to ``postgresql+asyncpg://``. When the
variable is unset, ``alembic.ini``'s own ``sqlalchemy.url`` (Postgres on host
port 5433) applies.

Online, the revisions run over an async engine on the ``asyncpg`` driver, the
application's own runtime driver. That driver prepares every statement, and
PostgreSQL refuses to prepare more than one command at a time, which is why
each revision hands its multi-statement DDL to ``migrations._ddl.execute_sql``
instead of one ``op.execute``. Offline (``--sql``), the same revisions are
rendered as SQL text. There is no ``target_metadata``: every revision is
hand-written DDL, and autogenerate is never used.
"""

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
# when the variable is unset - a bare `alembic` invocation, since `make
# migrate` loads dev.env and so takes the environment-variable branch too.
if (env_url := os.environ.get("HURON_DATABASE_URL")) is not None:
    config.set_main_option(
        "sqlalchemy.url", env_url.replace("postgresql://", "postgresql+asyncpg://", 1)
    )


def run_migrations_offline() -> None:
    """Render the revisions as SQL text instead of executing them.

    Offline mode configures the Alembic context with the resolved URL alone,
    never opening a connection; bind parameters are inlined as literals so
    the output is a script an operator can review or apply by hand.
    """
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
    """Run the revisions online, over a single asyncpg connection.

    Builds an engine from the ``sqlalchemy.*`` options without pooling, so
    nothing outlives the run, then opens one connection and both configures
    the Alembic context and runs the migrations on it inside the same
    ``run_sync`` call. The pairing is the point: the context executes
    against whatever connection was last passed to ``configure()``, not
    whatever connection is open around the call site, so configuring on one
    pooled connection and migrating on another would execute every
    statement on a connection that is never committed - ``alembic upgrade
    head`` would log success and change nothing. The engine is disposed
    once the connection closes.
    """
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
