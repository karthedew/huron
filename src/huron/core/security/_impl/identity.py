"""Authorized identity provisioning and credential lifecycle operations."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from huron.core.foundation.errors import Forbidden, ResourceNotFound
from huron.core.security.apikeys import create_api_key
from huron.core.security.errors import PrincipalKindMismatch
from huron.core.security.rules import ScopeType

if TYPE_CHECKING:
    from uuid import UUID

    from huron.core.security.apikeys import ApiKeyRecord
    from huron.core.security.ports import ApiKeyWriter
    from huron.core.security.principals import PrincipalRecord, PrincipalStore
    from huron.core.security.types import ServiceAccount

    from .access import AccessPolicy
    from .service_accounts import ServiceAccounts


class IdentityService:
    """Manage identities using the actor's authority and injected credential stores."""

    def __init__(
        self,
        access: AccessPolicy,
        principals: PrincipalStore,
        api_keys: ApiKeyWriter,
        service_accounts: ServiceAccounts,
    ) -> None:
        """Compose identity capabilities for one actor.

        Args:
            access: The caller's authorization policy.
            principals: Durable identities.
            api_keys: Programmatic credential storage.
            service_accounts: Authorized service-account administration.
        """
        self._access = access
        self._principals = principals
        self._api_keys = api_keys
        self._service_accounts = service_accounts

    async def _user(self, principal_id: UUID) -> PrincipalRecord:
        """Require user-management authority and resolve a human identity.

        Args:
            principal_id: The identity to resolve.

        Returns:
            The user record.

        Raises:
            ResourceNotFound: If no identity exists.
            PrincipalKindMismatch: If the identity is not human.
        """
        await self._access.require("user.manage", ScopeType.SYSTEM)
        principal = await self._principals.get_by_id(principal_id)
        if principal is None:
            raise ResourceNotFound(f"principal does not exist: {principal_id}")
        if principal.kind != "user":
            raise PrincipalKindMismatch(f"principal is not a user: {principal_id}")
        return principal

    async def disable_user(self, principal_id: UUID) -> PrincipalRecord:
        """Disable a user and revoke their programmatic credentials.

        Args:
            principal_id: The user to disable.

        Returns:
            The disabled identity.

        Raises:
            ResourceNotFound: If the identity disappeared before the update.
        """
        await self._user(principal_id)
        now = datetime.now(UTC)
        updated = await self._principals.disable(principal_id, disabled_at=now)
        if updated is None:
            raise ResourceNotFound(f"principal does not exist: {principal_id}")
        await self._revoke(updated.subject, now)
        return updated

    async def _revoke(self, subject: str, now: datetime) -> None:
        """Revoke all currently issued credentials for one subject.

        Args:
            subject: The identity losing access.
            now: The revocation instant.
        """
        await self._api_keys.revoke_all_for(subject, now)

    async def issue_key(
        self,
        *,
        name: str,
        scopes: frozenset[str],
        project_id: str | None,
        ttl: timedelta,
    ) -> tuple[ApiKeyRecord, str]:
        """Issue a programmatic credential for the authenticated actor only.

        Args:
            name: A label for the key.
            scopes: The requested credential scopes.
            project_id: An optional project restriction.
            ttl: The credential lifetime.

        Returns:
            The stored key record and its one-time cleartext token.
        """
        actor = self._access.actor
        record, token = create_api_key(
            actor.subject,
            name=name,
            scopes=scopes,
            project_id=project_id,
            ttl=ttl,
            owner_kind=actor.kind,
        )
        await self._api_keys.add(record)
        return record, token

    async def _account(self, organization_id: UUID, principal_id: UUID) -> ServiceAccount:
        """Resolve an account within its authorized organization.

        Args:
            organization_id: The addressed organization.
            principal_id: The service-account identity.

        Returns:
            The authoritative account.

        Raises:
            ResourceNotFound: If the account belongs to another organization.
        """
        await self._access.require(
            "service_account.manage", ScopeType.ORGANIZATION, organization_id
        )
        account = await self._service_accounts.get_service_account(principal_id)
        if account.organization_id != organization_id:
            raise ResourceNotFound("service account belongs to a different organization")
        return account

    async def issue_service_account_key(
        self,
        organization_id: UUID,
        principal_id: UUID,
        *,
        name: str,
        scopes: frozenset[str],
        ttl: timedelta,
    ) -> tuple[ApiKeyRecord, str]:
        """Issue a credential under the account's owning organization's authority.

        Args:
            organization_id: The organization administering the account.
            principal_id: The service-account identity.
            name: The key label.
            scopes: The requested credential scopes.
            ttl: The credential lifetime.

        Returns:
            The persisted credential and its one-time token.

        Raises:
            Forbidden: If the account is disabled.
        """
        account = await self._account(organization_id, principal_id)
        if account.disabled_at is not None:
            raise Forbidden("service account is disabled")
        record, token = create_api_key(
            account.subject,
            name=name,
            scopes=scopes,
            ttl=ttl,
            owner_kind="service_account",
        )
        await self._api_keys.add(record)
        return record, token

    async def disable_service_account(
        self, organization_id: UUID, principal_id: UUID
    ) -> ServiceAccount:
        """Disable an account and revoke its programmatic credentials.

        Args:
            organization_id: The organization administering the account.
            principal_id: The service-account identity.

        Returns:
            The disabled account.
        """
        await self._account(organization_id, principal_id)
        now = datetime.now(UTC)
        account = await self._service_accounts.disable_service_account(
            principal_id, disabled_at=now
        )
        if account.disabled_at is not None and account.disabled_at < now:
            return account
        await self._api_keys.revoke_all_for(account.subject, now)
        return account
