"""In-memory audit log."""

from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import uuid
    from collections.abc import Sequence

    from huron.core.lake.audit.models import AuditEntry
    from huron.core.metastore.memory import MemoryState

__all__ = ["MemoryAudit"]


class MemoryAudit:
    """The audit log in a :class:`MemoryState`."""

    def __init__(self, state: MemoryState) -> None:
        self._state = state

    async def write(self, entry: AuditEntry) -> AuditEntry:
        """Append an entry with the next id."""
        stored = replace(entry, id=len(self._state.audit) + 1)
        self._state.audit.append(stored)
        return stored

    async def for_object(
        self, object_id: uuid.UUID, before: int | None, limit: int
    ) -> Sequence[AuditEntry]:
        """Entries about one object, newest first."""
        return self._newest(
            [e for e in self._state.audit if e.object_id == object_id], before, limit
        )

    async def for_catalog(
        self, catalog_id: uuid.UUID, before: int | None, limit: int
    ) -> Sequence[AuditEntry]:
        """Entries within one catalog, newest first."""
        return self._newest(
            [e for e in self._state.audit if e.catalog_id == catalog_id], before, limit
        )

    @staticmethod
    def _newest(entries: list[AuditEntry], before: int | None, limit: int) -> list[AuditEntry]:
        rows = [e for e in reversed(entries) if before is None or (e.id or 0) < before]
        return rows[:limit]
