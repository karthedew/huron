"""Reading the audit log of a collection or a catalog."""

from __future__ import annotations

from typing import TYPE_CHECKING

from huron.core.lake.audit.models import ObjectType
from huron.core.lake.lookups import cursor_value, find_catalog, find_collection, page_of
from huron.core.security.rbac import Authorizer, Privilege, Scope
from huron.pkg.paging import Page, clamp_limit, encode_cursor

if TYPE_CHECKING:
    import uuid

    from huron.core.lake.audit.models import AuditEntry
    from huron.core.lake.transaction import Transaction, UnitOfWork
    from huron.core.security.rbac import Actor

__all__ = ["AuditLog"]


class AuditLog:
    """Pages audit entries newest first; needs ``AUDIT_READ`` on the catalog."""

    def __init__(self, uow: UnitOfWork) -> None:
        self._uow = uow

    async def for_collection(
        self,
        actor: Actor,
        collection_id: uuid.UUID,
        cursor: str | None = None,
        limit: int | None = None,
    ) -> Page[AuditEntry]:
        """Entries about one collection."""
        size = clamp_limit(limit)
        before = _before(cursor)
        async with self._uow.transaction() as tx:
            authz = Authorizer(tx.grants)
            collection, catalog = await find_collection(
                tx, authz, actor, collection_id=collection_id
            )
            await authz.require(actor, Privilege.AUDIT_READ, Scope.catalog(catalog.id))
            rows = await tx.audit.for_object(collection.id, before, size + 1)
        return page_of(rows, size, lambda entry: entry.id)

    async def for_catalog(
        self, actor: Actor, catalog: str, cursor: str | None = None, limit: int | None = None
    ) -> Page[AuditEntry]:
        """Entries within one catalog.

        Callers who may not see drafts get no entries about collections that are drafts or no
        longer exist, so draft names never leak through the log.
        """
        size = clamp_limit(limit)
        before = _before(cursor)
        async with self._uow.transaction() as tx:
            authz = Authorizer(tx.grants)
            found = await find_catalog(tx, authz, actor, catalog)
            scope = Scope.catalog(found.id)
            await authz.require(actor, Privilege.AUDIT_READ, scope)
            rows = list(await tx.audit.for_catalog(found.id, before, size + 1))
            next_cursor = encode_cursor([rows[size - 1].id]) if len(rows) > size else None
            shown = rows[:size]
            if not await authz.holds(actor, Privilege.COLLECTION_CREATE, scope):
                shown = [entry for entry in shown if await _settled_or_other(tx, entry)]
        return Page(tuple(shown), next_cursor)


def _before(cursor: str | None) -> int | None:
    value = cursor_value(cursor)
    return value if isinstance(value, int) else None


async def _settled_or_other(tx: Transaction, entry: AuditEntry) -> bool:
    if entry.object_type is not ObjectType.COLLECTION or entry.object_id is None:
        return True
    collection = await tx.collections.get(entry.object_id)
    return collection is not None and collection.settled
