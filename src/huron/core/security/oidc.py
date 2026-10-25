"""OIDC provider discovery and bearer-token verification."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

import httpx
import jwt

from huron.core.foundation.errors import AuthError

from .principal import Principal

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping


class OidcResolver:
    """Resolve a token after an injected verifier has validated its signature.

    The resolver owns no cryptography: ``verify`` is whatever turns a raw
    token into trusted claims (a :class:`JwksVerifier` in production), and
    the resolver only maps those claims to a :class:`Principal`. The split
    keeps the claim-shape rules testable without keys and lets the
    composition root choose which claims name the subject and the groups.
    """

    def __init__(
        self,
        verify: Callable[[str], Mapping[str, object]],
        *,
        subject_claim: str = "sub",
        groups_claim: str = "groups",
    ):
        """Bind the resolver to a verifier and the claims it reads.

        Args:
            verify: Turns a raw bearer token into its claims, raising
                :class:`AuthError` for a token that must not be trusted.
            subject_claim: The claim naming the principal's subject.
            groups_claim: The claim carrying the principal's groups as a
                list of strings.
        """
        self.verify = verify
        self.subject_claim = subject_claim
        self.groups_claim = groups_claim

    async def resolve(self, credential: str) -> Principal:
        """Verify a bearer token and map its claims to a principal.

        The subject claim must be a string and the groups claim, when
        present, a list of strings; a missing groups claim resolves to an
        empty set rather than an error, so a provider that issues none
        still yields a usable principal. A token the verifier rejects
        propagates its error unchanged.

        Args:
            credential: The raw bearer token.

        Returns:
            A principal with the token's subject and groups and
            ``authentication_method`` ``"oidc"``; no scopes and no project
            restriction.

        Raises:
            AuthError: If the subject claim is not a string, or the groups
                claim is present but not a list of strings.
        """
        claims = self.verify(credential)
        subject = claims.get(self.subject_claim)
        groups = claims.get(self.groups_claim, [])
        if (
            not isinstance(subject, str)
            or not isinstance(groups, list)
            or not all(isinstance(group, str) for group in groups)
        ):
            raise AuthError("OIDC token has invalid principal claims")
        return Principal(
            subject=subject,
            groups=frozenset(groups),
            authentication_method="oidc",
        )


class JwksVerifier:
    """Validate signature, issuer, audience, and expiry against the IdP's JWKS.

    Signing keys are fetched from the JWKS URL on demand and cached for
    five minutes, so a key rotation is picked up without a restart and a
    burst of requests does not become a burst of key fetches. Only the
    asymmetric ``RS256`` and ``ES256`` algorithms are accepted, which
    rules out a token that names an HMAC algorithm and uses the public
    key as its secret. ``exp``, ``iat`` and ``sub`` are required claims.
    """

    def __init__(self, *, issuer: str, audience: str, jwks_url: str) -> None:
        """Configure the verifier for one issuer and one audience.

        Args:
            issuer: The exact ``iss`` a token must carry.
            audience: The ``aud`` a token must be issued for - the client
                id when verifying ID tokens.
            jwks_url: Where the issuer publishes its signing keys.
        """
        self.issuer = issuer
        self.audience = audience
        self._jwks = jwt.PyJWKClient(jwks_url, cache_keys=True, lifespan=300)

    def __call__(self, token: str) -> Mapping[str, object]:
        """Verify a token and return its claims.

        Args:
            token: The compact-serialized JWT.

        Returns:
            The verified claims, exactly as the token carries them.

        Raises:
            AuthError: If no signing key matches, the signature, issuer,
                audience or expiry does not check out, or a required claim
                is missing - every ``jwt.PyJWTError`` is wrapped so the
                caller sees one error type.
        """
        try:
            key = self._jwks.get_signing_key_from_jwt(token).key
            return jwt.decode(
                token,
                key,
                algorithms=["RS256", "ES256"],
                issuer=self.issuer,
                audience=self.audience,
                options={"require": ["exp", "iat", "sub"]},
            )
        except jwt.PyJWTError as error:
            raise AuthError(f"OIDC token rejected: {error}") from error


@dataclass(frozen=True, slots=True)
class OidcProviderConfig:
    """The endpoints of one identity provider, as its discovery document publishes them.

    Filled by :meth:`OidcClient.discover` from the provider's
    ``/.well-known/openid-configuration``. ``end_session_endpoint`` is
    optional in the specification and None when the provider does not
    advertise one.
    """

    issuer: str
    authorization_endpoint: str
    token_endpoint: str
    jwks_uri: str
    end_session_endpoint: str | None


@dataclass(frozen=True, slots=True)
class OidcUser:
    """Verified provider identity fields used to upsert a principal.

    ``idp_subject`` is the provider's stable ``sub`` and becomes both the
    principal's ``subject`` and its ``idp_subject``. ``display_name``
    falls back to the subject when the provider sends no ``name``,
    ``email`` is None when absent, and ``groups`` is empty when the
    groups claim is missing or malformed - the mapping never fails on an
    optional claim.
    """

    idp_subject: str
    display_name: str
    email: str | None
    groups: frozenset[str]


_REQUIRED_DISCOVERY_FIELDS: tuple[str, ...] = (
    "issuer",
    "authorization_endpoint",
    "token_endpoint",
    "jwks_uri",
)


def _validate_discovery_document(document: Mapping[str, object], issuer: str) -> None:
    """Confirm a discovery document carries every endpoint a client needs.

    Args:
        document: The parsed JSON body of the provider's well-known
            discovery document.
        issuer: The issuer this client was configured to discover.

    Raises:
        AuthError: If a required field is absent from ``document``, or
            ``document["issuer"]`` does not equal ``issuer``.
    """
    for field in _REQUIRED_DISCOVERY_FIELDS:
        if field not in document:
            raise AuthError(f"OIDC discovery document for issuer {issuer!r} is missing {field!r}")
    if document["issuer"] != issuer:
        raise AuthError(
            f"OIDC discovery document for issuer {issuer!r} reports issuer {document['issuer']!r}"
        )


class OidcClient:
    """Discover the endpoints published by one configured provider."""

    def __init__(self, provider: OidcProviderConfig) -> None:
        """Keep the validated provider endpoints.

        Args:
            provider: The discovered provider document.
        """
        self._provider = provider

    @classmethod
    async def discover(
        cls,
        http: httpx.AsyncClient,
        issuer: str,
    ) -> OidcClient:
        """Fetch ``{issuer}/.well-known/openid-configuration`` and build a client.

        The well-known path is appended to ``issuer`` verbatim, and the
        document's ``issuer`` field must equal it exactly - a provider
        that serves a different issuer's document (a misconfigured proxy,
        or a copy-pasted well-known URL) is refused rather than silently
        trusted.

        Args:
            http: The async HTTP client used for discovery; the caller owns its lifetime.
            issuer: The provider's issuer URL.

        Returns:
            A client configured from the discovery document.

        Raises:
            AuthError: If the discovery request returns an error status,
                the document is missing a required endpoint, or the
                document's ``issuer`` does not match ``issuer``.
        """
        response = await http.get(f"{issuer}/.well-known/openid-configuration")
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as error:
            raise AuthError(f"OIDC discovery failed for issuer {issuer!r}: {error}") from error
        document = response.json()
        _validate_discovery_document(document, issuer)
        provider = OidcProviderConfig(
            issuer=document["issuer"],
            authorization_endpoint=document["authorization_endpoint"],
            token_endpoint=document["token_endpoint"],
            jwks_uri=document["jwks_uri"],
            end_session_endpoint=document.get("end_session_endpoint"),
        )
        return cls(provider)

    @property
    def provider(self) -> OidcProviderConfig:
        """The discovered provider document.

        The composition root needs the JWKS endpoint to build the
        bearer-token verifier.
        """
        return self._provider


__all__ = [
    "JwksVerifier",
    "OidcClient",
    "OidcProviderConfig",
    "OidcResolver",
    "OidcUser",
]
