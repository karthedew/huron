"""tusd's files of an upload and the seal into the object area, on both adapters."""

import errno
import hashlib
import json
import uuid
from pathlib import Path
from typing import Any

import pytest

from huron.core.storage import (
    OBJECT_DIR_MODE,
    UPLOAD_DIR_MODE,
    UPLOADS,
    Completeness,
    Inspection,
    LakePath,
    SealedFile,
    Sealer,
    SourceGone,
    SourceSizeMismatch,
    Storage,
    StorageError,
)
from huron.core.storage.memory import MemoryStorage
from huron.core.storage.posix import PosixStorage
from tests.support.disk import LAKE

UPLOAD = uuid.UUID("0190d5a4-0000-7000-8000-0000000000aa")
DATA = b"solar wind"
AREA = LakePath.of("helio", ".huron-objects")
OBJECT = AREA.joinpath(str(UPLOAD))


@pytest.fixture(params=["posix", "memory"])
def storage(request: pytest.FixtureRequest, tmp_path: Path) -> Storage:
    """A lake with ``.tus-uploads`` and the organization directory ``helio``."""
    lake: Storage
    if request.param == "posix":
        (tmp_path / "lake").mkdir()
        lake = PosixStorage(tmp_path / "lake")
    else:
        lake = MemoryStorage(LAKE, uid=1000, gid=1000)
    lake.make_directory(UPLOADS, UPLOAD_DIR_MODE)
    lake.make_directory(LakePath.of("helio"), 0o2751)
    return lake


def put(storage: Storage, name: str, data: bytes) -> None:
    storage.write_bytes(UPLOADS.joinpath(name), data, 0o600)


def received(storage: Storage, info: dict[str, Any] | None = None, data: bytes = DATA) -> None:
    """tusd's data file of :data:`UPLOAD` and its ``.info`` file with ``info``."""
    put(storage, str(UPLOAD), data)
    document = {"ID": str(UPLOAD), "Size": len(DATA), "SizeIsDeferred": False}
    put(storage, f"{UPLOAD}.info", json.dumps(document if info is None else info).encode())


def check(storage: Storage, size: int = len(DATA), *, locked: bool = True) -> Inspection:
    return Sealer(storage).check(UPLOAD, size, locked=locked)


def test_a_complete_upload_is_complete(storage: Storage) -> None:
    received(storage)
    assert check(storage) == Inspection(Completeness.COMPLETE)


def test_an_info_file_without_the_deferred_flag_is_not_deferred(storage: Storage) -> None:
    received(storage, {"Size": len(DATA)})
    assert check(storage) == Inspection(Completeness.COMPLETE)


def test_a_lock_file_makes_a_complete_upload_locked_unless_the_hook_checks(
    storage: Storage,
) -> None:
    received(storage)
    put(storage, f"{UPLOAD}.lock", b"1")
    assert check(storage) == Inspection(Completeness.LOCKED)
    assert check(storage, locked=False) == Inspection(Completeness.COMPLETE)


def test_a_deferred_length_is_deferred(storage: Storage) -> None:
    received(storage, {"Size": 0, "SizeIsDeferred": True}, b"")
    assert check(storage, 0) == Inspection(Completeness.DEFERRED)


def test_a_short_or_missing_data_file_is_incomplete_also_with_a_lock(storage: Storage) -> None:
    received(storage, data=DATA[:-1])
    put(storage, f"{UPLOAD}.lock", b"1")
    assert check(storage) == Inspection(Completeness.INCOMPLETE)
    storage.remove_file(UPLOADS.joinpath(str(UPLOAD)))
    assert check(storage, locked=False) == Inspection(Completeness.INCOMPLETE)
    storage.make_directory(UPLOADS.joinpath(str(UPLOAD)), 0o700)
    assert check(storage) == Inspection(Completeness.INCOMPLETE)


@pytest.mark.parametrize(
    ("data", "declared", "size", "received_size"),
    [
        (DATA + b"!", len(DATA), len(DATA), len(DATA) + 1),  # the data file is too long
        (DATA, len(DATA), len(DATA) + 1, len(DATA)),  # the attempt declares more
        (DATA, len(DATA) - 1, len(DATA), len(DATA) - 1),  # the .info file declares less
    ],
)
def test_sizes_that_can_never_agree_are_mismatched(
    storage: Storage, data: bytes, declared: int, size: int, received_size: int
) -> None:
    received(storage, {"Size": declared}, data)
    assert check(storage, size, locked=False) == Inspection(Completeness.MISMATCHED, received_size)


@pytest.mark.parametrize(
    "info",
    [
        None,
        b"not json",
        b"\xff",
        b"[1]",
        b'{"Size": "10"}',
        b'{"Size": true}',
        b'{"Size": 1.5}',
        b'{"Size": 10, "SizeIsDeferred": "no"}',
    ],
)
def test_a_missing_or_malformed_info_file_is_no_info(storage: Storage, info: bytes | None) -> None:
    put(storage, str(UPLOAD), DATA)
    if info is not None:
        put(storage, f"{UPLOAD}.info", info)
    assert check(storage) == Inspection(Completeness.NO_INFO)
    assert Sealer(storage).has_info(UPLOAD) is (info is not None)


@pytest.mark.parametrize("entry", [None, "file"])
def test_a_lake_without_the_upload_directory_gives_an_error_to_retry(
    storage: Storage, entry: str | None
) -> None:
    storage.remove_directory(UPLOADS)
    if entry == "file":
        storage.write_bytes(UPLOADS, b"", 0o600)
    sealer = Sealer(storage)
    for call in (lambda: sealer.check(UPLOAD, len(DATA)), lambda: sealer.has_info(UPLOAD)):
        with pytest.raises(StorageError) as refused:
            call()
        assert refused.value.message == ".tus-uploads is not a directory"
        assert refused.value.context == {"path": ".tus-uploads"}


def test_a_seal_makes_the_object_area_and_a_measured_copy(storage: Storage) -> None:
    received(storage)
    sealed = Sealer(storage).seal(UPLOAD, OBJECT, len(DATA))
    area, copy = storage.stat(AREA), storage.stat(OBJECT)
    assert area is not None and area.mode == OBJECT_DIR_MODE
    assert copy is not None and copy.inode != storage.stat(UPLOADS.joinpath(str(UPLOAD))).inode
    assert sealed == SealedFile(len(DATA), hashlib.sha256(DATA).hexdigest(), copy.inode)
    assert storage.read_bytes(OBJECT) == DATA


def test_a_seal_that_runs_again_replaces_a_part_of_an_earlier_copy(storage: Storage) -> None:
    received(storage)
    storage.make_directory(AREA, OBJECT_DIR_MODE)
    storage.write_bytes(OBJECT, DATA[:3], 0o644)
    assert Sealer(storage).seal(UPLOAD, OBJECT, len(DATA)).size == len(DATA)
    assert storage.read_bytes(OBJECT) == DATA


def test_a_seal_of_a_short_or_missing_upload_makes_no_object(storage: Storage) -> None:
    received(storage, data=DATA[:-1])
    with pytest.raises(SourceSizeMismatch):
        Sealer(storage).seal(UPLOAD, OBJECT, len(DATA))
    assert storage.stat(OBJECT) is None
    storage.remove_file(UPLOADS.joinpath(str(UPLOAD)))
    with pytest.raises(SourceGone):
        Sealer(storage).seal(UPLOAD, OBJECT, len(DATA))


def test_a_missing_upload_directory_is_a_storage_error_to_retry(storage: Storage) -> None:
    storage.remove_directory(UPLOADS)
    with pytest.raises(StorageError) as refused:
        Sealer(storage).seal(UPLOAD, OBJECT, len(DATA))
    assert type(refused.value) is not SourceGone
    assert refused.value.context == {"path": f".tus-uploads/{UPLOAD}"}


def test_upload_ids_are_the_files_named_by_a_canonical_id(storage: Storage) -> None:
    other = uuid.UUID(int=7)
    received(storage)
    put(storage, f"{UPLOAD}.lock", b"1")
    put(storage, f"{other}.info", b"{}")
    put(storage, str(other).upper(), b"")
    put(storage, "notes.txt", b"")
    storage.make_directory(UPLOADS.joinpath(str(uuid.UUID(int=8))), 0o700)
    storage.write_bytes(UPLOADS.joinpath(str(uuid.UUID(int=8)), str(uuid.UUID(int=9))), b"", 0o600)
    assert Sealer(storage).upload_ids() == {UPLOAD, other}


def test_remove_upload_removes_the_data_and_info_files_and_keeps_the_lock(
    storage: Storage,
) -> None:
    received(storage)
    put(storage, f"{UPLOAD}.lock", b"1")
    sealer = Sealer(storage)
    sealer.remove_upload(UPLOAD)
    sealer.remove_upload(UPLOAD)
    assert storage.stat(UPLOADS.joinpath(str(UPLOAD))) is None
    assert sealer.has_info(UPLOAD) is False
    assert storage.read_bytes(UPLOADS.joinpath(f"{UPLOAD}.lock")) == b"1"


def test_a_failed_sync_of_the_new_object_area_leaves_it_for_the_next_seal() -> None:
    storage = MemoryStorage(LAKE, uid=1000, gid=1000)
    storage.make_directory(UPLOADS, UPLOAD_DIR_MODE)
    storage.make_directory(LakePath.of("helio"), 0o2751)
    received(storage)
    storage.faults[("fsync", LakePath.of("helio"))] = errno.EIO
    with pytest.raises(StorageError):
        Sealer(storage).seal(UPLOAD, OBJECT, len(DATA))
    assert Sealer(storage).seal(UPLOAD, OBJECT, len(DATA)).size == len(DATA)
