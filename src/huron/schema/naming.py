"""Naming rules for segments, identifiers and file paths inside a collection."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

from huron.pkg.errors import HuronError, Invalid, register

__all__ = [
    "IDENTIFIER_MAX_BYTES",
    "METADATA_FILE",
    "PART_SUFFIX",
    "REL_PATH_MAX_BYTES",
    "REL_PATH_SEGMENT_MAX_BYTES",
    "RESERVED_SEGMENTS",
    "SEGMENT_MAX_BYTES",
    "Identifier",
    "NamingError",
    "RelPathError",
    "check_rel_path",
    "check_segment",
    "collection_identifier",
    "namespace_identifier",
    "parse_identifier",
    "part_name",
    "rel_path_key",
]

SEGMENT_MAX_BYTES = 63
IDENTIFIER_MAX_BYTES = 255
REL_PATH_MAX_BYTES = 1024
REL_PATH_SEGMENT_MAX_BYTES = 255
RESERVED_SEGMENTS = frozenset({"huron", "metadata"})
METADATA_FILE = "metadata.json"
PART_SUFFIX = ".huron-part"

NAME_INVALID = register("NAME_INVALID", 422, "Name invalid")

_SEGMENT = re.compile(r"[a-z0-9][a-z0-9_-]*")
_CONTROL = re.compile(r"[\x00-\x1f\x7f]")


class NamingError(HuronError):
    """A name or identifier breaks a naming rule; ``rule`` names which one."""

    error_code = NAME_INVALID

    def __init__(self, rule: str, value: str) -> None:
        super().__init__(f"{value!r} breaks the naming rule {rule}", {"rule": rule, "value": value})
        self.rule = rule
        self.value = value


class RelPathError(Invalid):
    """A file path inside a collection breaks a path rule; ``rule`` names which one."""

    def __init__(self, rule: str, value: str) -> None:
        super().__init__(f"{value!r} breaks the path rule {rule}", {"rule": rule, "value": value})
        self.rule = rule
        self.value = value


@dataclass(frozen=True, slots=True)
class Identifier:
    """A dotted identifier: the catalog, the namespace path and, for a collection, its name."""

    catalog: str
    namespace_path: tuple[str, ...] = ()
    name: str | None = None

    @property
    def segments(self) -> tuple[str, ...]:
        """Every segment in order."""
        tail = () if self.name is None else (self.name,)
        return (self.catalog, *self.namespace_path, *tail)

    @property
    def namespace(self) -> str:
        """The dotted namespace path without the catalog (empty for a catalog)."""
        return ".".join(self.namespace_path)

    @property
    def parent(self) -> Identifier | None:
        """The enclosing identifier, or ``None`` for a catalog."""
        if self.name is not None:
            return Identifier(self.catalog, self.namespace_path)
        if self.namespace_path:
            return Identifier(self.catalog, self.namespace_path[:-1])
        return None

    def __str__(self) -> str:
        return ".".join(self.segments)


def check_segment(value: str) -> str:
    """Return ``value`` when it is a valid segment; raises :class:`NamingError`."""
    if unicodedata.normalize("NFC", value) != value:
        raise NamingError("segment_nfc", value)
    if len(value.encode()) > SEGMENT_MAX_BYTES:
        raise NamingError("segment_length", value)
    if not _SEGMENT.fullmatch(value):
        raise NamingError("segment_chars", value)
    if value in RESERVED_SEGMENTS:
        raise NamingError("segment_reserved", value)
    return value


def parse_identifier(text: str) -> tuple[str, ...]:
    """Split a dotted identifier into checked segments."""
    if len(text.encode()) > IDENTIFIER_MAX_BYTES:
        raise NamingError("identifier_length", text)
    if not text:
        raise NamingError("identifier_empty", text)
    return tuple(check_segment(segment) for segment in text.split("."))


def namespace_identifier(text: str) -> Identifier:
    """Parse ``catalog.ns1.ns2``; at least the catalog and one namespace segment."""
    segments = parse_identifier(text)
    if len(segments) < 2:
        raise NamingError("identifier_depth", text)
    return Identifier(segments[0], segments[1:])


def collection_identifier(text: str) -> Identifier:
    """Parse ``catalog.ns1.name``; at least a catalog, one namespace and the name."""
    segments = parse_identifier(text)
    if len(segments) < 3:
        raise NamingError("identifier_depth", text)
    return Identifier(segments[0], segments[1:-1], segments[-1])


def check_rel_path(value: str) -> str:
    """Return ``value`` when it is a valid path in a collection; raises :class:`RelPathError`."""
    if unicodedata.normalize("NFC", value) != value:
        raise RelPathError("rel_path_nfc", value)
    if not value or len(value.encode()) > REL_PATH_MAX_BYTES:
        raise RelPathError("rel_path_length", value)
    if _CONTROL.search(value) or "\\" in value:
        raise RelPathError("rel_path_control", value)
    if value.startswith("/") or value.endswith("/"):
        raise RelPathError("rel_path_separator", value)
    for segment in value.split("/"):
        _check_path_segment(segment, value)
    if value == METADATA_FILE:
        raise RelPathError("rel_path_reserved", value)
    return value


def rel_path_key(value: str) -> str:
    """The case-folded key that decides whether two paths collide."""
    return unicodedata.normalize("NFC", value.casefold())


def part_name(rel_path: str) -> str:
    """The temporary name a file is written under before it is renamed into place."""
    return rel_path + PART_SUFFIX


def _check_path_segment(segment: str, value: str) -> None:
    if segment in {"", ".", ".."}:
        raise RelPathError("rel_path_separator", value)
    if len(segment.encode()) > REL_PATH_SEGMENT_MAX_BYTES:
        raise RelPathError("rel_path_segment", value)
    if segment.startswith(".huron") or segment.endswith(PART_SUFFIX):
        raise RelPathError("rel_path_reserved", value)
