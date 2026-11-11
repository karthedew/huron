"""Publication of accepted commit requests on the lake, and its recovery at startup.

The materializer does the entries of a pending request in their order. For each entry it turns
the entry into a step of :class:`~huron.core.storage.Publisher`, runs the step under the lock of
the entry's path after the marker check of the organization, and marks the entry done in its own
short transaction. When every entry is done, it finalizes the request. A step that finds an entry
that the request does not expect blocks the request. A storage error leaves the request pending
and gives no success: the task fails, and a later run does the entries that are not done.

One task runs for each request. The commit route starts it and waits at most
:data:`PUBLISH_WAIT` seconds with :func:`~huron.applications.api.disk.tasks.wait_for`. At startup
the API continues every ``accepted`` and ``blocked`` request, and its periodic loop continues
every ``accepted`` request that has no task. A platform administrator continues a ``blocked``
request with a retry.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from huron.applications.api.disk.tasks import Tasks
from huron.core.lake.publications.errors import PublicationBlocked
from huron.core.lake.publications.models import CommitState, EntryAction, Refusal
from huron.core.storage import (
    AddFile,
    BlockReason,
    MakeDirectory,
    PruneDirectory,
    RemoveDirectory,
    RemoveFile,
    StepResult,
)

if TYPE_CHECKING:
    import asyncio
    import uuid

    from huron.applications.api.disk.lake import LakeDisk, Located
    from huron.core.lake.publications.models import CommitOutcome, EntryTarget
    from huron.core.lake.publications.operations import Publications
    from huron.core.storage import Publisher, Step

__all__ = ["PUBLISH_WAIT", "Materializer"]

#: How long the commit route waits for a publication, in seconds, before it answers 202.
PUBLISH_WAIT = 5.0


class Materializer:
    """Publishes pending requests of ``publications`` on the lake of ``disk``."""

    def __init__(self, disk: LakeDisk, publications: Publications, publisher: Publisher) -> None:
        self._disk = disk
        self._publications = publications
        self._publisher = publisher
        self._tasks: Tasks[uuid.UUID, CommitOutcome] = Tasks("publication")

    def start(self, outcome: CommitOutcome) -> asyncio.Task[CommitOutcome]:
        """The publication task of the request ``outcome``; a second caller joins it.

        The task gives the request after the run: ``succeeded``, ``blocked``, or unchanged
        when it was not pending. A retry that an administrator asks for starts the task of the
        request that :meth:`Publications.resolve` gives.
        """
        return self._tasks.start(outcome.id, lambda: self._publish(outcome))

    async def recover_pending(self) -> list[asyncio.Task[CommitOutcome]]:
        """Start the task of every ``accepted`` and ``blocked`` request, the oldest first.

        The API calls this at startup. A blocked request runs the same steps: a step that is
        still blocked blocks the request again, and a request whose entries are all done is
        finalized.
        """
        return [self.start(outcome) for outcome in await self._publications.pending()]

    async def resume_accepted(self) -> list[asyncio.Task[CommitOutcome]]:
        """Start the task of every ``accepted`` request, the oldest first.

        The API calls this in its periodic loop, so that a transient storage error does not
        hold a collection until a restart. A request whose task runs is joined, not started two
        times. A ``blocked`` request is not continued: it waits for a platform administrator.
        """
        return [
            self.start(outcome)
            for outcome in await self._publications.pending()
            if outcome.state is CommitState.ACCEPTED
        ]

    async def close(self) -> None:
        """Cancel the publication tasks and wait until each one ended."""
        await self._tasks.close()

    async def _publish(self, outcome: CommitOutcome) -> CommitOutcome:
        for target in await self._publications.next_entries(outcome):
            blocked = await self._apply(target)
            if blocked is not None:
                return await self._publications.block(outcome, Refusal.of(blocked))
            await self._publications.mark_done(outcome, target.entry.ordinal)
        return await self._publications.finalize(outcome)

    async def _apply(self, target: EntryTarget) -> PublicationBlocked | None:
        """Run the step of ``target``; the refusal that blocks the request, or ``None``."""
        located = self._disk.locate(target.path)
        step = self._step(target, located)
        if isinstance(step, StepResult):
            result = step
        else:
            result = await self._disk.work(located, lambda: self._publisher.apply(step))
        if result.done:
            return None
        return PublicationBlocked(
            target.entry.ordinal, str(result.reason), str(result.path), result.detail
        )

    def _step(self, target: EntryTarget, located: Located) -> Step | StepResult:
        """The step of ``target`` at ``located``, or the result that blocks it at once.

        A removal of a file whose inode Huron never learned cannot tell that file from another
        file, so it blocks the request with ``inode_unknown``.
        """
        entry, location = target.entry, located.location
        match entry.action:
            case EntryAction.ADD_FILE:
                stored = target.source
                assert stored is not None and stored.inode is not None
                source = self._disk.locate(stored.path).location
                return AddFile(source, location, stored.inode, target.old_inode, stored.upload_id)
            case EntryAction.REMOVE_FILE:
                if target.old_inode is None:
                    return StepResult.blocked(BlockReason.INODE_UNKNOWN, location)
                return RemoveFile(location, target.old_inode)
            case EntryAction.MAKE_DIRECTORY:
                return MakeDirectory(location)
            case EntryAction.REMOVE_DIRECTORY:
                return RemoveDirectory(location)
            case _:
                return PruneDirectory(location)
