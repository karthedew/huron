"""Placing a finished upload: measure, link, undo, on both adapters."""

import hashlib
import uuid
from pathlib import Path

import pytest

from huron.core.lake.uploads.errors import UploadSizeMismatch
from huron.core.storage import (
    DIRECTORY_MODE,
    FILE_MODE,
    UPLOAD_DIR_MODE,
    UPLOADS,
    CollectionDirectoryMissing,
    LakePath,
    Linked,
    Measured,
    Outcome,
    Placer,
    SourceGone,
    Storage,
    StorageError,
    SymlinkInLake,
)
from huron.core.storage.memory import MemoryStorage
from huron.core.storage.posix import PosixStorage
from tests.support.disk import memory_lake, plant_symlink

UPLOAD_ID = uuid.UUID("0192b6a0-0000-7000-8000-0000000000aa")
DATA = b"solar wind"
SHA = hashlib.sha256(DATA).hexdigest()
COLLECTION = LakePath.of("helio", "heliophysics", "solar-wind", "run7")
SOURCE = UPLOADS.joinpath(str(UPLOAD_ID))
INFO = UPLOADS.joinpath(f"{UPLOAD_ID}.info")
PART = COLLECTION.joinpath(f".c.bin.{UPLOAD_ID}.huron-part")
BACKUP = COLLECTION.joinpath(f".c.bin.{UPLOAD_ID}.huron-prev")
TARGET = COLLECTION.joinpath("c.bin")


def prepared(storage: Storage) -> Storage:
    """``storage`` with tusd's directory, a received upload and a collection directory."""
    storage.make_directory(UPLOADS, UPLOAD_DIR_MODE)
    storage.write_bytes(SOURCE, DATA, 0o600)
    storage.write_bytes(INFO, b"{}", 0o600)
    for size in range(1, len(COLLECTION.names) + 1):
        storage.make_directory(LakePath(COLLECTION.names[:size]), DIRECTORY_MODE)
    return storage


@pytest.fixture(params=["posix", "memory"])
def storage(request: pytest.FixtureRequest, tmp_path: Path) -> Storage:
    if request.param == "posix":
        (tmp_path / "lake").mkdir()
        return prepared(PosixStorage(tmp_path / "lake"))
    return prepared(memory_lake())


@pytest.fixture
def memory() -> MemoryStorage:
    lake = memory_lake()
    prepared(lake)
    return lake


def inode(storage: Storage, location: LakePath) -> int:
    found = storage.stat(location)
    assert found is not None
    return found.inode


def link(storage: Storage, target: LakePath = TARGET, measured: int | None = None) -> Linked:
    source = inode(storage, SOURCE) if measured is None else measured
    return Placer(storage).link(UPLOAD_ID, COLLECTION, target, source)


def measure(storage: Storage) -> Measured:
    measured = Placer(storage).measure(UPLOAD_ID, len(DATA))
    assert measured is not None
    return measured


def test_measure_reads_size_hash_and_inode_and_makes_the_file_readable(storage: Storage) -> None:
    measured = measure(storage)
    assert measured == Measured(len(DATA), SHA, inode(storage, SOURCE))
    found = storage.stat(SOURCE)
    assert found is not None and found.mode == FILE_MODE
    assert measure(storage) == measured


def test_measure_refuses_another_size_before_the_hash(storage: Storage) -> None:
    with pytest.raises(UploadSizeMismatch) as raised:
        Placer(storage).measure(UPLOAD_ID, len(DATA) + 1)
    assert raised.value.context == {"declared": len(DATA) + 1, "received": len(DATA)}
    found = storage.stat(SOURCE)
    assert found is not None and found.mode == 0o600


def test_measure_of_a_missing_upload_is_none(storage: Storage) -> None:
    storage.remove_file(SOURCE)
    assert Placer(storage).measure(UPLOAD_ID, len(DATA)) is None


def test_an_inode_above_two_to_the_63_survives_measure_and_undo(memory: MemoryStorage) -> None:
    memory.nodes[SOURCE].inode = 2**64 - 3
    measured = measure(memory)
    assert measured.inode == 2**64 - 3
    linked = link(memory)
    assert inode(memory, TARGET) == 2**64 - 3
    Placer(memory).undo(TARGET, measured.inode, linked)
    assert memory.stat(TARGET) is None


def test_link_makes_inheriting_directories_and_removes_tusds_files(storage: Storage) -> None:
    source = inode(storage, SOURCE)
    target = COLLECTION.joinpath("a", "b", "c.bin")
    linked = link(storage, target)
    assert linked == Linked((COLLECTION.joinpath("a"), COLLECTION.joinpath("a", "b")), None)
    for directory in linked.made_dirs:
        found = storage.stat(directory)
        assert found is not None and found.mode == DIRECTORY_MODE
    assert inode(storage, target) == source
    assert storage.read_bytes(target) == DATA
    assert storage.stat(SOURCE) is None
    assert storage.stat(INFO) is None


def test_link_into_existing_directories_makes_none(storage: Storage) -> None:
    storage.make_inheriting_dir(COLLECTION.joinpath("a"))
    assert link(storage, COLLECTION.joinpath("a", "c.bin")) == Linked((), None)


@pytest.mark.parametrize("stale", [False, True], ids=["fresh", "stale-backup"])
def test_link_replaces_an_existing_file_and_keeps_its_bytes_in_the_backup(
    storage: Storage, stale: bool
) -> None:
    storage.write_bytes(TARGET, b"old", 0o644)
    old_inode = inode(storage, TARGET)
    storage.write_bytes(PART, b"stale", 0o644)
    if stale:
        storage.write_bytes(BACKUP, b"stale", 0o644)
    assert link(storage) == Linked((), BACKUP)
    assert storage.read_bytes(TARGET) == DATA
    assert (storage.read_bytes(BACKUP), inode(storage, BACKUP)) == (b"old", old_inode)
    assert storage.stat(PART) is None


def test_drop_backup_removes_the_backup_once(storage: Storage) -> None:
    storage.write_bytes(TARGET, b"old", 0o644)
    link(storage)
    Placer(storage).drop_backup(TARGET, UPLOAD_ID)
    assert storage.stat(BACKUP) is None
    Placer(storage).drop_backup(TARGET, UPLOAD_ID)
    assert storage.read_bytes(TARGET) == DATA


def test_link_without_tusds_info_file_still_succeeds(storage: Storage) -> None:
    storage.remove_file(INFO)
    link(storage)
    assert storage.read_bytes(TARGET) == DATA


def test_link_never_makes_the_collection_directory(storage: Storage) -> None:
    storage.remove_directory(COLLECTION)
    with pytest.raises(CollectionDirectoryMissing) as raised:
        link(storage, COLLECTION.joinpath("a", "c.bin"))
    assert (raised.value.code, raised.value.message, raised.value.context) == (
        "STORAGE_FAILED",
        f"the collection directory {COLLECTION} does not exist. To make the directory again,"
        " run huron adm repair for the collection",
        {"path": str(COLLECTION)},
    )
    assert storage.stat(COLLECTION) is None
    assert storage.stat(SOURCE) is not None


def test_link_refuses_a_collection_that_is_a_file(storage: Storage) -> None:
    storage.remove_directory(COLLECTION)
    storage.write_bytes(COLLECTION, b"", 0o644)
    with pytest.raises(StorageError) as raised:
        link(storage)
    assert (raised.value.code, raised.value.message, raised.value.context) == (
        "STORAGE_FAILED",
        f"{COLLECTION} is not a directory",
        {"path": str(COLLECTION)},
    )
    assert storage.stat(SOURCE) is not None


@pytest.mark.parametrize(
    "target", [COLLECTION, COLLECTION.parent.joinpath("c.bin"), LakePath.of("geo", "c.bin")]
)
def test_link_refuses_a_target_that_is_not_below_its_collection(
    storage: Storage, target: LakePath
) -> None:
    with pytest.raises(ValueError, match="is not below the collection directory"):
        link(storage, target)
    assert storage.stat(SOURCE) is not None


def test_link_of_a_gone_source_removes_the_directories_it_made(storage: Storage) -> None:
    measured = inode(storage, SOURCE)
    link(storage)
    with pytest.raises(SourceGone) as raised:
        link(storage, COLLECTION.joinpath("a", "b", "c.bin"), measured)
    assert raised.value.context == {"path": str(SOURCE)}
    assert storage.stat(COLLECTION.joinpath("a")) is None
    assert storage.read_bytes(TARGET) == DATA


def test_link_of_a_replaced_source_links_nothing_and_prunes(storage: Storage) -> None:
    measured = inode(storage, SOURCE)
    storage.remove_file(SOURCE)
    storage.write_bytes(SOURCE, DATA, 0o600)
    with pytest.raises(SourceGone):
        link(storage, COLLECTION.joinpath("a", "c.bin"), measured)
    assert storage.stat(COLLECTION.joinpath("a")) is None
    assert storage.stat(SOURCE) is not None
    assert storage.is_empty(COLLECTION)


def test_link_of_a_source_that_is_a_link_fails_and_prunes(storage: Storage) -> None:
    measured = inode(storage, SOURCE)
    storage.remove_file(SOURCE)
    plant_symlink(storage, SOURCE)
    with pytest.raises(SymlinkInLake) as raised:
        link(storage, COLLECTION.joinpath("a", "b", "c.bin"), measured)
    assert raised.value.context == {"path": str(SOURCE)}
    assert storage.stat(COLLECTION.joinpath("a")) is None
    assert storage.is_empty(COLLECTION)


def test_link_without_the_upload_directory_fails_and_prunes(storage: Storage) -> None:
    measured = inode(storage, SOURCE)
    storage.remove_file(SOURCE)
    storage.remove_file(INFO)
    storage.remove_directory(UPLOADS)
    with pytest.raises(StorageError) as raised:
        link(storage, COLLECTION.joinpath("a", "c.bin"), measured)
    assert (raised.value.code, raised.value.message) == (
        "STORAGE_FAILED",
        f"{SOURCE} does not exist",
    )
    assert storage.is_empty(COLLECTION)


def test_a_directory_that_fails_after_another_was_made_prunes_the_made_one(
    storage: Storage, monkeypatch: pytest.MonkeyPatch
) -> None:
    real = storage.make_inheriting_dir

    def second_fails(location: LakePath) -> bool:
        if location.name == "b":
            raise StorageError(f"{location}: Input/output error", {"path": str(location)})
        return real(location)

    monkeypatch.setattr(storage, "make_inheriting_dir", second_fails)
    with pytest.raises(StorageError) as raised:
        link(storage, COLLECTION.joinpath("a", "b", "c.bin"))
    failed = str(COLLECTION.joinpath("a", "b"))
    assert (raised.value.message, raised.value.context) == (
        f"{failed}: Input/output error",
        {"path": failed},
    )
    assert storage.is_empty(COLLECTION)
    assert storage.stat(SOURCE) is not None


def test_a_failed_prune_keeps_the_error_of_the_link(
    storage: Storage, monkeypatch: pytest.MonkeyPatch
) -> None:
    measured = inode(storage, SOURCE)
    storage.remove_file(SOURCE)

    def refuse(location: LakePath) -> Outcome:
        raise StorageError(f"permission denied on {location}", {"path": str(location)})

    monkeypatch.setattr(storage, "remove_directory", refuse)
    with pytest.raises(SourceGone):
        link(storage, COLLECTION.joinpath("a", "c.bin"), measured)
    assert storage.stat(COLLECTION.joinpath("a")) is not None


def test_undo_removes_the_placed_file_and_the_directories_link_made(storage: Storage) -> None:
    measured = measure(storage)
    target = COLLECTION.joinpath("a", "b", "c.bin")
    linked = link(storage, target)
    Placer(storage).undo(target, measured.inode, linked)
    assert storage.stat(COLLECTION.joinpath("a")) is None
    assert storage.is_empty(COLLECTION)
    Placer(storage).undo(target, measured.inode, linked)


def test_undo_of_an_overwrite_restores_the_old_bytes_and_inode(storage: Storage) -> None:
    measured = measure(storage)
    storage.write_bytes(TARGET, b"old", 0o644)
    old_inode = inode(storage, TARGET)
    Placer(storage).undo(TARGET, measured.inode, link(storage))
    assert (storage.read_bytes(TARGET), inode(storage, TARGET)) == (b"old", old_inode)
    assert storage.stat(BACKUP) is None


def test_undo_after_an_interrupted_overwrite_restores_the_old_bytes_and_inode(
    memory: MemoryStorage,
) -> None:
    measured = measure(memory)
    memory.write_bytes(TARGET, b"old", 0o644)
    old_inode = inode(memory, TARGET)
    # An earlier attempt stopped after its rename, before it removed tusd's files.
    memory.nodes[BACKUP] = memory.nodes[TARGET]
    memory.nodes[TARGET] = memory.nodes[SOURCE]
    linked = link(memory)
    assert linked == Linked((), BACKUP)
    Placer(memory).undo(TARGET, measured.inode, linked)
    assert (memory.read_bytes(TARGET), inode(memory, TARGET)) == (b"old", old_inode)
    assert memory.stat(BACKUP) is None


def test_undo_keeps_a_later_placement_and_directories_that_are_not_empty(
    storage: Storage,
) -> None:
    measured = measure(storage)
    target = COLLECTION.joinpath("a", "c.bin")
    linked = link(storage, target)
    storage.write_bytes(target, b"a later upload", 0o644)
    Placer(storage).undo(target, measured.inode, linked)
    assert storage.read_bytes(target) == b"a later upload"
    assert storage.stat(COLLECTION.joinpath("a")) is not None


def test_undo_of_an_overwrite_that_a_later_placement_replaced_drops_the_backup(
    storage: Storage,
) -> None:
    measured = measure(storage)
    storage.write_bytes(TARGET, b"old", 0o644)
    linked = link(storage)
    storage.write_bytes(TARGET, b"a later upload", 0o644)
    Placer(storage).undo(TARGET, measured.inode, linked)
    assert storage.read_bytes(TARGET) == b"a later upload"
    assert storage.stat(BACKUP) is None


def test_measure_destination_reads_a_file_another_attempt_placed(storage: Storage) -> None:
    link(storage)
    placer = Placer(storage)
    assert placer.measure_destination(TARGET, len(DATA)) == Measured(
        len(DATA), SHA, inode(storage, TARGET)
    )
    assert placer.measure_destination(TARGET, len(DATA) + 1) is None
    assert placer.measure_destination(COLLECTION.joinpath("missing"), len(DATA)) is None
