"""Upload attempts: create them, seal their bytes, cancel and expire them.

The API calls these for tusd's hooks, for its own seal check and for its cleanup. ``begin``,
``cancel`` and ``get`` act for the uploading user. ``start_seal``, ``finish_seal`` and ``expire``
record the API's own work, so they take no actor. No operation touches the filesystem: the
caller gives each fact that only the filesystem knows.

Every transaction takes its row locks in one order: the collection row, the commit request row,
the upload attempt rows, then the object rows. ``begin`` locks the collection before the attempt,
so a collection delete at the same time either finds the new attempt or makes ``begin`` fail
with the collection's not-found error. The other operations lock the attempt row, and the seals
the object row after it.

An attempt expires ``ttl`` after its last activity: an allowed ``PATCH`` or the end of a seal.
``expire`` marks the lapsed attempts ``expired``. ``begin`` and ``start_seal`` also mark the
attempt that they act on ``expired`` when it lapsed, before they decide, and they commit that
mark also when they then refuse. ``finish_seal``, ``cancel`` and ``get`` do not look at the
time.
"""

from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING

from huron.core.lake.lookups import find_collection, require_file_writer
from huron.core.lake.uploads.errors import (
    AttemptIdConflict,
    CapacityExceeded,
    IneligibleReason,
    UploadAttemptRefused,
    UploadIneligible,
    UploadNotFound,
    UploadSizeMismatch,
    UploadTooLarge,
)
from huron.core.lake.uploads.models import (
    AttemptState,
    Failure,
    ObjectState,
    Seal,
    StoredObject,
    UploadAttempt,
)
from huron.core.security.rbac import Authorizer
from huron.pkg.errors import Conflict, HuronError, Invalid, NotFound
from huron.pkg.identifiers import new_id
from huron.pkg.paging import clamp_limit
from huron.schema.naming import check_rel_path

if TYPE_CHECKING:
    import uuid
    from datetime import datetime, timedelta

    from huron.core.lake.transaction import Transaction, UnitOfWork
    from huron.core.security.rbac import Actor
    from huron.pkg.clock import Clock

__all__ = ["Attempts"]


class Attempts:
    """The upload attempt aggregate's operations.

    ``ttl`` is how long an idle attempt lives after its last activity. ``object_dir`` is the
    name of the object area in each organization directory: the object of an upload ID is
    ``<organization>/<object_dir>/<upload ID>``. ``max_upload_bytes`` is the largest upload and
    ``max_staged_bytes`` the most bytes that the staged attempts can use, with the bytes of each
    attempt counted two times for the tusd file and its copy. ``0`` is no limit.
    """

    def __init__(
        self,
        uow: UnitOfWork,
        clock: Clock,
        *,
        ttl: timedelta,
        object_dir: str,
        max_upload_bytes: int = 0,
        max_staged_bytes: int = 0,
    ) -> None:
        self._uow = uow
        self._clock = clock
        self._ttl = ttl
        self._object_dir = object_dir
        self._max_upload_bytes = max_upload_bytes
        self._max_staged_bytes = max_staged_bytes

    async def begin(
        self,
        actor: Actor,
        attempt_id: uuid.UUID,
        collection_id: uuid.UUID,
        rel_path: str,
        size: int,
        *,
        with_info: uuid.UUID | None = None,
    ) -> UploadAttempt:
        """Issue an upload ID for the actor's attempt to upload ``size`` bytes to ``rel_path``.

        ``with_info`` is the upload ID of this attempt whose tusd ``.info`` file the caller
        found, ``None`` when it found none. Under the lock of the attempt row, the first case
        that matches decides:

        1. No attempt has the key: make it ``receiving`` with a new upload ID.
        2. The attempt is for another collection, path or size: :class:`AttemptIdConflict`.
        3. The attempt is ``receiving`` and its current ID is ``with_info``:
           :class:`UploadAttemptRefused` that names the current ID to continue.
        4. The attempt is ``receiving`` otherwise: a new upload ID becomes the current ID.
        5. and 6. The attempt is in another state: :class:`UploadAttemptRefused` with the state.

        A fact about an ID that is no longer current gives case 4. Huron never issues one upload
        ID two times. The actor needs ``COLLECTION_WRITE_FILES`` on a collection that takes
        files. A ``size`` above ``max_upload_bytes`` is :class:`UploadTooLarge` in each case,
        before any row is read. A new attempt that does not fit in ``max_staged_bytes`` is
        :class:`CapacityExceeded`. The caller checks the free space of the filesystems.
        """
        check_rel_path(rel_path)
        if size < 0:
            raise Invalid("the size must be 0 or more", {"size": size})
        if self._max_upload_bytes and size > self._max_upload_bytes:
            raise UploadTooLarge(size, self._max_upload_bytes)
        async with self._uow.transaction() as tx:
            authz = Authorizer(tx.grants)
            collection, catalog = await find_collection(
                tx, authz, actor, collection_id=collection_id, lock=True
            )
            await require_file_writer(authz, actor, collection, catalog, "upload")
            candidate = self._new_attempt(actor, attempt_id, collection_id, rel_path, size)
            attempt = await tx.attempts.insert_or_lock(candidate)
            if attempt.id == candidate.id:
                await self._check_staged(tx, size)
                return attempt
            if not attempt.has_fields(collection_id, rel_path, size):
                raise AttemptIdConflict(attempt_id)
            result = await self._reissue(tx, attempt, with_info)
        return _raised(result)

    async def start_seal(self, upload_id: uuid.UUID, *, orphaned: bool = False) -> Seal:
        """Start the seal of ``upload_id``: its attempt becomes ``sealing``.

        A seal starts only for the current upload ID of a ``receiving`` attempt. ``orphaned``
        says that the attempt is ``sealing`` and this process runs no seal task for it, after a
        stop of the API during a seal: that seal starts again. A seal that runs again has the
        object row of its first run. Raises :class:`UploadNotFound` for an ID that Huron never
        issued, :class:`UploadIneligible` for an attempt in another state or an ID that is not
        current, and :class:`NotFound` when the collection of the attempt is deleted.
        """
        async with self._uow.transaction() as tx:
            result = await self._start(tx, upload_id, orphaned)
        return _raised(result)

    async def finish_seal(
        self, upload_id: uuid.UUID, size: int, sha256: str, inode: int
    ) -> UploadAttempt:
        """Record the measured copy of ``upload_id``: its ``size``, ``sha256`` and ``inode``.

        A ``sealing`` attempt becomes ``ready``, or ``failed`` when ``size`` is not its size, and
        the end of the seal is its last activity. An attempt that a cancel or an expiry ended
        during the seal stays as it is: its object is only private bytes to remove. A seal that
        ends two times changes nothing the second time. Raises :class:`UploadNotFound` for an
        ID that has no started seal.
        """
        now = self._clock.now()
        async with self._uow.transaction() as tx:
            attempt = (await tx.attempts.lock_uploads([upload_id])).get(upload_id)
            stored = (await tx.objects.lock_uploads([upload_id])).get(upload_id)
            if attempt is None or stored is None:
                raise UploadNotFound(upload_id)
            if stored.state is not ObjectState.SEALING:
                return attempt
            sealed = replace(
                stored,
                state=ObjectState.SEALED,
                size=size,
                sha256=sha256,
                inode=inode,
                sealed_at=now,
            )
            await tx.objects.update(sealed)
            if attempt.state is not AttemptState.SEALING:
                return attempt
            finished = _finished(attempt, size, now)
            await tx.attempts.update(finished)
            return finished

    async def cancel(self, actor: Actor, attempt_id: uuid.UUID) -> UploadAttempt:
        """End the actor's attempt that no commit uses; the attempt becomes ``cancelled``.

        The caller then removes the tusd files of every upload ID of the attempt. An attempt that
        ended already stays as it is. Raises :class:`Conflict` when a commit request holds or
        consumed the attempt.
        """
        async with self._uow.transaction() as tx:
            attempt = await _locked(tx, actor, attempt_id)
            if attempt.state.ended:
                return attempt
            if attempt.commit_request_id is not None:
                raise Conflict(
                    "a commit uses the upload attempt. You cannot cancel it",
                    {
                        "attempt_id": str(attempt_id),
                        "state": str(attempt.state),
                        "allowed": [str(state) for state in _CANCELLABLE],
                    },
                )
            cancelled = replace(attempt, state=AttemptState.CANCELLED)
            await tx.attempts.update(cancelled)
            return cancelled

    async def expire(self, limit: int | None = None) -> list[UploadAttempt]:
        """Mark up to ``limit`` lapsed attempts ``expired``, the oldest activity first.

        A lapsed attempt is ``receiving`` or ``sealing``, or ``ready`` and held by no commit
        request, and its last activity is more than ``ttl`` ago. An attempt that another
        transaction holds locked waits for the next run. The caller removes the files of the
        expired attempts.
        """
        before = self._clock.now() - self._ttl
        async with self._uow.transaction() as tx:
            lapsed = await tx.attempts.lock_idle(before, clamp_limit(limit))
            expired = [replace(attempt, state=AttemptState.EXPIRED) for attempt in lapsed]
            for attempt in expired:
                await tx.attempts.update(attempt)
            return expired

    async def get(self, actor: Actor, attempt_id: uuid.UUID) -> UploadAttempt:
        """The actor's attempt with ``attempt_id``; another actor's attempt is not found."""
        async with self._uow.transaction() as tx:
            return _found(await tx.attempts.get(actor.subject, attempt_id), attempt_id)

    def _new_attempt(
        self,
        actor: Actor,
        attempt_id: uuid.UUID,
        collection_id: uuid.UUID,
        rel_path: str,
        size: int,
    ) -> UploadAttempt:
        now = self._clock.now()
        upload_id = new_id()
        return UploadAttempt(
            id=new_id(),
            subject=actor.subject,
            attempt_id=attempt_id,
            collection_id=collection_id,
            rel_path=rel_path,
            size=size,
            state=AttemptState.RECEIVING,
            current_upload_id=upload_id,
            upload_ids=(upload_id,),
            created_at=now,
            active_at=now,
        )

    async def _check_staged(self, tx: Transaction, size: int) -> None:
        """Refuse a new attempt of ``size`` bytes when the staged bytes with it do not fit."""
        if not self._max_staged_bytes:
            return
        staged = await tx.attempts.staged_bytes()
        if 2 * staged > self._max_staged_bytes:
            available = max(0, self._max_staged_bytes - 2 * (staged - size))
            raise CapacityExceeded("max_staged_bytes", 2 * size, available)

    async def _reissue(
        self, tx: Transaction, attempt: UploadAttempt, with_info: uuid.UUID | None
    ) -> UploadAttempt | HuronError:
        """Cases 3 to 6 of :meth:`begin` for an attempt with the fields of the creation."""
        attempt = await self._unless_lapsed(tx, attempt)
        if attempt.state is not AttemptState.RECEIVING or attempt.current_upload_id == with_info:
            return UploadAttemptRefused(attempt)
        await tx.attempts.issue(attempt.id, new_id(), self._clock.now())
        reissued = await tx.attempts.get(attempt.subject, attempt.attempt_id)
        return _found(reissued, attempt.attempt_id)

    async def _start(
        self, tx: Transaction, upload_id: uuid.UUID, orphaned: bool
    ) -> Seal | HuronError:
        attempt = (await tx.attempts.lock_uploads([upload_id])).get(upload_id)
        if attempt is None:
            raise UploadNotFound(upload_id)
        attempt = await self._unless_lapsed(tx, attempt)
        refusal = _seal_refusal(attempt, upload_id, orphaned)
        if refusal is not None:
            return refusal
        organization = await _organization(tx, attempt)
        sealing = replace(attempt, state=AttemptState.SEALING)
        await tx.attempts.update(sealing)
        stored = await tx.objects.insert_or_lock(
            StoredObject(
                id=new_id(),
                upload_id=upload_id,
                path=f"{organization}/{self._object_dir}/{upload_id}",
                state=ObjectState.SEALING,
                created_at=self._clock.now(),
            )
        )
        return Seal(sealing, stored)

    async def _unless_lapsed(self, tx: Transaction, attempt: UploadAttempt) -> UploadAttempt:
        """``attempt``, or the attempt marked ``expired`` when it lapsed."""
        if not attempt.lapsed(self._clock.now() - self._ttl):
            return attempt
        expired = replace(attempt, state=AttemptState.EXPIRED)
        await tx.attempts.update(expired)
        return expired


_CANCELLABLE = (AttemptState.RECEIVING, AttemptState.SEALING, AttemptState.READY)


def _raised[T](result: T | HuronError) -> T:
    """``result``, or raise it when it is the refusal that the transaction committed."""
    if isinstance(result, HuronError):
        raise result
    return result


def _found(attempt: UploadAttempt | None, attempt_id: uuid.UUID) -> UploadAttempt:
    if attempt is None:
        raise NotFound("upload attempt not found", {"attempt_id": str(attempt_id)})
    return attempt


async def _locked(tx: Transaction, actor: Actor, attempt_id: uuid.UUID) -> UploadAttempt:
    """The actor's attempt, locked: by its current upload ID, which no other attempt has."""
    found = _found(await tx.attempts.get(actor.subject, attempt_id), attempt_id)
    locked = await tx.attempts.lock_uploads([found.current_upload_id])
    return locked[found.current_upload_id]


def _seal_refusal(
    attempt: UploadAttempt, upload_id: uuid.UUID, orphaned: bool
) -> UploadIneligible | None:
    if attempt.current_upload_id != upload_id:
        return UploadIneligible(upload_id, attempt.state, IneligibleReason.SUPERSEDED, sealing=True)
    if attempt.state is AttemptState.RECEIVING or (
        orphaned and attempt.state is AttemptState.SEALING
    ):
        return None
    return UploadIneligible(upload_id, attempt.state, sealing=True)


async def _organization(tx: Transaction, attempt: UploadAttempt) -> str:
    """The name of the organization of the attempt's collection."""
    if attempt.collection_id is None:
        raise NotFound(
            "the collection of the upload does not exist",
            {"upload_id": str(attempt.current_upload_id)},
        )
    collection = await tx.collections.get(attempt.collection_id)
    assert collection is not None
    catalog = await tx.catalogs.get(collection.catalog_id)
    assert catalog is not None
    organization = await tx.organizations.get(catalog.organization_id)
    assert organization is not None
    return organization.name


def _finished(attempt: UploadAttempt, size: int, now: datetime) -> UploadAttempt:
    """The attempt after its seal ends at ``now`` with a copy of ``size`` bytes."""
    if size != attempt.size:
        mismatch = UploadSizeMismatch(attempt.size, size)
        failure = Failure(mismatch.code, mismatch.message)
        return replace(attempt, state=AttemptState.FAILED, failure=failure, active_at=now)
    return replace(attempt, state=AttemptState.READY, active_at=now)
