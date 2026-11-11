"""In-memory collections."""

from __future__ import annotations

import copy
from dataclasses import replace
from typing import TYPE_CHECKING

from huron.core.lake.errors import NameTaken
from huron.core.lake.listing import ListOrder, Position

if TYPE_CHECKING:
    import uuid
    from collections.abc import Collection as Container
    from collections.abc import Sequence

    from huron.core.lake.collections.models import Collection, Search, State
    from huron.core.metastore.memory import MemoryState

__all__ = ["MemoryCollections", "matches"]


def matches(collection: Collection, query: Search) -> bool:
    """Whether ``collection`` satisfies a search; shared with tests of other adapters."""
    if collection.state not in query.states:
        return False
    labels = collection.metadata.get("labels")
    labels = labels if isinstance(labels, dict) else {}
    if any(labels.get(key) != value for key, value in query.labels):
        return False
    if not query.q:
        return True
    needle = query.q.casefold()
    haystack = (
        collection.identifier,
        str(collection.metadata.get("title", "")),
        str(collection.metadata.get("description", "")),
    )
    return any(needle in text.casefold() for text in haystack)


class MemoryCollections:
    """Collections in a :class:`MemoryState`, with sibling exclusion against namespaces."""

    def __init__(self, state: MemoryState) -> None:
        self._state = state

    async def insert(self, collection: Collection) -> None:
        """Store a collection."""
        taken = any(
            c.identifier == collection.identifier for c in self._state.collections.values()
        ) or any(
            n.parent_id == collection.namespace_id and n.name == collection.name
            for n in self._state.namespaces.values()
        )
        if taken:
            raise NameTaken(f"{collection.identifier!r} is in use", {"name": collection.name})
        self._state.collections[collection.id] = _copy(collection)

    async def get(self, collection_id: uuid.UUID) -> Collection | None:
        """The collection with ``collection_id``."""
        found = self._state.collections.get(collection_id)
        return None if found is None else _copy(found)

    async def get_by_identifier(self, identifier: str) -> Collection | None:
        """The collection with ``identifier``."""
        found = next(
            (c for c in self._state.collections.values() if c.identifier == identifier), None
        )
        return None if found is None else _copy(found)

    async def lock(self, collection_id: uuid.UUID) -> Collection | None:
        """Transactions are serialized, so locking is reading."""
        return await self.get(collection_id)

    async def update(self, collection: Collection) -> None:
        """Replace the stored row."""
        self._state.collections[collection.id] = _copy(collection)

    async def delete(self, collection_id: uuid.UUID) -> None:
        """Remove a collection with its uploads.

        Its removals and commit requests stay, without collection or commit, and its upload
        attempts stay without collection.
        """
        self._state.collections.pop(collection_id, None)
        self._state.uploads = {
            key: upload
            for key, upload in self._state.uploads.items()
            if upload.collection_id != collection_id
        }
        self._state.removals = {
            key: replace(removal, collection_id=None, commit_id=None)
            if removal.collection_id == collection_id
            else removal
            for key, removal in self._state.removals.items()
        }
        self._state.attempts = {
            key: replace(attempt, collection_id=None)
            if attempt.collection_id == collection_id
            else attempt
            for key, attempt in self._state.attempts.items()
        }
        self._state.commit_requests = {
            key: replace(outcome, collection_id=None, commit_id=None)
            if outcome.collection_id == collection_id
            else outcome
            for key, outcome in self._state.commit_requests.items()
        }

    async def list_in_namespace(
        self,
        namespace_id: uuid.UUID,
        states: Container[State],
        after: Position,
        limit: int,
        ordering: ListOrder | None = None,
    ) -> Sequence[Collection]:
        """Collections in a namespace in the requested order."""
        rows = (
            c
            for c in self._state.collections.values()
            if c.namespace_id == namespace_id and c.state in states
        )
        return [_copy(c) for c in (ordering or ListOrder()).rows(rows, after, limit)]

    async def list_in_catalog(
        self, catalog_id: uuid.UUID, states: Container[State]
    ) -> Sequence[Collection]:
        """Every collection of a catalog in ``states``."""
        rows = sorted(
            (
                c
                for c in self._state.collections.values()
                if c.catalog_id == catalog_id and c.state in states
            ),
            key=lambda c: c.identifier,
        )
        return [_copy(c) for c in rows]

    async def search(
        self, catalog_id: uuid.UUID, query: Search, after: str | None, limit: int
    ) -> Sequence[Collection]:
        """Collections matching ``query`` sorted by identifier."""
        rows = sorted(
            (
                c
                for c in self._state.collections.values()
                if c.catalog_id == catalog_id
                and matches(c, query)
                and (after is None or c.identifier > after)
            ),
            key=lambda c: c.identifier,
        )
        return [_copy(c) for c in rows[:limit]]


def _copy(collection: Collection) -> Collection:
    return replace(
        collection,
        metadata=copy.deepcopy(collection.metadata),
        schema_override=copy.deepcopy(collection.schema_override),
    )
