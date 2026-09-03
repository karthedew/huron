"""Manifest validation and RFC 8785 content identity.

A manifest is the client's declaration of a raw revision: every file's
payload-relative path, size and SHA-256. This module checks that
declaration against the path rules and the configured size limits, and
defines *content identity* - the SHA-256 of a document's RFC 8785 (JCS)
canonical serialization - which is how a manifest, a generation document
or a release record gets a hash that every implementation computes the
same way, whatever key order or whitespace it was written with.
"""

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
    """One file of a revision as the manifest declares it.

    The dataclass itself accepts anything; :func:`validate_manifest` is what
    guarantees the path obeys the layout rules, the size is within limits
    and the digest is well formed.

    Attributes:
        path: The file's path within the revision, beginning with
            ``payload/``.
        size: The file's length in bytes.
        sha256: The lower-case hexadecimal SHA-256 of the file's bytes.
        media_type: The file's media type; ``application/octet-stream``
            when the client declares none.
    """

    path: str
    size: int
    sha256: str
    media_type: str = "application/octet-stream"

    def as_dict(self) -> dict[str, JsonValue]:
        """Return the entry as the JSON object the manifest document lists it as.

        Returns:
            The four fields under their manifest names, ready for canonical
            serialization.
        """
        return {
            "path": self.path,
            "size": self.size,
            "sha256": self.sha256,
            "media_type": self.media_type,
        }


@dataclass(frozen=True, slots=True)
class Manifest:
    """A validated revision manifest: its files, sorted by path, and their hash algorithm.

    Built by :func:`validate_manifest`, which sorts the entries by path so
    that two clients declaring the same files in different orders produce
    byte-identical documents and therefore the same content identity.

    Attributes:
        files: The revision's entries, in ascending path order.
        hash_algorithm: The digest the entries' hashes were computed with.
    """

    files: tuple[ManifestEntry, ...]
    hash_algorithm: str = "sha256"

    def as_dict(self) -> dict[str, JsonValue]:
        """Return the manifest as the ``urn:huron:manifest:1`` JSON document.

        Returns:
            The document with its schema identifier, hash algorithm and file
            list, ready for canonical serialization.
        """
        return {
            "schema": "urn:huron:manifest:1",
            "hash_algorithm": self.hash_algorithm,
            "files": [entry.as_dict() for entry in self.files],
        }

    @property
    def sha256(self) -> str:
        """Return the manifest's content identity.

        Returns:
            The SHA-256 of the manifest document's RFC 8785 canonical bytes,
            as lower-case hexadecimal; this is the ``manifest_sha256`` an
            ingest session and a revision record carry.
        """
        return content_identity(self.as_dict())

    @property
    def total_bytes(self) -> int:
        """Return the revision's payload size.

        Returns:
            The sum of every entry's declared size, in bytes.
        """
        return sum(entry.size for entry in self.files)


def _assert_ints_safe(value: object, path: str = "$") -> None:
    """Refuse any integer in the document outside the range JCS serializes exactly.

    RFC 8785 serializes numbers as IEEE 754 doubles, which are exact only up
    to 2**53 - 1 in magnitude. An integer beyond that could round to the
    same canonical bytes as a different integer, giving two documents one
    identity, or serialize differently across implementations, giving one
    document two. Booleans are skipped although they subclass ``int``;
    strings and bytes are not walked as sequences.

    Args:
        value: The document, or the node of it being walked.
        path: The JSONPath-style location of ``value`` within the document,
            used only to point at the offending integer in the error.

    Raises:
        ValueError: If an integer anywhere in the document has a magnitude
            above ``MAX_SAFE_INT``.
    """
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
    """Return the document's RFC 8785 (JCS) canonical serialization.

    Keys are sorted, whitespace is dropped and numbers are rendered exactly
    as the specification prescribes, so the bytes depend only on the
    document's content. Integers are checked first so a value the
    serializer would silently round is refused instead (``ValueError`` from
    that check); a value JSON cannot represent at all fails inside the
    serializer.

    Args:
        doc: The JSON-compatible document to serialize.

    Returns:
        The canonical UTF-8 bytes, suitable for hashing or for writing
        where a byte-for-byte reproducible file is required.
    """
    _assert_ints_safe(doc)
    return rfc8785.dumps(cast("Any", dict(doc)))


def content_identity(doc: Mapping[str, object]) -> str:
    """Return the SHA-256 of the document's canonical bytes.

    Two documents have the same identity exactly when their canonical forms
    match, so key order and formatting never change an identity and any
    change of content does.

    Args:
        doc: The JSON-compatible document to identify.

    Returns:
        The digest as 64 lower-case hexadecimal characters.
    """
    return hashlib.sha256(canonical_bytes(doc)).hexdigest()


def validate_manifest_path(path: str) -> None:
    """Refuse a manifest path that breaks any storage-layout rule.

    Each rule reports its own code so a client can tell which one it
    broke, all as :class:`PathRuleViolation` with the path in context:

    - ``PATH_OUTSIDE_PAYLOAD``: the path does not begin with ``payload/``,
      the one directory of a revision envelope that holds client files.
    - ``PATH_NOT_NFC``: the path is not in Unicode NFC, so the same name
      could be stored under two byte sequences.
    - ``PATH_TOO_LONG``: the path exceeds 1024 UTF-8 bytes.
    - ``PATH_TRAVERSAL``: a segment is empty, ``.`` or ``..``, which would
      escape or alias the payload directory.
    - ``PATH_CONTROL_CHARS``: the path contains a C0 control character or
      DEL.
    - ``PATH_SEPARATOR``: the path contains a backslash; only ``/``
      separates segments.

    Args:
        path: The entry's path as the manifest declares it.

    Raises:
        PathRuleViolation: If the path breaks one of the rules above; the
            first rule broken, in the order listed, is the one reported.
    """
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
    """Check a declared file list against every manifest rule and build the manifest.

    The count and emptiness checks come first, so an oversized manifest is
    refused before any per-entry work. Each entry's path is then validated,
    its size and digest checked, and its path tested for collision against
    every earlier entry with case folded and Unicode normalized: two paths
    that differ only in case or normalization would be one file on a
    case-insensitive or normalizing filesystem, so they are refused even
    where the store itself would keep them apart. The running byte total is
    checked as it grows, so the revision limit is reported at the entry
    that crosses it. The defaults are 10 GiB per file, 10,000 files and
    1 TiB per revision.

    Args:
        entries: The files the client declares, in any order.
        max_file_bytes: The largest size any single entry may declare.
        max_files: The most entries a revision may hold.
        max_revision_bytes: The largest total size the entries may add up
            to.

    Returns:
        The manifest with its entries sorted by path, so its content
        identity does not depend on the order the client listed them.

    Raises:
        EmptyRevision: If ``entries`` is empty.
        TooManyFiles: If there are more than ``max_files`` entries.
        ValueError: If an entry declares a negative size or a digest that
            is not 64 lower-case hexadecimal characters.
        FileTooLarge: If an entry's size exceeds ``max_file_bytes``.
        PathCollision: If two entries' paths coincide once case is folded
            and Unicode normalized.
        RevisionTooLarge: If the sizes add up to more than
            ``max_revision_bytes``.
    """
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
    """Return whether ``value`` is a SHA-256 digest in the one form the manifest accepts.

    Upper-case hexadecimal is refused as well as malformed text: digests are
    compared as strings when an upload plan looks for unchanged files, so
    one spelling has to be canonical.

    Args:
        value: The declared digest.

    Returns:
        True if ``value`` is exactly 64 lower-case hexadecimal characters.
    """
    return len(value) == 64 and all(character in "0123456789abcdef" for character in value)
