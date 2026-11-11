"""The free-space limit of a new upload: one filesystem for ``.tus-uploads`` and the object
area, or one filesystem for each."""

from collections.abc import AsyncIterator

import pytest

from huron.core.lake.uploads.errors import CapacityExceeded
from huron.core.storage import MARKER_FILE, UPLOADS, LakePath, LakeUnavailable, StorageError
from tests.support.orchestration import ORGANIZATION, Bench, bench, collection_lake

RESERVE = 100


@pytest.fixture
async def lab() -> AsyncIterator[Bench]:
    """``.tus-uploads`` and ``helio`` on two filesystems, with ``min_free_bytes`` 100."""
    storage = collection_lake()
    storage.mounts |= {UPLOADS, ORGANIZATION}
    storage.free.update({UPLOADS: 1000, ORGANIZATION: 1000})
    async with bench(storage=storage, min_free_bytes=RESERVE) as built:
        yield built


async def test_one_filesystem_for_both_sides_needs_the_upload_two_times() -> None:
    storage = collection_lake()
    storage.free[LakePath()] = 1000
    async with bench(storage=storage, min_free_bytes=RESERVE) as one:
        await one.capacity.admit("helio", 450)
        with pytest.raises(CapacityExceeded) as refused:
            await one.capacity.admit("helio", 451)
    assert refused.value.context == {
        "limit": "min_free_bytes",
        "requested": 902,
        "available": 900,
    }


async def test_an_upload_that_keeps_the_reserve_on_both_filesystems_fits(lab: Bench) -> None:
    await lab.capacity.admit("helio", 900)
    lab.storage.free.update({UPLOADS: 150, ORGANIZATION: 150})
    await lab.capacity.admit("helio", 50)
    await lab.capacity.admit("helio", 0)


@pytest.mark.parametrize("full", [UPLOADS, ORGANIZATION])
async def test_a_full_filesystem_on_either_side_refuses(lab: Bench, full: LakePath) -> None:
    lab.storage.free[full] = 149
    with pytest.raises(CapacityExceeded) as refused:
        await lab.capacity.admit("helio", 50)
    assert refused.value.context == {"limit": "min_free_bytes", "requested": 50, "available": 49}
    assert refused.value.message == (
        "the upload needs 50 bytes, but min_free_bytes permits only 49 bytes."
        " Send the upload again later"
    )


async def test_a_filesystem_below_the_reserve_permits_no_byte(lab: Bench) -> None:
    lab.storage.free[ORGANIZATION] = 10
    with pytest.raises(CapacityExceeded) as refused:
        await lab.capacity.admit("helio", 0)
    assert refused.value.context["available"] == 0


async def test_an_organization_without_a_directory_or_a_marker_gives_no_answer(
    lab: Bench,
) -> None:
    with pytest.raises(StorageError) as missing:
        await lab.capacity.admit("geo", 1)
    assert missing.value.context == {"path": "geo"}
    lab.storage.remove_file(LakePath.of(MARKER_FILE))
    with pytest.raises(LakeUnavailable):
        await lab.capacity.admit("helio", 1)
