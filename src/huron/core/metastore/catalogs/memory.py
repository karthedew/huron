"""In-memory catalogs."""

from __future__ import annotations

from typing import TYPE_CHECKING

from huron.core.lake.catalogs.errors import CatalogNotFound
from huron.core.lake.errors import NameTaken
from huron.core.lake.listing import ListOrder, Position

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
        after: Position,
        limit: int,
        ordering: ListOrder | None = None,
    ) -> Sequence[Catalog]:
        """Catalogs in the requested order."""
        rows = (
            c
            for c in self._state.catalogs.values()
            if (organization_id is None or c.organization_id == organization_id)
            and (visible is None or c.organization_id in visible[0] or c.id in visible[1])
        )
        return (ordering or ListOrder()).rows(rows, after, limit)

    async def update(self, catalog: Catalog) -> None:
        """Replace the stored row; raises :class:`CatalogNotFound` when there is none."""
        if catalog.id not in self._state.catalogs:
            raise CatalogNotFound(catalog.name)
        self._state.catalogs[catalog.id] = catalog

    async def delete(self, catalog_id: uuid.UUID) -> None:
        """Remove a catalog."""
        self._state.catalogs.pop(catalog_id, None)

    async def namespace_count(self, catalog_id: uuid.UUID) -> int:
        """How many namespaces the catalog has."""
        return sum(1 for n in self._state.namespaces.values() if n.catalog_id == catalog_id)
