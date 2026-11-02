"""Ports for writing and reading the audit log."""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    import uuid
    from collections.abc import Sequence

    from huron.core.lake.audit.models import AuditEntry

__all__ = ["AuditStore"]


class AuditStore(Protocol):
    """The append-only audit log."""

    async def write(self, entry: AuditEntry) -> AuditEntry:
        """Append ``entry`` and return it with its id."""
        ...

    async def for_object(
        self, object_id: uuid.UUID, before: int | None, limit: int
    ) -> Sequence[AuditEntry]:
        """Entries about one object, newest first, with ids below ``before``."""
        ...

    async def for_catalog(
        self, catalog_id: uuid.UUID, before: int | None, limit: int
    ) -> Sequence[AuditEntry]:
        """Entries within one catalog, newest first, with ids below ``before``."""
        ...
