"""Catalog operations, including schema assignment."""

from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING, Any

from huron.core.lake.audit import Action, AuditWriter, ObjectType
from huron.core.lake.catalogs.errors import CatalogNotEmpty
from huron.core.lake.catalogs.models import Catalog, CatalogView
from huron.core.lake.lookups import cursor_value, find_catalog, find_organization, page_of
from huron.core.lake.schemas.errors import SchemaScope
from huron.core.lake.schemas.models import BASE_SCHEMA_NAME
from huron.core.security.rbac import Authorizer, Privilege, Scope
from huron.pkg.errors import NotFound
from huron.pkg.identifiers import new_id
from huron.pkg.paging import Page, clamp_limit
from huron.schema.naming import check_segment

if TYPE_CHECKING:
    import uuid

    from huron.core.lake.schemas.completeness import Completeness, RecomputeResult
    from huron.core.lake.schemas.models import SchemaEntry
    from huron.core.lake.schemas.registry import SchemaResolver
    from huron.core.lake.transaction import Transaction, UnitOfWork
    from huron.core.security.rbac import Actor
    from huron.pkg.clock import Clock

__all__ = ["Catalogs"]


class Catalogs:
    """Create, read, list and delete catalogs and assign their schema."""

    def __init__(
        self,
        uow: UnitOfWork,
        clock: Clock,
        resolver: SchemaResolver,
        completeness: Completeness,
    ) -> None:
        self._uow = uow
        self._clock = clock
        self._resolver = resolver
        self._completeness = completeness

    async def create(
        self,
        actor: Actor,
        organization: str,
        name: str,
        display_name: str = "",
        description: str = "",
        schema_id: uuid.UUID | None = None,
    ) -> CatalogView:
        """Create a catalog in an organization; needs ``CATALOG_CREATE`` on it."""
        check_segment(name)
        async with self._uow.transaction() as tx:
            authz = Authorizer(tx.grants)
            owner = await find_organization(tx, authz, actor, organization)
            await authz.require(actor, Privilege.CATALOG_CREATE, Scope.organization(owner.id))
            schema = await _schema_for(tx, owner.id, schema_id)
            catalog = Catalog(
                id=new_id(),
                organization_id=owner.id,
                name=name,
                display_name=display_name or name,
                description=description,
                schema_id=schema.id,
                version=1,
                created_at=self._clock.now(),
                created_by=actor.subject,
            )
            await tx.catalogs.insert(catalog)
            await AuditWriter(tx.audit, self._clock).record(
                actor,
                Action.CATALOG_CREATE,
                ObjectType.CATALOG,
                catalog.id,
                catalog_id=catalog.id,
                organization_id=owner.id,
                detail={"name": name, "schema_id": str(schema.id)},
            )
            return await _view(tx, catalog)

    async def get(self, actor: Actor, name: str) -> CatalogView:
        """A catalog the actor may see."""
        async with self._uow.transaction() as tx:
            catalog = await self._readable(tx, actor, name)
            return await _view(tx, catalog)

    async def list(
        self,
        actor: Actor,
        organization: str | None = None,
        cursor: str | None = None,
        limit: int | None = None,
    ) -> Page[CatalogView]:
        """Catalogs the actor may see, optionally within one organization."""
        size = clamp_limit(limit)
        after = cursor_value(cursor)
        async with self._uow.transaction() as tx:
            authz = Authorizer(tx.grants)
            visible = await authz.visibility(actor)
            owner_id = None
            if organization is not None:
                owner_id = (await find_organization(tx, authz, actor, organization)).id
            filters = (
                None
                if visible.everything
                else (visible.managed_organization_ids, visible.catalog_ids)
            )
            rows = await tx.catalogs.list(
                owner_id, filters, None if after is None else str(after), size + 1
            )
            views = [await _view(tx, catalog) for catalog in rows]
        return page_of(views, size, lambda view: view.catalog.name)

    async def delete(self, actor: Actor, name: str) -> None:
        """Delete a catalog without namespaces; needs ``CATALOG_DELETE``."""
        async with self._uow.transaction() as tx:
            authz = Authorizer(tx.grants)
            catalog = await find_catalog(tx, authz, actor, name)
            await authz.require(actor, Privilege.CATALOG_DELETE, Scope.catalog(catalog.id))
            await tx.lock_catalog(catalog.id)
            count = await tx.catalogs.namespace_count(catalog.id)
            if count:
                raise CatalogNotEmpty(
                    f"catalog {name!r} has {count} namespaces", {"namespace_count": count}
                )
            await tx.grants.delete_scope(Scope.catalog(catalog.id))
            await tx.catalogs.delete(catalog.id)
            await AuditWriter(tx.audit, self._clock).record(
                actor,
                Action.CATALOG_DELETE,
                ObjectType.CATALOG,
                catalog.id,
                catalog_id=catalog.id,
                organization_id=catalog.organization_id,
                detail={"name": name},
            )

    async def assign_schema(
        self, actor: Actor, name: str, schema_id: uuid.UUID
    ) -> tuple[CatalogView, RecomputeResult]:
        """Assign a registry entry to the catalog and re-validate its collections."""
        async with self._uow.transaction() as tx:
            authz = Authorizer(tx.grants)
            catalog = await find_catalog(tx, authz, actor, name)
            await authz.require(actor, Privilege.SCHEMA_ASSIGN, Scope.catalog(catalog.id))
            await tx.lock_catalog(catalog.id)
            schema = await _schema_for(tx, catalog.organization_id, schema_id)
            updated = replace(catalog, schema_id=schema.id, version=catalog.version + 1)
            await tx.catalogs.update(updated)
            await AuditWriter(tx.audit, self._clock).record(
                actor,
                Action.CATALOG_ASSIGN_SCHEMA,
                ObjectType.CATALOG,
                catalog.id,
                catalog_id=catalog.id,
                organization_id=catalog.organization_id,
                detail={"schema_id": str(schema.id), "previous": str(catalog.schema_id)},
            )
            result = await self._completeness.recompute(tx, actor, updated)
            return await _view(tx, updated), result

    async def resolved_schema(self, actor: Actor, name: str) -> dict[str, Any]:
        """The catalog's composed schema document."""
        async with self._uow.transaction() as tx:
            catalog = await self._readable(tx, actor, name)
            return await self._resolver.resolve(tx.schemas, catalog.schema_id)

    async def _readable(self, tx: Transaction, actor: Actor, name: str) -> Catalog:
        authz = Authorizer(tx.grants)
        catalog = await find_catalog(tx, authz, actor, name)
        await authz.require(actor, Privilege.CATALOG_READ, Scope.catalog(catalog.id))
        return catalog


async def _view(tx: Transaction, catalog: Catalog) -> CatalogView:
    organization = await tx.organizations.get(catalog.organization_id)
    schema = await tx.schemas.get(catalog.schema_id)
    assert organization is not None and schema is not None
    count = await tx.catalogs.namespace_count(catalog.id)
    return CatalogView(catalog, organization.name, schema.ref, count)


async def _schema_for(
    tx: Transaction, organization_id: uuid.UUID, schema_id: uuid.UUID | None
) -> SchemaEntry:
    if schema_id is None:
        base = await tx.schemas.latest(None, BASE_SCHEMA_NAME)
        if base is None:
            raise NotFound("the base schema is not installed", {"schema": BASE_SCHEMA_NAME})
        return base
    schema = await tx.schemas.get(schema_id)
    if schema is None:
        raise NotFound("schema not found", {"schema": str(schema_id)})
    if schema.organization_id not in (None, organization_id):
        raise SchemaScope(
            "a catalog can only use platform schemas or its organization's",
            {"schema": str(schema_id)},
        )
    return schema
