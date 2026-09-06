"""Direct contract tests for ``PosixRawStore``'s streaming, document and link primitives.

Each method the raw store exposes to the catalog gets its own tests here:
envelope claiming, range-addressed part writes (including out-of-order
parts, resends and mid-stream failures), the whole-file read-back,
hard-linking from a parent revision, sealing, and the small document
primitives. ``crash_on`` and ``fsync_log`` from ``tests.unit.support``
inject the same filesystem failures the crash-safety suite for
``commit_envelope`` uses, so a durability claim here is checked against
what is actually on disk, not against how the method happens to be written.
"""

from __future__ import annotations

import errno
import hashlib
import os
import stat
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from huron.pkg.rawstore import PartLengthMismatchError, PosixRawStore
from huron.pkg.rawstore.commit import CrossDeviceCommitError
from huron.pkg.rawstore.store import _safe_relative
from tests.unit.support import crash_on, fsync_log

if TYPE_CHECKING:
    from collections.abc import Iterator

pytestmark = pytest.mark.unit


def _initialized_store(tmp_path: Path) -> PosixRawStore:
    """Build a ``PosixRawStore`` rooted at ``tmp_path`` with its skeleton created.

    Args:
        tmp_path: The directory to root the store at.

    Returns:
        A store whose ``.staging`` and ``organization`` directories exist.
    """
    store = PosixRawStore(tmp_path)
    store.initialize()
    return store


def _staging_payload(store: PosixRawStore, name: str = "envelope") -> Path:
    """Claim a fresh staging envelope on ``store`` and return its ``payload`` directory.

    Args:
        store: The store to claim the envelope on.
        name: The envelope's name under ``.staging``.

    Returns:
        The new envelope's empty ``payload`` directory.
    """
    staging = store.root / ".staging" / name
    store.create_staging(staging)
    return staging / "payload"


def _with_different_device(result: os.stat_result) -> os.stat_result:
    """Return a copy of ``result`` with ``st_dev`` changed, every other field kept.

    Args:
        result: The real ``stat`` result to vary.

    Returns:
        An equivalent result reporting a different device number.
    """
    fields = (
        result.st_mode,
        result.st_ino,
        result.st_dev + 1,
        result.st_nlink,
        result.st_uid,
        result.st_gid,
        result.st_size,
        result.st_atime,
        result.st_mtime,
        result.st_ctime,
    )
    return os.stat_result(fields)


def test_initialize_creates_the_skeleton_and_refuses_a_cross_device_layout(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Initialize creates both directories and refuses a layout spanning two devices."""
    store = PosixRawStore(tmp_path)

    store.initialize()

    assert (tmp_path / ".staging").is_dir()
    assert (tmp_path / "organization").is_dir()

    crossed = PosixRawStore(tmp_path / "crossed")
    staging_root = crossed.root / ".staging"
    real_stat = type(staging_root).stat

    def _fake_stat(self: Path, *args: object, **kwargs: object) -> os.stat_result:
        result = real_stat(self, *args, **kwargs)
        return _with_different_device(result) if self == staging_root else result

    monkeypatch.setattr(type(staging_root), "stat", _fake_stat)

    with pytest.raises(CrossDeviceCommitError):
        crossed.initialize()


def test_create_staging_claims_a_private_envelope_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """create_staging makes a 0o700 envelope once, fsyncs its parents, and refuses a repeat."""
    store = _initialized_store(tmp_path)
    log = fsync_log(monkeypatch)
    staging = store.root / ".staging" / "abc123"

    store.create_staging(staging)

    assert stat.S_IMODE(staging.stat().st_mode) == 0o700
    assert stat.S_IMODE((staging / "payload").stat().st_mode) == 0o700
    assert log == [store.root / ".staging", staging, staging / "payload"]

    with pytest.raises(FileExistsError):
        store.create_staging(staging)

    with pytest.raises(ValueError):
        store.create_staging(store.root / "elsewhere" / "xyz789")


def test_write_part_pulls_one_chunk_at_a_time_and_reports_the_digest_of_the_bytes_written(
    tmp_path: Path,
) -> None:
    """write_part reads chunks lazily and returns the SHA-256 of the bytes it wrote."""
    store = _initialized_store(tmp_path)
    payload_root = _staging_payload(store)
    chunks = [b"abc", b"defgh", b"ij"]
    whole = b"".join(chunks)
    target = payload_root / "a.bin"

    def _spy() -> Iterator[bytes]:
        written = 0
        for chunk in chunks:
            if written:
                assert target.read_bytes() == whole[:written]
            written += len(chunk)
            yield chunk

    digest = store.write_part(payload_root, "a.bin", _spy(), offset=0, length=len(whole))

    assert digest == hashlib.sha256(whole).hexdigest()
    assert target.read_bytes() == whole


def test_write_part_places_parts_at_their_offsets_in_any_order(tmp_path: Path) -> None:
    """Parts written out of order assemble into the correct whole file."""
    store = _initialized_store(tmp_path)
    payload_root = _staging_payload(store)
    part_size = 4
    parts = [b"aaaa", b"bbbb", b"cccc"]

    for index in (2, 0, 1):
        store.write_part(
            payload_root, "f.bin", [parts[index]], offset=index * part_size, length=part_size
        )

    assert (payload_root / "f.bin").read_bytes() == b"".join(parts)


def test_write_part_overwrites_a_resent_part_s_range_only(tmp_path: Path) -> None:
    """Resending a part after a partial write overwrites only that part's range."""
    store = _initialized_store(tmp_path)
    payload_root = _staging_payload(store)
    part_size = 4
    store.write_part(payload_root, "f.bin", [b"1111"], offset=0, length=part_size)
    store.write_part(payload_root, "f.bin", [b"3333"], offset=2 * part_size, length=part_size)

    def _dropped() -> Iterator[bytes]:
        yield b"xx"
        raise ConnectionResetError("dropped mid-part")

    with pytest.raises(ConnectionResetError):
        store.write_part(payload_root, "f.bin", _dropped(), offset=part_size, length=part_size)

    store.write_part(payload_root, "f.bin", [b"2222"], offset=part_size, length=part_size)

    assert (payload_root / "f.bin").read_bytes() == b"111122223333"


def test_write_part_refuses_a_short_or_long_stream(tmp_path: Path) -> None:
    """A stream that ends short or runs long raises PartLengthMismatchError, no digest returned."""
    store = _initialized_store(tmp_path)
    payload_root = _staging_payload(store)

    with pytest.raises(PartLengthMismatchError):
        store.write_part(payload_root, "short.bin", [b"ab"], offset=0, length=3)

    with pytest.raises(PartLengthMismatchError):
        store.write_part(payload_root, "long.bin", [b"abcd"], offset=0, length=3)


def test_write_part_propagates_a_mid_stream_exception_and_leaves_the_range_for_the_resend(
    tmp_path: Path,
) -> None:
    """A client disconnect mid-stream propagates, and a resend of the same part succeeds."""
    store = _initialized_store(tmp_path)
    payload_root = _staging_payload(store)
    target = payload_root / "f.bin"

    def _dropped() -> Iterator[bytes]:
        yield b"ab"
        raise ConnectionResetError("client disconnected")

    with pytest.raises(ConnectionResetError):
        store.write_part(payload_root, "f.bin", _dropped(), offset=0, length=4)

    assert stat.S_IMODE(target.stat().st_mode) == 0o600
    assert target.read_bytes()[:2] == b"ab"

    digest = store.write_part(payload_root, "f.bin", [b"abcd"], offset=0, length=4)

    assert digest == hashlib.sha256(b"abcd").hexdigest()
    assert target.read_bytes() == b"abcd"


def test_write_part_fsyncs_the_file_and_every_directory_up_to_the_payload_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """write_part fsyncs the file and every directory from it up to the payload root."""
    store = _initialized_store(tmp_path)
    payload_root = _staging_payload(store)
    log = fsync_log(monkeypatch)

    store.write_part(payload_root, "d1/d2/f.bin", [b"data"], offset=0, length=4)

    target = payload_root / "d1" / "d2" / "f.bin"
    assert log == [target, target.parent, target.parent.parent, payload_root]
    assert stat.S_IMODE(target.parent.stat().st_mode) == 0o700
    assert stat.S_IMODE(target.parent.parent.stat().st_mode) == 0o700


def test_write_part_refuses_an_unsafe_path_before_touching_the_disk(tmp_path: Path) -> None:
    """An unsafe rel_path raises ValueError before any file or directory is created."""
    store = _initialized_store(tmp_path)
    payload_root = _staging_payload(store)

    with pytest.raises(ValueError, match="unsafe relative path"):
        store.write_part(payload_root, "../escape.bin", [b"x"], offset=0, length=1)

    assert list(payload_root.iterdir()) == []


def test_a_single_part_write_is_the_whole_file_observation(tmp_path: Path) -> None:
    """A single-part write's returned digest matches finish_file's whole-file observation."""
    store = _initialized_store(tmp_path)
    payload_root = _staging_payload(store)
    content = b"the whole file, in one part"

    digest = store.write_part(payload_root, "f.bin", [content], offset=0, length=len(content))
    size, finished_digest = store.finish_file(payload_root, "f.bin")

    assert (size, digest) == (len(content), finished_digest)


def test_finish_file_reports_size_and_digest_and_refuses_a_missing_file(tmp_path: Path) -> None:
    """finish_file reports the file's real size and digest, and refuses a missing file."""
    store = _initialized_store(tmp_path)
    payload_root = _staging_payload(store)
    content = b"x" * 5000
    store.write_part(payload_root, "f.bin", [content], offset=0, length=len(content))

    size, digest = store.finish_file(payload_root, "f.bin")

    assert size == len(content)
    assert digest == hashlib.sha256(content).hexdigest()

    with pytest.raises(FileNotFoundError):
        store.finish_file(payload_root, "missing.bin")


def test_discard_file_removes_the_file_and_tolerates_a_missing_one(tmp_path: Path) -> None:
    """discard_file removes an existing file and is a no-op for one already gone."""
    store = _initialized_store(tmp_path)
    payload_root = _staging_payload(store)
    store.write_part(payload_root, "f.bin", [b"data"], offset=0, length=4)

    store.discard_file(payload_root, "f.bin")

    assert not (payload_root / "f.bin").exists()

    store.discard_file(payload_root, "f.bin")


def test_hardlink_from_parent_links_the_inode_and_is_idempotent(tmp_path: Path) -> None:
    """hardlink_from_parent shares the parent's inode and a repeat call is a no-op."""
    store = _initialized_store(tmp_path)
    parent_payload = tmp_path / "parent" / "payload"
    parent_payload.mkdir(parents=True)
    source = parent_payload / "f.bin"
    source.write_bytes(b"shared")
    staging_payload = _staging_payload(store)

    store.hardlink_from_parent(parent_payload, staging_payload, "f.bin")

    target = staging_payload / "f.bin"
    assert target.stat().st_nlink == 2
    assert os.path.samefile(source, target)

    store.hardlink_from_parent(parent_payload, staging_payload, "f.bin")

    assert target.stat().st_nlink == 2
    assert os.path.samefile(source, target)


def test_hardlink_from_parent_replaces_a_foreign_file_at_the_target(tmp_path: Path) -> None:
    """A foreign file already at the target is replaced by the parent's inode."""
    store = _initialized_store(tmp_path)
    parent_payload = tmp_path / "parent" / "payload"
    parent_payload.mkdir(parents=True)
    source = parent_payload / "f.bin"
    source.write_bytes(b"shared")
    staging_payload = _staging_payload(store)
    target = staging_payload / "f.bin"
    target.write_bytes(b"a crashed attempt's bytes")

    store.hardlink_from_parent(parent_payload, staging_payload, "f.bin")

    assert os.path.samefile(source, target)


def test_hardlink_from_parent_copies_when_linking_fails_and_the_copy_is_enabled(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """When linking fails and the fallback is enabled, the file is copied instead."""
    store = _initialized_store(tmp_path)
    parent_payload = tmp_path / "parent" / "payload"
    parent_payload.mkdir(parents=True)
    source = parent_payload / "f.bin"
    source.write_bytes(b"shared")
    staging_payload = _staging_payload(store)
    crash_on(monkeypatch, "link", errno_=errno.EPERM)

    store.hardlink_from_parent(parent_payload, staging_payload, "f.bin")

    target = staging_payload / "f.bin"
    assert target.read_bytes() == source.read_bytes()
    assert target.stat().st_nlink == 1
    assert stat.S_IMODE(target.stat().st_mode) == 0o600


def test_hardlink_from_parent_raises_when_linking_fails_and_the_copy_is_disabled(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """With the copy fallback disabled, a failed link raises and leaves no target."""
    store = PosixRawStore(tmp_path, hardlink_fallback_copy=False)
    store.initialize()
    parent_payload = tmp_path / "parent" / "payload"
    parent_payload.mkdir(parents=True)
    source = parent_payload / "f.bin"
    source.write_bytes(b"shared")
    staging_payload = _staging_payload(store)
    crash_on(monkeypatch, "link", errno_=errno.EPERM)

    with pytest.raises(OSError) as exc_info:
        store.hardlink_from_parent(parent_payload, staging_payload, "f.bin")

    assert exc_info.value.errno == errno.EPERM
    assert not (staging_payload / "f.bin").exists()


def test_hardlink_from_parent_links_a_sealed_parent_file_into_a_private_envelope(
    tmp_path: Path,
) -> None:
    """A hard link reaches into a sealed 0o555 parent revision without disturbing it."""
    store = _initialized_store(tmp_path)
    parent_revision = tmp_path / "parent_revision"
    parent_payload = parent_revision / "payload"
    parent_payload.mkdir(parents=True)
    source = parent_payload / "f.bin"
    source.write_bytes(b"shared")
    store.seal(parent_revision)
    staging_payload = _staging_payload(store)

    store.hardlink_from_parent(parent_payload, staging_payload, "f.bin")

    target = staging_payload / "f.bin"
    assert os.path.samefile(source, target)
    assert stat.S_IMODE(source.stat().st_mode) == 0o444
    assert stat.S_IMODE(parent_payload.stat().st_mode) == 0o555


def test_seal_makes_files_read_only_and_directories_below_the_root_traversal_only(
    tmp_path: Path,
) -> None:
    """Seal makes every file 0o444 and every directory below the root 0o555, root untouched."""
    revision = tmp_path / "revision"
    nested = revision / "payload" / "sub"
    nested.mkdir(parents=True)
    file_path = nested / "f.bin"
    file_path.write_bytes(b"data")
    root_mode_before = stat.S_IMODE(revision.stat().st_mode)
    store = PosixRawStore(tmp_path)

    store.seal(revision)

    assert stat.S_IMODE(file_path.stat().st_mode) == 0o444
    assert stat.S_IMODE(nested.stat().st_mode) == 0o555
    assert stat.S_IMODE((revision / "payload").stat().st_mode) == 0o555
    assert stat.S_IMODE(revision.stat().st_mode) == root_mode_before

    with pytest.raises(PermissionError):
        file_path.write_bytes(b"changed")

    store.seal(revision)


def test_seal_refuses_a_missing_directory(tmp_path: Path) -> None:
    """Seal refuses a path that is not a directory."""
    store = PosixRawStore(tmp_path)

    with pytest.raises(FileNotFoundError):
        store.seal(tmp_path / "missing")


def test_seal_after_hardlink_leaves_the_shared_inode_read_only_for_both_revisions(
    tmp_path: Path,
) -> None:
    """Sealing a revision built from a hard link makes both linked paths read-only."""
    store = _initialized_store(tmp_path)
    parent_revision = tmp_path / "parent_revision"
    parent_payload = parent_revision / "payload"
    parent_payload.mkdir(parents=True)
    source = parent_payload / "f.bin"
    source.write_bytes(b"shared")
    store.seal(parent_revision)
    staging = store.root / ".staging" / "envelope"
    store.create_staging(staging)
    staging_payload = staging / "payload"
    store.hardlink_from_parent(parent_payload, staging_payload, "f.bin")

    store.seal(staging)

    linked = staging_payload / "f.bin"
    assert stat.S_IMODE(source.stat().st_mode) == 0o444
    assert stat.S_IMODE(linked.stat().st_mode) == 0o444
    assert linked.stat().st_nlink == 2


def test_write_document_replaces_at_the_envelope_root_and_refuses_a_nested_or_reserved_name(
    tmp_path: Path,
) -> None:
    """A repeat write replaces the document read-only; a nested or reserved name is refused."""
    store = PosixRawStore(tmp_path)
    envelope = tmp_path / "envelope"
    envelope.mkdir()

    store.write_document(envelope, "manifest.json", b"first")
    store.write_document(envelope, "manifest.json", b"second")

    document = envelope / "manifest.json"
    assert document.read_bytes() == b"second"
    assert stat.S_IMODE(document.stat().st_mode) == 0o444

    for name in ("a/b", "..", "payload"):
        with pytest.raises(ValueError):
            store.write_document(envelope, name, b"x")


def test_read_document_returns_the_bytes_and_refuses_a_missing_file(tmp_path: Path) -> None:
    """read_document returns exactly the stored bytes and refuses a missing document."""
    store = PosixRawStore(tmp_path)
    document = tmp_path / "manifest.json"
    document.write_bytes(b"content")

    assert store.read_document(document) == b"content"

    with pytest.raises(FileNotFoundError):
        store.read_document(tmp_path / "missing.json")


def test_atomic_replace_leaves_the_old_bytes_when_the_write_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A failure during atomic_replace leaves the old bytes and no temporary file behind."""
    store = PosixRawStore(tmp_path)
    target = tmp_path / "pointer.json"
    store.atomic_replace(target, b"first")
    crash_on(monkeypatch, "fsync")

    with pytest.raises(OSError):
        store.atomic_replace(target, b"second")

    assert target.read_bytes() == b"first"
    assert list(tmp_path.glob(".pointer.json.*")) == []


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("../x", None),
        ("/abs", None),
        ("", None),
        (".", None),
        ("payload", None),
        # ``PurePosixPath`` itself collapses a mid-path ``.`` or a doubled
        # ``/`` before ``_safe_relative`` ever sees the parts, so both
        # normalize the same as the plain form.
        ("a/./b", "a/b"),
        ("a//b", "a/b"),
        ("payload/a", "a"),
        ("a/b", "a/b"),
    ],
)
def test_safe_relative_refuses_escapes_and_strips_a_leading_payload_component(
    value: str, expected: str | None
) -> None:
    """_safe_relative refuses every unsafe shape and strips a leading payload component."""
    if expected is None:
        with pytest.raises(ValueError):
            _safe_relative(value)
    else:
        assert _safe_relative(value) == Path(expected)


def test_commit_envelope_delegates_to_the_module_level_publish_primitive(tmp_path: Path) -> None:
    """PosixRawStore.commit_envelope publishes a marked envelope through the shared primitive."""
    store = _initialized_store(tmp_path)
    staging = store.root / ".staging" / "envelope"
    store.create_staging(staging)
    (staging / "COMMITTED").touch()
    final = store.root / "organization" / "final"

    store.commit_envelope(staging, final)

    assert not staging.exists()
    assert final.is_dir()
    assert stat.S_IMODE(final.stat().st_mode) == 0o555
