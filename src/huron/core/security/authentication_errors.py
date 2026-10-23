"""API-key refusals a caller can act on differently from a wrong credential.

Every credential resolver fails with :class:`huron.core.foundation.errors.AuthError`
or one of its subclasses, and the service answers with a 401 whose
problem-detail ``code`` is the class's ``code`` attribute. Catching
``AuthError`` catches every authentication failure; the two subclasses here
report an API key whose secret matched but which may no longer be used. The
class names mirror those codes on purpose, so a name in a traceback and a
code in a response point at the same condition.
"""

from __future__ import annotations

from huron.core.foundation.errors import AuthError


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
]
