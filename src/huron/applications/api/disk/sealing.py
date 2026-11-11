"""Seals: one task for each upload ID copies a complete upload into its object area.

A seal starts from tusd's pre-finish hook (:meth:`Sealing.start`) or from the API's own check
(:meth:`Sealing.check`), which the client's read of its attempt and a commit run. tusd does not
always send the hook, so the check is necessary. One seal task runs for each upload ID, and a
second caller joins it. A check that finds a complete upload starts or joins that seal task. A
check that finds no complete upload holds no seal back: a hook that comes during the check
starts the seal. The tasks do not depend on their callers. They go on when the callers go away,
and a caller waits with :func:`~huron.applications.api.disk.tasks.wait_for`.

No transaction waits for the disk: a task reads the attempt, checks tusd's files, starts the
seal, copies the bytes and finishes the seal, each in its own step.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

import structlog

from huron.applications.api.disk.tasks import Tasks
from huron.core.lake.uploads.errors import UploadIneligible
from huron.core.lake.uploads.models import AttemptState
from huron.core.storage import Completeness

if TYPE_CHECKING:
    import uuid
    from collections.abc import Collection

    from huron.applications.api.disk.lake import LakeDisk
    from huron.core.lake.uploads.attempts import Attempts
    from huron.core.lake.uploads.models import UploadAttempt
    from huron.core.storage import Sealer

__all__ = ["SEAL_WAIT", "Sealing"]

#: How long tusd's pre-finish hook waits for a seal, in seconds. After it, the hook answers that
#: the upload is still sealing, and the client reads its attempt.
SEAL_WAIT = 20.0

_log = structlog.get_logger(__name__)

#: The states of an attempt whose current upload ID a seal can act on.
_SEALABLE = frozenset({AttemptState.RECEIVING, AttemptState.SEALING})


class Sealing:
    """Runs the seals of uploads on the lake of ``disk``, one seal task for each upload ID."""

    def __init__(self, disk: LakeDisk, attempts: Attempts, sealer: Sealer) -> None:
        self._disk = disk
        self._attempts = attempts
        self._sealer = sealer
        self._seals: Tasks[uuid.UUID, UploadAttempt] = Tasks("seal")
        self._checks: Tasks[uuid.UUID, UploadAttempt] = Tasks("seal check")

    def start(self, upload_id: uuid.UUID) -> asyncio.Task[UploadAttempt]:
        """The seal task of ``upload_id``, for tusd's pre-finish hook; a running one is joined.

        tusd sends the hook after the last byte, while it still holds the upload's lock file,
        so this seal does not look at the lock file. It checks the other conditions of a
        complete upload first. The task gives the attempt after the seal: ``ready``, or
        ``failed`` when tusd's files can never get the size of the attempt. When the upload is
        not complete yet, no seal starts and the task gives the attempt as it is.
        """
        return self._seals.start(upload_id, lambda: self._seal(upload_id))

    def check(self, upload_id: uuid.UUID) -> asyncio.Task[UploadAttempt]:
        """The task of the API's own seal check of ``upload_id``.

        A running seal task is joined. Otherwise the check task of the ID runs, and a second
        check joins it. It starts or joins the seal task only when tusd's files show a complete
        upload with no lock file (:meth:`Sealer.check`), and then gives the result of the seal.
        An upload with a lock file, a deferred length or a short data file is skipped, not
        failed: the task gives the attempt as it is. An upload whose files can never get the
        size of the attempt fails its attempt.
        """
        if self._seals.running(upload_id):
            return self.start(upload_id)
        return self._checks.start(upload_id, lambda: self._check(upload_id))

    async def settle(self, upload_ids: Collection[uuid.UUID], timeout: float) -> None:
        """Run the seal check of each of ``upload_ids``, and wait at most ``timeout`` seconds
        until all of them end.

        The wait cancels no check: a check that goes on after the wait ends later on its own.
        """
        checks = {self.check(upload_id) for upload_id in upload_ids}
        if checks:
            await asyncio.wait(checks, timeout=timeout)

    def running(self, upload_id: uuid.UUID) -> bool:
        """Whether a seal task or a check task of ``upload_id`` runs now."""
        return self._seals.running(upload_id) or self._checks.running(upload_id)

    async def has_info(self, upload_id: uuid.UUID) -> bool:
        """Whether tusd made the ``.info`` file of ``upload_id``: the fact that the creation of
        an upload attempt needs.
        """
        located = self._disk.in_uploads(str(upload_id))
        return await self._disk.work(located, lambda: self._sealer.has_info(upload_id))

    async def close(self) -> None:
        """Cancel the check tasks and the seal tasks and wait until each one ended."""
        await self._checks.close()
        await self._seals.close()

    async def _check(self, upload_id: uuid.UUID) -> UploadAttempt:
        stopped = await self._gate(upload_id, locked=True)
        if stopped is not None:
            return stopped
        # The seal goes on when this check is cancelled.
        return await asyncio.shield(self.start(upload_id))

    async def _seal(self, upload_id: uuid.UUID) -> UploadAttempt:
        """Seal the current upload ID of a ``receiving`` or ``sealing`` attempt.

        Raises ``UPLOAD_NOT_FOUND`` for an ID that Huron never issued, and a ``StorageError``
        when the disk fails: an attempt that the seal moved to ``sealing`` stays there, and the
        next check starts the seal again.
        """
        stopped = await self._gate(upload_id, locked=False)
        if stopped is not None:
            return stopped
        try:
            # The registry runs one seal task for each upload ID, so no other seal of this ID
            # runs in this process: a ``sealing`` attempt is one that a stopped process left.
            seal = await self._attempts.start_seal(upload_id, orphaned=True)
        except UploadIneligible:
            return await self._attempts.by_upload(upload_id)
        target = self._disk.locate(seal.stored.path)
        sealed = await self._disk.work(
            target, lambda: self._sealer.seal(upload_id, target.location, seal.size)
        )
        return await self._attempts.finish_seal(upload_id, sealed.size, sealed.sha256, sealed.inode)

    async def _gate(self, upload_id: uuid.UUID, *, locked: bool) -> UploadAttempt | None:
        """``None`` when a seal of ``upload_id`` can start now, else the attempt to give back.

        Only the current upload ID of a ``receiving`` or ``sealing`` attempt with complete
        files can be sealed. Files that can never get the size of the attempt fail it.
        """
        attempt = await self._attempts.by_upload(upload_id)
        if attempt.current_upload_id != upload_id or attempt.state not in _SEALABLE:
            return attempt
        located = self._disk.in_uploads(str(upload_id))
        found = await self._disk.work(
            located, lambda: self._sealer.check(upload_id, attempt.size, locked=locked)
        )
        if found.completeness is Completeness.COMPLETE:
            return None
        if found.received is not None:
            return await self._attempts.fail(upload_id, found.received)
        _log.info("seal.skipped", upload_id=str(upload_id), reason=str(found.completeness))
        return attempt
