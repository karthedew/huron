"""Stable authentication error codes shared by every credential resolver.

Every resolver in this package fails the same way: it raises one of these
classes, and the service answers with a 401 whose problem-detail ``code``
is the class's ``code`` attribute. The class names mirror those codes on
purpose, so a name in a traceback and a code in a response point at the
same condition. Catching :class:`AuthError` catches every authentication
failure; the subclasses exist for the conditions a caller can act on
differently from "the credential is wrong".
"""

from __future__ import annotations


class AuthError(Exception):
    """A credential could not be resolved to a principal.

    The base of every authentication failure and the ``INVALID_CREDENTIAL``
    condition in its own right: a malformed token, an unknown key or
    session id, a secret that does not match, a signature or claim the
    verifier rejects, or no credential at all. A resolver raises it
    directly whenever nothing more specific is true, and the message is
    the only place it says which of those cases applied.
    """

    code = "INVALID_CREDENTIAL"


class ApiKeyExpired(AuthError):
    """An API key whose secret matched but whose ``expires_at`` has passed.

    The ``APIKEY_EXPIRED`` condition. It is raised only once the secret has
    been verified, so a caller guessing key ids never sees it, and a
    revoked key that has also expired reports revocation instead.
    """

    code = "APIKEY_EXPIRED"


class ApiKeyRevoked(AuthError):
    """An API key whose secret matched but which has been revoked.

    The ``APIKEY_REVOKED`` condition: ``revoked_at`` is set on the record,
    which disabling the owning service account does for every key it
    holds. Like expiry, it is reported only after the secret has been
    verified, and it takes precedence over expiry.
    """

    code = "APIKEY_REVOKED"


__all__ = [
    "ApiKeyExpired",
    "ApiKeyRevoked",
    "AuthError",
]
