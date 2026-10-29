"""Authorization: privilege checks, visibility and effective groups per catalog."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from huron.core.security.rbac.grants import Scope
from huron.core.security.rbac.roles import ROLE_PRIVILEGES, Role, ScopeType
from huron.pkg.errors import Forbidden

if TYPE_CHECKING:
    import uuid

    from huron.core.security.rbac.actor import Actor
    from huron.core.security.rbac.ports import GrantReader
    from huron.core.security.rbac.privileges import Privilege

__all__ = ["Authorizer", "EffectiveGroups", "Visibility"]


@dataclass(frozen=True, slots=True)
class Visibility:
    """What an actor may see: everything, or these organizations and catalogs.

    ``managed_organization_ids`` are the organizations where the actor holds an organization
    role, so every catalog in them is visible; ``organization_ids`` adds the organizations of
    individually granted catalogs.
    """

    everything: bool
    organization_ids: frozenset[uuid.UUID]
    catalog_ids: frozenset[uuid.UUID]
    managed_organization_ids: frozenset[uuid.UUID] = frozenset()


@dataclass(frozen=True, slots=True)
class EffectiveGroups:
    """The groups holding each role on a catalog, inherited ones included."""

    platform_admin: tuple[str, ...] = ()
    org_admin: tuple[str, ...] = ()
    catalog_admin: tuple[str, ...] = ()
    contributor: tuple[str, ...] = ()
    reader: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, list[str]]:
        """Render as the API body of ``GET /catalogs/{catalog}/grants``."""
        return {role.value: list(getattr(self, role.value)) for role in Role}


class Authorizer:
    """Answers whether an actor holds a privilege at a scope.

    Roles come only from the current grants for the actor's groups, never from the token.
    """

    def __init__(self, grants: GrantReader) -> None:
        self._grants = grants
        self._roles: dict[frozenset[str], frozenset[tuple[Scope, Role]]] = {}

    async def roles_for(self, actor: Actor) -> frozenset[tuple[Scope, Role]]:
        """Every ``(scope, role)`` the actor holds through their groups."""
        cached = self._roles.get(actor.groups)
        if cached is None:
            cached = frozenset(await self._grants.roles_for_groups(sorted(actor.groups)))
            self._roles[actor.groups] = cached
        return cached

    async def holds(self, actor: Actor, privilege: Privilege, scope: Scope) -> bool:
        """Whether a role held at ``scope`` or an enclosing scope carries ``privilege``."""
        held = await self.roles_for(actor)
        if not held:
            return False
        scopes = set(await self._grants.enclosing(scope))
        return any(
            privilege in ROLE_PRIVILEGES[role] for granted, role in held if granted in scopes
        )

    async def require(self, actor: Actor, privilege: Privilege, scope: Scope) -> None:
        """Raise :class:`Forbidden` unless the actor holds ``privilege`` at ``scope``."""
        if not await self.holds(actor, privilege, scope):
            raise Forbidden(
                f"{privilege} is required",
                {"privilege": str(privilege), "scope": str(scope.type)},
            )

    async def visibility(self, actor: Actor) -> Visibility:
        """The organizations and catalogs the actor may see."""
        managed: set[uuid.UUID] = set()
        organizations: set[uuid.UUID] = set()
        catalogs: set[uuid.UUID] = set()
        for scope, _ in await self.roles_for(actor):
            if scope.type is ScopeType.PLATFORM:
                return Visibility(True, frozenset(), frozenset())
            assert scope.id is not None
            if scope.type is ScopeType.ORGANIZATION:
                managed.add(scope.id)
            else:
                catalogs.add(scope.id)
                organizations.update(await self._organization_of(scope))
        return Visibility(
            False, frozenset(organizations | managed), frozenset(catalogs), frozenset(managed)
        )

    async def can_see_organization(self, actor: Actor, organization_id: uuid.UUID) -> bool:
        """Whether the actor holds any role at, above or below the organization."""
        visible = await self.visibility(actor)
        return visible.everything or organization_id in visible.organization_ids

    async def can_see_catalog(self, actor: Actor, catalog_id: uuid.UUID) -> bool:
        """Whether the actor holds any role at the catalog or a scope enclosing it."""
        held = {scope for scope, _ in await self.roles_for(actor)}
        if not held:
            return False
        enclosing = await self._grants.enclosing(Scope.catalog(catalog_id))
        return any(scope in held for scope in enclosing)

    async def effective_groups(self, scope: Scope) -> EffectiveGroups:
        """Groups per role at ``scope``, including those inherited from enclosing scopes."""
        collected: dict[Role, set[str]] = {role: set() for role in Role}
        for enclosing in await self._grants.enclosing(scope):
            granted = await self._grants.groups_for_scope(enclosing)
            for role, groups in granted.items():
                collected[role].update(groups)
        return EffectiveGroups(**{role.value: tuple(sorted(collected[role])) for role in Role})

    async def _organization_of(self, scope: Scope) -> set[uuid.UUID]:
        return {
            enclosing.id
            for enclosing in await self._grants.enclosing(scope)
            if enclosing.type is ScopeType.ORGANIZATION and enclosing.id is not None
        }
