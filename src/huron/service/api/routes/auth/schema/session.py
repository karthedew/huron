"""Response bodies owned by ``endpoints/session.py``."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class SessionInfo(BaseModel):
    """The answer to "who am I, and how was I authenticated" - moved from
    ``GET /api/v1/auth/whoami`` to the unversioned ``GET /auth/session``.
    ``csrf_token``/``expires_at`` are only ever set for a cookie-authenticated
    caller; a bearer credential carries no server-side session to report."""

    subject: str
    kind: str
    groups: list[str]
    authentication_method: str
    csrf_token: str | None
    expires_at: datetime | None


class ProviderInfo(BaseModel):
    """What the login page renders from - which credential methods this
    deployment accepts, unauthenticated by design."""

    password: bool
    oidc: bool
    oidc_start_url: str | None
