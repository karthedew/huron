"""Authorized service-account administration.

Service accounts are roleless identities owned by one organization: they
never gain human role-binding rules, and their whole authority is
synthesized from their owning organization (see
:func:`huron.core.security.roles.service_account_bindings`), not granted through
:class:`huron.core.security.Bindings`.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from huron.core.foundation.names import validate_slug
from huron.core.security.rules import ScopeType
from huron.core.security.scopes import require_scope_exists

if TYPE_CHECKING:
    from datetime import datetime
    from uuid import UUID

    from huron.core.security.facts import CatalogFacts
    from huron.core.security.ports import ServiceAccountStore
    from huron.core.security.types import ServiceAccount

    from .access import AccessPolicy


class ServiceAccounts:
    """Create, read, list and disable service accounts, with fresh authority on every call.

    Every operation requires ``service_account.manage`` on the account's
    owning organization; disabling is idempotent and does not itself
    revoke keys - :class:`huron.core.security.IdentityService` layers key
    revocation on top, since a service account's credentials are an
    identity concern, not a catalog one.
    """

    def __init__(
        self, access: AccessPolicy, hierarchy: CatalogFacts, store: ServiceAccountStore
    ) -> None:
        """Bind service-account administration to one authenticated actor.

        Args:
            access: The caller's authorization policy.
            hierarchy: Committed catalog readers, used to resolve the owning
                organization's slug at creation.
            store: Service-account persistence.
        """
        self._access = access
        self._hierarchy = hierarchy
        self._store = store

    async def create_service_account(self, organization_id: UUID, *, name: str) -> ServiceAccount:
        """Create a service account whose subject derives from the organization slug.

        ``name`` is validated as a slug with the organization/project length
        limit and the organization must exist, read with unrestricted
        visibility since this is RBAC provisioning rather than a discovery
        decision - the granting principal's own visibility is already
        checked by ``require``. The account's subject is ``{organization
        slug}/{name}``: that is what its API keys authenticate as, and it is
        stable for the account's lifetime because organization slugs are
        immutable. A second account with the same name in the same
        organization is refused with ``ServiceAccountExists``.

        Args:
            organization_id: Authoritative organization identifier.
            name: Human-readable name, unique within the organization; 2 to
                62 characters of lowercase letters, digits and hyphens, with
                no doubled hyphen.

        Returns:
            The stored account, enabled, with its generated principal id and
            subject.
        """
        await self._access.require(
            "service_account.manage", ScopeType.ORGANIZATION, organization_id
        )
        created_by = self._access.actor.subject
        validate_slug(name, 62)
        organization_slug = await self._hierarchy.organization_slug(organization_id)
        subject = f"{organization_slug}/{name}"
        return await self._store.create_service_account(
            organization_id, name=name, subject=subject, created_by=created_by
        )

    async def get_service_account(self, principal_id: UUID) -> ServiceAccount:
        """Return one service account, after confirming the caller may administer its organization.

        Args:
            principal_id: Service-account identity.

        Returns:
            The stored account, disabled or not.
        """
        account = await self._store.get_service_account(principal_id)
        await self._access.require(
            "service_account.manage", ScopeType.ORGANIZATION, account.organization_id
        )
        return account

    async def list_service_accounts(self, organization_id: UUID) -> list[ServiceAccount]:
        """List every service account an organization owns, disabled ones included.

        Args:
            organization_id: Authoritative organization identifier.

        Returns:
            The organization's accounts, sorted by name.
        """
        await self._access.require(
            "service_account.manage", ScopeType.ORGANIZATION, organization_id
        )
        await require_scope_exists(self._hierarchy, ScopeType.ORGANIZATION, organization_id)
        return await self._store.list_service_accounts(organization_id)

    async def disable_service_account(
        self, principal_id: UUID, *, disabled_at: datetime
    ) -> ServiceAccount:
        """Mark a service account disabled, after confirming the caller may administer it.

        Disabling is idempotent: an already-disabled account keeps its
        original ``disabled_at``. Revoking the account's existing API keys
        is the caller's job, not this method's.

        Args:
            principal_id: Service-account identity.
            disabled_at: Disable instant.

        Returns:
            The account with ``disabled_at`` set - to this call's instant on
            a first disable, or to the original instant if it was already
            disabled.
        """
        account = await self._store.get_service_account(principal_id)
        await self._access.require(
            "service_account.manage", ScopeType.ORGANIZATION, account.organization_id
        )
        return await self._store.disable_service_account(principal_id, disabled_at=disabled_at)
