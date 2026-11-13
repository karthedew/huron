"""The catalog step: which catalogs it selects, what it does to them and its shell script."""

import errno
import grp
import os
import stat
import subprocess
from collections.abc import Iterator
from pathlib import Path
from types import SimpleNamespace

import pytest

from huron.core.storage import (
    DIRECTORY_MODE,
    FILE_MODE,
    LakePath,
    LakeUnavailable,
    OrganizationPlace,
    PermissionDenied,
    StorageError,
)
from huron.core.storage.memory import MemoryStorage
from huron.core.storage.ports import Entry
from huron.core.storage.posix import PosixStorage
from huron.core.storage.provision import (
    CatalogTarget,
    Provisioner,
    catalog_script,
    provision_catalogs,
)
from tests.fakes.storage import Unmounted
from tests.support.shell import NEEDS_SHELL

PREFIX = "/projects/huron"
HELIO = OrganizationPlace("helio", LakePath(), own_marker=True)
CATALOG = LakePath.of("helio", "cat")
NAMESPACE = CATALOG.joinpath("ns")
RUN = NAMESPACE.joinpath("run")
#: The share group of the catalog, and the groups this machine knows.
READERS = 2001
GROUPS = {"readers": READERS}


def target(group: str | int = "readers", location: LakePath = CATALOG) -> CatalogTarget:
    return CatalogTarget(HELIO, location, group)


@pytest.fixture
def lake() -> MemoryStorage:
    """``helio/cat/ns/run`` with a file, every directory of the group ``readers`` with setgid."""
    storage = MemoryStorage(Path(PREFIX))
    storage.groups.update(GROUPS)
    storage.member_of.add(READERS)
    storage.make_directory(LakePath.of("helio"), 0o2751)
    storage.make_directory(CATALOG, DIRECTORY_MODE)
    storage.set_group(CATALOG, READERS)
    for location in (NAMESPACE, RUN):
        storage.make_directory(location, DIRECTORY_MODE)
    storage.write_bytes(RUN.joinpath("a.bin"), b"x", FILE_MODE)
    return storage


def selected(storage: MemoryStorage | PosixStorage, *targets: CatalogTarget) -> list[LakePath]:
    return [found.location for found in provision_catalogs(storage, targets, GROUPS.get)]


def test_a_catalog_whose_directories_carry_its_group_is_not_selected(lake: MemoryStorage) -> None:
    lake.nodes[RUN.joinpath("a.bin")].gid = 1000
    lake.nodes[RUN.joinpath("a.bin")].mode = 0o600
    assert selected(lake, target(), target(READERS)) == []


@pytest.mark.parametrize(
    ("location", "change"),
    [
        (CATALOG, {"gid": 1000}),
        (CATALOG, {"mode": 0o750}),
        (NAMESPACE, {"mode": 0o750}),
        (RUN, {"gid": 1000}),
    ],
)
def test_a_catalog_with_a_directory_without_its_group_or_setgid_is_selected(
    lake: MemoryStorage, location: LakePath, change: dict[str, int]
) -> None:
    node = lake.nodes[location]
    for name, value in change.items():
        setattr(node, name, value)
    assert selected(lake, target()) == [CATALOG]


@pytest.mark.parametrize("closed", [LakePath.of("helio"), CATALOG], ids=["above", "catalog"])
def test_a_catalog_directory_that_cannot_be_read_is_left_to_the_check(
    lake: MemoryStorage, closed: LakePath
) -> None:
    lake.unreadable.add(closed)
    assert selected(lake, target()) == []


def test_a_catalog_that_is_a_link_is_left_to_the_check(lake: MemoryStorage) -> None:
    lake.symlink(LakePath.of("helio", "linked"), "/etc")
    assert selected(lake, target(location=LakePath.of("helio", "linked"))) == []


def test_a_directory_below_a_catalog_that_cannot_be_read_does_not_select_it(
    lake: MemoryStorage,
) -> None:
    lake.unreadable.add(NAMESPACE)
    lake.nodes[RUN].gid = 1000
    lake.symlink(CATALOG.joinpath("link"), "/etc")
    assert selected(lake, target()) == []


def test_drift_after_a_directory_that_cannot_be_read_selects_the_catalog(
    lake: MemoryStorage,
) -> None:
    lake.unreadable.add(NAMESPACE)
    lake.make_directory(CATALOG.joinpath("other"), 0o750)
    assert selected(lake, target()) == [CATALOG]


def test_a_missing_catalog_directory_is_left_to_repair(lake: MemoryStorage) -> None:
    assert selected(lake, target(location=LakePath.of("helio", "gone"))) == []


def test_a_share_group_that_this_machine_does_not_know_selects_the_catalog(
    lake: MemoryStorage,
) -> None:
    assert selected(lake, target("unknown-group")) == [CATALOG]


def test_a_catalog_without_a_share_group_is_compared_with_the_service_gid(
    lake: MemoryStorage,
) -> None:
    assert selected(lake, target(1000)) == [CATALOG]
    assert selected(lake, target(READERS)) == []


@pytest.mark.parametrize("name", [".snapshot", ".huron-objects"])
def test_a_snapshot_or_object_directory_below_a_catalog_and_its_entries_are_not_compared(
    lake: MemoryStorage, name: str
) -> None:
    skipped = NAMESPACE.joinpath(name)
    lake.make_directory(skipped, 0o777)
    lake.make_directory(skipped.joinpath("inside"), 0o700)
    lake.nodes[skipped].gid = 0
    lake.nodes[skipped.joinpath("inside")].gid = 0
    assert selected(lake, target()) == []


def test_a_lake_that_is_not_mounted_stops_the_selection() -> None:
    with pytest.raises(LakeUnavailable):
        provision_catalogs(Unmounted(), [target()], GROUPS.get)


def test_the_catalog_step_gives_every_directory_the_group_and_the_mode(
    lake: MemoryStorage,
) -> None:
    lake.uid = 0
    for location in (CATALOG, NAMESPACE, RUN, RUN.joinpath("a.bin")):
        lake.nodes[location].gid = 1000
    lake.nodes[NAMESPACE].mode = 0o750
    skipped = [RUN.joinpath(".snapshot"), RUN.joinpath(".huron-objects")]
    for location in skipped:
        lake.make_directory(location, 0o777)
        lake.make_directory(location.joinpath("inside"), 0o777)
    provisioner = Provisioner(lake, PREFIX)
    steps = provisioner.provision_catalog(target())
    assert steps == [
        f"group readers and mode 2750: 3 of 3 directories changed in {PREFIX}/helio/cat"
    ]
    for location in (CATALOG, NAMESPACE, RUN):
        node = lake.nodes[location]
        assert (node.gid, node.mode) == (READERS, DIRECTORY_MODE)
    for location in skipped:
        for node in (lake.nodes[location], lake.nodes[location.joinpath("inside")]):
            assert (node.gid, node.mode) == (1000, 0o777)
    placed = lake.nodes[RUN.joinpath("a.bin")]
    assert (placed.gid, placed.mode) == (1000, FILE_MODE)
    assert provisioner.provision_catalog(target()) == [
        f"group readers and mode 2750: 0 of 3 directories changed in {PREFIX}/helio/cat"
    ]


def test_a_dry_run_of_the_catalog_step_changes_nothing(lake: MemoryStorage) -> None:
    calls = list(lake.calls)
    steps = Provisioner(lake, PREFIX).provision_catalog(target(1000), dry_run=True)
    assert steps == [f"would set group 1000 and mode 2750: {PREFIX}/helio/cat"]
    assert lake.calls == calls


def test_the_catalog_step_fails_on_a_group_that_it_cannot_give(lake: MemoryStorage) -> None:
    lake.groups["geo-readers"] = 2002
    with pytest.raises(StorageError) as refused:
        Provisioner(lake, PREFIX).provision_catalog(target("geo-readers"))
    assert (refused.value.message, refused.value.context) == (
        f"the CLI cannot give {PREFIX}/helio/cat the group geo-readers: Operation not permitted",
        {"path": f"{PREFIX}/helio/cat", "group": "geo-readers"},
    )
    assert lake.nodes[CATALOG].gid == READERS


def test_the_catalog_step_names_a_group_that_the_filesystem_refuses_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "helio" / "cat").mkdir(parents=True)
    monkeypatch.setattr(grp, "getgrnam", lambda name: SimpleNamespace(gr_gid=os.getgid() + 1))

    def refuse(*args: object, **kwargs: object) -> None:
        raise PermissionError(errno.EPERM, os.strerror(errno.EPERM))

    monkeypatch.setattr(os, "chown", refuse)
    with pytest.raises(StorageError) as refused:
        Provisioner(PosixStorage(tmp_path), PREFIX).provision_catalog(target())
    assert refused.value.message == (
        f"the CLI cannot give {PREFIX}/helio/cat the group readers: {os.strerror(errno.EPERM)}"
    )


def test_the_catalog_step_fails_on_a_group_that_this_machine_does_not_know(
    lake: MemoryStorage,
) -> None:
    with pytest.raises(StorageError) as refused:
        Provisioner(lake, PREFIX).provision_catalog(target("nobody"))
    assert (refused.value.message, refused.value.context) == (
        f"the CLI cannot give {PREFIX}/helio/cat the group nobody:"
        " this machine does not know the group nobody",
        {"path": f"{PREFIX}/helio/cat", "group": "nobody"},
    )
    assert lake.nodes[CATALOG].gid == READERS


def test_the_catalog_step_fails_on_a_directory_that_another_client_removed_after_the_walk(
    lake: MemoryStorage, monkeypatch: pytest.MonkeyPatch
) -> None:
    lake.uid = 0
    listed = lake.walk

    def walk(location: LakePath, *, recursive: bool = True) -> Iterator[Entry]:
        yield from list(listed(location, recursive=recursive))
        for gone in (RUN.joinpath("a.bin"), RUN):
            del lake.nodes[gone]

    monkeypatch.setattr(lake, "walk", walk)
    with pytest.raises(StorageError) as refused:
        Provisioner(lake, PREFIX).provision_catalog(target(1000))
    assert refused.value.message == (
        f"the CLI cannot give {PREFIX}/helio/cat/ns/run the group 1000:"
        " the directory does not exist"
    )


def test_the_posix_catalog_step_fails_on_a_directory_that_another_client_removed_after_the_walk(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run = tmp_path / "helio" / "cat" / "ns" / "run"
    run.mkdir(parents=True)
    storage = PosixStorage(tmp_path)
    listed = storage.walk

    def walk(location: LakePath, *, recursive: bool = True) -> Iterator[Entry]:
        yield from list(listed(location, recursive=recursive))
        run.rmdir()

    monkeypatch.setattr(storage, "walk", walk)
    with pytest.raises(StorageError) as refused:
        Provisioner(storage, PREFIX).provision_catalog(target(os.getgid()))
    assert refused.value.message == (
        f"the CLI cannot give {PREFIX}/helio/cat/ns/run the group {os.getgid()}:"
        " the directory does not exist"
    )


def test_the_catalog_step_fails_on_a_directory_that_it_cannot_read_and_changes_nothing(
    lake: MemoryStorage,
) -> None:
    lake.nodes[CATALOG].mode = 0o750
    lake.unreadable.add(RUN)
    with pytest.raises(StorageError) as refused:
        Provisioner(lake, PREFIX).provision_catalog(target())
    assert refused.value.message == f"the CLI cannot read {PREFIX}/helio/cat/ns/run"
    assert refused.value.context == {"path": f"{PREFIX}/helio/cat/ns/run"}
    assert lake.nodes[CATALOG].mode == 0o750


def test_a_catalog_directory_that_cannot_be_listed_is_named_by_its_path_on_this_machine(
    lake: MemoryStorage,
) -> None:
    lake.unreadable.add(CATALOG)
    with pytest.raises(PermissionDenied) as refused:
        Provisioner(lake, PREFIX).provision_catalog(target())
    assert (refused.value.message, refused.value.context) == (
        f"permission denied on {PREFIX}/helio/cat",
        {"path": f"{PREFIX}/helio/cat", "error": os.strerror(errno.EACCES)},
    )


@NEEDS_SHELL
def test_the_catalog_script_has_one_find_line_for_each_catalog() -> None:
    odd = LakePath.of("helio", "it's")
    script = catalog_script(PREFIX, [target(), target(1000, odd)])
    assert script.splitlines() == [
        "#!/bin/sh",
        "# Give each catalog directory and every directory in it the group of the catalog and"
        " the mode 2750: huron adm provision-catalogs --emit-script.",
        "# Run it as root. Files keep their group and mode. Running it again is harmless.",
        "set -eu",
        "",
        f"find {PREFIX}/helio/cat -type d -exec chgrp readers {{}} + -exec chmod 2750 {{}} +",
        f"find '{PREFIX}/helio/it'\"'\"'s' -type d -exec chgrp 1000 {{}} + -exec chmod 2750 {{}} +",
    ]
    assert "chgrp -R" not in script
    checked = subprocess.run(["sh", "-n"], input=script, text=True, check=False)
    assert checked.returncode == 0


@NEEDS_SHELL
def test_the_catalog_script_changes_directories_and_never_files(tmp_path: Path) -> None:
    lake = tmp_path / "lake"
    name = "$(touch pwned)"
    catalog = lake / "helio" / name
    (catalog / "ns" / "run").mkdir(parents=True)
    placed = catalog / "ns" / "run" / "a.bin"
    placed.write_bytes(b"x")
    os.chmod(placed, 0o600)
    for directory in (catalog, catalog / "ns", catalog / "ns" / "run"):
        os.chmod(directory, 0o755)
    script = tmp_path / "catalogs.sh"
    location = LakePath.of("helio", name)
    script.write_text(catalog_script(str(lake), [target(os.getgid(), location)]))
    done = subprocess.run(
        ["sh", str(script)], capture_output=True, text=True, check=False, cwd=tmp_path
    )
    assert done.returncode == 0, done.stderr
    for directory in (catalog, catalog / "ns", catalog / "ns" / "run"):
        info = os.lstat(directory)
        assert (stat.S_IMODE(info.st_mode), info.st_gid) == (DIRECTORY_MODE, os.getgid())
    assert stat.S_IMODE(os.lstat(placed).st_mode) == 0o600
    assert not (tmp_path / "pwned").exists()
    assert provision_catalogs(PosixStorage(lake), [target(os.getgid(), location)], GROUPS.get) == []
