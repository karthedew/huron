"""The orchestration of uploads on an in-memory lake: tusd's files, seals and publications."""

import json
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any

from huron.applications.api.disk import (
    Capacity,
    Cleanup,
    LakeDisk,
    Materializer,
    Sealing,
    Writer,
)
from huron.core.lake.transaction import UnitOfWork
from huron.core.lake.uploads.leftovers import Leftovers
from huron.core.lake.uploads.models import UploadAttempt
from huron.core.metastore.store import MemoryStore
from huron.core.security.rbac import Actor
from huron.core.storage import (
    DIRECTORY_MODE,
    UPLOAD_DIR_MODE,
    UPLOADS,
    LakePath,
    Publisher,
    Sealer,
)
from huron.core.storage.memory import MemoryStorage
from tests.support.disk import lake_disk, memory_lake
from tests.support.lake import CONTRIBUTOR
from tests.support.publication import Publishing, publishing_over

#: The directory of the collection ``run7`` of the seeded lake.
COLLECTION = LakePath.of("helio", "heliophysics", "solar-wind", "run7")
#: The organization directory of the seeded lake.
ORGANIZATION = LakePath.of("helio")
#: The object area of the organization.
OBJECTS = ORGANIZATION.joinpath(".huron-objects")


def collection_lake() -> MemoryStorage:
    """An in-memory lake with ``.tus-uploads`` and the directories of the collection ``run7``."""
    storage = memory_lake()
    storage.make_directory(UPLOADS, UPLOAD_DIR_MODE)
    for depth in range(1, len(COLLECTION.names) + 1):
        storage.make_directory(LakePath(COLLECTION.names[:depth]), DIRECTORY_MODE)
    return storage


def tus_file(upload_id: uuid.UUID, suffix: str = "") -> LakePath:
    """The tusd file of ``upload_id``: the data file, or the file with ``suffix``."""
    return UPLOADS.joinpath(f"{upload_id}{suffix}")


def receive(
    storage: MemoryStorage,
    upload_id: uuid.UUID,
    data: bytes,
    *,
    info: dict[str, Any] | None = None,
    locked: bool = False,
) -> None:
    """Write the files that tusd keeps for a complete upload of ``data``.

    ``info`` replaces the fields of the ``.info`` file, and ``locked`` adds a ``.lock`` file.
    """
    document = {"ID": str(upload_id), "Size": len(data), "SizeIsDeferred": False, "Offset": 0}
    storage.write_bytes(tus_file(upload_id), data, 0o600)
    storage.write_bytes(tus_file(upload_id, ".info"), json.dumps(info or document).encode(), 0o600)
    if locked:
        storage.write_bytes(tus_file(upload_id, ".lock"), b"1", 0o600)


@dataclass
class Bench:
    """The aggregates of a seeded store, an in-memory lake and the orchestration on it."""

    publishing: Publishing
    storage: MemoryStorage
    disk: LakeDisk
    sealing: Sealing
    materializer: Materializer
    capacity: Capacity
    cleanup: Cleanup

    async def received(self, path: str, data: bytes, author: Actor = CONTRIBUTOR) -> UploadAttempt:
        """A ``receiving`` attempt of ``author`` for ``path`` whose tusd files are complete."""
        attempt = await self.publishing.receiving(author, path, data)
        receive(self.storage, attempt.current_upload_id, data)
        return attempt

    async def sealed(self, path: str, data: bytes, author: Actor = CONTRIBUTOR) -> UploadAttempt:
        """A ``ready`` attempt whose object on the lake holds ``data``."""
        attempt = await self.received(path, data, author)
        return await self.sealing.start(attempt.current_upload_id)


@asynccontextmanager
async def bench(
    store: UnitOfWork | None = None,
    *,
    storage: MemoryStorage | None = None,
    writer: Writer | None = None,
    min_free_bytes: int = 0,
) -> AsyncIterator[Bench]:
    """A :class:`Bench` over ``store`` (a new in-memory store by default) and ``storage``.

    The organization ``helio`` is not declared, so the marker at the lake's root guards it.
    ``writer`` says whether this process writes. The tasks and the disk pools are closed at
    the end.
    """
    publishing = await publishing_over(store or MemoryStore())
    lake = storage or collection_lake()
    disk = lake_disk(lake, publishing.clock, writer=writer)
    sealer = Sealer(lake)
    sealing = Sealing(disk, publishing.attempts, sealer)
    materializer = Materializer(disk, publishing.publications, Publisher(lake))
    built = Bench(
        publishing=publishing,
        storage=lake,
        disk=disk,
        sealing=sealing,
        materializer=materializer,
        capacity=Capacity(disk, lake, min_free_bytes),
        cleanup=Cleanup(
            disk, lake, publishing.attempts, Leftovers(publishing.store), sealing, sealer
        ),
    )
    try:
        yield built
    finally:
        await sealing.close()
        await materializer.close()
        disk.close()
