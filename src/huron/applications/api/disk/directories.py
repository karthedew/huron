"""The directory verbs: the disk work of a lake operation, after its commit.

A route passes the API path that the lake operation answered to one verb. Each verb locates the
path and does its work through :meth:`LakeDisk.hold`: under the path's lock, in the disk pool,
after the organization's marker. Without a lake, :class:`NoLake` does nothing, so every verb
changes only its rows.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

import structlog

from huron.core.storage import Outcome

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from huron.applications.api.disk.lake import LakeDisk, Run
    from huron.core.storage import DirectoryWriter, ShareWarning

__all__ = ["Directories", "LakeDirectories", "NoLake", "Render"]

type Render = Callable[[], Awaitable[bytes | None]]

_log = structlog.get_logger(__name__)


class Directories(Protocol):
    """The disk work of the directory verbs, on the API paths of directories."""

    async def make(self, path: str) -> None:
        """Make the directory, or adopt an empty one."""
        ...

    async def set_group(self, path: str, share_group: str | None) -> ShareWarning | None:
        """Try to give the catalog directory its share group, or the service group for ``None``.

        The answer is the ``SHARE_GROUP_PENDING`` warning when the group is not set.
        """
        ...

    async def write_metadata(self, path: str, render: Render) -> None:
        """Write the ``metadata.json`` that ``render`` gives, when its bytes differ.

        ``render`` reads the rows again under the path's lock; ``None`` writes nothing.
        """
        ...

    async def remove(self, path: str) -> None:
        """Remove the empty directory; one that is not empty stays."""
        ...

    async def remove_collection(self, path: str) -> None:
        """Remove what Huron put into the collection directory, then the directory."""
        ...


class LakeDirectories:
    """The directory verbs on the lake of ``disk``; ``writer`` does each verb's disk work.

    A directory that a removal keeps goes to the log as ``disk.directory_kept``.
    """

    def __init__(self, disk: LakeDisk, writer: DirectoryWriter) -> None:
        self._disk = disk
        self._writer = writer

    async def make(self, path: str) -> None:
        """Make the directory, or adopt an empty one; see :meth:`DirectoryWriter.make`."""
        located = self._disk.locate(path)
        await self._disk.work(located, lambda: self._writer.make(located.place, located.location))

    async def set_group(self, path: str, share_group: str | None) -> ShareWarning | None:
        """Try to give the catalog directory its group; the warning names the group by name or
        by number.
        """
        located = self._disk.locate(path)
        result = await self._disk.work(
            located, lambda: self._writer.set_group(located.location, share_group)
        )
        return result.warning(self._writer.group_for(share_group))

    async def write_metadata(self, path: str, render: Render) -> None:
        """Render under the path's lock, from a new read of the rows, and write when it differs.

        So two changes that commit in one order cannot write the file in the other order.
        """
        located = self._disk.locate(path)

        async def unit(run: Run) -> None:
            body = await render()
            if body is not None:
                await run(lambda: self._writer.write_metadata(located.location, body))

        await self._disk.hold(located, unit)

    async def remove(self, path: str) -> None:
        """Remove the empty directory; one that is not empty stays, with a warning in the log."""
        located = self._disk.locate(path)
        _logged(path, await self._disk.work(located, lambda: self._writer.remove(located.location)))

    async def remove_collection(self, path: str) -> None:
        """Clear and remove the collection directory; one that keeps entries stays, logged."""
        located = self._disk.locate(path)
        outcome = await self._disk.work(
            located, lambda: self._writer.remove_collection(located.location)
        )
        _logged(path, outcome)


class NoLake:
    """The directory verbs of a service without a lake: each returns at once."""

    async def make(self, path: str) -> None:
        """Do nothing."""

    async def set_group(self, path: str, share_group: str | None) -> ShareWarning | None:
        """Do nothing; there is no warning."""
        return None

    async def write_metadata(self, path: str, render: Render) -> None:
        """Do nothing; ``render`` is not called."""

    async def remove(self, path: str) -> None:
        """Do nothing."""

    async def remove_collection(self, path: str) -> None:
        """Do nothing."""


def _logged(path: str, outcome: Outcome) -> None:
    if outcome is Outcome.KEPT:
        _log.warning("disk.directory_kept", path=path)
