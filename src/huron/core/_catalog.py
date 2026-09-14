"""Internal governance coordination and Raw storage initialization.

Governance operations validate their scope and delegate to RBAC storage.
Catalog identity creation, descriptive updates and immutable releases have
their own authorized workflow modules and use the hierarchy adapter directly.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from huron.pkg.catalog.paths import validate_slug
from huron.pkg.rbac import ScopeType, Visibility

if TYPE_CHECKING:
    from datetime import datetime
    from uuid import UUID

    from huron.pkg.catalog.ports import RawStore
    from huron.pkg.catalog.records import (
        Policy,
        PolicyAttachment,
        RoleBindingRecord,
        ServiceAccount,
    )

    from .ports import HierarchyStore, RbacStore


class HierarchyRepository:
    """Remaining governance operations plus Raw storage initialization.

    Roles, service accounts and policies use the injected RBAC adapter.
    Governance scope validation uses committed hierarchy readers.
    Actor-bound workflows enforce authority before invoking these internal
    operations.

    Attributes:
        raw_store: Initialized storage for durable documents.
        hierarchy: The committed hierarchy and transaction adapter.
        rbac: Role, policy and service-account persistence.
    """

    def __init__(
        self,
        raw_store: RawStore,
        hierarchy: HierarchyStore,
        *,
        rbac_store: RbacStore,
    ):
        """Wire the repository over its raw store, hierarchy store and RBAC storage port.

        Construction initializes the raw store's directory layout, so the
        data root must be writable and its staging and ``organization``
        directories must sit on one filesystem.

        Args:
            raw_store: The store that holds every durable generation
                and release-tag document; it is initialized here.
            hierarchy: Durable storage for the organization/project/dataset/
                release hierarchy and its idempotency claims.
            rbac_store: Storage for role bindings, service accounts and
                policies.
        """
        self.raw_store = raw_store
        self.raw_store.initialize()
        self.hierarchy = hierarchy
        self.rbac = rbac_store

    # -- RBAC ------------------------------------------------------------
    # Every method below delegates to ``self.rbac``; the only logic
    # kept here is what depends on the hierarchy the RBAC store deliberately
    # knows nothing about (existence checks, and the service-account
    # subject derived from the org slug).

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
        """Grant a role to a principal at a scope that is known to exist.

        The scope pair is checked first: ``_require_scope`` raises
        ``ValueError`` for an inconsistent pair (a caller bug) and
        ``ResourceNotFound`` when the organization, project or dataset does
        not exist, so a binding can never point at nothing. Everything else
        is the store's: it validates the grant against the role model
        (``compile_binding`` raises a ``RoleError`` for an unknown role, a
        principal kind the role does not admit, or a scope level the role
        cannot bind at) and refuses an identical existing binding with
        ``BindingExists``.

        Args:
            principal: The ``kind:subject`` identifier the role is granted
                to: ``user:...``, ``group:...`` or ``sa:...``.
            role_code: A role code from :mod:`huron.pkg.rbac.roles`.
            scope_type: The level the role applies at.
            scope_id: The organization, project or dataset id, or ``None``
                for ``SYSTEM`` scope.
            created_by: The subject of the principal making the grant.
            expires_at: When the grant lapses, or ``None`` for no expiry.

        Returns:
            The stored binding, with its generated id and timestamp.
        """
        await self._require_scope(scope_type, scope_id)
        return await self.rbac.grant_role(
            principal=principal,
            role_code=role_code,
            scope_type=scope_type,
            scope_id=scope_id,
            created_by=created_by,
            expires_at=expires_at,
        )

    async def revoke_role(self, binding_id: UUID) -> RoleBindingRecord:
        """Delete one role binding and return what was removed.

        The store raises ``ResourceNotFound`` when no such binding exists, so
        revoking twice is refused rather than silently succeeding.

        Args:
            binding_id: The binding's id.

        Returns:
            The binding as it was before removal.
        """
        return await self.rbac.revoke_role(binding_id)

    async def get_role_binding(self, binding_id: UUID) -> RoleBindingRecord:
        """Return one role binding by id.

        The store raises ``ResourceNotFound`` when no such binding exists.

        Args:
            binding_id: The binding's id.

        Returns:
            The stored binding.
        """
        return await self.rbac.get_role_binding(binding_id)

    async def bindings_at(
        self, scope_type: ScopeType, scope_id: UUID | None
    ) -> list[RoleBindingRecord]:
        """Return the role bindings granted at exactly one scope.

        Only bindings stored at this scope are returned; inheritance from
        enclosing scopes is ``decide()``'s concern, not a listing's. The
        scope's existence is checked first, through ``_require_scope``, so
        an unknown ``scope_id`` is ``ResourceNotFound`` rather than an
        empty list.

        Args:
            scope_type: The level to list.
            scope_id: The organization, project or dataset id, or ``None``
                for ``SYSTEM`` scope.

        Returns:
            The bindings at that scope, ordered by ``(principal, role_code)``.
        """
        await self._require_scope(scope_type, scope_id)
        return await self.rbac.bindings_at(scope_type, scope_id)

    async def create_service_account(
        self, organization_id: UUID, *, name: str, created_by: str
    ) -> ServiceAccount:
        """Create a service account whose subject derives from the organization slug.

        ``name`` is validated as a slug with the organization/project length
        limit (``validate_slug`` raises ``PathRuleViolation`` otherwise) and
        the organization must exist, read with unrestricted visibility since
        this is RBAC provisioning rather than a discovery decision - the
        granting principal's own visibility is already checked by the
        ``require_*`` guard before the handler runs. The account's subject
        is ``{organization slug}/{name}``: that is what its API keys
        authenticate as, and it is stable for the account's lifetime because
        organization slugs are immutable. The store refuses a second account
        with the same name in the same organization with
        ``ServiceAccountExists``.

        Args:
            organization_id: The owning organization.
            name: The account's name, unique within the organization; 2 to
                62 characters of lowercase letters, digits and hyphens, with
                no doubled hyphen.
            created_by: The subject of the principal creating the account.

        Returns:
            The stored account, with its generated principal id and subject.
            ``organization_id`` not naming an organization surfaces here as
            the ``ResourceNotFound`` the read raises.
        """
        validate_slug(name, 62)
        organization = await self.hierarchy.organizations.get(organization_id, Visibility.ALL)
        subject = f"{organization.slug}/{name}"
        return await self.rbac.create_service_account(
            organization_id, name=name, subject=subject, created_by=created_by
        )

    async def get_service_account(self, principal_id: UUID) -> ServiceAccount:
        """Return one service account by its principal id.

        The store raises ``ResourceNotFound`` when no such account exists.

        Args:
            principal_id: The account's principal id.

        Returns:
            The stored account, disabled or not.
        """
        return await self.rbac.get_service_account(principal_id)

    async def list_service_accounts(self, organization_id: UUID) -> list[ServiceAccount]:
        """Return every service account of one organization, ordered by name.

        The organization's existence is checked first, through
        ``_require_scope``, so an unknown organization is
        ``ResourceNotFound`` rather than an empty list.

        Args:
            organization_id: The organization whose accounts to list.

        Returns:
            The organization's accounts, sorted by name.
        """
        await self._require_scope(ScopeType.ORGANIZATION, organization_id)
        return await self.rbac.list_service_accounts(organization_id)

    async def disable_service_account(
        self, principal_id: UUID, *, disabled_at: datetime
    ) -> ServiceAccount:
        """Mark a service account disabled as of a moment.

        Disabling is recorded, not deleted: the account stays resolvable by
        id and by subject with ``disabled_at`` set, and a disabled account
        resolves to no bindings. Disabling is idempotent: an
        already-disabled account keeps its original ``disabled_at`` and
        ``disabled_at`` is discarded. Revoking the account's existing API
        keys is the caller's job, not this method's. The store raises
        ``ResourceNotFound`` when no such account exists.

        Args:
            principal_id: The account's principal id.
            disabled_at: The instant recorded as the disabling time, if the
                account is not already disabled.

        Returns:
            The account with ``disabled_at`` set - to this call's instant on
            a first disable, or to the original instant if it was already
            disabled.
        """
        return await self.rbac.disable_service_account(principal_id, disabled_at=disabled_at)

    async def create_policy(
        self, *, policy_type: str, name: str, spec: dict[str, object], created_by: str
    ) -> Policy:
        """Store a policy definition.

        Nothing here inspects ``spec`` or checks ``name`` for uniqueness - a
        policy is identified by the id the store generates, and several
        policies may share a name.

        Args:
            policy_type: The kind of policy ``spec`` describes.
            name: A human-readable label; not required to be unique.
            spec: The policy body, stored as given.
            created_by: The subject of the principal creating the policy.

        Returns:
            The stored policy, with its generated id and timestamp.
        """
        return await self.rbac.create_policy(
            policy_type=policy_type, name=name, spec=spec, created_by=created_by
        )

    async def attach_policy(
        self, policy_id: UUID, *, scope_type: ScopeType, scope_id: UUID, attached_by: str
    ) -> PolicyAttachment:
        """Attach a policy at a scope that is known to exist.

        The scope pair is checked first: ``_require_scope`` raises
        ``ValueError`` for an inconsistent pair and ``ResourceNotFound`` when
        the organization, project or dataset does not exist. ``scope_id`` is
        required, so a policy cannot be attached at ``SYSTEM`` scope. The
        store raises ``ResourceNotFound`` when the policy does not exist and
        ``AttachmentExists`` when it is already attached at that scope.

        Args:
            policy_id: The policy to attach.
            scope_type: The level the policy applies at; never ``SYSTEM``.
            scope_id: The organization, project or dataset id.
            attached_by: The subject of the principal attaching the policy.

        Returns:
            The stored attachment, with its timestamp.
        """
        await self._require_scope(scope_type, scope_id)
        return await self.rbac.attach_policy(
            policy_id, scope_type=scope_type, scope_id=scope_id, attached_by=attached_by
        )

    async def list_policies(self) -> list[Policy]:
        """Return every policy, ordered by ``(name, id)``.

        The order is the key the listing route pages by; ``id`` breaks ties
        because names are not unique.

        Returns:
            All policies, sorted by name and then id.
        """
        return await self.rbac.list_policies()

    async def _require_scope(self, scope_type: ScopeType, scope_id: UUID | None) -> None:
        """Reject an internally inconsistent scope/id pair.

        No request can produce one of these - each binding route passes
        the pair its own path supplies, and the SYSTEM route passes ``None``
        literally - so this is a caller bug, not a client contract, and its
        honest answer is the 500 the unhandled-exception path produces.

        A consistent pair is then checked for existence, with unrestricted
        visibility: the organization, project or dataset ``scope_id`` names
        must be known, and the matching read raises ``ResourceNotFound``
        when it is not. That one is a client contract - a grant or
        attachment cannot point at nothing - and it is independent of the
        granting principal's own visibility, which the ``require_*`` guard
        already checked before the handler ran. ``SYSTEM`` scope has
        nothing to look up.

        Args:
            scope_type: The level a grant or attachment applies at.
            scope_id: The organization, project or dataset id, or ``None``
                for ``SYSTEM`` scope.

        Raises:
            ValueError: If ``SYSTEM`` comes with an id, or any other level
                comes without one.
        """
        if scope_type is ScopeType.SYSTEM:
            if scope_id is not None:
                raise ValueError("SYSTEM scope takes no scope_id")
            return
        if scope_id is None:
            raise ValueError(f"{scope_type.value} scope requires a scope_id")
        if scope_type is ScopeType.ORGANIZATION:
            await self.hierarchy.organizations.get(scope_id, Visibility.ALL)
        elif scope_type is ScopeType.PROJECT:
            await self.hierarchy.projects.get(scope_id, Visibility.ALL)
        else:
            await self.hierarchy.datasets.get(scope_id, Visibility.ALL)
