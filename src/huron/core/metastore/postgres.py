"""The PostgreSQL unit of work: an asyncpg pool and transactions over one connection."""

from __future__ import annotations

import json
import uuid
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, Any

import asyncpg

from huron.core.metastore.audit.postgres import PostgresAudit
from huron.core.metastore.catalogs.postgres import PostgresCatalogs
from huron.core.metastore.collections.postgres import PostgresCollections
from huron.core.metastore.files.postgres import PostgresCommits, PostgresFiles
from huron.core.metastore.grants.postgres import PostgresGrants
from huron.core.metastore.keys.postgres import PostgresKeys
from huron.core.metastore.namespaces.postgres import PostgresNamespaces
from huron.core.metastore.organizations.postgres import PostgresOrganizations
from huron.core.metastore.schemas.postgres import PostgresSchemas
from huron.pkg.errors import Unavailable

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

    from huron.core.metastore.rows import Db

__all__ = ["PostgresStore", "PostgresTransaction", "lock_key"]


def lock_key(namespace: str, value: uuid.UUID) -> int:
    """A signed 64-bit advisory-lock key for ``value`` within a lock namespace."""
    digest = uuid.uuid5(uuid.NAMESPACE_URL, f"huron:{namespace}:{value}")
    return int.from_bytes(digest.bytes[:8], "big", signed=True)


class PostgresTransaction:
    """Every area's PostgreSQL store sharing one connection inside one transaction."""

    def __init__(self, connection: Db) -> None:
        self.connection = connection
        self.organizations = PostgresOrganizations(connection)
        self.catalogs = PostgresCatalogs(connection)
        self.namespaces = PostgresNamespaces(connection)
        self.collections = PostgresCollections(connection)
        self.files = PostgresFiles(connection)
        self.commits = PostgresCommits(connection)
        self.schemas = PostgresSchemas(connection)
        self.audit = PostgresAudit(connection)
        self.grants = PostgresGrants(connection)
        self.keys = PostgresKeys(connection)

    async def lock_catalog(self, catalog_id: uuid.UUID) -> None:
        """Take the catalog's transaction-scoped advisory lock."""
        await self.connection.execute(
            "select pg_advisory_xact_lock($1)", lock_key("catalog", catalog_id)
        )


class PostgresStore:
    """A unit of work over an asyncpg pool."""

    def __init__(self, dsn: str, pool_size: int = 10) -> None:
        self._dsn = dsn
        self._pool_size = pool_size
        self._pool: asyncpg.Pool[asyncpg.Record] | None = None

    async def connect(self) -> None:
        """Open the pool; raises ``Unavailable`` when the database is unreachable."""
        try:
            self._pool = await asyncpg.create_pool(
                self._dsn, min_size=1, max_size=self._pool_size, init=_init_connection
            )
        except (OSError, asyncpg.PostgresError) as error:
            raise Unavailable("the database is unreachable") from error

    async def close(self) -> None:
        """Close the pool."""
        if self._pool is not None:
            await self._pool.close()
            self._pool = None

    async def ping(self) -> bool:
        """Whether a trivial query succeeds."""
        if self._pool is None:
            return False
        try:
            value = await self._pool.fetchval("select 1")
            return bool(value == 1)
        except (OSError, asyncpg.PostgresError, asyncpg.InterfaceError):
            return False

    @asynccontextmanager
    async def transaction(self) -> AsyncGenerator[PostgresTransaction]:
        """A transaction on one pooled connection; an exception rolls it back."""
        if self._pool is None:
            raise Unavailable("the database pool is not open")
        async with self._pool.acquire() as connection, connection.transaction():
            yield PostgresTransaction(connection)


async def _init_connection(connection: asyncpg.Connection[asyncpg.Record]) -> None:
    for name in ("jsonb", "json"):
        await connection.set_type_codec(
            name, encoder=_dumps, decoder=json.loads, schema="pg_catalog"
        )


def _dumps(value: Any) -> str:
    return json.dumps(value, separators=(",", ":"))
