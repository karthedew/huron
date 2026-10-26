"""Composite persistence contracts for the Raw lake."""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from contextlib import AbstractAsyncContextManager


class LakeTransaction(Protocol):
    """One open database transaction: every lake write, plus reads that see its own writes."""


class LakeStore(Protocol):
    """The lake's persistence root, with atomic transactions and a readiness probe."""

    def transaction(self) -> AbstractAsyncContextManager[LakeTransaction]:
        """Open a transaction that commits on success and rolls back on failure.

        Returns:
            A context manager yielding one open transaction.
        """
        ...

    async def ping(self) -> None:
        """Probe whether persistence is available."""
        ...
