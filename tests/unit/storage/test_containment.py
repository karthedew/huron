"""No storage operation follows a symbolic link or leaves the lake, on both adapters."""

import copy
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path

import pytest

from huron.core.storage import DIRECTORY_MODE, LakePath, Storage, StorageError
from huron.core.storage.memory import MemoryStorage
from huron.core.storage.posix import PosixStorage
from huron.pkg.errors import HuronError
from tests.support.disk import plant_symlink, snapshot

SOURCE = LakePath.of("up", "src")
LINK = LakePath.of("a", "link")


@dataclass
class Lake:
    """A lake with the directory ``a`` (setgid) and the file ``up/src``."""

    storage: Storage
    unchanged: Callable[[], bool]


@pytest.fixture(params=["posix", "memory"])
def lake(request: pytest.FixtureRequest, tmp_path: Path) -> Iterator[Lake]:
    if request.param == "posix":
        (tmp_path / "lake").mkdir()
        (tmp_path / "outside" / "inner").mkdir(parents=True)
        (tmp_path / "outside" / "file").write_bytes(b"keep")
        storage: Storage = PosixStorage(tmp_path / "lake")
    else:
        storage = MemoryStorage(Path("/lake"))
    storage.make_directory(LakePath.of("a"), DIRECTORY_MODE)
    storage.make_directory(LakePath.of("up"), DIRECTORY_MODE)
    storage.write_bytes(SOURCE, b"new", 0o644)
    plant_symlink(storage, LINK)
    if isinstance(storage, MemoryStorage):
        nodes = copy.deepcopy(storage.nodes)
        storage.calls.clear()
        yield Lake(storage, lambda: storage.nodes == nodes and storage.calls == [])
    else:
        before = snapshot(tmp_path / "outside")
        yield Lake(storage, lambda: snapshot(tmp_path / "outside") == before)


def source_inode(storage: Storage) -> int:
    found = storage.stat(SOURCE)
    assert found is not None
    return found.inode


OPERATIONS: dict[str, Callable[[Storage, LakePath], object]] = {
    "stat": lambda storage, at: storage.stat(at),
    "read_bytes": lambda storage, at: storage.read_bytes(at),
    "is_empty": lambda storage, at: storage.is_empty(at),
    "open_file": lambda storage, at: storage.open_file(at),
    "make_directory": lambda storage, at: storage.make_directory(at, DIRECTORY_MODE),
    "make_inheriting_dir": lambda storage, at: storage.make_inheriting_dir(at),
    "set_mode": lambda storage, at: storage.set_mode(at, 0o700),
    "set_group": lambda storage, at: storage.set_group(at, 0),
    "write_bytes": lambda storage, at: storage.write_bytes(at, b"x", 0o644),
    "link": lambda storage, at: storage.link(
        SOURCE, at, inode=source_inode(storage), part_name=".part", backup_name=".prev"
    ),
    "rename": lambda storage, at: storage.rename(SOURCE, at),
    "rename_from": lambda storage, at: storage.rename(at, LakePath.of("up", "moved")),
    "remove_file": lambda storage, at: storage.remove_file(at),
    "remove_directory": lambda storage, at: storage.remove_directory(at),
    "walk": lambda storage, at: list(storage.walk(at)),
}


@pytest.mark.parametrize("operation", sorted(OPERATIONS))
@pytest.mark.parametrize("place", ["last", "intermediate"])
def test_a_symbolic_link_on_the_way_is_refused_and_nothing_changes(
    lake: Lake, operation: str, place: str
) -> None:
    at = LINK if place == "last" else LINK.joinpath("x")
    with pytest.raises(StorageError) as refused:
        OPERATIONS[operation](lake.storage, at)
    assert (refused.value.code, refused.value.status) == ("SYMLINK_IN_LAKE", 409)
    assert refused.value.context["path"] == "a/link"
    assert refused.value.message == (
        "a/link is a symbolic link. The lake must not contain symbolic links. Remove it."
    )
    assert lake.unchanged()


def test_walk_yields_a_link_and_never_enters_it(lake: Lake) -> None:
    entries = list(lake.storage.walk(LakePath.of("a")))
    assert [(e.names, e.kind) for e in entries] == [(("link",), "symlink")]
    assert lake.storage.is_empty(LakePath.of("a")) is False
    assert lake.unchanged()


@pytest.mark.parametrize("field", ["part_name", "backup_name"])
@pytest.mark.parametrize("name", ["../../outside/escaped", "x/y", "..", ""])
def test_link_refuses_a_part_or_backup_name_that_is_not_one_name(
    lake: Lake, field: str, name: str
) -> None:
    names = {"part_name": ".part", "backup_name": ".prev", field: name}
    inode = source_inode(lake.storage)
    with pytest.raises(HuronError) as refused:
        lake.storage.link(SOURCE, LakePath.of("a", "c.bin"), inode=inode, **names)
    assert (refused.value.code, refused.value.status) == ("NAME_INVALID", 422)
    assert lake.unchanged()
