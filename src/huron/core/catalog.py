"""Actor-bound catalog operations shared by HTTP and in-process callers."""

from __future__ import annotations

from typing import TYPE_CHECKING

from huron.pkg.rbac import ScopeType

if TYPE_CHECKING:
    from datetime import datetime
    from uuid import UUID

    from huron.pkg.catalog.records import (
        Policy,
        PolicyAttachment,
        RoleBindingRecord,
        ServiceAccount,
    )

    from ._catalog import HierarchyRepository
    from .catalog_ports import DescriptionStore


from huron.pkg.catalog.layers import LAYER_ORDER, LAYER_SPECS
from huron.pkg.rbac import Decision, decide

from .access import AccessPolicy, as_rbac_principal
from .catalog_collections import DatasetCollection, OrganizationCollection, ProjectCollection


class CatalogService:
    """Authorize catalog operations against current bindings before invoking domain workflows."""

    def __init__(
        self, operations: HierarchyRepository, access: AccessPolicy, readers: DescriptionStore
    ) -> None:
        """Bind catalog workflows to one authenticated actor.

        Args:
            operations: The internal catalog implementation.
            access: The caller's authorization policy.
            readers: Typed committed catalog readers.
        """
        self._operations = operations
        self._access = access
        self.organizations = OrganizationCollection(access, readers, operations.raw_store)
        self.projects = ProjectCollection(access, readers, operations.raw_store)
        self.datasets = DatasetCollection(access, readers, operations.raw_store)

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
        """Authorize and execute grant role.

        Args:
            principal: Identity receiving the role.
            role_code: Registered role code.
            scope_type: Target scope level.
            scope_id: Target identifier, absent for system scope.
            created_by: Caller label; provenance uses the authenticated actor.
            expires_at: Optional role-binding expiration.

        Returns:
            The operation result after authorization.
        """
        await self._access.require("rbac.binding_manage", scope_type, scope_id)
        created_by = self._access.actor.subject
        return await self._operations.grant_role(
            principal=principal,
            role_code=role_code,
            scope_type=scope_type,
            scope_id=scope_id,
            created_by=created_by,
            expires_at=expires_at,
        )

    async def revoke_role(self, binding_id: UUID) -> RoleBindingRecord:
        """Authorize and execute revoke role.

        Args:
            binding_id: Persisted role-binding identifier.

        Returns:
            The operation result after authorization.
        """
        binding = await self._operations.get_role_binding(binding_id)
        await self._access.require(
            "rbac.binding_manage", ScopeType(binding.scope_type), binding.scope_id
        )
        return await self._operations.revoke_role(binding_id)

    async def get_role_binding(self, binding_id: UUID) -> RoleBindingRecord:
        """Authorize and execute get role binding.

        Args:
            binding_id: Persisted role-binding identifier.

        Returns:
            The operation result after authorization.
        """
        binding = await self._operations.get_role_binding(binding_id)
        await self._access.require(
            "rbac.binding_manage", ScopeType(binding.scope_type), binding.scope_id
        )
        return await self._operations.get_role_binding(binding_id)

    async def bindings_at(
        self, scope_type: ScopeType, scope_id: UUID | None
    ) -> list[RoleBindingRecord]:
        """Authorize and execute bindings at.

        Args:
            scope_type: Target scope level.
            scope_id: Target identifier, absent for system scope.

        Returns:
            The operation result after authorization.
        """
        await self._access.require("rbac.binding_manage", scope_type, scope_id)
        return await self._operations.bindings_at(scope_type, scope_id)

    async def create_service_account(
        self, organization_id: UUID, *, name: str, created_by: str
    ) -> ServiceAccount:
        """Authorize and execute create service account.

        Args:
            organization_id: Authoritative organization identifier.
            name: Human-readable name.
            created_by: Caller label; provenance uses the authenticated actor.

        Returns:
            The operation result after authorization.
        """
        await self._access.require(
            "service_account.manage", ScopeType.ORGANIZATION, organization_id
        )
        created_by = self._access.actor.subject
        return await self._operations.create_service_account(
            organization_id, name=name, created_by=created_by
        )

    async def get_service_account(self, principal_id: UUID) -> ServiceAccount:
        """Authorize and execute get service account.

        Args:
            principal_id: Service-account identity.

        Returns:
            The operation result after authorization.
        """
        account = await self._operations.get_service_account(principal_id)
        await self._access.require(
            "service_account.manage", ScopeType.ORGANIZATION, account.organization_id
        )
        return await self._operations.get_service_account(principal_id)

    async def list_service_accounts(self, organization_id: UUID) -> list[ServiceAccount]:
        """Authorize and execute list service accounts.

        Args:
            organization_id: Authoritative organization identifier.

        Returns:
            The operation result after authorization.
        """
        await self._access.require(
            "service_account.manage", ScopeType.ORGANIZATION, organization_id
        )
        return await self._operations.list_service_accounts(organization_id)

    async def disable_service_account(
        self, principal_id: UUID, *, disabled_at: datetime
    ) -> ServiceAccount:
        """Authorize and execute disable service account.

        Args:
            principal_id: Service-account identity.
            disabled_at: Disable instant.

        Returns:
            The operation result after authorization.
        """
        account = await self._operations.get_service_account(principal_id)
        await self._access.require(
            "service_account.manage", ScopeType.ORGANIZATION, account.organization_id
        )
        return await self._operations.disable_service_account(principal_id, disabled_at=disabled_at)

    async def create_policy(
        self, *, policy_type: str, name: str, spec: dict[str, object], created_by: str
    ) -> Policy:
        """Authorize and execute create policy.

        Args:
            policy_type: Registered policy kind.
            name: Human-readable name.
            spec: Policy configuration.
            created_by: Caller label; provenance uses the authenticated actor.

        Returns:
            The operation result after authorization.
        """
        created_by = self._access.actor.subject
        return await self._operations.create_policy(
            policy_type=policy_type, name=name, spec=spec, created_by=created_by
        )

    async def attach_policy(
        self, policy_id: UUID, *, scope_type: ScopeType, scope_id: UUID, attached_by: str
    ) -> PolicyAttachment:
        """Authorize and execute attach policy.

        Args:
            policy_id: Policy identifier.
            scope_type: Target scope level.
            scope_id: Target identifier, absent for system scope.
            attached_by: Caller label; provenance uses the authenticated actor.

        Returns:
            The operation result after authorization.
        """
        await self._access.require(
            f"{scope_type.value.lower()}.policy_attach", scope_type, scope_id
        )
        attached_by = self._access.actor.subject
        return await self._operations.attach_policy(
            policy_id, scope_type=scope_type, scope_id=scope_id, attached_by=attached_by
        )

    async def list_policies(self) -> list[Policy]:
        """Authorize and execute list policies.

        Returns:
            The operation result after authorization.
        """
        return await self._operations.list_policies()

    async def layers(self, dataset_id: UUID) -> list[dict[str, object]]:
        """Describe layer capabilities for the current actor.

        Args:
            dataset_id: The dataset whose layer workflow to describe.

        Returns:
            Layer descriptions with current read and write decisions.
        """
        dataset = await self.datasets.get(dataset_id)
        scope = await self._access.scope(ScopeType.DATASET, dataset_id)
        actor = as_rbac_principal(self._access.actor)
        bindings = await self._access.bindings()
        return [
            {
                "layer": layer,
                "derived_from": list(LAYER_SPECS[layer].derived_from),
                "principal_writable": LAYER_SPECS[layer].principal_writable,
                "accepts_direct_entry": LAYER_SPECS[layer].accepts_direct_entry,
                "is_entry_layer": layer.value == dataset.entry_layer,
                "produced_by": LAYER_SPECS[layer].produced_by,
                "caller_may": {
                    action: decide(bindings, actor, f"data.{action}", scope, layer=layer.value)
                    is Decision.ALLOW
                    for action in ("read", "write")
                },
            }
            for layer in LAYER_ORDER
        ]
