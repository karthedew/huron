"""Dry runs of a commit: the checks of a real commit but not of its uploads, nothing written."""

import uuid

import pytest

from huron.core.lake.files.errors import (
    BaseVersionConflict,
    CommitInvalid,
    CommitTooLarge,
    FileNotRecorded,
)
from huron.core.lake.publications.errors import CollectionBusy
from huron.core.lake.publications.models import (
    MAX_ENTRIES,
    CommitDraft,
    CommitPreview,
    DraftAdd,
)
from huron.pkg.errors import Conflict, Forbidden, NotFound
from tests.support.lake import CONTRIBUTOR, READER, STRANGER
from tests.support.publication import Publishing

SHA = "b" * 64


def draft(
    publishing: Publishing,
    base_version: int,
    adds: tuple[DraftAdd, ...] = (),
    removes: tuple[str, ...] = (),
) -> CommitDraft:
    return CommitDraft(publishing.collection_id, base_version, adds, removes)


async def unchanged(publishing: Publishing, version: int, files: list[str]) -> None:
    collection = await publishing.collection()
    assert (collection.version, collection.file_count) == (version, len(files))
    assert sorted(await publishing.files()) == files
    async with publishing.store.transaction() as tx:
        assert await tx.commit_requests.pending() == []


def test_a_draft_can_leave_out_the_hash_and_the_upload() -> None:
    added = DraftAdd("a.txt", 4)
    assert (added.sha256, added.upload_id) == (None, None)
    assert CommitDraft(uuid.uuid4(), 2, (added,), ()).adds == (added,)


@pytest.mark.parametrize(
    ("adds", "removes", "error"),
    [
        ((DraftAdd("a.txt", 4, "X"),), (), CommitInvalid),
        ((DraftAdd("a.txt", -1),), (), CommitInvalid),
        ((DraftAdd("../a", 1),), (), CommitInvalid),
        ((DraftAdd("a.txt", 1),), ("A.txt",), CommitInvalid),
        (
            (DraftAdd("a", 1, SHA, uuid.UUID(int=1)), DraftAdd("b", 1, SHA, uuid.UUID(int=1))),
            (),
            CommitInvalid,
        ),
        ((), tuple(f"f{index}" for index in range(MAX_ENTRIES + 1)), CommitTooLarge),
    ],
)
def test_a_draft_keeps_the_rules_of_a_commit_request(
    adds: tuple[DraftAdd, ...], removes: tuple[str, ...], error: type[Exception]
) -> None:
    with pytest.raises(error):
        CommitDraft(uuid.uuid4(), 2, adds, removes)


def test_a_draft_refuses_a_base_version_outside_the_column() -> None:
    with pytest.raises(CommitInvalid):
        CommitDraft(uuid.uuid4(), -1, (), ())


async def test_a_dry_run_answers_the_would_be_result_and_writes_nothing(
    publishing: Publishing,
) -> None:
    await publishing.commit(CONTRIBUTOR, 2, {"a.txt": b"a", "b.txt": b"b"})
    preview = await publishing.publications.preview(
        CONTRIBUTOR,
        draft(publishing, 3, (DraftAdd("A.txt", 5), DraftAdd("c.txt", 2)), ("b.txt",)),
    )
    assert preview == CommitPreview(4, 2)
    assert preview.as_dict() == {"version": 4, "file_count": 2}
    await unchanged(publishing, 3, ["a.txt", "b.txt"])


async def test_an_empty_dry_run_previews_the_next_version(publishing: Publishing) -> None:
    preview = await publishing.publications.preview(CONTRIBUTOR, draft(publishing, 2))
    assert preview == CommitPreview(3, 0)
    await unchanged(publishing, 2, [])


async def test_a_dry_run_is_refused_like_a_real_commit(publishing: Publishing) -> None:
    preview = publishing.publications.preview
    unhashed = (DraftAdd("a.txt", 1),)
    with pytest.raises(Forbidden):
        await preview(READER, draft(publishing, 2, unhashed))
    with pytest.raises(NotFound):
        await preview(STRANGER, draft(publishing, 2, unhashed))
    with pytest.raises(BaseVersionConflict) as raised:
        await preview(CONTRIBUTOR, draft(publishing, 1, unhashed))
    assert raised.value.context == {"current_version": 2, "base_version": 1}
    with pytest.raises(FileNotRecorded):
        await preview(CONTRIBUTOR, draft(publishing, 2, (), ("x",)))
    await publishing.commit(CONTRIBUTOR, 2, {"d": b"d"})
    with pytest.raises(CommitInvalid):
        await preview(CONTRIBUTOR, draft(publishing, 3, (DraftAdd("d/e", 1),)))
    await unchanged(publishing, 3, ["d"])


async def test_a_dry_run_of_a_draft_collection_is_refused(publishing: Publishing) -> None:
    created = await publishing.lake.collections.create(
        CONTRIBUTOR, "heliophysics", "solar-wind", "d"
    )
    with pytest.raises(Conflict):
        await publishing.publications.preview(
            CONTRIBUTOR, CommitDraft(created.collection.id, 1, (), ())
        )


async def test_a_dry_run_on_a_busy_collection_is_refused(publishing: Publishing) -> None:
    attempt = await publishing.ready(CONTRIBUTOR, "a.txt", b"a")
    await publishing.publications.submit(CONTRIBUTOR, publishing.request(2, [(attempt, b"a")]))
    with pytest.raises(CollectionBusy):
        await publishing.publications.preview(CONTRIBUTOR, draft(publishing, 2))
