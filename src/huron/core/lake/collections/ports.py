"""Persistence port for collections."""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    import uuid
    from collections.abc import Collection as Container
    from collections.abc import Sequence

    from huron.core.lake.collections.models import Collection, Search, State

__all__ = ["CollectionStore"]


class CollectionStore(Protocol):
    """Reads and writes collections."""

    async def insert(self, collection: Collection) -> None:
        """Store a collection; raises ``NameTaken`` when a sibling uses the name."""
        ...

    async def get(self, collection_id: uuid.UUID) -> Collection | None:
        """The collection with ``collection_id``."""
        ...

    async def get_by_identifier(self, identifier: str) -> Collection | None:
        """The collection with the dotted ``identifier``."""
        ...

    async def lock(self, collection_id: uuid.UUID) -> Collection | None:
        """The collection, locked for update until the transaction ends."""
        ...

    async def update(self, collection: Collection) -> None:
        """Replace the stored row."""
        ...

    async def delete(self, collection_id: uuid.UUID) -> None:
        """Remove a collection."""
        ...

    async def list_in_namespace(
        self,
        namespace_id: uuid.UUID,
        states: Container[State],
        after: str | None,
        limit: int,
    ) -> Sequence[Collection]:
        """Collections directly in a namespace in ``states``, sorted by name."""
        ...

    async def list_in_catalog(
        self, catalog_id: uuid.UUID, states: Container[State]
    ) -> Sequence[Collection]:
        """Every collection of a catalog in ``states``, sorted by identifier."""
        ...

    async def search(
        self,
        catalog_id: uuid.UUID,
        query: Search,
        after: str | None,
        limit: int,
    ) -> Sequence[Collection]:
        """Collections matching ``query``, sorted by identifier."""
        ...
