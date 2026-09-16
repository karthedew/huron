"""Authorized policy definition and attachment."""

from __future__ import annotations

from typing import TYPE_CHECKING

from huron.core.security.scopes import require_scope_exists

if TYPE_CHECKING:
    from uuid import UUID

    from huron.core.security.facts import CatalogFacts
    from huron.core.security.ports import PolicyStore
    from huron.core.security.rules import ScopeType
    from huron.core.security.types import Policy, PolicyAttachment

    from .access import AccessPolicy


class Policies:
    """Create, list and attach policy definitions, with fresh authority on attachment.

    A policy definition is creatable and listable by any authenticated
    actor, since defining one grants nothing; attaching it to a scope is
    the guarded act and always requires that scope's own
    ``policy_attach`` capability, checked at a scope confirmed to exist.
    """

    def __init__(self, access: AccessPolicy, hierarchy: CatalogFacts, store: PolicyStore) -> None:
        """Bind policy administration to one authenticated actor.

        Args:
            access: The caller's authorization policy.
            hierarchy: Committed catalog readers, used to confirm a scope exists.
            store: Policy definition and attachment persistence.
        """
        self._access = access
        self._hierarchy = hierarchy
        self._store = store

    async def create_policy(
        self, *, policy_type: str, name: str, spec: dict[str, object]
    ) -> Policy:
        """Store a policy definition; any authenticated actor may create one.

        Args:
            policy_type: Registered policy kind.
            name: Human-readable name.
            spec: Policy configuration.

        Returns:
            The stored policy, with its generated id and timestamp.
        """
        created_by = self._access.actor.subject
        return await self._store.create_policy(
            policy_type=policy_type, name=name, spec=spec, created_by=created_by
        )

    async def attach_policy(
        self, policy_id: UUID, *, scope_type: ScopeType, scope_id: UUID
    ) -> PolicyAttachment:
        """Attach an existing policy at a scope that is known to exist.

        Requires ``{scope}.policy_attach`` at the target scope; policies
        never attach at SYSTEM scope.

        Args:
            policy_id: Policy identifier.
            scope_type: Target scope level.
            scope_id: Target identifier.

        Returns:
            The stored attachment.
        """
        await self._access.require(
            f"{scope_type.value.lower()}.policy_attach", scope_type, scope_id
        )
        await require_scope_exists(self._hierarchy, scope_type, scope_id)
        attached_by = self._access.actor.subject
        return await self._store.attach_policy(
            policy_id, scope_type=scope_type, scope_id=scope_id, attached_by=attached_by
        )

    async def list_policies(self) -> list[Policy]:
        """List every policy definition; any authenticated actor may list them.

        Returns:
            All policies, ordered by ``(name, id)``.
        """
        return await self._store.list_policies()
