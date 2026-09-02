"""Stable errors the service tier raises, with the codes clients switch on.

Every class here is a ``DomainError`` subclass with a code that is a row in
``design/api.html`` §7. The tier raises no untyped failure: a condition
without a code is a bug, and a bug is a 500.

Pure - this module imports only ``huron.pkg.catalog.errors``, so
``records.py`` and ``repository.py`` can import it without acquiring
FastAPI.
"""

from __future__ import annotations

from huron.pkg.catalog.errors import DomainError


class Forbidden(DomainError):
    code, status_code = "FORBIDDEN", 403


class SlugExists(DomainError):
    code, status_code = "SLUG_EXISTS", 409


class BindingExists(DomainError):
    code, status_code = "BINDING_EXISTS", 409


class ServiceAccountExists(DomainError):
    code, status_code = "SERVICE_ACCOUNT_EXISTS", 409


class AttachmentExists(DomainError):
    code, status_code = "ATTACHMENT_EXISTS", 409


class UsernameTaken(DomainError):
    code, status_code = "USERNAME_TAKEN", 409


class PrincipalKindMismatch(DomainError):
    code, status_code = "PRINCIPAL_KIND_MISMATCH", 409


class OidcNotConfigured(DomainError):
    code, status_code = "OIDC_NOT_CONFIGURED", 404


class DependencyUnavailable(DomainError):
    code, status_code = "DEPENDENCY_UNAVAILABLE", 503


__all__ = [
    "AttachmentExists",
    "BindingExists",
    "DependencyUnavailable",
    "Forbidden",
    "OidcNotConfigured",
    "PrincipalKindMismatch",
    "ServiceAccountExists",
    "SlugExists",
    "UsernameTaken",
]
