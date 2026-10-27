"""Strict catalog names, namespace paths and lexical identifier conversions."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Final

SEGMENT_PATTERN: Final = "[a-z0-9][a-z0-9_-]{0,63}"
IDENTIFIER_MAX_BYTES: Final = 1023


class NamingError(ValueError):
    """A naming refusal preserving the rule and the caller's offending value."""

    def __init__(self, rule: str, value: str, detail: str) -> None:
        """Describe a refused name without rewriting it.

        Args:
            rule: The violated naming rule.
            value: The offending input verbatim.
            detail: Human-readable explanation.
        """
        self.rule = rule
        self.value = value
        super().__init__(f"{detail}: {value!r}")


def check_segment(value: str) -> str:
    """Validate one catalog, namespace or collection name unchanged.

    Args:
        value: The explicit name.

    Returns:
        The supplied name unchanged.

    Raises:
        NamingError: If the name violates the strict ASCII segment rule.
    """
    if re.fullmatch(SEGMENT_PATTERN, value) is None:
        raise NamingError("segment", value, "expected a lowercase ASCII name of 1-64 characters")
    return value


def is_reserved(name: str) -> bool:
    """Identify server-reserved file names.

    Args:
        name: One file name.

    Returns:
        Whether the name begins with a dot or ends with the partial suffix.
    """
    return name.startswith(".") or name.endswith(".part")


def _check_length(value: str) -> None:
    if len(value.encode("utf-8", errors="surrogatepass")) > IDENTIFIER_MAX_BYTES:
        raise NamingError("path_length", value, f"path exceeds {IDENTIFIER_MAX_BYTES} UTF-8 bytes")


def _segments(text: str, separator: str) -> tuple[str, ...]:
    parts = tuple(text.split(separator))
    if "" in parts:
        raise NamingError("empty_segment", text, "empty path segment")
    return parts


def check_namespace(path: tuple[str, ...]) -> tuple[str, ...]:
    """Validate a nonempty recursive namespace path without limiting its depth.

    Args:
        path: Explicit namespace segments within a catalog.

    Returns:
        The immutable validated path.

    Raises:
        NamingError: If the namespace is empty or contains an unsafe or overlong name.
    """
    path = tuple(path)
    if not path:
        raise NamingError("empty_segment", "", "a namespace requires at least one segment")
    _check_length("/".join(path))
    for segment in path:
        check_segment(segment)
    return path


def _check_prefix(prefix: PurePosixPath) -> str:
    if prefix.anchor != "/" or ".." in prefix.parts or "\x00" in str(prefix):
        raise NamingError(
            "outside_prefix", str(prefix), "mount prefix must be an absolute safe path"
        )
    return str(prefix).rstrip("/")


def _mount_relative(text: str, mount_prefix: PurePosixPath) -> str | None:
    prefix = _check_prefix(mount_prefix)
    if text.removesuffix("/") == prefix:
        raise NamingError("outside_prefix", text, "mount path must be below its prefix")
    if text.startswith(prefix + "/"):
        return text[len(prefix) + 1 :]
    return None


@dataclass(frozen=True, slots=True, order=True)
class Identifier:
    """An immutable catalog and optional descendant namespace or collection path."""

    catalog: str
    path: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        """Validate and freeze every supplied segment."""
        object.__setattr__(self, "path", tuple(self.path))
        _check_length(self.fully_qualified())
        check_segment(self.catalog)
        for segment in self.path:
            check_segment(segment)

    @classmethod
    def parse(
        cls, text: str, *, catalog: str | None = None, mount_prefix: PurePosixPath | None = None
    ) -> Identifier:
        """Parse mount, catalog-rooted, fully qualified or canonical form in that order.

        Args:
            text: The identifier, with at most one optional trailing slash.
            catalog: Current catalog for a catalog-rooted input.
            mount_prefix: Absolute lexical mount prefix, if configured.

        Returns:
            The validated identifier.

        Raises:
            NamingError: If the spelling is unsafe, overlong or lacks required catalog context.
        """
        if text.startswith("/") and mount_prefix is not None:
            relative = _mount_relative(text, mount_prefix)
            if relative is not None:
                return cls._from_slashes(relative)
        if text.startswith("/"):
            if catalog is None:
                raise NamingError("no_catalog", text, "catalog-rooted input requires a catalog")
            if text == "/":
                return cls(catalog)
            return cls._from_slashes(catalog + text)
        if "/" in text:
            return cls._from_slashes(text)
        return cls.from_canonical(text)

    @classmethod
    def _from_slashes(cls, text: str) -> Identifier:
        parts = _segments(text.removesuffix("/"), "/")
        return cls(parts[0], parts[1:])

    @classmethod
    def from_canonical(cls, text: str) -> Identifier:
        """Parse only the canonical dotted form accepted by the server.

        Args:
            text: A dotted catalog and descendant path.

        Returns:
            The validated identifier.
        """
        _check_length(text)
        parts = _segments(text, ".")
        return cls(parts[0], parts[1:])

    def canonical(self) -> str:
        """Return the dotted identifier.

        Returns:
            The catalog and path joined by dots.
        """
        return ".".join((self.catalog, *self.path))

    def fully_qualified(self) -> str:
        """Return the slash-separated identifier including its catalog.

        Returns:
            The relative catalog and descendant path.
        """
        return "/".join((self.catalog, *self.path))

    def catalog_rooted(self) -> str:
        """Return the slash-separated path within the catalog.

        Returns:
            A leading slash followed by descendants, or just a slash for the catalog.
        """
        return "/" + "/".join(self.path)

    def mount_path(self, prefix: PurePosixPath) -> PurePosixPath:
        """Place the identifier below an absolute lexical mount prefix.

        Args:
            prefix: The configured absolute mount path.

        Returns:
            The absolute mount path without filesystem access.
        """
        base = _check_prefix(prefix)
        text = base + "/" + self.fully_qualified()
        return PurePosixPath(text)
