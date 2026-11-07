"""Layout, modes, ACL plans, the marker and both storage adapters."""

import errno
import grp
import hashlib
import os
import stat
from pathlib import Path
from types import SimpleNamespace

import pytest

from huron.core.storage import (
    DIRECTORY_MODE,
    FILE_MODE,
    MARKER_FILE,
    ORGANIZATION_MODE,
    UPLOAD_DIR_MODE,
    DirectoryKind,
    EffectiveGroups,
    FileStamp,
    GroupOutcome,
    GroupResult,
    Marker,
    Ownership,
    Storage,
    StorageError,
    diff,
    is_reserved_entry,
    mode_of,
    plan,
    read_marker,
    render_marker,
    resolve,
    verify_marker,
)
from huron.core.storage.factory import storage_for
from huron.core.storage.memory import ROOT_DEVICE, MemoryStorage, Node
from huron.core.storage.posix import PosixStorage
from huron.pkg.fs.acl import Acl, AclEntry, CompletedRun, SubprocessRunner, acl_supported
from tests.support.disk import LAKE

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


@pytest.mark.parametrize(
    ("kind", "mode"),
    [
        (DirectoryKind.ORGANIZATION, 0o2751),
        (DirectoryKind.CATALOG, 0o2750),
        (DirectoryKind.NAMESPACE, 0o2750),
        (DirectoryKind.NAMESPACE_WITH_COLLECTIONS, 0o2750),
        (DirectoryKind.COLLECTION, 0o2750),
    ],
)
def test_each_kind_of_directory_has_its_mode(kind: DirectoryKind, mode: int) -> None:
    assert mode_of(kind) == mode


def test_files_and_the_upload_directory_have_their_modes() -> None:
    assert (FILE_MODE, UPLOAD_DIR_MODE) == (0o644, 0o700)


@pytest.fixture
def posix() -> PosixStorage:
    return storage_for("none")


def test_posix_make_directory_gives_exactly_the_mode(tmp_path: Path, posix: PosixStorage) -> None:
    target = tmp_path / "helio"
    assert posix.make_directory(target, ORGANIZATION_MODE) is True
    assert posix.owner(target) == Ownership(os.getuid(), os.lstat(target).st_gid, 0o2751)
    os.chmod(target, 0o755)
    assert posix.make_directory(target, ORGANIZATION_MODE) is False
    assert posix.owner(target).mode == 0o755


def test_posix_make_directory_refusals(
    tmp_path: Path, posix: PosixStorage, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "file").write_bytes(b"")
    with pytest.raises(StorageError, match="is not a directory"):
        posix.make_directory(tmp_path / "file", DIRECTORY_MODE)
    with pytest.raises(StorageError, match="does not exist"):
        posix.make_directory(tmp_path / "missing" / "d", DIRECTORY_MODE)

    def refuse(*args: object) -> None:
        raise PermissionError(errno.EACCES, "Permission denied")

    monkeypatch.setattr(os, "mkdir", refuse)
    with pytest.raises(StorageError, match="permission denied") as raised:
        posix.make_directory(tmp_path / "d", DIRECTORY_MODE)
    assert raised.value.context["path"] == str(tmp_path / "d")


def test_posix_set_mode_changes_only_a_different_mode(tmp_path: Path, posix: PosixStorage) -> None:
    target = tmp_path / "f"
    target.write_bytes(b"")
    os.chmod(target, 0o600)
    assert posix.set_mode(target, FILE_MODE) is True
    assert stat.S_IMODE(os.lstat(target).st_mode) == FILE_MODE
    assert posix.set_mode(target, FILE_MODE) is False
    with pytest.raises(StorageError):
        posix.set_mode(tmp_path / "missing", FILE_MODE)


def test_posix_set_group_keeps_a_matching_group(tmp_path: Path, posix: PosixStorage) -> None:
    target = tmp_path / "catalog"
    target.mkdir()
    name = grp.getgrgid(os.lstat(target).st_gid).gr_name
    assert posix.set_group(target, name) == GroupResult(GroupOutcome.UNCHANGED)


def test_posix_set_group_is_pending_for_an_unknown_group(
    tmp_path: Path, posix: PosixStorage
) -> None:
    result = posix.set_group(tmp_path, "no-such-group-xyz")
    assert result == GroupResult(
        GroupOutcome.PENDING, "this machine does not know the group no-such-group-xyz"
    )


@pytest.mark.parametrize("by_name", [True, False])
def test_posix_set_group_changes_the_group(
    tmp_path: Path, posix: PosixStorage, monkeypatch: pytest.MonkeyPatch, by_name: bool
) -> None:
    target = tmp_path / "catalog"
    target.mkdir()
    other = os.lstat(target).st_gid + 1
    calls: list[tuple[object, ...]] = []
    monkeypatch.setattr(grp, "getgrnam", lambda name: SimpleNamespace(gr_gid=other))
    monkeypatch.setattr(os, "chown", lambda *args, **kwargs: calls.append((*args, kwargs)))
    group = "helio-readers" if by_name else other
    assert posix.set_group(target, group) == GroupResult(GroupOutcome.CHANGED)
    assert calls == [(target, -1, other, {"follow_symlinks": False})]


def test_posix_set_group_is_pending_when_refused_or_missing(
    tmp_path: Path, posix: PosixStorage, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "catalog"
    target.mkdir()
    monkeypatch.setattr(grp, "getgrnam", lambda name: SimpleNamespace(gr_gid=os.getgid() + 1))
    missing = posix.set_group(tmp_path / "missing", "helio-readers")
    assert missing.outcome is GroupOutcome.PENDING
    assert missing.reason == f"{tmp_path / 'missing'}: No such file or directory"

    def refuse(*args: object, **kwargs: object) -> None:
        raise PermissionError(errno.EPERM, "Operation not permitted")

    monkeypatch.setattr(os, "chown", refuse)
    refused = posix.set_group(target, "helio-readers")
    assert refused == GroupResult(GroupOutcome.PENDING, f"{target}: Operation not permitted")


def test_posix_owner_and_device(tmp_path: Path, posix: PosixStorage) -> None:
    target = tmp_path / "f"
    target.write_bytes(b"")
    os.chmod(target, 0o640)
    info = os.lstat(target)
    assert posix.owner(target) == Ownership(info.st_uid, info.st_gid, 0o640)
    assert posix.device(target) == os.stat(tmp_path).st_dev
    for read in (posix.owner, posix.device):
        with pytest.raises(StorageError):
            read(tmp_path / "missing")


@pytest.fixture
def memory() -> MemoryStorage:
    """An in-memory lake whose root is a setgid directory of root's group (gid 0)."""
    return MemoryStorage(LAKE, user="huron", uid=1000, gid=1000)


def test_memory_make_directory_inherits_the_group_of_a_setgid_parent(
    memory: MemoryStorage,
) -> None:
    memory.member_of.add(0)
    assert memory.make_directory(LAKE / "helio", ORGANIZATION_MODE) is True
    assert memory.owner(LAKE / "helio") == Ownership(1000, 0, 0o2751)
    assert memory.make_directory(LAKE / "helio", DIRECTORY_MODE) is False
    assert memory.owner(LAKE / "helio").mode == 0o2751


def test_memory_make_directory_drops_setgid_outside_the_callers_groups(
    memory: MemoryStorage,
) -> None:
    memory.make_directory(LAKE / "helio", ORGANIZATION_MODE)
    assert memory.owner(LAKE / "helio") == Ownership(1000, 0, 0o751)
    memory.nodes[LAKE / "plain"] = Node(owner="huron", mode=0o755, uid=1000, gid=1000)
    memory.make_directory(LAKE / "plain" / "d", DIRECTORY_MODE)
    assert memory.owner(LAKE / "plain" / "d") == Ownership(1000, 1000, 0o2750)


def test_memory_make_directory_refusals(memory: MemoryStorage) -> None:
    memory.write_bytes(LAKE / "file", b"")
    with pytest.raises(StorageError, match="is not a directory"):
        memory.make_directory(LAKE / "file", DIRECTORY_MODE)
    with pytest.raises(StorageError, match="does not exist"):
        memory.make_directory(LAKE / "file" / "d", DIRECTORY_MODE)
    memory.denied.add(LAKE)
    with pytest.raises(StorageError, match="permission denied"):
        memory.make_directory(LAKE / "d", DIRECTORY_MODE)


def test_memory_set_mode(memory: MemoryStorage) -> None:
    memory.write_bytes(LAKE / "f", b"", 0o600)
    assert memory.set_mode(LAKE / "f", FILE_MODE) is True
    assert memory.set_mode(LAKE / "f", FILE_MODE) is False
    assert memory.owner(LAKE / "f").mode == FILE_MODE
    memory.member_of.add(0)
    memory.make_directory(LAKE / "d", 0o750)
    memory.member_of.discard(0)
    assert memory.set_mode(LAKE / "d", DIRECTORY_MODE) is True
    assert memory.owner(LAKE / "d").mode == 0o750
    with pytest.raises(StorageError, match="permission denied"):
        memory.set_mode(LAKE, 0o755)
    with pytest.raises(StorageError, match="does not exist"):
        memory.set_mode(LAKE / "missing", FILE_MODE)


def test_memory_set_group_outcomes(memory: MemoryStorage) -> None:
    memory.groups.update({"helio-readers": 2001, "geo-readers": 2002})
    memory.member_of.add(2001)
    memory.make_directory(LAKE / "cat", DIRECTORY_MODE)
    target = LAKE / "cat"
    assert memory.set_group(target, "unknown") == GroupResult.unknown("unknown")
    assert memory.set_group(LAKE / "missing", "helio-readers") == GroupResult(
        GroupOutcome.PENDING, f"{LAKE / 'missing'}: {os.strerror(errno.ENOENT)}"
    )
    assert memory.set_group(target, "geo-readers") == GroupResult(
        GroupOutcome.PENDING, f"{target}: {os.strerror(errno.EPERM)}"
    )
    assert memory.set_group(target, "helio-readers") == GroupResult(GroupOutcome.CHANGED)
    assert memory.owner(target).gid == 2001
    assert memory.set_group(target, "helio-readers") == GroupResult(GroupOutcome.UNCHANGED)
    assert memory.set_group(LAKE, "helio-readers").outcome is GroupOutcome.PENDING
    assert memory.set_group(target, 2002).outcome is GroupOutcome.PENDING
    assert memory.set_group(target, 1000) == GroupResult(GroupOutcome.CHANGED)
    assert memory.owner(target).gid == 1000


def test_memory_write_bytes_gives_a_file_the_group_of_a_setgid_parent(
    memory: MemoryStorage,
) -> None:
    memory.write_bytes(LAKE / "inherited", b"")
    assert memory.owner(LAKE / "inherited").gid == 0
    memory.nodes[LAKE / "plain"] = Node(owner="huron", mode=0o755, uid=1000, gid=2001)
    memory.write_bytes(LAKE / "plain" / "own", b"")
    assert memory.owner(LAKE / "plain" / "own").gid == 1000
    memory.nodes[LAKE / "plain"].mode = 0o2755
    memory.write_bytes(LAKE / "plain" / "own", b"again")
    assert memory.owner(LAKE / "plain" / "own").gid == 2001


def test_memory_device_follows_the_mount_points(memory: MemoryStorage) -> None:
    memory.mount(LAKE / "geo", 7)
    memory.make_directory(LAKE / "geo" / "cat", DIRECTORY_MODE)
    memory.make_directory(LAKE / "helio", DIRECTORY_MODE)
    assert memory.device(LAKE) == memory.device(LAKE / "helio") == ROOT_DEVICE
    assert memory.device(LAKE / "geo") == memory.device(LAKE / "geo" / "cat") == 7
    with pytest.raises(StorageError, match="does not exist"):
        memory.device(LAKE / "missing")


@pytest.fixture(params=["posix", "memory"])
def share(request: pytest.FixtureRequest, tmp_path: Path) -> tuple[Storage, Path]:
    """Each adapter with a setgid directory of the caller's group to work in."""
    if request.param == "posix":
        base = tmp_path / "share"
        base.mkdir()
        os.chmod(base, 0o2750)
        return storage_for("none"), base
    memory = MemoryStorage(LAKE, user="huron", uid=1000, gid=1000)
    memory.nodes[LAKE / "share"] = Node(owner="huron", mode=0o2750, uid=1000, gid=1000)
    return memory, LAKE / "share"


def test_make_inheriting_dir_inherits_setgid_and_the_group(share: tuple[Storage, Path]) -> None:
    storage, base = share
    target = base / "run7"
    assert storage.make_inheriting_dir(target) is True
    assert storage.owner(target).mode == DIRECTORY_MODE
    assert storage.owner(target).gid == storage.owner(base).gid
    assert storage.make_inheriting_dir(target) is False


def test_make_inheriting_dir_refusals(share: tuple[Storage, Path]) -> None:
    storage, base = share
    storage.write_bytes(base / "file", b"")
    with pytest.raises(StorageError, match="File exists"):
        storage.make_inheriting_dir(base / "file")
    storage.make_directory(base / "plain", 0o750)
    storage.set_mode(base / "plain", 0o750)
    with pytest.raises(StorageError, match="did not inherit the setgid bit"):
        storage.make_inheriting_dir(base / "plain" / "d")
    assert not storage.exists(base / "plain" / "d")
    with pytest.raises(StorageError):
        storage.make_inheriting_dir(base / "missing" / "d")


def test_an_open_file_reports_from_its_descriptor(share: tuple[Storage, Path]) -> None:
    storage, base = share
    storage.write_bytes(base / "upload", b"payload", 0o600)
    opened = storage.open_file(base / "upload")
    assert opened is not None
    try:
        assert (opened.size, opened.inode) == (7, storage.inode(base / "upload"))
        assert opened.sha256() == hashlib.sha256(b"payload").hexdigest()
        opened.set_mode(FILE_MODE)
    finally:
        opened.close()
    assert storage.owner(base / "upload").mode == FILE_MODE
    assert storage.open_file(base / "missing") is None


def test_link_gives_a_file_a_new_name(share: tuple[Storage, Path]) -> None:
    storage, base = share
    storage.write_bytes(base / "upload", b"new")
    assert storage.link(base / "upload", base / "a.bin", ".a.bin.1.huron-part") is True
    assert storage.inode(base / "a.bin") == storage.inode(base / "upload")
    assert storage.read_bytes(base / "a.bin") == b"new"


@pytest.mark.parametrize("stale_part", [False, True], ids=["no-part", "stale-part"])
def test_link_replaces_an_existing_file(share: tuple[Storage, Path], stale_part: bool) -> None:
    storage, base = share
    storage.write_bytes(base / "upload", b"new")
    storage.write_bytes(base / "a.bin", b"old")
    if stale_part:
        storage.write_bytes(base / ".a.bin.1.huron-part", b"stale")
    assert storage.link(base / "upload", base / "a.bin", ".a.bin.1.huron-part") is True
    assert storage.read_bytes(base / "a.bin") == b"new"
    assert storage.inode(base / "a.bin") == storage.inode(base / "upload")
    assert not storage.exists(base / ".a.bin.1.huron-part")


def test_link_without_a_source_is_false(share: tuple[Storage, Path]) -> None:
    storage, base = share
    assert storage.link(base / "missing", base / "a.bin", ".a.bin.1.huron-part") is False
    assert not storage.exists(base / "a.bin")
    storage.write_bytes(base / "upload", b"new")
    with pytest.raises(StorageError):
        storage.link(base / "upload", base / "missing" / "a.bin", ".a.bin.1.huron-part")


def test_inode_of_a_missing_path_is_none(share: tuple[Storage, Path]) -> None:
    storage, base = share
    assert storage.inode(base / "missing") is None
    assert storage.inode(base) is not None


def test_posix_link_and_open_failures_are_storage_errors(
    tmp_path: Path, posix: PosixStorage, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "upload"
    source.write_bytes(b"new")
    (tmp_path / "a.bin").mkdir()
    with pytest.raises(StorageError, match="Is a directory"):
        posix.link(source, tmp_path / "a.bin", ".a.bin.1.huron-part")
    with pytest.raises(StorageError, match="Not a directory"):
        posix.inode(source / "x")
    os.chmod(source, 0)
    with pytest.raises(StorageError, match="permission denied"):
        posix.open_file(source)
    os.chmod(source, 0o600)
    opened: list[int] = []
    real_open, real_fstat = os.open, os.fstat

    def recording_open(path: Path, flags: int) -> int:
        opened.append(real_open(path, flags))
        return opened[-1]

    def failing_fstat(descriptor: int) -> os.stat_result:
        if descriptor in opened:
            raise OSError(errno.EIO, "Input/output error")
        return real_fstat(descriptor)

    monkeypatch.setattr(os, "open", recording_open)
    monkeypatch.setattr(os, "fstat", failing_fstat)
    with pytest.raises(StorageError, match="Input/output error"):
        posix.open_file(source)
    monkeypatch.undo()
    with pytest.raises(OSError, match="Bad file descriptor"):
        real_fstat(opened[0])  # the failed open released its descriptor


def test_memory_open_file_refuses_a_directory_and_a_foreign_file(memory: MemoryStorage) -> None:
    with pytest.raises(StorageError, match="Is a directory"):
        memory.open_file(LAKE)
    memory.nodes[LAKE / "theirs"] = Node(owner="root", mode=0o600, uid=0, gid=0, data=b"")
    opened = memory.open_file(LAKE / "theirs")
    assert opened is not None
    with pytest.raises(StorageError, match="permission denied"):
        opened.set_mode(FILE_MODE)


def test_memory_without_inheritance_refuses_new_directories(memory: MemoryStorage) -> None:
    memory.inherits = False
    with pytest.raises(StorageError, match="did not inherit"):
        memory.make_inheriting_dir(LAKE / "d")
    memory.denied.add(LAKE)
    memory.inherits = True
    with pytest.raises(StorageError, match="permission denied"):
        memory.make_inheriting_dir(LAKE / "d")


def test_memory_link_into_a_denied_directory_is_refused(memory: MemoryStorage) -> None:
    memory.write_bytes(LAKE / "upload", b"new")
    memory.denied.add(LAKE)
    with pytest.raises(StorageError, match="permission denied"):
        memory.link(LAKE / "upload", LAKE / "a.bin", ".a.bin.1.huron-part")
