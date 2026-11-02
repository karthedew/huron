"""Persistence port for the schema registry."""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    import uuid
    from collections.abc import Sequence

    from huron.core.lake.schemas.models import SchemaEntry

__all__ = ["SchemaStore"]


class SchemaStore(Protocol):
    """Reads and writes registry entries."""

    async def insert(self, entry: SchemaEntry) -> None:
        """Store a new entry."""
        ...

    async def get(self, schema_id: uuid.UUID) -> SchemaEntry | None:
        """The entry with ``schema_id``."""
        ...

    async def latest(self, organization_id: uuid.UUID | None, name: str) -> SchemaEntry | None:
        """The highest version of ``name`` in the scope."""
        ...

    async def list(
        self, organization_id: uuid.UUID | None, after: tuple[str, int] | None, limit: int
    ) -> Sequence[SchemaEntry]:
        """Entries of one scope sorted by name, then version descending."""
        ...
