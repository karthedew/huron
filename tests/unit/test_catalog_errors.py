"""``DomainError`` itself: it refuses direct instantiation, and
``PathRuleViolation``'s per-instance code - the one subclass whose wire
code isn't fixed at the class."""

from __future__ import annotations

import pytest

from huron.pkg.catalog.errors import DomainError, PathRuleViolation

pytestmark = pytest.mark.unit


def test_domain_error_refuses_direct_instantiation() -> None:
    with pytest.raises(TypeError, match="DomainError is abstract"):
        DomainError("x")


def test_path_rule_violation_defaults_to_the_shared_code() -> None:
    error = PathRuleViolation("invalid slug: 'Bad Slug'")
    assert error.code == "PATH_RULE_VIOLATION"
    assert error.status_code == 400
    assert error.detail == "invalid slug: 'Bad Slug'"


def test_path_rule_violation_carries_a_more_specific_code_with_a_path() -> None:
    error = PathRuleViolation("PATH_TOO_LONG", "a/very/long/path.txt")
    assert error.code == "PATH_TOO_LONG"
    assert error.detail == "PATH_TOO_LONG: 'a/very/long/path.txt'"
    assert error.context == {"path": "a/very/long/path.txt"}
