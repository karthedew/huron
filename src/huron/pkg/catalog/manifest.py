"""Manifest validation and RFC 8785 content identity."""

from __future__ import annotations

import hashlib
import unicodedata
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, cast

import rfc8785

from .errors import (
    EmptyRevision,
    FileTooLarge,
    PathCollision,
    PathRuleViolation,
    RevisionTooLarge,
    TooManyFiles,
)

MAX_SAFE_INT = 2**53 - 1
DEFAULT_MAX_FILE_BYTES = 10 * 1024**3
DEFAULT_MAX_FILES = 10_000
DEFAULT_MAX_REVISION_BYTES = 1024**4

type JsonScalar = bool | int | float | str | None
type JsonValue = JsonScalar | list[JsonValue] | dict[str, JsonValue]


@dataclass(frozen=True, slots=True)
class ManifestEntry:
    path: str
    size: int
    sha256: str
    media_type: str = "application/octet-stream"

    def as_dict(self) -> dict[str, JsonValue]:
        return {
            "path": self.path,
            "size": self.size,
            "sha256": self.sha256,
            "media_type": self.media_type,
        }


@dataclass(frozen=True, slots=True)
class Manifest:
    files: tuple[ManifestEntry, ...]
    hash_algorithm: str = "sha256"

    def as_dict(self) -> dict[str, JsonValue]:
        return {
            "schema": "urn:huron:manifest:1",
            "hash_algorithm": self.hash_algorithm,
            "files": [entry.as_dict() for entry in self.files],
        }

    @property
    def sha256(self) -> str:
        return content_identity(self.as_dict())

    @property
    def total_bytes(self) -> int:
        return sum(entry.size for entry in self.files)


def _assert_ints_safe(value: object, path: str = "$") -> None:
    if isinstance(value, bool):
        return
    if isinstance(value, int):
        if abs(value) > MAX_SAFE_INT:
            raise ValueError(f"integer outside the JCS safe range at {path}: {value}")
        return
    if isinstance(value, Mapping):
        for key, child in value.items():
            _assert_ints_safe(child, f"{path}.{key}")
        return
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        for index, child in enumerate(value):
            _assert_ints_safe(child, f"{path}[{index}]")


def canonical_bytes(doc: Mapping[str, object]) -> bytes:
    _assert_ints_safe(doc)
    return rfc8785.dumps(cast("Any", dict(doc)))


def content_identity(doc: Mapping[str, object]) -> str:
    return hashlib.sha256(canonical_bytes(doc)).hexdigest()


def validate_manifest_path(path: str) -> None:
    if not path.startswith("payload/"):
        raise PathRuleViolation("PATH_OUTSIDE_PAYLOAD", path)
    if unicodedata.normalize("NFC", path) != path:
        raise PathRuleViolation("PATH_NOT_NFC", path)
    if len(path.encode("utf-8")) > 1024:
        raise PathRuleViolation("PATH_TOO_LONG", path)
    parts = path.split("/")
    if any(part in ("", ".", "..") for part in parts):
        raise PathRuleViolation("PATH_TRAVERSAL", path)
    if any(ord(character) < 0x20 or ord(character) == 0x7F for character in path):
        raise PathRuleViolation("PATH_CONTROL_CHARS", path)
    if "\\" in path:
        raise PathRuleViolation("PATH_SEPARATOR", path)


def validate_manifest(
    entries: Sequence[ManifestEntry],
    *,
    max_file_bytes: int = DEFAULT_MAX_FILE_BYTES,
    max_files: int = DEFAULT_MAX_FILES,
    max_revision_bytes: int = DEFAULT_MAX_REVISION_BYTES,
) -> Manifest:
    if not entries:
        raise EmptyRevision()
    if len(entries) > max_files:
        raise TooManyFiles(f"manifest has {len(entries)} files; limit is {max_files}")

    seen: dict[str, str] = {}
    total = 0
    validated: list[ManifestEntry] = []
    for entry in entries:
        validate_manifest_path(entry.path)
        if entry.size < 0:
            raise ValueError(f"negative file size: {entry.path!r}")
        if entry.size > max_file_bytes:
            raise FileTooLarge(f"{entry.path!r} is {entry.size} bytes; limit is {max_file_bytes}")
        if not _is_sha256(entry.sha256):
            raise ValueError(f"invalid SHA-256 for {entry.path!r}")
        collision_key = unicodedata.normalize("NFC", entry.path).casefold()
        if collision_key in seen:
            raise PathCollision(
                f"{entry.path!r} collides with {seen[collision_key]!r}",
                context={"paths": [seen[collision_key], entry.path]},
            )
        seen[collision_key] = entry.path
        total += entry.size
        if total > max_revision_bytes:
            raise RevisionTooLarge(
                f"manifest is {total} bytes; revision limit is {max_revision_bytes}"
            )
        validated.append(entry)

    return Manifest(tuple(sorted(validated, key=lambda item: item.path)))


def _is_sha256(value: str) -> bool:
    return len(value) == 64 and all(character in "0123456789abcdef" for character in value)
