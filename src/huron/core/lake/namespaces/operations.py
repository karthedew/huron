"""Namespace operations."""

from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING

from huron.core.lake.audit import Action, AuditWriter, ObjectType
from huron.core.lake.lookups import cursor_value, find_catalog, find_namespace, page_of
from huron.core.lake.namespaces.errors import NamespaceNotEmpty
from huron.core.lake.namespaces.models import Namespace, NamespaceView
from huron.core.security.rbac import Authorizer, Privilege, Scope
from huron.pkg.identifiers import new_id
from huron.pkg.paging import Page, clamp_limit
from huron.schema.naming import check_segment, parse_identifier

if TYPE_CHECKING:
    from huron.core.lake.catalogs.models import Catalog
    from huron.core.lake.transaction import Transaction, UnitOfWork
    from huron.core.security.rbac import Actor
    from huron.pkg.clock import Clock

__all__ = ["Namespaces"]


class Namespaces:
    """Create, read, configure and delete namespaces."""

    def __init__(self, uow: UnitOfWork, clock: Clock) -> None:
        self._uow = uow
        self._clock = clock

    async def create(
        self,
        actor: Actor,
        catalog: str,
        parent: str,
        name: str,
        collections_allowed: bool = False,
    ) -> NamespaceView:
        """Create ``name`` under ``parent`` (empty: the catalog root)."""
        check_segment(name)
        path = f"{parent}.{name}" if parent else name
        parse_identifier(f"{catalog}.{path}")
        async with self._uow.transaction() as tx:
            found = await self._catalog(tx, actor, catalog, Privilege.NAMESPACE_CREATE)
            await tx.lock_catalog(found.id)
            parent_id = (await find_namespace(tx, found, parent)).id if parent else None
            namespace = Namespace(
                id=new_id(),
                catalog_id=found.id,
                parent_id=parent_id,
                name=name,
                path=path,
                collections_allowed=collections_allowed,
                version=1,
                created_at=self._clock.now(),
                created_by=actor.subject,
            )
            await tx.namespaces.insert(namespace)
            await self._audit(tx, actor, Action.NAMESPACE_CREATE, found, namespace)
            return await _view(tx, actor, found, namespace)

    async def get(self, actor: Actor, catalog: str, path: str) -> NamespaceView:
        """A namespace in a catalog the actor may read."""
        async with self._uow.transaction() as tx:
            found = await self._catalog(tx, actor, catalog, Privilege.CATALOG_READ)
            return await _view(tx, actor, found, await find_namespace(tx, found, path))

    async def children(
        self,
        actor: Actor,
        catalog: str,
        parent: str = "",
        cursor: str | None = None,
        limit: int | None = None,
    ) -> Page[NamespaceView]:
        """Direct children of ``parent`` (empty for the catalog root), sorted by name."""
        size = clamp_limit(limit)
        after = cursor_value(cursor)
        async with self._uow.transaction() as tx:
            found = await self._catalog(tx, actor, catalog, Privilege.CATALOG_READ)
            parent_id = (await find_namespace(tx, found, parent)).id if parent else None
            rows = await tx.namespaces.children(
                found.id, parent_id, None if after is None else str(after), size + 1
            )
            views = [await _view(tx, actor, found, namespace) for namespace in rows]
        return page_of(views, size, lambda view: view.namespace.name)

    async def configure(
        self, actor: Actor, catalog: str, path: str, collections_allowed: bool
    ) -> NamespaceView:
        """Allow or forbid collections; forbidding needs the namespace to hold none."""
        async with self._uow.transaction() as tx:
            found = await self._catalog(tx, actor, catalog, Privilege.NAMESPACE_CONFIGURE)
            await tx.lock_catalog(found.id)
            namespace = await find_namespace(tx, found, path)
            _, collections = await tx.namespaces.child_counts(namespace.id)
            if not collections_allowed and collections:
                raise NamespaceNotEmpty(
                    f"{catalog}.{path} still holds {collections} collections",
                    {"collection_count": collections},
                )
            if namespace.collections_allowed != collections_allowed:
                namespace = replace(
                    namespace,
                    collections_allowed=collections_allowed,
                    version=namespace.version + 1,
                )
                await tx.namespaces.update(namespace)
                await self._audit(
                    tx,
                    actor,
                    Action.NAMESPACE_CONFIGURE,
                    found,
                    namespace,
                    {"collections_allowed": collections_allowed},
                )
            return await _view(tx, actor, found, namespace)

    async def delete(self, actor: Actor, catalog: str, path: str) -> None:
        """Delete a namespace with no child namespaces and no collections (drafts included)."""
        async with self._uow.transaction() as tx:
            found = await self._catalog(tx, actor, catalog, Privilege.NAMESPACE_DELETE)
            await tx.lock_catalog(found.id)
            namespace = await find_namespace(tx, found, path)
            namespaces, collections = await tx.namespaces.child_counts(namespace.id)
            if namespaces or collections:
                raise NamespaceNotEmpty(
                    f"{catalog}.{path} is not empty",
                    {"namespace_count": namespaces, "collection_count": collections},
                )
            await tx.namespaces.delete(namespace.id)
            await self._audit(tx, actor, Action.NAMESPACE_DELETE, found, namespace)

    async def _catalog(
        self, tx: Transaction, actor: Actor, name: str, privilege: Privilege
    ) -> Catalog:
        authz = Authorizer(tx.grants)
        found = await find_catalog(tx, authz, actor, name)
        await authz.require(actor, privilege, Scope.catalog(found.id))
        return found

    async def _audit(
        self,
        tx: Transaction,
        actor: Actor,
        action: Action,
        catalog: Catalog,
        namespace: Namespace,
        extra: dict[str, object] | None = None,
    ) -> None:
        await AuditWriter(tx.audit, self._clock).record(
            actor,
            action,
            ObjectType.NAMESPACE,
            namespace.id,
            catalog_id=catalog.id,
            organization_id=catalog.organization_id,
            detail={"path": namespace.path, **(extra or {})},
        )


async def _view(
    tx: Transaction, actor: Actor, catalog: Catalog, namespace: Namespace
) -> NamespaceView:
    organization = await tx.organizations.get(catalog.organization_id)
    assert organization is not None
    namespaces, collections = await tx.namespaces.child_counts(namespace.id)
    drafts_visible = await Authorizer(tx.grants).holds(
        actor, Privilege.COLLECTION_CREATE, Scope.catalog(catalog.id)
    )
    if not drafts_visible:
        collections -= await tx.namespaces.draft_count(namespace.id)
    return NamespaceView(namespace, catalog.name, organization.name, namespaces, collections)
