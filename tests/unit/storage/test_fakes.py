"""The views of an in-memory share that the CLI tests use: a subtree and a read-only share."""

import hashlib

import pytest

from huron.core.storage import LakePath, SealedFile, Storage
from huron.core.storage.memory import MemoryStorage
from tests.fakes.storage import WRITES, ReadOnlyShare, Subtree
from tests.support.disk import LAKE

BASE = LakePath.of("roots", "x")
#: The public methods of the ``Storage`` port.
PORT = frozenset(name for name in dir(Storage) if not name.startswith("_"))


@pytest.fixture
def share() -> MemoryStorage:
    """An in-memory share with the directory ``roots/x`` and the file ``roots/x/upload``."""
    memory = MemoryStorage(LAKE, uid=1000, gid=1000)
    memory.add_directory(BASE, uid=1000)
    memory.write_bytes(BASE.joinpath("upload"), b"payload", 0o600)
    return memory


def test_the_subtree_has_every_method_of_the_port() -> None:
    assert PORT.issubset(dir(Subtree))


def test_the_writes_are_methods_of_the_port() -> None:
    assert WRITES <= PORT
    assert {"copy_sealed", "link_once"} <= WRITES
    assert "sync_directory" not in WRITES


def test_the_subtree_copies_links_and_syncs_below_its_base(share: MemoryStorage) -> None:
    subtree = Subtree(share, BASE)
    sealed = subtree.copy_sealed(LakePath.of("upload"), LakePath.of("object"), 7)
    copy = share.stat(BASE.joinpath("object"))
    assert copy is not None
    assert sealed == SealedFile(7, hashlib.sha256(b"payload").hexdigest(), copy.inode)
    subtree.link_once(LakePath.of("object"), LakePath.of("a.bin"))
    assert share.read_bytes(BASE.joinpath("a.bin")) == b"payload"
    subtree.sync_directory(LakePath())
    assert share.calls[-1] == ("sync", BASE)
    assert subtree.in_group(1000) is True


@pytest.mark.parametrize("method", ["copy_sealed", "link_once"])
def test_the_read_only_share_refuses_a_copy_and_a_link(share: MemoryStorage, method: str) -> None:
    source, destination = BASE.joinpath("upload"), BASE.joinpath("c")
    with pytest.raises(AssertionError) as refused:
        getattr(ReadOnlyShare(share), method)(source, destination)
    assert str(refused.value) == (
        f"a write to the read-only share: {method}{(source, destination)}"
    )
    assert share.stat(BASE.joinpath("c")) is None


def test_the_read_only_share_allows_a_sync(share: MemoryStorage) -> None:
    ReadOnlyShare(share).sync_directory(BASE)
    assert share.calls[-1] == ("sync", BASE)
