"""Consumer-owned governance and credential-administration persistence."""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

from .apikeys import ApiKeyStore
from .facts import BindingFacts

if TYPE_CHECKING:
    from datetime import datetime
    from uuid import UUID

    from .apikeys import ApiKeyRecord
    from .rules import ScopeType
    from .types import Policy, PolicyAttachment, RoleBindingRecord, ServiceAccount


class BindingStore(Protocol):
    """Role-model validated grant persistence; Security verifies target existence."""

    async def grant_role(
        self,
        *,
        principal: str,
        role_code: str,
        scope_type: ScopeType,
        scope_id: UUID | None,
        created_by: str,
        expires_at: datetime | None = None,
    ) -> RoleBindingRecord:
        """Validate and insert a unique principal/role/scope grant.

        Args:
            principal: User or group identifier; service accounts cannot hold roles.
            role_code: Registered role code.
            scope_type: Bindable scope level.
            scope_id: Target identity, absent only for SYSTEM.
            created_by: Authoritative actor attribution.
            expires_at: Optional expiry.

        Returns:
            The stored grant; a duplicate raises BindingExists.
        """
        ...

    async def revoke_role(self, binding_id: UUID) -> RoleBindingRecord:
        """Hard-delete a grant; repeated revocation raises ResourceNotFound.

        Args:
            binding_id: Grant identity.

        Returns:
            The record before deletion.
        """
        ...

    async def get_role_binding(self, binding_id: UUID) -> RoleBindingRecord:
        """Read one grant including expired grants.

        Args:
            binding_id: Grant identity.

        Returns:
            The stored grant or raises ResourceNotFound.
        """
        ...

    async def bindings_at(
        self, scope_type: ScopeType, scope_id: UUID | None
    ) -> list[RoleBindingRecord]:
        """Read grants at exactly one scope, without inherited grants.

        Args:
            scope_type: Scope level.
            scope_id: Target identity or None for SYSTEM.

        Returns:
            Grants, including expired ones, in principal/role byte order.
        """
        ...


class PolicyStore(Protocol):
    """Policy definitions and unique scope attachments."""

    async def create_policy(
        self, *, policy_type: str, name: str, spec: dict[str, object], created_by: str
    ) -> Policy:
        """Store a policy without imposing name uniqueness.

        Args:
            policy_type: Consumer-interpreted policy kind.
            name: Descriptive label.
            spec: JSON body stored verbatim.
            created_by: Authoritative actor attribution.

        Returns:
            The stored policy.
        """
        ...

    async def attach_policy(
        self, policy_id: UUID, *, scope_type: ScopeType, scope_id: UUID, attached_by: str
    ) -> PolicyAttachment:
        """Attach an existing policy once at one non-system scope.

        Args:
            policy_id: Existing policy identity.
            scope_type: Organization, project or dataset.
            scope_id: Existing target identity, checked by Security.
            attached_by: Authoritative actor attribution.

        Returns:
            The attachment; duplicates raise AttachmentExists.
        """
        ...

    async def list_policies(self) -> list[Policy]:
        """Read every definition in name/id byte order.

        Returns:
            The ordered policy definitions.
        """
        ...


class ServiceAccountStore(Protocol):
    """Organization-owned roleless accounts with reserved disabled identities."""

    async def create_service_account(
        self, organization_id: UUID, *, name: str, subject: str, created_by: str
    ) -> ServiceAccount:
        """Insert an enabled account with organization-local name and global subject uniqueness.

        Args:
            organization_id: Existing owning organization.
            name: Organization-local name.
            subject: Stable subject derived by Security.
            created_by: Authoritative actor attribution.

        Returns:
            The stored enabled account.
        """
        ...

    async def get_service_account(self, principal_id: UUID) -> ServiceAccount:
        """Read an account including its disablement state.

        Args:
            principal_id: Account identity.

        Returns:
            The account or raises ResourceNotFound.
        """
        ...

    async def list_service_accounts(self, organization_id: UUID) -> list[ServiceAccount]:
        """Read all accounts, including disabled ones, in name byte order.

        Args:
            organization_id: Owning organization.

        Returns:
            The ordered accounts; empty for an unknown organization.
        """
        ...

    async def disable_service_account(
        self, principal_id: UUID, *, disabled_at: datetime
    ) -> ServiceAccount:
        """Disable an account idempotently while reserving its identity and name.

        Args:
            principal_id: Account identity.
            disabled_at: Timestamp used only for the first disablement.

        Returns:
            The disabled account, retaining an earlier disablement timestamp.
        """
        ...


class RbacStore(BindingFacts, BindingStore, PolicyStore, ServiceAccountStore, Protocol):
    """The governance capabilities supplied by one adapter for application wiring."""


class ApiKeyWriter(ApiKeyStore, Protocol):
    """Key persistence used by identity administration and credential bookkeeping."""

    async def add(self, record: ApiKeyRecord) -> None:
        """Persist a freshly issued key with its secret already reduced to a digest.

        Args:
            record: Complete issued key record.
        """
        ...

    async def touch_last_used(self, key_id: str) -> None:
        """Record credential usage without affecting its authority.

        Args:
            key_id: Public handle; unknown handles are ignored.
        """
        ...

    async def revoke_all_for(self, subject: str, revoked_at: datetime) -> int:
        """Revoke live keys across owner kinds, retaining prior revocation timestamps.

        Args:
            subject: Owner subject.
            revoked_at: Timestamp for newly revoked keys.

        Returns:
            The number newly revoked.
        """
        ...
