"""Persistence port for catalogs."""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    import uuid
    from collections.abc import Collection, Sequence

    from huron.core.lake.catalogs.models import Catalog
    from huron.core.lake.listing import ListOrder, Position

__all__ = ["CatalogStore"]


class CatalogStore(Protocol):
    """Reads and writes catalogs."""

    async def insert(self, catalog: Catalog) -> None:
        """Store a new catalog; raises ``NameTaken`` for a used name."""
        ...

    async def get(self, catalog_id: uuid.UUID) -> Catalog | None:
        """The catalog with ``catalog_id``."""
        ...

    async def get_by_name(self, name: str) -> Catalog | None:
        """The catalog named ``name``."""
        ...

    async def list(
        self,
        organization_id: uuid.UUID | None,
        visible: tuple[Collection[uuid.UUID], Collection[uuid.UUID]] | None,
        after: Position,
        limit: int,
        ordering: ListOrder | None = None,
    ) -> Sequence[Catalog]:
        """Catalogs in the requested order after ``after``, within one organization unless ``None``.

        ``visible`` is ``(organization_ids, catalog_ids)``: a catalog is listed when its
        organization or its own id is in them. ``None`` lists every catalog.
        """
        ...

    async def update(self, catalog: Catalog) -> None:
        """Replace the stored row."""
        ...

    async def delete(self, catalog_id: uuid.UUID) -> None:
        """Remove a catalog."""
        ...

    async def namespace_count(self, catalog_id: uuid.UUID) -> int:
        """How many namespaces the catalog has, at every depth."""
        ...
