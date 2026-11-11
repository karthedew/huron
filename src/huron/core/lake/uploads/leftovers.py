"""Leftovers: the tusd files and the objects that no row needs any more.

The API removes these from the lake. The database decides what goes, by upload ID and by object
ID. No operation selects by age or by name, and no operation touches the filesystem. Every
transaction takes its row locks in the order of :mod:`huron.core.lake.uploads.attempts`: the
upload attempt rows, then the object rows.
"""

from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING

from huron.core.lake.uploads.models import ObjectState
from huron.pkg.paging import clamp_limit

if TYPE_CHECKING:
    import uuid
    from collections.abc import Collection

    from huron.core.lake.transaction import UnitOfWork
    from huron.core.lake.uploads.models import StoredObject

__all__ = ["Leftovers"]


class Leftovers:
    """Finds the tusd files and the objects to remove, and records each removed object."""

    def __init__(self, uow: UnitOfWork) -> None:
        self._uow = uow

    async def spent(self, upload_ids: Collection[uuid.UUID]) -> set[uuid.UUID]:
        """The IDs of ``upload_ids`` whose tusd files can go.

        An ID can go when it is not the current ID of its attempt, or when its attempt is
        ``consumed``, ``failed``, ``cancelled`` or ``expired``. Such an attempt never needs its
        tusd files again. An ID that Huron never issued never goes.
        """
        if not upload_ids:
            return set()
        async with self._uow.transaction() as tx:
            return await tx.attempts.spent(upload_ids)

    async def unreferenced(
        self, after: uuid.UUID | None = None, limit: int | None = None
    ) -> list[StoredObject]:
        """Up to ``limit`` objects to remove, in the order of their IDs, after ``after``.

        An object goes when it is not ``removed``, no file row names it, no pending request
        names its upload, and its upload ID is not current or its attempt ended or was
        consumed. Such an object never gets a new reference: only a ``ready`` attempt can join
        a request.
        """
        async with self._uow.transaction() as tx:
            return list(await tx.objects.unreferenced(after, clamp_limit(limit)))

    async def removed(self, stored: StoredObject) -> None:
        """Record that the file of the object ``stored`` is gone from the lake.

        The object becomes ``removed``. An object that is ``removed`` already stays as it is.
        A stored object is never deleted, so its row exists.
        """
        async with self._uow.transaction() as tx:
            await tx.attempts.lock_uploads([stored.upload_id])
            found = (await tx.objects.lock_uploads([stored.upload_id]))[stored.upload_id]
            if found.state is not ObjectState.REMOVED:
                await tx.objects.update(replace(found, state=ObjectState.REMOVED))
