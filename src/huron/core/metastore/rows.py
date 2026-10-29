"""Helpers shared by the PostgreSQL adapters."""

from __future__ import annotations

from typing import TYPE_CHECKING

import asyncpg
import asyncpg.pool

from huron.core.lake.errors import NameTaken

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

__all__ = ["Db", "unique"]

type Db = asyncpg.Connection[asyncpg.Record] | asyncpg.pool.PoolConnectionProxy[asyncpg.Record]


async def unique[T](call: Callable[[], Awaitable[T]], name: str) -> T:
    """Run ``call``, turning a unique violation into :class:`NameTaken` for ``name``."""
    try:
        return await call()
    except asyncpg.UniqueViolationError as error:
        raise NameTaken(f"{name!r} is taken", {"name": name}) from error
