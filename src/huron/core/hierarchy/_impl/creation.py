"""Explicit authorized catalog identity creation and durable idempotent publication."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import PurePosixPath
from typing import TYPE_CHECKING, Literal

from huron.core.foundation.identifiers import uuid7
from huron.core.foundation.names import validate_org_slug, validate_slug
from huron.core.foundation.retry import Replay
from huron.core.hierarchy.errors import ClassificationUnknown
from huron.core.hierarchy.layers import Layer, parse_entry_layer
from huron.core.hierarchy.lifecycle import DatasetLifecycle
from huron.core.hierarchy.paths import (
    dataset_dir,
    organization_dir,
    project_dir,
)
from huron.core.hierarchy.retry import claimed_result
from huron.core.hierarchy.types import Dataset, Organization, Project
from huron.core.security.rules import ScopeType, Visibility

from .documents import GenerationDocuments

if TYPE_CHECKING:
    from uuid import UUID

    from huron.core.foundation.retry import IdempotencyClaim, RetryTransaction
    from huron.core.hierarchy.ports import CreationStore, GenerationStorage
    from huron.core.security import AccessPolicy


class HierarchyCreation:
    """Create authorized catalog identities with transaction-scoped retry claims."""

    def __init__(
        self,
        access: AccessPolicy,
        hierarchy: CreationStore,
        storage: GenerationStorage,
        *,
        classification_vocabulary: tuple[str, ...],
    ) -> None:
        """Bind creation to current actor authority and initialized persistence capabilities.

        Args:
            access: The authenticated actor and current authorization facts.
            hierarchy: Committed readers and atomic creation transactions.
            storage: Initialized generation storage, owned by the application.
            classification_vocabulary: Permitted project classification codes.
        """
        self._access = access
        self._hierarchy = hierarchy
        self._generations = GenerationDocuments(storage)
        self._root = PurePosixPath(storage.root)
        self._classification_vocabulary = frozenset(classification_vocabulary)

    async def create_organization(
        self, *, slug: str, title: str, description: str, claim: IdempotencyClaim
    ) -> Organization:
        """Create an organization and write its first generation document.

        The slug must satisfy the organization slug rules and must not be a
        reserved root slug (``validate_org_slug`` raises ``PathRuleViolation``
        otherwise); it is immutable afterwards because it names the
        organization's storage directory. Creation is idempotent per
        ``claim``: staking an identical claim returns the organization
        created the first time without touching storage, and staking one
        whose key was used for a different request is refused with
        ``IdempotencyKeyReused``. Generation ``1`` is written to the raw
        store after the row is inserted and before the transaction commits.

        Args:
            slug: The URL and path segment identifying the organization; 2 to
                62 characters of lowercase letters, digits and hyphens, with
                no doubled hyphen (the slug/id separator in path components),
                and not one of the reserved root slugs.
            title: The human-readable name.
            description: Free-text description; may be empty.
            claim: The caller's idempotency claim for this request.

        Returns:
            The stored organization, at generation and version ``1``.
        """
        await self._access.require("organization.create", ScopeType.SYSTEM)
        self._access.require_claim(claim)
        validate_org_slug(slug)
        async with self._hierarchy.transaction() as writer:
            replayed = await claimed_result(
                writer,
                claim,
                lambda resource_id: self._hierarchy.organizations.get(resource_id, Visibility.ALL),
            )
            if replayed is not None:
                return replayed
            item = Organization(uuid7(), slug, title, description, 1, 1, datetime.now(UTC))
            await writer.insert_organization(item)
            await self._publish_created(writer, claim, item, organization_dir(self._root, item))
            return item

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
        """Create a project under an organization and write its first generation.

        ``data_classification`` must be one of the codes in the
        classification vocabulary the repository was built with, checked
        before the transaction opens. The slug is validated by
        ``validate_slug`` (which raises ``PathRuleViolation``) and is
        immutable afterwards because it names the project's storage
        directory; it must be unique within the organization only, so two
        organizations may each have a project with the same slug. The
        organization is read with ``visibility``, so an invisible or absent
        organization is ``ResourceNotFound``. Creation is idempotent per
        ``claim``: staking an identical claim returns the original project
        without writing, and staking one whose key was used for a different
        request is refused with ``IdempotencyKeyReused``. Generation ``1``
        is written to the raw store after the row is inserted and before
        the transaction commits.

        Args:
            organization_id: The owning organization.
            slug: The path segment identifying the project within its
                organization; 2 to 62 characters of lowercase letters, digits
                and hyphens, with no doubled hyphen.
            title: The human-readable name.
            description: Free-text description; may be empty.
            data_classification: A code from the configured vocabulary; it
                cannot be changed afterwards, since descriptive updates take
                none.
            claim: The caller's idempotency claim for this request.

        Returns:
            The stored project, at generation and version ``1``.

        Raises:
            ClassificationUnknown: If ``data_classification`` is not in the
                vocabulary.
        """
        await self._access.require("project.create", ScopeType.ORGANIZATION, organization_id)
        self._access.require_claim(claim)
        visibility = await self._access.visibility()
        validate_slug(slug, 62)
        if data_classification not in self._classification_vocabulary:
            raise ClassificationUnknown(f"unknown data classification: {data_classification}")
        async with self._hierarchy.transaction() as writer:
            organization = await self._hierarchy.organizations.get(organization_id, visibility)
            replayed = await claimed_result(
                writer,
                claim,
                lambda resource_id: self._hierarchy.projects.get(resource_id, Visibility.ALL),
            )
            if replayed is not None:
                return replayed
            item = Project(
                uuid7(),
                organization_id,
                slug,
                title,
                description,
                data_classification,
                1,
                1,
                datetime.now(UTC),
            )
            await writer.insert_project(item)
            await self._publish_created(
                writer, claim, item, project_dir(self._root, organization, item)
            )
            return item

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
        """Create a dataset under a project and write its first generation.

        The slug is validated by ``validate_slug`` (which raises
        ``PathRuleViolation``), may run to 80 characters - longer than an
        organization or project slug - and is immutable afterwards because
        it names the dataset's storage directory; it must be unique within
        the project. ``entry_layer`` is parsed by ``parse_entry_layer``,
        which raises ``LayerWorkflowError`` for an unknown layer and for
        gold: every gold version needs a derivation record, so nothing may
        enter there directly. The project is read with ``visibility``, so
        an invisible or absent project is ``ResourceNotFound``; its
        organization is then read with unrestricted visibility purely to
        build the storage path. Every dataset starts in the ``ACTIVE``
        lifecycle state and inherits its project's data classification.
        Creation is idempotent per ``claim``: staking an identical claim
        returns the original dataset without writing, and staking one whose
        key was used for a different request is refused with
        ``IdempotencyKeyReused``. Generation ``1`` is written to the raw
        store after the row is inserted and before the transaction commits.

        Args:
            project_id: The owning project.
            slug: The path segment identifying the dataset within its
                project; 2 to 80 characters of lowercase letters, digits and
                hyphens, with no doubled hyphen.
            title: The human-readable name.
            description: Free-text description; may be empty.
            profile_name: The dataset profile the dataset declares; stored
                verbatim, not validated here.
            profile_version: The declared profile's version; stored verbatim.
            entry_layer: The layer at which the dataset's data first arrives:
                ``raw`` (the default), ``bronze`` or ``silver``, never
                ``gold``.
            claim: The caller's idempotency claim for this request.

        Returns:
            The stored dataset, ``ACTIVE`` at generation and version ``1``.
        """
        await self._access.require("dataset.create", ScopeType.PROJECT, project_id)
        self._access.require_claim(claim)
        visibility = await self._access.visibility()
        validate_slug(slug, 80)
        entry = parse_entry_layer(entry_layer)
        async with self._hierarchy.transaction() as writer:
            project = await self._hierarchy.projects.get(project_id, visibility)
            organization = await self._hierarchy.organizations.get(
                project.organization_id, Visibility.ALL
            )
            replayed = await claimed_result(
                writer,
                claim,
                lambda resource_id: self._hierarchy.datasets.get(resource_id, Visibility.ALL),
            )
            if replayed is not None:
                return replayed
            item = Dataset(
                uuid7(),
                project_id,
                slug,
                title,
                description,
                profile_name,
                profile_version,
                entry.value,
                DatasetLifecycle.ACTIVE,
                1,
                1,
                datetime.now(UTC),
            )
            await writer.insert_dataset(item, data_classification=project.data_classification)
            await self._publish_created(
                writer, claim, item, dataset_dir(self._root, organization, project, item)
            )
            return item

    async def _publish_created(
        self,
        writer: RetryTransaction,
        claim: IdempotencyClaim,
        item: Organization | Project | Dataset,
        directory: PurePosixPath,
    ) -> None:
        """Publish a created entity's generation before recording its retry receipt.

        The caller has inserted the entity in the transaction holding the claim.
        Both publication and receipt recording must succeed before that transaction commits.

        Args:
            writer: The transaction containing the identity insert and retry claim.
            claim: The creation request's acquired idempotency claim.
            item: The inserted entity, which determines its receipt kind and identity.
            directory: The entity's resolved generation directory.
        """
        kind: Literal["organization", "project", "dataset"]
        if isinstance(item, Organization):
            kind = "organization"
        elif isinstance(item, Project):
            kind = "project"
        else:
            kind = "dataset"
        await self._generations.write(directory, item)
        await writer.remember(claim, Replay(kind=kind, resource_id=item.id))
