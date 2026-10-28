"""Composite persistence contracts for the Raw lake."""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

from huron.core.foundation.retry import RetryTransaction
from huron.core.security.broker import RoleMappingReader, SigningKeyReader

if TYPE_CHECKING:
    from collections.abc import Sequence
    from contextlib import AbstractAsyncContextManager

    from huron.core.lake.audit import AuditEntry


class AuditWriter(Protocol):
    """Append entries in the transaction that records their change."""

    async def append_audit(self, entries: Sequence[AuditEntry]) -> None:
        """Stage a non-empty batch in call order.

        Args:
            entries: Facts about changes made by the same transaction.
        """
        ...


class LakeTransaction(AuditWriter, RetryTransaction, Protocol):
    """One open database transaction: every lake write, plus reads that see its own writes."""


class LakeStore(RoleMappingReader, SigningKeyReader, Protocol):
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
