"""Persistence port for namespaces."""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    import uuid
    from collections.abc import Sequence

    from huron.core.lake.namespaces.models import Namespace

__all__ = ["NamespaceStore"]


class NamespaceStore(Protocol):
    """Reads and writes namespaces."""

    async def insert(self, namespace: Namespace) -> None:
        """Store a namespace; raises ``NameTaken`` when a sibling uses the name."""
        ...

    async def get(self, namespace_id: uuid.UUID) -> Namespace | None:
        """The namespace with ``namespace_id``."""
        ...

    async def get_by_path(self, catalog_id: uuid.UUID, path: str) -> Namespace | None:
        """The namespace at ``path`` in the catalog."""
        ...

    async def children(
        self, catalog_id: uuid.UUID, parent_id: uuid.UUID | None, after: str | None, limit: int
    ) -> Sequence[Namespace]:
        """Direct children of ``parent_id`` (``None``: the catalog root), sorted by name."""
        ...

    async def child_counts(self, namespace_id: uuid.UUID) -> tuple[int, int]:
        """``(child namespaces, collections)`` directly inside the namespace, drafts included."""
        ...

    async def draft_count(self, namespace_id: uuid.UUID) -> int:
        """How many draft collections are directly inside the namespace."""
        ...

    async def update(self, namespace: Namespace) -> None:
        """Replace the stored row."""
        ...

    async def delete(self, namespace_id: uuid.UUID) -> None:
        """Remove a namespace."""
        ...
