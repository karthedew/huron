"""Every way of authenticating, resolved to one Principal.

The package owns authentication and nothing else, and is free of any web
framework. Its public surface, re-exported here, is: the credential
resolvers (``ApiKeyResolver``, ``SessionResolver``, ``OidcResolver`` with
``JwksVerifier``, ``DevHeaderResolver``) and the ``OidcClient``/``LoginFlow``
pair behind the browser login; the store protocols with their in-memory
implementations and the records they hold (API keys, sessions, password
credentials, principals); the ``create_*``/``parse_*`` helpers that mint
and split credentials; the argon2 password functions and
``MIN_PASSWORD_LENGTH``; the session lifetimes ``IDLE_TTL``,
``ABSOLUTE_TTL`` and ``TOUCH_INTERVAL``; the stable errors; and
``Principal`` itself.
"""

from .apikeys import (
    ApiKeyRecord,
    ApiKeyResolver,
    ApiKeyStore,
    MemoryApiKeyStore,
    create_api_key,
    parse_api_key,
)
from .dev import DevHeaderResolver
from .errors import ApiKeyExpired, ApiKeyRevoked, AuthError
from .oidc import (
    JwksVerifier,
    LoginFlow,
    OidcClient,
    OidcProviderConfig,
    OidcResolver,
    OidcUser,
    code_challenge_s256,
)
from .password import (
    MIN_PASSWORD_LENGTH,
    CredentialRecord,
    CredentialStore,
    MemoryCredentialStore,
    PasswordRejected,
    hash_password,
    make_credential,
    needs_rehash,
    verify_password,
)
from .principal import Principal
from .principals import (
    MemoryPrincipalStore,
    PrincipalRecord,
    PrincipalStore,
    PrincipalSubjectExists,
)
from .sessions import (
    ABSOLUTE_TTL,
    IDLE_TTL,
    TOUCH_INTERVAL,
    MemorySessionStore,
    SessionExpired,
    SessionRecord,
    SessionResolver,
    SessionRevoked,
    SessionStore,
    create_session,
    parse_session_token,
)

__all__ = [
    "ABSOLUTE_TTL",
    "IDLE_TTL",
    "MIN_PASSWORD_LENGTH",
    "TOUCH_INTERVAL",
    "ApiKeyExpired",
    "ApiKeyRecord",
    "ApiKeyResolver",
    "ApiKeyRevoked",
    "ApiKeyStore",
    "AuthError",
    "CredentialRecord",
    "CredentialStore",
    "DevHeaderResolver",
    "JwksVerifier",
    "LoginFlow",
    "MemoryApiKeyStore",
    "MemoryCredentialStore",
    "MemoryPrincipalStore",
    "MemorySessionStore",
    "OidcClient",
    "OidcProviderConfig",
    "OidcResolver",
    "OidcUser",
    "PasswordRejected",
    "Principal",
    "PrincipalRecord",
    "PrincipalStore",
    "PrincipalSubjectExists",
    "SessionExpired",
    "SessionRecord",
    "SessionResolver",
    "SessionRevoked",
    "SessionStore",
    "code_challenge_s256",
    "create_api_key",
    "create_session",
    "hash_password",
    "make_credential",
    "needs_rehash",
    "parse_api_key",
    "parse_session_token",
    "verify_password",
]
