"""``DomainError`` refuses direct instantiation; ``PathRuleViolation`` varies its code.

``PathRuleViolation`` is the one subclass whose wire code is not fixed on the
class: most raise sites keep the shared ``PATH_RULE_VIOLATION`` code, but a
few report a more specific one alongside the offending path.
"""

from __future__ import annotations

import pytest

from huron.core.foundation.errors import DomainError, PathRuleViolation

pytestmark = pytest.mark.unit


def test_domain_error_refuses_direct_instantiation() -> None:
    """Instantiating ``DomainError`` itself raises ``TypeError``, not a usable error."""
    with pytest.raises(TypeError, match="DomainError is abstract"):
        DomainError("x")


def test_path_rule_violation_defaults_to_the_shared_code() -> None:
    """With no path, ``PathRuleViolation`` keeps its default code, 400 status, and given detail."""
    error = PathRuleViolation("invalid slug: 'Bad Slug'")
    assert error.code == "PATH_RULE_VIOLATION"
    assert error.status_code == 400
    assert error.detail == "invalid slug: 'Bad Slug'"
