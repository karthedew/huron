"""Persistence ports for upload attempts and stored objects."""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    import uuid
    from collections.abc import Collection, Mapping, Sequence
    from datetime import datetime

    from huron.core.lake.uploads.models import StoredObject, UploadAttempt

__all__ = ["AttemptStore", "ObjectStore"]


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

    async def find_uploads(
        self, upload_ids: Collection[uuid.UUID]
    ) -> Mapping[uuid.UUID, UploadAttempt]:
        """The attempt of each issued ID of ``upload_ids``, read without a row lock.

        The map has a key for each of ``upload_ids`` that Huron issued, current or not.
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

    async def spent(self, upload_ids: Collection[uuid.UUID]) -> set[uuid.UUID]:
        """The IDs of ``upload_ids`` whose tusd files no attempt needs any more.

        A spent ID is an issued ID that is not the current ID of its attempt, or any ID of an
        attempt that is ``consumed``, ``failed``, ``cancelled`` or ``expired``. An ID that Huron
        never issued is not spent.
        """
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

    async def unreferenced(self, after: uuid.UUID | None, limit: int) -> Sequence[StoredObject]:
        """Up to ``limit`` objects that no row needs any more, in the order of their IDs.

        Such an object is not ``removed``. Its upload ID is not the current ID of its attempt,
        or its attempt is ``consumed``, ``failed``, ``cancelled`` or ``expired``. No file row
        names the object, and no entry of an ``accepted`` or ``blocked`` request names its
        upload ID. With ``after``, only objects with a greater ID come. The rows are not locked.
        """
        ...

    async def update(self, stored: StoredObject) -> None:
        """Replace the state, the size, the SHA-256, the inode and the seal time of an object.

        Nothing happens when no object has the ID of ``stored``.
        """
        ...
