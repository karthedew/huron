"""Upload attempts and commit requests over any store: ready uploads and published requests."""

import hashlib
import itertools
import uuid
from collections.abc import Iterator, Sequence
from dataclasses import dataclass, field
from datetime import timedelta

from huron.core.lake.bootstrap import Lake, bootstrap, build_lake
from huron.core.lake.collections.models import Collection
from huron.core.lake.files.models import FileRecord
from huron.core.lake.publications.models import CommitAdd, CommitEntry, CommitOutcome, CommitRequest
from huron.core.lake.publications.operations import Publications
from huron.core.lake.transaction import UnitOfWork
from huron.core.lake.uploads.attempts import Attempts
from huron.core.lake.uploads.models import StoredObject, UploadAttempt
from huron.core.security.rbac import Actor
from huron.pkg.clock import FrozenClock
from huron.pkg.identifiers import new_id
from tests.support.clock import frozen
from tests.support.lake import SETTINGS, seed_lake, settled_collection

TTL = timedelta(days=7)
OBJECT_DIR = ".huron-objects"


def sha256(data: bytes) -> str:
    """The lowercase hexadecimal sha256 of ``data``."""
    return hashlib.sha256(data).hexdigest()


@dataclass
class Publishing:
    """A seeded lake over one store, its clock, the two aggregates and an active collection.

    The collection is at version 2 with no file. Each sealed copy gets the next inode.
    """

    lake: Lake
    store: UnitOfWork
    clock: FrozenClock
    attempts: Attempts
    publications: Publications
    collection_id: uuid.UUID
    inodes: Iterator[int] = field(default_factory=lambda: itertools.count(100))

    async def receiving(
        self,
        author: Actor,
        rel_path: str,
        data: bytes,
        *,
        attempt_id: uuid.UUID | None = None,
    ) -> UploadAttempt:
        """A new ``receiving`` attempt of ``author`` to upload ``data`` to ``rel_path``."""
        return await self.attempts.begin(
            author, attempt_id or new_id(), self.collection_id, rel_path, len(data)
        )

    async def ready(self, author: Actor, rel_path: str, data: bytes) -> UploadAttempt:
        """A ``ready`` attempt of ``author`` whose sealed copy holds ``data``."""
        attempt = await self.receiving(author, rel_path, data)
        return await self.seal(attempt, data)

    async def seal(self, attempt: UploadAttempt, data: bytes) -> UploadAttempt:
        """Seal the current upload ID of ``attempt`` with a copy that holds ``data``."""
        upload_id = attempt.current_upload_id
        await self.attempts.start_seal(upload_id)
        inode = next(self.inodes)
        return await self.attempts.finish_seal(upload_id, len(data), sha256(data), inode)

    def request(
        self,
        base_version: int,
        adds: Sequence[tuple[UploadAttempt, bytes]] = (),
        removes: Sequence[str] = (),
        *,
        request_id: uuid.UUID | None = None,
    ) -> CommitRequest:
        """A request that adds each attempt's file with ``data`` and removes ``removes``."""
        return CommitRequest(
            request_id=request_id or new_id(),
            collection_id=self.collection_id,
            base_version=base_version,
            adds=tuple(
                CommitAdd(attempt.rel_path, len(data), sha256(data), attempt.current_upload_id)
                for attempt, data in adds
            ),
            removes=tuple(removes),
            host="host-1",
            message="a test commit",
        )

    async def publish(self, outcome: CommitOutcome) -> CommitOutcome:
        """Mark each entry of an accepted request done, then finalize the request."""
        for target in await self.publications.next_entries(outcome):
            await self.publications.mark_done(outcome, target.entry.ordinal)
        return await self.publications.finalize(outcome)

    async def commit(
        self,
        author: Actor,
        base_version: int,
        files: dict[str, bytes],
        removes: Sequence[str] = (),
    ) -> CommitOutcome:
        """Upload ``files``, then submit and publish one request with them and ``removes``."""
        adds = [(await self.ready(author, path, data), data) for path, data in files.items()]
        outcome = await self.publications.submit(author, self.request(base_version, adds, removes))
        return await self.publish(outcome)

    async def collection(self) -> Collection:
        """The collection row now."""
        async with self.store.transaction() as tx:
            found = await tx.collections.get(self.collection_id)
        assert found is not None
        return found

    async def files(self) -> dict[str, FileRecord]:
        """The recorded files of the collection, by path."""
        async with self.store.transaction() as tx:
            records = await tx.files.list(self.collection_id, None, 1000)
        return {record.rel_path: record for record in records}

    async def attempt(self, attempt: UploadAttempt) -> UploadAttempt:
        """The stored row of ``attempt`` now."""
        async with self.store.transaction() as tx:
            found = await tx.attempts.get(attempt.subject, attempt.attempt_id)
        assert found is not None
        return found

    async def stored(self, upload_id: uuid.UUID) -> StoredObject:
        """The object of ``upload_id``."""
        async with self.store.transaction() as tx:
            found = (await tx.objects.lock_uploads([upload_id]))[upload_id]
        return found

    async def entries(self, outcome: CommitOutcome) -> Sequence[CommitEntry]:
        """The stored entries of a request."""
        async with self.store.transaction() as tx:
            return await tx.commit_requests.entries(outcome.id)

    async def saved(self, outcome: CommitOutcome) -> CommitOutcome:
        """The stored row of a request now."""
        async with self.store.transaction() as tx:
            found = await tx.commit_requests.get(outcome.subject, outcome.request_id)
        assert found is not None
        return found


async def publishing_over(store: UnitOfWork) -> Publishing:
    """A :class:`Publishing` over the empty ``store``: bootstrapped, seeded, one collection."""
    clock = frozen()
    await bootstrap(store, clock, SETTINGS)
    lake = build_lake(store, clock, SETTINGS)
    await seed_lake(lake)
    return publishing_of(lake, store, clock, await settled_collection(lake))


def publishing_of(
    lake: Lake, store: UnitOfWork, clock: FrozenClock, collection_id: uuid.UUID
) -> Publishing:
    """A :class:`Publishing` for the collection ``collection_id`` of a lake that exists."""
    return Publishing(
        lake=lake,
        store=store,
        clock=clock,
        attempts=Attempts(store, clock, ttl=TTL, object_dir=OBJECT_DIR),
        publications=Publications(store, clock),
        collection_id=collection_id,
    )
