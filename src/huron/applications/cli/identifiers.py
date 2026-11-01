"""Identifiers typed on the command line, relative to the current catalog."""

from __future__ import annotations

from collections.abc import Callable

from huron.applications.cli.errors import UsageError
from huron.schema.naming import (
    Identifier,
    NamingError,
    collection_identifier,
    namespace_identifier,
    parse_identifier,
)

__all__ = [
    "collection_candidates",
    "namespace_candidates",
    "parent_candidates",
    "qualify",
    "resolve_collection",
    "resolve_namespace",
]


def qualify(text: str, catalog: str | None) -> str:
    """Prefix ``text`` with the current catalog unless it already starts with it."""
    if catalog is None or text == catalog or text.startswith(f"{catalog}."):
        return text
    return f"{catalog}.{text}"


def resolve_collection(text: str, catalog: str | None) -> Identifier:
    """A collection identifier (``catalog.ns….name``) from what the user typed."""
    try:
        return collection_identifier(qualify(text, catalog))
    except NamingError as error:
        raise UsageError(
            f"{text!r} is not a collection identifier ({error.rule})",
            hint="use catalog.namespace.name, or set a catalog with: huron catalog <name>",
        ) from error


def resolve_namespace(text: str, catalog: str | None) -> Identifier:
    """A namespace identifier (``catalog.ns…``) from what the user typed."""
    try:
        return namespace_identifier(qualify(text, catalog))
    except NamingError as error:
        raise UsageError(
            f"{text!r} is not a namespace identifier ({error.rule})",
            hint="use catalog.namespace, or set a catalog with: huron catalog <name>",
        ) from error


def collection_candidates(text: str, catalog: str | None) -> tuple[Identifier, ...]:
    """The collections ``text`` may name: relative to the current catalog first, then as written.

    A full identifier copied from another catalog (``huron --catalog other tree``) is found too,
    while a relative one still wins when both exist.
    """
    return _candidates(resolve_collection(text, catalog), text, collection_identifier)


def namespace_candidates(text: str, catalog: str | None) -> tuple[Identifier, ...]:
    """The namespaces ``text`` may name: relative to the current catalog first, then as written."""
    return _candidates(resolve_namespace(text, catalog), text, namespace_identifier)


def parent_candidates(text: str, catalog: str | None) -> tuple[Identifier, ...]:
    """The catalog or namespace ``text`` may name, as :func:`namespace_candidates` orders them.

    A catalog is an identifier with an empty namespace path.
    """
    try:
        first = _catalog_or_namespace(qualify(text, catalog))
    except NamingError as error:
        raise UsageError(
            f"{text!r} is not a catalog or namespace identifier ({error.rule})",
            hint="use catalog or catalog.namespace",
        ) from error
    return _candidates(first, text, _catalog_or_namespace)


def _catalog_or_namespace(text: str) -> Identifier:
    segments = parse_identifier(text)
    return Identifier(segments[0], segments[1:])


def _candidates(
    first: Identifier, text: str, parse: Callable[[str], Identifier]
) -> tuple[Identifier, ...]:
    try:
        written = parse(text)
    except NamingError:
        return (first,)
    return (first,) if written == first else (first, written)
