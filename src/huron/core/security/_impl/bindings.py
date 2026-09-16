"""Authorized role-binding administration."""

from __future__ import annotations

from typing import TYPE_CHECKING

from huron.core.security.rules import ScopeType
from huron.core.security.scopes import require_scope_exists

if TYPE_CHECKING:
    from datetime import datetime
    from uuid import UUID

    from huron.core.security.facts import CatalogFacts
    from huron.core.security.ports import BindingStore
    from huron.core.security.types import RoleBindingRecord

    from .access import AccessPolicy


class Bindings:
    """Grant, list and revoke role bindings, with fresh authority checked on every call.

    System, organization, project and dataset admission are explicit: a
    grant or a listing always requires ``rbac.binding_manage`` at the
    addressed scope, and the scope must exist there (independent of the
    caller's own discovery rights, which the permission check already
    applied) before the store is ever touched.
    """

    def __init__(self, access: AccessPolicy, hierarchy: CatalogFacts, store: BindingStore) -> None:
        """Bind role-binding administration to one authenticated actor.

        Args:
            access: The caller's authorization policy.
            hierarchy: Committed catalog readers, used to confirm a scope exists.
            store: Role-binding persistence.
        """
        self._access = access
        self._hierarchy = hierarchy
        self._store = store

    async def grant_role(
        self,
        *,
        principal: str,
        role_code: str,
        scope_type: ScopeType,
        scope_id: UUID | None,
        expires_at: datetime | None = None,
    ) -> RoleBindingRecord:
        """Grant a role to a principal at a scope that is known to exist.

        ``compile_binding`` raises a ``RoleError`` for an unknown role, a
        principal kind the role does not admit, or a scope level the role
        cannot bind at. An identical existing binding is refused with
        ``BindingExists``.

        Args:
            principal: The ``kind:subject`` identifier the role is granted
                to: ``user:...``, ``group:...`` or ``sa:...``.
            role_code: A role code from :mod:`huron.core.security.roles`.
            scope_type: The level the role applies at.
            scope_id: The organization, project or dataset id, or ``None``
                for ``SYSTEM`` scope.
            expires_at: When the grant lapses, or ``None`` for no expiry.

        Returns:
            The stored binding, with its generated id and timestamp.
        """
        await self._access.require("rbac.binding_manage", scope_type, scope_id)
        await require_scope_exists(self._hierarchy, scope_type, scope_id)
        created_by = self._access.actor.subject
        return await self._store.grant_role(
            principal=principal,
            role_code=role_code,
            scope_type=scope_type,
            scope_id=scope_id,
            created_by=created_by,
            expires_at=expires_at,
        )

    async def revoke_role(self, binding_id: UUID) -> RoleBindingRecord:
        """Revoke one role binding after confirming it is the caller's to administer.

        Membership is verified before revocation: the binding is read
        first, and the required capability is checked at *its own* scope,
        not the caller's intended one.

        Args:
            binding_id: Persisted role-binding identifier.

        Returns:
            The binding as it was before removal.
        """
        record = await self._store.get_role_binding(binding_id)
        await self._access.require(
            "rbac.binding_manage", ScopeType(record.scope_type), record.scope_id
        )
        return await self._store.revoke_role(binding_id)

    async def get_role_binding(self, binding_id: UUID) -> RoleBindingRecord:
        """Return one role binding, after confirming the caller may administer its scope.

        Args:
            binding_id: Persisted role-binding identifier.

        Returns:
            The stored binding.
        """
        record = await self._store.get_role_binding(binding_id)
        await self._access.require(
            "rbac.binding_manage", ScopeType(record.scope_type), record.scope_id
        )
        return record

    async def bindings_at(
        self, scope_type: ScopeType, scope_id: UUID | None
    ) -> list[RoleBindingRecord]:
        """List every role binding granted at exactly one scope, expired grants included.

        Args:
            scope_type: Target scope level.
            scope_id: Target identifier, absent for system scope.

        Returns:
            The bindings at that scope, ordered by ``(principal, role_code)``.
        """
        await self._access.require("rbac.binding_manage", scope_type, scope_id)
        await require_scope_exists(self._hierarchy, scope_type, scope_id)
        return await self._store.bindings_at(scope_type, scope_id)
