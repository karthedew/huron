"""The plan of a commit request: its entries and their one fixed order."""

import random
import uuid
from collections.abc import Sequence

import pytest

from huron.core.lake.files.errors import CommitInvalid, FileNotRecorded
from huron.core.lake.publications.models import CommitAdd, CommitEntry, CommitRequest, EntryAction
from huron.core.lake.publications.planning import plan_entries
from huron.pkg.errors import HuronError
from huron.schema.naming import rel_path_key

SHA = "a" * 64
REMOVE_FILE = EntryAction.REMOVE_FILE
REMOVE_DIRECTORY = EntryAction.REMOVE_DIRECTORY
PRUNE_DIRECTORY = EntryAction.PRUNE_DIRECTORY
MAKE_DIRECTORY = EntryAction.MAKE_DIRECTORY
ADD_FILE = EntryAction.ADD_FILE


def upload(rel_path: str) -> uuid.UUID:
    """A fixed upload ID for each path, so the expected entries can name it."""
    return uuid.uuid5(uuid.NAMESPACE_URL, rel_path)


def request(adds: Sequence[str] = (), removes: Sequence[str] = ()) -> CommitRequest:
    return CommitRequest(
        uuid.uuid4(),
        uuid.uuid4(),
        1,
        tuple(CommitAdd(path, 4, SHA, upload(path)) for path in adds),
        tuple(removes),
        "host1",
    )


def plan(
    current: list[str], adds: tuple[str, ...] = (), removes: tuple[str, ...] = ()
) -> list[tuple[EntryAction, str]]:
    """The planned entries as ``(action, rel_path)`` pairs, in their order."""
    entries = plan_entries(current, request(adds, removes))
    assert [entry.ordinal for entry in entries] == list(range(len(entries)))
    return [(entry.action, entry.rel_path) for entry in entries]


def test_a_case_only_change_removes_the_recorded_spelling_then_adds_the_new_one() -> None:
    assert plan(["A.txt", "b.txt"], adds=("a.txt",)) == [
        (REMOVE_FILE, "A.txt"),
        (ADD_FILE, "a.txt"),
    ]


def test_a_case_only_change_of_a_directory_prunes_the_old_spelling_it_empties() -> None:
    assert plan(["Dir/a.txt"], adds=("dir/a.txt",)) == [
        (REMOVE_FILE, "Dir/a.txt"),
        (PRUNE_DIRECTORY, "Dir"),
        (MAKE_DIRECTORY, "dir"),
        (ADD_FILE, "dir/a.txt"),
    ]


def test_a_case_only_change_of_a_directory_keeps_the_old_spelling_that_holds_a_file() -> None:
    assert plan(["Dir/a.txt", "Dir/b.txt"], adds=("dir/a.txt",)) == [
        (REMOVE_FILE, "Dir/a.txt"),
        (MAKE_DIRECTORY, "dir"),
        (ADD_FILE, "dir/a.txt"),
    ]


def test_a_file_to_directory_change_removes_the_file_then_adds_below_it() -> None:
    assert plan(["a", "z.txt"], adds=("a/b",), removes=("a",)) == [
        (REMOVE_FILE, "a"),
        (MAKE_DIRECTORY, "a"),
        (ADD_FILE, "a/b"),
    ]


def test_a_directory_to_file_change_clears_the_deepest_paths_first() -> None:
    assert plan(["a/b/c", "a/d"], adds=("a",), removes=("a/b/c", "a/d")) == [
        (REMOVE_FILE, "a/b/c"),
        (REMOVE_DIRECTORY, "a/b"),
        (REMOVE_FILE, "a/d"),
        (REMOVE_DIRECTORY, "a"),
        (ADD_FILE, "a"),
    ]


def test_a_directory_with_another_spelling_than_the_added_file_is_pruned() -> None:
    assert plan(["A/x"], adds=("a",), removes=("a/X",)) == [
        (REMOVE_FILE, "A/x"),
        (PRUNE_DIRECTORY, "A"),
        (ADD_FILE, "a"),
    ]


def test_adds_make_each_new_directory_before_its_children() -> None:
    assert plan(["x.txt", "n/old.txt"], adds=("n/m/o.txt", "x.txt", "n/p.txt")) == [
        (ADD_FILE, "x.txt"),
        (MAKE_DIRECTORY, "n/m"),
        (ADD_FILE, "n/p.txt"),
        (ADD_FILE, "n/m/o.txt"),
    ]


def test_an_add_with_the_recorded_spelling_replaces_the_file_in_one_entry() -> None:
    entries = plan_entries(["a.txt"], request(adds=("a.txt",)))
    assert entries == (CommitEntry(0, ADD_FILE, "a.txt", upload("a.txt")),)


def test_only_add_entries_name_an_upload() -> None:
    entries = plan_entries(["a", "keep.txt"], request(adds=("a/b",), removes=("a",)))
    assert [entry.upload_id for entry in entries] == [None, None, upload("a/b")]


def test_a_removal_prunes_each_emptied_directory_up_to_the_collection_directory() -> None:
    assert plan(["d1/d2/d3/f.txt", "top.txt"], removes=("d1/d2/d3/f.txt",)) == [
        (REMOVE_FILE, "d1/d2/d3/f.txt"),
        (PRUNE_DIRECTORY, "d1/d2/d3"),
        (PRUNE_DIRECTORY, "d1/d2"),
        (PRUNE_DIRECTORY, "d1"),
    ]


def test_a_removal_of_a_top_level_file_prunes_nothing() -> None:
    assert plan(["top.txt", "keep.txt"], removes=("top.txt",)) == [(REMOVE_FILE, "top.txt")]


def test_a_directory_that_holds_a_kept_file_is_not_pruned() -> None:
    assert plan(["Dir/A.txt", "Dir/sub/b.txt"], removes=("dir/SUB/B.txt",)) == [
        (REMOVE_FILE, "Dir/sub/b.txt"),
        (PRUNE_DIRECTORY, "Dir/sub"),
    ]


def test_a_directory_that_an_add_uses_again_is_not_pruned() -> None:
    assert plan(["d/e/old.txt"], adds=("d/e/new.txt",), removes=("d/e/old.txt",)) == [
        (REMOVE_FILE, "d/e/old.txt"),
        (ADD_FILE, "d/e/new.txt"),
    ]


def test_clears_prunes_and_adds_mix_in_one_order() -> None:
    current = ["a/b/c.txt", "a/b/d/e.txt", "a/f.txt", "g/h.txt"]
    removes = ("a/b/c.txt", "a/b/d/e.txt", "g/h.txt")
    assert plan(current, adds=("a/b", "g2/i.txt"), removes=removes) == [
        (REMOVE_FILE, "a/b/d/e.txt"),
        (REMOVE_FILE, "a/b/c.txt"),
        (REMOVE_DIRECTORY, "a/b/d"),
        (REMOVE_DIRECTORY, "a/b"),
        (REMOVE_FILE, "g/h.txt"),
        (PRUNE_DIRECTORY, "g"),
        (MAKE_DIRECTORY, "g2"),
        (ADD_FILE, "a/b"),
        (ADD_FILE, "g2/i.txt"),
    ]


def test_an_empty_request_has_no_entries() -> None:
    assert plan_entries(["a.txt"], request()) == ()


def test_an_empty_collection_takes_new_files() -> None:
    assert plan([], adds=("d/e.txt",)) == [(MAKE_DIRECTORY, "d"), (ADD_FILE, "d/e.txt")]


def test_a_remove_of_a_path_that_is_not_recorded_is_refused() -> None:
    with pytest.raises(FileNotRecorded) as caught:
        plan(["a.txt"], removes=("a.txt", "b.txt", "c.txt"))
    assert caught.value.context == {"rel_paths": ["b.txt", "c.txt"]}


def test_a_refusal_names_at_most_twenty_missing_paths() -> None:
    removes = tuple(f"missing/{n:02}.txt" for n in range(25))
    with pytest.raises(FileNotRecorded) as caught:
        plan([], removes=removes)
    assert caught.value.context == {"rel_paths": list(removes[:20])}


def test_an_add_inside_an_added_file_is_refused() -> None:
    with pytest.raises(CommitInvalid) as caught:
        plan([], adds=("a", "A/b"))
    assert caught.value.context == {"rel_path": "A/b", "other": "a"}


def test_an_add_inside_a_recorded_file_that_stays_is_refused() -> None:
    with pytest.raises(CommitInvalid) as caught:
        plan(["Data"], adds=("data/b",))
    assert caught.value.context == {"rel_path": "data/b", "other": "Data"}


def test_an_add_over_a_directory_that_keeps_a_recorded_file_is_refused() -> None:
    with pytest.raises(CommitInvalid) as caught:
        plan(["a/b/c", "a/d", "a/e"], adds=("a",), removes=("a/d",))
    assert caught.value.context == {"rel_path": "a", "other": "a/b/c"}


def test_every_accepted_plan_reaches_its_tree_on_a_case_sensitive_filesystem() -> None:
    """Random trees and requests from a fixed seed, run on a strict model of the filesystem.

    Each step must find its precondition: a removed or pruned directory is empty, a new path is
    free and its parent exists. The end tree holds exactly the kept and added files, and every
    directory below the collection directory holds a file.
    """
    rng = random.Random(20261110)
    accepted = 0
    for _ in range(4000):
        current = _tree(rng)
        removes = [_respell(rng, path) for path in current if rng.random() < 0.5]
        adds = [_path(rng) for _ in range(rng.randrange(4))]
        try:
            entries = plan_entries(current, request(adds, removes))
        except HuronError:
            continue
        accepted += 1
        gone = {rel_path_key(path) for path in [*removes, *adds]}
        expected = {path for path in current if rel_path_key(path) not in gone} | set(adds)
        files, directories = _run(current, entries)
        assert (files, directories) == (expected, _parents_of(expected)), (current, entries)
    assert accepted > 1000


def _tree(rng: random.Random) -> list[str]:
    """Recorded files with unique keys, none inside another file, compared by key."""
    files: dict[str, str] = {}
    for _ in range(rng.randrange(6)):
        path = _path(rng)
        key = rel_path_key(path)
        clash = key in files or any(
            other.startswith(f"{key}/") or key.startswith(f"{other}/") for other in files
        )
        if not clash:
            files[key] = path
    return list(files.values())


def _path(rng: random.Random) -> str:
    return "/".join(rng.choice("aAbB") for _ in range(rng.randrange(1, 4)))


def _respell(rng: random.Random, path: str) -> str:
    return "".join(char.swapcase() if rng.random() < 0.3 else char for char in path)


def _parents_of(paths: set[str]) -> set[str]:
    return {path.rsplit("/", end)[0] for path in paths for end in range(1, path.count("/") + 1)}


def _run(current: list[str], entries: Sequence[CommitEntry]) -> tuple[set[str], set[str]]:
    """Apply the entries to a case-sensitive tree, checking each step's precondition."""
    files, directories = set(current), _parents_of(set(current))
    for entry in entries:
        path = entry.rel_path
        parent = path.rpartition("/")[0]
        below = any(each.startswith(f"{path}/") for each in files | directories)
        if entry.action is REMOVE_FILE:
            files.remove(path)
        elif entry.action in (REMOVE_DIRECTORY, PRUNE_DIRECTORY):
            assert not below, entry
            directories.remove(path)
        else:
            assert parent == "" or parent in directories, entry
            assert path not in directories, entry
            if entry.action is MAKE_DIRECTORY:
                assert path not in files, entry
                directories.add(path)
            else:
                files.add(path)
    return files, directories
