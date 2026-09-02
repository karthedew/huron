"""The cookies this service issues, and the attributes that define them.

A cookie is cleared only if the attributes on the clearing response match
the ones it was set with; a session cookie is read only under the name it
was written with. Both are properties of one object here rather than
agreements between four call sites.
"""

from __future__ import annotations

from dataclasses import dataclass

from fastapi import Request, Response

from huron.pkg.auth import ABSOLUTE_TTL

from ..settings import ApiSettings

#: The pending-login cookie's lifetime, which doubles as ``LoginFlow.decode``'s
#: ``max_age``: a flow the browser still holds a cookie for is never rejected as
#: stale, and a flow it has forgotten is never accepted.
LOGIN_FLOW_MAX_AGE = 600


@dataclass(frozen=True, slots=True)
class CookieSpec:
    """One cookie, fully described. Frozen: an issued cookie and the response
    that clears it must not be able to disagree about name, path or flags."""

    name: str
    path: str
    max_age: int
    secure: bool

    def issue(self, response: Response, value: str) -> None:
        response.set_cookie(
            self.name,
            value,
            max_age=self.max_age,
            path=self.path,
            httponly=True,
            samesite="lax",
            secure=self.secure,
        )

    def revoke(self, response: Response) -> None:
        response.delete_cookie(
            self.name,
            path=self.path,
            httponly=True,
            samesite="lax",
            secure=self.secure,
        )

    def read(self, request: Request) -> str | None:
        return request.cookies.get(self.name)


def session_cookie(settings: ApiSettings) -> CookieSpec:
    """The session cookie: configurable name, site-wide path, absolute TTL."""
    return CookieSpec(
        name=settings.session_cookie_name,
        path="/",
        max_age=int(ABSOLUTE_TTL.total_seconds()),
        secure=settings.env != "development",
    )


def login_flow_cookie(settings: ApiSettings) -> CookieSpec:
    """The transient OIDC pending-login cookie. Its name is not configurable -
    it never leaves ``/auth`` - and it carries the PKCE verifier, nonce and
    state, HMAC-signed, between ``/auth/oidc/start`` and the callback."""
    return CookieSpec(
        name="huron_login",
        path="/auth",
        max_age=LOGIN_FLOW_MAX_AGE,
        secure=settings.env != "development",
    )
