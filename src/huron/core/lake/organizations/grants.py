"""Administration of role grants at platform, organization and catalog scope."""

from __future__ import annotations

from typing import TYPE_CHECKING

from huron.core.lake.audit import Action, AuditWriter, ObjectType
from huron.core.lake.lookups import find_catalog, find_organization
from huron.core.lake.organizations.declarations import UNMANAGED, Declarations
from huron.core.lake.organizations.models import OrganizationGroups
from huron.core.security.rbac import (
    CATALOG_ROLES,
    ORGANIZATION_ROLES,
    PLATFORM,
    Authorizer,
    EffectiveGroups,
    Grant,
    GrantInvalid,
    GrantSource,
    Privilege,
    Role,
    Scope,
    check_grant,
)

if TYPE_CHECKING:
    import uuid
    from collections.abc import Iterable

    from huron.core.lake.transaction import Transaction, UnitOfWork
    from huron.core.security.rbac import Actor
    from huron.pkg.clock import Clock

__all__ = ["GrantAdministration", "GrantChange", "record_grant_change"]


class GrantChange:
    """The groups a replacement added and removed."""

    def __init__(self, role: Role, groups: list[str], added: list[str], removed: list[str]) -> None:
        self.role = role
        self.groups = groups
        self.added = added
        self.removed = removed

    def as_dict(self) -> dict[str, object]:
        """Render for the API."""
        return {
            "role": str(self.role),
            "ldap_groups": self.groups,
            "added": self.added,
            "removed": self.removed,
        }


class GrantAdministration:
    """Reads and replaces the groups granted each role.

    The organization-scope groups of a declared organization (all four roles) belong to the
    configuration and cannot be replaced here.
    """

    def __init__(
        self,
        uow: UnitOfWork,
        clock: Clock,
        platform_admin_group: str,
        declarations: Declarations = UNMANAGED,
    ) -> None:
        self._uow = uow
        self._clock = clock
        self._platform_group = platform_admin_group
        self._declarations = declarations

    async def platform_admins(self, actor: Actor) -> list[str]:
        """Groups holding Platform Admin; needs ``ORGANIZATION_GRANT``."""
        async with self._uow.transaction() as tx:
            await Authorizer(tx.grants).require(actor, Privilege.ORGANIZATION_GRANT, PLATFORM)
            granted = await tx.grants.groups_for_scope(PLATFORM)
            return sorted(granted.get(Role.PLATFORM_ADMIN, []))

    async def set_platform_admins(self, actor: Actor, groups: Iterable[str]) -> GrantChange:
        """Replace the Platform Admin groups; the configured group always stays."""
        wanted = sorted(set(groups))
        async with self._uow.transaction() as tx:
            await Authorizer(tx.grants).require(actor, Privilege.ORGANIZATION_GRANT, PLATFORM)
            if self._platform_group not in wanted:
                raise GrantInvalid(
                    "you cannot revoke the Platform Admin role from the configured"
                    " platform admin group",
                    {"ldap_group": self._platform_group},
                )
            return await self._replace(
                tx, actor, PLATFORM, Role.PLATFORM_ADMIN, wanted, ObjectType.PLATFORM, None
            )

    async def organization_groups(self, actor: Actor, organization: str) -> OrganizationGroups:
        """Groups per organization-scope role; needs ``ORGANIZATION_READ`` at the organization."""
        async with self._uow.transaction() as tx:
            authz = Authorizer(tx.grants)
            found = await find_organization(tx, authz, actor, organization)
            scope = Scope.organization(found.id)
            await authz.require(actor, Privilege.ORGANIZATION_READ, scope)
            return OrganizationGroups.of(await tx.grants.groups_for_scope(scope))

    async def set_organization_role(
        self, actor: Actor, organization: str, role: Role, groups: Iterable[str]
    ) -> GrantChange:
        """Replace the groups of one organization-scope role of an undeclared organization.

        ``org_admin`` needs ``ORGANIZATION_GRANT`` (Platform Admin). The catalog roles, which every
        catalog of the organization inherits, need ``CATALOG_GRANT_ADMIN`` at the organization
        (Org Admin or above): an organization-wide Catalog Admin may grant members on each
        catalog, but not organization-wide.
        """
        if role not in ORGANIZATION_ROLES:
            raise GrantInvalid(f"{role} is not an organization role", {"role": str(role)})
        async with self._uow.transaction() as tx:
            authz = Authorizer(tx.grants)
            found = await find_organization(tx, authz, actor, organization)
            scope = Scope.organization(found.id)
            if role is Role.ORG_ADMIN:
                await authz.require(actor, Privilege.ORGANIZATION_GRANT, PLATFORM)
            else:
                await authz.require(actor, Privilege.CATALOG_GRANT_ADMIN, scope)
            self._declarations.require_undeclared(
                organization,
                f"The service configuration sets the {role} groups of this organization in "
                f"`groups.{role}`",
            )
            return await self._replace(
                tx, actor, scope, role, sorted(set(groups)), ObjectType.ORGANIZATION, found.id
            )

    async def catalog_groups(self, actor: Actor, catalog: str) -> EffectiveGroups:
        """Effective groups per role on a catalog, inherited ones included."""
        async with self._uow.transaction() as tx:
            authz = Authorizer(tx.grants)
            found = await find_catalog(tx, authz, actor, catalog)
            await authz.require(actor, Privilege.CATALOG_READ, Scope.catalog(found.id))
            return await authz.effective_groups(Scope.catalog(found.id))

    async def catalog_grant_sources(self, actor: Actor, catalog: str) -> list[GrantSource]:
        """Every grant holding on a catalog, with its scope; needs ``CATALOG_READ``."""
        async with self._uow.transaction() as tx:
            authz = Authorizer(tx.grants)
            found = await find_catalog(tx, authz, actor, catalog)
            await authz.require(actor, Privilege.CATALOG_READ, Scope.catalog(found.id))
            return await authz.grant_sources(Scope.catalog(found.id))

    async def set_catalog_role(
        self, actor: Actor, catalog: str, role: Role, groups: Iterable[str]
    ) -> GrantChange:
        """Replace the groups of a catalog role on one catalog.

        The groups add to those the catalog inherits from its organization. ``catalog_admin``
        needs ``CATALOG_GRANT_ADMIN``; ``contributor`` and ``reader`` need
        ``CATALOG_GRANT_MEMBER``.
        """
        if role not in CATALOG_ROLES:
            raise GrantInvalid(f"{role} is not a catalog role", {"role": str(role)})
        privilege = (
            Privilege.CATALOG_GRANT_ADMIN
            if role is Role.CATALOG_ADMIN
            else Privilege.CATALOG_GRANT_MEMBER
        )
        async with self._uow.transaction() as tx:
            authz = Authorizer(tx.grants)
            found = await find_catalog(tx, authz, actor, catalog)
            scope = Scope.catalog(found.id)
            await authz.require(actor, privilege, scope)
            return await self._replace(
                tx, actor, scope, role, sorted(set(groups)), ObjectType.CATALOG, found.id
            )

    async def _replace(
        self,
        tx: Transaction,
        actor: Actor,
        scope: Scope,
        role: Role,
        groups: list[str],
        object_type: ObjectType,
        object_id: uuid.UUID | None,
    ) -> GrantChange:
        for group in groups:
            check_grant(Grant(scope, role, group))
        added, removed = await tx.grants.replace(scope, role, groups, actor.subject)
        writer = AuditWriter(tx.audit, self._clock)
        await record_grant_change(writer, actor, role, object_type, object_id, added, removed)
        return GrantChange(role, groups, added, removed)


async def record_grant_change(
    writer: AuditWriter,
    actor: Actor | str,
    role: Role,
    object_type: ObjectType,
    object_id: uuid.UUID | None,
    added: Iterable[str],
    removed: Iterable[str],
) -> None:
    """Audit one grant and one revoke entry per group a replacement added and removed."""
    grant_action, revoke_action = _ACTIONS[object_type]
    is_catalog = object_type is ObjectType.CATALOG
    is_organization = object_type is ObjectType.ORGANIZATION
    for action, changed in ((grant_action, added), (revoke_action, removed)):
        for group in changed:
            await writer.record(
                actor,
                action,
                object_type,
                object_id,
                catalog_id=object_id if is_catalog else None,
                organization_id=object_id if is_organization else None,
                detail={"role": str(role), "ldap_group": group},
            )


_ACTIONS = {
    ObjectType.PLATFORM: (Action.PLATFORM_GRANT, Action.PLATFORM_REVOKE),
    ObjectType.ORGANIZATION: (Action.ORGANIZATION_GRANT, Action.ORGANIZATION_REVOKE),
    ObjectType.CATALOG: (Action.CATALOG_GRANT, Action.CATALOG_REVOKE),
}
