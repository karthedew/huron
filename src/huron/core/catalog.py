"""Actor-bound catalog operations shared by HTTP and in-process callers."""

from __future__ import annotations

from typing import TYPE_CHECKING

from huron.pkg.catalog.layers import Layer
from huron.pkg.rbac import ScopeType

if TYPE_CHECKING:
    from datetime import datetime
    from uuid import UUID

    from huron.pkg.catalog.persistence import IdempotencyClaim, Window
    from huron.pkg.catalog.records import (
        Dataset,
        Organization,
        Policy,
        PolicyAttachment,
        Project,
        Release,
        RoleBindingRecord,
        ServiceAccount,
    )

    from ._catalog import HierarchyRepository


from huron.pkg.catalog.layers import LAYER_ORDER, LAYER_SPECS
from huron.pkg.rbac import Decision, decide

from .access import AccessPolicy, as_rbac_principal, bindings_for_principal


class CatalogService:
    """Authorize catalog operations against current bindings before invoking domain workflows."""

    def __init__(self, operations: HierarchyRepository, access: AccessPolicy) -> None:
        """Bind catalog workflows to one authenticated actor.

        Args:
            operations: The internal catalog implementation.
            access: The caller's authorization policy.
        """
        self._operations = operations
        self._access = access

    async def create_organization(
        self, *, slug: str, title: str, description: str, claim: IdempotencyClaim
    ) -> Organization:
        """Authorize and execute create organization.

        A claim belonging to another actor raises ``Forbidden``.

        Args:
            slug: Stable URL and storage slug.
            title: Descriptive title.
            description: Free-text description.
            claim: Retry identity and request fingerprint.

        Returns:
            The operation result after authorization.
        """
        await self._access.require("organization.create", ScopeType.SYSTEM)
        self._access.require_claim(claim)
        return await self._operations.create_organization(
            slug=slug, title=title, description=description, claim=claim
        )

    async def patch_organization(
        self,
        organization_id: UUID,
        *,
        expected_version: int,
        slug: str | None,
        title: str | None,
        description: str | None,
    ) -> Organization:
        """Authorize and execute patch organization.

        Args:
            organization_id: Authoritative organization identifier.
            expected_version: Version the caller last observed.
            slug: Stable URL and storage slug.
            title: Descriptive title.
            description: Free-text description.

        Returns:
            The operation result after authorization.
        """
        await self._access.require("organization.update", ScopeType.ORGANIZATION, organization_id)
        return await self._operations.patch_organization(
            organization_id,
            await self._access.visibility(),
            expected_version=expected_version,
            slug=slug,
            title=title,
            description=description,
        )

    async def create_project(
        self,
        organization_id: UUID,
        *,
        slug: str,
        title: str,
        description: str,
        data_classification: str,
        claim: IdempotencyClaim,
    ) -> Project:
        """Authorize and execute create project.

        A claim belonging to another actor raises ``Forbidden``.

        Args:
            organization_id: Authoritative organization identifier.
            slug: Stable URL and storage slug.
            title: Descriptive title.
            description: Free-text description.
            data_classification: Configured project classification code.
            claim: Retry identity and request fingerprint.

        Returns:
            The operation result after authorization.
        """
        await self._access.require("project.create", ScopeType.ORGANIZATION, organization_id)
        self._access.require_claim(claim)
        return await self._operations.create_project(
            organization_id,
            await self._access.visibility(),
            slug=slug,
            title=title,
            description=description,
            data_classification=data_classification,
            claim=claim,
        )

    async def patch_project(
        self,
        project_id: UUID,
        *,
        expected_version: int,
        slug: str | None,
        title: str | None,
        description: str | None,
    ) -> Project:
        """Authorize and execute patch project.

        Args:
            project_id: Authoritative project identifier.
            expected_version: Version the caller last observed.
            slug: Stable URL and storage slug.
            title: Descriptive title.
            description: Free-text description.

        Returns:
            The operation result after authorization.
        """
        await self._access.require("project.update", ScopeType.PROJECT, project_id)
        return await self._operations.patch_project(
            project_id,
            await self._access.visibility(),
            expected_version=expected_version,
            slug=slug,
            title=title,
            description=description,
        )

    async def create_dataset(
        self,
        project_id: UUID,
        *,
        slug: str,
        title: str,
        description: str,
        profile_name: str,
        profile_version: str,
        entry_layer: str = Layer.RAW.value,
        claim: IdempotencyClaim,
    ) -> Dataset:
        """Authorize and execute create dataset.

        A claim belonging to another actor raises ``Forbidden``.

        Args:
            project_id: Authoritative project identifier.
            slug: Stable URL and storage slug.
            title: Descriptive title.
            description: Free-text description.
            profile_name: Science profile name.
            profile_version: Science profile version.
            entry_layer: Dataset entry layer.
            claim: Retry identity and request fingerprint.

        Returns:
            The operation result after authorization.
        """
        await self._access.require("dataset.create", ScopeType.PROJECT, project_id)
        self._access.require_claim(claim)
        return await self._operations.create_dataset(
            project_id,
            await self._access.visibility(),
            slug=slug,
            title=title,
            description=description,
            profile_name=profile_name,
            profile_version=profile_version,
            entry_layer=entry_layer,
            claim=claim,
        )

    async def patch_dataset(
        self,
        dataset_id: UUID,
        *,
        expected_version: int,
        slug: str | None,
        title: str | None,
        description: str | None,
    ) -> Dataset:
        """Authorize and execute patch dataset.

        Args:
            dataset_id: Authoritative dataset identifier.
            expected_version: Version the caller last observed.
            slug: Stable URL and storage slug.
            title: Descriptive title.
            description: Free-text description.

        Returns:
            The operation result after authorization.
        """
        await self._access.require("dataset.update", ScopeType.DATASET, dataset_id)
        return await self._operations.patch_dataset(
            dataset_id,
            await self._access.visibility(),
            expected_version=expected_version,
            slug=slug,
            title=title,
            description=description,
        )

    async def create_release(
        self,
        dataset_id: UUID,
        *,
        tag: str,
        revision_number: int,
        title: str | None,
        created_by: str,
        claim: IdempotencyClaim,
    ) -> Release:
        """Authorize and execute create release.

        A claim belonging to another actor raises ``Forbidden``.

        Args:
            dataset_id: Authoritative dataset identifier.
            tag: Immutable release tag.
            revision_number: Exact committed revision number.
            title: Descriptive title.
            created_by: Caller label; provenance uses the authenticated actor.
            claim: Retry identity and request fingerprint.

        Returns:
            The operation result after authorization.
        """
        await self._access.require("release.create", ScopeType.DATASET, dataset_id)
        self._access.require_claim(claim)
        created_by = self._access.actor.subject
        return await self._operations.create_release(
            dataset_id,
            await self._access.visibility(),
            tag=tag,
            revision_number=revision_number,
            title=title,
            created_by=created_by,
            claim=claim,
        )

    async def organization(self, organization_id: UUID) -> Organization:
        """Authorize and execute organization.

        Args:
            organization_id: Authoritative organization identifier.

        Returns:
            The operation result after authorization.
        """
        return await self._operations.organization(organization_id, await self._access.visibility())

    async def project(self, project_id: UUID) -> Project:
        """Authorize and execute project.

        Args:
            project_id: Authoritative project identifier.

        Returns:
            The operation result after authorization.
        """
        return await self._operations.project(project_id, await self._access.visibility())

    async def dataset(self, dataset_id: UUID) -> Dataset:
        """Authorize and execute dataset.

        Args:
            dataset_id: Authoritative dataset identifier.

        Returns:
            The operation result after authorization.
        """
        return await self._operations.dataset(dataset_id, await self._access.visibility())

    async def release(self, dataset_id: UUID, tag: str) -> Release:
        """Authorize and execute release.

        Args:
            dataset_id: Authoritative dataset identifier.
            tag: Immutable release tag.

        Returns:
            The operation result after authorization.
        """
        return await self._operations.release(dataset_id, tag, await self._access.visibility())

    async def organizations(
        self, *, limit: int, after: tuple[str, UUID] | None
    ) -> Window[Organization]:
        """Authorize and execute organizations.

        Args:
            limit: Maximum number of records.
            after: Exclusive pagination cursor.

        Returns:
            The operation result after authorization.
        """
        return await self._operations.organizations(
            await self._access.visibility(), limit=limit, after=after
        )

    async def projects(
        self, organization_id: UUID, *, limit: int, after: tuple[str, UUID] | None
    ) -> Window[Project]:
        """Authorize and execute projects.

        Args:
            organization_id: Authoritative organization identifier.
            limit: Maximum number of records.
            after: Exclusive pagination cursor.

        Returns:
            The operation result after authorization.
        """
        return await self._operations.projects(
            organization_id, await self._access.visibility(), limit=limit, after=after
        )

    async def datasets(
        self, project_id: UUID, *, limit: int, after: tuple[str, UUID] | None
    ) -> Window[Dataset]:
        """Authorize and execute datasets.

        Args:
            project_id: Authoritative project identifier.
            limit: Maximum number of records.
            after: Exclusive pagination cursor.

        Returns:
            The operation result after authorization.
        """
        return await self._operations.datasets(
            project_id, await self._access.visibility(), limit=limit, after=after
        )

    async def releases(
        self, dataset_id: UUID, *, limit: int, after: tuple[str] | None
    ) -> Window[Release]:
        """Authorize and execute releases.

        Args:
            dataset_id: Authoritative dataset identifier.
            limit: Maximum number of records.
            after: Exclusive pagination cursor.

        Returns:
            The operation result after authorization.
        """
        return await self._operations.releases(
            dataset_id, await self._access.visibility(), limit=limit, after=after
        )

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
        dataset = await self.dataset(dataset_id)
        scope = await self._access.scope(ScopeType.DATASET, dataset_id)
        actor = as_rbac_principal(self._access.actor)
        bindings = await bindings_for_principal({}, self._operations, actor)
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
