"""Commits: parsing, refusal rules, recorded files, receipts and the removal outbox."""

import uuid
from dataclasses import replace
from datetime import timedelta

import pytest

from huron.core.lake.audit import Action
from huron.core.lake.files.commits import MAX_COMMIT_ENTRIES, parse_commit_request
from huron.core.lake.files.errors import (
    BaseVersionConflict,
    CommitInvalid,
    CommitTooLarge,
    FileNotRecorded,
)
from huron.core.lake.files.models import CommitRequest, FileAdd
from huron.core.lake.uploads.errors import UploadReceiptMissing
from huron.core.lake.uploads.models import ReceiptMode, UploadState
from huron.core.security.rbac import Actor
from huron.pkg.errors import Conflict, Forbidden
from tests.support.lake import (
    CONTRIBUTOR,
    OTHER_CONTRIBUTOR,
    READER,
    SETTINGS,
    World,
    commit_uploaded,
    make_world,
    placed_upload,
    seed,
    settled_collection,
)

SHA = "a" * 64
OTHER_SHA = "c" * 64


def body(**overrides: object) -> dict[str, object]:
    return {"base_version": 2, "adds": [], "removes": [], "host": "h", **overrides}


def adds(*paths: str) -> tuple[FileAdd, ...]:
    return tuple(FileAdd(path, 1, SHA) for path in paths)


def test_a_valid_body_parses() -> None:
    request = parse_commit_request(
        body(adds=[{"rel_path": "a/b.txt", "size": 3, "sha256": SHA}], removes=["c"], message="m")
    )
    assert request.adds == (FileAdd("a/b.txt", 3, SHA),)
    assert request.removes == ("c",) and request.message == "m"


@pytest.mark.parametrize(
    "bad",
    [
        body(base_version=0),
        body(adds=[{"rel_path": "a", "size": -1, "sha256": SHA}]),
        body(adds=[{"rel_path": "a", "size": 1, "sha256": SHA.upper()}]),
        body(base_etag="x"),
        {"adds": [], "removes": []},
        [],
    ],
)
def test_malformed_bodies_are_invalid(bad: object) -> None:
    with pytest.raises(CommitInvalid) as raised:
        parse_commit_request(bad)
    assert raised.value.status == 422


@pytest.mark.parametrize(
    ("paths", "removes", "rule"),
    [
        (["../x"], [], "rel_path_separator"),
        (["metadata.json"], [], "rel_path_reserved"),
        (["A.txt", "a.TXT"], [], None),
        (["a"], ["a"], None),
    ],
)
def test_paths_are_checked_and_unique(
    paths: list[str], removes: list[str], rule: str | None
) -> None:
    with pytest.raises(CommitInvalid) as raised:
        parse_commit_request(
            body(adds=[{"rel_path": p, "size": 1, "sha256": SHA} for p in paths], removes=removes)
        )
    if rule:
        assert raised.value.context["rule"] == rule


def test_too_many_entries_are_refused_before_validation() -> None:
    with pytest.raises(CommitTooLarge) as raised:
        parse_commit_request(body(removes=[str(i) for i in range(MAX_COMMIT_ENTRIES + 1)]))
    assert raised.value.status == 413


async def test_commits_record_replace_and_remove_files(
    seeded: World, collection_id: uuid.UUID
) -> None:
    lake = seeded.lake
    first = await commit_uploaded(
        seeded.lake,
        CONTRIBUTOR,
        collection_id,
        CommitRequest(2, (FileAdd("b.txt", 1, SHA), FileAdd("A.txt", 2, SHA)), (), "host", "m"),
    )
    assert (first.version, first.file_count) == (3, 2)
    replaced = await commit_uploaded(
        seeded.lake,
        CONTRIBUTOR,
        collection_id,
        CommitRequest(3, (FileAdd("b.txt", 9, SHA),), (), "h"),
    )
    assert replaced.file_count == 2
    files = await lake.commits.list_files(READER, collection_id, limit=1)
    assert [f.rel_path for f in files.items] == ["A.txt"]
    rest = await lake.commits.list_files(READER, collection_id, cursor=files.next_cursor)
    assert [(f.rel_path, f.size) for f in rest.items] == [("b.txt", 9)]
    removed = await lake.commits.commit(
        CONTRIBUTOR, collection_id, CommitRequest(4, (), ("a.txt",), "host")
    )
    assert removed.file_count == 1
    commits = await lake.commits.list_commits(READER, collection_id, limit=2)
    assert [c.new_version for c in commits.items] == [5, 4]
    older = await lake.commits.list_commits(READER, collection_id, cursor=commits.next_cursor)
    assert [c.new_version for c in older.items] == [3]
    entries = [e for e in seeded.store.state.audit if e.action is Action.COLLECTION_COMMIT]
    assert entries[0].detail == {
        "adds": 2,
        "removes": 0,
        "host": "host",
        "message": "m",
        "version": 3,
    }
    assert first.as_dict()["version"] == 3


async def test_commit_refusals(seeded: World, collection_id: uuid.UUID) -> None:
    lake = seeded.lake
    with pytest.raises(BaseVersionConflict) as raised:
        await lake.commits.commit(CONTRIBUTOR, collection_id, CommitRequest(1, (), (), "h"))
    assert raised.value.context["current_version"] == 2
    assert raised.value.status == 409
    with pytest.raises(FileNotRecorded):
        await lake.commits.commit(CONTRIBUTOR, collection_id, CommitRequest(2, (), ("nope",), "h"))
    with pytest.raises(Forbidden):
        await lake.commits.commit(READER, collection_id, CommitRequest(2, (), (), "h"))
    draft = await lake.collections.create(CONTRIBUTOR, "heliophysics", "solar-wind", "d")
    with pytest.raises(Conflict):
        await lake.commits.commit(CONTRIBUTOR, draft.collection.id, CommitRequest(1, (), (), "h"))


@pytest.mark.parametrize("paths", [["d", "d/e"], ["d/e/f", "D"], ["x/y", "x/y/z/w"]])
def test_a_commit_cannot_add_a_file_and_a_path_inside_it(paths: list[str]) -> None:
    with pytest.raises(CommitInvalid) as raised:
        parse_commit_request(body(adds=[{"rel_path": p, "size": 1, "sha256": SHA} for p in paths]))
    assert "lies inside" in raised.value.message


async def test_paths_must_fit_the_recorded_tree(seeded: World, collection_id: uuid.UUID) -> None:
    lake = seeded.lake
    await commit_uploaded(
        seeded.lake, CONTRIBUTOR, collection_id, CommitRequest(2, adds("d", "a/b"), (), "h")
    )
    for refused in (adds("d/e"), adds("D/e/f"), adds("a"), adds("A")):
        with pytest.raises(CommitInvalid):
            await lake.commits.commit(
                CONTRIBUTOR, collection_id, CommitRequest(3, refused, (), "h")
            )
    replaced = await commit_uploaded(
        seeded.lake,
        CONTRIBUTOR,
        collection_id,
        CommitRequest(3, adds("d/e", "a"), ("d", "a/b"), "h"),
    )
    assert replaced.version == 4 and replaced.file_count == 2


async def test_a_commit_consumes_the_receipt_that_proves_an_add(
    seeded: World, collection_id: uuid.UUID
) -> None:
    older = await placed_upload(seeded.lake, CONTRIBUTOR, collection_id, "a.txt", 1, SHA)
    latest = await placed_upload(seeded.lake, CONTRIBUTOR, collection_id, "a.txt", 1, SHA)
    result = await seeded.lake.commits.commit(
        CONTRIBUTOR, collection_id, CommitRequest(2, adds("a.txt"), (), "h")
    )
    uploads = seeded.store.state.uploads
    assert (uploads[latest.id].state, uploads[latest.id].commit_id) == (
        UploadState.COMMITTED,
        result.commit_id,
    )
    assert uploads[older.id] == older
    with pytest.raises(UploadReceiptMissing):
        await seeded.lake.commits.commit(
            CONTRIBUTOR, collection_id, CommitRequest(3, adds("a.txt"), (), "h")
        )


@pytest.mark.parametrize(
    ("author", "sha256"),
    [
        pytest.param(CONTRIBUTOR, OTHER_SHA, id="by the committer with other bytes"),
        pytest.param(OTHER_CONTRIBUTOR, SHA, id="by another user"),
    ],
)
async def test_a_later_placement_of_the_path_voids_an_earlier_receipt(
    seeded: World, collection_id: uuid.UUID, author: Actor, sha256: str
) -> None:
    receipt = await placed_upload(seeded.lake, CONTRIBUTOR, collection_id, "a.txt", 1, SHA)
    seeded.clock.advance(timedelta(seconds=1))
    await placed_upload(seeded.lake, author, collection_id, "A.txt", 1, sha256)
    with pytest.raises(UploadReceiptMissing) as raised:
        await seeded.lake.commits.commit(
            CONTRIBUTOR, collection_id, CommitRequest(2, adds("a.txt"), (), "h")
        )
    assert raised.value.context == {"rel_path": "a.txt"}
    assert seeded.store.state.uploads[receipt.id] == receipt


async def test_a_committed_later_placement_voids_an_earlier_receipt(
    seeded: World, collection_id: uuid.UUID
) -> None:
    await placed_upload(seeded.lake, CONTRIBUTOR, collection_id, "a.txt", 1, SHA)
    await commit_uploaded(
        seeded.lake, OTHER_CONTRIBUTOR, collection_id, CommitRequest(2, adds("a.txt"), (), "h")
    )
    with pytest.raises(UploadReceiptMissing):
        await seeded.lake.commits.commit(
            CONTRIBUTOR, collection_id, CommitRequest(3, adds("a.txt"), (), "h")
        )


async def test_the_latest_placement_is_the_last_placed_whatever_began_first(
    seeded: World, collection_id: uuid.UUID
) -> None:
    lake = seeded.lake
    first = await lake.uploads.begin(CONTRIBUTOR, collection_id, "a.txt", 1)
    second = await lake.uploads.begin(CONTRIBUTOR, collection_id, "a.txt", 1)
    await lake.uploads.receipt(second.id, 1, OTHER_SHA)
    seeded.clock.advance(timedelta(seconds=1))
    await lake.uploads.receipt(first.id, 1, SHA)
    with pytest.raises(UploadReceiptMissing):
        await lake.commits.commit(
            CONTRIBUTOR, collection_id, CommitRequest(2, (FileAdd("a.txt", 1, OTHER_SHA),), (), "h")
        )
    result = await lake.commits.commit(
        CONTRIBUTOR, collection_id, CommitRequest(2, adds("a.txt"), (), "h")
    )
    assert seeded.store.state.uploads[first.id].commit_id == result.commit_id


async def test_placements_at_the_same_moment_are_ordered_by_upload(
    seeded: World, collection_id: uuid.UUID
) -> None:
    await placed_upload(seeded.lake, CONTRIBUTOR, collection_id, "a.txt", 1, SHA)
    await placed_upload(seeded.lake, CONTRIBUTOR, collection_id, "a.txt", 1, OTHER_SHA)
    with pytest.raises(UploadReceiptMissing):
        await seeded.lake.commits.commit(
            CONTRIBUTOR, collection_id, CommitRequest(2, adds("a.txt"), (), "h")
        )
    result = await seeded.lake.commits.commit(
        CONTRIBUTOR, collection_id, CommitRequest(2, (FileAdd("a.txt", 1, OTHER_SHA),), (), "h")
    )
    assert result.file_count == 1


@pytest.mark.parametrize(
    ("author", "rel_path", "size", "sha256", "age"),
    [
        pytest.param(CONTRIBUTOR, "a.txt", 2, SHA, timedelta(0), id="other size"),
        pytest.param(CONTRIBUTOR, "a.txt", 1, OTHER_SHA, timedelta(0), id="other hash"),
        pytest.param(CONTRIBUTOR, "b.txt", 1, SHA, timedelta(0), id="other path"),
        pytest.param(CONTRIBUTOR, "A.txt", 1, SHA, timedelta(0), id="same key, other case"),
        pytest.param(OTHER_CONTRIBUTOR, "a.txt", 1, SHA, timedelta(0), id="other author"),
        pytest.param(CONTRIBUTOR, "a.txt", 1, SHA, timedelta(hours=24), id="expired"),
    ],
)
async def test_an_add_needs_a_receipt_that_proves_it(
    seeded: World,
    collection_id: uuid.UUID,
    author: Actor,
    rel_path: str,
    size: int,
    sha256: str,
    age: timedelta,
) -> None:
    await placed_upload(seeded.lake, author, collection_id, rel_path, size, sha256)
    seeded.clock.advance(age)
    with pytest.raises(UploadReceiptMissing) as raised:
        await seeded.lake.commits.commit(
            CONTRIBUTOR, collection_id, CommitRequest(2, adds("a.txt"), (), "h")
        )
    assert (raised.value.status, raised.value.context) == (422, {"rel_path": "a.txt"})
    view = await seeded.lake.collections.get(READER, collection_id)
    assert (view.collection.version, view.collection.file_count) == (2, 0)


async def test_a_pending_upload_is_no_receipt(seeded: World, collection_id: uuid.UUID) -> None:
    await seeded.lake.uploads.begin(CONTRIBUTOR, collection_id, "a.txt", 1)
    with pytest.raises(UploadReceiptMissing):
        await seeded.lake.commits.commit(
            CONTRIBUTOR, collection_id, CommitRequest(2, adds("a.txt"), (), "h")
        )


async def test_a_receipt_is_good_until_its_time_to_live_ends(
    seeded: World, collection_id: uuid.UUID
) -> None:
    await placed_upload(seeded.lake, CONTRIBUTOR, collection_id, "a.txt", 1, SHA)
    seeded.clock.advance(SETTINGS.upload_ttl - timedelta(seconds=1))
    result = await seeded.lake.commits.commit(
        CONTRIBUTOR, collection_id, CommitRequest(2, adds("a.txt"), (), "h")
    )
    assert result.file_count == 1


async def test_optional_receipts_record_unproved_adds_and_still_consume_receipts() -> None:
    world = await make_world(replace(SETTINGS, upload_receipts=ReceiptMode.OPTIONAL))
    await seed(world)
    collection_id = await settled_collection(world.lake)
    upload = await placed_upload(world.lake, CONTRIBUTOR, collection_id, "proved.txt", 1, SHA)
    result = await world.lake.commits.commit(
        CONTRIBUTOR, collection_id, CommitRequest(2, adds("proved.txt", "unproved.txt"), (), "h")
    )
    assert result.file_count == 2
    stored = world.store.state.uploads[upload.id]
    assert (stored.state, stored.commit_id) == (UploadState.COMMITTED, result.commit_id)


async def test_a_commit_queues_the_removal_of_each_removed_file(
    seeded: World, collection_id: uuid.UUID
) -> None:
    await commit_uploaded(
        seeded.lake,
        CONTRIBUTOR,
        collection_id,
        CommitRequest(2, (FileAdd("Data/A.txt", 4, SHA), FileAdd("b.txt", 1, OTHER_SHA)), (), "h"),
    )
    result = await seeded.lake.commits.commit(
        CONTRIBUTOR, collection_id, CommitRequest(3, (), ("data/a.txt", "b.txt"), "h")
    )
    queued = sorted(seeded.store.state.removals.values(), key=lambda r: r.rel_path)
    directory = "helio/heliophysics/solar-wind/run7"
    assert [(r.path, r.rel_path, r.rel_path_key, r.sha256) for r in queued] == [
        (f"{directory}/Data/A.txt", "Data/A.txt", "data/a.txt", SHA),
        (f"{directory}/b.txt", "b.txt", "b.txt", OTHER_SHA),
    ]
    assert {(r.collection_id, r.commit_id, r.claimed_at) for r in queued} == {
        (collection_id, result.commit_id, None)
    }
    assert {r.created_at for r in queued} == {seeded.clock.now()}


async def test_adding_a_path_again_cancels_its_queued_removal(
    seeded: World, collection_id: uuid.UUID
) -> None:
    await commit_uploaded(
        seeded.lake, CONTRIBUTOR, collection_id, CommitRequest(2, adds("a.txt", "b.txt"), (), "h")
    )
    await seeded.lake.commits.commit(
        CONTRIBUTOR, collection_id, CommitRequest(3, (), ("a.txt", "b.txt"), "h")
    )
    await commit_uploaded(
        seeded.lake, CONTRIBUTOR, collection_id, CommitRequest(4, adds("A.TXT"), (), "h")
    )
    assert [r.rel_path for r in seeded.store.state.removals.values()] == ["b.txt"]


async def test_a_refused_commit_queues_and_consumes_nothing(
    seeded: World, collection_id: uuid.UUID
) -> None:
    await commit_uploaded(
        seeded.lake, CONTRIBUTOR, collection_id, CommitRequest(2, adds("a"), (), "h")
    )
    upload = await placed_upload(seeded.lake, CONTRIBUTOR, collection_id, "b", 1, SHA)
    with pytest.raises(UploadReceiptMissing):
        await seeded.lake.commits.commit(
            CONTRIBUTOR, collection_id, CommitRequest(3, adds("b", "c"), ("a",), "h")
        )
    assert seeded.store.state.removals == {}
    assert seeded.store.state.uploads[upload.id].state is UploadState.PLACED
