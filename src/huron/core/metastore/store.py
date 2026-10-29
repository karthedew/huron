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
from huron.core.metastore.schemas.memory import MemorySchemas

if TYPE_CHECKING:
    import uuid
    from collections.abc import AsyncGenerator

__all__ = ["MemoryStore", "MemoryTransaction"]


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
        self.schemas = MemorySchemas(state)
        self.audit = MemoryAudit(state)
        self.grants = MemoryGrants(state)
        self.keys = MemoryKeys(state)

    async def lock_catalog(self, catalog_id: uuid.UUID) -> None:
        """Transactions are already serialized; nothing to do."""


class MemoryStore:
    """A unit of work whose transactions run one at a time and commit by swapping state."""

    def __init__(self, state: MemoryState | None = None) -> None:
        self.state = state or MemoryState()
        self._lock = asyncio.Lock()

    @asynccontextmanager
    async def transaction(self) -> AsyncGenerator[MemoryTransaction]:
        """Run a transaction on a copy; commit by replacing the state when the block succeeds."""
        async with self._lock:
            working = self.state.copy()
            yield MemoryTransaction(working)
            self.state = working

    async def close(self) -> None:
        """Nothing to release."""
