"""Repair of one planned directory, on both adapters where the case needs no group membership."""

import copy
import errno
import os
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

import pytest

from huron.core.storage import (
    DIRECTORY_MODE,
    FILE_MODE,
    ORGANIZATION_MODE,
    SHARE_GROUP_PENDING,
    DirectoryWriter,
    FailureReason,
    LakePath,
    LakeUnavailable,
    OrganizationPlace,
    Repairer,
    RepairFailure,
    RepairResult,
    RepairStep,
    ShareWarning,
    Storage,
    StorageError,
    SymlinkInLake,
)
from huron.core.storage.memory import MemoryStorage
from huron.core.storage.posix import PosixStorage
from tests.support.disk import (
    SERVICE_GID,
    WRITE_CLEANUP_FAILURES,
    cleanup_notes,
    exception_chain,
    fail_file_io,
    fail_write_cleanup,
    memory_lake,
    plant_symlink,
    snapshot,
)

PLACE = OrganizationPlace("helio", LakePath(), own_marker=False)
ORG = LakePath.of("helio")
CATALOG = ORG.joinpath("cat")
NS = CATALOG.joinpath("ns")
RUN7 = NS.joinpath("run7")
METADATA = b'{"title": "Run 7"}\n'
DRIFT = FailureReason.MODE_DRIFT
#: An organization whose base lies below the lake's root, with its catalog directory.
ROOTED = OrganizationPlace("geo", LakePath.of("roots", "x"), own_marker=True)
ROOTED_CATALOG = ROOTED.directory.joinpath("cat")
PROVISION = "The storage administrator must run huron adm provision-catalogs."


@dataclass
class Lake:
    """The organization ``place`` (2751) with ``cat`` and ``cat/ns`` (2750) on one adapter.

    ``chmods`` records each ``set_mode`` call of a repair; :meth:`force_mode` changes a mode
    without a record. ``deny`` makes a directory refuse every change to its entries, and
    ``files`` gives everything on the disk, in the lake and outside it.
    """

    storage: Storage
    place: OrganizationPlace
    service_gid: int
    force_mode: Callable[[LakePath, int], bool]
    deny: Callable[[LakePath], None]
    files: Callable[[], object]
    chmods: list[LakePath] = field(default_factory=list)

    def repair(
        self,
        location: LakePath,
        catalog: LakePath | None = CATALOG,
        share_group: str | None = None,
        metadata: bytes | None = None,
    ) -> RepairResult:
        writer = DirectoryWriter(self.storage, self.service_gid)
        step = RepairStep(self.place, location, catalog, share_group, metadata)
        return Repairer(self.storage, writer).repair(step)

    def mode(self, location: LakePath) -> int:
        found = self.storage.stat(location)
        assert found is not None
        return found.mode

    def frozen(self) -> Callable[[], bool]:
        """A check that nothing in the lake or outside it changed after this call."""
        if isinstance(self.storage, MemoryStorage):
            memory = self.storage
            nodes, calls = copy.deepcopy(memory.nodes), list(memory.calls)
            return lambda: memory.nodes == nodes and memory.calls == calls
        files = self.files()
        return lambda: self.files() == files


@pytest.fixture(params=["posix", "memory"])
def lake(
    request: pytest.FixtureRequest,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    temporary_mode: Callable[[Path, int], None],
) -> Lake:
    return built_lake(request.param, PLACE, tmp_path, monkeypatch, temporary_mode)


@pytest.fixture(params=["posix", "memory"])
def rooted(
    request: pytest.FixtureRequest,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    temporary_mode: Callable[[Path, int], None],
) -> Lake:
    """The lake of :data:`ROOTED`, whose base ``roots/x`` lies below the lake's root."""
    return built_lake(request.param, ROOTED, tmp_path, monkeypatch, temporary_mode)


def built_lake(
    kind: str,
    place: OrganizationPlace,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    temporary_mode: Callable[[Path, int], None],
) -> Lake:
    """The :class:`Lake` of ``place`` on the adapter ``kind``, with its directories above."""
    storage: Storage
    deny: Callable[[LakePath], None]
    if kind == "posix":
        (tmp_path / "lake").mkdir()
        (tmp_path / "outside" / "inner").mkdir(parents=True)
        posix = PosixStorage(tmp_path / "lake")
        storage, service_gid = posix, (tmp_path / "lake").stat().st_gid

        def deny(location: LakePath) -> None:
            temporary_mode(posix.root.joinpath(*location.names), 0o550)

    else:
        memory = memory_lake()
        storage, service_gid, deny = memory, SERVICE_GID, memory.denied.add
    names = place.directory.names
    for size in range(1, len(names) + 1):
        storage.make_directory(LakePath(names[:size]), ORGANIZATION_MODE)
    storage.make_inheriting_dir(place.directory.joinpath("cat"))
    storage.make_inheriting_dir(place.directory.joinpath("cat", "ns"))

    def files() -> object:
        return snapshot(tmp_path / "lake"), snapshot(tmp_path / "outside")

    lake = Lake(storage, place, service_gid, storage.set_mode, deny, files)
    real = storage.set_mode

    def recorded(location: LakePath, mode: int) -> bool:
        lake.chmods.append(location)
        return real(location, mode)

    monkeypatch.setattr(storage, "set_mode", recorded)
    return lake


def failure(path: str, reason: FailureReason, detail: str) -> RepairResult:
    return RepairResult(failed=(RepairFailure(path, reason, detail),))


def test_a_missing_directory_is_made_with_its_mode(lake: Lake) -> None:
    assert lake.repair(RUN7) == RepairResult(changed=("helio/cat/ns/run7",))
    assert lake.mode(RUN7) == DIRECTORY_MODE
    assert lake.chmods == []


def test_a_missing_collection_directory_gets_its_metadata(lake: Lake) -> None:
    result = lake.repair(RUN7, metadata=METADATA)
    assert result.changed == ("helio/cat/ns/run7", "helio/cat/ns/run7/metadata.json")
    assert lake.storage.read_bytes(RUN7.joinpath("metadata.json")) == METADATA
    assert lake.mode(RUN7.joinpath("metadata.json")) == FILE_MODE


def test_wrong_bits_are_set(lake: Lake) -> None:
    lake.force_mode(NS, 0o2770)
    assert lake.repair(NS) == RepairResult(changed=("helio/cat/ns",))
    assert lake.mode(NS) == DIRECTORY_MODE
    assert lake.chmods == [NS]


def test_right_bits_get_no_chmod(lake: Lake) -> None:
    assert lake.repair(NS) == RepairResult()
    assert lake.chmods == []


@pytest.mark.parametrize("location", [CATALOG, NS], ids=["catalog", "namespace"])
def test_a_missing_setgid_bit_is_mode_drift_with_no_chmod(lake: Lake, location: LakePath) -> None:
    lake.force_mode(location, 0o750)
    path = str(location)
    assert lake.repair(location) == failure(
        path,
        DRIFT,
        f"{path} does not have the setgid bit. The storage administrator must run huron adm"
        " provision-catalogs.",
    )
    assert lake.mode(location) == 0o750
    assert lake.chmods == []


def test_the_organization_directory_gets_its_mode(lake: Lake) -> None:
    lake.force_mode(ORG, 0o751)
    assert lake.repair(ORG, catalog=None) == RepairResult(changed=("helio",))
    assert lake.mode(ORG) == ORGANIZATION_MODE
    assert lake.repair(ORG, catalog=None) == RepairResult()


def test_a_missing_organization_directory_is_made(lake: Lake) -> None:
    geo = LakePath.of("geo")
    place = OrganizationPlace("geo", LakePath(), own_marker=False)
    writer = DirectoryWriter(lake.storage, lake.service_gid)
    result = Repairer(lake.storage, writer).repair(RepairStep(place, geo, None))
    assert result == RepairResult(changed=("geo",))
    assert lake.mode(geo) == ORGANIZATION_MODE


def test_the_catalog_step_keeps_a_matching_service_group(lake: Lake) -> None:
    assert lake.repair(CATALOG) == RepairResult()


def test_a_non_directory_at_a_planned_path_is_storage_failed(lake: Lake) -> None:
    lake.storage.write_bytes(RUN7, b"", FILE_MODE)
    unchanged = lake.frozen()
    expected = failure(
        "helio/cat/ns/run7", FailureReason.STORAGE_FAILED, "helio/cat/ns/run7 is not a directory"
    )
    assert lake.repair(RUN7, metadata=METADATA) == expected
    assert unchanged()


def test_a_link_at_the_steps_directory_is_symbolic_link_with_no_write(lake: Lake) -> None:
    plant_symlink(lake.storage, RUN7)
    unchanged = lake.frozen()
    result = lake.repair(RUN7, metadata=METADATA)
    assert result == failure(
        "helio/cat/ns/run7",
        FailureReason.SYMBOLIC_LINK,
        "helio/cat/ns/run7 is a symbolic link. The lake must not contain symbolic links. Remove"
        " it.",
    )
    assert unchanged()
    assert lake.chmods == []


def test_a_link_above_the_steps_directory_fails_at_the_links_path(lake: Lake) -> None:
    lake.storage.remove_directory(NS)
    plant_symlink(lake.storage, NS)
    unchanged = lake.frozen()
    assert lake.repair(RUN7, metadata=METADATA) == failure(
        "helio/cat/ns",
        FailureReason.SYMBOLIC_LINK,
        "helio/cat/ns is a symbolic link. The lake must not contain symbolic links. Remove it.",
    )
    assert unchanged()


@pytest.mark.parametrize("name", ["metadata.json", "metadata.json.huron-part"])
def test_a_link_at_metadata_json_or_its_part_file_is_symbolic_link(lake: Lake, name: str) -> None:
    lake.storage.make_inheriting_dir(RUN7)
    plant_symlink(lake.storage, RUN7.joinpath(name))
    unchanged = lake.frozen()
    path = f"helio/cat/ns/run7/{name}"
    assert lake.repair(RUN7, metadata=METADATA) == failure(
        path,
        FailureReason.SYMBOLIC_LINK,
        f"{path} is a symbolic link. The lake must not contain symbolic links. Remove it.",
    )
    assert unchanged()


@pytest.mark.parametrize(
    ("name", "detail"),
    [
        ("metadata.json", "{}: Is a directory"),
        ("metadata.json.huron-part", "{}: Is a directory"),
    ],
    ids=["metadata", "part-file"],
)
def test_a_directory_at_metadata_json_or_its_part_file_fails_at_that_file(
    lake: Lake, name: str, detail: str
) -> None:
    lake.storage.make_inheriting_dir(RUN7)
    lake.storage.make_inheriting_dir(RUN7.joinpath(name))
    lake.storage.write_bytes(RUN7.joinpath(name, "keep"), b"keep", FILE_MODE)
    unchanged = lake.frozen()
    path = f"helio/cat/ns/run7/{name}"
    expected = failure(path, FailureReason.STORAGE_FAILED, detail.format(path))
    assert lake.repair(RUN7, metadata=METADATA) == expected
    assert lake.storage.read_bytes(RUN7.joinpath(name, "keep")) == b"keep"
    assert unchanged()


def test_a_metadata_json_of_mode_000_on_the_disk_fails_at_that_file_and_changes_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, temporary_mode: Callable[[Path, int], None]
) -> None:
    """``MemoryStorage`` does not model the permission of a file, so this case is on the disk."""
    lake = built_lake("posix", PLACE, tmp_path, monkeypatch, temporary_mode)
    lake.storage.make_inheriting_dir(RUN7)
    metadata = RUN7.joinpath("metadata.json")
    lake.storage.write_bytes(metadata, b"stale", FILE_MODE)
    unchanged = lake.frozen()
    file = tmp_path.joinpath("lake", *metadata.names)
    temporary_mode(file, 0o000)
    path = "helio/cat/ns/run7/metadata.json"
    assert lake.repair(RUN7, metadata=METADATA) == failure(
        path, FailureReason.STORAGE_FAILED, f"permission denied on {path}"
    )
    file.chmod(FILE_MODE)
    assert unchanged()
    assert lake.chmods == []


#: The files of the catalog directory before a write of ``metadata.json``.
OLD_METADATA = {"metadata.json": b"old"}
#: An old ``metadata.json`` and the part file that a crash left beside it.
CRASH_LEFT_PART = {**OLD_METADATA, "metadata.json.huron-part": b"half"}


@pytest.mark.parametrize("base", [LakePath(), LakePath.of("roots", "x")])
@pytest.mark.parametrize("number", [errno.EIO, errno.EACCES])
@pytest.mark.parametrize(
    ("operation", "name", "inspection", "files"),
    [
        ("fstat", "metadata.json", 0, OLD_METADATA),
        ("read", "metadata.json", 0, OLD_METADATA),
        ("stat", "metadata.json", 0, OLD_METADATA),
        ("stat", "metadata.json.huron-part", 0, OLD_METADATA),
        ("stat", "metadata.json.huron-part", 1, OLD_METADATA),
        ("unlink", "metadata.json.huron-part", 0, CRASH_LEFT_PART),
        ("fchmod", "metadata.json.huron-part", 0, OLD_METADATA),
        ("write", "metadata.json.huron-part", 0, OLD_METADATA),
        ("fsync", "metadata.json.huron-part", 0, OLD_METADATA),
        ("fsync", "metadata.json.huron-part", 0, {}),
        ("close", "metadata.json.huron-part", 0, OLD_METADATA),
    ],
    ids=[
        "fstat-of-read",
        "read",
        "lstat-of-write",
        "part-stat",
        "part-stat-before-removal",
        "removal-of-old-part",
        "part-fchmod",
        "part-write",
        "part-fsync",
        "part-fsync-of-new-file",
        "part-close",
    ],
)
def test_an_error_on_metadata_json_or_its_part_file_is_storage_failed_and_changes_nothing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    base: LakePath,
    number: int,
    operation: str,
    name: str,
    inspection: int,
    files: dict[str, bytes],
) -> None:
    root = tmp_path / "lake"
    place = OrganizationPlace("geo", base, own_marker=bool(base.names))
    catalog = place.directory.joinpath("cat")
    root.joinpath(*catalog.names).mkdir(parents=True)
    storage = PosixStorage(root)
    storage.set_mode(catalog, DIRECTORY_MODE)
    for file, data in files.items():
        root.joinpath(*catalog.names, file).write_bytes(data)
    writer = DirectoryWriter(storage, root.stat().st_gid)
    before = snapshot(root)
    fail_file_io(monkeypatch, operation, name, number, after=inspection)
    # The directory refuses the removal of the part file, so that error names metadata.json.
    named = "metadata.json" if (operation, number) == ("unlink", errno.EACCES) else name
    path = f"geo/cat/{named}"
    detail = (
        f"permission denied on {path}" if number == errno.EACCES else f"{path}: Input/output error"
    )
    assert Repairer(storage, writer).repair(
        RepairStep(place, catalog, catalog, metadata=METADATA)
    ) == failure(path, FailureReason.STORAGE_FAILED, detail)
    assert snapshot(root) == before
    assert Repairer(storage, writer).repair(
        RepairStep(place, catalog, catalog, metadata=METADATA)
    ) == RepairResult(changed=("geo/cat/metadata.json",))
    assert storage.read_bytes(catalog.joinpath("metadata.json")) == METADATA
    assert storage.stat(catalog.joinpath("metadata.json.huron-part")) is None


@pytest.mark.parametrize("base", [LakePath(), LakePath.of("roots", "x")])
@pytest.mark.parametrize("number", [errno.ENOSPC, errno.EACCES, errno.ENOENT])
@pytest.mark.parametrize("operation,cleanup", WRITE_CLEANUP_FAILURES)
def test_write_cleanup_keeps_the_original_cause_path_and_repair_detail(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    base: LakePath,
    number: int,
    operation: str,
    cleanup: tuple[str, ...],
) -> None:
    root = tmp_path / "lake"
    place = OrganizationPlace("geo", base, own_marker=bool(base.names))
    catalog = place.directory.joinpath("cat")
    root.joinpath(*catalog.names).mkdir(parents=True)
    storage = PosixStorage(root)
    storage.set_mode(catalog, DIRECTORY_MODE)
    metadata = catalog.joinpath("metadata.json")
    storage.write_bytes(metadata, b"old", FILE_MODE)
    old_inode = root.joinpath(*metadata.names).stat().st_ino
    with monkeypatch.context() as patch:
        primary, *secondary = fail_write_cleanup(
            patch, "metadata.json.huron-part", operation, cleanup, number
        )
        with pytest.raises(StorageError) as refused:
            storage.write_bytes(metadata, METADATA, FILE_MODE)
    error = refused.value
    assert exception_chain(error)[-1] is primary
    assert isinstance(primary, OSError)
    assert (primary.errno, primary.strerror, primary.filename) == (
        number,
        os.strerror(number),
        "/untrusted/elsewhere",
    )
    assert all(fault.__traceback__ is not None for fault in secondary)
    assert len(cleanup_notes(error)) == len(cleanup)
    named = (
        "metadata.json"
        if operation == "rename" or (operation == "open" and number == errno.EACCES)
        else "metadata.json.huron-part"
    )
    path = f"geo/cat/{named}"
    location = catalog.joinpath(named)
    if number == errno.EACCES:
        message, detail = f"permission denied on {location}", f"permission denied on {path}"
        assert error.context == {"path": str(location), "error": os.strerror(number)}
    elif number == errno.ENOENT:
        message, detail = f"{location} does not exist", f"{path} does not exist"
        assert error.context == {"path": str(location)}
    else:
        message, detail = f"{location}: {os.strerror(number)}", f"{path}: {os.strerror(number)}"
        assert error.context == {"path": str(location)}
    assert error.message == str(error) == message
    assert RepairFailure.of(place, FailureReason.STORAGE_FAILED, error, catalog) == RepairFailure(
        path, FailureReason.STORAGE_FAILED, detail
    )
    assert storage.read_bytes(metadata) == b"old"
    assert root.joinpath(*metadata.names).stat().st_ino == old_inode
    writer = DirectoryWriter(storage, root.stat().st_gid)
    assert Repairer(storage, writer).repair(
        RepairStep(place, catalog, catalog, metadata=METADATA)
    ) == RepairResult(changed=("geo/cat/metadata.json",))
    assert storage.read_bytes(metadata) == METADATA
    assert storage.stat(catalog.joinpath("metadata.json.huron-part")) is None


@pytest.mark.parametrize("operation", ["fchmod", "write", "fsync", "rename"])
def test_parent_close_preserves_the_storage_failure_and_all_secondary_diagnostics(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, operation: str
) -> None:
    storage = PosixStorage(tmp_path)
    catalog = LakePath.of("catalog")
    storage.make_directory(catalog, DIRECTORY_MODE)
    metadata = catalog.joinpath("metadata.json")
    storage.write_bytes(metadata, b"old", FILE_MODE)
    with monkeypatch.context() as patch:
        primary, secondary = fail_write_cleanup(
            patch, "metadata.json.huron-part", operation, ("unlink",), errno.ENOSPC
        )
        closed = fail_file_io(patch, "close", "catalog", errno.EIO)
        with pytest.raises(StorageError) as refused:
            storage.write_bytes(metadata, METADATA, FILE_MODE)
    named = str(metadata) if operation == "rename" else f"{metadata}.huron-part"
    assert refused.value.message == f"{named}: No space left on device"
    assert refused.value.context == {"path": named}
    assert exception_chain(refused.value)[-1] is primary
    assert len(cleanup_notes(refused.value)) == 2
    assert secondary.__traceback__ is not None and closed.__traceback__ is not None
    assert storage.read_bytes(metadata) == b"old"
    storage.write_bytes(metadata, METADATA, FILE_MODE)
    assert storage.read_bytes(metadata) == METADATA


def test_an_unreadable_catalog_directory_is_storage_failed(
    lake: Lake, temporary_mode: Callable[[Path, int], None]
) -> None:
    if isinstance(lake.storage, PosixStorage):
        temporary_mode(lake.storage.root.joinpath(*CATALOG.names), 0o2000)
    else:
        assert isinstance(lake.storage, MemoryStorage)
        lake.storage.unreadable.add(CATALOG)
    assert lake.repair(NS) == failure(
        "helio/cat/ns", FailureReason.STORAGE_FAILED, "permission denied on helio/cat/ns"
    )
    assert lake.chmods == []


def test_a_stale_metadata_file_is_rewritten_and_an_equal_one_kept(lake: Lake) -> None:
    lake.storage.make_inheriting_dir(RUN7)
    lake.storage.write_bytes(RUN7.joinpath("metadata.json"), b"stale", FILE_MODE)
    result = lake.repair(RUN7, metadata=METADATA)
    assert result == RepairResult(changed=("helio/cat/ns/run7/metadata.json",))
    assert lake.storage.read_bytes(RUN7.joinpath("metadata.json")) == METADATA
    assert lake.repair(RUN7, metadata=METADATA) == RepairResult()


def test_a_repair_is_idempotent(lake: Lake) -> None:
    lake.force_mode(CATALOG, 0o2700)
    lake.force_mode(ORG, 0o2700)
    steps = [(ORG, None), (CATALOG, CATALOG), (NS, CATALOG), (RUN7, CATALOG)]
    first = RepairResult.combine(lake.repair(where, catalog) for where, catalog in steps)
    assert first.changed == ("helio", "helio/cat", "helio/cat/ns/run7")
    assert RepairResult.combine(lake.repair(where, catalog) for where, catalog in steps) == (
        RepairResult()
    )


def test_a_lake_that_does_not_open_ends_the_repair(tmp_path: Path) -> None:
    storage = PosixStorage(tmp_path / "missing")
    step = RepairStep(PLACE, NS, CATALOG)
    with pytest.raises(LakeUnavailable):
        Repairer(storage, DirectoryWriter(storage, 0)).repair(step)


def test_combine_keeps_each_path_warning_and_failure_once() -> None:
    link = RepairFailure("helio/cat/ns", FailureReason.SYMBOLIC_LINK, "a link")
    drift = RepairFailure("helio/cat", DRIFT, "no setgid bit")
    stale = RepairFailure("helio/cat/x", FailureReason.STORAGE_FAILED, "Input/output error")
    pending = ShareWarning(SHARE_GROUP_PENDING, "helio-readers", "refused")
    results = [
        RepairResult(("helio/cat",), (pending,), (drift,)),
        RepairResult(("helio/cat", "helio/cat/a"), (pending,), (link,)),
        RepairResult((), (), (link, stale)),
    ]
    assert RepairResult.combine(results) == RepairResult(
        ("helio/cat", "helio/cat/a"), (pending,), (drift, link, stale)
    )
    assert RepairResult.combine([]) == RepairResult()


@pytest.fixture
def memory() -> MemoryStorage:
    """The in-memory lake with ``helio``, ``helio/cat`` and ``helio/cat/ns``."""
    storage = memory_lake()
    storage.make_directory(ORG, ORGANIZATION_MODE)
    storage.make_inheriting_dir(CATALOG)
    storage.make_inheriting_dir(NS)
    storage.calls.clear()
    return storage


def repaired(
    storage: Storage,
    location: LakePath,
    *,
    place: OrganizationPlace = PLACE,
    catalog: LakePath | None = CATALOG,
    share_group: str | None = None,
) -> RepairResult:
    writer = DirectoryWriter(storage, SERVICE_GID)
    return Repairer(storage, writer).repair(RepairStep(place, location, catalog, share_group))


def chmods(storage: MemoryStorage) -> list[LakePath]:
    return [location for call, location in storage.calls if call == "chmod"]


def test_a_directory_of_another_group_below_the_catalog_is_mode_drift(
    memory: MemoryStorage,
) -> None:
    memory.nodes[NS].gid = 2001
    memory.nodes[NS].mode = 0o2770
    assert repaired(memory, NS) == failure(
        "helio/cat/ns",
        DRIFT,
        f"helio/cat/ns has the group 2001, not the group {SERVICE_GID} of the catalog directory."
        " The storage administrator must run huron adm provision-catalogs.",
    )
    assert memory.nodes[NS].mode == 0o2770
    assert chmods(memory) == []


def test_a_directory_outside_the_services_groups_gets_no_chmod(memory: MemoryStorage) -> None:
    memory.nodes[CATALOG].gid = 2001
    memory.nodes[CATALOG].mode = 0o2770
    memory.groups["helio-readers"] = 2001
    result = repaired(memory, CATALOG, share_group="helio-readers")
    assert result == failure(
        "helio/cat",
        DRIFT,
        "The API is not in the group 2001 of helio/cat. Thus the API cannot change the mode"
        " 2770 to 2750.",
    )
    assert chmods(memory) == []


class SetgidDroppingStorage(MemoryStorage):
    """An in-memory lake whose server drops the setgid bit of every ``chmod``."""

    def set_mode(self, location: LakePath, mode: int) -> bool:
        return super().set_mode(location, mode & ~0o2000)


def test_a_chmod_that_still_drops_the_setgid_bit_is_mode_drift() -> None:
    storage = SetgidDroppingStorage(Path("/lake"), uid=1000, gid=SERVICE_GID)
    storage.nodes[LakePath()].gid = SERVICE_GID
    storage.make_directory(ORG, ORGANIZATION_MODE)
    storage.nodes[ORG].mode = 0o2700
    assert repaired(storage, ORG, catalog=None) == failure(
        "helio",
        DRIFT,
        "The mode of helio is not 2751 after the change. The storage administrator must run"
        " huron adm provision-catalogs.",
    )
    assert storage.nodes[ORG].mode == 0o751


@pytest.mark.parametrize(
    ("member", "known", "expected"),
    [
        (True, True, RepairResult(changed=("helio/cat",))),
        (
            False,
            True,
            RepairResult(
                warnings=(
                    ShareWarning(
                        SHARE_GROUP_PENDING, "helio-readers", "helio/cat: Operation not permitted"
                    ),
                )
            ),
        ),
        (
            False,
            False,
            RepairResult(
                warnings=(
                    ShareWarning(
                        SHARE_GROUP_PENDING,
                        "helio-readers",
                        "this machine does not know the group helio-readers",
                    ),
                )
            ),
        ),
    ],
    ids=["changed", "refused", "unknown"],
)
def test_the_catalog_step_tries_the_share_group(
    memory: MemoryStorage, member: bool, known: bool, expected: RepairResult
) -> None:
    if known:
        memory.groups["helio-readers"] = 2001
    if member:
        memory.member_of.add(2001)
    assert repaired(memory, CATALOG, share_group="helio-readers") == expected
    assert memory.nodes[CATALOG].gid == (2001 if member else SERVICE_GID)


def no_inheritance(memory: MemoryStorage) -> None:
    memory.inherits = False


def narrow_umask(memory: MemoryStorage) -> None:
    memory.umask = 0o077


@pytest.mark.parametrize(
    ("arrange", "reason"),
    [
        (
            no_inheritance,
            f"the directory did not inherit the setgid bit and the group {SERVICE_GID}",
        ),
        (narrow_umask, "the directory has the mode 2700, not 2750"),
    ],
    ids=["setgid-and-group", "mode"],
)
def test_a_new_directory_that_did_not_get_its_mode_is_mode_drift(
    memory: MemoryStorage, arrange: Callable[[MemoryStorage], None], reason: str
) -> None:
    arrange(memory)
    assert repaired(memory, RUN7) == failure(
        "helio/cat/ns/run7", DRIFT, f"helio/cat/ns/run7: {reason}"
    )
    assert RUN7 not in memory.nodes


def test_any_other_storage_error_is_storage_failed_with_its_detail(memory: MemoryStorage) -> None:
    memory.denied.add(NS)
    assert repaired(memory, RUN7) == failure(
        "helio/cat/ns/run7", FailureReason.STORAGE_FAILED, "permission denied on helio/cat/ns/run7"
    )


@pytest.mark.parametrize(
    ("location", "catalog", "path"),
    [
        (ROOTED.directory.joinpath("new"), ROOTED.directory.joinpath("new"), "geo/new"),
        (ROOTED_CATALOG.joinpath("ns", "run7"), ROOTED_CATALOG, "geo/cat/ns/run7"),
    ],
    ids=["catalog", "collection"],
)
def test_a_made_directory_is_named_relative_to_the_organizations_base(
    rooted: Lake, location: LakePath, catalog: LakePath, path: str
) -> None:
    assert rooted.repair(location, catalog=catalog) == RepairResult(changed=(path,))
    assert rooted.mode(location) == DIRECTORY_MODE


def without_setgid(lake: Lake) -> None:
    lake.force_mode(ROOTED_CATALOG, 0o750)


@pytest.mark.parametrize(
    ("arrange", "location", "expected"),
    [
        (
            without_setgid,
            ROOTED_CATALOG,
            ("geo/cat", DRIFT, f"geo/cat does not have the setgid bit. {PROVISION}"),
        ),
        (
            lambda lake: lake.deny(ROOTED_CATALOG),
            ROOTED_CATALOG.joinpath("other"),
            ("geo/cat/other", FailureReason.STORAGE_FAILED, "permission denied on geo/cat/other"),
        ),
        (
            lambda lake: plant_symlink(lake.storage, ROOTED_CATALOG.joinpath("l")),
            ROOTED_CATALOG.joinpath("l", "run7"),
            (
                "geo/cat/l",
                FailureReason.SYMBOLIC_LINK,
                "geo/cat/l is a symbolic link. The lake must not contain symbolic links. Remove"
                " it.",
            ),
        ),
        (
            without_setgid,
            ROOTED_CATALOG.joinpath("other"),
            (
                "geo/cat/other",
                DRIFT,
                "geo/cat/other: the directory did not inherit the setgid bit and the group {gid}",
            ),
        ),
    ],
    ids=["no-setgid-bit", "denied", "link-above", "not-inherited"],
)
def test_a_failure_is_named_relative_to_the_organizations_base_and_changes_nothing(
    rooted: Lake,
    arrange: Callable[[Lake], None],
    location: LakePath,
    expected: tuple[str, FailureReason, str],
) -> None:
    """``{gid}`` in the detail is the group of the catalog directory, the service group."""
    arrange(rooted)
    unchanged = rooted.frozen()
    path, reason, detail = expected
    assert rooted.repair(location, catalog=ROOTED_CATALOG) == failure(
        path, reason, detail.format(gid=rooted.service_gid)
    )
    assert unchanged()


@pytest.mark.parametrize(
    ("link", "path"),
    [
        (LakePath.of("roots"), "roots"),
        (LakePath.of("roots", "x"), "roots/x"),
        (LakePath.of("roots", "xy"), "roots/xy"),
        (LakePath.of("roots", "x", "geo"), "geo"),
        (LakePath.of("roots", "x", "geo", "cat"), "geo/cat"),
    ],
    ids=["above-the-base", "at-the-base", "sibling-prefix", "organization", "below"],
)
def test_a_failure_names_the_place_in_the_api_form_or_by_its_lake_path(
    link: LakePath, path: str
) -> None:
    error = SymlinkInLake(link)
    assert RepairFailure.of(ROOTED, FailureReason.SYMBOLIC_LINK, error, ROOTED.directory) == (
        RepairFailure(
            path,
            FailureReason.SYMBOLIC_LINK,
            f"{path} is a symbolic link. The lake must not contain symbolic links. Remove it.",
        )
    )


def test_a_failure_whose_error_names_no_place_names_the_steps_directory() -> None:
    where = ROOTED.directory.joinpath("cat")
    for context in ({}, {"path": ""}):
        error = StorageError("the disk is full", context)
        assert RepairFailure.of(ROOTED, FailureReason.STORAGE_FAILED, error, where) == (
            RepairFailure("geo/cat", FailureReason.STORAGE_FAILED, "the disk is full")
        )


def test_a_step_names_its_places_below_the_organizations_base() -> None:
    step = RepairStep(ROOTED, ROOTED.directory, None)
    assert step.api_path(ROOTED.directory) == "geo"
    assert step.api_path(ROOTED.directory.joinpath("cat", "ns")) == "geo/cat/ns"
    for outside_the_base in (LakePath.of("roots"), LakePath.of("roots", "xy", "geo")):
        with pytest.raises(ValueError, match="is not below roots/x"):
            step.api_path(outside_the_base)


def test_a_reason_that_holds_the_path_text_stays_as_it_is(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "lake" / "Input" / "output").mkdir(parents=True)
    storage = PosixStorage(tmp_path / "lake")
    place = OrganizationPlace("output", LakePath.of("Input"), own_marker=True)
    real = os.stat

    def failing(
        path: str, *, dir_fd: int | None = None, follow_symlinks: bool = True
    ) -> os.stat_result:
        if path == "output":
            raise OSError(errno.EIO, "Input/output error")
        return real(path, dir_fd=dir_fd, follow_symlinks=follow_symlinks)

    monkeypatch.setattr(os, "stat", failing)
    result = repaired(storage, place.directory, place=place, catalog=None)
    assert result == failure("output", FailureReason.STORAGE_FAILED, "output: Input/output error")
