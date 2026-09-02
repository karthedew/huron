"""The service tier's own stable errors: every class here is a
``DomainError`` subclass whose ``code``/``status_code`` pair is the one row
of the error table a raiser gets by construction."""

from __future__ import annotations

import pytest

from huron.pkg.catalog.errors import DomainError
from huron.service.api.errors import (
    AttachmentExists,
    BindingExists,
    DependencyUnavailable,
    Forbidden,
    OidcNotConfigured,
    PrincipalKindMismatch,
    ServiceAccountExists,
    SlugExists,
    UsernameTaken,
)

pytestmark = pytest.mark.unit

_CLASSES = [
    (Forbidden, "FORBIDDEN", 403),
    (SlugExists, "SLUG_EXISTS", 409),
    (BindingExists, "BINDING_EXISTS", 409),
    (ServiceAccountExists, "SERVICE_ACCOUNT_EXISTS", 409),
    (AttachmentExists, "ATTACHMENT_EXISTS", 409),
    (UsernameTaken, "USERNAME_TAKEN", 409),
    (PrincipalKindMismatch, "PRINCIPAL_KIND_MISMATCH", 409),
    (OidcNotConfigured, "OIDC_NOT_CONFIGURED", 404),
    (DependencyUnavailable, "DEPENDENCY_UNAVAILABLE", 503),
]


@pytest.mark.parametrize(("error_type", "code", "status_code"), _CLASSES)
def test_each_error_carries_its_documented_code_and_status(
    error_type: type[DomainError], code: str, status_code: int
) -> None:
    instance = error_type("something went wrong")
    assert isinstance(instance, DomainError)
    assert instance.code == code
    assert instance.status_code == status_code
    assert instance.detail == "something went wrong"


@pytest.mark.parametrize(("error_type", "code", "status_code"), _CLASSES)
def test_a_detail_defaults_to_the_code_in_lowercase_words(
    error_type: type[DomainError], code: str, status_code: int
) -> None:
    instance = error_type()
    assert instance.detail == code.replace("_", " ").lower()


def test_context_travels_into_as_problem() -> None:
    instance = SlugExists("astro already exists", context={"slug": "astro"})
    problem = instance.as_problem()
    assert problem["context"] == {"slug": "astro"}
    assert problem["code"] == "SLUG_EXISTS"
    assert problem["status"] == 409
