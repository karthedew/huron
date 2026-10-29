"""Walk a user through a metadata document, one schema field at a time."""

from __future__ import annotations

import copy
import json
from collections.abc import Mapping
from typing import Any

from huron.applications.cli.prompts import Prompter
from huron.schema.validator import Problem, Validator

__all__ = ["fill", "merge_diff", "review"]


def fill(
    prompter: Prompter, schema: Mapping[str, Any], current: Mapping[str, Any]
) -> dict[str, Any]:
    """Ask for every required field, offer every optional one, and return the document.

    Required fields come in the schema's ``required`` order, optional ones alphabetically (the
    database does not keep property order).

    Values already in ``current`` are offered as defaults; optional fields are skipped unless the
    user chooses to set them, and fields the schema does not describe are kept untouched.
    """
    return _object(prompter, schema, dict(current), "")


def review(schema: Mapping[str, Any], document: Mapping[str, Any]) -> list[Problem]:
    """Problems of ``document`` against ``schema``."""
    return Validator(schema).validate(dict(document))


def merge_diff(before: Mapping[str, Any], after: Mapping[str, Any]) -> dict[str, Any]:
    """The RFC 7396 merge patch that turns ``before`` into ``after``."""
    patch: dict[str, Any] = {key: None for key in before if key not in after}
    for key, value in after.items():
        old = before.get(key)
        if isinstance(value, dict) and isinstance(old, dict):
            nested = merge_diff(old, value)
            if nested:
                patch[key] = nested
        elif key not in before or old != value:
            patch[key] = copy.deepcopy(value)
    return patch


def _object(
    prompter: Prompter, schema: Mapping[str, Any], current: dict[str, Any], prefix: str
) -> dict[str, Any]:
    properties: Mapping[str, Any] = schema.get("properties", {})
    required = [name for name in schema.get("required", []) if name in properties]
    optional = sorted(name for name in properties if name not in required)
    result = dict(current)
    for name in [*required, *optional]:
        prop = properties[name]
        label = f"{prefix}{prop.get('title') or name}"
        if name not in required and not prompter.confirm(f"Set {label}? (optional)", default=False):
            continue
        result[name] = _value(prompter, prop, current.get(name), label)
    return result


def _value(prompter: Prompter, prop: Mapping[str, Any], current: Any, label: str) -> Any:
    kind = prop.get("type")
    if "enum" in prop:
        choices = [str(choice) for choice in prop["enum"]]
        picked = prompter.select(label, choices, None if current is None else str(current))
        return prop["enum"][choices.index(picked)]
    if kind == "boolean":
        return prompter.confirm(label, default=bool(current))
    if kind == "object":
        if "properties" in prop:
            return _object(prompter, prop, dict(current or {}), f"{label} › ")
        return _pairs(prompter, prop, current, label)
    if kind == "array":
        return _array(prompter, prop, current, label)
    return _scalar(prompter, prop, current, label)


def _scalar(prompter: Prompter, prop: Mapping[str, Any], current: Any, label: str) -> Any:
    validator = Validator(prop)
    default = "" if current is None else str(current)
    if current is None and "default" in prop:
        default = str(prop["default"])
    hint = f" ({prop['description']})" if prop.get("description") else ""

    def check(text: str) -> str | None:
        value, problem = _convert(prop, text)
        if problem is not None:
            return problem
        problems = validator.validate(value)
        return problems[0].message if problems else None

    text = prompter.text(f"{label}{hint}", default=default, validate=check)
    return _convert(prop, text)[0]


def _array(prompter: Prompter, prop: Mapping[str, Any], current: Any, label: str) -> list[Any]:
    items: Mapping[str, Any] = prop.get("items", {"type": "string"})
    existing = list(current or [])
    if items.get("type") == "object":
        kept = (
            existing
            if existing
            and prompter.confirm(
                f"Keep the {len(existing)} existing {label} entries?", default=True
            )
            else []
        )
        while prompter.confirm(f"Add a {label} entry?", default=not kept):
            kept.append(_object(prompter, items, {}, f"{label} › "))
        return kept
    validator = Validator(prop)

    def check(text: str) -> str | None:
        values, problem = _list(items, text)
        if problem is not None:
            return problem
        problems = validator.validate(values)
        return problems[0].message if problems else None

    default = ", ".join(str(item) for item in existing)
    text = prompter.text(f"{label} (comma-separated)", default=default, validate=check)
    return _list(items, text)[0]


def _pairs(prompter: Prompter, prop: Mapping[str, Any], current: Any, label: str) -> dict[str, Any]:
    default = ", ".join(f"{k}={v}" for k, v in (current or {}).items())

    def parse(text: str) -> tuple[dict[str, str], str | None]:
        pairs: dict[str, str] = {}
        for chunk in filter(None, (part.strip() for part in text.split(","))):
            key, sep, value = chunk.partition("=")
            if not sep or not key.strip():
                return {}, f"{chunk!r} is not key=value"
            pairs[key.strip()] = value.strip()
        return pairs, None

    def check(text: str) -> str | None:
        pairs, problem = parse(text)
        if problem is not None:
            return problem
        problems = Validator(prop).validate(pairs)
        return problems[0].message if problems else None

    text = prompter.text(f"{label} (key=value, comma-separated)", default=default, validate=check)
    return parse(text)[0]


def _list(items: Mapping[str, Any], text: str) -> tuple[list[Any], str | None]:
    values: list[Any] = []
    for chunk in filter(None, (part.strip() for part in text.split(","))):
        value, problem = _convert(items, chunk)
        if problem is not None:
            return [], problem
        values.append(value)
    return values, None


def _convert(prop: Mapping[str, Any], text: str) -> tuple[Any, str | None]:
    kind = prop.get("type")
    try:
        if kind == "integer":
            return int(text), None
        if kind == "number":
            return float(text), None
    except ValueError:
        return None, f"{text!r} is not a {kind}"
    if kind not in (None, "string"):
        try:
            return json.loads(text), None
        except ValueError:
            return None, f"{text!r} is not valid JSON"
    return text, None
