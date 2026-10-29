"""Identifiers typed on the command line, relative to the current catalog."""

from __future__ import annotations

from huron.applications.cli.errors import UsageError
from huron.schema.naming import Identifier, NamingError, collection_identifier, namespace_identifier

__all__ = ["qualify", "resolve_collection", "resolve_namespace"]


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
            hint="use catalog.namespace.name, or set a catalog with: huron catalog use <name>",
        ) from error


def resolve_namespace(text: str, catalog: str | None) -> Identifier:
    """A namespace identifier (``catalog.ns…``) from what the user typed."""
    try:
        return namespace_identifier(qualify(text, catalog))
    except NamingError as error:
        raise UsageError(
            f"{text!r} is not a namespace identifier ({error.rule})",
            hint="use catalog.namespace, or set a catalog with: huron catalog use <name>",
        ) from error
