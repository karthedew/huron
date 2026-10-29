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
    """Appends audit entries in the transaction that makes their change.

    Entries become visible when that transaction commits and vanish if it rolls back.
    An operation appends after the write that locks the audited row, so one object's
    entry ids ascend in commit order.
    """

    async def append_audit(self, entries: Sequence[AuditEntry]) -> None:
        """Append entries, with ids ascending in call order.

        An empty sequence raises ValueError: an audited change always records an entry.

        Args:
            entries: Entries describing changes made in this transaction.
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
