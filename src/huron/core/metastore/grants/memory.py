"""In-memory grants with the catalog → organization hierarchy."""

from __future__ import annotations

from typing import TYPE_CHECKING

from huron.core.security.rbac import PLATFORM, Role, Scope, ScopeType

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping, Sequence

    from huron.core.metastore.memory import MemoryState

__all__ = ["MemoryGrants"]


class MemoryGrants:
    """Grants in a :class:`MemoryState`."""

    def __init__(self, state: MemoryState) -> None:
        self._state = state

    async def roles_for_groups(self, groups: Iterable[str]) -> Sequence[tuple[Scope, Role]]:
        """Every ``(scope, role)`` granted to any of ``groups``."""
        wanted = set(groups)
        return sorted(
            {(scope, role) for scope, role, group in self._state.grants if group in wanted}
        )

    async def groups_for_scope(self, scope: Scope) -> Mapping[Role, Sequence[str]]:
        """Groups per role at exactly ``scope``."""
        found: dict[Role, list[str]] = {}
        for granted, role, group in sorted(self._state.grants):
            if granted == scope:
                found.setdefault(role, []).append(group)
        return found

    async def enclosing(self, scope: Scope) -> Sequence[Scope]:
        """``scope`` and its enclosing scopes, innermost first."""
        if scope.type is ScopeType.PLATFORM:
            return [PLATFORM]
        if scope.type is ScopeType.ORGANIZATION:
            return [scope, PLATFORM]
        assert scope.id is not None
        catalog = self._state.catalogs.get(scope.id)
        if catalog is None:
            return [scope, PLATFORM]
        return [scope, Scope.organization(catalog.organization_id), PLATFORM]

    async def replace(
        self, scope: Scope, role: Role, groups: Iterable[str], created_by: str
    ) -> tuple[list[str], list[str]]:
        """Make ``groups`` the exact set granted ``role`` at ``scope``."""
        wanted = set(groups)
        current = {g for s, r, g in self._state.grants if s == scope and r == role}
        for group in current - wanted:
            del self._state.grants[(scope, role, group)]
        for group in wanted - current:
            self._state.grants[(scope, role, group)] = created_by
        return sorted(wanted - current), sorted(current - wanted)

    async def delete_scope(self, scope: Scope) -> None:
        """Remove every grant at ``scope``."""
        for key in [key for key in self._state.grants if key[0] == scope]:
            del self._state.grants[key]
