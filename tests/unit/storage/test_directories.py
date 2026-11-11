"""The directory writer over both adapters: make, the group, ``metadata.json`` and removal."""

import grp
import os
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import pytest
import structlog

from huron.core.storage import (
    DIRECTORY_MODE,
    FILE_MODE,
    ORGANIZATION_MODE,
    SHARE_GROUP_PENDING,
    DirectoryWriter,
    GroupOutcome,
    GroupResult,
    InheritanceFailed,
    LakePath,
    OrganizationPlace,
    Outcome,
    ShareWarning,
    Stat,
    Storage,
    StorageError,
)
from huron.core.storage.memory import MemoryStorage
from huron.core.storage.posix import PosixStorage
from tests.support.disk import SERVICE_GID, memory_lake, plant_symlink, snapshot

PLACE = OrganizationPlace("helio", LakePath(), own_marker=False)
ORGANIZATION = PLACE.directory
CATALOG = ORGANIZATION.joinpath("heliophysics")
NAMESPACE = CATALOG.joinpath("solar-wind")
COLLECTION = NAMESPACE.joinpath("run7")
SHARE_GID = 2001


@dataclass
class Lake:
    """A lake with the helio organization and its heliophysics catalog, and its writer.

    ``group`` is a group name the writer may give the catalog directory; ``unchanged`` says
    whether everything outside the lake is as it was.
    """

    storage: Storage
    writer: DirectoryWriter
    group: str
    unchanged: Callable[[], bool]


@pytest.fixture(params=["posix", "memory"])
def lake(request: pytest.FixtureRequest, tmp_path: Path) -> Lake:
    made = posix_lake(tmp_path) if request.param == "posix" else in_memory_lake()
    made.writer.make(PLACE, ORGANIZATION)
    made.writer.make(PLACE, CATALOG)
    return made


def posix_lake(tmp_path: Path) -> Lake:
    """A temporary lake whose writer has the process's group as the service group."""
    (tmp_path / "lake").mkdir()
    (tmp_path / "outside").mkdir()
    (tmp_path / "outside" / "keep.bin").write_bytes(b"keep")
    storage = PosixStorage(tmp_path / "lake")
    before = snapshot(tmp_path / "outside")

    def unchanged() -> bool:
        return snapshot(tmp_path / "outside") == before

    group = grp.getgrgid(os.getgid()).gr_name
    return Lake(storage, DirectoryWriter(storage, os.getgid()), group, unchanged)


def in_memory_lake() -> Lake:
    """An in-memory lake that knows the group helio-readers, which its user may give."""
    storage = memory_lake()
    storage.groups["helio-readers"] = SHARE_GID
    storage.member_of.add(SHARE_GID)
    return Lake(storage, DirectoryWriter(storage, SERVICE_GID), "helio-readers", lambda: True)


def found(storage: Storage, location: LakePath) -> Stat:
    entry = storage.stat(location)
    assert entry is not None
    return entry


def test_the_organization_directory_gets_its_mode(lake: Lake) -> None:
    assert found(lake.storage, ORGANIZATION).mode == ORGANIZATION_MODE


def test_a_directory_below_the_organization_inherits_setgid_and_the_group(lake: Lake) -> None:
    assert lake.writer.make(PLACE, NAMESPACE) is True
    made = found(lake.storage, NAMESPACE)
    assert (made.mode, made.gid) == (DIRECTORY_MODE, found(lake.storage, CATALOG).gid)


def test_an_empty_directory_is_adopted_as_it_is(lake: Lake) -> None:
    lake.storage.make_directory(NAMESPACE, 0o2770)
    assert lake.writer.make(PLACE, NAMESPACE) is False
    assert found(lake.storage, NAMESPACE).mode == 0o2770


@pytest.mark.parametrize("entry", ["directory", "file"])
def test_any_other_entry_is_refused(lake: Lake, entry: str) -> None:
    if entry == "directory":
        lake.writer.make(PLACE, NAMESPACE)
        lake.storage.write_bytes(NAMESPACE.joinpath("x.bin"), b"x", FILE_MODE)
    else:
        lake.storage.write_bytes(NAMESPACE, b"x", FILE_MODE)
    with pytest.raises(StorageError) as refused:
        lake.writer.make(PLACE, NAMESPACE)
    assert (refused.value.code, refused.value.message, refused.value.context) == (
        "STORAGE_FAILED",
        "helio/heliophysics/solar-wind exists and is not an empty directory",
        {"path": "helio/heliophysics/solar-wind"},
    )


def test_a_link_is_refused_and_stays(lake: Lake) -> None:
    plant_symlink(lake.storage, NAMESPACE)
    with pytest.raises(StorageError) as refused:
        lake.writer.make(PLACE, NAMESPACE)
    assert (refused.value.code, refused.value.status) == ("SYMLINK_IN_LAKE", 409)
    with pytest.raises(StorageError) as refused:
        lake.writer.make(PLACE, NAMESPACE.joinpath("inner"))
    assert (refused.value.message, refused.value.context) == (
        f"{NAMESPACE} is a symbolic link. The lake must not contain symbolic links. Remove it.",
        {"path": str(NAMESPACE)},
    )
    assert lake.unchanged()


def test_a_directory_that_does_not_inherit_is_refused_and_removed(lake: Lake) -> None:
    lake.storage.make_directory(NAMESPACE, 0o750)
    with pytest.raises(InheritanceFailed) as refused:
        lake.writer.make(PLACE, COLLECTION)
    assert (refused.value.code, refused.value.status) == ("STORAGE_FAILED", 500)
    gid = found(lake.storage, NAMESPACE).gid
    assert refused.value.message == (
        f"{COLLECTION}: the directory did not inherit the setgid bit and the group {gid}"
    )
    assert refused.value.context == {"path": str(COLLECTION)}
    assert lake.storage.stat(COLLECTION) is None


def test_the_catalog_directory_gets_its_share_group(lake: Lake) -> None:
    assert lake.writer.set_group(CATALOG, lake.group).outcome in {
        GroupOutcome.CHANGED,
        GroupOutcome.UNCHANGED,
    }
    assert grp_of(lake, CATALOG) == lake.group
    assert lake.writer.set_group(CATALOG, lake.group) == GroupResult(GroupOutcome.UNCHANGED)


def test_a_catalog_without_a_share_group_gets_the_service_group(lake: Lake) -> None:
    lake.writer.set_group(CATALOG, lake.group)
    assert lake.writer.set_group(CATALOG, None).outcome is not GroupOutcome.PENDING
    assert found(lake.storage, CATALOG).gid == lake.writer.group_for(None)
    assert lake.writer.group_for("helio-readers") == "helio-readers"


def test_a_group_that_cannot_be_set_is_pending(lake: Lake) -> None:
    assert lake.writer.set_group(CATALOG, "no-such-group-xyz") == GroupResult.unknown(
        "no-such-group-xyz"
    )
    result = lake.writer.set_group(NAMESPACE, None)
    assert (result.outcome, result.reason) == (GroupOutcome.PENDING, f"{NAMESPACE} does not exist")


def test_a_pending_result_is_the_one_warning() -> None:
    pending = GroupResult(GroupOutcome.PENDING, "refused")
    assert pending.warning("helio-readers") == ShareWarning(
        SHARE_GROUP_PENDING, "helio-readers", "refused"
    )
    assert GroupResult(GroupOutcome.PENDING).warning(1000) == ShareWarning(
        SHARE_GROUP_PENDING, "1000", ""
    )
    assert GroupResult(GroupOutcome.CHANGED).warning("helio-readers") is None
    assert GroupResult(GroupOutcome.UNCHANGED).warning(1000) is None


def test_metadata_is_written_when_its_bytes_change(lake: Lake) -> None:
    metadata = CATALOG.joinpath("metadata.json")
    assert lake.writer.write_metadata(CATALOG, b"{}\n") is True
    written = found(lake.storage, metadata)
    assert written.mode == FILE_MODE
    assert lake.writer.write_metadata(CATALOG, b"{}\n") is False
    assert found(lake.storage, metadata).inode == written.inode
    assert lake.writer.write_metadata(CATALOG, b'{"a":1}\n') is True
    assert lake.storage.read_bytes(metadata) == b'{"a":1}\n'


def test_metadata_that_is_not_a_file_is_refused(lake: Lake) -> None:
    lake.storage.make_inheriting_dir(CATALOG.joinpath("metadata.json"))
    with pytest.raises(StorageError) as refused:
        lake.writer.write_metadata(CATALOG, b"{}\n")
    metadata = str(CATALOG.joinpath("metadata.json"))
    assert (refused.value.code, refused.value.message, refused.value.context) == (
        "STORAGE_FAILED",
        f"{metadata}: Is a directory",
        {"path": metadata},
    )


def test_remove_reports_what_it_did(lake: Lake) -> None:
    lake.writer.make(PLACE, NAMESPACE)
    lake.storage.write_bytes(NAMESPACE.joinpath("x.bin"), b"x", FILE_MODE)
    assert lake.writer.remove(NAMESPACE) is Outcome.KEPT
    lake.storage.remove_file(NAMESPACE.joinpath("x.bin"))
    assert lake.writer.remove(NAMESPACE) is Outcome.REMOVED
    assert lake.writer.remove(NAMESPACE) is Outcome.MISSING


@pytest.fixture
def collection(lake: Lake) -> Lake:
    """Collection run7 with metadata.json, and a part file in ``a``."""
    for directory in (NAMESPACE, COLLECTION, COLLECTION.joinpath("a")):
        lake.writer.make(PLACE, directory)
    lake.writer.write_metadata(COLLECTION, b"{}\n")
    lake.storage.write_bytes(COLLECTION.joinpath("a", ".c.bin.1.huron-part"), b"x", FILE_MODE)
    return lake


def test_removing_a_collection_removes_what_huron_put_there(collection: Lake) -> None:
    assert collection.writer.remove_collection(COLLECTION) is Outcome.REMOVED
    assert collection.storage.stat(COLLECTION) is None
    assert collection.writer.remove_collection(COLLECTION) is Outcome.MISSING


def test_a_collection_with_other_entries_is_kept(collection: Lake) -> None:
    storage = collection.storage
    collection.writer.make(PLACE, COLLECTION.joinpath("b"))
    storage.write_bytes(COLLECTION.joinpath("b", "data.bin"), b"data", FILE_MODE)
    storage.write_bytes(COLLECTION.joinpath("a", "metadata.json"), b"user", FILE_MODE)
    storage.write_bytes(COLLECTION.joinpath("metadata.json.bak"), b"x", FILE_MODE)
    assert collection.writer.remove_collection(COLLECTION) is Outcome.KEPT
    assert [entry.names for entry in storage.walk(COLLECTION)] == [
        ("a",),
        ("a", "metadata.json"),
        ("b",),
        ("b", "data.bin"),
        ("metadata.json.bak",),
    ]


def test_a_link_in_a_collection_keeps_the_directory(collection: Lake) -> None:
    link = COLLECTION.joinpath("a", "link")
    plant_symlink(collection.storage, link)
    with structlog.testing.capture_logs() as logged:
        assert collection.writer.remove_collection(COLLECTION) is Outcome.KEPT
    assert [(e["event"], e["path"]) for e in logged] == [("disk.link_found", str(link))]
    assert [entry.names for entry in collection.storage.walk(COLLECTION)] == [
        ("a",),
        ("a", "link"),
    ]
    assert collection.unchanged()


def grp_of(lake: Lake, location: LakePath) -> str:
    gid = found(lake.storage, location).gid
    if isinstance(lake.storage, MemoryStorage):
        return next(name for name, number in lake.storage.groups.items() if number == gid)
    return grp.getgrgid(gid).gr_name
