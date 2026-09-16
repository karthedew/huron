"""The cookies this service issues, and the attributes that define them.

A cookie is cleared only if the attributes on the clearing response match
the ones it was set with; a session cookie is read only under the name it
was written with. Both are properties of one object here rather than
agreements between four call sites.
"""

from __future__ import annotations

from dataclasses import dataclass

from fastapi import Request, Response

from huron.core.security.sessions import ABSOLUTE_TTL

from ..settings import ApiSettings

#: The pending-login cookie's lifetime, which doubles as ``LoginFlow.decode``'s
#: ``max_age``: a flow the browser still holds a cookie for is never rejected as
#: stale, and a flow it has forgotten is never accepted.
LOGIN_FLOW_MAX_AGE = 600


@dataclass(frozen=True, slots=True)
class CookieSpec:
    """One cookie, fully described.

    Frozen: an issued cookie and the response that clears it must not be
    able to disagree about name, path or flags. The flags that are not
    fields - ``HttpOnly`` and ``SameSite=Lax`` - are fixed for every cookie
    the service issues: no script may read a session or login-flow cookie,
    and no cross-site POST may carry one.
    """

    name: str
    path: str
    max_age: int
    secure: bool

    def issue(self, response: Response, value: str) -> None:
        """Set the cookie on a response with this spec's attributes.

        Args:
            response: The response the ``Set-Cookie`` header is added to.
            value: The cookie's value - a session token or an encoded login
                flow - stored as given.
        """
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
        """Clear the cookie, using the attributes it was issued with.

        A browser drops a cookie only when the clearing ``Set-Cookie``
        matches the original's name, path and flags, which is why this
        reads them from the same spec ``issue`` used.

        Args:
            response: The response the expiring ``Set-Cookie`` header is
                added to.
        """
        response.delete_cookie(
            self.name,
            path=self.path,
            httponly=True,
            samesite="lax",
            secure=self.secure,
        )

    def read(self, request: Request) -> str | None:
        """Return the cookie's value from a request, if the browser sent it.

        Args:
            request: The request whose cookie jar is consulted.

        Returns:
            The value as sent, unverified, or ``None`` when the request
            carries no cookie of this name.
        """
        return request.cookies.get(self.name)


def session_cookie(settings: ApiSettings) -> CookieSpec:
    """Describe the session cookie: configurable name, site-wide path, absolute TTL.

    The cookie's lifetime is the session's absolute TTL, so the browser
    forgets it no later than the server would refuse it. It is ``Secure``
    everywhere but development, where the web app is served over plain
    HTTP.

    Args:
        settings: Supplies ``session_cookie_name`` and the environment that
            decides the ``Secure`` flag.

    Returns:
        The spec every session-issuing, session-reading and logout path
        shares.
    """
    return CookieSpec(
        name=settings.session_cookie_name,
        path="/",
        max_age=int(ABSOLUTE_TTL.total_seconds()),
        secure=settings.env != "development",
    )


def login_flow_cookie(settings: ApiSettings) -> CookieSpec:
    """Describe the transient OIDC pending-login cookie.

    Its name is not configurable - it never leaves ``/auth`` - and it
    carries the PKCE verifier, nonce and state, HMAC-signed, between
    ``/auth/oidc/start`` and the callback. Its ``max_age`` is
    ``LOGIN_FLOW_MAX_AGE``, the same bound the flow decoder applies, so the
    browser and the server agree on when a pending login is stale.

    Args:
        settings: Read for the environment, which decides the ``Secure``
            flag; nothing else about this cookie is configurable.

    Returns:
        The spec the OIDC start and callback routes share.
    """
    return CookieSpec(
        name="huron_login",
        path="/auth",
        max_age=LOGIN_FLOW_MAX_AGE,
        secure=settings.env != "development",
    )
