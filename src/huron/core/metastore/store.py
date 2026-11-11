"""The in-memory unit of work: serializable transactions over plain dictionaries."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING

from huron.core.metastore.audit.memory import MemoryAudit
from huron.core.metastore.catalogs.memory import MemoryCatalogs
from huron.core.metastore.collections.memory import MemoryCollections
from huron.core.metastore.files.memory import MemoryCommits, MemoryFiles
from huron.core.metastore.grants.memory import MemoryGrants
from huron.core.metastore.keys.memory import MemoryKeys
from huron.core.metastore.memory import MemoryState
from huron.core.metastore.namespaces.memory import MemoryNamespaces
from huron.core.metastore.organizations.memory import MemoryOrganizations
from huron.core.metastore.publications.memory import MemoryCommitRequests
from huron.core.metastore.schemas.memory import MemorySchemas
from huron.core.metastore.uploads.memory import MemoryAttempts, MemoryObjects

if TYPE_CHECKING:
    import uuid
    from collections.abc import AsyncGenerator

__all__ = ["MemoryStore", "MemoryTransaction", "MemoryWriterLock"]


class MemoryTransaction:
    """Every area's in-memory store over one working copy of the state."""

    def __init__(self, state: MemoryState) -> None:
        self.state = state
        self.organizations = MemoryOrganizations(state)
        self.catalogs = MemoryCatalogs(state)
        self.namespaces = MemoryNamespaces(state)
        self.collections = MemoryCollections(state)
        self.files = MemoryFiles(state)
        self.commits = MemoryCommits(state)
        self.attempts = MemoryAttempts(state)
        self.objects = MemoryObjects(state)
        self.commit_requests = MemoryCommitRequests(state)
        self.schemas = MemorySchemas(state)
        self.audit = MemoryAudit(state)
        self.grants = MemoryGrants(state)
        self.keys = MemoryKeys(state)

    async def lock_catalog(self, catalog_id: uuid.UUID) -> None:
        """Transactions are already serialized; nothing to do."""

    async def lock_bootstrap(self) -> None:
        """Transactions are already serialized; nothing to do."""


class MemoryStore:
    """A unit of work whose transactions run one at a time and commit by swapping state.

    ``writer`` is the :class:`MemoryWriterLock` that holds the store's writer lock, ``None``
    when no lock holds it. A test that sets it to ``None`` drops the lock of its holder, as a
    lost connection does on PostgreSQL.
    """

    def __init__(self, state: MemoryState | None = None) -> None:
        self.state = state or MemoryState()
        self.writer: MemoryWriterLock | None = None
        self._lock = asyncio.Lock()

    def writer_lock(self) -> MemoryWriterLock:
        """A writer lock of this store: two runtimes on one store share it."""
        return MemoryWriterLock(self)

    @asynccontextmanager
    async def transaction(self) -> AsyncGenerator[MemoryTransaction]:
        """Run a transaction on a copy; commit by replacing the state when the block succeeds."""
        async with self._lock:
            working = self.state.copy()
            yield MemoryTransaction(working)
            self.state = working

    async def close(self) -> None:
        """Nothing to release."""


class MemoryWriterLock:
    """The writer lock of a :class:`MemoryStore`: one holder at a time."""

    def __init__(self, store: MemoryStore) -> None:
        self._store = store

    async def acquire(self) -> bool:
        """Take the lock; ``False`` when another lock of the store holds it."""
        if self._store.writer is not None:
            return False
        self._store.writer = self
        return True

    async def held(self) -> bool:
        """Whether this lock still holds the store's writer lock."""
        return self._store.writer is self

    async def release(self) -> None:
        """Give the lock back when this lock holds it."""
        if self._store.writer is self:
            self._store.writer = None
