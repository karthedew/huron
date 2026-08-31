"""POSIX implementation of raw evidence-tier mechanisms."""

from __future__ import annotations

import hashlib
import os
import shutil
import tempfile
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING

from .commit import assert_same_filesystem, commit_envelope, fsync_dir

if TYPE_CHECKING:
    from uuid import UUID


class PosixRawStore:
    def __init__(self, root: str | Path, *, hardlink_fallback_copy: bool = True):
        self.root = Path(root)
        self.hardlink_fallback_copy = hardlink_fallback_copy

    @property
    def staging_root(self) -> Path:
        return self.root / ".staging"

    def initialize(self) -> None:
        self.staging_root.mkdir(parents=True, exist_ok=True)
        (self.root / "organization").mkdir(parents=True, exist_ok=True)
        assert_same_filesystem(self.staging_root, self.root / "organization")

    def create_staging(self, ingest_id: UUID) -> Path:
        self.staging_root.mkdir(parents=True, exist_ok=True)
        staging = self.staging_root / ingest_id.hex
        staging.mkdir(mode=0o700)
        (staging / "payload").mkdir(mode=0o700)
        return staging

    def hardlink_from_parent(
        self,
        parent_payload: PurePosixPath,
        staging_payload: PurePosixPath,
        rel_path: str,
    ) -> None:
        relative = _safe_relative(rel_path)
        source = Path(parent_payload) / relative
        target = Path(staging_payload) / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        try:
            os.link(source, target)
        except OSError:
            if not self.hardlink_fallback_copy:
                raise
            _copy_exclusive(source, target)

    def commit_envelope(self, staging: PurePosixPath, final: PurePosixPath) -> None:
        commit_envelope(Path(staging), Path(final))

    def seal(self, revision_dir: PurePosixPath) -> None:
        root = Path(revision_dir)
        if not root.is_dir():
            raise FileNotFoundError(root)
        for path in root.rglob("*"):
            if path.is_file():
                path.chmod(0o444)
        for path in sorted(
            (item for item in root.rglob("*") if item.is_dir()),
            key=lambda item: len(item.parts),
            reverse=True,
        ):
            path.chmod(0o555)
        root.chmod(0o555)

    def write_once(self, path: PurePosixPath | Path, payload: bytes, *, mode: int = 0o444) -> None:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        descriptor = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, mode)
        try:
            _write_all(descriptor, payload)
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        fsync_dir(target.parent)

    def write_tag_once(self, tag_file: PurePosixPath, payload: bytes) -> None:
        self.write_once(tag_file, payload, mode=0o444)

    def write_generation(self, entity_dir: PurePosixPath, generation: int, payload: bytes) -> Path:
        if not 1 <= generation <= 999_999:
            raise ValueError(f"generation out of range: {generation}")
        entity_path = Path(entity_dir)
        generation_path = entity_path / "generations" / f"{generation:06d}.json"
        self.write_once(generation_path, payload)
        pointer = (
            f'{{"generation":{generation},"path":"generations/{generation:06d}.json"}}'
        ).encode()
        self.atomic_replace(entity_path / "CURRENT.json", pointer, mode=0o444)
        return generation_path

    def atomic_replace(
        self, path: PurePosixPath | Path, payload: bytes, *, mode: int = 0o444
    ) -> None:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temp_name = tempfile.mkstemp(prefix=f".{target.name}.", dir=target.parent)
        temp_path = Path(temp_name)
        try:
            os.fchmod(descriptor, mode)
            _write_all(descriptor, payload)
            os.fsync(descriptor)
            os.close(descriptor)
            descriptor = -1
            os.replace(temp_path, target)
            fsync_dir(target.parent)
        finally:
            if descriptor >= 0:
                os.close(descriptor)
            temp_path.unlink(missing_ok=True)

    def write_part(
        self, staging: PurePosixPath, rel_path: str, chunks: list[bytes]
    ) -> tuple[int, str]:
        """Write one upload atomically while hashing the exact bytes in flight."""
        target = Path(staging) / _safe_relative(rel_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        descriptor = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        digest = hashlib.sha256()
        size = 0
        try:
            for chunk in chunks:
                _write_all(descriptor, chunk)
                digest.update(chunk)
                size += len(chunk)
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        return size, digest.hexdigest()


def _safe_relative(value: str) -> Path:
    path = PurePosixPath(value)
    if path.is_absolute() or not path.parts or any(part in ("", ".", "..") for part in path.parts):
        raise ValueError(f"unsafe relative path: {value!r}")
    parts = path.parts[1:] if path.parts[0] == "payload" else path.parts
    if not parts:
        raise ValueError("a payload file path is required")
    return Path(*parts)


def _copy_exclusive(source: Path, target: Path) -> None:
    descriptor = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with (
            source.open("rb") as source_file,
            os.fdopen(descriptor, "wb", closefd=False) as target_file,
        ):
            shutil.copyfileobj(source_file, target_file)
            target_file.flush()
            os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _write_all(descriptor: int, payload: bytes) -> None:
    remaining = memoryview(payload)
    while remaining:
        written = os.write(descriptor, remaining)
        remaining = remaining[written:]
