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

from huron.core.rawstore import PartLengthMismatchError, PosixRawStore
from huron.core.rawstore.commit import CrossDeviceCommitError
from huron.core.rawstore.store import _safe_relative
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


def _staging_session(store: PosixRawStore, name: str = "envelope") -> Path:
    """Claim a fresh staging envelope on ``store`` and return its ``payload`` directory.

    Args:
        store: The store to claim the envelope on.
        name: The envelope's name under ``.staging``.

    Returns:
        The new envelope's empty ``payload`` directory.
    """
    staging = store.root / ".staging" / name
    store.create_staging(staging)
    return staging


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
    assert stat.S_IMODE((staging / "envelope" / "payload").stat().st_mode) == 0o700
    assert set(log) == {
        store.root / ".staging",
        staging,
        staging / "upload",
        staging / "completion",
        staging / "envelope",
        staging / "envelope" / "payload",
    }

    with pytest.raises(FileExistsError):
        store.create_staging(staging)

    with pytest.raises(ValueError):
        store.create_staging(store.root / "elsewhere" / "xyz789")


def test_write_part_pulls_one_chunk_at_a_time_and_reports_the_digest_of_the_bytes_written(
    tmp_path: Path,
) -> None:
    """write_part reads chunks lazily and returns the SHA-256 of the bytes it wrote."""
    store = _initialized_store(tmp_path)
    payload_root = _staging_session(store)
    chunks = [b"abc", b"defgh", b"ij"]
    whole = b"".join(chunks)
    target = payload_root / "upload" / "a.bin"

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
    payload_root = _staging_session(store)
    part_size = 4
    parts = [b"aaaa", b"bbbb", b"cccc"]

    for index in (2, 0, 1):
        store.write_part(
            payload_root, "f.bin", [parts[index]], offset=index * part_size, length=part_size
        )

    assert (payload_root / "upload" / "f.bin").read_bytes() == b"".join(parts)


def test_write_part_overwrites_a_resent_part_s_range_only(tmp_path: Path) -> None:
    """Resending a part after a partial write overwrites only that part's range."""
    store = _initialized_store(tmp_path)
    payload_root = _staging_session(store)
    part_size = 4
    store.write_part(payload_root, "f.bin", [b"1111"], offset=0, length=part_size)
    store.write_part(payload_root, "f.bin", [b"3333"], offset=2 * part_size, length=part_size)

    def _dropped() -> Iterator[bytes]:
        yield b"xx"
        raise ConnectionResetError("dropped mid-part")

    with pytest.raises(ConnectionResetError):
        store.write_part(payload_root, "f.bin", _dropped(), offset=part_size, length=part_size)

    store.write_part(payload_root, "f.bin", [b"2222"], offset=part_size, length=part_size)

    assert (payload_root / "upload" / "f.bin").read_bytes() == b"111122223333"


def test_write_part_refuses_a_short_or_long_stream(tmp_path: Path) -> None:
    """A stream that ends short or runs long raises PartLengthMismatchError, no digest returned."""
    store = _initialized_store(tmp_path)
    payload_root = _staging_session(store)

    with pytest.raises(PartLengthMismatchError):
        store.write_part(payload_root, "short.bin", [b"ab"], offset=0, length=3)

    with pytest.raises(PartLengthMismatchError):
        store.write_part(payload_root, "long.bin", [b"abcd"], offset=0, length=3)


def test_short_positional_writes_preserve_the_complete_range(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Short filesystem writes complete the requested range without touching adjacent bytes."""
    store = _initialized_store(tmp_path)
    root = _staging_session(store)
    store.write_part(root, "file", [b"prefix------suffix"], offset=0, length=18)
    original = os.pwrite

    def short_write(descriptor: int, data: bytes, offset: int) -> int:
        return original(descriptor, data[:2], offset)

    monkeypatch.setattr(os, "pwrite", short_write)
    assert store.write_part(root, "file", [b"middle"], offset=6, length=6) == (
        hashlib.sha256(b"middle").hexdigest()
    )
    assert (root / "upload/file").read_bytes() == b"prefixmiddlesuffix"


def test_stalled_positional_write_refuses_success_and_can_retry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Zero progress raises EIO promptly, preserving bytes for a successful part retry."""
    store = _initialized_store(tmp_path)
    root = _staging_session(store)
    store.write_part(root, "file", [b"before"], offset=0, length=6)
    with monkeypatch.context() as patch:
        patch.setattr(os, "pwrite", lambda *_args: 0)
        with pytest.raises(OSError) as raised:
            store.write_part(root, "file", [b"after!"], offset=0, length=6)
    assert raised.value.errno == errno.EIO
    assert (root / "upload/file").read_bytes() == b"before"
    store.write_part(root, "file", [b"after!"], offset=0, length=6)
    assert (root / "upload/file").read_bytes() == b"after!"


def test_write_part_propagates_a_mid_stream_exception_and_leaves_the_range_for_the_resend(
    tmp_path: Path,
) -> None:
    """A client disconnect mid-stream propagates, and a resend of the same part succeeds."""
    store = _initialized_store(tmp_path)
    payload_root = _staging_session(store)
    target = payload_root / "upload" / "f.bin"

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
    payload_root = _staging_session(store)
    log = fsync_log(monkeypatch)

    store.write_part(payload_root, "d1/d2/f.bin", [b"data"], offset=0, length=4)

    target = payload_root / "upload" / "d1" / "d2" / "f.bin"
    assert {target, target.parent, target.parent.parent, payload_root / "upload"} <= set(log)
    assert stat.S_IMODE(target.parent.stat().st_mode) == 0o700
    assert stat.S_IMODE(target.parent.parent.stat().st_mode) == 0o700


def test_write_part_refuses_an_unsafe_path_before_touching_the_disk(tmp_path: Path) -> None:
    """An unsafe rel_path raises ValueError before any file or directory is created."""
    store = _initialized_store(tmp_path)
    payload_root = _staging_session(store)

    with pytest.raises(ValueError, match="unsafe relative path"):
        store.write_part(payload_root, "../escape.bin", [b"x"], offset=0, length=1)

    assert list((payload_root / "upload").iterdir()) == []


def test_a_single_part_write_is_the_whole_file_observation(tmp_path: Path) -> None:
    """A single-part write's returned digest matches finish_file's whole-file observation."""
    store = _initialized_store(tmp_path)
    payload_root = _staging_session(store)
    content = b"the whole file, in one part"

    digest = store.write_part(payload_root, "f.bin", [content], offset=0, length=len(content))
    size, finished_digest = store.finish_file(
        payload_root,
        "f.bin",
        "payload/f.bin",
        expected_size=len(content),
        expected_sha256=hashlib.sha256(content).hexdigest(),
    )

    assert (size, digest) == (len(content), finished_digest)


def test_finish_file_reports_size_and_digest_and_refuses_a_missing_file(tmp_path: Path) -> None:
    """finish_file reports the file's real size and digest, and refuses a missing file."""
    store = _initialized_store(tmp_path)
    payload_root = _staging_session(store)
    content = b"x" * 5000
    store.write_part(payload_root, "f.bin", [content], offset=0, length=len(content))

    size, digest = store.finish_file(
        payload_root,
        "f.bin",
        "payload/f.bin",
        expected_size=len(content),
        expected_sha256=hashlib.sha256(content).hexdigest(),
    )

    assert size == len(content)
    assert digest == hashlib.sha256(content).hexdigest()

    with pytest.raises(FileNotFoundError):
        store.finish_file(
            payload_root,
            "missing.bin",
            "payload/missing.bin",
            expected_size=0,
            expected_sha256=hashlib.sha256(b"").hexdigest(),
        )


def test_discard_file_removes_the_file_and_tolerates_a_missing_one(tmp_path: Path) -> None:
    """discard_file removes an existing file and is a no-op for one already gone."""
    store = _initialized_store(tmp_path)
    payload_root = _staging_session(store)
    store.write_part(payload_root, "f.bin", [b"data"], offset=0, length=4)

    store.discard_file(payload_root, "f.bin")

    assert not (payload_root / "upload" / "f.bin").exists()

    store.discard_file(payload_root, "f.bin")


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


def test_write_document_is_immutable_and_refuses_a_nested_or_reserved_name(
    tmp_path: Path,
) -> None:
    """Identical document retries succeed and conflicting bytes or unsafe names are refused."""
    store = _initialized_store(tmp_path)
    envelope = _staging_session(store) / "envelope"

    store.write_document(envelope, "manifest.json", b"first")
    store.write_document(envelope, "manifest.json", b"first")
    with pytest.raises(ValueError, match="conflicts"):
        store.write_document(envelope, "manifest.json", b"second")

    document = envelope / "manifest.json"
    assert document.read_bytes() == b"first"
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


def test_document_writes_complete_short_writes_and_refuse_zero_progress(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Pointer replacement writes all bytes and retains its old value if writing stalls."""
    store = PosixRawStore(tmp_path)
    target = tmp_path / "pointer.json"
    original = os.write
    with monkeypatch.context() as patch:
        patch.setattr(os, "write", lambda descriptor, data: original(descriptor, data[:2]))
        store.atomic_replace(target, b"original")
    assert target.read_bytes() == b"original"
    with monkeypatch.context() as patch:
        patch.setattr(os, "write", lambda *_args: 0)
        with pytest.raises(OSError) as raised:
            store.atomic_replace(target, b"replacement")
    assert raised.value.errno == errno.EIO
    assert target.read_bytes() == b"original"
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
