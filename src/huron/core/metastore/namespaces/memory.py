"""In-memory namespaces."""

from __future__ import annotations

from typing import TYPE_CHECKING

from huron.core.lake.errors import NameTaken

if TYPE_CHECKING:
    import uuid
    from collections.abc import Sequence

    from huron.core.lake.namespaces.models import Namespace
    from huron.core.metastore.memory import MemoryState

__all__ = ["MemoryNamespaces"]


class MemoryNamespaces:
    """Namespaces in a :class:`MemoryState`, with sibling exclusion against collections."""

    def __init__(self, state: MemoryState) -> None:
        self._state = state

    async def insert(self, namespace: Namespace) -> None:
        """Store a namespace."""
        taken = any(
            n.catalog_id == namespace.catalog_id and n.path == namespace.path
            for n in self._state.namespaces.values()
        ) or any(
            c.namespace_id == namespace.parent_id and c.name == namespace.name
            for c in self._state.collections.values()
        )
        if taken:
            raise NameTaken(f"{namespace.path!r} is taken", {"name": namespace.name})
        self._state.namespaces[namespace.id] = namespace

    async def get(self, namespace_id: uuid.UUID) -> Namespace | None:
        """The namespace with ``namespace_id``."""
        return self._state.namespaces.get(namespace_id)

    async def get_by_path(self, catalog_id: uuid.UUID, path: str) -> Namespace | None:
        """The namespace at ``path``."""
        return next(
            (
                n
                for n in self._state.namespaces.values()
                if n.catalog_id == catalog_id and n.path == path
            ),
            None,
        )

    async def children(
        self, catalog_id: uuid.UUID, parent_id: uuid.UUID | None, after: str | None, limit: int
    ) -> Sequence[Namespace]:
        """Direct children sorted by name."""
        rows = sorted(
            (
                n
                for n in self._state.namespaces.values()
                if n.catalog_id == catalog_id
                and n.parent_id == parent_id
                and (after is None or n.name > after)
            ),
            key=lambda n: n.name,
        )
        return rows[:limit]

    async def child_counts(self, namespace_id: uuid.UUID) -> tuple[int, int]:
        """``(child namespaces, collections)``."""
        namespaces = sum(1 for n in self._state.namespaces.values() if n.parent_id == namespace_id)
        collections = sum(
            1 for c in self._state.collections.values() if c.namespace_id == namespace_id
        )
        return namespaces, collections

    async def draft_count(self, namespace_id: uuid.UUID) -> int:
        """How many drafts are directly inside the namespace."""
        return sum(
            1
            for c in self._state.collections.values()
            if c.namespace_id == namespace_id and not c.settled
        )

    async def update(self, namespace: Namespace) -> None:
        """Replace the stored row."""
        self._state.namespaces[namespace.id] = namespace

    async def delete(self, namespace_id: uuid.UUID) -> None:
        """Remove a namespace."""
        self._state.namespaces.pop(namespace_id, None)
