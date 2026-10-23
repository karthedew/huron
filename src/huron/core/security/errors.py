"""Transport-independent Security failures: governance conflicts and grant refusals.

Stable codes are documented in design/api.html. ``ERROR_CODES`` also names
the codes of the credential and role-model failures that Security's other
modules declare; the refusals every domain shares, ``FORBIDDEN`` and
``INVALID_CREDENTIAL``, belong to :mod:`huron.core.foundation.errors`. HTTP
adapters render their status mappings; core and domain objects raise these
errors without importing FastAPI or any other application layer.
"""

from __future__ import annotations

from huron.core.foundation.errors import DomainError


class BindingExists(DomainError):
    """An identical role binding is already stored.

    A binding is unique per principal, role and scope; granting the same
    triple twice is refused rather than treated as an idempotent no-op,
    because the second grant almost always means two administrators acted
    on stale views of the same list.
    """

    code, status_code = "BINDING_EXISTS", 409


class ServiceAccountExists(DomainError):
    """That service-account name is already taken in this organization.

    Names are unique per organization, not platform-wide, so the same name
    may exist under two organizations.
    """

    code, status_code = "SERVICE_ACCOUNT_EXISTS", 409


class AttachmentExists(DomainError):
    """The policy is already attached at this scope.

    A policy attaches to a given scope at most once; attaching it again is
    a caller error, not a refresh.
    """

    code, status_code = "ATTACHMENT_EXISTS", 409


class UsernameTaken(DomainError):
    """Some principal already holds the requested subject.

    Subjects are unique across every principal kind, so a username clashes
    with an existing user and with a service account alike.
    """

    code, status_code = "USERNAME_TAKEN", 409


class PrincipalKindMismatch(DomainError):
    """The addressed principal exists but is not a user.

    The user-management routes act only on ``user`` principals; pointing
    one at a service account is a conflict rather than a 404, because the
    id is real and the caller should learn what it actually names.
    """

    code, status_code = "PRINCIPAL_KIND_MISMATCH", 409


class OidcNotConfigured(DomainError):
    """The OIDC routes are mounted, but no identity provider is configured.

    The routes exist in every deployment so the API surface is stable;
    without ``HURON_OIDC__*`` settings they answer 404 to say that this
    login method is absent here, not broken.
    """

    code, status_code = "OIDC_NOT_CONFIGURED", 404


class GrantExpired(DomainError):
    """The data-access grant has expired."""

    code, status_code = "GRANT_EXPIRED", 401


class GrantScopeExceeded(DomainError):
    """The requested access exceeds the grant."""

    code, status_code = "GRANT_SCOPE_EXCEEDED", 403


class InputNotReadable(DomainError):
    """The principal cannot read a referenced input."""

    code, status_code = "INPUT_NOT_READABLE", 403


class ClassificationExceeded(DomainError):
    """The data classification exceeds the grant."""

    code, status_code = "CLASSIFICATION_EXCEEDED", 403


__all__ = [
    "ERROR_CODES",
    "AttachmentExists",
    "BindingExists",
    "ClassificationExceeded",
    "GrantExpired",
    "GrantScopeExceeded",
    "InputNotReadable",
    "OidcNotConfigured",
    "PrincipalKindMismatch",
    "ServiceAccountExists",
    "UsernameTaken",
]

ERROR_CODES = frozenset(
    {
        "BINDING_EXISTS",
        "SERVICE_ACCOUNT_EXISTS",
        "ATTACHMENT_EXISTS",
        "USERNAME_TAKEN",
        "PRINCIPAL_KIND_MISMATCH",
        "OIDC_NOT_CONFIGURED",
        "GRANT_EXPIRED",
        "GRANT_SCOPE_EXCEEDED",
        "INPUT_NOT_READABLE",
        "CLASSIFICATION_EXCEEDED",
        "APIKEY_EXPIRED",
        "APIKEY_REVOKED",
        "PASSWORD_REJECTED",
        "SESSION_EXPIRED",
        "SESSION_REVOKED",
        "UNKNOWN_ROLE",
        "PRINCIPAL_KIND_NOT_ALLOWED",
        "SCOPE_NOT_BINDABLE",
    }
)
