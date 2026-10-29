"""Layout, ACL plans, the marker and both storage adapters."""

import grp
import hashlib
import os
import stat
from pathlib import Path

import pytest

from huron.core.storage import (
    MARKER_FILE,
    DirectoryKind,
    EffectiveGroups,
    FileStamp,
    Marker,
    StorageError,
    diff,
    is_reserved_entry,
    plan,
    read_marker,
    render_marker,
    resolve,
    verify_marker,
)
from huron.core.storage.factory import storage_for
from huron.core.storage.memory import MemoryStorage
from huron.core.storage.posix import PosixStorage
from huron.pkg.fs.acl import Acl, AclEntry, CompletedRun, SubprocessRunner, acl_supported

GROUPS = EffectiveGroups(
    platform_admin=("platform",),
    org_admin=("org",),
    catalog_admin=("cadmin",),
    contributor=("contrib",),
    reader=("read",),
)


def named(acl_entries: frozenset[AclEntry]) -> dict[str, str]:
    return {e.qualifier: e.perms for e in acl_entries if e.tag == "group" and e.qualifier}


def test_resolve_refuses_escapes() -> None:
    prefix = Path("/projects/huron")
    assert resolve(prefix, "helio/heliophysics") == prefix / "helio" / "heliophysics"
    for bad in ("../etc", "/abs", "a//b", "a/./b", ""):
        with pytest.raises(StorageError):
            resolve(prefix, bad)


def test_reserved_entries() -> None:
    assert is_reserved_entry("metadata.json")
    assert is_reserved_entry("x/a.bin.huron-part")
    assert is_reserved_entry(".huron")
    assert not is_reserved_entry("sub/metadata.json")


@pytest.mark.parametrize(
    ("kind", "mode", "access", "default", "owner"),
    [
        (
            DirectoryKind.ORGANIZATION,
            0o2771,
            {"platform": "rwx", "org": "rwx"},
            {"platform": "rwx", "org": "rwx"},
            "org",
        ),
        (
            DirectoryKind.CATALOG,
            0o2770,
            {"platform": "rwx", "org": "rwx", "cadmin": "rwx", "contrib": "r-x", "read": "r-x"},
            {"platform": "rwx", "org": "rwx"},
            "cadmin",
        ),
        (
            DirectoryKind.NAMESPACE,
            0o2770,
            {"platform": "rwx", "org": "rwx", "cadmin": "rwx", "contrib": "r-x", "read": "r-x"},
            {"platform": "rwx", "org": "rwx"},
            "cadmin",
        ),
        (
            DirectoryKind.NAMESPACE_WITH_COLLECTIONS,
            0o3770,
            {"platform": "rwx", "org": "rwx", "cadmin": "rwx", "contrib": "rwx", "read": "r-x"},
            {"platform": "rwx", "org": "rwx"},
            "contrib",
        ),
        (
            DirectoryKind.COLLECTION,
            0o2770,
            {"platform": "rwx", "org": "rwx", "cadmin": "rwx", "contrib": "rwx", "read": "r-x"},
            {"platform": "rwx", "org": "rwx", "cadmin": "rwx", "contrib": "rwx", "read": "r-x"},
            "contrib",
        ),
    ],
)
def test_plans_follow_the_table(
    kind: DirectoryKind, mode: int, access: dict[str, str], default: dict[str, str], owner: str
) -> None:
    planned = plan(kind, GROUPS)
    assert planned.mode == mode and planned.owning_group == owner
    assert named(planned.acl.access) == access
    assert named(planned.acl.default) == default
    other = next(e for e in planned.acl.access if e.tag == "other")
    assert other.perms == ("--x" if kind is DirectoryKind.ORGANIZATION else "---")
    assert diff(planned, planned.acl) == []


def test_plans_without_groups_and_diffs() -> None:
    planned = plan(DirectoryKind.CATALOG, EffectiveGroups())
    assert planned.owning_group is None
    groups = EffectiveGroups.from_mapping({"reader": ["r"], "ignored": ["x"]})
    assert groups.reader == ("r",)
    reader_plan = plan(DirectoryKind.CATALOG, groups)
    problems = diff(reader_plan, Acl(frozenset({AclEntry("group", "intruder", "rwx")})))
    assert "unexpected group:intruder:rwx" in problems
    assert any(p.startswith("missing default:") for p in problems)
    stray = Acl(reader_plan.acl.access, reader_plan.acl.default | {AclEntry("group", "z", "r-x")})
    assert diff(reader_plan, stray) == ["unexpected default:group:z:r-x"]


def test_marker_round_trip_and_refusals(tmp_path: Path) -> None:
    storage = MemoryStorage(tmp_path)
    with pytest.raises(StorageError, match="not a Huron share"):
        read_marker(storage, tmp_path)
    with pytest.raises(StorageError, match="not mounted"):
        read_marker(storage, tmp_path / "missing")
    storage.write_bytes(tmp_path / MARKER_FILE, b"{not json")
    with pytest.raises(StorageError, match="unreadable"):
        read_marker(storage, tmp_path)
    storage.write_bytes(tmp_path / MARKER_FILE, render_marker(Marker(1, "http://a", "id-1")))
    assert verify_marker(storage, tmp_path, "id-1").api_url == "http://a"
    with pytest.raises(StorageError, match="another Huron service"):
        verify_marker(storage, tmp_path, "id-2")


def test_memory_storage_behaves_like_a_share(tmp_path: Path) -> None:
    root = Path("/share")
    storage = MemoryStorage(root, user="dave")
    planned = plan(DirectoryKind.COLLECTION, GROUPS)
    with pytest.raises(StorageError):
        storage.ensure_directory(root / "a" / "b", planned)
    assert storage.ensure_directory(root / "a", planned) is True
    assert storage.ensure_directory(root / "a", planned) is False
    assert storage.apply_plan(root / "a", planned) is False
    assert storage.read_acl(root / "a") == planned.acl
    source = tmp_path / "f.bin"
    source.write_bytes(b"abc")
    stamp = storage.copy_in(source, root / "a", "x/y/f.bin")
    assert stamp == FileStamp(3, hashlib.sha256(b"abc").hexdigest())
    assert storage.copy_in(source, root / "a", "x/y/f.bin", stamp) == stamp
    assert [e.rel_path for e in storage.walk(root / "a")] == ["x", "x/y", "x/y/f.bin"]
    assert storage.stamp(root / "a" / "x" / "y" / "f.bin").size == 3
    assert storage.read_bytes(root / "nope") is None
    with pytest.raises(StorageError):
        storage.copy_in(tmp_path / "missing", root / "a", "m")
    with pytest.raises(StorageError):
        storage.remove_directory(root / "a")
    assert storage.remove_file(root / "a" / "x" / "y" / "f.bin") is True
    assert storage.remove_file(root / "a" / "nope") is False
    assert storage.remove_directory(root / "missing") is False
    storage.write_bytes(root / "file", b"")
    with pytest.raises(StorageError):
        storage.ensure_directory(root / "file", planned)
    other = MemoryStorage(root, user="erin")
    other.nodes = storage.nodes
    assert not other.owned_by_me(root / "a") and storage.owned_by_me(root / "a")
    with pytest.raises(StorageError, match="only the owner"):
        other.apply_plan(root / "a", plan(DirectoryKind.CATALOG, GROUPS))
    storage.denied.add(root)
    with pytest.raises(StorageError, match="permission denied"):
        storage.ensure_directory(root / "b", planned)
    with pytest.raises(StorageError):
        storage.stamp(root / "gone")
    assert storage.exists(root / "a") and not storage.is_directory(root / "file")


@pytest.fixture
def group() -> str:
    return grp.getgrgid(os.getgid()).gr_name


def test_posix_storage_creates_directories_with_modes_and_acls(tmp_path: Path, group: str) -> None:
    acls = acl_supported(tmp_path, SubprocessRunner())
    storage = storage_for("posix" if acls else "none")
    groups = EffectiveGroups(platform_admin=(group,), contributor=(group,))
    planned = plan(DirectoryKind.COLLECTION, groups)
    target = tmp_path / "c"
    assert storage.ensure_directory(target, planned) is True
    assert stat.S_IMODE(os.lstat(target).st_mode) == 0o2770
    assert storage.ensure_directory(target, planned) is False
    assert storage.apply_plan(target, planned) is False
    if acls:
        assert diff(planned, storage.read_acl(target)) == []
    os.chmod(target, 0o755)
    assert storage.apply_plan(target, planned) is True
    assert storage.apply_plan(target, plan(DirectoryKind.CATALOG, EffectiveGroups())) is True
    with pytest.raises(StorageError, match="does not exist"):
        storage.ensure_directory(tmp_path / "x" / "y", planned)
    assert storage.owned_by_me(target)


def test_posix_storage_copies_files_and_reports_failures(tmp_path: Path) -> None:
    storage = PosixStorage("none", SubprocessRunner())
    source = tmp_path / "src.bin"
    source.write_bytes(b"payload")
    collection = tmp_path / "col"
    collection.mkdir()
    stamp = storage.copy_in(source, collection, "a/b/f.bin")
    assert stamp.size == 7 and stat.S_IMODE(os.lstat(collection / "a").st_mode) == 0o2770
    assert storage.copy_in(source, collection, "a/b/f.bin", stamp) == stamp
    assert storage.hash(collection / "a" / "b" / "f.bin") == stamp
    assert [e.rel_path for e in storage.walk(collection)] == ["a", "a/b", "a/b/f.bin"]
    assert storage.stamp(collection / "a" / "b" / "f.bin").size == 7
    storage.write_bytes(collection / "metadata.json", b"{}")
    assert storage.read_bytes(collection / "metadata.json") == b"{}"
    assert storage.read_bytes(collection / "none") is None
    assert storage.exists(collection) and storage.is_directory(collection)
    with pytest.raises(StorageError):
        storage.copy_in(tmp_path / "missing", collection, "m")
    with pytest.raises(StorageError):
        storage.remove_directory(collection)
    assert storage.remove_file(collection / "metadata.json") is True
    assert storage.remove_directory(tmp_path / "nope") is False
    read = storage.read_acl(collection)
    assert AclEntry("user", None, "rwx") in read.access


def test_posix_storage_turns_permission_errors_into_storage_errors(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from huron.pkg.fs import posix

    def refuse(*args: object) -> None:
        raise PermissionError(13, "Permission denied")

    monkeypatch.setattr(posix, "atomic_write", refuse)
    storage = PosixStorage("none", SubprocessRunner())
    with pytest.raises(StorageError, match="permission denied"):
        storage.write_bytes(tmp_path / "f", b"x")


def test_posix_storage_group_changes(tmp_path: Path, group: str, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    storage = PosixStorage("none", SubprocessRunner())
    target = tmp_path / "d"
    target.mkdir()
    unknown = EffectiveGroups(catalog_admin=("no-such-group-xyz",))
    assert storage.apply_plan(target, plan(DirectoryKind.CATALOG, unknown)) is True
    mine = EffectiveGroups(catalog_admin=(group,))
    storage.apply_plan(target, plan(DirectoryKind.CATALOG, mine))
    other = next((g for g in grp.getgrall() if g.gr_gid != os.getgid()), None)
    if other is not None:

        def refuse(*args: object) -> None:
            raise PermissionError("no")

        monkeypatch.setattr(os, "chown", refuse)
        changed = storage.apply_plan(
            target, plan(DirectoryKind.CATALOG, EffectiveGroups(catalog_admin=(other.gr_name,)))
        )
        assert changed is False
        monkeypatch.undo()
        assert storage.apply_plan(
            target, plan(DirectoryKind.CATALOG, EffectiveGroups(catalog_admin=(other.gr_name,)))
        ) is (os.geteuid() == 0)


def test_posix_acl_failures_surface(tmp_path: Path) -> None:
    class Failing:
        def run(self, argv, stdin=None):  # type: ignore[no-untyped-def]
            if argv[0] == "getfacl":
                return CompletedRun(0, "user::rwx\ngroup::r-x\nother::---\n", "")
            return CompletedRun(1, "", "Operation not supported")

    storage = PosixStorage("posix", Failing())  # type: ignore[arg-type]
    target = tmp_path / "d"
    target.mkdir(mode=0o2770)
    with pytest.raises(Exception, match="setfacl failed"):
        storage.apply_plan(target, plan(DirectoryKind.CATALOG, GROUPS))
    storage.write_bytes(target / "x", b"x")
    with pytest.raises(StorageError):
        storage.hash(target / "missing")


def test_copy_in_leaves_the_mode_of_existing_subdirectories_alone(tmp_path: Path) -> None:
    storage = storage_for("none")
    source = tmp_path / "source.txt"
    source.write_bytes(b"data")
    collection = tmp_path / "collection"
    (collection / "sub").mkdir(parents=True)
    os.chmod(collection / "sub", 0o750)
    storage.copy_in(source, collection, "sub/new/file.txt")
    assert stat.S_IMODE(os.lstat(collection / "sub").st_mode) == 0o750
    assert stat.S_IMODE(os.lstat(collection / "sub" / "new").st_mode) == 0o2770
    assert (collection / "sub" / "new" / "file.txt").read_bytes() == b"data"
