"""Authoritative scope discovery and target-existence rules."""

from __future__ import annotations

from typing import TYPE_CHECKING

from .rules import ScopeType, Visibility

if TYPE_CHECKING:
    from uuid import UUID

    from .facts import CatalogFacts
    from .rules import Scope


async def resource_scope(
    repository: CatalogFacts, kind: ScopeType, resource_id: UUID, visibility: Visibility
) -> Scope:
    """Resolve the target's discovery and complete ancestry before checking its capabilities.

    Args:
        repository: Authoritative catalog-fact projection.
        kind: Organization, project or dataset scope.
        resource_id: Target identity.
        visibility: Security's discovery projection.

    Returns:
        The target scope with authoritative ancestors.

    Raises:
        ValueError: If system scope is requested as a catalog resource.
    """
    if kind is ScopeType.SYSTEM:
        raise ValueError("system scope has no catalog resource")
    return await repository.resource_scope(kind, resource_id, visibility)


async def require_scope_exists(
    repository: CatalogFacts, scope_type: ScopeType, scope_id: UUID | None
) -> None:
    """Validate an already-authorized governance target without trusting caller ancestry.

    Args:
        repository: Authoritative existence and ancestry projection.
        scope_type: Target level.
        scope_id: Target identity, absent only for SYSTEM.

    Raises:
        ValueError: If the scope/id pair is inconsistent.
    """
    if scope_type is ScopeType.SYSTEM:
        if scope_id is not None:
            raise ValueError("SYSTEM scope takes no scope_id")
        return
    if scope_id is None:
        raise ValueError(f"{scope_type.value} scope requires a scope_id")
    await repository.resource_scope(scope_type, scope_id, Visibility.ALL)
