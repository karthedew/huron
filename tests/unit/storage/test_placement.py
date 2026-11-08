"""Placing a finished upload on an in-memory lake: measure, link, undo."""

import hashlib
import uuid
from pathlib import Path

import pytest

from huron.core.lake.uploads.errors import UploadSizeMismatch
from huron.core.storage import (
    DIRECTORY_MODE,
    FILE_MODE,
    UPLOAD_DIR,
    CollectionDirectoryMissing,
    Linked,
    Measured,
    Placer,
    SourceGone,
)
from huron.core.storage.memory import MemoryStorage
from tests.support.disk import LAKE, memory_lake

UPLOAD_ID = uuid.UUID("0192b6a0-0000-7000-8000-0000000000aa")
DATA = b"solar wind"
SHA = hashlib.sha256(DATA).hexdigest()
COLLECTION = LAKE / "helio" / "heliophysics" / "solar-wind" / "run7"
PART = f".c.bin.{UPLOAD_ID}.huron-part"
BACKUP = f".c.bin.{UPLOAD_ID}.huron-prev"


@pytest.fixture
def storage() -> MemoryStorage:
    """The in-memory lake with tusd's directory, a received upload and a collection directory."""
    lake = memory_lake()
    lake.make_directory(LAKE / UPLOAD_DIR, 0o700)
    lake.write_bytes(LAKE / UPLOAD_DIR / str(UPLOAD_ID), DATA, 0o600)
    lake.write_bytes(LAKE / UPLOAD_DIR / f"{UPLOAD_ID}.info", b"{}", 0o600)
    lake.add_root(COLLECTION.parent)
    lake.nodes[COLLECTION.parent].mode = DIRECTORY_MODE
    lake.make_inheriting_dir(COLLECTION)
    return lake


@pytest.fixture
def placer(storage: MemoryStorage) -> Placer:
    return Placer(storage, LAKE)


def source(placer: Placer) -> Path:
    return placer.upload_file(UPLOAD_ID)


def link(placer: Placer, destination: Path) -> Linked:
    return placer.link(
        source(placer), placer.info_file(UPLOAD_ID), destination, COLLECTION, UPLOAD_ID
    )


def test_tusds_files_lie_in_the_upload_directory(placer: Placer) -> None:
    assert placer.upload_file(UPLOAD_ID) == LAKE / UPLOAD_DIR / str(UPLOAD_ID)
    assert placer.info_file(UPLOAD_ID) == LAKE / UPLOAD_DIR / f"{UPLOAD_ID}.info"


def test_measure_reads_size_hash_and_inode_and_makes_the_file_readable(
    storage: MemoryStorage, placer: Placer
) -> None:
    inode = storage.inode(source(placer))
    assert inode is not None
    measured = placer.measure(source(placer), len(DATA))
    assert measured == Measured(len(DATA), SHA, inode)
    assert storage.owner(source(placer)).mode == FILE_MODE
    assert placer.measure(source(placer), len(DATA)) == measured


def test_measure_refuses_another_size_before_the_hash(
    storage: MemoryStorage, placer: Placer
) -> None:
    with pytest.raises(UploadSizeMismatch) as raised:
        placer.measure(source(placer), len(DATA) + 1)
    assert raised.value.context == {"declared": len(DATA) + 1, "received": len(DATA)}
    assert storage.owner(source(placer)).mode == 0o600


def test_measure_of_a_missing_upload_is_none(storage: MemoryStorage, placer: Placer) -> None:
    storage.remove_file(source(placer))
    assert placer.measure(source(placer), len(DATA)) is None


def test_an_inode_above_two_to_the_63_survives_measure_and_undo(
    storage: MemoryStorage, placer: Placer
) -> None:
    storage.nodes[source(placer)].inode = 2**64 - 3
    measured = placer.measure(source(placer), len(DATA))
    assert measured is not None and measured.inode == 2**64 - 3
    destination = COLLECTION / "c.bin"
    linked = link(placer, destination)
    assert storage.inode(destination) == 2**64 - 3
    placer.undo(destination, measured.inode, linked)
    assert not storage.exists(destination)


def test_link_makes_inheriting_directories_and_removes_tusds_files(
    storage: MemoryStorage, placer: Placer
) -> None:
    inode = storage.inode(source(placer))
    destination = COLLECTION / "a" / "b" / "c.bin"
    linked = link(placer, destination)
    assert linked == Linked((COLLECTION / "a", COLLECTION / "a" / "b"), None)
    for directory in linked.made_dirs:
        assert storage.owner(directory).mode == DIRECTORY_MODE
    assert storage.inode(destination) == inode
    assert storage.read_bytes(destination) == DATA
    assert not storage.exists(source(placer))
    assert not storage.exists(placer.info_file(UPLOAD_ID))


def test_link_into_existing_directories_makes_none(storage: MemoryStorage, placer: Placer) -> None:
    storage.make_inheriting_dir(COLLECTION / "a")
    assert link(placer, COLLECTION / "a" / "c.bin") == Linked((), None)


@pytest.mark.parametrize("stale", [False, True], ids=["fresh", "stale-backup"])
def test_link_replaces_an_existing_file_and_keeps_its_bytes_in_the_backup(
    storage: MemoryStorage, placer: Placer, stale: bool
) -> None:
    destination = COLLECTION / "c.bin"
    storage.write_bytes(destination, b"old")
    old_inode = storage.inode(destination)
    storage.write_bytes(COLLECTION / PART, b"stale")
    if stale:
        storage.write_bytes(COLLECTION / BACKUP, b"stale")
    linked = link(placer, destination)
    assert linked == Linked((), COLLECTION / BACKUP)
    assert placer.backup_file(destination, UPLOAD_ID) == COLLECTION / BACKUP
    assert storage.read_bytes(destination) == DATA
    assert (storage.read_bytes(COLLECTION / BACKUP), storage.inode(COLLECTION / BACKUP)) == (
        b"old",
        old_inode,
    )
    assert ("rename", destination) in storage.calls
    assert not storage.exists(COLLECTION / PART)


def test_drop_backup_removes_the_backup_once(storage: MemoryStorage, placer: Placer) -> None:
    destination = COLLECTION / "c.bin"
    storage.write_bytes(destination, b"old")
    link(placer, destination)
    placer.drop_backup(destination, UPLOAD_ID)
    assert not storage.exists(COLLECTION / BACKUP)
    placer.drop_backup(destination, UPLOAD_ID)
    assert storage.read_bytes(destination) == DATA


def test_link_without_tusds_info_file_still_succeeds(
    storage: MemoryStorage, placer: Placer
) -> None:
    storage.remove_file(placer.info_file(UPLOAD_ID))
    link(placer, COLLECTION / "c.bin")
    assert storage.read_bytes(COLLECTION / "c.bin") == DATA


def test_link_never_makes_the_collection_directory(storage: MemoryStorage, placer: Placer) -> None:
    storage.remove_directory(COLLECTION)
    with pytest.raises(CollectionDirectoryMissing, match="huron adm repair") as raised:
        link(placer, COLLECTION / "a" / "c.bin")
    assert (raised.value.code, raised.value.context) == (
        "STORAGE_FAILED",
        {"path": str(COLLECTION)},
    )
    assert not storage.exists(COLLECTION)
    assert storage.exists(source(placer))


def test_link_of_a_gone_source_removes_the_directories_it_made(
    storage: MemoryStorage, placer: Placer
) -> None:
    link(placer, COLLECTION / "c.bin")
    with pytest.raises(SourceGone) as raised:
        link(placer, COLLECTION / "a" / "b" / "c.bin")
    assert raised.value.context == {"path": str(source(placer))}
    assert not storage.exists(COLLECTION / "a")
    assert storage.read_bytes(COLLECTION / "c.bin") == DATA


def test_undo_removes_the_placed_file_and_the_directories_link_made(
    storage: MemoryStorage, placer: Placer
) -> None:
    measured = placer.measure(source(placer), len(DATA))
    assert measured is not None
    destination = COLLECTION / "a" / "b" / "c.bin"
    linked = link(placer, destination)
    placer.undo(destination, measured.inode, linked)
    assert not storage.exists(COLLECTION / "a")
    assert storage.is_directory(COLLECTION)
    placer.undo(destination, measured.inode, linked)


def test_undo_of_an_overwrite_restores_the_old_bytes_and_inode(
    storage: MemoryStorage, placer: Placer
) -> None:
    measured = placer.measure(source(placer), len(DATA))
    assert measured is not None
    destination = COLLECTION / "c.bin"
    storage.write_bytes(destination, b"old")
    old_inode = storage.inode(destination)
    placer.undo(destination, measured.inode, link(placer, destination))
    assert (storage.read_bytes(destination), storage.inode(destination)) == (b"old", old_inode)
    assert not storage.exists(COLLECTION / BACKUP)


def test_undo_after_an_interrupted_overwrite_restores_the_old_bytes_and_inode(
    storage: MemoryStorage, placer: Placer
) -> None:
    measured = placer.measure(source(placer), len(DATA))
    assert measured is not None
    destination = COLLECTION / "c.bin"
    storage.write_bytes(destination, b"old")
    old_inode = storage.inode(destination)
    # An earlier attempt stopped after its rename, before it removed tusd's files.
    storage.nodes[COLLECTION / BACKUP] = storage.nodes[destination]
    storage.nodes[destination] = storage.nodes[source(placer)]
    linked = link(placer, destination)
    assert linked == Linked((), COLLECTION / BACKUP)
    placer.undo(destination, measured.inode, linked)
    assert (storage.read_bytes(destination), storage.inode(destination)) == (b"old", old_inode)
    assert not storage.exists(COLLECTION / BACKUP)


def test_undo_keeps_a_later_placement_and_directories_that_are_not_empty(
    storage: MemoryStorage, placer: Placer
) -> None:
    measured = placer.measure(source(placer), len(DATA))
    assert measured is not None
    destination = COLLECTION / "a" / "c.bin"
    linked = link(placer, destination)
    storage.write_bytes(destination, b"a later upload")
    placer.undo(destination, measured.inode, linked)
    assert storage.read_bytes(destination) == b"a later upload"
    assert storage.is_directory(COLLECTION / "a")


def test_undo_of_an_overwrite_that_a_later_placement_replaced_drops_the_backup(
    storage: MemoryStorage, placer: Placer
) -> None:
    measured = placer.measure(source(placer), len(DATA))
    assert measured is not None
    destination = COLLECTION / "c.bin"
    storage.write_bytes(destination, b"old")
    linked = link(placer, destination)
    storage.write_bytes(destination, b"a later upload")
    placer.undo(destination, measured.inode, linked)
    assert storage.read_bytes(destination) == b"a later upload"
    assert not storage.exists(COLLECTION / BACKUP)


def test_measure_destination_reads_a_file_another_attempt_placed(
    storage: MemoryStorage, placer: Placer
) -> None:
    destination = COLLECTION / "c.bin"
    link(placer, destination)
    inode = storage.inode(destination)
    assert inode is not None
    assert placer.measure_destination(destination, len(DATA)) == Measured(len(DATA), SHA, inode)
    assert placer.measure_destination(destination, len(DATA) + 1) is None
    assert placer.measure_destination(COLLECTION / "missing", len(DATA)) is None
