"""``prune``: the clean-up of empty directories below a collection, on both adapters."""

from pathlib import Path

import pytest

from huron.core.storage import DIRECTORY_MODE, LakePath, Storage, prune
from huron.core.storage.memory import MemoryStorage
from huron.core.storage.posix import PosixStorage

COLLECTION = LakePath.of("helio", "run7")
A = COLLECTION.joinpath("a")
B = A.joinpath("b")


@pytest.fixture(params=["posix", "memory"])
def storage(request: pytest.FixtureRequest, tmp_path: Path) -> Storage:
    lake: Storage
    if request.param == "posix":
        (tmp_path / "lake").mkdir()
        lake = PosixStorage(tmp_path / "lake")
    else:
        lake = MemoryStorage(Path("/lake"))
    for directory in (COLLECTION.parent, COLLECTION, A, B):
        lake.make_directory(directory, DIRECTORY_MODE)
    return lake


def test_prune_removes_empty_directories_innermost_first(storage: Storage) -> None:
    prune(storage, (A, B))
    assert storage.stat(A) is None
    assert storage.is_empty(COLLECTION)


def test_prune_stops_at_the_first_directory_that_is_not_empty(storage: Storage) -> None:
    storage.write_bytes(A.joinpath("keep"), b"", 0o644)
    prune(storage, (A, B))
    assert storage.stat(B) is None
    assert storage.read_bytes(A.joinpath("keep")) == b""


def test_prune_passes_over_a_directory_that_is_gone(storage: Storage) -> None:
    storage.remove_directory(B)
    prune(storage, (A, B))
    assert storage.stat(A) is None


def test_prune_of_nothing_keeps_the_collection(storage: Storage) -> None:
    prune(storage, ())
    assert storage.stat(B) is not None
    assert storage.stat(COLLECTION) is not None
