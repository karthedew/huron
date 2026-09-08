"""Transport-independent catalog and authorization failures.

Stable codes are documented in design/api.html. HTTP adapters render their
status mappings; core and domain objects raise these errors without importing
FastAPI or any other application layer.
"""

from __future__ import annotations

from huron.pkg.catalog.errors import DomainError


class Forbidden(DomainError):
    """The caller is authenticated but its role bindings do not allow this.

    Raised by the binding check once the principal is known, so it is
    always a 403 and never a 401: the credential was fine, the authority
    was not. The service-account routes raise it too, for an account that
    has been disabled.
    """

    code, status_code = "FORBIDDEN", 403


class SlugExists(DomainError):
    """An organization, project or dataset already holds this slug.

    Slugs are unique among siblings - organizations platform-wide, projects
    within their organization, datasets within their project - and are
    immutable once assigned, so the caller must choose another rather than
    expect the existing one to be replaced.
    """

    code, status_code = "SLUG_EXISTS", 409


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


class DependencyUnavailable(DomainError):
    """A dependency ``/readyz`` probed did not answer.

    The one 503 the service produces on purpose: an orchestrator acts on
    it by taking the instance out of rotation. ``context["checks"]`` names
    each failed dependency and the reason it gave.
    """

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
