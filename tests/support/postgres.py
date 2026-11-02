"""PostgreSQL for the contract and integration tiers.

``HURON_TEST_DATABASE_URL`` names a server whose user may create databases (for example
``postgresql://postgres@127.0.0.1:5432/postgres``); without it a ``postgres:16`` testcontainer is
started. Each test session gets a fresh database migrated to head.
"""

import asyncio
import os
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from urllib.parse import urlsplit, urlunsplit

import asyncpg
from alembic import command
from alembic.config import Config

from huron.core.metastore.tables import SCHEMA, load_all

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


@contextmanager
def server_url() -> Iterator[str]:
    """A URL of a PostgreSQL server whose user may create databases."""
    configured = os.environ.get("HURON_TEST_DATABASE_URL")
    if configured:
        yield configured
        return
    from testcontainers.postgres import PostgresContainer

    with PostgresContainer("postgres:16", driver=None) as container:
        yield container.get_connection_url()


def with_database(url: str, database: str) -> str:
    """``url`` pointing at another database on the same server."""
    parts = urlsplit(url)
    return urlunsplit((parts.scheme, parts.netloc, f"/{database}", parts.query, parts.fragment))


def alembic_config(url: str) -> Config:
    """An Alembic configuration for ``url``."""
    config = Config(os.path.join(ROOT, "alembic.ini"))
    config.set_main_option("script_location", os.path.join(ROOT, "migrations"))
    config.set_main_option("sqlalchemy.url", url)
    return config


@contextmanager
def migrated_database(server: str) -> Iterator[str]:
    """Create a uniquely named database, migrate it to head, and drop it afterwards."""
    name = f"huron_test_{uuid.uuid4().hex[:12]}"
    asyncio.run(_admin(server, f'create database "{name}"'))
    url = with_database(server, name)
    try:
        command.upgrade(alembic_config(url), "head")
        yield url
    finally:
        asyncio.run(_admin(server, f'drop database if exists "{name}" with (force)'))


async def truncate(url: str) -> None:
    """Empty every Huron table."""
    tables = ", ".join(f"{SCHEMA}.{table.name}" for table in load_all().sorted_tables)
    connection = await asyncpg.connect(url)
    try:
        await connection.execute(f"truncate {tables} restart identity cascade")
    finally:
        await connection.close()


async def _admin(url: str, statement: str) -> None:
    connection = await asyncpg.connect(url)
    try:
        await connection.execute(statement)
    finally:
        await connection.close()
