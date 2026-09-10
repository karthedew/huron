"""Internal catalog transaction and storage coordination.

:class:`HierarchyRepository` implements persistence for the authorized core catalog over the
organization/project/dataset/release/revision hierarchy - persisted through
an injected :class:`~huron.core.ports.HierarchyStore` - and over the
injected RBAC store. Every write is one store transaction: the row lands
first, then the durable generation (or release-tag) document, both before
the transaction's commit makes the change visible to any reader. A slug is
immutable once created, because it is baked into the storage path; no patch
accepts a different one. The store itself validates nothing - every slug,
tag and classification check happens here, before the store is ever asked to
do anything - and writes no file; the document write is this repository's
job, run off the event loop through ``asyncify`` because it may block on the
raw store's filesystem.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import PurePosixPath
from typing import TYPE_CHECKING

from asyncer import asyncify

from huron.pkg.catalog.errors import (
    ClassificationUnknown,
    TagExists,
)
from huron.pkg.catalog.ids import uuid7
from huron.pkg.catalog.layers import Layer, parse_entry_layer
from huron.pkg.catalog.lifecycle import DatasetLifecycle
from huron.pkg.catalog.manifest import canonical_bytes
from huron.pkg.catalog.paths import (
    dataset_dir,
    organization_dir,
    project_dir,
    release_tag_file,
    validate_org_slug,
    validate_slug,
    validate_tag,
)
from huron.pkg.catalog.persistence import Replay
from huron.pkg.catalog.records import (
    Dataset,
    Organization,
    Policy,
    PolicyAttachment,
    Project,
    Release,
    RoleBindingRecord,
    ServiceAccount,
    jsonable,
)
from huron.pkg.rbac import Binding, ProjectVisibility, ScopeType, Visibility

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable
    from uuid import UUID

    from huron.pkg.catalog.ports import RawStore

    from .ports import HierarchyStore, HierarchyWriter, RbacStore
from huron.pkg.catalog.persistence import IdempotencyClaim, Window


class HierarchyRepository:
    """Internal catalog operations used by authorized core services and bootstrap wiring.

    One instance is wired per application, and every route reaches the
    hierarchy - organizations, projects, datasets, revisions and releases -
    through it. The hierarchy and its idempotency claims live in the
    injected ``HierarchyStore``; role bindings, service accounts and
    policies live in the injected RBAC store; the raw store holds the
    durable generation and release-tag documents.

    Invariants every method keeps:

    - A write is one store transaction: the row is inserted or updated
      first, then its durable document is written, both before the
      transaction commits and the change becomes visible to any reader.
      Nothing ever touches disk before the row insert or update succeeded.
    - A slug is immutable once created, because it is baked into the
      storage path; no role can change it, and the patch methods refuse a
      different slug before the version precondition is even compared.
    - Every read, write and RBAC existence check is resolved through the
      caller's ``Visibility``: an id the caller cannot discover is
      ``ResourceNotFound``, indistinguishable from one that does not exist.
    - Creation is idempotent per ``IdempotencyClaim``: replaying an
      identical claim returns the original record without writing again,
      and reusing a claim's key for a different request is refused.

    Attributes:
        raw_store: The raw store holding the durable documents.
    """

    def __init__(
        self,
        raw_store: RawStore,
        hierarchy: HierarchyStore,
        *,
        classification_vocabulary: tuple[str, ...],
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
            classification_vocabulary: The data-classification codes a
                project may declare; ``create_project`` refuses any other.
            rbac_store: Storage for role bindings, service accounts and
                policies.
        """
        self.raw_store = raw_store
        self.raw_store.initialize()
        self._hierarchy = hierarchy
        self._classification_vocabulary = frozenset(classification_vocabulary)
        self._rbac_store = rbac_store

    @property
    def data_root(self) -> PurePosixPath:
        """Return the raw store's root in the form the layout functions take.

        Every ``organization/...`` directory and release-tag file is derived
        from this root by :mod:`huron.pkg.catalog.paths`.

        Returns:
            The raw store's root directory as a ``PurePosixPath``.
        """
        return PurePosixPath(self.raw_store.root)

    async def _claimed_result[RecordT](
        self,
        writer: HierarchyWriter,
        claim: IdempotencyClaim,
        read: Callable[[UUID], Awaitable[RecordT]],
    ) -> RecordT | None:
        """Stake a write's idempotency claim, returning what a prior identical claim produced.

        Args:
            writer: The open transaction's writer.
            claim: The claim this write is staking.
            read: Given the id ``claim`` was originally remembered under,
                returns the resource it named. A release ignores the id,
                since its own read is keyed by dataset and tag instead.

        Returns:
            The resource an earlier, identical request already created, or
            ``None`` when no live claim exists and this transaction is the
            one to perform the write.
        """
        replay = await writer.claim(claim)
        if replay is None:
            return None
        return await read(replay.resource_id)

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
        validate_org_slug(slug)
        async with self._hierarchy.transaction() as writer:
            replayed = await self._claimed_result(
                writer, claim, lambda resource_id: self.organization(resource_id, Visibility.ALL)
            )
            if replayed is not None:
                return replayed
            item = Organization(uuid7(), slug, title, description, 1, 1, datetime.now(UTC))
            await writer.insert_organization(item)
            await asyncify(self._write_generation)(organization_dir(self.data_root, item), item)
            await writer.remember(claim, Replay(kind="organization", resource_id=item.id))
            return item

    async def patch_organization(
        self,
        organization_id: UUID,
        visibility: Visibility,
        *,
        expected_version: int,
        slug: str | None,
        title: str | None,
        description: str | None,
    ) -> Organization:
        """Apply a partial update to an organization under a version precondition.

        The organization is read with ``visibility``, so an invisible or
        absent id is ``ResourceNotFound`` before the version is even
        compared. ``expected_version`` is the version the caller last saw -
        the route derives it from the ``If-Match`` header - and the patch
        applies only while it still matches. A ``slug`` that differs from
        the current one is refused before the version is compared: the slug
        is baked into the organization's storage path, so no role may
        change it; passing the current slug, or ``None``, is accepted.
        ``title`` and ``description`` replace the stored values when given
        and are left alone when ``None``; a patch naming no change - both
        left ``None`` or already equal to what is stored - is a no-op that
        opens no transaction, writes no document and returns the record
        unchanged. Otherwise ``generation`` and ``version`` each advance by
        one, and the new generation document is written before the
        transaction commits.

        Args:
            organization_id: The organization to update.
            visibility: The caller's discovery rights.
            expected_version: The version the caller believes is current.
            slug: The current slug or ``None``; any other value is refused.
            title: A replacement title, or ``None`` to keep the current one.
            description: A replacement description, or ``None`` to keep it.

        Returns:
            The organization, unchanged if the patch named no change, or
            with version and generation advanced.
        """
        item = await self.organization(organization_id, visibility)
        return await self._patch_description(
            item, expected_version=expected_version, slug=slug, title=title, description=description
        )

    async def create_project(
        self,
        organization_id: UUID,
        visibility: Visibility,
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
            visibility: The caller's discovery rights, used to resolve
                ``organization_id``.
            slug: The path segment identifying the project within its
                organization; 2 to 62 characters of lowercase letters, digits
                and hyphens, with no doubled hyphen.
            title: The human-readable name.
            description: Free-text description; may be empty.
            data_classification: A code from the configured vocabulary; it
                cannot be changed afterwards, since ``patch_project`` takes
                none.
            claim: The caller's idempotency claim for this request.

        Returns:
            The stored project, at generation and version ``1``.

        Raises:
            ClassificationUnknown: If ``data_classification`` is not in the
                vocabulary.
        """
        validate_slug(slug, 62)
        if data_classification not in self._classification_vocabulary:
            raise ClassificationUnknown(f"unknown data classification: {data_classification}")
        async with self._hierarchy.transaction() as writer:
            organization = await self._hierarchy.organization(organization_id, visibility)
            replayed = await self._claimed_result(
                writer, claim, lambda resource_id: self.project(resource_id, Visibility.ALL)
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
            await asyncify(self._write_generation)(
                project_dir(self.data_root, organization, item), item
            )
            await writer.remember(claim, Replay(kind="project", resource_id=item.id))
            return item

    async def patch_project(
        self,
        project_id: UUID,
        visibility: Visibility,
        *,
        expected_version: int,
        slug: str | None,
        title: str | None,
        description: str | None,
    ) -> Project:
        """Apply a partial update to a project under a version precondition.

        The project is read with ``visibility``, so an invisible or absent
        id is ``ResourceNotFound`` before the version is even compared. A
        ``slug`` that differs from the current one is refused before the
        version is compared: the slug is baked into the project's storage
        path, so no role may change it; the data classification has no
        parameter here and so cannot change. ``title`` and ``description``
        replace the stored values when given and are left alone when
        ``None``; a patch naming no change is a no-op that opens no
        transaction, writes no document and returns the record unchanged.
        Otherwise ``generation`` and ``version`` each advance by one.

        Args:
            project_id: The project to update.
            visibility: The caller's discovery rights.
            expected_version: The version the caller believes is current.
            slug: The current slug or ``None``; any other value is refused.
            title: A replacement title, or ``None`` to keep the current one.
            description: A replacement description, or ``None`` to keep it.

        Returns:
            The project, unchanged if the patch named no change, or with
            version and generation advanced.
        """
        item = await self.project(project_id, visibility)
        return await self._patch_description(
            item, expected_version=expected_version, slug=slug, title=title, description=description
        )

    async def create_dataset(
        self,
        project_id: UUID,
        visibility: Visibility,
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
            visibility: The caller's discovery rights, used to resolve
                ``project_id``.
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
        validate_slug(slug, 80)
        entry = parse_entry_layer(entry_layer)
        async with self._hierarchy.transaction() as writer:
            project = await self._hierarchy.project(project_id, visibility)
            organization = await self._hierarchy.organization(
                project.organization_id, Visibility.ALL
            )
            replayed = await self._claimed_result(
                writer, claim, lambda resource_id: self.dataset(resource_id, Visibility.ALL)
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
            await asyncify(self._write_generation)(
                dataset_dir(self.data_root, organization, project, item), item
            )
            await writer.remember(claim, Replay(kind="dataset", resource_id=item.id))
            return item

    async def patch_dataset(
        self,
        dataset_id: UUID,
        visibility: Visibility,
        *,
        expected_version: int,
        slug: str | None,
        title: str | None,
        description: str | None,
    ) -> Dataset:
        """Apply a partial update to a dataset under a version precondition.

        The dataset is read with ``visibility``, so an invisible or absent
        id is ``ResourceNotFound`` before the version is even compared. A
        ``slug`` that differs from the current one is refused before the
        version is compared: the slug is baked into the dataset's storage
        path, so no role may change it. ``title`` and ``description``
        replace the stored values when given and are left alone when
        ``None``; a patch naming no change is a no-op that opens no
        transaction, writes no document and returns the record unchanged.
        Otherwise ``generation`` and ``version`` each advance by one.

        Args:
            dataset_id: The dataset to update.
            visibility: The caller's discovery rights.
            expected_version: The version the caller believes is current.
            slug: The current slug or ``None``; any other value is refused.
            title: A replacement title, or ``None`` to keep the current one.
            description: A replacement description, or ``None`` to keep it.

        Returns:
            The dataset, unchanged if the patch named no change, or with
            version and generation advanced.
        """
        item = await self.dataset(dataset_id, visibility)
        return await self._patch_description(
            item, expected_version=expected_version, slug=slug, title=title, description=description
        )

    async def _patch_description[ItemT: (Organization, Project, Dataset)](
        self,
        item: ItemT,
        *,
        expected_version: int,
        slug: str | None,
        title: str | None,
        description: str | None,
    ) -> ItemT:
        """Publish a descriptive successor only after the row's version comparison succeeds.

        The caller has already resolved the entity through its visibility. Ancestors
        are loaded solely to derive the immutable storage path, inside the transaction
        after the update; a no-op performs neither those reads nor any write.

        Args:
            item: The visible current hierarchy entity.
            expected_version: The version the caller observed.
            slug: The immutable current slug, or None to retain it.
            title: A replacement title, or None to retain it.
            description: A replacement description, or None to retain it.

        Returns:
            The original entity for a no-op, or its durably recorded successor.
        """
        successor = item.describe(
            expected_version=expected_version, slug=slug, title=title, description=description
        )
        if successor is item:
            return item
        async with self._hierarchy.transaction() as writer:
            directory = await self._update_description(writer, successor, item.version)
            await asyncify(self._write_generation)(directory, successor)
        return successor

    async def _update_description(
        self,
        writer: HierarchyWriter,
        successor: Organization | Project | Dataset,
        expected_version: int,
    ) -> PurePosixPath:
        """Update the entity's row and resolve its generation document directory.

        Args:
            writer: The open hierarchy transaction.
            successor: The immutable descriptive successor.
            expected_version: The version required on the persisted entity.

        Returns:
            The stable directory for the entity whose row was updated.
        """
        if isinstance(successor, Organization):
            await writer.update_organization(successor, expected_version=expected_version)
            return organization_dir(self.data_root, successor)
        if isinstance(successor, Project):
            await writer.update_project(successor, expected_version=expected_version)
            organization = await self._hierarchy.organization(
                successor.organization_id, Visibility.ALL
            )
            return project_dir(self.data_root, organization, successor)
        await writer.update_dataset(successor, expected_version=expected_version)
        project = await self._hierarchy.project(successor.project_id, Visibility.ALL)
        organization = await self._hierarchy.organization(project.organization_id, Visibility.ALL)
        return dataset_dir(self.data_root, organization, project, successor)

    async def create_release(
        self,
        dataset_id: UUID,
        visibility: Visibility,
        *,
        tag: str,
        revision_number: int,
        title: str | None,
        created_by: str,
        claim: IdempotencyClaim,
    ) -> Release:
        """Pin a release tag to a registered revision of a dataset.

        ``tag`` must satisfy the tag rules (``validate_tag`` raises
        ``PathRuleViolation`` otherwise) and is unique within the dataset for
        all time: the release is stored as a write-once file under the
        dataset's ``releases/`` directory, so a tag is refused both when the
        store already holds it and when the file already exists on disk.
        The dataset is read with ``visibility``, so an invisible or absent
        dataset is ``ResourceNotFound``; its project and organization are
        then read with unrestricted visibility purely to build the storage
        path, and the revision is resolved by ``revision_number`` - an
        unregistered number is ``ResourceNotFound``. Creation is idempotent
        per ``claim``: staking an identical claim returns the original
        release without writing, and staking one whose key was used for a
        different request is refused with ``IdempotencyKeyReused``. The tag
        file is written after the row is inserted and before the
        transaction commits.

        Args:
            dataset_id: The dataset the tag belongs to.
            visibility: The caller's discovery rights, used to resolve
                ``dataset_id``.
            tag: The release tag; 2 to 63 characters of lowercase letters,
                digits, dots, underscores and hyphens.
            revision_number: The number of a revision already registered for
                the dataset.
            title: An optional human-readable name for the release.
            created_by: The subject of the principal creating the release.
            claim: The caller's idempotency claim for this request.

        Returns:
            The stored release, pinned to the revision's id and number.

        Raises:
            TagExists: If the dataset already has a release with ``tag``,
                in the store or on disk.
        """
        validate_tag(tag)
        async with self._hierarchy.transaction() as writer:
            dataset = await self._hierarchy.dataset(dataset_id, visibility)
            project = await self._hierarchy.project(dataset.project_id, Visibility.ALL)
            organization = await self._hierarchy.organization(
                project.organization_id, Visibility.ALL
            )
            revision = await self._hierarchy.revision_ref(dataset_id, revision_number)
            replayed = await self._claimed_result(
                writer, claim, lambda _: self.release(dataset_id, tag, Visibility.ALL)
            )
            if replayed is not None:
                return replayed
            item = Release(
                uuid7(),
                dataset_id,
                tag,
                revision.id,
                revision.number,
                title,
                created_by,
                datetime.now(UTC),
            )
            await writer.insert_release(item)
            payload = canonical_bytes(jsonable(item))
            tag_path = release_tag_file(self.data_root, organization, project, dataset, tag)
            try:
                await asyncify(self.raw_store.write_tag_once)(tag_path, payload)
            except FileExistsError as exc:
                raise TagExists(f"release tag already exists: {tag}") from exc
            await writer.remember(claim, Replay(kind="release", resource_id=item.id))
            return item

    async def organization(self, organization_id: UUID, visibility: Visibility) -> Organization:
        """Return one organization, if ``visibility`` admits it.

        Args:
            organization_id: The organization's id.
            visibility: The caller's discovery rights.

        Returns:
            The stored organization record. The store raises
            ``ResourceNotFound`` when no organization has
            ``organization_id``, or ``visibility`` does not admit it.
        """
        return await self._hierarchy.organization(organization_id, visibility)

    async def project(self, project_id: UUID, visibility: Visibility) -> Project:
        """Return one project, if ``visibility`` admits it.

        Args:
            project_id: The project's id.
            visibility: The caller's discovery rights.

        Returns:
            The stored project record. The store raises
            ``ResourceNotFound`` when no project has ``project_id``, or
            ``visibility`` does not admit it.
        """
        return await self._hierarchy.project(project_id, visibility)

    async def dataset(self, dataset_id: UUID, visibility: Visibility) -> Dataset:
        """Return one dataset, if ``visibility`` admits it.

        Args:
            dataset_id: The dataset's id.
            visibility: The caller's discovery rights.

        Returns:
            The stored dataset record. The store raises
            ``ResourceNotFound`` when no dataset has ``dataset_id``, or
            ``visibility`` does not admit it.
        """
        return await self._hierarchy.dataset(dataset_id, visibility)

    async def release(self, dataset_id: UUID, tag: str, visibility: Visibility) -> Release:
        """Return the release a dataset publishes under a tag, if ``visibility`` admits the dataset.

        Args:
            dataset_id: The dataset the tag belongs to.
            tag: The release tag to resolve.
            visibility: The caller's discovery rights.

        Returns:
            The release created under that tag. The store raises
            ``ResourceNotFound`` when the dataset has no release with
            ``tag``, or ``visibility`` does not admit the dataset.
        """
        return await self._hierarchy.release(dataset_id, tag, visibility)

    async def organizations(
        self, visibility: Visibility, *, limit: int, after: tuple[str, UUID] | None
    ) -> Window[Organization]:
        """Return a window of organizations ordered by ``(slug, id)``.

        Args:
            visibility: The caller's discovery rights; only admitted
                organizations are counted toward ``limit``.
            limit: The maximum number of organizations to return.
            after: The ``(slug, id)`` of the last organization already
                seen, excluded from the window, or ``None`` to start from
                the beginning.

        Returns:
            The next window of admitted organizations.
        """
        return await self._hierarchy.organizations(visibility, limit=limit, after=after)

    async def projects(
        self,
        organization_id: UUID,
        visibility: Visibility,
        *,
        limit: int,
        after: tuple[str, UUID] | None,
    ) -> Window[Project]:
        """Return a window of one organization's projects ordered by ``(slug, id)``.

        The organization is read with ``visibility`` first, so an invisible
        or absent organization is ``ResourceNotFound`` rather than an empty
        window.

        Args:
            organization_id: The owning organization.
            visibility: The caller's discovery rights; only admitted
                projects are counted toward ``limit``.
            limit: The maximum number of projects to return.
            after: The ``(slug, id)`` of the last project already seen,
                excluded from the window, or ``None`` to start from the
                beginning.

        Returns:
            The next window of admitted projects.
        """
        await self._hierarchy.organization(organization_id, visibility)
        return await self._hierarchy.projects(organization_id, visibility, limit=limit, after=after)

    async def datasets(
        self,
        project_id: UUID,
        visibility: Visibility,
        *,
        limit: int,
        after: tuple[str, UUID] | None,
    ) -> Window[Dataset]:
        """Return a window of one project's datasets ordered by ``(slug, id)``.

        The project is read with ``visibility`` first, so an invisible or
        absent project is ``ResourceNotFound`` rather than an empty window.

        Args:
            project_id: The owning project.
            visibility: The caller's discovery rights; only admitted
                datasets are counted toward ``limit``.
            limit: The maximum number of datasets to return.
            after: The ``(slug, id)`` of the last dataset already seen,
                excluded from the window, or ``None`` to start from the
                beginning.

        Returns:
            The next window of admitted datasets.
        """
        await self._hierarchy.project(project_id, visibility)
        return await self._hierarchy.datasets(project_id, visibility, limit=limit, after=after)

    async def releases(
        self, dataset_id: UUID, visibility: Visibility, *, limit: int, after: tuple[str] | None
    ) -> Window[Release]:
        """Return a window of one dataset's releases ordered by ``tag``.

        The dataset is read with ``visibility`` first, so an invisible or
        absent dataset is ``ResourceNotFound`` rather than an empty window.

        Args:
            dataset_id: The dataset whose releases to list.
            visibility: The caller's discovery rights, checked against the
                dataset itself.
            limit: The maximum number of releases to return.
            after: The tag of the last release already seen, excluded from
                the window, or ``None`` to start from the beginning.

        Returns:
            The next window of the dataset's releases.
        """
        await self._hierarchy.dataset(dataset_id, visibility)
        return await self._hierarchy.releases(dataset_id, visibility, limit=limit, after=after)

    async def project_visibilities(self) -> list[ProjectVisibility]:
        """Return every project's identity, owning organization and classification.

        This is the input the per-request visibility computation reduces
        role bindings against; it applies no filtering of its own.

        Returns:
            Every project, in no particular order.
        """
        return await self._hierarchy.project_visibilities()

    async def dataset_parents(self, dataset_ids: frozenset[UUID]) -> dict[UUID, UUID]:
        """Return each requested dataset's owning project id.

        This is the second input the per-request visibility computation
        needs: which project's classification and bindings a dataset-scope
        grant is evaluated against.

        Args:
            dataset_ids: The datasets to resolve.

        Returns:
            A mapping from dataset id to project id, holding an entry for
            every id in ``dataset_ids`` that exists; an id that names no
            dataset is simply absent, not an error.
        """
        return await self._hierarchy.dataset_parents(dataset_ids)

    # -- RBAC ------------------------------------------------------------
    # Every method below delegates to ``self._rbac_store``; the only logic
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
        return await self._rbac_store.grant_role(
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
        return await self._rbac_store.revoke_role(binding_id)

    async def get_role_binding(self, binding_id: UUID) -> RoleBindingRecord:
        """Return one role binding by id.

        The store raises ``ResourceNotFound`` when no such binding exists.

        Args:
            binding_id: The binding's id.

        Returns:
            The stored binding.
        """
        return await self._rbac_store.get_role_binding(binding_id)

    async def bindings_for(self, identifiers: frozenset[str]) -> tuple[Binding, ...]:
        """Return the compiled capability bindings held by any of some identifiers.

        ``identifiers`` is a principal's whole identifier set - its own
        ``user:`` or ``sa:`` name plus one ``group:`` entry per group - so a
        single call answers "what may this caller do" in the form
        ``decide()`` consumes. The result is whatever the store compiles from
        the stored grants; the per-request binding cache memoizes it by
        identifier set.

        Args:
            identifiers: The ``kind:subject`` strings that count as the
                caller.

        Returns:
            The compiled bindings whose principal is one of ``identifiers``.
        """
        return await self._rbac_store.bindings_for(identifiers)

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
        return await self._rbac_store.bindings_at(scope_type, scope_id)

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
        organization = await self.organization(organization_id, Visibility.ALL)
        subject = f"{organization.slug}/{name}"
        return await self._rbac_store.create_service_account(
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
        return await self._rbac_store.get_service_account(principal_id)

    async def service_account_by_subject(self, subject: str) -> ServiceAccount:
        """Return one service account by the subject its API keys carry.

        This is how an authenticated ``sa:`` principal is traced back to its
        owning organization, from which its whole authority is synthesized.
        The store raises ``ResourceNotFound`` when no account has
        ``subject`` - for example a key that outlived its account.

        Args:
            subject: The ``{organization slug}/{name}`` subject.

        Returns:
            The stored account, disabled or not.
        """
        return await self._rbac_store.service_account_by_subject(subject)

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
        return await self._rbac_store.list_service_accounts(organization_id)

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
        return await self._rbac_store.disable_service_account(principal_id, disabled_at=disabled_at)

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
        return await self._rbac_store.create_policy(
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
        return await self._rbac_store.attach_policy(
            policy_id, scope_type=scope_type, scope_id=scope_id, attached_by=attached_by
        )

    async def list_policies(self) -> list[Policy]:
        """Return every policy, ordered by ``(name, id)``.

        The order is the key the listing route pages by; ``id`` breaks ties
        because names are not unique.

        Returns:
            All policies, sorted by name and then id.
        """
        return await self._rbac_store.list_policies()

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
            await self._hierarchy.organization(scope_id, Visibility.ALL)
        elif scope_type is ScopeType.PROJECT:
            await self._hierarchy.project(scope_id, Visibility.ALL)
        else:
            await self._hierarchy.dataset(scope_id, Visibility.ALL)

    def _write_generation(
        self, entity_path: PurePosixPath, item: Organization | Project | Dataset
    ) -> None:
        """Persist one record as its current generation document.

        The record is rendered with ``jsonable``, stamped with the
        ``urn:huron:generation:1`` schema and serialized canonically, then
        handed to the raw store, which writes
        ``generations/{generation:06d}.json`` and atomically repoints
        ``CURRENT.json`` at it. The caller must already have advanced
        ``item.generation`` to the number this write acknowledges: the
        store replaces a generation file that already exists at that
        number rather than refusing it, because an acknowledged generation
        is made immutable by the hierarchy store advancing ``version`` only
        through a committed update, not by the file being write-once - a
        file already on disk at a generation number that has not yet been
        acknowledged can only be a crashed attempt, and replacing it loses
        nothing. A number outside ``1..999999`` raises ``ValueError``.
        Always called through ``asyncify``, since it may block on the raw
        store's filesystem.

        Args:
            entity_path: The entity's directory under the data root, as
                built by :mod:`huron.pkg.catalog.paths`.
            item: The organization, project or dataset to persist.
        """
        document = jsonable(item)
        document["schema"] = "urn:huron:generation:1"
        self.raw_store.write_generation(entity_path, item.generation, canonical_bytes(document))
