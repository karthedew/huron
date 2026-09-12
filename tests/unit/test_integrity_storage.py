"""Maintenance inspection hashes actual files without following unsafe entries."""

import hashlib
import os
from pathlib import Path

import pytest

from huron.core.integrity.ports import LegacyStorage
from huron.pkg.rawstore.maintenance import MaintenanceStore

pytestmark = pytest.mark.unit


@pytest.fixture
def envelope(tmp_path: Path) -> tuple[MaintenanceStore, str, dict[str, tuple[int, str]]]:
    """Create a sealed revision with one nested payload and one control document."""
    relative = "organization/org/project/project/dataset/data/raw/revision/revision"
    revision = tmp_path / relative
    (revision / "payload" / "nested").mkdir(parents=True)
    expected = {}
    for name, payload in (("payload/nested/file", b"science"), ("COMMITTED", b"{}")):
        path = revision / name
        path.write_bytes(payload)
        path.chmod(0o444)
        expected[name] = len(payload), hashlib.sha256(payload).hexdigest()
    for directory in (revision, revision / "payload", revision / "payload" / "nested"):
        directory.chmod(0o555)
    return MaintenanceStore(tmp_path, os.geteuid()), relative, expected


def test_inspection_streams_exact_inventory_and_reads_original_document(
    envelope: tuple[MaintenanceStore, str, dict[str, tuple[int, str]]],
) -> None:
    """A valid sealed independent tree yields exact paths and no findings."""
    store, path, expected = envelope
    assert isinstance(store, LegacyStorage)
    assert list(store.revision_paths()) == [path]
    assert store.read_control(path, "COMMITTED") == b"{}"
    assert store.inspect_revision(path, expected) == ()
    assert store.inspect_revision(path, None) == ()


def test_corrupt_payload_and_extra_empty_directory_are_findings(
    tmp_path: Path, envelope: tuple[MaintenanceStore, str, dict[str, tuple[int, str]]]
) -> None:
    """Content mismatch and undeclared empty directories cannot pass inventory verification."""
    store, path, expected = envelope
    payload = tmp_path / path / "payload" / "nested" / "file"
    payload.chmod(0o644)
    payload.write_bytes(b"changed")
    assert store.inspect_revision(path, expected) == ("INVENTORY_MISMATCH", "UNSEALED")
    payload.write_bytes(b"science")
    payload.chmod(0o444)
    revision = tmp_path / path
    revision.chmod(0o755)
    (revision / "extra").mkdir(mode=0o555)
    revision.chmod(0o555)
    assert store.inspect_revision(path, expected) == ("INVENTORY_MISMATCH",)


def test_shared_inode_and_link_targets_are_never_certified(
    tmp_path: Path, envelope: tuple[MaintenanceStore, str, dict[str, tuple[int, str]]]
) -> None:
    """A shared inode is flagged and a symlink is never followed."""
    store, path, expected = envelope
    revision = tmp_path / path
    revision.chmod(0o755)
    os.link(revision / "COMMITTED", revision / "alias")
    (revision / "escape").symlink_to(tmp_path)
    revision.chmod(0o555)
    assert store.inspect_revision(path, expected) == (
        "INVENTORY_MISMATCH",
        "SHARED_INODE",
        "UNSAFE_ENTRY",
    )
    assert "WRONG_OWNER" in MaintenanceStore(tmp_path, os.geteuid() + 1).inspect_revision(
        path, expected
    )
    revision.chmod(0o755)
    (revision / "escape").unlink()


@pytest.mark.parametrize("path", ["", "/absolute", "../outside", "a//b", "a/./b"])
def test_maintenance_rejects_unsafe_relative_paths(tmp_path: Path, path: str) -> None:
    """Traversal inputs cannot escape or alias the storage root."""
    with pytest.raises(ValueError, match="unsafe maintenance path"):
        MaintenanceStore(tmp_path, os.geteuid()).read_control(path, "COMMITTED")


def test_control_documents_require_single_names_and_regular_files(
    tmp_path: Path, envelope: tuple[MaintenanceStore, str, dict[str, tuple[int, str]]]
) -> None:
    """Control reads reject nested names, special files and excessive documents."""
    store, path, _ = envelope
    with pytest.raises(ValueError, match="one component"):
        store.read_control(path, "payload/file")
    with pytest.raises(ValueError, match="bounded regular file"):
        store.read_control(path, "payload")
    revision = tmp_path / path
    revision.chmod(0o755)
    with (revision / "large").open("wb") as output:
        output.truncate((64 << 20) + 1)
    with pytest.raises(ValueError, match="bounded regular file"):
        store.read_control(path, "large")


def test_protocol_evidence_is_durable_and_cannot_be_replaced(tmp_path: Path) -> None:
    """A report is atomically installed and conflicting replay leaves its bytes intact."""
    store = MaintenanceStore(tmp_path, os.geteuid())
    store.write_evidence("reports/run.json", b"{}")
    store.write_evidence("reports/run.json", b"{}")
    with pytest.raises(ValueError, match="conflicts"):
        store.write_evidence("reports/run.json", b"changed")
    assert (tmp_path / "protocol/reports/run.json").read_bytes() == b"{}"
    assert list((tmp_path / "protocol/workspace").iterdir()) == []
    assert (tmp_path / "protocol/reports/run.json").stat().st_nlink == 1


def test_empty_hierarchy_and_dataset_without_revisions(tmp_path: Path) -> None:
    """Unpopulated collections and datasets without Raw revisions have empty inventory."""
    store = MaintenanceStore(tmp_path, os.geteuid())
    assert list(store.revision_paths()) == []
    (tmp_path / "organization/org/project/project/dataset/data/raw").mkdir(parents=True)
    assert list(store.revision_paths()) == []


def test_control_read_refuses_growth_beyond_its_declared_size(
    envelope: tuple[MaintenanceStore, str, dict[str, tuple[int, str]]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A control file growing after fstat cannot exhaust unbounded memory."""
    store, path, _ = envelope
    blocks = iter([b"x" * (1 << 20)] * 65 + [b""])
    monkeypatch.setattr(os, "read", lambda descriptor, size: next(blocks))
    with pytest.raises(ValueError, match="exceeded its byte bound"):
        store.read_control(path, "COMMITTED")


def test_changed_file_kind_is_refused_before_reading(
    envelope: tuple[MaintenanceStore, str, dict[str, tuple[int, str]]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A file replaced with a directory between listing and open is never read as payload."""
    store, path, expected = envelope
    original = os.open

    def opened(
        name: str | Path, flags: int, mode: int = 0o777, *, dir_fd: int | None = None
    ) -> int:
        """Expose the replaced directory at the filesystem boundary."""
        return original("payload" if name == "COMMITTED" else name, flags, mode, dir_fd=dir_fd)

    monkeypatch.setattr(os, "open", opened)
    assert "UNSAFE_ENTRY" in store.inspect_revision(path, expected)


def test_one_unreadable_entry_does_not_hide_other_corruption(
    tmp_path: Path,
    envelope: tuple[MaintenanceStore, str, dict[str, tuple[int, str]]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An I/O failure becomes an explicit finding while sibling seals are inspected."""
    store, path, expected = envelope
    (tmp_path / path / "payload/nested/file").chmod(0o644)
    original = os.open

    def opened(
        name: str | Path, flags: int, mode: int = 0o777, *, dir_fd: int | None = None
    ) -> int:
        """Inject a failed control-file open at the operating-system boundary."""
        if name == "COMMITTED":
            raise OSError("injected storage read failure")
        return original(name, flags, mode, dir_fd=dir_fd)

    monkeypatch.setattr(os, "open", opened)
    assert store.inspect_revision(path, expected) == (
        "ENTRY_IO_ERROR",
        "INVENTORY_MISMATCH",
        "UNSEALED",
    )


def test_storage_claim_excludes_independent_instances_and_releases_after_error(tmp_path: Path) -> None:
    """Ownership is attached to the storage inode and survives only its open descriptor."""
    first = MaintenanceStore(tmp_path, tmp_path.stat().st_uid)
    second = MaintenanceStore(tmp_path, tmp_path.stat().st_uid)
    with pytest.raises(RuntimeError, match="interrupted"):
        with first.claim():
            with pytest.raises(BlockingIOError):
                with second.claim():
                    pytest.fail("conflicting owner admitted")
            raise RuntimeError("interrupted")
    with second.claim():
        second.write_evidence("owned.json", b"durable")
    assert first.read_control("protocol", "owned.json") == b"durable"


@pytest.mark.parametrize("kind", ["symlink", "hardlink", "public", "fifo", "directory"])
def test_storage_claim_refuses_unsafe_lock_inodes(tmp_path: Path, kind: str) -> None:
    """A permanent independent private regular inode is required for shared ownership."""
    store = MaintenanceStore(tmp_path, tmp_path.stat().st_uid)
    protocol = tmp_path / "protocol"
    protocol.mkdir()
    lock = protocol / ".maintenance.lock"
    target = tmp_path / "target"
    target.touch(mode=0o600)
    if kind == "symlink":
        lock.symlink_to(target)
    elif kind == "hardlink":
        os.link(target, lock)
    elif kind == "fifo":
        os.mkfifo(lock, 0o600)
    elif kind == "directory":
        lock.mkdir()
    else:
        lock.touch(mode=0o644)
    with pytest.raises((OSError, ValueError)):
        with store.claim():
            pytest.fail("unsafe ownership admitted")
