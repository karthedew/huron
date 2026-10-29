"""In-memory catalogs."""

from __future__ import annotations

from typing import TYPE_CHECKING

from huron.core.lake.errors import NameTaken

if TYPE_CHECKING:
    import uuid
    from collections.abc import Collection, Sequence

    from huron.core.lake.catalogs.models import Catalog
    from huron.core.metastore.memory import MemoryState

__all__ = ["MemoryCatalogs"]


class MemoryCatalogs:
    """Catalogs in a :class:`MemoryState`."""

    def __init__(self, state: MemoryState) -> None:
        self._state = state

    async def insert(self, catalog: Catalog) -> None:
        """Store a new catalog."""
        if any(c.name == catalog.name for c in self._state.catalogs.values()):
            raise NameTaken(f"catalog {catalog.name!r} exists", {"name": catalog.name})
        self._state.catalogs[catalog.id] = catalog

    async def get(self, catalog_id: uuid.UUID) -> Catalog | None:
        """The catalog with ``catalog_id``."""
        return self._state.catalogs.get(catalog_id)

    async def get_by_name(self, name: str) -> Catalog | None:
        """The catalog named ``name``."""
        return next((c for c in self._state.catalogs.values() if c.name == name), None)

    async def list(
        self,
        organization_id: uuid.UUID | None,
        visible: tuple[Collection[uuid.UUID], Collection[uuid.UUID]] | None,
        after: str | None,
        limit: int,
    ) -> Sequence[Catalog]:
        """Catalogs sorted by name."""
        rows = sorted(self._state.catalogs.values(), key=lambda c: c.name)
        rows = [
            c
            for c in rows
            if (organization_id is None or c.organization_id == organization_id)
            and (visible is None or c.organization_id in visible[0] or c.id in visible[1])
            and (after is None or c.name > after)
        ]
        return rows[:limit]

    async def update(self, catalog: Catalog) -> None:
        """Replace the stored row."""
        self._state.catalogs[catalog.id] = catalog

    async def delete(self, catalog_id: uuid.UUID) -> None:
        """Remove a catalog."""
        self._state.catalogs.pop(catalog_id, None)

    async def namespace_count(self, catalog_id: uuid.UUID) -> int:
        """How many namespaces the catalog has."""
        return sum(1 for n in self._state.namespaces.values() if n.catalog_id == catalog_id)
