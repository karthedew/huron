"""Read-only envelope inspection rejects incomplete or untrusted publication evidence."""

from __future__ import annotations

import hashlib
import os
from typing import TYPE_CHECKING

import pytest

from huron.pkg.rawstore import PosixRawStore

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = pytest.mark.unit


@pytest.fixture
def envelope(tmp_path: Path) -> Path:
    """Build sibling and nested payload paths with sealed files and a control document."""
    for name in ("payload/a/file", "payload/ab/deep/file", "COMMITTED"):
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"good")
        path.chmod(0o444)
    return tmp_path


def _verify(envelope: Path) -> None:
    digest = hashlib.sha256(b"good").hexdigest()
    PosixRawStore(envelope).verify_envelope(
        envelope,
        [("payload/a/file", 4, digest), ("payload/ab/deep/file", 4, digest)],
        {"COMMITTED": b"good"},
    )


def test_inspection_accepts_exact_nested_inventory_without_mutation(envelope: Path) -> None:
    """Shared directory-name prefixes remain distinct and validation leaves evidence intact."""
    before = {path: path.stat() for path in envelope.rglob("*")}
    _verify(envelope)
    assert {path: path.stat() for path in envelope.rglob("*")} == before


@pytest.mark.parametrize("name", ["COMMITTED", "payload/a/file", "payload/ab/deep/file"])
@pytest.mark.parametrize("change", ["missing", "extra"])
def test_inspection_rejects_inventory_disagreement(envelope: Path, name: str, change: str) -> None:
    """Missing evidence and undeclared siblings fail at any inventory depth."""
    path = envelope / name
    if change == "missing":
        path.unlink()
    else:
        path.with_name("extra").write_bytes(b"unexpected")
    with pytest.raises(ValueError, match="inventory disagrees"):
        _verify(envelope)


def test_inspection_rejects_foreign_directory_ownership(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An envelope directory owned by another identity is not trusted."""
    (tmp_path / "payload").mkdir()
    uid = os.geteuid()
    monkeypatch.setattr(os, "geteuid", lambda: uid + 1)
    with pytest.raises(ValueError, match="directory ownership or seal disagrees"):
        PosixRawStore(tmp_path).verify_envelope(tmp_path, [], {})


@pytest.mark.parametrize("kind", ["writable", "hardlink", "fifo", "foreign_owner"])
def test_inspection_rejects_untrusted_file_inodes(
    envelope: Path, monkeypatch: pytest.MonkeyPatch, kind: str
) -> None:
    """Matching inventory cannot authorize writable, shared, special or foreign-owned files."""
    path = envelope / "COMMITTED"
    if kind == "writable":
        path.chmod(0o644)
    elif kind == "hardlink":
        os.link(path, envelope.parent / "shared")
    elif kind == "fifo":
        path.unlink()
        os.mkfifo(path)
    else:
        uid = os.geteuid()
        monkeypatch.setattr(os, "geteuid", lambda: uid + 1)
    with pytest.raises(
        ValueError, match=r"ownership or seal disagrees|not independently owned and sealed"
    ):
        _verify(envelope)


def test_inspection_rejects_changed_document_bytes(envelope: Path) -> None:
    """A sealed document with the right length still must match the frozen digest."""
    path = envelope / "COMMITTED"
    path.chmod(0o644)
    path.write_bytes(b"evil")
    path.chmod(0o444)
    with pytest.raises(ValueError, match="content disagrees: COMMITTED"):
        _verify(envelope)


def test_published_inspection_requires_sealed_descendants_but_allows_pending_root_seal(
    envelope: Path,
) -> None:
    """The post-rename root can be resealed only after its descendants already verify."""
    store = PosixRawStore(envelope)
    files = [
        ("payload/a/file", 4, hashlib.sha256(b"good").hexdigest()),
        ("payload/ab/deep/file", 4, hashlib.sha256(b"good").hexdigest()),
    ]
    with pytest.raises(ValueError, match="seal disagrees"):
        store.verify_envelope(envelope, files, {"COMMITTED": b"good"}, sealed=True)
    store.seal(envelope)
    assert envelope.stat().st_mode & 0o200
    store.verify_envelope(envelope, files, {"COMMITTED": b"good"}, sealed=True)
    (envelope / "payload/ab").chmod(0o755)
    with pytest.raises(ValueError, match="seal disagrees: payload/ab"):
        store.verify_envelope(envelope, files, {"COMMITTED": b"good"}, sealed=True)
