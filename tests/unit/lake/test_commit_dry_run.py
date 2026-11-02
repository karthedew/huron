"""Dry-run commits: every check of a real commit, nothing written."""

import uuid

import pytest

from huron.core.lake.audit import Action
from huron.core.lake.files.commits import parse_commit_request
from huron.core.lake.files.errors import BaseVersionConflict, CommitInvalid, FileNotRecorded
from huron.core.lake.files.models import CommitRequest, CommitResult, FileAdd
from huron.pkg.errors import Conflict, Forbidden
from tests.support.lake import CONTRIBUTOR, READER, VALID_METADATA, World

SHA = "b" * 64


async def settled(world: World) -> uuid.UUID:
    draft = await world.lake.collections.create(
        CONTRIBUTOR, "heliophysics", "solar-wind", "run7", dict(VALID_METADATA)
    )
    activated = await world.lake.collections.activate(CONTRIBUTOR, draft.collection.id, 1)
    return activated.collection.id


async def unchanged(world: World, collection_id: uuid.UUID, version: int, files: int) -> None:
    view = await world.lake.collections.get(CONTRIBUTOR, collection_id)
    assert (view.collection.version, view.collection.file_count) == (version, files)
    commits = await world.lake.commits.list_commits(READER, collection_id)
    assert len(commits.items) == version - 2


def commit_audits(world: World) -> int:
    return sum(1 for e in world.store.state.audit if e.action is Action.COLLECTION_COMMIT)


def test_a_dry_run_body_may_leave_out_hashes() -> None:
    request = parse_commit_request(
        {"base_version": 2, "adds": [{"rel_path": "a.txt", "size": 4}], "removes": [], "host": "h"},
        dry_run=True,
    )
    assert request.adds == (FileAdd("a.txt", 4, None),)


def test_a_dry_run_body_still_checks_hashes_it_carries_and_paths() -> None:
    bad_hash = {"rel_path": "a.txt", "size": 4, "sha256": "X"}
    with pytest.raises(CommitInvalid):
        parse_commit_request(
            {"base_version": 2, "adds": [bad_hash], "removes": [], "host": "h"}, dry_run=True
        )
    with pytest.raises(CommitInvalid):
        parse_commit_request(
            {
                "base_version": 2,
                "adds": [{"rel_path": "../a", "size": 1}],
                "removes": [],
                "host": "h",
            },
            dry_run=True,
        )


def test_a_real_commit_body_needs_hashes() -> None:
    with pytest.raises(CommitInvalid) as raised:
        parse_commit_request(
            {
                "base_version": 2,
                "adds": [{"rel_path": "a.txt", "size": 4}],
                "removes": [],
                "host": "h",
            }
        )
    assert raised.value.status == 422


async def test_a_dry_run_answers_the_would_be_result_and_writes_nothing(seeded: World) -> None:
    lake = seeded.lake
    cid = await settled(seeded)
    await lake.commits.commit(
        CONTRIBUTOR,
        cid,
        CommitRequest(2, (FileAdd("a.txt", 1, SHA), FileAdd("b.txt", 1, SHA)), (), "h"),
    )
    before = commit_audits(seeded)
    request = CommitRequest(
        3, (FileAdd("A.txt", 5, None), FileAdd("c.txt", 2, None)), ("b.txt",), "h", "m"
    )
    preview = await lake.commits.commit(CONTRIBUTOR, cid, request, dry_run=True)
    assert preview == CommitResult(4, 2, None)
    assert preview.as_dict() == {"version": 4, "file_count": 2, "commit_id": None}
    await unchanged(seeded, cid, 3, 2)
    assert commit_audits(seeded) == before
    listed = await lake.commits.list_files(READER, cid)
    assert [(f.rel_path, f.size) for f in listed.items] == [("a.txt", 1), ("b.txt", 1)]


async def test_an_empty_dry_run_previews_the_next_version(seeded: World) -> None:
    cid = await settled(seeded)
    preview = await seeded.lake.commits.commit(
        CONTRIBUTOR, cid, CommitRequest(2, (), (), "h"), dry_run=True
    )
    assert preview == CommitResult(3, 0, None)
    await unchanged(seeded, cid, 2, 0)


async def test_a_dry_run_is_refused_like_a_real_commit(seeded: World) -> None:
    lake = seeded.lake
    cid = await settled(seeded)
    unhashed = (FileAdd("a.txt", 1, None),)
    with pytest.raises(Forbidden):
        await lake.commits.commit(READER, cid, CommitRequest(2, unhashed, (), "h"), dry_run=True)
    with pytest.raises(BaseVersionConflict) as raised:
        await lake.commits.commit(
            CONTRIBUTOR, cid, CommitRequest(1, unhashed, (), "h"), dry_run=True
        )
    assert raised.value.context == {"current_version": 2, "base_version": 1}
    with pytest.raises(FileNotRecorded):
        await lake.commits.commit(CONTRIBUTOR, cid, CommitRequest(2, (), ("x",), "h"), dry_run=True)
    await lake.commits.commit(CONTRIBUTOR, cid, CommitRequest(2, (FileAdd("d", 1, SHA),), (), "h"))
    with pytest.raises(CommitInvalid):
        await lake.commits.commit(
            CONTRIBUTOR, cid, CommitRequest(3, (FileAdd("d/e", 1, None),), (), "h"), dry_run=True
        )
    draft = await lake.collections.create(CONTRIBUTOR, "heliophysics", "solar-wind", "d")
    with pytest.raises(Conflict):
        await lake.commits.commit(
            CONTRIBUTOR, draft.collection.id, CommitRequest(1, (), (), "h"), dry_run=True
        )
    await unchanged(seeded, cid, 3, 1)


async def test_a_real_commit_refuses_an_add_without_a_hash(seeded: World) -> None:
    cid = await settled(seeded)
    with pytest.raises(CommitInvalid) as raised:
        await seeded.lake.commits.commit(
            CONTRIBUTOR, cid, CommitRequest(2, (FileAdd("a.txt", 1, None),), (), "h")
        )
    assert raised.value.context == {"rel_path": "a.txt"}
    await unchanged(seeded, cid, 2, 0)
