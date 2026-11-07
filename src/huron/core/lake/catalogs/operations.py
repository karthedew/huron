"""Catalog operations, including schema assignment."""

from __future__ import annotations

import re
from dataclasses import replace
from typing import TYPE_CHECKING, Any

from huron.core.lake.audit import Action, AuditWriter, ObjectType
from huron.core.lake.catalogs.errors import CatalogNotEmpty, CatalogNotFound
from huron.core.lake.catalogs.models import Catalog, CatalogView
from huron.core.lake.listing import ListOrder
from huron.core.lake.lookups import find_catalog, find_organization
from huron.core.lake.schemas.errors import SchemaScope
from huron.core.lake.schemas.models import BASE_SCHEMA_NAME
from huron.core.security.rbac import Authorizer, Privilege, Scope
from huron.pkg.errors import Invalid, NotFound
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
    """Create, read, list and delete catalogs, and set their schema and their share group.

    Changes to the whole catalog take the catalog lock and read the catalog again after it, so
    they apply to the catalog as the previous change left it.
    """

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
        share_group: str | None = None,
    ) -> CatalogView:
        """Create a catalog in an organization; needs ``CATALOG_CREATE`` on it."""
        check_segment(name)
        _check_share_group(share_group)
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
                share_group=share_group,
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
        ordering: ListOrder | None = None,
    ) -> Page[CatalogView]:
        """Catalogs the actor may see, optionally within one organization."""
        ordering = ordering or ListOrder()
        size = clamp_limit(limit)
        after = ordering.after(cursor)
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
            rows = await tx.catalogs.list(owner_id, filters, after, size + 1, ordering)
            views = [await _view(tx, catalog) for catalog in rows]
        return ordering.page(views, size, lambda view: view.catalog)

    async def delete(self, actor: Actor, name: str) -> str:
        """Delete a catalog without namespaces; needs ``CATALOG_DELETE``.

        The answer is the directory the catalog had, in the form of :attr:`CatalogView.disk_path`.
        """
        async with self._uow.transaction() as tx:
            authz = Authorizer(tx.grants)
            catalog = await find_catalog(tx, authz, actor, name)
            await authz.require(actor, Privilege.CATALOG_DELETE, Scope.catalog(catalog.id))
            await tx.lock_catalog(catalog.id)
            view = await _view(tx, catalog)
            if view.namespace_count:
                raise CatalogNotEmpty(
                    f"catalog {name!r} has {view.namespace_count} namespaces",
                    {"namespace_count": view.namespace_count},
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
            return view.disk_path

    async def assign_schema(
        self, actor: Actor, name: str, schema_id: uuid.UUID
    ) -> tuple[CatalogView, RecomputeResult]:
        """Assign a registry entry to the catalog and re-validate its collections."""
        async with self._uow.transaction() as tx:
            catalog = await _locked(tx, actor, name, Privilege.SCHEMA_ASSIGN)
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

    async def set_share_group(self, actor: Actor, name: str, group: str | None) -> CatalogView:
        """Set the catalog's share group, or clear it with ``None``; needs ``CATALOG_GRANT_ADMIN``.

        Every call counts as a change: it raises the catalog's version and writes an audit entry.
        """
        _check_share_group(group)
        async with self._uow.transaction() as tx:
            catalog = await _locked(tx, actor, name, Privilege.CATALOG_GRANT_ADMIN)
            updated = replace(catalog, share_group=group, version=catalog.version + 1)
            await tx.catalogs.update(updated)
            await AuditWriter(tx.audit, self._clock).record(
                actor,
                Action.CATALOG_SET_SHARE_GROUP,
                ObjectType.CATALOG,
                catalog.id,
                catalog_id=catalog.id,
                organization_id=catalog.organization_id,
                detail={"share_group": group, "previous": catalog.share_group},
            )
            return await _view(tx, updated)

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


async def _locked(tx: Transaction, actor: Actor, name: str, privilege: Privilege) -> Catalog:
    """The catalog named ``name``, read again after its lock once ``actor`` holds ``privilege``.

    A change that held the lock first may have changed or deleted the catalog.
    """
    authz = Authorizer(tx.grants)
    found = await find_catalog(tx, authz, actor, name)
    await authz.require(actor, privilege, Scope.catalog(found.id))
    await tx.lock_catalog(found.id)
    catalog = await tx.catalogs.get(found.id)
    if catalog is None:
        raise CatalogNotFound(name)
    return catalog


def _check_share_group(group: str | None) -> None:
    if group is not None and _SHARE_GROUP.fullmatch(group) is None:
        raise Invalid(
            "the share group must be a POSIX group name. It starts with a letter or an underscore"
            " and has at most 32 letters, digits, underscores, periods and hyphens",
            {"share_group": group},
        )


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
            "a catalog can use only platform schemas or the schemas of its organization",
            {"schema": str(schema_id)},
        )
    return schema


_SHARE_GROUP = re.compile(r"[A-Za-z_][A-Za-z0-9_.-]{0,31}")
