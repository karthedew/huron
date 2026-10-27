"""Bounded RE2 matching and offline references for shared JSON Schema validation."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Final

import re2
from attrs import fields
from jsonschema import Draft202012Validator, FormatChecker, ValidationError, validators
from jsonschema._utils import extras_msg
from referencing import Registry

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator, Mapping

    from jsonschema.protocols import Validator

MAX_REGEX_LENGTH: Final = 1024


def compile_regex(pattern: str) -> None:
    """Check that a bounded pattern compiles under RE2 without diagnostic output.

    Refused expressions raise ``ValueError``.

    Args:
        pattern: The regular expression to check.
    """
    _compiled(pattern)


def _compiled(pattern: str) -> Any:
    if len(pattern) > MAX_REGEX_LENGTH:
        raise ValueError(f"regular expression exceeds {MAX_REGEX_LENGTH} characters")
    options = re2.Options()
    options.log_errors = False
    try:
        return re2.compile(pattern, options=options)
    except re2.error as error:
        raise ValueError(str(error)) from error


def _pattern(
    validator: Any, pattern: str, instance: Any, schema: Mapping[str, Any]
) -> Iterator[ValidationError]:
    if validator.is_type(instance, "string") and not _compiled(pattern).search(instance):
        yield ValidationError(f"{instance!r} does not match {pattern!r}")


def _pattern_properties(
    validator: Any, patterns: Mapping[str, Any], instance: Any, schema: Mapping[str, Any]
) -> Iterator[ValidationError]:
    if not validator.is_type(instance, "object"):
        return
    for pattern, subschema in patterns.items():
        compiled = _compiled(pattern)
        for key, value in instance.items():
            if compiled.search(key):
                yield from validator.descend(value, subschema, path=key, schema_path=pattern)


def _matching_keys(instance: Mapping[str, Any], schema: Mapping[str, Any]) -> set[str]:
    patterns = [_compiled(pattern) for pattern in schema.get("patternProperties", {})]
    return {key for key in instance if any(pattern.search(key) for pattern in patterns)}


def _additional_properties(
    validator: Any, additional: Any, instance: Any, schema: Mapping[str, Any]
) -> Iterator[ValidationError]:
    if not validator.is_type(instance, "object"):
        return
    extras = (
        instance.keys() - schema.get("properties", {}).keys() - _matching_keys(instance, schema)
    )
    if validator.is_type(additional, "object"):
        for key in extras:
            yield from validator.descend(instance[key], additional, path=key)
        return
    if additional or not extras:
        return
    if "patternProperties" in schema:
        verb = "does" if len(extras) == 1 else "do"
        names = ", ".join(repr(key) for key in sorted(extras))
        patterns = ", ".join(repr(pattern) for pattern in sorted(schema["patternProperties"]))
        yield ValidationError(f"{names} {verb} not match any of the regexes: {patterns}")
    else:
        names, verb = extras_msg(sorted(extras, key=str))
        yield ValidationError(f"Additional properties are not allowed ({names} {verb} unexpected)")


def _evaluated_keys(validator: Any, instance: Mapping[str, Any], schema: Any) -> set[str]:
    if isinstance(schema, bool):
        return set()
    evaluated: set[str] = instance.keys() & schema.get("properties", {}).keys()
    evaluated |= _matching_keys(instance, schema)
    for keyword in ("$ref", "$dynamicRef"):
        if keyword in schema:
            resolved = validator._resolver.lookup(schema[keyword])
            child = validator.evolve(schema=resolved.contents, _resolver=resolved.resolver)
            evaluated |= _evaluated_keys(child, instance, resolved.contents)
    for keyword in ("additionalProperties", "unevaluatedProperties"):
        if keyword in schema:
            evaluated.update(
                key
                for key, value in instance.items()
                if next(validator.descend(value, schema[keyword]), None) is None
            )
    for subschema in _evaluated_subschemas(validator, instance, schema):
        evaluated |= _evaluated_keys(validator, instance, subschema)
    return evaluated


def _evaluated_subschemas(
    validator: Any, instance: Mapping[str, Any], schema: Mapping[str, Any]
) -> Iterator[Any]:
    yield from (
        subschema
        for key, subschema in schema.get("dependentSchemas", {}).items()
        if key in instance
    )
    for keyword in ("allOf", "oneOf", "anyOf"):
        for subschema in schema.get(keyword, []):
            if next(validator.descend(instance, subschema), None) is None:
                yield subschema
    if "if" in schema:
        condition = validator.evolve(schema=schema["if"]).is_valid(instance)
        if condition:
            yield schema["if"]
        branch = "then" if condition else "else"
        if branch in schema:
            yield schema[branch]


def _unevaluated_properties(
    validator: Any, unevaluated: Any, instance: Any, schema: Mapping[str, Any]
) -> Iterator[ValidationError]:
    if not validator.is_type(instance, "object"):
        return
    evaluated = _evaluated_keys(validator, instance, schema)
    invalid = [
        key
        for key, value in instance.items()
        if key not in evaluated
        for _ in validator.descend(value, unevaluated, path=key, schema_path=key)
    ]
    if invalid:
        if unevaluated is False:
            message = "Unevaluated properties are not allowed (%s %s unexpected)"
            invalid.sort(key=str)
        else:
            message = (
                "Unevaluated properties are not valid under the given schema "
                "(%s %s unevaluated and invalid)"
            )
        yield ValidationError(message % extras_msg(invalid))


def _evolve(validator: Any, **changes: Any) -> Validator:
    # A subschema's $schema must not switch back to a validator using Python re.
    for field in fields(type(validator)):
        if field.init:
            changes.setdefault(field.alias, getattr(validator, field.name))
    evolved: Validator = HuronValidator(**changes)
    return evolved


def _regex_format(instance: Any) -> bool:
    if isinstance(instance, str):
        compile_regex(instance)
    return True


_FORMAT_CHECKER = FormatChecker()
_FORMAT_CHECKER.checks("regex", raises=ValueError)(_regex_format)
_extend: Callable[..., Any] = validators.extend
HuronValidator: Final = _extend(
    Draft202012Validator,
    {
        "pattern": _pattern,
        "patternProperties": _pattern_properties,
        "additionalProperties": _additional_properties,
        "unevaluatedProperties": _unevaluated_properties,
    },
    format_checker=_FORMAT_CHECKER,
)
HuronValidator.evolve = _evolve


def build(document: Mapping[str, Any]) -> Validator:
    """Build a checked Draft 2020-12 validator with RE2 and an offline registry.

    Malformed documents raise ``jsonschema.SchemaError`` before validation.

    Args:
        document: The JSON Schema document to apply.

    Returns:
        A validator enforcing formats and bounded regular expressions.
    """
    HuronValidator.check_schema(document, format_checker=_FORMAT_CHECKER)
    validator: Validator = HuronValidator(
        document, format_checker=_FORMAT_CHECKER, registry=Registry()
    )
    return validator
