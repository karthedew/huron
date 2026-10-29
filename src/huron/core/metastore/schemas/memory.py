"""In-memory schema registry."""

from __future__ import annotations

from typing import TYPE_CHECKING

from huron.core.lake.errors import NameTaken

if TYPE_CHECKING:
    import uuid
    from collections.abc import Sequence

    from huron.core.lake.schemas.models import SchemaEntry
    from huron.core.metastore.memory import MemoryState

__all__ = ["MemorySchemas"]


class MemorySchemas:
    """Registry entries in a :class:`MemoryState`."""

    def __init__(self, state: MemoryState) -> None:
        self._state = state

    async def insert(self, entry: SchemaEntry) -> None:
        """Store a new entry."""
        if any(
            e.organization_id == entry.organization_id
            and e.name == entry.name
            and e.version == entry.version
            for e in self._state.schemas.values()
        ):
            raise NameTaken(f"{entry.name} v{entry.version} exists", {"name": entry.name})
        self._state.schemas[entry.id] = entry

    async def get(self, schema_id: uuid.UUID) -> SchemaEntry | None:
        """The entry with ``schema_id``."""
        return self._state.schemas.get(schema_id)

    async def latest(self, organization_id: uuid.UUID | None, name: str) -> SchemaEntry | None:
        """The highest version of ``name``."""
        versions = sorted(
            (
                e
                for e in self._state.schemas.values()
                if e.organization_id == organization_id and e.name == name
            ),
            key=lambda e: e.version,
        )
        return versions[-1] if versions else None

    async def list(
        self, organization_id: uuid.UUID | None, after: tuple[str, int] | None, limit: int
    ) -> Sequence[SchemaEntry]:
        """Entries sorted by name, then version descending."""
        rows = sorted(
            (e for e in self._state.schemas.values() if e.organization_id == organization_id),
            key=lambda e: (e.name, -e.version),
        )
        if after is not None:
            rows = [e for e in rows if (e.name, -e.version) > (after[0], -after[1])]
        return rows[:limit]
