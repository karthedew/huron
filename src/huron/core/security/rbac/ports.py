"""Ports the authorizer reads grants through and administration writes them through."""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping, Sequence

    from huron.core.security.rbac.grants import Scope
    from huron.core.security.rbac.roles import Role

__all__ = ["GrantReader", "GrantWriter"]


class GrantReader(Protocol):
    """Reads grants and the scope hierarchy."""

    async def roles_for_groups(self, groups: Iterable[str]) -> Sequence[tuple[Scope, Role]]:
        """Every ``(scope, role)`` granted to any of ``groups``."""
        ...

    async def groups_for_scope(self, scope: Scope) -> Mapping[Role, Sequence[str]]:
        """The groups granted each role exactly at ``scope``."""
        ...

    async def enclosing(self, scope: Scope) -> Sequence[Scope]:
        """``scope`` and every scope enclosing it, innermost first, ending with the platform."""
        ...


class GrantWriter(Protocol):
    """Replaces the groups granted one role at one scope."""

    async def replace(
        self, scope: Scope, role: Role, groups: Iterable[str], created_by: str
    ) -> tuple[list[str], list[str]]:
        """Make ``groups`` the exact set; return the ``(added, removed)`` groups, sorted."""
        ...
