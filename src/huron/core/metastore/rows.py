"""Helpers shared by the PostgreSQL adapters."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import asyncpg
import asyncpg.pool

from huron.core.lake.errors import NameTaken

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, Sequence

__all__ = ["Db", "columns", "signed_inode", "unique", "unsigned_inode"]

type Db = asyncpg.Connection[asyncpg.Record] | asyncpg.pool.PoolConnectionProxy[asyncpg.Record]


async def unique[T](call: Callable[[], Awaitable[T]], name: str) -> T:
    """Run ``call``, turning a unique violation into :class:`NameTaken` for ``name``."""
    try:
        return await call()
    except asyncpg.UniqueViolationError as error:
        raise NameTaken(f"{name!r} is in use", {"name": name}) from error


def columns(rows: Sequence[tuple[Any, ...]]) -> list[list[Any]]:
    """The columns of ``rows``, one list per position, as ``unnest`` takes them."""
    return [list(column) for column in zip(*rows, strict=True)]


def signed_inode(inode: int | None) -> int | None:
    """The ``bigint`` that stores the unsigned 64-bit ``inode`` in two's complement."""
    if inode is None or inode < _SIGN_BIT:
        return inode
    return inode - _WORD


def unsigned_inode(stored: int | None) -> int | None:
    """The unsigned 64-bit inode that the ``bigint`` ``stored`` holds in two's complement."""
    if stored is None or stored >= 0:
        return stored
    return stored + _WORD


_SIGN_BIT = 2**63
_WORD = 2**64
