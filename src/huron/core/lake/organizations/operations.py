"""Organization operations."""

from __future__ import annotations

from typing import TYPE_CHECKING

from huron.core.lake.audit import Action, AuditWriter, ObjectType
from huron.core.lake.lookups import cursor_value, find_organization, page_of
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
    """Create, read, list and delete organizations."""

    def __init__(self, uow: UnitOfWork, clock: Clock) -> None:
        self._uow = uow
        self._clock = clock

    async def create(
        self, actor: Actor, name: str, display_name: str = "", description: str = ""
    ) -> OrganizationView:
        """Create an organization; needs ``ORGANIZATION_CREATE``."""
        check_segment(name)
        async with self._uow.transaction() as tx:
            await Authorizer(tx.grants).require(actor, Privilege.ORGANIZATION_CREATE, PLATFORM)
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
            return OrganizationView(organization, 0)

    async def get(self, actor: Actor, name: str) -> OrganizationView:
        """An organization the actor may see."""
        async with self._uow.transaction() as tx:
            authz = Authorizer(tx.grants)
            organization = await find_organization(tx, authz, actor, name)
            return OrganizationView(
                organization, await _visible_count(tx, authz, actor, organization)
            )

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
            views = [OrganizationView(o, await _visible_count(tx, authz, actor, o)) for o in rows]
        return page_of(views, size, lambda view: view.organization.name)

    async def delete(self, actor: Actor, name: str) -> None:
        """Delete an organization without catalogs; needs ``ORGANIZATION_DELETE``."""
        async with self._uow.transaction() as tx:
            authz = Authorizer(tx.grants)
            organization = await find_organization(tx, authz, actor, name)
            await authz.require(actor, Privilege.ORGANIZATION_DELETE, PLATFORM)
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


async def _visible_count(
    tx: Transaction, authz: Authorizer, actor: Actor, organization: Organization
) -> int:
    visible = await authz.visibility(actor)
    if visible.everything or organization.id in visible.managed_organization_ids:
        return await tx.organizations.catalog_count(organization.id)
    filters = (visible.managed_organization_ids, visible.catalog_ids)
    return len(await tx.catalogs.list(organization.id, filters, None, 100_000))
