"""Commits: parsing, refusal rules and recorded files."""

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
from huron.pkg.errors import Conflict, Forbidden
from tests.support.lake import CONTRIBUTOR, READER, VALID_METADATA, World

SHA = "a" * 64


def body(**overrides: object) -> dict[str, object]:
    return {"base_version": 2, "adds": [], "removes": [], "host": "h", **overrides}


async def settled(world: World) -> object:
    draft = await world.lake.collections.create(
        CONTRIBUTOR, "heliophysics", "solar-wind", "run7", dict(VALID_METADATA)
    )
    return (
        await world.lake.collections.activate(CONTRIBUTOR, draft.collection.id, 1)
    ).collection.id


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
    ("adds", "removes", "rule"),
    [
        (["../x"], [], "rel_path_separator"),
        (["metadata.json"], [], "rel_path_reserved"),
        (["A.txt", "a.TXT"], [], None),
        (["a"], ["a"], None),
    ],
)
def test_paths_are_checked_and_unique(
    adds: list[str], removes: list[str], rule: str | None
) -> None:
    with pytest.raises(CommitInvalid) as raised:
        parse_commit_request(
            body(adds=[{"rel_path": p, "size": 1, "sha256": SHA} for p in adds], removes=removes)
        )
    if rule:
        assert raised.value.context["rule"] == rule


def test_too_many_entries_are_refused_before_validation() -> None:
    with pytest.raises(CommitTooLarge) as raised:
        parse_commit_request(body(removes=[str(i) for i in range(MAX_COMMIT_ENTRIES + 1)]))
    assert raised.value.status == 413


async def test_commits_record_replace_and_remove_files(seeded: World) -> None:
    lake = seeded.lake
    cid = await settled(seeded)
    first = await lake.commits.commit(
        CONTRIBUTOR,
        cid,  # type: ignore[arg-type]
        CommitRequest(2, (FileAdd("b.txt", 1, SHA), FileAdd("A.txt", 2, SHA)), (), "host", "m"),
    )
    assert (first.version, first.file_count) == (3, 2)
    replaced = await lake.commits.commit(
        CONTRIBUTOR,
        cid,
        CommitRequest(3, (FileAdd("b.txt", 9, SHA),), (), "host"),  # type: ignore[arg-type]
    )
    assert replaced.file_count == 2
    files = await lake.commits.list_files(READER, cid, limit=1)  # type: ignore[arg-type]
    assert [f.rel_path for f in files.items] == ["A.txt"]
    rest = await lake.commits.list_files(READER, cid, cursor=files.next_cursor)  # type: ignore[arg-type]
    assert [(f.rel_path, f.size) for f in rest.items] == [("b.txt", 9)]
    removed = await lake.commits.commit(
        CONTRIBUTOR,
        cid,
        CommitRequest(4, (), ("a.txt",), "host"),  # type: ignore[arg-type]
    )
    assert removed.file_count == 1
    commits = await lake.commits.list_commits(READER, cid, limit=2)  # type: ignore[arg-type]
    assert [c.new_version for c in commits.items] == [5, 4]
    older = await lake.commits.list_commits(READER, cid, cursor=commits.next_cursor)  # type: ignore[arg-type]
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


async def test_commit_refusals(seeded: World) -> None:
    lake = seeded.lake
    cid = await settled(seeded)
    with pytest.raises(BaseVersionConflict) as raised:
        await lake.commits.commit(CONTRIBUTOR, cid, CommitRequest(1, (), (), "h"))  # type: ignore[arg-type]
    assert raised.value.context["current_version"] == 2
    assert raised.value.status == 409
    with pytest.raises(FileNotRecorded):
        await lake.commits.commit(CONTRIBUTOR, cid, CommitRequest(2, (), ("nope",), "h"))  # type: ignore[arg-type]
    with pytest.raises(Forbidden):
        await lake.commits.commit(READER, cid, CommitRequest(2, (), (), "h"))  # type: ignore[arg-type]
    draft = await lake.collections.create(CONTRIBUTOR, "heliophysics", "solar-wind", "d")
    with pytest.raises(Conflict):
        await lake.commits.commit(CONTRIBUTOR, draft.collection.id, CommitRequest(1, (), (), "h"))


@pytest.mark.parametrize("adds", [["d", "d/e"], ["d/e/f", "D"], ["x/y", "x/y/z/w"]])
def test_a_commit_cannot_add_a_file_and_a_path_inside_it(adds: list[str]) -> None:
    with pytest.raises(CommitInvalid) as raised:
        parse_commit_request(body(adds=[{"rel_path": p, "size": 1, "sha256": SHA} for p in adds]))
    assert "lies inside" in raised.value.message


async def test_paths_must_fit_the_recorded_tree(seeded: World) -> None:
    lake = seeded.lake
    collection_id = await settled(seeded)

    def add(*paths: str) -> tuple[FileAdd, ...]:
        return tuple(FileAdd(p, 1, SHA) for p in paths)

    await lake.commits.commit(
        CONTRIBUTOR, collection_id, CommitRequest(2, add("d", "a/b"), (), "h")
    )  # type: ignore[arg-type]
    for adds in (add("d/e"), add("D/e/f"), add("a"), add("A")):
        with pytest.raises(CommitInvalid):
            await lake.commits.commit(CONTRIBUTOR, collection_id, CommitRequest(3, adds, (), "h"))  # type: ignore[arg-type]
    replaced = await lake.commits.commit(
        CONTRIBUTOR,
        collection_id,
        CommitRequest(3, add("d/e", "a"), ("d", "a/b"), "h"),  # type: ignore[arg-type]
    )
    assert replaced.version == 4 and replaced.file_count == 2
