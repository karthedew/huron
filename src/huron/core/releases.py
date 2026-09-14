"""Authorized immutable release publication, resolution and browsing."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import PurePosixPath
from typing import TYPE_CHECKING

from asyncer import asyncify

from huron.pkg.catalog.errors import TagExists
from huron.pkg.catalog.ids import uuid7
from huron.pkg.catalog.manifest import canonical_bytes
from huron.pkg.catalog.paths import release_tag_file, validate_tag
from huron.pkg.catalog.persistence import Replay
from huron.pkg.catalog.records import Release, jsonable
from huron.pkg.rbac import ScopeType, Visibility

from .catalog_claims import claimed_result

if TYPE_CHECKING:
    from uuid import UUID

    from huron.pkg.catalog.persistence import IdempotencyClaim, Window
    from huron.pkg.catalog.ports import RawStore

    from .access import AccessPolicy
    from .catalog_ports import ReleaseStore


class Releases:
    """Pin, resolve and browse a dataset's immutable release tags."""

    def __init__(self, access: AccessPolicy, hierarchy: ReleaseStore, storage: RawStore) -> None:
        """Bind release operations to the current actor and durable storage.

        Args:
            access: The authenticated actor and current authorization facts.
            hierarchy: Committed ancestry, release resolution and the
                claimed release-publication transaction.
            storage: Initialized generation and tag-document storage, owned
                by the application.
        """
        self._access = access
        self._hierarchy = hierarchy
        self._storage = storage
        self._root = PurePosixPath(storage.root)

    async def create_release(
        self,
        dataset_id: UUID,
        *,
        tag: str,
        revision_number: int,
        title: str | None,
        claim: IdempotencyClaim,
    ) -> Release:
        """Pin a release tag to a registered revision of a dataset.

        ``tag`` must satisfy the tag rules (``validate_tag`` raises
        ``PathRuleViolation`` otherwise) and is unique within the dataset for
        all time: the release is stored as a write-once file under the
        dataset's ``releases/`` directory, so a tag is refused both when the
        store already holds it and when the file already exists on disk.
        The dataset is read with the caller's current visibility, so an
        invisible or absent dataset is ``ResourceNotFound``; its project and
        organization are then read with unrestricted visibility purely to
        build the storage path, and the revision is resolved by
        ``revision_number`` - an unregistered number is ``ResourceNotFound``.
        Creation is idempotent per ``claim``: staking an identical claim
        returns the original release without writing, and staking one whose
        key was used for a different request is refused with
        ``IdempotencyKeyReused``. The tag file is written after the row is
        inserted and before the transaction commits.

        Args:
            dataset_id: The dataset the tag belongs to.
            tag: The release tag; 2 to 63 characters of lowercase letters,
                digits, dots, underscores and hyphens.
            revision_number: The number of a revision already registered for
                the dataset.
            title: An optional human-readable name for the release.
            claim: The caller's idempotency claim for this request.

        Returns:
            The stored release, pinned to the revision's id and number.

        Raises:
            TagExists: If the dataset already has a release with ``tag``,
                in the store or on disk.
        """
        await self._access.require("release.create", ScopeType.DATASET, dataset_id)
        self._access.require_claim(claim)
        created_by = self._access.actor.subject
        validate_tag(tag)
        visibility = await self._access.visibility()
        async with self._hierarchy.transaction() as writer:
            dataset = await self._hierarchy.datasets.get(dataset_id, visibility)
            project = await self._hierarchy.projects.get(dataset.project_id, Visibility.ALL)
            organization = await self._hierarchy.organizations.get(
                project.organization_id, Visibility.ALL
            )
            revision = await self._hierarchy.revision_ref(dataset_id, revision_number)
            replayed = await claimed_result(
                writer, claim, lambda _: self._hierarchy.release(dataset_id, tag, Visibility.ALL)
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
            tag_path = release_tag_file(self._root, organization, project, dataset, tag)
            try:
                await asyncify(self._storage.write_tag_once)(tag_path, payload)
            except FileExistsError as exc:
                raise TagExists(f"release tag already exists: {tag}") from exc
            await writer.remember(claim, Replay(kind="release", resource_id=item.id))
            return item

    async def release(self, dataset_id: UUID, tag: str) -> Release:
        """Return the release a dataset publishes under a tag, if visible to the caller.

        Args:
            dataset_id: The dataset the tag belongs to.
            tag: The release tag to resolve.

        Returns:
            The release created under that tag. Raises ``ResourceNotFound``
            when the dataset has no release with ``tag``, or the caller's
            current visibility does not admit the dataset.
        """
        return await self._hierarchy.release(dataset_id, tag, await self._access.visibility())

    async def releases(
        self, dataset_id: UUID, *, limit: int, after: tuple[str] | None
    ) -> Window[Release]:
        """Return a window of one dataset's releases ordered by ``tag``.

        The dataset is read with the caller's current visibility first, so
        an invisible or absent dataset is ``ResourceNotFound`` rather than an
        empty window.

        Args:
            dataset_id: The dataset whose releases to list.
            limit: The maximum number of releases to return.
            after: The tag of the last release already seen, excluded from
                the window, or ``None`` to start from the beginning.

        Returns:
            The next window of the dataset's releases.
        """
        visibility = await self._access.visibility()
        await self._hierarchy.datasets.get(dataset_id, visibility)
        return await self._hierarchy.releases(dataset_id, visibility, limit=limit, after=after)
