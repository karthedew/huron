"""The API's hold on the lake: where API paths are, which marker guards them, and the gate.

Only the one writer of the lake (:mod:`huron.applications.api.disk.ownership`) passes the gate.

The lake is a ``hard`` NFS mount, so a disk call can block without end during an outage. All
disk work therefore runs in dedicated pools of worker threads, never in the event loop or the
default executor, and readiness waits for its probe only for a bounded time.
"""

from __future__ import annotations

import asyncio
import contextlib
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import timedelta
from typing import TYPE_CHECKING, Protocol

import structlog

from huron.core.storage import (
    FILE_MODE,
    MARKER_FILE,
    UPLOAD_DIR,
    UPLOAD_DIR_MODE,
    UPLOADS,
    LakePath,
    LakeUnavailable,
    OrganizationPlace,
    PathLocks,
    Publisher,
    StorageError,
    SymlinkInLake,
    verify_marker,
)

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, Mapping
    from datetime import datetime

    from huron.core.storage import Storage
    from huron.pkg.clock import Clock

__all__ = [
    "DISK_WORKERS",
    "PROBE_TIMEOUT",
    "PROBE_TTL",
    "LakeDisk",
    "Located",
    "Run",
    "Writer",
]

#: The worker threads of the disk pool, which runs every disk call.
DISK_WORKERS = 8
#: How long readiness waits for the lake probe, in seconds.
PROBE_TIMEOUT = 2.0
#: How long readiness keeps the probe's answer.
PROBE_TTL = timedelta(seconds=10)

_log = structlog.get_logger(__name__)


@dataclass(frozen=True, slots=True)
class Located:
    """A place on the lake and the organization it belongs to; a value with no disk methods."""

    place: OrganizationPlace
    location: LakePath

    def joinpath(self, *names: str) -> Located:
        """The place of ``names`` below this one, in the same organization."""
        return Located(self.place, self.location.joinpath(*names))


class Run(Protocol):
    """Run one action in the disk pool, after the marker of the held place is verified."""

    def __call__[T](self, action: Callable[[], T]) -> Awaitable[T]:
        """The action's result."""
        ...


class Writer(Protocol):
    """Whether this process is the one writer of the lake."""

    @property
    def writable(self) -> bool:
        """Whether this process can start a filesystem step now."""
        ...

    @property
    def lost(self) -> bool:
        """Whether this process was the writer and lost its lock."""
        ...


class LakeDisk:
    """The lake that this process alone writes, behind the one gate :meth:`hold`.

    ``places`` are the declared organizations; any other organization lies directly below the
    root and shares the marker there. The locks serialize the disk work of one place within
    this process. With ``writer``, only while ``writer`` is writable does the gate pass, and
    without it the gate always passes.
    """

    def __init__(
        self,
        storage: Storage,
        places: Mapping[str, OrganizationPlace],
        instance_id: str,
        *,
        clock: Clock,
        probe_timeout: float = PROBE_TIMEOUT,
        writer: Writer | None = None,
    ) -> None:
        self._storage = storage
        self._writer = writer
        self._publisher = Publisher(storage)
        self._places = dict(places)
        self._instance_id = instance_id
        self._clock = clock
        self._probe_timeout = probe_timeout
        self._locks = PathLocks()
        self._pool = ThreadPoolExecutor(DISK_WORKERS, thread_name_prefix="huron-disk")
        self._probe: asyncio.Future[bool] | None = None
        self._probed: tuple[datetime, bool] | None = None

    async def open(self) -> None:
        """Create the upload directory with mode ``0700`` when it is missing.

        Raises ``LAKE_UNAVAILABLE`` when the root does not open or this process cannot write it.
        """
        await self._submit(self._open)

    def close(self) -> None:
        """Stop the disk pool; work that has not started is dropped."""
        self._pool.shutdown(wait=False, cancel_futures=True)

    async def ready(self) -> bool:
        """Whether this process can write the upload directory and publish into each declared
        organization.

        The writer writes and removes a file in the upload directory, then makes and removes a
        real hard link from the object area into each declared organization directory
        (:meth:`Publisher.probe`), each after the marker check. A process that is not the
        writer writes nothing: it checks only that the upload directory is a directory. The
        answer is kept for :data:`PROBE_TTL`. A probe that does not answer within the
        timeout counts as ``False``; while it still runs, no second probe starts.
        """
        if self._writer is not None and self._writer.lost:
            return False
        now = self._clock.now()
        if self._probed is not None and now - self._probed[0] < PROBE_TTL:
            return self._probed[1]
        if self._probe is None or self._probe.done():
            self._probe = self._submit(self._probed_lake)
        try:
            ready = await asyncio.wait_for(asyncio.shield(self._probe), self._probe_timeout)
        except TimeoutError:
            ready = False
        self._probed = (now, ready)
        return ready

    def in_uploads(self, *names: str) -> Located:
        """The place of ``names`` in tusd's upload directory; no disk call.

        The marker at the lake's root guards the upload directory.
        """
        place = OrganizationPlace(UPLOAD_DIR, LakePath(), own_marker=False)
        return Located(place, UPLOADS.joinpath(*names))

    def locate(self, api_path: str) -> Located:
        """The place of an API path (``<organization>/…``); no disk call.

        Raises ``NAME_INVALID`` for a name that breaks the rule ``lake_name``.
        """
        organization = api_path.split("/")[0]
        place = self._places.get(organization) or OrganizationPlace(
            organization, LakePath.of(), own_marker=False
        )
        return Located(place, place.locate(api_path))

    async def hold[T](self, located: Located, unit: Callable[[Run], Awaitable[T]]) -> T:
        """Await ``unit`` while holding the lock of ``located``.

        ``unit`` gets a :class:`Run`, which verifies the organization's marker in the disk
        worker before each action. Between two actions the unit may await rows. The lock stays
        held until the unit ends, also when the caller is cancelled: a worker thread cannot be
        stopped, so the next unit on the place waits for it. An error the unit raises after its
        caller is cancelled goes to the log, because no caller is left.
        """
        place = located.place

        def run[R](action: Callable[[], R]) -> Awaitable[R]:
            return self._submit(lambda: self._checked(place, action))

        async with self._locks.hold(located.location):
            work = asyncio.ensure_future(unit(run))
            try:
                return await asyncio.shield(work)
            except asyncio.CancelledError:
                await _settled(work)
                if not work.cancelled() and (error := work.exception()) is not None:
                    _log.error(
                        "disk.cancelled_action_failed",
                        path=str(located.location),
                        error=repr(error),
                    )
                raise

    async def work[T](self, located: Located, action: Callable[[], T]) -> T:
        """Run one ``action`` on :meth:`hold`."""
        return await self.hold(located, lambda run: run(action))

    def _submit[T](self, action: Callable[[], T]) -> asyncio.Future[T]:
        return asyncio.get_running_loop().run_in_executor(self._pool, action)

    def _checked[T](self, place: OrganizationPlace, action: Callable[[], T]) -> T:
        if not self._writes():
            raise LakeUnavailable(
                "this API process does not hold the writer lock. Another API process writes"
                " the lake",
                {"reason": "writer_lock"},
            )
        organization = place.name if place.own_marker else None
        try:
            verify_marker(self._storage, place.marker_directory, self._instance_id, organization)
        except SymlinkInLake:
            raise
        except StorageError as error:
            raise LakeUnavailable(error.message, error.context) from error
        return action()

    def _open(self) -> None:
        try:
            self._storage.make_directory(UPLOADS, UPLOAD_DIR_MODE)
        except (LakeUnavailable, SymlinkInLake):
            raise
        except StorageError as error:
            raise LakeUnavailable(
                f"the API cannot write the lake: {error.message}", error.context
            ) from error

    def _writes(self) -> bool:
        return self._writer is None or self._writer.writable

    def _probed_lake(self) -> bool:
        if not self._writes():
            return self._uploads_directory()
        return self._writable() and all(self._linkable(place) for place in self._places.values())

    def _uploads_directory(self) -> bool:
        try:
            found = self._storage.stat(UPLOADS)
        except StorageError:
            return False
        return found is not None and found.kind == "dir"

    def _writable(self) -> bool:
        probe = UPLOADS.joinpath(f"{MARKER_FILE}-ready-{uuid.uuid4().hex}")
        if not self._uploads_directory():
            return False
        try:
            self._storage.write_bytes(probe, b"", FILE_MODE)
            self._storage.remove_file(probe)
        except StorageError:
            return False
        return True

    def _linkable(self, place: OrganizationPlace) -> bool:
        try:
            self._checked(place, lambda: self._publisher.probe(place))
        except StorageError:
            return False
        return True


async def _settled[T](work: asyncio.Future[T]) -> None:
    # A second cancellation must not end the wait either: the work still runs in its thread.
    while not work.done():
        with contextlib.suppress(asyncio.CancelledError):
            await asyncio.wait([work])
