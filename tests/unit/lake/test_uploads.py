"""Uploads: begin, placement, receipts, failures, termination and the removal outbox."""

import uuid
from dataclasses import replace
from datetime import timedelta

import pytest

from huron.core.lake.files.models import CommitRequest, FileAdd, FileRecord
from huron.core.lake.uploads.errors import (
    UploadNotFound,
    UploadSizeMismatch,
    UploadStateConflict,
    UploadTooLarge,
)
from huron.core.lake.uploads.models import Destination, Failure, Removal, Upload, UploadState
from huron.core.lake.uploads.operations import REMOVAL_LEASE
from huron.core.security.rbac import Role
from huron.pkg.errors import Conflict, Forbidden, Invalid, NotFound
from huron.pkg.identifiers import new_id
from huron.pkg.paging import DEFAULT_LIMIT, MAXIMUM_LIMIT
from huron.schema.naming import RelPathError
from tests.support.clock import START
from tests.support.lake import (
    CATALOG_ADMIN,
    CONTRIBUTOR,
    OTHER_CONTRIBUTOR,
    READER,
    SETTINGS,
    STRANGER,
    VALID_METADATA,
    World,
    commit_uploaded,
    make_world,
    placed_upload,
    seed,
    settled_collection,
)

SHA = "d" * 64
OTHER_SHA = "e" * 64
PATH = "solar/day1.cdf"
INODE = 7340


@pytest.fixture
async def pending(seeded: World, collection_id: uuid.UUID) -> Upload:
    """A pending upload of the contributor to :data:`PATH`, 10 bytes long."""
    return await seeded.lake.uploads.begin(CONTRIBUTOR, collection_id, PATH, 10)


@pytest.fixture
async def removal_id(seeded: World, collection_id: uuid.UUID) -> uuid.UUID:
    """A queued removal of ``a.txt``, which a commit recorded and then removed."""
    return await _queue_removal(seeded, collection_id, "a.txt")


@pytest.fixture
async def orphan_id(seeded: World, collection_id: uuid.UUID, removal_id: uuid.UUID) -> uuid.UUID:
    """The queued removal of ``a.txt`` after its collection was deleted."""
    await seeded.lake.collections.delete(CONTRIBUTOR, collection_id, 4)
    return removal_id


@pytest.fixture
async def backlog(seeded: World) -> list[Removal]:
    """More queued removals than one claim may take."""
    removals = [
        Removal(new_id(), None, f"helio/c/n/r/{i}", str(i), str(i), SHA, None, START)
        for i in range(MAXIMUM_LIMIT + 1)
    ]
    async with seeded.store.transaction() as tx:
        await tx.uploads.insert_removals(removals)
    return removals


async def test_begin_stores_a_pending_upload(seeded: World, collection_id: uuid.UUID) -> None:
    upload = await seeded.lake.uploads.begin(CONTRIBUTOR, collection_id, "Solar/Day1.cdf", 10)
    assert (upload.rel_path, upload.rel_path_key, upload.size) == (
        "Solar/Day1.cdf",
        "solar/day1.cdf",
        10,
    )
    assert (upload.state, upload.created_by, upload.created_at) == (
        UploadState.PENDING,
        CONTRIBUTOR.subject,
        START,
    )
    assert (upload.sha256, upload.failure, upload.placed_at, upload.commit_id) == (
        None,
        None,
        None,
        None,
    )
    assert seeded.store.state.uploads[upload.id] == upload


async def test_begin_accepts_an_empty_file_and_any_size_without_a_maximum(
    seeded: World, collection_id: uuid.UUID
) -> None:
    empty = await seeded.lake.uploads.begin(CONTRIBUTOR, collection_id, "empty", 0)
    huge = await seeded.lake.uploads.begin(CONTRIBUTOR, collection_id, "huge", 2**50)
    assert (empty.size, huge.size) == (0, 2**50)


async def test_begin_refuses_a_bad_path_and_a_negative_size(
    seeded: World, collection_id: uuid.UUID
) -> None:
    with pytest.raises(RelPathError) as bad_path:
        await seeded.lake.uploads.begin(CONTRIBUTOR, collection_id, "../escape", 1)
    assert bad_path.value.rule == "rel_path_separator"
    with pytest.raises(Invalid) as negative:
        await seeded.lake.uploads.begin(CONTRIBUTOR, collection_id, "a", -1)
    assert negative.value.context == {"size": -1}
    assert seeded.store.state.uploads == {}


async def test_begin_refuses_an_upload_larger_than_the_maximum() -> None:
    world = await make_world(replace(SETTINGS, upload_max_size=100))
    await seed(world)
    collection_id = await settled_collection(world.lake)
    largest = await world.lake.uploads.begin(CONTRIBUTOR, collection_id, "a", 100)
    assert largest.size == 100
    with pytest.raises(UploadTooLarge) as raised:
        await world.lake.uploads.begin(CONTRIBUTOR, collection_id, "b", 101)
    assert (raised.value.status, raised.value.context) == (413, {"size": 101, "maximum": 100})


async def test_begin_needs_the_right_to_write_files(
    seeded: World, collection_id: uuid.UUID
) -> None:
    with pytest.raises(Forbidden):
        await seeded.lake.uploads.begin(READER, collection_id, "a", 1)
    with pytest.raises(NotFound):
        await seeded.lake.uploads.begin(STRANGER, collection_id, "a", 1)
    with pytest.raises(NotFound):
        await seeded.lake.uploads.begin(CONTRIBUTOR, uuid.uuid4(), "a", 1)


async def test_begin_needs_a_settled_collection(seeded: World) -> None:
    draft = await seeded.lake.collections.create(CONTRIBUTOR, "heliophysics", "solar-wind", "d")
    with pytest.raises(Conflict) as raised:
        await seeded.lake.uploads.begin(CONTRIBUTOR, draft.collection.id, "a", 1)
    assert raised.value.context == {"state": "draft", "allowed": ["active", "incomplete"]}


async def test_placement_gives_the_collection_directory_and_the_path_in_it(
    seeded: World, pending: Upload
) -> None:
    destination = await seeded.lake.uploads.placement(CONTRIBUTOR, pending.id)
    assert destination == Destination("helio/heliophysics/solar-wind/run7", PATH)


async def test_a_destination_and_the_removal_of_its_upload_name_the_same_file(
    seeded: World, pending: Upload
) -> None:
    destination = await seeded.lake.uploads.placement(CONTRIBUTOR, pending.id)
    placed = await seeded.lake.uploads.receipt(pending.id, 10, SHA, INODE)
    removal = placed.removal(destination.directory, seeded.clock.now())
    assert (removal.directory, removal.rel_path) == (destination.directory, destination.rel_path)
    assert removal.path == f"helio/heliophysics/solar-wind/run7/{PATH}"


async def test_placement_is_for_the_creator_of_a_pending_upload(
    seeded: World, pending: Upload
) -> None:
    for actor, upload_id in ((OTHER_CONTRIBUTOR, pending.id), (CONTRIBUTOR, uuid.uuid4())):
        with pytest.raises(UploadNotFound) as missing:
            await seeded.lake.uploads.placement(actor, upload_id)
        assert (missing.value.status, missing.value.context) == (404, {"upload": str(upload_id)})
    await seeded.lake.uploads.receipt(pending.id, 10, SHA, INODE)
    with pytest.raises(UploadStateConflict) as raised:
        await seeded.lake.uploads.placement(CONTRIBUTOR, pending.id)
    assert (raised.value.status, raised.value.context) == (
        409,
        {"state": "placed", "allowed": ["pending"]},
    )


async def test_placement_needs_the_right_to_write_files_still(
    seeded: World, pending: Upload
) -> None:
    grants = seeded.lake.grants
    await grants.set_catalog_role(
        CATALOG_ADMIN, "heliophysics", Role.READER, ["helio-readers", "helio-contributors"]
    )
    await grants.set_catalog_role(CATALOG_ADMIN, "heliophysics", Role.CONTRIBUTOR, [])
    with pytest.raises(Forbidden):
        await seeded.lake.uploads.placement(CONTRIBUTOR, pending.id)


@pytest.mark.parametrize("inode", [0, INODE, 2**64 - 1])
async def test_a_receipt_places_the_upload_with_its_inode(
    seeded: World, pending: Upload, inode: int
) -> None:
    seeded.clock.advance(timedelta(minutes=5))
    placed = await seeded.lake.uploads.receipt(pending.id, 10, SHA, inode)
    assert placed == replace(
        pending,
        state=UploadState.PLACED,
        sha256=SHA,
        placed_at=START + timedelta(minutes=5),
        inode=inode,
    )
    assert seeded.store.state.uploads[pending.id] == placed


async def test_a_repeated_receipt_changes_nothing_and_keeps_the_first_inode(
    seeded: World, pending: Upload
) -> None:
    placed = await seeded.lake.uploads.receipt(pending.id, 10, SHA, INODE)
    seeded.clock.advance(timedelta(minutes=5))
    assert await seeded.lake.uploads.receipt(pending.id, 10, SHA, INODE + 1) == placed
    for size, sha256 in ((10, OTHER_SHA), (11, SHA)):
        with pytest.raises(UploadStateConflict):
            await seeded.lake.uploads.receipt(pending.id, size, sha256, INODE)
    assert seeded.store.state.uploads[pending.id] == placed


async def test_a_receipt_must_have_the_declared_size(seeded: World, pending: Upload) -> None:
    with pytest.raises(UploadSizeMismatch) as raised:
        await seeded.lake.uploads.receipt(pending.id, 9, SHA, INODE)
    assert (raised.value.status, raised.value.context) == (422, {"declared": 10, "received": 9})
    assert seeded.store.state.uploads[pending.id] == pending


@pytest.mark.parametrize("sha256", ["", "d" * 63, "D" * 64, "g" * 64, "d" * 65])
async def test_a_receipt_needs_a_sha256(seeded: World, pending: Upload, sha256: str) -> None:
    with pytest.raises(Invalid) as raised:
        await seeded.lake.uploads.receipt(pending.id, 10, sha256, INODE)
    assert raised.value.context == {"sha256": sha256}


async def test_receipts_and_failures_need_a_known_pending_upload(
    seeded: World, pending: Upload
) -> None:
    unknown = uuid.uuid4()
    with pytest.raises(UploadNotFound):
        await seeded.lake.uploads.receipt(unknown, 10, SHA, INODE)
    with pytest.raises(UploadNotFound):
        await seeded.lake.uploads.fail(unknown, "X", "x")
    await seeded.lake.uploads.fail(pending.id, "UPLOAD_OUTSIDE_LAKE", "outside")
    with pytest.raises(UploadStateConflict):
        await seeded.lake.uploads.receipt(pending.id, 10, SHA, INODE)
    with pytest.raises(UploadStateConflict):
        await seeded.lake.uploads.fail(pending.id, "X", "again")


async def test_a_failure_is_recorded_with_its_reason(seeded: World, pending: Upload) -> None:
    failed = await seeded.lake.uploads.fail(pending.id, "PLACEMENT_FAILED", "no space left")
    assert (failed.state, failed.failure) == (
        UploadState.FAILED,
        Failure("PLACEMENT_FAILED", "no space left"),
    )
    shown = await seeded.lake.uploads.get(CONTRIBUTOR, pending.id)
    assert shown.as_dict() == {
        "id": str(pending.id),
        "collection_id": str(pending.collection_id),
        "rel_path": PATH,
        "size": 10,
        "state": "failed",
        "sha256": None,
        "failure": {"code": "PLACEMENT_FAILED", "message": "no space left"},
    }


async def test_terminate_ends_a_pending_or_failed_upload_once(
    seeded: World, collection_id: uuid.UUID, pending: Upload
) -> None:
    terminated = await seeded.lake.uploads.terminate(CONTRIBUTOR, pending.id)
    assert terminated == replace(pending, state=UploadState.TERMINATED)
    assert await seeded.lake.uploads.terminate(CONTRIBUTOR, pending.id) == terminated
    failing = await seeded.lake.uploads.begin(CONTRIBUTOR, collection_id, "b", 1)
    await seeded.lake.uploads.fail(failing.id, "X", "x")
    ended = await seeded.lake.uploads.terminate(CONTRIBUTOR, failing.id)
    assert ended.state is UploadState.TERMINATED
    assert seeded.store.state.uploads[failing.id].state is UploadState.TERMINATED


async def test_terminate_is_for_the_creator_of_an_unplaced_upload(
    seeded: World, pending: Upload
) -> None:
    with pytest.raises(UploadNotFound):
        await seeded.lake.uploads.terminate(OTHER_CONTRIBUTOR, pending.id)
    await seeded.lake.uploads.receipt(pending.id, 10, SHA, INODE)
    with pytest.raises(UploadStateConflict) as raised:
        await seeded.lake.uploads.terminate(CONTRIBUTOR, pending.id)
    assert raised.value.context["allowed"] == ["pending", "failed"]


async def test_only_the_creator_reads_an_upload(seeded: World, pending: Upload) -> None:
    assert await seeded.lake.uploads.get(CONTRIBUTOR, pending.id) == pending
    with pytest.raises(UploadNotFound):
        await seeded.lake.uploads.get(OTHER_CONTRIBUTOR, pending.id)
    with pytest.raises(UploadNotFound):
        await seeded.lake.uploads.get(CONTRIBUTOR, uuid.uuid4())


async def test_claimed_removals_carry_the_file_path(seeded: World, removal_id: uuid.UUID) -> None:
    _end_the_lease(seeded)
    (removal,) = await seeded.lake.uploads.claim_removals(10)
    assert isinstance(removal, Removal)
    assert (removal.id, removal.rel_path, removal.claimed_at) == (
        removal_id,
        "a.txt",
        seeded.clock.now(),
    )
    assert removal.path == "helio/heliophysics/solar-wind/run7/a.txt"
    assert (removal.organization, removal.directory) == (
        "helio",
        "helio/heliophysics/solar-wind/run7",
    )


@pytest.mark.parametrize(
    ("limit", "taken"),
    [(0, 1), (-1, 1), (None, DEFAULT_LIMIT), (MAXIMUM_LIMIT + 1, MAXIMUM_LIMIT)],
)
async def test_a_claim_takes_a_bounded_number_of_removals(
    seeded: World, backlog: list[Removal], limit: int | None, taken: int
) -> None:
    claimed = await seeded.lake.uploads.claim_removals(limit)
    assert [c.id for c in claimed] == [r.id for r in backlog[:taken]]


async def test_a_queued_removal_stays_with_its_request_until_the_lease_ends(
    seeded: World, removal_id: uuid.UUID
) -> None:
    assert seeded.store.state.removals[removal_id].claimed_at == START
    assert await seeded.lake.uploads.claim_removals(10) == []
    seeded.clock.advance(REMOVAL_LEASE)
    assert await seeded.lake.uploads.claim_removals(10) == []
    seeded.clock.advance(timedelta(seconds=1))
    (again,) = await seeded.lake.uploads.claim_removals(10)
    assert (again.id, again.claimed_at) == (removal_id, seeded.clock.now())
    assert await seeded.lake.uploads.claim_removals(10) == []


async def test_claims_take_the_oldest_removals_up_to_the_limit(
    seeded: World, collection_id: uuid.UUID
) -> None:
    request = CommitRequest(2, (FileAdd("a", 1, SHA), FileAdd("b", 1, SHA)), (), "h")
    await commit_uploaded(seeded.lake, CONTRIBUTOR, collection_id, request)
    for version, path in ((3, "b"), (4, "a")):
        seeded.clock.advance(timedelta(seconds=1))
        await seeded.lake.commits.commit(
            CONTRIBUTOR, collection_id, CommitRequest(version, (), (path,), "h")
        )
    _end_the_lease(seeded)
    first = await seeded.lake.uploads.claim_removals(1)
    second = await seeded.lake.uploads.claim_removals(5)
    assert [c.rel_path for c in (*first, *second)] == ["b", "a"]
    assert await seeded.lake.uploads.claim_removals(5) == []


async def test_a_removal_is_valid_while_nothing_claims_its_path(
    seeded: World, removal_id: uuid.UUID
) -> None:
    assert await seeded.lake.uploads.removal_still_valid(removal_id)


async def test_a_recorded_file_makes_a_removal_invalid(
    seeded: World, collection_id: uuid.UUID, removal_id: uuid.UUID
) -> None:
    removal = seeded.store.state.removals[removal_id]
    async with seeded.store.transaction() as tx:
        await tx.files.upsert_many(
            [FileRecord(collection_id, "A.txt", "a.txt", 1, SHA, START, "t", removal.commit_id)]
        )
    assert not await seeded.lake.uploads.removal_still_valid(removal_id)


async def test_a_placed_upload_makes_a_removal_invalid_until_it_expires(
    seeded: World, collection_id: uuid.UUID, removal_id: uuid.UUID
) -> None:
    await placed_upload(seeded.lake, OTHER_CONTRIBUTOR, collection_id, "A.txt", 1, OTHER_SHA)
    assert not await seeded.lake.uploads.removal_still_valid(removal_id)
    seeded.clock.advance(SETTINGS.upload_ttl)
    assert await seeded.lake.uploads.removal_still_valid(removal_id)


async def test_a_removal_in_a_nested_namespace_follows_its_collection(
    seeded: World, nested_collection_id: uuid.UUID
) -> None:
    removal_id = await _queue_removal(seeded, nested_collection_id, "x/a.txt")
    removal = seeded.store.state.removals[removal_id]
    assert removal.path == "helio/heliophysics/solar-wind/inner/deep/x/a.txt"
    assert await seeded.lake.uploads.removal_still_valid(removal_id)
    await placed_upload(seeded.lake, OTHER_CONTRIBUTOR, nested_collection_id, "X/A.txt", 1, SHA)
    assert not await seeded.lake.uploads.removal_still_valid(removal_id)


async def test_a_pending_upload_leaves_a_removal_valid(
    seeded: World, collection_id: uuid.UUID, removal_id: uuid.UUID
) -> None:
    await seeded.lake.uploads.begin(OTHER_CONTRIBUTOR, collection_id, "a.txt", 1)
    assert await seeded.lake.uploads.removal_still_valid(removal_id)


async def test_an_upload_a_later_placement_replaced_leaves_a_removal_valid(
    seeded: World, collection_id: uuid.UUID
) -> None:
    lake = seeded.lake
    await placed_upload(lake, OTHER_CONTRIBUTOR, collection_id, "a.txt", 1, OTHER_SHA)
    request = CommitRequest(2, (FileAdd("a.txt", 1, SHA),), (), "h")
    await commit_uploaded(lake, CONTRIBUTOR, collection_id, request)
    await lake.commits.commit(CONTRIBUTOR, collection_id, CommitRequest(3, (), ("a.txt",), "h"))
    (removal_id,) = seeded.store.state.removals
    assert await lake.uploads.removal_still_valid(removal_id)


async def test_a_removal_outlives_its_collection(seeded: World, orphan_id: uuid.UUID) -> None:
    removal = seeded.store.state.removals[orphan_id]
    assert (removal.collection_id, removal.commit_id) == (None, None)
    assert await seeded.lake.uploads.removal_still_valid(orphan_id)
    _end_the_lease(seeded)
    (claimed,) = await seeded.lake.uploads.claim_removals(10)
    assert claimed == replace(removal, claimed_at=seeded.clock.now())


async def test_a_collection_settled_at_the_same_directory_can_make_a_removal_invalid(
    seeded: World, orphan_id: uuid.UUID
) -> None:
    lake = seeded.lake
    draft = await lake.collections.create(
        CONTRIBUTOR, "heliophysics", "solar-wind", "run7", dict(VALID_METADATA)
    )
    assert await lake.uploads.removal_still_valid(orphan_id)
    await lake.collections.activate(CONTRIBUTOR, draft.collection.id, 1)
    assert await lake.uploads.removal_still_valid(orphan_id)
    upload = await placed_upload(lake, OTHER_CONTRIBUTOR, draft.collection.id, "A.txt", 1, SHA)
    assert not await lake.uploads.removal_still_valid(orphan_id)
    request = CommitRequest(2, (FileAdd("A.txt", 1, SHA),), (), "h")
    await lake.commits.commit(OTHER_CONTRIBUTOR, draft.collection.id, request)
    assert seeded.store.state.uploads[upload.id].state is UploadState.COMMITTED
    assert not await lake.uploads.removal_still_valid(orphan_id)


async def test_a_removal_in_another_organization_ignores_a_collection_of_the_same_names(
    seeded: World, collection_id: uuid.UUID
) -> None:
    request = CommitRequest(2, (FileAdd("a.txt", 1, SHA),), (), "h")
    await commit_uploaded(seeded.lake, CONTRIBUTOR, collection_id, request)
    elsewhere = Removal(
        new_id(), None, "geo/heliophysics/solar-wind/run7/a.txt", "a.txt", "a.txt", SHA, None, START
    )
    async with seeded.store.transaction() as tx:
        await tx.uploads.insert_removals([elsewhere])
    assert await seeded.lake.uploads.removal_still_valid(elsewhere.id)


async def test_a_finished_removal_is_gone_for_good(seeded: World, removal_id: uuid.UUID) -> None:
    await seeded.lake.uploads.finish_removal(removal_id)
    await seeded.lake.uploads.finish_removal(removal_id)
    assert seeded.store.state.removals == {}
    assert not await seeded.lake.uploads.removal_still_valid(removal_id)
    _end_the_lease(seeded)
    assert await seeded.lake.uploads.claim_removals(10) == []


def _end_the_lease(world: World) -> None:
    """Advance the clock past the lease of every removal claimed so far."""
    world.clock.advance(REMOVAL_LEASE + timedelta(seconds=1))


async def _queue_removal(world: World, collection_id: uuid.UUID, rel_path: str) -> uuid.UUID:
    """The id of the removal queued by committing ``rel_path`` and then removing it."""
    request = CommitRequest(2, (FileAdd(rel_path, 1, SHA),), (), "h")
    await commit_uploaded(world.lake, CONTRIBUTOR, collection_id, request)
    await world.lake.commits.commit(
        CONTRIBUTOR, collection_id, CommitRequest(3, (), (rel_path,), "h")
    )
    (queued,) = world.store.state.removals
    return queued
