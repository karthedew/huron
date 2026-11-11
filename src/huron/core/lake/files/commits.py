"""Recorded files and commits: the reads of what commit requests published."""

from __future__ import annotations

from typing import TYPE_CHECKING

from huron.core.lake.lookups import cursor_value, find_collection, page_of
from huron.core.security.rbac import Authorizer, Privilege, Scope
from huron.pkg.identifiers import parse_id
from huron.pkg.paging import Page, clamp_limit

if TYPE_CHECKING:
    import uuid

    from huron.core.lake.collections.models import Collection
    from huron.core.lake.files.models import Commit, FileRecord
    from huron.core.lake.transaction import Transaction, UnitOfWork
    from huron.core.security.rbac import Actor

__all__ = ["Commits"]


class Commits:
    """Lists the recorded files and the commits of a collection for a reader."""

    def __init__(self, uow: UnitOfWork) -> None:
        self._uow = uow

    async def list_files(
        self,
        actor: Actor,
        collection_id: uuid.UUID,
        cursor: str | None = None,
        limit: int | None = None,
    ) -> Page[FileRecord]:
        """Recorded files sorted by their case-folded path."""
        size = clamp_limit(limit)
        after = cursor_value(cursor)
        async with self._uow.transaction() as tx:
            collection = await self._readable(tx, actor, collection_id)
            rows = await tx.files.list(
                collection.id, None if after is None else str(after), size + 1
            )
        return page_of(rows, size, lambda record: record.rel_path_key)

    async def list_commits(
        self,
        actor: Actor,
        collection_id: uuid.UUID,
        cursor: str | None = None,
        limit: int | None = None,
    ) -> Page[Commit]:
        """Commits newest first."""
        size = clamp_limit(limit)
        before = cursor_value(cursor)
        async with self._uow.transaction() as tx:
            collection = await self._readable(tx, actor, collection_id)
            rows = await tx.commits.list(
                collection.id, None if before is None else parse_id(str(before)), size + 1
            )
        return page_of(rows, size, lambda commit: str(commit.id))

    async def _readable(
        self, tx: Transaction, actor: Actor, collection_id: uuid.UUID
    ) -> Collection:
        authz = Authorizer(tx.grants)
        collection, catalog = await find_collection(tx, authz, actor, collection_id=collection_id)
        await authz.require(actor, Privilege.COLLECTION_READ, Scope.catalog(catalog.id))
        return collection
