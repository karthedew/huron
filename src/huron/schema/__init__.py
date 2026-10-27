"""Versioned JSON Schema documents and validators shared by every surface.

The ``schema`` tier is the one thing every service and package may import,
so it holds only contracts: the Draft 2020-12 documents packaged under
``documents/``, the three functions that load and apply them, and pure rule modules shared by
the server and CLI, including ``naming``, ``catalog_config`` and ``metadata``. A document
is addressed by its file name, and the name carries the version
(``generation-v1.json``), so a reader always knows which contract a document
follows; a breaking change replaces the file and every caller in one change.

``format: date-time`` is not a no-op here: ``rfc3339-validator``, pulled in
by the ``jsonschema[format-nongpl]`` extra, backs the ``FormatChecker``
below, so an instant that is not RFC 3339 (a naive spelling, "yesterday")
fails validation instead of passing through unchecked.
"""

from __future__ import annotations

import json
from functools import cache
from importlib.resources import files
from typing import TYPE_CHECKING, Any

from huron.schema._validator import build

if TYPE_CHECKING:
    from jsonschema.protocols import Validator


@cache
def load_schema(name: str) -> dict[str, Any]:
    """Load one packaged schema document by file name.

    The name is a bare file name such as ``generation-v1.json``: path
    separators are refused so a caller can never reach outside the
    ``documents`` directory, and the ``.json`` suffix is required so the
    name says which version it asks for. A name that matches no packaged
    document fails when the resource is read. The parsed document is cached
    for the life of the process and shared between callers, so it must be
    treated as read-only.

    Args:
        name: The document's file name within ``documents/``, including its
            ``.json`` suffix.

    Returns:
        The parsed schema, as the JSON object at the top of the file.

    Raises:
        ValueError: If ``name`` contains a path separator or lacks the
            ``.json`` suffix, or if the document's top level is not a JSON
            object.
    """
    if "/" in name or "\\" in name or not name.endswith(".json"):
        raise ValueError(f"invalid schema name: {name!r}")
    resource = files(__package__).joinpath("documents", name)
    document = json.loads(resource.read_text(encoding="utf-8"))
    if not isinstance(document, dict):
        raise ValueError(f"schema {name!r} is not an object")
    return document


@cache
def validator(name: str) -> Validator:
    """Return the cached Draft 2020-12 validator for one packaged schema.

    The schema is checked against the Draft 2020-12 metaschema before the
    validator is built, so a malformed document fails at its first use
    instead of silently accepting everything (``jsonschema.SchemaError``
    propagates from that check). The validator carries a ``FormatChecker``,
    so ``format`` assertions are checked for every format the installed
    checker supports instead of being ignored, as the specification allows
    by default. Patterns use RE2 and references use a closed registry.
    One validator is built per name per process.

    Args:
        name: The document's file name within ``documents/``, as
            :func:`load_schema` takes it.

    Returns:
        A validator whose ``validate`` and ``iter_errors`` apply the named
        schema.
    """
    return build(load_schema(name))


def validate(name: str, document: Any) -> None:
    """Assert that ``document`` conforms to the named packaged schema.

    Returns silently on success; the first violation propagates as
    ``jsonschema.ValidationError`` from the cached validator, so the caller
    decides how to report it.

    Args:
        name: The document's file name within ``documents/``, as
            :func:`load_schema` takes it.
        document: The parsed JSON value to check.
    """
    validator(name).validate(document)


__all__ = ["load_schema", "validate", "validator"]
