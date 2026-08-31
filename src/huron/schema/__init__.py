"""Versioned JSON Schema documents and validators shared by every surface."""

from __future__ import annotations

import json
from functools import cache
from importlib.resources import files
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker


@cache
def load_schema(name: str) -> dict[str, Any]:
    if "/" in name or "\\" in name or not name.endswith(".json"):
        raise ValueError(f"invalid schema name: {name!r}")
    resource = files(__package__).joinpath("documents", name)
    document = json.loads(resource.read_text(encoding="utf-8"))
    if not isinstance(document, dict):
        raise ValueError(f"schema {name!r} is not an object")
    return document


@cache
def validator(name: str) -> Draft202012Validator:
    schema = load_schema(name)
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema, format_checker=FormatChecker())


def validate(name: str, document: object) -> None:
    validator(name).validate(document)


__all__ = ["load_schema", "validate", "validator"]
