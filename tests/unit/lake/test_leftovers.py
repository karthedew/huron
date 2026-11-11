"""Leftovers and the read of an attempt by upload ID, on both stores."""

from dataclasses import replace

import pytest

from huron.core.lake.uploads.errors import UploadNotFound
from huron.core.lake.uploads.leftovers import Leftovers
from huron.core.lake.uploads.models import AttemptState, ObjectState
from huron.pkg.identifiers import new_id
from tests.support.lake import CONTRIBUTOR
from tests.support.publication import Publishing

DATA = b"solar wind"


async def test_by_upload_reads_the_attempt_of_any_issued_id(publishing: Publishing) -> None:
    first = await publishing.receiving(CONTRIBUTOR, "a.cdf", DATA)
    current = await publishing.attempts.begin(
        CONTRIBUTOR, first.attempt_id, publishing.collection_id, "a.cdf", len(DATA)
    )
    assert await publishing.attempts.by_upload(first.current_upload_id) == current
    assert await publishing.attempts.by_upload(current.current_upload_id) == current
    unknown = new_id()
    with pytest.raises(UploadNotFound) as missing:
        await publishing.attempts.by_upload(unknown)
    assert missing.value.context == {"upload": str(unknown)}


async def test_spent_ids_are_the_ids_of_final_attempts_and_ids_that_are_not_current(
    publishing: Publishing,
) -> None:
    leftovers = Leftovers(publishing.store)
    receiving = await publishing.receiving(CONTRIBUTOR, "a.cdf", DATA)
    reissued = await publishing.attempts.begin(
        CONTRIBUTOR, receiving.attempt_id, publishing.collection_id, "a.cdf", len(DATA)
    )
    ready = await publishing.ready(CONTRIBUTOR, "b.cdf", DATA)
    cancelled = await publishing.receiving(CONTRIBUTOR, "c.cdf", DATA)
    await publishing.attempts.cancel(CONTRIBUTOR, cancelled.attempt_id)
    published = await publishing.commit(CONTRIBUTOR, 2, {"d.cdf": DATA})
    (consumed,) = [entry.upload_id for entry in await publishing.entries(published)]
    assert consumed is not None
    asked = [
        consumed,
        receiving.current_upload_id,
        reissued.current_upload_id,
        ready.current_upload_id,
        cancelled.current_upload_id,
        new_id(),
    ]
    assert await leftovers.spent(asked) == {
        consumed,
        receiving.current_upload_id,
        cancelled.current_upload_id,
    }
    assert await leftovers.spent([]) == set()


async def test_unreferenced_objects_page_and_a_removed_object_stays_removed(
    publishing: Publishing,
) -> None:
    leftovers = Leftovers(publishing.store)
    published = await publishing.commit(CONTRIBUTOR, 2, {"a.cdf": DATA})
    assert published.version == 3
    ready = await publishing.ready(CONTRIBUTOR, "b.cdf", DATA)
    ended = []
    for path in ("c.cdf", "d.cdf"):
        attempt = await publishing.ready(CONTRIBUTOR, path, DATA)
        ended.append(await publishing.attempts.cancel(CONTRIBUTOR, attempt.attempt_id))
    objects = sorted(
        [await publishing.stored(attempt.current_upload_id) for attempt in ended],
        key=lambda stored: stored.id,
    )
    assert await leftovers.unreferenced() == objects
    assert await leftovers.unreferenced(limit=1) == objects[:1]
    assert await leftovers.unreferenced(objects[0].id) == objects[1:]
    await leftovers.removed(objects[0])
    await leftovers.removed(objects[0])
    removed = replace(objects[0], state=ObjectState.REMOVED)
    assert await publishing.stored(objects[0].upload_id) == removed
    assert await leftovers.unreferenced() == objects[1:]
    assert (await publishing.attempt(ready)).state is AttemptState.READY
