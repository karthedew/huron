"""Durable identity mapping from an external catalog to Huron's Raw hierarchy."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal, Protocol

from huron.core.foundation.canonical import content_identity
from huron.core.foundation.retry import IdempotencyClaim, request_sha256

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable
    from uuid import UUID

    from huron.core.catalog import CatalogCreation
    from huron.core.catalog.types import Dataset, Organization, Project
    from huron.core.security.raw_delegation import DelegationTarget, RawDelegation

PROVISIONER_SUBJECT = "huron-raw-web-provisioner"


@dataclass(frozen=True, slots=True)
class ExternalDataset:
    """A committed mapping; upstream names never become filesystem paths."""

    target: DelegationTarget
    dataset_id: UUID


class ExternalDatasetStore(Protocol):
    """Immutable external-target mappings with uniqueness on both identities."""

    async def provisioned_identity(
        self,
        kind: Literal["organization", "project", "dataset"],
        slug: str,
        parent_id: UUID | None,
    ) -> UUID | None:
        """Recover a deterministic infrastructure identity after its retry receipt expires.

        Args:
            kind: Internal hierarchy level.
            slug: Collision-resistant slug derived from the complete upstream target.
            parent_id: Exact parent identity, absent only for organizations.

        Returns:
            The existing identity, or None before provisioning.
        """
        ...

    async def by_target(self, target: DelegationTarget) -> ExternalDataset | None:
        """Look up an upstream target.

        Args:
            target: Exact authorized upstream identity.

        Returns:
            Its persisted mapping, or None.
        """
        ...

    async def by_dataset(self, dataset_id: UUID) -> ExternalDataset:
        """Resolve an opaque backend identity.

        Args:
            dataset_id: Persisted backend identity.

        Returns:
            Its mapping, or raises ResourceNotFound.
        """
        ...

    async def remember(self, mapping: ExternalDataset) -> ExternalDataset:
        """Persist a mapping without replacing either identity.

        Args:
            mapping: Mapping created by trusted provisioning.

        Returns:
            The stored mapping, including an identical concurrent insertion.
        """
        ...


def target_key(target: DelegationTarget) -> str:
    """Derive a collision-resistant key for the complete external identity.

    Args:
        target: Exact upstream identity.

    Returns:
        SHA-256 over its canonical JSON representation.
    """
    return content_identity(target.model_dump(mode="json"))


def _claim(kind: str, key: str) -> IdempotencyClaim:
    """Name an infrastructure creation consistently across actors and process restarts.

    Args:
        kind: The hierarchy level being created.
        key: Canonical upstream identity digest at that level.

    Returns:
        A stable claim belonging to the explicit provisioning authority.
    """
    return IdempotencyClaim(
        principal=PROVISIONER_SUBJECT,
        key=f"raw-web/{kind}/{key}",
        request_sha256=request_sha256("raw-web", kind, key),
    )


class ExternalCatalog:
    """Provision only explicitly delegated targets through existing catalog operations."""

    def __init__(self, store: ExternalDatasetStore, provisioner: CatalogCreation) -> None:
        """Inject durable mappings and trusted hierarchy provisioning authority.

        Args:
            store: Immutable target-to-dataset mappings.
            provisioner: Explicit deployment authority for internal hierarchy creation.
        """
        self._store = store
        self._provisioner = provisioner

    async def resolve(self, delegation: RawDelegation, dataset_id: UUID) -> ExternalDataset:
        """Match the persisted identity before a delegated operation reaches its dataset.

        Args:
            delegation: Verified upstream scope.
            dataset_id: The opaque dataset requested or resolved from a session/revision.

        Returns:
            Its matching mapping.

        """
        mapping = await self._store.by_dataset(dataset_id)
        delegation.require_scope(target=mapping.target)
        return mapping

    async def ensure(self, delegation: RawDelegation) -> ExternalDataset:
        """Resolve a writable target, requiring explicit create authority if absent.

        Stable claims make crashes between hierarchy creation and mapping insertion
        recoverable without minting a second hierarchy or broadening actor authority.

        Args:
            delegation: Verified actor and exact upstream target.

        Returns:
            The persisted dataset mapping.
        """
        delegation.require("write")
        existing = await self._store.by_target(delegation.target)
        if existing is not None:
            return existing
        delegation.require("create")
        target = delegation.target
        catalog_key = target_key(target.model_copy(update={"namespace": (), "name": ""}))
        project_key = target_key(target.model_copy(update={"name": ""}))
        dataset_key = target_key(target)
        organization_slug = f"pc-{catalog_key[:48]}"
        organization_id = await self._recover(
            "organization",
            organization_slug,
            None,
            lambda: self._provisioner.create_organization(
                slug=organization_slug,
                title=target.catalog,
                description="Polaris Raw storage",
                claim=_claim("organization", catalog_key),
            ),
        )
        project_slug = f"ns-{project_key[:48]}"
        project_id = await self._recover(
            "project",
            project_slug,
            organization_id,
            lambda: self._provisioner.create_project(
                organization_id,
                slug=project_slug,
                title=" / ".join(target.namespace) or target.catalog,
                description="Polaris namespace Raw storage",
                data_classification="raw-web",
                claim=_claim("project", project_key),
            ),
        )
        dataset_slug = f"ds-{dataset_key[:48]}"
        dataset_id = await self._recover(
            "dataset",
            dataset_slug,
            project_id,
            lambda: self._provisioner.create_dataset(
                project_id,
                slug=dataset_slug,
                title=target.name,
                description="Managed Raw dataset registered in Polaris",
                profile_name="raw",
                profile_version="1",
                claim=_claim("dataset", dataset_key),
            ),
        )
        return await self._store.remember(ExternalDataset(target, dataset_id))

    async def _recover(
        self,
        kind: Literal["organization", "project", "dataset"],
        slug: str,
        parent_id: UUID | None,
        create: Callable[[], Awaitable[Organization | Project | Dataset]],
    ) -> UUID:
        """Recover persisted infrastructure before attempting a retryable creation.

        Args:
            kind: The hierarchy level being provisioned.
            slug: Its deterministic target-derived identity.
            parent_id: Its exact parent, absent for organizations.
            create: Authorized creation used only when the identity is absent.

        Returns:
            The original identity, even after creation retry receipts expire.
        """
        existing = await self._store.provisioned_identity(kind, slug, parent_id)
        return existing if existing is not None else (await create()).id
