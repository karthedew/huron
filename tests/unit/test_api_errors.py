"""Proves each service-tier error's stable ``code``/``status_code`` pair and default detail.

Every class here is a ``DomainError`` subclass whose ``code``/``status_code``
pair is the one row of the error table a raiser gets by construction.
"""

from __future__ import annotations

import pytest

from huron.core.foundation.errors import DependencyUnavailable, DomainError, Forbidden
from huron.core.hierarchy.errors import SlugExists
from huron.core.security.errors import (
    AttachmentExists,
    BindingExists,
    PrincipalKindMismatch,
    RotationRefused,
    ServiceAccountExists,
    SigningKeyUnavailable,
    UsernameTaken,
)

pytestmark = pytest.mark.unit

_CLASSES = [
    (SigningKeyUnavailable, "SIGNING_KEY_UNAVAILABLE", 503),
    (RotationRefused, "ROTATION_REFUSED", 409),
    (Forbidden, "FORBIDDEN", 403),
    (SlugExists, "SLUG_EXISTS", 409),
    (BindingExists, "BINDING_EXISTS", 409),
    (ServiceAccountExists, "SERVICE_ACCOUNT_EXISTS", 409),
    (AttachmentExists, "ATTACHMENT_EXISTS", 409),
    (UsernameTaken, "USERNAME_TAKEN", 409),
    (PrincipalKindMismatch, "PRINCIPAL_KIND_MISMATCH", 409),
    (DependencyUnavailable, "DEPENDENCY_UNAVAILABLE", 503),
]


@pytest.mark.parametrize(("error_type", "code", "status_code"), _CLASSES)
def test_each_error_carries_its_documented_code_and_status(
    error_type: type[DomainError], code: str, status_code: int
) -> None:
    """Each error type carries its documented ``code``/``status_code`` and a given detail."""
    instance = error_type("something went wrong")
    assert isinstance(instance, DomainError)
    assert instance.code == code
    assert instance.status_code == status_code
    assert instance.detail == "something went wrong"


@pytest.mark.parametrize(("error_type", "code", "status_code"), _CLASSES)
def test_a_detail_defaults_to_the_code_in_lowercase_words(
    error_type: type[DomainError], code: str, status_code: int
) -> None:
    """With no detail given, an error's detail defaults to its code in lowercase words."""
    instance = error_type()
    assert instance.detail == code.replace("_", " ").lower()


def test_context_travels_into_as_problem() -> None:
    """``as_problem`` carries the constructor's ``context`` through into the problem body."""
    instance = SlugExists("astro already exists", context={"slug": "astro"})
    problem = instance.as_problem()
    assert problem["context"] == {"slug": "astro"}
    assert problem["code"] == "SLUG_EXISTS"
    assert problem["status"] == 409


def test_signing_failures_distinguish_retryable_unavailability_from_refusal() -> None:
    """Unavailable signing requests may retry after 30 seconds; refusals promise no retry."""
    assert DependencyUnavailable.retry_after == 30
    assert SigningKeyUnavailable.retry_after == 30
    assert RotationRefused.retry_after is None
