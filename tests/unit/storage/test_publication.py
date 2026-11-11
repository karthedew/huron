"""The steps of a publication and the link probe, on both adapters."""

import copy
import errno
import os
import re
import shutil
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from huron.core.storage import (
    DIRECTORY_MODE,
    MARKER_FILE,
    OBJECT_DIR_MODE,
    ORGANIZATION_MODE,
    UPLOAD_DIR_MODE,
    UPLOADS,
    AddFile,
    BlockReason,
    LakePath,
    MakeDirectory,
    OrganizationPlace,
    PruneDirectory,
    Publisher,
    RemoveDirectory,
    RemoveFile,
    Step,
    StepOutcome,
    StepResult,
    Storage,
    StorageError,
)
from huron.core.storage.memory import MemoryStorage
from huron.core.storage.posix import PosixStorage
from tests.support.disk import inject_fault, memory_lake, plant_symlink, snapshot

ORG = OrganizationPlace("helio", LakePath(), own_marker=False)
CATALOG = ORG.directory.joinpath("cat")
COLLECTION = CATALOG.joinpath("run7")
TARGET = COLLECTION.joinpath("a.bin")
SUB = COLLECTION.joinpath("sub")
NEW, OLD = uuid.UUID(int=1), uuid.UUID(int=2)
DONE = StepResult(StepOutcome.DONE)
#: The directories on the way to the target of an add and to the place of the other steps.
WAY = {"organization": ORG.directory, "catalog": CATALOG, "collection": COLLECTION}
#: The storage calls that change the lake or sync it, in which a step can stop.
CHANGES = (
    "link_once",
    "rename",
    "sync_directory",
    "remove_file",
    "remove_directory",
    "make_inheriting_dir",
)


@dataclass
class Lake:
    """The organization ``helio`` with its object area, ``cat`` and the collection ``run7``.

    ``files`` is everything in the lake and, on the disk, in the directory ``outside`` that
    planted links point to.
    """

    storage: Storage
    files: Callable[[], object]

    @property
    def publisher(self) -> Publisher:
        return Publisher(self.storage)

    def apply(self, step: Step) -> StepResult:
        return self.publisher.apply(step)

    def object(self, upload_id: uuid.UUID, data: bytes) -> tuple[LakePath, int]:
        """Seal ``data`` as the object of ``upload_id``; its place and its inode."""
        upload, sealed = UPLOADS.joinpath(str(upload_id)), ORG.objects.joinpath(str(upload_id))
        self.storage.write_bytes(upload, data, 0o600)
        return sealed, self.storage.copy_sealed(upload, sealed, len(data)).inode

    def add(self, old: bytes | None = None) -> AddFile:
        """The step that adds the object ``new`` at :data:`TARGET`, over the published object
        ``old`` when it is given.
        """
        old_inode = None
        if old is not None:
            old_object, old_inode = self.object(OLD, old)
            self.storage.link_once(old_object, TARGET)
        source, new_inode = self.object(NEW, b"new")
        return AddFile(source, TARGET, new_inode, old_inode, NEW)

    def old_file(self) -> RemoveFile:
        """The step that removes the published object ``old`` at :data:`TARGET`."""
        source, inode = self.object(OLD, b"old")
        self.storage.link_once(source, TARGET)
        return RemoveFile(TARGET, inode)

    def inode(self, location: LakePath) -> int | None:
        found = self.storage.stat(location)
        return None if found is None else found.inode

    def kind(self, location: LakePath) -> str | None:
        found = self.storage.stat(location)
        return None if found is None else found.kind

    def foreign(self, location: LakePath, kind: str = "file") -> None:
        """Replace what is at ``location`` with a file or a directory that Huron did not make."""
        if self.kind(location) == "file":
            self.storage.remove_file(location)
        if kind == "file":
            self.storage.write_bytes(location, b"theirs", 0o644)
        else:
            self.storage.make_directory(location, DIRECTORY_MODE)

    def link_at(self, location: LakePath) -> None:
        """Replace what is at ``location``, and everything below it, with a symbolic link."""
        self.clear(location)
        plant_symlink(self.storage, location)

    def break_way(self, location: LakePath, kind: str) -> None:
        """Replace the directory ``location`` and everything below it with a foreign file, or
        remove it (``missing``).
        """
        self.clear(location)
        if kind == "file":
            self.storage.write_bytes(location, b"theirs", 0o644)

    def clear(self, location: LakePath) -> None:
        """Remove what is at ``location`` and everything below it."""
        storage = self.storage
        if isinstance(storage, MemoryStorage):
            depth = len(location.names)
            for path in [p for p in storage.nodes if p.names[:depth] == location.names]:
                del storage.nodes[path]
        else:
            assert isinstance(storage, PosixStorage)
            path = storage.root.joinpath(*location.names)
            if path.is_dir():
                shutil.rmtree(path)
            elif path.exists():
                path.unlink()


@pytest.fixture(params=["posix", "memory"])
def lake(request: pytest.FixtureRequest, tmp_path: Path) -> Lake:
    if request.param == "posix":
        (tmp_path / "lake").mkdir()
        (tmp_path / "outside" / "inner").mkdir(parents=True)
        storage = PosixStorage(tmp_path / "lake")

        def files() -> object:
            return snapshot(tmp_path / "lake"), snapshot(tmp_path / "outside")

        return built(storage, files)
    return memory()


def memory() -> Lake:
    """The :class:`Lake` on the in-memory adapter."""
    storage = memory_lake()
    return built(storage, lambda: copy.deepcopy(storage.nodes))


def built(storage: Storage, files: Callable[[], object]) -> Lake:
    """Make the directories of a :class:`Lake` on ``storage``."""
    storage.make_directory(ORG.directory, ORGANIZATION_MODE)
    storage.make_directory(ORG.objects, OBJECT_DIR_MODE)
    storage.make_directory(CATALOG, DIRECTORY_MODE)
    storage.make_inheriting_dir(COLLECTION)
    storage.make_directory(UPLOADS, UPLOAD_DIR_MODE)
    return Lake(storage, files)


class Stop(Exception):
    """The process stops in the middle of a step."""


def stop_after(monkeypatch: pytest.MonkeyPatch, storage: Storage, count: int) -> None:
    """Stop the process right after the ``count``-th change or sync of ``storage``."""
    calls = 0
    for name in CHANGES:
        real = getattr(storage, name)

        def stopping(*args: Any, real: Callable[..., Any] = real, **kwargs: Any) -> Any:
            nonlocal calls
            result = real(*args, **kwargs)
            calls += 1
            if calls == count:
                raise Stop
            return result

        monkeypatch.setattr(storage, name, stopping)


def published(lake: Lake, step: Step) -> None:
    assert isinstance(step, AddFile)
    assert lake.storage.read_bytes(TARGET) == b"new"
    assert lake.inode(TARGET) == step.new_inode == lake.inode(step.source)
    assert lake.kind(step.temporary) is None


def made_directory(lake: Lake, step: Step) -> None:
    assert lake.kind(SUB) == "dir"


def removed(location: LakePath) -> Callable[[Lake, Step], None]:
    def check(lake: Lake, step: Step) -> None:
        assert lake.kind(location) is None

    return check


def with_sub(step: Step) -> Callable[[Lake], Step]:
    def arrange(lake: Lake) -> Step:
        lake.storage.make_inheriting_dir(SUB)
        return step

    return arrange


#: Each kind of step: how to arrange it, the number of changes and syncs it makes, and the check
#: of the lake after it.
SCENARIOS: dict[str, tuple[Callable[[Lake], Step], int, Callable[[Lake, Step], None]]] = {
    "add": (lambda lake: lake.add(), 4, published),
    "replace": (lambda lake: lake.add(old=b"old"), 4, published),
    "remove": (lambda lake: lake.old_file(), 2, removed(TARGET)),
    "make directory": (lambda lake: MakeDirectory(SUB), 2, made_directory),
    "remove directory": (with_sub(RemoveDirectory(SUB)), 2, removed(SUB)),
    "prune": (with_sub(PruneDirectory(SUB)), 2, removed(SUB)),
}


def test_an_add_links_the_object_to_a_new_path(lake: Lake) -> None:
    step = lake.add()
    assert lake.apply(step) == DONE
    published(lake, step)


def test_an_add_replaces_the_old_object_and_the_old_object_stays(lake: Lake) -> None:
    step = lake.add(old=b"old")
    assert lake.apply(step) == DONE
    published(lake, step)
    old_object = ORG.objects.joinpath(str(OLD))
    assert lake.storage.read_bytes(old_object) == b"old"
    assert lake.inode(old_object) == step.old_inode


def test_an_add_whose_target_already_is_the_new_object_is_done(lake: Lake) -> None:
    step = lake.add(old=b"old")
    lake.storage.link_once(step.source, step.temporary)
    lake.storage.rename(step.temporary, TARGET)
    lake.storage.link_once(step.source, step.temporary)
    assert lake.apply(step) == DONE
    published(lake, step)


def test_an_add_syncs_after_the_link_and_after_the_rename() -> None:
    lake = memory()
    assert isinstance(lake.storage, MemoryStorage)
    step = lake.add()
    start = len(lake.storage.calls)
    lake.apply(step)
    assert lake.storage.calls[start:] == [
        ("link", step.temporary),
        ("sync", COLLECTION),
        ("rename", TARGET),
        ("sync", COLLECTION),
    ]


@pytest.mark.parametrize(
    ("old", "found"),
    [
        (None, "file"),
        (None, "dir"),
        (b"old", "file"),
        (b"old", "dir"),
        (b"old", None),
    ],
    ids=[
        "a file at a new path",
        "a directory at a new path",
        "another file in place of the old file",
        "a directory in place of the old file",
        "no old file",
    ],
)
def test_an_add_over_a_target_that_is_neither_old_nor_new_blocks(
    lake: Lake, old: bytes | None, found: str | None
) -> None:
    step = lake.add(old=old)
    if found is None:
        lake.storage.remove_file(TARGET)
    else:
        lake.foreign(TARGET, found)
    before = lake.files()
    assert lake.apply(step) == StepResult.blocked(BlockReason.FOREIGN_ENTRY, TARGET)
    assert lake.files() == before


@pytest.mark.parametrize("replaced", [False, True], ids=["missing", "another file"])
def test_an_add_of_an_object_that_is_gone_blocks(lake: Lake, replaced: bool) -> None:
    step = lake.add()
    lake.storage.remove_file(step.source)
    if replaced:
        lake.storage.write_bytes(step.source, b"new", 0o644)
    before = lake.files()
    assert lake.apply(step) == StepResult.blocked(BlockReason.OBJECT_MISSING, step.source)
    assert lake.files() == before


@pytest.mark.parametrize("kind", ["file", "dir"])
def test_an_add_with_a_foreign_entry_at_the_temporary_name_blocks(lake: Lake, kind: str) -> None:
    step = lake.add()
    lake.foreign(step.temporary, kind)
    before = lake.files()
    assert lake.apply(step) == StepResult.blocked(BlockReason.FOREIGN_ENTRY, step.temporary)
    assert lake.files() == before


@pytest.mark.parametrize(
    ("scenario", "count"),
    [(name, count) for name, (_, points, _) in SCENARIOS.items() for count in range(1, points + 1)],
)
def test_a_step_runs_again_after_a_stop_at_each_point(
    lake: Lake, monkeypatch: pytest.MonkeyPatch, scenario: str, count: int
) -> None:
    arrange, _, check = SCENARIOS[scenario]
    step = arrange(lake)
    with monkeypatch.context() as patch:
        stop_after(patch, lake.storage, count)
        with pytest.raises(Stop):
            lake.apply(step)
    assert lake.apply(step) == DONE
    check(lake, step)
    settled = lake.files()
    assert lake.apply(step) == DONE
    assert lake.files() == settled


@pytest.mark.parametrize(
    "component",
    ["target", "temporary", "collection", "catalog", "organization", "object", "object area"],
)
def test_a_link_at_any_name_of_an_add_blocks_it_and_stays(lake: Lake, component: str) -> None:
    step = lake.add()
    location = {
        "target": TARGET,
        "temporary": step.temporary,
        "collection": COLLECTION,
        "catalog": CATALOG,
        "organization": ORG.directory,
        "object": step.source,
        "object area": ORG.objects,
    }[component]
    lake.link_at(location)
    before = lake.files()
    assert lake.apply(step) == StepResult.blocked(BlockReason.SYMBOLIC_LINK, location)
    assert lake.files() == before


@pytest.mark.parametrize("component", ["place", "organization", "catalog", "collection"])
@pytest.mark.parametrize("scenario", ["remove", "make directory", "remove directory", "prune"])
def test_a_link_at_the_place_or_a_directory_on_its_way_blocks_a_step_and_stays(
    lake: Lake, scenario: str, component: str
) -> None:
    step = SCENARIOS[scenario][0](lake)
    place = TARGET if scenario == "remove" else SUB
    location = place if component == "place" else WAY[component]
    lake.link_at(location)
    before = lake.files()
    assert lake.apply(step) == StepResult.blocked(BlockReason.SYMBOLIC_LINK, location)
    assert lake.files() == before


def test_a_remove_unlinks_the_old_file_and_the_old_object_stays(lake: Lake) -> None:
    step = lake.old_file()
    assert lake.apply(step) == DONE
    assert lake.kind(TARGET) is None
    assert lake.storage.read_bytes(ORG.objects.joinpath(str(OLD))) == b"old"


def test_a_remove_whose_directory_is_gone_is_done(lake: Lake) -> None:
    assert lake.apply(RemoveFile(SUB.joinpath("a.bin"), 1)) == DONE
    assert lake.kind(SUB) is None


@pytest.mark.parametrize("kind", ["file", "dir"])
def test_a_remove_of_another_entry_blocks_and_the_entry_stays(lake: Lake, kind: str) -> None:
    step = lake.old_file()
    lake.foreign(TARGET, kind)
    before = lake.files()
    assert lake.apply(step) == StepResult.blocked(BlockReason.FOREIGN_ENTRY, TARGET)
    assert lake.files() == before


def test_a_new_directory_inherits_the_setgid_bit_and_the_group(lake: Lake) -> None:
    assert lake.apply(MakeDirectory(SUB)) == DONE
    made, collection = lake.storage.stat(SUB), lake.storage.stat(COLLECTION)
    assert made is not None and collection is not None
    assert (made.mode, made.gid) == (DIRECTORY_MODE, collection.gid)


def test_a_new_directory_that_exists_is_done(lake: Lake) -> None:
    lake.storage.make_inheriting_dir(SUB)
    before = lake.files()
    assert lake.apply(MakeDirectory(SUB)) == DONE
    assert lake.files() == before


def test_a_new_directory_over_a_file_blocks(lake: Lake) -> None:
    lake.foreign(SUB)
    before = lake.files()
    assert lake.apply(MakeDirectory(SUB)) == StepResult.blocked(BlockReason.FOREIGN_ENTRY, SUB)
    assert lake.files() == before


@pytest.mark.parametrize("step", [RemoveDirectory(SUB), PruneDirectory(SUB)])
def test_a_directory_that_is_gone_is_done(lake: Lake, step: Step) -> None:
    assert lake.apply(step) == DONE
    assert lake.apply(RemoveDirectory(SUB.joinpath("deeper"))) == DONE


@pytest.mark.parametrize("step", [RemoveDirectory(SUB), PruneDirectory(SUB)])
def test_a_directory_removal_of_a_file_blocks(lake: Lake, step: Step) -> None:
    lake.foreign(SUB)
    before = lake.files()
    assert lake.apply(step) == StepResult.blocked(BlockReason.FOREIGN_ENTRY, SUB)
    assert lake.files() == before


def test_a_foreign_file_blocks_the_removal_of_its_directory_and_stays(lake: Lake) -> None:
    lake.storage.make_inheriting_dir(SUB)
    lake.foreign(SUB.joinpath("theirs"))
    before = lake.files()
    result = lake.apply(RemoveDirectory(SUB))
    assert result == StepResult.blocked(BlockReason.DIRECTORY_NOT_EMPTY, SUB)
    assert lake.files() == before


def test_a_prune_keeps_a_directory_with_a_foreign_file_and_is_done(lake: Lake) -> None:
    lake.storage.make_inheriting_dir(SUB)
    lake.foreign(SUB.joinpath("theirs"))
    before = lake.files()
    result = lake.apply(PruneDirectory(SUB))
    assert (result, result.done) == (StepResult(StepOutcome.KEPT), True)
    assert lake.files() == before


def test_no_space_for_the_link_gives_no_success_and_the_step_runs_again(
    lake: Lake, monkeypatch: pytest.MonkeyPatch
) -> None:
    step = lake.add(old=b"old")
    with monkeypatch.context() as patch:
        inject_fault(lake.storage, patch, "link", step.temporary, errno.ENOSPC)
        with pytest.raises(StorageError) as refused:
            lake.apply(step)
    assert_refused(refused.value, f"{step.temporary}: No space left on device", step.temporary)
    assert lake.storage.read_bytes(TARGET) == b"old"
    assert lake.kind(step.temporary) is None
    assert lake.apply(step) == DONE
    published(lake, step)


@pytest.mark.parametrize("scenario", [*SCENARIOS, "add after the rename"])
def test_a_failed_sync_gives_no_success_and_the_step_runs_again(
    lake: Lake, monkeypatch: pytest.MonkeyPatch, scenario: str
) -> None:
    if scenario == "add after the rename":
        step: Step = lake.add(old=b"old")
        assert isinstance(step, AddFile)
        lake.storage.link_once(step.source, step.temporary)
        lake.storage.rename(step.temporary, TARGET)
        check = published
    else:
        arrange, _, check = SCENARIOS[scenario]
        step = arrange(lake)
    with monkeypatch.context() as patch:
        inject_fault(lake.storage, patch, "fsync", COLLECTION, errno.EIO)
        with pytest.raises(StorageError) as refused:
            lake.apply(step)
    assert_refused(refused.value, f"{COLLECTION}: Input/output error", COLLECTION)
    assert lake.apply(step) == DONE
    check(lake, step)


def test_a_blocked_result_says_why_and_is_not_done() -> None:
    details = {
        BlockReason.FOREIGN_ENTRY: (
            "helio/cat/run7/a.bin is not the entry that the request expects."
            " Huron did not change it."
        ),
        BlockReason.DIRECTORY_NOT_EMPTY: (
            "The directory helio/cat/run7/a.bin contains an entry that Huron did not record."
            " Huron did not remove the directory."
        ),
        BlockReason.OBJECT_MISSING: (
            "The sealed object helio/cat/run7/a.bin does not exist or is another file."
        ),
        BlockReason.SYMBOLIC_LINK: (
            "helio/cat/run7/a.bin is a symbolic link. The lake must not contain symbolic links."
            " Remove it."
        ),
    }
    for reason, detail in details.items():
        result = StepResult.blocked(reason, TARGET)
        assert (result.outcome, result.done, result.detail) == (StepOutcome.BLOCKED, False, detail)
    assert (DONE.done, DONE.detail) == (True, "")


def test_the_temporary_name_lies_beside_the_target() -> None:
    step = AddFile(ORG.objects.joinpath("o"), TARGET, 7, None, NEW)
    assert step.temporary == COLLECTION.joinpath(f".a.bin.{NEW}.huron-part")


@pytest.mark.parametrize(
    ("source", "target"),
    [
        (COLLECTION.joinpath("o"), TARGET),
        (ORG.objects.joinpath("o"), LakePath.of("geo", "cat", "a.bin")),
        (ORG.objects.joinpath("o"), ORG.objects.joinpath("a.bin")),
        (ORG.objects.joinpath("o"), ORG.directory),
    ],
    ids=["not an object", "another organization", "the object area", "the organization"],
)
def test_an_add_links_only_inside_one_organization(source: LakePath, target: LakePath) -> None:
    with pytest.raises(ValueError) as refused:
        AddFile(source, target, 7, None, NEW)
    assert str(refused.value) == f"{source} and {target} are not in one organization"


def assert_refused(error: StorageError, message: str, path: LakePath) -> None:
    """``error`` is a plain ``StorageError`` with ``message``, and it names ``path``."""
    assert type(error) is StorageError
    assert error.message == message
    assert error.context == {"path": str(path)}


def top_names(lake: Lake, directory: LakePath) -> set[str]:
    return {entry.names[0] for entry in lake.storage.walk(directory)}


def test_the_probe_makes_a_real_link_and_leaves_only_the_object_area(lake: Lake) -> None:
    lake.storage.remove_directory(ORG.objects)
    lake.publisher.probe(ORG)
    area = lake.storage.stat(ORG.objects)
    assert area is not None
    assert (area.kind, area.mode) == ("dir", OBJECT_DIR_MODE)
    assert lake.storage.is_empty(ORG.objects)
    assert top_names(lake, ORG.directory) == {"cat", ".huron-objects"}


def test_the_probe_gives_the_object_area_its_mode(lake: Lake) -> None:
    lake.storage.set_mode(ORG.objects, 0o755)
    lake.publisher.probe(ORG)
    area = lake.storage.stat(ORG.objects)
    assert area is not None
    assert area.mode == OBJECT_DIR_MODE


def test_the_probe_fails_when_the_object_area_is_on_another_mount(
    lake: Lake, monkeypatch: pytest.MonkeyPatch
) -> None:
    if isinstance(lake.storage, MemoryStorage):
        lake.storage.mounts.add(ORG.objects)
    else:

        def refuse(*args: object, **kwargs: object) -> None:
            raise OSError(errno.EXDEV, os.strerror(errno.EXDEV))

        monkeypatch.setattr(os, "link", refuse)
    with pytest.raises(StorageError) as refused:
        lake.publisher.probe(ORG)
    link = refused.value.context["path"]
    assert re.fullmatch(r"helio/\.huron-link-probe-[0-9a-f]{32}", link)
    assert_refused(refused.value, f"{link}: Invalid cross-device link", LakePath.parse(link))
    assert lake.storage.is_empty(ORG.objects)
    assert top_names(lake, ORG.directory) == {"cat", ".huron-objects"}


def test_the_probe_fails_when_the_object_area_is_not_a_directory(lake: Lake) -> None:
    lake.storage.remove_directory(ORG.objects)
    lake.foreign(ORG.objects)
    with pytest.raises(StorageError) as refused:
        lake.publisher.probe(ORG)
    assert_refused(refused.value, "helio/.huron-objects: File exists", ORG.objects)


@pytest.mark.parametrize("component", sorted(WAY))
@pytest.mark.parametrize("scenario", ["add", "replace", "make directory"])
def test_a_file_on_the_way_blocks_an_add_or_a_new_directory(
    lake: Lake, scenario: str, component: str
) -> None:
    step = SCENARIOS[scenario][0](lake)
    lake.break_way(WAY[component], "file")
    before = lake.files()
    assert lake.apply(step) == StepResult.blocked(BlockReason.FOREIGN_ENTRY, WAY[component])
    assert lake.files() == before


@pytest.mark.parametrize("component", sorted(WAY))
@pytest.mark.parametrize("scenario", ["add", "replace", "make directory"])
def test_a_missing_directory_on_the_way_blocks_an_add_or_a_new_directory(
    lake: Lake, scenario: str, component: str
) -> None:
    step = SCENARIOS[scenario][0](lake)
    lake.break_way(WAY[component], "missing")
    before = lake.files()
    result = lake.apply(step)
    assert result == StepResult.blocked(BlockReason.DIRECTORY_MISSING, WAY[component])
    assert result.detail == (
        f"The directory {WAY[component]} does not exist. The request expects this directory."
    )
    assert lake.files() == before


@pytest.mark.parametrize("kind", ["file", "missing"])
def test_a_broken_object_area_blocks_an_add(lake: Lake, kind: str) -> None:
    step = lake.add()
    lake.break_way(ORG.objects, kind)
    reason = BlockReason.FOREIGN_ENTRY if kind == "file" else BlockReason.DIRECTORY_MISSING
    assert lake.apply(step) == StepResult.blocked(reason, ORG.objects)


@pytest.mark.parametrize("kind", ["file", "missing"])
@pytest.mark.parametrize("component", ["catalog", "collection"])
@pytest.mark.parametrize("scenario", ["remove", "remove directory", "prune"])
def test_a_removal_whose_way_is_gone_or_not_a_directory_is_done(
    lake: Lake, scenario: str, component: str, kind: str
) -> None:
    step = SCENARIOS[scenario][0](lake)
    lake.break_way(WAY[component], kind)
    before = lake.files()
    assert lake.apply(step) == DONE
    assert lake.files() == before


@pytest.mark.parametrize("kind", ["file", "missing"])
@pytest.mark.parametrize("scenario", ["add", "replace", "make directory"])
def test_a_step_completes_after_the_operator_repairs_the_way(
    lake: Lake, scenario: str, kind: str
) -> None:
    arrange, _, check = SCENARIOS[scenario]
    step = arrange(lake)
    lake.break_way(COLLECTION, kind)
    assert not lake.apply(step).done
    lake.clear(COLLECTION)
    lake.storage.make_inheriting_dir(COLLECTION)
    if scenario == "replace":
        lake.storage.link_once(ORG.objects.joinpath(str(OLD)), TARGET)
    assert lake.apply(step) == DONE
    check(lake, step)


def test_a_refused_permission_with_an_intact_way_is_an_error(
    lake: Lake, temporary_mode: Callable[[Path, int], None]
) -> None:
    step = lake.add()
    if isinstance(lake.storage, MemoryStorage):
        lake.storage.denied.add(COLLECTION)
    else:
        assert isinstance(lake.storage, PosixStorage)
        temporary_mode(lake.storage.root.joinpath(*COLLECTION.names), 0o2550)
    with pytest.raises(StorageError) as refused:
        lake.apply(step)
    assert type(refused.value) is StorageError
    assert refused.value.message == f"permission denied on {step.temporary}"
    assert refused.value.context == {"path": str(step.temporary), "error": "Permission denied"}


def test_the_probe_syncs_the_organization_directory_after_it_makes_the_object_area() -> None:
    lake = memory()
    assert isinstance(lake.storage, MemoryStorage)
    lake.storage.remove_directory(ORG.objects)
    start = len(lake.storage.calls)
    lake.publisher.probe(ORG)
    assert lake.storage.calls[start : start + 2] == [
        ("mkdir", ORG.objects),
        ("sync", ORG.directory),
    ]


def test_a_failed_sync_of_a_new_object_area_fails_the_probe(
    lake: Lake, monkeypatch: pytest.MonkeyPatch
) -> None:
    lake.storage.remove_directory(ORG.objects)
    inject_fault(lake.storage, monkeypatch, "fsync", ORG.directory, errno.EIO)
    with pytest.raises(StorageError) as refused:
        lake.publisher.probe(ORG)
    assert_refused(refused.value, "helio: Input/output error", ORG.directory)


#: The storage calls of a probe, at each of which a second probe can start.
PROBE_CALLS = ("make_directory", "set_mode", "write_bytes", "link_once", "remove_file")


@pytest.mark.parametrize("area", ["made", "missing", "other mode"])
@pytest.mark.parametrize("hook", PROBE_CALLS)
def test_a_probe_that_starts_inside_another_probe_lets_both_pass(
    lake: Lake, monkeypatch: pytest.MonkeyPatch, hook: str, area: str
) -> None:
    if area == "missing":
        lake.storage.remove_directory(ORG.objects)
    elif area == "other mode":
        lake.storage.set_mode(ORG.objects, 0o755)
    real = getattr(lake.storage, hook)
    inner: list[str] = []

    def interleaved(*args: Any, **kwargs: Any) -> Any:
        if not inner:
            inner.append(hook)
            lake.publisher.probe(ORG)
        return real(*args, **kwargs)

    monkeypatch.setattr(lake.storage, hook, interleaved)
    lake.publisher.probe(ORG)
    assert inner == [hook]
    found = lake.storage.stat(ORG.objects)
    assert found is not None
    assert (found.kind, found.mode) == ("dir", OBJECT_DIR_MODE)
    assert lake.storage.is_empty(ORG.objects)
    assert top_names(lake, ORG.directory) == {"cat", ".huron-objects"}


def test_the_probe_changes_no_other_entry_and_reads_no_foreign_directory(
    lake: Lake, temporary_mode: Callable[[Path, int], None]
) -> None:
    left = f"{MARKER_FILE}-link-probe-{'0' * 32}"
    lake.storage.write_bytes(ORG.objects.joinpath("object"), b"x", 0o644)
    lake.storage.write_bytes(ORG.objects.joinpath(left), b"", 0o644)
    lake.storage.write_bytes(ORG.directory.joinpath(left), b"", 0o644)
    foreign = ORG.directory.joinpath(".foreign")
    lake.storage.make_directory(foreign, 0o700)
    lake.storage.write_bytes(foreign.joinpath("inner"), b"theirs", 0o644)
    if isinstance(lake.storage, MemoryStorage):
        lake.storage.nodes[foreign].mode = 0o000
        lake.storage.unreadable.add(foreign)
    else:
        assert isinstance(lake.storage, PosixStorage)
        temporary_mode(lake.storage.root.joinpath(*foreign.names), 0o000)
    before = lake.files()
    lake.publisher.probe(ORG)
    assert lake.files() == before
