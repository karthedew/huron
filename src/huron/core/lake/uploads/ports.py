"""Persistence ports for uploads, the removal outbox, upload attempts and stored objects."""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    import uuid
    from collections.abc import Collection, Mapping, Sequence
    from datetime import datetime

    from huron.core.lake.uploads.models import Removal, StoredObject, Upload, UploadAttempt

__all__ = ["AttemptStore", "ObjectStore", "UploadStore"]


class AttemptStore(Protocol):
    """Reads and writes upload attempts with every upload ID that Huron issued for them.

    A transaction locks upload attempt rows after the collection row and the commit request row,
    and before the object rows.
    """

    async def insert_or_lock(self, attempt: UploadAttempt) -> UploadAttempt:
        """Store ``attempt`` when its key is free, then return the attempt of the key, locked.

        The key is the subject and the ``attempt_id``. When an attempt with the key exists, it is
        returned and ``attempt`` is not stored. Two transactions that store one key together give
        one attempt: the second waits for the first and gets the first's attempt.
        ``attempt.upload_ids`` are stored as issued at ``attempt.created_at``.

        Raises ``NameTaken`` when Huron issued one of ``attempt.upload_ids`` before.
        """
        ...

    async def get(self, subject: str, attempt_id: uuid.UUID) -> UploadAttempt | None:
        """The attempt of ``subject`` with ``attempt_id``."""
        ...

    async def lock_uploads(
        self, upload_ids: Collection[uuid.UUID]
    ) -> Mapping[uuid.UUID, UploadAttempt]:
        """The attempt of each issued ID of ``upload_ids``, locked until the transaction ends.

        The map has a key for each of ``upload_ids`` that Huron issued, current or not. The
        attempts are locked in the order of their row IDs.
        """
        ...

    async def lock_idle(self, before: datetime, limit: int) -> Sequence[UploadAttempt]:
        """Lock up to ``limit`` idle attempts whose last activity is before ``before``.

        An idle attempt is ``receiving`` or ``sealing``, or ``ready`` and held by no commit
        request. The oldest activity comes first. An attempt that another transaction holds
        locked is skipped.
        """
        ...

    async def staged_bytes(self) -> int:
        """The total declared size of the ``receiving``, ``sealing`` and ``ready`` attempts."""
        ...

    async def issue(self, attempt_id: uuid.UUID, upload_id: uuid.UUID, issued_at: datetime) -> None:
        """Issue ``upload_id`` for the stored attempt with row ID ``attempt_id``.

        ``upload_id`` becomes the current upload ID. Nothing happens when no attempt has the row
        ID. Raises ``NameTaken`` when Huron issued ``upload_id`` before.
        """
        ...

    async def update(self, attempt: UploadAttempt) -> None:
        """Replace the state, the activity time, the commit request and the failure of an attempt.

        Nothing happens when no attempt has the row ID of ``attempt``.
        """
        ...


class ObjectStore(Protocol):
    """Reads and writes the objects that seals make.

    A transaction locks object rows after every other row that it locks.
    """

    async def insert_or_lock(self, stored: StoredObject) -> StoredObject:
        """Store ``stored`` when its upload ID has no object, then return that object, locked.

        When the upload ID has an object, that object is returned and ``stored`` is not stored.
        Raises ``NameTaken`` when another object has the path of ``stored``.
        """
        ...

    async def lock_uploads(
        self, upload_ids: Collection[uuid.UUID]
    ) -> Mapping[uuid.UUID, StoredObject]:
        """The object of each of ``upload_ids`` that has one, by upload ID, locked in that order."""
        ...

    async def update(self, stored: StoredObject) -> None:
        """Replace the state, the size, the SHA-256, the inode and the seal time of an object.

        Nothing happens when no object has the ID of ``stored``.
        """
        ...


class UploadStore(Protocol):
    """Reads and writes uploads and the removals the API still has to make."""

    async def insert(self, upload: Upload) -> None:
        """Store a new upload."""
        ...

    async def get(self, upload_id: uuid.UUID) -> Upload | None:
        """The upload with ``upload_id``."""
        ...

    async def lock(self, upload_id: uuid.UUID) -> Upload | None:
        """The upload, locked for update until the transaction ends."""
        ...

    async def update(self, upload: Upload) -> None:
        """Replace the state, receipt (inode included), failure and commit of a stored upload."""
        ...

    async def latest_placements(
        self, collection_id: uuid.UUID, keys: Collection[str]
    ) -> Sequence[Upload]:
        """The latest placement of each of ``keys``, whoever made it.

        A placement is a ``placed`` or ``committed`` upload. The latest has the latest
        ``placed_at``, and of those the greatest id.
        """
        ...

    async def placed(self, collection_id: uuid.UUID) -> Sequence[Upload]:
        """The ``placed`` uploads of a collection, in the order they began."""
        ...

    async def mark_committed(self, upload_ids: Collection[uuid.UUID], commit_id: uuid.UUID) -> None:
        """Move the uploads to ``committed`` with ``commit_id``."""
        ...

    async def insert_removals(self, removals: Sequence[Removal]) -> None:
        """Store new removals as they are, claimed or not."""
        ...

    async def delete_removals(self, collection_id: uuid.UUID, keys: Collection[str]) -> None:
        """Forget the removals of ``keys``, claimed or not."""
        ...

    async def claim_removals(
        self, now: datetime, stale_before: datetime, limit: int
    ) -> list[Removal]:
        """Claim up to ``limit`` removals, oldest first, at ``now``.

        A removal is claimable when nobody claimed it, or when its claim is older than
        ``stale_before`` (the claimer stopped before it finished).
        """
        ...

    async def get_removal(self, removal_id: uuid.UUID) -> Removal | None:
        """The removal with ``removal_id``."""
        ...

    async def delete_removal(self, removal_id: uuid.UUID) -> None:
        """Forget a removal; nothing happens when it is gone already."""
        ...
