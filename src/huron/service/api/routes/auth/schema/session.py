"""Response bodies owned by ``endpoints/session.py``."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel


class ScopeRoles(BaseModel):
    """The capabilities this caller holds at one scope.

    Grouped from the same compiled ``Binding`` set ``rbac.decide`` evaluates
    for every guarded route, so this reports exactly what the guard chain
    would allow at this scope rather than a role name reconstructed after
    the fact - a compiled binding carries capability codes, not the role it
    was compiled from, and re-deriving one would risk drifting from what is
    actually enforced.
    """

    scope_type: str
    scope_id: UUID | None
    roles: list[str]


class SessionInfo(BaseModel):
    """The answer to "who am I, and how was I authenticated".

    Served by the unversioned ``GET /auth/session`` rather than a
    versioned resource route: identity introspection is a login concern,
    not a v1 resource. ``effective_roles`` is resolved from the same
    binding set the authorization guards consult, so what a caller is told
    it may do and what it is actually allowed to do cannot drift apart.
    ``csrf_token``/``expires_at`` are only ever set for a cookie-authenticated
    caller; a bearer credential carries no server-side session to report.
    """

    subject: str
    kind: str
    groups: list[str]
    authentication_method: str
    effective_roles: list[ScopeRoles]
    csrf_token: str | None
    expires_at: datetime | None


class ProviderInfo(BaseModel):
    """What the login page renders from: the credential methods this deployment accepts.

    Served unauthenticated by design - the page has no principal yet when
    it needs this. ``oidc_start_url`` is the path that begins a browser
    login when an identity provider is configured, and ``null`` when
    ``oidc`` is false.
    """

    password: bool
    oidc: bool
    oidc_start_url: str | None
