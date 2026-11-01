"""Organization operations."""

from __future__ import annotations

from typing import TYPE_CHECKING

from huron.core.lake.audit import Action, AuditWriter, ObjectType
from huron.core.lake.lookups import cursor_value, find_organization, page_of
from huron.core.lake.organizations.declarations import UNMANAGED, Declarations
from huron.core.lake.organizations.errors import OrganizationNotEmpty
from huron.core.lake.organizations.models import Organization, OrganizationView
from huron.core.security.rbac import PLATFORM, Authorizer, Privilege, Scope
from huron.pkg.identifiers import new_id
from huron.pkg.paging import Page, clamp_limit
from huron.schema.naming import check_segment

if TYPE_CHECKING:
    from huron.core.lake.transaction import Transaction, UnitOfWork
    from huron.core.security.rbac import Actor
    from huron.pkg.clock import Clock

__all__ = ["Organizations"]


class Organizations:
    """Create, read, list and delete organizations.

    In managed mode (``declarations.managed``) the configuration owns the organizations: creating
    one is refused, and a declared one cannot be deleted.
    """

    def __init__(
        self, uow: UnitOfWork, clock: Clock, declarations: Declarations = UNMANAGED
    ) -> None:
        self._uow = uow
        self._clock = clock
        self._declarations = declarations

    async def create(
        self, actor: Actor, name: str, display_name: str = "", description: str = ""
    ) -> OrganizationView:
        """Create an organization; needs ``ORGANIZATION_CREATE`` and unmanaged mode."""
        check_segment(name)
        async with self._uow.transaction() as tx:
            await Authorizer(tx.grants).require(actor, Privilege.ORGANIZATION_CREATE, PLATFORM)
            self._declarations.require_unmanaged()
            organization = Organization(
                id=new_id(),
                name=name,
                display_name=display_name or name,
                description=description,
                version=1,
                created_at=self._clock.now(),
                created_by=actor.subject,
            )
            await tx.organizations.insert(organization)
            await AuditWriter(tx.audit, self._clock).record(
                actor,
                Action.ORGANIZATION_CREATE,
                ObjectType.ORGANIZATION,
                organization.id,
                organization_id=organization.id,
                detail={"name": name},
            )
            return self._view(organization, 0)

    async def get(self, actor: Actor, name: str) -> OrganizationView:
        """An organization the actor may see."""
        async with self._uow.transaction() as tx:
            authz = Authorizer(tx.grants)
            organization = await find_organization(tx, authz, actor, name)
            return self._view(organization, await _visible_count(tx, authz, actor, organization))

    async def list(
        self, actor: Actor, cursor: str | None = None, limit: int | None = None
    ) -> Page[OrganizationView]:
        """Organizations the actor may see, sorted by name."""
        size = clamp_limit(limit)
        after = cursor_value(cursor)
        async with self._uow.transaction() as tx:
            authz = Authorizer(tx.grants)
            visible = await authz.visibility(actor)
            ids = None if visible.everything else visible.organization_ids
            rows = await tx.organizations.list(ids, None if after is None else str(after), size + 1)
            views = [self._view(o, await _visible_count(tx, authz, actor, o)) for o in rows]
        return page_of(views, size, lambda view: view.organization.name)

    async def delete(self, actor: Actor, name: str) -> None:
        """Delete an undeclared organization without catalogs; needs ``ORGANIZATION_DELETE``."""
        async with self._uow.transaction() as tx:
            authz = Authorizer(tx.grants)
            organization = await find_organization(tx, authz, actor, name)
            await authz.require(actor, Privilege.ORGANIZATION_DELETE, PLATFORM)
            self._declarations.require_undeclared(name, "remove it from there first")
            count = await tx.organizations.catalog_count(organization.id)
            if count:
                raise OrganizationNotEmpty(
                    f"organization {name!r} has {count} catalogs", {"catalog_count": count}
                )
            await tx.grants.delete_scope(Scope.organization(organization.id))
            await tx.organizations.delete(organization.id)
            await AuditWriter(tx.audit, self._clock).record(
                actor,
                Action.ORGANIZATION_DELETE,
                ObjectType.ORGANIZATION,
                organization.id,
                organization_id=organization.id,
                detail={"name": name},
            )

    def _view(self, organization: Organization, catalog_count: int) -> OrganizationView:
        declaration = self._declarations.get(organization.name)
        return OrganizationView(organization, catalog_count, declaration)


async def _visible_count(
    tx: Transaction, authz: Authorizer, actor: Actor, organization: Organization
) -> int:
    visible = await authz.visibility(actor)
    if visible.everything or organization.id in visible.managed_organization_ids:
        return await tx.organizations.catalog_count(organization.id)
    filters = (visible.managed_organization_ids, visible.catalog_ids)
    return len(await tx.catalogs.list(organization.id, filters, None, 100_000))
