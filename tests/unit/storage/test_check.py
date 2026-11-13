"""Drift findings on both adapters: one case per finding code, and a check that only reads."""

import copy
import errno
import hashlib
import os
from collections.abc import Callable, Iterator
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from huron.core.storage import (
    DIRECTORY_MODE,
    FILE_MODE,
    MARKER_FILE,
    OBJECT_DIR,
    OBJECT_DIR_MODE,
    ORGANIZATION_MODE,
    Entry,
    LakePath,
    LakeUnavailable,
    Marker,
    ShareReader,
    Storage,
    StorageError,
    render_marker,
)
from huron.core.storage.check import (
    STALE_DRAFT_AGE,
    STALE_PART_AGE,
    STALE_PROBE_AGE,
    ExpectedCollection,
    ExpectedDirectory,
    ExpectedOrganization,
    Finding,
    Severity,
    check,
    check_organization,
    unreadable_detail,
)
from huron.core.storage.memory import MemoryStorage
from huron.core.storage.posix import PosixStorage
from tests.fakes.storage import Unmounted
from tests.support.clock import START
from tests.support.disk import plant_symlink, snapshot

ORGANIZATION = LakePath.of("o")
CATALOG = ORGANIZATION.joinpath("c")
NAMESPACE = CATALOG.joinpath("ns")
RUN = NAMESPACE.joinpath("run")
SIDECAR = b'{"huron":1}\n'
INSTANCE = "id-1"
#: The group names that this machine knows, for the cases that resolve a share group.
GROUPS = {"readers": 4242}
NAMESPACES = [ExpectedDirectory("c.ns", "o/c/ns")]
LINK_DETAIL = (
    "the lake must not contain symbolic links. The storage administrator must remove this link"
)
PROBE = ".huron-link-probe-0123456789abcdef0123456789abcdef"
EPOCH = datetime(1970, 1, 1, tzinfo=UTC)


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def before_start(age: timedelta) -> int:
    """The moment ``age`` before :data:`START`, in nanoseconds since the epoch."""
    return (START - age - EPOCH) // timedelta(microseconds=1) * 1000


@dataclass
class Share:
    """A lake with ``o/c/ns/run`` that holds ``a.txt`` and ``metadata.json``, on one adapter.

    ``owner`` and ``gid`` are the owner and the group of the catalog directory. ``close`` makes
    a directory that the check cannot list, ``touch`` sets the modification time of an entry in
    nanoseconds since the epoch, and ``state`` is everything on the lake, to compare before and
    after a check.
    """

    storage: Storage
    close: Callable[[LakePath], None]
    touch: Callable[[LakePath, int], None]
    state: Callable[[], object]
    owner: int = 0
    gid: int = 0

    def put(self, location: LakePath, data: bytes = b"x", mode: int = FILE_MODE) -> None:
        self.storage.write_bytes(location, data, mode)

    def mkdir(self, location: LakePath, mode: int = DIRECTORY_MODE) -> None:
        self.storage.make_directory(location, mode)


@pytest.fixture(params=["posix", "memory"])
def share(
    request: pytest.FixtureRequest, tmp_path: Path, temporary_mode: Callable[[Path, int], None]
) -> Share:
    made: Share
    if request.param == "posix":
        root = tmp_path / "lake"
        root.mkdir()

        def place(location: LakePath) -> Path:
            return root.joinpath(*location.names)

        def touch(location: LakePath, mtime_ns: int) -> None:
            os.utime(place(location), ns=(mtime_ns, mtime_ns), follow_symlinks=False)

        made = Share(
            PosixStorage(root),
            lambda location: temporary_mode(place(location), 0o000),
            touch,
            lambda: snapshot(root),
        )
    else:
        memory = MemoryStorage(Path("/share"))
        memory.nodes[LakePath()].gid = memory.gid

        def touch_node(location: LakePath, mtime_ns: int) -> None:
            memory.nodes[location].mtime_ns = mtime_ns

        made = Share(
            memory,
            memory.unreadable.add,
            touch_node,
            lambda: (copy.deepcopy(memory.nodes), list(memory.calls)),
        )
    made.mkdir(ORGANIZATION, ORGANIZATION_MODE)
    for location in (CATALOG, NAMESPACE, RUN):
        made.mkdir(location)
    made.put(RUN.joinpath("a.txt"), b"alpha")
    made.put(RUN.joinpath("metadata.json"), SIDECAR)
    found = made.storage.stat(CATALOG)
    assert found is not None
    made.owner, made.gid = found.uid, found.gid
    return made


def expected_catalog(share: Share, **overrides: Any) -> ExpectedDirectory:
    return replace(ExpectedDirectory("c", "o/c", group=share.gid, owner=share.owner), **overrides)


def expected_collection(share: Share, **overrides: Any) -> ExpectedCollection:
    files = {"a.txt": {"rel_path": "a.txt", "size": 5, "sha256": sha(b"alpha")}}
    found = ExpectedCollection(
        "c.ns.run", "active", START, "o/c/ns/run", files, SIDECAR, owner=share.owner
    )
    return replace(found, **overrides)


def run_check(
    share: Share,
    *,
    top: ExpectedDirectory | None = None,
    namespaces: list[ExpectedDirectory] | None = None,
    collections: list[ExpectedCollection] | None = None,
    now: datetime = START,
    hash_files: bool = False,
) -> list[Finding]:
    if namespaces is None:
        namespaces = [ExpectedDirectory("c.ns", "o/c/ns", owner=share.owner)]
    return check(
        share.storage,
        top or expected_catalog(share),
        namespaces,
        [expected_collection(share)] if collections is None else collections,
        now,
        groups=GROUPS.get,
        hash_files=hash_files,
    )


def codes(share: Share, **arguments: Any) -> list[tuple[str, str]]:
    """The code and the path of each finding."""
    return [(f.code, f.path) for f in run_check(share, **arguments)]


def test_a_clean_tree_has_no_findings(share: Share) -> None:
    assert run_check(share, hash_files=True) == []


def test_missing_directories_and_files(share: Share) -> None:
    share.storage.remove_file(RUN.joinpath("a.txt"))
    assert codes(share) == [("file_missing", "o/c/ns/run/a.txt")]
    moved = expected_collection(share, disk_path="o/c/ns/other")
    assert codes(share, collections=[moved]) == [
        ("collection_dir_missing", "o/c/ns/other"),
        ("dir_unrecorded", "o/c/ns/run"),
    ]
    gone = [ExpectedDirectory("c.gone", "o/c/gone")]
    findings = run_check(share, namespaces=gone, collections=[])
    assert [(f.code, f.severity, f.path) for f in findings] == [
        ("namespace_dir_missing", Severity.ERROR, "o/c/gone"),
        ("dir_unrecorded", Severity.WARNING, "o/c/ns"),
    ]


def test_a_missing_catalog_directory_has_every_directory_below_it_missing(share: Share) -> None:
    findings = run_check(
        share,
        top=expected_catalog(share, identifier="x", disk_path="o/x"),
        namespaces=[ExpectedDirectory("x.ns", "o/x/ns")],
        collections=[expected_collection(share, identifier="x.ns.run", disk_path="o/x/ns/run")],
    )
    assert [(f.code, f.identifier, f.path) for f in findings] == [
        ("namespace_dir_missing", "x", "o/x"),
        ("namespace_dir_missing", "x.ns", "o/x/ns"),
        ("collection_dir_missing", "x.ns.run", "o/x/ns/run"),
    ]


def test_changed_and_unrecorded_files(share: Share) -> None:
    share.put(RUN.joinpath("a.txt"), b"ALPHA")
    assert codes(share) == []
    assert codes(share, hash_files=True) == [("file_changed", "o/c/ns/run/a.txt")]
    share.put(RUN.joinpath("a.txt"), b"longer")
    share.put(RUN.joinpath("stray"))
    findings = run_check(share)
    assert [(f.code, f.detail) for f in findings] == [
        ("file_changed", "size 6, but the recorded size is 5"),
        ("file_unrecorded", ""),
    ]


def test_every_file_directly_in_a_namespace_or_catalog_directory_is_unrecorded(
    share: Share,
) -> None:
    share.put(NAMESPACE.joinpath("loose.txt"))
    share.put(NAMESPACE.joinpath("metadata.json"))
    share.put(NAMESPACE.joinpath("x.huron-part"))
    share.put(CATALOG.joinpath("top.txt"))
    share.put(CATALOG.joinpath(MARKER_FILE))
    assert codes(share) == [
        ("file_unrecorded", "o/c/.huron"),
        ("file_unrecorded", "o/c/top.txt"),
        ("file_unrecorded", "o/c/ns/loose.txt"),
        ("file_unrecorded", "o/c/ns/metadata.json"),
        ("file_unrecorded", "o/c/ns/x.huron-part"),
    ]


def test_a_snapshot_file_and_an_nfs_directory_in_a_catalog_or_namespace_are_unrecorded(
    share: Share,
) -> None:
    share.put(CATALOG.joinpath(".snapshot"))
    share.mkdir(NAMESPACE.joinpath(".nfs000000000123abcd00000001"))
    assert codes(share) == [
        ("file_unrecorded", "o/c/.snapshot"),
        ("dir_unrecorded", "o/c/ns/.nfs000000000123abcd00000001"),
    ]


def test_unrecorded_directories_and_stale_sidecars(share: Share) -> None:
    share.mkdir(NAMESPACE.joinpath("mystery"))
    assert codes(share, collections=[expected_collection(share, sidecar=b"other")]) == [
        ("dir_unrecorded", "o/c/ns/mystery"),
        ("sidecar_stale", "o/c/ns/run/metadata.json"),
    ]


@pytest.mark.parametrize(("beyond", "stale"), [(0, False), (1, True)])
def test_a_part_file_is_stale_after_one_hour(share: Share, beyond: int, stale: bool) -> None:
    part = RUN.joinpath(".a.txt.0192b6a0-0000-7000-8000-000000000009.huron-part")
    share.put(part)
    share.touch(part, before_start(STALE_PART_AGE) - beyond)
    found = run_check(share)
    assert found == ([Finding("stale_part", Severity.INFO, "c.ns.run", str(part))] if stale else [])


def test_informational_findings_of_drafts_and_incomplete_collections(share: Share) -> None:
    later = START + STALE_DRAFT_AGE + timedelta(days=10)
    incomplete = run_check(share, collections=[expected_collection(share, state="incomplete")])
    assert [(f.code, f.detail) for f in incomplete] == [
        ("incomplete", "metadata does not satisfy the catalog schema")
    ]
    draft = expected_collection(share, state="draft", disk_path=None)
    assert codes(share, collections=[draft]) == [("dir_unrecorded", "o/c/ns/run")]
    stale = run_check(share, collections=[draft], now=later)
    assert [(f.code, f.detail) for f in stale] == [
        ("dir_unrecorded", ""),
        ("stale_draft", "older than 30 days"),
    ]


def test_a_pending_commit_is_information_and_its_mix_of_files_is_no_drift(share: Share) -> None:
    share.put(RUN.joinpath("a.txt"), b"new bytes")
    share.put(RUN.joinpath("added.txt"))
    pending = expected_collection(
        share,
        pending="accepted",
        files={"gone.txt": {"rel_path": "gone.txt", "size": 1, "sha256": sha(b"x")}},
    )
    findings = run_check(share, collections=[pending], hash_files=True)
    assert [f.as_dict() for f in findings] == [
        {
            "code": "pending_commit",
            "severity": "info",
            "identifier": "c.ns.run",
            "path": "o/c/ns/run",
            "detail": "a commit request is accepted."
            " Until the request ends, the directory can hold old and new files",
        }
    ]


def test_a_pending_commit_still_reports_a_stale_temporary_name(share: Share) -> None:
    part = RUN.joinpath(".b.0192b6a0-0000-7000-8000-000000000009.huron-part")
    share.put(part)
    share.touch(part, before_start(timedelta(hours=2)))
    pending = expected_collection(share, pending="blocked")
    assert codes(share, collections=[pending]) == [
        ("pending_commit", "o/c/ns/run"),
        ("stale_part", str(part)),
    ]


def test_an_nfs_file_and_a_snapshot_directory_are_information(share: Share) -> None:
    nfs = RUN.joinpath(".nfs000000000123abcd00000001")
    share.put(nfs, mode=0o600)
    share.put(CATALOG.joinpath(".nfs000000000123abcd00000002"), mode=0o600)
    share.mkdir(NAMESPACE.joinpath(".snapshot"), 0o777)
    share.put(NAMESPACE.joinpath(".snapshot", "copy.txt"))
    findings = run_check(share)
    assert [(f.code, f.severity, f.path, f.detail) for f in findings] == [
        (
            "nfs_file",
            Severity.INFO,
            "o/c/.nfs000000000123abcd00000002",
            "an NFS client keeps this removed file while a process holds it open",
        ),
        (
            "snapshot_dir",
            Severity.INFO,
            "o/c/ns/.snapshot",
            "the storage shows its snapshots here. The check does not read them",
        ),
        (
            "nfs_file",
            Severity.INFO,
            str(nfs),
            "an NFS client keeps this removed file while a process holds it open",
        ),
    ]


def test_a_collection_with_an_nfs_file_and_a_snapshot_directory_gives_only_information(
    share: Share,
) -> None:
    nfs = RUN.joinpath(".nfs000000000123abcd00000003")
    snapshots = RUN.joinpath(".snapshot")
    share.put(nfs, mode=0o600)
    share.mkdir(snapshots, 0o777)
    share.mkdir(snapshots.joinpath("hourly.0"), 0o755)
    share.put(snapshots.joinpath("hourly.0", "a.txt"), b"old", 0o600)
    share.put(snapshots.joinpath("hourly.0", "metadata.json"), b"{}")
    findings = run_check(share, hash_files=True)
    assert [(f.code, f.severity, f.path) for f in findings] == [
        ("nfs_file", Severity.INFO, str(nfs)),
        ("snapshot_dir", Severity.INFO, str(snapshots)),
    ]


def test_the_mode_of_each_directory_and_file_is_compared(share: Share) -> None:
    share.storage.set_mode(NAMESPACE, 0o750)
    share.storage.set_mode(RUN.joinpath("a.txt"), 0o600)
    findings = run_check(share)
    assert [(f.code, f.identifier, f.path, f.detail) for f in findings] == [
        ("mode_drift", "c.ns", "o/c/ns", "the mode is 750, not 2750"),
        ("mode_drift", "c.ns.run", "o/c/ns/run/a.txt", "the mode is 600, not 644"),
    ]


def test_the_owner_is_compared_only_when_the_service_reports_it(share: Share) -> None:
    other = share.owner + 1
    namespaces = [ExpectedDirectory("c.ns", "o/c/ns", owner=other)]
    top = expected_catalog(share, owner=None)
    findings = run_check(share, top=top, namespaces=namespaces)
    assert [(f.code, f.path, f.detail) for f in findings] == [
        ("mode_drift", "o/c/ns", f"the owner is {share.owner}, not the service user {other}")
    ]
    assert run_check(share, top=top, namespaces=[ExpectedDirectory("c.ns", "o/c/ns")]) == []


def test_a_directory_below_a_catalog_needs_the_group_of_the_catalog_directory() -> None:
    memory = MemoryStorage(Path("/share"))
    memory.nodes[LakePath()].gid = memory.gid
    memory.member_of.add(2001)
    for location in (ORGANIZATION, CATALOG, NAMESPACE, RUN):
        memory.make_directory(location, DIRECTORY_MODE)
    memory.write_bytes(RUN.joinpath("placed.bin"), b"x", FILE_MODE)
    memory.nodes[RUN.joinpath("placed.bin")].gid = 2001
    memory.nodes[RUN].gid = 2001
    findings = check(
        memory,
        ExpectedDirectory("c", "o/c"),
        [ExpectedDirectory("c.ns", "o/c/ns")],
        [ExpectedCollection("c.ns.run", "active", START, "o/c/ns/run", sidecar=None)],
        START,
        groups=GROUPS.get,
    )
    assert [(f.code, f.path, f.detail) for f in findings] == [
        (
            "mode_drift",
            "o/c/ns/run",
            f"the group is 2001, not {memory.gid} (the group of the catalog directory)",
        ),
        ("file_unrecorded", "o/c/ns/run/placed.bin", ""),
    ]


def test_a_row_with_its_own_group_is_compared_with_that_group(share: Share) -> None:
    findings = run_check(share, namespaces=[ExpectedDirectory("c.ns", "o/c/ns", group="readers")])
    assert [(f.code, f.path, f.detail) for f in findings] == [
        ("mode_drift", "o/c/ns", f"the group is {share.gid}, not 4242 (the group readers)")
    ]


@pytest.mark.parametrize(
    ("group", "detail"),
    [
        ("readers", "the group is {gid}, not 4242 (the share group readers)"),
        ("nobody-knows", "this machine does not know the share group nobody-knows"),
        (4343, "the group is {gid}, not 4343 (the service group)"),
    ],
)
def test_a_catalog_directory_needs_its_share_group(
    share: Share, group: str | int, detail: str
) -> None:
    findings = run_check(share, top=expected_catalog(share, group=group))
    assert [(f.code, f.severity, f.path, f.detail) for f in findings] == [
        ("share_group_mismatch", Severity.WARNING, "o/c", detail.format(gid=share.gid))
    ]


def test_a_catalog_directory_with_its_share_group_or_none_has_no_mismatch(share: Share) -> None:
    assert run_check(share, top=expected_catalog(share, group=None)) == []
    assert run_check(share, top=expected_catalog(share, group=share.gid)) == []


def test_a_catalog_directory_has_its_own_mode_and_owner(share: Share) -> None:
    share.storage.set_mode(CATALOG, 0o755)
    findings = run_check(share, top=expected_catalog(share, owner=share.owner + 1))
    assert [(f.code, f.path) for f in findings] == [("mode_drift", "o/c")] * 2


def test_an_unreadable_directory_is_reported_and_nothing_below_it_is_missing(
    share: Share,
) -> None:
    share.mkdir(RUN.joinpath("sub"))
    share.put(RUN.joinpath("sub", "b.txt"))
    files = {
        "a.txt": {"rel_path": "a.txt", "size": 5, "sha256": sha(b"alpha")},
        "sub/b.txt": {"rel_path": "sub/b.txt", "size": 1, "sha256": sha(b"x")},
    }
    share.close(RUN.joinpath("sub"))
    findings = run_check(share, collections=[expected_collection(share, files=files)])
    assert [(f.code, f.severity, f.path, f.detail) for f in findings] == [
        ("unreadable", Severity.WARNING, "o/c/ns/run/sub", unreadable_detail(errno.EACCES))
    ]


def test_an_unreadable_namespace_hides_the_rows_below_it(share: Share) -> None:
    share.close(NAMESPACE)
    assert codes(share) == [("unreadable", "o/c/ns")]


def test_a_catalog_directory_that_cannot_be_listed_is_one_unreadable_finding(
    share: Share,
) -> None:
    share.close(CATALOG)
    findings = run_check(share)
    assert [(f.code, f.detail) for f in findings if f.code != "mode_drift"] == [
        ("unreadable", "permission denied on o/c")
    ]
    assert {f.path for f in findings} == {"o/c"}


def test_a_catalog_directory_that_cannot_be_reached_is_one_unreadable_finding(
    share: Share,
) -> None:
    share.close(ORGANIZATION)
    assert [(f.code, f.path, f.detail) for f in run_check(share)] == [
        ("unreadable", "o/c", "permission denied on o/c")
    ]


class RefusingFiles(MemoryStorage):
    """A lake whose files refuse each read, as files that the account cannot read."""

    def open_file(self, location: LakePath) -> None:
        raise StorageError(f"permission denied on {location}", {"path": str(location)})

    def read_bytes(self, location: LakePath) -> bytes | None:
        raise StorageError(f"permission denied on {location}", {"path": str(location)})


def memory_tree(storage: MemoryStorage) -> list[ExpectedCollection]:
    """Make ``o/c/ns/run`` with ``a.txt`` in ``storage``; the collection that records it.

    The namespace ``c.ns`` is :data:`NAMESPACES`.
    """
    storage.nodes[LakePath()].gid = storage.gid
    for location in (ORGANIZATION, CATALOG, NAMESPACE, RUN):
        storage.make_directory(location, DIRECTORY_MODE)
    storage.write_bytes(RUN.joinpath("a.txt"), b"alpha", FILE_MODE)
    files = {"a.txt": {"rel_path": "a.txt", "size": 5, "sha256": sha(b"alpha")}}
    return [ExpectedCollection("c.ns.run", "active", START, "o/c/ns/run", files)]


def test_a_file_that_cannot_be_read_is_unreadable_and_no_drift() -> None:
    storage = RefusingFiles(Path("/share"))
    collections = memory_tree(storage)
    findings = check(
        storage,
        ExpectedDirectory("c", "o/c"),
        NAMESPACES,
        collections,
        START,
        groups=GROUPS.get,
        hash_files=True,
    )
    assert [(f.code, f.path, f.detail) for f in findings] == [
        ("unreadable", "o/c/ns/run/a.txt", "permission denied on o/c/ns/run/a.txt"),
        ("unreadable", "o/c/ns/run/metadata.json", "permission denied on o/c/ns/run/metadata.json"),
    ]


def test_a_symbolic_link_anywhere_is_an_error(share: Share) -> None:
    plant_symlink(share.storage, RUN.joinpath("link"))
    plant_symlink(share.storage, CATALOG.joinpath("other"))
    findings = run_check(share)
    assert [(f.code, f.severity, f.identifier, f.path, f.detail) for f in findings] == [
        ("symbolic_link", Severity.ERROR, "c", "o/c/other", LINK_DETAIL),
        ("symbolic_link", Severity.ERROR, "c.ns.run", "o/c/ns/run/link", LINK_DETAIL),
    ]


def test_a_link_at_a_namespace_is_an_error_and_the_namespace_is_missing(share: Share) -> None:
    plant_symlink(share.storage, CATALOG.joinpath("lnk"))
    linked = [ExpectedDirectory("c.lnk", "o/c/lnk")]
    assert codes(share, namespaces=[*linked], collections=[]) == [
        ("namespace_dir_missing", "o/c/lnk"),
        ("symbolic_link", "o/c/lnk"),
        ("dir_unrecorded", "o/c/ns"),
    ]


def test_a_link_on_the_way_to_the_catalog_directory_is_the_one_finding(share: Share) -> None:
    plant_symlink(share.storage, ORGANIZATION.joinpath("linked"))
    findings = run_check(share, top=expected_catalog(share, disk_path="o/linked/c"))
    assert [(f.code, f.path) for f in findings] == [("symbolic_link", "o/linked")]


def test_the_check_changes_nothing_on_the_share(share: Share) -> None:
    share.put(RUN.joinpath("stray"))
    share.put(RUN.joinpath(".nfs1"))
    share.mkdir(NAMESPACE.joinpath(".snapshot"))
    share.mkdir(NAMESPACE.joinpath("mystery"))
    share.storage.set_mode(NAMESPACE, 0o750)
    plant_symlink(share.storage, RUN.joinpath("link"))
    old = RUN.joinpath("x.huron-part")
    share.put(old)
    share.touch(old, before_start(timedelta(days=1)))
    before = share.state()
    assert run_check(share, hash_files=True, now=START)
    assert share.state() == before


def test_a_lake_that_is_not_mounted_stops_the_check() -> None:
    with pytest.raises(LakeUnavailable):
        check(
            Unmounted(),
            ExpectedDirectory("c", "o/c"),
            [],
            [],
            START,
            groups=GROUPS.get,
        )


def test_findings_render_for_output(share: Share) -> None:
    finding = run_check(share, collections=[expected_collection(share, files={})])[0]
    assert finding.as_dict() == {
        "code": "file_unrecorded",
        "severity": "warning",
        "identifier": "c.ns.run",
        "path": "o/c/ns/run/a.txt",
        "detail": "",
    }


def test_the_detail_of_an_unreadable_entry_names_the_error() -> None:
    assert unreadable_detail(errno.EACCES) == "Permission denied (errno 13)"
    assert unreadable_detail(errno.EIO) == "Input/output error (errno 5)"


class VanishingFiles(MemoryStorage):
    """A lake whose files are gone by the time the check opens them."""

    def open_file(self, location: LakePath) -> None:
        return None


def test_a_hash_of_a_file_gone_since_the_walk_is_a_change() -> None:
    storage = VanishingFiles(Path("/share"))
    collections = memory_tree(storage)
    findings = check(
        storage,
        ExpectedDirectory("c", "o/c"),
        NAMESPACES,
        collections,
        START,
        groups=GROUPS.get,
        hash_files=True,
    )
    assert [(f.code, f.detail) for f in findings] == [
        ("file_changed", "sha256 is not the recorded sha256")
    ]


def organization(share: Share, **overrides: Any) -> ExpectedOrganization:
    found = ExpectedOrganization(
        "o", ORGANIZATION, INSTANCE, own_marker=True, group=share.gid, owner=share.owner
    )
    return replace(found, **overrides)


def marked(share: Share) -> Share:
    share.put(
        ORGANIZATION.joinpath(MARKER_FILE), render_marker(Marker(1, "http://a", INSTANCE, "o"))
    )
    return share


def test_a_prepared_organization_directory_has_no_findings(share: Share) -> None:
    share.mkdir(ORGANIZATION.joinpath(OBJECT_DIR), OBJECT_DIR_MODE)
    assert check_organization(marked(share).storage, organization(share), START) == []


def test_an_organization_directory_has_its_mode_owner_and_group(share: Share) -> None:
    marked(share).storage.set_mode(ORGANIZATION, 0o755)
    wanted = organization(share, owner=share.owner + 1, group=share.gid + 1)
    findings = check_organization(share.storage, wanted, START)
    assert [(f.code, f.path, f.detail) for f in findings] == [
        ("mode_drift", "o", "the mode is 755, not 2751"),
        ("mode_drift", "o", f"the owner is {share.owner}, not the service user {share.owner + 1}"),
        ("mode_drift", "o", f"the group is {share.gid}, not {share.gid + 1} (the service group)"),
    ]


@pytest.mark.parametrize(("beyond", "stale"), [(0, False), (1, True)])
def test_a_probe_file_older_than_one_hour_is_reported_and_kept(
    share: Share, beyond: int, stale: bool
) -> None:
    marked(share).mkdir(ORGANIZATION.joinpath(OBJECT_DIR), OBJECT_DIR_MODE)
    probes = [ORGANIZATION.joinpath(PROBE), ORGANIZATION.joinpath(OBJECT_DIR, PROBE)]
    for probe in probes:
        share.put(probe, b"")
        share.touch(probe, before_start(STALE_PROBE_AGE) - beyond)
    findings = check_organization(share.storage, organization(share), START)
    detail = "the file is older than 1 hour. A readiness probe that stopped left it"
    reported = [Finding("stale_link_probe", Severity.INFO, "o", str(p), detail) for p in probes]
    assert findings == (reported if stale else [])
    assert all(share.storage.stat(probe) is not None for probe in probes)


def test_an_nfs_file_and_a_snapshot_directory_in_an_organization_directory_are_information(
    share: Share,
) -> None:
    area = ORGANIZATION.joinpath(OBJECT_DIR)
    marked(share).mkdir(area, OBJECT_DIR_MODE)
    nfs = ORGANIZATION.joinpath(".nfs000000000123abcd00000001")
    snapshots = ORGANIZATION.joinpath(".snapshot")
    share.put(nfs, mode=0o600)
    share.mkdir(snapshots, 0o777)
    share.put(snapshots.joinpath("copy.txt"))
    share.put(area.joinpath(".nfs000000000123abcd00000002"), mode=0o600)
    before = share.state()
    findings = check_organization(share.storage, organization(share), START)
    assert findings == [
        Finding(
            "nfs_file",
            Severity.INFO,
            "o",
            "o/.nfs000000000123abcd00000001",
            "an NFS client keeps this removed file while a process holds it open",
        ),
        Finding(
            "snapshot_dir",
            Severity.INFO,
            "o",
            "o/.snapshot",
            "the storage shows its snapshots here. The check does not read them",
        ),
    ]
    assert share.state() == before


def test_probe_and_nfs_directories_and_a_snapshot_file_in_an_organization_give_no_finding(
    share: Share,
) -> None:
    marked(share).mkdir(ORGANIZATION.joinpath(".nfs000000000123abcd00000001"))
    share.put(ORGANIZATION.joinpath(".snapshot"))
    share.mkdir(ORGANIZATION.joinpath(PROBE))
    share.touch(ORGANIZATION.joinpath(PROBE), before_start(timedelta(hours=2)))
    assert check_organization(share.storage, organization(share), START) == []


def test_an_organization_without_an_object_area_has_no_finding_about_it(share: Share) -> None:
    assert check_organization(marked(share).storage, organization(share), START) == []


def test_an_object_area_that_the_account_may_not_list_is_skipped(share: Share) -> None:
    marked(share).mkdir(ORGANIZATION.joinpath(OBJECT_DIR), OBJECT_DIR_MODE)
    probe = ORGANIZATION.joinpath(PROBE)
    share.put(probe, b"")
    share.touch(probe, before_start(timedelta(hours=2)))
    share.close(ORGANIZATION.joinpath(OBJECT_DIR))
    findings = check_organization(share.storage, organization(share), START)
    assert [(f.code, f.path) for f in findings] == [("stale_link_probe", str(probe))]


class FailingListing:
    """Reads go to ``share``; a listing of the directory ``place`` fails with an I/O error."""

    def __init__(self, share: ShareReader, place: LakePath) -> None:
        self.share = share
        self.place = place

    def walk(self, location: LakePath, *, recursive: bool = True) -> Iterator[Entry]:
        if location == self.place:
            raise StorageError(f"{location}: Input/output error", {"path": str(location)})
        return self.share.walk(location, recursive=recursive)

    def __getattr__(self, name: str) -> Any:
        return getattr(self.share, name)


def test_an_object_area_that_fails_to_list_for_another_reason_is_unreadable(
    share: Share,
) -> None:
    area = ORGANIZATION.joinpath(OBJECT_DIR)
    marked(share).mkdir(area, OBJECT_DIR_MODE)
    findings = check_organization(FailingListing(share.storage, area), organization(share), START)
    assert [(f.code, f.path, f.detail) for f in findings] == [
        ("unreadable", "o/.huron-objects", "o/.huron-objects: Input/output error")
    ]


def test_links_in_an_organization_directory_are_errors(share: Share) -> None:
    plant_symlink(marked(share).storage, ORGANIZATION.joinpath("stray"))
    plant_symlink(share.storage, ORGANIZATION.joinpath(OBJECT_DIR))
    findings = check_organization(share.storage, organization(share), START)
    assert [(f.code, f.path, f.detail) for f in findings] == [
        ("symbolic_link", "o/.huron-objects", LINK_DETAIL),
        ("symbolic_link", "o/stray", LINK_DETAIL),
    ]


def test_a_link_in_the_object_area_is_an_error(share: Share) -> None:
    area = ORGANIZATION.joinpath(OBJECT_DIR)
    marked(share).mkdir(area, OBJECT_DIR_MODE)
    plant_symlink(share.storage, area.joinpath("lnk"))
    findings = check_organization(share.storage, organization(share), START)
    assert [(f.code, f.severity, f.path, f.detail) for f in findings] == [
        ("symbolic_link", Severity.ERROR, "o/.huron-objects/lnk", LINK_DETAIL)
    ]


def test_an_entry_of_the_object_area_that_cannot_be_stat_ed_is_unreadable(
    tmp_path: Path, temporary_mode: Callable[[Path, int], None]
) -> None:
    lake = tmp_path / "lake"
    (lake / "o" / OBJECT_DIR / "sealed").mkdir(parents=True)
    temporary_mode(lake / "o", 0o755)
    temporary_mode(lake / "o" / OBJECT_DIR, 0o600)
    expected = ExpectedOrganization("o", ORGANIZATION, INSTANCE, own_marker=False, mode=0o755)
    findings = check_organization(PosixStorage(lake), expected, START)
    assert [(f.code, f.path, f.detail) for f in findings] == [
        ("unreadable", "o/.huron-objects/sealed", unreadable_detail(errno.EACCES))
    ]


def test_an_organization_directory_that_cannot_be_listed_is_unreadable(share: Share) -> None:
    marked(share).mkdir(ORGANIZATION.joinpath(OBJECT_DIR), OBJECT_DIR_MODE)
    share.close(ORGANIZATION)
    findings = check_organization(share.storage, organization(share), START)
    assert [(f.code, f.path, f.detail) for f in findings if f.code != "mode_drift"] == [
        ("unreadable", "o/.huron", "permission denied on o/.huron"),
        ("unreadable", "o", "permission denied on o"),
    ]


def test_an_organization_directory_that_cannot_be_reached_is_unreadable(share: Share) -> None:
    share.close(LakePath())
    findings = check_organization(share.storage, organization(share), START)
    assert [(f.code, f.path, f.detail) for f in findings] == [
        ("unreadable", "o", "permission denied on o")
    ]


def test_an_organization_directory_that_is_a_link_is_an_error(share: Share) -> None:
    plant_symlink(share.storage, LakePath.of("linked"))
    findings = check_organization(
        share.storage, organization(share, name="linked", directory=LakePath.of("linked")), START
    )
    assert [(f.code, f.path) for f in findings] == [("symbolic_link", "linked")]


def untrusted(share: Share, wanted: ExpectedOrganization) -> bool:
    return wanted.untrusted(check_organization(share.storage, wanted, START))


def test_a_missing_directory_or_a_link_to_it_makes_an_organization_untrusted(
    share: Share,
) -> None:
    gone = LakePath.of("gone")
    assert untrusted(share, organization(share, name="gone", directory=gone))
    plant_symlink(share.storage, LakePath.of("linked"))
    assert untrusted(share, organization(share, name="linked", directory=LakePath.of("linked")))
    below = organization(share, directory=LakePath.of("linked", "o"))
    assert untrusted(share, below)
    assert not untrusted(share, organization(share, name="gone", directory=gone, own_marker=False))
    assert not untrusted(share, replace(below, own_marker=False))


def test_a_missing_or_wrong_marker_makes_an_organization_untrusted(share: Share) -> None:
    share.mkdir(ORGANIZATION.joinpath(OBJECT_DIR), OBJECT_DIR_MODE)
    assert untrusted(share, organization(share))
    share.put(ORGANIZATION.joinpath(MARKER_FILE), render_marker(Marker(1, "http://a", "id-2", "o")))
    assert untrusted(share, organization(share))
    assert not untrusted(share, organization(share, own_marker=False))


def test_a_marker_that_is_a_link_makes_an_organization_untrusted(share: Share) -> None:
    marker = ORGANIZATION.joinpath(MARKER_FILE)
    plant_symlink(share.storage, marker)
    findings = check_organization(share.storage, organization(share), START)
    assert [(f.code, f.path) for f in findings] == [
        ("symbolic_link", str(marker)),
        ("symbolic_link", str(marker)),
    ]
    assert organization(share).untrusted(findings)
    assert not organization(share, own_marker=False).untrusted(findings)


class RefusingMarker:
    """Reads go to ``share``; a read of the marker of :data:`ORGANIZATION` is refused."""

    def __init__(self, share: ShareReader) -> None:
        self.share = share

    def read_bytes(self, location: LakePath) -> bytes | None:
        if location == ORGANIZATION.joinpath(MARKER_FILE):
            raise StorageError(f"permission denied on {location}", {"path": str(location)})
        return self.share.read_bytes(location)

    def __getattr__(self, name: str) -> Any:
        return getattr(self.share, name)


def test_a_marker_that_cannot_be_read_leaves_an_organization_trusted(share: Share) -> None:
    marked(share).mkdir(ORGANIZATION.joinpath(OBJECT_DIR), OBJECT_DIR_MODE)
    findings = check_organization(RefusingMarker(share.storage), organization(share), START)
    assert [(f.code, f.path) for f in findings] == [("unreadable", "o/.huron")]
    assert not organization(share).untrusted(findings)


def test_links_and_unreadable_entries_in_an_organization_leave_it_trusted(share: Share) -> None:
    area = ORGANIZATION.joinpath(OBJECT_DIR)
    marked(share).mkdir(area, OBJECT_DIR_MODE)
    plant_symlink(share.storage, ORGANIZATION.joinpath("stray"))
    plant_symlink(share.storage, area.joinpath("lnk"))
    share.storage.set_mode(ORGANIZATION, 0o755)
    findings = check_organization(share.storage, organization(share), START)
    assert {f.code for f in findings} == {"symbolic_link", "mode_drift"}
    assert not organization(share).untrusted(findings)
    assert not organization(share).untrusted(
        [Finding("unreadable", Severity.WARNING, "o", "o", "permission denied on o")]
    )


def test_an_organization_directory_without_its_own_marker_has_no_marker_finding(
    share: Share,
) -> None:
    assert check_organization(share.storage, organization(share, own_marker=False), START) == []


def test_an_entry_that_is_no_file_directory_or_link_gives_no_finding(tmp_path: Path) -> None:
    lake = tmp_path / "lake"
    (lake / "o" / "c").mkdir(parents=True)
    os.chmod(lake / "o" / "c", DIRECTORY_MODE)
    os.mkfifo(lake / "o" / "c" / "pipe")
    storage = PosixStorage(lake)
    assert check(storage, ExpectedDirectory("c", "o/c"), [], [], START, groups=GROUPS.get) == []


def test_an_entry_of_an_organization_directory_that_cannot_be_stat_ed_is_unreadable(
    tmp_path: Path, temporary_mode: Callable[[Path, int], None]
) -> None:
    lake = tmp_path / "lake"
    (lake / "o" / "c").mkdir(parents=True)
    storage = PosixStorage(lake)
    found = storage.stat(ORGANIZATION)
    assert found is not None
    temporary_mode(lake / "o", 0o640)
    expected = ExpectedOrganization("o", ORGANIZATION, INSTANCE, own_marker=False, mode=0o640)
    findings = check_organization(storage, expected, START)
    assert [(f.code, f.path, f.detail) for f in findings] == [
        ("unreadable", "o/c", unreadable_detail(errno.EACCES))
    ]
