"""The listings of recorded files and commits: their order and their pages, on both stores."""

import pytest

from huron.pkg.paging import InvalidCursor
from tests.support.lake import CONTRIBUTOR, READER
from tests.support.publication import Publishing


async def published(publishing: Publishing) -> None:
    """Three commits: four adds, a replacement of ``b.txt``, then the removal of ``e.txt``.

    The recorded files are then ``A.txt``, ``b.txt`` and ``c/d.txt``, at version 5.
    """
    files = {"b.txt": b"b", "A.txt": b"aa", "c/d.txt": b"ddd", "e.txt": b"e"}
    await publishing.commit(CONTRIBUTOR, 2, files)
    await publishing.commit(CONTRIBUTOR, 3, {"b.txt": b"bbbb"})
    await publishing.commit(CONTRIBUTOR, 4, {}, ["e.txt"])


async def test_an_empty_collection_lists_no_file_and_no_commit(publishing: Publishing) -> None:
    files = await publishing.lake.commits.list_files(READER, publishing.collection_id)
    commits = await publishing.lake.commits.list_commits(READER, publishing.collection_id)
    assert (files.items, files.next_cursor) == ((), None)
    assert (commits.items, commits.next_cursor) == ((), None)


async def test_files_come_in_the_order_of_their_case_folded_paths_one_page_at_a_time(
    publishing: Publishing,
) -> None:
    await published(publishing)
    list_files = publishing.lake.commits.list_files
    pages: list[list[tuple[str, int]]] = []
    cursor: str | None = None
    while True:
        page = await list_files(READER, publishing.collection_id, cursor, 1)
        pages.append([(record.rel_path, record.size) for record in page.items])
        if page.next_cursor is None:
            break
        cursor = page.next_cursor
    assert pages == [[("A.txt", 2)], [("b.txt", 4)], [("c/d.txt", 3)]]


@pytest.mark.parametrize("limit", [3, 10])
async def test_a_page_as_large_as_the_files_or_larger_holds_them_all(
    publishing: Publishing, limit: int
) -> None:
    await published(publishing)
    page = await publishing.lake.commits.list_files(READER, publishing.collection_id, None, limit)
    assert [record.rel_path for record in page.items] == ["A.txt", "b.txt", "c/d.txt"]
    assert page.next_cursor is None


async def test_commits_come_newest_first_one_page_at_a_time(publishing: Publishing) -> None:
    await published(publishing)
    list_commits = publishing.lake.commits.list_commits
    first = await list_commits(READER, publishing.collection_id, None, 2)
    assert [commit.new_version for commit in first.items] == [5, 4]
    assert first.next_cursor is not None
    rest = await list_commits(READER, publishing.collection_id, first.next_cursor, 2)
    assert [commit.new_version for commit in rest.items] == [3]
    assert rest.next_cursor is None
    assert [(commit.adds, commit.removes) for commit in (*first.items, *rest.items)] == [
        (0, 1),
        (1, 0),
        (4, 0),
    ]


@pytest.mark.parametrize("limit", [3, 10])
async def test_a_page_as_large_as_the_commits_or_larger_holds_them_all(
    publishing: Publishing, limit: int
) -> None:
    await published(publishing)
    page = await publishing.lake.commits.list_commits(READER, publishing.collection_id, None, limit)
    assert [commit.new_version for commit in page.items] == [5, 4, 3]
    assert page.next_cursor is None


async def test_a_cursor_that_huron_did_not_make_is_refused(publishing: Publishing) -> None:
    commits = publishing.lake.commits
    for listing in (commits.list_files, commits.list_commits):
        with pytest.raises(InvalidCursor) as refused:
            await listing(READER, publishing.collection_id, "not-a-cursor", 1)
        assert (refused.value.code, refused.value.status) == ("INVALID_CURSOR", 400)
        assert refused.value.context == {"cursor": "not-a-cursor"}
